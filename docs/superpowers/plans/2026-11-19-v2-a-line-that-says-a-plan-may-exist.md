# A line that says a plan may exist: the build

> For the workers who build it. The spec is
> `docs/superpowers/specs/2026-11-19-v2-a-line-that-says-a-plan-may-exist.md` (revision 3). This plan
> fixes the files, the names and what passes between the parts. Where the spec and this plan differ, the
> spec holds and you say so.

**Goal:** make the second pilot's frozen plan, run its rows, judge them and print its report, by two new
scripts that reuse the first pilot's, with the first pilot's scripts changed only where named below.

**Shape.** The first pilot's three programs stay: `documents_plan.py`, `documents_run.py`,
`documents_judge.py`. Two new programs stand beside them and import them:

| File | Task | What it is |
| --- | --- | --- |
| `v2/probes/documents/documents_plan2.py` | 1 | The second pilot's maker: candidates, the walk, the plan |
| `v2/probes/documents/test_documents_plan2.py` | 1 | Its tests |
| `v2/probes/documents/documents_run.py` | 1 | One change: every item's controls are checked before the first turn |
| `v2/probes/documents/documents_judge.py` | 2 | One change: one item's controls become a function of their own (`control_item`), which `controls` calls for each item as now |
| `v2/probes/documents/documents_judge2.py` | 2 | The second pilot's judge: controls for candidates, scoring by the first judge's own `judge_row`, the report of the spec's section 8 |
| `v2/probes/documents/test_documents_judge2.py` | 2 | Its tests |
| `.github/workflows/v2.yml`, `test_documents_plan.py` | 1 | The five documents test files on the workflow's list; the history test skipped where there is no history |

The spec's section 9 says "in place"; the lead changed that to this shape after the spec's approval,
because it leaves the first pilot's scoring code untouched and under its own tests. Nothing of the
pilot's design changes by it.

## Global constraints

- Python 3.9, standard library only, run with `python3 -I`. No model and no network in any test.
- A turn's code runs only inside the room's jail. The judge reads what a turn committed, bounded as the
  first judge bounds it; reuse that code, do not copy it.
- Every stage refuses a plan whose hash or pinned inputs changed (`documents_plan.load_plan`).
- No private names and no machine paths in any tracked file.
- A mutant for every condition, comparison and number you add, in a scratch copy after a control that
  passes; list each as killed by a named test or survived with why.
- You make no git commit; the team's daemon commits at hand-in. Hand in by the minute your brief says.

## The directory

```
<out>/candidates.json            made by `documents_plan2.py candidates`
<out>/src/                       a bare repository: refs/documents/<item>/<row> and -wrong
<out>/controls/<item>/           cases.json, parent.json or stopped.json (the judge)
<out>/plan.json, plan.sha256     made by `documents_plan2.py make`, after the controls
<out>/rows/<nnn>-<item>-<row>/   the runner, as in the first pilot
<out>/judged/<nnn>-<item>-<row>/ score.json (the judge)
<out>/report.json, report.md     the judge
```

**`candidates.json`** (sort_keys, indent 1, a final newline):

```
{"v": 2, "list_sha256": str,
 "selection": {"used_before_sha256": str, "pool_p_order_sha256": str, "pool_n_order_sha256": str,
               "pool_p_record_sha256": str, "pool_n_record_sha256": str},
 "part_a": [{"commit": str(40), "item": str(10), "parent": str(40)}],             the first pilot's twelve
 "pool_p": [{"n": int, "commit", "item", "parent", "plan_group": str, "matching": [str], "direct_path": str}],
 "pool_n": [{"n": int, "commit", "item", "parent"}]}                               accepted items only, in the order's order
```

**`plan.json`** has every key of the first pilot's plan that `load_plan`, the runner and `judge_row`
read (`v`, `seed`, `spec_sha256`, `list_sha256`, `worker`, `limits`, `programs`, `environment`,
`inputs`, `items`, `order`, `items_dir`), with `"v": 2`, `"seed": 20261120`, and:

```
 "line": "There may be a plan for this work in the repository. Look for one before you change code.",
 "selection": as in candidates.json,
 "part_b_run": bool,
 "walk": {"P": [{"n", "commit", "taken": bool, "why": str}], "N": [...]},        every accepted item the walk reached
 "items": [{"commit", "item", "parent", "part": "A" | "B", "pool": null | "P" | "N",
            "plan_group": str | null, "matching": [str], "direct_path": str | null,
            "task_kind": "frozen" | "message", "task_sha256": str,
            "message": {"names_a_matching_file": bool, "cites_a_task_or_step": bool,
                        "counted_names_held": [str]} | null,                     pool P items only
            "tests": [str], "kept_out": {...}, "documents": {"<path>": "<blob>"},
            "rows": {"<row>": {"paragraph": str, "base": str(40), "wrong": str(40), "task_file_sha256": str}}}],
 "order": [{"n", "commit", "item", "row", "hash", "directory"}]
```

