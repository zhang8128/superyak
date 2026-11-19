#!/usr/bin/env python3
"""The judge of the pilot "a document offered". Python 3.9+, standard library, python -I.

  python3 -I documents_judge.py controls <out> --items <items dir>
  python3 -I documents_judge.py judge <out> --items <items dir> [--rows N]
  python3 -I documents_judge.py report <out>

controls: for each item, in the room's jail with a script in the worker's place, the reference's change on the item's
own base with the item's tests run to a JUnit report: cases.json (the frozen cases). Then the same change by replay,
for the room's verdict; then no change at all: parent.json. A reference with no passing case, or one whose room
verdict by replay is not a pass, stops the judge for that item (controls/<item>/stopped.json says why).

judge: for each recorded row not yet judged, score.json by the spec's section 6. report: the spec's section 7.

The score's denominator is always the count of frozen cases; nothing a turn's own run counts can move it. A turn's
code runs only inside the jail: this program applies no change and runs no test outside it.

Every room this program starts (a control's, a diagnostic's, a replay's) runs the plan's pinned room program with the
plan's environment and the plan's limits given to the clock explicitly, as the runner starts a row. A diagnostic or a
replay whose turn reaches its limit, whose clock fails, or which hands in nothing is kept as its own outcome with no
score, beside what was counted.

The JUnit report is read on the host from the diagnostic's commit: its blob must be a regular file of at most
MAX_REPORT bytes (its size is read before its contents), UTF-8, with no document type and no entity declaration, and it
is parsed as UTF-8 whatever it declares. That makes the parse safe; it does not make the report true. A turn's code
runs in the test runner's own process in the jail and can write the report, so a change can forge an all-pass report.
The room's verdict by replay, which runs the item's frozen check and none of the turn's code, stands beside every score
for that reason.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ITEMS = HERE.parent / "items"


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


maker = import_file("documents_plan", HERE / "documents_plan.py")
runner = import_file("documents_run", HERE / "documents_run.py")
pilot = maker.pilot
Refused = maker.Refused
load_plan = maker.load_plan

SOURCE = "peer/superyak_peer"
ROWS = ("nothing-1", "nothing-2", "exists", "path", "search", "newest", "lot")
NOTHING = ("nothing-1", "nothing-2")
OFFERING = ("exists", "path", "search", "newest", "lot")
OFFERED_BY = {"path": None, "search": "search", "newest": "newest", "lot": "lot"}
RULE_ROWS = ("nothing-1", "nothing-2", "search", "newest", "lot")
OUTCOMES = ("handed-in", "no-hand-in", "limit", "clock-failed")
MAX_OBSTACLES = 20
LINE_CHARS = 400
STATUS_ORDER = ("passed", "skipped", "failed", "error")
MAX_REPORT = 8 * 1024 * 1024        # bytes of a committed file the judge reads; its size is read first
DIAGNOSTIC_MARGIN_SECS = 120        # the diagnostic's turn: its tests' limit and this, to apply the change and commit
NO_REPORT = {"cases": {}, "collection_errors": []}


# ---------------------------------------------------------------- the plan

def items_by_short(plan):
    return {item["item"]: item for item in plan["items"]}


def row_name(order):
    """The last part of a row's directory. The maker stores `rows/<nnn>-<item>-<row>`, relative to the plan's
    directory, and the runner writes there; the judge reads the record there and judges in `judged/<the same name>`."""
    name = "%03d-%s-%s" % (order["n"], order["item"], order["row"])
    if order["directory"] != "rows/" + name:
        raise Refused("the plan's directory for row %r is %r, not rows/%s" % (order["n"], order["directory"], name))
    return name


def row_dir(out, order):
    return Path(out) / "rows" / row_name(order)


def judged_dir(out, order):
    return Path(out) / "judged" / row_name(order)


# ---------------------------------------------------------------- the JUnit report

def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:LINE_CHARS]
    return ""


def runner_words(element):
    """A collection error in the runner's words: its first line that begins "E ", else its message."""
    for line in (element.text or "").splitlines():
        if line.startswith("E "):
            return line[1:].strip()[:LINE_CHARS]
    return first_line(element.get("message")) or first_line(element.text)


