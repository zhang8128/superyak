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


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("out")
    plan.add_argument("items")
    plan.add_argument("worker")
    plan.add_argument("--three", nargs="+", required=True)
    plan.add_argument("--history", nargs="+", required=True)
    plan.add_argument("--seed", type=int, required=True)
    plan.add_argument("--rounds", type=int, default=1)
    for name in ("screen", "history", "list"):
        stage = commands.add_parser(name)
        stage.add_argument("out")
    return root


def main(argv):
    try:
        args = parser().parse_args(argv)
        if args.command == "plan":
            return make_plan(args)
        if args.command == "screen":
            return screen(args.out)
        if args.command == "history":
            return run_history(args.out)
        return make_list(args.out)
    except (Refused, records.Refused, OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        print("REFUSED: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
