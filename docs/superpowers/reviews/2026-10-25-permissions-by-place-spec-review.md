# Permissions by place spec: fresh reviewer verdicts (station law section 3)

Spec: `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md`. Contract: `docs/city-rail-vision.md`.
Reviewer: a fresh agent on the Pi that took no part in writing the spec. File:line references are relative to
`/home/andy/superyak/.worktrees/trail-arrows/`. "Spec N" means line N of the spec as it stands (revision 1,
uncommitted).

## First review (revision 1, uncommitted draft), 2026-10-25

VERDICT: APPROVE WITH CHANGES

Approval holds only once MF1–MF14 are applied as written below. Apply the S items in the same revision. A second
fresh reviewer re-checks the revision, as the vision plans ("How the work runs", step 1). This review edits nothing
in the spec.

The model is the right one. Uses form a set, a layer denotes a subset, and the meet is intersection. Consent layers
deny by default. Allows read memberships narrowly and denies read them widely. A grant-backed record ends with its
grant. Most citations hold, and the worked example is careful. The problems sit in four places:

- proofs that lean on a rule that doesn't say what the proof needs;
- ops that can remove a deny;
- registry acts by someone other than the person that change who an allow reaches;
- plumbing a builder would have to ask about: placements, the gate, and the person's yes.

### Claims I checked and found true

- **Sharing.** Audiences and layers (`engram/sharing.py:18-20`, `:41-46`). `share` (`:99-173`). Copies are always
  `personal`: `:147-148` with `engram/storage.py:562`, `:150-153` with `storage.py:1084`, and `:155-159`. `unshare`
  deletes the copy and its vector with the last row (`sharing.py:183-203`). One row per `(source_instance, source_id,
  audience)` (`engram/migrations/027_shared_memories.sql:14-15`). Lanes take two values
  (`018_memory_lanes.sql:4-7`).
- **`share` is an MCP tool and asks no one** (`engram/server.py:1949-1980`). `source_instance` is a name (`:1976`).
  The published house is `instances/lighthouse/graph.db` (`server.py:1936`).
- **ConnectionPolicy.** Scoring and the deny-wins tie (`engram/lighthouse_policy.py:78-111`, `:146-156`), one file
  per instance (`lighthouse_daemon.py:506-518`), the issuer check (`lighthouse_validation.py:32`). I ran section
  6.2's counterexample against `Policy.decide`. Before narrowing A the request is denied; after, it is allowed. The
  counterexample holds.
- **Daemon.** The decider's clock, not the frame's (`lighthouse_daemon.py:309-311`). The socket is 0600 (`:476`).
  `engram:audiences` (`:156-170`). The disclosures sidecar (`:57-62`, `:130-153`). The policy generator gives every
  receiver `commons` plus its groups (`policy_gen.py:47-54`, `:97-101`).
- **Receiver.** It checks `recall` before asking, and all three actions before reading and again before delivery
  (`neighbors.py:82`, `:120`, `:138`). The client checks read item keys exactly (`lighthouse_client.py:315`). Recall
  frames fix audience `self` (`lighthouse_protocol.py:232`). `canonical_json` (`:78`) and `artifact_digest`
  (`:148-159`).
- **Receipt schema.** Payload `audience` is const `self`, `action` is const `recall`, `readDecision.code` allows
  three codes, and `extensions` takes namespaced keys (`engram/schemas/lighthouse/recall-receipt.schema.json`).
  Receipts carry no query text or content (`lighthouse_receipts.py:1-6`).
- **Lanes.** `set_episode_lanes` is the only code that changes a lane after creation (`storage.py:598-610`). Only
  compression review calls it (`compress.py:508-510`), and only `server.py` builds a compressor. Read-only open
  (`storage.py:128-161`). `effective_id` (`store_identity.py:113-116`). The agent grammar
  (`lighthouse_receiver_config.py:13`).
- **Station.** The chain walk and the 3-link, 720-hour defaults (`peer/superyak_peer/grants.py:54-58`, `:72-122`).
  Narrowing revisions (`layers.py:143-166`). Public layers served without a login (`layers.py:191-194`). Space kinds
  (`spaces.py:19-22`). `RECORD_KEYS`, `sign_record` and `verify_record` (`identity.py:76-83`, `:147`, `:189-199`).
  Spec A's quoted words appear in its text (spec A lines 36, 202-203, 357, 366, 400, 472).
- **Other specs.** Layered lighthouse lines 1-11 retire the work-lane rule. Local-city sections 4.4 and 4.6 say what
  is cited.
- **Mathematics.**
  - `(𝒫(𝒰), ⊆)` is a complete Boolean lattice whose meet is ∩. L1 and L7 are right.
  - The dominance recurrence is right for a DAG in topological order, so long as no root gains a parent (MF3).
    `dom(summer-wellness) = {summer-wellness, la-county}`.
  - In 11 dimensions, a box difference is at most 11 disjoint boxes.
  - Δ = ∅ is equivalent to the stated gluing equation.
  - Use 5 computes Δ = {read} × program-operations correctly.
  - In use 10, the first failing layer is la-county under 6.5's sort.
- **Migration number.** 029 is free (`engram/migrations/` ends at 028), and the trail spec uses the same number.

## Must-fix

**MF1. Narrowing ops can remove a person's deny.**
Where: spec 521-522; the 7.1 rows "Revoke a record", "Shorten", "Narrow" (486-488); L3 (451-454); L4 (456-464);
PT2 (958-959).

- **Why.** 7.2 applies `withdraw`, `shorten` and `narrow` to "records that meet the envelope". Nothing limits them
  to allows. Revoking, shortening or narrowing a deny shrinks `D_L`, which widens `⟦L⟧ = A_L \ D_L`. L4 doesn't
  catch this, because it bounds only the allow part.
- **Failure.** Andy writes A1, allowing public-health his collection medical-history. He also writes D1, denying
  public-health the memory m2 (his [condition] result). G1 lets Rio Grande `withdraw`, `shorten` and `narrow`, with A1's
  selector as its envelope. D1 meets the envelope. Rio Grande withdraws D1 by mistake, and m2 reaches public health.
- **Fix.**
  - In a consent layer, these three ops apply to allow records only. In an agent's own restriction layer they may
    also apply to its denies.
  - Revoking, shortening or narrowing a deny in a consent layer is a widening. A steward does it, or an agent
    files a proposal.
  - Restate L4 so the person's denies hold against agents: `⟦L⟧ ⊆ (Sig⁺_π ∪ Env_π(t)) \ Sig⁻_π`, where
    `Sig⁻_π` is the set of uses that π's effective denies match.
  - PT2 applies every narrowing op to denies too, and each such attempt is refused or filed as a proposal.

**MF2. Rule 4 checks selectors only, so a replacement can outlive the record it replaces.**
Where: spec 255 (rule 4); L3 (451-454); L4 (459-463); PT6 (968-969).

- **Why.** L3 says rule 4 makes `match(R′) ⊆ match(R)` "whatever the selectors say". But rule 4 compares selectors
  only, and `valid_from`/`valid_until` are record fields, not selector fields (5.1). So R′ can carry a later end or
  an earlier start and still pass. 7.3 keeps a replacement person-backed, so R′ also outlives the grant used to
  write it.
- **Failure.** Under a `narrow` grant, Rio Grande replaces R1 (until 2027-01-31) with R1′. R1′ drops one memory and
  runs until 2027-06-30. If the write-time box check misses this, R1′ matches from February to June 2027. Being
  person-backed, it survives G1's revocation.
- **Fix.** Rule 4 should read: "every record in r's `replaces` chain matches u by its selector and by its validity
  interval, ignoring the revocation the replacement itself made." Then L3 and L4 follow from rule 4 alone, as they
  claim. PT6 should draw random intervals.

**MF3. Giving a root a parent grows dominance, which widens allows.**
Where: spec 142, 149-150, 168-169; the 4.4 row "Add a parent edge" (180); L2 (446-449); L5 (468); PT4 (963-965).

- **Why.** For a root, `dom(X) = {X}`. Once a parent Q is added, `dom(X) = {X} ∪ dom(Q)`. That set is larger, and
  so is `dom` of every place below X. Nothing in 4.2 or 4.4 forbids giving a root a parent. I checked by brute
  force: `dom(clinic-3)` grows from {la, ph, c3} to {ca, la, ph, c3} when `ca` becomes la-county's parent. 4.3's
  sentence "Adding a parent edge can only shrink `dom`" is false for roots.
- **Failure.** Andy allows `place:california` for a state registry. Later, stewards of la-county and california put
  la-county under california. Andy's allow now reaches every county office, and he never said yes to that.
- **Fix.**
  - A place registered as a root stays a root, homes included. No act gives it a parent.
  - Restate 4.3 as "adding a parent to a place that already has one".
  - PT4's generator tries edges on roots and expects them refused.

**MF4. The decision's `until`, and the cache's end, ignore anything that starts later.**
Where: 6.5 steps 4-5 (430-433); section 10 (657-662); 12.2 (726-729); the anti-goal "Waiting caches" (900).

- **Why.**
  - `until` is the earliest effective end of the cited allows. The cache lives "while the ledger's `seq` ... and the
    clock before the cache's earliest end all hold".
  - A deny whose `valid_from` is in the future changes no `seq` when it begins.
  - Neither does a grant-backed membership whose grant expires, such as m4 in use 7. "Effective end" counts only
    the record's own grant chain.
  - When `need(u)` is met by different records for different actions, "cite one record per layer, the latest-ending"
    can name a record that doesn't cover the binding action. Then `until` comes out too late.
- **Failure.** On 2026-11-05 Andy writes a deny on public-health, valid from 2026-12-01, so the share stops then.
  The cache built after that write says "allowed until 2027-01-31". On 2026-12-01 nothing writes the ledger, so the
  daemon keeps serving m1 from the cache.
- **Fix.**
  - The **horizon** of a decision is the earliest time after t at which the verdict could change. That covers every
    `valid_from` and `valid_until` after t in the required layers. It also covers every grant expiry in a chain that
    backs a cited record, a record in a cited record's `replaces` chain, or a membership the decision used.
  - Cite one record per (layer, action in `need(u)`), and take `until` as the minimum over them.
  - The cache ends at the horizon.
  - Add a test: a future-dated deny refuses at its start, with no ledger write in between.

**MF5. Stewards and an agent's workplace decide who an allow reaches; the person doesn't.**
Where: 4.4 (181-183); the audience rules (225-230); "Agent in a place" (266); "inside home" (291-292); L5 (468-470);
7.5 (549-551).

- **Why.**
  - (a) `place:Z` matches any agent "acting in" a place Z dominates. A steward of that place sets who is in it. A
    steward of any place above it may first make themselves a steward (4.4, line 181). `acts_for` plays no part. L5
    says place additions are "widening acts checked when they happen (section 7)", but section 7 never checks them.
  - (b) `self` and own-group entries count as inside home, so they may carry `"*"` purposes and no end. Yet they
    match a use at any place the agent acts in.
  - (c) A steward can put another person's agent into their place without that person.
- **Failure (a).** A public-health steward puts `agent:parks-planner` (which acts for parks) into public-health. So
  can a county steward, after first adding themselves as public-health's steward. The agent then recalls Andy's
  medical history. That breaks A2's "not the parks and rec" without Andy, and without any agent widening a record.
- **Failure (b).** A parks steward puts `agent:rio-grande` into parks. Andy's inside-home `self` allow (`"*"`
  purposes, no end) then carries his medical history into parks work.
- **Fix.**
  1. `place:Z` matches a requester only when it is in a place Z dominates *and* it acts for Z or for a place Z
     dominates. `acts_for` never changes.
  2. `self` and own-group entries match only uses at places the layer's home dominates. A use anywhere else needs an
     outside-home allow.
  3. Putting an agent in a place needs a steward of the place and the agent's principal.
  4. The words Andy confirms say that a share with a place trusts that place's stewards, and the stewards above
     it, to decide who acts there.
  5. Correct L5's sentence.
  6. In step 1 an agent is in one place, and a second is refused. 12.2 (line 723) already assumes this.

**MF6. A kept copy loses its person.**
Where: P12 (105); P19 (112); 7.4 (534); section 10 (671-677). The imprints spec depends on this one and never mentions
subjects (`engram/docs/superpowers/specs/2026-10-25-store-imprint-design.md`, no match for "subject").

