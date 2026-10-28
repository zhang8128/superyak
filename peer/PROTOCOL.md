# Superyak peer protocol v1

This implementation exchanges selected plaintext over verified TLS between explicitly
paired hosts. Each host's operator controls its SQLite database and keys. TLS is
not end-to-end encryption against either hosting operator. No broker, registry,
automatic discovery, identity merge, remote login or model call is involved.

## Identity and pairing

`PeerIdentity.load_or_create(data_dir, *, hosts=('localhost','127.0.0.1'))` persists
an Ed25519 key and a separate EC P-256 TLS key/certificate in private state. The
peer ID is the lowercase hex SHA-256 of the 32 raw Ed25519 public-key bytes.
`identity.json`, `peer-key.pem` and `peer-cert.pem` are created with mode 0600;
state is mode 0700. Symlinked identity files are refused. Existing identity and
TLS files must agree; startup does not silently regenerate or rotate them.
Generated certificates have the supplied DNS/IP SANs and a 365-day validity.
Create the card for the desired endpoint before first serving that state so its
hostname is included in the generated certificate. Changing a hostname later
requires an explicit future migration; automatic rotation is intentionally absent.

A public card is exactly:

```json
{
  "version": 1,
  "peer_id": "64 lowercase hex characters",
  "signing_key": "base64 raw Ed25519 public key",
  "certificate": "PEM X.509 certificate",
  "fingerprint": "lowercase SHA-256 hex of DER certificate",
  "endpoint": "https://hostname:port",
  "participant": {"id": "origin-local account ID", "name": "Display name"}
}
```

Endpoint length is at most 2048 characters; participant ID is 1–64 ASCII letters,
digits, underscore or hyphen; name is at most 200 characters; certificate is at
most 16384 characters. Endpoints must be HTTPS origins without path (including
trailing slash), userinfo, query, fragment or whitespace. No redirects are followed.
Only a local owner can preview/import/pair/unpair. The participant can export their
own card. Import verifies key→peer-ID and certificate→fingerprint bindings. The card is
not a central identity assertion.

**The pairing code** is the first 32 lowercase hex characters of the SHA-256 of the
whole canonical card, `participant` included, shown in groups of four. The exporting
side shows it (`card` on stderr, `/api/connections/code`, "Show my peer card"); the
importing side never shows it before it is typed. Pairing takes the code **typed** by a
person reading it off the exporting machine's own screen: in the browser's box, never
pre-filled, or at `pair --as` on a real terminal. A wrong code is refused, and only then
names the card's code; a request carrying only the old `fingerprint` pairs nothing. The
code proves the card in hand matches the card on that screen, the fingerprint
included. It does not prove a person typed it: a pty wrapper or an admin session's own
client could supply it, which is why typing it is a person's act by rule (CLAUDE.md),
not by mechanism alone. `connections` lists each contact's code and whether a typed code
confirmed that card. Pairing authorizes signed ingress from explicitly
imported participants; it does not grant content access. Import each desired
participant's card separately. Cards for a known peer cannot change its URL, key,
certificate or fingerprint, even after unpairing. Name corrections preserve IDs.
Unpairing a contact disconnects that entire peer, including its other contacts,
and suppresses all hosted received content from it. Re-pairing does not restore
old bodies; only a newer valid release may become visible again.

## Wire request

POST `/federation/events` over HTTPS, `Content-Type: application/json`. No cookies
or browser Origin grant peer authority. Host must be explicitly configured.
Maximum whole envelope/request is 6 MiB, bounded before JSON parsing. Duplicate
JSON object keys, non-finite numbers, invalid UTF-8/surrogates and non-object JSON
are rejected. JSON is canonicalized with sorted keys, compact separators,
`ensure_ascii=False`, `allow_nan=False`, then UTF-8 encoded.

The signed envelope has exactly these fields:

```json
{
  "version": 1,
  "event_id": "stable unique ID",
  "origin": "signing peer ID",
  "destination": "receiving peer ID",
  "actor": {"peer": "same as origin", "id": "imported origin-local participant ID"},
  "resource_id": "origin-local resource ID",
  "revision": 1,
  "action": "layer.release",
  "recipients": ["receiving host's local account ID"],
  "payload": {},
  "payload_digest": "SHA-256 hex of canonical payload bytes",
  "signature": "base64 Ed25519 signature"
}
```

