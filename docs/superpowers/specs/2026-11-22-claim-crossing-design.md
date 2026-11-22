# Claims that cross with their sources' identity (north-star test 5, Rio Grande's half)

Revision 2, 2026-11-22. Rio Grande (the Pi). Board item `north:5-two-lighthouses-keep-source-identity`. Under station
law section 3, a fresh reviewer approves it in Andy's place, and Andy can veto. Revision 1 (e3fc031f) was read by a
fresh reviewer on the Pi, who asked for a revision (all hands 1d808ee0). This revision answers its ten findings,
named F1 to F10 below.

## Why

Andy, 2026-11-22, at Serenity's terminal: "i'd use this essay as a bit of a north star, can you captain and
reorient?" Test 5 of [docs/north-star.md](../../north-star.md) asks two lighthouses, the Pi's and Tardis's, to exchange
evidence while keeping each source's identity. Copied evidence must be told from independent confirmation, a
correction in one must reach what the other built on it, and their accounts are compared without forcing agreement.
Today the crossing carries recall and read of memories only. No claim crosses.

## The split, agreed (all hands 983200e5, 76c735c8, daf52d30, 1102371c)

- **This spec (Rio Grande):** the source identity key, what a publication carries, retraction and correction notices,
  how a notice is applied, how accounts are compared, and the planted stores with known answers.
- **Tardis (T1):** the receiver's rule, a pure function of two claims' roots and chains, written test-first on these
  planted stores. Also a second Lighthouse, so evidence travels both ways.
- **Tardis with Serenity (test 6):** the sheaf and n-category machinery against this plain rule, on the same data.

## What exists, and what this builds on (F8)

- **Lighthouse 0.1** (`lighthouse/packages/protocol/src/schemas.ts`, and in Python `atlas/workbench/lighthouse_wire.py`):
  a `Snapshot` (`profile`, `signature`, `context`, `model`, `lineage`) and a `Claim` (`profile`, `signature`,
  `context`, `sentenceMediaType`, `sentence`, `snapshotDigests`, `provenance`). `profile` and `signature` are
  `{"id": <URI>, "version": <text>}`. `context` is `{id, path}`. Every digest reference is
  `{"algorithm": "sha-256", "value": <64 hex>}`. An artifact's `issuer` and `id` are URIs, and Python's `verify`
  enforces it. The Python validator is the stricter one, so every fixture must pass it (F5).
- **Atlas's projection** (`atlas/workbench/lighthouse.py`): `publish` seals one Snapshot whose `model` holds the
  selected items, the relations among them and the sources their evidence names. It seals one Claim per item, whose
  `snapshotDigests` names that Snapshot, plus a ConnectionPolicy and a descriptor. `overlap` authorizes `read` and
  `link_overlap` against the receiver's policy, then compares same-origin records side by side. Across origins it
  says "Different declared collection origins require an explicit correspondence."
- **This spec sits beside that projection, not in place of it.** It adds a profile,
  `{"id": "urn:superyak:profile:atlas-sourced", "version": "1"}`, that is the same publication plus three things:
  1. a source key on every source, the correspondence across origins;
  2. Claim `provenance` for copies;
  3. source notices.

  Profile `urn:lighthouse:profile:atlas-research` 0.1.0 is unchanged. Every authorization goes through
  `lighthouse_wire.authorize` and the receiver's ConnectionPolicy, as `overlap` does, with this profile and its two
  media types (F9).
- **Atlas** (`validation.py`): a source has `id`, `title`, `url` (required, http or https), `year` and `citation`,
  with no revision field. `store.retraction_impact(source_ids)` is read-only and takes local source ids. Audit history
  is written only by `set_status`, on items and relations.

## A source's keys (F1, F2, F6)

Every source gets up to three keys, from one function, `source_key(record)` (version `source_key/1`, pinned by the
profile version):

