#!/usr/bin/env python3
"""The judge of the second pilot, "a line that says a plan may exist". Python 3.9+, standard library, python -I.

  python3 -I documents_judge2.py controls <out> --items <items dir>
  python3 -I documents_judge2.py judge <out> --items <items dir> [--rows N]
  python3 -I documents_judge2.py report <out>

controls: the first judge's controls (documents_judge.control_item) for every item of plan.json, or, when there is no
plan yet, of candidates.json (part A, pool P and pool N). Before a plan exists the limits, the room's program and its
environment come from the first maker's runtime_pins, as the maker pins them.

judge: each recorded row is scored by the first judge's own judge_row, unchanged. Added to its score, the walk's counts
of the spec's section 7: plans_named and first_source_second from the walk; from the room's turns export,
worker_seconds (its measured worker_ms, not the first pilot's ended minus began) and tokens; steps, the room's own
count when its turns export gives one, else the walk's. A walk or a turns export that could not be read gives nulls,
never zeros.

report: the spec's section 8. Part B's readings by item and by pool, the counts beside them, part A's counts, and the
rule for whether a larger trial is worth running, read once on the shares of all frozen cases.
"""
import argparse
import importlib.util
import inspect
import json
import os
import sys
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


first = import_file("documents_judge", HERE / "documents_judge.py")
maker = first.maker
pilot = first.pilot
Refused = first.Refused

LINE = "There may be a plan for this work in the repository. Look for one before you change code."
PART_ROWS = {"A": ("may-1", "may-2"), "B": ("nothing-1", "nothing-2", "may-1", "may-2")}
NOTHING = ("nothing-1", "nothing-2")
MAY = ("may-1", "may-2")
POOLS = {"A": (None,), "B": ("P", "N")}
FOLDERS = ("plans", "specs", "reviews")
SOURCE = first.SOURCE
NOT_WORTH_BELOW = Fraction(-5, 100)         # pool N's mean d below this is "not worth one"
NOT_WORTH_LOWER = 2                         # pool N items lower, at or above this, is "not worth one"
STAND_IN_WORKER = "script:/bin/sh"          # the controls run script workers of their own; this pin is not used
RULE_SENTENCE = ("The rule reads agreement with the reference's tests and nothing else. It leaves out what the line "
    "costs in seconds and tokens; those are printed beside it, by pool and row kind, and the rule does not weigh them.")
PART_A_SENTENCE = ("Part A's twelve items are seen: earlier turns were run at them and their results shaped this design. "
    "They enter no class and no rule.")
NONE_FOUND_SENTENCE = ("Pool N is \"no plan found by the review\": one reader's review of the Markdown files tracked at "
    "the item's first parent. It is not a showing that no plan exists.")
NOT_AVAILABLE = "not available"


# ---------------------------------------------------------------- the plan

def check_shape(plan):
    """One plan shape only: v 2; part A items have the rows may-1 and may-2, part B items nothing-1, nothing-2, may-1
    and may-2; a part B item only when part_b_run; the order holds each item's every row once."""
    if plan.get("v") != 2:
        raise Refused("the plan's v is %r, not 2" % plan.get("v"))
    if type(plan.get("part_b_run")) is not bool:
        raise Refused("the plan's part_b_run is %r, not a bool" % plan.get("part_b_run"))
    for item in plan["items"]:
        part = item.get("part")
        if part not in PART_ROWS:
            raise Refused("%s: part %r is not A or B" % (item["item"], part))
        if item.get("pool") not in POOLS[part]:
            raise Refused("%s: part %s with pool %r" % (item["item"], part, item.get("pool")))
        if sorted(item["rows"]) != sorted(PART_ROWS[part]):
            raise Refused("%s: the plan's rows are %s, not %s" % (item["item"], sorted(item["rows"]),
                sorted(PART_ROWS[part])))
        if part == "B" and not plan["part_b_run"]:
            raise Refused("%s: a part B item in a plan whose part_b_run is false" % item["item"])
    wanted = sorted((item["commit"], row) for item in plan["items"] for row in item["rows"])
    if sorted((order["commit"], order["row"]) for order in plan["order"]) != wanted:
        raise Refused("the plan's order is not each item's rows once")
    return plan


