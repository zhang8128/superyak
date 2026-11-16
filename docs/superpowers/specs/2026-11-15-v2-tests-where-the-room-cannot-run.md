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

## What building it showed

Added after the builders handed in and the first live turn ran. Five things the text above did not foresee,
and what was done about each. Where this section and the text above differ, this section holds. A fresh
reader of the other family read the first four before the change was pushed, and approved each; what it
asked to be changed is said under the second.

**1. In the measured run, a test's own words often do not name the cause.** Of the 159 tests that failed
there, 96 printed a line that names the look at processes. The other 63 failed further on: a clock that
could not freeze its item, and then a test that found no turn where it expected one. "Which tests" asks for
the line. For the measured run the evidence is the run itself: the same commit, machine and command as the
run in which all 418 pass, and one difference, the `ps`. The line is asked of the second place, a sandbox,
where many things differ at once. What each of the 159 printed is kept with the report.

**2. A test of the jail that makes its control first.** Seven tests of the jail first show, with no jail,
that the thing they are about to refuse works on this machine: a listener, a socket, a listing of the
home, a terminal, the system's launcher, a question about another process, a keyring. Then each enters a
jail. In a builder's sandbox the control fails, or the jail is refused without a word, so what such a test
prints there is not about a jail; by "Which tests" it would stay unmarked, and fail in every worker's
sandbox. Each of the seven enters a jail on a line that every path through its body reaches, and passes
only on something the jailed program itself printed. No place without a jail can pass it. They carry the
mark on that evidence: the line of the body, and the pass where the room can run. One of the seven is built
on Linux only, where no builder stood.

The reader found that one of the seven did not hold to this as first written. The test of the terminal
passed when nothing reached the terminal, and a jail whose shell never started leaves nothing there either.
Its shell now says first, on the output it was given, that it started, and the test requires that line
before it looks for the one that must not come. With the jailed program replaced by one that starts no
shell, the test fails with "the jailed shell did not start", and its control still holds.

**3. The room needs a third thing of a machine: a directory of its own in /tmp.** Nine tests of what the
room gives a worker's program (its command, its settings, its own place for temporary files) make that
directory as the room does, and look at no process and enter no jail. A builder reported them from its own
sandbox, and the first live turn of a Claude worker through the room showed the same nine, each with
`make /private/tmp/yak-...: Operation not permitted`, and no other test failing. They are marked, with
words of their own, because the first words would say something untrue of them:
`#[ignore = "needs the room: a directory of its own in /tmp"]`.

So there are two sentences, and **every such reason begins `needs the room: `** and then names what the
room needs of the machine. The set is found by that beginning. A test that was shown to need a list of
processes or a jail carries the first sentence, whatever else it needs. A new sentence is added only for a
need that is shown in a worker's sandbox, on a test that the first two do not describe.

**4. The guard looks at one more number.** A `test result:` line also counts tests left out by a filter.
In the whole run that number is 0 on every line, as the ignored count is, and the guard fails on either.
It still does not see a test program that a test started for itself, whose output that test kept; that is
what "A test that another test starts" is for.

**5. The acceptance suite's owner marked its tests, and the exception is closed.** The ship that owns the
suite marked the thirteen with the first sentence, by its own reading of the path each takes, and changed a
fourteenth: a test that no text of a turn reaches the store passed where no turn ran, which is a pass for
what did not run. It now requires that its turn passed, and so needs the room, and says so. Run at the
owner's commit on the lead's machine with every test asked for: all 16 pass with the machine's own `ps`; 14
fail and 2 pass with a `ps` that fails. The two that pass anywhere start no clock. So the workspace has no
`default-members` line: a plain `cargo test` runs the acceptance suite's two, and prints the other fourteen
as left out, with their reason, as it does for every other crate.

**What is not changed:** the way taken, the first sentence's words, and the command that runs everything.
