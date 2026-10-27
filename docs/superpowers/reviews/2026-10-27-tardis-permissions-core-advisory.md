# permissions-core: Tardis's advisory review

**Head reviewed:** e1e95ef. The read started on 6610215. Each finding was re-run or re-read at e1e95ef, and findings
that e1e95ef already fixes are listed apart.

**Status:** advisory. Under station law section 2, this isn't an approval. Serenity holds permissions-core's section 2
review.

**How it was done:** a Tardis session started four reviewers, one each for the decision core, the ledger and receipts,
the serving paths, and the CLI with migrate. Each looked mostly for paths that widen a permission or fail open. Each
reproduced what it could with a small script. The scripts are in [2026-10-27-tardis-repros/](2026-10-27-tardis-repros/)
(see "Running the repros" at the end).

## CI: Lighthouse and interoperability, run on Tardis

This is the job from `.github/workflows/ci.yml` that the Pi can't run (it needs Node 24 and pnpm 11.20.0). It ran with
Node 24.21.0 and pnpm 11.20.0 through corepack: `make setup-engram setup-lighthouse setup-atlas`, then
`make check-lighthouse` and `make check-integration`.

| Head | Result |
|---|---|
| 6610215 | passed |
| e1e95ef | passed: Lighthouse package tests 139/139 (protocol 21, calculus 14, hyper 4, engram adapter 25, aDNA 12, hyper-aDNA 5, recall-evaluation 49, conformance 9); the protocol and recall proofs; integration (2 matching schemas, 7 socket checks, 4 validated receipts); interop 3/3; Atlas integration (28 artifacts, 20 policy checks) |

## Still present at e1e95ef

### Must-fix

**T1. The horizon misses the expiry of a grant reached through another grant's envelope.**
`engram/permissions.py:1953` (`_horizon`); the same gap is in `_terms`, which feeds `until` and `EXPIRED`.
- `named` holds only collections named by records and by the envelopes of grants behind records.
- When a grant-backed membership counts, `_membership_counts` also matches that membership's own grant envelope. If
  that envelope names a second collection, and the object is in it only through a second grant-backed membership, the
  second grant's expiry is never a horizon term.
- Scenario: allow R names `[c1]`. m1 is in c1 under G1 (its envelope names `[c2]`, expiring 11-30), and in c2 under G2
  (expiring 11-05). `decide` at 11-02 allows with `horizon == until == 11-30`; at 11-05, with the same State, it refuses.
- The eligible set takes this horizon (`permissions.py:2230`, `eligible_set`). M2's new terms are log times and
  anchors, not grant expiries, so the daemon's cache keeps serving the recall from 11-05 to 11-30, against L8.
- The refusal code is `NO_ALLOW` where the spec says `EXPIRED`. `random_world` only puts grant-backed memberships in
  `_COLLECTIONS[0]`, so pt12 never builds this nesting.
- Fix: add the expiries of every grant-backed membership row of each needed object. The docstring already allows
  terms that come out earlier than the spec's reading.
- Repro: `r1_nested_horizon.py`.

**T2. `remember(genome=True)` after a delivery writes a second copy with no lineage, and imprint into the genome store
is never decided.** `engram/server.py:1915`, `:1929-1949`.
- `keep.record_copy` records only the local episode as a copy of the delivered item.
- The genome copy and the `genome_updated` signal (which `federation.process_inbox` turns into an episode in every
  instance) get no `copies` row.
- Scenario: m1 has co-subject Amy. The local copy keeps `{amy, andy, …}`; the genome copy's subjects are
  `('person:andy',)`. Genome sync then spreads it, so later uses never need Amy's layer (P25).
- Fix: refuse `genome=True` when the guard has a source, or record the genome copy too and decide imprint for the
  genome store.
- Repro: `test_r3_genome_remember.py`.

### Should-fix

**T3. `shorten` and `narrow` accept a replacement wider than the record when the old record's region is empty.**
`engram/permission_cli.py:578` (`_record_edit`) calls `check_narrower` at `engram/permissions.py:3236`.
- The check compares current regions, so an empty old region (no agent in the audience yet, or an empty collection)
  lets anything through.
- Steps: allow `collection:doctor/med` until 2027-01-31, then narrow it to `collections: "*"` (Done), then shorten it
  to 2027-12-31 (Done).
