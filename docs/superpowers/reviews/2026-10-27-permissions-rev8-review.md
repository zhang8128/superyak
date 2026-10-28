# Review: permissions spec revision 8 (the performance change)

**Date:** 2026-10-27
**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in the revision, the
design or the prototype.
**Spec:** `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md`, revision 8 (`git diff HEAD`, branch
`trail-arrows-spec`, HEAD `a093144`). Line numbers below are the working tree's.
**Design:** `permissions-core/.superpowers/sdd/2026-10-25-permissions-by-place/perf-design.md`, with its prototype on
branch `perf/design-index` (`a083a96..e0cc5d1`).
**Verdict: approve with changes.** Three must-fix items remain (M1 to M3). Each one needs a sentence or two of the
spec changed. The budgets match the measurements, the index is exact, and the background build fails closed and
stays within the 2 State slots. But 6.4's list of what a decision reads leaves out one attribute the prototype
handles (M1). As written, the list lets an evaluator group two objects that get different decisions, which would
widen a permission. Revision 8 is approved once M1 to M3 are applied, and a re-check of those three edits alone is
enough. The should-fix items (S1 to S9) don't block it.

## What the revision changes

- Header: revision 8's status line, its own paragraph, and a "Depended on by" bullet.
- 6.4, "How it is computed": a new list of what a decision reads, and the evaluator may decide each group of objects
  that read alike once, except under the bulk use's Pi budget.
- 6.5, "How it is computed": the records index, and what may be kept per State.
- 12.2: the cache's estimate counts a shared decision once. Three rebuild budgets replace one. A new bullet, "While a
  set is being built", covers the background build, failing closed, one build per key, failed builds and the check of
  a finished set. A build counts as a frame.
- 15: new figures in the "Eligible-set rebuild" and "Bulk decision" rows. Two new rows: "Rebuild wait" (1.0 s) and
  "Shared decisions per eligible set" (4,096). The frames row counts a build. The bulk run's memory part becomes
  58.6 MB. A new "Measured" paragraph.
- 16: the new parts of `permissions.py` and `lighthouse_daemon.py`.
- 17: U9 gains the background build's cases. U24 becomes five timed budgets, and its daemon run gets more keys.
- **The file is complete.** All 19 `## ` headings and every `### ` heading of HEAD are present, in the same order.
  The file ends with a newline. It grows from 2,449 to 2,539 lines, which matches the diff's +126/-36, and its last
  five lines are unchanged.

## How I checked

I read the whole diff and the whole design. In the prototype I read `_share_key`, `_times_of_interest`,
`_envelopes_list_memories`, `lane_held`, `lane_touched`, `_span`, `_in_force`, `_meets`, `_membership_counts`,
`_grant_ok`, `eligible_set` and `_a_collect` (`git show perf/design-index:engram/permissions.py`). I also read the
build's daemon (`permissions-core` at `231cd91`, `engram/lighthouse_daemon.py`) and the U24 probe
(`engram/tests/pi_budget_probe.py`). I redid every figure in the revision. I searched the spec, the vision, the
imprints and trail specs and the review ledgers for the old 2 s and 40 s.

## 1. Do the new rules change a decision?

**The index (6.5, lines 942-950) is exact.** 5.2 makes an object's dimensions a conjunction (line 441). So a
record whose own selector lists memories can match only a memory it lists. A record that names collections can match
only an object with a membership row in one of them: an allow needs an effective membership at t, and a deny needs a
row in force at some time in `[anchor, t]`. In the prototype, `_object_dims` returns False at `memories` before it
reads lanes, collections, the `replaces` chain or a grant. So a record the index skips could never have raised.
The index reads only a record's own selector, so records reached through a `replaces` chain or a grant's envelope
are still tested. Each layer's version, its denies that start after t, and the horizon's terms from the layers'
records and grants read no object. This is design 2.A and 2.B. One wording point is S3.

