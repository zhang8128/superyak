# Re-check 2: a ship's own home, and lighthouse crossings (revision 3)

**Verdict: APPROVE WITH CHANGES.** Revision 3 (2ae42376) decides A, B and C soundly; no Major remains. The seven changes below are bounded, and applied as written they need no further round.

## The earlier items

| Item | Status |
|---|---|
| A | Closed in design (2.2), with one gap (change 1) and a cost to state (change 2). |
| B | Closed in design (2.5), with the storage and coverage gaps in change 3. |
| C | Closed (2.1, section 3). Hosting the socket in `federate` needs change 4, and stage 2 needs one more step (change 5). |
| S-a | Closed (1.2, section 5), except for how far a client may skip (change 6). |
| S-b, S-c, S-d, S-e | Closed (2.3 and 2.4; 2.3; 1.2; 1.2). |
| S-f | Closed for crossings. The 30 s window breaks local reads (change 7). |

## Changes

**1. The receiver legacy layer still refuses every remote ref.** The ledger side always adds `LegacyLayer("receiver", …)` (lighthouse_daemon.py:493-496). With no local receiver file, it returns False (:514-516), so `enforce` refuses every crossing. 2.2 drops the file but not the layer.
*Fix:* for a remote ref, the receiver layer is left out of the legacy layers, since the receiver checked its own policy before asking. Add that to the ledger test.

**2. Say what one shared agent gives up.**
- **Kept:** the owner still bounds what leaves home. The requester's place is a consent layer (permissions.py:1443-1444), and an outside-home allow needs finite purposes, at most 366 days and named memories (permissions.py:3385-3398).
- **Lost, per remote store:** ledger requester rules, agent retirement and grants, and the requester in `permission-uses.db` receipts (all `agent:remote-stores`).
- **Moved:** which store sees what is now set by the policy file and audience map, which the publisher's ship edits, and which carry a digest, not a signature (lighthouse-receiver.md:5).

*Fix:* state this. Name the owner's own cut-off for one store: hold its contact, or unpair. Write the place as `place:outside-home`, a top-level place the owner registers.

**3. `remote_deliveries` (B).**
- `permission-uses.db` is a hash-chained receipts file whose schema and digest form `Uses.open` checks (permission_uses.py:4-6, 30, 205-206), and the guard treats a missing file as "nothing to check" (server.py:2104-2105). Creating a table there on first use collides with both. Use a separate `remote-deliveries.db`.
- The remote check must come before the gate-off return (server.py:2091-2092).
- `remember` is only one writer. `jot` and `erase` with global scope, `task_update`, `dream_capture`, `clipboard_pin` and `add_anchor` also store text (Rio Grande 3.5). Guard every Sent tool that stores text, or narrow the claim.
- Define the normalization, the sentence split and how long rows are kept.

**4. `federate` hosting `crossing.sock`.**
- A pass is single-threaded and can block for minutes (10 pull rounds under a rate deadline: federate.py:39-71; pull spec §5). So the socket needs its own thread, sharing only the identity and read-only store access, and a fault there must never end `federate` (federate.py:5).
- The pull spec says federate "has no listening socket" (§1), federate.py:5-6 says "It listens on nothing", and test_federate.py:112-122 fails on any `bind` or `listen`. Amend all three by name.
- The socket must be opt-in, off by default, so the Mac's `federate` never opens it (section 6).

**5. Stage 2 needs the ship's pairing.** Only `pair()` makes a contact (federation.py:144). Tardis's peer has a `tardis` ship user, but its only contact on the Pi is Andy. Add this setup step: on Tardis, `card --username tardis --pull`, then Andy types its code on the Pi. Otherwise check 5 refuses every crossing.

**6. Bound `skip to n`** to exactly one operation. The host accepts a station-refusal skip only for `n = high + 1`, carrying the station's code; a wider skip stays 3.3's lost-outbox case. A 4xx without `kind`, such as BrowserBoundary's 413 (app.py:110-111), reads as `unreachable`, never a skip, so a misdeployed cap can't silently drop work. The client always knows the `seq` it sent, so drop "with no `seq` it can name".

**7. Scope the 30 s `turnId` binding.** `context` re-reads by `turnId` at `model_dispatch` and `source_inspection` (context_lighthouse.py:171-174, 213, 250), possibly minutes later. Bind remote refs only (30 s is ample against a 10 s deadline), and cap the map.

## Nits

- A 401's `kind` needs `ship_for_key` to tell expired, revoked and unknown keys apart; today all three get one answer (ships.py:119-128). Name that change.
- A `revoked` outbox is "never replayed". Say whether the owner can review and release it, or only discard it.
- A failed `crossings` write leaves the daemon's disclosure unpartnered; say it records an attempt.
- Say how a station knows it's a cluster station, for the Funnel exception.
