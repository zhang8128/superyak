# v2 stage 2, part 1: the pilot

Serenity, 2026-11-15 (UTC). Part 1 of `docs/superpowers/specs/2026-11-15-v2-stage-2-experiment.md`, run after
part 0's report (`docs/reports/2026-11-15-v2-stage-2-part-0.md`) was pushed.

**Twenty-one turns, twenty-one usable observations, twenty-one passed verified.** The instrument worked on
live turns: every record's parts add up, every token total is whole, and nothing written down at the block's
start had changed at its end.

**By the rule fixed before the pilot, part 3 is not affordable in the form it was designed.** The same turn
differs from itself too much at one of the three items. The rule sizes the experiment on the largest of the
three spreads. It gives 481 scored items, and part 3 is not run above 40.

**Long commands go with that spread.** The room records when each step was seen and when its result came.
At that item, three of the five turns held steps of more than a minute, and one step took 601 seconds. What
those commands were is not in the record.

## What was run

- **The room program:** `yak` built from ab446b99, SHA-256 5d7c9e74..., the same bytes the three replays of
  part 0 ran. **The workers:** Claude Code 2.1.325 as `claude:opus`, codex-cli 0.163.0 as
  `codex:gpt-6.1-sol`. **The machine:** macOS 27.0.0 on arm64.
- **The items:** the three of the first run with model workers, each based on 453c8b6b, the commit they
  were based on then. That is older than the room program that ran them. Each is judged by the check frozen
  for it at that base; the data file names each check's blob and each item's wrong commit.
- **The limits in force:** 20 minutes a turn, a lease of 30 minutes, one turn at a time, and for each room
  a day's ceiling of one turn, which is how a room runs one turn and no second attempt.
- **The turns:** the 21 that `v2/probes/pilot/pilot.sh` writes down before the first. Each is one run of
  `turn.sh`: a room of its own, a new copy of the items' repository, one item, the worker that may take it,
  one turn, nothing offered. Every turn but the memory test's two without it had a first line of its own.
- **From 10:58:02 to 12:14:46 UTC,** 4,604 seconds. The turns' active seconds add up to 3,738. The other
  866 are each turn's repository being copied, its room made and its check frozen, five second looks by
  the room (88 seconds), and what the scripts write down.
- **Nothing else of the lead's ran on the machine.** Its load average at the start of a turn was between
  5.91 and 25.95. What made it so is not measured; each check builds the room program, and another program
  of the machine's owner was running.
- **Every record is in** `docs/reports/2026-11-15-v2-stage-2-pilot-turns.json`, as the room printed it. For
  each step it has the tool, whether the step went well, and the milliseconds to its being seen and to its
  result; for each turn, the load before and after. The tables below are made from the records by
  `v2/probes/pilot/records.py`, and the step table from that file.

## The fifteen

Each item five times, one of each and then round again. Active seconds are the deciding outcome: a turn's
sandbox, its worker, the room's commit for it, bringing that in, and its check.

| Item | Worker | Passed | Active s of each turn, in order | Typical s | Spread | Spread of the worker's seconds alone |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| A wrong commit that is not a commit is refused | claude:opus | 5 of 5 | 141, 164, 135, 135, 147 | 144 | 0.080 | 0.071 |
| A title that is empty, of several lines or too long is refused | codex:gpt-6.1-sol | 5 of 5 | 69, 82, 66, 92, 94 | 80 | 0.165 | 0.215 |
| A check that could never be frozen is refused | claude:opus | 5 of 5 | 857, 314, 179, 123, 331 | 288 | 0.735 | 0.793 |

"Typical" is the geometric mean. "Spread" is the standard deviation of the logarithms of the five, with 4
in the divisor. A spread of 0.08 says a turn is usually within about 8% of the typical one; 0.735 says a
factor of two either way is ordinary.

- **A check took 16.2 to 24.7 seconds,** 17.7 on average over all 21 turns. It is inside the active
  seconds, and moves with how busy the machine is.
- **Making a sandbox took about a second,** and the room's commit for a worker and bringing it in less than
  a second each.
- **Five turns were looked at a second time by the room** (one in five, by its own draw). Each passed again.

## What goes with the third item's spread

The room keeps, for every step, when it was seen and when its result came. It keeps no command's text.

| Turn | Item | Worker's s | Steps | Steps over a minute | Longest step, s |
| ---: | --- | ---: | ---: | ---: | ---: |
| 9 | check that cannot be frozen | 837 | 20 | 3 | 601 |
| 12 | check that cannot be frozen | 294 | 15 | 3 | 75 |
| 15 | check that cannot be frozen | 158 | 16 | 0 | 23 |
| 18 | check that cannot be frozen | 103 | 10 | 0 | 23 |
| 21 | check that cannot be frozen | 311 | 15 | 3 | 78 |

- **At the other two items no step of the fifteen ran over a minute.** Their longest steps were 25 to 29
  seconds (the wrong commit) and 15 to 21 (the title).
- **Every step of over a minute was a shell command, and each is marked as having gone well.** In the
  three long turns they add up to 739, 208 and 215 seconds.
- **601 seconds is ten minutes and a second.** Ten minutes is the longest this worker's program lets one
  command run, by the lead's reading of its settings. That suggests the command was ended and did not
  finish. The record does not show that.
