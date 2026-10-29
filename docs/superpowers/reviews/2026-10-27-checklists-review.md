# Review: Checklists, rules that fire at moments (revision 1)

**Verdict: REQUEST CHANGES.** The design is right and worth building: explicit lists fired at named moments, run out
loud and measured on whether they retire. But as written, a builder could not build phase 1 correctly. It leaves
undefined the output budget it shares with the law, which process carries the lists, how `command` words match, how
trust is scoped, and what the runs log needs in order to count `unrun`. It also claims a shared record with an unbuilt
hook that the two hooks can't share as described. Every must-fix below is a change to the spec's text, and each gives the
exact change. A re-check only needs to confirm the must-fixes.

Reviewer: a fresh agent under station law section 3, with no part in writing the spec. Read-only. Reviewed
`docs/superpowers/specs/2026-10-27-checklists-design.md` at da8f750 (on ba4f677). I read `agent/superyak_agent/hook.py`,
`install.py`, `mcp.py`, `__main__.py`, `claims.py` and `station.py` in this worktree; `docs/checklists.md` at 127d285;
the first-rail spec at 3f8063e1, section 8; `docs/station-law.md`; `.gitignore`; and the Claude Code hooks and
permissions references (code.claude.com/docs/en/hooks, /permissions), fetched 2026-10-27.

## Must fix

**M1. Checklists can push the law out of the hook's output.**
Evidence: Claude Code caps a hook's plain stdout and `additionalContext` at 10,000 characters. Output over the cap is
saved to a file and replaced by the file's path and a preview of at most 2,000 characters (hooks reference, "capped at
10,000 characters"). The station hook keeps the law, the version line and the board lines within `TOTAL_CHARS = 9500`
(`hook.py:91`), and adds each later part only if it fits whole (`hook.py:253-257`). The spec adds up to 2 lists a
moment, each up to 12 × 206 bytes plus a header, but never says where they sit in that budget. Two full lists come to
about 5 KB. Added after a long law, they would put the whole output over the cap, and the session would see 2,000
characters of its law.
Change: add to "How a list is shown": "Lists go after the law and the version line, and before the board lines, within
the hook's `TOTAL_CHARS`. A list is shown whole or not at all. One that doesn't fit is named in the 'N more' line and
isn't marked fired (M9). The law is never shortened for a list." If the builder would rather use a separate hook entry
with its own 10,000-character cap, say so instead, and keep the rule that a list is shown whole or not at all.

**M2. The spec doesn't say which process shows the lists, so a station that's down or a ship that stands down would hide
them.**
Evidence: `hook.run` returns nothing:
- in watcher and teamd runs (`hook.py:163-164`);
- when this ship stands down for another ship's claim (`hook.py:168-172`);
- for 60 s after the station couldn't be reached (`hook.py:176-178`);
- when the instructions call raises `OSError` (`hook.py:219-221`).

If the lists go inside `run()`, a station outage hides lists that are local files. With a machine ship and a project
ship both docked, two hooks run in the session (D7). Unless the spec says which one shows lists, both show them, or
neither does. "`~/.superyak/checklists/`: the ship's own" is the machine ship's home. A project ship's home is
`~/.superyak/ships/<name>` (`claims.py:39-47`).
Change: add a "Where it runs" paragraph:
- "Lists are local. The hook reads them before any station call. It shows them whether the station answers or is in its
  quiet minute, and their 150 ms is apart from the station's deadline."
- "Only the hook of the ship that acts in this session (`claims.verdict == 'act'`) shows lists, so a session never
  sees them twice."
- "A ship's own lists are in `<ship home>/checklists/`: `~/.superyak/checklists/` for the machine ship and
  `~/.superyak/ships/<name>/checklists/` for a project ship."
- "No list fires in a watcher or teamd run (`SUPERYAK_RUN`)." Then state the decision for an owner's builder run, which
  can push (law section 1). Either holds apply there too, or they don't, with the reason.

**M3. Installing the `PreToolUse` hook: undock would leave it in place, it would fire on every tool, and an older
checkout would eat room messages.**
Evidence:
- `HOOK_EVENTS = ('SessionStart', 'UserPromptSubmit', 'SessionEnd')` (`install.py:84`) is what `remove_hooks`
  walks (`install.py:172`), so undock wouldn't remove a `PreToolUse` entry.
