# Standard medical research sources and source-grounded evidence review

The strongest foundation for a medical and biotechnology research app combines a biomedical publication catalog, article text with documented reuse terms, and carefully reviewed supervision for extracting and comparing evidence. PubMed and Europe PMC provide discovery and identifiers; PMC supplies structured full text through approved services; Crossref supplies publication relationships and correction metadata. These sources serve different purposes. A record being searchable, freely readable, or downloadable does not by itself establish permission to redistribute its text or include it in a particular training release.

The recommended first LoRA should improve **evidence-review behavior**: identify supporting passages, extract study design and outcomes, distinguish reported findings from inference, and answer with appropriate citations and uncertainty. Current scientific facts should remain retrievable from dated sources. Evidence Inference 2.0 and BioASQ provide the closest established supervision patterns; PubMedQA and SciFact support complementary evaluation. Their benchmark licenses must be examined separately from the rights in the articles and abstracts they reference.

This starting point uses public literature. Actual clinical research and biotechnology work remain in scope, including later authorized confidential datasets. Their access, training, sharing, and publication conditions must be recorded individually. An open-source application and peer-to-peer operation do not require every source corpus to be publicly redistributed.

The current backend accepts private selected-source documents. A one-time staging bridge has now prepared and replay-tested three public papers; production external connectors and a scheduled harvesting service have not been established by this work. The proposed source definitions are recorded in the [source catalog](../data-sources/catalog.json) and [import profile](../data-sources/import-profile.json). The recommendations below describe the next implementation, with technical acceptance evidence separated from scientific evaluation.

## Publication infrastructure

The first publication sequence should be PubMed discovery, PMC text acquisition, and Europe PMC enrichment, with Crossref status checks. OpenAlex and direct preprint feeds add value after those paths preserve identity, versions, and rights correctly.

| Source | Primary role | Preferred access | Main qualification |
|---|---|---|---|
| PubMed | Biomedical citation catalog, MeSH, publication types | E-utilities; annual baseline and daily XML updates | Abstract copyright remains relevant |
| PMC | Structured article text and supporting material | Current AWS objects and approved article APIs | Rights attach to article versions and components |
| Europe PMC | Discovery, identifier mapping, preprints, citation context | REST JSON and approved full-text services | Searchable full text is not necessarily redistributable |
| Crossref | DOI relationships, publisher metadata, corrections | REST works and DOI lookups | Missing metadata is not evidence of missing restrictions |
| OpenAlex | Citation, institution, author, and topic graph | REST; quarterly public snapshot | Metadata license does not cover underlying PDFs |
| bioRxiv/medRxiv | Early research and publication transitions | Official details/pubs APIs; optional S3 TDM | Preserve preprint status, versions, and author licenses |

PubMed contains citations and abstracts rather than a general full-text corpus. For a small topic collection, ESearch followed by batched EFetch is sufficient. At larger scale, NLM provides an annual XML baseline followed by daily files containing new, revised, and deleted citations. Load updates in numerical order and replace revised or deleted records. Pin the actual DTD; the 2026 baseline README references the 2025-01-01 schema.[^1]

E-utilities allows three requests per second without a key and ten per second with a key by default. Batch requests and Entrez History reduce traffic; NCBI recommends overnight Eastern-time or weekend scheduling for large jobs. Identify the application appropriately and expose the required NCBI copyright/disclaimer notice. NLM explicitly warns that abstracts can contain copyrighted material.[^2]

Correction handling belongs in the initial importer. PubMed's `CommentsCorrections` links identify errata, retractions, expressions of concern, and other relationships through `RefType` and associated citations. Retraction notices and retracted articles are different records. Preserve both and their relationship so retrieval can explain a changed evidence state.[^3]

### PMC after the August 2026 migration

