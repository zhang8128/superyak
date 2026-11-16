#!/usr/bin/env python3
"""Tests of probe.py and of the checks that judge what it leaves. Run as: python3 -I test_probe.py

No cargo is run and nothing is built: the cargo and the ps the probe starts are scripts that print what the
real ones would and write down the words they were given.
"""
import contextlib
import importlib.util
import io
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest

# Nothing is left beside the scripts by running these.
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS = os.path.join(HERE, "..", "..", "checks")
spec = importlib.util.spec_from_file_location("probe", os.path.join(HERE, "probe.py"))
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

ROOM = "needs the room: a list of processes and a jail"


def result(passed=3, failed=0, ignored=0, filtered=0, word="ok"):
    return "test result: %s. %d passed; %d failed; %d ignored; 0 measured; %d filtered out; finished in 0.52s" % (
        word,
        passed,
        failed,
        ignored,
        filtered,
    )


GOOD = "\n".join(
    [
        "    Finished `test` profile [unoptimized + debuginfo] target(s) in 0.11s",
        "     Running unittests src/lib.rs (target/debug/deps/room-0123456789abcdef)",
        "",
        "running 3 tests",
        "test one ... ok",
        "test two ... ok",
        "test three ... ok",
        "",
        result(),
        "",
        "     Running tests/sandbox.rs (target/debug/deps/sandbox-0123456789abcdef)",
        "",
        "running 5 tests",
        "test a ... ok",
        "test b ... ignored, " + ROOM,
        "test c ... ignored, " + ROOM,
        "test d ... ignored, run in a child process by a",
        "test e ... ignored",
        "",
        result(passed=1, ignored=4),
        "",
        "   Doc-tests room",
        "",
        "running 0 tests",
        "",
        result(passed=0),
    ]
)

FAILING = "\n".join(
    [
        "     Running tests/clock.rs (target/debug/deps/clock-0123456789abcdef)",
        "",
        "running 3 tests",
        "test holds ... ok",
        "test a_stop_leaves_no_ref ... FAILED",
        "test another ... FAILED",
        "",
        "failures:",
        "",
        "---- a_stop_leaves_no_ref stdout ----",
        "the test's own run of itself printed:",
        "running 1 test",
        "test a_stop_leaves_no_ref ... FAILED",
        result(passed=0, failed=1, filtered=51, word="FAILED"),
        "",
        result(passed=1, failed=2, word="FAILED"),
        "test result: nothing that can be read",
    ]
)


def sleeper_gone(pid, within=5.0):
    """Whether a process is gone, or only waiting for its parent to ask."""
    until = time.monotonic() + within
    while time.monotonic() < until:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        shown = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False)
        if shown.returncode != 0 or shown.stdout.strip().startswith("Z"):
            return True
        time.sleep(0.05)
    return False


class Counted(unittest.TestCase):
    def test_a_run_that_passed_is_added_up_with_why_tests_were_ignored(self):
        seen, reasons, failed = probe.counted(GOOD)
        self.assertEqual(
            seen, {"programs": 3, "results": 3, "unread": 0, "passed": 4, "failed": 0, "ignored": 4, "inner": 0}
        )
        self.assertEqual(reasons, {ROOM: 2, "run in a child process by a": 1, "no reason given": 1})
        self.assertEqual(failed, [])

    def test_a_failed_tests_own_child_is_not_counted_twice(self):
        seen, reasons, failed = probe.counted(FAILING)
        self.assertEqual(
            seen, {"programs": 1, "results": 1, "unread": 1, "passed": 1, "failed": 2, "ignored": 0, "inner": 1}
        )
        self.assertEqual(reasons, {})
        self.assertEqual(failed, ["a_stop_leaves_no_ref", "another"])

    def test_nothing_printed_adds_up_to_nothing(self):
        seen, reasons, failed = probe.counted("")
        self.assertEqual(set(seen.values()), {0})
        self.assertEqual((reasons, failed), ({}, []))