**The grouping (6.4, lines 853-858) is exact only within the exceptions the prototype makes.** Here is what a
decision compares an object's times with:
- the lane tests (5.3's table, `lane_held`, `lane_touched`) compare notes with an anchor, with t, and, through
  `max(anchor, first note)`, with the object's own notes. The notes keep their order;
- the membership tests (`_in_force`, `_meets`) compare a row's start and end with t and an anchor;
- `until` moves t only to a deny's `valid_from`.

So "each time read only by its order against t and every record's anchor and `valid_from`" holds. "Order" covers
equality, which is the design's in-Θ flag (its A/B case). The design argues that the note rank is redundant
(perf-design.md:216-219), and I agree: the `all(...)` in `lane_held` reads every note from the first one on.

**The evidence (design section 4) supports the prototype's rule.** The differential dump is byte-identical from A to
K, the share-key fuzz passes, and the suites pass. But the prototype decides two cases alone: an object with a
grant-backed membership, and every object while some grant's envelope lists memories (`_share_key`,
`perf/design-index:engram/permissions.py:2353-2365`; design 2.H, line 155). The spec's list has neither exception,
so the evidence doesn't cover everything the spec allows. That is M1.

## 2. Do the budgets match the measurements?

Yes. Each budget is about 1.5 times its measure, except the 2 s, which is kept:

| Budget | Measured (design 3 and 5) | Ratio |
|---|---|---|
| Rebuild, U24's fixture, 2 s | 0.9 s | 2.2 |
| Rebuild, no two objects alike, 30 s | 17.4 to 20.2 s | 1.49 to 1.72 |
| Rebuild, reference ledger, 6 s | 3.6 s | 1.67 |
| Bulk, U24's fixture, 300 s | 191.4 s | 1.57 |
| Bulk, reference ledger, 300 s | 210.6 s | 1.42 |

- 15's rationale for the rebuild row checks out. 20,000 × 41 = 820,000 layer verdicts, and at 21 to 26 µs each
  that is 17.2 to 21.3 s. 2 s / 820,000 = 2.44 µs.
- The memory figures check out. The bulk row is 30.3 + 72.7 + 58.6 + 13.6 = 175.2 at the reference, and 30.3 + 95.9
  + 58.6 + 13.6 = 198.4 at the bounds. That leaves 512 − 198.4 = 313.6 MB of margin, and 512 − 175.2 = 336.8. The
  run's 58.6 is 47.5 + 11.1.
- The rebuild peak is 98.6 MB (estimate 126.8). The daemon peaks are 312.4 MB and 331.3 MB (estimates 409.1 and
  471.7). The prototype measured 80,483 lines of the dump, and 134,430, 37,440 and 48,000 fuzz checks. The
  revision's other figures (11 commits, and Andy's 0.30 to 0.83 s) match the design too.
- The bulk row's per-pair rate doesn't add up to its own measure (S4). The 6 s doesn't say what it covers (S7).

## 3. The daemon while a set is being built

**It fails closed.** Under `enforce`, a frame is served only from a finished set that still holds. A stale entry
never serves. A failed build leaves no entry. A set whose `seq` or change counter moved is dropped. A build decides
with the frame's own State and t, so it makes exactly the decisions the frame would have made. Under `shadow`, the
legacy path decides alone, which it already does in that mode. Deny by default holds.

**It stays within the memory budget and the 2 slots.** A build takes over its frame's slot and State, so at most 2
States are held at once (item 3, and line 2046). The daemon row's "2 frames × (a State + a set being built + …)"
still bounds it. A frame that answers after the wait holds no State. A later frame for the same key holds its own
State in the second slot while it waits. Measured: 312.4 MB and 331.3 MB, but with the cache at 72 MB (S5).

**Problems.** The receipt that the shadow case promises is defined nowhere (M2). The wait for a slot has no deadline,
so the 2 s claim holds only at Andy's size (S1). The frame whose build fails is not covered (S6), and neither are
bursts of writes (S9).

## 4. Does anything else in the spec contradict the new text?

- The spec cites the old 2 s and 40 s only as history (lines 88-91, 153, 2029-2030). 6.4, 6.5, 12.2, 15, 16 and
  U24 agree with each other on every figure.
- The citations of `engram/lighthouse_client.py` are right: `:16` is `MAX_TIMEOUT_S = 10.0`, and `:89` is
  `timeout_s: float = 2.0`.
- The imprints spec, the trail spec and the vision cite neither figure. The interfaces ledger still does (S8).
- U24's daemon recipe can't reach the condition it states (M3).

## Must-fix

**M1. 6.4's list of what a decision reads leaves out grant envelopes that list memories. As written, it lets an
evaluator widen.** *Where:* 6.4, "How it is computed" (lines 853-858). The same list backs "objects that read alike"
in 12.2 (line 1630) and 15 (line 2032).

