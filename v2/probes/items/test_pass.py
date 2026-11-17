#!/usr/bin/env python3
"""Pass tests: toy item repositories and stand-in worker programs, no model.

Run: python3 -I test_pass.py. Real-clock tests are selected with YAK_PASS_JAIL=1
and YAK pointing to a built room program on a host that can enter its jail.
The whole-pass class also needs YAK_PASS_REAL_STORE=1, executable YAK_STORE,
and YAK_STORE_FILES naming the real store's sources.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
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

# The second half: the room's offer commands, a block in the prompt, the record of
# the block, the item's base and its walks. The stand-in mirrors what the pass reads
# (route_offer.rs: canonical answer naming the list and repository, goals as asked;
# offer.rs: the offer file, Offer::empty, the blocks' lines and marks).
OFFER_FAKE = r'''
import hashlib, random
MARK = {"same": "", "changed": " (changed since)", "gone": " (gone)"}
def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
def render(offer, arm, seed):
    text = "OPENING the block\n\n"
    if not any(g["route"] is not None for g in offer["goals"]):
        return text + "Earlier turns left nothing for this item.\n"
    named = []
    for g in offer["goals"]:
        named.append((g["path"], g["state"]))
        named += [(r["to"], r["state"]) for r in (g["route"] or {}).get("roads", [])]
    if arm == "shuffled":
        places = sorted(dict(named).items())
        random.Random(seed).shuffle(places)
        return text + "SHUFFLED\n" + "".join("- %s%s\n" % (p, MARK[s]) for p, s in places)
    text += "ROUTE\n"
    for n, g in enumerate(offer["goals"], 1):
        if g["route"] is None:
            text += "%d. %s%s, with no way to it: %s\n" % (n, g["path"], MARK[g["state"]], g["none"])
            continue
        text += "%d. %s%s\n" % (n, g["path"], MARK[g["state"]])
        for k, r in enumerate(g["route"]["roads"]):
            text += "   %s %s%s: walked by %d\n" % ("then to" if k else "from where every turn starts to", r["to"],
                MARK[r["state"]], r["walked_by"])
        if g["route"]["dearer_ways"]:
            text += "   %d went a dearer way to it\n" % g["route"]["dearer_ways"]
    return text
def word(name):
    return args[args.index(name) + 1]
if args[:2] == ["offer", "goals"]:
    listed = hashlib.sha256(pathlib.Path(word("--list")).read_bytes()).hexdigest()
    names = config.get("goals", {}).get(word("--title"), ["docs/notes.md", "peer/superyak_peer/b.py", "added.txt"])
    measure = {"name": "share", "version": 1}
    print(json.dumps({"ranker": "title-words-1", "history": listed, "measure": measure,
        "chosen": [{"attempt": "a000000000001", "score": 2}, {"attempt": "a000000000002", "score": 1}], "goals": names,
        "question": {"v": 1, "repo": "b" * 40, "list": listed, "measure": measure, "goals": names}}))
    sys.exit(0)
if args[:2] == ["offer", "make"]:
    goals = json.loads(pathlib.Path(word("--goals")).read_text())
    if len(goals["goals"]) > 64:
        print("refused: goals.limit", file=sys.stderr); sys.exit(1)
    raw = pathlib.Path(word("--answer")).read_bytes()
    answer = json.loads(raw)
    if (canonical(answer) != raw or answer["store"] != "3" or answer["list"] != goals["history"]
            or answer["repo"] != goals["question"]["repo"] or [a["goal"] for a in answer["answers"]] != goals["goals"]):
        print("refused: answer", file=sys.stderr); sys.exit(1)
    states = config.get("states", {})
    output = []
    for a in answer["answers"]:
        if "route" in a:
            roads = [{"to": r["to"], "walked_by": r["turns"], "state": states.get(r["to"], "same")} for r in a["route"]["roads"]]
            output.append({"path": a["goal"], "state": states.get(a["goal"], "same"), "route": {"roads": roads,
                "cost_millis": 1504, "dearer_ways": len(a["route"]["detours"])}})
        else:
            output.append({"path": a["goal"], "state": states.get(a["goal"], "same"), "route": None, "none": a["none"]})
    pathlib.Path(word("--out")).write_bytes(canonical({"offer": 1, "history": goals["history"], "ranker": goals["ranker"],
        "store": "3", "kernel": answer["kernel"], "measure": {"name": "share", "version": "1"}, "chosen": goals["chosen"],
        "goals": output}))
    sys.exit(0)
if args[:2] == ["offer", "render"]:
    sys.stdout.write(render(json.loads(pathlib.Path(word("--offer")).read_text()), word("--arm"), int(word("--seed"))))
    sys.exit(0)
'''

WALK_STEPS = [{"seq": 0, "named": [["README.md", "5" * 40]], "seen_ms": 1000},
              {"seq": 1, "named": [["peer/superyak_peer/start.py", "4" * 40]], "seen_ms": 4000},
              {"seq": 2, "named": [["peer/superyak_peer/ref.py", "7" * 40]], "seen_ms": 2500}]

PASS_FAKE = PASS_FAKE.replace("\nroom = pathlib.Path(args[1]); words = args[2:]",
    OFFER_FAKE + "\nroom = pathlib.Path(args[1]); words = args[2:]", 1)
PASS_FAKE = PASS_FAKE.replace('    worker = words[words.index("--worker") + 1]\n', '''    worker = words[words.index("--worker") + 1]
    block = None
    if "--offer" in words:
        block = render(json.loads(pathlib.Path(word("--offer")).read_text()), word("--arm"), int(word("--seed")))
    prompt = ("This is turn of the room.\\n\\nThe item\\n\\n" + ("" if block is None else block + "\\n") + "The rules\\n").encode()
''')
PASS_FAKE = PASS_FAKE.replace('subprocess.check_call([worker.split(":", 1)[1]], cwd=scratch)',
    'subprocess.run([worker.split(":", 1)[1]], cwd=scratch, input=prompt, check=True)')
PASS_FAKE = PASS_FAKE.replace('        offered.update(config.get("offered", {}))', '''        offered.update(config.get("offered", {}))
        if block is not None or config.get("made_under_nothing"):
            text = (block or "a block").encode()
            offered["made"] = {"block_sha256": hashlib.sha256(text).hexdigest(), "block_bytes": len(text),
                "empty": "left nothing" in (block or "")}
            offered["made"].update(config.get("made", {}).get(slot, {}))''')
PASS_FAKE = PASS_FAKE.replace('(room / "view.json").write_text(json.dumps({"state": state}))',
    '(room / "view.json").write_text(json.dumps({"state": state})); '
    '(room / "base.txt").write_text(config.get("room_bases", {}).get(slot, add[add.index("--base") + 1]))')
PASS_FAKE = PASS_FAKE.replace('elif words[:2] == ["item", "turns"]:', '''elif words[:2] == ["item", "walks"]:
    turn = json.loads((room / "turns.json").read_text())[0]
    slot = str(json.loads((room.parent / "manifest.json").read_text())["slot"])
    if slot not in config.get("no_walk", []):
        print(json.dumps({"v": 1, "attempt": config.get("walk_attempts", {}).get(slot, turn["attempt"]), "item": words[2],
            "base": (room / "base.txt").read_text(), "steps": config.get("walks", {}).get(slot,
            %s), "changed": []}, sort_keys=True, separators=(",", ":")))
elif words[:2] == ["item", "turns"]:''' % json.dumps(WALK_STEPS))
for _needle in ("block = render", "input=prompt", 'offered["made"]', "base.txt", '["item", "walks"]', 'args[:2] == ["offer", "make"]'):
    assert _needle in PASS_FAKE, _needle

STORE = r'''
import hashlib, json, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
config = json.loads((here / "store-config.json").read_text())
args = sys.argv[1:]
with (here / "store-calls.jsonl").open("a") as out:
    out.write(json.dumps(args) + "\n")
def word(name):
    return args[args.index(name) + 1]
if args[0] == "build":
    walks = args[args.index("--list") + 2:]
    listed = hashlib.sha256(pathlib.Path(word("--list")).read_bytes()).hexdigest()
    pathlib.Path(word("--out")).write_text(json.dumps({"list": listed, "walks": walks}))
    print("built from %d walks" % len(walks)); sys.exit(0)
if args[0] == "check":
    json.loads(pathlib.Path(word("--store")).read_text())
    print(config.get("check", "store 3: whole")); sys.exit(config.get("check_exit", 0))
if args[0] == "ask":
    question = json.loads(sys.stdin.read())
    store = json.loads(pathlib.Path(word("--store")).read_text())
    answers = []
    for goal in question["goals"]:
        if config.get("all_none") or goal in config.get("none", ["added.txt"]):
            answers.append({"goal": goal, "none": "never_named"})
            continue
        # A route stitched from three turns' roads, with two detours.
        start, middle = "peer/superyak_peer/start.py", "README.md"
        roads = [{"from": None, "to": start, "turns": 2, "witness": "a000000000001"},
                 {"from": start, "to": middle, "turns": 1, "witness": "a000000000002"},
                 {"from": middle, "to": goal, "turns": 1, "witness": "a000000000003"}]
        detours = [{"attempt": "a00000000000%d" % n, "cost": {"den": "27", "nats": "2.602689685", "num": "2"},
            "family": "claude", "item": "i00000000000%d" % n, "paths": [start, "x.txt", goal], "roads_n": 3, "seq": 3,
            "visit": 3} for n in (1, 2)]
        answers.append({"goal": goal, "route": {"blobs": {start: ["4" * 40], middle: ["5" * 40], goal: ["6" * 40]},
            "cost": {"den": "9", "nats": "1.504077397", "num": "2"}, "detours": detours, "detours_more": 0,
            "paths": [start, middle, goal], "roads": roads, "roads_n": 3}})
    answer = {"answers": answers, "for_experiment": True, "kernel": "511bacd017146586", "list": store["list"],
        "measure": {"name": "share", "teaches": ["passed_verified"], "version": 1}, "path_rule": 1,
        "repo": question["repo"], "store": "3", "taught": 3, "v": 1}
    sys.stdout.write(json.dumps(answer, sort_keys=True, indent=config.get("indent"),
        separators=None if config.get("indent") else (",", ":")) + "\n"); sys.exit(0)
sys.exit(9)
'''


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

    def test_list_holds_each_rooms_own_attempt_against_both_files(self):
        """The history's record and the teach plan can agree with each other and still not be what a room
        holds. Only the room's own attempt tells: a mutant that dropped that comparison passed every test."""
        self.ready_history()
        history = self.read("history.json")
        true = history["turns"][1]["attempt"]
        self.assertNotEqual(true, "afedcba987654")
        history["turns"][1]["attempt"] = "afedcba987654"
        (self.out / "history.json").write_text(json.dumps(history))
        teach = {"items": [{key: t[key] for key in ("room", "item", "attempt")} for t in history["turns"][1:]]}
        (self.out / "teach-plan.json").write_text(json.dumps(teach))
        self.refused(self.run_script("pass.sh", "list", self.out), "differs from the history turns")
        self.assertFalse((self.out / "list.json").exists())
        # The control: the room's own attempt back in both files, and the list is made.
        history["turns"][1]["attempt"] = true
        (self.out / "history.json").write_text(json.dumps(history))
        teach["items"][0]["attempt"] = true
        (self.out / "teach-plan.json").write_text(json.dumps(teach))
        self.ok(self.run_script("pass.sh", "list", self.out))
        self.assertEqual(self.read("list.json")["status"], "ready")

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


