# Imprints spec: fresh reviewer verdicts (station law section 3)

Spec: `engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md`. Reviewer: a fresh agent on the Pi that took
no part in writing the spec.

## First review (revision 1, uncommitted draft), 2026-10-25

VERDICT: APPROVE WITH CHANGES

Approval holds only once MF1–MF7 are applied as written below. Apply the S items in the same revision. Nothing in
this review edits the spec. File:line references are relative to `/home/andy/superyak/.worktrees/trail-arrows/`.

The spec is careful work. The table classification is complete. I checked every migration and every runtime
`CREATE TABLE` that writes to `graph.db`, and every citation listed below holds. The problems are where it departs from
the permissions spec it names as the source of truth, three places where a check or a constant doesn't do what the
text says, and two privacy gaps it doesn't state.

### Claims I checked and found true

- Every table that `engram/migrations/001`–`028` creates is in section 6.2. So are the hook tables
  (`hooks/nudge.py:140`, `:161`, `:170`, `:354`, `:428`; `hooks/wake.py:494`). The other runtime tables live in other
  files, and 6.3 names those files: `cold.db` (`storage.py:803`, `:838`), `signals.db` (`federation.py:33`),
  `notepad.db`, `clipboard.db`, `instinct_transitions.db`, `categories*.db` and `lighthouse-disclosures.db`. The only
  `meta` keys written anywhere are the identity keys and `last_indexed_commit` (`storage.py:1906-1915`,
  `indexer.py:458`, `:482`).
- calibrate: backup-API snapshot through a read-only connection (`engram/calibrate.py:54-68`), migrating only the
  working copy (`:262-277`), the `source_unchanged` check (`:300-305`), isolated analyses (`:236-241`), no cache
  write (`:142-143`), content excerpts (`:172`; `persistence.py:392`, `:415`).
- store_reader: `mode=ro` plus `query_only` (`store_reader.py:44-55`), applied, pending and unknown (`:88-101`),
  1 MiB hashing (`:58-63`).
- Identity: `effective_id` (`store_identity.py:113-116`), `stamp_fork` (`:143-160`), fork by backup with ids kept
  (`cli.py:38-49`). The imprint's `meta` rebuild drops `instance_id_basis_episode`, which can name the source's
  earliest episode. That is good.
- Peer: `canonical` and `parse` (`peer/superyak_peer/identity.py:20-48`), `RECORD_KEYS` and `sign_record` (`:76-87`,
  `:147-151`), `verify_record` never raises (`:189-200`), the 6 MiB body bound (`app.py:19`, `:44-51`),
  `ship_member` (`app.py:104-109`), person-only login and the 8/40 per 5 minutes limits (`auth.py:85-94`),
  `safe_line` (`ships.py:33`), `station_pending`/`station_decide`/`station_notices` (`ships.py:191-198`, `:279-302`,
  `:380-393`), backups copy only `peer.sqlite3` (`backups.py:167-176`, `:226-227`).
- DS9 spec lines 39-41, 57-58, 60-61, 80-86, 106-108 and 117-119 say what the spec cites. Station law lines 28-31 say
  only Andy admits.
- Server: the published house path (`engram/server.py:1936`), `source_instance` (`:1976`), query text in recall
  context (`:2102`, `:2181`, `:2376`), free-text outcome notes (`:2629-2631`), repo provenance (`:83`, `:1340`),
  genome and inbox sync (`:1443-1452`). Also `CITING_OPERATIONS` and `AUTO_OUTCOME` (`hooks/sleep.py:43-44`).
- `operation_log.outcome` holds only `success`, `failure` or `error:<ExceptionClass>` (`server.py:50-60`), so it is
  safe to keep unscrubbed.
- Header bytes 18 and 19 equal 1 do mean rollback-journal mode. 2 GiB / 4 MiB = 512 parts, and 512 hashes fit in
  256 KiB.
- **Check 7 holds across SQLite versions.** I built a fresh store from all 28 migrations under SQLite 3.40.1
  (system Python) and 3.53.1 (uv Python 3.14), both with sqlite-vec 0.1.7. The two `sqlite_master` tables were
  identical: 169 rows each, no diff.
- The Pi has 16 GB RAM and 875 GB free disk, and `~/.engram` is absent.

## Must-fix

**MF1. Sections 3, 4 (D8–D10), 5.3, 8 and 12 contradict the permissions spec and the vision on meaning, not encoding.**
The spec says the permissions spec wins on "encoding" (header lines 9-12). The permissions spec says the imprints spec
uses its sections 5, 6 and 11 "as they stand" (`docs/superpowers/specs/2026-10-25-permissions-by-place-design.md:15`).
They differ on meaning:
- **Instincts.** D8 and 5.2 ship instincts. The permissions spec says "Instincts, dream residue, task contexts and the
  knowledge graph are never objects; they never leave" (permissions spec lines 233-235 and 885). Its `layers` ⊆
  {`episode`, `semantic`}.