def load_judged_plan(out):
    return check_shape(maker.load_plan(out))


# ---------------------------------------------------------------- controls

def pinned_runtime(items, out):
    """The limits, the room's program and its environment, as the first maker pins them, for controls made before a
    plan exists. The diagnostic's and the replay's limits are the first maker's make_plan defaults."""
    defaults = inspect.signature(maker.make_plan).parameters
    _, limits, programs, environment = maker.runtime_pins(items, out, STAND_IN_WORKER, None,
        defaults["replay_secs"].default, defaults["diagnostic_secs"].default)
    return {"limits": limits, "programs": programs, "environment": environment}


def candidate_items(candidates):
    if candidates.get("v") != 2:
        raise Refused("candidates.json's v is %r, not 2" % candidates.get("v"))
    held, seen = [], set()
    for key in ("part_a", "pool_p", "pool_n"):
        for item in candidates[key]:
            if item["item"] not in seen:
                seen.add(item["item"])
                held.append(item)
    return held


def controls(out, items):
    out = Path(out).resolve()
    if (out / "plan.json").exists():
        plan = load_judged_plan(out)
        items = first.items_dir(plan, items)
        listed = first.check_items(plan, items)
        targets = plan["items"]
    else:
        candidates = pilot.load(out / "candidates.json")
        targets = candidate_items(candidates)
        if items is None:
            raise Refused("no plan yet: --items is needed")
        listed = first.check_items({"list_sha256": candidates["list_sha256"]}, items)
        plan = pinned_runtime(items, out)
    (out / "controls").mkdir(exist_ok=True)
    for item in targets:
        first.control_item(out, plan, items, listed, item)
    return 0


# ---------------------------------------------------------------- the walk's counts

def read_steps(path):
    """The steps of a row's one walk, or None when it cannot be read: no file, no walk, more than one, not JSON, or
    not a walk's shape."""
    if path is None:
        return None
    try:
        lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) != 1:
            return None
        walk = json.loads(lines[0])
    except (OSError, ValueError):
        return None
    if not isinstance(walk, dict) or not isinstance(walk.get("steps"), list) \
            or not all(isinstance(step, dict) for step in walk["steps"]):
        return None
    return walk["steps"]


def named_paths(steps):
    return {named[0] for step in steps for named in (step.get("named") or [])
        if isinstance(named, (list, tuple)) and named and isinstance(named[0], str)}


def under_folders(path):
    """A path under a plans, specs or reviews folder, at any depth."""
    return any(part in FOLDERS for part in path.split("/")[:-1])


def first_source_second(steps):
    """The seconds of the first step naming a path under the source directory, each path's first step found by the
    first judge's own first_named: None when no step naming one has a time."""
    seen = [first.first_named(steps, path)["seconds"] for path in named_paths(steps) if path.startswith(SOURCE + "/")]
    seen = [seconds for seconds in seen if seconds is not None]
    return min(seen) if seen else None


def read_measured(path):
    """(worker_seconds, tokens, steps) from a row's turns export: the worker's milliseconds as seconds (not the
    record's ended minus began, which the first pilot's rows called seconds), fresh-in plus output, and the room's own
    count of the turn's steps. None for each that is not there as a whole number."""
    try:
        turns = json.loads(Path(path).read_bytes()) if path is not None else None
    except (OSError, ValueError):
        turns = None
    if not (isinstance(turns, list) and len(turns) == 1 and isinstance(turns[0], dict)):
        return None, None, None
    steps = turns[0].get("steps") if type(turns[0].get("steps")) is int else None
    measured = turns[0].get("measured")
    if not isinstance(measured, dict):
        return None, None, steps
    worker_ms = measured.get("worker_ms")
    seconds = worker_ms / 1000 if type(worker_ms) is int else None
    tokens = measured.get("tokens") if isinstance(measured.get("tokens"), dict) else {}
    parts = [tokens.get("fresh_in"), tokens.get("output")]
    return seconds, (sum(parts) if all(type(part) is int for part in parts) else None), steps


