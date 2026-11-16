#!/usr/bin/env python3
"""Makes the experiment's items from a repository's merged commits, by section 6 of
docs/superpowers/specs/2026-11-16-v2-a-route-offered.md.

    python3 -I items.py list --repo <path> --first <commit> --last <commit> --component peer --python <path>
                             --scored 40 --pilot 3 --out <dir> [--limit-secs 300]

It puts every commit reached from --last and not from --first in one order, finds by rules 1 to 3 the commits
that could be items, runs each one's tests (rule 4) with --python, makes each eligible commit's item (a base,
a wrong commit and a reference, kept under refs/yak-items/<commit>/), gives each eligible commit its part
(history, pilot, scored, or left out by rule 5), and writes <out>/items.json once. It prints that file's
SHA-256. It runs no room and no model, and it never checks anything out in --repo: the repository's work tree,
index and branches are not touched. Each item's check is check.py, beside this file.

It is one file that imports nothing of its own but check.py, so that it runs with python3 -I.
"""
import argparse
import collections
import hashlib
import heapq
import importlib.util
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("yak_items_check", os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "check.py"))
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

# For each component, by its directory: where its tests are (test_*.py directly in that directory), where its
# source is (anything under that directory), where documents are (anything under it), and its lock file.
COMPONENTS = {
    "peer": {"tests": "peer/tests", "source": "peer/superyak_peer", "documents": "docs", "lock": "peer/uv.lock"},
}
# Rule 3.
MAX_TEST_FILES = check.MAX_TEST_FILES
MAX_SOURCE_FILES = 5
BROWSER = "browser"
REGULAR = ("100644", "100755")
MAX_TITLE = 200
DEFAULT_LIMIT_SECS = 300
TITLE = "Make the failing tests in %s pass by changing the code under %s, not the tests."
CHECK_COMMAND = "python3 -I .yak-check/check.py"
UNRELATED = ".yak-check/unrelated.txt"
UNRELATED_TEXT = b"A file that changes nothing the tests run.\n"
# Every commit made here: one name, the parent's committer time, and a message that says nothing of the fix.
MADE_NAME = "yak items"
MADE_EMAIL = "items@yak.invalid"
BASE_MESSAGE = "tests first"
REFERENCE_MESSAGE = "the reference"
WRONG_MESSAGE = "an unrelated file"
REFS = "refs/yak-items/"
# A commit that met rules 1 to 3 is given one of these parts, or one of these reasons.
HISTORY, PILOT, SCORED, RULE_5 = "history", "pilot", "scored", "left out by rule 5"
PARTS = (HISTORY, PILOT, SCORED, RULE_5)
PASS_BEFORE = "rule 4: the tests pass before the change"
FAIL_AFTER = "rule 4: the tests fail after the change"
PAST_LIMIT = "rule 4: past the limit"
TITLE_TOO_LONG = "the title would be too long"
REASONS = (PASS_BEFORE, FAIL_AFTER, PAST_LIMIT, TITLE_TOO_LONG)
# The settings every git here runs with, whatever the repository's own say: no hook (update-ref would run one),
# no filesystem monitor, commits made the same on any machine, and files written as they are stored.
GIT_FLAGS = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "i18n.commitEncoding=UTF-8",
             "-c", "core.autocrlf=false"]

Change = collections.namedtuple("Change", "status mode blob path")


class Refused(Exception):
    pass


