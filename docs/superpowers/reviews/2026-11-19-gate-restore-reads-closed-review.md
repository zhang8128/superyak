# Fresh review: P 12.3 "this id, never raised" reads closed (branch tardis/gate-restore-reads-closed, 33d940ac)

I'm a fresh reviewer on Tardis, 2026-11-18, and I took no part in writing this. I only read files, ran probes and read
station posts 2134709b and fdbb4496. I didn't edit, commit or post anything, and I didn't touch the main checkout or
`~/.engram/`. Every fixture was in a tmp or scratch directory. The worktree is as I found it: I removed the
`__pycache__` that my first test run made there. Line numbers are at 33d940ac, whose code is the same as main cdc639c1.

## Verdict: APPROVE WITH CHANGES

The design holds. I traced every writer of `permissions_ledger_id`: only `_make_gate`, and 029's hook in
`storage.py`, which writes what `house_mark` returns.
Outside the paths the draft names, no code path gives a house this ledger's id while `gate_raised` is unset. I also
built the proposal into a scratch copy, and probes there show all of these:

- a restored older ledger reads `off` today and `closed` with the change;
- in every case I probed, at least one of the two recoveries works at the owner's own terminal;
- rebuild and replay are untouched;
- only the test that pins R50 as first written fails.

What needs changing is the text around the design:

- the words shown at the yes still describe the old act (M1);
- the claim that the body's `meta` tells a marking from an unmarking is false for the very logs path 3 makes (S1);
- rule 2 gives the closed reading one cause where the draft names three (S2);
- the recovery for a restore says nothing about the acts the older copy lost (S3);
- every first raise briefly passes through the new closed state, which the draft doesn't name (S4);
- R50's reason and cost columns weren't revised (S5).

## Findings

### M1. Must-fix: the yes's words still say the never-raised `gate off` marks houses

- **Where:** the plan's Task 26 text (`docs/superpowers/plans/2026-10-25-permissions-by-place.md:3403-3405`) still says
  the gate plan shown before the yes names "which of them the yes marks (under `off` on a ledger never raised, only
  those marked `unreadable` or with another ledger's id, R50)". The CLI prints exactly that:
  `gate_plan_lines` (`engram/permission_cli.py:692-705`) says "the yes marks only each that carries `unreadable` or
  another ledger's id, since the gate was never raised".
- **What the test pins:** `tests/test_permissions_recheck_fixes.py:257-267` pins those words.
- **The contradiction:** under the revised R50, the yes removes the mark from every house that carries one, this
  ledger's own id included. Neither the spec change nor the R50 row says the words change, and no test makes them
  change. With the proposed `_make_gate` patched into a scratch copy, that test still passes.