PMC's article distribution changed materially in August 2026. Its August 26 completion notice states that legacy article-dataset files on FTP and Cloud were removed during the week of August 24. The legacy OA package-discovery web service also retired. New imports should not depend on `oa_bulk`, `oa_package`, deprecated archives, or the former commercial/noncommercial folder layout. PMC FTP still supplies the identifier cross-reference file; PubMed's separate baseline distribution was not abolished.[^4]

The current world-readable bucket is `s3://pmc-oa-opendata` in `us-east-1`, accessible through HTTPS or unsigned S3 requests without retrieval charges or login. Each article-version prefix contains individual objects: JSON metadata, JATS XML, extracted text, and permitted PDF, media, or supplementary files. The new distribution does not provide compressed bulk article packages.[^5]

Metadata includes PMCID, PMID, DOI, version, license code, manuscript/OA flags, retraction status, and file URLs with MD5 digests. Checked objects use JSON booleans for status flags. Store the raw response as well as normalized fields; documentation wording and observed types can differ. Preserve SHA-256 for local content identity and compare the provider's MD5 against the exact object named by its metadata.[^6]

PMC version numbers need interpretation. A larger suffix can reflect deposit processing order rather than the preferred scholarly version; author manuscripts and publisher versions may coexist. Content and metadata can change inside a version without a new suffix. The daily inventory lags continuous updates and is retained for 30 days. Version removals have no separate notification, making inventory reconciliation necessary. Discover available versions, inspect their metadata, and retain a dated selection decision instead of assuming `.1` exists or the highest suffix is always best.[^5][^6]

PMC's OA subset includes multiple Creative Commons licenses, custom terms, and article types, including corrections and retractions. Non-CC author manuscripts generally provide XML/text for text mining and uses consistent with applicable copyright law; their PDF/media/supplements are not generally included in the article dataset. A `TDM` license code is distinct from CC BY. Author-accepted manuscripts have undergone peer review, while preprints have not.[^7]

### Europe PMC, Crossref, OpenAlex, and preprints

Europe PMC's REST API supports JSON/XML search with `idlist`, `lite`, and `core` results. Use `core` for richer rights and publication metadata and cursor pagination for traversal. Preserve `(source,id)` because MED records and PPR preprints occupy separate namespaces. Record publication, indexing, update, and retrieval dates separately; late indexing otherwise makes date-only harvesting incomplete.[^8]

Europe PMC still documents its own bulk services, including weekly full-text metadata and monthly identifier mappings. These should not be confused with the retired NCBI PMC article FTP. Its copyright policy restricts systematic downloading to approved APIs and bulk services. The team confirmed free commercial API use and per-IP limits in 2024, but a current numeric ceiling was not unambiguously verified. Conservative requests, response-aware backoff, and bounded downloads are appropriate initial settings.[^9]

Crossref adds publisher-deposited DOI relationships, licenses, corrections, and Retraction Watch information. Bibliographic facts and Crossref-generated data are broadly reusable; supplied abstracts retain author or publisher copyright. For incremental synchronization, use bounded index-date windows and cursors, caching results and treating missing status/license fields as unknown.[^10]

A July 21, 2026 Crossref announcement supersedes older rate tables. Public/polite single-record requests allow five/ten per second; list requests allow **one/three per second**. Polite access uses a valid contact email, and limits can aggregate by email. A live anonymous list response confirmed one request per second. Read current rate/concurrency headers and back off on 429 responses.[^11]

OpenAlex is useful for broader citation and entity connections. Current documentation permits anonymous basic queries, provides a free key with a $1 daily usage budget, caps request rate at 100 per second, and limits `per_page` to 100. Free snapshots are quarterly; paid services add daily snapshots and update filters. Record snapshot manifests and reconcile deleted or merged IDs. OpenAlex metadata is CC0, but its full-text service explicitly grants no additional rights in downloaded PDFs.[^12]

