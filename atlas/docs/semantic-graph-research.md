# Semantic Graph Research — Key Findings (March 2026)

## Top Actionable Discoveries

### 1. Convergent Research Gap Map (gap-map.org)
**This is the closest existing project to Atlas.** Interactive database spanning 20 scientific fields, mapping R&D gaps and capabilities. Built with input from hundreds of scientists. It's a curated web portal, not a programmable KG — validates our concept, potential data source and partner.

### 2. KGGen (NeurIPS 2025) — `pip install kg-gen`
66% accuracy on text-to-KG extraction (vs GraphRAG 48%, OpenIE 30%). Includes entity resolution. Use for automated KG construction from papers instead of LLM hallucination.

### 3. TypeDB 3.0 (Dec 2024)
Polymorphic type system with inheritance — MathProblem, PhysicsProblem etc. as subtypes with shared + layer-specific properties. Best fit for our ontology. Constraint validation built in.

### 4. Ontology-grounded GraphRAG reduced hallucination from 63% to 1.7%
Clinical implementation that constrains LLM assertions against a formal ontology. This is the pattern we should follow.

## Recommended Stack for Production

| Layer | Tool | Why |
|-------|------|-----|
| Primary graph store | TypeDB 3.0 | Polymorphic schema, constraint validation |
| Query/GraphRAG layer | Neo4j 5.x | LLM integration ecosystem |
| Text-to-KG | KGGen | 66% accuracy, entity resolution |
| GraphRAG | Microsoft GraphRAG / LazyGraphRAG | Community detection + hierarchical summaries |
| GNN (link prediction) | PyTorch Geometric | Predict missing edges, estimate cost/timeline |
| Graph analysis | graph-tool | 40-250x faster than NetworkX |
| Scholarly data | OpenAlex API | 209M works, free, best coverage |
| Temporal versioning | TerminusDB or event-sourcing | Git-for-data model |
| Biology ontologies | OBO Foundry | Gene Ontology, Cell Ontology, ChEBI |

## Architecture Pattern: Hub-and-Spoke (not federated)

Central KG (TypeDB) holds canonical state. Workers push proposed changes as PR-like contributions. Central system validates against schema, deduplicates, merges. This avoids federation complexity while preserving institutional autonomy.

## Key Decisions

- **Build our own problem ontology** — nothing exists for "unsolved scientific problem dependencies"
- **Use OBO Foundry** for biology layers — don't reinvent molecular/cellular ontologies
- **KGGen for paper extraction** — replace LLM hallucination with structured extraction
- **TypeDB for schema enforcement** — the polymorphic type system prevents the kind of schema drift we've seen
- **Category theory for design, not runtime** — Catlab.jl for schema validation, not production infra

## Sources
Full research report with all URLs: docs/semantic-graph-research-full.md (from research agent output)