- **Audience.** D9 uses `person:<username>`. The vision's audience is "a place, a group or the commons"
  (`docs/city-rail-vision.md:76`). The permissions spec's audience grammar is `place:`, `group:`, `self` or `commons`
  (lines 225-230), and a person's place is `place:home/<handle>`. A `person:` audience has no meaning in either
  document.
- **Who uses.** The use check in 12 takes `who` to be a person (APPROVER). In the permissions spec a use is made by a
  requester *agent* acting in a place (6.1). The spec never says whether Andy's ships or Claude on the Pi count as
  `person:andy`.
- **Action closure.** D10 grants `imprint` and `route` only. In the permissions spec, `imprint` needs `recall`, `read`
  and `imprint` on every object included, and `route` needs `recall` on every memory it names (6.4, lines 405-411).
  Under that closure, this permission would be refused.
- **Purpose and time.** Here a permission has one purpose (`Pur′ = Pur`) and a float `expires`. There, `purposes` is
  a set and times are integer seconds, half-open (5.1-5.2).
- **The order.** Section 8 orders records with `Pur′ = Pur`. That order is not a lattice, because two purposes have no
  meet. The permissions spec orders denotations ⟦p⟧ ⊆ 𝒰 by inclusion, with meet = intersection (6.1-6.2).
- **Receipts the owner can list.** The permissions spec has the imprints spec build the owner's use-list entry ("copy
  held, deletion not confirmed", lines 674-676) and the `mem:<instance_id>/…` refs (line 132). The spec's receipts
  live only on the station, and an imprint's memories carry a new `instance_id`, so nothing ties them to the owner's
  refs.

*Fix:* Adopt permissions spec 5–6 as they stand.
- Step 1 objects are episodes and semantics only. Drop instincts from D8, 5.2 (Î), 6.2, check 12 and the tests, or
  raise the conflict to Andy as one question.
- The audience becomes `place:home/<owner of the audience>`, with requester agents acting for that person.
- Actions are closed under `need`.
- Purposes become a set, and `valid_until` becomes integer seconds.
- Define ⟦p⟧ for an imprint permission, and make section 12's check "u ∈ ⟦p⟧ ∩ ⟦ceiling⟧" literally.
- Say how an imprint's uses are receipted under the source refs `mem:<source instance_id>/…`, so
  `engram-permissions uses --person` lists them.

Keep the station-signed record as the step-2 form the permissions spec already plans (`permission-record` and
friends, its line 867). The cleanest fix is to name the new kind there.

**MF2. Section 11: Lin is not a closure, so copies can count as independent.**
Lin(X) looks back at most two steps. `cli.py fork` can fork an instance from another instance (`cli.py:21-24`), and by
default it forks from the genome.

| Case | Lin | Verdict | Should be |
|---|---|---|---|
| G, then Y = fork(G), then X = fork(Y) | Lin(X) = {X, Y}, Lin(G) = {G} | X and G independent | not independent, since X holds a full copy of G |
| Z = fork(G), cousin of X | {Z, G} ∩ {X, Y} = ∅ | independent | not independent |
| Y and Z, siblings | share G | not independent | not independent |
| Imprint I of a fork-of-fork | {I, X, Y} | independent of G | not independent |

D13, the anti-goal "False agreement", and the claim that the rule "stops accidental double counting" all fail for any
chain longer than two. The tests in 16 check only one-step cases, so they would pass.

*Fix:*
- Add `meta.ancestry`, a JSON list (bounded, e.g. 64), written by `stamp_fork` and `stamp_imprint` as the parent's
  ancestry plus the parent's id. The manifest carries `source.ancestry`.
- Define Lin(X) = {X.id} ∪ ancestry(X).
- A store with `forked_from_instance_id` but no `ancestry` predates the rule. Mark it `ancestry_complete: false`, and
  have `independent` return `unknown` for it, never `true`.
- Add a three-generation test and a cousins test.
- Say plainly that siblings forked from one genome are never independent. That is conservative, and the rail spec
  should know it.
- Genome-synced episodes carry `origin_instance_id` (`federation.py:182-186`). Name it as row-level provenance the
  rail spec must also read.

**MF3. Section 6.4 and the canary test in 16: the leak checks are blind exactly where the anti-goal points.**
I ran three experiments on SQLite 3.40.1, each with VACUUM and `freelist_count` 0.
- An FTS5 external-content index stores terms with prefix compression. A canary `zqxcanaryalphatwo`, indexed after
  `zqxcanaryalphaone`, was **not** present in the raw bytes.
