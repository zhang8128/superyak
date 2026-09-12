# Probe the research lead models

The agreed starting group is four Kimi K3 and four GLM-5.3 identities. Their
model-serving replicas and placement depend on actual tests. This command
exercises an already-running local model with two fictional text requests:
an initial observation and a correction to that observation. It checks the
client protocol and a basic response contract. It does not evaluate biomedical
research quality, memory benefit, or cluster capacity.

## Run a probe

Start with `make lead-probe` to see the arguments. Once a model server is
running on an allocated compute node, run this from the prepared source tree
using that environment's Python. Replace the revision and deployment description
with the checkpoint and runtime actually loaded:

```sh
PYTHONPATH="$PWD/engram:$PWD" ../.venv/bin/python -m deploy.stampede.probe \
  --endpoint http://127.0.0.1:8000/v1 \
  --model moonshotai/Kimi-K3 \
  --protocol kimi-k3 \
  --revision CHECKPOINT_COMMIT \
  --deployment 'BACKEND_VERSION; PRECISION; GPU_MODELS_AND_COUNT; NODE_COUNT' \
  --reasoning-effort low \
  --max-tokens 4096 \
  --timeout 120 \
  --output .engram/lead-probes/k3-01
```

Use `--model zai-org/GLM-5.3 --protocol glm-5.3` for GLM, with its own server,
revision, deployment description, and fresh output directory. The `--model`
value must exactly match the server's configured name; aliases are allowed
when declared explicitly. The revision must be a 40-character checkpoint commit
or `sha256:` followed by a 64-character model digest. These are operator-supplied
records: the report explicitly says the server's revision was not independently
verified. Check the server's loaded-checkpoint manifest when assessing a result.

The example assumes the launcher's `RUN/source` working directory and
`RUN/.venv/bin/python` environment. Its bootstrap installs dependencies without
installing the Engram project, so the explicit `PYTHONPATH` is required. In a
normal installed checkout, `make lead-probe LEAD_PROBE_ARGS='...'` uses the local
Engram environment instead.

The endpoint must be loopback HTTP. Run on the server's compute node or use a
separately established local tunnel. The command does not launch a server,
download weights, submit jobs, create an agent population, or access a paid API.
New Stampede source bundles include the probe; older prepared archives need to
be regenerated before they contain it. The existing campaign configuration and
synthetic startup check retain their prior defaults.

## What is preserved and checked

Both lead protocols send an explicit reasoning effort and preserve the complete
returned assistant object for the next turn. K3 requires its `reasoning_content`
field. GLM explicitly uses `clear_thinking=false` for this continuing-agent test.
Neither lead protocol forces JSON mode or disables reasoning. The prompt asks
for a JSON final answer and the probe checks it after completion. These settings
follow the [K3 model instructions](https://huggingface.co/moonshotai/Kimi-K3)
and [GLM model instructions](https://huggingface.co/zai-org/GLM-5.3), checked on
12 September 2026. GLM recommends clearing thinking for ordinary chat; this
probe deliberately tests preserved conversation state. This is a text-only
boundary: active tool calls and vision inputs are not implemented here.

The first fictional source reports six of ten wells fluorescing. Its correction
reports two of ten, supplies a new source identifier, and supersedes the first
version. Both are uncontrolled observations. The response must use the current
count and source, identify the superseded version, and avoid claiming an
established causal effect. The comparison uses literal expected fields, not a
model judging its own answer. Such a small test is only a starting diagnostic.

Each invocation makes at most two calls with bounded output and deadlines. A
transport error, wrong model identity, or truncated answer stops the probe;
there are no automatic retries. A completed but incorrect first answer still
allows the correction turn, while the overall result remains failed. Increasing
the token budget or changing effort creates a new comparison and should use a
new output directory. `--protocol synthetic` retains the existing client
settings for a Qwen control; it does not emulate either lead model.

The output directory is private (`0700`), with `0600` JSON artifacts containing
requests and responses. `report.json` contains checks, per-call wall time,
reported token counts, declared model/deployment identity, and hashes of
completed turn artifacts. Missing token counts remain unknown. Assistant
reasoning remains in local turn artifacts and the same conversation; it is not
copied into the summary or shared with other agents. A shared client does not
accumulate histories between callers.

Failed checks distinguish malformed JSON (`invalid_json`) from a parsed answer
with incorrect fields, types, or values (`unexpected_answer`). Model output is
retained exactly; the checker does not remove prefixes or repair answers to
make them pass.

Exit code 0 means both fictional checks passed; 1 means the probe failed;
2 means configuration or local file handling failed. Existing output directories
are refused without sending requests or overwriting records. Interrupted runs
may retain a `running` report and partial artifacts; inspect them and use a new
directory for a fresh probe.

## Continue on Stampede3

For each selected model, record successful model loading, backend/version,
precision, actual GPU and host memory use, placement, and practical context
limits. Run this probe first, then replay matched public-source research tasks
with source corrections and independent evaluation. Measure latency at the
intended input/output lengths before deciding replica counts. A successful
local Qwen control or scripted protocol test does not demonstrate that K3 or
GLM can run on H100. The [model review](reports/2026-09-12-open-model-lead-selection.md)
records those open deployment questions.
