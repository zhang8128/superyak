# v2: walks into roads, and a route back

Tardis, 2026-11-16, revision 7. The store's side of `docs/superpowers/specs/2026-11-16-v2-a-route-offered.md`
("the room's spec" below, at 487f44bb), which fixes what the room writes, the list's form, and what the room
needs back (its sections 1, 2, 3 and 8). This spec says how a walk becomes cells, which walks may teach, what a
road costs, what a route and a detour are, how the store is built and checked, and what the answer holds. It
builds on the n-category store (`2026-11-07-ncat-store.md`) and its kernel (`2026-11-07-ncat-kernel.md`), and
states the detour rule that spec left to "stage 4".

A fresh reader of the other family (w45) approved revision 1 with seven named changes, and confirmed revision 2
with one more. All eight are made here; the last section says where. Revision 7 is store `"3"`: a goal keeps its
16 cheapest detours and counts the rest (section 7), because a goal's detours grow with the history (section 9).

## What is asked

1. **Read the room's walk files,** each checked against the list that says which turns may teach.
2. **Keep their roads, routes and detours as cells,** on the kernel, in a file that is derived, rebuilt whole,
   and read only once built.
3. **Answer a route,** for each file the room asks for, in the order asked, with the same bytes on any machine.
4. **Name a turn for every road and every detour,** so that a route is shown to be stitched from ways turns
   really went.

## Not asked

- **An estimate.** The search is the cheapest way with no estimate of the distance left.
- **A tour.** A route to each goal on its own, in the order asked. Nothing joins two goals.
- **Names across machines.** A path means a path in one repository. A store holds one repository.
- **Recall.** Nothing in Engram's recall reads this. It answers the room, and nothing else.
- **Text.** The store reads paths, blob hashes, ids, counts and times. The walk file has no field that could
  carry a message, prompt, command or output.

## 1. One rule for a plain path

The room's, exactly (`v2/crates/room/src/walk.rs`, `plain_path`): 1 to 512 bytes; each byte an ASCII letter or
digit, or one of `_ . / -`; not starting with `/`; and no part between slashes that is empty, `.` or `..`.
It is applied to every named path, every changed path and every goal. One rule, so that the store never answers
with a path the room would refuse to render. Its version is 1, and the answer names it.

## 2. The walk file

