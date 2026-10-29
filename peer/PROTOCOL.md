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

A pull peer's card is **version 2**: v1's keys with `"endpoint": null`, plus
`"delivery": "pull"`. Version 2 means pull; there is no v2 push card. A store's
`federation_mode` is written once: the first `card --pull` makes it `pull`, the first
`card --endpoint` or `serve --federation-endpoint` makes it `push`, and the other kind
of command is refused after that, so one identity never exports both kinds. `card
--pull` also refuses on a store that already has an identity or any `peers` row, so it
can't turn an existing peer into a pull peer. A known peer can't change mode, and a
pull peer refuses to pair a pull card (two pull peers can never reach each other).

Endpoint length is at most 2048 characters; participant ID is 1–64 ASCII letters,
digits, underscore or hyphen; name is at most 200 characters; certificate is at
most 16384 characters. Endpoints must be HTTPS origins without path (including
trailing slash), userinfo, query, fragment or whitespace. No redirects are followed.
Only a local owner can preview/import/pair/unpair. The participant can export their
own card. Import verifies key→peer-ID and certificate→fingerprint bindings. The card is
not a central identity assertion.

**The pairing code** is the first 32 lowercase hex characters of the SHA-256 of the
whole canonical card, `participant` included, shown in groups of four. The exporting
side shows it (`card` on its terminal only, `/api/connections/code`, "Show my peer card"); the
importing side never shows it before it is typed. Pairing takes the code **typed** by a
person reading it off the exporting machine's own screen: in the browser's box, never
pre-filled, or at `pair --as` on a real terminal. A wrong code is refused, and only then
names the card's code; a request carrying only the old `fingerprint` pairs nothing. The
code proves the card in hand matches the card on that screen, the fingerprint
included. It does not prove a person typed it: a pty wrapper or an admin session's own
client could supply it, which is why typing it is a person's act by rule (CLAUDE.md),
not by mechanism alone. `connections` says whether a typed code confirmed each contact's
card, and lists the code only for a contact so confirmed. Pairing authorizes signed ingress from explicitly
imported participants; it does not grant content access. Import each desired
participant's card separately. Cards for a known peer cannot change its URL, key,
certificate or fingerprint, even after unpairing. Name corrections preserve IDs.
Unpairing a contact disconnects that entire peer, including its other contacts,
and suppresses all hosted received content from it. Re-pairing does not restore
old bodies; only a newer valid release may become visible again.

## Wire request

POST `/federation/events` over HTTPS, `Content-Type: application/json`. No cookies
or browser Origin grant peer authority. On `serve` the Host must be explicitly
configured. `federation-listen` (a push peer's listener: loopback only, the
identity's own TLS files, this route and `/federation/pull` and nothing else, bodies
capped at 6 MiB and 16 KiB) does no Host check, since a pinned peer dials the name its
card gives and a 403 there would be terminal.
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
by all Store transactions for that state. **The dial verifies the exact DER pin and
nothing else:** TLS 1.3 at minimum, no chain, name or date check, and after the
handshake, before any byte is written, the SHA-256 of the peer's DER certificate must
equal the card's `fingerprint` (a mismatch is a peer failure, "certificate differs").
The handshake's signature proves the peer holds the pinned certificate's key; names
and dates add nothing to an exact pin, and checking them made identities undialable by
tailnet name and would end every dial a year after an identity was made. Push and pull
share this one dial. Under the gate, current state is
read and the envelope committed; the SQLite transaction then closes; HTTP request
bytes are written while the gate still serializes with local commits. The gate is
released before waiting for the response. There is no database write transaction
across socket I/O. A concurrent withdrawal after the socket write is already an
in-flight attempt: it cannot unsend plaintext. Its newer tombstone suppresses
stale arrivals once delivered. Offline or disconnected remote hosts cannot be
promised immediate withdrawal; copies outside this hosted API cannot be erased.

