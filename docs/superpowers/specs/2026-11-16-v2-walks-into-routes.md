# v2: walks into roads, and a route back

Tardis, 2026-11-16, revision 1, not yet read. The store's side of
`docs/superpowers/specs/2026-11-16-v2-a-route-offered.md` ("the room's spec" below, revision 3 at 94d7027b),
which fixes what the room writes and what it needs back (its sections 1, 2, 3 and 8). This spec says how a
walk becomes cells, which walks may teach, what a road costs, what a route and a detour are, and what the
answer holds. It builds on the n-category store (`2026-11-07-ncat-store.md`) and its kernel
(`2026-11-07-ncat-kernel.md`), and states the detour rule that spec left to "stage 4". It needs a fresh reader
of the other family, like any spec.

## What is asked

1. **Read the room's walk files,** each checked against the list that says which turns may teach.
2. **Keep their roads as cells,** on the kernel, in a file that is derived and disposable.
3. **Answer a route,** for each file the room asks for, in the order asked, with the same bytes on any machine.
4. **Name the detours,** each kept as a cell the kernel checked, so that a route is shown to be a rewriting of
   ways turns really went.

## Not asked

- **An estimate.** The search is the cheapest way with no estimate of the distance left (the room's spec,
  "Not asked").
- **A tour.** A route to each goal on its own, in the order asked. Nothing joins two goals.
- **Names across machines.** A path means a path in one repository. Two repositories' walks never share a
  cell.
- **Recall.** Nothing in Engram's recall reads this. It answers the room, and nothing else.
- **Text.** The store reads paths, blob hashes, counts and times. It reads no message, prompt, command or
  output, and the walk file has no field that could carry one.

## 1. The walk file

JSON Lines: one walk on each line, as `yak item walks <item> --json` writes it (the room's spec, section 1).
Every field is required; a part the room did not record is `null`, never left out and never 0.

| Field | Type | What |
| --- | --- | --- |
| `v` | 1 | this format's number |
| `source` | `"room"` or `"ship"` | a turn of the room, or a ship's own record of files it named |
| `repo` | 40 or 64 hex | the repository's root commit, so that the same repository has the same id on any clone |
| `base` | 40 or 64 hex | the commit the turn's sandbox was made from |
| `item`, `attempt` | the room's ids | |
| `family` | the room's family name | `claude`, `codex`, `script`; never a worker's own name |
| `verdict` | `"passed"`, `"failed"` or `null` | whether the turn's commit passed its frozen check; `null` when the check could not run |
| `standing` | `"passed_verified"`, `"passed_unverified"`, `"failed"` or `"unjudged"` | how the room classes the turn when it writes the file; a ship's walk is `"unjudged"` |
| `steps` | list | in order of `seq` |
| `changed` | list of `[path, "added" \| "changed" \| "removed"]` | the paths the turn's commit changed, in the order recorded |

A step is an object: `seq` (a positive integer, increasing), `tool` (the room's tool word), `ok` (true or
false), `named` (a list of `[path, blob]` in the order named, possibly empty), `seen_ms`, `result_ms`,
`tokens_in`, `tokens_out` (each an integer or `null`). A step of an older store, which had one target and no
list, is written with that one file as its list.

**Refused, the whole file with it:** a field missing, unknown, or of another type; a `seq` that does not
increase; a path that is not plain (not empty, not absolute, no `.` or `..` part, no empty part, no control
character, no backslash); a blob that is not 40 or 64 lowercase hex; a line longer than 1 MiB. The refusal
names the line and the field, and never repeats a value. Nothing is dropped silently: a failed step and a
failed turn are read, and kept as what they are.

## 2. Which walks teach

**An experiment's store is built from a list** (the room's spec, section 3), and from nothing else. The store
reads the list, which names each walk file's SHA-256, and checks each file it is given against it: the
file's bytes hash to an entry; no entry is given twice; the file's `repo`, `base`, `item`, `attempt` and
`standing` are the entry's; its `source` is `"room"`. Anything else stops the build and is named. The list's
own SHA-256 is written into the store and into every answer.

**The measure says which standings teach.** This spec defines one, `share`, version 1, which lets only
`"passed_verified"` teach. A turn of another standing is read, its walk kept, and counted apart as *not
taught*; it makes no road and enters no count. Only its paths are kept, so that a file it alone named is told
apart from one nobody named (section 5).

**A ship's walks are kept apart as unjudged** (the lead's question: 239 session records, 626 roads on the
Mac). They are built only into a store of their own, with no list, whose answers say `"list": null` and
`"for_experiment": false`. No experiment's store reads a ship's walk: the list check refuses one.

