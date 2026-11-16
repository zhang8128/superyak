#!/usr/bin/env python3
"""Tests of suite_guard.py and of whole-suite.sh. Run as: python3 -I test_suite_guard.py

No cargo is run: every log here is made by hand, and the cargo that whole-suite.sh starts is a script that
prints one of them and writes down the words it was given.
"""
import contextlib
import importlib.util
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest

# Nothing is left beside the scripts by running these.
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("suite_guard", os.path.join(HERE, "suite_guard.py"))
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

LISTED = ["Doc-tests room", "Running tests/store.rs [store]", "Running unittests src/lib.rs [room]"]


def started(name, where="target/debug/deps"):
    """The line cargo prints when it starts a program the list names."""
    if name.startswith("Doc-tests "):
        return "   " + name
    words, binary = name[: -1].rsplit(" [", 1)
    return "     %s (%s/%s-0123456789abcdef)" % (words, where, binary)


def result(passed=3, failed=0, ignored=0, filtered=0, word="ok"):
    return "test result: %s. %d passed; %d failed; %d ignored; 0 measured; %d filtered out; finished in 0.52s" % (
        word,
        passed,
        failed,
        ignored,
        filtered,
    )


def whole(names=LISTED, **parts):
    """A log as a whole run prints one: each program started, its tests, its result."""
    lines = ["   Compiling room v0.1.0 (/somewhere/v2/crates/room)"]
    for name in names:
        lines += [started(name), "", "running 3 tests", "test one ... ok", "", result(**parts), ""]
    return lines


