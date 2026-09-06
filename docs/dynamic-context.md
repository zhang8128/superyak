# Dynamic context runtime

This opt-in runtime automatically archives conversations and selects relevant
originals before each invocation. It includes a terminal chat, a local browser
chat, source inspection, and explicit correction/pin controls. It leaves the
existing daemon, MCP server, and current Codex conversations unchanged.

## Start with your Codex subscription

From the Engram checkout with its Python environment installed:

```bash
.venv/bin/python -m context_cli serve
```

Open **http://127.0.0.1:7433**. Codex must already be signed in with ChatGPT.
The default model is `gpt-6-astra`; account/model availability is checked by
the adapter. No API key is needed for this route, and it never falls back to
API billing. Calls use your Codex subscription allowance.

For a named instance, put shared options before the command:

```bash
.venv/bin/python -m context_cli --instance engram serve
.venv/bin/python -m context_cli --instance engram --thread research chat
```

`ENGRAM_HOME` selects the Engram root; it defaults to the module's directory.
Default memory source: `$ENGRAM_HOME/.engram/graph.db`, or
`.engram/instances/<name>/graph.db` for a named instance. Override it with
`--engram-db PATH`. A missing memory source stays missing: the runtime never
initializes or modifies that database.

The new conversation archive defaults to `.engram/context-runtime/context.db`
under the selected root/instance. Use `--data-dir PATH` for another location.
With an installed wheel, set `ENGRAM_HOME` or `--data-dir` explicitly to a
writable data directory.

When running from the development worktree, use the main checkout's environment
and an explicit root:

```bash
ENGRAM_HOME=/Users/kairos/Projects/engram \
  /Users/kairos/Projects/engram/.venv/bin/python -m context_cli serve
```

## What the two provider modes guarantee

| Mode | Automatic context | Counting and limits | Billing |
| --- | --- | --- | --- |
| `codex` (default) | Fresh ephemeral Codex episode for each Engram response | Conservative estimate of supplied content; process deadline and output-byte caps. Codex's hidden instructions and internal steps are outside the estimate | ChatGPT/Codex subscription |
| `responses` | Fresh explicit request before each model/tool round | Provider preflight input count plus configured output reserve and context limit; no automatic history truncation | Separate OpenAI API usage |

The subscription adapter **does not yet implement replacement before every
internal Codex model call**. Its output-token reserve is also not enforceable
through app-server. `--strict` rejects this adapter. Closing an episode drops
its private reasoning continuity; the visible conversation continues through
Engram's archive and selected context.

The first live subscription smoke returned `ENGRAM_OK`, with 9,882 reported
input tokens and 7 output tokens. That difference from a tiny supplied prompt
demonstrates why a local estimate cannot certify the complete Codex request.
No private memory source was sent in that smoke.

