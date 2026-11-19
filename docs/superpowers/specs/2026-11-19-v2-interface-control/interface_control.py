"""The interface control (README.md beside this file, committed before any run at 740ef4b2).

  python3 -I interface_control.py check <repo> <cases.json> <out> [--items a,b]   checks A and B
  python3 -I interface_control.py make  <repo> <cases.json> <out>                 the interfaces, imported
  python3 -I interface_control.py run   <repo> <cases.json> <out>                 check C and the run, once
  python3 -I interface_control.py read  <cases.json> <out>                        the tables

Standard library only. The tests run under the peer's virtual environment (PYTHON below), from a tree exported from
the repository's history, never from a working checkout.
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

SRC = "peer/superyak_peer"
CASES_SHA256 = "07e9d27b6a685761580da09016cc007fe75973d6d291a0d9f9b3ea8e73d81263"
PYTHON = "/home/doctor/Projects/superyak/peer/.venv/bin/python"
LIMIT = 1200
CAP = ["/usr/bin/prlimit", "--as=%d" % (3 * 1024 ** 3), "--"]     # README, "A memory cap"
WORKERS = 2
STATUS_ORDER = ("passed", "skipped", "failed", "error")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def load_cases(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CASES_SHA256:
        raise SystemExit("cases.json is not the pinned one (sha256 %s)" % CASES_SHA256)
    return json.loads(raw)


# ---------------------------------------------------------------- trees

def export(repo, commit, dest, paths=()):
    data = git(repo, "archive", "--format=tar", commit, *paths)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(dest, filter="data")


def make_tree(repo, item, dest, at):
    """`at` is "parent" (the parent with the item's test files from the commit) or "commit" (that, with the commit's
    source directory in place of the parent's)."""
    export(repo, item["parent"], dest)
    for path in item["tests"]:
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git(repo, "show", "%s:%s" % (item["commit"], path)))
    if at == "commit":
        shutil.rmtree(dest / SRC)
        export(repo, item["commit"], dest, (SRC,))
    return dest


# ---------------------------------------------------------------- running the tests

def environment(tree, home):
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home), "PYTHONPATH": str(tree / "peer"),
        "PYTHONDONTWRITEBYTECODE": "1"}


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:300]
    return ""


def read_junit(data):
    """pytest's JUnit report -> ({id: (status, first line)}, [collection errors]), as the pilots' first judge reads it:
    id `classname::name`, a collection error a testcase with no classname and an error, the worst status standing."""
    if not data.strip():
        return {}, []
    root = ElementTree.fromstring(data)
    cases, collection = {}, []
    for case in root.iter("testcase"):
        classname, name = case.get("classname") or "", case.get("name") or ""
        found = {child.tag: child for child in case}
        if not classname and "error" in found:
            collection.append("%s: %s" % (name, first_line(found["error"].get("message"))))
            continue
        status = next((tag for tag in ("error", "failure", "skipped") if tag in found), "passed")
        status = "failed" if status == "failure" else status
        element = found.get({"failed": "failure"}.get(status, status))
        line = "" if element is None else (first_line(element.get("message")) or first_line(element.text))
        key = "%s::%s" % (classname, name)
        if key not in cases or STATUS_ORDER.index(status) > STATUS_ORDER.index(cases[key][0]):
            cases[key] = (status, line)
    return cases, collection


def run_tests(tree, item):
    """The item's tests at `tree`, one pytest run. Refuses a run whose superyak_peer is not the tree's own."""
    home = Path(tempfile.mkdtemp(prefix="ifc-home-"))
    try:
        env = environment(tree, home)
        where = subprocess.run([PYTHON, "-c", "import superyak_peer; print(superyak_peer.__file__)"], cwd=tree / "peer",
            env=env, capture_output=True, text=True)
        imported = where.stdout.strip()
        if not imported.startswith(str(tree / "peer") + os.sep):
            raise SystemExit("%s: superyak_peer imported from %r, not the tree" % (item["commit"][:8], imported))
        report = home / "junit.xml"
        tests = [path[len("peer/"):] for path in item["tests"]]
        began = time.monotonic()
        try:
            done = subprocess.run(CAP + [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "-rfE",
                "--junitxml=" + str(report), *tests], cwd=tree / "peer", env=env, capture_output=True, text=True,
                timeout=LIMIT, start_new_session=True, stdin=subprocess.DEVNULL)
            exit_code, limit = done.returncode, False
            tail = done.stdout[-3000:]
        except subprocess.TimeoutExpired:
            exit_code, limit, tail = None, True, ""
        cases, collection = read_junit(report.read_bytes() if report.exists() else b"")
        return {"exit": exit_code, "limit": limit, "seconds": round(time.monotonic() - began, 1), "cases": cases,
            "collection_errors": collection, "tail": tail}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def passing(ran, frozen):
    return sorted(case for case in frozen if ran["cases"].get(case, ("",))[0] == "passed")


