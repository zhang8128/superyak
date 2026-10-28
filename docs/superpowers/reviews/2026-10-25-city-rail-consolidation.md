# City rail: consolidation pass across the three specs

Date: 2026-10-25. Author: Rio Grande's consolidation author, a fresh agent on the Pi. Contract:
[the city rail vision](../../city-rail-vision.md).

Each spec was approved on its last check. This pass settles what those checks left, so that the three specs agree
before planning. I applied every listed item or said why not. I let nothing more leave a machine and widened no
permission. I edited the three specs with targeted edits only, and the interface table. I wrote this log. I edited no
review file. I committed nothing, pushed nothing, merged nothing, deployed nothing and posted nothing.

The specs after this pass:

- **P**, permissions: `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md`, revision 5.
- **I**, imprints: `engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md`, revision 5.
- **T**, trails: `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md`, revision 7.
- The interface table: `docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md`.

The items came from:

- P: "Check of the follow-up revision (revision 4)" in `2026-10-25-permissions-by-place-spec-review.md` (BS1 to BS3,
  BN1 to BN4), and its "For Rio Grande" list.
- I: "Check of revision 4" in `2026-10-25-store-imprint-spec-review.md` (CS1, CS2, CN1 to CN6), and the two items
  P's reviser carried for I.
- T: the points I's response and I's check left for T's next pass, and P's carried note on T 7.

Every decision below that doesn't quote Andy, station law or a spec's source of truth is Rio Grande's call.

## Summary

| Spec | Applied | Declined |
|---|---|---|
| P | BS1, BS2, BS3, BN1, BN2, BN3, BN4; status line and revision tags | none |
| I | CS1, CS2, CN1, CN2, CN3, CN4, CN5, CN6; I 8's owner who is the operator; I 12's rows for roads and trails; status line, revision history and revision tags | none |
| T | I2, I3 and I6 marked provided, each checked against I; section 7's "Calibration reads exactly that"; section 7's citation of P 7.6; status line, revision history and revision tags | none |
| Table | rows 8, 13, 21 and 29 from P's reviser, and "What changed, by spec"; every row this pass touched (6, 8, 13, 14, 20, 21, 23, 24, 27, 28, 29) | none |

Two things went one step past the letter of an item. Both only narrow:

- BS2's bound covers every bulk use, not only counted ones (P, below).
- Checking T's I6 against I found that I's recall-row test needs its one `as_of` at or after the plan's end t₁ (I
  and T, below).

## Permissions (revision 5)

- **BS1. Applied.** P 10, "Keeping it is an imprint", gains "What the agent is told". To an agent that doesn't act
  for the ledger owner, a refused `remember` says only that keeping this content is not allowed. It names no code,
  layer or action, as 9.2 says of a refused read, and its receipt shows as 9.2's agents row. The paragraph gives the
  case. Andy records `person:amy` on m1 after use 1 delivers it. The first failing layer is then `place:home/amy`,
  since subjects come first, by id (6.5, step 2). Naming it would tell `ph-coordinator` that m1 is about Amy. U17
  tests it with that co-subject. P 18 now says its "each refusal names its rule" is for the owner's CLI, and that 9.2
  and 10 fix what an agent is told, since the reviewer noted that line could be read to cover the guard. No rule
  changes.
- **BS2. Applied, as a bound (the reviewer's first option).** P 6.4 "Size" gains "Named memories": the roads and
  trails of one bulk use name at most 100,000 distinct memories in all, and a larger set is several bulk uses.
  - *Past the letter.* The reviewer asked for counted bulk uses. I bound every bulk use, named or counted. P bounds no
    trail's length, so a named bulk use of 512 trails has no bound on what it names either. This only narrows, and no
    use in I or T is a named bulk use over roads or trails.
  - "Refused" says an oversized U, in objects or in named memories, gets `BOUND` before any object.
  - 6.5 step 1 runs both size bounds before any object.
  - "Its Pi budget" now says what the largest is: 100,000 objects at three actions each, plus 100,000 named
    memories at `recall` each, so 400,000 (object, action) pairs. That is the case section 15's 40 s covers.
  - 9.1 item 3 says "one counted row per bulk use", within both bounds.
  - Section 15 gains the row "Memories named per bulk use".
  - U22 gains: 100,001 named memories gets `BOUND`; the same trails split in two are decided object by object.
  - U24 says its fixture is the largest bulk use 6.4 allows.
  - The header's "Depended on by" says I's uses always fit: every memory a road or trail of R(I) names is in
    objects(I), at most 100,000 (I 8, D36). No verdict in I or T changes.
- **BS3. Applied.**
  - P 14's step 2 gains the line: step 2 decides what a subject sees of another subject's home in receipts (9.2).
    As written, a co-subject such as Jenn would see Andy's home's layer and record ids, while 9.4 keeps home rules
    readable only by their person.
  - P 19's item on memories that mention other people gains "A second fact, not a decision": once co-subjects can
    say yes, an allowed item's annotation names each allowing home. So an agent shown a memory about Andy and Jenn
    learns both homes.
  - Neither line decides whether such memories may move.
- **BN1. Applied.** Section 15's "Objects per bulk use" says "such as an imprint batch, or one of the evaluation's
  `read` batches".
- **BN2. Applied.** 6.4's "Refused" says an oversized U is refused "once its requester and places pass, before any
  object is decided", as 6.5 step 1 and U22 already say.
- **BN3. Applied.** 9.2 gains the row "The ledger owner, and agents acting for the owner": the owner's list (9.3),
  with each refusal's code, layer and action. A refused agent acting for the owner sees its own receipts as the agents
  row says, and the layer only in that list. This states what 9.2's paragraph and 9.3 already gave, so nothing
  widens.
- **BN4. Applied.** 9.2's agents row says a bulk refusal, which names no id, shows its count in place of the id, and
  for a named bulk use also the SHA-256 of its sorted objects. Both are already in that use's own receipt (9.1), and
  are about what the agent itself asked for.
- **Revision tags.** The status line says revision 5 and lists these. The header says the imprints spec is revision
  5 and the trail spec revision 7, and gains a revision 5 item in "Depended on by". 6.4 and 11 say trail spec
  revision 7.

## Imprints (revision 5)

- **CS1. Applied.** I 16, "Log rows": the test also leaves out the survey's `file` and `identity`, and passes one
  fixed `now` to both runs.
  - `survey` returns `{"file": facts, **body}` (`engram/store_reader.py:174`).
  - `file_facts` holds the path, bytes and SHA-256 (`:66-73`).
  - The body holds `identity` from `store_identity.describe` (`:124`).
  - Two packages with different bytes and imprint ids differ in all of these.
  - `first_open_preview` reads the wall clock unless `now` is passed (`engram/calibrate.py:89`). `calibrate` takes
    `now` (`:244-245`) and passes it on (`:286`).
  - No other analysis on calibration's path reads the clock. The `datetime.now` calls in `engram/sheaf.py` (`:187`,
    `:298`, `:390`) are in the writing and sleep-pass functions, which calibration doesn't run.
