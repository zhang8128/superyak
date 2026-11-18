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
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("documents_plan_tests", HERE / "test_documents_plan.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

FAKE = r'''
import json, pathlib, sys
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
    turn = {"commit": base if mode in ("handed-in", "commit-at-limit") else None,
        "measured": {"ended": "timed_out" if mode in ("limit", "commit-at-limit") else "exited"},
        "passed": False, "attempt": "a0123456789ab"}
    turns = [] if mode == "clock-failed" else [turn]
    (room / "turns.json").write_text(json.dumps(turns))
    print("clock finished")
    sys.exit(7 if mode in ("clock-failed", "limit", "commit-at-limit") else 0)
elif words[:2] == ["item", "turns"]:
    if config.get("turns_fail"):
        print("cannot read turns", file=sys.stderr); sys.exit(8)
    print((room / "turns.json").read_text())
elif words[:2] == ["item", "walks"]:
    print(json.dumps({"steps": [], "attempt": "a0123456789ab"}))
else:
    sys.exit(9)
'''


class Outcomes(unittest.TestCase):
    def test_all_record_shapes(self):
        run = fixtures.module("documents_run")
        for value in (None, {}, [], [None], [{}, {}], [{"commit": "bad"}]):
            self.assertEqual(run.outcome(value, 0), ("clock-failed", None))
        for ended, code, wanted in (("timed_out", 7, "limit"), ("exited", 0, "no-hand-in"),
                ("exited", 1, "clock-failed"), ("unknown", 0, "clock-failed")):
            self.assertEqual(run.outcome([{"commit": None, "measured": {"ended": ended}}], code), (wanted, None))
        self.assertEqual(run.outcome([{"commit": None, "measured": []}], 0), ("clock-failed", None))
        for ended in ("timed_out", "exited"):
            self.assertEqual(run.outcome([{"commit": "a" * 40, "measured": {"ended": ended}}], 7), ("handed-in", "a" * 40))


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
                run.archive_interrupted(out, directory)
                self.assertTrue((out / "rows/interrupted/001-item-path-1").is_dir())
                directory.mkdir()
                run.archive_interrupted(out, directory)
                self.assertTrue((out / "rows/interrupted/001-item-path-2").is_dir())
                run.archive_interrupted(out, directory)
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

    def test_order_row_limit_recorded_rows_and_clock_contract(self):
        self.assertEqual(self.run.run_rows(self.out, rows=2), 2)
        self.assertEqual([r["n"] for r in self.records()], [1, 2])
        self.assertEqual(self.run.run_rows(self.out, rows=2), 2)
        self.assertEqual([r["n"] for r in self.records()], [1, 2, 3, 4])
        self.assertEqual(self.run.run_rows(self.out), 3)
        self.assertEqual(self.run.run_rows(self.out), 0)
        calls = [json.loads(l) for l in (self.tmp / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([c["n"] for c in calls], list(range(1, 8)))
        for call in calls:
            words = call["args"]
            for key, value in (("--daily-turns", "1"), ("--concurrent", "1"), ("--turn-secs", "1200"), ("--lease-secs", "1800")):
                self.assertEqual(words[words.index(key) + 1], value)
            self.assertNotIn("--own-prompts", words)
            self.assertEqual(call["env"]["PATH"], self.plan["environment"]["PATH"])
            self.assertNotIn("YAK", call["env"])
        for record, row in zip(self.records(), self.plan["order"]):
            self.assertEqual(set(record), {"n", "commit", "row", "began", "ended", "load_before", "load_after", "clock_exit", "outcome", "turn_commit", "at_limit"})
            self.assertEqual(record["commit"], row["commit"])
            self.assertEqual(record["row"], row["row"])
            directory = self.out / row["directory"]
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
        second = self.out / self.plan["order"][1]["directory"]
        second.mkdir()
        (self.out / "rows/interrupted" / (second.name + "-1")).mkdir()
        self.run.run_rows(self.out, rows=1)
        self.assertTrue((self.out / "rows/interrupted" / (second.name + "-2")).is_dir())

    def test_lock_and_changed_input_before_any_row(self):
        with (self.out / "run.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(self.run.Refused, "runner"):
                self.run.run_rows(self.out)
        self.task.write_text("changed")
        with self.assertRaisesRegex(self.run.Refused, "task.md"):
            self.run.run_rows(self.out)
        self.assertFalse((self.out / "rows").exists())

    def test_every_outcome_and_commit_at_limit(self):
        outcomes = {"1": "handed-in", "2": "no-hand-in", "3": "limit", "4": "clock-failed", "5": "commit-at-limit"}
        self.config.write_text(json.dumps({"outcomes": outcomes}))
        self.run.run_rows(self.out, rows=5)
        self.assertEqual([r["outcome"] for r in self.records()], ["handed-in", "no-hand-in", "limit", "clock-failed", "handed-in"])
        self.assertEqual([r["clock_exit"] for r in self.records()], [0, 0, 7, 7, 7])
        self.assertIsNone(self.records()[1]["turn_commit"])
        self.assertIsNotNone(self.records()[4]["turn_commit"])
        self.assertEqual([r["at_limit"] for r in self.records()], [False, False, True, False, True])

    def test_failed_export_is_recorded_and_not_rerun(self):
        self.config.write_text('{"turns_fail": true}')
        self.run.run_rows(self.out, rows=1)
        self.assertEqual(self.records()[0]["outcome"], "clock-failed")
        self.assertIn("cannot read turns", (self.out / self.plan["order"][0]["directory"] / "turns.err").read_text())
        self.config.write_text("{}")
        self.run.run_rows(self.out, rows=1)
        self.assertEqual([r["n"] for r in self.records()], [1, 2])

    def test_kept_out_objects_are_checked_before_room(self):
        row = self.plan["order"][0]
        item = self.plan["items"][0]
        item["kept_out"]["test_blobs"] = [fixtures.git(self.out / "src", "rev-parse", item["parent"] + ":peer/superyak_peer/work.py")]
        with self.assertRaisesRegex(self.run.Refused, "kept from"):
            self.run.run_turn(self.out, self.plan, row, item)
        self.assertFalse((self.out / row["directory"] / "room").exists())

    def test_invalid_row_cap_and_malformed_turn(self):
        with self.assertRaisesRegex(self.run.Refused, "nonnegative"):
            self.run.run_rows(self.out, rows=-1)
        for turns in ([], [None], [{}, {}], {}):
            self.assertEqual(self.run.outcome(turns, 0), ("clock-failed", None))
        self.assertEqual(self.run.outcome([{"commit": None, "measured": {"ended": "unknown"}}], 0), ("clock-failed", None))


if __name__ == "__main__":
    unittest.main()
