# v2: tests that need the room say so

Serenity, 2026-11-15. A small spec for one repair. It answers to
`docs/superpowers/specs/2026-11-14-superyak-v2-design.md`, and it comes out of two reports:
`docs/reports/2026-11-15-v2-stage-1-run.md` (findings 1 and 3) and
`docs/reports/2026-11-15-v2-stage-2-pilot.md`.

## The fault

v2 is worked on by workers that the room itself runs, each in its own program's sandbox. v2's tests are part
of what such a worker meets. Many of those tests need the room to be able to run: to look at the machine's
processes, and to enter a jail. Inside a worker's sandbox neither can be done.

- **Measured at 417ccdea,** on macOS, outside any sandbox, with a `ps` first on the search path that prints
  an error and ends with 1: the whole suite took 460 seconds. Of 418 tests, 259 passed and 159 failed.
  Seventeen of those that failed ran for more than a minute first.
- **By test program:** every test of the `room` crate passed. In `turn`: 12 of 14 check tests failed, 27 of
  45 sandbox tests, 17 of 20 of the untrusted-run tests, 22 of 37 worker tests, 3 of 44 unit tests and 1 of
  25 transcript tests. In `yak`: 36 of 52 clock tests, 12 of 27 command-line tests, 11 of 12 of the part 0
  tests and 5 of 17 unit tests. In the acceptance suite: 13 of 16.
- **This is the mild form.** That run could still enter a jail. A worker's sandbox on macOS cannot.
- **At the commit the pilot's items stand on it was worse:** two tests did not end at all. They were given a
  stop of their own since, which is why 460 seconds is an end.

**What it costs.** A worker that runs the tests to see whether its change is sound waits about eight
minutes and is shown 159 failures that are not its doing. It cannot tell them from one that is. The first
run with model workers lost a turn's twenty minutes this way. In the pilot, the turns at one item that held
commands of over a minute took from under twice to seven times as long as those that did not; what those
commands were is not recorded, and this fault would produce them.

## What is asked

1. **Where the room cannot run, the tests that can run there do, and quickly.** A plain `cargo test` on an
   unchanged tree passes, in about a minute, with no test left waiting.
2. **It says plainly which tests did not run, and why.** Not as a pass.
3. **Where the room can run, every test runs, as now.** On the lead's two machines and in CI. A test left
   out there is seen.

## Not asked

- That the tests which need the room be made to run in a worker's sandbox. They cannot: a sandbox that
  could run them would not be a sandbox.
- A word to workers about how to test. A worker reads its item's check, which says how to build. Whether
  an instruction file would help is a separate question with its own cost: every worker would be given it.
- Any change to what the room does. This changes tests and how they are run.

## Three ways, and the one taken

| Way | What a worker sees | Why not, or why |
| --- | --- | --- |
| Each such test looks whether the room can run, and returns at once if not | A pass for a test that did not run | It reports as checked what was not. Not taken |
| Each such test looks, and fails at once with one line | 159 failures in seconds in place of minutes | Quick, and honest, and still a red run that hides a real failure among 159. Not taken |
| Each such test is marked as left out unless asked for, with its reason | `ignored, needs the room: ...` for each, and a green run of the rest | **Taken.** It is the test harness's own way to say "not here", it is printed for every test, and it costs nothing at run time |

**So:** a test that needs the room carries `#[ignore = "needs the room: a list of processes and a jail"]`,
with those exact words, so that the set can be found by its reason. The words name what the room needs of
a machine. A test may need only one of the two.