# ---------------------------------------------------------------- check A and B

def check_item(repo, key, item, out):
    record = {"item": key, "commit": item["commit"], "parent": item["parent"]}
    for at in ("parent", "commit"):
        with tempfile.TemporaryDirectory(prefix="ifc-tree-") as scratch:
            tree = make_tree(repo, item, Path(scratch), at)
            ran = run_tests(tree, item)
        got = passing(ran, item["frozen"])
        record["at_" + at] = {"exit": ran["exit"], "limit": ran["limit"], "seconds": ran["seconds"], "passed": got,
            "collection_errors": ran["collection_errors"],
            "not_passing": {case: list(ran["cases"].get(case, ("not run", ""))) for case in item["frozen"]
                if case not in got}}
    wanted = sorted(item["pass_on_the_parent"])
    record["A"] = record["at_parent"]["passed"] == wanted
    record["A_differs"] = {"extra": sorted(set(record["at_parent"]["passed"]) - set(wanted)),
        "missing": sorted(set(wanted) - set(record["at_parent"]["passed"]))}
    record["B"] = record["at_commit"]["passed"] == sorted(item["frozen"])
    (out / "checks").mkdir(parents=True, exist_ok=True)
    (out / "checks" / ("%s.json" % key)).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    return record


def check(repo, cases_path, out, only):
    items = load_cases(cases_path)["items"]
    keys = sorted(items)
    if only:
        keys = [key for key in keys if any(key.startswith(prefix) for prefix in only)]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for record in pool.map(lambda key: check_item(repo, key, items[key], out), keys):
            item = items[record["item"]]
            print("%s A %s B %s  parent %d/%d (want %d)  commit %d/%d  %ss+%ss" % (record["item"],
                "ok" if record["A"] else "NO", "ok" if record["B"] else "NO", len(record["at_parent"]["passed"]),
                len(item["frozen"]), len(item["pass_on_the_parent"]), len(record["at_commit"]["passed"]),
                len(item["frozen"]), record["at_parent"]["seconds"], record["at_commit"]["seconds"]), flush=True)


# ---------------------------------------------------------------- the interface

import ast
import difflib

WORD = re.compile(r"[A-Za-z0-9_]+", re.A)
STUB = 'raise NotImplementedError("interface control")'


def words(text):
    return set(WORD.findall(text))


def holds_string(node):
    """A string or bytes constant anywhere in the node (f-strings included)."""
    return node is not None and any(isinstance(sub, (ast.Constant,)) and isinstance(sub.value, (str, bytes))
        or isinstance(sub, ast.JoinedStr) for sub in ast.walk(node))


def top_names(tree):
    """Module-level names: def, async def, class, and names assigned by = or by an annotation with a value."""
    found = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.setdefault(target.id, node)
        elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            found.setdefault(node.target.id, node)
    return found