A grant-backed membership counts for an allow "only for uses inside every envelope of that chain" (line 489-491).
An envelope is a selector (7.2), so it may list memories. Through such a membership, then, a decision reads the
object's own ref against the envelope's `memories` list. The spec's list doesn't name that. Here is how it plays
out:
1. Grant G's envelope lists memories `[m1]`.
2. Rio Grande collects m1 and m2 into collection C under G, in one act. No allow names C yet, so `collect`'s
   condition holds: it checks only the allows that name the collection, not the objects (line 1055;
   `_a_collect`, `perf/design-index:engram/permissions.py:3470-3482`).
3. Andy later writes a person-backed allow that names C, with `memories` `"*"`.
4. m1's membership counts and m2's doesn't, so m1 is allowed and m2 is refused.

But the two agree on kind, store, layer and subjects, on which records list them (none), on their lane notes, and on
their memberships (C, backed by G, with the same times). By 6.4 they "get the same decision", so an evaluator may
decide the group once and give m2 m1's allow. The prototype doesn't do this, because of the two exceptions in
section 1. The design's proposed wording (its section 7) dropped them, and the spec copied that wording. So the
header's "Revision 8 widens nothing and changes no decision" is not yet true of the text.

*Fix:* after "… and `valid_from`." in 6.4, add: "An object with a grant-backed membership is decided alone, and so is
every object while some grant's envelope lists memories." This is the rule the evidence covers. Optionally, say in
the same place that the grouping holds for any uses that differ only in their object, such as an eligible set's
placements of one house (12.2). 12.2 and 15 rely on it there, and 6.4 states it only for bulk uses.

**M2. In the shadow case, "the receipt says the ledger decision was not made, as for a failed ledger read" describes
a receipt that nothing defines.** *Where:* 12.2 item 2 (lines 1643-1645) and U9 (lines 2269-2270).
- **A failed ledger read writes no such receipt.** 12.2's paragraph (lines 1686-1688) only warns and lets the legacy
  path decide. The build does the same: `_ledger_side` returns `(None, enforce)` (`engram/lighthouse_daemon.py:
  718-719`), and `_rank_recall` writes a receipt only when there is a side (`:794-796`).
- **9.1 has nowhere to record it.** Its `uses` table has `ledger_seq`, `allowed` and `cited` all NOT NULL, and no
  column for "not made" (lines 1320-1323).

So U9's clause can't be met without inventing a receipt form in a hash-chained file.

*Fix:* in 12.2 and U9, say "and, as for a failed ledger read, the daemon warns and writes no ledger receipt for that
frame". Or define the form in 9.1 and give the failed read the same one. If you choose a receipt, also say that the
frame reads nothing from the State it handed to the build, since the build's thread holds it.

**M3. U24's daemon run can't fill the cache past 96 MB with "8 receivers × 2 purposes".** *Where:* U24 (lines
2380-2381).
- **The recipe falls short.** 14 entries held 72.0 MB by their estimate (design 3, line 182; the probe sums
  `estimate()`), so 5.14 MB each. 16 keys hold about 82 MB, 14 MB short of the 96 MB the sentence requires. Passing
  96 MB needs at least 19 keys: 7 receivers × 3 purposes (21) or 8 × 3 (24). The "or 3 purposes" option works; the
  8 × 2 option doesn't.
- **The design aims lower still.** Its P9 asks for "16 keys so the cache passes 80 % of 96 MB" (perf-design.md:494).
- **The miss matters.** The cache is the daemon's largest single part, and the records bound leaves a margin of only
  40.3 MB. A run that holds 82 MB under-measures by more than a third of that margin.

*Fix:* write "8 receivers × 3 purposes (24 keys)", or "at least 19 keys". Make the test assert that the cache's
estimate reached 96 MB and that entries were evicted. Align the plan's P9.

## Should-fix

**S1. The wait for a slot has no deadline, and the 2 s claim holds only for small houses.** *Where:* 12.2 items 1 and
3 (lines 1637-1649), and 15's "Rebuild wait" row (line 2031).
- **Builds can block every frame.** A frame takes its slot with `self._frames.acquire()` and waits as long as it
  takes (`engram/lighthouse_daemon.py:705`: "a frame waits, it is never refused"; and 12.2's "a third waits", line
  1682). A build now keeps its slot after its frame has answered. So at the reference size, two builds (3.6 s each,
  up to 30 s when no two objects read alike) hold both slots. Every other frame waits past the client's 2 s,
  including reads and frames whose entry is still valid.