**Where the room can run, the whole suite is run so:** `yak` is built as now, and then
`cargo test --workspace --locked --no-fail-fast -- --include-ignored`, with no filter and no choice of
targets (and `--offline` on the lead's machines). That is the lead's command on both machines and the
workflow's in CI. Documentation tests stay in it. The two tests that are ignored today are helpers started
by another test; run by themselves they return at once, so asking for all ignored tests changes nothing
for them, and it is their parents' assertions that show their work.

**A test that another test starts.** Some tests start the test program again, to run one test in a process
of its own: a test that has to be killed, or held still, or made to fail. The harness's flag does not pass
to that process. Without care, a marked test started that way is ignored there, ends well, and is taken
for a pass.

- Every such start that is meant to run a marked test asks for it in that process too.
- The test that started it shows that the test's body ran, by something the body printed or left behind.
  A good exit does not show it: an ignored test gives one.
- Two cases are shown working after the marks, by name: the test that runs itself again and looks only at
  the exit, and the one whose children are meant to fail.

**What is seen, and what is not.** In that whole run no test is ignored, so every `test result:` line must
say `0 ignored`, and the run's own exit is kept. The workflow fails if a line does not. That catches a test
left ignored in a test program that ran. It does not catch a test program that was never started, a crate
left out, or a filter. So the same step lists the test programs that ran, and that list is compared, for
each platform, with the list from before this change.

**What it costs.** A plain `cargo test` on a machine where the room can run now runs fewer tests than it
did: the ones that can run anywhere. A run of one test program by itself needs the flag too. Whoever works
where the room can run has to ask for the whole suite to get it.

**The acceptance suite is another ship's, and frozen. It is the one exception, for now.** It is not edited
here. The workspace gets `default-members` without it. So a plain `cargo test`, `cargo build`,
`cargo check` or `cargo clippy` at the workspace's root leaves the whole crate out, without a line for any
of its sixteen tests: the thirteen that fail where the room cannot run, and the three that would pass
there. `--workspace` still takes it in, which is what the workflow's build, lints and tests ask for; the
formatter is asked for all; and the three item checks build `yak` by name. Marking its tests is its
owner's, asked for as a separate handoff. Putting the crate back among the defaults waits for that, and
for a measurement of what in it still needs a jail inside a real worker's sandbox.

## Which tests

A test is marked if, on an unchanged tree, it passes where the room can run and fails for want of the room
in one of two places:

- the run above, with the look at processes taken away. Its 159 are listed for the builder. A test that
  enters a jail and never looks at processes is not among them, because that run could still enter a jail;
- a builder's own sandbox, of either program. A builder's sandbox is a worker's sandbox, so the builder is
  standing in the place this repair is for.

**For want of the room** means that what the test printed when it failed says it could not look at
processes, or could not enter a jail. For each marked test the builder records the place, the command and
that line. A test that fails in a sandbox for another reason (it needs the network, it may not write
somewhere, a tool is missing) is not marked with these words. It is reported to the lead with its reason.

A test that fails in neither place is not marked. Tests that a macro makes are marked one by one, not by
marking everything a module holds.

## How we know it is done

Every run named here is from one pinned commit, and its command, its exit, how long it took and all it
printed are kept.

| What | Shown by |
| --- | --- |
| A plain `cargo test` passes where processes cannot be looked at | The lead's run with the failing `ps`, on both machines: none failed. How long the tests took is recorded apart from the build |
| It passes inside each worker program's sandbox | A live turn of each program through the room, at the new head, on a probe item whose work is to run a script and hand in what it printed. The script builds, then runs the tests under a limit of its own, so that a test that waits cannot take the turn, and prints the harness's own lines and the seconds. On Linux for the one program that is there. What a model says about the tests is not the evidence; what the script printed is |
| Every test still runs where the room can | The whole command above on both machines and in CI: none failed, `0 ignored` on every line, and every test named in today's run named again. By count, today's 418 on macOS and 411 on Linux, the two helpers, and whatever this change adds |
| Each mark is earned | For every marked test: a pass where the room can run, and the recorded failure for want of the room in one of the two places |
| A test that another test starts still runs | The two cases named above, each shown to fail when its child is left ignored |
| A test left ignored where it should run is seen | The workflow's step, tried once with a marked test and without `--include-ignored`: it fails |

## What is left to the builder

How to give a started test program the flag, and what a test's body leaves to show it ran; the order of
work. The reason's words, the rule under "Which tests" and what is said of a test that another test starts
are fixed.

## What this does to the experiment

It changes the work a later pilot would measure. A worker that runs the tests is meant to wait about a
minute and not eight; what it does wait is measured when this is built. This gives no new measure of how
much turns differ, and it does not reopen the rule the pilot was stopped on. If long test runs are what made one item's turns differ so much, that difference shrinks; and one
way a note from an earlier turn could have helped a later one is gone with it. A later result says so. The
pilot that was run stands as it is.
