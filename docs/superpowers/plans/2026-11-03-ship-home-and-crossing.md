# Plan: a ship's own home, and lighthouse crossings between peers

Tardis, 2026-11-03. **Revision 2.**
- Revision 1 (785bdf46) got APPROVE WITH CHANGES from a fresh reviewer
  ([plan review](../reviews/2026-11-03-ship-home-and-crossing-plan-review.md)). Its verdict says the changed parts need
  a re-read, not a new round.
- **Its two Must-fixes and nine Should-fixes are applied here as written,** each marked with its number (M1, M2,
  S1 to S9). Where it offered two fixes, the one taken is named: S2, S3 and S8.
- Its nits are numbered here in its order (nit 1 to nit 8), and its "What a builder would still invent" items B1 to
  B8. Each is applied and marked.
- It implements the approved spec `docs/superpowers/specs/2026-11-03-ship-home-and-crossing-design.md`, **revision 5**
  (785bdf46, plus the R5 items this plan revision adds there) (nit 1): stage 2 first, then stage 3. Stage 1 (own home
  on one machine) is Rio Grande's build and isn't planned here. Section numbers below are the spec's.
- The interface it meets is Rio Grande's section 3.11 (memory-follows-ship 888a5a2d).
- Where the spec leaves a choice open, the plan makes it, marks it **P1** to **P24**, and gives the reason. P19, who
  asks a crossing before Rio Grande's store host exists, is **decided by Tardis**: today's in-process Engram server
  asks, behind one function the host will call later, under Rio Grande's two conditions (all hands, 4164449a).
- Every concrete change the spec's three reviews and this plan's review name lands somewhere below; "Where each review
  change lands" lists them by number.
- Planning against the code found eleven places where the spec's words and the code differed. They are listed at the
  end of "What the code looks like today", each with the decision that handles it, and each is an R5 mark in spec
  revision 5.

