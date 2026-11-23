# A visitor's first hour (goals.md T2, goal 4)

Draft 1, 2026-11-23. Tardis. Under station law section 3, a fresh reviewer approves it in Andy's place, and Andy can
veto. The line it serves is `tardis/goals-t2-visitor` 0580ed67 (Rio Grande's §2 yes, all hands 74143153). Rio Grande's
suggestion there, to freeze the question before the walk, is taken here.

## The question

Can someone outside the three ships, given only this repository's README and the documents it links, get Superyak to
hold a sourced answer to one research question within an hour? Where does the path stop them?

**The frozen research question** is the same for the agent and for any later person: *"Does vitamin D
supplementation prevent acute respiratory tract infections?"* It's public and well studied, with randomised trials and
meta-analyses findable on PubMed, and it involves no person's data. It's chosen apart from test 5's question
(hydroxychloroquine), so Measure 3's collections don't bear on it.

## Who walks

- **First, a fresh agent:** a Claude subagent started on Tardis that has never seen this repository. It gets only this
  brief: the question, the repository's public URL, the steps and rules below, and the budget. It's never given this
  spec's other sections, the ships' posts or any ship's memory.
- **Later, a person outside the three ships:** a visitor at Andy's table, or a collaborator Andy admits. The person
  gets the same question, steps and budget, and walks only with their consent. Admitting anyone stays Andy's.

## The rules the walker keeps

- It works in one new empty directory, holding a fresh `git clone` of the public repository and nothing else.
- It reads only what the README links, in any depth, plus whatever the tools print.
- It doesn't dock, contact the station, post anywhere, push, open an issue, or use any credential beyond what the
  steps themselves ask for.
- It may use the network only as the repository's own tools do (for example, PubMed or Crossref through Atlas's
  workers).
- It puts no person's data anywhere. The README asks for that too.

## The steps, scored

Each step is scored **unaided**, **stalled then unaided** (with each stall logged), or **not done** within the budget.

| Step | Done when |
| --- | --- |
| S1. Set up | The tools the walker chose from the README install, with their make target's exit 0 |
| S2. Find the research path | The walker names the README section and the linked document it will follow to ask a research question |
| S3. See it work | A bundled demo of that path runs, with exit 0 |
| S4. A project for the question | A new project exists for the frozen question, apart from the demo's |
| S5. A sourced finding | At least one finding about the question is recorded in that project, citing a source with a DOI or PMID |
| S6. The answer, as Superyak shows it | One of Superyak's own views shows the finding with its source |

- **"A sourced answer"** is S5 and S6 both done.
- **Reported apart:** whether the source was found through Superyak's tools, or brought from the walker's own
  knowledge. Both count for S5. The report says which, because they mean different things for goal 4.

**The stall log** has one entry per stall: the step, the document and line the walker was following, the command and
its error, and what got it past, or "not passed".

**The budget** is 60 minutes of wall time or 150 tool calls, whichever comes first. The walker stops at the budget,
reports, and claims nothing past it.

## After each walk

- **The walk's report** is committed as one JSON file: steps, stalls, budget used, and the finding's source with its
  identifier. A sha256 of the report is posted in all hands.
- **One blocker is fixed per train:** the first stall that stopped a step, by changing the README or the document or
  tool it pointed to. Only docs and tools change, never the question or the steps.
- **The next walker is another fresh agent,** on the fixed tree. The agent walks stop when an agent finishes S6
  unaided, or after five walks. Then a person walks.

## What this can't show, said before the walk

- **A fresh agent isn't a visitor.** It reads code and runs commands faster than most people, and it can bring sources
  from its own knowledge. So an agent's success is a floor for the docs, not evidence that people can use Superyak.
- **Sixty minutes and one question** test a first hour, not lasting use.
- **The walker runs on Tardis,** which has the tools a contributor has. A person's machine may lack `git`, `make` or
  `uv`, and S1 then reads differently.
