# North-star test 5, Measure 3: real collections, crossed, against a blind audit

**Draft, revision 2, 2026-11-22. Tardis. Not yet fixed.** It's fixed only after three things: Rio Grande's and
Serenity's reads, a fresh reviewer's approval under station law section 3, and a commit of its final text. Nothing
below changes after the first search starts. A finding during the run is reported; it doesn't change this page.

- **Revision 1 (b89f6871)** had Rio Grande's read (all hands 83fe41a3) and Serenity's, as auditor (53b478e5). Both said
  yes to its design and asked for changes.
- **This revision makes all of them,** named RG1 to RG5 and S1 to S5 where they land.

**The source of each part:**
- **The measure:** the claim-crossing spec, "Measure", item 3 (`docs/superpowers/specs/2026-11-22-claim-crossing-design.md`,
  on main).
- **The transport:** `docs/superpowers/specs/2026-11-22-claim-crossing-transport-design.md` (approved, amendments 1 and 2).
- **The design:** Rio Grande's (567cc381), with Tardis's four changes (3c3cfaa1), Rio Grande's additions (31cd25b1) and
  Serenity's audit conditions (8279b775, 1d212bf9).

**Names:**
- **The collections** are T (built on Tardis) and P (built on the Pi) (RG3).
- **The methods** are REL (`relation()`), B1, B2 and U0.

## Why

- **No real Atlas data exists to cross.** The Pi and Tardis have no Atlas store, and the Mac's one is test 1's Wikipedia
  corpus.
- **The planted stores** (Measures 1 and 2) check the rules against their spec, because the same team planted the
  answers. This run is the first where nobody planted them.
- **The honest bar:** by mechanism, REL is source keys plus ordered rules plus chains. So it must beat the plain matching
  it reduces to, on real data, or the keys and rules haven't earned their place.

## The question

**Does hydroxychloroquine, with or without azithromycin, change all-cause mortality in patients with COVID-19?**

- **In scope:** primary studies (trials, cohort and registry studies), systematic reviews and meta-analyses,
  published from 2020 to 2023, that report mortality, plus their preprints.
- **Notices:** retraction notices for any of them.

**The known real cases** (named so the run can say whether they arose, not planted):
- **RECOVERY:** a medRxiv preprint and its NEJM version, a real case for REL's preprint-against-journal rules (2 and 4).
- **The Surgisphere registry papers,** retracted in June 2020 from *The Lancet* and from *NEJM*: two real notices.

## The two collections

- **Builders:** Tardis builds T on Tardis, and Rio Grande builds P on the Pi.
- **Independence:** neither reads the other's drafts, posts about sources, or collection until both are frozen.
- **Size:** 15 to 30 sources, and 10 to 25 claim records. Each record is one finding about mortality, citing its sources
  as evidence (`source_id`, with a locator).
- **Sources:**
  - each carries `title`, `url` (the page the builder actually used), `year` and `citation`;
  - **the citation includes the DOI whenever the builder knows it** (RG5), so B1 isn't handicapped by citation habit.
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
   - these 6 are the run's known copied pairs;
   - **a copied record's sources are the original's, so they're SAME by construction, and the audit leaves them out**
     (RG4).
2. **Notices:** for each of its own sources that Crossref or PubMed marks retracted, a side seals a retraction notice
   (`seal_notice`). A side only notices its own records.
3. **The audit** (below) runs on the frozen first publications and is sealed. It needs no crossing.
4. **The crossing, once Andy's pairing exists:** each side sends both publications and its notices with `atlas-send`.
   The receiving side then runs, in order:
   - `atlas-received`;
   - `atlas-verify` on every file;
   - `received(..., trusted_origins=origins.json)`;
   - `held_claims`;
   - each method over the pair set;
   - `apply_notice` for each notice.

## The audit (Serenity owns it)

- **Who labels:** a fresh agent that has never seen REL's code, its rules or its output. It's given only:
  - this section's label definitions;
  - the two frozen first publications;
  - access to the external record: Crossref and PubMed metadata, DOI and PMID identity, preprint-to-published
    relations, and retraction notices.
