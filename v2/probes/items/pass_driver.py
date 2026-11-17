#!/usr/bin/env python3
"""The pass through the teaching list. Python 3.9+, standard library, python -I.

File contracts (all paths in generated JSON are absolute unless called directory):
plan.json: v, items_dir, items_sha256, lock_sha256, store_version, programs (name -> path,
sha256, optional version), store_files (path/sha256), inputs (path/sha256),
environment, worker (the exact word, including model), limits (defaults/in_force/
own_prompts), own_prompts, seed, rounds, three/history (commits in list order),
order (order/kind/commit/arm/round/directory; the thrown-away row also has
first_kept_of and its commit is resolved only after screening). Never rewritten.
screen.json: v, status (ready/stopped), reason, results (commit/kind/repetition/
directory/receipt), excluded (commit/reason), kept_history, instrument_failure.
teach-plan.json: items (room/item/attempt), bound to the history actually run.
room-plan.json: items (room/item), the strict projection the room CLI accepts.
list.json: v, status, reason, list_sha256 (the room's printed admission hash),
history_file_sha256, walks (file/sha256), teaching_count, not_teaching
(attempt/item/standing/reason), turns (room/item/attempt), teach_plan_sha256,
room_plan (path/sha256). Later room commands use room_plan.path as --plan.
history.json: v, status, reason, turns: only the turns actually run, with
order/kind/commit/directory/room/item/attempt/passed/clock_exit/driver_exit.
The discarded turn is recorded here but never in teach-plan.json. Interrupted
stages leave their directories and cannot be retried; use a new pass directory.
offers.json: v, status, reason, list_sha256, store_check (the store's own check, as printed),
goal_limit (true only when the room refused an offer file for more than 64 goals), items (in the
list's order: commit/title/base/directory/goals/answer_bytes/empty/refused, files (name ->
file/sha256/bytes for goals.json, question.json, answer.json, offer.json, block-route.txt,
block-shuffled.txt), and route/shuffled: sha256/bytes/places/roads/first_tracked_path/
first_source_file/gone/changed). Kept under offers/<commit>/; offers/store is the store's file.
arms.json: v, status, reason, left_out (commits whose offer is empty), turns: order/kind/commit/
arm/round/directory/room/began/ended/load_before/load_after (the pass's own, before and after
the turn), driver_exit, item, base, attempt, passed, clock_exit. arms-turns.jsonl holds each
finished turn as it ends.
report.json / report.md: section 5's tables, from the files above and the rooms' walks. They
may be made again; nothing else changes.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


pilot = import_file("pilot_driver", HERE / "pilot_driver.py")
records = import_file("pass_records", pilot.RECORDS)
Refused = pilot.Refused
ARMS = ("nothing", "route", "shuffled")
REFERENCE_RUNS = 6
MIN_HISTORY = 4
WALK_LINE_BYTES = 1048576
MAX_GOALS = 64
GOAL_LIMIT = "refused: goals.limit"
OFFERING = ("route", "shuffled")
SOURCE_DIR = "peer/superyak_peer"
MARKS = {"same": "", "changed": " (changed since)", "gone": " (gone)"}
KEPT = ("goals.json", "question.json", "answer.json", "offer.json", "block-route.txt", "block-shuffled.txt")
ERRORS = (Refused, OSError, ValueError, TypeError, KeyError, AttributeError)


def arm_order(seed, round_number, commit):
    """Section 4: lowercase hex SHA-256, no newline, ties by arm name."""
    return sorted(ARMS, key=lambda arm: (hashlib.sha256(
        ("%s:%s:%s:%s" % (seed, round_number, commit, arm)).encode("utf-8")).hexdigest(), arm))


def file_record(path):
    # Keep the path used to read/execute it: resolving a symlink here would
    # rehash its old target after the worker's PATH link had been retargeted.
    path = Path(path).absolute()
    return {"path": str(path), "sha256": records.sha256(path)}


def executable(path, name):
    if not path or not Path(path).is_file() or not os.access(path, os.X_OK):
        raise Refused("%s is not an executable file" % name)
    return file_record(path)


def jail_program():
    # turn/src/jail.rs::Jail::detect uses fixed locations, not PATH.
    paths = (("/usr/bin/sandbox-exec",) if sys.platform == "darwin" else
        ("/usr/bin/bwrap", "/bin/bwrap", "/usr/local/bin/bwrap") if sys.platform.startswith("linux") else ())
    return next((path for path in paths if Path(path).is_file()), None)


def clock_environment():
    environment = {key: os.environ.get(key, "") for key in ("HOME", "USER", "LOGNAME")}
    environment.update(SHELL=os.environ.get("SHELL", "/bin/sh"), LANG="en_US.UTF-8", TERM="dumb",
        PATH=os.environ.get("YAK_PROBE_PATH", ""), YAK_JAIL_READ=os.environ.get("YAK_JAIL_READ", ""))
    for key in ("SDKROOT", "TMPDIR"):
        if os.environ.get(key):
            environment[key] = os.environ[key]
    return environment


def turn_row(number, kind, commit, arm="nothing", round_number=None):
    return {"order": number, "kind": kind, "commit": commit, "arm": arm, "round": round_number,
        "directory": "turns/%03d-%s-%s" % (number, kind, commit or "first-kept")}


def make_plan(args):
    if os.path.lexists(args.out):
        raise Refused("%s exists" % args.out)
    if len(args.three) != 3:
        raise Refused("exactly three items under the arms are required")
    if len(args.history) < MIN_HISTORY:
        raise Refused("at least four history items are required")
    if len(set(args.three)) != len(args.three) or len(set(args.history)) != len(args.history):
        raise Refused("a commit is repeated")
    if set(args.three) & set(args.history):
        raise Refused("three and history overlap")
    if args.rounds < 1 or args.seed < 0:
        raise Refused("rounds must be positive and seed nonnegative")
    if not args.worker or any(c.isspace() for c in args.worker):
        raise Refused("worker must be one word")
    data, raw = pilot.listed(args.items)
    lock = data.get("lock_sha256")
    if not isinstance(lock, str) or not re.fullmatch("[0-9a-f]{64}", lock):
        raise Refused("items.json lacks its lock_sha256")
    for commit in args.three + args.history:
        entry = pilot.item_from(data, commit)
        if not re.fullmatch("[0-9a-f]{40}", commit):
            raise Refused("the arm order requires forty lowercase commit digits")
        pilot.source_checks(args.items, entry)
    three = [e["commit"] for e in data["commits"] if e.get("commit") in args.three]
    history = [e["commit"] for e in data["commits"] if e.get("commit") in args.history]
    yak = pilot.settings(args.items, args.out)
    environment = clock_environment()
    for path in environment["PATH"].split(os.pathsep):
        if not os.path.isabs(path):
            raise Refused("YAK_PROBE_PATH must contain absolute directories")
    programs = {"yak": executable(yak, "YAK"), "store": executable(os.environ.get("YAK_STORE"), "YAK_STORE")}
    store_files = os.environ.get("YAK_STORE_FILES", "")
    if not store_files or any(not path for path in store_files.split(os.pathsep)):
        raise Refused("YAK_STORE_FILES is required and must name files")
    store_files = [file_record(path) for path in store_files.split(os.pathsep)]
    family, separator, model = args.worker.partition(":")
    if not separator or family not in ("script", "claude", "codex") or not model:
        raise Refused("worker must name script, claude or codex and its path or model")
    if family == "script" and not os.path.isabs(model):
        raise Refused("script worker must have an absolute path")
    worker_path = model if family == "script" else shutil.which(family, path=environment["PATH"])
    programs["worker"] = executable(worker_path, "worker")
    programs["worker"]["version"] = (None if family == "script" else
        records.said([worker_path, "--version"], environment, "worker version").strip().splitlines()[0])
    for name, word in (("python3", "python3"), ("git", "git"), ("shell", "sh"),
            ("worker_shell", environment["SHELL"])):
        programs[name] = executable(shutil.which(word, path=environment["PATH"]), name)
    jail = jail_program()
    if jail:
        programs["jail"] = executable(jail, "jail")
    flags = ["--own-prompts", "--daily-turns", "1", "--concurrent", "1"]
    limits = records.limits_in_force(yak, flags, environment)
    rows = [turn_row(1, "thrown-away", None)]
    rows[0]["first_kept_of"] = history
    for commit in history:
        rows.append(turn_row(len(rows) + 1, "history", commit))
    for round_number in range(1, args.rounds + 1):
        for commit in three:
            for arm in arm_order(args.seed, round_number, commit):
                rows.append(turn_row(len(rows) + 1, "arms", commit, arm, round_number))
    inputs = [file_record(Path(args.items) / "list" / "items.json")]
    inputs += [file_record(path) for path in (Path(__file__), HERE / "pilot_driver.py", pilot.RECORDS,
        HERE / "turn.sh", HERE / "stand-in.sh")]
    plan = {"v": 1, "items_dir": str(Path(args.items).resolve()), "items_sha256": pilot.digest(raw),
        "lock_sha256": lock, "store_version": "3", "programs": programs, "store_files": store_files, "inputs": inputs,
        "environment": environment, "worker": args.worker, "limits": limits, "own_prompts": True,
        "seed": args.seed, "rounds": args.rounds, "three": three, "history": history, "order": rows}
    out = pilot.new_output(args.out)
    pilot.write_json(out / "plan.json", plan)
    print(json.dumps(plan, sort_keys=True, indent=1))
    return 0


def load_plan(out):
    """Public seam for later stages: load the immutable plan and rehash every input."""
    plan = pilot.load(Path(out) / "plan.json")
    lookups = {"python3": "python3", "git": "git", "shell": "sh", "worker_shell": plan["environment"]["SHELL"]}
    family = plan["worker"].split(":", 1)[0]
    if family != "script":
        lookups["worker"] = family
    for name, word in lookups.items():
        found = shutil.which(word, path=plan["environment"]["PATH"])
        if not found or str(Path(found).absolute()) != plan["programs"][name]["path"]:
            raise Refused("program lookup changed: " + name)
    for held in plan["inputs"] + list(plan["programs"].values()) + plan["store_files"]:
        try:
            actual = records.sha256(held["path"])
        except OSError:
            raise Refused("input changed or missing: " + held["path"]) from None
        if actual != held["sha256"]:
            raise Refused("input changed after plan: " + held["path"])
    return plan


@contextlib.contextmanager
def planned_environment(plan):
    previous = dict(os.environ)
    try:
        for key in ("SDKROOT", "TMPDIR"):
            os.environ.pop(key, None)
        os.environ.update(plan["environment"])
        os.environ.update(YAK=plan["programs"]["yak"]["path"], YAK_PROBE_PATH=plan["environment"]["PATH"])
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def new_stage(out, name):
    target = Path(out) / name
    if os.path.lexists(target) or (Path(out) / (name + ".json")).exists():
        raise Refused("%s already begun; begin again only in a new pass directory" % name)
    target.mkdir()
    return target


def screen(out):
    out = Path(out).resolve()
    plan = load_plan(out)
    root = new_stage(out, "screen")
    result = {"v": 1, "status": "stopped", "reason": None, "results": [], "excluded": [],
        "kept_history": [], "instrument_failure": False}
    excluded = {}
    try:
        with planned_environment(plan):
            for kind, commits, repeats in (("three", plan["three"], REFERENCE_RUNS), ("history", plan["history"], 1)):
                for commit in commits:
                    for repetition in range(1, repeats + 1):
                        load_plan(out)
                        if (out / "STOP").exists():
                            raise Refused("STOP before reference; the rehearsal is not run")
                        directory = root / ("%s-%s-%d" % (kind, commit, repetition))
                        try:
                            pilot.reference(directory, plan["items_dir"], commit)
                            receipt = pilot.load(directory / "reference.json")
                        except (Refused, OSError, ValueError) as error:
                            receipt = {"outcome": "no usable observation", "detail": str(error)}
                        result["results"].append({"commit": commit, "kind": kind, "repetition": repetition,
                            "directory": str(directory), "receipt": receipt})
                        outcome = receipt.get("outcome")
                        if outcome == "check failed":
                            excluded[commit] = "reference check failed"
                        elif outcome != "passed" or receipt.get("verified") is not True:
                            result["instrument_failure"] = True
                            excluded.clear()
                            raise Refused("instrument failed at %s: %s; begin again in a new pass directory" % (commit, outcome))
        load_plan(out)
        result["excluded"] = [{"commit": c, "reason": why} for c, why in excluded.items()]
        result["kept_history"] = [c for c in plan["history"] if c not in excluded]
        if any(c in excluded for c in plan["three"]):
            raise Refused("a three-item reference check failed; the rehearsal is not run")
        if len(result["kept_history"]) < MIN_HISTORY:
            raise Refused("fewer than four history items remain; the rehearsal is not run")
        result["status"] = "ready"
    except (Refused, OSError, ValueError) as error:
        result["reason"] = str(error)
        if result["instrument_failure"]:
            result["excluded"] = []
            result["kept_history"] = []
    pilot.write_json(out / "screen.json", result)
    print(result["reason"] or "screen ready")
    return 0 if result["status"] == "ready" else 1


def run_history(out):
    out = Path(out).resolve()
    plan = load_plan(out)
    screened = pilot.load(out / "screen.json")
    if screened.get("status") != "ready" or screened.get("instrument_failure"):
        raise Refused("screen does not let the pass go on")
    kept = screened["kept_history"]
    if len(kept) < MIN_HISTORY or kept != [c for c in plan["history"] if c in kept]:
        raise Refused("screen has no usable kept history")
    new_stage(out, "turns")
    result = {"v": 1, "status": "stopped", "reason": None, "turns": []}
    rows = [dict(plan["order"][0], commit=kept[0],
        directory="turns/001-thrown-away-" + kept[0])]
    rows += [row for row in plan["order"] if row["kind"] == "history" and row["commit"] in kept]
    try:
        with planned_environment(plan):
            for row in rows:
                load_plan(out)
                if (out / "STOP").exists():
                    raise Refused("STOP before turn %d" % row["order"])
                directory = out / row["directory"]
                flags = ["--own-prompts", "--arm", "nothing", "--order", str(row["order"]), "--seed", str(plan["seed"])]
                for name, value in plan["limits"]["in_force"].items():
                    flags += ["--" + name, str(value)]
                os.environ.update(YAK_PILOT_SLOT=str(row["order"]), YAK_PILOT_KIND=row["kind"])
                with (out / "history.log").open("a", encoding="utf-8") as log:
                    # pilot.turn checks the observation independently of clock.exit.
                    # Its return is not the verdict: failed checks remain usable.
                    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                        code = pilot.turn(directory, plan["items_dir"], row["commit"], plan["worker"], flags)
                held = dict(row, directory=str(directory), room=str(directory / "room"), driver_exit=code)
                result["turns"].append(held)
                attempts = pilot.load(directory / "turns.json")
                if not isinstance(attempts, list) or len(attempts) != 1:
                    raise Refused("turn %d has no verdict or not exactly one attempt" % row["order"])
                attempt = attempts[0]
                if not isinstance(attempt, dict) or type(attempt.get("passed")) is not bool:
                    raise Refused("turn %d has no verdict" % row["order"])
                if code:
                    raise Refused("turn %d has no usable observation" % row["order"])
                offered = attempt.get("offered") or {}
                if (offered.get("arm") != "nothing" or offered.get("order") != row["order"]
                        or offered.get("seed") != plan["seed"]):
                    raise Refused("turn %d has different arm, order or seed" % row["order"])
                manifest = pilot.load(directory / "manifest.json")
                if manifest.get("yak", {}).get("sha256") != plan["programs"]["yak"]["sha256"]:
                    raise Refused("turn %d names another yak" % row["order"])
                held.update(item=manifest["item"], attempt=attempt["attempt"], passed=attempt["passed"],
                    clock_exit=int((directory / "clock.exit").read_text().strip()))
                with (out / "history-turns.jsonl").open("a", encoding="utf-8") as journal:
                    journal.write(json.dumps(held, sort_keys=True) + "\n")
        load_plan(out)
        result["status"] = "complete"
    except (Refused, OSError, ValueError, TypeError, KeyError) as error:
        result["reason"] = str(error)
    pilot.write_json(out / "history.json", result)
    print(result["reason"] or "history complete")
    return 0 if result["status"] == "complete" else 1


def checked_teach_rooms(plan, teach):
    """Validate the supplied plan before make/check, including hand-edited plans."""
    bindings = []
    yak = plan["programs"]["yak"]["path"]
    for row in teach["items"]:
        room, item = row["room"], row["item"]
        items = json.loads(pilot.command([yak, "--room", room, "item", "list", "--json"]))
        if len(items) != 1 or items[0].get("id") != item:
            raise Refused("teaching room must hold exactly one item: " + room)
        attempts = json.loads(pilot.command([yak, "--room", room, "item", "turns", item, "--json"]))
        if not isinstance(attempts, list) or len(attempts) != 1:
            raise Refused("teaching room must hold exactly one attempt: " + room)
        attempt = attempts[0]
        if (attempt.get("offered") or {}).get("arm") != "nothing":
            raise Refused("teaching room's arm must be nothing: " + room)
        bindings.append({"room": room, "item": item, "attempt": attempt["attempt"]})
    return bindings


def check_walk_lines(path):
    """Count bytes including LF; bounded reads also handle a missing newline."""
    with Path(path).open("rb") as held:
        while True:
            line = held.readline(WALK_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > WALK_LINE_BYTES:
                raise Refused("walk line exceeds 1048576 bytes including newline: " + str(path))


def make_list(out):
    out = Path(out).resolve()
    plan = load_plan(out)
    history = pilot.load(out / "history.json")
    if history.get("status") != "complete":
        raise Refused("history did not complete")
    if (out / "history").exists() or (out / "list.json").exists():
        raise Refused("list already begun; begin again only in a new pass directory")
    ran = [row for row in history["turns"] if row["kind"] == "history"]
    expected = {"items": [{key: row[key] for key in ("room", "item", "attempt")} for row in ran]}
    teach_path = out / "teach-plan.json"
    if not teach_path.exists():
        pilot.write_json(teach_path, expected)
    teach = pilot.load(teach_path)
    bindings = checked_teach_rooms(plan, teach)
    if teach != expected or bindings != expected["items"]:
        raise Refused("teach plan differs from the history turns actually run")
    # The room's PlanItem denies unknown fields. Keep the required attempt in
    # our authoritative plan and give the CLI its exact, checked projection.
    room_plan = {"items": [{key: row[key] for key in ("room", "item")} for row in bindings]}
    room_plan_path = out / "room-plan.json"
    if room_plan_path.exists():
        if pilot.load(room_plan_path) != room_plan:
            raise Refused("room plan differs from the checked teaching plan")
    else:
        pilot.write_json(room_plan_path, room_plan)
    result = {"v": 1, "status": "stopped", "reason": None, "list_sha256": None,
        "history_file_sha256": None, "walks": [], "teaching_count": 0, "not_teaching": [],
        "turns": bindings, "teach_plan_sha256": records.sha256(teach_path), "room_plan": file_record(room_plan_path)}
    yak = plan["programs"]["yak"]["path"]
    walks = out / "history"
    try:
        load_plan(out)
        made = pilot.command([yak, "history", "make", "--plan", room_plan_path, "--measure", "share:1", "--out", walks]).decode().strip()
        listing = pilot.load(walks / "history.json")
        # Iterate the room's list, never directories, for walks and classifications.
        for row in listing["turns"]:
            path = walks / (row["attempt"] + ".jsonl")
            check_walk_lines(path)
            result["walks"].append({"file": str(path), "sha256": records.sha256(path)})
            walk = pilot.load(path)
            if walk.get("standing") == "passed_verified":
                result["teaching_count"] += 1
            else:
                result["not_teaching"].append({"attempt": row["attempt"], "item": row["item"],
                    "standing": walk.get("standing"), "reason": "share:1 requires passed_verified"})
        admitted = pilot.command([yak, "history", "check", "--plan", room_plan_path,
            "--list", walks / "history.json", "--walks", walks]).decode().strip()
        if not re.fullmatch("[0-9a-f]{64}", admitted) or admitted != made:
            raise Refused("history make and check disagree on the list hash")
        result["list_sha256"] = admitted
        result["history_file_sha256"] = records.sha256(walks / "history.json")
        if result["history_file_sha256"] != admitted:
            raise Refused("history check printed another list hash")
        if result["teaching_count"] < MIN_HISTORY:
            raise Refused("fewer than four turns teach")
        load_plan(out)
        result["status"] = "ready"
    except (Refused, OSError, ValueError, TypeError, KeyError) as error:
        result["reason"] = str(error)
    pilot.write_json(out / "list.json", result)
    print(result["reason"] or "list ready: " + result["list_sha256"])
    return 0 if result["status"] == "ready" else 1


def ready(out, name, before):
    path = Path(out) / name
    if not path.exists():
        raise Refused("%s is missing: run %s first" % (name, before))
    held = pilot.load(path)
    if not isinstance(held, dict) or held.get("status") != "ready":
        raise Refused("%s does not let the pass go on" % name)
    return held


def kept_file(path):
    data = Path(path).read_bytes()
    return {"file": str(path), "sha256": pilot.digest(data), "bytes": len(data)}


def unchanged(held, what):
    try:
        data = Path(held["file"]).read_bytes()
    except OSError:
        raise Refused("%s is missing: %s" % (what, held["file"])) from None
    if pilot.digest(data) != held["sha256"] or len(data) != held["bytes"]:
        raise Refused("%s changed after it was kept: %s" % (what, held["file"]))


def check_list(out, listed):
    """Step 4's list, walks and plans are hashed and never change afterwards."""
    held = [(Path(out) / "history" / "history.json", listed["list_sha256"]),
            (Path(out) / "teach-plan.json", listed["teach_plan_sha256"]),
            (Path(listed["room_plan"]["path"]), listed["room_plan"]["sha256"])]
    held += [(Path(row["file"]), row["sha256"]) for row in listed["walks"]]
    for path, wanted in held:
        try:
            actual = records.sha256(path)
        except OSError:
            raise Refused("the list's file is missing: %s" % path) from None
        if actual != wanted:
            raise Refused("the list's file changed after the list: %s" % path)


