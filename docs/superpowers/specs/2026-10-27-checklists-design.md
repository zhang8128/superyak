# Checklists: rules that fire at moments, renegotiated in the open

Revision 1, 2026-10-27. Serenity (the Mac). Asked for by Andy.

## Why

Andy, 2026-10-27, after a day the ships spent tunnelling into review loops:
- "make these a part of superyak, configurable checklists for conversations and tasks and for entering a location";
- "it feels like we built this cool memory and hive mind system but hard to get you to instinctively use it because
  your instincts are hardcoded. maybe checklists are a stopgap";
- "just start. the whole point of this is it is rules to be renegotiated";
- earlier: "a checklist that you occasionally hit to do things like reflect … you see them everywhere in the
  military", and "a checklist where you review against department and overarching goals".

An agent in Superyak can carry three kinds of guidance:

| Kind | Where it comes from | How it reaches the agent |
|---|---|---|
| **Instincts** | Emerge from engram's memory | Shown at session start; the model may or may not act on them |
| **Lessons** | Learned the hard way, chosen | Matched by similarity on the rail (first-rail spec) |
| **Checklists** | Agreed, then renegotiated | Fired at a known moment, run out loud |

A model's own instincts are fixed. Engram's instincts are suggestions it often passes over. A checklist works now
because it is explicit, it fires at a moment everyone can name, and its run is on the record. It is honest about being
a stopgap: every run records which items were already done before the checklist asked. An item that keeps being done
unasked has become habit and can retire into a lesson. An item that keeps catching mistakes stays.

## Goals, non-goals, anti-goals

**Goals**
- The people and ships who use checklists configure them.
- They fire at three kinds of moment: a conversation, a task, and entering a location.
- Every run is recorded, and the agent says which list it ran.
- Every change is proposed, versioned and reversible ("rules to be renegotiated").
- Step one seeds from docs/checklists.md, the lists the ships already run.

**Non-goals**
- **Law.** Checklists are working practice. The signed law outranks them, and a checklist never widens what a person
  or ship may do.
- **Enforcement.** A checklist asks; it does not block. The one exception is the single hold before a matched command
  (below), which is the rail's hold shape and passes on a re-run.
- **Checklists for people in the web app**, such as a teacher's or a nurse's. That is phase 2, with its own spec.

**Anti-goals**
- **Checklist spam.** At most 12 items a list and 2 lists a moment. A list nobody reads is worse than none.
- **Lists that only grow.** The run data proposes removals as readily as additions.
- **A backdoor for instructions.** Checklist text is quoted data. It can't authorize an act, and a stranger's
  repository can't plant one (see Trust).

## Phase 1: the agent's checklists (this spec builds)

### A checklist is a file

A checklist is a Markdown file in a `.superyak/checklists/` directory:

```
---
id: before-push
title: Before any push
when: command git push
version: 3
owner: ships of this repository
---
- [ ] The branch's base is on the rewritten history.
- [ ] Nothing in the diff describes an unfixed security hole, names a person or holds a key.
- [ ] The push is needed now.
```

- `id` is `[a-z0-9-]{1,40}`, unique within its directory.
- `when` holds one or more moments (below), separated by `;`.
- `version` is a whole number, raised by each accepted change.
- `owner` is free text naming who accepts changes: a person, "ships of this repository", or a room.
- There are 1 to 12 items, each a line starting `- [ ] ` with at most 200 bytes after it.
- Anything else in the file is a parse error. The agent says so once per session and skips that file.

**Where checklists are found, which is the "location" part:**
- `~/.superyak/checklists/`: the ship's own, always loaded.
- `.superyak/checklists/` in the session's working directory and in each of its parents up to the home directory, the
  nearest first. Superyak's shared set lives in the repository at `.superyak/checklists/`, so every session working in
  Superyak gets it.
- When two files have the same `id`, the nearest one wins, so a project can narrow a shared list.

### Moments

| `when` | Fires | Where it is checked |
|---|---|---|
| `start` | When a conversation begins | SessionStart hook |
| `every <N>h` (1 to 24) | At the first prompt N hours after this list last fired in this session | UserPromptSubmit hook |
| `enter` | When the session's working directory first enters the checklist's directory or a directory below it, at start or at any later prompt | SessionStart and UserPromptSubmit, against the last directory seen in this session |
| `command <words>` | Before a Bash command containing these words runs, once per session | PreToolUse hook on Bash (new) |
| `claim` | When the session takes a board item | The station MCP's `station_claim` result |
| `room <room id>` | At the first `station_read` of that room in a session | The station MCP's `station_read` result |

- **Each moment fires a list at most once a session.** `every` fires at most once a period.
- **At most 2 lists a moment.** The nearest win, and the rest are named in one line ("2 more: …").
- **`command` holds once.** It denies the first matching command with the checklist as its reason. The reason says
  plainly that it is a checklist and not a refusal. A re-run of the same command passes, and nothing rewrites the
  command. This matches the first-rail spec's hold, and the two share one per-session record so they never hold the
  same command twice.

### How a list is shown

The hook adds it as context, quoted as data with its source:

```
Checklist "Before any push" (before-push v3, from <path>, owner: ships of this repository). Run it out loud: say
which list you ran and answer each item as done, done before asked, n/a, or skipped and why.
- [ ] …
```

Items are shown exactly as written, within their limits. A hook that can't read its files in 150 ms adds nothing and
records why. It never stalls a prompt.

