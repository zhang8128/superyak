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

## Re-check (revision 2 with the interface pass), 2026-10-25

Reviewer: a second fresh agent on the Pi, re-checking in Andy's place under station law section 3. I took no part in
writing revision 1 or 2, the first review, its response, or the interface pass. I read the vision, the spec as it
stands in the working tree (revision 2 at `3c022bf`, plus the uncommitted interface pass), the first review and its
response, the interface table, and the sections of the permissions spec (P) and the trail spec (T) that the table
names. I checked every code claim below by reading the code. Nothing here edits a spec. File:line references are
relative to `/home/andy/superyak/.worktrees/trail-arrows/`. "Spec line" means a line of
`engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md` as it stands today.

VERDICT: APPROVE WITH CHANGES

One must-fix remains (RMF1). Approval holds once it is applied as written, or in another form that keeps the same
property. Apply RS1–RS5 in the same revision. The nits are optional.

### 1. The first review's must-fix items

- **MF1. Resolved.** Instincts are gone from D8, 5.2 (Λ ⊆ {`episode`, `semantic`}), 6.2, checks 11–12 and the tests.
  The audience is `place:home/<operator>` (D9, 5.3). The one requester is `agent:station-imprints` (section 8).
  Actions are closed under P's `need`, quoted from P's current 6.4 (5.3). Purposes are a set, and times are integer
  seconds, half-open (8). ⟦p⟧, the ceiling ⟦c⟧ and `allowed(k, t)` are defined, with P's inclusion order and
  intersection meet (8). Uses reach the owner's `permission-uses.db` in P 9.1's form, under the source refs (12). P's
  step 2 now names both imprint kinds (P section 14, P lines 1352-1355). Two new defects come from how it was applied:
  RS1 (how r_M reads lanes) and RS2 (P's records don't name the copy).
- **MF2. Resolved.** `meta.ancestry` and `ancestry_complete`, Lin = {id} ∪ ancestry, a three-valued `independent`,
  the review's cases as a table, siblings never independent, `origin_instance_id` named (`engram/federation.py:182-186`),
  and the tests in 16. One gap remains, for stores older than identity: RS4.
- **MF3. Resolved.** L1–L4 (6.4), checks 16 and 17 on the Pi, a canary test that plants prefix-sharing FTS terms,
  hyphen-split UUIDs and overflow-crossing UUIDs, and tests that L2 and L3 catch planted faults.
- **MF4. Resolved, second option** (D19, 12). `station-approve` and `-deny` do open `Store(..., signing=False)`
  (`peer/superyak_peer/__main__.py:322-327`). `signing=False` skips the key (`peer/superyak_peer/db.py:86-89`). API.md
  states the contract (`peer/API.md:300-302`). The precedent exists (`peer/superyak_peer/signatures.py:159-166`, run at
  start by `db.py:89`). `Store.transaction()` is `BEGIN IMMEDIATE` (`db.py:113`). The lifespan has a worker to sit
  beside (`peer/superyak_peer/peer_routes.py:9-25`).
