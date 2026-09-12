# The Organization of Biomedical Research and a Federated Research System

## Principal findings

Biology and healthcare research are organized through several overlapping systems. Institutions allocate resources and responsibility; studies define questions and populations; repositories preserve particular kinds of data; ontologies name biological entities and relationships; clinical systems record care; evidence syntheses assess findings for particular decisions. None supplies a complete account of a person or a disease. The most useful architecture for connecting them must preserve the differences between those accounts while making their relationships inspectable.

The proposed foundation for Superyak is therefore **a federation of traceable observations, studies, interpretations, models, and questions, with explicit mappings between them**. A knowledge graph is one useful view of that foundation. Timelines, cohort tables, experimental matrices, narratives, and executable models are equally necessary views. This is an architectural recommendation drawn from the landscape below, rather than an established universal standard.

Three distinctions matter immediately. An article is a report of research, and may contain several studies or analyses. A database association is a qualified assertion with a history, rather than an unqualified fact. An agent's memory is an account of its experience and reasoning, rather than independent evidence for a biomedical conclusion. The system can support sustained communities of researchers without conflating those objects.

The strongest precedents are already plural: international sequence archives exchange records; clinical networks convene expertise around cases; common data models enable comparable analyses; and curation systems retain evidence types and competing classifications. Their limitations suggest a practical direction: preserve original records, record transformations, keep disagreements addressable, and let people retain control over their participation. The difficult work is maintaining these relationships over time, including when interpretations, institutions, and software change.

## Institutions, studies, and research communities

### Research activity

The familiar progression from basic science to clinical care is an incomplete map. NCATS describes translation as a spectrum with movement in multiple directions and patient involvement throughout. Basic investigation, preclinical work, clinical research, implementation, and public health interact; clinical research also includes observational and behavioral work. A disappointing clinical result can produce a new biological question, while difficulties delivering care can motivate implementation research.[^1]

Health policy and systems research adds another set of objects: organizations, incentives, financing arrangements, professional behavior, and the experience of accessing services. The WHO Alliance describes an interdisciplinary field drawing on economics, sociology, anthropology, political science, public health, and epidemiology.[^2] For complex illness, a system organized exclusively around molecular mechanisms would miss questions about disability, coordination, caregiver burden, and whether an intervention can actually be used.

An operational map has at least four interacting levels. A laboratory or clinical team performs work. A study or protocol gives that work a question, population, methods, and intended analyses. Institutions, funders, and sponsors establish resources and responsibilities. Journals, archives, registries, professional networks, and knowledge bases make selected outputs available to others. These levels should be linked explicitly: a paper's author affiliation, a study's sponsor, and the custodian of its underlying data can be different organizations.

Funding records expose part of this structure. NIH RePORT connects funded projects to outputs including publications and patents, while its disease categories support administrative reporting.[^3] Such categories are useful for finding activity, but should not become the system's ontology of disease. A grant is neither a complete description of a scientific program nor a guarantee that its data are available. Commercial research, unpublished analyses, local quality improvement, and informal collaboration are only partly visible through public records.

### Persistence and incentives

Research also depends on sustained services: accession assignment, curation, metadata repair, software maintenance, access review, training, and preservation. The Global Biodata Coalition distinguishes primary archives from resources that add interpretation and integration. Its coordination work addresses the long-term funding of this shared infrastructure.[^4] These functions deserve explicit ownership in a research system; generating more candidate findings does not automatically maintain their dependencies.

The WHO Global Observatory on Health R&D organizes information about research activity, needs, capacity, and gaps.[^5] Its existence is itself instructive: the distribution of research cannot be inferred from a literature search alone. Bibliographic coverage, funding visibility, local disease burden, and research capacity are different measurements. A high volume of accessible publications should not be interpreted as a complete account of either global knowledge or unmet need.

For a small nonprofit, the implication is selective participation in existing infrastructure. Building a durable connection to a few relevant archives, communities, and standards is a more defensible starting point than attempting to reproduce their entire curation and governance workload. That recommendation concerns institutional sustainability; it does not imply that the research community should be judged chiefly by throughput.

### Participants and expertise

Collaboration can be organized around a person rather than a database. European Reference Networks connect providers working on rare and complex conditions. Their clinical patient management system supports secure cross-border case discussion, with access mediated through healthcare providers and patient consent.[^15] This offers a precedent for assembling complementary expertise around a case, although it is not an unrestricted peer-to-peer agent network.

Patients can also set agendas and allocate resources. The Patient-Led Research Collaborative's research fund awarded $5 million in November 2022 through a patient-led process.[^16] In myasthenia gravis, the MGFA–Vitaccess registry collects recurring contributions from people living with the disease to support understanding of its course, outcomes, and trial design.[^17] These examples support treating a participant as an author of questions and interpretations, with knowledge of daily life that may be absent from institutional records.