class SecondHalf(unittest.TestCase):
    """offers, arms, report and run, with the stand-in room above and a stand-in store."""
    git = PassScripts.git
    write_list = PassScripts.write_list
    configure = PassScripts.configure
    run_script = PassScripts.run_script
    plan = PassScripts.plan
    ok = PassScripts.ok
    refused = PassScripts.refused
    read = PassScripts.read
    screen = PassScripts.screen

    def setUp(self):
        PassScripts.setUp(self)
        self.store.write_text("#!" + sys.executable + "\n" + STORE)
        self.store_config()
        # The worker keeps the prompt it was given beside its turn.
        self.worker.write_text("#!/bin/sh\ncat > ../prompt.txt\n")
        # A reference that changes a source file, so a walk can name one first.
        self.git("checkout", "-q", "--detach", self.reference)
        (self.repo / "peer" / "superyak_peer").mkdir(parents=True)
        (self.repo / "peer" / "superyak_peer" / "ref.py").write_text("changed\n")
        self.git("add", ".")
        self.git("commit", "-qm", "reference with a source file")
        reference = self.git("rev-parse", "HEAD")
        for entry in self.entries:
            entry["reference"] = reference
            self.git("update-ref", "refs/yak-items/%s/reference" % entry["commit"], reference)
        self.write_list()

    def store_config(self, **config):
        (self.bin / "store-config.json").write_text(json.dumps(config))

    def stage(self, name):
        return self.run_script("pass.sh", name, self.out)

    def to_list(self, rounds=1, **config):
        self.configure(**config)
        self.ok(self.plan(extra=("--rounds", str(rounds))))
        self.assertEqual(self.screen(), 0)
        self.ok(self.stage("history"))
        self.ok(self.stage("list"))

    def to_offers(self, rounds=1, **config):
        self.to_list(rounds, **config)
        self.ok(self.stage("offers"))
        return self.read("offers.json")

    def calls(self):
        return [json.loads(x) for x in (self.bin / "calls.jsonl").read_text().splitlines()]

    def test_fixture_goes_through_offers_arms_report_in_two_rounds(self):
        offers = self.to_offers(rounds=2)
        self.assertEqual(offers["status"], "ready")
        self.assertEqual(offers["store_check"], "store 3: whole")
        self.assertFalse(offers["goal_limit"])
        self.assertEqual([i["commit"] for i in offers["items"]], self.three)
        store_calls = [json.loads(x) for x in (self.bin / "store-calls.jsonl").read_text().splitlines()]
        self.assertEqual([c[0] for c in store_calls], ["build", "check", "ask", "ask", "ask"])
        walks = [w["file"] for w in self.read("list.json")["walks"]]
        self.assertEqual(store_calls[0][store_calls[0].index("--list") + 2:], walks)
        for item in offers["items"]:
            here = Path(item["directory"])
            self.assertEqual(here, self.out / "offers" / item["commit"])
            for name, held in item["files"].items():
                data = (here / name).read_bytes()
                self.assertEqual(held, {"file": str(here / name), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            self.assertEqual(item["answer_bytes"], len((here / "answer.json").read_bytes()))
            question = (here / "question.json").read_bytes()
            self.assertEqual(question, (json.dumps(json.loads((here / "goals.json").read_text())["question"],
                sort_keys=True, separators=(",", ":")) + "\n").encode())
            self.assertEqual((item["goals"], item["empty"]), (3, False))
            self.assertEqual(item["route"]["places"], 5)
            self.assertEqual(item["route"]["roads"], 6)
            self.assertEqual(item["shuffled"]["places"], 5)
            self.assertEqual(item["shuffled"]["roads"], 0)
            self.assertEqual(item["route"]["first_tracked_path"], "docs/notes.md")
            self.assertEqual(item["route"]["first_source_file"], "peer/superyak_peer/start.py")
            self.assertEqual(item["route"]["sha256"], item["files"]["block-route.txt"]["sha256"])
            offer = json.loads((here / "offer.json").read_text())
            self.assertEqual(sum(len(g["route"]["roads"]) for g in offer["goals"] if g["route"]), 6)
            self.assertEqual([g["route"]["dearer_ways"] for g in offer["goals"] if g["route"]], [2, 2])
        held = {name: (self.out / name).read_bytes() for name in ("teach-plan.json", "list.json", "room-plan.json")}
        history = {p.name: p.read_bytes() for p in (self.out / "history").iterdir()}
        self.ok(self.stage("arms"))
        arms = self.read("arms.json")
        self.assertEqual(arms["status"], "complete")
        self.assertEqual(len(arms["turns"]), 18)
        plan_rows = [r for r in self.read("plan.json")["order"] if r["kind"] == "arms"]
        self.assertEqual([(t["order"], t["arm"], t["commit"], t["round"]) for t in arms["turns"]],
            [(r["order"], r["arm"], r["commit"], r["round"]) for r in plan_rows])
        kept = {i["commit"]: i for i in offers["items"]}
        for t in arms["turns"]:
            attempt = json.loads((Path(t["directory"]) / "turns.json").read_text())[0]
            prompt = (Path(t["directory"]) / "prompt.txt").read_bytes()
            self.assertEqual(t["base"], kept[t["commit"]]["base"])
            for key in ("began", "ended", "load_before", "load_after", "attempt", "room", "item"):
                self.assertIsNotNone(t[key], key)
            if t["arm"] == "nothing":
                self.assertNotIn("made", attempt["offered"])
                self.assertNotIn(b"OPENING", prompt)
                for arm in ("route", "shuffled"):
                    self.assertNotIn((Path(kept[t["commit"]]["directory"]) / ("block-%s.txt" % arm)).read_bytes(), prompt)
            else:
                block = (Path(kept[t["commit"]]["directory"]) / ("block-%s.txt" % t["arm"])).read_bytes()
                self.assertIn(block, prompt)
                self.assertEqual(attempt["offered"]["made"]["block_sha256"], hashlib.sha256(block).hexdigest())
                self.assertEqual(attempt["offered"]["made"]["block_bytes"], len(block))
                run = next(c for c in self.calls() if c[2:4] == ["clock", "run"] and c[1] == t["room"])
                self.assertEqual(run[run.index("--offer") + 1], kept[t["commit"]]["files"]["offer.json"]["file"])
        # A turn of arms never teaches.
        for name, data in held.items():
            self.assertEqual((self.out / name).read_bytes(), data, name)
        self.assertEqual({p.name: p.read_bytes() for p in (self.out / "history").iterdir()}, history)
        self.refused(self.stage("list"), "new pass directory")
        self.ok(self.stage("report"))
        report = self.read("report.json")
        self.assertEqual(len(report["turns"]), 18)
        self.assertIn("Conventions: a step's number counts from nought", (self.out / "report.md").read_text())
        for t in report["turns"]:
            self.assertEqual(t["first_source_file"], {"step": 2, "second": 2.5, "path": "peer/superyak_peer/ref.py"})
            self.assertEqual(t["first_reference_file"], {"step": 2, "second": 2.5, "path": "peer/superyak_peer/ref.py"})
            self.assertEqual(t["active_seconds"], 0.006)
        self.assertEqual(report["items_with_ratios"], 6)
        self.assertEqual(report["teaching_count"], 8)
        self.assertEqual(len(report["screen"]), 26)
        for word in ("spread", "significan", "p-value", "confidence"):
            self.assertNotIn(word, json.dumps(report).lower())
        before = {name: (self.out / name).read_bytes() for name in ("arms.json", "offers.json", "list.json")}
        self.ok(self.stage("report"))
        self.assertEqual({name: (self.out / name).read_bytes() for name in before}, before)

    def test_empty_offer_gets_no_turns_and_is_reported(self):
        title = next(e["title"] for e in self.entries if e["commit"] == self.three[1])
        offers = self.to_offers(goals={title: ["added.txt"]})
        self.assertEqual([i["empty"] for i in offers["items"]], [False, True, False])
        self.assertIn(b"left nothing", (self.out / "offers" / self.three[1] / "block-route.txt").read_bytes())
        self.assertEqual(offers["items"][1]["route"]["places"], 0)
        self.assertIsNone(offers["items"][1]["route"]["first_tracked_path"])
        self.ok(self.stage("arms"))
        arms = self.read("arms.json")
        self.assertEqual(arms["left_out"], [self.three[1]])
        self.assertEqual(len(arms["turns"]), 6)
        self.assertNotIn(self.three[1], [t["commit"] for t in arms["turns"]])
        self.ok(self.stage("report"))
        self.assertEqual(self.read("report.json")["left_out"], [self.three[1]])
        self.assertIn("Left out under the arms, for an empty offer: " + self.three[1], (self.out / "report.md").read_text())
        self.assertIn("none named", (self.out / "report.md").read_text())

    def test_all_empty_stops_before_any_turn(self):
        self.store_config(all_none=True)
        self.to_list()
        self.refused(self.stage("offers"), "every offer is empty")
        self.assertEqual(self.read("offers.json")["status"], "stopped")
        self.assertEqual([i["empty"] for i in self.read("offers.json")["items"]], [True, True, True])
        self.refused(self.stage("arms"), "offers.json does not let")
        self.assertFalse((self.out / "arms").exists())

    def test_more_than_64_goals_stops_with_its_own_reason_and_nothing_is_cut(self):
        title = next(e["title"] for e in self.entries if e["commit"] == self.three[0])
        names = ["peer/superyak_peer/m%02d.py" % n for n in range(65)]
        self.to_list(goals={title: names})
        self.refused(self.stage("offers"), "more than 64 goals")
        offers = self.read("offers.json")
        self.assertTrue(offers["goal_limit"])
        self.assertEqual(offers["items"][0]["goals"], 65)
        self.assertIn("goals.limit", offers["items"][0]["refused"])
        self.assertEqual(json.loads((self.out / "offers" / self.three[0] / "question.json").read_text())["goals"], names)
        self.assertFalse((self.out / "offers" / self.three[0] / "offer.json").exists())
        self.assertEqual(len(offers["items"]), 1)

    def test_another_refusal_of_the_offer_file_is_told_apart(self):
        # An answer that is not canonical bytes: the room refuses the offer file for another reason.
        self.store_config(indent=1)
        self.to_list()
        self.refused(self.stage("offers"), "the room refused the offer file at")
        offers = self.read("offers.json")
        self.assertFalse(offers["goal_limit"])
        self.assertNotIn("more than 64", offers["reason"])
        self.assertEqual(offers["items"][0]["refused"], "refused: answer")

    def test_offering_arm_stops_on_changed_kept_files_and_store(self):
        self.to_offers()
        item = self.read("offers.json")["items"][0]
        for name in ("block-route.txt", "offer.json"):
            path = Path(item["files"][name]["file"])
            data = path.read_bytes()
            path.write_bytes(data + b" ")
            self.refused(self.stage("arms"), "changed after it was kept")
            self.assertFalse((self.out / "arms").exists())
            path.write_bytes(data)
        Path(item["files"]["offer.json"]["file"]).rename(self.tmp / "away")
        self.refused(self.stage("arms"), "is missing")
        (self.tmp / "away").rename(item["files"]["offer.json"]["file"])
        for path in (self.store, self.store_file):
            data = path.read_bytes()
            path.write_bytes(data + b"\n")
            self.refused(self.stage("arms"), "input changed after plan")
            path.write_bytes(data)
        self.assertFalse((self.out / "arms").exists())

    def test_store_changed_after_plan_stops_offers(self):
        self.to_list()
        self.store_file.write_text("# another store\n")
        self.refused(self.stage("offers"), "input changed after plan")
        self.assertFalse((self.out / "offers").exists())

    def arms_stop(self, reason, turns, **config):
        self.to_offers(**config)
        self.refused(self.stage("arms"), reason)
        arms = self.read("arms.json")
        self.assertEqual(arms["status"], "stopped")
        self.assertEqual(len(arms["turns"]), turns)
        return arms

    def test_block_changed_between_turns_stops(self):
        self.to_list()
        self.ok(self.stage("offers"))
        block = self.read("offers.json")["items"][0]["files"]["block-shuffled.txt"]["file"]
        self.configure(mutate_list=block, mutate_at=10)
        self.refused(self.stage("arms"), "changed after it was kept")
        self.assertEqual(len(self.read("arms.json")["turns"]), 1)
        self.assertTrue((self.out / "turns" / ("010-arms-%s" % self.three[0]) / "turns.json").exists())

    def test_record_block_differs_stops(self):
        self.to_list()
        self.ok(self.stage("offers"))
        offering = [r["order"] for r in self.read("plan.json")["order"] if r["kind"] == "arms" and r["arm"] != "nothing"]
        self.configure(made={str(offering[0]): {"block_sha256": "0" * 64}})
        self.refused(self.stage("arms"), "hash or length is not the one kept")
        self.assertEqual(len(self.read("arms.json")["turns"]), offering[0] - 9)

    def test_record_block_length_differs_stops(self):
        self.to_list()
        self.ok(self.stage("offers"))
        offering = [r["order"] for r in self.read("plan.json")["order"] if r["kind"] == "arms" and r["arm"] != "nothing"]
        self.configure(made={str(offering[1]): {"block_bytes": 1}})
        self.refused(self.stage("arms"), "hash or length is not the one kept")
        self.assertEqual(len(self.read("arms.json")["turns"]), offering[1] - 9)

    def test_nothing_record_with_a_block_stops(self):
        self.to_list()
        self.ok(self.stage("offers"))
        self.configure(made_under_nothing=True)
        arms = self.read("plan.json")["order"][9:]
        first_nothing = next(n for n, r in enumerate(arms) if r["arm"] == "nothing")
        self.refused(self.stage("arms"), "under nothing holds a block")
        self.assertEqual(len(self.read("arms.json")["turns"]), first_nothing + 1)

    def test_room_at_another_base_stops(self):
        self.arms_stop("another base", 2, room_bases={"11": "0" * 40})

    def test_the_base_is_read_from_the_rooms_walk_of_the_turns_own_attempt(self):
        """The real room prints an item's base only in the walk it exports; `item show` does not give it."""
        self.arms_stop("no one walk of its attempt", 2, walk_attempts={"11": "afedcba987654"})

    def test_a_turn_with_no_walk_stops(self):
        self.arms_stop("no one walk of its attempt", 2, no_walk=["11"])

    def test_lost_turn_stops(self):
        self.arms_stop("no verdict", 3, lost_at=12)

    def test_STOP_between_turns(self):
        arms = self.arms_stop("STOP before turn 12", 2, stop_at=11)
        self.assertTrue(all("passed" in t for t in arms["turns"]))

    def test_failed_turn_does_not_stop_and_is_reported_with_seconds(self):
        self.to_offers(failed_at=13)
        self.ok(self.stage("arms"))
        arms = self.read("arms.json")
        failed = next(t for t in arms["turns"] if t["order"] == 13)
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["clock_exit"], 1)
        self.assertEqual(len(arms["turns"]), 9)
        self.ok(self.stage("report"))
        report = self.read("report.json")
        row = next(t for t in report["turns"] if t["order"] == 13)
        self.assertFalse(row["passed"])
        self.assertEqual((row["worker_seconds"], row["active_seconds"]), (0.002, 0.006))
        self.assertEqual(report["items_with_ratios"], 2)
        ratios = {i["commit"]: i["ratios"] for i in report["items"]}
        self.assertIsNone(ratios[failed["commit"]])
        self.assertIn("not all three passed", (self.out / "report.md").read_text())
        self.assertIn("Items with ratios: 2", (self.out / "report.md").read_text())

    def test_report_blocks_apart_and_a_walk_naming_no_source_file(self):
        quiet = [{"seq": 0, "named": [["README.md", "5" * 40]], "seen_ms": 900}]
        self.to_offers(walks={"10": quiet}, states={"docs/notes.md": "gone", "README.md": "changed"})
        self.ok(self.stage("arms"))
        self.ok(self.stage("report"))
        report = self.read("report.json")
        row = next(t for t in report["turns"] if t["order"] == 10)
        self.assertIsNone(row["first_source_file"])
        self.assertIsNone(row["first_reference_file"])
        self.assertEqual(row["steps"], 1)
        block = report["blocks"][0]
        self.assertEqual(block["route"]["first_tracked_path"], "peer/superyak_peer/start.py")
        self.assertEqual(block["route"]["first_source_file"], "peer/superyak_peer/start.py")
        self.assertEqual((block["route"]["gone"], block["route"]["changed"]), (1, 1))
        shuffled = (self.out / "offers" / self.three[0] / "block-shuffled.txt").read_text().splitlines()
        listed = [line[2:].split(" (")[0] for line in shuffled if line.startswith("- ")]
        self.assertEqual(block["shuffled"]["first_tracked_path"], next(p for p in listed if p != "docs/notes.md"))
        self.assertEqual(block["shuffled"]["first_source_file"], next(p for p in listed if p.startswith("peer/superyak_peer/")))
        self.assertEqual(len(report["turns"]), 9)
        self.assertIn("none named", (self.out / "report.md").read_text())

    def test_refusals_and_second_runs(self):
        self.ok(self.plan())
        self.refused(self.stage("offers"), "list.json is missing")
        self.refused(self.stage("arms"), "list.json is missing")
        self.refused(self.stage("report"), "arms.json is missing")
        self.assertEqual(self.screen(), 0)
        self.ok(self.stage("history"))
        self.ok(self.stage("list"))
        self.refused(self.stage("arms"), "offers.json is missing")
        self.ok(self.stage("offers"))
        offers = (self.out / "offers.json").read_bytes()
        self.refused(self.stage("offers"), "new pass directory")
        self.assertEqual((self.out / "offers.json").read_bytes(), offers)
        self.ok(self.stage("arms"))
        arms = (self.out / "arms.json").read_bytes()
        self.refused(self.stage("arms"), "new pass directory")
        self.assertEqual((self.out / "arms.json").read_bytes(), arms)

    def test_list_files_changed_refuse_offers_and_arms(self):
        self.to_list()
        for name in ("teach-plan.json", "room-plan.json", "history/history.json"):
            path = self.out / name
            data = path.read_bytes()
            path.write_bytes(data + b" ")
            self.refused(self.stage("offers"), "changed after the list")
            path.write_bytes(data)
        self.assertFalse((self.out / "offers").exists())
        self.ok(self.stage("offers"))
        walk = Path(self.read("list.json")["walks"][0]["file"])
        walk.write_bytes(walk.read_bytes() + b" ")
        self.refused(self.stage("arms"), "changed after the list")
        self.assertFalse((self.out / "arms").exists())

    def test_list_that_stopped_refuses_offers(self):
        self.configure(unverified=[0, 1, 2, 3, 4])
        self.ok(self.plan())
        self.assertEqual(self.screen(), 0)
        self.ok(self.stage("history"))
        self.refused(self.stage("list"), "fewer than four")
        self.refused(self.stage("offers"), "list.json does not let")
        self.assertFalse((self.out / "offers").exists())

    def run_in_process(self, failures=()):
        driver = module("pass_driver")

        def reference(out, items, commit):
            out.mkdir()
            outcome = "check failed" if commit in failures else "passed"
            driver.pilot.write_json(out / "reference.json", {"outcome": outcome, "verified": outcome == "passed"})
            return 0 if outcome == "passed" else 1

        argv = ["run", str(self.out), str(self.items), "script:" + str(self.worker), "--three", *self.three,
            "--history", *self.history_commits, "--seed", "20261117"]
        said = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch.object(driver.pilot, "reference", side_effect=reference):
            with contextlib.redirect_stderr(said):
                code = driver.main(argv)
        self.said = said.getvalue()
        return code

    def test_run_all_stages_in_order(self):
        self.assertEqual(self.run_in_process(), 0)
        for name in ("plan.json", "screen.json", "history.json", "list.json", "offers.json", "arms.json", "report.json"):
            self.assertTrue((self.out / name).exists(), name)
        self.assertEqual(self.read("arms.json")["status"], "complete")
        self.assertEqual(len(self.read("report.json")["turns"]), 9)

    def test_run_stops_at_the_screen_and_begins_no_later_stage(self):
        self.assertEqual(self.run_in_process(failures=self.three[:1]), 1)
        self.assertIn("run stopped at screen: a three-item reference check failed", self.said)
        self.assertEqual(self.read("screen.json")["status"], "stopped")
        for name in ("turns", "history.json", "list.json", "offers", "offers.json", "arms", "arms.json", "report.json"):
            self.assertFalse((self.out / name).exists(), name)


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


@unittest.skipUnless(
    os.environ.get("YAK_PASS_JAIL") == "1" and os.environ.get("YAK_PASS_REAL_STORE") == "1"
    and Path(os.environ.get("YAK_STORE", "")).is_file()
    and os.access(os.environ.get("YAK_STORE", ""), os.X_OK),
    "needs YAK_PASS_JAIL=1, YAK_PASS_REAL_STORE=1 and YAK_STORE naming an executable file")
class RealRoomPass(unittest.TestCase):
    """The entire pass with the actual clock, jail and external version-3 store.

    The Codex *wrapper* runs outside the OS jail (sandbox.rs::run_model); its
    shell permissions would be enforced by Codex itself. This no-model wrapper
    can therefore save prompts beside the fixture, outside every checkout and
    outside YAK_JAIL_READ. The room's checks still enter the real OS jail.
    """
    git = PassScripts.git
    write_list = PassScripts.write_list
    run_script = PassScripts.run_script
    SEED = 20261117
    SOURCE = "peer/superyak_peer/target.py"
    START = "peer/superyak_peer/start.py"
    TITLES = ("amber bridge", "cobalt bridge", "violet orchard", "sienna ridge", "teal arch")
    ARM_TITLES = ("amber repair", "cobalt repair", "quartz obelisk")
    ROADS = (
        ("README.md", START, SOURCE),
        ("docs/guide.md", "peer/superyak_peer/other.py", SOURCE),
        ("README.md", "docs/detour.md", "peer/superyak_peer/other.py", START, SOURCE),
        ("docs/guide.md", START, SOURCE),
        ("README.md", "peer/superyak_peer/other.py", SOURCE),
    )
    CODEX = r'''
import json, pathlib, re, shutil, subprocess, sys, time
if sys.argv[1:] == ["--version"]:
    print("codex pass-test 1")
    sys.exit(0)
prompt = sys.stdin.buffer.read()
match = re.match(rb"This is turn (\S+) of the room\.\n", prompt)
if match is None:
    raise SystemExit("expected the room's own first line, found %r" % prompt[:120])
attempt = match.group(1).decode("ascii")
capture = pathlib.Path(config["capture"])
capture.mkdir(exist_ok=True)
(capture / (attempt + ".prompt")).write_bytes(prompt)
title = next(line[len("The item: "):] for line in prompt.decode().splitlines() if line.startswith("The item: "))
out = pathlib.Path(config["out"])
before = capture / "before-arms"
if title in config["arm_titles"] and not before.exists():
    before.mkdir()
    for name in ("teach-plan.json", "room-plan.json", "list.json"):
        shutil.copyfile(str(out / name), str(before / name))
    shutil.copytree(str(out / "history"), str(before / "history"))
paths = config["roads"].get(title, config["arm_roads"])
def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)
emit({"type": "thread.started", "thread_id": "00000000-0000-0000-0000-000000000000"})
emit({"type": "turn.started"})
for number, path in enumerate(paths):
    item = {"id": "item_%d" % number, "type": "command_execution", "command": "cat " + path,
            "aggregated_output": "", "exit_code": None, "status": "in_progress"}
    emit({"type": "item.started", "item": item})
    # Actually read the named file; the stream uses the same event pair and id
    # as codex-json-sample.jsonl, so this is one Shell step, not two.
    data = pathlib.Path(path).read_text()
    item.update(aggregated_output=data, exit_code=0, status="completed")
    emit({"type": "item.completed", "item": item})
    time.sleep(0.01)  # Distinct seen_ms values make report ordering unambiguous.
if title == config["fail_title"]:
    pathlib.Path(config["source"]).write_text("still wrong\n")
else:
    subprocess.run(["git", "apply", "--binary", config["patch"]], check=True)
# CodexWorker::seal commits the resulting change on the worker's behalf.
emit({"type": "turn.completed", "usage": {"input_tokens": 40, "cached_input_tokens": 10,
      "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 0}})
'''

    def setUp(self):
        self.succeeded = False
        self.tmp = Path(tempfile.mkdtemp(prefix="pass-real-room-")).resolve()
        self.addCleanup(self.clean_or_keep)
        yak = Path(os.environ.get("YAK", ""))
        self.assertTrue(yak.is_file() and os.access(str(yak), os.X_OK),
            "expected YAK to name the real executable; found %r; fixture %s" % (str(yak), self.tmp))
        self.assertTrue(os.environ.get("YAK_STORE_FILES"),
            "expected YAK_STORE_FILES to name the real store's source files; found unset; fixture %s" % self.tmp)
        self.items = self.tmp / "items"
        self.repo = self.items / "repo"
        self.repo.mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.capture = self.tmp / "captured"
        self.capture.mkdir()
        self.out = self.tmp / "pass"
        self.git("init", "-q", "--template=")
        # The JailPass toy repository, extended with tracked source paths and
        # several roads to a shared goal. Checks are separate, frozen files.
        files = {"README.md": "start here\n", "docs/guide.md": "another start\n",
            "docs/detour.md": "a longer way\n", self.START: "start\n",
            "peer/superyak_peer/other.py": "other\n", self.SOURCE: "wrong\n",
            "check.sh": 'test "$(cat peer/superyak_peer/target.py)" = right\n'}
        for name, data in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / "unrelated.txt").write_text("wrong answer\n")
        self.git("add", ".")
        self.git("commit", "-qm", "wrong")
        wrong = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--detach", self.base)
        (self.repo / self.SOURCE).write_text("right\n")
        self.git("add", ".")
        self.git("commit", "-qm", "reference")
        reference = self.git("rev-parse", "HEAD")
        self.entries = []
        for n, title in enumerate(self.TITLES + self.ARM_TITLES):
            self.git("commit", "-q", "--allow-empty", "-m", "item %d" % n)
            commit = self.git("rev-parse", "HEAD")
            for kind, value in (("base", self.base), ("wrong", wrong), ("reference", reference)):
                self.git("update-ref", "refs/yak-items/%s/%s" % (commit, kind), value)
            self.entries.append({"commit": commit, "part": "history" if n < 5 else "pilot",
                "base": self.base, "wrong": wrong, "reference": reference, "title": title,
                "check": {"command": "sh check.sh", "files": ["check.sh"]}})
        self.history_commits = [e["commit"] for e in self.entries[:5]]
        self.three = [e["commit"] for e in self.entries[5:]]
        self.list = self.items / "list" / "items.json"
        self.list.parent.mkdir()
        self.write_list()
        self.patch = self.bin / "reference.patch"
        self.patch.write_bytes(subprocess.check_output(
            ["git", "-C", str(self.repo), "diff", "--binary", self.base, reference]))
        reads = [str(self.bin)] + [p for p in os.environ.get("YAK_JAIL_READ", "").split(os.pathsep) if p]
        search = str(self.bin) + os.pathsep + os.environ.get("YAK_PROBE_PATH", os.environ["PATH"])
        self.env = dict(os.environ, YAK=str(yak.resolve()), PATH=search, YAK_PROBE_PATH=search,
            YAK_JAIL_READ=os.pathsep.join(reads), HOME=str(self.tmp), USER="test", LOGNAME="test")

    def clean_or_keep(self):
        if self.succeeded:
            shutil.rmtree(str(self.tmp))
        else:
            print("\nReal-room pass failed; all artifacts kept at %s" % self.tmp, file=sys.stderr)

    def write_worker(self, fail_title=None):
        config = {"capture": str(self.capture), "out": str(self.out), "patch": str(self.patch),
            "source": self.SOURCE, "fail_title": fail_title, "arm_titles": self.ARM_TITLES,
            "roads": dict(zip(self.TITLES, self.ROADS)), "arm_roads": ["README.md", self.START, self.SOURCE]}
        worker = self.bin / "codex"
        worker.write_text("#!" + sys.executable + "\nconfig = " + repr(config) + "\n" + self.CODEX)
        worker.chmod(0o755)

    def load(self, path):
        path = Path(path)
        self.assertTrue(path.is_file(), "expected a JSON file at %s; found missing" % path)
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError) as error:
            self.fail("expected readable JSON at %s; found %s" % (path, error))

    def equal(self, found, expected, path, what):
        self.assertEqual(found, expected, "%s: expected %r; found %r; inspect %s" % (what, expected, found, path))

    def room(self, row, command):
        done = subprocess.run([self.env["YAK"], "--room", row["room"], "item", command, row["item"], "--json"],
            env=self.env, capture_output=True, text=True)
        path = Path(row["directory"]) / ("real-%s.jsonl" % command)
        path.write_text(done.stdout)
        path.with_suffix(".stderr").write_text(done.stderr)
        self.equal(done.returncode, 0, path, "real yak item %s exit" % command)
        if command == "turns":
            return path, self.load(path)
        return path, [json.loads(line) for line in done.stdout.splitlines() if line.strip()]

    def whole_pass(self, fail_title=None):
        self.write_worker(fail_title)
        done = self.run_script("pass.sh", "run", self.out, self.items, "codex:pass-test", "--three", *self.three,
            "--history", *self.history_commits, "--seed", str(self.SEED))
        log = self.tmp / "run.stdout"
        log.write_text(done.stdout)
        (self.tmp / "run.stderr").write_text(done.stderr)
        self.equal(done.returncode, 0, log,
            "pass.sh run exit (stderr %r; stage logs under %s)" % (done.stderr, self.out))
        names = ("plan.json", "screen.json", "history.json", "list.json", "offers.json", "arms.json", "report.json")
        stages = {name: self.load(self.out / name) for name in names}
        for name, status in (("screen.json", "ready"), ("history.json", "complete"), ("list.json", "ready"),
                ("offers.json", "ready"), ("arms.json", "complete")):
            self.equal(stages[name].get("status"), status, self.out / name, "stage status")
        try:
            printed_plan, position = json.JSONDecoder().raw_decode(done.stdout)
        except ValueError as error:
            self.fail("expected the plan printed before any stage; found %s; inspect %s" % (error, log))
        self.equal(printed_plan, stages["plan.json"], log, "printed plan matches plan.json")
        messages = ("screen ready", "history complete", "list ready:", "offers ready", "arms complete:",
            "report written:", "run complete")
        for message in messages:
            found = done.stdout.find(message, position)
            self.assertGreaterEqual(found, position,
                "expected %r after output offset %d; found %d; inspect %s" % (message, position, found, log))
            position = found + len(message)
        plan, history, listed = (stages[name] for name in ("plan.json", "history.json", "list.json"))
        self.equal(plan.get("worker"), "codex:pass-test", self.out / "plan.json", "worker")
        self.equal(plan["programs"]["worker"].get("version"), "codex pass-test 1", self.out / "plan.json", "worker version")
        # Work section 4's rule here; never call pass_driver.arm_order.
        for commit in self.three:
            expected = sorted(("nothing", "route", "shuffled"), key=lambda arm: (
                hashlib.sha256(("%d:1:%s:%s" % (self.SEED, commit, arm)).encode("utf-8")).hexdigest(), arm))
            self.equal([r["arm"] for r in plan["order"] if r["kind"] == "arms" and r["commit"] == commit],
                expected, self.out / "plan.json", "seeded arm order for " + commit)
        ran = [row for row in history["turns"] if row["kind"] == "history"]
        self.equal([row["kind"] for row in history["turns"]], ["thrown-away"] + ["history"] * 5,
            self.out / "history.json", "one discarded turn followed by five history turns")
        self.equal([r["commit"] for r in ran], self.history_commits, self.out / "history.json", "history turns")
        bindings = [{key: row[key] for key in ("room", "item", "attempt")} for row in ran]
        self.equal(self.load(self.out / "teach-plan.json"), {"items": bindings}, self.out / "teach-plan.json", "only history may teach")
        self.equal(listed["turns"], bindings, self.out / "list.json", "admitted history bindings")
        self.equal(listed["teaching_count"], 4 if fail_title else 5, self.out / "list.json", "verified teaching count")
        before = self.capture / "before-arms"
        self.assertTrue(before.is_dir(), "expected teaching-list snapshot before arms; found missing at %s" % before)
        old = {p.relative_to(before): p.read_bytes() for p in before.rglob("*") if p.is_file()}
        current_paths = [self.out / name for name in ("teach-plan.json", "room-plan.json", "list.json")]
        current_paths += [p for p in (self.out / "history").rglob("*") if p.is_file()]
        current = {p.relative_to(self.out): p.read_bytes() for p in current_paths}
        self.equal(set(current), set(old), before, "teaching files before and after arms")
        for name in old:
            self.equal(current[name], old[name], self.out / name, "unchanged teaching bytes")
        exported = self.load(self.out / "history" / "history.json")
        self.equal({r["attempt"] for r in exported["turns"]}, {r["attempt"] for r in ran},
            self.out / "history" / "history.json", "export contains exactly history turns")
        for row, roads in zip(ran, self.ROADS):
            walk = self.load(self.out / "history" / (row["attempt"] + ".jsonl"))
            self.equal([name for step in walk["steps"] for name, _ in step["named"]], list(roads),
                self.out / "history" / (row["attempt"] + ".jsonl"), "history's chosen road (including the detour)")
        offers, arms, report = (stages[name] for name in ("offers.json", "arms.json", "report.json"))
        self.equal([i["commit"] for i in offers["items"]], self.three, self.out / "offers.json", "offered items")
        kept = {i["commit"]: i for i in offers["items"]}
        blocks = {}
        for commit in self.three:
            item = kept[commit]
            directory = Path(item["directory"])
            answer = self.load(directory / "answer.json")
            self.equal(answer.get("store"), "3", directory / "answer.json", "real store answer version")
            self.equal(item["empty"], commit == self.three[2], self.out / "offers.json", "intentional empty offer")
            goals = self.load(directory / "goals.json")
            if commit != self.three[2]:
                self.assertTrue(goals["chosen"], "expected ranked history for %s; found %r; inspect %s" % (commit, goals, directory / "goals.json"))
                offer = self.load(directory / "offer.json")
                roads = [len(g["route"]["roads"]) for g in offer["goals"] if g.get("route")]
                self.assertTrue(any(n >= 2 for n in roads),
                    "expected a route with at least two roads; found %r; inspect %s" % (roads, directory / "offer.json"))
                self.assertGreaterEqual(item["route"]["roads"], 2,
                    "expected at least two kept route roads; found %r; inspect %s" % (item["route"], self.out / "offers.json"))
            else:
                self.equal(goals["chosen"], [], directory / "goals.json", "unmatched title selects no history")
            blocks[commit] = {arm: (directory / ("block-%s.txt" % arm)).read_bytes() for arm in ("route", "shuffled")}
            if not item["empty"]:
                for arm, block in blocks[commit].items():
                    self.assertTrue(block, "expected nonempty %s block; found %r; inspect %s" % (arm, block, directory))
                self.assertNotEqual(blocks[commit]["route"], blocks[commit]["shuffled"],
                    "expected different route/shuffled blocks; found equal bytes; inspect %s" % directory)
        for row in history["turns"]:
            prompt_path = self.capture / (row["attempt"] + ".prompt")
            self.assertTrue(prompt_path.is_file(), "expected saved nothing-arm stdin; found missing at %s" % prompt_path)
            prompt = prompt_path.read_bytes()
            for commit in self.three[:2]:
                for block in blocks[commit].values():
                    first = block.splitlines()[0]
                    self.assertNotIn(first, prompt,
                        "expected no block first line %r in history/discard; found it in %s" % (first, prompt_path))
        self.equal(arms["left_out"], [self.three[2]], self.out / "arms.json", "empty offer left out")
        expected_rows = [r for r in plan["order"] if r["kind"] == "arms" and r["commit"] != self.three[2]]
        self.equal([(r["order"], r["commit"], r["arm"]) for r in arms["turns"]],
            [(r["order"], r["commit"], r["arm"]) for r in expected_rows], self.out / "arms.json", "exact six planned arm turns")
        self.equal(report["arms_status"], "complete", self.out / "report.json", "report arms status")
        self.equal(report["offers_status"], "ready", self.out / "report.json", "report offers status")
        self.equal([r["order"] for r in report["turns"]], [r["order"] for r in arms["turns"]],
            self.out / "report.json", "one report row per arm turn")
        self.equal([r["commit"] for r in report["history"]], self.history_commits,
            self.out / "report.json", "one history report row per history turn")
        for row, line in zip(arms["turns"], report["turns"]):
            prompt_path = self.capture / (row["attempt"] + ".prompt")
            self.assertTrue(prompt_path.is_file(), "expected saved stdin prompt; found missing at %s" % prompt_path)
            prompt = prompt_path.read_bytes()
            turns_path, turns = self.room(row, "turns")
            self.equal(len(turns), 1, turns_path, "one attempt in real room")
            turn = turns[0]
            self.equal(turn["attempt"], row["attempt"], turns_path, "room attempt matches arms")
            self.equal(turn["passed"], True, turns_path, "worker's reference change passes")
            self.equal(row["base"], self.base, self.out / "arms.json", "the item's base, from the real room's walk")
            made = turn["offered"].get("made")
            if row["arm"] == "nothing":
                self.equal(made, None, turns_path, "nothing has no block record")
                for block in blocks[row["commit"]].values():
                    first = block.splitlines()[0]
                    self.assertNotIn(first, prompt, "expected no block first line %r; found it in %s" % (first, prompt_path))
            else:
                block = blocks[row["commit"]][row["arm"]]
                self.equal(prompt.count(block), 1, prompt_path, "exactly one byte-for-byte kept block")
                self.assertIsInstance(made, dict, "expected offered.made object; found %r; inspect %s" % (made, turns_path))
                self.equal(made["block_sha256"], hashlib.sha256(block).hexdigest(), turns_path, "real prompt block hash")
                self.equal(made["block_bytes"], len(block), turns_path, "real prompt block byte length")
            walk_path, walks = self.room(row, "walks")
            self.equal(len(walks), 1, walk_path, "one walk from real yak item walks")
            walk = walks[0]
            self.equal(walk["attempt"], row["attempt"], walk_path, "walk attempt matches arms")
            self.equal([s["seq"] for s in walk["steps"]], [0, 1, 2], walk_path, "zero-based real shell steps")
            self.equal([[p for p, _ in s["named"]] for s in walk["steps"]],
                [["README.md"], [self.START], [self.SOURCE]], walk_path, "real walk's named paths")
            for field, number, path in (("first_source_file", 1, self.START), ("first_reference_file", 2, self.SOURCE)):
                expected = {"step": number, "path": path, "second": walk["steps"][number]["seen_ms"] / 1000}
                self.equal(line[field], expected, self.out / "report.json", field + " from " + str(walk_path))
        return ran, listed

    def test_real_room_plan_through_report(self):
        self.whole_pass()
        self.succeeded = True

    def test_real_failed_history_turn_does_not_teach_or_stop(self):
        ran, listed = self.whole_pass(fail_title=self.TITLES[-1])
        failed = ran[-1]
        self.equal(failed["passed"], False, self.out / "history.json", "one deliberate history check failure")
        self.equal([r["passed"] for r in ran[:-1]], [True] * 4, self.out / "history.json", "four remaining passes teach")
        self.equal(listed["not_teaching"], [{"attempt": failed["attempt"], "item": failed["item"],
            "standing": "failed", "reason": "share:1 requires passed_verified"}], self.out / "list.json", "failed turn excluded from teaching")
        self.succeeded = True


if __name__ == "__main__":
    unittest.main()