- **MF5. Resolved** (D15, D26, D32; sections 3, 7.1, 9). The request's contents stay in staging, the manifest is sent
  after the yes, and the retention table is there. Backups copy only `peer.sqlite3`
  (`peer/superyak_peer/backups.py:167-176`), keep 14 days and 8 weeks (`:30`, `:109-119`), and prune an off-Pi copy
  the same way (`:294-319`). Two things are left over: RS5 (rows kept with no end, which the owner isn't told about)
  and RN3 (request fields the view doesn't show).
- **MF6. Resolved** (D27; 5.2 `cosubjects`; 6.4 item 5; 8; 20). A memory with a recorded co-subject stays home, the
  owner ticks the check, and the question stays open for Andy. This is the strictest default of the three specs. I
  don't decide the question.
- **MF7. Resolved** (D31; 10; 14). I redid the arithmetic: ⌊√((4 GiB − 512 MiB) / 60 B)⌋ = 7,914, and
  7.5 × 7,500² × 8 B = 3.14 GiB, which leaves 512 MiB under 4 GiB. `build_filtration` holds `D`, the diagonal and
  `off` (`engram/persistence.py:63-64`), and `_mst_edges` adds `floored` and a CSR copy (`:41-46`). The core set
  (`:399-409`, called at `engram/calibrate.py:211`) and each hub's sources (`persistence.py:342-384`) are bounded too.

### 2. Claims I checked and found true

- calibrate: `out.mkdir(parents=True, exist_ok=False)` is at `engram/calibrate.py:251`. The analyses are at
  `:286-296`. `source_unchanged` and side files are at `:302-305`. The snapshot is immutable without a WAL (`:61`).
  `Storage(working)` runs only when migrations are pending (`:266-268`), so an imprint never reaches it.
- Calibration reads no log rows. `memory_log` appears in none of `calibrate.py`, `persistence.py` or `paths.py`.
  sheaf reads it only in `_rate_limited` (`engram/sheaf.py:285-299`), which only `:323` calls.
- `Storage.__init__` loads sqlite-vec (`engram/storage.py:102-104`), then sets WAL (`:108`, `:122`), then migrates
  (`:115`), then checks vec0 (`:118`). `open_read_only` loads sqlite-vec at `:153-156`. `_now_iso` writes `+00:00`
  (`:55-56`).
- `store_reader.connect` (`engram/store_reader.py:44-55`) loads no extension (`:7-9`). `read_episodes` reads only
  episodes (`:188-210`).
- `stamp_fork` is at `engram/store_identity.py:143-160`. `_write` skips null values (`:118-123`), so a fork of a store
  with no identity has no `forked_from_instance_id` row, as section 11 assumes. `KEYS` is at `:43-49`.
- `resolve_db_path(engram_home, project_root)` routes as the server does (`engram/config.py:373-409`;
  `engram/server.py:1302-1311`).
- `shared(m, A)`'s digest test is `_verify_reused_copy`'s (`engram/sharing.py:77-96`). `audiences_for` checks only the
  published copy (`:236-254`).
- Pruning copies episodes to cold (`engram/storage.py:734-747`) and deletes them (`:760`), and `semantic_sources`
  cascades (`engram/migrations/002_v3_layers.sql:27`).
- Late outcomes come from `update_log_outcome` (`engram/storage.py:1704-1708`) and the Stop hook
  (`engram/hooks/sleep.py:137`). `AUTO_OUTCOME` and `CITING_OPERATIONS` are at `:43-44`. A resonance that forms again
  only raises `co_occurrences` and `last_seen` (`engram/storage.py:2002-2010`).
- A recall row's `id` is its own uuid, separate from `recall_id` (`engram/server.py:2370-2386`). So `recall_id` is no
  primary key, and X*'s subtraction of recall ids (spec line 584) is harmless but subtracts nothing.
- Peer: `canonical` and `parse` (`peer/superyak_peer/identity.py:20-48`), `RECORD_KEYS` (`:76-83`), the peer id as
  SHA-256 of the key (`:94`), `sign_record` (`:147-151`), and `verify_record` never raises (`:189-200`). The username
  grammar (`peer/superyak_peer/auth.py:34-35`). Person-only login and 8 / 40 attempts per 300 s (`auth.py:85`, `:90`,
  `:94`). `_operator` checks only that the name is a person (`peer/superyak_peer/ships.py:201-206`). `APPROVER ?= andy`
  (`Makefile:32`).
- The embedder service answers with vectors and keeps no text (`engram/embedder_service.py:105-122`). It logs only at
  `:84` and `:134`, its socket is the user's own (`:99`), and a failed request is answered without logging its text
  (`:73-78`).
- The installed lighthouse unit (`~/.config/systemd/user/superyak-lighthouse.service`) has no filesystem sandbox, so it
  can remove `~/.engram/imprints/…` as withdrawal needs. Its `MemoryMax=1G` is enough for streamed joins and hashes.
- Every example time and size holds. 1792951950 is 2026-10-25T18:12:30Z. Ninety days later is 1800727950
  (2027-01-23T18:12:30Z). 1792956600 is 19:30:00Z. 43,188,224 bytes is 41.19 MiB in 11 parts. 1,300 refs make 3
  batches of 512.
- DS9 spec line 78 ("No patient or participant data") and station law lines 28-31 (only Andy admits).

### 3. Must-fix

**RMF1. Without `route`, the owner's footpaths still leave, through every episode's `session_id`.** Places: D6, D7,
D10; 5.2 "Log rows" (spec lines 279-290); the dry run's "What stays here" (line 390); 6.2's `episodes` row and the
scrubbed-column list (lines 469, 534-537); 8's `Need(admission)` (line 848); check 12 (line 1046); 16 "Log rows"
(line 1466). Interface row 13. T section 12 (T line 1458).

Row 13 rests on this premise: log rows are what the owner's trails are made of, so without `route` no trail leaves.
The premise is false.
- Every episode records the session that wrote it. `remember` writes `session_id=_session_id`
  (`engram/server.py:1869-1876`; the column is `engram/migrations/001_initial.sql:48`). 6.2 copies episodes with every
  column except `rowid`.
- T builds trails from episodes alone. A session is "any distinct non-null `episodes.session_id`", and wrote touches
  are "every episode carrying that `session_id`" (T lines 197-204). A trail needs two touches (T line 256). So every
  shipped session that wrote two episodes in the lane has a trail on the imprint.
- Calibration derives exactly these paths. `paths.report` groups episodes by `session_id` in `(created_at, id)` order
  and computes each session's path and its "different routes" (`engram/paths.py:338-354`, `:418-423`), and admission
  runs it (`engram/calibrate.py:295-296`). The spec's own example shows "31 session paths" (spec line 1093).

What follows:
- The dry run and the confirm view present trails as part of the `route` choice only. The dry run even lists "session
  provenance" under what stays home (line 390). Yet the order in which the owner's sessions wrote their memories
  leaves with every imprint.
- Under P's `need(imprint)`, a kept trail needs `recall`, `read` and `imprint` on it (P 6.4). Without `route` there is
  no r_T to cover it. `Need(admission)` names only "a trail of S whose log rows I holds" (line 848), so it leaves out
  objects the package keeps.
- T's test "built without `route`, … `trails.py` finds no trail on it" (T line 1458) fails on any fixture whose session
  wrote two episodes.

The vision says an agent's trails are the person's to share ("Count its own trails as the person's"), and T 8 says
"sharing a memory is still not consent to sharing routes". Fix, as Rio Grande's call, one of:
- **(a) The safest default, which I recommend.** Without `route`, set `episodes.session_id` to null in the package. Add
  it to D6's scrubbed columns, to check 12 ("without `route`, every `episodes.session_id` is null") and to the dry run
  ("which session wrote each memory stays here unless you choose route"). Calibration's `paths` analysis then reports
  no sessions, and the report should say why. Row 13 and T's test then hold as written. One note for the builder: once
  no session id ships, X*'s subtraction of the session ids that shipped rows keep (line 584) subtracts nothing, so an
  episode whose text names a session id becomes a cross-reference (D23).
- **(b)** Keep session ids, and say plainly that each session's writing order leaves with every imprint. r_T, with
  `imprint`, `read` and `recall` on trails, is then part of every permission, `Need(admission)` covers wrote-touch
  trails, the dry run and the confirm view say so, and T's test becomes "finds only wrote-touch trails".

Either way, add a test: a package built without `route`, from a store whose session wrote two work episodes, has (a)
no `session_id`, or (b) a permission that covers its trails.

### 4. Should-fix

**RS1. r_M names `lanes: ["work"]`, and the spec reads lanes in a way P rules out.** Places: spec line 755; 8, "The
denotation" (lines 817-818); 17 step 1 (lines 1572-1576). Interface row 2.
For an allow, P reads a memory's lane from the source's lane notes, "never from the published copy", and "a memory
with no lane note matches no allow whose `lanes` is a list" (P 5.3, P lines 335 and 356). The spec reads the lane from
the imprint and says this is "as that spec's 5.3 asks". It is not. Two effects:
- If the owner, or their agent in compression review, moves a shipped memory from work to personal at home, P stops
  matching r_M on it, but the station keeps allowing it. That differs from P in the wider direction, and the header
  says P wins.
- 17 step 1 moves the records "into that ledger unchanged". A station ledger has no lane notes for `mem:S/…` refs, so
  P would then refuse every use under r_M.
*Fix:* r_M reaches memories only through its collection (D36), and P28 lets lanes and layers only narrow. So set
r_M's `lanes` and `layers` to `"*"`. Keep the scope's lanes in the request, the manifest and check 12. Drop the "read
from the imprint" bullet, and keep item 6 of what P doesn't cover ("Later changes at home"). The signing test in 16
then also checks `lanes: "*"`.

**RS2. P's records don't name the copy. So ⟦p⟧ ∩ ⟦c⟧ is not P's meet once an owner has a second imprint, and a
ship-withdrawn copy's records stay in force.** Places: 8 (lines 826-836 and 838-843); D17; 12 "Withdrawal"; 17 step 1
(lines 1575-1576). Interface rows 6 and 24.
- The interface pass moved the copy binding out of r_M and into the ceiling ("of the copy the wrapper names"). A P
  use is `(a, P, o, x, p, t)`, with no copy (P 6.1, P line 456). P sees a copy only through the holding place H (P 6.3
  item 3), and every imprint here has H = `place:home/<operator>`.
- P's owner layer is the union of every effective allow in the owner's home (P line 462). When the ship withdraws, r_M
  and r_T stay unrevoked until their end, by design (D17). So once the owner sends a second imprint of the same store,
  the first copy's records also match uses of the second copy's memories by the same agent in the same place.
  Example: copy 1 had `route` and the ship withdrew it; copy 2 has no `route`. Under P, r_M1 and r_T1 still allow a
  trail evaluation on copy 2 until r_T1 ends.
- Nothing widens in step 1, because the station decides with this imprint's records only. But "So ⟦p⟧ ∩ ⟦c⟧ is that
  spec's meet over `Req`" (line 836) is false in general, and 17 step 1 would carry the wider result into step 2.
*Fix:* Say that the station decides by the narrower per-imprint check, ⟦p_I⟧ ∩ ⟦c_I⟧ ⊆ P's meet, and why. Say that a
use names its copy (P 9.1 has a `copy` column, and the import fills it). In 17 step 1, say that a record whose copy the
ship withdrew, or which ended or was deleted, moves into a ledger revoked (the station refused it), never in force,
and that the owner's `shortened` and `withdrawn` receipts become P replacements and revocations. Rio Grande's call.

**RS3. Admission is decided once, at approval, and never checks the end again.** Places: 10, "Hand-off" step 4 and
"Deletion wins" (lines 995-1016); 12 (line 1183).
`station-approve` decides admission in its own transaction. The detached unit then checks only for a tombstone and for
`approved.json`. `make station-imprint-admit` with no ID resumes approved imprints after a crash (line 1002), maybe
days later. If the effective end passed in between, or the ship shortened it, calibration runs on a copy whose
permission has ended, until the hourly sweep deletes it. P says "Time needs no act", and its anti-goal "Waiting
caches" rules out an expiry that takes effect later than the next decision at or after its time (P lines 1001 and
1391-1392). *Fix:* Admission reruns section 8's check, with the effective end and the ship's shortening, at its start
and before each write. On failure it stops ("ended during admission") with a `failed` receipt. Add a test: approve,
move the clock past the end, resume.

**RS4. Stores older than identity count as complete roots, so an old copy can count as independent.** Place: 11
(lines 1119-1120).
A `retroactive` store took its id from its earliest episode (`engram/store_identity.py:84-102`). A fork made before
identity existed is a full copy by backup (`engram/cli.py:15-49`) with no `forked_from_instance_id`. If one side pruned
its earliest episode (`engram/storage.py:734-747`, `:760`) before both derived their ids, the ids differ. Both are then
roots with ancestry [] and complete, and `independent` returns true for a store and its own copy. Such forks exist:
`instances.json` records their `forked_from` (`engram/federation.py:127-142`). Genome-synced episodes carry
`origin_instance_id` only since migration 028 (`engram/migrations/028_store_identity.sql:10-12`), so row-level
provenance has the same gap. This is the anti-goal "False agreement". *Fix:* Give a `retroactive` store ancestry []
and **incomplete**, since nothing recorded copies made before identity. `independent` then returns `unknown` for it,
which never counts. Say so for the rail spec, and add a test. Rio Grande's call.

**RS5. Some rows about the owner are kept with no end, and the owner is never told.** Places: D32 (line 188); section
9's table (lines 957 and 959); the confirm view's retention text (lines 930-932); 7.1's terminal message (lines
651-653).
- The request row (ids, ship, owner, status, times) is "never" removed (line 957). That includes a request the owner
  declined or let expire. After 400 days, each deleted imprint also leaves "a content-free row: id, ship, owner, final
  status and times" for good (D32). Both are in nightly backups.
- Tombstones keep the `withdrawn` and `deleted` receipts for good (line 959), with every removed file's path, size and
  SHA-256.
- The confirm view mentions only "400 days after the copy is deleted" and about 8 weeks of backups. The terminal
  message before sending says nothing about the row a request leaves even when declined.
