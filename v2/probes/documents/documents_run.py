#!/usr/bin/env python3
"""Run the next document pilot rows once each, serially. Python 3.9+, stdlib."""
import argparse
import contextlib
import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("documents_plan", HERE / "documents_plan.py")
maker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maker)
pilot = maker.pilot
Refused = maker.Refused
load_plan = maker.load_plan


@contextlib.contextmanager
def runner_lock(out):
    # The clock inherits this open file description. Closing the runner's copy
    # releases the lock only after the clock also exits; explicit LOCK_UN would
    # release both copies at once. A stale pathname cannot block resumption.
    with (Path(out) / "run.lock").open("a", encoding="ascii") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused("another runner holds run.lock") from None
        yield lock.fileno()


@contextlib.contextmanager
def planned_environment(plan):
    before = dict(os.environ)
    try:
        os.environ.update(plan["environment"])
        os.environ.update(YAK=plan["programs"]["yak"]["path"], YAK_PROBE_PATH=plan["environment"]["PATH"])
        yield
    finally:
        os.environ.clear()
        os.environ.update(before)


def outcome(turns, base):
    if not isinstance(turns, list) or len(turns) != 1 or not isinstance(turns[0], dict):
        return "clock-failed", None
    turn = turns[0]
    commit = turn.get("commit")
    measured = turn.get("measured") or {}
    ended = measured.get("ended") if isinstance(measured, dict) else None
    if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit):
        if commit == base:
            # The real room records the base's own commit for a turn that handed in nothing, whether it finished
            # or was stopped at its limit; only how it ended tells the two apart.
            return ("limit" if ended == "timed_out" else "no-hand-in"), None
        return "handed-in", commit
    if commit is not None:
        return "clock-failed", None
    if ended == "timed_out":
        return "limit", None
    if ended == "exited":
        return "no-hand-in", None
    return "clock-failed", None


def written_by(worker):
    """Who a row's item is said to be written by. The room never gives an item to a worker of the family that
    wrote it (the text before the first colon), so a script worker's item is written by another family."""
    return "claude:probe" if worker.split(":", 1)[0] == "script" else "script:probe"


def archive_interrupted(out, directory):
    if directory.exists():
        interrupted = Path(out) / "rows/interrupted"
        interrupted.mkdir(parents=True, exist_ok=True)
        k = 1
        saved = interrupted / (directory.name + "-%s" % k)
        while saved.exists():
            k += 1
            saved = interrupted / (directory.name + "-%s" % k)
        directory.rename(saved)
    archived = (Path(out) / "rows/interrupted").glob(directory.name + "-*")
    return [{"directory": str(saved.relative_to(out)), "started": (saved / "started.txt").exists(),
        "clock_exited": (saved / "clock.exit").exists()}
        for saved in sorted(archived, key=lambda p: int(p.name.rsplit("-", 1)[1])) if saved.is_dir()]


def export(yak, environment, room, identity, what, stdout, stderr):
    done = subprocess.run([yak, "--room", str(room), "item", what, identity, "--json"],
        env=environment, capture_output=True)
    stdout.write_bytes(done.stdout)
    stderr.write_bytes(done.stderr)
    return done.returncode


def controls_ready(out, item):
    if (Path(out) / "controls" / item["item"] / "stopped.json").exists():
        raise Refused("%s: controls stopped (stopped.json exists)" % item["item"])
    for name in ("cases.json", "parent.json"):
        path = Path(out) / "controls" / item["item"] / name
        try:
            held = json.loads(path.read_bytes())
        except (OSError, ValueError) as error:
            raise Refused("%s: control %s missing or unreadable: %s" % (item["item"], name, error)) from None
        if not isinstance(held, dict) or held.get("commit") != item["commit"]:
            raise Refused("%s: control %s has another or missing commit: %r" % (item["item"], name, held))
        if name == "cases.json" and (not isinstance(held.get("cases"), list) or not held["cases"]):
            raise Refused("%s: control cases.json has no non-empty cases list: %r" % (item["item"], held.get("cases")))


