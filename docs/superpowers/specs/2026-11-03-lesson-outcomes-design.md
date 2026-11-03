# Lesson outcomes: did a shown lesson help?

Rio Grande, 2026-11-03, board item `spec:rail-lesson-outcomes`. Builds on the first rail
(`docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md`, branch trail-arrows-spec): its receipts (section 5)
and repeats (section 7.1). Ties to the rail mathematics (`2026-11-03-rail-mathematics.md`, branch rail-mathematics):
weights learned from use, with a temperature where evidence is thin. Revision 1, for a fresh reviewer (station law
section 3).

## 1. Why

Today the rail knows where a lesson was shown, from its receipt, and when a seen lesson failed to stop a mistake,
from a verified repeat. It never learns whether a shown lesson helped. So the query ranks by words and angle alone,
forever. A lesson that misleads keeps showing exactly as often as one that saves an hour.

Agents learn from each other when the rail learns which lessons land. That's the rail's own why. It's also the
smallest real case of the rail mathematics' claim that use carries information meaning doesn't.

## 2. An outcome

A ship that was shown a lesson says what it did, once, against that receipt:

- `helped`: it changed what the ship did, for the better;
- `misled`: it pointed the wrong way here (wrong, stale, or about something else that looked alike);
- `unused`: it wasn't needed, or the ship didn't act on it.

**What a record holds:** its id, the time, the receipt id, and the outcome. The ship and the lesson come from the
receipt and are never arguments. **No free text**: no note, no command, no context. The table has only these columns,
with a CHECK on `outcome`, beside `lesson_receipts`, `lesson_queries` and `lesson_repeats`.

## 3. The verb

`lessons outcome <receipt id> helped|misled|unused`, run by a ship on its own peer (`make lesson-outcome RECEIPT=
OUTCOME=`).
- The ship is the calling account. The receipt must be one of its own: a receipt shown to another ship is refused.
- A receipt id is a full id, or a short form that resolves to exactly one of the ship's receipts.
- **One outcome per receipt, within 24 hours** of the receipt. A second outcome is refused, and so is a late one.
  It's honest, and it can't be farmed by repeating it.
- The answer the query gives (first rail, section 5, step 5) gains each lesson's **receipt short id** beside the
  lesson's, so the ship has what the verb needs. The prompt path writes no receipt (first rail, section 5), so a
  lesson shown at a prompt can't take an outcome; that's accepted.
- `make lesson-outcomes` lists this peer's records, newest first: ids, ship, lesson short id, outcome. No text.

Outcomes are local to each peer, like receipts and repeats. They never federate (section 6).

## 4. Ranking weighs it, in shadow first

**The estimate.** For each lesson, count the latest outcome of each ship on this peer: `h` helped and `m` misled
(`unused` counts for neither). Only the latest outcome per ship and lesson counts, so one ship shown a lesson ten
times has one voice. Take the posterior mean of a Beta(1, 1) prior: `p = (h + 1) / (h + m + 2)`. Its variance is the
lesson's temperature, as in the rail mathematics: a lesson nobody has judged sits at `p = 0.5` and ranks as today.

**The weight.** Near ranks by angle (first rail, section 5, step 2). With outcomes it ranks by an effective angle,
`θ' = θ · (1 + λ · (0.5 − p))`, with `λ = 0.5`. So a lesson that has always helped ranks as if up to 25% nearer, and
one that has always misled ranks as if up to 25% farther. Two rules bound it:
- **It reorders within `r_max`; it never widens it.** A lesson is a candidate only when its true angle is within
  `r_max`, as today. A misleading lesson can drop out when `θ'` passes `r_max`. No lesson is ever shown farther than
  today.
- **Words matches aren't reweighted.** A literal command, error or file match is evidence of its own kind.

**Shadow first** (rail commons, stage 5). Until a proposal turns it on, the query ranks as today and computes the
outcome order beside it. The query row gains `reordered` (0 or 1): whether the outcome order would have changed the
shown set or its order. `λ` and the 24-hour window go on the rail-parameters list (rail commons, principle 3), and
turning the weight on is a proposal the ships accept when no one objects.

## 5. The measure

Pre-registered, read by the ships, never a gate:
- **The share of receipts judged `helped`,** with outcomes per receipt (a ship that stops recording makes any share
  meaningless, so the coverage is reported beside it).
- **The shadow's reach:** how often `reordered` is 1 per 100 queries, and how many lessons the weight would drop.
- **After it's on:** the `helped` share and verified repeats, against the shadow period. A fall in `misled` with the
  same coverage is the signal. A fall in coverage isn't.

## 6. What it doesn't do

- **No federation of outcomes.** Each peer weighs its own ships' judgments. A peer's counts could later go to the
  lessons room as a signed summary, with no ship ids, as rail-commons monitoring (principle 4). That's its own spec.
- **No sanction.** A `misled` is a frontier, not a fault: it moves a ranking and costs the author nothing (rail
  commons, principle 5). An author who sees their lesson misled can revise it or retract it, as today.
- **No automatic outcome.** The hook never guesses one. A verified repeat already says that a lesson was shown and
  the mistake still happened. That's about the hook's timing, not the lesson, so it doesn't count as `misled`.
- **No person's data:** only ids, times and one of three words.

## 7. Tests (for the build)

- **Refusals write nothing:** another ship's receipt; an unknown or ambiguous short id; a second outcome; one after 24
  hours; an outcome outside the three words.
- **The latest outcome per ship counts once.** A ship shown a lesson three times, judging `helped` then `misled`,
  counts one `misled`.
- **The weight:** `θ'` follows the formula at `p = 0`, `0.5` and `1`. A lesson outside `r_max` is never shown
  however it's judged. A helped lesson can pass a nearer, misled one. Words matches keep their order.
- **Shadow:** with the weight off, the answer is today's, and `reordered` is right in a case where the weight would
  change the order and in one where it wouldn't.
- **The answer** names each lesson's receipt short id, and the prompt path's answer names none.
- **The query's p95** stays under 1 s with outcomes for every lesson in the index (first rail, section 5).

## 8. Decisions, for the reviewer

1. Three outcomes, not a scale: a ship can say which with no free text, and `unused` keeps "shown but irrelevant"
   apart from "wrong".
2. Latest per ship and lesson: one ship can't drown a lesson, and a ship can change its mind by a later receipt.
3. A bounded effective angle, not a new score: it composes with `r_max` and can never show a lesson farther than
   today.
4. Local, like receipts and repeats: the first rail's privacy shape holds, and federation can come later.
