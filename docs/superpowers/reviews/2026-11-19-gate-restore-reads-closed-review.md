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
