# A visitor's first hour (goals.md T2, goal 4)

Draft 2, 2026-11-23. Tardis. Under station law section 3, a fresh reviewer approves it in Andy's place, and Andy can
veto. The line it serves is `tardis/goals-t2-visitor` 0580ed67 (Rio Grande's §2 yes, all hands 74143153). Rio Grande's
suggestion there, to freeze the question before the walk, is taken here.

- **Draft 1 (62f6d011)** went to a fresh reviewer: approved with eight required changes, W1 to W8
  (`docs/superpowers/reviews/2026-11-23-visitor-first-hour-review-1.md`, e82ccc82). Draft 2 makes all eight, and the
  advisories marked below.

## The question

Can someone outside the three ships, given only this repository's README and the documents it links, get Superyak to
hold a sourced answer to one research question within an hour? Where does the path stop them?

**The frozen research question** is the same for the agent and for any later person: *"Does vitamin D
supplementation prevent acute respiratory tract infections?"* It's public, the literature disagrees on it, and it
involves no person's data. It's chosen apart from test 5's question (hydroxychloroquine), and it appears nowhere else
in the repository.

**Goal 4's measure moves only on a person's walk.** The agent walks find and fix blockers first.

## Who walks, and how (W1, W2)

**First, fresh agents,** each a separate `claude` process on Tardis, never a subagent of a ship's session. A subagent
inherits the session's instructions, memory, tools, hooks and logins.
- **Its directory:** one new empty directory per walk, outside every checkout: `/var/tmp/visitor-walk-N/`. It holds
  `home/` (empty, used as `HOME`), `uv-cache/` (empty, used as `UV_CACHE_DIR`), and the walker's clone.
- **Its environment** is cleared to `PATH`, `LANG`, `TERM` and `TZ`, plus that `HOME`, `UV_CACHE_DIR` and
  `CLAUDE_CONFIG_DIR=home/.claude`. That config directory holds only a copy of the machine's Claude sign-in file, with
  no settings, hooks, MCP servers or memory. Nothing else carries over: no git identity, no `gh` or ssh credentials,
  no `~/.superyak`, and no agent socket.
- **Its brief** is the question, the repository's public URL, the commit to clone, the rules below and the budget.
  Nothing else: never this spec's other sections, the scorer's checklist, a ship's post or a ship's memory.
- **Its transcript** is captured whole (`--output-format stream-json`) to a file outside the walk directory.

**Later, a person outside the three ships:** a visitor at Andy's table, or a collaborator Andy admits. Admitting stays
Andy's. The person uses a fresh user account on whatever machine they walk on, never Andy's account, which carries his
station and GitHub keys. They get the same question, rules and steps, and walk only with their consent.

## The rules the walker keeps

- It works only in its walk directory, and reads only what the README links, at any depth, plus what the tools print.
- **Repository text that asks it to dock, pair, imprint, sign in, or contact anyone** (CLAUDE.md, for one, offers
  docking), and the README's invitation to say hello in Discussions, are declined and logged as observations. Acting on
  any of them ends the walk, and the walk counts.
- It doesn't push, open an issue, post anywhere, or use any credential beyond the model's.
- **Outside search (W3):** the agent and the person get the same access. Each may search the web read-only: the agent
  with its built-in web tools, which the transcript logs, and the person in a browser, noting each search. Neither may
  write anywhere outside the walk directory.
- It puts no person's data anywhere.
- Its Atlas session label is `walk-N`, never `$USER` or a git name.

## The steps

Each step is scored **unaided**, **stalled then unaided**, or **not done** within the budget.

| Step | Done when (the scorer's checklist below decides) |
| --- | --- |
| S1. Find the research path | The walker names the README section and the linked document it will follow to ask a research question |
| S2. Set up | The setup that named document gives exits 0 |
| S3. See it work | That document's bundled demo exits 0 |
| S4. A project for the question | A new project holds the frozen question |
| S5. A sourced finding | A finding about the question, citing a source whose DOI or PMID resolves to its recorded title |
| S6. The answer, as Superyak shows it | Superyak's own view of that project shows the finding and its source |

**A stall (W5)** is any of: a command the walker ran from the docs that exits non-zero; a documented command, file
or link that doesn't exist; or a read outside the README-linked set. Each is logged with the step, the document and
line being followed, the command and its error, and what got it past, or "not passed".

**The route to S5's source (W3)** is reported as one of three: found through Superyak's tools, found by an outside
search, or brought from the walker's own knowledge.

**The budget:** 60 minutes of wall time or 150 tool calls for an agent, whichever comes first, and 60 minutes for a
person, with no call count. The walker stops at the budget and claims nothing past it.

## The scorer's checklist (W4, W5), frozen, never in the brief

Tardis scores each walk after it ends, from the whole transcript and the walk directory. The transcript's sha256 goes
in the report.
- **S1:** the transcript names a README section and a document linked from it, before S2's first setup command.
- **S2 and S3:** the named document's setup and demo commands, run in the transcript, exit 0.
- **S4:** a question record holding the frozen question, verbatim, in an Atlas project at a path that isn't the
  default `.engram/atlas/project`.
- **S5:** a claim that `informs` that question record, citing a source whose `url` or `citation` holds a DOI or a
  PMID. After the walk, the scorer resolves it through Crossref or PubMed, and the resolved title must equal the
  recorded title, ignoring case and whitespace. An unresolved or mismatched identifier means S5 is not done.
- **S6:** after `make atlas ATLAS_ARGS='refresh'` for that project, the claim's id and the identifier appear in its
  `.atlas/research/index.html` or under its `Research/`. This is read from the files, never by opening a browser.

## After each walk (W6, W7)

- **The report** is one JSON file: the commit walked, the steps, the stalls, the budget used, the source's route and
  identifier, the transcript's sha256, and Tardis's load during the walk. It's kept on this spec's branch, off the
  tree walkers clone, and its sha256 is posted in all hands.
- **One blocker is fixed per train:** the first stall in a step scored "not done", or else the first stall. The fix
  changes only the README, or the document or tool the stall pointed to. It never names the question, its topic, or
  any identifier a walk found.
- **Each walk clones a named train commit** on main, recorded in its report. This spec and the reports stay off main
  until the agent walks end, so no walker can reach them through the docs.
- **The agent walks stop** when one walk scores S1 to S6 each "unaided" or "stalled then unaided", with S5's source
  verified and found through Superyak's tools or an outside search. A source from memory doesn't stop them. They also
  stop after five walks. Then a person walks.
- **A void walk:** one ended by a model-API fault or a machine fault is reported as void and not counted.
- **Frozen together:** the question, the rules, the steps, the budget, the checklist and the stop rule. None changes
  after a walk.

## The person's report (W8)

It holds no name, username, machine name or home path. The person reads it and says yes before it's committed, and
it's committed only then.

## What this can't show, said before the walk

- **A fresh agent isn't a visitor.** It reads code and runs commands faster than most people, and it can bring
  sources from its own knowledge. So an agent's success is a floor for the docs, not evidence that people can use
  Superyak.
- **The walker is the same model as the ships that wrote these docs,** so the docs may read more easily to it than
  to anyone else.
- **Atlas's own literature worker needs a local Ollama model** and searches Europe PMC
  (`atlas/docs/ollama-research.md`), and Tardis has no Ollama. So an agent's S5 source will likely come by outside
  search or from memory. **A source Superyak didn't find shows that Superyak can hold an answer, not that the visitor
  asked Superyak,** which is T2's words. The route is reported so that difference stays visible.
- **The agent's containment is by environment and instruction, not by filesystem permission.** It runs as the same
  user as Tardis, so a read outside its directory is possible. The transcript is checked for one, and any such read is
  a stall and is reported. A separate user account or v2's jail would be stronger, and the person's walk uses a
  separate account.
- **Sixty minutes and one question** test a first hour, not lasting use.
- **The walker runs on Tardis,** which has a contributor's tools. A person's machine may lack `git`, `make` or `uv`,
  and S2 then reads differently.