Signature covers the canonical entire envelope with only `signature` omitted.
Thus destination, actor namespace, recipients, action, revision, payload and digest
are bound. Resource/event IDs are 1–100 ASCII letters/digits/underscore/hyphen;
revision is an integer in 1..2^53. Recipient list contains 1–100 distinct local IDs.
Current sender emits one recipient per event. Unknown peers, unpaired peers,
unimported actors and unknown recipients fail. Every accepted event is recorded
atomically with application in durable `receipts(origin,event_id,digest,created)`.
Exact repeats return `{ok:true,duplicate:true}` without reapplying; reuse of an ID
with different valid signed bytes returns 409. Receipts have no message/release
bodies and are retained without an expiry that could revive stale events.

Success is HTTP 200 `{ok:true,duplicate:false}` (or duplicate true). Malformed
payloads return 400, authentication/membership failures 403, missing resources
404, replay/revision conflicts 409, oversized input 413. Public-safe error JSON is
`{error:message}`. An acknowledgement is trusted through the pinned HTTPS channel;
it is not separately signed.

## Actions and authority

`layer.release`: `payload={title,body,attachment_ids,files}`. Title ≤200 characters,
body ≤100000; no draft, audience-management lists, frozen space memberships,
private citation targets or account metadata. Attribution comes from the signed
actor and origin. Files are explicit selected owned attachments only, each
`{id,name,media_type,digest,size,content_base64}`. All file bytes together must be
≤4 MiB; selecting a larger remote draft/release is rejected before activation.
Receiver revalidates upload type/magic, filename, decoded size and SHA-256 digest.
Current upload types include UTF-8 CSV and JSON datasets; receivers predating
that support reject those file types. Both peers need compatible type support
before exchanging those attachments. Dataset bytes are preserved exactly.
Files are stored inside the received resource, never in its local owned-file table.
Download requires that exact still-active received layer and current recipient.
No received-file or received-layer forwarding API exists. Corrections are higher
resource revisions using the same release action.

`layer.withdraw`: empty payload. Higher revisions replace received layer payload
with NULL; stale/equal-tombstoned revisions cannot restore a body, even with fresh
event IDs. Named-recipient access restriction also emits this per-recipient action
if the named route disappeared. Public access on the originating peer may still
exist; public access cannot promise exclusion. Transport sends only explicitly
named remote audiences; spaces currently contain local users only.

`room.roster`: payload `{title,owner_id,member_ids,members,linked_room_id,created,
last_activity}`. `owner_id` is origin-qualified; `members` is an array of
`{peer,id}`, and `member_ids` is the matching array of `peer:id` strings. Only the
room origin distributes roster and message events, signed by its original owner.
Initial epoch is 1; removals increment it. Existing room recipients reject newly
added members and changes at the same epoch. Adding people locally creates a
separate linked empty room. A linked reference grants no old-room access. A
receiver refuses a roster whose `linked_room_id` is not null or `<origin>:<id>`
(`<id>` as a participant id, `[A-Za-z0-9_-]{1,64}`) under the envelope's own
origin (400); `room.message` carries the same fields and is refused the same way.

`room.message`: same roster fields plus `message={id,room_id,author_id,
client_message_id,body,epoch,created}`. Here `room_id` is origin-local and
`author_id` is always origin-qualified. Body ≤20000 and client ID ≤100 characters;
message epoch must equal envelope/roster epoch and author must be in the roster.
The origin attests authorship of forwarded replies only after separately verifying
the replying peer and its current membership. Message ID collisions with differing
content fail. Old message bodies already received remain for remaining members.
Old queued messages are never relabeled with a newer epoch.
A receiver shows a message attributed to one of its own users only when it matches
a reply that receiver sent (author, client ID and body), and only the first copy;
anything else is shown as the origin's, marked unverified. Known limit: the origin
orders and timestamps its own room, so it can drop a reply and show it elsewhere,
beside a different message; when it holds a replayed copy, it also chooses which
copy comes first and is shown as the reply. The receiver cannot detect either.
A received message's delivery state is the receiver's alone: its own reply shows
delivered once the origin's copy matches its outbox row, a reply still queued
shows that row's status, and any state the origin sends is ignored. A second copy
of a verified reply is shown as unverified: it may be a replay, and the receiver
cannot tell a replay from a forgery.