## 3. The cells

All of it lives on the kernel, in one category per store.

- **0-cells.** One 0-generator for the start, where every turn begins, and one for each path any read walk
  named. The start is not a path: no path can name it, and the answer writes it as `null`.
- **A visit.** A taught walk's visits are its steps' `named` lists, joined in step order and the order named,
  with a repeat of the visit just before dropped. A file read and then edited is one visit; a file left and
  come back to is two. A walk that named nothing has no visits.
- **A road, a 1-generator.** The start to a walk's first visit, and each visit to the next. One generator for
  each ordered pair any taught walk walked, however often. There is no road from a file to itself.
- **A walk's way to a file, a 1-cell.** The composite of its roads from the start up to the file's first
  visit, in order, each road as often as it was walked. Two turns that walked alike have the same cell; they
  are still two turns in every count.
- **A route, a 1-cell.** The composite of the roads section 5 chooses.
- **A detour, a 2-generator,** from a walk's way to the route to the same file (section 6). The kernel
  refuses one whose two sides do not start and end at the same 0-cells, so a detour whose ends do not meet
  cannot be kept.

**Counts.** For each road, the number of taught turns that walked it, each turn once. `N` is the number of
taught turns in the list, whether or not they named anything.

**The file** is the store's (`2026-11-07-ncat-store.md`): generators, composites by recipe, and a check that
rebuilds each key through the kernel and refuses a mismatch. Two tables are added: `walk` (attempt, item,
family, standing, taught, the file's SHA-256) and `detour` (the 2-generator's key, the turn, the goal, the
visit). It is rebuilt whole from the list and its files, and renamed into place.

## 4. The measure: `share`, version 1

- **A road's share** is `k / N`: `k` taught turns walked it, of `N`.
- **Its cost** is `−ln(k / N)`. A road every taught turn walked costs nothing; one walked by a single turn of
  many costs the most.
- **A way's cost** is the sum of its roads' costs, a road walked twice counted twice. So a way's cost is
  `−ln` of the product of its roads' shares.
- **Compared exactly.** One way is cheaper than another when the product of its shares is strictly larger.
  The store compares the products as exact fractions, never as floating-point sums, so no machine's
  logarithm decides an answer.
- **Written exactly.** A cost is given as the product, `num` and `den` in lowest terms, and beside it `nats`:
  `−ln` of that fraction, worked in Python's `decimal` at 34 digits (correctly rounded on every machine)
  and quantized to 9 places, as a string. `nats` is for reading; the fraction decides.
- **Longer can be cheaper.** Under a price by share, a way of three well-walked roads can cost less than a
  way of two seldom-walked ones (the room's spec, section 8's third row). The answer gives the cost and,
  apart from it, the number of roads. The number decides nothing.

## 5. A route

**The question,** one JSON object: `v` 1, `repo`, the list's SHA-256 (or `null` for a ship's store), and
`goals`, a list of plain paths, in the room's order.

**The answer,** one JSON object, written with its keys sorted, no spaces, and UTF-8, so that the same store
and the same question give the same bytes on any machine:

- `v`, `repo`, `list`, `for_experiment`, the measure (`name`, `version`, the standings that teach), `taught`
  (`N`), and `answers`: one for each goal, in the order asked, a goal asked twice answered twice.
- **A route:** `paths` (the files after the start, in order, ending at the goal); `roads` (for each, `from`,
  `to`, and `turns`, its `k`; `from` is `null` for the start); `cost`; `roads_n`; `blobs` (for each path on
  the route, every blob taught walks saw it at, sorted, so the room can mark a file changed since or gone);
  and `detours` (section 6).
- **The cheapest way.** Of all ways from the start to the goal along roads, with no file twice, the one whose
  cost is least. Of ways that cost the same, the one whose list of paths is first in byte order, a shorter
  list first where one begins the other. Found by a search over exact fractions; a test checks it against
  every simple way, on walks drawn at random.
- **No route, said as one of four:**
  - `"no_history"`: the list teaches no turn (`N` is 0).
  - `"never_named"`: no walk in the store named the file, as with a file a turn added.
  - `"not_taught"`: only walks that do not teach named it.
  - `"refused"`: the kernel refused a cell the answer needed, with the kernel's reason. No route is made of
    what was left.
  A taught walk that named the file always gives a way to it, so there is no fifth kind.

## 6. A detour

For each taught turn that visited the goal, its way to the goal's first visit is set beside the route.

