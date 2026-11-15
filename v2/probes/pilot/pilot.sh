#!/bin/sh
# The pilot (part 1 of the stage 2 experiment): its turns, in an order written down before the first.
#
#   sh pilot.sh <pilot-dir> <made-dir>
#   sh pilot.sh --plan          prints the plan and runs nothing
#
# <pilot-dir> must not exist. It gets plan.txt (every turn, in order, written before any is run), the two
# reports of ../block-check.sh (before the first turn and after the last), pilot.log, one directory for each
# turn, made by turn.sh and named by the turn's line in the plan, and tables.md (records.py tables), which
# is written only if every turn of the plan left one usable observation and both block checks held.
# A turn that leaves no usable observation ends the pilot there: nothing is passed over, and no turn is run
# a second time. A pilot that stopped is not taken up again: what it left is looked at with
# `records.py tables <pilot-dir> --partial`, and a new pilot starts at its first turn in a new directory.
# <made-dir> and the environment are turn.sh's. YAK_PILOT_ROUNDS, when set, is how many rounds the fifteen
# are cut to: a dress rehearsal sets 1. The pilot itself leaves it unset, and the plan says which it was.
# A file named STOP in <pilot-dir> ends the pilot before its next turn.
#
# The plan:
#   1       thrown away: the memory test's item and worker, with a first line of its own, so that it leaves
#           the bare prompt unseen.
#   2, 3    the memory test: the same item and worker, without the line.
#   4, 5    the memory test: the same, with the line.
#   6       thrown away: the other worker's item, with the line, so that that worker's first measured turn
#           is not the first its program runs in the sitting. Nothing checks that a program's memory stays
#           warm after that; how long each worker went between turns is written down.
#   7-21    the fifteen: five rounds of the three items, one of each and then round again, each with the line.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROUNDS=${YAK_PILOT_ROUNDS:-5}
case $ROUNDS in '' | *[!0-9]*) echo "refused: YAK_PILOT_ROUNDS is not a number"; exit 1 ;; esac
A="item-add-wrong-commit claude:opus"
B="item-add-title codex:gpt-6.1-sol"
C="item-add-check-freezable claude:opus"
plan() {
    echo "1 thrown-away $A --own-prompts"
    echo "2 memory-without $A"
    echo "3 memory-without $A"
    echo "4 memory-with $A --own-prompts"
    echo "5 memory-with $A --own-prompts"
    echo "6 thrown-away $B --own-prompts"
    n=6
    round=0
    while [ "$round" -lt "$ROUNDS" ]; do
        round=$((round + 1))
        for item in "$A" "$B" "$C"; do
            n=$((n + 1))
            echo "$n round-$round $item --own-prompts"
        done
    done
}
if [ "${1:-}" = --plan ]; then
    plan
    exit 0
fi
PILOT=$1
MADE=$2
[ ! -e "$PILOT" ] || { echo "refused: $PILOT exists"; exit 1; }
[ -x "${YAK:-}" ] || { echo "refused: YAK is not a program"; exit 1; }
[ -n "${YAK_PROBE_PATH:-}" ] || { echo "refused: YAK_PROBE_PATH is not set"; exit 1; }
mkdir -p "$PILOT"
PILOT=$(cd "$PILOT" && pwd -P)
plan > "$PILOT/plan.txt"
say() { printf '%s %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S')" "$1" >> "$PILOT/pilot.log"; }
say "the plan is written: $(wc -l < "$PILOT/plan.txt" | tr -d ' ') turns"
# What a worker's program would load by itself is not there, and what must not change is written down.
if ! PATH="$YAK_PROBE_PATH" sh "$HERE/../block-check.sh" "$PILOT" "$YAK" > "$PILOT/block-before.txt" 2>&1; then
    say "refused by the block check before the first turn"
    exit 1
fi
while read -r n kind slug worker flag; do
    if [ -e "$PILOT/STOP" ]; then
        say "stopped before turn $n"
        exit 1
    fi
    say "turn $n begins: $kind $slug $worker $flag"
    # $flag is one word or none.
    if ! YAK_PILOT_SLOT="$n" YAK_PILOT_KIND="$kind" sh "$HERE/turn.sh" "$PILOT/$n-$kind-$slug" "$MADE" "$slug" "$worker" $flag < /dev/null >> "$PILOT/pilot.log" 2>&1; then
        say "turn $n left no usable observation, or its script failed: the pilot ends here"
        exit 1
    fi
    say "turn $n ended: the clock's exit $(cat "$PILOT/$n-$kind-$slug/clock.exit" 2>/dev/null || echo unknown)"
done < "$PILOT/plan.txt"
if ! PATH="$YAK_PROBE_PATH" sh "$HERE/../block-check.sh" "$PILOT" "$YAK" > "$PILOT/block-after.txt" 2>&1; then
    say "the pilot's turns are done, and the block check at the end REFUSED: see block-after.txt"
    exit 1
fi
say "the pilot's turns are done, and nothing written down at its start has changed"
# The tables, only if every turn of the plan left one usable observation.
if python3 -I "$HERE/records.py" tables "$PILOT" > "$PILOT/tables.md"; then
    say "every turn of the plan is in tables.md"
else
    say "the tables are REFUSED: see tables.md for what is missing or unusable"
    exit 1
fi
