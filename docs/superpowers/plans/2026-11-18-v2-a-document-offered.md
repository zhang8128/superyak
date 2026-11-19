# A document offered: the build

> For the workers who build it. The spec is `docs/superpowers/specs/2026-11-18-v2-a-document-offered.md`
> (revision 4). This plan fixes the files, the names and what passes between the parts. Where the spec
> and this plan differ, the spec holds and you say so.

**Goal:** scripts that make the pilot's frozen plan, run its 96 rows one at a time, and judge them, with
no change to the room.

**Shape:** three programs over one directory. The maker writes `plan.json` and the bases. The runner
runs the next row that has no record. The judge makes the controls, scores every row against cases
frozen from the reference, and prints the report's tables. Each stage refuses a plan whose hash or
inputs have changed.

**Tools:** Python, standard library only, parsing under Python 3.9
(`ast.parse(..., feature_version=(3, 9))`). Tests are `unittest` scripts run as
`python3 -I v2/probes/documents/test_*.py`. Reuse `v2/probes/items/pilot_driver.py` (`Refused`, `git`,
`command`, `digest`, `write_json`, `new_output`, `now`, `settings`, `machine`) by import, as
`pass_driver.py` does.

## What holds for every part

- No file outside `v2/probes/documents/` changes. No change to the room, to `v2/probes/items/` or to
  `v2/probes/pilot/`.
- No directory the programs make holds a run of 32 or more hexadecimal characters in its own name. An
  item is named by its first ten characters; the maker refuses two items that share them.
- A turn's code runs only inside the room's jail. Nothing a worker wrote is executed by these programs
  outside it.
- Nothing a turn's tests print is stored by the room. What the diagnostic hands in is read from the
  turn's own repository.
- A count comes from a record, never from a remembered number. Every refusal says what was found.
- No private names and no machine paths in any tracked file.
- The earlier probes did this by hand. Their scripts are beside the lead's briefs, to read and port,
  not to import: `plan-probe-evidence/scripts/` (`describe-probe.py` makes bases and runs a turn;
  `describe-replay.py` judges by replay; `replay-explain.py` is the diagnostic; `plan-search.py` is the
  search; `plan-ceiling.py` finds matching files).

## Files

| File | Whose | What it is |
| --- | --- | --- |
| `v2/probes/documents/documents_plan.py` | Task 1 | The maker, and `load_plan` for the other two |
| `v2/probes/documents/documents_run.py` | Task 2 | The runner |
| `v2/probes/documents/documents_judge.py` | Task 3 | The controls, the judge and the report |
| `v2/probes/documents/documents.sh` | Task 1 | `sh documents.sh <stage> ...`, one line per stage |
| `v2/probes/documents/test_documents_plan.py`, `test_documents_run.py`, `test_documents_judge.py` | With each | Unit tests, with stand-ins |
| `v2/probes/documents/tasks/<item>.facts.md`, `<item>.task.md` | Another worker | The twelve tasks; input to the maker |

## The plan's directory, which is the interface

```
<out>/plan.json            frozen by the maker; never written again
<out>/src/                 a bare repository holding every base (refs/documents/<item>/<row>)
<out>/rows/<nnn>-<item>-<row>/   one per row, made by the runner: repo/, room/, item.txt, started.txt,
                           ended.txt, load-before.txt, load-after.txt, clock.log, clock.exit,
                           turns.json, walks.jsonl, walks.err, record.json
<out>/controls/<item>/     made by the judge: cases.json, parent.json, reference/ and parent/ runs
<out>/judged/<nnn>-<item>-<row>/ made by the judge: replay/, diagnostic/, score.json
<out>/report.json, report.md     made by the judge
```

`<nnn>` is the row's place in the order, three digits from 001. `<item>` is the commit's first ten
characters. `<row>` is one of `nothing-1`, `nothing-2`, `exists`, `path`, `search`, `newest`, `lot`, `bm25`.

**`plan.json`** (every key present; `sort_keys`, indent 1, a final newline; its own SHA-256 is written
to `<out>/plan.sha256` and checked by `load_plan`):

