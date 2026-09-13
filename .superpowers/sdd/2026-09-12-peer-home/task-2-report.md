# Task 2 — authenticated peer transport

Implemented on `codex/peer-home`, building on reviewed Task 1 `e2d4fb8ded2d896e5bc88128b8bdaa614ac9a45f`.
Only peer application/transport modules, tests and protocol/API documentation changed.
No Pi, existing services, Engram/Atlas stores, live research, models or external
messaging were touched. No subagents or reviewers were spawned. The task used the
TDD and verification-before-completion skills and completed a local self-review.

## Result and module map

- `identity.py`: private persistent Ed25519 and independent P-256 TLS identity;
  SAN-bearing generated certificate; strict public card validation; canonical
  finite UTF-8 JSON; signed v1 envelopes covering origin, destination, qualified
  actor, revision, resource, recipients, payload/digest and stable event ID.
- `transport.py`: actual HTTPS sockets, normal chain and hostname verification,
  exact DER SHA-256 pin, no redirects, bounded DNS concurrency/waiting, total
  three-second attempt watchdog, bounded acknowledgements.
- `dispatch.py`: process/thread-reentrant POSIX flock/RLock gate. Store transactions
  share the gate; final grant validation commits and closes SQLite before HTTP
  bytes are written under the gate. Gate releases before reading the response.
- `peer_store.py`: additive SQLite tables for peer trust, separate remote contacts,
  remote room membership, original remote message authors, inbox resources,
  receipts and durable outbox/cursor. Unified remote layer/file/room reads;
  durable own pending replies and echo reconciliation. No remote login accounts.
- `federation.py`: explicit pair/unpair/card operations, bounded metadata event
  collection, final-state payload assembly, stable-envelope retries, tombstones,
  durable replay/collision checks, origin-authoritative roster/message application,
  authenticated member replies, author-filtered status and explicit retry.
- `peer_routes.py`: CSRF/session-authorized connection and sync APIs, independent
  HTTPS/signature ingress, optional lifespan worker. No cookie-based peer authority.
- Minimal `db.py`, `layers.py`, `chats.py`, `files.py` extensions preserve existing
  APIs while allowing named remote recipients, separate remote roster rows,
  current attachment authorization and qualified received object IDs. Local
  spaces remain local-account-only. Upload validation is shared without putting
  received files into the local owned-file table.
- `app.py`: adds explicit `federation_endpoint` and optional `sync_enabled`; endpoint
  must already be an allowed HTTPS origin. Exposes `app.state.federation`.
- CLI: `card --username --endpoint`, `serve --peer-tls --federation-endpoint --sync`.
  Generated TLS serving ensures exported card pin and actual server certificate
  match. Local-only operation remains supported.
- `API.md` and `PROTOCOL.md`: exact browser/Store/wire contracts, identity mapping,
  message reconciliation, timeout/retry and in-flight/availability limitations.

New browser routes are `/api/connections` (owner listing), `/card` (self export),
`/preview`, `/pair` (explicit reviewed fingerprint), DELETE `/{contact_id}`;
`/api/sync` GET/POST and `/{delivery_id}/retry` POST. Peer ingress is HTTPS POST
`/federation/events`. Received layers/chats/files use existing browser resource
routes with `<origin-peer>:<origin-resource>` IDs. Remote contact IDs are separate
`remote_<opaque>` references; remote origin-local IDs never become local user IDs.

## RED/GREEN evidence

Initial test command from worktree root:

```
uv run --project peer pytest peer/tests/test_identity.py peer/tests/test_federation.py -q
2 failed, 4 errors — absent identity/federation modules (expected missing feature).
```

Tests specified persistent identity/card constraints, signature field binding,
unknown peer/recipient denial, durable duplicate/collision handling, explicit
remote contacts, sharing/withdrawal and private-room replies/removal before those
modules existed. After implementation, the same command reported `6 passed`.

HTTP/CLI feature REDs:

```
cd peer
uv run pytest tests/test_transport.py -q
2 failed, 1 passed — factory lacked federation_endpoint and connections returned 404.
uv run pytest tests/test_cli.py::test_card_cli_and_peer_tls_options -q
1 failed — argparse had no card command.
```

Implemented the routes/factory/CLI and real HTTPS transport; the then-current full
suite reported `45 passed`, then `53 passed` as additional contracts landed.

Self-review exposed concrete regressions with failing tests before fixes:

- `test_roster_cannot_add_to_existing_room`: DID NOT RAISE. Receiver now rejects
  additions to an existing room and changes without an epoch increase.
- `test_exhausted_retry_keeps_event_id_and_rechecks_current_state`: missing retry
  method. Added author-only budget reset preserving stable ID/signed envelope.
- `test_malformed_authenticated_room_is_public_safe`: raw TypeError in malformed
  roster. Added typed roster/timestamp validation and public-safe payload errors.
- `test_room_activity_includes_remote_reply`: 1000 observed, 2000 expected. Local
  room activity now includes origin-accepted remote-authored messages.
