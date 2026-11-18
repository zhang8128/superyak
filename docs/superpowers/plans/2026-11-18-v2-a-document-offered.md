# A document offered: the build

> For the workers who build it. The spec is `docs/superpowers/specs/2026-11-18-v2-a-document-offered.md`
> (revision 3). This plan fixes the files, the names and what passes between the parts. Where the spec
> and this plan differ, the spec holds and you say so.

**Goal:** scripts that make the pilot's frozen plan, run its 84 rows one at a time, and judge them, with
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
| `v2/probes/documents/test_documents_real.py` | Task 4 | The whole path against the real room and jail, no model |
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
characters. `<row>` is one of `nothing-1`, `nothing-2`, `exists`, `path`, `search`, `newest`, `lot`.

**`plan.json`** (every key present; `sort_keys`, indent 1, a final newline; its own SHA-256 is written
to `<out>/plan.sha256` and checked by `load_plan`):

```
{"v": 1, "seed": 20261118,
 "spec_sha256": str, "list_sha256": str,
 "worker": {"name": str, "version": str, "model": str},
 "limits": {"worker_secs": int, "check_secs": int, "replay_secs": int, "diagnostic_secs": int},
 "inputs": {"<path from the repository's root>": "<sha256>", ...},   every script here and each it imports, and the room's program
 "items": [{"commit": str(40), "item": str(10), "parent": str(40), "probed_before": bool,
            "plan_group": str,            the direct path; items with one direct path are one plan
            "tests": [str], "kept_out": {"reference": str, "test_blobs": [str]},
            "direct_path": str, "matching": [str],
            "facts_sha256": str, "task_sha256": str, "query_sha256": str,
            "search": {"three": [str], "best_place": int, "tied": int},
            "newest": {"three": [str], "best_place": int},
            "lot": {"three": [str]},
            "documents": {"<path>": "<blob>", ...},       every matching and every offered file, at the parent
            "rows": {"<row>": {"paragraph": str, "base": str(40), "wrong": str(40), "task_file_sha256": str}}}],
 "order": [{"n": int, "commit": str(40), "item": str(10), "row": str, "hash": str(64), "directory": str}]}
```

**`record.json`** (the runner, one per row): `{"n", "commit", "row", "began", "ended", "load_before",
"load_after", "clock_exit": int, "outcome": "handed-in" | "no-hand-in" | "limit" | "clock-failed",
"at_limit": bool, "turn_commit": str or null}`. A recorded commit makes the row `handed-in` even when the
room ended the turn at its limit; `limit` is a turn ended at its limit with no commit; `at_limit` is true
whenever the room ended the turn at its limit, and the report counts those rows by condition.

**`cases.json`** (the judge, one per item): `{"commit", "cases": [str], "counts": {"passed", "failed",
"error", "skipped"}}`, where `cases` are the identifiers of the item's tests that pass on the reference
in the jail, sorted. **`parent.json`**: `{"commit", "passed": [str]}`, the frozen cases that pass on the
base with no change.

**`score.json`** (the judge, one per row): `{"n", "commit", "row", "outcome", "scored": bool, "of":
int, "passed": int, "failed": int, "error": int, "skipped": int, "not_run": int, "unfrozen": int,
"collection_errors": [str], "first_obstacles": [str], "room_passed": bool or null, "matching_named":
{"<path>": {"step": int, "seconds": float}}, "offered_named": [str]}`.

## Task 1. The maker (`documents_plan.py`)

`python3 -I documents_plan.py make <items dir> <tasks dir> <out> --worker <name>` and
`python3 -I documents_plan.py show <out>`.

- **Items** by the spec's section 2, from the list and the census file the lead passes
  (`--census <file>`): the three rules, in the spec's words. It must select exactly the twelve the spec
  names; a test holds the twelve ids as a literal and fails if the rule selects otherwise.
- **Matching files and the direct path** by the spec's rule. **Tasks**: for each item the two files
  must exist; the task file's bytes are the task; the query is the task's bytes.
- **The task file a turn sees:** the task, a blank line, the fixed sentence, and for a row with a
  paragraph a blank line and the paragraph. The seven task files of an item are equal, byte for byte,
  up to the paragraph: the maker checks it and refuses otherwise.
- **The search, the newest plans and the lot** exactly as the spec's section 4 fixes them. Port the
  search from `plan-search.py` (its first row). The lot's and the order's hashes are over ASCII text
  with the whole commit id.
- **Bases:** for each item and row, a commit on the item's true parent with the task file and the
  probe's small check file laid over, in `<out>/src`, as `describe-probe.py`'s `make` does. The maker
  proves each item's seven bases share the parent and differ in the task file alone.
- **Pins:** `inputs`, `worker`, `limits`, `spec_sha256`, `list_sha256`, `documents`.
- **`load_plan(out)`**, used by all three programs: reads `plan.json`, checks `plan.sha256`, rehashes
  every input, and raises `Refused` naming the first that changed.

**Tests** (stand-ins; a small git repository made in the test): the twelve ids; a thirteenth item with a
test function in its plan is left out; the seven task files' equality up to the paragraph; each row's
paragraph as the spec words it; the lot draws three without replacement and never a matching file; the
order is the 84 hashes ascending and stable; two items sharing ten characters are refused; a changed
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
- `outcome`: `handed-in` when the room recorded a commit for the turn; `limit` when the room ended the
  turn at its limit; `no-hand-in` when it finished with no commit; `clock-failed` otherwise.

**Tests** (a stand-in for the room, as `test_pass.py` does it; read how its stand-in takes its
answers): the order is followed; `--rows` stops; an interrupted row is moved aside and run once more
and a recorded row is not; a second runner is refused; each outcome is recorded; a plan with a changed
input is refused before any row.

## Task 3. The judge (`documents_judge.py`)

`controls <out>`, `judge <out> [--rows N]`, `report <out>`.

- **`controls`**, for each item, in the jail, by a script in the worker's place (port
  `replay-explain.py`; the script worker commits a file the judge reads from the turn's repository):
  the reference's change on the item's `nothing-1` base, the item's tests run with a JUnit report, and
  `cases.json` written from it; then the same with no change, and `parent.json`. A reference with no
  passing case, or one whose room verdict by replay is not a pass, stops the judge for that item and is
  reported.
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

## Task 4. The whole path, real (`test_documents_real.py`)

Skipped unless `YAK_DOCUMENTS_REAL=1` and the room's program is given as the earlier real tests take
it. With a script named for the worker and no model, over two small items made in the test from the
real item-maker's shapes: the maker, all fourteen rows through the real room and jail, the controls,
the judge and the report. It must show every row run once, a row whose script hands in nothing, a row
whose script hands in a change that fails some frozen cases and passes others, a test file that cannot
be collected scored as not run, an interrupted row taken up, and a changed input refused. The lead runs
it on the host before any reader sees the build.

## Who builds what

- **One builder: Tasks 1 and 2.** **Another: Task 3.** Each works on a branch from this plan's commit.
  Task 3's builder writes against the plan's directory as fixed above and makes its own fixtures; it
  does not wait for Task 1's code.
- **Task 4** follows when the three are joined, by the builder of Tasks 1 and 2.
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
