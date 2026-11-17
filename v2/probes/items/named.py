#!/usr/bin/env python3
"""What a commit handed in names, for a person to look at:

    python3 -I named.py --repo <path> --base <commit> --commit <commit> --source <directory>

It reads the lines the commit adds against the base and says, for each of three groups of words, where a word of it
is named: the test runner (and how the run was started), its report, and the ending of the process. The list is
fixed here, with a version. A word is found wherever its bytes occur in an added line as git prints it, also inside
a longer word, with its case kept as written, but for junit, found in any case.

What is matched is bytes, and nothing is read as Python would read it. A word spelt another way is not found: built
when the program runs; written with an escape; written in other letters that Python takes for the same name (the
full-width ones, say); or in a file that declares another encoding for its source (in a file declared as UTF-7,
"+AHAAeQB0AGUAcwB0-" is the name pytest, and is not found).

A change that names none of these is not thereby shown to have left the test run alone.

It prints one JSON object on one line, keys sorted: the list's version; the two commits; how many files changed
under the source directory and how many lines were added there; the paths that changed outside it, and those of them
that are not the check's own files; the binary files, listed and not read; and for each group each place a word was
named, by path, line number in the commit's file and word. Never a line's text. It ends with 0 whether or not
anything is named: naming is not failing. It ends with 1 and one line on stderr only when it could not do its work.

Where to run it. On a repository whose objects a worker did not write: the one a room fetches a turn's commit into.
A fetch works out each object's name from what the object holds, so there the two commits are what their names say.
What the program says is only as good as that store. Of a repository it reads the objects and nothing else, and it
runs nothing from it and changes nothing in it: git runs in an empty repository of the program's own that borrows
the objects, from an empty directory, with no settings file of the machine's and no home. So a setting, an
attributes file or a replaced object that a worker left in the repository is not read (an attributes file saying
-diff, or a low core.bigFileThreshold, would make every file binary, and so unread); nor is a commit-graph, which
can give a commit another tree than the commit names, or a multi-pack-index, which says where each object lies. No
attributes file of a work tree applies either. No renames are followed, and there is no external diff, text
conversion or context.

What that does not cover: an object store that a worker wrote. git does not check what it reads from a store
against the name it asked for, follows the store's own list of other stores and its links wherever they lead, and
holds what it reads in memory. Such a store can give this program other lines than the commit's, have git read
files outside the repository, or have git use memory without limit before its time is up. Nothing here bounds
git's memory.

The bounds there are. git's diff of the source directory is read up to MAX_DIFF_BYTES, 2 MiB, and its list of the
files that changed up to MAX_LIST_BYTES, 512 KiB: a change with more of either is not read, and the program ends
with 1 and says so. The places named are listed while their paths come to no more than MAX_PLACES_BYTES, 1 MiB: a
change that names more is not listed, and the program ends with 1 and says so. So what is printed is bounded. No
figure is given for the memory this program uses: it grows with the diff it reads, up to that bound. A file of more
than MAX_FILE_BYTES, 16 MiB, on either side is listed with the binary files and not read. All of git's runs
together have MAX_SECONDS, 120: when that is up, git is ended and waited for, and the program ends with 1 and says
so. That is a limit on git's runs and not on the whole program: starting git, and writing the answer to whoever
reads it, are outside it. It is there for a repository whose files keep git waiting (a pipe where an object is
looked for). A change within the bounds that is dear to compare can run out of time too, and is then not read. A
line of a million characters is read whole, and its test asks that the program end within 20 seconds.

An interrupt from the keyboard is held back while git is started and while it is ended and waited for, and is let
through while git's output is read: so one interrupt, whenever it comes, leaves no git behind. git stays in this
program's own process group, so that whoever ends the group ends git with it. If this program alone is ended
outright, git is not.

A repository whose objects are named by SHA-256 is not read: the program's own repository names them by SHA-1, the
commits are not found, and it ends with 1.
"""
import argparse
import importlib.util
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

_spec = importlib.util.spec_from_file_location("yak_named_check", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "check.py"))
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

VERSION = "named-1"
# The three groups of words, in the order they are printed. How the run was started (sys.argv, orig_argv) goes
# with the runner. A word is here for what naming it could do to a test run from inside the runner's own process:
# reach the runner or learn that it is running; write the report; or end or replace the process before the runner
# has said what it found. Where one word holds another, only the shorter is here: exit for sys.exit, _exit and
# atexit; kill for os.kill and killpg; signal, abort.
#
# The list was chosen with a count, so that a flag tells a person something: of 193 merged changes to one
# project's source that each made failing tests pass, 13 name a word of it and 180 name none. Ten of the 13 name
# exit: in a program's entry point, or in a comment about the code it ends with.
WORDS = (
    ("runner", ("pytest", "unittest", "conftest", "PYTEST_", "sys.argv", "orig_argv", "sys.modules", "pluggy",
                "settrace", "setprofile", "_getframe")),
    ("report", ("junit", "testsuite", "testcase", "report.xml", "etree", "minidom")),
    ("ending", ("exit", "quit", "SystemExit", "kill", "abort", "signal", "execv", "execl", "os.fork")),
)
# The words found in any case. bytes.lower() lowers ASCII only.
ANY_CASE = {"junit"}
# The most bytes of git's diff of the source directory that are read: 2 MiB.
MAX_DIFF_BYTES = 2097152
# The most bytes of the list of changed files that are read: 512 KiB.
MAX_LIST_BYTES = 524288
# The most that the places named may come to, each counted as its path's bytes and 64 more: 1 MiB.
MAX_PLACES_BYTES = 1048576
# What is held back while git is started and while it is ended and waited for.
INTERRUPTS = {signal.SIGINT}
# A file of more bytes than this is not read: git is told to treat it as it treats a binary one. 16 MiB.
MAX_FILE_BYTES = 16777216
# How long all of git's runs together may take.
MAX_SECONDS = 120
# The check's own files, which a turn's commit may change outside the source directory.
OWN = (check.CHECK, check.ITEM)
DIFF = ["--no-color", "--no-ext-diff", "--no-textconv", "--no-renames"]
PATCH = ["--unified=0"]
HUNK = re.compile(rb"@@ -[0-9]{1,10}(?:,([0-9]{1,10}))? \+([0-9]{1,10})(?:,([0-9]{1,10}))? @@")
NOTE = "A change that names none of these is not thereby shown to have left the test run alone."
# What the matching cannot see, said wherever the program describes itself.
LIMIT = ("What is matched is bytes. A word built when the program runs, written with an escape, written in other "
         "letters that Python takes for the same name, or spelt in a file that declares another encoding for its "
         "source, is not found.")