- **Why it matters:** the owner says yes to those words (R26; R47's words and change at the terminal). A builder who
  follows Task 26 as written ships a yes that says "marks" over an act that unmarks.
- **Fix:** have R50's row and Task 26's line say that, under `off` on a ledger never raised, the plan lists each house
  that carries a mark and says the yes removes it. Better still, set apart each house that carries this ledger's own
  id, the sign of an older copy (S2 and S3).

### S1. Should-fix: the body's `meta` doesn't tell the two apart in a log that ran R50 as first written

- **The claim:** "the body's `meta`, which sets `gate_raised` only when the gate is raised, tells the two apart"
  (spec :1756-1758). It holds only for rows written after the change.
- **What the probe showed:** in `r50old`, the old code ran a never-raised `gate off` over a foreign mark, and then the
  patched code ran `gate off` again. The two log rows hold the same body:
  `{"houses": [".engram/instances/lighthouse/graph.db"], "meta": {"gate": "off"}}`. Seq 2 marked the house and seq 3
  unmarked it.
- **Why it matters:** path 3 is exactly a home whose log holds the first kind of row. No code reads `houses` (it isn't
  projected, `permission_ledger.py:12, 1740`; only tests read it), so nothing breaks, but the claim is too strong.
- **Fix:** say it holds for rows written from this change on, and that a never-raised `off` row written before it
  lists houses it marked. Revise the module docstring at `permission_ledger.py:12` ("the houses it marked") to match.
- **A stale sentence:** R50's row still ends "The houses marked are in the act's `houses`, as before." That is the
  sentence Serenity's item 3 asked to change, and it now contradicts the sentence two before it. Drop it.

### S2. Should-fix: rule 2 gives one cause for three paths, and "closed is right" overstates path 3

- **The single cause:** spec :1749-1750 says such a house "comes from a ledger that was raised and is now an older copy
  of itself". Rule 2's clause (:1767-1769) says "so the ledger is an older copy from before the raise". The same draft
  then names two paths where the ledger is no older copy:
  - a first raise cut short;
  - R50 as first written, where nothing was restored and the home was genuinely `off`.
- **Path 3:** for that home, closed is a false reading. It is accepted because the code can't tell that home from a
  restore, and one `gate off` clears it. "Closed is right for both" (:1751) overstates it.
- **Why it matters:** a cause text built from rule 2 tells an owner whose raise has just failed, or whose home was
  always `off`, that their ledger is an older copy. That could send them off to restore something.
- **Fix:** give the clause's reason as "a house carries this ledger's id but this ledger was never raised". Have the
  cause text name the three ways that happens and which recovery fits each:
  - raise again after a cut-short raise;
  - `gate off` for a home that was `off`;
  - for a restore, S3.

### S3. Should-fix: the recovery for a restore doesn't say the older copy lost every later act

- **The gap:** a ledger restored from before the first raise has lost every act after its copy: revocations, denies,
  shortened and narrowed records. "Raises the gate again" (:1775-1777) puts the copy's allows back in force under
  `shadow` or `enforce`, including ones the owner had revoked.
- **The precedent:** R48's recovery for a lost tail says "with the lost acts made again".
- **Why it matters:** the closed reading is worth having because it makes the owner notice. Its text shouldn't send
  them straight to the one move that brings revoked allows back.
- **Fix:** the recovery sentence and the cause text say the ledger is older than its houses. They point first to
  putting back the newest copy, or to making the lost acts again before raising, and they say `gate off` lowers the
  home to `off`.

### S4. Should-fix: every first raise passes through "this id, never raised" (a fourth path)

- **How:** `_make_gate` commits each house's mark in its own `BEGIN IMMEDIATE` (`permission_ledger.py:3109-3122`,
  `:3144-3146`) inside `_make`, before `_append` writes the log row (:1819-1821; also :1919-1921 and :1940-1942).
- **What the probe showed:** in `cutshort`, a reader inside that window read `Gate(mode='off')` today and
  `Gate(mode='closed', ...)` with the change. That happens on every successful first raise, not only a failed one.
- **How long:** up to `BUSY_MS` = 5 s per busy house, then the append, up to `WRITER_TRIES` = 3 tries ×
  max(12 s, 350 ms/MB).
- **What closed means in that window:**
  - the daemon serves nothing;
  - `_lane_notes` raises `LaneNoteError`, so a re-lane is refused (`server.py:1364-1368`);
  - genome sync skips;
  - `share` and `permit` refuse;
  - the keep guard refuses as under `enforce`.
- **Fix:** failing closed while the gate moves is defensible, but the question was whether the three paths are the
  only ones, and they aren't. Name the window, its bound, and that closed is accepted there.

### S5. Should-fix: R50's reason and cost columns describe the old act

- **The old cost:** "Cost if wrong: `gate off` writes to houses that carry a foreign mark". It now writes to every house
  that carries any mark, this ledger's id included.
- **A behaviour change the columns don't show:** in probe `readonly_marked`, a read-only house carries this ledger's id
  after a restore.
  - Today `gate off` writes nothing to it and the home reads `off`.
  - With the change, `gate off` is refused ("could not be unmarked") and the home stays closed.
  - `gate shadow` still works, because it writes nothing to a house that already carries the id.
- **The reason column:** it still argues from "`gate off` on a ledger never raised marked nothing". It doesn't give the
  new reason for removing rather than re-marking: a re-mark with this id now itself reads closed under the new rule 2
  clause.
- **Fix:** revise both columns.

### N1. Nit: "A ledger whose gate was never raised marks no house" (:1748-1749) is too broad

- **The exception:** migration 029 writes `unreadable` into a house created while the ledger exists but can't be read,
  raised or not. `house_mark` returns `"unreadable"` at `permission_ledger.py:3073` and `:3077` before it reads
  `gate_raised` at :3080; `storage.py:329-341` writes it.
