# Lessons hold at tool calls

Draft 1, 2026-10-30, Serenity. Board: `spec:lesson-holds-on-tool-calls` (all hands). For a fresh reader (law section 3);
Andy can veto. Built from the all-hands thread of 2026-10-30 (Serenity cc931987, Rio Grande 8cbea18b and 3af2f123,
Tardis 52f03275 and a09fdd5e), with the measurements below.

## Why

A lesson is shown before the act it is about. Today the one act the rail can hold is a Bash command: the PreToolUse
entry `run_agent.py hold` answers only `tool_name == 'Bash'` (agent/superyak_agent/hold.py:39-40), and it is installed
under the matcher `Bash` (agent/superyak_agent/install.py:164). A lesson whose act is a tool call (posting to the
station, claiming a board item, asking the person a question) can surface only through prompt words (lessons.py:558),
which come before the act or never. Four of Serenity's drafted lessons and one of Rio Grande's are about such acts: the
20,000-character cut on a post, a check-in that leads with the purpose, a blocking question in a watch, and taking a
lapsed claim. (A fifth of Serenity's, about the Edit tool, is out of scope: see "Before it is built".)

## Design

Two places can hold a tool call, and this spec uses each where it fits.

- **The station's own tools hold in the station's MCP server.** `mcp__station__station_post` and
  `mcp__station__station_claim` are served by this repo's agent (agent/superyak_agent/mcp.py), a process that lives
  as long as the session. It already opens the session's record, the same file and lock the hold uses
  (`holds.record_path(home / 'sessions', CLAUDE_CODE_SESSION_ID)`, mcp.py:571), to fire a `claim` checklist once per
  item (mcp.py:561-584). So no PreToolUse entry is needed for these two tools, and no Python starts per call.
- **AskUserQuestion is built in,** so only a PreToolUse entry can hold it, as Bash is held today.

1. **The head is the tool's name.** For each of the three tools the command string the lessons provider sees is the
   tool's full name, and nothing from its input. A post's text (up to 20,000 characters) is never matched: a post that
   quotes `git rev-parse`, or one that discusses a lesson, is not held by that lesson (Tardis, point 1).
   `lessons_hook.head` of one word is that word (lessons_hook.py:138-149), so the provider `lessons_hold.candidates`
   (lessons_hold.py:39) is called as it is.
2. **Matching is unchanged.** A `command:` value holds when it is contained in the head and is at least HOLD_BYTES (6)
   bytes (lessons.py:604, :28). There is no new line in the lesson format: a `tool:` line would be refused by every door
   and parser on the rail that has not taken it yet, which is a federation rollout for one field.
3. **Authoring rule: write the tool's full name** (Tardis): `command: mcp__station__station_post`, never
   `command: station_post`, which would also hold any grep of the station client. This goes in the lesson format notes
   too.
4. **A hold in the MCP server.** Before it posts or claims, the tool asks the provider with the session's record under
   its lock, as `_claim_lists` does. When a lesson is due, the tool does not post or claim. It answers with an error
   result holding the lessons' text and the line "Call it again if you still want it.", and the record notes the
   lessons as shown, so the next call goes through. Within the server the check is in process: `could_hold` first
   (about 0.2 ms), the full query only when it says yes. With no session id, or no ship home, it holds nothing, as
   `_claim_lists` falls back today. Any failure in the check lets the call through: a lesson never stops a post.
5. **A hold for AskUserQuestion** is the PreToolUse entry's: hold.py answers `tool_name == 'AskUserQuestion'` as it
   answers Bash, with the tool's name as the head and the deny's last line "Call it again if you still want it."
   in place of `RERUN` (hold.py:23). The entry gets the hold's `|| true` (install.py:84, :104): an older checkout
   rejects `hold` with exit 2, and exit 2 from PreToolUse blocks the call, which for a question would be every question
   (Tardis, point 2).
6. **Checklists.** At a tool call the hold asks only the lessons provider. The one checklist moment at a tool call,
   `when: claim` (before-work.md), already fires in the MCP server after the claim (mcp.py:577-584), and stays as it is.
   The other `when` lines are commands (`make`, `git`, `systemctl`), pushes, starts and timers.
7. **Subagents.** hold.py never holds a subagent's call (hold.py:41, D14), so a subagent's AskUserQuestion is not held.
   The MCP server can't tell a subagent's call apart: a subagent shares the session's MCP server and its
   `CLAUDE_CODE_SESSION_ID`. Untested: whether Claude Code marks a subagent's call in the MCP request. If it doesn't, a
   subagent's first post can be held, which costs it one more call. For the reader to judge whether that is acceptable,
   or whether the MCP hold should wait for such a mark.
8. **The install check.** `install.py:135-138` (N10) accepts a station hold only in a `Bash` entry. It accepts the hold
   in a `Bash` entry and an `AskUserQuestion` entry, each with the hold's timeout, and still refuses it anywhere else.

## Costs (measured)

- **The whole call**, spawn to exit, `run_agent.py hold`, 40 runs under a throwaway HOME (an empty
  `~/.superyak/station.json`, so the verdict is "act", acting.py:177-184):
  - the Mac (M-series, Python 3.15.0): p50 27.8 ms, p95 28.2 ms; with a 20,000-character input, p95 29.3 ms;
  - the Pi (Rio Grande, main 078fdd9c, load near 1): p50 50.9 ms, **p95 51.7 ms**.
- **Today, before this change,** the same call on a tool payload returns at hold.py:39 with no file I/O: Mac p95
  28.1 ms. So it is Python's start, and a tool-call hold costs what a Bash hold costs, on far fewer calls.
- **`could_hold` in process**, synthetic indexes, three `command:` values each and none matching: 100 lessons, p95
  0.23 ms; 1,000 lessons, p95 2.12 ms. The three ships' drafts come to about 95.
- **What each place costs.** AskUserQuestion pays this whole call, as a Bash command does; it is asked a few times a
  day. Posts and claims pay only the in-process check in the MCP server. Had they been held by PreToolUse too, a watch
  posting about 6 times an hour would pay about 0.3 s an hour on the Pi.
- **The full query** (about 360 ms at its bound, lessons_hold.py:13) runs only when `could_hold` says yes.
- **Two small, seen-once costs of reusing `command:`:** a Bash command that contains a tool's name (a grep of a
  transcript), and a prompt that names it (a review of the hook, lessons.py:558; Rio Grande). Each holds or surfaces
  the lesson once, and then it is seen.

