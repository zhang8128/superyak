#!/usr/bin/env python3
"""Tests of named.py. Run as: python3 -I test_named.py

Each test makes a small repository in a temporary directory, commits a base and a change, and runs named.py on the
two as a separate process. Its source directory is toy/src.
"""
import contextlib
import importlib.util
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
        lines = ["one = 1", "two = 2"] + ["x = %s  # %s" % (word, MARKER) for group, words in named.WORDS
                                         for word in words]
        commit = self.repo.commit({"toy/src/a.py": "\n".join(lines) + "\n"})
        out = self.named(commit)
        number, expected = 2, {group: [] for group in GROUPS}
        for group, words in named.WORDS:
            for word in words:
                number += 1
                expected[group].append(("toy/src/a.py", number, word))
        self.assertEqual(self.places(out), {group: sorted(found) for group, found in expected.items()})
        self.assertEqual(out["source"], {"path": SOURCE, "files": 1, "lines": number - 2})
        self.assertEqual((out["version"], out["base"], out["commit"]), ("named-1", self.base, commit))
        self.assertEqual(len(sum((words for _, words in named.WORDS), ())), 15)

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
                                            "ending": [("toy/src/a.py", 8, "atexit")]})

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
        self.assertEqual(self.places(out)["ending"], [("toy/src/x/y.py", 2, "signal.")])
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
        self.assertEqual(self.places(out)["ending"], [(path, 2, "os.kill")])

    def test_a_line_of_a_million_characters(self):
        commit = self.repo.commit({"toy/src/long.py": "a\n" + "x" * 1000000 + "atexit" + "y" * 10 + "\n"})
        started = time.monotonic()
        out = self.named(commit)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(self.places(out)["ending"], [("toy/src/long.py", 2, "atexit")])
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
                ("its attributes file", lambda: open(info, "w").write("* -diff\n"), lambda: os.remove(info)),
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
