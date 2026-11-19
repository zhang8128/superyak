#!/usr/bin/env python3
"""A script answers as the room; it never runs a worker or a check."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("documents_plan_tests", HERE / "test_documents_plan.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

FAKE = r'''
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
if args == ["clock", "run", "--help"]:
    print("--turn-secs <TURN_SECS> [default: 1200]\n--lease-secs <LEASE_SECS> [default: 1800]")
    sys.exit(0)
here = pathlib.Path(__file__).resolve().parent
config = json.loads((here / "config.json").read_text())
room = pathlib.Path(args[1]); words = args[2:]
root = room.parent
if words == ["init"]:
    room.mkdir()
elif words[:2] == ["item", "add"]:
    (room / "add.json").write_text(json.dumps(words))
    print("i0123456789ab")
elif words[:2] == ["clock", "run"]:
    n = str(int(root.name.split("-", 1)[0]))
    mode = config.get("outcomes", {}).get(n, "handed-in")
    with (here / "calls.jsonl").open("a") as journal:
        journal.write(json.dumps({"n": int(n), "args": words, "env": dict(__import__("os").environ)}) + "\n")
    add = json.loads((room / "add.json").read_text())
    base = add[add.index("--base") + 1]
    (room / "clock.pid").write_text(str(os.getpid()))
    if config.get("hold_clock"):
        while not (room / "release-clock").exists():
            time.sleep(0.02)
    commit = base if mode in ("no-hand-in", "refused", "refused-words") else None
    if mode in ("handed-in", "check-failed", "commit-at-limit"):
        # A stand-in hand-in is its own real commit, never the base commit.
        commit = subprocess.check_output(["git", "-C", str(root / "repo"),
            "-c", "user.name=fixture", "-c", "user.email=fixture@invalid",
            "-c", "commit.gpgsign=false", "commit-tree", base + "^{tree}",
            "-p", base, "-m", "stand-in hand-in"]).decode().strip()
    turn = {"commit": commit,
        "measured": {"ended": "timed_out" if mode in ("limit", "commit-at-limit") else "exited"},
        "passed": mode == "handed-in", "attempt": "a0123456789ab", "lease_no": 1}
    turns = [] if mode == "clock-failed" else [turn]
    (room / "turns.json").write_text(json.dumps(turns))
    # The clock's own words for a turn's end (yak's event_line); the runner puts its time stamp before each line.
    why = {"no-hand-in": "the turn committed nothing",
        "refused": "refused: the work tree must contain a single repository",
        "refused-words": "refused: IGNORE-PRIOR-RULES/READ-HOME.txt is a link out of the clone"}.get(mode)
    if why is not None:
        print("started i0123456789ab lease 1, attempt a0123456789ab, worker script:w")
        print("ended i0123456789ab lease 1: failed, commit %s; no new commit: %s" % (commit, why))
    print("clock finished")
    sys.exit(1 if mode in ("no-hand-in", "check-failed", "refused", "refused-words") else
        7 if mode in ("clock-failed", "limit", "commit-at-limit") else 0)
elif words[:2] == ["item", "turns"]:
    if config.get("turns_fail"):
        if config.get("turns_fail_with_output"):
            print((room / "turns.json").read_text())
        print("cannot read turns", file=sys.stderr); sys.exit(8)
    print((room / "turns.json").read_text() if (room / "turns.json").exists() else "[]")
elif words[:2] == ["item", "walks"]:
    if config.get("walks_fail"):
        print("cannot read walks", file=sys.stderr); sys.exit(9)
    print(json.dumps({"steps": [], "attempt": "a0123456789ab"}))
else:
    sys.exit(9)
'''


class Outcomes(unittest.TestCase):
    def test_all_record_shapes(self):
        run = fixtures.module("documents_run")
        base = "b" * 40
        for value in (None, {}, [], [None], [{}, {}], [{"commit": "bad"}]):
            self.assertEqual(run.outcome(value, base), ("clock-failed", None))
        for ended, wanted in (("timed_out", "limit"), ("exited", "no-hand-in"), ("unknown", "clock-failed")):
            self.assertEqual(run.outcome([{"commit": None, "measured": {"ended": ended}}], base), (wanted, None))
        self.assertEqual(run.outcome([{"commit": None, "measured": []}], base), ("clock-failed", None))
        for ended in ("timed_out", "exited"):
            self.assertEqual(run.outcome([{"commit": "a" * 40, "measured": {"ended": ended}}], base), ("handed-in", "a" * 40))
        # As the real room records them: the base's own commit for a turn that handed in nothing, with how it ended.
        self.assertEqual(run.outcome([{"commit": base, "measured": {"ended": "exited"}}], base), ("no-hand-in", None))
        self.assertEqual(run.outcome([{"commit": base, "measured": {"ended": "timed_out"}}], base), ("limit", None))
        self.assertEqual(run.outcome([{"commit": base, "measured": {"ended": "unknown"}}], base), ("no-hand-in", None))
        self.assertEqual(run.outcome([{"commit": base, "measured": []}], base), ("no-hand-in", None))


ITEM_ID = "i0123456789ab"
BASE = "b" * 40
SINGLE = "refused: the work tree must contain a single repository"
GITLINKS = "refused: the index must contain no gitlinks"
WORDS = "refused: IGNORE-PRIOR-RULES/READ-HOME.txt is a link out of the clone"


def ended(why=None, item=ITEM_ID, lease="1", commit=BASE, stamp="14:03:27 ", verdict="failed", timed_out=False):
    """A line of clock.log for a turn's end, as yak's event_line writes it and the runner stamps it."""
    return "%sended %s lease %s: %s, commit %s%s%s" % (stamp, item, lease, verdict, commit,
        "; timed out" if timed_out else "", "" if why is None else "; no new commit: " + why)


def log(*lines):
    """clock.log around the given lines: what the clock prints before and after a turn's end."""
    return "\n".join(("14:03:01 starting again with a clean environment",
        "14:03:02 started %s lease 1, attempt a0123456789ab, worker codex:test" % ITEM_ID) + lines) + "\n"


