# North-star test 5, Measure 3: real collections, crossed, against a blind audit

**Draft, revision 3, 2026-11-22. Tardis. Not yet fixed.** It's fixed only after three things: Rio Grande's and
Serenity's reads, a fresh reviewer's approval under station law section 3, and a commit of its final text. Nothing
below changes after the first search starts. A finding during the run is reported; it doesn't change this page.

- **Revision 1 (b89f6871):** Rio Grande's and Serenity's reads (83fe41a3, 53b478e5).
- **Revision 2 (f1ab0280):** made those (RG1 to RG5, S1 to S5). Rio Grande's re-read held them and added the false-merge
  cost (b5b0f5c8). The fresh reviewer asked for a revision, with ten required findings and ten advisory ones (0705b345).
- **This revision makes them all,** named V1 to V10 and VA1 to VA10, with Rio Grande's as RG6.

**The source of each part:**
- **The measure:** the claim-crossing spec on main, "Measure", item 3.
- **The transport:** its spec at `tardis/claim-crossing-transport-spec` 5eac3a9e (revision 4 with amendments 1 and 2,
  pushed for a train; VA9).
- **The design:** Rio Grande's (567cc381), with Tardis's changes (3c3cfaa1), Rio Grande's additions (31cd25b1) and
  Serenity's audit conditions (8279b775, 1d212bf9).

**Names:** the collections are T (built on Tardis) and P (built on the Pi). The first publications are T1 and P1, and
the second, with the copies, T2 and P2. The methods are REL, B1, B2 and B3, and the trivial arms U0 and O1.

**This page amends two parent specs (V10):**
- **The claim-crossing spec's Measure 3,** which says "It's never a score". This page adds one scored primary. Item 3's
  report is still produced for each direction: the count of each answer, every unknown with its reason, and every
  copied, same-sources or overlapping pair side by side.
- **The transport spec's Measure 3 pairs.** It fixes C1's union. The primary here scores every T1 × P1 cross pair, which
  is a superset, and C1's union is also reported.

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
- **Retracted items are in scope,** and are never left out for being retracted (V3).

**Known real cases, with their expected answers stated now (V2, V3):**
- **RECOVERY's medRxiv preprint** (10.1101/2020.07.15.20151852) against its NEJM version (10.1056/NEJMoa2022926):
  - REL is expected to answer **distinct by DOI**, under rule 1, with two DOIs and different titles, not unclear;
  - the audit is expected to say SAME, by the medRxiv link.

  So, if both sides cite it, it's a *dangerous error REL shares with B1 and B2*, reported as such.
- **The Surgisphere papers:**
  - the *Lancet* registry paper on hydroxychloroquine is in scope;
  - the *NEJM* one (10.1056/NEJMoa2007621) is about ACE inhibitors, ARBs and statins, so it's likely out of scope.

  So at most one in-scope notice is expected. If no notice reaches the other side, the result says "notices not
  exercised".

## The two collections

- **Builders:** Tardis builds T on Tardis, and Rio Grande builds P on the Pi. Both wrote REL's rules, which the
  caveats name (V2).
- **Independence:** neither reads the other's drafts, posts about sources, or collection until both are frozen.
- **Size:** 15 to 30 sources, and 10 to 25 claim records.
  - Each record is one finding about mortality, citing **at least one** of its sources as evidence, with a locator
    (V4).
  - **The freeze check refuses** a collection outside these ranges (VA10).
- **The source fields are canonical, not the builder's choice (V2):**
  - **The title** is Crossref's `title` verbatim, or PubMed's when there's no DOI.
  - **The year** is Crossref's `issued` year, or PubMed's.
  - **The url** is the builder's, logged.
  - **The citation** includes the item's own DOI whenever one exists.
- **The freeze check:** a committed script, `engram/experiments/northstar/measure3_freeze.py`, checks every source
  against Crossref and PubMed at the freeze. It lists every deviation, and the freeze waits until there are none or each
  one is explained in the log.
- **Search, with each ship's own queries:**
  - each query is logged verbatim, with a UTC time, in `queries.log`, which names each source's url and the result it
    came from (V2);
  - the allowed sources are PubMed, Crossref, medRxiv and bioRxiv, and publisher pages;
  - each builder decides inclusion alone and writes a one-line reason per source.