- `decide` stays bounded because `_record_boxes` intersects the replaces chain. But `share_cover`
  (`permissions.py:3340`, via `_counts_for_share`) reads the record raw: at 2027-06 it returns this record for m2,
  which was never in the collection.
- So the server's `share` under enforce places a copy without a proposal, and `place show` publishes the wider fields.
- An agent holding a narrow or shorten grant can do the same, because `_a_edit_allow`'s envelope test looks only at
  the old record.
- Repro: `t_narrow3.py`.

**T4. Genome sync under a closed gate runs the pre-ledger path and drops co-subjects for good.**
`engram/server.py:1314-1322` (`_sync_genome_kept`).
- The ledger is passed only for shadow and enforce, so closed falls through to `sync_genome` with no ledger.
- The copy loses `person:jenn`, and once the gate reopens the episode is skipped as already present.
- Under closed, skip the sync.
- Repro: `test_r3_genome_closed.py`.

**T5. The `shares` tool lists every placement to any agent's server, under every gate.**
`engram/server.py:2543`.
- A non-owner agent that `permissions(focus="rules")` refuses still gets every placement from `shares()`: memory and
  source ids, audience, reason (for example "Jenn's [condition] result for her care group") and content digest.
- That tells it refused memories exist (P23) and who the owner shares with, and the digest can be tested against
  guessed content.
- `unshare` (`:2351`) has no acting-for-owner check either, though removing a placement only narrows.
- Repro: `test_r3_shares.py`.

**T6. An object in a store with no `stores` row is decided on co-subject and copy layers instead of refused with
`NO_LAYER`.** `engram/permissions.py:1186` (`_own_subjects`), `:1213` (`subjects_of`).
- P 6.3 item 1 and P32 say such an object has no subject. The code drops only the store's default owner, then
  decides on co-subject rows and copy sources.
- `record_copy` doesn't check that the target store is registered.
- The oracle's `own_subjects` (`tests/permissions_oracle.py`) reads it the same way, so the property tests can't see
  it.
- Repro: `r2_unregistered_store.py`.

**T7. The retention fold counts shadow receipts and empty recalls as real uses, and can't be undone.**
`engram/permission_uses.py:335` (`fold`).
- A shadow refusal, where the legacy path actually delivered the item, becomes a permanent `refused`.
- An empty recall becomes `allowed` under subject `(none)`.
- Imported rows fold in with local ones, and the originals are deleted.
- Repro: `fold.py`.

**T8. Migrate isn't atomic against a hard kill.** `engram/permission_cli.py:1003` (`_migrate`), `:1064`.
- `Ledger.create` writes the final path, then runs many separate transactions. Clean-up runs only on a Python
  exception.
- SIGHUP after the 6th act leaves agents and one store, with no collections and no allows. The rerun is refused with
  "migrate runs once…" and no hint to delete the file, so the owner is stranded.
- Build beside the final name and `os.replace`, as `rebuild` does.
- Repro: `t_migrate_kill.py`.

**T9. The yes prints its words and code to stdout, not the tty.** `engram/permission_cli.py:82` (`confirm`).
- The answer is read from /dev/tty, but everything is printed to stdout.
- An agent launched from the person's shell can capture stdout, see the code, and relay it, while the person's
  terminal shows nothing.
- Open the tty read-write and print there.
- Repro: `t_stdout.py`.

**T10. `person retire <owner>` makes the ledger permanently unwritable.** `engram/permission_cli.py:1336`, and the
ledger's retire-by-themself rule.
- After it, every act is refused, including revoke, deny, `agent unplace` and `gate off`. Uses fail closed, but there
  is no way back.
- Refuse to retire `meta.owner`, or warn plainly.
- Repro: `t_retire.py`.

### Minor

- **T11.** `decide` ignores co-subject rows and placement removals logged after `at` even when they're already in the
  State (`permissions.py:1186` and `_requester_ok`). M2 closes the cache side of this; `decide` itself is unchanged.
  Repro: `r3_rows_after_t.py`.
- **T12.** `append_imported` (`permission_uses.py:283`) accepts an `inject_context` row with a content digest and the
  local ledger id. `deliveries()` and `owner_list` then treat it as local. There's no production caller yet. Repro:
  `imported.py`.
