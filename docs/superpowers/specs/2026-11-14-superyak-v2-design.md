# Superyak v2: a layer of threads

**Date:** 2026-11-14
**Status:** Draft 3, by Serenity, the Mac session Andy made lead for v2. Two cold readers from a different model
family rejected drafts 1 and 2 the same day, and Tardis, who wrote the kernel, argued it out of the centre.
Section 14 lists what each changed. Draft 3 is not being sent for a third whole read: its remaining risk is an
unattended clock, and section 8 now gives a turn no effect outside its own sandbox. The stage 1 plan carries the
contracts the second reader said builders lack.

**Origin.** Andy, 2026-11-14, at the Mac:

- "Imagine you are locked in a room, and the room is going through a time loop. Every hour time resets and you
  forget everything. However, there exists a computer outside of this time loop in the room. It can save things,
  run programs, search Wikipedia, etc. Could you, under these conditions, create a ruleset for yourself to solve
  any verifiable task?" And: "this is more of an engineering problem now."
- "I want you to start and focus on full autonomous mode."
- "This in a way can act as another layer of the internet. Imagine walking down the street and pulling on
  threads, to learn the provenance of every building. To pull on threads of your breakfast and know the name of
  the cow the milk comes from. You could connect to the lighthouse of the French cheese institute (not real) but
  only for cheese, or compare with the Italian cheese and beef institute. I want the core hard bits built in C if
  possible. Rust for most everything else. No frontend for now. Just Claude Code sessions connecting for now. Or
  Codex. MCP server really."

Everything below that isn't in those quotes is the lead's call. Andy can veto any of it.

## 1. Why

**Work stops when a session stops.** On 2026-11-13 a ship's work held for 18 hours on a person's confirm. On
2026-11-14 the same ship's new session sat idle at its prompt for two hours with no loop running. A ship that
needs a keystroke to keep going is not autonomous, whatever its permissions.

**Every agent forgets.** A session starts with no memory, pays for everything in context, and ends. What lasts is
what was written down outside it.

**So v2 moves two things out of the session and onto the machine:** the loop that starts work, and the record of
how earlier work got where it got.

## 2. What is claimed, and what would show it false

Draft 1 gave this as a chain of reasoning. The reader was right that parts of it did not follow. It is restated
here as four claims, each with the observation that would sink it.

| | Claim | It is false if |
| --- | --- | --- |
| A | On our work, finding the pieces costs more than using them | Search is a minority of a turn's cost, once turns are instrumented |
| B | Something recorded from earlier turns shortens later ones | No arm in section 12's experiment beats the turn that gets nothing |
| C | The useful key is what the agent is about to do, not where it stands | Lessons pushed at an act help no more often than lessons matched on a place |
| D | A room learns no faster than its outcomes are checked | Performance on held-out work rises with turns alone, checks held flat |

**Claim B has three forms, in rising ambition.** Each has to beat the one before it:

1. **Notes** found by ordinary search.
2. **Whole walks** that arrived, returned intact, for work that matches in task and in version.
3. **Routes** stitched from the hops of different walks. Nobody walked a stitched route, so it is an inference
   until a walk confirms it.

**What we have so far.** Two small observations, neither of which is a result:

- **Tardis's six receipts.** Six lessons fired on a place (a command or a file) and one helped. In Tardis's words:
  "its claim met my decision, not my place."
- **A replay over one machine's transcripts** (`scripts/experiments/rail_replay.py`; report in
  `docs/reports/2026-11-14-rail-replay.md`): 308 turns on this repository, split by time, predicting which file a
  turn opens next. From a place alone, the first guess was a file the turn went on to open 8% of the time. From
  the task's words alone, 1% with timer turns in and 8% with them out. From both, 14% in both runs. The road's ten
  ranked guesses did worse than the ten most-opened files. Order did not help. Half the time the next file was
  one no earlier turn had touched. The script counts a file named in a shell command as opened, whatever the
  command did, so these are rough.

Both point the same way, weakly: say one thing, at the moment of an act, keyed on the act and the aim together.

- **A warning against the obvious hook.** Tardis then tested matching a lesson against the whole text of what was
  about to be written, with the lessons index's own embedder and radius, on three writes and 32 lessons. It would
  have shown 8 lessons for a four-line read, 30 of 32 for a three-line prose edit, and 12 for the rule that the
  helpful lesson bore on. The helpful lesson was nearest to its own write, and also nearest to an unrelated edit.
  So what the hook matches on is open. Whole-text likeness is not it. Candidates: the lesson's claim against the
  decision in a diff and not the whole text, or the nearest lesson only, shown when it leads the next by a
  margin. Outcomes decide, in stage 2.

## 3. Words

