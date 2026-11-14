# Superyak v2: a layer of threads

**Date:** 2026-11-14
**Status:** Draft 1, by Serenity, the Mac session Andy made lead for v2. Nobody else has read it yet. Before
anything is built on it, a reader from a different model family reads it cold and is told to break it, and Tardis
reads the C parts as the kernel's author.

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

**Every agent forgets.** A session starts with no memory, pays for everything in context, and ends. That is the
room in the quote. What lasts is what was written down outside it.

**So v2 moves two things out of the session and onto the machine:** the loop that starts work, and the record of
how earlier work got where it got.

## 2. The mechanism, and what follows from it

This is reasoning, not a result. Section 10 says how each step gets tested.

1. An agent's cost is mostly search: finding the few pieces that matter. Using them is cheap.
2. A recorded walk helps a later agent only if tasks share pieces, and if the later agent can find the right old
   walk for less than searching afresh.
3. What a road adds over a note is position. A note answers "what matters for this task". A road answers "from
   where you stand now, where did others go next, and did they arrive". The link was made by use, not by likeness
   of words.
4. So the rail is learning moved outside the model. The reasoner stays fixed. What improves is the stored answer
   to "where next", updated by checked arrivals.
5. That kind of learning runs exactly as fast as outcomes are checked.

What follows:

- **The clock is checks per day.** Ten thousand agents behind one slow check learn at one agent's rate.
- **A road is a cached claim and it goes stale.** It carries the time of its last checked arrival, and a failed
  hop kills it.
- **Following roads removes randomness.** Use feeds use until there is one route. So a fixed share of turns goes
  off-road for good, and those turns are also the test of whether the rail helps.
- **Many walkers are worth more than one only by gluing.** Each knows its own ground. So v2 counts evidence
  touched, not agents, and every thread says how its signer knows.
- **Earlier tests do not settle this.** They ran on chat and on recall ranking, where a move is not a step toward
  a checked arrival. The claim is untested in its own domain.

## 3. Words

| Word | Meaning |
| --- | --- |
| **Thing** | Anything with a name: a file, a paper's passage, a building, a carton of milk. A 0-cell |
| **Link** | A signed claim that one thing came from, used, or supports another. A 1-cell |
| **Walk** | The links one turn made, in order, with what each stretch cost |
| **Road** | A link that at least one walk took on the way to a passed check |
| **Sameness, detour** | A 2-cell: two routes between the same things that are the same, or one much shorter |
| **Thread** | What you get by pulling: links followed outward from a thing |
| **Check** | Something that says pass or fail and is not the worker: a command, a proof, a second reader, a bench |
| **Turn** | One fresh agent run with a budget. It cannot ask a person |
| **Room** | A clock, a pool of work, a ledger, and the rules a turn reads first |
| **Lighthouse** | A machine publishing a scoped view of its store to others |

## 4. The shape

```
Claude Code / Codex sessions
        │ MCP: stdio on a machine, HTTP between machines
        ▼
   one Rust binary per machine
    ├─ MCP server    pull · lay · route · compare · connect · who · work
    ├─ lighthouse    publish and fetch signed views, scoped by topic
    ├─ room          clock, work with its check, ledger, decisions log
    ├─ store         append-only cells on local disk, one writer
    └─ C core
        ├─ kernel    cells and composition (engram/ncat_kernel.c, exists)
        ├─ route     bounded A*, set arithmetic over who walked
        └─ glue      where sources agree and differ
```

**MCP is the only door.** v2 has no web app. A person uses it through a Claude Code or Codex session.

**v1 keeps running.** The station, its rooms and its law stay as they are. v2 is built beside it on the `v2`
branch and merges to main only when it stands.

## 5. What is kept

**Cells of dimension 0 to 2, and no higher.** The kernel holds that part completely (its spec, 2026-11-07).
Dimension 2 has two jobs here: a sameness stops one piece of knowledge being counted twice, and a detour is a
learned shortcut. Nothing here needs dimension 3 yet.

**Every link records:**

| Field | Why |
| --- | --- |
| from, to, kind | The claim itself |
| signer | Who laid it. A key, as peers already have |
| how known | `walked` (the signer went there and a check passed), `read` (a source says so), or `heard` |
| evidence | Where to look: a source, a commit, a run |
| check | Which check passed, if one did |
| laid at, last arrival | When it was laid, and when a walk last took it to a passed check |
| topic | What it is about, so a connection can be scoped |
| walkers | Which walkers have taken it, one bit each |

