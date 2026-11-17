#!/usr/bin/env python3
"""The check of every item made from a merged commit by items.py, beside it. It is copied into each item's base as
.yak-check/check.py, and the room runs it at the root of a fresh clone of the commit judged:

    python3 -I .yak-check/check.py

It reads .yak-check/item.json and passes, printing ok and ending with 0, only when all of these hold:

1. The item's parent is in the clone and is an ancestor of the commit judged. Between the two, every path that
   differs is under the item's source directory or is one of the check's own files. Each test file's blob at the
   commit judged is the one item.json names, and check.py and item.json there are the copies running now.
2. The test runner, started on the item's test files as run_tests says, ends with 0, and the report it leaves
   says no failure and no error.
3. That report says at least as many tests passed as on the reference, and no more were skipped.

Otherwise it ends with 1 and one line on stderr that begins FAIL and names which. FAIL 0 is item.json out of its
form, or a check that could not run. Everything it reads from the checkout is hostile, since a worker wrote it:
item.json is held to its form, nothing read from it reaches a shell, and git runs with no hooks, no filesystem
monitor and no settings file but the clone's own. Of the checkout it runs nothing but the tests.

What a pass shows is what the check observed: the path rule held, the frozen files are the item's blobs, the test
runner ended with 0, and the report it left says no failure, no error, at least as many passed as on the reference
and no more skipped. That is a showing that the tests pass when the runner and its report did what they are for.
The check does not show that they did, nor what the worker meant: the turn's code runs inside the runner's own
process, and by accident or on purpose it can bear on what is gathered, on what a test asserts, on the test files
as they lie in the checkout during the run, on the report, or on how the process ends. No check written here can
rule that out.

items.py loads this file for run_tests and plain, so that the item-maker runs the tests as the check does. It runs
this file with YAK_CHECK_SHARE_GROUP=1 in its environment, so that the tests stay in the check's own process group
and are ended with it at the item-maker's limit. The room does not set it, and then the tests run in a session of
their own, which the check ends when they end.
"""
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree

ITEM = ".yak-check/item.json"
CHECK = ".yak-check/check.py"
# The largest item.json read. One the item-maker writes is under a kilobyte.
MAX_ITEM_BYTES = 65536
# The largest test report read.
MAX_REPORT_BYTES = 16777216
# An item names at most this many test files (the spec's rule 3).
MAX_TEST_FILES = 3
# The most tests a count in item.json may say.
MAX_COUNT = 1000000
KEYS = {"component", "parent", "passed", "skipped", "source", "tests"}
TEST_KEYS = {"blob", "path"}
COUNTS = ("tests", "failures", "errors", "skipped")
# One part of a plain path: ASCII letters, digits, '_', '.' and '-', and not beginning with '.' or '-'. So never
# '.', '..' or '.git', and never a space, a quote, a line end or anything a shell or git reads as more than a name.
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
HEX = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
COUNT = re.compile(r"[0-9]{1,9}")
# Every git this runs reads objects only: no hook runs and no attribute applies. The filesystem monitor is off as
# in v2/checks/worker-tests-done.sh, so that nothing configured is started.
GIT_FLAGS = ["-c", "core.fsmonitor=false"]
# The environment variable that, set to 1, keeps the tests in the check's own process group, for a caller that ends
# that group (items.py does, at its limit and after the check ends).
SHARE_GROUP = "YAK_CHECK_SHARE_GROUP"


class Fail(Exception):
    pass


def plain(path):
    """A relative path of plain names joined by '/'."""
    return isinstance(path, str) and all(NAME.fullmatch(part) for part in path.split("/"))


def shown(text):
    """Text from the checkout as it may be printed: quoted, escaped to ASCII, on one line and not long."""
    return json.dumps(text[:200])


