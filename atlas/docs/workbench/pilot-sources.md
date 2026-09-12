# Cell-fate pilot: sources and boundaries

This deliberately selected methods-and-limitations demonstration spans 2016–2024. It is not a systematic review of current methods, comprehensive coverage of cell fate, an experimental result, or an expert adjudication. Metadata and the indicated primary sections were checked on 2026-09-07. No abstracts or article full text are bundled. The JSON contains concise scoped paraphrases, source locators and explicit limitations.

The two questions and five approach groupings are editorial proposals. All eight claims are `source_reported`; all 20 relations and both experiments are `proposed`. Shared facets and citations do not create prerequisite edges. There are no reviewed prerequisites in the pilot.

## Primary publications and claim trace

| Primary publication | Claim IDs | Primary locator | Boundary carried into the record |
| --- | --- | --- | --- |
| Weiler et al. (2024), [CellRank 2: unified fate mapping in multiview single-cell data](https://www.nature.com/articles/s41592-024-02303-9). DOI: 10.1038/s41592-024-02303-9 | `c-cellrank`, `c-markov` | Abstract; Results, “A modular framework for studying state-change trajectories,” kernels and Markov assumption | Multiview inference and a gradual, memoryless transition model; inferred lineage-correlated genes are not established causal regulators by these claims. |
| Weinreb et al. (2020), [Lineage tracing on transcriptional landscapes links state to fate during differentiation](https://pmc.ncbi.nlm.nih.gov/articles/PMC7608074/). DOI: 10.1126/science.aaw3381 | `c-lineage-bias`, `c-larry-limit` | Abstract, sister-cell fate biases; Discussion, LARRY limitations | Mouse hematopoiesis observations and the reported assay's one-cell-cycle resolution/culture-transplantation boundaries; not universal restrictions on transcriptomics or lineage tracing. |
| Pratapa et al. (2020), [Benchmarking algorithms for gene regulatory network inference from single-cell transcriptomic data](https://pmc.ncbi.nlm.nih.gov/articles/PMC7098173/). DOI: 10.1038/s41592-019-0690-6 | `c-beeline` | Abstract, precision-recall, early precision and benchmark comparison | Moderate performance pertains to the evaluated algorithms and reference networks, not every current GRN method. |
| Dixit et al. (2016), [Perturb-Seq: Dissecting Molecular Circuits with Scalable Single-Cell RNA Profiling of Pooled Genetic Screens](https://pmc.ncbi.nlm.nih.gov/articles/PMC5181115/). DOI: 10.1016/j.cell.2016.11.038 | `c-perturbseq` | Summary; Results, pooled combinatorial CRISPR screens with scRNA-seq readout | Measured expression responses to tested perturbations in immune cells/cell lines do not establish every affected gene as a direct binding target. |
| Schiebinger et al. (2019), [Optimal-Transport Analysis of Single-Cell Gene Expression Identifies Developmental Trajectories in Reprogramming](https://pmc.ncbi.nlm.nih.gov/articles/PMC6402800/). DOI: 10.1016/j.cell.2019.01.006 | `c-wot` | Summary; “Modeling developmental processes with optimal transport” | Couplings inferred from sampled mouse reprogramming populations are not directly observed ancestry for every cell pair. |
| Gayoso et al. (2024), [Deep generative modeling of transcriptional dynamics for RNA velocity analysis in single cells](https://www.nature.com/articles/s41592-023-01994-w). DOI: 10.1038/s41592-023-01994-w | `c-velovi` | Abstract; Results, “veloVI identifies insufficiently observed or steady-state dynamics” | Velocity uncertainty is conditional on the model/data; it does not independently establish lineage or causal regulation. |

The source records in [cell_fate.json](../../workbench/data/cell_fate.json) retain the verified full titles, author strings, issue years, primary URLs and DOI citations. veloVI's journal issue year is 2024; its online publication was in 2023. The Waddington-OT record points to the main article, not the separate correction notice (DOI 10.1016/j.cell.2019.02.026). No equations from that notice are bundled.

The primary-section verification used publisher/PMC pages and readable primary excerpts, with Europe PMC metadata/abstract text when automated PMC retrieval encountered a browser challenge. Metadata accessibility is not treated as a scientific assessment. The pilot makes no new claim requiring broader literature coverage.

## Editorial interpretation and proposed tests

The relations connect reported capabilities or limitations to possible approaches. For example, `c-markov` challenges the proposed dynamics approach by identifying an assumption to examine; it does not refute the entire method. The lineage-bias result motivates testing prediction against held-out clonal outcomes. The GRN benchmark motivates comparing nominated links with matched-state perturbation responses. These connections are our proposals and carry `proposed` status.

`e-heldout-fates` asks what disagreement between predictions and held-out clonal outcomes would imply for applicability. `e-perturb-regulators` asks whether candidate links anticipate matched-state perturbation responses. Both include a result that could change the interpretation and unresolved design constraints. Neither is a completed experiment or a detailed laboratory protocol.

No domain expert has reviewed this pilot. The next step is the [source-tracing and usefulness evaluation](evaluation.md), including a check that the model/assay boundaries remain clear when a user follows a proposed relation.
