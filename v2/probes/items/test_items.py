#!/usr/bin/env python3
"""Tests of items.py and check.py. Run as: python3 -I test_items.py

No room, no model and no real repository are run. The repositories here are made by the tests in a temporary
directory, with a component of their own added to items.py's table: "toy", whose tests are toy/tests/test_*.py
and whose source is under toy/src/.

The test runner here is a STAND-IN, so that no test needs pytest installed. A virtual environment made by these
tests holds a tiny module named pytest (STAND_IN below), and its interpreter is the --python given to the
program. The stand-in runs the named files' test_* functions and writes the four counts of pytest's XML report.
It is not pytest, and nothing here shows how pytest itself behaves.
"""
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

# Nothing is left beside the scripts by running these.
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("items", os.path.join(HERE, "items.py"))
assert spec is not None and spec.loader is not None
items = importlib.util.module_from_spec(spec)
spec.loader.exec_module(items)
check = items.check

TOY = {"tests": "toy/tests", "source": "toy/src", "documents": "docs", "lock": "toy/uv.lock"}

STAND_IN = r'''"""A STAND-IN for pytest, written by test_items.py so that its tests need no pytest. It is not pytest.

Run as `python -m pytest ... --junit-xml <file> <test files>`, it imports each file in turn, runs its test_*
functions by name, and writes the four counts pytest's XML report holds: tests, failures, errors and skipped.
A file that cannot be imported counts as one test and one error. It ends with 0 when every test passed or was
skipped, 1 when one failed or errored, and 5 when none was collected, as pytest does. It writes each run's
words, directory and environment to RECORD, for the tests to read.
"""
import importlib.util
import json
import os
import sys

RECORD = @RECORD@


class Skipped(Exception):
    pass


def skip(reason=""):
    raise Skipped(reason)


def main(argv):
    with open(RECORD, "a") as record:
        record.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "env": dict(os.environ)}) + "\n")
    report, files, words = None, [], iter(argv)
    for word in words:
        if word == "--junit-xml":
            report = next(words)
        elif word == "-p":
            next(words)
        elif not word.startswith("-"):
            files.append(word)
    tests = failures = errors = skipped = 0
    for number, path in enumerate(files):
        found = importlib.util.spec_from_file_location("stand_in_test_%d" % number, path)
        module = importlib.util.module_from_spec(found)
        try:
            found.loader.exec_module(module)
        except Exception:
            tests, errors = tests + 1, errors + 1
            continue
        for name in sorted(vars(module)):
            if name.startswith("test_") and callable(vars(module)[name]):
                tests += 1
                try:
                    vars(module)[name]()
                except Skipped:
                    skipped += 1
                except Exception:
                    failures += 1
    with open(report, "w") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" errors="%d" '
                  'failures="%d" skipped="%d" tests="%d" /></testsuites>' % (errors, failures, skipped, tests))
    return 5 if tests == 0 else 1 if failures or errors else 0


if __name__ == "__main__":
    import pytest  # The module the tests import, so that the Skipped they raise is the one caught here.
    sys.exit(pytest.main(sys.argv[1:]))
'''

