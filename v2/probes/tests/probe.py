#!/usr/bin/env python3
"""What a plain `cargo test` of v2 does in the place this is run from, and how long it takes.

    python3 -I v2/probes/tests/probe.py <vendored crates' directory> [seconds the tests may take] > tests-run.txt 2>&1

Run at the root of a checkout. A worker of the room runs it inside its own program's sandbox and hands in
what it printed; the lead runs the same where nothing is hidden. Nothing here judges: it prints, and a person
reads.

It prints, in this order:
  PLACE    whether this place can list the machine's processes the way the room does, and whether it can
           enter a jail. Where it cannot, the tests that need the room cannot pass, which is why they are left
           out of a plain run; where it can, a pass here says nothing about a worker's sandbox.
  BUILD    `cargo build`, offline, from the vendored crates, and its seconds.
  COMPILE  `cargo test --no-run`: the tests built and not run, so that the tests' own seconds are apart.
  TESTS    `cargo test --no-fail-fast` under a limit of its own (240 seconds unless another is given), with
           all of its own process group ended at the limit, so that a test that waits cannot take the turn.
           Then the counts, why tests were ignored, and all that cargo printed. It says `ok` only when cargo
           ended well and the harness's own lines show tests that ran and passed; a good exit with no such
           lines is said as that.
  PROBE DONE, as the last line, whatever happened before it.

The whole probe keeps to nine minutes: a worker's program may end a command at ten. When the build has used
the time, the tests are not run, and it says so; run again, the build is already made.
"""
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

WHOLE = 540  # seconds for all of it
TESTS = 240  # seconds for the tests, unless another number is given
LEAST = 20  # with fewer seconds than this left of the whole, the tests are not started
KEPT = 400_000  # bytes of cargo's output printed; the middle of a longer one is left out, and said to be
RESULT = re.compile(
    r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; "
    r"(\d+) filtered out; finished in \S+$"
)
STARTED = re.compile(r"^ {5}Running |^ {3}Doc-tests ")
IGNORED = re.compile(r"^test (.+) \.\.\. ignored(?:, (.*))?$")
FAILED = re.compile(r"^test (.+) \.\.\. FAILED$")


def say(line=""):
    print(line, flush=True)


def limited(command, seconds, cwd=None, env=None):
    """Runs a command, and ends it and all of its own group after `seconds`.

    Returns (exit, or None when the limit ended it; seconds taken; what it printed; what was left running).
    The last is "nothing", or a word about processes of the command's own group that outlived it. What it
    prints goes to a file and not through a pipe: a process that outlives the command and still holds a pipe
    would otherwise be waited for.
    """
    began = time.monotonic()
    with tempfile.TemporaryFile() as printed:
        try:
            child = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=printed,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e:
            return 127, 0.0, "could not be started: %s\n" % e, "nothing"
        try:
            code = child.wait(timeout=max(seconds, 0))
        except subprocess.TimeoutExpired:
            code = None
        took = time.monotonic() - began
        # Whatever is in the command's group now has outlived it, or is the command itself at its limit.
        left = "nothing"
        try:
            os.killpg(child.pid, signal.SIGKILL)
            if code is not None:
                left = "processes it had started, ended now"
        except ProcessLookupError:
            pass
        except PermissionError:
            left = "processes that could not be ended from here"
        if code is None:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                left = "the command itself, which did not end when killed"
        printed.seek(0)
        out = printed.read().decode("utf-8", errors="replace")
    return code, took, out, left


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:300]
    return "nothing"