- **Format:** an Atlas bundle, published with `publish_sourced`.
  - **The issuer** is `urn:superyak:peer:<the publishing peer's id>`.
  - **The policy** follows the transport's T5.
- **The freeze:** each side commits its bundle, T1 or P1, and its `queries.log`, and posts their sha256 in all hands.

## After both are frozen

1. **Copies, from the committed first publications (VA7):**
   - each side copies 3 of the other's claim records into its second publication, with `copied_from`;
   - the three are `numpy.random.default_rng(20261124).choice(n, 3, replace=False)`, over the other side's record ids
     in Python sort order (V6);
   - these 6 are the known copied pairs;
   - their sources are SAME by construction, so the audit leaves them out.
2. **Notices:** for each of its own sources that Crossref or PubMed marks retracted, a side seals a retraction notice.
3. **The audit** (below) runs on T1 and P1 and is sealed.
4. **The crossing:**
   - once Andy's pairing exists, each side sends both publications and its notices with `atlas-send`, and the receiving
     side runs `atlas-received`, `atlas-verify`, `received(..., trusted_origins=origins.json)` and `held_claims`;
   - **the run that's scored** is the one on Tardis, receiving P. The Pi's run must give identical answers, and any
     difference is reported (V4);
   - **if there's no pairing by 2026-12-06,** the methods run from the committed files in git instead, and the transport
     facts are reported as not run (VA7).

## The audit (Serenity owns it)

- **Who labels:** a fresh agent that has never seen REL's code, its rules or its output. It's given only:
  - a verbatim prompt, committed with this page;
  - the two frozen first publications, their sources without `keys` (VA5);
  - access to the external record.
- **Each source is resolved to one identity first (V5):**
  - a DOI or a PMID, with its version links from named sources: Crossref's `relation` (`is-preprint-of`,
    `has-preprint`), the medRxiv/bioRxiv API's published DOI, and PubMed's linked preprint;
  - or UNCLEAR, with its reason.
- **Then each cross source pair's label is derived mechanically from the two identities:**
  - **SAME:** one identity, or two linked as versions;
  - **UNCLEAR:** either identity is UNCLEAR, or the two are unlinked DOIs that share a normalised title or a trial
    registration number;
  - **DIFFERENT:** anything else.
- **Every identity carries its evidence:** the records looked up, the link, or the reason.
- **The seal (VA5):** a named file, `measure3-audit.json`, holds the identities, their evidence and the derived labels.
  Its sha256 goes in a commit and is posted in all hands before any method's output exists.
- **The sealed labels stand:** the primary scores them alone.
- **Serenity's spot check:** she isn't blind to the rule, so it never changes a label. She checks:
  - every SAME and every UNCLEAR label;
  - 30 DIFFERENT labels, `default_rng(20261125).choice(n, min(30, n), replace=False)` over the DIFFERENT labels sorted
    by (T id, P id) (V6).

  Her disagreements are published with their evidence. As a secondary, the primary is also reported with them applied
  (VA8).
- **Blindness:** Serenity doesn't search the question or open either collection before both freezes are posted.
- **Notice reach:** the receiving side's records whose evidence rests on the retracted identity, directly or through a
  declared copy (VA6). Reach through `supports` relations is reported apart.

## The truth, derived for claim pairs (V4)

Over T1 × P1, the primary's pairs, which hold no copies, since first publications have no provenance:
- **independent:** every cross source pair is DIFFERENT;
- **undecided:** no SAME, and at least one UNCLEAR. Left out of every score and counted;
- **same sources:** every source of each record is SAME as one of the other's;
- **overlapping:** any other pair with a SAME.

Same sources and overlapping are **not independent**.

## The methods

Each answers every T1 × P1 pair from the frozen first publications:
- **REL:** `relation()`, at commit 77ec7f88 (V9).
- **B1, exact DOI:** sources match only on equal DOI keys.
- **B2, exact DOI or strong url:** also on equal url keys where `strong_url` holds (VA3).
- **B3, keys and title (VA2):** a match on DOI, on a strong url, or on equal title and year. There's no DOI-decides rule
  and no unclear. It shows whether REL's ordered rules, not titles alone, are what win.
- **U0** always answers unknown, and **O1** always answers overlapping (V1).

For B1, B2 and B3: a record pair with every cross source pair a match is same sources; one with any match is
overlapping; and one with none is independent.

