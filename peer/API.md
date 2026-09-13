# Superyak local peer API

Task 1 implements the local account/content boundary. It makes no model requests.
Run commands from `peer/`, or use `uv run --project peer python -m superyak_peer`
from the repository root. Paths are relative to the command's working directory.

```sh
uv sync --locked
uv run python -m superyak_peer init --data-dir /private/path/home --username owner --name 'Peer owner'
uv run python -m superyak_peer demo --data-dir /private/path/home-demo
uv run python -m superyak_peer serve --data-dir /private/path/home-demo
uv run pytest -q
```

`init` prompts for a password (12–1024 characters), or reads `--password-file`.
It refuses to add another owner to an initialized peer. Owners invite participants.
`demo` writes four fictional accounts and their random passwords into a private
`demo-credentials.json`; it never prints passwords. Repeating a complete demo
initialization validates the existing database, seeded accounts and credentials
read-only before reporting success; missing or mismatched state is refused without
replacement. New credentials include stable account IDs. Legacy credential files
without IDs are checked against usernames/passwords and database foreign keys.
Accounts and drafts are preserved; non-demo/incomplete state is refused. The CLI defaults are `.engram/home`, `.engram/home-demo`, and loopback
`127.0.0.1:7435`. `serve --host` outside loopback requires `--tls-cert` and
`--tls-key`; provide repeated `--origin https://hostname:port` options for actual
browser and peer addresses. Forwarded proxy headers are disabled. IPv4/localhost
are the documented local launch route.

## Factory and extension boundary

```python
from pathlib import Path
from superyak_peer.app import create_app, current_user, actor
from superyak_peer.db import Store

app = create_app(
    Path('/private/path/home'),
    # Optional clock callable, default time.time; used by expiry and timestamps.
    allowed_origins=('https://peer.example:7435',),
    secure_cookies=True,
)
store = app.state.store
```

Factory signature:
`create_app(data_dir: Path, *, clock=time.time, allowed_origins=DEFAULT_ORIGINS, secure_cookies=False)`.
Defaults allow `http://127.0.0.1:7435` and `http://localhost:7435` only; tests must
explicitly allow `http://testserver`. An empty origin list also uses safe defaults.
All requests require a configured scheme/Host; browser mutations additionally
require an exact allowed `Origin`. User IDs from JSON never set acting identity.

`current_user(request)` verifies the cookie and CSRF on mutation, returning the
current public user plus `csrf_token`. `actor(request)` returns only its local ID.
Use these in every added authenticated browser route. `Problem(status, message)`
from `common.py` becomes a public-safe `{"error":"..."}` response. Malformed JSON
and validation are 400, missing sessions 401, origin/CSRF/admin denials 403,
inaccessible resources 404, version conflicts 409, oversize input 413, bounded
login attempts 429. Unexpected failures expose only a generic 500 message.

Additional routers can use `app.include_router(...)`; browser UI can register
`/` and static assets. `/federation/` is reserved for signed transport: its requests
retain Host and size checks but skip browser Origin checks. Such routes MUST
perform independent signature/pairing authorization, never trust cookies as peer
authority, and must not expose Store methods as unauthenticated RPC.

`Store(data_dir: Path, *, clock=time.time)` uses `peer.sqlite3` in a mode-0700 state
directory. The database is mode 0600. SQLite journal permissions inherit its mode.
Existing symlinked state directory/database/journal/WAL/SHM entries are refused.
Attachments are immutable BLOBs in SQLite, so uploaded names never address paths.
The hosting OS user can read plaintext content; this is not end-to-end encryption.

Each public Store operation creates and closes its own SQLite connection and owns
one `BEGIN IMMEDIATE` transaction. `transaction()` is a context manager yielding
an SQLite connection with Row results and foreign keys enabled. `emit(db, kind,
resource_id, resource_version, payload=None)` appends a durable event in the
caller's existing transaction. Do not nest Store operations while holding a
transaction: use documented transaction helpers when an atomic larger operation
is needed. Initialization uses idempotent schema creation; there is no destructive
migration or import of legacy state.

