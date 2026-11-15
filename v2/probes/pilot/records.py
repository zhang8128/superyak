#!/usr/bin/env python3
"""What the pilot's turns leave behind: written down before a turn, checked after it, printed as tables.

    python3 -I records.py manifest <turn-dir> key=value ... -- <the words given to env -i>
    python3 -I records.py check <turn-dir>
    python3 -I records.py tables <pilot-dir> [--partial]

It is one file that imports nothing of its own, so that it runs with python3 -I.

manifest  writes <turn-dir>/manifest.json before the clock is started: what was planned (slot, kind, item,
          worker), what the item is (its base, its wrong commit, its check and the check file's blob), the
          room program and its SHA-256, the worker's program as the clock will find it and its version, the
          words of the clock's command and of the environment it is given, the limits in force (the
          program's own defaults, and each one the command sets), and the block's written-down versions.
          It refuses, and writes nothing, when a program is not found or does not say its version.
check     says whether a turn's directory holds one usable observation: one attempt, by the worker that
          was planned, whose program ran, with a verdict and a record whose parts add up to its active
          time. A turn that failed its check or ran to its limit is a usable observation. A turn that did
          not run, a clock that died and a record that is missing are not.
tables    checks every slot of <pilot-dir>/plan.txt that way, and both reports of the block check, and
          prints the tables only if all hold. With --partial it prints them anyway, under a list of what
          is missing or unusable, for looking at a pilot that is still running or that stopped.

The deciding outcome is a turn's active seconds: its sandbox, its worker, the room's commit for it, bringing
that in, and its check. They take in the check and how busy the machine was, so the worker's own seconds
are shown beside them, as a description.
"""
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys

USAGE = """python3 -I records.py manifest <turn-dir> key=value ... -- <the words given to env -i>
python3 -I records.py check <turn-dir>
python3 -I records.py tables <pilot-dir> [--partial]"""
RAN = ("exited", "signalled", "timed_out")
LIMITS = ("lease-secs", "turn-secs", "daily-turns", "concurrent")


class Refused(Exception):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as held:
        for piece in iter(lambda: held.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def said(command, environment, what):
    """The first line a command prints, which must end well and print something."""
    try:
        done = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f"{what} could not be asked: {error}") from error
    if done.returncode != 0:
        raise Refused(f"{what} ended with {done.returncode}")
    lines = done.stdout.strip().splitlines()
    if not lines or not lines[0].strip():
        raise Refused(f"{what} said nothing")
    return done.stdout


def limits_in_force(yak, argv, environment):
    """The room program's own defaults, read from its help, and over them what the command sets."""
    helped = said([yak, "clock", "run", "--help"], environment, "the room program's help")
    defaults = {}
    for name in LIMITS:
        found = re.search(rf"--{name} <[A-Z_]+>\s+\[default: (\d+)\]", helped)
        if not found:
            raise Refused(f"the room program's help names no default for --{name}")
        defaults[name] = int(found.group(1))
    in_force = dict(defaults)
    words = list(argv)
    for at, word in enumerate(words):
        for name in LIMITS:
            value = None
            if word == f"--{name}" and at + 1 < len(words):
                value = words[at + 1]
            elif word.startswith(f"--{name}="):
                value = word.split("=", 1)[1]
            if value is not None:
                if not value.isdigit():
                    raise Refused(f"--{name} is given {value!r}, which is not a number")
                in_force[name] = int(value)
    return {"defaults": defaults, "in_force": in_force, "own_prompts": "--own-prompts" in words}


