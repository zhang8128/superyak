# v2: tests that need the room say so. What was built and measured

Serenity, 2026-11-16 (UTC). The repair specified in
`docs/superpowers/specs/2026-11-15-v2-tests-where-the-room-cannot-run.md`, in the six commits from 43488f76 to
190ab6bf on branch `v2`. Every run below is of the tree at 190ab6bf unless it says otherwise.

**A worker that runs `cargo test` inside its own sandbox now waits under a minute and sees a run with no
failure.** Before, at 417ccdea with the look at processes taken away, the whole suite took 460 seconds and
159 of 418 tests failed.

**Where the room can run, every test still runs.** The same test names as before, program by program, on
both of the lead's machines, and none left ignored.

## Inside each worker program's own sandbox

One live turn of each program through the room. The turn's work was to run `v2/probes/tests/probe.py` and
commit what it printed; the numbers are from that file, not from what a model said.

| Program, machine | Build | Tests' own build | Tests | Passed | Failed | Left out, each with its reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Claude Code as `claude:opus`, macOS | 10 s | 4 s | 45 s | 217 | 0 | 203 |
| Codex as `codex:gpt-6.1-sol`, macOS | 9 s | 4 s | 45 s | 217 | 0 | 203 |
| Claude Code as `claude:haiku`, Linux | 80 s | 47 s | 29 s | 217 | 0 | 196 |

- **Each of the three places is one where the room cannot run,** by the probe's own look: none can enter a
  jail. On macOS neither can start `ps`. On Linux `ps` runs and lists 4 lines, the sandbox's own.
- **No process of the tests was left running** in cargo's own group when it ended, in any of the three.
- **Codex is not installed on the Linux machine,** so there is no fourth row.
- **One run each.** The machine's load average was between 5 and 10 on the Mac during its two.

## Where the room can run

| Machine | Command | Tests run | Ignored | Seconds |
| --- | --- | ---: | ---: | ---: |
| macOS (arm64) | `bash scripts/whole-suite.sh <log> --offline` | 420 | 0 | 181 |
| Linux (the Pi, arm64) | the same, inside a live session | 413 | 0 | 196 |

- **The same names as before the change:** 420 on macOS and 413 on Linux, compared program by program with
  the runs at 417ccdea (418 and 411 passed then, and 2 helpers were ignored that now run and return at once).
- **With a `ps` first on the path that fails, a plain `cargo test` passes:** 217 passed, none failed, on
  macOS in 45 seconds (203 left out) and on Linux in 28 seconds (196 left out).
- **A test left ignored where it should run is seen.** Given the log of that plain run, the guard ends with 1
  and names twelve result lines that leave tests out.
- **CI ran the same script on 190ab6bf and passed** (run 43925646040): 413 tests on x86-64 Linux and 420 on
  macOS, none ignored on either, the 29 test programs as listed.

## The marks

202 tests carry a reason that begins `needs the room: `. Every one, with what shows it, is in
`docs/reports/2026-11-16-v2-tests-that-need-the-room-marks.tsv`.

| Sentence | Tests | Marked by |
| --- | ---: | --- |
| `a list of processes and a jail`, the `turn` crate | 106 | a builder (Opus) 99, the lead 7 |
| the same, the `yak` crate | 73 | a builder (Sol) |
| the same, the acceptance suite | 14 | its owner, the ship Tardis |
| `a directory of its own in /tmp`, the `turn` crate | 9 | the lead, from a live turn |

- **Of the 159 that failed in the measured run, 96 printed a line that names the look at processes.** The
  other 63 failed further on. For those the evidence is the run and its one difference, the `ps`.
- **43 more were never in that run's list** and were shown by a sandbox, a test's own body, or its owner.

## A test that another test starts

Twelve places start the test program again. Three were changed, because a child that is left ignored ends
well. Five mutants that take a flag or a printed line away were run where the room can run, before and
after the last change: each failed with the words expected, and each unchanged control passed.

## Found on the way

- **A memory test on macOS took its number from `/usr/bin/time`,** which gives one for an ignored child too.
  Its child's body now prints a line the parent requires. Found by a builder.
- **An acceptance test passed for a turn that never ran.** It now requires that the turn passed. Found by
  the suite's owner.
- **The test that a jailed run cannot write to the terminal passed when its shell never started.** The shell
  now says first that it started. Found by a reader of the other family.
- **The probe said `TESTS ok` on cargo's exit alone.** It now needs the harness's own lines as well. Found by
  the same reader.
- **The lead's check stopped at bytes that are not text,** in a locale that is not plain. Found by running
  the cases written for its twin, which a worker of the other family wrote apart.
- **On the Linux machine one test's control reaches the session's keyring.** Started with `nohup` and left,
  the whole run fails that one test; inside a live session it passes. Shown both ways.

## What this does not show

- **How any other sandbox behaves.** Three places were tried. A test that fails in a fourth shows as a
  failure there, and is marked when its own line says what the room lacked.
- **That the pilot's noisy item is now quiet.** Its long commands were not recorded. A worker's test run is
  now under a minute; whether that was what made those turns differ is for a fresh pilot to show.
- **Seconds under a steady load.** Each figure is one run.

## Where the rest is kept

The logs of every run named here, the three live turns' own files, the two readers' texts and the mutants'
output are on the lead's machine, beside the builders' briefs. They are not in the repository.