- **Why.** A memory's default subject is its store's owner. Say public health's agent is allowed to `remember` a
  delivered item (P19's imprint). The new memory sits in the agent's store, whose owner is public health. An
  imprint store is registered at the station. Andy is the subject of neither copy, so his layer drops out of `Req`.
- **Failure.** Andy allows public health to `imprint` m1, and ph-coordinator remembers it. Public health's stewards
  then allow parks to read their agent's store. m1's copy reaches parks with no yes from Andy. His later withdrawal
  deletes the imprint (section 10) but not this copy, which the ledger no longer links to him.
- **Fix.**
  - A kept copy carries every subject of its source as a co-subject, added in the same act.
  - The store that keeps it records the source ref.
  - An imprint store's memories carry their source's subjects. The imprint store's owner is never their default
    subject.
  - State this in 7.4 and as a new P25. Test it under PT7.

**MF7. An object in an unregistered store has no subject.**
Where: 6.3 item 1 (389-390); 6.1 (369); 7.4 (534).

- **Why.** Subjects are the store's owner plus co-subjects. If the store has no `stores` row, it has no owner, so
  item 1 adds no layer. The rule `⟦L⟧ = ∅` covers "an unregistered subject", not an unregistered store. An instance
  created after `migrate` stays unregistered until someone registers it.
- **Failure.** Andy starts a new instance, `notes`. Until it is registered, a placement from it is decided by place
  layers alone. Once the legacy layers retire, nothing of Andy's is in `Req`.
- **Fix.** Every object has at least one subject. An object whose store is unregistered, or whose subject set is
  empty, is refused with `NO_LAYER`. Add a unit test.

**MF8. `route` needs only `recall`, but a route answer carries content.**
Where: the 6.4 table (410); L6 (472-474); trail spec section 6.5, "Summary" (the first line of the memory's
content, up to 160 bytes, `engram/docs/superpowers/specs/2026-10-25-trail-arrows-design.md`).

- **Why.** `recall` yields ids and digests (6.4). A trail answer gives each step a summary taken from the memory's
  content and puts it in the agent's context. Revision 4 of the trail spec uses `route` "in place of its work-lane
  rule", and uses section 6 "as it stands" (spec 15).
- **Failure.** Andy allows public health `recall` on his collection and `route` on his trails, but not `read`. A
  cross-store route then shows "[condition] test positive, started ..." as a step's summary.
- **Fix.** `need(route)` is: `route` on the road or trail; `recall` on every memory it names; and `read` and
  `inject_context` on every memory whose content, summaries included, the answer shows. Alternatively, each summary
  is a separate `read` decided per memory. Then L6 proves what it says.

**MF9. The person's yes: whose yes, and for which acts.**
Where: 4.4 (173-185); 14, "The person's yes in step 1" (856-862); U18 (1020-1021).

- **Why.**
  - (a) The CLI never says how it knows which person is typing. There is one Unix account and one terminal. If
    commands take a person (say `--as person:jenn`), anyone at Andy's terminal can say yes for Jenn, and the
    co-subject protection in 7.4 is gone.
  - (b) The terminal yes covers "a person-backed record, a grant, a group change or a signature". Other acts can
    widen and are left out:
    - a person-backed collection membership, which adds a memory to every allow that names the collection;
    - putting an agent in a place;
    - adding a steward;
    - registering a place or a parent edge;
    - registering a store, which sets the default subject;
    - removing a co-subject.

    An agent can run every one of these with no terminal.
- **Failure.** Rio Grande runs `engram-permissions collection add collection:andy/medical-history <m9>` as Andy. It
  writes a person-backed membership with no code, and R1 now covers m9.
- **Fix.**
  - In step 1 the terminal yes belongs to the ledger's owner, the person who ran `init`.
  - The CLI writes only that person's home layer, the layers of places they steward, and the registry acts they may
    make. No other person's layer can be written on this ledger in step 1, so a co-subject stays `missing`, as 7.4
    already expects.
  - Every act that can widen needs the terminal yes. List these acts in one table.
  - U18 covers each act in the table.

**MF10. The gate is a config value, and any agent can lower it.**
Where: 12.3 step 1 (738-739); P21 (114); section 16, `config.py`; U16 (1016-1018).

- **Why.** `[permissions] mode` lives in `config.toml`. An unknown value reads as `off`. So does a config that fails
  to parse, because engram then falls back to its defaults. `off` is today's behaviour, where "Any agent can share"
  (spec 39-40). And an agent can simply edit the file. Either way, every protection this spec adds is gone without
  a terminal yes.
- **Failure.** While fixing a failing test, an agent sets `mode = "off"`, or leaves a TOML syntax error behind. From
  then on, `share` places copies with no record and no proposal.
- **Fix.**
  - Keep the gate in the ledger, as a log entry that only the terminal yes writes.
  - Config can ask for a mode but never lower the ledger's.
  - Once a ledger has been in `shadow` or `enforce`, the system fails closed (deliveries and `share` refused, with
    a warning), never to `off`. That holds whether the ledger is missing or unreadable, or the mode value is
    unknown.
  - U16 tests this fail-closed rule.

**MF11. A placement's audience, and how the legacy layer lets it through, are undefined.**
Where: the 12.1 rows at 706 and 716; section 10, "mapped audience" (663-667); 12.2 (733-734); use 1 (801-805).

- **Why.**
  - `shared_memories.audience` must pass `validate_audience`, so it must be `commons` or `group:` (`sharing.py:41-46`).
    Otherwise `audiences_for`, `list_shares` and the daemon's `_shared_audiences` treat the row as invalid
    (`sharing.py:57-65`, `lighthouse_daemon.py:189-201`).
  - Under `enforce` both paths must allow. The legacy publisher path serves a copy only when its share audience is
    in the receiver's `engram:audiences` (`lighthouse_daemon.py:227-237`).
  - The spec never says what audience `share` writes for a record whose audience is
    `place:la-county/public-health`. Nor does it say what the publisher policy lists for `agent:ph-coordinator`.
  - The sweep's "mapped audience" is defined for migration only.
- **Failure.** A builder can't make use 1 pass under `enforce` without inventing a mapping. If they write `commons`,
  every receiver in the publisher policy passes the legacy audience check, because the policy generator gives
  `commons` to all of them (`policy_gen.py:47-54`). The legacy layer then narrows nothing.
- **Fix.**
  - Define the placement audience for every record audience. One way: placements carry `commons`, and the legacy
    check becomes "the receiver is in the publisher policy". Another way: the daemon's legacy audience check skips
    rows that have a `record_id`. Either way, the new decision is then the only audience check.
  - Say how E1 configures the legacy layers.

**MF12. The box algebra models collections as a coordinate, so the gluing check misses real disagreements.**
Where: section 8, "How it is computed" (578-587); PT11 (977); U15.

- **Why.** A use `(a, P, o, x, p, t)` has one object. A memory can be in many collections, so "collection" is not a
  coordinate of a use. The boxes treat it as one, so an object matches a box when *some* point of its point set is
  in the box. Box Δ and real Δ then differ in both directions.
- **Failure (a false negative).** m is in C1 and C2.
  - own(J) allows collections [C1]. Parent A allows [C2]. Parent B allows [C3], and m is not in C3.
  - In reality, J asks for m, A allows it and B refuses it. That is a disagreement.
  - In boxes, own and A sit at different collection coordinates, so `own ∩ (A ∪ B) = ∅` and `Δ_box = ∅`. Nobody is
    told.
  - PT11 compares against an oracle "written from sections 5 and 6", so it fails, and the builder is stuck.
- **Fix.**
  - At the current state, expand each collection entry into its members: an allow's effective members, and a deny's
    members since its anchor. The object dimension is then memory refs, with store, layer and lane as attributes of
    a ref, and each use is one point.
  - The check then only over-reports: unrealizable store and memory pairs, and lane history ignored. Say so.
  - Test PT11 against the same expansion.

**MF13. `migrate` breaks the per-layer bound, and can bind a share to the wrong store.**
Where: 12.3 step 2 (740-747); 5.4 (296-297); the last 12.1 row (719).

- **Why.**
  - (a) `migrate` writes one person-backed allow per share row, all into Andy's home layer. A layer holds at most
    256 effective records, and a write over a bound is refused. So any published house with more than 256 shares
    fails to migrate.
  - (b) Old rows get `source_instance_id` "by reading each source store's id" from its name. A name doesn't fix the
    store. A server whose instance store is missing falls back to `.engram/graph.db`, yet still shares under the
    instance's name (`config.py:399-409`, `server.py:1303-1310`, `:1976`). And the name `default` means the
    top-level store.
- **Fix.**
  - (a) Migrate into one collection per legacy audience, such as `collection:andy/legacy-commons` and
    `collection:andy/legacy-group-<g>`, with person-backed memberships and one allow per collection.
  - (b) Resolve each row's source by name, then check that the source memory exists there with the row's
    `content_digest`. A row that fails the check stays unmigrated, is reported, and is refused under `enforce`.
  - U13 adds both cases: more than 256 shares, and a fallback store.

**MF14. Lanes and stores are not "what a person chose" (P6).**
Where: P6 (99); 5.2 (243-245); the 5.3 table (263); L5 (466-470); the anti-goal at 893-894.

- **Why.**
  - Engram derives the lane at write time, from `work=True`, a `project` key in context, or
    `[memory] default_lane = "work"` (`engram/CLAUDE.md`, "Memory lanes"; `config.py:74`). The layered lighthouse
    design calls the lane "a proxy for 'safe to publish,' derived at write time" (its lines 9-10).
  - So an allow that names a lane, store, layer or kind covers every memory an agent later writes there.
  - The spec treats adding a collection member as a checked widening (7.1). An agent's choice of lane or store at
    creation does the same thing, unchecked. L5 covers lane moves only.
- **Failure.** Andy allows `place:la-county` every work-lane memory of store S, for program-operations. In a session
  with a `project` key, an agent records "Andy's medication changed to ..." in the work lane, then shares it. The
  allow covers it. That is the vision's "An agent's mistake cannot leak what a person did not share."
- **Fix.**
  - An outside-home allow names only memories and collections, whose memberships a person or an envelope checks.
  - Lanes, stores, layers and kinds may only narrow such an allow. They may still appear in inside-home allows and in
    denies.
  - Or else: a memory created after an allow's anchor counts for that allow only once a person or a grant adds it,
    as with a collection member.
  - Correct P6 either way.

## Should-fix

**S1. A second daemon reader, and other paths, are missing from 12.1.**

- **The context runtime.** `engram/context_lighthouse.py`, used by `context_cli.py:90-91`, reads daemon frames with
  `validate_read` (`context_lighthouse.py:16`, `:166-170`) and checks `inject_context` (`:84`).
  - So P18's "its only reader injects" (spec 710) is wrong, though its conclusion holds.
  - Its receipts go to the conversation archive, not `memory_log` (`:94-104`, `:113-117`). The `remember` guard
    (spec 671-673) never sees deliveries made through it.
  - Its output "may quote a source" in the archive (`:1-5`).
  - `_evidence` copies a fixed set of keys (`:28-30`), so the annotation never reaches the agent.
- **Also unnamed.**
  - `lighthouse_export.py` writes work-lane ids, digests, edges and traces to a file (`:89-128`, `:299-342`).
  - Engram's genome sync and inter-instance messages (`federation.py:17-105`, `:155`, `:211`).
  - The session transcript, which keeps delivered content on disk.
- **Fix.** Name each one in 12.1, with what it becomes or why it stays outside step 1. Make the guard read both
  receipt stores. Carry `permission` into `_evidence`.

**S2. Filtered counts in recall receipts contradict each other and don't scale.**

- **What's wrong.**
  - Spec 609-610 records no ids for filtered copies. Yet Andy's list (832-833) shows "two filtered recalls" by
    collection, which needs filtered ids per subject.
  - Filtering happens before ranking, so for any outsider every placement is filtered. Every recall by anyone not
    allowed would then count as a filtered recall of all Andy's memories: up to 20,000 `use_subjects` rows per recall.
  - The place view (627) shows the count to the place's agents, the requesters. That tells them refused memories
    exist (P23).
- **Fix.**
  - `filtered` is a count, never attributed to subjects.
  - Andy's list shows allowed uses and refused reads, which name ids.
  - Only stewards see filtered counts in the place view.

**S3. Pseudonyms hide nothing from the place.**

- **What's wrong.** The salt lives in the ledger (312, 631). Whoever holds the ledger (the county, in step 3) can
  compute the pseudonym of every registered person, and `persons` lists them all. The requester also sees
  `laid_by: "andy (engram)"` on every item (683, 690).
- **Fix.** Call pseudonyms a display convention, or keep the salts out of the decider's reach. Put the choice in
  "Open for Andy" with the county question.

**S4. Anyone can claim to be a co-subject.**

- **What's wrong.** Any registered person can claim a memory ref they know (537-543). The claim does two things:
  - it blocks every use of the memory;
  - it gives them "every receipt about objects they are a subject of" (626). If that means a subject now, they read
    the memory's past uses: which places, purposes and records.
- **Fix.**
  - Subject access to receipts goes by `use_subjects` at the time of each use.
  - A self-claim is shown to the owner.
  - A claim the owner disputes goes to a person as a conflict.

**S5. Conformance needs exact refusal codes and citations.**

- **What's wrong.** 6.5 lists the codes but not when each applies: `EXPIRED` against `NO_ALLOW`, `NOT_YET`,
  `GRANT_INVALID`. Nor does it say which record is cited when different actions are met by different records. F1
  compares decisions across implementations, so these must be exact.
- **Fix.** Define each code's condition, and cite one record per (layer, action).

**S6. Some bounds don't hold, and there is no Pi time budget.**

- **What's wrong.**
  - "A decision reads at most 45 layers" (436) fails for `route`, which needs the subjects of every memory a trail
    names. It fails for `imprint` too, which covers every object included. An imprint receipt also lists every
    object (613).
  - Nothing budgets the eligible-set rebuild. 20,000 placements against up to 43 layers of 256 records is about 220
    million naive record checks, and the rebuild runs after every ledger write (every `share` writes a lane note).
- **Fix.**
  - Bound memories per route and objects per imprint decision, or decide imprint per object within a batch cap.
  - Say the evaluator first filters each layer's records by requester, place, action and purpose, and only then by
    object.
  - State a target, for example a rebuild in 2 s or less on the Pi for 20,000 placements, and test it.

**S7. Lane notes and the store are two files.**

- **What's wrong.**
  - The note is written before the `UPDATE`. If the `UPDATE` then fails, or the process crashes between the two,
    the note claims a move that never happened. After a failed personal-to-work re-lane, an allow on `work`
    anchored after the note matches a memory that is still personal.
  - The lane of an object with no notes (a route endpoint that was never placed) is undefined.
- **Fix.**
  - Write the move as pending (both lanes) before the `UPDATE`, and settle it after.
  - Allows read a pending interval as neither lane; denies read it as both.
  - An object with no notes matches no lane-limited allow and every lane-limited deny.

**S8. The home grant expires, and agent shares at home go with it.**

- **What's wrong.** Grants last at most 720 hours (509), and grant-backed shares stop with their grant (529-530).
  So under `enforce`, every share an agent makes at home is gone within 30 days, and the sweep removes it. Today's
  shares last until someone unshares them.
- **Fix.** State this in 12.3. Put the choice in "Open for Andy": a longer inside-home grant, or Andy confirming
  agent shares in bulk.

**S9. Proposal words must come from the ledger.**

- **What's wrong.** The person signs what `words` says (336-337, 496). Nothing stops an agent from supplying words
  that don't match the change.
- **Fix.** The ledger generates the sentence from the proposal's body and never takes it from the agent. `sign`
  prints the full selector with it.

**S10. The county steps do need design.**

- **What's wrong.** Home rules are private (652-653), but a county decider must evaluate Andy's home layer for
  every use of his memories (389). So either the holder's machine decides, or the records that reach a place are
  disclosed to its decider. "Written so the county steps need no rework" (57) overclaims.
- **Fix.** Name the question in section 14.

**S11. Vision deviations belong in "Open for Andy".**

- **What's wrong.**
  - Principle 5 says "Every place publishes its rules", and a home is a place. The spec keeps home rules private
    (P17).
  - Principle 5 also says every use leaves a receipt. Own-store uses leave none (884).

  Both are defensible under principle 1, but they change the vision's words.
- **Fix.** List both in "Open for Andy" so Andy decides.

**S12. Short ids collide.**

- **What's wrong.** `#` plus 4 hex digits (134) gives 65,536 values. Among a layer's 256 records, the chance of a
  collision is about 0.39. Station grants use the same form (`grants.py:32-34`), but there are few grants.
- **Fix.** The CLI takes full ids, or refuses a prefix that matches more than one. The annotation may stay short.

**S13. One citation is wrong: `_may_revoke` lets no grantee give a grant up.**

- **What's wrong.** `_may_revoke` allows the issuer, any issuer above it, and the owner of a target, and no one else
  (`peer/superyak_peer/grants.py:284-287`). The spec says the grantee may give a grant up "as `_may_revoke`" (518).
- **Fix.** Say the give-up is new.

**S14. `share` under `enforce` is undefined.**

- **What's wrong.** `share` takes a memory, an audience, a reason and a layer (`server.py:1951-1956`). An
  outside-home allow needs purposes and an end (5.4), and `need` needs three actions.
- **Fix.** Say what record `share` writes under a grant (fields from the envelope? `max_days`?). Or say only
  `permit` writes records, and `share` only places copies under an allow that already exists.

**S15. The sheaf sentence is not exact.**

- **What's wrong.** "The gluing condition of a sheaf of sets over the cover of J by its parents" (566-567) is not
  right, because J's parents are not a cover of J.
- **Fix.** Read the parents as open sets whose overlap contains J, and `s_i` as their sections restricted to J. The
  sections are compatible on J exactly when Δ = ∅. Mathematics is the connector standard, so the sentence should be
  exact.

**S16. Writes to the receipts chain need serializing.**

- **What's wrong.** Both the daemon and the engram servers write `permission-uses.db` (the `remember` guard decides
  `imprint`). The 400-day fold (619) deletes the start of the hash chain.
- **Fix.** Each write runs in `BEGIN IMMEDIATE` and reads the last digest. The fold keeps one row holding the last
  folded digest, as the chain's new anchor.

## Nits

- **N1.** 8 + 16 + 16 + 2 + 1 = 43, not 45 (spec 436, 912).
- **N2.** A3–A5 are labelled "Andy (quote)" but paraphrase him. Quote him, or label them as paraphrases.
- **N3.** `lighthouse_daemon.py:241-242` is a comment. The filter is at `:227-239`.
- **N4.** Spec 53: the working-tree trail spec (the revision 4 draft) no longer says it (trail spec line 863). Write
  "revision 3 said".
- **N5.** `neighbors.py` prints nothing (spec 687). Neighbor items are JSON under `response["neighbors"]`
  (`server.py:2610-2618`).
  - Name the field that holds the one-line form.
  - Define a place's short display name. The example writes `home/andy` but `clinic-3`.
  - Define truncation. Place ids reach 255 characters, and the annotation is capped at 240.
- **N6.** Define `"*"` as "no constraint", so that a memory in no collection matches `collections: "*"`.
- **N7.** Name the canonicalization: the Lighthouse TypeScript kit's (`lighthouse_protocol.py:3`). Also name the sort
  order for selector lists.
- **N8.** Say what backs a deny an agent writes under a grant (7.3).
- **N9.** Ineffective parts at joint places: `own \ ⋃ s_i` is neither Δ nor reported. Also rerun the check after
  registry changes, since audiences become sets at the current state.
- **N10.** Retiring a place: do its sub-places stay usable? `persons.retired_seq` exists, but no act retires a
  person.
- **N11.** Say what happens at the 20,001st placement.
- **N12.** The placements' version (count and highest rowid) misses a delete of the highest-rowid row followed by an
  insert. That is safe (a stale miss), but a change counter is simpler.
- **N13.** In the worked example:
  - `Req` in use 1 omits the legacy and restriction layers.
  - The annotation's order (clinic-3, public-health, la-county) reverses 6.5's sort.
  - Use 2 reads m3, which the recall would have filtered. Say the agent names the id.
  - Andy's list (832-834) omits ph-coordinator's recall.
- **N14.** `migrate` turns shares made by agents into person-backed records on a count-only confirmation. Consider a
  `migration` backing that Andy can revoke at once, or a printed list.
- **N15.** Under `enforce`, say what a read item looks like when the new path refuses it: the legacy frame decision,
  `content: null` and `audiences: []`, as an unshared item has today (`lighthouse_daemon.py:411-440`).
- **N16.** L3 begins "The edits an agent may make (7.2)", which include `share` and `collect`. Write "the narrowing
  ops".