- `test_trickling_response_has_total_deadline`: 5.319 seconds observed for a
  0.2-second requested deadline (assertion `<0.8` failed). Replaced per-read-only
  timeout behavior with bounded DNS wait and whole-attempt socket shutdown.
- `test_remote_reply_remains_visible_offline_without_duplicate_echo`: IndexError
  because no pending messages were returned. Reads now include durable author's
  pending/failed replies and replace them on matching qualified-author/client-ID
  echo without duplicate bodies.
- `test_multiple_imported_participants_keep_their_own_card_labels`: second contact
  displayed first participant's ID. Connection cards now use each contact's exact
  imported participant ID/name; reimported display-name correction preserves ID.
- `test_protocol_version_is_integer_not_boolean`: accepted True as version 1.
  Card/envelope versions now require exact integer type.

Each fix's targeted suite passed afterward. Supplemental adversarial tests verify
selected attachment transport/withdrawal/no reownership, aggregate attachment
bounds before saving, unknown peers, unauthorized room replies, newer tombstones
against fresh stale event IDs, local/remote object-ID collisions, immutable peer
URLs, absence of remote login, and active-route revocation without private-draft
publication.

One accidental `uv run --project peer pytest -q` from the repository root collected
unrelated Atlas/Engram suites and failed collection on unavailable modules. Correct
peer-project checks run with cwd `peer/`; no unrelated dependency/environment
changes were made. A refactor briefly introduced a missing parenthesis in the
attachment-size validation, was caught immediately by the full suite, and fixed
before final verification. No failed check is represented as passing.

## Real TLS measurements

`uv run pytest tests/test_transport.py -q --durations=10` reported:

```
7 passed, 1 warning in 2.93s
0.85s two live HTTPS peers exchanging room replies and final-dispatch withdrawal
0.61s real HTTPS release, restart, replay, wrong-certificate rejection and withdrawal
0.51s trickling-response deadline (includes HTTP fixture shutdown)
0.19s exhausted explicit retry retaining its ID
0.19s offline connection refusal/backoff/restart
0.01s different leaf signed by trusted certificate rejected by exact fingerprint
```

The alternate-leaf test first succeeds with normal TLS chain+hostname verification
against the imported root, then proves the transport rejects that same server
with `Peer certificate fingerprint differs`. Thus the pin check is independently
tested beyond an unknown-CA failure. All transport TLS uses generated real keys,
actual loopback sockets and active verification. There is no `verify=False`.

Two independently hosted HTTPS apps exchange a room's creation, message, reply
and origin echo. A mutation inserted after TLS establishment but before final
preparation withdraws the queued layer; no release reaches the other peer, and the
subsequent tombstone succeeds. Separate tests reload both Store/Federation state
and repeat a signed event to prove persistent identity, receipt/idempotency and
outbox/retry preservation across restart.

Final validation is recorded below after its actual completion.

## Self-review conclusions and constraints

All original Task 1 authorization tests remain in the suite. Nonowner/public
representations retain the reviewed filtering; transport builds selected payloads
from trusted active snapshots and includes no private audience-management fields.
Actor, destination and recipient bindings are signed. Incoming room replies must
name the local room owner, use the current epoch and have current explicit remote
membership. Origin alone distributes rosters; adding people creates a linked empty
room. Newer tombstones dominate stale deliveries without exposing stored receipts'
bodies. Unpair suppresses local hosted received content and cancels pending work.

The final dispatch gate serializes final request writes with local commits across
threads/processes without a SQLite transaction across network I/O. An already
written request remains in flight; later withdrawals cannot retract plaintext
and take effect remotely when their tombstone arrives. Room origin availability
is required for remote replies and roster changes. Disconnected peers are not
promised immediate erasure. Locally authored pending replies remain visible offline.

Automatic delivery attempts are capped at eight; explicit owner-of-content retry
retains the event ID and repeats authorization. A pass defaults to at most 20
attempts. Network work is deadline-bounded; local lock/database contention may add
waiting (SQLite busy timeout 30 seconds). DNS can leave at most four bounded daemon
resolver workers awaiting the OS. Shutdown waits for the current bounded sync pass.
The POSIX gate targets macOS/Linux, including Pi Python 3.11; arbitrary external SQL
writers do not participate. Disk retention remains operator-managed; no receipt
expiry that would weaken replay/tombstone protection was added.

Generated certificates expire after 365 days and require the intended endpoint SAN
at initial creation. Automatic trust rotation/URL replacement is intentionally
refused; a future explicit migration is needed. Browser trust of the generated
certificate remains an explicit operator setup step. Peer transport itself pins
and verifies it. UI/model/packaging/live-host deployment are later tasks and were
not altered here. The only remaining test warning is the existing third-party
Starlette/AnyIO BlockingPortal deprecation, not a transport verification bypass.

## Final verification

```
# cwd peer/
uv run pytest -q --durations=8
67 passed, 1 warning in 25.44s

# cwd worktree root
git diff --check
# exit 0, no output
uv run --project peer python -m compileall -q peer/superyak_peer
# exit 0, no output
```

The complete 67-test peer suite includes all 36 reviewed Task 1 tests and 31 Task 2
checks. The single warning is the existing third-party AnyIO alias deprecation.