def settings():
    """git's own settings for every run, beside no filesystem monitor (check.GIT_FLAGS): a file over the bound is
    treated as a binary one; and neither a commit-graph nor a multi-pack-index is read, since either can stand
    between a commit's name and what the commit holds. Made at each run, so that a bound changed is the bound used."""
    return ["-c", "core.bigFileThreshold=%d" % MAX_FILE_BYTES, "-c", "core.commitGraph=false",
            "-c", "core.multiPackIndex=false"]


class Fail(Exception):
    pass


class Late(Fail):
    """git was ended because the time for its runs was up."""


class Git:
    """git reading the objects of the repository at `repo`, and nothing else of it: it runs in a repository of the
    program's own, made empty in `scratch`, that borrows them. So the repository's settings, its attributes file and
    its replaced objects, which a worker may have written, are never read."""

    def __init__(self, repo, scratch):
        dot = os.path.join(repo, ".git")
        objects = os.path.join(dot if os.path.isdir(dot) else repo, "objects")
        if not os.path.isdir(objects):
            raise Fail("%s is not a repository with objects of its own" % json.dumps(repo[:80]))
        # The work tree is the directory git runs in: an empty one, so that no attributes file is found in it.
        self.cwd = os.path.join(scratch, "tree")
        own = os.path.join(scratch, "own.git")
        for made in (self.cwd, os.path.join(own, "refs"), os.path.join(own, "objects", "info")):
            os.makedirs(made)
        with open(os.path.join(own, "HEAD"), "w") as out:
            out.write("ref: refs/heads/none\n")
        # Borrowed through a link named here, so that no character of the repository's path is read as git's.
        os.symlink(os.path.abspath(objects), os.path.join(scratch, "borrowed"))
        with open(os.path.join(own, "objects", "info", "alternates"), "w") as out:
            out.write(os.path.join(scratch, "borrowed") + "\n")
        self.env = {"PATH": os.environ.get("PATH", ""), "GIT_DIR": own, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_ATTR_NOSYSTEM": "1"}
        self.until = time.monotonic() + MAX_SECONDS

    def __call__(self, args, limit):
        """git's output, or Fail if it is longer than `limit` bytes, if git fails, or if the time for all of git's
        runs is up. One thread does all of it: it reads until the time is up, and it alone ends git, and only
        before it has waited for git, so no signal goes to a process that is no longer git. On every way out of
        here, an error of this program's own among them, git is ended if it runs and is waited for. An interrupt
        is held back from before git is started until its output is being read, and again from the end of the
        reading until git is ended and waited for: it is raised in the reading or after all is tidied, and git
        itself is started with interrupts as they were."""
        held = signal.pthread_sigmask(signal.SIG_BLOCK, INTERRUPTS)
        try:
            proc = subprocess.Popen(["git"] + check.GIT_FLAGS + settings() + args, cwd=self.cwd, env=self.env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, held))
            chunks, size, late = [], 0, False
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, held)
                assert proc.stdout is not None
                pipe = proc.stdout.fileno()
                while size <= limit:
                    left = self.until - time.monotonic()
                    if left <= 0 or not select.select([pipe], [], [], left)[0]:
                        late = True
                        break
                    chunk = os.read(pipe, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                if size <= limit and not late:
                    # git has closed its output. It has what is left of the time to end.
                    try:
                        proc.wait(timeout=max(0.0, self.until - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        late = True
                # Held back again before the way out, so that the tidying below is entered with it held.
                signal.pthread_sigmask(signal.SIG_BLOCK, INTERRUPTS)
            finally:
                signal.pthread_sigmask(signal.SIG_BLOCK, INTERRUPTS)
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                if proc.stdout is not None:
                    proc.stdout.close()
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, held)
        if size > limit:
            raise Fail("git's output is longer than %d bytes, so it is not read" % limit)
        if late:
            raise Late("git did not end within %d seconds, so it was ended" % MAX_SECONDS)
        if proc.returncode != 0:
            raise Fail("git failed (%s)" % args[0])
        return b"".join(chunks)

    def commit(self, name, given):
        """The full id of the commit `given` names. git's rev-parse --verify reads no word beginning with '-' as a
        commit, so none is taken for one of its options."""
        try:
            out = self(["rev-parse", "--verify", "--quiet", given + "^{commit}"], 1024)
        except Late:
            raise
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
        files = lines = listed = 0
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
                listed += len(found) * (len(raw) + 64)
                if listed > MAX_PLACES_BYTES:
                    raise Fail("the change names more places than %d bytes list, so they are not listed"
                               % MAX_PLACES_BYTES)
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
                                "runner, its report and the ending of the process.\n\n%s\n\n%s\n\nRun it on a "
                                "repository whose objects a worker did not write: what it says is only as good as "
                                "that store." % (VERSION, LIMIT, NOTE))
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