def methods(cls):
    return {node.name: node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def bare_args(args):
    """The parameters with their defaults and no annotations."""
    args = ast.parse("def f(%s): pass" % ast.unparse(args)).body[0].args
    for arg in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
        if arg is not None:
            arg.annotation = None
    return ast.unparse(args)


def segment(source, node):
    return ast.get_source_segment(source, node)


def function_stub(source, node, indent):
    lines = ["%s@%s" % (indent, segment(source, dec)) for dec in node.decorator_list]
    lines.append("%s%sdef %s(%s):" % (indent, "async " if isinstance(node, ast.AsyncFunctionDef) else "", node.name,
        bare_args(node.args)))
    lines.append(indent + "    " + STUB)
    return lines


def value_stub(source, node, indent):
    """A module- or class-level assignment: the commit's statement when its value holds no string, else the name
    alone (a class-level annotation keeps its annotation)."""
    value = node.value
    if not holds_string(value):
        lines = segment(source, node).splitlines()          # continuation lines keep the commit's own indent
        return [indent + lines[0]] + lines[1:]
    if isinstance(node, ast.AnnAssign):
        return ["%s%s: %s = NotImplemented" % (indent, ast.unparse(node.target), segment(source, node.annotation))]
    return ["%s%s = NotImplemented" % (indent, " = ".join(ast.unparse(target) for target in node.targets))]


def class_stub(source, node, indent):
    heads = [segment(source, base) for base in node.bases] + [segment(source, k) for k in node.keywords]
    lines = ["%s@%s" % (indent, segment(source, dec)) for dec in node.decorator_list]
    lines.append("%sclass %s%s:" % (indent, node.name, "(%s)" % ", ".join(heads) if heads else ""))
    inner = indent + "    "
    body = []
    for sub in node.body:
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body += function_stub(source, sub, inner)
        elif isinstance(sub, ast.ClassDef):
            body += class_stub(source, sub, inner)
        elif isinstance(sub, ast.Assign) or (isinstance(sub, ast.AnnAssign) and sub.value is not None):
            body += value_stub(source, sub, inner)
        elif isinstance(sub, ast.AnnAssign):
            body.append("%s%s: %s" % (inner, ast.unparse(sub.target), segment(source, sub.annotation)))
    return lines + (body or [inner + "pass"])


def needs(source, node):
    """The words of what a given part needs at import: decorators, bases, defaults, a copied value."""
    parts = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        parts += node.decorator_list
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        parts += [d for d in node.args.defaults + node.args.kw_defaults if d is not None]
    if isinstance(node, ast.ClassDef):
        parts += node.bases + [k.value for k in node.keywords]
        for sub in node.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
                parts.append(sub)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        parts += [node.value] if not holds_string(node.value) else []
        if isinstance(node, ast.AnnAssign) and holds_string(node.value):
            parts.append(node.annotation)
    found = set()
    for part in parts:
        if isinstance(part, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
            found |= needs(source, part)
        else:
            found |= words(segment(source, part) or ast.unparse(part))
    return found


def imports_bound(node):
    return [(alias.asname or alias.name).split(".")[0] for alias in node.names]


def interface(repo, item):
    """{path: new text} for every changed Python file under SRC that gains a given part, and the parts given."""
    parent, commit = item["parent"], item["commit"]
    changed = git(repo, "diff", "--name-only", "--no-renames", parent, commit, "--", SRC).decode().split()
    test_words = set()
    for path in item["tests"]:
        test_words |= words(git(repo, "show", "%s:%s" % (commit, path)).decode("utf-8", "replace"))
    modules = {}
    for path in changed:
        if not path.endswith(".py"):
            continue
        try:
            after = git(repo, "show", "%s:%s" % (commit, path)).decode()
        except subprocess.CalledProcessError:
            continue                                              # deleted by the commit
        try:
            before = git(repo, "show", "%s:%s" % (parent, path)).decode()
        except subprocess.CalledProcessError:
            before = None                                         # a new module
        modules[path] = (before, after)
    # every added part, as (path, kind, name, class, node)
    added = []
    for path, (before, after) in modules.items():
        old_tree, new_tree = (ast.parse(before) if before is not None else ast.Module(body=[])), ast.parse(after)
        old_top, new_top = top_names(old_tree), top_names(new_tree)
        for name, node in new_top.items():
            if name not in old_top:
                added.append((path, "top", name, None, node))
        for name, node in new_top.items():
            if isinstance(node, ast.ClassDef) and isinstance(old_top.get(name), ast.ClassDef):
                old_methods = methods(old_top[name])
                for method, sub in methods(node).items():
                    if method not in old_methods:
                        added.append((path, "method", method, name, sub))
    given, wanted, grew = set(), set(test_words), True
    while grew:
        grew = False
        for part in added:
            path, kind, name, owner, node = part
            if part[:4] not in given and name in wanted:
                given.add(part[:4])
                wanted |= needs(modules[path][1], node)
                grew = True
    texts, listed = {}, []
    for path, (before, after) in modules.items():
        parts = [part for part in added if part[0] == path and part[:4] in given]
        if not parts:
            continue
        new_tree = ast.parse(after)
        old_tree = ast.parse(before) if before is not None else ast.Module(body=[])
        old_imports = {ast.dump(node) for node in old_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))}
        part_needs = set()
        for part in parts:
            part_needs |= needs(after, part[4])
        imports = [node for node in new_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
            and ast.dump(node) not in old_imports and set(imports_bound(node)) & part_needs]
        lines = (before or "").splitlines()
        # Every insertion as (after this line, lines), applied from the lowest so earlier line numbers stand: the
        # added imports after the parent's leading imports (a default or a decorator may need one when its class is
        # made), and each class's new methods at its end.
        insertions = []
        leading = 0
        for index, node in enumerate(old_tree.body):
            docstring = index == 0 and isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None),
                ast.Constant) and isinstance(node.value.value, str)
            if not (docstring or isinstance(node, (ast.Import, ast.ImportFrom))):
                break
            leading = node.end_lineno
        if imports:
            insertions.append((leading, ["# The interface control: imports the commit adds that a given part needs."]
                + [segment(after, node) for node in imports]))
        old_top = top_names(old_tree)
        for owner in sorted({part[3] for part in parts if part[1] == "method"}):
            cls = old_top[owner]
            indent = " " * cls.body[0].col_offset
            stubs = []
            for sub in top_names(new_tree)[owner].body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and (path, "method", sub.name, owner) in given:
                    stubs += [""] + function_stub(after, sub, indent)
            insertions.append((cls.end_lineno, stubs))
        for line, block in sorted(insertions, key=lambda held: held[0], reverse=True):
            lines[line:line] = block
        tail = []
        for node in new_tree.body:
            name = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
            elif isinstance(node, ast.Assign):
                name = next((t.id for t in node.targets if isinstance(t, ast.Name)), None)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
            if name is None or (path, "top", name, None) not in given:
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                tail += [""] + function_stub(after, node, "")
            elif isinstance(node, ast.ClassDef):
                tail += [""] + class_stub(after, node, "")
            else:
                tail += value_stub(after, node, "")
        if tail:
            lines += ["", "", "# The interface control: names the commit adds, with no bodies."] + tail
        texts[path] = "\n".join(lines) + "\n"
        listed += ["%s %s%s" % (path.split("/")[-1], "" if part[3] is None else part[3] + ".", part[2])
            for part in sorted(parts, key=lambda part: (part[3] or "", part[2]))]
    return texts, sorted(listed), sorted("%s %s%s" % (p[0].split("/")[-1], "" if p[3] is None else p[3] + ".", p[2])
        for p in added)


