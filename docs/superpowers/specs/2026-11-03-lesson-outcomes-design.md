# Lesson outcomes: did a shown lesson help?

Rio Grande, 2026-11-03, board item `spec:rail-lesson-outcomes`. Builds on the first rail
(`docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md`, branch trail-arrows-spec): its receipts (section 5)
and repeats (section 7.1); the code is `peer/superyak_peer/lessons.py` on main. Ties to the rail mathematics
(`2026-11-03-rail-mathematics.md`, branch rail-mathematics): weights learned from use, loose where evidence is thin.

Revision 2. A fresh reviewer gave revision 1 (54d9344d) APPROVE WITH CHANGES, with four must-fixes:
- the weight's real bound depends on how many ships judged;
- a dropped lesson could never be judged again;
- the temperature was named but unused;
- the prompt path wasn't covered.

All four are answered here, along with its should-fixes.

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

**The table:** `lesson_outcomes(id TEXT PRIMARY KEY, created REAL NOT NULL, receipt_id TEXT NOT NULL UNIQUE
REFERENCES lesson_receipts(id), outcome TEXT NOT NULL CHECK(outcome IN ('helped','misled','unused')))`, beside
`lesson_receipts`, `lesson_queries` and `lesson_repeats`. The ship and the lesson come from the receipt and are never
arguments. **No free text**: no note, no command, no context.

## 3. The verb

`lessons outcome <receipt id> helped|misled|unused`, run by a ship on its own peer (`make lesson-outcome RECEIPT=
OUTCOME=`).
- The ship is the calling account. The receipt must be one of its own: a receipt shown to another ship is refused.
- A receipt id is its full id (32 hex characters) or a prefix of at least 6 that matches exactly one of the ship's
  receipts. An ambiguous or unknown one is refused.
- **One outcome per receipt, within 24 hours** of the receipt. A second outcome is refused, and so is a late one.
  The cost: a ship changes its mind about a lesson only through a later receipt of it.
- The query's answer (first rail, section 5, step 5) gains each lesson's **receipt short id** (its first 8
  characters) beside the lesson's, so the ship has what the verb needs.
- `make lesson-outcomes` lists this peer's records, newest first: ids, ship, lesson short id, outcome. No text.

Outcomes are local to each peer, like receipts and repeats. They never federate (section 6).

## 4. Ranking weighs it, in shadow first

**The evidence.** For each lesson, take each ship's latest outcome on this peer from the last **30 days**. Let `n` be
the number of ships whose latest outcome is `helped` or `misled`, with `h` helped and `m` misled (`n = h + m`). An
`unused` counts for neither.

So `p` below is quality when used: how often the lesson helped among the times it mattered. It doesn't measure
usefulness per showing; section 5 reports `unused` beside it, as salience.

**The estimate.** The posterior mean of a Beta(1, 1) prior is `p = (h + 1) / (n + 2)`. With few judges it's coarse
(at most four ships today, so `p` takes few values), and it's expected to be.

**The weight, loose where evidence is thin.** Near ranks by angle (first rail, section 5, step 2). With outcomes it
ranks by an effective angle:

`θ' = θ · (1 + λ_n · (0.5 − p))`, with `λ_n = 0.5 · n / (n + 2)`.

`λ_n` shrinks the weight while few ships have judged: that's the temperature the rail mathematics asks for. Since `p`
lies in `[1/(n+2), (n+1)/(n+2)]`, the largest shift is `n² / (4 (n+2)²)` of `θ`:

| n | largest shift |
|---|---|
| 1 | no weight (below) |
| 2 | 6.3% |
| 4 | 11.1% |
| ∞ | 25% |

**Four rules bound it:**
- **At least 2 judges.** With `n < 2` the lesson ranks as today. One ship never decides alone, and on a peer where one
  ship is the only judge the weight is off. That's the honest result.