Direct bioRxiv/medRxiv feeds should preserve DOI, explicit version, posting date, license, and published-article relationship. The bioRxiv-hosted details API currently documents 30 records per page, whereas the medRxiv mirror says 100; a live details query returned 30. Advance using the response's cursor/count rather than a fixed assumption. New articles use DOI prefix **10.64898 from December 1, 2025**; older 10.1101 DOIs remain unchanged.[^13]

Both servers offer monthly processed XML/PDF delivery through requester-pays S3 buckets requiring an AWS account. Their TDM access does not independently authorize rehosting articles or derivatives. Keep preprints visibly distinguishable from accepted/published versions, and consult the author's license for downstream use. No guaranteed current numeric API rate was verified.[^14]

## Task datasets for the first adapter

The most useful training resources already separate a question or claim from supporting evidence. They should supply task structure and reviewed labels, while article text enters through its own provenance and rights checks.

| Dataset | Task contribution | Recommended position | Rights issue to retain |
|---|---|---|---|
| Evidence Inference 2.0 | Intervention–comparator–outcome evidence and effect direction | First supervision candidate | Repository MIT does not automatically license external article text |
| BioASQ task b | Questions, snippets, exact and ideal answers | Complementary evidence-grounded QA | Benchmark CC BY 2.5; linked articles have separate terms |
| PubMedQA | Abstract-context reasoning and yes/no/maybe answers | Compact evaluation; optional training | Repository grant and underlying abstracts are distinct |
| SciFact | Scientific claims and sentence-level support/refutation | Evidence/citation evaluation | Claims, database contents, and code have different licenses |
| EBM-NLP | Participant, intervention, outcome extraction | Optional after licensing is resolved | Corpus license remains unresolved |

**Evidence Inference 2.0** is the closest task match. Its paper reports 12,616 intervention–comparator–outcome prompts from 3,346 articles. The task identifies evidence and classifies the reported direction as significantly decreased, no significant difference, or significantly increased. Preserve evidence offsets, invalid-prompt indicators, and annotation disagreements. An abstract-only condition is available, but it should be evaluated as a separate information condition.[^15]

The repository includes an MIT license, while the separately hosted v2.0 archive contains article text and no license member was found during inspection. Therefore article licenses must be resolved individually before inclusion in a distributable text snapshot. Several prompts from one article or trial are correlated examples. Use article and trial-family identity when splitting, not prompt-level randomness.[^16]

**BioASQ task b** adds question answering with source documents, snippets, exact answers, and ideal answers. The official 2026 listing gives 5,729 questions for training release 14b; the test listing remained TBA when checked. Downloads require registration. BioASQ specifies CC BY 2.5 and refers users to NLM source conditions. Pin one release and compare question/article IDs across years instead of concatenating overlapping annual packages. Supplied gold snippets and independently retrieved context must remain separate evaluation conditions.[^17]

**PubMedQA** is compact and useful for controlled reasoning experiments. The original release describes 1,000 expert-labeled PQA-L examples, 61,200 unlabeled PQA-U examples, and 211,300 artificial PQA-A examples. Artificial title-derived examples are not expert evidence reviews. The official split reserves 500 PQA-L examples for testing; the remaining 500 form ten folds, each with 450 training and 50 development examples. Conclusions used as long answers must not leak into evaluation context.[^18]

**SciFact** contains 1,409 scientific claims and a 5,183-abstract corpus, with sentence-level evidence rationales. The documented test labels are not public. Its official component licensing is unusually explicit: claims/annotations are CC BY 4.0, S2ORC-derived abstracts are ODC-By 1.0, and code is Apache-2.0. Preserve this attribution chain; a database license is not proof of unrestricted rights in every article's expression. Its claim-verification task is medically relevant but narrower than systematic evidence review.[^19]

**EBM-NLP** provides 4,993 abstracts with participant, intervention, and outcome labels. Training aggregates crowd annotations; test labels come from medical professionals. Some spans overlap, so forcing mutually exclusive labels would discard information. The original repository has no root corpus license, and its model-code license does not resolve dataset rights. Archive inspection also found no license member. Keep this resource optional until the corpus terms are established.[^20]