class Unshown(unittest.TestCase):
    """What keeps cargo's good exit from being taken for tests that ran and passed."""

    def doubts(self, text):
        seen, _, failed = probe.counted(text)
        return probe.unshown(seen, failed)

    def test_a_run_whose_lines_show_tests_that_passed_leaves_no_doubt(self):
        self.assertEqual(self.doubts(GOOD), [])

    def test_each_thing_missing_is_said(self):
        started = "     Running tests/a.rs (target/debug/deps/a-0123456789abcdef)"
        for text, said in (
            ("", ["no test program was started", "no test is counted as passed"]),
            (started, ["1 test programs were started and 0 results were read", "no test is counted as passed"]),
            (result(), ["no test program was started", "0 test programs were started and 1 results were read"]),
            (started + "\ntest result: ok. some passed",
             ["1 test programs were started and 0 results were read", "1 results could not be read",
              "no test is counted as passed"]),
            (started + "\n" + result(filtered=7),
             ["1 test programs were started and 0 results were read", "1 results leave tests out by a filter",
              "no test is counted as passed"]),
            (started + "\n" + result(passed=2, failed=1, word="FAILED"), ["1 tests are counted as failed"]),
            (started + "\ntest x ... FAILED\n" + result(passed=2), ["1 tests are counted as failed"]),
            (started + "\n" + result(passed=0), ["no test is counted as passed"]),
            (started + "\n" + result(passed=0, ignored=5), ["no test is counted as passed"]),
        ):
            self.assertEqual(self.doubts(text), said, text)