**This is safety code** under law section 2: it decides who may read what leaves a store (the publisher's checks, the
crossing route, the receiver's records and its guard) and it changes how the permission ledger judges a requester
(`remote-stores`). So it gets a test-first build, each test written and seen failing before its code; a fresh reviewer
started on the Pi that took no part in writing it; and each partner's explicit yes before it merges. Nothing in
"Deploy" runs on a merge alone. **(S5)** That yes covers three decisions the spec's revision 5 now records as
decisions, not corrections: P9 (`federation-listen`'s socket only on request), P10 (the publisher home's whole gate at
`enforce`) and P19 (the in-process server asks until the host lands).

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
  (`__main__.py:931-951`) takes `federation_lock` (an flock, `dispatch.py:34-45`), then `keep_open`, then runs.
  `federation-listen` (:952-982) refuses a non-loopback host and a non-push mode, and takes no lock (S3).
- `join_plan.plan` counts a contact as confirmed when any confirmation row exists (`join_plan.py:66-69`), which is
  weaker than check 5 (nit 6).
- `peer_store.py:28-45`, `PEER_SCHEMA`, has no `crossings` table. `test_restore.py:2536-2548` lists every coordination
  table, and `:2551-2566` fails on an unclassified one.
- `tests/test_federate.py:112-122` fails on any `bind` or `listen` during a pass. `tests/test_listener.py:55-60`
  lists other methods and paths that must answer 404 (nit 2).
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
  match every value. `_pattern_score` serves allow and deny rules alike, and a deny wins only a specificity tie
  (:146-152) (S4).
- `server.py:1351-1355` opens `instances/<name>/graph.db` whenever it exists, so an instance directory can appear
  without `fork_instance` (nit 4).
- `lighthouse_protocol.py`: the local frames are `recall` (:213-238) and `read` (:264-284). `validate_frame`
  (:313-327) checks that fields are present, not that the key set is exact (`_required`, :205-206).
- The agent grammar is `_NAME` (`permissions.py:104`, used at :138-139), with no colon. `_requester_ok` (:2062-2067)
  needs a registered agent placed at the use's place, else `UNKNOWN_REQUESTER` (:2420-2421). `agent_place_at`
  (:908-912) returns the agent's place. A root place dominates only itself (:593-600), so a `self` allow in a home
  layer never reaches an agent at a root place (:960-974). That holds only while the place has no parent:
  `add-parent` (:3928-3931) can give it one later, and `_parents` (:575-576) has no removal (M2).
- How an allow's audience reaches an agent at a root place that acts for the home (S1): `commons` always (:962-963);
  `self` fails (above); a group needs its owner's home to dominate the place (:984); a place entry must dominate both
  the use's place and the agent's (:991). So only `commons` reaches `remote-stores`. Each consent layer passes only
  on an allow (:2318), and the use's place and the holding place are consent layers (:1443-1449).
- `permission_cli.py`: `agent add` and `agent place` (:443-452, parser :1413-1420) write `register-agent` and
  `put-agent`; `_perform` (:280-293) prints the change, asks the typed code and writes as the owner. `migrate`
  registers receivers acting for and placed at the owner's home (:1142-1144), and finds publisher policies by globbing
  every `instances/*/lighthouse-policy.json` (:969).
- Instance creation is `cli.fork_instance` (`cli.py:15-45`), which takes any name. Sharing refuses an imprint source
  (`sharing.py:109-110`); `validate_audience` (:43-48) checks values, not map keys. `policy_gen.build_publisher_policy`
  (:59-107) writes local receivers only, has no caller outside tests, and `policy_gen.py` has no command (S6).

**Engram, the receiver**
- `neighbors.neighbor_arm` (:25-180): one shared deadline (:47); a `LighthouseClient` built whatever is configured
  (:48), and `attempted` set only by a local publisher (:78, :87, :108-109) (B5); local publishers only (:79-80, names
  checked by
  `valid_publishers`, which needs at least one: `lighthouse_receiver_config.py:26-29`); `k=20` per publisher (:91);
  reads with the prefix stripped (:125); a 32 KiB total content budget (:17, :147-155); a content-free receipt written
  before delivery (:160-176), whose failure suppresses everything (:177-178).
- `validate_read` (`lighthouse_client.py:303-357`) returns items and drops the read's `disclosureId`, so a receiver
  receipt holds only the recall traces' ids (`neighbors.py:166`).
- `load_settings` (`lighthouse_receiver_config.py:32-54`) refuses any extra key (:40) and needs `socket_path`.
  `lighthouse_validation.py:53-58` refuses an `engram:weight` key that isn't `urn:engram:`.
- `attach_neighbors` needs the session's store to be its named instance's `graph.db` (`neighbors.py:191-197`), so a
  session that fell back to the default store gets `RECEIVER_CONFIG_INVALID` (B7).
- The receiver arm runs from `recall` (`server.py:3232-3242`), after the response is built, and from
  `context`'s `LighthouseSource` (`context_cli.py:89-92`, `context_lighthouse.py:126-129`), which re-reads by `turnId`
  later (`context_lighthouse.py:159`, `:171-174`). The wake and nudge hooks (`hooks/wake.py:145`,
  `hooks/nudge.py:92`) call no neighbor.
- `write_receipt` (`lighthouse_receipts.py:90-113`) logs the receipt in `graph.db`. The receipt schema lets
  `extensions` carry any `prefix:`-named member.

**Engram, the guard**
- `_keep_decision` (`server.py:2081-2120`) is the only guard. `remember` calls it (:1907), and so does `_keep_check`
  (:2179-2181), which tests use (nit 2). It returns early with the gate off (:2091-2092) and again when
  `permission-uses.db` is missing (:2104-2105).
- `permission-uses.db` is hash-chained (`permission_uses.py:1-7`) with a checked digest form (:30-32, :202-206).
- Eleven other tools store text and call no guard:
  - `add_anchor` (:3744-3765), `task_update` (:4113-4127), `dream_capture` (:4151-4168), `jot` (:4306-4326, both
    pads) and `clipboard_pin` (:4524-4539);
  - **(M1)** `challenge_instinct` stores `evidence` in an episode as "Evidence: …" (:3451-3461), after it has already
    weakened the instinct (:3448); `retire_instinct` stores `reason` as "Reason: …" (:3503-3507), after it has retired
    the instinct (:3500); `compress_commit` (:3645-3654) hands `summaries` to `Compressor.commit`, which stores each
    `content` as a semantic (`compress.py:551`, :567); `task_focus` stores `name` and `content` (:4094-4105);
    `dream_react` stores `reaction` (:4260-4265); `clipboard_remind` stores `text` (:4573-4576).
  - The wake hook injects the active task context, the clipboard's pins and reminders, and residues
    (`hooks/wake.py:349-358`, :370-384, :391-393). So these tools could break both of 2.5's rules.

**Stage 3's ground**
- `ship_keys` is `(id, ship_id, key_hash, created, last_used, revoked)` (`ships.py:32`): no scope and no expiry.
  `ship_for_key` and `ship_key_is_valid` (:119-143) accept any unrevoked key and give one 401 for every bad key.
- `PublicRoute` lets a public request through on any valid ship key (`app.py:157-168`); its own fault is a 503 with no
  `Retry-After` (:138-142). `is_public` (:68-81) counts compute-node clients as public. `BrowserBoundary` answers 413
  over 6 MiB before any route (:110-111). `ship_member` answers 403 with no code (:235-240). `tailnet_only`
  (:250-255) guards the imprint routes (:857-866).
- The dock client deletes its key on a 401 (`agent/superyak_agent/dock.py:67-71`). `peer_meta` has no `station_kind`.

**Found while planning: where the spec's words and the code differed**

Spec revision 5 corrects each, marked R5 (nit 1): 1 in 2.5's guard; 2 in 2.2's ledger; 3 and 7 in 2.3's request
table; 4, 9 and 11 in 2.4's receiver checks; 5 in 1.2's 401s; 6 in 2.1; 8 under 2.3's answer; 10 in 2.2's audience
map.
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
  - **(B2) Both tables name a ship by username,** resolved per request to a `users.id` of kind `ship`. The local hop
    sends `receiver_ship` as that participant id (P8), and it must equal the resolved id of a `[[hosted]]` row whose
    `instance_id` equals `receiver_instance`.
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
  - `crossing.CrossingSocket` binds `crossing.sock` (mode 0600, a symlink refused) in a `ThreadingUnixStreamServer`
    run by a supervisor thread. A fault in it is logged, and it restarts after 1 s. It shares only the `Federation`
    (identity and store reads), and never raises into `federate`.
  - **(S3; of the review's two fixes, the first) One owner of the socket.** Before binding, it takes an flock on
    `<data dir>/crossing.lock`, opened `O_NOFOLLOW` at 0600 and taken `LOCK_NB`, as `federation_lock` does
    (`dispatch.py:34-45`). It holds the lock for the socket's life. A second process gets "another process already
    serves crossing.sock" and exits 1. Only the lock's holder unlinks a stale `crossing.sock`, so no process can take
    over a live one. `federation-listen` takes no `federation_lock` (`__main__.py:952-982`), so the socket needs its own.
  - **(B3) Where it starts:** in `__main__.py`'s `federate` and `federation-listen` branches, not in `Federate`.
    `federate --crossing-socket` starts it after `federation_lock` and `keep_open`, before `run()`;
    `federation-listen --crossing-socket` starts it before `uvicorn.run`. Both stop it in `finally`.
  - **A narrowing, said plainly:** 2.1 says federation-listen "opens it". Here it opens it only when asked. In stage 2
    the Pi only answers, so its socket would have no use, and a listener nobody uses is surface.
- **P10 The daemon serves a remote frame only under `enforce`.** Under `off`, `shadow` or `closed`, a frame whose
  receiver is a remote ref gets `error_frame("PUBLISHER_UNAVAILABLE")` before any read, and no disclosure.
  - Two more daemon refusals for remote frames: a receiver that starts `urn:superyak:` but isn't a well-formed store
    ref, and a house that is an imprint (`store_identity.is_imprint`, `store_identity.py:152-153`), which answers
    `PUBLISHER_UNAVAILABLE`. A remote read with more than 5 ids is `MALFORMED_FRAME`.
  - **(nit 4)** A local frame whose receiver is `remote-stores` is `MALFORMED_FRAME`, before any read. An instance
    directory of that name can appear without `fork_instance` (`server.py:1351-1355`), and its frames would otherwise
    be judged as the reserved agent.
  - **Why:** finding 2. The spec's fail-closed claim, and re-check 2's "kept" list (the place is a consent layer;
    an outside-home allow needs finite purposes, at most 366 days and named memories: `permissions.py:3385-3398`),
    hold only when the ledger decides. The imprint refusal is the first review's nit, put where the house is known.
  - **Cost:** stage 2 waits until the Pi's gate is `enforce`, which is Andy's act (Deploy step 3).
- **P11 `remote-stores`: registered by one informed command, placed at a root place.**
  - `engram-permissions agent remote-stores` prints Rio Grande's words (77dec36f), "Every remote store this home's
    publisher grants may cross, under these audiences", then the remote refs and their audiences read at that moment.
    Under one typed code it writes `register-place place:outside-home` with no parents (only if absent),
    `register-agent agent:remote-stores` acting for the owner's home, and `put-agent` at `place:outside-home`.
  - **(B6) Which houses it lists:** every `instances/*/lighthouse-policy.json`, found as `migrate` finds publisher
    policies (`permission_cli.py:969`), each read with `load_owned_policy`. It lists every rule and audience entry that
    names a remote ref, by house. A policy it can't read is named as unreadable, so the owner knows the list may be
    short. It doesn't read the daemon's config, which can change without a ledger act.
  - It refuses when `place:outside-home` exists with a parent, and when the agent exists already.
  - `agent add remote-stores` is refused with "use `agent remote-stores`", so the only way in shows the grants.
  - The daemon judges a remote ref as `agent:remote-stores` at `agent_place_at`'s answer only if that is
    `place:outside-home`; any other place becomes `""`, which `_requester_ok` refuses.
  - **(M2) And only while `place:outside-home` is a root.** If `_parents(state, "place:outside-home")`
    (`permissions.py:575-576`) is non-empty in the frame's ledger state, the place becomes `""` too, so every crossing
    is refused (`UNKNOWN_REQUESTER`). The state is read per frame (`lighthouse_daemon.py:876`), so this holds at use
    time: a later `add-parent` (`permissions.py:3928-3931`) would make the home dominate the place, and every `self`
    allow in the home would then reach every remote store (:971-974).
  - **Why it acts for the home:** `migrate` registers local receivers that way (`permission_cli.py:1142-1144`), so
    the home's `self` denies apply to it. A root place dominates only itself (`permissions.py:593-600`), so the
    home's `self` allows don't reach it (:960-974).
  - **(S1) The records a crossing needs.** Only `commons` reaches `remote-stores` ("What the code looks like today"),
    and both the home's layer and `place:outside-home`'s are consent layers that need their own allow. So stage 2
    needs two allows, each:
    - `layer`: `place:home/<owner>` for the first, `place:outside-home` for the second;
    - selector: `audience: ["commons"]`, `requesters: ["agent:remote-stores"]`, `kinds: ["memory"]`, `memories`: the
      shared memories' objects (`mem:<instance>/<layer>/<id>`, `lighthouse_daemon.py:384-388`), `actions:
      ["recall", "read", "inject_context"]` (the daemon decides a read item as `inject_context`, :618, and deciding
      `inject_context` needs `read` in the same layers, or the ledger answers NO_ALLOW: the build's finding 3, section 2
      review S1), and `purposes: ["session-recall"]` (`recall`'s default, `server.py:2696`);
    - `valid_from` now and `valid_until` at most 366 days later, as an outside-home allow in a home layer must be
      (`permissions.py:3385-3398`).

    Task 8's fixture ledger, Task 13's check and Deploy step 5 write exactly these.
- **P12 Remote refs, in one place.** `sharing.py` gains `REMOTE_STORE_REF`
  (`urn:superyak:<64 hex>:store:<uuid>`), `REMOTE_SHIP_REF` (`urn:superyak:<64 hex>:ship:<participant id>`),
  `RESERVED_AGENT = "remote-stores"`, `is_remote(value)` and `receiver_ref(name_or_ref)`. The last returns a
  well-formed store ref as it is, `urn:engram:<name>` for a local `NAME`, and raises otherwise.
  - **(S4) Only an allow rule loses its wildcards on a remote ref.** `_rule_score` (`lighthouse_policy.py:95-111`)
    passes the rule's effect down, and `_pattern_score` refuses a `*` match of a value starting `urn:superyak:` only
    for an allow rule. So `*`, `urn:engram:*`, `urn:superyak:*` and `urn:superyak:<peer>:*` allow no remote ref, on
    either side, and the same patterns in a deny still refuse one. A deny wins only a tie (:146-152), so disarming
    denies too would let any allow through. With an exact allow (score 2) beside a `*` deny (score 1), the exact allow
    wins, as today.
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
  - **(S8; of the review's two fixes, the first) Leading Markdown markers are stripped** before normalizing: from the
    whole text and from each sentence, repeatedly, any leading `-`, `*`, `+` or `>`, or a number followed by `.` or `)`,
    when followed by whitespace. So "- " plus a delivered sentence, or "> " plus a delivered item, still matches.
    Spec 2.5 says so (R5).
  - **What's refused:** a text whose normalized digest is among the recorded digests of either part, or one of whose
    sentences of 12 words or more has a digest among them.
    - **(nit 8) Both sides count sentences only at 12 words or more.** Revision 1 checked every candidate sentence,
      which let a short delivered item bar that sentence from local notes for 90 days, a lever for the publisher. Now
      a short item blocks only a whole-text copy of itself. Spec 2.5 lists the gap among what it doesn't catch (R5).
  - **Order:** in `neighbor_arm`, after the content budget and the final permission recheck, the record is written
    first and the receipt second. A failed record returns nothing, as a failed receipt does. A record left by a
    receipt that then failed guards text nobody received, which is harmless.
  - **(S7) Two writers, and busy isn't unreadable.**
    - The file runs in WAL with a 2,000 ms busy timeout, so a guard's read never waits on a writer.
    - A write that stays busy past the timeout fails, and the delivery is suppressed (`RECORD_BUSY` in `diagnostics`).
    - A guard read that stays busy answers a distinct refusal with the cause "busy, try again", not the unreadable one.
      An unreadable file (not SQLite, the wrong table, or `SQLITE_CORRUPT`) refuses with its cause, in every gate mode.
    - P19's limit names both.
  - **Keeping:** rows older than 90 days are deleted in the record's own transaction, at most once an hour per file
    (the last prune's time is a row in a `meta` table), so concurrent writers don't each prune (S7).
  - **Reading:** a missing file means nothing was ever delivered remotely, since a failed record delivers nothing.
- **P17 A query too large for the route.** The asking peer measures the canonical signed request. Over 16 KiB, it
  answers `QUERY_TOO_LARGE` on the local hop and dials nothing. The listener's cap stays 16 KiB (finding 7).
  - **(S5) This whole-request measure is the only size rule.** Revision 5's first wording added "at most 12 KiB as
    UTF-8" for the query, but the other fields can reach about 5 KiB, so that never guaranteed a fit, and P4 never
    checked it. Spec 2.3 now states P17's rule instead (R5).
- **P18 Reconciliation is a command.** `python -m superyak_peer crossings --data-dir D` (trusted local, read-only)
  lists recent `crossings` rows. For each `[[published]]` sidecar, opened read-only, it lists as **unsent** every
  disclosure whose receiver is a remote ref and which has no `crossings` row. This is 2.3's "the peer's
  reconciliation reports it as unsent", and re-check 2's nit ("say it records an attempt").
  - **(nit 6)** `crossings --contacts PEER_ID` lists that origin's contacts by name and participant id, each with
    whether check 5 accepts it, by P5's helper. It prints no pairing code. `join_plan` counts any confirmation row
    (`join_plan.py:66-69`), so Deploy step 2 uses this instead.
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
    - **(S7)** That file runs in WAL with a busy timeout, so one session's guard never waits on the other's write. A
      record that stays busy suppresses its delivery, and a guard read that stays busy refuses with "busy, try again",
      told apart from an unreadable file (P16). Pruning runs at most once an hour, not on every write.
  - **What it still costs:**
    - It departs from 2.4's "only the store host" for the interim. This plan's fresh reviewer judges that, and the
      spec's next revision records it.
    - The peer's hosted check reads `[[hosted]]` (P2), a second list to retire when the host lands.
    - When the host lands, the thin client must forward `neighbors`, `degraded` and the guard (Rio Grande 3.4's client
      digest check), and the guard's placement is reviewed again.
  - Rollback: the receiver off.
- **P24 (S6) A command writes a remote grant into a publisher policy.** Nothing writes a publisher policy in
  production today: `build_publisher_policy` has no caller outside tests, and `policy_gen.py` has no command.
  - `python -m policy_gen grant-remote --house NAME --ref REF --context CONTEXT --audience AUDIENCE [--audience …]
    --purpose PURPOSE --until DATE` loads `instances/NAME/lighthouse-policy.json` with `load_owned_policy`. It adds one
    allow rule whose `publishers` is exactly `[REF]` (actions `recall` and `read`, that context and purpose, audience
    `self`, valid until `--until`) and the `engram:audiences` entry keyed by `REF`.
  - `REF` must match `REMOTE_STORE_REF` (P12), and each audience `validate_audience` (`sharing.py:43-48`). An existing
    rule or entry for `REF` is refused, not replaced.
  - It re-digests with `artifact_digest`, validates the result by loading it with `load_owned_policy` from a file
    beside the policy, keeps the old file as `lighthouse-policy.json.bak`, and renames the new one into place.
  - `build_publisher_policy` keeps its `remote_receivers` argument for generated policies. Both paths go through one
    `remote_grant(ref, audiences, …)` helper, so the validator sees every remote grant.

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
- **Plan review (revision 1):**
  - M1: the eleven-tool guard on raw arguments (server.py's changes, Task 12, its mutants; spec 2.5, R5).
  - M2: an unplaced `remote-stores` once `place:outside-home` has a parent (P11, Task 8, its mutant; spec 2.2, R5).
  - S1 the records (P11, Tasks 8, 13, Deploy 5); S2 the interim test moved to Task 12; S3 `crossing.lock` (P9,
    Task 7); S4 wildcard denies kept (P12, Task 8; spec 2.2, R5); S5 the spec's status line and request size (spec
    status, 2.3, R5); S6 `grant-remote` (P24, Task 10, Deploy 4); S7 WAL and busy (P16, P19, Task 12; spec 2.4, R5);
    S8 Markdown markers stripped (P16, Task 12; spec 2.5, R5); S9 what `enforce` changes (Deploy 3).
  - Nits: 1 the header and the R5 map; 2 the three citations ("What the code looks like today", Task 14); 3 `closed`
    (Task 8); 4 a local `remote-stores` frame refused (P10, Task 8); 5 the args drop-in removed (Units, Task 14); 6
    `crossings --contacts` (P18, Deploy 2); 7 the hold's limit (Risks); 8 the 12-word minimum (P16, spec 2.5, R5).
  - B1 (S1, S6); B2 (P2); B3 (P9); B4 (Task 13); B5 (neighbors.py's changes, Task 11); B6 (P11); B7 (Deploy 6); B8
    (Deploy 4).

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
  in, at most 1 MiB, parsed with `parse`; `CrossingSocket` (P9), with `crossing_lock(data_dir)` (S3).
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
- `_contact_confirmed` (P5), used by `connections()`, by `crossing.serve`, and by `crossings --contacts` (nit 6).
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
- `federate --crossing-socket` and `federation-listen --crossing-socket` (P9, B3): each branch takes
  `crossing_lock`, starts the socket (in `federate`, after `federation_lock` and `keep_open`), and stops it in
  `finally`. A held `crossing.lock` exits 1 with its message (S3).
- `crossings --data-dir D [--contacts PEER_ID]` (P18, nit 6).
- `federation-listen`'s help says events, pulls and crossings.

**Units, Makefile, packaging**
- `superyak-federate.service`: `Environment=FEDERATE_ARGS=` and `ExecStart=… federate --data-dir ${FEDERATION_DATA}
  $FEDERATE_ARGS` (unbraced, so an empty value adds no argument).
- `make federation-units FEDERATE_ARGS=--crossing-socket` writes `30-federate-args.conf` for the federate unit only
  (`Makefile:558-565`). **(nit 5)** Run without `FEDERATE_ARGS`, it removes that file, so a rollback that reruns it
  turns the flag off. `federation-units-remove` removes it too.
- `pyproject.toml`: `superyak_peer/crossing.py` in the sdist (:92's list) and the wheel (:252's); the new tests beside
  :184. `tests/test_packaging.py:97` imports `superyak_peer.crossing`; :156's set lists the new tests.

### Stage 2, Engram

**sharing.py**: P12's refs, `receiver_ref` and `RESERVED_AGENT`.

**lighthouse_policy.py**: `_rule_score` (:95-111) passes `allow = rule["effect"] == "allow"` through
`_selector_score` (:86-92) to `_pattern_score` (:78-83), which refuses a prefix match on a `urn:superyak:` value only
when `allow` is true (P12, S4).

**lighthouse_daemon.py**
- `_request` (:785-798) and both `_allowed_audiences` calls (:958, :988-992) use `receiver_ref(frame['receiver'])`.
- `handle_frame` (:810-850), for remote frames: the malformed-ref refusal first; P10's gate refusal right after the
  gate is read (:825), before the policy loads; the imprint refusal once the house is checked out (:836). A local
  frame whose receiver is `remote-stores` is `MALFORMED_FRAME` (nit 4).
- `_LedgerSide.__init__` (:483-496), for a remote ref: the agent is `agent:remote-stores`; the place is P11's, and
  `""` when `place:outside-home` has any parent in the frame's state (M2); `_load_receiver_policy` isn't called;
  `legacy` holds the publisher layer only (re-check 2, change 1).
- `_recall` (:900-937) records P13's binding for a remote ref after its disclosure. `_read` (:978-1035) checks it
  first.
- `PublisherDaemon.__init__` gains the binding map and its lock.

**permission_cli.py**: `agent remote-stores`, listing houses as B6 says, and the `agent add` refusal (P11).

**cli.py**: `fork_instance` (:15-45) refuses `remote-stores` before making the directory.

**policy_gen.py**: `remote_grant(ref, audiences, …)`, checked by `REMOTE_STORE_REF` and `validate_audience`, makes
one exact-ref rule and its `engram:audiences` entry. `build_publisher_policy` takes `remote_receivers` and uses it, and
the new `grant-remote` command (`main()`, with `python -m policy_gen`) uses it on a live policy (P24, S6).

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
- **(B5) With only remote publishers:** the `LighthouseClient` (:48) is built only when there are local publishers,
  and `attempted` (:78, :87) is set by a remote publisher whose recall grant passed, as by a local one. So the
  `:108-109` return stays right for both.
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

**remote_deliveries.py (new)**: `path_for`, `strip_markers` (S8), `normalize`, `sentences`, `digests`,
`record(path, items, *, now)` and `refused(path, texts, *, now)`, opening the file in WAL with a 2,000 ms busy timeout
and raising `RecordBusy` and `Unreadable` apart (S7).

**server.py**
- `_REMOTE_REFUSED = {"error": "this text was delivered from another peer's store and is never kept here",
  "layer": "rejected", "code": "REMOTE_DELIVERY"}` beside `_KEEP_REFUSED` (:2000).
- `_remote_refusal(*texts)` returns that reply; a refusal with the cause "busy, try again" when the file stays busy
  (S7); a fail-closed refusal with the cause when the file is unreadable; or `None`.
- It is the first statement of `_keep_decision` (before :2087, so before :2091-2092 and :2104-2105).
- **(M1) It runs in eleven more tools, on their raw arguments, after each one's `_init()` and before the tool writes
  anything:**
  - `add_anchor` (`content`, `expected`), `task_update` (`content`), `dream_capture` (`reaction`), `jot` (`key`,
    `value`) and `clipboard_pin` (`text`);
  - `challenge_instinct` (`evidence`), before `_storage.challenge_instinct` (:3448), since the episode wraps it as
    "Evidence: …" (:3455), which would defeat the sentence digests;
  - `retire_instinct` (`reason`), before `_storage.retire_instinct` (:3500), for the same reason ("Reason: …", :3506);
  - `compress_commit` (each summary's `content`), before `_compressor.commit` (:3654);
  - `task_focus` (`name`, and `content` when given), before `set_task_context` (:4105);
  - `dream_react` (`reaction`), before `record_reaction` (:4260);
  - `clipboard_remind` (`text`), before `add_reminder` (:4576).
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
| `test_only_its_two_routes_are_served` (test_listener.py:55-60, a list of other methods and paths that answer 404; nit 2) | renamed for three routes; `GET /federation/crossing` and `POST /federation/crossing/x` join the 404 cases |
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
- **(S3)** With one process holding `crossing.lock`, a second `federate --crossing-socket` or `federation-listen
  --crossing-socket` on the same directory exits 1 with the lock's message, and the first one's socket still answers.
  A stale `crossing.sock` with no lock holder is replaced.
- `crossings` lists a row, and lists a sidecar disclosure with no row as unsent (P18). `crossings --contacts` shows a
  held contact and one with a stale confirmation as refused, a current one as accepted, and prints no code (nit 6).

**Task 8: the publisher in Engram** (`engram/tests/test_lighthouse_policy.py`, `engram/tests/test_daemon_remote.py`,
with `FakeEmbeddings` from `test_lighthouse_daemon.py:25` and a fixture ledger holding P11's two allows, S1):
- **Selectors:** `*`, `urn:engram:*`, `urn:superyak:*` and `urn:superyak:<peer>:*` allow no remote ref; the exact
  rule does; local prefix matching is unchanged.
- **(S4) Wildcard denies still refuse:** a `*` deny and a `urn:superyak:<peer>:*` deny each refuse a remote ref
  when no exact allow names it; with an exact allow beside a `*` deny, the exact allow wins, as today.
- **Refs:** malformed `urn:superyak:` receivers are refused, and `receiver_ref` maps local names as today.
- **Ledger, under `enforce`:**
  - with `remote-stores` unregistered, nothing is delivered and the receipt's refusal is `UNKNOWN_REQUESTER`;
  - registered at `place:outside-home` with S1's two allows, an allowed memory is delivered and a memory the ledger
    keeps at home isn't; with either allow missing, nothing is;
  - placed anywhere else, nothing is;
  - **(M2)** with the home layer holding a `self` allow in place of S1's `commons` one (and S1's
    `place:outside-home` allow kept): nothing is delivered, because `self` doesn't reach a root place; then, after
    `add-parent place:outside-home place:home/<owner>`, still nothing, now `UNKNOWN_REQUESTER`. Without M2's check the
    second case would deliver, since the home would then dominate the place;
  - **with no receiver file anywhere, a remote crossing is still delivered** (re-check 2, change 1).
- **No local file:** an `instances/<instance_id>/lighthouse-receiver.toml` and an agent named like it contribute
  nothing; `_load_receiver_policy` (patched to raise) is never called.
- **Audience:** with only `<A>:store:<X>` granted, `<A>:store:<Y>` and `<B>:store:<X>` get nothing.
- **P10:** under `off`, `shadow` and `closed` (nit 3) a remote frame is `PUBLISHER_UNAVAILABLE` with no disclosure
  row; an imprint house refuses it; a remote read of 6 ids is `MALFORMED_FRAME`.
- **(nit 4)** A local recall and a local read whose receiver is `remote-stores` are `MALFORMED_FRAME`, with an
  `instances/remote-stores/` directory present.
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
- `agent remote-stores` prints the words, then the remote refs and audiences of every instance's policy, by house,
  and names an unreadable policy as unreadable (B6); with the code it writes the place (with no parent), the agent
  (acting for the owner's home) and its place; run again, it is refused. A `place:outside-home` that has a parent is
  refused.
- `build_publisher_policy` with a remote receiver writes an exact-ref rule and its audience entry, and refuses a
  malformed ref.
- **(S6) `python -m policy_gen grant-remote`** on a fixture house's policy adds exactly one rule and one audience
  entry for the ref, and the result loads with `load_owned_policy` and its digest verifies. It refuses a malformed
  ref, an invalid audience, and a ref already granted, each leaving the file unchanged. It keeps a `.bak`.

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
- **(B5)** With only remote publishers configured (no local ones, no `socket_path`), `neighbor_arm` builds no
  `LighthouseClient`, asks the remote publisher, and delivers; with its recall grant denied, it returns `None` as an
  all-denied local configuration does.
- `LighthouseSource.search` with remote publishers configured never connects to `crossing.sock`.
- **The asking seam (P19, condition 1):**
  - `neighbor_arm` given a recording `ask` and no socket delivers through it, so the caller can be swapped. With no
    `ask` it reports `NO_ASKER` and opens no socket.
  - `attach_neighbors` calls `ask` with the store's `instance_id` and `receiver_ship`, and with
    `storage.conn.in_transaction` false.
- Task 11 stubs the remote-deliveries record as a no-op. Its real record, and the interim's two-session test, are
  Task 12's (S2).

**Task 12: remote deliveries and the guard** (`engram/tests/test_remote_deliveries.py`,
`engram/tests/test_permissions_keep.py`, `engram/tests/test_wake.py`, `engram/tests/test_nudge.py`):
- Normalization (NFKC, case, whitespace) and the sentence split, on fixed strings.
- **(S8)** "- ", "* ", "> ", "1. " and "2) " before a delivered sentence or item still match, nested markers too
  ("> - "); a marker in mid-sentence is left alone.
- `record` writes item and sentence digests; rows older than 90 days go at a write an hour after the last prune, and
  not at an earlier one (S7).
- `remember` of a delivered item, and of one of its sentences of 12 words or more, is refused with the gate `off`,
  `shadow` and `enforce`, and with no `permission-uses.db` (both early returns).
- **(nit 8)** A delivered item of 6 words is refused when remembered whole, and is kept when it is one sentence of a
  longer note (the stated gap).
- **(M1) Parametrized over every guarded tool,** each refusing a delivered item, or one of its sentences of 12 words
  or more, and writing nothing:
  - `jot` (project and global), `task_update`, `dream_capture`, `clipboard_pin` and `add_anchor`;
  - `challenge_instinct`: the instinct's strength is unchanged and no episode is added, although the stored episode
    would read "Evidence: …";
  - `retire_instinct`: the instinct is still active and no episode is added;
  - `compress_commit`: a summary whose `content` is delivered text adds no semantic and marks no episode compressed;
  - `task_focus`: no task context is set, by `name` or by `content`;
  - `dream_react`: no reaction is recorded and no residue stored;
  - `clipboard_remind`: no reminder is added.
- A paraphrase is kept (the stated limit).
- **(S7)** An unreadable file (not SQLite, or the wrong table) refuses with its cause; a missing one doesn't. A file
  held under an exclusive lock past the busy timeout makes the guard refuse with "busy, try again", and makes a record
  fail with `RECORD_BUSY`, which suppresses the delivery. A WAL writer in progress doesn't block a guard's read.
- A failed record (patched) suppresses the delivery in `neighbor_arm`.
- **(S2) The interim's limit (P19, condition 2):** two `Storage` connections on one store, as two sessions, each
  deliver through their own `attach_neighbors` at once. Both receipts and both sets of `remote_deliveries` rows land,
  and either session's guard refuses the text the other received.
- After a recall that delivered remote text, `wake()` and `nudge()` output none of it (spec section 4, "Inject"). And
  since M1's tools refuse it, no later wake shows it as a task context, a pin, a reminder or a residue
  (`hooks/wake.py:349-358`, :370-384, :391-393).

**Task 13: end to end** (`peer/scripts/crossing_check.py`, run in "Checks before review"):
- **(B4) Two environments.** The script runs in the peer's venv, as `two_peer_check.py` does. It starts Engram's two
  halves as subprocesses with `uv run --locked --project engram python -I engram/scripts/crossing_check_engram.py
  daemon|ask …`. That helper holds a fixed-vector fake embedder of its own, since `FakeEmbeddings` lives in a test
  module. The two talk only over the daemon socket and `crossing.sock`, as in production.
- Two throwaway peers on loopback: A, a push peer running `federation-listen` over real HTTPS, and M, a pull peer
  running `federate --crossing-socket`. They pair in process, as the test fixtures do (`test_listener.py:21-26`).
- A's Engram home runs the daemon under `enforce`, with `remote-stores` registered and P11's two allows (S1), and its
  policy written by `grant-remote` (S6). M's home runs `attach_neighbors` against M's `crossing.sock`.
- A recall on M delivers from A's house, and the read's `disclosureId` is the same in M's receipt, M's
  `remote_deliveries`, A's sidecar and A's `crossings` (spec section 4, "Records").
- After `unshare` on A, nothing is delivered. After unpairing M on A, check 3 refuses.

**Task 14: docs, units and packaging**: the docs, unit, Makefile and packaging lines above.
`peer/tests/test_station_units.py` (nit 2) checks that the federate unit carries `$FEDERATE_ARGS`, that
`federation-units FEDERATE_ARGS=--crossing-socket` writes `30-federate-args.conf`, and that `federation-units` without
it, and `federation-units-remove`, remove it (nit 5).

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
  - a `*` pattern allowing a `urn:superyak:` value;
  - **(S4)** the wildcard refusal applied to deny rules too, so a `*` deny no longer refuses a remote ref;
  - remote refs judged as `agent:<receiver>`;
  - the receiver legacy layer kept for remote refs;
  - **(M2)** the parent check on `place:outside-home` removed;
  - a remote frame served under `shadow`; one served under `closed` (nit 3);
  - **(nit 4)** a local frame with receiver `remote-stores` served;
  - an imprint house served to a remote frame;
  - the binding window at 300 s; the binding applied to local reads; the binding not checked;
  - an answer sent when the `crossings` insert fails; an answer over 128 KiB sent;
  - the asking side skipping the answer's signature, or its `request_digest`;
  - the hosted check removed from the local hop;
  - the remote guard placed after the gate-off return;
  - **(M1)** the guard missing from each guarded tool in turn, one mutant per tool, each caught by its own case of the
    parametrized test: `jot` (project and global), `task_update`, `task_focus`, `dream_capture`, `dream_react`,
    `clipboard_pin`, `clipboard_remind`, `add_anchor`, `challenge_instinct`, `retire_instinct` and `compress_commit`;
  - **(M1)** `challenge_instinct`'s guard run on the stored "Evidence: …" text instead of the raw `evidence`, and
    `retire_instinct`'s on "Reason: …"; and `challenge_instinct`'s guard moved after `_storage.challenge_instinct`;
  - a failed remote record that still delivers;
  - **(S7)** a busy `remote-deliveries.db` read reported as unreadable; the prune run on every write;
  - **(S8)** the Markdown marker strip removed;
  - a socket fault that ends `federate`; the socket opened without the flag;
  - **(S3)** `crossing.lock` not taken, so a second process takes over the live socket;
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
2. **The contact.** Rio Grande runs `python -m superyak_peer crossings --data-dir <the Pi's> --contacts <Tardis
   peer_id>` on the Pi, read-only, to confirm check 5 accepts the tardis ship by P5's rule; it prints no code (nit 6).
   `make join-machine-plan` isn't enough, since it counts any confirmation row (`join_plan.py:66-69`). If check 5
   refuses, the ship is paired as CLAUDE.md says: Andy reads the code of `card --username tardis --pull` on Tardis's
   terminal himself and types it into the Pi's pair box. No ship sees, relays or types it.
3. **The gate.** Rio Grande reads the Pi's effective gate for the published house, read-only. If it isn't `enforce`
   (P10), moving it is Andy's act at his own terminal (`engram-permissions gate enforce`, `permission_cli.py:1498`).
   **(S9) Before he does, Rio Grande lists what `enforce` changes on the Pi, beyond its local frames:**
   - the gate is the home's (`server.py:2200-2203`), so every Pi session's `remember` guard starts deciding `imprint`
     for delivered content, and refusing genome keeps of it (`server.py:2081-2120`);
   - `enforce` needs a ledger: with none, the effective gate is `off`, or `closed` when a house carries a ledger id,
     never `enforce` (`permission_ledger.py:2139-2151`);
   - every served house needs migration 029, or `enforce` serves it nothing (`lighthouse_daemon.py:375-381`,
     :859-863). Rio Grande checks each house read-only first.
4. **The publisher's settings.** After Andy's yes in the room, Rio Grande writes on the Pi:
   - **(S6)** with `python -m policy_gen grant-remote` (P24), the house's rule for Tardis's exact store ref
     (`urn:superyak:<Tardis peer_id>:store:<Tardis instance_id>`), for `recall` and `read`, in one context, with the
     work lane's audience in `engram:audiences`;
   - `crossings.toml`'s `[[published]]` entry for the publishing ship, its daemon publisher, socket and sidecar.
     **(B8)** The publishing ship is a `ship` user on the Pi, as P2 requires: Rio Grande names it (rio-grande is
     expected) and the daemon publisher that serves the house, read from the Pi's daemon config, before Andy's yes.

   Tardis posts its `peer_id` and its store's `instance_id`, which aren't secrets. Rio Grande posts the publishing
   ship's participant id.
5. **The ledger.** On the Pi, Andy runs `engram-permissions agent remote-stores`, reads the grant it lists (step 4's),
   and types its code. **(S1)** Then he writes P11's two allows, each with `audience: ["commons"]`, `requesters:
   ["agent:remote-stores"]`, the shared memories by name, `actions: ["recall", "read", "inject_context"]` (all three:
   without `read` the first crossing answers NO_ALLOW, section 2 review S1), `purposes:
   ["session-recall"]` and at most 366 days: one with `--layer place:home/andy`, one with `--layer
   place:outside-home`. `engram-permissions place show` prints the result. Ships never sign ledger records.
6. **The receiver** (Tardis, on its own machine, with Andy's yes):
   - **(B7)** first, a check that Tardis's sessions run on the named instance `tardis`, whose `graph.db` exists, so
     `attach_neighbors`'s store check passes (`neighbors.py:191-197`) and `server.py:1352-1355` doesn't fall back to
     the default store;
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
   - The receiver off: Tardis sets `enabled = false` in its receiver settings, or reruns `make federation-units`
     without `FEDERATE_ARGS`, which removes the drop-in (nit 5), and restarts `federate`.
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
- **(nit 7) A hold on one ship trusts the origin peer.** The publisher can't bind an `instance_id` to a ship, so a
  paired origin could name another of its contacts as `receiver_ship` and keep crossing for a held one's store. A
  hold cuts off an honest origin's ship; an unpair of the whole origin peer is the real cut-off.
- **P10 may hold stage 2** until Andy moves the Pi's gate to `enforce`.
- **Same uid.** Any process of the Pi's user can talk to the daemon's socket and claim a remote ref, and any process
  of Tardis's user can talk to `crossing.sock` and claim a hosted store. That's 1.1's caveat; real isolation needs one
  uid per ship, which the spec doesn't require.
- **Whole answers are refused** over 128 KiB or 32 KiB of text (P7), so a read of several long memories delivers
  nothing from that publisher. The receiver reads at most `k` (1 to 5) items, and the refusal shows in `degraded`.
- **The guard stops copies, not paraphrases,** nothing after 90 days, and not a delivered item under 12 words copied
  inside a longer text (2.5, said plainly; nit 8). Leading Markdown markers no longer hide a copy (S8).
- **P19's interim limit.** Until the host lands, two sessions of one ship asking at once each write receipts and
  `remote-deliveries.db` rows through their own server, as every tool's writes do today. It's safe for P19's stated
  reasons (a crossing writes no memories and no trails, and the publisher writes nothing), and it ends with the host.
  **(S7)** The file runs in WAL with a busy timeout. A record that stays busy suppresses its delivery, and a guard read
  that stays busy refuses with "busy, try again", so a busy file costs a retry, never a silent pass.
- **The TypeScript kit** still lets a prefix allow match a `urn:superyak:` value. The Python publisher and receiver decide
  crossings, and no vendored fixture uses that form (`test_vendored_fixtures_match_typescript_decisions` stays green).
- **`crossings` rows aren't pruned.** One origin at 60 a minute is at most 86,400 rows a day. That's revisited when a
  second origin asks.
- **Rio Grande's stage 1** rewrites the files Tasks 11 and 12 touch. A late rebase can move the guard; Task 12's
  parametrized test and its mutant catch a tool left out.

## Plan re-check: decided items (approved)

The same fresh reviewer re-read revision 2 and gave **APPROVE WITH CHANGES**
([re-check](../reviews/2026-11-03-ship-home-and-crossing-plan-recheck.md)). M1 and M2 are closed. Its four remaining
items are decided here, and it said none needs another re-read.

1. **The S4 test gains a tie case.** A `*`-publisher deny with an exact purpose, against an exact-ref allow with
   `purposes: ["*"]`: the deny wins with `EXPLICIT_DENY`. The S4 mutant must fail this case. That's Task 8.
2. **Four more free-text tools are guarded,** so spec 2.5's "every tool that stores text at the home" holds:
   - `log_outcome`'s note (server.py:3255);
   - `instinct_feedback`'s context (:3380);
   - `share`'s reason (:2383), which goes into the published house, so a remote passage could otherwise be
     republished;
   - `assessment_report`'s text fields.

   They're guarded on raw arguments before the write, as M1's eleven are. Task 12's parametrized test gains a case
   for each, and a mutant for `share`.
3. **The guard's limit, stated as the general rule** in spec 2.5 and Risks:
   - only items and sentences of 12 words or more are recorded and checked;
   - a delivered sentence under 12 words is never caught, however long its item;
   - nor is a 12-word sentence carried with other words on the same line ("Note: …").

   The guard catches verbatim whole items, and verbatim sentences of 12 words or more, and nothing else.
4. **Build details:**
   - **The guard opens `remote-deliveries.db` read-write,** in WAL, as the record does. A read-only open of a WAL
     file without `-wal` and `-shm` would read as unreadable and refuse every write. The file is local and the
     same user's.
   - **When `crossing.lock` is held,** `federation-listen` and `federate` start **without** the socket, log it, and
     report it in their status. Exiting would stop events and pulls. Task 7 tests that events and pulls keep flowing.
   - **`grant-remote`** names each rule `remote:<origin peer 12>:<instance_id>`, sets `validFrom` to now, and holds an
     flock on the policy file for its whole edit, so two runs can't interleave. Task 10 tests a second concurrent run
     refused.

**Deploy gains a ship-side step before Andy's sitting** (Rio Grande, all hands d91dddb5). The Pi's publishing ship is
`rio-grande`, its only instance. It publishes nothing yet: no `lighthouse-policy.json`, no `lighthouse-receiver.toml`,
0 `shared_memories`, and 7 work-lane episodes. So before step (b):
- rio-grande migrates its file memories into its store;
- it runs the publisher daemon for its instance;
- it shares **chosen memories only**, to the `tardis` store's exact ref through `share`: memories it put in itself with
  `remember(work=True)`, shared one by one, each read before it's shared. **Never a lane-wide set** (Serenity and Rio
  Grande, all hands 2069b049 and 22ac1dd4). The work lane isn't "fit to share": the nudge hook files any novel typed
  prompt there as `source='auto'`, a person's own words (hooks/nudge.py:543-547).
- **This step waits on `fix:share-refuses-captured-memories`** (Rio Grande, d07bff9a, safety code), so `share` refuses
  a captured memory, and any semantic built from one, before anything crosses.

That's the ship's own act on its own memories, and before the gate is raised `share` answers the ship. Otherwise the
first crossing would answer "absent", and teach nothing about receipts or lighthouse_sheaf.

## After approval: an expiry someone will see (Serenity, all hands 6915cfbf)

The Mac's lighthouse receiver rule expired 2026-10-15, and recall fell back to local with no word for three weeks. Every publisher rule there ends 2027-01-01. So `grant-remote` (P24) never writes an open-ended grant:
- It sets `validUntil` explicitly. The default is 90 days, and `--until` sets it, up to 366 days. The date is printed in its output.
- Rio Grande's fix:lighthouse-expired-rule-silent makes runtime status warn 14 days ahead and names `OUTSIDE_VALIDITY` in a recall's diagnostics. A crossing that hits an expired publisher rule shows that code in `neighbors`, never silence. Task 10 tests the default date and the `--until` cap.
- Deploy step 4 records the date in the room, so a person sees it.

## Build findings, stage 2 (Tasks 0-14, built 2026-11-04 on main 4be306de)

The builder followed the plan's intent wherever main had moved since it was written (b7d91462), and stopped to report
where an assumption no longer held. Points 1 to 5 correct the plan's text, and point 1 is a decision for the partners.

1. **Check 5 and owner trust. OPEN, a decision for Rio Grande and Serenity.**
   - **What's built:** P5's helper already exists as `owner_trust.code_current`, and check 5 is
     `federation.contact_current`: paired, not held, and `code_current`. So a ship contact confirmed only by an owner
     trust, with no typed code, is refused. That's the conservative reading of spec 2.2's "a current typed
     confirmation".
   - **What spec 2.2 also says:** "by the rule `connections()` uses", and `connections()` reports a trust-made ship as
     "confirmed by owner trust".
   - **Tardis's proposal:** accept a trust-made ship contact while its trust is live (not revoked, not expired), with
     holds applying as now. Cluster ships are trust-paired, so with the conservative rule no cluster ship could ever
     cross.
   - **For stage 2,** the tardis ship is code-confirmed on the Pi, so the first crossing works either way.
2. **P8 and P17.** A 16 KiB cap on the local line made P17 unreachable, since P17's own example (4,096 four-byte
   characters) is over 16 KiB as a local line. So the peer reads the local line up to 32 KiB, P17 still measures the
   signed request at 16 KiB, and a BAD_REQUEST code was added.
3. **P11 and S1's allows** need `read` as well. Deciding `inject_context` requires recall, read and `inject_context`,
   or the ledger answers NO_ALLOW. The tests and Task 13 use all three, and Deploy step 5's allows read "recall, read
   and inject_context".
4. **M2 can't happen through the ledger:** rule P26 keeps a one-segment place a root, at registration and through
   `add-parent`. The daemon's and the CLI's parent checks stay, as defence in depth. Their tests simulate a parent
   through `permissions._parents`.
5. **B5's "returns None"** is out of date. With main's lighthouse diagnostics, an all-denied configuration returns an
   empty result that names its code, and remote-only matches that.
6. **Moved code, intent kept:**
   - The daemon's eligible-set cache, `_FrameHouse` and LEDGER_BUSY moved. A busy ledger still answers LEDGER_BUSY
     before the enforce check, and the cache key carries agent and place, so remote crossings share one
     `remote-stores` entry.
   - Two newer main rules apply. Only reviewed code enters `store.reading()`, so crossing.py uses
     `store.transaction()` as `serve_pull` does. Contact names show through `contact_labels`.
7. **The Deploy order before the first crossing** (Rio Grande, all hands c858a53c):
   1. Restart rio-grande's session, so its Engram server postdates 53d22df0, and check that `status()` names migration
      030.
   2. Rio Grande shares its chosen memories.
   3. Andy's one sitting: `migrate`, `agent remote-stores` at `place:outside-home`, and `gate enforce`.
   4. Tardis's `federate` runs with `--crossing-socket`.
   5. The first recall.
