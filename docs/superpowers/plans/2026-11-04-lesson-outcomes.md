# Lesson outcomes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ship shown a lesson can say once, against its receipt, whether the lesson helped, misled or went unused, and
the peer lists those outcomes with section 5's counts.

**Architecture:** One new table beside the first rail's receipts, one verb on the peer's `lessons` module (the ship is
derived as `lessons repeat` derives it), the receipt's short id carried in the query's answer, and the agent's lessons
hook showing that short id next to each lesson. No federation, no free text.

**Tech Stack:** Python 3 (the peer's and the agent's own venvs), SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-lesson-outcomes-design.md` (revision 3, approved, 5a5748f4).

**Branch:** `build-lesson-outcomes`, worktree `/home/andy/superyak/.worktrees/lesson-outcomes-build`, from main
bb90cb4d with the spec merged in (13fc91dc).

## Scope: sections 2, 3 and 5 now; section 4 waits

Ruling (Rio Grande, 2026-11-04): this plan builds the outcome (section 2), the verb and the receipt short id (section
3), and section 5's counts that need no weight. **Section 4 (the weight and its shadow columns) is not built.** Why:
receipts and outcomes are local to each peer (sections 3 and 6), and the first rail's section 3 lets each peer hold at
most one ship in the lessons room (`REPEAT_SHIPS` in lessons.py refuses more). So on every peer the number of judges `n`
is at most 1, and section 4's 2-judge minimum keeps the weight off everywhere. A shadow built now would read
`reordered = 0` forever. Section 4 comes back in a spec revision that says where a second judge comes from: a signed
outcome summary across peers (section 6's "its own spec"), or several ships on one peer, as on the cluster. If this
ruling is wrong, the cost is that section 4 gets built later, on top of this table, with nothing here undone.

## Global Constraints

- The table is exactly the spec's: `lesson_outcomes(id TEXT PRIMARY KEY, created REAL NOT NULL, receipt_id TEXT NOT
  NULL UNIQUE REFERENCES lesson_receipts(id), outcome TEXT NOT NULL CHECK(outcome IN ('helped','misled','unused')))`.
- No free text anywhere: no note, no command, no context. The ship and the lesson come from the receipt.
- Every refusal names its rule, never the value typed, and writes nothing (as `lessons repeat`'s refusals do).
- One outcome per receipt, within 24 hours of the receipt: `OUTCOME_SECONDS = 86_400`, and an age of exactly 86,400 s is
  still in.
- A receipt id is 32 lowercase hex characters, or a prefix of at least 6 that matches exactly one of the ship's receipts:
  `RECEIPT_PREFIX = re.compile(r'[0-9a-f]{6,32}')`.
- The receipt short id is its first 8 characters: `RECEIPT_SHORT = 8`.
- Outcomes never federate and are never written by the hook.
- Commit messages end with "Made by Rio Grande." and the Co-Authored-By line. Peer tests run from the worktree's
  `peer/` with `/home/andy/superyak/peer/.venv/bin/python -m pytest … -q -p no:cacheprovider`. Agent tests run from
  `agent/` with `/home/andy/superyak/agent/.venv/bin/python`. Both import the worktree's code from there.

## Review Focus

1. A receipt id typed in uppercase is refused with `OUTCOME_ID`. Lowercase only, as `REPEAT_ID` is (Task 1).
2. The 24-hour edge: an age of exactly 86,400 s is accepted, and 86,401 s is refused (Task 1).
3. A receipt whose lesson was retracted after it was shown still takes its outcome, since the measure counts it (Task 1).
4. Two outcomes racing for one receipt: the UNIQUE constraint's `sqlite3.IntegrityError` becomes the same 409
   `OUTCOME_TWICE`, never a traceback (Task 1).
5. An answer whose `receipt` is malformed reaches the hook: the hook drops that key and still shows the lesson (Task 3).

---

### Task 1: The outcome table, the verb and the list

**Files:**
- Modify: `peer/superyak_peer/lessons.py`, for `LESSON_SCHEMA` (~:1440), the constants near `REPEAT_*` (~:90-106), the
  `Lessons` methods beside `lesson_repeat` (~:1330-1392), `describe_outcomes` beside `describe_repeats` (~:872), and the
  verbs beside `_repeat` and `_repeats` (~:1586-1595) with `main()`'s extra-argument check (~:1491).
- Modify: `Makefile`: `.PHONY`, the help lines after `lesson-repeats` (~:119), and the targets after `lesson-repeats`
  (~:512).
- Modify: `peer/README.md`, in its lessons section next to `lesson-repeat`.
- Create: `peer/tests/test_lessons_outcomes.py`.

**Interfaces:**
- Produces: `OUTCOMES = ('helped', 'misled', 'unused')`, `OUTCOME_SECONDS`, `RECEIPT_PREFIX`, `RECEIPT_SHORT`.
- Produces: `Lessons._lessons_ship(self, db, refusals) -> str`. This is the ship derivation lifted out of
  `lesson_repeat` unchanged (the record's ship on the origin, else the one ship account in the room). It raises
  `Problem(404, 'No lessons room is recorded on this peer')` and `Problem(409, refusals[k])`, where `refusals =
  (no_ship, ships, not_member)`. `lesson_repeat` calls it with `(REPEAT_NO_SHIP, REPEAT_SHIPS, REPEAT_NOT_MEMBER)` and
  keeps every message and test it has.
- Produces: `Lessons.lesson_outcome(self, receipt: str, outcome: str) -> dict`, with keys `id, created, ship,
  receipt_id, short, outcome` (`short` is the lesson's short id).
- Produces: `Lessons.lesson_outcomes(self, limit=50) -> tuple[list[dict], dict]`. The rows are newest first, each with
  `id, created, ship, receipt_id, lesson_id, outcome`. The counts are `receipts, outcomes, helped, misled, unused,
  queries, verified_repeats`, over the whole peer.
- Produces: `describe_outcomes(rows, counts) -> str`.

The exact refusal words (new constants):
```python
OUTCOME_WORD = 'Say what the lesson did: helped, misled or unused'
OUTCOME_ID = 'Name the receipt by its full id (32 hex) or a prefix of at least 6, in lowercase'
OUTCOME_UNKNOWN = 'No receipt of this ship on this peer matches that id'
OUTCOME_AMBIGUOUS = "That prefix matches more than one of this ship's receipts; give more of it"
OUTCOME_TWICE = 'That receipt already has its outcome; a ship changes its mind only through a later receipt'
OUTCOME_LATE = 'That receipt is more than 24 hours old, so it takes no outcome'
OUTCOME_NO_SHIP = ('No ship account on this peer is a member of the lessons room, so there is no ship to record an '
                   "outcome for: the ship is this peer's one ship account in the room, never an argument")
