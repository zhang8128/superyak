#!/bin/sh
# One live turn that shows what a plain `cargo test` of v2 does inside a worker program's own sandbox: a new
# room, a new copy of the repository, one item whose work is to run probe.py and commit what it printed, one
# worker, one turn.
#
#   sh turn.sh <out-dir> <source> <worker> <check file> <who wrote that check, as family:name>
#
# <out-dir>     must not exist. It gets repo/, room/, item.txt, manifest.json (see ../pilot/records.py),
#               started.txt, clock.log, clock.exit, ended.txt, turns.json, how busy the machine was before and
#               after, and tests-run.txt: what the probe printed inside the worker's sandbox, taken from the
#               commit the turn handed in. That file is the evidence, not what the worker said about it.
#               The script ends with something other than 0 when the turn is not one usable observation, or
#               handed in no tests-run.txt.
# <source>      a repository whose branch v2 is at the commit to try. That commit holds the probe and its checks.
# <worker>      as the clock names one, claude:opus say.
# <check file>  worker-tests-done-claude.sh or worker-tests-done.sh, under v2/checks at that commit. The room
#               gives an item only to a worker of another family than its check's writer, so a Codex worker
#               is given the first and a Claude worker the second.
# From the environment:
#   YAK             the yak program.
#   YAK_PROBE_PATH  the PATH the clock is given: the worker's program, git, python3 and the toolchain are on it.
#   YAK_JAIL_READ   the directories the room shows its workers: the toolchain and the vendored crates.
#   YAK_VENDOR      the vendored crates' directory, which the probe is told.
#   SDKROOT         passed on when it is set (see ../reach/run.sh).
#
# The control is the same probe run by hand where nothing is hidden, from a copy of the same commit: there the
# room can run, and what differs between that and a turn's tests-run.txt is what the sandbox does.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$1
SRC=$2
WORKER=$3
CHECK=$4
BY=$5
[ ! -e "$OUT" ] || { echo "refused: $OUT exists"; exit 1; }
[ -x "${YAK:-}" ] || { echo "refused: YAK is not a program"; exit 1; }
[ -n "${YAK_PROBE_PATH:-}" ] || { echo "refused: YAK_PROBE_PATH is not set"; exit 1; }
[ -n "${YAK_JAIL_READ:-}" ] || { echo "refused: YAK_JAIL_READ is not set"; exit 1; }
[ -d "${YAK_VENDOR:-}" ] || { echo "refused: YAK_VENDOR is not a directory"; exit 1; }
case $YAK_VENDOR in
/*) ;;
*) echo "refused: YAK_VENDOR is not an absolute path"; exit 1 ;;
esac
case $YAK_VENDOR in
*[!A-Za-z0-9/._-]*) echo "refused: YAK_VENDOR holds a character a worker would have to quote"; exit 1 ;;
esac
case $CHECK in
worker-tests-done-claude.sh | worker-tests-done.sh) ;;
*) echo "refused: $CHECK is not one of the probe's two checks"; exit 1 ;;
esac
TITLE="Run \`python3 -I v2/probes/tests/probe.py $YAK_VENDOR > tests-run.txt 2>&1\` at the root (it takes minutes), then commit tests-run.txt and nothing else."
[ "${#TITLE}" -le 200 ] || { echo "refused: the item's title would be ${#TITLE} characters, and a title has 200"; exit 1; }
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd -P)
SRC=$(cd "$SRC" && pwd -P)
git clone -q --no-local --no-tags --single-branch --branch v2 "$SRC" "$OUT/repo"
git -C "$OUT/repo" remote remove origin
BASE=$(git -C "$OUT/repo" rev-parse HEAD)
for held in v2/probes/tests/probe.py "v2/checks/$CHECK"; do
    git -C "$OUT/repo" cat-file -e "$BASE:$held" 2>/dev/null || { echo "refused: $BASE holds no $held"; exit 1; }
done
# A wrong commit: an output that does not end as the probe ends.
g() { git -C "$OUT/repo" -c user.name='probe setup' -c user.email=setup@yak.invalid -c commit.gpgsign=false "$@"; }
g checkout -q --detach "$BASE"
echo "PROBE a plain cargo test of v2, in the place this is run from" > "$OUT/repo/tests-run.txt"
g add tests-run.txt
g commit -q -m "wrong: the probe did not run to its end"
WRONG=$(g rev-parse HEAD)
g update-ref refs/wrong/tests-probe "$WRONG"
g checkout -q v2
[ "$(g rev-parse HEAD)" = "$BASE" ] && [ ! -e "$OUT/repo/tests-run.txt" ] || { echo "refused: the copy is not back at its base"; exit 1; }
"$YAK" --room "$OUT/room" init
ID=$("$YAK" --room "$OUT/room" item add --title "$TITLE" --repo "$OUT/repo" --base "$BASE" \
    --check "sh v2/checks/$CHECK" --file "v2/checks/$CHECK" --wrong "$WRONG" --origin outside --by "$BY")
printf 'tests-probe %s %s\n' "$ID" "$WORKER" > "$OUT/item.txt"
date -u '+%Y-%m-%d %H:%M:%S UTC' > "$OUT/started.txt"
# The clock is given only what is named here, whatever this shell holds, and one turn.
set -- HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" SHELL="${SHELL:-/bin/sh}" LANG=en_US.UTF-8 TERM=dumb \
    PATH="$YAK_PROBE_PATH" YAK_JAIL_READ="$YAK_JAIL_READ" \
    "$YAK" --room "$OUT/room" clock run --once-through --daily-turns 1 --worker "$WORKER"
[ -z "${TMPDIR:-}" ] || set -- TMPDIR="$TMPDIR" "$@"
[ -z "${SDKROOT:-}" ] || set -- SDKROOT="$SDKROOT" "$@"
python3 -I "$HERE/../pilot/records.py" manifest "$OUT" "slot=" "kind=tests-probe" \
    "slug=tests-probe" "worker=$WORKER" "item=$ID" "base=$BASE" "wrong=$WRONG" \
    "check=sh v2/checks/$CHECK" "check_file=v2/checks/$CHECK" \
    "check_blob=$(git -C "$OUT/repo" rev-parse "$BASE:v2/checks/$CHECK")" -- "$@"
uptime > "$OUT/load-before.txt"
{
    # The clock ends with something other than 0 when its item is left open, which is no failure of this
    # script: its exit is written down either way.
    code=0
    env -i "$@" </dev/null || code=$?
    echo "$code" > "$OUT/clock.exit"
} 2>&1 | while IFS= read -r line; do
    printf '%s %s\n' "$(date -u '+%H:%M:%S')" "$line"
done > "$OUT/clock.log"
date -u '+%Y-%m-%d %H:%M:%S UTC' > "$OUT/ended.txt"
uptime > "$OUT/load-after.txt"
"$YAK" --room "$OUT/room" item turns "$ID" --json > "$OUT/turns.json"
python3 -I "$HERE/../pilot/records.py" check "$OUT"
# What the probe printed in the sandbox: from the commit the turn handed in, whether or not its check passed.
COMMIT=$(python3 -I -c 'import json, sys
turns = json.load(open(sys.argv[1]))
print(turns[0].get("commit") or "" if len(turns) == 1 else "")' "$OUT/turns.json")
if [ -n "$COMMIT" ] && git -C "$OUT/repo" cat-file -e "$COMMIT:tests-run.txt" 2>/dev/null; then
    git -C "$OUT/repo" show "$COMMIT:tests-run.txt" > "$OUT/tests-run.txt"
    echo "the turn handed in tests-run.txt at $COMMIT: $(tail -n 1 "$OUT/tests-run.txt")"
else
    echo "the turn handed in no tests-run.txt"
    exit 1
fi
