#!/usr/bin/env python3
"""Freeze the second document pilot. Python 3.9+, stdlib, run with python -I."""
import argparse
import collections
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("documents_plan", HERE / "documents_plan.py")
first = importlib.util.module_from_spec(spec)
spec.loader.exec_module(first)
pilot = first.pilot
Refused = first.Refused
SPEC = first.ROOT / "docs/superpowers/specs/2026-11-19-v2-a-line-that-says-a-plan-may-exist.md"
CENSUS = HERE / "census-2026-11-18.txt"
SEED = 20261120
LINE = "There may be a plan for this work in the repository. Look for one before you change code."
MAY = {"may-1": LINE, "may-2": LINE}
BOTH = {"nothing-1": "", "nothing-2": "", **MAY}
SELECTION = {"used_before": "used-before.txt", "pool_p_order": "pool-p.order.json",
    "pool_n_order": "pool-n.order.json", "pool_p_record": "pool-p.record.json", "pool_n_record": "pool-n.record.json"}


def selection_pins(selection):
    return {key + "_sha256": first.digest((Path(selection) / name).read_bytes()) for key, name in SELECTION.items()}


def accepted(selection, pool):
    """Read the reader's prefix, never reopen a skipped review."""
    selection = Path(selection)
    prefix = "pool-" + pool.lower()
    order = pilot.load(selection / (prefix + ".order.json"))
    record = pilot.load(selection / (prefix + ".record.json"))
    ordered, walked = order["items"], record["walked"]
    if order["pool"] != pool or record["pool"] != pool:
        raise Refused("%s: order or record names another pool" % pool)
    used = set((selection / "used-before.txt").read_text(encoding="ascii").split())
    first.distinct_items([entry["commit"] for entry in ordered])
    previous = ""
    for n, entry in enumerate(ordered, 1):
        hashed = first.digest(("%s:pick:%s" % (SEED, entry["commit"])).encode("ascii"))
        if entry["n"] != n or entry["hash"] != hashed or hashed <= previous:
            raise Refused("%s: order differs at %s" % (pool, n))
        if entry["commit"] in used:
            raise Refused("%s: item used before: %s" % (pool, entry["commit"]))
        previous = hashed
    if len(walked) > len(ordered):
        raise Refused("%s: record walks past the order" % pool)
    if record["stopped"] not in ("nine accepted", "the pool ended", "time"):
        raise Refused("%s: record has an unknown stopped reason" % pool)
    if type(record["stopped_n"]) is not int or record["stopped_n"] != len(walked):
        raise Refused("%s: stopped_n is not the last place walked" % pool)
    if record["stopped"] == "the pool ended" and len(walked) != len(ordered):
        raise Refused("%s: record says the pool ended before its end" % pool)
    result = []
    fields = {"n", "commit", "verdict", "reason", "files_read"}
    fields |= {"plan_group", "plan_group_reason", "gives"} if pool == "P" else {"subject", "terms", "queries", "found"}
    for reviewed, entry in zip(walked, ordered):
        if not fields <= reviewed.keys():
            raise Refused("%s: record entry lacks fields: %s" % (pool, sorted(fields - reviewed.keys())))
        if (reviewed["n"], reviewed["commit"]) != (entry["n"], entry["commit"]):
            raise Refused("%s: record is not the order's own prefix at %s" % (pool, entry["n"]))
        if reviewed["verdict"] not in ("accepted", "skipped"):
            raise Refused("%s: unknown verdict at %s" % (pool, entry["n"]))
        if reviewed["verdict"] == "skipped":
            continue
        item = {key: entry[key] for key in ("n", "commit", "parent")}
        item["item"] = entry["commit"][:10]
        if pool == "P":
            group = reviewed["plan_group"]
            if not isinstance(group, str) or not group.strip():
                raise Refused("P: accepted item has no plan_group: " + item["item"])
            item.update(plan_group=group, matching=entry["matching"], direct_path=entry["direct_path"])
        result.append(item)
    counts = collections.Counter(i["plan_group"] for i in result) if pool == "P" else None
    counted = sum(min(n, 2) for n in counts.values()) if pool == "P" else len(result)
    if record["stopped"] == "nine accepted" and counted != 9:
        raise Refused("%s: nine accepted does not describe the record: %s" % (pool, counted))
    return result