WORK = PYTHON = ALIAS = RECORD = None
GIT_ENV = {"PATH": os.environ.get("PATH") or "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}


def setUpModule():
    global WORK, PYTHON, ALIAS, RECORD
    WORK = os.path.realpath(tempfile.mkdtemp(prefix="test-items-"))
    venv = os.path.join(WORK, "venv")
    subprocess.run([sys.executable, "-I", "-m", "venv", "--without-pip", venv], check=True)
    PYTHON = os.path.join(venv, "bin", "python")
    site = subprocess.run([PYTHON, "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                          check=True, stdout=subprocess.PIPE).stdout.decode().strip()
    RECORD = os.path.join(WORK, "runs.jsonl")
    with open(os.path.join(site, "pytest.py"), "w") as out:
        out.write(STAND_IN.replace("@RECORD@", json.dumps(RECORD)))
    # The same interpreter by another path.
    os.symlink(venv, os.path.join(WORK, "the-same-venv"))
    ALIAS = os.path.join(WORK, "the-same-venv", "bin", "python")
    items.COMPONENTS["toy"] = TOY


def tearDownModule():
    items.COMPONENTS.pop("toy", None)
    shutil.rmtree(WORK, ignore_errors=True)


def git(repo, *args, data=None, env=None):
    done = subprocess.run(["git", "-C", repo] + list(args), input=data, env=dict(GIT_ENV, **(env or {})),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr.decode()))
    return done.stdout


class Exe(bytes):
    """A file's bytes, to be committed executable."""


class Link(bytes):
    """A symbolic link's target, to be committed as a link."""


def commit(repo, parents, files, when, message="a change"):
    """A commit by plumbing: the first parent's tree (or none) with `files` laid over it, a path to None removed."""
    index = os.path.join(WORK, "index-%d" % random.getrandbits(64))
    stamp = "@%d +0000" % when
    env = {"GIT_INDEX_FILE": index, "GIT_AUTHOR_NAME": "A Person", "GIT_AUTHOR_EMAIL": "person@example.invalid",
           "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_NAME": "A Person",
           "GIT_COMMITTER_EMAIL": "person@example.invalid", "GIT_COMMITTER_DATE": stamp}
    try:
        git(repo, "read-tree", *(parents[:1] or ["--empty"]), env=env)
        for path, content in files.items():
            if content is None:
                git(repo, "update-index", "--force-remove", "--", path, env=env)
                continue
            mode = "120000" if isinstance(content, Link) else "100755" if isinstance(content, Exe) else "100644"
            blob = git(repo, "hash-object", "-w", "--stdin", data=bytes(content)).decode().strip()
            git(repo, "update-index", "--add", "--cacheinfo", mode, blob, path, env=env)
        tree = git(repo, "write-tree", env=env).decode().strip()
        argv = ["commit-tree", tree] + [word for parent in parents for word in ("-p", parent)] + ["-m", message]
        return git(repo, *argv, env=env).decode().strip()
    finally:
        if os.path.exists(index):
            os.unlink(index)


def item(key, value, executable=False):
    """A source module toy/src/m_<key>.py holding VALUE, and toy/tests/test_<key>.py, which wants `value`."""
    test = ("from src import m_%s\n\n\ndef test_value():\n    assert m_%s.VALUE == %d\n" % (key, key, value)).encode()
    return {"toy/src/m_%s.py" % key: b"VALUE = %d\n" % value,
            "toy/tests/test_%s.py" % key: Exe(test) if executable else test}


def wants(key, value):
    return ("from src import m_%s\n\n\ndef test_value():\n    assert m_%s.VALUE == %d\n" % (key, key, value)).encode()


ROOT_FILES = {
    "toy/uv.lock": b"a lock file stands in here\n",
    "toy/pyproject.toml": b'[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
    "toy/src/__init__.py": b"",
    "toy/src/judged.py": b"def total(values):\n    return 0\n",
    "toy/tests/helper.py": b"EXPECTED = 3\n",
    "docs/notes.md": b"notes\n",
    "other/x.py": b"X = 1\n",
}
# The item the check is tried on. Its source decides whether a test is skipped and how many cases there are.
JUDGED_TEST = b'''import pytest
from src import judged
from tests import helper


def test_sum():
    if getattr(judged, "SKIP", False):
        pytest.skip("skipped by the source")
    assert judged.total([1, 2]) == helper.EXPECTED


def _case(n):
    def case():
        assert judged.total([n]) == n
    return case


for _n in getattr(judged, "CASES", (1,)):
    globals()["test_case_%d" % _n] = _case(_n)
'''
FIXED = b"def total(values):\n    return sum(values)\n"
# Tests whose runs end in ways real pytest does not take, so that each part of a pass is needed alone: an exit
# that is not 0 with no failure, failures or errors with an exit of 0, every test skipped, and no report.
X_TESTS = {
    "x1": b"import atexit\nimport os\n\nfrom src import m_x1\n\nif m_x1.VALUE != 2:\n    atexit.register(os._exit, 3)\n"
          b"\n\ndef test_value():\n    pass\n",
    "x2": b"import atexit\nimport os\n\ntry:\n    from src import m_x2\nexcept ImportError:\n    m_x2 = None\n"
          b"    atexit.register(os._exit, 0)\n\n\ndef test_value():\n    assert m_x2.VALUE == 1\n",
    "x3": b"import atexit\nimport os\n\natexit.register(os._exit, 0)\nfrom src import m_x3  # noqa: E402\n\n\n"
          b"def test_value():\n    assert m_x3.VALUE == 1\n",
    "x4": b"import pytest\n\ntry:\n    from src import m_x4\nexcept ImportError:\n    m_x4 = None\n\n\n"
          b"def test_value():\n    if m_x4 is None:\n        pytest.skip('not yet')\n    assert m_x4.VALUE == 1\n",
    "x5": b"import os\n\ntry:\n    from src import m_x5\nexcept ImportError:\n    os._exit(0)\n\n\n"
          b"def test_value():\n    assert m_x5.VALUE == 1\n",
}
# A test that fails where its file was written with carriage returns.
CRLF_TEST = (b"from src import m_crlf\n\n\ndef test_value():\n"
             b"    assert b'\\r' not in open(__file__, 'rb').read() and m_crlf.VALUE == 1\n")
# Sources that behave apart in a clone, where .git is beside the component, and in a plain copy of the tree.
IN_A_CLONE = b"import os\n\nCLONE = os.path.isdir(os.path.join(os.path.dirname(__file__), '..', '..', '.git'))\n"
# A test whose reference skips one of its two tests: a turn that makes it run skips fewer.
FEWER_SKIPPED_TEST = (b"import pytest\nfrom src import m_fs\n\n\ndef test_value():\n    assert m_fs.VALUE == 1\n\n\n"
                      b"def test_later():\n    if not getattr(m_fs, 'LATER', False):\n        pytest.skip('later')\n")
# A test that passes only when its own file is executable and the link beside its directory is a link.
LAID_OUT_TEST = (b"import os\n\nfrom src import m_lo\n\n\ndef test_value():\n    assert m_lo.VALUE == 1\n"
                 b"    assert os.access(__file__, os.X_OK)\n"
                 b"    assert os.readlink(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'linked')) "
                 b"== 'src'\n")


def slow_in_a_clone(lock, pid_file):
    """A source that, in a clone only, holds a lock on `lock`, writes its process's id to `pid_file` and sleeps."""
    return IN_A_CLONE + ("if CLONE:\n    import fcntl\n    import time\n    held = open(%r, 'a')\n"
                         "    fcntl.flock(held, fcntl.LOCK_EX)\n    open(%r, 'w').write(str(os.getpid()))\n"
                         "    time.sleep(60)\nVALUE = 1\n" % (lock, pid_file)).encode()


def held(lock):
    """Whether a process holds `lock`. A process's locks go when it ends, before anything waits for it, so a lock
    that is free shows its holder has ended, where a signal to its id would still find it until it is waited for."""
    with open(lock, "a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(file, fcntl.LOCK_UN)
        return False


def end_if_held(test, lock, pid_file):
    """Fails `test` if the process that wrote `pid_file` still holds `lock`, and then ends it."""
    with open(pid_file) as file:
        pid = int(file.read())
    if held(lock):
        with contextlib.suppress(OSError):
            os.kill(pid, 9)
        test.fail("the tests the check ran (process %d) are still running" % pid)


def title_key(length):
    """A key whose item's title is `length` characters long."""
    return "w" * (length - len(items.TITLE % ("", TOY["source"])) - len("test_.py"))


class Toy:
    """A repository made commit by commit, each a little later than the one before."""

    def __init__(self, path):
        os.makedirs(path)
        git(path, "init", "-q", "-b", "main")
        self.path, self.when, self.tip, self.named = path, 1_700_000_000, None, {}

    def add(self, name, files, parents=None, when=None):
        self.when += 10
        parents = ([self.tip] if self.tip else []) if parents is None else parents
        made = commit(self.path, parents, files, when or self.when, "%s: MESSAGE-%s" % (name, name.replace(" ", "-")))
        self.named[name] = made
        return made

    def main(self, name, files, parents=None):
        self.tip = self.add(name, files, parents)
        return self.tip

    def finish(self):
        git(self.path, "update-ref", "refs/heads/main", self.tip)
        git(self.path, "reset", "-q", "--hard")


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = items.main(argv)
    return code, out.getvalue(), err.getvalue()


def list_args(repo, first, last, out, python=None, scored=3, pilot=2, more=()):
    return (["list", "--repo", repo, "--first", first, "--last", last, "--component", "toy", "--python",
             python or PYTHON, "--scored", str(scored), "--pilot", str(pilot), "--out", out] + list(more))


class Fixture:
    """The repository most tests read, and its list, made once."""

    made = None

    @classmethod
    def get(cls):
        if cls.made is None:
            cls.made = cls()
        return cls.made

    def __init__(self):
        self.work = tempfile.mkdtemp(dir=WORK, prefix="fixture-")
        self.marker = os.path.join(self.work, "a hostile test ran")
        self.hook_marker = os.path.join(self.work, "a hook ran")
        toy = self.toy = Toy(os.path.join(self.work, "repo"))
        t = toy.main
        t("root", ROOT_FILES)
        t("out", item("out", 1))
        self.first = t("first", {"docs/first.md": b"first\n"})
        hostile = ("open(%r, 'w').write('ran')\n\n\ndef test_value():\n    pass\n" % self.marker).encode()
        # Each of rules 1 to 3, by commits that do not meet it.
        t("helper", dict(item("h", 1), **{"toy/tests/helper.py": b"EXPECTED = 3  # the same\n"}))
        t("subdir", dict(item("fx", 1), **{"toy/tests/fixtures/test_data.py": b"DATA = 1\n"}))
        t("other", dict(item("o", 1), **{"other/x.py": b"X = 2\n"}))
        t("only tests", {"toy/tests/test_ot.py": b"def test_value():\n    assert True\n"})
        t("only source", {"toy/src/m_x1.py": b"VALUE = 1\n"})
        t("four tests", dict({"toy/tests/test_u%d.py" % n: wants("u", 1) for n in range(1, 5)},
                             **{"toy/src/m_u.py": b"VALUE = 1\n"}))
        t("three tests", dict({"toy/tests/test_t%d.py" % n: wants("t", 1) for n in range(1, 4)},
                              **{"toy/src/m_t.py": b"VALUE = 1\n"}))
        t("six sources", dict({"toy/src/m_v%d.py" % n: b"VALUE = 1\n" for n in range(1, 7)},
                              **{"toy/tests/test_v.py": wants("v1", 1)}))
        five = "from src import m_f1, m_f2, m_f3, m_f4, m_f5\n\n\ndef test_value():\n    assert {m.VALUE for m in " \
               "(m_f1, m_f2, m_f3, m_f4, m_f5)} == {1}\n"
        t("five sources", dict({"toy/src/m_f%d.py" % n: b"VALUE = 1\n" for n in range(1, 6)},
                               **{"toy/tests/test_f.py": five.encode(), "docs/b.md": b"a document\n"}))
        t("deleted", dict(item("d", 1), **{"toy/tests/test_t3.py": None}))
        t("browser", item("browser_x", 1))
        t("space", {"toy/tests/test_a b.py": hostile, "toy/src/m_sp.py": b"VALUE = 1\n"})
        t("quote", {"toy/tests/test_it's.py": hostile, "toy/src/m_qu.py": b"VALUE = 1\n"})
        t("source space", {"toy/tests/test_ss.py": hostile, "toy/src/a b.py": b"VALUE = 1\n"})
        t("symlink", dict(item("sl", 1), **{"toy/src/link.py": Link(b"m_sl.py")}))
        t("not python", dict(item("np", 1), **{"toy/src/data.json": b"{}\n"}))
        t("beside the source", dict(item("bs", 1), **{"toy/src_extra/x.py": b"X = 1\n"}))
        # Rule 4 and the title.
        t("pass before", {"toy/tests/test_pb.py": b"def test_value():\n    assert True\n",
                          "toy/src/m_pb.py": b"VALUE = 1\n"})
        t("fail after", {"toy/tests/test_q.py": wants("q", 2), "toy/src/m_q.py": b"VALUE = 1\n"})
        t("title 200", item(title_key(200), 1))
        t("title 201", item(title_key(201), 1))
        # A side branch and its merge, and an unrelated history merged in: a root is no item.
        fork = toy.tip
        side = toy.add("side", item("side", 1), parents=[fork])
        t("main after the fork", item("mf", 1))
        t("merge", item("side", 1), parents=[toy.tip, side])
        orphan = toy.add("orphan", dict(item("orphan", 1), **{"toy/uv.lock": b"another\n"}), parents=[])
        t("merge orphan", {}, parents=[toy.tip, orphan])
        t("judged", {"toy/tests/test_judged.py": JUDGED_TEST, "toy/src/judged.py": FIXED})
        for key, test in sorted(X_TESTS.items()):
            t(key, {"toy/tests/test_%s.py" % key: test, "toy/src/m_%s.py" % key: b"VALUE = %d\n" % (
                2 if key == "x1" else 1)})
        t("crlf", {"toy/tests/test_crlf.py": CRLF_TEST, "toy/src/m_crlf.py": b"VALUE = 1\n"})
        t("fewer skipped", {"toy/tests/test_fs.py": FEWER_SKIPPED_TEST, "toy/src/m_fs.py": b"VALUE = 1\n"})
        # The parts: history, the pilot's, scored and left out by rule 5.
        t("H1", dict(item("k1", 1), **item("s1", 0)))
        t("H2", item("k1", 2, executable=True))
        t("P1", item("p1", 1))
        t("P2a", item("p2", 1))
        t("P2b", item("p2", 2))
        t("A", item("s1", 1))
        t("B", dict(item("s1", 2), **item("s2", 1)))
        t("C", dict(item("s2", 2), **{"toy/tests/test_q.py": wants("q", 3), "toy/src/m_q.py": b"VALUE = 3\n"}))
        t("E", item("s4", 1))
        toy.finish()
        self.repo, self.last = toy.path, toy.tip
        # The work tree and index as a person left them: a change not staged, one staged and a file not tracked.
        with open(os.path.join(self.repo, "docs", "notes.md"), "a") as out:
            out.write("an edit not staged\n")
        with open(os.path.join(self.repo, "other", "x.py"), "a") as out:
            out.write("Y = 2\n")
        git(self.repo, "add", "other/x.py")
        with open(os.path.join(self.repo, "untracked.txt"), "w") as out:
            out.write("not tracked\n")
        # A hook that would say if one ran: update-ref runs reference-transaction.
        hook = os.path.join(self.repo, ".git", "hooks", "reference-transaction")
        with open(hook, "w") as out:
            out.write("#!/bin/sh\necho ran >> '%s'\n" % self.hook_marker)
        os.chmod(hook, 0o755)
        self.before = self.state()
        self.out = os.path.join(self.work, "out-1")
        self.code, self.printed, self.said = run_main(list_args(self.repo, self.first, self.last, self.out))
        assert self.code == 0, (self.printed, self.said)
        with open(os.path.join(self.out, "items.json"), "rb") as file:
            self.bytes = file.read()
        self.list = json.loads(self.bytes)
        self.by_commit = {entry["commit"]: entry for entry in self.list["commits"]}

    def state(self):
        """The repository's index, work tree and branches, read without writing anything."""
        with open(os.path.join(self.repo, ".git", "index"), "rb") as file:
            index = file.read()
        status = git(self.repo, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                     env={"GIT_OPTIONAL_LOCKS": "0"})
        with open(os.path.join(self.repo, "docs", "notes.md"), "rb") as file:
            notes = file.read()
        return (index, status, notes, git(self.repo, "for-each-ref", "refs/heads", "refs/tags"),
                git(self.repo, "symbolic-ref", "HEAD"), git(self.repo, "rev-parse", "HEAD"))

    def entry(self, name):
        return self.by_commit[self.toy.named[name]]


class TheOrder(unittest.TestCase):
    def test_the_same_list_whatever_order_the_commits_are_read_out_in(self):
        commits = [("r", 10, ()), ("a", 30, ("r",)), ("b", 20, ("r",)), ("m", 25, ("a", "b")), ("c", 5, ("m",)),
                   ("d", 30, ("r",))]
        want = items.order(commits)
        # After a, the free are d (30) and m (25): m first, then c (5), freed by m, and d last.
        self.assertEqual(want, ["r", "b", "a", "m", "c", "d"])
        draw = random.Random(7)
        for _ in range(20):
            shuffled = commits[:]
            draw.shuffle(shuffled)
            self.assertEqual(items.order(shuffled), want)

    def test_two_commits_at_one_committer_time_go_by_id(self):
        one = "1" * 40
        commits = [("f" * 40, 100, (one,)), ("e" * 40, 100, (one,)), (one, 50, ())]
        self.assertEqual(items.order(commits), [one, "e" * 40, "f" * 40])

    def test_a_commit_is_never_before_one_it_descends_from_with_a_merge_between(self):
        # z is the earliest by time, and descends from x, the latest, through the merge m.
        commits = [("root", 0, ()), ("x", 500, ("root",)), ("y", 50, ("root",)), ("m", 100, ("x", "y")),
                   ("z", 1, ("m",))]
        self.assertEqual(items.order(commits), ["root", "y", "x", "m", "z"])

    def test_a_parent_outside_the_bounds_holds_nothing_back(self):
        self.assertEqual(items.order([("a", 2, ("outside",)), ("b", 1, ("before",))]), ["b", "a"])


class TheParts(unittest.TestCase):
    """parts() alone, on eligible commits named by letters; the letters in brackets are their test files."""

    def divided(self, eligible, scored, pilot):
        part, place, dividing = items.parts([(name, set(files)) for name, files in eligible], scored, pilot)
        return part, place, dividing

    def test_the_readers_first_case_the_later_of_two_is_kept_going_back(self):
        eligible = [("A1", "a"), ("B1", "b"), ("A2", "a"), ("C1", "c"), ("S1", "s"), ("S2", "t")]
        part, place, dividing = self.divided(eligible, 2, 3)
        self.assertEqual(dividing, "C1")
        self.assertEqual({name for name, given in part.items() if given == items.PILOT}, {"B1", "A2", "C1"})
        # A1 comes before the earliest of the pilot's, so it is history, which rule 5 does not hold (spec rev. 7).
        self.assertEqual(part["A1"], items.HISTORY)
        self.assertEqual(place, {"S1": 1, "S2": 2})

    def test_the_readers_second_case_forty_three_apart(self):
        eligible = [("c%02d" % n, ["t%02d" % n]) for n in range(43)]
        part, place, dividing = self.divided(eligible, 40, 3)
        self.assertEqual(dividing, "c02")
        self.assertEqual([name for name, _ in eligible if part[name] == items.PILOT], ["c00", "c01", "c02"])
        self.assertNotIn(items.HISTORY, part.values())
        self.assertEqual(sorted(place.values()), list(range(1, 41)))
        self.assertEqual(place["c03"], 1)

    FIXTURE = [("H0", "h"), ("H1", ["k1", "s1"]), ("H2", "k"), ("P1", ["p1"]), ("P2a", ["p2"]), ("P2b", ["p2"]),
               ("A", ["s1"]), ("B", ["s1", "s2"]), ("C", ["s2", "q"]), ("E", ["s4"])]

    def test_the_dividing_commit_and_each_part(self):
        part, place, dividing = self.divided(self.FIXTURE, 3, 2)
        self.assertEqual(dividing, "P2b")
        self.assertEqual(part, {"H0": items.HISTORY, "H1": items.HISTORY, "H2": items.HISTORY, "P1": items.PILOT,
                                "P2a": items.RULE_5, "P2b": items.PILOT, "A": items.SCORED, "B": items.RULE_5,
                                "C": items.SCORED, "E": items.SCORED})
        self.assertEqual(place, {"A": 1, "C": 2, "E": 3})

    def test_the_dividing_commit_is_one_earlier_when_a_late_commit_is_not_eligible(self):
        part, _, dividing = self.divided(self.FIXTURE[:-1], 3, 2)
        self.assertEqual(dividing, "P2a")
        self.assertEqual(part["P2b"], items.SCORED)

    def test_exactly_as_many_scored_as_asked_is_enough(self):
        part, place, dividing = self.divided([("P", "p"), ("S1", "a"), ("S2", "b")], 2, 1)
        self.assertEqual((dividing, len(place)), ("P", 2))

    def test_the_pilot_stops_at_the_number_asked_and_history_is_before_it(self):
        part, _, _ = self.divided([("H", "a"), ("Q", "b"), ("P", "c"), ("S", "d")], 1, 1)
        self.assertEqual((part["H"], part["Q"], part["P"]), (items.HISTORY, items.HISTORY, items.PILOT))

    def test_history_may_name_one_test_file_many_times(self):
        part, _, _ = self.divided([("H1", "a"), ("H2", "a"), ("H3", "a"), ("P", "b"), ("S", "a")], 1, 1)
        self.assertEqual([part[name] for name in ("H1", "H2", "H3")], [items.HISTORY] * 3)

    def test_too_few_for_the_scored_is_refused_by_name(self):
        # The last: nothing is after it. Three that name one file: one is found after any of them.
        for eligible, scored in (([], 1), ([("A", "a")], 1), ([("A", "a"), ("B", "a"), ("C", "a")], 2)):
            with self.subTest(eligible), self.assertRaisesRegex(items.Refused, "^too few for the scored"):
                self.divided(eligible, scored, 1)

    def test_too_few_for_the_pilot_is_refused_by_name(self):
        for eligible in ([("A", "a"), ("S", "s")], [("A", "a"), ("B", "a"), ("S", "s")]):
            with self.subTest(eligible), self.assertRaisesRegex(items.Refused, "^too few for the pilot"):
                self.divided(eligible, 1, 2)


class TheList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = Fixture.get()

    def listed(self, *names):
        return [self.f.toy.named[name] in self.f.by_commit for name in names]

    def test_each_rule_by_a_commit_that_meets_it_and_one_that_does_not(self):
        f = self.f
        met = ["three tests", "five sources", "pass before", "fail after", "title 200", "title 201", "side",
               "main after the fork", "judged", "x1", "x2", "x3", "x4", "x5", "crlf", "fewer skipped", "H1", "H2",
               "P1", "P2a", "P2b", "A", "B", "C", "E"]
        not_met = ["root", "out", "first", "helper", "subdir", "other", "only tests", "only source", "four tests",
                   "six sources", "deleted", "browser", "space", "quote", "source space", "symlink", "not python",
                   "beside the source",
                   "merge", "orphan", "merge orphan"]
        self.assertEqual(self.listed(*met), [True] * len(met))
        self.assertEqual(self.listed(*not_met), [False] * len(not_met))
        self.assertEqual(len(f.list["commits"]), len(met))
        reasons = {name: f.entry(name).get("reason") for name in met}
        self.assertEqual({name: why for name, why in reasons.items() if why}, {
            "pass before": items.PASS_BEFORE, "fail after": items.FAIL_AFTER, "title 201": items.TITLE_TOO_LONG})

    def test_the_commits_are_listed_in_order(self):
        named = {commit: name for name, commit in self.f.toy.named.items()}
        order = [named[entry["commit"]] for entry in self.f.list["commits"]]
        self.assertEqual(order[:3], ["three tests", "five sources", "pass before"])
        self.assertLess(order.index("side"), order.index("main after the fork"))
        self.assertEqual(order[-4:], ["A", "B", "C", "E"])

    def test_the_parts_the_dividing_commit_and_the_places(self):
        f = self.f
        self.assertEqual(f.list["dividing"], f.toy.named["P2b"])
        parts = {name: f.entry(name)["part"] for name in ("H1", "H2", "P1", "P2a", "P2b", "A", "B", "C", "E")}
        self.assertEqual(parts, {"H1": items.HISTORY, "H2": items.HISTORY, "P1": items.PILOT, "P2a": items.RULE_5,
                                 "P2b": items.PILOT, "A": items.SCORED, "B": items.RULE_5, "C": items.SCORED,
                                 "E": items.SCORED})
        # B names test_s1.py, which A, scored before it, names; H1, history, names it too and stays history. C names
        # test_q.py, which "fail after" named: rule 4 left that one out, so C is not left out for it.
        self.assertEqual([f.entry(name).get("place") for name in ("A", "B", "C", "E")], [1, None, 2, 3])
        self.assertEqual({f.entry(name)["part"] for name in ("judged", "x1", "crlf", "fewer skipped", "side")},
                         {items.HISTORY})

    def test_the_counts_add_up_to_the_commits_that_met_rules_1_to_3(self):
        counts = self.f.list["counts"]
        self.assertEqual(counts["by_part"], {"history": 15, "pilot": 2, "scored": 3, "left out by rule 5": 2})
        self.assertEqual(counts["by_reason"], {"rule 4: the tests pass before the change": 1,
                                               "rule 4: the tests fail after the change": 1,
                                               "rule 4: past the limit": 0, "the title would be too long": 1})
        total = sum(counts["by_part"].values()) + sum(counts["by_reason"].values())
        self.assertEqual(total, counts["met rules 1 to 3"])
        self.assertEqual(total, len(self.f.list["commits"]))

    def test_an_eligible_commit_is_listed_with_its_item(self):
        f = self.f
        entry = f.entry("judged")
        self.assertEqual(entry["title"], "Make the failing tests in test_judged.py pass by changing the code under "
                                         "toy/src, not the tests.")
        self.assertEqual(entry["tests"], ["toy/tests/test_judged.py"])
        self.assertEqual(entry["counts"], {"passed": 2, "skipped": 0})
        self.assertEqual(entry["check"], {"command": "python3 -I .yak-check/check.py", "files": [
            ".yak-check/check.py", ".yak-check/item.json", "toy/tests/test_judged.py"]})
        self.assertEqual(set(entry), {"base", "check", "commit", "counts", "part", "reference", "tests", "title",
                                      "wrong"})
        three = f.entry("three tests")
        self.assertEqual(three["title"], "Make the failing tests in test_t1.py, test_t2.py, test_t3.py pass by "
                                         "changing the code under toy/src, not the tests.")
        self.assertEqual(len(f.entry("title 200")["title"]), 200)
        self.assertEqual(set(f.entry("pass before")), {"commit", "reason"})

    def test_the_list_says_its_bounds_component_lock_and_interpreter(self):
        f, written = self.f, self.f.list
        self.assertEqual((written["first"], written["last"], written["component"]), (f.first, f.last, "toy"))
        self.assertEqual(written["lock_sha256"], hashlib.sha256(ROOT_FILES["toy/uv.lock"]).hexdigest())
        said = subprocess.run([PYTHON, "-I", "-c", "import platform; print(platform.python_version())"],
                              stdout=subprocess.PIPE).stdout.decode().strip()
        self.assertEqual(written["python"], "cpython " + said)
        self.assertEqual(written["asked"], {"limit_secs": 300, "pilot": 2, "scored": 3})
        self.assertNotIn(WORK.encode(), f.bytes)
        self.assertEqual(f.bytes, (json.dumps(written, sort_keys=True, indent=1) + "\n").encode("ascii"))

    def test_it_prints_the_lists_sha256_and_the_interpreters_path_apart(self):
        f = self.f
        self.assertIn("sha256 %s\n" % hashlib.sha256(f.bytes).hexdigest(), f.printed)
        self.assertIn("the tests were run by %s " % PYTHON, f.printed)

    def test_the_base_has_one_parent_the_fixed_message_name_and_time(self):
        f = self.f
        for name in ("judged", "H2", "E"):
            entry, commit = f.entry(name), f.toy.named[name]
            parent = git(f.repo, "rev-parse", commit + "^").decode().strip()
            when = git(f.repo, "log", "-1", "--format=%ct", parent).decode().strip()
            raw = git(f.repo, "cat-file", "commit", entry["base"]).decode()
            head, _, message = raw.partition("\n\n")
            self.assertEqual([line for line in head.splitlines() if line.startswith("parent ")], ["parent " + parent])
            self.assertIn("\nauthor yak items <items@yak.invalid> %s +0000\n" % when, head + "\n")
            self.assertIn("\ncommitter yak items <items@yak.invalid> %s +0000\n" % when, head + "\n")
            self.assertEqual(message, "tests first\n")
            # Its tree is the parent's with the commit's test files and the check's two files laid over it.
            changed = git(f.repo, "diff-tree", "-r", "--name-only", parent, entry["base"]).decode().split()
            self.assertEqual(changed, sorted([".yak-check/check.py", ".yak-check/item.json"] + entry["tests"]))
            # Each test file is the commit's own, mode and all.
            for path in entry["tests"]:
                self.assertEqual(git(f.repo, "ls-tree", entry["base"], "--", path),
                                 git(f.repo, "ls-tree", commit, "--", path))
            with open(os.path.join(HERE, "check.py"), "rb") as file:
                self.assertEqual(git(f.repo, "cat-file", "blob", entry["base"] + ":.yak-check/check.py"), file.read())

    def test_the_reference_and_the_wrong_commit(self):
        f = self.f
        entry, commit = f.entry("five sources"), f.toy.named["five sources"]
        for made, message, files in ((entry["reference"], "the reference", ["toy/src/m_f%d.py" % n for n in
                                                                             range(1, 6)]),
                                     (entry["wrong"], "an unrelated file", [".yak-check/unrelated.txt"])):
            raw = git(f.repo, "cat-file", "commit", made).decode()
            self.assertIn("\nparent %s\n" % entry["base"], raw)
            self.assertTrue(raw.endswith("\n\n%s\n" % message), raw)
            self.assertEqual(git(f.repo, "diff-tree", "-r", "--name-only", entry["base"], made).decode().split(),
                             files)
        # The reference is the commit's own tree but for its documents and the check's files.
        self.assertEqual(git(f.repo, "diff-tree", "-r", "--name-only", commit, entry["reference"]).decode().split(),
                         [".yak-check/check.py", ".yak-check/item.json", "docs/b.md"])
        self.assertEqual(git(f.repo, "cat-file", "blob", entry["wrong"] + ":.yak-check/unrelated.txt"),
                         b"A file that changes nothing the tests run.\n")

    def test_item_json_says_the_item_and_nothing_of_the_commit(self):
        f = self.f
        entry = f.entry("judged")
        parent = git(f.repo, "rev-parse", f.toy.named["judged"] + "^").decode().strip()
        blob = git(f.repo, "rev-parse", f.toy.named["judged"] + ":toy/tests/test_judged.py").decode().strip()
        said = json.loads(git(f.repo, "cat-file", "blob", entry["base"] + ":.yak-check/item.json"))
        self.assertEqual(said, {"component": "toy", "parent": parent, "passed": 2, "skipped": 0, "source": "toy/src",
                                "tests": [{"blob": blob, "path": "toy/tests/test_judged.py"}]})
        for name, commit in f.toy.named.items():
            entry = f.by_commit.get(commit)
            if not entry or "base" not in entry:
                continue
            message = "MESSAGE-" + name.replace(" ", "-")
            for made in (entry["base"], entry["reference"], entry["wrong"]):
                for raw in (git(f.repo, "cat-file", "commit", made),
                            git(f.repo, "cat-file", "blob", made + ":.yak-check/item.json")):
                    with self.subTest(name=name, made=made):
                        self.assertNotIn(commit.encode(), raw)
                        self.assertNotIn(commit[:7].encode(), raw)
                        self.assertNotIn(message.encode(), raw)

    def test_the_repository_is_as_it_was_and_the_items_are_kept_as_refs(self):
        f = self.f
        self.assertEqual(f.state(), f.before)
        self.assertFalse(os.path.exists(f.hook_marker), "a hook ran in the repository")
        refs = dict(line.split()[::-1] for line in git(f.repo, "for-each-ref", "--format=%(objectname) %(refname)",
                                                       "refs/yak-items/").decode().splitlines())
        eligible = [entry for entry in f.list["commits"] if "part" in entry]
        self.assertEqual(len(refs), 3 * len(eligible))
        for entry in eligible:
            for kind in ("base", "reference", "wrong"):
                self.assertEqual(refs["refs/yak-items/%s/%s" % (entry["commit"], kind)], entry[kind])

    def test_a_hostile_test_files_name_is_left_out_by_rule_2_and_never_run(self):
        self.assertEqual(self.listed("space", "quote", "source space"), [False] * 3)
        self.assertFalse(os.path.exists(self.f.marker))

    def test_a_list_is_written_once(self):
        f = self.f
        code, printed, _ = run_main(list_args(f.repo, f.first, f.last, f.out))
        self.assertEqual(code, 1)
        self.assertRegex(printed, r"^REFUSED: .*items\.json is there already: a list is written once\n$")
        with open(os.path.join(f.out, "items.json"), "rb") as file:
            self.assertEqual(file.read(), f.bytes)


class TheSameList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = Fixture.get()

    def test_the_same_bytes_twice(self):
        f = self.f
        out = os.path.join(f.work, "out-2")
        code, printed, said = run_main(list_args(f.repo, f.first, f.last, out))
        self.assertEqual(code, 0, printed + said)
        with open(os.path.join(out, "items.json"), "rb") as file:
            self.assertEqual(file.read(), f.bytes)

    def test_the_same_bytes_from_a_second_clone_elsewhere_whatever_its_settings_and_order(self):
        f = self.f
        clone = os.path.join(f.work, "elsewhere", "a second clone")
        os.makedirs(os.path.dirname(clone))
        subprocess.run(["git", "clone", "-q", f.repo, clone], env=GIT_ENV, check=True)
        # Settings and a replaced commit that would change the list if git took them in.
        git(clone, "config", "i18n.commitEncoding", "ISO-8859-1")
        git(clone, "config", "core.autocrlf", "true")
        git(clone, "replace", "--graft", f.toy.named["H1"], f.toy.named["root"])
        out = os.path.join(f.work, "out-3")
        read = items.read_commits
        items.read_commits = lambda *args: list(reversed(read(*args)))
        try:
            code, printed, said = run_main(list_args(clone, f.first, f.last, out, python=ALIAS))
        finally:
            items.read_commits = read
        self.assertEqual(code, 0, printed + said)
        self.assertIn("the tests were run by %s " % ALIAS, printed)
        with open(os.path.join(out, "items.json"), "rb") as file:
            self.assertEqual(file.read(), f.bytes)


def place(root, path, data):
    """Writes `data` at `path` under `root`, replacing what is in the way, as the room writes a frozen copy."""
    at = os.path.join(root, path)
    if os.path.isdir(at) and not os.path.islink(at):
        shutil.rmtree(at)
    elif os.path.lexists(at):
        os.unlink(at)
    os.makedirs(os.path.dirname(at), exist_ok=True)
    with open(at, "wb") as out:
        out.write(data)


class TheCheck(unittest.TestCase):
    """check.py run as the room's run_check runs it: in a fresh clone holding what the commit judged reaches,
    with the frozen copies of the check's files written over theirs, by `python3 -I .yak-check/check.py` at the
    clone's root, with the environment's interpreter first on the path."""

    @classmethod
    def setUpClass(cls):
        cls.f = Fixture.get()
        cls.item = cls.f.entry("judged")
        cls.parent = git(cls.f.repo, "rev-parse", cls.f.toy.named["judged"] + "^").decode().strip()

    def judged(self, commit, also=(), gone=False, path_first=None, then=None, entry=None):
        f, entry = self.f, entry or self.item
        where = tempfile.mkdtemp(dir=WORK, prefix="judged-")
        clone = os.path.join(where, "clone")
        if gone:
            # A checkout that is not a repository, inside one that is: nothing is found by looking above it.
            git(where, "init", "-q")
            git(where, "commit", "-q", "--allow-empty", "-m", "above", env={
                "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b.invalid", "GIT_COMMITTER_NAME": "a",
                "GIT_COMMITTER_EMAIL": "a@b.invalid"})
        git(where, "init", "-q", clone)
        git(clone, "-c", "protocol.version=2", "-c", "protocol.file.allow=always", "fetch", "-q", "--no-tags",
            "--no-write-fetch-head", f.repo, commit, *also)
        git(clone, "checkout", "-q", "-b", "turn", commit)
        for path in entry["check"]["files"]:
            place(clone, path, git(f.repo, "cat-file", "blob", "%s:%s" % (entry["base"], path)))
        if gone:
            shutil.rmtree(os.path.join(clone, ".git"))
        if then:
            then(clone)
        home = os.path.join(where, "home")
        os.mkdir(home)
        path = os.pathsep.join(([path_first] if path_first else []) + [os.path.dirname(PYTHON), GIT_ENV["PATH"]])
        done = subprocess.run(["python3", "-I", ".yak-check/check.py"], cwd=clone, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env={"PATH": path, "HOME": home, "TMPDIR": home})
        return done.returncode, done.stdout.decode(), done.stderr.decode()

    def turn(self, files, on=None, message="a turn"):
        return commit(self.f.repo, [on or self.item["base"]], files, 1_800_000_000, message)

    def fails(self, commit, says, **how):
        code, out, err = self.judged(commit, **how)
        self.assertEqual((code, out), (1, ""), err)
        self.assertTrue(err.startswith("FAIL " + says), err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertNotIn("Traceback", err)

    def test_the_reference_passes(self):
        self.assertEqual(self.judged(self.item["reference"]), (0, "ok\n", ""))

    def test_a_turn_with_only_source_changes_that_passes_passes(self):
        turn = self.turn({"toy/src/judged.py": FIXED + b"# tidied\n", "toy/src/new.py": b"X = 1\n"})
        self.assertEqual(self.judged(turn), (0, "ok\n", ""))

    def test_more_passed_than_the_reference_passes(self):
        # Three cases where the reference had two, none skipped.
        turn = self.turn({"toy/src/judged.py": FIXED + b"CASES = (1, 2)\n"})
        self.assertEqual(self.judged(turn), (0, "ok\n", ""))

    def test_fewer_skipped_than_the_reference_passes(self):
        entry = self.f.entry("fewer skipped")
        self.assertEqual(entry["counts"], {"passed": 1, "skipped": 1})
        turn = commit(self.f.repo, [entry["base"]], {"toy/src/m_fs.py": b"VALUE = 1\nLATER = True\n"}, 1_800_000_000)
        self.assertEqual(self.judged(turn, entry=entry), (0, "ok\n", ""))

    def test_what_the_tests_left_is_ended_when_the_check_ends(self):
        # Run as the room runs it, with no word to share a group: the process the tests leave holds a lock until it
        # is ended, and the check ends it.
        lock, pid_file = os.path.join(WORK, "left-by-a-turn.lock"), os.path.join(WORK, "left-by-a-turn.pid")
        left = ("import fcntl\nimport subprocess\n\n_held = open(%r, 'a')\nfcntl.flock(_held, fcntl.LOCK_EX)\n"
                "_left = subprocess.Popen(['/bin/sleep', '60'], pass_fds=(_held.fileno(),))\n"
                "open(%r, 'w').write(str(_left.pid))\n" % (lock, pid_file)).encode()
        turn = self.turn({"toy/src/judged.py": FIXED + left})
        self.assertEqual(self.judged(turn), (0, "ok\n", ""))
        end_if_held(self, lock, pid_file)

    def test_each_failure_by_name(self):
        outside = "1: a path outside toy/src changed: "
        test_file = "1: the test file toy/tests/test_judged.py is not the item's"
        base = self.item["base"]
        remade = commit(self.f.repo, [self.parent], {
            "toy/tests/helper.py": b"EXPECTED = 0\n", "toy/tests/test_judged.py": JUDGED_TEST,
            ".yak-check/check.py": git(self.f.repo, "cat-file", "blob", base + ":.yak-check/check.py"),
            ".yak-check/item.json": git(self.f.repo, "cat-file", "blob", base + ":.yak-check/item.json")}, 1_800_000_000)
        cases = [
            ("the base", base, "2: the tests did not pass (exit 1, 2 failed, 0 errors)"),
            ("the wrong commit", self.item["wrong"], outside + '".yak-check/unrelated.txt"'),
            ("a changed test file", self.turn({"toy/tests/test_judged.py": b"def test_sum():\n    pass\n"}),
             test_file),
            ("an added conftest.py", self.turn({"toy/src/judged.py": FIXED, "toy/tests/conftest.py": b"X = 1\n"}),
             outside + '"toy/tests/conftest.py"'),
            ("a changed helper", self.turn({"toy/src/judged.py": FIXED, "toy/tests/helper.py": b"EXPECTED = 3  #\n"}),
             outside + '"toy/tests/helper.py"'),
            ("a test file's bytes", self.turn({"toy/src/judged.py": FIXED,
                                               "toy/tests/test_judged.py": JUDGED_TEST + b"# more\n"}), test_file),
            ("the tests' configuration", self.turn({"toy/src/judged.py": FIXED, "toy/pyproject.toml": b""}),
             outside + '"toy/pyproject.toml"'),
            ("another component", self.turn({"toy/src/judged.py": FIXED, "other/x.py": b"X = 3\n"}),
             outside + '"other/x.py"'),
            ("a directory beside the source's", self.turn({"toy/src/judged.py": FIXED,
                                                           "toy/src_extra/x.py": b"X = 2\n"}),
             outside + '"toy/src_extra/x.py"'),
            ("the tests skipped by the source", self.turn({"toy/src/judged.py": FIXED + b"SKIP = True\n"}),
             "3: 1 tests passed, fewer than the reference's 2"),
            ("more skipped and as many passed", self.turn({"toy/src/judged.py": FIXED +
                                                           b"SKIP = True\nCASES = (1, 2)\n"}),
             "3: 1 tests were skipped, more than the reference's 0"),
            ("a deleted test file", self.turn({"toy/src/judged.py": FIXED, "toy/tests/test_judged.py": None}),
             test_file),
            ("a history made again from the parent", self.turn({"toy/src/judged.py": FIXED}, on=remade),
             outside + '"toy/tests/helper.py"'),
            ("a second file under .yak-check", self.turn({"toy/src/judged.py": FIXED,
                                                          ".yak-check/notes.txt": b"notes\n"}),
             outside + '".yak-check/notes.txt"'),
            ("item.json changed in the commit", self.turn({"toy/src/judged.py": FIXED,
                                                           ".yak-check/item.json": b"{}\n"}),
             "1: .yak-check/item.json at the commit judged is not the copy this check runs with"),
            ("check.py changed in the commit", self.turn({"toy/src/judged.py": FIXED,
                                                          ".yak-check/check.py": b"print('ok')\n"}),
             "1: .yak-check/check.py at the commit judged is not the copy this check runs with"),
            ("an exit that is not 0", self.turn({"toy/src/judged.py": FIXED + b"import atexit\nimport os\n"
                                                 b"atexit.register(os._exit, 7)\n"}),
             "2: the tests did not pass (exit 7, 0 failed, 0 errors)"),
            ("failures with an exit of 0", self.turn({"toy/src/judged.py": b"import atexit\nimport os\n"
                                                      b"atexit.register(os._exit, 0)\n\n\ndef total(values):\n"
                                                      b"    return 0\n"}),
             "2: the tests did not pass (exit 0, 2 failed, 0 errors)"),
            ("errors with an exit of 0", self.turn({"toy/src/judged.py": b"import atexit\nimport os\n"
                                                    b"atexit.register(os._exit, 0)\nraise RuntimeError('broken')\n"}),
             "2: the tests did not pass (exit 0, 0 failed, 1 errors)"),
            ("no report", self.turn({"toy/src/judged.py": b"import os\nos._exit(0)\n"}),
             "2: the tests wrote no report that can be read (exit 0)"),
        ]
        for name, judged, says in cases:
            with self.subTest(name):
                self.fails(judged, says)

    def test_a_commit_that_does_not_descend_from_the_parent(self):
        tree = git(self.f.repo, "rev-parse", self.item["reference"] + "^{tree}").decode().strip()
        orphan = git(self.f.repo, "commit-tree", tree, "-m", "the same files, another history", env={
            "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b.invalid", "GIT_COMMITTER_NAME": "a",
            "GIT_COMMITTER_EMAIL": "a@b.invalid"}).decode().strip()
        with self.subTest("the parent is in the clone"):
            self.fails(orphan, "1: the commit judged does not descend from the item's parent", also=(self.parent,))
        with self.subTest("a clone in which the parent is not there"):
            self.fails(orphan, "1: the item's parent %s is not in this repository" % self.parent)

    def test_a_checkout_that_is_not_a_repository(self):
        self.fails(self.item["reference"], "1: the checkout is not a git repository with a commit", gone=True)

    def test_a_clone_in_which_what_changed_cannot_be_listed(self):
        def lose_the_parents_tree(clone):
            # The parent's commit stays, so that it is found and is an ancestor; its root tree, which only listing
            # what changed reads, is taken away. Each object is made loose first, so that one can be taken.
            objects = os.path.join(clone, ".git", "objects")
            packs = os.path.join(objects, "pack")
            moved = tempfile.mkdtemp(dir=WORK, prefix="packs-")
            for name in os.listdir(packs):
                os.rename(os.path.join(packs, name), os.path.join(moved, name))
            for name in sorted(os.listdir(moved)):
                if name.endswith(".pack"):
                    with open(os.path.join(moved, name), "rb") as pack:
                        git(clone, "unpack-objects", "-q", data=pack.read())
            tree = git(clone, "rev-parse", self.parent + "^{tree}").decode().strip()
            os.unlink(os.path.join(objects, tree[:2], tree[2:]))
            self.assertEqual(git(clone, "cat-file", "-t", self.parent).decode().strip(), "commit")

        self.fails(self.item["reference"], "1: cannot list what changed since the item's parent",
                   then=lose_the_parents_tree)

    def test_a_git_committed_in_the_checkout_is_never_run(self):
        marker = os.path.join(WORK, "a committed git ran")
        turn = self.turn({"toy/src/judged.py": FIXED, "git": Exe(b"#!/bin/sh\necho ran > '%s'\nexit 0\n" %
                                                                   marker.encode())})
        self.fails(turn, '1: a path outside toy/src changed: "git"', path_first=".")
        self.assertFalse(os.path.exists(marker))

    def test_a_check_that_cannot_run_says_so_on_one_line(self):
        judge = check.judge
        check.judge = lambda root: [][0]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = check.main()
        finally:
            check.judge = judge
        self.assertEqual((code, out.getvalue(), err.getvalue()), (1, "", "FAIL 0: the check could not run "
                                                                         "(IndexError)\n"))


class ItemJsonHeldToItsForm(unittest.TestCase):
    """check.py given item.json files that the item-maker never writes: each is refused on one line. The limits are
    written out as numbers, not read from check.py, so that a limit changed there fails here."""

    GOOD = {"component": "toy", "parent": "a" * 40, "passed": 2, "skipped": 0, "source": "toy/src",
            "tests": [{"blob": "b" * 40, "path": "toy/tests/test_a.py"}]}
    # What check.py says next for a form it accepts, in a directory that is no repository.
    ACCEPTED = "FAIL 1: the checkout is not a git repository with a commit\n"

    def judged(self, content, link=False):
        root = tempfile.mkdtemp(dir=WORK, prefix="form-")
        os.makedirs(os.path.join(root, ".yak-check"))
        shutil.copy(os.path.join(HERE, "check.py"), os.path.join(root, ".yak-check", "check.py"))
        target = os.path.join(root, ".yak-check", "item.json")
        if link:
            with open(os.path.join(root, "elsewhere.json"), "wb") as out:
                out.write(content)
            os.symlink(os.path.join(root, "elsewhere.json"), target)
        elif content is not None:
            with open(target, "wb") as out:
                out.write(content)
        else:
            os.mkdir(target)
        done = subprocess.run([PYTHON, "-I", ".yak-check/check.py"], cwd=root, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env={"PATH": GIT_ENV["PATH"], "HOME": root, "TMPDIR": root})
        return done.returncode, done.stdout.decode(), done.stderr.decode()

    def with_(self, **changed):
        made = json.loads(json.dumps(self.GOOD))
        for key, value in changed.items():
            if value is KeyError:
                del made[key]
            else:
                made[key] = value
        return json.dumps(made).encode()

    def test_a_good_form_is_accepted_and_the_check_goes_on(self):
        for name, content in [("good", self.with_()),
                              ("the most tests a count may say", self.with_(passed=1_000_000, skipped=1_000_000)),
                              ("three test files", self.with_(tests=[{"blob": "b" * 40, "path": "toy/tests/t%d.py" % n}
                                                                     for n in range(3)])),
                              ("an item of the largest size", self.with_().ljust(65536)),
                              ("a sha256 repository's ids", self.with_(parent="a" * 64, tests=[
                                  {"blob": "b" * 64, "path": "toy/tests/test_a.py"}]))]:
            with self.subTest(name):
                self.assertEqual(self.judged(content), (1, "", self.ACCEPTED))

    def test_each_wrong_form_is_refused_on_one_line(self):
        keys = "0: .yak-check/item.json must hold exactly the keys"
        count = "0: .yak-check/item.json's %s is not a whole number"
        test = "0: .yak-check/item.json names a test file that is not a plain path"
        tests = "0: .yak-check/item.json's tests are not a list of 1 to 3"
        each = "0: .yak-check/item.json's tests must each hold exactly the keys"
        blob = "0: .yak-check/item.json names a test file's blob"
        source = "0: .yak-check/item.json's source is not a plain path under its component"
        component = "0: .yak-check/item.json's component is not a plain name"
        parent = "0: .yak-check/item.json's parent is not a commit id"
        strict = "0: .yak-check/item.json is not strict JSON"
        unreadable = "0: .yak-check/item.json is not a regular file of at most 65536 bytes"
        a_test = lambda **changed: dict({"blob": "b" * 40, "path": "toy/tests/test_a.py"}, **changed)  # noqa: E731
        cases = [
            ("not JSON", b"{", strict), ("not UTF-8", b'{"\xff": 1}', strict),
            ("a key given twice", self.with_()[:-1] + b', "passed": 1}', strict),
            ("nested past the stack", b"[" * 60000, strict),
            ("a list", b"[]", keys), ("a number", b"5", keys), ("an unknown field", self.with_(extra=1), keys),
            ("a field missing", self.with_(skipped=KeyError), keys),
            ("a component that is a number", self.with_(component=5), component),
            ("a component that is a path", self.with_(component="toy/x"), component),
            ("a component with a lone surrogate", self.with_(component="\ud800"), component),
            ("a source with ..", self.with_(source="toy/../etc"), source),
            ("a source with a line end", self.with_(source="toy/sr\nc"), source),
            ("a source outside the component", self.with_(source="other/src"), source),
            ("a source that is a list", self.with_(source=["toy/src"]), source),
            ("a parent in capitals", self.with_(parent="A" * 40), parent),
            ("a parent of 50", self.with_(parent="a" * 50), parent),
            ("a parent that is a number", self.with_(parent=1), parent),
            ("passed as words", self.with_(passed="2"), count % "passed"),
            ("passed true", self.with_(passed=True), count % "passed"),
            ("passed as a fraction", self.with_(passed=2.0), count % "passed"),
            ("passed 0", self.with_(passed=0), count % "passed"),
            ("skipped below nothing", self.with_(skipped=-1), count % "skipped"),
            ("skipped 10**30", self.with_(skipped=10 ** 30), count % "skipped"),
            ("passed 10**30", self.with_(passed=10 ** 30), count % "passed"),
            ("passed past the most", self.with_(passed=1_000_001), count % "passed"),
            ("skipped past the most", self.with_(skipped=1_000_001), count % "skipped"),
            ("passed NaN", self.with_()[:-1] + b', "passed": NaN}', strict),
            ("tests empty", self.with_(tests=[]), tests),
            ("four test files", self.with_(tests=[a_test(path="toy/tests/t%d.py" % n) for n in range(4)]), tests),
            ("tests a short string", self.with_(tests="ab"), tests),
            ("a test that is a string", self.with_(tests=["toy/tests/test_a.py"]), each),
            ("a test that is a list of its keys", self.with_(tests=[["blob", "path"]]), each),
            ("a test with an unknown field", self.with_(tests=[a_test(mode="100644")]), each),
            ("a test path with ..", self.with_(tests=[a_test(path="toy/tests/../../x.py")]), test),
            ("a test path with a line end", self.with_(tests=[a_test(path="toy/tests/test_a\n.py")]), test),
            ("a test path with a space", self.with_(tests=[a_test(path="toy/tests/test a.py")]), test),
            ("a test path with a quote", self.with_(tests=[a_test(path="toy/tests/test_it's.py")]), test),
            ("a test path that is absolute", self.with_(tests=[a_test(path="/toy/tests/test_a.py")]), test),
            ("a test path outside the component", self.with_(tests=[a_test(path="other/tests/test_a.py")]), test),
            ("a test path under the source", self.with_(tests=[a_test(path="toy/src/test_a.py")]), test),
            ("a test path that is a number", self.with_(tests=[a_test(path=7)]), test),
            ("a blob of another length", self.with_(tests=[a_test(blob="b" * 64)]), blob),
            ("a blob that is not hex", self.with_(tests=[a_test(blob="z" * 40)]), blob),
            ("a blob that is a number", self.with_(tests=[a_test(blob=7)]), blob),
            ("one test file twice", self.with_(tests=[a_test(), a_test()]),
             "0: .yak-check/item.json names one test file twice"),
            ("past the largest size", self.with_().ljust(65537), unreadable),
        ]
        for name, content, says in cases:
            with self.subTest(name):
                code, out, err = self.judged(content)
                self.assertEqual((code, out), (1, ""), err)
                self.assertTrue(err.startswith("FAIL " + says), err)
                self.assertEqual(err.count("\n"), 1, err)
                self.assertNotIn("Traceback", err)

    def test_an_item_json_that_is_a_link_or_a_directory_is_refused(self):
        for name, how in (("a link", {"link": True}), ("a directory", {})):
            with self.subTest(name):
                code, out, err = self.judged(self.with_() if how else None, **how)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("FAIL 0: .yak-check/item.json is not a regular file"), err)

    def test_a_nesting_the_parser_gives_up_on_is_not_strict_json(self):
        # Python 3.9 gives up on "[" * 60000 at its recursion limit (about a thousand), as the case "nested past the
        # stack" above shows. From 3.14 the parser's depth is bounded by the stack instead, and in a main thread
        # 60000 is parsed to its end (a ValueError). Read in a thread of 4 MiB, the parser gives up on every version
        # (3.15 at about 32,000), and the RecursionError it raises is also not strict JSON.
        root = tempfile.mkdtemp(dir=WORK, prefix="form-")
        place(root, ".yak-check/item.json", b"[" * 60000)
        raised = []

        def read():
            try:
                check.read_item(root)
            except BaseException as error:  # noqa: B902 - whatever it is, the test says it
                raised.append(error)

        size = threading.stack_size(4 << 20)
        try:
            reader = threading.Thread(target=read)
            reader.start()
            reader.join()
        finally:
            threading.stack_size(size)
        self.assertEqual([(type(error), str(error)) for error in raised],
                         [(check.Fail, "0: .yak-check/item.json is not strict JSON")])


class TheReport(unittest.TestCase):
    """check.read_report. Its limit is written out as a number, so that a limit changed in check.py fails here."""

    def read(self, data):
        path = os.path.join(tempfile.mkdtemp(dir=WORK, prefix="report-"), "report.xml")
        with open(path, "wb") as out:
            out.write(data)
        return check.read_report(path)

    @staticmethod
    def suite(tests="3", failures="0", errors="0", skipped="1"):
        return ('<testsuite tests="%s" failures="%s" errors="%s" skipped="%s"/>' % (
            tests, failures, errors, skipped)).encode()

    def test_the_counts_are_summed_over_the_suites(self):
        self.assertEqual(self.read(b"<testsuites>" + self.suite() + self.suite("2", "1", "0", "0") +
                                   b"</testsuites>"), {"tests": 5, "failures": 1, "errors": 0, "skipped": 1})
        self.assertEqual(self.read(self.suite("999999999")), {"tests": 999999999, "failures": 0, "errors": 0,
                                                              "skipped": 1})

    def test_a_report_that_cannot_be_read_is_none(self):
        cases = [
            ("not XML", b"<testsuite"),
            ("no suite", b"<testsuites/>"),
            ("a count missing", b'<testsuite tests="1" failures="0" errors="0"/>'),
            ("a count below nothing", self.suite(skipped="-1")),
            ("a count of ten digits", self.suite("1234567890")),
            ("a count in words", self.suite("three")),
            ("a document type", b"<!DOCTYPE testsuite>" + self.suite()),
            ("a document type that declares an entity", b'<!DOCTYPE t [<!ENTITY a "1">]>' + self.suite()),
            ("past the largest size", self.suite().ljust(16_777_217)),
        ]
        for name, data in cases:
            with self.subTest(name):
                self.assertIsNone(self.read(data))
        self.assertIsNotNone(self.read(self.suite().ljust(16_777_216)))

    def test_a_blob_id_is_gits_in_either_object_format(self):
        for form, parent in (("sha1", "a" * 40), ("sha256", "a" * 64)):
            with self.subTest(form):
                repo = tempfile.mkdtemp(dir=WORK, prefix="format-")
                git(repo, "init", "-q", "--object-format=" + form)
                said = git(repo, "hash-object", "--stdin", data=b"some bytes\n").decode().strip()
                self.assertEqual(check.blob_id(b"some bytes\n", parent), said)

    def test_a_report_that_is_a_link_is_none(self):
        where = tempfile.mkdtemp(dir=WORK, prefix="report-")
        with open(os.path.join(where, "real.xml"), "wb") as out:
            out.write(self.suite())
        os.symlink(os.path.join(where, "real.xml"), os.path.join(where, "report.xml"))
        self.assertIsNone(check.read_report(os.path.join(where, "report.xml")))


class TheTestsRun(unittest.TestCase):
    """check.run_tests, which both rule 4 and the check use, on a small tree."""

    def tree(self, test):
        root = tempfile.mkdtemp(dir=WORK, prefix="tree-")
        for path, data in {"toy/tests/test_a.py": test, "toy/src/__init__.py": b""}.items():
            place(root, path, data)
        return root

    def test_the_words_directory_and_environment_are_the_specs(self):
        root = self.tree(b"from src import __name__ as found\n\n\ndef test_a():\n    assert found == 'src'\n")
        code, late, counts = check.run_tests(PYTHON, root, "toy", ["toy/tests/test_a.py"], 60)
        self.assertEqual((code, late, counts), (0, False, {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}))
        with open(RECORD) as runs:
            run = json.loads(runs.read().splitlines()[-1])
        report = run["argv"][4]
        self.assertEqual(run["argv"], ["-q", "-p", "no:cacheprovider", "--junit-xml", report, "tests/test_a.py"])
        self.assertEqual(os.path.realpath(run["cwd"]), os.path.realpath(os.path.join(root, "toy")))
        # The interpreter itself may add LC_CTYPE (PEP 538's locale coercion) and the system its text encoding.
        env = run["env"]
        self.assertEqual(set(env) - {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"},
                         {"PATH", "HOME", "TMPDIR", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"})
        self.assertEqual((env["PATH"], env["PYTHONPATH"], env["PYTHONDONTWRITEBYTECODE"]),
                         ("/usr/bin:/bin", os.path.join(root, "toy"), "1"))
        self.assertEqual(env["HOME"], env["TMPDIR"])
        # The report and the scratch directory are under the caller's TMPDIR, outside the tree, and are gone.
        scratch = os.path.dirname(report)
        self.assertEqual(os.path.dirname(scratch), tempfile.gettempdir())
        self.assertTrue(env["HOME"].startswith(scratch + os.sep))
        self.assertFalse(os.path.exists(scratch))
        self.assertEqual(sorted(os.listdir(os.path.join(root, "toy"))), ["src", "tests"])

    def test_what_the_tests_started_and_left_is_ended(self):
        pid_file = os.path.join(WORK, "left.pid")
        root = self.tree(("import subprocess\n\nsleeper = subprocess.Popen(['/bin/sleep', '60'])\n"
                          "open(%r, 'w').write(str(sleeper.pid))\n\n\ndef test_a():\n    pass\n" % pid_file).encode())
        check.run_tests(PYTHON, root, "toy", ["toy/tests/test_a.py"], 60)
        with open(pid_file) as file:
            pid = int(file.read())
        try:
            for _ in range(100):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("the process the tests left is still running")
        finally:
            with contextlib.suppress(OSError):
                os.kill(pid, 9)

    def test_a_run_past_its_limit_is_ended_at_the_limit(self):
        started = time.monotonic()
        code, late = check.run_limited([sys.executable, "-c", "import time; time.sleep(30)"], WORK, {}, 0.5)
        self.assertTrue(late)
        self.assertLess(time.monotonic() - started, 10)

    def test_a_run_in_the_callers_group_stays_in_it_and_alone_is_ended_at_the_limit(self):
        said = os.path.join(WORK, "group.txt")
        says_group = [sys.executable, "-I", "-c", "import os\nopen(%r, 'w').write(str(os.getpgrp()))\n" % said]
        for own_group, same in ((False, True), (True, False)):
            with self.subTest(own_group=own_group):
                self.assertEqual(check.run_limited(says_group, WORK, {}, 30, own_group=own_group), (0, False))
                with open(said) as file:
                    self.assertEqual(int(file.read()) == os.getpgrp(), same)
        started = time.monotonic()
        code, late = check.run_limited([sys.executable, "-c", "import time; time.sleep(30)"], WORK, {}, 0.5,
                                       own_group=False)
        self.assertTrue(late)
        self.assertLess(time.monotonic() - started, 10)


class TheGitRun(unittest.TestCase):
    """The words and the environment that check.py and items.py give git, as TheTestsRun shows the test runner's.
    No filesystem monitor and no settings file of the machine's: neither shows in what a run of git here prints,
    so each is shown by what git is given. A recorder stands in for subprocess.run; no git is run."""

    def recorded(self, module, path, call):
        calls = []

        class Recorder:
            DEVNULL, PIPE = subprocess.DEVNULL, subprocess.PIPE

            @staticmethod
            def run(argv, **how):
                calls.append((argv, how))
                return subprocess.CompletedProcess(argv, 0, b"", b"")

        real, before = module.subprocess, os.environ.get("PATH")
        module.subprocess, os.environ["PATH"] = Recorder, path
        try:
            call()
        finally:
            module.subprocess = real
            if before is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = before
        return calls

    def test_the_checks_git(self):
        root = os.path.join(WORK, "a checkout")
        calls = self.recorded(check, os.pathsep.join(["/opt/a/bin", "relative/bin", "", "/usr/bin"]),
                              lambda: check.git(root, "rev-parse", "HEAD"))
        self.assertEqual(calls, [(["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"], {
            "cwd": root, "env": {"PATH": os.pathsep.join(["/opt/a/bin", "/usr/bin"]),
                                 "GIT_DIR": os.path.join(root, ".git"), "GIT_CONFIG_NOSYSTEM": "1"},
            "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL})])

    def test_the_item_makers_git(self):
        repo = os.path.join(WORK, "a repository")
        calls = self.recorded(items, "/opt/a/bin:/usr/bin", lambda: items.Git(repo)(
            "read-tree", "HEAD", data=b"given", env={"GIT_INDEX_FILE": "/an/index"}))
        self.assertEqual(calls, [(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                                   "-c", "i18n.commitEncoding=UTF-8", "-c", "core.autocrlf=false", "-C", repo,
                                   "read-tree", "HEAD"], {
            "input": b"given", "env": {"PATH": "/opt/a/bin:/usr/bin", "GIT_CONFIG_NOSYSTEM": "1",
                                       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_ATTR_NOSYSTEM": "1",
                                       "GIT_NO_REPLACE_OBJECTS": "1", "GIT_INDEX_FILE": "/an/index"},
            "stdout": subprocess.PIPE, "stderr": subprocess.PIPE})])


class ThePeerComponent(unittest.TestCase):
    """items.py's table as the brief has its one entry: tests are peer/tests/test_*.py, source is
    peer/superyak_peer/**, documents are docs/**, and the lock file is peer/uv.lock. Rules 2 and 3 tried on
    changes alone, with no repository."""

    @staticmethod
    def sorted_out(*paths):
        found = items.sort_out("peer", [items.Change("M", "100644", "b" * 40, path) for path in paths])
        return found and tuple([change.path for change in part] for part in found)

    def test_its_tests_source_and_documents(self):
        meets = ["docs/a.md", "docs/deep/b.md", "peer/superyak_peer/a.py", "peer/superyak_peer/deep/er/b.py",
                 "peer/tests/test_a.py"]
        self.assertEqual(self.sorted_out(*meets), (["peer/tests/test_a.py"],
                                                   ["peer/superyak_peer/a.py", "peer/superyak_peer/deep/er/b.py"]))
        for other in ["peer/tests/helper.py", "peer/tests/conftest.py", "peer/tests/deep/test_b.py",
                      "peer/test/test_c.py", "peer/test_d.py", "peer/superyak_peer_extra/c.py", "peer/pyproject.toml",
                      "peer/uv.lock", "superyak_peer/a.py", "docs_extra/a.md", "toy/src/a.py"]:
            with self.subTest(other):
                self.assertIsNone(self.sorted_out(*meets, other))

    def test_its_lock_file(self):
        self.assertEqual(items.COMPONENTS["peer"]["lock"], "peer/uv.lock")


class AChangeOfType(unittest.TestCase):
    """Rule 3's "added or changed", on what git itself says of a link that became a file and the other way."""

    def test_a_link_that_became_a_regular_file_is_taken_and_a_file_that_became_a_link_is_not(self):
        toy = Toy(os.path.join(tempfile.mkdtemp(dir=WORK, prefix="type-"), "repo"))
        root = toy.main("root", dict(ROOT_FILES, **{"toy/src/m_ln.py": Link(b"judged.py"),
                                                    "toy/src/m_rl.py": b"VALUE = 1\n"}))
        became_a_file = toy.main("became a file", {"toy/src/m_ln.py": b"VALUE = 1\n",
                                                   "toy/tests/test_ln.py": wants("ln", 1)})
        became_a_link = toy.main("became a link", {"toy/src/m_rl.py": Link(b"judged.py"),
                                                   "toy/tests/test_rl.py": wants("rl", 1)})
        repo = items.Git(toy.path)
        for name, parent, commit_, path, mode, taken in (
                ("a link that became a file", root, became_a_file, "toy/src/m_ln.py", "100644", True),
                ("a file that became a link", became_a_file, became_a_link, "toy/src/m_rl.py", "120000", False)):
            with self.subTest(name):
                found = items.changes(repo, parent, commit_)
                self.assertIn(("T", mode, path), [(change.status, change.mode, change.path) for change in found])
                sorted_out = items.sort_out("toy", found)
                self.assertEqual(sorted_out and [change.path for change in sorted_out[1]],
                                 [path] if taken else None)


class TheSameListFromAnyRepository(unittest.TestCase):
    """Rule 4 runs each tree laid out from its blobs, and the check runs in a clone with no settings of the
    repository's: so one list from an ordinary repository, a bare one, a linked worktree, one whose HEAD is unborn,
    and one whose settings would change the files or run a filter if a checkout took them in."""

    def test_the_same_list_and_no_filter_run(self):
        work = tempfile.mkdtemp(dir=WORK, prefix="any-")
        toy = Toy(os.path.join(work, "repo"))
        toy.main("root", dict(ROOT_FILES, **{"toy/linked": Link(b"src")}))
        first = toy.main("first", {"docs/first.md": b"first\n"})
        toy.main("crlf", {"toy/tests/test_crlf.py": CRLF_TEST, "toy/src/m_crlf.py": b"VALUE = 1\n"})
        toy.main("laid out", {"toy/tests/test_lo.py": Exe(LAID_OUT_TEST), "toy/src/m_lo.py": b"VALUE = 1\n"})
        toy.main("e1", item("e1", 1))
        toy.finish()
        last = toy.tip

        def made_from(repo, name):
            out = os.path.join(work, "out-" + name)
            code, printed, said = run_main(list_args(repo, first, last, out, scored=1, pilot=1))
            self.assertEqual(code, 0, printed + said)
            with open(os.path.join(out, "items.json"), "rb") as file:
                return file.read()

        ordinary = made_from(toy.path, "ordinary")
        written = json.loads(ordinary)
        self.assertEqual([entry.get("reason") for entry in written["commits"]], [None] * 3)

        def cloned(name, *how):
            path = os.path.join(work, name)
            subprocess.run(["git", "clone", "-q"] + list(how) + [toy.path, path], env=GIT_ENV, check=True)
            return path

        bare = cloned("bare.git", "--bare")
        holder = cloned("holder")
        linked = os.path.join(work, "linked")
        git(holder, "worktree", "add", "-q", "--detach", linked, first)
        unborn = os.path.join(work, "unborn")
        git(work, "init", "-q", unborn)
        git(unborn, "fetch", "-q", toy.path, "main:refs/heads/kept")
        hostile = cloned("hostile")
        marker = os.path.join(work, "a filter ran")
        git(hostile, "config", "core.autocrlf", "true")
        git(hostile, "config", "filter.mark.smudge", "touch '%s'; cat" % marker)
        git(hostile, "config", "filter.mark.clean", "cat")
        for path in (os.path.join(hostile, ".git", "info", "attributes"), os.path.join(hostile, ".gitattributes")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as out:
                out.write("* text eol=crlf filter=mark\n")
        # The hostile settings are live: a checkout in that repository runs the filter.
        git(hostile, "checkout-index", "-f", "--prefix=%s/" % os.path.join(work, "a checkout"), "toy/uv.lock")
        self.assertTrue(os.path.exists(marker))
        os.unlink(marker)
        for name, repo in (("bare", bare), ("linked", linked), ("unborn", unborn), ("hostile", hostile)):
            with self.subTest(name):
                self.assertEqual(made_from(repo, name), ordinary)
        self.assertEqual(git(linked, "rev-parse", "HEAD").decode().strip(), first)
        self.assertNotEqual(subprocess.run(["git", "-C", unborn, "rev-parse", "--verify", "-q", "HEAD"], env=GIT_ENV,
                                           stdout=subprocess.DEVNULL).returncode, 0)
        self.assertFalse(os.path.exists(marker), "a filter of the repository's ran")

    def test_a_tree_is_laid_out_from_its_blobs_and_a_path_that_cannot_be_is_refused(self):
        toy = Toy(os.path.join(tempfile.mkdtemp(dir=WORK, prefix="lay-"), "repo"))
        toy.main("root", {"a/run.sh": Exe(b"#!/bin/sh\n"), "a/link": Link(b"run.sh"), "b.txt": b"one\r\ntwo\n"})
        toy.finish()
        repo = items.Git(toy.path)
        maker = items.Maker(repo, "toy", PYTHON, 3, tempfile.mkdtemp(dir=WORK, prefix="maker-"))
        blob = git(toy.path, "hash-object", "-w", "--stdin", data=b"X = 1\n").decode().strip()
        # A submodule, written as git writes one in a tree, at a commit that is not in this repository.
        index = {"GIT_INDEX_FILE": os.path.join(WORK, "lay-index")}
        git(toy.path, "read-tree", toy.tip, env=index)
        git(toy.path, "update-index", "--add", "--cacheinfo", "160000,%s,sub" % ("1" * 40), env=index)
        tree = git(toy.path, "write-tree", env=index).decode().strip()
        root = os.path.join(tempfile.mkdtemp(dir=WORK, prefix="laid-"), "tree")
        maker.lay_out(tree, root)
        self.assertEqual(sorted(os.listdir(root)), ["a", "b.txt", "sub"])
        self.assertEqual(os.listdir(os.path.join(root, "sub")), [])
        self.assertEqual(os.readlink(os.path.join(root, "a", "link")), "run.sh")
        self.assertTrue(os.access(os.path.join(root, "a", "run.sh"), os.X_OK))
        self.assertFalse(os.access(os.path.join(root, "b.txt"), os.X_OK))
        with open(os.path.join(root, "b.txt"), "rb") as file:
            self.assertEqual(file.read(), b"one\r\ntwo\n")
        for name, says in ((b"..", "cannot be laid out"), (b".", "cannot be laid out"), (b".git", "cannot be laid out"),
                           (b".Git", "cannot be laid out"), (b"", "git ls-tree failed")):
            with self.subTest(name):
                raw = b"100644 " + name + b"\0" + bytes.fromhex(blob)
                bad = git(toy.path, "hash-object", "-t", "tree", "--literally", "-w", "--stdin",
                          data=raw).decode().strip()
                with self.assertRaisesRegex(items.Refused, says):
                    maker.lay_out(bad, os.path.join(tempfile.mkdtemp(dir=WORK, prefix="laid-"), "tree"))


class TheProgram(unittest.TestCase):
    """The program on small repositories of their own."""

    def small(self, *named):
        toy = Toy(os.path.join(tempfile.mkdtemp(dir=WORK, prefix="small-"), "repo"))
        toy.main("root", ROOT_FILES)
        first = toy.main("first", {"docs/first.md": b"first\n"})
        for name, files in named:
            toy.main(name, files)
        toy.finish()
        return toy, first

    def test_each_way_of_running_past_the_limit_and_failing_in_a_clone(self):
        sleeps = b"import time\n\ntime.sleep(60)\n"
        lock, pid_file = os.path.join(WORK, "slow-in-a-clone.lock"), os.path.join(WORK, "slow-in-a-clone.pid")
        toy, first = self.small(
            ("slow before", {"toy/tests/test_sb.py": b"try:\n    from src import m_sb\nexcept ImportError:\n"
                                                     b"    import time\n    time.sleep(60)\n\n\n"
                                                     b"def test_value():\n    assert m_sb.VALUE == 1\n",
                             "toy/src/m_sb.py": b"VALUE = 1\n"}),
            ("slow after", {"toy/tests/test_sa.py": wants("sa", 1), "toy/src/m_sa.py": sleeps + b"VALUE = 1\n"}),
            ("slow in a clone", {"toy/tests/test_sc.py": wants("sc", 1),
                                 "toy/src/m_sc.py": slow_in_a_clone(lock, pid_file)}),
            ("fails in a clone", {"toy/tests/test_fc.py": wants("fc", 1), "toy/src/m_fc.py": IN_A_CLONE +
                                  b"VALUE = 0 if CLONE else 1\n"}),
            ("fails in a plain copy", {"toy/tests/test_fp.py": wants("fp", 1), "toy/src/m_fp.py": IN_A_CLONE +
                                       b"VALUE = 1 if CLONE else 0\n"}),
            ("e1", item("e1", 1)), ("e2", item("e2", 1)))
        out = os.path.join(os.path.dirname(toy.path), "out")
        code, printed, said = run_main(list_args(toy.path, first, toy.tip, out, scored=1, pilot=1,
                                                 more=["--limit-secs", "3"]))
        self.assertEqual(code, 0, printed + said)
        with open(os.path.join(out, "items.json")) as file:
            written = json.load(file)
        reasons = {entry["commit"]: entry.get("reason", entry.get("part")) for entry in written["commits"]}
        self.assertEqual({name: reasons[toy.named[name]] for name in toy.named if toy.named[name] in reasons}, {
            "slow before": items.PAST_LIMIT, "slow after": items.PAST_LIMIT, "slow in a clone": items.PAST_LIMIT,
            "fails in a clone": items.FAIL_AFTER, "fails in a plain copy": items.FAIL_AFTER, "e1": items.PILOT,
            "e2": items.SCORED})
        self.assertEqual((written["dividing"], written["asked"]["limit_secs"]), (toy.named["e1"], 3))
        # The tests the check ran in the clone were reached, and were ended with the check at the limit.
        end_if_held(self, lock, pid_file)

    def test_the_tests_a_check_ran_have_ended_before_its_clone_is_deleted(self):
        lock, pid_file = os.path.join(WORK, "before-deleting.lock"), os.path.join(WORK, "before-deleting.pid")
        toy, first = self.small(("slow", {"toy/tests/test_sl.py": wants("sl", 1),
                                          "toy/src/m_sl.py": slow_in_a_clone(lock, pid_file)}))
        repo = items.Git(toy.path)
        maker = items.Maker(repo, "toy", PYTHON, 3, tempfile.mkdtemp(dir=WORK, prefix="maker-"))
        found = items.sort_out("toy", items.changes(repo, first, toy.named["slow"]))
        seen, real = [], items.shutil

        class Watched:
            @staticmethod
            def rmtree(path, **how):
                if os.path.basename(path) == "clone":
                    seen.append((os.path.exists(pid_file), held(lock)))
                return real.rmtree(path, **how)

        items.shutil = Watched
        try:
            made = maker.make(toy.named["slow"], first, *found)
        finally:
            items.shutil = real
        self.assertEqual(made, items.PAST_LIMIT)
        # The tests in the clone had started (they wrote their id), and had ended when the clone was deleted.
        self.assertEqual(seen, [(True, False)])
        end_if_held(self, lock, pid_file)

    def test_too_few_for_the_scored_is_refused_and_writes_nothing(self):
        toy, first = self.small(("e1", item("e1", 1)))
        out = os.path.join(os.path.dirname(toy.path), "out")
        code, printed, _ = run_main(list_args(toy.path, first, toy.tip, out, scored=1, pilot=1))
        self.assertEqual(code, 1)
        self.assertTrue(printed.startswith("REFUSED: too few for the scored"), printed)
        self.assertEqual(printed.count("\n"), 1)
        self.assertFalse(os.path.exists(os.path.join(out, "items.json")))
        self.assertEqual(git(toy.path, "for-each-ref", "refs/yak-items/"), b"")

    def test_what_cannot_be_used_is_refused_before_anything_runs(self):
        toy, first = self.small()
        out = os.path.join(os.path.dirname(toy.path), "out")
        says_nothing = os.path.join(WORK, "says-nothing")
        fails = os.path.join(WORK, "says-and-fails")
        for path, body in ((says_nothing, "exit 0\n"), (fails, "echo cpython 3.0\nexit 1\n")):
            with open(path, "w") as script:
                script.write("#!/bin/sh\n" + body)
            os.chmod(path, 0o755)
        cases = [
            ("a first commit that reads as a flag", list_args(toy.path, "x", toy.tip, out)[:3] + ["--first=--all"]
             + list_args(toy.path, "x", toy.tip, out)[5:], '"--all" is not a commit'),
            ("a first commit that is not there", list_args(toy.path, "no-such-commit", toy.tip, out),
             "git rev-parse failed"),
            ("an interpreter that is not there", list_args(toy.path, first, toy.tip, out,
                                                           python=os.path.join(WORK, "none")), "cannot be run"),
            ("an interpreter that says nothing", list_args(toy.path, first, toy.tip, out, python=says_nothing),
             "does not say its version"),
            ("an interpreter that fails", list_args(toy.path, first, toy.tip, out, python=fails),
             "does not say its version"),
        ]
        for name, argv, says in cases:
            with self.subTest(name):
                code, printed, _ = run_main(argv)
                self.assertEqual(code, 1)
                self.assertTrue(printed.startswith("REFUSED: ") and says in printed, printed)
                self.assertEqual(printed.count("\n"), 1)

    def test_numbers_that_are_not_above_0_are_refused(self):
        for flag in ("--scored", "--pilot", "--limit-secs"):
            with self.subTest(flag), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                items.main(["list", "--repo", ".", "--first", "a", "--last", "b", "--component", "toy", "--python",
                            "p", "--scored", "1", "--pilot", "1", "--out", "o", flag, "0"])

    def test_an_unforeseen_failure_is_one_line(self):
        toy, first = self.small(("e1", item("e1", 1)))
        order = items.order
        items.order = lambda commits: 1 / 0
        try:
            code, printed, _ = run_main(list_args(toy.path, first, toy.tip, os.path.join(WORK, "o")))
        finally:
            items.order = order
        self.assertEqual((code, printed), (1, "REFUSED: the item-maker could not go on (ZeroDivisionError: "
                                              "division by zero)\n"))


if __name__ == "__main__":
    unittest.main()
