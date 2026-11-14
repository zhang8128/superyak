# Rail replay: a first measurement

Serenity, 2026-11-14. Run while the v2 spec was being argued, to put one number under its section 2. It is a
first instrument on a small sample, and nothing here is a result.

## What was run

`scripts/experiments/rail_replay.py` over the Claude Code transcripts for this repository on one Mac.

- **Unit:** a turn, meaning what the agent touched between one prompt and the next. A ship's session runs for
  days and holds many tasks, so a whole session is not one walk.
- **A walk:** the repo files a turn read, edited, or named in a shell command, in order. Most reading in these
  sessions happens in the shell: 7,102 shell calls against 2,393 file-tool calls. (That count came from a separate
  one-off tally, not from this script.)
- **Sample:** 232 transcripts gave 745 turns that touched a repo file, and 308 that touched three or more.
- **Split:** by time. The earlier 215 turns lay the roads; the later 93 are scored.
- **Question at each step:** which file does this turn open next that it has not opened yet?
- **It prints rates only.** No prompt, path or file content leaves the machine.

## What came back

The strict target is the exact next file. Half the time (52%) that file was one no earlier turn had touched,
which caps every predictor.

| Predictor | First guess right | In the top 10 |
| --- | ---: | ---: |
| The most-opened files | 0.4% | 8.8% |
| Files in the same folder | 2.3% | 11.7% |
| Turns with a similar prompt | 0.4% | 10.8% |
| Files used in the same turn as this one, in any order | 4.8% | 14.2% |
| The road: what came next after this file | 3.4% | 8.6% |
| The road and the similar prompts together | 3.9% | 13.1% |

The looser target is any file the turn goes on to open.

| Predictor | First guess | Top 10 | First guess, timer turns left out |
| --- | ---: | ---: | ---: |
| The most-opened files | 2.0% | 34.5% | 2.1% |
| Turns with a similar prompt | 1.1% | 39.5% | 7.9% |
| Files used in the same turn, in any order | 9.7% | 34.6% | 7.5% |
| The road: what came next | 8.4% | 23.9% | 7.9% |
| The road and the similar prompts together | 13.6% | 39.0% | 14.2% |

Timer turns all share one prompt, so the prompt says nothing about them. Leaving them out drops 146 turns and
leaves 240 scored steps.

## What it suggests

Corrected on 2026-11-14 after a cold reader checked this report against its script. The first version said place
and aim each scored 8 to 10% alone. That was wrong for the prompt on the full sample.

1. **Place and aim add, for the first guess.** On the looser target the road alone was right first 8.4% of the
   time, and 7.9% with timer turns out. The prompt alone was 1.1%, and 7.9% with timer turns out. Together they
   were 13.6% and 14.2%.
2. **The road's ten ranked guesses did worse than the ten most-opened files** (23.9% against 34.5%). These are
   ranked candidates, not hops anyone walked, so this says nothing about routes.
3. **Order did not help.** Files used together in any order matched or beat the directed road.
4. **Half the next steps are new ground.** No record of earlier turns can point at a place nobody has been.

## Its limits

- One repository, one owner, about 300 turns. The gaps between the better predictors are a handful of hits.
- A file is a coarse place. A function or a line would be a different test.
- Nothing here knows whether a turn arrived. No check's verdict is in the data.
- "Opens next" is not "was helped by". A file can be opened and be useless. Nothing here measures usefulness or
  work saved.
- A file named in a shell command counts as opened, whatever the command did. Printing a filename makes a step.
  An absolute path in a shell command, or a path after a change of directory, can be missed.
- The prompt is a poor stand-in for an aim, and timer prompts are no stand-in at all.

The spec's stage 2 is the test this is not: arms assigned by a coin, every attempt and cost counted, checks
frozen first.