Rows: a part A item has `may-1`, `may-2`; a part B item has `nothing-1`, `nothing-2`, `may-1`, `may-2`.
A `may` row's paragraph is the line; a `nothing` row's is empty. The order's hash is the SHA-256 of the
ASCII text `20261120:order:<commit>:<row>`.

## Task 1. The maker and the runner's check (`documents_plan2.py`)

`python3 -I documents_plan2.py candidates <items> <selection dir> <out>`
`python3 -I documents_plan2.py make <items> <tasks> <selection dir> <out> --worker <name> --census <file>`

- **`candidates`** reads the two order files and the two records, refuses a record whose walked items
  are not the order's own, in order, from its first, and writes `candidates.json` with the accepted
  items; for part A it takes the first pilot's twelve by the first maker's `select_items`. It writes no
  plan. A record entry that is neither "accepted" nor "skipped", or a pool P acceptance with no
  `plan_group`, is refused.
- **`make`** requires `candidates.json` and, for every candidate and part A item, the judge's
  `controls/<item>/cases.json` and `parent.json`. A `stopped.json` at any item the walk would reach
  refuses the make and names it. Then **the walk**, for each pool in order: take an item when fewer
  than two of its plan group are taken (pool P) and not every frozen case is in the parent's `passed`;
  stop at six. `plan.walk` records each item reached and why it was or was not taken ("taken", "the
  plan group has two", "every frozen case passes on the parent").
- **A pool that ends before six:** `part_b_run` is false, the plan holds part A alone (24 rows), and
  `make` says so on its last line.
- **Tasks.** Part A: the frozen task files, checked against `FROZEN.sha256`. Part B: the bytes of
  `git show -s --encoding=UTF-8 --format=%s%n%n%b <commit>` in the item list's repository with
  `.rstrip(b" \t\r\n\v\f")`, framed by the first maker's `task_bytes`.
- **The message's record** for a pool P item, computed and pinned: whether the message holds a matching
  file's path or its file name; whether it matches `\b[Tt]ask\s+\d+` or `\b[Ss]tep\s+\d+`; which of
  the item's counted names it holds as whole words.
- **Bases** by the first maker's `make_bases` and `prove_bases`, which take the rows from a new
  argument (`rows: {name: paragraph}`); with none they behave as now. `prove_bases` compares against
  the item's first row by name.
- **Pins:** every `.py` and `.sh` in the directory, the spec, the frozen tasks, the two orders, the two
  records, `used-before.txt`, the census, and every part B message's bytes (written to
  `<out>/messages/<item>.txt`).
- **The runner's one change:** `run_rows` checks `controls_ready` for every item of the plan before
  its first turn, and refuses with the item's name.

**Tests** (fixtures as the first maker's tests make them: a small repository, a stand-in list):
candidates from a record with a skipped and an accepted item; a record out of order refused; the walk's
cap of two a plan group, an item all of whose frozen cases pass on the parent skipped, a stopped control
refusing the make; a pool ending at five giving part A alone with `part_b_run` false; the message's
exact bytes with a trailer kept and trailing white space gone; the three facts of a message's record,
each true and false; the 72 rows and their hashes; four task files of a part B item equal up to the
paragraph; a part A item's two; the runner refusing when a later row's item has no controls; a changed
record refused by `load_plan`.

**The workflow.** Add `probes/documents/test_documents_plan.py`, `test_documents_run.py`,
`test_documents_judge.py`, `test_documents_plan2.py` and `test_documents_judge2.py` to the list in
`.github/workflows/v2.yml`'s step "The scripts' own tests". In `test_documents_plan.py` the history
test skips (`unittest.SkipTest`, with its reason) when the first census commit is not in the
repository; it must still run and pass in a full checkout.

## Task 2. The judge (`documents_judge2.py`)

`python3 -I documents_judge2.py controls <out> --items <items dir>`
`python3 -I documents_judge2.py judge <out> --items <items dir> [--rows N]`
`python3 -I documents_judge2.py report <out>`

- **`controls`** makes the first judge's controls for every item of `plan.json`, or, when there is no
  plan yet, of `candidates.json` (part A, pool P and pool N). In `documents_judge.py`, move the body of
  `controls`' loop into `control_item(out, plan, items, listed, item)` with no change of behaviour (the
  first judge's own tests must pass untouched), and call that; do not copy it. Before a plan exists the
  limits, program and environment come from the first maker's `runtime_pins`, as `make` will pin them.
  A refused report stops that item, as there.
- **`judge`** scores each recorded row with `documents_judge.judge_row`, unchanged. Add to each score
  what the spec's section 7 asks of the walk: `plans_named` (the distinct paths under a `plans`,
  `specs` or `reviews` folder that the walk names, sorted), `first_source_second` (the `seen_ms` of the
  first step naming a path under the source directory, in seconds, or null), `steps`, `seconds`,
  `tokens` (fresh-in plus output, or null). A walk that could not be read gives nulls, never zeros.
