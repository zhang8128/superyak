# Superyak: the map

One page, 100 lines at most, kept true: a change to the shape of the system changes this page in the same commit.
Counted on main d330c898 and branch `v2` 7a78136e on 2026-11-20. Kept by Serenity, the Mac's ship. Andy vetoes.

## What we are building

A layer where agents that forget share the paths they took and what they found, under their owners' rules, with
homes for people. Andy, 2026-11-19: "another layer of the internet, from schools to businesses. To research."

## Up next

Someone outside Andy's ships asks a lighthouse a scoped question and gets an answer with a receipt. This is v2's
line (proposed by Serenity); the five goals in [docs/goals.md](docs/goals.md) stand unchanged.

The rail is measured by the distinct things it carried between machines, never by its trips (Tardis's lesson 26).
On 2026-11-20 it had carried 3 memories.

## The parts

| Layer | Part | State |
| --- | --- | --- |
| The room: a turn that forgets, judged by a frozen check | `v2/crates` (Rust, 37,104 lines), branch `v2` | Works on one machine. Not on main. Talks to no other machine |
| Memory outside the room | `engram/` (Python, 60,144 lines) | Live on every machine |
| The graph | `engram/ncat_kernel.c` (C, 822 lines) with `engram/ncat*.py` | Live, little used. Stays C (Andy, 11-14); `tardis/ncat-cpp` stays a branch |
| Paths into roads | `engram/ncat_routes.py`, on `v2` only | Ran in one rehearsal. Parked |
| The agreement for sharing | `lighthouse/` (protocol v0.1, a TypeScript kit), `engram/lighthouse_protocol.py`, `atlas/workbench/lighthouse_wire.py` | Used by Engram's recall crossing. Kit untouched since 2026-09-11 |
| The station: where ships and people meet | `peer/` (26,886 lines) and `agent/` (9,516) | Live on the Pi: nine `superyak-*` services running there on 2026-11-20, by `systemctl --user list-units`. Its own API for rooms; `peer/superyak_peer/crossing.py` carries the protocol's recall and read frames between peers |
| Teams of builders | `team/` (9,955 lines) | Live on the Mac |
| Evidence for research | `atlas/` (8,334 lines) | Last touched 2026-10-27 |
| Frames | Outside this repository | Not connected to anything here |
| Lab | `tuning/`, `deploy/`, `research_tasks/`, `research_poc/` | Untouched since 2026-09-13. They move under `lab/` |
| Support, not a layer | `docs/` (specs, plans, reports), `scripts/` (hooks, measures), `tests/`, `.github/` (CI), `.superyak/` (checklists), `.superpowers/` | In use |

## How the parts talk

1. Protocol v0.1, as memories only: Engram's recall crosses machines in signed `recall` and `read` frames that the
   peer carries to a publisher's lighthouse daemon.
2. The crossing answers two kinds of request and no others, `recall` and `read`. The protocol's Claim is made and
   checked in the TypeScript kit and in Atlas (`atlas/workbench/lighthouse.py`), but no crossing carries one. Rooms
   go by the station's own API.
3. The room in `v2`: one machine, standard input and output.

One word, three things: "lighthouse" is the protocol kit, Engram's publisher, and the Pi's peer service
(`superyak-lighthouse`).

## Who holds what

- Rio Grande (the Pi): the station, merges, deploys.
- Tardis: the kernel and store, federation, the public route, CI, and the visitor's view.
- Serenity (the Mac): the room, memory, this map, and trains (the law names Rio Grande and Serenity as the two that merge).
- Andy: the law, admissions and direction.

## Rules

None of these is checked by a test yet. The plan that makes 1, 3 and 4 into checks is
[docs/superpowers/specs/2026-11-20-organizing-for-size-design.md](docs/superpowers/specs/2026-11-20-organizing-for-size-design.md).
Rules 2 and 6 stay on trust, and 5 is each ship's to do and report in its reflect.

1. This page stays under 100 lines.
2. State is overwritten and short. Logs are appended, and no session reads a log at its start.
3. What crosses machines speaks the protocol, and CI checks it.
4. Lab code lives apart from the product, and the product never imports it.
5. Branches and worktrees that are merged or abandoned are removed each week.
6. Reader rounds are for safety code and wire formats. Elsewhere one read, then follow-ups on the board.

## Decided on 2026-11-20

None of these is law, and Andy can veto each. Rio Grande leads the ships (Andy, 10-27; revision 2's section 8).

1. Proposed by Serenity under section 8: the August protocol is the one agreement. Its first new use is a walk
   sealed as a Claim.
2. Proposed by Serenity under section 8: the four lab folders move under `lab/`. Nothing is deleted.
3. Andy's word, 11-14 at the Pi's terminal: the n-category kernel stays C, new native code is Rust, and C++ is only
   for CUDA or HPC. `tardis/ncat-cpp` stays a branch unless he says otherwise. For the sheaf, his later word at the
   Mac on 11-20 allows "some flavor of c or rust". (His 11-07 request for C++ on issue #2 came before both.)
4. Tardis's branches merge in trains under section 2, on Andy's 10-27 word, and Defiant's on his 11-09 word. Law
   revision 2's draft (layer 263d19b8) writes both into section 2 for him to sign.

## Where the detail is

- The law: `station_instructions`, with its reviewed text in [docs/station-law.md](docs/station-law.md).
- Procedures for Andy's ships: [CLAUDE.md](CLAUDE.md). Checklists: [docs/checklists.md](docs/checklists.md).
- History: [HANDOFF.md](HANDOFF.md) stops at 2026-10-15. Its notes on the station's units, its backups and the
  wormhole still describe what runs.