- **The frame's own work already uses the 2 s.** At the reference size a frame's own `state()` takes 1.0 s (design
  3, line 198), and the design's daemon probe took 217.4 s for 14 frames.
- **The outcome.** This fails closed (the client gives up), and memory holds. But "so that the frame still answers
  inside the client's 2 seconds" is true at Andy's size only.
- **Fix.** Either bound the wait for a slot by the rebuild wait as well, and serve nothing past it, as item 2 does.
  Or say that the 2 s holds when a frame's own work is small, as in Andy's step 1, and that at the reference size a
  frame can pass the client's deadline whatever the build does.

**S2. Section 17 has no test that a shared decision equals deciding the object alone.** U9's last clause covers
builds, not grouping, and F1 runs `decide`. The design's fuzz didn't catch dropping the in-Θ flag
(perf-design.md:216-219), so its A/B case is the only guard. Add these tests, for example to U9 or PT10. They are the
plan's P7 (a) to (d):
- an eligible set's decision for each placement equals `decide` on that placement alone, on random worlds whose lane
  notes and membership rows sit a second before, at and after every anchor, `valid_from` and t;
- the A/B case: notes `personal` and `work` exactly at an allow's anchor refuse, a second before they allow, and the
  two objects are not grouped;
- objects with a grant-backed membership, and every object of a ledger whose grant envelope lists memories, share no
  decision (M1);
- at most 4,096 shared decisions are kept.

**S3. 6.5's "keep per State" should be "keep per State and t".** *Where:* lines 946-948. "Its denies that start
after t" depends on t. The horizon's layer part also depends on the ordered required layers. Design 2.A keys it by
(t, layers), because a chain longer than 16 makes the walk depend on their order.

**S4. 15's "Bulk decision" rationale doesn't add up to its measure.** *Where:* line 2030. "About 0.5 ms an (object,
action) pair … and 0.8 to 1.1 µs a touch read" gives 400,000 × 0.5 ms + 51.2 million × 0.8 to 1.1 µs = 241 to 256 s,
not the measured 191.4 s. The design's own figures add up (perf-design.md:242-244): about 66 s for 100,000 memories'
`recall` at 0.66 ms each, plus 1.08 to 1.23 ms for each trail's three actions with its 512 touches, 174 to 189 s in
all. Use those.

**S5. 15's "Measured" paragraph needs three clarifications.** *Where:* lines 2153-2159.
- (a) The bulk decision's "estimate 164.1" is revision 7's estimate. The table's estimate is now 175.2. Say so.
- (b) The daemon's 312.4 and 331.3 MB were measured with the cache at 72.0 MB (14 entries), 24 MB below the 96 MB
  the estimate holds. Say so. U24's run after M3 is what measures a full cache.
- (c) The prototype has no background build. "The memory budget is unchanged" is therefore argued, not measured.
  After P8, U24's daemon run should have builds running in the background.

**S6. 12.2 item 4 doesn't say what a waiting frame does when its build fails.** It says only that the build is
"logged and leaves no entry". Say that the frame is answered as a failed ledger read: a warning, and nothing served
under `enforce`.

**S7. The 6 s budget doesn't say what it covers.** *Where:* lines 1630 and 2029. The probe's clock runs over opening
the ledger, `state()`, the module imports and the eligible set (`engram/tests/pi_budget_probe.py:47-53, 224-226`).
Design 5 reads the 3.6 s as "plus the frame's `state()`". If the probe is the measure, say that the 6 s includes the
State.

**S8. The interfaces ledger still states the 40 s.** *Where:* row 29 (`docs/superpowers/reviews/
2026-10-25-city-rail-interfaces.md:67`). Its agreed rule still reads "within P 15's 40 s" and "so the 40 s covers
every bulk use". Add a revision 8 pass note:
- the budget is 300 s;
- no verdict of I or T changes;
- I decides by its own finite check, so its 1,740 s deadline is untouched.

Row 8 (line 46) cites the 40 s as history, so it can stay.

**S9. "Returns nothing for a few seconds" understates the worst case.** *Where:* lines 1658-1659. When no two
objects read alike, the gap can last up to the 30 s budget. If writes come faster than a build finishes, each build
is dropped (item 5), so nothing is served until the writes pause. Say this as a known limit.

## What holds