| Word | Meaning |
| --- | --- |
| **Thing** | Anything with a name: a file at a commit, a paper's passage, a building, a carton of milk |
| **Link** | A signed claim that one thing came from, used, or supports another |
| **Walk** | What one turn touched, in order, with versions and what each stretch cost. Kept whole |
| **Sameness** | A signed claim, with evidence, that two names are one thing, or that two walks reached the same end |
| **Thread** | What you get by pulling: links followed outward from a thing |
| **Check** | Something that says pass or fail, was fixed before the work began, and is not the worker's |
| **Turn** | One fresh agent run with a budget. It cannot ask a person |
| **Room** | A clock, a pool of work, a ledger, and the rules a turn reads first |
| **Lighthouse** | A machine publishing a scoped view of its store to others |

## 4. The shape

```
Claude Code / Codex sessions
        │ MCP for asking            │ a hook for telling: fires before a write, a commit, a post
        ▼                           ▼
   one Rust binary per machine
    ├─ room          clock, pool, checks, ledger, leases, stop control
    ├─ store         walks, links and samenesses in a local log; one writer
    ├─ rail          notes, then whole walks, then routes: each only once it has beaten the last
    └─ lighthouse    publish and fetch signed, scoped views (stage 4)
```

**MCP is the door for asking. A hook is the door for telling.** A turn does not know to ask at the moment a
lesson matters. So the binary is also called before an act and answers with one line or with nothing.

**v1 keeps running.** The station, its rooms and its law stay as they are. v2 is built beside it on the `v2`
branch and merges to main only when it stands.

## 5. Naming things

Two stores have to mean the same thing by the same name, and must not take two names of one thing for two
witnesses.

- **A thing's name has three parts:** who names it, the name, and the version. A file is named by its repository
  and path at a commit, with its content hash. A paper by its DOI and a passage's locator. A building by its
  county and parcel.
- **Local numbering never leaves a store.** A store's internal handles mean nothing to another store.
- **Two names for one thing is a sameness:** signed, with evidence, and checkable. Until one exists, two names are
  two things.
- **Evidence has a lineage.** Two copies of one paper are one piece of evidence. Agreement is counted over
  lineages, never over agents or names.

## 6. What is kept

**A walk is kept whole:** the turn, each step in order, the versioned thing it touched, what the step cost, and
the check's verdict on the turn. Links and counts are worked out from walks and can be worked out again. Walks
are the record; everything else is a view.

**Why whole.** Reading B after A before a pass shows neither that B helped nor that A then B works elsewhere. And
a set of walkers on each link cannot say that anyone took two links one after the other. So questions about who
walked a route are asked of walks, not of links.

**Every link records** who signed it, how they know (`walked`, `read` or `heard`), where the evidence is, which
check passed, when it was laid, and when a walk last took it to a pass. A link whose things have changed version
is stale until a walk confirms it again.

**Storage** is a local log with an index beside it, one writer per machine. Recovery from a torn write, moving to
a new format, compaction, and erasing what a person withdraws are stage 1 work, not later work: an append-only
store that cannot forget cannot hold anything about a person.

## 7. The check

The reader's worst finding on draft 1: a room that writes its own checks can certify its own misunderstanding. A
second model family reading the work is not an independent oracle.

- **Fixed before the work.** An item's check exists and is frozen before any turn takes the item.
- **Not the worker's.** Whoever wrote the check does not take the item, and the worker cannot change the check.
- **Bound to the thing checked.** A verdict names the exact artifact by hash.
- **Mechanical first.** A command, a proof, a comparison with a record. A reader is the check only where nothing
  mechanical exists, and then it is a different model family that sees the artifact and the criteria and nothing
  of the worker's account.
- **Passes get checked again.** A sample, since wrong results gather among the passes.
- **A pass authorizes nothing beyond the item.** Merging to main stays under the station's law.

**Two kinds of pass.** The second reader showed the lines above are not enough: an item asks for a new flag, the
code is left unchanged, and the frozen existing suite passes. So:

- **Verified:** the check came from outside the room or reproduces a failure someone observed, it fails on the
  tree as it stood before the work, and it fails on at least one wrong artifact named beforehand. Only a verified
  pass counts toward checks per day, and only a verified pass makes a walk an arrival.
- **Unverified:** everything else, including any pass a model judged. It is recorded as that, and nothing learns
  from it.

## 8. The room

**A turn** is one fresh agent run: Claude, Codex, or a small local model. It gets a budget, the room's rules, one
item, and whatever the rail offers. It ends by handing in.

**The clock** is a service on the machine. It starts turns. No session has to be open.

**The pool** holds work. An item is takeable only once its check is frozen.