def export_path(out, order, record, score, what, name):
    """The export judge_row read: the runner's, or the judge's own export again when the runner's failed; None when
    that failed too."""
    if record[what + "_exit"] == 0:
        return first.row_dir(out, order) / name
    if score["exported_again"].get(what) == 0:
        return first.judged_dir(out, order) / name
    return None


def walk_counts(out, order, record, score):
    """The counts added to a row's score. steps is the room's own count from the turns export when it gives one,
    else the walk's steps, else None; steps_from says which."""
    steps = read_steps(export_path(out, order, record, score, "walks", "walks.jsonl"))
    seconds, tokens, room_steps = read_measured(export_path(out, order, record, score, "turns", "turns.json"))
    counts = {"walk_read": steps is not None, "worker_seconds": seconds, "tokens": tokens}
    if room_steps is not None:
        counts.update(steps=room_steps, steps_from="room")
    elif steps is not None:
        counts.update(steps=len(steps), steps_from="walk")
    else:
        counts.update(steps=None, steps_from=None)
    if steps is None:
        counts.update(plans_named=None, first_source_second=None)
    else:
        counts.update(plans_named=sorted(path for path in named_paths(steps) if under_folders(path)),
            first_source_second=first_source_second(steps))
    return counts


# ---------------------------------------------------------------- judge

def judge(out, items, rows=None):
    out = Path(out).resolve()
    plan = load_judged_plan(out)
    items = first.items_dir(plan, items)
    listed = first.check_items(plan, items)
    (out / "judged").mkdir(exist_ok=True)
    done = 0
    for order in plan["order"]:
        if rows is not None and done >= rows:
            break
        recorded = first.row_dir(out, order)
        if not (recorded / "record.json").exists():
            continue
        judged = first.judged_dir(out, order)
        if (judged / "score.json").exists():
            continue
        controls_dir = out / "controls" / order["item"]
        if not (controls_dir / "parent.json").exists():
            print("%s: not judged: the item's controls %s" % (order["directory"],
                "stopped" if (controls_dir / "stopped.json").exists() else "are not made"))
            continue
        if judged.exists():
            first.move_aside(judged)
        judged.mkdir()
        score = first.judge_row(out, items, plan, order, listed=listed)
        score.update(walk_counts(out, order, pilot.load(recorded / "record.json"), score))
        pilot.write_json(judged / "score.json", score)
        done += 1
        print("%s: %s, %s" % (order["directory"], score["outcome"],
            "%d of %d" % (score["passed"], score["of"]) if score["scored"] else "no score"))
    return 0


# ---------------------------------------------------------------- readings

def pair(scores, rows, new):
    """(first, second, mean, gap) of a pair of rows, or four Nones when either has no score."""
    if not all(first.usable(scores.get(row), new) for row in rows):
        return None, None, None, None
    one, two = first.share(scores[rows[0]], new), first.share(scores[rows[1]], new)
    return one, two, (one + two) / 2, abs(one - two)


def item_reading(scores, new=False):
    """A part B item's n1, n2, b, rn, m1, m2, m, rm, d, its class with max(rn, rm), and whether its Nothing pair is at
    its ceiling (both pass every case the share counts). A pair with a row unscored gives Nones."""
    n1, n2, b, rn = pair(scores, NOTHING, new)
    m1, m2, m, rm = pair(scores, MAY, new)
    d = m - b if b is not None and m is not None else None
    return {"n1": n1, "n2": n2, "b": b, "rn": rn, "m1": m1, "m2": m2, "m": m, "rm": rm, "d": d,
        "class": first.classify(d, max(rn, rm)) if d is not None else None,
        "ceiling": n1 == 1 and n2 == 1 if n1 is not None else None}