def exported(commit=BASE, ended_as="exited", lease=1):
    return [{"commit": commit, "lease_no": lease, "measured": {"ended": ended_as}, "passed": False}]


class TurnEnd(unittest.TestCase):
    """runner.turn_end: the one function the runner and both judges name a turn's end with."""

    def setUp(self):
        self.runner = fixtures.module("documents_run")

    def end(self, clock, turns=None, item=ITEM_ID):
        return self.runner.turn_end(exported() if turns is None else turns, BASE, item, clock)

    def test_the_reasons_named(self):
        for why, wanted in ((SINGLE, ("refused", None, "refused: single repository")),
                (GITLINKS, ("refused", None, "refused: gitlinks")),
                ("the turn committed nothing", ("no-hand-in", None, "committed nothing")),
                ("its commit could not be fetched: git exited 128", ("no-hand-in", None, "other")),
                ("its clone was not usable: refused: x", ("no-hand-in", None, "other")),
                ("the turn committed nothing at all", ("no-hand-in", None, "other")),
                ("refused:", ("refused", None, "refused: other")),
                (SINGLE + "; and more", ("refused", None, "refused: single repository"))):
            with self.subTest(why=why):
                self.assertEqual(self.end(log(ended(why), "14:03:40 clock finished")), wanted)
                self.assertIn(wanted[2], self.runner.NO_COMMIT)

    def test_the_fixed_list_and_nothing_else(self):
        self.assertEqual(self.runner.NO_COMMIT, ("committed nothing", "refused: single repository", "refused: gitlinks",
            "refused: other", "other"))
        named = {self.runner.no_commit_of(why) for why in (SINGLE, GITLINKS, "the turn committed nothing", "refused: x",
            "x", "", "refused", "REFUSED: x", " refused: x")}
        self.assertEqual(named, set(self.runner.NO_COMMIT))
        for why, wanted in (("refused", "other"), ("refusedx", "other"), ("refused:x", "refused: other"),
                ("the turn committed nothing ", "other"), ("refused: the work tree must contain a single", "refused: other"),
                ("refused: the index must contain no gitlink", "refused: other")):
            self.assertEqual(self.runner.no_commit_of(why), wanted, why)

    def test_a_refusal_in_words_a_worker_could_choose_keeps_none_of_them(self):
        got = self.end(log(ended(WORDS)))
        self.assertEqual(got, ("refused", None, "refused: other"))
        for word in ("IGNORE", "PRIOR", "RULES", "READ-HOME", "link", "clone"):
            self.assertNotIn(word, json.dumps(got))

    def test_the_base_at_its_limit_is_a_limit_whatever_the_reason(self):
        for line in (ended(SINGLE), ended(SINGLE, timed_out=True)):
            self.assertEqual(self.end(log(line), exported(ended_as="timed_out")),
                ("limit", None, "refused: single repository"))
        self.assertEqual(self.end(log(ended("the turn committed nothing")), exported(ended_as="timed_out")),
            ("limit", None, "committed nothing"))
        # The clock's own "timed out" without the export's measured end decides nothing: the export's end does.
        self.assertEqual(self.end(log(ended(SINGLE, timed_out=True))), ("refused", None, "refused: single repository"))

    def test_a_commit_of_its_own_is_handed_in_with_no_reason(self):
        c = "c" * 40
        for ended_as in ("timed_out", "exited"):
            for clock in (log(ended(commit=c, verdict="passed verified")), log(ended(SINGLE, commit=c)),
                    log(ended(SINGLE))):
                self.assertEqual(self.end(clock, exported(c, ended_as)), ("handed-in", c, None))

    def test_matched_on_item_lease_and_commit_with_the_stamp(self):
        self.assertEqual(self.end(log(ended(SINGLE, stamp="09:00:00 "))), ("refused", None,
            "refused: single repository"))
        self.assertEqual(self.end(log(ended(SINGLE)), exported(lease=12)), ("no-hand-in", None, None))
        self.assertEqual(self.end(log(ended(SINGLE, lease="12")), exported(lease=12)),
            ("refused", None, "refused: single repository"))
        for verdict in ("passed unverified", "abandoned"):
            self.assertEqual(self.end(log(ended(SINGLE, verdict=verdict)))[2], "refused: single repository")

    def test_what_is_not_this_turns_ended_event_is_not_evidence(self):
        today = ("no-hand-in", None, None)
        for clock in ("", "\n", log(),
                log(ended(SINGLE, item="i9999999999ab")),
                log(ended(SINGLE, item=ITEM_ID + "x")),
                log(ended(SINGLE, lease="2")),
                log(ended(SINGLE, lease="01")),
                log(ended(SINGLE, commit="c" * 40)),
                log(ended(SINGLE, stamp="")),                        # the clock's words with no stamp
                log(ended(SINGLE, stamp="14:03 ")),
                log(" " + ended(SINGLE)),
                log(ended(SINGLE, verdict="Failed")),
                log(ended(SINGLE, verdict="a b c")),
                log("14:03:27 problem with %s: no new commit: %s" % (ITEM_ID, SINGLE)),
                log("14:03:27 not checked: no new commit: " + SINGLE),
                log("14:03:27 worker said: " + ended(SINGLE)),
                log("no new commit: " + SINGLE),
                log(ended(None)),                                     # the event, with no reason given
                log(ended(SINGLE), ended(SINGLE)),                    # two: neither is taken
                log(ended(SINGLE), ended("the turn committed nothing"))):
            with self.subTest(clock=clock):
                self.assertEqual(self.end(clock), today)
        # An item given as empty text matches no event, and neither does a line with no item in it.
        self.assertEqual(self.end(log(ended(SINGLE, item="")), item=""), today)
        # The clock's form, to its colon after the lease.
        self.assertEqual(self.end(log(ended(SINGLE).replace(" lease 1: ", " lease 1 "))), today)
        # A line is what the runner wrote up to its newline: another separator inside one starts no line of its own.
        for separator in (chr(0x2028), chr(0x85), chr(0x0b), chr(0x0d)):
            self.assertEqual(self.end(log("14:03:27 problem with %s: x%s%s" % (ITEM_ID, separator, ended(SINGLE)))),
                today, hex(ord(separator)))
        # Two events of which only one is this turn's: that one is taken. A line that only begins as this turn's
        # event (its commit runs on) is not one.
        for other in (ended(SINGLE, lease="2"), ended("the turn committed nothing", commit=BASE + "0"),
                ended(commit=BASE) + "; rechecked: failed"):
            self.assertEqual(self.end(log(ended(SINGLE), other)), ("refused", None, "refused: single repository"), other)

    def test_an_export_that_failed_or_is_not_one_turn_beside_a_refusal(self):
        clock = log(ended(SINGLE))
        self.assertEqual(self.runner.turn_end(self.runner.EXPORT_FAILED, BASE, ITEM_ID, clock), ("export-failed", None, None))
        for turns in (None, {}, [], [None], exported() * 2, [{"commit": "bad", "lease_no": 1}],
                [{"commit": BASE.upper(), "lease_no": 1, "measured": {"ended": "exited"}}],
                [{"commit": None, "lease_no": 1, "measured": {"ended": "unknown"}}], "export-failed"):
            with self.subTest(turns=turns):
                self.assertEqual(self.runner.turn_end(turns, BASE, ITEM_ID, clock), ("clock-failed", None, None))
        # A turn with no commit at all is named as before: nothing in the clock's output is its.
        for ended_as, kind in (("exited", "no-hand-in"), ("timed_out", "limit")):
            self.assertEqual(self.runner.turn_end([{"commit": None, "lease_no": 1, "measured": {"ended": ended_as}}], BASE,
                ITEM_ID, clock), (kind, None, None))

    def test_hostile_clock_output_and_exports_raise_nothing(self):
        today = ("no-hand-in", None, None)
        long_line = "14:03:27 ended " + "a" * 2000000
        near = "14:03:27 ended %s lease 1: failed, commit %s; no new commit: " % (ITEM_ID, BASE)
        for clock in ("", long_line, "x" * 2000000, log(long_line), near[:-1] + "\ud800",
                log("\ud800" + ended(SINGLE)), log(ended(SINGLE, item="\ud800")), None, b"", log(ended(SINGLE)).encode(),
                1, ["14:03:27"]):
            with self.subTest(clock=repr(clock)[:80]):
                self.assertEqual(self.end(clock), today)
        for commit in ("b" * 39, "b" * 41, "B" * 40, "g" * 40, BASE + " "):
            with self.subTest(commit=commit):
                self.assertEqual(self.end(log(ended(SINGLE, commit=commit))), today)
        for lease in ("1", "x", True, 1.0, None, -1, [1]):
            with self.subTest(lease=lease):
                self.assertEqual(self.end(log(ended(SINGLE)), exported(lease=lease)), today)
        for lease in ("x", "-1", "\u0661", "1.0", "", " 1"):
            with self.subTest(line_lease=lease):
                self.assertEqual(self.end(log(ended(SINGLE, lease=lease))), today)
        self.assertEqual(self.end(log(ended(SINGLE)), [{"commit": BASE, "measured": {"ended": "exited"}}]), today)
        for item in (None, 1, ""):
            self.assertEqual(self.end(log(ended(SINGLE)), item=item), today)
        # A lone surrogate inside the reason of this turn's event is still a reason, and none of it is kept.
        self.assertEqual(self.end(log(ended("refused: \ud800"))), ("refused", None, "refused: other"))

    def test_the_clock_log_read_from_a_file(self):
        with __import__("tempfile").TemporaryDirectory() as folder:
            path = Path(folder) / "clock.log"
            self.assertEqual(self.runner.read_clock(path), "")                     # none there: empty, not an error
            path.write_bytes(log(ended(SINGLE)).encode())
            self.assertEqual(self.runner.turn_end(exported(), BASE, ITEM_ID, self.runner.read_clock(path)),
                ("refused", None, "refused: single repository"))
            for raw in (b"\xff\xfe\x00", b"\xed\xa0\x80", b"14:03:27 \xed\xa0\x80" + ended(SINGLE, stamp="").encode(),
                    b"\x80" * 100000):
                path.write_bytes(raw)
                text = self.runner.read_clock(path)
                self.assertIsInstance(text, str)
                self.assertEqual(self.runner.turn_end(exported(), BASE, ITEM_ID, text), ("no-hand-in", None, None))
            # Bytes that are not UTF-8 on another line leave this turn's event readable.
            path.write_bytes(b"\xff\xfe junk\n" + log(ended(SINGLE)).encode() + b"\xed\xa0\x80\n")
            self.assertEqual(self.runner.turn_end(exported(), BASE, ITEM_ID, self.runner.read_clock(path))[2],
                "refused: single repository")
            directory = Path(folder) / "a-directory"
            directory.mkdir()
            self.assertEqual(self.runner.read_clock(directory), "")

    def test_outcome_is_turn_end_with_no_clock_output(self):
        for turns in (exported(), exported(ended_as="timed_out"), exported("c" * 40), None, [], exported() * 2):
            self.assertEqual(self.runner.outcome(turns, BASE), self.runner.turn_end(turns, BASE, ITEM_ID, "")[:2])
        with mock.patch.object(self.runner, "turn_end", return_value=("x", "y", "z")) as named:
            self.assertEqual(self.runner.outcome(exported(), BASE), ("x", "y"))
        named.assert_called_once_with(exported(), BASE, None, "")