def candidate_data(items, selection, census=CENSUS, expected=first.EXPECTED, expected_list_sha256="4b25d330"):
    data, raw = pilot.listed(items)
    hashed = first.digest(raw)
    if not hashed.startswith(expected_list_sha256):
        raise Refused("items.json sha256 differs: expected %s, found %s" % (expected_list_sha256, hashed))
    selected = first.select_items(Path(items) / "repo", data["commits"], first.census_passes(census))
    if expected is not None and ({i["commit"][:8] for i in selected} != expected or len(selected) != len(expected)):
        raise Refused("part A cohort differs from the first pilot")
    candidate = {"v": 2, "list_sha256": hashed, "selection": selection_pins(selection),
        "part_a": [{key: item[key] for key in ("commit", "item", "parent")} for item in selected],
        "pool_p": accepted(selection, "P"), "pool_n": accepted(selection, "N")}
    all_items = candidate["part_a"] + candidate["pool_p"] + candidate["pool_n"]
    first.distinct_items([i["commit"] for i in all_items])
    entries = {e["commit"]: e for e in data["commits"]}
    for item in all_items:
        commit = item["commit"]
        if commit not in entries or first.git(Path(items) / "repo", "rev-parse", commit + "^1").decode().strip() != item["parent"]:
            raise Refused("%s: candidate is absent from the list or has another parent" % item["item"])
    return candidate, selected


def candidates(items, selection, out, census=CENSUS, expected=first.EXPECTED, expected_list_sha256="4b25d330"):
    candidate, _ = candidate_data(items, selection, census, expected, expected_list_sha256)
    for directory in (Path(out).absolute(), *Path(out).absolute().parents):
        if not directory.exists() and re.search(r"[0-9a-fA-F]{32}", directory.name):
            raise Refused("directory name holds 32 hexadecimal characters: " + directory.name)
    out = pilot.new_output(out)
    pilot.write_json(out / "candidates.json", candidate)
    return candidate


def control_data(out, item):
    directory = Path(out) / "controls" / item["item"]
    if (directory / "stopped.json").exists():
        return None
    result = []
    for name, field in (("cases.json", "cases"), ("parent.json", "passed")):
        try:
            held = pilot.load(directory / name)
        except (OSError, ValueError) as error:
            raise Refused("%s: control %s missing or unreadable: %s" % (item["item"], name, error)) from None
        if not isinstance(held, dict) or held.get("commit") != item["commit"] or not isinstance(held.get(field), list):
            raise Refused("%s: invalid control %s" % (item["item"], name))
        result.append(set(held[field]))
    if not result[0]:
        raise Refused("%s: control cases.json is empty" % item["item"])
    return result


def walk_pool(candidates, controls, pool):
    taken, walked = [], []
    groups = collections.Counter()
    for item in candidates:
        held = controls[item["commit"]]
        if held is None:
            raise Refused("%s: controls stopped (stopped.json exists)" % item["item"])
        if pool == "P" and groups[item["plan_group"]] >= 2:
            why = "the plan group has two"
        elif held[0] <= held[1]:
            why = "every frozen case passes on the parent"
        else:
            why = "taken"
            taken.append(item)
            if pool == "P":
                groups[item["plan_group"]] += 1
        walked.append({"n": item["n"], "commit": item["commit"], "taken": why == "taken", "why": why})
        if len(taken) == 6:
            break
    return taken, walked


def message_bytes(repo, commit):
    return first.git(repo, "show", "-s", "--encoding=UTF-8", "--format=%s%n%n%b", commit).rstrip(b" \t\r\n\v\f")


def message_record(message, item):
    text = message.decode("utf-8")
    return {"names_a_matching_file": any(path in text or Path(path).name in text for path in item["matching"]),
        "cites_a_task_or_step": re.search(r"\b[Tt]ask\s+\d+|\b[Ss]tep\s+\d+", text) is not None,
        "counted_names_held": sorted(name for name in item["counted_names"] if first.has_word(text, name))}


