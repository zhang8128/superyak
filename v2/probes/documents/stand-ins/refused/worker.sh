#!/bin/sh
# A script worker (script:<path to this file>). Run by the room in the clone's top, it reads its prompt, appends
# the same comment line as the codex stand-in to a source file, commits it itself, then leaves the same directory
# named .git in a new subfolder, and exits 0. See README.md.
cat > /dev/null
file=
for candidate in peer/superyak_peer/*.py; do
    if [ -f "$candidate" ]; then
        file=$candidate
        break
    fi
done
if [ -z "$file" ]; then
    printf '%s\n' 'stand-in: no file under peer/superyak_peer/ to change' >&2
    exit 1
fi
printf '%s\n' '# A line a stand-in added, to be handed in.' >> "$file"
git add -- "$file" || exit 1
git -c user.name=stand-in -c user.email=stand-in@yak.invalid -c commit.gpgsign=false \
    commit -q -m 'stand-in: one comment line' || exit 1
mkdir -p scratch-repository/.git
exit 0