That someone sent their memories to a station is about them, as D25 says. *Fix:* Either give these rows and tombstones
an end (for example 400 days, the receipts' own), or say exactly what stays with no end in the terminal message before
sending, in the confirm view and in `imprint-status`. Rio Grande's call.

### 5. Nits

- **RN1.** `covers` is never defined (check 11, line 1043; the admission test, line 1549). It is left over from an
  earlier draft. Say "`scope.lanes`" and "the scope".
- **RN2.** `contents` "counts every non-empty table except shadow tables and `sqlite_sequence`" (line 673). But `meta`,
  `schema_version` and the FTS tables are non-empty too, and the example leaves them out. Section 14's "exactly the
  section 7.1 keys, at every level" (line 1410) can't fix a key set that depends on the data. List the keys: the ten
  digest tables of 5.4, each present only when non-empty.
- **RN3.** Goal 3 and the anti-goal "Early bytes" allow no request field the view doesn't show. The request also holds
  `kind`, `version`, `imprint_id` and the full 64-hex `plan_digest`. The view shows 8 hex of the digest and no imprint
  id. They hold no content. Either show the imprint's short id and say the whole digest is sent, or restate the rule as
  "only what the view shows, plus ids that hold no content". The test at line 1502 needs the same words.
- **RN4.** The manifest's `source.ancestry` sends the ids of the stores the owner's store was copied from (the genome,
  other instances). The view names only "the store id". Name the ancestry in the view, or on the terminal before the
  manifest goes.
- **RN5.** P 9.1 writes one receipt per imprint batch. The spec writes one row per action per batch (line 1314), and one
  summary row for roads and trails whose `use_subjects` names the copy, which is not an object of any P kind (line
  1325). Both suit privacy. Say they depart from P 9.1's form, as Rio Grande's call, so counts by `uses --action` are
  read right.
- **RN6.** P refuses a `route` use whose road or trail names more than 32 memories (`BOUND`, P 6.4). Section 8's finite
  check (line 868) depends on o only through its kind, so a trail of up to 512 touches passes. Say whether the
  evaluation's `route` objects are roads and steps only (two memories each), or that `BOUND` applies, so the station
  and P agree.
- **RN7.** In P's terms the ceiling ⟦c⟧ is the layer of `place:home/<operator>` (line 835), which is Andy's own consent
  (P section 2, "Home place"). Say it is a fixed rule over the station's receipts (uses of copy I are refused after a
  withdrawal receipt, and from the ship's shortened end), so no one edits a layer when the ship acts. Add a deploy gate
  in which Andy accepts C as his home's rule for imprints.
- **RN8.** With a permissions ledger present, a memory whose latest lane note is `pending` counts as neither lane for an
  allow (P 5.3). base(m) reads the lane column (line 236). Leave such memories home and count them in the dry run.
- **RN9.** The admission unit is named by the 4-hex short id (line 997), so two imprints with one short id would clash.
  Use the full imprint id.
- **RN10.** Withdrawal runs in the lighthouse and removes `~/.engram/imprints/…`. Section 15 doesn't say how the
  lighthouse learns that root, since the Makefile's `IMPRINTS` reaches only the CLI. Name the flag or the environment
  variable.

### 6. The interface table, row by row

The spec agrees with P and T as the table states on rows 1, 3, 4, 5, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20,
21 (see RN5), 22, 23, 24 (see RS2 and RN7), 25, 26 (see RS4), 27, 28, 29, 30, 31 and 32.

It disagrees, or the row is incomplete, on three:
- **Row 13** (log rows are the owner's trails). The premise misses `episodes.session_id`. RMF1. T's test at its line
  1458 changes with the fix.
- **Row 2** (what an outside-home allow may name). r_M's shape passes P28, but naming `lanes: ["work"]` brings in P
  5.3's lane-note rule, which the station can't meet. RS1.
- **Row 6** (the meet). The ceiling's copy binding lies outside P's use tuple, so the decision equals P's meet only
  while the owner holds one imprint permission at the station. RS2.

I checked these in detail: the allow file's fields and path (I 12; T 7, items 2–6), the tombstone path, `valid_until`
as the effective end, `--lane` and `--deadline 1740`, the 4G / 1,800 s detached unit (I 10 and 12; T 7 step 10 and its
section 10 table), `laid_by` on an imprint (T line 645), the other-people question in all three specs (I 20; P 19, P
lines 1609-1613; T 14, T lines 1500-1503), both imprint kinds in P's step 2 (P lines 1352-1355), and P 6.4's note on
`imprint` over trails (P lines 518-519).

### 7. Still open with Andy (this re-check changes none of them)

- **Memories that mention other people.** Each spec keeps its safest default. The imprint spec's is the strictest: no
  memory with a recorded co-subject leaves, and the owner ticks the check for the rest. I decide nothing here.
- Which store to imprint first, and its owner's yes. Whether the station-signed browser yes is enough for step 1. The
  license. One permission an agent may set on its own. What the county sets.

## Re-check response (revision 3), 2026-10-25

Reviser: a fresh agent on the Pi, working for Rio Grande. I took no part in writing revisions 1 or 2, either review,
the first response or the interface pass. I read the vision, the spec, this file, the interface table, and the parts
of P (now revision 3) and T (now revision 6) that the re-check names. Both were revised in parallel with this pass, so
where they changed under the re-check I say so. I checked every new claim about code by reading the code; the new
citations are listed at the end. Section numbers are revision 3's. Nothing here is committed, pushed or posted.

I applied the must-fix, all five should-fix items and all ten nits. I declined none. Three are applied in another
form than the re-check named: RS2 (stronger), RN4 (one of its two options) and RN6 (P's revision 3 form). Each line
says why. Every decision below is Rio Grande's call unless it quotes Andy, station law or P.

### Must-fix

- **RMF1. Applied, option (a).** I confirmed the premise in code. `remember` writes `session_id=_session_id` on every
  episode (`engram/server.py:1869-1876`; column at `engram/migrations/001_initial.sql:48`), and so does the nudge hook
  (`engram/hooks/nudge.py:531-535`). `paths.report` counts distinct non-null ids and `session_paths` groups by them
  (`engram/paths.py:338-354`, `:418-427`), run at `engram/calibrate.py:295-296`. What changed:
  - D6 adds `episodes.session_id` to the scrubbed columns, and D7 says session ids leave only with `route`. D10 says
    session ids and log rows. 5.2 is now "Log rows and session ids". 5.3's closure bullet names both.
  - Without `route`, every shipped episode's `session_id` is null. One step narrower than asked: with `route`, an
    episode keeps its id only when its session is closed at t₁, the same rule as its log rows. So a session still
    open at t₁ leaves no mark at all, and T never sees a part-trail whose recalls stayed home.
  - 5.4's episodes key is now `[id, lane, created_at, session_id as kept, …]`, so the digest and check 13 bind it. The
    re-check didn't ask for this, but the spec claims the keys bind "every column the trails read".
  - The dry run gains a "Session ids" line, "What stays here" now names the session registry instead of "session
    provenance", and it adds a line for the case without `route`. "Permission you would give" and the confirm view say
    that keeping which session wrote each memory is part of `route`. `make imprint-read` shows null where the package
    will hold null (`engram/store_reader.py:37-41`).
  - 6.2's `episodes` row and the scrubbed-column list name the scrub.
  - 8: `Need(admission)` now ranges over R(I), the roads and trails derivable from the package's session ids and log
    rows. Following P 6.4 (revision 3), it also adds `recall` on every memory they name. Admission is "with `route`,
    also on their roads and trails" in section 12's table.
  - Check 12 requires every `episodes.session_id` to be null without `route`. 10's calibration bullet makes the report
    say "paths: no session ids, because route was not chosen" (`engram/paths.py:349`, `:423`). The "31 session
    paths" example is marked as the `route` case.
  - 6.4, item 1: as the re-check noted, without `route` nothing is subtracted from X*, so text naming a registered
    session's id is a cross-reference. I also dropped the recall-id subtraction, which subtracted nothing. A recall id
    is kept only inside `context` (`engram/server.py:2369-2384`), and the re-check's section 2 found the same.
  - New anti-goal "Footpaths without `route`". New test "No footpath without `route`": a store with one closed
    session that wrote two work episodes and made no recall. Built without `route` it has null ids, empty logs and no
    session for a reader written from T 4. Built with `route` it has one two-touch trail. An open session keeps no id.
    A hand-set id fails checks 12 and 13. The calibration test now holds for every section but `paths`.
  - T's test (T section 12, "built without `route`") now holds as written. T's re-check pass already rewrote it, and
    added R18 and I5, after reading this revision in progress.

### Should-fix

- **RS1. Applied.** r_M names `"*"` for `layers` and `lanes` (D36; section 8). P's own example of an allow by
  collection does the same (P 5.2). One fact changed under the re-check: P revision 3 added "A copy held away from its
  source's ledger" (P 5.3), which reads an imprint's lanes from the imprint. So the re-check's first effect, re-lanes
  at home, is now P's stated rule rather than a disagreement. The second effect still held, since a step-2 ledger has
  no lane notes for `mem:S/…` refs. `"*"` removes both. The denotation no longer reads lanes, and points to P's
  paragraph for any later record that names lanes, so P's citation of I 8 still lands. The scope's lanes stay in the
  request, the manifest and check 12. The signing test checks `"*"`. Interface row 2 is updated.
- **RS2. Applied, in a stronger form.** P revision 3 now puts the copy h in every use (P 6.1), so a use names its copy
  as the re-check asked. The re-check suggested only saying that the station's per-imprint check is narrower than P's
  meet. I made the two equal instead. P says its `decide` and `explain` agree with the station's check (P 6.4, last
  paragraph), and a known gap would break that. The ceiling is now one rule per copy I (D38; section 8, items 1–5): uses
  of h_I only, on objects(I) or R(I), within I's own records' actions and purposes, from `valid_from` to I's effective
  end, and before any `withdrawn` receipt of I. Section 8 then shows that for every use of copy I, P's meet over `Req`
  is exactly ⟦c_I⟧ = ⟦p_I⟧ ∩ ⟦c_I⟧, however many imprints the owner holds. It is narrower only once a step-2 ledger adds
  the owner's denies. I corrected the example: copy 1's r_M matches copy 2's uses only for memories copy 1 also held,
  since its collection holds only copy 1's refs. 17 step 1 says what moves into a step-2 ledger:
  - the owner's `shortened` and `withdrawn` receipts become P replacements and revocations;
  - a record whose copy the ship withdrew, or that ended, or whose copy was deleted, moves in revoked or not at all,
    never in force. Which of the two is P step 2's to say, since the station is no steward of the owner's home (P 7.1);
  - the ceiling stays a layer kept outside the ledger (P 6.1).

  New test "One ceiling per copy". It compares the station's check with P's `decide` on a fixture of two imprints.
  Rows 6 and 24 are updated.
- **RS3. Applied** (D39; 10, "Admission is decided again" and "Deletion and the end win"; 12; 13; 16).
  - Every admission run, the first included, starts with the new `station-imprint-admit-begin`. It reruns section 8's
    whole check at its own time, with the effective end and every shortening by the owner or the ship. If allowed, it
    writes `<id>.state/admission.json` with the effective end. A shortening replaces that file atomically, as it does a
    use's allow files.
  - Admission checks the file, the tombstone and `approved.json` before each write and before calibration. The other
    terms are fixed by signed records and code.
  - A refusal or an end mid-run gives a `failed` receipt naming the term, and deletion with reason `ended`, before any
    sweep.
  - New test "Admission after the end": a resume past the end, a ship's shortening that has passed, and an end that
    passes during calibration.
- **RS4. Applied** (D13; 11; 16; 17 step 6; row 26). I confirmed it in code: the old `fork` is a whole backup copy
  (`engram/cli.py:15-49`, the copy at `:42`); the retroactive id comes from the earliest episode
  (`engram/store_identity.py:84-102`); pruning deletes episodes (`engram/storage.py:734-747`, `:760`); and only a
  store this open created gets a random `creation` id (`engram/storage.py:246-254`). Now:
  - A store of origin `retroactive`, or with no stored identity, has ancestry [] and is incomplete, so `independent`
    is `unknown` and never counts. An imprint or fork of it inherits the incompleteness. `creation` roots stay
    complete.
  - Two new rows in the lineage table, and the lineage test covers the pruned-copy case.
  - Also added: a `genome_sync` episode with a null `origin_instance_id` is a copy of unknown origin. A sync fills
    the origin in only when the genome still holds an episode with the same content hash (`engram/federation.py:187-193`).
  - Told the rail spec in 11 and 17: stores older than identity count for nothing until a later spec gives them a
    complete ancestry.
- **RS5. Applied, first option: everything has an end** (D32; 7.1; 9; 12; 14; 16; new anti-goal "Kept for good").
  - The row, the permission, the receipts and the tombstone all go 400 days after `deleted`, the receipts' own term.
    A declined or expired request's row goes after 30 days. That is long enough for a rerun of `make imprint-send`
    to report the outcome, and the owner's machine keeps its own record.
  - The terminal message before sending, the confirm view and `imprint-status` say exactly this, including the row a
    decline leaves, and the backups' "about 8 weeks more".
  - Since tombstones now end, restore reconciliation covers any live row whose files are gone. I checked the
    rotation (`peer/superyak_peer/backups.py:30`, `:109-119`): a copy older than 400 days survives only if fewer than
    8 weeks or 14 days since had a backup, and such a restored row is removed again.

### Nits

- **RN1. Applied.** `scope.lanes` in check 11, and "a lane outside `scope.lanes` or a time outside the scope" in the
  admission test.
- **RN2. Applied.** 7.1 lists the ten digest tables, each present only when non-empty. Section 14's check and the
  request test say the same.
- **RN3. Applied, both halves.** The view shows the imprint's short id, the request's short id, and the digest's first
  8 characters with "the whole 64-character digest is sent". Goal 3, the anti-goal, D26, 7.1 and the test restate the
  rule as "everything the view shows, plus the fixed labels `kind` and `version`".
- **RN4. Applied, the view option.** The request now carries `source_ancestry` and `source_ancestry_complete`. The dry
  run, the terminal and the confirm view name them, the manifest must equal them, and section 14 gives their formats.
  The cost is that these ids reach the station before the yes. They are held only in staging `request.json`, deleted
  at decline or expiry, and never in `peer.sqlite3`. I chose this over the terminal-only option so the yes binds what
  the manifest later carries.
- **RN5. Applied** (12). The imported rows are named as P 9.1's imported form, with its four differences from a local
  receipt. P revision 3 now lists the same four. Row 21 is updated.
- **RN6. Applied in P revision 3's form.** P now defines bulk uses (P 6.4, P33), so neither option the re-check named
  is needed. Section 8 says admission and the evaluation are bulk uses: the 32 is waived, and P's other bounds hold
  (100,000 derived objects per counted bulk use, 8 subjects, 43 layers). There is a test for a 40-touch trail. Row 8
  is updated.
- **RN7. Applied** (D38; 8; 18). The ceiling is stated as one rule over the station's records and receipts, so no one
  edits a layer when the ship acts. New deploy gate: Andy accepts C and the five items as his home's rule before any
  imprint is approved.
- **RN8. Applied, slightly extended** (D40; 5.2 `pending(m)`; dry run; test). A memory whose latest lane note is
  `pending` stays home. So does one whose latest note names a lane other than its column, which is a re-lane that
  hasn't settled. Both only narrow.
- **RN9. Applied** (10; test). The unit is `superyak-imprint-admit-<full imprint id>`.
- **RN10. Applied** (10, "The imprints root"; 12; 15; 16; 18). One flag, `--imprints-dir`, on `superyak-peer serve`,
  every station command that touches imprints, and `imprint.py`. No environment variable sets it. Other changes:
  - The hand-off records the root in the request row, and every removal uses the recorded root.
  - The lighthouse's installed unit (`~/.config/systemd/user/superyak-lighthouse.service`, read today: its
    `ExecStart` passes `--data-dir`, `--host`, `--port`, `--proxy-headers`, `--origin` and `--share-link-file` only)
    gains the flag, and a deploy gate checks that it names the Makefile's root.

### The interface table

I updated rows 2, 6, 8, 13, 21, 24 and 26, each with a note under "Imprint re-check pass", plus the I line in the
header and "What changed, by spec". P's and T's re-check passes were editing the table at the same time. I appended to
their text and changed none of it. Row 13 notes:
- T's pass had listed three points pending in I: check 12, the calibration test and "31 session paths". All three
  are applied.
- One point for P's next revision. P 6.4's last paragraph says "the trails whose log rows it keeps"; it should read
  "the roads and trails derivable from its session ids and log rows". The decisions agree either way, since r_T covers
  every road and trail of the store.

### Not taken in this pass

T revision 6 also asks this spec for I2 (`use-finished` end codes, retiring a use's allow file, report and result file
names, the use id format, always passing `--lane`), I3 (passing the embedder socket to the use's unit) and I6 (section
16's recall-row assertion, which T says fails on any fixture with a mixed-lane recall). These come from T's re-check,
not this one, and cover I's side of rows 14, 24, 27 and 28. I left them for Rio Grande to schedule. I6 matters most:
T is the source of truth for trails, and it says a test assertion here is false, so it should be fixed before the
plan.

### Still open with Andy (unchanged)

- **Memories that mention other people.** The default is unchanged and stays the strictest of the three specs: no
  memory with a recorded co-subject leaves, and the owner ticks the check for the rest (D27; 6.4, item 5; section 20).
  This pass decides nothing about it. RMF1 and RN8 only narrow what leaves.
- Which store to imprint first, and its owner's yes. Whether the station-signed browser yes is enough for step 1. The
  license. One permission an agent may set on its own. What the county sets.

### New code citations in revision 3, each read for this pass

`engram/server.py:1869-1876`, `:2369-2384`; `engram/migrations/001_initial.sql:48`; `engram/hooks/nudge.py:531-535`;
`engram/paths.py:338-354`, `:349`, `:418-427`, `:423`; `engram/calibrate.py:295-296`; `engram/store_reader.py:37-41`;
`engram/store_identity.py:84-102`; `engram/storage.py:246-254`, `:734-747`, `:760`; `engram/cli.py:15-49`, `:42`;
`engram/federation.py:127-142`, `:187-193`; `peer/superyak_peer/backups.py:30`, `:109-119`; and the installed
lighthouse unit's `ExecStart`.

## Final check (revision 3), 2026-10-25

Reviewer: a fresh agent on the Pi, making the final check in Andy's place under station law section 3. I took no part
in writing revisions 1 to 3, the first review, the re-check, either response or the interface pass. I read the vision,
the whole spec as it stands in the working tree (revision 3, uncommitted), this file, the interface table, and the
parts of P (revision 3) and T (revision 6) that RMF1 and row 13 name. I checked every code claim below by reading the
code today. File:line references are relative to `/home/andy/superyak/.worktrees/trail-arrows/`. "Spec line" means a
line of `engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md` as it stands today. Nothing here edits a
spec. I committed, pushed and posted nothing.

VERDICT: APPROVE

RMF1 is resolved. The fixes add no must-fix defect and break no interface. Three should-fix items remain (FS1–FS3).
FS3 is not from this pass: it is the trail spec's pending asks, and it must be scheduled before the plan. The nits are
optional. Every fix named below is Rio Grande's call.

### 1. RMF1: resolved, option (a)

The premise holds in code. `remember` writes `session_id=_session_id` (`engram/server.py:1869-1876`). So do
`challenge_instinct` and `retire_instinct` (`engram/server.py:2834-2836`, `:2885-2887`) and the nudge hook's own insert
(`engram/hooks/nudge.py:531-535`). The column is `engram/migrations/001_initial.sql:48`. A session id is the Claude
session id or a random UUID (`engram/server.py:1332`), so L1's UUID scan sees it.

Each place RMF1 named:

- **D6, D7, D10** (spec lines 176, 177, 180). `episodes.session_id` is a scrubbed column. Session ids leave only with
  `route`, and then only for sessions closed at t₁. D10 names session ids beside log rows as what makes the trails.
- **5.2, "Log rows and session ids"** (spec lines 302-327). It states the premise with the code above. Without `route`,
  every episode's `session_id` is null. The closed-at-t₁ rule reads only rows before t₁, so it is the same at the plan
  and the build. With `route`, a session open at t₁ keeps no session id either. That only narrows.
- **The dry run** (spec lines 421-432, 446-448). A "Session ids" line appears only with `route`. "Session provenance"
  is gone from the spec; "What stays here" names the session registry, and adds "Without route, which session wrote
  each episode, and the recall log, would stay here too." The permission's words, and the confirm view's (spec lines
  1060-1062), put keeping which session wrote each memory inside `route`.
- **5.4** (spec lines 388, 398-399). The episodes key includes `session_id as kept`, so the digest and check 13 bind it.
- **6.2** (spec lines 515, 580-583). The `episodes` row and the scrubbed-column list name the scrub.
- **6.4, item 1** (spec lines 629-636). Without `route`, nothing is subtracted from X*. `session_registry` is keyed by
  `session_id` (`engram/migrations/023_session_registry.sql:5`), so every registered session's id is in X*. With
  `route`, the kept ids are subtracted, so the kept column is no cross-reference. Dropping the recall-id subtraction
  loses nothing: no migration keys a table by `recall_id` (a grep of `engram/migrations/*.sql` finds none), and a
  recall row's own `id` is a fresh uuid apart from `recall_id` (`engram/server.py:2369-2386`).
- **8, `Need(admission)`** (spec lines 959-972). It ranges over R(I), the roads and trails derivable from the package's
  session ids and log rows. R(I) is empty without `route`, and r_T exists exactly when it can be non-empty. Every pair
  it needs is in C and in the matching record. See FS1 for the one use it still leaves out.
- **Check 12** (spec lines 1222-1226). Without `route`, every `episodes.session_id` is null. "Each check fails" adds a
  session id in a package without `route` (spec line 1810).
- **Section 10** (spec lines 1254-1257, 1276-1281). `session_paths` selects only non-null ids (`engram/paths.py:349`)
  and `report` counts only them (`:423`). The "31 session paths" example is marked as the `route` case.
- **Tests** (spec lines 1698-1705). "No footpath without `route`" is the test RMF1 asked for, with an open session, a
  hand-set id that fails checks 12 and 13, and the cross-reference case.
- **T.** A session comes only from `episodes.session_id` or a recall row's `context.session_id`, and wrote touches
  only from the first (T lines 204-211). Without `route` the package holds neither, so T's test now holds as written
  (T lines 1607-1611; the re-check's T line 1458). T R18 (T line 71) and T 7 (T lines 919-938) state the same rule.
- **Interface row 13.** Its premise is now true, and its "Imprint re-check pass" note matches the spec.

No other episode column names a session. I checked every column the migrations add to `episodes` (001; 002:4-7;
004:27; 006:3-4; 007:3; 013:3; 018:4; 022:5; 028:10-12) and every episode writer (`engram/server.py:1869`, `:2834`,
`:2885`; `engram/engine.py:102`; `engram/deep_pass.py:283`; `engram/sheaf.py:366`; `engram/federation.py:197`, `:221`;
`engram/hooks/nudge.py:531`). The writers' own `context` dicts hold no session id. A caller of `remember` could put one
in `context`. If it names a registered session, it is a cross-reference without `route`, so the build refuses.

### 2. Claims I checked and found true (new in revision 3)

- `paths.session_paths` groups episodes by `session_id` in `(created_at, id)` order (`engram/paths.py:338-354`), and
  `report` counts distinct non-null ids (`:418-427`). Calibration runs it (`engram/calibrate.py:295-296`) among its
  analyses (`:286-296`).
- Calibration reads no log row's content. sheaf's only `memory_log` read is `_rate_limited` (`engram/sheaf.py:283-298`),
  called only at `:323`, in the sleep pass, which calibration doesn't run. `first_open_preview` reads only episodes
  (`engram/calibrate.py:90-93`). See FS2 for the row counts.
- `store_reader`'s episode fields include `session_id` (`engram/store_reader.py:37-41`), and `read_episodes` reads only
  episodes (`:188-210`), as the `imprint-read` bullet says.
- P's ceiling is a layer kept outside a ledger, which the meet treats like any other (P lines 501-503). P's `read`
  "returns content to a program", and `imprint` needs `recall`, `read` and `imprint` on every object kept (P lines 557,
  560). P counts a layer that appears twice once (P line 546).

### 3. Must-fix

None.

### 4. Should-fix

**FS1. With `route`, calibration reads the kept trails for purpose `calibration`, and no record allows that.** Places:
r_T (spec lines 826-831); ceiling item 2 (spec lines 912-913); `Need(admission)` (spec lines 959-961); section 10's
calibration bullet and example (spec lines 1254-1257, 1276-1281); section 12's table (spec line 1384).

- Calibration always runs `paths.report` (`engram/calibrate.py:295-296`). With `route`, it turns the kept session ids
  into each session's path (`engram/paths.py:348-354`). Its report names each session with its shape
  (`"session": p.key`, `:446-449`) and the pairs of sessions that took "different routes" (`"a"`, `"b"`, `:328-330`).
  T says calibration "reads exactly" the wrote-touch trails (T line 923). That is a `read` on R(I), in P's sense.
- r_T allows only `trail-evaluation` (spec line 828). Item 2 takes the purpose for R(I) from r_T. `Need(admission)`
  lists `read` on R(I) only for `trail-evaluation`. So admission does a use its `Need` leaves out. P would refuse it
  (`NO_ALLOW`), and the owner's imported use rows name the trails' use as `trail-evaluation` only (section 12).
- Nothing leaves a machine that the owner didn't send, and the report holds no content. That is why this isn't a
  must-fix. It is also not new: revision 2's calibration read the same paths. Revision 3's `Need(admission)` made it
  visible.

*Fix, Rio Grande's call, one of:*
- **(a) The safest default, which I recommend.** On an imprint, admission runs calibration without the paths analysis
  (a `calibrate` flag beside `no_content`). The report says "paths: not measured at admission; trails are used only by
  the trail evaluation". The dry run's words ("for the trail evaluation, keeping which session wrote each memory") stay
  exact. The "31 session paths" example changes. T reads nothing from calibration's `paths` section (T lines 923-933
  only note its cost), so T loses nothing.
- **(b)** Add `calibration` to r_T's purposes and `read` on R(I) for `calibration` to `Need(admission)`. Say in the dry
  run and the confirm view that calibration measures the shape of the kept sessions. C holds (`read`, `calibration`)
  but not (`route`, `calibration`), so no `route` use for calibration follows.

Either way, add a test: with `route`, every use admission performs is in its `Need`, and P's `decide` agrees with the
station's check on each.

**FS2. Calibration's report differs in more than `paths`, and its survey says "0 sessions" without saying why.**
Places: 16, "Log rows" (spec lines 1695-1697); section 10's calibration bullet (spec lines 1254-1257); 5.2 (spec lines
312-316).

