#!/usr/bin/env python3
"""The judge of the pilot "a document offered". Python 3.9+, standard library, python -I.

  python3 -I documents_judge.py controls <out> --items <items dir>
  python3 -I documents_judge.py judge <out> --items <items dir> [--rows N]
  python3 -I documents_judge.py report <out>

controls: for each item, in the room's jail with a script in the worker's place, the reference's change on the item's
own base with the item's tests run to a JUnit report: cases.json (the frozen cases). Then the same change by replay,
for the room's verdict; then no change at all: parent.json. A reference with no passing case, or one whose room
verdict by replay is not a pass, stops the judge for that item (controls/<item>/stopped.json says why).

judge: for each recorded row not yet judged, score.json by the spec's section 6. A row whose turns export failed, or
whose walks export did not exit 0, is exported again from its own room (never run again). A report the judge refuses
to read is the row's outcome report-refused, with no score; the other rows are judged. Every unscored outcome is one of
UNSCORED. report: the spec's section 7, on the share over all frozen cases (the rule's) and beside it on the share
over the new cases (those that fail on the parent). Every judge's own turn begins on the item list's base for the item,
and is read with the runner's outcome(turns, base): the clock's exit code decides nothing. The plan has eight rows; bm25
is an offering row outside the rule.

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
# bm25 is an offering row outside the rule: it was added after its places were seen and before any turn.
ROWS = ("nothing-1", "nothing-2", "exists", "path", "search", "newest", "lot", "bm25")
NOTHING = ("nothing-1", "nothing-2")
OFFERING = ("exists", "path", "search", "newest", "lot", "bm25")
THREES = ("search", "newest", "lot", "bm25")             # the rows that offer three files from the plan's item
RULE_ROWS = ("nothing-1", "nothing-2", "search", "newest", "lot")
OUTCOMES = ("handed-in", "no-hand-in", "limit", "clock-failed", "export-failed")
# Every outcome a judged row can have with no score, in one place; the report names each that occurred.
UNSCORED = ("clock-failed", "export-failed", "report-refused", "not-applied", "diagnostic-limit",
    "diagnostic-clock-failed", "diagnostic-no-hand-in", "diagnostic-no-status", "replay-limit", "replay-clock-failed")
BM25_SENTENCE = ("The bm25 row was added to the plan after its places were seen and before any turn; it is not a row "
    "of the rule.")
MAX_OBSTACLES = 20
LINE_CHARS = 400
STATUS_ORDER = ("passed", "skipped", "failed", "error")
MAX_REPORT = 8 * 1024 * 1024        # bytes of a committed file the judge reads; its size is read first
DIAGNOSTIC_MARGIN_SECS = 120        # the diagnostic's turn: its tests' limit and this, to apply the change and commit
NO_REPORT = {"cases": {}, "collection_errors": []}


class ReportRefused(Refused):
    """What a turn's commit holds for the judge (its JUnit report or its status) cannot be read safely. A turn's code
    can cause this, so for a row it is an outcome with no score, never a stop."""


# ---------------------------------------------------------------- the plan

def items_by_short(plan):
    return {item["item"]: item for item in plan["items"]}


def check_shape(plan):
    """One plan shape only: every item has every row in ROWS (bm25 included) and a bm25 member as search has, and
    the order holds each item's every row once. A plan of seven rows is refused."""
    for item in plan["items"]:
        if sorted(item["rows"]) != sorted(ROWS):
            raise Refused("%s: the plan's rows are %s, not %s" % (item["item"], sorted(item["rows"]), sorted(ROWS)))
        bm25 = item.get("bm25")
        if not isinstance(bm25, dict) or not isinstance(bm25.get("three"), list) or len(bm25["three"]) != 3 \
                or type(bm25.get("best_place")) is not int or type(bm25.get("tied")) is not int:
            raise Refused("%s: the plan has no bm25 member with three, best_place and tied" % item["item"])
    wanted = sorted((item["commit"], row) for item in plan["items"] for row in ROWS)
    if sorted((order["commit"], order["row"]) for order in plan["order"]) != wanted:
        raise Refused("the plan's order is not each item's %d rows once" % len(ROWS))
    return plan