JSON Lines: one walk on each line, as the room writes it (the room's spec, section 1). Under a list, a walk
file holds one walk and no more. Every field is required; a part the room did not record is `null`, never
left out and never 0.

| Field | Type | What |
| --- | --- | --- |
| `v` | 1 | this format's number |
| `source` | `"room"` or `"ship"` | a turn of the room, or a ship's own record of files it named |
| `repo` | 40 or 64 lowercase hex | the repository's id: of its root commits that the turn's base reaches, the first in byte order (the room's spec, section 3) |
| `base` | 40 or 64 lowercase hex | the commit the turn's sandbox was made from |
| `item`, `attempt` | the room's ids | an attempt names a turn, once, everywhere |
| `family` | `"claude"`, `"codex"` or `"script"` | the room's families; never a worker's own name |
| `verdict` | `"passed"`, `"failed"` or `null` | whether the turn's commit passed its frozen check; `null` when the check could not run |
| `standing` | `"passed_verified"`, `"passed_unverified"`, `"failed"` or `"unjudged"` | how the room classed the turn when it wrote the file; a ship's walk is `"unjudged"`, and only a ship's |
| `steps` | list | in order of `seq` |
| `changed` | list of `[path, "added" \| "changed" \| "removed"]` | the paths the turn's commit changed, in the order recorded |

A step is an object: `seq` (a non-negative integer, each greater than the last; the room numbers a turn's steps
from 0), `tool` (one of `read`, `edit`, `write`, `search`, `shell`, `other`: the room's), `ok` (true or
false), `named` (a list of `[path, blob]` in the order named, possibly empty), `seen_ms`, `result_ms`,
`tokens_in`, `tokens_out` (each a non-negative integer or `null`). A step of an older store, which had one
target and no list, is written with that one file as its list.

**Refused, the whole file with it:** a field missing or unknown, or of another type; a word outside its
vocabulary; a `seq` that does not increase; a path the rule refuses; a blob that is not 40 or 64 lowercase hex;
a line whose bytes before its newline are more than 1 MiB (the newline does not count, so a line of
exactly 1 MiB is read); bytes that are not UTF-8. The refusal names the file, the line and the field by
its place in this schema (a step by its index), and never repeats a value or an unknown key. Nothing is dropped
silently: a failed step and a failed turn are read and kept as what they are.

**Bounds, each refused by name before the work it bounds:** a walk file over 64 MiB, before it is read; a list over
4 MiB; a question over 1 MiB; JSON nested deeper than 8 (a walk needs 5); more than 10,000 walks in a store or turns
on a list; more than 1,000,000 named files over all of a store's steps, before any network or cell is made; and a
string holding a lone surrogate, which no UTF-8 file can hold.

## 3. Which walks teach

**An experiment's store is built from a list,** whose form is the room's (its section 3): one JSON object, keys
sorted, no spaces, UTF-8, with `v` 1, `repo`, `measure` (`name`, `version`), and `turns` sorted by `attempt`,
each with `attempt`, `item`, `base`, `standing` and `sha256`. The store reads the list's bytes as given, keeps
them, and takes the list's id as their SHA-256.

**The build refuses, before any cell is made,** each by name: a list that is not in that form, or not sorted, or names
an attempt twice, or one walk file's digest for two turns; a measure this store does not have (section 5); a file given
whose bytes hash to no entry, or to an entry already given; a listed entry with no file given; a file holding more than
one walk; a walk whose `attempt`, `item`, `base` or `standing` differ from its entry's, whose `repo` differs from the
list's, or whose `source` is not `"room"`. So every listed turn is in the store once, and nothing else is: a missing
turn would change `N`, and with it every price.

**What the store can and cannot check.** It checks a frozen snapshot: the files it is given against the list
it is given. If a listed turn's standing changes in the room after the list is made, an export written again
fails its hash, and is refused here; the old export, given again, still matches, and is caught by the room's
own check against its store before any offer (the room's spec, section 3). That check is the room's, and this
store does not claim it.

**A ship's walks are kept apart.** They build only a store with no list, under the ship measure of section 5,
whose answers say `"list": null` and `"for_experiment": false`. An experiment's build refuses a ship's walk
wherever it is in a file. No answer of a ship's store can carry an experiment's list or measure.

## 4. The cells

All of it lives on the kernel, in one category per store, with the store's budget (128 MiB) and the kernel's
default work limit.

- **0-cells.** One 0-generator for the start, where every turn begins, and one for each path a taught walk
  visited. The start is not a path: no path can name it, and the answer writes it as `null`.
- **A visit.** A taught walk's visits are its steps' `named` lists, joined in step order and the order named,
  with a repeat of the visit just before dropped. A file read and then edited is one visit; a file left and
  come back to is two. A walk that named nothing has no visits, and still teaches: it counts in `N`.
- **A road, a 1-generator.** The start to a walk's first visit, and each visit to the next. One generator for
  each ordered pair any taught walk walked. There is no road from a file to itself.
- **A turn's way to a file, a 1-cell.** The composite of its roads from the start up to the file's first visit,
  in order, each road as often as it was walked there. It may pass a file twice; the kernel keeps each
  occurrence as its own element, so it is still a cell.
- **A route, a 1-cell,** the composite of the roads section 6 chooses.
- **A detour, a 2-generator,** from a turn's way to the route to the same file (section 7).

**Counts.** For each road, `k`: the taught turns that walked it, each turn once however often. `N`: the taught
turns on the list, whether or not they named anything. Two turns that walked alike are one cell and two turns.

**Paths only untaught walks named** are kept in a table, not as cells, so that section 6 can tell a file no
walk named from one only an untaught walk named.

## 5. The measures

**`share`, version 1,** for an experiment's store. It lets `"passed_verified"` teach, and nothing else.

- **A road's share** is `k / N`. **Its cost** is `−ln(k / N)`: a road every taught turn walked costs nothing,
  and one walked by a single turn of many costs the most.
- **A way's cost** is the sum of its roads' costs, a road walked twice counted twice, so it is `−ln` of the
  product of its roads' shares.
- **Compared exactly.** One way is cheaper than another when the product of its shares is strictly larger,
  compared as exact fractions, never as floating-point sums.

**`ship-share`, version 1,** for a ship's store only. It lets `"unjudged"` walks of `source` `"ship"` teach,
by the same formula over that population. It is observational: a way to try the store on real walks, never an
experiment's measure.

**What a measure is not** (w45's C1). `k / N` is an unconditional share of turns, not a probability of going
from one file to the next, and a product of shares is not the probability that a turn walked a whole route.
So:

- **Turns that named nothing move the prices.** With two walks of start, a, b, target and one of start, b, x,
  the three-road way wins (8/27 against 2/9); add one taught turn that named nothing and the two tie at 1/8;
  add two and the two-road way wins (2/25 against 8/125). A worker that names little changes every route.
- **A worker's order of naming lays roads.** A step that named three files makes two roads between them, in
  the order named, though they may have been read at once. A worker can lay adjacencies by naming, and several
  verified turns can raise a road's support. Passing a frozen check admits a turn; it does not make its order
  necessary, causal, useful or candid.
- **Costs move every way as the history grows.** A cost can stay at nothing, stay the same, rise or fall as `k`
  and `N` change. An answer is of one list, named by its hash, and is never compared with another list's.

## 6. A route

**The question,** one JSON object: `v` 1; `repo`; `list` (the list's id, or `null` for a ship's store);
`measure` (`name`, `version`); and `goals`, a list of paths, in the room's order.

**Refused as a whole, with no answer and a named reason,** distinct from any no-route answer: a question not in
that form; a goal the path rule refuses; a `repo`, `list` or `measure` that is not the store's. A consumer that
runs an experiment also requires `for_experiment: true`, and the list and measure it pinned.

**The answer** (section 8 gives its bytes): `v` 1; `store`, this store's version, `"3"` for this revision and raised
whenever an answer's bytes could change for the same walks, list and question; `kernel`, the digest of the kernel
source that built the store's cells (the first 16 hex digits of the SHA-256 of the source the kernel's loader builds
from, an installed wheel's shared copy included), recorded at build time; `repo`;
`list`; `for_experiment`; `measure` (`name`,
`version`, `teaches`, the standings it lets teach, sorted); `path_rule` 1; `taught`, which is `N`; and
`answers`, one for each goal, in the order asked, a goal asked twice answered twice.

**Each goal, in this order of precedence:**

1. `{"goal", "none": "no_history"}` when `N` is 0, whatever the goal.
2. `{"goal", "none": "never_named"}` when no walk in the store named it, as with a file a turn added.
3. `{"goal", "none": "not_taught"}` when only untaught walks named it.
4. `{"goal", "none": "refused", "code", "reason"}` when the build recorded a kernel refusal for this goal's
   route or a way to it (section 7), with the kernel's code and its words.
5. Otherwise a route: `{"goal", "route"}`, where `route` has `paths` (the files after the start, in order,
   ending at the goal); `roads`, in route order, each with `from` (`null` for the start), `to`, `turns` (its
   `k`) and `witness` (the `attempt` of a taught turn that walked it: the first in byte order); `cost`;
   `roads_n`; `blobs`, an object from each path on the route to a sorted array of the blob hashes taught steps named
   it at, none twice (every step's, not only each visit's first); `detours`; and `detours_more` (both section 7).

A taught walk that visited the goal always gives a way to it, so a goal past the first three has a route or a
recorded refusal.

**The cheapest way.** Of all ways from the start to the goal along roads, with no file twice, the one whose
cost is least. Of ways that cost the same, the one whose list of paths is first in byte order, a shorter list
first where one begins the other. A road can cost nothing, so cycles of no cost exist; the rule is over simple
ways, and a search that stops at the first way found, or settles a file by cost alone, is not this rule. The
builder's search is checked against every simple way.

## 7. Detours, built with the store

**When.** Every route and detour is made while the store is built, never while it answers. For each path a
taught walk visited, in byte order: its route; then, for each taught turn that visited it, in byte order of
`attempt`, that turn's way to its first visit. A way that costs strictly more than the route is dearer. Of a
goal's dearer ways, the 16 cheapest are kept, compared exactly, a tie at the edge going to the earlier `attempt` in
byte order; each kept way makes a detour, a 2-generator from the way to the route, and the rest are only counted. A
query reads a finished file and makes no cell.

**The fixed order of cells,** so that every key is the same on every machine: the start; the paths in byte
order; the roads in byte order of (`from`, `to`), the start before any path; then, path by path as above, its
route, then each kept turn's way and detour, in byte order of `attempt`. Two generators with the same boundaries
are two cells, which is why the order is fixed.

**A detour in the answer** is one flat object, `{attempt, item, family, visit, seq, paths, cost, roads_n}`: the
turn, how far along its visits the goal first came (from 1), that step's `seq`, and its way's paths, cost and
number of roads. Detours are sorted by `attempt`. A way that costs the same or less is not a detour, and is not named.
`detours_more` is the number of dearer ways not kept: always present beside `detours`, a whole number, 0 when
none was left out. So `detours` holds at most 16, `detours_more` is more than 0 only when it holds 16, and the
number of taught turns that went a dearer way is their sum. Which 16 are kept changes which detours are shown,
never their order.

**Refused, never dropped.** The inherited store drops a refused session and keeps the rest; this one does not.
If the kernel refuses a goal's route, a way to it, or a detour, that goal answers `refused` with the kernel's
code, and the refusal is recorded in the file. If it refuses a 0-generator or a road, the build stops, the old
file stays, and the build says so: it is never served as the new list's.

**The check.** The store's check rebuilds every cell through the kernel in the fixed order and compares keys,
as the inherited store does, and then checks what a key cannot: each detour's source is its turn's way to its
goal's first visit, recomputed from the walk; its target is the goal's route, recomputed; its `visit` and
`seq` are the walk's; every road of both sides was walked by a taught turn; and the way costs strictly more,
exactly. Which detours are kept, and each goal's `detours_more`, are recomputed and compared too, as are the counts,
witnesses and refusals. A right key with a wrong witness
is damage.

**What the check binds besides the cells.** The store keeps the list's own bytes. Its check hashes them to the list
it names and admits the stored walks against them again, compares every walk row (its attempt, item, family, base,
standing and whether it teaches) with the walk it holds, and holds every walk to the store's repository. Opening a
store refuses a header out of its form: an unknown or missing key, a kernel digest that is not 16 lowercase hex, a
measure, list and flag that disagree (an experiment's is `share`, a list and `true`; a ship's is `ship-share`,
`null` and `false`), and a file built by another store version, which is to be built again.

**What a detour shows, and no more.** The kernel checks that its two sides start and end at the same 0-cells,
and keeps it in the category's structure. That the way was walked, that the route is cheaper and that it is
the cheapest are the store's checks. None of it shows that the stitched way was walked whole, that it is a
better way to do the work, or that it beats a table that made the same offer.

## 8. The answer's bytes

- **Canonical JSON:** keys sorted, `,` and `:` with no spaces, ASCII with `\u` escapes, integers as JSON
  integers, one newline at the end, nothing else. Every list's order is fixed above; none follows the order
  files were read in.
- **A cost** is an object: `num` and `den`, the product of shares in lowest terms, each the whole number's decimal
  digits, with no sign and no leading zeros (they can outgrow any fixed-width integer, and are written and read
  exactly, with no ceiling: Python's `str(int)` stops at 4,300 digits); and `nats`, for reading.
- **`nats`** is worked in a fresh `decimal.Context(prec=34, rounding=ROUND_HALF_EVEN)`: `x = Decimal(num) /
  Decimal(den)`, then `−x.ln()`, then quantized to 9 places with `ROUND_HALF_EVEN`, and written in fixed point
  with exactly 9 decimals (`format(q, 'f')`, so nothing is `0E-9`), with no sign when it is zero. It is a
  reproducible approximation for reading, not a certified rounding of the real logarithm.
  The fraction decides.
- **The fixture is normative.** `2026-11-16-v2-walks-into-routes-fixture/` holds three walk files, `list.json`,
  `question.json` and `answer.json`, worked by hand from this spec's rules and not by the store. Given the three walks
  and the list, the store answers the question with exactly `answer.json`'s bytes, and the room's renderer reads
  `answer.json`. Its route to `target.txt` is `b.txt`, `target.txt` at 2/9, stitched: the first road is witnessed by
  `attempt-2`, the second, walked by two turns, by `attempt-1`. Both other ways are detours at 2/27. `b.txt` was seen at
  two blobs from two bases, and `added.txt` is `never_named`. Its `detours_more` is 0. Its `store` is `"3"`, and its `kernel` is the digest of
  the kernel source at v2 487f44bb; a store built from another kernel answers with that kernel's digest, and is byte for
  byte the same otherwise.

## 9. What it doesn't do, and what it accepts

- **No filling in.** A step with no named file adds no visit. The room's spec measures how little the first
  pilot named (103 of 244 steps).
- **The blob is evidence, not identity.** Routing is by path. A file whose contents changed between two turns'
  bases is one 0-cell; `blobs` says it was seen at two versions.
- **Size.** Nearly every taught turn that reaches a goal goes a dearer way, so revision 6's detours grew with the
  history: on made histories of 6 to 12 files a turn from 190 (the second pilot read 6 to 12), the 5 most-reached
  goals took 80 KB at 100 taught turns, 246 KB at 300 and 834 KB at 1,000, one goal 216 KB; at 40 files a turn,
  1,000 turns took 2.8 MB, and the 128 MiB budget refused 209 of 1,949 goals by build order. With 16 kept, a goal
  is near 5 KB at 6 to 12 files a turn and near 15 KB at 40. The room's own 1 MiB bound on an answer stays the
  limit; the store does not cap how many goals a question asks. Measured on made walks with the real store at
  8ce02f78 (all hands b442f501 and a85c3e66), not on a scored history.

## 10. How we know it is done

Each row names what a right store does, and what a wrong one would do that its test catches.

| What | Shown by | A wrong store caught |
| --- | --- | --- |
| The path rule | Accepted: a 512-byte path, `a/b-c_d.e`. Refused: 513 bytes, a space, a quote, `é`, a leading `/`, `a//b`, `./a`, `a/..`, an empty path | One that accepts any of these, as revision 1's rule did |
| A walk file is read as written | Every field read back, on a step that named three files, a step that named none, an older store's one-target step, and a failed turn | One that drops a list or a `null`, accepts an unknown key or a wrong type, or repeats a refused value or key; markers are planted as values, as unknown keys and in unparsable lines, and are in no store, answer or log |
| Only listed turns teach | A list built, its id in every answer | One that admits an unlisted file, a second copy of an entry, a two-walk file, a listed entry left out, another repository's walk, a ship's walk after a room line, a wrong standing, a wrong measure, or an unverified turn into `N` or `k`; and a re-exported file after a standing changes |
| A ship's store is apart | A ship's store under `ship-share` gives one route that is not empty, `list` null and `for_experiment` false | One that lets a ship walk into an experiment's build, or an answer of a ship's store carry experiment flags |
| Visits and roads | Read then edit is one visit; leave and come back is two; three files in one step make two roads; a road walked twice by one turn has `k` 1; two alike turns share one cell and count two; a taught turn that named nothing is in `N` | One that counts repeats as turns, collapses a real return, or leaves an empty taught turn out of `N` |
| A route is stitched, and the cheapest | Walks start, a, b, target and start, b, x: the route to target is start, b, target, walked whole by neither, and the first walk's way is a detour kept and read back. A search written apart, over every simple way, agrees on fixed cases and on 1,000 sets drawn at random | One that returns the first walk's way, or a way that is not least, or the first way found |
| Cheaper by the measure, not by roads | Two walks start, a, b, target and one start, b, x: the three-road way, at exactly 8/27 against 2/9, with no detour named. One empty taught turn ties them at 1/8, broken by byte order; two reverse it | One that picks by the number of roads, or compares floats |
| Zero-cost cycles | Roads every taught turn walked, in a cycle: the route is simple, and first in byte order of the ways of least cost | One that loops, or settles a file by cost alone |
| Exact, and the same bytes | The same store's answer, byte for byte, on two machines; with the files given in another order; with goals permuted and repeated; with several detours; under a changed ambient `decimal` context. `nats` of 1/2 is `0.693147181`. Two products equal as floats and different as fractions are told apart | One that follows read order, the ambient context, or float equality |
| A detour is real | One with a shared final road, and one whose way passes a file twice, each kept and checked | One that keeps a way no taught turn went, a road no taught turn walked, a way no dearer, sides that do not meet, or a right key with a tampered turn, goal or visit |
| Only the cheapest are kept | Twenty dearer turns to one goal, the ten cheaper with the later names and the ten dearer tied: kept are the ten cheaper and the earliest six of the tie, listed and made as cells in `attempt` order, with `detours_more` 4; a goal with none left out says 0 | One that keeps by name, the dearest, the later of a tie, or more or fewer than 16; lists or makes them in cost order; says 0 when some were left out; or passes a check with a tampered count |
| What is not there is said | Each told apart and in precedence: no history, with a goal never named and one only untaught; a file no walk named; a file only an untaught walk named; a kernel refusal for a route and for a way, forced through the budget, with its code | One that conflates two kinds, or answers a route made of what was left |
| A question is the store's | Answered when its `repo`, `list` and `measure` are the store's | One that answers a question of another list, repository or measure, or answers it as no route |
| The store is the store | It rebuilds whole and renames into place; a failed build leaves the old file and says so; its check rebuilds every key and every witness; a recall run with this file present reads nothing of it | One that serves a partial or old file as the new list's, or accepts a damaged 2-cell recipe or witness |

## Decisions

1. **One path rule, the room's** (C2).
2. **The start is a 0-cell, written `null`,** because a repository may hold a file of any plain name.
3. **Routing is by path; blobs are evidence** (the lead's answer to Tardis's first question).
4. **A step's whole `named` list makes visits** (the lead's measurement: most looking is by shell).
5. **`share` 1 lets only `"passed_verified"` teach; `ship-share` 1 lets only ship walks teach,** in stores of
   their own (C3).
6. **Costs compare as exact fractions;** `nats` is for reading, worked one fixed way (C5).
7. **Ties break by byte order of the paths,** shorter first, over simple ways.
8. **Every route and detour is made at build time,** in a fixed order, and a query makes no cell (C6).
9. **Every road names a witness turn,** the first in byte order, beside its count (C4).
10. **A detour is a 2-generator,** the rule the store spec left to stage 4: from a taught turn's way to a
    strictly cheaper route between the same 0-cells. It shows that and no more.
11. **A goal keeps its 16 cheapest detours and counts the rest** (store `"3"`). The room's block uses only how many
    turns went a dearer way (the lead read `route_offer.rs`), so nothing it says is lost, and an answer's size stops
    growing with the history. 16 is a constant of this store version, not a field.

## Left to the builder

The command's name and flags; the store file's name and its new tables; how the search is written, so long as it
agrees with the search written apart; the order of work. Sections 1 to 8 and the rows of section 10 are fixed
here.

## What the reader named, and where it is answered

| Named change | Where |
| --- | --- |
| C1. State what the measure and a worker's order of naming mean | Section 5, "What a measure is not"; section 10, "Cheaper by the measure" |
| C2. Use the room's exact path rule | Section 1; section 10, "The path rule" |
| C3. Give ship trials a measure of their own | Sections 3 and 5; section 10, "A ship's store is apart" |
| C4. Name a witness turn for every road | Section 6; section 7, "The check" |
| C5. Finish the canonical answer and the decimal | Sections 6 and 8; section 10, "Exact, and the same bytes" |
| C6. Say when detours are made, in what order, how they are checked, and that a refusal is said | Section 7; section 10, "A detour is real" and "The store is the store" |
| C7. Fix admission: the list's form, every listed turn and no other, one repository, the question matched | Sections 2, 3 and 6, with the room's list form at 487f44bb; section 10, "Only listed turns teach" and "A question is the store's" |

**The same reader confirmed revision 2 with one more:**

| Named change | Where |
| --- | --- |
| R1. Fix the last two containers, the fractions' strings, and give a fixture | Sections 6, 7 and 8: `blobs` and a detour as w45 suggested, `str()` fractions, and the fixture |

**Asked since, by the room's builder (w46), through the lead:** every answer names the store's version and the
kernel's, so that the room can keep them with each offer (the room's spec, section 4). Section 6, and the fixture.

**Found on the room's 21 real walks, by the lead:** the room numbers steps from 0, and revision 4 said a positive
`seq`. A first `seq` of 0 is now read, and a detour's `seq` can be 0. Section 2.

**The code's reader (w50, Sol) on 2d1a2dac, approve with named changes, all made:**

| Named change | Where |
| --- | --- |
| C1. Accept a first `seq` of 0 | Section 2 (revision 5) |
| C2. Refuse one digest for two listed turns | Section 3 |
| C3. The room's own family and tool words | Section 2 |
| C4. Blobs from every taught step, apart from the collapsing of visits | Section 6; the store's version is raised to `"2"` |
| C5. The kernel's digest from the source its loader builds from | Section 6 |
| C6. Whole numbers written and read with no ceiling on their digits | Section 8 |
| C7. Bounds on reading and nesting, and refusals by name for what escaped them | Section 2's bounds |
| C8. Bind the header, the list's bytes and the walk rows | Section 7, "What the check binds" |

**Asked since, by the lead, after the second pilot (all hands 1352cfa0, ad7353d4, a85c3e66): store `"3"`.** The
answer's size was left to measure on the scored history; it was measured now on made histories instead (section 9).
A goal keeps its 16 cheapest detours and says `detours_more`. Sections 6, 7, 9 and 10, decision 11, and the fixture,
whose walks, list and question are unchanged.