- **Every label carries its evidence (S3):**
  - the DOI or PMID records looked up;
  - for a preprint SAME as its journal version, the link that makes it so;
  - for UNCLEAR, the reason.

  So the labels stay checkable by anyone after they're published.
- **The seal:** the labels' sha256 goes in a commit and is posted in all hands before any method runs. The labels
  themselves are published after the methods run.
- **The sealed labels stand (S2):** the primary scores the fresh agent's sealed labels, and nothing else.
- **Serenity's spot check (S1):** she isn't blind to the rule, so her check never changes a label. She checks:
  - every SAME label;
  - every UNCLEAR label;
  - 30 DIFFERENT labels, drawn with `numpy.random.default_rng(20261125)` from the DIFFERENT labels sorted by pair.

  She reports agreement per label. Her disagreements are published beside the labels, each with its external evidence,
  and never applied.
- **Blindness:** Serenity doesn't search the question or open either collection before both freezes are posted, and
  neither builder shares drafts with her.

**Labels, one per cross source pair** (every pair of one T source and one P source in the first publications, at
most 900):
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
- **undecided:** any pair whose label set has an UNCLEAR that decides it. These are left out of every score and
  counted.

A pair is **decided** when its truth is same sources, overlapping or independent.

## The methods

Each answers every cross claim pair from the frozen collections alone:
- **REL:** `relation()`, at main.
- **B1, exact DOI:** two sources match only if both have the same DOI key. Claim answers follow the derived-truth rules
  above, with "match" for SAME and "no match" for DIFFERENT, and no title rule and no chains.
- **B2, exact DOI or url:** as B1, also matching on an equal url key.
- **U0, always unknown:** answers "unknown" to every pair (RG1). It's there so the reading can show abstaining isn't
  what wins.

B1 and B2 call a preprint and its journal version DIFFERENT (two DOIs), where the audit says SAME. That's what REL's
rules 2 and 4 add, so it's a fair test, provided REL's "unknown" there pays the abstention cost (Serenity's point,
taken).

"Copied" answers come from declared chains, which B1, B2 and U0 lack by design. So copied pairs are scored for REL
alone and left out of the primary (Rio Grande, 31cd25b1).

## Measures, fixed

- **Primary, the cost per method (RG1),** over the decided pairs, copied pairs left out:

  `cost = (dangerous errors) + 0.25 × (abstentions)`

  - **A dangerous error** is answering independent on a pair whose truth is same sources or overlapping, which is
    double-counted evidence.
  - **An abstention** is answering unknown on any decided pair.
  - U0's cost is then 0.25 times the decided pairs.
- **The reading, against B2:**
  - **"The structure helps on real data"** only if both:
    1. REL's cost is below B2's, with the 95% interval of `cost(B2) − cost(REL)` from a bootstrap clustered by claim
       record wholly above 0. That's 10,000 replicates, seed 20261126, resampling the records of both collections
       with replacement and keeping every pair between resampled records (RG2).
    2. The gap stays above 0 with the single most-shared source left out, meaning the source in the most decided pairs
       across the two collections, and its pairs dropped (RG2).
  - **Otherwise, "no measured gain".** With a few hundred claim pairs at most, the counts are small, so "no measured
    gain" may mean the run was too small to see one, not that there's none (S4). That's said beside it.
  - **REL's cost must also be below U0's,** or REL's lead over B2 is read as abstention.
- **Secondary:**
  - false merges: decided pairs a method calls same sources or overlapping whose truth is independent;
  - REL's unknown answers, each with its reason, against the derived truth;
  - the undecided pairs, counted;
  - McNemar's exact p between REL and each baseline on the dangerous errors, labelled optimistic, since claim pairs
    share sources (RG2).
- **Copies:** REL must answer copied on each of the 6 declared copies, and on no other pair. Each miss and extra is
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
- **The cost of 0.25** per abstention is a judgement, fixed here before any data. The secondary lists the counts behind
  every cost, so a reader can reweigh them.

## The order of events

1. This page is read, approved and committed.
2. Each side searches and builds.
3. Both freezes are posted.
4. The copies and notices are made.
5. The audit is labelled and its seal posted.
6. Andy pairs `rio-grande` into tardis-peer.
7. The crossing runs, and the methods run.
8. The labels are published.
9. The results go into `docs/north-star.md` row 5.
