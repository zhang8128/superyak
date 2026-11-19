#!/usr/bin/env python3
"""Freeze the document pilot. Python 3.9+, standard library, run with python -I.

inputs keys are relative to this repository's root (including external ../ paths).
Extra runtime pins: items_dir, tasks_dir, census_file, spec_file, programs,
environment, machine; limits also pins lease_secs. No model is run by make/show.
"""
import argparse
import collections
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


pilot = import_file("documents_pilot", HERE.parent / "items/pilot_driver.py")
Refused = pilot.Refused
git = pilot.git
digest = pilot.digest
ROWS = ("nothing-1", "nothing-2", "exists", "path", "search", "newest", "lot", "bm25")
K1 = 1.2
B = 0.75
SEED = 20261118
EXPECTED = {"9a3f21cf", "71a593d5", "d20c739b", "cd884db7", "c9ceb15b", "671a2250",
    "1113f1db", "0193bde8", "fff1b349", "027834bf", "3879e609", "3f349e89"}
SOURCE = "peer/superyak_peer"
CHECK_FILE = ".yak-check/probe.sh"
CHECK_COMMAND = "sh " + CHECK_FILE
TASK_FILE = "TASK.md"
TITLE = "Make the change that TASK.md at the repository's root describes, in the code under peer/superyak_peer."
FIXED = "Make this change in the code under `peer/superyak_peer`. Add tests for it if you like."
WORD = re.compile(r"[a-z][a-z0-9_]{3,}")
ADDED = re.compile(r"^\+\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)|^\+([A-Z][A-Z0-9_]{3,})\s*=")
SPEC = ROOT / "docs/superpowers/specs/2026-11-18-v2-a-document-offered.md"
BLOBS = {}


def distinct_items(commits):
    seen = set()
    for commit in commits:
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise Refused("not forty lowercase commit digits: %r" % commit)
        if commit[:10] in seen:
            raise Refused("items share their first ten characters: " + commit[:10])
        seen.add(commit[:10])


def census_passes(path):
    found = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        words = line.split()
        if len(words) >= 5 and words[-1] == "passed" and words[-3] == "0":
            found.add(words[0])
    return found


def tree_files(repo, commit):
    found = {}
    for line in git(repo, "ls-tree", "-rz", commit).split(b"\0"):
        if line:
            meta, path = line.split(b"\t", 1)
            mode, kind, blob = meta.split()
            if kind == b"blob" and mode in (b"100644", b"100755"):
                found[path.decode("utf-8")] = blob.decode("ascii")
    return found


def read_blobs(repo, blobs):
    missing = sorted(set(blobs) - BLOBS.keys())
    if missing:
        raw = git_as(repo, "cat-file", "--batch", data=("\n".join(missing) + "\n").encode("ascii"))
        at = 0
        for blob in missing:
            end = raw.index(b"\n", at)
            size = int(raw[at:end].split()[2])
            at = end + 1
            BLOBS[blob] = raw[at:at + size].decode("utf-8", "replace")
            at += size + 1
    return {b: BLOBS[b] for b in blobs}


def markdown(repo, parent):
    files = {p: b for p, b in tree_files(repo, parent).items() if p.endswith(".md")}
    texts = read_blobs(repo, files.values())
    return {path: {"blob": blob, "text": texts[blob]} for path, blob in files.items()}


def under(path, folder):
    return folder in path.split("/")[:-1]


def has_word(text, name):
    return re.search(r"\b" + re.escape(name) + r"\b", text) is not None


def matching_documents(diff, parent_source, docs):
    # Rule 2 reads names as def/class/async def at any indent, or an unindented
    # UPPER_CASE assignment (the earlier ceiling probe's rule). Eight characters
    # includes digits and underscores; __ prefixes are excluded.
    names = set()
    for line in diff.splitlines():
        match = ADDED.match(line)
        if match:
            name = match.group(1) or match.group(2)
            if len(name) >= 8 and "_" in name[1:-1] and not name.startswith("__") and not has_word(parent_source, name):
                names.add(name)
    held = collections.defaultdict(set)
    for name in names:
        paths = [p for p in docs if has_word(docs[p]["text"], name)]
        if len(paths) <= 5:
            for path in paths:
                if under(path, "plans") or under(path, "specs"):
                    held[path].add(name)
    return held


