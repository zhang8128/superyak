# Blind reading: spec gaps and judgement calls

Line numbers refer to `spec.md` in this folder. "Affects" names the notices and fields whose values depend on the gap.
In `blind-reports.json`, a field affected by a gap holds my best reading.

## How I computed

- I wrote `source_key` out of lines 62-107 and recomputed every source key in all four held publications (the two
  carried copies of the Pi snapshot included) and in all five notices (lines 128-129, 211-212). Every recomputed key
  equals the published one, so no publication or notice is refused for its keys.
- I built Tardis's store from `held/tardis.json`'s `snapshot.payload.model` (46 sources, 50 items, 2 relations).
  Chains come from that file's Claims, and digests are resolved against every Claim in the four held files, carried
  ones included.
- I did not check the artifact digests. The spec doesn't give the canonical form `seal` and `verify` use (line 292),
  and that is outside this reading.

## Gaps

### 1. No shape is given for the report or its entries
- **Lines:** 206-245, 213-228.
- **Affects:** every field of every notice.
- **What's open:** the spec says what each step finds, but never names the fields (`matched`, `unclear`,
  `through_chain`, `impact`, `corrected`, `outcome` come from the task). It also never gives an entry's keys.
- **What I used:**
  - `matched` entries are `{source_id, by, snapshot, record_id}`, naming the gathered record matched. Lines 227-228
    ("named by the first it matches in gathering order") imply that an entry names a gathered record.
  - `unclear` entries would be `{source_id, snapshot, record_id}` (line 217: "with that record's Snapshot and id").
  - `through_chain` and `corrected` entries are `{record_id, verdict}`.
  - `impact` entries are `{record_id, verdict, path}` (line 233).

### 2. Which name a match takes when several keys are equal
- **Lines:** 119, 131-133, 72, 214-215.
- **Affects:** `matched[].by` in N1, N4 and N5.
- **What's open:** in N1, N4 and N5, `t-lean-copy-a-1` and `t-copied-a-1` equal the gathered record in all three
  keys: url (strong), DOI and title. Rule 3 (line 119) says only that "any" equal strong key or equal title keys make a
  match. Line 133 says the report names "how each source matched", without saying how to pick between several ways.
  - Line 72 ("names such a match by 'title', never 'url'") implies that url outranks title when both are equal. It is
    silent on url against DOI.
- **What I used:** the first equal key in the order the spec lists them (lines 64, 85, 105, 133, 140: url, DOI,
  title), so `"by url"`.
- **Alternatives:** `"by DOI"` (the strongest key), or a list of every equal key (`["url", "DOI", "title"]`).

### 3. The form of a match's name
- **Lines:** 133 against 72.
- **Affects:** `matched[].by`, all notices that have one.
- **What's open:** line 133 writes the names as "by url", "by DOI" and "by title", and line 72 as "title" and "url".
- **What I used:** the line 133 form.

### 4. How a Snapshot is referenced in an entry
- **Lines:** 39, 202, 217, 226.
- **Affects:** `matched[].snapshot` (and `unclear` entries, though none occur).
- **What's open:** whether an entry holds a digest object or a bare hex string. Line 226 sorts by "Snapshot digest",
  which is natural for a string.
- **What I used:** the digest object `{"algorithm": "sha-256", "value": ...}`, as the notices themselves carry it
  (line 202 and the data).

### 5. Read authorization of a notice against Tardis's policy
- **Lines:** 196, 249, 252-254, 274, 282.
- **Affects:** all five notices, all fields.
- **What's open:** a notice needs `read` (line 274), and every step goes through `authorize` "with this profile and
  the artifact's media type" (line 249).
  - Tardis's only `read` rule (`tardis-reads` in `held/tardis.json`) lists `claimMediaTypes`
    `["application/vnd.superyak.atlas-sourced-claim+json"]`.
  - Every notice's `sentenceMediaType` is `application/vnd.superyak.source-notice+json` (line 196 and the data).
  - Read literally, Tardis refuses to read every notice. The spec defines no report for a refused notice.
  - Line 282 says the fixture policies grant exactly the actions each case uses, which suggests the notice cases were
    meant to be readable.
  - Without code I can't tell whether `authorize` compares `claimMediaTypes` with the sentence media type, the
    payload media type (`application/vnd.lighthouse.claim+json`), or neither for notices.
- **What I used:** the notices are read and applied. Under the literal reading, all five would instead be refused,
  with no report shape defined.