def load_judged_plan(out):
    return check_shape(load_plan(out))


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
        raise ReportRefused("the JUnit report is not UTF-8: %s" % error) from None
    if not text.strip():
        return {"cases": {}, "collection_errors": []}
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        # XML allows none of these; pytest escapes them. A NUL also lets the parser take UTF-16 or UTF-32 from the
        # report's first bytes whatever encoding it is told: UTF-16 with no byte-order mark is valid UTF-8.
        raise ReportRefused("the JUnit report holds a control character XML does not allow")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.IGNORECASE):
        # The report is written inside the jail, where a turn's code runs; pytest writes no DOCTYPE.
        raise ReportRefused("the JUnit report declares a DOCTYPE or an entity")
    try:
        # Parsed as UTF-8 whatever the report declares: no other encoding reaches the parser.
        parser = ElementTree.XMLParser(encoding="utf-8")
        parser.feed(data)
        root = parser.close()
    except ElementTree.ParseError as error:
        raise ReportRefused("the JUnit report does not parse: %s" % error) from None
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


def score_cases(frozen, report, new):
    """Counts over the frozen cases only. `of` is len(frozen) whatever the run collected; `of_new` is how many of them
    are `new` (do not pass on the parent) and `passed_new` how many of those pass here."""
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
    if not set(new) <= held:
        raise Refused("a new case is not a frozen case")
    counts.update(of=len(frozen), unfrozen=sum(1 for case in report["cases"] if case not in held),
        of_new=len(set(new)), passed_new=sum(1 for case in set(new) if report["cases"].get(case, ("",))[0] == "passed"),
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
    if row in THREES:
        return list(item[row]["three"])
    return []


def read_walk(path, item, row):
    """matching_named and offered_named from the row's walks.jsonl (one walk, or none). The bm25 row's offered files
    are read as the search row's are: its plan member's three."""
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


def turn_base(listed, commit):
    """The commit a judge's own turn begins on: the item list's base for the item's commit, the one turn.sh gives the
    room (pilot_driver's turn: item_from(listed(items)), then `--base entry["base"]`)."""
    return pilot.item_from(listed, commit)["base"]


def turn_outcome(directory, base):
    """How the run's one turn ended, read as the runner reads a row: (outcome, commit, verdict). The outcome is the
    runner's outcome(turns, base), `base` the commit the turn began on: a turn whose commit is its base handed in
    nothing. The clock's exit code decides nothing (the room exits 1 on a finished turn); turn.sh's clock.exit stays
    in the turn's directory for a reader. The verdict is the room's bool for a hand-in, else None."""
    directory = Path(directory)
    try:
        turns = json.loads((directory / "turns.json").read_bytes())
    except (OSError, ValueError):
        turns = None
    kind, commit = runner.outcome(turns, base)
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
        raise ReportRefused("%s in the turn's commit is not a regular file (mode %s)" % (name, mode.decode("ascii")))
    size = int(pilot.git(repo, "cat-file", "-s", blob.decode("ascii")))
    if size > MAX_REPORT:
        raise ReportRefused("%s in the turn's commit holds %d bytes, over %d" % (name, size, MAX_REPORT))
    return pilot.git(repo, "cat-file", "blob", blob.decode("ascii"))


def diagnostic(directory, items, commit, patch, plan, base):
    """The change applied and the item's tests run in the jail: {"turn", "applied", "limit", "report"}. `turn` is
    how the room's turn ended, with "no-status" for a hand-in with no jail-status.json; only a turn that handed in
    its status has `applied` and a report. `limit` is true when the turn or its tests reached their limit. `base` is
    the commit the turn begins on (turn_base). A report or status the judge will not read raises ReportRefused."""
    limit = plan["limits"]["diagnostic_secs"]
    worker = Path(directory) / "stand-in"
    worker.mkdir(parents=True)
    (worker / "change.patch").write_bytes(patch)
    (worker / "worker.sh").write_text(WORKER, encoding="utf-8")
    (worker / "worker.sh").chmod(0o755)
    (worker / "explain.py").write_text(EXPLAIN % limit, encoding="utf-8")
    turn = Path(directory) / "turn"
    jail_turn(turn, items, commit, worker, plan, limit + DIAGNOSTIC_MARGIN_SECS)
    kind, turn_commit, _ = turn_outcome(turn, base)
    if kind != "handed-in":
        return {"turn": kind, "applied": None, "limit": kind == "limit", "report": NO_REPORT}
    status = committed(turn / "repo", turn_commit, "jail-status.json")
    if status is None:
        return {"turn": "no-status", "applied": None, "limit": False, "report": NO_REPORT}
    try:
        status = json.loads(status)
    except ValueError:
        raise ReportRefused("jail-status.json is not JSON") from None
    if not isinstance(status, dict):
        raise ReportRefused("jail-status.json is not an object")
    report = committed(turn / "repo", turn_commit, "jail-junit.xml") or b""
    return {"turn": kind, "applied": status.get("apply_exit") == 0, "limit": status.get("limit") is True,
        "report": read_junit(report)}


def replay(directory, items, commit, patch, plan, base):
    """The change by the earlier probes' stand-in, judged by the room with the item's frozen check, the turn limited
    to the plan's replay_secs: (how the turn ended, the room's verdict)."""
    worker = Path(directory) / "stand-in"
    worker.mkdir(parents=True)
    (worker / "reference.patch").write_bytes(patch)
    shutil.copyfile(ITEMS / "stand-in.sh", worker / "worker.sh")
    (worker / "worker.sh").chmod(0o755)
    jail_turn(Path(directory) / "turn", items, commit, worker, plan, plan["limits"]["replay_secs"])
    kind, _, verdict = turn_outcome(Path(directory) / "turn", base)
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
    plan = load_judged_plan(out)
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
        ran = diagnostic(directory / "reference" / "diagnostic", items, item["commit"], patch, plan, entry["base"])
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
            kind, verdict = replay(directory / "reference" / "replay", items, item["commit"], patch, plan, entry["base"])
            if kind in ("limit", "clock-failed"):
                stop = "the reference's replay turn ended %s" % kind
            elif verdict is not True:
                stop = "the room's verdict on the reference by replay is %s" % json.dumps(verdict)
        if stop is not None:
            pilot.write_json(directory / "stopped.json", {"commit": item["commit"], "reason": stop})
            print("%s: stopped: %s" % (item["item"], stop))
            continue
        parent = diagnostic(directory / "parent" / "diagnostic", items, item["commit"], b"", plan, entry["base"])
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


def parent_score(directory, frozen, new):
    held = json.loads((directory / "parent" / "junit.json").read_text(encoding="utf-8"))
    return score_cases(frozen, {"cases": {key: tuple(value) for key, value in held["cases"].items()},
        "collection_errors": held["collection_errors"]}, new)


def new_cases(directory, frozen):
    """The frozen cases that do not pass on the parent (parent.json's `passed`): the cases a change must make pass."""
    return sorted(set(frozen) - set(pilot.load(directory / "parent.json")["passed"]))


# ---------------------------------------------------------------- judge

def read_turns(path, base):
    """(outcome, turn_commit, at_limit) from an `item turns --json` export, decided as the runner's run_turn decides
    them from its own export: runner.outcome(turns, base), and at_limit when the one turn ended timed_out."""
    try:
        turns = json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        turns = None
    kind, commit = runner.outcome(turns, base)
    at_limit = (isinstance(turns, list) and len(turns) == 1 and isinstance(turns[0], dict)
        and isinstance(turns[0].get("measured"), dict) and turns[0]["measured"].get("ended") == "timed_out")
    return kind, commit, at_limit


def export_again(out, plan, order, judged, what):
    """The room's own export (`item turns` or `item walks`, with --json) run again from the row's room/, with the
    plan's pinned program and environment, as the runner's export ran it; written under the judged row. The item's id
    is the second word of the row's item.txt. Returns the export's exit code."""
    recorded = row_dir(out, order)
    words = (recorded / "item.txt").read_text(encoding="utf-8").split()
    if len(words) < 2 or words[0] != order["commit"]:
        raise Refused("%s: item.txt does not name the row's commit and the room's item" % order["directory"])
    name = {"turns": "turns.json", "walks": "walks.jsonl"}[what]
    return runner.export(plan["programs"]["yak"]["path"], dict(plan["environment"]), recorded / "room", words[1],
        what, Path(judged) / name, Path(judged) / (what + ".err"))


def judge_row(out, items, plan, order, run_diagnostic=None, run_replay=None, listed=None, run_export=None):
    """score.json's value for one recorded row (not written here). Every row's `of` is the count of frozen cases and
    its `of_new` the count of those that do not pass on the parent, scored or not; a row with no score keeps what was
    counted beside its named outcome, which is one of UNSCORED. A row whose turns export failed, or whose walks export
    did not exit 0, is exported again from its room (never run again). `listed` is the item list: a diagnostic's and
    a replay's turn begin on its base for the item (turn_base)."""
    run_diagnostic = run_diagnostic or diagnostic
    run_replay = run_replay or replay
    run_export = run_export or export_again
    item = items_by_short(plan)[order["item"]]
    recorded = row_dir(out, order)
    judged = judged_dir(out, order)
    record = pilot.load(recorded / "record.json")
    if record.get("outcome") not in OUTCOMES:
        raise Refused("%s: record.json's outcome is %r" % (order["directory"], record.get("outcome")))
    if (record.get("n"), record.get("commit"), record.get("row")) != (order["n"], order["commit"], order["row"]):
        raise Refused("%s: record.json names row %r of %r, not the plan's" % (order["directory"], record.get("n"),
            record.get("commit")))
    for key in ("turns_exit", "walks_exit"):
        if type(record.get(key)) is not int:
            raise Refused("%s: record.json's %s is %r" % (order["directory"], key, record.get(key)))
    if (record["outcome"] == "export-failed") != (record["turns_exit"] != 0):
        raise Refused("%s: record.json's outcome %s with turns_exit %d" % (order["directory"], record["outcome"],
            record["turns_exit"]))
    kind, commit, at_limit = record["outcome"], record.get("turn_commit"), record.get("at_limit") is True
    if kind == "handed-in" and not commit:
        raise Refused("%s: handed in with no turn_commit" % order["directory"])
    if kind != "handed-in" and commit:
        raise Refused("%s: %s, yet turn_commit is %s" % (order["directory"], kind, commit))
    again, walks = {}, recorded / "walks.jsonl"
    if kind == "export-failed":
        again["turns"] = run_export(out, plan, order, judged, "turns")
        if again["turns"] == 0:
            kind, commit, at_limit = read_turns(judged / "turns.json", item["rows"][order["row"]]["base"])
    if record["walks_exit"] != 0:
        again["walks"] = run_export(out, plan, order, judged, "walks")
        walks = judged / "walks.jsonl" if again["walks"] == 0 else None
    controls_dir = out / "controls" / item["item"]
    frozen = pilot.load(controls_dir / "cases.json")["cases"]
    new = new_cases(controls_dir, frozen)
    score = {"n": order["n"], "commit": order["commit"], "row": order["row"], "room_passed": None,
        "at_limit": at_limit, "exported_again": again}
    # A walk that could not be read names nothing: its fields are null, not empty.
    matching, offered = read_walk(walks, item, order["row"]) if walks is not None else (None, None)
    score.update(matching_named=matching, offered_named=offered)

    def done(counted, outcome, scored, **more):
        if scored == (outcome in UNSCORED):
            raise Refused("%s: outcome %s %s a score" % (order["directory"], outcome, "with" if scored else "without"))
        score.update(counted, outcome=outcome, scored=scored, **more)
        return score
    if kind in ("clock-failed", "export-failed"):
        return done(score_cases(frozen, NO_REPORT, new), kind, False)
    if not commit:
        return done(parent_score(controls_dir, frozen, new), kind, True)
    patch = source_patch(recorded / "repo", item["rows"][order["row"]]["base"], commit)
    if not patch.strip():
        return done(parent_score(controls_dir, frozen, new), "unchanged-source", True)
    base = turn_base(listed, order["commit"])
    try:
        ran = run_diagnostic(judged / "diagnostic", items, order["commit"], patch, plan, base)
    except ReportRefused as error:
        # A turn's code wrote what the judge refuses to read; the other rows are judged all the same.
        return done(score_cases(frozen, NO_REPORT, new), "report-refused", False, reason=str(error))
    counted = score_cases(frozen, ran["report"], new)
    if ran["limit"]:
        return done(counted, "diagnostic-limit", False)
    if ran["turn"] != "handed-in":
        return done(counted, "diagnostic-" + ran["turn"], False)
    if not ran["applied"]:
        return done(counted, "not-applied", False)
    replayed, verdict = run_replay(judged / "replay", items, order["commit"], patch, plan, base)
    if replayed in ("limit", "clock-failed"):
        return done(counted, "replay-" + replayed, False)
    return done(counted, kind, True, room_passed=verdict)


def judge(out, items, rows=None):
    out = Path(out).resolve()
    plan = load_judged_plan(out)
    items = items_dir(plan, items)
    listed = check_items(plan, items)
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
        score = judge_row(out, items, plan, order, listed=listed)
        pilot.write_json(judged / "score.json", score)
        done += 1
        print("%s: %s, %s" % (order["directory"], score["outcome"],
            "%d of %d" % (score["passed"], score["of"]) if score["scored"] else "no score"))
    return 0


# ---------------------------------------------------------------- report

def share(score, new=False):
    """The share of the frozen cases that pass; with `new`, of the frozen cases that fail on the parent."""
    return Fraction(score["passed_new"], score["of_new"]) if new else Fraction(score["passed"], score["of"])


def classify(d, r):
    if d > r:
        return "higher"
    if d < -r:
        return "lower"
    return "within"


def usable(score, new=False):
    return score is not None and score.get("scored") is True and score.get("of_new" if new else "of", 0) > 0


def item_reading(scores, new=False):
    """One item's b, r and each offering row's d and class, from {row: score or None}, on the share over all frozen
    cases or, with `new`, on the share over the new ones (an item whose of_new is 0 is not read). None where not read."""
    if not all(usable(scores.get(row), new) for row in NOTHING):
        return None
    n1, n2 = share(scores["nothing-1"], new), share(scores["nothing-2"], new)
    b, r = (n1 + n2) / 2, abs(n1 - n2)
    conditions = {}
    for row in OFFERING:
        if usable(scores.get(row), new):
            d = share(scores[row], new) - b
            conditions[row] = {"o": share(scores[row], new), "d": d, "class": classify(d, r)}
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


def attempts_of(directory, record):
    """(earlier attempts, interrupted attempts) from the record's own fields: an attempt is interrupted when it had
    started and its clock had not exited, as the runner counts interrupted_attempts; the two must agree."""
    attempts = record.get("attempts")
    if not isinstance(attempts, list) or not all(isinstance(held, dict) for held in attempts):
        raise Refused("%s: record.json has no attempts list" % directory)
    interrupted = sum(1 for held in attempts if held.get("started") is True and held.get("clock_exited") is not True)
    if (record.get("earlier_attempts"), record.get("interrupted_attempts")) != (len(attempts), interrupted):
        raise Refused("%s: record.json's attempt counts do not agree with its attempts" % directory)
    return len(attempts), interrupted


def make_report(out):
    out = Path(out).resolve()
    plan = load_judged_plan(out)
    scores, unjudged = {}, []
    outcomes, judged_outcomes = {}, {}
    at_limit = {row: 0 for row in ROWS}
    earlier, interrupted = {row: 0 for row in ROWS}, {row: 0 for row in ROWS}
    recorded = 0
    for order in plan["order"]:
        record_path = row_dir(out, order) / "record.json"
        score_path = judged_dir(out, order) / "score.json"
        record = pilot.load(record_path) if record_path.exists() else None
        score = pilot.load(score_path) if score_path.exists() else None
        if score is not None:
            if (score.get("n"), score.get("commit"), score.get("row")) != (order["n"], order["commit"], order["row"]):
                raise Refused("%s: score.json names another row" % order["directory"])
            scores.setdefault(order["item"], {})[order["row"]] = score
            judged_outcomes[score["outcome"]] = judged_outcomes.get(score["outcome"], 0) + 1
        if record is None:
            continue
        recorded += 1
        if score is None:
            unjudged.append(order["directory"])
        outcomes[record.get("outcome")] = outcomes.get(record.get("outcome"), 0) + 1
        # A judged row's at_limit is the judge's (it may come from turns exported again); a record without the key is
        # not at its limit.
        if (score if score is not None and "at_limit" in score else record).get("at_limit") is True:
            at_limit[order["row"]] += 1
        many, cut = attempts_of(order["directory"], record)
        earlier[order["row"]] += many
        interrupted[order["row"]] += cut
    probed = {item["item"] for item in plan["items"] if item["probed_before"]}
    stopped = {}
    for item in plan["items"]:
        held = out / "controls" / item["item"] / "stopped.json"
        if held.exists():
            stopped[item["item"]] = pilot.load(held)["reason"]
    parent = {}
    for item in plan["items"]:
        directory = out / "controls" / item["item"]
        if (directory / "parent.json").exists():
            frozen = pilot.load(directory / "cases.json")["cases"]
            parent[item["item"]] = {"passed": len(pilot.load(directory / "parent.json")["passed"]), "of": len(frozen),
                "of_new": len(new_cases(directory, frozen))}
    report = {
        "v": 2,
        "rows": {"planned": len(plan["order"]), "recorded": recorded, "judged": sum(map(len, scores.values())),
            "unjudged": unjudged, "outcomes": outcomes, "judged_outcomes": judged_outcomes,
            "unscored": {outcome: judged_outcomes[outcome] for outcome in UNSCORED if outcome in judged_outcomes},
            "at_limit": at_limit, "earlier_attempts": earlier, "interrupted": interrupted},
        "controls_stopped": stopped,
        "parent": parent,
        "probed": sorted(probed),
        "plan_of": {item["item"]: item["plan_group"] for item in plan["items"]},
        "places": {item["item"]: {"search": item["search"]["best_place"], "search_tied": item["search"]["tied"],
            "newest": item["newest"]["best_place"], "bm25": item["bm25"]["best_place"], "bm25_tied": item["bm25"]["tied"]}
            for item in plan["items"]},
    }
    for suffix, new in (("", False), ("_new", True)):
        readings = {item["item"]: item_reading(scores.get(item["item"], {}), new) for item in plan["items"]}
        items_tally = {row: tally(readings, row) for row in OFFERING}
        every = plan_summaries(plan, readings)
        if not new:
            # The rule of the spec's section 7 reads the share over all frozen cases, and only RULE_ROWS.
            report["rule"] = spending_rule(plan, scores, items_tally, every["plans_tally"])
        report["items" + suffix] = {item["item"]: None if readings[item["item"]] is None else {
            "probed_before": item["probed_before"], "plan_group": item["plan_group"],
            "n1": number(readings[item["item"]]["n1"]), "n2": number(readings[item["item"]]["n2"]),
            "b": number(readings[item["item"]]["b"]), "r": number(readings[item["item"]]["r"]),
            "conditions": {row: {"o": number(held["o"]), "d": number(held["d"]), "class": held["class"]}
                for row, held in readings[item["item"]]["conditions"].items()}} for item in plan["items"]}
        report["tally" + suffix] = items_tally
        report["tally_without_probed" + suffix] = {row: tally(readings, row, lambda item: item not in probed)
            for row in OFFERING}
        unprobed = plan_summaries(plan, readings, lambda item: not item["probed_before"])
        for part, held in (("", every), ("_without_probed", unprobed)):
            report["plans" + part + suffix] = {group: {"items": value["items"], "conditions": {row: {
                "D": number(cond["D"]), "R": number(cond["R"]), "class": cond["class"], "on": cond["on"]}
                for row, cond in value["conditions"].items()}} for group, value in held["plans"].items()}
            report["plans_tally" + part + suffix] = held["plans_tally"]
            report["figures" + part + suffix] = {row: number(value) for row, value in held["figures"].items()}
            report["figures_on" + part + suffix] = held["figures_on"]
    return report


def cell(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return "%.3f" % value
    return str(value)


def counted(pairs):
    return ", ".join("%s %d" % pair for pair in pairs) or "none"


SHARES = (("", "shares of the frozen cases"),
    ("_new", "shares of the new cases: the frozen cases that fail on the parent; an item whose of_new is 0 is not read"))


def report_markdown(report):
    lines = ["# A document offered: the report", ""]
    rows = report["rows"]
    lines += ["Rows: %d planned, %d recorded, %d judged, %d recorded and not judged." % (rows["planned"],
        rows["recorded"], rows["judged"], len(rows["unjudged"])), "",
        "Attempts interrupted (started, clock not exited) and taken up again, by condition, from the records: %s; "
        "earlier attempts of any kind: %s." % (counted((row, rows["interrupted"][row]) for row in ROWS),
        counted((row, rows["earlier_attempts"][row]) for row in ROWS)), "",
        "Recorded outcomes: %s. Judged outcomes: %s." % (counted(sorted(rows["outcomes"].items())),
        counted(sorted(rows["judged_outcomes"].items()))), "",
        "Rows with no score, by outcome: %s." % counted((outcome, rows["unscored"][outcome]) for outcome in UNSCORED
        if outcome in rows["unscored"]), "",
        "Rows the room ended at their limit, by condition: %s." % ", ".join("%s %d" % (row, rows["at_limit"][row])
        for row in ROWS), "", BM25_SENTENCE, ""]
    for item, reason in sorted(report["controls_stopped"].items()):
        lines.append("Controls stopped at %s: %s" % (item, reason))
    for suffix, title in SHARES:
        lines += ["", "## Each item (%s)" % title, "",
            "| item | plan | parent | of | of_new | n1 | n2 | b | r | " + " | ".join("%s d (class)" % row
            for row in OFFERING) + " |", "| --- " * (9 + len(OFFERING)) + "|"]
        for item, held in report["items" + suffix].items():
            parent = report["parent"].get(item)
            first = "%s | %s | %s | %s" % (report["plan_of"][item], "-" if parent is None else "%d of %d" % (
                parent["passed"], parent["of"]), "-" if parent is None else parent["of"],
                "-" if parent is None else parent["of_new"])
            if held is None:
                lines.append("| %s | %s | no baseline |" % (item, first) + " |" * (3 + len(OFFERING)))
                continue
            mark = " (probed)" if held["probed_before"] else ""
            lines.append("| %s%s | %s | %s | %s | %s | %s | %s |" % (item, mark, first, cell(held["n1"]),
                cell(held["n2"]), cell(held["b"]), cell(held["r"]), " | ".join(
                "%s (%s)" % (cell(held["conditions"][row]["d"]), held["conditions"][row]["class"])
                if row in held["conditions"] else "not read" for row in OFFERING)))
        lines += ["", "## Each condition over the items (%s)" % title, "",
            "| condition | higher | lower | within | items it stands on |"
            " without the probed: higher | lower | within | on |", "| --- " * 9 + "|"]
        for row in OFFERING:
            a, w = report["tally" + suffix][row], report["tally_without_probed" + suffix][row]
            lines.append("| %s | %d | %d | %d | %d | %d | %d | %d | %d |" % (row, a["higher"], a["lower"],
                a["within"], a["on"], w["higher"], w["lower"], w["within"], w["on"]))
        for part, named in (("", "By plan"), ("_without_probed", "By plan, without the probed item")):
            key = part + suffix
            lines += ["", "## %s (%s)" % (named, title), "", "| plan | items | " + " | ".join(
                "%s D, R (class)" % row for row in OFFERING) + " |", "| --- " * (2 + len(OFFERING)) + "|"]
            for group, held in report["plans" + key].items():
                lines.append("| %s | %s | %s |" % (group, ", ".join(held["items"]), " | ".join(
                    "%s, %s (%s; on %d)" % (cell(held["conditions"][row]["D"]), cell(held["conditions"][row]["R"]),
                    held["conditions"][row]["class"], held["conditions"][row]["on"]) if row in held["conditions"]
                    else "not read" for row in OFFERING)))
            lines += ["", "Every plan weighing the same: " + "; ".join("%s %s (%d plans, %d items)" % (row,
                cell(report["figures" + key][row]), report["figures_on" + key][row]["plans"],
                report["figures_on" + key][row]["items"]) for row in OFFERING) + ". Plans higher: " + "; ".join(
                "%s %d of %d" % (row, report["plans_tally" + key][row]["higher"], report["plans_tally" + key][row]["on"])
                for row in OFFERING) + "."]
    lines += ["", "## The rule for where to spend next", "",
        "The rule reads the shares of all frozen cases at the rows %s; bm25 is not among them." % ", ".join(RULE_ROWS), ""]
    rule = report["rule"]
    lines.append("**%s**." % rule["decision"].capitalize() + ("" if not rule["missing"] else
        " The rule is not applied: these rows it needs have no score: %s." % ", ".join(rule["missing"])))
    lines += ["", "## Places counted before any turn", "", BM25_SENTENCE, "",
        "| item | search: best place | tied | bm25: best place | tied | newest plans: best place |",
        "| --- | --- | --- | --- | --- | --- |"]
    for item, held in report["places"].items():
        lines.append("| %s | %s | %s | %s | %s | %s |" % (item, cell(held["search"]), cell(held["search_tied"]),
            cell(held["bm25"]), cell(held["bm25_tied"]), cell(held["newest"])))
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