class Kept(unittest.TestCase):
    def test_a_short_text_is_kept_whole_and_a_long_one_by_its_two_ends(self):
        self.assertEqual(probe.kept("all of it\n"), "all of it\n")
        long = "HEAD" + "x" * (probe.KEPT * 2) + "TAIL"
        kept = probe.kept(long)
        self.assertTrue(kept.startswith("HEAD"))
        self.assertTrue(kept.endswith("TAIL"))
        self.assertIn("[... %d bytes of the middle are left out ...]" % (len(long) - probe.KEPT), kept)
        # As many bytes as it keeps of any text: a quarter from the start and the rest from the end.
        self.assertGreater(len(kept), probe.KEPT)
        self.assertLess(len(kept), probe.KEPT + 200)
        self.assertEqual(kept.index("\n[... "), probe.KEPT // 4)
        # At the limit, whole.
        self.assertEqual(probe.kept("y" * probe.KEPT), "y" * probe.KEPT)


class Limited(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pid_at = os.path.join(self.tmp.name, "pid")

    def pid(self):
        with open(self.pid_at, encoding="utf-8") as text:
            return int(text.read())

    def test_a_command_that_ends_gives_its_exit_and_both_its_streams(self):
        code, took, out, left = probe.limited(["/bin/sh", "-c", "echo one; echo two >&2; exit 7"], 20)
        self.assertEqual((code, left), (7, "nothing"))
        self.assertEqual(sorted(out.split()), ["one", "two"])
        self.assertLess(took, 10)

    def test_a_command_past_its_limit_is_ended_with_what_it_started_and_what_it_printed_is_kept(self):
        script = "echo before; sleep 300 & echo $! > %s; wait" % self.pid_at
        began = time.monotonic()
        code, took, out, left = probe.limited(["/bin/sh", "-c", script], 1)
        self.assertIsNone(code)
        self.assertEqual((out, left), ("before\n", "nothing"))
        self.assertGreaterEqual(took, 1)
        self.assertLess(time.monotonic() - began, 10)
        self.assertTrue(sleeper_gone(self.pid()), "what the command started outlived its limit")

    def test_what_a_command_leaves_running_is_ended_and_said_and_not_waited_for(self):
        # The sleeper holds the command's own output open, as a test's forgotten child would.
        script = "sleep 300 & echo $! > %s; echo done" % self.pid_at
        began = time.monotonic()
        code, _, out, left = probe.limited(["/bin/sh", "-c", script], 60)
        self.assertEqual((code, out, left), (0, "done\n", "processes it had started, ended now"))
        self.assertLess(time.monotonic() - began, 10)
        self.assertTrue(sleeper_gone(self.pid()), "what the command left running was not ended")

    def test_a_command_that_cannot_be_started_is_said(self):
        code, _, out, left = probe.limited([os.path.join(self.tmp.name, "not-there")], 5)
        self.assertEqual((code, left), (127, "nothing"))
        self.assertTrue(out.startswith("could not be started: "))

    def test_bytes_that_are_not_text_are_kept_as_text(self):
        code, _, out, _ = probe.limited(["/bin/sh", "-c", "printf 'a\\377b\\n'"], 20)
        self.assertEqual((code, out), (0, "a�b\n"))


CARGO = """#!/bin/sh
# Stands in for cargo: writes down what it was given, and prints what a run would.
case "$1 $2" in
"--version "*) echo "cargo 9.9.9 (stand-in)"; exit 0 ;;
esac
echo "$* | CARGO_HOME=$CARGO_HOME CARGO_TARGET_DIR=$CARGO_TARGET_DIR PWD=$PWD" >> "$STAND_IN/calls.txt"
case "$1 $2" in
"build "*) kind=build ;;
"test --no-run") kind=compile ;;
"test --no-fail-fast") kind=tests ;;
*) exit 64 ;;
esac
if [ -f "$STAND_IN/$kind.sleep" ]; then
    sleep 300 &
    echo $! > "$STAND_IN/sleeper.pid"
    cat "$STAND_IN/$kind.out" 2>/dev/null
    wait
fi
[ ! -f "$STAND_IN/$kind.wait" ] || sleep "$(cat "$STAND_IN/$kind.wait")"
cat "$STAND_IN/$kind.out" 2>/dev/null
exit "$(cat "$STAND_IN/$kind.exit" 2>/dev/null || echo 0)"
"""

PS_WORKS = """#!/bin/sh
echo "$*" >> "$STAND_IN/ps-calls.txt"
echo "    1     0     1 Sun Nov 15 09:00:00 2026"
echo "   77     1    77 Sun Nov 15 09:00:01 2026"
"""

PS_REFUSED = """#!/bin/sh
echo "ps: Operation not permitted" >&2
exit 1
"""


class Whole(unittest.TestCase):
    """The probe from its first line to its last, with scripts where cargo and ps would be."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        top = os.path.realpath(self.tmp.name)
        self.bin = os.path.join(top, "bin")
        self.root = os.path.join(top, "checkout")
        self.vendor = os.path.join(top, "vendor")
        for made in (self.bin, os.path.join(self.root, "v2"), self.vendor):
            os.makedirs(made)
        with open(os.path.join(self.root, "v2", "Cargo.toml"), "w", encoding="utf-8") as out:
            out.write("[workspace]\n")
        self.script("cargo", CARGO)
        self.script("ps", PS_WORKS)
        self.give("tests.out", GOOD + "\n")
        path = os.environ["PATH"]
        self.addCleanup(self.put_back, os.getcwd(), path, os.environ.get("STAND_IN"), probe.WHOLE)
        os.chdir(self.root)
        os.environ["PATH"] = self.bin + os.pathsep + path
        os.environ["STAND_IN"] = self.bin

    def put_back(self, cwd, path, stand_in, whole):
        os.chdir(cwd)
        os.environ["PATH"] = path
        if stand_in is None:
            os.environ.pop("STAND_IN", None)
        else:
            os.environ["STAND_IN"] = stand_in
        self.whole(whole)

    def whole(self, seconds):
        """The seconds the probe has for all of it, which a test shortens."""
        setattr(probe, "WHOLE", seconds)

    def script(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as out:
            out.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def give(self, name, content):
        with open(os.path.join(self.bin, name), "w", encoding="utf-8") as out:
            out.write(content)

    def calls(self):
        path = os.path.join(self.bin, "calls.txt")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as text:
            return text.read().splitlines()

    def run_probe(self, *words):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = probe.main(["probe.py", *words])
        return code, out.getvalue().splitlines()

    def line(self, lines, start):
        found = [line for line in lines if line.startswith(start)]
        self.assertEqual(len(found), 1, "%r in:\n%s" % (start, "\n".join(lines)))
        return found[0]

    def test_a_run_that_passes_says_each_part_and_all_that_cargo_printed(self):
        code, lines = self.run_probe(self.vendor)
        self.assertEqual(code, 0, "\n".join(lines))
        self.assertEqual(lines[0], "PROBE a plain cargo test of v2, in the place this is run from")
        self.assertTrue(lines[1].endswith(", in " + self.root), lines[1])
        self.assertEqual(self.line(lines, "PLACE processes: "), "PLACE processes: CAN list them as the room does (2 lines)")
        self.line(lines, "PLACE jail: ")
        self.assertEqual(self.line(lines, "cargo: "), "cargo: cargo 9.9.9 (stand-in)")
        self.assertRegex(self.line(lines, "BUILD "), r"^BUILD ok in \d+ s: `cargo build --locked --offline, ")
        self.assertRegex(self.line(lines, "COMPILE "), r"^COMPILE ok in \d+ s: `cargo test --no-run --locked ")
        self.assertRegex(
            self.line(lines, "TESTS "),
            r"^TESTS ok in \d+ s: `cargo test --no-fail-fast --locked --offline, from the vendored crates`, "
            r"under a limit of 240 s\. Every test that ran passed$",
        )
        at = lines.index(self.line(lines, "TESTS "))
        self.assertEqual(
            lines[at + 1: at + 8],
            [
                "  test programs started: 3, with 3 results (0 more that could not be read, and 0 of test programs"
                " that a failed test had started itself)",
                "  passed 4, failed 0, ignored 4",
                "  ignored, 2: " + ROOM,
                "  ignored, 1: no reason given",
                "  ignored, 1: run in a child process by a",
                "  left running in cargo's own group when it ended: nothing",
                "--- all that cargo printed:",
            ],
        )
        self.assertEqual(lines[at + 8: -2], GOOD.splitlines())
        self.assertEqual(lines[-2:], ["--- the end of what cargo printed", "PROBE DONE"])

    def test_cargo_is_given_the_vendored_crates_and_a_home_and_a_target_inside_the_checkout(self):
        self.run_probe(self.vendor)
        words = '--locked --offline --config source.crates-io.replace-with="vendored" --config ' \
            'source.vendored.directory="%s"' % self.vendor
        target = os.path.join(self.root, "v2", "target")
        where = " | CARGO_HOME=%s CARGO_TARGET_DIR=%s PWD=%s" % (
            os.path.join(target, "cargo-home"), target, os.path.join(self.root, "v2"))
        self.assertEqual(
            self.calls(),
            ["build " + words + where, "test --no-run " + words + where, "test --no-fail-fast " + words + where],
        )

    def test_the_look_at_processes_is_the_rooms_own(self):
        self.run_probe(self.vendor)
        with open(os.path.join(self.bin, "ps-calls.txt"), encoding="utf-8") as text:
            self.assertEqual(text.read().splitlines(), ["-o pid=,ppid=,pgid=,lstart= -A"])

    def test_a_place_that_cannot_list_processes_is_said_with_what_ps_said(self):
        self.script("ps", PS_REFUSED)
        code, lines = self.run_probe(self.vendor)
        self.assertEqual(code, 0)
        self.assertEqual(
            self.line(lines, "PLACE processes: "),
            "PLACE processes: CANNOT list them as the room does: `ps -o pid=,ppid=,pgid=,lstart= -A` ended with 1 "
            "and said: ps: Operation not permitted",
        )
        # A ps that ends well and lists nothing is no list either.
        self.script("ps", "#!/bin/sh\nexit 0\n")
        _, lines = self.run_probe(self.vendor)
        self.assertIn("CANNOT list them as the room does", self.line(lines, "PLACE processes: "))
        self.assertIn("ended with 0 and said: nothing", self.line(lines, "PLACE processes: "))

    def test_tests_that_fail_are_named_and_the_probe_ends_with_1(self):
        self.give("tests.out", FAILING + "\n")
        self.give("tests.exit", "101")
        code, lines = self.run_probe(self.vendor)
        self.assertEqual(code, 1)
        self.assertRegex(self.line(lines, "TESTS "), r"^TESTS failed with 101 after \d+ s: ")
        self.assertIn("  passed 1, failed 2, ignored 0", lines)
        self.assertIn("  failed: a_stop_leaves_no_ref", lines)
        self.assertIn("  failed: another", lines)
        self.assertIn("1 more that could not be read, and 1 of test programs", self.line(lines, "  test programs started"))
        self.assertEqual(lines[-1], "PROBE DONE")

    def test_a_good_exit_is_not_called_ok_without_the_harnesss_own_lines(self):
        # Cargo ends with 0 in each: a runner that started nothing, a program with no result, a result that
        # says a test failed, a result that cannot be read, a run with a filter, a run in which nothing passed.
        started = "     Running tests/a.rs (target/debug/deps/a-0123456789abcdef)"
        for name, text, said in (
            ("nothing printed", "", "no test program was started; no test is counted as passed"),
            ("no result", started, "1 test programs were started and 0 results were read"),
            ("a failed result", started + "\n" + result(passed=2, failed=1, word="FAILED"),
             "1 tests are counted as failed"),
            ("a result that cannot be read", started + "\ntest result: ok. some passed", "1 results could not be read"),
            ("a filter", started + "\n" + result(filtered=7), "1 results leave tests out by a filter"),
            ("nothing passed", started + "\n" + result(passed=0, ignored=5), "no test is counted as passed"),
        ):
            with self.subTest(name):
                self.give("tests.out", text + "\n")
                code, lines = self.run_probe(self.vendor)
                self.assertEqual(code, 1, "\n".join(lines))
                line = self.line(lines, "TESTS ")
                self.assertRegex(line, r"^TESTS not shown to have passed after \d+ s: `cargo test --no-fail-fast ")
                self.assertIn("Cargo ended with 0, and yet: ", line)
                self.assertIn(said, line)
                self.assertFalse(any(found.startswith("TESTS ok") for found in lines))
                self.assertEqual(lines[-1], "PROBE DONE")

    def test_tests_that_wait_are_ended_at_the_limit_with_all_they_started(self):
        self.give("tests.sleep", "")
        began = time.monotonic()
        code, lines = self.run_probe(self.vendor, "1")
        self.assertLess(time.monotonic() - began, 30)
        self.assertEqual(code, 1)
        self.assertRegex(
            self.line(lines, "TESTS "),
            r"^TESTS ended by the limit after \d+ s: .*, under a limit of 1 s\. A test waited, or they are slow here$",
        )
        # What was printed before the limit is still shown, and counted.
        self.assertIn("  passed 4, failed 0, ignored 4", lines)
        self.assertEqual(lines[-1], "PROBE DONE")
        with open(os.path.join(self.bin, "sleeper.pid"), encoding="utf-8") as text:
            self.assertTrue(sleeper_gone(int(text.read())), "a test's own process outlived the limit")

    def test_a_build_that_fails_runs_no_test_and_says_so(self):
        for kind, name, said in (("build", "BUILD", "the build"), ("compile", "COMPILE", "the tests' own build")):
            with self.subTest(kind):
                if os.path.exists(os.path.join(self.bin, "calls.txt")):
                    os.unlink(os.path.join(self.bin, "calls.txt"))
                self.give(kind + ".out", "error: could not compile `room`\nthe last line\n")
                self.give(kind + ".exit", "101")
                code, lines = self.run_probe(self.vendor)
                self.assertEqual(code, 1)
                self.assertRegex(self.line(lines, name + " "), "^%s failed with 101 after \\d+ s: " % name)
                self.assertIn("    the last line", lines)
                self.assertEqual(self.line(lines, "TESTS "), "TESTS not run: %s did not end well" % said)
                self.assertEqual(lines[-1], "PROBE DONE")
                self.assertFalse(any(call.startswith("test --no-fail-fast") for call in self.calls()))
                os.unlink(os.path.join(self.bin, kind + ".exit"))

    def test_builds_that_took_the_probes_time_leave_the_tests_for_a_second_run(self):
        self.whole(probe.LEAST + 6)
        self.give("build.wait", "2")
        code, lines = self.run_probe(self.vendor, "10")
        self.assertEqual(code, 1)
        self.assertRegex(
            self.line(lines, "TESTS "),
            r"^TESTS not run: the builds took the probe's time \(\d+ s of %d are gone\)\. Run it again: they are made$"
            % probe.WHOLE,
        )
        self.assertEqual(lines[-1], "PROBE DONE")
        self.assertFalse(any(call.startswith("test --no-fail-fast") for call in self.calls()))

    def test_a_build_past_the_probes_time_is_ended(self):
        self.whole(1)
        self.give("build.sleep", "")
        began = time.monotonic()
        code, lines = self.run_probe(self.vendor, "1")
        self.assertLess(time.monotonic() - began, 30)
        self.assertEqual(code, 1)
        self.assertRegex(self.line(lines, "BUILD "), r"^BUILD was ended at the probe's own limit after \d+ s: ")
        self.assertEqual(self.line(lines, "TESTS "), "TESTS not run: the build did not end well")
        with open(os.path.join(self.bin, "sleeper.pid"), encoding="utf-8") as text:
            self.assertTrue(sleeper_gone(int(text.read())), "a build's own process outlived the limit")

    def test_the_tests_limit_is_what_is_left_when_that_is_less(self):
        self.whole(100)
        _, lines = self.run_probe(self.vendor, "100")
        limit = int(self.line(lines, "TESTS ").split("under a limit of ")[1].split(" s")[0])
        self.assertGreaterEqual(limit, 85)
        self.assertLessEqual(limit, 95)

    def test_where_there_is_no_checkout_or_no_vendored_crates_nothing_is_built(self):
        os.unlink(os.path.join(self.root, "v2", "Cargo.toml"))
        code, lines = self.run_probe(self.vendor)
        self.assertEqual(code, 1)
        self.assertEqual(
            lines[-3:],
            [
                "BUILD not run: there is no v2/Cargo.toml here: run it at the root of a checkout",
                "TESTS not run: there is no v2/Cargo.toml here: run it at the root of a checkout",
                "PROBE DONE",
            ],
        )
        with open(os.path.join(self.root, "v2", "Cargo.toml"), "w", encoding="utf-8") as out:
            out.write("[workspace]\n")
        gone = os.path.join(self.vendor, "not-there")
        code, lines = self.run_probe(gone)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-2], "TESTS not run: the vendored crates' directory is not there: " + gone)
        self.assertEqual(self.calls(), [])

    def test_what_it_was_not_given_ends_with_2_and_still_ends_as_a_probe_ends(self):
        for words in ([], ["vendor"], [self.vendor, "abc"], [self.vendor, "0"], [self.vendor, "-5"],
                      [self.vendor, str(probe.WHOLE + 1)], [self.vendor, "10", "more"], [self.vendor, "1e2"]):
            code, lines = self.run_probe(*words)
            self.assertEqual(code, 2, words)
            self.assertTrue(lines[0].startswith("usage: "), words)
            self.assertEqual(lines[1:], ["TESTS not run: the probe was not given what it needs", "PROBE DONE"])
        self.assertEqual(self.calls(), [])


GIT = ["git", "-c", "user.name=probe test", "-c", "user.email=test@yak.invalid", "-c", "commit.gpgsign=false",
       "-c", "core.hooksPath=/dev/null"]
DONE = "PROBE a plain cargo test of v2\nTESTS ok in 12 s: `cargo test`\n  passed 4, failed 0, ignored 4\nPROBE DONE\n"


class Checks(unittest.TestCase):
    """Each check that judges a probe item, in a checkout made here. A check judges that the probe ran to its
    end and was handed in, and nothing of what the tests did."""

    def checks(self):
        found = [name for name in ("worker-tests-done-claude.sh", "worker-tests-done.sh")
                 if os.path.exists(os.path.join(CHECKS, name))]
        self.assertIn("worker-tests-done-claude.sh", found)
        return found

    def judged(self, check, content=None, tracked=True, make=None):
        """(exit, stdout, stderr) of a check in a repository that holds tests-run.txt with `content`."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.mkdir(repo)
            subprocess.run(GIT + ["init", "-q", repo], check=True)
            with open(os.path.join(repo, "other.txt"), "w", encoding="utf-8") as out:
                out.write("PROBE DONE\n")
            if make is not None:
                make(repo)
            elif content is not None:
                with open(os.path.join(repo, "tests-run.txt"), "wb") as out:
                    out.write(content if isinstance(content, bytes) else content.encode("utf-8"))
            if tracked:
                subprocess.run(GIT + ["-C", repo, "add", "-A"], check=True)
                subprocess.run(GIT + ["-C", repo, "commit", "-q", "-m", "handed in"], check=True)
            done = subprocess.run(["sh", os.path.join(CHECKS, check)], cwd=repo, capture_output=True, text=True,
                                  timeout=60, check=False)
            return done.returncode, done.stdout, done.stderr

    def test_a_probe_that_ran_to_its_end_and_was_handed_in_passes(self):
        for check in self.checks():
            with self.subTest(check):
                self.assertEqual(self.judged(check, DONE), (0, "ok\n", ""))
                # What the tests did is not the check's to judge.
                failed = DONE.replace("TESTS ok in 12 s", "TESTS failed with 101 after 12 s")
                self.assertEqual(self.judged(check, failed)[0], 0)
                self.assertEqual(self.judged(check, "TESTS not run: the build did not end well\nPROBE DONE\n")[0], 0)
                # The last line may lack its newline.
                self.assertEqual(self.judged(check, DONE.rstrip("\n"))[0], 0)
                # What cargo printed may hold any byte: a NUL, or bytes that are not text, away from the two lines.
                odd = b"TESTS ok in 3 s\n  a test printed \x00 and \xff\xfe and `rm -rf $(x)`; $HOME\nPROBE DONE\n"
                self.assertEqual(self.judged(check, odd), (0, "ok\n", ""))

    def test_what_is_not_a_finished_probes_file_fails(self):
        def link(repo):
            with open(os.path.join(repo, "real.txt"), "w", encoding="utf-8") as out:
                out.write(DONE)
            os.symlink("real.txt", os.path.join(repo, "tests-run.txt"))

        def directory(repo):
            os.mkdir(os.path.join(repo, "tests-run.txt"))
            with open(os.path.join(repo, "tests-run.txt", "inner"), "w", encoding="utf-8") as out:
                out.write(DONE)

        cases: tuple = (
            ("no file at all", {"content": None}),
            ("a file git does not track", {"content": DONE, "tracked": False}),
            ("a link to a finished file", {"make": link}),
            ("a directory of that name", {"make": directory}),
            ("the wrong commit's file", {"content": "PROBE a plain cargo test of v2, in the place this is run from\n"}),
            ("an empty file", {"content": ""}),
            ("a blank line after the end", {"content": DONE + "\n"}),
            ("the end, and then more", {"content": DONE + "more\n"}),
            ("the end with a space after it", {"content": DONE.rstrip("\n") + " \n"}),
            ("no line that begins with TESTS", {"content": DONE.replace("TESTS ok", "  TESTS ok")}),
            ("TESTS only inside a line", {"content": "the TESTS ran\nPROBE DONE\n"}),
            ("TESTS with nothing after it", {"content": "TESTS\nPROBE DONE\n"}),
            ("a file past the size a probe leaves", {"content": "TESTS ok\n" + "x" * 1_048_576 + "\nPROBE DONE\n"}),
            ("a NUL after the end's words", {"content": b"TESTS ok\nPROBE DONE\x00\n"}),
            ("a NUL inside the end's words", {"content": b"TESTS ok\nPROBE\x00 DONE\n"}),
            ("a NUL before TESTS", {"content": b"\x00TESTS ok\nPROBE DONE\n"}),
            ("a NUL inside TESTS", {"content": b"TES\x00TS ok\nPROBE DONE\n"}),
            ("a carriage return after the end", {"content": "TESTS ok\nPROBE DONE\r\n"}),
            ("one line with no end, holding both", {"content": "TESTS PROBE DONE"}),
        )
        for check in self.checks():
            for name, how in cases:
                with self.subTest(check=check, case=name):
                    code, out, err = self.judged(check, **how)
                    self.assertNotEqual(code, 0, name)
                    self.assertEqual(out, "", name)
                    self.assertTrue(err.startswith("FAIL "), err)

    def test_a_file_of_the_largest_size_passes(self):
        head = "TESTS ok\n"
        tail = "\nPROBE DONE\n"
        for check in self.checks():
            with self.subTest(check):
                content = head + "x" * (1_048_576 - len(head) - len(tail)) + tail
                self.assertEqual(self.judged(check, content)[0], 0)


if __name__ == "__main__":
    unittest.main()