## Before it is built

- **What the model is shown.** An MCP tool's error result reaches the model as any tool result does; check that it
  does for the station's tools on each ship's version. A PreToolUse deny's reason must reach the model for
  AskUserQuestion on each ship's Claude Code version, as Tardis confirmed for Bash on 2.1.312 in an isolated
  `claude -p` session with only a logging hook (docs/superpowers/plans/2026-10-27-rail-lessons-hook.md, "Confirmed on
  Tardis's Claude Code"). Where it doesn't, AskUserQuestion stays unheld on that version.
- **Tool names under 6 bytes** (Edit, Read, Write, Bash, Glob, Grep) can't be held by containment. They are out of
  scope.

## Tests

- The MCP server's post and claim: a lesson with `command: mcp__station__station_post` stops the first post with its
  text and "Call it again if you still want it.", posts nothing, and lets the second call through; the same for a
  claim.
- A post whose text contains a lesson's `command:` value is not held by it.
- A failure inside the check (an unreadable index, a record that can't be locked in time) lets the post through.
- No session id or no ship home: nothing is held.
- The PreToolUse hold answers AskUserQuestion with the tool's name as the head, and its deny ends with "Call it again
  if you still want it."; a call with `agent_id` set is not held; the checklist provider is not asked.
- The guard: an entry whose checkout exits 2 for `hold` can't block an AskUserQuestion.
- The install check accepts the hold in the `Bash` and `AskUserQuestion` entries and refuses it in any other.

## Not in this spec

- A `tool:` line in the lesson format. It is the way out if a real false hold appears.
- Edit and the other short-named tools.