Each push attempt has a 3-second total deadline, including bounded DNS waiting,
connect, TLS, request and response. A watchdog shuts down a trickling response
socket at the deadline. At most four daemon DNS resolver workers may remain waiting
on the OS; excess attempts fail. Local lock acquisition/content preparation can
add waiting independently of the wire deadline (SQLite busy timeout is 30 seconds);
expired wire attempts fail before output. A pass with 20 unavailable destinations
has at most roughly 60 seconds of wire waiting, plus local database work/contention.

**One outcome table for push and pull.** Each attempt ends in one of these:

| Where | What happens | Row becomes | Peer |
|---|---|---|---|
| local | preparing finds the row obsolete | `withdrawn` | neutral |
| local | preparing hits `sqlite3.OperationalError` (locked, busy, I/O, full) | `failed` | neutral |
| local | preparing raises anything else (a local 413, `ValueError`, `KeyError` …) | `refused`, `last_error` = code or class | neutral |
| transport | the pin doesn't match | `failed`, "certificate differs" | failure |
| peer | 2xx with `{"ok": true}` | `delivered` | reset |
| peer | a peer-scoped answer: any 5xx; a 2xx without `ok`, unparseable or over 64 KiB; 401, 404, 408, 421, 425, 429; 403 "Unknown or unpaired peer", "Peer authentication failed", "Unrecognized host", "Same-origin request required", "Federation requires HTTPS" | `failed` | failure |
| peer | every other 4xx: the peer answered about this row (403 "Unknown remote participant", 409 "Revision already used", 400, 413 …) | `refused`, `last_error` = status and message | reset |
| network | `OSError`, a timeout, any `HTTPException` | `failed` | failure |

Neutral and row-scoped outcomes never block a peer: the next row goes at once, so
neither a poison row nor one the peer refuses stalls the queue. **Backoff is per
peer** (`peer_delivery`): a peer's first failure in a pass counts, waits
`min(cap, 2**min(failures, 12))` seconds and holds that peer's other rows to the next
pass; a reset clears it. The cap is an hour on a push peer and 300 s on a pull peer,
whose pulls are its only way to learn a listener is back. A row's own `next_attempt`
is no longer consulted, and rows never expire: a peer gone for good is dialled hourly
until someone unpairs it, which withdraws its rows (an Ops notice says so after a day
of failing). `failing_since` starts at a peer's first failure and clears on reset. The
author's retry takes a `failed` or `refused` row, keeps its ID and envelope, and makes
its peer due; pending, delivered and withdrawn rows return 409. "Check delivery now"
makes every peer due.

**One sync process per data directory:** `serve --sync`'s worker, or `federate` (no
listening socket; a pass every 5 s, pulls first on a pull peer). Each holds
`federation.lock` (an `flock`, 0600, no symlink) for its life, and a second exits with
"another process already syncs this directory", so rows are never sent or backed off
twice. A pass that raises is logged, and the next goes on. Without `--sync`, "Check
delivery now" never dials; with it, the answer waits about 10 s at most for the pass it
woke. Status and retry resolve the same
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
no automatic retention cleanup or replay-expiry shortcut in this slice, except pull
nonces, pruned by their `at` once 600 s old.

Browser status collection materializes local events without opening any transport
connection. Status remains author-filtered, includes resource/destination
correlation, and reports the effective operation (or the immutable signed action
once prepared). Canceled obsolete content is not an acknowledgement of remote
removal. Local withdrawal is immediate; remote hosted access may continue until
the signed tombstone is acknowledged. No status refresh erases existing copies.

## Pull (version 2 peers)

A pull peer never listens. It fetches what a push peer holds for it with POST
`/federation/pull` on that peer's `federation-listen`, and sends its own events by
push. The request is canonical JSON with exactly these keys:

| Key | Rule |
|---|---|
| `version` | `1`, an int (a bool is refused) |
| `kind` | `"pull"` |
| `origin` | the puller's peer ID |
| `destination` | the listener's peer ID |
| `nonce` | 32 lowercase hex characters |
| `at` | an int Unix time |
| `limit` | an int, 0–20; 0 means acks only |
| `budget` | encoded response bytes, 65,536–6,291,456 |
| `ack` | at most 100 event IDs |
| `refused` | at most 100 `{event_id, code}`, code an int 400–499 |
| `signature` | Ed25519 over the canonical request without `signature`, by the card's `signing_key` |