OUTCOME_SHIPS = ('More than one ship account on this peer is a member of the lessons room, so the ship is unknown: the '
                 "ship is this peer's one ship account in the room, never an argument")
OUTCOME_NOT_MEMBER = "This peer's recorded ship is not a member of the lessons room, so it records no outcome here"
```

- [ ] **Step 1: Write the failing tests** in `peer/tests/test_lessons_outcomes.py`. Use `lessons_station` and
  `lessons_peers` from conftest. Take `shown_to`, `receipts` and the lesson bodies (`HASHES`, `GLOBS`) the way
  test_lessons_repeats.py defines them. Each test also checks that the outcomes table is unchanged after a refusal.
  - `test_the_outcomes_table_has_only_the_specs_columns_and_refuses_anything_else_even_by_raw_sql`: columns are `['id',
    'created', 'receipt_id', 'outcome']`; raw inserts of `'great'`, a NULL outcome, a second row for one receipt, and
    an unknown `receipt_id` (with foreign keys on) all raise `sqlite3.IntegrityError`.
  - `test_an_outcome_against_this_ships_receipt_is_recorded_by_full_id_and_by_prefix`: one receipt is shown, and
    `lesson_outcome(<full id>, 'helped')` returns `outcome == 'helped'`, `receipt_id ==` the receipt's id, the ship's
    username, and the lesson's short id. A second receipt is recorded by its first 6 characters, and a third by its
    first 8.
  - `test_each_refusal_names_its_rule_echoes_nothing_and_writes_nothing`, parametrized over:
    - an outcome outside the three words (`'great'`, `'Helped'`, `''`) → `OUTCOME_WORD`, 400;
    - a prefix of 5 → `OUTCOME_ID`, 400;
    - uppercase hex → `OUTCOME_ID`, 400;
    - 33 hex → `OUTCOME_ID`, 400;
    - an unknown prefix → `OUTCOME_UNKNOWN`, 404;
    - another ship's receipt → `OUTCOME_UNKNOWN`, 404;
    - a prefix two of the ship's receipts share → `OUTCOME_AMBIGUOUS`, 409;
    - a second outcome → `OUTCOME_TWICE`, 409;
    - an age of 86,401 s → `OUTCOME_LATE`, 409.

    In each case, `str(problem)` does not contain the typed value.
  - `test_another_ships_receipt_is_refused`: use `lessons_peers`, with a receipt written for the other peer's ship.
    Insert it directly if the fixture can't produce one, and say so in a comment.
  - `test_an_age_of_exactly_24_hours_is_accepted` (Review Focus 2).
  - `test_a_retracted_lessons_receipt_still_takes_its_outcome` (Review Focus 3).
  - `test_a_race_for_one_receipt_is_refused_as_a_second_outcome`: monkeypatch so the row appears between the check and
    the insert (for example, wrap the transaction's `execute` to insert first), then assert `Problem` 409
    `OUTCOME_TWICE` (Review Focus 4).
  - `test_the_ship_is_derived_as_for_repeats`: with no ship in the room, `OUTCOME_NO_SHIP`; on a peer with two, 
    `OUTCOME_SHIPS`; a recorded ship that isn't a member, `OUTCOME_NOT_MEMBER`. Build each state the way
    test_lessons_repeats.py's ship tests do.
  - `test_outcomes_list_newest_first_with_ids_ship_lesson_and_outcome_and_section_5s_counts_and_no_text`: two outcomes
    and one verified repeat. Check `describe_outcomes` word for word, as shown in Step 3, and check that neither the
    claim nor the why of either lesson appears in it.
  - `test_the_verbs_run_through_the_cli`: `run_lessons('outcome', '--data-dir', D, <id>, 'helped')` exits 0 and prints
    `Recorded outcome`. An extra argument exits 2 with `lessons outcome takes one receipt id and one outcome, and nothing
    else`. `run_lessons('outcomes', '--data-dir', D)` prints the list.

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && /home/andy/superyak/peer/.venv/bin/python -m pytest tests/test_lessons_outcomes.py -q -p no:cacheprovider`
Expected: FAIL (`lesson_outcome` and the table don't exist).

- [ ] **Step 3: Implement.**
  - Add the table to `LESSON_SCHEMA`, word for word from Global Constraints. An existing store gains it on open, since
    the schema is `CREATE TABLE IF NOT EXISTS`.
  - Lift `_lessons_ship` out of `lesson_repeat`.
  - `lesson_outcome` checks, in order, with no store read before the first two:
    1. the word, against `OUTCOMES`;
    2. the id, by `RECEIPT_PREFIX.fullmatch`;
    3. then, in one transaction: the ship, by `_lessons_ship`;
    4. this ship's receipts with `substr(id, 1, ?) = ?`, where 0 matches → `OUTCOME_UNKNOWN` and more than 1 →
       `OUTCOME_AMBIGUOUS`;
    5. an existing outcome → `OUTCOME_TWICE`;
    6. `self.clock() - receipt.created > OUTCOME_SECONDS` → `OUTCOME_LATE`;
    7. then the insert, with `uid()` and `self.clock()`.

    Map `sqlite3.IntegrityError` from the insert to `Problem(409, OUTCOME_TWICE)`.
  - `lesson_outcomes` joins `lesson_receipts` and `users` to get each row's ship and lesson. Clamp the limit as
    `lesson_repeats` does.
  - `describe_outcomes` prints `No outcomes on this peer yet.` when there are no rows. Otherwise it prints one line per
    row, then the counts line:
    ```
    <outcome id[:8]>  <ship>  lesson <lesson short id>  receipt <receipt id[:8]>  <outcome>
    Coverage: <o> outcomes on <r> receipts. Helped <h>, misled <m>, unused <u>. Verified repeats: <v> in <q> queries (<rate> per 100).
    ```
    `<rate>` is `f'{100 * v / q:.1f}'`, or `-` when `q == 0`. The counts line comes after the rows even when the list
    is cut at `limit`, and its counts are always the whole peer's.
  - Add the verbs:
    - `@verb('outcome', 'Section 3: say once, within 24 h, whether a lesson shown to this peer's ship helped, misled or went unused', ('receipt', {}), ('outcome', {}))`,
      which prints `Recorded outcome <id[:8]>: <ship>, lesson <short>, receipt <receipt_id[:8]>, <outcome>.`;
    - `@verb('outcomes', "Section 3: this peer's outcome records, newest first, with section 5's counts", ('--limit', {'type': int, 'default': 50}))`.

    `main()` gains the `outcome` case beside `repeat`'s, with the exit-2 words above.
  - Makefile:
    - `lesson-outcome` requires `RECEIPT` and `OUTCOME`. Its usage line is `Usage: make lesson-outcome
      RECEIPT=<receipt id or a prefix of 6+> OUTCOME=helped|misled|unused [LESSONS_DATA=…]`, and it runs `$(LESSONS)
      outcome --data-dir "$(LESSONS_DATA)" "$(RECEIPT)" "$(OUTCOME)"`.
    - `lesson-outcomes` runs `$(LESSONS) outcomes --data-dir "$(LESSONS_DATA)"`.
    - Help lines: `make lesson-outcome RECEIPT=… OUTCOME=helped|misled|unused  Say once whether a lesson shown to
      this peer's ship helped` and `make lesson-outcomes    This peer's outcomes, newest first, with the rail's
      counts`.
  - Put the same two lines in peer/README.md, next to `lesson-repeat`.

- [ ] **Step 4: Run the new tests, then every lessons test**

Run: `cd peer && /home/andy/superyak/peer/.venv/bin/python -m pytest tests/test_lessons_outcomes.py tests/test_lessons_repeats.py tests/test_lessons.py tests/test_lessons_index.py tests/test_lessons_room.py -q -p no:cacheprovider`
Expected: all pass. Repeats' tests are unchanged.

- [ ] **Step 5: Commit**: `lessons: an outcome per receipt (helped, misled or unused, once, within 24 h), the verb and its list with section 5's counts; the ship derived as for repeats. Made by Rio Grande.`

### Task 2: The answer names each lesson's receipt

**Files:**
- Modify: `peer/superyak_peer/lessons.py`: `shown()` (~:534) and `Lessons._lessons_answer` (~:1259-1305).
- Modify: `peer/tests/test_lessons.py` or `peer/tests/test_lessons_outcomes.py`, whichever holds the answer's word-for-word tests (keep them together).

**Interfaces:**
- Consumes: `RECEIPT_SHORT` (Task 1).
- Produces: `shown(item, match, command=None, receipt=None)`. When `receipt` is given, the entry gains a last key,
  `receipt`, after `command` when there is one. The answer of the query's step 4 gives every lesson it shows a
  `receipt`: the first 8 characters of the receipt row written for it. The prompt path never passes `receipt`.

- [ ] **Step 1: Write the failing tests.**
  - `test_each_lesson_in_the_answer_names_its_receipts_short_id`: one words query, then one Near query (with
    `fake_embedder`), each showing two lessons. Each entry's keys are exactly `['id', 'ship', 'claim', 'why', 'match',
    'receipt']`, or `[..., 'command', 'receipt']` for a command match. The set of `entry['receipt']` equals the set of
    `id[:8]` over the receipt rows that query wrote.
  - `test_a_lesson_the_fit_drops_has_no_receipt_and_its_id_is_never_written`: lessons sized so the 2,000-byte fit drops
    the third. Two receipt rows are written, and both match the answer.
  - `test_the_prompt_path_names_no_receipt`: `answer_prompt` entries have no `receipt` key, and no receipt row is
    written. The existing prompt-path tests stay as they are.
  - Update the existing word-for-word answer tests, adding the `receipt` key with the value read back from the
    receipts table. Change nothing else in them.

- [ ] **Step 2: Run them to see them fail.**

Run: `cd peer && /home/andy/superyak/peer/.venv/bin/python -m pytest tests/test_lessons.py tests/test_lessons_outcomes.py -q -p no:cacheprovider`
Expected: the new tests FAIL (no `receipt` key).

- [ ] **Step 3: Implement.** In `_lessons_answer`, draw each kept lesson's receipt id (`uid()`) before `fit`, build its
  entry with `receipt=key[:RECEIPT_SHORT]`, and after the deadline check insert receipts only for the entries in the
  answer, each with the id drawn for it. The fit counts the receipt's bytes, so near the 2,000-byte cap a third lesson
  can fit less often. That is accepted, and the commit message says it.

- [ ] **Step 4: Run every lessons test, the hold contract and the timing test**

Run: `cd peer && /home/andy/superyak/peer/.venv/bin/python -m pytest tests/test_lessons.py tests/test_lessons_outcomes.py tests/test_lessons_repeats.py tests/test_lessons_index.py tests/test_lessons_room.py tests/test_lessons_hold_contract.py tests/test_lessons_tool_holds.py tests/test_lessons_timing.py -q -p no:cacheprovider`
Expected: all pass. test_lessons_hold_contract.py's timing flakes under load are known (150 ms hook budget). Rerun a flake
once by itself before calling it real.

- [ ] **Step 5: Commit**: `lessons: the query's answer names each lesson's receipt short id (its first 8), drawn before the fit so the answer and the receipts agree; the prompt path names none. Made by Rio Grande.`

### Task 3: The hook shows the receipt

**Files:**
- Modify: `agent/superyak_agent/lessons_hook.py`: `_checked` (~:169), `render` (~:220) and `hold_reason` (~:225).
- Modify: `agent/tests/test_lessons_hook.py` and `agent/tests/lessons_stub.py`, if the stub builds answers.

**Interfaces:**
- Consumes: the answer's `receipt` key (Task 2): 8 lowercase hex.
- Produces: `RECEIPT = re.compile(r'[0-9a-f]{8}')`, and `receipt_line(r) -> str`, which returns
  `f'Receipt {r}: make lesson-outcome RECEIPT={r} OUTCOME=helped|misled|unused'`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_good_answer_keeps_each_lessons_receipt`: `check_answer` keeps `receipt` when it matches `RECEIPT`.
  - `test_a_malformed_receipt_is_dropped_and_the_lesson_still_shown`, parametrized over `'ABCDEF01'`, `'abc'`, `7`,
    `'0123456789'` and `'zz000000'`: the lesson is kept, with no `receipt` key (Review Focus 5).
  - `test_render_word_for_word_with_a_receipt`: `render([lesson with receipt])` is `HEADING`, then `Lesson <id> from
    <ship>`, its fence, and `receipt_line(r)` on the line after the fence. A lesson without a receipt renders exactly as
    today.
  - Add to `test_the_hold_reason_word_for_word` a case with a receipt: the block ends with `'\n' + receipt_line(r)`
    after the fence. The two existing cases stay unchanged.
  - `test_the_transcript_reads_ids_back_from_output_with_receipt_lines`: a transcript record holding `render()` output
    with receipt lines gives the same ids from `transcript_ids` as one without.

