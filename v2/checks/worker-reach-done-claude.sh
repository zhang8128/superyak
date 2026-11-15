#!/bin/sh
# Frozen check for the probe item "what a worker's shell can read": did the worker run the probe to its end and
# commit its output? It does not judge what the probe found; the lead reads that in the commit handed in.
# Run from the root of a checkout of the commit being judged. Exits 0 and prints "ok" when all four hold:
#   1. reach.txt is at the root, a regular file and not a link, and git tracks it;
#   2. it is at most 65,536 bytes;
#   3. its last line is exactly "PROBE DONE" (blank lines after it do not pass);
#   4. it holds a line that begins "CAN " and a line that begins "CANNOT ".
set -u
fail() {
    echo "FAIL $1" >&2
    exit 1
}
f=reach.txt
if [ -L "$f" ] || [ ! -f "$f" ]; then
    fail "1: reach.txt is not a regular file at the root"
fi
git ls-files --error-unmatch -- "$f" >/dev/null 2>&1 || fail "1: git does not track reach.txt"
size=$(wc -c < "$f" | tr -d ' ')
case $size in
'' | *[!0-9]*) fail "2: the size of reach.txt could not be read" ;;
esac
[ "$size" -le 65536 ] || fail "2: reach.txt is larger than 65,536 bytes"
last=$(tail -n 1 "$f")
[ "$last" = "PROBE DONE" ] || fail "3: the last line of reach.txt is not PROBE DONE"
grep -q '^CAN ' "$f" || fail "4: no line of reach.txt begins with CAN"
grep -q '^CANNOT ' "$f" || fail "4: no line of reach.txt begins with CANNOT"
echo ok