## JSON types and browser routes

All IDs are opaque strings, scoped to this peer. They are not usernames or display
names. A future transport must carry origin peer identity alongside these IDs and
must not merge remote/local IDs by spelling or name. No global owner exists.

A user is `{id, username, name, is_admin, created}`. `created` is Unix seconds;
`is_admin` is 0 or 1 and only permits local invitation/account setup. It conveys no
private-content permission. Contacts expose only `{id,name}` for provisioned local
accounts. All these accounts are known local contacts for this first slice.

| Method/path | Request JSON | Response |
|---|---|---|
| POST `/api/login` | `{username,password}` | `{user,csrf_token}`, session cookie |
| GET `/api/me` | — | User fields plus `csrf_token` and public key-derived `peer_id` |
| PATCH `/api/me` | `{name}` | Corrected user, same ID and grants |
| GET `/api/me/corrections` | — | Signed-in account's ordered `{id,user_id,old_name,new_name,actor_id,created}` name corrections |
| POST `/api/logout` | none | `{ok:true}`, revoked/deleted cookie |
| GET `/api/accounts` | — | User array, owner only |
| POST `/api/invitations` | `{expires_in:86400}` optional; 60–604800 seconds | `{id,token,expires}`; owner only |
| POST `/api/invitations/redeem` | `{token,username,name,password}` | User, 201; no session until login |
| GET `/api/contacts` | — | Contact array |
| GET `/api/home` | — | `{user,spaces,chats,layers,shared_layers,counts}` |
| GET/POST `/api/spaces` | POST `{name,kind,member_ids:[]}` | Space array / created space (201) |
| GET `/api/spaces/{id}` | — | Space, members only |
| PATCH `/api/spaces/{id}` | `{name}` | Renamed space; owner only |
| POST `/api/spaces/{id}/members` | `{user_id}` | Space; owner only |
| DELETE `/api/spaces/{id}/members/{user_id}` | — | Space; owner only |

Sessions use random tokens stored only as SHA-256 hashes, expire after 24 hours,
and are revoked on logout. The cookie is HttpOnly, SameSite=Strict and Secure for
HTTPS or explicit secure-cookie mode. Every authenticated write sends
`X-CSRF-Token` from login or `/api/me`; login/redeem require Origin without CSRF.
No public registration or password reset route exists. Passwords use scrypt with
random salts (`n=16384,r=8,p=1,dklen=32`). Failed logins share a generic response and
are limited to eight per username / forty per source per five minutes; success
clears the username failure counter. One-use invitation redemption is atomic.
Name corrections append their actual old/new values, acting account ID and time.
The self-only history begins with the first correction recorded by this schema;
existing account names do not create fabricated earlier entries. No administrative
route exposes another account's correction history, and corrections change no ID,
membership, layer audience or chat grant.

Home arrays/counts contain only items accessible to the current account. `chats`
contains room summaries, not message bodies. `layers` contains only owned drafts;
`shared_layers` contains accessible active releases (including owned/public ones).

Space: `{id,owner_id,name,kind,version,member_ids,audience_note}`.
`kind` is `care-circle`, `project`, or `organization`. Creator is always a member;
only the space owner edits membership/name. No organization-wide account admin
implicitly owns someone else's space or private draft. Name correction increments
space version without changing identity or membership.

## Layers and publications

Draft input fields (all optional at create):

```json
{"title":"Update","body":"Selected text","audience_users":[],"audience_spaces":[],"public":false,"attachment_ids":[]}
```

Default title is `Untitled`; default body is empty. Title/name limits are 200
characters, draft body 100,000 characters, audience lists at most 100 distinct IDs.
Only local known users, spaces the author belongs to, and owned file IDs may be
selected. Unknown layer fields, including an acting `owner_id`, are rejected.

