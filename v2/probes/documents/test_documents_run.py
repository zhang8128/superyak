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
    commit = base if mode == "no-hand-in" else None
    if mode in ("handed-in", "check-failed", "commit-at-limit"):
        # A stand-in hand-in is its own real commit, never the base commit.
        commit = subprocess.check_output(["git", "-C", str(root / "repo"),
            "-c", "user.name=fixture", "-c", "user.email=fixture@invalid",
            "-c", "commit.gpgsign=false", "commit-tree", base + "^{tree}",
            "-p", base, "-m", "stand-in hand-in"]).decode().strip()
    turn = {"commit": commit,
        "measured": {"ended": "timed_out" if mode in ("limit", "commit-at-limit") else "exited"},
        "passed": mode == "handed-in", "attempt": "a0123456789ab"}
    turns = [] if mode == "clock-failed" else [turn]
    (room / "turns.json").write_text(json.dumps(turns))
    print("no new commit: the turn committed nothing" if mode == "no-hand-in" else "clock finished")
    sys.exit(1 if mode in ("no-hand-in", "check-failed") else
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
            self.assertEqual(run.outcome([{"commit": base, "measured": {"ended": ended}}], base), ("no-hand-in", None))


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
            self.assertEqual(set(record), {"n", "commit", "row", "began", "ended", "load_before", "load_after", "clock_exit", "outcome", "turn_commit", "at_limit", "turns_exit", "walks_exit", "earlier_attempts", "attempts", "interrupted_attempts"})
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