def as_patch(repo, parent, texts):
    out = []
    for path, text in sorted(texts.items()):
        try:
            before = git(repo, "show", "%s:%s" % (parent, path)).decode()
            old_name = "a/" + path
        except subprocess.CalledProcessError:
            before, old_name = "", "/dev/null"
        out += difflib.unified_diff(before.splitlines(True), text.splitlines(True), old_name, "b/" + path)
    return "".join(out)


def make_item(repo, key, item, out):
    texts, given, added = interface(repo, item)
    patch = as_patch(repo, item["parent"], texts)
    record = {"item": key, "given": given, "added": added, "files": sorted(texts), "imports": {}}
    with tempfile.TemporaryDirectory(prefix="ifc-tree-") as scratch:
        tree = make_tree(repo, item, Path(scratch), "parent")
        if patch:
            done = subprocess.run(["patch", "-p1", "-s", "--no-backup-if-mismatch"], input=patch.encode(), cwd=tree,
                capture_output=True)
            record["applied"] = done.returncode == 0
            record["apply_error"] = (done.stdout + done.stderr).decode()[-500:]
        else:
            record["applied"] = True
        home = Path(tempfile.mkdtemp(prefix="ifc-home-"))
        try:
            for path in sorted(texts):
                module = path[len("peer/"):-len(".py")].replace("/", ".")
                done = subprocess.run([PYTHON, "-c", "import %s" % module], cwd=tree / "peer",
                    env=environment(tree, home), capture_output=True, text=True)
                record["imports"][module] = "ok" if done.returncode == 0 else first_line(done.stderr.splitlines()[-1]
                    if done.stderr.strip() else "exit %d" % done.returncode)
        finally:
            shutil.rmtree(home, ignore_errors=True)
    (out / "interfaces").mkdir(parents=True, exist_ok=True)
    (out / "interfaces" / ("%s.patch" % key)).write_text(patch)
    record["patch_sha256"] = hashlib.sha256(patch.encode()).hexdigest()
    (out / "interfaces" / ("%s.json" % key)).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    return record


