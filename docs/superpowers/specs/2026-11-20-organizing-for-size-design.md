# Organizing Superyak for its size: design

Draft 2, 2026-11-20, by Serenity. The map it builds on is [MAP.md](../../../MAP.md). A fresh reader read draft 1 and
said "approve with named changes"; its six are made here and in the map.

## Why

Andy, 2026-11-19: "can we organize more effectively. Ai coding seems to run into these problems when big", then
"plan this out more", with a pointer to `github.com/zjshen14/agy-hq` as something to learn from.

What had gone wrong, counted on 2026-11-19:

- **No current map.** `HANDOFF.md` said "resume here" and stopped on 2026-10-15. A session that read it built
  beside parts it did not know existed.
- **Writing outruns pruning.** 2,341 commits on main since 2026-10-01, 207 worktrees on the Mac and 106 on the Pi,
  233 branches on the remote, and four folders untouched since September that still looked current.
- **Structure follows who talks.** `peer`, `agent` and `team` name each other; `engram`, `lighthouse` and `atlas`
  name each other; the room in `v2` talks to no other part.
- **Reviews check the diff, not the shape.** 98 specs and 107 plans, each read; nothing asked whether a part
  should exist or already did.

## The aim

Any session on any machine knows the whole from one page, and cannot silently change the shape.

## What agy-hq does (read at its main decd901 on 2026-11-19; nothing of it was run)

A personal agent system in Go by one author: 200 commits in 13 days, about 80,800 lines of code and 29,300 of
tests. What bears on our problem:

1. Every rule names the check that enforces it. One command and CI run them all.
2. One index of every document, each with a status. A check fails when a document is not in it or a link is dead.
3. Four kinds of document kept apart and numbered: product (with 38 user journeys), design, decisions (six, about
   2 KB each), research.
4. The user journeys are the acceptance tests.
5. Hard caps on what a session is given at its start, enforced in code.
6. Public engine and private data are two repositories, with a scanner between them.
7. A list of paths that need extra review; everything else moves fast.
8. Every agent turn ends with a clean, pushed tree.

Not copied: its design documents (642 KB in 27 files). Its own audit found its start-up context five times over
its cap and a line cap gamed with long lines, so a cap needs lines and bytes both.

## What exists already, so nothing is built twice

- A pre-push scanner with a private terms file and tests (`scripts/git-hooks/pre-push`).
- CI with eight jobs, lighthouse interoperability among them, and `make check`.
- `docs/goals.md`, the reflect in `docs/checklists.md`, and `docs/components.md` for earlier work.
- The lighthouse protocol v0.1 with a conformance kit.
- The station law and the work board.
- No index of documents, no decisions folder, and no check on the shape.

## Approaches

- **A. Documents only.** Write the map and the conventions and trust sessions to follow them. This is what the
  handoff file, the goals and the checklists were; the handoff went stale in five weeks. Not chosen.
- **B. Checks first, with a ratchet.** Every rule gets a check. Where today's tree already breaks a rule, the
  check records today's count and refuses any increase. **Chosen:** it lands on a live system without a halt.
- **C. A clean repository** holding only the product path, with this one as the lab. The cleanest result, but the
  station is live and the move is all at once. To look at again after phase 4.

## The plan, in phases. Each ends in something a check can show

**Phase 0: make the whole visible (documents and a sweep; no product code)**

1. `MAP.md` at the top of the repository. `HANDOFF.md` is marked as history. `CLAUDE.md` opens by pointing at the
   map. (This branch.)
2. `docs/README.md`: an index of every spec, plan, report and decision with one line and a status (proposed,
   approved, built, withdrawn, history). A script lists them, a worker drafts the statuses, and a sample is
   checked against the code.
3. `docs/decisions/`: one page each, 40 lines at most, for decisions already made and for the open ones.
4. State apart from log: each lead keeps a state file of 60 lines at most, overwritten. Logs stay append-only,
   and no session reads one at its start.
5. A sweep: every worktree and branch already merged into main or `v2` is removed. Nothing unmerged is removed;
   the rest are listed by owner.

**Phase 1: the rules become checks (`make check-shape`, in CI and before a push)**

| Check | What it holds |
| --- | --- |
| S1 the map | At most 100 lines and 8 KB; every top-level folder of main is named in the parts table (the map names all sixteen today); a new folder that the table does not name fails |
| S2 documents | Every spec, plan, report and decision is in the index with a status; links resolve |
| S3 the start | The map's cap is S1's. `CLAUDE.md` is held by a ratchet at its size on this branch's head, 146 lines and 13,042 bytes by `wc`: it may shrink and may not grow |
| S4 boundaries | Which part may name which; today's counts are the ratchet; a new crossing needs a decision page |
| S5 private terms | Local, not in CI: each ship's reflect runs a command that says whether the pre-push scanner is installed in its checkout, and posts the answer. CI cannot see another machine's hooks |
| S6 loose ends | Each reflect prints its ship's count of branches and worktrees; reported, not failing |

**Phase 2: journeys as acceptance.** `docs/journeys.md`, six to eight, each with one end-to-end test: two people
pair and exchange a message; a ship is mentioned and answers; a recall crosses a lighthouse and comes back with a
receipt; a turn in the room is judged by its frozen check; a walk is recorded and offered to a later turn; an
agent from outside asks a lighthouse a scoped question. The last has no test today, and it is goal 4.

**Phase 3: one agreement.** Memories already cross in protocol v0.1 frames. What does not: the protocol's Claim
and Witness, and anything of the room. The first step is Tardis's: one walk sealed as a Claim, checked with the
kit's command line, evaluated on a second clone, with no network. The conformance kit then runs in CI against
each implementation.

**Phase 4: lab apart.** `tuning/`, `deploy/`, `research_tasks/` and `research_poc/` move under `lab/` and leave
the default checks. Nothing is deleted. The product never names them (S4).

## How ships work under it

- **Owners by path:** Rio Grande `peer/`, `agent/` and deploys; Tardis the kernel, the store, federation and CI;
  Serenity `v2/`, `engram/` memory, the map and the index.
- **Paths where reader rounds stay:** the jail (`v2/crates/turn`); signing, pairing and sign-in in `peer/`; law
  and grants in `agent/`; the permission ledger and the imprint filter in `engram/`; the protocol's schemas; CI
  and hooks. Elsewhere one read, then follow-ups on the board.
- **A new part or a new wire format:** a research note, a design, an approval, then code. Everything else goes
  straight to a branch.
- **A session ends with its work pushed or its worktree removed.**
- **"Up next" on the map** takes the place of goals dated by the week.

## What this design does not do

No rewrite, no new language, no change to the law, and no new permission layer. Section 2 of the law still
governs every merge here.

## Open, and not blocking

- The size caps in S1 and S3 are guesses until they have been run against a month of real changes.
- S4's first allow-list is today's graph, which includes crossings nobody chose.
- Three of the map's six rules get no failing check here. Rule 2 (state apart from logs) and rule 6 (where reader
  rounds stay) rest on trust. Rule 5 (removing merged branches and worktrees) is each ship's own weekly act, with
  S6 printing the count in its reflect so that a ship that stops doing it is seen.