def select_items(repo, entries, passing, exclude_test_functions=True):
    selected = []
    for entry in entries:
        commit = entry["commit"]
        if commit not in passing or not isinstance(entry.get("reference"), str):
            continue
        parent = git(repo, "rev-parse", commit + "^1").decode().strip()
        diff = git(repo, "diff", "--no-ext-diff", "--no-textconv", parent, commit, "--", SOURCE).decode("utf-8", "replace")
        # Avoid reading every Markdown blob at parents with no qualifying additions.
        if not ADDED.search(diff) and not any(ADDED.match(line) for line in diff.splitlines()):
            continue
        files = tree_files(repo, parent)
        source_blobs = [b for p, b in files.items() if p.startswith(SOURCE + "/")]
        source = "\n".join(read_blobs(repo, source_blobs).values())
        docs = markdown(repo, parent)
        held = matching_documents(diff, source, docs)
        # Rule 3 includes indented def test_ lines, but not async def test_.
        if not held or (exclude_test_functions and any(re.search(r"^\s*def test_", docs[p]["text"], re.M) for p in held)):
            continue
        direct = min(held, key=lambda p: (not under(p, "plans"), -len(held[p]), p.encode("utf-8")))
        selected.append({"commit": commit, "item": commit[:10], "parent": parent,
            "probed_before": commit.startswith("027834bf"), "plan_group": direct,
            "direct_path": direct, "matching": sorted(held, key=lambda p: p.encode("utf-8"))})
    return selected


def bm25_scores(frequencies, use, df):
    """Score the search's used words, counting all document word occurrences."""
    lengths = {p: sum(counts.values()) for p, counts in frequencies.items()}
    count = len(frequencies)
    average = sum(lengths.values()) / count or 1
    return {p: round(sum(math.log(1 + (count - df[w] + 0.5) / (df[w] + 0.5))
        * counts[w] * (K1 + 1) / (counts[w] + K1 * (1 - B + B * lengths[p] / average))
        for w in sorted(use)), 9) for p, counts in frequencies.items()}


def rank_documents(docs, query, matching, commit):
    frequencies = {p: collections.Counter(WORD.findall(d["text"].lower())) for p, d in docs.items()}
    counts = {p: set(f) for p, f in frequencies.items()}
    words = set(WORD.findall(query.decode("utf-8").lower()))
    df = collections.Counter(w for p in counts for w in words & counts[p])
    use = {w for w in words if df[w] <= len(docs) / 2}
    scores = {p: len(use & counts[p]) for p in docs}
    search = sorted(docs, key=lambda p: (-scores[p], p.encode("utf-8")))
    best = min(search.index(p) for p in matching)
    newest = sorted((p for p in docs if under(p, "plans")),
        key=lambda p: (p.rsplit("/", 1)[-1].encode("utf-8"), p.encode("utf-8")), reverse=True)
    lot = sorted((p for p in docs if (under(p, "plans") or under(p, "specs")) and p not in matching),
        key=lambda p: digest(("%s:lot:%s:%s" % (SEED, commit, p)).encode("ascii")))
    if min(len(search), len(newest), len(lot)) < 3:
        raise Refused("%s: fewer than three candidate documents" % commit)
    bm25 = bm25_scores(frequencies, use, df)
    second_search = sorted(docs, key=lambda p: (-bm25[p], p.encode("utf-8")))
    second_best = min(second_search.index(p) for p in matching)
    return {"search": {"three": search[:3], "best_place": best + 1,
            "tied": sum(scores[p] == scores[search[best]] for p in docs)},
        "newest": {"three": newest[:3], "best_place": min(newest.index(p) for p in matching if p in newest) + 1},
        "lot": {"three": lot[:3]},
        "bm25": {"three": second_search[:3], "best_place": second_best + 1,
            "tied": sum(bm25[p] == bm25[second_search[second_best]] for p in docs)}}


def paragraphs(item):
    result = {"nothing-1": "", "nothing-2": "", "exists": "There is a plan for this work in the repository.",
        "path": "The plan for this work is in the repository at `%s`." % item["direct_path"]}
    for name in ("search", "newest", "lot", "bm25"):
        result[name] = "These documents in the repository may bear on this work:\n" + "\n".join(
            "- `%s`" % path for path in item[name]["three"])
    return result


def task_bytes(task, paragraph):
    separator = b"\n" if task.endswith(b"\n") else b"\n\n"
    common = task + separator + FIXED.encode("utf-8") + b"\n"
    return common + (("\n" + paragraph + "\n").encode("utf-8") if paragraph else b"")