## The global infrastructure landscape

The following map is selective. Its purpose is to show different organizational forms and points of connection, rather than rank countries or estimate their share of world research.

| Region or network | Documented example | Organizing unit and architectural lesson |
| --- | --- | --- |
| Japan, Europe, United States; international submissions | The International Nucleotide Sequence Database Collaboration links DDBJ, EMBL-EBI, and NCBI. Its scope includes sequence data and associated project and sample records. | Persistent accessions and coordinated exchange can connect geographically distributed archives. INSDC accepts openly available data; controlled human data require another route.[^6] |
| Europe | ELIXIR connects national nodes and shared life-science services. | A federation can coordinate institutions, expertise, training, and infrastructure without requiring every participant to run an identical application.[^7] |
| China | The National Genomics Data Center's 2026 resource paper distinguishes open non-human sequence archiving in GSA from controlled human omics archiving in GSA-Human. | Resource discovery must identify both scientific scope and the conditions under which data can be accessed.[^8] |
| India | The Department of Biotechnology's 2024–25 report describes the Indian Biological Data Centre at RCB and portals covering multiple biological data types, including GenomeIndia archiving. | National infrastructure can connect large research programs while maintaining local custodianship and data-access arrangements.[^9] |
| Singapore | TRUST provides a governed environment for cross-institution health research; PRECISE coordinates the National Precision Medicine effort. | Linkage, institutional relationships, and approved analytical environments are part of the research infrastructure, alongside datasets.[^10][^11] |
| Africa | Africa CDC announced the launch of AGARI on 21 November 2025 for sharing and analyzing pathogen genomic information. | Regional infrastructure is organized around public-health needs and regional participation; its existence should not be reduced to a source feeding an external index.[^12] |
| Latin America and the Caribbean | PAHO/BIREME's Virtual Health Library and LILACS connect regional health literature; Global Index Medicus complements major bibliographic indexes. | Language and regional publication channels affect discoverability. Searching only the most familiar English-language resources will miss relevant material.[^13] |
| Global clinical research | WHO's ICTRP search system aggregates records supplied by registries in its international network. | Registration, publication, and results are distinct records. ICTRP is an aggregation platform, rather than the registry in which an investigator directly registers a trial.[^14] |

These examples describe a mixture of local custody, central discovery services, shared standards, and institutional agreements. “Federated” does not by itself specify whether raw data, metadata, analysis code, or only results move between sites. Nor does it establish that an individual project has permission or funding to use a service.

Singapore's infrastructure is especially relevant to collaboration there, but proximity to TRUST or PRECISE does not establish access for a hackathon. Their published materials identify organized programs and access routes, rather than a public pool of patient records. The immediate use for this project is understanding possible partners and interfaces; no existing affiliation or data entitlement is assumed.

Public literature has a different distribution system. Europe PMC integrates articles, preprints, abstracts, full text where available, and links to related research resources.[^47] A literature connector should preserve which version and which portion of a work it actually retrieved. An abstract-only record cannot support the same methodological inspection as a full paper with supplements, and access to an article does not imply access to its underlying data.

Cohort resources introduce another boundary. UK Biobank describes access for eligible researchers through an approved research environment. Its application page, as observed for this report, says new applications are paused and an intended reopening is in late 2026.[^48][^49] This illustrates why a resource catalog needs a dated access status as well as a scientific description. A valuable dataset can be discoverable while unavailable for the present project.

## Records, concepts, and analytical representations

### Standards and their different purposes

Several established standards can describe related phenomena while preserving different meanings. Their overlap is useful, but they are not interchangeable.

| Representation | Main purpose | What should remain visible when using it |
| --- | --- | --- |
| HL7 FHIR | Exchange of clinical information through defined resources and interfaces | Source system, implementation profile, version, and the original clinical context. The R5 specification is a reference here, not a claim that every provider deploys R5.[^18] |
| OMOP Common Data Model | Consistent structure and vocabulary for observational health-data analysis | Original codes, transformation decisions, cohort definitions, and the purpose for which source data were collected.[^19] |
| CDISC SDTM | Organization of study tabulation data | Study design and the appropriate implementation guide, rather than treating study tables as a general patient record.[^20] |
| CDISC ADaM | Analysis datasets and metadata, with traceability to study data and results | The analysis population, derivations, and assumptions behind an estimate.[^21] |
| GA4GH Phenopackets | Exchange of phenotypic and associated clinical information | Onset, severity, relevant findings, and connections to other records; the packet is a structured view of a case.[^41] |
| OBO ontologies and Gene Ontology annotations | Shared biological concepts and qualified functional annotations | The ontology version, relation type, evidence category, and source supporting an annotation.[^23][^24] |
| SBML | Exchange of quantitative biological models | Model structure, parameters, interpretation, and the conditions needed for simulation.[^32] |