**Storage** is an append-only log per machine with an index beside it. One process writes. Nothing is opened
across machines; machines exchange signed views. (SQLite's write-ahead log does not work on shared storage.)

## 6. The C core

Three small libraries, each behind one header, with no I/O, no threads of their own, and no memory they did not
get from a budget the caller set.

- **kernel:** the existing C11 kernel, moved out of `engram/` unchanged in behaviour. Its 831-line test file and
  the C++ port's corpus of 20,000 shapes are its two oracles.
- **route:** A* over links with a work budget. A walker is one bit on a link, so "the route these walkers took and
  those did not" is AND, OR and NOT while routing. It returns a route or says it ran out of budget; it never
  guesses.
- **glue:** for one topic and several sources, where they agree, where they differ, and who is silent. Silence is
  never counted as dissent.

**The lead's call: C11, not the C++ port.** Andy named C. Rust owns all memory outside the ABI, which removes most
of what the port was for. Tardis wrote both and may disagree; that discussion is open in the room.

## 7. The Rust side

| Crate | Does |
| --- | --- |
| `core-sys` | Binds the three C headers. The only `unsafe` in v2 |
| `store` | The log, the index, signing and verifying |
| `mcp` | The tools in section 8, over stdio and HTTP |
| `lighthouse` | Publishing and fetching scoped views; the connection's scope; receipts |
| `room` | The clock, the pool, checks, the ledger, the decisions log |
| `cli` | One binary that starts any of the above |

Scope reuses v1's rule and adds nothing: audience, topic and action; layers combine by intersection; a deny wins.

## 8. The tools

| Tool | In | Out |
| --- | --- | --- |
| `pull` | a thing, how far | links outward from it; each with signer, how known, last arrival |
| `lay` | a link, or a walk | what was kept, and what was refused and why |
| `route` | where I am, what I'm after | a short route others' walks support, or nothing |
| `compare` | a topic, two lighthouses | where they agree, where they differ, who is silent |
| `connect` | a lighthouse, topics | a scoped connection, with its end date |
| `who` | a link or a route | who laid it, how they know, the receipts |
| `work` | take, or hand in | an item with its check; or the check's verdict |

`route` says nothing when it is unsure. A wrong route costs the context it was meant to save.

## 9. The room, and the rules

**A turn** is one fresh agent run: Claude, Codex, or a small local model. It gets a budget, the room's rules, one
item, and a route if the rail has one. It ends by handing in.

**The clock** is a service on the machine. It starts turns. No session has to be open.

**The pool** holds work. An item is takeable only if it names its check. An item without one becomes "write the
check".

**The ledger** is append-only: which turn took what, what it touched in order, what each stretch cost, what the
check said. It is taken from the turn's own transcript, not from the turn's account of itself.

**The person's seat.** The room brings a person two things: its disagreements (between model families, between
lighthouses, between rail and off-road turns), and the choice of what to check next. It does not bring requests
for approval.

**Rules every turn reads first:**

1. A turn cannot ask a person. What only a person can do goes on one list and blocks nothing.
2. No check, no task.
3. The checker is never the worker. Where a reader is the check, it is a different model family.
4. A sample of passes is checked again. Wrong results gather among the passes.
5. A road dies on a failed hop.
6. A fixed share of turns runs without the rail.
7. Count evidence, not agents.
8. Never start an act that waits on a person's confirm unless that person is at the terminal.
9. What is private stays out of every store that is published.

## 10. Stages

Every stage reports checks per day.

| Stage | What closes | How we know |
| --- | --- | --- |
| 1 | One machine: store, C core, MCP. One session lays a walk and another pulls it | `pull` and `route` answer from a second session; the kernel's oracles agree |
| 2 | The room: turns run with no person and lay walks as they work | Items passed per day with zero keystrokes |
| 3 | The rail, measured | Tokens to a passed check, with the rail against the off-road share |
| 4 | Two lighthouses: scoped connect, compare | Two machines differ on a topic and `compare` shows where |
| 5 | A research room: stations are pieces of evidence | A known result, hidden from the agents, is predicted and scored |

**Stage 3 can fail.** If the rail does not beat off-road turns, `route` is dropped and v2 stays a store, checks
and scoped sharing. That is still worth having.

## 11. Not in v2

- A web app, or any door but MCP.
- A new permission layer.
- Cells above dimension 2.
- A rewrite of the station. v1 stays.
- Counting agreement between copies of one model as evidence.

## 12. Open

| What | The lead's lean |
| --- | --- |
| C11 or the C++ port | C11; Tardis may change this |
| Embeddings from Rust | The shared embedder service v1 already runs, over its socket, until a Rust one is measured |
| Lighthouse transport and keys | HTTP over the tailnet, and the Ed25519 identity each peer already has |
| The log's format | Fixed-width cell records and a length-prefixed link record; decided with Tardis |
| Which model families take turns first | Claude Opus and Codex, each reading the other's work |

## 13. Left to the builders

Crate layout, error types, the index's structure, test harnesses, and the build. The kernel's behaviour, the
link's fields, the nine rules and the tool names are fixed here.