## Measures, fixed

- **Primary, the cost per method (V1, RG6),** over the decided T1 × P1 pairs:

  `cost = DE + 0.5 × FM + 0.25 × ABS`

  - **DE, a dangerous error:** answering independent on a not-independent pair, which double-counts evidence.
  - **FM, a false merge:** answering same sources or overlapping on an independent pair, which throws away a real
    confirmation. That's 0.5, since w > 1/3 is what makes unknown ever the best answer.
  - **ABS, an abstention:** answering unknown on any decided pair.
  - Any copied answer would count as not-independent.
- **The reading, against B2:**
  - **"The structure helps on real data"** only if all three hold:
    1. REL's cost is below B2's, with the **lower bound** of the 95% interval of `cost(B2) − cost(REL)` above 0;
    2. the point estimate stays above 0 with the most-shared identity's pairs dropped;
    3. REL's cost is below U0's and O1's.
  - **"Too little overlap to test" (V8)** if there are fewer than 3 shared identities, or fewer than 10 decided
    not-independent pairs.
  - **Otherwise, "no measured gain".** With a few hundred pairs, that may mean the run was too small to see one, which
    is said beside it.
- **The bootstrap (V6):** 10,000 replicates from `numpy.random.default_rng(20261126)`.
  - **Each replicate** draws T's records with replacement to T's size, then P's to P's size, separately.
  - **A pair** between a T record drawn k_t times and a P record drawn k_p times counts k_t × k_p times.
  - **The interval** is `numpy.quantile` at 0.025 and 0.975 of the difference of totals.
- **The most-shared identity (V7):** the audit identity in the most decided pairs where it holds a SAME, with ties to
  the lowest DOI or PMID. Every pair in which either record cites it is dropped, nothing else is recomputed, and the
  point estimate is judged.
- **Secondary:**
  - **for every method:** its answer × truth matrix, and the break-even abstention weight
    `(DE_B2 − DE_REL) / ABS_REL` (VA1);
  - **REL:** its unknowns with their reasons;
  - **the remaining pairs:** the undecided ones, counted; review-against-trial pairs reported apart, since identity
    isn't evidential independence (VA4); and C1's union;
  - **McNemar's exact p** on DE, labelled optimistic;
  - **the primary with Serenity's disagreements applied.**
- **Copies:** REL must answer copied on each of the 6 declared copies, and on no other cross pair of held claims (V4).
- **Notices:** `apply_notice`'s reach against the audit's, per notice.
- **Item 3's report, per direction:**
  - its counts and reasons;
  - the pairs side by side, produced by `measure3.side_by_side()`, since `compare_sourced` isn't on main.
- **The transport:**
  - rows sent, delivered, refused and retried;
  - the seconds from send to receipt;
  - the longest atlas-push write;
  - `atlas-verify` on every file.

## The analysis, pinned before the first search (V9)

`engram/experiments/northstar/measure3.py` and its tests are committed and passing before anyone searches. It holds:
- B1, B2, B3, U0 and O1;
- the truth derivation from the audit file;
- the cost, the bootstrap and the most-shared rule;
- `side_by_side()`;
- the freeze check.

They're tested on the planted stores (f51cdebd's fixtures), including:
- a hand-made audit file;
- a case where O1 would win without FM;
- the RECOVERY pair, which must come out distinct under REL.

That commit's hash is added here before the page is fixed.

## What this can't show, said before the run

- **Independence:**
  - both builders are the same model family, searching the same indexes, so "built independently" isn't independent
    sampling;
  - both wrote REL's rules (V2);
  - the auditor is the same family too, so the audit is blind to the rule but isn't an independent judge.
- **Size:** at most 900 source pairs and a few hundred claim pairs, on one question. A null is weak evidence.
- **The weights,** 0.5 and 0.25, are judgements fixed here before any data. The matrices let a reader reweigh them.

## The order of events

1. `measure3.py` and its tests are committed, and this page is approved and fixed with the hash.
2. Each side searches and builds.
3. The freeze checks pass, and both freezes are posted.
4. The copies and notices are made.
5. The audit is labelled and its seal posted.
6. Andy pairs `rio-grande` into tardis-peer, or 2026-12-06 passes.
7. The methods run.
8. The labels are published.
9. The results go into `docs/north-star.md` row 5.