class Judged(unittest.TestCase):
    def wrong(self, lines, expected=LISTED):
        return guard.judge(lines, expected)[0]

    def test_a_whole_run_with_nothing_left_out_is_passed_and_counted(self):
        wrong, seen = guard.judge(whole(), LISTED)
        self.assertEqual(wrong, [])
        self.assertEqual(seen, "3 test programs, 3 result lines, 9 tests passed")

    def test_one_ignored_test_is_named_with_its_line(self):
        lines = whole()
        at = lines.index(result())
        lines[at] = result(passed=2, ignored=1)
        wrong = self.wrong(lines)
        self.assertEqual(len(wrong), 1)
        self.assertIn("line %d leaves 1 out as ignored" % (at + 1), wrong[0])

    def test_one_filtered_test_is_named(self):
        lines = whole()
        lines[lines.index(result())] = result(filtered=40)
        wrong = self.wrong(lines)
        self.assertEqual(len(wrong), 1)
        self.assertIn("leaves 40 out by a filter", wrong[0])

    def test_a_failed_test_is_not_this_guards_to_report(self):
        lines = whole()
        lines[lines.index(result())] = result(passed=2, failed=1, word="FAILED")
        self.assertEqual(self.wrong(lines), [])

    def test_a_listed_program_that_was_not_started_is_named(self):
        wrong = self.wrong(whole(LISTED[:2]))
        self.assertEqual(wrong, ["in the list, and not started: Running unittests src/lib.rs [room]"])

    def test_a_started_program_that_is_not_listed_is_named(self):
        wrong = self.wrong(whole(LISTED + ["Running tests/new.rs [new]"]))
        self.assertEqual(len(wrong), 1)
        self.assertIn("started, and not in the list", wrong[0])
        self.assertIn("Running tests/new.rs [new]", wrong[0])

    def test_a_program_started_twice_is_one_too_many_unless_listed_twice(self):
        twice = LISTED + [LISTED[1]]
        self.assertEqual(len(self.wrong(whole(twice))), 1)
        self.assertEqual(self.wrong(whole(twice), expected=twice), [])
        # Listed twice and started once: the second is missing.
        self.assertEqual(self.wrong(whole(), expected=twice), ["in the list, and not started: " + LISTED[1]])

    def test_a_program_that_printed_no_result_is_seen(self):
        lines = whole()
        del lines[lines.index(result())]
        wrong = self.wrong(lines)
        self.assertEqual(wrong, ["3 test programs were started and there are 2 result lines: one for each is expected"])

    def test_a_result_line_more_than_the_programs_is_seen(self):
        # A test that starts the test program again, and lets what it prints through.
        lines = whole() + [result(passed=1)]
        wrong = self.wrong(lines)
        self.assertEqual(wrong, ["3 test programs were started and there are 4 result lines: one for each is expected"])

    def test_a_result_line_that_cannot_be_read_is_not_passed_over(self):
        for bad in (
            "test result: ok. many passed",
            "test result: ok. 3 passed; 0 failed; -1 ignored; 0 measured; 0 filtered out; finished in 0.52s",
            "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.52s and more",
            "test result:",
        ):
            lines = whole()
            lines[lines.index(result())] = bad
            wrong = self.wrong(lines)
            self.assertEqual(len(wrong), 1, bad)
            self.assertIn("a result that could not be read", wrong[0])

    def test_a_log_with_no_program_is_not_a_pass(self):
        for lines in ([], [""], ["   Compiling room v0.1.0"], [result()]):
            wrong = self.wrong(lines)
            self.assertIn("no test program was started, by this log", wrong)
            self.assertTrue(any(line.startswith("in the list, and not started") for line in wrong))

    def test_a_line_that_only_holds_cargos_words_is_not_a_program(self):
        # What a test printed, or cargo's words set otherwise than cargo sets them.
        for line in (
            "Running tests/fake.rs (target/debug/deps/fake-0123456789abcdef)",
            "    Running tests/fake.rs (target/debug/deps/fake-0123456789abcdef)",
            "      Running tests/fake.rs (target/debug/deps/fake-0123456789abcdef)",
            "     Running tests/fake.rs",
            "Doc-tests fake",
            "    Doc-tests fake",
            "   Doc-tests fake and more",
            " test result: ok. 3 passed; 0 failed; 9 ignored; 0 measured; 0 filtered out; finished in 0.52s",
        ):
            self.assertEqual(self.wrong(whole() + [line]), [], line)

    def test_a_program_is_named_without_its_build_or_where_it_was_built(self):
        self.assertEqual(
            guard.program("     Running tests/store.rs (/home/someone/a b/target/debug/deps/store-00112233aabbccdd)"),
            "Running tests/store.rs [store]",
        )
        self.assertEqual(
            guard.program("     Running unittests src/main.rs (target/debug/deps/yak-00112233aabbccdd)"),
            "Running unittests src/main.rs [yak]",
        )
        # A name that only looks as if it ended in a build's hash keeps what is its own.
        self.assertEqual(
            guard.program("     Running tests/x.rs (target/debug/deps/x-00112233aabbccd)"),
            "Running tests/x.rs [x-00112233aabbccd]",
        )
        # Only the end is a build's: the same shape earlier in a name is the name's.
        self.assertEqual(
            guard.program("     Running tests/x.rs (target/debug/deps/x-00112233aabbccdd-y-00112233aabbccdd)"),
            "Running tests/x.rs [x-00112233aabbccdd-y]",
        )
        self.assertEqual(guard.program("   Doc-tests room"), "Doc-tests room")
        self.assertIsNone(guard.program("test one ... ok"))


