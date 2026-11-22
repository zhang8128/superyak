# North-star test 5, Measure 3: real collections, crossed, against a blind audit

**Draft, revision 1, 2026-11-22. Tardis. Not yet fixed.** It's fixed only after three things: Rio Grande's and
Serenity's reads, a fresh reviewer's approval under station law section 3, and a commit of its final text. Nothing
below changes after the first search starts. A finding during the run is reported; it doesn't change this page.

**The source of each part:**
- **The measure:** the claim-crossing spec, "Measure", item 3 (`docs/superpowers/specs/2026-11-22-claim-crossing-design.md`,
  on main).
- **The transport:** `docs/superpowers/specs/2026-11-22-claim-crossing-transport-design.md` (approved, amendments 1 and 2).
- **The design:** Rio Grande proposed it (all hands 567cc381). Tardis's four changes, which Rio Grande agreed, are in
  3c3cfaa1. Rio Grande's additions are in 31cd25b1, and Serenity's audit conditions in 8279b775 and 1d212bf9.

## Why

- **No real Atlas data exists to cross.** The Pi and Tardis have no Atlas store, and the Mac's one is test 1's Wikipedia
  corpus.
- **The planted stores** (Measures 1 and 2) check the rules against their spec, because the same team planted the
  answers. This run is the first where nobody planted them.
- **The honest bar (Tardis, from test 6):** by mechanism, `relation()` is source keys plus ordered rules plus chains.
  So it must beat the plain matching it reduces to, on real data, or the keys and rules haven't earned their place.

## The question

**Does hydroxychloroquine, with or without azithromycin, change all-cause mortality in patients with COVID-19?**

- **In scope:** primary studies (trials, cohort and registry studies), systematic reviews and meta-analyses,
  published from 2020 to 2023, that report mortality, plus their preprints.
- **Notices:** retraction notices for any of them.

**The known real cases** (named so the run can say whether they arose, not planted):
- **RECOVERY:** a medRxiv preprint and its NEJM version, a real case for the preprint-against-journal rule.
- **The Surgisphere registry papers,** retracted in June 2020 from *The Lancet* and from *NEJM*: two real notices.

## The two collections

- **Builders:** Tardis builds collection T on Tardis, and Rio Grande builds R on the Pi.
- **Independence:** neither reads the other's drafts, posts about sources, or collection until both are frozen.
- **Size:** 15 to 30 sources, and 10 to 25 claim records. Each record is one finding about mortality, citing its sources
  as evidence (`source_id`, with a locator).
- **Sources:** each carries `title`, `url` (the page the builder actually used), `year` and `citation`. The citation
  holds the DOI when the builder knows it.
- **Search, with each ship's own queries:**
  - each query is logged verbatim, with a UTC time, in the collection's `queries.log`;
  - the allowed sources are PubMed, Crossref, medRxiv and bioRxiv, and publisher pages;
  - each builder decides inclusion alone and writes a one-line reason per source.
- **Format:** an Atlas bundle (`sources`, `items`, `relations`), published with `publish_sourced`.
  - **The issuer** is `urn:superyak:peer:<the publishing peer's id>`.
  - **The policy** follows the transport's T5: `read`, `link_overlap` and `retain` for the other peer's URI exactly; no
    `reshare` and no `*`.
- **The freeze:** each side commits its bundle, its publication and its `queries.log`, and posts their sha256 in all
  hands. Nothing in a frozen collection changes afterwards.

## After both are frozen

1. **Copies, as declared provenance:**
   - each side copies 3 of the other's claim records into a second publication, with `copied_from` naming the
     original Claim's digest;
   - the three are chosen with `numpy.random.default_rng(20261124)`, from the other side's claims sorted by record id;
   - these are the run's known copied pairs.
2. **Notices:** for each of its own sources that Crossref or PubMed marks retracted, a side seals a retraction notice
   (`seal_notice`). A side only notices its own records.
3. **The audit** (below) runs on the frozen files and is sealed. It needs no crossing.
4. **The crossing, once Andy's pairing exists:** each side sends both publications and its notices with `atlas-send`.
   The receiving side then runs, in order:
   - `atlas-received`;
   - `atlas-verify` on every file;
   - `received(..., trusted_origins=origins.json)`;
   - `held_claims`;
   - `relation()` over the pair set;
   - `apply_notice` for each notice.

