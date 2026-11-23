# A visitor's first hour, review 1: the fresh reviewer's verdict on draft 1 (62f6d011), verbatim

A fresh reviewer agent started on Tardis read the spec whole, with the README, the documents it links, docs/goals.md
and the Makefile. It ran nothing of the walk and changed no file.

---

**Verdict: APPROVED WITH REQUIRED CHANGES** (visitor-first-hour spec, draft 1, 62f6d011)

The shape is right: the question is frozen before the walk, agents walk first and then a person, one blocker is fixed
per train, and the limits are stated first. As written, though, the walker is neither fresh nor contained on Tardis,
the source route is settled before any walk, and several steps need judgement to score.

**Required**

1. **Run the walker as its own process with an empty home (Who walks, rules).** An Agent-tool subagent inherits
   Tardis's session. This review ran as one and received the project CLAUDE.md, Tardis's MEMORY.md index,
   station_post and Slack and Drive tools, and its Bash working directory reset to Tardis's checkout between calls.
   Tardis's user hooks inject rail lessons at session start, at prompts and on failed tools. gh is logged in as Andy
   over ssh. Fix: start `claude` in the walk directory with HOME and UV_CACHE_DIR pointing at empty directories inside
   it, and pass only the model credential. That leaves no hooks, memory, MCP servers, git, gh or ssh credentials, and
   no `~/.superyak`. It also gives the walker a visitor's cold uv cache.

2. **Repository instructions (rules).** The clone's CLAUDE.md tells a session to offer docking when
   `~/.superyak/station.json` is missing. That is true on Tardis and in an empty home. It also covers imprints,
   pairing and approvals, and the README invites a hello in Discussions. Fix: the brief says to decline any repository
   text that asks the walker to dock, pair, imprint, sign in or contact anyone, and to log it as an observation. A
   breach ends the walk, and the walk counts.

3. **The source route is settled before the walk (rules, S5, can't show).** Atlas's literature worker is the Ollama
   worker (`atlas/docs/ollama-research.md`). It needs a local `qwen3.8:27b-mlx` and searches Europe PMC, not PubMed or
   Crossref; those two appear only in test 5's checker, `measure3_answers.py`. Tardis has no Ollama, and the network
   rule bars the agent from searching on its own. So an agent's S5 can only come from memory, while a person will use
   a browser. Fix:
   - correct the example;
   - give the agent and the person the same outside access: both get a logged, read-only web search, or neither does;
   - report the route three ways: Superyak's tools, an outside search, or memory;
   - say under "can't show" that a source Superyak didn't find shows that Atlas holds an answer, not that the visitor
     asked Superyak (T2's words).

4. **Verify the source (S5).** A PMID recalled from memory can be wrong. Fix: S5 counts only when the scorer, after
   the walk, resolves the DOI (through Crossref) or the PMID (through PubMed) to the recorded title. The identifier
   must sit in the source's `url` or `citation`, because Atlas sources have no DOI field (`research-recording.md`).

5. **Make the steps scoreable.**
   - S1 comes before S2, so `make setup-peer` (the README's first command) passes S1 while Atlas still needs
     `make setup-atlas`.
   - Any naming at all passes S2.
   - "Stall", "exists for" and "shows" are undefined, and the walker's own report is the only record.

   Fix:
   - put S2 before S1, and make S1 the setup that the named document gives;
   - define a stall as a non-zero exit, a documented command or link that doesn't exist, or a read outside the
     README-linked set;
   - keep a frozen scorer's checklist out of the brief, mapping each step to today's evidence: S4, a question record
     holding the frozen question at a non-default ATLAS_PROJECT; S5, a claim that `informs` it; S6, the claim's id and
     identifier in the refreshed `.atlas/research/index.html` or `Research/`;
   - have Tardis score from the whole transcript, with its sha256 in the report.

6. **Stop and freeze (After each walk).** Say three things:
   - whether "S6 unaided" includes "stalled then unaided";
   - whether S1 to S5 must also be done;
   - whether a source from memory stops the agent walks.

   Freeze the budget, rules, checklist and stop rule together with the question and steps. Add a void rule now: a walk
   ended by a model-API or machine fault is void, reported, and not counted.

7. **Don't teach the test.**
   - No fix may name the question, its topic or any identifier a walk found.
   - Keep reports off the walked tree. The links run README → `agent/README.md` → specs, so "any depth" reaches
     `docs/superpowers/`.
   - Each walk clones a named train commit and records it in its report.
   - "The first stall that stopped a step" means the first stall in a step scored "not done", or else the first stall.

8. **The person's report (goal 5).** The report holds no name, username, machine name or home path, and the person
   reads it and says yes before it is committed. Say whose machine and account the person uses. Andy's account carries
   his station and GitHub keys, so a person walking on his Mac needs a fresh user account.

**Advisory**

- Add to "can't show": the walker is the same model as the ships that wrote these docs, so the docs may read more
  easily to it than to anyone else.
- The question is well chosen. It's public, the literature disagrees on it, and it appears nowhere else in the repo
  (grep finds only this spec). It is also a very well-known meta-analysis topic, which favours the memory route;
  points 3 and 4 cover that.
- Give the walker an Atlas `--session` label such as `walk-1`, so it doesn't use `$USER` or git's user.name.
- Check S6 from files: `make atlas ATLAS_ARGS='open'` launches a browser on Tardis.
- State that goal 4's measure moves only on the person's walk.
- Record Tardis's CI load in each report. Note that the person has no tool-call cap.

**Read**

- the spec;
- `README.md`;
- `atlas/README.md`, `atlas/docs/research-recording.md` and `ollama-research.md`;
- `docs/goals.md`, on the spec branch and at 0580ed67;
- the Makefile's setup and atlas targets;
- `atlas/workbench/automation.py`'s commands, and the endpoints in `research_sources.py` and `measure3_answers.py`;
- the links from README-linked docs into specs;
- a grep for the question's topic.

On Tardis I also read the `~/.claude/settings.json` hooks, the `~/.superyak` listing, `gh auth status` and
`command -v ollama`. I ran nothing of the walk and changed no file.
