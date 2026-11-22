# Claims that cross with their sources' identity (north-star test 5, Rio Grande's half)

Revision 1, 2026-11-22. Rio Grande (the Pi). Board item `north:5-two-lighthouses-keep-source-identity`. Under
station law section 3, a fresh reviewer approves it in Andy's place, and Andy can veto.

## Why

Andy, 2026-11-22, at Serenity's terminal: "i'd use this essay as a bit of a north star, can you captain and
reorient?" Test 5 of [docs/north-star.md](../../north-star.md) asks two lighthouses, the Pi's and Tardis's, to exchange
evidence while keeping each source's identity. Copied evidence must be told from independent confirmation, a
correction in one must reach what the other built on it, and their accounts are compared without forcing agreement.

Today the crossing carries recall and read of memories only. No claim crosses, and nothing tells copied from
independent.

## The split, agreed (all hands 983200e5, 76c735c8, daf52d30, 1102371c)

- **This spec (Rio Grande):** what a claim carries across, the source identity key, retraction and correction notices,
  and the planted pair of stores with known answers.
- **Tardis (T1):** the receiver's rule, a pure function of two claims' root sets and chains, written test-first on
  these planted stores. Also a second Lighthouse, so evidence travels both ways.
- **Tardis with Serenity (test 6):** the sheaf and n-category machinery against this plain rule, on the same data.

## What exists

- **Lighthouse 0.1** already has a `Claim`: `sentenceMediaType`, an opaque `sentence`, `snapshotDigests`, `provenance`
  (an array of digest references) and an optional validity interval. It also has a `Snapshot`: an opaque `model` and
  `lineage` digests. See `lighthouse/packages/protocol/src/schemas.ts` and `atlas/workbench/lighthouse_wire.py`, whose
  `seal` and `verify` make and check both. The protocol doesn't say what `provenance` points at. This spec fills it in.
- **Atlas** keeps sources (`id`, `title`, `url`, `year`, `citation`), items with `evidence` naming source ids, and
  relations. `Store.retraction_impact` (train 1144b) says what a retraction does to what depends on it.

No new artifact kind is added.

## A source's identity

A source's identity is its content, not its place: two stores citing one paper share it. The store and record ids
still travel, in the issuer chain and the record, so who held what is kept. The **key** is chosen in this order:

1. **`doi:` + the DOI**, when the url is a doi.org link or the citation holds a DOI (`10.` then a registrant, `/`, and
   a suffix). The DOI is lowercased. `https://doi.org/`, `http://dx.doi.org/` and `doi:` are taken off, and
   surrounding spaces and a trailing full stop too. Strength: **strong**.
2. **`url:` + the normalised url**, when there's a url and no DOI. The scheme and host are lowercased, a default port,
   the fragment and one trailing slash are taken off, and the query is kept as it is. Strength: **strong**.
3. **`title:` + the normalised title + `:` + the year**, otherwise. The title is NFKC-normalised and casefolded, with
   punctuation taken off and spaces collapsed. Strength: **weak**.

Titles and citations drift in punctuation, case and order, so two copies of one paper can key apart. Reading them as
independent double-counts evidence, the worse error. So a weak key never by itself makes "independent" (Tardis,
1102371c). The key and its strength are computed by one function, `source_key(record)`, which both sides import.

## What crosses

**A source** travels as a `Snapshot`, with profile `superyak:atlas-source/1` and `model`:

```
{"key": "doi:10.1000/xyz", "strength": "strong", "revision": 2,
 "record": {"id": "S1", "title": "...", "url": "...", "year": 2024, "citation": "..."}}
```

Its digest changes with its revision. Its identity is `key`, which doesn't change.

**A claim** travels as a `Claim`, with profile `superyak:atlas-claim/1`, `sentenceMediaType`
`application/vnd.superyak.atlas-item+json`, and `sentence` holding the Atlas item: its id, kind, title, body and
status. Its `provenance` lists:

- the digest of each source Snapshot its evidence names;
- the digest of each `Claim` it was copied or derived from, when it came from another store.

`snapshotDigests` stays as the protocol means it.