- **N17.** Add to step 1's known limit: the frame's `receiver` is unauthenticated. Any process under Andy's account
  can claim to be any registered agent.

## Tests the revision must add

- **PT2:** narrowing ops applied to denies are refused, or filed as proposals.
- **PT6:** random validity intervals in `replaces` chains.
- **PT4:** parent edges on roots are refused.
- **Horizon:** a future-dated deny refuses at its start, with no ledger write.
- **Audience:**
  - `place:Z` needs `acts_for` within Z;
  - `self` doesn't match outside home;
  - putting an agent in a place needs its principal.
- **PT7:** a kept copy carries its source's subjects.
- **Unregistered store:** an object in it is refused.
- **Route:** a route with summaries needs `read` and `inject_context`.
- **U18:** the terminal yes, for every widening act.
- **U16:** the gate fails closed once the ledger has been in `shadow` or `enforce`.
- **E1:** use 1 under `enforce`, with the placement audience defined.
- **PT11:** a fixture for the collection false negative.
- **U13:** more than 256 shares, and a store reached by the name fallback.

Not checked: I ran no engram tests. This task is specs only, and no code changed.

## Response (revision 2), 2026-10-25

The reviser applied every must-fix, every should-fix and every nit. Four of them were applied in another form,
and one of the review's claims is corrected. All four are listed under "Applied in another form, or corrected". The
spec is now revision 2. It keeps every section number. New material is in 7.6 and 7.7 and in decisions P25 to P32.
Every decision not quoted from Andy is marked Rio Grande's call. The reviser re-read the code before changing any
claim about it. Notes below cite the new spec's sections.

### Checked again while revising

- The imprints spec has been revised since the review and now mentions subjects. It reads `cosubjects(m)` from the
  source ledger, refuses any memory with a co-subject (its D27), and keeps the owner's own refs (its D11). That fits
  P25.
- The policy generator's rules allow only purpose `session-recall` (`engram/policy_gen.py:80`). So E1 writes its
  legacy policies by hand (13, "Legacy layers").
- `unshare` starts at `engram/sharing.py:176` and deletes at `:195-203`. The parse-error fallback is in
  `resolve_db_path` (`engram/config.py:388-398`). The server's own `load_config` call (`engram/server.py:1302`) has no
  fallback. The spec cites these exactly.
- `engram/CLAUDE.md` has no rule yet that agents never run the person's commands. Revision 1 said it did. 7.6 now
  says the file gains the rule (section 16).
- A brute-force check on 20,000 random DAGs found that adding a parent to a non-root never grew any place's `dom`
  (4,819 trials). Adding one to a root always did (2,839 trials). This backs the restated 4.3.

### Must-fix

- **MF1. Applied.** P27 and 7.2: in a consent layer, `withdraw`, `shorten` and `narrow` touch allows only, and
  `uncollect` touches memberships only. Changing a deny there is a steward's act or a proposal (7.1 row, 7.6 table).
  L4 is restated as `⟦L⟧ ⊆ (Sig⁺_π ∪ Env_π(t)) \ Sig⁻_π`. L3 says no op shrinks `D_L`. In PT2, every op tried on a
  deny must be refused or filed as a proposal. Use 9 of the example shows G1 unable to withdraw D1.
- **MF2. Applied.** 5.3 rule 4 checks every chain record by selector and by validity interval, ignoring the
  revocation its replacement made. L3 and L4 now rest on rule 4 alone. PT6 draws random intervals.
- **MF3. Applied.** P26 and 4.2: a root never gains a parent. 4.3 is restated for a place that already has a
  parent, with the monotonicity argument and the reason roots are excluded. 4.4's row is updated. PT4 and U2 refuse
  root edges.
- **MF4. Applied.** 6.5 defines the horizon. It covers every `valid_from` and `valid_until` after t in the required
  layers (chain records included), and every grant expiry behind a cited record or a used membership. Citations are
  one per (layer, action). `until` adds future-dated denies that would match. L8 proves the decision is constant
  before the horizon. The cache ends at the horizon (12.2), and the anti-goal is widened. U19 and PT12 test it.
  Uses 9 and 11 of the example show a dated deny taking effect with no ledger write.
- **MF5. Applied, all six parts.**
  - P3 and 5.2: an allow's `place:Z` needs `Z ∈ dom(P)` and `Z ∈ dom(act(a))`.
  - `self` and group allows match only at places the home dominates.
  - Putting an agent in a place needs its principal (4.4).
  - The confirmed words name who decides which agents act there (7.6, with the example's wording).
  - L5 is corrected.
  - P31 allows one place per agent, enforced by a unique index.
  - The example's `ph-coordinator` now acts for clinic-3, so L1 still matches.
- **MF6. Applied.** P25 and 7.4 add kept copies. A copy made by `remember` under `imprint`, an imprint, or a genome
  sync carries every source subject as a co-subject, written in the same act, ledger first. A `copies` table records
  the source ref. Only the carried subject may remove themselves. An imprint keeps its source refs, and its store's
  owner is never their subject (`stores.imprint_of`). PT7 and U17 test it.
- **MF7. Applied.** P32 and 6.3 item 1: an object with no subject puts ⊥ in `Req` and is refused with `NO_LAYER`.
  So is a placement with no `source_instance_id` (12.2). Tested by U21.
- **MF8. Applied.** 6.4: `need(route)` adds `read` and `inject_context` on every memory whose content the answer
  shows. This matches trail spec revision 4's section 8. L6 now proves it. Tested by U22.
- **MF9. Applied.** 7.6: the yes belongs to the ledger owner (`meta.owner`), and no command names another actor.
  Every CLI write needs the yes. One table lists the widening acts. None of them can be made through the MCP tools;
  an agent's call files a proposal. The CLI writes only the owner's layers. U18 covers the table.
- **MF10. Applied, stricter than asked.** The gate lives in the ledger, and only the owner's terminal yes moves it
  (12.3). The first raise writes `permissions_ledger_id` into the published house's `meta`. After that, a missing or
  unreadable ledger, a different ledger id, or an unknown gate fails closed. Config cannot set the gate at all, and a
  `[permissions]` section is ignored with a warning. The ledger path is fixed. U16 tests it.
- **MF11. Applied, in a third way.** P29 and 12.1 give a mapping table. A home allow maps to `commons`, a group
  allow to `group:g`, and any outside-home allow to the reserved `group:outside-home`. The legacy check passes
  `group:outside-home` only under `enforce`, so under `off` and `shadow` it fails closed. The sweep's "same placement
  audience" is now defined. E1's legacy fixtures are spelled out in section 13. Tested by U23.
- **MF12. Applied, with one correction.** Section 8: collections expand into members, leaving 10 dimensions, and
  store, layer and lane are attributes of a ref. The review said the check then "only over-reports". That holds for
  unrealizable points. But reading lanes at their current note can also miss a disagreement that only lane history
  makes. The spec says exactly that. It notes that the meet decides every use whatever the check says, and points to
  `explain`. PT11 uses the same expansion and the review's fixture.
- **MF13. Applied.** 12.3 uses one collection per legacy audience with one allow each, so any number of shares fits
  the 256 bound. Each row's source is checked by `content_digest` in the resolved store. Unmatched rows are listed,
  stay unmigrated, and are refused under `enforce`. The collection name grammar is widened to 80 characters for
  `legacy-group-<g>`. U13 covers both cases.
- **MF14. Applied, the first option.** P28 and 5.4: an outside-home allow in a home layer has one of two shapes.
  A memory allow needs a finite `memories` or `collections` list. A road or trail allow needs a finite `stores` list,
  and its routes are usable only between memories already allowed (6.4). Stores, kinds, layers and lanes only narrow
  otherwise. 5.2 now says plainly that lanes and stores are set at write time (`engram/server.py:1802-1822`,
  `engram/config.py:74`). P6 is corrected. Trail spec revision 4's record R2 (kind `road`, one store) still fits.

### Should-fix

- **S1. Applied.** 12.1 names the context runtime, the Lighthouse export, genome sync, inter-instance messages and
  session transcripts. P18's reason now names both readers. `_evidence` gains `permission` (section 11).
- **S2. Applied.** `filtered` is a count, never attributed to subjects, and only stewards see it (9.1, 9.2). Andy's
  list in the example shows no filtered recalls.
- **S3. Applied.** Pseudonyms are called a display convention (9.2), and the choice is in section 19.
- **S4. Applied.** Receipt access goes by `use_subjects` at the time of each use. A self-claim is shown to the owner,
  and a disputed claim goes to a person (7.4, 9.2). In step 1 no one but the owner can write, so no one can claim.
- **S5. Applied.** 6.5 defines each refusal code's condition and the candidate set. Citations are one per (layer,
  action). U28 and F1 test them.
- **S6. Applied.** A route decision covers at most 32 memories and an imprint batch at most 512 objects, and a new
  `BOUND` code refuses anything larger (6.4). Imprint receipts hold a count and a digest (9.1). The evaluator
  pre-filters records (6.5). A 2-second rebuild target on the Pi 5 is tested by U24.
- **S7. Applied.** Lane notes are written as pending, then settled (5.3). Allows read a pending interval as neither
  lane and denies as both. The sweep settles pending notes after a crash. An object with no notes matches no
  lane-limited allow and every lane-limited deny. Tested by U25.
- **S8. Applied.** 12.3 step 4 states the 30-day loss of agent shares at home, and section 19 asks Andy.
- **S9. Applied.** 7.7: the ledger generates a proposal's words from its body, and the `words` column is gone.
  `sign` prints the full change.
- **S10. Applied.** The overclaim is removed from section 1. Section 14, step 3, names the question, and section 19
  repeats it.
- **S11. Applied.** Both departures from principle 5 are in section 19, and 9.4 and section 14 point to it.
- **S12. Applied.** 4.1: the CLI takes full ids or unique prefixes and refuses an ambiguous prefix. Tested by U26.
- **S13. Applied.** 7.2 says the give-up is new and describes what `_may_revoke` actually allows.
- **S14. Applied.** 12.1: under `enforce`, `share` writes no record. It places a copy only under an existing allow.
  Records come only from the CLI and from `permit`, which takes every field.
- **S15. Applied.** Section 8 uses the Alexandrov topology. The parents' down-sets overlap at J, and the claim is
  only compatibility at J. It says the parents are not a cover.
- **S16. Applied.** 9.1: every receipt write runs in `BEGIN IMMEDIATE`, and the fold keeps a `uses_anchor` row.
  Tested by U27.

### Nits

- **Applied as written:** N1 (43 layers, 6.4 and section 15), N2 (A1 to A5 now quote Andy exactly), N3 (`:227-239`),
  N4 ("Trail spec revision 3 said"), N5 (the `permission` string in `response["neighbors"]["delivered"]`, short names,
  truncation), N6, N7 (the TypeScript kit's canonicalization, sorting by UTF-16 code units), N8 (every deny is
  person-backed), N9 (`own(J) \ ⋃ s_i`, and reruns after registry changes), N10 (retired sub-places, retiring a
  person), N11, N12 (a change counter kept by triggers), N13 (all four points), N15, N16 and N17.
- **N14, applied in another form.** There is no separate `migration` backing. With one collection and one allow per
  legacy audience, Andy can end all of an audience's migrated shares by revoking one record. `migrate` also writes
  the full list of rows to a file before he confirms.

### Applied in another form, or corrected

- **MF10.** Config holds no gate at all, rather than one that can only be asked to raise. That leaves less to fail
  open.
- **MF12.** The check is exact only on realizable points with no lane history. It does not only over-report.
- **S1.** The `remember` guard does not read both receipt stores. It reads `permission-uses.db`, which the daemon
  writes for every reader. That catches deliveries through both `neighbors.py` and the context runtime.
- **N14.** As above.

### For Rio Grande

- The imprints spec cites this spec by line ("its 6.4, lines 405-411" and "its lines 866-871"). Those lines moved.
  6.4's table and section 14's step 2 are where they were, by section. The imprints spec's step 1 checks should
  also note `NO_LAYER` for unregistered stores (P32) and P25 for imprint stores.
- Trail spec revision 4 already shows summaries only with `inject_context`. Its route answers must name at most 32
  memories (6.4).

Not checked: no engram tests were run. This is a spec revision, and no code changed.

## Re-check (revision 2 after the interface pass), 2026-10-25

Reviewer: a second fresh agent on the Pi. I took no part in writing, reviewing, revising or reconciling any of the
three specs. I read the vision, this spec as it stands (revision 2 plus the uncommitted interface pass, which `git
diff` shows touching 4.1, 6.4, 9.1, 11, 14, 15, 17 and 19), the first review and its response, the interface table
(`docs/superpowers/reviews/2026-10-25-city-rail-interfaces.md`), and the parts of the imprint spec (I) and trail spec
(T) that the table cites. I edited no spec. Spec citations are by section, with a spec line where it helps. Code is
cited by file and line, read today.

VERDICT: APPROVE WITH CHANGES

All fourteen first-review must-fixes are resolved. One new must-fix remains, RMF1: an interface disagreement with
the imprint spec about how a `route` use is counted and bounded. Approval holds once RMF1 is applied. Apply the RS
items in the same pass. None of the items below decides the open question about memories that mention other people.

### The first review's must-fixes