- **Probe `unreadable029`:** `house_mark` returned `unreadable` on a never-raised ledger.
- **Fix:** the deduction only needs "marks no house with its id", which holds apart from the named paths and S4. R50's
  "so a ledger never raised leaves no house marked" has the same flaw: a house whose mark can't be read is left as it
  is, and 029 can write `unreadable` later.

### N2. Nit: the cut-short path's citation and its error text

- **Other places with the same order:** the draft cites only `perform` (:1819-1821). The signed-proposal paths have the
  same order: `_on_proposal` (:1919-1921) and `_sign_alone` (:1940-1942).
- **A second way to cut it short:** `_mark_house` can fail at a later house. In probe `midmark`, the first house was
  marked, the error said "nothing was recorded, run the gate again", and the home then read closed.
- **Misleading text:** that error (`:3121-3122`) and `LedgerBusy`'s "nothing was written" are now misleading, because
  the houses were written and the home reads closed. The build should say so.

### N3. Nit: a rebuild is an older copy too

`rebuild` keeps `ledger_id` (`permission_ledger.py:2163`). That covers R48's named recovery for a lost tail, and also a
rebuild of any older copy.

- **Probe `rebuild`:** the rebuilt id equals the raised ledger's id, and the rebuilt ledger reads closed with the
  change.
- **Fix:** name it with path 1 ("restored or rebuilt from before the raise").

### N4. Nit: the clause is per served house

- **What happens:** after a restore, a house created then gets no mark, because 029 sees a never-raised ledger. A
  reader that serves only that house reads `off`.
- **Probe `probe_served`:** the published-house reader read `closed`, and the new house's own server read `off`.
- **What runs as `off` there:** the engram server's lane notes and genome sync read its own store
  (`server.py:1364`, `:1395-1398`).
- **What still refuses:** `share`, `permit` and the keep guard read the published house (`server.py:2325-2328`).
- **Fix:** it's acceptable, but say so. Or let the clause read every house of the home (at most 64), as rule 1 does.

### N5. Nit: name the upgrade effect

Any home that ran a never-raised `gate off` over a foreign mark reads closed once this is deployed, until its owner runs
`gate off` again. Per the posts, no known home is in that state:

- Serenity (fdbb4496): the Mac has no ledger file;
- Tardis (2134709b): the Pi's and Tardis's gates are raised.

Saying so tells the build's reviewer that the deploy closes nothing known.

### N6. Nit: "under a raised gate" reads as "already raised"

- **Where:** R50's row, and the spec at :1757.
- **The ambiguity:** read that way, it leaves out the first raise.
- **What the code does:** `mode != "off" or raised` (`permission_ledger.py:3131`, `permission_cli.py:761-763`).
- **Fix:** say "under `shadow` and `enforce`, and under `off` once the gate was raised".

### N7. Nit, older than this change: two gate acts can race

The gate act builds its body and touches houses from a State read before the write lock, and `_append_on` accepts a
verified key that changed in between.

- **The race:** a never-raised `off` running alongside a first raise can unmark houses the raise has just marked.
- **The result:** "no id while raised", which reads closed.
- **Fix:** none needed, since it fails closed. A case for the build's tests.

## Answers to the five questions

1. **Is "a ledger never raised marks no house" true today?** Not as worded. Apart from R50's never-raised `off`:
   - 029 marks `unreadable` when the ledger can't be read (N1);
   - `_make_gate` marks houses before the raise's row commits (S4 and path 2);
   - nothing else writes the mark (I searched the repo for writers of `permissions_ledger_id`: only
     `permission_ledger.py` and `storage.py`).

   For "no house carries its id", the answer is yes, apart from the named paths and S4.
2. **Are the three paths the only ones, is closed right, and does the recovery work?**
   - The three paths are not the only ones. Add every first raise's window (S4), a rebuild (N3), and propagation by
     `cli.py fork`, which copies an instance's meta whole (`cli.py:51-63`), though it only copies a state that already
     exists.
   - Closed is safe for each. For path 3 it is a false closed (S2).
   - The recovery works at the owner's terminal: probes `restore`, `cutshort`, `midmark`, `r50old` and
     `readonly_marked` all reach `shadow` or `off`. The one case where neither move works is a read-only marked house
     with the published house missing: a raise needs the published house, and `gate off` needs to write the house.
     The owner then makes the house writable, which R50's cost text already covers (S5).
   - Re-raising a restored copy brings back allows the owner had revoked (S3).
