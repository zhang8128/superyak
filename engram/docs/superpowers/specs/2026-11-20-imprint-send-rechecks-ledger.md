# Imprints, revision 9: each send asks the ledger again

Tardis, 2026-11-20, draft 2. A change to the imprint spec (`2026-10-25-store-imprint-design.md`, revision 8), for board
item `fix:imprint-send-rechecks-ledger`, from Serenity's question on train 1140. It changes what may leave a person's
machine, so it takes the safety-code path: a fresh reader of this text, a test-first build, and a fresh reader of the
code. Draft 1 (4f7d9032) got DO NOT APPROVE with twelve named changes from a fresh reader. All twelve are made here, and
the last section says where. This text and its build stay off GitHub until the fix is merged and live.

## Why

Revision 8 decided that a deny or a co-subject recorded at home after the build "reaches the imprint only in step 2"
(5.2, `denied(m)`'s last sentence and the paragraph before `retired(m)`). This revision ends that limit for the
owner's own ledger. Today:
- `make imprint-send` runs `imprint.py build --plan … --if-needed`, which returns an already built plan's `Built`
  without opening the ledger (`imprint.py`, `build`'s `if_needed` branch);
- the agent's `send` (`agent/superyak_agent/imprint.py`) posts `request.json`, then after the owner's yes the manifest
  and the parts of `imprint.db`, and reads no ledger;
- the station's admission (10) can't read the owner's ledger.

**Why not refuse on any ledger change:** the owner's ordinary work writes the ledger: a share, a re-lane, a kept
`remember`, a genome sync, a CLI act (revision 8's list). A send refused on any append would refuse on an active
machine almost every time.

## What is asked

1. **The build records what it read.** The plan file gains `ledger`: the ledger's resolved path when the plan read one,
   or null when the machine had none. The build writes, beside the package and never sent, `sources.json`: for each
   shipped semantic, each recorded source episode and that episode's lane, as the build read them (Ŝ needs
   src(s) ⊆ Ê, 5.2).
2. **Each send run asks the ledger again before anything leaves.** When `build --if-needed` finds the plan built, it
   first deletes the imprint's `checked.json` if one is there. Then it opens the ledger at the plan's recorded path and
   takes one checked State, as a build does (revision 8: `LedgerFacts`, the projection digest or SQLite's integrity
   check, and the closing read). It then asks:
   - **The memories:** every shipped episode and semantic, with its id and lane read from the imprint's own
     `imprint.db`, opened read-only (the file that leaves, which the manifest hashes), never from a side file.
   - **The sources:** every source episode in `sources.json`, with its lane.
   - **The questions:** for each, the ones the build asked of `base(m)` (5.2), at the plan's time, as the build uses:
     the latest lane note against the package's lane (D40), `cosubjects(m)` up its `copies` chain, and with
     co-subjects `needs_yes` when the plan isn't `home`, then `retired(m)`, `bound(m)` and `denied(m)`. Also new: the
     fresh `cosubjects(m)` must be a subset of the memory's rows in the imprint's `subjects.json`, or the carried counts
     the owner acknowledged (D27) would be wrong.
   - **The store's row:** asked once (D37, `check_owner`).
   The memories are read in a stream, in the build's order, with `prefetch`, never all held at once.
3. **A ledger that's gone refuses.** If the plan recorded a ledger and none is at that path now, the check refuses.
   If the plan recorded none and one is at the plan's engram home now, the check runs against it.
4. **A refusal stops the send and says what's out there.** If any answer differs, the run refuses before it sends
   anything, with `PlanRefused`, and makes no stamp. Before any request was sent: "Your permissions changed since this
   imprint was built: N memories would now stay home. Nothing was sent. Run the plan again." The count is a number,
   with no names. When `send.json` exists, a request is at the station. Then the refusal names the request's short id
   and what the station holds in its status (9's table: nothing of the package while `requested`; parts or the whole
   package once `allowed` or `received`). It withdraws the request, as `make imprint-withdraw` does (D17). And it says
   not to allow the link if it is still open. A ledger that can't be read, or that changed during the check, refuses
   with the build's sentences, ending "nothing was sent".
5. **A stamp ties the send to a check, and is read at each step that sends.** On success the check writes
   `checked.json` in the imprint's folder, atomically, at 0600: `{"imprint_id": …, "at": <unix seconds when the State
   was read>, "seq": <its seq>}`. The agent's `send` reads it before each POST of the request, before the PUT of the
   manifest, and before a run's first part. It goes on only when the file exists, names this folder's imprint, and its
   `at` is no more than 300 s old and not in the future. Otherwise it sends nothing more, ends with `STATUS:
   check-again` (make's `Error 3`, expected) and says to run `make imprint-send` again, which checks first. The stamp
   is local, and no request, manifest or receipt carries it.
6. **A fresh build checks too.** After a fresh build, `build` runs the same check on a new State before it writes the
   stamp, so a deny marked during the build, which the build's closing read passes by design, stops the request in
   the same run.
7. **The wait fits the timeout.** A later run's wait for the yes (540 s) is shortened by the check's own time, so a
   run stays inside the 10-minute Bash timeout CLAUDE.md gives `make imprint-send`.

## What it doesn't close

- **A change during one run's upload.** A deny recorded after a run's last stamp read, while its parts are going, is
  not seen by that run. Each step that sends reads a stamp no more than 300 s old.
- **A stamp written by hand,** or a package edited by hand. They are outside this spec.
- **The station side.** Admission still can't read the owner's ledger. A deny recorded after the last part applies to
  this imprint only through `make imprint-withdraw`, and to later ones by their checks.
- **Store-side changes after the build,** such as an erase or an unshare (which changes shared(m, A)). They aren't
  ledger facts. They are revision 8's, unchanged.
- **A plan made under the wrong engram home,** which reads no ledger. The plan records the path it read (item 1).
  Choosing the home is the owner's.

## The budget

Revision 8 measured, on Tardis, not a Pi, at a reference ledger with no `copies` rows: the State in 6.8 s, 100,000
co-subject reads in 6.7 s, a 106 MiB peak in a process holding only the State. The check reads more: a `copies` chain
adds up to 4 reads per memory, and the sources add theirs. Its memory holds by 14.1's arithmetic for the plan row
(State 140.9 MiB, 286.3 in all, under 384), since the memories are streamed. Its time is measured on Tardis and on the
Pi in the cap test, and must stay under 60 s at the reference store, or the wait in item 7 shrinks to fit.

## How we know it is done

| What | Shown by | A wrong change caught |
| --- | --- | --- |
| A deny after the build stops the send | Build, then a co-subject's deny by a writer: the engram step refuses with the count, and `send` posts no request; the same after the request and the yes, with no manifest or part sent and the request withdrawn | One that reads the ledger only at build |
| A deny during the build stops the request | A marked deny appended during the build, after its State: the fresh build's check refuses, and no request is posted in that run | One that stamps from the build's own State |
| Each question stops it | A retirement; `bound`; a re-lane finished after the build (the note names the new lane, the package the old); a new co-subject on a `home` plan, not in subjects.json; any co-subject on a not-home plan | One that checks denies only, or reads the store's lane |
| Up the chain and down to sources | A deny on a copy's source; with `--layers semantic`, a deny on a semantic's source episode | One that reads a ref's own rows, or skips sources |
| An ordinary append passes | A marked `_put` that changes no answer: the send goes | One that refuses on any change |
| A ledger gone | The plan read a ledger, then it is moved: refused; the plan read none and one appears with a deny: refused | One that passes with no ledger |
| The stamp | No stamp, a 301 s stamp, one in the future, another imprint's: each `send` step refuses with `check-again`; a refused check leaves no stamp from before; a stamp read before the manifest after a 540 s wait is stale and stops it | One that keeps an old stamp, or reads it once |
| A refusal after a request | In `requested`, `allowed` with parts sent, and `received`: the short id, what the station holds, the withdrawal made | One that says "nothing was sent" there |
| Reads as the build does | A torn page, an unstamped ledger's failed integrity check, a ledger moved during the check: the build's refusal, ending "nothing was sent" | One that reads by direct SQL |
| Nothing is said of anyone | Refusals hold counts only; the stamp only its three fields | One that names a co-subject |
| The budget | The cap test (`ENGRAM_PI_BUDGET=1`) gains the check at the reference store with one deny and a copies chain: under 384 MiB, its time recorded on both machines | One that loads every row |

## Decisions

1. **Ask the build's questions again, not "did anything change".** Ordinary work writes the ledger.
2. **Ask them of what leaves:** the package's own rows and the sources the build read.
3. **A stamp no more than 300 s old, read before each step that sends,** ties the agent's send to the check.
4. **A refusal after a request withdraws it,** and says what the station holds.

## Sections changed in the imprint spec

When approved, this is folded in as revision 9:
- a row in the revision history;
- 5.2: the two sentences on what is added after the build (the paragraph before `retired(m)`, and `denied(m)`'s
  last sentence) now say each send asks again;
- 6.1: the build writes `sources.json` and the plan's `ledger`;
- 9 and 13: `STATUS: check-again`, the refusal and its withdrawal, and the shorter wait;
- 16: the table above;
- D44: "Each send run asks the ledger the build's questions again, for the package's own rows and the semantics'
  sources, and the agent's send goes on only with that check's stamp, no more than 300 s old, read before each step
  that sends."
- CLAUDE.md's imprint section: the refusal, the withdrawal and `check-again`.

## The reader's changes on draft 1, and where each is made

| Named change (4f7d9032) | Where |
| --- | --- |
| 1. Semantics' source episodes | Asked 1 (`sources.json`), 2; the table |
| 2. Lanes from `imprint.db` | Asked 2; the table (re-lane) |
| 3. A missing ledger | Asked 1 (`ledger`), 3; the table |
| 4. Revision 8's sentences, and a new co-subject | Why; Asked 2 (subset of subjects.json); Sections changed |
| 5. No stamp left after a refusal | Asked 2 (deleted first), 4 |
| 6. The stamp read at each step that sends | Asked 5, 7; Doesn't close |
| 7. A fresh build checks on a new State; `imprint_id` | Asked 5, 6 |
| 8. A refusal once a request exists | Asked 4; Sections changed (13, CLAUDE.md) |
| 9. The budget | The budget; Asked 2 (streamed), 7 |
| 10. "Nothing was sent"; the plan's time | Asked 2, 4 |
| 11. Tests | The table |
| 12. The G18 sentence | Cut |