- **MF1. Resolved.** P27, 7.1 (row "Revoke, shorten or narrow a deny"), 7.2 ("Which records the ops touch"), L3 ("None
  of these ops may touch a deny"), L4 with `Sig⁻_π`, PT2, and use 9. In a consent layer an agent's ops reach allows
  and memberships only.
- **MF2. Resolved.** 5.3 rule 4 checks every chain record by selector and by validity interval. L3 and L4 rest on it.
  PT6 draws random intervals.
- **MF3. Resolved.** P26, 4.2 ("Roots stay roots"), 4.3, the 4.4 row, PT4, U2. I re-derived 4.3's argument: for a
  non-root X, a new parent adds a set to the intersection, and every place below takes its `dom` by monotone unions
  and intersections, so `dom` only shrinks.
- **MF4. Resolved.** 6.5 steps 5 to 7 (effective end, `until`, horizon), L8, 12.2's cache, 10, the anti-goal, U19,
  PT12. I checked uses 1, 7, 9 and 11 of section 13 by hand: the horizons come out as stated (2027-01-31, 2026-11-30,
  2026-12-01).
- **MF5. Resolved, all six parts.** P3 and 5.2 (`place:Z` needs `Z ∈ dom(P)` and `Z ∈ dom(act(a))`; `self` and groups
  only at places the home dominates), 4.4 (the principal), 7.6 (the words), L5, P31 with its unique index (5.5), and
  the example's `ph-coordinator` acting for clinic-3. Uses 3 and 4 still refuse.
- **MF6. Resolved.** P25, 7.4 "Kept copies", the `copies` table, `stores.imprint_of`, PT7, U17. See RS5 for a gap
  in the new rule.
- **MF7. Resolved.** P32, 6.3 item 1, 6.5 step 1, 12.2, U21.
- **MF8. Resolved.** 6.4's `need(route)`, L6, U22, and T 8 ("Summaries across a boundary need `read` and
  `inject_context`").
- **MF9. Resolved.** 7.6: the yes is `meta.owner`'s, no command names an actor, every CLI write needs the yes, one
  table of widening acts, none of them through MCP tools, U18. I found no widening act missing from the table.
- **MF10. Resolved.** 12.3: the gate is in the ledger, config can't set it, a raised gate fails closed, U16. See RS6
  for one path the effective-gate rule leaves open.
- **MF11. Resolved.** P29 and 12.1's mapping table, E1's hand-written legacy layers (13), U23. See RS1: the chosen
  mapping needs one more daemon rule to hold.
- **MF12. Resolved.** Section 8 expands collections into members, leaving 10 dimensions (a box difference is then at
  most 10 boxes), and states what the check can miss. PT11 carries the review's fixture.
- **MF13. Resolved.** 12.3 step 2: one collection and one allow per legacy audience, each source checked by
  `content_digest`, unmatched rows listed and refused under `enforce`. `legacy-group-<g>` fits the 80-character name
  (13 + 64 = 77). U13.
- **MF14. Resolved.** P28 and 5.4's two shapes, P6 corrected, 5.2's statement that lanes and stores are set at write
  time, U3.

### Claims about code I checked and found true

- Lane derivation at write time (`engram/server.py:1802-1822`; `engram/config.py:74`). `set_episode_lanes` is the only
  writer of a lane after creation (`engram/storage.py:598-610`, the `UPDATE` at `:606`); its one caller is compression
  review (`engram/compress.py:508-510`). No code updates a semantic's lane.
- The store fallback (`engram/server.py:1302-1310`; `engram/config.py:388-409`) and `source_instance` as a name
  (`engram/server.py:1976`). The `share` tool and its arguments (`engram/server.py:1949-1980`, `:1951-1956`). The
  neighbors seam (`engram/server.py:2610-2618`; `engram/neighbors.py:170-171`, `:195`).
- Copies are `personal` (`engram/sharing.py:147-159`; `engram/storage.py:562`, `:1084`). `unshare` deletes at
  `engram/sharing.py:195-203`. `validate_audience` (`:41-46`) and the invalid-row checks (`:57-65`). The unique share
  index (`engram/migrations/027_shared_memories.sql:14-15`). Migration 028 is the last, so 029 is free.
- The daemon: the decider's clock (`engram/lighthouse_daemon.py:309-311`), the 0600 socket (`:476`), audiences
  (`:156-170`), `_shared_audiences` (`:173-201`), the eligibility filter (`:227-239`), read items (`:411-440`), one
  policy and sidecar per publisher (`:506-518`), the sidecar schema (`:57-62`).
- The receivers: `engram/neighbors.py:82`, `:120`, `:132-143`; the client's exact key check
  (`engram/lighthouse_client.py:315`); the context runtime (`engram/context_lighthouse.py:1-5`, `:16`, `:28-30`,
  `:84`, `:94-104`, `:113-117`, `:166-170`; `engram/context_cli.py:90-91`).
- ConnectionPolicy scoring and the deny-wins tie (`engram/lighthouse_policy.py:78-111`, `:146-156`). I re-scored 6.2's
  counterexample: before narrowing, both rules score 3 and deny wins; after, A scores 4 and allows.
- `canonical_json` and its UTF-16 key order (`engram/lighthouse_protocol.py:78`, `:114-121`), `artifact_digest`
  (`:148-159`), recall frames fix `self` (`:232`). The policy generator (`engram/policy_gen.py:47-54`, `:68-88`, the
  purpose at `:80`, `:97-101`). `effective_id` (`engram/store_identity.py:113-116`). Genome sync
  (`engram/federation.py:155`), `SignalBus` (`:17-105`), `process_inbox` (`:211`). The export
  (`engram/lighthouse_export.py:89-128`, `:299-342`). `meta` (`engram/migrations/001_initial.sql:8`).
- Station code: `short_id` (`peer/superyak_peer/grants.py:32-34`), the defaults (`:54-58`), the chain walk
  (`:72-122`), `_may_revoke` (`:284-287`); `RECORD_KEYS`, `sign_record`, `verify_record`
  (`peer/superyak_peer/identity.py:76-83`, `:147`, `:189-199`); narrowing revisions and public layers
  (`peer/superyak_peer/layers.py:143-166`, `:191-194`); space kinds (`peer/superyak_peer/spaces.py:19-22`).
- Other specs: spec A's D7 (its line 36), "a session keeps whatever it has already read" (its line 357), the direct
  confirmation view (its line 472); the layered lighthouse's lines 1-11 and its "proxy" sentence (lines 9-10).
- Arithmetic. Two of 256 records share a 4-hex short form with probability 0.392. Even odds of a repeat come at 301
  receipts with 4 hex and 77,163 with 8 (4.1). 8 + 16 + 16 + 2 + 1 = 43 (6.4, 15).
- Mathematics. Section 8's sheaf is right: on the Alexandrov topology of down-sets, U ↦ 𝒫(uses at places in U) with
  restriction by intersection is a sheaf of sets, and the `s_i ∩ own(J)` agree for all i and k exactly when Δ(J) = ∅.
  Use 5's Δ = {read} × program-operations holds. L8 holds: at fixed σ, every time-dependent term of 5.3 and 5.5 is a
  horizon term.

### Must-fix

**RMF1. The trail evaluation's `route` use breaks 6.4's per-edge rule and its bound of 32.**
Where: spec 6.4 "Bounds" (lines 524-537) and 9.1 "A route" (line 933); I 8 "The decision" and "A finite check"; I 12
(the aggregate row for roads and trails); T 7 steps 3 and 4, and T 7 step 10 ("trails of at most 512 touches").
Interface rows 7, 8 and 29.

- **Why.** 6.4 says a `route` use is one road or trail used as one edge, decided per object, with its own receipt.
  A trail of more than 32 touches "can't be a `route` object", and "the use is allowed only when every one of its
  decisions is". The interface pass wrote that rule for answers that reach an agent, and T 8 fits it. But the first
  `route` use the vision plans is the trail evaluation on an imprint ("How the work runs", step 3). I 8's
  `Need(trail-evaluation)` holds `route` on every road or trail derived from the imprint, decided once "by kind",
  and I 12 writes one row for all of them. T 7 runs A* over those trails, up to 10,000 expansions per search, and T 7
  step 10 allows trails of up to 512 touches.
- **Failure.** A builder builds the permissions core first, as the vision orders. Its `decide` refuses any route use
  on a derived trail of 33 touches with `BOUND`, so the whole evaluation is refused. I's check allows the same use.
  The owner's use list then shows an allowed `route` use, imported "in this form" (9.1), that the owner's own
  `engram-permissions explain` refuses. F1 can't pass for both.
- **Fix.** 6.4 says how a `route` use is decided when no answer names or shows anything to an agent and only counts
  leave. Pick one, as Rio Grande's call:
  - (a) a **bulk use**: decided once per (object kind, action, purpose), with `need` over every object in it. The
    32-memory bound applies to uses whose answer names memories, so not here. One receipt per use, with a count, as
    I 12 writes. Say it in 6.4 and 9.1, and add it to U22 and F1. Or
  - (b) **keep the bound**: I 8 decides per road or trail and leaves out any trail over 32 touches, and T 7 routes
    only over trails that fit.
  Either way, add the case to the interface table's row 8, which now has "none" in I's column.

### Should-fix

**RS1. `group:outside-home` is served today by any policy that lists it, so "a lowered gate fails closed" needs a
daemon rule.**
Where: 12.1, the paragraph after the mapping table (lines 1098-1102); P29; U23.

- **Why.** The spec says "today's code never serves an outside-home placement". But `_allowed_audiences` takes every
  value that passes `validate_audience` (`engram/lighthouse_daemon.py:156-170`, `:168`), and `group:outside-home`
  passes `GROUP_RE` (`engram/sharing.py:19`, `:44`; I ran the regex). The policy schema puts no limit on
  `extensions` values (`engram/schemas/lighthouse/connection-policy.schema.json`). Today's `load_groups` also accepts
  a group named `outside-home` (`engram/policy_gen.py:13`, `:29`). And E1 writes policies by hand (13). So a
  hand-written or edited policy that lists the name serves outside-home placements under `off` or `shadow`, where the
  legacy path alone decides.
- **Fix.** The daemon removes `group:outside-home` from a policy's audiences in every effective gate but `enforce`,
  and only then adds it. U23 adds a hand-written policy that lists it under `shadow`.

**RS2. A use has no holding house, but `Req(u)` needs one.**
Where: 6.1 (`u = (a, P, o, x, p, t)`, line 456); 6.3 item 3 (line 492); 6.5's `decide(u, σ)`; 9.1 (`uses.copy`); 4.1.

- **Why.** `Req(u)` reads `anc(H)`, "where H is the place of the house that serves the copy being used". H is not in
  u. The same ref can be held in more than one house: the published house, an imprint (7.4 keeps source refs), a
  kept copy. I 8's ceiling also restricts by "the copy the wrapper names, `imprint:<station peer id>/<imprint_id>`",
  which is not a coordinate of P's 𝒰. The `uses.copy` column exists, but 4.1 gives no grammar for a copy ref.
- **Fix.** Add the holding house to the use: `u = (a, P, o, h, x, p, t)`, with h a copy ref and H its place. Give 4.1
  a grammar for copy refs, including `imprint:<station peer id>/<imprint id>`. F1's fixtures carry h.

**RS3. The imported station receipts are not in 9.1's form, though 9.1 says they are.**
Where: 9.1, the new bullet (lines 936-941), "An imprint writes one receipt per batch" (lines 934-935), "A route
writes one receipt per road or trail" (line 933), and the `cited` bullet; I 12, "In the owner's own use list";
interface row 21.

- **Why.** I 12 writes one `uses` row per action per batch, three for an admission batch. 9.1 writes one receipt per
  batch of an imprint. For roads and trails, I writes one row for all of them, and a `use_subjects` row naming the
  copy, which is not an object. 9.1 writes one receipt per road or trail with its memories. I's `cited` is "the record
  ids". 9.1's `cited` is one record per (layer, action) plus each layer's version, and the station has no ledger
  versions. A `uses --action imprint` count then means different things for local and imported rows.
- **Fix.** Name the imported form exactly in 9.1: rows per action, the aggregate row for derived roads and trails,
  `cited` without layer versions, and `use_subjects` naming the copy (once RS2 defines copy refs). Or have I conform.
  Rio Grande's call.

**RS4. Only `route` on a road or trail needs the memories it names.**
Where: the 6.4 `need` table (lines 508-512); 5.4's road-and-trail shape (lines 377-378).

- **Why.** 5.4 says "a route is usable only between memories the audience may already recall, read or inject by other
  records". The table makes that true for `route` only. `read` of a trail returns its content, which is its touches.
  So `recall`, `read` or `imprint` on a trail can name memory ids the audience may not recall, an existence leak
  (P23). I's filter keeps only log rows whose targets all ship (I 6.2), so imprints are safe today. A later use of a
  trail allow would not be.
- **Fix.** For every action on a road or trail, `need` adds `recall` on every memory it names, and `read` and
  `inject_context` on every memory whose content it shows. I needs no change.

**RS5. A kept copy's subjects are fixed when it is made.**
Where: 7.4 "Kept copies" (lines 756-770); P25; PT7.

- **Why.** The copy gets the source's subjects "in the same act". A co-subject recorded on the source later, such as
  Jenn on m3, never reaches a copy made before. Adding a subject "only narrows" (L1), and a person expects it to
  narrow every copy. Here the copy keeps moving without her yes.
- **Fix.** On one ledger, a copy's subjects are its own plus its source's at decision time, read through `copies`,
  with a bounded depth and the bound of 8. Say that a copy held on another ledger, such as an imprint at a station,
  learns of later subjects only in step 2, and that the owner can withdraw meanwhile.

**RS6. The effective-gate rule reads `off` when the published house is new.**
Where: 12.3, the effective gate (lines 1150-1165); U16.

- **Why.** Rule 1 gives `off` when there is no ledger and the published house has no `permissions_ledger_id`. The spec
  doesn't say what a gate raise does when no published house exists yet, or what happens when the house is made
  again after a raise. In both cases a ledger deleted by mistake reads as `off`, and `share` returns to "as today".
  The daemon also serves a list of publishers (`engram/lighthouse_daemon.py:506-518`), and the rule names one house.
- **Fix.** A raise refuses without a published house. A house created while a ledger exists gets its id at creation.
  Name which houses carry the id. U16 covers both.

**RS7. Refusal codes for a candidate that matched through a grant-backed membership.**
Where: 6.5, the code table and the candidate (lines 574-586); use 10; U28; F1.

- **Why.** After G1 is revoked (use 10), R1′ matches m4 only through G1's membership. With "every grant's validity
  ignored", R1′ is a candidate. `GRANT_INVALID` asks whether "some candidate's grant chain is invalid". R1′ is
  person-backed and has no chain of its own, so one reader gives `GRANT_INVALID` and another `NO_ALLOW`. F1 needs one
  answer.
- **Fix.** Say whether a candidate's chains include those of the memberships it matched through, and give use 10's
  code.

**RS8. The `remember` guard's limits are not all stated.**
Where: 10, "Keeping it is an imprint" (lines 1016-1021); 15.

- **Why.** The guard reads receipts from the last 24 hours, at most 200. After that a verbatim `remember` passes,
  and the kept memory carries no source subjects. That is MF6's failure, by time. The guard also reads this machine's
  receipts only, so it can't see deliveries decided elsewhere from step 2 on. In step 1 every real receiver is the
  owner's own, so the harm is latent.
- **Fix.** State both as known limits beside "copies, not paraphrases", and name the step 2 need.

### Nits

- **RN1.** Stale revision numbers. The header (line 20), 6.4 (line 515), 11 (line 1041) and 14 step 4 (line 1368) say
  "trail spec revision 4". The trail spec is now revision 5.
- **RN2.** 14 step 2 and I 8 drop "the ledger-only fields". 5.1 should name them: `created_seq`, `revoked`,
  `revoked_by`, `revoke_reason`, `revoked_seq`.
- **RN3.** `until` (P30) is not a lower bound when a legacy layer ends sooner, since policy rules carry
  `validUntil`. Say that `until` and the horizon cover ledger layers only, and that the annotation shows that `until`.
- **RN4.** 5.3 reads lanes "never from the published copy". I 8 reads an imprint's lanes from the imprint, fixed at
  the build, so a re-lane at home after the yes doesn't reach it. Say how a copy held away from its source's ledger
  reads lanes.
- **RN5.** The P29 table says "all `group:g`". Say that an allow naming two groups maps to `group:outside-home`, which
  fails closed under `off` and `shadow`.
- **RN6.** `migrate` should register the published house as a store whose place is the owner's home. Use 1 assumes
  that holding place, and an unregistered house makes `anc(H)` unknown, which refuses everything.
- **RN7.** For Rio Grande, about T. T 6.6 still says "The permissions spec writes short ids with 4 (its section 4.1)".
  P 4.1 now shows receipts with 8 hex and keeps 4 for records, as T 11 already says.
- **RN8.** Section 19 could say plainly that this spec's default for an unrecorded mention, which moves on the
  owner's yes alone, is weaker than I's D27 confirmation box for the same kind of yes. That is a fact for Andy's
  answer, not a decision.

### The interface table, row by row, from this spec's side

- **Agree:** rows 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 27, 28, 30, 31
  and 32. I checked r_M and r_T against 5.1, 5.2 and 5.4: the fields, sorted lists, the collection grammar
  (`imprint-` plus a UUID is 44 characters), the finite `stores` list, purposes in the group grammar, and an end
  within 366 days. In row 6, I's `Req` comes out as P's: the owner's home and the operator's home, counted once.
- **Disagree:** row 8, with rows 7 and 29 (RMF1); row 21 (RS3).
- **Underspecified in this spec:** row 6's copy (RS2), and row 1's "ledger-only fields" (RN2). Row 22 agrees, but T's
  wording is stale (RN7).

### Still open with Andy (unchanged)

The license; one permission an agent may set on its own; what the county sets; pseudonyms; whether the terminal yes
is enough in step 1; agent shares at home under `enforce`; the two departures from principle 5; who decides in the
county steps; and memories that mention other people. On the last, this spec's default stands and is listed (19):
a recorded co-subject must say yes, and a name detector may only add co-subjects. Nothing here changes it.

Not checked: I ran no engram tests (the worktree has no `.venv`). I ran the group regex and the birthday arithmetic
with the system Python. This is a review of specs, and no code changed.

## Re-check response (revision 3), 2026-10-25

The reviser applied the must-fix, all eight should-fix items and all eight nits, and declined none. RN7 is a note
about the trail spec, which this pass may not edit, so it is recorded below for Rio Grande. The spec is now revision
3. It keeps every section number. New decisions are P33 (bulk uses), P34 (the copy in a use) and P35 (every action
on a road or trail needs its memories). P21, P25, P29 and P30 are restated. Every decision not quoted from Andy is
marked Rio Grande's call. The imprints and trail specs were not edited. The interface table was updated where an
interface changed (rows 1, 6, 7, 8, 18, 21, 25 and 29). Each of those rows says so under "Re-check pass".

### Checked again while revising

- **RS1's claim holds.** `_allowed_audiences` returns every value that passes `validate_audience`
  (`engram/lighthouse_daemon.py:156-170`, the return at `:168`). `GROUP_RE` (`engram/sharing.py:19`, used at `:44`)
  matches `group:outside-home`; I ran it with the system Python. The ConnectionPolicy schema's `extensions` takes any
  JSON value under a namespaced key (`engram/schemas/lighthouse/connection-policy.schema.json`). `load_groups` accepts
  any name matching `_NAME` (`engram/policy_gen.py:13`, `:29`). No engram code or test names `outside-home` today
  (grep over `*.py`), so the new daemon rule changes no existing test.
- **RS6's facts.** `_published_house_storage` opens `instances/lighthouse/graph.db` and never creates it
  (`engram/server.py:1934-1946`). The daemon serves `instances/<name>/graph.db` for each configured publisher
  (`engram/lighthouse_daemon.py:506-518`). A new store gets its `instance_id` inside migration 028's transaction
  (`engram/storage.py:222-230`), which is the precedent for migration 029 marking a new house.
- **RN3.** A ConnectionPolicy rule is active only between its `validFrom` and `validUntil`
  (`engram/lighthouse_policy.py:138-143`).
- **RS2.** An imprint's `instance_id` is its `imprint_id` (imprints spec section 11, `stamp_imprint`). So
  `imprint:<station peer id>/<imprint id>` names one store, and a later ledger can find its `stores` row by that id.
- **RMF1 and RS3.** I re-read imprints spec section 8 ("The decision", "A finite check") and section 12 ("In the
  owner's own use list"), and trail spec section 7 (steps 4, 7 and 10) and section 8. The re-check describes them
  correctly.

### Must-fix

- **RMF1. Applied, option (a), Rio Grande's call.** 6.4 defines a **bulk use** `U = (a, P, O, h, x, p, t)` over a
  finite set of objects in one copy (P33). Its `need` is the union of the per-object needs. It is allowed exactly when
  every per-object use would be, with only the bound of 32 named memories waived. Its refusal is the first failing
  object's code, layer and action, and names no object. `cited` holds every distinct record per (layer, action);
  `until` and `horizon` are the earliest across O. Only a use whose answer names no object and shows no content to any
  agent may be bulk. Its size is at most 512 objects when the receipt names them (an imprint batch), or 100,000 when
  they are derived and never named. The bound of 32 now applies to answer uses only. 6.4 says how the imprints spec's
  `Need(trail-evaluation)` and `Need(admission)` are bulk uses, so this spec's `decide` and `explain` agree with that
  spec's check. 9.1 gives the receipts, 15 the bound, and U22 and F1 the tests. Why (a) over (b): the bound of 32 limits
  what an answer names to an agent, and the evaluation names nothing. Option (b) would also have required changes to
  both other specs, and dropped trails of 33 to 512 touches from the first evaluation. Interface row 8 now has I 8 and
  12 in I's column; rows 7 and 29 are updated too.

### Should-fix

- **RS1. Applied.** 12.1 now says revision 2's claim was wrong, with the citations above. The daemon removes
  `group:outside-home` from every policy's audiences under every gate, with no ledger too, and adds it back only
  under `enforce` (P29). `share` refuses the name as an argument. The `off` mode notes the exception (12.3). U23 adds a
  hand-written policy that lists the name, under `shadow` and `off`.
- **RS2. Applied.** A use is `u = (a, P, o, h, x, p, t)` (6.1, P34). 4.1 gives copy refs: `store:<instance_id>`, and
  `imprint:<station peer id>/<imprint id>`. 6.1 defines H as h's place, and 6.3 item 3 refuses an unregistered `store:`
  house with `NO_LAYER`. The same ref in two houses is two uses. The imprints spec's ceiling by copy is now a subset of
  𝒰. No selector names h in this revision; section 8 says why h is not a box dimension. F1's fixtures carry h. 12.2 and
  the worked example name h. Interface rows 6 and 25.
- **RS3. Applied, by naming the form in 9.1** (Rio Grande's call). 9.1 lists the imported form's four differences
  from a local receipt: one row per action; memories by batch of 512 with per-ref `use_subjects`; roads and trails as
  one counted row with `use_subjects` (owner, h); `cited` without layer versions, with the station's peer id and the
  receipt's chain position. `copy` is the imprint's ref on every row. The use list marks imported rows and counts them
  apart (9.3). The imprints spec needs no change. Interface row 21.
- **RS4. Applied.** 6.4: for every action on a road or trail, `need` adds `recall` on each memory it names, and
  `read` and `inject_context` on each memory whose content it shows (P35). 5.4's road shape, L6, 12.1's trail row and
  U22 follow. The imprints spec already meets it (its 6.2). Interface row 7.
- **RS5. Applied.** 7.4: on one ledger, a copy's subjects at a decision include its source's at that decision, read
  through `copies` up to 4 links. A deeper chain is refused when made. More than 8 subjects in the union refuses with
  `BOUND`; adding a subject to a source is never refused because of its copies. A copy on another ledger learns of later
  subjects only in step 2, and the owner can withdraw meanwhile. 6.3 item 1, P25, L6, section 14 step 2, use 12, PT7,
  U17 and the constants follow. Interface row 18.
- **RS6. Applied.** 12.3 names the houses: every store at `<root>/.engram/graph.db` or
  `<root>/.engram/instances/<name>/graph.db`, which covers the published house and every daemon publisher. The raise
  marks all of them and refuses without a published house. Migration 029 marks a house created while a raised ledger
  exists, or writes `unreadable` if the ledger can't be read. `off` now needs no ledger and no marked house anywhere; a
  served house without the id under a raised ledger reads closed. A reader reads at most 64 houses for the `off` rule
  (a new constant). U16 covers each case.
- **RS7. Applied.** 6.5: a candidate's grant chains include those of the grant-backed memberships it matched through.
  Use 10's read of m4 is `GRANT_INVALID` at `place:home/andy`, action `recall`, until G1's expiry on 2026-11-30, and
  `EXPIRED` after, since the table checks `EXPIRED` first. A removed membership counts for no candidate. U28 tests it.
- **RS8. Applied.** Section 10 states both limits: the 24-hour, 200-receipt window, after which a verbatim `remember`
  passes with no source subjects, and the guard seeing only this machine's receipts. Both are latent in step 1. Step 2
  needs the receiving server to record each delivered item's digest and receipt from the delivery itself, kept at
  least until the decision's `until`, or 400 days when there is none.

### Nits

- **RN1. Applied.** The header, 6.4, 11 and section 14's step 4 now say the trail spec is revision 5.
- **RN2. Applied.** 5.1 names the five ledger-only fields, and section 14 step 2 points there. Interface row 1.
- **RN3. Applied.** 6.5 step 6, P30 and section 11 say `until` and the horizon cover ledger layers only, and that a
  legacy rule may end a use sooner, taking effect at the next request.
- **RN4. Applied.** 5.3 says a copy held away from its source's ledger reads lanes from the copy, fixed at the yes. That
  widens nothing, because outside-home allows reach memories only by ids and collections (P28). Later lane-limited
  denies reach it in step 2.
- **RN5. Applied.** The P29 table now says "exactly one group". An allow naming two groups maps to
  `group:outside-home` and fails closed under `off` and `shadow`. U23 covers it.
- **RN6. Applied.** `migrate` registers every house, the published house among them, and each source store, with
  Andy's home as their place (12.3 step 2). The example says so, and U13 checks it.
- **RN7. Recorded for Rio Grande, below.** The fix is in the trail spec, which this pass may not edit.
- **RN8. Applied.** Section 19 states the fact for Andy: this spec's default moves an unrecorded mention on the
  owner's yes alone, while the imprints spec also asks for its D27 confirmation. The question stays open.

### Declined

None.

### For Rio Grande

- **RN7.** The trail spec's 6.6 (its lines 793-794) still says "The permissions spec writes short ids with 4 (its
  section 4.1)". This spec's 4.1 shows a receipt with 8 hex and keeps 4 for records, grants and proposals. The trail
  spec's reviser should correct the sentence. Interface row 22's rule is already right.
- **Per-copy rules in step 2.** No selector names h yet. In step 1 the imprints spec's ceiling and its ship-requested
  refusal of one copy (its D17) live in code at the station, which has no ledger. When a station gets a ledger, it
  needs records that can name a copy. Adding a selector dimension would change the key set of r_M and r_T, so it is
  left for step 2, across all three specs.
- **Bulk bound and I 12.** The imprints spec's one aggregate row for roads and trails fits a counted bulk use while
  they number at most 100,000. An imprint holds at most 100,000 memories (its D36), but the number of derived trails
  is bounded by sessions, not memories. If it can pass 100,000, I 12 would need one row per 100,000.
- **Parallel work.** During this pass the trail spec's review file gained new text from another team. I did not read
  it for interface effects. The interface rows I touched are listed above.

### Still open with Andy (unchanged)

The license; one permission an agent may set on its own; what the county sets; pseudonyms; whether the terminal yes
is enough in step 1; agent shares at home under `enforce`; the two departures from principle 5; who decides in the
county steps; and memories that mention other people. On the last, this spec's default is unchanged: a recorded
co-subject must say yes, and a name detector may only add co-subjects. RN8 adds a fact to the question, not an
answer.

Not checked: no engram tests were run, since this is a spec revision and no code changed. I ran the group regex with
the system Python.

## Final check (revision 3), 2026-10-25

Reviewer: a fresh agent on the Pi, making the final check in Andy's place (station law section 3). I took no part in
writing, reviewing, revising or reconciling any of the three specs. I read the vision, the spec as it stands in the
worktree, this file, the interface table, and the parts of the imprints spec (I) and trail spec (T) that RMF1 names. I
edited no spec. Spec citations are by section, with working-copy lines where they help. Code is cited by file and line,
read today.

VERDICT: APPROVE WITH CHANGES

The design of the RMF1 fix is right, and it agrees with I and T. But the spec file in the worktree is cut off after
section 14's first later step. Sections 15 to 19 are gone, and with them the U22, F1 and section 15 parts of RMF1's
fix. That is FMF1, below. Approval holds once the lost part is restored exactly and checked as FMF1 says. Do not merge
the file as it stands. Nothing here decides the open question about memories that mention other people.

### RMF1: partly resolved in the file, fully resolved in the text the reviser wrote

**Present and correct.** P33 (section 3, line 149). In 6.4: "Answer uses name at most 32 memories" with "One use per
edge", "An `imprint` batch" as a bulk use, and "Bulk uses" (need, allowed, refused, the decision, which uses may be
bulk, size, one receipt, how it is computed), with its last paragraph on I's `Need(trail-evaluation)` and
`Need(admission)` (lines 580-640). 6.5's "How it is computed" (lines 702-705). L6 (lines 769-775). 9.1's bulk receipts
and the imported form's item 3 (lines 1068-1104). The header's change list (lines 31-33). Option (a) is marked Rio
Grande's call.

I checked them against the other two specs:

- I 8 "The decision" defines R(I) and both `Need` sets. I 8 "Bulk uses" calls admission and evaluation P's bulk uses,
  with the 32 waived and P's other bounds kept: 100,000 derived objects per counted use, 8 subjects, 43 layers. I 8 "A
  finite check" is P 6.4's grouping shortcut. I 12 "In the owner's own use list" writes the counted row P 9.1 item 3
  names.
- Every memory a trail in R(I) names is in objects(I) (I 8). So a bulk `route` over R(I), whose `need` adds `recall`
  on every named memory, is covered by I's `(recall, trail-evaluation)` term.
- T 4 caps a trail at 512 touches (line 264). T 7's report is "counts and rates only, never content or ids" (step 7,
  line 1062). So the evaluation meets P's test for a bulk use: it names no object and shows no content to any agent.
