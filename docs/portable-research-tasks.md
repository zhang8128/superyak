# Portable research tasks

**Current model requirement:** [American models only](model-policy.md), with
Gemma 4 preferred. Qwen/Kimi/GLM examples below describe historical preparation,
not approved selections for new calls. A new task must explicitly select an
eligible model and verify its serving compatibility; preserve prior artifacts.

Freeze one selected Atlas question and one completed paper job, then run an
extraction and a fresh source-support check against an existing local endpoint.
The same packet can travel with the Stampede3 source bundle. This measures a
research turn before hardware access; the current cluster launcher still runs
its synthetic campaign and does not schedule these tasks automatically.

## Select and export

Run `make setup-engram`, then `make research-task` for help. Inspect the selected
project with `make atlas ATLAS_ARGS='research-status --json'` and its saved
`.atlas/research/jobs/*.json` files. Choose an exact recorded job and its question:

```sh
make research-task RESEARCH_TASK_ARGS='export --project /absolute/MG-project --question-id QUESTION_ID --job-id JOB_ID --output /absolute/tasks/mg.json'
```

Export reads the live project without creating a worker identity or changing its
journal. The packet contains the current question, one cached document's exact
passages, attribution, coverage, publication types and content hashes. It omits
other records, private context fields, previous model replies and session identity.
Question projections begin as proposed; provenance retains their original status
without exporting reviewer identity. For abstract-only evidence, the document URL
is the public source URL and the coverage note is standardized, so search queries
and transport exception text are omitted. Explicitly selected question text and
source content are still exported: inspect the packet before sharing it.

This creates a new fixed-input task. It does not reconstruct the historical
prompt: the original job did not preserve its original question snapshot. The
provenance job hash covers canonical parsed job JSON; `content_sha256` covers
canonical normalized passages, and `document_sha256` covers the exported document
including metadata. Neither is a hash of original publisher PDF/XML bytes.

## Run or replay

Use a fresh output directory outside any live Atlas project:

```sh
make research-task RESEARCH_TASK_ARGS='run --packet /absolute/tasks/mg.json --output /absolute/runs/mg-ollama --backend ollama --endpoint http://127.0.0.1:11434 --model qwen3.8:27b-mlx --model-revision EXACT_REVISION'
```

For a chat-completions server, change the backend and endpoint and choose a new
output directory:

```sh
make research-task RESEARCH_TASK_ARGS='run --packet /absolute/tasks/mg.json --output /absolute/runs/mg-completions --backend completions --endpoint http://127.0.0.1:11434/v1 --model qwen3.8:27b-mlx --model-revision EXACT_REVISION --protocol research'
```

`--model-revision` records an operator-declared weight/serving revision. The
runner also checks the model name reported by replies; it cannot verify which
weights a server loaded. Record server configuration and observed digests alongside
runs. Kimi K3 and GLM-5.3 can use their matching protocol names on a compatible
existing loopback server, with an explicit reasoning effort. A loopback SSH tunnel
can expose a remote service. No model is downloaded or started by this command.

The research completions protocol omits forced JSON mode and disables thinking.
Native Ollama keeps the Atlas request format. These are matched evidence turns,
not byte-identical requests or a controlled test of one serving parameter. Both
paths strictly validate returned JSON without repairing prefixes. Lead protocols
retain complete returned assistant state in artifacts. Source review is always a
fresh conversation using the candidate and supplied paper, with no prior graph
records or extraction assistant history.

Run the identical command again to replay. Completed tasks check their pinned
packet, configuration, implementation and artifact hashes and return the saved
result without checking the server or calling the model. A changed model, seed,
source or implementation requires a fresh output. Preserve the matching source
checkout or archive to reproduce old runs. Keep the Engram and research-task test
suites in separate Python processes because the earlier POC pins its own Atlas
imports.

## Results and recovery

`result.json` records one of `recorded`, `held`, `irrelevant`, `invalid`, or
`failed`, inside a checksummed envelope. Recorded findings remain proposed and
live only in the run's isolated `project/`; open its `Research/index.html`.
A supported automated check is not independent scientific validation.

The directory includes the task, code/configuration manifest, run identity,
immutable started/response checkpoints, exact dispatched requests and retained raw
replies, context manifests, timing/token metrics when supplied, draft and Atlas
receipt/publication. Corrupt or changed artifacts are refused. Hashes detect
accidental changes; they are not signatures authenticating an external sender.

A saved extraction or review is reused after a restart. If capture saved a draft
but the process lost the receipt, replay recovers the same draft through its stable
identity and idempotency key. A started request with no durable response has an
unknown outcome: replay stops without another model call. Inspect the evidence and
choose a new output directory for an explicit new attempt. This does not promise
exactly-once remote inference across a crash.

Model replies can contain source excerpts and reasoning. Keep real run artifacts
local by default; the source staging allowlist includes executable task code and
excludes task packets and live project state. Transfer only the explicitly selected
packet separately. Source archives support running `python -m research_tasks` from
the extracted root after installing the Engram lockfile.

## HTTP recovery and remaining measurements

Paper retrieval and native Ollama calls now have separate, fixed request slots.
An absolute deadline bounds connection setup, sending, headers and response reads;
slow headers cannot keep the shared model path busy. Loopback model calls bypass
environment proxies. There is no automatic retry of a model POST.

An operating-system DNS call can remain stuck beyond the Python deadline. Its
single daemon retains only its own lane until resolution returns. It cannot
accumulate more workers, block the other lane, or dispatch a late HTTP request.
This residual limitation is reported as a busy lane, not hidden by spawning more
threads.

The next research slice is a matched comparison of researchers with individual
memory, explicit shared memory, disagreement and source corrections. This task
runner does not yet implement that community. Whole-Stampede3 placement, Intel
runtime behavior, K3/GLM hosting and useful throughput remain measurements for
hardware access. The agreed four K3 and four GLM lead identities remain the
starting group; identities do not imply eight loaded replicas.