def make(repo, cases_path, out, only):
    items = load_cases(cases_path)["items"]
    keys = [key for key in sorted(items) if not only or any(key.startswith(prefix) for prefix in only)]
    for key in keys:
        record = make_item(repo, key, items[key], out)
        bad = {module: said for module, said in record["imports"].items() if said != "ok"}
        print("%s given %d of %d added, %d files, applied %s, imports %s" % (key, len(record["given"]),
            len(record["added"]), len(record["files"]), record["applied"], "ok" if not bad else bad), flush=True)


# ---------------------------------------------------------------- the run, once

SIGNATURE = re.compile(r"unexpected keyword|got an unexpected|missing \d+ required|takes \d+ positional|"
    r"takes from \d+ to \d+ positional|positional arguments? but \d+")


def test_function(repo, item, case):
    """The test function's AST node for a case `classname::name`, at the commit, or None."""
    classname, name = case.split("::", 1)
    name = name.split("[", 1)[0]
    for path in item["tests"]:
        module = path[len("peer/"):-len(".py")].replace("/", ".")
        if classname == module or classname.startswith(module + "."):
            tree = ast.parse(git(repo, "show", "%s:%s" % (item["commit"], path)).decode())
            scope = tree.body
            for part in classname[len(module) + 1:].split(".") if classname != module else []:
                scope = next((node.body for node in scope if isinstance(node, ast.ClassDef) and node.name == part), [])
            return next((node for node in scope if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name), None)
    return None


def body_strings(node):
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return {sub.value for statement in body for sub in ast.walk(statement)
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and len(sub.value) >= 4}


def commit_strings(repo, item):
    """(the text of every line the commit adds under SRC, the bytes of every file under SRC at the parent)."""
    diff = git(repo, "diff", "--no-color", "--no-ext-diff", "--no-renames", "-U0", item["parent"], item["commit"],
        "--", SRC).decode("utf-8", "replace")
    added = "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    parent = b"\n".join(git(repo, "show", "%s:%s" % (item["parent"], path))
        for path in git(repo, "ls-tree", "-r", "--name-only", item["parent"], "--", SRC).decode().splitlines())
    return added, parent


def string_bound(repo, item, case, added, parent):
    node = test_function(repo, item, case)
    if node is None:
        return None
    return sorted(s for s in body_strings(node) if s in added and s.encode() not in parent)


def run_item(repo, key, item, out):
    made = json.loads((out / "interfaces" / ("%s.json" % key)).read_text())
    patch = (out / "interfaces" / ("%s.patch" % key)).read_bytes()
    if hashlib.sha256(patch).hexdigest() != made["patch_sha256"]:
        raise SystemExit("%s: the interface patch is not the one made" % key)
    with tempfile.TemporaryDirectory(prefix="ifc-tree-") as scratch:
        tree = make_tree(repo, item, Path(scratch), "parent")
        if patch:
            subprocess.run(["patch", "-p1", "-s", "--no-backup-if-mismatch"], input=patch, cwd=tree, check=True)
        ran = run_tests(tree, item)
    got = set(passing(ran, item["frozen"]))
    on_parent = set(item["pass_on_the_parent"])
    record = {"item": key, "patch_sha256": made["patch_sha256"], "exit": ran["exit"], "limit": ran["limit"],
        "seconds": ran["seconds"], "collection_errors": ran["collection_errors"],
        "C": on_parent <= got, "C_lost": sorted(on_parent - got)}
    names_only = sorted(got - on_parent)
    candidates = sorted(set(item["frozen"]) - on_parent - got)
    added, parent = commit_strings(repo, item)
    bound = {case: string_bound(repo, item, case, added, parent) for case in candidates}
    record.update(names_only=names_only, candidates=candidates,
        first_line={case: ran["cases"].get(case, ("not run", ""))[1] or ran["cases"].get(case, ("not run",))[0]
            for case in candidates},
        signature=sorted(case for case in candidates if SIGNATURE.search(ran["cases"].get(case, ("", ""))[1] or "")),
        string_bound={case: held for case, held in bound.items() if held},
        unread=sorted(case for case, held in bound.items() if held is None))
    (out / "run").mkdir(parents=True, exist_ok=True)
    (out / "run" / ("%s.json" % key)).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    return record