A claim's **root set** is every source key reached through its provenance, following copied claims to their own
sources. Its **chain** is the claim digests that its provenance reaches. Both are a function of the artifacts alone,
so the receiver needs no access to the other store.

**A retraction or a correction** travels as a `Claim` with `sentenceMediaType`
`application/vnd.superyak.source-notice+json`:

```
{"notice": "retraction", "key": "doi:10.1000/xyz", "reason": "..."}
{"notice": "correction", "key": "doi:10.1000/xyz", "revision": 2, "corrected_by": "<digest of revision 3>", "reason": "..."}
```

A retraction targets the identity, so it covers all revisions. A correction targets one revision (Tardis, 1102371c).
The receiving store applies a retraction by key to its own claims with Atlas's `retraction_impact`, and keeps the
earlier belief in its audit history, as Atlas already does.

## The five answers

For two claims from two stores, the receiver's rule gives one of five answers, never rounded (Tardis, 1102371c):

| Answer | When |
| --- | --- |
| copied | a Claim digest in one chain links the two |
| same sources | the root sets are equal, every key strong, and no chain link: one piece of evidence held twice |
| overlapping | the root sets share a key and differ, with no chain link |
| independent | the root sets are disjoint and every key is strong |
| unknown | either root set is empty, or a weak key decides the answer |

The rule is Tardis's to write (T1). This spec fixes the answers it must give on the planted stores.

## The planted stores

`atlas/tests/fixtures/claim_crossing/` holds two Atlas stores, `pi.json` and `tardis.json`, and `expected.json`, all
fixed in a commit before any run. There are 16 claim pairs, at least two per case:

- **copied:** Tardis imports a Pi claim. Its provenance names the Pi's Claim digest.
- **copied twice:** Tardis copies a Pi claim that was itself copied from a third store, issuer `fixture-c`.
- **same sources:** both cite one DOI, written once as `https://doi.org/10.1/A` and once as `doi:10.1/a`.
- **drift:** the same paper under one DOI, its title punctuated and cased differently on each side, gives same sources.
- **overlapping:** one source shared and one source each.
- **independent:** disjoint strong keys, one by DOI and one by url.
- **weak, deciding:** neither side has a DOI or url, and the titles differ only in punctuation. The answer is unknown,
  never independent.
- **no roots:** a claim with no evidence gives unknown.
- **a retraction:** the Pi retracts source X by key. On the Tardis store, `retraction_impact` reaches each claim whose
  root set holds X, and `expected.json` names them, with each verdict: unsupported, challenge lost, still supported or
  not grounded before either.
- **a correction:** the Pi corrects revision 1 of source Y. Only claims built on revision 1 are named. A claim on
  revision 2 is not.

The fixtures are research evidence built for the test: no person's data, no real person's name. Fictional sources
use the DOI prefix `10.5555`, which is reserved for examples.

## Measure

Fixed in the fixtures' commit before the run (goals R1 and T1):

1. On the planted stores, the receiver gives every pair its expected answer: 16 of 16.
2. The retraction and the correction reach exactly the claims `expected.json` names.
3. Then real crossings both ways, once Tardis's Lighthouse stands. Those are reported as counts of each answer, with
   every "unknown" listed, never as a score.

A failure is a result, and it's written down in `docs/north-star.md`'s row 5.

## What this spec does not do

- **The transport.** Today's crossing frames carry memories. Carrying claims and source Snapshots over the crossing
  is a follow-up spec, after the rule passes on fixtures. The fixtures are artifacts on disk, so the rule is tested
  without a network.
- **Permissions.** Atlas evidence is research data, not a person's, but anything that crosses machines for real does
  so under each owner's permissions ledger. A real crossing of claims waits on an allow that its owner signs. For the
  Pi and Tardis, that's Andy's.
- **Agreement.** Neither side's account is changed to match the other. The rule reports the relation, and each store
  keeps its own belief and history.

## Open questions

1. Should a DOI found only in `citation` count as strong, or only one in `url`? The draft says both, since a citation
   with a DOI is as specific as a link.
2. Is url normalisation's kept query right? Tracking parameters would make one page key apart. The draft keeps the
   query, because dropping it can merge pages that differ, and merging is the worse error here.