- **`report`**, the spec's section 8, on the shares of all frozen cases and again on the cases that do
  not pass on the parent:
  - part B, an item: `n1`, `n2`, `b`, `rn`, `m1`, `m2`, `m`, `rm`, `d`, its class with `max(rn, rm)`,
    and `ceiling` (both Nothing rows pass every frozen case); a pair with a row unscored gives nulls;
  - a pool: the mean `d` and the items it stands on; for pool P the mean over plan groups and the
    groups it stands on; "not available" where nothing stands under an aggregate; items higher, lower,
    within;
  - the counts beside the scores, by pool and row kind: turns whose walk names a matching file (pool
    P), the distinct plans, specs and reviews paths named, the first source second, steps, seconds,
    tokens, each with how many turns it stands on;
  - a pool P item's message record beside its four scores;
  - part A: turns of 24 whose walk names a matching file; the frozen cases passed at each item in each
    run. No class;
  - the rule, read once on all frozen cases: "worth a larger trial" when pool P's mean `d` and its
    mean over plan groups are both above zero and at least one pool P item is higher, and pool N's
    mean `d` is zero or above and no pool N item is lower; "not worth one" when two or more pool N
    items are lower or pool N's mean `d` is below -0.05; otherwise "between", and "the pool could show
    no gain" when every pool P pair is at its ceiling. Suspended, naming the rows, when a part B row has
    no score. Not given at all when `part_b_run` is false;
  - before the tables, in the report itself: that the rule reads agreement with the reference's tests
    and leaves out seconds and tokens; that every score could be forged by a turn's own code; that the
    room's verdict by replay does not vouch for a score; that part A's items are seen and enter no rule.
- One plan shape only: a plan with `v` other than 2 is refused, and so is a part B item with a row
  missing.

**Tests:** the readings worked by hand (a higher, a lower inside a wide gap that stays within, a pair
with one row unscored, a ceiling); the pool means and the mean over plan groups, with a group that has
no `d`; "not available" not zero; each branch of the rule at its edges, the all-zero result among them
("between"), a pool N mean of -0.05 exactly and just below; suspended on a missing part B score and not
on a missing part A score; `part_b_run` false; the walk's counts from a small walk file with a path
under `reviews`, one under the source directory, and none; a walk that cannot be read; a plan of the
first pilot refused.

## Who builds what

- **One builder: Task 1. Another: Task 2,** of the other family. Each works on a branch from this
  plan's commit. Task 2's builder writes against the plan's shapes as fixed above and makes its own
  fixtures; it does not wait for Task 1's code.
- Each builder's work is read by a fresh reader of the other family before it is joined.
- **Then the lead** runs the whole path on the real room with a stand-in script in the worker's place,
  at one item of each part and pool, through the judge and the report, before the plan is made: the
  plan pins both judges.

## Where a builder is most likely to go wrong

1. **Copying the first pilot's code instead of calling it.** The scoring must be the first judge's own
   function, so that one set of tests holds it.
2. **Averaging one run as a cell.** A pair with a missing score gives nulls and the report says how
   many items a mean stands on.
3. **A walk that chooses.** The walk takes or skips by the three stated facts alone, in the order's
   order; nothing a model did can reach it.
4. **Zero for nothing.** An empty aggregate, an unread walk and a missing token count are null or "not
   available".
5. **A stand-in that answers as the builder guessed the room answers.** Say every such place in your
   summary. The first pilot's two real-room findings are in its plan document: the room never gives an
   item to a worker of the family that wrote it, and it records the base's own commit for a turn that
   handed in nothing.