Draft response adds `{id,owner_id,version,resource_version,active_revision,state}`.
`version` starts at 1 and increments only on draft save. `resource_version` starts
at 0 and increments on activation, restriction or withdrawal. `active_revision`
is null or the active immutable resource revision. `state` says `draft` or
`active` (an active layer can ALSO have newer unpublished draft text; compare the
release's `draft_version` with draft `version`).

| Method/path | Request | Response |
|---|---|---|
| GET/POST `/api/layers` | POST draft fields | Owned drafts / new draft, 201 |
| GET `/api/layers/{id}` | — | Owner-only draft |
| GET `/api/layers/{id}/preview` | — | Owner-only saved draft, selected `files`, named `people`, `audience_details`, and `space_versions` |
| PUT `/api/layers/{id}` | `{version,...changedDraftFields}` | Saved draft; omitted fields preserved |
| POST `/api/layers/{id}/activate` | `{version,space_versions?}` | Exact current draft activated; supplied space versions must still match |
| POST `/api/layers/{id}/revoke` | `{revision,public:false,user_ids:[],space_ids:[]}` | Narrowed active revision |
| POST `/api/layers/{id}/withdraw` | none | Draft with no active release |
| GET `/api/layers/{id}/revisions` | — | Immutable revision array; owner only |
| GET `/api/shared/layers` | — | Accessible active releases |
| GET `/api/shared/layers/{id}` | — | Accessible active release |
| GET `/public/layers/{id}` | — | Signed-out exact active public snapshot |

Activation requires the current draft `version` and revalidates ownership/audiences.
The browser fetches preview immediately before showing it and sends its
`space_versions` map with activation. Membership or space-name changes invalidate
that preview with 409; the user must preview again. Existing API callers may omit
this optional map and continue to activate against current membership. Preview
fails visibly if any selected space, person or file cannot be resolved; missing
selections are never presented as empty. File metadata includes ID, name, media
type, byte size and SHA-256; `/api/files/{id}` inspects the owned immutable bytes.
Owner-only active responses include `audience_details` with frozen care-circle/
project members and current organization members. Other readers receive no such
private audience metadata.
It appends a snapshot with `draft_version`, `revision`, `created`, and original
`owner_id`. Saving privately does not modify any existing release. Revisions keep
original text, author ID and timestamps. Corrections are new explicit draft saves
and activations; display-name corrections never replace IDs or grants.

An owner’s active response includes snapshot fields plus
`{id,owner_id,revision,resource_version,draft_version,created,access_routes}`,
`resolved_space_users` and `audience_notes`. Non-owner named/space recipients receive
only `{id,revision,title,body,attachment_ids,resource_version,access_routes,owner_id,created}`.
An account authorized only through public receives the public content shape plus
`resource_version` and `access_routes:["public"]`; it receives no attribution or
audience metadata beyond the signed-out view. Audience-management lists, frozen
memberships and space labels remain owner-only. These same shapes apply in Home
and shared lists; delivery revision checks retain `resource_version`. Selected care-circle/project members
are frozen into `resolved_space_users` at activation; joining later grants no
access. Selected organizations use current/future membership, explicitly labeled
in `audience_notes`. Organization membership alone never reveals unshared content.
`access_routes` lists every matching route in order: `owner`, `person`,
`space:<id>` for each selected accessible space, then `public`. Public access
cannot exclude an individual. Personal exclusions are not implemented in this slice.

`revoke` requires the current active `revision`. `public:true` means remove public
access; user_ids remove direct person grants and space_ids remove entire selected
space grants. It narrows the ACTIVE snapshot, appends an immutable revision/event,
and never copies or changes a newer private draft. Other routes remain effective.
Removing a direct person grant does not revoke a separate space/public route.
For frozen spaces, remove the space route or activate a newly selected audience.
Existing private draft selections remain available for deliberate later activation;
the UI must preview them again before reactivation.

`withdraw` stops all hosted sharing, emits one ordered withdrawal event, and is
idempotent while already withdrawn. Historical revisions remain owner-only.
Public responses contain ONLY `{id,revision,title,body,attachment_ids}`. Public
JSON has no owner-account, audience, draft, chat, or private citation metadata.
All incoming JSON keys/values, domain text and audience IDs must encode as valid
UTF-8; lone surrogates are rejected with 400 before persistence. Identifier encoding
errors at the SQLite boundary roll back the operation and become a safe 400.
Body is plain authored text; this API does not resolve/fetch URLs or citations.

## Files

| Method/path | Request | Response |
|---|---|---|
| GET `/api/files` | — | Own metadata array |
| POST `/api/files` | `{name,media_type,content_base64}` | Metadata, 201 |
| GET `/api/files/{id}` | — | Owner-only bytes |
| GET `/api/shared/layers/{layer_id}/files/{id}` | — | Authorized active attachment |
| GET `/public/layers/{layer_id}/files/{id}` | — | Active public attachment |

Metadata is `{id,name,media_type,digest,size}`; digest is immutable SHA-256 hex.
Limit: 4 MiB decoded bytes, 6 MiB whole HTTP request. Names allow plain ASCII
letters/digits/spaces/dot/underscore/hyphen, no directories or `..`. Types:
UTF-8 `text/plain`, `application/pdf`, `image/png`, `image/jpeg`, `image/gif`.
Binary magic prefixes are checked; this is not a malware scanner. Downloads use
`application/octet-stream`, `Content-Disposition: attachment` and `nosniff`.
No raw global public-file route exists. Only explicit active owned-layer selection
allows someone else to retrieve bytes; withdrawal immediately closes those routes.

## Private rooms

| Method/path | Request | Response |
|---|---|---|
| GET/POST `/api/chats` | POST `{title,member_ids:[]}` | Accessible summaries / created room, 201 |
| GET `/api/chats/{id}` | — | Room plus `messages` |
| POST `/api/chats/{id}/messages` | `{client_message_id,body}` | Message, 201 |
| POST `/api/chats/{id}/participants` | `{member_ids:[]}` | New linked room, 201; owner only |
| DELETE `/api/chats/{id}/participants/{user_id}` | — | Updated room; owner only |

Room: `{id,owner_id,title,epoch,linked_room_id,member_ids,created,last_activity}`.
Creation/activity values are Unix seconds. Home and chat lists sort by
`last_activity` descending, then stable `id` ascending. Activity is the greater of
room creation and latest message time; summaries expose no message bodies.
The additive `room_activity` table preserves existing room records; rooms created
before timestamp support have `created:0` and use their latest message time for
activity until a new message arrives. Empty members creates a
personal room; one additional member a direct room; more members a group.
Creator is always a member. Account/organization admin status gives no read/send
permission. The first slice reserves audience changes to the room creator, who
cannot remove themselves. Adding participants creates a linked, empty room with
old and added participants; old room/messages stay unchanged. `linked_room_id`
may refer to an inaccessible room; it grants no ability to fetch it.

Message: `{id,room_id,author_id,client_message_id,body,epoch,created}`. Body maximum
20,000 characters; client ID maximum 100. Idempotency key is room+author+client ID;
repeating the same body returns the same message, changing it returns 409.
Removing a member immediately revokes their hosted access and increments the
room epoch. Old queued deliveries fail the documented epoch recheck. No old
plaintext copies are claimed to be erased.

## Store interfaces for following tasks

Browser route methods mirror their resource domain and take trusted `actor` first:

```text
create_user(username, name, password, *, is_admin=False) -> user [trusted CLI only]
rename_user(actor, name) -> user
account_corrections(actor) -> ordered actual self-correction records
login(username, password, source) -> {user,csrf_token,token}
session(token) -> user+csrf_token; logout(token) -> None
accounts(actor); invite(actor, expires_in=86400); redeem(token,username,name,password)
contacts(actor) -> [{id,name}]
create_space(actor,name,kind,member_ids=None); list_spaces(actor); get_space(actor,key)
rename_space(actor,key,name); change_space_member(actor,key,user_id,*,remove=False)
create_layer(actor,data); get_layer(actor,key); list_layers(actor); save_layer(actor,key,data)
preview_layer(actor,key); activate_layer(actor,key,version,space_versions=None); withdraw_layer(actor,key)
revoke_layer_routes(actor,key,data); layer_revisions(actor,key)
active_layer(key,actor=None,*,public=False); shared_layers(actor)
upload_file(actor,name,media_type,content_base64); list_files(actor)
download_file(actor,key,*,layer_id=None,public=False) -> metadata+owner_id+content bytes
create_room(actor,title,member_ids=None); list_rooms(actor); get_room(actor,key)
send_message(actor,key,client_message_id,body)
add_participants(actor,key,member_ids); remove_participant(actor,key,user_id)
can_deliver_layer(key,actor,resource_version) -> bool
can_deliver_message(message_id,recipient_id,epoch) -> bool
events_since(after_id=0,limit=100) -> ordered events (limit clamped 1..1000)
```

Events: `{id,kind,resource_id,resource_version,payload,created}`. `id` is a monotonic
SQLite integer, not a peer-global ID. Kinds: `layer.activated`, `layer.restricted`,
`layer.withdrawn`, `space.membership`, `chat.message`, `chat.membership`. Event
payloads identify author, draft version, message ID, or membership change; they do
not carry full draft/message text. Events are trusted-worker-only, not a browser
feed. Active layer revisions and room epochs are different counters.

Trusted transaction helpers: `_active_layer(db,key,actor=None,*,public=False)`
performs current release authorization; `_room(db,actor,key)` checks current
membership; `_known_users(db,ids)` validates local participants; `emit` appends
within the transaction. Federation must define remote contact identities separately
and explicitly extend audience validation/resolution; no implicit remote account
provisioning or identity merge exists yet. Private draft serialization is never
an exchange payload.

Delivery checks must run immediately before output. A bool check followed by
uncoordinated later send is not an atomic delivery guarantee: the transport task
must serialize its final grant/version check with its outbound send and local
revocation, and persist a retry/outbox record. This task provides current-state
checks and ordered events, but no network, outbox, retry or delivery status UI.
A changed room epoch invalidates queued messages from the previous epoch even for
remaining members; never relabel an old queued send to bypass this check.

## Authenticated peers (Task 2)

The factory now also accepts `federation_endpoint=None, sync_enabled=False`.
A configured endpoint must be an HTTPS origin explicitly present in
`allowed_origins`; configuration never expands origins implicitly. The app exposes
`app.state.federation` and `app.state.sync_enabled`. With no endpoint, local work
and connection listing still run; browser card export returns 409 until configured.
Federation ingress requires HTTPS and independent paired signatures.

Provision an account, export its public card, then serve its generated certificate:

```sh
uv run python -m superyak_peer card --data-dir /private/path/home --username owner --endpoint https://localhost:7435 > owner-card.json
uv run python -m superyak_peer serve --data-dir /private/path/home --host 127.0.0.1 --port 7435 --peer-tls --origin https://localhost:7435 --federation-endpoint https://localhost:7435 --sync
```

For a remote hostname, use it in the **first** card export (or first `--peer-tls`
serve) so its SAN is generated. Cards contain only public material. Browser setup
must trust the generated certificate explicitly; peer transport uses imported exact
pins and never disables certificate verification. `--federation-endpoint` serving
requires `--peer-tls` so the certificate matches the exported identity. Do not mix
`--peer-tls` with explicit TLS files. `--sync` enables the optional lifespan worker.
All origins used by browser/peer traffic must be repeated with `--origin`.

| Method/path | Request | Response/authority |
|---|---|---|
| GET `/api/connections` | — | Array of `{id,peer_id,user_id,name,card,paired}`; local owner only |
| GET `/api/connections/card` | — | Current signed-in participant's public card |
| POST `/api/connections/preview` | `{card}` | Validated public card; local owner only; no pairing or network |
| POST `/api/connections/pair` | `{card,fingerprint}` | Remote contact `{id,peer_id,user_id,name}`, 201; local owner; fingerprint must equal reviewed card |
| DELETE `/api/connections/{contact_id}` | — | `{ok:true}`; local owner; unpairs entire peer and hides its received content |
| GET `/api/sync` | — | `{enabled,deliveries:[...]}` for current author only |
| POST `/api/sync` | none | Runs one bounded pass, returns same author-filtered status |
| POST `/api/sync/{delivery_id}/retry` | none | `{ok:true}`; authorized local delivery controller; resets failed attempt budget, preserves event ID; nonfailed returns 409 |
| POST `/federation/events` | Signed envelope | HTTPS, independent pairing/signature authentication; see PROTOCOL.md |

Delivery metadata is `{id,resource_id,revision,contact_id,action,status,attempts,
next_attempt,resource_title,contact_name,peer_id}`. Message/reply deliveries additionally include `message_id` and
`client_message_id` for correlating pending/sent state to the author's message;
these fields contain no body or audience-management lists. Status is `pending`, `delivered`, `withdrawn` (obsolete/canceled)
or `failed`. GET status collects local events without any network operation,
including when background delivery is disabled. `action` is the effective current
operation for queued work or the immutable signed operation for sent work.
Obsolete queued work reports cancellation, never remote acknowledgement. A delivered
withdrawal means the destination acknowledged it; a pending/failed withdrawal means
access stopped locally while the other host may still serve its existing copy.
Explicit browser delivery checks also reload visible home/room/shared snapshots,
preserving unsaved layer edits and chat composition. `next_attempt` is Unix seconds; after eight attempts explicit retry is
required. Account administration never grants visibility of another person's
layer/chat delivery metadata. Layer delivery authority is its local layer owner;
local-message authority is its actual author (including a nonowner participant);
roster authority is its local room owner. When the room origin distributes an
already-verified remote-authored reply, the local room owner controls that relay.
An outbound reply to a remote-origin room belongs solely to its recorded local
author; matching unqualified local object IDs confer no status/retry authority.
The same action-specific rule protects both status and retry. Sync may send all already-authorized pending work,
but its browser result is filtered. Wire attempts have a three-second deadline;
a default pass attempts at most 20 records. Background interval is five seconds.

Contacts now include explicit paired remote contacts as
`{id,name,peer_id,user_id,remote:true}`. Local contacts retain `{id,name}`. A remote
contact ID is `remote_<random opaque ID>`; it is never inserted into `users`, never
usable for local login, and never treated as an account because of a matching name
or ID. Remote contacts may be selected in `audience_users` and room `member_ids`.
Spaces continue accepting only local account IDs. Pairing alone shares nothing.
For layers naming any remote contact, selected attachment bytes total at most
4 MiB; creating/saving/activating an oversized selection returns 400 before changing
the release. The same file type, digest and download restrictions apply remotely.

Existing `/api/shared/layers`, `/api/shared/layers/{id}`, `/api/chats`,
`/api/chats/{id}`, room send routes, attachment downloads, and Home include
received resources through the same Store APIs. A received resource has stable
`id="<origin peer ID>:<origin-local resource ID>"` and an explicit `origin`.
Local resource IDs retain their existing spelling. URL-encode IDs/path segments.
Received layers expose only selected title/body/attachment IDs, qualified
`owner_id`, revision/resource_version and `access_routes:["person"]`; no private
audience-management metadata. Remote active files use
`/api/shared/layers/{qualified_layer_id}/files/{origin_local_file_id}`. There is no
received-file entry in `/api/files`, no public remote-resource route and no
received-content ownership/republish capability.

Locally hosted room summaries retain local/remote-contact `member_ids`. Received
room summaries have qualified `owner_id`, qualified `member_ids`, plus a `members`
array of `{peer,id}` that can be matched to contact `peer_id,user_id`; no local
account is inferred from an origin-local ID. Their epoch/linked-room references
remain origin-controlled. Messages received in remote rooms have qualified
`author_id`; remote replies in locally hosted rooms also preserve qualified
`author_id`. Locally authored messages in locally hosted rooms retain the local ID.
The UI can distinguish self by local ID or by `/api/me`'s `peer_id:id`. The
authenticated `/api/me` response includes the public key-derived `peer_id` even
without a configured federation endpoint; it exposes no private key or certificate
configuration. Do not infer self from an origin-local ID suffix.
Only a local room owner can change its roster. Adding people creates a new linked
room; remote-origin rooms cannot be managed from a receiving host.

Sending in a received room saves a local outbox reply and returns a Message with
`state:"pending"`. Subsequent room reads include that author's pending/failed
replies, even offline, and replace them with the origin-confirmed message on echo
without duplicate text. The origin assigns its authoritative message ID; identify
an optimistic reply by author+client_message_id when reconciling. A successful
reply delivery can precede the origin's echo, so pending local views may briefly
show `state:"delivered"`. Received rooms disappear on withdrawal/unpair; stale
revisions cannot restore hosted bodies. Applying a room tombstone atomically marks
that recipient's pending/failed replies to that peer/room as `withdrawn`; canceled
work cannot be retried or restored by a late acknowledgement. Repeating an
idempotent send returns the original message ID/body with the current delivery
state, rather than its originally saved pending state. No claim is made to erase copied plaintext.

Worker interface:

```python
from superyak_peer.federation import Federation
from superyak_peer.identity import PeerIdentity

identity = PeerIdentity.load_or_create(store.data_dir)
fed = Federation(store, endpoint='https://peer.example:7435', identity=identity)
fed.card(local_user_id)
fed.pair(local_owner_id, validated_card)
fed.unpair(local_owner_id, contact_id)
fed.collect()                  # bounded metadata-only event → outbox scan
fed.sync_once()                # {delivered,withdrawn,failed,pending}, optional busy:true
fed.status(local_user_id)      # author-filtered delivery metadata
fed.retry(local_user_id, delivery_id)
```

Store adds focused `PeerStore` helpers for remote layers/files/rooms/replies and
keeps existing public signatures. All Store transactions participate in the shared
POSIX/thread dispatch gate. Exact final-dispatch and in-flight limitations, TLS
verification, signed field contracts, receipt retention and room availability are
specified in [PROTOCOL.md](PROTOCOL.md).

## Optional assistant and selected sources

See [configuration, bounds and interchange semantics](MODELS_AND_SOURCES.md).
Every route below requires the local session; POST routes use the existing
same-origin and CSRF boundary. Browser actor/model/provider overrides are rejected.

| Method/path | Request | Response/authority |
|---|---|---|
| GET `/api/assistant` | — | `{enabled,model,message}`; default disabled; configured status may verify native identity without generation |
| POST `/api/assistant` | `{text,layer_id?,version?}` | `{suggestion,model,private:true,layer_id,version}`; selected layer must be owned and exact saved version; no persistence or publication |
| GET `/api/sources` | — | Array of `{id,record}` for the current account's imported private sources |
| POST `/api/interchange/export` | `{selections?:[{layer_id,kind,version}],source_ids?:[id]}` | `{format:"superyak.selected-sources.v1",records:[...]}`; select 1–20 total exact owned draft/active versions or owned imported-source IDs |
| POST `/api/interchange/import` | `{format,records}` | `{records:[{id,record}]}`, 201; validates every record before private atomic import; conflicting same source/revision returns 409 |
| GET `/api/interchange/adna/{layer_id}` | — | Safe Markdown download of one current active owned local layer; no active release or nonowner returns 404; serialized Markdown over 65,536 UTF-8 bytes or containing NUL returns 400 without truncation |

For an export selection, `kind:"draft"` uses the layer's saved `version`, while
`kind:"active"` uses its `active_revision` (the release revision). A changed selected
version returns 409. The browser downloads only the explicitly clicked selection;
no attachment content is included. Imported record audiences never become grants.

Factory extension: `create_app(data_dir, *, model_config=None, ...)`. The configured
adapter is `app.state.assistant`; the private interchange service is
`app.state.interchange`. `models.LocalGemma.suggest(text, draft_or_none)` is the
trusted internal guard; the route enforces session ownership/version before it.
`Interchange.export(actor,data)`, `.import_document(actor,document)`, `.sources(actor)`
and `.adna(actor,layer_id)` use the existing Store's serialized transactions.