- **CS2. Applied, the reviewer's first option, with one sentence of the second.**
  - I 12: once it has created the use directory, `imprint.py use` writes `result.json` in a `finally`. Its own
    errors give `"exit": null` and `"error"` = the exception's class name, never its message, which could quote a
    path or text. The schema gains `"error"`.
  - A refusal before the directory exists writes nothing, and never into another use's directory. In the unit, only
    a withdrawal, a deletion or an end reached between the begin step and the use can lead there, and rules 2 to 4
    record those.
  - Rule 6 says a stop from outside, such as `systemctl --user stop`, reads as a limit, since the station can't tell
    it from a cap. That is honest, and it names no wrong cause.
  - Rule 7 covers an error in `imprint.py use`.
  - D41, the `use-finished` receipt row and the status line say the same.
  - I 12's receipt note says an error class is a name from the code, never a message, so receipts still hold
    nothing about the store.
  - I 16, "Use ends", tests `failed` both ways. That is the first half of CN7.
- **CN1. Applied.**
  - The use's unit passes `-p TimeoutStopSec=60`.
  - The sync finishes a use with no `result.json` 1,860 s after `use-started`, in place of 1,800 s. `RuntimeMaxSec`
    counts from the unit's start, which comes before `use-started`, and systemd waits `TimeoutStopSec` between
    SIGTERM and SIGKILL. On the Pi `systemctl --user show -p DefaultTimeoutStopUSec` gives 1 min 30 s, and the unit
    now fixes 60 s.
  - A stopped unit runs no sync of its own, so its use is finished by the first sync after that, which the hourly
    sweep runs.
  - The t_end fallback, the constants row and the test say 1,860 s and "the first sync".
  - Rio Grande's call: passing the property, rather than waiting for the user manager's default, keeps the bound in
    the spec.
- **CN2. Applied.**
  - I 12 and I 16: `"embedder_socket": null` passes nothing, as `superyak-runtime` reads it (`scripts/runtime.py:84-86`;
    `raw.get` returns None for a null).
  - The Makefile reads only the default `~/.config/superyak/runtime.json` and ignores `SUPERYAK_RUNTIME_CONFIG`,
    which `superyak-runtime` honours (`:595-597`). So the unit's socket never depends on the caller's shell.
  - D29 no longer says "only through `--setenv`". It says a unit inherits the user manager's own environment.
  - I 18 gains a deploy gate: that environment holds no `ENGRAM_` variable. `systemctl --user show-environment` on the
    Pi today lists none.
- **CN3. Applied.** I 10's reason for the survey's counts now fits both counts. A count returns no id, digest or
  content, so under P 6.4 it is no `recall` or `read` of a road or trail. It groups no episodes by session and orders
  none. The log tables' row counts are already in the request's `contents`, which the owner saw before the yes (I
  7.1). The interface table's row 13 now says "no log row's content".
- **CN4. Applied: `imprint.py use` fills in `LANE`.**
  - Section 12, its table, D41, section 15 and interface row 27 already said so. Only the unit's command line read
    otherwise.
  - The command now carries `[LANE=<lane>]` only when the caller gave it.
  - `imprint.py use` reads `scope.lanes` from the imprint's `manifest.json`, and refuses a two-lane scope without
    `LANE`. The refusal is recorded as `failed` with its error class.
  - The test says so.
  - Rio Grande's call: the Makefile would need its own reader of the manifest, and the use is decided inside the unit
    anyway.
- **CN5. Applied.**
  - `make station-imprint-use` prints "Started a use of c0a8 in the background; see make station-imprints.", as
    admission does.
  - While a use of that imprint runs, systemd-run refuses the loaded unit name. The Makefile then says a use is
    already running, starts nothing and exits non-zero.
  - Section 13's comment, section 15's Makefile row and the test say so.
- **CN6. Applied.** `imprint.py use` writes `report.json` first, atomically (a temporary file, then a rename), and
  then `result.json` the same way. The test checks that a sync between the two writes finishes nothing.
