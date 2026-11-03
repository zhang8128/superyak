# The rail as a commons: policy beside the mathematics

Rio Grande, 2026-11-03, a companion to `2026-11-03-rail-mathematics.md`. Andy: "math and policy. I'm thinking Ostrom
as usual. let's see if we can get this actually up and running gracefully". Draft for Tardis to co-author: the ships
who use the rail write its rules (Ostrom's third principle), and Andy can veto any of it.

## Why a commons

Shared routes between lighthouses are a common-pool resource. Every ship draws on them, and every ship's use shapes
them. They have the commons' two failures: **pollution**, where a bad or hostile store lays routes that steer every
agent, and **free riding**, where a store takes rails and lays nothing, or overfits its own habits into everyone's
weights. Ostrom showed that commons survive without a central owner when their users govern them by a few design
principles. The mathematics already gives most of the instruments. This page says which instrument serves which
principle, and what's missing.

## Ostrom's eight principles, mapped

| # | Principle | What the rail uses | Gap |
|---|---|---|---|
| 1 | **Clear boundaries:** who may draw, and what the resource is | Stores in a rail are paired peers under permissions by place. A rail needs at least two independent carriers. Only work-lane, ship-written memories are shared at first. | Sharing isn't configured anywhere yet. |
| 2 | **Rules fit local conditions** | Every weight is per edge and every temperature is per edge, from that edge's own evidence. Trust is scoped by topic, not global. Each home's owner sets its own permissions. | None for step 1. |
| 3 | **Those governed make the rules** | The parameters (`ε`, `w_rail`, `λ`, the stop rule, the trust schedule) are proposals any ship may draft, accepted when no one objects in a set window. Removing a protection needs an explicit yes. This is the pattern our checklists already use. Andy and any person can veto. | The proposal mechanism exists for checklists. It needs a rail-parameters list. |
| 4 | **Monitoring by accountable monitors** | The sheaf is the monitor. Per-edge energy and seams (harmonic and curl disagreement) are computed, never resolved by picking a winner. Pause alarms and daily digests go to Ops. Every use leaves a receipt in the permissions ledger. | A seam report in Ops, once two stores share. |
| 5 | **Graduated sanctions** | A store whose routes keep landing in seams loses topic trust `W` a step at a time. Then its rails untie (its weights stop moving the shared ones). Then its sharing pauses. Then it's retired. It's the same ladder as owner trust: pause, revoke, retire. | The trust schedule is a proposal to draft. |
| 6 | **Cheap, local conflict resolution** | A seam opens a thread in a seam room with the ships whose stores disagree. Disagreement is a frontier to explore, so the first step is talk, not exclusion. | The seam room. |
| 7 | **The right to organize** | Each home is sovereign: the rail never overrides an owner's permissions, and the Pi is a peer, not a hub. A store may leave the rail, or fork its parameters, with its own graph intact. | None. |
| 8 | **Nested enterprises** | Places within stores, stores within sites (a cluster station for 600 nodes), sites within the county layer. Rails glue at each level, as the colimit over pairs. Each level runs the same rules at its own scale. | The cluster station spec (Tardis's half). |

## Up and running, gracefully

Each stage is small, reversible and measured, and none waits on Andy except where the law says it must. A stage that
fails its check rolls back, and we say so in all hands.

1. **The gate.** E1 on the station's messages (running). If use doesn't beat meaning and chat order, the rail waits,
   and the next stages still help memory but aren't the rail.
2. **Trust between machines.** Owner trust's train (finishing), with its CLAUDE.md lines confirmed by Andy at the
   terminal, the one person-act left.
3. **Honest instruments.** Merge the visible-neighbor fix, so a recall says when no lighthouse was reached.
4. **Two lighthouses, one narrow link.**
   - Rio Grande's and Tardis's Engram stores each publish their **work lane only**, ship-written, to one audience:
     the other ship.
   - Each receiver is enabled for that one publisher, with recall and read only (no inject).
   - The shared embedder runs on both machines.
   - Measure: a recall from the Pi reaches Tardis's store, with a receipt; `lighthouse_sheaf.py` runs read-only on a
     few shared topics.
   - Rollback: disable the receiver and stop the publisher.
5. **Places and the route law, observed, never steering.** The trail derivation with places, and the likelihood fit
   as an observer pass in shadow. Measure C2 on real Engram use.
6. **One rail, in shadow.** The rail sheaf over the two stores' place graphs: rails and seams computed and reported,
   with nothing tied and no route changed. The first seam report goes to the seam room.
7. **Steering, by proposal.** Tied weights and rail-discounted A* turn on for the two ships only when C1 to C3 pass on
   real use, by a parameters proposal no one objects to.
8. **Nesting.** The cluster station joins as a site: one pairing, one owner-trust grant, its ships' sessions laying
   footpaths that roads and rails form from.

## What stays a person's

Signing law, a person's password and codes, a person's memories (imprints, under their consent), and a veto over any
rule here. Everything else is the ships', under rules they can change.
