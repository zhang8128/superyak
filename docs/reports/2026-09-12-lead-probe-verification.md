# Lead-model probe: implementation and observations

Kairos asked to merge the completed work and continue after agreeing to four
Kimi K3 and four GLM-5.3 leaders. The earlier implementation branches were
already ancestors of local `main`. Commit `b0accae` records the outstanding
research reports, plans, and handoff. That integration passed `make check`:
2,473 Python tests, two expected live-config skips, Lighthouse build/lint/type
checks/tests/proofs, and interoperability checks. Five existing dependency/fork
deprecation warnings were reported. Nothing was pushed.

## Bounded continuation

The [probe](../lead-model-probes.md) extends the existing local inference client
with opt-in K3 and GLM text protocols. It preserves returned assistant state,
sets reasoning effort explicitly, and leaves the synthetic campaign's request
defaults intact. The two-call diagnostic checks a fictional observation and
its correction. It records failures, timing, token usage when supplied, and
private request/response artifacts. It makes no deployment or scientific-quality
claim. Tool execution and vision are outside this probe.

Provider tests first failed because protocol selection was absent, then passed
after implementation. Probe tests cover state round trips over real loopback
HTTP, stale answers, truncated and failed requests, malformed JSON, revision
validation, artifact permissions, and refusal to overwrite prior runs. The
source-bundle test first failed because the new probe was not packaged, then
passed after its addition to the exact allowlist. An independent review found
a missing import path in the prepared-tree command; that command now supplies
the Engram source path and starts with editable installations excluded. The
reviewer's final run passed all 66 focused provider/probe/launcher tests, with
no outstanding findings.

The final full Python regression passed **2,491 tests**, with two expected
live-config skips and five existing warnings. Run this suite from `engram`,
as the repository Makefile specifies. An earlier invocation from the repository
root failed because existing fixtures resolve manifests, schemas, and migrations
relative to the working directory; the corrected invocation passed. The
Lighthouse source was unchanged from the successful initial `make check`.

A generated source bundle was unpacked into a temporary directory and the
probe's `--help` was executed with Python `-S` and the documented `PYTHONPATH`.
The new module's archived bytes matched its source. This verifies the packaged
entry point independently of the workstation's editable Engram installation.

## Actual local model observations

The installed `qwen3.8:27b-mlx` was used as a control through its loopback
chat-completions endpoint. Its advertised model digest was
`sha256:5642e97495e1a088883805981563dcdc4a040c2f53388b7a41d1f24d3622cf7e`.
This run did not independently verify checkpoint contents, precision, or the
server's load manifest. It used the unchanged synthetic-client settings:
temperature 0.6, seed 0, forced JSON mode, reasoning disabled in template kwargs,
a 512-token output cap, and a 120-second request deadline.

Both requests completed but **both checks failed**. The returned text contained
the expected counts and source versions embedded in malformed JSON with leading
text. The first call took 84.98 seconds and reported 133 input / 222 output
tokens; the correction took 9.35 seconds and reported 237 / 248 tokens. These
are two observations on a shared workstation, not a throughput estimate.

A separate one-call diagnostic repeated the first request while omitting only
`response_format`. It returned valid JSON with the expected fields in 56.63
seconds. This suggests a problem involving forced JSON mode in this local
serving path. It is insufficient to identify the underlying engine fault or
claim a complete two-turn repair. The original outputs remain unchanged, and
the probe now labels invalid JSON separately from a parsed, unexpected answer.
The native K3/GLM request profiles do not force JSON mode.

Local artifacts, excluded from Git, are under:

- `.engram/lead-probes/2026-09-12-qwen-control-01/`: failed two-turn control,
  raw requests/responses, and a source snapshot identifying the uncommitted code
  used for that control.
- `.engram/lead-probes/2026-09-12-qwen-format-diagnostic-01/`: request and raw
  result for the one-variable comparison.
- `.engram/lead-probes/prepared-source.tar.gz`: updated allowlisted source
  bundle with the probe entry point.

K3 and GLM were exercised through scripted HTTP fixtures only. Neither model
was downloaded or launched, and no Stampede3 job was submitted. Actual model
loading, GPU kernels, multi-node placement, context limits, and useful research
behavior remain the next measurements. The agreed eight identities do not
establish a number of physical model-serving replicas.