def offer_empty(offer):
    """offer.rs Offer::empty: no goal has a route (a goal's route is an object or null)."""
    return not any(goal["route"] is not None for goal in offer["goals"])


def offer_named(offer):
    """offer.rs Offer::named: each goal's path, then the `to` of each of its roads, in the file's order."""
    named = []
    for goal in offer["goals"]:
        named.append((goal["path"], goal["state"]))
        for road in (goal["route"] or {}).get("roads", []):
            named.append((road["to"], road["state"]))
    return named


def block_listing(offer, arm, text):
    """The paths a block lists, in its order: the route block in Offer::named's order, the shuffled
    block as its own lines say, each line read only as one exact path with its mark."""
    if offer_empty(offer):
        return []
    states = {}
    for path, state in offer_named(offer):
        states.setdefault(path, state)
    if arm == "route":
        listed = list(states)
        if any(path not in text for path in listed):
            raise Refused("the route block does not name every path of its offer")
    else:
        lines = {"- " + path + MARKS[state]: path for path, state in states.items()}
        listed = [lines[line] for line in text.split("\n") if line in lines]
        if sorted(listed) != sorted(states):
            raise Refused("the shuffled block does not list each path of its offer once")
    return [(path, states[path]) for path in listed]


def block_summary(offer, arm, text):
    listed = block_listing(offer, arm, text)
    roads = 0 if arm == "shuffled" else sum(len((goal["route"] or {}).get("roads", [])) for goal in offer["goals"])
    return {"places": len(listed), "roads": roads,
        "first_tracked_path": next((path for path, state in listed if state != "gone"), None),
        "first_source_file": next((path for path, _ in listed if path.startswith(SOURCE_DIR + "/")), None),
        "gone": sum(state == "gone" for _, state in listed), "changed": sum(state == "changed" for _, state in listed)}