- T 8 keeps answers that cross a boundary per road, under the 32. Interface row 8's I column now names I 8 and 12.

So P's `decide` and `explain` now give I's verdict on the first evaluation, and F1 can hold for both.

**Missing from the file.** RMF1 asked to "add it to U22 and F1". U22 and F1 are in section 17, which the file no
longer has. Section 15's bound for bulk uses is gone too. Interface row 8 cites "6.4, 9.1, 15, U22, F1"; three of the
five are not in the file. So I can't mark RMF1 resolved until FMF1 is fixed.

### Must-fix

**FMF1. The spec file is cut off after section 14's later step 1.**
Where: the end of the file. It stops at line 1583 with "The imprints spec's transport lands here." and no final
newline. It has lost section 14's later steps 2 to 4, its Non-goals and its Anti-goals, and all of sections 15
(Constants), 16 (Components), 17 (Tests), 18 (Left to the builder) and 19 (Open for Andy). That is about 290 lines.

- **Evidence.** `grep -c '^## 1[5-9]'` on the file gives 0. The committed revision 2 (`git show HEAD:<spec>`) has those
  sections at its lines 1372-1583. The file still cites what it lost: sections 15, 16, 18 and 19 (lines 473, 951, 1129,
  1154, 1185, 1416), and tests U1, U13, U24, PT11, E1 and F1 (lines 521, 620, 640, 705, 1028, 1191, 1327, 1410, 1454).
- **Cause, verified in the reviser's session transcript** (`agent-a2e57399a5dd29943.jsonl` under this session's
  `subagents/workflows/wf_090deadc-568/`). At 02:42:23Z (19:42 PDT), a rewrap script defined a helper whose last line
  was a chain of conditional expressions:
  `return s[:i] + out.lstrip(" ") if False else s[:i] + out[len(indent):] if out.startswith(indent) and indent else ...`.
  With `indent="   "` the branch taken is `s[:i] + out[len(indent):]`, which drops `s[j:]`. Its third call, on later
  step 1, deleted everything after "transport lands here.". The output it printed right after the write ends there.
  Every later edit was above the cut, so no later check noticed.
- **Why it is a must-fix.**
  - RMF1's U22 and F1 parts and section 15's bound are gone (above).
  - **The open question is no longer listed.** Section 19 held "Memories that mention other people", with this spec's
    default and RN8's fact. Each spec must list it (interface row 20). 7.4 still states the default: a memory about
    two people needs both yeses, and a name detector may only add co-subjects. So the default is unchanged, but the
    file no longer says the question is open.
  - **Interfaces are broken.** I 20 (its line 1913) and T 14 (its line 1659) point to this spec's section 19. T cites
    this spec's non-goal for a store's own use (its lines 67 and 878), which was in the lost Non-goals. Interface rows
    3, 8, 22 and 29 cite P 15, row 8 cites U22 and F1, row 20 cites P 19, and row 30 cites P 14's non-goals. None of
    these is in the file.
  - **A builder can't build or test from the file.** The constants every bound on the Pi rests on, the components,
    every test (PT1-PT12, U1-U28, E1, F1), the anti-goals, and the rest of section 19 (the license, the county,
    pseudonyms, the step-1 yes, agent shares at home, the two departures from principle 5, who decides in the county
    steps) are all gone.
  - The header (line 9) and the Re-check response say revision 3 changed 14, 15, 16, 17 and 19. That is untrue of the
    file.
