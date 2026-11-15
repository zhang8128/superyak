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

# Test the link first, before any command opens reach.txt.
if [ -L reach.txt ] || [ ! -f reach.txt ] ||
    ! git -c core.fsmonitor=false ls-files --error-unmatch -- reach.txt >/dev/null 2>&1; then
    fail '1: reach.txt must be a regular, non-link, tracked file'
fi

bytes=$(wc -c 2>/dev/null < reach.txt) ||
    fail '2: cannot measure reach.txt'
[ "$bytes" -le 65536 ] 2>/dev/null ||
    fail '2: reach.txt must be at most 65536 bytes'

# Replacing NUL with SOH preserves line starts and exact ASCII comparisons.
# It also prevents text tools from treating NUL as a record terminator.
{
    tr '\000' '\001' < reach.txt |
        awk '
            /^CAN / { can = 1 }
            /^CANNOT / { cannot = 1 }
            { last = $0 }
            END {
                if (last != "PROBE DONE") exit 3
                if (!can || !cannot) exit 4
            }
        '
} 2>/dev/null
result=$?
case $result in
    0) printf 'ok\n' ;;
    3) fail '3: last line must be exactly PROBE DONE' ;;
    4) fail '4: reach.txt must contain CAN and CANNOT lines' ;;
    *) fail '3: cannot check the last line of reach.txt' ;;
esac
