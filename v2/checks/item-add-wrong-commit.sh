#!/bin/sh
# yak item add refuses a wrong commit that is not a commit of the repository, and says which
#
# Refuse an absent 40-hex object id, a tree id, a blob id, and an unresolved
# name. Refuse an entire add with a bad value first, middle, or last among
# real commits. Every refusal must name that bad value in its sole stderr
# line, exit nonzero, print no stdout, and leave the item count unchanged.
# Controls accept a real full commit id and two or three real commits immediately
# before and after the relevant refusals, printing the added item's id.
# Adds with no --wrong are accepted before and after all refusal cases.
# Branch/tag names resolving to commits and abbreviated ids are not tested.
#
# Run at the candidate clone's root with an absolute vendor directory as $1.
# Build its yak offline and locked, using crates-io replacement by that vendor
# directory and clone-local target/CARGO_HOME. All git fixtures and the room
# live in a fresh TMPDIR child, removed on exit; no clock or check is run.

check_name=item-add-wrong-commit
set -eu
LC_ALL=C
export LC_ALL

fatal() {
    printf 'FAIL setup: %s\n' "$*"
    exit 1
}

[ "$#" -eq 1 ] || fatal 'usage: sh CHECK <absolute-vendor-dir>'
case $1 in
    /*) ;;
    *) fatal 'vendor directory must be absolute' ;;
esac
clone=$(pwd -P)
CARGO_HOME="$clone/v2/target/cargo-home"
CARGO_TARGET_DIR="$clone/v2/target"
export CARGO_HOME CARGO_TARGET_DIR
[ -n "${TMPDIR:-}" ] || fatal 'TMPDIR must name the scratch directory'
work=$(mktemp -d "$TMPDIR/$check_name.XXXXXX")
trap 'rm -rf "$work"' 0
trap 'exit 1' HUP INT TERM
# Keep build-tool temporary files inside the directory removed by the trap too.
mkdir "$work/tmp"
TMPDIR="$work/tmp"
export TMPDIR
if ! (cd "$clone/v2" && cargo build -q -p yak --offline --locked \
    --config 'source.crates-io.replace-with="vendored"' \
    --config "source.vendored.directory=\"$1\""); then
    fatal 'offline yak build failed'
fi
yak="$clone/v2/target/debug/yak"
repo="$work/repo"
room="$work/room"
mkdir "$repo"

git_fixture() {
    git -c user.name=Check -c user.email=check@example.invalid \
        -c commit.gpgsign=false -c core.hooksPath=/dev/null -C "$repo" "$@"
}

snapshot() {
    if ! "$yak" --room "$room" item list </dev/null \
        >"$work/list.json" 2>"$work/list.err"; then
        cat "$work/list.err"
        fatal 'yak item list failed'
    fi
    item_count=$(awk '/^[ \t]*"id"[ \t]*:/ { n++ } END { print n+0 }' "$work/list.json")
}

run_add() {
    add_command=$1
    shift
    "$yak" --room "$room" item add --title 'Frozen check fixture' \
        --repo "$repo" --base "$base" --check "$add_command" \
        --origin outside --by person:check "$@" </dev/null
}

fail_case() {
    failures=$((failures + 1))
    printf 'FAIL %s: expected %s; exit=%s; stdout=<%s>; stderr-lines=%s; stderr=<%s>; items=%s->%s\n' \
        "$case_name" "$expectation" "$code" "$(cat "$work/out")" \
        "$stderr_lines" "$(cat "$work/err")" "$before" "$item_count"
}

accept() {
    case_name=$1
    shift
    cases=$((cases + 1))
    snapshot
    before=$item_count
    if run_add "$@" >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
    snapshot
    stderr_lines=$(awk 'END { print NR+0 }' "$work/err")
    id=$(cat "$work/out")
    # The printed value must identify the item just added, not merely be nonempty.
    if [ "$code" -ne 0 ] || [ -z "$id" ] || [ "$item_count" -ne "$((before + 1))" ] ||
        ! awk -v id="$id" '$1 == "\"id\":" { gsub(/[",]/, "", $2); if ($2 == id) found=1 } END { exit !found }' "$work/list.json"; then
        expectation='acceptance and an added item id on stdout'
        fail_case
    fi
}

refuse() {
    case_name=$1
    named=$2
    shift 2
    cases=$((cases + 1))
    snapshot
    before=$item_count
    if run_add "$@" >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
    snapshot
    stderr_lines=$(awk 'END { print NR+0 }' "$work/err")
    good=yes
    if [ "$code" -eq 0 ] || [ -s "$work/out" ] || [ "$stderr_lines" -ne 1 ] ||
        [ "$item_count" -ne "$before" ]; then good=no; fi
    if [ -n "$named" ] && ! grep -F -e "$named" "$work/err" >/dev/null; then good=no; fi
    if [ "$good" = no ]; then
        expectation='nonzero exit, empty stdout, one stderr line, no added item'
        if [ -n "$named" ]; then expectation="$expectation, naming $named"; fi
        fail_case
    fi
}

finish() {
    if [ "$failures" -ne 0 ]; then
        printf 'FAIL %s: %s of %s cases failed\n' "$check_name" "$failures" "$cases"
        exit 1
    fi
    printf 'PASS %s: %s cases\n' "$check_name" "$cases"
}

failures=0
cases=0

git_fixture init -q -b main
printf 'fixture\n' >"$repo/answer"
git_fixture add answer
git_fixture commit -qm base
base=$(git_fixture rev-parse HEAD)
printf 'second commit\n' >"$repo/answer"
git_fixture commit -qam second
second=$(git_fixture rev-parse HEAD)
printf 'third commit\n' >"$repo/answer"
git_fixture commit -qam third
third=$(git_fixture rev-parse HEAD)
tree=$(git_fixture rev-parse "$base^{tree}")
blob=$(git_fixture rev-parse "$base:answer")
absent=1111111111111111111111111111111111111111
if git_fixture cat-file -e "$absent" 2>/dev/null; then fatal 'absent object fixture exists'; fi
unresolved=no-such-wrong-commit
if git_fixture rev-parse --verify "$unresolved" >/dev/null 2>&1; then fatal 'unresolved fixture resolves'; fi
"$yak" --room "$room" init </dev/null

accept 'before: no --wrong' false
accept 'before absent object: full commit' false --wrong "$base"
refuse 'absent 40-hex object' "$absent" false --wrong "$absent"
accept 'after absent object: full commit' false --wrong "$base"

accept 'before tree: full commit' false --wrong "$base"
refuse 'tree instead of commit' "$tree" false --wrong "$tree"
accept 'after tree: full commit' false --wrong "$base"

accept 'before blob: full commit' false --wrong "$base"
refuse 'blob instead of commit' "$blob" false --wrong "$blob"
accept 'after blob: full commit' false --wrong "$base"

accept 'before unresolved name: full commit' false --wrong "$base"
refuse 'unresolved name' "$unresolved" false --wrong "$unresolved"
accept 'after unresolved name: full commit' false --wrong "$base"

accept 'before bad first: two real commits' false --wrong "$base" --wrong "$second"
refuse 'bad first among wrong commits' "$absent" false --wrong "$absent" --wrong "$base"
accept 'after bad first: two real commits' false --wrong "$base" --wrong "$second"

accept 'before bad middle: three real commits' false --wrong "$base" --wrong "$second" --wrong "$third"
refuse 'bad middle among wrong commits' "$blob" false --wrong "$base" --wrong "$blob" --wrong "$second"
accept 'after bad middle: three real commits' false --wrong "$base" --wrong "$second" --wrong "$third"

accept 'before bad last: two real commits' false --wrong "$base" --wrong "$second"
refuse 'bad last among wrong commits' "$unresolved" false --wrong "$base" --wrong "$unresolved"
accept 'after bad last: two real commits' false --wrong "$base" --wrong "$second"
accept 'after: no --wrong' false
finish