```
{"v": 1, "seed": 20261118,
 "spec_sha256": str, "list_sha256": str,
 "worker": {"name": str, "version": str, "model": str},
 "limits": {"worker_secs": int, "check_secs": int, "replay_secs": int, "diagnostic_secs": int, "lease_secs": int},
 "programs": {...}, "environment": {...},      the room's program and the environment every stage runs it in
 "inputs": {"<path from the repository's root>": "<sha256>", ...},   every script here and each it imports, and the room's program
 "items": [{"commit": str(40), "item": str(10), "parent": str(40), "probed_before": bool,
            "plan_group": str,            the direct path; items with one direct path are one plan
            "tests": [str], "kept_out": {"reference": str, "test_blobs": [str]},
            "direct_path": str, "matching": [str],
            "facts_sha256": str, "task_sha256": str, "query_sha256": str,
            "search": {"three": [str], "best_place": int, "tied": int},
            "newest": {"three": [str], "best_place": int},
            "lot": {"three": [str]},
            "bm25": {"three": [str], "best_place": int, "tied": int},     the second search of the spec's section 4
            "documents": {"<path>": "<blob>", ...},       every matching and every offered file, at the parent
            "rows": {"<row>": {"paragraph": str, "base": str(40), "wrong": str(40), "task_file_sha256": str}}}],
 "order": [{"n": int, "commit": str(40), "item": str(10), "row": str, "hash": str(64), "directory": str}]}
```

**`record.json`** (the runner, one per row): `{"n", "commit", "row", "began", "ended", "load_before",
"load_after", "clock_exit": int, "turns_exit": int, "walks_exit": int, "outcome": "handed-in" |
"no-hand-in" | "limit" | "clock-failed" | "export-failed", "at_limit": bool, "turn_commit": str or null,
"earlier_attempts": int, "attempts": [{"directory", "started": bool, "clock_exited": bool}],
"interrupted_attempts": int}`.

- The outcome is read from the room's export of the turn, not from the clock's exit code: the real room
  ends a finished turn that handed in nothing with exit 1 and records the base's own commit for it.
- A recorded commit other than the base makes the row `handed-in`, even when the room ended the turn at
  its limit. A commit equal to the base is `no-hand-in`, unless the turn ended `timed_out`: then it is
  `limit`. (The real room records the base's own commit for a turn that handed in nothing, finished or
  stopped at its limit.) A turn with no commit is read the same way by how it ended. `at_limit` is true
  whenever the room ended the turn at its limit, and the report counts those rows by condition.
- `export-failed`: the room's export of the turn failed. What it printed is kept, and the judge asks
  for the export once more before scoring. A failed export of the walk leaves the outcome as it is.
- `clock-failed`: anything else, a clock that ended with no turn among them.
- `interrupted_attempts` counts the earlier attempts that had started and whose clock had not ended.

**`cases.json`** (the judge, one per item): `{"commit", "cases": [str], "counts": {"passed", "failed",
"error", "skipped"}}`, where `cases` are the identifiers of the item's tests that pass on the reference
in the jail, sorted. **`parent.json`**: `{"commit", "passed": [str]}`, the frozen cases that pass on the
base with no change.

**`score.json`** (the judge, one per row): `{"n", "commit", "row", "outcome", "scored": bool, "of":
int, "passed": int, "failed": int, "error": int, "skipped": int, "not_run": int, "unfrozen": int,
"collection_errors": [str], "first_obstacles": [str], "room_passed": bool or null, "matching_named":
{"<path>": {"step": int, "seconds": float}}, "offered_named": [str], "of_new": int, "passed_new":
int, "at_limit": bool, "exported_again": {"turns": int, "walks": int}}`, and `"reason": str` on a row
whose report was refused. `of_new`
is how many frozen cases do not pass on the parent, and `passed_new` how many of those pass under the
change. The walk's two members are null when the walk could not be exported. `exported_again` holds
the exit code of each export the judge asked the room for once more, because the runner's had failed;
it is empty when none was. Only the export that failed is asked for again.

**A turn of the judge's own that the room stops at its limit** (a diagnostic, a replay) gives no score,
whatever it had committed by then; a diagnostic's counts are kept beside the row. A row's own turn may
hand in at its limit and be scored.

**The outcomes with no score,** one constant in the judge: `clock-failed`, `export-failed`,
`report-refused`, `not-applied`, `diagnostic-limit`, `diagnostic-clock-failed`, `diagnostic-no-hand-in`,
`diagnostic-no-status`, `replay-limit`, `replay-clock-failed`. Each has `scored: false`, `of` the frozen
count, and enters no sum.