**Checks, in order:** shape (any other key set is 400, so no envelope or record body
passes); `destination` is this peer (403 "Not addressed to this peer", so one listener
can't replay a puller's request at another); `origin` is a paired peer (403 "Unknown or
unpaired peer") with a v2 card (403 "Not a pull peer"); the signature (403); `at` within
300 s (403 "Clocks differ by more than 5 minutes"); the nonce, unseen for that origin
(409 "Replay"); and one pull per origin at a time (409 "Busy"; only a request that
passed the signature, clock and nonce can be busy).

**Processing.** Acks make that origin's rows `delivered`, refusals make them
`refused` with the code in `last_error`; both only from `pending` or `failed`, and
idempotent. The listener records "last pulled from us", resets that peer, and
collects. It then walks that origin's own `pending` or `failed` rows by `event_seq,
id`, preparing each under its own hold of the dispatch gate, never one hold across
rows, and applying the outcome table; a local outcome never stops the walk or makes a
500. It stops at `limit` envelopes, at `budget` encoded bytes, at 200 rows examined, or
after about 5 s; when nothing else is ready, one envelope over the budget is still
sent, so a large row can't block the queue. The answer is `{"ok": true, "envelopes":
[<canonical envelope text>, …], "more": <bool>}`, `more` true when rows remain beyond
those examined.

**The boundary is per envelope.** Each envelope's release is decided under the gate
when it is prepared, as push decides when it writes. A withdrawal committed before a
row is prepared is honoured: the row comes back withdrawn. One committed after it was
prepared isn't recalled from that response; it goes out as the next pull's tombstone.
A row becomes `delivered` only when an ack names it, so a lost response costs one
duplicate, which receipts absorb.

**Transport.** The pinned dial above, a deadline of 10 s to the response headers, then
the declared `Content-Length` at no less than 64 KiB/s (a 5.8 MB response gets about
100 s on a slow link, and a stalled one still ends). A 2xx needs a `Content-Length`
within 6 MiB + 64 KiB, or it is refused unread. The puller asks for a 1 MiB budget.

**Too large to pull.** The listener answers in compact UTF-8, and every size here is
counted in those bytes. Envelopes travel as JSON strings, so escaping grows them: a
control character costs 7 bytes in the answer (escaped twice), a quote or backslash 4,
and any other character its UTF-8 bytes. A row whose encoded envelope alone can't fit
within the cap less 1 KiB of frame is `refused` where it waits, `last_error` "413 Too
large to pull": its owner sees "Too large to deliver by pull", with no Retry, and a
smaller release is a new revision. The worst release the limits allow (100 files
totalling 4 MiB with 120-character names, a body of 100,000 U+0001 characters and a
200-character title of the same) makes a 6,229,026 B envelope and a 6,331,727 B answer
against the 6,356,992 B cap: a margin of 25,265 B, measured through the listener's own
encoding (test_listener). The same release in emoji answers 6,031,127 B. Any later
change to the body, title or attachment limits has to revisit this cap.

**The puller.** It keeps acks and refusals per listener until a request carrying them
gets a 2xx. An envelope from any origin but the listener is dropped; the rest go to
`receive`: ok or duplicate is acked, a peer-scoped answer is neither (offered again
next pull), and every other 4xx is refused. It takes up to 10 rounds while `more`,
ending early when a response brought envelopes and none gave a new ack or refusal, then
sends `limit` 0 if acks remain. To the pull itself: 409 "Busy" waits 5 s and tries once
more with a new nonce; 409 "Replay" takes a new nonce at once; 400 is logged as a bug,
acks kept; 403 is logged with its words and shown in `connections`; 404 means no pull
route yet, so it waits 5 minutes; a 5xx, a network failure or a pin mismatch goes into
the per-peer backoff. It pulls each listener every 60 s, at once at start, after a
recovery, after "Check delivery now", and after a sleep overrun.