3. **Does removing the mark break anything?**
   - **Readers:** only `effective_gate` (:3028-3037) and `_make_gate` read the mark. Removing it gives `mark is None`,
     and with `gate_raised` unset that reads `off`.
   - **Rebuild and replay:** they replay bodies and never touch houses. `houses` is not projected, and the projection
     digest doesn't cover it.
   - **Tests:** with the change patched in, only `test_item6_gate_off_re_marks_a_house_whose_mark_is_not_this_ledgers`
     fails, in both its params (`tests/test_permissions_serenity_fixes.py:351-365`). That is expected, because it pins
     R50 as first written. The other 826 tests in the 37 files that touch the ledger or the gate pass, the
     gate-plan words test among them (M1).
   - **`meta` as the tell:** it is enough only for rows written after the change (S1).
4. **Could the closed rule lock someone out, or let something read `off` that should be closed?**
   - No lockout without a recovery (Q2).
   - It reads `off` where it arguably shouldn't for a reader that serves only a house made after the restore (N4).
   - It reads closed where `off` was right during every first raise (S4) and in path-3 homes (S2).
   - Nothing that should be closed reads `off` because of the removal: a never-raised `gate off` is the owner's yes.
5. **Overclaims and citations:**
   - **Overclaims:**
     - "marks no house" (N1);
     - "closed is right for both" and "an older copy" (S2);
     - "tells the two apart" (S1);
     - "leaves no house marked" (N1);
     - R50's leftover sentence (S1).
   - **Citations that check out:** `permission_ledger.py:1819-1821` (`_make`, `_stamp`, `_append`) and the review
     file's lines 162-165.
   - **Citations not followed through:** Task 26's words at plan :3403-3405 were not updated (M1).

## What I ran

- I read the whole diff (`git diff origin/main...HEAD`) and spec section 12.3. In the worktree's `engram/` I read:
  - `effective_gate`, `house_mark`, `_house_id`, `_make_gate`, `_mark_house`, `perform`, `_make`, `_append`,
    `_append_on`, `_project`'s body keys, `_on_proposal`, `_sign_alone`, `rebuild`'s id and `houses()`;
  - `storage.py`'s 029 hook;
  - `permission_cli.py`'s `_gate`, `gate_plan_lines` and `_marks_unmarked`;
  - `cli.py fork`;
  - the server's and daemon's gate readers;
  - every test that names R50, `gate_raised`, `_house_id` or `permissions_ledger_id`.