- **I 8, an owner who is also the operator. Applied** (carried by P's reviser).
  - I 8 gains "When the owner is the operator". P 6.3 counts the one home layer once. A consent layer is the union
    of its allows less its denies (P 6.1).
  - If the ceiling were read as one more allow there, the owner's unrevoked r_M would still match a copy's uses after
    the ship withdrew it. No selector names h.
  - So at the station that home layer is defined as the owner's records met with the ceiling,
    ⟦L⟧ = (∪_J ⟦p_J⟧) ∩ ⟦c⟧, as P 6.1 lets a layer kept outside a ledger be.
  - The ceiling stays its own term. That also answers I's final-check nit FN2.
  - The station's code doesn't change, since it already computes the intersection.
  - The item about outside-home allows points to the new paragraph.
- **I 12, "one row" for roads and trails. Applied** (carried by P's reviser). An action on roads and trails now gets
  one row per bulk use: ⌈N / 100,000⌉ rows for N of them, as I 8 splits R(I) and P 9.1 item 3 has it. The paragraph
  on departures from P's form says "one counted row per bulk use". I 8's "Bulk uses" also names P's new bound on
  named memories, which never splits a use here.
- **Beyond the items, found while checking.**
  - I 12's known limits on the station cited "the permissions spec ... its 14" for the terminal yes. The words are
    in P 7.6, so it now cites 7.6, as T does (below).
  - I 16, "Recall rows", now takes its one `as_of` at or after the plan's end t₁. See T's I6 below.
- **Revision tags.** The status line says revision 5, and the revision history gains row 5 (row 4 now names
  `05f4538`). The header cites P revision 5, whose bulk uses name at most 100,000 memories, and T revision 7.

## Trails (revision 7)

- **The status line and section 11: I2, I3 and I6 marked provided.** I checked each ask against I as it now stands.
  - **I2: provided** (I D41; sections 12, 14 and 16).
    - `withdrawn` only with the tombstone, `ended`, `allow changed` and "not evaluable: limit" are I's rules 2, 3, 5
      and 6.
    - I's rule 2 is narrower: it also needs a `withdrawn` receipt by the run's end.
    - I adds `deleted` (a station deletion writes a tombstone but is no withdrawal) and `failed`. T 7's check 7 now
      names both.
    - The sync deletes the allow file, then writes `use-finished` once.
    - `report.json` (only on exit 0) and `result.json` are the names T's check 5 reads.
    - A use id is a lowercase uuid4 of 36 characters, which fits check 2's `[A-Za-z0-9-]{1,64}`.
    - The use always passes `--lane`, and `imprint.py use` fills in one lane.
    - The unit runs the begin, the use and the sync, so every run has `use-started`, one at a time per imprint.
    - T 7's checks 2 and 5 no longer say "asked" (they cite I D41), and T 12's "Use ends (I2)" points to I 16's test.
  - **I3: provided** (I D29; sections 12, 16 and 18).
    - The unit carries `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` exactly when the default `runtime.json` names an
      absolute `embedder_socket`. No file, no key or `null` passes nothing. Any other value stops the use.
    - I 18 rests "never downloads a model" on T's `local_files_only=True` and names the cache.
    - sqlite-vec stays in the admission environment.
    - I's revision 5 adds the user manager's environment gate (CN2).
  - **I6: provided, with one gap found** (I 16, "Recall rows").
    - Both of T's assertions are there, on a fixture with `route` and a mixed-lane recall, with the pointer to T 12.
    - I's revision 4 added one condition: one `as_of` for both files.
    - The gap: T 4 counts a session closed when its newest row is an hour older than `as_of`, and ignores newer rows.
      With an `as_of` before the plan's end t₁, a session could be closed in the package, whose later rows stayed
      home, and open in the source. Then the package would have touches the source lacks, and the first assertion
      fails.
    - I ships only sessions closed at t₁ by a rule at least as strict as T's (row 16). So with `as_of` at or after
      t₁, every package session is closed in the source too, and both assertions hold.
    - I 16 now says "at or after the plan's end t₁", and T 11's I6 says why. This fixes a test and narrows nothing
      that leaves.
  - The section 11 intro says all six items are settled: five provided, I4 declined.
  - The header's "Builds on" now names P revision 5 (adding 7.6) and I revision 5, and says they "were written in
    parallel".
- **Section 7, "Calibration reads exactly that". Fixed.**
  - It now says "Calibration on a plain copy reads exactly that".
  - A new paragraph, "At admission, calibration reads no session path, with or without `route`", says I runs it
    with `no_paths`, since the owner's record for roads and trails names only `trail-evaluation` (I 8, 10). T reads
    nothing from calibration's `paths` section, so no rule of T's changes.
  - The "Without `route`" bullet no longer says admission's `paths.report` finds no session. It says what such a file
    gives: `paths.report` would find none (`engram/paths.py:349`, `:423`), and the survey counts no sessions and no
    log rows (`engram/store_reader.py:111-121`, `:126-131`). It quotes I's note "because route was not chosen".
  - T 11's I5 no longer cites the "31 session paths" example or "differs only in `paths`". It says I's example
    counts 57 sessions with "paths not measured at admission", and what the log-rows test compares.
  - T 7's paragraph on the old recall-row test now says I's revision 4 replaced it.
- **Section 7's citation of P 14. Fixed.** The known limit quotes "this narrows mistakes, not malice". The words are
  in P 7.6 (its "Known limits"), so T now cites 7.6.
- **Beyond the items.** T 7 step 10 names the use's `TimeoutStopSec=60` (I's CN1), so row 29 agrees in all three
  specs.
- **Revision tags.** The status line says revision 7. The revision history gains row 7, and row 6 now names
  `53c132a`.

## The interface table

- **Header.** Each spec's line names its latest revisions and the rows they updated. A paragraph names this pass.
- **Row 6.** I 8's owner who is the operator.
- **Row 8.** P's reviser's note (the bulk order of P 6.5 step 1), under "Permissions final-check pass". BS2's
  bound, under "Consolidation pass". The agreed rule now names the bound on named memories and the order.
- **Row 13.**
  - The agreed rule says "no log row's content" (CN3).
  - The note "For P's next revision" is marked applied, under "Permissions final-check pass".
  - The note "For T's next revision" is marked applied, with T's section 7 change, CN3's reason and CS1's test.
- **Row 14.** I6 provided, and the `as_of` gap.
- **Row 20.** BS3's fact and step-2 line. Still open with Andy.
- **Row 21.**
  - P's reviser's note (9.2's views of a refusal), under "Permissions final-check pass".
  - BS1, BN3 and BN4, and I 12's rows per bulk use, under "Consolidation pass".
  - The agreed rule says "one counted row per action per bulk use of at most 100,000".
- **Row 23.** T 7 and I 12 now cite P 7.6.
- **Row 24.** CS2 and CN1.
- **Row 27.** CN1, CN4, CN5, CN6, and T marking I2 provided.
- **Row 28.** CN2, and T marking I3 provided.
- **Row 29.**
  - P's reviser's note (the 40 s budget), under "Permissions final-check pass".
  - BS2's bound and the use's `TimeoutStopSec=60`, under "Consolidation pass".
  - The agreed rule names the named-memory bound, the 400,000 pairs and the 40 s.
- **"What changed, by spec."** It gains the line P's reviser proposed, "Permissions, final-check pass (revision 4;
  header, 6.4, 6.5, 7.6, 9.1, 9.2, 11, 12.2, 12.3, 13, 15, 16, 17): rows 8, 13, 21 and 29", and one line per spec for
  this pass. It now says nothing is pending in any spec.
- Rows 3 and 23's agreed rules are unchanged, as P's reviser said. Row 23 gained only the citation note.

## Declined

None. No item would let more leave a machine or widen a permission.

## Left open: not in this pass's list

I didn't decide these. Rio Grande may want them before the plan.

- **Recall and resonance times leave with the memories, and the owner isn't told.** T's final check FS2 and I's
  final check FN1 are the same point from two sides.
  - An episode ships `accessed_count` and `last_accessed`, and resonances ship without `route`.
  - Both tell when one recall returned memories together.
  - T 7's known limit names write times only.
  - I's dry run says "Without route, which session wrote each episode, and the recall log, would stay here too".
  - Telling the owner more lets nothing more leave, so either spec could take it.
  - It touches what I 5.4 and 8 show the owner, so it needs both specs to agree.
- **T's final check, FS1:** the offline test says "nothing is written to the cache directory", and fastembed 0.7.4
  makes `tmp/` there. **T's final check, FN1 to FN3:** wording, citations and wrap width. None crosses a spec.
- **I's check of revision 4:**
  - CN7's second half: no test that no use is finished while the imprint is `deleting`.
  - CN8: a withdrawal or station delete could stop `superyak-imprint-use-<imprint id>`, which only narrows.
- **Where the count of roads and trails comes from** (noticed, not changed; it predates this pass).
  - I 12's import writes `returned` = the count of roads and trails, and now ⌈N / 100,000⌉ rows.
  - The station's `use-started` and `use-finished` name objects only as `{imprint, count}`.
  - Admission decides its counted bulk `imprint` on R(I) by the finite check. It never derives R(I), so nothing
    computes N for admission.
  - A builder will need a rule. For example, the station could record N for the evaluation from `trails.py`'s
    counts. For admission, it could write the counted row with the count unknown.
  - Either is content-free. The choice is Rio Grande's.

## Still open with Andy (unchanged)

- **Memories that mention other people.** Whether they may move at all is still Andy's. This pass decides nothing
  about it.
  - Each spec keeps its default: P 7.4 and 19; I D27 and 20, the strictest, where no memory with a recorded
    co-subject leaves; T 14.
  - BS3 adds a fact to P 19, not a decision.
  - BS1 and BN3 only keep a refusal from naming a person's home to an agent.
- Also unchanged:
  - the license;
  - which store to imprint first, and its owner's yes;
  - whether the station-signed browser yes is enough for step 1, and whether the terminal yes is enough at home;
  - one permission an agent may set on its own;
  - what the county sets;
  - pseudonyms;
  - agent shares at home under `enforce`;
  - the two departures from principle 5;
  - who decides in the county steps.

## Code and system claims checked today

- `engram/store_reader.py:66-73` (`file_facts`), `:111-131` (row counts, `identity` at `:124`, distinct session ids
  at `:128-130`), `:156-174` (`survey` returns `{"file": facts, **body}`).
- `engram/calibrate.py:89` (`now = now or datetime.now(...)`), `:244-245` (`calibrate(..., now=None)`), `:258` (the
  survey), `:286` (`first_open` with `now`), `:295-296` (paths).
- `engram/sheaf.py:187`, `:298`, `:390`: clock reads outside calibration's path.
- `engram/paths.py:348-354` (only non-null session ids, ordered by session, time and id), `:418-426` (`report`).
- `scripts/runtime.py:84-88` (`embedder_socket`: None passes nothing; a non-string or relative path is an error),
  `:594-597` (`--config` defaults to `SUPERYAK_RUNTIME_CONFIG`, else the default path), `:653-655` (sets the
  variable).
- On the Pi: systemd 252 (252.39-1~deb12u2); `systemctl --user show -p DefaultTimeoutStopUSec` gives 1 min 30 s;
  `systemctl --user show-environment` lists no `ENGRAM_` variable; `~/.config/superyak/runtime.json` doesn't exist.
- P 6.1 (a layer kept outside a ledger; a consent layer is its allows less its denies), P 6.3 ("A layer that
  appears twice counts once"), P 7.6 ("this narrows mistakes, not malice"), T 4 ("As-of time", "Sessions", the
  512-touch cap), I 7.1 (`contents` holds the log tables' row counts).

## Checked after editing

- Every `## ` heading in each of the four edited files matches `git show HEAD:<file>` (a `diff` of `grep '^## '`,
  and of `grep '^#'`, against HEAD: no difference).
- Each file ends with a newline. Lines now: P 1,997, I 2,118, T 1,711, the table 118.
- Every added line outside a table is at most 120 characters.
- No "pending in the imprint spec" is left in T.

Not checked: I ran no engram or peer tests, since this pass changes specs only and no code.

## Cross-check, 2026-10-25

Reviewer: a fresh agent on the Pi (`smart`), checking the three specs as one set in Andy's place (station law section
3). I took no part in writing, reviewing, fixing or consolidating any of them. I read this log, `git diff HEAD` of the
three specs and the table, the reviews' items it answers (P's "Check of the follow-up revision (revision 4)", I's
"Check of revision 4"), and the parts of each spec those items touch. I checked code claims by reading the code today.
I edited no spec and not the table. I appended only this section. I committed, pushed and posted nothing.

