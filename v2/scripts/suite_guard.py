#!/usr/bin/env python3
"""Reads what a whole run of v2's tests printed, and says whether every test ran.

    python3 -I suite_guard.py <log> <list of test programs>
    python3 -I suite_guard.py --programs <log>

Tests that need the room are left out of a plain `cargo test`. Where the room can run, the whole suite is asked
for with `-- --include-ignored` (see whole-suite.sh), and then no test is left out. This reads the log of such
a run and ends with 1 when:

  - a `test result:` line counts a test as ignored, or as filtered out;
  - the test programs that were started are not the ones the list names: one missing, or one more;
  - there is not one `test result:` line for each program started (a program that died prints none);
  - a `test result:` line cannot be read.

It does not replace cargo's own exit. A failed test is cargo's to report; this reports a test that did not run.
What it cannot see: a test that a test started in a process of its own, whose output that test kept.

With --programs it prints the programs a log names, in the list's own form, and judges nothing. That is how
the list is made again when a test program is added.

It ends with 2 when it was not given a log and a list it can read.
"""
import re
import sys

# Cargo sets its status word to the right in twelve columns: five spaces before "Running", three before
# "Doc-tests". A line of a test's own output that only holds those words does not begin so.
RUNNING = re.compile(r"^ {5}Running (unittests )?(\S+) \((.+)\)$")
DOC = re.compile(r"^ {3}Doc-tests (\S+)$")
RESULT = re.compile(
    r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; "
    r"(\d+) filtered out; finished in \S+$"
)
COLOUR = re.compile(r"\x1b\[[0-9;]*m")
BUILD_HASH = re.compile(r"-[0-9a-f]{16}$")


def lines_of(path):
    """A log's lines. Bytes that are not text are replaced, not refused: a test may print anything."""
    with open(path, "rb") as log:
        text = log.read().decode("utf-8", errors="replace")
    return [COLOUR.sub("", line).rstrip("\r") for line in text.split("\n")]


def program(line):
    """The program a line of cargo's names, without what differs from one build to the next, or None."""
    found = RUNNING.match(line)
    if found:
        name = found.group(3).rsplit("/", 1)[-1]
        return "Running %s%s [%s]" % (found.group(1) or "", found.group(2), BUILD_HASH.sub("", name))
    found = DOC.match(line)
    if found:
        return "Doc-tests %s" % found.group(1)
    return None


def read(lines):
    """(programs started, result lines as (line number, text, parts or None))."""
    programs = []
    results = []
    for number, line in enumerate(lines, start=1):
        named = program(line)
        if named is not None:
            programs.append(named)
        elif line.startswith("test result:"):
            found = RESULT.match(line)
            results.append((number, line, tuple(int(n) for n in found.groups()[1:]) if found else None))
    return programs, results


def listed(path):
    with open(path, encoding="utf-8") as text:
        return [line.strip() for line in text if line.strip() and not line.lstrip().startswith("#")]


def judge(lines, expected):
    """(what is wrong, one line each; a line that says what was seen)."""
    programs, results = read(lines)
    wrong = []
    passed = 0
    for number, line, parts in results:
        if parts is None:
            wrong.append("line %d is a result that could not be read: %s" % (number, line[:200]))
            continue
        passed += parts[0]
        if parts[2] != 0:
            wrong.append("line %d leaves %d out as ignored: %s" % (number, parts[2], line))
        if parts[4] != 0:
            wrong.append("line %d leaves %d out by a filter: %s" % (number, parts[4], line))
    if not programs:
        wrong.append("no test program was started, by this log")
    left = list(expected)
    for name in programs:
        if name in left:
            left.remove(name)
        else:
            wrong.append("started, and not in the list (or more often than the list has it): %s" % name)
    for name in left:
        wrong.append("in the list, and not started: %s" % name)
    if len(results) != len(programs):
        wrong.append(
            "%d test programs were started and there are %d result lines: one for each is expected"
            % (len(programs), len(results))
        )
    seen = "%d test programs, %d result lines, %d tests passed" % (len(programs), len(results), passed)
    return wrong, seen


def main(argv):
    if len(argv) == 3 and argv[1] == "--programs":
        try:
            programs, _ = read(lines_of(argv[2]))
        except OSError as e:
            print("suite guard: the log could not be read: %s" % e, file=sys.stderr)
            return 2
        for name in sorted(programs):
            print(name)
        return 0
    if len(argv) != 3 or argv[1].startswith("-"):
        print("usage: python3 -I suite_guard.py <log> <list of test programs>", file=sys.stderr)
        print("       python3 -I suite_guard.py --programs <log>", file=sys.stderr)
        return 2
    try:
        lines = lines_of(argv[1])
    except OSError as e:
        print("suite guard: the log could not be read: %s" % e, file=sys.stderr)
        return 2
    try:
        expected = listed(argv[2])
    except (OSError, UnicodeDecodeError) as e:
        print("suite guard: the list could not be read: %s" % e, file=sys.stderr)
        return 2
    if not expected:
        print("suite guard: the list names no test program", file=sys.stderr)
        return 2
    wrong, seen = judge(lines, expected)
    if wrong:
        print("suite guard: NOT every test ran (%s)" % seen)
        for line in wrong:
            print("  " + line)
        return 1
    print("suite guard: every test ran: %s, none ignored, none filtered out, the programs as listed" % seen)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