def mean(values):
    values = list(values)
    return sum(values, Fraction(0)) / len(values) if values else None


def pool_reading(plan, readings, pool):
    """A pool's mean d and the items it stands on; for pool P the mean over plan groups of each group's mean d and
    the groups it stands on (a group with no d is left out); items higher, lower and within."""
    members = [item for item in plan["items"] if item["pool"] == pool]          # part A's pool is None
    with_d = [item for item in members if readings[item["item"]]["d"] is not None]
    held = {"items": len(members), "mean_d": mean(readings[item["item"]]["d"] for item in with_d), "on": len(with_d)}
    for kind in ("higher", "lower", "within"):
        held[kind] = sum(1 for item in with_d if readings[item["item"]]["class"] == kind)
    if pool == "P":
        groups = {}
        for item in with_d:
            groups.setdefault(item["plan_group"], []).append(readings[item["item"]]["d"])
        held["groups"] = {group: {"mean_d": mean(ds), "on": len(ds)} for group, ds in sorted(groups.items())}
        held["mean_groups"] = mean(value["mean_d"] for value in held["groups"].values())
        held["groups_on"] = len(groups)
        held["all_at_ceiling"] = bool(members) and all(readings[item["item"]]["ceiling"] is True for item in members)
    return held


def rule(plan, scores, pools):
    """The rule, read once on the shares of all frozen cases. None when part B was not run."""
    if not plan["part_b_run"]:
        return None
    missing = ["%s %s" % (item["item"], row) for item in plan["items"] if item["part"] == "B"
        for row in PART_ROWS["B"] if not first.usable(scores.get(item["item"], {}).get(row))]
    if missing:
        return {"decision": "suspended", "missing": missing, "no_gain_possible": None}
    p, n = pools["P"], pools["N"]
    positive = lambda value: value is not None and value > 0
    if positive(p["mean_d"]) and positive(p["mean_groups"]) and p["higher"] >= 1 \
            and n["mean_d"] is not None and n["mean_d"] >= 0 and n["lower"] == 0:
        decision = "worth a larger trial"
    elif n["lower"] >= NOT_WORTH_LOWER or (n["mean_d"] is not None and n["mean_d"] < NOT_WORTH_BELOW):
        decision = "not worth one"
    else:
        decision = "between"
    return {"decision": decision, "missing": [], "no_gain_possible": p["all_at_ceiling"]}


def mean_of(values):
    values = [value for value in values if value is not None]
    return {"mean": sum(values) / len(values) if values else None, "on": len(values)}


def counts_beside(plan, scores):
    """By pool (A, P, N) and row kind (nothing, may), over judged rows: turns whose walk names a matching file (A and
    P), the distinct plans/specs/reviews paths named, the first source second, steps, worker seconds and tokens, each with the
    turns it stands on."""
    table = {}
    for item in plan["items"]:
        pool = "A" if item["part"] == "A" else item["pool"]
        for row, score in scores.get(item["item"], {}).items():
            kind = "nothing" if row in NOTHING else "may"
            table.setdefault(pool, {}).setdefault(kind, []).append(score)
    out = {}
    for pool, kinds in sorted(table.items()):
        for kind, held in sorted(kinds.items()):
            read = [score for score in held if score.get("walk_read") is True]
            cell = {"turns": len(held), "walks_read": len(read),
                "plans_paths": sorted({path for score in read for path in score["plans_named"]}),
                "turns_naming_plans_paths": sum(1 for score in read if score["plans_named"]),
                "first_source_second": mean_of(score.get("first_source_second") for score in read),
                "steps": mean_of(score.get("steps") for score in held),
                "worker_seconds": mean_of(score.get("worker_seconds") for score in held),
                "tokens": mean_of(score.get("tokens") for score in held)}
            if pool in ("A", "P"):
                cell["names_matching"] = sum(1 for score in read if score.get("matching_named"))
            out["%s %s" % (pool, kind)] = cell
    return out