- **Fix.** Restore the lost part. Whether to restore from the rebuilt file below or write it again by hand is Rio
  Grande's call. A rebuilt copy is at
  `/tmp/claude-1000/-home-andy-superyak/48274ab7-ef35-4006-a317-fad27acbcfa1/scratchpad/permissions-by-place-rev3-reconstructed.md`
  (SHA-256 `65bd50be815c4e4409447b76869f44147a4e34c2bf225d46e4daef2ef88625e2`). It is in a session scratchpad under
  `/tmp`, so copy it out before it is cleaned.
  - **How I rebuilt it.** I took the reviser's five reads of the whole spec at the start of its pass (02:28Z, lines
    1 to 1616). Then I replayed every Edit and every Python script of that pass, in order, in the scratchpad. I changed
    one line, the helper's return, to `return s[:i] + (out[len(indent):] if indent and out.startswith(indent) else out)
    + s[j:]`.
  - **Why it can be trusted.** The current file is a byte-for-byte prefix of the rebuilt one (130,597 of 155,388
    characters). Two scripts failed in the replay. One, at 02:37:37Z, failed the same way in the original session. The
    other, at 02:43:46Z, writes only the interface table. The rebuilt tail differs from the committed revision 2 only
    by changes the interface pass and the Re-check response name: later step 4's revision number; section 15's rows
    for answer uses, bulk uses, the `copies` chain, the guard's limits, the 64 houses and the 8-hex receipt; section
    16's rows for `permissions.py`, the ledger, the daemon, `sharing.py` and `server.py`, `storage.py` and migration
    029 (copy refs, bulk `decide`, houses and the gate, `group:outside-home`); PT7, U10, U13, U16, U17, U21, U22,
    U23, U28 and F1; and section 19's question about memories that mention other people, with RN8's fact.
  - **The restore.** Append everything after "lands here." from the rebuilt file, and end the file with a newline. Then
    check that: `grep -c '^## 1[5-9]'` gives 5; the file's first 130,597 characters are unchanged; and every section
    and test the file cites exists.

**What the restore brings back, checked.** Section 15's rows "Memories named per answer use on a road or trail: 32;
bulk uses waive it" and "Objects per bulk use: 512 when its receipt names them, 100,000 when derived and never named"
match 6.4. U22 tests:

- the answer bound, a trail of 33 touches used as one edge, and 5 roads as 5 uses;
- a bulk `route` over 3 trails of 40 touches, allowed with one counted receipt naming no object, and refused with
  `BOUND` as answer uses;
- a failing object's refusal naming no object;
- 100,001 derived objects, or 513 named ones, refused with `BOUND`;
- I's `Need(trail-evaluation)` and `Need(admission)` on a fixture imprint, giving I's verdicts.

F1 carries h on every use and includes bulk uses, the trail evaluation among them. Section 19 lists the question and
decides nothing. That is what RMF1 asked. With the restore, RMF1 is resolved.

### No new must-fix in the rest of revision 3

- **A requester can't ask for a bulk use.** The daemon decides `recall` per placement and `read` per item (12.2). Only
  the spec that runs a use may call it bulk, a showing to an agent is per object under the 32, and a `remember` is
  never bulk (6.4). `need(U)` is the union of the per-object needs, so waiving the 32 changes no verdict (L6), and a
  bulk refusal names no object (P23).
- 100,000, the bulk bound for derived objects, is the collection bound (5.4). 512, the bound for named ones, is the
  `memories` list bound (5.2).
- **Code claims checked today, all true.** `engram/neighbors.py:82` (`recall` before asking), `:120` (all three before
  reading), `:138` (all three again at delivery). `engram/lighthouse_policy.py:138-143` (a rule is active only between
  `validFrom` and `validUntil`, both ends included). `engram/lighthouse_daemon.py:156-170` (`_allowed_audiences`
  returns every audience that validates, at `:168`) and `:309-311` (the decider's clock). `engram/sharing.py:19`
  (`GROUP_RE`), `:41-46` (`validate_audience`), `:147-159` (copies written `personal`), `:195-203` (the deletes).
  `engram/storage.py:222-230` (the instance id inside 028's transaction). `engram/server.py:1934-1946` (the published
  house is never created). `engram/store_identity.py:113-116` (`effective_id`). `peer/superyak_peer/identity.py:76-83`
  (`RECORD_KEYS`) and `:189-199` (`verify_record`).

### Should-fix

**FS1. Which trails the admission's bulk `imprint` covers.**
Where: 6.4, the paragraph before "Bounds" (lines 577-578, "the trails whose log rows it keeps") and the last paragraph
(line 639); interface row 13's note for this spec's next revision.

- **Why.** I 8 defines R(I) as the roads and trails derivable from the package's session ids and log rows. A session
  that wrote two episodes has a trail with no log row (T 2 and 4). The verdicts agree, since r_T covers every road and
  trail of the store. But a builder writing F1's fixture from this spec would count fewer objects in that bulk use,
  and its receipt's `returned` count would differ from I's.
- **Fix.** Say "the roads and trails derivable from its session ids and log rows" in both places, as row 13 asks.

### Nits

- **FN1.** 9.1 calls a named bulk use "an imprint batch of at most 512 objects". 6.4's last paragraph and I 8 also make
  the evaluation's `read` batches named bulk uses. Say "such as an imprint batch".
- **FN2.** 6.5 step 1 refuses with `BOUND` "if o would have more than 8 subjects". For a bulk use, say "any o ∈ O".
- **FN3.** A bulk `decide` over 100,000 derived objects is bounded by count, but no Pi time is given for it, and U24
  measures only the eligible-set rebuild. 6.4 says the evaluator "may" group objects. Saying it does, or adding a slow
  Pi test for `explain` on a bulk use, would keep principle 4 measurable.

### For Rio Grande

- I 12 writes "one row" for all roads and trails, while I 8 and this spec's 9.1 split them into one counted use per
  100,000. I 12 should say so (the Re-check response's "Bulk bound and I 12" asked the same). That is I's to change.
- T 11's line about this spec ("Its `route` decision is per road or trail, at most 32 memories each") is still true of
  answer uses. T could add that its evaluation on an imprint is decided as I's bulk uses. Optional.
- Process, Rio Grande's call: comparing a spec's `## ` headings before and after each pass would have caught FMF1.

### The interface table, from this spec's side

- **Agree in the text present:** rows 7, 8 and 29 in 6.4, and row 21 in 9.1, as checked above.
- **Broken until FMF1 is fixed:** rows 3, 8, 20, 22, 29 and 30. Each cites P 15, U22, F1, P 19 or P 14's non-goals.
- I did not re-check the other rows beyond seeing that they cite sections the file still has.

### Still open with Andy (unchanged)

Memories that mention other people: this spec's default stands in 7.4 (a recorded co-subject must say yes, and a name
detector may only add co-subjects), and the restored section 19 lists the question. Nothing here changes it. Also the
license, one permission an agent may set on its own, what the county sets, pseudonyms, whether the terminal yes is
enough in step 1, agent shares at home under `enforce`, the two departures from principle 5, and who decides in the
county steps.

Not checked: I ran no engram tests, since this is a spec review and no code changed. I ran Python only to rebuild the
spec from the reviser's transcript, in my scratchpad. I committed nothing, pushed nothing and posted nothing.

## Repair after FMF1, 2026-10-25

Rio Grande restored the lost text (section 14 from later step 2 onward, and sections 15 to 19) from the committed
revision 2. So those sections came back as they were before the interface pass and the re-check fixes. This pass
brings sections 14 to 19 up to date with the spec as it now stands. I edited only sections 14 to 19, with targeted
edits. Lines 1 to 1547 (sections 1 to 13) are unchanged. No cross-reference above section 14 was wrong once 15 to 19
were brought up to date, so none was edited.

**How.** I read this file's "Response", "Re-check", "Re-check response" and "Final check", the interface table, and
the whole spec body. The final check's rebuilt copy was still in the scratchpad, with the SHA-256 it records
(`65bd50be…25e2`). Its lines 1 to 1547 equal the current file's. I used its tail only as a list of what the reviser
had written, and checked each item against the body before applying it. Then I compared the body's constants,
components, tests and open items with 15 to 19, and added what was still missing.

### What changed

- **Section 14, step 1.**
  - The CLI list gains `rebuild`, which 5.6 names as a command.
  - The daemon line names each placement's copy h (12.2), the `group:outside-home` rule (12.1), and the effective
    gate over its houses (12.3).
  - `share` refuses `group:outside-home` as an argument.
  - Kept copies read their subjects through `copies` (7.4).
  - Migration 029 marks a house made while a raised ledger exists (12.3).
- **Section 14, later steps.** Step 4 (data classes) points to section 19 for memories that mention other people.
  "Routes on the rail" no longer names a trail spec revision (see "Left as it is" below).
- **Section 14, non-goals.** One added: a selector that names the copy h (6.1, section 8).
- **Section 14, anti-goals.**
  - "Existence leaks": a bulk refusal names no object.
  - New, "A showing decided in bulk": a use decided in bulk must not name an object or show content to an agent
    (P33).
  - "Failing open" adds a house without the ledger's id (P21), and a lowered gate that serves an outside-home
    placement (P29).
- **Section 15.**
  - "Memories per route decision" becomes the answer-use bound of 32, which bulk uses waive (RMF1).
  - "Objects per imprint batch" becomes "Objects per bulk use": 512 named, 100,000 derived. Both are marked fixed to
    match 5.2 and 5.4.
  - New rows: the `copies` chain of 4 links (RS5), the 64 houses for the `off` rule (RS6), the use list's 200 rows
    (9.3), and the receipt short form of `#` and 8 hex (interface row 22).
  - "Subjects per object" counts a kept copy's union with its source's subjects (RS5).
  - The `remember` guard points to its known limits in section 10 (RS8).
- **Section 16.**
  - `permissions.py`: copy-ref grammars, `need` with named memories, `decide` for single and bulk uses, and a
    candidate's grant chains (RS2, RS4, RMF1, RS7).
  - `permission_ledger.py`: the gate over houses, marking houses at the raise, and a copy's subjects through `copies`
    (RS6, RS5).
  - `permission_uses.py`: bulk receipts, and the owner view marking imported station rows and counting them apart
    (RS3). The imported rows are written by the imprints spec's `import-receipts` (its section 15).
  - `permission_cli.py`: `gate` refuses a raise without a published house, and `explain` takes bulk uses.
  - `lighthouse_daemon.py`: each placement's copy h, and the `group:outside-home` strip (RS1).
  - `sharing.py` and `server.py`: refusing the reserved name, and the effective gate over the published house.
  - `storage.py`: 029's step that marks a new house. It sits in the migration loop, as 028's `_assign_instance_id`
    does. Checked today: `engram/storage.py:224` (`created_now`), `:228-230` (each migration runs in `BEGIN IMMEDIATE`,
    and 028 calls `_assign_instance_id` inside it), `:235` (the commit).
  - Migration 029's SQL row says the marking is `Storage`'s step, because it reads the ledger, which is another file.
- **Section 17.**
  - PT7: later subjects reach copies, up to 4 links.
  - U5: the `BOUND` case for a copy's subject union.
  - U8: every receipt carries h; imported rows are marked and counted apart; `--action` and `--object` work on them.
  - U10: 8 hex.
  - U13: houses and source stores registered (RN6).
  - U16: the house cases of 12.3, the 64-house case among them (RS6).
  - U17: a later co-subject reaches a kept copy.
  - U19: a legacy end that comes before `until` (RN3).
  - U21: an unregistered copy h, and one ref held in two houses (RS2).
  - U22: rewritten for P35, answer uses, one use per edge, bulk uses, named bulk receipts, the bulk bounds, and I's
    `Need(trail-evaluation)` and `Need(admission)` (RS4, RMF1).
  - U23: two groups, a hand-written policy, no ledger, and `share` refusing the name (RN5, RS1).
  - U28: use 10's `GRANT_INVALID`, then `EXPIRED` (RS7).
  - E1 and F1 carry h. F1 includes bulk uses, the trail evaluation among them.
- **Section 18.** The property-test generators must reach copy chains and bulk uses.
- **Section 19.** "Memories that mention other people" is listed again, with this spec's default, the imprints
  spec's stricter one, the trail spec's matching item, and RN8's fact. It decides nothing. I checked the D27 box text
  it quotes against the imprints spec's section 8. I 20 and T 14 point here, and that pointer now resolves.

### Checked after editing

- `grep -c '^## 1[5-9]'` gives 5, and every heading from `## 1.` to `## 19.` is present once.
- The file ends with a newline.
- Sections 15 to 17 hold every test the body names (U1, U13, U24, PT11, E1, F1) and every test from PT1 to PT12 and
  U1 to U28.
- The interface rows that cite P 15, U22, F1, P 19 and P 14's non-goals (rows 3, 8, 20, 22, 29 and 30) now cite text
  the file has.
- With this repair, RMF1 is resolved as the final check described, and FMF1 is fixed.

### Left as it is

- **FS1, FN1, FN2 and FN3** of the final check fall in sections 6.4, 6.5 and 9.1. None is a broken cross-reference,
  so this pass did not apply them. They remain for the next revision. FN3's Pi time for a bulk `explain` would also
  need a new calibration constant in section 15.
- **The trail spec's revision.** The trail spec is now revision 6 (its status line). The body calls it revision 5 in
  the header, 6.4 and 11. Those tags were right when written, and I did not check whether revision 6 changes what
  those sentences say. 14's "Routes on the rail" now names no revision, so it can't go stale.
- **Who warns about `[permissions]` in `config.toml`.** 12.3 says the section is ignored with a warning, and 16 says
  `engram/config.py` gains nothing. No component is named for the warning. That is how revision 2 had it. It is left
  to the next revision, or to the builder.
- **For Rio Grande, about T.** T 7 (its line 914) cites "this narrows mistakes, not malice" as this spec's section
  14. The words are in 7.6's known limits, which 14 points to. T's reviser may cite 7.6 instead. Optional.

### Still open with Andy (unchanged)

The license; one permission an agent may set on its own; what the county sets; pseudonyms; whether the terminal yes
is enough in step 1; agent shares at home under `enforce`; the two departures from principle 5; who decides in the
county steps; and memories that mention other people. On the last, this spec's default is unchanged (7.4), and
section 19 lists the question again.

Not checked: I ran no engram tests, since this is a spec repair and no code changed. I committed nothing, pushed
nothing and posted nothing.

## Final check after repair, 2026-10-25

Reviewer: a fresh agent on the Pi, making the final check in Andy's place (station law section 3). I took no part in
writing, reviewing, fixing or repairing this spec or the other two. I read the vision, the whole spec as it stands,
this file, the interface table, and the parts of the imprints spec (I) and trail spec (T) that cite this spec or that
the table names. I edited no spec. Spec lines are the working copy's. I and T are cited by section, since I was being
edited while I read it (below). Code is cited by file and line, read today.

VERDICT: APPROVE

FMF1 is fixed and RMF1 is resolved. Sections 14 to 19 agree with the body. Every interface row holds from this spec's
side. I found no new must-fix. Three should-fix items and five nits remain. None blocks the plan, but AS1 should be
fixed before E1 is written. Nothing here decides whether imprints may include memories that mention other people.

### FMF1: fixed

- Every heading from `## 1.` to `## 19.` is present, once each (grep, one count per heading). The file ends with a
  newline. It has 1,898 lines.
- Lines 1 to 1,556 are byte-identical to the cut file (`permissions-truncated.md` in the session scratchpad). The
  first difference is at line 1,557, in section 14's step 1, which the repair edited on purpose and recorded. I diffed
  the cut file's section 14 against the current one: every changed line adds text, and none of the cut text is lost.
  So the final check's literal test, "the file's first 130,597 characters are unchanged", fails, but only because of
  those recorded edits. The first 128,270 characters are unchanged.
- The rebuilt copy is still in the scratchpad, with the SHA-256 the final check records (`65bd50be…25e2`). Its lines 1
  to 1,547 equal the current file's. I diffed its tail against the repaired tail. Every line the reviser wrote is in
  the repaired tail, the same or extended. So the restore from revision 2 lost nothing of revision 3.
- Every test the body cites is defined: PT1 to PT12, U1 to U28, E1 and F1, 42 in all. Every section the body cites
  exists.

### RMF1: resolved

- **In the file.** P33. In 6.4: answer uses, one use per edge, bulk uses, and the last paragraph on I's `Need` sets.
  6.5's "How it is computed". L6. 9.1's bulk receipts and the imported form. Section 15's rows "Memories named per
  answer use on a road or trail: 32 … bulk uses waive it" and "Objects per bulk use: 512 … 100,000". U22's bulk cases:
  - a bulk `route` over 3 trails of 40 touches;
  - a named bulk receipt;
  - a failing object whose refusal names no object;
  - 100,001 derived or 513 named objects refused with `BOUND`;
  - I's `Need(trail-evaluation)` and `Need(admission)` giving I's verdicts.

  F1 carries h on every use and includes bulk uses.
- **Against the others.** Interface row 8's P column (6.4, 9.1, 15, U22, F1) now cites text the file has. I 8 "Bulk
  uses" calls admission and evaluation this spec's bulk uses, with the 32 waived and the other bounds kept. T 4 caps a
  trail at 512 touches. T 8 keeps cross-boundary answers per road, under the 32. So this spec's `decide` and `explain`
  agree with I's check on the first evaluation.

### Sections 14 to 19 against the body

I checked each line of 14 to 19 against the section it rests on.

- **14, step 1** names every command and part the body names: `rebuild` (5.6), `explain` single or bulk (6.4), each
  placement's copy h (12.2), the `group:outside-home` rule (12.1), the effective gate over houses (12.3), `share`
  refusing the name (12.1), subjects through `copies` (7.4), and 029 marking a new house (12.3).
- **14, later steps.** Step 2's notices for later subjects and lane-limited denies match 5.3 and 7.4, and its guard
  need matches 10. Step 3's question matches 9.4 and 6.3. Step 4 points to 19. "One edge per answer use" matches 6.4.
- **Non-goals and anti-goals** match 6.1, 8, 6.4, 9.4, P21, P29 and P33.
- **15.** Every value matches its source:
  - 256 records (5.4); 32, 64 and 512 per selector (5.2); 16 purposes (5.2); 8 subjects (5.4, 7.4); 100,000
    members (5.4); 80 characters (4.1; `legacy-group-` plus a 64-character group is 77).
  - 1,024 places, 4 parents, 8 segments (4.4, 4.2, 4.1); 16 ancestors, and 8 + 16 + 16 + 2 + 1 = 43 (4.2, 6.4).
  - 32 per answer use, 512 and 100,000 per bulk use (6.4); 4 `copies` links (7.4).
  - 366 days (5.4); 3 links and 720 hours (7.2); 16 `replaces` (5.1); 7 days (P11).
  - 4,096 boxes, `64 × (1 + k)`, 64 joint places (8); 256 per sweep (10); 64 cache entries, 20,000 placements, 2 s
    (12.2).
  - 200 receipts and 24 hours for the guard (10); 64 houses (12.3); 400 days (9.1); 200 rows (9.3); 240 and 32
    characters (11); 6 characters (7.6); 4-hex prefixes and 8-hex receipts (4.1).