class Git:
    """git in one repository, with nothing of the caller's environment but its search path: no settings file of
    the machine's or a home's, and no replaced object, which would make one commit's parents differ by machine."""

    def __init__(self, repo):
        self.repo = repo
        self.env = {"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_NO_REPLACE_OBJECTS": "1"}

    def __call__(self, *args, data=None, env=None, where=None):
        done = subprocess.run(["git"] + GIT_FLAGS + ["-C", where or self.repo] + list(args), input=data,
                              env=dict(self.env, **(env or {})), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode != 0:
            said = done.stderr.decode("utf-8", "replace").strip().splitlines()
            raise Refused("git %s failed: %s" % (args[0], said[0] if said else "exit %d" % done.returncode))
        return done.stdout

    def commit_id(self, name):
        if name.startswith("-"):
            raise Refused("%s is not a commit" % check.shown(name))
        return self("rev-parse", "--verify", "--quiet", name + "^{commit}").decode("ascii").strip()

    def committer_time(self, commit):
        return int(self("rev-list", "-1", "--format=%ct", commit).decode("ascii").split()[-1])


def read_commits(git, first, last):
    """(id, committer time, parents) of every commit reached from `last` and not from `first`, as git reads them."""
    commits = []
    for line in git("rev-list", "--format=%H %ct %P", last, "^" + first, "--").decode("ascii").splitlines():
        if not line.startswith("commit "):
            fields = line.split()
            commits.append((fields[0], int(fields[1]), tuple(fields[2:])))
    return commits


def order(commits):
    """The spec's "earlier", exactly: a commit after every commit it descends from, and among the commits free to
    come next, the earlier committer time first, and at one time the id first in byte order. The same list
    whatever order `commits` is in."""
    known = {commit for commit, _, _ in commits}
    waiting, children, ready = {}, collections.defaultdict(list), []
    for commit, time, parents in commits:
        inside = set(parents) & known
        waiting[commit] = len(inside)
        for parent in inside:
            children[parent].append(commit)
        if not inside:
            ready.append((time, commit))
    times = {commit: time for commit, time, _ in commits}
    heapq.heapify(ready)
    ordered = []
    while ready:
        _, commit = heapq.heappop(ready)
        ordered.append(commit)
        for child in children[commit]:
            waiting[child] -= 1
            if waiting[child] == 0:
                heapq.heappush(ready, (times[child], child))
    return ordered


def changes(git, parent, commit):
    """What `commit` changed from `parent`, path by path, with renames not followed."""
    fields = git("diff-tree", "-r", "-z", "--raw", "--no-renames", parent, commit).split(b"\0")
    found = []
    for meta, path in zip(fields[0::2], fields[1::2]):
        _, mode, _, blob, status = meta.decode("ascii")[1:].split(" ")
        found.append(Change(status, mode, blob, path.decode("utf-8", "surrogateescape")))
    return found


def sort_out(component, found):
    """The test files and source files of a commit's changes when they meet rules 2 and 3, else None."""
    where = COMPONENTS[component]
    tests, sources = [], []
    for change in found:
        directory, _, name = change.path.rpartition("/")
        if change.path.startswith(where["documents"] + "/"):
            continue
        if directory == where["tests"] and name.startswith("test_") and check.plain(change.path):
            tests.append(change)
        elif change.path.startswith(where["source"] + "/") and check.plain(change.path):
            sources.append(change)
        else:
            return None
    if not tests or not sources:
        return None
    if len(tests) > MAX_TEST_FILES or len(sources) > MAX_SOURCE_FILES:
        return None
    for change in tests + sources:
        if change.status not in ("A", "M") or change.mode not in REGULAR or not change.path.endswith(".py"):
            return None
    if any(BROWSER in posixpath.basename(change.path) for change in tests):
        return None
    # In git's order, which is by path.
    return tests, sources


def title_of(component, tests):
    return TITLE % (", ".join(posixpath.basename(change.path) for change in tests), COMPONENTS[component]["source"])


def passes(code, counts):
    """The spec's pass: the runner ended with 0, no failure, no error, and at least one test not skipped."""
    return (code == 0 and counts is not None and counts["failures"] == 0 and counts["errors"] == 0
            and counts["tests"] - counts["skipped"] >= 1)


def parts(eligible, scored, pilot):
    """Each eligible commit's part, each scored commit's place, and the dividing commit (spec revision 7, section
    6, "The scored, the pilot's and history"). Everything that decides a part is here.

    `eligible` is [(commit, set of its test files)] in order. One eligible commit divides, the last that is not
    scored. Scored: going forward from the eligible commit after the dividing one, each is scored unless it names
    a test file that a scored commit before it names, and then it is left out by rule 5: of two, the earlier is
    kept. The dividing commit is the latest for which at least `scored` are found so. The pilot's: going back from
    the dividing commit, itself included, each is the pilot's unless it names a test file that one already taken
    names, and then it is left out by rule 5: of two, the later is kept. The first `pilot` so found are the
    pilot's. History: every eligible commit before the earliest of the pilot's. It is not held to rule 5, and
    may be empty."""
    most = 0
    for divide in range(len(eligible) - 1, -1, -1):
        part, place, seen = {}, {}, set()
        for commit, tests in eligible[divide + 1:]:
            if seen & tests:
                part[commit] = RULE_5
            else:
                part[commit] = SCORED
                place[commit] = len(place) + 1
                seen |= tests
        most = max(most, len(place))
        if len(place) >= scored:
            break
    else:
        raise Refused("too few for the scored: %d asked for, and at most %d are found after any eligible commit"
                      % (scored, most))
    seen, taken = set(), []
    for at in range(divide, -1, -1):
        if len(taken) == pilot:
            break
        commit, tests = eligible[at]
        if seen & tests:
            part[commit] = RULE_5
        else:
            part[commit] = PILOT
            seen |= tests
            taken.append(at)
    if len(taken) < pilot:
        raise Refused("too few for the pilot: %d asked for, and %d are found going back from the dividing commit"
                      % (pilot, len(taken)))
    for commit, _ in eligible[:taken[-1]]:
        part[commit] = HISTORY
    return part, place, eligible[divide][0]


class Maker:
    """Runs rule 4 and makes the items, in a scratch directory of its own."""

    def __init__(self, git, component, python, limit, scratch):
        self.git, self.component, self.python, self.limit, self.scratch = git, component, python, limit, scratch
        self.index = os.path.join(scratch, "index")
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "check.py"), "rb") as file:
            self.check_blob = self.blob(file.read())
        self.unrelated_blob = self.blob(UNRELATED_TEXT)

    def blob(self, data):
        return self.git("hash-object", "-w", "--no-filters", "--stdin", data=data).decode("ascii").strip()

    def lay(self, tree, entries):
        """The tree `tree` with `entries` (mode, blob, path) laid over it, in the scratch index."""
        env = {"GIT_INDEX_FILE": self.index}
        self.git("read-tree", tree, env=env)
        info = b"".join(b"%s %s\t%s\0" % (mode.encode(), blob.encode(), path.encode()) for mode, blob, path in entries)
        self.git("update-index", "-z", "--index-info", data=info, env=env)
        return self.git("write-tree", env=env).decode("ascii").strip()

    def run(self, tree, tests):
        """The tests run in a clean copy of `tree`: (exit code, past the limit, counts)."""
        copy = os.path.join(self.scratch, "tree")
        env = {"GIT_INDEX_FILE": self.index}
        self.git("read-tree", tree, env=env)
        self.git("checkout-index", "-a", "-f", "--prefix=" + copy + "/", env=env)
        try:
            return check.run_tests(self.python, copy, self.component, tests, self.limit)
        finally:
            shutil.rmtree(copy, ignore_errors=True)

    def commit(self, tree, parent, time, message):
        when = "@%d +0000" % time
        env = {"GIT_AUTHOR_NAME": MADE_NAME, "GIT_AUTHOR_EMAIL": MADE_EMAIL, "GIT_AUTHOR_DATE": when,
               "GIT_COMMITTER_NAME": MADE_NAME, "GIT_COMMITTER_EMAIL": MADE_EMAIL, "GIT_COMMITTER_DATE": when}
        return self.git("commit-tree", tree, "-p", parent, "-m", message, env=env).decode("ascii").strip()

    def check_passes(self, commit):
        """Whether the check passes on `commit`, run as the room runs it, at the root of a clone: (passed, past the
        limit). A run ended at the limit has not passed."""
        clone = os.path.join(self.scratch, "clone")
        try:
            self.git("clone", "-q", "--shared", "--no-checkout", "--template=", os.path.abspath(self.git.repo), clone)
            self.git("checkout", "-q", "--detach", commit, where=clone)
            code, late = check.run_limited([self.python, "-I", check.CHECK], clone, {"PATH": self.git.env["PATH"]},
                                           self.limit)
            return code == 0, late
        finally:
            shutil.rmtree(clone, ignore_errors=True)

    def make(self, commit, parent, tests, sources):
        """The item of one commit that met rules 1 to 3, or the reason it is not eligible."""
        title = title_of(self.component, tests)
        if len(title) > MAX_TITLE:
            return TITLE_TOO_LONG
        test_paths = [change.path for change in tests]
        laid_tests = [(change.mode, change.blob, change.path) for change in tests]
        laid_sources = [(change.mode, change.blob, change.path) for change in sources]
        with_tests = self.lay(parent, laid_tests)
        code, late, counts = self.run(with_tests, test_paths)
        if late:
            return PAST_LIMIT
        if passes(code, counts):
            return PASS_BEFORE
        code, late, counts = self.run(self.lay(with_tests, laid_sources), test_paths)
        if late:
            return PAST_LIMIT
        if not passes(code, counts):
            return FAIL_AFTER
        passed, skipped = counts["tests"] - counts["skipped"], counts["skipped"]
        item = {"component": self.component, "parent": parent, "passed": passed, "skipped": skipped,
                "source": COMPONENTS[self.component]["source"],
                "tests": [{"blob": change.blob, "path": change.path} for change in tests]}
        item_blob = self.blob((json.dumps(item, sort_keys=True, indent=1) + "\n").encode("ascii"))
        time = self.git.committer_time(parent)
        base_tree = self.lay(with_tests, [("100644", self.check_blob, check.CHECK), ("100644", item_blob, check.ITEM)])
        base = self.commit(base_tree, parent, time, BASE_MESSAGE)
        reference = self.commit(self.lay(base_tree, laid_sources), base, time, REFERENCE_MESSAGE)
        wrong = self.commit(self.lay(base_tree, [("100644", self.unrelated_blob, UNRELATED)]), base, time,
                            WRONG_MESSAGE)
        green, late = self.check_passes(reference)
        if late:
            return PAST_LIMIT
        if not green:
            return FAIL_AFTER
        return {"base": base, "check": {"command": CHECK_COMMAND, "files": sorted([check.CHECK, check.ITEM]
                                                                                  + test_paths)},
                "commit": commit, "counts": {"passed": passed, "skipped": skipped}, "reference": reference,
                "tests": test_paths, "title": title, "wrong": wrong}


