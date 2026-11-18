# A lesson receipt names where it was shown

Tardis, 2026-11-18, draft 1, for the hook's authors and a fresh reader. The hook (`agent/superyak_agent/lessons_hook.py`)
is shared work: its commits on main name Rio Grande, Serenity and Tardis. A change to what the rail measures, so it
waits for a reader before any code.

## Why

On Tardis's machine, 30 receipts carry 30 outcomes: helped 3, misled 0, unused 27 (all hands 88ff400c). The last three,
shown on 2026-11-17 at 21:55 UTC, were Rio Grande's lessons on reruns, the station's SQLite stack and a password
page's text. They were shown in Andy's day-job session, in another project, whose replies never mention them. The hook
is installed per machine (`~/.superyak/lessons-hook.installed.json`), so it fires in every Claude Code session there,
whatever its folder. So "unused" mixes two things: a lesson that could have applied and didn't help, and a lesson shown
where it couldn't apply. No receipt can tell them apart. A receipt row is `(id, created, ship_id, lesson_id, author_id,
angle)` (`lesson_receipts`, `peer/superyak_peer/lessons.py`), with no place in it. How many of the 27 were out of place
can't be counted now.

## What is asked

1. **The hook sends the place's kind with every query:** `place`, which is `"superyak"` when the event's `cwd` is inside
   a checkout of this repository and `"other"` when it isn't, or absent when the event carries no `cwd`. Read from the
   code: the hook sends `cwd` only at session start and after a failed command (`lessons_hook.py:703, 723`). A prompt's
   request carries the prompt alone, though Claude Code's hook input carries `cwd` on every event, the prompt's included. So the prompt path computes the
   kind too, within its 150 ms. The kind is sent, never a new path.
2. **The receipt keeps it:** `lesson_receipts` gains `place TEXT`, NULL for every receipt written before this change
   and for a query with no `place`.
3. **The outcomes report splits by place:** `make lesson-outcomes` prints its line once in all, as now, and once per
   place, with the NULL rows counted as "before places".

## Not asked

- Not showing lessons outside Superyak. That changes what the rail does in Andy's other work, not only what it
  measures. It is Andy's to want or not. Recording the place first lets the split say whether it matters.
- The path itself. The kind is enough to read the outcomes, and a day-job folder's name has no place in a receipt.

## How "a checkout of this repository" is told

The hook already finds the branch for a `cwd` (`branch()`). The kind is `"superyak"` when the `cwd`'s git top level
holds this repository's own marker: the hook's own `CHECKOUT` is one, and so is any worktree whose top level holds
`agent/superyak_agent/lessons_hook.py`. Anything else, a missing git or a timeout included, is `"other"` only when the
check finished; when it didn't, `place` is absent. A wrong "superyak" would hide exactly what this is for, so the check
leans to absent.

## How we know it is done

| What | Shown by | A wrong hook or peer caught |
| --- | --- | --- |
| The kind at every event | A prompt, a session start and a failed command, each from a Superyak worktree and from another git folder: `superyak` and `other`; from no folder: absent | One that sends it only at start, sends a path, or calls a folder Superyak by its name alone |
| Within its budget | The prompt path's kind check under the 150 ms the prompt has | One that delays the prompt's lessons for the kind |
| Kept on the receipt | A query with each kind writes it; one with none writes NULL; old rows stay NULL | One that writes a kind it wasn't sent |
| The split | Outcomes printed in all and per place, NULL as "before places" | One that folds the old rows into "other" |

## Decisions

1. **Record first, decide after.** The split shows whether lessons outside Superyak matter, before anyone stops them.
2. **A kind, not a path.**
3. **Absent rather than guessed** when the check doesn't finish.