def read_regular(path, limit):
    """The bytes of a regular file that is not a link, or None if it is not one or is longer than `limit`."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    with os.fdopen(fd, "rb") as file:
        data = file.read(limit + 1)
    return data if len(data) <= limit else None


def no_key_twice(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a key given twice")
    return dict(pairs)


def read_item(root):
    """item.json's bytes and what it says, held to its form."""
    data = read_regular(os.path.join(root, ITEM), MAX_ITEM_BYTES)
    if data is None:
        raise Fail("0: %s is not a regular file of at most %d bytes" % (ITEM, MAX_ITEM_BYTES))
    try:
        item = json.loads(data.decode("utf-8"), object_pairs_hook=no_key_twice)
    except (ValueError, RecursionError):
        raise Fail("0: %s is not strict JSON" % ITEM) from None
    if not isinstance(item, dict) or set(item) != KEYS:
        raise Fail("0: %s must hold exactly the keys %s" % (ITEM, ", ".join(sorted(KEYS))))
    component, source, parent, tests = item["component"], item["source"], item["parent"], item["tests"]
    if not isinstance(component, str) or not NAME.fullmatch(component):
        raise Fail("0: %s's component is not a plain name" % ITEM)
    if not plain(source) or not source.startswith(component + "/"):
        raise Fail("0: %s's source is not a plain path under its component" % ITEM)
    if not isinstance(parent, str) or not HEX.fullmatch(parent):
        raise Fail("0: %s's parent is not a commit id" % ITEM)
    for key, least in (("passed", 1), ("skipped", 0)):
        if type(item[key]) is not int or not least <= item[key] <= MAX_COUNT:
            raise Fail("0: %s's %s is not a whole number from %d to %d" % (ITEM, key, least, MAX_COUNT))
    if not isinstance(tests, list) or not 1 <= len(tests) <= MAX_TEST_FILES:
        raise Fail("0: %s's tests are not a list of 1 to %d" % (ITEM, MAX_TEST_FILES))
    for test in tests:
        if not isinstance(test, dict) or set(test) != TEST_KEYS:
            raise Fail("0: %s's tests must each hold exactly the keys blob, path" % ITEM)
        path, blob = test["path"], test["blob"]
        if not plain(path) or not path.startswith(component + "/") or path.startswith(source + "/"):
            raise Fail("0: %s names a test file that is not a plain path under its component and outside its source"
                       % ITEM)
        if not isinstance(blob, str) or len(blob) != len(parent) or not HEX.fullmatch(blob):
            raise Fail("0: %s names a test file's blob that is not an object id" % ITEM)
    if len({test["path"] for test in tests}) != len(tests):
        raise Fail("0: %s names one test file twice" % ITEM)
    return data, item


def git_env(root):
    """git's environment: the absolute entries of the search path (a relative one would find a program the worker
    committed), the clone's own repository and nothing found by looking above it, and no settings file of the
    machine's. No home is given, so none is read."""
    path = os.pathsep.join(entry for entry in os.environ.get("PATH", "").split(os.pathsep) if os.path.isabs(entry))
    return {"PATH": path, "GIT_DIR": os.path.join(root, ".git"), "GIT_CONFIG_NOSYSTEM": "1"}


def git(root, *args):
    done = subprocess.run(["git"] + GIT_FLAGS + list(args), cwd=root, env=git_env(root), stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return done.returncode, done.stdout


def blob_id(data, parent):
    """The id git gives a blob of these bytes, in the object format of the item's parent."""
    digest = hashlib.sha1() if len(parent) == 40 else hashlib.sha256()
    digest.update(b"blob %d\0" % len(data) + data)
    return digest.hexdigest()


def entry_at(root, commit, path):
    """(mode, type, object id) of `path` at `commit`. A plain path names one entry, so ls-tree lists that one or
    none, and none gives an entry that is no file's."""
    return tuple(git(root, "ls-tree", "-z", commit, "--", path)[1].partition(b"\t")[0].decode("ascii").split(" "))


def judge_commit(root, item, item_bytes):
    """Condition 1."""
    code, out = git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if code != 0:
        raise Fail("1: the checkout is not a git repository with a commit")
    head = out.decode("ascii", "replace").strip()
    parent = item["parent"]
    if git(root, "rev-parse", "--verify", "--quiet", parent + "^{commit}")[0] != 0:
        raise Fail("1: the item's parent %s is not in this repository" % parent)
    code = git(root, "merge-base", "--is-ancestor", parent, head)[0]
    if code != 0:
        raise Fail("1: the commit judged does not descend from the item's parent %s" % parent)
    code, out = git(root, "diff-tree", "-r", "-z", "--name-only", "--no-renames", parent, head)
    if code != 0:
        raise Fail("1: cannot list what changed since the item's parent")
    tests = {test["path"]: test["blob"] for test in item["tests"]}
    own = {CHECK, ITEM} | set(tests)
    for raw in out.split(b"\0"):
        path = raw.decode("utf-8", "surrogateescape")
        if raw and path not in own and not path.startswith(item["source"] + "/"):
            raise Fail("1: a path outside %s changed: %s" % (item["source"], shown(path)))
    for path, blob in sorted(tests.items()):
        if not regular_blob(entry_at(root, head, path), blob):
            raise Fail("1: the test file %s is not the item's" % path)
    with open(os.path.abspath(__file__), "rb") as running:
        check_bytes = running.read()
    for path, data in ((CHECK, check_bytes), (ITEM, item_bytes)):
        if not regular_blob(entry_at(root, head, path), blob_id(data, parent)):
            raise Fail("1: %s at the commit judged is not the copy this check runs with" % path)


def regular_blob(entry, blob):
    """Whether a tree entry is the file `blob`, as a regular file, executable or not."""
    return entry in (("100644", "blob", blob), ("100755", "blob", blob))


def run_limited(argv, cwd, env, limit, own_group=True):
    """Runs `argv` in a session of its own, for at most `limit` seconds if one is given, and ends whatever it started
    and left when it ends or at the limit. Returns (exit code, whether it ran past the limit).

    With `own_group` false it runs in the caller's process group instead, and what it leaves is the group owner's to
    end: only the run itself is ended at the limit."""
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=own_group)
    try:
        code, late = proc.wait(timeout=limit), False
    except subprocess.TimeoutExpired:
        if own_group:
            end_group(proc)
        else:
            proc.kill()
        code, late = proc.wait(), True
    # A run in the caller's group leads no group, and once it is waited for its id may be another group's.
    if own_group:
        end_group(proc)
    return code, late


