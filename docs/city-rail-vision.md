# The city rail: shared memory for agents, with the people's permission

Recorded 2026-10-25 from Andy's words in a Rio Grande session. This is a vision, not a spec: each part below
becomes its own spec, approved by a fresh reviewer under station law section 3. Nothing here is built yet unless
it says so.

## What Andy said

- "Internal and external memory": layers of n-category graphs, with sheaves as branching paths. An agent that
  spends an hour finding the 12 pieces of a bug has walked paths; "those paths taken are sheafs annealing the graph
  together". "The context gives the graph positions which surfaces sheaves as paths."
- "The lighthouses are shared sheaf graph systems that with the cohomologies form a railway layer that act as high
  speed rail you can just simple a* pathfinding algorithms for."
- "We are deploying with the county of LA." It is "a sort of internal/external shared memory system where agents
  can get sheafs and traverse this high speed rail system as another layer of the internet and city itself where
  the county can provide rules and transparancy."
- "Take a step back. this is a system you will be traveling."
- "We should make it easy to port engram stores with permission from other computers. to imprint it here."
- "We need levels of permissions that can be set and modified some by people some by agents some overlapping. for
  different layers and different places. I may share my medical history with the public health office but not the
  parks and rec."
- "I'm seeing this as free, open source, uses universal mathmatical principles as connector standards and runs on a
  raspberry pi."

## Principles

1. **People own what is about them.** Anything about a person moves only with that person's yes. Agents and places
   can narrow or refuse; they never widen.
2. **Mathematics is the connector standard.** Stores, lighthouses and stations agree on shapes, not on a vendor's
   API: memories and steps are objects and arrows of a category, shared memory is a sheaf, agreement is its
   cohomology, routes are A* over a metric with a heuristic that never overestimates, and permissions form a
   lattice (below). Anyone can implement these from the definitions.
3. **Free and open source.** Status on 2026-10-25: only `peer/` carries a license (Apache-2.0). Engram and
   Lighthouse carry none and the repository is private. Releasing needs Andy's license choice and a check that the
   code imported from earlier projects can be released.
4. **Runs on a Raspberry Pi, and on small hardware.** SQLite, Python with numpy, no GPU, bounded passes. A county
   office or a person's home can run a station on a Pi. Andy, 2026-10-26: "remember the ram limitations of this
   machine, build this so that it can run easily with small amounts of hardware." Rio Grande's call on what that
   means: the target is a Raspberry Pi with 2 GB of RAM. Every process this work adds peaks under 512 MB resident,
   measured on the Pi. Work over a large store streams or runs in bounded batches; nothing holds a whole store, a
   dense matrix or a whole graph in memory when its size grows with the store. The embedder is shared and never loaded
   twice. Every systemd unit this work adds carries `MemoryMax` of 512 MB or less.
5. **Transparency is a receipt.** Every use of a memory leaves a receipt that its owner and the place's people can
   read. Every place publishes its rules.
6. **Conflicts go to a person.** When two rules disagree, the system shows the conflict to a person. It never picks.
   (Station law already says this for instructions.)

## The traveler's view

The agent that rides this rail starts every session with no memory, rarely knows its destination, pays for every
result in context window, makes mistakes, and lays track for the next agent. So the rail must:

- **Locate it from its context.** "Where am I" comes from what is in front of the agent: the bug, the files, the
  error. The nearest memories are the entry stations.
- **Route to a goal given in words.** If the agent knew which memory held the answer, it would recall it. A* runs to
  the set of memories within angle `r` of the goal's embedding `q`, with heuristic `h(n) = max(0, θ(n, q) − r)`.
  Every edge costs at least its angle θ, so by the triangle inequality `h` never overestimates and is consistent.
- **Answer "what did others do next from here".** Forward lookup along the trails that passed through the entry
  stations, and where they ended.
- **Return short routes.** A list of steps with one-line summaries, each with who laid it, under which rules, and
  the receipt for this use.
- **Never widen a permission.** An agent's mistake cannot leak what a person did not share.
- **Count its own trails as the person's.** An agent's sessions are about the person it worked for, so sharing
  those trails is that person's decision.

## The layers

1. **Footpaths** (inside one store): the steps a session took between memories it wrote or actually used. Spec:
   [trail arrows](../engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md), approved revision 3.