### 6. `retraction_impact` has no verdict vocabulary
- **Lines:** 56-57, 232-234.
- **Affects:** `impact[].verdict` in N1, N2 and N5.
- **What's open:** the spec says each item comes "with its verdict and path", but names no verdict. This is one of
  the two operations given only in prose.
- **What I used:** placeholders. `"cites a retracted source"` marks an item whose own evidence names a step-2 id, and
  `"supported by an impacted item"` marks an item reached through a `supports` relation. The item set is what I'd
  expect a check to compare. The verdict strings can't be read off the spec.

### 7. The form of an impact item's `path`
- **Lines:** 56-57 ("with relations inside each item's path"), 233.
- **Affects:** `impact[].path` in N1, N2 and N5.
- **What's open:** what a path starts with (the source id or the item), whether it includes the item itself, and
  whether it holds relation ids or relation objects.
- **What I used:** `[source id, item, relation id, item, ...]`. A direct item is `[source, item]`, and N1's `T-lean-a`
  is `["t-lean-copy-a-1", "T-lean-copy-a", "T-lean-rel-a", "T-lean-a"]`.

### 8. Which way `supports` and `challenges` are followed, how far, and under what status
- **Lines:** 233-234, 189-192.
- **Affects:** `impact` in N1 (`T-lean-a`).
- **What's open:**
  - Direction: relation `T-lean-rel-a` is `T-lean-copy-a supports T-lean-a`. The spec says a belief "built on" a
    retracted source is reported, and C10 (lines 189-191) says B (`T-lean-a`) is reached "through `supports`" when
    the copy's source matches. Both point from subject to object, but the spec never states the direction.
  - Reach: it doesn't say whether the walk is transitive.
  - Status: it doesn't say whether a `proposed` relation is followed (both relations are `proposed`).
- **What I used:** subject to object, transitive, any status. Only one hop occurs in the data.

### 9. The order of impact items
- **Lines:** 226 (only `unclear` gets a sort order).
- **Affects:** `impact` in N1.
- **What's open:** no order is given for impact items, or for the `matched`, `through_chain` or `corrected` lists.
- **What I used:** reach order, with direct items first. Sorted by id, N1's two items would swap.

### 10. A correction's own sources, and their gathering order
- **Lines:** 208-212, 227-228, 236-239.
- **Affects:** N4 (no value changes here).
- **What's open:** step 1 gathers "the notice's source" plus sources joined by held corrections. For a correction,
  the spec doesn't say whether the notice's source is `old`, `new` or both, or which counts as "the notice's own record
  first" (line 228).
- **What I used:** both, `old` first. This changes nothing in N4, because `t-copied-a-1` matches only `old`. Against
  `new` it is rule 2's "unclear": the DOIs differ and the title is the same. So it isn't listed under `unclear`
  (line 216: "matches no gathered source").
- **Alternative:** if only `new` were gathered, N4 would have no match and an `unclear` entry for `t-copied-a-1`.

### 11. Step 4 for a correction
- **Lines:** 232, 236.
- **Affects:** `impact` in N4.
- **What's open:** step 4 is "for a retraction". Step 5 says that for a correction "steps 1 to 3 run", then the D6
  verdicts.
- **What I used:** `retraction_impact` doesn't run for N4, so `impact` is `[]`.

### 12. `corrected` on a retraction
- **Lines:** 236-239.
- **Affects:** `corrected` in N1, N2, N3 and N5.
- **What's open:** whether the field is an empty list, null or absent.
- **What I used:** `[]`.

### 13. What "roots ... include a gathered source" means
- **Lines:** 168-173, 208-210, 229-231, 237-239.
- **Affects:** `through_chain` in N1, N4 and N5, and `corrected` in N4 (no value changes here).
- **What's open:** "Include" could mean the same Snapshot and record id, or a key match through `source_key`.
- **What I used:** identity, the same Snapshot digest and record id, the sense line 209 gives "joined".
- **Alternative:** a key match. Both readings give the same lists on this data: the chain roots
  `pi-lean-a-1@860a0c` and `pi-copied-a-1@860a0c` are themselves gathered records, and no other chain-reached root
  matches a gathered record by key.

### 14. Whether step 3 counts a claim's own local roots
- **Lines:** 168-170, 229-231.
- **Affects:** `through_chain` in N2.
- **What's open:** step 3 says "every local claim whose roots, followed through its chain, include a gathered
  source", and its heading is "reached through a chain". A claim's roots include its own local sources (line 168).
- **What I used:** only roots reached through the chain (the provenance digests). Under identity (gap 13), own local
  roots sit in Tardis's Snapshot and can never be a gathered Pi record anyway.