VERDICT: APPROVE WITH CHANGES

Every item in this log is applied where it says. The files are whole. One must-fix is new in this pass (XM1, in I 8's
new paragraph): it is broken mathematics, though it fails closed and changes no step-1 verdict. Its fix is one
sentence in I 8 and one in row 6's note. With XM1 applied, nothing here blocks the plan. Nothing here decides whether
memories that mention other people may move at all.

### The files are complete

- Every `## ` heading, and every `#` heading, of P, I, T and the table matches `git show HEAD:<file>` (a `diff` of
  `grep`, no difference).
- Each file ends with a newline. P has 1,997 lines (1,952 + 69 − 24), I 2,118 (2,035 + 143 − 60), T 1,711
  (1,667 + 97 − 53), the table 118.
- Every added line outside a table is at most 120 characters. The edited table rows keep their column counts.
- The table's changed rows are exactly 6, 8, 13, 14, 20, 21, 23, 24, 27, 28 and 29, as this log says. It has 32 rows.

### The log's items

- **P.** BS1 (10, 18, U17), BS2 (6.4 "Named memories", "Refused" and "Its Pi budget"; 6.5 step 1; 9.1 item 3; 15;
  U22; U24; the header), BS3 (14 step 2; 19), BN1 to BN4 and the revision tags are all there as listed. 400,000 =
  3 × 100,000 + 100,000 is right, since a bulk use shows no content, so its named memories need only `recall`.
- **I.** CS1, CS2, CN1 to CN6, the 7.6 citation, the roads-and-trails rows and the revision tags are there. CN7's first
  half is in "Use ends". I 8's "When the owner is the operator" is there, but see XM1. I 16's `as_of` is there, but see
  XS1.
- **T.** I2, I3 and I6 are marked provided, and each part matches I as it stands (I D29, D41, 12, 16, 18). Section 7's
  "on a plain copy", its "At admission" paragraph, the "Without `route`" bullet, the 7.6 citation and step 10's
  `TimeoutStopSec=60` are there. T 11's I5 matches I 10's example: "57 sessions counted; paths not measured at
  admission" (I lines 1345-1346). No "pending" is left in T.

### Code and system claims checked today, all true

