# Imprints, revision 9: each send asks the ledger again

Tardis, 2026-11-20, draft 1. A change to the imprint spec (`2026-10-25-store-imprint-design.md`, revision 8), for board
item `fix:imprint-send-rechecks-ledger`. Serenity's question on train 1140 (all hands 9a5011b6) found it, and Tardis's
answer (e31e17b8) traced it. It changes what may leave a person's machine, so it takes the safety-code path: a fresh
reader of this text, then a test-first build and a fresh reader of the code.

## Why

Revision 8 reads the ledger as one checked State per plan, read and build, and the build's closing read refuses a
ledger that moved beyond what a writer marked. A marked append after the build's State passes by design (I 5.2,
`test_a_marked_append_during_the_run_passes`), so the build ships as of that State. After the build nothing reads the
ledger again:
- `make imprint-send` runs `imprint.py build --plan … --if-needed`, which returns an already built plan's `Built`
  without opening the ledger (`imprint.py` `build`, the `if_needed` branch);
- the agent's `send` (`agent/superyak_agent/imprint.py`) posts `request.json`, then after the owner's yes the manifest
  and the parts of `imprint.db`, and reads no ledger;
- the station's admission (10) can't read the owner's ledger, which stays on the owner's machine.

So a deny or a retirement recorded after the build's State, during the build or in the minutes or days before the
upload, is never applied to that imprint. That's the window from the build's State to the upload's last part, not only
the build. Today CLAUDE.md's rule that Andy approves no IMPRINT item with other people above 0 before gate G18 keeps an
imprint with a co-subject from admission. This revision closes the window in the code.

**Why not refuse on any ledger change:** the owner's ordinary work writes the ledger. A share, a re-lane, a kept
`remember`, a genome sync or a CLI act each append (revision 8's own list). A send refused on any append would refuse
on an active machine almost every time.

## What is asked

1. **Each send run asks the ledger again before anything leaves.** When `build --if-needed` finds the plan already
   built, it opens the ledger and takes one checked State, as a build does (revision 8: `LedgerFacts`, the projection
   digest or SQLite's integrity check, and the closing read). For every memory in the package, read from the
   imprint's own `objects.json` (R30), it asks the questions the build asked of `base(m)` (I 5.2): the latest lane
   note (D40), `cosubjects(m)`, and with co-subjects `needs_yes`, `retired(m)`, `bound(m)` and `denied(m)`. It asks the
   store's row (D37, `check_owner`) once.
2. **A memory that would now stay home stops the send.** If any memory would now stay home, the run refuses before it
   sends anything (a request, a manifest or a part), with `PlanRefused`: "Your permissions changed since this imprint
   was built: N memories would now stay home. Nothing was sent. Run the plan again." The count is a number, with no
   names. A ledger that can't be read or that changed during this check refuses as the build does, with the build's
   sentences. A change that leaves every answer as it was passes.
3. **The check is fresh for the send that follows it.** On success the check writes `checked.json` in the imprint's
   folder, atomically, at 0600: `{"at": <unix seconds>, "seq": <the State's seq>}`. The agent's `send` refuses unless
   that file exists and its `at` is no more than 300 s old and not in the future: "Run make imprint-send, which checks
   your permissions first; nothing was sent." The file is local, and no request, manifest or receipt carries it. A
   fresh build writes it too, since the build has just asked the same questions.
4. **What a refusal leaves.** Nothing is deleted on the owner's machine. A request already at the station isn't
   withdrawn by the refusal: it ends as any unanswered or unsent one does (the code's expiry, the hourly sweep, 9, 13),
   and the owner can `make imprint-withdraw`. The next plan is a new imprint.

## What it doesn't close

- **A change during one run's upload.** The check runs once per run, before the run's first byte. A deny recorded
  while that run's parts are going is not seen by that run. The window is one run, as the build's is one build.
- **A send run by hand without `make`.** Item 3's stamp makes `send` refuse without a check in the last 300 s. Someone
  who writes the stamp by hand is outside this spec, as is anyone editing the package.
- **The station side.** Admission still can't read the owner's ledger. A deny recorded after the upload's last part
  applies to later imprints, and to this one only through `make imprint-withdraw`.

## The budget

At the reference store (100,000 memories, 700,000 subject rows), revision 8 measured the State at 6.8 s and 100,000
co-subject reads at 6.7 s, peaking at 106 MiB in a process holding only the State. The check is one State and at most
one read per packaged memory, so about 14 s and the same peak, under 14.1's 384 MiB. It runs once per send run, and a
send run already waits up to 9 minutes.

## How we know it is done

| What | Shown by | A wrong change caught |
| --- | --- | --- |
| A deny after the build stops the send | Build, then a co-subject's deny recorded by a writer: `make imprint-send`'s engram step refuses with the count, and the agent's `send` sends no request; the same after the request and the yes, with no manifest or part sent | One that reads the ledger only at build |
| A deny during the build's run stops the send | A marked deny appended during the build, after its State (the build passes, as now): the next send refuses | One that trusts the closing read alone |
| A retirement, a lane note and `bound` each stop it | One case each | One that checks denies only |
| An ordinary append passes | A marked `_put` that changes no answer: the send goes | One that refuses on any change |
| The check is fresh | `send` with no `checked.json`, with one 301 s old, and with one in the future: each refuses and sends nothing; with one just written: it goes | One that trusts a stale or missing check |
| The check reads as the build does | A torn page, an unstamped ledger's failed integrity check, and a ledger moved during the check: each refuses with the build's sentence | One that reads the ledger by direct SQL |
| Nothing is said of anyone | The refusal holds the count only, and the stamp only `at` and `seq` | One that names a co-subject |
| The budget | The cap test (`ENGRAM_PI_BUDGET=1`) gains a send check at the reference store with one deny, under 384 MiB | One that loads every row |

## Decisions

1. **Ask the build's questions again, not "did anything change".** Ordinary work writes the ledger.
2. **Check before each send run's first byte**, on the owner's machine, where the ledger is.
3. **A stamp no more than 300 s old ties the agent's send to the check**, so `send` alone can't skip it.
4. **Refuse and keep everything.** The owner plans again; the station's request ends as an unsent one does.

## Sections changed in the imprint spec

When approved, this is folded into the imprint spec as revision 9: a row in the revision history; I 5.2 (the build's
questions asked again at send); 13 (`make imprint-send`'s first bullet, and a refusal line); 16 (the table above); and
D44, "Each send run asks the ledger the build's questions again for the package's memories, and the agent's send
refuses without that check in the last 300 s."
