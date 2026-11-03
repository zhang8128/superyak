# Plan: a ship's own home, and lighthouse crossings between peers

Tardis, 2026-11-03. **Revision 1**, for a fresh reviewer started on the Pi.
- It implements the approved spec `docs/superpowers/specs/2026-11-03-ship-home-and-crossing-design.md`, **revision 4**
  (d36fee92, this branch): stage 2 first, then stage 3. Stage 1 (own home on one machine) is Rio Grande's build and
  isn't planned here. Section numbers below are the spec's.
- The interface it meets is Rio Grande's section 3.11 (memory-follows-ship 888a5a2d).
- Where the spec leaves a choice open, the plan makes it, marks it **P1** to **P23**, and gives the reason. P19, who
  asks a crossing before Rio Grande's store host exists, is **decided by Tardis**: today's in-process Engram server
  asks, behind one function the host will call later, under Rio Grande's two conditions (all hands, 4164449a).
- Every concrete change the spec's three reviews name lands somewhere below; "Where each review change lands" lists
  them by number.
- Planning against the code found eleven places where the spec's words and the code differ. They are listed at the
  end of "What the code looks like today", each with the decision that handles it.

**This is safety code** under law section 2: it decides who may read what leaves a store (the publisher's checks, the
crossing route, the receiver's records and its guard) and it changes how the permission ledger judges a requester
(`remote-stores`). So it gets a test-first build, each test written and seen failing before its code; a fresh reviewer
started on the Pi that took no part in writing it; and each partner's explicit yes before it merges. Nothing in
"Deploy" runs on a merge alone.

## Base and order (P1)

- **The branch.** The build happens on `tardis/crossing`, cut from this branch (`tardis/crossing-spec`: main b7d91462
  plus the spec's four commits), so the spec, its reviews, this plan and the code travel together. It merges main
  before review and reruns everything.
- **Stage 2 is Tasks 0 to 14** and merges on its own. Its asking seam is P19's `ask_crossing`, called today from
  `neighbors.attach_neighbors` inside the in-process Engram server. When Rio Grande's host lands, the host becomes the
  caller of the same function and `[[hosted]]` (P2) is retired; no route changes.
- **Stage 3 is Tasks 15 to 18,** on a later branch. It depends on three things that don't exist yet:
  - Rio Grande's store host (its stage 1), since the memory route forwards 3.11 envelopes to it;
  - the cluster station spec's review, which owns the per-job key's expiry column (P20);
  - a home that serves: 1.2 starts "on a home that serves", and Tardis has no `serve` and no ship user today.
- **Shared files.** Rio Grande's stage 1 refactors `engram/server.py` and `engram/neighbors.py` (its 3.6). Tasks 11
  and 12 touch both. Before either starts, Tardis says so in the room; whichever lands second rebases.
- **Live state today** (re-check C, spec section 3): Tardis's peer is the pull peer at
  `~/.local/share/superyak/tardis-peer` and runs only `federate`. The Pi is a push peer running `federation-listen`.
  Rio Grande reports the tardis ship as a code-confirmed contact on the Pi.

## What the code looks like today

**The peer (`peer/superyak_peer/`)**
- `listener.py:13-14`: `ROUTES` has two entries, events (6 MiB) and pull (`PULL_REQUEST_MAX`, 16 KiB). The app
  (:66-84) refuses plain HTTP (:70-71), refuses an over-cap `Content-Length` unread (:72-74), and runs the handler with
  `asyncio.to_thread` (:79). A `Problem` becomes its status and `{"error": message}` (:80-81).
- `federation.py:421-463`, `serve_pull`: shape (400), destination (403), a paired origin (403), the v2-only check
  (:438-439, which a crossing doesn't copy), `verify_pull` (:440), the clock (:442-443), then the nonce under
  `_replay_floor` (:444-455, floor at :408-419) and 409 "Replay". `pull_nonces` is pruned by `at` (:448).
- Contacts: `pair()` is the only writer of `remote_contacts` (:144). Holds are `contact_holds` (`HELD`, :78). The
  confirmation rule lives inline in `connections()` (:185-191): a contact counts as confirmed only while its stored
  code equals `pairing_code` of the stored card with that participant, and its peer is paired.
- `identity.py`: `canonical()` is raw UTF-8 (:20-25). `RECORD_KEYS` (:103-116) reserves `pull` in a comment (:102),
  and `PULL_KEYS` (:119-120) is the pattern a crossing copies. `verify_pull` (:272-284) answers every fault with 403
  "Peer authentication failed". A card's participant id is `[A-Za-z0-9_-]{1,64}` (:77), and is the account's
  `users.id`, which `uid()` makes as 32 hex (`__main__.py:881`, `:901`; `common.py:22-23`).
- `transport.py`: `_dialable` (:55-63) refuses a card without an endpoint; `_pinned_socket` (:66-97) compares the pin
  before any byte; `pull_pinned` (:171-209) is the model for a capped, deadline-bound POST.
- `federate.py:1-6` says "It listens on nothing". `Federate.run` (:73-84) loops passes until SIGTERM. The command
  (`__main__.py:931-951`) takes `federation_lock`, then `keep_open`, then runs. `federation-listen` (:952-982)
  refuses a non-loopback host and a non-push mode.
- `peer_store.py:28-45`, `PEER_SCHEMA`, has no `crossings` table. `test_restore.py:2536-2548` lists every coordination
  table, and `:2551-2566` fails on an unclassified one.
- `tests/test_federate.py:112-122` fails on any `bind` or `listen` during a pass. `tests/test_listener.py:55-60`
  expects exactly two routes.
- The peer never imports Engram (no `engram` or `lighthouse_protocol` import in `superyak_peer/`), so it can't call
  `validate_frame`.

**Engram, the publisher (`engram/lighthouse_daemon.py`)**
- It keys every receiver check off one bare local name:
  - `_request` builds `publisher=f"urn:engram:{frame['receiver']}"` (:785-798);
  - `_allowed_audiences` is called with `urn:engram:` plus the name at :958 and :988-992, and looks the key up as
    given (:224). It adds `group:outside-home` under `enforce` for a receiver a rule names (:229-233);
  - `_LedgerSide` makes the agent `agent:{receiver}` and reads its place (:483-486), reads the receiver's own policy
    from `instances/<receiver>/` (:499-512), and always adds the "receiver" legacy layer (:493-496), which refuses
    when no file was found (:514-516).
- **The ledger side exists only under `shadow` and `enforce`** (:856-857). Under `shadow`, recall isn't filtered
  (:959) and a read delivers by the legacy path (:640-641).
- `_recall` makes a fresh `turn_id` (:904) and records a disclosure (:915-926). `_read` (:978-1035) never looks at
  `turnId`. The sidecar (`_SIDECAR_SCHEMA`, :65-70) has `receiver` and no network columns.
- `handle_frame` (:810-850) accepts `recall` and `read` only (:813), reloads the policy per frame (:830) and serves
  nothing under a closed gate. `build_publishers` (:1111-1123) maps a name to `instances/<name>/`.
- `lighthouse_policy.py:78-83`: a `*`-suffixed pattern matches any value with that prefix, so `urn:engram:*` and `*`
  match every value.
- `lighthouse_protocol.py`: the local frames are `recall` (:213-238) and `read` (:264-284). `validate_frame`
  (:313-327) checks that fields are present, not that the key set is exact (`_required`, :205-206).
- The agent grammar is `_NAME` (`permissions.py:104`, used at :138-139), with no colon. `_requester_ok` (:2062-2067)
  needs a registered agent placed at the use's place, else `UNKNOWN_REQUESTER` (:2420-2421). `agent_place_at`
  (:908-912) returns the agent's place. A root place dominates only itself (:593-600), so a `self` allow in a home
  layer never reaches an agent at a root place (:960-974).
- `permission_cli.py`: `agent add` and `agent place` (:443-452, parser :1413-1420) write `register-agent` and
  `put-agent`; `_perform` (:280-293) prints the change, asks the typed code and writes as the owner. `migrate`
  registers receivers acting for and placed at the owner's home (:1142-1144).
- Instance creation is `cli.fork_instance` (`cli.py:15-45`), which takes any name. Sharing refuses an imprint source
  (`sharing.py:109-110`); `validate_audience` (:43-48) checks values, not map keys. `policy_gen.build_publisher_policy`
  (:59-107) writes local receivers only.

**Engram, the receiver**
- `neighbors.neighbor_arm` (:25-180): one shared deadline (:47); local publishers only (:79-80, names checked by
  `valid_publishers`, which needs at least one: `lighthouse_receiver_config.py:26-29`); `k=20` per publisher (:91);
  reads with the prefix stripped (:125); a 32 KiB total content budget (:17, :147-155); a content-free receipt written
  before delivery (:160-176), whose failure suppresses everything (:177-178).
- `validate_read` (`lighthouse_client.py:303-357`) returns items and drops the read's `disclosureId`, so a receiver
  receipt holds only the recall traces' ids (`neighbors.py:166`).
- `load_settings` (`lighthouse_receiver_config.py:32-54`) refuses any extra key (:40) and needs `socket_path`.
  `lighthouse_validation.py:53-58` refuses an `engram:weight` key that isn't `urn:engram:`.
- The receiver arm runs from `recall` (`server.py:3232-3242`), after the response is built, and from
  `context`'s `LighthouseSource` (`context_cli.py:89-92`, `context_lighthouse.py:126-129`), which re-reads by `turnId`
  later (`context_lighthouse.py:159`, `:171-174`). The wake and nudge hooks (`hooks/wake.py:145`,
  `hooks/nudge.py:92`) call no neighbor.
- `write_receipt` (`lighthouse_receipts.py:90-113`) logs the receipt in `graph.db`. The receipt schema lets
  `extensions` carry any `prefix:`-named member.

**Engram, the guard**
- `_keep_decision` (`server.py:2081-2120`) is the only guard, called only from `remember` (:1907). It returns early
  with the gate off (:2091-2092) and again when `permission-uses.db` is missing (:2104-2105).
- `permission-uses.db` is hash-chained (`permission_uses.py:1-7`) with a checked digest form (:30-32, :202-206).
- The other tools that store text call no guard: `add_anchor` (:3744-3765), `task_update` (:4113-4127),
  `dream_capture` (:4151-4168), `jot` (:4306-4326, both pads) and `clipboard_pin` (:4524-4539).

**Stage 3's ground**
- `ship_keys` is `(id, ship_id, key_hash, created, last_used, revoked)` (`ships.py:32`): no scope and no expiry.
  `ship_for_key` and `ship_key_is_valid` (:119-143) accept any unrevoked key and give one 401 for every bad key.
- `PublicRoute` lets a public request through on any valid ship key (`app.py:157-168`); its own fault is a 503 with no
  `Retry-After` (:138-142). `is_public` (:68-81) counts compute-node clients as public. `BrowserBoundary` answers 413
  over 6 MiB before any route (:110-111). `ship_member` answers 403 with no code (:235-240). `tailnet_only`
  (:250-255) guards the imprint routes (:857-866).
- The dock client deletes its key on a 401 (`agent/superyak_agent/dock.py:67-71`). `peer_meta` has no `station_kind`.

**Found while planning: where the spec's words and the code differ**
1. 2.5 places the remote guard "before the existing guard's gate-off early return (server.py:2104-2109)". The gate-off
   return is `server.py:2091-2092`; :2104-2105 is the missing-receipts-file return. The remote check goes before both
   (Task 12).
2. 2.2: "Until the owner registers it, every crossing is refused (`UNKNOWN_REQUESTER`)". That holds only under
   `enforce`: under `off` no ledger side is built (`lighthouse_daemon.py:856-857`), and under `shadow` the legacy path
   delivers (:640-641, :959). P10 makes it hold.
3. 2.3 still calls the local frame a "`query` frame" and says "after a remote `query`". The frame kind is `recall`
   (`lighthouse_protocol.py:213`, `lighthouse_daemon.py:813`), as re-check 1 noted. The plan says `recall`.
4. 2.4 says `neighbors.py:80, 88, 117` take a `urn:engram:` prefix. :117 compares refs and takes none; the prefix sites
   are :80, :88 and :125 (and `context_lighthouse.py:172`, which skips remote publishers under P14).
5. 1.2: "`expired` from `expires`". `ship_keys` has no `expires` column (`ships.py:32`). It comes with the cluster
   station spec (P20).
6. 2.1 names three places that say federate never listens. A fourth is the pull spec's section 10, test 11 (its line
   368). `listener.py:1` and `tests/test_listener.py:1` also say "two routes". All are amended (Tasks 7, 14).
7. 2.3 caps the request at 16 KiB and the query at 4,096 characters. Re-check 1's nit stands: canonical JSON is raw
   UTF-8, so 4,096 four-byte characters are 16,384 bytes before any other key. P17 handles it.
8. 2.3: "delivered text at most 32 KiB, as locally". Locally, 32 KiB is the receiver's per-item cap
   (`lighthouse_client.py:19`, :351) and total budget (`neighbors.py:17`). The daemon caps nothing, and a five-item
   read can pass 128 KiB. P7 enforces it at the publisher's peer.
9. The read's `disclosureId` reaches no receiver record today (`lighthouse_client.py:303-357`, `neighbors.py:166`), so
   "all four records link by `disclosureId`" needs P15.
10. 2.2 asks "sharing's validation" to accept the remote form as an audience-map key. Sharing validates no map key
    today (`sharing.py:43-48`); the daemon's lookup (`lighthouse_daemon.py:224`) takes any string. P12 adds the one
    validator, used where policies are generated.
11. A site the spec doesn't name: `lighthouse_validation.py:56-58` makes a receiver policy that weights a remote
    publisher invalid as a whole. P14 leaves weights local.

## Decisions the spec leaves open

- **P2 The peer's crossing settings are `crossings.toml` in the peer data directory,** read at each request (by
  mtime), refusing a symlink and any unknown key:
  - `[[published]]`: `ship` (a username, resolved per request to a `users.id` of kind `ship`), `publisher` (the
    daemon's publisher name, Engram's `NAME`), `daemon_socket` and `sidecar` (absolute paths). This is 2.3's map
    (S-b).
  - `[[hosted]]`: `ship` and `instance_id`, the stores this home hosts. It serves P19's interim. When the host lands,
    the peer reads the host's own configuration instead (2.4), and this table goes.
  - A `daemon_socket` whose file name is `host.sock` is refused, so federation-listen can't be pointed at a store
    host (1.1's path).
  - **Why a file:** the spec says "in its peer config", and the peer has none. A file read per request takes effect
    without a restart, as the daemon's policy does, and keeps Engram paths out of `peer.sqlite3`. An invalid file
    refuses every crossing with 503 and is logged.
- **P3 Crossing nonces share `pull_nonces`.** Same `(origin, nonce)` key, same prune by `at`, same `_replay_floor`.
  - **Why:** `carry_pull_nonces` (`backups.py:1218`) and the restore floor (`federation.py:408-419`) already cover
    that table, and
    it is already classified (`test_restore.py:2546`). A new table would need both again.
  - Kinds keep the two apart: a pull can't verify as a crossing, nor the reverse. Random 32-hex nonces don't collide.
- **P4 The peer checks the frame's shape itself,** since it can't import Engram. The daemon still runs
  `validate_frame` as today.
  - A `recall` frame has exactly `protocolVersion` ("0.1"), `kind`, `receiver`, `publisher`, `context`, `purpose`,
    `audience` ("self"), `query` (1 to 4,096 characters), `k` (1 to 20) and `at`.
  - A `read` frame has exactly `protocolVersion`, `kind`, `receiver`, `publisher`, `context`, `purpose`, `turnId` (1 to
    64 characters) and `memoryIds` (1 to 5 distinct strings of at most 128).
  - `context` is exactly `{id, path}`, `id` at most 512 characters. `purpose` is 1 to 256 characters, as
    `neighbors.py:36` allows. `receiver` and `publisher` are any 1 to 256 characters, since they're overwritten.
  - `receiver_instance` matches the canonical UUID form (imprints' `_ANY_UUID`, `imprints.py:138`), since instance ids
    are uuid4 or uuid5 (`store_identity.py:57`, :143). Both ship fields follow the participant rule
    (`identity.py:77`).
- **P5 One contact rule.** `connections()`'s test (`federation.py:185-191`) moves into a helper,
  `_contact_confirmed(card, user_id, name, confirmed_code, paired)`, and both `connections()` and check 5 call it.
  - Check 5's query: the origin's `remote_contacts` row for `receiver_ship`, joined to a paired `peers` row, with no
    `contact_holds` row and a confirmation the helper accepts. Otherwise 403 "Receiving ship is not a current
    contact".
  - **Why:** 2.2 says "by the rule `connections()` uses"; one helper keeps it one rule.
- **P6 Load, counted in memory, on both sides.**
  - On the publisher's peer: a per-origin semaphore of 2, a total semaphore of 4, both taken with `blocking=False`,
    and a per-origin deque of request times for 60 in any 60 s. Each is checked after check 6, so only verified,
    mapped requests count. Otherwise 429 "Too many crossings".
  - On the asking peer: at most 2 crossings in flight per destination, waited for only within the request's
    deadline. So its own load can't earn 429s.
  - **Why:** the listener runs handlers in the default thread pool (`listener.py:79`). Four crossings at most leave
    the rest for events and pulls.
- **P7 The publisher's answers.**
  - **Direction:** the answer's `origin` is the answering peer and its `destination` the asking peer. It binds the
    request by `request_digest` (SHA-256 of the canonical signed request) and `nonce`.
  - **Caps:** if the daemon's frame makes an answer over 128 KiB, or its delivered `content` totals over 32 KiB of
    UTF-8, the peer answers 502 "Answer too large", writes no `crossings` row, and sends no frame.
  - **Daemon faults:** an error frame from the daemon is 502 with the daemon's code in `error`; a daemon that misses
    the deadline is 504 "Deadline passed"; neither writes a row.
  - A failed `crossings` insert is 503, with no answer (2.3).
  - **Why:** 2.3 caps the answer and the delivered text, and the daemon caps neither (finding 8). Refusing the whole
    answer keeps "no row means no answer" true; the disclosure the daemon recorded shows as unsent (P18).
- **P8 The local hop's wire.** One canonical JSON line each way over `<peer data dir>/crossing.sock`.
  - **Request:** exactly `receiver_instance`, `receiver_ship`, `destination` (the publisher's `peer_id`),
    `publisher_ship`, `frame` and `deadline_ms`, at most 16 KiB.
  - **Reply:** `{"ok": true, "frame": …}`, or `{"ok": false, "code": …}` with one of `NOT_HOSTED`, `NOT_PAIRED`,
    `TIMEOUT`, `UNAVAILABLE`, `QUERY_TOO_LARGE`, `REFUSED_<status>` and `BAD_ANSWER`. Engram shows the code in
    `diagnostics` by name.
  - The peer refuses a store not listed as hosted for that ship (2.4, with 1.1's same-uid caveat), and a destination
    that isn't a paired push peer with an endpoint.
- **P9 The socket: one module, opt-in on both commands, on its own supervised thread.**
  - `crossing.CrossingSocket` binds `crossing.sock` (mode 0600, a stale socket unlinked, a symlink refused) in a
    `ThreadingUnixStreamServer` run by a supervisor thread. A fault in it is logged, and it restarts after 1 s. It
    shares only the `Federation` (identity and store reads), and never raises into `federate`.
  - `federate --crossing-socket` starts it before `run()`, after the lock. `federation-listen --crossing-socket` does
    the same.
  - **A narrowing, said plainly:** 2.1 says federation-listen "opens it". Here it opens it only when asked. In stage 2
    the Pi only answers, so its socket would have no use, and a listener nobody uses is surface.
- **P10 The daemon serves a remote frame only under `enforce`.** Under `off`, `shadow` or `closed`, a frame whose
  receiver is a remote ref gets `error_frame("PUBLISHER_UNAVAILABLE")` before any read, and no disclosure.
  - Two more daemon refusals for remote frames: a receiver that starts `urn:superyak:` but isn't a well-formed store
    ref, and a house that is an imprint (`store_identity.is_imprint`, `store_identity.py:152-153`), which answers
    `PUBLISHER_UNAVAILABLE`. A remote read with more than 5 ids is `MALFORMED_FRAME`.
  - **Why:** finding 2. The spec's fail-closed claim, and re-check 2's "kept" list (the place is a consent layer;
    an outside-home allow needs finite purposes, at most 366 days and named memories: `permissions.py:3385-3398`),
    hold only when the ledger decides. The imprint refusal is the first review's nit, put where the house is known.
  - **Cost:** stage 2 waits until the Pi's gate is `enforce`, which is Andy's act (Deploy step 3).
- **P11 `remote-stores`: registered by one informed command, placed at a root place.**
  - `engram-permissions agent remote-stores` prints Rio Grande's words (77dec36f), "Every remote store this home's
    publisher grants may cross, under these audiences", then each served house's remote refs and their audiences
    read from its policy at that moment. Under one typed code it writes `register-place place:outside-home` with no
    parents (only if absent), `register-agent agent:remote-stores` acting for the owner's home, and `put-agent` at
    `place:outside-home`.
  - It refuses when `place:outside-home` exists with a parent, and when the agent exists already.
  - `agent add remote-stores` is refused with "use `agent remote-stores`", so the only way in shows the grants.
  - The daemon judges a remote ref as `agent:remote-stores` at `agent_place_at`'s answer only if that is
    `place:outside-home`; any other place becomes `""`, which `_requester_ok` refuses.
  - **Why it acts for the home:** `migrate` registers local receivers that way (`permission_cli.py:1142-1144`), so
    the home's `self` denies apply to it. A root place dominates only itself (`permissions.py:593-600`), so the
    home's `self` allows don't reach it (:960-974).
- **P12 Remote refs, in one place.** `sharing.py` gains `REMOTE_STORE_REF`
  (`urn:superyak:<64 hex>:store:<uuid>`), `REMOTE_SHIP_REF` (`urn:superyak:<64 hex>:ship:<participant id>`),
  `RESERVED_AGENT = "remote-stores"`, `is_remote(value)` and `receiver_ref(name_or_ref)`. The last returns a
  well-formed store ref as it is, `urn:engram:<name>` for a local `NAME`, and raises otherwise.
  - `_pattern_score` never lets a `*` pattern match a value starting `urn:superyak:` (in every dimension; only the
    publisher dimension carries one). So `*`, `urn:engram:*`, `urn:superyak:*` and `urn:superyak:<peer>:*` match no
    remote ref, on either side.
  - **Why `sharing.py`:** the daemon already imports it, and 2.2 names "sharing's validation" (finding 10).
- **P13 The `turnId` binding.**
  - After a remote `recall`, the daemon keeps `turn_id → (receiver ref, publisher name, frozenset of the candidate ids
    it returned, the time)` in an `OrderedDict` of at most 1,000, dropping the oldest, under a lock.
  - A remote `read` whose `turnId` is absent, older than 30 s by the daemon's own `clock`, or differs in receiver,
    publisher or any id gets `error_frame("TURN_UNBOUND")` before any read, and no disclosure. The entry isn't
    consumed, so a retry inside 30 s works.
  - Local frames never touch the map.
- **P14 The receiver's settings.** `lighthouse-receiver.toml` gains:
  - `[[remote_publishers]]`, each exactly `peer_id` (64 hex), `ship` (participant id) and `context` (a
    `context_ref`). A remote publisher is asked only when the recall's context equals its `context`.
  - `crossing_socket` (a path) and `receiver_ship` (this ship's participant id on its home peer), both required when
    any remote publisher is set.
  - `publishers` may then be empty, and `socket_path` is required only when it isn't. Local and remote together are 1
    to 8 (`MAX_PUBLISHERS`, `lighthouse_client.py:20`), with no duplicates.
  - **Weights stay local:** a remote publisher's weight is the default 1 (`neighbors.py:88`), and
    `lighthouse_validation.py:56-58` is unchanged (finding 11). Stage 2 has one remote publisher.
  - **`context` skips remote publishers:** `LighthouseSource` passes `remote_publishers=()`. Its later re-reads by
    `turnId` would fail P13, and 2.5's first rule puts remote text in a session only through that turn's `recall`.
- **P15 The read's `disclosureId` goes into the receiver's receipt.** `neighbor_arm` keeps each read reply's
  `disclosureId` (already checked by `validate_read`, `lighthouse_client.py:328`) and writes
  `receipt["extensions"]["engram:readDisclosures"]` = a list of `{publisher, disclosureId}`, before the digest.
  - **Why:** finding 9; the receipt schema allows it.
- **P16 `remote-deliveries.db`.**
  - **Where:** beside the receiving store's `graph.db` (`Path(storage.db_path).parent`), mode 0600, in its own module
    `engram/remote_deliveries.py`.
  - **Table:** `remote_deliveries(disclosure_id TEXT NOT NULL, publisher TEXT NOT NULL, memory_id TEXT NOT NULL,
    part TEXT NOT NULL CHECK(part IN ('item','sentence')), digest TEXT NOT NULL, at INTEGER NOT NULL)`, indexed on
    `digest` and `at`.
  - **What's recorded:** for each delivered remote item, the SHA-256 of its normalized text (`item`) and of each of its
    sentences of 12 words or more (`sentence`). Normalized: NFKC, `casefold()`, whitespace runs to one space,
    stripped. Sentences are split on the text before it is normalized (so newlines still split): after `.`, `!` or `?`
    followed by whitespace, or at a newline. Each sentence is then normalized, and its words are its
    whitespace-separated runs.
  - **What's refused:** a text whose normalized digest, or the digest of any of its sentences (of any length), is
    among the recorded digests of either part. The candidate side isn't limited to 12 words, so one short delivered
    item copied as one sentence of a longer note is still caught.
  - **Order:** in `neighbor_arm`, after the content budget and the final permission recheck, the record is written
    first and the receipt second. A failed record returns nothing, as a failed receipt does. A record left by a
    receipt that then failed guards text nobody received, which is harmless.
  - **Keeping:** rows older than 90 days are deleted at each write.
  - **Reading:** a missing file means nothing was ever delivered remotely, since a failed record delivers nothing. An
    unreadable file refuses, in every gate mode.
- **P17 A query too large for the route.** The asking peer measures the canonical signed request. Over 16 KiB, it
  answers `QUERY_TOO_LARGE` on the local hop and dials nothing. The listener's cap stays 16 KiB (finding 7).
- **P18 Reconciliation is a command.** `python -m superyak_peer crossings --data-dir D` (trusted local, read-only)
  lists recent `crossings` rows. For each `[[published]]` sidecar, opened read-only, it lists as **unsent** every
  disclosure whose receiver is a remote ref and which has no `crossings` row. This is 2.3's "the peer's
  reconciliation reports it as unsent", and re-check 2's nit ("say it records an attempt").
- **P19 Who asks a crossing before Rio Grande's store host exists. Decided by Tardis, 2026-11-03: today's
  in-process Engram MCP server asks,** from `recall`'s existing seam (`server.py:3232-3242`), under Rio Grande's two
  conditions (all hands, 4164449a). 2.4 says only the receiving home's store host asks, and the host is a week or more
  away.
  - **The option not taken:** stage 2 waiting for the host. It would match 2.4 by construction, but the measured
    crossing (rail commons stage 4, one way) would wait on Rio Grande's stage 1, and the host would need a new
    interface listing the stores it hosts.
  - **Condition 1: the asking sits behind one function with the shape the host will call.**
    `lighthouse_client.ask_crossing(receiver_instance, receiver_ship, publisher, frame, deadline_ms, *, socket_path)`
    returns the verified frame, or raises `NeighborUnavailable` with P8's code. `publisher` is the remote ship ref
    (`urn:superyak:<peer_id>:ship:<participant id>`); the function splits it into P8's `destination` and
    `publisher_ship`.
    - `neighbor_arm` reaches a remote publisher only through an `ask` callable of that shape (less `socket_path`), and
      never opens a socket for one itself.
    - Today `attach_neighbors` is the caller: it binds `socket_path` from the receiver's `crossing_socket` and passes
      the store's `instance_id` and `receiver_ship`.
    - Stage 1 swaps the caller, not the protocol: the host's `recall` passes its own `ask`. The local hop's request
      (P8) carries no word of which process asked, so nothing in `crossing.sock`, the route or the daemon changes.
  - **Condition 2: the interim's limit, named.** Two sessions of one ship asking at once each write receipts and
    `remote-deliveries.db` rows through their own server. That's today's behaviour, and it ends with the host.
    - **Why it's safe:** the receiver arm already writes its receipt on the server's own connection, one insert it
      commits by itself (`write_receipt` → `add_log_entry`, `storage.py:1802-1815`), as that store's only writer in
      single-session use. A crossing writes no memories and no trails: on the receiver it adds one log row and its
      delivery digests, and on the publisher's side nothing at all, since the daemon opens the house read-only
      (`lighthouse_daemon.py:3-9`, :99-105).
    - With two sessions, SQLite serializes the two writers, and both read one `remote-deliveries.db` beside the store,
      so either session's guard refuses text delivered to the other.
  - **What it still costs:**
    - It departs from 2.4's "only the store host" for the interim. This plan's fresh reviewer judges that, and the
      spec's next revision records it.
    - The peer's hosted check reads `[[hosted]]` (P2), a second list to retire when the host lands.
    - When the host lands, the thin client must forward `neighbors`, `degraded` and the guard (Rio Grande 3.4's client
      digest check), and the guard's placement is reviewed again.
  - Rollback: the receiver off.

**Stage 3's decisions**
- **P20 Key expiry comes from the cluster station spec.** The migration adds `scope` only. `ship_for_key`'s reason
  reads `revoked` from `revoked`, and `expired` from that spec's expiry column once it exists. Until then no key
  expires, and an unknown key answers `revoked`. **Why:** finding 5, and 1.2 leaves "its expiry columns" to that
  spec's review.
- **P21 Issuing and checking memory keys.**
  - A trusted-local command on the home, `ship-memory-key --username X`, issues one (`issue_ship_key(ship_id,
    scope='memory')`).
  - `PublicRoute.valid` passes the request's path, and asks `ship_key_is_valid(key, scope=…)` with `memory` for
    `/api/ships/memory` and `station` for every other path. So a memory key opens nothing else on a cluster's public
    route, and a station key never opens the memory route.
- **P22 The memory route's answers, and the transport.**
  - The route maps the host's answer to 1.2's table. A reach refusal off a cluster is 403 with no `code`, which the
    client reads as `unreachable` and so keeps its work. A per-key rate limit is 503 with `Retry-After`.
  - A body the route can parse but refuses (over 1 MiB, `deadline_ms` outside 500 to 10,000) is 400 or 413
    `{kind: "refused", code, seq}`. A body it can't parse has no `seq`, so it is 400 with no `kind`.
  - **The client half** (what the outbox does with each kind, "never queues over the cap", releasing a revoked
    outbox) is Rio Grande's thin client. Tardis builds `engram/memory_transport.py`: `MAX_BODY`, `post()`, and
    `answer_kind(status, headers, body)`, which returns the 3.11 kind for every row of the table, and never deletes a
    key. **Why there:** the client is Engram's, and one function holds the one mapping both sides test.
- **P23 A cluster station is marked at `init`.** `init --station-kind cluster` writes
  `peer_meta.station_kind = 'cluster'` with `INSERT OR IGNORE`, and it never changes. No row means not a cluster.

## Where each review change lands

- **Review (revision 1):**
  - M1: the ref from the verified origin (P7, Task 4); exact selectors (P12, Task 8); the ledger agent and place (P11,
    Tasks 8, 10); no local receiver read (Task 8); the receiver's ref for a remote publisher (P14, Task 11).
  - M2: inject granted on both sides (Deploy 5, 6); wake and nudge hold no remote text (Task 12).
  - M3: `purpose`, `k` up to 20, `turnId` and at most 5 ids (P4, Task 1); the publisher's frame inside a signed
    answer (P7, Task 4).
  - M4: the read-only daemon serves and the host never does (P2, Task 4); the sidecar untouched, the network half in
    `crossings` (Tasks 2, 4).
  - M5: 401 kinds, the 400 and 413 skip, 503 only with `Retry-After`, the missing rows (P22, Tasks 15, 17).
  - S1 deadlines (Tasks 6, 11); S2 caps and in-flight limits (P6, P7, P17, Task 5); S3 the named contact, not
    v2-only (P5, Task 3; Deploy 2); S4 order, replay floor, the signed answer (P3, Tasks 1, 3, 6); S5 the local hop
    (P8, Task 6); S6 reach (Tasks 16, 18); S7 stages and keys (Base, P20); S8 settings and live-recall only (P14, P19,
    Task 11); S9 route B carries nothing (not built here).
  - Nits: "no Engram store" (Task 3's probe); `turnId` binding (P13); the imprint refusal (P10); `disclosureId`
    throughout; a 403 with a `code` (P22).
- **Re-check 1:** A (P11, Tasks 8, 10); B (P16, Task 12; the client digest check is Rio Grande's, P19); C (Base, P9,
  Deploy); S-a (Tasks 15, 17); S-b (P2, P8); S-c (Tasks 2, 4, P18); S-d (Tasks 16, 18); S-e (Task 15, Base); S-f (P13,
  Task 9). Nits: `recall` (finding 3); UTF-8 size (P17); only `pair()` makes a contact (Deploy 2); `context` skips
  remote publishers (P14).
- **Re-check 2:** 1 (Task 8's ledger test); 2 (P11, Risks); 3 (P16, Task 12); 4 (P9, Tasks 7, 14, finding 6); 5
  (Deploy 2); 6 (P22, Task 17); 7 (P13, Task 9). Nits: reasons (Task 15); a revoked outbox (P22); an unpartnered
  disclosure (P18); a cluster station (P23).

## What changes

### Stage 2, the peer

**identity.py**
- The comment beside `RECORD_KEYS` reserves `crossing` and `crossing-answer` with `pull`, and
  `RESERVED_KINDS = frozenset({'pull', 'crossing', 'crossing-answer'})` sits beside it.
- `CROSSING_KEYS` (2.3's twelve keys) and `CROSSING_ANSWER_KEYS` (`version`, `kind`, `origin`, `destination`,
  `request_digest`, `nonce`, `frame`, `signature`).
- `crossing_shape_ok(request)`: exact keys and P4's types and ranges; `deadline_ms` an `int` from 100 to 10,000;
  `nonce` 32 hex; `at` an `int`; `signature` at most 128 characters.
- `sign_crossing(request)` and `verify_crossing(card, request)` (403 "Peer authentication failed", as `verify_pull`).
- `crossing_digest(signed)`, `sign_crossing_answer(answer)` and `verify_crossing_answer(card, answer, *, me,
  digest, nonce, kind)`, which raises `ValueError` on any difference, a frame kind that doesn't answer the request's,
  or a frame with no `disclosureId` string.

**peer_store.py**
- `PEER_SCHEMA` gains `crossings(disclosure_id TEXT PRIMARY KEY, origin_peer TEXT NOT NULL, receiver_ref TEXT NOT
  NULL, request_digest TEXT NOT NULL, nonce TEXT NOT NULL, at INTEGER NOT NULL)`, 2.3's columns exactly. Rows aren't
  pruned (Risks).

**crossing.py (new)**
- `load_settings(data_dir)` (P2); `Limiter` (P6); `daemon_call(socket_path, frame, deadline)`: one line out, one line
  in, at most 1 MiB, parsed with `parse`; `CrossingSocket` (P9).
- `serve(federation, raw)`, the publisher side, in 2.3's order:
  1. `parse(raw, limit=16 KiB)` and `crossing_shape_ok`, else 400 "Invalid crossing request";
  2. destination, else 403 "Not addressed to this peer";
  3. a paired origin of any card version, else 403 "Unknown or unpaired peer";
  4. `verify_crossing`, then the clock (403 `CLOCKS_DIFFER`), then the nonce under `_replay_floor` (409 "Replay"),
     as `federation.py:440-455`;
  5. the contact (P5), else 403;
  6. the map (P2), else 404 "No published house for that ship";
  7. the load (P6), else 429.

  Then it builds the ref `urn:superyak:<origin>:store:<receiver_instance>`, overwrites the frame's `receiver` and
  `publisher`, calls the daemon within the deadline, applies P7, inserts the `crossings` row, and returns the signed
  answer.
- `ask(federation, line)`, the asking side: P8's checks, P17's size check, the per-destination bound, then a request
  signed with `origin` = this peer, `nonce` = `uid()` and `at` = now, sent by `crossing_pinned`, and its answer
  verified before the frame is returned.

**federation.py**
- `_contact_confirmed` (P5), used by `connections()` and by `crossing.serve`.
- `serve_crossing(raw)` delegates to `crossing.serve`, so `create_listener`'s `getattr` finds it.

**transport.py**
- `CROSSING_ANSWER_CAP = 128 * 1024` and `crossing_pinned(card, body, *, deadline)`: `_dialable`, `_pinned_socket`
  and `_expire` against one monotonic deadline; POST `/federation/crossing`; a non-2xx is `PeerAnswer`; a 2xx needs a
  `Content-Length` within the cap, refused unread otherwise; a short body is `TimeoutError`.

**listener.py**
- `CROSSING_REQUEST_MAX = 16 * 1024`; `ROUTES` gains `'/federation/crossing': ('serve_crossing',
  CROSSING_REQUEST_MAX)`. The docstring says three routes.

**federate.py and \_\_main\_\_.py**
- `federate.py:5-6` says: it never opens a network listener; with `--crossing-socket` it opens one Unix socket, on its
  own thread.
- `federate --crossing-socket` and `federation-listen --crossing-socket` (P9). The socket starts after
  `federation_lock` and `keep_open` and stops in `finally`.
- `crossings --data-dir D` (P18).
- `federation-listen`'s help says events, pulls and crossings.

**Units, Makefile, packaging**
- `superyak-federate.service`: `Environment=FEDERATE_ARGS=` and `ExecStart=… federate --data-dir ${FEDERATION_DATA}
  $FEDERATE_ARGS` (unbraced, so an empty value adds no argument).
- `make federation-units FEDERATE_ARGS=--crossing-socket` writes `30-federate-args.conf` for the federate unit only
  (`Makefile:558-565`), and `federation-units-remove` removes it.
- `pyproject.toml`: `superyak_peer/crossing.py` in the sdist (:92's list) and the wheel (:252's); the new tests beside
  :184. `tests/test_packaging.py:97` imports `superyak_peer.crossing`; :156's set lists the new tests.

### Stage 2, Engram

**sharing.py**: P12's refs, `receiver_ref` and `RESERVED_AGENT`.

**lighthouse_policy.py**: `_pattern_score` (:78-83) refuses a prefix match on a `urn:superyak:` value (P12).

**lighthouse_daemon.py**
- `_request` (:785-798) and both `_allowed_audiences` calls (:958, :988-992) use `receiver_ref(frame['receiver'])`.
- `handle_frame` (:810-850), for remote frames: the malformed-ref refusal first; P10's gate refusal right after the
  gate is read (:825), before the policy loads; the imprint refusal once the house is checked out (:836).
- `_LedgerSide.__init__` (:483-496), for a remote ref: the agent is `agent:remote-stores`; the place is P11's;
  `_load_receiver_policy` isn't called; `legacy` holds the publisher layer only (re-check 2, change 1).
- `_recall` (:900-937) records P13's binding for a remote ref after its disclosure. `_read` (:978-1035) checks it
  first.
- `PublisherDaemon.__init__` gains the binding map and its lock.

**permission_cli.py**: `agent remote-stores` and the `agent add` refusal (P11).

**cli.py**: `fork_instance` (:15-45) refuses `remote-stores` before making the directory.

**policy_gen.py**: `build_publisher_policy` takes `remote_receivers`, a list of `(ref, audiences)` checked by
`REMOTE_STORE_REF`. Each gets an exact-ref rule and an `engram:audiences` entry keyed by the ref.

**lighthouse_receiver_config.py**: `load_settings` (:32-54) and `valid_publishers` (:26-29) per P14; the returned dict
gains `remote_publishers`, `crossing_socket` and `receiver_ship`.

**lighthouse_client.py**
- `CrossingClient(socket_path, timeout_s)`. `call(request, *, deadline)` sends P8's line, reads one line of at most
  160 KiB, and returns the inner frame through the same checks as `_decode_reply` (:65-83), or raises
  `NeighborUnavailable` with P8's code.
- `ask_crossing(receiver_instance, receiver_ship, publisher, frame, deadline_ms, *, socket_path)` (P19, condition 1):
  it builds P8's request from its arguments and makes one `CrossingClient` call.

**neighbors.py**
- `neighbor_arm` takes `remote_publishers=()`, `receiver_ship=None`, `receiver_instance=None` and `ask=None`. With
  remote publishers set and no `ask`, each shows in `diagnostics` as `NO_ASKER` and none is asked.
- After the local loop (:79-107), each remote publisher whose `context` matches: the ref
  `urn:superyak:<peer_id>:ship:<ship>`; `authorize` as for a local one; `deadline_ms` from the shared deadline, and
  `TIMEOUT` without a call under 100; `ask(…)` with a `recall` frame of `k=20`; `validate_trace` with the ref.
- In the read phase (:111-131), a remote publisher is read through `ask` with its trace's `turnId`, and its reply's
  `disclosureId` is kept (P15).
- Before the receipt (:160): P16's record of the delivered remote items, then `engram:readDisclosures`.
- `attach_neighbors` (:183-206), today's caller: it takes `crossing_socket` out of the settings, binds it into
  `ask_crossing` as `ask`, and passes `receiver_instance` from `storage.instance_identity()`.

**context_lighthouse.py**: `search` (:126-129) drops `crossing_socket` from the settings and passes
`remote_publishers=()` and no `ask` (P14).

**remote_deliveries.py (new)**: `path_for`, `normalize`, `sentences`, `digests`, `record(path, items, *, now)`,
`refused(path, texts, *, now)`.

**server.py**
- `_REMOTE_REFUSED = {"error": "this text was delivered from another peer's store and is never kept here",
  "layer": "rejected", "code": "REMOTE_DELIVERY"}` beside `_KEEP_REFUSED` (:2000).
- `_remote_refusal(*texts)` returns that reply, a fail-closed reply with the cause when the file is unreadable, or
  `None`.
- It is the first statement of `_keep_decision` (before :2087, so before :2091-2092 and :2104-2105), and runs at the
  top of `add_anchor` (`content`, `expected`), `task_update` (`content`), `dream_capture` (`reaction`), `jot` (`key`,
  `value`) and `clipboard_pin` (`text`), after each one's `_init()`.
- `recall`'s seam (:3232-3242) is unchanged. It calls `attach_neighbors`, which is today's caller of `ask_crossing`
  (P19), after the response is built.

**pyproject.toml**: `remote_deliveries` in `py-modules` (:41).

### Stage 2, docs
- `peer/PROTOCOL.md`: the crossing request, the answer, the statuses (P7), the local hop (P8), and the reserved kinds.
- The pull spec: §1's "It has no listening socket" (line 74) and §10 test 11 (line 368) say "no network listener; one
  Unix socket only under `--crossing-socket`", citing this plan.
- `engram/docs/lighthouse-receiver.md`: `[[remote_publishers]]`, remote refs, exact selectors, and the guard.
- The peer README: `crossings.toml`, `--crossing-socket` and `crossings`.

### Stage 3
- **db.py**: beside the other additive migrations (:100-134), `ship_keys` gains `scope TEXT NOT NULL DEFAULT
  'station' CHECK(scope IN ('station','memory'))`, guarded by `PRAGMA table_info`. Existing rows read `station`.
- **ships.py**: `issue_ship_key(ship_id, *, scope='station')`. `ship_for_key(key, presence=None, *, scope='station')`
  and `ship_key_is_valid(key, *, scope='station')` match on scope. A refusal raises `KeyRefused(Problem)` (401) with
  `kind` `revoked` or (P20) `expired`; an unknown key is `revoked`.
- **app.py**: `PublicRoute.valid` per P21. `POST /api/ships/memory`: `memory_member(request)` (scope `memory`); reach
  (tailnet only, except where `station_kind` is `cluster`); the limits; the envelope's `ship`, `agent_ref` and G13
  from the key and the client's half from the body; the host call; P22's mapping. The `Problem` handler (:330-332)
  adds `kind` to the body for a `KeyRefused`, and the memory route's refusals carry `kind`, `code` and `seq` the same
  way; every other route's body is unchanged.
- **\_\_main\_\_.py**: `init --station-kind`, `ship-memory-key` (P21, P23).
- **engram/memory_transport.py** (P22), and its line in `py-modules`.

## Tests that change

| Test | Change |
|---|---|
| `test_federate_never_listens` (test_federate.py:112-122) | becomes "no network bind; one Unix bind at `crossing.sock` only under `--crossing-socket`": `bind` is recorded, not refused; without the flag the list is empty |
| `test_only_its_two_routes_are_served` (test_listener.py:55-60) | renamed for three routes; `GET /federation/crossing` and `POST /federation/crossing/x` join the 404 cases |
| `test_a_body_over_its_cap_is_refused` (test_listener.py:63-66) | gains `('/federation/crossing', 16 * 1024)` |
| `COORDINATION_TABLES` (test_restore.py:2536-2548) | gains `crossings` |
| test_packaging.py:97 and :156 | import `superyak_peer.crossing`; list the new tests |
| stage 3: tests that build keys through `issue_ship_key` | unchanged, since the default scope is `station`; `test_public_route.py` gains the memory key's cases (Task 15) |

## Tasks (test-first; each test is written and seen failing before its code)

### Stage 2

**Task 0: base.** Cut `tardis/crossing` from this branch. Record on Tardis the whole peer suite's count (`make
check-peer`, browser tests included) and Engram's (`make check-engram`) as the baseline.

**Task 1: the wire** (`peer/tests/test_crossing_wire.py`):
- `crossing_shape_ok` accepts a recall and a read; it refuses each missing or extra key, each wrong type, a frame
  with an extra key, `k` 21, 6 ids, a query of 4,097 characters, `deadline_ms` 99 and 10,001, and a
  `receiver_instance` that isn't a canonical UUID.
- A 3.11 envelope (`session_id`, `outbox_id`, `seq`, `op_id`, …) is refused (spec section 4, "Two routes").
- Signatures: a crossing verifies; a pull doesn't verify as a crossing, nor a crossing as a pull, nor an answer as
  either.
- `RESERVED_KINDS` is disjoint from `RECORD_KEYS`, and `sign_record` refuses a `crossing-answer`.
- `verify_crossing_answer` refuses a changed signature, `request_digest`, `nonce`, `origin`, `destination`, an extra
  key, and a `read_result` answering a recall.

**Task 2: schema and settings** (`peer/tests/test_crossing_route.py`, `peer/tests/test_restore.py`):
- A store opened today has `crossings`, and it is classified.
- `load_settings` refuses an unknown key, a symlink, a `daemon_socket` named `host.sock`, a relative path and a
  duplicate ship. It resolves `ship` to a `users.id` of kind `ship` only, and picks up an edit without a restart.

**Task 3: the checks, in order** (same file). A fake daemon socket records every connection, so "no Engram store,
policy, ledger or sidecar was opened" is "the daemon socket saw nothing":
- 400 shape; 403 wrong destination, with **no nonce row**; 403 unpaired origin; 403 bad signature; 403 stale `at`;
  409 replay; 409 an `at` at the restore floor; 403 a held contact; 403 a contact whose confirmation no longer matches
  its card; 404 an unmapped `publisher_ship`. The daemon saw nothing for any of them.
- A held receiving ship and an unpaired origin also leave the sidecar fixture untouched (spec section 4's probe).
- A v2 (pull) origin card is accepted (S3: not v2-only).
- The order: a held contact's request with a bad signature is 403 "Peer authentication failed", and a wrong
  destination's replay is 403, not 409.

**Task 4: processing** (same file):
- The daemon receives the frame with `receiver` = `urn:superyak:<origin>:store:<instance>` and `publisher` = the
  mapped name, and every other member unchanged.
- The answer has exactly its keys and verifies with this peer's card; `request_digest` and `nonce` bind the request.
- A `crossings` row holds the frame's `disclosureId`, the origin, the ref, the digest, the nonce and `at`.
- A failed insert (patched) is 503 with no frame.
- A daemon error frame is 502; a daemon past the deadline is 504; an answer over 128 KiB, and a read whose content
  totals 32 KiB + 1, are 502. None writes a row.
- The same `instance_id` signed by another paired peer reaches the daemon with that peer's ref (spec section 4,
  "Audience", peer half).

**Task 5: the listener and load** (`peer/tests/test_listener.py`):
- `POST /federation/crossing` is served over HTTPS; 16 KiB + 1 is 413; the three-route test.
- With a fake daemon held open: two crossings from one origin are in flight; the third gets 429; a push to
  `/federation/events` and a pull both answer 200 meanwhile. With two origins, the fifth crossing in flight gets 429.
- With an injected clock, the 61st crossing in 60 s from one origin gets 429, and the next minute's first passes.

**Task 6: the asking side** (`peer/tests/test_transport.py`, `peer/tests/test_crossing_ask.py`):
- `crossing_pinned`, against a real TLS server: a pin mismatch writes zero bytes; a missing or over-cap
  `Content-Length` is refused unread; a short body is `TimeoutError`; the whole call ends by the deadline.
- `ask`: `NOT_HOSTED` for an unlisted store or the wrong ship; `NOT_PAIRED` for an unpaired destination or a pull
  card; `TIMEOUT` without a dial under 100 ms; `QUERY_TOO_LARGE` without a dial for 4,096 four-byte characters
  (P17).
- The request it sends carries `origin` = this peer and a fresh nonce, and verifies.
- Every bad answer from Task 1's list is `BAD_ANSWER` and returns no frame. A good one returns the frame unchanged.
- A third crossing to one destination waits, then runs when one finishes (P6).

**Task 7: the processes** (`peer/tests/test_federate.py`, `peer/tests/test_cli.py`):
- `federate --crossing-socket` binds one `AF_UNIX` socket at `<data>/crossing.sock`, mode 0600; without the flag
  nothing binds (the amended test).
- A handler that raises, and a server that dies, are logged and the socket comes back within 2 s, while `run_pass`
  keeps running. SIGTERM ends both.
- A request over the socket from a test client reaches `ask`.
- `federation-listen --crossing-socket` binds it; without the flag it doesn't.
- `crossings` lists a row, and lists a sidecar disclosure with no row as unsent (P18).

**Task 8: the publisher in Engram** (`engram/tests/test_lighthouse_policy.py`, `engram/tests/test_daemon_remote.py`,
with `FakeEmbeddings` from `test_lighthouse_daemon.py:25` and a fixture ledger):
- **Selectors:** `*`, `urn:engram:*`, `urn:superyak:*` and `urn:superyak:<peer>:*` don't match a remote ref; the
  exact rule does; local prefix matching is unchanged.
- **Refs:** malformed `urn:superyak:` receivers are refused, and `receiver_ref` maps local names as today.
- **Ledger, under `enforce`:**
  - with `remote-stores` unregistered, nothing is delivered and the receipt's refusal is `UNKNOWN_REQUESTER`;
  - registered at `place:outside-home`, an allowed memory is delivered and a memory the ledger keeps at home isn't;
  - placed anywhere else, nothing is;
  - **with no receiver file anywhere, a remote crossing is still delivered** (re-check 2, change 1).
- **No local file:** an `instances/<instance_id>/lighthouse-receiver.toml` and an agent named like it contribute
  nothing; `_load_receiver_policy` (patched to raise) is never called.
- **Audience:** with only `<A>:store:<X>` granted, `<A>:store:<Y>` and `<B>:store:<X>` get nothing.
- **P10:** under `off` and `shadow` a remote frame is `PUBLISHER_UNAVAILABLE` with no disclosure row; an imprint house
  refuses it; a remote read of 6 ids is `MALFORMED_FRAME`.
- **Records:** after `unshare`, the memory isn't delivered.
- The existing daemon, permissions-daemon and audience suites pass unchanged.

**Task 9: the `turnId` binding** (`engram/tests/test_daemon_remote.py`):
- A remote read is refused `TURN_UNBOUND` for an unknown `turnId`, another receiver ref, another publisher, an id not
  returned, and at 30.001 s on the daemon's clock.
- A read inside 30 s succeeds, twice.
- After 1,001 recalls the first binding is gone.
- A local read with an old `turnId`, 31 s later, still succeeds (the `context` re-read case).

**Task 10: the reserved agent** (`engram/tests/test_permissions_cli.py`, `engram/tests/test_cli.py`,
`engram/tests/test_policy_gen.py`):
- `fork_instance('remote-stores')` exits 1 and creates nothing.
- `agent add remote-stores` is refused.
- `agent remote-stores` prints the words, then each served house's remote refs and audiences; with the code it writes
  the place (with no parent), the agent (acting for the owner's home) and its place; run again, it is refused. A
  `place:outside-home` that has a parent is refused.
- `build_publisher_policy` with a remote receiver writes an exact-ref rule and its audience entry, and refuses a
  malformed ref.

**Task 11: the receiver** (`engram/tests/test_neighbors.py`, `engram/tests/test_lighthouse_client.py`,
`engram/tests/test_context_lighthouse.py`):
- `load_settings` takes `[[remote_publishers]]` with `crossing_socket` and `receiver_ship`, and empty local
  `publishers`. It refuses an unknown key in a remote table, a bad `peer_id` or `ship`, a missing `crossing_socket`,
  nine publishers in all, and a duplicate.
- `CrossingClient` against a fake socket returns the inner frame, and maps each P8 code, a timeout, an oversize line
  and a malformed line.
- `ask_crossing` sends exactly P8's keys, with `destination` and `publisher_ship` split from the ref, and refuses a
  malformed ref without connecting.
- `neighbor_arm` with a fake `crossing.sock` behind `ask_crossing`:
  - delivers a remote item;
  - never asks when the receiver's own policy denies `recall`, and never reads when it denies `inject_context`;
  - a slow publisher past the deadline delivers nothing and shows `degraded` (spec section 4, "Deadline");
  - a refusing remote publisher is in `diagnostics` and `degraded` by its ref;
  - another context's remote publisher is never asked;
  - the receipt's `engram:readDisclosures` holds the read's `disclosureId`.
- `LighthouseSource.search` with remote publishers configured never connects to `crossing.sock`.
- **The asking seam (P19, condition 1):**
  - `neighbor_arm` given a recording `ask` and no socket delivers through it, so the caller can be swapped. With no
    `ask` it reports `NO_ASKER` and opens no socket.
  - `attach_neighbors` calls `ask` with the store's `instance_id` and `receiver_ship`, and with
    `storage.conn.in_transaction` false.
- **The interim's limit (P19, condition 2):** two `Storage` connections on one store, as two sessions, each deliver
  through their own `attach_neighbors` at once. Both receipts and both sets of `remote_deliveries` rows land, and
  either session's guard refuses the text the other received.

**Task 12: remote deliveries and the guard** (`engram/tests/test_remote_deliveries.py`,
`engram/tests/test_permissions_keep.py`, `engram/tests/test_wake.py`, `engram/tests/test_nudge.py`):
- Normalization (NFKC, case, whitespace) and the sentence split, on fixed strings.
- `record` writes item and sentence digests; rows older than 90 days go at the next write.
- `remember` of a delivered item, and of one of its sentences of 12 words or more, is refused with the gate `off`,
  `shadow` and `enforce`, and with no `permission-uses.db` (both early returns).
- Parametrized over `jot` (project and global), `task_update`, `dream_capture`, `clipboard_pin` and `add_anchor`:
  each refuses a delivered item, and writes nothing.
- A paraphrase is kept (the stated limit). An unreadable file refuses; a missing one doesn't.
- A failed record (patched) suppresses the delivery in `neighbor_arm`.
- After a recall that delivered remote text, `wake()` and `nudge()` output none of it (spec section 4, "Inject").

**Task 13: end to end** (`peer/scripts/crossing_check.py`, run in "Checks before review"):
- Two throwaway peers on loopback: A, a push peer running `federation-listen` over real HTTPS, and M, a pull peer
  running `federate --crossing-socket`. They pair in process, as the test fixtures do (`test_listener.py:21-26`).
- A's Engram home runs the daemon with the fake embedder, under `enforce`, with `remote-stores` registered. M's home
  runs `neighbor_arm` against M's `crossing.sock`.
- A recall on M delivers from A's house, and the read's `disclosureId` is the same in M's receipt, M's
  `remote_deliveries`, A's sidecar and A's `crossings` (spec section 4, "Records").
- After `unshare` on A, nothing is delivered. After unpairing M on A, check 3 refuses.

**Task 14: docs, units and packaging**: the docs, unit, Makefile and packaging lines above.
`tests/test_station_units.py` checks that the federate unit carries `$FEDERATE_ARGS`, and that `federation-units`
writes and removes `30-federate-args.conf`.

### Stage 3 (after the host, the cluster spec and a serving home)

**Task 15: scoped keys** (`peer/tests/test_ships.py`, `peer/tests/test_public_route.py`):
- A store migrated from today's schema reads every key as `station`.
- A memory key gets 401 on `/api/chats` and on every route that calls `member`, `ship_member` or `ship_for_key`; a
  station key gets 401 on `/api/ships/memory` (S-e).
- A revoked key's 401 says `revoked`, an unknown key's says `revoked`, and, once the cluster column exists, an
  expired key's says `expired`.
- From Funnel on a cluster station, a memory key passes the public route only to `/api/ships/memory`.

**Task 16: the route and its reach** (`peer/tests/test_memory_route.py`):
- `ship` in the body is ignored; `ship`, `agent_ref` and G13 come from the key.
- A body over 1 MiB, and `deadline_ms` 499 and 10,001, are refused with `{kind: "refused", code, seq}`. An unparseable
  body is 400 with no `kind`.
- The per-key rate limit is 503 with `Retry-After`.
- From Funnel the route is 403 with no `code`, except on a cluster station (S-d).

**Task 17: the answers table** (`engram/tests/test_memory_transport.py`, and the route's half in
`peer/tests/test_memory_route.py`):
- Each row of 1.2's table, parametrized, maps to its 3.11 kind exactly once.
- A 413 for `seq` n gives `skip to n` carrying the station's code, and the next operation applies (against the host's
  test double, which accepts the skip only for `n = high + 1`; re-check 2, change 6).
- BrowserBoundary's 413 and any 4xx without `kind` are `unreachable`.
- `expired` replays under a renewed key; `revoked` never replays.
- The transport never deletes a key, unlike `dock.py:67-71`.

**Task 18: the cluster station**: `init --station-kind cluster` sets it once, a second `init` can't change it, and
the Funnel exception reads it.

## Checks before review

- The whole peer suite and the whole Engram suite on Tardis, browser tests included, against Task 0's baseline; and
  `make check-integration`.
- `make peer-bundle` and the packaging test: the wheel imports `superyak_peer.crossing` in a clean venv.
- `peer/scripts/crossing_check.py` passes.
- **Mutants**, each of which must fail the test written for it, run alone with `-k` (`make mutants SPEC=…`):
  - check 2 after the nonce insert;
  - the load check before the signature;
  - check 5 after the daemon call;
  - crossing nonces kept out of `pull_nonces`;
  - the frame's `receiver` passed through unchanged; its `publisher` passed through unchanged;
  - the ref built with an unverified origin field;
  - a `*` pattern matching a `urn:superyak:` value;
  - remote refs judged as `agent:<receiver>`;
  - the receiver legacy layer kept for remote refs;
  - a remote frame served under `shadow`;
  - an imprint house served to a remote frame;
  - the binding window at 300 s; the binding applied to local reads; the binding not checked;
  - an answer sent when the `crossings` insert fails; an answer over 128 KiB sent;
  - the asking side skipping the answer's signature, or its `request_digest`;
  - the hosted check removed from the local hop;
  - the remote guard placed after the gate-off return;
  - the guard missing from `jot`'s global scope (one per tool, by the parametrized test);
  - a failed remote record that still delivers;
  - a socket fault that ends `federate`; the socket opened without the flag;
  - `LighthouseSource` asking remote publishers;
  - `neighbor_arm` opening a `CrossingClient` itself instead of calling `ask` (P19, condition 1);
  - the read's `disclosureId` left out of the receipt.
- **By hand, by Andy:** two throwaway peer data dirs and two throwaway Engram homes on Tardis, as Task 13 sets up, but
  paired with `pair --as` in a real terminal, Andy typing each code. A ship never types, relays or computes a code
  (CLAUDE.md).

## Deploy (stage 2; each step is the named person's or ship's, and nothing runs on a merge alone)

The order matters twice: the code merges before anything uses it, and the publisher's grant exists before Andy
registers `remote-stores`, so the command shows him the grant he is agreeing to. Until step 5, every crossing fails
closed: P10 refuses remote frames outside `enforce`, and `_requester_ok` refuses an unregistered agent.

1. **The merge.** Rio Grande merges under law section 2, after the fresh Pi reviewer's verdict and each partner's yes.
   It restarts `superyak-federation-listen` and the lighthouse daemon on the Pi, checks them, and reverts and restarts
   if a check fails. Nothing crosses yet.
2. **The contact.** Rio Grande runs `make join-machine-plan` on the Pi, read-only, to confirm the tardis ship is a
   current, confirmed contact (check 5). If it isn't, it's paired as CLAUDE.md says: Andy reads the code of
   `card --username tardis --pull` on Tardis's terminal himself and types it into the Pi's pair box. No ship sees,
   relays or types it.
3. **The gate.** Rio Grande reads the Pi's effective gate for the published house, read-only. If it isn't `enforce`
   (P10), moving it is Andy's act at his own terminal (`engram-permissions gate enforce`, `permission_cli.py:1498`),
   after he weighs what `enforce` changes for the Pi's local frames.
4. **The publisher's settings.** After Andy's yes in the room, Rio Grande writes on the Pi:
   - the publisher policy's rule for Tardis's exact store ref (`urn:superyak:<Tardis peer_id>:store:<Tardis
     instance_id>`), for `recall` and `read`, in one context, with the work lane's audience in `engram:audiences`;
   - `crossings.toml`'s `[[published]]` entry for the publishing ship, its daemon publisher, socket and sidecar.

   Tardis posts its `peer_id` and its store's `instance_id`, which aren't secrets. Rio Grande posts the publishing
   ship's participant id.
5. **The ledger.** On the Pi, Andy runs `engram-permissions agent remote-stores`, reads the grant it lists (step 4's),
   and types its code. Then he writes the allows `agent:remote-stores` needs at `place:outside-home`, including the
   outside-home allow in his home layer (finite purposes, at most 366 days, named memories). `engram-permissions
   place show` prints the result. Ships never sign ledger records.
6. **The receiver** (Tardis, on its own machine, with Andy's yes):
   - its receiver settings with one `[[remote_publishers]]` (the Pi's `peer_id`, the publishing ship's participant
     id, the context), `crossing_socket` and `receiver_ship`;
   - a receiver policy granting `recall`, `read` and `inject_context` to `urn:superyak:<Pi peer_id>:ship:<id>` in that
     context;
   - `crossings.toml`'s `[[hosted]]` for the tardis ship and its store (P19's interim);
   - `make federation-units FEDERATION_DATA=$HOME/.local/share/superyak/tardis-peer FEDERATE_ARGS=--crossing-socket`,
     then a restart of `superyak-federate`.
7. **The measure.** Tardis runs a `recall` with that `lighthouse_context`. It reads the read's `disclosureId` from its
   receipt and its `remote_deliveries`; Rio Grande reads the Pi daemon's sidecar and the Pi's `crossings`, read-only,
   and runs `crossings` to show nothing unsent. Tardis posts the four in the room, then runs `lighthouse_sheaf` on a
   few shared topics. The post says plainly that the link is one-way: the Pi learns nothing from Tardis's store.
8. **Rollback.**
   - The receiver off: Tardis sets `enabled = false` in its receiver settings, or drops `FEDERATE_ARGS` and restarts
     `federate`.
   - Or Andy unpairs Tardis's peer on the Pi (an admin act); check 3 and check 5 refuse from the next request.
   - Code: Rio Grande reverts the merge and restarts. The `crossings` table stays, unused, and is copied by restores
     as coordination.

Stage 3 deploys under its own plan revision, once its three dependencies exist.

## Risks

- **What the shared agent gives up** (re-check 2, change 2). The ledger no longer holds per-store protections: no
  rule, retirement or grant names one remote store, and every ledger receipt says `agent:remote-stores`. Which store
  sees what lives in the policy file and the audience map, which the publisher's ship can edit and which are digested,
  not signed. The `crossings` table and the sidecar still name the store. The owner's cut-off for one store is a hold
  on its ship's contact, or an unpair, which check 5 enforces before any Engram read.
- **P10 may hold stage 2** until Andy moves the Pi's gate to `enforce`.
- **Same uid.** Any process of the Pi's user can talk to the daemon's socket and claim a remote ref, and any process
  of Tardis's user can talk to `crossing.sock` and claim a hosted store. That's 1.1's caveat; real isolation needs one
  uid per ship, which the spec doesn't require.
- **Whole answers are refused** over 128 KiB or 32 KiB of text (P7), so a read of several long memories delivers
  nothing from that publisher. The receiver reads at most `k` (1 to 5) items, and the refusal shows in `degraded`.
- **The guard stops copies, not paraphrases,** and nothing after 90 days (2.5, said plainly).
- **P19's interim limit.** Until the host lands, two sessions of one ship asking at once each write receipts and
  `remote-deliveries.db` rows through their own server, as every tool's writes do today. It's safe for P19's stated
  reasons (a crossing writes no memories and no trails, and the publisher writes nothing), and it ends with the host.
- **The TypeScript kit** still lets a prefix match a `urn:superyak:` value. The Python publisher and receiver decide
  crossings, and no vendored fixture uses that form (`test_vendored_fixtures_match_typescript_decisions` stays green).
- **`crossings` rows aren't pruned.** One origin at 60 a minute is at most 86,400 rows a day. That's revisited when a
  second origin asks.
- **Rio Grande's stage 1** rewrites the files Tasks 11 and 12 touch. A late rebase can move the guard; Task 12's
  parametrized test and its mutant catch a tool left out.