def run(repo, cases_path, out):
    items = load_cases(cases_path)["items"]
    if any((out / "run" / ("%s.json" % key)).exists() for key in items):
        raise SystemExit("the run was made already: it is run once")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for record in pool.map(lambda key: run_item(repo, key, items[key], out), sorted(items)):
            print("%s C %s  names and values only %d  candidates %d (string-bound %d, signature %d)" % (
                record["item"], "ok" if record["C"] else "NO %s" % record["C_lost"], len(record["names_only"]),
                len(record["candidates"]), len(record["string_bound"]), len(record["signature"])), flush=True)


# ---------------------------------------------------------------- the tables

BARRIER = re.compile(r"ImportError|ModuleNotFoundError|AttributeError|NameError|has no attribute|cannot import name|"
    r"unexpected keyword|got an unexpected|missing \d+ required|takes \d+ positional|fixture '[^']*' not found")
FIRST_ROWS = ("nothing-1", "nothing-2", "exists", "path", "search", "bm25", "newest", "lot")
SECOND_ROWS = ("nothing-1", "nothing-2", "may-1", "may-2")


def how_it_fails(line):
    """README, "Added before the run", 1: a given body, still a barrier, an assertion, other."""
    if "NotImplementedError: interface control" in line:
        return "a given body"
    if line in ("not run", "") or BARRIER.search(line):
        return "still a barrier"
    if line.startswith(("AssertionError", "assert ")):
        return "an assertion"
    return "other"


