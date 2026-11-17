#!/usr/bin/env python3
"""Toy repositories and a script standing in for yak: no model, clock, or room.

Run with python3 -I test_pilot.py. All paths and machine identities are made at runtime.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORKER = "script:unused"

FAKE = r'''
import json, os, pathlib, sqlite3, subprocess, sys
here = pathlib.Path(__file__).resolve().parent
config = json.loads((here / "config.json").read_text())
args = sys.argv[1:]
with (here / "calls.jsonl").open("a") as out:
    out.write(json.dumps(args) + "\n")
if args == ["clock", "run", "--help"]:
    for name, value in [("lease-secs", 1800), ("turn-secs", 1200), ("daily-turns", 40), ("concurrent", 1)]:
        print("--%s <%s> [default: %s]" % (name, name.upper().replace("-", "_"), value))
    sys.exit(0)
room = pathlib.Path(args[1]); words = args[2:]
if words == ["init"]:
    room.mkdir()
elif words[:2] == ["item", "add"]:
    (room / "add.json").write_text(json.dumps(words))
    print("i0123456789ab")
elif words[:2] == ["clock", "run"]:
    root = room.parent
    assert (root / "manifest.json").is_file()
    (root / "clock-env.json").write_text(json.dumps(dict(os.environ)))
    add = json.loads((room / "add.json").read_text())
    repo = pathlib.Path(add[add.index("--repo") + 1])
    worker = words[words.index("--worker") + 1]
    commit = None
    mode = config.get("mode", "passed")
    slot = str(json.loads((root / "manifest.json").read_text()).get("slot"))
    if slot == str(config.get("lost_at", "")):
        mode = "lost"
    if worker.startswith("script:") and worker != "script:unused" and mode not in ("lost", "nohandin"):
        scratch = root / "scratch"
        def git(*a, cwd=scratch):
            return subprocess.check_output(["git", "-c", "user.name=test", "-c", "user.email=test@yak.invalid",
                "-c", "commit.gpgsign=false", "-C", str(cwd), *a], stderr=subprocess.STDOUT).decode().strip()
        git("clone", "-q", "--no-local", str(repo), str(scratch), cwd=root)
        if mode == "note":
            (scratch / "source.txt").write_text("conflict\n")
            git("add", "."); git("commit", "-qm", "conflict")
        subprocess.check_call([worker.split(":", 1)[1]], cwd=scratch)
        if mode in ("tree_diff", "tree_diff_failed"):
            git("rm", "table.gen"); git("commit", "-qm", "different tree")
        commit = git("rev-parse", "HEAD")
        git("fetch", "-q", str(scratch), "HEAD", cwd=repo)
    measured = {"ended": "exited", "sandbox_ms": 1, "worker_ms": 2, "seal_ms": 1,
        "bring_ms": 1, "check_ms": 1, "active_ms": 6, "unknown_steps": 0,
        "tokens": {"fresh_in": None, "cache_write": None, "cache_read": None, "output": None, "complete": False}}
    turn = {"worker": worker, "commit": commit, "passed": mode not in ("failed", "note", "tree_diff_failed"),
        "measured": measured, "changes": [], "steps": 0}
    (room / "turns.json").write_text(json.dumps([] if mode == "lost" else [None] if mode == "malformed" else [turn]))
    if slot == str(config.get("stop_at", "")):
        (root.parent / "STOP").touch()
    if slot == str(config.get("change_at", "")):
        (here / "codex").write_text("#!/bin/sh\necho changed-version\n")
    if config.get("mutate_list") and slot == str(config.get("mutate_at", 1)):
        pathlib.Path(config["mutate_list"]).write_text("{}")
    if config.get("retarget") and slot == str(config.get("retarget_at", 2)):
        link = pathlib.Path(config["retarget"])
        link.unlink(); link.symlink_to(config["target"])
    if slot == str(config.get("manifest_yak_at", "")):
        path = root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["yak"]["sha256"] = "0" * 64
        path.write_text(json.dumps(manifest))
    state = "passed_unverified" if mode == "unverified" else ("failed" if mode in ("failed", "note", "tree_diff_failed") else "passed_verified")
    (room / "view.json").write_text(json.dumps({"state": state}))
    with sqlite3.connect(str(room / "room.sqlite3")) as db:
        db.execute("CREATE TABLE checks (item TEXT, frozen TEXT)")
        manifest = json.loads((root / "manifest.json").read_text())
        frozen = {"check_hash": config.get("hash", manifest["check_blob"])}
        db.execute("INSERT INTO checks VALUES (?, ?)", ("i0123456789ab", json.dumps(frozen)))
    sys.exit(config.get("clock_exit", 1 if mode in ("lost", "failed", "note", "tree_diff_failed") else 0))
elif words[:2] == ["item", "turns"]:
    print((room / "turns.json").read_text())
elif words[:2] == ["item", "show"]:
    print((room / "view.json").read_text())
else:
    sys.exit(9)
'''


class PilotScripts(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name).resolve()
        self.items = self.tmp / "items"
        self.repo = self.items / "repo"
        self.repo.mkdir(parents=True)
        self.git("init", "-q")
        (self.repo / "source.txt").write_text("wrong\n")
        (self.repo / "binary.bin").write_bytes(b"\0wrong\0")
        (self.repo / "check file.txt").write_text("frozen\n")
        (self.repo / "second.txt").write_text("also frozen\n")
        (self.repo / "second.txt").chmod(0o755)
        (self.repo / ".gitignore").write_text("*.gen\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / "unrelated.txt").write_text("unrelated\n")
        self.git("add", ".")
        self.git("commit", "-qm", "wrong")
        self.wrong = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", self.base)
        (self.repo / "source.txt").write_text("right\n")
        (self.repo / "binary.bin").write_bytes(b"\0right\0")
        (self.repo / "table.gen").write_text("reference addition\n")
        self.git("add", "-f", "table.gen")
        self.git("add", ".")
        self.git("commit", "-qm", "reference")
        self.reference = self.git("rev-parse", "HEAD")
        entries = []
        for n in range(3):
            self.git("commit", "-q", "--allow-empty", "-m", "merged %d" % n)
            commit = self.git("rev-parse", "HEAD")
            for kind, value in [("base", self.base), ("wrong", self.wrong), ("reference", self.reference)]:
                self.git("update-ref", "refs/yak-items/%s/%s" % (commit, kind), value)
            entries.append({"commit": commit, "part": "pilot", "base": self.base, "wrong": self.wrong,
                "reference": self.reference, "title": "Make the list's tests pass %d" % n,
                "check": {"command": "printf '%s' 'list command'", "files": ["second.txt", "check file.txt"]}})
        self.entries = entries
        self.commit = entries[0]["commit"]
        self.list = self.items / "list" / "items.json"
        self.list.parent.mkdir()
        self.write_list()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.yak = self.bin / "yak"
        self.yak.write_text("#!" + sys.executable + "\n" + FAKE)
        self.yak.chmod(0o755)
        (self.bin / "python3").symlink_to(sys.executable)
        for name in ("claude", "codex"):
            path = self.bin / name
            path.write_text("#!/bin/sh\necho stand-in-version\n")
            path.chmod(0o755)
        self.configure()
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            HOME=str(self.tmp), USER="test", LOGNAME="test", YAK=str(self.yak),
            YAK_PROBE_PATH=str(self.bin) + os.pathsep + os.environ["PATH"], YAK_JAIL_READ=str(self.bin),
            YAK_PILOT_SLOT="2", YAK_PILOT_KIND="round-1", UNNAMED_VARIABLE="must not reach clock")

    def git(self, *words, repo=None, check=True):
        done = subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@yak.invalid",
            "-c", "commit.gpgsign=false", "-C", str(repo or self.repo), *words], capture_output=True, text=True)
        if check:
            self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip() if check else done.returncode

    def write_list(self):
        self.list.write_text(json.dumps({"commits": self.entries, "lock_sha256": "f" * 64}))

    def driver(self):
        spec = importlib.util.spec_from_file_location("pilot_driver", HERE / "pilot_driver.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def configure(self, **config):
        (self.bin / "config.json").write_text(json.dumps(config))

    def run_script(self, name, *args, env=None):
        return subprocess.run(["sh", str(HERE / name), *map(str, args)], env=env or self.env,
            capture_output=True, text=True)

    def turn(self, commit=None, name="turn"):
        out = self.tmp / name
        done = self.run_script("turn.sh", out, self.items, commit or self.commit, WORKER, "--own-prompts")
        return done, out

    def test_list_words_copy_and_manifest(self):
        done, out = self.turn()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = [json.loads(line) for line in (self.bin / "calls.jsonl").read_text().splitlines()]
        add = next(words for words in calls if words[2:4] == ["item", "add"])
        for flag, value in [("--title", self.entries[0]["title"]), ("--base", self.base), ("--wrong", self.wrong),
                            ("--check", self.entries[0]["check"]["command"]), ("--by", "claude:merged"), ("--origin", "observed")]:
            self.assertEqual(add[add.index(flag) + 1], value)
        self.assertEqual([add[n + 1] for n, word in enumerate(add) if word == "--file"], self.entries[0]["check"]["files"])
        for name in (self.base, self.wrong):
            self.assertEqual(self.git("cat-file", "-e", name, repo=out / "repo", check=False), 0)
        for name in (self.reference, self.commit):
            self.assertNotEqual(self.git("cat-file", "-e", name, repo=out / "repo", check=False), 0)
        self.assertEqual(self.git("rev-parse", "HEAD", repo=out / "repo"), self.base)
        self.assertTrue(self.git("symbolic-ref", "HEAD", repo=out / "repo").startswith("refs/heads/"))
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual((manifest["slug"], manifest["base"], manifest["wrong"], manifest["check"]),
            (self.commit, self.base, self.wrong, self.entries[0]["check"]["command"]))
        self.assertEqual(json.loads(manifest["check_file"]), self.entries[0]["check"]["files"])
        self.assertNotIn("UNNAMED_VARIABLE", json.loads((out / "clock-env.json").read_text()))
        self.assertEqual(manifest["limits"]["in_force"]["daily-turns"], 1)
        # An independently framed expected hash: neither the fake yak nor this
        # assertion asks production code to compute its own expected answer.
        expected = hashlib.sha256(b"v2\n" + self.entries[0]["check"]["command"].encode() + b"\n" +
            b"check file.txt\x00100644\x00" + hashlib.sha256(b"frozen\n").hexdigest().encode() + b"\n" +
            b"second.txt\x00100755\x00" + hashlib.sha256(b"also frozen\n").hexdigest().encode() + b"\n").hexdigest()
        self.assertEqual(manifest["check_blob"], expected)
        for name in ("item.txt", "started.txt", "clock.log", "clock.exit", "ended.txt", "turns.json", "load-before.txt", "load-after.txt"):
            self.assertTrue((out / name).exists(), name)

    def test_absent_ineligible_and_missing_words_are_refused_before_output(self):
        done, out = self.turn("e" * 40)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("not in the list", done.stdout + done.stderr)
        self.assertIn("e" * 40, done.stdout + done.stderr)
        self.assertFalse(out.exists())
        self.git("update-ref", "-d", "refs/yak-items/%s/base" % self.commit)
        done, out = self.turn()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("failed", done.stdout + done.stderr)
        self.assertFalse(out.exists())
        original = json.loads(json.dumps(self.entries[0]))
        for field in ("reason", "title", "base", "wrong", "reference", "command", "files"):
            self.entries[0] = json.loads(json.dumps(original))
            if field == "reason":
                self.entries[0][field] = "rule 4: failed"
            else:
                del (self.entries[0]["check"] if field in ("command", "files") else self.entries[0])[field]
            self.write_list()
            done, out = self.turn()
            self.assertNotEqual(done.returncode, 0, field)
            self.assertIn(self.commit, done.stdout + done.stderr)
            self.assertIn("eligible" if field == "reason" else field, done.stdout + done.stderr)
            self.assertFalse(out.exists())

    def test_copy_that_holds_an_answer_is_refused(self):
        for kind, answer in [("reference", self.reference), ("original", self.commit)]:
            self.entries[0]["wrong"] = answer
            self.git("update-ref", "refs/yak-items/%s/wrong" % self.commit, answer)
            self.write_list()
            done, out = self.turn(name="holds-" + kind)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("holds", done.stdout + done.stderr)
            self.assertFalse((out / "room").exists())

    def test_prepared_git_files_do_not_name_answers_or_items_directory(self):
        done, out = self.turn()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        git_dir = out / "repo" / ".git"
        contents = [path.relative_to(git_dir).as_posix().encode() + b"\0" + path.read_bytes()
            for path in git_dir.rglob("*") if path.is_file()]
        self.assertTrue(any(self.base.encode() in data for data in contents))
        for forbidden in (self.commit, self.reference, str(self.items)):
            self.assertFalse(any(forbidden.encode() in data for data in contents), forbidden)

    def test_invalid_list_fields_refs_and_runtime_settings_are_refused(self):
        original = json.loads(json.dumps(self.entries[0]))
        cases = [("part", "unknown", "not eligible"), ("base", "short", "full base"), ("title", "  ", "title"),
                 ("check", {"command": "", "files": ["second.txt"]}, "command"),
                 ("check", {"command": "true", "files": []}, "files"),
                 ("check", {"command": "true", "files": ["second.txt", "second.txt"]}, "repeats"),
                 ("check", {"command": "true", "files": ["../second.txt"]}, "not plain"),
                 ("check", {"command": "true", "files": ["missing.txt"]}, "lacks the check file")]
        for field, value, diagnostic in cases:
            self.entries[0] = dict(original, **{field: value})
            self.write_list()
            done, out = self.turn()
            self.assertNotEqual(done.returncode, 0)
            self.assertIn(self.commit, done.stdout + done.stderr)
            self.assertIn(diagnostic, done.stdout + done.stderr)
            self.assertFalse(out.exists())
        self.entries[0] = original
        self.entries.append(original)
        self.write_list()
        done, out = self.turn()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("more than once", done.stdout + done.stderr)
        self.assertFalse(out.exists())
        self.entries.pop()
        self.write_list()
        for key in ("YAK", "YAK_PROBE_PATH", "YAK_JAIL_READ"):
            done = self.run_script("turn.sh", self.tmp / "turn", self.items, self.commit, WORKER,
                env=dict(self.env, **{key: ""}))
            self.assertNotEqual(done.returncode, 0)
            self.assertIn(key, done.stdout + done.stderr)
            self.assertFalse(out.exists())
        self.git("update-ref", "refs/yak-items/%s/base" % self.commit, self.wrong)
        done, out = self.turn()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ref differs", done.stdout + done.stderr)
        self.assertFalse(out.exists())

    def test_existing_output_is_not_reused(self):
        out = self.tmp / "turn"
        out.mkdir()
        (out / "kept").write_text("keep")
        done, _ = self.turn()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("REFUSED: %s exists" % out, done.stdout + done.stderr)
        self.assertEqual((out / "kept").read_text(), "keep")

    def test_jail_reads_cannot_overlap_answers_by_real_path(self):
        refs = self.tmp / "references"
        for script in ("turn.sh", "reference.sh", "pilot.sh"):
            for protected in ("items", "out", "references") if script == "pilot.sh" else ("items", "out"):
                for relation in ("same", "parent", "child", "link"):
                    with self.subTest(script=script, protected=protected, relation=relation):
                        out = self.tmp / (script + "-" + protected + "-" + relation)
                        target = {"items": self.items, "out": out, "references": refs}[protected]
                        read = target if relation == "same" else target.parent if relation == "parent" else target / "inside"
                        if relation == "link":
                            read = self.tmp / "jail-link"
                            if read.is_symlink():
                                read.unlink()
                            read.symlink_to(target / "inside")
                        args = [out, self.items, WORKER, "--references", refs] if script == "pilot.sh" else [out, self.items, self.commit]
                        if script == "turn.sh":
                            args.append(WORKER)
                        done = self.run_script(script, *args, env=dict(self.env, YAK_JAIL_READ=str(read)))
                        self.assertNotEqual(done.returncode, 0)
                        self.assertIn("YAK_JAIL_READ overlaps", done.stdout + done.stderr)
                        self.assertFalse(out.exists())
        allowed = self.tmp / "items-sibling"
        allowed.mkdir()
        done = self.run_script("turn.sh", self.tmp / "allowed-turn", self.items, self.commit, WORKER,
            env=dict(self.env, YAK_JAIL_READ=str(allowed)))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_bad_list_and_usage_leave_nothing(self):
        self.list.write_text("{}")
        done, out = self.turn()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("commits list", done.stdout + done.stderr)
        self.assertFalse(out.exists())
        for name in ("turn.sh", "reference.sh", "pilot.sh"):
            done = self.run_script(name)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("REFUSED", done.stdout + done.stderr)

    def test_identity_environment_is_required_before_output(self):
        for key in ("HOME", "USER", "LOGNAME"):
            for missing in (False, True):
                with self.subTest(key=key, missing=missing):
                    environment = dict(self.env, **{key: ""})
                    if missing:
                        del environment[key]
                    out = self.tmp / (key + str(missing))
                    done = self.run_script("turn.sh", out, self.items, self.commit, WORKER, env=environment)
                    self.assertNotEqual(done.returncode, 0)
                    self.assertIn(key, done.stdout + done.stderr)
                    self.assertFalse(out.exists())

    def test_nested_list_is_refused_without_traceback(self):
        self.list.write_text("[" * 12000 + "0" + "]" * 12000)
        done, out = self.turn()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("REFUSED", done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertFalse(out.exists())
        # JSON decoders differ in their depth limit; exercise RecursionError too.
        driver = self.driver()
        with mock.patch.object(driver.json, "loads", side_effect=RecursionError):
            with self.assertRaises(driver.Refused):
                driver.listed(self.items)

    def test_turn_worker_must_be_one_word_before_output(self):
        for n, worker in enumerate(("", "two words", "claude:opus\n2 x")):
            out = self.tmp / ("worker-%d" % n)
            done = self.run_script("turn.sh", out, self.items, self.commit, worker)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("worker must be one word", done.stdout + done.stderr)
            self.assertFalse(out.exists())

    def test_turn_failed_check_is_usable_but_lost_or_crashed_clock_is_not(self):
        for config, usable in [({"mode": "failed"}, True), ({"mode": "lost"}, False), ({"clock_exit": 101}, False)]:
            self.configure(**config)
            done, out = self.turn(name="turn-" + str(len(list(self.tmp.glob("turn-*")))))
            self.assertEqual(done.returncode == 0, usable, done.stdout + done.stderr)
            self.assertTrue((out / "turns.json").exists())
            self.assertIn("one usable observation" if usable else "REFUSED", done.stdout + done.stderr)

    def test_clock_optional_environment_and_extra_words_are_written_exactly(self):
        out = self.tmp / "turn"
        done = self.run_script("turn.sh", out, self.items, self.commit, WORKER, "--own-prompts", "--turn-secs", "61",
            env=dict(self.env, SDKROOT=str(self.tmp / "sdk"), TMPDIR=str(self.tmp)))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["argv"][-3:], ["--own-prompts", "--turn-secs", "61"])
        self.assertEqual(manifest["limits"]["in_force"]["turn-secs"], 61)
        expected = {"HOME": str(self.tmp), "USER": "test", "LOGNAME": "test", "SHELL": self.env.get("SHELL", "/bin/sh"),
            "LANG": "en_US.UTF-8", "TERM": "dumb", "PATH": self.env["YAK_PROBE_PATH"], "YAK_JAIL_READ": str(self.bin),
            "SDKROOT": str(self.tmp / "sdk"), "TMPDIR": str(self.tmp)}
        self.assertEqual(manifest["environment"], expected)

    def test_plan_order_and_rehearsal(self):
        for rounds in (5, 1):
            done = self.run_script("pilot.sh", "--plan", self.items, WORKER,
                env=dict(self.env, YAK_PILOT_ROUNDS=str(rounds)))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            rows = [line.split() for line in done.stdout.splitlines()]
            expected = [["1", "thrown-away", self.commit, WORKER, "--own-prompts"]]
            for n in range(1, rounds + 1):
                for entry in self.entries:
                    expected.append([str(len(expected) + 1), "round-%d" % n, entry["commit"], WORKER, "--own-prompts"])
            self.assertEqual(rows, expected)

    def test_plan_refuses_wrong_item_count_rounds_and_worker(self):
        for env, worker, diagnostic in [(dict(self.env, YAK_PILOT_ROUNDS="bad"), WORKER, "is not a number"),
                                        (self.env, "two words", "worker must be one word")]:
            done = self.run_script("pilot.sh", "--plan", self.items, worker, env=env)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn(diagnostic, done.stdout + done.stderr)
        self.entries.pop()
        self.write_list()
        done = self.run_script("pilot.sh", "--plan", self.items, WORKER)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("three", done.stdout + done.stderr)

    def reference_run(self, mode="passed", name="reference"):
        self.configure(mode=mode)
        out = self.tmp / name
        done = self.run_script("reference.sh", out, self.items, self.commit)
        return done, out

    def test_reference_pass_and_three_failures(self):
        for mode, outcome in [("passed", "passed"), ("note", "hand-in failed"),
                              ("failed", "check failed"), ("lost", "no usable observation"),
                              ("unverified", "recheck differs"), ("nohandin", "hand-in failed"),
                              ("malformed", "no usable observation")]:
            with self.subTest(mode=mode):
                done, out = self.reference_run(mode, "reference-" + mode)
                self.assertEqual(done.returncode == 0, mode == "passed", done.stdout + done.stderr)
                kept = json.loads((out / "reference.json").read_text())
                self.assertEqual(kept["outcome"], outcome)
                self.assertIn(outcome, done.stdout + done.stderr)
                self.assertEqual(kept["machine"], {"name": platform.node(), "kind": platform.system(), "architecture": platform.machine()})
                self.assertEqual(kept["yak_sha256"], hashlib.sha256(self.yak.read_bytes()).hexdigest())
                self.assertEqual((kept["commit"], kept["reference"]), (self.commit, self.reference))
                if mode == "passed":
                    self.assertTrue(kept["verified"])
                    self.assertEqual(len(kept["check_hash"]), 64)
                    self.assertTrue(kept["handed_in"])
                elif mode == "note":
                    self.assertIn("apply:", kept["note"])
                    self.assertIn("patch", kept["note"])
                elif mode == "unverified":
                    self.assertEqual(kept["state"], "passed_unverified")

    def test_reference_does_not_pass_with_another_frozen_hash(self):
        self.configure(hash="0" * 64)
        out = self.tmp / "bad-hash"
        done = self.run_script("reference.sh", out, self.items, self.commit)
        self.assertNotEqual(done.returncode, 0)
        receipt = json.loads((out / "reference.json").read_text())
        self.assertEqual(receipt["outcome"], "another frozen hash")
        self.assertEqual(receipt["state"], "passed_verified")
        self.assertFalse(receipt["verified"])

    def test_reference_ignored_addition_matches_tree(self):
        done, out = self.reference_run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        receipt = json.loads((out / "reference.json").read_text())
        expected = self.git("rev-parse", self.reference + "^{tree}")
        self.assertEqual(receipt["reference_tree"], expected)
        self.assertEqual(receipt["handed_in_tree"], expected)
        self.assertEqual(self.git("show", receipt["handed_in"] + ":table.gen", repo=out / "turn" / "repo"),
            "reference addition")

    def test_reference_patch_ignores_diff_color_and_prefix_settings(self):
        self.git("config", "diff.noprefix", "true")
        self.git("config", "diff.mnemonicPrefix", "true")
        self.git("config", "color.diff", "always")
        done, out = self.reference_run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        receipt = json.loads((out / "reference.json").read_text())
        self.assertEqual(receipt["handed_in_tree"], self.git("rev-parse", self.reference + "^{tree}"))

    def test_reference_clock_sees_only_its_stand_in_beside_normal_jail_reads(self):
        done, out = self.reference_run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        environment = json.loads((out / "turn" / "clock-env.json").read_text())
        self.assertEqual(environment["YAK_JAIL_READ"].split(os.pathsep), [str(self.bin), str(out / "stand-in")])
        self.assertEqual({path.name for path in (out / "stand-in").iterdir()}, {"worker.sh", "reference.patch"})

    def test_reference_closes_store_even_if_query_fails(self):
        driver = self.driver()
        real_connect = driver.sqlite3.connect
        for broken in (False, True):
            connections = []

            class Connection(driver.sqlite3.Connection):
                closed = False

                def close(self):
                    self.closed = True
                    super().close()

                def execute(self, *args, **kwargs):
                    if broken:
                        raise driver.sqlite3.OperationalError("unavailable check")
                    return super().execute(*args, **kwargs)

            def connect(*args, **kwargs):
                db = real_connect(*args, factory=Connection, **kwargs)
                connections.append(db)
                return db

            with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(driver.sqlite3, "connect", connect):
                result = driver.reference(self.tmp / ("connection-%s" % broken), self.items, self.commit)
            self.assertEqual(result, 1 if broken else 0)
            self.assertEqual(len(connections), 1)
            self.assertTrue(connections[0].closed)

    def test_reference_refuses_another_tree_despite_verified_check(self):
        for mode in ("tree_diff", "tree_diff_failed"):
            with self.subTest(mode=mode):
                done, out = self.reference_run(mode, mode)
                self.assertNotEqual(done.returncode, 0)
                receipt = json.loads((out / "reference.json").read_text())
                self.assertEqual(receipt["outcome"], "another tree")
                self.assertNotEqual(receipt["handed_in_tree"], receipt["reference_tree"])
                self.assertFalse(receipt["verified"])

    def test_reference_crashed_clock_has_no_usable_observation(self):
        for n, config in enumerate(({"mode": "failed"}, {"mode": "unverified"},
                                    {"mode": "tree_diff"}, {"hash": "0" * 64})):
            with self.subTest(config=config):
                self.configure(clock_exit=101, **config)
                out = self.tmp / ("reference-crashed-%d" % n)
                done = self.run_script("reference.sh", out, self.items, self.commit)
                self.assertNotEqual(done.returncode, 0)
                receipt = json.loads((out / "reference.json").read_text())
                self.assertEqual(receipt["outcome"], "no usable observation")
                self.assertFalse(receipt["verified"])

    def receipts(self):
        refs = self.tmp / "references"
        refs.mkdir()
        for entry in self.entries:
            out = refs / entry["commit"]
            done = self.run_script("reference.sh", out, self.items, entry["commit"])
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return refs

    def test_pilot_reference_preflight_and_success(self):
        out = self.tmp / "pilot"
        done = self.run_script("pilot.sh", out, self.items, WORKER)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("references", done.stdout + done.stderr)
        self.assertFalse(out.exists())
        refs = self.receipts()
        receipt = refs / self.commit / "reference.json"
        original = json.loads(receipt.read_text())
        receipt.write_text("[]")
        done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("REFUSED", done.stdout + done.stderr)
        self.assertFalse(out.exists())
        receipt.write_text(json.dumps(original))
        for field, value in [("yak_sha256", "0" * 64), ("outcome", "check failed"),
                             ("verified", False), ("machine", {"name": "elsewhere"}), ("check_hash", "0" * 64),
                             ("reference", "0" * 40), ("commit", "0" * 40), ("base", "0" * 40), ("handed_in", None)]:
            receipt.write_text(json.dumps(dict(original, **{field: value})))
            done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs)
            self.assertNotEqual(done.returncode, 0, field)
            self.assertFalse(out.exists(), field)
        receipt.write_text(json.dumps(original))
        receipt.unlink()
        done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(out.exists())
        receipt.write_text(json.dumps(original))
        done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs,
            env=dict(self.env, YAK_PILOT_ROUNDS="1"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr + ((out / "pilot.log").read_text() if out.exists() else ""))
        self.assertTrue((out / "tables.md").exists())
        self.assertEqual(len((out / "plan.txt").read_text().splitlines()), 4)

    def test_pilot_refuses_receipts_without_their_matching_run(self):
        refs = self.receipts()
        turn = refs / self.commit / "turn"
        kept = self.tmp / "kept-turn"
        turn.rename(kept)
        for case in ("missing", "another item", "yak", "slug", "handed in", "unusable"):
            with self.subTest(case=case):
                out = self.tmp / ("pilot-" + case.replace(" ", "-"))
                if turn.exists():
                    shutil.rmtree(turn)
                if case != "missing":
                    source = refs / self.entries[1]["commit"] / "turn" if case == "another item" else kept
                    shutil.copytree(source, turn)
                if case in ("yak", "slug"):
                    path = turn / "manifest.json"
                    value = json.loads(path.read_text())
                    if case == "yak":
                        value["yak"]["sha256"] = "0" * 64
                    else:
                        value["slug"] = "0" * 40
                    path.write_text(json.dumps(value))
                elif case == "handed in":
                    path = turn / "turns.json"
                    value = json.loads(path.read_text())
                    value[0]["commit"] = "0" * 40
                    path.write_text(json.dumps(value))
                elif case == "unusable":
                    (turn / "clock.exit").write_text("101\n")
                done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs,
                    env=dict(self.env, YAK_PILOT_ROUNDS="0"))
                self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertFalse(out.exists())
                if turn.exists():
                    shutil.rmtree(turn)

    def test_pilot_refuses_handwritten_receipts_with_no_turns(self):
        refs = self.tmp / "handwritten-references"
        driver = self.driver()
        for entry in self.entries:
            directory = refs / entry["commit"]
            directory.mkdir(parents=True)
            receipt = {"commit": entry["commit"], "base": entry["base"], "reference": entry["reference"],
                "check_hash": driver.check_hash(self.repo, entry),
                "machine": {"name": platform.node(), "kind": platform.system(), "architecture": platform.machine()},
                "yak_sha256": hashlib.sha256(self.yak.read_bytes()).hexdigest(),
                "outcome": "passed", "verified": True, "handed_in": "written by hand"}
            (directory / "reference.json").write_text(json.dumps(receipt))
        out = self.tmp / "pilot"
        done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs,
            env=dict(self.env, YAK_PILOT_ROUNDS="0"))
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(out.exists())

    def test_pilot_stops_on_lost_turn_stop_file_or_changed_block(self):
        refs = self.receipts()
        for config, count in [({"lost_at": 2}, 2), ({"stop_at": 1}, 1), ({"change_at": 4}, 4)]:
            self.configure(**config)
            out = self.tmp / ("pilot-" + next(iter(config)))
            done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs,
                env=dict(self.env, YAK_PILOT_ROUNDS="1"))
            self.assertNotEqual(done.returncode, 0)
            self.assertEqual(len([name for name in out.iterdir() if name.name[0].isdigit()]), count)
            self.assertFalse((out / "tables.md").exists())
        self.configure()
        (self.bin / "codex").write_text("#!/bin/sh\necho stand-in-version\n")
        instructions = self.tmp / ".claude" / "CLAUDE.md"
        instructions.parent.mkdir()
        instructions.write_text("instructions")
        out = self.tmp / "pilot-blocked"
        done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(any(name.name[0].isdigit() for name in out.iterdir()))

    def test_pilot_pins_yak_when_link_retargets_between_turns(self):
        refs = self.receipts()
        link = self.bin / "yak-link"
        link.symlink_to(self.yak)
        other = self.bin / "other-yak"
        other.write_bytes(self.yak.read_bytes() + b"\n# another build\n")
        other.chmod(0o755)
        self.configure(retarget=str(link), target=str(other))
        out = self.tmp / "pilot"
        done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs,
            env=dict(self.env, YAK=str(link), YAK_PILOT_ROUNDS="1"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(link.resolve(), other)
        manifests = list(out.glob("[0-9]*/manifest.json"))
        self.assertEqual(len(manifests), 4)
        for path in manifests:
            yak = json.loads(path.read_text())["yak"]
            self.assertEqual(yak["path"], str(self.yak))
            self.assertEqual(yak["sha256"], hashlib.sha256(self.yak.read_bytes()).hexdigest())

    def test_pilot_stops_on_another_yak_in_turn_manifest(self):
        refs = self.receipts()
        self.configure(manifest_yak_at=2)
        out = self.tmp / "pilot"
        done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs,
            env=dict(self.env, YAK_PILOT_ROUNDS="1"))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("another yak", (out / "pilot.log").read_text())
        self.assertEqual(len(list(out.glob("[0-9]*/manifest.json"))), 2)
        self.assertFalse((out / "tables.md").exists())

    def test_pilot_refuses_a_changed_list_after_a_turn(self):
        refs = self.receipts()
        for slot in (1, 4):
            self.write_list()
            self.configure(mutate_list=str(self.list), mutate_at=slot)
            out = self.tmp / ("pilot-changed-list-%d" % slot)
            done = self.run_script("pilot.sh", out, self.items, WORKER, "--references", refs,
                env=dict(self.env, YAK_PILOT_ROUNDS="1"))
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("list changed", (out / "pilot.log").read_text())
            self.assertEqual(len([name for name in out.iterdir() if name.name[0].isdigit()]), slot)

    def test_stand_in_alone_applies_and_commits_or_commits_note(self):
        done, out = self.reference_run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        worker = out / "stand-in" / "worker.sh"
        for bad in (False, True):
            scratch = self.tmp / ("scratch-bad" if bad else "scratch-good")
            self.git("clone", "-q", str(self.repo), str(scratch))
            self.git("checkout", "-q", "--detach", self.base, repo=scratch)
            if bad:
                (scratch / "source.txt").write_text("conflict\n")
                self.git("add", ".", repo=scratch)
                self.git("commit", "-qm", "conflict", repo=scratch)
            result = subprocess.run([str(worker)], cwd=scratch, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if bad:
                self.assertIn("apply:", self.git("show", "HEAD:hand-in-note.txt", repo=scratch))
            else:
                self.assertEqual(self.git("rev-parse", "HEAD^{tree}", repo=scratch), self.git("rev-parse", self.reference + "^{tree}"))

    def test_stand_in_records_apply_and_commit_failures(self):
        done, out = self.reference_run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        real_git = shutil.which("git")
        failing = self.tmp / "failing-bin"
        failing.mkdir()
        for step in ("apply", "commit"):
            scratch = self.tmp / ("scratch-" + step)
            self.git("clone", "-q", str(self.repo), str(scratch))
            self.git("checkout", "-q", "--detach", self.base, repo=scratch)
            wrapper = failing / "git"
            # The note's own add/commit must still work, so only the reference
            # hand-in command fails; no production test switch is introduced.
            wrapper.write_text("#!" + sys.executable + "\nimport os, sys\n"
                "args = sys.argv[1:]\n"
                "if " + repr(step) + " in args and not os.path.exists('hand-in-note.txt'):\n"
                "    sys.stderr.write('synthetic " + step + " error\\n'); sys.exit(7)\n"
                "os.execv(" + repr(real_git) + ", ['git'] + args)\n")
            wrapper.chmod(0o755)
            result = subprocess.run([str(out / "stand-in" / "worker.sh")], cwd=scratch,
                env=dict(self.env, PATH=str(failing) + os.pathsep + os.environ["PATH"]), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            note = self.git("show", "HEAD:hand-in-note.txt", repo=scratch)
            self.assertIn(step + ": synthetic " + step + " error", note)

    def test_stand_in_records_directory_failure(self):
        done, out = self.reference_run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        scratch = self.tmp / "scratch-directory"
        self.git("clone", "-q", str(self.repo), str(scratch))
        self.git("checkout", "-q", "--detach", self.base, repo=scratch)
        failing = self.tmp / "failing-bin"
        failing.mkdir()
        program = failing / "dirname"
        program.write_text("#!/bin/sh\nprintf '%s\\n' " + shlex.quote(str(self.tmp / "missing-directory")) + "\n")
        program.chmod(0o755)
        done = subprocess.run([str(out / "stand-in" / "worker.sh")], cwd=scratch,
            env=dict(self.env, PATH=str(failing) + os.pathsep + os.environ["PATH"]), capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("where:", self.git("show", "HEAD:hand-in-note.txt", repo=scratch))

    def test_stand_in_does_not_claim_to_have_committed_a_note_when_git_refuses(self):
        done, out = self.reference_run()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        for fail in ("add", "commit"):
            scratch = self.tmp / ("note-" + fail)
            self.git("clone", "-q", str(self.repo), str(scratch))
            self.git("checkout", "-q", "--detach", self.base, repo=scratch)
            (scratch / "source.txt").write_text("conflict\n")
            self.git("add", ".", repo=scratch)
            self.git("commit", "-qm", "conflict", repo=scratch)
            head = self.git("rev-parse", "HEAD", repo=scratch)
            failing = scratch / "bin"
            failing.mkdir()
            program = failing / "git"
            program.write_text("#!" + sys.executable + "\nimport os, sys\n"
                "args = sys.argv[1:]\n"
                "if " + repr(fail) + " in args and os.path.isfile('hand-in-note.txt'):\n"
                "    sys.exit(7)\n"
                "os.execv(" + repr(shutil.which("git")) + ", ['git'] + args)\n")
            program.chmod(0o755)
            done = subprocess.run([str(out / "stand-in" / "worker.sh")], cwd=scratch,
                env=dict(self.env, PATH=str(failing) + os.pathsep + os.environ["PATH"]), capture_output=True, text=True)
            self.assertNotEqual(done.returncode, 0)
            self.assertEqual(self.git("rev-parse", "HEAD", repo=scratch), head)


if __name__ == "__main__":
    unittest.main()