class WrittenBy(unittest.TestCase):
    def test_an_item_is_never_written_by_its_workers_family(self):
        # The real room's take() skips an item whose writer has the worker's family: found on the real room, where
        # every row of a script worker ended with no turn. No stand-in here knows that rule.
        run = fixtures.module("documents_run")
        self.assertEqual(run.written_by("script:/some/worker.sh"), "claude:probe")
        self.assertEqual(run.written_by("codex:gpt-6.1-sol"), "script:probe")
        self.assertEqual(run.written_by("claude:opus"), "script:probe")
        self.assertEqual(run.written_by("scripted:x"), "script:probe")
        for worker in ("script:/some/worker.sh", "codex:gpt-6.1-sol", "claude:opus", "script", "scripted:x"):
            self.assertNotEqual(run.written_by(worker).split(":", 1)[0], worker.split(":", 1)[0])


class Archives(unittest.TestCase):
    def test_distinct_archive_names_and_bounded_loop(self):
        run = fixtures.module("documents_run")
        with __import__("tempfile").TemporaryDirectory() as folder:
            out = Path(folder)
            directory = out / "rows/001-item-path"
            directory.mkdir(parents=True)
            def expired(*args):
                raise AssertionError("archive loop failed to finish")
            before = signal.signal(signal.SIGALRM, expired)
            signal.alarm(2)
            try:
                self.assertEqual(run.archive_interrupted(out, directory), [
                    {"directory": "rows/interrupted/001-item-path-1", "started": False, "clock_exited": False}])
                self.assertTrue((out / "rows/interrupted/001-item-path-1").is_dir())
                directory.mkdir()
                (directory / "started.txt").write_text("began\n")
                (directory / "clock.exit").write_text("1\n")
                attempts = run.archive_interrupted(out, directory)
                self.assertEqual(attempts[-1], {"directory": "rows/interrupted/001-item-path-2", "started": True, "clock_exited": True})
                self.assertTrue((out / "rows/interrupted/001-item-path-2").is_dir())
                self.assertEqual(run.archive_interrupted(out, directory), attempts)
                (out / "rows/interrupted/001-item-path-3").write_text("not an attempt directory")
                self.assertEqual(run.archive_interrupted(out, directory), attempts)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, before)