- FTS5 also splits a UUID at its hyphens. A left-out id that reached only the FTS index was **not** found by the
  section 6.4 regex.
- Both were visible through `fts5vocab`.
- A UUID inside a long TEXT value is split across an overflow-page boundary in 10 of 1,286 positions I tried, and the
  raw scan misses it there.

So the "raw-byte id scan" and the anti-goal canary test ("none of these byte strings occurs anywhere in `imprint.db`'s
raw bytes") can pass on a real FTS leak. I also tested FTS5 `'integrity-check'`. It did not catch an index entry with
no content row.

*Fix:* Make the checks logical, and run them both at build and as admission checks on the Pi.
- Read every value of every row of every table through SQL, shadow tables included, so overflow is reassembled. Scan
  that for UUID tokens and canaries.
- For each FTS table, the `fts5vocab` 'instance' rows (term, rowid, column, offset) must equal those of an index
  rebuilt from the kept rows in a scratch database.
- For each vec0 table, the ids in `_rowids` must be ⊆ the kept rows, and every chunk slot not marked valid must be
  zero bytes.
- Keep the raw scan as an extra check, and say what it cannot see.
- Change the canary test to plant canaries that index as FTS terms, and assert through `fts5vocab` as well as raw
  bytes.

**MF4. Sections 10 and 12: receipts are to be signed by commands that never load the key.**
`station-approve` and `station-deny` open the store with `Store(..., signing=False)` (`peer/superyak_peer/__main__.py:326`;
`db.py:51`, `:86`). API.md documents that contract: "they load no key at startup, so a damaged identity stops the
lighthouse alone" (`peer/API.md:296-300`). The spec has these commands write signed `approved`, `denied`, `failed` and
`deleted` receipts. The same holds for `station-imprint-sync`, `-sweep`, `-delete` and `-use`. It also leaves open who
computes `previous` when the lighthouse and a CLI both append to one chain.

*Fix:* Decide, and say which, as a Rio Grande's call:
- **Either** these commands load the key, and the spec states the change to API.md's contract and what a damaged
  identity then blocks.
- **Or** they write unsigned receipt rows, and the running lighthouse signs pending receipts within a stated bound.
  Until then `imprint-status` shows them as "not yet signed".

Either way, compute `previous` and insert the receipt in one `BEGIN IMMEDIATE` transaction.

**MF5. Sections 2, 3 and 9: the manifest leaves before the yes, and it outlives withdrawal in backups.**
Section 2 defines the package as `imprint.db` plus `manifest.json`. Goal 3 says "Nothing leaves before the owner says
yes", and the anti-goal "Early bytes" counts any byte of the package. Yet `POST /api/imprints` sends `{manifest,
terms}` before the yes. The manifest carries the store's id, lanes, dates and counts.

The request row lives in `peer.sqlite3` (section 15, "peer database migration"). So do the permission and the
receipts. Nightly backups copy that file, keep 14 daily and 8 weekly copies (`backups.py:30`, `:109-119`), and can
copy it off the Pi (`--copy-to`, `peer/systemd/superyak-backup.service:10`). D15 is true for `imprint.db` only.

*Fix:*
- Restate Goal 3 and the anti-goal precisely: no byte of `imprint.db` before the yes. The request carries only what
  the confirm view shows, and it says so on the owner's terminal before it is sent.
- Erase the manifest and terms from `declined` and `expired` rows, keeping a content-free tombstone.
- State what stays in `peer.sqlite3` after withdrawal (the permission and the receipts: scope, counts, dates). Say how
  long backups and off-Pi copies keep it, and show that to the owner in the confirm view and in `imprint-status`.

**MF6. Sections 3 and 20: memories about other people move on one person's yes.**
Vision principle 1: "Anything about a person moves only with that person's yes." An owner's episodes routinely
mention other people: family, colleagues, and in this project possibly patients or participants. The DS9 spec keeps
"No patient or participant data" out of ship rooms (DS9 spec, line 78). The spec's non-goal "Stores about several
people" is met only by the confirm view asserting "This store is about you". That doesn't address third parties
inside one person's store. The permissions spec has co-subjects (its 7.4) and a later name detector. This spec says
nothing.

*Fix:*
- State the limit under "What P does not cover".
- Add a step-1 rule, a Rio Grande's call. One option: `imprint-plan` prints a reminder, and the confirm view asks the
  owner to confirm the chosen memories hold nothing about another person that the person hasn't agreed to, and no
  patient or participant data.
- Add one item to "Open for Andy": whether step 1 may imprint memories that mention other people at all, and whether
  the first store must be work lane only.

**MF7. Sections 10 and 14: the calibration bound is wrong by a factor of more than 3, so admission is OOM-killed on the Pi.**
The spec counts "two dense n × n float64 matrices … at 12,000 episodes … about 2.3 GB". `build_filtration` actually
holds `D`, `np.diag(...)` and `off` at once (`engram/persistence.py:63-64`). Then `_mst_edges` adds `floored` and a
dense-to-CSR copy (`:41-46`).

I ran `persistence.build_filtration` itself on random 768-dimension vectors:

| n | Peak RSS | Ratio to n² × 8 bytes |
|---|---|---|
| 1,500 | 200 MiB | 7.16 |
| 3,000 | 609 MiB | 7.54 |
| 5,000 | 1,539 MiB | 7.50 |

At 12,000 that is about 8.6 GB. With `MemoryMax=4G` and `MemorySwapMax=0`, the scope is killed, and 10 says a failed
calibration fails admission. `flag_redundant_cores` also builds a filtration over every core episode, with no lane
bound (`persistence.py:399-409`; called at `calibrate.py:211`).

*Fix:*
- Set `max_lane_episodes` from the measurement: about 7,500 under 4G, leaving 512 MiB for the rest. Or derive
  `n_max = ⌊√((MemoryMax − 512 MiB) / (7.5 × 8 B))⌋` and record the formula.
- Apply the same bound to the core set.
- Correct the arithmetic in 10 and 14.

## Should-fix

**S1. Sections 5.4 and 6.1: log rows have no time bound, so the build refuses whenever engram was used.**
[t₀, t₁) bounds memories only. `memory_log` recall rows, `operation_log` rows and `resonances` (inserted during
recall, `storage.py:2003`) join whenever all their targets are in M. Any recall between plan and build changes the
digest, and the build stops with "Your store changed". That is likely whenever Claude Code runs the commands with
engram active. *Fix:* Bound those rows by `timestamp` or `created_at` < t₁ (and ≥ t₀), and say so in 5.2.

**S2. Section 6.2, `memory_log`: the whole-row rule throws away most recalls for a work-lane imprint.**
A plain recall mixes layers and lanes. Instincts are vector candidates when `layer` is None (`server.py:1643-1645`),
and lanes are filtered only when `lane` is given (`server.py:2332`). The spec's own example keeps 612 recall rows and
leaves 2,240. The trail spec drops instinct targets before every rule (trail spec section 4, "Cited touches").
*Fix:* Remove instinct ids not in I from `target_ids` (scrubbed column, D6). Keep whole-row dropping for episode and
semantic targets. This changes no trail result and reveals nothing.

**S3. Sections 5.2 and 6.4: pruning makes down-closure check only some sources.**
Pruning deletes the episode, and `semantic_sources` cascades (`storage.py:760`; `002_v3_layers.sql:27`). A semantic
then ships on its own selectors, even if its pruned sources were before t₀ or would have been excluded. The spec
states this for "all pruned". *Fix:*
- Say it also holds for partly pruned sources, in D5 and in P's limits.
- Have the dry run count semantics with no recorded sources.
- Ship those only with an explicit `--include-unsourced-semantics`.

**S4. Section 5.2, `shared(m, A)`: a changed source memory is not caught.**
`audiences_for` checks the published copy against the share digests (`sharing.py:236-254`), not the source memory.
`_verify_reused_copy` (`sharing.py:77-96`) shows the stronger check. *Fix:* Also require
`content_digest(m.content)` to equal the share row's `content_digest`.

**S5. Section 6.4, item 1: `--allow-cross-references` is a decision the owner's yes never shows.**
The agent running the commands can pass it, and by D21 the browser shows nothing about it. *Fix:* In step 1, either
allow only `--exclude`, or have `--allow-cross-references` read a code from `/dev/tty`, as the permissions spec's
step-1 yes does (its P20).

**S6. Section 10, checks 9, 10 and 13: the verification connection can't read vec0.**
`store_reader.connect` never loads extensions (`store_reader.py:7-9`, `:44-55`). Counting vec0 rows, checking their
ids and recomputing `sha256(embedding bytes)` all need sqlite-vec, or a defined decoding of `_rowids` and
`_vector_chunks00`. *Fix:* Say which. For example, load `sqlite_vec` on a `mode=ro&immutable=1` connection.

**S7. Section 6.2, last row: `sqlite_sequence` is created and filled by vec0.**
Every vec0 table's `_chunks` and `_rowids` use AUTOINCREMENT. A freshly migrated store has `sqlite_sequence`
(measured), and inserts fill it. "Not copied" is right, but `contents`, check 9 ("dropped tables are empty") and
check 13 must treat it as rebuilt. *Fix:* Say so, and exclude it from `contents`.

**S8. Section 11, the `Storage` guard: say where it runs.**
`Storage.__init__` sets `journal_mode=WAL` (`storage.py:108`, `:122`) and runs migrations (`:115`) before anything
else. *Fix:* The guard reads `meta` read-only right after connecting, before `_restore_pragmas()`.

**S9. Sections 10 and 12: uses and reports can't be written into a 0555 tree.**
Registration sets directories to 0555, but `station-imprint-use` writes `uses/<use id>.allow.json`, and the place for
use reports is never named. *Fix:*
- Name one writable sibling, e.g. `~/.engram/imprints/<id>.state/`, for uses and reports.
- Delete it on withdrawal, and list its files in the `deleted` receipt.

**S10. Sections 10 and 12: withdrawal during admission is undefined.**
Withdrawal runs in the lighthouse. Admission runs as a 30-minute CLI job. *Fix:* Deletion wins.
- Admission checks the status before each write and never creates the imprint directory.
- `station-imprint-sync` never moves `deleting` or `deleted` to `admitted`.
- The sweep removes leftovers, as it already does for directories with no live row.

**S11. Sections 10 and 13: `make station-approve` can block for 30 minutes.**
Claude runs it on the Pi when Andy asks, and the Bash tool's limit is 10 minutes. *Fix:* Start admission as a detached
`systemd-run --user` unit with the same limits. `station-approve` returns at once ("admitting; see `make
station-imprints`").

**S12. Section 11, guards: `lighthouse_sheaf.py` can already count an imprint as an agreeing lighthouse.**
It opens any `--store` path read-only (`engram/lighthouse_sheaf.py:269`, `:408`) and never checks lineage. *Fix:* Add
it to the guard table. It refuses, or loudly flags, any pair of stores that `independent` (after MF2) doesn't return
true for.

**S13. Sections 3 and 12: state the station-side limits plainly.**
Anyone with Andy's shell can read `imprint.db` 0444. That includes Claude sessions on the Pi. They can also read the
station's `identity.json`, so they could sign a permission no owner gave. "Nothing else reads an imprint" is policy,
not enforcement. *Fix:*
- Add a known-limits line, as the permissions spec does for P20.
- Add an agent rule to the CLAUDE.md approving section: never read `~/.engram/imprints/` except through
  `imprint.py use`.

**S14. Section 14: manifest fields need formats, because `imprint_id` becomes a path on the Pi.**
`POST /api/imprints` checks only the key set. *Fix:* Require these formats, and refuse an `imprint_id` the station
already holds:
- `imprint_id`: lowercase UUID4;
- hashes: 64 lowercase hex;
- times: ISO-8601 `Z`;
- counts and bytes: non-negative integers.

**S15. Section 5.4: define the digest row keys exactly.**
"A relation row's key is its key columns" is ambiguous. For example, `resonances` has both an `id` and a
`UNIQUE(memory_a, memory_b)`. Sorting mixed JSON arrays is not defined for a stranger. *Fix:*
- A table of key columns per table.
- Sort by the canonical JSON bytes of each key.
- Bind `memory_log` and `operation_log` `target_ids` in their keys, since the trails read them.

**S16. Section 6.1: say rowids are never copied.**
Copying source rowids would show gaps, and so counts of left-out rows between kept ones. That holds for the base
tables and for the FTS `content_rowid`. Explicit column lists imply it, but the spec should say it, and a test should
check that rowids are 1..n.

## Nits

- **N1.** Section 5.4 example: 43,188,224 bytes ÷ 4 MiB is 11 parts, not 10. "41.2 MB" is MiB.
- **N2.** Section 8 example: `created: 1761429851.0` is 2025-10-25T22:04Z, a year early. It also disagrees with the
  manifest's `built_at` 18:04Z. The receipt's `at` has the same problem.
- **N3.** Section 5.4 example: "Links 240" implies 8 `semantic_peers`, but section 7's `contents` lists none.
  "Citing actions 31" is unlikely for a work-lane imprint: `mark_core` refuses work-lane episodes
  (`server.py:3055-3056`), and the other two citing operations name instincts and residue.
- **N4.** Section 6.4, item 1: a cross-reference should be any primary key of any row of the source's `graph.db` or
  `cold.db` that doesn't ship. That would also cover `assessments` and `drift_reports`. Compare ignoring case in the
  raw scan too. A 2 GiB scan needs chunks that overlap by 35 bytes.
- **N5.** Section 5.2: the server uses `_instance_name or "default"` even when it fell back to `.engram/graph.db`
  (`server.py:1306-1311`, `:1976`). In that case `shared()` misses shares. That is safe, but worth a line.
- **N6.** Section 5.1: the server resolves its store from `PROJECT_ROOT`'s config (`server.py:1302-1304`), not from
  `resolve_db_path(engram_home)`. The default can differ by project. Say "use `--store` when unsure".
- **N7.** Goal 6 says "every event", but `declined` and `expired` have no receipt (there's no permission yet). Say so.
- **N8.** D24: also delete the source machine's copy on `declined`, `denied`, `failed` and `deleted`.
- **N9.** D4: an unknown table stops the build, and the owner has no way forward. Dropping it and naming it in the dry
  run is equally safe.
- **N10.** Section 4: D25 sits between D20 and D21.
- **N11.** Section 5.2: say that a `created_at` with no zone is read as UTC.
- **N12.** Section 5.4: `store_reader read` reads only episodes (`store_reader.py:188-210`). `imprint-read` needs its
  own reader for semantics, and for instincts if they stay.
- **N13.** Section 12, restore reconciliation: removing a directory whose row predates admission should write a
  `deleted` receipt (reason `restore`).
- **N14.** Section 13: `APPROVER` is the operator's claim, not authentication. Say it is the Pi operator's word.

## Response (revision 2), 2026-10-25

Reviser: a fresh agent that took no part in writing revision 1 or this review. Revision 2 of the spec answers every
item. I declined none of the review's items. Where I applied one in a different form than the review proposed, the
line says how and why. Every changed claim about code was checked against the code. Section numbers below are
revision 2's.

**What I re-measured, with numpy, scipy and sqlite-vec 0.1.7 on the Pi (SQLite 3.40.1 and 3.53.1)**

- `build_filtration` peak memory: 7.48 × n² × 8 bytes at n = 2,000 and 4,000, which agrees with your 7.16–7.54.
- FTS5: a term indexed only in the index, after a term sharing 14 letters with it, was absent from the raw bytes as a
  whole. A UUID that reached only the index was split at its hyphens, and the regex found nothing. `fts5vocab`
  `instance` showed both. `'integrity-check'` passed an index entry with no content row.
- vec0: a fresh table has `_chunks`, `_rowids` (both `AUTOINCREMENT`, so `sqlite_sequence` exists and fills),
  `_vector_chunks00` and `_info` (`CREATE_VERSION v0.1.7`). The validity bitmap is least-significant-bit first, with
  one little-endian int64 rowid per slot. 0.1.7 zeroed a deleted slot. The spec doesn't rely on that and checks it.
- I did not re-run the overflow-page split. Section 6.4 cites your 10 of 1,286.

### Must-fix

- **MF1. Applied.** The spec adopts permissions spec 5–6 as they stand (header; section 8).
  - (a) Instincts are dropped everywhere: D8, 5.2 (no Î), 6.2, checks 11 and 12, and the tests. I followed the
    permissions spec ("never leave") and asked Andy nothing.
  - (b) The audience is `place:home/<operator>`, the station super admin's home (D9; 5.3; section 14).
  - (c) The only requester is `agent:station-imprints`, acting for the operator in the operator's home. Andy's ships
    and Claude sessions are not requesters. Claude on the Pi is a caller of that agent (section 8).
  - (d) Actions are closed under `need`. r_M lists `recall`, `read` and `imprint`, and r_T lists `route` (D10; 5.3).
  - (e) Purposes are a set. Times are integer seconds, half-open.
  - (f) ⟦p⟧ = match(r_M) ∪ match(r_T), the ceiling is ⟦c⟧, and `allowed(k, t)` ⇔ Need(k, t) ⊆ ⟦p⟧ ∩ ⟦c⟧. The order is
    inclusion, and the meet is intersection. Shortening and withdrawal are shown to narrow. A short lemma reduces the
    check to at most six pair tests, which also answers the permissions review's S6 bound for imprints.
  - (g) Objects are named by the source's refs `mem:S/…`. Receipts name `{imprint, count}`. `make imprint-status`
    imports them into the owner's `permission-uses.db`, with `objects.json` so `--object` works. `uses --person`
    shows "copy held, deletion not confirmed" (section 12).
  - The record kind stays `imprint-permission`, wrapping two records in the permissions spec's 5.1 form, less its
    ledger-only fields. Reconciling it with that spec's step-2 `permission-record` list is left to Rio Grande
    (section 8).
- **MF2. Applied.** Section 11 adds `meta.ancestry` (at most 64) and `ancestry_complete`, written by `stamp_fork` and
  `stamp_imprint`, and carried in the manifest's `source`. Lin = {id} ∪ ancestry. `independent` returns true, false or
  unknown, and only true counts. Your four cases are a table. Siblings are never independent, stated for the rail
  spec. `origin_instance_id` is named as row-level provenance (`federation.py:182-186`). Tests cover three
  generations, cousins, siblings, an imprint of a fork of a fork, an old fork (unknown), and a chain over 64.
- **MF3. Applied.** Section 6.4 defines L1 (every value of every ordinary table through SQL, shadow tables included),
  L2 (each FTS table's `fts5vocab` `instance` rows equal a scratch index rebuilt from the kept rows, plus `_docsize`
  ids), L3 (vec0 `_rowids` ids are exactly the shipped vector rows, and the chunk layout is written out so invalid slots
  must be zero), and L4 (the raw scan as an extra, with its blind spots stated). The build runs all four. The Pi runs L2
  and L3 as checks 16 and 17. L1 and L4 need the keys of what stayed home, which the Pi never sees. The canary test
  plants prefix-sharing FTS terms, hyphen-split UUIDs and overflow-crossing UUIDs. It asserts through `fts5vocab`, L1,
  L3 and raw bytes, and adds tests that L2 and L3 catch planted faults.
- **MF4. Applied, second option** (D19, section 12). The key-less commands write unsigned receipts. The running
  lighthouse signs them at start, every 60 seconds (a lifespan task beside `peer_routes.py:10-19`), and before any
  imprint read. Until then the receipt shows "not yet signed". This keeps API.md's contract (`peer/API.md:300-302`),
  and there is a precedent in `signatures.py:159-166`. Every append computes `previous` inside `Store.transaction()`,
  which is `BEGIN IMMEDIATE` (`db.py:113`). The chain's first `previous` is the permission's hash.
- **MF5. Applied** (D26, D15, D32; sections 3, 7, 9).
  - Goal 3 and the anti-goal now say no byte of `imprint.db`, and nothing the view doesn't show, before the yes.
  - The request (7.1) holds only what the confirm view shows, and the terminal prints it first.
  - The manifest is sent after the yes, and the permission binds `request_sha256` and `plan_digest`.
  - The request's contents live in staging `request.json`, never in `peer.sqlite3`. They are deleted at decline and
    by the sweep within an hour of expiry. The row holds ids, status and times only.
  - Section 9 tabulates what lives where and for how long: the permission and receipts are kept 400 days after
    deletion. Backups keep about 8 weeks more, by `backups.py:30` and `:109-119`, and longer if the Pi was off; an
    off-Pi copy is pruned the same way (`backups.py:294-319`). The confirm view and `imprint-status` say so.
- **MF6. Applied** (D27; 5.2; 6.4 item 5; section 8; section 20).
  - The limit is stated under what P doesn't cover.
  - A memory with a recorded co-subject in the owner's permissions ledger is not admissible.
  - `imprint-plan` prints a reminder.
  - The confirm view requires the owner to tick "nothing about another person who hasn't agreed, no patient or
    participant data". The record holds the attestation.
  - Open for Andy asks whether step 1 may imprint memories that mention others at all, and whether the first store
    must be work lane only.
- **MF7. Applied** (D31; section 10; section 14). `max_lane_episodes` = 7,500, with the formula
  n_max = ⌊√((MemoryMax − 512 MiB)/(7.5 × 8 B))⌋, which is 7,914 at 4 GiB, recorded. The bound covers each lane, the
  core set (`persistence.py:399-409`), and also each hub's sources in `classify_hubs` (`persistence.py:342-384`),
  which builds filtrations too. A set over the bound is skipped and recorded, never sampled. Section 14's arithmetic is
  corrected.

### Should-fix

- **S1. Applied, extended.** Log rows and resonances are bounded by [t₀, t₁) (5.2). Two additions:
  - Log rows ship only from sessions closed at t₁, read from rows before t₁ (the trail spec's closed session). This
    keeps late outcomes of the running session (`storage.py:1704-1708`, `hooks/sleep.py:137`) from breaking the
    digest.
  - A resonance's growing counters (`storage.py:2003-2009`) are copied, but not digested.
- **S2. Applied.** Instinct ids are stripped from recall `target_ids`, and episode and semantic targets keep the
  whole-row rule (6.2). The example now keeps 1,940 recall rows and leaves 912.
- **S3. Applied.** "Recorded sources only" in 5.2 and D5, and item 4 under P's limits. The dry run counts sourceless
  semantics. `--include-unsourced-semantics` ships them.
- **S4. Applied.** `shared(m, A)` also requires `content_digest(m.content)` = the share row's digest.
- **S5. Applied, first option.** Step 1 has only `--exclude`, and `--allow-cross-references` is gone (D23).
- **S6. Applied, both.** `store_reader.connect(…, vec=True)` loads sqlite-vec on the immutable read-only connection
  for checks 9, 10 and 13. L3 (check 17) decodes the shadow tables directly, with the layout written out. Check 7 also
  compares vec0 `_info`.
- **S7. Applied.** `sqlite_sequence` is "rebuilt, never copied", left out of `contents` and check 9.
- **S8. Applied.** The `Storage` guard reads `meta` before `_restore_pragmas()` and before migrations (section 11).
  There is a test that no `-wal` appears and the bytes are unchanged.
- **S9. Applied.** `~/.engram/imprints/<id>.state/` (0700) holds calibration, allow files and use reports. Withdrawal
  removes it, and the `deleted` receipt lists its files.
- **S10. Applied** (section 10, "Deletion wins"). Admission never creates either directory and checks for a tombstone
  before each write. `calibrate` gains `create_parents=False`, so `out.mkdir(parents=True)` (`calibrate.py:251`)
  can't recreate a removed state directory. The sync moves only `approved` rows. The sweep removes leftovers.
- **S11. Applied.** Admission and uses run as detached `systemd-run --user` units with the same limits.
  `station-approve` returns at once, and `make station-imprints` reports.
- **S12. Applied, in the flag form.** `lighthouse_sheaf.py` refuses an imprint store. For a pair of other stores it
  reports `independent`, and marks any pair that isn't true. It is observational, and a person's instances are siblings
  (fork defaults to the genome, `cli.py:15`), so refusing pairs would break its current use.
- **S13. Applied.** "Known limits on the station" in section 12. The CLAUDE.md approving-section rule is in section
  15 and a deploy gate.
- **S14. Applied.** Formats for every request and manifest field. A duplicate `imprint_id` is refused, against
  requests, imprint directories and tombstones (section 14).
- **S15. Applied.** A key table per table, with keys sorted by their canonical JSON bytes and "as kept" values, so
  the Pi can recompute it. The log rows bind `target_ids`. There is a test with a second implementation written from
  5.4 alone.
- **S16. Applied** (D33, 6.1 step 5, check 15). Rowids are never copied, and memories go in `(created_at, id)`
  order. Rowids and FTS `_docsize` ids are tested to run 1..n.

### Nits

- **N1. Applied.** 41.2 MiB in 11 parts.
- **N2. Applied.** All times are integers in 2026. The yes is 1792951950 (2026-10-25T18:12:30Z), after `built_at`
  18:04:11Z. Receipts are examples in 2026 too.
- **N3. Applied.** Links are 201 + 31 + 8, and `semantic_peers` is in `contents`. Citing actions are 0, and 6.2 says
  why (`server.py:3055-3056`).
- **N4. Applied, refined.** A cross-reference is any left-out single-column TEXT primary key (or vec0 id) of the
  source's `graph.db` or `cold.db`, compared ignoring case, minus the session and recall ids that shipped rows keep. I
  needed the subtraction: `session_registry`'s primary key is `session_id` (`023_session_registry.sql`), it is
  dropped, and kept rows carry session ids, so the literal rule would flag every session. The raw scan's chunks overlap
  by 35 bytes.
- **N5. Applied** (5.2). After the permissions spec's migration 029, the match is on `source_instance_id`.
- **N6. Applied** (5.1). Resolution mirrors the server's `PROJECT_ROOT`, and the dry run says "Use `--store` when
  unsure".
- **N7. Applied** (goal 6; lifecycle table).
- **N8. Applied** (D24).
- **N9. Applied** (D4). A source-only table is dropped and named. A package table without a rule is a code bug and
  stops the build.
- **N10. Applied.** The D rows are in order.
- **N11. Applied** (5.2, "Times").
- **N12. Applied** (5.4). `imprint.py` has its own semantics reader.
- **N13. Applied.** Reason `restore`.
- **N14. Applied** (vocabulary; section 13).

### Changed beyond this review

- **Trail spec interface items** (its section 11, revision 4 then 5, written in parallel).
  - **I1 applied as D35.** `route_shown` rows ship with targets cut to M, the row kept even when the cut list is empty,
    and context cut to four keys. Check 11 allows them.
  - **I2 applied in part.** The allow file holds the imprint's `instance_id`, actions, purpose and effective end. A
    shortening replaces live allow files atomically. `use-finished` carries a report hash only when a report exists.
    I kept the file in the state directory (S9). The trail spec reads `<imprint dir>/uses/…` and `withdrawn.json`, and
    must change to `<id>.state/uses/…` and the tombstone. Rio Grande reconciles that.
  - **I3 is noted.** Admission needs no embedder. The trail evaluation's embedder is the trail spec's to settle.
- **The permissions spec's review** (written in parallel). Section 8 now says that imprint objects keep their
  source's subjects (its MF6). It also says the denotation covers only the fixed set objects(I), so a memory written
  later is never covered (its MF14). `Need(trail-evaluation)` already includes `read` (its MF8).

### Not taken

- **Trail spec I4** (keep partial recall rows with a `cut` flag). It changes D6, D7 and D21's promise that nothing
  tells about what stayed home. It came after this review, and it needs its own review and Rio Grande's call. Revision
  2 keeps whole-row dropping for episode and semantic targets.