1. **The DOI key, `doi:<doi>`, strong.**
   - **Where it's read:** the url first, when its host is `doi.org`, `dx.doi.org` or `www.doi.org`, over http or https.
     Then the citation.
   - **Extraction:** percent-decode first, then take the first match of `10\.\d{4,9}/[-._;()/:A-Za-z0-9]+`, case
     insensitive.
   - **Trailing characters:** remove `.`, `,`, `;` and `:`, and a closing `)` or `]` that has no opening partner inside
     the match. Lowercase the result.
   - **Edge cases:** a doi.org url's query and fragment are not part of the DOI. If the url gives a DOI, the citation
     is not read. If the citation holds more than one distinct DOI and the url gives none, there is no DOI key.
2. **The url key, `url:<url>`, strong.**
   - **When:** the url isn't a doi.org link.
   - **Normalising:** the scheme becomes `https`, so http and https fold. The host is lowercased with a leading `www.`
     removed, a default port is removed, and the fragment and one trailing slash are removed.
   - **The query stays as it is.** A tracking query can split one page into two url keys, but the title key below
     catches that. Dropping the query could merge two different pages, which the title key can't undo.
3. **The title key, `title:<title>:<year>`, weak.** It's computed for **every** source, alongside its strong key, with
   `store._normalized_title`: NFKC, casefold, and punctuation and symbols made spaces. A title that normalises to
   nothing gives no title key.

Since Atlas requires a url, every Atlas source has exactly one strong key, a DOI or a url, and a title key unless its
title is all punctuation.

**Two sources match** when any one of these holds:

- their strong keys are equal;
- or their title keys are equal, and they are not two different DOIs.

A DOI is authoritative, so two different DOIs never match by title. A url key against a DOI key, or two different
urls, still match by title. That is how the same paper under a publisher url and a DOI, or http and https, or an
abstract and its PDF with one title, is caught.

**A strong key proves sameness, not difference** (F1). Two sources are **distinct** only when they don't match. That
means their strong keys differ, and either their title keys differ or they are two different DOIs.

The receiver recomputes `source_key(record)` from each source's record. It refuses a publication whose keys don't
match, so no sender can label a url key a DOI.

## What a publication carries (F5)

The Snapshot and Claims are made by `publish`, with these differences:

- **The Snapshot's `model`** is `publish`'s model. Each source carries a `keys` object, for example
  `{"strong": "doi:10.5555/superyak-fixture-a1", "title": "title:a study of x:2024", "fn": "source_key/1"}`.
  `title` is `null` when there's none.
- **What leaves the model:**
  - an item's own `provenance` map, which holds sessions and paths;
  - `reviewed_by` and `reviewed_at`, which can hold a person's name, are replaced by `null` (F9).

  Both are left out of the content digest, the same in each publication. Each evidence entry (`source_id`, `locator`,
  `note`) stays.
- **`lineage`** names the issuer's previous Snapshot of the same collection, when there is one.
- **`signature`** is `{"id": "urn:superyak:atlas-sourced", "version": "1"}`.
- **`context`** is the publishing collection's, as `publish` already takes it.
- **Each Claim** keeps `publish`'s sentence (`origin`, `record_id`, `content_digest`), with
  `sentenceMediaType` `application/vnd.superyak.atlas-sourced-claim+json`.
  - **`snapshotDigests`** names the Snapshot that holds the record and its sources, as the protocol means it: the
    claim's source snapshot.
  - **`provenance`** names the digest of each Claim that this record was **copied** from. A copy is the same record,
    taken from another publication and kept in this store, with a note of where it came from.
  - **A derived record is not a copy.** That's a record that cites or builds on another. Derivation is an Atlas
    relation (`supports`, `informs` and so on). It isn't in `provenance`, and roots don't follow it (F3).

A claim's **roots** are the sources its record's evidence names, in its own Snapshot. A copied claim adds the roots
of each Claim in its `provenance`, transitively. Its **chain** is the set of Claim digests its `provenance` reaches,
transitively. Both come from the artifacts alone. Any `provenance` digest that the receiver can't resolve to an
artifact it holds is **unresolved**.

