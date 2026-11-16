# v2: a route, made from many walks, offered to a turn

Serenity, 2026-11-16. A change to the design of stage 2
(`docs/superpowers/specs/2026-11-15-v2-stage-2-experiment.md`), after its pilot
(`docs/reports/2026-11-15-v2-stage-2-pilot.md`) and the repair that followed
(`docs/reports/2026-11-16-v2-tests-that-need-the-room.md`). It needs a fresh reader, like any spec.

## Why the design changes

The pilot said the experiment as designed was not affordable, and the experiment's own text says what
follows: the design changes, and a changed design gets one pilot of its own. Two things change.

- **The noise it found has had its likely cause removed.** A worker's own test run took eight minutes and
  could wait ten; it now takes under a minute. Whether that was the cause is for the new pilot to show.
- **The person whose project this is asked for the whole of his idea to be made testable,** and the part of
  it that the first design put off is the part it rests on. His idea, in his words: the paths a worker took
  to find what it needed become, with use, "a road network. One that you can A* around", so that it rides
  "your own rails" where it would walk; and many agents' paths together make a better map than one.
  The first design offered a turn other turns' walks as they were, and left "stitched routes" to a fourth
  arm that would run only if walks had already won. So the claim about the network was never going to be
  tried unless a weaker one succeeded first.

## What is asked

1. **A walk as a file,** that the room writes and anything can read.
2. **A road network made from many walks,** kept on the n-category store, that answers one question: the
   cheapest known way from a turn's start to a named file.
3. **The room offers a turn a route,** as a block of text in its prompt, and records that it did.
4. **An arm for it from the start,** and one pilot of the changed design, fixed beforehand.

## Not asked

- **Frames.** Choosing how to look at a problem, and learning which way suits which problem, is a layer
  above this one. A route can be tried without it. It also means the goal of a route here is chosen by the
  experiment's own plain ranker, and not by any judgement of what a problem is like.
- **Lighthouses across machines.** Walks from two worker programs on one or two machines are merged. Names
  that mean the same on different machines are not.
- **The notes arm.** It asked whether a commit message helps. The question now is the network. If a route
  shows a benefit, notes come back as the comparison that says whether the structure was what helped.
- **Any text of a turn.** Rule 9 stands. A walk holds paths, blobs, tools, outcomes, times and counts.

## 1. A walk as a file

`yak item walks <item> --json` prints one object for each arrived turn of the item, from the room's store:

| Field | What |
| --- | --- |
| `walk` | `1`, the format's number |
| `base` | the commit the turn's sandbox was made from |
| `item`, `attempt`, `worker` | as the room names them |
| `passed` | whether the turn's commit passed its frozen check |
| `steps` | in order: `seq`, `tool`, `ok`, `named` (each a tracked `path` and its `blob` at the base), `seen_ms`, `result_ms`, `tokens_in`, `tokens_out` |
| `changed` | the paths the turn's commit changed, and how |

A path is one the room already admitted: plain, relative, tracked at the base. Nothing else of a turn is in
the file. A ship with no room can write the same file from its own record of the files it named. Such a
walk is marked `"worker": "ship:<name>"` and is never taken for a room's: it may be used to build and try
the store, and it never enters the network an experiment's offer is made from. That network holds arrived
turns of history items and nothing else, as the first design has it.

## 2. The road network

This part is the store's, on the kernel that the ship Tardis wrote, and its owner shapes it. What the room
needs of it is fixed here; how it is kept is not.

- **A 0-cell** is a tracked path of one repository. `START` is one more, for where every turn begins.
- **A road** from `a` to `b` is there when some walk named `b` next after `a`. From `START` to the first
  file a walk named. One road for each ordered pair, however often it was walked, with how often.
- **A walk** is the composite of its roads, a 1-cell. Two turns that named the same files in the same
  order are one cell.
- **What a road costs** is 1. A path's cost is the number of roads in it. Where two paths cost the same, the
  one whose least-walked road was walked more often is the cheaper.