def store_call(store, words, kept, stdin=None):
    done = subprocess.run([str(word) for word in [store, *words]], input=stdin, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    kept.write_bytes(done.stdout)
    if done.returncode:
        raise Refused("the store's %s failed: %s" % (words[0], done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout


def make_offers(out):
    out = Path(out).resolve()
    plan = load_plan(out)
    listed = ready(out, "list.json", "pass.sh list")
    check_list(out, listed)
    root = new_stage(out, "offers")
    result = {"v": 1, "status": "stopped", "reason": None, "list_sha256": listed["list_sha256"],
        "store_check": None, "goal_limit": False, "items": []}
    yak, store = plan["programs"]["yak"]["path"], plan["programs"]["store"]["path"]
    repo = Path(plan["items_dir"]) / "repo"
    history = out / "history" / "history.json"
    try:
        data = pilot.listed(plan["items_dir"])[0]
        with planned_environment(plan):
            store_file = root / "store"
            store_call(store, ["build", "--out", store_file, "--list", history] + [row["file"] for row in listed["walks"]],
                root / "build.out")
            result["store_check"] = store_call(store, ["check", "--store", store_file], root / "check.out").decode(
                "utf-8", "replace").strip()
            for commit in plan["three"]:
                load_plan(out)
                check_list(out, listed)
                entry = pilot.item_from(data, commit)
                here = root / commit
                here.mkdir()
                item = {"commit": commit, "title": entry["title"], "base": entry["base"], "directory": str(here),
                    "goals": None, "answer_bytes": None, "empty": None, "refused": None}
                result["items"].append(item)
                goals = pilot.command([yak, "offer", "goals", "--plan", listed["room_plan"]["path"], "--list", history,
                    "--title", entry["title"]])
                (here / "goals.json").write_bytes(goals)
                goals = json.loads(goals)
                item["goals"] = len(goals["goals"])
                # The prototype's bytes: canonical JSON of the room's question, ASCII, one newline.
                question = json.dumps(goals["question"], sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
                (here / "question.json").write_bytes(question.encode("ascii"))
                item["answer_bytes"] = len(store_call(store, ["ask", "--store", store_file], here / "answer.json",
                    stdin=question.encode("ascii")))
                made = subprocess.run([str(word) for word in (yak, "offer", "make", "--goals", here / "goals.json",
                    "--answer", here / "answer.json", "--repo", repo, "--base", entry["base"], "--out", here / "offer.json")],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if made.returncode:
                    said = made.stderr.decode("utf-8", "replace").strip()
                    item["refused"] = said
                    if GOAL_LIMIT in said:
                        result["goal_limit"] = True
                        raise Refused("more than %d goals at %s (%d): the room refused its offer file; nothing is cut"
                            % (MAX_GOALS, commit, item["goals"]))
                    raise Refused("the room refused the offer file at %s: %s" % (commit, said))
                offer = pilot.load(here / "offer.json")
                item["empty"] = offer_empty(offer)
                for arm in OFFERING:
                    text = pilot.command([yak, "offer", "render", "--arm", arm, "--offer", here / "offer.json",
                        "--seed", plan["seed"], "--repo", repo, "--base", entry["base"]])
                    (here / ("block-%s.txt" % arm)).write_bytes(text)
                    item[arm] = dict(block_summary(offer, arm, text.decode("utf-8")), sha256=pilot.digest(text),
                        bytes=len(text))
                item["files"] = {name: kept_file(here / name) for name in KEPT}
        if all(item["empty"] for item in result["items"]):
            raise Refused("every offer is empty: no turn runs under the arms")
        load_plan(out)
        check_list(out, listed)
        result["status"] = "ready"
    except ERRORS as error:
        result["reason"] = str(error)
    pilot.write_json(out / "offers.json", result)
    print(result["reason"] or "offers ready: %s" % ", ".join(
        "%s %s" % (item["commit"][:10], "empty" if item["empty"] else "offered") for item in result["items"]))
    return 0 if result["status"] == "ready" else 1


def check_offers(plan, offered):
    items = offered["items"]
    if [item["commit"] for item in items] != plan["three"]:
        raise Refused("offers.json does not hold the plan's three items in order")
    for item in items:
        if sorted(item["files"]) != sorted(KEPT):
            raise Refused("offers.json does not keep every file of %s" % item["commit"])
        for held in item["files"].values():
            unchanged(held, "a kept offer file")
    return {item["commit"]: item for item in items}


def load_now():
    return list(os.getloadavg())


def run_arms(out):
    out = Path(out).resolve()
    plan = load_plan(out)
    listed = ready(out, "list.json", "pass.sh list")
    offered = ready(out, "offers.json", "pass.sh offers")
    check_list(out, listed)
    kept = check_offers(plan, offered)
    new_stage(out, "arms")
    yak = plan["programs"]["yak"]["path"]
    left_out = [commit for commit in plan["three"] if kept[commit]["empty"]]
    result = {"v": 1, "status": "stopped", "reason": None, "left_out": left_out, "turns": []}
    rows = [row for row in plan["order"] if row["kind"] == "arms" and row["commit"] not in left_out]
    try:
        with planned_environment(plan):
            for row in rows:
                load_plan(out)
                check_list(out, listed)
                if (out / "STOP").exists():
                    raise Refused("STOP before turn %d" % row["order"])
                item = check_offers(plan, offered)[row["commit"]]
                directory = out / row["directory"]
                flags = ["--own-prompts", "--arm", row["arm"], "--order", str(row["order"]), "--seed", str(plan["seed"])]
                if row["arm"] in OFFERING:
                    flags += ["--offer", item["files"]["offer.json"]["file"]]
                for name, value in plan["limits"]["in_force"].items():
                    flags += ["--" + name, str(value)]
                os.environ.update(YAK_PILOT_SLOT=str(row["order"]), YAK_PILOT_KIND=row["kind"])
                held = dict(row, directory=str(directory), room=str(directory / "room"), began=pilot.now(),
                    load_before=load_now())
                result["turns"].append(held)
                with (out / "arms.log").open("a", encoding="utf-8") as log:
                    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                        code = pilot.turn(directory, plan["items_dir"], row["commit"], plan["worker"], flags)
                held.update(ended=pilot.now(), load_after=load_now(), driver_exit=code)
                identity = (directory / "item.txt").read_text(encoding="utf-8").split()[1]
                held.update(item=identity)
                attempts = pilot.load(directory / "turns.json")
                if not isinstance(attempts, list) or len(attempts) != 1:
                    raise Refused("turn %d has no verdict or not exactly one attempt" % row["order"])
                attempt = attempts[0]
                if not isinstance(attempt, dict) or type(attempt.get("passed")) is not bool:
                    raise Refused("turn %d has no verdict" % row["order"])
                if code:
                    raise Refused("turn %d has no usable observation" % row["order"])
                # Section 4 step 5: the room that ran the turn holds the item at the offer's base. The room
                # prints an item's base in one place only: the walk it exports for the item's turn.
                walks = [json.loads(line) for line in pilot.command([yak, "--room", directory / "room", "item", "walks",
                    identity, "--json"]).decode("utf-8").splitlines() if line.strip()]
                if len(walks) != 1 or walks[0].get("attempt") != attempt["attempt"]:
                    raise Refused("turn %d: the room exports no one walk of its attempt" % row["order"])
                held.update(base=walks[0].get("base"))
                if held["base"] != item["base"]:
                    raise Refused("turn %d: the item's room holds another base than its offer's" % row["order"])
                record = attempt.get("offered") or {}
                if (record.get("arm") != row["arm"] or record.get("order") != row["order"]
                        or record.get("seed") != plan["seed"]):
                    raise Refused("turn %d has different arm, order or seed" % row["order"])
                made = record.get("made")
                if row["arm"] not in OFFERING:
                    if made is not None:
                        raise Refused("turn %d under nothing holds a block" % row["order"])
                else:
                    block = item["files"]["block-%s.txt" % row["arm"]]
                    if (not isinstance(made, dict) or made.get("block_sha256") != block["sha256"]
                            or made.get("block_bytes") != block["bytes"]):
                        raise Refused("turn %d: the block's hash or length is not the one kept" % row["order"])
                manifest = pilot.load(directory / "manifest.json")
                if manifest.get("yak", {}).get("sha256") != plan["programs"]["yak"]["sha256"]:
                    raise Refused("turn %d names another yak" % row["order"])
                held.update(attempt=attempt["attempt"], passed=attempt["passed"],
                    clock_exit=int((directory / "clock.exit").read_text().strip()))
                with (out / "arms-turns.jsonl").open("a", encoding="utf-8") as journal:
                    journal.write(json.dumps(held, sort_keys=True) + "\n")
        load_plan(out)
        check_offers(plan, offered)
        result["status"] = "complete"
    except ERRORS as error:
        result["reason"] = str(error)
    pilot.write_json(out / "arms.json", result)
    print(result["reason"] or "arms complete: %d turns" % len(result["turns"]))
    return 0 if result["status"] == "complete" else 1


def first_named(steps, wanted):
    """By the time a step was first seen (seen_ms), then its place; a step's number counts from nought."""
    found = [(step.get("seen_ms") is None, step.get("seen_ms") or 0, number, path)
        for number, step in enumerate(steps) for path, _ in (step.get("named") or []) if wanted(path)]
    if not found:
        return None
    unseen, seen, number, path = min(found)
    return {"step": number, "second": None if unseen else seen / 1000, "path": path}


def turn_walk(yak, row):
    raw = pilot.command([yak, "--room", row["room"], "item", "walks", row["item"], "--json"])
    walks = [json.loads(line) for line in raw.decode("utf-8").split("\n") if line.strip()]
    found = [walk for walk in walks if walk.get("attempt") == row.get("attempt")]
    if len(found) != 1:
        raise Refused("the room has no one walk for turn %d" % row["order"])
    return found[0]


def seconds(value):
    return None if value is None else value / 1000


def turn_numbers(directory):
    attempts = pilot.load(Path(directory) / "turns.json")
    attempt = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 and isinstance(attempts[0], dict) else {}
    measured = attempt.get("measured") or {}
    tokens = measured.get("tokens") or {}
    return attempt, {"worker_seconds": seconds(measured.get("worker_ms")), "active_seconds": seconds(measured.get("active_ms")),
        "unknown_steps": measured.get("unknown_steps"), "tokens": {key: tokens.get(key) for key in
        ("fresh_in", "cache_write", "cache_read", "output")}, "tokens_whole": tokens.get("complete")}


def make_report(out):
    out = Path(out).resolve()
    plan = load_plan(out)
    if not (out / "arms.json").exists():
        raise Refused("arms.json is missing: run pass.sh arms first")
    arms = pilot.load(out / "arms.json")
    offered = pilot.load(out / "offers.json")
    listed = pilot.load(out / "list.json")
    history = pilot.load(out / "history.json")
    screened = pilot.load(out / "screen.json")
    yak = plan["programs"]["yak"]["path"]
    data = pilot.listed(plan["items_dir"])[0]
    repo = Path(plan["items_dir"]).resolve() / "repo"
    changes = {}
    for commit in plan["three"]:
        entry = pilot.item_from(data, commit)
        changes[commit] = [path for path in pilot.git(repo, "diff", "--name-only", "--no-renames", entry["base"],
            entry["reference"], "--", SOURCE_DIR).decode("utf-8").split("\n") if path]
    turns = []
    for row in arms["turns"]:
        line = {key: row.get(key) for key in ("order", "round", "commit", "arm", "passed", "began", "ended",
            "load_before", "load_after", "clock_exit")}
        if row.get("attempt") is None:
            line["note"] = "no verdict recorded: the pass stopped here"
            turns.append(line)
            continue
        attempt, numbers = turn_numbers(row["directory"])
        line.update(numbers)
        made = (attempt.get("offered") or {}).get("made")
        line["block"] = None if made is None else {key: made.get(key) for key in ("block_sha256", "block_bytes", "empty")}
        walk = turn_walk(yak, row)
        steps = walk.get("steps") or []
        line["steps"] = len(steps)
        wanted = set(changes[row["commit"]])
        line["first_reference_file"] = first_named(steps, lambda path: path in wanted)
        line["first_source_file"] = first_named(steps, lambda path: path.startswith(SOURCE_DIR + "/"))
        turns.append(line)
    blocks = [{"commit": item["commit"], "empty": item["empty"], "goals": item["goals"], "answer_bytes": item["answer_bytes"],
        "refused": item["refused"], **{arm: item.get(arm) for arm in OFFERING}} for item in offered["items"]]
    items = []
    for round_number in range(1, plan["rounds"] + 1):
        for commit in plan["three"]:
            three = {line["arm"]: line for line in turns if line["commit"] == commit and line["round"] == round_number}
            active = {arm: three[arm].get("active_seconds") if arm in three else None for arm in ARMS}
            whole = len(three) == len(ARMS) and all(three[arm].get("passed") is True and active[arm] for arm in ARMS)
            ratios = None
            if whole:
                ratios = {"route/nothing": active["route"] / active["nothing"],
                    "shuffled/nothing": active["shuffled"] / active["nothing"],
                    "route/shuffled": active["route"] / active["shuffled"]}
            items.append({"round": round_number, "commit": commit, "active_seconds": active, "ratios": ratios})
    history_rows = []
    for row in history["turns"]:
        if row["kind"] != "history":
            continue
        _, numbers = turn_numbers(row["directory"])
        history_rows.append({"commit": row["commit"], "passed": row.get("passed"),
            "worker_seconds": numbers["worker_seconds"], "active_seconds": numbers["active_seconds"]})
    report = {"v": 1, "conventions": CONVENTIONS, "arms_status": arms["status"], "arms_reason": arms["reason"],
        "offers_status": offered["status"], "offers_reason": offered["reason"], "list_sha256": offered["list_sha256"],
        "store_check": offered["store_check"], "left_out": arms["left_out"], "turns": turns, "blocks": blocks,
        "reference_changes": changes, "items": items, "items_with_ratios": sum(item["ratios"] is not None for item in items),
        "history": history_rows, "teaching_count": listed["teaching_count"],
        "screen": [dict({key: row.get(key) for key in ("commit", "kind", "repetition")}, outcome=row["receipt"].get("outcome"))
            for row in screened["results"]], "excluded": screened["excluded"]}
    with (out / "report.json").open("w", encoding="utf-8") as held:
        json.dump(report, held, sort_keys=True, indent=1)
        held.write("\n")
    (out / "report.md").write_text(report_markdown(report), encoding="utf-8")
    print("report written: %d turns" % len(turns))
    return 0


CONVENTIONS = ("Conventions: a step's number counts from nought; \"first names\" is by seen_ms; a source file is one "
    "under %s/; where a walk names none, the cell says so." % SOURCE_DIR)


def cell(value):
    if value is None:
        return "none named"
    if isinstance(value, dict) and "step" in value:
        return "%s, step %d, %s s" % (value["path"], value["step"], "-" if value["second"] is None else "%g" % value["second"])
    return str(value)


def report_markdown(report):
    lines = ["# The pass: what was recorded", "", report["conventions"], "",
        "Nothing here is tested for a difference, and no spread is worked from it.", "",
        "The list: %s. The store's own check: %s." % (report["list_sha256"], report["store_check"]), ""]
    lines += ["## Each turn", "", "| place | round | item | arm | passed | worker s | active s | steps | unknown steps | "
        "tokens | whole | began | ended | load before | load after | block sha256 | block bytes | empty | first reference file | "
        "first source file |", "|" + " --- |" * 20]
    for t in report["turns"]:
        block = t.get("block") or {}
        lines.append("| %s |" % " | ".join(str(x) for x in (t["order"], t["round"], t["commit"][:10], t["arm"], t["passed"],
            t.get("worker_seconds"), t.get("active_seconds"), t.get("steps"), t.get("unknown_steps"), t.get("tokens"),
            t.get("tokens_whole"), t["began"], t["ended"], t["load_before"], t["load_after"], block.get("block_sha256", "-"),
            block.get("block_bytes", "-"), block.get("empty", "-"),
            cell(t.get("first_reference_file")) if "note" not in t else t["note"],
            cell(t.get("first_source_file")) if "note" not in t else t["note"])))
    lines += ["", "## Each block", "", "| item | goals | answer bytes | empty | arm | places | roads | first tracked path | "
        "first source file | gone | changed | sha256 | bytes |", "|" + " --- |" * 13]
    for b in report["blocks"]:
        for arm in OFFERING:
            held = b.get(arm) or {}
            lines.append("| %s |" % " | ".join(str(x) for x in (b["commit"][:10], b["goals"], b["answer_bytes"], b["empty"], arm,
                held.get("places"), held.get("roads"), cell(held.get("first_tracked_path")),
                cell(held.get("first_source_file")), held.get("gone"), held.get("changed"), held.get("sha256"), held.get("bytes"))))
    lines += ["", "Left out under the arms, for an empty offer: %s" % (", ".join(report["left_out"]) or "none"), ""]
    lines += ["## Each item", "", "| round | item | nothing s | route s | shuffled s | route/nothing | shuffled/nothing | "
        "route/shuffled |", "|" + " --- |" * 8]
    for i in report["items"]:
        ratios = i["ratios"] or {}
        lines.append("| %s |" % " | ".join(str(x) for x in (i["round"], i["commit"][:10], *(i["active_seconds"][a] for a in ARMS),
            *(("%.3f" % ratios[k]) if ratios else "not all three passed" for k in ("route/nothing", "shuffled/nothing",
            "route/shuffled")))))
    lines += ["", "Items with ratios: %d" % report["items_with_ratios"], "",
        "## The history turns", "", "| item | passed | worker s | active s |", "| --- | --- | --- | --- |"]
    lines += ["| %s | %s | %s | %s |" % (h["commit"][:10], h["passed"], h["worker_seconds"], h["active_seconds"])
        for h in report["history"]]
    lines += ["", "Turns that teach: %d" % report["teaching_count"], "", "## The screen", "",
        "| item | kind | repetition | outcome |", "| --- | --- | --- | --- |"]
    lines += ["| %s | %s | %s | %s |" % (s["commit"][:10], s["kind"], s["repetition"], s["outcome"]) for s in report["screen"]]
    lines += ["", "Left out by the screen: %s" % (", ".join("%s (%s)" % (e["commit"][:10], e["reason"])
        for e in report["excluded"]) or "none"), ""]
    return "\n".join(lines)


STAGE_FILES = {"screen": "screen.json", "history": "history.json", "list": "list.json", "offers": "offers.json",
    "arms": "arms.json"}


def run_all(args):
    stages = [("plan", lambda: make_plan(args)), ("screen", lambda: screen(args.out)),
        ("history", lambda: run_history(args.out)), ("list", lambda: make_list(args.out)),
        ("offers", lambda: make_offers(args.out)), ("arms", lambda: run_arms(args.out)),
        ("report", lambda: make_report(args.out))]
    for name, stage in stages:
        try:
            code = stage()
        except (*ERRORS, records.Refused) as error:
            print("run stopped at %s: %s" % (name, error), file=sys.stderr)
            return 1
        if code:
            path = Path(args.out) / STAGE_FILES.get(name, "")
            reason = pilot.load(path).get("reason") if name in STAGE_FILES and path.is_file() else None
            print("run stopped at %s: %s" % (name, reason or "exit %d" % code), file=sys.stderr)
            return code
    print("run complete")
    return 0


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    # run takes plan's arguments, and only those.
    for name in ("plan", "run"):
        plan = commands.add_parser(name)
        plan.add_argument("out")
        plan.add_argument("items")
        plan.add_argument("worker")
        plan.add_argument("--three", nargs="+", required=True)
        plan.add_argument("--history", nargs="+", required=True)
        plan.add_argument("--seed", type=int, required=True)
        plan.add_argument("--rounds", type=int, default=1)
    for name in ("screen", "history", "list", "offers", "arms", "report"):
        stage = commands.add_parser(name)
        stage.add_argument("out")
    return root


def main(argv):
    # What the pass prints must reach the stream in the order it happened, also when the stream is a pipe:
    # the programs it runs write straight to the same stream, and the plan is printed before any of them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)
    try:
        args = parser().parse_args(argv)
        if args.command == "plan":
            return make_plan(args)
        if args.command == "screen":
            return screen(args.out)
        if args.command == "history":
            return run_history(args.out)
        if args.command == "offers":
            return make_offers(args.out)
        if args.command == "arms":
            return run_arms(args.out)
        if args.command == "report":
            return make_report(args.out)
        if args.command == "run":
            return run_all(args)
        return make_list(args.out)
    except (Refused, records.Refused, OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        print("REFUSED: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