def read_junit(data):
    """pytest's JUnit report -> {"cases": {id: (status, first line)}, "collection_errors": [str]}.

    A case's id is `classname::name`. A collection error is a testcase with an empty classname and an error (pytest
    names it by the module's dotted path). Where an id appears more than once its worst status stands."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Refused("the JUnit report is not UTF-8: %s" % error) from None
    if not text.strip():
        return {"cases": {}, "collection_errors": []}
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        # XML allows none of these; pytest escapes them. A NUL also lets the parser take UTF-16 or UTF-32 from the
        # report's first bytes whatever encoding it is told: UTF-16 with no byte-order mark is valid UTF-8.
        raise Refused("the JUnit report holds a control character XML does not allow")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.IGNORECASE):
        # The report is written inside the jail, where a turn's code runs; pytest writes no DOCTYPE.
        raise Refused("the JUnit report declares a DOCTYPE or an entity")
    try:
        # Parsed as UTF-8 whatever the report declares: no other encoding reaches the parser.
        parser = ElementTree.XMLParser(encoding="utf-8")
        parser.feed(data)
        root = parser.close()
    except ElementTree.ParseError as error:
        raise Refused("the JUnit report does not parse: %s" % error) from None
    cases, collection = {}, []
    for case in root.iter("testcase"):
        classname, name = case.get("classname") or "", case.get("name") or ""
        found = {child.tag: child for child in case}
        if not classname and "error" in found:
            collection.append("%s: %s" % (name, runner_words(found["error"])))
            continue
        if "error" in found:
            status, element = "error", found["error"]
        elif "failure" in found:
            status, element = "failed", found["failure"]
        elif "skipped" in found:
            status, element = "skipped", found["skipped"]
        else:
            status, element = "passed", None
        line = "" if element is None else (first_line(element.get("message")) or first_line(element.text))
        key = "%s::%s" % (classname, name)
        if key not in cases or STATUS_ORDER.index(status) > STATUS_ORDER.index(cases[key][0]):
            cases[key] = (status, line)
    return {"cases": cases, "collection_errors": collection}


def score_cases(frozen, report):
    """Counts over the frozen cases only. `of` is len(frozen) whatever the run collected."""
    frozen = sorted(set(frozen))
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "not_run": 0}
    obstacles = []
    for case in frozen:
        if case not in report["cases"]:
            counts["not_run"] += 1
            continue
        status, line = report["cases"][case]
        counts[status] += 1
        if status in ("failed", "error") and len(obstacles) < MAX_OBSTACLES:
            obstacles.append(line)
    held = set(frozen)
    counts.update(of=len(frozen), unfrozen=sum(1 for case in report["cases"] if case not in held),
        collection_errors=list(report["collection_errors"]), first_obstacles=obstacles)
    return counts


# ---------------------------------------------------------------- the walk

def first_named(steps, wanted):
    """Ported from pass_driver.first_named: by when a step was first seen, then its seq, then the name's place."""
    found = [((step.get("seen_ms") is None, step.get("seen_ms") or 0, step.get("seq", 0), place), step)
        for step in steps for place, named in enumerate(step.get("named") or [])
        if isinstance(named, (list, tuple)) and named and named[0] == wanted]
    if not found:
        return None
    (unseen, seen, seq, _), _ = min(found, key=lambda held: held[0])
    return {"step": seq, "seconds": None if unseen else seen / 1000}


def offered_paths(item, row):
    if row == "path":
        return [item["direct_path"]]
    if row in ("search", "newest", "lot"):
        return list(item[row]["three"])
    return []


def read_walk(path, item, row):
    """matching_named and offered_named from the row's walks.jsonl (one walk, or none)."""
    lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()] \
        if Path(path).exists() else []
    if len(lines) > 1:
        raise Refused("%s holds %d walks; one turn has one" % (path, len(lines)))
    steps = json.loads(lines[0]).get("steps") or [] if lines else []
    matching = {}
    for wanted in item["matching"]:
        found = first_named(steps, wanted)
        if found is not None:
            matching[wanted] = found
    offered = [wanted for wanted in offered_paths(item, row) if first_named(steps, wanted) is not None]
    return matching, offered


# ---------------------------------------------------------------- the jail

WORKER = """#!/bin/sh
# No model: lay the change beside this script on the item's own base, run the item's tests to a JUnit report, and
# hand in what they wrote as files. The judge reads them from this turn's repository, outside the room's store.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -s "$here/change.patch" ]; then
    git apply --index --binary "$here/change.patch" > jail-apply.txt 2>&1; echo $? > jail-apply-exit.txt
else
    : > jail-apply.txt; echo 0 > jail-apply-exit.txt
fi
python3 -I "$here/explain.py" > jail-explain.txt 2>&1
git add -f jail-apply.txt jail-apply-exit.txt jail-explain.txt jail-junit.xml jail-status.json
git -c user.name=stand-in -c user.email=stand-in@yak.invalid -c commit.gpgsign=false commit -q -m 'the change, and what the tests wrote in the jail'
"""

