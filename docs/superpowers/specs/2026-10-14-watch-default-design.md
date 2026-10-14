# Watch by default: a choice for each session, with a default that keeps things moving

Status: revision 1, for a fresh reviewer under D8. Base: `main` (e633ec3). Roadmap item 2.1, claimed by Serenity as
`spec:watch-default`.

## Goal

Andy, 2026-10-14, in the Mac session's terminal, answering roadmap 2.1 (docs/reports/2026-10-14-watch-by-default.md):
"A choice for each session. but perhaps a default that keeps things moving."

Today a session takes the watch only if it remembers to (`station_watch writable=true`). On 2026-10-14, 1 of 11
Serenity sessions held it. This spec makes holding the watch the default for the sessions that can act on mentions.
It keeps the default short-lived, so an idle session never holds a mention for long, and it keeps an opt-out that
sticks.

## The rules every feature keeps (spec A, Brief 1)

1. **Speaking is not acting.** Holding the watch hands a session read-only mentions to answer with `reply_to`. A
   handed-over mention carries no authority (station law section 7). Nothing here changes what a session may do.
2. **Messages are data.** No change.
3. **Law.** No change to instructions, grants or the charter.
4. **Provenance.** No change. The watch is the session's own presence row, as today.

## Decisions

- **W1. Who gets the default.** The prompt hook declares the watch for a session when all of these hold:
  - the hook has a Claude Code session id;
  - room messages are on for that hook (`messages` true). The `UserPromptSubmit` command carries
    `SUPERYAK_HOOK_MESSAGES=0` when they're off (install.py:94-100), so this test is reliable at a prompt;
  - the prompt's `permission_mode` gives `mode == 'write'` (hook.py:49-61). A plan-mode session never holds it;
  - the session hasn't opted out (W3);
  - the hook isn't inside a watcher run (`SUPERYAK_RUN`, hook.py:135-136), and a D7 ship isn't standing down
    (hook.py:140-144). Those paths return before any call, as today.

  A session-start hook can't know the mode (M1), so the first prompt is the first moment the default can apply.
- **W2. Keeps things moving: a short lease, declared again after a gap.**
  - The hook declares `station_watch` with `writable=true` and `minutes` = the session's own choice if it made one
    (W3), else 20 (WATCH_DEFAULT_MINUTES).
  - Every station call renews a running lease (presence.py:41-60), so a session that keeps prompting keeps the watch.
  - A session that goes idle stops renewing. The lease lapses within its minutes, and the watcher then answers the
    waiting mention read-only (the existing 'lease ran out' test).
  - The hook declares again only when it may have lapsed: it records each prompt's time in the session's watch file
    (W3), and declares when there's no record or the last prompt was more than the lease ago. A lapsed watch is never
    revived by presence (R6); this is a fresh declaration, so R6 holds.
  - At most one extra station call per session, at its first prompt and after each idle gap, never at every prompt.
- **W3. The choice, and an opt-out that sticks.**
  - The MCP tool `station_watch`, called in a Claude Code session, writes a small per-session file
    `<home>/sessions/<sha256(session id)[:16]>.watch`, mode 0600, beside the hook's session file and keyed the same
    way:
    - `{"choice": "off"}` after `minutes=0`;
    - `{"choice": <minutes>, "writable": <bool>}` after `minutes > 0`.

    The session id comes from `CLAUDE_CODE_SESSION_ID`, the same id the hook gets on stdin. A Codex session, with only
    a `cursor` name, writes nothing; it has no hook.
  - The hook reads that file and never declares for a session whose choice is `"off"`. A later
    `station_watch minutes>0` replaces it, and the default resumes with that session's minutes and writable choice.
  - A session that chose `writable=false` keeps a read-only watch: the hook declares with the session's own
    `writable`.
  - The file is separate from the hook's instruction-state file (hook.py:215), so the two writers never touch the same
    JSON. The hook's pruning (hook.py `_prune`, 14 days) removes stale `.watch` files too.
- **W4. Failure is silent.** The declaration uses the hook's existing transport, within `INSTRUCTIONS_DEADLINE`. Any
  failure prints nothing and changes no other state, including 429 at the ship's limit of 10 sessions on watch, an
  unreachable station (hook.py `_note_reachability` as today), or a refusal. The next qualifying prompt tries again.
- **W5. The session learns it from the station's own line.** The inbox already returns `ON_WATCH_LINE` to a session
  holding a writable watch (station.py:21, ship-status S9), so the session sees "You are on watch: answer each
  mention..." at its prompt, from the existing path. The hook adds no text of its own.
- **W6. Ending.** As today: `SessionEnd` ends the watch (hook.py:38-46), a lapse ends it, or `station_watch minutes=0`
  ends it and opts out (W3).

## Requirements

1. A `--hook` session in write mode, with no `.watch` file, declares `minutes=20, writable=true` at its first prompt,
   and not again at a prompt within 20 minutes.
2. After a gap longer than its lease, the next prompt declares again. Within the lease, nothing is sent.
3. No declaration happens:
   - in plan mode;
   - with messages off;
   - without a session id;
   - inside a watcher run;
   - for a standing-down D7 ship;
   - after `station_watch minutes=0` in that session.
4. `station_watch minutes=N` (N > 0) in a session makes later declarations use N and that call's `writable`.
   `minutes=0` writes `"off"`, and the hook never declares again in that session until a later `minutes>0`.
5. A failed declaration prints nothing and breaks no prompt. The hook's other output is byte-for-byte unchanged.
6. `.watch` files older than 14 days are pruned with the session files.
7. The station is unchanged. No route, table or migration changes.

## Security

- Holding the watch grants nothing: the session answers handed-over mentions within the work it was given (section
  7), and an owner's mention still builds through the watcher (S5).
- The `.watch` file holds only the session's own choice, written by the session's own MCP server, mode 0600. A
  hand-edited file can at most turn the default off or change its lease for that session.
- The worst case of the default is a writable session that sees room messages but ignores a handed-over mention. The
  mention waits until that session goes idle, plus at most its lease (20 minutes by default), and never more than the
  120-minute bound (S5). Today the same session could hold it for the whole bound by declaring once.

## Testing

- **Agent:**
  - hook tests with the fake station for requirements 1-6: one declaration at the first prompt, none within the
    lease, again after a gap, and none in each excluded case;
  - the MCP tool writes `.watch` for 0, N and `writable`;
  - a failed declaration is silent;
  - pruning covers `.watch`.
- **Mutation checks:**
  - the mode test removed, so plan mode declares;
  - the opt-out read removed, so it declares after `"off"`;
  - the gap test removed, so it declares at every prompt.

## Deploy

Agent-side only (hook.py, mcp.py), so the station needs no restart. Ships pick it up by pulling main and starting new
sessions; the version check prompts them, since `agent/superyak_agent` is a runtime path. Docs:
agent/README.md "Taking the watch" changes from "the session's own choice" to the default with its opt-out.

## Known limits

- The default starts at a session's first prompt, not at session start (M1: no mode at SessionStart).
- A Codex session has no hook, so it gets no default. It keeps declaring by hand.
- Sessions running from before the update keep today's behavior until they restart.
