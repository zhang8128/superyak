# Dynamic context runtime

This opt-in runtime automatically archives conversations and selects relevant
originals before each invocation. It includes terminal coding, terminal chat, a
local browser chat, source inspection, and explicit correction/pin controls. It leaves the
existing daemon, MCP server, and current Codex conversations unchanged.

## Terminal coding

Start a real coding task from the implementation worktree:

```bash
cd /Users/kairos/Projects/engram/.worktrees/dynamic-context
ENGRAM_HOME=/Users/kairos/Projects/engram \
  /Users/kairos/Projects/engram/.venv/bin/python -m context_cli \
  --instance engram --thread parser-fix code --repo /path/to/your/repo \
  'Fix the parser bug and run the relevant tests'
```

Replace the repository path, task name, and task text. This runs native Codex
editing and shell tools with your managed ChatGPT login and selected model
(`gpt-6-astra` by default). It streams command results, file changes, and progress
in the terminal. No API key or browser is needed. If `--thread` is omitted, the
command creates and prints a task name.

Every episode receives the original task, your explicit corrections, a bounded
repository snapshot, its latest checkpoint, and relevant archive/Engram evidence.
Codex can search earlier task notes and tool-result excerpts, then read original
events or output artifacts by ID. You do not need to call memory tools yourself.
The search index covers bounded excerpts; it is not an exhaustive full-output
search. External Engram retrieval remains the lexical adapter described below.

When Codex checkpoints with work remaining, the runner starts another fresh
episode automatically. A completed task returns exit code **0**. An episode
limit, interruption, transport error, or request for your input returns **2**
and prints the exact resume command. Configuration errors return **1**.
The resume command is also printed before work starts, for crash recovery.

```bash
ENGRAM_HOME=/Users/kairos/Projects/engram \
  /Users/kairos/Projects/engram/.venv/bin/python -m context_cli \
  --instance engram --thread parser-fix code --repo /path/to/your/repo --resume
```

Resume retains the original task. Add an answer or a durable constraint with
the existing correction command, then resume:

```bash
ENGRAM_HOME=/Users/kairos/Projects/engram \
  /Users/kairos/Projects/engram/.venv/bin/python -m context_cli \
  --instance engram --thread parser-fix correct public-api \
  'Keep the existing public function signatures'
```

Use a new task name for a new goal. Resuming a completed task does no further
work. Task identity is tied to the canonical repository directory and its
filesystem identity. Renaming/replacing it requires starting a new task.
Keep the printed resume command if using custom archive or memory paths: it
includes their resolved locations and the run limits.

The defaults allow **20 episodes**, **900 seconds per episode**, and **24 completed
command/file/archive-tool operations per episode**. The runner asks for a
checkpoint near the step limit or after **32,000 observed input tokens**, and
interrupts at the step limit or **48,000 observed input tokens**. Override these
with `--max-episodes`, `--episode-seconds`, `--max-steps`, `--soft-tokens`, and
`--hard-tokens` after `code`. Provider transport also caps total protocol bytes.

**These are episode controls, not a guarantee that Codex context never fills.**
Usage arrives after an internal request and can overshoot a threshold. Codex
still manages its own internal context and compaction. Input-envelope estimates
and `--max-output` do not constrain every native model call. The coding command
rejects `--strict` and API mode rather than changing billing or overstating its
control. It currently has no interactive mid-episode steering UI; Ctrl-C pauses
the task, and corrections plus resume continue it.

Coding uses a workspace-write sandbox, including Codex's normal temporary
directories, with network disabled by default. Codex
retains native repository instructions and saved user approval rules. Actual
permission requests forwarded by Codex are shown in the terminal for a one-time
decision; noninteractive runs decline them. External MCP servers, plugins,
hooks, and automatic subagents are disabled for this runner. The browser chat
retains its separate read-only, tool-disabled subscription adapter.

Visible provider events are archived before terminal presentation; large events
are stored as artifacts. Generated checkpoints are explicitly fallible notes,
not new user instructions. An interrupted or failed episode is **not replayed
automatically**, because commands may already have changed files. Explicit resume
restores that uncertainty and asks Codex to inspect actual state before retrying.
An episode deadline stops the local app-server process group; background or
remote effects cannot be assumed undone.

`status`, `inspect`, `correct`, `unpin`, and `forget --yes` work with the same
`--thread` and instance/data selectors. Status includes durable coding progress;
inspection shows the selected source IDs and input-envelope estimate for the
last episode. Forget removes the local task archive and its unshared artifacts.