## Adjacent clinical and biotechnology sources

ClinicalTrials.gov is the highest-priority structured complement to literature. API v2 exposes study search and single-study JSON, with pagination and bulk options. NCT identity connects registered design, interventions, prespecified outcomes, posted results, and linked publications. Comparing registration with published reporting is useful for evidence review. Missing posted results mean missing evidence, not a negative treatment result.[^21]

Its terms require attribution, current data handling, the date ClinicalTrials.gov processed a record, and disclosure of modifications. They also acknowledge third-party copyright. Record version and processed date should accompany each trial snapshot; separate protocol PDFs need their own terms. Group registry records and related papers as one study family for evaluation.[^22]

ClinVar and NCBI Gene support variant/gene interpretation and normalization. ClinVar's documented website, download, and read-API release cycle is weekly. Full XML carries more complete information than its partial VCF summaries. Preserve accession/version, assembly, condition, submitter, assertion date, evidence, review status, and conflicts. A single-submitter assertion and an expert-panel classification must not collapse into an unattributed “pathogenic” fact. Gene reports connect stable IDs, species, symbols, and transcript/protein accessions.[^23]

UniProt is valuable for biotechnology workflows because it connects proteins, organisms, functions, evidence, and literature through a REST API and identifier mapping. Its copyrightable database components are CC BY 4.0. Preserve entry/release versions and evidence attribution; reviewed-entry status does not imply every annotation rests on direct experiment. GEO is better introduced for specific expression-study questions: retain Series/sample relationships and study design, then analyze matrices with appropriate computational methods. NCBI places no restrictions of its own on molecular-data reuse but does not transfer possible submitter rights.[^24]

## Provenance and permission model

The import contract should separate the scientific object from the local record carrying it. A paper has publisher identifiers and versions; a peer import has an account owner, import identifier, revision, and receipt. Mapping one to the other must not imply that the publisher runs a peer or signed a local record.

| Record group | Required information |
|---|---|
| Identity | Source namespace, upstream ID, PMID/PMCID/DOI/NCT where applicable, version, relationships |
| Acquisition | Exact request/object URL, retrieval time, source update date, HTTP status, byte count, provider checksum, local SHA-256 |
| Rights | License URI and text evidence, version/component scope, attribution, exclusions, permission decisions |
| Transformation | Parser/version, raw-object hash, normalized-text hash, section/paragraph IDs, offsets, transformation history |
| Scientific context | Article/study type, evidence status, corrections, study-family links, population and experimental system |
| Training lineage | Annotation provenance, supporting spans, reviewer state, split, dataset release, generation history |

Metadata indexing, text storage, local training, shared training, corpus distribution, and adapter publication should be separately expressible. An initial CC0/CC BY selection rule is a practical starting policy, not a claim that all other licenses forbid training. Creative Commons explains that copyright exceptions can operate independently of licenses and that training, model outputs, and redistribution require distinct analysis.[^25]

Rights and evidence status can change after ingestion. Retain the original snapshot while recording later corrections, withdrawals, license evidence, and superseding versions. Retrieval should expose the selected version and current known status. Training manifests should record the review cutoff and excluded records. Text from the same paper obtained through different services must not share a byte hash unless it actually matches.

## Curriculum and evaluation

The proposed curriculum begins with extraction from a supplied document: population or experimental system, intervention, comparator, outcomes, design, and supporting spans. The next stage compares results across passages, preserves numerical denominators and units, and separates reported statistical significance from claims of equivalence or absence of effect. A final stage synthesizes several sources, reports conflicts, and identifies what evidence is missing.

Evidence Inference supplies a useful first task; BioASQ broadens question types. Carefully authored examples from rights-resolved papers can teach distinctions that public benchmarks underspecify: case reports versus comparative studies, animal or in-vitro findings versus human outcomes, protocol intentions versus observed results, and reviews versus their underlying studies. Dataset-derived answers should remain distinguishable from human-authored and model-generated supervision. Generated paraphrases do not become independent evidence or gold labels.