### Running it out loud

- The agent answers each item in its reply, and posts the answers in a room when the list says so (the reflect list
  does).
- The MCP tool `checklist_run(id, version, moment, answers)` appends a run to `~/.superyak/checklists/runs.jsonl`:
  the time, session id, id, version, moment, and for each item one of `done`, `done-before-asked`, `n/a` or
  `skipped`, with a reason for `skipped` of up to 200 bytes.
- The log holds only these fields. It never stores conversation text.
- A list that fired but wasn't recorded counts as `unrun` in the report. It is never guessed.

### Renegotiation

- **Anyone who runs a list can propose a change.** The `checklist_propose(id, change, reason)` tool drafts a post for
  the room the owner names (all hands for Superyak's shared set). It is marked "Proposal:" with a default and a
  deadline of at least one ten-minute tick (law draft section 8). The tool also points to the runs and the mistake
  that motivated the change.
- **Ships' working lists change by the ships' own process.** A change can be undone, so silence by the deadline is
  consent. Any person can veto at any time, and Andy's word ends any dispute.
- **Accepting a change is a commit.** It edits the file, raises `version` and names the proposal it accepts, so git
  history is the list's history and a revert undoes it.
- **A person's own lists in `~/.superyak/checklists/`** are theirs to change at will.
- **The report.** `superyak-agent checklists report` reads the runs log for each list and proposes, never applies:
  - **retire into a lesson:** items done before asked in every one of the last 10 runs;
  - **drop or narrow the moment:** items answered n/a in every one of the last 10 runs;
  - **look at why:** items skipped more than half the time, with their reasons;
  - **lists that fire but go unrun.**

  The reflect list reads this report.

### Trust

A cloned repository could ship a `.superyak/checklists/` that asks an agent to do harm, so checklists load only from
trusted places:
- `~/.superyak/checklists/`;
- directories the owner trusted with `superyak-agent checklists trust <path>`, recorded in
  `~/.superyak/checklists/trusted.json`.

Superyak's own repository is trusted when a ship docks.

From an untrusted directory, the hook shows one line ("this directory has 3 checklists; `superyak-agent checklists
trust <path>` to use them") and none of their text. Even a trusted list is quoted data: it can ask an agent to check
or do only what the law and its permissions already allow, and a `command` hold never runs anything.

### Seeding

docs/checklists.md becomes files in `.superyak/checklists/`, each with its moment:

| List | Moment |
|---|---|
| Why we build | `start; every 3h` (read, no items to answer except "re-read") |
| Each hour, before the queue | `every 1h` |
| Reflect, an after-action review | `every 3h` |
| Before any push | `command git push` |
| Merging to main | `command git merge` |
| Before starting a piece of work | `claim` |
| A session starting | `start` |
| The Mac's main checkout | `enter`, in that checkout's own `.superyak/checklists/` |
| Shell commands (zsh) | `command --include=*` |
| The rest | No moment yet. They stay in docs/checklists.md until someone proposes one. |

docs/checklists.md then points to the files, so the lists live in one place.

## Phase 2: rooms and places, for people (its own spec)

The station stores lists for a room or a place. The owner edits them in the web app, and members propose changes.
Runs become a table the owner can read. An organization's city of AI (a school, a hospital) starts with lists of its
own, for example:
- entering a clinic's room: a consent check and the place's never-to-a-cloud-model rule;
- a classroom: today's goals, and a reflection at the end.

The moments, the run answers and the report stay the same.

## Phase 3: from stopgap to instinct (its own spec)

Retired items become rail lessons, and later engram instincts. One honest test: drop a retired item from its list for
a week, and count whether the behaviour holds without the prompt.

## Tests

- **Parsing:** a valid file, every limit and every malformed field. A bad file is skipped with one notice.
- **Finding:** home and ancestors, nearest first, the same id overridden, untrusted directories shown as one line.
- **Moments:**
  - `start` fires once;
  - `every 3h` fires at the first prompt after three hours and not before;
  - `enter` fires when the directory changes and not again in the same session;
  - `command` holds once and passes on a re-run, sharing the rail hold's record;
  - `claim` and `room` appear in the tool results.
- **Budget:** a third list at one moment is named, not shown, and nothing is shown after 150 ms.
- **Runs:** the log holds exactly the fields above. The report's four proposals come from crafted logs, and it never
  writes to a checklist.
- **Safety:** a list's text never reaches a command, and an untrusted list's text never reaches the context.

## Measure (Andy's goal 3, and the stopgap question)

After a week of phase 1, report, for each list:
- runs and unruns;
- items done before asked;
- mistakes that an item caught, from the after-action reviews.

Also report the mistakes no list caught. If lists are run and catch things, phase 2 follows. If they are fired and
skipped, the moments or the lists are wrong, and that is the first renegotiation.

## Decisions

- D1: files, not station records, in phase 1. Ships use them today, git gives versions and reverts for free, and the
  location is the directory tree.
- D2: the three moment kinds are conversation (`start`, `every`), task (`claim`, `command`) and location (`enter`,
  `room`).
- D3: the only hold is the `command` hold, once, in the rail's shape. Everything else asks.
- D4: trust is explicit. A stranger's repository can't plant a checklist.
- D5: renegotiation follows the ships' decision process, with any person's veto. The report proposes and never
  applies.
- D6: runs record "done before asked", which is how a stopgap measures its own retirement.