EXPLAIN = """import json, os, subprocess, sys, tempfile
LIMIT = %d
status = {"apply_exit": int(open("jail-apply-exit.txt").read().strip() or "1"), "tests_exit": None, "limit": False}
open("jail-junit.xml", "w").close()
if status["apply_exit"] == 0:
    item = json.load(open(".yak-check/item.json"))
    component = item["component"]
    tests = [t["path"][len(component) + 1:] for t in item["tests"]]
    home = tempfile.mkdtemp(prefix="yak-explain-")
    report = os.path.join(os.getcwd(), "jail-junit.xml")
    env = {"PATH": "/usr/bin:/bin", "HOME": home, "TMPDIR": home, "PYTHONPATH": os.path.join(os.getcwd(), component),
        "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "-rfE",
            "--junitxml=" + report, *tests], cwd=component, env=env, capture_output=True, text=True, timeout=LIMIT,
            start_new_session=True, stdin=subprocess.DEVNULL)
        status["tests_exit"] = done.returncode
        print(done.stdout[-9000:])
        print("--- stderr ---")
        print(done.stderr[-4000:])
    except subprocess.TimeoutExpired:
        status["limit"] = True
json.dump(status, open("jail-status.json", "w"), sort_keys=True)
"""


def jail_turn(directory, items, commit, worker_dir, plan, secs):
    """One turn of the room, its jail and a script worker, through the earlier probes' turn.sh, with the plan's
    pinned room program and environment (as the runner's planned_environment sets them) and the plan's limits given
    to the clock explicitly: `secs` for the turn, the plan's lease. The script worker's directory is added to what
    the jail may read. What turn.sh prints is kept beside the turn's directory."""
    environment = dict(plan["environment"])
    environment.update(YAK=plan["programs"]["yak"]["path"], YAK_PROBE_PATH=plan["environment"]["PATH"],
        YAK_JAIL_READ=plan["environment"]["YAK_JAIL_READ"] + os.pathsep + str(worker_dir))
    done = subprocess.run(["/bin/sh", str(ITEMS / "turn.sh"), str(directory), str(items), commit,
        "script:" + str(Path(worker_dir) / "worker.sh"), "--concurrent", "1", "--turn-secs", str(secs),
        "--lease-secs", str(plan["limits"]["lease_secs"])], env=environment, capture_output=True)
    Path(str(directory) + ".log").write_bytes(b"exit %d\n--- stdout ---\n%s\n--- stderr ---\n%s"
        % (done.returncode, done.stdout[-20000:], done.stderr[-20000:]))


