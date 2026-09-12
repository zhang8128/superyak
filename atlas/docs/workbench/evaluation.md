# Pilot evaluation sheet

Software validation and human usefulness are separate evaluations. Automated checks establish that records, evidence, states and filters behave as specified. They do not establish that a scientific interpretation is correct or that a proposed study is worth doing.

The bundled pilot has six primary sources, eight source-reported claims, two questions, five approaches, two proposed experiments and twenty proposed relations. No expert review or biological experiment has been completed for this workbench.

## Completed software checks

The five workbench test modules cover import/export invariants, source references, facet identity, typed relations, status/history retention, dependency filtering, legacy-note import, malicious text/URL handling and protected atomic HTML output. A temporary-database CLI smoke flow exercises init → import → search/show → export → render, idempotent import, and a demonstration withdrawal.

Real headless Chrome checks exercise question-to-approach-to-claim navigation, source locators, multi-facet intersections, zero results, status filtering, clearing filters, keyboard activation, proposed experiment details, withdrawal history, mobile overflow and malicious strings retained as data. The page makes no HTTP requests while browsing locally. Visual inspection of screenshots checks typography and desktop/mobile readability. These are software and presentation checks, not a completed user study.

## Human session — not yet conducted

Evaluator: __________  Role/domain experience: __________  Date: __________

Collection/artifact revision: __________  Browser/device: __________

Ask a prospective research user to complete the tasks below without coaching. A domain expert should additionally assess the scientific scope and interpretations. Record where the participant hesitates, confuses statuses or needs a missing source. Do not mark a task complete merely because its software test passed.

| Task | What to observe | Result / evidence / correction |
| --- | --- | --- |
| Start from the fate question, open Transcriptomic dynamics and fate mapping, and follow the Markov limitation to its source. | Can the participant identify the primary paper and section locator, and explain which part is publication attribution versus our proposed relation? | Not yet evaluated: __________ |
| Compare a fate prediction with a regulatory explanation. | Can the participant explain why association, a perturbation response and direct regulation are distinct claims? Ask what further evidence they would need. | Not yet evaluated: __________ |
| Find the regulation question under scale=molecular and again under scale=cellular. | Is it clear that both facets refer to the same record rather than duplicate questions? | Not yet evaluated: __________ |
| Inspect the LARRY or BEELINE limitation and its challenge relation. | Can the participant state the study-specific boundary without interpreting it as disproof of all lineage tracing or GRN inference? | Not yet evaluated: __________ |
| Open either proposed experiment and name a result that would change the interpretation. | Is the proposal useful enough to refine into a study? Which controls, outcome definitions or measurements are missing? | Not yet evaluated: __________ |
| In a disposable database, withdraw a claim and regenerate the HTML. | Can the participant find the withdrawn status, reason, actor, timestamp and retained source? Do they understand that withdrawal is irreversible? | Not yet evaluated: __________ |
| Inspect the empty reviewed-prerequisite view. | Does the participant understand “not adjudicated” rather than “no prerequisites exist,” and avoid treating reachability as priority? | Not yet evaluated: __________ |

Scientific corrections and exact source locators: __________

Navigation friction or missing context: __________

Would this help with a real question? Which one, and what is the smallest necessary improvement? __________

## Decision after the session

Record the evaluator's actual assessment, unresolved disagreements and the artifact revision reviewed. Correct overstated claims with explicit new revisions/withdrawals, then repeat affected tasks. Do not promote pilot records merely to populate a dependency graph. Expansion to adjacent domains, assisted literature updates and resource planning follow the [roadmap's stage gates](roadmap.md), after this slice demonstrates value.
