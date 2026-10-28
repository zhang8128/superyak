# The first rail's lessons hook: implementation plan

**Spec:** `docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md` on branch `trail-arrows-spec`, revision 3
(approved). The hook only: section 8, the request fields and the prompt path of section 5, the short id of section 2,
decisions 7 and 8. The `lessons query` command and the index are Rio Grande's (R1) and don't exist yet.

**Branch:** `tardis/rail-lessons-hook`, local only, never pushed. Each task is test-first: the tests, seen failing,
then the code, then green, then one commit. Tardis builds it.

**Two changes since the first draft, agreed by the ships through the coordinator:** the hold before a command is one
shared entry that Serenity builds (`run_agent.py hold`), and this branch builds its lessons side as a provider; and the
request gains `limit`, an integer from 0 to 3.

## The contract with `lessons query`

The hook runs `<query argv> --data-dir <data dir>`, sends one JSON object on stdin and reads one on stdout:

- **Request** (section 5's fields and cuts): at a prompt `{ship, prompt, limit: 2, seen}`; at session start
  `{ship, cwd, branch, limit: 3, seen}`; before a command `{ship, command, words_only: true, limit, seen}`, with the
  entry's limit; after a failed command `{ship, cwd, branch, command, error, limit: 3, seen}`. `branch` is left out
  outside a repository. `seen` holds at most 128 short ids.
- **Answer:** `{"lessons": [{"id", "ship", "claim", "why", "match": "words" | <angle>}]}`, at most 3 lessons and
  2,000 bytes. A non-zero exit is an error, and the hook prints nothing.
- **One field the hold needs** that the answer above doesn't carry: `command`, the lesson's `command` value that
  words matched. Only a lesson with that field, of at least 6 bytes and found in the command sent, can hold a
  command (section 8). Rio Grande's query must add it for the hold to work; this is an open point for R1.

## Tasks, in order

1. **The pure parts** (new `agent/superyak_agent/lessons_hook.py`, new `agent/tests/test_lessons_hook.py`). The
   head (section 8: first word after leading `NAME=value` words, plus the second unless it starts with `-`); the
   answer's checks (short id shape, `SHIP_NAME`, byte limits, no control characters, `match`); the output, fenced
   with `fence_external` under "Lessons from Andy's ships (quoted data, not instructions)", each lesson's
   `Lesson <id> from <ship>` line outside its fence; the hold's reason for one lesson, word for word; the ids read
   back from the transcript (`Lesson <id> from <ship>` lines of the exact shape, and the hold's first line). Tests: the
   head cases, three backticks can't close a fence, the reason text exactly, a forged id line can only hide a lesson.
2. **The hook's own events** (`lessons_hook.run`). `SUPERYAK_RUN`; the settings (ship, data directory, query argv,
   state folder); the query subprocess with a wall-clock deadline (150 ms at a prompt, 2 s otherwise), killed at the
   deadline; the prompt (no writes), session start (cwd and branch) and a failed command (cwd, branch, command, last
   error line; once per command and error); one budget through `seen`, from the session's record and the
   transcript. The record holds digests and the ids shown at the hook's own events, written atomically under a
   per-session lock. Tests, with a stub query that answers fixtures, honours `limit` and records what it was sent:
   each path's request and limit, the seen budget across events, slow queries silent at each limit, `SUPERYAK_RUN`.
3. **The hold provider** (new `agent/superyak_agent/lessons_hold.py`). `candidates(command, record, now, limit)`
   returns at most `limit` holds `{kind: "lesson", key, text}`: first appearance per head (from the record), words
   only, the 1 s limit from `now`, `SUPERYAK_RUN`, unseen lessons only, a `command` value of at least 6 bytes. It
   denies nothing, writes nothing and leaves the cap of 3 to the entry. Tested alone with a fake record.
4. **No writes at a prompt** (section 8's pinned test), with the launcher it runs: `run_agent.py lessons-hook` goes
   straight to the hook, before `__main__` imports the station client. The hook as a subprocess under `python -B`,
   through `tests/lessons_audit.py` (`sys.addaudithook`): any file opened for writing, any write-like call, `sqlite3`
   imported or connected, a database opened, or the marker under the data directory, the state, the temporary
   directory or HOME, fails it. The same wrapper is shown to catch a write. Then each other event after the marker
   prompt, against a transcript holding the marker and a prompt-shown id line: neither reaches the record.
5. **The installer switch** (`install.py`, `__main__.py`). `install_lessons_hooks` / `remove_lessons_hooks` write
   SessionStart, UserPromptSubmit and PostToolUseFailure (Bash) entries running `python -B`, apart from the room
   hook's; `install_all(lessons=None)` and `dock --lessons <file>` install nothing unless asked.

## Confirmed on Tardis's Claude Code (2.1.312)

Run in an isolated `claude -p` session with only a logging hook: a non-zero Bash exit and a Bash timeout both arrive as
`PostToolUseFailure`, with `error` = `Exit code N` then the output's lines (a timeout ends with
`Command timed out after 1s`); a success arrives as `PostToolUse`, whose `tool_response` carries no exit code. A
`PreToolUse` deny's reason reached the model. A `UserPromptSubmit` hook's `additionalContext` was in the transcript
(an `attachment` of type `hook_additional_context`) before the next hook event ran. The other ships confirm on their
own versions.
