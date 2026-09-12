# Research iterations and Stampede3 bring-up

Direction agreed September 12, 2026: develop and test the research architecture
on available local compute; troubleshoot Intel and Stampede3 when access exists.
Useful public-source research should continue alongside comparative experiments.
The existing synthetic deployment harness is preparation for that work, not
evidence that the scientific workflow or GPU capacity is ready.

## Two tracks

| Track | Work | Evidence needed |
| --- | --- | --- |
| Research architecture, now | Atlas source retrieval, evidence assessment, research questions, individual histories, selected shared publications, recovery, and local concurrency comparisons | Inspectable sourced outputs; recorded exposure/usage/errors; preserved identities and histories; reproducible comparison runs |
| Intel/Stampede3, once accessible | Driver/device compatibility, vLLM/SYCL, placement, throughput, Slurm ownership, job expiry, storage and recovery | Actual allocated-node measurements and a successful research workload through the selected backend |

Neither track requires participant details. Research development does not wait
for cluster access, and inference probes do not wait for a completed memory
architecture. Hardware compatibility is a dependency of cluster execution only.

## Atlas's role

Use the current `atlas-workbench/workbench` implementation as the starting
research workflow and readable evidence collection. It has source retrieval,
bounded context, proposed findings with evidence locators, capture/retry state,
Lighthouse views, and browser/Obsidian exports. Export commit `d856fb6` exists in
the local history. The legacy `atlas/` engine is a separate implementation.

The current working tree also rotates research, audit, question, overlap and
connection roles. These share one process/model and shared evidence context;
they are not five independent agents with private continuing histories. Atlas's
context code follows Engram's selection pattern but does not itself use Engram
private memory stores. Superyak supplies those individual/shared-memory
mechanisms for the next research experiment.

There is no completed Atlas–Stampede integration. Atlas currently speaks
Ollama's chat protocol, whereas the prepared Stampede provider speaks local
chat completions for vLLM/SYCL. Atlas's source-analysis schema also differs from
the synthetic campaign's answer/memory/publication schema. Changing a base URL
would not port the workflow.

The Atlas working tree contains substantial ongoing uncommitted work. Select
and record an exact tested source snapshot before using it as an experimental
baseline; preserve the existing checkout and live research journal.

## Iterative research rounds

1. **Establish a real research baseline.** Use a bounded existing public-source
   question and one reproducible Atlas run on available compute. Record sources
   actually retrieved, passages supplied, proposed claims, limitations, model
   usage, errors, and elapsed time. Inspect the resulting browser/notes and
   verify that interruption/resume preserves unfinished and completed work.
   This produces research material while exposing workflow problems.
2. **Compare memory mechanisms alongside continuing research.** Run matched
   task/evidence packets with individual persistence off/on and shared
   persistence off/on. Give distinct agents stable identities and private
   histories; use explicit attributed publications for exchange. Keep the
   continuing research community separate from these experimental replicas.
   Retain lineage when creating a comparison from a published snapshot; do not
   reset the continuing community or silently mix histories between treatments.
3. **Improve from observed differences.** Compare small concurrent populations,
   request caps, retrieval choices or role arrangements when a concrete result
   motivates the comparison. Several variants can run in the same round, with
   their differences recorded. Retain a reference and contrary results. Repeat
   selected contrasts before making causal claims. Population settings remain
   experimental inputs, not commitments to a future organizational hierarchy.

Each round yields both a research artifact and an engineering observation. Use
the observation to choose the next bounded change. Do not require every scale
test to finish before useful research continues.

Measure source/quotation fidelity, unsupported-claim failures, duplicate work,
responses to corrections, recovery, latency, reported tokens and completed
tasks. Keep mechanical checks, model assessments and human scientific judgments
distinct. More notes, claims, agents or recalled memories do not establish
better research. Changes in instinct strength or other internal scores require
behavioral evidence and controlled comparisons; an unobserved trigger alone is
not evidence that a disposition should weaken.

## Port the demonstrated workflow later

Keep research inputs, scoped evidence records, memory ownership, task identity,
results and checkpoints understandable independently of the serving backend.
Use the existing Atlas model boundary and Superyak deployment/provider seams;
add only the adapter needed by the first measured workload. Do not build a
general orchestration platform, cross-node shared database, or large role
hierarchy before an observed workload requires it.

Once access arrives, independently probe Intel serving and Slurm behavior.
Then replay a known research task through the accepted backend, checking its
output contract, evidence handling and actual context/output limits. Continue
the local research effort while diagnosing cluster failures. Expand placement
and concurrency from measured results. The existing four-node/twelve-hour
synthetic preset remains available as a test preset; it is not a commitment to
launch that full campaign before testing the research workflow.

## Current observations

Read-only checks on September 12 found that Atlas's `research-status --json`
reported `running: false`, `phase: not_running`, dynamic context and 167 recorded
cycles. This does not establish why it stopped or the quality of those cycles.
An exact `context myasthenia --limit 3` CLI lookup exceeded a 15-second bound;
the MCP context/status checks also did not return promptly and were abandoned.
The cause is unmeasured. No conclusion about available myasthenia evidence can
be drawn from the timed-out lookup. Context-read latency and baseline recovery
are concrete first-round checks, without an Intel dependency.

No Atlas worker was started/restarted, no biological finding was recorded, and
no cluster job was submitted during this assessment.