def place(system):
    """Two lines about this place: the room's own look at processes, and the plainest jail."""
    look = ["ps", "-o", "pid=,ppid=,pgid=,lstart=", "-A"]
    code, _, out, _ = limited(look, 20, env=dict(os.environ, LC_ALL="C"))
    lines = [line for line in out.splitlines() if line.strip()]
    if code == 0 and lines:
        say("PLACE processes: CAN list them as the room does (%d lines)" % len(lines))
    else:
        say("PLACE processes: CANNOT list them as the room does: `%s` ended with %s and said: %s"
            % (" ".join(look), "its limit" if code is None else code, first_line(out)))
    if system == "Darwin":
        jail = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"]
    else:
        jail = ["bwrap", "--ro-bind", "/", "/", "/bin/true"]
    code, _, out, _ = limited(jail, 20)
    if code == 0:
        say("PLACE jail: CAN enter one (`%s`)" % " ".join(jail))
    else:
        say("PLACE jail: CANNOT enter one: `%s` ended with %s and said: %s"
            % (" ".join(jail), "its limit" if code is None else code, first_line(out)))


def counted(text):
    """What cargo's own lines add up to: a dict of counts, the ignored by reason, the failed by name."""
    seen = {"programs": 0, "results": 0, "unread": 0, "passed": 0, "failed": 0, "ignored": 0, "inner": 0}
    reasons = {}
    failed = []
    for line in text.splitlines():
        if STARTED.match(line):
            seen["programs"] += 1
        elif line.startswith("test result:"):
            parts = RESULT.match(line)
            if not parts:
                seen["unread"] += 1
                continue
            if int(parts.group(6)) != 0:
                # Nothing is filtered in this run, so this is the result of a test program that a test started
                # for itself with one test's name, shown because that test failed. It is not counted twice.
                seen["inner"] += 1
                continue
            seen["results"] += 1
            for key, at in (("passed", 2), ("failed", 3), ("ignored", 4)):
                seen[key] += int(parts.group(at))
        else:
            found = IGNORED.match(line)
            if found:
                reason = found.group(2) or "no reason given"
                reasons[reason] = reasons.get(reason, 0) + 1
            found = FAILED.match(line)
            if found and found.group(1) not in failed:
                failed.append(found.group(1))
    return seen, reasons, failed


def unshown(seen, failed):
    """Why cargo's good exit is not taken for tests that ran and passed: one line each, none when it is.

    The exit says only that the command ended well. That tests ran and passed is read from the harness's own
    lines: a program started for each result, every result read, none failed, at least one test passed.
    """
    doubts = []
    if seen["programs"] == 0:
        doubts.append("no test program was started")
    if seen["results"] != seen["programs"]:
        doubts.append("%d test programs were started and %d results were read" % (seen["programs"], seen["results"]))
    if seen["unread"]:
        doubts.append("%d results could not be read" % seen["unread"])
    if seen["inner"]:
        doubts.append("%d results leave tests out by a filter" % seen["inner"])
    if seen["failed"] or failed:
        doubts.append("%d tests are counted as failed" % max(seen["failed"], len(failed)))
    if seen["passed"] == 0:
        doubts.append("no test is counted as passed")
    return doubts


