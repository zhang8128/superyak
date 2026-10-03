# Team mode self-review plan

# Team mode self-review (2026-10-03)

## Goal
Review Superyak team mode end to end, using this team as the test case. Find coordination friction and propose concrete improvements. Design communication channels for Superyak engram: traditional ones (direct messages, topic channels, broadcasts) plus lighthouses. Read-only: the output is documents, not code changes.

## Constraints
- **Memory:** about 6 GB free. Don't run the full engram test suite. If you must run tests, run one targeted file and tell the others first. No embedder, Godot or parallel heavy processes (see the machine-memory-limits memory).
- Slack is off for this repo, so coordination runs through the local transcript only. Note this as an observation too.
- Data sovereignty and consent are hard requirements for anything that crosses machines or communities (the tribal partners memory).

## Tasks
| # | Owner | Angle | Output |
|---|---|---|---|
| A | Codex (sol) | **Correctness and failure modes.** Read `team/superyak_team/` deeply: the daemon, worker lifecycle, message delivery, worktrees, the key store, MCP tool surface and prompts. Find bugs, races, lost-message paths and unclear contracts. | A findings list ranked by severity, with file:line references |
| B | Claude | **Dogfooding and coordination ergonomics.** Watch how this very team works (messages, status, plan, transcript). Compare the docs (`docs/team-mode.md`, skills) with actual behavior. Find where the lead or workers lose context or block, and what would make coordination smoother. | Friction log plus ranked improvements |
| C | Claude | **Engram communication channels.** Survey what exists: engram sharing (`sharing.py`, `share` tools, `group:` scopes), `federation.py`, `lighthouse_*`, `atlas/docs/lighthouse.md`. Design a layered channel model: traditional channels (DMs, topic channels, broadcasts) alongside lighthouses (slow, durable, curated beacons), and how team mode would use it. | Design doc |
| D | Claude | **Adversary and integrator.** Challenge A–C's findings, and check proposals against the vision memories (lighthouse as civilization, platform not rule-maker, copy the principle not the mechanism). Look for the smallest change set with the biggest effect, then write the final synthesis. | Synthesis: top 5 changes, an explicit not-now list and open questions for Kairos |

## Coordination
- Talk to each other directly. C and A should exchange findings on the message and delivery mechanics.
- D starts by reading; join the others once they have early findings.
- Ask the lead if you're blocked. Send DONE with a summary and the path of your document.

## Risks
- Overlap between A and B (B covers experience, A covers mechanism).
- Channel design drifting into grand architecture (D keeps it grounded).

