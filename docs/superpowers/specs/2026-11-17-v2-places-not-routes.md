# v2: places, not routes (store "4")

Tardis, 2026-11-17, draft 4, for a fresh reader. The rehearsal ran on 11-17 (19:42 to 20:25 UTC), clean. A change to the store's side of
`2026-11-16-v2-walks-into-routes.md` ("the store's spec", revision 7, store `"3"`, approved at 6c861121). The room's
half is Serenity's, in a revision of `2026-11-16-v2-a-route-offered.md`. Each side gets its own read, and both land in
step, as store "3" did. The rehearsal runs store "3" at 45be5dd0, frozen by hash, and nothing here touches it.

## Why

The store's premise was that an earlier agent's way helps a later one. Two counts say it doesn't: the places do, and
the way between them adds nothing.

- **Serenity's** (all hands 66d18493): on 43 of the team's own workers' walks, a reading list ordered by the roads
  earlier workers took held no more of what a later worker found than one ordered by how many went to each file: 28,
  40 and 50% in the first 5, 10 and 16, either way. Its road model was one and two steps.
- **Tardis's** (all hands 0901d7dd), with this store at 6c861121, the measure posted before the run (fd38a8b8). On 49
  workers' first readings (Serenity's `workers-ordered-reads.json`, sha256 30f6b0f9…2d07), each worker's history was
  the earlier workers, built as a ship's store. The goals were the brief's files, and the target was what it read
  beyond its brief (a median of 8 files). Recall, with every path under `team/teams/` left out (25 entries that are
  the team's own plan files, not the repository's, which the export had folded under `team/`; all hands dcb78cd1):

  | History | n | @5 route / places | @10 | @16 |
  | --- | --- | --- | --- | --- |
  | every earlier worker | 48 | 0.149 / 0.163 | 0.240 / 0.246 | 0.320 / 0.325 |
  | the same area (a shared brief file) | 43 | 0.280 / 0.284 | 0.391 / 0.413 | 0.513 / 0.511 |

  Route better, worse and same: at @5, 6/8/34 and 6/7/30; at @10, 4/7/37 and 4/10/29. A route adds a median of 2
  files beyond the brief; the rest of either list is the same ranked places. The first run, with those 25 paths in
  (0901d7dd), read 1 to 2 points lower on both lists and said the same. On the second pilot's 16 walks the two
  lists could not be told apart (22 files in all).

- **What moves recall is the history, not the order:** the area's history about doubles what either list finds.
  Nothing chooses it today. The room's rule (`goals` in `v2/crates/yak/src/history.rs`, `title-words-1`) picks at most
  three taught turns by title words and offers the files they changed as goals; the store counts every walk in its
  list (Serenity read the code, all hands 13d7ac07; draft 1 said otherwise).
- **Serenity's count of ways to choose it** (13d7ac07), places only, on the 32 workers whose briefs have a title
  line, at 5 / 10 / 16: all earlier 0.17 / 0.24 / 0.35; the last three 0.18 / 0.26 / 0.37; nearest three by title
  words 0.24 / 0.33 / 0.40; nearest three by shared brief files 0.33 / 0.41 / 0.46. Its limits: three in four of the
  nearest by shared files are among the five workers just before, so on these logs "the same area" is mostly the same
  job a round earlier, and cannot say whether area helps fresh work; and an item has no brief, only its title and its
  tests.

