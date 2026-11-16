#!/usr/bin/env bash
# All of v2's tests, where the room can run: every test, those that need the room with them.
#
#   bash scripts/whole-suite.sh <log> [more words for cargo, such as --offline]
#
# A plain `cargo test` leaves out the tests that need the room (a list of processes and a jail), each with a
# line that says so, and the acceptance suite, with no line. That is for a worker's sandbox, where the room
# cannot run. This is the command that leaves nothing out, for the lead's machines and for CI:
#   - yak is built, because the acceptance suite looks for it in the build's own directory;
#   - every test of the workspace is run, the ignored ones asked for;
#   - suite_guard.py reads what was printed, and fails if a test was left out all the same or a test program
#     was not started.
# Everything printed goes to <log> as well as to the terminal, with the exit and the seconds at the end.
# It ends with cargo's own exit when the build or a test failed, and with 1 when every test passed and the
# guard found one left out.
set -euo pipefail
[ "$#" -ge 1 ] || { echo "usage: bash whole-suite.sh <log> [more words for cargo]" >&2; exit 2; }
log=$1
shift
case $log in
/*) ;;
*) log=$PWD/$log ;;
esac
cd "$(dirname "$0")/.."
: > "$log"
status=0
cargo build --workspace --bins --locked "$@" 2>&1 | tee -a "$log" || status=$?
if [ "$status" -ne 0 ]; then
    echo "whole suite: the build failed with $status after ${SECONDS}s, and no test was run" | tee -a "$log"
    exit "$status"
fi
cargo test --workspace --locked --no-fail-fast "$@" -- --include-ignored 2>&1 | tee -a "$log" || status=$?
guard=0
python3 -I scripts/suite_guard.py "$log" scripts/test-programs.txt 2>&1 | tee -a "$log" || guard=$?
if [ "$status" -eq 0 ] && [ "$guard" -ne 0 ]; then status=1; fi
echo "whole suite: exit $status after ${SECONDS}s (cargo's tests and the guard, $guard)" | tee -a "$log"
exit "$status"