- The header, the status line and "Depended on by" say what changed, mark the figures as Rio Grande's call, and say
  that it needs this check.
- The index of 6.5 is exact.
- Within the prototype's exceptions, the grouping of 6.4 is exact, and its evidence is strong: byte-identical dumps
  of every decision field, and the fuzz against deciding each object alone.
- Every budget and memory figure matches the design's measurements.
- The background build fails closed, never serves a stale set, and holds at most 2 States.
- No stale figure is left in the spec. 16's rows and U24's five budgets match the design's section 5. The file is
  complete.

## Response

**Date:** 2026-10-27. Every must-fix and every should-fix is applied. S1 is applied by stating the limit rather
than adding a deadline, for the reason given below. Nothing is committed. The spec grows from 2,539 to 2,589 lines,
so the line numbers above are now earlier than the text they name. All 19 `## ` and 34 `### ` headings are unchanged
and in order, and the file ends with a newline.

**Must-fix**
- **M1, applied.** 6.4, "How it is computed", now has the fix's sentence after "… and `valid_from`." It also gives
  the reason: such a membership counts only inside its chain's envelopes (5.3), and an envelope that lists memories
  reads the object's own ref. The next sentence now reads "each group of the other objects". The optional part is
  applied too: the grouping, with the same exceptions, holds for any uses that differ only in their object, such as
  an eligible set's placements (12.2). The header's revision 8 bullet and 16's `permissions.py` row name the objects
  decided alone. PT10 tests your example (S2).
- **M2, applied as "no receipt".** 12.2 item 2 now says that, as for a failed ledger read, the daemon warns and
  writes no receipt to `permission-uses.db` (9.1) for that frame. U9 says the same, so 9.1 is unchanged. I checked
  this against `_ledger_side` and `_rank_recall` at `231cd91`: a failed read leaves no side and so writes no receipt.
- **M3, applied.** U24's daemon run fills the cache from at least 19 keys, 8 receivers × 3 purposes (24 keys), with
  the 5.14 MB an entry. The test asserts that the entries added passed 96 MB in all by their estimate, and that the
  cache evicted some. I didn't write "the cache's estimate reached 96 MB" because the cache holds at most 96 MB by
  its estimate (U9), so its own total never passes the bound. The added total does, and eviction shows it. The
  plan's P9 lives in `permissions-core`, which this pass doesn't edit. Aligning it is left to the controller.

**Should-fix**
- **S1, applied as a stated limit, without a deadline.** 12.2 item 1 now says the frame answers inside 2 s "when its
  own work is small, as in Andy's step 1". The Memory bullet says a third frame waits for a slot "with no deadline".
  A new "Known limits" part after the items says the rest: two builds can hold both slots at the reference size, so
  every other frame waits past 2 s, reads and frames with valid entries included, and a frame's own `state()` takes
  about 1.0 s there. That fails closed. 15's "Rebuild wait" row says the same. I didn't bound the slot wait. That
  would change how every frame waits, reads included, which nothing measured, and it would widen this revision past
  the change its evidence covers. Both options fail closed. The deadline can come in a later revision with a
  measurement.
- **S2, applied in PT10.** PT10 now checks that an eligible set's decision for each placement equals `decide` alone.
  The worlds put notes and rows a second before, at and after every anchor, `valid_from` and t, with and without
  listing records. Named cases cover the A/B in-Θ case, M1's exclusions with your example, and the 4,096 cap with
  later groups decided alone.
- **S3, applied.** 6.5 now says "per State and t". It keeps the horizon's terms per ordered list of required layers.
  The header and 16 say "per State and t" too.
- **S4, applied.** 15's Bulk decision row now uses the design's figures: about 66 s for the 100,000 memories'
  `recall` at 0.66 ms each, plus 1.08 to 1.23 ms a trail, 174 to 189 s in all.
- **S5, applied.** (a) "Estimate 164.1, revision 7's; the table's estimate is now 175.2." (b) The daemon's two peaks
  were measured with the cache at 72.0 MB (14 entries), and U24's run after M3 is what measures a full cache.
  (c) A new paragraph says the prototype has no background build, so the claim that a build leaves the memory
  unchanged is argued, not measured. U24's daemon run now builds its sets in the background, so it measures that.
- **S6, applied.** 12.2 item 4 says that a frame still waiting on a failed build is answered as for a failed ledger
  read: a warning, nothing under `enforce`, the legacy path alone under `shadow`, and no receipt. U9 tests it.