## Task 1. The maker (`documents_plan.py`)

`python3 -I documents_plan.py make <items dir> <tasks dir> <out> --worker <name>` and
`python3 -I documents_plan.py show <out>`.

- **Items** by the spec's section 2, from the list and the census file the lead passes
  (`--census <file>`): the three rules, in the spec's words. It must select exactly the twelve the spec
  names; a test holds the twelve ids as a literal and fails if the rule selects otherwise.
- **Matching files and the direct path** by the spec's rule. **Tasks**: for each item the two files
  must exist; the task file's bytes are the task; the query is the task's bytes.
- **The task file a turn sees:** the task, a blank line, the fixed sentence, and for a row with a
  paragraph a blank line and the paragraph. The eight task files of an item are equal, byte for byte,
  up to the paragraph: the maker checks it and refuses otherwise.
- **The paragraphs' bytes,** as built and read: for `exists`, the spec's sentence; for `path`, the
  spec's sentence with the path in backticks and a full stop after it; for the three-path rows, the
  spec's sentence ending in a colon, then one line for each path, `- ` and the path in backticks, in
  the order the search, the newest plans, the lot or the second search (`bm25`) gives them. No line
  after the last.
- **The search, the newest plans and the lot** exactly as the spec's section 4 fixes them. Port the
  search from `plan-search.py` (its first row). The lot's and the order's hashes are over ASCII text
  with the whole commit id.
- **Bases:** for each item and row, a commit on the item's true parent with the task file and the
  probe's small check file laid over, in `<out>/src`, as `describe-probe.py`'s `make` does. The maker
  proves each item's eight bases share the parent and differ in the task file alone.
- **Pins:** `inputs`, `worker`, `limits`, `spec_sha256`, `list_sha256`, `documents`.
- **`load_plan(out)`**, used by all three programs: reads `plan.json`, checks `plan.sha256`, rehashes
  every input, and raises `Refused` naming the first that changed.

**Tests** (stand-ins; a small git repository made in the test): the twelve ids; a thirteenth item with a
test function in its plan is left out; the eight task files' equality up to the paragraph; each row's
paragraph as the spec words it; the lot draws three without replacement and never a matching file; the
order is the 96 hashes ascending and stable; two items sharing ten characters are refused; a changed
input, task or plan file is refused by `load_plan`; no directory name holds 32 hexadecimal characters.
A mutant for every condition and number you add, in a scratch copy after a control that passes.

## Task 2. The runner (`documents_run.py`)

`python3 -I documents_run.py run <out> [--rows N]`: runs, in the plan's order, the next row whose
directory holds no `record.json`, one at a time, up to `N`.

- A row's turn is `describe-probe.py`'s `turn`, ported: a fresh repository and room in the row's
  directory, the base fetched from `<out>/src`, the checks that the reference, the commit and the
  withheld test objects are absent, one turn of the plan's worker, then `turns.json` and `walks.jsonl`.
- `record.json` is written last, atomically. A row directory with no `record.json` is an interrupted
  row: it is moved aside to `rows/interrupted/<its name>-<k>` and the row is run again from nothing,
  and the report later says how many there were. A row with a `record.json` is never run again.