## The answers, in order (F3)

For a pair of claims, A from one store and B from the other, the first rule that holds gives the answer:

1. **copied:** A and B have the same digest; or one's digest is in the other's chain; or their chains share a digest.
   The last of these is sibling copies of one claim. The answer names the linking digest.
2. **unknown:** either claim has no roots, or either has an unresolved `provenance` digest.
3. **same sources:** every root of A matches a root of B, and every root of B matches a root of A.
4. **overlapping:** at least one root of A matches a root of B.
5. **independent:** every root of A is distinct from every root of B, and every root on both sides has a strong key.
6. **unknown:** anything else. In Atlas this can't happen, since every source has a strong key. The rule keeps it
   for other sources.

The rule is Tardis's to write (T1). These are the answers it must give. It's a pure function, `relation(a, b)`, of
two Claims, the Snapshots they name and the Claims their chains reach.

## Source notices, and how they are applied (F4, F6)

A notice is a Claim with profile `urn:superyak:profile:atlas-sourced` 1, `sentenceMediaType`
`application/vnd.superyak.source-notice+json`, `snapshotDigests` naming the Snapshot that holds the source, and an
empty `provenance`.

- **A retraction** targets the source's identity:
  `{"notice": "retraction", "source": {"strong": ..., "title": ...}, "reason": "..."}`.
- **A correction** targets one revision. Atlas sources have no revision number, and a number would mean something only
  to its issuer. So a correction names Snapshots:
  `{"notice": "correction", "source": {"strong": ..., "title": ...}, "corrected": <digest of the Snapshot holding the
  old record>, "corrected_by": <digest of the Snapshot holding the new one>, "reason": "..."}`.
  When the correction changes the DOI or the url, the new Snapshot's keys carry the new strong key. A later retraction
  by either key reaches both.

**Applying a notice is a report, not a write.** Neither side's account is changed to match the other. The receiver:

1. **Finds its matching local sources.** It runs `source_key` over every source in its own store and collects every
   local id that matches the notice's source by the rule above. Duplicates within a store are all collected.
2. **Finds the claims its chains reach.** It adds every local claim whose chain reaches a Claim whose Snapshot holds a
   matching source. That catches a copy whose own local source was keyed another way.
3. **For a retraction,** calls `retraction_impact(those ids)` when there is at least one id. Its output is the report:
   every item and relation it reaches, with `retraction_impact`'s own verdicts (unsupported, challenge lost, still
   supported, not grounded before either). It follows `supports` and `challenges`, which is intended: a belief built
   on a retracted source is reported even when it isn't a root. No match means the report is "no impact", not an
   error.
4. **For a correction,** the report names each local claim whose `snapshotDigests`, or a claim in its chain, names the
   `corrected` Snapshot. Each is "built on the corrected record". A claim on `corrected_by` or later is "on the
   corrected record". Atlas can't tell revisions apart, so this comes from the artifacts.
5. **Changes nothing.** Any status change is the receiving owner's own act, through `set_status`, with the owner as
   actor and the notice's digest in the reason. That is what writes the earlier belief into the audit history.

A notice is accepted only through `authorize`, against the receiver's ConnectionPolicy, for that publisher and the
notice's media type (F9). `verify` checks only a digest, and an issuer names itself, so on a real crossing who sent a
notice must come from the transport's own authentication (follow-up, below), never from the artifact alone.

## Accounts compared, not forced to agree (F10)

North-star test 5 asks that the two accounts be compared. For every pair with answer copied, same sources or
overlapping, the receiver reports both records side by side, as `overlap` already does for same-origin records: each
publisher's record, its sources and the relations that touch it. Its source keys now serve as the correspondence that
`overlap` asked for across origins. Whether the two records agree is not decided by this spec. It shows them, and
`retraction_impact`'s verdicts show what a notice would do on each side.

## The planted stores (F7)

`atlas/tests/fixtures/claim_crossing/` holds sealed publications and an answer file, all fixed in one commit before
any run:

