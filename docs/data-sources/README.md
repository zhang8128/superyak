# Research source import preparation

The dashboard now provides **Research & data**. Create a source of type
**Papers and selected source records**, choose **Select source document**, and
select the prepared `peer-import.json` described below. Review the three records,
then choose **Import privately**. The source page provides pause/resume, provenance,
import receipts, and **Start evidence review**, which creates a private cited
draft for manual review or the existing selected Gemma assistance. Importing does
not run a model or grant training or publication rights.

The [source comparison](../reports/2026-09-13-standard-medical-research-sources.md)
recommends PubMed discovery, rights-resolved PMC full text, and Europe PMC
enrichment for the first medical/biotech evidence-review corpus.
[catalog.json](catalog.json) describes 16 sources and their access, identity,
reuse and update boundaries. It is a planning catalog, not executable server
configuration. [import-profile.json](import-profile.json) records the measured
three-paper import and its exact document hash.

## Prepared files

The retained local package is in the repository's ignored directory:

```text
.worktrees/research-sources/.engram/research-import-20260913/
  peer-import.json         # Ready for existing selected-source import
  source-create.json       # Exact registration body for a named collection
  import-request.json      # Exact import body for the newly created source
  source-manifest.json     # Article licenses, identifiers, hashes and use grants
  acquisition.json         # Exact URLs, byte lengths and retrieval timestamp
  evidence-blocks.jsonl    # 129 paragraph blocks with source/hash references
  annotation-queue.jsonl   # Three unannotated review tasks; no invented answers
  raw/                    # Original API metadata and full JATS XML bytes
  prepare.py              # Offline reconstruction from retained inputs
  verify-import.py        # Isolated backend import/replay check
  verification.json       # Eight passing checks; no live-account import
```

The documents are a case study (`PMC12682587`), a clinical review
(`PMC12620256`), and an in-vitro neuromuscular-junction study (`PMC12817423`).
Each retained canonical PMC XML matches its version-1 metadata's MD5 and also has
a locally computed SHA-256. CC BY 4.0 was checked in both metadata and article XML.
Version 1 is the particular object checked, not an assertion that it is the newest
or preferred scholarly version. Europe PMC XML is retained separately because its
bytes differ from PMC's canonical objects.

The 91,519-byte `peer-import.json` has SHA-256:

```text
561c3a479a54a86cb029b4d0274513ca898d8eef167564dac6af8977b0814e7c
```

It contains attributed abstract/body prose and separately identified figure/table
caption blocks. Superscripts and subscripts retain explicit `^{...}` / `_{...}`
notation, including scientific exponents. Nested table contents are excluded from
prose; table layout and formula markup remain in the raw XML. Four focused checks
cover scientific notation, nested-block separation, real article cell counts and
retention of a figure-caption limitation exactly once. This is an extraction, not
a new clinical interpretation. Full source bytes, license
notices and extraction details are retained. `research-import` is the local aDNA
adapter namespace; it does not assert that PMC is a signed peer or that the
transformation was authored by the paper's authors.

## Import into an account

Use **Import selected source document** in the peer's selected-source records
view and choose `peer-import.json`. That existing interface imports into the
account's default selected-source collection. To use a named source instead,
create the `selected-records` source described in `import-profile.json`, then send
the prepared `import-request.json` body to its
`/api/data-sources/{id}/imports` endpoint. `source-create.json` is the exact
registration body; `import-request.json` contains all three records and the
stable request ID. It uses version 1 for a newly created source. Use the source's
current version when importing into an existing source. The route requires the
account's session, same-origin header and CSRF token, as described in
[the API](../../peer/API.md#backend-data-sources).
Credentials belong in the local session, not in the catalog or import document.
Repeating the same successful request ID and content returns its original receipt.
Imported sources stay private to the account; public sharing uses the existing
separate sharing flow.

The staged batch already passed an actual import into disposable local state,
exact content/provenance round trip, repeat import, pause behavior, and denial to
another account. Preparing the package did not import it into anyone's live demo
account. Source registration does not start a feed, fetch job, or research worker.

## Prepare evidence-review supervision

The annotation queue has `supervised_answer: null`, unassigned splits and
`training_ready: false`. Fill it with reviewed claims, supporting paragraph IDs,
reported numbers, study-design limits, and explicit uncertainty. Convert reviewed
items into the [tuning dataset format](../../tuning/README.md#prepare-a-clinical-or-biotech-dataset)
only after grouping related papers, versions and trials into one split.

The source manifest permits this local reading workflow. Local training, shared
training and adapter publication are separate false grants until the operator
records the intended use; a CC BY article does not automatically switch those
product controls on. Actual clinical and confidential biotech sources remain
supported by the tuning system. The first source choice simply starts with public
literature while real dataset and compute details are being assembled.

No labeled training set or trained adapter is claimed for this three-paper
fixture. Stampede3 access details are expected later; the prepared launcher stays
unsubmitted.