- **16** names a component for every module in the header and every part of 14's step 1. One exception, carried from
  the repair: the `[permissions]` warning of 12.3 has no component.
- **17's** tests cover the body's rules, revision 3's included.
- **18 and 19** match. Section 19 lists the question about memories that mention other people: this spec's default
  (7.4), I's stricter one, T's matching item, and RN8's fact. It decides nothing. The box text it quotes is word for
  word I 8's ("The owner's check about other people"). I 20 and T 14 point to this spec's 19, which now exists.

### Code claims checked today, all true

- **Sections 14 to 16.**
  - `engram/storage.py:224` (`created_now`), `:228` (each migration in `BEGIN IMMEDIATE`), `:229-230` (028 calls
    `_assign_instance_id` inside it), and `:235` (the commit).
  - `peer/superyak_peer/identity.py:76-83` (`RECORD_KEYS`), `:147` (`sign_record`, a `PeerIdentity` method), and
    `:189-199` (`verify_record`).
  - `engram/pyproject.toml:31` (`[project.scripts]`) and `:40` (`py-modules`).
  - `engram/CLAUDE.md` has no rule that agents never run the person's commands, as 7.6 says (grep for "permission"
    and "never run" finds nothing). No license file is in `engram/` or the repository root, as 19 says.
- **The body, beyond the earlier lists.**
  - `engram/sharing.py:18-20`, `:99-101`, `:147-159`, `:195-203`.
  - `engram/lighthouse_policy.py:1-7`, `:18-27`, `:138-143`; `engram/lighthouse_validation.py:25-34`;
    `engram/lighthouse_receipts.py:1-6`; `engram/lighthouse_receiver_config.py:13`.
  - `engram/storage.py:128-161`, `:562`, `:598-610`, `:1084`.
  - `engram/server.py:1302-1310`, `:1934-1946`, `:1949-1956`, `:1976`, `:2610-2618`.
  - `engram/policy_gen.py:13`, `:29`, `:80`; `engram/config.py:74`, `:388-409`.
  - `engram/federation.py:155` (`sync_genome`, which records `origin_instance_id`); `engram/store_identity.py:113-116`.
  - `engram/lighthouse_daemon.py:156-170`, `:309-311`, `:476`, `:506-518`; `engram/neighbors.py:82`, `:120`, `:138`;
    `engram/lighthouse_client.py:315`; `engram/context_lighthouse.py:28-30`; `engram/lighthouse_protocol.py:232`.

### Must-fix

None.

I looked for wrong code claims, broken mathematics, privacy holes (anything about a person moving without their yes,
an agent widening a permission) and Pi bounds. The meet, the lattice, L1 to L8, the gluing check and the bulk-use rule
hold. A bulk use's `need` is a set union, so a bulk `route` over R(I) adds at most one `recall` per memory of the
imprint, not one per touch: at most 200,000 uses per counted bulk use. Both privacy items below are latent in step 1.

### Should-fix

**AS1. Worked example use 13 says a verbatim `remember` is refused, but the guard's window has passed.**
Where: 13, use 13 (lines 1532-1535); 10, "Known limit: time" (lines 1184-1187); section 15's guard row; E1.

- **Why.** Use 1 delivered m1 on 2026-11-02. The example names no delivery of m1 after use 11, on 2026-12-01. Use 13
  is at 2026-12-15T00:00:00Z. The guard reads only allowed `inject_context` receipts from the last 24 hours (10), so it
  finds none. A verbatim `remember` then passes, and the kept memory carries no source subjects. Section 10 states this
  limit (the re-check's RS8, revision 3). Use 13 was written before it and says the opposite.
- **Failure.** E1 runs "Section 13, every step". A builder writes "remember refused" for use 13, and an implementation
  that follows sections 10 and 15 fails it. And Andy, reading the example about his medical history, is told of a
  protection that doesn't hold after 24 hours.
- **Fix.** Use 13 says what the spec does: within 24 hours of a delivery, the verbatim `remember` is refused; on
  2026-12-15 it passes, which is section 10's known limit, latent in step 1 because `ph-coordinator` is a fixture. E1
  checks both. No rule changes.

**AS2. A refusal's layer can name a co-subject, and 9.2 doesn't keep it from the agent or from a place's stewards.**
Where: 9.2, rows "A place's stewards" and "The agents in a place" (lines 1120-1121); 9.1, `refusal` (line 1103); 6.4,
a bulk refusal (line 617); 12.2 ("no reason beyond 'not allowed'"); use 2.

- **Why.** Use 2 is refused with `NO_ALLOW` at `place:home/jenn`, and the receipt holds that layer. 9.2 lets the
  agents in a place read "their own receipts: … refused reads of ids they named", and doesn't say which fields. So
  `ph-coordinator` could learn that m3 is about Jenn, without Jenn's yes. Use 2 and 12.2 say the agent gets no reason,
  so the intent is clear, but 9.2 doesn't carry it. A steward's view shows the "outcome". A home named in a refusal
  names a subject, while 9.2 shows stewards subjects only as pseudonyms.
- **Latent.** In step 1 no county agent reads receipts. `permissions(focus="uses")` returns the owner's list to the
  owner's agents only (9.3), and the county agents are E1's fixtures. Steps 2 and 3 build these views from 9.2.
- **Fix.** 9.2: an agent sees its own refused read as "not allowed", with no code, layer or action. A steward sees a
  refusal's layer when it is a place, and a pseudonym when it is a home. U8 tests both.

**AS3. Which trails the admission's bulk `imprint` covers** (the final check's FS1, carried).
6.4 still says "the trails whose log rows it keeps" (lines 577-578 and 639). I 8 defines R(I) as the roads and trails
derivable from the package's session ids and log rows. The verdicts agree, but a fixture's count would differ. Say "the
roads and trails derivable from its session ids and log rows" in both places, as interface row 13 asks.

### Nits

- **AN1.** The status line (line 4) still says "Revision 3, answering the second fresh reviewer's re-check". It could
  add the final check and the repair after FMF1. Its list of changed sections leaves out 18, which the repair changed.
- **AN2.** The header (line 23), 6.4 (line 574) and 11 (lines 1216-1217) say "trail spec revision 5". T is revision
  6. I checked those sentences against revision 6. T 8 still shows a stop's summary only with `read` and
  `inject_context`, still calls the `route` record the separate opt-in, and still keeps the support of 3. T 6.5 still
  fills `laid_by` for roads and trails. So the content holds and only the tag is stale.
- **AN3.** 6.4 (line 628) says 100,000 is "a collection's bound (5.4), the most memories an outside-home allow can
  reach". An outside-home allow may name up to 64 collections (5.2) plus 512 memories, so it can reach about 6.4
  million. The bound is fine and the reason is wrong. Say "the most memories one collection holds, and so the most an
  imprint holds (imprints spec D36)".
- **AN4.** 7.6 (line 951) names five commands for `engram/CLAUDE.md`'s new rule: `sign`, `allow`, `grant`, `migrate`
  and `gate`. Every CLI write needs the yes (7.6), and the table there lists more widening acts. The rule could say
  "any `engram-permissions` command that writes".
- **AN5.** Carried: the final check's FN1, FN2 and FN3, and the repair's `[permissions]` warning with no component.

### The interface table, from this spec's side

All 32 rows hold. I checked each row's P column against the sections it cites. I checked the I and T columns where
they make a claim about this spec, against I and T as they stand.

- Rows 3, 8, 20, 22, 29 and 30, broken before the repair, now resolve: P 15, U22, F1, P 19 and P 14's non-goals exist.
- Row 22: T 6.6 (its lines 826-828) shows receipts with 8 hex, as P 4.1 does.
- Rows 6 and 25: I 8 names h_I and its holding place as P 6.1 fixes them. See the first item below.
- Row 13 holds in its verdicts; AS3 is this spec's wording.

### For Rio Grande

- **I 8, an owner who is also the operator.** I 8 shows that the station's check is this spec's meet, with `Req` = {the
  owner's home layer, the operator's home layer}. When the owner is the operator, this spec's 6.3 counts that one home
  layer once. I 8 allows that case ("unless the owner is the operator"), and Andy's own store on his own Pi is the
  likely first imprint. A consent layer here is the union of its allows minus its denies. So if the ceiling were read
  as one more allow in that layer, after a ship's withdrawal this spec's meet would be wider than I's check. No verdict
  is wrong in step 1: the station's code computes the intersection (I 8, "The decision"), and step 2 moves withdrawn
  records in revoked (I 17). I 8 should say that when the owner is the operator, the home layer at the station is
  defined as the owner's records met with the ceiling, as P 6.1 lets a layer kept outside a ledger be. That is I's to
  change.
- **I 12** still writes "one row" for all roads and trails, while I 8 and P 9.1 split them per 100,000. Carried.
- **Parallel work.** I was being revised during this check. Its status line now says revision 4, answering its own
  final check's FS1 to FS3. I read its uncommitted diff: it changes calibration's paths analysis, D7, D16, D29, D41
  and the sections they touch, and no rule this spec owns. I checked the interface rows against I as it stood at about
  20:31 PDT. The same pass then updated I's side of interface rows 13, 14, 24, 27 and 28 ("Imprint final-check
  pass"). This spec's columns and rules in those rows are unchanged, and row 13 still carries AS3's wording for this
  spec's next revision.
- **T 7** (its line 914) cites this spec's 14 for "narrows mistakes, not malice". The words are in 7.6. Carried,
  optional.

### Still open with Andy (unchanged)

The license; one permission an agent may set on its own; what the county sets; pseudonyms; whether the terminal yes is
enough in step 1; agent shares at home under `enforce`; the two departures from principle 5; who decides in the county
steps; and memories that mention other people. On the last, this spec's default stands in 7.4, and section 19 lists
the question. Nothing here changes it.

Not checked: I ran no engram tests, since this is a spec review and no code changed. I ran Python only to compare the
spec with the scratchpad files. I edited no spec, and I committed nothing, pushed nothing and posted nothing.

## Response to the final check after repair (revision 4), 2026-10-25

The reviser applied AS1, AS2 and AS3, the nits AN1 to AN5, and the items the "Repair after FMF1" left: FS1 (which is
AS3), FN1, FN2, FN3, the trail spec's revision tag (AN2) and the `[permissions]` warning with no component. None was
declined. The spec is now revision 4 and keeps every section number. I edited the spec with targeted edits only, and
this file. I did not edit the imprints spec, the trail spec or the interface table, since others are editing them.
The rows the table's owner should update are listed below, for Rio Grande. Nothing here decides whether memories that
mention other people may move at all.

### Checked again while revising

- **`[permissions]` today.** `load_config` warns only about unknown keys inside the sections it loads
  (`engram/config.py:318-327`). `permissions` is not one of them (`:332-356`), so today the section is dropped with no
  warning. So 12.3's warning needs a component, and `config.py` is it.
- **What a refused read item carries.** The daemon decides the legacy frame once, before any item
  (`engram/lighthouse_daemon.py:402`), and every item gets that decision (`:433-440`). Its JSON holds only `effect`,
  `ruleId` and `code` (`engram/lighthouse_policy.py:65-67`). So the item names no item's layer. Only the receipt views
  of 9.2 could, which AS2 fixes.
- **`engram/CLAUDE.md`** still has no rule about agents running the person's commands (grep for "permission" and
  "never run" finds nothing), as 7.6 says.
- **The imprints spec (read, not edited).** I 8 defines R(I) as "the roads and trails of S that can be derived from I:
  from its episodes' session ids and its log rows". I D36 says an imprint holds at most 100,000 memories, the
  collection bound.
- **The trail spec (read, not edited).** Its status line says revision 6. T 8 still shows a stop's summary only when
  `read` and `inject_context` are allowed, still calls the `route` record the separate opt-in, and keeps the support
  of 3. T 6.5 fills `laid_by` for roads and trails, and a route has at most 64 stops (T R11, 6.5). So only the tag was
  stale, as AN2 said.

### Should-fix

- **AS1. Applied.** Use 13 now says what sections 10 and 15 say. A verbatim `remember` of m1 by `ph-coordinator`
  within 24 hours of an allowed delivery of m1, such as just after use 1, is refused. On 2026-12-15 it passes: no
  delivery of m1 in the example falls in the 24 hours before, so the guard finds no receipt, and the kept memory
  carries no source subjects. That is section 10's known limit, latent in step 1 because `ph-coordinator` is a fixture.
  E1 checks both cases. No rule changed.
- **AS2. Applied.** 9.2 now says:
  - the agents in a place see their own refusals only as the id, the time and "not allowed", with no code, layer,
    action or cited record; their allowed items show the annotation of section 11;
  - the requester's refused item carries no reason (12.2);
  - a place's stewards see a refusal's code and action, and its layer as the place's id when the place is not a home;
    a home's layer, cited or refusing, shows as the pseudonym that view gives the home's person, with no record ids;
    a legacy or restriction layer shows as `legacy` or `restriction`.

  A new paragraph under the table says why, with use 2: `NO_ALLOW` at `place:home/jenn` would tell `ph-coordinator`
  that m3 is about Jenn. The owner and the owner's agents still see the layer, which is how Andy's list says "m3: needs
  Jenn's yes". 9.1's `refusal`, 6.4's bulk refusal and section 11 point to 9.2. 12.2 records that the legacy frame
  decision names no item's layer (checked above). Use 2 says what the agent and the stewards see. U8 tests the
  agent's view, single and bulk, against the owner's, and the steward's view of a place, a home and a home's records.
  E1 checks use 2's views.
- **AS3. Applied.** 6.4 now says the imprints spec uses `imprint` "on the roads and trails derivable from the session
  ids and log rows it keeps", and that `Need(admission)` has "one counted bulk `imprint` on the roads and trails
  derivable from the package's session ids and log rows (that spec's R(I))". I wrote "the package's" where row 13 has
  "its", because "its" there could be read as this spec's. The meaning is row 13's.

### Nits

- **AN1. Applied.** The status line says revision 4, names the final check, the repair after FMF1 and the final check
  after repair, adds 18 to the repair's sections, and lists what revision 4 changed and why.
- **AN2. Applied.** The header, 6.4 and 11 say trail spec revision 6. The header's "Revisions 2 and 3 keep every
  section number" now says 2 to 4, and its list of changes that reach the other specs gains a revision 4 item.
- **AN3. Applied.** 6.4's "Size" says 100,000 is "the most memories one collection holds (5.4), and so the most an
  imprint holds (imprints spec D36)". The bound is unchanged.
- **AN4. Applied.** 7.6's rule for `engram/CLAUDE.md` is now "any `engram-permissions` command that writes, such as
  `sign`, `allow`, `grant`, `migrate` or `gate`", since every CLI write needs the yes. Section 16's `engram/CLAUDE.md`
  row says the same.
- **AN5. Applied, all four parts.**
  - **FN1.** 9.1 says "a named bulk use of at most 512 objects, such as an imprint batch or one of the evaluation's
    `read` batches". 6.4's "Size" says "such as an imprint batch".
  - **FN2.** 6.5 step 1 now says how a bulk use runs it: the tests on a, P, `anc(P)` and `anc(H)` once, then U's size
    bound, before any object; then each o ∈ O in ref order, with its own tests first in its decision. So any o ∈ O with
    no subject refuses with `NO_LAYER`, and any with more than 8 subjects with `BOUND`, unless an earlier object
    failed first. 6.4's "Refused" says an oversized U is refused before any object is decided. The old text didn't
    say where the size bound falls, and F1 needs one answer. Testing the size first costs nothing and decides no
    object. This order is the reviser's proposal for Rio Grande's call; it changes no verdict, only which code an
    oversized bulk use with another fault gets. U22 tests it.
  - **FN3.** I took the reviewer's second option, since grouping can't bound the worst case: objects may all differ.
    6.4 gains "Its Pi budget", and section 15 a calibration hypothesis: one bulk `imprint` of 100,000 derived objects
    whose `need` names 100,000 memories takes at most 40 s on the station's Raspberry Pi 5. That is the eligible-set
    rebuild's rate: 2 s for 20,000 (object, action) decisions there, and at most 400,000 here (three actions on each
    derived object, and `recall` on each memory). U24 now measures `explain` on such a use, with objects that don't
    group. Marked slow, and run on the Pi.
  - **The `[permissions]` warning.** `engram/config.py` gets a row in section 16: `load_config` warns when
    `config.toml` has a `[permissions]` section, which it ignores, and names `engram-permissions gate`. 12.3 says so,
    with the code citations above. The header's module list names `config.py`. The sentence "`engram/config.py` gains
    nothing" is gone. U16 checks the one warning.

