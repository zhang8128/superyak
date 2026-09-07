# Ask another Codex session

Superyak can list this account's local Codex sessions, queue a question for
one, and retrieve its matching answer. It uses Codex's native message queue and
conversation history. Tested with Codex CLI **0.153.4**; the queue API is
experimental. Both sessions must use the same local Codex home.

## In Codex

With the `superyak_sessions` MCP server connected, use:

1. `sessions_list(search="project or session name")` to find an exact session ID.
2. `session_ask(target_session="UUID", question="What did you find?")` once.
3. `session_result(request_id="returned ID", wait_seconds=20)` to read its answer.

The recipient sees an attributed peer question in its conversation and answers
normally. It needs no new tool to reply. The answer is matched by Codex's client
message ID; unrelated conversation text and tool output are not returned.
The requester can continue other work and look up the answer later.

The queue does not interrupt a busy turn. An open idle session normally notices
external input within about ten seconds; a busy session processes it after its
current turn. Closed or interrupted sessions may need to be resumed. Discovery
reports availability as unknown because a metadata connection cannot determine
another process's live status. This does not connect remote/cloud sessions or
override a session's existing model, sandbox, tools, or approval settings.

Questions and answers remain in Codex's ordinary local conversation history.
They are not automatically copied into an Engram memory store or published by
Lighthouse. Peer messages do not grant new human authorization. Avoid automatic
back-and-forth acknowledgments; ask for a concrete answer and collect it.

## From an already-open session or terminal

After the local launcher is installed:

```sh
superyak-sessions list --search parser
superyak-sessions ask TARGET_UUID 'Which parser file did you change?'
superyak-sessions result REQUEST_ID --wait 20
```

Before installing a launcher, run `uv run --project /absolute/path/to/superyak/engram
python -m session_cli` followed by the same arguments. `make sessions` lists
sessions from the monorepo; `SESSION_ARGS` supplies other commands.

CLI calls made inside Codex use `CODEX_THREAD_ID` for attribution. MCP calls use
the caller's `threadId` request metadata, which takes precedence over inherited
environment variables. An ordinary terminal without either identity is marked
as an unattributed local caller. The server operates with the OS user's Codex
access; request IDs are correlation handles, not cross-user access tokens.

## Install the tools

From the monorepo root, after `make setup-engram`:

```sh
codex mcp add superyak_sessions -- "$PWD/engram/.venv/bin/superyak-sessions" mcp
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/engram/.venv/bin/superyak-sessions" "$HOME/.local/bin/superyak-sessions"
```

Keep `~/.local/bin` on your shell's `PATH`. The launcher and MCP registration
use this checkout's virtual environment, so keep the checkout at that path.

Start a new Codex session or reconnect MCP to load the three tools. Existing
sessions can already receive native queued messages and use the CLI. Installing
the server does not replace their currently loaded tool catalog.

## Results and limits

`queued` and `running` are pending states. `completed` includes the matching
answer. `failed`, `interrupted`, and `completed_without_answer` report no usable
answer. `submission_unknown` means an acknowledgment was lost: keep the request
ID and check it rather than sending again. The bridge never retries a send.

Result lookup inspects ten recent turns at a time. `searching` returns
`next_cursor` for older history; pass it as `cursor` (CLI `--cursor`).
`not_found` can mean a visibility delay or missing history and does not prove
the question was never accepted. Session listing also uses `next_cursor`.
`pending_unknown` means the bounded queue scan was incomplete or the matching
turn has no recorded end. Codex can label a turn owned by another process as
interrupted while it is still running; the bridge preserves that uncertainty.
A crashed or older interrupted turn without an end timestamp can also remain
in this state. Check again later without resending the question.
Questions are limited to 8,000 UTF-8 bytes, answers to 64 KiB (explicitly marked
when truncated), waiting to 30 seconds, and each transport to 2 MiB of output.
No unbounded history load or model retry is performed.

The test suite covers ambiguous submission, exact correlation, partial answers,
self-send rejection, and protocol bounds. A separate CI job installs pinned
Codex and tests busy and idle recipients using two real Codex processes and a
synthetic local model endpoint, without credentials or live user sessions.
The [installation and real-model verification record](reports/2026-09-07-session-messaging.md)
documents the measured exchange and its limits.