class Run(unittest.TestCase):
    """The program as it is called: a log file and a list file, an exit, what it prints."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, content):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as out:
            out.write(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def run_guard(self, *words):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = guard.main(["suite_guard.py", *words])
        return code, out.getvalue(), err.getvalue()

    def the_list(self, names=LISTED):
        return self.file("list.txt", "# what a whole run starts\n\n" + "\n".join(names) + "\n   \n")

    def test_a_whole_run_ends_with_0_and_says_what_it_saw(self):
        code, out, err = self.run_guard(self.file("log", "\n".join(whole())), self.the_list())
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            "suite guard: every test ran: 3 test programs, 3 result lines, 9 tests passed, none ignored, "
            "none filtered out, the programs as listed\n",
        )

    def test_an_ignored_test_ends_with_1_and_is_printed(self):
        lines = whole()
        lines[lines.index(result())] = result(passed=2, ignored=1)
        code, out, _ = self.run_guard(self.file("log", "\n".join(lines)), self.the_list())
        self.assertEqual(code, 1)
        self.assertIn("NOT every test ran", out)
        self.assertIn("leaves 1 out as ignored", out)

    def test_colour_and_carriage_returns_do_not_hide_a_line(self):
        lines = whole()
        at = lines.index(started(LISTED[1]))
        lines[at] = "\x1b[1m\x1b[92m     Running\x1b[0m tests/store.rs (target/debug/deps/store-0123456789abcdef)"
        log = self.file("log", "\r\n".join(lines))
        self.assertEqual(self.run_guard(log, self.the_list())[0], 0)
        ignored = [result(passed=2, ignored=1) if line == result() else line for line in lines]
        self.assertEqual(self.run_guard(self.file("log2", "\r\n".join(ignored)), self.the_list())[0], 1)

    def test_bytes_that_are_not_text_are_read_past(self):
        noise = b"\xff\xfe\x00\x00 \xed\xa0\x80 " + b"x" * 300_000 + b"\n"
        log = self.file("log", noise + "\n".join(whole()).encode("utf-8") + b"\n" + noise)
        code, out, err = self.run_guard(log, self.the_list())
        self.assertEqual((code, err), (0, ""), out)

    def test_an_empty_log_ends_with_1(self):
        code, out, _ = self.run_guard(self.file("log", ""), self.the_list())
        self.assertEqual(code, 1)
        self.assertIn("no test program was started", out)

    def test_what_it_was_not_given_ends_with_2(self):
        log = self.file("log", "\n".join(whole()))
        missing = os.path.join(self.tmp.name, "not-there")
        for words in ([], [log], [log, self.the_list(), "more"], ["--other", log], ["--programs"]):
            code, out, err = self.run_guard(*words)
            self.assertEqual((code, out), (2, ""), words)
            self.assertIn("usage:", err)
        for words, said in (
            ([missing, self.the_list()], "the log could not be read"),
            ([log, missing], "the list could not be read"),
            ([log, self.file("bad-list", b"\xff\xfe")], "the list could not be read"),
            ([log, self.file("empty-list", "# nothing\n\n")], "the list names no test program"),
            (["--programs", missing], "the log could not be read"),
            ([self.tmp.name, self.the_list()], "the log could not be read"),
        ):
            code, out, err = self.run_guard(*words)
            self.assertEqual((code, out), (2, ""), words)
            self.assertIn(said, err)

    def test_the_programs_of_a_log_are_printed_in_the_lists_own_form(self):
        log = self.file("log", "\n".join(whole(list(reversed(LISTED)), ignored=2)))
        code, out, err = self.run_guard("--programs", log)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), LISTED)

    def test_the_list_in_the_repository_is_one_it_can_read(self):
        names = guard.listed(os.path.join(HERE, "test-programs.txt"))
        self.assertGreater(len(names), 0)
        self.assertEqual(names, sorted(names))
        for name in names:
            self.assertEqual(guard.program(started(name)), name)


CARGO = """#!/bin/sh
# Stands in for cargo: writes down the words it was given, and prints what a run would.
echo "$*" >> "$STAND_IN/calls.txt"
case $1 in
build) echo "    Finished dev profile"; exit "$(cat "$STAND_IN/build.exit")" ;;
test) cat "$STAND_IN/test.out"; echo "a word to stderr" >&2; exit "$(cat "$STAND_IN/test.exit")" ;;
esac
exit 64
"""


class WholeSuite(unittest.TestCase):
    """whole-suite.sh with a cargo that is a script: the words cargo is given, the exit, what the log keeps."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        path = os.path.join(self.dir, "cargo")
        with open(path, "w", encoding="utf-8") as out:
            out.write(CARGO)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        self.names = guard.listed(os.path.join(HERE, "test-programs.txt"))

    def given(self, lines, test_exit=0, build_exit=0):
        for name, content in (("test.out", "\n".join(lines) + "\n"), ("test.exit", str(test_exit)),
                              ("build.exit", str(build_exit))):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as out:
                out.write(content)

    def run_it(self, *words, cwd=None):
        env = dict(os.environ, PATH=self.dir + os.pathsep + os.environ["PATH"], STAND_IN=self.dir)
        done = subprocess.run(
            ["bash", os.path.join(HERE, "whole-suite.sh"), *words],
            env=env, cwd=cwd or self.dir, capture_output=True, text=True, timeout=60, check=False,
        )
        calls = []
        if os.path.exists(os.path.join(self.dir, "calls.txt")):
            with open(os.path.join(self.dir, "calls.txt"), encoding="utf-8") as text:
                calls = text.read().splitlines()
        return done, calls

    def log(self, name="suite.log"):
        with open(os.path.join(self.dir, name), encoding="utf-8") as text:
            return text.read()

    def test_it_builds_then_asks_for_every_test_and_passes_a_whole_run(self):
        self.given(whole(self.names))
        done, calls = self.run_it("suite.log")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            calls,
            ["build --workspace --bins --locked", "test --workspace --locked --no-fail-fast -- --include-ignored"],
        )
        log = self.log()
        # The log keeps all of it: the build, the tests' two streams, the guard's line, the exit.
        for part in ("Finished dev profile", "a word to stderr", started(self.names[0]),
                     "suite guard: every test ran: %d test programs" % len(self.names), "whole suite: exit 0 after "):
            self.assertIn(part, log)
            self.assertIn(part, done.stdout)

    def test_a_test_left_ignored_fails_it_though_cargo_passed(self):
        lines = whole(self.names)
        lines[lines.index(result())] = result(passed=2, ignored=1)
        self.given(lines)
        done, _ = self.run_it("suite.log")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("leaves 1 out as ignored", self.log())
        self.assertIn("whole suite: exit 1 after ", self.log())

    def test_a_program_that_was_not_started_fails_it_though_cargo_passed(self):
        self.given(whole(self.names[:-1]))
        done, _ = self.run_it("suite.log")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("in the list, and not started: " + self.names[-1], self.log())

    def test_cargos_own_exit_is_kept_when_a_test_failed(self):
        self.given(whole(self.names), test_exit=101)
        done, _ = self.run_it("suite.log")
        self.assertEqual(done.returncode, 101, done.stdout + done.stderr)
        self.assertIn("whole suite: exit 101 after ", self.log())
        # And when the guard finds something too, it is still cargo's.
        self.given(whole(self.names[:-1]), test_exit=101)
        done, _ = self.run_it("suite.log")
        self.assertEqual(done.returncode, 101, done.stdout + done.stderr)
        self.assertIn("in the list, and not started", self.log())

    def test_a_build_that_fails_runs_no_test(self):
        self.given(whole(self.names), build_exit=101)
        done, calls = self.run_it("suite.log")
        self.assertEqual(done.returncode, 101, done.stdout + done.stderr)
        self.assertEqual(calls, ["build --workspace --bins --locked"])
        self.assertIn("the build failed with 101", self.log())
        self.assertIn("no test was run", self.log())

    def test_more_words_go_to_cargo_before_the_tests_own(self):
        self.given(whole(self.names))
        done, calls = self.run_it("suite.log", "--offline", "--config", "a=\"b c\"")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            calls,
            [
                "build --workspace --bins --locked --offline --config a=\"b c\"",
                "test --workspace --locked --no-fail-fast --offline --config a=\"b c\" -- --include-ignored",
            ],
        )

    def test_an_old_log_is_not_added_to(self):
        with open(os.path.join(self.dir, "suite.log"), "w", encoding="utf-8") as out:
            out.write(result(ignored=5) + "\n")
        self.given(whole(self.names))
        done, _ = self.run_it("suite.log")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn("5 ignored", self.log())

    def test_the_log_is_where_the_caller_said_from_where_the_caller_stood(self):
        self.given(whole(self.names))
        inner = os.path.join(self.dir, "inner")
        os.mkdir(inner)
        done, _ = self.run_it("../from-inner.log", cwd=inner)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("whole suite: exit 0", self.log("from-inner.log"))

    def test_without_a_log_it_runs_nothing(self):
        self.given(whole(self.names))
        done, calls = self.run_it()
        self.assertEqual((done.returncode, calls), (2, []))
        self.assertIn("usage:", done.stderr)


if __name__ == "__main__":
    unittest.main()