def manifest(turn_dir, pairs, words):
    given = dict(pair.split("=", 1) for pair in pairs)
    for key in ("slug", "worker", "item", "base", "wrong", "check", "check_file", "check_blob"):
        if not given.get(key):
            raise Refused(f"the manifest is given no {key}")
    environment = {}
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        name, value = words.pop(0).split("=", 1)
        environment[name] = value
    if not words:
        raise Refused("the manifest is given no command")
    yak = words[0]
    # The room keeps only the absolute entries of the path it is given. A path with any other kind could
    # name one program here and another there, so it is refused.
    for entry in environment.get("PATH", "").split(":"):
        if not os.path.isabs(entry):
            raise Refused(f"the path the clock is given holds {entry!r}, which is not an absolute directory")
    family = given["worker"].split(":", 1)[0]
    if family in ("claude", "codex"):
        found = shutil.which(family, path=environment.get("PATH", ""))
        if not found:
            raise Refused(f"{family} is not on the path the clock is given")
        program = {"name": family, "path": os.path.realpath(found),
                   "version": said([found, "--version"], environment, f"{family}'s version").strip().splitlines()[0]}
    else:
        program = {"name": family, "path": given["worker"].split(":", 1)[-1], "version": None}
    block = os.path.join(os.path.dirname(os.path.abspath(turn_dir)), "versions.txt")
    record = {
        "slot": int(given["slot"]) if given.get("slot") else None,
        "kind": given.get("kind") or None,
        "slug": given["slug"],
        "worker": given["worker"],
        "item": given["item"],
        "base": given["base"],
        "wrong": given["wrong"],
        "check": given["check"],
        "check_file": given["check_file"],
        "check_blob": given["check_blob"],
        "yak": {"path": yak, "sha256": sha256(yak)},
        "program": program,
        "environment": environment,
        "argv": words,
        "limits": limits_in_force(yak, words, environment),
        "block": {"versions": block, "sha256": sha256(block)} if os.path.isfile(block) else None,
    }
    with open(os.path.join(turn_dir, "manifest.json"), "x", encoding="utf-8") as out:
        json.dump(record, out, indent=1, sort_keys=True)
        out.write("\n")


def load(path):
    with open(path, encoding="utf-8") as held:
        return json.load(held)


def observation(turn_dir, slug=None, worker=None):
    """What a turn's directory holds, and what is wrong with it: (manifest, turn, problems)."""
    problems = []
    plan, turn = None, None
    try:
        plan = load(os.path.join(turn_dir, "manifest.json"))
    except (OSError, ValueError) as error:
        problems.append(f"no manifest that can be read ({error.__class__.__name__})")
    if plan is not None:
        if slug is not None and plan.get("slug") != slug:
            problems.append(f"its manifest is for {plan.get('slug')}, and the plan says {slug}")
        if worker is not None and plan.get("worker") != worker:
            problems.append(f"its manifest names {plan.get('worker')}, and the plan says {worker}")
    try:
        code = open(os.path.join(turn_dir, "clock.exit"), encoding="utf-8").read().strip()
        if code not in ("0", "1"):
            problems.append(f"the clock ended with {code or 'nothing written'}")
    except OSError:
        problems.append("the clock's exit was not written: it did not end, or was ended")
    try:
        turns = load(os.path.join(turn_dir, "turns.json"))
    except (OSError, ValueError) as error:
        return plan, None, problems + [f"no record that can be read ({error.__class__.__name__})"]
    if not isinstance(turns, list) or len(turns) != 1:
        count = len(turns) if isinstance(turns, list) else "something other than"
        return plan, None, problems + [f"{count} attempts where one was planned"]
    turn = turns[0]
    planned = plan.get("worker") if plan else worker
    if planned is not None and turn.get("worker") != planned:
        problems.append(f"taken by {turn.get('worker')}, and {planned} was planned")
    measured = turn.get("measured")
    if measured is None:
        return plan, turn, problems + ["the turn has no measured record"]
    if measured.get("ended") not in RAN:
        problems.append(f"its worker's program did not run to an end of its own or its limit: {measured.get('ended')}")
    parts = [measured.get(name) for name in ("sandbox_ms", "worker_ms", "seal_ms", "bring_ms")]
    check = measured.get("check_ms")
    if not all(duration(part) for part in parts + [measured.get("active_ms")]) or not (check is None or duration(check)):
        problems.append("a duration of its record is missing, or is not a whole number of milliseconds from 0 up")
    else:
        if measured["active_ms"] != sum(parts) + (check or 0):
            problems.append("its record's parts do not add up to its active time")
        if measured["worker_ms"] <= 0 or measured["active_ms"] <= 0:
            problems.append("its record holds no time for its worker")
    if turn.get("passed") not in (True, False):
        problems.append("it has no verdict")
    return plan, turn, problems