def row_order(items):
    rows = [{"commit": i["commit"], "item": i["item"], "row": name,
        "hash": first.digest(("%s:order:%s:%s" % (SEED, i["commit"], name)).encode("ascii"))}
        for i in items for name in i["rows"]]
    rows.sort(key=lambda row: row["hash"])
    for n, row in enumerate(rows, 1):
        row.update(n=n, directory="rows/%03d-%s-%s" % (n, row["item"], row["row"]))
    return rows


def make_plan(items, tasks, selection, out, worker, census, expected=first.EXPECTED, expected_list_sha256="4b25d330"):
    items, tasks, selection, out = map(lambda p: Path(p).resolve(), (items, tasks, selection, out))
    candidate, part_a = candidate_data(items, selection, census, expected, expected_list_sha256)
    if pilot.load(out / "candidates.json") != candidate:
        raise Refused("candidates.json or its pinned selection changed")
    if (out / "plan.json").exists() or (out / "src").exists():
        raise Refused("plan.json or src already exists")
    all_items = candidate["part_a"] + candidate["pool_p"] + candidate["pool_n"]
    controls = {i["commit"]: control_data(out, i) for i in all_items}
    for item in candidate["part_a"]:
        if controls[item["commit"]] is None:
            raise Refused("%s: part A controls stopped" % item["item"])
    p, walked_p = walk_pool(candidate["pool_p"], controls, "P")
    n, walked_n = walk_pool(candidate["pool_n"], controls, "N")
    part_b_run = len(p) == len(n) == 6
    worker_pin, limits, programs, environment = first.runtime_pins(items, out, worker, None, 1200, 300)
    # The controls were made before this plan: what they ran under must be what the plan pins.
    runtime = out / first.CONTROL_RUNTIME
    if not runtime.exists():
        raise Refused("no %s: what the controls ran under is not recorded" % first.CONTROL_RUNTIME)
    if pilot.load(runtime) != first.control_runtime(limits, programs, environment):
        raise Refused("the controls ran under another runtime than this plan pins (%s): the room's program, the "
            "environment or a limit differs" % first.CONTROL_RUNTIME)
    paths = list(HERE.glob("*.py")) + list(HERE.glob("*.sh")) + [Path(pilot.__file__), SPEC, Path(census),
        items / "list/items.json", tasks / "FROZEN.sha256", out / "candidates.json", runtime]
    paths += [selection / name for name in SELECTION.values()] + [Path(pin["path"]) for pin in programs.values()]
    frozen = {}
    for line in (tasks / "FROZEN.sha256").read_text(encoding="ascii").splitlines():
        hashed, name = line.split()
        path = tasks / name
        if first.digest(path.read_bytes()) != hashed:
            raise Refused("FROZEN.sha256: frozen file changed: " + name)
        frozen[name] = hashed
        paths.append(path)
    chosen = []
    task_text = {}
    for original in part_a:
        item = dict(original)
        task = first.task_path(tasks, item["commit"], "task")
        raw = task.read_bytes()
        if frozen.get(task.name) != first.digest(raw):
            raise Refused("FROZEN.sha256 does not hold the frozen task: " + task.name)
        item.update(part="A", pool=None, task_kind="frozen", message=None)
        chosen.append(item)
        task_text[item["commit"]] = raw
    orders = {i["commit"]: i for pool in ("p", "n")
        for i in pilot.load(selection / ("pool-%s.order.json" % pool))["items"]}
    if part_b_run:
        (out / "messages").mkdir()
        for pool, picked in (("P", p), ("N", n)):
            for original in picked:
                item = dict(original)
                item.pop("n")
                raw = message_bytes(items / "repo", item["commit"])
                path = out / "messages" / (item["item"] + ".txt")
                path.write_bytes(raw)
                paths.append(path)
                item.update(part="B", pool=pool, task_kind="message", plan_group=item.get("plan_group"),
                    matching=item.get("matching", []), direct_path=item.get("direct_path"),
                    message=message_record(raw, orders[item["commit"]]) if pool == "P" else None)
                chosen.append(item)
                task_text[item["commit"]] = raw
    for item in all_items:
        directory = out / "controls" / item["item"]
        paths += [directory / "stopped.json"] if controls[item["commit"]] is None else [directory / "cases.json", directory / "parent.json"]
    inputs = {first.pin_path(path): first.digest(path.read_bytes()) for path in paths}
    for name, hashed in frozen.items():
        if inputs[first.pin_path(tasks / name)] != hashed:
            raise Refused("frozen file changed while preparing bases: " + name)
    src = out / "src"
    src.mkdir()
    first.git_as(src, "init", "-q", "--bare", "--template=")
    listed, _ = pilot.listed(items)
    entries = {e["commit"]: e for e in listed["commits"]}
    for item in chosen:
        entry = entries[item["commit"]]
        ref = "refs/documents-input/" + item["item"]
        first.git(src, "fetch", "-q", "--no-tags", "--no-write-fetch-head", str(items / "repo"),
            "refs/yak-items/%s/base:%s" % (item["commit"], ref))
        if first.git(src, "rev-parse", ref).decode().strip() != entry["base"]:
            raise Refused("%s: item base ref differs from list" % item["item"])
        meta = json.loads(first.git(src, "show", entry["base"] + ":.yak-check/item.json"))
        if meta["parent"] != item["parent"] or first.git(src, "rev-parse", entry["base"] + "^1").decode().strip() != item["parent"]:
            raise Refused("%s: item base parent differs from true parent" % item["item"])
        item.update(task_sha256=first.digest(task_text[item["commit"]]), tests=[t["path"] for t in meta["tests"]],
            kept_out={"reference": entry["reference"], "test_blobs": [t["blob"] for t in meta["tests"]]})
        docs = first.markdown(items / "repo", item["parent"])
        item["documents"] = {path: docs[path]["blob"] for path in item["matching"]}
        first.make_bases(src, item, task_text[item["commit"]], MAY if item["part"] == "A" else BOTH)
    plan = {"v": 2, "seed": SEED, "line": LINE, "spec_sha256": first.digest(SPEC.read_bytes()),
        "list_sha256": candidate["list_sha256"], "selection": candidate["selection"], "part_b_run": part_b_run,
        "walk": {"P": walked_p, "N": walked_n}, "worker": worker_pin, "limits": limits, "programs": programs,
        "environment": environment, "inputs": inputs, "items": chosen, "order": row_order(chosen),
        "items_dir": str(items), "tasks_dir": str(tasks), "census_file": str(Path(census).resolve()),
        "spec_file": str(SPEC), "machine": pilot.machine()}
    for path, hashed in inputs.items():
        if first.digest(first.input_path(path).read_bytes()) != hashed:
            raise Refused("input changed while making bases: " + path)
    for item in chosen:
        path = first.task_path(tasks, item["commit"], "task") if item["part"] == "A" else out / "messages" / (item["item"] + ".txt")
        if inputs[first.pin_path(path)] != item["task_sha256"]:
            raise Refused("%s: task changed while preparing bases" % item["item"])
    if selection_pins(selection) != candidate["selection"]:
        raise Refused("selection changed while making bases")
    pilot.write_json(out / "plan.json", plan)
    (out / "plan.sha256").write_text(first.digest((out / "plan.json").read_bytes()) + "\n", encoding="ascii")
    print("part B frozen: 48 rows; part A: 24 rows" if part_b_run else "part B was not run; part A alone: 24 rows")
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    pick = stages.add_parser("candidates")
    for word in ("items", "selection", "out"):
        pick.add_argument(word)
    make = stages.add_parser("make")
    for word in ("items", "tasks", "selection", "out"):
        make.add_argument(word)
    make.add_argument("--worker", required=True)
    make.add_argument("--census", required=True)
    try:
        args = parser.parse_args(argv)
        if args.stage == "candidates":
            value = candidates(args.items, args.selection, args.out)
            print("candidates frozen: %s part A, %s pool P, %s pool N" %
                (len(value["part_a"]), len(value["pool_p"]), len(value["pool_n"])))
        else:
            make_plan(args.items, args.tasks, args.selection, args.out, args.worker, args.census)
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as error:
        print("REFUSED: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
