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