Terminal verification included a live Astra task that created `calc.py` and two
passing unittest cases in a disposable repository. A second live task retrieved
an original synthetic note through the archive tools, created `greet.py`, saved
a continuation checkpoint, and automatically started a fresh episode that
inspected and tested the files. Its test with three name cases also passed on an
independent rerun. These smokes used only synthetic memory and the subscription
adapter. Scripted tests cover twenty-episode continuity, interruption, recovery,
source revocation, malformed checkpoints, and bounded archive access. Independent
review also verified that closing the host stops a native command running in a
separate macOS process group before it can make a delayed file write.

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

### Opt into Lighthouse sources for chat

An existing named receiver can use its configured Lighthouse publishers in
terminal or browser chat. Configure the receiver and publisher policies using
the [receiver guide](lighthouse-receiver.md), then declare both context and
purpose for the chat process:

```bash
ENGRAM_HOME=/Users/kairos/Projects/engram \
  /Users/kairos/Projects/engram/.venv/bin/python -m context_cli \
  --instance engram --lighthouse-context memory/technical \
  --lighthouse-purpose session-recall serve
```

Replace `serve` with `chat` for the terminal. The declaration applies to every
thread handled by that process. Each consultation sends the explicitly chosen
publishers a bounded retrieval query made from the current message (up to 1,500
characters) and the latest two dialogue excerpts (up to 250 characters each).
Context and purpose are never inferred from conversation text. Missing flags,
missing settings, or disabled settings leave Lighthouse inactive. Coding mode
does not accept these flags. A different `--engram-db` cannot borrow a named
receiver's settings; `--no-engram` disables only local lexical retrieval.

Shared accounts remain optional evidence under the same compiler budget. They
carry publisher-qualified IDs, layer, lane, audiences, a content digest, and a
version of the supplied account. The receiver writes a content-free preparation
receipt before exposing the account to the compiler. After counting, it re-reads
selected shares through the publisher and rechecks receiver settings and all
delivery grants. Changed, denied, or unavailable shares are removed and the
request is counted again. The runtime stops an unfinished tool episode if it
already depends on a withdrawn source, including a source read through a tool.

The existing settings limit consultation to eight publishers and five shares,
with 32 KiB of content in total. A dispatch revalidation pass shares one socket
deadline across its reads (two seconds by default, at most ten). Context
recompilation is limited to three attempts. All Lighthouse reads in an active
turn also respect its remaining time; source-page validation stops at its first
invalid dependency. A malformed peer response leaves healthy peers eligible,
although a peer exhausting the shared deadline can suppress the whole pass.
No retrieval or validation failure
causes an automatic provider retry or discards the local conversation.

The manifest's `source_coverage` lists preparation receipts and diagnostics;
`source_dispatch` lists receipts for the final dispatch admission. Receipt
extensions distinguish `source_preparation`, `model_dispatch`, and
`source_inspection`. Here `injected` describes delivery across that named
boundary. It does not prove generation succeeded or that a model used a memory.
In API mode, preflight counting can already send supplied content to the
provider; withdrawal cannot undo that earlier disclosure. Checks authorize
request construction, not an atomic lock on another process's future policy.

Source bodies stay in the turn's working memory. Receipts and manifests retain
metadata, not the bodies; `archive_search` does not index neighbor content.
`archive_read` and the browser's source inspector fetch an original again under
current permissions, using only a handle found in that thread's recent eight
receipts. Old or unavailable handles can fail inspection. Raw Lighthouse tool
pages are omitted from durable tool-event content. The ordinary visible answer
and provider response are still archived and can contain quoted or derived
material; withdrawal does not erase answers already received. `forget --yes`
removes the thread's receipts together with its existing archive. Inspection
shares the thread lease with chat and forgetting.

Validation uses deterministic recording providers and a real disposable Unix
socket publisher. It establishes delivery, denial, withdrawal, retention, and
budget behavior; it does not establish answer usefulness. No live grants or
running services are configured by installing this implementation.

### Local archive and Engram sources

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
Within an unfinished tool episode, previously supplied external sources and
external source pages returned by archive tools remain dependencies. If one
changes or becomes unavailable, the runtime archives and stops that episode
before further generation. Start a new turn to use the current sources; the
runtime does not silently replay old tool text or derived provider items.

