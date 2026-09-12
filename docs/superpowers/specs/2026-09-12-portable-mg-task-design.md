# Transport recovery and a portable MG task

Kairos approved the next preparation slice: fix the observed retrieval/inference
coupling and make one real MG task reproducible across local and cluster model
protocols. Keep the continuing MG project and historical POC runs intact.

The observed failure was a 30-second full-text timeout followed by an occupied
process-wide HTTP slot. Subsequent model and paper calls failed even though an
abstract was available. Use absolute-deadline socket handling and two fixed lanes
(papers and local models). Each lane retains one bounded transport owner until
cleanup; do not release a slot while its operation is alive. An uninterruptible
OS resolver may still occupy the paper lane, but cannot block model calls or
send a request after its deadline. Process-per-request orchestration is outside
this fix.

Add a separate `research_tasks` package. Explicit `export --project --question
--job --output` selects one completed cached job and one current question. Export
only the chosen question's public-facing fields and cached paper passages/source
metadata, with hashes, locators and coverage. Exclude the live graph, private
context/provenance, prior model reasoning, unrelated records and service state.
The task is a new frozen question/evidence selection, not an exact historical
prompt replay. Checksums provide integrity, not peer authentication.

`run --task --output --backend --model --model-revision` executes extraction and
fresh source-only review in an isolated Atlas project. Reuse Atlas's existing
compiler, extraction and review validators, and draft preparation/recording.
Support Ollama and the existing loopback chat-completions provider; preserve raw
responses, selected-context manifests, usage and complete lead assistant state.
The review deliberately starts a fresh conversation. A new opt-in research
protocol omits forced JSON mode; the synthetic client's defaults stay intact.

Pin task, model/protocol/budgets and implementation bytes in each run. Save a
started marker before a request, and a checksummed response before validating or
publishing it. Completed replay makes zero model/health requests. An attempt
without a saved completed response remains uncertain and cannot retry silently.
Stable Atlas attribution/idempotency prevents duplicate capture after an
interruption. Packet/source tampering, mismatched questions, altered run pins,
invalid quotes, and unsupported reviews must fail or hold before publication.

Verification uses controlled HTTP fixtures and synthetic packets, plus a fresh
local Qwen run on one explicitly exported completed MG job. Keep full-text packet
artifacts local and excluded from the source tar. Add portable code to staging;
this does not replace the synthetic cluster campaign or establish GPU support.
No broad live-state export, remote jobs, model downloads, or push. After testing,
a controlled restart of the authorized MG worker may activate the transport fix
while retaining its journal and options; report the process change explicitly.
