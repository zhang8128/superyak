# Dynamic context implementation completion

Implementation measured: `a7dddd7` on `feat/dynamic-context`, following the
recovered chat/coding runtime at `737213f`. Work and verification occurred on
September 6, 2026 in America/Los_Angeles (September 7 UTC).

## Fixes and independent review

An unfinished chat tool episode could retain external source text after the
source changed or was revoked. It now treats earlier selected external evidence
and external pages returned by archive tools as dependencies, checks them before
and after counting, and stops the episode before another generation if they
change. Stopping the whole episode also avoids replaying opaque provider items
that may derive from the old source. This cannot withdraw data already sent.

Historical correction inspection could resolve a new value, or lose the old
value after unpinning. Chat and coding manifests now record the immutable
original correction event ID and version; the browser inspector uses that ID.
Older manifests cannot acquire missing provenance retroactively.

All six source-validity and inspection regressions failed before the fixes and
passed afterward. Independent review accepted the fixes. It also caught a full
SQLite sort in the replay's final manifest audit; the audit now streams rows.
No material findings remained in the final scoped re-reviews.

## Archive ranking measurement

A repeated-prose workload exposed growing FTS ranking cost even though returned
candidate counts were bounded. A separate 1,000-generation-call diagnostic
without tracemalloc measured 32.9106 seconds in `ContextStore.search` out of
56.9571 seconds total (57.78%). Successive 100-call intervals grew from 3.6114
to 10.1142 seconds. See the [raw profile](2026-09-06-context-runtime-profile.json).

The final implementation adds a 50 ms SQLite progress deadline, under the same
connection lock, and clears the handler after each search. Chat and coding
continue using current, recent, and required context when it expires. Manifests
and archive-search tool results explicitly report incomplete coverage. The
deadline is cooperative: it does not bound lock waiting, every native operation,
or OS scheduling to exactly 50 ms. Timeout fallback may miss relevant old sources.

Three deadline/fallback regressions failed before implementation. The scoped
store/runtime/coding/replay group then passed 53 tests. Independent review
accepted the change. The original repeated-prose workload was retained for the
final replay; its retrieval failure count is reported below. Two preliminary
long replays were stopped to fix the audit and investigate ranking cost. They
are not reported as completed acceptance runs.

## Runtime replay

The final run passed its mechanical checks in **738.511 seconds** (12 min
18.5 s), averaging 13.541 generation calls per second. See the [raw runtime
report](2026-09-06-context-runtime-replay.json) and [RSS samples](2026-09-06-context-runtime-rss.json).

| Measurement | Observed result |
| --- | --- |
| Actual synthetic generations / exact counts / matching dispatched payloads | 10,000 / 10,000 / 10,000 |
| Completed turns / tool continuations / valid tool call-output pairs | 5,000 / 5,000 / 5,000 |
| Maximum input count | 13,718 synthetic units, below the 131,072 ceiling |
| Input + output reserve + margin | At most 18,838 units, below the 262,144 window |
| Maximum observed / selected candidates | 20 / 20, below the configured bound of 32 |
| Maximum decoded artifact page / serialized tool output | 4,096 / 5,593 bytes |
| Persisted archive at end | 25,000 events, 10,000 manifests, 5,000 turns |
| Python retained allocation growth after the 200-call warmup | 963,612 bytes (0.919 MiB), below the configured 32 MiB bound |
| Peak Python-traced allocations | 2,101,252 bytes (2.004 MiB) |
| Sampled process RSS, first / maximum / last | 42,303,488 / 42,811,392 / 42,811,392 bytes |
| Sampled RSS growth | 507,904 bytes (0.484 MiB) |
| Manifests reporting incomplete archive retrieval | **8,547 / 10,000 (85.47%)** |

The high fallback rate is a substantial recall limitation on this repeated-text
workload. The bounded deadline keeps work moving but does not establish effective
old-context retrieval. The synthetic answer only checks a directly addressed
artifact page; it does not depend on successfully retrieving an old dialogue
event. These results therefore support the resource and request-handling checks,
not a claim that long-session recall or the continuity pilot passed. Search
scalability and recall must be evaluated before normal-use rollout.

Tracemalloc measures Python allocations, not native SQLite memory or process
RSS. The independent RSS sampler collected 137 samples using macOS `ps` every
five seconds, converting KiB to bytes. It started after process initialization;
its first value is not the process startup peak or the exact 200-call warmup
boundary. Sampling can miss short peaks. Stable sampled RSS and bounded Python
growth are observations for this workload, not proof for every input size or
provider. The replay's final manifest audit uses a streaming table scan.

Reproduction from the implementation checkout:

```bash
python scripts/context_runtime_replay.py \
  --model-calls 10000 --warmup-calls 200 --progress-every 500 --indent 2 \
  > context-runtime-replay.json
```

Environment: CPython 3.13.5, SQLite 3.49.1, macOS 26.6.2, arm64. The synthetic
provider exercises the real archive/compiler/runtime, alternates a 4,096-byte
read from a 1 MiB fixture artifact with an answer, and uses repeated natural
language turn text. Its counter assigns one synthetic admission unit to each
UTF-8 byte of canonical request JSON. It does not contact a model, use private
data, certify a live tokenizer, or evaluate answer quality. The temporary archive
is deleted after the replay. The elapsed time includes tracemalloc overhead.

## Other verification

| Check | Observed result |
| --- | --- |
| Recovered implementation context suite | 181 passed in 46.11 s |
| Full repository suite after source/provenance fixes and replay harness | 1,950 passed in 643.03 s; three existing warnings |
| All context tests after the archive-search deadline change | 192 passed in 44.54 s |
| Browser integration with a deterministic provider and real store/runtime | Historical correction revision/unpin, reload, new thread, and no JavaScript errors passed |
| Fresh live Astra subscription smoke with a synthetic prompt | Returned `ENGRAM_CONTEXT_OK`; 10,054 input and 8 output tokens reported |

The full repository suite was not rerun after the scoped deadline change; all
context tests were. The warnings are an existing Graphiti/Pydantic configuration
warning and two warnings about fork from a multithreaded test process. No live
API-billed calls were made. Earlier live coding and two-episode recall checks
remain documented in the [runtime guide](../dynamic-context.md).

## Remaining evaluation boundaries

The ChatGPT subscription adapter starts fresh Codex episodes. It does not offer
strict admission or context replacement before every internal Codex model call.
Strict per-call admission is available only through the explicitly selected
Responses API adapter and its separate billing. The installed Codex 0.153.4
app-server schema was checked during this work.

The design's 100-question human continuity pilot has not been run. The lexical
Engram source is not equivalent to richer MCP recall. Live-tokenizer checks for
additional providers, category/sheaf influence, and Lighthouse networking remain
separate work. The opt-in runtime does not change existing Codex conversations
or the running Engram MCP server.
