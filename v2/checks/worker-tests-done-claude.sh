#!/bin/sh
# Frozen check for the probe item "a plain cargo test in a worker's sandbox": did the worker run the probe to its
# end and commit what it printed? It does not judge what the tests did; the lead reads that in the commit handed in.
# Run from the root of a checkout of the commit being judged. Exits 0 and prints "ok" when all four hold:
#   1. tests-run.txt is at the root, a regular file and not a link, and git tracks it;
#   2. it is at most 1,048,576 bytes;
#   3. its last line is exactly "PROBE DONE" (blank lines after it do not pass);
#   4. it holds a line that begins "TESTS ".
set -u
# Bytes, not letters: in another locale a tool may stop at a byte that is not text.
LC_ALL=C
export LC_ALL
fail() {
    echo "FAIL $1" >&2
    exit 1
}
f=tests-run.txt
if [ -L "$f" ] || [ ! -f "$f" ]; then
    fail "1: tests-run.txt is not a regular file at the root"
fi
git ls-files --error-unmatch -- "$f" >/dev/null 2>&1 || fail "1: git does not track tests-run.txt"
size=$(wc -c < "$f" | tr -d ' ')
case $size in
'' | *[!0-9]*) fail "2: the size of tests-run.txt could not be read" ;;
esac
[ "$size" -le 1048576 ] || fail "2: tests-run.txt is larger than 1,048,576 bytes"
# A shell drops a NUL from what a command printed, and a text tool may end a line at one. Each is read as another
# byte, so that a line with a NUL in it is not taken for the line without it.
last=$(tail -n 1 "$f" | tr '\000' '\001')
[ "$last" = "PROBE DONE" ] || fail "3: the last line of tests-run.txt is not PROBE DONE"
tr '\000' '\001' < "$f" | grep -q '^TESTS ' || fail "4: no line of tests-run.txt begins with TESTS"
echo ok