def run_turn(out, plan, row, item, lock_fd):
    out = Path(out)
    directory = out / row["directory"]
    with planned_environment(plan):
        yak = pilot.settings(plan["items_dir"], directory, out / "src")
    attempts = archive_interrupted(out, directory)
    directory.mkdir(parents=True)
    repo, room = directory / "repo", directory / "room"
    repo.mkdir()
    pilot.git(repo, "init", "-q", "--template=")
    base = item["rows"][row["row"]]
    ref = "refs/documents/%s/%s" % (item["item"], row["row"])
    for suffix, target, expected in (("", "base", base["base"]), ("-wrong", "wrong", base["wrong"])):
        pilot.git(repo, "fetch", "-q", "--no-tags", "--no-write-fetch-head", str(out / "src"),
            ref + suffix + ":refs/item-input/" + target)
        actual = pilot.git(repo, "rev-parse", "refs/item-input/" + target).decode().strip()
        if actual != expected:
            raise Refused("%s: fetched %s differs from plan: %s" % (row["directory"], target, actual))
    pilot.git(repo, "checkout", "-q", "-b", "item-base", base["base"])
    pilot.git(repo, "cat-file", "-e", base["base"] + "^{commit}")
    for name in [item["kept_out"]["reference"], item["commit"]] + item["kept_out"]["test_blobs"]:
        try:
            pilot.git(repo, "cat-file", "-e", name)
        except Refused:
            continue
        raise Refused("the turn's copy holds %s, which is kept from it" % name)
    environment = plan["environment"]
    pilot.command([yak, "--room", room, "init"], env=environment)
    identity = pilot.command([yak, "--room", room, "item", "add", "--title", maker.TITLE,
        "--repo", repo, "--base", base["base"], "--check", maker.CHECK_COMMAND, "--file", maker.CHECK_FILE,
        "--wrong", base["wrong"], "--origin", "observed", "--by", written_by(plan["worker"]["name"])],
        env=environment).decode().strip()
    (directory / "item.txt").write_text("%s %s %s\n" % (row["commit"], identity, plan["worker"]["name"]), encoding="utf-8")
    argv = [yak, "--room", str(room), "clock", "run", "--once-through", "--daily-turns", "1", "--concurrent", "1",
        "--turn-secs", str(plan["limits"]["worker_secs"]), "--lease-secs", str(plan["limits"]["lease_secs"]),
        "--worker", plan["worker"]["name"]]
    if not plan["worker"]["name"].startswith("script:"):
        argv.append("--own-prompts")
    began = pilot.now()
    load_before = pilot.command(["uptime"]).decode("utf-8", "replace")
    (directory / "load-before.txt").write_text(load_before, encoding="utf-8")
    code = -1
    with (directory / "clock.log").open("w", encoding="utf-8") as log:
        try:
            with subprocess.Popen(argv, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, pass_fds=(lock_fd,)) as clock:
                (directory / "started.txt").write_text(began + "\n", encoding="utf-8")
                for line in iter(clock.stdout.readline, b""):
                    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
                    log.write(stamp + " " + line.decode("utf-8", "replace").rstrip("\n") + "\n")
                    log.flush()
                code = clock.wait()
        except OSError as error:
            log.write(str(error) + "\n")
    ended = pilot.now()
    load_after = pilot.command(["uptime"]).decode("utf-8", "replace")
    (directory / "clock.exit").write_text(str(code) + "\n", encoding="ascii")
    (directory / "ended.txt").write_text(ended + "\n", encoding="utf-8")
    (directory / "load-after.txt").write_text(load_after, encoding="utf-8")
    turns_exit = export(yak, environment, room, identity, "turns", directory / "turns.json", directory / "turns.err")
    walks_exit = export(yak, environment, room, identity, "walks", directory / "walks.jsonl", directory / "walks.err")
    try:
        turns = json.loads((directory / "turns.json").read_bytes())
    except ValueError:
        turns = None
    kind, commit = outcome(turns, base["base"]) if turns_exit == 0 else ("export-failed", None)
    at_limit = (turns_exit == 0 and isinstance(turns, list) and len(turns) == 1 and isinstance(turns[0], dict)
        and isinstance(turns[0].get("measured"), dict) and turns[0]["measured"].get("ended") == "timed_out")
    record = {"n": row["n"], "commit": row["commit"], "row": row["row"], "began": began, "ended": ended,
        "load_before": load_before, "load_after": load_after, "clock_exit": code, "outcome": kind,
        "turn_commit": commit, "at_limit": at_limit, "turns_exit": turns_exit, "walks_exit": walks_exit,
        "earlier_attempts": len(attempts), "attempts": attempts,
        "interrupted_attempts": sum(a["started"] and not a["clock_exited"] for a in attempts)}
    pilot.write_json(directory / "record.tmp", record)
    os.replace(str(directory / "record.tmp"), str(directory / "record.json"))
    return record


def run_rows(out, rows=None):
    if rows is not None and (type(rows) is not int or rows < 0):
        raise Refused("--rows must be a nonnegative integer: %r" % rows)
    out = Path(out).resolve()
    with runner_lock(out) as lock_fd:
        plan = load_plan(out)
        items = {i["commit"]: i for i in plan["items"]}
        completed = 0
        for row in plan["order"]:
            if rows is not None and completed >= rows:
                break
            if (out / row["directory"] / "record.json").exists():
                continue
            load_plan(out)
            controls_ready(out, items[row["commit"]])
            run_turn(out, plan, row, items[row["commit"]], lock_fd)
            completed += 1
        return completed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["run"])
    parser.add_argument("out")
    parser.add_argument("--rows", type=int)
    try:
        args = parser.parse_args(argv)
        print("rows recorded: %s" % run_rows(args.out, args.rows))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as error:
        print("REFUSED: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
