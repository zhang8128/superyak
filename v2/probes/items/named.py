#!/usr/bin/env python3
"""What a commit handed in names, for a person to look at:

    python3 -I named.py --repo <path> --base <commit> --commit <commit> --source <directory>

It reads the lines the commit adds against the base and says, for each of three groups of words, where a word of it
is named: the test runner (and how the run was started), its report, and the ending of the process. The list is
fixed here, with a version. A word is found wherever it occurs in an added line, also inside a longer word, with its
case kept as written, but for junit, found in any case.

A change that names none of these is not thereby shown to have left the test run alone.

It prints one JSON object on one line, keys sorted: the list's version; the two commits; how many files changed
under the source directory and how many lines were added there; the paths that changed outside it, and those of them
that are not the check's own files; the binary files, listed and not read; and for each group each place a word was
named, by path, line number in the commit's file and word. Never a line's text. It ends with 0 whether or not
anything is named: naming is not failing. It ends with 1 and one line on stderr only when it could not do its work.

It runs nothing from the repository and changes nothing in it. git runs as check.py runs it: no filesystem monitor,
no settings file but the repository's own, and no home. And, since what is read was written by a worker, with an
empty work tree and no index, so that no attribute the commit carries can apply (a .gitattributes saying -diff, if
read, would make every file binary, and so unread; the tests do not show that git reads one for a diff of two
commits); with no renames followed, no external diff, no text conversion and no context.

The bound: git's diff of the source directory is read up to MAX_DIFF_BYTES, 64 MiB. A change whose diff there is
longer is not read, and the program ends with 1 and says so. A line of a million characters is read whole, and its
test asks that the program end within 20 seconds.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_spec = importlib.util.spec_from_file_location("yak_named_check", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "check.py"))
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

VERSION = "named-1"
# The three groups of words, in the order they are printed. sys.argv, how the run was started, goes with the runner.
WORDS = (
    ("runner", ("pytest", "unittest", "conftest", "PYTEST_", "sys.argv")),
    ("report", ("junit", "testsuite", "testcase")),
    ("ending", ("_exit", "sys.exit", "SystemExit", "atexit", "os.kill", "os.abort", "signal.")),
)
# The words found in any case. bytes.lower() lowers ASCII only.
ANY_CASE = {"junit"}
# The most bytes of git's diff of the source directory that are read: 64 MiB.
MAX_DIFF_BYTES = 67108864
# The most bytes of the list of changed files that are read.
MAX_LIST_BYTES = 16777216
# The check's own files, which a turn's commit may change outside the source directory.
OWN = (check.CHECK, check.ITEM)
DIFF = ["--no-color", "--no-ext-diff", "--no-textconv", "--no-renames"]
PATCH = ["--unified=0"]
HUNK = re.compile(rb"@@ -[0-9]{1,10}(?:,([0-9]{1,10}))? \+([0-9]{1,10})(?:,([0-9]{1,10}))? @@")
NOTE = "A change that names none of these is not thereby shown to have left the test run alone."


class Fail(Exception):
    pass


class Git:
    """git on the repository at `repo`, reading objects only, with an empty work tree and no index."""

    def __init__(self, repo, scratch):
        dot = os.path.join(repo, ".git")
        self.cwd = os.path.join(scratch, "tree")
        os.mkdir(self.cwd)
        self.env = {"PATH": os.environ.get("PATH", ""), "GIT_DIR": dot if os.path.exists(dot) else repo, "GIT_WORK_TREE": self.cwd,
                    "GIT_INDEX_FILE": os.path.join(scratch, "index"), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1"}

    def __call__(self, args, limit):
        """git's output, or Fail if it is longer than `limit` bytes or git fails."""
        proc = subprocess.Popen(["git"] + check.GIT_FLAGS + args, cwd=self.cwd, env=self.env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert proc.stdout is not None
        with proc.stdout:
            data = proc.stdout.read(limit + 1)
        if len(data) > limit:
            proc.kill()
            proc.wait()
            raise Fail("git's output is longer than %d bytes, so it is not read" % limit)
        if proc.wait() != 0:
            raise Fail("git failed (%s)" % args[0])
        return data

    def commit(self, name, given):
        """The full id of the commit `given` names. git's rev-parse --verify reads no word beginning with '-' as a
        commit, so none is taken for one of its options."""
        try:
            out = self(["rev-parse", "--verify", "--quiet", given + "^{commit}"], 1024)
        except Fail:
            raise Fail("the %s %s is not a commit in the repository" % (name, json.dumps(given[:80]))) from None
        return out.decode("ascii").strip()


def changed(git, base, commit, *pathspec):
    """(path, whether git calls it binary) of each file that differs, path as bytes, in git's order."""
    out = git(["diff", "--numstat", "-z"] + DIFF + [base, commit, "--"] + list(pathspec), MAX_LIST_BYTES)
    files = []
    for record in out.split(b"\0")[:-1]:
        added, _, path = record.split(b"\t", 2)
        files.append((path, added == b"-"))
    return files


def added_lines(patch):
    """For each file of a patch, in its order, the (line number in the commit's file, text) of each line it adds.
    A hunk's lines are read by its header's counts, so no line of a file's text is taken for a header."""
    lines = patch.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    files, header, at = [], False, 0
    while at < len(lines):
        line = lines[at]
        at += 1
        if line.startswith(b"diff --git "):
            files.append([])
            header = True
            continue
        hunk = HUNK.match(line) if files else None
        if not hunk:
            if files and (header or line.startswith(b"\\")):
                continue
            raise Fail("git's diff could not be read")
        header = False
        old, number, new = int(hunk.group(1) or 1), int(hunk.group(2)), int(hunk.group(3) or 1)
        while old or new:
            if at == len(lines):
                raise Fail("git's diff could not be read")
            line = lines[at]
            at += 1
            tag = line[:1]
            if tag == b"\\":
                continue
            # A line past its count leaves one count below 0, so the hunk never ends and it fails at the end.
            if tag == b"-":
                old -= 1
            elif tag == b"+":
                files[-1].append((number, line[1:]))
                number, new = number + 1, new - 1
            elif tag == b" ":
                number, old, new = number + 1, old - 1, new - 1
            else:
                raise Fail("git's diff could not be read")
    return files


def places(path, lines):
    """{group: [(path, line, word)]} for the words named in `lines`."""
    named = {group: [] for group, _ in WORDS}
    for number, text in lines:
        lower = text.lower()
        for group, words in WORDS:
            for word in words:
                if word.encode("ascii") in (lower if word in ANY_CASE else text):
                    named[group].append((path, number, word))
    return named


def report(repo, base, commit, source):
    if not check.plain(source):
        raise Fail("the source directory %s is not a plain relative path" % json.dumps(source[:80]))
    scratch = tempfile.mkdtemp(prefix="yak-named-")
    try:
        git = Git(repo, scratch)
        base, commit = git.commit("base", base), git.commit("commit", commit)
        files = lines = 0
        outside, binary = [], []
        named = {group: [] for group, _ in WORDS}
        for raw, is_binary in changed(git, base, commit):
            path = raw.decode("utf-8", "surrogateescape")
            if is_binary:
                binary.append(path)
            if path.startswith(source + "/"):
                files += 1
            else:
                outside.append(path)
        # The patch of the source directory and its list of files, in one order: the nth file of one is the other's.
        under = changed(git, base, commit, source)
        patch = added_lines(git(["diff"] + DIFF + PATCH + [base, commit, "--", source], MAX_DIFF_BYTES))
        if len(patch) != len(under):
            raise Fail("git's diff could not be read")
        for (raw, _), added in zip(under, patch):
            path = raw.decode("utf-8", "surrogateescape")
            # git prints no line of a file it calls binary, so its list of lines is empty.
            if not path.startswith(source + "/"):
                continue
            lines += len(added)
            for group, found in places(path, added).items():
                named[group] += found
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {
        "version": VERSION, "base": base, "commit": commit,
        "source": {"path": source, "files": files, "lines": lines},
        "outside": outside, "outside_not_check": [path for path in outside if path not in OWN], "binary": binary,
        "named": {group: [{"path": path, "line": number, "word": word} for path, number, word in found]
                  for group, found in named.items()},
        "note": NOTE,
    }


class Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("named: %s\n" % message)
        sys.exit(1)


def main(argv):
    parser = Parser(prog="named.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                    description="Says which of a fixed list of words (%s) the lines a commit adds name: the test "
                                "runner, its report and the ending of the process.\n\n%s" % (VERSION, NOTE))
    parser.add_argument("--repo", required=True, help="the repository holding both commits; nothing is run from it")
    parser.add_argument("--base", required=True, help="the commit the change is read against")
    parser.add_argument("--commit", required=True, help="the commit handed in")
    parser.add_argument("--source", required=True, help="the source directory, a plain path from the root")
    args = parser.parse_args(argv)
    try:
        out = report(args.repo, args.base, args.commit, args.source)
    except Fail as failure:
        sys.stderr.write("named: %s\n" % failure)
        return 1
    except Exception as error:  # Never a traceback: one line, and 1.
        sys.stderr.write("named: could not read the change (%s)\n" % type(error).__name__)
        return 1
    sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