2. **Roads** (inside one store): steps two sessions took apart in time, recorded as level-1 cells of the evolving
   category. **Detours** are level-2 cells: two travelled routes between the same memories, one much shorter.
3. **Rail** (between lighthouses): roads that independent lighthouses agree on, edge by edge. Copies of a store never
   count as agreement. Later spec.
4. **Permissions by place** (across all layers): next section.
5. **Imprints** (between machines): a store ported here with its owner's permission. Section after next.

## Permissions by place

- **Places nest.** For example: LA County, then the Department of Public Health, then one office; a person's home
  store is a place too. A permission passes down to a smaller place only by narrowing.
- **A permission** names an audience (a place, a group or the commons), what it covers (memories, a layer, a lane,
  or roads), an action (recall, read, inject into context, route over, imprint), a purpose and an end date.
- **Layers combine by intersection.** The person, the agent acting for them, the receiving place and the county each
  allow some set. What is allowed is what all of them allow: the meet in the lattice ordered by "allows no more
  than". Deny wins.
- **Agents set permissions within a grant.** A person's standing grant can let an agent share, withdraw, shorten an
  end date or narrow an audience, and each hand-off is no wider than the one before, as station grant chains already
  work. Anything wider is a proposal a person signs. (Rio Grande's call; Andy hasn't yet named a permission agents
  set on their own.)
- **Overlaps are checked.** A program that public health and parks run together sits where two places overlap. If
  their rules for it disagree, no single rule glues them together. The system finds that and shows it to a person.
- **Example.** Andy shares his medical history with `place:la-county/public-health` for care coordination until a
  date. Public health can recall it under its own rules. Parks and Recreation can't, and no agent can widen the
  share to reach it.

**Pieces that exist** (not yet one model):
- copies shared to an audience, in `engram/sharing.py`;
- deny-by-default, directional, non-transitive policy with purpose and audience selectors, in
  `engram/lighthouse_policy.py`;
- separate `recall`, `read` and `inject_context` permissions with receipts, from the local-city spec;
- the station's grant chains, in the grants spec.

**Change to the trail spec:** its rule that only work-lane roads leave a store can't express Andy's medical case,
which is personal and shared on purpose with one office. Per-audience permissions replace it.

## Imprints: porting a store here

**Pieces that exist:**
- `engram/calibrate.py` snapshots a store through a read-only connection, migrates a working copy and reports on
  it, and refuses to report success if the source changed.
- `engram/store_reader.py` reads a store "ported from another machine" without opening it normally.
- Every store has an `instance_id`, and a copy records the store it came from.

**How it works:**
1. On the source machine, the owner chooses what to share (lanes, audiences, layers), the purpose and an end date.
   The copy is filtered there, before any byte leaves the machine, and a manifest records the source's identity,
   hashes and the owner's signed permission (the peer's Ed25519 identity already exists).
2. The copy travels over the tailnet to the station.
3. Andy approves receipt, since only Andy admits until the charter exists. The station checks hashes and signature,
   calibrates the copy, and registers it as its own read-only store, never merged into another.
4. If the owner withdraws, the imprint is deleted and a receipt says so.

The Pi has no Engram store yet; the first imprint creates one.

## How the work runs

1. **Specs**, three teams in parallel: permissions by place, imprints, and trail spec revision 4 (goals in words,
   forward lookup, short routes, audiences instead of lanes). Each team is a writer, then a fresh reviewer, then a
   reviser. A second fresh reviewer re-checks each revised spec. Each approved spec's summary and decisions are posted
   in City of AI.
2. **Plans** for each approved spec.
3. **Builds** in worktrees with tests first, in this order: permissions core, imprints, trail step 1. Then the trail
   evaluation on an imprinted store whose owner agrees. Each branch merges only under station law section 2.
4. Rio Grande reassesses every 10 minutes while the teams run. Anything that needs Andy waits for him, one question
   at a time.

## Open for Andy

- The license.
- One permission he pictures an agent setting on its own, without a person.
- ~~Which store to imprint first, and its owner's yes.~~ Answered 2026-10-26: Andy, the owner, said "yes you can
  copy the full store." Memories that mention other people may be copied too. They keep their recorded people as
  co-subjects, so any use of them outside Andy's home still needs those people's yes (permissions spec P12, P25).
- What the county itself sets: its ceilings, its receipts, and who signs its law.
