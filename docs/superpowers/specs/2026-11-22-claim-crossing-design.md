# Claims that cross with their sources' identity (north-star test 5, Rio Grande's half)

Revision 3, 2026-11-22. Rio Grande (the Pi). Board item `north:5-two-lighthouses-keep-source-identity`. Under station
law section 3, a fresh reviewer approves it in Andy's place, and Andy can veto.

- **Revision 1 (e3fc031f)** went to a fresh reviewer, who asked for a revision with ten findings (all hands 1d808ee0).
- **Revision 2 (9044070d)** answered those, F1 to F10. Its re-check approved it with six required changes and six
  advisory ones (bbf3c93b).
- **This revision** makes all twelve, named C1 to C12 below.

## Why

Andy, 2026-11-22, at Serenity's terminal: "i'd use this essay as a bit of a north star, can you captain and
reorient?" Test 5 of [docs/north-star.md](../../north-star.md) asks two lighthouses, the Pi's and Tardis's, to exchange
evidence while keeping each source's identity. Copied evidence must be told from independent confirmation, a
correction in one must reach what the other built on it, and their accounts are compared without forcing agreement.
Today the crossing carries recall and read of memories only. No claim crosses.

## The split, agreed (all hands 983200e5, 76c735c8, daf52d30, 1102371c)

- **This spec (Rio Grande):** the source keys, the sourced publication, notices and how they're applied, the
  comparison, and the planted stores with known answers.
- **Tardis (T1):** the receiver's rule `relation(a, b)`, written test-first on these planted stores, and a second
  Lighthouse, so evidence travels both ways.
- **Tardis with Serenity (test 6):** the sheaf and n-category machinery against this plain rule, on the same data.

## What exists, and what this builds beside