- **T13.** The owner comes from `getpass.getuser()` (`permission_cli.py:384`), which reads `LOGNAME`/`USER` first, so
  `LOGNAME=mallory … init` makes `person:mallory` the owner. Use `pwd.getpwuid(os.getuid()).pw_name` (R24). Repro:
  `t_login.py`.
- **T14** (by reading). `place_rules` (`permission_ledger.py:1066`) publishes records past `valid_until` as in force,
  filtering only on `revoked_seq`.
- **T15** (by reading). `_migrate_receivers` (`permission_cli.py:898`) registers every rule's publishers, deny rules
  included, as home agents. Delivery still applies the legacy check.
- **T16** (by reading). On `share`'s existing-row path (`sharing.py:131`), `record_id` is filled only when null. After
  the old record expires by time, a fresh narrower cover is dropped, and the follow-up sweep can remove the placement
  `share` just reported. This only narrows.
- **T17** (by reading). `PublisherDaemon(engram_home=None)` (`lighthouse_daemon.py:609`) means gate off.
  `lighthouse_pilot.py` builds it that way, even over houses whose ledger is raised. Derive the home from `db_path`, or
  fail closed.
- **T18** (by reading):
  - `fill` substitutes the literal strings `"@seq"`/`"@at"` in user text too.
  - `state(seq)` shows later proposals as pending and reads `meta` at the top seq.
  - `Ledger.create` writes the schema and the first log row in separate steps.

## Fixed by e1e95ef

- **Two writers on one ledger** (`perform` checked one snapshot and wrote in another transaction). At 6610215 a
  concurrent withdrawal was silently overwritten, and one proposal could be signed twice. At e1e95ef both repros
  (`race_withdraw.py`, `race_sign.py`) are refused with "already revoked/signed (by another write)", from M1, Minor 6
  and concern 3.
  - Left, by reading and not reproduced: authorization still runs against the snapshot read before `BEGIN IMMEDIATE`.
    So a steward removed between the read and the write may still get a person-backed allow, and the per-layer (256)
    and per-object subject (8) bounds may be passable by two writers at once. I1 moved the proposal and child-grant
    bounds inside the write; these two could follow.
- **Control characters in place names reaching the yes prompt.** Refused at registration by M5 (`t_name.py`: register
  exits 1).
- **The 20-candidate cap per recall** (P 12.2, rev 7). Built: `lighthouse_daemon.py:897` passes
  `min(k, MAX_CANDIDATES)`.

## Checked and found sound

- **The decision core:** deny wins in every layer and chain; hand-offs only narrow at decision time (`_chain_ok`,
  `_grant_ok`); an end equal to now ends; removed memberships never count for an allow; pending lanes behave as
  specified; malformed input is refused with the right code; and the write authorization table matches P 7.1 and 7.6.
- **The ledger:** the hash chain is unambiguous and `verify` catches reorder, drop and edit; rebuild is temp-file plus
  rename; `state()` reads in one transaction; every failure path of the effective gate returns closed; and migration
  029 adopts existing columns with NULL defaults the daemon refuses.
- **The serving paths:** under enforce, recall and read decide before ranking and before any content leaves; closed
  serves nothing (T4 and T5 are the exceptions); decision exceptions fail closed; the eligible-set cache key covers
  house, agent, place and purpose, with no sharing across agents; and receivers take the `permission` object only from
  the local daemon and grant nothing on it.
- **The CLI:** piped stdin, an environment variable or a flag can't stand in for the terminal yes (a pty-driving agent
  is spec 7.6's known limit); sign and decline apply exactly the proposal shown; and migrate doesn't widen what legacy
  shares allowed.

## Running the repros

From a checkout at the reviewed head, after `cd engram && uv sync --locked --extra dev`:

- `r*.py`, `fold.py`, `race_*.py`, `imported.py`: from `engram/`, run
  `PYTHONPATH=. .venv/bin/python <repro dir>/<script>`.
- `test_r3_*.py`: from `engram/`, run
  `PYTHONPATH=. .venv/bin/python -m pytest -q --rootdir=<repro dir> <repro dir>/test_r3_*.py`. They pass while the bug
  is present.
- `t_*.py` (CLI, in a pty through `drive.py`): run `W=<checkout> .venv/bin/python <repro dir>/t_<name>.py <throwaway
  dir>`. **The throwaway dir is deleted first.**
