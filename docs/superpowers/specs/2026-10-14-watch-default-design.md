# Watch by default: a choice for each session, with a default that keeps things moving

Status: revision 3, **approved under D8**. Revision 1 (d0bdb21) had the fresh reviewer's verdict, APPROVE WITH CHANGES
(3 must-fix, 6 should-fix, 3 nits; room message 4a7d7857). Revision 2 (fe3f6b2) made all twelve, and the same reviewer's
re-check approved it with one should-fix and five nits, which this revision makes as written (see "Review map"). Base: `main` (3b48646, with
watch-default-docs merged). Roadmap item 2.1, claimed by Serenity as
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
  - the hook isn't inside a watcher run (`SUPERYAK_RUN`, hook.py:139), and a D7 ship isn't standing down
    (hook.py:144-148). Those paths return before any call, as today.

  A session-start hook can't know the mode (M1), so the first prompt is the first moment the default can apply.
- **W2. Keeps things moving: a short lease, declared again after a gap.**
  - The hook declares `station_watch` with `minutes` and `writable` set to the session's own choice if it made one
    (W3), else `minutes=20` (WATCH_DEFAULT_MINUTES) and `writable=true`.
  - Every station call renews a running lease (presence.py:41-60), so a session that keeps prompting keeps the watch.
  - A session that goes idle stops renewing. The lease lapses within its minutes, and the watcher then answers the
    waiting mention read-only (the existing 'lease ran out' test).
  - The hook declares again only when it may have lapsed. It records each qualifying prompt's time in its **own**
    file, `<home>/sessions/<key>.prompted` = `{"seen": <time>, "held": true|false}`. Only the hook writes it.
    - A **qualifying prompt** passes every W1 check, write mode included. At it the hook writes `seen` = now, and
      `held` = whether it declared or still holds the default.
    - A plan-mode prompt writes `.prompted` only when it ends a default the hook held (`held: false`).
    - An opted-out prompt, or one W1 excludes for any other reason, doesn't write it.
    - It declares when that file is missing, when `held` is false, or when `seen` is more than the lease ago. Every
      station call renews a running lease, so a prompt within the lease keeps it.
    - A lapsed watch is never revived by presence (R6). This is a fresh declaration, so R6 holds.
  - At most one extra station call per session, at its first prompt and after each idle gap, never at every prompt.
  - **Where it runs** (should-fix 4): after the instructions call and before the inbox call. That keeps the inbox
    advance the last network call (R4). It runs only if the hook isn't yet past `INSTRUCTIONS_DEADLINE`, with
    `INBOX_CALL_TIMEOUT`. A slow declaration can push the inbox past the deadline, as a slow instructions call can
    today. The messages then show at the next prompt, and nothing is lost, because the cursor doesn't advance.
  - **Plan mode lets go** (should-fix 5): the station defers to any writable watch whatever the session's mode
    (presence.py:69-71). So at a plan-mode prompt, if the hook holds the default for this session
    (`.prompted` says `held` and `.watch` holds no choice of the session's), it ends the watch with `station_watch
    minutes=0` and writes `held: false`. The next write-mode prompt declares again. A watch the session declared
    itself is left alone in plan mode: that was its choice. `held` is the hook's belief, not the station's live
    state, so after a natural lapse a plan-mode prompt may send one ending call for a watch that's already gone.
    That's harmless: the station's update is unconditional and idempotent.
- **W3. The choice, and an opt-out that sticks.**
  - The MCP tool `station_watch`, called in a Claude Code session, writes a small per-session file
    `<home>/sessions/<key>.watch`, mode 0600, where `<key>` is `sha256(session id)[:16]`, the hook's session-file key
    (hook.py:215). Only the MCP tool writes it:
    - `{"choice": "off", "seen": <time>}` after `minutes=0`;
    - `{"choice": <minutes>, "writable": <bool>, "seen": <time>}` after `minutes > 0`.

    The session id comes from `CLAUDE_CODE_SESSION_ID`, the same id the hook gets on stdin.
  - **Only for this session's own watch** (should-fix 6): the file is written only when the call targets this Claude
    Code session, that is, the `cursor` is absent or equals `CLAUDE_CODE_SESSION_ID`. A call naming another cursor
    manages that watch only and writes nothing. A Codex session, with only a `cursor` name, writes nothing; it has no
    hook.
  - The hook reads that file and never declares for a session whose choice is `"off"`. A later
    `station_watch minutes>0` replaces it, and the default resumes with that session's minutes and writable choice.
  - A session that chose `writable=false` keeps a read-only watch: the hook declares with the session's own
    `writable`.
  - **One writer per file** (must-fixes 2 and 3):
    - `.watch` is the MCP tool's, and the hook only reads it;
    - `.prompted` is the hook's;
    - the hook's instruction-state `.json` (hook.py:215) is unchanged.

    No two writers ever touch the same file, and each write is whole (`write_private`).
  - **Pruning:** `_prune` (hook.py:230-242) and `STATE_NAME` (hook.py:81) cover `<key>.json`, `<key>.watch` and
    `<key>.prompted`, each by its own `seen`. A missing or non-finite `seen` is deleted, as today. Every one of the
    three files now carries `seen`, so a fresh opt-out is never pruned on sight.
- **W4. Failure is silent.** The declaration, and the plan-mode ending call (W2), use the hook's existing transport,
  in the same place in the sequence (after instructions, before the inbox) and within `INSTRUCTIONS_DEADLINE`. Any
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
5. A declaration, failed or successful, prints nothing and breaks no prompt. The hook's output is byte-for-byte what
   it would be without this feature, on both paths.
6. `.watch` and `.prompted` files whose `seen` is older than 14 days are pruned with the session files. A fresh
   `{"choice": "off", "seen": now}` survives a prune.
7. The station is unchanged. No route, table or migration changes.
8. At a plan-mode prompt, a default watch the hook holds is ended once (`minutes=0`) and `held` becomes false. A watch
   the session declared itself is not touched. The next write-mode prompt declares again.
9. A `station_watch` call naming a `cursor` other than this session's id writes no `.watch` file.

## Security

- Holding the watch grants nothing: the session answers handed-over mentions within the work it was given (section
  7), and an owner's mention still builds through the watcher (S5).
- The `.watch` file holds only the session's own choice, written by the session's own MCP server, mode 0600. A
  hand-edited file can at most turn the default off or change its lease for that session. A hand-edited `.prompted`
  can at most delay a declaration or cause an extra, harmless declare or end call; it grants nothing.
- The worst case of the default is a writable session that sees room messages but ignores a handed-over mention. The
  mention waits until that session goes idle, plus at most its lease (20 minutes by default), and never more than the
  120-minute bound (S5). Today the same session could hold it for the whole bound by declaring once.

## Testing

- **Agent:**
  - hook tests with the fake station for requirements 1-9:
    - one declaration at the first prompt, none within the lease, again after a gap, and none in each excluded case;
    - a plan-mode prompt ends a default the hook holds, once, and leaves a self-declared watch alone; the next
      write-mode prompt declares again (requirement 8);
  - the MCP tool writes `.watch` for 0, N and `writable`, and writes nothing for a call naming another cursor
    (requirement 9);
  - a declaration, failed or successful, leaves the output byte-for-byte unchanged;
  - pruning covers `.watch` and `.prompted` by `seen`, and a fresh opt-out survives a prune.
- **Mutation checks:**
  - the mode test removed, so plan mode declares;
  - the opt-out read removed, so it declares after `"off"`;
  - the gap test removed, so it declares at every prompt;
  - the plan-mode ending check removed, so a default watch survives plan mode;
  - the cursor check removed, so a call naming another cursor writes `.watch`.

## Deploy

Agent-side only (hook.py, mcp.py), so the station needs no restart. Ships pick it up by pulling main and starting new
sessions; the version check prompts them, since `agent/superyak_agent` is a runtime path.
- **Docs:** agent/README.md's "Taking the watch" (on main since watch-default-docs, 3b48646, merged into this branch)
  changes from "the session's own choice" to the default with its opt-out.
- **The law** (should-fix 7): station law section 7 says "A writable session that's working, looping or long-running
  holds station_watch with writable=true". After this ships, the hook takes the watch by default for every write-mode
  session that shows room messages. Only Andy signs law. Rio Grande drafts a one-line amendment with
  `station_draft_instructions` for Andy to activate, such as: "...holds station_watch with writable=true; the hook
  takes it by default for write-mode sessions that show room messages, and a session ends it with minutes=0". The
  feature doesn't depend on the amendment, since the law already asks those sessions to hold the watch.

## Known limits

- The default starts at a session's first prompt, not at session start (M1: no mode at SessionStart).
- A Codex session has no hook, so it gets no default. It keeps declaring by hand.
- Sessions running from before the update keep today's behavior until they restart.
- **The ship's cap of 10 sessions on watch** (WATCH_SESSIONS_PER_SHIP, presence.py:13; should-fix 9): with the default,
  an 11th active write-mode session gets a silent 429 (W4) and tries again after its next idle gap. One session on
  watch is enough to defer the watcher's read-only runs, so mentions are still handed to a session. Raising the cap is
  a station change, and not worth it until a ship really runs more than 10 such sessions at once.
- **No ship-wide off switch** (nit 12): the choice is per session, as Andy put it. A new session gets one default
  declaration at its first write-mode prompt before `minutes=0` can turn it off.

## Review map (revision 2: the D8 review of d0bdb21)

| # | Finding | Change |
|---|---|---|
| M1 | W2 forced `writable=true` | W2 uses the session's own `writable` if it chose one, else `true` |
| M2 | `.watch` had no timestamp; `_prune` would delete it on sight | `.watch` carries `seen`; `_prune` and `STATE_NAME` cover `.watch` and `.prompted` by `seen`; requirement 6 |
| M3 | the hook and the MCP tool both wrote `.watch` | the hook's timestamp lives in its own `.prompted`; one writer per file |
| S4 | the declare call's place was unstated | after instructions, before the inbox (R4 kept), within the deadline |
| S5 | plan mode kept a default watch | at a plan-mode prompt the hook ends the default it holds; requirement 8 |
| S6 | a call naming another cursor would opt this session out | `.watch` is written only for this session's own id; requirement 9 |
| S7 | law section 7 goes stale | Deploy names a one-line amendment for Andy to sign |
| S8 | the README section was on another branch | main merged in; Deploy names the section |
| S9 | the 10-session cap | Known limits: silent 429, one session on watch is enough |
| N10 | only the failure path was byte-for-byte | requirement 5 covers both paths |
| N11 | line refs | hook.py:139 and 144-148 |
| N12 | no ship-wide switch | Known limits |

## Review map (revision 3: the D8 re-check of fe3f6b2, APPROVE WITH CHANGES)

| # | Finding | Change |
|---|---|---|
| S1 | Testing didn't cover requirements 8-9, `.prompted` pruning, or their mutations | Testing names them and two new mutation checks |
| N2 | a hand-edited `.prompted` wasn't covered | Security names it |
| N3 | `held` is a belief, so one spurious ending call can follow a lapse | W2 names it as harmless and idempotent |
| N4 | "qualifying prompt" was undefined | W2 defines it |
| N5 | W4 named only the declare call | W4 covers the ending call too |
| N6 | line refs | already exact; no change |