def number(value):
    return None if value is None else float(value)


def plain(value):
    """A reading for JSON: every Fraction as a float, in dicts at any depth."""
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, dict):
        return {key: plain(held) for key, held in value.items()}
    return value


def make_report(out):
    out = Path(out).resolve()
    plan = load_judged_plan(out)
    scores, recorded, unjudged, outcomes = {}, 0, [], {}
    for order in plan["order"]:
        record_path = first.row_dir(out, order) / "record.json"
        score_path = first.judged_dir(out, order) / "score.json"
        if score_path.exists():
            score = pilot.load(score_path)
            if (score.get("n"), score.get("commit"), score.get("row")) != (order["n"], order["commit"], order["row"]):
                raise Refused("%s: score.json names another row" % order["directory"])
            scores.setdefault(order["item"], {})[order["row"]] = score
            outcomes[score["outcome"]] = outcomes.get(score["outcome"], 0) + 1
        if record_path.exists():
            recorded += 1
            if not score_path.exists():
                unjudged.append(order["directory"])
    stopped = {item["item"]: pilot.load(out / "controls" / item["item"] / "stopped.json")["reason"]
        for item in plan["items"] if (out / "controls" / item["item"] / "stopped.json").exists()}
    report = {"v": 2, "line": LINE, "part_b_run": plan["part_b_run"],
        "rows": {"planned": len(plan["order"]), "recorded": recorded, "judged": sum(map(len, scores.values())),
            "unjudged": unjudged, "outcomes": outcomes,
            "unscored": {key: outcomes[key] for key in first.UNSCORED if key in outcomes}},
        "controls_stopped": stopped, "counts": counts_beside(plan, scores)}
    part_b = [item for item in plan["items"] if item["part"] == "B"]
    for suffix, new in (("", False), ("_new", True)):
        readings = {item["item"]: item_reading(scores.get(item["item"], {}), new) for item in part_b}
        pools = {pool: pool_reading(plan, readings, pool) for pool in ("P", "N")}
        if not new:
            report["rule"] = rule(plan, scores, pools)
        report["items" + suffix] = {item["item"]: dict(plain(readings[item["item"]]), pool=item["pool"],
            plan_group=item.get("plan_group"), message=item.get("message")) for item in part_b}
        report["pools" + suffix] = plain(pools)
    part_a = [item for item in plan["items"] if item["part"] == "A"]
    # judge_row's matching_named is None or empty for a walk this judge could not read.
    report["part_a"] = {"turns": sum(len(item["rows"]) for item in part_a),
        "names_matching": sum(1 for item in part_a for score in scores.get(item["item"], {}).values()
            if score.get("matching_named")),
        "walks_read": sum(1 for item in part_a for score in scores.get(item["item"], {}).values()
            if score.get("walk_read") is True),
        "items": {item["item"]: {row: None if not first.usable(scores.get(item["item"], {}).get(row)) else
            {"passed": scores[item["item"]][row]["passed"], "of": scores[item["item"]][row]["of"]}
            for row in PART_ROWS["A"]} for item in part_a}}
    return report


# ---------------------------------------------------------------- the report's text