- I read station posts 2134709b and fdbb4496 (Serenity's three items).
- I exported HEAD twice into the scratch directory: `orig/`, and `patched/`, which has the proposed rule.
  `effective_gate` closes when a mark equals this ledger's id and `gate_raised` is unset, and a never-raised `off`
  deletes the mark of every house that carries one and lists it in `houses` (`apply_patch.py`).
- `probe.py` runs these scenarios against either tree: `restore`, `cutshort`, `midmark`, `r50old` (old code then the
  patched code on the same home), `unreadable029`, `rebuild` and `readonly_marked`. `probe_served.py` covers N4. Output
  is in `probes_out.txt`. Every tree used the venv at `wt-imprint-state/engram/.venv`.
- On `patched/`, I ran the gate suites `test_permissions_{gate,serenity_fixes,recheck_fixes,migration_029,cli_records,
  daemon_gate,edges}`: 143 passed and 2 failed, both `test_item6...` params.
- On `patched/`, I also ran all 37 test files that touch the ledger or the gate (828 tests): 826 passed and 2 failed,
  the same two `test_item6...` params, in 925 s. Unpatched, `orig/` passes those two and the recheck file (7 passed).

## Re-check of the third draft (add4dd15)


Reviewer: the same fresh reviewer, on Tardis, 2026-11-18. I only read files and ran probes. I edited, committed and
posted nothing, I left the main checkout and `~/.engram/` alone, and every fixture was in scratch. The code is
unchanged since 33d940ac, so the earlier probes and the 828-test run still hold. I ran one new probe,
`probe_off_cut.py`, on the patched copy.

## Verdict: APPROVE WITH CHANGES

The draft resolves M1, S1 to S5 and N1, N3, N4, N6 and N7. N2 and N5 are partly resolved. One change is left before
approval: the plan's own lists of what changes under `off` are stale (R1). It is a mechanical text change, and once it
goes in as written the draft is approved with no further reading. The nits are optional.

## The thirteen findings

| # | Resolved? | Notes |
|---|---|---|
| M1 | Yes | R50's row and Task 26 (plan :3404-3405) now say that under a never-raised `off` the plan lists each house that carries a mark and that the yes removes it. They name `gate_plan_lines`, the words test and `test_item6`. What's left is in R3. |
| S1 | Yes | Spec :1769-1771 limits the meta tell to rows written from this change on and says what an earlier row means. The plan names the docstring revision, and R50's stale sentence is gone. "It sets `gate_raised` whenever the act marks" matches `_make_gate` (:3131-3133). |
| S2 | Yes | Rule 2's clause (:1785) reads "while this ledger was never raised (one of the paths above)". :1762-1763 says closed is false in path 3 and during path 2's window. The cause text names each path and its move (:1792-1797). |
| S3 | Yes | For an older ledger: put back the newest copy, or make the lost acts again, before raising. The draft says why, and cites R48. I checked that it can be done: no `engram-permissions` act refuses under a closed gate (`effective_gate` appears in `permission_cli.py` only at :258 and :929, both in the sweep). |
| S4 | Yes | Spec :1756-1758 names the window and accepts closed for it. The bound it gives is the one I wrote, and mine was incomplete (R2). |
| S5 | Yes | R50's reason and cost columns are revised: they cover the read-only house, `gate shadow` still working, and the refusal at a later house naming the houses it changed. |
| N1 | Yes | "writes its id into no house", with 029's `unreadable` named. The new sentence still contradicts paths 2 and 3 (R4). |
| N2 | Partly | The proposal-path lines (:1919-1921, :1940-1942) and the failure at a later house are in. An append that fails after the marks is not covered (R5). |
| N3 | Yes | Path 1 now covers a rebuild, and the citation is right (`permission_ledger.py:2163`). |
| N4 | Yes, accepted as stated | I agree with the choice (see below). One wording nit (R6). |
| N5 | Partly | P 12.3 now names the deploy effect and why no known home is in path 3. The plan's lists of what changes under `off` don't (R1). |
| N6 | Yes | "under `shadow` and `enforce`, and under `off` once the gate was raised", in R50's row and spec :1768-1769. |
| N7 | Yes | The race is named (:1774-1775). |

## The two choices

- **N4: reading the houses each reader serves, accepted rather than widened.** I agree.
  - **The cost of widening.** Every reader would read every house's `meta` at every request: the daemon at every
    frame, and each engram server on every lane note. It would also need rule 1's cap of 64, past which a raised home
    would read closed for having many houses. Every raised home would pay that, to catch a narrow case.
  - **The case it would catch.** A house made after a restore. 029 gives it no mark because the ledger says it was
    never raised, so its server's `off` matches what the ledger holds.
  - **The owner still notices.** What the owner meets still reads closed, because `share`, `permit` and the keep guard
    read the published house (`server.py:2212`, `:2497`, `:2635`), and the raise marked it.
  - **What is left.** The house's own lane notes and genome sync run as `off`. That house's genome copies get no
    subjects, as under any `off`. That's acceptable.
- **S4: closed during every first raise's window, accepted rather than reordered.** I agree.
  - **Reordering doesn't remove the window.** If the log row commits first, then until the marks are written each
    house carries no id while the gate is raised. That reads closed under the existing clause, for the same length of
    time.
  - **It breaks what `houses` means.** The row would have to be written before the marks, so it would list the houses
    the act means to mark. A marking that failed at a later house would leave a committed row naming houses it never
    marked, against R17 and `test_the_log_body_of_the_first_raise_records_the_mode_and_the_houses_it_marked`.
  - **Its one merit.** The new clause's causes would shrink to paths 1 and 3. That doesn't outweigh a log that
    records intent instead of fact.
  - **The windows aren't new.** A cut-short act was always visible to readers, as "no id while raised" or as this
    state.

## Remaining items

### R1. Should-fix: the plan's lists of what changes under `off` still describe R50 as first written

These three places say "the gate act re-marks every house that carries `unreadable` or another ledger's id, so
`gate off` opens it (R50)":

- the plan's overview, :20-21;
- the "Nothing live" constraints, :52-53;
- gate G2, :3984.

That is no longer what a never-raised `off` does: it removes the mark. None of the three lists the new closed reading,
yet each sets out to list every change a home with a ledger sees under `off`. G2 says "they behave as today except for
changes that only refuse or narrow", and the new clause is such a change. It reads closed in a path-3 home on deploy,
and for the length of every first raise.

**Fix:** in all three, say that the act re-marks under a raised gate and removes marks under a never-raised `off`.
Add that a house carrying the ledger's id under a never-raised ledger reads closed (P 12.3, "Before the raise").

### R2. Nit: the window's bound counts only the lock waits, and my S4 figure was the same

Each of the append's three tries first runs `_base_key()` outside the lock (`permission_ledger.py:1281-1296`). On a
memo miss, which is the case after another writer's unverified commit, that is a full check. The section 2 review
measured it at 20.6-22.1 s at the reference shape (`2026-11-03-projection-digest-section2-review.md:145`).

**Fix:** say "plus the append's own waits for the lock (up to 3 × max(12 s, 350 ms per MB)) and, on a retry, a full
check".

### R3. Nit: two words of M1's fix

- **"The sign of an older copy."** R50's row and Task 26 call a house carrying this ledger's own id "the sign of an
  older copy". That was my wording in M1, and it's the single-cause claim S2 removed from the spec. Say "the sign of
  one of P 12.3's three paths".
- **Task 27 still says "mark".** Task 27's Step 3 (plan :3563-3565) still says the gate prints "every house of
  `houses(ENGRAM_HOME)` it will mark", and Task 26 says it prints "as Task 27's `gate` prints". `gate_plan_lines` is
  shared, so the build will get this right anyway, but the text should match.

### R4. Nit: the opening sentence of the new bullet contradicts its own paths

Spec :1749-1750 says "A ledger whose gate was never raised writes its id into no house". Path 2, just below it, is a
never-raised ledger writing its id during its first raise, and path 3 is the old code doing so.

**Fix:** "after this change, a ledger never raised writes its id into no house except during its first raise (path
2)".