- **A detour** is a 2-cell from a path some walk took to a cheaper path with the same two ends, each road
  of which some walk took. It is the record that a shorter way is a rewriting of ways really gone, and not
  an invention: the kernel refuses a 2-cell whose two sides do not share their ends.
- **A route** to a file is the cheapest path from `START` to it, with the detours that lead to it from the
  walks it shortens. Asked for several files, it is their routes, in the order asked.

`ncat_store route --walks <directory> --to <path>...` prints the route as JSON: for each file asked, the
paths along its route in order, the cost, how many walks hold each road, and how many walks it shortens. A
file no walk reached has no route, and that is said, not guessed.

**The search is the plainest one.** With every road costing 1 and nothing known of how far a file is from
another, the search for the cheapest path has no estimate to steer it. It is the search the person's "A*"
names with its estimate at nothing. An estimate is a later question, and frames are where one would come
from.

**Where it runs from.** The route is run from the store's branch at a recorded commit. Putting it on the
project's main branch is not on the way to the test.

## 3. The offer

- **`yak clock run --offer <file>`** gives every turn of that clock one block of text, after the prompt's
  first lines and before the rules. The room renders the block from a route's JSON, by one fixed form: for
  each file, a line that names it, then the files on the way to it in order, then how many earlier turns
  went that way. Paths only. A path is admitted to the block by the same test that admits it to a walk.
- **Without `--offer` the prompt is byte for byte what it is today,** and the test that pins it holds.
- **The store records what a turn was given:** its arm, the order, the seed of the draw, and the SHA-256 of
  the offer's block. Not the block.
- **A walks arm is rendered by the same command** from walk files: every file each named, in order, which
  it changed, its verdict.

## 4. The arms, and the pilot

| Arm | What the turn is given |
| --- | --- |
| Nothing | Today's prompt |
| Walks | The whole walks of the nearest arrived history turns, up to three, as the first design had them |
| Route | The route to the files those same turns changed, over the network of every history walk |

- **One ranker picks the turns for both offered arms,** the first design's, unchanged: shared title words.
  So the two arms differ in one thing: whether the turn is shown three walks whole, or the one way through
  all of them.
- **History and scored items stay apart,** as the first design has it. No walk at a scored item enters the
  network.
- **Comparisons, in order:** walks against nothing and route against nothing; then route against walks, read
  only if route showed a benefit against nothing.
- **Everything else of part 3 stands:** every item under every arm, the order drawn by a seeded draw, an
  item's runs one after another, the deciding outcome, the four readings, the sizing rule.

**The pilot, once.** Three fresh items, found in order after the repair, each with a check frozen
beforehand by the other family. Five rounds with nothing offered give the spreads, and the same rule gives
`n`: the largest of the three decides, the floor is 20 and the ceiling 40. One turn at each item under each
offered arm is run as well, to show the whole path working, from walks to network to route to prompt to
record. Their history is what exists today: the 24 arrived turns of the first run and the first pilot, at
three older items. Those six turns are not scored and decide nothing. If `n` is over 40 again, that is
reported, and no third pilot follows.

## How we know it is ready to test

| What | Shown by |
| --- | --- |
| A walk file holds what the store holds, and no text | A turn's file set beside its store rows; a planted marker in a turn's output is in neither |
| The network is made of roads that were walked | Every road of a route is in some walk file named with it |
| A route is never longer than any walk it shortens | Checked over every history walk |
| A detour's two sides share their ends | The kernel's own refusal, tried with one that does not |
| The offer is paths only, and the prompt without it is unchanged | The pinned prompt test; a walk file with a path that is not plain is refused |
| What a turn was given is in its record | The arm, the order, the seed and the block's hash, for each of the six turns |
| Two machines can run it | The whole suite on the second machine, and one turn there |

## What is left to the builders

How the store keeps roads and detours; the block's exact words; the names of the new flags. The file's
fields, what a road costs, what a route is, and what a turn may be shown are fixed here.