- **It reorders, and never removes.** A lesson is a candidate when its true angle `θ` is within `r_max`, as today,
  however it's judged. `θ'` only orders the candidates. So a misled lesson still shows when nothing better matches,
  and it can be judged again. No lesson is ever shown farther than today.
- **Outcomes expire after 30 days,** so an old verdict can't hold a lesson down forever.
- **Words matches aren't reweighted.** A literal command, error or file match is evidence of its own kind.

**Revision is the author's recovery path.** An author whose lesson misled can revise it, which makes a new lesson
id that starts at the prior and inherits nothing, or retract it, as today.

**The prompt path is unchanged.** It reads only the index file and opens no database (first rail, section 5), so at
a prompt the weight doesn't apply. Carrying `p` in the index can come later, if the shadow shows it's worth it.

**Shadow first** (rail commons, stage 5). Until a proposal turns it on, the query ranks as today and computes the
outcome order beside it. That's on the post-skip candidates (after step 4's `seen`, retraction and own-lesson
skips), before the cut to 3. The query row gains two integers, so no ids or text enter it:
- `reordered`, 0 or 1: whether the outcome order would have changed the shown set or its order;
- `displaced`: how many shown lessons it would have pushed out of the top 3.

`λ`, the 30-day window, the 2-judge minimum and the 24-hour window go on the rail-parameters list (rail commons,
principle 3). Turning the weight on is a proposal the ships accept when no one objects.

## 5. The measure

Pre-registered, read by the ships, never a gate.
- **During the shadow:**
  - **The primary signal:** verified repeats per 100 queries.
  - **Coverage:** outcomes per receipt.
  - **The `helped` share** among `helped` and `misled`.
  - **`unused` per receipt.**
  - **The shadow's reach:** `reordered` per 100 queries, and the sum of `displaced`.
- **After it's on,** compared with the shadow period:
  - **A pass:** verified repeats per 100 queries fall while coverage stays within ±20% of the shadow's.
  - **Inconclusive:** coverage moving outside that band. Nothing is concluded from it.
  - **Secondary:** a rising `helped` share. Once the weight orders misled lessons lower, the share can rise with no
    better lessons, so it's never read alone.

Repeats and outcomes don't cross-check each other. A verified repeat says a shown lesson didn't stop a mistake, which
is about the hook's timing (section 6). It isn't counted as `misled`.

## 6. What it doesn't do, and what it accepts

- **No federation of outcomes.** Each peer weighs its own ships' judgments. A peer's counts could later go to the
  lessons room as a signed summary with no ship ids, as rail-commons monitoring (principle 4). That's its own spec.
- **No sanction.** A `misled` is a frontier, not a fault: it moves an ordering and costs the author nothing (rail
  commons, principle 5).
- **No automatic outcome.** The hook never guesses one.
- **No person's data:** only ids, times and one of three words.
- **Gaming, accepted at 2 to 4 ships.**
  - An author can't promote its own lesson: the query never shows a ship its own, and the verb needs a receipt.
  - A ship can mark another's lesson `misled` on every receipt it holds. With the 2-judge minimum and reorder-only,
    that can lower the lesson within the candidates once a second ship agrees, but never remove it.

## 7. Tests (for the build)

- **Refusals write nothing:** another ship's receipt; an unknown or ambiguous prefix; a prefix under 6 characters; a
  second outcome; one after 24 hours; an outcome outside the three words.
- **Counting:** a ship shown a lesson three times, judging `helped` then `misled`, counts one `misled`. An outcome
  older than 30 days doesn't count.
- **The weight:**
  - with `n = 1` it changes nothing;
  - with `n = 2` and `n = 4`, `θ'` follows the formula at its extremes (6.3% and 11.1%);
  - a lesson within `r_max` and judged `misled` by two ships is still shown when it's the only candidate;
  - a lesson outside `r_max` is never shown, however it's judged;
  - words matches keep their order.
- **Shadow:** with the weight off, the answer is today's. `reordered` and `displaced` are right in a case where the
  weight would change the order, one where it would push a lesson out, and one where it would change nothing.
- **The answer** names each lesson's receipt short id. The prompt path's answer names none, and its order doesn't
  change with outcomes.
- **The query's p95** stays under 1 s with outcomes for every lesson in the index (first rail, section 5).

## 8. Decisions

1. Three outcomes, not a scale: a ship can say which with no free text, and `unused` keeps "shown but irrelevant"
   apart from "wrong".
2. Latest per ship and lesson, within 30 days: one ship can't drown a lesson, and an old verdict fades.
3. A bounded effective angle that reorders and never removes. It composes with `r_max`, never shows a lesson farther
   than today, and can't lock a lesson out.
4. The weight grows with the number of judges, and needs at least 2.
5. Local, like receipts and repeats: the first rail's privacy shape holds, and federation can come later.