class Runner(fixtures.Fixture):
    def setUp(self):
        super().setUp()
        self.yak.write_text("#!" + sys.executable + "\n" + FAKE)
        self.config = self.tmp / "config.json"
        self.config.write_text("{}")
        self.plan = self.make()
        self.controls = self.out / "controls" / self.commit[:10]
        self.controls.mkdir(parents=True)
        (self.controls / "cases.json").write_text(json.dumps({"commit": self.commit, "cases": ["tests/test_work.py::test_new"],
            "counts": {"passed": 1, "failed": 0, "error": 0, "skipped": 0}}))
        (self.controls / "parent.json").write_text(json.dumps({"commit": self.commit, "passed": []}))
        self.run = fixtures.module("documents_run")

    def records(self):
        return [json.loads((self.out / r["directory"] / "record.json").read_text())
            for r in self.plan["order"] if (self.out / r["directory"] / "record.json").exists()]

    def test_cli_zero_rows_and_refusal(self):
        command = ["sh", str(HERE / "documents.sh"), "run", str(self.out), "--rows", "0"]
        done = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("rows recorded: 0", done.stdout)
        self.task.write_text("changed")
        done = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("REFUSED:", done.stderr)

    def test_later_items_controls_are_required_before_first_turn(self):
        later = dict(self.plan["items"][0], commit="c" * 40, item="c" * 10)
        self.plan["items"].append(later)
        self.plan["order"].append(dict(self.plan["order"][-1], commit=later["commit"], item=later["item"]))
        (self.out / "plan.json").unlink()
        self.driver.pilot.write_json(self.out / "plan.json", self.plan)
        (self.out / "plan.sha256").write_text(self.driver.digest((self.out / "plan.json").read_bytes()) + "\n")
        with self.assertRaisesRegex(self.run.Refused, later["item"]):
            self.run.run_rows(self.out, rows=1)
        self.assertEqual(self.records(), [])
        self.assertFalse((self.tmp / "calls.jsonl").exists())

    def test_controls_gate_precedes_any_row(self):
        cases = (self.controls / "cases.json").read_bytes()
        parent = (self.controls / "parent.json").read_bytes()
        bad = [("cases.json", None), ("cases.json", b"{}"), ("cases.json", b"["),
            ("cases.json", json.dumps({"commit": "a" * 40, "cases": ["case"]}).encode()),
            ("cases.json", json.dumps({"commit": self.commit, "cases": []}).encode()),
            ("cases.json", json.dumps({"commit": self.commit, "cases": "case"}).encode()),
            ("parent.json", None), ("parent.json", b"{}"), ("parent.json", b"[]")]
        for name, content in bad:
            with self.subTest(name=name, content=content):
                (self.controls / "cases.json").write_bytes(cases)
                (self.controls / "parent.json").write_bytes(parent)
                if content is None:
                    (self.controls / name).unlink()
                else:
                    (self.controls / name).write_bytes(content)
                with self.assertRaisesRegex(self.run.Refused, self.commit[:10]):
                    self.run.run_rows(self.out, rows=1)
                self.assertFalse((self.out / "rows").exists())
        (self.controls / "cases.json").write_bytes(cases)
        (self.controls / "parent.json").write_bytes(parent)
        self.assertEqual(self.run.run_rows(self.out, rows=1), 1)

    def test_failure_to_start_clock_is_recorded(self):
        original = self.run.subprocess.Popen
        def fail_clock(argv, *args, **kwargs):
            if Path(argv[0]).resolve() == self.yak.resolve() and argv[3:5] == ["clock", "run"]:
                raise OSError("fixture could not start clock")
            return original(argv, *args, **kwargs)
        with mock.patch.object(self.run.subprocess, "Popen", side_effect=fail_clock):
            self.run.run_rows(self.out, rows=1)
        self.assertEqual(self.records()[0]["outcome"], "clock-failed")
        self.assertEqual(self.records()[0]["clock_exit"], -1)
        self.assertFalse((self.out / self.plan["order"][0]["directory"] / "started.txt").exists())

    def test_order_row_limit_recorded_rows_and_clock_contract(self):
        self.assertEqual(self.run.run_rows(self.out, rows=2), 2)
        self.assertEqual([r["n"] for r in self.records()], [1, 2])
        self.assertEqual(self.run.run_rows(self.out, rows=2), 2)
        self.assertEqual([r["n"] for r in self.records()], [1, 2, 3, 4])
        self.assertEqual(self.run.run_rows(self.out), 4)
        self.assertEqual(self.run.run_rows(self.out), 0)
        calls = [json.loads(l) for l in (self.tmp / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([c["n"] for c in calls], list(range(1, 9)))
        self.assertEqual({record["row"] for record in self.records()},
            {"nothing-1", "nothing-2", "exists", "path", "search", "newest", "lot", "bm25"})
        for call in calls:
            words = call["args"]
            for key, value in (("--daily-turns", "1"), ("--concurrent", "1"), ("--turn-secs", "1200"), ("--lease-secs", "1800")):
                self.assertEqual(words[words.index(key) + 1], value)
            self.assertNotIn("--own-prompts", words)
            self.assertEqual(call["env"]["PATH"], self.plan["environment"]["PATH"])
            self.assertNotIn("YAK", call["env"])
        for record, row in zip(self.records(), self.plan["order"]):
            self.assertEqual(set(record), {"n", "commit", "row", "began", "ended", "load_before", "load_after", "clock_exit", "outcome", "turn_commit", "no_commit", "at_limit", "turns_exit", "walks_exit", "earlier_attempts", "attempts", "interrupted_attempts"})
            self.assertEqual((record["turns_exit"], record["walks_exit"]), (0, 0))
            self.assertEqual((record["earlier_attempts"], record["attempts"], record["interrupted_attempts"]), (0, [], 0))
            self.assertEqual(record["commit"], row["commit"])
            self.assertEqual(record["row"], row["row"])
            directory = self.out / row["directory"]
            self.assertEqual((directory / "repo/TASK.md").read_bytes(), self.driver.task_bytes(
                self.task.read_bytes(), self.plan["items"][0]["rows"][row["row"]]["paragraph"]))
            for name in ("repo", "room", "item.txt", "started.txt", "ended.txt", "load-before.txt", "load-after.txt", "clock.log", "clock.exit", "turns.json", "walks.jsonl", "walks.err"):
                self.assertTrue((directory / name).exists(), name)
            self.assertFalse((directory / "record.tmp").exists())

    def test_interrupted_row_is_preserved_and_retried_once(self):
        directory = self.out / self.plan["order"][0]["directory"]
        directory.mkdir(parents=True)
        (directory / "partial.txt").write_text("old attempt")
        self.assertEqual(self.run.run_rows(self.out, rows=1), 1)
        saved = self.out / "rows/interrupted" / (directory.name + "-1")
        self.assertEqual((saved / "partial.txt").read_text(), "old attempt")
        self.assertEqual(self.run.run_rows(self.out, rows=0), 0)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(len(list((self.out / "rows/interrupted").iterdir())), 1)
        self.assertEqual(self.records()[0]["earlier_attempts"], 1)
        self.assertEqual(self.records()[0]["interrupted_attempts"], 0)
        self.assertEqual(self.records()[0]["attempts"], [
            {"directory": str(saved.relative_to(self.out)), "started": False, "clock_exited": False}])
        second = self.out / self.plan["order"][1]["directory"]
        second.mkdir()
        (self.out / "rows/interrupted" / (second.name + "-1")).mkdir()
        self.run.run_rows(self.out, rows=1)
        self.assertTrue((self.out / "rows/interrupted" / (second.name + "-2")).is_dir())

    def test_archived_attempts_distinguish_refused_running_and_finished(self):
        row = self.plan["order"][0]
        directory = self.out / row["directory"]
        # Unequal running/finished counts expose a reversed clock-exit predicate.
        for started, finished in ((False, False), (True, False), (True, False), (True, True)):
            directory.mkdir(parents=True)
            if started:
                (directory / "started.txt").write_text("began\n")
            if finished:
                (directory / "clock.exit").write_text("1\n")
            self.run.archive_interrupted(self.out, directory)
        self.run.run_rows(self.out, rows=1)
        record = self.records()[0]
        self.assertEqual(record["earlier_attempts"], 4)
        self.assertEqual(record["interrupted_attempts"], 2)
        self.assertEqual([(a["started"], a["clock_exited"]) for a in record["attempts"]],
            [(False, False), (True, False), (True, False), (True, True)])
        self.assertEqual(len(list((self.out / "rows/interrupted").iterdir())), 4)

    def test_preclock_fetch_refusal_is_not_an_interrupted_turn(self):
        row = self.plan["order"][0]
        base = self.plan["items"][0]["rows"][row["row"]]
        ref = "refs/documents/%s/%s" % (row["item"], row["row"])
        fixtures.git(self.out / "src", "update-ref", ref, base["wrong"])
        with self.assertRaisesRegex(self.run.Refused, "fetched base differs"):
            self.run.run_rows(self.out, rows=1)
        directory = self.out / row["directory"]
        self.assertFalse((directory / "started.txt").exists())
        self.assertFalse((self.tmp / "calls.jsonl").exists())
        fixtures.git(self.out / "src", "update-ref", ref, base["base"])
        self.run.run_rows(self.out, rows=1)
        self.assertEqual(self.records()[0]["earlier_attempts"], 1)
        self.assertEqual(self.records()[0]["interrupted_attempts"], 0)
        self.assertEqual([(a["started"], a["clock_exited"]) for a in self.records()[0]["attempts"]], [(False, False)])

    def test_lock_and_changed_input_before_any_row(self):
        with (self.out / "run.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(self.run.Refused, "runner"):
                self.run.run_rows(self.out)
        self.task.write_text("changed")
        with self.assertRaisesRegex(self.run.Refused, "task.md"):
            self.run.run_rows(self.out)
        self.assertFalse((self.out / "rows").exists())

    def wait_for(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("stand-in process did not reach the expected state")

    def test_clock_keeps_lock_after_runner_is_killed(self):
        self.config.write_text('{"hold_clock": true}')
        directory = self.out / self.plan["order"][0]["directory"]
        room = directory / "room"
        command = ["sh", str(HERE / "documents.sh"), "run", str(self.out), "--rows", "1"]
        runner = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        clock_pid = None
        try:
            self.wait_for(lambda: (room / "clock.pid").exists() and (directory / "started.txt").exists())
            clock_pid = int((room / "clock.pid").read_text())
            self.config.write_text("{}")
            runner.kill()
            runner.communicate(timeout=5)
            self.assertEqual(runner.returncode, -signal.SIGKILL)
            os.kill(clock_pid, 0)
            second = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(second.returncode, 1, second.stdout + second.stderr)
            self.assertIn("another runner holds run.lock", second.stderr)
            self.assertFalse((self.out / "rows/interrupted").exists())
            (room / "release-clock").touch()
            def released():
                try:
                    with self.run.runner_lock(self.out):
                        return True
                except self.run.Refused:
                    return False
            self.wait_for(released)
        finally:
            if runner.poll() is None:
                runner.kill()
            runner.communicate(timeout=5)
            if clock_pid is not None:
                try:
                    os.kill(clock_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_inherited_lock_survives_runner_context_exit(self):
        # A shared LOCK_UN would release the child's lock too. Closing only the
        # parent's descriptor must leave the inherited descriptor holding it.
        with self.run.runner_lock(self.out) as lock_fd:
            child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                pass_fds=(lock_fd,), stdin=subprocess.PIPE)
        try:
            with self.assertRaisesRegex(self.run.Refused, "runner"):
                self.run.run_rows(self.out, rows=0)
        finally:
            child.communicate(timeout=5)
        self.assertEqual(self.run.run_rows(self.out, rows=0), 0)

    def test_every_outcome_and_commit_at_limit(self):
        outcomes = {"1": "handed-in", "2": "no-hand-in", "3": "limit", "4": "clock-failed", "5": "commit-at-limit", "6": "check-failed"}
        self.config.write_text(json.dumps({"outcomes": outcomes}))
        self.run.run_rows(self.out, rows=6)
        self.assertEqual([r["outcome"] for r in self.records()], ["handed-in", "no-hand-in", "limit", "clock-failed", "handed-in", "handed-in"])
        self.assertEqual([r["clock_exit"] for r in self.records()], [0, 1, 7, 7, 7, 1])
        self.assertIsNone(self.records()[1]["turn_commit"])
        self.assertIsNotNone(self.records()[4]["turn_commit"])
        self.assertEqual([r["at_limit"] for r in self.records()], [False, False, True, False, True, False])
        directory = self.out / self.plan["order"][1]["directory"]
        turn = json.loads((directory / "turns.json").read_text())[0]
        item_row = self.plan["items"][0]["rows"][self.plan["order"][1]["row"]]
        self.assertEqual(turn["commit"], item_row["base"])
        self.assertEqual(turn["measured"]["ended"], "exited")
        self.assertFalse(turn["passed"])
        self.assertIn("no new commit: the turn committed nothing", (directory / "clock.log").read_text())

    def test_a_refused_hand_in_is_named_from_the_clocks_line_and_its_words_are_not_kept(self):
        outcomes = {"1": "refused", "2": "refused-words", "3": "no-hand-in", "4": "handed-in", "5": "commit-at-limit"}
        self.config.write_text(json.dumps({"outcomes": outcomes}))
        self.run.run_rows(self.out, rows=5)
        records = self.records()
        self.assertEqual([(r["outcome"], r["no_commit"]) for r in records], [("refused", "refused: single repository"),
            ("refused", "refused: other"), ("no-hand-in", "committed nothing"), ("handed-in", None), ("handed-in", None)])
        self.assertEqual([r["turn_commit"] is None for r in records], [True, True, True, False, False])
        self.assertEqual([r["at_limit"] for r in records], [False, False, False, False, True])
        self.assertEqual([r["clock_exit"] for r in records], [1, 1, 1, 0, 7])
        directory = self.out / self.plan["order"][1]["directory"]
        # The clock's line, with the runner's stamp, is beside the row as before; the record holds none of its words.
        self.assertRegex((directory / "clock.log").read_text(),
            r"(?m)^[0-9]{2}:[0-9]{2}:[0-9]{2} ended i0123456789ab lease 1: failed, commit [0-9a-f]{40}; no new commit: "
            r"refused: IGNORE-PRIOR-RULES")
        raw = (directory / "record.json").read_text()
        for word in ("IGNORE", "PRIOR", "READ-HOME", "link out"):
            self.assertNotIn(word, raw)

    def test_a_failed_export_beside_a_refusal_line_is_export_failed(self):
        self.config.write_text(json.dumps({"outcomes": {"1": "refused"}, "turns_fail": True, "turns_fail_with_output": True}))
        self.run.run_rows(self.out, rows=1)
        record = self.records()[0]
        self.assertEqual((record["outcome"], record["turn_commit"], record["no_commit"], record["turns_exit"]),
            ("export-failed", None, None, 8))
        self.assertIn("no new commit: refused:", (self.out / self.plan["order"][0]["directory"] / "clock.log").read_text())

    def test_failed_export_is_recorded_and_not_rerun(self):
        self.config.write_text('{"turns_fail": true}')
        self.run.run_rows(self.out, rows=1)
        self.assertEqual(self.records()[0]["outcome"], "export-failed")
        self.assertEqual((self.records()[0]["turns_exit"], self.records()[0]["walks_exit"]), (8, 0))
        self.assertIn("cannot read turns", (self.out / self.plan["order"][0]["directory"] / "turns.err").read_text())
        self.config.write_text("{}")
        self.run.run_rows(self.out, rows=1)
        self.assertEqual([r["n"] for r in self.records()], [1, 2])

    def test_failed_walks_export_preserves_finished_turn_outcome(self):
        self.config.write_text('{"walks_fail": true}')
        self.run.run_rows(self.out, rows=1)
        record = self.records()[0]
        self.assertEqual(record["outcome"], "handed-in")
        self.assertIsNotNone(record["turn_commit"])
        self.assertEqual((record["turns_exit"], record["walks_exit"]), (0, 9))
        directory = self.out / self.plan["order"][0]["directory"]
        self.assertIn("cannot read walks", (directory / "walks.err").read_text())

    def test_failed_turns_export_does_not_trust_partial_output(self):
        self.config.write_text(json.dumps({"outcomes": {"1": "commit-at-limit"},
            "turns_fail": True, "turns_fail_with_output": True}))
        self.run.run_rows(self.out, rows=1)
        record = self.records()[0]
        self.assertEqual(record["turns_exit"], 8)
        self.assertEqual(record["outcome"], "export-failed")
        self.assertIsNone(record["turn_commit"])
        self.assertFalse(record["at_limit"])
        directory = self.out / self.plan["order"][0]["directory"]
        self.assertEqual(json.loads((directory / "turns.json").read_text())[0]["measured"]["ended"], "timed_out")

    def test_stopped_controls_refuse_even_with_success_markers(self):
        (self.controls / "stopped.json").write_text("{}")
        with self.assertRaisesRegex(self.run.Refused, "controls stopped"):
            self.run.run_rows(self.out, rows=1)
        self.assertFalse((self.out / "rows").exists())

    def test_kept_out_objects_are_checked_before_room(self):
        row = self.plan["order"][0]
        item = self.plan["items"][0]
        item["kept_out"]["test_blobs"] = [fixtures.git(self.out / "src", "rev-parse", item["parent"] + ":peer/superyak_peer/work.py")]
        with self.run.runner_lock(self.out) as lock_fd:
            with self.assertRaisesRegex(self.run.Refused, "kept from"):
                self.run.run_turn(self.out, self.plan, row, item, lock_fd)
        self.assertFalse((self.out / row["directory"] / "room").exists())

    def test_invalid_row_cap_and_malformed_turn(self):
        for cap in (-1, True, 0.5):
            with self.subTest(cap=cap), self.assertRaisesRegex(self.run.Refused, "nonnegative"):
                self.run.run_rows(self.out, rows=cap)
        self.assertEqual(self.run.run_rows(self.out, rows=0), 0)
        self.assertFalse((self.out / "rows").exists())
        for turns in ([], [None], [{}, {}], {}):
            self.assertEqual(self.run.outcome(turns, self.base), ("clock-failed", None))
        self.assertEqual(self.run.outcome([{"commit": None, "measured": {"ended": "unknown"}}], self.base), ("clock-failed", None))


if __name__ == "__main__":
    unittest.main()