`room.withdraw`: empty payload. Removes that recipient's hosted room/messages;
stale/equal events cannot reintroduce them. The same receipt transaction marks
that recipient's pending/failed replies to this origin and resource through the
withdrawal revision as `withdrawn`. A missing/revoked room at final preparation is
also obsolete, not a transient failure. Late acknowledgements cannot replace a
concurrently committed cancellation with delivered/failed state.

`room.reply`: payload `{body,client_message_id}`. Signed by a paired, imported remote
participant in their own namespace; destination is the room origin, resource ID is
origin-local, recipient is exactly the local room owner. Origin checks its current
roster and epoch, stores the original qualified author, and emits a fresh
origin-authoritative `room.message` to current remote participants. Idempotence is
room+qualified author+client ID; same key/different body fails. The room origin
must be online to accept and distribute replies; receipt by one participant never
confers roster-management authority. Local replies remain durably visible as
pending/failed until accepted and echoed by the origin.

## Durable dispatch and limits

`Federation.collect()` materializes the currently uncollected metadata-only local
events in its transaction snapshot into `outbox`, preserving resource, revision, recipient, stable event ID and sequence.
`sync_once(limit=20)` processes at most 20 attempts by default (hard cap 100).
Final content comes from currently authorized active state. The first attempted
body/signature is persisted before sending; retries reuse exactly those bytes and
ID while repeating current pairing/resource/epoch/recipient authorization.
Obsolete pending revisions become `withdrawn`; a subsequent current event carries
the correction or tombstone. Local edits never perform network I/O.

The final-dispatch boundary uses a reentrant thread lock plus POSIX `flock` shared
by all Store transactions for that state. TLS connection/hostname/chain verification
and exact DER fingerprint checking happen first. Under the gate, current state is
read and the envelope committed; the SQLite transaction then closes; HTTP request
bytes are written while the gate still serializes with local commits. The gate is
released before waiting for the response. There is no database write transaction
across socket I/O. A concurrent withdrawal after the socket write is already an
in-flight attempt: it cannot unsend plaintext. Its newer tombstone suppresses
stale arrivals once delivered. Offline or disconnected remote hosts cannot be
promised immediate withdrawal; copies outside this hosted API cannot be erased.

Each wire attempt has a 3-second total deadline, including bounded DNS waiting,
connect, TLS, request and response. A watchdog shuts down a trickling response
socket at the deadline. At most four daemon DNS resolver workers may remain waiting
on the OS; excess attempts fail. Local lock acquisition/content preparation can
add waiting independently of the wire deadline (SQLite busy timeout is 30 seconds);
expired wire attempts fail before output. A pass with 20 unavailable destinations
has at most roughly 60 seconds of wire waiting, plus local database work/contention.

Failures retry after 2,4,8,16,32,64,128,256 seconds (backoff formula capped at 300),
stop after eight automatic attempts, and stay visibly failed. Explicit author retry
resets the attempt budget while retaining ID/envelope and final authorization.
Only failed deliveries can be retried; pending/delivered/withdrawn return 409.
Optional application lifespan worker performs a bounded pass every five seconds
and waits for its current pass on shutdown. Status and retry resolve the same
action-specific local controller: local layer owner for layer events, actual local
message author for locally authored messages, and local room owner for roster
events or origin distribution of a verified remote-authored reply. Outbound
`room.reply` authority is solely its recorded local author, never a local resource
lookup using the destination's room ID. Origin room event collection likewise
excludes remote-origin reply records from its historical destinations. Account
administration confers no delivery authority. Status exposes message_id and
client_message_id only for authorized message/reply records, with no message body. It is
not a distributed availability guarantee or an audit export of others' content.

Only new `peer/` application state is affected. POSIX locking targets macOS/Linux
(including the Pi); multiple database processes must use these Store gates. External
SQL writers, operator-edited private files and other implementations are outside
this coordination boundary. Disk growth is durable and operator-managed; there is
no automatic retention cleanup or replay-expiry shortcut in this slice.

Browser status collection materializes local events without opening any transport
connection. Status remains author-filtered, includes resource/destination
correlation, and reports the effective operation (or the immutable signed action
once prepared). Canceled obsolete content is not an acknowledgement of remote
removal. Local withdrawal is immediate; remote hosted access may continue until
the signed tombstone is acknowledged. No status refresh erases existing copies.