FHIR and OMOP illustrate a consequential distinction. A record used to deliver care and a record used to reimburse care can encode related events differently. OHDSI explicitly identifies such differences as part of the motivation for its common model.[^19] Harmonization makes comparable analysis possible; it should also retain enough history to explain why a value was mapped, excluded, or reinterpreted.

Biological data introduce additional structure. The Human Cell Atlas separates metadata used for integration, richer contextual metadata, and cell annotations. Its documentation explains that inadequate correction can make similar cells appear different, while excessive correction can erase biological variation.[^22] Integration therefore changes what can be inferred. It is an analytical operation with assumptions, rather than a neutral step that merely makes files fit together.

Cell labels also have authorship. HCA's cell-annotation schema records ontology terms, synonyms, and broader categories for particular annotation sets.[^46] A system should be able to retain an investigator's original labels alongside a later alignment. Disagreement may indicate a mistaken annotation, a difference in resolution, or a biological distinction; the mapping alone does not decide which explanation is correct.

### Identity and time

The recommended identity rule is to preserve identifiers in their issuing namespaces. A hospital patient identifier, a laboratory specimen accession, a study participant identifier, and a repository sample accession have different scopes. Even identical strings are not enough to merge them. A correspondence should be a separately attributable assertion with its method, evidence, validity period where relevant, and review history.

Clinical observations need at least two temporal perspectives: when something occurred or was measured, and when it was recorded or learned. Uncertain dates should remain uncertain intervals or expressions. A correction should create a new version and identify what it supersedes, so that the system can reconstruct both the current account and what a researcher previously knew.

This is a proposed design requirement, not a claim that all existing standards implement it identically. It also applies to missingness: “not assessed,” “not documented,” “explicitly absent,” and “unknown” should not collapse into one false value. Units, reference ranges, specimen conditions, and measurement methods should remain attached wherever they are available. An unmapped narrative should survive extraction, especially when no structured field adequately captures the experience described.

## Evidence, interpretation, and disagreement

Biomedical knowledge resources already make distinctions that an agent system should retain. ClinVar archives classifications submitted by different organizations and can expose disagreement between them.[^25] Its review status summarizes aspects of submission and review, including expert-panel involvement; it is not a numerical probability that a variant interpretation is true.[^26] The useful object is the classification with its submitter, condition, evidence, date, and status.

Gene Ontology's evidence codes distinguish categories such as experimental support, computational inference, and author statements.[^24] These are statements about how an annotation is supported. Converting all annotations into identical graph edges would discard a central part of their meaning.

Open Targets provides a particularly clear warning against overinterpreting scores. Its target–disease association scores aggregate heterogeneous evidence with a heuristic; the documentation explicitly says they are not confidence scores. Direct evidence and evidence propagated through disease relationships can also contribute differently.[^27] A low score may reflect limited investigation, while a high score does not by itself establish that an intervention will help a particular person.

For clinical intervention questions, Cochrane's GRADE guidance evaluates a body of evidence for a specified outcome across domains including bias, inconsistency, indirectness, imprecision, and publication bias.[^28] That is a different task from assigning quality to a gene annotation or evaluating a mechanistic simulation. The architecture needs several forms of evidence assessment, each with a stated purpose.

The proposed evidence unit is consequently larger than a sentence-level claim. An **evidence packet** should connect a research question to a study or analysis, its population and conditions, its result, the supporting source locations, and an assessment of what the result does and does not establish. A paper may yield several packets. Several papers may report the same underlying study. A database may repeat a result from those papers.

Dependency tracking is essential here. Five sources repeating an analysis of one cohort are not five independent replications. Agent agreement is likewise not independent corroboration when agents share the same evidence, model, or prior summaries. The system should retain links between overlapping populations, reused datasets, derivative analyses, and summaries. Where independence is unknown, that uncertainty should be recorded rather than resolved by counting citations.

Disagreement should remain attached to the object being disputed: identity, measurement, annotation, effect estimate, causal explanation, applicability, or priority. A review can then improve one layer without silently rewriting all the others. For example, correcting an extraction error need not invalidate the original paper, while discovering a shared cohort may change an evidence synthesis without changing either study's reported estimate.

## Federation, access, and authority

Federation has several independent dimensions: discovery, custody of data, permission decisions, execution of analyses, and exchange of conclusions. The European Genome-phenome Archive makes some of these distinctions concrete. Its metadata model includes datasets, policies, and data access committees as objects.[^35] Federated EGA connects repositories with central coordination and catalog services; it is not a fully symmetric mesh in which every participant possesses every record.[^36]