def duration(value):
    """Whether a value is a whole number of milliseconds, from 0 up. True and False are not numbers here."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def slots(pilot):
    """The plan's turns: (slot, kind, slug, worker, own line). A slot is in the plan once."""
    planned = []
    with open(os.path.join(pilot, "plan.txt"), encoding="utf-8") as held:
        for line in held:
            words = line.split()
            if len(words) not in (4, 5) or not words[0].isdigit():
                raise Refused(f"a line of the plan cannot be read: {line.strip()!r}")
            if int(words[0]) in [slot for slot, *_ in planned]:
                raise Refused(f"turn {words[0]} is in the plan twice")
            planned.append((int(words[0]), words[1], words[2], words[3], len(words) == 5))
    return planned


def gathered(pilot):
    """Every slot of the plan with what it holds, and everything that is wrong with the pilot as a whole."""
    wrong, rows = [], []
    planned = slots(pilot)
    expected = {f"{slot}-{kind}-{slug}" for slot, kind, slug, _, _ in planned}
    numbered = {name for name in os.listdir(pilot)
                if name.split("-")[0].isdigit() and os.path.isdir(os.path.join(pilot, name))}
    for name in sorted(numbered - expected):
        wrong.append(f"{name}: a turn's directory that is not in the plan")
    for slot, kind, slug, worker, own in planned:
        name = f"{slot}-{kind}-{slug}"
        if name not in numbered:
            wrong.append(f"turn {slot} ({kind}, {slug}): not run")
            rows.append({"slot": slot, "kind": kind, "slug": slug, "worker": worker, "own": own, "turn": None,
                         "dir": None, "usable": False})
            continue
        turn_dir = os.path.join(pilot, name)
        plan, turn, problems = observation(turn_dir, slug, worker)
        if plan is not None and plan.get("limits", {}).get("own_prompts") != own:
            problems.append("its first line of its own is not as the plan says")
        for problem in problems:
            wrong.append(f"turn {slot} ({kind}, {slug}): {problem}")
        rows.append({"slot": slot, "kind": kind, "slug": slug, "worker": worker, "own": own, "turn": turn,
                     "dir": turn_dir, "usable": not problems})
    for report in ("block-before.txt", "block-after.txt"):
        try:
            lines = open(os.path.join(pilot, report), encoding="utf-8").read().split("\n")
            if [line for line in lines if line][-1:] != ["ok"]:
                wrong.append(f"{report}: the block check did not end with ok")
        except OSError:
            wrong.append(f"{report}: not written")
    return rows, wrong


def seconds(ms):
    return "" if ms is None else f"{ms / 1000:.1f}"


def cell(value):
    return "" if value is None else str(value)


def table(head, rows):
    print("| " + " | ".join(head) + " |")
    print("| " + " | ".join("---" for _ in head) + " |")
    for row in rows:
        print("| " + " | ".join(row) + " |")
    print()


def of_logs(values):
    """The geometric mean of some seconds, and the standard deviation of their logarithms (n - 1)."""
    logs = [math.log(value) for value in values]
    mean = sum(logs) / len(logs)
    spread = math.sqrt(sum((x - mean) ** 2 for x in logs) / (len(logs) - 1)) if len(logs) > 1 else None
    return math.exp(mean), spread