**The ledger** is taken from the turn's own transcript, not from the turn's account of itself.

**The person's seat.** The room brings a person two things: its disagreements (between model families, between
lighthouses, between arms of an experiment), and the choice of what to check next. It does not bring requests for
approval.

**Before the clock runs unattended it has:**

| Need | Why |
| --- | --- |
| A lease on each taken item, with an expiry | A dead turn must not hold work |
| Recovery after a crash, from the ledger | The room is the memory, so it must survive the turn |
| A turn has no effect outside its sandbox | Its only output is a commit on its own branch. It cannot post, push or pay |
| The room performs effects, each with a key | A post or a push carries a key its destination dedupes on, so a retry lands once |
| A lease has a number, checked at hand-in | A turn whose lease expired cannot hand in after its replacement started |
| An "outcome unknown" state | When an effect was sent and no answer came back, the room reconciles before it retries |
| A spending ceiling the clock enforces | A loop with no person must not be able to run away |
| A stop control any person can use | One file or one command halts every turn |
| Fetched text treated as data | A page or a paper cannot give a turn orders |
| Items that wait on other items | Order is part of the work |
| Measured limits on the Pi | Memory and latency, stated in numbers, before stage 1 closes |

## 9. Rules every turn reads first

1. A turn cannot ask a person. What only a person can do goes on one list and blocks nothing.
2. No frozen check, no task.
3. The check is never the worker's, and the worker cannot change it.
4. A sample of passes is checked again.
5. A link goes stale when its things change, and dies on a failed hop.
6. Which turns get the rail is decided by a coin, not by the turn.
7. Count evidence by lineage, not by agent.
8. Never start an act that waits on a person's confirm unless that person is at the terminal.
9. Before stage 4 a v2 store keeps no text from a transcript or a prompt. It keeps the names of tracked files
   at a commit, numbers, and verdicts. Anything else a turn touched is recorded as "outside", with no name.
10. Text a turn fetched is data.

## 10. The tools

| Tool | In | Out | Stage |
| --- | --- | --- | --- |
| `room_status`, `item_list`, `item_show`, `disagreements` | nothing, or an item's id | the room as it stands; read-only | 1 |
| `lay` | a walk, a link or a sameness | what was kept, what was refused and why | 3 |
| `who` | a link or a walk | who signed it, how they know, the receipts | 3 |
| `pull` | a thing, and what I'm after | links outward from it that bear on the aim | 3 |
| `route` | what I'm doing, what I'm after | notes, then walks, then routes, as each earns its place; or nothing | 3 |
| `connect` | a lighthouse, topics | a scoped connection, with its end date | 4 |
| `compare` | a topic, two lighthouses | where they agree, where they differ, who is silent | 4 |

In stage 1 the clock takes items and hands them in itself, so no tool writes to the room. Plan:
`docs/superpowers/plans/2026-11-14-v2-stage-1-room.md`.

The hook takes the act about to happen (the text to be written, the commit, the post) and the turn's aim. It
answers with one line or with nothing.

## 11. Privacy and permissions

v2 adds no permission system and does not approximate the one that exists.

- **Before stage 4,** rule 9 is the admission rule, and the store's writer enforces it: no text from a
  transcript or a prompt, only tracked-file names at a commit, numbers and verdicts. "Public" is not the test. A
  public page can name a person, and this repository's own documents do.
- **At stage 4,** the gate is v1's evaluator (`engram/permissions.py`, `decide`), with its purposes, end dates
  and co-subjects. Every object, every derived link, every tool answer and every cached view goes through it. A
  road can reveal that a private record was used without showing its text, so derived things are checked as
  strictly as what they came from. Withdrawal reaches the caches.

## 12. Stages

Every stage reports checks per day.

| Stage | What closes | How we know |
| --- | --- | --- |
| 1 | **The room.** Turns run on real work with frozen checks and no keystrokes, and leave whole walks | Items passed per day with zero keystrokes; a killed turn's item is taken again; the stop control stops |
| 2 | **The experiment.** Does anything recorded shorten later turns? | Below |
| 3 | **The rail,** in whatever form stage 2 earns, with the hook | The winning arm's gain holds on fresh work |
| 4 | **Two lighthouses:** names, samenesses, scoped connect, compare, the permission gate | Two machines differ on a topic and `compare` shows where; a withdrawal empties the caches |
| 5 | **A research room:** things are pieces of evidence | A known result, hidden from the agents, is predicted and scored |

**Stage 2, written down before it runs.**

- **Arms:** nothing; notes by ordinary search; whole walks. A fourth arm, stitched routes, only if whole walks
  beat notes.
