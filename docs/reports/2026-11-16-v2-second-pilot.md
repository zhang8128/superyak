# v2: the second pilot, at items made from merged commits

Serenity, 2026-11-16 (Pacific; the turns ran from 05:32 to 06:16 UTC on the 17th). This is the pilot of
section 7 of `docs/superpowers/specs/2026-11-16-v2-a-route-offered.md`: sixteen turns at three items with
nothing offered. It sizes the experiment and decides nothing else. Nothing here says whether a route helps.

## What was fixed before the first turn

The list below was written and hashed before turn 1 (SHA-256 beginning e4876f46).

| What | Fixed as |
| --- | --- |
| The items | The item-maker's list over every commit of the main branch since October: SHA-256 beginning 4b25d330. Its three pilot items, below |
| The room program | Built from 44447ae1; SHA-256 beginning af97236b |
| The scripts | `v2/probes/items/` at 7baab9bd, which is in `v2` at 19b23810 |
| The worker | `codex:gpt-6.1-sol`, codex-cli 0.163.0 |
| The test environment | Python 3.13.5 with 30 packages; the component's lock file, SHA-256 beginning 9c4b26ae |
| The machine | macOS on arm64 |
| The plan | Sixteen turns: one thrown away at item A, then five rounds of A, B, C. Every turn with a first line of its own. No arm, so no seed |

| Item | Made from | Its tests | Tests that pass on its reference | Lines its reference adds to the source |
| --- | --- | --- | --- | --- |
| A | 3d8775bc | `test_imprint_withdrawal.py` | 17 | 72 |
| B | 01c46a2d | `test_imprint_admission.py` | 16 | 259 |
| C | a0c94043 | `test_imprint_uses.py` | 27 | 71 |

The three are one evening's commits to one feature. Each asks for a part of that feature to be written so
that its failing tests pass.

**Each reference was shown through the room's jail on this machine first,** as section 6 asks: a stand-in
worker applied the reference's change inside the jail and handed it in, and the room judged it passed and
verified, in 18, 18 and 24 seconds. For each, the tree handed in was the reference's own, and the room's
hash of the frozen check was the one the scripts work out from the list. The pilot's script would not
start without those three receipts, tied to their runs.

## The sixteen turns

Every turn left one usable observation. The block checks before the first turn and after the last both
held.

| Turn | Round | Item | Verdict | Active s | Worker s | Check s | Steps | Load before, after | Lines added to the source | Words named |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | thrown away | A | passed | 74.4 | 65.3 | 7.3 | 12 | 4.02, 9.34 | 44 | none |
| 2 | 1 | A | passed | 105.2 | 96.7 | 7.0 | 16 | 9.34, 8.28 | 33 | none |
| 3 | 1 | B | passed | 236.2 | 228.3 | 6.6 | 18 | 10.98, 6.24 | 166 | `exit` 2 times in `__main__.py` |
| 4 | 1 | C | passed | 137.3 | 125.5 | 10.4 | 13 | 6.24, 7.98 | 71 | `exit` 4 times in `imprints.py` |
| 5 | 2 | A | passed | 103.2 | 95.0 | 6.8 | 15 | 7.98, 6.68 | 36 | none |
| 6 | 2 | B | passed | 278.1 | 270.4 | 6.4 | 17 | 6.68, 12.83 | 146 | `SystemExit` 2 times in `__main__.py` |
| 7 | 2 | C | passed | 113.6 | 102.4 | 9.8 | 11 | 12.83, 12.11 | 57 | `exit` 3 times in `imprints.py` |
| 8 | 3 | A | passed | 109.0 | 100.8 | 6.9 | 13 | 12.11, 7.43 | 34 | none |
| 9 | 3 | B | passed | 212.9 | 205.2 | 6.2 | 17 | 7.43, 6.73 | 147 | `exit` 2 times in `__main__.py` |
| 10 | 3 | C | passed | 139.2 | 127.3 | 10.4 | 13 | 6.51, 7.59 | 63 | `exit` 4 times in `imprints.py` |
| 11 | 4 | A | passed | 115.5 | 106.8 | 7.1 | 15 | 7.59, 6.76 | 34 | none |
| 12 | 4 | B | failed | 275.9 | 273.3 | 1.3 | 20 | 6.78, 3.57 | 129 | `SystemExit` 2 times in `__main__.py` |
| 13 | 4 | C | passed | 142.8 | 131.1 | 10.2 | 13 | 3.57, 10.14 | 64 | `exit` 5 times in `imprints.py` |
| 14 | 5 | A | passed | 101.4 | 92.6 | 7.3 | 14 | 10.14, 6.91 | 44 | none |
| 15 | 5 | B | passed | 216.3 | 208.5 | 6.3 | 16 | 6.91, 6.78 | 159 | `SystemExit` 2 times in `__main__.py` |
| 16 | 5 | C | passed | 124.5 | 112.7 | 10.2 | 15 | 6.78, 9.09 | 64 | `exit` 4 times in `imprints.py` |

