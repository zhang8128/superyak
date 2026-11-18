# A lesson receipt names where it was shown

Tardis, 2026-11-18, draft 4, fit to build: three readers (w94, w95, w96), each change made. The hook (`agent/superyak_agent/lessons_hook.py`)
and its hold (`lessons_hold.py`) are shared work: their commits on main name Rio Grande, Serenity and Tardis. A fresh
reader (w94, Sol, Serenity's team) read draft 1 and approved it with seven named changes, all made here. The last section
says where. A confirming reader (w95) found four of them made as named and three made otherwise, and named three more,
made in draft 3. It changes what the rail measures and what the hook keeps, so it takes the safety-code review path.

## Why

On Tardis's machine, 30 receipts carry 30 outcomes: helped 3, misled 0, unused 27 (all hands 88ff400c). The last three,
recorded at 21:55 UTC on 2026-11-17, were Rio Grande's lessons on reruns, the station's SQLite stack and a password
page's text. They came from Andy's day-job session, in another project, whose replies never mention them. The hook is
installed per machine (`~/.superyak/lessons-hook.installed.json`), so it fires in every Claude Code session there,
whatever its folder. A receipt row is `(id, created, ship_id, lesson_id, author_id, angle)` (`lessons.py:1784`), with no
place in it, so outcomes can't be read by where a lesson was shown.

**What this permits, and no more:** grouping receipts and outcomes by place. It doesn't redefine an outcome, which
already counts an irrelevant lesson as `unused` (`2026-11-03-lesson-outcomes-design.md`). It doesn't say why a lesson
went unused, and place isn't applicability: a shell or database lesson can help in another project, and a Superyak
session can find one beside the point.

## What is asked

1. **The events that write receipts send a place.** Those are session start, a failed command
   (`lessons_hook.py:703–726`), and the pre-command hold, for Bash and for confirmed held tools (`lessons_hold.py:165–167`;
   its entry already receives `cwd`, `hold.py:107–125`). Each sends `place`: `"superyak"`, `"other"`, or the key absent
   (below). The place comes from the current event's own `cwd` only, never from a `cwd` an earlier event left in the
   hold's record (`holds.py:125–129`): an event without one sends no place. And it goes only to the default query,
   this checkout's own peer (`default_query()`, `lessons_hook.py:134–138`). A configured `query` (`lessons_hook.py:
   379–395, 409–420`, which the hold uses too, `lessons_hold.py:122–130`) may run anything, so its locality isn't
   established, and it is sent no place. Its lessons go on as before. A prompt sends nothing new. Its path opens no store and writes no receipt (`lessons.py:632–686, 842–843`),
   and that stays so: a prompt's showings are not part of outcome coverage, before or after.
2. **The peer accepts only those values.** `read_request` (`lessons.py:524–571`) checks `place` before any early return.
   It must be exactly `"superyak"`, `"other"`, or absent; anything else is refused as a malformed request, without
   echoing it and without writing a receipt. `place` enters neither matching, nor the embedded text, nor eligibility
   (`lessons.py:728–743, 824–825`). It is stored and nothing more.
3. **The receipt keeps it.** `lesson_receipts` gains `place TEXT CHECK(place IN ('superyak','other'))`, NULL allowed.
   - **The migration:** idempotent, under the store's existing gate. On open, a store whose `lesson_receipts` lacks the
     column gains it by `ALTER TABLE … ADD COLUMN`. `CREATE TABLE IF NOT EXISTS` adds no column (`db.py:99`), and the
     fresh schema gets the column too.
   - **Every insert names its columns.** Today's writer inserts six values unnamed (`lessons.py:1576`), which a
     seventh column breaks ("table lesson_receipts has 7 columns but 6 values were supplied", the reader's probe).
   - **Old writers:** a peer process from before the change, writing to an upgraded store, would fail on that insert.
     So the change lands with its peer's restart, as any store change does, and an old peer is not run against an
     upgraded store.
   - Receipts are local records (`lessons.py:1575–1579, 1713`; `federation.py:416–437`), so no other peer migrates. A
     new hook asking an old peer loses `place`, because the old reader ignores the key, and its receipts are NULL.
4. **The outcomes report splits what can be split.** `make lesson-outcomes` keeps its line, and adds receipts, outcomes
   and coverage per place: `superyak`, `other` and "unknown place, including receipts from before this change". Verified
   repeats per 100 queries stay global, said as such. Query rows have no place and no receipt link (`lessons.py:1578,
   1787`), a query can show nothing, and its place can't be recovered from receipts. The groups are counted over the
   whole store, apart from the listing's row limit, and their totals equal the aggregate's.

## How "a checkout of this repository" is told

A marker file is not identity: any folder can plant `agent/superyak_agent/lessons_hook.py`, or link to it, and a fork
or copy carries it. So the kind is `"superyak"` only for the installed checkout the hook runs from (`CHECKOUT`) and the
worktrees git has registered for it. Their canonical roots come from that checkout's own `git worktree list
--porcelain`, never from the candidate folder. The event's `cwd` is resolved to its canonical form and matched as
inside one of those roots. When roots nest, as a worktree inside the checkout, the deepest is the one matched.
Containment isn't enough by itself, because an unrelated repository can sit inside a root. So the folders from the
`cwd` up to the matched root, the `cwd` itself included and the root excluded, are checked, at most 64 of them. A
`.git` there (a folder or a file) is only a candidate: it is a repository when git itself, asked with a bound, resolves
that folder as its own top level. Then the `cwd` is in a nested repository, and its kind is `"other"`. A `.git` git
can't resolve, can't read, or doesn't answer for in time is no answer, and gives no place. Everything else
outside the roots is `"other"` when the check finished: an independent clone, a fork, a copy, a folder of the same
name. The key is absent when the check didn't finish, or its answer was ambiguous: a missing git, an inaccessible
`cwd`, more than 64 folders, or roots that can't be read. Failed discovery never becomes `"other"`.

The roots are read with a bound. They may be cached in memory for one hook run, and are never written to disk. A
wrong `superyak` hides what this is for, so the check leans to absent. The kind confers nothing: no authority, no
routing, no trust.

## What it keeps, and who can read it

**No path is newly sent or kept.** Session start and failure already send `cwd` to the local query, which uses it in the
embedded context (`lessons.py:824–825`), and the hold's record already keeps `cwd` locally (`holds.py:125–129`). This
adds a kind, not a path. What it does add is a fact: that a ship's session outside Superyak was shown a given lesson at
a given time. That stays local. The query is this machine's own peer, not the station (`lessons_hook.py:134–138,
409–420, 447–461`). Receipts are listed to anyone who can read the peer's data folder (`lessons.py:1594–1598`, folder
0700, database 0600, `db.py:82–97`), and room membership reaches none of it. That audience is kept, and nothing of
`place` is federated.

## The budget

The prompt path's 150 ms is untouched, since a prompt sends no place. Session start and failure have 2 s
(`lessons_hook.py:38`), and the hold has its own. The kind is computed within each, and its git calls get a share of
what is left, not the helper's 500 ms (`lessons_hook.py:480–487`). When classifying runs out of time, the place is
absent and the lessons still show: classifying never silences a lesson.

## How we know it is done

| What | Shown by | A wrong change caught |
| --- | --- | --- |
| The events that write receipts send a place | Start, failure and a Bash hold, from the installed checkout, a registered worktree and another git folder: `superyak`, `superyak`, `other`; with no `cwd`: absent | One that leaves the hold out, sends a path, or sends at a prompt |
| A prompt is unchanged | A prompt opens no store and writes no receipt, before and after | One that makes a prompt write |
| Identity by registration | A planted marker file, a symlinked one, a copy, a fork and a same-name folder are each `other`; an unrelated repository nested inside the checkout and inside a registered worktree is `other`; an ordinary subfolder of either is `superyak`; a worktree inside another root matches the deepest; failed or ambiguous discovery is absent; a subfolder with a regular `.git` file of invalid contents, or one that can't be read, is absent, not `other` | One that trusts a file in the candidate, takes containment alone, calls a failure `other`, or takes any `.git` for a repository |
| A place reaches its receipt | Real request-to-store round trips for `superyak`, `other` and absent, from start, failure, a Bash hold and a confirmed held tool, each read back from `lesson_receipts`, then outcomes recorded and grouped, the groups summing to the aggregate; an old hook on a new peer writes NULL | One whose insert names its columns but drops `place`, so every row is NULL |
| Only to the default query | With a configured `query`, no `place` is sent and its lessons still show; a hold event without a `cwd` sends no place though the hold's record holds an earlier one | One that sends the fact to an arbitrary command, or reuses a stale `cwd` |
| The peer refuses other values | `place` of `"Superyak"`, `"x"`, a number, a path: refused, not echoed, no receipt; absent: accepted | One that stores what it was sent |
| No new path kept | The no-write checks (`agent/tests/test_lessons_hook_nowrite.py`) extended: no path or roots cached to disk, and no additional path disclosed on stdout or stderr, child processes included. A lesson's output, its receipt line among it, is intended (`lessons_hook.py:260–279, 522–524`) | One that caches the worktree list on disk, or prints a root |
| The budget | A control lesson still shows when classifying times out, with the place absent, inside the event's deadline; missing git, an inaccessible `cwd` and a finished non-repository answer told apart | One whose classifying uses the budget and silences the lesson |
| The migration | A populated store opened twice: the column added once, old rows NULL, receipt and outcome links kept; a fresh store has it; every insert names columns | One that loses rows, breaks the six-value insert, or adds the column twice |
| The split | Receipts, outcomes and coverage per place, apart from the row limit, summing to the aggregate; repeats per 100 queries said global; NULL called "unknown place, including receipts from before this change" | One that splits query rates, calls NULL "before places", or counts only the shown rows |

## Not asked

- Not showing lessons outside Superyak. That changes what the rail does in Andy's other work, not what it measures,
  so it is Andy's to want. This lets the split say whether it matters.
- A place for a query, or for a repeat. That needs a scheme of its own.
- Classifying independent clones and forks. They are `other` until their treatment is specified.

## Decisions

1. **Record first, decide after.**
2. **A kind, not a path,** checked by the peer and stored as that alone.
3. **Identity by the installed checkout's registered worktrees,** never by a file in the candidate.
4. **Absent rather than guessed,** and a lesson is never withheld for want of a kind.

## The reader's named changes, and where each is made

| Named change (w94 on 2cb318be) | Where |
| --- | --- |
| 1. The live store's migration and the old writer | What is asked, 3 |
| 2. Split only what can be split | What is asked, 4 |
| 3. A marker file is not identity | "How a checkout is told" |
| 4. The privacy boundary, enforced and said | What is asked, 2; "What it keeps" |
| 5. The hold covered; prompts stay receipt-free | What is asked, 1 |
| 6. NULL is unknown, and place is not applicability | Why; What is asked, 4 |
| 7. A budget check that catches a lost lesson | "The budget"; the table |

| Named change (w95 on 7364849c) | Where |
| --- | --- |
| Identity: containment admitted a nested unrelated repository | "How a checkout is told"; the table |
| Privacy: a configured query may not be local | What is asked, 1 |
| Acceptance: a place must be read back from its receipt; the current event's `cwd` only; "no additional path" on stdout | What is asked, 1; the table |

| Named change (w96 on 8646313d) | Where |
| --- | --- |
| A `.git` is a candidate; only one git resolves as its own top level is a repository, and an invalid or unreadable one gives no place | "How a checkout is told"; the table |

For the builder's reader (w95): trusted git discovery and environment overrides, canonical and quoted worktree paths,
the current event's `cwd`, and a timeout that leaves time to query, save and render. Roots stay transient, and never
enter a request, a stored state or a diagnostic.