- **Alternative:** own roots matched by key would also count. Then N2's `through_chain` would list `T-pub-doi-a`,
  which has no chain. N1, N4 and N5 already list the same claims.

### 15. Where a local claim's chain comes from, and how a local claim is named
- **Lines:** 143-146, 158-159, 164-166, 171-173.
- **Affects:** `through_chain` and `corrected`.
- **What's open:** the task builds the store from the model, but the model's items carry no Claim provenance. That
  is only on the publication's Claims (and the item-level `provenance` map is removed before sealing, line 145).
- **What I used:**
  - Chains are read from the Claims in `held/tardis.json`.
  - A local claim is named by its record id. The spec doesn't say whether that, or the Claim digest, names it; the
    digests are `T-lean-copy-a` bd37a1ac46fe568814c41e74b38222b5124902f707d3901d896cf90f6d7c24f3 and `T-copied-a`
    17fb65a788f419e77fe4c81b638e91a1d8ec579a0187b8c3ed3b2f72b3e2f728.
  - The spec also doesn't say whether Tardis's two carried Claims (`P-carried-a`, `P-carried-b`, lines 164-166) count
    as "local claims". No notice reaches them, so this changes nothing here.

### 16. Normalised title: thin prose
- **Lines:** 105-107.
- **Affects:** title keys and every title comparison.
- **What's open:** the prose says "NFKC, casefold, and punctuation and symbols turned to spaces". It doesn't say:
  - that runs of whitespace collapse to one space and the ends are stripped. The data needs this: "A Study of Drift,
    Part a." keys as `a study of drift part a`;
  - what counts as punctuation and symbols.
- **What I used:** Unicode categories P* and S* become spaces, then whitespace is collapsed and stripped. This
  reproduces every published title key.

### 17. Url key details the data doesn't exercise
- **Lines:** 64-66.
- **Affects:** no values.
- **What's open:** whether "a default port" means the default of the original scheme or of `https`, and whether "one
  trailing slash" means the path's or the whole string's when a query is present. No source in the data has a port,
  or a trailing slash before a query.

### 18. Amendment 1's "shape"
- **Lines:** 92-94.
- **Affects:** no values.
- **What's open:** whether the shape check is an anchored prefix `10\.\d{4,9}/.+` or a full match of the citation
  character class.
- **What I used:** the anchored prefix.
- **Effect:** none. Every url-derived DOI in the data passes both, and `https://doi.org/10.5555` fails both.

### 19. "One of three results" against five rules
- **Lines:** 109-126.
- **Affects:** no values.
- **What's open:** line 109 announces three results, then lists five rules.
- **What I used:** match, unclear (rules 2 and 4) and distinct (rules 1 and 5), as amendment 4 (line 217) treats
  rules 2 and 4 as "unclear".

### 20. Whether applying a notice also needs `link_overlap`
- **Lines:** 255, 274.
- **Affects:** none beyond gap 5.
- **What's open:** step 2 compares the notice's sources with the receiver's own, which line 255's `link_overlap`
  describes. Line 274 names only `read`.
- **Effect:** Tardis's rule grants both for the Pi, so nothing changes apart from the media-type question in gap 5.

## Observations: no gaps, no effect on the reports

- **Amendment 4's claim holds:** line 225 says every planted report's `unclear` list is empty. My computation agrees.
  The only "unclear" pairing is `t-copied-a-1` against `pi-copied-a-1-v2` (rule 2), in N4 and N5, and in both
  `t-copied-a-1` matches the other gathered record, `pi-copied-a-1`.
- **The case list (lines 359-364) fits the five notices loosely:**
  - Line 361 ("a retraction by DOI that reaches the other side's url-keyed copy, by title and through its chain")
    fits none exactly. N1's Tardis copy `t-lean-copy-a-1` is DOI-keyed and matches by all three keys. N2 matches by
    title, but the retracted source is the url-keyed one, and N2 reaches nothing through a chain.
  - Line 364 ("a correction in a publication of two claims") doesn't match `pi-corrected.json`, which holds one
    claim.
- **C10's second half (lines 191-192), "a copy whose local source is keyed another way":** `t-lean-copy-b-1` has the
  same keys as `pi-lean-b-1`, and no notice targets lean-b. Neither half is tested by N1-N5 beyond N1's first.
- **`refuses a publication` (line 129) and D7 (line 212):** nothing is refused, because every recomputed key matched.

**Count:** 20 gaps or judgement calls (gaps 1-20), plus 4 observations.