- **Boilerplate leads a plain list** (Serenity, after the rehearsal, all hands ae8df79c): there the route was start,
  `README.md` (walked by 8), `.yak-check/check.py`, `imprints.py`, and every turn reads those at its start. Measured on
  the 49 (draft 4, the same script): a path named by more than half the history is "common", a median of 2 files with
  every earlier worker and 7 with the area. With the common files left out, recall of the whole target falls (the
  area's @5 0.284 to 0.141), since workers do open them; recall of what a worker read beyond the common files, which
  is what an offer can add, rises:

  | History | @5 places / without common | @10 | @16 |
  | --- | --- | --- | --- |
  | every earlier worker (48) | 0.119 / 0.159 | 0.198 / 0.232 | 0.284 / 0.307 |
  | the same area (39 with a target beyond them) | 0.094 / 0.203 | 0.230 / 0.294 | 0.356 / 0.412 |

**What this does not show.** "No better", not "worse": 4 against 10 is no test at this n. The 49 are the team's own
logs, not in the repository, so a reader can check the arithmetic and not the source. A walk there is first readings
only, so a road is "read next for the first time". One repository; readers and builders, not item turns. Nothing here
says a list of places saves a reader time: it says which files a later reader went on to open.

## What is asked

1. **Ranked places in the answer.** For a question, after the goals' routes, `places`: the files the store's taught
   turns named, ranked by how many distinct taught turns named each, the question's goals left out.
2. **The question may say which taught turns count:** `among`, a list of attempts. The room chooses the area; the
   store counts within it. Places are counts, not cells, so one store answers any area, and no store is built per
   area.
3. **Counts with them,** so the room can say how many earlier turns went to each place.
4. **The measure kept with the spec:** the comparison's two scripts, so a reader can run them, and so can anyone with
   walks of their own.

## Not asked

- Choosing the area. The store counts within the turns a question names; which earlier work counts as the same area,
  for an item that has only a title and tests, is the room's, in its own revision, measured before it is picked.
- Dropping routes. They stay in the answer, as store "3" has them, for the experiment's arms and for a reader. The
  offer is the room's to make from `places`.
- Conditioning places on a goal (files named by turns that also named it). Not built. Serenity measured its nearest
  kin since (all hands 119973f2, no turn): on the item list's 64 multi-file changes, given one file of a change, the
  files earlier commits changed together with it named 0.15 / 0.26 / 0.28 of the change's other files in their first
  1 / 3 / 5; the files earlier commits changed most, whatever they went with, named 0.10 / 0.29 / 0.38. A plain count
  of places again, by a fourth instrument. The draft waits unread until something would use it (aa181cc6).

## 1. The answer, store "4"

Everything in store "3"'s answer stays, byte for byte, but `store` is `"4"`. Beside `answers`, a top-level `places`:
an array of `{path, turns}`, where `turns` is the number of distinct taught turns whose walk named `path` at any step.
Counted over the taught turns the question's `among` names, or over every taught turn when it is absent. A path named
by more than half the counted turns is common: it is left out of `places` and listed in `common`, the same objects in
the same order, at most 16, so the room can still say that every turn reads `README.md` without spending the offer on
it. Paths under `.yak-check/` are the room's check, not the repository's, and are left out of both. `places` is sorted
by `turns` falling, then `path` in byte order. It leaves out every goal the question asks, and holds at
most `PLACES_KEPT` = 16, a constant of store "4". Beside it, `places_more`: how many other named paths there are, a
whole number, always present, 0 when none was left out. When `N` is 0, `places` is `[]` and `places_more` is 0.

**The question.** `among` is optional. When present it is a non-empty array of distinct attempts, sorted by bytes, each
a taught turn of this store; anything else (an empty list, an attempt not in the store, an untaught one, a repeat, an
unsorted list) is refused as a question that is not the store's, never answered as fewer. An empty `among` is refused,
not read as absent: "all" is asked for only by leaving `among` out, on purpose, and a room whose rule chooses no one
offers nothing rather than asking (Serenity, all hands feab6e2d). Its
attempts are echoed in the answer as `among`, or `null` when absent, so the answer says which history it counted.

**Counted when asked.** Each taught turn's set of named paths is read from its stored walk, as routes' visits already
are, and counted over the turns in `among`. A query sorts and cuts, and makes no cell: places are counts, not cells.
The check needs nothing new, since the counts come from the walks it already binds.

## 2. The measure, kept

`2026-11-17-v2-places-not-routes-measure/` holds `compare.py` (room walks: the other items' taught turns as history)
and `compare_workers.py` (first readings: earlier workers as a ship's store; every earlier one, and the same area),
each with the measure in its docstring as posted before the run. They call the store, so they measure the store as it
is. Their inputs are not in the repository.

## 3. How we know it is done

| What | Shown by | A wrong store caught |
| --- | --- | --- |
| Places are counted by turns | Three taught turns, one naming `a` twice in different steps: `a` has `turns` 1 from it | One that counts steps or visits |
| Ranked and cut | Twenty named paths at distinct counts and a tie at the edge: 16 kept by count then bytes, `places_more` 4 | One that keeps by name, the wrong side of a tie, or not 16 |
| Goals left out | A goal that is also the most named path is not in `places` | One that offers a turn its own goal |
| Common apart | Of four counted turns, a path named by three is in `common`, one named by two (half, not more) is in `places`; `.yak-check/check.py` is in neither | One that offers boilerplate first, counts half as more, or offers the room's check |
| Only taught turns | An untaught walk's paths count nothing | One that counts what the measure doesn't teach |
| Among | Two areas of one store give their own counts; `among` absent counts all; an empty list, an unknown, untaught, repeated or unsorted attempt is refused; the answer echoes `among` | One that answers an unknown attempt as fewer turns, or hides which turns it counted |
| Checked | A tampered walk fails the check, as in store "3" | One that serves a count its walks don't make |
| Store "3" unchanged inside | The fixture's `answers` byte for byte, with `store` "4" and the new keys | One that moves a route |

## Decisions

1. **Places beside routes, not in place of them,** until the room's experiment drops the route arm.
2. **Counted by distinct taught turns,** the measure the comparison used, and when asked, over the turns `among`
   names, so the area is the room's choice and one store serves every area.
3. **16 kept and the rest counted,** as detours are, so the answer's size doesn't grow with the history.
4. **Common files apart, not dropped.** More than half, as the room's title rule leaves out words; measured to add what
   an offer is for, and kept in the answer so nothing a turn will read anyway is hidden from the room.
