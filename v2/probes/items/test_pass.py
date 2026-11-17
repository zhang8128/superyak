#!/usr/bin/env python3
"""Pass tests: toy item repositories and stand-in programs, no model or jail.

Run: python3 -I test_pass.py. Real-clock tests are selected with YAK_PASS_JAIL=1
and YAK pointing to a built room program on a host that can enter its jail.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


pilot_tests = module("test_pilot")

# Reuse the pilot's stand-in clock and repository operations; add the public
# history CLI and the offer metadata the pass requires. This is no room/jail.
FAKE_HISTORY = r'''
if args[:2] == ["history", "make"]:
    import hashlib
    plan = json.loads(pathlib.Path(args[args.index("--plan") + 1]).read_text())
    out = pathlib.Path(args[args.index("--out") + 1]); out.mkdir()
    listing = {"v": 1, "repo": "b" * 40, "measure": {"name": "share", "version": 1}, "turns": []}
    for n, row in enumerate(plan["items"]):
        turns = json.loads((pathlib.Path(row["room"]) / "turns.json").read_text())
        turn = turns[0]
        standing = ("passed_verified" if turn["passed"] else "failed")
        if n in config.get("unverified", []):
            standing = "passed_unverified"
        walk = {"attempt": turn["attempt"], "item": row["item"], "standing": standing}
        raw = (json.dumps(walk, sort_keys=True, separators=(",", ":")) + "\n").encode()
        # Inject after the stand-in's make, so the pass independently checks the
        # inclusive newline limit. Real room check would reject changed walks
        # for walk.store_mismatch; its make allows 1 MiB *before* adding LF.
        if n == 0 and config.get("walk_line"):
            raw = raw[:-2] + b',"padding":"' + b'x' * (config["walk_line"] - len(raw) - 13) + b'"}\n'
        (out / (turn["attempt"] + ".jsonl")).write_bytes(raw)
        listing["turns"].append(dict(walk, sha256=hashlib.sha256(raw).hexdigest()))
    listing["turns"].sort(key=lambda r: r["attempt"])
    raw = json.dumps(listing, sort_keys=True, separators=(",", ":")).encode()
    (out / "history.json").write_bytes(raw)
    print(config.get("printed_hash", hashlib.sha256(raw).hexdigest())); sys.exit(0)
if args[:2] == ["history", "check"]:
    import hashlib
    if config.get("check_refuses"):
        print("refused: stand-in admission", file=sys.stderr); sys.exit(1)
    raw = pathlib.Path(args[args.index("--list") + 1]).read_bytes()
    print(config.get("check_hash", config.get("printed_hash", hashlib.sha256(raw).hexdigest()))); sys.exit(0)
'''

PASS_FAKE = pilot_tests.FAKE.replace("room = pathlib.Path(args[1]); words = args[2:]", FAKE_HISTORY +
    "\nroom = pathlib.Path(args[1]); words = args[2:]")
PASS_FAKE = PASS_FAKE.replace('mode = config.get("mode", "passed")', '''mode = config.get("mode", "passed")
    manifest = json.loads((root / "manifest.json").read_text())
    slug = manifest["slug"]
    mode = config.get("modes", {}).get(slug, mode)
    if root.parent.name in config.get("reference_modes", {}):
        mode = config["reference_modes"][root.parent.name]
    if manifest.get("slot") == config.get("failed_at"):
        mode = "failed"''')
PASS_FAKE = PASS_FAKE.replace('turn = {"worker": worker', '''import hashlib
    offered = None
    if "--arm" in words:
        offered = {"arm": words[words.index("--arm") + 1], "order": int(words[words.index("--order") + 1]),
            "seed": int(words[words.index("--seed") + 1])}
        offered.update(config.get("offered", {}))
    turn = {"attempt": "a" + hashlib.sha256(str(room).encode()).hexdigest()[:12], "offered": offered,
        "worker": worker''')
PASS_FAKE = PASS_FAKE.replace('(root.parent / "STOP").touch()', '(root.parent.parent / "STOP").touch()')
PASS_FAKE = PASS_FAKE.replace('(room / "turns.json").write_text', '''if config.get("no_verdict"):
        turn["passed"] = None
    (room / "turns.json").write_text''')
PASS_FAKE = PASS_FAKE.replace('elif words[:2] == ["item", "turns"]:', '''elif words[:2] == ["item", "list"]:
    print(json.dumps(config.get("items", [{"id": "i0123456789ab"}])))
elif words[:2] == ["item", "turns"]:''')


class PassScripts(unittest.TestCase):
    git = pilot_tests.PilotScripts.git
    write_list = pilot_tests.PilotScripts.write_list
    configure = pilot_tests.PilotScripts.configure
    run_script = pilot_tests.PilotScripts.run_script

    def setUp(self):
        pilot_tests.PilotScripts.setUp(self)
        self.three = [e["commit"] for e in self.entries]
        history = []
        for n in range(8):
            self.git("commit", "-q", "--allow-empty", "-m", "history %d" % n)
            commit = self.git("rev-parse", "HEAD")
            for kind in ("base", "wrong", "reference"):
                self.git("update-ref", "refs/yak-items/%s/%s" % (commit, kind), getattr(self, kind))
            history.append(dict(self.entries[0], commit=commit, part="history",
                check=json.loads(json.dumps(self.entries[0]["check"]))))
        self.entries = history + self.entries
        self.history_commits = [e["commit"] for e in history]
        self.write_list()
        self.store = self.bin / "store"
        self.store.write_text("#!/bin/sh\nexit 0\n")
        self.store.chmod(0o755)
        self.store_file = self.bin / "store.py"
        self.store_file.write_text("# store source\n")
        self.worker = self.bin / "worker"
        self.worker.write_text("#!/bin/sh\nexit 0\n")
        self.worker.chmod(0o755)
        self.env.update(YAK_STORE=str(self.store), YAK_STORE_FILES=str(self.store_file))
        self.yak.write_text("#!" + sys.executable + "\n" + PASS_FAKE)
        self.out = self.tmp / "pass"

    def plan(self, three=None, history=None, env=None, extra=(), worker=None, seed=20261117):
        return self.run_script("pass.sh", "plan", self.out, self.items, worker or "script:" + str(self.worker),
            "--three", *(self.three if three is None else three), "--history",
            *(self.history_commits if history is None else history), "--seed", str(seed), *extra, env=env)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def refused(self, result, text):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(text, result.stdout + result.stderr)

    def read(self, name):
        return json.loads((self.out / name).read_text())

    def screen(self, failures=(), instrument=None, instrument_outcome="another tree", verified=None):
        driver = module("pass_driver")

        def reference(out, items, commit):
            out.mkdir()
            outcome = "check failed" if commit in failures else "passed"
            if instrument == commit:
                outcome = instrument_outcome
            driver.pilot.write_json(out / "reference.json", {"outcome": outcome,
                "verified": outcome == "passed" if verified is None else verified})
            return 0 if outcome == "passed" else 1

        with mock.patch.dict(os.environ, self.env), mock.patch.object(driver.pilot, "reference", side_effect=reference):
            return driver.screen(self.out)

    def ready_history(self, **config):
        self.configure(**config)
        self.ok(self.plan())
        self.assertEqual(self.screen(), 0)
        self.ok(self.run_script("pass.sh", "history", self.out))

    def test_plan_freezes_inputs_and_every_turn_without_running(self):
        self.ok(self.plan(extra=("--rounds", "2")))
        plan = self.read("plan.json")
        self.assertEqual(plan["v"], 1)
        self.assertEqual(plan["items_sha256"], hashlib.sha256(self.list.read_bytes()).hexdigest())
        self.assertEqual(plan["lock_sha256"], "f" * 64)
        self.assertEqual(plan["rounds"], 2)
        self.assertEqual(plan["seed"], 20261117)
        self.assertEqual(plan["store_version"], "3")
        self.assertTrue(plan["own_prompts"])
        self.assertEqual(plan["limits"]["in_force"]["daily-turns"], 1)
        self.assertEqual(plan["limits"]["in_force"]["concurrent"], 1)
        self.assertEqual(len(plan["order"]), 27)
        self.assertEqual([r["commit"] for r in plan["order"][1:9]], self.history_commits)
        self.assertEqual([r["order"] for r in plan["order"]], list(range(1, 28)))
        self.assertEqual(plan["order"][0]["first_kept_of"], self.history_commits)
        self.assertTrue({"yak", "worker", "store", "python3", "git", "shell", "worker_shell"}.issubset(plan["programs"]))
        jail = module("pass_driver").jail_program()
        if jail:
            self.assertEqual(plan["programs"]["jail"]["path"], jail)
        for held in plan["programs"].values():
            self.assertEqual(held["sha256"], hashlib.sha256(Path(held["path"]).read_bytes()).hexdigest())
        self.assertEqual(plan["store_files"], [{"path": str(self.store_file),
            "sha256": hashlib.sha256(self.store_file.read_bytes()).hexdigest()}])
        calls = [json.loads(x) for x in (self.bin / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls, [["clock", "run", "--help"]])
        self.assertFalse((self.out / "turns").exists())

    def test_plan_cardinality_duplicates_overlap_and_nonitems(self):
        cases = [(self.three[:2], self.history_commits, "exactly three"),
                 (self.three, self.history_commits[:3], "at least four"),
                 (self.three[:2] + self.three[:1], self.history_commits, "repeated"),
                 (self.three, self.history_commits + self.history_commits[:1], "repeated"),
                 (self.three, self.history_commits[:4] + self.three[:1], "overlap"),
                 (self.three[:2] + ["e" * 40], self.history_commits, "not in the list")]
        for three, history, reason in cases:
            self.refused(self.plan(three, history), reason)
            self.assertFalse(self.out.exists())
        self.entries[0]["reason"] = "unusable"
        self.write_list()
        self.refused(self.plan(), "not eligible")
        self.assertFalse(self.out.exists())

    def test_four_history_allowed_and_list_order_wins(self):
        # Eight is the live selection; at least four is the rehearsal's safety gate.
        self.ok(self.plan(three=self.three[::-1], history=self.history_commits[:4][::-1]))
        plan = self.read("plan.json")
        self.assertEqual(plan["three"], self.three)
        self.assertEqual(plan["history"], self.history_commits[:4])
        self.assertEqual(plan["rounds"], 1)

    def test_plan_another_seed_two_rounds_hand_worked(self):
        for n, old in enumerate(self.three, 1):
            row = next(e for e in self.entries if e["commit"] == old)
            row["commit"] = str(n) * 40
            for kind in ("base", "wrong", "reference"):
                self.git("update-ref", "refs/yak-items/%s/%s" % (row["commit"], kind), row[kind])
        self.three = [c * 40 for c in "123"]
        self.write_list()
        self.ok(self.plan(seed=7, extra=("--rounds", "2")))
        # Hash ordering is worked independently in ArmOrder's seed-7 comment.
        expected = ["route", "nothing", "shuffled", "route", "shuffled", "nothing",
                    "shuffled", "route", "nothing", "shuffled", "route", "nothing",
                    "shuffled", "route", "nothing", "shuffled", "nothing", "route"]
        self.assertEqual([r["arm"] for r in self.read("plan.json")["order"][9:]], expected)

    def test_plan_checks_source_refs_and_forty_digit_item_ids(self):
        old = self.three[0]
        row = next(e for e in self.entries if e["commit"] == old)
        row["commit"] = "a" * 64
        self.three[0] = row["commit"]
        self.write_list()
        self.refused(self.plan(), "forty lowercase commit digits")
        self.assertFalse(self.out.exists())
        row["commit"] = self.three[0] = old
        self.write_list()
        self.git("update-ref", "-d", "refs/yak-items/%s/base" % old)
        self.refused(self.plan(), "failed")
        self.assertFalse(self.out.exists())

    def test_existing_output_and_missing_store_leave_nothing(self):
        for key in ("YAK_STORE", "YAK_STORE_FILES"):
            self.refused(self.plan(env=dict(self.env, **{key: ""})), key)
            self.assertFalse(self.out.exists())
        self.refused(self.plan(env=dict(self.env, YAK_STORE=str(self.bin))), "YAK_STORE")
        self.assertFalse(self.out.exists())
        self.store.chmod(0o644)
        self.refused(self.plan(), "YAK_STORE")
        self.assertFalse(self.out.exists())
        self.store.chmod(0o755)
        self.refused(self.plan(env=dict(self.env, YAK_STORE_FILES=str(self.store_file) + os.pathsep)), "YAK_STORE_FILES")
        self.assertFalse(self.out.exists())
        self.ok(self.plan())
        held = (self.out / "plan.json").read_bytes()
        calls = (self.bin / "calls.jsonl").read_bytes()
        self.refused(self.plan(), "exists")
        self.assertEqual((self.out / "plan.json").read_bytes(), held)
        self.assertEqual((self.bin / "calls.jsonl").read_bytes(), calls)

    def test_changed_input_refuses_every_later_command(self):
        self.ok(self.plan())
        for path, diagnostic in [(self.list, "items.json"), (self.yak, "yak"), (self.store_file, "store.py"),
                                 (self.store, "store"), (self.worker, "worker")]:
            held = path.read_bytes()
            path.write_bytes(held + b"\n")
            for command in ("screen", "history", "list"):
                self.refused(self.run_script("pass.sh", command, self.out), diagnostic)
            path.write_bytes(held)
        self.store_file.unlink()
        for command in ("screen", "history", "list"):
            self.refused(self.run_script("pass.sh", command, self.out), "store.py")

    def test_plan_numeric_worker_lock_and_path_guards(self):
        for kwargs, reason in [({"extra": ("--rounds", "0")}, "rounds must be positive"),
                               ({"seed": -1}, "seed nonnegative"),
                               ({"worker": "script:a b"}, "one word"),
                               ({"worker": "other:model"}, "script, claude or codex"),
                               ({"worker": "codex"}, "script, claude or codex"),
                               ({"worker": "script:"}, "path or model"),
                               ({"worker": "script:relative"}, "absolute path"),
                               ({"worker": "script:/nonexistent-worker"}, "worker is not an executable")]:
            self.refused(self.plan(**kwargs), reason)
            self.assertFalse(self.out.exists())
        self.refused(self.plan(env=dict(self.env, YAK_PROBE_PATH="relative:" + self.env["YAK_PROBE_PATH"])), "absolute directories")
        self.assertFalse(self.out.exists())
        self.list.write_text(json.dumps({"commits": self.entries, "lock_sha256": "bad"}))
        self.refused(self.plan(), "lock_sha256")
        self.assertFalse(self.out.exists())

    def test_plan_model_version_and_environment_are_frozen(self):
        self.ok(self.plan(worker="codex:test-model"))
        plan = self.read("plan.json")
        self.assertEqual(plan["worker"], "codex:test-model")
        self.assertEqual(plan["programs"]["worker"]["version"], "stand-in-version")
        self.assertEqual(plan["environment"]["PATH"], self.env["YAK_PROBE_PATH"])
        self.assertEqual(plan["environment"]["YAK_JAIL_READ"], self.env["YAK_JAIL_READ"])
        (self.bin / "codex").write_text("#!/bin/sh\necho changed-version\n")
        self.refused(self.run_script("pass.sh", "screen", self.out), "codex")

    def test_retargeted_worker_symlink_is_rehashed(self):
        alternate = self.bin / "alternate"
        alternate.write_text("#!/bin/sh\necho another-program\n")
        alternate.chmod(0o755)
        original = self.bin / "original"
        (self.bin / "codex").rename(original)
        (self.bin / "codex").symlink_to(original)
        self.ok(self.plan(worker="codex:test-model"))
        (self.bin / "codex").unlink()
        (self.bin / "codex").symlink_to(alternate)
        self.refused(self.run_script("pass.sh", "screen", self.out), "codex")

    def test_new_worker_earlier_on_PATH_is_refused(self):
        first = self.tmp / "first"
        first.mkdir()
        self.env["YAK_PROBE_PATH"] = str(first) + os.pathsep + self.env["YAK_PROBE_PATH"]
        self.ok(self.plan(worker="codex:test-model"))
        replacement = first / "codex"
        replacement.write_text("#!/bin/sh\necho unexpected-worker\n")
        replacement.chmod(0o755)
        self.refused(self.run_script("pass.sh", "screen", self.out), "program lookup changed: worker")

    def test_planned_environment_does_not_inherit_new_optional_settings(self):
        environment = dict(self.env)
        environment.pop("SDKROOT", None)
        environment.pop("TMPDIR", None)
        self.ok(self.plan(env=environment))
        driver = module("pass_driver")
        with mock.patch.dict(os.environ, {"SDKROOT": "new-sdk", "TMPDIR": "new-tmp"}, clear=True):
            with driver.planned_environment(self.read("plan.json")):
                self.assertFalse("SDKROOT" in os.environ)
                self.assertFalse("TMPDIR" in os.environ)
            self.assertEqual(os.environ["SDKROOT"], "new-sdk")
            self.assertEqual(set(os.environ), {"SDKROOT", "TMPDIR"})

    def test_screen_stops_before_any_reference_on_STOP(self):
        self.ok(self.plan())
        (self.out / "STOP").touch()
        self.assertEqual(self.screen(), 1)
        self.assertEqual(self.read("screen.json")["results"], [])

    def test_history_requires_screen_and_list_requires_complete_history(self):
        self.ok(self.plan())
        self.refused(self.run_script("pass.sh", "history", self.out), "screen.json")
        self.refused(self.run_script("pass.sh", "list", self.out), "history.json")
        (self.out / "history.json").write_text(json.dumps({"status": "stopped", "turns": []}))
        self.refused(self.run_script("pass.sh", "list", self.out), "history did not complete")

    def test_screen_all_pass_and_is_immutable(self):
        self.ok(self.plan())
        self.assertEqual(self.screen(), 0)
        result = self.read("screen.json")
        self.assertEqual(result["v"], 1)
        self.assertEqual(len(result["results"]), 26)
        self.assertEqual(result["kept_history"], self.history_commits)
        self.assertEqual(result["excluded"], [])
        for c in self.three:
            self.assertEqual(sum(r["commit"] == c for r in result["results"]), 6)
        before = (self.out / "screen.json").read_bytes()
        self.refused(self.run_script("pass.sh", "screen", self.out), "new pass directory")
        self.assertEqual((self.out / "screen.json").read_bytes(), before)

    def test_screen_history_check_failure_keeps_other_items(self):
        self.ok(self.plan())
        self.assertEqual(self.screen(failures=self.history_commits[:1]), 0)
        result = self.read("screen.json")
        self.assertEqual(result["excluded"], [{"commit": self.history_commits[0], "reason": "reference check failed"}])
        self.assertEqual(result["kept_history"], self.history_commits[1:])

    def test_screen_history_below_four_stops(self):
        self.ok(self.plan())
        self.assertEqual(self.screen(failures=self.history_commits[:5]), 1)
        self.assertIn("fewer than four", self.read("screen.json")["reason"])
        self.refused(self.run_script("pass.sh", "history", self.out), "screen does not let")

    def test_screen_exactly_four_history_items_continue(self):
        self.ok(self.plan())
        self.assertEqual(self.screen(failures=self.history_commits[:4]), 0)
        self.assertEqual(self.read("screen.json")["kept_history"], self.history_commits[4:])

    def test_screen_any_of_six_three_failures_stops(self):
        self.configure(reference_modes={"three-%s-6" % self.three[1]: "failed"})
        self.ok(self.plan(history=self.history_commits[:4]))
        self.refused(self.run_script("pass.sh", "screen", self.out), "rehearsal is not run")
        result = self.read("screen.json")
        self.assertFalse(result["instrument_failure"])
        self.assertEqual(result["excluded"][0]["commit"], self.three[1])
        self.assertEqual(len(result["results"]), 22)

    def test_screen_instrument_failure_leaves_no_item_out(self):
        self.ok(self.plan())
        self.assertEqual(self.screen(failures=self.history_commits[:1], instrument=self.history_commits[1]), 1)
        result = self.read("screen.json")
        self.assertTrue(result["instrument_failure"])
        self.assertEqual(result["excluded"], [])
        self.assertEqual(result["kept_history"], [])
        self.refused(self.run_script("pass.sh", "screen", self.out), "new pass directory")

    def test_screen_every_unusable_reference_is_an_instrument_failure(self):
        self.ok(self.plan())
        original = self.out
        for n, outcome in enumerate(("hand-in failed", "another frozen hash", "recheck differs", "no usable observation")):
            self.out = self.tmp / ("instrument-%d" % n)
            self.out.mkdir()
            (self.out / "plan.json").write_bytes((original / "plan.json").read_bytes())
            self.assertEqual(self.screen(instrument=self.three[0], instrument_outcome=outcome), 1)
            result = self.read("screen.json")
            self.assertTrue(result["instrument_failure"])
            self.assertEqual(result["excluded"], [])
            self.assertEqual(len(result["results"]), 1)
            self.out = original
        driver = module("pass_driver")
        with mock.patch.dict(os.environ, self.env), mock.patch.object(driver.pilot, "reference",
                side_effect=OSError("reference instrument unavailable")):
            self.assertEqual(driver.screen(original), 1)
        self.assertTrue(self.read("screen.json")["instrument_failure"])
        self.assertEqual(self.read("screen.json")["excluded"], [])

    def test_screen_unverified_pass_is_an_instrument_failure(self):
        self.ok(self.plan())
        self.assertEqual(self.screen(verified=False), 1)
        self.assertTrue(self.read("screen.json")["instrument_failure"])

    def test_history_rejects_invalid_kept_history(self):
        self.ok(self.plan())
        self.assertEqual(self.screen(), 0)
        original = self.read("screen.json")
        for kept in (self.history_commits[:3], self.history_commits[::-1], self.history_commits + self.three[:1]):
            (self.out / "screen.json").write_text(json.dumps(dict(original, kept_history=kept)))
            self.refused(self.run_script("pass.sh", "history", self.out), "no usable kept history")
            self.assertFalse((self.out / "turns").exists())
        (self.out / "screen.json").write_text(json.dumps(dict(original, instrument_failure=True)))
        self.refused(self.run_script("pass.sh", "history", self.out), "screen does not let")

    def test_history_moves_discard_and_records_failed_clock(self):
        self.configure(failed_at=3, clock_exit=1)
        self.ok(self.plan())
        self.assertEqual(self.screen(failures=self.history_commits[:1]), 0)
        self.ok(self.run_script("pass.sh", "history", self.out))
        result = self.read("history.json")
        self.assertEqual(result["v"], 1)
        self.assertEqual(len(result["turns"]), 8)
        self.assertEqual(result["turns"][0]["commit"], self.history_commits[1])
        failed = next(t for t in result["turns"] if t["order"] == 3)
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["clock_exit"], 1)
        for row in result["turns"]:
            turns = json.loads((Path(row["directory"]) / "turns.json").read_text())
            manifest = json.loads((Path(row["directory"]) / "manifest.json").read_text())
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0]["offered"], {"arm": "nothing", "order": row["order"], "seed": 20261117})
            self.assertTrue(manifest["limits"]["own_prompts"])
            self.assertEqual(manifest["limits"]["in_force"], self.read("plan.json")["limits"]["in_force"])
            self.assertTrue(Path(row["directory"]).name.startswith("%03d-" % row["order"]))
        self.refused(self.run_script("pass.sh", "history", self.out), "new pass directory")

    def test_history_lost_turn_stops_and_preserves_work(self):
        self.configure(lost_at=3)
        self.ok(self.plan())
        self.assertEqual(self.screen(), 0)
        self.refused(self.run_script("pass.sh", "history", self.out), "no verdict")
        result = self.read("history.json")
        self.assertEqual(len(result["turns"]), 3)
        self.assertEqual(result["status"], "stopped")
        self.assertTrue((Path(result["turns"][0]["directory"]) / "turns.json").exists())
        self.assertEqual(len(list((self.out / "turns").iterdir())), 3)

    def test_history_STOP_between_turns(self):
        self.configure(stop_at=2)
        self.ok(self.plan())
        self.assertEqual(self.screen(), 0)
        self.refused(self.run_script("pass.sh", "history", self.out), "STOP before turn 3")
        self.assertEqual(len(self.read("history.json")["turns"]), 2)

    def test_history_rejects_wrong_metadata_and_manifest(self):
        self.ok(self.plan())
        self.assertEqual(self.screen(), 0)
        driver = module("pass_driver")
        # Exercise independent observations without running extra clocks: each
        # invocation uses a fresh output made from the same frozen plan/screen.
        for n, config, reason in [(1, {"offered": {"arm": "route"}}, "different arm"),
                                  (2, {"offered": {"order": 99}}, "different arm"),
                                  (3, {"offered": {"seed": 1}}, "different arm"),
                                  (4, {"manifest_yak_at": 1}, "another yak"),
                                  (5, {"clock_exit": 101}, "no usable observation"),
                                  (6, {"no_verdict": True}, "no verdict"),
                                  (7, {"mode": "malformed"}, "no verdict")]:
            self.configure(**config)
            original = self.out
            self.out = self.tmp / ("metadata-%d" % n)
            self.out.mkdir()
            for name in ("plan.json", "screen.json"):
                (self.out / name).write_bytes((original / name).read_bytes())
            self.refused(self.run_script("pass.sh", "history", self.out), reason)
            self.assertEqual(self.read("history.json")["status"], "stopped")
            self.out = original

    def test_list_uses_only_recorded_history_and_room_hash(self):
        self.ready_history(failed_at=3)
        # Stray reference, offered, and multiple-attempt rooms are beside the
        # discarded room; directory discovery must never admit any of them.
        for name in ("reference-room", "offered-room", "two-attempt-room"):
            room = self.out / name
            room.mkdir()
            turns = [{"attempt": "afedcba987654", "passed": True, "offered": {"arm": "route"}}]
            if name == "two-attempt-room":
                turns *= 2
            (room / "turns.json").write_text(json.dumps(turns))
        self.ok(self.run_script("pass.sh", "list", self.out))
        teach = self.read("teach-plan.json")
        ran = self.read("history.json")["turns"]
        self.assertEqual(teach, {"items": [{key: t[key] for key in ("room", "item", "attempt")} for t in ran[1:]]})
        result = self.read("list.json")
        self.assertEqual(result["v"], 1)
        self.assertEqual(result["teaching_count"], 7)
        self.assertEqual(len(result["not_teaching"]), 1)
        self.assertEqual(result["not_teaching"][0]["standing"], "failed")
        raw = (self.out / "history" / "history.json").read_bytes()
        self.assertEqual(result["list_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["history_file_sha256"], result["list_sha256"])
        self.assertEqual(result["teach_plan_sha256"], hashlib.sha256((self.out / "teach-plan.json").read_bytes()).hexdigest())
        self.assertEqual(self.read("room-plan.json"), {"items": [{key: t[key] for key in ("room", "item")} for t in ran[1:]]})
        self.assertEqual(result["room_plan"], {"path": str(self.out / "room-plan.json"),
            "sha256": hashlib.sha256((self.out / "room-plan.json").read_bytes()).hexdigest()})
        for row in result["walks"]:
            self.assertEqual(row["sha256"], hashlib.sha256(Path(row["file"]).read_bytes()).hexdigest())
        calls = [json.loads(x) for x in (self.bin / "calls.jsonl").read_text().splitlines()]
        self.assertTrue(any(x[:2] == ["history", "check"] for x in calls))
        made = next(x for x in calls if x[:2] == ["history", "make"])
        self.assertEqual(made[made.index("--measure") + 1], "share:1")
        self.assertEqual(len(result["walks"]), 8)
        self.refused(self.run_script("pass.sh", "list", self.out), "new pass directory")

    def test_list_rejects_hand_edited_teach_rooms(self):
        self.ready_history()
        for name, arm, count, reason in [("offered", "route", 1, "arm must be nothing"),
                                        ("two", "nothing", 2, "exactly one attempt")]:
            room = self.out / name
            room.mkdir()
            (room / "turns.json").write_text(json.dumps([{"attempt": "a0123456789ab", "offered": {"arm": arm}}] * count))
            (self.out / "teach-plan.json").write_text(json.dumps({"items": [{"room": str(room), "item": "i0123456789ab"}]}))
            self.refused(self.run_script("pass.sh", "list", self.out), reason)
            self.assertFalse((self.out / "history").exists())

    def test_list_checks_room_item_and_attempt_binding(self):
        self.ready_history()
        ran = self.read("history.json")["turns"][1:]
        teach = {"items": [{key: t[key] for key in ("room", "item", "attempt")} for t in ran]}
        (self.out / "teach-plan.json").write_text(json.dumps(teach))
        for items in ([], [{"id": "ifedcba987654"}], [{"id": teach["items"][0]["item"]}] * 2):
            self.configure(items=items)
            self.refused(self.run_script("pass.sh", "list", self.out), "exactly one item")
        self.configure()
        (self.out / "teach-plan.json").write_text(json.dumps(dict(teach, extra="unplanned")))
        self.refused(self.run_script("pass.sh", "list", self.out), "differs from the history turns")
        (self.out / "teach-plan.json").write_text(json.dumps(teach))
        (self.out / "room-plan.json").write_text(json.dumps({"items": []}))
        self.refused(self.run_script("pass.sh", "list", self.out), "room plan differs")
        (self.out / "room-plan.json").unlink()
        history = self.read("history.json")
        history["turns"][1]["attempt"] = "afedcba987654"
        (self.out / "history.json").write_text(json.dumps(history))
        self.refused(self.run_script("pass.sh", "list", self.out), "differs from the history turns")

    def test_list_stops_on_admission_failure(self):
        self.ready_history(check_refuses=True)
        self.refused(self.run_script("pass.sh", "list", self.out), "stand-in admission")
        self.assertEqual(self.read("list.json")["status"], "stopped")

    def test_list_refuses_disagreeing_printed_hashes(self):
        self.ready_history(check_hash="0" * 64)
        self.refused(self.run_script("pass.sh", "list", self.out), "disagree on the list hash")

    def test_list_refuses_agreeing_hashes_for_another_file(self):
        self.ready_history(printed_hash="0" * 64)
        self.refused(self.run_script("pass.sh", "list", self.out), "printed another list hash")

    def test_list_counts_room_standing_not_passes_or_entries(self):
        self.ready_history(unverified=[0, 1, 2, 3, 4])
        self.refused(self.run_script("pass.sh", "list", self.out), "fewer than four turns teach")
        result = self.read("list.json")
        self.assertEqual(result["teaching_count"], 3)
        self.assertEqual(len(result["not_teaching"]), 5)

    def test_list_exactly_four_teach(self):
        self.ready_history(unverified=[0, 1, 2, 3])
        self.ok(self.run_script("pass.sh", "list", self.out))
        self.assertEqual(self.read("list.json")["teaching_count"], 4)

    def test_list_whole_line_limit_includes_newline(self):
        self.ready_history(walk_line=1048577)
        self.refused(self.run_script("pass.sh", "list", self.out), "1048576 bytes including newline")
        self.assertEqual(self.read("list.json")["status"], "stopped")

    def test_list_whole_line_at_limit_passes(self):
        self.ready_history(walk_line=1048576)
        self.ok(self.run_script("pass.sh", "list", self.out))
        sizes = [Path(row["file"]).stat().st_size for row in self.read("list.json")["walks"]]
        self.assertEqual(max(sizes), 1048576)


class ArmOrder(unittest.TestCase):
    def test_another_seed_two_rounds(self):
        driver = module("pass_driver")
        # Independently worked hashes, ascending (first twelve hex digits):
        # seed 7, commits 1*40,2*40,3*40, respectively:
        # r1 35f3812b275b<7f771dbbfb7a<ad537235e0f7;
        #    195a4aa00adf<5148406dae43<be71685562a8;
        #    643c3f629442<6c66e33f2a0e<95286b002a4c.
        # r2 3b91c0b21e8b<73dd65eb3541<ced4687ad598;
        #    804f1c6fdcba<8da417c77952<c5645ca70d0e;
        #    27bcd31440ad<358c0038933e<aacc87cd3984.
        expected = [["route", "nothing", "shuffled"], ["route", "shuffled", "nothing"],
                    ["shuffled", "route", "nothing"], ["shuffled", "route", "nothing"],
                    ["shuffled", "route", "nothing"], ["shuffled", "nothing", "route"]]
        self.assertEqual([driver.arm_order(7, r, c * 40) for r in (1, 2) for c in "123"], expected)

    def test_equal_hashes_use_arm_name(self):
        driver = module("pass_driver")
        with mock.patch.object(driver.hashlib, "sha256") as hashed, mock.patch.object(
                driver, "ARMS", ("shuffled", "route", "nothing")):
            hashed.return_value.hexdigest.return_value = "0" * 64
            self.assertEqual(driver.arm_order(7, 1, "1" * 40), ["nothing", "route", "shuffled"])

    def test_live_seed(self):
        driver = module("pass_driver")
        commits = ["3d8775bc641ecd3fd2c92527348e5da8f6406d4a",
                   "01c46a2d5299304e0645cececebca34a7152f89e",
                   "a0c940438cfb80a87cca6d29423738ff4130ba72"]
        expected = [["shuffled", "nothing", "route"], ["route", "shuffled", "nothing"],
                    ["nothing", "route", "shuffled"]]
        self.assertEqual([driver.arm_order(20261117, 1, c) for c in commits], expected)


class UtilityContracts(unittest.TestCase):
    def test_jail_program_matches_room_detection(self):
        driver = module("pass_driver")
        # This is the other end of turn/src/jail.rs::Jail::detect's contract;
        # a PATH stand-in must not be hashed in place of the actual jail tool.
        for platform, choices in (("darwin", ["/usr/bin/sandbox-exec"]),
                                  ("linux", ["/usr/bin/bwrap", "/bin/bwrap", "/usr/local/bin/bwrap"])):
            for available in choices:
                with mock.patch.object(driver.sys, "platform", platform), mock.patch.object(
                        driver.Path, "is_file", lambda path: str(path) == available):
                    self.assertEqual(driver.jail_program(), available)
        with mock.patch.object(driver.Path, "is_file", return_value=False):
            self.assertIsNone(driver.jail_program())
        with mock.patch.object(driver.sys, "platform", "unsupported"), mock.patch.object(driver.Path, "is_file", return_value=True):
            self.assertIsNone(driver.jail_program())

    def test_clock_environment_matches_pilot_defaults_and_optionals(self):
        driver = module("pass_driver")
        with mock.patch.dict(os.environ, {"HOME": "test-home", "USER": "test", "LOGNAME": "test",
                "YAK_PROBE_PATH": "/bin", "YAK_JAIL_READ": "/tools"}, clear=True):
            expected = {"HOME": "test-home", "USER": "test", "LOGNAME": "test", "SHELL": "/bin/sh",
                "LANG": "en_US.UTF-8", "TERM": "dumb", "PATH": "/bin", "YAK_JAIL_READ": "/tools"}
            self.assertEqual(driver.clock_environment(), expected)
            os.environ.update(SDKROOT="test-sdk", TMPDIR="test-tmp")
            self.assertEqual(driver.clock_environment(), dict(expected, SDKROOT="test-sdk", TMPDIR="test-tmp"))


@unittest.skipUnless(os.environ.get("YAK_PASS_JAIL") == "1", "needs built YAK and the room's jail (YAK_PASS_JAIL=1)")
class JailPass(unittest.TestCase):
    """Real room/clock tests. The lead runs these on both supported jail hosts."""
    git = PassScripts.git
    write_list = PassScripts.write_list
    configure = PassScripts.configure
    run_script = PassScripts.run_script
    plan = PassScripts.plan
    read = PassScripts.read
    ok = PassScripts.ok
    refused = PassScripts.refused

    def setUp(self):
        real_yak = os.environ.get("YAK", "")
        PassScripts.setUp(self)
        self.assertTrue(Path(real_yak).is_file(), "YAK must point at the built room executable")
        self.env["YAK"] = str(Path(real_yak).resolve())
        # Four kept turns are enough to exercise the admission threshold, while
        # all three six-fold reference screens still run through the real jail.
        self.history_commits = self.history_commits[:4]
        for row in self.entries:
            row["check"]["command"] = 'test "$(cat source.txt)" = right'
        self.write_list()
        patch = self.bin / "reference.patch"
        patch.write_bytes(subprocess.check_output(["git", "-C", str(self.repo), "diff", "--binary", self.base, self.reference]))
        self.worker.write_text("#!/bin/sh\nset -eu\ngit apply --index --binary " + shlex.quote(str(patch)) + "\n"
            "git -c user.name=test -c user.email=test@yak.invalid -c commit.gpgsign=false commit -qm turn\n")
        self.worker.chmod(0o755)

    def screen_and_history(self):
        self.ok(self.plan())
        self.ok(self.run_script("pass.sh", "screen", self.out))
        self.ok(self.run_script("pass.sh", "history", self.out))

    def test_real_room_screen_history_list(self):
        self.screen_and_history()
        self.ok(self.run_script("pass.sh", "list", self.out))
        self.assertEqual(self.read("list.json")["teaching_count"], 4)
        self.assertEqual(len(self.read("teach-plan.json")["items"]), 4)

    def test_real_failed_verdict_despite_clock_failure(self):
        # Commit a change that leaves the source wrong. References use their own
        # stand-in and still pass; each history check fails, with clock exit 1.
        self.worker.write_text("#!/bin/sh\nset -eu\nprintf wrong > source.txt\ngit add source.txt\n"
            "git -c user.name=test -c user.email=test@yak.invalid -c commit.gpgsign=false commit -qm wrong\n")
        self.screen_and_history()
        turns = self.read("history.json")["turns"]
        self.assertEqual(len(turns), 5)
        self.assertTrue(all(t["passed"] is False and t["clock_exit"] == 1 for t in turns))
        self.refused(self.run_script("pass.sh", "list", self.out), "fewer than four turns teach")

    def test_real_history_screen_failure_moves_discard(self):
        bad = self.history_commits[0]
        self.history_commits = [e["commit"] for e in self.entries if e["part"] == "history"][:5]
        next(e for e in self.entries if e["commit"] == bad)["check"]["command"] = "false"
        self.write_list()
        self.screen_and_history()
        self.assertEqual(self.read("history.json")["turns"][0]["commit"], self.history_commits[1])

    def test_real_turn_rooms_hold_one_attempt_and_metadata(self):
        self.screen_and_history()
        for row in self.read("history.json")["turns"]:
            done = subprocess.run([self.env["YAK"], "--room", row["room"], "item", "turns", row["item"], "--json"],
                capture_output=True, text=True)
            self.ok(done)
            attempts = json.loads(done.stdout)
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["offered"]["arm"], "nothing")
            self.assertEqual(attempts[0]["offered"]["seed"], 20261117)
            self.assertEqual(attempts[0]["offered"]["order"], row["order"])


if __name__ == "__main__":
    unittest.main()
