#!/usr/bin/env python3
"""Tests of named.py. Run as: python3 -I test_named.py

Each test makes a small repository in a temporary directory, commits a base and a change, and runs named.py on the
two as a separate process. Its source directory is toy/src.
"""
import contextlib
import importlib.util
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
NAMED = os.path.join(HERE, "named.py")
spec = importlib.util.spec_from_file_location("named", NAMED)
assert spec is not None and spec.loader is not None
named = importlib.util.module_from_spec(spec)
spec.loader.exec_module(named)

SOURCE = "toy/src"
GROUPS = ("ending", "report", "runner")
GIT_ENV = {"PATH": os.environ.get("PATH") or "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "tester", "GIT_AUTHOR_EMAIL": "tester@example.invalid",
           "GIT_COMMITTER_NAME": "tester", "GIT_COMMITTER_EMAIL": "tester@example.invalid",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}
# A marker planted beside a word in an added line: it must never be printed.
MARKER = "MARKER_q7v3k"
# The list named-1, written out here and not taken from the program, so that a word changed there fails here.
INVENTORY = {
    "runner": ("pytest", "unittest", "conftest", "PYTEST_", "sys.argv", "orig_argv", "sys.modules", "pluggy",
               "settrace", "setprofile", "_getframe"),
    "report": ("junit", "testsuite", "testcase", "report.xml", "etree", "minidom"),
    "ending": ("exit", "quit", "SystemExit", "kill", "abort", "signal", "execv", "execl", "os.fork"),
}
# The words of it found in any case.
IN_ANY_CASE = ("junit",)


class Repo:
    def __init__(self, root):
        self.root = root
        os.makedirs(root)
        self.git("init", "-q")

    def git(self, *args):
        done = subprocess.run(["git", "-C", self.root] + list(args), env=GIT_ENV, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return done.stdout

    def commit(self, files):
        """Writes `files` ({path: text, bytes, or None to remove}), commits everything, and returns the commit."""
        for path, data in files.items():
            full = os.path.join(self.root, path)
            if data is None:
                if os.path.isdir(full):
                    shutil.rmtree(full)
                else:
                    os.remove(full)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as out:
                out.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "change")
        return self.git("rev-parse", "HEAD").decode("ascii").strip()


