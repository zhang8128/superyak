# Review: a ship's own home, and lighthouse crossings between peers

**Verdict: REVISE.**

Draft 1 (d0cd0ec2), checked against Rio Grande's half (8a5df4da), the cited specs and the code. The two-route split, the checks up to the signature and unpair as the rollback hold. But the crossing copies the local daemon's wire format, not its model of who the receiver is. A remote receiver can't pass today's publisher checks without a format change the spec doesn't name, and the request lacks fields those checks need.

## Majors

**M1. "The audience is a store" needs a receiver identity the spec doesn't define.** The daemon keys every receiver check off one bare local name:
- the rule selector `urn:engram:{receiver}` (engram/lighthouse_daemon.py:785-798);
- the `engram:audiences` key (:208-236, :958, :988-992);
- the ledger agent `agent:{receiver}` and its place (:483-486);
- the receiver's own policy, read from the publisher's own `instances/<receiver>/` (:499-512).

A remote name that matches a local instance is judged by that store's policy and ledger rows. One that matches nothing has no receiver layer (:515-516), so `enforce` refuses everything. `urn:engram:*` matches any name (lighthouse_policy.py:78-83), and any receiver a rule names gets `group:outside-home` (:229-233).
*Fix:*
- A remote receiver ref the destination builds from the verified `origin` and the request's `instance_id`, such as `urn:superyak:<peer_id>:store:<instance_id>`, which can't match a local `NAME` (lighthouse_receiver_config.py:13).
- Only an exact selector matches it (a code change).
- Its ledger agent and place, whether outside-home applies, and no local receiver-policy read for it.
- The receiver's ref for a remote publisher (neighbors.py:80, 88).

**M2. "Recall and read, never `inject_context`" contradicts Engram's own meaning.** In Engram, delivering read text is `inject_context`: the receiver requires it before every read and before delivery (neighbors.py:121, 139), and the publisher decides each read item as it (lighthouse_daemon.py:604-636). It's never a wire action (:813). So stage 2's measure needs an inject grant on both sides, and "refused by shape" tests nothing. *Fix:* say concretely what is forbidden across peers (for example, remote text never enters wake or nudge context), and test that.

**M3. The request lacks what the publisher's checks need, and the response is the wrong object.**
- **Missing fields:** both frames require `purpose`, which is a policy dimension (lighthouse_policy.py:25; lighthouse_protocol.py:213-238). `read` also requires `turnId` (:264-284). Neither is in the table.
- **Untyped fields:** `receiver` holds two values with no type, and `context` has no stated type.
- **Ranking:** the receiver asks each publisher for 20 candidates and fuses them down to `k` (neighbors.py:91-92, 112). A recall `limit` of 1-5 breaks that ranking.
- **Response:** `neighbors` is the object the receiver assembles (neighbors.py:179). A publisher returns `recall_result` or `read_result` with a `disclosureId` (lighthouse_protocol.py:241-293).

*Fix:* carry the local frame's fields (`purpose`; `k` up to 20 for recall; `turnId` and at most 5 ids for read), and return the publisher's frame inside a signed answer.

**M4. The spec doesn't name the process that serves a crossing, so "never a write" has no basis.**
- The store host is the only writer, and its `recall` writes access counts and log rows (Rio Grande §2, 3.5). A crossing through it writes the publisher's store and puts another ship's queries in its trails.
- Only the existing daemon opens the published house read-only (lighthouse_daemon.py:3-9, 99-105).
- "The publisher writes a receipt in the published house's log" is false. The daemon writes a sidecar (:65-70, 182-205), and the sidecar has no columns for origin, query digest or delivered digests.

*Fix:* name the read-only daemon (or a read-only host path) as the server, forbid the host's tools here, and specify the sidecar change.

**M5. The own-home error table can lose work or stall it.**
- **401:** "revoked" isn't one of the five kinds in 3.11. Today's dock client deletes the key on 401 (agent/superyak_agent/dock.py:67-71). A per-job key that expires mid-session must keep the outbox for the station's drain (3.9).
- **400 and 413** never reach the host, so `high` never advances and every later operation waits forever: the host applies only `high + 1` (3.3), and quarantine counts host failures only (3.9).
- **503:** "503 means retry" overlaps "a station 5xx means unreachable". The public route's own 503 sends no `Retry-After` (peer/superyak_peer/app.py:138-142).
- **Missing rows:** `expired`, and `already applied` for a replayed read (3.3).