def end_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


def read_report(path):
    """The four counts of a JUnit XML report, summed over its test suites, or None if it cannot be read."""
    data = read_regular(path, MAX_REPORT_BYTES)
    # Only a document type can declare entities, which can grow without end; pytest writes none.
    if data is None or b"<!DOCTYPE" in data:
        return None
    try:
        suites = list(ElementTree.fromstring(data).iter("testsuite"))
    except ElementTree.ParseError:
        return None
    if not suites:
        return None
    counts = dict.fromkeys(COUNTS, 0)
    for suite in suites:
        for key in COUNTS:
            value = suite.get(key)
            if value is None or not COUNT.fullmatch(value):
                return None
            counts[key] += int(value)
    return counts


def run_tests(python, root, component, tests, limit=None, own_group=True):
    """Runs the test files `tests` (paths from the repository's root) of the tree at `root`, as the spec says: from
    the component's directory, `<python> -m pytest -q -p no:cacheprovider --junit-xml <file> <the test files>`,
    with the component's directory first on PYTHONPATH, PYTHONDONTWRITEBYTECODE=1, and of the caller's
    environment nothing: PATH is /usr/bin:/bin and HOME and TMPDIR are a scratch directory. At most `limit`
    seconds if one is given; the run and whatever it started are ended then. `own_group` is run_limited's.

    Returns (exit code, whether it ran past the limit, the report's counts or None). A caller reads the counts of
    a run past its limit as nothing."""
    directory = os.path.join(root, component)
    scratch = tempfile.mkdtemp(prefix="yak-tests-")
    try:
        report = os.path.join(scratch, "report.xml")
        home = os.path.join(scratch, "home")
        os.mkdir(home)
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "TMPDIR": home, "PYTHONPATH": directory,
               "PYTHONDONTWRITEBYTECODE": "1"}
        argv = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junit-xml", report]
        argv += [test[len(component) + 1:] for test in tests]
        code, late = run_limited(argv, directory, env, limit, own_group)
        return code, late, read_report(report)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def judge(root):
    item_bytes, item = read_item(root)
    judge_commit(root, item, item_bytes)
    shared = os.environ.get(SHARE_GROUP) == "1"
    code, _, counts = run_tests(sys.executable, root, item["component"], [test["path"] for test in item["tests"]],
                                own_group=not shared)
    if counts is None:
        raise Fail("2: the tests wrote no report that can be read (exit %d)" % code)
    if code != 0 or counts["failures"] or counts["errors"]:
        raise Fail("2: the tests did not pass (exit %d, %d failed, %d errors)"
                   % (code, counts["failures"], counts["errors"]))
    passed = counts["tests"] - counts["skipped"]
    if passed < item["passed"]:
        raise Fail("3: %d tests passed, fewer than the reference's %d" % (passed, item["passed"]))
    if counts["skipped"] > item["skipped"]:
        raise Fail("3: %d tests were skipped, more than the reference's %d" % (counts["skipped"], item["skipped"]))


def main():
    try:
        judge(os.getcwd())
    except Fail as failure:
        sys.stderr.write("FAIL %s\n" % failure)
        return 1
    except Exception as error:  # A check never ends with a traceback: one line, and a failure.
        sys.stderr.write("FAIL 0: the check could not run (%s)\n" % type(error).__name__)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