- [ ] **Step 2: Run them to see them fail.**

Run: `cd agent && /home/andy/superyak/agent/.venv/bin/python -m pytest tests/test_lessons_hook.py -q -p no:cacheprovider`
Expected: the new tests FAIL.

- [ ] **Step 3: Implement.** In `_checked`, copy `receipt` into `found` only when it is a `str` that matches `RECEIPT`
  in full. Have `render` and `hold_reason` append `'\n' + receipt_line(...)` after the fence when a lesson has one.

- [ ] **Step 4: Run the hook's tests and the holds'**

Run: `cd agent && /home/andy/superyak/agent/.venv/bin/python -m pytest tests/test_lessons_hook.py tests/test_lessons_hold.py -q -p no:cacheprovider`
(`ls agent/tests | grep -i hold` lists the hold tests. Run each one.)
Expected: all pass.

- [ ] **Step 5: Commit**: `lessons hook: each lesson shown with a receipt names it on the line after its fence, with the make line that records its outcome; a malformed receipt is dropped and the lesson still shown. Made by Rio Grande.`

## After the tasks

- A fresh Pi reviewer reads the whole branch (law section 2). Its verdict is saved to a file the moment it lands and
  posted whole.
- The peer and agent suites pass on the Pi.
- The branch rides a train with `make merge-sitting`. It isn't safety code (it writes ids, times and one of three words),
  so it needs no partner yes. Tardis's T1 blind test needs it, so Tardis is told when it lands.
- Board: close `build:rail-lesson-outcomes` with the merge. Post `spec:lesson-outcome-weight-judges` for section 4's
  revision (where a second judge comes from).