GA4GH Beacon provides a way to discover biomedical data through structured queries.[^37] The Data Use Ontology describes permitted-use categories that can support matching and access decisions.[^38] Neither discovering a dataset nor finding a compatible use label grants access by itself. FAIR principles also explicitly allow authentication and authorization; reusable data need not be openly downloadable.[^39]

The CARE Principles add collective benefit, authority to control, responsibility, and ethics to discussions of Indigenous data governance.[^40] Their particular context matters: they should not be treated as a generic consent checkbox. They demonstrate why the identity of the people or community entitled to decide cannot always be represented by a single administrator account.

For Superyak, the recommendation is local ownership with explicit, scoped sharing and discoverable access routes. A participant may share a question, a redacted observation, an assessment, or a result without publishing an entire record or memory store. Administration of one peer should not imply authority over all peers. Transport identity, source attribution, and scientific credibility should be evaluated separately: an authenticated sender can still be mistaken.

The system should support a person declining a request, correcting a record, pausing participation, or exporting their own work. Revocation requires realistic semantics: it can prevent future authorized access and request deletion of copies, but cannot make a recipient forget material already seen. These are proposed product behaviors and trust boundaries, rather than a claim of legal compliance or a mechanism already implemented across the project.

## A mathematical foundation

The following model is a design proposal. It combines established representations where their assumptions fit, without claiming that one mathematical object already captures biomedical knowledge.

### Typed objects and qualified relations

Let the system's records form typed collections, with explicit relationships between them. An illustrative disjoint union is:

`O = Persons ⊔ Samples ⊔ Observations ⊔ Studies ⊔ Datasets ⊔ Runs ⊔ Claims ⊔ Assessments ⊔ Models ⊔ Questions ⊔ Decisions ⊔ Sources ⊔ Mappings ⊔ Memories ⊔ …`.

Each object is a record about something, rather than the thing itself. A person object is a scoped reference, not necessarily a globally resolved identity. An observation records an account of a measurement or experience; a claim is an interpretation with scope. Models, questions, decisions, and memories retain their distinct purposes. Additional types should cover protocols, actors, custodians, and access rules as their relationships are specified.

A useful qualified relation has the form:

`r = (subject, predicate, object, context, evidence, asserting_actor, version)`.

The relation is itself addressable. Context may include organism, tissue, population, experimental conditions, time, and outcome definition. Evidence points to packets and source locations; the asserting actor may be a person, organization, software process, or agent. Richer n-ary observations can be represented as objects with typed roles rather than forced into a single binary edge.

Biolink provides a precedent for typed biomedical associations and distinctions among direct observation, statistical association, prediction, logical entailment, and other knowledge levels.[^30][^31] Such distinctions belong in interchange contracts. A path through a graph can identify a promising connection without being a valid chain of causal inference.

### Multiple projections

The same underlying objects should support different projections: a clinical timeline, a study table, a molecular network, a source-dependency graph, and a narrative account. These views need not contain identical information. Each should declare its inputs, transformation, omissions, and intended interpretation.

For a view transformation `f: X → Y`, store the transformation version and a loss description `L_f`. If a return mapping `g: Y → X` exists, the meaningful check is whether `g(f(x))` preserves a specified set of invariants. An exact round trip is not always possible. The system should state which identifiers, dates, relations, and source references are preserved rather than claiming unrestricted equivalence.

Ontology alignment should similarly be represented as data. SSSOM requires a justification for mappings, distinguishes mapping relations, and can explicitly represent an entity for which no corresponding term was found.[^29] For this system, “no adequate mapping” is a useful result. It preserves a boundary at which a later researcher may improve the representation.

### Provenance and recursive memory

Use a directed acyclic graph for immutable artifact versions and their material derivation: source snapshot, extraction run, evidence packet, synthesis, and revision. A feedback process produces new versions, rather than a cycle in that version-level dependency graph. The biological model itself can still contain cycles, and a community's conversations can revisit previous ideas repeatedly.

W3C PROV supplies entities, activities, agents, derivation, and provenance bundles, including ways to describe the provenance of provenance.[^33] Workflow Run RO-Crate adds a practical packaging precedent for computational runs, their inputs, outputs, software, and workflow details.[^34] These structures are suitable for connecting a cluster result back to the exact records and transformations that produced it.

Memory of memory can then be represented without erasing layers. A source supports an observation; an agent remembers considering that observation; a later reflection examines that earlier memory. The reflection's lineage should connect to both the memory and the source, while preserving the difference between them. Repeated reflection can change an agent's interpretation, but does not create a new independent observation of the biological world.

### Context and formal models