Codex's managed login and custom-client interface are documented in
[app-server](https://learn.chatgpt.com/docs/app-server). The API counting contract
is documented in [token counting](https://developers.openai.com/api/docs/guides/token-counting).
An integration inside Codex request assembly remains necessary for strict
subscription-backed dynamic context.

## Explicit API mode

Configure `OPENAI_API_KEY` through your normal secret management. Select the
context limit from the documentation for the exact model used; do not copy a
different model's capacity. For example, substituting the verified limit:

```bash
.venv/bin/python -m context_cli \
  --provider responses --model gpt-6-astra \
  --context-window VERIFIED_LIMIT --strict chat
```

`VERIFIED_LIMIT` is intentionally not a preset model claim. The runtime refuses
API mode without an explicit context limit. Other configurable values are
`--input-ceiling` (24,000), `--soft-target` (12,000), `--max-output` (8,000), and
`--margin` (1,000). Check output-limit compatibility against the same model
profile. The model service can reject unsupported settings.

The API adapter sends `store=false` and disables automatic truncation. It counts
the same context-bearing fields it dispatches, including instructions and local
function-tool schemas. Provider items and tool call/output pairs remain intact
inside the active episode. Hosted tools and hidden conversation chains are
rejected because they can introduce model work outside this gate.

Count and generation calls have independent views of the remaining turn
deadline. HTTP reads/sends enforce that deadline and response-byte caps;
standard-library DNS resolution remains subject to operating-system resolver
behavior. API transport was validated with local protocol/socket fixtures;
no live separately billed API invocation was performed for this implementation.

## Recall and inspection

Ordinary conversation requires no memory-tool ceremony. Each user event is
committed before inference; completed answers are saved with their turn result.
Search indexes originals immediately. Failed turns stay available for inspection
but do not become mandatory continuity for the next response.

The current local Engram adapter uses **bounded lexical retrieval**, reading
recent episodes/semantics and a small core/instinct sample without loading a
model or running maintenance. It reports `sqlite_lexical` in source coverage.
It is simpler than both embedding retrieval and the MCP server's richer recall.
Source versions are rechecked after counting; changed/deleted selections are
removed and recounted before dispatch. This checks local availability at
preparation time, not retroactive withdrawal from a service already sent data.

Selected dialogue renders chronologically, regardless of retrieval score. The
immediate completed exchange and explicit user notes remain required. Original
roles, source IDs, versions, and excerpt markers stay attached. No recalled
instruction becomes a developer instruction, and mere selection does not
reinforce a memory.

Use **Context in use** in the browser to inspect the actual selection, its
reasons, count method, omitted count, model, and source versions. Click an entry
to read its original. The CLI equivalent is:

```bash
.venv/bin/python -m context_cli --thread research inspect
.venv/bin/python -m context_cli --thread research status
.venv/bin/python -m context_cli --thread research correct coordinator "Mira is the coordinator"
.venv/bin/python -m context_cli --thread research unpin coordinator
```

Explicit notes are optional. Reusing a note's key replaces its active value while
keeping its historical source event. This first version does not pretend to
reliably extract every natural-language correction, infer task boundaries, or
promote dialogue automatically into verified semantic facts. Those need separate
continuity evaluation. You can keep relevant decisions explicit without manually
capturing every exchange.

## Recovery and retention

The archive persists until explicitly deleted; leaving the prompt is not
deletion. It uses bounded query pages instead of an expanding in-memory transcript.
No network replication or automatic sharing is enabled.

A repeated completed `--event-id` returns its existing result. Reusing an ID with
different text or after uncertain/failed execution produces a conflict instead
of automatically repeating work. Inspect status, then deliberately start a new
event if appropriate. Required context that cannot fit produces a capacity error;
it is never silently cut. An oversized unfinished tool episode is archived and
stopped; a later episode does not resume its opaque reasoning.

To delete one local thread and its derived context:

```bash
.venv/bin/python -m context_cli --thread research forget --yes
```

Reference deletion commits before artifact cleanup. A durable cleanup queue
retains failed deletions and incomplete artifact writes for retry. Repeating
`forget --yes` retries cleanup. Shared local artifacts remain while another
thread still references them. This is logical application deletion, not a claim
of secure erasure from filesystem snapshots or remote provider systems.

The local HTTP service binds only to loopback and rejects other origins and
oversized/malformed bodies. It is a single-user service; do not expose it as a
public multi-user server.

## Validation and next work

The final implementation suite passed **1,848 tests**, with the same three
dependency/fork warnings present in the 1,761-test baseline. Independent review
findings were reproduced, fixed, and rechecked. Wheel-building and installed-wheel
startup checks are included in that suite.

An additional end-to-end subscription check used two fresh Astra episodes with
no existing Engram source: the first recorded a teal garden bench; the second
recalled its color from the automatically archived exchange. Four original
messages were saved and two were selected for the second response. This is a
small integration check, not the long-session quality evaluation below.

Tests cover 10,000 synthetic compile cycles, full-payload admission, mandatory
overflow, ordered tool/opaque items, idempotence and restart, correction capture,
chronological referents, source invalidation, deletion recovery, HTTP parsing,
subprocess isolation, provider deadlines, and API transport fixtures.

The source-grounded 100-question human continuity pilot from the design has not
been run. Neither budget tests nor the small live smoke establish that quality
gate. Rich Engram recall parity, model-derived continuity, local-model tokenizer
validation, category/sheaf influence, and Lighthouse networking remain separate
work described in the [design](superpowers/specs/2026-09-05-dynamic-context-runtime-design.md).