- **Lighthouse 0.1.** The TypeScript is `lighthouse/packages/protocol/src/schemas.ts`; the stricter Python is
  `atlas/workbench/lighthouse_wire.py`, and every fixture must pass it.
  - A `Snapshot` has `profile`, `signature`, `context`, `model` and `lineage`.
  - A `Claim` has `profile`, `signature`, `context`, `sentenceMediaType`, `sentence`, `snapshotDigests` and
    `provenance`.
  - `profile` and `signature` are `{"id": <URI>, "version": <text>}`, `context` is `{id, path}`, and a digest
    reference is `{"algorithm": "sha-256", "value": <64 hex>}`. Issuers and artifact ids are URIs.
  - Trust is local, deny-by-default and non-transitive. `read`, `derive`, `retain` and `reshare` are independent
    actions (the protocol plan's principles).
- **Atlas's projection** (`atlas/workbench/lighthouse.py`):
  - `publish` seals one Snapshot per publication, holding the selected items, their relations and their sources, and
    one Claim per item naming that Snapshot.
  - `overlap` authorizes, then compares same-origin records side by side, and says "Different declared collection
    origins require an explicit correspondence." across origins.
  - Its validator and `overlap` hard-check their profile, and `publish` hard-codes its profile, signature, sentence
    type and an empty `provenance`.
- **The new code lives in its own module** (C3). That's `atlas/workbench/sourced.py`, with its own `publish_sourced`,
  `validate_sourced`, `relation` (Tardis's) and `compare_sourced`, all built on `lighthouse_wire`'s `seal`, `verify`
  and `authorize`. It uses profile `{"id": "urn:superyak:profile:atlas-sourced", "version": "1"}` and signature
  `{"id": "urn:superyak:atlas-sourced", "version": "1"}`. `lighthouse.py` and its profile are unchanged.
- **Atlas's records** (`validation.py`):
  - a source has `id`, `title`, `url` (required, http or https), `year` and `citation`, and no revision;
  - `store.retraction_impact(source_ids)` is read-only, takes local source ids and reports items, with relations
    inside each item's `path`;
  - only `set_status` writes the audit history.

## A source's keys (C5, C6, C8)

One function, `source_key(record)`, version `source_key/1`, pinned by the profile version, gives each source:

- **A url key, `url:<url>`, strong, always,** since Atlas requires a url. The scheme becomes `https`. The host is
  lowercased with a leading `www.` removed, a default port is removed, and the fragment and one trailing slash are
  removed. The query is kept, since the title key catches a tracking query that splits one page into two keys.
- **A DOI key, `doi:<doi>`, strong, when one is found:**
  - **From a doi.org url** (host `doi.org`, `dx.doi.org` or `www.doi.org`, over http or https): the whole path after
    the host, with its leading `/` removed, percent-decoded and lowercased. Its query and fragment are not part of it.
    The path is taken whole, never through the regex, so `%3C` and `%3E`, `<` and `>`, stay in it (C5).
  - **From the citation,** only when the url gave none: the first match of `10\.\d{4,9}/[-._;()/:A-Za-z0-9]+`, case
    insensitive, after percent-decoding.
    - **Stripping:** remove trailing `.`, `,`, `;` and `:`, and a closing `)` or `]` with no opening partner in the
      match. Do it repeatedly until none is left, so `doi:10.5555/x.)` gives `10.5555/x`.
    - **Then lowercase it.**
    - **More than one distinct DOI** in the citation gives no DOI key.
- **A title key, `title:<title>:<year>`, weak,** from `store._normalized_title`: NFKC, casefold, and punctuation and
  symbols turned to spaces. A title that normalises to nothing gives **no title key**, and a missing title key never
  equals anything (C8).

**Comparing two sources gives one of three results:**

- **Match:** any of one source's strong keys equals any of the other's. Or their title keys are equal and they are not
  two different DOIs.
- **Unclear:** both have DOI keys and the DOIs differ, but their title keys are equal. A preprint and its journal
  version look like this, and so do two editorials of one year (C7).
- **Distinct:** anything else. No strong key is shared, and the title keys differ, or one is missing.

A strong key proves sameness, never difference. The receiver recomputes every key from the record, and refuses a
publication whose keys don't match its own computation.

**Accepted cost (C12):** a generic title, such as "Editorial" 2024, matches across a url key and a DOI key. It merges
two different works, so the answers err towards not-independent, and retraction reports can over-reach. The report
names how each source matched ("by url", "by DOI", "by title"), so a person can see it.

## The sourced publication (C3, C4)

`publish_sourced` makes what `publish` makes, under the new profile, with these differences:

- **Each source in the Snapshot's model carries `keys`:**
  `{"url": ..., "doi": ... or null, "title": ... or null, "fn": "source_key/1"}`.
  `validate_sourced` accepts the field. When a receiver keeps a copy in its own Atlas store, `keys` is dropped before
  `normalize_source`.
- **What leaves each item, before sealing:**
  - its own `provenance` map, which holds session ids and paths;
  - `reviewed_by`, which becomes `""` on proposed, source_reported and withdrawn records;
  - `reviewed_at`, which becomes `""` too.

  A `reviewed` record crosses with `reviewed_by` set to the publishing issuer's URI, which names a lighthouse, not a
  person, and its `reviewed_at` kept. Both pass `normalize_item`. So no person's name crosses (C3).
- **`lineage`** names the issuer's previous sourced Snapshot of the same collection, if there is one.
- **Each Claim:**
  - its sentence is `{"origin", "record_id", "content_digest"}`, as `publish`'s is;
  - its `sentenceMediaType` is `application/vnd.superyak.atlas-sourced-claim+json`;
  - `snapshotDigests` names its Snapshot;
  - `provenance` names the digest of each Claim this record was copied from.
- **A copy** is a record taken from another publication and kept in this store, with its provenance link. The link is
  its identity as a copy. Its status, and any later edit, are not. A difference between a copy and its original is
  what the comparison shows.
- **A derived record is not a copy:** one that cites or builds on another is an Atlas relation, and roots don't follow
  relations.
- **A carried Claim** is a foreign Claim, kept exactly as its issuer sealed it, with the foreign Snapshot it names
  (C4). A publication can list them under `carried`, so a store can hold the other side's claim itself, with the same
  digest.

**A claim's roots** are the sources its record's evidence names in its own Snapshot. To these it adds the roots of each
Claim in its `provenance`, transitively.

**Its chain** is the set of Claim digests its `provenance` reaches, transitively, counting a digest whether or not
the receiver can resolve it. Digests are content addresses, so two claims naming one digest name one thing (C9). A
digest the receiver can't resolve to an artifact it holds is **unresolved**.

## The answers, in order

For a pair of claims, A from one store and B from the other, the first rule that holds gives the answer:

1. **copied:** A and B have the same digest, or one's digest is in the other's chain, or their chains share a digest,
   resolved or not. The last is sibling copies. The answer names the linking digest.
2. **unknown:** either has no roots, or either has an unresolved digest in its chain.
3. **same sources:** every root of A matches a root of B, and every root of B matches a root of A.
4. **overlapping:** at least one root of A matches a root of B.
5. **independent:** every root of A is distinct from every root of B. Here **distinct** means distinct, not unclear.
6. **unknown:** anything else. That's when some pair of roots is unclear (C7).

**Stated limit (C10):** the answer reads the two claims' own provenance only. If Tardis's B is supported, through a
relation in Tardis's store, by Tardis's copy of the Pi's A, and B cites its own source, then (A, B) is independent.
B's own evidence is independent of A's, even though B leans on a copy of A. Notice reports do follow `supports`, so
a retraction under A still reaches B. A planted case pins this.

## Notices, and how they're applied (C2)

A notice is a Claim under the new profile, with `sentenceMediaType` `application/vnd.superyak.source-notice+json`,
`snapshotDigests` naming the Snapshot or Snapshots it refers to, and an empty `provenance`.

- **A retraction:**
  `{"notice": "retraction", "record_id": <the source's id in the named Snapshot>, "keys": <its keys>, "reason": "..."}`.
- **A correction:**
  `{"notice": "correction", "old": {"snapshot": <digest>, "record_id": ..., "keys": ...}, "new": {"snapshot": <digest>,
  "record_id": ..., "keys": ...}, "reason": "..."}`.
  It carries both key sets and the record's id in both Snapshots, so a change of DOI or url is explicit.

**Applying a notice is a report, never a write.** The receiver:

1. **Gathers the sources it means:** the notice's source, plus every source joined to it by a correction notice the
   receiver holds, through `old` and `new`, transitively. So a retraction by a new DOI reaches records keyed by the
   old one.
2. **Matches its own sources:** it computes `source_key` over every source in its own store, and collects every local
   id that matches any gathered source. Duplicates within a store are all collected, and each is named with how it
   matched.
3. **Lists its claims reached through a chain:** every local claim whose roots, followed through its chain, include
   a gathered source. These are listed with the verdict "reached through its chain", separate from step 4's output.
   A copy whose own local source is keyed another way is caught here.
4. **For a retraction,** calls `retraction_impact(step 2's ids)`, when there is at least one. Its items, each with its
   verdict and `path`, are the report's main part. It follows `supports` and `challenges`, so a belief built on a
   retracted source is reported even when it isn't a root. With no ids and nothing from step 3, the report is "no
   impact".
5. **For a correction,** reports every local claim whose roots, followed through its chain, include `old`'s record.
   Each is "built on the corrected record". Atlas can't tell revisions apart, so this comes from the artifacts.
6. **Changes nothing.** A status change is the receiving owner's own act, through `set_status`, with the owner as
   actor and the notice's digest in the reason. That act writes the earlier belief into the audit history.

## Authorization (C11)

Every step goes through `lighthouse_wire.authorize` and the receiver's ConnectionPolicy, for the publisher, this
profile and the media type:

| Action | What it allows |
| --- | --- |
| `read` | read a publication or a notice |
| `link_overlap` | compute answers and comparisons against the receiver's own claims |
| `retain` | keep a copy, or a carried Claim, in the receiver's store |
| `reshare` | publish a copy onward |

A notice needs `read` for its media type. Acting on it is the owner's act, above. Consent isn't transitive: "copied
twice through `third`" needs `third` to allow the first store `reshare`, and the first store to allow the second
store `read`. The fixtures' policies grant exactly the actions each case uses, and one case refuses `reshare`.

`verify` checks only a digest, and an issuer names itself. So on a real crossing, who sent a publication or a notice
must come from the transport's authenticated peer (follow-up, below), never from the artifact alone.

## Accounts compared, not forced to agree

For every pair answered copied, same sources or overlapping, `compare_sourced` shows both records side by side, as
`overlap` does for one origin: each publisher's record, its sources with how they matched, and the relations that
touch it. The source keys are the correspondence `overlap` asks for across origins. Whether the two records agree
isn't decided. They're shown, and the notice reports show what a notice would do on each side.

## The planted stores (C4)

`atlas/tests/fixtures/claim_crossing/` holds everything below, all fixed in one commit before any run:

- **The publications:** `pi.json`, `tardis.json` and `third.json`, each `publish_sourced`'s full output, with a fixed
  `issued_at` so every digest reproduces. The issuers are `urn:superyak:fixture:pi`, `urn:superyak:fixture:tardis` and
  `urn:superyak:fixture:third`.
- **Their policies**, and **`notices.json`**.
- **`expected.json`:** for each pair, the answer and its linking digest; for each notice, the exact output of steps 1
  to 5. Counts are per case.
- **Local ids:** each store's sources have their own ids (`pi-S1`, `t-S1`).
- **DOIs:** under `10.5555/superyak-fixture-...`. That's a test prefix used in Crossref's examples, not formally
  reserved, so the suffixes are plainly synthetic, and nothing resolves a DOI.
- **Items:** fictional, `proposed` or `source_reported`, with one `reviewed` record, whose `reviewed_by` crosses as
  the issuer's URI.

**Cases, each with at least two pairs:**

- **Copied:**
  - copied;
  - copied twice through `third`;
  - sibling copies of one `third` claim;
  - a carried Claim, the identical digest on both sides;
  - a copy of a claim with no evidence, which is copied because rule 1 comes first;
  - both chains sharing one unresolved digest, which is copied (C9).
- **Unknown:**
  - both root sets empty;
  - one empty against one not;
  - one unresolved digest that isn't shared;
  - two different DOIs with one title and year, which is unclear.
- **Same sources:**
  - one DOI as `https://doi.org/10.5555/superyak-fixture-a1`, as `http://dx.doi.org/10.5555/SUPERYAK-FIXTURE-A1`,
    and as `doi: 10.5555/superyak-fixture-a1.)` in a citation;
  - a doi.org url with `%3C` and `%3E`;
  - the same publisher url on both sides, one with a citation DOI and one without (C6);
  - title drift under one DOI;
  - a publisher url against a DOI with the same title and year;
  - http against https;
  - `www.` against none.
- **Different, not merged:** two SICI-style DOIs from one issue, `…(199806)49:8<693::…` and `…49:8<701::…`, are two
  different sources (C5).
- **Overlapping:** one source shared, by key or by title, and one source each.
- **Independent:**
  - disjoint DOIs with different titles;
  - disjoint urls with different titles;
  - the C10 limit: a record that leans, by relation, on a copy and cites its own source.
- **Refused:** a `reshare` that `third`'s policy doesn't allow.
- **Notices:**
  - a retraction by DOI that reaches the other side's url-keyed copy, by title and through its chain;
  - a retraction reached through a copied chain;
  - a retraction with no match, which reports "no impact";
  - a correction that changes the DOI, then a retraction by the new DOI, which reaches records keyed by the old one;
  - a correction in a publication of two claims, which names only the claim built on the corrected record.

## Measure

Fixed in the fixtures' commit, before the run (goals R1 and T1):

1. **On the planted stores,** `relation` gives every pair its expected answer and linking digest.
2. **The notices' reports** equal `expected.json`'s, entry for entry.
3. **Real crossings,** once Tardis's Lighthouse and the transport stand. What's reported is the count of each answer,
   every "unknown" with its reason, and every copied, same sources or overlapping pair side by side. It's never a score.

**The pairs for real crossings (C1)** are fixed in a commit before the run, and are the union of three sets:

- claims about the same thing: items whose titles match by `store._normalized_title`, which is what
  `store.duplicates` uses;
- claims whose roots share a match;
- claims linked by a chain.

The first set is what lets a real crossing show "independent".

A failure is a result, written in `docs/north-star.md`'s row 5.

## What this spec does not do

- **The transport.** It's a follow-up spec, after the rule passes on fixtures. It owns who sent what: a sender comes
  from the crossing's authenticated peer, never from an artifact's self-named issuer.
- **Permissions.** Anything that crosses machines for real does so under each owner's ledger. A real crossing waits
  on an allow its owner signs, and for the Pi and Tardis that's Andy's.
- **Agreement.** Neither side's account is changed. The rule reports the relation, the comparison shows both, and
  each store keeps its own belief and history.
- **An "issuer chain".** Lighthouse has none: each artifact has one issuer. "Chain" here means only the `provenance`
  digests between Claims.