- **Fourteen of the fifteen measured turns passed, and were verified.** The room ran each passing check a
  second time, as it always does, and it agreed.
- **Active seconds** are the clock's, from the worker's start to its end with the room's own work between.
  **Worker seconds** are the worker program's alone.
- **The load** is the machine's one-minute load average as the turn began and as it ended. Other programs
  of the person's were running on the machine throughout, and nothing was done about them. It ranged from
  3.6 to 12.8 on sixteen cores.

## The one turn that failed

Turn 12, at item B. The worker's commit held, beside its change to two source files, six files of the
test runner's own temporary directory, which it had made inside its checkout and then committed. The
check's first rule is that nothing outside the source directory changes, and it refused the commit there,
in 1.3 seconds, without running the tests. Run by hand outside the jail on that commit, the check says the
same: a path outside the source directory changed.

So the check did what it is for, and the turn failed by the item's rule and not by the feature. It is
counted as failed. It could happen under any arm.

## The spread, and how many items

| Item | Passed | Active s of each turn | Geometric mean s | SD of log |
| --- | --- | --- | --- | --- |
| A | 5 of 5 | 105 103 109 116 101 | 107 | 0.0516 |
| B | 4 of 5 | 236 278 213 276 216 | 242 | 0.1286 |
| C | 5 of 5 | 137 114 139 143 124 | 131 | 0.0952 |

- **The largest spread is 0.1286.** Every measured turn is in its item's spread, passed or not.
- **The rule of the first design** (`2026-11-15-v2-stage-2-experiment.md`, "How many"), with the largest
  spread for both of its terms and worked before rounding: `7.84 * 3 * 0.1286^2 / 0.1625^2` is 14.72,
  rounded up 15.
- **That is under the rule's floor, so `n` is 20.** The scored items are the first twenty of the list's
  forty.
- **What this number leans on.** Five turns at each of three items, which are close neighbours and each
  took two to five minutes. The scored items are spread over the whole component. The first design says
  the planning numbers are looked at again by the scored design's reader with what the history items show.

## What each change names

Section 6 says a pass cannot show that a test run was left alone, and that a run's report says, for each
passing turn, whether its change names the test runner, its report or the ending of the process:
something for a person to look at. The last column of the table above is that, from a list of 26 words.

- **Item A's five turns name none.** Its reference names none.
- **Every turn at item B names `exit` or `SystemExit` twice,** in the component's command-line entry
  point. Its reference names `exit` four times in the same file.
- **Every turn at item C names `exit` three to five times,** in the one source file it changes. Its
  reference names it twice in the same file.
- **Every such line was read: thirty, of three kinds.** At item B each is the entry point ending the
  command with a code after a refusal: `parser.exit(...)` in the reference and in two turns (four lines),
  `raise SystemExit(...)` in the other three (six lines). At item C each of the twenty is a key named
  `exit` in a record of how a run ended. None reaches the test runner or its report, and none ends the
  process the tests run in other than as the tests ask.
- **How often an honest change names a word of this list:** of 193 merged changes to this component that
  each made failing tests pass, 13 name one and 180 name none. Two of the pilot's three references are
  among the 13.
- **The program that says this is not yet pushed.** Its readers have not passed it; their open findings
  are about ending the program cleanly, and not about what it prints. What it printed here was checked by
  looking at each line it pointed to.
- A change that names none of these is not thereby shown to have left the test run alone.

## What the walks hold

For the store, which takes these walks as its history. Exported from each turn's room by
`yak item walks`.

| In one walk | Least | Median | Most |
| --- | --- | --- | --- |
| Steps | 11 | 15 | 20 |
| Steps that name a file | 10 | 12 | 18 |
| Different files named | 6 | 9 | 12 |

Over all sixteen walks, 22 different files are named. Four are named by every walk: the repository's
README, its notes for agents, the one source file all three items change, and the item's own check.

## The list the items came from

- **252 commits meet the first three rules,** and 188 can be items: 40 scored, 3 for the pilot, 51 of
  history, and 94 left out because a kept item names the same test file. Of the 64 that cannot: the tests
  of 47 fail after the change, the tests of 16 pass before it, and one ran past its limit.
- **The spec's count of 257 was the lead's earlier script,** which let through five commits that change a
  file of the component that is neither a test file nor source. The item-maker leaves them out by rule 2.
- **One commit was judged by chance.** The lead's earlier run had it usable; the item-maker found its
  tests failing after the change. Run six times as the check runs them, its two test files passed four
  times and failed twice, on one timing test both times. No item in the list uses that test file.
- **So a check is judged once, and a test that sometimes fails can put a commit in or out by chance.** For
  the scored design's reader: show each scored item's reference to pass several times before it is used.

## What is not shown

- Whether a route shortens a turn. Nothing was offered.
- How turns at the scored items will differ. These three are neighbours in one feature.
- How long a scored turn takes. These took two to five minutes; a scored item may be larger or smaller.
- That a check which passed was left alone. See "What each change names".
- Anything on Linux. The pilot ran on one machine.