- **What the commands were is not in the record,** on purpose. The first run with model workers found the
  same shape at this same item and named it from a separate measurement: the worker ran two crates' whole
  tests in its sandbox, where two of the clock's tests could not end. The items' base is from before those
  tests were given a stop of their own. That this is what happened here is a guess that fits, not a
  finding.
- **Long steps go with most of the difference between these five turns.** The record does not separate
  finding the fix from running or waiting for commands. The same five turns' tokens differ less than their
  seconds, a spread of 0.22, which fits either.

## The size the rule gives

The rule, fixed in the experiment's text before any pilot turn:

`n = (1.96 + 0.84)^2 * (t^2 + 2 * c^2) / 0.1625^2`, with `c` the largest of the pilot's three spreads and
`t` taken to be equal to `c`.

| `c` | Which | `n` |
| ---: | --- | ---: |
| 0.735 | the largest: the rule's | 481 |
| 0.165 | the middle one | 25 |
| 0.080 | the smallest | 6, so the floor of 20 |

- **481 is above 40, so part 3 is not run in this form.** The text's own words for this: "not affordable at
  this noise", with the question open. It is not an answer about notes or walks.
- **The two smaller spreads give 20 and 25 under the same planning assumptions.** The largest is the one
  the rule uses, and it is over the ceiling. The rule is not read again here because of how it came out.
- **Tokens would not have been affordable either.** They were not the deciding outcome, and all 21 totals
  happened to be whole. Their spreads are 0.31, 0.30 and 0.22, and the rule at the largest gives 84.
- Sizes are worked from the spreads before they are rounded.

## The memory test

One item, one worker, five turns back to back: one thrown away, two without a first line of their own, two
with it. The later turn of each pair less the earlier:

| Pair | Fresh input | Written to memory | Read from memory | Output | Active s | Steps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Without the line | 0 | -2,274 | -7,895 | -554 | -48.4 | 10, then 9 |
| With the line | -8 | -4,583 | -160,369 | -1,536 | -28.4 | 12, then 8 |

- **This shows what was seen, and nothing about the line.** In both pairs the later turn was faster and
  read less, and took fewer steps. The experiment's text said beforehand that one pair of each kind could
  not take the line apart from everything else that differs between two turns, and it did not.
- **The line stays,** as decided before the pilot.
- **Every turn writes 26,000 to 38,000 tokens to memory and reads 260,000 to 620,000,** with 18 to 36 of
  fresh input, for Claude. For Codex: 17,000 to 27,000 fresh, none written, 210,000 to 400,000 read.

## What a turn's memory had to go on

The time from the end of a worker's last clock to the start of its next was 0 to 134 seconds for Claude,
and 177 to 1,113 for Codex, which waited out both of Claude's turns each round. Codex's longest wait was
behind the 857-second turn. The program itself had been idle for longer than that each
time, by the check before and the making of the turn after. Nothing checks that a program's memory stays
warm, and nothing here says whether it did. Every measured turn is kept.

## What the pilot does not say

- **How turns differ on other work.** Three small items of one repository, all from one command of it.
- **How a run differs from itself.** A run is up to three turns; every turn here passed at the first.
- **What an offer does to any of this.** Nothing was offered.
- **How much the gain from an offer differs from item to item.** The rule guesses it equal to `c`.
- **What the third item's long commands were.** Tests that cannot end in a sandbox would fit. Not shown.
- **Where an offer would help.** Nothing was offered, so nothing here says that long commands are what a
  note or a walk would spare a later turn.
- **Anything about Linux, or about a second machine.**

## What follows

The experiment's text allows for this outcome: "The experiment stopped at part 0, 1 or 2, or was not
affordable: reported as that. The question stays open and the design changes." What the design changes to
is not decided in this report. It goes to a fresh reader of the other model family, and to the person whose
project this is, with what the pilot shows:

1. **The three spreads are far apart.** The two smaller give 20 and 25 under the planning assumptions; the
   largest controls the rule and is over the ceiling. What a real set of scored items would need depends on
   how many of them are like the third, and three items cannot say.
2. **Long commands go with the third item's spread, and a known fault of the repository would produce
   them.** A worker that runs the tests in its sandbox can wait ten minutes on tests that cannot end there:
   the first run found that and reproduced it apart from any worker. That fault is worth repairing on that
   evidence, whatever these commands were. Repairing it also changes the work an offer would be tried on,
   and may remove one way an offer could have helped. A later result has to say so.
3. **A changed design needs a pilot of its own, once.** A rule fitted to these fifteen turns after seeing
   them is a rule chosen by its result. Fresh items found in order, a base, checks and limits fixed
   beforehand, a spread measured on them afresh and the same rule applied to it, would not be. If that
   pilot is not affordable either, that is reported as it is, and not followed by another.

The reader of this report, of the other model family, recomputed its numbers and held the same: close
this pilot on the rule as fixed, repair the fault that can be reproduced, and at most one follow-up pilot
frozen beforehand. It would not accept a different outcome chosen now, the long turn cut or dropped, or
the rule read on the middle spread because that gives 25.

No turn of part 2 or part 3 is run until that is settled.