Contexts can sometimes be partially ordered by restriction: a statement about a defined subgroup has a narrower scope than one about a containing population. But the set of all scientific contexts need not have a unique least upper bound or greatest lower bound. Calling this a mathematical lattice would require constructing and testing those operations, not relying on a project name.

Category-theoretic or sheaf-based formulations may eventually help characterize composable mappings or local accounts that do not reconcile globally. Their value should be tested against a concrete problem, such as detecting incompatible phenotype mappings or explaining why two study views cannot be joined. An initial typed model with explicit partial mappings can expose the needed structure before choosing that formalism.

Statistical and mechanistic models should remain executable objects with named assumptions. A probability model for an effect estimate, a causal model for an intervention, and a dynamical model of a biological process answer different questions. SBML already supports an important class of quantitative biological models, while explicitly not attempting to be a universal modeling language.[^32] An agent should be able to propose or compare models without treating every relationship in the shared graph as an equation.

Confidence is best represented initially as several assessments: extraction fidelity, source reliability, study limitations, relevance to the question, uncertainty in an estimate, and applicability to the case. Calibrated probabilities can be added where there is a specified target and evaluation data. A single global score would otherwise hide why two conclusions differ.

## Superyak, aDNA, and research communities

### Existing foundations

The local proof of concept already exercises useful mechanisms: separate Engram stores, explicit audience-bound sharing, source-aware Atlas proposals, recorded model calls, and recovery without repeating completed work.[^43] Its deliberately narrow article task tested the base structure. It was not intended as a complete mathematical organization of research.

The aDNA adapter preserves source identities and supports bounded local project access and lattice projections.[^44] These are useful foundations for adapters and interchange. They do not yet establish complete semantic round trips, cryptographic trust in every source, live peer application exchange, or a multiuser clinical application. The Stampede launcher likewise supplies scheduling and recovery mechanisms, with live Intel inference and cross-node research transport still requiring work and measurement.[^45]

### Recommended responsibilities

The architecture should distinguish four responsibilities. Participant peers hold their records, private memories, and sharing decisions. Research resources provide versioned evidence and access routes. Compute services execute bounded analyses and model requests. Participant-facing views explain findings, disagreements, and next questions in an accessible form. A peer may perform several responsibilities, but none should be assumed merely from network reachability.

Biological lighthouses could organize expertise around molecular immunology, neuromuscular physiology, clinical trajectories, pharmacology, methods, and lived experience. These would be perspectives on shared objects, with their own questions and working memories. Cross-perspective tasks are necessary because a division by specialty can otherwise reproduce the fragmentation the system is meant to address.

Agent identities should be independent of inference replicas. Many persistent researchers can share a model service while retaining different histories, responsibilities, and relationships. A small group using a more capable model can coordinate and critique, but its conclusions should remain reviewable proposals. More model capacity does not turn a coordinator into an independent source of biological evidence.

Task contracts should expand beyond single-article extraction. Useful assignments include reconstructing a study's design, comparing outcome definitions, identifying dataset overlap, proposing a mechanistic explanation, searching for contrary evidence, testing a mapping, assessing applicability, and tracing a correction through prior conclusions. Each task should specify its question, admissible inputs, expected output type, and unresolved assumptions. Agents need room to follow useful questions, while their published conclusions retain evidence boundaries.

### Standards at the boundaries

For one complex case, prioritize source-preserving uploads and provider-specific record ingestion, with FHIR where supported and a Phenopacket view where useful. Preserve narrative and unmapped fields. Add OMOP when a concrete cohort analysis requires it; adopting a common model does not require forcing every object into it at the start.

Use existing biological identifiers and ontology versions, with Biolink-style qualified relations and SSSOM-style mappings. Package substantial analyses with provenance compatible with PROV and Workflow Run RO-Crate. Maintain the existing private/shared memory distinction, and add dependencies from published findings to source versions and analysis runs. These are proposed extensions, not completed changes to the repository.

The display should begin with a person's question and show what is known, what remains uncertain, where accounts differ, and what new evidence would help. Source and transformation details should be available on demand. Screens, speech, and interaction burden should be designed around participants' actual abilities; the underlying graph need not become the main user interface.

## A worked research path for myasthenia gravis and complex disease

This is an illustrative workflow using public or synthetic material, not an account of an identified patient. NINDS describes myasthenia gravis as an autoimmune disorder affecting transmission at the neuromuscular junction, including mechanisms involving acetylcholine-receptor or MuSK antibodies.[^42] That establishes several relevant biological perspectives, while leaving open what any particular person's unresolved difficulties require investigating.

**The initiating object is a question.** For example: “Which parts of this person's functional variation are explained by existing evidence, and which remain unresolved?” Record who asked, why it matters, the time horizon, and what kind of answer would be useful. Preserve the person's own account alongside the formal question. A research question about function need not begin as a search for a gene.