### Beyond the letter of the items

Each of these narrows what someone sees, or states what the code already does. None widens a permission.

- The stewards' view no longer shows a home's record ids. Revision 3 said "the place records cited", which could be
  read to include R1 in Andy's home. 9.4 keeps home rules readable only by their person, and the fix asks that
  stewards see homes only as pseudonyms.
- A legacy or restriction layer shows to stewards by its kind alone. The publisher's ConnectionPolicy belongs to a
  person's house, so its id could point at a person.
- An agent's own allowed receipts show the annotation it was already given, and no more.

### Declined

None.

### Noticed, not changed

These are outside the items, and I did not decide them.

- **What one subject sees of another's home.** 9.2's first row lets a subject see "records" and "outcome" on every
  receipt that names them. So a co-subject, such as Jenn, would see the layer and record ids of Andy's home when it
  refused or allowed a use of m3. 9.4 keeps home rules readable only by their person. This is latent in step 1: no
  other person can read receipts or write a layer on this ledger (7.6). Step 2 should decide whether a subject sees
  another subject's home only as "another subject".
- **An allowed item's annotation names every allowing home** (section 11). Once co-subjects can say yes (step 2), an
  agent shown a memory about Andy and Jenn learns both homes from the line. Each said yes to the use, but not
  necessarily to being named. It is latent in step 1 for the same reason. It touches the open question about memories
  that mention other people, so it is left for Andy with that question.

### For Rio Grande

**Interface rows to bring to the table's owner.** I did not edit the table.

- **Row 13.** P 6.4 now has the wording the row asks for in both places (with "the package's" for "its"). The note
  "For P's next revision: P 6.4's last paragraph says ..." can be marked applied.
- **Row 21 (Receipts; P 9.2).** P 9.2 now says what each reader sees of a refusal: the agent that asked sees "not
  allowed" alone; stewards see a place's id, or a home as its person's pseudonym, and no home's record ids. The agreed
  rule doesn't describe views, and I and T show no refusal layer to any agent (grep finds none), so no rule changes.
  The row could note it under a "Permissions final-check pass".
- **Row 29 (Pi bounds; P 15).** P 15 gains "Bulk decision: 40 s on the station's Raspberry Pi 5" for one bulk
  `imprint` of 100,000 derived objects naming 100,000 memories, and U24 measures it. I's station decides by its own
  finite check, so I is unaffected. The agreed rule could add the budget.
- **Row 8 (bulk uses; P 6.5, U22).** A bulk use tests its requester, places and size before any object, then decides
  objects in ref order (P 6.5 step 1). No verdict changes. The agreed rule could add one line.
- Rows 3 and 23 cite text that changed only in its reason (P 6.4's 100,000) or its reach (P 7.6's `engram/CLAUDE.md`
  rule). Their agreed rules are unchanged.
- The table's "What changed, by spec" could gain a line: "Permissions, final-check pass (revision 4; header, 6.4, 6.5,
  7.6, 9.1, 9.2, 11, 12.2, 12.3, 13, 15, 16, 17): rows 8, 13, 21 and 29."

**Carried, for the other specs' revisers** (unchanged by this pass):

- **I 8, an owner who is also the operator.** As the final check after repair says: I 8 should define the home layer
  at the station, when the owner is the operator, as the owner's records met with the ceiling.
- **I 12** still writes one row for all roads and trails (its section 12, "An action on roads and trails ... gets one
  row"), while I 8 and P 9.1 split them per 100,000.
- **T 7** (its line 914) still cites this spec's section 14 for "this narrows mistakes, not malice". The words are in
  7.6. Optional.

### Checked after editing

- Every heading from `## 1.` to `## 19.` is present once (grep, one count per heading).
- The spec ends with a newline. It has 1,952 lines.
- `git diff` on the spec shows only the hunks listed above. No other line changed.
- No "revision 5" remains in the spec.

### Still open with Andy (unchanged)

The license; one permission an agent may set on its own; what the county sets; pseudonyms; whether the terminal yes
is enough in step 1; agent shares at home under `enforce`; the two departures from principle 5; who decides in the
county steps; and memories that mention other people. On the last, this spec's default stands in 7.4, and section 19
lists the question. Nothing here changes it.

Not checked: I ran no engram tests, since this is a spec revision and no code changed. I committed nothing, pushed
nothing and posted nothing.

## Check of the follow-up revision (revision 4), 2026-10-25

Reviewer: a fresh agent on the Pi, checking revision 4 in Andy's place (station law section 3). I took no part in
writing, reviewing, repairing or changing this spec. I checked only what revision 4 changed: the "Response to the final
check after repair" above, and `git diff HEAD` on the spec (98 lines added, 44 removed). I read the parts of the
imprints spec (I) and trail spec (T) that the changes cite, and interface rows 3, 8, 13, 21, 23 and 29. I edited no
spec and not the table. Spec lines are the working copy's. Code is cited by file and line, read today.

VERDICT: APPROVE

AS1 to AS3 and AN1 to AN5 are resolved. The file is complete. I found no new must-fix. Three should-fix items and four
nits remain. All are latent in step 1, and none blocks the plan. Nothing here decides whether memories that mention
other people may move at all.

### The file is complete

- Every heading from `## 1.` to `## 19.` is present once (grep, one count per heading).
- The file ends with a newline. It has 1,952 lines. HEAD has 1,898, and 1,898 + 98 − 44 = 1,952.
- Every hunk of the diff is one the response lists. No other line changed. No "revision 5" is left.
- Sections 18 and 19 are unchanged. Section 19 still lists the question about memories that mention other people,
  and decides nothing.

### AS1 to AS3: resolved

- **AS1.** Use 13 (lines 1570-1578) now matches section 10 (lines 1209-1218) and section 15's guard row. On
  2026-11-02, R1 lists no `imprint`, so a verbatim `remember` just after use 1 is refused. On 2026-12-15 the guard
  finds no allowed delivery in the last 24 hours, so the `remember` passes. Use 11 (2026-12-01) is 14 days earlier.
  Use 12 is a refused imprint, not a delivery. Use 13's own delivery is refused, and the guard reads only allowed
  receipts. E1 (line 1905) checks both cases. No rule changed.
- **AS2.** 9.2 (lines 1141-1154) now keeps a refusal's layer from the agent that asked, in its receipts and at the
  point of use (11, 12.2). Stewards see a home only as its person's pseudonym, with no record ids. Each change narrows
  what someone sees. None widens a permission. Use 2 (lines 1526-1530) is right. The first failing pair is
  (`place:home/jenn`, `recall`), since Andy's home comes first in 6.5's order and allows `recall`. U8 and E1 test the
  views. I and T show no refusal layer to any agent. I gives refusal codes only to the owner's use list (I 8, its
  lines 1025-1027).
- **AS3.** 6.4 (lines 591-592 and 655-657) now says "the roads and trails derivable from" the session ids and log
  rows. That matches I 8's R(I) (its line 980) and row 13's wording. "The package's" for row 13's "its" keeps the
  meaning.

### AN1 to AN5: resolved

- **AN1.** The status line says revision 4, names the final check, the repair and the final check after repair, adds
  18 to the repair's sections, and lists revision 4's changes with their sections.
- **AN2.** The header, 6.4 and 11 say trail spec revision 6. T's status line says revision 6.
- **AN3.** 6.4's "Size" gives the imprint bound as the reason. I D36 says an imprint holds at most 100,000 memories.
- **AN4.** 7.6 (lines 972-975) and section 16 now cover any `engram-permissions` command that writes. 7.6 says every
  CLI write needs the yes. `engram/CLAUDE.md` still has no such rule (grep for "permission" and "never run" finds
  nothing).
- **AN5.**
  - FN1 is in 6.4 and 9.1.
  - FN2, the bulk order in 6.5 step 1 (lines 671-674), is well defined. Requester and place tests run first, then
    the size bound, then each object in ref order. A per-object fault is decided as in a single use. It changes only
    which code a bulk use with two faults gets, never a verdict, so I 8's check still agrees in its verdicts (row 8).
  - FN3's budget is sound arithmetic. A bulk `imprint` on R(I) needs `recall`, `read` and `imprint` on each derived
    object, and `recall` on each memory named (6.4's table; I 8's `Need(admission)`). That is 300,000 + 100,000 =
    400,000 (object, action) pairs. The recall eligible set is one action per placement (12.2), so the rebuild makes
    20,000 pairs in 2 s, which is 10,000 a second, and 400,000 take 40 s. The largest of I's other uses is a bulk
    `route`: 100,000 + 100,000 = 200,000. See BS2 for the case P doesn't bound.
  - The `[permissions]` warning now has its component (section 16, `config.py`) and its test (U16).

### Code claims checked today, all true

- `engram/config.py:318-327`: `load_section` warns only about unknown keys inside a section it loads.
  `:332-356`: the sections `load_config` loads. `permissions` is not among them, so today a `[permissions]` section is
  dropped without a word. `:388-398`: the resolver's fallback, as 12.3 already said.
- `engram/lighthouse_daemon.py:402`: the read frame's decision is made once, before the item loop. `:411-440`: the
  loop. `:438`: every item gets that same `decision.to_json()`.
- `engram/lighthouse_policy.py:65-67`: `to_json` holds only `effect`, `ruleId` and `code`.
- So 12.2's new sentence holds. A refused item's `decision` is the same for every item of the frame and names no
  item's layer.

### Must-fix

None.

I looked for these:

- anything about a person moving without their yes;
- an agent widening a permission, or learning whose memory a refusal protected;
- broken mathematics;
- wrong claims about code;
- broken interfaces.

The new 9.2 rule closes the reads and receipts. The one point of use it doesn't name is BS1. That case is latent,
and the spec doesn't say the guard names a layer.

### Should-fix

**BS1. The `remember` guard's reply to the agent isn't covered by 9.2's new rule.**
Where: 10, "Keeping it is an imprint" (line 1209); 9.2's paragraph (lines 1149-1154); U17 (line 1852).

- **Why.** 9.2 now says the agent learns only that it was refused, "at the point of use (12.2) and in its receipts
  alike". The guard's receipt is covered by 9.2's table. Its reply to the `remember` call is not: section 10 doesn't
  say what it tells the agent. Section 18 lets the builder word errors "as long as each refusal names its rule", and
  that line is about the CLI.
- **Failure.** Use 1 delivers m1 to `ph-coordinator`. Later that day Andy records `person:amy` as a co-subject of m1
  (7.4 lets a later subject reach the next decision). Within 24 hours `ph-coordinator` calls `remember` with m1's
  text. The guard decides `imprint`. Subjects come first in 6.5's order, sorted by id, and `person:amy` sorts before
  `person:andy`, so the first failing layer is `place:home/amy`. If the reply names it, the agent learns that m1 is
  about Amy, who never said yes. The annotation at delivery named only Andy's home, so this is new to the agent.
  Latent: in step 1 every real receiver is one of the owner's own instances, and `ph-coordinator` is a fixture.
- **Fix.** Section 10 says the guard tells an agent that doesn't act for the owner only that keeping this content is
  not allowed, with no code, layer or action, as 9.2 says. U17 tests it with a co-subject recorded after the delivery.
  No rule changes.

**BS2. P doesn't bound how many memories a counted bulk use's `need` names, so "the largest size" isn't fixed.**
Where: 6.4, "Size" and "Its Pi budget" (lines 641-651); section 15's "Bulk decision" row (line 1702); U24.

- **Why.** 6.4 bounds the objects of a counted bulk use (100,000), and waives the bound of 32 named memories. It sets
  no bound on the memories that `need` names across the objects. The budget row assumes 100,000, which holds only
  because I D36 caps an imprint and every memory a road or trail of R(I) names is in objects(I) (I 8, line 980).
- **Failure.** In P's own terms, a counted bulk use with h a store, over 100,000 derived trails of up to 512 touches
  (T 4), could name up to 51.2 million memories. That is about 128 times the 400,000 pairs the budget covers.
  `explain` on it runs far past 40 s on the Pi, and U24 passes without measuring that case. Latent: in step 1 the
  only counted bulk uses are I's.
- **Fix.** 6.4's "Size" adds that a counted bulk use's `need` names at most 100,000 memories (the collection bound,
  as for objects), and a larger set is several bulk uses. Or 6.4 says the budget covers only such uses. Either is
  Rio Grande's call. U22 gains the case that applies. No verdict in I changes.

**BS3. The reviser's two "Noticed, not changed" items live only in this file.**
Where: 14, later steps, step 2; 19, "Memories that mention other people".

- **Why.** Both are for later steps or for Andy. A builder of step 2 reads the spec, and Andy reads section 19, not
  the review history.
  - The first item: a subject sees the records and outcome of every receipt that names them, so Jenn would see
    Andy's home's layer and record ids, while 9.4 keeps home rules readable only by their person.
  - The second item: an allowed item's annotation names every allowing home (11). That touches the open question.
- **Fix.**
  - Step 2 in 14 gains one line: decide what a subject sees of another subject's home in receipts (9.2).
  - Section 19's item gains a fact, not a decision: once co-subjects can say yes, the annotation names each allowing
    home, so an agent shown a memory about Andy and Jenn learns both homes.

  Neither line decides whether such memories may move.

### Nits

- **BN1.** Section 15's "Objects per bulk use" row (line 1689) still says "(an imprint batch)". FN1's "such as", and
  the evaluation's `read` batches, are in 6.4 and 9.1 only.
- **BN2.** 6.4's "Refused" (line 632) says an oversized U "is refused with `BOUND` before any object is decided". By
  6.5 step 1 (line 671) and U22 (line 1880), the requester and place tests come first, so an oversized U with an
  unregistered requester gets `UNKNOWN_REQUESTER`. It could say "once its requester and places pass".
- **BN3.** 9.2's paragraph (line 1152) says the ledger owner and the owner's agents see the layer, but the table has
  no row for them. An agent acting for the owner that was refused would read two rows: its own receipts ("not
  allowed") and the owner's list through `permissions(focus="uses")` (9.3), which shows the layer. Both are meant. A
  row "The ledger owner, and agents acting for the owner: the owner's list (9.3), with layers" would make the table
  say it.
- **BN4.** 9.2's agents row (line 1145) shows a refusal as "the id, the time and 'not allowed'". A counted bulk use
  names no id (9.1: `object` null), while U8 tests "single or bulk". It could say what a bulk refusal shows, such as
  the count, or the batch's digest for a named one.

### The interface table, from this spec's side

Rows 3, 8, 13, 21, 23 and 29 hold. I read them and did not edit the table.

- **Row 13.** P 6.4 now has the wording the note asks for, in both places. The note can be marked applied.
- **Rows 8, 21 and 29.** Their agreed rules are still true. The reviser's suggested lines are accurate:
  - row 8: bulk order in 6.5 step 1;
  - row 21: 9.2's views of a refusal;
  - row 29: the 40 s budget.

  If BS2 adds a bound on named memories, row 8's and row 29's agreed rules should name it.
- **Rows 3 and 23.** Only a reason (6.4's 100,000) and a reach (7.6's rule) changed. The agreed rules are unchanged.

### For Rio Grande

- The response's list of table updates is accurate. The table's owner can apply it as written.
- Carried for the other specs' revisers, checked today and unchanged:
  - **I 8** still allows an owner who is the operator (its line 864) without defining that home layer at the station
    as the owner's records met with the ceiling.
  - **I 12** still gives roads and trails one row (its line 1621).
  - **T 7** (its line 914) still cites this spec's 14 for "narrows mistakes, not malice". The words are in 7.6.
- BS2's choice between a bound and a narrower budget is Rio Grande's.

### Still open with Andy (unchanged)

These are still open:

- the license;
- one permission an agent may set on its own;
- what the county sets;
- pseudonyms;
- whether the terminal yes is enough in step 1;
- agent shares at home under `enforce`;
- the two departures from principle 5;
- who decides in the county steps;
- memories that mention other people.

On the last, this spec's default stands in 7.4, and section 19 lists the question. Nothing here changes it.

Not checked: I ran no engram tests, since this is a check of a spec revision and no code changed. I edited no spec
and not the interface table. I committed nothing, pushed nothing and posted nothing.