- **S7, applied.** The probe's clock is the measure. At `231cd91` and on `perf/design-index`, `pi_budget_probe.py`
  starts its clock before `op_eligible`, which opens the ledger and calls `state()` (lines 36-53, 224-226). So 12.2,
  15's rebuild row and U24 say that the 6 s includes opening the ledger, its `Ledger.state()` and the module imports.
  The design's reading ("plus the frame's `state()`") is not adopted.
- **S8, applied** in `docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md`:
  - the header's P list names revision 8;
  - row 29's agreed rule reads "within P 15's 300 s";
  - row 29 gains a "Permissions revision 8 pass" note: the budget is 300 s, the 40 s in the earlier notes is history,
    no verdict of I or T changes, and I's 1,740 s deadline is untouched;
  - "What changed, by spec" gains a bullet.

  Row 8's 40 s stays as history.
- **S9, applied** under "Known limits" in 12.2. Recalls after a change return nothing until the build finishes:
  a few seconds, and up to the 30 s budget when no two objects read alike. If writes come faster than a build
  finishes, each build is dropped (item 5), so nothing is served until the writes pause.

**Also changed.** The status line now says this check approved revision 8 with changes, that its fixes are
applied, and that a re-check of M1 to M3 is due. A short paragraph at the end of revision 8's header text lists the
fixes. No decision rule changes beyond M1. M1 narrows the text to the prototype's rule, so "Revision 8 widens
nothing and changes no decision" now holds of the text.

## Final check

**Date:** 2026-10-27.
**Reviewer:** a fresh reviewer acting in Andy's place (station law section 3). I took no part in the revision, its
first check or the fixes.
**What I read:** the spec as it now stands (`git diff HEAD`, 2,589 lines), the "Response" above, and the interfaces
ledger's diff. In the design I read 2.H and Task P9 (`perf-design.md:150-160`, `:485-496`). In the prototype
(`git show perf/design-index:engram/permissions.py`) I read `_share_key`, `_envelopes_list_memories`,
`_listed_memories`, `group_key`, `eligible_set` and `_a_collect`. In the build at `231cd91` I read the daemon's
`_ledger_side`, `_recall` and `_rank_recall`, and the U24 probe. Line numbers below are the spec's as it now stands.

**Verdict: approve.** M1 to M3 are resolved, and the fixes add no must-fix. Revision 8 can be committed as it
stands. N1 to N4 below are should-fix wording. C1 to C3 are for the build. None of them blocks.

### The three must-fix items

**M1, resolved.** 6.4, "How it is computed" (lines 863-873), now says: "An object with a grant-backed membership is
decided alone, and so is every object while some grant's envelope lists memories." It also gives the reason (5.3).
- **It is the prototype's rule.** `_share_key` returns None while any grant in the State has an envelope whose
  `memories` is not `"*"`, revoked grants included (`_envelopes_list_memories`, prototype `:2348-2351`). It also
  returns None when the object has a grant-backed row (`:2362-2366`). The spec's "some grant" is just as broad.
- **The example is excluded twice.** m1 and m2 each have a grant-backed membership in C, and G's envelope lists
  memories. Either clause alone keeps m2 from taking m1's allow. PT10 (lines 2255-2263) tests this case by name.
