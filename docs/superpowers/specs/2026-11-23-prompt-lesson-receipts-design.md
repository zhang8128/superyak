# Receipts for lessons shown at a prompt, written later in the same session (goals.md T5, goal 1)

Draft 2, 2026-11-23 (draft 1 at 49428768). Tardis, drafted at Rio Grande's ask (all hands 7d7b2e4d). It's a change to the rail's specs, so
under station law section 3 a fresh reviewer approves it in Andy's place, and Andy can veto.

## Why

**No lesson shown at a prompt is ever receipted.** So no ship can score one, and T5's helped share can't see the prompt
path at all.
- **The hook:** `agent/superyak_agent/lessons_hook.py` says "the hook writes nothing at all at a prompt".
- **The peer:** `peer/superyak_peer/lessons.py`'s `prompt_answer` reads "this peer's index file and nothing else; no
  store, no database, no write", inside its 150 ms.

**The evidence, on 11-23:**
- **Every angle receipt is from another path:** every receipt on both ships with an angle lies between 0.788 and 0.922
  rad. That's inside the session-start-and-failure bar, `R_MAX` = acos(0.60) = 0.927, and outside the prompt bar,
  `R_PROMPT` = acos(0.75) = 0.723 (Rio Grande, d8adc1cd).
- **So the helped share measures only one kind of path:** it covers the paths that ask with the cwd and branch (3 of 47
  on Tardis, 1 of 4 scored on the Pi), never the turn's own words.
- **A correction to the case first offered for this spec:** Tardis named lesson `4de98e28-d37c4938` as a prompt-shown
  lesson that helped and had no receipt (all hands a6022bbe). It is Tardis's **own** lesson, shown under "Your own
  lessons". Own lessons never carry a receipt on any path (own-lessons spec), so it isn't a case of this gap. No
  receipt-less, prompt-shown lesson from another ship that helped is known yet. The pinned case below is constructed.
- **Own lessons are a second, separate gap:** they're never scored, and this spec doesn't change that.

## Constraints (Rio Grande's, 7d7b2e4d)

1. **The same session that saw the prompt writes the receipt,** at its next write point, from that session's own
   record.
2. **Never at a later session's start.** A new session can't honestly score what an older one saw. That's also why
   Rio Grande left 14 receipts unscored.
3. **The prompt path stays write-free,** with its 150 ms unchanged.

## How big the gap is, measured before the design

On Tardis, every session transcript in this project that shows a lesson (one so far, 11-22 to 11-23) was read for the
hook's own id lines, by the hook event of the record that holds them. Distinct lessons per session:
- **At a prompt:** 6, of which **5 are Tardis's own** and **1 is another ship's** (Rio Grande's).
- **At a failed command:** 25, of which 24 are other ships' and 1 is Tardis's own.

So on Tardis **this spec adds about one scoreable receipt a session.** The prompt path shows mostly a ship's own
lessons, which never carry a receipt (own-lessons spec) and which this spec leaves alone. The Pi's count may differ,
and it's asked for before any build.

## What the hook already knows

At every write event, the hook reads its own `Lesson <id> from <ship>` lines back from the session's transcript
(`transcript_ids`, within `_hook_texts`). **Each such record names the hook event that wrote it:** a prompt's added
context is an attachment with `hookEvent` = `UserPromptSubmit`. That's on 2.1.312 in the hook's tests, and on 2.1.330
in this session's own transcript.

So at a later write event in the same session, **the lessons shown at a prompt are the ids on lines inside
`UserPromptSubmit` attachments, from a ship other than the asking one,** less the record's `shown` (a lesson the start
or failure path already receipted and a prompt re-showed after a compaction).

**Draft 1's rule was wrong, and a smoke run showed it.** Draft 1 took every transcript id the record's `shown` didn't
hold. The hold path (`lessons_hold`) shows lessons in a deny and receipts them through its own query, but records them
in the holds record, not in `shown`. On the hook's own test rail, with the real hook and hold code, draft 1's rule
listed a held lesson from another ship as prompt-shown, which would have receipted it twice. The rule above, keyed on
the record's event, leaves it out.

## The change

- **(1) At a failed command, the same session's next write point,** the hook adds `prompt_shown` to its request. That
  list is the prompt-shown ids above, cut to `SEEN_MAX` and in transcript order.
- **(2) The peer writes one receipt for each id it's sent,** with a new column `path = 'prompt'`. **The hook, not the
  peer, keeps each id once a session:** the receipts table has no session column, so the peer can't tell sessions
  apart. The hook adds the ids it sent to a `prompt_receipted` list in its session record, under `_record`'s lock, and
  never sends one twice. A record that can't be written sends nothing, as now. Today's receipts get `path = 'start'` or `'failure'`; those from before this change keep NULL,
  meaning unknown.
  - `angle` is NULL for a prompt receipt, since the prompt answer's match isn't kept, and NULL already means "words".
    So **`path` is what tells a prompt receipt apart.**
  - `place` is the failure event's, as now.
- **(3) The failure answer prints each new prompt receipt's line,** the same `receipt_line` the hook prints today, with
  "shown at a prompt" on it. So the session can score it with `make lesson-outcome` while it still remembers the turn.
- **(4) A compacted session's start is not a write point** for prompt receipts. After a compaction the session holds a
  summary, not the turn, and so it can't honestly score. That's the same reason as constraint 2. The prompt ids from
  before the compaction are left unreceipted.
- **(5) `make lesson-outcomes`** adds a line for `path = 'prompt'`, beside the match-kind lines (train 1154), with
  scored and unscored apart.

**An option, for the reviewer to keep or cut:** a `PreCompact` or `SessionEnd` hook could write receipts for the
prompt ids still unreceipted, marked `scoreable = 0`. No session could score them, so they'd measure only how many
lessons the prompt path shows, and they'd be reported apart from the helped share. That adds an unscored count that
isn't a ship's neglect. Both events exist in Claude Code 2.1.330.

## Tests, said before the code

- **The pinned case, constructed:** a session shows another ship's lesson at a prompt, then has a failed command. The
  failure answer holds a prompt receipt for that lesson, and `lesson-outcomes` counts it under the prompt path.
- **Nothing at the prompt:** the prompt path writes no row, and its timing tests still pass.
- **One receipt only:** a second failure in the same session writes no second receipt for the same lesson.
- **Not across sessions:** a new session's start writes no prompt receipt for an older session's ids.
- **Not after a compaction:** a compact start writes none, and the ids from before it stay unreceipted.
- **Own lessons:** the asking ship's own lessons, shown at a prompt, never get a receipt.
- **Failure receipts unchanged:** the receipts a failure writes for its own answer are as before.

## Open, for the reviewer to check against the code

1. **Answered by the smoke run:** the hold path doesn't record in `shown`, so the rule keys on the record's hook event
   instead.
2. **Is the transcript read-back exact enough** to attribute a lesson to a prompt? Or does a lesson shown at a failure
   and then re-shown at a prompt need care?
3. **`SEEN_MAX`:** is it the right cut for `prompt_shown`?
4. **The `path` column:** should it be added the way `place` was (receipt-place spec, 8d), with a CHECK over `'start'`,
   `'failure'` and `'prompt'`?

## What this can't fix, said now

- **On Tardis, it's about one receipt a session.** If the Pi's count is as small, the build may not be worth it, and
  T5 can say plainly that the prompt path shows mostly own lessons.
- **A session with no failed command never writes its prompt receipts.** The prompt path stays under-measured, by how
  often sessions fail a command, and the option above only counts it.
- **A prompt receipt is written after the turn.** So its outcome is the session's later judgement, not its judgement at
  the moment.