def kept(text):
    """All of a text, or its two ends and a line that says what was left out."""
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= KEPT:
        return text
    head = raw[: KEPT // 4].decode("utf-8", errors="replace")
    tail = raw[-(KEPT - KEPT // 4):].decode("utf-8", errors="replace")
    return "%s\n[... %d bytes of the middle are left out ...]\n%s" % (head, len(raw) - KEPT, tail)


def tail_of(text, lines=30):
    return "\n".join("    " + line for line in text.splitlines()[-lines:])


def main(argv):
    began = time.monotonic()
    tests_limit = TESTS
    if len(argv) == 3:
        try:
            tests_limit = int(argv[2])
        except ValueError:
            tests_limit = -1
    if len(argv) not in (2, 3) or not os.path.isabs(argv[1]) or not 1 <= tests_limit <= WHOLE:
        say("usage: python3 -I v2/probes/tests/probe.py <vendored crates' directory, absolute> [seconds, 1 to %d]"
            % WHOLE)
        say("TESTS not run: the probe was not given what it needs")
        say("PROBE DONE")
        return 2
    vendor = argv[1]
    root = os.getcwd()
    v2 = os.path.join(root, "v2")
    system = os.uname().sysname
    say("PROBE a plain cargo test of v2, in the place this is run from")
    say("at %s, on %s %s, in %s" % (time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), system,
                                    os.uname().machine, root))
    place(system)
    why = None
    if not os.path.isfile(os.path.join(v2, "Cargo.toml")):
        why = "there is no v2/Cargo.toml here: run it at the root of a checkout"
    elif not os.path.isdir(vendor):
        why = "the vendored crates' directory is not there: %s" % vendor
    if why:
        say("BUILD not run: %s" % why)
        say("TESTS not run: %s" % why)
        say("PROBE DONE")
        return 1
    target = os.path.join(v2, "target")
    env = dict(os.environ, CARGO_HOME=os.path.join(target, "cargo-home"), CARGO_TARGET_DIR=target)
    words = ["--locked", "--offline", "--config", 'source.crates-io.replace-with="vendored"',
             "--config", 'source.vendored.directory="%s"' % vendor]
    shown = "--locked --offline, from the vendored crates"

    def left():
        return WHOLE - (time.monotonic() - began)

    code, _, out, _ = limited(["cargo", "--version"], 20, cwd=v2, env=env)
    say("cargo: %s" % (first_line(out) if code == 0 else "could not be asked its version: " + first_line(out)))
    status = 0
    for name, command in (("BUILD", ["cargo", "build"]), ("COMPILE", ["cargo", "test", "--no-run"])):
        code, took, out, _ = limited(command + words, left(), cwd=v2, env=env)
        said = "`%s %s`" % (" ".join(command), shown)
        if code == 0:
            say("%s ok in %.0f s: %s" % (name, took, said))
            continue
        ended = "was ended at the probe's own limit" if code is None else "failed with %s" % code
        say("%s %s after %.0f s: %s. Its last lines:" % (name, ended, took, said))
        say(tail_of(out))
        say("TESTS not run: %s did not end well" % {"BUILD": "the build", "COMPILE": "the tests' own build"}[name])
        say("PROBE DONE")
        return 1
    # What is left for the tests, less a little for what is printed after them.
    free = int(left()) - 5
    limit = min(tests_limit, free)
    if free < LEAST:
        say("TESTS not run: the builds took the probe's time (%.0f s of %d are gone). Run it again: they are made"
            % (time.monotonic() - began, WHOLE))
        say("PROBE DONE")
        return 1
    command = ["cargo", "test", "--no-fail-fast"]
    code, took, out, after = limited(command + words, limit, cwd=v2, env=env)
    said = "`%s %s`, under a limit of %d s" % (" ".join(command), shown, limit)
    seen, reasons, failed = counted(out)
    doubts = unshown(seen, failed)
    if code is None:
        say("TESTS ended by the limit after %.0f s: %s. A test waited, or they are slow here" % (took, said))
        status = 1
    elif code == 0 and doubts:
        say("TESTS not shown to have passed after %.0f s: %s. Cargo ended with 0, and yet: %s"
            % (took, said, "; ".join(doubts)))
        status = 1
    elif code == 0:
        say("TESTS ok in %.0f s: %s. Every test that ran passed" % (took, said))
    else:
        say("TESTS failed with %s after %.0f s: %s" % (code, took, said))
        status = 1
    say("  test programs started: %d, with %d results (%d more that could not be read, and %d of test programs"
        " that a failed test had started itself)" % (seen["programs"], seen["results"], seen["unread"], seen["inner"]))
    say("  passed %d, failed %d, ignored %d" % (seen["passed"], seen["failed"], seen["ignored"]))
    for reason in sorted(reasons):
        say("  ignored, %d: %s" % (reasons[reason], reason))
    for name in failed:
        say("  failed: %s" % name)
    say("  left running in cargo's own group when it ended: %s" % after)
    say("--- all that cargo printed:")
    say(kept(out).rstrip("\n"))
    say("--- the end of what cargo printed")
    say("PROBE DONE")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