### R5. Nit: an append that fails after the houses changed (N2's remainder)

R50's cost now covers a marking that fails at a later house. It doesn't cover `_append` failing after every house has
already changed. That happens with `LedgerBusy`'s "nothing was written, so try again" (`permission_ledger.py:1547-1548`),
with a cut tail, or with a stop between the two steps:

- **After a first raise:** the houses stay marked and the home reads closed.
- **After a never-raised `off`:** the probe `probe_off_cut.py` restored an older ledger, so the home read closed. Then
  `gate off`'s log write failed after the marks were removed. The home read `off`, and the log held no gate row.

The owner said yes to that state. But the message says nothing changed while the gate moved from closed to `off`.

**Fix:** have the build's refusal say the houses were changed and what the gate reads now.

### R6. Nit: "as its other clauses do" (:1772)

Rule 2's first clause, "no ledger file but some house carries the id", reads every house, not the served ones.

**Fix:** say "as its other clauses about houses do, when there is a ledger".

### R7. Nit: the cause text is long, and is read in many places

- **Where it shows.** The daemon logs it once per request (`lighthouse_daemon.py:993-998`). `share`, `permit` and
  `LaneNoteError` return it. `test_permissions_gate.py:83` is named for causes being "a short sentence".
- **The length.** Naming all three paths with their moves is several sentences.
- **Fix, optional:** the cause states the fact in one sentence and names `engram-permissions gate`. That command's plan
  already sets apart the houses carrying this id and can carry the paths and their moves.

### R8. Nit: cite the fork

Spec :1762's "(`cli.py fork`)" could be `engram/cli.py:51-63`, to match the spec's other citations.

## Checked and right

- **The review the spec cites** exists at the cited path with my verdict whole.
- **Rebuild:** `rebuild` keeps `ledger_id` (:2163).
- **The signed-proposal paths** run in the same order (:1919-1921, :1940-1942).
- **The fork:** it copies the mark. `stamp_fork` deletes only the identity keys (`store_identity.py:212`).
- **The keep guard** reads the published house (`server.py:2212`).
- **Houses are WAL** (`storage.py:141`), so the "5 s per busy house" is the write lock's wait.
- **The R50 row's test list** names the words test and `test_item6`, the only tests the patched run failed.
- **No other text** in the spec or plan states the never-raised behaviour, apart from R1's three places.
