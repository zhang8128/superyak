# Re-check: a ship's own home, and lighthouse crossings (revision 2)

**Verdict: REVISE**, narrowly. Revision 2 (821df03c) closes most of the first review. Three Majors remain: halves of M1 and M2 that the code doesn't support, and a new one from the deployed Tardis. Each needs a decision, not wording.

## The first review's items

| Item | Status |
|---|---|
| M1 | **Partly open** (A). The ref, exact selectors and no local file are closed (2.2). |
| M2 | **Partly open** (B). The definition is closed (2.5); the storage ban has no mechanism. |
| M3 | Closed (2.3). Nit: the local frame kind is `recall`, not `query` (lighthouse_protocol.py:213; lighthouse_daemon.py:813). |
| M4 | Closed (the table, 2.3). The sidecar has a residue (S-c). |
| M5 | Closed in 1.2 and section 5, with residues (S-a). |
| S1, S4, S9 | Closed (2.3, 2.4; 2.3; 2.1 and section 6). |
| S2 | Closed (2.3). Nit: canonical JSON is raw UTF-8 (identity.py:23), so 4,096 four-byte characters fill 16 KiB alone. |
| S3 | Closed (2.2, check 5). Only `pair()` makes a contact (federation.py:144), so stage 2 must list the ship-card pairings Andy types. |
| S5 | Partly open (S-b). |
| S6 | Decided, but too wide (S-d). |
| S7 | Closed for stages, residue on keys (S-e). |
| S8 | Closed (2.4). Nit: `context` also consults neighbors (context_cli.py:92-97); say it skips remote publishers. |

## Majors

**A. The ledger refuses every remote receiver under `enforce`.**
- 2.2 makes the ledger agent `agent:<ref>`. The agent grammar is `_NAME`, which has no colons (engram/permissions.py:104, 138-139), so that agent can't be registered.
- `decide` refuses an unregistered requester, or one with no place, as `UNKNOWN_REQUESTER` (permissions.py:2062-2067, 2420-2422). So no item is delivered.
- "Its place is outside the home" names no place id.
- 2.2 doesn't name the `urn:engram:` prefix sites (lighthouse_daemon.py:519, 789, 958, 990), and sharing validates audience values, not map keys (sharing.py:43-48).

*Fix:* choose and state one:
- (a) remote refs are decided by policy and audience map alone, with no ledger side, which drops the owner's ledger records for crossings;
- (b) a remote-agent grammar, registered by the owner with a named place.

Either is safety code (law section 2).

**B. "No remote text stored as memory" (2.5) has no mechanism.**
- The `remember` guard reads only the local `permission-uses.db` (engram/server.py:2104-2109; permission_uses.py:542-547).
- A crossing's `inject_context` receipt is written at the publisher's home, so the receiver's guard never matches remote text.
- With the gate off, the guard does nothing at all (server.py:2091-2092).

*Fix:* the receiver records each remote delivery's content digest locally, and `remember` refuses a match in every gate mode, both at the host and in the client's digest check (Rio Grande 3.4). Say that exact digests stop copies, not paraphrases.

**C (new). Tardis is a pull peer today.** On this machine, `~/.local/share/superyak/tardis-peer/peer.sqlite3` has `federation_mode = 'pull'`, and only `superyak-federate` runs: there is no federation-listen and no `serve`. A known identity's mode never changes (pull spec §1). So Tardis can't be asked (2.1), can't open `crossing.sock` (2.4), and has no main app for 1.2. Stage 2 can't run as written.
*Fix:* stage 2 starts with a new push identity on Tardis (new data directory, `card --endpoint`, federation-listen on 7437, typed re-pairing), or uses another pair.

## Should-fix

**S-a. The own-home residues.**
- The body omits `outbox_id`, but the high-water mark is keyed by `(session_id, outbox_id)` (Rio Grande 3.3). 3.11 omits it too; add it here and tell Rio Grande.
- A refusal can be recorded only for a parseable envelope with `seq = high + 1`. The body is read in full before any route runs, so a body over 6 MiB gets BrowserBoundary's 413 (app.py:110-111) and never reaches the route. An unparseable 400 never does either. For a 4xx without `kind`, use 3.3's `skip to n`.
- "The first result if kept" contradicts 3.3 (no stored answer holds content).
- Off a cluster, `unauthorized` has no station drain; say a re-issued key resumes sending.

**S-b. The local hop.** One host serves many ships (3.8), so the host must name the asking store; the peer can only check it's hosted here. Say that instead of "never from the body". Name where federation-listen maps `publisher_ship` to a daemon publisher.

**S-c. The sidecar.** The daemon sees only the frame, so it can't know `origin_peer`, `request_digest` or `nonce`, and federation-listen can't share its transaction. Carry them in a frame extension that `record_disclosure` writes with the disclosure.

**S-d. Reach.** On the Pi, the memory route would read and write a ship's whole store from Funnel by bearer key, and no stage needs that: the Tardis case runs over the tailnet. Make the route tailnet-only (app.py:250-255), except on a cluster station.

**S-e. Memory keys.**
`ship_for_key` and `ship_key_is_valid` accept any unrevoked key (ships.py:119-143), so "opens only this route" needs a named change and a test on `/api/chats`. `ship_keys` needs a `scope` migration. A home needs a ship user (trusted `create-ship`) and a running `serve`.

**S-f. `turnId` binding.**
The daemon never sees `deadline_ms`, so use a fixed lifetime. Bind the turn to the receiver ref and the publisher, and to the candidates the daemon returned, not "selected" ones. Local reads already send the daemon's `turnId` (neighbors.py:126), so it can apply to all reads.

## The `unauthorized` amendment (section 5)

Sound and needed. It amends an approved interface, so it holds only once Rio Grande accepts it in 3.11.