- **A detour** is a way that costs strictly more than the route. The answer names the turn (`item`,
  `attempt`, `family`), `visit` (how far along its visits the goal first came, from 1) and `seq` (that
  step's), and the way: its `paths`, `cost` and `roads_n`. A way that costs the same or less is not a detour,
  and is not named.
- **Kept as a cell.** Each detour is a 2-generator from the way to the route, kept in the store's file and
  read back by its key. The store refuses to keep one, by name, when the way is not a taught turn's way, when
  either side uses a road no taught turn walked, when the way is no dearer, or when the two sides do not
  meet (the kernel's own refusal of a generator between cells that are not parallel).
- **Stitched, and said so.** A route can be walked whole by no turn. The answer does not say otherwise: each
  road carries its own count, and only those.

## 7. What it doesn't do, and what it accepts

- **No filling in.** A step with no named file adds no visit, and a turn whose files are all outside the
  repository has no roads. The room's spec measures how little the first pilot named (103 of 244 steps).
- **Order within a step is the order named.** A step that named three files makes two roads between them,
  though the worker may have read them at once. That is what was recorded, so it is what counts.
- **The blob is evidence, not identity.** Routing is by path. A file whose contents changed between two
  turns' bases is one 0-cell; `blobs` says it was seen at two versions.
- **Costs grow with the history.** `N` grows as turns are taught, so every cost moves. An answer is of one
  list, named by its hash, and is never compared with an answer of another.
- **Size.** The first pilot's walks made 16 files and 50 roads. Nothing here needs more than thousands of
  cells, well inside the store's budget of 128 MiB.

## 8. How we know it is done

Each row has a case that must pass and a case that must be refused. The rows of the room's spec that rest on
the store (its second to seventh) are here too, by the store's side of them.

| What | Shown by |
| --- | --- |
| A walk file is read as written | Every field read back, on a step that named three files, a step that named none, an older store's one-target step, and a failed turn. Refused, each by name and with no value repeated: a field missing, an unknown field, a `seq` that goes back, a path with `..`, a blob of 39 hex, a line over 1 MiB. A marker planted in a field's place is in no store, answer or log |
| Only listed turns teach | Refused, each by name: an unlisted file, an entry given twice, a wrong hash, another repository's walk, a ship's walk, a standing other than the list's. A passed but unverified turn is kept and in no count |
| A ship's store is apart | Built from ship walks with no list: `for_experiment` false and `list` null in every answer. Given to an experiment's build, a ship's walk is refused |
| Visits and roads | Read then edit of one file is one visit; a file left and come back to is two; a step's three files make two roads; a road walked twice by one turn counts once; two turns that walked alike count two and share one cell |
| A route is stitched, and the cheapest | Walks start, a, b, target and start, b, x: the route to target is start, b, target, two roads walked whole by neither, and the first walk's way is a detour. A search written apart, over every simple way, agrees on this and on 1,000 sets of walks drawn at random |
| Cheaper by the measure, not by roads | Walks start, a, b, target twice and start, b, x once: the three-road way is the answer, with its cost and three roads, and no detour is named |
| Exact, and the same bytes | Two ways of equal cost: the one first in byte order, on two machines, byte for byte. Two products that agree to 15 digits as floats and differ as fractions are told apart |
| A detour is real | One kept and read back by its key. Refused, by name: a way no taught turn went, a road no taught turn walked, a way no dearer, sides that do not meet |
| What is not there is said | Each told from the others: no history; a file no walk named; a file only an untaught turn named; a kernel refusal with its reason, forced through the kernel's budget |
| The store is the store | It rebuilds whole and renames into place; its check rebuilds each key through the kernel; nothing in Engram's recall reads it |

## Decisions

1. **The start is a 0-cell, written `null`,** because a repository may hold a file of any plain name (the
   room's spec, section 2).
2. **Routing is by path; blobs are evidence** (the lead's answer to Tardis's first question).
3. **A step's whole `named` list makes visits,** not only its target (the lead's measurement: most looking is
   by shell).
4. **Only `"passed_verified"` teaches under `share` 1.** Another standing would be another measure, named and
   versioned in the list.
5. **Costs compare as exact fractions,** with `nats` for reading.
6. **Ties break by byte order of the paths,** shorter first.
7. **A ship's walks build only a store of their own.**
8. **A detour is a 2-generator,** the rule the store spec left to stage 4: from a taught turn's way to a
   strictly cheaper route between the same 0-cells.

## Left to the builder

The command's name and flags; the store file's name; how the search is written, so long as it agrees with
the search written apart; the order of work. Sections 1 to 6 and the rows of section 8 are fixed here.