def read(cases_path, out):
    cases = load_cases(cases_path)
    items = cases["items"]
    records = {key: json.loads((out / "run" / ("%s.json" % key)).read_text()) for key in sorted(items)}
    made = {key: json.loads((out / "interfaces" / ("%s.json" % key)).read_text()) for key in sorted(items)}
    kept = [key for key in sorted(items) if records[key]["C"]]
    left_out = {key: records[key]["C_lost"] for key in sorted(items) if not records[key]["C"]}
    group = lambda key: items[key]["pool"] or "A"
    by_item = {}
    for key in sorted(items):
        record, item = records[key], items[key]
        candidates = set(record["candidates"])
        bound = set(record["string_bound"])
        kinds = {}
        for case in record["candidates"]:
            kind = how_it_fails(record["first_line"].get(case, ""))
            kinds[kind] = kinds.get(kind, 0) + 1
        rows = {}
        for name, held in ((n, cases["rows_second_pilot"].get("%s %s" % (key, n))) for n in SECOND_ROWS):
            if held is not None:
                rows["second " + name] = {"published": len(held), "names_only": len(set(held) & set(record["names_only"])),
                    "candidates": len(set(held) & candidates), "not_string_bound": len(set(held) & (candidates - bound))}
        for name, held in ((n, cases["rows_first_pilot"].get("%s %s" % (key, n))) for n in FIRST_ROWS):
            if held is not None:
                rows["first " + name] = {"published": len(held), "names_only": len(set(held) & set(record["names_only"])),
                    "candidates": len(set(held) & candidates), "not_string_bound": len(set(held) & (candidates - bound))}
        by_item[key] = {"part": item["part"], "pool": item["pool"], "C": record["C"], "C_lost": record["C_lost"],
            "frozen": len(item["frozen"]), "on_parent": len(item["pass_on_the_parent"]),
            "outside_parent": len(set(item["frozen"]) - set(item["pass_on_the_parent"])),
            "given": len(made[key]["given"]), "names_only": len(record["names_only"]), "candidates": len(candidates),
            "string_bound": len(bound), "not_string_bound": len(candidates - bound), "fails_by": kinds,
            "signature": len(record["signature"]), "rows": rows}
    sums = {}
    for key in kept:
        for row, held in by_item[key]["rows"].items():
            pilot = row.split()[0]
            cell = sums.setdefault((pilot, group(key) if pilot == "second" else "A"), {}).setdefault(row.split()[1],
                {"items": 0, "outside_parent": 0, "candidates": 0, "not_string_bound": 0, "published": 0,
                 "names_only": 0, "candidates_passed": 0, "not_string_bound_passed": 0})
            cell["items"] += 1
            cell["outside_parent"] += by_item[key]["outside_parent"]
            cell["candidates"] += by_item[key]["candidates"]
            cell["not_string_bound"] += by_item[key]["not_string_bound"]
            cell["published"] += held["published"]
            cell["names_only"] += held["names_only"]
            cell["candidates_passed"] += held["candidates"]
            cell["not_string_bound_passed"] += held["not_string_bound"]
    result = {"cases_sha256": CASES_SHA256, "kept": kept, "left_out": left_out, "by_item": by_item,
        "sums": {"%s %s" % pair: value for pair, value in sorted(sums.items())}}
    (out / "read.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    lines = ["# The interface control: the counts", "",
        "Made by `interface_control.py read` from the run's files; nothing here is typed.", "",
        "Items kept by check C: %d of %d." % (len(kept), len(items))]
    for key, lost in left_out.items():
        lines.append("- Left out by check C: %s, where these parent-passing cases stopped passing: %s" % (key,
            ", ".join(lost)))
    lines += ["", "## By item", "",
        "| item | part, pool | frozen | pass on parent | outside the parent | names given | names and values only |"
        " candidates | given body | still a barrier (signature) | assertion | other | string-bound | not string-bound |",
        "| --- " * 14 + "|"]
    for key, held in by_item.items():
        kinds = held["fails_by"]
        lines.append("| %s%s | %s %s | %d | %d | %d | %d | %d | %d | %d | %d (%d) | %d | %d | %d | %d |" % (key,
            "" if held["C"] else " (left out)", held["part"], held["pool"] or "", held["frozen"], held["on_parent"],
            held["outside_parent"], held["given"], held["names_only"], held["candidates"], kinds.get("a given body", 0),
            kinds.get("still a barrier", 0), held["signature"], kinds.get("an assertion", 0), kinds.get("other", 0),
            held["string_bound"], held["not_string_bound"]))
    for pilot, names in (("second", SECOND_ROWS), ("first", FIRST_ROWS)):
        lines += ["", "## The %s pilot's rows by item: passes on all cases outside the parent / names and values only"
            " / candidates / candidates not string-bound" % pilot, "",
            "| item | outside / candidates / not string-bound | " + " | ".join(names) + " |", "| --- " * (len(names) + 2) + "|"]
        for key, held in by_item.items():
            cells = [held["rows"].get("%s %s" % (pilot, name)) for name in names]
            if not any(cells):
                continue
            lines.append("| %s | %d / %d / %d | " % (key, held["outside_parent"], held["candidates"],
                held["not_string_bound"]) + " | ".join("-" if cell is None else "%d / %d / %d / %d" % (
                cell["published"], cell["names_only"], cell["candidates"], cell["not_string_bound"]) for cell in cells)
                + " |")
    lines += ["", "## Summed over the kept items", "",
        "| pilot, pool | row | items | outside the parent: cases, passed | names and values only, passed |"
        " candidates: cases, passed | not string-bound: cases, passed |", "| --- " * 7 + "|"]
    for (pilot, pool), rows in sorted(sums.items()):
        for row in (SECOND_ROWS if pilot == "second" else FIRST_ROWS):
            if row in rows:
                cell = rows[row]
                lines.append("| %s %s | %s | %d | %d, %d | %d | %d, %d | %d, %d |" % (pilot, pool, row, cell["items"],
                    cell["outside_parent"], cell["published"], cell["names_only"], cell["candidates"],
                    cell["candidates_passed"], cell["not_string_bound"], cell["not_string_bound_passed"]))
    (out / "read.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main(argv):
    parser = argparse.ArgumentParser(prog="interface_control.py")
    sub = parser.add_subparsers(dest="stage", required=True)
    one = sub.add_parser("check")
    one.add_argument("repo")
    one.add_argument("cases")
    one.add_argument("out")
    one.add_argument("--items", default="")
    two = sub.add_parser("make")
    two.add_argument("repo")
    two.add_argument("cases")
    two.add_argument("out")
    two.add_argument("--items", default="")
    three = sub.add_parser("run")
    three.add_argument("repo")
    three.add_argument("cases")
    three.add_argument("out")
    four = sub.add_parser("read")
    four.add_argument("cases")
    four.add_argument("out")
    args = parser.parse_args(argv)
    if args.stage == "check":
        check(Path(args.repo).resolve(), args.cases, Path(args.out).resolve(),
            [prefix for prefix in args.items.split(",") if prefix])
    if args.stage == "make":
        make(Path(args.repo).resolve(), args.cases, Path(args.out).resolve(),
            [prefix for prefix in args.items.split(",") if prefix])
    if args.stage == "run":
        run(Path(args.repo).resolve(), args.cases, Path(args.out).resolve())
    if args.stage == "read":
        read(args.cases, Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