def cell(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return "%.3f" % value
    return str(value)


def aggregate(value, on, what="items"):
    return NOT_AVAILABLE if value is None else "%s (on %d %s)" % (cell(value), on, what)


SHARES = (("", "shares of all frozen cases"),
    ("_new", "shares of the frozen cases that do not pass on the parent; an item with none is not read"))


def report_markdown(report):
    rows = report["rows"]
    lines = ["# A line that says a plan may exist: the report", "", "The line: %s" % report["line"], "",
        "Rows: %d planned, %d recorded, %d judged, %d recorded and not judged." % (rows["planned"], rows["recorded"],
        rows["judged"], len(rows["unjudged"])), "",
        "Judged outcomes: %s. Rows with no score, by outcome: %s." % (first.counted(sorted(rows["outcomes"].items())),
        first.counted(sorted(rows["unscored"].items()))), "", "## Read this before the tables", "",
        "- " + RULE_SENTENCE, "- " + first.FORGE_SENTENCE, "- " + first.REPLAY_SENTENCE, "- " + PART_A_SENTENCE,
        "- " + NONE_FOUND_SENTENCE, ""]
    for item, reason in sorted(report["controls_stopped"].items()):
        lines.append("Controls stopped at %s: %s" % (item, reason))
    if not report["part_b_run"]:
        lines += ["", "Part B was not run: a pool ended before six items were taken. The rule gives no outcome."]
    else:
        for suffix, title in SHARES:
            lines += ["", "## Part B, each item (%s)" % title, "",
                "| item | pool | plan group | n1 | n2 | b | rn | m1 | m2 | m | rm | d | class | ceiling |"
                " message: names a matching file | cites a task or step | counted names held |", "| --- " * 17 + "|"]
            for item, held in sorted(report["items" + suffix].items(), key=lambda pair: (pair[1]["pool"], pair[0])):
                message = held["message"] or {}
                lines.append("| %s |" % item + " | ".join(cell(held[key]) for key in ("pool", "plan_group", "n1", "n2",
                    "b", "rn", "m1", "m2", "m", "rm", "d", "class", "ceiling")) + " | %s | %s | %s |" % (
                    cell(message.get("names_a_matching_file")), cell(message.get("cites_a_task_or_step")),
                    ", ".join(message.get("counted_names_held") or []) or "-"))
            lines += ["", "## Part B, each pool (%s)" % title, ""]
            for pool, held in sorted(report["pools" + suffix].items()):
                text = "Pool %s: mean d %s; higher %d, lower %d, within %d, of %d items." % (pool,
                    aggregate(held["mean_d"], held["on"]), held["higher"], held["lower"], held["within"], held["items"])
                if pool == "P":
                    text += " Mean over plan groups %s." % aggregate(held["mean_groups"], held["groups_on"], "groups")
                lines.append(text)
        lines += ["", "## The rule for whether a larger trial is worth running", "",
            "It reads part B alone, once, on the shares of all frozen cases. The reading on the cases that do not pass "
            "on the parent, above, decides nothing.", ""]
        held = report["rule"]
        if held["decision"] == "suspended":
            lines.append("**Suspended.** The rule is not applied: these rows it needs have no score: %s."
                % ", ".join(held["missing"]))
        else:
            lines.append("**%s**." % held["decision"].capitalize())
            if held["no_gain_possible"]:
                lines.append("Every pool P pair is at its ceiling: the pool could show no gain.")
    lines += ["", "## Counts beside the scores, by pool and row kind", "",
        "| pool, rows | turns | walks read | names a matching file | turns naming a plans/specs/reviews path |"
        " distinct paths | first source second | steps | worker seconds | tokens |", "| --- " * 10 + "|"]
    for key, held in sorted(report["counts"].items()):
        lines.append("| %s | %d | %d | %s | %d | %d | %s | %s | %s | %s |" % (key, held["turns"], held["walks_read"],
            cell(held.get("names_matching")), held["turns_naming_plans_paths"], len(held["plans_paths"]),
            *(aggregate(number(held[name]["mean"]), held[name]["on"], "turns")
            for name in ("first_source_second", "steps", "worker_seconds", "tokens"))))
    part_a = report["part_a"]
    lines += ["", "## Part A, counts only", "",
        "Turns whose walk names a matching file: %d of %d (walks read: %d)." % (part_a["names_matching"],
        part_a["turns"], part_a["walks_read"]), "", "| item | may-1 | may-2 |", "| --- | --- | --- |"]
    for item, held in sorted(part_a["items"].items()):
        lines.append("| %s | %s |" % (item, " | ".join("no score" if held[row] is None else "%d of %d" % (
            held[row]["passed"], held[row]["of"]) for row in PART_ROWS["A"])))
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
    parser = argparse.ArgumentParser(prog="documents_judge2.py")
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
