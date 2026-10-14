# Should the hook take the watch by itself? (roadmap 2.1, evidence for Andy)

Serenity, 2026-10-14, from a writable Mac session that ran as a 10-minute loop all day.

## The question

Today a session takes the watch by choice: `station_watch writable=true`. While it holds the watch, the station
defers its ship's watcher's read-only runs, and the session answers those mentions itself. Should the hook declare
the watch automatically for writable sessions?

## What is already settled

- A lapsed lease hands its mentions back to the watcher, which answers read-only and says so. This is tested:
  `peer/tests/test_ship_agent.py::test_a_deferred_mention_runs_once_the_watch_ends`, with the endings 'declared off',
  'session end', 'lease ran out' and 'bound'.
- Every call the session makes renews the lease (20 minutes by default, at most 120), and every deferral ends within
  120 minutes even under a watch that stays on.
- The agent README now documents taking the watch ("Taking the watch").

## What today's loop showed

- **The lease never lapsed.** This session declared the watch once, with 30 minutes, and every prompt renewed it. The
  loop prompted at least every 10 minutes, so the lease never ran out.
- **Nothing was deferred, because nothing mentioned Serenity.** In the station's whole history, the mentions of
  Serenity are four messages, all from acceptance tests or earlier. Law section 7 ("write ship names without the at
  sign unless you mean to start that ship's run") keeps ship-to-ship mentions rare. The watch protects against crossed
  rulings, a read-only answer racing a working session, and today there was nothing to race.
- **Most sessions don't take the watch.** The ship directory listed 11 Serenity sessions on the Mac, and only this
  loop's was on watch. Most of the others were old or idle.

## Options

| | What | Cost if a writable session isn't reading the room |
|---|---|---|
| A | Keep it the session's choice (today), now documented | none: only sessions that chose to answer get the mentions |
| B | The hook declares it for sessions that show room messages (`--hook`) in write mode, with the 20-minute lease renewed per prompt | a mention waits until that session goes idle plus at most 20 minutes, then the watcher answers |
| C | The hook declares it for every writable session | a mention can wait up to the 120-minute bound for a session that never sees room messages |

## Recommendation

**A for now.** The measured need is near zero (no mentions to defer today), and A carries no delay risk. If people
start mentioning ships more, **B** is the safe form: only sessions that see room messages hold the watch, and an idle
session lets go within 20 minutes. **C** isn't recommended, because it hands mentions to sessions that can't see them.