def row_order(commits):
    rows = [{"commit": c, "item": c[:10], "row": r,
        "hash": digest(("%s:order:%s:%s" % (SEED, c, r)).encode("ascii"))} for c in commits for r in ROWS]
    rows.sort(key=lambda r: r["hash"])
    for n, row in enumerate(rows, 1):
        row.update(n=n, directory="rows/%03d-%s-%s" % (n, row["item"], row["row"]))
    return rows


def git_as(repo, *words, data=None, index=None):
    environment = {"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@invalid",
        "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@invalid",
        "GIT_AUTHOR_DATE": "2026-11-18T00:00:00Z", "GIT_COMMITTER_DATE": "2026-11-18T00:00:00Z"}
    if index is not None:
        environment["GIT_INDEX_FILE"] = str(index)
    return pilot.command(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "-c", "commit.gpgsign=false", "-C", repo, *words], input=data, env=environment)


def check_script(parent):
    return ("#!/bin/sh\ngit -c core.fsmonitor=false diff --quiet %s HEAD -- %s\n"
        "status=$?\nif [ \"$status\" -eq 1 ]; then\n echo ok\n exit 0\nfi\n"
        "echo 'FAIL: source difference not established' >&2\nexit 1\n" % (parent, SOURCE)).encode("ascii")


def make_bases(src, item, task, rows=None):
    index = src.parent / "index.tmp"
    item["rows"] = {}
    for name, paragraph in (paragraphs(item) if rows is None else rows).items():
        git_as(src, "read-tree", item["parent"], index=index)
        content = task_bytes(task, paragraph)
        for path, data in ((CHECK_FILE, check_script(item["parent"])), (TASK_FILE, content)):
            blob = git_as(src, "hash-object", "-w", "--stdin", data=data).decode().strip()
            git_as(src, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path), index=index)
        tree = git_as(src, "write-tree", index=index).decode().strip()
        base = git_as(src, "commit-tree", tree, "-p", item["parent"], "-m", "document pilot base").decode().strip()
        other = git_as(src, "hash-object", "-w", "--stdin", data=b"not the work\n").decode().strip()
        git_as(src, "update-index", "--add", "--cacheinfo", "100644,%s,PROBE-UNRELATED.txt" % other, index=index)
        wrong_tree = git_as(src, "write-tree", index=index).decode().strip()
        wrong = git_as(src, "commit-tree", wrong_tree, "-p", base, "-m", "document pilot wrong").decode().strip()
        ref = "refs/documents/%s/%s" % (item["item"], name)
        git_as(src, "update-ref", ref, base)
        git_as(src, "update-ref", ref + "-wrong", wrong)
        item["rows"][name] = {"paragraph": paragraph, "base": base, "wrong": wrong, "task_file_sha256": digest(content)}
    index.unlink()
    prove_bases(src, item, task, rows)


