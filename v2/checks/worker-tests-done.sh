#!/bin/sh
# Judge probe completion in a static checkout, without running the probe.
set -u
LC_ALL=C
PATH=/usr/bin:/bin
export LC_ALL PATH

fail() {
    printf 'FAIL %s\n' "$1" >&2
    exit 1
}

# Test the link first, before any command opens tests-run.txt.
if [ -L tests-run.txt ] || [ ! -f tests-run.txt ] ||
    ! git -c core.fsmonitor=false ls-files --error-unmatch -- tests-run.txt >/dev/null 2>&1; then
    fail '1: tests-run.txt must be a regular, non-link, tracked file'
fi

bytes=$(wc -c 2>/dev/null < tests-run.txt) ||
    fail '2: cannot measure tests-run.txt'
[ "$bytes" -le 1048576 ] 2>/dev/null ||
    fail '2: tests-run.txt must be at most 1048576 bytes'

# Replacing NUL with SOH preserves line starts and exact ASCII comparisons.
# It also prevents text tools from treating NUL as a record terminator.
{
    tr '\000' '\001' < tests-run.txt |
        awk '
            /^TESTS / { tests = 1 }
            { last = $0 }
            END {
                if (last != "PROBE DONE") exit 3
                if (!tests) exit 4
            }
        '
} 2>/dev/null
result=$?
case $result in
    0) printf 'ok\n' ;;
    3) fail '3: last line must be exactly PROBE DONE' ;;
    4) fail '4: tests-run.txt must contain a TESTS line' ;;
    *) fail '3: cannot check the last line of tests-run.txt' ;;
esac