- `install_hooks` writes entries with no `matcher` (`install.py:150`). A `PreToolUse` entry without `"matcher":
  "Bash"` runs on every tool call (Read, Edit, the station tools).
- `is_station_hook` recognises only `run_agent.py hook` (`install.py:68-79`), so a new subcommand would be installed
  twice and never removed.
- `_hook` maps any `SUPERYAK_HOOK_EVENT` it doesn't know to `'prompt'` (`__main__.py:80`). An agent checkout older
  than the settings (the Mac's main checkout is reset by hand; the hook runs from it) would therefore run the prompt
  path at every Bash call. That path fetches the instructions, declares the watch, reads the inbox and advances its
  cursor (`hook.py:229-243`, `543`). `PreToolUse` stdout isn't given to the model, so those messages would be marked
  read and never shown.
- A hook that returns `"allow"` skips the person's permission prompt (hooks reference, `PreToolUse` decision control).

Change: add an "Install" paragraph:
- "`make dock` adds a `PreToolUse` entry with `"matcher": "Bash"` and the same `|| true` guard. `PreToolUse` joins
  `HOOK_EVENTS`, so undock removes it, and `is_station_hook` recognises its command."
- "The hook takes its event from stdin's `hook_event_name`. It acts only on the events it knows. Any other event, and
  `PreToolUse` in an agent that predates this spec, makes no station call and prints nothing." One way: give the hold a
  subcommand that an older argparse rejects, which exits 2, and the guard turns that into 0.
- "The hold's only output is `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
  "permissionDecisionReason": …}}`, or nothing. It never returns `allow`, `ask` or `updatedInput`."

**M4. The record shared with the rail's hold can't be built as described.**
Evidence: the rail's spec says "Nothing here is built" (3f8063e1, line 7). Its hook is "a hook of its own, apart from the
room hook, with its own switch" (line 290). It keeps its record in its own state. That record is keyed by the command's
head (the first word, plus the second when that doesn't start with `-`) as (session, head digest, lesson), with at most
3 holds a session (lines 307, 314). The checklist hold is keyed by list and words. Claude Code runs matching hooks in
parallel (hooks reference: "its matching hooks run in parallel") and applies `deny` over everything else. The reference
doesn't say how two deny reasons are combined. If only one is shown, the other hook still records its hold as done: the
re-run passes, and that list or lesson never reached the model.
Change: replace the last sentence of "`command` holds once" with this: "Phase 1 keeps its own per-session record (M9).
When the rail's hook is built, the two holds become one hook process, whose single deny carries the checklist first and
then the lesson. Until then, the builder confirms on each ship's Claude Code version what the model sees when two
`PreToolUse` hooks deny one call. A list held at a deny whose reason didn't reach the model is recorded as `unshown`,
not fired." Also adopt the rail's bounds here: at most 3 holds a session across all lists, and the rail's wording,
"Held once: checklist <id> v<version> applies. … Re-run the same command if you still want it."

**M5. `command <words>` matching is undefined, and with a once-a-session hold a misfire skips the real moment silently.**
Evidence: "a Bash command containing these words" could mean a substring, tokens or a glob. The seeded lists show
why the choice matters:
- As a substring, `git merge` matches `git merge-base --is-ancestor 60dd851 HEAD`, the first item of "Before any push"
  (checklists.md:57). It also matches `git commit -m "… git merge …"`.
- "Merging to main" requires "Main is merged into the branch (never a rebase)" (checklists.md:70). So in a session the
  first `git merge` is usually main into a feature branch. That merge is held, the list is spent for the session, and
  the real merge to main later passes with no list.
- For `--include=*`, a raw substring matches only the unquoted, wrong form (`--include=*.py`), not
  `--include='*.py'`. That is useful. Token matching after `shlex` matches both, so it holds correct commands too.

Change: replace the `command` row and its bullet with these two rules.
- "The words are a literal piece of the raw command string, as in the rail's spec (never expanded, never a glob or a
  regular expression), case-sensitive, at least 6 bytes. A match must begin at the start of the command, after
  whitespace, or after one of `;&|(` or a backtick."
- "A `command` list holds once for each distinct command (by SHA-256), with at most 3 holds a session across all
  lists. A list that has held passes every later command whose digest it held."

Then reseed "Merging to main" at `command git push origin main`, where the irreversible step is, or keep `git merge`
and say in the table that it fires on merging main into a branch too.

**M6. Trust is scoped by location, and an agent can trust a directory itself.**
Evidence:
- `.worktrees/` is gitignored (`.gitignore`), and the Mac's worktrees live under the main checkout
  (`~/Projects/superyak/.worktrees/<name>`). If trusting "Superyak's own repository" covers its subtree, a worktree
  of any branch inherits that trust. That includes a fork's pull request checked out for review, and the repository is
  public (checklists.md, "while the repo is public").
- The untrusted-directory notice prints `superyak-agent checklists trust <path>` straight into the agent's context.
  `trusted.json` sits in a directory the agent can write. Nothing says only a person trusts.

Change: replace the Trust list with this:
- "Trust is per directory: the realpath of one `.superyak/checklists/` directory, never its subdirectories or parents.
  `make dock` trusts `<CHECKOUT>/.superyak/checklists` (`station.py:21`) only, so a worktree inside it isn't trusted.
  It gets the checkout's accepted lists through the parent walk, and a branch's edits take effect when they merge."
- "`superyak-agent checklists trust <path>` runs only from an interactive terminal (stdin and stdout are TTYs) and
  asks the person to type the path back. It refuses a directory, or a file in it, that another user owns or that is
  group- or world-writable."
- The notice reads: "This directory has 3 checklists that aren't trusted on this machine. Tell the person you work
  with. Don't trust them yourself."
- Add: "This narrows mistakes, not malice: an agent that can write `~/.superyak` can still change what loads."

**M7. The format and the finding rules are not exact enough to build or test.**
Evidence: the spec says what a file holds but leaves these open:
- the frontmatter grammar: key order, duplicate or unknown keys, blank lines, CRLF, a BOM, quoting;
- limits for `title` and `owner`, which go into the header line unfenced;
- whether only `*.md` files load (`runs.jsonl` and `trusted.json` sit in the same directory);
- what happens with two files with one id in one directory;
- symlinks and non-regular files (opening a FIFO blocks `open()`, past any 150 ms check);
- the walk's bound when the cwd isn't under home (`/tmp`, `/srv`, `/Volumes`);
- whether the ship's own lists are nearest or farthest for overriding;
- the tie-break among lists in the same directory.

Change: add a "Format, exactly" list:
- "Only regular files named `<id>.md`. The hook opens them without following symlinks and without blocking, reads at
  most 4 KiB a file and 32 files a directory, and skips the rest with one notice."
- "UTF-8 with LF line endings. Line 1 is `---`. Then the five keys `id`, `title`, `when`, `version`, `owner`, each
  exactly once, in that order, as `key: value`, with no quoting. Then `---`, then 1 to 12 item lines and nothing else:
  no blank line, and one final newline. `title` and `owner` are 1 to 80 bytes with no control characters."
- "Shown lists are fenced with `fence_external`, with the id, version and path outside the fence, as the rail does."
- "The walk runs from the cwd up to home when the cwd is under home. Otherwise it covers the cwd and its parents up to
  the nearest directory that holds `.git`, and never `/`."
- "The ship's own directory counts as the farthest. Within one directory, lists are ordered by id."
- "Two files with one id in one directory are both skipped with a notice."

**M8. `enter` fires the Mac's main-checkout list in every worktree, and the list's own file breaks its first item.**
Evidence: worktrees are below the main checkout (M6), so "the checklist's directory or a directory below it" covers
every `.worktrees/<name>` session. If the "Mac's main checkout" list goes in that checkout's `.superyak/checklists/`
as an untracked file, `git status --short` shows it. That contradicts the list's first item, "`git status --short` in
`~/Projects/superyak` is empty" (checklists.md:116). If it's tracked, it fires in every clone, on the Pi and on Tardis.
The spec also doesn't say whether "the checklist's directory" is the directory that holds `.superyak/` or
`.superyak/checklists/` itself.
Change:
- "A list's location is the directory that holds its `.superyak/`. `enter` fires when the cwd is that directory or
  below it, but not past a directory in between that holds `.git` (another working tree)."
- "A list in the ship's own directory may name its location as `enter <absolute path>`."
- Seed the Mac's list in the Mac's `~/.superyak/checklists/` as `enter /Users/kairos/Projects/superyak`, not in the
  repository.

**M9. The firing rules leave the record, `every`'s first firing, deferral and session sources undefined. One seeded list
can starve another.**
Evidence: the spec never names the per-session record that "once a session", `every` and `enter`'s "last directory
seen" depend on. It doesn't say whether a list with only `every 1h` fires at the first prompt or after an hour. It
doesn't define "a moment" for the 2-list cap: an event, or a moment kind? At hour 3 the seed puts "Each hour", "Reflect"
and "Why we build" (two with `every 3h`) at one prompt. The third is only named, and if it counts as fired, the same one
loses every 3 hours. `SessionStart` arrives with `source` `startup`, `resume`, `clear`, `compact` or `fork` (hooks
reference), and the spec doesn't say which of these is "a conversation begins".
Change: add "Firing, exactly":
- "The record is `<ship home>/sessions/<session_key>.checklists`, holding fired list keys with times, held command
  digests and the last cwd. `_prune`'s `STATE_NAME` gains the suffix (`hook.py:96`)."
- "A cap of 2 applies per hook event, across every moment kind."
- "A list named but not shown isn't fired. It's due again at the next event, and due lists show in the order of the
  longest wait first, then nearest."
- "`every <N>h` first fires N hours after the session's first event."
- "`start` fires on `startup`, `clear` and `fork`, not on `resume` or `compact`."

**M10. "Why we build" can't be written in the format, and "post the answers in a room" has no field.**
Evidence: "Why we build" has no `- [ ]` item (checklists.md:6-13). The format needs 1 to 12 items, and "anything else
in the file is a parse error" (spec lines 73-74). The seeding table says "no items to answer except 're-read'", but the
text to re-read can't be in the file. "Posts the answers in a room when the list says so (the reflect list does)" names
no way for a list to say so.
Change: add two optional keys after `owner`:
- `read: yes`: the body is up to 1,500 bytes of plain lines, shown as written, with no items. Its run has no answers.
- `post: <room id>`: the agent posts its answers there.

Or turn "Why we build" into items, and drop the "except 're-read'" wording.

**M11. The runs log can't do what the spec says: "never conversation text", `unrun`, and the measure.**
Evidence:
- A `skipped` reason is up to 200 bytes of the agent's free text. The report shows reasons, and the reflect list posts
  in a room. So "It never stores conversation text" can't be enforced.
- "A list that fired but wasn't recorded counts as `unrun`" needs a record of firings. The log has only runs, and "adds
  nothing and records why" names no place.
- The measure counts "mistakes that an item caught", and "an item that keeps catching mistakes stays", but no answer
  value records a catch.
- Runs are keyed by `id`, and a nearer list overrides a farther one with the same id. So the report would mix two
  different lists, and their items by position across versions.

Change:
- "The hook and the MCP server append each firing (time, session key, list key, version, moment) to `fired.jsonl`, and
  each budget miss, beside `runs.jsonl`. Both files are 0600."
- "A list key is the first 8 hex digits of the SHA-256 of its directory's realpath, then `/` and its id. The report
  compares items only within one list key and version."
- Add the answer `caught`: done, and it caught a mistake.
- Replace "It never stores conversation text" with: "A reason is the agent's own words: one line of at most 200 bytes.
  The tool refuses a reason holding an email address, a phone number or a key-like token. The log never leaves the
  machine except in a report the agent chooses to post."

**M12. Renegotiation conflicts with the law, and "silence is consent" covers changes that guard irreversible acts.**
Evidence: law section 7 says "Only Rio Grande and Serenity merge to main … No ship pushes straight to main", and section
2 sets the merge conditions (`docs/station-law.md`). The spec says "Accepting a change is a commit", and a builder could
read that as committing to main. "A change can be undone, so silence … is consent" is true of the file, not of what
it guards. A change that drops "Nothing in the diff describes a security hole" (checklists.md, push list) passes on 10
minutes of silence. The push it then lets through can't be undone. `checklist_propose` "drafts a post for the room the
owner names", but `owner` is free text such as "ships of this repository", which names no room. "Law draft section 8"
isn't in the law (`docs/station-law.md` ends at section 7).
Change:
- "Accepting a change to a list in the repository is a branch merged to main under law section 2. A change to a ship's
  own lists is that ship's person's to make."
- "Silence is consent only for adding an item or a moment. Removing or weakening an item in a list whose moment comes
  before an irreversible act (a push, a merge to main, anything public, a live station act, an imprint) needs an
  explicit yes from a person, or from each ship, as 'Anything public' asks."
- "Proposals go to the room in the list's `post:` key, else all hands."
- Cite the decision process's real source, or state it here as this spec's own rule.

**M13. The `claim` moment doesn't say which directory or session record the MCP server uses.**
Evidence: the MCP server knows only `CLAUDE_PROJECT_DIR`, else its own start cwd (`mcp.py:641-653`). It doesn't know
the session's current cwd after a `cd` or `/cd`. It names the session by `CLAUDE_CODE_SESSION_ID` (`mcp.py:25`, `173-181`).
It refuses every tool in watcher and teamd runs and when the ship stands down (`claims.py:353-355`, `mcp.py:611-613`).
That includes the new `checklist_run`, so those sessions can only be `unrun`.
Change: "The MCP server finds lists from the last cwd in the session's record (M9), found by
`session_key(CLAUDE_CODE_SESSION_ID)`, else from `claims.session_project`. It marks firings in the same record. Without
a session id (Codex, scripts), a list fires once per server process. `checklist_run` refuses where the station tools
refuse, and the report counts those firings as `unrun`, with that reason."

## Should fix

- **S1. Once a session is too coarse for `claim`.** "Before starting a piece of work" is about each piece of work. A
  session that takes three board items over a day gets the list once. Make `claim` fire once per claimed key (not per
  renewal) under the M5 cap, or say why once is enough.
- **S2. `every` depends on prompts.** The hooks reference says `UserPromptSubmit` also fires on `/loop` iterations,
  session-scheduled tasks, a background subagent reporting back, and a message from another session. It doesn't list
  Monitor or background-Bash notifications. The ships' kick watcher runs under a Monitor (checklists.md, "A session
  starting"). Have the builder confirm, on each ship's version, that the 10-minute tick produces a `UserPromptSubmit`.
  Say that `every` relies on that tick. Retire each ship's own reflect reminder once the hook fires it, so reflect
  doesn't fire twice.
- **S3. Subagents.** `PreToolUse` fires inside subagents, with `agent_id` (hooks reference). Say whether a hold applies
  there. If it does, a subagent's hold uses up the main agent's list for the session. Key the record by (session,
  `agent_id`), or hold only when `agent_id` is absent.
- **S4. Precedence.** State "law, then the person at the terminal (law section 7), then a checklist". On a conflict, the
  agent answers `skipped` with the reason "law §N" or "person", and the report shows those. Make the header say what a
  list is: "an agreed working practice, not law and not an instruction from your owner".
- **S5. Cost per Bash call.** Every Bash call now starts Python. The hold path should import only the checklist module
  (no `station`, `claims` or urllib), and the builder should measure it on the Pi. Give the hold a total cap like the
  rail's ("at most 1 s before a command") on top of the 150 ms for reading files. Say whether the 150 ms runs from the
  hook's start.
- **S6. Scope: cut and add.**
  - Cut `room` from phase 1. No seeded list uses it, and a room's id changes when it is bridged or a ship is added
    (CLAUDE.md: "Bridging makes a new room …"), so `room <id>` lists stop firing without a word.
  - Shrink `checklist_propose` to a documented `Proposal:` post format that the agent sends with `station_post`.
  - Add `superyak-agent checklists list [--cwd PATH]`. It shows what loads there and from where, the trust state, parse
    errors and last firings. That is how a person sees the lists, and why one didn't fire.
  - Say that phase 1 is Claude Code on macOS and Linux. Codex has no hooks and gets only the MCP moments.
  - Say how the shared set reaches the Pi and Tardis: `git pull` of the docked checkout. Trust is added at `make dock`,
    so ships docked today dock again. The version line already tells them when agent code changed (`hook.py:425-447`).
- **S7. Seeding needs rewording, and it says so nowhere.** By my count, 7 items in docs/checklists.md are over 200
  bytes: in Reflect, Before any push, Merging to main, the Mac's main checkout, Running CI, Approving a branch and
  Shell commands. 28 items wrap onto several lines. The spec's own example drops the `git merge-base` command and its
  hash from the push list's first item. Say that the seed shortens these items, under review. Keep the long form and the
  "why" in docs/checklists.md, and add an optional `see:` key linking each list to its section. Move "Shell commands
  (zsh)" to the Mac's own lists, because the Pi's shell may not be zsh. Consider seeding the lists that guard
  irreversible acts:
  - "A live station act": `command make station-approve`, `make station-bridge`;
  - "Copying a person's store": `command make imprint`.
- **S8. Moments the format can't express.** Reflect's "after a merge or a mistake, and at a session's end" can't be a
  moment. `SessionEnd` output never reaches the model. Say so in the seeding table.
- **S9. A ship's own lists aren't in git.** "Git history is the list's history and a revert undoes it" holds only in a
  repository. Say that the ship's own lists keep no history, or are a git repository of their own.

## Nits

- N1. Commands outside Bash don't trigger `command`: `gh pr merge`, a GitHub MCP tool, or a Monitor-run command. Say
  so.
- N2. Phase 2's "never-to-a-cloud-model rule" is a permission, not a checklist item. The non-goal "Enforcement" says
  so. A list can only remind.
- N3. Make the `id` rule `fullmatch` and require file name = `<id>.md` (M7). That also makes "unique within its
  directory" automatic.
- N4. `runs.jsonl` grows forever. Rotate it, or let the report read only the last 90 days. Append each line in one
  `write` under `O_APPEND`.
- N5. Docking a project ship should not trust its project's lists automatically. Only Superyak's checkout is trusted at
  dock.
- N6. Add tests:
  - the law is never shortened by lists (M1);
  - lists show while the station is unreachable (M2);
  - undock removes the `PreToolUse` entry, and an unknown event does nothing (M3);
  - the hold never emits `allow` (M3);
  - trust refuses a non-TTY call, a symlink, a FIFO and a world-writable directory (M6, M7);
  - `enter` doesn't fire across `.worktrees/<name>` (M8);
  - a deferred list isn't starved (M9);
  - `fired.jsonl` against `runs.jsonl` gives `unrun` (M11).

## Checked and fine

- **Session-start and prompt context.** `SessionStart` and `UserPromptSubmit` add plain stdout or `additionalContext`
  to the model's context (hooks reference). The station hook already relies on plain stdout (`__main__.py:81-84`).
- **The hold.** A `PreToolUse` `permissionDecision: "deny"` blocks the call, and its `permissionDecisionReason` is
  shown to Claude. The hook runs again on the re-run and lets it through by printing nothing. When decisions conflict,
  `deny` wins, and a deny applies even where an allow rule would let the call through (permissions reference).
- **Input fields.** `session_id` and `cwd` are in the input of `SessionStart`, `UserPromptSubmit` and `PreToolUse`, and
  `tool_input.command` is in a Bash call's. `permission_mode` isn't on every event, and `hook_fields` already treats it
  as optional (`hook.py:66-78`).
- **Leaks.** Matching words against a command leaks nothing, as long as the record keeps only digests (as the rail's
  does) and the deny reason carries only the checklist. "Nothing rewrites the command" (no `updatedInput`) is right.
- **Bounded holds.** A hold can't block work for more than one turn per list, since the re-run passes. With M5's cap it
  can't take more than 3 turns a session.
- **Within the law.** A checklist never widens what a person or ship may do (non-goals). An untrusted list's text never
  reaches the context.
- **The decisions.** D1 (files in phase 1, with versions and reverts from git) and D6 ("done before asked" as the
  retirement signal) are sound. The report proposes and never applies.
- **Renegotiation.** Silence as consent for reversible changes, any person's veto and Andy's final word match the ships'
  process, with M12's carve-out for changes that guard irreversible acts.
- **Sizes.** No list in docs/checklists.md has more than 8 items, so the 12-item limit takes none of them.

## Re-check of revision 2 (a02ecc01)

**Verdict: APPROVE WITH CHANGES.** All 13 must-fixes are applied, and none wrongly. Four new problems need a change to
the text before building (R1 to R4 below). Three of them come from my own earlier wording: M4's `unshown`, M5's cap,
and M7's walk. Apply R1 to R4 as written; they need no further re-check. Read against
`git diff da8f750 a02ecc01 -- docs/superpowers/specs/`. Line numbers are revision 2's.

### M1 to M13

| | Status | Where it landed |
|---|---|---|
| M1 | Applied | How a list is shown, "The budget" (196-199); D7 |
| M2 | Applied | Where it runs (205-215); D8 |
| M3 | Applied | Install (217-226); The hold (230-232); D9 |
| M4 | Applied, but my `unshown` can't be built (R1) | The hold (236-239); D16 |
| M5 | Applied; my cap leaves a gap (R2) | Moments, "`command`, exactly" (151-156); seeding; D10 |
| M6 | Applied | Trust (298-316); D4, D15 |
| M7 | Applied; my walk wording leaves a gap (R3) | A checklist is a file, "Format, exactly" (100-114); Where checklists are found (116-129) |
| M8 | Applied | Where found (128-129); "`enter`, exactly" (147-149); seeding row |
| M9 | Applied, missing one field (S-c) | Firing, exactly (166-177) |
| M10 | Applied | Keys (97-99, 110-111); seeding; D11 |
| M11 | Applied; the new key-like rule refuses paths (R4) | Running it out loud (252-266) |
| M12 | Applied | Renegotiation (268-287); D12 |
| M13 | Applied | "`claim`, exactly" (158-164) |

### Must fix before building

**R1. `unshown` can't be observed, so drop it.** No hook learns whether its deny's reason reached the model. It's my
M4 wording, and the coordinator is right about it. In phase 1 the hold is Superyak's only `PreToolUse` hook that denies,
so the case only arises with a person's or a plugin's own hook. Change: delete "A list held at a deny whose reason
didn't reach the model is recorded as `unshown`, not fired" (238-239) and "and lists recorded `unshown`" (294). Keep the
builder's confirmation, and record the result in the plan as a known limit. A list that fired and wasn't run already
counts as `unrun`.

**R2. Past the 3-hold cap, a matched `command` list never shows.** The cap is my M5 suggestion. A list that isn't held is
"due again at … the next distinct command it matches" (173-174), and once the session has held 3 commands, nothing
holds again. So in a long session, three ordinary pushes leave Merging to main silent at `git push origin main`, the one
moment it exists for. Change, in "The hold":
- "Past the cap, a matched list is added as `additionalContext`, with no `permissionDecision`, and recorded as fired.
  It reaches the model with the command's result."
- Widen the output contract at 230-232 to allow that. It is still never `allow`, `ask` or `updatedInput`.

Consider also making the cap per list (at most 3 holds per list a session), so one noisy list can't spend the holds of
another.

**R3. The walk reaches a ship's own directory.** "From the cwd up to home" (120-121) includes `~/.superyak/checklists/`.
- For the machine ship that is its own directory, so it is found twice, both nearest at home level and "the farthest"
  (127).
- For a project ship it is neither its own directory nor in its `trusted.json`. So every project-ship session in a
  folder under home shows "This directory has N checklists that aren't trusted…".

Change: "The walk runs from the cwd up to, but not including, home. A ship's own directory is never part of the walk."

**R4. The key-like rule refuses ordinary file paths.** The class `[A-Za-z0-9+/=_-]` includes `/`. So
`docs/superpowers/specs/2026-10-27-checklists-design` (49 characters, all in the class) is refused as a key. The
refusal "never says which", so the agent can't tell why (255-258). Change: "a run of 32 or more characters from that
class that holds an uppercase letter, a lowercase letter and a digit, and isn't a 40- or 64-digit hex hash." Add "a
file path passes" to the Runs tests (401). The refusal may name the kind (person data or key-like) without repeating
the text.

### The editor's decisions D7 to D17

- **D7: sound.** One process keeps the law first. The record is shared with the hold process and the MCP server under
  `flock` (170).
- **D8: sound, and the evidence holds.**
  - `runs.py:71` builds the builder run's settings from `workers.claude_sandbox_settings(mode='build')`, whose deny
    list has `Bash(git push*)`, `git commit`, `git reset` and `git rebase` (`workers.py:309-310`).
  - `runs.py:129` passes `--setting-sources project,local`.
  - `runs.py:152` sets `SUPERYAK_RUN='1'`, which silences a claimed project's own hooks too.

  So my M2 premise, that an owner's builder run can push, was wrong.
- **D9: sound.** An older `main()` sends anything but `hook` to `parser.parse_args`, which exits 2, and `|| true` turns
  that into 0. Without the guard, an exit 2 from a `PreToolUse` hook would block every Bash call. The spec keeps the
  guard (219).
- **D10: sound.** The cost is in R2 and S-b.
- **D11, D12, D13 and D17: sound.** D12 is stricter than the ships' process, which a spec may be.
- **D14: sound.** Commands that subagents run go unchecked, and the spec says so as a known gap (432).
- **D15: safe.** No untrusted text reaches the context either way. Comparing byte for byte means reading the untrusted
  file, which the safe-open rules at 101-104 already cover. S-d is about the wording of the notice.
- **D16: sound as a direction.** With R2, one shared cap of 3 for lists and lessons would still need the
  `additionalContext` fallback.

### The editor's items that aren't fully resolved

- **`unshown`:** agreed; see R1.
- **The process isn't on main:** acceptable as written. I checked `review/trail-arrows-spec`, where
  `docs/governance/ship-decisions.md` records message 53c12bac. It says that for reversible acts silence by the deadline
  is consent, and that otherwise each ship says yes explicitly, and a dead session's silence is not consent. The spec's
  own rules match that or are stricter, so they don't depend on it landing. One sentence would say so: "These rules
  stand on their own until the log or the law's section 8 lands."
- **Reflect's `post:`:** write `1bfd1b03e9f94519b1bb3c86c0fafaa1` in the seeding row (334). `plain_id` accepts it.
  Like `room` (D2), a `post:` id goes stale if all hands is rebuilt. Line 250 makes that loud, and fixing the id is an
  ordinary change.
- **`command` false positives** (`git push origin main-fix`, words inside a quoted commit message): acceptable once R2
  lands. A hold now goes to each distinct command, so a false positive costs one turn and an `n/a`, not the real moment.
  See S-b.

### Should fix

- **S-a. The light hold path needs a restructure the spec doesn't name.** `run_agent.py:15` imports
  `superyak_agent.__main__`, which imports `station` at `__main__.py:5`, and `claims` imports `station`
  (`claims.py:13`). So the hold must be dispatched in `run_agent.py` before that import. A second copy of
  `claims.verdict` "without them" (241) can drift from the first, and then two ships hold or none does. Move verdict's
  part that needs no station into a module both import, and add a test that the hook and the hold agree.
- **S-b. Make the match skip quoted text.** A match must begin outside single and double quotes. That cheaply removes
  the commit-message case. Add heredocs and `main-fix` to Deferred as known limits.
- **S-c. The record needs the session's first-event time.** `every` counts from it (141, 176), but the record's fields
  (168-170) don't include it.
- **S-d. D15's notice in a ship's own worktree.** A branch that edits a list shows "Tell the person you work with" in
  every session of ordinary edit work. Under a trusted checkout, say instead: "This branch changes N lists. They take
  effect when merged."

### Nits

- `claim` fires only when `station_claim`'s result says `board == 'open'` (`mcp.py:383`). Say so.
- If `/clear` keeps the session id, `start` "once a session" (177) blocks the firing on `clear` (175). The builder
  should confirm. Also, `CLAUDE_CODE_SESSION_ID` is fixed when the MCP server starts.
- Outside home with no parent holding `.git`, the walk is the cwd only. Say so (121-122).
- A moment repeated in `when` (`start; start`) should be a parse error.