- `engram/store_reader.py:66-73` (`file_facts`: path, bytes, SHA-256), `:111-121` (every table's row count), `:124`
  (`identity`), `:126-131` (`COUNT(DISTINCT session_id)`, which skips nulls), `:174` (`{"file": facts, **body}`).
- `engram/calibrate.py:89` (`now or datetime.now`), `:244-245`, `:258`, `:286`, `:295-296`. No other part of
  calibration's path reads the clock or a log table: `first_open_preview` reads only `episodes` (`:90-92`),
  `persistence.generativity_scores` reads `resonances` (`engram/persistence.py:172-174`), and the three
  `datetime.now` calls in `engram/sheaf.py` (`:187`, `:298`, `:390`) are in `apply_subdivision`, `_rate_limited` and
  `run_sleep_pass`. The report's other keys (`migration`, `source_unchanged`) agree between two packages.
- `engram/paths.py:349` and `:423` (`WHERE session_id IS NOT NULL`).
- `scripts/runtime.py:84-88` (`None` passes nothing; a non-string or relative path is an error), `:594-597`
  (`SUPERYAK_RUNTIME_CONFIG`, else the default path), `:653-655`.
- On the Pi: systemd 252 (252.39-1~deb12u2); `DefaultTimeoutStopUSec=1min 30s`; `systemctl --user show-environment`
  lists no `ENGRAM_` variable; `~/.config/superyak/runtime.json` doesn't exist. systemd-run(1): the service type
  defaults to `simple`, so `RuntimeMaxSec` applies (systemd.service(5) says it doesn't for `oneshot`).

### The interface rows

I read all 32 rows against the three specs as they stand. Rows 1 to 5, 7, 9 to 12, 15 to 19, 22, 25, 26 and 30 to 32
are untouched by this pass and still hold (spot-checked: I D18's 365 days, P P13's 366; T's `#` and 8 hex; I D35;
T 4's instinct rule; T's `independent`). Of the touched rows:

- **Row 6** does not hold as written once the operator also owns an imprint here. See XM1.
- **Row 14**'s new note says that with `as_of` at or after t₁ "every package session is closed in the source too".
  That needs one more condition. See XS1.
- **Rows 8 and 21** hold in what they say. But I gives no source for N, the count of roads and trails their per-bulk-use
  rows need. See XS2.
- **Rows 13, 20, 23, 24, 27, 28 and 29** hold in all three specs.

### Privacy and permissions

Nothing more leaves a machine. No permission widens.

- BS1 and BN3 keep a refused `remember` from naming a person's home to an agent that doesn't act for the owner.
- BN4 shows an agent only the count or digest of its own bulk use, which its receipt already holds.
- CS2 adds an error class to a receipt, a name from the code and never a message.
- CN4 to CN6 change where the lane is filled in, what the caller is told, and a write order.
- XM1 is about a definition. It would refuse, never allow.

I found no agent that learns whose memory a refusal protected, and nothing about a person that moves without their
yes.

### Must-fix

**XM1. I 8's operator layer refuses every other owner's imprint** (I lines 979-993; row 6's consolidation note).

- **Why.** P 6.1 says a layer kept outside a ledger is one subset of 𝒰. In step 1 the operator's home layer is the
  ceiling ⟦c⟧ for every imprint (I line 948, "Why the station's check is the permissions spec's meet", lines 954-967).
  The new paragraph defines that same layer, when the owner is the operator, as ⟦L⟧ = (∪_J ⟦p_J⟧) ∩ ⟦c⟧, with J over
  the operator's own imprints. That set holds no use of another owner's copy, since the operator's records name his own
  store and collections.
- **Failure.** I 10's example has an imprint `c0a8` owned by `sam`, decided in `place:home/andy` (I lines 750,
  1345). Let Andy also imprint his own store. A use of `c0a8` has `Req` = {sam's home, Andy's home}. Under the new
  definition, Andy's home layer doesn't hold it, so P's meet is ∅ and P's `decide` refuses with `NO_ALLOW`. I's
  per-copy check allows it. So "the meet still equals I's per-copy check" (I 8; row 6) is false, and P U22's agreement
  test fails on a fixture with two owners, one of them the operator. It fails closed, and the station's code decides
  per copy, so no step-1 verdict changes. A step-2 `decide` built from this definition would refuse every other
  owner's imprint (I 17 step 1).
- **Fix** (Rio Grande's call). Define the one layer for every copy: ⟦L⟧ = ⟦c⟧ ∩ (∪_J ⟦p_J⟧ ∪ 𝒰_other), where
  𝒰_other is the uses of copies whose owner isn't the operator. Since ⟦c_I⟧ ⊆ ⟦p_I⟧ for every copy (I 8), that is just
  ⟦c⟧: at the station, the operator's own records add nothing, and the ceiling is never one more allow. Row 6's note
  says the same. No verdict changes.

### Should-fix

**XS1. The recall-row test's `as_of` needs one more condition** (I 16, "Recall rows", line 1875; T 11's I6, lines
1485-1489; row 14's consolidation note).

- **Why.** I 5.2 decides "closed at t₁" from rows before t₁ only, "so rows written after the plan can't change it" (I
  lines 346-351). So a source may hold a later row of a shipped session. That happens: engram's session id is Claude
  Code's `CLAUDE_CODE_SESSION_ID` (`engram/server.py:1320-1332`), which a resumed session keeps. T 4 counts a session
  open while its newest row up to `as_of` is within an hour of `as_of` (T lines 209-216).
- **Failure.** Session S is closed at t₁ and ships. It is resumed and writes an episode at r = t₁ + 2 h, which the
  package drops. With `as_of` = r + 10 min, which is after t₁, S is open in the source and closed in the package. The
  package has S's touches and the source has none, so the first assertion fails, and so does the second on S's kept
  rows.
- **Fix.** I 16 says the fixture's source holds no row at or after t₁ (then any `as_of` at or after t₁ works), or uses
  `as_of` = t₁ with no row at exactly t₁. T 11's I6 and row 14 drop "every package session is closed in the source
  too" or add the condition. It changes a test, not a rule.

**XS2. Nothing says where N comes from** (I 12, lines 1686-1689; P 9.1 item 3; rows 8 and 21). This log's "Left open"
names it, and it still blocks a builder.

- **Why.** P 6.4 splits a counted bulk use at 100,000 objects, and P 9.1 and I 12 then write ⌈N / 100,000⌉ rows with
  `returned` = each part's count. But admission decides R(I) by the finite check and never derives it (I 8), and the
  station's receipts name objects only as `{imprint, count}` (I line 1596).
- **Failure.** For an imprint whose R(I) holds 150,000 roads and trails, nothing can compute the split into 100,000
  and 50,000, or the two `returned` values, at the station or in `import-receipts`.
- **Fix** (Rio Grande's call). For example, admission counts R(I) from the package's session ids and log rows, a
  content-free count inside `Need(admission)`, and `admitted` and `use-finished` carry it. Or the import writes the
  count as unknown, and P 9.1 says that is allowed.

**XS3. Carried, unchanged: recall and resonance times leave, and the owner isn't told** (T's final check FS2; I's final
check FN1; this log's "Left open"). It lets nothing more leave to tell the owner, so it can wait for the plan. But
both specs should say it before the first live imprint.

### Nits

- **XN1. D41 overclaims** (I line 234, line 1498). An error before `imprint.py use` makes the use directory, such as
  an import error at start-up or an unreadable allow file, writes no `result.json` either. Rule 6 then reads it as a
  limit. Say so in rule 6, or say only refusals come before the directory.
- **XN2. The `ENGRAM_` gate holds only on the day it runs** (D29; I line 2086). A later `systemctl --user
  set-environment` would reach the unit. Passing `-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET` when there is no
  `--setenv` would make D29 hold always (systemd.exec(5) on the Pi). It must not be passed with `--setenv`, since it is
  applied last and would undo it.
- **XN3. U24's fixture should fix the trails' length** (P line 1931; P 6.4 "Its Pi budget"). Deciding a trail reads
  one `recall` per touch. 100,000 trails of 512 touches over 100,000 memories are 400,000 decisions but 51.2 million
  reads. Row 29's "the 40 s covers every bulk use" rests on U24 measuring that case. Latent: I decides by its finite
  check.
- **XN4. P 9.1 item 3** (P line 1137) says "one row for all of them" under the title "one counted row per bulk use".
  "One row for all of them in that bulk use" would read right.
- **XN5. Row 8's agreed rule** says every bulk use has "one counted receipt". A named bulk use's receipt names its
  batch (P 9.1 item 2). This predates this pass.
- **XN6. I 8's last sentence** (I line 992) says the same holds in a step-2 ledger, but not which item of P's `Req`
  holds the ceiling there when the owner is the operator. XM1's fix can say it, or leave it to P 14 step 2.

### Carried, not changed

I's CN7 second half and CN8. T's final check FS1 and FN1 to FN3. These are as this log's "Left open" says.

### Still open with Andy (unchanged)

- **Memories that mention other people.** Whether they may move at all is Andy's. Each spec keeps its default: P 7.4
  and 19; I D27 and 20, the strictest; T 14. BS3 adds a fact, not a decision. I decide nothing here.
- Also: the license; which store to imprint first, and its owner's yes; whether the station-signed browser yes is
  enough for step 1, and the terminal yes at home; one permission an agent may set on its own; what the county sets;
  pseudonyms; agent shares at home under `enforce`; the two departures from principle 5; who decides in the county
  steps.

Not checked: I ran no engram or peer tests, since nothing here changes code.

## Cross-check fixes, 2026-10-25

Author: a fresh agent on the Pi, applying the cross-check above as its sections describe. I edited the three specs
and the interface table with targeted edits only, and appended only this section here. I let nothing more leave a
machine and widened no permission. I decided nothing about whether memories that mention other people may move at
all. I committed nothing, pushed nothing, merged nothing, deployed nothing and posted nothing.

The specs after these fixes: P revision 6, I revision 6, T revision 8.

### Must-fix

- **XM1. Applied** (I 8, "When the owner is the operator"; row 6).
  - The ceiling is never one more allow. At the station the one home layer is the ceiling itself, ⟦c⟧, for every
    copy, whoever owns it.
  - The operator's own records add nothing there. Each ⟦c_J⟧ ⊆ ⟦p_J⟧ (I 8), and every other copy's ceiling lies in
    𝒰_other, so ⟦c⟧ ∩ (∪_J ⟦p_J⟧ ∪ 𝒰_other) = ⟦c⟧.
  - So the cross-check's case holds again. A use of sam's `c0a8` meets sam's layer and ⟦c⟧, which holds it, and P's
    meet equals I's per-copy check on a fixture with two owners, one of them the operator.
  - I 8 says what revision 5 defined and why it failed closed. The station's code and every verdict are unchanged.
  - Row 6's consolidation note is corrected in place and marked so.

### Should-fix

- **XS1. Applied** (I 16, "Recall rows"; T 11's I6; row 14).
  - The fixture's source holds no row at or after t₁, and `as_of` is at or after t₁. Or the test takes `as_of` = t₁,
    and the source holds no row at exactly t₁. Either way every package session is closed in the source too.
  - Why. I 5.2 decides "closed at t₁" from rows before t₁ only. Engram's session id is `CLAUDE_CODE_SESSION_ID`
    (`engram/server.py:1319-1332`), so a shipped session can write again later under that id. T 4 ignores rows newer
    than `as_of`, and counts a session open while its newest row is within an hour of `as_of`. So an `as_of` at such a
    later row, or less than an hour after it, finds the session open in the source.
  - T 11's I6 says so, and row 14's consolidation note is corrected in place. It changes a test, not a rule.
- **XS2. Applied as the item states it, with one step it needed** (Rio Grande's call; I D16, 8, 10, 12 and 16; P 6.4
  and 9.1 item 3; rows 8 and 21).
  - With `route`, once the checks pass, `imprint.py admit` derives R(I) in memory with the trail spec's functions, at
    `as_of` = t₁, the scope's `until`. It keeps only N, the number of roads and trails. Without `route`, N is 0.
  - At t₁ every session the package holds is closed (I 5.2), and no kept row is ignored, so a later `as_of` gives the
    same N.
  - `result.json` and the `admitted` receipt carry N as `roads_and_trails`. `use-started` and `use-finished` copy it
    from `admitted`, and so does `refused` once there is an `admitted` receipt.
  - The import reads N from the receipt and writes ⌈N / 100,000⌉ rows per action on roads and trails. An R(I) of
    150,000 gives `returned` 100,000 and 50,000.
  - **The step it needed.** Deriving R(I) reads memory text: T 4 makes a cited touch when a later same-session
    episode's `content` or `context` contains the target's id. Need(admission) had only `recall` on the memories for
    `trail-evaluation`. Its third set is now `recall` and `read` on the memories for `trail-evaluation`, as in
    Need(trail-evaluation). r_M lists `read` with purpose `trail-evaluation`, and C holds (read, trail-evaluation), so
    no permission widens, and only N leaves the run. I 8's bulk uses, I 12's uses table and P 6.4's last paragraph say
    so.
  - **An edge the item didn't name.** A use refused with `route` before admission counted R(I) read no road or trail,
    and its receipt has no N: a `denied` at approval, a `failed` naming a term at a run's start, or a `refused` before
    `admitted`. Its import writes one row per action on roads and trails, with `returned` null, and P 9.1 item 3 now
    allows that. This is the cross-check's second option, used only where no count exists.
  - A count names no id, digest or content. The station keeps it in its receipts until 400 days after deletion, as
    it keeps their `count` of memories, and it counts only roads and trails the owner's yes covers.
  - I 16 tests the count, the split and the null row.
- **XS3. Applied** (I 5.4 and 9; T 7).
  - The dry run's "What would leave" gains, in plain words: "With them, route or not: when each memory was written;
    how often and when last each episode was recalled; and the resonances, pairs of memories one recall returned
    together, with when. These show when memories were recalled together." Its "Without route" line gains "The times
    above would still leave."
  - The confirm view says the same, as a fixed line beside the closed actions.
  - The code, read today: each recall adds one to `accessed_count` and sets `last_accessed` on every episode it
    returns (`engram/server.py:2388-2391`; `engram/storage.py:627-638`), with a microsecond timestamp
    (`engram/storage.py:55-56`). It forms a resonance between results it returned together, keeping `created_at`,
    `last_seen` and `co_occurrences` (`engram/server.py:2488-2491`; `engram/storage.py:2001-2012`).
  - T 7's known limit names these beside write times, and says the imprint spec now tells the owner.
  - Telling lets nothing more leave. Nothing in what ships changes.

### Nits

- **XN1. Applied** (I D41 and 12, rule 6; row 24). An error in `imprint.py use` before it makes the use directory,
  such as an import error at start-up or an allow file it can't read, writes no `result.json`. Rule 6 reads it as a
  limit, and both places say so.
- **XN2. Not applied, carried.** Passing `-p UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET` when there is no `--setenv` is
  right: systemd.exec(5) on the Pi (systemd 252) says it is applied as the final step, so it must never go with
  `--setenv`. But it isn't quick. It changes the unit's command and its rule in I D29, 12, 16 and 18, in T 7 step 8.2
  and 11's I3, and in row 28, which all say "nothing otherwise". It also covers one variable, while I 18's gate checks
  every `ENGRAM_` one. The plan can take it.
- **XN3. Applied** (P U24; row 29). U24's fixture has trails of 512 touches each, the trail spec's cap, so the 40 s is
  measured where a decision reads 51.2 million touches.
- **XN4. Applied** (P 9.1 item 3): "one row for all of them in that bulk use".
- **XN5. Applied** (row 8's agreed rule): "one receipt, which names its batch of objects or holds their count".
- **XN6. Applied with XM1** (I 8; row 6). In a step-2 ledger the ceiling stays a term of the meet of its own, so a use
  of copy I is allowed only within ⟦c_I⟧ less the home's denies. Which item of P's `Req` holds it there is left to
  P 14 step 2.

### Revision tags

- P: the status line says revision 6 and lists these. The header names I revision 6 and T revision 8, and gains a
  revision 6 item in "Depended on by". 6.4 and 11 say trail spec revision 8.
- I: the status line says revision 6. The revision history gains row 6, and row 5 now names `ade420c`. The header
  cites P revision 6 and T revision 8.
- T: the status line says revision 8. The revision history gains row 8, and row 7 now names `ade420c`. The header
  cites P revision 6 and I revision 6.

### The interface table

- The header names each spec's new revision and the rows it updated, and a paragraph names these fixes.
- Row 6: the consolidation note corrected (XM1), and XN6.
- Row 8: XS2's count and Need(admission)'s `read`; XN5 in the agreed rule.
- Row 14: the consolidation note corrected (XS1), and the fix.
- Row 21: the agreed rule names `{imprint, count, roads_and_trails}` and where `returned` comes from; XS2 and XN4.
- Row 24: XN1. Row 29: XN3.
- "What changed, by spec" gains a "Cross-check fixes" entry. XS3 changes no row.

### Code and system claims checked today

- `engram/server.py:1319-1332`: the session id is `CLAUDE_CODE_SESSION_ID` under Claude Code, else a bound or random
  id.
- `engram/server.py:2388-2391` (access counts on episode results), `:2488-2491` (`_form_resonances`).
- `engram/storage.py:55-56` (`_now_iso`, microseconds), `:627-638` (`increment_episode_access`), `:2001-2012` (the
  resonance upsert).
- `engram/migrations/002_v3_layers.sql:5-6`: `accessed_count` and `last_accessed` are episode columns only.
- systemd.exec(5) on the Pi, systemd 252 (252.39-1~deb12u2): `UnsetEnvironment=` is applied last.
- Spec claims: T 2 (a road is a step with support ≥ 2, its section 5), T 4 ("As-of time", "Sessions", "Cited
  touches"), I 5.2 (closed at t₁), I 6.4 item 2, I 7.1 and 7.2 (`scope.until`), P 6.1 and 6.3.

### Checked after editing

- Every `## ` heading, and every `#` heading, in P, I, T and the table matches `git show HEAD:<file>` (a `diff` of
  `grep`, no difference). This file gains only this section.
- Each file ends with a newline. Lines now: P 2,013, I 2,190, T 1,733, the table 130.
- Every added line outside a table is at most 120 characters. Every table row keeps its column count.

Not checked: I ran no engram or peer tests, since nothing here changes code.

### Still open with Andy (unchanged)

- **Memories that mention other people.** Whether they may move at all is Andy's. Each spec keeps its default: P 7.4
  and 19; I D27 and 20, the strictest; T 14. These fixes decide nothing about it.
- Also: the license; which store to imprint first, and its owner's yes; whether the station-signed browser yes is
  enough for step 1, and the terminal yes at home; one permission an agent may set on its own; what the county sets;
  pseudonyms; agent shares at home under `enforce`; the two departures from principle 5; who decides in the county
  steps.

## Check of the cross-check fixes, 2026-10-25

Reviewer: a fresh agent on the Pi (`smart`), in Andy's place (station law section 3). I took no part in writing,
reviewing, fixing, consolidating or cross-checking these specs. I read the "Cross-check" and "Cross-check fixes"
sections above, `git diff HEAD` of P, I, T and the table, and the parts of each spec those touch. I checked code
claims by reading the code today. I edited no spec and not the table. I appended only this section. I committed,
pushed, merged, deployed and posted nothing.

VERDICT: APPROVE

XM1 and XS1 to XS3 are resolved. No must-fix is left, and the fixes add none. One should-fix is new (YS1): the XS3
lines say wrongly how recall forms resonances, so the owner's words say a little less than what leaves. It lets
nothing more leave. Fix it before the first live imprint, the gate XS3 already had. The rest are nits. Nothing here
decides whether memories that mention other people may move at all.

### The files are complete

- Every `## ` heading, and every `#` heading, of P, I, T and the table matches `git show HEAD:<file>` (a `diff` of
  `grep`, no difference). This file differs from HEAD only by the "Cross-check fixes" section and this one.
- Each file ends with a newline, and each one's last five lines match HEAD's. Lines: P 2,013, I 2,190, T 1,733, the
  table 130, as the fixes say.
- Every added line outside a table is at most 120 characters. Every edited table keeps its column count: the
  table's 32 rows, I's decisions, revision history, uses and receipts tables, and T's revision history.

### The four items

- **XM1. Resolved** (I lines 1001-1024; row 6). The one home layer is ⟦c⟧ for every copy. The identity
  ⟦c⟧ ∩ (∪_J ⟦p_J⟧ ∪ 𝒰_other) = ⟦c⟧ holds. ⟦c⟧ is the union of the ⟦c_K⟧. Each of the operator's own lies in its
  ⟦p_K⟧ (I 8, "Every u in ⟦c_I⟧ is in ⟦p_I⟧"). Each other one lies in 𝒰_other, since item 1 names its h.
  - The cross-check's case now works. A use of sam's `c0a8` has `Req` = {sam's layer, ⟦c⟧}. It is in ⟦c⟧ only
    through ⟦c_c0a8⟧, which lies in sam's ⟦p⟧. So the meet on that copy is ⟦c_c0a8⟧, I's per-copy check.
  - For Andy's own copy I, `Req` is ⟦c⟧ alone, and the meet on that copy is again ⟦c_I⟧. The ceiling still narrows
    after a ship's withdrawal, since the owner's records are no allow of their own there.
  - No text in the four files still gives revision 5's definition as current (`grep`). XN6's step-2 paragraph
    defers to P 14 step 2 and claims nothing P lacks.
- **XS1. Resolved** (I 16, lines 1931-1945; T 11's I6, lines 1502-1510; row 14). Both fixtures work.
  - I 5.2 calls a session closed at t₁ when its newest row before t₁ is older than t₁ − 3,600, over every log kind
    (I lines 356-360). T 4 calls it closed when its newest row up to `as_of` is older than `as_of` − 3,600, over
    fewer kinds (T lines 212-225). So I's closed at t₁ gives T's closed at `as_of` = t₁.
  - With no source row at or after t₁, a shipped session's newest source row is the same at any `as_of` ≥ t₁, so it
    stays closed. With `as_of` = t₁, T ignores rows after t₁, and no row sits at exactly t₁, so it is closed too.
  - The package's rows are then a subset of the source's, filtered the same way, and both assertions hold. The code
    claim is true (`engram/server.py:1319-1332`). A session idle for over an hour that writes again after t₁ is
    enough, with or without a resume.
- **XS2. Resolved** (I D16, 8, 10, 12 and 16; P 6.4 and 9.1 item 3; rows 8 and 21). N now has a source.
  - Admission derives R(I) at `as_of` = t₁ and keeps only the count, and the receipts carry it. At t₁ every package
    session is closed (as under XS1), and no package row is newer than t₁. So a later `as_of` gives the same N.
  - The split is right: ⌈150,000 / 100,000⌉ = 2 rows, `returned` 100,000 and 50,000.
  - The added `read` on the memories for `trail-evaluation` is needed: T 4's cited touches read an episode's
    `content` and `context` (T line 234). It widens nothing. r_M's actions and purposes give (read, trail-evaluation)
    (I line 870), and so does C (I lines 956-958). P 6.4's last paragraph and I 12's uses table say the same.
  - Only a count leaves. It names no id, and the station keeps it as it already keeps the memories' `count`.
- **XS3. Resolved in substance, with YS1** (I 5.4, lines 466-468, 475 and 513-519; I 9, lines 1154-1156; T 7, lines
  969-976). The dry run and the confirm view now tell the owner that write times, access counts, last-access times
  and resonances leave, with or without `route`. Telling lets nothing more leave. The access-count claim is true.
  The resonance claim is not (YS1).

The nits the fixes applied (XN1, XN3 to XN6) are where the log says. 51.2 million = 100,000 × 512, and 400,000 =
3 × 100,000 + 100,000. XN2 is carried, with a reason that holds.

### Code and system claims checked today

- True: `engram/server.py:1319-1332` (the session id is `CLAUDE_CODE_SESSION_ID` under Claude Code, else a bound or
  random id); `:2388-2391` (each episode result's access count; `:2466` does the same for uninvited episodes);
  `:2488-2491` (the call to `_form_resonances`, imported from `resonance.py` at `:24-26`).
- True: `engram/storage.py:55-56` (`_now_iso`, with microseconds), `:627-638` (`increment_episode_access`),
  `:2001-2012` (the upsert raises `co_occurrences` and sets `last_seen`).
- True: `engram/migrations/002_v3_layers.sql:5-6` (`accessed_count` and `last_accessed` are episode columns), and
  `012_resonances.sql` gives resonances no session column, so T 7's "no record names a session" holds.
- True: the Pi runs systemd 252 (252.39-1~deb12u2), and its systemd.exec(5) says `UnsetEnvironment=` "is applied as
  final step".
- Not as written: "forms a resonance between results it returned together" (YS1).

### Privacy and permissions

Nothing more leaves a machine, and no permission widens. N is a content-free count of what the owner's yes covers.
Admission's new `read` is inside r_M and C. XM1's fix changes a definition and no verdict. XS3 tells the owner more.
I found nothing about a person that moves without their yes.

### Must-fix

None.

### Should-fix

**YS1. The XS3 lines misstate how recall forms resonances** (I lines 467-468, 516-517 and 1155-1156; T lines
971-973; this log's XS3 fix).

- **Why.** `_form_resonances` is `resonance.form_resonances` (`engram/resonance.py:42-85`). It computes PMI over
  every recall row in `memory_log` (`:52-58`; `engram/storage.py:2206-2229`). Then it upserts every pair with
  PMI > 0 that has at least one member in this recall's results (`:68`, `:74`, `:81-82`). So each pair was returned
  together by some recall. But `last_seen` is the latest recall that returned either one, and `co_occurrences`
  counts those recalls, not joint returns.
- **Failure.** Semantic s and episode e form a resonance. Later a recall returns s alone. The pair's `last_seen`
  moves to that time, so the copy shows when s was last recalled. The owner was told that only episodes keep a last
  recall time, and that resonances keep when a pair was recalled together.
- **Fix.** Say that each recall updates every resonance with one of its results in it, once the pair has been
  returned together. In the owner's words, for example: "Resonances, pairs of memories recalls returned together,
  keep when they formed and when either was last recalled." While there: `last_accessed` also moves when an episode
  leaves core (`engram/storage.py:987-1012`, from the `unmark_core` tools, `engram/server.py:3098`, `:3112`), so
  "when last it was recalled" is nearly, not exactly, true. A builder's note covers it.

### Nits

- **YN1. N can exceed what an evaluation derives.** The use runs `trails.py` with no `--as-of` (I line 1506), so its
  `as_of` is the copy's newest row (T line 1017), before t₁. Sessions in that last hour are open then and get no
  trail, and the run covers one lane. Its receipts still carry N. That matches `Need(trail-evaluation)`, which names
  all of R(I), and it only over-reports. Say N is R(I) as `Need` names it, or pass `--as-of` = t₁ to the use, which
  would also end T 7's "which of the newest sessions count as closed can differ".
- **YN2. One imported receipt is in neither list.** "Ended during admission" writes a `failed` receipt naming the
  effective end (I 10, "Deletion and the end win"). It is imported (I line 1729). It is not "at a run's start", so
  I 12's null list (I lines 1745-1748) misses it, and it may come after the count. Say "every imported receipt with
  no N". I 16's use-list test should say a `denied` receipt "naming a failing term", since only those are imported.
- **YN3. `until` may be null in the request** (I line 1854), but the count reads `as_of` = the scope's `until`. 5.2
  always gives t₁ a value. Require `until`, or say what admission does without it.
- **YN4. The count has no failure path of its own.** "Any failure writes `result.json` with `failed`, the check's
  number" (I line 1389), but the count is no numbered check, and it shares the admission unit's 1,800 s with
  calibration. Name its result. Calibration has the same gap today.
- **YN5. T doesn't say that admission now derives trails.** T 7's "At admission, calibration reads no session path"
  is still true. But I 10 now calls T's pure functions on an imprint, outside the CLI's imprint check (T 11's
  `trails.py` row). One sentence in T 7 would keep a builder from putting that check into the shared functions.
- **YN6. P 9.1 item 1 says "three for an admission"** (P line 1143). `uses.purpose` is NOT NULL (P line 1109), so a
  row is per action and purpose. With `route`, an admission has `recall` and `read` for two purposes, and three
  actions on roads and trails. I 16's "3 rows per memory action" (I line 2099) reads the same way. Say "per action
  and purpose".
- **YN7. One boundary.** T 11's I6 (T line 1507) and this log's XS1 fix say "less than an hour after it". T 4 keeps
  a session open while its newest row is not older than `as_of` − 3,600, so "at most an hour" is exact. Row 14's
  "within an hour" is right.

### Carried, not changed

XN2, as the fixes say. The cross-check's own "Carried, not changed" items.

### Still open with Andy (unchanged)

- **Memories that mention other people.** Whether they may move at all is Andy's. Each spec keeps its default: P 7.4
  and 19; I D27 and 20, the strictest; T 14. No added line in this pass mentions it (`grep`). I decide nothing here.
- Also: the license; which store to imprint first, and its owner's yes; whether the station-signed browser yes is
  enough for step 1, and the terminal yes at home; one permission an agent may set on its own; what the county sets;
  pseudonyms; agent shares at home under `enforce`; the two departures from principle 5; who decides in the county
  steps.

Not checked: I ran no engram or peer tests, since nothing here changes code.