- Calibration surveys the snapshot (`engram/calibrate.py:258`). The survey counts every table's rows, the log tables'
  included (`engram/store_reader.py:111-121`), and `COUNT(DISTINCT session_id)` over episodes (`:126-131`). report.md
  prints it as "… N sessions" (`engram/calibrate.py:328-331`). Without `route` that is 0 sessions and 0 log rows. With
  it, the example's 57 and 1,940. The `source` and `identity` sections also differ between any two packages, since
  their bytes and imprint ids differ.
- So the test "equals, in every section but `paths`" fails as written. T 7 already says the survey "counts no sessions
  either" (T line 933), so I and T disagree on it.

*Fix:* compare the analyses other than `paths` (`first_open`, `persistence_scores`, `cohesion`, `persistence`), and the
survey apart from `episodes.sessions` and the log tables' row counts. Put the same "because route was not chosen" note
beside the survey's session count. In 5.2, say that calibration reads no log row but counts the log tables' rows.

**FS3. The trail spec's asks I2, I3 and I6 are still pending here** (interface rows 14, 24, 27 and 28). They are not
from this re-check. The reviser left them for Rio Grande ("Not taken in this pass", above). Two make this spec's own
text wrong today:

- Section 12 (spec lines 1408-1411) records a use's end as "withdrawn" or "not evaluable". So a shortening during a run
  would be recorded as a withdrawal (T's I2; row 24). Nothing retires a finished use's allow file, and the report's
  file name isn't fixed, though T's rerun check reads it (T's I2; row 27).
- 16, "Recall rows" (spec lines 1710-1711): "A trail derived from the package equals the trail derived from the source
  restricted to M" fails on a mixed-lane recall (T's I6; row 14).
- The use's unit doesn't pass `--setenv=ENGRAM_EMBEDDER_SOCKET` (T's I3; row 28).

*Fix:* apply I2, I3 and I6 as T states them, before the plan. None of them lets more leave a machine.

### 5. Nits

- **FN1.** Without `route`, two records of use still leave. Resonances say which two shipped memories one recall
  returned together, first and last when (`engram/server.py:2488-2492`; `engram/storage.py:2003-2010`). Each episode's
  `last_accessed` is the time of its last recall (`engram/storage.py:628-638`). Neither names a session, T reads
  neither, and 6.4 items 2 and 3 cover them, so the anti-goal holds as written. The dry run's "Without route" line could
  say that they still leave, as T 7 states its write-time limit (T line 941).
- **FN2.** Section 8's proof that the station's check is P's meet (spec lines 925-938) takes the owner's and the
  operator's home layers as two layers. The spec allows the owner to be the operator (spec lines 848-849). Then both are
  `place:home/andy`, and P counts that layer once (P line 546). Step 1 still decides with ⟦p_I⟧ ∩ ⟦c_I⟧, so nothing
  widens. Say that the ceiling stays its own layer in `Req` then (P lines 501-503), so 17 step 1 carries that into a
  ledger. This matters if the first imprint is Andy's own store.
- **FN3.** For the next interface pass: row 13's first note still says "A test checks that calibration's report
  doesn't change" (see FS2). P 6.4's last paragraph (P lines 638-639) still says "the trails whose log rows it keeps",
  as row 13 already notes for P.

### 6. The interface table

Revision 3 updated rows 2, 6, 8, 13, 21, 24 and 26. I checked each against the spec:

- Row 2: r_M names `"*"` lanes and layers and one collection (spec lines 816-820, 833-840).
- Row 6: one ceiling per copy (spec lines 903-923), and the proof (spec lines 925-945). See FN2.
- Row 8: admission and the evaluation are P's bulk uses (spec lines 985-994).
- Row 13: matches. See FS1 and FS2.
- Row 21: the imported rows' four departures from P's local form (spec lines 1546-1552).
- Row 24: the ship acts through receipts (spec lines 950-955), and 17 step 1 (spec lines 1838-1852). Its end codes are
  pending (FS3).
- Row 26: a store older than identity is incomplete (spec lines 1308-1315).

The fixes broke no interface. T's R18, I5 and its synthetic-imprint test rest on exactly what this spec now ships.
P's `need(imprint)` on R(I) is met, apart from FS1's purpose. Rows 14, 27 and 28 are pending in this spec (FS3).

### 7. Still open with Andy (this check changes none of them)

- **Memories that mention other people.** The default is unchanged and stays the strictest of the three specs: no
  memory with a recorded co-subject leaves, and the owner ticks the check for the rest (D27; 6.4, item 5; section 20).
  I decide nothing here. RMF1's fix only narrows what leaves.
- Which store to imprint first, and its owner's yes. Whether the station-signed browser yes is enough for step 1. The
  license. One permission an agent may set on its own. What the county sets.

## Response to the final check (revision 4), 2026-10-25

Reviser: a fresh agent on the Pi, working for Rio Grande. I took no part in writing revisions 1 to 3, any review, the
earlier responses or the interface pass. I read the vision, the final check above, the spec, the interface table, and
T (revision 6): its status line, section 4, section 7 ("The imprint check", "What an imprint changes", "The cost,
chosen for privacy", step 8.2 and step 10), section 11 and the section 12 tests that I2, I3 and I6 name. I checked
every new claim about code by reading the code; the citations are listed at the end. Section numbers are revision
4's. I edited only the spec, this file and the interface table. I did not edit T or P, since P is being repaired by
someone else. Nothing here is committed, pushed or posted.

I applied FS1, FS2 and FS3. I declined nothing: no item lets more leave a machine or weakens a permission. FS1 takes
option (a). FS3 adds two end values T's list doesn't name; I say why below. I didn't take the nits FN1 and FN2. FN3's
first half, row 13's note, is covered by the row 13 note this pass adds. Every decision below is Rio Grande's call
unless it quotes Andy, station law or P.

### FS1. Applied, option (a)

The premise holds in code. Calibration runs `paths.report` (`engram/calibrate.py:295-296`), which turns each session
into a path (`engram/paths.py:338-354`) and names each session with its shape (`"session": p.key`, `:446-449`) and
pairs of sessions that took different routes (`"a"`, `"b"`, `:328-330`). report.md prints those pairs too
(`engram/calibrate.py:386-392`). That is a `read` on R(I) for `calibration`, and r_T allows the trails only for
`trail-evaluation`.

- **10, "No paths at admission".** `calibrate` gains `no_paths` (default false, today's behaviour). Admission always
  passes it, with or without `route`. The report's `paths` section says only "not measured at admission; trails are
  used only by the trail evaluation". T reads nothing from that section, so it loses nothing. The dry run's and confirm
  view's words stay exact.
- **8.** r_T's paragraph says that its one purpose is `trail-evaluation`, and that admission's calibration reads no
  trail. After `Need(admission)`, a paragraph lists what admission does: verification reads the session ids and log
  rows only to check what is kept, as part of the `imprint` use; calibration reads the memories for `calibration` and
  derives no road or trail.
- **The survey.** One more thing reads `episodes.session_id` at admission: the survey's `COUNT(DISTINCT session_id)`
  (`engram/store_reader.py:126-131`). I kept it, as FS2's fix assumes. It is a count over a column of the memories,
  read for `calibration` under r_M. It groups no episodes by session and orders none, so it derives no road or trail.
  Section 10 says so.
- **D7, D16, 5.2, 12's table, the `station-imprints` example and 15** say the same. The example now reads "88
  semantics measured; 57 sessions counted; paths not measured at admission".
- **The test FS1 asked for** is in 16, "Admission stays inside its `Need`": with `route`, every use admission performs
  is in `Need(admission)`, and P's `decide` agrees with the station's check on each.

### FS2. Applied

- **16, "Log rows".** The test now compares `first_open`, `persistence_scores`, `cohesion` and `persistence`, and the
  survey apart from `episodes.sessions` and the log tables' row counts. It says why `source` and `identity` differ.
  Both reports' `paths` sections say "not measured at admission", and neither report names a session id.
- **10, "The survey's counts".** `calibrate` gains `notes`, fixed sentences written beside named sections before the
  report is hashed. Without `route`, admission notes "0 sessions and 0 log rows, because route was not chosen" beside
  the survey's session count and the log tables' row counts. I put the note beside the log counts too, since those
  zeros are just as easy to misread.
- **5.2.** Calibration reads no log row's content, but its survey counts every table's rows
  (`engram/store_reader.py:111-121`) and the distinct session ids (`:126-131`).
- This makes I agree with T 7, which says the survey "counts no sessions either" without `route`.

### FS3. Applied: T's I2, I3 and I6, as T states them

I checked each ask against the rule I was given: decline it if it would let more leave a machine or weaken a
permission. None does. I2 retires allow files and refuses reruns, which only narrows. I3 passes the socket of an
embedder already on the Pi, which section 8 already names as where the text goes. I6 changes a test.

- **I2** (new D41; 12, 13, 14, 15, 16; rows 24 and 27).
  - A use id is a new lowercase uuid4 that `station-imprint-use-begin` makes. `imprint.py use` refuses any other form,
    and a use directory that already exists. It never creates the directory's parents.
  - `imprint.py use` writes `uses/<use id>/report.json`, only when `trails.py` exits 0, and `uses/<use id>/result.json`
    with the exit status and the time the run ended.
  - Finishing a use retires its allow file: `station-imprint-sync` deletes it, then writes `use-finished`, once.
  - `use-finished` records the end: `report` with its SHA-256; `withdrawn` only when the tombstone exists and the
    withdrawal came by the run's end; `ended`; `allow changed` otherwise; `not evaluable: limit` for a run a cap killed.
  - The use always passes `--lane`. With `LANE` left out it fills in the scope's one lane, and it refuses when the
    scope holds two.
  - **Two additions, both needed so no run is recorded as something it wasn't.** A station deletion during a run
    (`make station-imprint-delete`) writes a tombstone but is not a withdrawal, so it is recorded as `deleted`, with
    its reason. Any other run with no report, such as a crash, is `failed`, with its exit status. Without these, the
    first would read as a withdrawal, or both would read as a limit.
  - **How the sync knows a run is over.** To record a run a cap killed, the sync must know the unit has stopped. So
    the use's unit runs all three steps, begin, use and sync, as admission's does, and is named by the full imprint id.
    `use-started` is then written inside the unit, and its `RuntimeMaxSec=1800` has stopped it 1,800 s later. The sync
    finishes a use when `result.json` exists, when the imprint is `deleted`, or 1,800 s after `use-started`. It
    finishes none while the imprint is `deleting`, since a withdrawal is still removing files. One imprint runs one use
    at a time, which only narrows.
  - `use-started` and `use-finished` now name the use id, so the sync can find the use's directory. It is a random
    uuid4 the station made, and says nothing about the store.
- **I3** (D29; 12, 15, 16, 18; row 28). The unit gets `--setenv=ENGRAM_EMBEDDER_SOCKET=<path>` exactly when the
  station's `~/.config/superyak/runtime.json` names an `embedder_socket`, and nothing otherwise. A `systemd-run`
  unit starts "in a clean and detached execution environment" (systemd-run(1), systemd 252 on the Pi, read today).
  The Makefile reads only that key, by `superyak-runtime`'s rule (`scripts/runtime.py:84-89`): no file or no key
  passes nothing, and a value that isn't an absolute path stops the use before the unit starts. I read only that key
  because `superyak-runtime`'s whole reader (`scripts/runtime.py:56-89`) also requires `memory_home` and
  `default_instance`, which the Pi may not set. Section 18's "The run never downloads a model" now rests on T's
  `local_files_only=True`. It names the station user's `~/.kairos/models/fastembed` (`engram/embeddings.py:12`) for
  the model files without the service, and says a service that doesn't answer raises rather than loading a local copy
  (`engram/embeddings.py:191-194`).
- **I6** (16, "Recall rows"; row 14). The test no longer asserts that the package's trails equal the source's
  restricted to M. It asserts T's two statements: every touch derived from the package is a touch derived from the
  source, of the same memory, kind and time, in the same order within its recall, and suggested only if the source's
  is; and on every kept recall row, the "exactly one target" rule gives the source's answer. It points to T 12's
  synthetic-imprint test for what is lost. I added one condition: derive both files' touches with one `as_of`. The
  CLI's default `as_of` is each file's newest timestamp (T 4), so the two defaults differ, and T 7 names that as a
  cause of difference. With one `as_of`, the package's rows are a subset of the source's, filtered the same way, so
  both statements hold as T derives touches in its section 4.

### The interface table

I updated rows 13, 14, 24, 27 and 28, each with a note under "Imprint final-check pass", plus the I line in the header
and a bullet in "What changed, by spec". Rows 14, 24, 27 and 28 are marked agreed. Row 13 gets a note for FS1 and FS2,
and its "Agreed rule" cell now says that admission runs calibration without its paths analysis. Two points for T's
next pass:

- T's status line and section 11 still call I2's and I3's new parts and I6 pending in I. They are applied.
- T 7's "Calibration reads exactly that" holds for calibration on a plain copy, not at admission on an imprint. No
  rule of T's changes, since T reads nothing from calibration's `paths` section.

### Not taken in this pass

- FN1 (the dry run could say that resonances and `last_accessed` still leave without `route`) and FN2 (when the owner
  is the operator, say that the ceiling stays its own layer in `Req`). Both are optional and change no decision.
  FN2 matters if the first imprint is Andy's own store.
- FN3's second half is P's text (P 6.4's last paragraph), and P is being repaired by someone else.

### Still open with Andy (unchanged)

- **Memories that mention other people.** The default is unchanged and stays the strictest of the three specs: no
  memory with a recorded co-subject leaves, and the owner ticks the check for the rest (D27; 6.4, item 5; section 20).
  This pass decides nothing about it. FS1 only narrows what is read at the station.
- Which store to imprint first, and its owner's yes. Whether the station-signed browser yes is enough for step 1. The
  license. One permission an agent may set on its own. What the county sets.

### New code citations in revision 4, each read for this pass

`engram/calibrate.py:258`, `:295-296`, `:328-331`, `:386-392`; `engram/store_reader.py:111-121`, `:126-131`;
`engram/paths.py:328-330`, `:418-452`, `:446-449`; `scripts/runtime.py:56-89`, `:84-89`, `:597`, `:653-655`;
`engram/embeddings.py:12`, `:191-194`; systemd-run(1) on the Pi (systemd 252).

## Check of revision 4, 2026-10-25

Reviewer: a fresh agent on the Pi, checking revision 4 in Andy's place under station law section 3. I took no part in
writing any revision of the spec, any review, any response, or the interface pass. I read the vision's principles and
its imprint section, the final check and the response to it above, `git diff HEAD` of the spec, the spec's sections 4,
5.2, 6.2, 8, 10, 12, 13, 14, 15 and 16 as they stand, the interface table, and T (revision 6): section 4, section 7
("The imprint check", "What an imprint changes", "The cost, chosen for privacy", steps 8.2 and 10), section 11 and
section 12's imprint tests. I checked every new code claim by reading the code today, and the systemd claims on the Pi.
File:line references are relative to `/home/andy/superyak/.worktrees/trail-arrows/`. "Spec line" means a line of
`engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md` as it stands today. I edited no spec. I appended
only this section. I committed, pushed and posted nothing.

VERDICT: APPROVE

FS1, FS2 and FS3 are resolved, apart from one more gap in FS2's test (CS1). I2, I3 and I6 are provided as T states
them. The file is whole. Revision 4 lets nothing more leave a machine and widens no permission. I found no wrong claim
about code and no broken interface. Two should-fix items (CS1, CS2) and eight nits remain. Every fix named below is Rio
Grande's call.

### 1. FS1 to FS3

**FS1: resolved, option (a).**

- `calibrate` gains `no_paths`, and admission always passes it (spec lines 1260-1261, 1275-1283). The premise holds.
  Calibration runs `paths.report` (`engram/calibrate.py:295-296`). Its report names each session
  (`"session": p.key`, `engram/paths.py:447`) and pairs of sessions (`"a"`, `"b"`, `:329`), and report.md prints the
  pairs (`engram/calibrate.py:386-392`).
- No other analysis reads session ids or log rows. A grep for `session_id`, `memory_log` and `operation_log` in
  `engram/calibrate.py`, `persistence.py`, `sheaf.py` and `store_identity.py` finds only sheaf's sleep-pass rate limit
  (`engram/sheaf.py:287-291`) and sheaf's own writes (`:368`, `:387`). Calibration runs neither.
- r_T now says its one purpose is `trail-evaluation` (spec lines 845-846). `Need(admission)` says what admission does
  (spec lines 987-993). D7, D16, 5.2, section 12's table and the `station-imprints` example agree (spec lines 186, 195,
  322-330, 1419, 1309-1316).
- The test FS1 asked for is there (spec lines 1925-1927).
- The survey still counts distinct session ids (`engram/store_reader.py:128-130`). That is no use on a trail. In P,
  `recall` returns ids and digests, and `read` returns content (P lines 556-557). A count returns neither. report.md
  already printed it in revision 3 (`engram/calibrate.py:329-331`), so the station sees nothing new. See CN3 for the
  wording.

**FS2: resolved in 5.2 and section 10. The test still has a gap (CS1).**

- 5.2 now says calibration reads no log row's content, but counts the log tables' rows (spec lines 322-326;
  `engram/store_reader.py:111-121`).
- `calibrate` gains `notes`. Without `route`, the note sits beside the session count and the log row counts (spec lines
  1288-1291).
- The test (spec lines 1780-1789) now leaves out `paths`, the session count, the log row counts, `source` and
  `identity`. That is the fix FS2 named. But the survey holds two more keys that differ, and one analysis reads the
  clock. See CS1.

**FS3: resolved. I2, I3 and I6, as T states them (T lines 1382-1446).**

- **I2** (D41, spec line 220; spec lines 1436-1478, 1532, 1540-1541, 1713-1714, 1928-1937). Each part T asks is there:
  - `withdrawn` only with the tombstone, `ended`, `allow changed` and `not evaluable: limit` are rules 2, 3, 5 and 6;
  - the sync deletes the allow file, then writes `use-finished` once;
  - `report.json` and `result.json` are the names T's check 5 reads (T lines 899-902);
  - a lowercase uuid4 fits T's check 2 (T line 888);
  - the use always passes `--lane`.

  The two additions, `deleted` and `failed`, only name cases T's list leaves out. A station deletion writes a
  tombstone but no `withdrawn` receipt (spec lines 1543-1557), so rule 4 keeps it from reading as a withdrawal. T's own
  I2 test (T lines 1625-1628) passes on these rules. Moving `station-imprint-use-begin` inside the unit is sound: each
  start is decided again and leaves its own `use-started`, the use id never reaches the caller's shell history, and one
  unit per imprint only narrows. See CS2 for one gap in `failed`.
- **I3** (D29, spec line 208; spec lines 1479-1495, 1938-1940, 2007-2015).
  - systemd-run(1) on the Pi (systemd 252.39) says the unit runs "in a clean and detached execution environment".
  - `scripts/runtime.py:84-89` is the `embedder_socket` rule, `:597` the default path, and `:653-655` sets the
    variable. `:56-89` also requires `memory_home` and `default_instance`, as the response says.
  - `engram/embeddings.py:12` is `~/.kairos/models/fastembed`. `:191-194` raises `EmbedderUnavailableError` when the
    socket doesn't answer, and `create_embedding_provider` has no fallback (`:200-207`).
  - The Pi has no `~/.config/superyak/runtime.json` today, so the use would pass nothing and take the in-process path.
    The model is in the station user's cache (`~/.kairos/models/fastembed/models--nomic-ai--nomic-embed-text-v1.5`).
  - The text still goes only to an embedder on the Pi, which section 8 already names (spec lines 994-997).
- **I6** (spec lines 1800-1812). The two assertions are T's (T lines 1442-1444), and so is the pointer to T 12's
  synthetic-imprint test (T line 1594). The added "one `as_of`" is right: T's CLI defaults `as_of` to each file's
  newest timestamp (T line 199). With one `as_of`, both assertions hold as T derives touches:
  - episodes ship whole apart from `session_id` (spec lines 594-597);
  - a kept recall row loses only instinct ids (spec lines 577-581);
  - outcome normalization keeps "starts with `used`" (spec lines 584-585; T line 215);
  - a `route_shown` row is a cut of its source row (spec lines 587-589).

### 2. Privacy and permissions

Nothing more leaves a machine.

- FS1 narrows what is read at the station. FS2 adds fixed sentences and changes a test. I6 changes a test.
- I2 adds a random use id, an end code, a deletion reason and an exit status to receipts. None names anything in the
  store, and receipts already go to the owner.
- I3 passes a local socket path to a unit on the same Pi.

No permission widens. Retiring the allow file, refusing a used use directory, one use per imprint, and refusing a
two-lane scope without `LANE` only narrow. The decision rule (spec lines 972-1004) and C are unchanged.

### 3. Must-fix

None.

### 4. Should-fix

**CS1. The calibration test in "Log rows" still fails as written** (spec lines 1780-1789; the class of FS2).

- The survey section is `report["snapshot"] = store_reader.survey(snap)` (`engram/calibrate.py:258`). `survey` returns
  `{"file": facts, **body}` (`engram/store_reader.py:156-174`). `file` is the snapshot's path, bytes and SHA-256
  (`:66-73`), and the body holds `identity`, from `store_identity.describe(conn)` (`:124`). Both differ between two
  packages whose bytes and imprint ids differ. The path also sits under each imprint's own state directory.
- `first_open` reads the wall clock unless `now` is passed (`engram/calibrate.py:89`, `:245`, `:286`). Admission
  passes none (spec lines 1260-1261), so two runs at different times give different decay strengths.

*Fix:* also leave out the survey's `file` and `identity`, and run both calibrations with one fixed `now`, as I6 uses
one `as_of`.

**CS2. A run with no `result.json` is always `not evaluable: limit`, so `failed` never names a crash of
`imprint.py use` itself** (spec lines 220, 1472-1474).

- D41 says `failed` is "for any other run with no report", and the response above says a crash is `failed`. But rule
  6 comes first and takes every run with no `result.json`. So `imprint.py use` raising before it writes `result.json`,
  or a manual `systemctl --user stop`, is recorded as a limit. Only a `trails.py` exit other than 0 and 3 reaches rule
  7.
- Nothing leaves, and no permission changes. But the receipt says the Pi ran out of room when it may be a bug. That is
  the kind of mis-record D41 was added to prevent.

*Fix, one of:* `imprint.py use` writes `result.json` for its own errors too (`exit` null, plus an error class), in a
`finally`, so a missing file means only that the unit was stopped. Or D41 says that `not evaluable: limit` also covers
a run stopped from outside, or one whose runner crashed.

### 5. Nits

- **CN1. "At the latest" and "by then the run is over."** The constants row (spec line 1714) says a use is finished
  1,800 s after `use-started` "at the latest". But only the unit's own sync and the hourly sweep run the sync (spec
  lines 1480, 1564-1570). A use whose unit was stopped is finished at the first sweep after 1,800 s, up to an hour
  later. Also, at `RuntimeMaxSec` systemd sends SIGTERM and waits `TimeoutStopSec` before SIGKILL (systemd.service(5)
  on the Pi). This user manager's default is 90 s (`systemctl --user show -p DefaultTimeoutStopUSec`). Say "at the
  first sync after 1,800 s", and pass `-p TimeoutStopSec=` or wait 1,800 s plus it (spec lines 1454-1458). The window
  is still narrower than revision 3's, which never retired an allow file.
- **CN2. The socket rule's edges** (spec lines 208, 1490-1494, 1938-1940). runtime.py treats `"embedder_socket": null`
  as absent (`scripts/runtime.py:85-86`), but the test says a non-string stops the use. "By the same rule", null
  passes nothing. `superyak-runtime` also lets `SUPERYAK_RUNTIME_CONFIG` replace the default path (`:595-597`). Say
  that the Makefile reads only the default. D29's "only through `--setenv`" is a little strong: a user unit also
  inherits the user manager's environment. Today that holds no `ENGRAM_` variable (`systemctl --user
  show-environment`, checked). A deploy gate could check it.
- **CN3. "Counts over columns of the memories"** (spec line 1286; row 13's note). That fits the session count, not
  the log tables' row counts, which count R(I)'s rows. A reason that fits both: the log row counts are already in the
  request's `contents` (spec lines 733-743), and a count returns no id, digest or content, so under P 6.4 it is no use.
- **CN4. Who fills in `LANE`.** The unit's command line carries `LANE=<lane>` (spec line 1486), so the Makefile fills
  it in before the unit starts, and the test names `make station-imprint-use` (spec lines 1935-1937). Row 27's note
  says `imprint.py use` does it. Name one.
- **CN5. What the caller sees.** The use is now decided inside the unit, so `make station-imprint-use` can't show a
  refusal. Print "Started; see make station-imprints", as admission does (spec line 1168). Say what a second start
  prints while one runs, since systemd-run refuses a unit name that is already loaded.
- **CN6. Write order.** `imprint.py use` should write `report.json`, atomically, before `result.json`. The sync starts
  on `result.json` (spec line 1455), and the sweep's sync can run beside the unit. In the other order, a sync between
  the two writes records an exit of 0 as `failed`.
- **CN7. Tests.** "Use ends" (spec lines 1928-1937) tests every end but `failed`. Nothing tests that no use is
  finished while the imprint is `deleting` (spec lines 1457-1458).
- **CN8. Not new, now cheap.** Withdrawal and a station delete don't stop a running use's unit (spec lines
  1547-1557). `trails.py` keeps working on the unlinked file until its deadline, then discards its report (T lines
  905-911). The unit is now named by the full imprint id, so a withdrawal could stop `superyak-imprint-use-<imprint
  id>`, and admission's unit too. That only narrows.

### 6. The interface table

Rows 13, 14, 24, 27 and 28 match the spec. Rows 14, 24, 27 and 28 are rightly marked agreed. The header line and
"What changed, by spec" are right. Row 13's "Agreed rule" still opens "Calibration reads no log row", where the spec
now says "no log row's content" (see CN3). Two points for T's next pass, which are not defects in I:

- T's section 11 still calls I2's and I3's new parts, and I6, pending in I (T lines 1388-1389, 1407-1408, 1446).
- T 7 (T lines 932-933) and T 11's I5 (T lines 1434-1435) still describe calibration's paths at admission:
  "`paths.report` finds no session", the "31 session paths" example, and "differs only in `paths`". T reads nothing
  from that section, so no rule of T's changes.

### 7. The file is complete

All 32 headings of the committed revision 3 are present, in order (a `diff` of `grep '^#'` against `git show HEAD:`).
The diff adds 169 lines and removes 47, and every hunk is an edit the response names. The file ends with a newline, and
section 20 ends where it did.

### 8. Still open with Andy (this check changes none of them)

- **Memories that mention other people.** The default is unchanged and stays the strictest of the three specs: no
  memory with a recorded co-subject leaves, and the owner ticks the check for the rest (D27; 6.4, item 5; section 20).
  I decide nothing here.
- Which store to imprint first, and its owner's yes. Whether the station-signed browser yes is enough for step 1. The
  license. One permission an agent may set on its own. What the county sets.