Selected dialogue renders chronologically, regardless of retrieval score. The
immediate completed exchange and explicit user notes remain required. Original
roles, source IDs, versions, and excerpt markers stay attached. No recalled
instruction becomes a developer instruction, and mere selection does not
reinforce a memory.

Archive ranking has a 50 ms query deadline, checked periodically by SQLite and
again when the query returns. If it expires, chat and coding continue with their
recent dialogue, current goal, and explicit notes; manifests report incomplete
archive coverage. Archive search tools also return an explicit incomplete result.
Large archives first probe the query's terms for distinctive matches, then rank
that smaller union; broad-only queries return recent matches. Small archives
retain BM25 ordering. This substantially reduced repeated-history timeouts in
the [fixed retrieval benchmark](reports/2026-09-06-context-retrieval-evaluation.md).
When a distinctive term exists, broad-only matches are excluded, so incidental
rare words can still reduce recall. The deadline is
cooperative, not an exact 50 ms wall-clock guarantee: lock waiting, native work
between progress callbacks, and OS scheduling can add elapsed time.

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

New context manifests retain the original correction event ID and version.
Inspecting an earlier call therefore shows the correction used by that call,
even after the note is revised or unpinned. Older manifests that recorded only
a mutable `state:<key>` do not gain this provenance retroactively.

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

The retrieval/evaluation follow-up passed **1,973 tests** across the repository,
with three existing dependency/fork warnings. An existing category-validation
test was made deterministic after its 5 ms deadline expired before validation
under load; production category behavior was unchanged. Independent review
findings were reproduced, fixed, and rechecked. Wheel-building and installed-wheel
startup checks are included in the full suite. Browser checks covered historical
correction inspection after revision/unpin, thread reload, and new conversations.

An additional end-to-end subscription check used two fresh Astra episodes with
no existing Engram source: the first recorded a teal garden bench; the second
recalled its color from the automatically archived exchange. Four original
messages were saved and two were selected for the second response. This is a
small integration check, not the long-session quality evaluation below.
The completion run also verified a fresh Astra subscription response using only
a synthetic prompt and no existing Engram source.

Tests cover 10,000 synthetic compile cycles, full-payload admission, mandatory
overflow, ordered tool/opaque items, idempotence and restart, correction capture,
chronological referents, source invalidation, deletion recovery, HTTP parsing,
subprocess isolation, provider deadlines, and API transport fixtures.

The standalone runtime replay exercises actual archive/compiler/tool
continuations through a deterministic synthetic provider:

```bash
.venv/bin/python scripts/context_runtime_replay.py > context-runtime-replay.json
```

Its default workload executes 10,000 synthetic generation calls and 5,000
paginated artifact reads while the persisted archive grows. It checks the
counted/dispatched payloads, configured budget, active tool groups, and candidate
bounds, and reports incomplete archive retrievals caused by the search deadline.
Its allocation figures measure Python allocations only; process resident memory
requires a separate sampler. Its byte counter is an artificial test profile, not a model
tokenizer; this run consumes no model allowance and measures no answer quality.

The [completion report](reports/2026-09-06-context-runtime-completion.md) records
the successful 10,000-call replay: all counted payloads matched dispatch, all
budgets passed, and sampled RSS grew by 0.484 MiB as the archive reached 25,000
events. **85.47% of archive searches hit the deadline** on its repeated-text
workload. The [retrieval follow-up](reports/2026-09-06-context-retrieval-evaluation.md)
reduced this to **0.66%** on the same 10,000-call workload. A separate fixed
100-question source-selection repeat at 25,000 routine entries improved from
**10/100 to 99/100** with all expected originals supplied; the remaining timeout
is retained in the report. Source availability does not establish answer quality.

The [preliminary continuity capture](reports/2026-09-06-context-continuity-results.md)
saved 100 dynamic-context answers and 100 answers using actual LocalAgent recall
and formatting. Expected-source citation coverage was 99/100 and 96/100,
respectively, with no unavailable citation IDs. The append-and-compact comparator
timed out during preparation and supplied no scored answers. Human ratings remain
unset in the [review page](reports/2026-09-06-context-continuity-review.html);
the source-grounded human continuity gate from the design has not passed.
Rich Engram recall parity, broader continuity evaluation, local-model tokenizer
validation, category/sheaf influence, and Lighthouse networking remain separate
work described in the [design](superpowers/specs/2026-09-05-dynamic-context-runtime-design.md).