def turn_outcome(directory):
    """How the run's one turn ended, read as the runner reads a row: (outcome, commit, verdict). The outcome is the
    runner's: handed-in, limit, no-hand-in or clock-failed; the verdict is the room's bool for a hand-in, else None."""
    directory = Path(directory)
    try:
        turns = json.loads((directory / "turns.json").read_bytes())
    except (OSError, ValueError):
        turns = None
    try:
        code = int((directory / "clock.exit").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        code = -1
    kind, commit = runner.outcome(turns, code)
    passed = turns[0].get("passed") if kind == "handed-in" else None
    return kind, commit, passed if type(passed) is bool else None


def committed(repo, commit, name):
    """A file the turn committed, or None where it committed none. Refused unless it is a regular file of at most
    MAX_REPORT bytes; the size is read before the contents are captured."""
    listed = pilot.git(repo, "ls-tree", "-z", commit, "--", name).split(b"\0")[0]
    if not listed:
        return None
    meta, _, path = listed.partition(b"\t")
    mode, kind, blob = meta.split()
    if path != name.encode("utf-8") or kind != b"blob" or mode not in (b"100644", b"100755"):
        raise Refused("%s in the turn's commit is not a regular file (mode %s)" % (name, mode.decode("ascii")))
    size = int(pilot.git(repo, "cat-file", "-s", blob.decode("ascii")))
    if size > MAX_REPORT:
        raise Refused("%s in the turn's commit holds %d bytes, over %d" % (name, size, MAX_REPORT))
    return pilot.git(repo, "cat-file", "blob", blob.decode("ascii"))


def diagnostic(directory, items, commit, patch, plan):
    """The change applied and the item's tests run in the jail: {"turn", "applied", "limit", "report"}. `turn` is
    how the room's turn ended, with "no-status" for a hand-in with no jail-status.json; only a turn that handed in
    its status has `applied` and a report. `limit` is true when the turn or its tests reached their limit."""
    limit = plan["limits"]["diagnostic_secs"]
    worker = Path(directory) / "stand-in"
    worker.mkdir(parents=True)
    (worker / "change.patch").write_bytes(patch)
    (worker / "worker.sh").write_text(WORKER, encoding="utf-8")
    (worker / "worker.sh").chmod(0o755)
    (worker / "explain.py").write_text(EXPLAIN % limit, encoding="utf-8")
    turn = Path(directory) / "turn"
    jail_turn(turn, items, commit, worker, plan, limit + DIAGNOSTIC_MARGIN_SECS)
    kind, turn_commit, _ = turn_outcome(turn)
    if kind != "handed-in":
        return {"turn": kind, "applied": None, "limit": kind == "limit", "report": NO_REPORT}
    status = committed(turn / "repo", turn_commit, "jail-status.json")
    if status is None:
        return {"turn": "no-status", "applied": None, "limit": False, "report": NO_REPORT}
    try:
        status = json.loads(status)
    except ValueError:
        raise Refused("%s: jail-status.json is not JSON" % directory) from None
    if not isinstance(status, dict):
        raise Refused("%s: jail-status.json is not an object" % directory)
    report = committed(turn / "repo", turn_commit, "jail-junit.xml") or b""
    return {"turn": kind, "applied": status.get("apply_exit") == 0, "limit": status.get("limit") is True,
        "report": read_junit(report)}


def replay(directory, items, commit, patch, plan):
    """The change by the earlier probes' stand-in, judged by the room with the item's frozen check, the turn limited
    to the plan's replay_secs: (how the turn ended, the room's verdict)."""
    worker = Path(directory) / "stand-in"
    worker.mkdir(parents=True)
    (worker / "reference.patch").write_bytes(patch)
    shutil.copyfile(ITEMS / "stand-in.sh", worker / "worker.sh")
    (worker / "worker.sh").chmod(0o755)
    jail_turn(Path(directory) / "turn", items, commit, worker, plan, plan["limits"]["replay_secs"])
    kind, _, verdict = turn_outcome(Path(directory) / "turn")
    return kind, verdict


def source_patch(repo, base, commit):
    return pilot.git(repo, "diff", "--binary", "--no-ext-diff", "--no-textconv", "--no-color", "--src-prefix=a/",
        "--dst-prefix=b/", base, commit, "--", SOURCE)


def items_dir(plan, items):
    """The item list's directory: as given, else the plan's own `items_dir` (the maker writes it)."""
    if items is None:
        if not isinstance(plan.get("items_dir"), str):
            raise Refused("no --items given and the plan has no items_dir")
        return plan["items_dir"]
    return items


def check_items(plan, items):
    _, raw = pilot.listed(items)
    if pilot.digest(raw) != plan["list_sha256"]:
        raise Refused("the item list's sha256 is %s; the plan holds %s" % (pilot.digest(raw), plan["list_sha256"]))
    return pilot.listed(items)[0]


# ---------------------------------------------------------------- controls

def move_aside(directory):
    aside = directory.parent / "interrupted"
    aside.mkdir(exist_ok=True)
    k = 1
    while (aside / ("%s-%d" % (directory.name, k))).exists():
        k += 1
    directory.rename(aside / ("%s-%d" % (directory.name, k)))


def controls(out, items):
    out = Path(out).resolve()
    plan = load_plan(out)
    items = items_dir(plan, items)
    listed = check_items(plan, items)
    (out / "controls").mkdir(exist_ok=True)
    for item in plan["items"]:
        directory = out / "controls" / item["item"]
        if (directory / "parent.json").exists() or (directory / "stopped.json").exists():
            continue
        if directory.exists():
            move_aside(directory)
        directory.mkdir()
        entry = pilot.item_from(listed, item["commit"])
        repo = Path(items).resolve() / "repo"
        patch = source_patch(repo, entry["base"], entry["reference"])
        ran = diagnostic(directory / "reference" / "diagnostic", items, item["commit"], patch, plan)
        passed = sorted(case for case, (status, _) in ran["report"]["cases"].items() if status == "passed")
        counts = {status: sum(1 for held, _ in ran["report"]["cases"].values() if held == status)
            for status in ("passed", "failed", "error", "skipped")}
        stop = None
        if ran["limit"]:
            stop = "the reference's diagnostic reached its limit"
        elif ran["turn"] != "handed-in":
            stop = "the reference's diagnostic turn ended %s" % ran["turn"]
        elif not ran["applied"]:
            stop = "the reference's diagnostic did not apply"
        elif not passed:
            stop = "no case passes on the reference (%s)" % json.dumps(counts, sort_keys=True)
        else:
            pilot.write_json(directory / "cases.json", {"commit": item["commit"], "cases": passed, "counts": counts})
            kind, verdict = replay(directory / "reference" / "replay", items, item["commit"], patch, plan)
            if kind in ("limit", "clock-failed"):
                stop = "the reference's replay turn ended %s" % kind
            elif verdict is not True:
                stop = "the room's verdict on the reference by replay is %s" % json.dumps(verdict)
        if stop is not None:
            pilot.write_json(directory / "stopped.json", {"commit": item["commit"], "reason": stop})
            print("%s: stopped: %s" % (item["item"], stop))
            continue
        parent = diagnostic(directory / "parent" / "diagnostic", items, item["commit"], b"", plan)
        if parent["limit"] or parent["turn"] != "handed-in":
            pilot.write_json(directory / "stopped.json", {"commit": item["commit"], "reason":
                "the parent's run reached its limit" if parent["limit"] else "the parent's turn ended %s" % parent["turn"]})
            continue
        frozen = set(passed)
        (directory / "parent" / "junit.json").write_text(json.dumps({"cases": {key: list(value) for key, value in
            parent["report"]["cases"].items()}, "collection_errors": parent["report"]["collection_errors"]},
            sort_keys=True), encoding="utf-8")
        pilot.write_json(directory / "parent.json", {"commit": item["commit"], "passed": sorted(case for case, (status, _)
            in parent["report"]["cases"].items() if status == "passed" and case in frozen)})
        print("%s: %d frozen cases, %d pass on the parent" % (item["item"], len(passed),
            len(pilot.load(directory / "parent.json")["passed"])))
    return 0


def parent_score(directory, frozen):
    held = json.loads((directory / "parent" / "junit.json").read_text(encoding="utf-8"))
    return score_cases(frozen, {"cases": {key: tuple(value) for key, value in held["cases"].items()},
        "collection_errors": held["collection_errors"]})


# ---------------------------------------------------------------- judge

def judge_row(out, items, plan, order, run_diagnostic=None, run_replay=None):
    """score.json's value for one recorded row (not written here). Every row's `of` is the count of frozen cases,
    scored or not; a row with no score keeps what was counted beside its named outcome."""
    run_diagnostic = run_diagnostic or diagnostic
    run_replay = run_replay or replay
    item = items_by_short(plan)[order["item"]]
    recorded = row_dir(out, order)
    judged = judged_dir(out, order)
    record = pilot.load(recorded / "record.json")
    if record.get("outcome") not in OUTCOMES:
        raise Refused("%s: record.json's outcome is %r" % (order["directory"], record.get("outcome")))
    if (record.get("n"), record.get("commit"), record.get("row")) != (order["n"], order["commit"], order["row"]):
        raise Refused("%s: record.json names row %r of %r, not the plan's" % (order["directory"], record.get("n"),
            record.get("commit")))
    commit = record.get("turn_commit")
    if record["outcome"] == "handed-in" and not commit:
        raise Refused("%s: handed in with no turn_commit" % order["directory"])
    if record["outcome"] == "no-hand-in" and commit:
        raise Refused("%s: no hand-in, yet turn_commit is %s" % (order["directory"], commit))
    controls_dir = out / "controls" / item["item"]
    frozen = pilot.load(controls_dir / "cases.json")["cases"]
    score = {"n": order["n"], "commit": order["commit"], "row": order["row"], "room_passed": None}
    matching, offered = read_walk(recorded / "walks.jsonl", item, order["row"])
    score.update(matching_named=matching, offered_named=offered)
    if record["outcome"] == "clock-failed":
        score.update(score_cases(frozen, NO_REPORT), outcome="clock-failed", scored=False)
        return score
    if not commit:
        score.update(parent_score(controls_dir, frozen), outcome=record["outcome"], scored=True)
        return score
    patch = source_patch(recorded / "repo", item["rows"][order["row"]]["base"], commit)
    if not patch.strip():
        score.update(parent_score(controls_dir, frozen), outcome="unchanged-source", scored=True)
        return score
    ran = run_diagnostic(judged / "diagnostic", items, order["commit"], patch, plan)
    counted = score_cases(frozen, ran["report"])
    if ran["limit"]:
        score.update(counted, outcome="diagnostic-limit", scored=False)
        return score
    if ran["turn"] != "handed-in":
        score.update(counted, outcome="diagnostic-" + ran["turn"], scored=False)
        return score
    if not ran["applied"]:
        score.update(counted, outcome="not-applied", scored=False)
        return score
    kind, verdict = run_replay(judged / "replay", items, order["commit"], patch, plan)
    if kind in ("limit", "clock-failed"):
        score.update(counted, outcome="replay-" + kind, scored=False)
        return score
    score.update(counted, outcome=record["outcome"], scored=True, room_passed=verdict)
    return score


def judge(out, items, rows=None):
    out = Path(out).resolve()
    plan = load_plan(out)
    items = items_dir(plan, items)
    check_items(plan, items)
    (out / "judged").mkdir(exist_ok=True)
    done = 0
    for order in plan["order"]:
        if rows is not None and done >= rows:
            break
        if not (row_dir(out, order) / "record.json").exists():
            continue
        judged = judged_dir(out, order)
        if (judged / "score.json").exists():
            continue
        controls_dir = out / "controls" / order["item"]
        if not (controls_dir / "parent.json").exists():
            print("%s: not judged: the item's controls %s" % (order["directory"],
                "stopped" if (controls_dir / "stopped.json").exists() else "are not made"))
            continue
        if judged.exists():
            move_aside(judged)
        judged.mkdir()
        score = judge_row(out, items, plan, order)
        pilot.write_json(judged / "score.json", score)
        done += 1
        print("%s: %s, %s" % (order["directory"], score["outcome"],
            "%d of %d" % (score["passed"], score["of"]) if score["scored"] else "no score"))
    return 0


# ---------------------------------------------------------------- report

def share(score):
    return Fraction(score["passed"], score["of"])


def classify(d, r):
    if d > r:
        return "higher"
    if d < -r:
        return "lower"
    return "within"


def usable(score):
    return score is not None and score.get("scored") is True and score.get("of", 0) > 0


def item_reading(scores):
    """One item's b, r and each offering row's d and class, from {row: score or None}. None where not read."""
    if not all(usable(scores.get(row)) for row in NOTHING):
        return None
    n1, n2 = share(scores["nothing-1"]), share(scores["nothing-2"])
    b, r = (n1 + n2) / 2, abs(n1 - n2)
    conditions = {}
    for row in OFFERING:
        if usable(scores.get(row)):
            d = share(scores[row]) - b
            conditions[row] = {"o": share(scores[row]), "d": d, "class": classify(d, r)}
    return {"n1": n1, "n2": n2, "b": b, "r": r, "conditions": conditions}


def tally(readings, row, keep=lambda item: True):
    counts = {"higher": 0, "lower": 0, "within": 0, "on": 0}
    for item, reading in readings.items():
        if keep(item) and reading is not None and row in reading["conditions"]:
            counts[reading["conditions"][row]["class"]] += 1
            counts["on"] += 1
    return counts


def by_plan(plan, readings):
    groups = {}
    for item in plan["items"]:
        groups.setdefault(item["plan_group"], []).append(item["item"])
    table = {}
    for group, members in sorted(groups.items()):
        table[group] = {"items": members, "conditions": {}}
        for row in OFFERING:
            read = [readings[member] for member in members if readings.get(member) is not None
                and row in readings[member]["conditions"]]
            if not read:
                continue
            D = sum((reading["conditions"][row]["d"] for reading in read), Fraction(0)) / len(read)
            R = sum((reading["r"] for reading in read), Fraction(0)) / len(read)
            table[group]["conditions"][row] = {"D": D, "R": R, "class": classify(D, R), "on": len(read)}
    figures = {}
    for row in OFFERING:
        held = [group["conditions"][row]["D"] for group in table.values() if row in group["conditions"]]
        figures[row] = sum(held, Fraction(0)) / len(table) if len(held) == len(table) and table else None
    return table, figures


def plan_summaries(plan, readings, keep=lambda item: True):
    """The by-plan table, its tally of plans, the equally weighted figure and what each figure stands on (plans and
    items), over the plan's items that `keep` keeps."""
    table, figures = by_plan({"items": [item for item in plan["items"] if keep(item)]}, readings)
    tallied = {row: {"higher": sum(1 for group in table.values() if group["conditions"].get(row, {}).get("class")
        == "higher"), "on": sum(1 for group in table.values() if row in group["conditions"])} for row in OFFERING}
    on = {row: {"plans": len(table) if figures[row] is not None else 0, "items": sum(group["conditions"][row]["on"]
        for group in table.values()) if figures[row] is not None else 0} for row in OFFERING}
    return {"plans": table, "plans_tally": tallied, "figures": figures, "figures_on": on}


def spending_rule(plan, scores, items_tally, plans_tally):
    missing = ["%s %s" % (item["item"], row) for item in plan["items"] for row in RULE_ROWS
        if not usable(scores.get(item["item"], {}).get(row))]
    if missing:
        return {"decision": "suspended", "missing": missing}
    worth = any(items_tally[row]["higher"] >= 8 and items_tally[row]["lower"] <= 2 and plans_tally[row]["higher"] >= 4
        for row in ("search", "newest")) and items_tally["lot"]["lower"] <= 3
    if worth:
        return {"decision": "worth designing an experiment", "missing": []}
    if all(items_tally[row]["higher"] <= 5 for row in ("search", "newest")):
        return {"decision": "not worth one", "missing": []}
    return {"decision": "between", "missing": []}


def number(value):
    return None if value is None else float(value)


def make_report(out):
    out = Path(out).resolve()
    plan = load_plan(out)
    scores, records, unjudged = {}, {}, []
    for order in plan["order"]:
        record_path = row_dir(out, order) / "record.json"
        score_path = judged_dir(out, order) / "score.json"
        if record_path.exists():
            records[order["directory"]] = pilot.load(record_path)
        if score_path.exists():
            score = pilot.load(score_path)
            if (score.get("n"), score.get("commit"), score.get("row")) != (order["n"], order["commit"], order["row"]):
                raise Refused("%s: score.json names another row" % order["directory"])
            scores.setdefault(order["item"], {})[order["row"]] = score
        elif record_path.exists():
            unjudged.append(order["directory"])
    readings = {item["item"]: item_reading(scores.get(item["item"], {})) for item in plan["items"]}
    probed = {item["item"] for item in plan["items"] if item["probed_before"]}
    items_tally = {row: tally(readings, row) for row in OFFERING}
    without = {row: tally(readings, row, lambda item: item not in probed) for row in OFFERING}
    every = plan_summaries(plan, readings)
    unprobed = plan_summaries(plan, readings, lambda item: not item["probed_before"])
    plans_tally = every["plans_tally"]
    rule = spending_rule(plan, scores, items_tally, plans_tally)
    interrupted = out / "rows" / "interrupted"
    outcomes, at_limit = {}, {row: 0 for row in ROWS}
    for directory, record in records.items():
        outcomes[record.get("outcome")] = outcomes.get(record.get("outcome"), 0) + 1
        if record.get("at_limit") is True:       # a record without the key is not at its limit
            at_limit[record.get("row")] = at_limit.get(record.get("row"), 0) + 1
    judged_outcomes = {}
    for item_scores in scores.values():
        for score in item_scores.values():
            judged_outcomes[score["outcome"]] = judged_outcomes.get(score["outcome"], 0) + 1
    stopped = {}
    for item in plan["items"]:
        held = out / "controls" / item["item"] / "stopped.json"
        if held.exists():
            stopped[item["item"]] = pilot.load(held)["reason"]
    report = {
        "v": 1,
        "rows": {"planned": len(plan["order"]), "recorded": len(records), "judged": sum(map(len, scores.values())),
            "unjudged": unjudged, "outcomes": outcomes, "judged_outcomes": judged_outcomes,
            "at_limit": at_limit,
            "interrupted": len([name for name in os.listdir(interrupted)]) if interrupted.is_dir() else 0},
        "controls_stopped": stopped,
        "items": {item["item"]: None if readings[item["item"]] is None else {
            "probed_before": item["probed_before"], "plan_group": item["plan_group"],
            "n1": number(readings[item["item"]]["n1"]), "n2": number(readings[item["item"]]["n2"]),
            "b": number(readings[item["item"]]["b"]), "r": number(readings[item["item"]]["r"]),
            "conditions": {row: {"o": number(held["o"]), "d": number(held["d"]), "class": held["class"]}
                for row, held in readings[item["item"]]["conditions"].items()}} for item in plan["items"]},
        "parent": {item["item"]: {"passed": len(pilot.load(out / "controls" / item["item"] / "parent.json")["passed"]),
            "of": len(pilot.load(out / "controls" / item["item"] / "cases.json")["cases"])}
            for item in plan["items"] if (out / "controls" / item["item"] / "parent.json").exists()},
        "tally": items_tally, "tally_without_probed": without, "probed": sorted(probed),
        "plan_of": {item["item"]: item["plan_group"] for item in plan["items"]},
        "rule": rule,
        "places": {item["item"]: {"search": item["search"]["best_place"], "search_tied": item["search"]["tied"],
            "newest": item["newest"]["best_place"]} for item in plan["items"]},
    }
    for suffix, held in (("", every), ("_without_probed", unprobed)):
        report["plans" + suffix] = {group: {"items": value["items"], "conditions": {row: {"D": number(cond["D"]),
            "R": number(cond["R"]), "class": cond["class"], "on": cond["on"]} for row, cond in value["conditions"].items()}}
            for group, value in held["plans"].items()}
        report["plans_tally" + suffix] = held["plans_tally"]
        report["figures" + suffix] = {row: number(value) for row, value in held["figures"].items()}
        report["figures_on" + suffix] = held["figures_on"]
    return report


def cell(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return "%.3f" % value
    return str(value)


def report_markdown(report):
    lines = ["# A document offered: the report", ""]
    rows = report["rows"]
    lines += ["Rows: %d planned, %d recorded, %d judged, %d recorded and not judged; %d interrupted and taken up again."
        % (rows["planned"], rows["recorded"], rows["judged"], len(rows["unjudged"]), rows["interrupted"]), "",
        "Recorded outcomes: %s. Judged outcomes: %s." % (
        ", ".join("%s %d" % pair for pair in sorted(rows["outcomes"].items())) or "none",
        ", ".join("%s %d" % pair for pair in sorted(rows["judged_outcomes"].items())) or "none"), "",
        "Rows the room ended at their limit, by condition: %s." % ", ".join("%s %d" % (row, rows["at_limit"][row])
        for row in ROWS), ""]
    for item, reason in sorted(report["controls_stopped"].items()):
        lines.append("Controls stopped at %s: %s" % (item, reason))
    lines += ["", "## Each item (shares of the frozen cases)", "",
        "| item | plan | parent | n1 | n2 | b | r | " + " | ".join("%s d (class)" % row for row in OFFERING) + " |",
        "| --- " * (7 + len(OFFERING)) + "|"]
    for item, held in report["items"].items():
        parent = report["parent"].get(item)
        if held is None:
            lines.append("| %s | %s | %s | no baseline |" % (item, report["plan_of"][item], "-" if parent is None
                else "%d of %d" % (parent["passed"], parent["of"])) + " |" * (3 + len(OFFERING)))
            continue
        mark = " (probed)" if held["probed_before"] else ""
        lines.append("| %s%s | %s | %s | %s | %s | %s | %s | %s |" % (item, mark, held["plan_group"],
            "-" if parent is None else "%d of %d" % (parent["passed"], parent["of"]), cell(held["n1"]),
            cell(held["n2"]), cell(held["b"]), cell(held["r"]), " | ".join(
            "%s (%s)" % (cell(held["conditions"][row]["d"]), held["conditions"][row]["class"])
            if row in held["conditions"] else "not read" for row in OFFERING)))
    lines += ["", "## Each condition over the items", "", "| condition | higher | lower | within | items it stands on |"
        " without the probed: higher | lower | within | on |", "| --- " * 9 + "|"]
    for row in OFFERING:
        a, w = report["tally"][row], report["tally_without_probed"][row]
        lines.append("| %s | %d | %d | %d | %d | %d | %d | %d | %d |" % (row, a["higher"], a["lower"], a["within"],
            a["on"], w["higher"], w["lower"], w["within"], w["on"]))
    for suffix, title in (("", "By plan"), ("_without_probed", "By plan, without the probed item")):
        lines += ["", "## " + title, "", "| plan | items | " + " | ".join("%s D, R (class)" % row for row in OFFERING)
            + " |", "| --- " * (2 + len(OFFERING)) + "|"]
        for group, held in report["plans" + suffix].items():
            lines.append("| %s | %s | %s |" % (group, ", ".join(held["items"]), " | ".join(
                "%s, %s (%s; on %d)" % (cell(held["conditions"][row]["D"]), cell(held["conditions"][row]["R"]),
                held["conditions"][row]["class"], held["conditions"][row]["on"]) if row in held["conditions"]
                else "not read" for row in OFFERING)))
        lines += ["", "Every plan weighing the same: " + "; ".join("%s %s (%d plans, %d items)" % (row,
            cell(report["figures" + suffix][row]), report["figures_on" + suffix][row]["plans"],
            report["figures_on" + suffix][row]["items"]) for row in OFFERING) + ". Plans higher: " + "; ".join(
            "%s %d of %d" % (row, report["plans_tally" + suffix][row]["higher"], report["plans_tally" + suffix][row]["on"])
            for row in OFFERING) + "."]
    lines += ["", "## The rule for where to spend next", ""]
    rule = report["rule"]
    lines.append("**%s**." % rule["decision"].capitalize() + ("" if not rule["missing"] else
        " The rule is not applied: these rows it needs have no score: %s." % ", ".join(rule["missing"])))
    lines += ["", "## Places counted before any turn", "", "| item | search: best place | tied | newest plans: best place |",
        "| --- | --- | --- | --- |"]
    for item, held in report["places"].items():
        lines.append("| %s | %s | %s | %s |" % (item, cell(held["search"]), cell(held["search_tied"]), cell(held["newest"])))
    return "\n".join(lines) + "\n"


def write_report(out):
    out = Path(out).resolve()
    report = make_report(out)
    for name, text in (("report.json", json.dumps(report, sort_keys=True, indent=1) + "\n"),
            ("report.md", report_markdown(report))):
        partial = out / (name + ".partial")
        partial.write_text(text, encoding="utf-8")
        os.replace(partial, out / name)
    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="documents_judge.py")
    sub = parser.add_subparsers(dest="stage", required=True)
    for name in ("controls", "judge", "report"):
        stage = sub.add_parser(name)
        stage.add_argument("out")
        if name != "report":
            stage.add_argument("--items")
        if name == "judge":
            stage.add_argument("--rows", type=int)
    args = parser.parse_args(argv)
    try:
        if args.stage == "controls":
            return controls(args.out, args.items)
        if args.stage == "judge":
            return judge(args.out, args.items, args.rows)
        print(report_markdown(write_report(args.out)))
        return 0
    except (Refused, OSError, ValueError, KeyError) as error:
        print("refused: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