**The case becomes a versioned timeline.** Keep each reported symptom, assessment, laboratory result, exposure, and relevant event attached to its source and temporal uncertainty. Distinguish a clinical diagnosis from an agent's hypothesis and a reported experience from a measurement. Represent missing assessments explicitly. Produce a structured phenotype view without deleting details that do not map cleanly.

**Parallel inquiries connect the case to different kinds of knowledge.** One group reconstructs the chronology and searches for inconsistencies. Another examines relevant physiological or immunological explanations. A methods group identifies which studies actually measured comparable outcomes. A participant-oriented group checks whether those outcomes address the person's priorities. Their outputs should connect to the same case questions without being forced into consensus.

**Evidence packets connect studies to hypotheses.** A trial registration supplies planned study information; a paper supplies reported analyses; a dataset description identifies the population and measurements that may be available. The packet records relevant inclusion criteria, outcome definitions, effect estimates where available, and limitations. If a paper's methods cannot be inspected, that becomes a limit on the packet rather than a detail invented by an agent.

**Models propose discriminating observations.** Competing explanations can state what they would predict, which existing observations they explain poorly, and what information would distinguish them. A simulation or reanalysis should run only when the necessary data and assumptions are explicit. The desired output is a defensible research dossier for discussion, not an automatic treatment decision inferred from a graph path.

**The dossier remains revisable.** A corrected date, new result, changed patient priority, or reinterpreted study should identify affected findings and reopen the relevant questions. Some conclusions may remain unchanged; others may become unsupported. The system should preserve that history so participants can understand both the current account and why it changed.

## Evaluation and development priorities

The first representation experiment should compare the existing article-focused approach with study-centered evidence packets and a case-question workflow on matched public or synthetic tasks. Hold retrieved source passages and evaluation questions constant where the comparison is intended to isolate memory or representation effects. Include conflicting reports, uncertain dates, an unmappable concept, overlapping datasets, and a later correction.

Evaluate several outcomes separately:

| Property | Observable test |
| --- | --- |
| Identity preservation | Different namespaces remain distinct; justified correspondences are retained without silent merges. |
| Evidence fidelity | Findings point to supporting source locations and do not exceed the available text or analysis. |
| Study dependence | Repeated reports of one study are recognized; apparent corroboration is not inflated by duplicated evidence. |
| Semantic preservation | A view records lost or unmapped information and passes its stated round-trip invariants. |
| Disagreement | Conflicting interpretations remain discoverable with their reasons and contexts. |
| Revision | A source correction identifies affected outputs and supports rebuilding or qualifying them. |
| Participant usefulness | People can identify the answer, uncertainty, and relevance without reconstructing the entire graph. |
| Continuity and autonomy | A peer can pause, recover, export its work, and decline a sharing request without losing unrelated work. |

Known injected errors can provide objective checks. Scientific adequacy also needs assessment independent of the same model that generated the findings, including domain review where the question warrants it. Reviewer disagreement should itself be recorded. Agreement scores alone can reward conformity and conceal shared mistakes.

Development can proceed in three overlapping streams: refine the object and mapping model locally; perform useful public-source case-domain research; and benchmark the actual cluster inference and transport setup. The continuing community should remain separate from controlled experimental copies so that methodological comparison does not repeatedly erase its history.

For an allocation week, prepare reproducible source bundles and tasks before access, run parallel comparisons within measured capacity, and checkpoint artifacts in a form that returns to participant peers. The durable output should include an evidence dossier, reusable mappings, dependency records, and unresolved questions, as well as performance measurements. Agent count is a capacity parameter; it is not the measure of whether the system helped anyone understand a difficult problem.

## Scope and unresolved questions

This report reflects sources reviewed as of 12 September 2026. It combines official standards, infrastructure documentation, organizational publications, and local implementation records. These establish documented purposes and mechanisms; they do not independently measure adoption, reliability, or scientific benefit. Some source pages are undated, and their inclusion does not imply that every described capability was operationally tested.

The geographic coverage is selective and does not constitute a census. Commercial R&D, local-language literature beyond the examples included, routine laboratory work, and informal clinical collaboration are underrepresented. Detailed economic comparisons and jurisdiction-specific legal requirements are outside scope. The China resource paper and India's annual report support narrowly bounded descriptions from accessible indexed material; they were not audited in full.

For the proposed system, the main unresolved questions are the actual case's research priorities, which record sources can be connected, how collaborators want to work, and which analyses have adequate data. Stanley's private clinical plans were not available for this report. These gaps do not prevent work on public evidence, synthetic cases, representation fidelity, or memory experiments. They do limit claims about a finished clinical workflow and the usefulness of any particular model population.