def prove_bases(src, item, task, rows=None):
    first = item["rows"][next(iter(item["rows"]))]["base"]
    paragraphs_by_name = {name: row["paragraph"] for name, row in item["rows"].items()} if rows is None else rows
    for name, paragraph in paragraphs_by_name.items():
        row = item["rows"][name]
        parent = git(src, "show", "-s", "--format=%P", row["base"]).decode().strip()
        if parent != item["parent"]:
            raise Refused("%s/%s: base parent differs: %s" % (item["item"], name, parent))
        changed = set(git(src, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", first, row["base"]).split(b"\0")) - {b""}
        if changed - {b"TASK.md"}:
            raise Refused("%s/%s: bases differ outside TASK.md: %r" % (item["item"], name, changed))
        actual = git(src, "show", row["base"] + ":TASK.md")
        if actual != task_bytes(task, paragraph) or digest(actual) != row["task_file_sha256"]:
            raise Refused("%s/%s: TASK.md differs from frozen task and paragraph" % (item["item"], name))


def pin_path(path):
    return os.path.relpath(Path(path).absolute(), ROOT)


def input_path(path):
    return ROOT / path


def task_path(tasks, commit, kind):
    found = [p for p in Path(tasks).glob("*." + kind + ".md") if commit.startswith(p.name.split(".")[0])]
    if len(found) != 1:
        raise Refused("%s: expected one %s file, found %d" % (commit, kind, len(found)))
    return found[0]


def runtime_pins(items, out, worker, worker_secs, replay_secs, diagnostic_secs):
    yak = pilot.settings(items, out)
    environment = {k: os.environ.get(k, "") for k in ("HOME", "USER", "LOGNAME")}
    environment.update(SHELL=os.environ.get("SHELL", "/bin/sh"), LANG="en_US.UTF-8", TERM="dumb",
        PATH=os.environ["YAK_PROBE_PATH"], YAK_JAIL_READ=os.environ["YAK_JAIL_READ"])
    environment.update({k: os.environ[k] for k in ("SDKROOT", "TMPDIR") if os.environ.get(k)})
    family, _, model = worker.partition(":")
    if family not in ("script", "claude", "codex") or not model or any(c.isspace() for c in worker):
        raise Refused("worker must be script:path, claude:model or codex:model: %r" % worker)
    if family == "script" and not os.path.isabs(model):
        raise Refused("script worker path must be absolute: " + model)
    path = model if family == "script" else shutil.which(family, path=environment["PATH"])
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise Refused("worker program missing: %r" % path)
    version = "script" if family == "script" else pilot.command([path, "--version"], env=environment).decode().strip()
    if not version:
        raise Refused("worker version is empty: " + str(path))
    helped = pilot.command([yak, "clock", "run", "--help"], env=environment).decode()
    defaults = {}
    for name in ("turn-secs", "lease-secs"):
        match = re.search(r"--" + name + r" <[A-Z_]+>\s+\[default: (\d+)\]", helped)
        if not match:
            raise Refused("room help has no default for --" + name)
        defaults[name] = int(match.group(1))
    limits = {"worker_secs": defaults["turn-secs"] if worker_secs is None else worker_secs,
        "check_secs": 900, "replay_secs": replay_secs, "diagnostic_secs": diagnostic_secs,
        "lease_secs": defaults["lease-secs"]}
    if any(type(n) is not int or n <= 0 for n in limits.values()):
        raise Refused("limits must be positive integers: %r" % limits)
    programs = {"yak": {"path": yak}, "worker": {"path": str(Path(path).absolute())}}
    for p in programs.values():
        p["sha256"] = digest(Path(p["path"]).read_bytes())
    return {"name": worker, "version": version, "model": "script" if family == "script" else model}, limits, programs, environment


CONTROL_LIMITS = ("check_secs", "replay_secs", "diagnostic_secs", "lease_secs")
CONTROL_RUNTIME = "controls-runtime.json"


def control_runtime(limits, programs, environment):
    """What a control's turns run under: the limits a control uses, the room's program and the environment. The
    worker's pin and its own limit are left out, since no control uses them."""
    return {"limits": {key: limits[key] for key in CONTROL_LIMITS}, "yak": dict(programs["yak"]),
        "environment": dict(environment)}


def make_plan(items, tasks, out, worker, census, worker_secs=None, replay_secs=1200, diagnostic_secs=300,
        expected=EXPECTED, expected_list_sha256="4b25d330"):
    items, tasks, out = Path(items).resolve(), Path(tasks).resolve(), Path(out).absolute()
    for directory in (out, *out.parents):
        if not directory.exists() and re.search(r"[0-9a-fA-F]{32}", directory.name):
            raise Refused("directory name holds 32 hexadecimal characters: " + directory.name)
    data, raw = pilot.listed(items)
    list_sha256 = digest(raw)
    if not list_sha256.startswith(expected_list_sha256):
        raise Refused("items.json sha256 differs: expected %s, found %s" % (expected_list_sha256, list_sha256))
    selected = select_items(items / "repo", data["commits"], census_passes(census))
    distinct_items([i["commit"] for i in selected])
    if expected is not None and ({i["commit"][:8] for i in selected} != expected or len(selected) != len(expected)):
        raise Refused("selected cohort differs from spec: " + ", ".join(i["commit"] for i in selected))
    worker_pin, limits, programs, environment = runtime_pins(items, out, worker, worker_secs, replay_secs, diagnostic_secs)
    paths = list(HERE.glob("*.py")) + list(HERE.glob("*.sh")) + [Path(pilot.__file__), SPEC, Path(census), items / "list/items.json"]
    paths += [Path(p["path"]) for p in programs.values()]
    entries = {e["commit"]: e for e in data["commits"]}
    frozen_tasks = {}
    for item in selected:
        commit = item["commit"]
        facts, task = task_path(tasks, commit, "facts"), task_path(tasks, commit, "task")
        paths += [facts, task]
        frozen_tasks[commit] = task.read_bytes()
        item.update(facts_sha256=digest(facts.read_bytes()), task_sha256=digest(frozen_tasks[commit]), query_sha256=digest(frozen_tasks[commit]))
        docs = markdown(items / "repo", item["parent"])
        item.update(rank_documents(docs, frozen_tasks[commit], item["matching"], commit))
        offered = set(item["matching"]) | {p for k in ("search", "newest", "lot", "bm25") for p in item[k]["three"]}
        item["documents"] = {p: docs[p]["blob"] for p in sorted(offered)}
    for item in selected:
        if task_path(tasks, item["commit"], "task").read_bytes() != frozen_tasks[item["commit"]]:
            raise Refused("%s: task changed during search" % item["item"])
    out = pilot.new_output(out)
    src = out / "src"
    src.mkdir()
    git_as(src, "init", "-q", "--bare", "--template=")
    for item in selected:
        commit = item["commit"]
        entry = entries[commit]
        git(src, "fetch", "-q", "--no-tags", "--no-write-fetch-head", str(items / "repo"),
            "refs/yak-items/%s/base:refs/documents-input/%s" % (commit, item["item"]))
        actual = git(src, "rev-parse", "refs/documents-input/%s" % item["item"]).decode().strip()
        if actual != entry["base"]:
            raise Refused("%s: item base ref differs from list: %s" % (commit, actual))
        meta = json.loads(git(src, "show", entry["base"] + ":.yak-check/item.json"))
        if meta["parent"] != item["parent"] or git(src, "rev-parse", entry["base"] + "^1").decode().strip() != item["parent"]:
            raise Refused("%s: item base parent differs from true parent" % commit)
        item.update(tests=[t["path"] for t in meta["tests"]],
            kept_out={"reference": entry["reference"], "test_blobs": [t["blob"] for t in meta["tests"]]})
        make_bases(src, item, frozen_tasks[commit])
    plan = {"v": 1, "seed": SEED, "spec_sha256": digest(SPEC.read_bytes()), "list_sha256": list_sha256,
        "worker": worker_pin, "limits": limits, "inputs": {pin_path(p): digest(p.read_bytes()) for p in paths},
        "items": selected, "order": row_order([i["commit"] for i in selected]), "items_dir": str(items),
        "tasks_dir": str(tasks), "census_file": str(Path(census).resolve()), "spec_file": str(SPEC),
        "programs": programs, "environment": environment, "machine": pilot.machine()}
    for item in selected:
        for kind in ("facts", "task"):
            path = task_path(tasks, item["commit"], kind)
            if plan["inputs"][pin_path(path)] != item[kind + "_sha256"]:
                raise Refused("%s: %s changed while making bases" % (item["item"], kind))
    pilot.write_json(out / "plan.json", plan)
    (out / "plan.sha256").write_text(digest((out / "plan.json").read_bytes()) + "\n", encoding="ascii")
    return plan


def load_plan(out):
    out = Path(out)
    raw = (out / "plan.json").read_bytes()
    if digest(raw) != (out / "plan.sha256").read_text(encoding="ascii").strip():
        raise Refused("plan.json hash changed")
    plan = json.loads(raw)
    for path, expected in sorted(plan["inputs"].items()):
        try:
            actual = digest(input_path(path).read_bytes())
        except OSError:
            raise Refused("input missing: " + path) from None
        if actual != expected:
            raise Refused("input changed: " + path)
    family = plan["worker"]["name"].split(":", 1)[0]
    if family != "script":
        found = shutil.which(family, path=plan["environment"]["PATH"])
        if not found or str(Path(found).absolute()) != plan["programs"]["worker"]["path"]:
            raise Refused("worker lookup changed: " + family)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    make = stages.add_parser("make")
    for word in ("items", "tasks", "out"):
        make.add_argument(word)
    make.add_argument("--worker", required=True)
    make.add_argument("--census", required=True)
    make.add_argument("--worker-secs", type=int)
    make.add_argument("--replay-secs", type=int, default=1200)
    make.add_argument("--diagnostic-secs", type=int, default=300)
    stages.add_parser("show").add_argument("out")
    try:
        args = parser.parse_args(argv)
        if args.stage == "make":
            plan = make_plan(args.items, args.tasks, args.out, args.worker, args.census,
                args.worker_secs, args.replay_secs, args.diagnostic_secs)
        else:
            plan = load_plan(args.out)
        print(json.dumps(plan, sort_keys=True, indent=1))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as error:
        print("REFUSED: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
