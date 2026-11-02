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

1. **Conventions, not laws.** Rio Grande and Tardis (and Serenity when back) change the ships' own conventions when
   they cost more than they save, say why in the room, and Andy may veto. People and ships may fork a list or leave.
   Signed law and people's own acts stay as they are.
2. **Guard only what can't be undone:** a person's data or a key leaving, an unfixed hole made public, admitting a
   person, the live store's switch. Everything else is reversible: try it, measure it, and revert it if it hurts.
3. **Assemblies over atoms.** A step done twice becomes one tested command, and lists point at the command.
4. **Use what we build, daily.** The lists fire, the lessons hook runs, lessons get laid and read.
5. **Measure, then keep or revert.** Small batches, each with a measure written down before it starts.

## Roadmap (each step: the measure, and what reverting means)

0. **The rail runs (today).** Open the lessons room, install the Pi's index and hook, lay Rio Grande's 24 and
   Tardis's 27. Measure: one of Tardis's lessons fires in Rio Grande's session on a real error within an hour. Revert:
   open a new room.
1. **Two assemblies (this week).** `make merge-sitting`: backup, ff, tree and history checks, restart and stop read,
   health and probes, push, and the announcement text. `make train`: scratch merges, build, suites in both modes.
   Measure: the next merge is one command plus its report, with no hand steps. Revert: the hand steps are still in
   docs.
2. **Prune by evidence.** After a week of the lists firing, `checklists report` shows each item's fired and caught
   counts. Retire items that never fired or caught anything, keep each list to one screen, and cut docs/checklists.md
   to the why and the cites of kept items. Measure: half the lines, and no rise in misses (reverts, corrections).
   Revert: git.
3. **Review in proportion to risk, within signed law.** Law section 2 still names the approver: Serenity or a fresh Pi
   reader for a Rio Grande branch, Rio Grande for a Serenity branch. What changes is the depth. Safety code (auth, a
   person's data, keys, the live store) gets the full read, mutants and each working partner's yes. Reversible code
   (tests, docs, tooling) gets one short read and no re-check rounds for nits. Measure: review hours per merge, and
   reverts. Revert: full reads for all. If the law itself proves brittle, the ships draft a revision and Andy signs
   it or doesn't.
4. **An error budget.** A revert or a bad merge is allowed. Count them each week in Reflect, and tighten only where
   the count is over budget.
5. **Easy to fork.** A ship's own lists (`~/.superyak/checklists`) and a person's own rooms already fork the
   commons. Say so plainly in the README, and make leaving cheap.

Each week's Reflect reviews this roadmap: what moved, what stalled, what we changed or reverted.