def read_first(path):
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def moment(path):
    """The time a turn's script wrote down, or nothing."""
    try:
        return datetime.datetime.strptime(read_first(path), "%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return None


def tables(pilot, partial):
    rows, wrong = gathered(pilot)
    if wrong:
        print("NOT WHOLE. Missing or unusable:" if partial else "REFUSED. Missing or unusable:")
        for line in wrong:
            print(f"- {line}")
        print()
        if not partial:
            return 1
    out = []
    last_ended = {}
    for row in rows:
        turn = row["turn"]
        head = [str(row["slot"]), row["kind"], row["slug"]]
        if turn is None or turn.get("measured") is None:
            out.append(head + [row["worker"], "no usable record"] + [""] * 15)
            continue
        if not row["usable"]:
            # What is wrong with it is listed above the table. Its numbers may not be numbers, and are not shown.
            out.append(head + [str(turn.get("worker")), "NOT USABLE"] + [""] * 15)
            continue
        m, k = turn["measured"], turn["measured"]["tokens"]
        # How long since this worker's last turn: what its program keeps of what it was sent grows cold with
        # time. The program itself was idle for longer than this by the time the room takes to start a turn.
        started = moment(os.path.join(row["dir"], "started.txt"))
        before = last_ended.get(turn["worker"])
        gap = "" if started is None or before is None else f"{(started - before).total_seconds():.0f}"
        last_ended[turn["worker"]] = moment(os.path.join(row["dir"], "ended.txt"))
        out.append(head + [
            turn["worker"], "",
            {True: "passed", False: "failed"}[turn["passed"]], m["ended"],
            read_first(os.path.join(row["dir"], "started.txt")).replace(" UTC", "")[-8:], gap,
            seconds(m["active_ms"]), seconds(m["worker_ms"]), seconds(m.get("check_ms")),
            cell(k["fresh_in"]), cell(k["cache_write"]), cell(k["cache_read"]), cell(k["output"]),
            "whole" if k["complete"] else "not whole",
            str(turn["steps"]), str(m["unknown_steps"]), str(len(turn["changes"])),
        ])
    table(["Turn", "Kind", "Item", "Worker", "Usable", "Verdict", "Ended", "Started (UTC)",
           "From this worker's last clock ending to this one starting, s", "Active s", "Worker s", "Check s", "Fresh in", "Written", "Read",
           "Output", "Tokens", "Steps", "Unnamed steps", "Files changed"], out)

    usable = [row for row in rows if row["usable"]]
    memory = [row for row in usable if row["kind"].startswith("memory-")]
    if memory:
        print("The memory test: the later turn of each pair less the earlier, in the order they were run.")
        print("One pair of each kind, for one worker: what was seen, not what a first line of its own does.\n")
        pairs = []
        for kind in ("memory-without", "memory-with"):
            pair = [row["turn"]["measured"] for row in memory if row["kind"] == kind]
            if len(pair) != 2:
                pairs.append([kind, "not both usable"] + [""] * 5)
                continue
            first, second = pair

            def less(key, first=first, second=second):
                a, b = first["tokens"][key], second["tokens"][key]
                return "" if a is None or b is None else f"{b - a:+d}"

            pairs.append([kind, less("fresh_in"), less("cache_write"), less("cache_read"), less("output"),
                          f"{(second['active_ms'] - first['active_ms']) / 1000:+.1f}",
                          f"{(second['worker_ms'] - first['worker_ms']) / 1000:+.1f}"])
        table(["Pair", "Fresh in", "Written", "Read", "Output", "Active s", "Worker s"], pairs)

    measured = [row for row in rows if row["kind"].startswith("round-")]
    if measured:
        print("The spread of active seconds over an item's turns: the standard deviation of their logarithms.")
        print("Every turn is in it, passed or not. The worker's own seconds are beside it as a description.\n")
        spread = []
        for slug in sorted({row["slug"] for row in measured}):
            planned = [row for row in measured if row["slug"] == slug]
            mine = [row for row in planned if row["usable"]]
            if not mine:
                spread.append([slug, planned[0]["worker"], f"0 of {len(planned)}"] + [""] * 5)
                continue
            active = [row["turn"]["measured"]["active_ms"] / 1000 for row in mine]
            worker = [row["turn"]["measured"]["worker_ms"] / 1000 for row in mine]
            mean, sd = of_logs(active)
            _, worker_sd = of_logs(worker)
            passed = sum(1 for row in mine if row["turn"]["passed"])
            spread.append([slug, mine[0]["turn"]["worker"], f"{len(mine)} of {len(planned)}", str(passed),
                           " ".join(f"{value:.0f}" for value in active), f"{mean:.0f}",
                           "" if sd is None else f"{sd:.3f}", "" if worker_sd is None else f"{worker_sd:.3f}"])
        table(["Item", "Worker", "Usable turns", "Passed", "Active s of each", "Geometric mean s", "SD of log",
               "SD of log, worker's seconds alone"], spread)
    return 0


def main(argv):
    try:
        if len(argv) >= 3 and argv[1] == "manifest" and "--" in argv:
            cut = argv.index("--")
            manifest(argv[2], argv[3:cut], argv[cut + 1:])
            return 0
        if len(argv) == 3 and argv[1] == "check":
            _, _, problems = observation(argv[2])
            for problem in problems:
                print(f"REFUSED: {problem}")
            if not problems:
                print("ok: one usable observation")
            return 1 if problems else 0
        if len(argv) in (3, 4) and argv[1] == "tables" and argv[3:] in ([], ["--partial"]):
            return tables(argv[2], argv[3:] == ["--partial"])
    except Refused as refusal:
        print(f"REFUSED: {refusal}")
        return 1
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
