# Imprints, revision 9: each send asks the ledger again

Tardis, 2026-11-20, draft 4, approved: the fresh reader's confirming read of draft 3 named four text edits and no further reading, and they are made. A change to the imprint spec (`2026-10-25-store-imprint-design.md`, revision 8), for board
item `fix:imprint-send-rechecks-ledger`, from Serenity's question on train 1140. It changes what may leave a person's
machine, so it takes the safety-code path: a fresh reader of this text, a test-first build, and a fresh reader of the
code. Draft 1 (4f7d9032) got DO NOT APPROVE with twelve named changes from a fresh reader, and its re-check of draft 2
(61c5ce8d) APPROVE WITH NAMED CHANGES, N1 to N7, and its confirming read of draft 3 (14d0c3d7) the same, with four
edits. All are made here, and the last section says where. This text and its build stay off GitHub until the fix is merged and live.

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

1. **The plan and the build record what they read.** The plan file gains `ledger`: the resolved path of the ledger
   the plan actually read (its context's ledger), or null when it read none. `read` and `build` compare the resolved
   path of the ledger they open with it, and refuse when they differ or when it is gone ("Run the plan again."). They
   compare ledger paths, never engram homes. The recorded path comes from the plan's own ledger, so a test fixture
   that hands `make_plan` a ledger needs no engram home, and the CLI's `_plan` uses one home for both. No `ledger_id`
   is recorded: an older copy of the same ledger restored at the same path carries the same id, so it wouldn't tell
   that case apart (the code reader's 8). A ledger the owner restores from an older copy before a send is outside this check, as it is outside the build's; revision 8's closing read catches only a restore during the run. The build always writes, beside the package and never sent, `sources.json`: each
   shipped semantic's recorded source episodes with each episode's lane, as the build read them (Ŝ needs
   src(s) ⊆ Ê, 5.2), `[]` when there are none. It is written in R30's form, one element per line, streamed. It names
   episodes that stay home, so it goes when `imprint.db` goes (D24): the agent's `_drop_local_copy` deletes both. A
   plan whose file has no `ledger` key, or an imprint with no `sources.json`, was made before revision 9, and its send
   refuses with "Run the plan again." A missing key never reads as null.
2. **Each send run asks the ledger again before anything leaves.** When `build --if-needed` finds the plan built, it
   first deletes the imprint's `checked.json` and `refused.json` if they are there. When the imprint's `imprint.db` is
   gone and `send.json` exists (D24, after a final status), it checks nothing, writes no stamp, and leaves the agent to
   report the status. When `imprint.db` is gone and no request was sent, it refuses ("Run the plan again."). Otherwise
   it opens
   the ledger at the plan's recorded path and takes one checked State, as a build does (revision 8: `LedgerFacts`, the
   projection digest or SQLite's integrity check, and the closing read). It then asks:
   - **The memories:** every shipped episode and semantic, with its id and lane read from the imprint's own
     `imprint.db`, opened read-only (the file that leaves, which the manifest hashes).
   - **The sources:** every source episode in `sources.json`, with its lane.
   - **The questions:** for each, the ones the build asked of `base(m)` (5.2), at the plan's time, as the build uses:
     the latest lane note against the package's lane (D40), `cosubjects(m)` up its `copies` chain, and with
     co-subjects `needs_yes` when the plan isn't `home`, then `retired(m)`, `bound(m)` and `denied(m)`. Also new: the
     fresh `cosubjects(m)` must be a subset of the memory's carried rows in `imprint.db`'s `imprint_subjects`, read by
     its primary key (memory_id, layer, subject) one chunk at a time, or the carried counts the owner acknowledged
     (D27) would be wrong.
   - **The store's row:** asked once (D37, `check_owner`).
   The memories are read in a stream, with `prefetch`, never all held at once.
3. **A ledger that's gone refuses.** If the plan recorded a ledger and none is at that path now, the check refuses.
   If the plan recorded none and the check's own engram home has one now, the check runs against it.
4. **A refusal stops the send, and the agent says what's out there.** If any answer differs, the check sends nothing
   and makes no stamp. Before any request was sent, it refuses with `PlanRefused`: "Your permissions changed since
   this imprint was built: N memories would now stay home. Nothing was sent. Run the plan again." The count is a
   number, with no names. When `send.json` exists, a request is at the station, and the engram check has no station
   client. So the check writes `refused.json` in the imprint's folder (0600: `imprint_id`, `at`, the count) and exits
   with code 5. The `imprint-send` recipe catches exactly that code and runs the agent's `send --plan … --refused`,
   with the engram step in a subshell, `(cd engram && …)`, so the agent runs from the checkout's root. The agent
   reads `refused.json`, goes on only when it names this folder's imprint, and reads the request's status. In `requested` or `allowed`, while the upload is unfinished, it withdraws the
   request as `make imprint-withdraw` does (D17: the ship's key, no password). It prints the request's short id, what
   the station held (nothing of the package while `requested`; the parts sent so far while `allowed`), that the
   request is withdrawn, and not to allow the link if it is still open. It ends with `STATUS: refused` (exit 1). In
   `received` or `approved` it withdraws nothing. It says the station holds the whole package and that withdrawing is
   the owner's choice, by `make imprint-withdraw`, and ends with `STATUS: refused` (exit 1). In `deleting`, in a final
   status, or `admitted` with `imprint.db` still on disk, it reports as `send` does and drops the local copy on a
   final status. A ledger that can't be read, or that changed during the check, and
   `check_owner`'s refusals, end "nothing was sent" at send.
5. **A stamp ties the send to a check, and is read at each step that sends.** On success the check writes
   `checked.json` in the imprint's folder, atomically, at 0600: `{"imprint_id": …, "at": <unix seconds when the State
   was read>, "seq": <its seq>}`. The agent's `send` reads it before each POST of the request, before the PUT of the
   manifest, and before a run's first part. It goes on only when the file exists, names this folder's imprint, and its
   `at` is no more than 300 s old and not in the future. Otherwise it sends nothing more, ends with `STATUS:
   check-again` (exit 3 in the agent's map, so make's `Error 3`, expected) and says to run `make imprint-send` again,
   which checks first. The stamp is local, and no request, manifest or receipt carries it.
6. **A fresh build checks too.** After a fresh build, `build` runs the same check on a new State before it writes the
   stamp, so a deny marked during the build, which the build's closing read passes by design, stops the request in
   the same run.
7. **The wait fits the timeout and the stamp.** A later run's wait for the yes ends at the earlier of 540 s less the
   check's own time and the stamp's 300 s. So a run stays inside the 10-minute Bash timeout CLAUDE.md gives `make
   imprint-send`, and no wait outlives its stamp.

## What it doesn't close

- **A change during one run's upload.** A deny recorded after a run's last stamp read, while its parts are going, is
  not seen by that run. Each step that sends reads a stamp no more than 300 s old.
- **A stamp or a marker written by hand,** or a package edited by hand. They are outside this spec.
- **The station side once the upload is complete.** Admission can't read the owner's ledger. A deny recorded after
  the last part applies to this imprint only through the owner's `make imprint-withdraw`, which item 4's message
  names, and to later ones by their checks.
- **Store-side changes after the build,** such as an erase or an unshare (which changes shared(m, A)). They aren't
  ledger facts. They are revision 8's, unchanged.
- **A plan made under the wrong engram home,** which reads no ledger. The plan records the home and path it read
  (item 1). Choosing the home is the owner's.

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
| Each question stops it | A retirement; `bound`; a re-lane finished after the build (the note names the new lane, the package the old); a new co-subject on a `home` plan, not among its carried `imprint_subjects` rows; any co-subject on a not-home plan | One that checks denies only, or reads the store's lane |
| Up the chain and down to sources | A deny on a copy's source; with `--layers semantic`, a deny on a semantic's source episode | One that reads a ref's own rows, or skips sources |
| An ordinary append passes | A marked `_put` that changes no answer: the send goes | One that refuses on any change |
| A ledger gone | The plan read a ledger, then it is moved: refused; the plan read none and one appears with a deny: refused; `read` and `build` under another engram home: refused; a plan from before revision 9: refused | One that passes with no ledger, or opens whatever home it's given |
| The stamp | No stamp, a 301 s stamp, one in the future, another imprint's: each `send` step refuses with `check-again`; a refused check leaves no stamp from before; a stamp read before the manifest after a 540 s wait is stale and stops it | One that keeps an old stamp, or reads it once |
| A refusal after a request | Exit 5 and `refused.json`; the recipe runs `send --refused`: in `requested` and in `allowed` with parts sent, the short id, what the station held, the withdrawal made, `STATUS: refused`; in `received`, no withdrawal and the owner told | One that says "nothing was sent" there, never reaches the agent, or withdraws a finished upload |
| After D24 | `admitted`, then `make imprint-send` again: no check, no stamp, no withdrawal, and the agent reports `admitted` | One that withdraws an admitted imprint |
| The wait | An `allowed` arriving after the stamp's 300 s: the run ends at the stamp, with `check-again` | One that waits past its stamp |
| Reads as the build does | A torn page, an unstamped ledger's failed integrity check, a ledger moved during the check: the build's refusal, ending "nothing was sent" | One that reads by direct SQL |
| Nothing is said of anyone | Refusals hold counts only; the stamp only its three fields | One that names a co-subject |
| The budget | The cap test (`ENGRAM_PI_BUDGET=1`) gains the check at the reference store with one deny and a copies chain: under 384 MiB, its time recorded on both machines | One that loads every row |

## Decisions

1. **Ask the build's questions again, not "did anything change".** Ordinary work writes the ledger.
2. **Ask them of what leaves:** the package's own rows and the sources the build read.
3. **A stamp no more than 300 s old, read before each step that sends,** ties the agent's send to the check.
4. **A refusal while the upload is unfinished withdraws its request,** through the agent, and says what the station held;
   after the upload it says what the station holds and leaves withdrawing to the owner.

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
- the Makefile's `imprint-send` recipe: exit 5 runs `send --refused`, the engram step in a subshell;
- the agent: `send --refused`, the stamp reads, `STATUS: check-again` and `refused`, and `_drop_local_copy`;
- CLAUDE.md's imprint section: the refusal, the withdrawal, `STATUS: refused` and `STATUS: check-again`.

## The reader's changes on draft 1, and where each is made

| Named change (4f7d9032) | Where |
| --- | --- |
| 1. Semantics' source episodes | Asked 1 (`sources.json`), 2; the table |
| 2. Lanes from `imprint.db` | Asked 2; the table (re-lane) |
| 3. A missing ledger | Asked 1 (`ledger`), 3; the table |
| 4. Revision 8's sentences, and a new co-subject | Why; Asked 2 (subset of the carried rows; first subjects.json, then `imprint_subjects` by N3); Sections changed |
| 5. No stamp left after a refusal | Asked 2 (deleted first), 4 |
| 6. The stamp read at each step that sends | Asked 5, 7; Doesn't close |
| 7. A fresh build checks on a new State; `imprint_id` | Asked 5, 6 |
| 8. A refusal once a request exists | Asked 4; Sections changed (13, CLAUDE.md) |
| 9. The budget | The budget; Asked 2 (streamed), 7 |
| 10. "Nothing was sent"; the plan's time | Asked 2, 4 |
| 11. Tests | The table |
| 12. The G18 sentence | Cut |

| Named change (re-check of 61c5ce8d) | Where |
| --- | --- |
| 10. `check_owner`'s sentences | Asked 4 |
| N1. The refusal reaches the agent | Asked 4 (`refused.json`, exit 5, `send --refused`); Sections changed (Makefile); the table |
| N2. No withdrawal after D24 or after the upload | Asked 2 (no `imprint.db`), 4 (statuses); Doesn't close; the table |
| N3. Carried rows from `imprint_subjects`, chunked | Asked 2 |
| N4. Old plans, the recorded home, `read` and `build` | Asked 1, 3; the table |
| N5. The wait ends at the stamp | Asked 7; the table |
| N6. `check-again`'s exit 3 | Asked 5 |
| N7. `sources.json`'s form and keeping | Asked 1 |

| Named change (confirming read of 14d0c3d7) | Where |
| --- | --- |
| 1. Compare ledger paths, not homes; fixtures pass `engram_home` | Asked 1, 3 |
| 2. `_drop_local_copy` deletes `sources.json` | Asked 1; Sections changed (the agent) |
| 3. The recipe's subshell | Asked 4; Sections changed |
| 4. Other statuses; stale `refused.json`; a missing key; `[]`; a gone `imprint.db` with no request | Asked 1, 2, 4 |
