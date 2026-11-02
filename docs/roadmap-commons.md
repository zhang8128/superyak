# Roadmap: a commons that learns

Rio Grande and Tardis, 2026-11-02, from Andy's words that day. A plan to test and revise, not a rule.

## Why

Andy: "nothing is ever bug free… Rigid rules are brittle… Look to the experts… create a roadmap. test and try again."
Also: our rules are conventions, like driving on the right, kept because agreeing is easier, not because they're true.
The goal is "a shitty AI HOA that can be updated by the members. Or forked/left behind", not one immune to problems.
And: "simplify from code to lego blocks… reference a tested millenium falcon instead of each individual atom."

What we see now, measured this week:
- The repo's 9 checklists never fired on the Pi until 2026-11-02 (`checklists list`: "never fired"). We kept writing
  lessons into lists that didn't reach the sessions.
- The rail, overarching goal 1, stalled for a week. The lessons room isn't open, and the lessons were drafted 10-27.
- docs/checklists.md runs to about 680 lines. One sentence from Andy ("the lessons room is administration") touched
  CLAUDE.md, two lists, three docs and a test of pinned wording.
- A merge sitting is about 12 hand steps. Reviews run three to five rounds with mutant tables, even for small changes.
- For twelve hours, ten-minute ticks repeated one blocker until the week's usage ran out.

## What the experts say

- **John Gall** (Systemantics, Gall's Law): a complex system that works has evolved from a simple system that
  worked; one designed complex from scratch doesn't work. For us: grow by small working steps, and delete what doesn't
  work.
- **Elinor Ostrom** (Governing the Commons): commons last when the people a rule binds can change it, rules fit local
  conditions, use is watched by members, sanctions are graduated, and groups nest. For us: the ships change their own
  conventions and say why; Andy keeps his veto; anyone can fork.
- **James C. Scott** (Seeing Like a State): schemes imposed for legibility fail when they crowd out practical
  know-how (mētis). For us: lessons from practice (the rail) over more written rules.
- **Nassim Taleb** (Antifragile): small, reversible, frequent experiments gain from error; improve by taking away (via
  negativa). For us: prune first, and keep each change easy to revert.
- **Atul Gawande** (The Checklist Manifesto): a good checklist is short, fires at a real pause point, holds only the
  steps people actually miss, and is tested and revised in use. It isn't a manual. For us: a list fits one screen.
- **Google SRE** (Site Reliability Engineering): 100% is the wrong reliability target; agree an error budget and
  spend effort where failure costs most. For us: accept some failures, and guard only what can't be undone.
- **Erik Hollnagel, Sidney Dekker** (Safety-II, resilience engineering): study how work actually succeeds ("work as
  done", not "work as imagined"). For us: judge a rule by what fired and what it caught, not by what the doc says.
- **Christopher Alexander** (A Pattern Language), **Doug McIlroy** (the Unix philosophy): tested patterns and small
  tools that compose. For us: assemblies, the lego Millennium Falcon, instead of atoms.
- **W. Edwards Deming** (Plan-Do-Check-Act): change something, measure it, then keep it or revert it. For us: every
  step below is an experiment with a measure.

## Principles we'll try

1. **Rules sized to risk.** The more a mistake costs a person, and the harder it is to undo, the stronger the rule.
   Reversible work is tried, measured, and reverted if it hurts. This goes for signed law too: the ships drafted
   revision 2 of section 2 in risk tiers (station layer d19aba15) for Andy to edit and sign, or not. Andy:
   "make the laws flexible to their risk".
2. **Conventions, not laws.** The ships change their own conventions (checklists, docs, review depth, their tools)
   when they cost more than they save, say why in the room, and Andy may veto. People and ships may fork or leave.
3. **Outcomes first, in layers.** Outcomes (what a person notices) sit on top, then assemblies, then bricks, then code.
   docs/assemblies.md is the map: start at an outcome, run its assembly, and go down a layer only when it fails.
4. **Use what we build, daily.** The lists fire, the lessons hook runs, lessons get laid and read.
5. **Measure, then keep or revert.** Small batches, each with its measure written down before it starts.

## Not sunk cost: what we stop or pause

- **WAL Tasks 8-9 pause after Task 7.** Tasks 4-7 are harmless in rollback mode and merge as reviewed. But nobody has
  measured that reads waiting on writes slow a chat for a person (goal 2's measure is a room read under 400 ms). Build
  `make chat-probe` first. If it shows the gate matters, Tasks 8-9 resume; if it doesn't, they stay parked.
- **No new spec** unless an outcome on the map needs it.
- **No full review rounds** for low-risk changes, as the law draft's tiers say.

## Roadmap (each step: the measure, and what reverting means)

0. **Ships remember and share: the point.** Andy, 2026-11-02: "the whole point of this is to use the lighthouse
   system with the shared engrams and shared memory", and "engram should be able to be run with very little memory
   in theory… rarely accessed paths could be on disk". Give Rio Grande its Engram (docs/assemblies.md, "Give a ship its
   memory"), then Tardis, then share a work-lane memory between them through a lighthouse. Measure: one ship's session
   recalls what the other shared, and a machine at rest holds almost no Engram memory. Revert: the runtime is opt-in.
0b. **The rail runs (today).** Open the rail (docs/assemblies.md). Measure: one of Tardis's lessons fires in Rio
   Grande's session on a real error within an hour. Revert: open a new room.
1. **Probes for the outcomes.** `make chat-probe` (goal 2). The rail's receipts and segments already exist (goal 1).
   Measure: each outcome on the map has a number. Revert: nothing to revert.
2. **Two assemblies.** `make train` and `make merge-sitting`. Measure: the next merge is two commands and their
   reports. Revert: the hand steps are still in docs.
3. **Welcome a person (goal 4).** Walk "Welcome a person" as a newcomer would, fix what trips them, and invite one
   person Andy names. Measure: someone outside the ships docks or replies.
4. **Prune by evidence.** After a week of firing, retire checklist items that never fired or caught anything, keep
   each list to one screen, and cut docs/checklists.md to the why and the cites of kept items. Measure: half the lines,
   with no rise in reverts or corrections. Revert: git.
5. **An error budget.** A revert is allowed. Count reverts each week in Reflect, and tighten only where the count is
   over budget.

Each week's Reflect reviews this roadmap and the map: what moved, what stalled, what we changed or reverted.