## The audit (Serenity owns it)

- **Who labels:** a fresh agent that has never seen `relation()`'s code, its rules or its output. It's given only:
  - this section's label definitions;
  - the two frozen collections;
  - access to the external record: Crossref and PubMed metadata, DOI and PMID identity, preprint-to-published
    relations, and retraction notices.
- **Serenity's role:**
  - she spot-checks a seeded sample of its labels by hand, 50 source pairs drawn with
    `numpy.random.default_rng(20261125)`, and posts the agreement rate;
  - she doesn't search the question or open either collection before both freezes are posted;
  - neither builder shares drafts with her.
- **The seal:** the labels' sha256 goes in a commit and is posted in all hands before `relation()` or either baseline
  runs. The labels themselves are published after the rules run.

**Labels, one per cross source pair** (every pair of one T source and one R source, at most 900):
- **SAME:** the same published item, by DOI or PMID. Or a preprint and its published version, *as the external record
  links them* (for example Crossref's `is-preprint-of` or a PubMed/medRxiv link).
- **DIFFERENT:** the external record identifies two distinct items, with different DOIs or PMIDs not linked as
  versions.
- **UNCLEAR:** the external record doesn't settle it, for example a source with neither DOI nor PMID, a news page or a
  dataset. The reason is written beside it.

**Notice reach, per notice:** the receiving side's records whose evidence rests on the retracted item, by the external
record's identity.

**Derived truth for claim pairs, mechanically from the labels and the declared copies,** never labelled by hand:
- **copied:** a declared copy, or its chain;
- **same sources:** every source of each record is SAME as one of the other's;
- **overlapping:** at least one SAME pair;
- **independent:** every cross source pair is DIFFERENT;
- **left out and counted:** any pair whose label set has an UNCLEAR that decides it.

## What's compared

Each method answers every cross claim pair from the frozen collections alone:
- **R:** `relation()`, at main.
- **B1, exact DOI:** two sources match only if both have the same DOI key. Then claim answers follow the derived-truth
  rules above, with "match" for SAME and "no match" for DIFFERENT, and no title rule and no chains.
- **B2, exact DOI or url:** as B1, also matching on an equal url key.

"Copied" answers come from declared chains, which the baselines lack by design. So they're scored for R alone and
never compared with B1 or B2 (Rio Grande, 31cd25b1).

## Measures, fixed

- **Primary, the dangerous error:** claim pairs a method calls **independent** whose derived truth is same sources or
  overlapping. That's double-counted evidence.
  - **Reported:** R, B1 and B2's counts, with paired disagreements and an exact McNemar test between R and each
    baseline.
  - **The reading:** "the structure helps on real data" only if R's count is strictly lower than **B2's** with an exact
    McNemar p < 0.05. Otherwise, "no measured gain", which is a result.
- **Secondary:**
  - false merges: pairs a method calls same sources or overlapping whose truth is independent;
  - R's unknown and unclear answers, each with its reason, against the derived truth;
  - the audit's UNCLEAR pairs, counted.
- **Copies:** R must answer copied on each of the 6 declared copies, and on no other pair. Each miss and extra is
  listed.
- **Notices:** `apply_notice`'s reach against the audit's reach, per notice, with every difference listed.
- **The transport:** rows sent, delivered, refused and retried; the seconds from send to receipt; and `atlas-verify`'s
  result on every file.

## What this can't show, said before the run

- **Independence:**
  - both builders are the same model family, searching the same indexes, so "built independently" isn't independent
    sampling (Tardis);
  - the auditor is the same family too, so the audit is blind to the rule but isn't an independent judge (Serenity).
- **Size:** at most 900 source pairs and a few hundred claim pairs, on one question. A null is weak evidence.
- **Matching:** relation()'s rules 2 and 4 call a preprint against its journal version "unclear", where the audit calls it
  SAME. The primary counts only "independent" errors, so that caution is never scored against R. The secondary lists
  it.

## The order of events

1. This page is read, approved and committed.
2. Each side searches and builds.
3. Both freezes are posted.
4. The copies and notices are made.
5. The audit is labelled and its seal posted.
6. Andy pairs `rio-grande` into tardis-peer.
7. The crossing runs, and the rules run.
8. The labels are published.
9. The results go into `docs/north-star.md` row 5.