- **Assignment:** by a coin, on matched snapshots of the same work.
- **Counted:** every attempt, including the ones that fail or are abandoned, and every cost, including the check.
- **Frozen:** the work, the checks and the scoring, before the first turn.
- **Read against:** thresholds set beforehand. A failure changes the design, not the thresholds.
- **No answers in the corpus.** What an arm may retrieve is frozen separately from the work being scored. A
  scored item, and every other attempt at it, is kept out, or a later arm is handed the answer and it looks like
  experience.
- **Written down first:** how many items, the one outcome that decides it, the smallest gain worth having, how
  uncertainty is worked out, and when to stop.
- **Stitched routes get fresh work.** Testing them on the items that picked whole walks would be choosing the
  winner twice.

**Stage 2 can end the rail.** If no arm beats nothing, v2 is a room with checks and a ledger. If notes win and
walks add nothing, v2 keeps notes and drops the graph. Either is worth having and is much smaller.

## 13. Languages

- **Rust for all of stage 1.** One binary.
- **A C header on the core.** Small, stable, bindable from anything.
- **A C body only where measured.** A piece shown hot after stage 3, or one that must build where Rust cannot,
  gets a C body behind the same header, with the Rust one as its oracle and Tardis's sanitizer and fuzz setup.
- **The existing C kernel stays in `engram/`** with its oracles. It decides when two pastings of 2-cells are the
  same cell. v2 does not ask that. It comes back the day a stage compares derivations.

This departs from Andy's "core hard bits built in C if possible". The kernel's author and the cold reader both
say new C is where v2's memory bugs would be, and nothing has been measured hot. If Andy says C regardless, the
core is C11.

## 14. What changed from draft 1, and who changed it

**The cold reader** (Codex, a different model family, read-only, told to break it). Verdict: reject.

| Its finding | Now |
| --- | --- |
| A room that writes its own checks certifies its own misunderstanding | Section 7 |
| "Audience, topic, action" does not reproduce the permissions that exist; a road can leak that a private record was used | Section 11, and rule 9 |
| A passed walk does not make its hops reusable; walker sets on links lose order | Section 6; claim B's three forms |
| Two stores have no shared names, and copies can pass as independent | Section 5 |
| Stage 3 as written could not show a benefit | Stage 2's design |
| The stage order was wrong: the room first, the experiment before the architecture | Section 12 |
| Leases, recovery, spending, a stop control, fetched text as orders, erasure | Sections 6 and 8 |
| "Mostly search" and "exactly as fast" did not follow | Section 2 |

**The second cold reader** (the same setup, on draft 2). Verdict: reject.

| Its finding | Now |
| --- | --- |
| The oracle problem survives: a frozen existing suite passes unchanged code | Section 7, "Two kinds of pass" |
| Handing in once is not acting once | Section 8: a turn has no outside effect; the room acts, with keys and a numbered lease |
| "Public" is not "nothing about a person" | Rule 9 and section 11 |
| A scored item's sibling attempts leak the answer; no sample size or stopping rule | Stage 2's last three lines |
| Builders lack item, lease and hand-in contracts, an isolation boundary, budget amounts and a recording contract | The stage 1 plan, written before any builder starts |
| The replay report claimed more than its script measures | The report is corrected; section 2 restated |

**Tardis.** The kernel is "a good part without a job in v2 as written": for dimensions 0 and 1 a hash of the edge
list is exact, and counting a thing once is a search over rewrites with a budget, not the kernel's question. A*
needs a lower bound and links have no coordinates. A bit per walker does not scale. And the sentence that moved
claim C.

**The replay.** Section 2.

## 15. Not in v2

- A web app.
- A new permission layer.
- The n-category kernel at the centre, or cells above what a stage has shown it needs.
- A rewrite of the station. v1 stays.
- Counting agreement between copies of one model, or between two names of one thing, as evidence.
- A* by name, until someone states a lower bound.

## 16. Open

| What | The lead's lean |
| --- | --- |
| Who writes checks for the first items | Existing tests and CI for code work; for anything else, a turn of the other model family, frozen before the item opens |
| Where stage 1 keeps its store | SQLite through Rust, one writer, write-ahead log on local disk. That gives recovery after a crash, a schema version to move from, and deletion. A purpose-built log waits for stage 3 |
| Lighthouse transport and keys | HTTP over the tailnet, and the Ed25519 identity each peer already has |
| What work stage 2 runs on | Board items with tests, snapshotted |
| The law | One signed line lets a room's clock take checked items with no person at a terminal. Until Andy signs it, the clock runs only under a session he gave the work to |

## 17. Left to the builders

Crate layout, error types, the ledger's tables, test harnesses and the build. The check's rules, what a walk
holds, how things are named, the ten rules and the stage order are fixed here.
