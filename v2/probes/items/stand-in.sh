#!/bin/sh
# No model: apply only the patch beside this script and hand it in as a commit.
# On a failure hand in a note, since the room retains no worker output text.
step=start
note() {
    printf '%s: %s\n' "$step" "$1" > hand-in-note.txt
    git add hand-in-note.txt || exit 1
    git -c user.name=stand-in -c user.email=stand-in@yak.invalid -c commit.gpgsign=false \
        commit -q -m 'the stand-in could not hand in' || exit 1
    exit 0
}
step=where; here=$(CDPATH= cd -- "$(dirname -- "$0")" 2>&1 && pwd) || note "$here"
step=apply; out=$(git apply --index --binary "$here/reference.patch" 2>&1) || note "$out"
step=commit; out=$(git -c user.name=stand-in -c user.email=stand-in@yak.invalid -c commit.gpgsign=false \
    commit -q -m 'the reference change' 2>&1) || note "$out"
