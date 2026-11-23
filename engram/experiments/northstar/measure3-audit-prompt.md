# Measure 3's audit: the labeller's prompt, verbatim

This is the whole prompt given to the fresh labelling agent, as `PREREG-test5-measure3.md` requires ("a verbatim
prompt, committed with this page"). Serenity owns the audit and wrote it. It names no matching rule of the project and
no method's output, so the labeller stays blind to them. Only the three paths in angle brackets are filled in at
dispatch, each to a frozen file whose sha256 was posted in all hands.

---

You are labelling bibliographic identities for a pre-registered study. Your labels become the study's ground truth,
so follow these instructions exactly, and record evidence for everything.

**What you may read:**
- the two frozen collections at `<T first publication path>` and `<P first publication path>`. Each lists sources with
  `id`, `title`, `url`, `year` and `citation`;
- the notices file at `<notices path>`. Each notice names one retracted source by its collection and source id;
- the external record, and only these services:
  - the Crossref REST API (`api.crossref.org/works/...`);
  - NCBI E-utilities for PubMed (`eutils.ncbi.nlm.nih.gov`), and the PMC ID converter;
  - the medRxiv and bioRxiv API (`api.biorxiv.org/details/...`);
  - publisher landing pages reached from a DOI.

Read nothing else: no other file on this machine, no code, no chat or station message. Don't guess or use background
knowledge in place of a lookup. If the external record doesn't settle a question, the answer is UNCLEAR, with the reason.

**Step 1: one canonical identity per source.** For every source in both collections:
- **its DOI,** whenever one exists:
  - take it from the citation or url if present, and confirm it resolves on Crossref;
  - if none is given, search Crossref by title and year, and accept a DOI only if the record's title matches (case
    and punctuation ignored) and its year matches.
  - A PMID maps to its DOI through PubMed's article ids.
- **its PMID** otherwise, from PubMed;
- **UNCLEAR** otherwise, for example a news page, a dataset with neither identifier, or a title matching no record.
  Write the reason.

Lowercase every DOI.

**Step 2: version classes.** Two identities are versions of one work only when the external record links them by name.
The links that count:
- Crossref's `relation` field, `is-preprint-of` and `has-preprint`;
- the medRxiv or bioRxiv API's `published` DOI for a preprint;
- PubMed's link between a preprint record and its published article.

A version class is the transitive closure of these links. Name each class by its lowest DOI in string order, or its
lowest PMID if it has no DOI. An identity with no links is a class of one. UNCLEAR identities have no class (`null`).

**Step 3: unclear pairs.** For every pair of one T source and one P source whose classes are both known and *different*,
mark the pair unclear if either holds:
- the two records have the same title (case and punctuation ignored) and the same first author's family name;
- they share a trial registration number, from PubMed's DataBank list or Crossref's `clinical-trial-number`.

A shared generic title with different first authors is *not* unclear. Write the reason for each unclear pair.

**Step 4: derived labels.** For every pair of one T source and one P source:
- **SAME** if both are in one class;
- **UNCLEAR** if either identity is UNCLEAR, or the pair is an unclear pair from step 3;
- **DIFFERENT** otherwise.

**Step 5: notice reach.** For each notice, list the records of the *other* collection whose evidence cites a source in
the same class as the retracted source. If you can't establish the retracted source's class, write that.

**Output:** write one JSON file, `measure3-audit.json`, with exactly these keys:

```json
{
  "identities": {
    "T:<source id>": {"canonical": "doi:<doi>" | "pmid:<pmid>" | null, "class": "<class name>" | null,
                      "evidence": [{"service": "...", "request": "<the exact URL>", "fields": {"...": "..."}}],
                      "reason": "<why UNCLEAR>" | null},
    "P:<source id>": {"...": "..."}
  },
  "classes": {"<class name>": {"members": ["T:<id>", "P:<id>"], "links": [{"from": "...", "to": "...", "via": "..."}]}},
  "unclear_pairs": [["T:<id>", "P:<id>"]],
  "unclear_reasons": {"T:<id>|P:<id>": "<same title and first author, or the shared registration>"},
  "labels": {"T:<id>|P:<id>": "SAME" | "DIFFERENT" | "UNCLEAR"},
  "notice_reach": {"<notice id>": {"retracted": "<T or P>:<id>", "class": "<class name>" | null,
                                   "reached_records": ["<record id>"], "reason": "<if the class is unknown>" | null}},
  "requests": ["<every external URL you requested, in order>"]
}
```

`labels` holds every T × P source pair. Check before you finish that every label follows from steps 1 to 4 exactly, and
that `unclear_pairs` holds only pairs with two different known classes.
