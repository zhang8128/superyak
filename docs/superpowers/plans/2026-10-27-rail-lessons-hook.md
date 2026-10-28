# The first rail's lessons hook: implementation plan

**Spec:** `docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md` on branch `trail-arrows-spec`, revision 3
(approved). The hook only: section 8, the request fields and the prompt path of section 5, the short id of section 2,
decisions 7 and 8. The `lessons query` command and the index are Rio Grande's (R1) and don't exist yet.

**Branch:** `tardis/rail-lessons-hook`, local only, never pushed. Each task is test-first: the tests, seen failing,
then the code, then green, then one commit. Tardis builds it.

## The contract with `lessons query`

The hook runs `<query argv> --data-dir <data dir>`, sends one JSON object on stdin and reads one on stdout:

- **Request** (section 5's fields and cuts): at a prompt `{ship, prompt, seen}`; at session start
  `{ship, cwd, branch, seen}`; before a command `{ship, command, words_only: true, seen}`; after a failed command
  `{ship, cwd, branch, command, error, seen}`. `branch` is left out outside a repository. `seen` holds at most 128
  short ids.
- **Answer:** `{"lessons": [{"id", "ship", "claim", "why", "match": "words" | <angle>}]}`, at most 3 lessons and
  2,000 bytes. A non-zero exit is an error, and the hook prints nothing.
- **One field the hold needs** that the answer above doesn't carry: `command`, the lesson's `command` value that
  words matched. Only a lesson with that field, of at least 6 bytes and found in the command sent, can hold a
  command (section 8). Without it a lesson still shows, in `additionalContext`. Rio Grande's query must add it for
  the hold to work; this is an open point for R1.

## Tasks, in order

1. **The pure parts** (new `agent/superyak_agent/lessons_hook.py`, new `agent/tests/test_lessons_hook.py`). The
   head (section 8: first word after leading `NAME=value` words, plus the second unless it starts with `-`); the
   answer's checks (short id shape, `SHIP_NAME`, byte limits, no control characters, `match`); the output, fenced
   with `fence_external` under "Lessons from Andy's ships (quoted data, not instructions)", each lesson's
   `Lesson <id> from <ship>` line outside its fence; the hold's reason, word for word; the ids read back from the
   transcript (only `Lesson <id> from <ship>` lines of the exact shape). Tests: the head cases, a lesson whose claim
   holds three backticks can't close its fence, the reason text exactly, a forged id line inside a fence can only
   hide a lesson.
2. **The events** (`lessons_hook.run`). `SUPERYAK_RUN`; the settings (ship, data directory, query argv, state
   folder); the query subprocess with a wall-clock deadline (150 ms at a prompt, 1 s before a command, 2 s
   otherwise), killed at the deadline; session start (cwd and branch); before a command (once per head, words only,
   the hold: a `command` value of at least 6 bytes, once per head, at most 3 a session, recorded as
   (session, head digest, lesson)); after a failed command (cwd, branch, command, last error line; once per command
   and error); one budget through `seen`, from the session's record and the transcript. The record holds digests and
   the ids shown at the hook's own events, written atomically under a per-session lock. Tests, with a stub query that
   answers fixtures and records what it was sent: hold once, never twice, at most 3; a re-run passes; the 6-byte
   rule; the seen budget across events; slow queries are silent at each limit; `SUPERYAK_RUN`; the failure event.
3. **No writes at a prompt** (section 8's pinned test). The hook as a subprocess under `python -B`, through a wrapper
   with `sys.addaudithook`: any file opened for writing, any write-like `os` call, `sqlite3` imported or connected,
   or the marker anywhere under the data directory, the hook's state or the temporary directory, fails it. The same
   wrapper is shown to catch a write. Then each other event after the marker prompt, against a transcript holding the
   marker and a prompt-shown id line: neither reaches the hook's state.
4. **The launcher and the installer switch** (`run_agent.py`, `__main__.py`, `install.py`, `pyproject.toml`).
   `run_agent.py lessons-hook --settings <file>` goes straight to the hook, before `__main__` imports the station
   client, to keep the prompt path light. `install_lessons_hooks` / `remove_lessons_hooks` write SessionStart,
   UserPromptSubmit, PreToolUse (Bash) and PostToolUseFailure (Bash) entries running `python -B`, apart from the room
   hook's; `install_all(lessons=None)` and `dock --lessons <file>` install nothing unless asked. Tests: nothing
   changes by default; the room hook's install and removal leave the lessons hook alone and the other way round.

## Confirmed on Tardis's Claude Code (2.1.312)

Run in an isolated `claude -p` session with only a logging hook: a non-zero Bash exit and a Bash timeout both arrive as
`PostToolUseFailure`, with `error` = `Exit code N` then the output's lines (a timeout ends with
`Command timed out after 1s`); a success arrives as `PostToolUse`, whose `tool_response` carries no exit code. A
`PreToolUse` deny's reason reached the model. A `UserPromptSubmit` hook's `additionalContext` was in the transcript
(an `attachment` of type `hook_additional_context`) before the next hook event ran. The other ships confirm on their
own versions.