*Fix:* on 401, stop and keep the outbox (amend 3.11 for a sixth kind). Record a station-side refusal at the host at that `seq`, or never queue an operation over the cap. Only a 503 with `Retry-After` means retry. Add the missing rows.

## Should-fix

1. **Deadlines.** The receiver shares one deadline across publishers and the recall-then-read pair: 2 s by default, anything in (0, 10] (lighthouse_receiver_config.py:43-47; neighbors.py:47, 89-127). A 2,000 ms floor makes the read, and often the recall, unsendable, and 2.1's "2 to 10 s" is false. Take 100-10,000 ms as time remaining, and bound the pinned dial by it (`pull_pinned` allows 10 s to headers).
2. **Caps.**
   - federation-listen caps each route (listener.py:13-14; pull 16 KiB). A crossing needs about 16 KiB, not 1 MiB. State the response cap.
   - The query cap is 2,000 characters here, 4,096 locally (lighthouse_client.py:18).
   - Handlers run in `asyncio.to_thread` (listener.py:79), so 10 s crossings can starve events and pulls. Cap crossings in flight, per origin and in total.
   - 60 a minute per origin is the ceiling for a whole cluster station; say so.
3. **Check 3 against the code.** Holds and confirmations belong to contacts (federation.py:78, 151-193), and `peers` has only `paired` (:140). "Retired" and owner trust aren't built yet (spec-machine-trust, plan e1186af4). Name the contact that is checked, and how a receiving ship becomes one. Don't copy pull's v2-only check (:438-439).
4. **Check 4 and the answer.**
   - Signature, then clock, then nonce insert, as `serve_pull` (federation.py:440-455). Reuse the restore replay floor (:408-419); pick 403 or pull's 409 "Replay".
   - Give the signed answer exact keys and its own reserved kind, binding the request's nonce, origin, destination and digest. The origin peer verifies it, since Engram holds no card.
5. **The local hop** from a store to its peer is unspecified. The peer must take `receiver` from the caller, not the body; state the same-uid caveat, as 1.1 does. The Mac never listens and reaches its peer in process (pull spec §1), so there Engram would hold the key, against 2.3.
6. **The public-route claim is false.** No named list of routes exists: a valid ship key passes for any route (app.py:157-163), and route_watch.py:37 relies on that. Decide whether this route is tailnet-only, as imprints are (app.py:250-255). Note that `is_public` counts compute-node clients as public (app.py:68-81).
7. **Stages and keys.**
   - Rio Grande's stage 3 is a Tardis session reaching its home from another machine (§4); this stage 3 covers clusters only, and laptops' keys come from the Pi, not their homes.
   - Per-job expiry depends on the cluster draft, which hasn't been reviewed; `ship_keys` has no expiry (ships.py:119-143).
   - Say where the map from ship to store lives; the peer has none.
8. **The receiver's settings.** `load_settings` refuses any extra key and any publisher that isn't a plain name (lighthouse_receiver_config.py:26-42), so "the rest is unchanged" can't hold. Say crossings run only from the home host in a live recall, never inside an open `graph.db` transaction (3.4); away recalls get none.
9. **Cluster route B** serves only federation-listen's two routes (cluster spec §2), and pull test 13 expects every other path to answer 404. Say that B carries no crossings, or extend B under its own review.

## Nits

- "Reads no store": check 3 reads `peer.sqlite3` and check 4 writes to it. Say "no Engram store".
- Nothing enforces that read ids come "from an earlier delivery" (lighthouse_daemon.py:978-1000). Bind them with `turnId`.
- The no-imprint test should cite sharing.py:109-110, and the publisher map should refuse an imprint store.
- Call `receipt_id` `disclosureId`.
- The 403 row should require a `code`, since app.py:235-240 also answers 403.