Start with a modest human-reviewed pilot and compare the adapter with the installed base model before expanding volume. Keep retrieval and answer generation independently assessable:

| Condition | Comparison | What it isolates |
|---|---|---|
| Gold context | Base model versus adapter with identical reviewed passages | Extraction and reasoning from sufficient evidence |
| Retrieved context | Base model versus adapter with identical retrieval pipeline | End-to-end performance, including missing or irrelevant context |
| Missing/conflicting context | Both models with deliberately incomplete or inconsistent evidence | Unsupported inference and calibrated uncertainty |

Measure supporting-span accuracy, correct citation targets, supported-claim rate, effect direction, numerical fidelity, and behavior when evidence is insufficient. Report retrieval recall separately from answer quality. Inspect errors by study type and evidence source; an overall average can conceal poor handling of laboratory research or clinical trials. Reviewers should judge fidelity to the supplied source separately from whether the source itself supports a strong scientific conclusion.

Freeze evaluation membership before annotation, paraphrasing, or training. Deduplicate across literature imports, Evidence Inference, BioASQ, PubMedQA, and SciFact using identifiers and text similarity. Group article versions, preprints, trial reports, and cohort-related publications. For reviews, audit overlap with their underlying studies. Chunk-level splits otherwise let near-identical evidence appear on both sides.

Public benchmarks may already have appeared in a foundation model's training data. That is a contamination uncertainty, not proof that a particular selected model saw them. Report familiar benchmark results alongside a freshly authored held-out study set, disclose date cutoffs and matching methods, and avoid describing either as contamination-free without evidence. No current evaluation here establishes clinical or biotechnology performance.

## Verified import fixture and implementation sequence

The staging sample contains three public CC BY 4.0 papers whose licenses were checked in JATS and PMC metadata:

| Document type | Identifiers | Source |
|---|---|---|
| Case report | PMC12682587; PMID 41368056 | [10.1002/ccr3.71604](https://doi.org/10.1002/ccr3.71604) |
| Review | PMC12620256; PMID 41255784 | [10.3389/fneur.2025.1678151](https://doi.org/10.3389/fneur.2025.1678151) |
| Biotechnology research | PMC12817423; PMID 41387932 | [10.1186/s40360-025-01056-1](https://doi.org/10.1186/s40360-025-01056-1) |

The sample is a technical fixture, not a representative corpus or a scientific quality assessment. No private patient uploads were used. PMC version 1 was checked for each paper; latest-version status remains unknown. Europe PMC fullTextXML bytes differed from the PMC objects named by metadata, so canonical PMC version-1 XML was acquired separately. Each provider MD5 matched its corresponding object, and local SHA-256 hashes record exact acquired bytes.[^26]

The prepared selected-source document contains three records and 129 prose/caption evidence blocks. Scientific superscripts and subscripts retain explicit notation; figure/table captions are separate blocks and table cells are not flattened into prose. Four focused extraction checks cover those boundaries, including real article cell counts and a caption limitation retained exactly once. Eight checks passed against an isolated instance of the actual backend: schema/hash validation, authenticated registration, atomic import, exact content/provenance round-trip, idempotent replay, paused-source denial of new imports, replay of completed imports while paused, and denial to another account. These checks establish import behavior; they do not evaluate a model. No live-demo import or model call was required for this preparation.[^26]

The local identifiers use `adna:research-import:pmc/PMCID` as an adapter namespace, with real publisher URLs and author attribution retained separately. The annotation queue has null supervision. No gold labels, training examples, or trained adapter were created; current fixture permissions leave local/shared training and adapter publication disabled. The [source-management and staging guide](../data-sources/README.md) explains operator-led import and links raw objects, provenance, and replay receipts.

Implementation should proceed in four bounded stages. First, stabilize acquisition adapters using the catalog and import profile: bounded queries, response-driven pagination, rights checks, raw snapshots, exact hashes, and repeatable private imports. Complete the refresh and version-reconciliation behavior before scheduling ongoing collection.

Second, create the review workspace around the annotation queue. Reviewers should select supporting spans, correct extracted study metadata, record uncertainty, and approve explicit supervision. Keep article license acceptance separate from evidence-quality judgments. Freeze evaluation families before accepting related examples into training.

Third, run a small Evidence Inference–style adapter experiment on cleared text and reviewed annotations. Record the base-model identifier, tokenizer, adapter configuration, dataset manifest, seeds, and evaluation outputs. Compare with the unchanged base model under the gold-context and retrieval conditions above. Additional compute capacity is a separate operational decision, not a prerequisite for establishing this data contract.

Fourth, expand into registered-trial comparisons, protein/variant grounding, and direct preprint monitoring where measured errors justify them. Add a scheduler only with source-specific update windows, retries, removal handling, and observable receipts. Release decisions should use the completed rights and evaluation manifests rather than download counts or a successful model request.

## Sources

Sources were checked on September 13, 2026. Counts describe the cited releases; service policies and live query results are dated observations. Local staging evidence is available in the private workspace bundle, while the external references below are public primary sources.

[^1]: NLM, [Download PubMed Data](https://pubmed.ncbi.nlm.nih.gov/download/), January 14, 2025; [2026 baseline README](https://ftp.ncbi.nlm.nih.gov/pubmed/baseline/README.txt).
[^2]: NCBI, [E-utilities introduction, usage requirements, and copyright](https://www.ncbi.nlm.nih.gov/books/NBK25497/).
[^3]: NLM, [CommentsCorrections, 2025-01-01 DTD](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/el-CommentsCorrections.html).
[^4]: PMC, [FTP Service](https://pmc.ncbi.nlm.nih.gov/tools/ftp/), August 26, 2026 completion notice; NCBI, [distribution transition](https://ncbiinsights.ncbi.nlm.nih.gov/2026/02/12/pmc-article-dataset-distribution-services/), February 12, 2026.
[^5]: PMC, [Accessing Article Datasets Using AWS](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/), August 2026 documentation.
[^6]: NLM, [PMC AWS technical README](https://pmc-oa-opendata.s3.amazonaws.com/README.txt); PMC, [Cloud Service](https://pmc.ncbi.nlm.nih.gov/tools/cloud/).
[^7]: PMC, [Article Datasets](https://pmc.ncbi.nlm.nih.gov/tools/textmining/) and [Author Manuscripts](https://pmc.ncbi.nlm.nih.gov/about/authorms/), August 2026.
[^8]: Europe PMC, [RESTful Web Service](https://europepmc.org/RestfulWebService) and [reference guide](https://dev.europepmc.org/docs/EBI_Europe_PMC_Web_Service_Reference.pdf), version 6.9.0.
[^9]: Europe PMC, [Bulk downloads](https://europepmc.org/downloads), [Copyright](https://europepmc.org/copyright), and [team API response](https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/cZLnV1JhCj8), December 11, 2024.
[^10]: Crossref, [Metadata retrieval and licensing](https://www.crossref.org/documentation/retrieve-metadata/) and [API synchronization guidance](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/).
[^11]: Crossref staff, [Refining REST API limits](https://community.crossref.org/t/refining-rest-api-limits-for-improved-stability-and-reliability/16137), July 21, 2026.
[^12]: OpenAlex, [Authentication](https://help.openalex.org/api/authentication/), [Pricing](https://help.openalex.org/access/pricing/), [Sync](https://help.openalex.org/access/sync/), August 17, 2026, and [Fulltext licensing](https://help.openalex.org/access/fulltext/), August 11, 2026.
[^13]: bioRxiv, [API summary](https://api.biorxiv.org/); medRxiv, [API summary](https://api.medrxiv.org/); openRxiv, [Preprint DOI policy](https://connect.medrxiv.org/news/2025/11/18/preprint_dois), November 18, 2025.
[^14]: bioRxiv, [TDM resources](https://www.biorxiv.org/tdm); medRxiv, [TDM resources](https://www.medrxiv.org/tdm).
[^15]: DeYoung et al., [Evidence Inference 2.0](https://aclanthology.org/2020.bionlp-1.13.pdf), 2020, including Table 13.
[^16]: Evidence Inference authors, [repository](https://github.com/jayded/evidence-inference), [MIT license](https://raw.githubusercontent.com/jayded/evidence-inference/master/LICENSE), and [v2.0 archive](https://evidence-inference.ebm-nlp.com/v2.0.tar.gz); inspected repository revision `a661e8c14f973398380c8865cf2f27a535aaaf6d`.
[^17]: BioASQ, [Official datasets and terms](https://participants-area.bioasq.org/datasets/), 2026 task-b listing.
[^18]: Jin et al., [PubMedQA](https://aclanthology.org/D19-1259.pdf), 2019; authors' [repository](https://github.com/pubmedqa/pubmedqa), [split script](https://raw.githubusercontent.com/pubmedqa/pubmedqa/master/preprocess/split_dataset.py), and [license](https://raw.githubusercontent.com/pubmedqa/pubmedqa/master/LICENSE); revision `1cbae8e92f72f20c8d3747cbb3bf5bc53554d997`.
[^19]: Wadden et al., [Fact or Fiction](https://aclanthology.org/2020.emnlp-main.609.pdf), 2020; AI2, [SciFact release](https://github.com/allenai/scifact) and [component licenses](https://github.com/allenai/scifact/blob/master/LICENSE.md); revision `68b98a56d93e0f9da0d2aab4e6c3294699a0f72e`.
[^20]: EBM-NLP authors, [README](https://github.com/bepnye/EBM-NLP), [repository tree](https://api.github.com/repos/bepnye/EBM-NLP/git/trees/master?recursive=1), and [v2 archive](https://raw.githubusercontent.com/bepnye/EBM-NLP/master/ebm_nlp_2_00.tar.gz); revision `43a4a1ea3f0a21cfb8820c040b843dfaf66192d0`.
[^21]: NLM, [ClinicalTrials.gov API migration](https://clinicaltrials.gov/data-about-studies/api-migration).
[^22]: NLM, [ClinicalTrials.gov terms](https://clinicaltrials.gov/about-site/terms-conditions), verified against its [served page bundle](https://clinicaltrials.gov/chunk-BMYXEWAI.js).
[^23]: NCBI, [ClinVar access](https://www.ncbi.nlm.nih.gov/clinvar/docs/access/), [downloads](https://www.ncbi.nlm.nih.gov/clinvar/docs/downloads/), [review status](https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/), and [Gene reports](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/command-line-tools/using-dataformat/gene-data-reports/).
[^24]: UniProt, [License](https://www.uniprot.org/help/license/), December 18, 2024, and [API](https://www.uniprot.org/help/api), December 17, 2025; NCBI, [molecular-data policies](https://www.ncbi.nlm.nih.gov/home/about/policies/); GEO, [programmatic access](https://www.ncbi.nlm.nih.gov/geo/info/geo_paccess.html) and [disclaimer](https://www.ncbi.nlm.nih.gov/geo/info/disclaimer.html).
[^25]: Creative Commons, [Using CC-licensed works for AI training](https://creativecommons.org/using-cc-licensed-works-for-ai-training-2/), linked from its May 15, 2025 legal primer.
[^26]: Local verification, retained `source-manifest.json`, `peer-import.json`, and `verification.json`, September 13, 2026; exact workspace location and use are documented in the [operator guide](../data-sources/README.md#prepared-files). Staging records are private technical evidence, not publisher-signed artifacts.