def interpreter_version(python):
    try:
        done = subprocess.run([python, "-I", "-c", "import platform, sys; print(sys.implementation.name, "
                               "platform.python_version())"], env={},
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as error:
        raise Refused("--python %s cannot be run (%s)" % (check.shown(python), error.strerror)) from None
    said = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or not said:
        raise Refused("--python %s does not say its version" % check.shown(python))
    return said


def make_list(args, say):
    git = Git(os.path.abspath(args.repo))
    first, last = git.commit_id(args.first), git.commit_id(args.last)
    where = COMPONENTS[args.component]
    lock = hashlib.sha256(git("cat-file", "blob", "%s:%s" % (last, where["lock"]))).hexdigest()
    python = os.path.abspath(args.python)
    version = interpreter_version(python)
    out = os.path.abspath(args.out)
    target = os.path.join(out, "items.json")
    if os.path.lexists(target):
        raise Refused("%s is there already: a list is written once" % target)
    commits = read_commits(git, first, last)
    read = {commit: parents for commit, _, parents in commits}
    ordered = order(commits)
    scratch = tempfile.mkdtemp(prefix="yak-items-")
    try:
        maker = Maker(git, args.component, python, args.limit_secs, scratch)
        listed = []
        for at, commit in enumerate(ordered, 1):
            parents = read[commit]
            # Rule 1: not a merge, and a commit with a parent to make the item's base from.
            if len(parents) != 1:
                continue
            sorted_out = sort_out(args.component, changes(git, parents[0], commit))
            if sorted_out is None:
                continue
            made = maker.make(commit, parents[0], *sorted_out)
            listed.append(made if isinstance(made, dict) else {"commit": commit, "reason": made})
            say("%d of %d: %s %s" % (at, len(ordered), commit[:12], made["title"] if isinstance(made, dict)
                                     else made))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    eligible = [(entry["commit"], set(entry["tests"])) for entry in listed if "reason" not in entry]
    part, place, dividing = parts(eligible, args.scored, args.pilot)
    for entry in listed:
        if "reason" not in entry:
            entry["part"] = part[entry["commit"]]
            if entry["commit"] in place:
                entry["place"] = place[entry["commit"]]
    by_part = {name: sum(1 for entry in listed if entry.get("part") == name) for name in PARTS}
    by_reason = {name: sum(1 for entry in listed if entry.get("reason") == name) for name in REASONS}
    refs = "".join("update %s%s/%s %s\n" % (REFS, entry["commit"], kind, entry[kind])
                   for entry in listed if "part" in entry for kind in ("base", "reference", "wrong"))
    git("update-ref", "--stdin", data=refs.encode("ascii"))
    written = {"asked": {"limit_secs": args.limit_secs, "pilot": args.pilot, "scored": args.scored},
               "commits": listed, "component": args.component,
               "counts": {"by_part": by_part, "by_reason": by_reason, "met rules 1 to 3": len(listed)},
               "dividing": dividing, "first": first, "last": last, "lock_sha256": lock, "python": version}
    data = (json.dumps(written, sort_keys=True, indent=1, ensure_ascii=True) + "\n").encode("ascii")
    os.makedirs(out, exist_ok=True)
    partial = tempfile.NamedTemporaryFile(dir=out, prefix=".items-", delete=False)
    try:
        with partial:
            partial.write(data)
        os.link(partial.name, target)
    finally:
        os.unlink(partial.name)
    return target, hashlib.sha256(data).hexdigest(), python, by_part, by_reason


def positive(text):
    if not re.fullmatch(r"[1-9][0-9]{0,8}", text):
        raise argparse.ArgumentTypeError("%r is not a whole number above 0" % text)
    return int(text)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="items.py", description="Makes experiment items from merged commits.")
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("list", help="find the items, make them and write items.json")
    for flag in ("--repo", "--first", "--last", "--python", "--out"):
        one.add_argument(flag, required=True)
    one.add_argument("--component", required=True, choices=sorted(COMPONENTS))
    one.add_argument("--scored", required=True, type=positive)
    one.add_argument("--pilot", required=True, type=positive)
    one.add_argument("--limit-secs", type=positive, default=DEFAULT_LIMIT_SECS)
    args = parser.parse_args(argv)
    try:
        target, digest, python, by_part, by_reason = make_list(args, lambda line: print(line, file=sys.stderr))
    except Refused as refusal:
        print("REFUSED: %s" % refusal)
        return 1
    except Exception as error:  # One line, never a traceback.
        print("REFUSED: the item-maker could not go on (%s: %s)" % (type(error).__name__, error))
        return 1
    print("wrote %s" % target)
    print("sha256 %s" % digest)
    print("the tests were run by %s (the list holds its version, not its path)" % python)
    for name, count in list(by_part.items()) + list(by_reason.items()):
        print("%4d %s" % (count, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