## Sources

[^1]: National Center for Advancing Translational Sciences. [Translational Science Spectrum](https://ncats.nih.gov/about/about-translational-science/spectrum). Undated official overview.
[^2]: WHO Alliance for Health Policy and Systems Research. [What is health policy and systems research?](https://ahpsr.who.int/what-we-do/what-is-health-policy-and-systems-research-%28hpsr%29). Undated official overview.
[^3]: National Institutes of Health. [Research Portfolio Online Reporting Tools](https://www.report.nih.gov/). Official funding and research-output information portal.
[^4]: Global Biodata Coalition. [Global Core Biodata Resources](https://globalbiodata.org/what-we-do/global-core-biodata-resources/). Resource definitions and preservation rationale.
[^5]: World Health Organization. [Global Observatory on Health Research and Development](https://www.who.int/observatories/global-observatory-on-health-research-and-development). Official observatory; constituent datasets have their own reporting periods.
[^6]: International Nucleotide Sequence Database Collaboration. [About INSDC](https://www.insdc.org/about-insdc/). Official membership, scope, exchange, and access description.
[^7]: ELIXIR. [Who we are](https://elixir-europe.org/about-us/who-we-are). Official institutional overview.
[^8]: National Genomics Data Center, China National Center for Bioinformation. [Database resources of the National Genomics Data Center, China National Center for Bioinformation in 2026](https://academic.oup.com/nar/article/54/D1/D28/8373952). *Nucleic Acids Research* 54(D1), 2026, D28 onward. Repository distinctions used from indexed article text; full publisher page unavailable.
[^9]: Government of India, Department of Biotechnology. [Annual Report 2024–25](https://dbtindia.gov.in/sites/default/files/DBT%20Annual%20Report%202024-25.pdf). IBDC section; accessible indexed report text. Descriptions refer to that reporting period.
[^10]: TRUST. [About us](https://www.trustplatform.sg/about-us/). Singapore health research platform; page updated 14 July 2026.
[^11]: Precision Health Research, Singapore. [About PRECISE](https://www.npm.sg/about-us/). Official program overview; page updated 8 June 2026.
[^12]: Africa Centres for Disease Control and Prevention. [Africa CDC Launches AGARI, a Continent-Wide Genomic Data Platform to Strengthen Outbreak Response](https://africacdc.org/news-item/africa-cdc-launches-agari-a-continent-wide-genomic-data-platform-to-strengthen-outbreak-response/). 21 November 2025.
[^13]: Pan American Health Organization. [Tips and major resources](https://www.paho.org/en/tips-and-major-resources). Official guide to regional and global health-information resources, including LILACS and Global Index Medicus.
[^14]: World Health Organization. [International Clinical Trials Registry Platform](https://www.who.int/ictrp/en/). Official platform overview.
[^15]: European Commission. [European Reference Networks](https://health.ec.europa.eu/rare-diseases-and-european-reference-networks/european-reference-networks_en) and [Work of the ERNs](https://health.ec.europa.eu/rare-diseases-and-european-reference-networks/european-reference-networks/work-erns_en). Official network and case-management descriptions.
[^16]: Patient-Led Research Collaborative. [Patient-Led Research Fund](https://patientresearchcovid19.com/projects/patient-led-research-fund/). Fund awards announced November 2022; subsequent project updates are later.
[^17]: Myasthenia Gravis Foundation of America. [MG Patient Registry](https://myasthenia.org/living-with-mg/after-your-diagnosis/mg-patient-registry/). Official description of the Vitaccess Real MG Registry collaboration.
[^18]: Health Level Seven International. [FHIR Overview](https://fhir.hl7.org/fhir/overview.html). FHIR R5, version 5.0.0.
[^19]: Observational Health Data Sciences and Informatics. [Data Standardization](https://www.ohdsi.org/data-standardization/). OMOP CDM rationale and analytical purpose. OHDSI's ATLAS software is distinct from this project's Atlas workbench.
[^20]: Clinical Data Interchange Standards Consortium. [Study Data Tabulation Model](https://www.cdisc.org/standards/foundational/sdtm). Official SDTM overview.
[^21]: Clinical Data Interchange Standards Consortium. [Analysis Data Model](https://www.cdisc.org/standards/foundational/adam). Official ADaM overview.
[^22]: Human Cell Atlas. [Metadata](https://data.humancellatlas.org/metadata). Integration, contextual metadata, annotations, and schema evolution.
[^23]: OBO Foundry. [OBO Foundry Principles](https://obofoundry.org/principles/fp-000-summary.html). Shared ontology principles, identifiers, scope, and versioning.
[^24]: Gene Ontology Consortium. [Guide to GO evidence codes](https://geneontology.org/docs/guide-go-evidence-codes/) and [GO annotations](https://www.geneontology.org/docs/go-annotations/). Official annotation and evidence documentation.
[^25]: National Center for Biotechnology Information. [ClinVar: Introduction](https://www.ncbi.nlm.nih.gov/clinvar/intro/). Submission, classification, and archival model.
[^26]: National Center for Biotechnology Information. [ClinVar review status](https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/). Official criteria and interpretation.
[^27]: Open Targets. [Target–disease associations](https://platform-docs.opentargets.org/associations). Association aggregation, direct and indirect evidence, and score limitations.
[^28]: Schünemann HJ, Higgins JPT, Vist GE, and colleagues. [Chapter 14: Completing “Summary of findings” tables and grading the certainty of the evidence](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-14). *Cochrane Handbook*, version 6.5 (2024); chapter updated August 2023.
[^29]: Mapping Commons. [The SSSOM data model](https://mapping-commons.github.io/sssom/1.0/spec-model/). Version 1.0 documentation; mappings, justifications, predicates, and unmapped entities.
[^30]: Biolink Model contributors. [Biolink Model](https://biolink.github.io/biolink-model/). Official biomedical knowledge-graph model documentation.
[^31]: Biolink Model contributors. [KnowledgeLevelEnum](https://biolink.github.io/biolink-model/KnowledgeLevelEnum/). Official distinctions between kinds of knowledge represented in associations.
[^32]: SBML community. [What is SBML?](https://sbml.org/documents/what-is-sbml/). Scope and purpose of Systems Biology Markup Language.
[^33]: Moreau L, Missier P, editors; W3C Provenance Working Group. [PROV-DM: The PROV Data Model](https://www.w3.org/TR/prov-dm/). W3C Recommendation, 30 April 2013.
[^34]: Research Object community. [Workflow Run RO-Crate](https://www.researchobject.org/workflow-run-crate/). Official profiles and links to the 2024 methods publication.
[^35]: European Genome-phenome Archive. [EGA metadata schema](https://ega-archive.org/submission/metadata/ega-schema/). Study metadata and dataset, policy, and access-committee objects.
[^36]: European Genome-phenome Archive. [Federated EGA](https://ega-archive.org/about/projects-and-funders/federated-ega/). Current overview of the network and central services.
[^37]: Global Alliance for Genomics and Health. [Beacon API](https://www.ga4gh.org/product/beacon-api/). Official discovery standard overview.
[^38]: Global Alliance for Genomics and Health. [Data Use Ontology](https://www.ga4gh.org/product/data-use-ontology-duo/). Official permitted-use terminology overview.
[^39]: GO FAIR Foundation. [FAIR Principles](https://www.gofair.foundation/fair-principles). Includes A1.2 on authentication and authorization where necessary.
[^40]: Carroll SR and colleagues. [The CARE Principles for Indigenous Data Governance](https://datascience.codata.org/en/articles/dsj-2020-043). *Data Science Journal* 19, 43, 2020. Principles used from the indexed article abstract.
[^41]: Global Alliance for Genomics and Health. [Phenopackets](https://www.ga4gh.org/product/phenopackets/). Official standard overview and clinical scope.
[^42]: National Institute of Neurological Disorders and Stroke. [Myasthenia Gravis](https://www.ninds.nih.gov/sites/default/files/2025-05/myasthenia-gravis.pdf). Patient-information booklet; indexed text, antibody mechanism discussion on printed page 3. Used for general biology, not current treatment recommendations.
[^43]: Superyak project. [Atlas research proof of concept](../atlas-research-poc.md). Local implementation documentation at commit `3d44f2f`, 12 September 2026; mechanism evidence, not independent scientific validation.
[^44]: Superyak project. [aDNA compatibility](../adna-compatibility.md). Local adapter and projection documentation; implementation introduced at commit `b01c475`.
[^45]: Superyak project. [Stampede3 deployment](../stampede3-deployment.md). Local launcher documentation; prepared execution path rather than a measured cluster deployment.
[^46]: Human Cell Atlas. [Cell Annotation Metadata](https://data.humancellatlas.org/metadata/cell-annotation). Official annotation-set schema description.
[^47]: Europe PMC. [About Europe PMC](https://europepmc.org/about). Official description of literature types and links to related resources; live corpus counts omitted.
[^48]: UK Biobank. [Access to UK Biobank data](https://www.ukbiobank.ac.uk/about-us/how-we-work/access-to-uk-biobank-data/). Official access model and research environment description.
[^49]: UK Biobank. [Apply for access](https://www.ukbiobank.ac.uk/use-our-data/apply-for-access/). Application pause and intended late-2026 reopening, observed 12 September 2026; this status is time-sensitive.