- **Grant-backed records are covered too.** 5.3 rule 5 matches every envelope of a grant-backed record's chain by
  object dimensions. The second clause excludes that case, and the stated reason ("an envelope that lists memories
  reads the object's own ref") applies to it.
- **The bulk path is exact on the same example.** Revision 7's `group_key` (prototype `:2088-2096`) keys a memory
  that any record or grant lists by its own ref (`_listed_memories`, `:1967-1975`). Its note and membership rows
  carry the object's ref, so two memories with notes or memberships never group.
- **The imprints spec is untouched.** Its finite check reads only its own two records (its section 8, "A finite
  check"), not the owner's grants.

So the header's "Revision 8 widens nothing and changes no decision" holds of the text.

**M2, resolved.** 12.2 item 2 (lines 1657-1662) now says that under `shadow`, "as for a failed ledger read (Memory,
below), the daemon warns and writes no receipt to `permission-uses.db` (9.1) for that frame". U9 (lines 2313-2316)
says the same, and item 4 (lines 1666-1669) says it for a failed build.
- **No receipt form is needed.** Nothing now asks for a "not made" receipt, and 9.1 is unchanged.
- **The build agrees.** `_ledger_side` returns `(None, enforce)` when the ledger can't be read
  (`engram/lighthouse_daemon.py:719`), and `_rank_recall` writes a receipt only when there is a side (`:796`).
- **The frame is still recorded.** `_recall` writes the house's disclosure record for every recall frame, side or
  none (`:748`), with the ids it returned. So no use goes unrecorded, and section 19 needs no new departure from the
  vision's principle 5.

**M3, resolved.** U24 (lines 2427-2433) fills the cache from at least 19 keys: 8 receivers × 3 purposes, 24 keys.
- **The figures hold.** 24 × 5.14 = 123.4 MB, past 96. 18 keys hold 92.6 MB, short of it, and 19 keys hold 97.7 MB.
- **The assertion is sound.** The test asserts that the entries added passed 96 MB in all by their estimate, and
  that the cache evicted some.
  - The Response is right not to assert the held total: U9 keeps it at most 96 MB (line 2309).
  - 24 keys are under the 64-entry cap (line 2056), so any eviction comes from the byte bound, and the assertion
    shows the run reached it. After an eviction the cache holds within one entry, about 5.1 MB, of 96 MB.
- **The rest agrees.** 15's "Measured" paragraph and the header's fix list both say the same.

**The file.** All 19 `## ` and 34 `### ` headings of HEAD are present, in the same order. The file ends with a
newline. It has 2,589 lines: 2,449 + 178 − 38 (`git diff --numstat`). Its last five lines are unchanged. The
interfaces ledger's diff touches only the header's P list, row 29 (its rule now reads 300 s, plus a pass note) and
one "What changed" bullet.

### Should-fix (not blocking)

**N1. Item 2's `enforce` case doesn't say whether a receipt is written.** Lines 1657-1659 say only "answers as a
refused frame does", and U9's `enforce` clause doesn't say either. Item 4 says "no receipt" in both modes. A frame
past the wait made no ledger decision, so any receipt would need the form M2 avoided. Write "and no receipt" in
item 2 and U9 for `enforce` as well; the build writes none there either (`:719`, `:796`).
- Optionally, the failed-read sub-bullet (lines 1715-1717) could say "and writes no receipt". Then the "as for a
  failed ledger read" of items 2 and 4 points at text that says it.
- And "Modes" (line 1697) could name these frames as an exception to "both decisions go to the receipts".

**N2. "Known limits" says "returns nothing", which is true only under `enforce`.** Lines 1678-1683. Under `shadow`,
a recall made while a build runs gets the legacy path's answer (item 2). Add "under `enforce`".

**N3. The new "holds for any uses that differ only in their object" (lines 870-871) should say it is per decision.**
A use on a road or trail is "one decision for the road or trail and one for each memory it names" (6.4, Bounds). Two
uses on two trails may share the trails' own decision, but not the uses' results, since they name different
memories. Write "each decision of such uses", or add "a road's or trail's named memories are decided as their own
objects". This is wording only:
- the bulk text already relies on the same reading;
- in an eligible set, the prototype shares only memory objects (`_share_key` returns None for a road or trail).

**N4. The status line (line 9) says that a re-check of M1 to M3 is due.** When revision 8 is committed, it should say
that this final check approved it.

### For the build (the controller's, not the spec's)

**C1. Task P9 still asks for 16 keys and 80 %** (`perf-design.md:490-494`: "`--receivers 8` or a third purpose").
U24 now needs both 8 receivers and a third purpose.

**C2. The probe can't yet check M3's assertion.** `engram/tests/pi_budget_probe.py` has two purposes (line 26) and
7 receivers by default (line 221). It reports only the held total (line 195), which can never pass 96 MB. It needs:
- a third purpose that the reference ledger's records allow, so that its entries are full size;
- counts of the bytes added and the entries evicted.

**C3. Bring the bulk `group_key` to 6.4's new sentence.** It groups roads and trails, which have no notes or
memberships, even while some grant's envelope lists memories. That is exact: a `memories` list doesn't make two
roads read differently, and F1 compares results, so the code conforms. But it doesn't do what 6.4 now says. One
check in `group_key` would make it match: no group key while `_envelopes_list_memories` holds. That helper is the
prototype's, and it isn't in the build at `231cd91`. U24 doesn't feel it, since it measures with `group=False`.