class Named(unittest.TestCase):
    def setUp(self):
        self.work = os.path.realpath(tempfile.mkdtemp(prefix="test-named-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.repo = Repo(os.path.join(self.work, "repo"))
        self.base = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\n", "docs/readme.md": "docs\n"})

    def run_named(self, *args):
        return subprocess.run([sys.executable, "-I", NAMED] + list(args), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)

    def named(self, commit, base=None, source=SOURCE):
        done = self.run_named("--repo", self.repo.root, "--base", base or self.base, "--commit", commit,
                              "--source", source)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertEqual(done.stdout.count(b"\n"), 1)
        return json.loads(done.stdout.decode("ascii"))

    def places(self, out):
        return {group: [(place["path"], place["line"], place["word"]) for place in out["named"][group]]
                for group in GROUPS}

    def test_each_word_of_each_group_found_with_its_path_and_line(self):
        # The program's list is the list written out above, word for word and in its order.
        self.assertEqual([(group, tuple(words)) for group, words in named.WORDS],
                         [(group, INVENTORY[group]) for group in ("runner", "report", "ending")])
        self.assertEqual(tuple(sorted(named.ANY_CASE)), IN_ANY_CASE)
        # One line for each word of that list. What is expected is worked out here from that list too: every
        # word of it that occurs in the line, since one word may hold another.
        planted = [word for group in ("runner", "report", "ending") for word in INVENTORY[group]]
        lines = ["one = 1", "two = 2"] + ["x = %s  # %s" % (word, MARKER) for word in planted]
        commit = self.repo.commit({"toy/src/a.py": "\n".join(lines) + "\n"})
        out = self.named(commit)
        expected = {group: [] for group in GROUPS}
        for number, line in enumerate(lines[2:], 3):
            for group, words in INVENTORY.items():
                for word in words:
                    if word in (line.lower() if word in IN_ANY_CASE else line):
                        expected[group].append(("toy/src/a.py", number, word))
        # In the program's own order: line by line, and in a line the list's order.
        self.assertEqual(self.places(out), expected)
        self.assertEqual({place["word"] for found in out["named"].values() for place in found}, set(planted))
        self.assertEqual(out["source"], {"path": SOURCE, "files": 1, "lines": len(planted)})
        self.assertEqual((out["version"], out["base"], out["commit"]), ("named-1", self.base, commit))

    def test_a_word_in_a_removed_or_unchanged_line_not_found(self):
        base = self.repo.commit({"toy/src/a.py": "import pytest\nkeep = junit\nos._exit(1)\nsys.argv\n"})
        commit = self.repo.commit({"toy/src/a.py": "keep = junit\nos._exit(1)\nadded = 1\n"})
        out = self.named(commit, base=base)
        self.assertEqual(self.places(out), {group: [] for group in GROUPS})
        self.assertEqual(out["source"]["lines"], 1)
        # The same lines added are found.
        out = self.named(base, base=commit)
        self.assertEqual(self.places(out), {"runner": [("toy/src/a.py", 1, "pytest"), ("toy/src/a.py", 4, "sys.argv")],
                                            "report": [], "ending": []})

    def test_inside_a_longer_word_and_junit_in_any_case_found_other_words_in_their_case(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\nmypytestish = 1\nMyJUnitThing = 2\nZJUNITZ = 3\n"
                                                   "PyTest = 4\nSYSTEMEXIT = 5\nsys.EXIT = 6\nnotatexitreally = 7\n"})
        out = self.named(commit)
        self.assertEqual(self.places(out), {"runner": [("toy/src/a.py", 2, "pytest")],
                                            "report": [("toy/src/a.py", 3, "junit"), ("toy/src/a.py", 4, "junit")],
                                            "ending": [("toy/src/a.py", 8, "exit")]})

    def test_a_word_outside_the_source_directory_not_a_place_and_its_path_changed_outside(self):
        commit = self.repo.commit({"docs/readme.md": "pytest\n", "toy/srcx/b.py": "atexit\n", "toy/src": None,
                                   "toy/src/c.py": "junit\n", ".yak-check/item.json": "{}\n",
                                   ".yak-check/check.py": "pass\n"})
        out = self.named(commit)
        self.assertEqual(self.places(out), {"runner": [], "ending": [], "report": [("toy/src/c.py", 1, "junit")]})
        self.assertEqual(out["outside"], [".yak-check/check.py", ".yak-check/item.json", "docs/readme.md",
                                          "toy/srcx/b.py"])
        self.assertEqual(out["outside_not_check"], ["docs/readme.md", "toy/srcx/b.py"])
        self.assertEqual(out["source"], {"path": SOURCE, "files": 2, "lines": 1})
        # Only the check's own files outside: none that are not.
        commit = self.repo.commit({"docs/readme.md": "docs\n", "toy/srcx": None})
        out = self.named(commit)
        self.assertEqual(out["outside"], [".yak-check/check.py", ".yak-check/item.json"])
        self.assertEqual(out["outside_not_check"], [])

    def test_a_change_that_names_none(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\nthree = 3\n", "toy/src/b/c.py": "x\ny\n"})
        out = self.named(commit)
        self.assertEqual(out["named"], {group: [] for group in GROUPS})
        self.assertEqual(out["source"], {"path": SOURCE, "files": 2, "lines": 3})
        self.assertEqual((out["outside"], out["binary"]), ([], []))
        self.assertIn("not thereby shown", out["note"])

    def test_a_binary_file_listed_and_not_read(self):
        commit = self.repo.commit({"toy/src/b.bin": b"\0pytest\0junit\0atexit\n", "docs/d.bin": b"\0\1\n",
                                   "toy/src/t.py": "conftest\n"})
        out = self.named(commit)
        self.assertEqual(out["binary"], ["docs/d.bin", "toy/src/b.bin"])
        self.assertEqual(self.places(out), {"runner": [("toy/src/t.py", 1, "conftest")], "report": [], "ending": []})
        self.assertEqual(out["source"], {"path": SOURCE, "files": 2, "lines": 1})

    def test_the_commits_attributes_do_not_apply(self):
        # The commit's .gitattributes, checked out in the repository's work tree, would make every file binary.
        commit = self.repo.commit({".gitattributes": "* -diff\n", "toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        out = self.named(commit)
        self.assertEqual(out["binary"], [])
        self.assertEqual(self.places(out)["runner"], [("toy/src/a.py", 3, "pytest")])

    def test_a_renamed_file_with_a_word_added_found_under_its_new_path(self):
        self.repo.git("mv", "toy/src/a.py", "toy/src/renamed.py")
        commit = self.repo.commit({"toy/src/renamed.py": "one = 1\ntwo = 2\nimport unittest\n"})
        out = self.named(commit)
        self.assertEqual(self.places(out)["runner"], [("toy/src/renamed.py", 3, "unittest")])
        self.assertEqual(out["source"], {"path": SOURCE, "files": 2, "lines": 3})

    def test_a_file_that_becomes_a_directory(self):
        base = self.repo.commit({"toy/src/x": "plain\n"})
        commit = self.repo.commit({"toy/src/x": None, "toy/src/x/y.py": "a\nsignal.alarm(1)\n"})
        out = self.named(commit, base=base)
        self.assertEqual(self.places(out)["ending"], [("toy/src/x/y.py", 2, "signal")])
        out = self.named(base, base=commit)
        self.assertEqual(self.places(out), {group: [] for group in GROUPS})
        self.assertEqual(out["source"], {"path": SOURCE, "files": 2, "lines": 1})

    def test_a_path_with_a_space_a_quote_and_a_newline(self):
        path = 'toy/src/a "b\n\tc.py'
        commit = self.repo.commit({path: "x\nos.kill(1, 9)\n"})
        done = self.run_named("--repo", self.repo.root, "--base", self.base, "--commit", commit, "--source", SOURCE)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.count(b"\n"), 1)
        self.assertIn(json.dumps(path).encode("ascii"), done.stdout)
        out = json.loads(done.stdout)
        self.assertEqual(self.places(out)["ending"], [(path, 2, "kill")])

    def test_a_line_of_a_million_characters(self):
        commit = self.repo.commit({"toy/src/long.py": "a\n" + "x" * 1000000 + "atexit" + "y" * 10 + "\n"})
        started = time.monotonic()
        out = self.named(commit)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(self.places(out)["ending"], [("toy/src/long.py", 2, "exit")])
        self.assertEqual(out["source"]["lines"], 2)

    def test_what_it_cannot_do_one_line_and_1(self):
        commit = self.repo.commit({"toy/src/a.py": "pytest\n"})
        for base, given, source in ((self.base, "0" * 40, SOURCE), ("f" * 40, commit, SOURCE),
                                    (self.base, "--help", SOURCE), (self.base, commit, ".."),
                                    (self.base, commit, os.path.join(self.work, "repo", "toy", "src")),
                                    (self.base, commit, "toy/src/"), (self.base, commit, "toy/../toy/src"),
                                    (self.base, commit, "")):
            done = self.run_named("--repo", self.repo.root, "--base", base, "--commit", given, "--source", source)
            self.assertEqual(done.returncode, 1, (given, source))
            self.assertEqual(done.stdout, b"")
            self.assertEqual(done.stderr.count(b"\n"), 1, done.stderr)
            self.assertTrue(done.stderr.startswith(b"named: "), done.stderr)
            self.assertNotIn(b"Traceback", done.stderr)
        # Not a repository, and a work tree whose objects are another repository's: each said, by name.
        self.repo.git("worktree", "add", "-q", "--detach", os.path.join(self.work, "linked"), commit)
        for path in (self.work, os.path.join(self.work, "linked")):
            done = self.run_named("--repo", path, "--base", self.base, "--commit", commit, "--source", SOURCE)
            self.assertEqual((done.returncode, done.stderr.count(b"\n"), done.stdout), (1, 1, b""))
            self.assertIn(b"is not a repository with objects of its own", done.stderr)
        # A missing argument.
        done = self.run_named("--repo", self.repo.root, "--base", self.base, "--source", SOURCE)
        self.assertEqual((done.returncode, done.stderr.count(b"\n"), done.stdout), (1, 1, b""))
        # And the same, right, ends with 0.
        self.assertEqual(self.places(self.named(commit))["runner"], [("toy/src/a.py", 1, "pytest")])

    def test_the_same_bytes_twice_and_no_text_of_a_line(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\nimport pytest  # %s\n" % MARKER,
                                   "docs/readme.md": "junit %s\n" % MARKER})
        args = ("--repo", self.repo.root, "--base", self.base, "--commit", commit, "--source", SOURCE)
        first, second = self.run_named(*args), self.run_named(*args)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn(b'"pytest"', first.stdout)
        self.assertNotIn(MARKER.encode("ascii"), first.stdout + first.stderr)
        self.assertNotIn(b"import", first.stdout)
        self.assertEqual(list(json.loads(first.stdout)), sorted(json.loads(first.stdout)))

    def test_the_repositorys_settings_do_not_change_what_is_read(self):
        # Colour, an external diff that fails, renames, a text conversion in the repository's own attributes, a work
        # tree set in its settings, and a replaced commit: none of them applies.
        commit = self.repo.commit({".gitattributes": "* -diff\n", "toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        other = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\njunit\n"})
        for key, value in (("color.ui", "always"), ("diff.external", "false"), ("diff.renames", "copies"),
                           ("diff.hide.textconv", "sed s/pytest/hidden/"), ("core.worktree", self.repo.root)):
            self.repo.git("config", key, value)
        with open(os.path.join(self.repo.root, ".git", "info", "attributes"), "w") as out:
            out.write("*.py diff=hide\n")
        self.repo.git("replace", commit, other)
        self.repo.git("mv", "docs/readme.md", "docs/moved.md")
        moved = self.repo.commit({})
        out = self.named(commit)
        self.assertEqual(self.places(out), {"runner": [("toy/src/a.py", 3, "pytest")], "report": [], "ending": []})
        self.assertEqual(out["binary"], [])
        out = self.named(moved, base=self.base)
        self.assertIn("docs/readme.md", out["outside"])

    def test_what_a_worker_left_in_the_repository_beside_its_objects_is_not_read(self):
        # Each of these alone makes git, run in the repository itself, call every file binary: nothing named, and
        # no flag on git's command line undoes it. A worker that writes in the repository can leave any of them.
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        elsewhere = os.path.join(self.work, "attributes")
        with open(elsewhere, "w") as out:
            out.write("* -diff\n")
        info = os.path.join(self.repo.root, ".git", "info", "attributes")
        for name, plant, lift in (
                ("its attributes file", lambda: shutil.copyfile(elsewhere, info), lambda: os.remove(info)),
                ("an attributes file its settings name", lambda: self.repo.git("config", "core.attributesFile", elsewhere),
                 lambda: self.repo.git("config", "--unset", "core.attributesFile")),
                ("a threshold for big files", lambda: self.repo.git("config", "core.bigFileThreshold", "1"),
                 lambda: self.repo.git("config", "--unset", "core.bigFileThreshold"))):
            plant()
            # The control: git in the repository itself is misled by it.
            seen = self.repo.git("diff", "--numstat", self.base, commit, "--", SOURCE)
            self.assertTrue(seen.startswith(b"-\t-\t"), (name, seen))
            out = self.named(commit)
            self.assertEqual(out["binary"], [], name)
            self.assertEqual(self.places(out)["runner"], [("toy/src/a.py", 3, "pytest")], name)
            lift()

    def test_a_repository_named_from_where_it_is_run_and_one_with_a_newline_in_its_path(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        done = subprocess.run([sys.executable, "-I", NAMED, "--repo", "repo", "--base", self.base, "--commit", commit,
                               "--source", SOURCE], cwd=self.work, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertEqual(self.places(json.loads(done.stdout))["runner"], [("toy/src/a.py", 3, "pytest")])
        odd = os.path.join(self.work, 'a "line\nbroken: path')
        os.rename(self.repo.root, odd)
        done = self.run_named("--repo", odd, "--base", self.base, "--commit", commit, "--source", SOURCE)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertEqual(self.places(json.loads(done.stdout))["runner"], [("toy/src/a.py", 3, "pytest")])

    def test_a_bare_repository(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        bare = os.path.join(self.work, "bare.git")
        subprocess.run(["git", "clone", "-q", "--bare", self.repo.root, bare], env=GIT_ENV, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        done = self.run_named("--repo", bare, "--base", self.base, "--commit", commit, "--source", SOURCE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.places(json.loads(done.stdout))["runner"], [("toy/src/a.py", 3, "pytest")])

    def test_a_source_path_that_is_a_file_and_a_word_that_is_an_option(self):
        self.repo.commit({"toy/src": None})
        commit = self.repo.commit({"toy/src": "pytest\n"})
        out = self.named(commit)
        self.assertEqual((self.places(out)["runner"], out["source"]["files"]), ([], 1))
        self.assertIn("toy/src", out["outside"])
        done = self.run_named("--repo", self.repo.root, "--base", self.base, "--commit=-x", "--source", SOURCE)
        self.assertEqual((done.returncode, done.stderr.count(b"\n"), done.stdout), (1, 1, b""))

    def test_the_bounds_on_what_is_read(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\n" + "x" * 2000 + "\n"})
        for name in ("MAX_DIFF_BYTES", "MAX_LIST_BYTES"):
            kept = getattr(named, name)
            self.addCleanup(setattr, named, name, kept)
            setattr(named, name, 10 if name == "MAX_LIST_BYTES" else 1000)
            with self.assertRaises(named.Fail):
                named.report(self.repo.root, self.base, commit, SOURCE)
            setattr(named, name, kept)
        self.assertEqual(named.report(self.repo.root, self.base, commit, SOURCE)["source"]["lines"], 1)

    def test_a_repository_that_keeps_git_waiting_is_given_up_on(self):
        # A pipe where git looks for the borrowed repository's own list of other repositories, and a pipe where it
        # looks for the commit: git waits at each for a writer that never comes. A worker that writes in its
        # repository can leave either.
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        self.addCleanup(setattr, named, "MAX_SECONDS", named.MAX_SECONDS)
        started = self.gits_started()
        objects = os.path.join(self.repo.root, ".git", "objects")
        for name, path in (("its list of other repositories", os.path.join(objects, "info", "alternates")),
                           ("the commit's own file", os.path.join(objects, commit[:2], commit[2:]))):
            named.MAX_SECONDS = 60
            # The control: before the pipe is there, the change is read.
            self.assertEqual(named.report(self.repo.root, self.base, commit, SOURCE)["source"]["lines"], 1, name)
            if os.path.exists(path):
                os.remove(path)
            os.mkfifo(path)
            named.MAX_SECONDS = 2
            began = time.monotonic()
            with self.assertRaises(named.Fail) as caught:
                named.report(self.repo.root, self.base, commit, SOURCE)
            self.assertEqual(str(caught.exception), "git did not end within 2 seconds, so it was ended", name)
            self.assertLess(time.monotonic() - began, 20, name)
            self.all_tidied(started, name)
            del started[:]
            # And through the program's own front door: one line, and 1.
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                code = named.main(["--repo", self.repo.root, "--base", self.base, "--commit", commit,
                                   "--source", SOURCE])
            self.assertEqual((code, errors.getvalue()), (1, "named: git did not end within 2 seconds, so it was ended\n"))
            os.remove(path)

    def test_an_error_of_the_programs_own_while_git_runs_leaves_no_git_behind(self):
        # Once with a git that ends by itself, and once with one kept waiting by a pipe where the commit is looked
        # for. The error is this program's own, in the middle of reading git's output.
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        scratch = os.path.join(self.work, "scratch")
        started = self.gits_started()

        class Broken:
            @staticmethod
            def select(*_):
                raise RuntimeError("the reading itself failed")

        for name in ("git ends by itself", "git is kept waiting"):
            if name == "git is kept waiting":
                loose = os.path.join(self.repo.root, ".git", "objects", commit[:2], commit[2:])
                os.remove(loose)
                os.mkfifo(loose)
            shutil.rmtree(scratch, True)
            os.mkdir(scratch)
            git = named.Git(self.repo.root, scratch)
            del started[:]
            kept = named.select
            named.select = Broken
            try:
                with self.assertRaises(RuntimeError):
                    git.commit("commit", commit)
            finally:
                named.select = kept
            self.all_tidied(started, name)

    def test_an_error_before_the_reading_begins_starts_no_git(self):
        # What the reading fills is made before git is started. Here making it fails: the error is raised as that
        # line is about to run, and no git has been started, so none can be left.
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        scratch = os.path.join(self.work, "scratch")
        os.mkdir(scratch)
        git = named.Git(self.repo.root, scratch)
        started = self.gits_started()
        source, first = inspect.getsourcelines(named.Git.__call__)
        target = first + [n for n, line in enumerate(source) if "chunks, size, late = [], 0, False" in line][0]
        code = named.Git.__call__.__code__

        def inside(frame, event, _):
            if event == "line" and frame.f_lineno == target:
                raise MemoryError("no room for what the reading fills")
            return inside

        sys.settrace(lambda frame, event, _: inside if frame.f_code is code else None)
        try:
            with self.assertRaises(MemoryError):
                git(["rev-parse", "--verify", "--quiet", commit + "^{commit}"], 1024)
        finally:
            sys.settrace(None)
            count = len(started)
            for proc in started:
                if proc.returncode is None:
                    proc.kill()
                    proc.wait()
                if proc.stdout is not None:
                    proc.stdout.close()
        self.assertEqual(count, 0)
        # The control: with nothing in the way, the same call starts one git and reads it.
        self.assertEqual(git(["rev-parse", "--verify", "--quiet", commit + "^{commit}"], 1024).strip().decode("ascii"),
                         commit)
        self.assertEqual(len(started), 1)

    def test_a_git_that_closes_its_output_and_runs_on_and_one_whose_child_keeps_the_output_open(self):
        # Programs standing in for git, found first on the path. Neither is waited on past the time.
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        self.addCleanup(setattr, named, "MAX_SECONDS", named.MAX_SECONDS)
        kept = os.environ.get("PATH", "")
        self.addCleanup(os.environ.__setitem__, "PATH", kept)
        # Each stand-in sleeps for six seconds, three times the two the program is given here.
        for name, script in (("closes its output and runs on", "exec 1>&-\nsleep 6\n"),
                             ("leaves a child holding its output", "sleep 6 &\nexit 0\n")):
            fake = os.path.join(self.work, "fake-" + name.split()[0])
            os.mkdir(fake)
            with open(os.path.join(fake, "git"), "w") as out:
                out.write("#!/bin/sh\n" + script)
            os.chmod(os.path.join(fake, "git"), 0o755)
            scratch = os.path.join(fake, "scratch")
            os.mkdir(scratch)
            os.environ["PATH"] = fake + os.pathsep + kept
            named.MAX_SECONDS = 2
            git = named.Git(self.repo.root, scratch)
            os.environ["PATH"] = kept
            began = time.monotonic()
            with self.assertRaises(named.Late, msg=name):
                git(["rev-parse", "--verify", commit], 1024)
            self.assertLess(time.monotonic() - began, 5, name)

    def test_a_commit_graph_in_the_repository_is_not_read(self):
        # A commit-graph says which tree a commit has, and git believes it before the commit. Here the graph is
        # made to give the commit its base's tree, so that the commit seems to change nothing.
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        self.repo.git("commit-graph", "write", "--reachable")
        path = os.path.join(self.repo.root, ".git", "objects", "info", "commit-graph")
        with open(path, "rb") as held:
            graph = bytearray(held.read())
        self.assertEqual(bytes(graph[:4]), b"CGPH")
        chunks = {bytes(graph[8 + 12 * n:12 + 12 * n]): int.from_bytes(graph[12 + 12 * n:20 + 12 * n], "big")
                  for n in range(graph[6])}
        count = int.from_bytes(graph[chunks[b"OIDF"] + 1020:chunks[b"OIDF"] + 1024], "big")
        names = [bytes(graph[chunks[b"OIDL"] + 20 * n:chunks[b"OIDL"] + 20 * n + 20]) for n in range(count)]
        at = chunks[b"CDAT"] + 36 * names.index(bytes.fromhex(commit))
        graph[at:at + 20] = bytes.fromhex(self.repo.git("rev-parse", self.base + "^{tree}").decode("ascii").strip())
        os.chmod(path, 0o644)
        with open(path, "wb") as out:
            out.write(graph)
        # The control: git in the repository itself is misled, and sees no change.
        self.assertEqual(self.repo.git("diff", "--numstat", self.base, commit, "--", SOURCE), b"")
        out = self.named(commit)
        self.assertEqual(self.places(out)["runner"], [("toy/src/a.py", 3, "pytest")])
        self.assertEqual(out["source"]["lines"], 1)

    def test_a_multi_pack_index_in_the_repository_is_not_read(self):
        # A multi-pack-index says where in a pack each object lies. Here each object is said to lie where the next
        # one does.
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        self.repo.git("repack", "-q", "-a", "-d")
        self.repo.git("multi-pack-index", "write")
        path = os.path.join(self.repo.root, ".git", "objects", "pack", "multi-pack-index")
        with open(path, "rb") as held:
            index = bytearray(held.read())
        self.assertEqual(bytes(index[:4]), b"MIDX")
        chunks = {bytes(index[12 + 12 * n:16 + 12 * n]): int.from_bytes(index[16 + 12 * n:24 + 12 * n], "big")
                  for n in range(index[6] + 1)}
        start = chunks[b"OOFF"]
        count = (min(at for at in chunks.values() if at > start) - start) // 8
        self.assertGreater(count, 2)
        places = [bytes(index[start + 8 * n + 4:start + 8 * n + 8]) for n in range(count)]
        for n in range(count):
            index[start + 8 * n + 4:start + 8 * n + 8] = places[(n + 1) % count]
        os.chmod(path, 0o644)
        with open(path, "wb") as out:
            out.write(index)
        # The control: git in the repository itself no longer reads the change.
        plain = subprocess.run(["git", "-C", self.repo.root, "diff", "--numstat", self.base, commit, "--", SOURCE],
                               env=GIT_ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual((plain.returncode, plain.stdout), (0, b"1\t0\ttoy/src/a.py\n"))
        out = self.named(commit)
        self.assertEqual(self.places(out)["runner"], [("toy/src/a.py", 3, "pytest")])
        self.assertEqual(out["source"]["lines"], 1)

    def gits_started(self):
        """A list that every git the program starts from here on is added to, as the program's own object for it.
        Held here, so that none is tidied away merely by being forgotten: Python waits for an ended child of an
        object it lets go of, which would hide a program that did not."""
        started = []
        real = named.subprocess.Popen

        class Held(real):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                started.append(self)

        named.subprocess.Popen = Held
        self.addCleanup(setattr, named.subprocess, "Popen", real)
        return started

    def all_tidied(self, started, name):
        """Fails unless the program started a git, waited for each it started, and closed each one's output.
        Ends and waits for any it left, so that a broken program leaves nothing behind a test."""
        left = [proc for proc in started if proc.returncode is None]
        for proc in left:
            proc.kill()
            proc.wait()
        unclosed = [proc for proc in started if proc.stdout is not None and not proc.stdout.closed]
        for proc in unclosed:
            proc.stdout.close()
        self.assertEqual((len(started) > 0, len(left), len(unclosed)), (True, 0, 0), name)

    def test_more_places_than_are_listed(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\n" + "pytest\n" * 5})
        self.addCleanup(setattr, named, "MAX_PLACES_BYTES", named.MAX_PLACES_BYTES)
        # The control: with the bound as it is, the five places are listed.
        self.assertEqual(len(named.report(self.repo.root, self.base, commit, SOURCE)["named"]["runner"]), 5)
        # Each place counts as its path's bytes and 64 more: five of them come to 380.
        named.MAX_PLACES_BYTES = 379
        with self.assertRaises(named.Fail) as caught:
            named.report(self.repo.root, self.base, commit, SOURCE)
        self.assertEqual(str(caught.exception), "the change names more places than 379 bytes list, so they are not listed")
        named.MAX_PLACES_BYTES = 380
        self.assertEqual(len(named.report(self.repo.root, self.base, commit, SOURCE)["named"]["runner"]), 5)

    def test_the_time_is_for_all_of_gits_runs_together(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        self.addCleanup(setattr, named, "MAX_SECONDS", named.MAX_SECONDS)
        scratch = os.path.join(self.work, "scratch")
        os.mkdir(scratch)
        named.MAX_SECONDS = 2
        git = named.Git(self.repo.root, scratch)
        # The control: at once, a run that takes no time is let through.
        self.assertEqual(git.commit("commit", commit), commit)
        time.sleep(2.5)
        # The same run, once the time is used up, is ended, though it would take no time itself.
        with self.assertRaises(named.Late):
            git.commit("commit", commit)

    def test_a_file_too_big_to_read_is_listed_with_the_binary_ones(self):
        commit = self.repo.commit({"toy/src/big.py": "pytest\n" + "x = 1\n" * 400,
                                   "toy/src/a.py": "one = 1\ntwo = 2\njunit\n"})
        self.addCleanup(setattr, named, "MAX_FILE_BYTES", named.MAX_FILE_BYTES)
        # The control: with the bound as it is, both files are read.
        out = named.report(self.repo.root, self.base, commit, SOURCE)
        self.assertEqual((out["binary"], [place["path"] for place in out["named"]["runner"]]), ([], ["toy/src/big.py"]))
        named.MAX_FILE_BYTES = 1000
        out = named.report(self.repo.root, self.base, commit, SOURCE)
        self.assertEqual(out["binary"], ["toy/src/big.py"])
        self.assertEqual(self.places(out), {"runner": [], "report": [("toy/src/a.py", 3, "junit")], "ending": []})

    def test_a_word_python_reads_and_the_bytes_do_not_hold_is_not_found_and_the_program_says_so(self):
        wide = "".join(chr(ord(letter) + 0xFEE0) for letter in "pytest")
        for name, body in (("another encoding", b"# coding: utf-7\nimport +AHAAeQB0AGUAcwB0-\n"),
                           ("other letters", ("import " + wide + "\nx = 1\n").encode("utf-8"))):
            # The control: Python reads these bytes as a file that names pytest.
            self.assertEqual(compile(body, "b.py", "exec").co_names[0], "pytest", name)
            out = self.named(self.repo.commit({"toy/src/b.py": body}))
            self.assertEqual(self.places(out), {group: [] for group in GROUPS}, name)
            self.assertEqual(out["source"]["lines"], 2, name)
        said = " ".join((named.__doc__ or "").split())
        self.assertIn('in a file declared as UTF-7, "+AHAAeQB0AGUAcwB0-" is the name pytest, and is not found', said)
        self.assertIn("written in other letters that Python takes for the same name", said)
        # And where the program describes itself to whoever runs it.
        done = self.run_named("--help")
        self.assertEqual(done.returncode, 0)
        self.assertIn(" ".join(named.LIMIT.split()), " ".join(done.stdout.decode("ascii").split()))
        self.assertIn("written in other letters that Python takes for the same name", named.LIMIT)
        self.assertIn("declares another encoding", named.LIMIT)

    def test_a_patch_and_its_list_that_disagree_and_an_unexpected_error(self):
        commit = self.repo.commit({"toy/src/a.py": "one = 1\ntwo = 2\npytest\n"})
        changed = named.changed
        self.addCleanup(setattr, named, "changed", changed)
        named.changed = lambda git, *args: changed(git, *args) + [(b"toy/src/z.py", False)]
        with self.assertRaises(named.Fail):
            named.report(self.repo.root, self.base, commit, SOURCE)

        def broken(*args):
            raise RuntimeError("a text that is not printed")
        named.changed = broken
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = named.main(["--repo", self.repo.root, "--base", self.base, "--commit", commit, "--source", SOURCE])
        self.assertEqual((code, err.getvalue()), (1, "named: could not read the change (RuntimeError)\n"))

    def test_the_patch_is_read_by_its_counts(self):
        head = b"diff --git a/x b/x\nindex 1..2 100644\n--- a/x\n+++ b/x\n"
        self.assertEqual(named.added_lines(head + b"@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n"),
                         [[(1, b"b")]])
        self.assertEqual(named.added_lines(head + b"@@ -1 +1,2 @@\n-a\n\\ No newline at end of file\n+b\n+c\n"),
                         [[(1, b"b"), (2, b"c")]])
        self.assertEqual(named.added_lines(head + b"@@ -4,2 +7,2 @@ def f():\n-a\n x\n+++ b\n"), [[(8, b"++ b")]])
        self.assertEqual(named.added_lines(head + b"@@ -0,0 +1 @@\n+diff --git a/y b/y\n" + head
                                           + b"Binary files a/x and b/x differ\n"), [[(1, b"diff --git a/y b/y")], []])
        self.assertEqual(named.added_lines(b""), [])
        for bad in (b"@@ -1 +1 @@\n+a\n", head + b"@@ -1 +1,2 @@\n-a\n+b\n", head + b"@@ -1 +1 @@\n-a\n+b\nstray\n",
                    head + b"@@ -1 +1 @@\n-a\n-b\n+c\n", head + b"@@ -1 +1 @@\n-a\n+b\n+c\n",
                    head + b"@@ -1,0 +1 @@\n x\n+a\n", head + b"@@ -1 +1 @@\n-a\n\n"):
            with self.assertRaises(named.Fail, msg=bad):
                named.added_lines(bad)

    def test_the_sentence_goes_with_every_use(self):
        done = self.run_named("--help")
        self.assertEqual(done.returncode, 0)
        self.assertIn(named.NOTE.encode("ascii"), done.stdout)
        self.assertIn(named.NOTE, named.__doc__ or "")
        self.assertEqual(named.NOTE, "A change that names none of these is not thereby shown to have left the test "
                                     "run alone.")


if __name__ == "__main__":
    unittest.main()
