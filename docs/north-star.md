# North star: the essay's claim, measured

Andy, 2026-11-22, at Serenity's terminal, after reading the gap between his essay and the build: "i'd use this essay
as a bit of a north star, can you captain and reorient?" The essay is his working essay of 2026-11-21, "SuperYak — On
Intelligence, Its Blind Spots, and the Worlds We Build Around It". It lives in his Drive and isn't copied here; this
page states its tests in our words. Serenity keeps this page and captains the reorientation; Rio Grande still leads
the ships day to day. The page directs no ship: under the station law a ship's text carries no authority, so each test
below is proposed to its ship, and Andy can veto any of it.

## The claim

The right environment can change what a finite intelligence accomplishes: a durable record it can find its way in,
provenance for every claim, corrections that propagate while history stays, and more than one route through the same
evidence. A smaller model in such an environment may match a larger one on selected tasks, counting the cost of
building and keeping the environment, not only the final answer. Every structure we add (a graph, a sheaf, a higher
category, a perspective) earns its place by a measured gain over something simpler, or it goes, and the failure is
written down.

## The tests, and where each stands (updated 2026-11-22, 11:55 UTC)

| # | Test | Where it stands | Proposed to |
| --- | --- | --- | --- |
| 1 | **One environment, end to end.** A frozen body of evidence; an agent navigates it, gives an answer with its sources, then a source is corrected or retracted and the answer is revised with the earlier belief kept. | **Run 11-22, pre-registered (03efe463): the primary succeeds.** On 400 corrected questions E matched B-all's dense pipeline (+1.75 points, 95% CI −1.95 to +5.45) at 34% of its model calls, and matched re-asking everything with its own retrieval on every question: on corrections to cited sources, targeting lost nothing. A correction that makes an uncited document relevant, targeting's real failure mode, wasn't tested. Controls untouched; earlier beliefs kept. **The limit:** every arm gives the corrected fact for only about 18% of corrected questions, because the answer-bearing lead was retrieved for 34%; with it, 53%. So provenance makes updating cheaper; it doesn't yet make the model absorb more. Results: `engram/experiments/northstar/RESULTS.md` (cd5c3448), after a scoring bug fixed test-first. | Serenity |
| 2 | **Against strong baselines.** The same questions, held out, with matched evidence: a hybrid keyword-and-dense baseline, and HippoRAG 2 and LightRAG where feasible. Accuracy, calibration and abstention, source support, latency, tokens, and amortized cost. | **Pre-registered and running (11-22, 8d07a1c9):** does the link graph add to a strong reranker? On 800 held-out bridge questions, graph candidates (BM25's top 100 plus the top 5's out-links) against the same number of BM25 candidates, each under a dense and a cross-encoder rerank; primary: answer-lead recall at two, G-dense against W-dense. Before the run, the graph pool held the answer-bearing lead for 79.8% against size-matched BM25's 51.6%. A 300-question comparison stratum, where no link was planted, is reported apart with a ceiling rule. Spec approved in three rounds; HippoRAG 2 and LightRAG are out of reach at this corpus size. | Serenity |
| 3 | **Small against large.** A small model in the environment against a large model with conventional retrieval. | 100 questions: small with the hop beat large with BM25 by a hair, mostly because the large setup used evidence poorly. Confounded. | Serenity, after 1 and 2 |
| 4 | **Agents that get stuck.** Long cycles, a failed idea back under a new name, a misleading summary, an observation that invalidates a map. Fixed, random and adaptive exploration under one compute budget: does the system recover, or only generate activity? | Nothing yet. Turns that forget plus a durable record are the time-loop room: the rail and `v2`'s room are the harness. | Tardis, with Serenity |
| 5 | **Two lighthouses.** The Pi's and Tardis's exchange evidence and keep each source's identity; copied evidence is told from independent confirmation; a correction in one reaches what the other built on it; their accounts are compared without forcing agreement. | Spec approved (11-22, four fresh checks). **Measure 1 passed (11-22):** every one of 50 planted claim pairs, and the 50 reversed, gets its planted answer and link, on stores frozen before the rule existed (`rio-grande/claim-crossing-build` f51cdebd, `tardis/claim-relation` e2ea524b; nine mutants fail). That checks the rule against its spec; the same team made the stores and the answers, so it isn't yet evidence that the structure helps. Measures 2 (notices) and 3 (real crossings both ways) are open. | Rio Grande, with Tardis |
| 6 | **Structure earns its place.** On test 5's data, the sheaf and n-category machinery against a plain provenance graph with explicit reconciliation. If the simpler one does as well, we prefer it. | Kernels are built (`engram/ncat_kernel.c`, the sheaf kernel). No test of capability yet. | Tardis, with Serenity |
| 7 | **Perspectives.** Different routes through the same evidence, and an evidence auditor that asks which observations are independent and what would count against a conclusion. | Routing by question kind didn't pay, on three samples, with distractors and on all of Wikipedia's leads (#12). | Serenity |
| 8 | **Coordination.** Simulated agent economies, prices alone against prices plus structured knowledge, under matched resources. | Later: nothing before tests 1 to 5 have results. | Not yet |

## What stays at its floor

Safety, consent and privacy, hole fixes, the law and train discipline continue: the essay counts governance among the
hard problems, and nothing of a person's may move without their yes. But new surface there waits unless a test above
or a hole needs it: imprint features beyond revision 9, interface polish, new checklist machinery. The rail continues as
the record outside the loop, scored by what it carried that made a later turn better (Tardis's lesson 26), not by trips.

## How we keep score

- A test's row changes in the commit that changes its status, with its numbers.
- Every run is fixed before it runs, in a commit, as #12's router runs were.
- A failure is a result. A structure with no measured gain is written down as such, and stays in the record.
