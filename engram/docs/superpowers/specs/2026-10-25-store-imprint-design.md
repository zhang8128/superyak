# Imprints: Porting an Engram Store Here with Its Owner's Permission

**Date:** 2026-10-25
**Status:** Revision 6, the fixes after the cross-check of the consolidation pass
(`docs/superpowers/reviews/2026-10-25-city-rail-consolidation.md`, "Cross-check" and "Cross-check fixes"). XM1: at
the station the one home layer is the ceiling itself, for every copy, and the operator's own records add nothing there
(section 8). XS1: the recall-row test's source holds no row at or after t₁, or the test takes `as_of` = t₁ with no
row at exactly t₁ (section 16). XS2: with `route`, admission counts R(I), and the `admitted` and use receipts carry
that count, so the rows for roads and trails are defined; counting reads the memories for `trail-evaluation`, which
the owner's record and the ceiling already allow (sections 8, 10, 12 and 16). XS3: the dry run and the confirm view
say that access counts, last-access times and resonances leave with the memories (sections 5.4 and 9). The nits XN1
and XN6 (D41, sections 8 and 12). Revision 6 changes D16 and D41, the header and sections 5.4, 8, 9, 10, 12 and 16.
It lets nothing more leave a machine, and it widens no permission.
Revision 5 was the consolidation pass across the three city-rail specs (the same file, which logs each change).
Revision 4 was approved on
its check (`docs/superpowers/reviews/2026-10-25-store-imprint-spec-review.md`, "Check of revision 4": approve, with
CS1, CS2 and CN1–CN8). Revision 5 applies CS1, CS2 and CN1–CN6. CS1: the calibration test also leaves out the
survey's file and identity facts, and both runs share one `now`. CS2: `imprint.py use` writes `result.json` for its
own errors too, so `failed` is reachable, and a missing `result.json` means that the unit was stopped, or that a
withdrawal, a deletion or the end came before the run began. It also takes two items the permissions spec's reviser
carried: section 8 defines the home layer at the station when the owner is the operator, and section 12's rows for
roads and trails are one per bulk use of at most 100,000, as the permissions spec's 9.1 has them. The recall-row
test's one `as_of` is at or after the plan's end t₁, found while checking I6. Revision 5 changes D29 and D41, the
header and sections 8, 10, 12, 13, 14, 15, 16 and 18. It lets nothing more leave a machine, and it widens no
permission.
Revision 3 was approved on its final check
(`docs/superpowers/reviews/2026-10-25-store-imprint-spec-review.md`, "Final check": approve, with three should-fix
items, FS1–FS3). Revision 4 applies all three; that file's "Response to the final check" lists each. FS1: admission
runs calibration without its paths analysis, so it reads no road or trail, which no record allows for `calibration`.
FS2: the calibration test compares what is the same, and the survey's session count says why it is 0. FS3: the trail
spec's asks I2, I3 and I6 (its section 11), as it states them. Revision 4 changes D7, D16 and D29, adds D41, and
changes the header and sections 5.2, 8, 10, 12, 13, 14, 15, 16 and 18. It settles interface rows 14, 24, 27 and 28,
and notes row 13. It lets nothing more leave a machine, and it widens no permission.
Revision 3 answered the second fresh reviewer's re-check
(the same file, "Re-check": approve with changes, RMF1, RS1–RS5,
RN1–RN10). That file's "Re-check response" lists each item, what was done, and what was declined. Revision 2 applied
the first review (MF1–MF7, S1–S16, N1–N14; that file's "Response"). An interface pass across the three city-rail specs
then changed D7, D8, D10, D17, D35, sections 3, 5, 6.2, 8, 9, 10, 12, 13, 14, 16, 17, 18 and 20, and added D36 and D37
(`docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md`). Revision 3 changes D6, D7, D10, D13, D17, D26, D28,
D32, D36, sections 2, 3 and 5 to 18, and adds D38–D40. It updates interface rows 2, 6, 8, 13, 21, 24 and 26. No revision lets more leave a machine than before. Revision 3 lets
less leave: without `route`, no episode's session id leaves either. Nothing here is built.
**Modules:** new `engram/imprint.py`; new `peer/superyak_peer/imprints.py`; small changes in `store_identity.py`,
`storage.py`, `store_reader.py`, `calibrate.py`, `persistence.py`, `sharing.py`, `federation.py`, `cli.py`,
`lighthouse_sheaf.py`, the peer's `identity.py`, `ships.py`, `app.py`, `peer_routes.py`, `__main__.py`, the agent, the
Makefile and the CLAUDE.md files (section 15).
**Contract:** `docs/city-rail-vision.md`, "Imprints: porting a store here" and "Permissions by place".
**Source of truth for permissions:** `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md` (revision 6,
whose uses name their copy h and whose bulk uses this spec's checks are, each naming at most 100,000 memories; its
6.1, 6.4 and 9.1).
That spec says the imprints spec cites its sections 5, 6 and 11 (its header, "Depended on by"). This spec does: the record and its selector (its 5.1–5.2), matching (5.3), uses and denotations (6.1), the order
and the lattice (6.2), and `need` (6.4). Section 8 says how an imprint permission is made of those records, and names
the few imprint-only fields beside them. Where the two specs differ, the permissions spec wins and this one is revised.
**Builds on:** `2026-10-03-ds9-station-design.md` (ships, docking, approval), `2026-10-15-grants-step3-design.md`
(signed records), `2026-09-29-inheritance-reading-design.md` (store identity), the trail spec
`2026-10-25-trail-arrows-design.md` (revision 8; it uses this spec's sections 5.3, 6.2,
10, 11 and 12 and D10, and lists what it needs from this spec as its interface items I1–I6, in its section 11).

Every decision here that does not quote Andy, station law or the permissions spec is **Rio Grande's call**. Section 4
lists them all.

## Revision history

| Revision | Commit | What changed |
|---|---|---|
| 1 | uncommitted draft | First draft. Verdict: approve with changes (MF1–MF7, S1–S16, N1–N14). |
| 2 | `3c022bf` | Adopts the permissions spec's records, uses, lattice and `need`; drops instincts; the audience is the operator's home. Lineage is a closure over a stored ancestry. Leak checks read values, FTS vocabularies and vec0 slots. Receipts from station commands are signed by the lighthouse. The request carries only what the confirm view shows. Other people in a store get a stated limit and an owner's check. Calibration's bound comes from a measurement. Plus the should-fix items and nits. |
| 2, interface pass | uncommitted | Log rows ship only with `route`, and r_T then lists `imprint`, `read` and `recall` too (D7, D10). r_M reaches memories through one collection, as P28 requires (D36). A `route_shown` row cut to nothing is dropped (D35); I4's cut flag is declined. The ship's withdrawal and shortening narrow the station's ceiling, never the owner's records (D17). The source store's ledger owner must be the ship's owner (D37). The owner's use list gets the permissions spec's receipt form, in batches of 512. `--lane` for the trail evaluation, and an embedder gate. |
| 3 | `21fe509` | Answers the re-check. Without `route`, every shipped episode's `session_id` is null, so no footpath leaves; with it, only sessions closed at t₁ keep theirs (RMF1, option (a)). r_M names `"*"` lanes and layers (RS1). Uses name their copy, and the ceiling is per copy: a fixed rule over the station's own records and receipts, so the station's check is the permissions spec's meet however many imprints an owner holds (RS2, RN7). Admission is decided again at every start and checks its end before each write (RS3). Stores older than store identity have incomplete ancestry (RS4). Every row and file about an imprint or a request has an end, and the owner is told before sending (RS5). The nits: `scope.lanes`, the ten `contents` keys, the request's labels, ancestry in the request, the named departures from the permissions spec's receipts, bulk uses, the ceiling as Andy's rule, pending lane notes, full-id unit names, and the `--imprints-dir` flag. |
| 4 | `05f4538` | Answers the final check (FS1–FS3). Admission runs calibration without its paths analysis, so it reads no road or trail (FS1, option (a)). The calibration test compares the sections that are the same, and the survey's zero session count says why (FS2). The trail spec's I2: a use id is a lowercase uuid4, `imprint.py use` writes `report.json` and `result.json`, finishing a use retires its allow file, `use-finished` records how the run ended, and the use always passes `--lane` (D41). I3: the use's unit gets the shared embedder's socket from the station's `runtime.json` (D29). I6: the recall-row test asserts what the trail spec says holds (FS3). Approved on its check. |
| 5 | `ade420c` | The consolidation pass. The calibration test leaves out the survey's file and identity facts and fixes one `now` (CS1). `imprint.py use` writes `result.json` for its own errors, so a crash is `failed` and a missing file means the unit was stopped (CS2, D41). The use's unit stops within 60 s of its limit, and the sync finishes it at the first sync after (CN1). The socket rule's edges, and a deploy gate on the user manager's environment (CN2, D29). The survey's counts get a reason that fits both (CN3). `imprint.py use` fills in `LANE` (CN4). What `make station-imprint-use` prints (CN5). `report.json` before `result.json` (CN6). The home layer when the owner is the operator (section 8). Roads-and-trails rows per bulk use (section 12). The recall-row test's `as_of` is at or after t₁ (section 16). |
| 6 | this file | The cross-check's fixes. At the station the one home layer is the ceiling itself for every copy; revision 5's layer would have refused every other owner's imprint (XM1, section 8). The recall-row test's source holds no row at or after t₁, or its `as_of` is t₁ with no row at exactly t₁ (XS1). With `route`, admission counts R(I), reading the memories for `trail-evaluation`, and the `admitted` and use receipts carry the count, so the import's rows for roads and trails are defined (XS2). The dry run and the confirm view say that access counts, last-access times and resonances leave and show when memories were recalled together (XS3). An error before the use directory reads as a limit (XN1). In a step-2 ledger the ceiling stays its own term (XN6). |

## 1. Why

Andy said:

- "We should make it easy to port engram stores with permission from other computers. to imprint it here."
- "We need levels of permissions that can be set and modified some by people some by agents some overlapping. for
  different layers and different places. I may share my medical history with the public health office but not the
  parks and rec."
- "I'm seeing this as free, open source, uses universal mathmatical principles as connector standards and runs on a
  raspberry pi."
- "Take a step back. this is a system you will be traveling."

What exists today:

- `calibrate.py` snapshots a store through a read-only connection with SQLite's backup API (`calibrate.py:54-68`),
  migrates only a working copy (`calibrate.py:262-277`), and refuses to report success if the source changed
  (`calibrate.py:300-305`).
- `store_reader.py` opens a store `mode=ro` with `query_only` and never migrates (`store_reader.py:44-55`). It never
  loads extensions, so it lists vec0 tables but can't query them (`store_reader.py:7-9`). It reports applied, pending
  and unknown migrations (`store_reader.py:88-101`).
- Every store has `meta.instance_id`. A fork gets a new id and records `forked_from_instance_id`
  (`store_identity.py:143-160`, `cli.py:38-49`). It records only its parent. A fork can be made from another instance
  (`cli.py:21-24`), and nothing records a grandparent.
- The station's Ed25519 key signs records with exactly their kind's keys (`peer/superyak_peer/identity.py:76-87`,
  `:147-151`), and `verify_record` checks them and never raises (`identity.py:189-200`).
- The permissions spec defines records, uses, a lattice of permissions and the closure of actions. Nothing of it is
  built yet.
- Only Andy admits until the charter exists (`docs/station-law.md:28-31`).

What is missing: a way to choose what leaves, to filter it before any byte leaves, to carry it to the Pi, to admit
it there, and to delete it when the owner says so. The Pi has no Engram store yet (`~/.engram` is absent, trail spec
section 14). The first imprint creates `~/.engram/imprints/`, and nothing else.

## 2. Vocabulary

| Term | Meaning |
|---|---|
| **Owner** | The station person the store is about. In step 1, the person who owns the ship on the source machine. |
| **Operator** | The station person the Pi's `make station-*` commands act as (Makefile `APPROVER ?= andy`, `Makefile:32`). It is the operator's word, not an authentication (`ships.py:201-206` checks only that the name is a person). |
| **Source** | The owner's `graph.db`. It is only ever read. |
| **Selection** | The owner's choice of lanes, layers, dates, an optional shared-with audience, ids to leave out, and whether semantics with no recorded source may leave (section 5.2). |
| **Plan** | A selection, the terms, and the exact list of rows that would leave, with its digest. Kept on the source machine. |
| **Package** | `imprint.db` (the filtered copy) plus `manifest.json`, built from a plan. Neither leaves before the yes. |
| **Request** | What the owner's machine sends to ask for the yes: only what the confirm view shows, plus two fixed labels (section 7.1). |
| **Terms** | The permission the owner asks for: audience, actions, purposes, days (section 5.3). |
| **Permission** | The terms after the owner's yes: a station-signed record holding permissions-spec records (section 8). |
| **Use** | One act on one object held in one copy, as the permissions spec defines it (its 6.1). |
| **Copy** | The house that serves a use. For an imprint I it is h_I = `imprint:<station peer id>/<imprint id>` (permissions spec 4.1). |
| **Ceiling** | The station's own rule for the uses of one imprint, fixed in code and read from the station's records and receipts (section 8, D38). |
| **Imprint** | An admitted package on the Pi: its own read-only store. |
| **State directory** | A writable directory beside each imprint, for its calibration report and its uses (section 10). |
| **Receipt** | A station record of one event in an imprint's life, hash-chained and signed (section 12). |
| **Ancestry** | The stored list of the stores a store was copied from, nearest first (section 11). |

## 3. Goals (step 1), non-goals, anti-goals

**Goals (step 1)**

1. The owner chooses what leaves, sees a dry run that lists exactly what would leave, and can read it first.
2. The copy is filtered on the source machine. No byte of a memory the owner left out is in the package: not in a row,
   an FTS index, a vec0 chunk or a free page.
3. No byte of `imprint.db` reaches the station before the owner says yes in their browser. The request carries nothing
   the confirm view doesn't show, except its two fixed labels, `kind` and `version`. The view shows the imprint's short
   id and the plan digest's first 8 characters, and says that the whole digest is sent. None of these holds content.
   The owner's terminal prints the request before it is sent, with what the station keeps, and for how long, if the
   owner never says yes.
4. The package travels over the tailnet to the station in bounded, resumable parts.
5. Andy approves receipt. The station verifies the package, calibrates it with `calibrate.py`, and registers it as
   its own read-only store that is never merged into another.
6. Every event after the yes leaves a receipt, signed by the station, that the owner can read and check. A request
   declined or expired before a yes has no permission and so no receipt. Its row holds no content, and the station
   removes it 30 days later (D32).
7. The owner can withdraw at any time. Withdrawal deletes the imprint at once and a receipt says so. End dates delete
   it too.
8. Step 1 uses: admission (verify, survey, calibrate) and the trail evaluation (trail spec section 7), once
   `trails.py` exists. Each is allowed only when its `need` lies in the permission and in the station's ceiling.

**Non-goals (step 1)**

- Serving `recall`, `read` or `inject_context` over an imprint to agents. That needs the permissions core and the
  lighthouse receiver (section 17).
- Instincts, dream residue, task contexts and the knowledge graph. In the permissions spec they "are never objects;
  they never leave" (its 5.2, and section 14's non-goals).
- Audiences other than the operator's home, requesters other than the station's imprint agent, and `group:`, `self`
  and `commons` audiences.
- Cold storage, category stores, anchors, assessments, notes, the clipboard and the code index (section 6.3).
- Station-to-station imprints over federation, owner-held keys, deltas, and lengthening an end date.
- Asking the other people a store mentions for their yes. Step 1 states the limit and asks the owner (D27).
- Imprinting a published house or an imprint.
- Secure erase of disk blocks.

**Anti-goals** (failure even if the code works)

- **Leakage.** Any byte of a left-out memory in the package: in a row, an FTS or vec0 shadow table, or a free page,
  including bytes a raw-byte scan cannot see.
- **Early bytes.** Any byte of `imprint.db`, or any request field other than `kind` and `version` that the confirm view
  doesn't show, reaches the station before the owner's yes.
- **Footpaths without `route`.** Without `route`, a log row or an episode's `session_id` leaves: anything from which
  the trail spec could rebuild which session wrote or used what.
- **Agent consent.** An agent can produce the owner's yes, or tick the owner's check about other people.
- **Normal open.** An imprint is migrated, decayed, pruned, compressed, genome-synced or merged.
- **False agreement.** An imprint, a fork, a store older than store identity, or any store whose lineage meets
  another's counts as independent of it.
- **Sticky data.** Withdrawal waits for Andy, fails silently, or leaves imprint files on the station.
- **Telling receipts.** A manifest or receipt carries memory content, query text, memory ids, or anything about what
  stayed home.
- **Backed-up imprints.** Imprint bytes, or a request's contents from before the yes, in any station backup.
- **Kept for good.** Any row or file about an imprint or a request that the station keeps with no end, or keeps longer
  than the owner was told before sending.
- **Late ends.** A use or an admission step that runs after the permission's effective end, or after a withdrawal.

**The vision's constraints**

- **People own what is about them.** Only the owner's yes sends anything. The owner or their agent can narrow or
  withdraw. The station can refuse. Nobody can widen. Memories that mention other people are the one place step 1
  rests on the owner's word, and section 6.4 says so.
- **Mathematics is the connector standard.** The selection (5.2), the plan digest (5.4), the no-leak property and its
  checks (6.4), the permission as a set of uses and its order (8), lineage (11) and the use check (8, 12) are
  definitions a stranger can implement. The request, manifest, records and parts are canonical JSON and SHA-256, with
  integer times and no floats, and no vendor API.
- **Free and open source.** No new dependency. The peer side uses its standard library and `cryptography`, the agent
  only the standard library, and engram what it already uses. Releasing waits on the vision's license item.
- **Runs on a Raspberry Pi.** SQLite files, 4 MiB parts, streamed hashing, streamed index comparisons, calibration
  under a memory cap with every dense set bounded at 7,500 episodes, an hourly sweep. No GPU. Admission needs no
  embedder. What the trail evaluation needs on the Pi is the trail spec's to say (its interface item I3).

## 4. Decisions

| # | Decision | Source |
|---|---|---|
| A1 | Stores are ported with the owner's permission and imprinted here. | Andy (quoted above) |
| A2 | Only Andy admits: an item is approved or denied only when he names it and confirms its short id. | Station law section 1 (D7) |
| D1 | The owner's yes is a browser confirmation by the signed-in owner, with their password, after the dry run. No byte of `imprint.db` leaves before it. | Rio Grande's call |
| D2 | The station's Ed25519 key signs the permission in the transaction that records the yes, as it signs grants (`peer/API.md:282-284`). Owner-held keys are a later step. | Rio Grande's call |
| D3 | The package is built by inserting chosen rows into a fresh database, never by deleting rows from a copy. It is vacuumed and has no free pages. | Rio Grande's call |
| D4 | Tables are deny by default. A source table no rule names is not copied, and the dry run names it. A table the package's own migrations create without a rule stops the build, because that is a bug in this code. | Rio Grande's call |
| D5 | Semantics are closed downward over their recorded sources: a semantic leaves only if every recorded source episode is admissible. One with no recorded source leaves only with `--include-unsourced-semantics`. | Rio Grande's call |
| D6 | Rows are kept whole or dropped whole, except a fixed list of scrubbed columns. `episodes.session_id` is one of them: null unless D7 lets it leave. | Rio Grande's call |
| D7 | Log rows (`memory_log`, `operation_log`) and episodes' `session_id` leave only when the owner chooses `route`. They are the owner's trails: the trail spec makes a session from any distinct `episodes.session_id` and a trail from its episodes alone (its section 4). Calibration reads no log row's content, though its survey counts the log tables' rows and the distinct session ids. At admission it skips its paths analysis, so it derives no road or trail, with or without `route`, and its survey says why it counts no session without `route` (section 10; the final check's FS1 and FS2). With `route`, an episode keeps its `session_id`, and log rows leave, only for sessions closed at t₁, and log rows only inside [t₀, t₁). A recall row loses its instinct results and leaves only if every other result leaves, with no mark of what was cut. Query text and outcome notes never leave. | Rio Grande's call (option (a) of the re-check's RMF1) |
| D8 | Step 1 layers: episode and semantic. Instincts never leave. | Permissions spec 5.2 |
| D9 | Step 1 audience: `place:home/<operator>`. The only requester is the station's agent `agent:station-imprints`, acting for the operator in the operator's home. | Rio Grande's call |
| D10 | Actions are closed under the permissions spec's `need`: `recall`, `read` and `imprint` on the memories, and, when the owner chooses `route`, `recall`, `read`, `imprint` and `route` on their roads and trails, since the session ids and log rows that make the trails are kept too (D7). Purposes are a set: `calibration` (required) and `trail-evaluation` (exactly when `route` is chosen). | Rio Grande's call, using permissions spec 6.4 |
| D11 | An imprint gets a new random `instance_id`, origin `imprint`, `forked_from_instance_id` = the source, and an ancestry. Memory ids are kept. | Rio Grande's call |
| D12 | Imprints live at `~/.engram/imprints/<imprint id>/`, read-only, with guards in `Storage`, `sharing`, genome sync, `fork` and `lighthouse_sheaf`. | Rio Grande's call |
| D13 | A store's lineage is its id plus its stored ancestry. Two stores are independent only when their lineages don't meet and both ancestries are complete. Siblings are never independent. A store older than store identity (origin `retroactive`) is never complete, since nothing recorded the copies made of it then. | Rio Grande's call |
| D14 | Transport is the station's HTTPS over the tailnet with the ship key, in 4 MiB parts hashed in the manifest. | Rio Grande's call |
| D15 | Staged and admitted bytes, and a request's contents, live outside `peer.sqlite3`, so station backups never hold them. Tombstones survive a restore. | Rio Grande's call |
| D16 | Admission is 17 checks plus calibration with a content-free report, and, with `route`, a count of the roads and trails (section 10). Calibration runs without its paths analysis, since the trails are kept only for the trail evaluation (section 10). Any failure deletes the package. | Rio Grande's call (the paths part: option (a) of the final check's FS1; the count: the cross-check's XS2) |
| D17 | The owner can withdraw at any time in the browser, which revokes the records. The owner's ship can ask the station to refuse at any time, which deletes the copy the same way and edits none of the owner's records, since an agent edits a person's layer only under a grant (permissions spec P10, 7.1). The ship's withdrawal and shortening are receipts, which the station's ceiling reads (D38). Deletion is immediate, never waits for Andy, and wins over a running admission. The station may also delete. | Rio Grande's call |
| D18 | An end date is required, at most 365 days out. It can be shortened, never lengthened. | Rio Grande's call (the permissions spec's P13 allows 366) |
| D19 | Receipts are hash-chained and hold no content. Station commands that hold no key write them unsigned, and the running lighthouse signs them within 60 seconds. | Rio Grande's call |
| D20 | One live imprint per source store per station: one in any status before `deleted`, `declined` or `expired`. | Rio Grande's call |
| D21 | The manifest says nothing about what stayed home. | Rio Grande's call |
| D22 | A plan digest binds what the owner reviewed to what is built and to what arrives. | Rio Grande's call |
| D23 | Text that names a left-out row's key is shown to the owner, and the build refuses until they leave that memory out with `--exclude`. Step 1 has no flag that allows it. | Rio Grande's call |
| D24 | The source machine deletes its package copy once the imprint is admitted, declined, denied, failed or deleted. | Rio Grande's call |
| D25 | Odo's notice says only that an imprint waits for review. It names no owner and no details. | Rio Grande's call |
| D26 | The request carries only what the confirm view shows, plus its fixed labels `kind` and `version`. It names the source's ancestry, so the view can. The manifest is sent after the yes. | Rio Grande's call |
| D27 | Before the yes, the owner confirms that nothing chosen is about another person who hasn't agreed, and that none of it is patient or participant data. A memory with a recorded co-subject never leaves. | Rio Grande's call |
| D28 | The permission is an `imprint-permission` record holding two permissions-spec records. A use of imprint I is allowed iff its `need` lies in ⟦p_I⟧ ∩ ⟦c_I⟧, the meet of the owner's permission for I and the station's ceiling for I (D38). | Rio Grande's call, using permissions spec 5–6 |
| D29 | Admission and uses run as detached user units. The station commands that start them return at once. A unit starts in a clean environment: not the caller's shell, only the user manager's own environment, which a deploy gate checks holds no `ENGRAM_` variable (section 18). So a use's unit gets `ENGRAM_EMBEDDER_SOCKET` through `--setenv`, and only when the station's `~/.config/superyak/runtime.json` names an `embedder_socket` (section 12). | Rio Grande's call (the socket: the trail spec's I3) |
| D30 | Each imprint has a writable state directory beside it for reports and uses. Withdrawal removes both. | Rio Grande's call |
| D31 | Calibration skips any dense set over 7,500 episodes, from a measured peak of about 7.5 × n² × 8 bytes. | Rio Grande's call |
| D32 | The station keeps a deleted imprint's row, permission, receipts and tombstone for 400 days after `deleted`, then removes them all. It removes a declined or expired request's row 30 days after it ends. Nothing about an imprint or a request is kept with no end. Backups age out by their own rule (section 9). The owner is told all of this before sending, in the confirm view, and in `imprint-status`. | Rio Grande's call (the permissions spec keeps receipts 400 days, its 9.1) |
| D33 | Memories are inserted in `(created_at, id)` order. Source rowids are never copied. | Rio Grande's call |
| D34 | Leak checks are logical: every value through SQL, FTS vocabularies against a rebuilt index, and vec0 slots. They run at the build, and the index checks run again on the Pi. A raw-byte scan is an extra check. | Rio Grande's call |
| D35 | `route_shown` rows leave like recall rows, with their targets cut to what ships. A row cut to nothing is dropped, since it would say that a tool named only memories that stayed home (D21). | Rio Grande's call, from the trail spec's interface item I1 |
| D36 | The memories record reaches its memories through one collection whose members are exactly the shipped refs, as the permissions spec requires of an allow that leaves a home (its P28). Its `layers` and `lanes` are `"*"`: the collection fixes what it reaches, so no lane is read at the station. An imprint holds at most 100,000 memories, that spec's collection bound. | Rio Grande's call, using permissions spec 5.4 |
| D37 | When the source machine has a permissions ledger, the source store must be registered there with the requesting ship's owner as its owner. | Rio Grande's call, using permissions spec P12 and P32 |
| D38 | The station's ceiling is one rule per copy, fixed in code over the station's own signed records and receipts. It allows only uses of that copy, on its own objects, within its own records' actions, purposes and dates, and none after a withdrawal or past a shortening. So no one edits a layer when the ship acts, and the station's check is the permissions spec's meet however many imprints an owner holds. Andy accepts it as his home's rule for imprints before the first one (section 18). | Rio Grande's call, from the re-check's RS2 and RN7 |
| D39 | Admission is decided again at the start of every run, the first included, and checks the effective end and withdrawal before each of its writes. It never runs past the end. | Rio Grande's call, using permissions spec 10 ("Time needs no act") |
| D40 | With a permissions ledger at home, a memory whose latest lane note is `pending`, or names another lane than its lane column, stays home. | Rio Grande's call, using permissions spec 5.3 |
| D41 | One use id gives one run. A use id is a new lowercase uuid4. `imprint.py use` writes the report as `uses/<use id>/report.json` and how the run ended as `uses/<use id>/result.json`. Finishing a use retires its allow file. `use-finished` records the run's end: the report's SHA-256, or `withdrawn` (only when the tombstone exists), `ended`, `deleted` (a station deletion), `allow changed`, `not evaluable: limit` for a run a signal killed or a unit stopped before `imprint.py use` ended, or `failed` for any other run with no report, an error in `imprint.py use` itself included (section 12). `imprint.py use` writes `result.json` for its own errors too, once it has made the use directory. So a missing `result.json` means that the unit was stopped, or that `imprint.py use` failed before it made that directory, both of which rule 6 of section 12 reads as a limit, or that a withdrawal, a deletion or the end came before the run began, which rules 2 to 4 record (the check of revision 4, CS2; the cross-check's XN1). The use always passes `--lane`. | Rio Grande's call, from the trail spec's I2 |

## 5. On the source machine: choosing what leaves

### 5.1 Which store

`--store PATH` names it. **Use `--store` when unsure.** Without it, the plan resolves the store the engram server
would open from the current directory: `config.resolve_db_path(engram_home, project_root)` (`config.py:373-409`), with
`engram_home` = `$ENGRAM_HOME` or this checkout's `engram/` directory and `project_root` = `$ENGRAM_PROJECT_ROOT` or the
current directory. The server reads its config from that project root (`server.py:160-163`, `:1302-1311`), so the
default can differ from one project to another. The dry run always prints the resolved path.

The plan refuses:

- the published house, `…/.engram/instances/lighthouse/graph.db` (`server.py:1936`);
- an imprint (`meta.instance_id_origin = imprint`);
- a store with unknown migrations, which is newer than this code (`store_reader.py:100`);
- a store with no identity it can derive: `store_identity.effective_id` returns `None` (`store_identity.py:113-116`);
- when the machine has a permissions ledger (`ENGRAM_HOME/.engram/permissions.db`, read with `mode=ro`), a store with
  no `stores` row there, or whose row's `owner` is not `person:<the requesting ship's owner>` (D37). A memory's default
  subject is its store's owner, and a memory with no subject is refused (permissions spec P12, P32), so the yes must
  come from the person the ledger names. With no ledger, the owner's word stands, as in the rest of step 1;
- a selection with no memories, or with more than 100,000 (D36).

### 5.2 The selection, precisely

A selection is σ = (L, Λ, t₀, t₁, A, X, U):

- L ⊆ {`personal`, `work`}, not empty (`--lanes`). No default.
- Λ ⊆ {`episode`, `semantic`}, not empty (`--layers`). No default.
- t₀ and t₁ are integer UTC seconds, and [t₀, t₁) is half-open (`--since`, `--until`, which take ISO-8601 dates or
  times; a value with no zone is UTC). t₀ defaults to −∞. t₁ defaults to the plan's own time, so nothing written after
  the plan joins it.
- A is an audience or ⊥ (`--shared-with`, optional). Its grammar is `sharing.validate_audience`
  (`sharing.py:41-46`).
- X is a finite set of ids to leave out (`--exclude FILE`, one id per line).
- U is true or false (`--include-unsourced-semantics`, default false).

**Times.** For a row, τ is its stored time (`created_at`, or a log row's `timestamp`) read with ISO-8601 rules. A
stored time with no zone is read as UTC. Engram writes an explicit `+00:00` today (`storage.py:55-56`). A row whose
time does not parse is not admissible, and the dry run counts it. τ ∈ [t₀, t₁) compares instants exactly, fractions of
a second included.

For a memory m, ℓ(m) is its `lane` column now. Define

    base(m)  ⇔  ℓ(m) ∈ L  ∧  t₀ ≤ τ(m) < t₁  ∧  m ∉ X  ∧  (A = ⊥ ∨ shared(m, A))  ∧  cosubjects(m) = ∅  ∧  ¬pending(m)

**`shared(m, A)`** holds when the published house, opened read-only, holds a `shared_memories` row r with:

- `r.source_instance` = the source's instance name: `default` for `<engram_home>/.engram/graph.db`, else the directory
  name under `instances/`, as `server.py:1976` writes it. Once the permissions spec's migration 029 has landed, the
  match is on `r.source_instance_id` = the source's effective id instead (its 12.1);
- `r.source_id` = m's id, `r.layer` = m's layer and `r.audience` = A;
- A ∈ `sharing.audiences_for(published, r.memory_id)`, which checks the published copy against every share digest
  (`sharing.py:236-254`);
- and `content_digest(m.content)["value"]` = `r.content_digest`. So a source memory changed since it was shared is
  not shared any more. This is the comparison `_verify_reused_copy` makes before reusing a copy (`sharing.py:77-96`).

The server names a share's source `_instance_name or "default"` even when a configured instance's store was missing and
it fell back to `.engram/graph.db` (`server.py:1306-1311`, `:1976`). Shares made in that state carry the instance's
name, so `shared` misses them for `.engram/graph.db`. That only narrows.

**`cosubjects(m)`** is the set of effective co-subjects of `mem:<source id>/<layer>/<m id>` other than the owner, read
read-only from the source machine's permissions ledger (permissions spec 5.5, table `subjects`, rows with no
`removed_seq`). It is ∅ when that machine has no ledger. A memory with a co-subject needs that person's yes too (its
7.4), and step 1 cannot collect it, so the memory stays home. The dry run counts these as "needs <name>'s yes".

**`pending(m)`** (D40; the re-check's RN8). It holds when the source machine has a permissions ledger and the latest
lane note of `mem:<source id>/<layer>/<m id>` (permissions spec 5.3 and 5.5, table `lane_notes`) is `pending`, or
names a lane other than ℓ(m). That spec counts a memory with a pending move as in neither lane for an allow (its 5.3
table), and a note that disagrees with the column means a re-lane has not settled. It is false with no ledger, and for
a memory with no lane note. The dry run counts these as "lane change at home not settled".

The admissible memories:

    Ê = { e ∈ episodes  : base(e) }
    Ŝ = { s ∈ semantics : base(s) ∧ src(s) ⊆ Ê ∧ (src(s) ≠ ∅ ∨ U) }      src(s) = { e : (s, e) ∈ semantic_sources }

**Recorded sources only.** Pruning deletes an episode row (`storage.py:760`), and `semantic_sources` cascades on that
delete (`002_v3_layers.sql:27`) with foreign keys on (`storage.py:123`). The pruned episode moves to `cold.db` with no
link back to its semantics (`storage.py:734-747`). So src(s) holds only the sources still recorded. A semantic whose
sources were partly pruned is judged on the rest, even if a pruned source was before t₀ or in X. A semantic with none
recorded has src(s) = ∅ and leaves only with U. The dry run counts semantics with no recorded source. Engram keeps no
record that would tell a partly pruned semantic from a whole one.

The shipped memories:

    E = Ê if episode ∈ Λ, else ∅      S = Ŝ if semantic ∈ Λ, else ∅      M = E ∪ S

Λ chooses what ships. It never widens what is admissible. A semantic can ship without its episodes, but only if they
are admissible.

**Log rows and session ids.** Recall and `route_shown` rows in `memory_log`, `operation_log` rows, and each episode's
`session_id` say which session did what: the order in which the owner's agents worked, from which the trail spec
derives trails. Every episode records the session that wrote it: `remember` passes `session_id=_session_id`
(`server.py:1869-1876`; the column is `migrations/001_initial.sql:48`), and so does the nudge hook
(`hooks/nudge.py:531-535`). The trail spec makes a session from "any distinct non-null `episodes.session_id`", and its
wrote touches are "every episode carrying that `session_id`" (its section 4, "Sessions" and "Wrote touches"). A trail
needs two touches. So episodes alone give a trail to every session that wrote two of them. Session ids and log rows
ship only when the terms include `route` (5.3; D7). Without `route`, the package sets every episode's `session_id` to
null and holds no log row.

Calibration reads no log row's content: its analyses (`calibrate.py:286-296`) read episodes, semantics, vectors,
resonances and subdivision events, and sheaf's only `memory_log` read is the sleep pass's rate limit (`sheaf.py:285-300`,
called only at `:323`), which calibration never runs. It does count the log tables' rows: its survey of the snapshot
(`calibrate.py:258`) counts every table's rows (`store_reader.py:111-121`), and the distinct session ids of the
episodes (`:126-131`). Its paths analysis reads `episodes.session_id` too: `paths.report` turns each session into a
path, and names sessions and pairs of sessions in its report (`paths.py:338-354`, `:418-452`, `:328-330`; run at
`calibrate.py:295-296`). That is a `read` of the owner's trails. So admission runs calibration without it, with or
without `route` (section 10; the final check's FS1). Without `route`, the survey counts 0 sessions and 0 log rows, and
the admission report says why (section 10).

For a session id s, let rows_<t₁(s) be the source's episodes with
`session_id` s, its `memory_log` rows whose `context.session_id` is s (any event type), and its `operation_log` rows
with `session_id` s, each with τ < t₁. The session is **closed at t₁** when max τ over rows_<t₁(s) < t₁ − 3,600. This
is the trail spec's closed session (its section 4) read at t₁, made stricter: it counts every `memory_log` event type
and `operation_log` rows too, so a session is closed here no sooner than there. It uses only rows before t₁, so rows
written after the plan can't change it. A log row ships only if the terms include `route`, t₀ ≤ τ < t₁, it has a
session id, that session is closed at t₁, and its table's rule in 6.2 keeps it. A shipped episode keeps its
`session_id` only if the terms include `route` and that session is closed at t₁. Otherwise the package holds null
there. So a session still open at t₁ leaves no mark at all: neither its writes' session id nor its log rows (Rio
Grande's call; it only narrows, and spares the trail spec a part-trail whose recalls stayed home).

A resonance ships only if t₀ ≤ τ(`created_at`) < t₁ and both its memories are in M. Recall forms resonances
(`server.py:2490`), and a resonance that forms again only raises `co_occurrences` and `last_seen`
(`storage.py:2003-2009`). Those two are numbers measured over the whole store (6.4, item 2). They are copied as of the
build and are not in the plan digest.

Late outcomes are the one change before t₁ that can still reach a kept row: `log_outcome` and the Stop hook set a
recall's outcome after the fact (`storage.py:1704-1708`, `hooks/sleep.py:137`). The closed-session rule keeps the
current session out, so this is rare. When it happens, the digest changes and the build refuses (6.1, step 1).

### 5.3 The terms

| Flag | Meaning | Step 1 values |
|---|---|---|
| `--audience` | who may use the imprint | exactly `place:home/<operator>`, for Deep Space 9 `place:home/andy` (D9) |
| `--actions` | what the owner chooses | `imprint` (required), optionally `route`. The permission lists their closure (D10) |
| `--purposes` | why (a set) | `calibration` (required), plus `trail-evaluation` exactly when `route` is chosen (D10) |
| `--days` | days from the owner's yes to the end date | 1 to 365 (D18) |

What the closure means, from the permissions spec's table (its 6.4):

- `imprint` "Keeps a copy as part of another store" and needs `recall`, `read` and `imprint` "on every object
  included". So the memories' record lists all three. With `route`, the package also holds the session ids and log
  rows that make the owner's trails (D7), so the roads-and-trails record lists all three as well.
- `route` "Uses a road or trail as an edge" and needs "`route` on the road or trail; `recall` on every memory it
  names; and `read` and `inject_context` on every memory whose content the answer shows". So the roads-and-trails
  record lists `route`, and the memories' record must list `recall` for the same purpose. It does, because its
  purposes include `trail-evaluation`. The trail evaluation's answer is a report of counts and rates (trail spec
  section 7, step 7). It shows no memory's content to any agent, so it needs no `inject_context`.

The plan prints the closed set in words. The permissions spec defines the general vocabulary. Step 1 accepts only
these values because their meaning is fixed here (section 8).

The audience must be a home place whose handle is the operator's station username. That username must fit the
permissions spec's person grammar `[a-z][a-z0-9-]{0,62}` (its 4.1). Station usernames may also hold `_`, `.` or an
email address (`peer/superyak_peer/auth.py:34-35`). In step 1 such a name can't be a home place, and the station
refuses it. The owner's own username must fit the grammar too, since the permission's layer is the owner's home.

### 5.4 The plan and the dry run

`imprint.py plan` reads the source the way `calibrate.py` does. It takes a snapshot (`calibrate.snapshot`) and a
working copy migrated to this code's schema, both in a 0700 directory beside the plans, and deleted when the
command ends. It never writes the source.

It computes M, the rows of every table that would leave (section 6), the cross-references (section 6.4), and the
**plan digest**:

    plan_digest = SHA-256( canonical({ "filter": "imprint-filter-v1", "scope": scope, "rows": rows }) )

- `canonical` is the peer's canonical JSON (`identity.py:20-23`): keys sorted, `,` and `:` with no spaces, UTF-8,
  no NaN. Every value in it is a string, an integer, a boolean, null, a list or an object. There are no floats.
- `scope` is the request's `scope` object (section 7.1).
- `rows` is an object with exactly the ten keys in the table below. Each value is the list of that table's row keys
  for the rows that ship, as the package will hold them (after scrubbing), sorted by the bytes of each key's canonical
  JSON. An empty table gives `[]`.
- `sha256(v)` is the lowercase hex SHA-256 of a TEXT value's UTF-8 bytes or a BLOB's bytes. A null hashes as the empty
  string. Stored strings are used as stored: `created_at` is not reparsed.

| Table | Row key |
|---|---|
| `episodes` | `[id, lane, created_at, session_id as kept, sha256(content), sha256(context)]` |
| `semantics` | `[id, lane, created_at, sha256(content)]` |
| `episode_vectors`, `semantic_vectors` | `[id, sha256(embedding bytes)]` |
| `semantic_sources` | `[semantic_id, episode_id]` |
| `resonances` | `[id, memory_a, layer_a, memory_b, layer_b, created_at]` |
| `semantic_peers` | `[peer_id, parent_id]` |
| `subdivision_events` | `[id, parent_id, peer_ids as a sorted list]` |
| `memory_log` | `[id, timestamp, event_type, layer, target_ids as a list, context as an object, outcome]`, all as kept |
| `operation_log` | `[id, timestamp, operation, session_id, target_ids as a list, outcome]` |

The keys bind every column the filter reads and every column the trails read, including the log rows' `target_ids`
and each episode's `session_id` as the package holds it (null without `route`).
Counters that change on every recall (access counts, decay strength, confidence, `co_occurrences`, `last_seen`) are
measured numbers, not keys. They are copied as of the build. X and the cross-references are not in the digest input.
Only shipped rows are. Anyone holding the package can recompute the digest from these definitions (check 13).

The plan is saved as `~/.superyak/imprints/plans/<plan id>.json` (0600): selection, X, terms and digest. It never leaves
the machine.

What the owner sees (example numbers):

```
Imprint plan 7c41 (nothing has left this machine)

Store     /home/sam/superyak/engram/.engram/graph.db
Store id  3f2a9c1e (stored, made after store identity; copied from no recorded store;
          lineage complete)
Station   https://smart.tail7db420.ts.net as ship voyager (owner sam)

What would leave
  Episodes        1,204   work lane, 2026-01-01 to 2026-10-25 18:00 UTC
  Semantics          88   work lane; every recorded source is also leaving
  Vectors         1,292   copied as stored, never re-embedded
  Session ids        57   sessions closed by 17:00 UTC: which of them wrote each episode,
                          sent only because you chose route
  Recall log      1,940   rows from those sessions, sent only because you chose route;
                          instinct results, query text and notes removed
  Citing actions      0   a work-lane imprint has none
  Links             240   201 semantic sources, 31 resonances, 8 semantic peers
  With them, route or not: when each memory was written; how often and when last each
  episode was recalled; and the resonances, pairs of memories one recall returned
  together, with when. These show when memories were recalled together.

What stays here
  4,676 episodes, 322 semantics, every instinct, dream residue, task contexts, anchors,
  assessments, notes, clipboard, code index, cold storage, category stores, knowledge graph,
  the session registry (harness, model, working directory).
  Without route, which session wrote each episode, and the recall log, would stay here too.
  The times above would still leave.
  14 semantics stay because a recorded source episode stays.
  3 semantics stay because no source is recorded (add --include-unsourced-semantics to send them).
  912 recall rows stay because a result stays.

Text that names something staying here: 3 episodes. See them with --show-cross-references,
then leave them out with --exclude FILE and plan again.

Other people: these memories may mention people who haven't agreed to share them. Before you
allow, your browser asks you to confirm that nothing here is about such a person, and that none
of it is patient or participant data. If you can't confirm that, narrow the plan or stop here.

Permission you would give
  Audience  place:home/andy (the station's imprint agent, acting for andy)
  Allows    recall, read and imprint on these memories; for the trail evaluation, keeping
            which session wrote each memory and the recall log, which make your trails, and
            route over their roads and trails
  Purposes  calibration, trail-evaluation
  Ends      90 days after you say yes
  Size      41.2 MiB in 11 parts

Plan digest 9d3e…  (your browser will show the same 8 characters)
Read what would leave: make imprint-read PLAN=7c41
Send it:               make imprint-send PLAN=7c41
```

- `make imprint-read PLAN=… [START=… LIMIT=…]` takes a new snapshot as `plan` does, refuses if the digest differs, and
  pages through every memory that would leave in `(created_at, id)` order. Episodes are read as `store_reader
  read_episodes` reads them (`store_reader.py:188-210`), then shown as the package will hold them: its fields include
  `session_id` (`store_reader.py:37-41`), which shows null where the package holds null. That reader reads only
  episodes, so `imprint.py` has its own reader for semantics, in the same order.
- `--list FILE` writes one JSON line `{table, key}` per row that would leave.
- `--json` prints the whole dry run.
- With a permissions ledger on the machine, the dry run also counts memories that stay because they need another
  person's yes, and memories that stay because a lane change at home has not settled (5.2).
- The "Store id" line names the stores this one was copied from (its ancestry, section 11), which the request carries
  and the confirm view names too (7.1, 9).
- A source table no rule names is listed under "What stays here" as not copied (D4).
- The lines on times (the cross-check's XS3; the trail spec's final check FS2; this spec's final check FN1). Each
  recall adds one to `accessed_count` and sets `last_accessed` on every episode it returns
  (`engram/server.py:2388-2391`; `engram/storage.py:627-638`). It also forms a resonance between results it returned
  together, which keeps `created_at`, `last_seen` and `co_occurrences` (`engram/server.py:2488-2491`;
  `engram/storage.py:2001-2012`). So episodes whose last-access times lie a moment apart were very likely returned by
  one recall. These are measured numbers copied as of the build (6.4, item 2), with or without `route`. None names a
  session. Telling the owner lets nothing more leave. The confirm view says the same (section 9).

## 6. Filtering at the source

### 6.1 How the package is built

`imprint.py build --plan ID`:

1. Take a new snapshot and working copy (as in 5.4) and recompute the plan. If the digest differs, stop: "Your store
   changed since the plan. Run the plan again."
2. Refuse if the plan has cross-references not in X (6.4, item 1).
3. Create `~/.superyak/imprints/<imprint id>/` (0700). `imprint id` is a new lowercase `uuid4`.
4. Create `imprint.db` with `Storage(path)`. A fresh file gets every migration (`storage.py:189-243`). Then call
   `store_identity.stamp_imprint` (section 11) on the same connection.
5. With foreign keys off, insert the rows of section 6.2 table by table, with explicit column lists that never name
   `rowid` (D33). Memories go in `(created_at, id)` order and vectors in the order of their memories, so every memory
   table's rowids run 1..n and say nothing about the rows left out. Copied rowids would show gaps, and so how many rows
   stayed home between two kept ones. The FTS indexes use the base tables' rowids (`content_rowid=rowid`,
   `002_v3_layers.sql:72-76`, `:96-100`), so they inherit 1..n. Vectors are inserted as the source's raw `embedding`
   bytes. The FTS triggers fill `episode_fts` and `semantic_fts` (`002_v3_layers.sql:102-105`,
   `015_dispositions.sql:60-63`). vec0 fills its own shadow tables.
6. Check that `PRAGMA foreign_key_check` returns nothing and `PRAGMA integrity_check` returns `ok`.
7. Set `PRAGMA journal_mode=DELETE`, run `VACUUM`, then check that `PRAGMA freelist_count` is 0. `Storage` opens in
   WAL (`storage.py:122`), and a WAL file can't be read in a read-only directory without side files.
8. Run the leak checks L1–L4 (section 6.4).
9. Write `manifest.json` (section 7.2) and set `imprint.db` to 0400.
10. Delete the snapshot and the working copy.

Built by insertion, the file never held a left-out row, so no page, FTS segment or vec0 chunk was written from one.
sqlite-vec deletions may leave vector bytes in chunk blobs. Insertion avoids depending on that (D3), and L3 checks it.

### 6.2 Every table

The tables below are every table the migrations create (`001`–`028`), plus the tables the hooks create in
`graph.db`. A table whose name starts with a virtual table's name and `_` is that table's shadow. It is never copied;
SQLite or sqlite-vec rebuilds it from the inserts.

A source table no rule names is not copied, and the dry run names it (D4). A table the package's migrations create
that no rule names stops the build. That is a bug in this code, and the test "Every table classified" catches it.

"Dropped" means no row is copied. A dropped table that a migration creates exists in the package, empty. A
hook-only table is absent.

| Table | Rule | Why |
|---|---|---|
| **Memories** | | |
| `episodes` | filtered: rows in E, every column except `rowid`, in `(created_at, id)` order; `session_id` scrubbed to null unless the terms include `route` and its session is closed at t₁ (5.2) | the memories chosen; a session id is the thread the owner's trails are made of (D7) |
| `semantics` | filtered: rows in S, in `(created_at, id)` order; `contradicted_by` set to null when it names a semantic outside S | it would name a memory that stayed |
| `instincts` | dropped | instincts never leave (permissions spec 5.2) |
| **Vectors (vec0)** | | |
| `episode_vectors`, `semantic_vectors` | filtered: id in E, S; bytes as stored | no re-embedding, so no embedder needed |
| `instinct_vectors`, `instinct_context_vectors` | dropped | instincts |
| `entity_vectors` | dropped | code index |
| `residue_vectors` | dropped | dream residue |
| vec0 shadow tables | rebuilt by inserts | never copied (6.1) |
| **Full-text (FTS5)** | | |
| `episode_fts`, `semantic_fts` | rebuilt by the insert triggers | external-content indexes; copying would carry left-out terms |
| `entity_fts` | rebuilt, empty | entities dropped |
| FTS5 shadow tables | rebuilt | |
| **Links** | | |
| `semantic_sources` | filtered: semantic in S and episode in E | induced on M (6.4) |
| `instinct_sources`, `instinct_co_firing` | dropped | instincts |
| `resonances` | filtered: `memory_a` and `memory_b` each in M under `layer_a` and `layer_b`, and `created_at` in [t₀, t₁) (5.2) | read by calibration's generativity (`persistence.py:174`) |
| `semantic_peers` | filtered: `peer_id` and `parent_id` in S | |
| `subdivision_events` | filtered: `parent_id` and every id in `peer_ids` in S | read by calibration's conjunct audit (`persistence.py:222`) |
| `entities`, `relationships`, `episode_entities` | dropped | the code index of the repository the server ran in (`indexer.py:324-364`); not memories, and the station has no code to index |
| **Logs** | | |
| `memory_log` | only when the terms include `route` (D7); filtered and scrubbed; see below | the trails read these (trail spec section 4); calibration doesn't (5.2) |
| `operation_log` | only when the terms include `route` (D7); filtered and scrubbed: only `operation` in `CITING_OPERATIONS` (`hooks/sleep.py:44`), passing the log-row rule (5.2), with every target in M. `harness`, `model`, `repo` set to null and `details` to `{}` | the trail cited-touch rule reads them. `repo` is the session's working directory (`server.py:82-85`, `:1340`) |
| `session_registry` | dropped | harness, model and repo provenance (`023_session_registry.sql:1-2`); no step 1 use |
| `session_bindings` | dropped | runtime-only (`024_session_bindings.sql:1-2`) |
| **Caches and session state** | | |
| `persistence_scores` | dropped | a cache (`021_persistence.sql:2`); calibration recomputes without caching (`calibrate.py:142-143`) |
| `subdivision_queue` | dropped | maintenance queue |
| `instinct_context_feedback` | dropped | `context_text` is free text about what the person was doing, with no lane |
| `instinct_clusters`, `instinct_cluster_members` | dropped | instincts |
| `lens_cluster_affinity` | dropped | reserved, unused (`016_instinct_clusters.sql:30`) |
| `session_bias` | dropped | per-session tilt (`011_session_bias.sql`, `hooks/nudge.py:140`) |
| `context_threads`, `context_prev_embedding`, `nudge_co_fire_window`, `nudge_surfaced` | dropped | made in `graph.db` by the hooks (`hooks/nudge.py:161`, `:170`, `:354`, `:428`; `hooks/wake.py:494`). `context_prev_embedding.message_text` is the person's last prompt |
| **Personal layers not in step 1** | | |
| `residue` | dropped | `reaction` holds raw text (`010_dream_residue.sql:13`) |
| `task_contexts` | dropped | working plans, no lane |
| `anchors`, `drift_reports` | dropped | identity anchors and drift summaries |
| `assessments` | dropped | self-reports |
| **Sharing** | | |
| `shared_memories` | dropped | records copies made for other audiences (`sharing.py:167-172`) |
| **Bookkeeping** | | |
| `schema_version` | rebuilt by the migrations that create the package | |
| `meta` | rebuilt: only the imprint's identity keys (section 11) | the only other key, `last_indexed_commit` (`indexer.py:458`), belongs to the code index |
| `sqlite_sequence` | rebuilt, never copied | vec0's `_chunks` and `_rowids` shadow tables use `AUTOINCREMENT`, so the inserts fill it (measured with sqlite-vec 0.1.7). It is not counted in `contents` and is not a dropped table for check 9. Its values equal the inserted counts, since nothing is deleted |
| `sqlite_stat1`–`4` | never copied, never created | the build runs no `ANALYZE` |

**`memory_log`.** Kept: rows with `event_type` = `recall` or `route_shown` that pass the log-row rule (5.2).

- **Recall rows.** Remove from `target_ids` every id that is an instinct in the source. Instincts never ship, and a
  plain recall mixes layers and lanes: instincts are vector candidates whenever `layer` is not given
  (`server.py:1643-1645`), and lanes are filtered only when `lane` is given (`server.py:2332`). The row is kept only
  if what remains is not empty and every remaining id is in M. A row with any other target outside M is dropped
  whole: it never ships cut, and nothing marks that it was. The trail spec asked for cut rows with a `cut` flag (its
  interface item I4). The interface pass declined that, since the flag says that something the recall matched stayed
  home (D21). The trail spec records what this costs its evaluation (its section 7). `context` becomes
  `{recall_id, session_id}`, keeping those present. `outcome` becomes `used: auto: cited` (`hooks/sleep.py:43`) when equal to it, else `used` or
  `not_used` by prefix, else null. `context.query` is the person's words (`server.py:2376`, `:2102`, `:2181`), and an
  outcome may carry a free-text note (`server.py:2629-2631`).
- **`route_shown` rows** (trail spec section 6.6, its interface item I1). `target_ids` is cut to the ids in M, in
  order. A row cut to nothing is dropped (D35): a tool answer names at least one memory (trail spec 6.6), so an empty
  list would say that everything it named stayed home. The row is kept only if `context.lane` ∈ L. `context` becomes
  `{receipt_id, session_id, tool, lane}`, keeping those present, and `outcome` stays null. Without these rows, a
  session the tools steered looks unsteered on the imprint, and its suggested touches would count as support.
- Every other event type is dropped.

Memory rows are copied whole but for two columns. The only scrubbed columns are the ones named in the table:
`episodes.session_id` (null without `route`, and null for a session open at t₁); `semantics.contradicted_by`;
`memory_log.target_ids` (instinct ids removed from recall rows, ids outside M cut from `route_shown` rows),
`memory_log.context` and `memory_log.outcome`; and `operation_log.harness`, `model`, `repo` and `details` (D6).

A kept recall row keeps every result that isn't an instinct, and the trail spec removes instinct targets before it
counts a recall's targets (its section 4, "Cited touches"). So filtering never creates the trail spec's "exactly one
target" case, and removing instinct ids changes no trail result. It reveals nothing either: no instinct id ships.

For a work-lane imprint, no `operation_log` row ships. `mark_core` refuses work-lane episodes (`server.py:3055-3056`),
and the other two citing operations name instincts and residue, which never ship.

### 6.3 The store's other files

None of these leave in step 1:

- `cold.db`: pruned episodes; vectors already stripped (`storage.py:794-842`).
- `categories.db`: legacy cells whose content is the query text and notes (`server.py:2685-2693`).
- `categories_v2.db`: query terms in events and contexts (`category_evolution.py:1079`, `:1106`, `:1119`).
- `knowledge.kuzu`: LLM-extracted facts that merge across episodes, so they can't be filtered per memory.
- `clipboard.db` (`server.py:1483`), `notepad.db` (`server.py:3665-3666`), `instinct_transitions.db`
  (`server.py:407`), `lighthouse-disclosures.db` (`lighthouse_daemon.py:516`), `signals.db`, `instances.json`,
  `genome/`, and any `-wal` or `-shm`.

The trail evaluation needs only `graph.db` (trail spec section 7).

### 6.4 The no-leak property and its checks

The store, read as a graph whose objects are memories and whose arrows are link and log rows, gives the package as
the **sub-structure induced by M**. For each table rule above, a row r naming the memory ids ref(r) is kept only if
ref(r) ⊆ M, under the layer each column names. The two exceptions are scrubs that remove ids: instinct ids from recall
rows, and ids outside M from `route_shown` rows.

**Property P.** For every row r in the package, every memory r names, and every memory r was derived from through
`semantic_sources` as recorded at the build, is admissible (in Ê ∪ Ŝ). Every entry of every FTS and vec0 index in the
package belongs to a row in the package.

P holds by construction:

- memories are in M ⊆ Ê ∪ Ŝ;
- semantics are closed downward over their recorded sources (5.2);
- link and log rows are induced on M, after the two id-removing scrubs;
- scrubbed columns are cleared;
- dropped tables are empty;
- indexes are built only by inserting kept rows, and L2 and L3 check that they hold exactly those.

What P does not cover, stated plainly:

1. **Free text inside a chosen memory.** It is the owner's content, so the owner decides. The build scans it for
   **cross-references**. The **left-out keys** X* are every value of a single-column TEXT primary key (or a vec0 `id`)
   of a row of the source's `graph.db` or `cold.db` that does not ship, minus the session ids that shipped rows keep in
   their kept columns, compared ignoring case. So X* includes left-out memories and instincts, and residue, task
   contexts, anchors, assessments, drift reports, log rows, every registered session (`session_registry`'s key) and
   every other table's keys. Revision 2 also subtracted recall ids. A recall id is no table's key
   (`server.py:2369-2384` keeps it inside `context`), so that subtracted nothing and is gone. Without `route`, no
   session id ships, so nothing is subtracted, and text in a chosen memory that names a registered session's id is a
   cross-reference too. A UUID token (L1) in the package that is in X* is a cross-reference. The build refuses until each cross-reference's memory is
   left out with `--exclude` (D23). Step 1 has no flag that keeps one: the browser yes never shows such a choice, and
   the agent running the commands could pass it.
2. **Numbers measured over the whole store** and kept on chosen rows: decay strength, access counts, innovation,
   confidence, reinforcement counts, resonance counts, link similarity and weights. No left-out memory's id or content
   can be recovered from them.
3. **Timestamps of chosen rows.** Gaps between them stay visible.
4. **Sources Engram no longer records.** Down-closure checks only recorded sources (5.2). A semantic whose sources
   were partly pruned is judged on the rest. One with none recorded ships only with `--include-unsourced-semantics`.
5. **Other people.** Vision principle 1: "Anything about a person moves only with that person's yes." An owner's
   memories can be about their family, colleagues, and in this project patients or participants. The DS9 spec keeps
   "No patient or participant data" out of ship rooms (DS9 spec, line 78). Step 1 can't ask those people. It removes
   memories with a recorded co-subject (5.2) and asks the owner to confirm the rest in the browser (D27, section 8).
   It has no name detector. The permissions spec's step 4 may add one that only adds co-subjects (its 7.4). This is
   the one place step 1 rests on the owner's word about other people, and Open for Andy (section 20) asks whether
   that is acceptable at all.
6. **Later changes at home.** The imprint is a copy as of the build. A later re-lane, edit or exclusion at home does
   not reach it. The owner withdraws and sends again. This is the permissions spec's "content already delivered"
   case (its section 10). r_M names no lane (D36), so no decision at the station reads one.

**The leak checks** (D34). All of them read the finished, vacuumed `imprint.db`.

- **L1. Value scan.** For every ordinary table in `sqlite_master` (every shadow table, `sqlite_sequence` and `meta`
  included; virtual tables are read through their shadow tables), `SELECT` every row and read every value. SQLite
  reassembles overflow pages, so a value split across pages is read whole. Each TEXT value, and each BLOB value read
  as Latin-1, is scanned for UUID tokens, ignoring case:

      [0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}

  No token may be in X*. The tests also scan for planted canaries this way. L1 can't see inside FTS5 term lists,
  because FTS5 stores terms prefix-compressed; L2 covers them.
- **L2. FTS index equality.** For each FTS5 table F (`episode_fts`, `semantic_fts`, `entity_fts`) with base table B
  and columns c₁…c_k, build a scratch FTS5 table in a scratch file with the same columns and options as F's DDL,
  without `content=` and `content_rowid=`. Insert `(rowid, c₁…c_k)` for every row of B in rowid order. Then the
  `fts5vocab` `instance` rows `(term, doc, col, offset)` of F and of the scratch table, both read in that order, must be
  equal, and `F_docsize`'s ids must equal B's rowids. The comparison streams row by row, so memory stays bounded.
  FTS5's own `'integrity-check'` is not enough: the review measured that it passed an index entry with no content row,
  and this revision's run saw the same.
- **L3. vec0 slots.** For each vec0 table V (`id TEXT PRIMARY KEY, embedding float[d]`) with base table B, read its
  shadow tables directly. They are plain tables, laid out as sqlite-vec 0.1.7 writes them (measured):
  - `V_rowids(rowid, id, chunk_id, chunk_offset)`: the set of `id`s equals the set of ids of B's shipped rows that have
    a vector, and each row names a slot that is valid.
  - `V_chunks(chunk_id, size, validity, rowids)`: `validity` has `size / 8` bytes, and slot i is valid when bit
    `i mod 8` (least significant first) of byte `⌊i / 8⌋` is set. `rowids` has `8 × size` bytes, one little-endian
    int64 per slot. A valid slot's value is the rowid of the `V_rowids` row that names it. An invalid slot's value is 0.
  - `V_vector_chunks00(rowid, vectors)`, with rowid = `chunk_id`: `vectors` has `4 × d × size` bytes, and slot i is
    bytes `[4·d·i, 4·d·(i + 1))`. Every invalid slot's bytes are all zero. A valid slot's bytes equal the source's
    `embedding` bytes for that id (checked at the build; on the Pi, against the plan digest's vector keys).
  - `V_info` equals the reference's (check 7), so a package from another sqlite-vec version is refused, not misread.
- **L4. Raw-byte scan** (extra). Read the file in 1 MiB chunks, each overlapping the next by 35 bytes, since a UUID is
  36 bytes. Scan for UUID tokens ignoring case. None may be in X*. This scan cannot see three things, all measured: a
  term FTS5 stored prefix-compressed after a term sharing its start (this revision's run: a 17-letter term after one
  sharing 14 letters was absent from the raw bytes as a whole); a UUID the FTS5 tokenizer split at its hyphens (seen
  in both runs; the regex found nothing); and a value split across overflow pages (the review: 10 of 1,286 offsets).
  L1–L3 cover all three. L4 also reads free space, which `freelist_count` = 0 says is empty.

**Where they run.** The build runs L1–L4 and stops on any failure. The Pi runs L2 and L3 again (checks 16 and 17).
Those two need nothing the Pi doesn't hold. L1 and L4 need X*, the keys of what stayed home, which the Pi never sees.
The Pi's structural checks (10, 11) instead require that every id-shaped key column names a row in the package.

## 7. The request and the manifest

### 7.1 The request (before the yes)

The request holds only what the confirm view shows, plus its fixed labels `kind` and `version` (D26). `make
imprint-send` prints it in words before it sends it, and then says: "This goes to the station now, before you say
yes. It holds only what your browser will show. No memory leaves until you allow it. If you decline, or don't answer
within 10 minutes, the station deletes the request (at once when you decline, within an hour when it expires) and
keeps a row with its ids, your ship and its times, and no scope or counts, for 30 days. Its nightly backups keep that
row about 8 weeks more. If you allow, the station keeps the permission, its receipts and that row until 400 days after
the copy is deleted (backups about 8 weeks more). Nothing is kept with no end." (D32.)

```json
{
  "kind": "engram-imprint-request",
  "version": 1,
  "imprint_id": "c0a8f5e2-…",
  "plan_digest": "9d3e…",
  "source_instance_id": "3f2a9c1e-…",
  "source_ancestry": [], "source_ancestry_complete": true,
  "scope": {"lanes": ["work"], "layers": ["episode", "semantic"],
            "since": "2026-01-01T00:00:00Z", "until": "2026-10-25T18:00:00Z",
            "shared_with": null, "unsourced_semantics": false},
  "contents": {"episodes": 1204, "semantics": 88, "episode_vectors": 1204, "semantic_vectors": 88,
               "semantic_sources": 201, "resonances": 31, "semantic_peers": 8, "memory_log": 1940},
  "package": {"bytes": 43188224, "parts": 11},
  "terms": {"audience": ["place:home/andy"], "actions": ["imprint", "route"],
            "purposes": ["calibration", "trail-evaluation"], "days": 90}
}
```

- `contents` has one key for each of the ten tables of 5.4 (`episodes`, `semantics`, `episode_vectors`,
  `semantic_vectors`, `semantic_sources`, `resonances`, `semantic_peers`, `subdivision_events`, `memory_log`,
  `operation_log`) that holds at least one row in the package, and no other key. Each value is that table's row count.
  So `meta`, `schema_version`, the FTS tables, shadow tables and `sqlite_sequence` are never counted.
- `source_ancestry` and `source_ancestry_complete` are the source's ancestry and its completeness (section 11): the
  ids of the stores the source was copied from, nearest first. They are ids, not content, and the confirm view names
  them.
- The view shows every field but the two labels: `imprint_id` by its short id (`c0a8`), and `plan_digest` by its first
  8 characters, with the words "the whole 64-character digest is sent".
- `since` is null for t₀ = −∞.
- `parts` = ⌈`bytes` / 4,194,304⌉. Here 43,188,224 bytes (41.2 MiB) give 11 parts.
- `request_sha256` = SHA-256 of the request's canonical JSON. The permission binds it (section 8).

### 7.2 The manifest (after the yes)

`manifest.json` is canonical JSON with no floats, so the source and the station compute the same bytes.
`manifest_sha256` = SHA-256 of those bytes. It is the first thing sent after the yes (section 9).

```json
{
  "kind": "engram-imprint-manifest",
  "version": 1,
  "imprint_id": "c0a8f5e2-…",
  "filter": "imprint-filter-v1",
  "plan_digest": "9d3e…",
  "request_sha256": "…",
  "built_at": "2026-10-25T18:04:11Z",
  "engram_commit": "3269091…",
  "source": {"instance_id": "3f2a9c1e-…", "identity": "present",
             "ancestry": [], "ancestry_complete": true},
  "schema": {"applied": [1, 2, 3, "…", 28]},
  "embedding": {"model": "nomic-ai/nomic-embed-text-v1.5", "dimension": 768},
  "vec": {"create_version": "v0.1.7"},
  "scope": {"…": "the request's scope"},
  "contents": {"…": "the request's contents"},
  "package": {"file": "imprint.db", "bytes": 43188224, "sha256": "…",
              "part_bytes": 4194304, "parts": ["<sha256 of part 0>", "…"]}
}
```

- `source.instance_id` is `store_identity.effective_id` of the snapshot. `identity` is `present` when stored and
  `derived` when the store predates identity and this is the id its migration will derive
  (`store_identity.py:84-116`). `ancestry` and `ancestry_complete` are the source's (section 11), and equal the
  request's `source_ancestry` and `source_ancestry_complete`.
- `schema.applied` is the package's `schema_version` set.
- `embedding.model` is the constant `embeddings.py:70` names. `dimension` is read from the vec0 DDL.
- `vec.create_version` is the package's vec0 `_info` `CREATE_VERSION`.
- `engram_commit` is `git rev-parse HEAD` of the engram checkout, or null.
- `scope`, `contents`, `imprint_id`, `plan_digest`, `source.instance_id`, `source.ancestry`,
  `source.ancestry_complete`, `package.bytes` and the number of `package.parts` equal the request's, and
  `request_sha256` is the request's hash. The station refuses a manifest that differs.
- Part n covers bytes [n·B, min((n+1)·B, size)) with B = `part_bytes`.
- The filter name stays `imprint-filter-v1`: nothing is built, so no package of an older form exists.

The manifest names the source, the package and the scope. It has no counts of what stayed, no ids, and no flags
about exclusions or cross-references (D21).

## 8. The owner's yes and the signed permission

**Why a browser yes.** An agent on the source machine can read any file there, including a private key. A signature
by such a key would not show that a person said yes. Ships "have no usable password, cannot sign in through
`/api/login`" (DS9 spec, lines 39-41; `auth.py:90` accepts only `kind = 'person'`), and station law says "Never ask
for or type a person's password". So the yes is a person signed in to the station, typing their password again on
the confirm view. The password is checked as `/api/login` checks it, and attempts count against the same limits:
8 per user and 40 per source per 5 minutes (`auth.py:85`, `:94`) (D1).

**The owner's check about other people** (D27). The confirm view has a box the owner must tick: "Nothing I am sending
is about another person who hasn't agreed to share it, and none of it is patient or participant data." The station
refuses the confirm without it, and the record holds `attestation: "no-unconsented-others-v1"`. The view says: "If you
can't confirm this, don't allow. Narrow the plan on your machine, or stop."

**The record.** When the owner allows, the station writes and signs, in the same transaction, a record of the new
kind `imprint-permission`. It wraps permissions-spec records, which are the owner's consent, with the fields that bind
them to this one copy:

```json
{"kind": "imprint-permission", "station": "<station peer id>", "id": "<request id>",
 "owner": "person:sam", "owner_id": "<user id>", "ship_id": "<ship id>",
 "imprint_id": "c0a8f5e2-…", "source_instance_id": "3f2a9c1e-…",
 "request_sha256": "…", "plan_digest": "9d3e…",
 "attestation": "no-unconsented-others-v1", "created": 1792951950,
 "records": [<memories record>, <roads and trails record>]}
```

Each entry of `records` has exactly the permissions spec's record fields (its 5.1), less the ledger-only ones
(`created_seq`, `revoked`, `revoked_by`, `revoke_reason`, `revoked_seq`). Withdrawal and shortening are receipts here
(section 12). The memories record, r_M:

```json
{"id": "r-5b0d…", "layer": "place:home/sam", "effect": "allow",
 "selector": {"audience": ["place:home/andy"], "requesters": ["agent:station-imprints"],
              "objects": {"kinds": ["memory"], "stores": ["3f2a9c1e-…"], "layers": "*", "lanes": "*",
                          "collections": ["collection:sam/imprint-c0a8f5e2-…"], "memories": "*"},
              "actions": ["imprint", "read", "recall"], "purposes": ["calibration", "trail-evaluation"]},
 "valid_from": 1792951950, "valid_until": 1800727950, "anchor": 1792951950, "backing": "person",
 "set_by": "person:sam", "channel": "browser", "under_grant": null, "proposal_id": null, "replaces": null,
 "reason": "imprint c0a8 at Deep Space 9", "created": 1792951950}
```

The roads-and-trails record, r_T, is present only when the owner chose `route`. It differs in `id` and in its selector:
`objects` = `{"kinds": ["road", "trail"], "stores": ["3f2a9c1e-…"], "layers": "*", "lanes": "*", "collections": "*",
"memories": "*"}`, `actions` = `["imprint", "read", "recall", "route"]` and `purposes` = `["trail-evaluation"]`. The
permissions spec requires `"*"` in those four object dimensions for roads and trails (its 5.2), and a finite `stores`
list for one that leaves a home (its P28). `imprint`, `read` and `recall` are there because the package keeps the
session ids and log rows that make the owner's trails (D7, D10). Its one purpose is `trail-evaluation`, so nothing
may read the trails for `calibration`, and admission's calibration doesn't (section 10; the final check's FS1).

r_M's `layers` and `lanes` are `"*"` (D36; Rio Grande's call, from the re-check's RS1). Its one collection fixes which
memories it reaches, and P28 lets layers and lanes only narrow it, so naming them would add nothing. With `"*"`, no
decision under r_M depends on where a lane is read: at home from the source's lane notes, at the station from the
imprint (permissions spec 5.3, "A copy held away from its source's ledger"), or in a step-2 ledger, which would hold
no lane notes for `mem:S/…` refs, so that a list of lanes would match nothing there ("a memory with no lane note
matches no allow whose `lanes` is a list", its 5.3). The scope's lanes and layers stay in the request, the manifest
and check 12, so the owner still sees them and the Pi still checks them. The permissions spec's own example of an
allow by collection names `"*"` there too (its 5.2).

- Every list is sorted, as the permissions spec's selector requires (its 5.2). Ids are `r-` plus 32 random lowercase
  hex.
- Times are integer UTC seconds (its P14). `valid_until` = `valid_from` + days × 86,400. In the example the yes is
  2026-10-25T18:12:30Z and the end is 2027-01-23T18:12:30Z. Integers also avoid the float form that API.md warns
  differs between languages (`peer/API.md:270-274`).
- `channel` is `browser`, the channel the permissions spec's step 2 adds (its 5.1 and 14). Imprints are its first user.
- An outside-home allow needs named purposes and an end at most 366 days out (its P13). These do: the audience is not
  the owner's home unless the owner is the operator ("When the owner is the operator", below).
- `imprint-permission` and its keys are added to `identity.RECORD_KEYS` (`identity.py:76-83`), so `sign_record` signs
  it (`identity.py:147-151`) and it can't pass as another kind. `verify_station_record` (section 15) also checks that
  each `records` entry has exactly its keys.
- The permissions spec plans station-signed `permission-record` and related kinds for its step 2 (its section 14,
  step 2). That list now names `imprint-permission` and `imprint-receipt` as the first station-signed kinds. Each
  inner record is already in the form a `permission-record` signs, so step 2 adds no second form (Rio Grande's call,
  from the interface pass).

**Why a collection** (D36). An allow that leaves a person's home reaches memories only by listed ids or collections;
stores, layers and lanes may only narrow it (permissions spec P28 and 5.4). So r_M names one collection,
`collection:<owner handle>/imprint-<imprint_id>`, which fits that spec's grammar (its 4.1). Its members are exactly
objects(I) (below): the shipped refs, which the plan digest binds and the owner's yes covers, so the memberships are
person-backed. Nothing adds a member after the yes. The station holds no permissions ledger in step 1, so the
collection lives in the signed permission as this definition, and the owner's machine keeps its member list in
`objects.json` (section 12). A collection holds at most 100,000 members (its 5.4), so an imprint holds at most
100,000 memories.

**Uses on the station.** A use is the permissions spec's u = (a, P, o, h, x, p, t) (its 6.1, revision 3). In step 1
the station has exactly one requester: a = `agent:station-imprints`, the imprint runner, acting for the operator in
P = `place:home/<operator>`. Andy's ships and Claude sessions are not requesters. Claude on the Pi running `make
station-imprint-use` when Andy asks is a caller of that agent. The record's `requesters` names only that agent, so
nothing else in Andy's home is allowed by it. h is the copy: every use of imprint I names h_I =
`imprint:<station peer id>/<imprint_id>`, and its holding place H is the operator's home, as that spec's 6.1 fixes it
for a station with no ledger. t is the station's clock.

**The objects.** For an imprint I of a source store with instance id S, objects(I) is the set of refs
`mem:S/<layer>/<id>` of its shipped memories (permissions spec 4.1). Memory ids are kept (D11), so these are the
owner's own refs. The trail evaluation derives roads and trails of S from I in memory. Each is an object of kind
`road` or `trail` in store S.

- **Subjects.** Every object in objects(I) keeps its source's subjects: the source store's owner (permissions spec
  P12). No memory with another subject ships (5.2). The station that holds the copy is never a subject of it. The
  permissions spec's own review asks for exactly this (its MF6), and naming objects by source refs gives it.
- **A fixed set.** r_M reaches memories only through its collection, whose members are objects(I), the set the plan
  digest binds. Its store only narrows, and it names no layer or lane. A memory written at home after the build is
  never covered.
  The permissions spec's review warns that an allow by store and lane covers memories an agent writes later (its
  MF14). This one can't, by that spec's own rule (its P28).

**The denotation.** For a record r of the permission p, match(r) ⊆ 𝒰 is the set of uses r matches by the permissions
spec's 5.3, rules 1–3, read this way:

- the audience `place:home/<operator>` matches a use whose place is that home (it is a root, so `dom` is itself);
- r_M names `"*"` layers and lanes, and r_T must (its 5.2), so neither reads a memory's lane. Should a later record
  over an imprint name lanes, that spec's 5.3 ("A copy held away from its source's ledger") reads them from the
  imprint, where the build fixed them;
- a memory is in the collection exactly when it is in objects(I), with a person-backed membership from the yes;
- r stops matching when the owner withdraws (rule 1, "not revoked"), and the owner's shortening to e replaces
  `valid_until` by min(`valid_until`, e). That is a replacement with `replaces` = r, which matches only what r
  matches (its rule 4). The owner does both in the browser.

Then ⟦p_I⟧ = match(r_M) ∪ match(r_T) for I's own records (with match(r_T) = ∅ when r_T is absent).

**The station's ceiling** (D38; Rio Grande's call, from the re-check's RS2 and RN7). Let

    C = { (recall, calibration), (read, calibration), (imprint, calibration),
          (recall, trail-evaluation), (read, trail-evaluation), (imprint, trail-evaluation),
          (route, trail-evaluation) }

For an imprint I, with records r_M and r_T, the ceiling ⟦c_I⟧ is the set of uses u = (a, P, o, h, x, p, t) with:

1. a = `agent:station-imprints`, P = `place:home/<operator>`, and h = h_I;
2. o ∈ objects(I) and (x, p) ∈ actions(r_M) × purposes(r_M), or o ∈ R(I), the roads and trails of S derived from I
   (defined under "The decision" below), and (x, p) ∈ actions(r_T) × purposes(r_T);
3. (x, p) ∈ C;
4. `valid_from` ≤ t < the effective end of I: the earliest of its records' `valid_until` and every shortening of I,
   by the owner or the ship (section 12);
5. t is before every `withdrawn` receipt of I, by the owner or the ship.

The station's layer is ⟦c⟧ = the union of ⟦c_I⟧ over its imprints. It is the station's own consent layer in step 1:
one rule, fixed in code, over the station's own signed records and receipts. No one edits it when anyone acts. The
ship's withdrawal or shortening writes a receipt, and items 4 and 5 read it. A place's later rules can only remove
from it. Andy accepts it as his home's rule for imprints before the first one (section 18), since the operator's home
is his (permissions spec section 2, "Home place").

**Why the station's check is the permissions spec's meet.** In that spec's terms (its 6.1 and 6.3), a use of copy I
has `Req` = {the owner's home layer, the operator's home layer}: the requester's place and the holding place are both
`place:home/<operator>`, counted once. The agent's restriction layer is empty, and there are no legacy layers. At the
station the owner's layer holds every allow the station holds for that owner: the records of every imprint J the
owner sent here, so it is the union of the ⟦p_J⟧. Now take a use u of copy I.

- u is in ⟦c⟧ only through ⟦c_I⟧, since item 1 names h_I.
- Every u in ⟦c_I⟧ is in ⟦p_I⟧. Item 1 gives the audience and requester that r_M and r_T name. Item 2 gives the
  action, the purpose and every object dimension: the store is S, the collection holds o, and the other dimensions
  are `"*"`. Items 4 and 5 give that the record in force, after any replacement, is valid and unrevoked at t.

So a use of copy I is in the meet over `Req` exactly when it is in ⟦c_I⟧, and ⟦c_I⟧ = ⟦p_I⟧ ∩ ⟦c_I⟧. That holds however
many imprints the owner holds here, and however the others ended. The station decides with I's own records and
receipts alone, and that is the meet.

Revision 2's ceiling named only the copy and C. Then the station's per-imprint check was never wider than the meet,
but the meet could be wider than it. A copy the ship withdrew keeps r_M and r_T unrevoked until their end (D17), and
they match the same refs, and the same store's roads and trails, in a later copy of the same store, since no selector
names a copy (permissions spec 6.1). So if copy 1 had `route` and copy 2, with no `route`, held only memories copy 1
held, the meet would have allowed a trail evaluation on copy 2 through copy 1's r_M (the re-check's RS2). Items 2, 4
and 5 close that.

From step 2, a ledger may add the owner's denies at home to the owner's layer. The meet is then narrower than ⟦c_I⟧,
never wider, and the station decides with the permissions spec's `decide` (section 17).

**When the owner is the operator** (carried by the permissions spec's reviser; Rio Grande's call, corrected after the
cross-check's XM1). Andy may imprint his own store here, and then the owner's home and the operator's home are one
place. The permissions spec counts a layer that appears twice once (its 6.3), so `Req` holds one home layer, not two.
A consent layer there is the union of its allows less its denies (its 6.1). If the ceiling were read as one more allow
in that layer, it would stop narrowing: after the ship withdrew a copy, the owner's unrevoked r_M would still match
that copy's uses, since no selector names h. So the ceiling is never one more allow. At the station the one home
layer `place:home/<operator>` is the ceiling itself, ⟦c⟧, for every copy, whoever owns it, as that spec's 6.1 lets a
layer kept outside a ledger be. The operator's own records add nothing there. Let 𝒰_other be the uses of copies whose
owner isn't the operator, and J range over the operator's own imprints. Each ⟦c_J⟧ ⊆ ⟦p_J⟧ (above), and every other
copy's ceiling lies in 𝒰_other, so

    ⟦c⟧ ∩ (∪_J ⟦p_J⟧ ∪ 𝒰_other) = ⟦c⟧.

Then the argument above holds word for word. A use of the operator's copy I is in the one layer exactly when it is in
⟦c_I⟧, since item 1 names h_I, and ⟦c_I⟧ = ⟦p_I⟧ ∩ ⟦c_I⟧. A use of another owner's copy meets that owner's layer and
⟦c⟧, as above. The station's code doesn't change, since it decides each copy by ⟦p_I⟧ ∩ ⟦c_I⟧ ("The decision",
below). Revision 5 defined the layer as (∪_J ⟦p_J⟧) ∩ ⟦c⟧. That set holds no use of another owner's copy, so the
meet would have refused every other owner's imprint while the station's check allowed it. It failed closed, and no
step-1 verdict changed.

In a step-2 ledger, the owner's home and the operator's home are ledger layers, and the ceiling stays a layer kept
outside the ledger (section 17, step 1), a term of the meet beside them. So a use of copy I is allowed only within
⟦c_I⟧ less the home's denies, never wider. Which item of the permissions spec's `Req` holds the ceiling there is
that spec's step 2 to say (its 14; the cross-check's XN6).

**The ship's withdrawal and shortening** (D17). The requesting ship acts for the owner. But the permissions spec lets
an agent edit a person's layer only under that person's grant (its P10 and 7.1), and step 1 makes no grants. So the
ship never revokes or replaces r_M or r_T. Its withdrawal is the station refusing at the owner's agent's request: it
writes a `withdrawn` receipt, and from that moment ⟦c_I⟧ holds no use of this copy (item 5), as a place may always
refuse what a person allowed (its 7.5). Its shortening to e writes a `shortened` receipt, and ⟦c_I⟧ then holds no use
at or after e (item 4). Both only narrow. Both act at once and never wait for Andy. Rio Grande's call.

**The decision.** Each step-1 use kind k expands, at time t, into the finite set of uses it needs:

    Need(admission, t)        = { (a, P, o, h_I, x, calibration, t) : o ∈ objects(I), x ∈ {recall, read, imprint} }
                              ∪ { (a, P, o, h_I, x, trail-evaluation, t) : o ∈ R(I), x ∈ {recall, read, imprint} }
                              ∪ { (a, P, o, h_I, x, trail-evaluation, t) : o ∈ objects(I), x ∈ {recall, read} }
    Need(trail-evaluation, t) = { (a, P, o, h_I, x, trail-evaluation, t) : o ∈ objects(I), x ∈ {recall, read} }
                              ∪ { (a, P, o, h_I, route, trail-evaluation, t) : o ∈ R(I) }

R(I) is the set of roads and trails of S that can be derived from I: from its episodes' session ids and its log rows
(trail spec section 4). Every memory one of them names is in objects(I), since a wrote touch is a shipped episode and a
cited touch a target of a kept row.

The first is the permissions spec's `need` of an `imprint` use on each object kept, including, on a road or trail,
`recall` on every memory it names (its 6.4). R(I) is empty unless the terms include `route`, since only then do session
ids or log rows ship (D7), and Need(admission)'s third set is there only with `route`. With `route`, admission also
counts R(I), and keeps only the count (section 10). Deriving the roads and trails reads memory text to find cited
touches (trail spec section 4), so that third set is `recall` and `read` on the memories for `trail-evaluation`, as in
Need(trail-evaluation). It holds the `recall` on every memory a road or trail names, which revision 5 listed alone.
r_M and the ceiling already allow it, so no permission widens, and only the count leaves the run (the cross-check's
XS2; Rio Grande's call). Revision 2 named only "a trail of S whose log rows I holds" here, and missed the trails
that session ids alone make (the re-check's RMF1). Admission performs no use outside Need(admission). Verification
reads the session ids and log rows only to check what is kept (checks 10–13), as part of that `imprint` use.
Calibration reads the memories for `calibration`. It derives no road or trail, since admission runs it without its
paths analysis.
Its survey counts each table's rows and the episodes' distinct session ids. It reads no log row's content and groups
no episodes by session (section 10). Revision 3's calibration ran the paths analysis, a `read` on R(I) for
`calibration` that no record allows (the final check's FS1). The second is `need` of a `route` use, plus `read`,
because `trails.py` reads memory content to find cited touches (trail spec section 4), and to embed measure W's texts
and find their anchors (trail spec section 7, step 8). The text goes only to the embedder, in the run's process or the
Pi's shared embedder service, which answers with vectors and keeps nothing (`embedder_service.py:105-122`; it logs
only connection events, `:84`, `:134`, and its socket is the user's own, `:99`). Only counts and rates leave the run.
Then

    allowed(k, t)  ⇔  status(I) ∈ Status(k)  ∧  Need(k, t) ⊆ ⟦p_I⟧ ∩ ⟦c_I⟧

with Status(admission) = {`approved`} and Status(trail-evaluation) = {`admitted`}. Admission is decided by this rule
at approval and again at the start of every admission run, and checks its end and withdrawal before each write
(section 10, D39).

**Bulk uses** (the permissions spec's 6.4, P33; the re-check's RN6). Each use kind here shows nothing to any agent, and
only counts, rates and digests leave the run. So each is decided as that spec's bulk uses. Need(admission) is named
bulk `imprint` uses on the memories, in batches of at most 512 refs, and, with `route`, named bulk `read` uses on the
memories for `trail-evaluation`, in batches of 512, and one counted bulk `imprint` use on R(I).
Need(trail-evaluation) is named bulk `read` uses on the memories, in batches of 512, and one counted bulk `route` use
on R(I). That spec's bound of 32 named memories applies to answer uses, not to bulk uses, so a trail of up to 512
touches (trail spec section 4) is no `BOUND` refusal here. Its other bounds still apply: at most 100,000 derived
objects in one counted bulk use (a larger R(I) is split into several, each with its own receipt row, and admission's
count of R(I) fixes the split, section 10), at most 100,000
memories named by one bulk use's roads and trails (its revision 5; every memory a road or trail of R(I) names is in
objects(I), which holds at most 100,000, D36, so this bound never splits a use here), at most 8
subjects per road or trail (here there is one, the owner, since no memory with a co-subject ships), and 43 layers per
object. A use that showed an object to an agent would be an ordinary use, decided per object under the bound of 32.
Step 1 has none.

**A finite check.** Every o ∈ objects(I) matches r_M's object dimensions: its store is S (D11, bound by check 8), r_M
names `"*"` layers and lanes, and o is in the collection by definition. Every road or trail in R(I) matches r_T's
objects. So whether a use in Need(k, t) is in ⟦p_I⟧ ∩ ⟦c_I⟧ depends on o only through its kind. The check is at most
nine tests of an (action, purpose) pair against one record, C and I's dates and receipts, whatever the imprint's size.
This is the permissions spec's shortcut for bulk uses: objects that agree on every attribute the records read get the
same decision (its 6.4, "How it is computed"). So a batch's decision is computed once, and the owner's use list gets
one row per batch (section 12).

A refusal names the first failing term, in this order: status, `valid_from`, the effective end, withdrawal, audience,
requester, action, purpose, ceiling. For the owner's use list these map to the permissions spec's codes (its 6.5):
`NOT_YET`, `EXPIRED`, and `NO_ALLOW` for the rest.

**The order.** Permissions compare by what they allow, as in the permissions spec's 6.2: p′ ≤ p iff ⟦p′⟧ ⊆ ⟦p⟧.
(𝒫(𝒰), ⊆) is a complete Boolean lattice, with meet = intersection. A decision uses ⟦p_I⟧ ∩ ⟦c_I⟧, the meet of the
owner's layer and the station's for copy I. After the yes, step 1 allows only narrowings. The owner's shortening gives
⟦p′⟧ ⊆ ⟦p⟧, since every record's validity shrinks, and the owner's withdrawal gives ⟦p′⟧ = ∅. The ship's shortening and
withdrawal shrink ⟦c_I⟧ the same way, since a receipt only ever removes uses from items 4 and 5. None can widen (the
permissions spec's L1 and L3). Revision 1's
order, with one purpose that had to be equal, is gone: two purposes had no meet there.

## 9. Transport over the tailnet

The station is `https://smart.tail7db420.ts.net`. Port 443 is tailnet-only (DS9 spec, line 84), and shared users
reach only `smart:443` (DS9 spec, lines 106-108). The public door serves only its two access-request routes (DS9
spec, lines 80-86). Imprint routes must answer 404 there.

The agent authenticates with the ship key in `~/.superyak/station.json` (DS9 spec, lines 117-119) and sends the
station's `Origin`, as ship clients do (DS9 spec, lines 57-58).

| Method and path | Who | Does |
|---|---|---|
| POST `/api/imprints` | ship key | `{request}` → `{id, code, confirm_url, expires}`. Checks in section 14. Writes `request.json` in staging. Status `requested`. |
| GET `/api/imprints/code/{code}` | the signed-in person who owns that ship | the confirm view's data; anyone else gets 404 |
| POST `/api/imprints/{id}/confirm` | that person, CSRF, password, the ticked check | signs the permission; status `allowed` |
| POST `/api/imprints/{id}/decline` | that person, CSRF | deletes the staging directory; status `declined` |
| PUT `/api/imprints/{id}/manifest` | the requesting ship | once, only in `allowed`; refused unless it agrees with the request (7.2) |
| PUT `/api/imprints/{id}/parts/{n}` | the requesting ship | one part, raw bytes. Accepted only in `allowed` after the manifest, only if its length is right and its SHA-256 equals `manifest.package.parts[n]`. Written to `part-n.tmp`, fsynced, renamed. A part already held with the same hash returns 200 and changes nothing. |
| POST `/api/imprints/{id}/complete` | the requesting ship | joins the parts in order into `imprint.db`, streaming, and checks bytes and SHA-256. Deletes the parts. Status `received`. |
| GET `/api/imprints` and `/api/imprints/{id}` | the owner, or the requesting ship | status, held part numbers, permission with `{record, signature, station_key}`, receipts with their signatures or "not yet signed" (section 12) |
| POST `/api/imprints/{id}/withdraw` | the owner (CSRF) or the requesting ship | section 12 |
| POST `/api/imprints/{id}/shorten` | the owner (CSRF) or the requesting ship | `{valid_until}`; section 12 |

Bounds for a Pi:

- The peer buffers each request body whole, up to 6 MiB (`app.py:19`, `:44-51`). A 4 MiB part fits, and the agent
  sends parts one at a time.
- Requests, manifests and parts are files under `$(STATION_DATA)/imprints/<request id>/` (0700), never rows in
  `peer.sqlite3`.
- Hashing reads 1 MiB at a time, as `store_reader.sha256_file` does (`store_reader.py:58-63`).

**Resuming.** The agent keeps `~/.superyak/imprints/<imprint id>/send.json` with the station and request id.
Rerunning `make imprint-send` reads the held part numbers and sends only the missing ones. Parts survive a station
restart.

**The confirm view** (`/#imprint?code=`, like docking's `/#dock?code=`) shows exactly the request's fields, in words,
plus what the station knows itself:

- the ship and machine (from the ship's docking);
- the imprint's short id (`c0a8`) and the request's short id (`4f1c`), which `make imprint-send` printed on the owner's
  machine;
- the store id, and the stores it was copied from by their short ids, with "lineage complete" or "lineage incomplete"
  (`source_ancestry`; the re-check's RN4), or "copied from no recorded store";
- the scope, the counts and the size;
- the audience in words ("the station's imprint agent, acting for andy");
- the closed actions ("recall, read and imprint on these memories; for the trail evaluation, keeping which session
  wrote each memory and the recall log, which make your trails, and route over their roads and trails") and the
  purposes. Without `route`: "which session wrote each memory, and the recall log, stay on your machine";
- what leaves with the memories, with or without `route` (5.4; the cross-check's XS3): "Each memory keeps when it
  was written. Each episode keeps how often and when last it was recalled. Resonances, pairs of memories one recall
  returned together, keep when. These show when memories were recalled together.";
- the end date if confirmed now;
- the plan digest's first 8 characters, with "the whole 64-character digest is sent";
- the owner's check about other people (section 8);
- what the station keeps (D32): "If you allow, the station keeps this permission, its receipts and a row with the ids,
  your ship and the times (no memory content) until 400 days after the copy is deleted, then removes them all. Its
  nightly backups keep copies of them for about 8 weeks more, longer if the Pi was off, and also off the Pi if an
  off-Pi copy is set up. If you decline, it keeps only that row, with no scope or counts, for 30 days. Nothing is kept
  with no end.";
- "This store is about you. Allow sends this copy to Deep Space 9. Andy then decides whether the station takes it.
  You can withdraw it at any time, and it is deleted on the end date."

**Lifecycle.**

| Status | On the station | Next |
|---|---|---|
| `requested` | `request.json` in staging; no package bytes | `allowed`, `declined`, or `expired` after 10 minutes |
| `allowed` | manifest and parts in staging | `received`, `deleting` (withdrawn, or 7 days without completing) |
| `received` | staged `imprint.db` | `approved`, `deleting` (denied, withdrawn, or 7 days without review) |
| `approved` | the imprint and state directories; admission running | `admitted`, `deleting` (failed, withdrawn) |
| `admitted` | read-only imprint | `deleting` (withdrawn, ended, deleted by the station) |
| `deleting` | being removed | `deleted`; the sweep retries a failed removal |
| `deleted` | no files but the tombstone; the row, the permission and the receipts, for 400 days, then nothing | terminal; the reason is in the last receipt |
| `declined`, `expired` | no files; a content-free row, for 30 days, then nothing | terminal; no permission, so no receipt (goal 6) |

**Where an imprint's data lives, and for how long** (D15, D32).

| What | Where | In backups | Removed |
|---|---|---|---|
| The request (scope, counts, terms, ancestry) | staging `request.json` | never | at decline; by the sweep within an hour of expiry; with the staging directory |
| Manifest, parts, staged `imprint.db` | staging | never | at hand-off (moved), denial, withdrawal, or the window's end |
| `imprint.db`, manifest, permission, registration | `~/.engram/imprints/<imprint id>/` | never | at withdrawal, the end date, a station delete, or a failed admission |
| Calibration report, uses and their reports | `~/.engram/imprints/<imprint id>.state/` | never | with the imprint |
| The request row: ids, ship, owner, status, times, `request_sha256` | `peer.sqlite3` | yes | 30 days after a decline or an expiry; otherwise with the permission, 400 days after `deleted` (D32). It holds no scope and no counts |
| The permission and its signature; the receipts | `peer.sqlite3` | yes | 400 days after `deleted` (D32) |
| Tombstones | `~/.engram/imprints/tombstones/` | never | 400 days after `deleted`, with the row (D32). They hold only the `withdrawn` and `deleted` receipts: ids, times, and each removed file's path, bytes and SHA-256 |

Nothing about an imprint or a request has no end (D32; Rio Grande's call, from the re-check's RS5). Revision 2 kept the
request row, a content-free row per deleted imprint, and the tombstones for good, and told the owner only of the 400
days. A tombstone keeps a restore from bringing a withdrawn imprint back (section 12). A backup from 400 days ago stays
in the rotation only if fewer than 8 of the ISO weeks since, or fewer than 14 of the days since, had a backup
(`backups.py:30`, `:109-119`: "a Pi that was off never ages out its last copies"). A row restored from it whose files
are gone becomes `deleted` or `expired` anyway, and one past its end is removed again (section 12, the sweep).

Backups copy only `peer.sqlite3` (`backups.py:167-176`). They keep the newest copy of each of the 14 most recent days
and the 8 most recent ISO weeks that have a copy (`backups.py:30`, `:109-119`). So a row erased today stays in the
rotation for about 8 weeks, and longer if the Pi was off on some of those days. An off-Pi copy (`--copy-to`, from
`~/.config/superyak/backup.env`; `peer/systemd/superyak-backup.service:10`) is pruned by the same rule there
(`backups.py:294-319`). On 2026-10-25 the Pi had no `backup.env`, so no off-Pi copy was being made. `make
imprint-status` shows the same retention as the confirm view.

## 10. On the Pi: approval, verification, calibration, registration

**Approval.** A `received` imprint appears in `make station-pending` (`ships.py:191-199`) beside dockings and access
requests, read from its `request.json`:

```
4f1c  IMPRINT  from sam (ship voyager, machine sam-laptop): store 3f2a9c1e, 1,204 episodes and 88 semantics,
      work lane, since 2026-01-01; 41.2 MiB; for place:home/andy; recall, read, imprint, route;
      purposes calibration, trail-evaluation; ends 2027-01-23
```

- Requester text goes through `safe_line` (`ships.py:33`), as for other items.
- Odo's notices (`ships.py:380-393`) gain one line: "An imprint is waiting for Andy's review. He decides with make
  station-pending on the Pi." Ops is shared, and that someone is sharing their memories is about them (D25).
- Andy approves with `make station-approve ID=4f1c` or refuses with `make station-deny ID=4f1c`, after confirming
  that the short id matches what the owner's machine showed (A2; `station_decide`, `ships.py:279-302`).
- A denial deletes the staged bytes and writes `denied` and `deleted` receipts.
- `station-approve` refuses an imprint whose audience is not `place:home/<APPROVER>`: no use could be allowed.

**Hand-off.** `station-approve` (peer, `Store(signing=False)`, `__main__.py:322-327`) for an imprint item:

1. In one transaction: status `received` → `approved`, and the unsigned `approved` receipt (section 12).
2. Create `<root>/<imprint id>/` and `<root>/<imprint id>.state/` (both 0700, exclusive create), where `<root>` is the
   imprints root, `~/.engram/imprints` by default (below). It refuses if either exists or a tombstone for that id
   exists. It records the absolute root in the request row.
3. Move `imprint.db` and `manifest.json` from staging, and write `permission.json` (`{record, signature,
   station_key}`; the lighthouse signed it at the yes) and `approved.json`. Remove the staging directory.
4. The Makefile then starts admission as a detached user unit and returns at once (D29):

       systemd-run --user --unit=superyak-imprint-admit-<imprint id> --collect \
           -p MemoryMax=4G -p MemorySwapMax=0 -p RuntimeMaxSec=1800 \
           make -C <repository> station-imprint-admit ID=<imprint id>

   The unit is named by the full imprint id, so two imprints whose short ids match never share a unit (the re-check's
   RN9). It prints "Approved 4f1c. Admitting in the background; see make station-imprints." Claude's Bash tool stops
   at 10 minutes, and calibration can take 30. `make station-imprint-admit` with no ID starts one unit for each
   approved imprint without a result, after a crash. Approving a docking never touches the engram environment.

**The imprints root** (the re-check's RN10). It is one setting, the flag `--imprints-dir DIR`, with default
`$HOME/.engram/imprints`. It is taken by `superyak-peer serve` (the lighthouse, which runs withdrawal), by every
station command that touches imprints (`station-approve`, `station-deny`, `station-imprints`, `station-imprint-sync`,
`-sweep`, `-delete`, `-use-begin`, `-admit-begin`), and by engram's `imprint.py admit`, `use` and `list`. The Makefile
passes `IMPRINTS ?= $(HOME)/.engram/imprints` to the commands it runs. The sweep's unit passes `--imprints-dir
%h/.engram/imprints`. The lighthouse's installed unit (`~/.config/systemd/user/superyak-lighthouse.service`) passes
the same flag; today its `ExecStart` passes only `--data-dir`, `--host`, `--port`, `--proxy-headers`, `--origin` and
`--share-link-file`. No environment variable sets the root, so every command line says where it is. Every later
removal (withdrawal, the sweep, a station delete) removes the directories under the root recorded in the request row,
whatever its own flag says, and a process whose flag differs logs the mismatch. A deploy gate checks that the
lighthouse and the Makefile name one root (section 18).

`station-imprint-admit ID=…` runs the peer's `station-imprint-admit-begin --id …`, then engram's `imprint.py admit --id
…`, then the peer's `station-imprint-sync`, which records the result whatever admission's exit status. Each step is
idempotent.

**Admission is decided again** (D39; Rio Grande's call, from the re-check's RS3). `station-approve` decides admission
once, in the transaction that sets `approved`. A run may start much later: after a crash, `make station-imprint-admit`
resumes, maybe days on. So every run, the first included, begins with `station-imprint-admit-begin`, which reruns
section 8's whole check at its own time t: status `approved`, `valid_from`, the effective end with every shortening
by the owner or the ship, withdrawal, audience, requester, action, purpose and ceiling. If it allows, it writes
`<imprint id>.state/admission.json` (0400):

    {"kind": "imprint-admission-allow", "instance_id": "c0a8f5e2-…", "decided_at": 1792956660,
     "valid_until": 1800727950}

with `valid_until` the effective end. A shortening replaces this file atomically, as it replaces a use's allow files
(section 12). If refused, it writes a `failed` receipt naming the failing term and writes no file. The sync then
deletes the imprint as a failed admission, with reason `ended` when the term is the end. So an end takes effect at the
next decision at or after it, never at the next sweep: the permissions spec's "Time needs no act" (its section 10).

**Deletion and the end win** (D17, D39). Withdrawal runs in the lighthouse, and admission runs in its own unit. So:

- Admission never creates `<imprint id>/` or `<imprint id>.state/`. Before each write, and before calibration starts,
  it checks that no tombstone exists, that `<imprint id>/approved.json` is present, and that
  `<imprint id>.state/admission.json` is present with `valid_until` later than now. If not, it stops without writing
  ("withdrawn during admission", or "ended during admission"), and its exit status says which. The other terms of the
  check are fixed by signed records and code, so these are the only ones that can change during a run. On "ended",
  the sync writes the `failed` receipt (term: the effective end) and deletes the imprint with reason `ended`.
- Calibration writes into `<imprint id>.state/calibration/`. `calibrate` gains `create_parents` (default true, today's
  behaviour at `calibrate.py:251`). Admission passes false, so a removed state directory is never recreated.
- `station-imprint-sync` moves only `approved` rows. It never moves `deleting` or `deleted` to `admitted`.
- A write that lands after a removal is a leftover. The sweep removes any directory with no live row (section 12).

**Verification.** All 17 checks must pass. `imprint.db` is opened `mode=ro&immutable=1` with sqlite-vec loaded:
`store_reader.connect(path, immutable=True, vec=True)`. The new `vec` flag loads `sqlite_vec` the way
`Storage.open_read_only` does (`storage.py:153-156`). Checks 9, 10, 13 and 17 need it.

1. `<imprint id>/` holds exactly `imprint.db`, `manifest.json`, `permission.json` and `approved.json`, and none is a
   symlink.
2. Bytes and SHA-256 of `imprint.db` equal `manifest.package`.
3. `verify_station_record` (section 15) passes for the permission. Its `request_sha256` and `plan_digest` equal the
   manifest's, the two `imprint_id`s and source ids match, and the manifest agrees with the request (7.2).
4. The file starts with `SQLite format 3\0`, and header bytes 18 and 19 are both 1, so it is not WAL.
5. `PRAGMA integrity_check` returns `ok`.
6. `schema_version` equals `manifest.schema.applied`, with nothing unknown to this engram (`store_reader.py:100`).
7. `sqlite_master` (type, name, table, SQL; not rootpage) equals that of a reference file that `Storage` builds
   from an empty file with exactly those migrations (`Storage(path, migrations_dir=…)`, `storage.py:84-118`), and every
   vec0 `_info` table equals the reference's. No extra table, trigger, view or index can ride along. If the engram
   code or sqlite-vec on the two machines differ, the error says to put both on one commit.
8. `meta` holds exactly the identity keys of section 11, with `instance_id` = `manifest.imprint_id`,
   `forked_from_instance_id` = `manifest.source.instance_id`, and the ancestry that `stamp_imprint` derives from
   `manifest.source`.
9. Every table dropped in 6.2 is empty. `sqlite_sequence` is rebuilt, not dropped, and is not checked here.
10. `PRAGMA foreign_key_check` returns nothing. Every non-foreign-key reference in 6.2 resolves inside the package:
    links, peers, subdivision events, and log rows' `target_ids`. Every vector row's id is a row of its base table.
11. Scrubs hold. Every `memory_log` row is a `recall` or `route_shown`. A recall has a non-empty target list with no id
    outside the package's memories, `context` keys within {`recall_id`, `session_id`}, and an outcome of null, `used`,
    `not_used` or `used: auto: cited`. A `route_shown` row's targets are not empty and are in the package, its `context` keys within
    {`receipt_id`, `session_id`, `tool`, `lane`}, its lane in `scope.lanes`, and its outcome null. Every `operation_log` row
    has its operation in `CITING_OPERATIONS`, null `harness`, `model` and `repo`, and `{}` details.
12. Scope holds. Every memory's lane and `created_at`, and every log row's and resonance's time, are within the
    scope. Tables of layers not chosen are empty, and the instinct tables are empty. Without `route` in the terms,
    `memory_log` and `operation_log` are empty, and every `episodes.session_id` is null (D7). With `route`, the Pi
    can't check which sessions were closed at t₁, since it never sees the rows that stayed home. The plan digest binds
    each episode's session id as kept (5.4), and check 13 recomputes it.
13. Counts equal `manifest.contents`, and recomputing the plan digest from the package's rows (5.4) equals
    `manifest.plan_digest` (D22).
14. `PRAGMA freelist_count` is 0.
15. Each memory table's rowids are exactly 1..n, and so are each FTS table's `_docsize` ids (D33).
16. FTS index equality, L2 (6.4).
17. vec0 slots, L3 (6.4).

The Pi cannot check `shared_with`, the owner's exclusions or the cross-reference scan. It never sees what stayed home.
Those rest on the source build, its L1 and L4, and its tests.

**Calibration** (D31).

- Admission runs `calibrate.calibrate(<imprint id>/imprint.db, <imprint id>.state/calibration, migrate=True,
  no_content=True, no_paths=True, notes=…, max_lane_episodes=7500, create_parents=False)`, inside the unit's limits.
- `no_content` removes every `content` key at any depth before the report is written. Today the cohesion and
  persistence sections carry content excerpts (`calibrate.py:172`; `persistence.py:392`, `:415`).
- `max_lane_episodes` bounds every dense set calibration builds. A set over the bound is skipped and the skip is
  recorded. It is never sampled. The sets are: each lane's episodes with vectors (`calibrate.py:146-160`); the core set
  in `flag_redundant_cores` (`persistence.py:399-409`, called at `calibrate.py:211`), which has no lane bound today;
  and each semantic's sources in `classify_hubs` (`persistence.py:342-384`).
- **Why 7,500.** `build_filtration` holds `D`, the diagonal and `off` at once (`persistence.py:63-64`), and
  `_mst_edges` adds `floored` and a dense-to-sparse copy (`persistence.py:41-46`). Measured peak resident memory, as a
  ratio to n² × 8 bytes: 7.16, 7.54 and 7.50 at n = 1,500, 3,000 and 5,000 (the review's run), and 7.48 at 2,000 and
  4,000 (this revision's run, numpy and scipy on the Pi). So n_max = ⌊√((MemoryMax − 512 MiB) / (7.5 × 8 B))⌋, which
  is 7,914 at MemoryMax = 4 GiB. Step 1 uses 7,500. Revision 1's 12,000 would have peaked near 8.6 GB and been killed.
- The report must show `source_unchanged` true and no side files created (`calibrate.py:302-305`). The snapshot
  uses `immutable` when there is no WAL (`calibrate.py:61`), so the read-only directory stays clean.
- **No paths at admission** (the final check's FS1, option (a); Rio Grande's call). `calibrate` gains `no_paths`
  (default false, today's behaviour at `calibrate.py:295-296`). With it, the paths analysis doesn't run, and the
  report's `paths` section holds only the sentence "not measured at admission; trails are used only by the trail
  evaluation". Admission always passes it, with or without `route`. `paths.report` turns each session into a path,
  and its report names each session with its shape (`"session": p.key`, `paths.py:446-449`) and the pairs of sessions
  that took different routes (`"a"`, `"b"`, `:328-330`). That is a `read` of the owner's trails, which r_T allows only
  for `trail-evaluation` (section 8). The trail spec reads nothing from calibration's `paths` section (its section 7
  only notes what calibration costs), so it loses nothing. The dry run's and the confirm view's words, "for the trail
  evaluation, keeping which session wrote each memory", stay exact.
- **The survey's counts.** The survey (`calibrate.py:258`) counts every table's rows (`store_reader.py:111-121`) and
  the episodes' distinct session ids (`:126-131`), and report.md prints the second as "… N sessions"
  (`calibrate.py:328-331`). A count returns no id, digest or content, so it is no `recall` or `read` of a road or
  trail in the permissions spec's terms (its 6.4). It groups no episodes by session and orders none, so it derives no
  road or trail. The log tables' row counts are also already in the request's `contents`, which the owner saw before
  the yes (7.1). So these counts are read for `calibration` under r_M (the check of revision 4, CN3). Without
  `route`, every `episodes.session_id` is null and the log tables are empty, so the survey counts 0 sessions and 0
  log rows. `calibrate` gains `notes`: fixed sentences that it writes beside named
  sections of report.json and report.md, before either is hashed. Without `route`, admission passes "0 sessions and
  0 log rows, because route was not chosen" for the survey's session count and the log tables' row counts, so the
  zeros are not read as a store with no sessions (the final check's FS2).
- After calibration, `snapshot.db` and `working.db` are deleted. `report.json` and `report.md` stay.
- One analysis that errors is reported, not fatal (`calibrate.py:236-241`). A calibration that fails as a whole
  (exception, memory limit, timeout, source changed) fails admission, because the trail spec needs this evidence.

**Counting R(I)** (the cross-check's XS2; Rio Grande's call). The station's receipts name objects only as counts
(section 12), and the owner's import splits the roads and trails at 100,000 per bulk use (section 8). So with `route`,
once the checks pass, `imprint.py admit` derives R(I) in memory with the trail spec's own functions (its `trails.py`;
sections 4 and 5 there), at `as_of` = t₁, the scope's `until`. Every session the package holds is closed then (5.2),
and no kept row is ignored, since every one is before t₁. It keeps only N, the number of roads and trails, and nothing
else of what it derived. Without `route`, N is 0. This is part of admission's `imprint` use on R(I), and reads the
memories for `trail-evaluation` (section 8, Need(admission)'s third set). N is a number: it names no id, digest or
content, and the owner's yes already covers keeping these roads and trails.

**Registration.**

1. Write `<imprint id>/imprint.json`: status, manifest, permission, admission time, the report's SHA-256, and the
   engram commit.
2. Set the files in `<imprint id>/` to 0444 and the directory to 0555. The state directory stays 0700.
3. Write `<imprint id>.state/result.json`: `{"status": "admitted", "roads_and_trails": N, …}`. The sync copies N into
   the `admitted` receipt (section 12).

Any failure writes `<imprint id>.state/result.json` with `failed`, the check's number and a fixed message. The sync
then deletes the package and writes `failed` and `deleted` receipts. The directory is the registration. An imprint is
never added to `instances.json` (`federation.py:127-142`).

What `make station-imprints` shows Andy after admission:

```
c0a8  sam  admitted 2026-10-25 19:41 UTC   17 of 17 checks; calibrated (88 semantics measured; 57 sessions
      counted; paths not measured at admission)
      read-only at ~/.engram/imprints/c0a8f5e2-…/   ends 2027-01-23   receipts signed
```

The 57 sessions are the survey's count, there because this example chose `route`. Without it, the line says "0
sessions (route not chosen)". Admission never measures session paths, with or without `route` (FS1).

## 11. Identity, lineage, never merged

**Identity.** `store_identity.stamp_imprint(conn, source_instance_id, source_ancestry, source_complete, imprint_id)`
deletes the identity keys and writes:

- `instance_id` = `imprint_id`;
- `instance_id_origin` = `imprint` (new constant `ORIGIN_IMPRINT`);
- `instance_id_basis` = `random`;
- `forked_from_instance_id` = the source's effective id;
- `ancestry` and `ancestry_complete`, as below.

It mirrors `stamp_fork` (`store_identity.py:143-160`) and does not commit. Memory ids are kept, as a fork keeps them
(`cli.py:38-49`), so receipts, withdrawal, the owner's refs and the trails name the same memories on both machines
(D11). `ancestry` and `ancestry_complete` join `store_identity.KEYS` (`store_identity.py:43-49`), so a fork or an
imprint replaces them with the rest.

**Ancestry** (D13). For a store X:

- `meta.ancestry` is a canonical JSON list of distinct lowercase instance ids, nearest ancestor first, at most 64.
  `meta.ancestry_complete` is `true` or `false`.
- `stamp_fork` and `stamp_imprint` write the child's ancestry as `[parent id] + ancestry(parent)`, cut to 64 entries.
  The child is complete when the parent is complete, the parent's id is not null, and nothing was cut.
- A store with neither key and no `forked_from_instance_id`, of origin `creation`, is a root: ancestry [], complete.
  Store identity gave it a random id when this open created it (`storage.py:246-254`), so a copy made since is either
  a fork, which records its parent, or a file copy, which keeps the same id.
- A store with neither key and no `forked_from_instance_id`, of origin `retroactive` or with no stored identity yet,
  is older than store identity (migration 028, 2026-09-29): ancestry [], **incomplete** (D13; Rio Grande's call, from
  the re-check's RS4). Before identity, `cli.py fork` copied a store whole with SQLite's backup (`cli.py:15-49`, the
  copy at `:42`) and recorded nothing in the copy. Such copies exist: `instances.json` records their `forked_from`
  (`federation.py:127-142`). A retroactive id comes from the earliest episode (`store_identity.py:84-102`), and
  pruning deletes episodes (`storage.py:734-747`, `:760`). So if the parent or its old copy pruned that episode before
  migrating, the two got different ids, and nothing in either says that one is a copy of the other. Calling them
  complete would make `independent` true for a store and its own copy.
- A store with `forked_from_instance_id` and no `ancestry` was forked before this rule. Its ancestry is
  `[forked_from_instance_id]`, incomplete. Nothing recorded its grandparents.
- A fork of a store with no identity (`forked_from_instance_id` null, which `stamp_fork` allows for an empty old
  store, `store_identity.py:146-147`) has ancestry [], incomplete.
- `cli.py fork` reads the parent's ancestry read-only and passes it to `stamp_fork`.

**Lineage.** Lin(X) = {X's `instance_id`} ∪ ancestry(X). Then

    independent(X, Y) = false     if Lin(X) ∩ Lin(Y) ≠ ∅
                        true      if Lin(X) ∩ Lin(Y) = ∅ and both X and Y are complete
                        unknown   otherwise

Only `true` counts as independent. `unknown` never does.

The review's cases, with G a genome, Y = fork(G), X = fork(Y), Z = fork(G) and I an imprint of X:

| Pair | Lineages | `independent` |
|---|---|---|
| X and G | {X, Y, G}, {G} | false: X holds a full copy of G |
| X and Z (cousins) | {X, Y, G}, {Z, G} | false |
| Y and Z (siblings) | {Y, G}, {Z, G} | false |
| I and G | {I, X, Y, G}, {G} | false |
| an old fork W of F, made before this rule, and an unrelated G | {W, F}, {G} | unknown |
| a store R older than identity, and a copy R′ the old `fork` made of it, whose earliest episode was pruned before either migrated | {R}, {R′} (two derived ids) | unknown: both incomplete |
| an imprint I of R | {I, R}, {R′} | unknown: I's ancestry inherits R's incompleteness |
| two unrelated stores made after identity (origin `creation`) | {A}, {B} | true |

- **Siblings forked from one genome are never independent.** That is conservative. `cli.py fork` forks from the
  genome by default (`cli.py:15`), so a person's instances are siblings. The rail spec should know this.
- A plain file copy keeps the same id, so it is never independent either.
- An imprint is read-only and has no sessions after its creation, so it adds no support the trail spec could count
  after a fork (trail spec section 8, "Forks and imprints are not independent").
- **Row-level provenance.** Genome-synced episodes carry `origin_instance_id`, `origin_id` and `origin_created_at`
  (`federation.py:182-186`; `028_store_identity.sql:10-12`). Two stores whose lineages don't meet can still hold copies
  of one genome's episodes. The rail spec must also read `origin_instance_id`: an episode whose origin is in the other
  store's lineage is a copy, not agreement. The columns exist only since migration 028. A sync fills them in for an
  older synced episode only when the genome still holds an episode with the same content hash
  (`federation.py:187-193`). So an episode of type `genome_sync` with a null `origin_instance_id` is a copy of unknown
  origin, and never agreement either. This spec only names it.
- **Stores older than identity.** Every store of origin `retroactive`, or with no stored identity, is incomplete. So
  `independent` is `unknown` for every pair that holds one, and the pair never counts. That is the strict default. A later spec may
  give such a store a complete ancestry another way, for example its owner's signed word that it was never copied.
  This spec does neither. The rail spec should know that today's older stores count for nothing until then.
- The rail spec must count agreement only between stores whose `independent` is true. This stops accidental double
  counting. It cannot stop someone who rewrites identity by hand.

**Never merged, never opened normally.** A normal open migrates and runs vec0 repair (`storage.py:115-118`). A
server on an instance store also runs genome sync and inbox processing (`server.py:1443-1452`). Guards:

| Guard | Where |
|---|---|
| Imprints live only at `~/.engram/imprints/<id>/`, never under `instances/` or at `.engram/graph.db`, so `resolve_db_path` and the server never reach them (`config.py:400-404`, `server.py:1306-1311`) | `imprint.py` |
| Files 0444, the imprint directory 0555 | `imprint.py` |
| `Storage(path)` raises when `meta.instance_id_origin = imprint`, unless `imprint_working_copy=True`, which only calibrate's throwaway working copy passes (`calibrate.py:268`). It reads `meta` on its new connection right after connecting: before `_restore_pragmas()` sets WAL (`storage.py:108`, `:122`) and before migrations run (`storage.py:115`). A file in rollback-journal mode can be read without writing anything | `storage.py` |
| `share` refuses a source store whose origin is `imprint` | `sharing.py` |
| `sync_genome` refuses a genome whose origin is `imprint` (it reads the genome raw, `federation.py:168-172`) | `federation.py` |
| `fork` refuses a source whose origin is `imprint`; `stamp_fork` would otherwise erase the origin | `cli.py` |
| `lighthouse_sheaf.py` opens any `--store` path read-only (`lighthouse_sheaf.py:267-269`, `:408`) and checks no lineage. It refuses a store whose origin is `imprint`. For every pair of stores it covers, it reports `independent`, and marks any pair whose value is not `true` as "not independent evidence". It is observational today and a person's instances are siblings, so it flags such pairs rather than refusing them | `lighthouse_sheaf.py` |
| `trails.py` refuses an imprint without a matching allow file (trail spec R13) | `trails.py` |

Readers use `Storage.open_read_only` (`storage.py:128-161`) or `store_reader.connect`.

## 12. Uses, receipts, expiry, withdrawal, and what the owner sees

**Uses in step 1.** Each is decided by section 8's check.

| Use | Needs (section 8) | Status | Started by | Output |
|---|---|---|---|---|
| admission: verify, survey, calibrate, and with `route` count R(I) | `recall`, `read`, `imprint` on the memories, purpose `calibration`; with `route`, also `recall`, `read`, `imprint` on their roads and trails, and `recall` and `read` on the memories, purpose `trail-evaluation`, since counting the roads and trails reads memory text (section 8). Calibration runs without its paths analysis, so it reads no road or trail (section 10) | `approved` | `station-approve`, in a detached unit; decided again at each run's start (D39) | the content-free report in the state directory, shown to the owner |
| `trail-evaluation` | `recall`, `read` on the memories and `route` on their roads and trails, purpose `trail-evaluation` | `admitted` | `make station-imprint-use ID=… USE=trail-evaluation LANE=…`, in a detached unit | `trails.py <imprint dir>/imprint.db --evaluate --lane <LANE> --seed N --deadline 1740 --json --imprint-use <use id>`: counts and rates only (trail spec section 7, step 7). `LANE` is one lane of the scope, since a pass licenses one lane (trail spec section 7, step 9). The use always passes `--lane`: when `LANE` is left out and the scope holds one lane, `imprint.py use` fills in that lane; when the scope holds two, it refuses (D41) |

- Admission's decision is made by `station-approve`, in the transaction that sets `approved`, before the hand-off.
  A refusal there is a denial, and its receipt names the failing term. It is made again by
  `station-imprint-admit-begin` at the start of every admission run, and admission checks its end and withdrawal
  before each write (section 10, D39). A refusal then is a `failed` receipt naming the term.
- `station-imprint-use-begin` (peer) decides a use. If allowed, it writes the `use-started` receipt and the allow file
  `<imprint id>.state/uses/<use id>.allow.json` (0400):

  ```json
  {"kind": "imprint-use-allow", "use_id": "…", "instance_id": "c0a8f5e2-…", "use": "trail-evaluation",
   "actions": ["read", "recall", "route"], "purpose": "trail-evaluation",
   "requester": "agent:station-imprints", "acting_for": "person:andy", "place": "place:home/andy",
   "records": ["r-5b0d…", "r-91c2…"], "decided_at": 1792960000, "valid_until": 1800727950}
  ```

  `use_id` is a new lowercase uuid4 that `station-imprint-use-begin` makes, 36 characters, which fits the trail
  spec's `[A-Za-z0-9-]{1,64}` (its section 7, check 2; D41). `instance_id` is the imprint's. `valid_until` is the
  effective end. This holds what the trail spec's `--imprint-use` checks (its interface item I2). The allow file
  lives in the state directory, because the imprint directory is 0555 after admission. So `trails.py --imprint-use`
  must read it there, and must treat the tombstone `~/.engram/imprints/tombstones/<imprint id>.json` as withdrawal
  (revision 1's `withdrawn.json` was never written by anything). If refused, it writes a `refused` receipt and nothing
  else.
- A shortening replaces each live allow file of that imprint, `admission.json` included, atomically, with one holding
  the new `valid_until`. A withdrawal removes the whole state directory.
- Engram's `imprint.py use` refuses without the allow file, if a tombstone exists, or if `valid_until` has passed. It
  also refuses a use id that is not a lowercase uuid4, and a use whose directory `<imprint id>.state/uses/<use id>/`
  already exists. It creates that directory (0700) and never creates its parents, so a removed state directory is
  never recreated. It runs `trails.py`, always with `--lane` (D41). When the caller left `LANE` out, `imprint.py use`
  fills it in from the imprint's `manifest.json` (`scope.lanes`) when the scope holds one lane, and refuses when it
  holds two; the Makefile passes `LANE` through only when the caller gave it (the check of revision 4, CN4). It writes
  two files there, the names the trail spec's check 5 reads (D41; the trail spec's I2):
  - `report.json`: what `trails.py` printed, only when it exited with status 0;
  - `result.json`: `{"kind": "imprint-use-result", "use_id": "…", "exit": n, "error": null, "report": true or false,
    "ended_at": <integer UTC seconds>}`, where `exit` is the exit status of `trails.py`, or minus the signal that
    killed it.

  Once it has created the use directory, `imprint.py use` writes `result.json` in a `finally`, so its own errors
  write it too. An exception before or after `trails.py` runs, the two-lane refusal above included, gives
  `"exit": null` and `"error"` = the exception's class name, never its message, which could quote a path or text. A
  refusal before the directory exists writes nothing, and never into another use's directory. In the unit, the begin
  step has just made the use id and the allow file, so only a withdrawal, a deletion or an end reached in between
  leads there, and rules 2 to 4 below name those. A signal that stops `imprint.py use` itself writes nothing either,
  and nor does an error before it has made the directory, such as an import error at start-up or an allow file it
  can't read. So a missing `result.json` means only that the unit was stopped, that `imprint.py use` failed that
  early, or one of those three (the check of revision 4, CS2; the cross-check's XN1). It writes `report.json` first,
  atomically (a temporary file in the same directory, then a rename), and `result.json` after, the same way. The
  sync starts on `result.json`, and the sweep's sync can run beside the unit, so in the other order a sync between
  the two writes would record an exit of 0 as `failed` (CN6).
- **Finishing a use** (D41; the trail spec's I2; Rio Grande's call). `station-imprint-sync` finishes every use that has
  a `use-started` receipt and no `use-finished`, once one of these holds: `result.json` exists; the imprint is
  `deleted`; or 1,860 s have passed since `use-started`. The use's unit writes `use-started` itself. Its
  `RuntimeMaxSec=1800` counts from the unit's start, which comes before `use-started`. At that limit systemd sends
  SIGTERM, and SIGKILL after the unit's `TimeoutStopSec=60` (systemd.service(5); the user manager's default is 90 s).
  So 1,860 s after `use-started` the run is over. A stopped unit runs no sync of its own, so its use is finished by
  the first sync after that, which the hourly sweep runs, up to an hour later (the check of revision 4, CN1). The
  sync finishes no use of an imprint in `deleting`: the withdrawal is still removing files, and the next sync
  finishes it. To finish a use, the sync first
  deletes its allow file `<imprint id>.state/uses/<use id>.allow.json` (a missing file is no error), and then appends
  `use-finished`, checking inside the receipt's transaction that none exists yet, so two syncs write it once. So a
  finished use has no allow file, and rerunning its command from shell history is refused by the trail spec's checks 2
  and 5. `use-finished` records the run's end as the first of these that holds, at t_end, the time in `result.json`'s
  `ended_at`, or else the earlier of now and 1,860 s after `use-started`:
  1. `report.json` exists: the end is `report`, with its SHA-256;
  2. the tombstone `<root>/tombstones/<imprint id>.json` exists and a `withdrawn` receipt of the imprint is at or
     before t_end: `withdrawn`. So `withdrawn` is recorded only when the tombstone exists;
  3. the effective end is at or before t_end: `ended`;
  4. the tombstone exists and a `deleted` receipt of the imprint is at or before t_end, as when the station deletes
     the copy (reason `station`): `deleted`, with that receipt's reason. A deletion is not a withdrawal, and the trail
     spec's list doesn't name this case;
  5. `trails.py` exited with status 3: `allow changed`, for example after a shortening whose new end is still ahead;
  6. `trails.py` was killed by a signal, or no `result.json` was written, so the unit was stopped: `not evaluable:
     limit`, since a run the memory cap or the 30-minute limit killed writes no report (trail spec section 7, step
     10). A stop from outside the run, such as `systemctl --user stop`, reads the same, since the station can't tell
     it from a cap, and so does an error in `imprint.py use` before it made the use directory, which writes no
     `result.json` either (XN1);
  7. otherwise: `failed`, with the exit status, or with the error class when `exit` is null. That covers a
     `trails.py` exit other than 0 and 3, and an error in `imprint.py use` itself (D41; CS2).

  A shortening during a run is therefore recorded as `allow changed` or `ended`, never as a withdrawal. Revision 3
  recorded only "withdrawn" or "not evaluable", and nothing retired an allow file, so an old use id passed every check
  until the end date and left no `use-started` receipt.
- **The use's unit** (D29; the trail spec's I3; Rio Grande's call). `make station-imprint-use` starts it and returns at
  once. The unit runs `station-imprint-use-begin`, then `imprint.py use`, then `station-imprint-sync`, as admission's
  does (section 10), with calibration's limits:

      systemd-run --user --unit=superyak-imprint-use-<imprint id> --collect \
          -p MemoryMax=4G -p MemorySwapMax=0 -p RuntimeMaxSec=1800 -p TimeoutStopSec=60 \
          [--setenv=ENGRAM_EMBEDDER_SOCKET=<path>] \
          make -C <repository> station-imprint-use-run ID=<imprint id> USE=trail-evaluation [LANE=<lane>]

  `LANE=<lane>` is there only when the caller gave it; otherwise `imprint.py use` fills it in (above; CN4). The unit
  is named by the full imprint id, so one imprint runs one use at a time. The use is decided inside the unit, so
  `make station-imprint-use` can't show a refusal. It prints "Started a use of c0a8 in the background; see make
  station-imprints.", as admission does (section 10). While a use of that imprint runs, systemd-run refuses the unit
  name, since it is already loaded; the Makefile then prints "A use of c0a8 is already running; see make
  station-imprints.", starts nothing and exits non-zero (the check of revision 4, CN5). Such a unit starts in a clean
  environment, not the caller's shell (systemd-run(1), systemd 252 on the Pi; trail spec section 7, step 8.2). It
  inherits only the user manager's own environment, which on the Pi holds no `ENGRAM_` variable today (`systemctl
  --user show-environment`, checked 2026-10-25), and a deploy gate checks that (section 18; CN2). So the Makefile
  passes `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` when the station's `~/.config/superyak/runtime.json` names an
  `embedder_socket`, and nothing otherwise. That is the file and key `superyak-runtime` reads to set the same variable
  for every engram process (`scripts/runtime.py:84-89`, `:597`, `:653-655`). The Makefile reads only that key, by the
  same rule (`:84-88`): no file, no key, or `null` passes nothing; an absolute path is passed; anything else stops the
  use before the unit starts. It reads only that default path. `superyak-runtime` also takes another path from
  `SUPERYAK_RUNTIME_CONFIG` (`:595-597`), and the Makefile ignores it, so the unit's socket never depends on the
  caller's shell (CN2). Without the variable, `trails.py` loads the model in process from the local cache only
  (trail spec section 7, step 8.2, `local_files_only=True`), so the run never downloads a model (section 18).
- A use's report is never posted to a room unless the owner allows it. Step 1 has no command that posts it.
- Allowed and refused uses both leave receipts. Nothing else reads an imprint in step 1. That is a rule, not an
  enforcement: see the known limits below.

**Receipts.** Each is a record of the new kind `imprint-receipt`:

```json
{"kind": "imprint-receipt", "station": "…", "id": "<32 hex>", "permission": "<request id>", "event": "approved",
 "actor_id": "<user id, or null for the station>", "at": 1792956600, "detail": {}, "previous": "<sha256>"}
```

- `at` is integer UTC seconds. The example is 2026-10-25T19:30:00Z.
- `previous` is the SHA-256 of the canonical previous receipt record of the same permission. The first receipt's
  `previous` is the SHA-256 of the canonical permission record. The owner, who keeps every receipt, can see if one
  goes missing.
- **Writing.** Every receipt, from any process, is appended in one `Store.transaction()`, which is `BEGIN IMMEDIATE`
  (`peer/superyak_peer/db.py:113`): read the permission's last receipt, compute `previous`, insert. So the lighthouse
  and a station command appending at once can't fork the chain.
- **Signing** (D19). The station commands that write receipts (`station-approve`, `station-deny`,
  `station-imprint-sync`, `-sweep`, `-delete`, `-use-begin`) open the store with `Store(..., signing=False)` and hold
  no key (`__main__.py:322-327`; `db.py:86-89`). API.md makes that a contract: "they load no key at startup, so a
  damaged identity stops the lighthouse alone" (`peer/API.md:300-302`). This spec keeps the contract. Those commands
  write receipts with no signature. The running lighthouse signs every unsigned imprint receipt at start, every 60
  seconds after (a lifespan task beside federation's worker, `peer_routes.py:10-19`), and before it answers any
  imprint read. There is a precedent: revocations the restore reconcile writes are signed at the next start
  (`signatures.py:159-166`). Signing doesn't change the record, so the chain doesn't depend on it. Receipts the
  lighthouse writes itself (`received`, `shortened`, `withdrawn`, and a withdrawal's `deleted`) are signed at once.
  Until a receipt is signed, `imprint-status` and the web view show "not yet signed". While the lighthouse is down,
  receipts stay unsigned until it starts. The permission itself is always signed in the confirm transaction (D2).

| Event | `detail` |
|---|---|
| `received` | bytes, SHA-256 and parts of `imprint.db`; `manifest_sha256` |
| `approved`, `denied` | none; `actor_id` is the operator |
| `admitted` | checks passed (17), the report's SHA-256, skipped analyses, and `roads_and_trails`: N, admission's count of R(I), 0 without `route` (section 10) |
| `failed` | check number and fixed message |
| `use-started`, `use-finished` | use, its `use_id`, actions, purpose, objects as `{"imprint": <imprint id>, "count": n, "roads_and_trails": N}`, with N copied from the `admitted` receipt; when finished, the run's `end` (`report`, `withdrawn`, `ended`, `deleted`, `allow changed`, `not evaluable: limit` or `failed`), with the report's SHA-256 for `report`, the reason for `deleted` and the exit status, or the error class, for `failed` (D41) |
| `refused` | use, actions, purpose, the failing term, and `roads_and_trails` from the `admitted` receipt when there is one |
| `shortened` | the new `valid_until` |
| `withdrawn` | none; `actor_id` is the owner or the ship |
| `ended` | none |
| `deleted` | reason (`denied`, `failed`, `withdrawn`, `ended`, `upload-expired`, `review-expired`, `station`, `missing`, `restore`), and each removed file's path in the imprint and state directories, bytes and SHA-256 |
| `delete-failed` | path and error class |

No receipt holds content, query text, ids of memories, or anything about what stayed home. A use id is a random
uuid4 the station made, so naming it in a receipt tells nothing about the store. `roads_and_trails` is a count of
what the owner's yes covers, and names no id (XS2). An error class is a name from the
code, such as `OperationalError`, never the error's message.

**Withdrawal.** The owner (browser, CSRF) withdraws by revoking the permission's records. The requesting ship
(principle 1: agents may narrow) withdraws by asking the station to refuse, which edits none of the owner's records
(section 8, D17). Either may do it in any status before `deleted`. In one request:

1. Set status `deleting` and write `withdrawn`. From this receipt on, the ceiling ⟦c_I⟧ holds no use of the copy
   (section 8, item 5), whoever withdrew.
2. Remove the staging directory, the imprint directory and its state directory, under the root the request row
   records (section 10), after restoring write permission. Hash each file first. For `imprint.db` the hash is the
   manifest's, which admission verified.
3. Write the tombstone `<root>/tombstones/<imprint id>.json` holding both receipts.
4. Write `deleted` and set status `deleted`.

It never waits for Andy, and it wins over a running admission (section 10). If a removal fails, the status stays
`deleting`, a `delete-failed` receipt is written, the sweep retries, and the owner sees it. The station operator may
also delete (`make station-imprint-delete ID=`; reason `station`), since places can refuse.

**Shortening.** The owner or the ship can set a new end, later than now and earlier than the effective end. The
owner's replaces the records; the ship's is a `shortened` receipt, which the ceiling reads (section 8, item 4). Each
is a narrowing (section 8).
The effective end is the earliest of the records' `valid_until` and every shortening. Lengthening is refused: it needs a new imprint and a new yes (D18).

**Expiry and the sweep.** `superyak-imprint-sweep.timer` runs hourly (beside the backup timer, Makefile
`station-units`) and runs `superyak-peer station-imprint-sweep`. It:

- deletes, as withdrawal does, every imprint past its effective end (reason `ended`) and every request past its
  upload or review window;
- deletes the staging directory of every expired request, leaving its row content-free;
- runs `station-imprint-sync`, then retries `deleting`;
- reconciles after a restore: a row with a tombstone becomes `deleted`; a row in any status before `deleting` whose
  files are gone becomes `deleted` (reason `missing`) when it has a permission, and `expired` when it has none; a
  directory with no live row is removed, with a `deleted` receipt (reason `restore`) when the station holds a
  permission for it;
- removes the row, the permission, the receipts and the tombstone of every imprint deleted more than 400 days ago,
  and the row of every request declined or expired more than 30 days ago, so nothing is kept with no end (D32). A
  restore that brings such a row back has it removed again at the next sweep.

Imprint bytes and request contents are never in backups, because station backups copy only `peer.sqlite3`
(`backups.py:167-176`) (D15). What `peer.sqlite3` holds, and for how long its backups keep it, is in section 9.

**Known limits, stated in every `deleted` receipt:** "Files removed. The station does not overwrite disk blocks, and
cannot reach copies anyone made by hand."

**Known limits on the station** (as the permissions spec states its own for the terminal yes, its 7.6). Anyone with
Andy's shell on the Pi can read `imprint.db` (0444). That includes Claude sessions on the Pi. They can also read the
station's `identity.json`, so they could sign a permission no owner gave. "Nothing else reads an imprint" is a rule,
not enforcement. The CLAUDE.md approving section gains the rule that agents never read `~/.engram/imprints/` except
through `imprint.py use`, and never sign or write imprint records by hand. Owner-held keys (section 17, step 2) remove
the second limit. Encrypted imprints (step 7) narrow the first.

**What the owner sees afterwards.**

- `make imprint-status`: one line per imprint at the station, with short id, status, end date and last event.
- `make imprint-status ID=…`: the permission with its signature, every receipt (signed, or "not yet signed"), the
  content-free calibration report, any use reports, and what the station keeps and for how long, in the confirm view's
  words (section 9, D32), with the date each thing will be removed. The agent saves receipts in
  `~/.superyak/imprints/<imprint id>/receipts/` and checks the hash chain.
- `make imprint-verify ID=…` (peer environment):
  - checks that SHA-256 of `station_key` equals each record's `station` (`identity.py:94` makes the peer id that way);
  - verifies every signature;
  - checks that the station key matches the one pinned in `~/.superyak/imprints/station-key.json` at the first
    imprint. A changed key is a loud warning, not a pass (`peer/API.md:304-309` explains when a station's key
    changes).
- **In the owner's own use list.** The permissions spec has this spec build the owner's entry: "Until the deletion is
  confirmed, the owner's use list shows 'copy held, deletion not confirmed'" (its section 10). The machine keeps the
  shipped refs `mem:S/<layer>/<id>`, sorted, in `~/.superyak/imprints/<imprint id>/objects.json`. When the owner's
  machine has a permissions ledger, `make imprint-status` also imports each verified receipt of a use (`admitted`,
  or `failed` or `denied` with a failing term, for admission; `use-finished` or `refused` for a later use) into
  `permission-uses.db` in the form that spec gives an imprint's receipts (its 9.1). For each action on memories the
  use needed, it writes one `uses` row per batch of at most 512 refs from `objects.json`, in order:
  - `id` = `u-` + the first 32 hex of SHA-256(receipt id + action + batch number);
  - `ledger_id` = the station's peer id (its 4.1 names that for step 2), and `ledger_seq` = the receipt's position in
    its chain;
  - `agent`, `place` and `acting_for` from the use's terms; `action` and `purpose`; `object` = null;
  - `copy` = `imprint:<station peer id>/<imprint_id>`; `allowed`; `cited` = the record ids; `refusal`; `until` = the
    effective end;
  - `returned` = the batch's count and the SHA-256 of its sorted refs;
  - one `use_subjects` row (owner, ref) for each ref in the batch.

  An action on roads and trails, which the Pi derives in memory and never names, gets one row per bulk use, since
  section 8 splits an R(I) of more than 100,000 into several (the permissions spec's 9.1, item 3). N is the
  `roads_and_trails` the imported receipt carries, admission's count (section 10; the cross-check's XS2). That is
  ⌈N / 100,000⌉ rows, each with `returned` = its bulk use's count (100,000, and the rest in the last) and one
  `use_subjects` row (owner, the copy's ref). Without `route`, N is 0 and there is no such row. A use refused with
  `route` before admission counted R(I) read no road or trail, and its receipt has no N: a `denied` at approval, a
  `failed` naming a term at a run's start, or a `refused` before the imprint was `admitted`. It gets one row per
  action on roads and trails, with `returned` null, as that spec's 9.1 allows. So `engram-permissions uses --object
  mem:S/episode/<id>` finds every imprint use that covered that memory, as it finds any other use. That spec's `uses`
  lists the ledger owner's uses and takes no person argument (its 7.6, 9.3), so the owner runs it as themselves. It
  shows "copy held at Deep Space 9 (imprint c0a8), deletion not confirmed" for every imprint whose last verified
  receipt is not `deleted`, and the deletion's date and receipt once it is. The station's own receipts still name
  objects only by counts (`{imprint, count, roads_and_trails}`): they outlive the copy by 400 days (D32), and memory
  ids kept there would outlive it too. Rio Grande's call, from the
  interface pass.

  **These rows depart from the permissions spec's local receipt form** (the re-check's RN5; Rio Grande's call, privacy
  over a uniform form). They are its imported form, which its 9.1 names with four differences: one row per action the
  use needed, where a local use writes one receipt whose `cited` covers all of `need`; memories by batches of at most
  512 refs, where that spec writes one receipt per imprint batch; roads and trails as one counted row per bulk use,
  whose one `use_subjects` row is (owner, h), a copy ref and not an object of any kind; and `cited` with record ids
  but no versions. So `engram-permissions uses --action recall` counts an admission's recall rows, one per batch,
  apart from its read and imprint rows, and its use list counts imported rows apart from local ones (its 9.3).
- In the station web app, Accounts → Imprints shows the same, with Withdraw and Shorten buttons.
- Once the imprint is `admitted`, `declined`, `denied`, `failed` or `deleted`, the agent deletes the source machine's
  `imprint.db` copy and keeps the manifest, plan, `objects.json` and receipts (D24).

## 13. The commands, end to end

**On the owner's machine** (from the repository clone; Claude Code runs these when the owner asks):

```
make imprint-plan IMPRINT_ARGS='--lanes work --layers episode,semantic --since 2026-01-01 \
    --audience place:home/andy --actions imprint,route --purposes calibration,trail-evaluation --days 90'
make imprint-read PLAN=7c41                 # optional: read what would leave
make imprint-send PLAN=7c41                 # build, print and send the request, wait for the browser yes, upload
make imprint-status [ID=c0a8]
make imprint-withdraw ID=c0a8
make imprint-shorten ID=c0a8 DAYS=30
make imprint-verify ID=c0a8
```

Other plan flags: `--store PATH`, `--until`, `--shared-with`, `--exclude FILE`, `--include-unsourced-semantics`,
`--show-cross-references`, `--list FILE`, `--json`.

`make imprint-send` behaves like `make dock`:

- It builds the package, prints the request in words with the ancestry and what the station keeps (7.1), sends it,
  prints the imprint's short id (`c0a8`), the request's short id (`4f1c`, which Andy confirms at approval), the code
  and the confirm link, and waits up to 9 minutes per run.
- While it waits, it ends with `STATUS: waiting-for-you` and make reports `Error 3`. That is expected.
- After the yes it sends the manifest and the parts with progress, and ends with `STATUS: received` (waiting for
  Andy).
- Rerunning it resumes. Later runs report `STATUS: admitted`, or `declined`, `denied`, `failed` or `deleted` with the
  reason.
- Claude relays the link. The owner opens it, reads the view, ticks the check about other people, and types their own
  password. Claude never types the password and never ticks the check.

**On the Pi** (Andy, or Claude when he asks):

```
make station-pending                        # IMPRINT items with their short ids
make station-approve ID=4f1c                # approve; admission starts in the background
make station-deny ID=4f1c
make station-imprints                       # every imprint: owner, status, end date, checks, signing
make station-imprint-use ID=c0a8 USE=trail-evaluation LANE=work   # in the background, as agent:station-imprints for APPROVER;
                                            # LANE may be left out when the scope holds one lane;
                                            # prints "Started", or that a use is already running
make station-imprint-delete ID=c0a8         # the station declines to keep it
make station-imprint-admit                  # resume an interrupted admission; decided again first (D39)
```

`APPROVER` (default `andy`) is the Pi operator's word about who is acting, not an authentication. Anyone with the
Pi's shell can set it. The station checks only that it names a person (`ships.py:201-206`).

## 14. Constants

| Constant | Value | Reason |
|---|---|---|
| Part size | 4,194,304 bytes | under the 6 MiB request bound (`app.py:19`) |
| Largest package | 2 GiB | a Pi's disk and verification time |
| Largest request body | 64 KiB | it holds no part hashes |
| Largest manifest | 256 KiB | 512 part hashes fit |
| Live imprint bytes per station | 16 GiB | disk budget |
| Free-space floor | 4 GiB left after reserving 3 × package bytes | staging, joined file and calibration copy coexist |
| Open requests per ship | 4 | |
| Live imprints per source store per station | 1 (D20) | a new scope means withdraw, then send again |
| Confirm code life | 10 minutes | docking's (DS9 spec, lines 60-61) |
| Upload window, review window | 7 days each | access requests' expiry (DS9 spec, line 85) |
| Longest permission | 365 days (D18) | within the permissions spec's 366 (its P13) |
| Part uploads per ship | 120 per minute | |
| Sweep | hourly | expired imprints gone within an hour |
| Receipt signing | at start, every 60 seconds, and before an imprint read | D19 |
| Closed session | newest row before t₁ older than t₁ − 3,600 s | the trail spec's closed session (its section 4) |
| Ancestry | at most 64 ids | bounds `meta`; a longer chain is marked incomplete |
| Memories per imprint | 100,000 | the permissions spec's collection bound (its 5.4), since r_M names them as one collection (D36) |
| Calibration | MemoryMax=4G, MemorySwapMax=0, 30 minutes, at most 7,500 episodes in any dense set | measured 7.5 × n² × 8 B (section 10) |
| Station-held row, permission, receipts and tombstone | 400 days after `deleted`, then removed (D32) | the permissions spec's receipt retention (its 9.1) |
| Row of a declined or expired request | 30 days after it ends, then removed (D32) | long enough for `make imprint-send` to report the outcome; the row holds no scope or counts |
| Agent wait per run | 9 minutes | `make dock`'s |
| Use id | a lowercase uuid4, 36 characters (D41) | fits the trail spec's `[A-Za-z0-9-]{1,64}` (its section 7, check 2) |
| Unfinished use | finished by the first sync at least 1,860 s after `use-started`, which the hourly sweep runs when the unit was stopped (D41) | the use's unit's `RuntimeMaxSec=1800` and `TimeoutStopSec=60` (section 12) |
| Filter, request, manifest | `imprint-filter-v1`, version 1, version 1 | |

`POST /api/imprints` refuses a request that breaks any of these:

- it parses with `identity.parse` (`identity.py:27-48`) and has exactly the section 7.1 keys, at every level, where
  `contents` holds a subset of the ten table names 7.1 lists, each with a count of at least 1;
- `imprint_id` is a lowercase UUID4 (`[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}`), and no
  request, imprint directory or tombstone on this station already has it. It becomes a path component on the Pi;
- `source_instance_id` is a lowercase UUID; `source_ancestry` is a list of at most 64 distinct lowercase UUIDs, none
  equal to `source_instance_id`; `source_ancestry_complete` is a boolean;
- `plan_digest` is 64 lowercase hex;
- `since` and `until` are null or `YYYY-MM-DDTHH:MM:SSZ`, with `since` before `until`;
- every count and `package.bytes` is an integer from 0 to 2⁵³, `parts` equals ⌈bytes / part size⌉, and `episodes` plus
  `semantics` is at most 100,000 (D36);
- `contents` holds `memory_log` or `operation_log` only when the terms include `route` (D7);
- lanes, layers and every list are sorted, distinct and within 5.2's sets;
- the terms obey 5.3: the audience is `place:home/<h>` with h the station's super admin (`users.is_super_admin`,
  `auth.py:23`), meant to be Andy on Deep Space 9 (a deploy gate checks it), and the requesting ship's owner has a
  username that fits the person grammar;
- disk, size, per-ship and per-source limits hold.

`PUT /api/imprints/{id}/manifest` applies the same formats to the manifest's fields, with every `parts` entry and
`sha256` 64 lowercase hex, `built_at` in the `Z` form, and `ancestry` a list of at most 64 lowercase UUIDs equal to
the request's `source_ancestry`.

## 15. Components

| Component | Responsibility |
|---|---|
| `engram/imprint.py` | `plan`, `read`, `build` on the source; `admit`, `use`, `list` on the Pi, each with `--imprints-dir`; `import-receipts` on the owner's machine. The table rules of 6.2 as one ordered map, checked against the schema, with the `session_id` scrub. `pending(m)` from the ledger's lane notes. The digest keys of 5.4. The leak checks L1–L4. The 17 checks. The semantics reader. Admission's checks of `admission.json` before each write (D39). `use` with its use-id check, `--lane` always (filling in the scope's one lane), and `report.json` then `result.json`, each written atomically, with `result.json` also for its own errors (D41). |
| `engram/store_identity.py` | `ORIGIN_IMPRINT`, `stamp_imprint`, ancestry in `stamp_fork`, `ancestry`, `lineage`, `independent` (returns true, false or unknown); a `retroactive` store, or one with no stored identity, is incomplete (D13) |
| `engram/storage.py` | refuse a normal open of an imprint, before any pragma or migration, unless `imprint_working_copy=True` |
| `engram/store_reader.py` | `connect(…, vec=True)` loads sqlite-vec on a read-only connection |
| `engram/calibrate.py` | `no_content`, `no_paths`, `notes`, `max_lane_episodes`, `create_parents`, and the working-copy flag |
| `engram/persistence.py` | the bound applied to the core set and to each hub's sources |
| `engram/sharing.py`, `federation.py`, `cli.py`, `lighthouse_sheaf.py` | the guards in section 11; `fork` passes ancestry |
| `peer/superyak_peer/identity.py` | `RECORD_KEYS` for `imprint-permission` and `imprint-receipt`; `verify_station_record(public_key_b64, record, signature)`, True only when SHA-256 of the key equals `record.station`, the shape is right (including each inner record's keys) and the signature verifies; never raises |
| `peer/superyak_peer/imprints.py` | requests, the confirm with password and the check, manifests, parts, joining, status, withdrawal, shortening, receipts and their chain, tombstones, the sweep, the hand-off, the use decision with the per-copy ceiling (D38), admission's decision at each run (D39), the sync, which finishes uses, retires their allow files and records how each run ended (D41), retention with its ends (D32) |
| `peer/superyak_peer/app.py`, `peer_routes.py` | the routes in section 9 (ship routes through `ship_member`, `app.py:104-109`); the signing task in the lifespan, only where the store signs |
| `peer/superyak_peer/ships.py`, `__main__.py` | `station_pending`, `station_decide`, `station_notices` and `describe_pending` learn `imprint`; new `station-imprints`, `station-imprint-sync`, `station-imprint-sweep`, `station-imprint-delete`, `station-imprint-use-begin`, `station-imprint-admit-begin`, `verify-imprint`; `--imprints-dir` on `serve` and on every one of these (section 10) |
| peer database migration | tables for requests (ids, ship, owner, status, times, decisions, `request_sha256`, the imprints root, permission and signature) and receipts (seq, id, request, record, signature or null) |
| the lighthouse's installed user unit | `--imprints-dir %h/.engram/imprints` in its `ExecStart` (a deploy gate) |
| peer web app | the confirm view and Accounts → Imprints |
| `peer/systemd/` | `superyak-imprint-sweep.service` and `.timer`, added to `station-units` |
| `agent/superyak_agent` | `imprint send`, `status`, `withdraw`, `shorten` over the ship key, standard library only |
| `Makefile` | the targets in section 13, and the detached units for admission and uses; `station-imprint-use-run`, which the use's unit runs; the use's `--setenv=ENGRAM_EMBEDDER_SOCKET` from the default `runtime.json` only (D29); `TimeoutStopSec=60` on the use's unit; "Started", or that a use is already running (section 12) |
| `peer/API.md`, `engram/CLAUDE.md`, `CLAUDE.md` | routes and records, and that receipts from key-less commands are signed by the lighthouse; an "Imprints" paragraph and Key Files row; in CLAUDE.md's approving section, that an `IMPRINT` item is a person's memories, that Andy confirms its short id against the owner's machine, that `station-approve` returns while admission runs, and that agents never read `~/.engram/imprints/` except through `imprint.py use` |

## 16. Tests the builder must include

**Filter (engram)**

- **Every table classified.** Build a store from every migration, add the hook tables, and assert that each table
  has a rule. A source-only table is not copied and is named in the dry run. A package table without a rule stops the
  build.
- **Selection.** Lanes; layers; the half-open date range, including an unparseable `created_at` and one with no zone
  (read as UTC); `--shared-with` matched by instance name, layer, audience and digest; a source memory changed after it
  was shared is not shared; `--exclude`; a memory with a co-subject in a fixture ledger stays home and is counted. In a
  fixture ledger, a memory whose latest lane note is `pending`, and one whose latest note names the other lane, stay
  home and are counted; with no ledger, or no note, the lane column decides (D40).
- **Down-closure.** A semantic with one out-of-scope source stays home. A semantic whose sources were all pruned stays
  home and is counted, and ships with `--include-unsourced-semantics`. A semantic with one source pruned is judged on
  the rest.
- **Induced links.** For each link table, a row with one endpoint outside M is dropped. A resonance created after t₁
  is dropped.
- **Log rows.** Rows at or after t₁ and rows of sessions not closed at t₁ are dropped. A recall and a `log_outcome`
  after the plan don't change the digest. A late outcome on a kept row does, and the build refuses. With no `route`
  in the terms, no `memory_log` or `operation_log` row ships. Calibration's report on such a package, run as admission
  runs it but with one fixed `now` passed to both runs, equals its report on a package of the same memories built
  with `route` in the analyses `first_open`, `persistence_scores`, `cohesion` and `persistence`, and in the survey
  apart from `episodes.sessions`, the log tables' row counts, and the survey's `file` and `identity` (calibration
  reads no log row's content). The `source` and `identity` sections, and the survey's `file` and `identity`, differ,
  since the two packages' paths, bytes and imprint ids differ (`engram/store_reader.py:66-73`, `:124`, `:174`).
  `first_open` reads the wall clock unless `now` is passed (`engram/calibrate.py:89`, `:286`), so the test fixes it,
  as the recall-row test below fixes one `as_of` (the check of revision 4, CS1). Without `route`, the survey counts
  0 sessions and 0 log rows, with the note "because route was not chosen" beside them. In both reports the `paths`
  section says only "not measured at admission; trails are used only by the trail evaluation", and neither report
  names a session id (the final check's FS1 and FS2).
- **No footpath without `route`** (D7; the re-check's RMF1). The fixture is a store with one closed session that
  wrote two work-lane episodes and made no recall. Built without `route`, the package's `episodes.session_id` is null
  on every row, `memory_log` and `operation_log` are empty, check 12 passes, and a session reader written from the
  trail spec's section 4 alone finds no session and no trail. Built with `route`, both episodes keep the session id,
  and the reader finds one trail of two wrote touches. A second session still open at t₁ keeps no session id even with
  `route`. Setting one session id by hand in a package built without `route` fails check 12 and the digest (check
  13). Without `route`, an episode whose text names a registered session's id is a cross-reference, and the build
  refuses until it is left out.
- **Source owner (D37).** With a fixture ledger, a store with no `stores` row, or one whose owner is another person,
  is refused. With no ledger, the plan proceeds.
- **Recall rows.** Instinct ids are removed, and a row whose remaining targets are all in M is kept. A row with any
  other target outside M is dropped, as is one with no targets left. Kept rows have `context` = {recall_id,
  session_id}. Outcomes are normalized, including `used: auto: cited`. On a fixture with `route` and a mixed-lane
  recall, derive touches from the package and from the source as the trail spec's section 4 does, with one `as_of`
  for both (the CLI's default `as_of` differs between the two files, its section 7). Either the fixture's source holds
  no row at or after the plan's end t₁, and `as_of` is at or after t₁; or the test takes `as_of` = t₁, and the source
  holds no row at exactly t₁. Then every session the package holds is closed in the source too. An earlier `as_of`
  could count a session closed in the package, whose later rows stayed home, and open in the source (its section 4,
  "Sessions"; found while checking I6 in the consolidation pass). A later one, on a source with rows after t₁, could
  find a shipped session open in the source: 5.2 decides "closed at t₁" from rows before t₁ only, and a session can
  write again later under the same id, since engram takes it from `CLAUDE_CODE_SESSION_ID`
  (`engram/server.py:1319-1332`). Then the package would have that session's touches and the source none (the
  cross-check's XS1). With either fixture (the trail spec's I6):
  - every touch derived from the package is a touch derived from the source, of the same memory, kind and time, in the
    same order within its recall, and suggested only if the source's is;
  - on every recall row the package keeps, the trail spec's "exactly one target" rule (its section 4) gives the
    source's answer.

  The package's trails are not asserted to equal the source's restricted to M. That fails on a mixed-lane recall,
  for the reasons the trail spec's section 7 gives ("The cost, chosen for privacy"). What an imprint loses is measured
  by its synthetic-imprint test (its section 12).
- **`route_shown` rows.** Targets are cut to M in order. A row cut to nothing is dropped, and so is a row of another
  lane. `context` is cut to its four keys. No kept recall or `route_shown` row carries a `cut` key or any other mark
  of what was removed.
- **Plan digest from the definitions.** A second implementation in the test, written from section 5.4 alone, computes
  the digest of a fixture package and gets the same value.
- **Rowids.** Every memory table's rowids, and each FTS `_docsize`'s ids, run 1..n, whatever the source's rowids were.
- **Canaries (the anti-goal test).** Plant unique random strings in every TEXT column of every left-out row and of
  every dropped table, in a query, in an outcome note, and in `cold.db`, the category stores, the clipboard and the
  notepad. Make some of them index as FTS terms that share a long prefix with a shipped term, so FTS5 would store them
  prefix-compressed. Plant left-out UUIDs so they would be split at their hyphens, and UUIDs in long values at offsets
  that cross an overflow page boundary. Plant a unique 3,072-byte vector in every left-out vector row. Build. None of
  these is found by L1, by any FTS table's `fts5vocab`, by L3, or by a raw-byte search.
- **The checks catch what they claim.** On copies of a built package: an index-only FTS entry with no content row
  fails L2 (and passes FTS5 `'integrity-check'`, which the test records); a non-zero invalid vec0 slot fails L3; a
  vec0 `_rowids` id that is not a shipped row fails L3; a left-out UUID split across an overflow boundary is found by
  L1.
- **Insertion only.** `freelist_count` is 0. Header bytes 18 and 19 are 1. `foreign_key_check` is empty.
- **Cross-references.** Text naming any left-out key (a memory, an instinct, residue, an assessment, a drift report, a
  log row) stops the build, ignoring case. A shipped session id in a kept column does not. `--exclude` lets the build
  through, and every scan then passes. There is no flag that keeps a cross-reference.
- **Plan digest.** The build refuses when a memory changes between plan and build. The plan's `--list` equals the
  package's rows.
- **Source untouched.** The source's SHA-256 is unchanged with no writer. With a live writer the snapshot is
  consistent and the source is never written.
- **Identity and ancestry.** A random imprint id, origin `imprint`, `forked_from` = the stored or derived source id,
  ancestry = [source] + the source's. An empty old store, the published house and an imprint are refused as sources.
- **Vectors.** Copied bit for bit.
- **Request.** The request has exactly the 7.1 keys. `contents` names exactly the non-empty tables among 5.4's ten,
  and never `meta`, `schema_version`, an FTS table or `sqlite_sequence`. Every field but `kind` and `version` is shown
  in the confirm view: `imprint_id` by its short id, `plan_digest` by its first 8 characters with the words that the
  whole digest is sent, and `source_ancestry` by its short ids. The terminal prints the request, the ancestry and
  what the station keeps, and for how long, before it is sent.

**Station (peer)**

- **Routes.** Ship key only, the right ship, and 404 on the door.
- **Request checks.** Each format in section 14 refuses a bad value: a non-UUID4 or uppercase `imprint_id`, a path
  separator in it, a duplicate `imprint_id`, a bad hash, a time without `Z`, a float or negative count, a wrong part
  count, an audience other than the super admin's home. Size, disk, per-ship and per-source limits.
- **Confirm.** Only the ship's owner sees and confirms; others get 404. CSRF, password and the ticked check are
  required. A wrong password counts toward the login limits. The code is single-use and expires.
- **Signing.** The permission is signed in the confirming transaction, has exactly its keys and each inner record
  exactly its keys, and verifies with `verify_station_record`. A record of another kind or another station fails.
  r_M names exactly one collection, `collection:<owner>/imprint-<imprint_id>`, finite `stores`, and `"*"` for `layers`
  and `lanes`; r_T names finite `stores` and `"*"` in its other four object dimensions. Both pass the permissions
  spec's write rules for an outside-home allow (its 5.4), run as written from that spec.
- **The ship narrows without editing the owner's records.** A withdrawal or shortening by the ship leaves r_M and r_T
  unchanged, and every later use of the copy is refused at the station's ceiling, or past the new end.
- **One ceiling per copy** (D38; the re-check's RS2). Two imprints of one store by one owner, made one after the
  other: copy 1 with `route`, withdrawn by the ship, so its records stay unrevoked; copy 2 without `route`, holding
  only memories copy 1 held. A trail evaluation on copy 2 is refused at the ceiling (item 2), though copy 1's r_M
  would match it. A use of copy 2 is never
  allowed through copy 1's records, nor after copy 2's own end, even while copy 1's records run longer. On a fixture of
  both, the station's check gives the same answer as the permissions spec's meet over `Req`, computed with that spec's
  `decide` over every record the station holds and ⟦c⟧ as a layer kept outside a ledger (its 6.1).
- **Manifest before parts.** A manifest before `allowed`, a second manifest, and a manifest that differs from the
  request in any shared field are refused. Parts before the manifest are refused.
- **Parts.** Refused before `allowed`. A wrong length or hash is refused. A repeated part changes nothing. Upload
  resumes after a restart. A body over 6 MiB gets 413.
- **Complete.** The whole-file hash is checked. The item appears in `station-pending` with its text flattened.
  Odo's notice appears, naming no owner and no details.
- **Decline and expiry.** A declined request's staging directory is gone at once, and an expired one's after the
  sweep. The row holds no scope, counts or terms in either case, and `peer.sqlite3` never did. The row itself is gone
  after the sweep 30 days later.
- **Approval.** Approve and deny by short id. `station-approve` returns before admission ends and starts the unit,
  named `superyak-imprint-admit-<full imprint id>`: two imprints whose ids share their first 4 hex get two units. The
  request row records the imprints root. A denial deletes everything and writes receipts.
- **Admission after the end** (D39; the re-check's RS3). Approve, stop the unit before it runs, move the clock past
  the effective end, and resume with `make station-imprint-admit`: `station-imprint-admit-begin` refuses with a
  `failed` receipt naming the end, no calibration runs, and the imprint is deleted with reason `ended`, before any
  sweep. The same when the ship shortened the end to a time that has passed. A shortening that passes during
  calibration stops admission before it writes its report, with the same receipts. `admission.json` is replaced
  atomically on a shortening.
- **The imprints root** (the re-check's RN10). With `--imprints-dir` set to a test root on `serve` and the commands,
  withdrawal in the lighthouse removes the directories under the root the request row records, and nothing under
  `~/.engram/imprints`. A lighthouse started with another root still removes the recorded one and logs the mismatch.
- **Receipts.** A receipt written by a key-less command is stored unsigned and signed by the lighthouse within 60
  seconds, and at its next start if it was down. `imprint-status` shows "not yet signed" until then. Two processes
  appending at once produce one unbroken chain. A removed receipt is detected by `imprint-verify`.
- **Withdrawal.** In every status, by the owner and by the ship. Another person or ship gets 404. Every file in the
  imprint and state directories is gone, the receipt lists the hashes, the tombstone is written, and a second
  withdrawal changes nothing.
- **Withdrawal during admission.** Withdraw while admission is checking, and again while it calibrates. Admission
  stops, writes nothing after the removal, never recreates either directory, and the sync never moves the row to
  `admitted`. A leftover is removed by the next sweep.
- **Shortening.** It narrows only.
- **Sweep.** End dates and windows delete. A failed removal is retried. Restore reconciliation uses tombstones, and
  removing a directory with a permission writes `deleted` (reason `restore`). A restored row in `approved` or
  `received` whose files are gone becomes `deleted` (reason `missing`); one in `requested` with no permission becomes
  `expired`. 400 days after `deleted`, the row, the permission, the receipts and the tombstone are all gone; 30 days
  after a decline or expiry, the row is gone. No table or file the station keeps about imprints holds a row or file
  past those ends (D32).
- **Backups.** A `station-backup` copy holds no imprint path and no request contents, and the restore test passes.

**Admission (engram)**

- **Each check fails.** One tampered package per check: a changed byte, a WAL header, a planted trigger, an extra
  table, another sqlite-vec `_info`, a changed `meta`, a dangling target, a non-empty dropped table, an unscrubbed
  context, an instinct id in a recall, a lane outside `scope.lanes` or a time outside the scope, a session id in a
  package without `route`, an unknown migration, a free page, a digest mismatch, a rowid gap, an FTS orphan, a non-zero
  invalid vec0 slot.
- **vec0 reading.** The verifier opens the package immutable with sqlite-vec loaded, and creates no side file.
- **Calibration.** No `content` key and no text value from the imprint in `report.json`. `source_unchanged`. No side
  files. Copies deleted. A lane, a core set and a hub over 7,500 each record a skip. A 7,500-episode lane on random
  768-dimension vectors finishes under MemoryMax=4G with MemorySwapMax=0.
- **Guards.** `Storage(path)` raises on an imprint before it sets WAL or migrates: the file's bytes are unchanged and
  no `-wal` appears. `open_read_only` works. `share`, `sync_genome` and `fork` refuse an imprint. `resolve_db_path`
  never returns one. `lighthouse_sheaf.py` refuses an imprint and flags a pair of sibling stores as not independent.
- **Uses.** For each term of section 8's check, a use that fails only that term is refused with that term, in order.
  Each writes a receipt. A use after withdrawal or the end is refused. An allowed use writes the allow file with the
  fields the trail spec checks. A trail evaluation over a trail of 40 touches is not refused with `BOUND`, since it is
  a bulk use (section 8; the re-check's RN6).
- **Admission stays inside its `Need`** (the final check's FS1). With `route`, record every use admission performs
  (verification, the count of R(I), the survey and calibration, run as admission runs them). Each is in
  Need(admission), and the permissions spec's `decide` agrees with the station's check on each. No use reads a road or
  trail for `calibration`.
- **The count of R(I)** (the cross-check's XS2). With `route`, `result.json` and the `admitted` receipt hold the
  number of roads and trails the trail spec's functions derive from the package at `as_of` = t₁, and a later `as_of`
  gives the same number. Without `route` they hold 0. No receipt names a road, a trail or a session.
- **Use ends** (D41; the trail spec's I2). A use id is a lowercase uuid4, and `imprint.py use` refuses any other form
  and a use whose directory exists. A finished use has `report.json` and `result.json` in its directory and no allow
  file, and rerunning `trails.py --imprint-use <that id>` is refused with no report. On fixtures where the run ends
  each way, `use-finished` records: `report` with the report's SHA-256; `withdrawn` for a withdrawal during the run,
  and only once the tombstone exists; `ended` for an end reached during the run; `deleted` with reason `station` for a
  station deletion during the run, never `withdrawn`; `allow changed` for a shortening whose
  new end is still ahead, never `withdrawn`; `not evaluable: limit` for a run killed by a signal, and for a unit
  stopped with no `result.json`, finished by the sweep's first sync at least 1,860 s after `use-started` and not
  before; `failed` with the exit status for a `trails.py` exit other than 0 and 3, and `failed` with the error class,
  never its message, when `imprint.py use` raises after creating the use directory (the check of revision 4, CS2).
  Two syncs at once write one `use-finished`. A sync run between `imprint.py use`'s two writes finds no `result.json`
  and finishes nothing, so an exit of 0 is recorded as `report` (CN6). With no `LANE`, `imprint.py use` passes the
  scope's one lane to `--lane`, and with a two-lane scope it refuses before `trails.py` runs, recorded as `failed`
  (CN4). A second `make station-imprint-use` of the same imprint while one runs starts nothing, prints that a use is
  already running, and exits non-zero (CN5).
- **The use's unit** (D29; the trail spec's I3). Its command carries `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` exactly
  when the fixture's `runtime.json` names an absolute `embedder_socket`. With no file, no key, or `null`, it carries
  none, and with a relative path or another non-string the use stops before the unit starts. A
  `SUPERYAK_RUNTIME_CONFIG` naming another file changes nothing. The command carries `-p TimeoutStopSec=60` (CN1,
  CN2).
- **Lineage.** An imprint and its source, two imprints of one source, an imprint and a fork of its source, and a file
  copy are not independent. Three generations: a fork of a fork is not independent of the genome. Cousins and siblings
  are not independent. An imprint of a fork of a fork is not independent of the genome. A fork made before the rule
  gives unknown. A chain longer than 64 is incomplete. A store older than identity, and its copy made by the old
  `fork` after one side pruned its earliest episode, get different retroactive ids and `independent` = unknown, not
  true; an imprint of either is incomplete too (the re-check's RS4). A store with no stored identity, read read-only,
  counts as retroactive. Two unrelated stores made after identity are independent.
- **Owner's use list.** With a fixture ledger, `import-receipts` writes the `uses` rows of section 12: one per action
  per batch of at most 512 refs, with one `use_subjects` row per ref, so an imprint of 1,300 memories gives 3 rows
  per memory action. An `admitted` receipt with `roads_and_trails` = 150,000 gives two rows per action on roads and
  trails, with `returned` 100,000 and 50,000; a `denied` receipt of an imprint with `route` gives one, with `returned`
  null (XS2). `uses` shows "copy held, deletion not confirmed" until a verified `deleted` receipt arrives, and
  `--object` finds an imprint use by a shipped memory's ref. No station receipt names a memory id.

## 17. Later steps (separate specs)

1. **Serving an imprint** to agents through the lighthouse receiver, with `recall`, `read` and `inject_context` as
   separate actions with receipts (local-city spec), under the permissions core: more audiences and requesters, and
   the meet of person, agent, place and county. The station's ledger then registers each imprint store with
   `imprint_of` = its source's id (permissions spec 4.4 and 7.4). Its collection and records move into that ledger,
   and nothing moves in wider than it stands (Rio Grande's call, from the re-check's RS2):
   - the owner's `shortened` receipts become that spec's replacements (`replaces` = the record, the new
     `valid_until`), and the owner's `withdrawn` receipts become its revocations, both by the owner in the browser;
   - a record whose copy the ship withdrew, or that ended, or whose copy was deleted, moves in revoked, with its
     receipt as the reason, or does not move in. It never moves in in force. Which of the two that spec's step 2
     allows is its to say, since the station is no steward of the owner's home (its 7.1);
   - the ceiling stays a layer kept outside the ledger, defined here, as that spec's 6.1 lets a layer be. It keeps
     reading the station's receipts, so a ship's shortening still ends its copy at its time;
   - every use names its copy h (its 6.1), and the decision is that spec's `decide`. It equals section 8's check, or
     is narrower once the owner's home adds denies (section 8, "Why the station's check is the permissions spec's
     meet").
2. **Owner-held keys** (a passkey or hardware key), so a permission verifies without trusting the station. Needed
   before a county station takes imprints.
3. **Station to station** over federation's signed envelopes (`identity.py:153-159`).
4. **Deltas and replacement.** A new imprint that supersedes an older one with one yes.
5. **More of the store.** Cold storage and category stores, each with its own closure rule. Trail roads rebuilt on
   the Pi from the imprint.
6. **Rail.** The rail spec counts agreement only between stores whose `independent` is true, and reads row-level
   provenance (section 11). A store older than store identity is never complete, so it counts for nothing until a
   spec gives it a complete ancestry another way. A synced episode with no recorded origin is a copy of unknown origin
   (section 11).
7. **Encrypted imprints.** Each imprint encrypted at rest with its own key, so deletion destroys the key and reaches
   every copy of the bytes.
8. **Other people's yes.** Co-subjects found by a detector (permissions spec step 4) and asked through their own
   homes, so a memory about two people can move with both yeses.

## 18. Deploy gates and things to confirm during the build

Before the first live imprint:

- Andy names the store and its owner says yes, and Andy answers the question about other people (section 20).
- `make setup-engram` succeeds on the Pi. It needs aarch64 wheels for every locked dependency. If one has none, the
  builder adds an admission environment holding only what calibration and `trails.py` import (numpy, scipy,
  sqlite-vec: `calibrate.py:41`, `persistence.py:19-21`, `storage.py:102-104`), and says so. The trail spec needs
  sqlite-vec there too (its interface item I3).
- The peer and engram suites pass on the Pi (station law section 2).
- The imprint routes answer 404 on the door.
- `make station-units` installs the sweep timer.
- A `station-backup` holds no imprint path and no request contents.
- The lighthouse signs a receipt that a key-less command wrote, within 60 seconds.
- The station's super admin is `andy`, since the audience check (section 14) names the super admin's home.
- Andy accepts the ceiling as his home's rule for imprints: the set C and the five items of section 8 (D38; the
  re-check's RN7). The operator's home is his, so this layer is his consent, and the ship's acts only ever remove
  uses from it through receipts. Until he accepts it, no imprint is approved.
- The lighthouse's installed unit passes `--imprints-dir`, and it names the same root as the Makefile's `IMPRINTS`
  and the sweep's unit (section 10; the re-check's RN10).
- The CLAUDE.md rule about `~/.engram/imprints/` is in the approving section.
- The station user's systemd user manager holds no `ENGRAM_` variable in its environment (`systemctl --user
  show-environment`), since a use's unit inherits it (section 12, D29; the check of revision 4, CN2). It held none on
  2026-10-25.

Before the first `trail-evaluation` use: the store's embedding model is on the Pi, through the shared embedder service
or in the admission environment, loaded inside the use's 4 GB cap. Without it, measure W is "not evaluable: no
embedder" and only the route gate is decided (trail spec section 7, step 8.2, its interface item I3). The run never
downloads a model. That rests on the trail spec's step 8.2: without `ENGRAM_EMBEDDER_SOCKET`, `trails.py` builds the
in-process model with `local_files_only=True`, which reads only the cache. With the shared service, the use's unit
gets its socket from the station's `runtime.json` (section 12, D29), and a service that doesn't answer raises
`EmbedderUnavailableError` rather than loading a local copy (`embeddings.py:191-194`). Without
the service, the model files must be in the station user's `~/.kairos/models/fastembed` (`embeddings.py:12`) before
the first use.

## 19. Left to the builder

- The peer tables' exact DDL, within the fields in section 15.
- The insertion order of link and log tables, and how `imprint.py` is split into modules. Memories and vectors go in
  `(created_at, id)` order (D33).
- The confirm view's and Accounts section's layout, and progress output.
- The fixed failure messages.

## 20. Open for Andy

None of these block building. They block the first live imprint.

- **Which store to imprint first, and its owner's yes** (the vision's open item).
- **Is the station-signed record of the owner's browser yes, with their password, enough for step 1?** The other
  choice is that the owner must also hold a key of their own (later step 2) before any imprint leaves a machine.
- **Memories that mention other people.** Step 1 can't ask the people a store mentions. It leaves out memories with a
  recorded co-subject and relies on the owner's check for the rest (D27). May step 1 imprint memories that mention
  other people at all? And must the first store be work lane only? Until Andy answers, that default stands. The
  permissions spec and the trail spec list the same question (their sections 19 and 14).
