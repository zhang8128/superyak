# Atlas research workbench: first usable slice

Direction approved in conversation on 2026-09-07: connect evidence, explanations, questions and possible experiments to understand what would make biological capabilities possible. Initial case: cell-fate prediction and gene-regulatory inference. This first release is a local, inspectable workbench; broad automated ingestion and funding allocation follow evaluation of this release.

## User outcome

Open a self-contained HTML workbench, search/filter questions by several facets, inspect alternative approaches, follow scoped claims to primary publications, and see proposed experiments. Import saved Atlas notes as proposals without promoting old confidence/cost/dependency estimates. Record corrections or withdrawals and regenerate the view. A CLI provides the same records as JSON and an explicitly limited prerequisite-reachability query.

## Global Constraints

- Python >=3.11; Python standard library only at runtime; pytest for development.
- New code lives in `workbench/`; never import the legacy `atlas/` runtime.
- Existing Atlas code, saved vault files, and Docker data are read-only inputs and must not be modified.
- SQLite workbench databases have an application/schema marker; refuse unrelated existing databases before writing.
- All scientific content is local; no implicit network calls, background workers, paid models, services, or telemetry.
- Categories are multiple annotations and never determine identity, dependency direction, or research priority.
- Import is atomic and idempotent for identical IDs/content; conflicting IDs fail without partial changes.
- Every source-reported/reviewed claim and every reviewed scientific relation has explicit source evidence with a locator.
- Proposed, source-reported, reviewed and withdrawn remain visibly distinct. Reviewed requires a named reviewer and timestamp; imported legacy records remain proposed.
- Dependency traversal uses reviewed, active relations only, reversing `requires` and following `enables`; it reports reachability, not scientific importance. Withdrawn endpoints and relations are excluded.
- HTML must escape all supplied content, reject unsafe URL schemes, work without external assets, and provide accessible search/filter controls.
- A bundled pilot is a small literature-backed demonstration, not comprehensive coverage, expert adjudication, or a clinical recommendation.

## Portable bundle and identity

Version 1 JSON: `schema_version: 1`, `title: str`, `sources: list`, `items: list`, `relations: list`. Unknown keys should fail clearly rather than silently disappear, except optional export-only `history` which may be preserved or explicitly ignored on import with documentation. Stable IDs do not contain required category prefixes.

Source fields: `id`, `title`, `url` (http/https), `year` (integer), `citation` (string). No article full text is required or bundled.

Item fields: `id`, `kind` (`question|approach|claim|experiment`), `title`, `summary`, `status` (`proposed|source_reported|reviewed|withdrawn`, default proposed), `context` (string-to-string mapping, default empty), `facets` (string-to-list-of-strings mapping, default empty), `evidence` (list, default empty), `provenance` (string-to-string mapping, default empty), `reviewed_by`, `reviewed_at` (strings, default empty). Evidence entries are `{source_id, locator, note}`; source and locator must be nonempty and source must exist in the resulting database. An evidence note is a scoped paraphrase, not a blanket endorsement.

Relation fields: `id`, `subject`, `predicate`, `object`, `status`, `rationale`, `context`, `evidence`, `reviewed_by`, `reviewed_at`. Same status/default/evidence rules as items. Allowed predicates: `addresses`, `supports`, `challenges`, `informs`, `tests`, `uses_method`, `part_of`, `requires`, `enables`. Both endpoints must exist; self-dependencies are rejected. `requires` and `enables` additionally require nonempty context and rationale when reviewed. Do not infer relations from tags or shared citations.

At least the following semantic endpoint rules apply: `addresses` is approach→question; `supports/challenges` is claim→claim/approach; `informs` is claim→question; `tests` is experiment→claim/approach/question; `uses_method` is approach/experiment→approach; `part_of` is question→question; `requires/enables` may connect any non-claim items but require scope as above. No automatic equivalence or merge operation.

## Store and CLI interfaces

`Store(path, create=False)` is a context manager. Absent path fails unless create=True; create=True may open an existing marked workbench but never initialize an unrelated database. `import_bundle(bundle: dict) -> dict` returns inserted counts by record kind; `export_bundle() -> dict` returns all current records and audit history. `search(text='', facets=None, kind=None) -> list[dict]` matches title/summary and facet intersections without duplicating IDs. `duplicates() -> list[list[dict]]` finds punctuation/Unicode-normalized exact-title candidates across all facets, without merging. `unlocks(item_id: str) -> list[dict]` returns reachable active items excluding the start, deduplicated and cycle-safe. `set_status(record_id, status, reason, actor) -> None` changes an item or relation after applying all target-state invariants and appends a timestamped audit event; no silent resurrection or automatic promotion. A record ID is globally unique across items/relations so the update is unambiguous. Invalid status changes must roll back.

Use `python -m workbench --db PATH init|import BUNDLE|search QUERY|show ID|duplicates|unlocks ID|review ID --status STATUS --reason TEXT --actor NAME|export|import-vault VAULT|render --output FILE`. `search` supports repeated `--facet axis=value` and `--kind`; JSON commands write machine-readable stdout, errors go to stderr with nonzero exit. `init` is the only command allowed to create a missing DB. `render` produces one HTML file atomically; reject an output path pointing at the database or a source bundle. Existing output can be replaced only if it has this renderer’s document marker; refuse all other existing files. Reject symlink output paths. No HTTP server is needed.

## Legacy import

Read only `VAULT/Nodes/**/*.md`. Parse the existing frontmatter/title/summary format without executing YAML. Use stable IDs derived from the old node ID in a `legacy:` namespace. All imported items have kind question and status proposed, with original layer/domain as facets, old ID/path/SHA256 as provenance, and a visible warning that legacy node kind and claims have not been reassessed. Do not import edges, papers, confidence tiers, costs or timelines as trusted fields. Reject malformed notes with a clear path and roll back the import; identical reruns do nothing. No local path is rendered as an executable link. Copying or deleting source notes is out of scope.

## Pilot, presentation and evaluation

Ship `workbench/data/cell_fate.json`: two questions, at least three approaches, at least eight scoped source-reported claims, at least two proposed experiments, and at least six distinct primary publications with verified title/URL/year. Every claim has context, a source locator and an explicit limitation where relevant. At least one limitation/challenge relation must be visible. Pilot relations remain proposed or source-reported unless a real named expert review occurs; don't manufacture reviewed dependencies to make the graph busy.

The page leads with questions and their connected approaches/claims/experiments; record detail shows status, scope, facets, evidence links, incoming/outgoing relations and review history. Multiple facets refer to one record. Search/filter has a clear no-results state and keyboard-operable controls. Display counts as collection counts. Explain that an empty reviewed-dependency view means prerequisites haven't been adjudicated. No funding scores, guessed costs, false precision, or decorative hairball graph.

Provide README quick start, an example generated HTML artifact under `artifacts/`, and a pilot evaluation sheet. Check: tracing a claim to its specific source; distinguishing fate correlation from causal regulation; finding the same question under multiple facets; seeing why a method's applicability is limited; proposing an experiment that could change a conclusion; withdrawing a claim without losing its history. Automated checks verify structural invariants and regressions. Human usefulness/expert scientific assessment remains an explicit next evaluation, never claimed as completed by passing software tests.

## Delivery boundary

Deliver the first usable slice with offline tests, CLI smoke validation, a generated pilot page and a reviewed local branch. Preserve the archived checkout as-is. The next stages are: expert/user evaluation; adjacent-domain expansion; assisted literature updates; grounded resource planning. They depend on the first slice demonstrating value and are not silently implemented as an autonomous production system.