- A lock file in `<out>` refuses a second runner.
- **Controls before turns.** Before a row, the runner requires `controls/<item>/cases.json` (its
  `commit` the item's whole id, its `cases` not empty) and `controls/<item>/parent.json` (its `commit`
  the item's whole id). Without them it refuses, names the item and what is missing, and runs no later
  row. No flag turns this off.
- `outcome`: as `record.json` above gives it.
- **Who wrote the item.** The room never gives an item to a worker of the family that wrote it (the
  text before the first colon of a worker's name). The runner adds each row's item as written by
  `script:probe`, or by `claude:probe` when the worker is itself a script. Found on the real room: with
  a script worker and `script:probe`, every clock ended in two seconds with no turn.
- **The lock outlives a killed runner.** The clock holds the runner's lock while it lives, so a second
  runner is refused until the turn it would collide with has ended.

**Tests** (a stand-in for the room, as `test_pass.py` does it; read how its stand-in takes its
answers): the order is followed; `--rows` stops; an interrupted row is moved aside and run once more
and a recorded row is not; a second runner is refused; each outcome is recorded; a plan with a changed
input is refused before any row.

## Task 3. The judge (`documents_judge.py`)

`controls <out>`, `judge <out> [--rows N]`, `report <out>`.

- **`controls`**, for each item, in the jail, by a script in the worker's place (port
  `replay-explain.py`; the script worker commits a file the judge reads from the turn's repository):
  the reference's change on the item list's own base (the parent with the item's held-back tests and
  its check laid over; the pilot's bases do not hold those tests), the item's tests run with a JUnit
  report, and `cases.json` written from it; then the same with no change, and `parent.json`. A turn's
  change is replayed and diagnosed on that same base: what it changed under the source directory,
  taken as a diff in the row's own repository from the row's base to the turn's commit. A reference
  with no passing case, or one whose room verdict by replay is not a pass, stops the judge for that
  item and is reported.
- **A clock that failed** (a control's, a replay's, a diagnostic's or a row's) gives a row with no score:
  `scored: false`, `of` still the count of frozen cases. The spending rule is then suspended, as for any
  missing row.
- **The report read on the host** is a turn's output: it is bounded in size, must be a regular file of
  the commit in UTF-8, and is refused if it declares a document type or an entity. A turn's code runs
  in the test runner's own process and could forge it; the room's verdict by replay stands beside the
  score for that reason.
- **`judge`**, for each recorded row not yet judged: when `outcome` is `handed-in` and the turn changed
  something under `peer/superyak_peer`, the replay (port `describe-replay.py`) for the room's verdict
  and the diagnostic for the cases; `score.json` by the spec's section 6. `no-hand-in`, `limit` with no
  commit, and a hand-in that changes nothing under the source directory are scored as the parent. A
  change that does not apply, or a diagnostic at its limit, has `scored: false`.
  - A frozen case absent from the JUnit report is `not_run`. A case in the report that is not frozen is
    `unfrozen`. A file that could not be collected appears in `collection_errors` in the runner's words.
  - `first_obstacles`: for each failing or erroring frozen case, the first line of its message, at most
    twenty, as data.
  - `matching_named` and `offered_named` from `walks.jsonl`.
- **`report`**: the spec's section 7, exactly: `b`, `r`, `d`; higher, lower, within the gap; the twelve,
  the eleven without the probed item, by plan with `D` and `R`, the equally weighted figure; the rule's
  three outcomes or "suspended", with which rows were missing; how many items each table stands on;
  the search's and the newest plans' places; interrupted rows.

**Tests** (stand-ins for the room and for the JUnit report): a case frozen and not collected is
`not_run`; a candidate that adds cases does not change `of`; a collection error; each unscored outcome;
`b`, `r`, `d` and the three classes on numbers worked by hand in the test, including `d == r`; the
by-plan rule on a plan of one and of four; the rule suspended when a Nothing row has no score; the
report's counts equal the records'. A mutant for every comparison and number.

## Task 4. The whole path, real: the lead's runs

Not a tracked test file. The lead runs the whole path on the real room and jail with a stand-in script
in the worker's place and no model, over the real twelve items, and keeps each command and what it
printed: the maker, the controls, rows through the runner, the judge and the report. The runs must show
a row whose script hands in nothing, a row ended at its limit, a row whose change passes some frozen
cases and fails others, an interrupted row taken up, and a changed input refused. What they found is
written in the pilot's report. The first such run found the family rule of Task 2.

## Who builds what

- **One builder: Tasks 1 and 2.** **Another: Task 3.** Each works on a branch from this plan's commit.
  Task 3's builder writes against the plan's directory as fixed above and makes its own fixtures; it
  does not wait for Task 1's code.
- **Task 4** is the lead's, once the three are joined.
- Each builder's work is read by a fresh reader of the other family before it is joined.

## Where a builder is most likely to go wrong

1. **A score whose denominator moves.** `of` is the count of frozen cases, always. A test must fail if
   `of` is taken from the candidate's own run.
2. **Bases that differ by more than the paragraph.** The maker proves it; the test must fail when a
   base differs elsewhere.
3. **A row run twice, or a lost row hidden.** Interrupted rows are moved aside and counted.
4. **A rule applied on missing rows.** The report says "suspended" and why.
5. **A stand-in that answers as the builder guessed the room answers.** Say in your summary every place
   your tests guess at the real room, the jail or the worker's program. Those guesses are what Task 4
   and the lead's run are for.