- **The publications:** `pi.json`, `tardis.json` and `third.json`. Each is `publish`'s full output under the new
  profile, with a fixed `issued_at` so every digest reproduces. The issuers are `urn:superyak:fixture:pi`,
  `urn:superyak:fixture:tardis` and `urn:superyak:fixture:third`.
- **Local ids:** each store's sources have their own local ids (`pi-S1`, `t-S1`), so nothing is imported over another
  store's id.
- **Notices:** `notices.json`.
- **Answers:** `expected.json` lists, for each pair, the expected answer and the linking digest when there is one, and
  for each notice the exact output of steps 1 to 4 above. Counts are per case, not one total.

**DOIs:** under `10.5555/superyak-fixture-...`. 10.5555 is a test prefix used in Crossref's examples, but not formally
reserved, so the suffixes are plainly synthetic, and fixtures never resolve a DOI (F9).

**Items:** the records are fictional research items with `proposed` or `source_reported` status, so no fixture
carries a reviewer's name.

**Cases, each with at least two pairs:**

- **Copied:** copied; copied twice through `third`; sibling copies of one `third` claim; an identical digest held on
  both sides; and a copy of a claim with no evidence, which is copied, since rule 1 comes before rule 2.
- **Unknown:** both root sets empty; one empty against one not; an unresolved `provenance` digest.
- **Same sources:** one DOI written as `https://doi.org/10.5555/superyak-fixture-a1`, as
  `http://dx.doi.org/10.5555/SUPERYAK-FIXTURE-A1` and as `doi: 10.5555/superyak-fixture-a1.` in a citation.
- **Percent-encoded and bracketed DOIs:** one with `%3C`, and one followed by `)` in a citation, both giving same
  sources.
- **Drift:** one DOI, with the title punctuated and cased differently on each side, gives same sources.
- **Not independent across key forms:**
  - a publisher url against a DOI, same title and year;
  - http against https;
  - `www.` against none.

  All give same sources, never independent.
- **Overlapping:** one source shared, by key or by title, and one source each.
- **Independent:**
  - two different DOIs with the same generic title ("editorial", 2024);
  - disjoint DOIs;
  - disjoint urls with different titles.
- **Notices:**
  - a retraction by DOI that reaches the other side's copy held under a url key, by title, and through its chain;
  - a retraction reached through a copied chain;
  - a retraction with no match, which reports "no impact";
  - a correction whose new record changes the DOI, then a retraction by the new DOI.

## Measure

Fixed in the fixtures' commit, before the run (goals R1 and T1):

1. **On the planted stores,** `relation` gives every pair its expected answer and linking digest.
2. **The notices' reports** equal `expected.json`'s, item for item.
3. **Real crossings,** once Tardis's Lighthouse stands and the transport exists.
   - **What's reported:** for the pairs defined below, the count of each answer, every "unknown" listed with its
     reason, and every same sources or overlapping pair shown side by side. Never a score.
   - **Which pairs:** each claim on one side paired with each claim on the other whose roots share a match or whose
     chain links to it.

A failure is a result, written in `docs/north-star.md`'s row 5.

## What this spec does not do

- **The transport.** Today's crossing frames carry memories. Carrying publications and notices between the Pi and
  Tardis is a follow-up spec, after the rule passes on fixtures. That spec owns who sent what: a notice's sender must
  come from the crossing's authenticated peer, never from the artifact's self-named issuer.
- **Permissions.** Atlas evidence is research data, but anything that crosses machines for real does so under each
  owner's permissions ledger. A real crossing waits on an allow its owner signs, for the Pi and Tardis, Andy's. A
  record's reviewer name never crosses (above).
- **Agreement.** Neither side's account is changed. The rule reports the relation, the comparison shows both, and
  each store keeps its own belief and history.
- **Lighthouse's "issuer chain".** There isn't one: each artifact has one issuer. "Chain" here means only the
  `provenance` digests between Claims.
