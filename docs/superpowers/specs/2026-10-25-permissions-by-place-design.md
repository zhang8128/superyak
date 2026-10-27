# Permissions by Place

**Date:** 2026-10-25
**Status:** Revision 7, for Andy's two decisions of 2026-10-26 (below), with the fixes from its check and its re-check
([small-hardware review](../reviews/2026-10-25-small-hardware-permissions-review.md), "Response" and "Re-check
response"). Revision 6 was
the fixes after the cross-check of the consolidation pass
([consolidation](../reviews/2026-10-25-city-rail-consolidation.md), "Cross-check" and "Cross-check fixes"). Revision 5
was the consolidation pass itself (the same file, which logs each change). It answers the check of
revision 4 ([review](../reviews/2026-10-25-permissions-by-place-spec-review.md), "Check of the follow-up revision":
approve, with BS1 to BS3 and BN1 to BN4). Revision 4 answered the final check after repair (the same file, verdict
approve; its "Response to the final check after repair" says what changed). Revision 2 answered the first fresh
review. An interface pass across the three city-rail specs then changed 4.1, 6.4, 9.1, 11, 14, 15, 17 and 19
([interfaces](../reviews/2026-10-25-city-rail-interfaces.md)). Revision 3 answered the second fresh reviewer's
re-check. It changed 3, 4.1, 5.1, 5.3, 5.4, 6.1, 6.3, 6.4, 6.5, 6.6, 7.4, 8, 9.1, 9.3, 10, 11, 12.1, 12.2, 12.3, 13,
14, 15, 16, 17 and 19. Its final check found the file cut off after section 14's first later step. The repair after
that restored the rest and brought 14, 15, 16, 17, 18 and 19 up to date, and the final check after repair approved
it. Revision 4 applies that check's AS1 to AS3 and AN1 to AN5, and the items the repair left:
- use 13 says the `remember` guard refuses only within 24 hours of a delivery (13, E1; AS1);
- a refusal tells the agent that asked no code, layer or action, and stewards see a home only as a pseudonym (9.1,
  9.2, 11, 12.2, use 2, U8; AS2);
- the admission's bulk `imprint` covers the roads and trails derivable from session ids and log rows (6.4; AS3);
- the trail spec is revision 6 (header, 6.4, 11; AN2); the reason for 100,000 is the imprint bound (6.4; AN3); the
  `engram/CLAUDE.md` rule covers every CLI write (7.6, 16; AN4);
- "such as an imprint batch" (6.4, 9.1); a bulk use's step-1 order (6.5, U22); a Pi budget for a bulk decision (6.4,
  15, U24); and `config.py` warns about `[permissions]` (header, 12.3, 16, U16) (AN5).

Revision 5 applies BS1 to BS3 and BN1 to BN4:
- a refused `remember` tells an agent that doesn't act for the owner only "not allowed" (10, 18, U17; BS1);
- a bulk use's roads and trails name at most 100,000 memories, and a larger set is split (6.4, 6.5, 9.1, 15, U22,
  U24; BS2);
- step 2 decides what a subject sees of another subject's home in receipts (14), and section 19 gains a fact (BS3);
- section 15 says "such as" (BN1); an oversized bulk use is refused once its requester and places pass (6.4; BN2);
  9.2 gains the owner's row and says what a bulk refusal shows an agent (BN3, BN4);
- the imprints spec is revision 5 and the trail spec revision 7 (header, 6.4, 11).

Revision 6 applies the cross-check's items for this spec:
- 9.1 item 3: the count of an imprint's roads and trails is the one the station's receipts carry, which that spec's
  admission makes, and a use the station refused before counting them holds null (XS2); "in that bulk use" (XN4);
- 6.4: that spec's `Need(admission)`, with `route`, also reads the memories for `trail-evaluation`, to count them
  (XS2);
- U24's fixture's trails have 512 touches each (XN3);
- the imprints spec is revision 6 and the trail spec revision 8 (header, 6.4, 11).

Revision 7 applies Andy's two decisions of 2026-10-26, which the vision records (its principle 4 and "Open for Andy"),
and then the fixes from its check (M1 to M7 and S1 to S9 of the review named above) and from its re-check (RC1 to RC4
and RCS1 to RCS10, the same file):
- "remember the ram limitations of this machine, build this so that it can run easily with small amounts of
  hardware." (A7) Rio Grande's call on what that means (P37):
  - the target is a Raspberry Pi with 2 GB of RAM;
  - every process this work adds peaks under 512 MB resident, measured on the Pi;
  - work over a large store streams or runs in bounded batches;
  - the embedder is shared and never loaded twice;
  - every systemd unit this work adds carries `MemoryMax` of 512 MB or less.

  Section 15 gains the memory budget, with each operation's figure and margin, the reference ledger it is measured
  on, and the parts that must stream or run in batches. 5.6 follows (a State reads per-object rows when decisions
  ask, `perform` holds one State at a time, and `rebuild` streams the log), and so do 5.4 (a ledger holds at most
  16,384 records, and one act names at most 10,000 collection members), 6.4, 8 (the box refs bound), 9.1 (the fold
  reads one receipt at a time, in batches), 12.2 (the cache's byte bound, two frames at once, at most 20 candidates
  per recall, the shared embedder), 16, and PT10, U9, U15, U24 and U27. None of these changes a permission decision.
  The new write bounds refuse a write as 5.4's other bounds do.

  Why: measured on the station's Pi on 2026-10-26 and scaled to the reference ledger, the step 1 build as it stood
  peaked at about 1.4 GB in `Ledger.state()` on that ledger. One cached eligible set at 20,000 placements and 43
  layers held about 182 MB, so the 64-entry cache could reach about 11.4 GB.
- "yes you can copy the full store." (A6) Andy, the owner, decided that his whole store may be copied, memories that
  mention other people included. Revision 6 refused a memory with a recorded co-subject until that person said yes,
  even into his own home. Revision 7 widens that one rule, on Andy's decision: P36 (end of 6.3). Inside the owner's
  home, his `imprint`, and every bulk use there that shows nothing to any agent, read each co-subject's layer as a
  restriction layer. A co-subject's silence passes, and their deny still refuses. The copy carries every subject
  (P25). Every use that shows content to an agent, and every use outside the owner's home, still needs every
  subject's yes. Sections 3 (A6, A7, P36, P37), 6.4, 6.6, 7.4, 14, 16, 17 (U5, U22, U29, F1) and 19 follow. Section
  19 lists P36 as a departure from the words of the vision's principle 1.

Every revision keeps every section number. No pass before revision 7 widened a permission. Revision 7 widens one, on
Andy's decision: P36. Step 1 is being built on branch `permissions-core`. Tasks 1 to 24 of its plan were done when
revision 7 was first written, and Tasks 1 to 28 when its check's fixes were applied. Its re-check's fixes cite that
build at `dc0881e`. Revision 7's memory changes and P36 reach that build as controller tasks of their own.
**Contract:** [the city rail vision](../../city-rail-vision.md). Its principles and its "Permissions by place"
section bind this spec. Rio Grande wrote them from Andy's words. Where they go past a quote, they are Rio Grande's
call carried by the contract, and this spec says so.
**Modules:** new `engram/permissions.py`, `engram/permission_ledger.py`, `engram/permission_uses.py`,
`engram/permission_cli.py`; changes to `lighthouse_daemon.py`, `neighbors.py`, `lighthouse_client.py`,
`context_lighthouse.py`, `sharing.py`, `server.py`, `storage.py`, `federation.py`, `policy_gen.py`, `config.py` (one
warning, 12.3), and migration `029`.
**Builds on:** [lighthouse local city](../../../engram/docs/superpowers/specs/2026-09-01-lighthouse-local-city-design.md),
[layered lighthouse](../../../engram/docs/superpowers/specs/2026-09-02-layered-lighthouse-design.md),
[memory lanes](../../../engram/docs/superpowers/specs/2026-06-12-memory-lanes-design.md),
[spec A](2026-10-08-instruction-layers-and-grants-design.md), [grants step 3](2026-10-15-grants-step3-design.md).
**Depended on by:** the imprints spec revision 7 and the trail spec revision 9. Both cite sections 5, 6 and 11.
Revisions 2 to 7 keep every section number, but line numbers moved. These changes reach them:

- `route` also needs `read` and `inject_context` on every memory whose content a route answer shows (6.4). From
  revision 3, every action on a road or trail needs `recall` on each memory it names (6.4).
- A kept copy carries its source's subjects (P25, 7.4). From revision 3, on one ledger it also gains subjects
  recorded on its source later (7.4).
- Revision 3: a use names the copy that serves it, `h` (6.1), with a grammar for copy refs (4.1).
- Revision 3: a use that shows nothing to any agent and lets only counts leave, such as the trail evaluation on an
  imprint, may be decided as one **bulk use** (6.4, P33). The bound of 32 named memories doesn't apply to it.
- Revision 3: 9.1 names the exact form of the station receipts the imprints spec imports.
- Revision 4: the agent that asked sees a refused read only as "not allowed", and a place's stewards see a home in
  a refusal only as its person's pseudonym (9.2). A bulk use tests its requester, places and size before any object
  (6.5, step 1), and a bulk decision has a Pi budget (15, U24). No rule either spec relies on changes.
- Revision 5: the roads and trails of one bulk use name at most 100,000 memories in all, and a larger set is several
  bulk uses (6.4). The imprints spec's uses always fit: every memory a road or trail of its R(I) names is a memory
  the imprint holds, and it holds at most 100,000 (its section 8 and D36).
- Revision 6: an imported counted row for an imprint's roads and trails holds the count the station's receipts carry,
  or null for a use refused before the station counted them (9.1, item 3). No rule either spec relies on changes.
- Revision 7: the memory bounds (15) change no decision. P36 (6.3) widens one rule, on Andy's decision. Inside the
  owner's home, the owner's `imprint`, and every bulk use there that shows nothing to any agent, named or counted,
  read each co-subject's layer as a restriction layer, and so do the uses their `need` adds on the owner's own
  memories. So the imprints spec's admission and trail evaluation on a copy kept in the owner's home are no longer
  refused for a carried co-subject who has no layer or is silent, and are refused for one who denies. Both other
  specs now read a carried co-subject's layer this way (the imprints spec's section 8, "Carried co-subjects in the
  meet"; the trail spec's section 7, "On a full-store imprint"). They still differ on one rule: a road or trail with
  more than 8 subjects in a bulk use, which this spec refuses with `BOUND` (19). A copy carries its source's subjects
  as 6.3, item 1 reads them, through `copies` too (7.4), and the imprints spec's `cosubjects(m)` must read them the
  same way (19). Every use that shows content to an agent, or whose P or H is outside the owner's home, still needs
  every subject's yes.

## 1. Why

Andy's words (vision, "What Andy said"):

- "We need levels of permissions that can be set and modified some by people some by agents some overlapping. for
  different layers and different places. I may share my medical history with the public health office but not the
  parks and rec."
- "We are deploying with the county of LA." It is "a sort of internal/external shared memory system where agents can
  get sheafs and traverse this high speed rail system as another layer of the internet and city itself where the
  county can provide rules and transparancy."
- "We should make it easy to port engram stores with permission from other computers. to imprint it here."
- "I'm seeing this as free, open source, uses universal mathmatical principles as connector standards and runs on a
  raspberry pi."
- "Take a step back. this is a system you will be traveling."

The pieces exist, but they are not one model, and none of them knows about people or places:

- **Shares are copies with an audience.** `share` copies one episode or semantic into the published house with an
  audience of `commons` or `group:<name>` (`engram/sharing.py:18-20`, `:41-46`, `:99-173`). A share has no purpose,
  no end date and no person. One row exists per `(source_instance, source_id, audience)`
  (`engram/migrations/027_shared_memories.sql:14-15`), and `source_instance` is the instance's name, not its store
  identity (`engram/server.py:1976`).
- **Any agent can share.** `share` is an MCP tool (`engram/server.py:1949-1980`). Nothing asks the person. That breaks
  principle 1 of the vision: "Anything about a person moves only with that person's yes."
- **ConnectionPolicy is about instances.** It is deny-by-default and directional, with purpose and validity
  selectors (`engram/lighthouse_policy.py:1-7`, `:18-27`). The most specific rule wins and deny wins a tie
  (`:78-111`, `:146-156`). It lives in one file per instance (`engram/lighthouse_daemon.py:506-518`), issued by that
  instance (`engram/lighthouse_validation.py:25-34`).
- **The local city separates actions.** `recall` yields ids and digests, `read` yields content, and `inject_context`
  is needed to deliver into a response (local-city spec, section 4.4). The receiver checks `recall` before asking
  and all three before reading and again before delivery (`engram/neighbors.py:82`, `:120`, `:132-143`). Receipts
  carry no query text and no content (`engram/lighthouse_receipts.py:1-6`).
- **Station grants chain.** A child is a subset of its parent in every field (spec A, section 2). Validity is a walk
  to the root at each check, and "Nothing cascades, so a revocation anywhere above takes effect at the next check"
  (spec A, section 2; `peer/superyak_peer/grants.py:72-122`). They grant builds of ships, not uses of memories.
- **Lanes were a proxy.** The layered lighthouse design already retired the work-lane publish rule for an explicit
  share with an audience (its lines 1-11). Trail spec revision 3 said "Only the work lane can ever leave" (its
  section 8). Revision 4 replaces that with per-audience permissions, as the vision asks.

This spec gives one model for all of it: places, people, a permission record, a lattice order, and receipts. It
builds step 1 on one machine. It names the questions the county steps must still answer (section 14), because some
of them need design.

## 2. Vocabulary

| Term | Meaning |
|---|---|
| **Person** | A human. Only a person says yes about what is about them. |
| **Ledger owner** | The person who ran `engram-permissions init`. In step 1 the only person who says yes on that ledger (7.6). |
| **Agent** | A program acting for one person or one place, for example an engram instance or a station ship. |
| **Acts-for place** | `act(a)`: the home of the person agent a acts for, or the place it acts for. It never changes. |
| **Place** | A named scope with its own rules: the county, a department, an office, a joint program, or a person's home. |
| **Home place** | `place:home/<handle>`, one per person. Its rules are that person's consent. |
| **Joint place** | A place with two or more parents, for example a program two departments run together. |
| **Dominates** | Z dominates X when every path from X up to a root passes through Z (section 4.3). |
| **Steward** | A person who may set a place's rules. A person is the only steward of their own home. |
| **Ledger** | The SQLite file that holds places, people, agents, records, grants and proposals, with an append-only log. |
| **Layer** | One authority's set of records. A **consent** layer denies by default. A **restriction** layer only denies. |
| **Record** | One permission: allow or deny, a selector, a validity interval, and who set it under what (section 5). |
| **Use** | One act on one object: who asks, from which place, for what purpose, which action, when. |
| **Subject** | A person or place a memory is about. Each subject's consent layer must allow every use, except as P36 reads it (6.3). |
| **Collection** | A person's named set of memories, for example `collection:andy/medical-history`. |
| **Grant** | A person's standing grant to an agent: which edits it may make to that person's layer, within an envelope. |
| **Envelope** | The selector that bounds every record an agent makes under a grant. |
| **Proposal** | A wider change an agent asks for. It does nothing until the person signs it. |
| **Placement** | A copy of a memory in a house that serves it, for example a `shared_memories` row. It is not a permission. |
| **Kept copy** | A memory written into a store from another memory's content: an imprint, a `remember` of delivered content, a genome sync. |
| **Receipt** | The record of one use or one refusal (section 9). |
| **Horizon** | The earliest time after a decision at which its verdict could change with no ledger write (6.5). |

## 3. Decisions

"Andy" means Andy's own words, quoted as the vision gives them. Every other line is Rio Grande's call, and the text
cites its number where it applies. `place:home` and `home` as a first place segment are reserved for homes.

| # | Decision | Source |
|---|---|---|
| A1 | "We need levels of permissions that can be set and modified some by people some by agents some overlapping. for different layers and different places." | Andy (quote) |
| A2 | "I may share my medical history with the public health office but not the parks and rec." | Andy (quote) |
| A3 | "the county can provide rules and transparancy." | Andy (quote) |
| A4 | "free, open source, uses universal mathmatical principles as connector standards and runs on a raspberry pi." | Andy (quote) |
| A5 | "make it easy to port engram stores with permission from other computers." | Andy (quote) |
| A6 | "yes you can copy the full store." The owner may imprint his whole store, memories that mention other people included. They keep their recorded people as co-subjects, so any use of them outside his home still needs those people's yes (P12, P25). Copying is not sharing. | Andy (quote, 2026-10-26, the vision's "Open for Andy"); the rest is the vision's reading, Rio Grande's call carried by the contract |
| A7 | "remember the ram limitations of this machine, build this so that it can run easily with small amounts of hardware." | Andy (quote, 2026-10-26, the vision's principle 4) |
| P1 | Inside a layer, deny records win literally; across layers, the meet (intersection). No specificity. | Rio Grande's call (the vision says "Deny wins") |
| P2 | Every consent layer belongs to a place. A person's consent layer is the layer of their home place. | Rio Grande's call |
| P3 | An allow's `place:Z` reaches a requester only when Z dominates both its place and its acts-for place. A deny's `place:Z` reaches every requester whose place or acts-for place has Z as an ancestor. | Rio Grande's call |
| P4 | Required layers: every subject, the requester's place chain, the holding place's chain, legacy policies, the agent's restrictions. | Rio Grande's call (the vision names person, agent, receiving place and county) |
| P5 | Five actions with a fixed closure: `inject_context` needs `read` needs `recall`, and so on. | Rio Grande's call |
| P6 | Coverage names only what a person or steward chose. Outside a person's home, nothing an agent or a heuristic sets at write time widens what an allow covers (P28). | Rio Grande's call |
| P7 | Allows read memberships narrowly and denies read them widely. A lane must hold continuously for an allow, and a pending lane move counts as neither lane for an allow and as both for a deny. | Rio Grande's call |
| P8 | A narrowed record is intersected, selector and validity interval, with every record it replaced, and a grant-made record with every envelope above it, at every decision. | Rio Grande's call |
| P9 | A record is backed by its person or by a grant. A grant-backed record dies with its grant; a person-backed one does not. Every deny is person-backed. | Rio Grande's call |
| P10 | Agents edit a person's layer only under that person's grant: listed ops, one envelope, chains of at most 3 links, at most 720 hours. No grant exists by default. | Rio Grande's call (the vision marks this as Rio Grande's call) |
| P11 | A proposal is signed or declined one at a time, and expires after 7 days. The ledger writes its words. | Rio Grande's call |
| P12 | A memory's default subject is its store's owner. Anyone acting for the owner may add a co-subject. Removal is limited. | Rio Grande's call |
| P13 | In a home layer, an allow that reaches outside the home needs named purposes and an end date at most 366 days out. | Rio Grande's call |
| P14 | Times are integer UTC seconds. Validity is half-open, `[from, until)`. | Rio Grande's call |
| P15 | The ledger is its own SQLite file with a hash-chained log. Receipts go in a second file. The daemon opens the ledger read-only. | Rio Grande's call |
| P16 | A disagreement at a joint place is what the joint place asks for that one parent allows and another refuses. Deny holds and a person is shown it. | Rio Grande's call |
| P17 | One receipt per recall, one per read item. Owners see every use of their memories. A place's stewards see subjects under pseudonyms, a display convention. Home rules are private. | Rio Grande's call |
| P18 | The daemon decides a `read` frame as `inject_context`. | Rio Grande's call |
| P19 | Writing delivered content into one's own store is an `imprint` use. | Rio Grande's call |
| P20 | In step 1 the yes belongs to the ledger owner alone, given in a terminal command that reads a code from `/dev/tty`. Every act that can widen needs it (7.6). | Rio Grande's call |
| P21 | Migration maps today's shares to records without widening, behind a gate `off`, `shadow`, `enforce`. The gate lives in the ledger and only the owner's yes moves it. Once raised, a missing, unreadable or unknown gate fails closed, and so does a store that should carry the ledger's id and doesn't (12.3). Enforce needs both old and new to allow. | Rio Grande's call |
| P22 | Places are retired, never deleted. Parent edges are never removed. | Rio Grande's call |
| P23 | A requester never learns that a refused memory exists. | Rio Grande's call |
| P24 | A derived object (a road, a trail) has the union of its sources' subjects plus its store's owner. | Rio Grande's call (the vision: an agent's trails are the person's) |
| P25 | A kept copy carries every subject of its source as a co-subject, written in the same act, and its store records the source ref. On one ledger it also has its source's subjects at each decision, read through `copies`. An imprint keeps its source's refs. | Rio Grande's call |
| P26 | A place registered as a root stays a root. No act gives it a parent. | Rio Grande's call |
| P27 | In a consent layer, an agent's narrowing ops touch allows and memberships only. Revoking, shortening or narrowing a deny there is a steward's act or a proposal. | Rio Grande's call |
| P28 | In a home layer, an outside-home allow reaches memories only by ids and collections, and roads and trails only by store and through their memories' allows. Stores, kinds, layers and lanes only narrow it. | Rio Grande's call |
| P29 | A placement's audience column holds a fixed mapping of its record's audience. Outside-home placements carry the reserved `group:outside-home`. The daemon strips that name from every policy it reads, and adds it back only under `enforce`. | Rio Grande's call |
| P30 | A decision reports `until`, a lower bound on its end, and a `horizon`, both over ledger layers only. A cached decision ends at its horizon. | Rio Grande's call |
| P31 | In step 1 an agent is in exactly one place. Putting it there needs a steward of the place and the agent's principal. | Rio Grande's call |
| P32 | An object with no subject is refused (`NO_LAYER`). | Rio Grande's call |
| P33 | A use whose answer names no object and shows no content to any agent, so that only counts, rates and digests leave, may be decided as one bulk use over a finite set of objects: `need` over every object, the bound of 32 named memories waived, one receipt with counts. | Rio Grande's call (the re-check's RMF1, option (a)) |
| P34 | A use names the copy that serves it, `h`. The chain of h's place is required. | Rio Grande's call |
| P35 | Every action on a road or trail needs `recall` on each memory it names, and `read` and `inject_context` on each memory whose content it shows. | Rio Grande's call |
| P36 | Inside the owner's home, his `imprint`, and every bulk use that shows nothing to any agent, read each co-subject's layer as a restriction layer: silence and a missing layer pass, a deny refuses. It covers the uses their `need` adds on the owner's own memories. Every other use reads it as a consent layer. It widens what revision 6 allowed (6.3). | Rio Grande's call on the form, on Andy's decision A6 |
| P37 | Every process this work adds peaks under 512 MB resident, measured on the Pi, for a Raspberry Pi with 2 GB of RAM. What grows with the store streams or runs in bounded batches. The embedder is shared and never loaded twice. Each systemd unit this work adds carries `MemoryMax` of 512 MB or less. | Rio Grande's call, reading A7 (the vision's principle 4) |

## 4. Names and places

### 4.1 Identifiers

| Kind | Grammar | Example |
|---|---|---|
| Person | `person:` + `[a-z][a-z0-9-]{0,62}` | `person:andy` |
| Agent | `agent:` + `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` (the instance-name grammar, `engram/lighthouse_receiver_config.py:13`) | `agent:engram` |
| Place | `place:` + segments joined by `/`, each `[a-z0-9][a-z0-9-]{0,62}`, 1 to 8 segments, at most 255 characters | `place:la-county/public-health` |
| Home place | `place:home/<person handle>`; `home` alone is not a place | `place:home/andy` |
| Group | `group:` + `[a-z][a-z0-9-]{0,63}` (today's grammar, `engram/sharing.py:19`). `group:outside-home` is reserved (P29). | `group:engram-system` |
| Collection | `collection:<person handle>/<name>`, name `[a-z][a-z0-9-]{0,79}` (room for the migration's names, 12.3) | `collection:andy/medical-history` |
| Audience words | `commons`, `self` | |
| Memory | `mem:<instance_id>/<episode or semantic>/<memory id>`; `instance_id` is the store's `meta.instance_id` (`engram/store_identity.py:113-116`) | |
| Road, trail | `road:<instance_id>/<cell id>`, `trail:<instance_id>/<trail event id>` | |
| Copy (the house that serves a use) | `store:<instance_id>` for a store a ledger registers (5.5, `stores`), or `imprint:<station peer id>/<imprint id>` for an imprint held at a station, where the imprint id is that imprint store's `instance_id` (imprints spec section 11) | `store:9b1e…`, `imprint:5d0c…/c0a8f5e2-…` |
| Record, grant, proposal, use | `r-`, `g-`, `p-`, `u-` + 32 lowercase hex | |

**Short ids are for display only.** The short form is `#` plus the first 4 hex, as station grants show theirs
(`peer/superyak_peer/grants.py:32-34`). Among a layer's 256 records, two share a short form with probability about
0.39. So every command takes a full id, or a prefix of at least 4 hex that matches exactly one id on the ledger. A
prefix that matches more than one is refused, and the refusal lists the matches.

**A receipt's short form has 8 hex.** The annotation (section 11) shows a use's receipt as `#` plus the first 8 hex
of its id. An agent holds many receipts, and the short form is its only handle on them. With 4 hex, even odds of a
repeat come at about 300 receipts; with 8, near 77,000. The trail spec's receipts show 8 for the same reason (its
6.6), and its answers will carry this receipt in later steps (its 6.5). Rio Grande's call.

**Copy refs** (P34, Rio Grande's call). One memory ref can be held in several houses: its own store, the published
house that serves a placement of it, and an imprint that keeps its source's refs (7.4). A copy ref names the house.
A store using its own memories, and the published house serving a placement, are `store:` refs. An imprint is always
named by its `imprint:` ref, so its receipts name one copy wherever they are read. A ledger that later registers the
imprint's store (step 2) finds its `stores` row by the imprint id, which is that store's `instance_id`. A kept copy
made by `remember` is a memory of its own with its own `mem:` ref (7.4); it is served by its keeper's `store:` ref.

Every ledger has a `ledger_id` (a random UUID made at `init`). Outside its ledger, an id is written
`<ledger_id>:<id>`, as spec A writes station ids (`<station peer id>:<id>`). In step 2 a station's ledger uses the
station's peer id.

### 4.2 Nesting

A place has a set of parents, `Par(X)`. A root has none. A home place is a root. A place's **ancestors** are itself
and every place above it by any path: `anc(X) = {X} ∪ ⋃_{Q ∈ Par(X)} anc(Q)`.

- **Name rule.** Drop the last segment of a place's name. What remains, if anything, must be a registered place that
  dominates the new place (4.3). So `place:la-county/public-health/clinic-3` sits under public health, and a joint
  program of public health and parks is named under the county, for example `place:la-county/summer-wellness`, with
  both departments as parents.
- **Parents.** With no parent given, the parent is the name's prefix. A place has at most 4 parents.
- **Roots stay roots** (P26). A place registered with no parent never gains one. A one-segment name and every home
  are roots. To put the county under a state later, the state registers a new place, for example
  `place:california/la-county`, and its rules are made again. Records never follow a place.
- **No cycles.** Adding a parent that would make a cycle is refused.
- **Bounded ancestry.** A place has at most 16 ancestors, itself included. A registration or a parent edge that would
  give any place more is refused.
- **Never removed** (P22). A parent edge is never removed, and a place is never deleted.
- **Retiring a place.** A steward may retire a place. Then no use at it, or at any place below it, is allowed
  (`RETIRED`), no record reaches it, and its rules stay readable. Its sub-places stay registered and unusable. A
  sub-place that should go on is registered again under a living parent. Retiring is permanent in step 1.
- **Retiring a person.** The person, or a ledger admin, may retire a person. Their home is retired with them, and
  every use of an object they are a subject of is refused (`RETIRED`). It only narrows, and it is permanent in
  step 1.

### 4.3 Dominance

Z dominates X when every path from X up to a root passes through Z. X dominates itself. Computed in topological
order:

- `dom(X) = {X}` for a root;
- `dom(X) = {X} ∪ ⋂_{Q ∈ Par(X)} dom(Q)` otherwise.

With one parent everywhere, this is plain nesting. For the joint place `summer-wellness` under public health and
parks, `dom = {summer-wellness, la-county}`: neither department dominates it, and the county does.

**Adding a parent to a place that already has one** can only shrink `dom` and grow `anc`. The intersection for X
gains a set, so `dom(X)` can only shrink. Every place below X computes its `dom` from X's by unions and
intersections with fixed sets, which are monotone, so theirs can only shrink too. `anc` only gains members. A root
is the exception, which is why P26 forbids it: giving root X a parent Q would make `dom(X) = {X} ∪ dom(Q)`, larger,
and every place below X would grow with it. Registering a new place changes no existing place's `dom` or `anc`,
because it has no children yet. No act removes an edge. So `dom` never grows for an existing place.

### 4.4 Who registers places and people

| Act | Who | Note |
|---|---|---|
| Create a ledger | The person who runs `engram-permissions init`. They become its owner, its only admin in step 1, and a person on it. | |
| Register a person | A ledger admin. This creates the person's home place with an empty layer, so nothing about them moves until they say yes themselves. | |
| Register a root place | A ledger admin. | In step 3 the county's own people (Open for Andy) |
| Register a child place | A steward of its parent. | |
| Register a joint place | One steward of every parent signs. It waits as a proposal until all have. | |
| Add a parent edge | A steward of the place and a steward of the new parent, only to a place that already has a parent (4.2). It only narrows (4.3). | |
| Add or remove a steward | A steward of the place, or of a place that dominates it. A place keeps at least one steward. | Home: the person only, never changed |
| Register an agent | The person it acts for, or a steward of the place it acts for. | Sets `act(a)`, which never changes |
| Put an agent in a place | A steward of that place and the agent's principal (the person it acts for, or a steward of the place it acts for). In step 1 an agent is in exactly one place; a second is refused until the first is removed (P31). | |
| Remove an agent from a place | A steward of that place, or its principal. | |
| Register a store | The store's owner (a person, or a steward for a place's store). Its owner is the default subject of its memories (P12). An imprint store is registered with `imprint_of`, its source's `instance_id` (7.4). | |
| Retire a place or a person | 4.2. | |

On one ledger in step 1, every act in this table that can widen also needs the ledger owner's terminal yes (7.6).
At most 1,024 places per ledger.

## 5. The permission record

### 5.1 Fields

| Field | Meaning |
|---|---|
| `id` | `r-` + 32 hex. |
| `layer` | The place whose layer it is in (consent), or the agent whose restriction layer it is in. |
| `effect` | `allow` or `deny`. A restriction layer holds only `deny`. |
| `selector` | What it matches (5.2). |
| `valid_from`, `valid_until` | Integer UTC seconds, half-open (P14). `valid_until` null means until revoked; see 5.4 for when that is allowed. |
| `anchor` | The `created` time of the first record in its `replaces` chain. History rules read it (5.3). |
| `backing` | `person` or `grant:<id>` (P9, section 7.3). |
| `set_by` | The person or agent that wrote it. |
| `channel` | `terminal`, `tool`, `migration`; step 2 adds `browser`. |
| `under_grant` | The grant an agent used, or null. |
| `proposal_id` | The proposal it came from, or null. |
| `replaces` | The record it narrows, or null. A chain is at most 16 long. |
| `reason` | One line, at most 200 characters. |
| `created`, `created_seq` | Time and log sequence number. |
| `revoked`, `revoked_by`, `revoke_reason`, `revoked_seq` | Filled once, by a revocation. Nothing else in a row ever changes. |

A record is **effective** at ledger state σ and time t when it is not revoked at σ and `valid_until` is null or after
t.

**The ledger-only fields** are `created_seq`, `revoked`, `revoked_by`, `revoke_reason` and `revoked_seq`. Only a
ledger can fill them. A record kept outside a ledger, such as one inside the imprints spec's signed permission (its
section 8), leaves out exactly these five and carries every other field above. Its revocation is then a receipt where
it is kept. Step 2's `permission-record` signs the same form (section 14).

### 5.2 The selector

A selector is canonical JSON: the Lighthouse TypeScript kit's canonicalization, which engram's `canonical_json`
implements (`engram/lighthouse_protocol.py:1-6`, `:78`). Object keys sort by UTF-16 code units (`:114-121`). Each list
is 1 to 64 distinct values sorted the same way, or the string `"*"`. Every grammar in 4.1 is ASCII, so that is byte
order. `memories` allows up to 512 values; use a collection for more.

**`"*"` means "no constraint".** A dimension that is `"*"` matches every object, including one with no value for it.
So `collections: "*"` matches a memory that is in no collection.

```json
{"audience": ["place:la-county/public-health"],
 "requesters": "*",
 "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
             "collections": ["collection:andy/medical-history"], "memories": "*"},
 "actions": ["recall", "read", "inject_context"],
 "purposes": ["care-coordination"]}
```

- **`audience`** (1 to 32 entries, never `"*"`): who may use it. Let a be the requester, P the place of the use,
  `act(a)` its acts-for place (section 2), and L the layer, whose place is `place(L)`.
  - `place:Z` in an allow: `Z ∈ dom(P)` and `Z ∈ dom(act(a))` (P3). The agent must work at a place Z dominates and
    act for one. Who acts for a place is decided by that place's stewards and the stewards above it (4.4). The words
    a person confirms for such an allow say so (7.6).
  - `place:Z` in a deny: `Z ∈ anc(P)`, or `Z ∈ anc(act(a))`, or `Z ∈ anc(X)` for some place X that a was in during
    `[anchor, t]`.
  - `group:g`: a requester agent that belongs to group g. A group belongs to one person, holds only agents that act
    for that person in step 1, and only that person changes it. In an allow, it also needs `home(owner(g)) ∈ dom(P)`.
  - `self`: a requester agent with `act(a) = place(L)`. In an allow, it also needs `place(L) ∈ dom(P)`.
  - `commons`: any requester.
- **`requesters`**: agent ids, or `"*"`. It narrows the audience to named agents.
- **`objects`**: every listed dimension must match (a conjunction).
  - `kinds` ⊆ {`memory`, `road`, `trail`}: the rail's layers. Instincts, dream residue, task contexts and the
    knowledge graph are never objects; they never leave (as today: `engram/sharing.py:20`).
  - `stores`: store `instance_id`s. `layers` ⊆ {`episode`, `semantic`}: memory layers. `lanes` ⊆ {`personal`,
    `work`}. `collections`: collection ids. `memories`: memory refs.
  - For a road or trail, `layers`, `lanes`, `collections` and `memories` must all be `"*"`: what it touches is
    checked through the memories it names instead (6.4).
- **`actions`** ⊆ {`recall`, `read`, `inject_context`, `route`, `imprint`} (6.4).
- **`purposes`**: purpose names in the group-name grammar, at most 16, or `"*"`. A requester declares its purpose.
  The receipt records it. Nothing can check that it is honest; that is accountability, not enforcement.

No selector depends on a classifier, an embedding, a category or anything else the system derives (P6). Lanes and
stores are not chosen by the person, though. Engram derives a memory's lane at write time from `work=True`, a
`project` key in its context, or `[memory] default_lane` (`engram/server.py:1802-1822`, `engram/config.py:74`), and
the layered lighthouse design calls the lane "a proxy for 'safe to publish,' derived at write time" (its lines 9-10).
Which store a memory lands in depends on the instance an agent runs as (`engram/server.py:1303-1310`). So an allow that names a lane or a store
covers whatever agents later write there. 5.4 limits what such an allow may do outside a home (P28), and 5.3 reads
lanes so that a re-lane never widens.

### 5.3 Matching, with history (P7)

A record r matches a use u at time t when all of these hold:

1. `valid_from ≤ t < valid_until` (no upper bound when `valid_until` is null), and r is not revoked at the
   decision's log sequence;
2. the audience (5.2), `requesters`, `actions` (the action being checked) and `purposes` match;
3. every object dimension matches, reading memberships as below;
4. every record in r's `replaces` chain also matches u by rules 1 to 3, where rule 1 checks only its validity
   interval: each record in the chain was revoked by the record that replaced it, and that revocation is ignored
   (P8);
5. if r is grant-backed, every envelope in its grant chain matches u by rules 2 and 3, and the chain is valid at t
   (section 7.2).

Rule 4 makes a replacement match no use its original doesn't, by selector and by time, whatever the replacement's
own fields say.

Memberships change over time. Allows read them narrowly and denies read them widely:

| Membership | Changed by | An allow matches when | A deny matches when |
|---|---|---|---|
| Lane | compression review, not a permission act | the memory's lane was L throughout `[max(anchor, created_at), t]`, with no pending move in that interval | the lane was L, or a move to or from L was pending, at any time in `[anchor, t]`; or the memory has no lane note |
| Collection | the person, or an agent within an envelope (checked as a widening) | the memory is in it at t, by an effective membership | it was in it at any time in `[anchor, t]` |
| Group | its person | the agent is in it at t | it was in it at any time in `[anchor, t]` |
| Agent in a place | that place's steward and the agent's principal (4.4) | the agent is in that place at t | it was there at any time in `[anchor, t]` |
| Place parents | stewards; never removed | dominance (4.3) | ancestry (4.2) |

A memory with no lane note matches no allow whose `lanes` is a list, and every deny whose `lanes` is a list.

A collection membership has a backing, like a record (P9). A grant-backed membership counts for an allow only while
its grant chain is valid, and only for uses inside every envelope of that chain. Every membership row counts for
denies.

**Lane notes.** The ledger learns lanes from notes (`lane_notes`). A memory's first note is dated at its
`created_at`, with the lane it has when the ledger first sees it: when it is placed (`share`), added to a
collection, found placed by `migrate`, or re-laned. `Storage.set_episode_lanes` (`engram/storage.py:598-610`) is the
only writer of lanes after creation. It gains a listener, called twice:

1. Before its `UPDATE`, the listener writes a first note for each memory that has none, then a `pending` note dated
   now. If either can't be written, the re-lane is refused.
2. After the `UPDATE` commits, it writes a note with the new lane. If the `UPDATE` fails, it writes a note with the
   old lane.

A pending interval runs from a `pending` note to the next note. If the process dies in between, the note stays
pending, which only narrows. The next sweep (10) reads the store's lane read-only and writes the settling note. The
lane store and the ledger are two files, so this order matters: a note that claimed a move before it happened would
let a work-lane allow match a memory that is still personal.

The engine reads the source memory's lane from these notes, never from the published copy. A copy's own `lane`
column is not the source's: `share` writes every copy as `personal`, by the storage defaults for an episode
(`engram/sharing.py:147-148`, `engram/storage.py:562`) and a semantic with a vector (`engram/sharing.py:150-153`,
`engram/storage.py:1084`), and explicitly for a semantic without one (`engram/sharing.py:155-159`).

**A copy held away from its source's ledger** (RN4 of the re-check; Rio Grande's call). An imprint at a station has
no lane notes there. Its decider reads a memory's lane from the imprint itself, where the build fixed it to the
source's lane when the owner said yes (imprints spec section 8, "The denotation"). A re-lane at home after that does
not reach the imprint. That widens nothing the owner didn't say yes to: an outside-home allow reaches memories only by
listed ids and collections (P28), so a lane only narrows it, and the yes covered the shipped memories as they stood.
A lane-limited deny written at home after the build reaches the imprint only in step 2, as later subjects do (7.4).
The owner can withdraw the imprint at any time meanwhile.

**Known limit.** Re-lanes made before the ledger existed, or while the gate was `off`, are invisible: a first note
assumes the lane held since creation. Compression review re-lanes only toward what it judged correct, and Andy's yes in
`migrate` covers the placed memories as they stand.

### 5.4 Validity rules at write time

- An allow in a home layer is **inside home** when every audience entry is `self`, a group of the person's own
  agents, or `place:Z` where the person's home place dominates Z. Otherwise it is outside home. `commons` is outside
  home. Since `self` and group entries match only at places the home dominates (5.2), an inside-home allow reaches no
  use outside the home.
- An outside-home allow in a home layer needs a finite `purposes` list and a `valid_until` at most 366 days after
  `valid_from` (P13). The person renews it by saying yes again. An inside-home allow may use `"*"` purposes and a
  null `valid_until`.
- **What an outside-home allow may name** (P28). It is one of two shapes:
  - kinds `["memory"]`, with a finite `memories` list, a finite `collections` list, or both. Memories enter it only
    by the person's choice or an envelope's check: a listed id, or a collection membership.
  - kinds ⊆ {`road`, `trail`}, with a finite `stores` list. It covers only the roads and trails of stores the person
    named. Every use of one, whatever its action, also needs `recall` on each memory it names, and `read` and
    `inject_context` on each memory whose content it shows, by other records (6.4, P35). So no use of a road or trail
    names a memory its audience may not recall.
  Beyond what each shape requires, `stores`, `layers`, `lanes` and `kinds` only narrow. They may still be the whole
  of an inside-home allow and of any deny.
- A place's layer has no lifetime rule. Its allows only ever narrow a person's, since the person's layer is always in
  `Req` (6.3, item 1).
- A deny may have a null `valid_until` anywhere.
- At most 256 effective records per layer, 8 subjects per object, and 100,000 members per collection. A write over a
  bound is refused with the bound in the reason.
- **Two bounds for memory** (revision 7; Rio Grande's call; 15, "Memory"). A ledger holds at most 16,384 records,
  revoked and replaced ones included, because a State holds them whole (5.6). A `collect` or `uncollect` act names at
  most 10,000 objects, because `perform` and `rebuild` each hold one act's body whole. A write over either is refused
  with the bound in the reason. The records count is taken inside the write's own `BEGIN IMMEDIATE` (5.5), for every
  write that adds a record: an act, a signed proposal (7.1) and `migrate`. So two writers at once can't both pass it.
  A revocation writes no record, so a person can always revoke. A new deny, a shortening and a narrowing each write a
  record, so at the bound they are refused too, until a State reads records per layer (15, "Records per ledger").
  At the bound a person narrows by revoking. One CLI command splits a larger set of members into acts of at most
  10,000 under its one yes (7.6). `migrate` already writes acts of 500 (`COLLECT_CHUNK`,
  `engram/permission_cli.py:755`).

### 5.5 Storage

The ledger is `ENGRAM_HOME/.engram/permissions.db`, a SQLite file of its own (P15). Its path is fixed, not
configured, so no config edit can point a reader at another ledger. The daemon opens it with `mode=ro` and
`query_only`, as `Storage.open_read_only` opens a store (`engram/storage.py:128-161`). Only the person's commands and
the person's own engram servers write it, each write inside `BEGIN IMMEDIATE`.

```sql
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
  -- ledger_id, schema_version 1, owner, admins, gate, gate_raised
CREATE TABLE ledger_log(seq INTEGER PRIMARY KEY, at INTEGER NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
  actor TEXT NOT NULL, channel TEXT NOT NULL, under_grant TEXT, proposal_id TEXT, body TEXT NOT NULL,
  prev_digest TEXT NOT NULL, digest TEXT NOT NULL);
CREATE TABLE persons(id TEXT PRIMARY KEY, home TEXT NOT NULL UNIQUE, is_admin INTEGER NOT NULL, created_seq INTEGER NOT NULL,
  retired_seq INTEGER);
CREATE TABLE places(id TEXT PRIMARY KEY, is_root INTEGER NOT NULL, created_seq INTEGER NOT NULL, retired_seq INTEGER,
  pseudonym_salt BLOB NOT NULL);
CREATE TABLE place_parents(place TEXT NOT NULL, parent TEXT NOT NULL, added_seq INTEGER NOT NULL, PRIMARY KEY(place, parent));
CREATE TABLE place_stewards(place TEXT NOT NULL, person TEXT NOT NULL, added_seq INTEGER NOT NULL, removed_seq INTEGER);
CREATE TABLE agents(id TEXT PRIMARY KEY, acts_for TEXT NOT NULL, created_seq INTEGER NOT NULL, retired_seq INTEGER);
CREATE TABLE agent_places(agent TEXT NOT NULL, place TEXT NOT NULL, added_seq INTEGER NOT NULL, removed_seq INTEGER);
CREATE UNIQUE INDEX agent_places_one ON agent_places(agent) WHERE removed_seq IS NULL;  -- P31
CREATE TABLE stores(instance_id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, place TEXT NOT NULL,
  imprint_of TEXT, created_seq INTEGER NOT NULL);
CREATE TABLE groups(id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_seq INTEGER NOT NULL);
CREATE TABLE group_members(group_id TEXT NOT NULL, agent TEXT NOT NULL, added_seq INTEGER NOT NULL, removed_seq INTEGER);
CREATE TABLE collections(id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_seq INTEGER NOT NULL);
CREATE TABLE collection_members(collection TEXT NOT NULL, object TEXT NOT NULL, backing TEXT NOT NULL,
  added_seq INTEGER NOT NULL, added_by TEXT NOT NULL, removed_seq INTEGER, removed_by TEXT);
CREATE TABLE subjects(object TEXT NOT NULL, subject TEXT NOT NULL, added_seq INTEGER NOT NULL, added_by TEXT NOT NULL,
  self_claimed INTEGER NOT NULL, removed_seq INTEGER, removed_by TEXT);
CREATE TABLE copies(object TEXT PRIMARY KEY, source TEXT NOT NULL, added_seq INTEGER NOT NULL);  -- P25
CREATE TABLE lane_notes(object TEXT NOT NULL, lane TEXT NOT NULL, at INTEGER NOT NULL, seq INTEGER NOT NULL);
  -- lane is 'personal', 'work' or 'pending'
CREATE TABLE records(id TEXT PRIMARY KEY, layer TEXT NOT NULL, effect TEXT NOT NULL, selector TEXT NOT NULL,
  valid_from INTEGER NOT NULL, valid_until INTEGER, anchor INTEGER NOT NULL, backing TEXT NOT NULL, set_by TEXT NOT NULL,
  channel TEXT NOT NULL, under_grant TEXT, proposal_id TEXT, replaces TEXT, reason TEXT NOT NULL,
  created INTEGER NOT NULL, created_seq INTEGER NOT NULL, revoked INTEGER, revoked_by TEXT, revoke_reason TEXT,
  revoked_seq INTEGER);
CREATE TABLE permission_grants(id TEXT PRIMARY KEY, issuer TEXT NOT NULL, grantee TEXT NOT NULL, layer TEXT NOT NULL,
  parent_id TEXT, ops TEXT NOT NULL, envelope TEXT NOT NULL, max_days INTEGER NOT NULL, depth INTEGER NOT NULL,
  expires INTEGER NOT NULL, created INTEGER NOT NULL, created_seq INTEGER NOT NULL, revoked INTEGER, revoked_by TEXT,
  revoke_reason TEXT, revoked_seq INTEGER);
CREATE TABLE proposals(id TEXT PRIMARY KEY, by_agent TEXT NOT NULL, for_person TEXT NOT NULL, kind TEXT NOT NULL,
  body TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL, status TEXT NOT NULL,
  decided_seq INTEGER);
```

A proposal has no `words` column. Its words are generated from its body whenever they are shown (7.7).

The builder adds indexes as needed (section 18).

### 5.6 Versioning

- **The log is the source of truth.** Every write appends one `ledger_log` row, in the same transaction as its table
  row. The tables are projections of the log. `engram-permissions rebuild` replays the log into a fresh file and must
  get the same tables. It reads the log row by row and never holds it whole (15, "Memory").
- **The version is the sequence number.** A layer's version is the highest `seq` that touched it. Every decision
  cites the `seq` it read, so `state(seq)` replays it exactly.
- **A State reads what grows with the store when it is asked** (revision 7; Rio Grande's call). `state(seq)` holds
  the registry, the records, the grants and the proposals whole. It reads an object's subjects, lane notes,
  memberships and copies, and a log row's time, from the ledger when a decision asks, as they were at `seq`. It keeps
  at most 65,536 of those rows and 65,536 log times. So its memory doesn't grow with the store (15, "Memory").
  - **Rows read later read as at `seq`.** Of those four tables, only `subjects` and `collection_members` change in
    place, and only to set `removed_seq` and `removed_by` (`engram/permission_ledger.py:1026-1027`, `:1052-1054`). A
    State clears those when their seq is past its own, and leaves out a row added after it
    (`engram/permissions.py:390-399`, `:458-467`). `lane_notes` and `copies` are only appended. So a State asked
    after later writes decides as it would have at its own `seq` (PT10).
  - **A failed read** during a decision counts as an unreadable ledger: under `enforce` the daemon serves nothing for
    that frame (12.2), and the CLI refuses the command and says why.
  - A ledger that holds more than 16,384 records (5.4), which no write of this spec makes, also reads as unreadable:
    the State refuses to build, and says why.
- **`perform` holds one State at a time** (revision 7; Rio Grande's call). Today an act keeps the State it checked
  with while its gluing check builds a second, and a record act builds a third to find the record's layer
  (`engram/permission_ledger.py:340`, `:372`, `:377`). A signed proposal keeps the State it was checked with in the
  same way (`:405`, alive at `:445` and `:465`). An act, a signed one included, reads the record's layer from the
  ledger and drops its own State before the check builds the next (15, "Memory").
- **The log is hash-chained.** `digest = sha256(prev_digest + "\n" + canonical_json(entry))`, where the entry is the
  row without `prev_digest` and `digest`, and the first `prev_digest` is 64 zeros. `canonical_json` is the
  canonicalization named in 5.2. Anyone holding a published digest can detect a changed history. In step 1 records
  are not signed by a key; step 2 adds station signatures (section 14).
- **Places publish sealed rules.** A place's rules at a `seq` export as a `PlaceRules` artifact (section 9.4).

## 6. Combining permissions: the order, the meet, the decision

### 6.1 Uses

A use is `u = (a, P, o, h, x, p, t)`: requester agent a, acting in place P, on object o, held in copy h, with action
x, for purpose p, at time t. h is a copy ref (4.1), and H, the **holding place**, is h's place: for `store:<id>`, the
`place` of that store's `stores` row; for `imprint:<station>/<id>`, the place the station's ledger registers for it,
or, at a station with no ledger in step 1, the operator's home, as the imprints spec fixes it (its section 8). t is the
deciding party's clock, never the requester's (as the daemon does today, `engram/lighthouse_daemon.py:309-311`). 𝒰 is
the set of all uses (P34; revision 2 left h out, though 6.3 item 3 read it). A single `imprint` use also names k, the
store it keeps into, as a `store:` copy ref (the `remember` guard's own store, section 10). No layer reads k. Only
P36's test of who qualifies does (6.3; Rio Grande's call, the re-check's RC4).

No selector names h in this spec. h reaches a decision through the layers of `anc(H)` (6.3, item 3). The same ref
held in two houses is two uses, each with its own holding place, so a place's rules for the copies it holds (7.5)
apply to its copies only. A layer kept outside any ledger is the subset of 𝒰 that its own spec defines, and the meet
treats it like any other layer. The imprints spec's station ceiling is one: it allows uses of one copy h only (its
section 8), and h is now a coordinate of 𝒰.

For a layer L at ledger state σ, its **denotation** `⟦L⟧ ⊆ 𝒰`:

- consent layer: `⟦L⟧ = A_L \ D_L`, where `A_L` is the set of uses some effective allow record in L matches, and
  `D_L` the set some deny record matches;
- restriction layer: `⟦L⟧ = 𝒰 \ D_L`;
- a required consent layer that does not exist (an unregistered subject, an unknown place): `⟦L⟧ = ∅`;
- the **empty layer** ⊥, with `⟦⊥⟧ = ∅`, which `Req` holds for an object with no subject (6.3, item 1).

### 6.2 The order and the lattice

For sets of uses X and Y, **X allows no more than Y**, written `X ≤ Y`, when `X ⊆ Y`. `(𝒫(𝒰), ⊆)` is a complete
Boolean lattice. The meet is intersection, the join is union, the bottom (∅) refuses everything and the top (𝒰)
allows everything. Layers are ordered by their denotations. "Deny wins" is literal: inside a layer a matching deny
removes the use, and across layers the meet removes anything one layer refuses (P1).

ConnectionPolicy's most-specific-wins rule is not monotone in its rules, which is why the new layers don't use it
(test U1). Take two rules that agree in every dimension except two. Rule A allows with `publishers:
["urn:engram:*"]` (1 point, `engram/lighthouse_policy.py:78-83`) and `contexts: ["memory/technical"]` (2 points).
Rule D denies with `publishers: ["urn:engram:x"]` (2 points) and `contexts: ["memory/*"]` (1 point). For publisher x
in `memory/technical` both score the same, and deny wins the tie (`:146-152`). Narrow A's publishers to
`["urn:engram:x"]` and A scores higher, so the request is now allowed. Narrowing a selector widened the policy.

### 6.3 Required layers (P4)

`Req(u)` is the set of layers that must all allow u:

1. **Subjects.** For each subject s of o at t: the layer of `home(s)` if s is a person, or of s if s is a place.
   Consent. An object's subjects are its store's owner and its co-subjects, and, for a kept copy on the same ledger
   as its source, its source's subjects at t, read through `copies` (7.4). An object whose store has no
   `stores` row, or whose ref names no store (a placement with no `source_instance_id`), has no subject. Then `Req`
   holds ⊥ and the use is refused with `NO_LAYER` (P32). Every object that can be allowed has at least one subject.
2. **The requester's places.** The layer of every place in `anc(P)`: the place itself, its parents, and up to the
   county. Consent. This is the county's ceiling: no place can allow at P what an ancestor refuses at P.
3. **The holding place.** The layer of every place in `anc(H)`, where H is the place of the copy h that serves the
   use (6.1). Consent. A `store:` ref whose store has no `stores` row has no place, so this item adds a layer that
   doesn't exist, and the use is refused with `NO_LAYER`. `migrate` registers the published house for that reason
   (12.3, step 2).
4. **Legacy layers** while they exist: the publisher's and the receiver's ConnectionPolicy, each decided by its own
   evaluator on every request, never cached (section 12). Consent.
5. **The agent's restrictions.** a's own restriction layer. Anyone may refuse for itself.

A layer that appears twice counts once. A use is also refused if a is not registered or is retired, or is not in P
at t.

**The owner's own copies (P36; Andy's decision A6: "yes you can copy the full store").** Revision 6 required every
subject's consent layer for every use. So a memory with a recorded co-subject could not be imprinted, even into its
owner's own home, until that person said yes. P36 changes that. It is the one rule any revision of this spec has
widened. A use **qualifies** when all of these hold, where the owner is the owner of o's store (P12):
- the requester acts for the owner: `act(a)` is the owner's home;
- the use's place P and its holding place H are both inside the owner's home: `place:home/<owner>` dominates both;
- the use is an `imprint`, single or an imprint batch, and the copy it keeps is held inside the owner's home; or it
  is a bulk use (P33), named or counted, which by 6.4 shows nothing to any agent. For an imprint batch the copy it
  keeps is h. A single `imprint` is the `remember` guard's (section 10), and the copy it keeps is k, the store the
  guard writes into, which is not h: h is the copy the delivery came from (6.1). That store's place is its `stores`
  row's `place`. A store with no `stores` row has no place, and the use doesn't qualify (Rio Grande's call; the
  re-check's RC4). In the imprints spec, for a copy kept in the owner's home, these are all its step-1 uses: its
  requester `agent:station-imprints` acts for the operator, who is then the owner, in the operator's home (its D9).
  They are admission's imprint batches (its checks and calibration), its `read` batches for `trail-evaluation` and
  its counted bulk `imprint` on R(I), and the trail evaluation's `read` batches and its counted bulk `route` (6.4, its
  last paragraph).

**How a qualifying use is decided.** Each use in its `need` (6.4) is tested on its own object: the `recall` and
`read` an `imprint` needs, and the `recall` on every memory a road or trail names. It keeps its parent's a, P, h and
t. It qualifies when its parent does and the first two conditions hold for the owner of its own object's store. So a
memory that a road or trail names from another person's store, such as a memory of Jenn's store on one of Andy's
trails, is decided with every subject's layer as a consent layer, as before. A6 is Andy's answer about his own store
(Rio Grande's call; the re-check's RC4). In item 1 of a qualifying use the owner's home layer stays a consent layer.
Each other subject's layer is read as a **restriction layer**, `⟦L⟧ = 𝒰 \ D_L` (6.1). So in step 3 of 6.5 its
silence passes, a missing layer passes, and a deny in it refuses with `DENIED` at that layer. It keeps its place in
step 2's order and cites no record (step 5). Its dated denies still count for `until`, and its records' times for
the horizon (steps 6 and 7). Step 1 of 6.5 is unchanged: a retired co-subject's home still refuses with `RETIRED`, an
object with no subject with `NO_LAYER`, and one with more than 8 subjects with `BOUND`. Items 2 to 5 still apply.
A place co-subject that is also in `anc(P)` or `anc(H)` keeps its consent layer: items 2 and 3 require it as one,
and the layer counts once, as consent (Rio Grande's call; the re-check's RCS4).

**How `cited` shows it** (Rio Grande's call; the re-check's RCS1). A co-subject's layer read this way has its own
kind in `cited` (6.5) and in receipts (9.1): `co-subject`. Its verdict is `deny` when a deny matches, `missing` when
the layer doesn't exist, and `silent` otherwise, whatever allows it holds. Only `deny` fails. Its records are empty,
and its version is the layer's version, as every ledger layer's is (0 for a layer that doesn't exist). It is not
`restriction`, because a place's stewards see a `restriction` layer as that word, while a home's layer must show as
its person's pseudonym (9.2). It is not `consent`, because it neither cites nor needs an allow.

**Whom it reaches.** Every co-subject: one the owner or his agents recorded, one who claimed the memory
(`self_claimed`, 7.4), and the source's people that a kept copy carries (P25). So a copy the owner kept of someone
else's memory may be imprinted into his own home without that person's allow, but never against their deny. A
`remember` of delivered content (section 10) is an `imprint`. By an agent acting for the owner, kept in a store whose
`stores` row places it in his home, it qualifies, and the kept memory carries every subject.

**What it never covers.** A use that is neither an `imprint` nor a bulk use, such as any `recall`, `read`,
`inject_context` or `route` answer use, which names objects or shows content to an agent. A use whose requester
doesn't act for the owner, or whose P or H is outside his home. For all of these every subject's layer stays a
consent layer, so they still need every subject's yes. The copy carries every subject (P25, 7.4), so every later use
of it is decided by the same rules.

**Why this form** (Rio Grande's call, on A6). It is the narrowest rule that lets the owner copy his full store into
his own home and evaluate it there, as Andy decided. Nothing about another person reaches an agent, or leaves the
home, on the owner's yes alone. It overrides no one's no: a deny is a person's explicit refusal, P1 makes a deny win
literally, and the vision's principle 6 forbids picking a winner. In step 1 the CLI writes no other person's layer
(7.6), so a person co-subject's layer is empty or missing, and passes: Andy's full store copies into his own home, as
he decided. A place co-subject's layer can hold a deny in step 1, when the owner stewards that place, since the CLI
writes those layers (7.6), and that deny refuses (the re-check's RC1). P36 departs from the words of the vision's
principle 1 inside the owner's home (section 19).

### 6.4 Actions and their closure (P5)

Each action needs others. A use with action x is allowed only if every use in `need(u)` is in every required layer of
that use.

| Action | What it does | `need` |
|---|---|---|
| `recall` | Returns ids and digests | `recall` on o |
| `read` | Returns content to a program | `recall`, `read` on o |
| `inject_context` | Puts content into an agent's active context | `recall`, `read`, `inject_context` on o |
| `route` | Uses a road or trail as an edge | `route` on the road or trail, and the named memories' uses below |
| `imprint` | Keeps a copy as part of another store | `recall`, `read`, `imprint` on every object included, and, on a road or trail, the named memories' uses below |

**On a road or trail, every action names memories** (P35; the re-check's RS4). A road names its two endpoints, and
a trail its touches. A `read` of either returns those ids, and an `imprint` of a trail keeps the log rows that hold
them. So for every action x on a road or trail, `need(u)` also holds, with the same a, P, h, p and t:

- `recall` on every memory it names;
- `read` and `inject_context` on every memory whose content the answer shows, even one summary line.

Revision 2 had this for `route` only. Then a `recall`, `read` or `imprint` of a trail could name a memory its
audience may not recall, which P23 forbids. The imprints spec already meets the rule: it ships a log row only when
every target of the row ships (its section 6.2).

This matches today's receiver: `recall` before asking, and all three before reading and delivering
(`engram/neighbors.py:82`, `:120`, `:138`). The trail spec (revision 9) uses `route` in place of its work-lane rule,
and its section 8 already shows a stop's summary only when `inject_context` is allowed on that memory, naming the id
alone otherwise. Its "separate owner opt-in to route publication" is a `route` record. Its minimum published support
of 3 stays in the trail spec. The imprints spec uses `imprint` on the memories it keeps, and on the roads and trails
derivable from the session ids and log rows it keeps (its D7 and D10).

**Bounds.** A use on one object reads at most 43 layers (8 subjects, 16 requester places, 16 holding places, 2
legacy, 1 restriction). A use on a road or trail is one decision for the road or trail and one for each memory it
names.

- **Answer uses name at most 32 memories.** A use on a road or trail that is not a bulk use (below) names at most 32
  memories. One that names more is refused with `BOUND`. The bound limits what one answer can name to an agent, and
  what one decision costs. The trail spec's answers must fit.
  - **One use per edge.** A `route` use is one road or trail used as one edge. An answer that walks several edges is
    several `route` uses, each with its own decision and receipt (9.1). So the 32 bounds what one road or trail
    names. A road names its two endpoints. A trail names its touches, so a trail of more than 32 touches can't be the
    object of an answer use. The trail spec's answers fit: a route of at most 64 stops walks at most 63 edges (its
    6.5), and each edge it takes across a store boundary is a road (its section 8).
  - The `read` and `inject_context` of `need` fall on each edge's endpoints whose content the answer shows.
  - Rio Grande's call, from the interface pass.
- **An `imprint` batch** is a bulk use (below) of at most 512 objects, whose receipt names them (9.1). The imprints
  spec splits larger imprints into batches.
- A road or trail whose subjects would number more than 8 is refused with `BOUND`.

A use is allowed only when every one of its decisions is. Its refusal is the first failing decision: the road or
trail first, then memories in ref order.

**Bulk uses** (P33; Rio Grande's call, the re-check's RMF1, option (a)). Some uses show nothing to any agent, and only
counts, rates and digests leave the deciding party. The trail evaluation on an imprint is one. It reads memory text
inside the run, routes A* over every road and trail it derives (up to 10,000 expansions per search, over trails of up
to 512 touches), and reports counts and rates only (trail spec section 7, steps 4, 7 and 10; imprints spec section 8,
"The decision"). Decided road by road under the bound of 32, it would be refused for a reason that protects no one,
and this spec's `explain` would refuse what the imprints spec's check allows. So such a use may be decided as one
**bulk use**

`U = (a, P, O, h, x, p, t)`, where O is a finite set of objects held in one copy h.

- **Need.** `need(U)` is the union over o ∈ O of `need(a, P, o, h, x, p, t)`, by the table and the named-memory rule
  above. So a bulk `route` over trails needs `recall` on every memory that any of them names.
- **Allowed** when every use in `need(U)` is in every required layer of that use. That is exactly when every
  per-object use would be allowed, except that the bound of 32 named memories doesn't apply. Nothing else is
  waived: 43 layers per object, 8 subjects per road or trail.
- **Refused** when any per-object decision is. The refusal is the first failing per-object decision, objects in ref
  order. It holds the code, layer and action only, never the object (P23). What each reader sees of it is 9.2. A U
  larger than **Size** below allows, in objects or in the memories its roads and trails name, is refused with `BOUND`
  once its requester and places pass, before any object is decided (6.5, step 1).
- **The decision.** `cited` holds, for each (layer, action), every distinct record cited for it across O, sorted by
  id. `until` and `horizon` are the earliest across O, and null when every one is null. `decide` gives one result for
  U, and F1 fixes it.
- **Which uses may be bulk.** Only a use whose answer names no object and shows no content to any agent, and from
  which only counts, rates and digests leave the deciding party, as the spec that runs it says. An imprint batch
  qualifies: what it keeps stays in the copy h, and nothing of it reaches an agent. If the same run shows an object
  to an agent, that showing is an ordinary use, decided per object under the bound of 32. A `remember` of delivered
  content (section 10) is never bulk: it is decided per item.
- **Size.** At most 512 objects when the receipt names them, such as an imprint batch. At most 100,000 when the
  deciding party derives the objects and never names them, such as the roads and trails derived from an imprint.
  100,000 is the most memories one collection holds (5.4), and so the most an imprint holds (imprints spec D36). A
  larger set is several bulk uses, each with its own receipt.
  - **Named memories.** The roads and trails of one bulk use, named or counted, name at most 100,000 distinct
    memories in all, by the same bound (Rio Grande's call, from the check of revision 4, BS2). A set that names more
    is split into several bulk uses in the same way. Without this bound, 100,000 derived trails of up to 512 touches
    (the trail spec's section 4) could name 51.2 million memories, far past the Pi budget below. The imprints spec's
    uses always fit: every memory a road or trail of its R(I) names is a memory the imprint holds (its section 8).
- **One receipt** per bulk use (9.1).
- **How it is computed.** Objects that agree on every attribute the pre-filtered records read (6.5) get the same
  decision: kind, store, layer, lane history, collection memberships, whether a record lists them in `memories`, and
  subjects. So the evaluator may decide each such group once. The imprints spec's finite check is this shortcut:
  every object of one kind in an imprint matches the same records (its section 8, "A finite check").
- **Its Pi budget.** With or without grouping, one bulk decision at the largest size must fit the time and memory
  budgets in section 15, which U24 measures. It keeps, per object, only the object's subjects and which actions it
  decided, and it keeps the earliest effective end as it goes (revision 7). `explain` on a bulk use runs the same
  decision. **Size** fixes the largest: at most 100,000 objects, each needing at most three actions (`imprint`'s
  `recall`, `read` and `imprint`), and at most 100,000 named memories, each needing `recall`. That is at most 400,000
  (object, action) pairs.

So the imprints spec's `Need(trail-evaluation)` is bulk uses with h = `imprint:<station peer id>/<imprint id>`:
`read` on the shipped memories, in batches of 512 (its `need` adds `recall`), and one `route` on all the roads and
trails derived from them (its `need` adds `recall` on every memory they name). Its `Need(admission)` is imprint
batches on the memories and, with `route`, one counted bulk `imprint` on the roads and trails derivable from the
package's session ids and log rows (that spec's R(I)), and `read` batches on the memories for `trail-evaluation`,
since admission counts R(I) and deriving it reads memory text (that spec's sections 8 and 10; the cross-check's
XS2). This spec's `decide` and `explain` then agree with the station's check, and F1 holds for both. Each of these is
a bulk use inside the owner's home when the copy is kept there, so P36 (6.3) decides a carried co-subject's layer in
all of them.

### 6.5 The decision

```
decide(u, σ) → {allowed, at, ledger_seq, action, cited: [{layer, kind, action, verdict, record}],
                refusal: {code, layer, action} | null, until, horizon}
```

1. **Before any layer.** Refuse with `UNKNOWN_REQUESTER` if a is not registered, is retired, or is not in P at t. Then
   with `RETIRED` if P, a place in `anc(P)` or `anc(H)`, or the home of a subject is retired. Then with `NO_LAYER` if
   o has no subject. Then with `BOUND` if a bound of 6.4 would be passed, or if o would have more than 8 subjects,
   which a kept copy can reach through its source (7.4).
   **For a bulk use U** (6.4), the tests on a, P, `anc(P)` and `anc(H)` run once, and then U's size bounds (its
   objects, and the memories its roads and trails name), before any object. Then each o ∈ O is decided in ref
   order, and its own tests here (a retired subject's home, no subject, more than 8 subjects) come first in its
   decision. So any o ∈ O with no subject refuses U with `NO_LAYER`, and any o ∈ O
   with more than 8 subjects with `BOUND`, unless an earlier object failed first.
2. **The order.** Compute `Req(u)` and sort it: subjects by id, then the requester's places by id, then the holding
   places by id, then legacy layers, then the restriction layer. Actions take `need`'s order: `recall`, `read`,
   `inject_context`, `route`, `imprint`.
3. **Verdicts.** For each layer L in that order, and within L each action y in `need(u)`, the verdict is `allow` (an
   effective allow matches and no deny does), `deny` (a deny matches), `silent` (no allow matches), or `missing` (L
   doesn't exist). In a restriction layer, `silent` passes.
4. **`allowed`** is true when no verdict fails.
5. **Citations.** For each consent layer L and each action y, the decision cites one allowing record: among the
   effective allows in L that match the use with action y, the one whose effective end is latest, then the smallest
   id. A record's **effective end** is the earliest of its own `valid_until`, the `valid_until` of every record in its
   `replaces` chain, the `expires` of every grant in its grant chain, and, when it matched through a grant-backed
   membership, the `expires` of every grant in that membership's chain. A co-subject's layer that P36 reads as a
   restriction layer is not a consent layer here: it shows in `cited` with kind `co-subject` and no record (6.3).
6. **`until`** is the earliest of: the effective end of every cited record; and the `valid_from` of every deny in a
   required layer whose `valid_from` is after t and which would match some use in `need(u)` at that `valid_from`,
   with σ fixed. It is a lower bound on when the ledger stops allowing the use: another record may carry it further.
   It is null when every term is null. **`until` and the horizon cover ledger layers only** (P30). A legacy layer
   can end a use sooner: each ConnectionPolicy rule carries `validFrom` and `validUntil`, and is active only between
   them (`engram/lighthouse_policy.py:138-143`). Legacy layers are decided afresh on every request (6.3, item 4), so
   a legacy end takes effect at the next request. The annotation shows this `until` (section 11).
7. **`horizon`** is the earliest time after t at which any term the decision read could change with no ledger write.
   It is the earliest of: every `valid_from` and `valid_until` after t of every record in a required ledger layer that
   is effective at σ or in the `replaces` chain of one; and every `expires` after t of a grant in any chain behind a
   record or membership the decision read. It is null when there is none. Every term of `until` is a term of the
   horizon, so `horizon ≤ until` whenever both exist. Legacy layers are outside it, because they are decided afresh
   on every request (6.3, item 4).
8. **`refusal`** is the first failing (layer, action) in the order of step 2, with one code:

| Code | When |
|---|---|
| `UNKNOWN_REQUESTER`, `RETIRED`, `NO_LAYER`, `BOUND` | Step 1 above, in that order. `NO_LAYER` also when the failing verdict is `missing`. |
| `DENIED` | A deny in L matches the use with action y. |
| `EXPIRED` | No effective allow matches, and some *candidate* has an effective end ≤ t. |
| `GRANT_INVALID` | Else, some candidate's grant chain is invalid at t for a reason other than expiry: a link revoked, more than 3 links, or the root issuer no longer a steward. |
| `NOT_YET` | Else, some candidate, or a record in its `replaces` chain, has `valid_from` > t. |
| `NO_ALLOW` | Else. |
| `LEGACY_DENY` | A legacy layer refuses. |

A **candidate** is an unrevoked allow in L that matches the use by rules 2 and 3 of 5.3 and by the selector parts of
rules 4 and 5, with every validity interval and every grant's validity ignored. A revoked allow is never a candidate,
so a use refused after a revocation gets `NO_ALLOW`. A removed membership is never counted, as a revoked allow is
never a candidate.

**A candidate's grant chains** (the re-check's RS7; Rio Grande's call). They are its own chain, when it is
grant-backed, and the chain of every grant-backed membership it matched the use through. `EXPIRED` and
`GRANT_INVALID` read all of them, as a candidate's effective end already does (step 5). So in use 10 of section 13,
a read of m4 after Andy revokes G1, and before G1's expiry, is refused with `GRANT_INVALID` at `place:home/andy`,
action `recall`: R1′ is a candidate only through G1's membership of m4, and G1 is revoked. From 2026-11-30, G1's
expiry, the same read gets `EXPIRED`, which the table checks first.

**How it is computed.** The evaluator first selects, per layer, the records whose audience, `requesters`, `actions`
and `purposes` can match the requester, its place, the action and the purpose. Only those are matched against the
object. The result depends only on u (h included, and k for a single `imprint`), σ and t. A bulk use's result
depends only on U, σ and t (6.4).
Conforming implementations agree on `allowed`, `cited`, `refusal`, `until` and `horizon` for both (test F1).

### 6.6 Proofs

Each proof is short because each structure is a set and each combination is an intersection.

**L1. The meet only narrows.** If `ℛ ⊆ ℛ′` then `⋂ℛ′ ⊆ ⋂ℛ`: a use in every layer of ℛ′ is in every layer of ℛ.
So adding a party to `Req(u)`, whether a subject, a place, a legacy policy or an agent's restriction, can only
refuse more. A missing consent layer and ⊥ are ∅, so they refuse. ∎

**L2. Nesting only narrows.** For a place X and an ancestor Z, Z's layer is in `Req(u)` for every use at X (6.3,
item 2). So by L1 what is allowed at X is within what Z allows at X: "A permission passes down to a smaller place only
by narrowing." A person's allow to `place:Z` reaches a use only when Z dominates both the use's place and the
requester's acts-for place (P3), so it reaches no place that has a path around Z. Dominance of an existing place
never grows (4.3), because a root never gains a parent (P26). ∎

**L3. The narrowing ops only narrow.** The narrowing ops (7.2) each shrink `A_L`, grow `D_L` or grow `Req`. In a
consent layer they are: revoking, shortening or narrowing an allow; adding a deny; adding a subject; and removing a
collection member. Shortening and narrowing write a replacement R′ of R, and rule 4 of 5.3 checks every record in
R′'s chain by selector and by validity interval. So `match(R′) ⊆ match(R)` at every decision, whatever R′'s fields
say and whatever changes later in the registry. Removing a member removes allow matches only, because denies read
every membership row since their anchor. Then `A′ ⊆ A` and `D′ ⊇ D`, so `A′ \ D′ ⊆ A \ D`. None of these ops may
touch a deny in a consent layer (P27), so none shrinks `D_L`. An agent that revokes its own restriction only returns
to what the consent layers allow. ∎

**L4. Delegation and backing.** For a person π with layer L:

- `Sig⁺_π` is the set of uses matched by allows π wrote or signed, reading collections through person-backed
  memberships only;
- `Sig⁻_π` is the set of uses matched by the denies π wrote or signed, as π last left them;
- `Env_π(t)` is the union of the envelopes of π's valid root grants at t.

Then at every state, `⟦L⟧ ⊆ (Sig⁺_π ∪ Env_π(t)) \ Sig⁻_π`.

*Proof.* Allows first. Take an effective allow r and a use it matches.

- If r is backed by grant g_k, its chain g_1 … g_k is valid at t, g_1 is a root by π, and rule 5 keeps the use
  inside `env(g_1)`.
- If r is person-backed, its `replaces` chain ends in a record π wrote or signed (7.3), and rule 4 keeps the use
  inside that record's matches, by selector and by time. That use is in `Sig⁺_π` unless r matched it through a
  grant-backed membership. Then 5.3 keeps it inside that grant chain's envelopes, so inside `Env_π(t)`.

So `A_L ⊆ Sig⁺_π ∪ Env_π(t)`. Denies next. Only a steward of L, here π alone, may revoke, shorten or narrow a deny in
L (P27, 7.1). Every deny an agent writes is person-backed and outlives its grant (7.3). So every deny π left stays,
and `D_L ⊇ Sig⁻_π`. Then `⟦L⟧ = A_L \ D_L ⊆ (Sig⁺_π ∪ Env_π(t)) \ Sig⁻_π`. ∎

*So* no sequence of agent acts, mistaken or not, can make a person's layer allow something the person did not sign,
or undo something the person denied.

**L5. Changes nobody checked only narrow.**

- A lane move cannot create an allow match. An allow needs the lane to hold throughout, and a pending move counts as
  neither lane. A lane move cannot remove a deny match either, because a deny matches any time since its anchor, and
  a pending move counts as both lanes.
- Removing a collection, group or place member cannot remove a deny match, and can only remove allow matches.
- Adding a parent edge to a place that already has one only shrinks `dom` and grows `anc` (4.3). A root never gains
  one (P26).
- A memory an agent writes into a lane or store joins no outside-home allow of a home layer, because those reach
  memories only by listed ids and collections (P28). Adding it to a collection is a checked widening (7.1).

Every other registry change that could widen is in the table of 7.6. In step 1 each needs the ledger owner's
terminal yes. Two are trusted rather than checked, and the person is told so when they say yes: who a place's
stewards register as acting for the place, and whom they put in it (5.2, 7.6). ∎

**L6. Subjects and derived objects.** Adding a subject adds a consent layer to `Req` (L1). A road's or trail's
subjects are the union of its sources' subjects and its store's owner (P24). A kept copy's subjects include all of
its source's when it is made, and on one ledger all of its source's at every decision (P25, 7.4). Every use of a road
or trail, whatever its action, needs `recall` on each memory it names, and `read` and `inject_context` on each memory
whose content it shows (6.4, P35). A bulk use needs every per-object use in it (P33), so waiving the bound of 32
changes no verdict, only which uses may be asked for at once. So no use of a road or trail names or shows what its
memories don't allow, and a copy never leaves its source's people behind. ∎

**L7. The closure only narrows.** `need(u) ∋ u`, so an allowed u is in every required layer. ∎

**L8. The horizon.** With σ fixed, `decide(u, σ, t′) = decide(u, σ, t)` for every t′ in `[t, horizon)`.

*Proof.* At fixed σ, a decision depends on time only through:

- record intervals (rules 1 and 4);
- grant expiries (rule 5, and grant-backed memberships);
- membership and lane history up to t.

With no write, no note or membership row is added. So "held throughout `[…, t′]`" and "at any time in `[anchor, t′]`"
have the same truth as at t. Every interval endpoint and expiry that could flip a rule between t and t′ is a term of
the horizon (6.5, step 7). ∎ So a cache that ends at the horizon never serves a stale decision.

**P36 and the proofs** (revision 7). For a qualifying use, P36 reads a co-subject's layer as a restriction layer
(6.3). L1, L2, L3, L5, L7 and L8 hold as written: that layer is still a term of the meet, and adding a co-subject
still only narrows, since `𝒰 \ D_L` only removes uses. The second half of L4 holds: no agent act removes a
co-subject's deny, and P36 keeps every deny. Its first half doesn't bound a qualifying use: there a co-subject's
layer passes uses they never signed, by Andy's decision (A6), never by an agent's act. L6 holds for every use P36
doesn't cover, and a copy still carries its source's people.

## 7. Who may set what

### 7.1 The table

| Act on a layer | The layer's stewards (the person, for a home) | An agent under the stewards' grant | An agent on its own |
|---|---|---|---|
| Add an allow | yes | `share`, within the envelope | a proposal |
| Add a deny | yes | `deny`, within the envelope | only in its own restriction layer |
| Revoke an allow | yes | `withdraw`, for allows that meet the envelope | grant-backed allows it wrote itself |
| Shorten an allow's `valid_until` | yes | `shorten` | a proposal |
| Narrow an allow's selector (audience included) | yes | `narrow` | a proposal |
| Revoke, shorten or narrow a deny (P27) | yes | a proposal | a proposal; its own restriction denies, yes |
| Add a collection member | yes | `collect`, when every allow that names the collection lies within the envelope | a proposal |
| Remove a collection member | yes | `uncollect` | a proposal |
| Add a co-subject | yes | yes | yes, when it acts for the store's owner (P12) |
| Remove a co-subject | see 7.4 | no | no |
| Change a group | its person | no | a proposal |
| Make a grant | yes (a root) | a child, when its grant has depth left | no |
| Give up a grant | | the grantee, of its own grant (7.2) | |

A proposal records the full change. The person signs or declines it with `engram-permissions sign <id>` or
`decline <id>`, one at a time, with no batch action (as spec A's direct confirmation). An unsigned proposal expires
after 7 days (P11). A signed proposal writes a person-backed record with its `proposal_id`. 7.7 says how its words
are made.

### 7.2 Grants (P10)

A grant is a row in `permission_grants`. It follows the station grants' rules:

- **Root.** A steward of the layer (the person, for a home) issues it to an agent that acts for them. `ops` ⊆
  {`share`, `deny`, `withdraw`, `shorten`, `narrow`, `collect`, `uncollect`}. `envelope` is one selector. `max_days`
  bounds the lifetime of each record made under it. `depth` is 0 to 2, so a chain has at most 3 links, and the grant
  lasts at most 720 hours (spec A's no-charter defaults, `peer/superyak_peer/grants.py:54-58`).
- **Child.** An agent holding a grant with depth left may issue a child to another agent acting for the same person.
  The child is a subset in every field: ops ⊆, envelope ⊆ (checked per dimension: each audience entry within a parent
  entry, each list a subset, `"*"` only where the parent has `"*"`), `max_days` ≤, `depth` <, `expires` ≤.
- **Validity** at t is a walk from the grant to its root. Every link must be unrevoked and unexpired, the chain at
  most 3 links, and the root's issuer still a steward of the layer. This is `_grant_validity`'s walk
  (`peer/superyak_peer/grants.py:95-122`). Nothing cascades: a revocation anywhere above takes effect at the next
  decision.
- **Revoking.** The issuer, any issuer above it, or the layer's stewards may revoke a grant. This follows
  `_may_revoke`, which allows the issuer of any link in the chain and the owner of a target ship
  (`peer/superyak_peer/grants.py:284-287`); here the layer's stewards play the owner's part. **New here:** the
  grantee may also give its own grant up. `_may_revoke` has no such case. A revoked grant is never valid again.
- **No grant by default.** An agent has none until a person makes one.

**Which records the ops touch** (P27). In a consent layer, `withdraw`, `shorten` and `narrow` apply only to allow
records whose selectors meet the envelope (their intersection is not empty), and `uncollect` only to memberships
whose object meets it. They never touch a deny there: removing, shortening or narrowing a deny shrinks `D_L`, which
widens `⟦L⟧`. An agent's attempt on a deny is filed as a proposal. `deny` adds a deny within the envelope. In its own
restriction layer an agent needs no grant. An envelope of all `"*"` gives full narrowing power over allows.

### 7.3 Backing (P9)

- A record a steward writes or signs is **person-backed**. So is every record `migrate` writes after the person's
  yes (12.3).
- A narrowing replacement keeps the backing of the record it replaces. So when Andy's agent shortens Andy's share and
  Andy later revokes the agent's grant, the shortened share stays.
- **A deny an agent writes under a grant is person-backed.** If it died with its grant, the grant's end would widen
  the layer. It stays until a steward removes it (P27).
- An allow made by `share`, and a membership made by `collect`, are **grant-backed** by the grant used. They stop
  counting the moment that grant's chain is invalid.

### 7.4 Overlapping ownership

A memory about two people needs both yeses. Its subjects are its store's owner by default, plus any co-subjects in
`subjects`.

- **Adding** a co-subject only narrows (L1). The person, an agent acting for the store's owner, or the co-subject
  (`self_claimed`) may add one. A detector that finds names may add co-subjects too. It can only narrow, so step 4
  may build one.
- **Removing** one could widen. The store's owner may remove a co-subject that they or their agents added. A
  co-subject who claimed the memory themselves, or one carried by a kept copy, can be removed only by themselves.
- **A self-claim is shown to the owner.** The owner's use list (9.3) shows "Jenn claimed m3 on 2026-11-03". A claim
  the owner disputes is a conflict that goes to a person; the claim holds until it is resolved, since it only
  narrows. In step 1 only the ledger owner writes the ledger (7.6), so no one else can claim.
- A co-subject who can't say yes on this ledger refuses: `NO_ALLOW` if they are registered with an empty home layer,
  `NO_LAYER` if not. The memory doesn't move until they say yes on a ledger that holds their home.
  - **One exception, on Andy's decision: the owner's own copy inside his home** (P36, 6.3). For the owner's `imprint`
    there, and for a bulk use there that shows nothing to any agent, a co-subject's layer is read as a restriction
    layer. Their silence, or a missing layer, passes, and their deny refuses. The copy carries them (below), so it
    shows nothing to an agent, and moves nowhere else, without their yes.
- The person whose allow was blocked by a co-subject sees "needs Jenn's yes" in their use list (9.3). In step 1 the
  system sends Jenn nothing.

**Kept copies** (P25). A kept copy is a memory written into a store from another memory's content:

- by `remember` under an allowed `imprint` (section 10);
- by an imprint (the imprints spec);
- by genome sync, which copies genome-core episodes into an instance and records their origin (`engram/federation.py:155`).

In the same act, the ledger writes a `copies` row (the copy's ref, the source's ref). It also adds every subject of
the source at that moment, as 6.3, item 1 reads them (so through `copies` too, when the source is itself a copy),
other than the copy's own default subject, as a co-subject of the copy, with `added_by` = `copy:<source ref>`. The
build does this (`subjects_of` at `engram/permission_ledger.py:511` on `permissions-core`). The ledger write comes
first. If the store write then fails, the extra rows only narrow. A copy that would have more than 8 subjects is
refused. The copy's people are then its source's people plus its keeper, so public health's copy of Andy's m1 can't
reach parks without Andy's yes.

**Subjects recorded on the source later** (the re-check's RS5; Rio Grande's call). Adding a subject is meant to
narrow every use, copies included. So on the ledger that holds both the copy and its source, a copy's subjects at a
decision are its own (its store's owner and its co-subjects) plus its source's subjects at that decision, read
through `copies` (6.3, item 1). A source may be a copy itself, so the read follows `copies` up to 4 links. A copy
whose chain would be longer is refused when it is made, so no decision meets one. The bound of 8 subjects applies to
the union: a decision whose object would have more than 8 refuses with `BOUND`, which only narrows. Adding a subject
to a source is never refused because of its copies. So if Andy adds Jenn as m3's co-subject after `ph-coordinator`
kept a copy of m3, the copy needs Jenn's yes from the next decision on, with no write to the copy. Removing a subject
from the source leaves the copy's carried row, which only that subject may remove (above).

**A copy held on another ledger**, such as an imprint at a station, or a copy kept on a machine whose ledger doesn't
hold the source, has only the subjects carried when it was made. It carries exactly its source's subjects at that
moment, as 6.3, item 1 reads them on the source's ledger, through `copies` too, less its own default subject. A
source that is itself a kept copy has the subjects of its own sources, so a copy made from it carries them (the
re-check's RC2). It learns of a subject recorded at the source later only in step 2, when such changes go to every
holder with a receipt, as withdrawal notices do (section 14, step 2). Until then the owner can withdraw it, and the
imprints spec's withdrawal acts at once (its section 12). An imprint's carried subjects are its `imprint_subjects`
rows (imprints spec D43): one per subject of that set other than the owner, at the plan. That spec ships a memory
with a recorded co-subject only in a copy kept in the owner's home, with its co-subjects carried. It keeps the memory
at home otherwise, and also when a co-subject's layer on the owner's ledger denies a use the imprint needs, since the
station can't read that deny (its D27 and `denied(m)`, revision 7). As committed in `c795c59`, its `cosubjects(m)`
read `subjects` rows alone (its section 5.2), and so missed a memory's subjects through `copies`. Its revision after
the re-check must read the set as this paragraph says (section 19).

An imprint keeps its source's refs, `mem:<source instance id>/…` (imprints spec D11 keeps memory ids, and its
objects are the owner's own refs). So its memories' subjects are their source's. The imprint store's `stores` row
carries `imprint_of`, and its own owner is never their default subject. A use of an imprint's memory names the
imprint as its copy, h = `imprint:<station peer id>/<imprint id>` (4.1, 6.1). The same ref used at home is a
different use, with h = `store:<source instance id>`.

### 7.5 What places and the county set

A place's stewards set its layer: its own rules for uses at it and its sub-places, and for the copies it holds. The
county is a root place. Its layer is the ceiling for everything under it (L2). A place's rules can refuse what a
person allowed. They never widen it, because the person's layer is always in `Req` (6.3, item 1). A place's stewards,
and the stewards of places that dominate it, also decide which agents act for it and work in it (4.4). A person's
allow to that place trusts them with that, and says so (7.6).

### 7.6 The person's yes (P20)

**Whose yes.** In step 1 the yes belongs to the ledger owner, `meta.owner`, the person who ran `init`. The CLI acts
as that person and no other. No command takes an argument naming who is acting. The CLI writes only the owner's home
layer, the layers of places the owner stewards, and the registry acts the owner may make (4.4). No other person's
layer can be written on this ledger in step 1, so another person stays at `NO_ALLOW` or `NO_LAYER` (7.4).

**How.** A command that writes prints the change in words and a 6-character code from `os.urandom`, then reads the
code from `/dev/tty`. It refuses without a terminal. Its channel is `terminal`. Every write the CLI makes needs the
yes.

**Which acts.** These acts can widen. Each needs the yes, and the MCP tools can make none of them. An agent's tool
call for one files a proposal.

| Act | Why it can widen |
|---|---|
| Write a person-backed allow (`allow`, or `sign` of a proposal) | adds to `A_L` |
| Revoke, shorten or narrow a deny in a consent layer | shrinks `D_L` (P27) |
| Make a root grant | lets agents add allows inside its envelope |
| Add a person-backed collection member | adds a memory to every allow that names the collection |
| Change a group | adds an agent to every allow that names the group |
| Register an agent | sets `act(a)`, which allows to places read (5.2) |
| Put an agent in a place | sets where it works |
| Add a steward | a steward writes the place's layer and decides who acts there |
| Register a place, or add a parent edge | changes `dom` and `anc` |
| Register a store | sets the default subject of its memories (P12) |
| Remove a co-subject | drops a layer from `Req` |
| Move the gate (12.3) | `off` drops every check this spec adds |
| `migrate` | writes person-backed allows and memberships |

For an allow to `place:Z`, the words name who Z's people are. For example: "Share collection
andy/medical-history with place:la-county/public-health, for care-coordination, until 2027-01-31. Agents that act
for a place Public Health dominates, working there, may use it. Public Health's stewards, and LA County's above it,
decide which agents those are."

**Known limits.** The person and their agents share one Unix account, so this narrows mistakes, not malice. An agent
that fakes a terminal and runs `sign` is acting against the law, not by mistake. `engram/CLAUDE.md` gains the rule
that agents never run, for the person, any `engram-permissions` command that writes, such as `sign`, `allow`,
`grant`, `migrate` or `gate` (section 16). Every such command needs the yes (above). `engram/CLAUDE.md` has no such
rule today. The daemon's frames name
their `receiver` without authentication, so any process under that account can claim to be any registered agent.
Step 2 moves every outside-home yes to the browser, and requesters authenticate as station ships.

### 7.7 Proposal words (P11)

The ledger generates a proposal's sentence from its body each time it is shown, by one fixed template per kind. It
never takes words from the agent. The agent's reason, kept in the body, is shown separately and labelled as the
agent's. `sign` prints
the sentence, then the full change: the selector in canonical JSON, `valid_from`, `valid_until`, the layer, and for a
replacement the record it replaces. Only then does it ask for the code.

## 8. Overlaps between places: the gluing check

Places nest in a directed acyclic graph. For a place X, read "the uses at X" as the uses whose requester acts in X.
A joint place J has parents `Q_1 … Q_n`, n ≥ 2. Each parent's chain gives a local section over J:

- `s_i = ⋂_{Z ∈ anc(Q_i)} ⟦Z⟧`, restricted to the uses at J: what `Q_i`'s chain allows at J;
- `own(J) = ⟦J⟧` at J: what J's own rules ask for.

The sections **glue** on what J asks for when they agree there: `s_i ∩ own(J) = s_k ∩ own(J)` for all i and k. The
**disagreement** is

`Δ(J) = own(J) ∩ ( ⋃_i s_i \ ⋂_i s_i )`

the uses J asks for that some parent's chain allows and another's refuses (P16).

**In sheaf terms.** Give the places the Alexandrov topology of the DAG: an open set is a down-set, a set that holds
every place below each place it holds. Each parent `Q_i` has the open set `↓Q_i`, and J lies in their overlap
`⋂_i ↓Q_i`. Assign to an open set U the set of all subsets of the uses at places in U, with restriction by
intersection. That is a sheaf of sets. `Q_i`'s chain gives a section over `↓Q_i`, and `s_i` is its restriction to
`↓J`, read at J. The sections are compatible at J on what J asks for exactly when `Δ(J) = ∅`. That is the whole
claim. J's parents are not a cover of J.

- **When Δ is empty**, nothing is reported.
- **When Δ is not empty**, the uses at J stay at the meet, `own(J) ∩ ⋂_i s_i`. Deny holds, and the system never picks
  a side. It shows Δ to the stewards of J and of every parent whose chain refuses part of it, in words: "Parks and
  Recreation allows read in Summer Wellness for program-operations; Public Health does not. Until one of you changes
  your rules, Summer Wellness may only recall." A person resolves it by changing their place's rules.
- **Not a disagreement:** a place refusing what a person allowed (refusing is allowed); one person's yes blocked by a
  co-subject (7.4); a part of a place's rules that its parents don't allow. That last one is reported to the place's
  stewards as an **ineffective part**:
  - at a place X with one parent: `own(X) \ ⋂_{Z ∈ anc(X), Z ≠ X} ⟦Z⟧`;
  - at a joint place J: `own(J) \ ⋃_i s_i`, what J asks for that no parent's chain allows. Δ(J) covers what some
    allow and some refuse.

The meet decides every use, whatever the check reports. The check only tells people.

**How it is computed.** The check uses boxes. A box is a product of one set per dimension: requester place,
requester agent, kind, store, layer, lane, memory, action, purpose, time. That is 10 dimensions. Every dimension
except time is a finite or cofinite set of strings. Time is a finite union of half-open integer intervals. Each
dimension is a Boolean algebra, so boxes support intersection, emptiness (some dimension empty), and difference
(`B \ C` is at most 10 disjoint boxes). The copy h of a use (6.1) is not a dimension: no selector names it, and the
sections compare parents' chains, which never hold the holding place's layers.

At the ledger's current state, every entry becomes a finite set:

- **Audience entries.** These become sets of registered places and agents. An allow's `place:Z` is one box, with
  places `{X : Z ∈ dom(X)}` and agents `{a : Z ∈ dom(act(a))}`. A deny's `place:Z` is two boxes, one by the place's
  ancestry and one by the agent's acts-for ancestry and placement history. `self` and group entries are one box each,
  read as 5.2 reads them. `commons` is the full set. For the uses at J, the requester-place dimension is `{J}`.
- **Collections.** These expand into their members, because a memory can be in many collections and so "collection"
  is not a coordinate of a use. An allow's collection becomes its effective members. A person-backed member is one
  memory ref. A grant-backed member is that ref, in a box intersected with its chain's envelopes. A deny's collection
  becomes every member since its anchor. The `memories` dimension is then the record's `memories` intersected with
  its collections' members.
- **Store, layer and lane.** These stay dimensions, read as attributes of a ref. A lane is read at its latest note: a
  pending note reads as no lane for an allow and as both lanes for a deny.

A record is a union of at most `64 × (1 + k)` boxes, where k is the number of distinct grant chains behind its
grant-backed members: up to 64 audience boxes, each split once for its person-backed members and once per chain. A
layer is the union of its allow boxes minus the union of its deny boxes.

**What it gets right.** On realizable points, at the current state, with no lane history, box membership equals
membership by 5.3, so the box Δ equals the real Δ. The check may over-report, because a box can hold a store and
memory pair, or a memory and lane pair, that no memory has. It reads lanes and memberships at the current state only,
so a lane move inside a record's history can make it miss or add a disagreement. PT11 tests it against a brute-force
oracle with the same expansion. A person who wants certainty about one use runs `engram-permissions explain`, which
calls `decide`.

The check never holds more than 4,096 boxes. If it would, it reports "could not check: too complex" for J to the
same stewards, and that counts as a disagreement. Nor does it hold more than 2,000,000 memory refs in its sets at
once, past which it reports the same (revision 7; Rio Grande's call; 15, "Memory"). The count is of the sets held:
those one State keeps for its layers' boxes, counted once when they are made, plus those the current check has made,
counted afresh for each check. So the sets one check frees don't count against the next of an act's up to 64 checks
(the re-check's RCS8). A meet with a full set shares the other set rather than copying it.

**When it runs.** It runs after every change to the layer of J, of a parent, or of an ancestor. It also runs after
every registry change, because audiences and collections become sets at the current state: places, parent edges,
agents and their placements, groups, collection members, stewards. It checks at most 64 joint places per change, and
the rest wait for the next run. It also runs on demand: `engram-permissions check [place]`. Ineffective parts use the
same algebra. So do two write-time checks: that a narrowing is narrower, and that a `share` lies within its envelope.

## 9. Receipts and transparency

### 9.1 What each use records

The deciding party writes receipts to `ENGRAM_HOME/.engram/permission-uses.db`, a file of its own, so the daemon's
read-only ledger stays read-only (P15).

```sql
CREATE TABLE uses(seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, at INTEGER NOT NULL, ledger_id TEXT NOT NULL,
  ledger_seq INTEGER NOT NULL, agent TEXT NOT NULL, place TEXT NOT NULL, acting_for TEXT NOT NULL, session_label TEXT,
  action TEXT NOT NULL, purpose TEXT NOT NULL, object TEXT, copy TEXT, allowed INTEGER NOT NULL, cited TEXT NOT NULL,
  refusal TEXT, until INTEGER, horizon INTEGER, returned TEXT, filtered INTEGER, content_digest TEXT,
  shadow INTEGER NOT NULL DEFAULT 0, prev_digest TEXT NOT NULL, digest TEXT NOT NULL);
CREATE TABLE use_subjects(use_seq INTEGER NOT NULL, subject TEXT NOT NULL, object TEXT NOT NULL);
CREATE TABLE uses_anchor(through_seq INTEGER PRIMARY KEY, digest TEXT NOT NULL);
CREATE TABLE uses_monthly(month TEXT NOT NULL, subject TEXT NOT NULL, place TEXT NOT NULL, action TEXT NOT NULL,
  purpose TEXT NOT NULL, outcome TEXT NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY(month, subject, place, action, purpose, outcome));
```

- **A recall** writes one receipt. It holds the object refs it returned (`returned`), at most 20 (12.2), and how many
  copies were filtered out (`filtered`), as a count only. Filtered copies get no ids and no `use_subjects` rows. A
  filtered recall is not a use of the memory. Filtering happens before ranking, so for an outsider every placement is
  filtered. Attributing those to subjects would write up to 20,000 rows per recall and tell nobody anything.
- **A read or delivery** writes one receipt per item asked for, allowed or refused, because the requester named that
  id. An allowed delivery records the item's `content_digest`, which the `remember` guard reads (section 10). No view
  shows it.
- **An answer use on a road or trail** (6.4), such as one `route` edge, writes one receipt per road or trail, listing
  the memories it named, at most 32.
- **A bulk use** (6.4, P33) writes one receipt, with `object` null and `copy` = h.
  - A *named* bulk use of at most 512 objects, such as an imprint batch or one of the evaluation's `read` batches
    (6.4), holds in `returned` the count and the SHA-256 of the sorted object list. Its objects are in
    `use_subjects`.
  - A *counted* bulk use, over objects the deciding party derives and never names, holds the count in `returned`.
    It has one `use_subjects` row per distinct subject of its objects, with the copy ref h in the `object` column.
    No object is named anywhere.
- **Imported station receipts** (the re-check's RS3; Rio Grande's call). A deciding party with no receipts file of
  this form, such as a station holding an imprint in the imprints spec's step 1, keeps its own content-free
  receipts. The owner's machine imports each verified one into this file, with the refs from its own list of what it
  sent (imprints spec section 12, "In the owner's own use list"). That is step 2's "sends each receipt about a person
  to that person's home ledger" (9.3), done by the home pulling. The station's own imprint receipts name no memory
  ids, because they outlive the copy by 400 days (imprints spec D32). The imported form is this section's form with
  four named differences, written exactly as that spec writes them:
  1. **One row per action.** The station decides each action of a use as its own term (imprints spec section 8). So
     the import writes one row per action the use needed: three for an admission (`recall`, `read`, `imprint`), and
     for an evaluation `recall` and `read` on the memories and `route` on the roads and trails. A local use writes
     one receipt under its own action, whose `cited` covers all of `need`.
  2. **Memories by batch.** For each action on memories, one row per batch of at most 512 refs, in the order of the
     owner's list. `returned` holds the batch's count and the SHA-256 of its sorted refs, and there is one
     `use_subjects` row per (owner, ref). Each row is a named bulk use.
  3. **Roads and trails as one counted row per bulk use.** For each action on roads and trails, one row for all of
     them in that bulk use, with `returned` = their count and one `use_subjects` row of (owner, h). The count is the
     one the station's receipts carry, which that spec's admission makes (its sections 10 and 12). A use the station
     refused before it counted them read none, and its one row holds null in `returned` (the cross-check's XS2). It is
     a counted bulk use over roads and trails together, within 6.4's bounds of 100,000 objects and 100,000 named
     memories. A use over more would be several rows, one per bulk use.
  4. **Cited without versions.** `cited` holds the record ids alone. `ledger_id` is the station's peer id (4.1), and
     `ledger_seq` is the receipt's position in its chain. A station without a ledger has no layer versions, and
     `horizon` is null.

  Every imported row has `copy` = h = `imprint:<station peer id>/<imprint id>`, `object` null, and the `id` the
  imprints spec derives. The use list (9.3) marks each imported row with its station and counts imported rows apart
  from local ones, and `--action X` matches each row's own action. Privacy over a uniform form.
- `use_subjects` has one row per (subject, object) the receipt names, written at the time of the use. For a counted
  bulk use, the object column holds the copy ref h.
- `cited` holds the record cited per (layer, action) and every layer's version (`ledger_seq`); for a bulk use, every
  distinct record cited per (layer, action) (6.4). `refusal` holds the code, the layer and the action. Which readers
  see which of them is 9.2: the agent that asked sees none. `copy` holds h (6.1) on every receipt.
- A receipt never holds content or query text, as today's receipts (local-city spec, section 4.6). `session_label`
  is the client's declared label: provenance, never authority (spec A, D7). In step 1 the frame carries none, so it is
  null.
- **Writing.** Both the daemon and the engram servers write this file (the `remember` guard decides `imprint`). Each
  write runs in `BEGIN IMMEDIATE`, reads the last digest inside that transaction, and appends. Receipts are
  hash-chained like the log (5.6).
- **Retention.** Receipts are kept 400 days. Then they are folded into `uses_monthly` counts per subject, place,
  action, purpose and outcome, which are kept. The fold writes one `uses_anchor` row holding the last folded row's
  `seq` and digest, and verification of the chain starts from the latest anchor.
  - **Only the leading run folds.** The fold reads receipts in `seq` order from the latest anchor, and stops at the
    first one whose `at` is at or after the cutoff, as today (`engram/permission_uses.py:344-347`). A receipt's `at` is
    when its use was decided, and the daemon and the servers both append, so `at` is not in `seq` order. A filter on
    `at` alone could fold past a younger receipt and anchor beyond it, which would then never be verified or folded.
  - **In batches, one receipt at a time** (revision 7; 15, "Memory"). The fold works in batches of at most 4,096
    receipts, oldest first, each in a transaction of its own. Inside it, the fold reads the receipts through a cursor.
    It verifies each against the running digest, adds it to the monthly counts in the file, and keeps nothing of it.
    Then it deletes the batch and writes its anchor. So its memory is one receipt, however many bytes a batch holds.
    A break in the chain rolls back its batch, and the fold stops there.

### 9.2 Who can read them

| Reader | Sees |
|---|---|
| A subject (and agents acting for them) | Every receipt whose `use_subjects` names them, as written at the time of the use: requester, place, action, purpose, records, time, outcome. A later claim to be a subject gives no access to earlier uses. |
| The ledger owner, and agents acting for the owner | The owner's list (9.3), with each refusal's code, layer and action. An agent acting for the owner that was refused sees its own receipts as the agents row below says, and the layer only in this list (the check of revision 4, BN3). |
| A place's stewards, and the stewards of every place that dominates it | Receipts for uses at the place, or of copies it holds: requester, action, purpose, outcome, time, and the records cited in the layers of places that are not homes. Each subject appears as a pseudonym, and so does every home: a home's layer, cited or refusing, shows as the pseudonym this view gives the home's person, with no record ids. A refusal shows its code and action, and its layer as the place's id when that place is not a home, or as `legacy` or `restriction`. Filtered counts. |
| The agents in a place | Their own receipts: allowed items, with the annotation of section 11, and refusals of ids they named. A refusal shows only the id, the time and "not allowed": no code, layer, action or cited record. A bulk refusal, which names no id (9.1), shows its count in place of the id, and for a named bulk use also the SHA-256 of its sorted objects (the check of revision 4, BN4). No filtered counts, which would tell them refused memories exist (P23). |
| The requester | Its own allowed items, with the annotation of section 11. A refused item carries no reason (12.2). |
| Anyone else | Nothing. |

**A refusal names no layer to the agent that asked** (the final check after repair, AS2). A refusal's layer can name
a person: `NO_ALLOW` at `place:home/jenn` would tell `ph-coordinator` that m3 is about Jenn, without her yes (use 2).
So the agent learns only that it was refused, at the point of use (12.2) and in its receipts alike, and a place's
stewards see that home only as Jenn's pseudonym. The ledger owner and the agents acting for the owner see the layer:
that is how Andy's list says "m3: needs Jenn's yes" (9.3). An allowed item's annotation still names the layers that
allowed it (section 11).

A pseudonym is the first 16 hex of `HMAC-SHA256(places.pseudonym_salt, subject id)`. It is stable within one place,
so a place's stewards can count uses per person without the name on the screen. It is different across places.
**It is a display convention, not a protection.** The salt is in the ledger, so whoever holds the ledger can compute
the pseudonym of every registered person. A requester also sees `laid_by` on every allowed item (section 11). Whether
the county needs more is in section 19.

### 9.3 Listing every use of my memories

`engram-permissions uses [--since T] [--until T] [--place P] [--action X] [--purpose Y] [--collection C]
[--object O] [--refused] [--json]` lists the ledger owner's uses: counts first, then at most 200 rows, newest first.
With `--place P` for a place the owner stewards, it shows that place's view (9.2) instead. The engram MCP tool
`permissions(focus="uses", ...)` returns the owner's list to agents acting for the owner. The list shows allowed uses,
refused reads, blocked shares with their reason ("needs Jenn's yes", "Public Health does not allow imprint"), and
self-claims (7.4). It shows no filtered recalls (9.1). It marks each imported station receipt with its station and
counts imported rows apart from local ones, since their form differs (9.1). In step 1 there is one receipts file.
From step 2 on, every deciding party also sends each receipt about a person to that person's home ledger (section
14).

### 9.4 How a place publishes its rules

`engram-permissions place show <place> [--json]` prints a `PlaceRules` artifact in the Lighthouse envelope that
ConnectionPolicy and RecallReceipt use: `protocolVersion "0.1"`, `kind "PlaceRules"`, `id`, `issuedAt`, `issuer`
(`urn:engram:<ledger_id>`), `payloadMediaType "application/vnd.engram.place-rules+json"`, a `payload` of `{place,
parents, stewards, retired, ledgerSeq, logDigest, records}` (every effective record, all fields), and `digest` from
`artifact_digest` (`engram/lighthouse_protocol.py:148-159`). Every receipt cites the `ledger_seq` the rules had, so a
reader can check a decision against the rules in force. From step 2 a station serves it without a login, as it
serves public layers (`peer/superyak_peer/layers.py:191-194`).

**Home places are not published.** Who Andy shares with is about Andy, so his home's rules are readable only by him
and his agents. This departs from the vision's principle 5, "Every place publishes its rules", and section 19 puts it
to Andy.

## 10. Revocation, expiry, and copies already delivered

- **Revoking a record** takes effect at the next decision. The daemon's cache is keyed on the ledger's `seq` (12.2),
  so the next request recomputes.
- **Revoking a grant** stops its grant-backed records and memberships at the next decision. Person-backed records
  stay (7.3).
- **Time needs no act.** A record stops matching at `valid_until`, a dated deny starts at its `valid_from`, and a
  grant-backed membership stops at its grant's expiry. The cache ends at the horizon of the decisions it holds (6.5,
  L8), so each takes effect at the next decision at or after its time.
- **Placements.** The person's engram server sweeps the published house at startup, after each permissions command,
  and after each `share` or `unshare`, at most 256 placements per pass. A placement whose linked record no longer
  counts is relinked to another effective allow of the same subject that covers the same object with the same
  placement audience (P29, 12.1), or removed. When the last share row of a copy goes, the copy and its vector are
  deleted, as `unshare` does today (`engram/sharing.py:176-204`, the deletes at `:195-203`). The sweep also settles pending lane notes (5.3). A
  use is refused at once whether or not the sweep has run.
- **Content already in an agent's context** cannot be taken back. Spec A says the same of instructions: "a session
  keeps whatever it has already read" (spec A, section 4). The receipt says where it went. The annotation carries
  `until`.
- **Content already on disk** cannot be taken back either. Claude Code keeps delivered content in its session
  transcripts. The context runtime's conversation archive "may quote a source" (`engram/context_lighthouse.py:1-5`).
  Both are outside this spec's reach, like content in context.
- **Keeping it is an imprint** (P19). `remember` refuses content whose `content_digest` equals that of an item
  delivered to this instance's agent, unless `decide` allows `imprint` for that item. It finds deliveries in
  `permission-uses.db`: allowed `inject_context` receipts with `agent` = this instance's agent, from the last
  24 hours, at most 200. The daemon writes those receipts whichever reader asked, so deliveries through the context
  runtime are caught as well as those through `neighbors.py` (12.1). This catches copies, not paraphrases. When
  `imprint` is allowed, the kept memory carries its source's subjects (P25). The use's h is the copy the delivery
  came from. The guard also passes k, the store it keeps into, its own instance's, whose `stores` row's place P36
  tests (6.1, 6.3).
  - **What the agent is told** (the check of revision 4, BS1). To an agent that doesn't act for the ledger owner, a
    refused `remember` says only that keeping this content is not allowed: no code, layer or action, as 9.2 says of
    a refused read. Its receipt shows as 9.2's agents row. A layer can name a person. If Andy records `person:amy` as
    a co-subject of m1 after use 1 delivered it (7.4), the guard's first failing layer is `place:home/amy`, since
    subjects come first, by id (6.5, step 2). Naming it would tell `ph-coordinator` that m1 is about Amy, who never
    said yes. No rule changes.
  - **Known limit: time** (the re-check's RS8). The guard reads only the last 24 hours, at most 200 receipts
    (section 15). A verbatim `remember` after that passes, and the kept memory carries no source subjects. That is
    the failure P25 exists to stop (the first review's MF6), reached by waiting. The window bounds the guard's cost
    on each `remember`.
  - **Known limit: place.** The guard reads this machine's `permission-uses.db` only. From step 2, a delivery
    decided by another party's daemon, such as a station's, leaves its receipt there, so the guard can't see it.
  - In step 1 both harms are latent: every real receiver is one of the owner's own instances (12.1, the `commons`
    row), and the county agents exist only as E1's fixtures.
  - **What step 2 needs.** A guard that sees every delivery to its agent, wherever it was decided, for as long as the
    delivered content could be kept. The receiving server records each delivered item's `content_digest`, and the
    receipt id from its `permission` member, from the delivery itself. It keeps them at least until the decision's
    `until`, or for 400 days when there is none, and the guard reads that record. Paraphrases stay out of reach
    either way.
- **Imprints** are deleted by the store that holds them when the owner withdraws or the record ends, and that store
  writes a deletion receipt (vision, "Imprints"). Until the deletion is confirmed, the owner's use list shows "copy
  held, deletion not confirmed". The imprints spec builds this.

## 11. What an agent sees at the point of use

The daemon adds one `permission` object to each allowed read item:

```json
{"laid_by": "andy (engram)", "allowed_by": [{"place": "place:home/andy", "records": ["r-7f3a…"]},
 {"place": "place:la-county", "records": ["r-0b9e…"]}], "until": "2027-01-31T00:00:00Z", "receipt": "u-5e21…"}
```

The agent sees one line. `neighbors.py` prints nothing; it returns JSON, which the server puts under
`response["neighbors"]` (`engram/neighbors.py:170-171`, `:195`; `engram/server.py:2610-2618`). Each item in
`response["neighbors"]["delivered"]` gains `permission`, a string of at most 240 characters, built from the object:

`laid by andy (engram) · allowed by home/andy #7f3a, la-county #0b9e · until 2027-01-31 · receipt #5e21a9c0`

- `laid_by`: who made it. For a memory, its store's owner and instance name. For a road or trail, the trail spec
  (revision 9) fills it in the same field.
- `allowed_by`: each consent layer's cited records, in the order of 6.5, step 2. Each layer shows its place's short
  name and the short ids of its distinct cited records, joined by `+`.
- `until`: the decision's `until`, as a date. It covers ledger layers only (6.5, step 6): a legacy policy rule may
  end the use sooner, and the next request then refuses it.
- `receipt`: the short id of this use's receipt, `#` and 8 hex (4.1). The full ids are in the receipt.

**A place's short name** is its last segment, or `home/<handle>` for a home. When two places in one line share a last
segment, both show their full id without `place:`. **Truncation:** each name in `laid_by` and `allowed_by` longer than
32 characters is cut to 31 and `…`. If the line is still over 240 characters, `allowed_by` entries are dropped from
the end and `+N` is added. The receipt holds everything.

The context runtime carries the same line: `_evidence` copies a fixed set of keys (`engram/context_lighthouse.py:28-30`)
and gains `permission`.

A requester never learns that a refused memory exists (P23). Refused copies are filtered before ranking, as the daemon
filters by audience today (`engram/lighthouse_daemon.py:227-239`). A refused read returns no content and no reason
beyond "not allowed" (12.2), and the agent's receipts give it none later (9.2).

## 12. How it maps onto what exists

### 12.1 The map

| What exists | Where | What it becomes |
|---|---|---|
| Share rows: a copy with an audience | `engram/sharing.py:99-173`; migration 027 | Placements. Each links to the allow record it serves (`record_id`), and its `audience` column holds the placement audience (below). |
| `commons` and `group:` audiences | `engram/sharing.py:18-19`; `engram/policy_gen.py:47-54` | Migrated `commons` becomes `place:home/<person>`: today the daemon's socket is mode 0600 (`engram/lighthouse_daemon.py:476`), so today's commons is the owner's own processes. `group:g` becomes a ledger group of the same instances. Neither widens later. |
| ConnectionPolicy files | `engram/lighthouse_policy.py`; `engram/lighthouse_validation.py:25-64`; `engram/policy_gen.py:57-105` | Legacy consent layers, still required, decided by their own evaluator on every request, edited only by the person (6.2 says why agents never edit them). Retired in a later step once the ledger covers them. |
| `engram:audiences` in the publisher policy | `engram/lighthouse_daemon.py:156-170`; `engram/policy_gen.py:97-101` | Still intersected. The daemon strips `group:outside-home` from it under every gate and adds it back only under `enforce` (below). Later generated from ledger groups. `policy_gen.py` refuses a group named `outside-home`. |
| `recall`, `read`, `inject_context` | local-city spec 4.4; `engram/neighbors.py:82`, `:120`, `:138` | The same three actions, with the same order as `need` (6.4). The daemon decides a `read` frame as `inject_context` (P18), because both of its readers inject what they read: `neighbors.py`, and the context runtime (next row). |
| The context runtime | `engram/context_lighthouse.py`, used by `engram/context_cli.py:90-91` | A second daemon reader. It checks `recall`, `read` and `inject_context` (`:84`), reads read frames (`:166-170`) and validates them with `validate_read` (`:16`, `:170`). Its receipts go to the conversation archive (`:94-104`, `:113-117`), not to `memory_log`. It becomes: `_evidence` (`:28-30`) also copies `permission` (section 11). Its receipts stay where they are. The daemon's own receipts record its deliveries, which is what the `remember` guard reads (section 10). |
| Disclosures sidecar | `engram/lighthouse_daemon.py:57-62`, `:130-153` | `permission-uses.db` receipts. The sidecar keeps being written until the legacy layers retire. |
| RecallReceipt | `engram/lighthouse_receipts.py:32-70`; `engram/schemas/lighthouse/recall-receipt.schema.json` | Payload unchanged: the schema fixes `audience` to `self`, `action` to `recall`, and `readDecision.code` to three Lighthouse codes. The use receipt ids and cited records go in `extensions["engram:permissions"]`, which the schema allows (namespaced keys). |
| Station grants | `peer/superyak_peer/grants.py:72-122`, `:284-306`; spec A section 2 | The model for permission grants (7.2). A separate table, because in step 1 the store's machine need not be the station. |
| Station layer narrowing | `peer/superyak_peer/layers.py:143-166` | The precedent for narrowing-only revisions. |
| Station spaces | `peer/superyak_peer/spaces.py:19-22` (`care-circle`, `project`, `organization`) | Candidates in step 2: an organization as a place, a care circle as a group. Not built here. |
| The `share` MCP tool | `engram/server.py:1949-1980`; arguments at `:1951-1956` | Under `enforce` it never writes a record (below). `unshare` removes a placement, which only narrows, so any agent acting for the owner may still call it. |
| The trail spec's work-lane rule | trail spec revision 3, section 8 | Replaced by `route` records. Every use of a road or trail also needs `recall` on the memories it names, and `read` and `inject_context` on those it shows (6.4, P35). |
| Re-laning | `engram/compress.py:508-510`; `engram/storage.py:598-610` | A pending lane note first, a settling note after; the re-lane is refused if the first note fails (5.3). |
| `source_instance`, a name | `engram/server.py:1976` | Migration 029 adds `shared_memories.source_instance_id` and `shared_memories.record_id`. `share` fills both. `migrate` fills old rows (12.3). |
| Genome sync | `engram/federation.py:155` | It moves genome-core episodes between one person's own stores, so it stays inside home. Under `shadow` and `enforce`, each synced copy carries its source's co-subjects (P25). |
| Inter-instance messages | `engram/federation.py:17-105` (`SignalBus`), `:211` (`process_inbox`) | Text between one person's own instances, not memories. Outside step 1. |
| The Lighthouse export | `engram/lighthouse_export.py:89-128`, `:299-342` | It writes work-lane ids, content digests, edges and traces to a file the person names, with no content. It is the person reading their own store. Outside step 1. A later spec decides it as a use with an audience before the file leaves the machine. |
| Session transcripts | Claude Code, outside engram | They keep delivered content on disk. Outside this spec's reach (section 10). |

**The placement audience** (P29). `shared_memories.audience` must pass `validate_audience`, which takes only
`commons` and `group:` values (`engram/sharing.py:41-46`). A row that fails it is invalid to `audiences_for`,
`list_shares` and the daemon's `_shared_audiences` (`engram/sharing.py:57-65`, `engram/lighthouse_daemon.py:173-201`).
So each placement carries a fixed mapping of its linked record's audience:

| Linked record | `shared_memories.audience` | The legacy audience check |
|---|---|---|
| A row `migrate` linked | its legacy audience, unchanged | as today |
| An allow each of whose audience entries is `self` or a `place:Z` that the owner's home dominates | `commons` | as today: the owner's own processes |
| An allow whose audience is exactly one group, `group:g` | `group:g` | as today |
| Any other allow: outside home, mixed, or naming two or more groups | `group:outside-home` | under `enforce`, passes for every receiver the publisher policy names; under `off` and `shadow`, never passes |

**Two groups** (the re-check's RN5). An allow naming two of the owner's groups, `group:g1` and `group:g2`, is inside
home (5.4), but one placement row has one audience. So it maps to `group:outside-home`, and under `off` and `shadow` its
placement is never served: it fails closed. Under `enforce` the new decision serves it to the agents of either group. A
person who wants the legacy path to serve it too writes one allow per group.

`group:outside-home` is reserved. No ledger group or `groups.toml` group may take the name (`policy_gen.py` refuses
it, section 16), the policy generator never writes it, and the `share` tool refuses it as an argument, so only the
server's mapping writes it. That alone doesn't keep it from being served. Today the daemon accepts every audience a
policy lists that passes `validate_audience` (`engram/lighthouse_daemon.py:156-170`, the check at `:168`), and
`group:outside-home` passes `GROUP_RE` (`engram/sharing.py:19`, `:44`). The ConnectionPolicy schema puts no limit on
`extensions` values (`engram/schemas/lighthouse/connection-policy.schema.json`, `extensions`), today's `load_groups`
accepts a group named `outside-home` (`engram/policy_gen.py:13`, `:29`), and E1 writes its policies by hand (section
13). So a hand-written or edited policy that listed the name would serve outside-home placements under `off` or
`shadow`, where the legacy path alone decides. Revision 2 said today's code never serves one; that was wrong.

**The daemon rule** (P29; the re-check's RS1). `_allowed_audiences` removes `group:outside-home` from whatever a policy
lists, under every effective gate (12.3), and also when there is no ledger at all. Under `enforce` alone it then adds
`group:outside-home` back for a receiver when the publisher policy has a rule for that receiver. The new decision is
then that placement's only audience check. So a lowered gate fails closed for every outside-home placement, whatever any
policy says. The sweep's "same placement audience" (section 10) means this column.

The `commons` row rests on a step 1 fact: every receiver a publisher policy names is one of the owner's own
instances on his machine, behind the 0600 socket. Under `off` and `shadow` the legacy path alone decides, so a
receiver acting for anyone else must not hold `commons` there. E1's county receivers hold it only because E1 runs
under `enforce`, where the new decision also applies.

**`share` under `enforce`.** `share(memory_id, audience, reason, layer)` (`engram/server.py:1951-1956`) has no
purposes, end or actions, so it writes no record. It places a copy only when an effective allow in the owner's layer
already covers the memory for `recall`, `read` and `inject_context`, for some purpose, for the audience it names.
`commons` means `place:home/<owner>`, `group:g` the ledger group, and it also accepts `place:Z`. The server maps the
audience to the placement audience before calling `sharing.share`, and links the covering record. Otherwise it
changes nothing and returns the `permit` call or the CLI command that would make the allow. Records are written only
by the CLI and by `permit(op, ...)`. `permit` takes every field of the change in full: for `share`, the selector,
`valid_from`, `valid_until` (at most `max_days` after `valid_from`) and a reason. It acts under a valid grant, or
files a proposal, and says which.

### 12.2 The daemon in step 1

- **The requester** is `agent:<receiver>` from the frame, in its one registered place (P31), acting for its
  registered principal. The frames do not change on the request side. A recall frame's audience must still be
  `"self"` (`engram/lighthouse_protocol.py:232`).
- **For a recall**, each placement's object is its source memory ref, `mem:<source_instance_id>/<layer>/<source_id>`,
  and its copy is the house that serves it, h = `store:<the house's instance_id>`, whose place `migrate` registers
  (12.3, step 2).
  A row with no `source_instance_id` has no object, so under `enforce` it is refused (`NO_LAYER`). The daemon decides
  `recall` for each placement before ranking.
- **The cache.** The daemon keeps an eligible-set cache per (agent, place, purpose, action), at most 64 entries and
  96 MB, whichever it reaches first (revision 7). It sizes each entry by an estimate from its decisions, which U9
  checks against a measure. An entry larger than 96 MB alone serves its own frame and is not kept. The decisions of
  one entry share their equal citations. An entry is valid while three things hold: the ledger's `seq`, the
  placements' change counter, and the clock before the entry's horizon (the earliest horizon among its decisions,
  6.5). Migration 029 adds the change counter: a one-row table whose count triggers raise on every insert, update and
  delete of `shared_memories`. A count and highest rowid would miss a delete followed by an insert.
- **The rebuild budget.** Rebuilding one eligible set for 20,000 placements against 43 layers of 256 records is about
  220 million record checks if done naively. With the pre-filter of 6.5, it must take at most 2 seconds on the
  station's Raspberry Pi 5. That is a calibration hypothesis, and test U24 measures it. The rebuild runs at the first
  recall after a change, not at every ledger write.
- **For a read**, each item is decided as `inject_context`. An allowed item gains `permission` (section 11). Engram's
  client checks read items' keys strictly (`engram/lighthouse_client.py:315`), so it accepts `permission` with that
  shape and still rejects any other member. Both ends are engram's own code, so the protocol version stays `0.1`.
- **A refused item** looks like an unshared item today: `content: null`, `audiences: []`, and `decision` the legacy
  frame decision, with no `permission` member (`engram/lighthouse_daemon.py:411-440`). That decision is made once per
  frame, before any item (`:402`), and holds only `effect`, `ruleId` and `code` (`engram/lighthouse_policy.py:65-67`).
  So it is the same for every item of the frame and names no item's layer (9.2).
- **Modes.** With the gate at `enforce`, an item is served only when the legacy path and the new decision both allow
  it. With `shadow`, the legacy path alone decides, and both decisions go to the receipts with `shadow = 1`.
- **Bounds.** `share` refuses the 20,001st placement in a house, with the bound in its reason. Under `enforce`, a
  house that holds more than 20,000 placements (written by older code) serves nothing, and the daemon warns.
- **At most 20 candidates per recall** (revision 7; Rio Grande's call). The daemon answers a recall frame with at
  most 20 candidates, whatever `k` it names. The protocol checks only `k > 0`
  (`engram/lighthouse_protocol.py:234-236`), and the daemon passes `k` to retrieval as it is
  (`engram/lighthouse_daemon.py:752`). 20 is the cap engram's own client already sets (`MAX_CANDIDATES`,
  `engram/lighthouse_client.py:17`, checked at `:109`), and both readers go through that client
  (`engram/neighbors.py:90`, `engram/context_lighthouse.py:159`). So nothing engram sends changes. The cap bounds a
  recall's receipt: it names every ref returned, with one `use_subjects` row per subject of each
  (`engram/lighthouse_daemon.py:493`; 9.1). At `k` = 20,000 with 8 subjects a ref, writing that receipt peaks at
  75.1 MB and verifying it at 102.4 MB (15, "Memory").
- **Closed** (12.3). The daemon serves nothing: no candidates, and no content in any read item. It warns with the
  cause.
- **Memory** (revision 7; Rio Grande's call). At most 2 frames decide at once, and a third waits. Each holds one
  State (5.6). The daemon embeds through the shared embedder service that `ENGRAM_EMBEDDER_SOCKET` names, and never
  loads a model of its own. Without the service it refuses to start, and says why. Its peak resident memory is in the
  budget of section 15.
  - **A failed ledger read** during a decision, which a State's lazy reads make possible (5.6), is handled as a State
    that can't be built is today (`engram/lighthouse_daemon.py:678-689`): the daemon warns, serves nothing for that
    frame under `enforce`, and lets the legacy path decide under `shadow`.
  - **A deploy gate.** `superyak-runtime` sets `ENGRAM_EMBEDDER_SOCKET` only when `runtime.json` has
    `embedder_socket` (`scripts/runtime.py:653-655`). So before the daemon's refusal ships, every machine that runs
    the daemon has that key and runs the embedder unit.
  - **Per process, not per machine.** The 2 GB target bounds each process this work adds. The embedder unit is not
    one of them, and carries `MemoryMax=3G` (`scripts/superyak-embedder.service:14`). This spec doesn't claim that a
    whole machine running the daemon, the engram servers and the embedder fits in 2 GB, and it doesn't measure that.

### 12.3 The migration path

**The gate** (P21) lives in the ledger, not in `config.toml`. When `config.toml` fails to parse, the store resolver
warns and falls back to its defaults (`engram/config.py:388-398`). Any agent can also edit the file. Either would turn
a config gate off without a yes. A `gate` log entry sets `meta.gate` to `off`, `shadow` or `enforce`. Only
`engram-permissions gate <mode>`, with the owner's terminal yes, writes it.

**Which houses carry the ledger's id** (the re-check's RS6; Rio Grande's call). A **house** here is any engram store
at `<root>/.engram/graph.db` or `<root>/.engram/instances/<name>/graph.db`, whose ledger is the fixed
`<root>/.engram/permissions.db` (5.5). That covers the published house, `instances/lighthouse/graph.db`, where
`share` writes (`engram/server.py:1934-1946`), and every publisher house the daemon serves, `instances/<name>/graph.db`
for each name in its config (`engram/lighthouse_daemon.py:506-518`), including one added to that config later.

- **The raise.** The first move above `off` sets `meta.gate_raised` and writes `permissions_ledger_id` into the
  `meta` table (`engram/migrations/001_initial.sql:8`) of every house. It refuses unless the published house exists,
  since `share` and the daemon serve from it and `_published_house_storage` never creates it
  (`engram/server.py:1934-1946`).
- **A house made later.** A house created while a ledger exists gets the id when it is created. Migration 029 writes
  it inside its own transaction, as migration 028 gives a new store its `instance_id` (`engram/storage.py:222-230`):
  if the house's ledger exists and has `gate_raised`, 029 reads its `ledger_id` read-only and writes it. If that
  ledger can't be read, it writes `unreadable`, which no ledger matches. A house that ran 029 before the raise gets
  the id from the raise.

Every reader computes the effective gate at every request: the daemon over the houses it serves, an engram server
over the published house.

1. No ledger file, and no house under `<root>/.engram/` carries `permissions_ledger_id`: `off`. To decide this a
   reader reads at most 64 houses' `meta`; with more houses it reads **closed**.
2. **Closed** when any of these holds: there is no ledger file but some house carries the id; the ledger can't be
   opened or read; a house the reader serves carries an id other than the ledger's, or `unreadable`; a house the
   reader serves carries no id while `gate_raised` is set, so it was made or restored without one; `meta.gate` is
   not one of the three values; or `gate_raised` is set and `gate` is missing.
3. Otherwise, `meta.gate`.

So a ledger deleted by mistake, or a house made again after the raise, never reads `off` while any house still
carries the id. A house that reads closed for want of the id, such as one restored from before the raise, is marked
by running `engram-permissions gate <current mode>` again, with the yes.

Closed means fail closed: the daemon serves nothing, `share` and `permit` refuse, and the `remember` guard refuses
as under `enforce`. Each says why. A `[permissions]` section in `config.toml` is ignored with a warning: config
can't lower the gate, or set it at all. Lowering the gate is the owner's terminal act like any other move.
`load_config` logs the warning, naming `engram-permissions gate` (section 16). Today it warns only about unknown keys
inside the sections it loads (`engram/config.py:318-327`), and `permissions` is not one of them (`:332-356`), so the
section would be dropped without a word.

1. **Off.** No ledger: everything behaves exactly as today, which is deny-by-default already, except that the
   daemon never serves `group:outside-home` and `share` refuses that name (12.1).
2. **`engram-permissions migrate`**, which Andy runs in his terminal. It creates the ledger with Andy as its owner. It
   registers `person:andy` and his home place. It registers one agent per receiver named in the publisher policies'
   rules (a rule's `publishers` list names the receivers, as the layered lighthouse design notes), each in his home
   place and acting for him. It registers each store with Andy as owner and `place:home/andy` as its place: every
   house of 12.3 above, the published house among them, and each source store a share row resolves to. A use's
   holding place is its house's place (6.3, item 3), and an unregistered house would refuse every use (`NO_LAYER`).
   Use 1 of section 13 rests on this. The published house's own copies are never the objects of a use: placements
   are decided on their source refs (12.2). It registers the groups from `groups.toml`. Then the shares:
   - **One collection per legacy audience.** `collection:andy/legacy-commons` holds the rows shared to `commons`, and
     `collection:andy/legacy-group-<g>` the rows shared to `group:g`. Each row becomes a person-backed membership of
     its source memory. Each collection gets one person-backed allow: audience `place:home/andy` for commons, or
     `group:g`; actions `recall`, `read` and `inject_context`; purposes `"*"`; no end; reason `legacy share`. These
     are inside home (5.4). So a house with any number of shares needs one record per audience, within the 256 bound.
   - **Each row's source is checked.** A row names its source by instance name. `default` means
     `ENGRAM_HOME/.engram/graph.db`, and a name n means `instances/n/graph.db`. A name doesn't fix the store: a server
     whose instance store is missing falls back to the default store yet still shares under the instance's name
     (`engram/config.py:399-409`, `engram/server.py:1303-1310`, `:1976`). So `migrate` opens the named store read-only
     and checks that the source memory exists there with the row's `content_digest`. A row that passes gets
     `source_instance_id`, `record_id` and a first lane note. A row that fails stays unmigrated and is listed. Under
     `enforce` it is refused, because it has no object (12.2). Andy can share it again.
   - **Before he confirms**, it prints the count per audience and the unmatched rows. It also writes every row it
     will migrate to a file and prints the path. Andy can end all of one audience's migrated shares at once by
     revoking its one allow.
3. **Shadow.** `engram-permissions gate shadow`. The daemon decides both ways. `engram-permissions report shadow`
   lists every disagreement. After a correct migration, the legacy path allows nothing the new one refuses, except the
   unmatched rows `migrate` listed (test U13).
4. **The home grant.** Andy signs one grant for his own agents, for example `share`, `withdraw`, `shorten` and
   `narrow` within `place:home/andy`, so that `share` keeps working for them at home. That is his act, not a design
   choice. **A limit to know:** a grant lasts at most 720 hours (7.2), and a grant-backed allow stops with its grant
   (7.3). So under `enforce`, every share an agent makes at home stops within 30 days of its grant's start, and the
   sweep removes its placement. That happens unless Andy renews the grant or makes the share his own with `allow`.
   Today's shares last until someone unshares them. Section 19 asks Andy which he wants.
5. **Enforce.** `engram-permissions gate enforce`. From then on an agent widens only inside an envelope he signed.

What each mode does:

| Part | `off` | `shadow` | `enforce` | closed |
|---|---|---|---|---|
| Daemon delivery | legacy | legacy; both decisions in receipts | legacy and new must both allow | nothing |
| `group:outside-home` placements | never served | never served | served when the new decision allows | nothing |
| `share` | as today | as today; `report shadow` lists the shares that would have needed a proposal | 12.1 | refused |
| Lane notes | no | yes, so the history exists before enforce | yes | none can be written, so re-lanes are refused (5.3) |
| Sweep | no | reports what it would remove | removes | no |
| Annotation | no | yes | yes | no |
| `remember` guard | no | reports what it would refuse | refuses | refuses |

## 13. Worked example: Andy's medical history

In step 1 this whole example runs as one end-to-end test on one ledger. Andy is the ledger owner. The county's
places, stewards and agents are fixtures written through the ledger's API, not the CLI, since in step 1 the CLI acts
only as Andy (7.6). From step 3 the same records live on the county's station and on Andy's machine (section 14).

**Places and rules.** The county `place:la-county`, with children `public-health` and `parks-and-rec`, the office
`place:la-county/public-health/clinic-3`, and the joint place `place:la-county/summer-wellness` with both
departments as parents. Each record allows the audience named, with all objects:

| Layer | Record | Audience | Actions | Purposes | Until |
|---|---|---|---|---|---|
| la-county | C1 | `place:la-county` | recall, read, inject_context, route | care-coordination, program-operations | 2027-12-31 |
| public-health | H1 | `place:la-county/public-health` | recall, read, inject_context | care-coordination | none |
| public-health | H2 | `place:la-county/summer-wellness` | recall | program-operations | none |
| parks-and-rec | K1 | `place:la-county/parks-and-rec` | recall, read, inject_context, route | program-operations | none |
| parks-and-rec | K2 | `place:la-county/summer-wellness` | recall, read | program-operations | none |
| summer-wellness | W1 | `place:la-county/summer-wellness` | recall, read | program-operations | none |
| clinic-3 | L1 | `place:la-county/public-health/clinic-3` | recall, read, inject_context | care-coordination | none |

**Agents.** `agent:ph-coordinator` acts for clinic-3, in clinic-3. `agent:parks-planner` acts for
parks-and-rec, in it. `agent:sw-helper` acts for summer-wellness, in it. `agent:rio-grande` acts for Andy, at his home.

**Legacy layers (E1).** The fixture writes the publisher's and each receiver's ConnectionPolicy by hand. Today's
generator would not do: its rules allow only purpose `session-recall` (`engram/policy_gen.py:68-87`, the purpose at
`:80`). Each rule allows `recall` and `read` (publisher) or `recall`, `read` and `inject_context` (receiver), for
context `memory/technical` and purposes `care-coordination` and `program-operations`. `engram:audiences` gives each receiver `commons`. So the
legacy layers refuse nothing the ledger allows here, and the new decision is the one that tells the agents apart.

**Andy's side.** He registers `person:jenn`, whose home layer is empty. He makes `collection:andy/medical-history`
with m1 (an allergy list), m2 (his medication history) and m3 ("Jenn drove me to the clinic"), and adds `person:jenn`
as m3's co-subject. On 2026-11-01 he says yes:

- **R1**, in `place:home/andy`: allow, audience `place:la-county/public-health`, collections
  `[collection:andy/medical-history]`, actions `recall`, `read`, `inject_context`, purposes `care-coordination`, from
  2026-11-01 until 2027-01-31, person-backed. It is outside home and names a collection (P28). The words he confirmed
  end: "Public Health's stewards, and LA County's above it, decide which agents those are."
- **G1**, a grant to `agent:rio-grande`: ops `share`, `withdraw`, `shorten`, `narrow`, `collect`, `uncollect`;
  envelope as R1 without the time; `max_days` 120; depth 0; expires 2026-11-30.

His copies are placed in his home lighthouse, the published house, which `migrate` registered with his home as its
place (12.3, step 2). So every use below names h = `store:<the house's instance_id>`, and the holding place is
`place:home/andy`. m1's placement is linked to R1, so its `audience` column is `group:outside-home` (P29).

**Uses.**

1. *2026-11-02. `ph-coordinator` recalls, then delivers m1, for care-coordination.* `Req` is:
   - Andy's home, as subject and as holder, counted once;
   - la-county, public-health and clinic-3, the requester's places;
   - the publisher's and the receiver's ConnectionPolicy, the legacy layers;
   - `ph-coordinator`'s restriction layer, which is empty.

   R1 matches. Public health dominates clinic-3, where the agent works, and clinic-3, which it acts for. m1 is in the
   collection, all three actions and the purpose are listed, and the date is inside. L1, H1 and C1 match, and the
   legacy layers allow. Under `enforce`, the daemon passes m1's `group:outside-home` placement through the legacy
   audience check (12.1). The recall returns m1 and m2, and m3 is filtered. The delivery is **allowed**, until
   2027-01-31, with the same horizon. The receipt cites R1, C1, H1 and L1 for each of the three actions. The agent sees
   `laid by andy (engram) · allowed by home/andy #R1, la-county #C1, public-health #H1, clinic-3 #L1 · until
   2027-01-31 · receipt #…`.
2. *Same agent, m3.* The recall filtered m3, so the agent asks for it by an id Andy gave it. m3's subjects are Andy
   and Jenn. Jenn's home layer allows nothing. **Refused**, `NO_ALLOW` at `place:home/jenn`. The agent gets
   `content: null` and no reason. Andy's list says "m3: needs Jenn's yes". The agent's own receipts show the read only
   as "not allowed", so it can't learn from the layer that m3 is about Jenn. Clinic-3's stewards, and those above it,
   see `NO_ALLOW` at Jenn's pseudonym, never `place:home/jenn` (9.2).
3. *`parks-planner` recalls for program-operations.* R1's audience doesn't dominate parks-and-rec, where the agent
   works and which it acts for. m1 to m3 are filtered before ranking. **Refused**; the recall receipt counts them as
   filtered, with no subject named. This is A2. A public-health steward can't change that alone. Putting
   `parks-planner` in public-health needs its principal, a parks-and-rec steward, too, and even there it acts for
   parks-and-rec, which public health doesn't dominate (P3).
4. *`sw-helper` recalls for program-operations.* Summer Wellness has a path to the county through parks, so public
   health doesn't dominate it, and R1 doesn't reach it. **Refused**, even though public health's own rule H2 lets
   Summer Wellness recall.
5. *The gluing check at Summer Wellness.* `own = {recall, read} × program-operations`. Public health's chain gives
   `{recall}` (H2 ∩ C1), and parks' gives `{recall, read}` (K2 ∩ C1). `Δ = {read} × program-operations`, which is not
   empty. The stewards of Summer Wellness, Public Health and Parks see the sentence in section 8. Summer Wellness may
   recall and not read until one of them changes their rules. No ineffective part: each use J asks for is allowed
   by some parent.
6. *Rio Grande tries to add parks-and-rec to R1.* That is outside G1's envelope, so it becomes a proposal. The ledger
   writes its words: "Share collection andy/medical-history with place:la-county/parks-and-rec for
   care-coordination until 2027-01-31. Agents that act for a place Parks and Recreation dominates, working there, may
   use it. Parks and Recreation's stewards, and LA County's above it, decide which agents those are." `sign` would
   print the full selector after it. Andy declines. Nothing changes.
7. *Rio Grande adds m4 (a lab result) to the collection.* The only allow naming the collection is R1, which lies
   within G1's envelope, so `collect` is allowed. The membership is backed by G1, and m4 is covered until G1's
   expiry, 2026-11-30. A decision about m4 has that as its `until` and its horizon.
8. *2026-11-10. Rio Grande shortens R1 to 2026-12-15.* R1 is revoked and R1′ is written: `replaces` R1, the same
   anchor, person-backed, `set_by agent:rio-grande`, `under_grant` G1. R1′'s interval lies inside R1's, as rule 4
   requires.
9. *2026-11-12. Andy denies m2 from 2026-12-01.* He writes D1 in his home: deny, audience
   `place:la-county/public-health`, memories `[m2]`, valid from 2026-12-01, no end. He wants to tell his doctor
   first. The next decision about m2 for `ph-coordinator` has `until` and horizon 2026-12-01. G1 meets D1, yet Rio
   Grande can't withdraw, shorten or narrow it: a try becomes a proposal (P27).
10. *2026-11-20. Andy revokes G1.* R1′ stays, being person-backed. m4's membership was backed by G1, so m4 is no longer
    covered. Andy can add it back himself. If `ph-coordinator` asks for m4 by id, the read is refused with
    `GRANT_INVALID` at `place:home/andy`, action `recall`: R1′ is a candidate only through G1's membership, and a
    candidate's chains include its memberships' (6.5). From 2026-11-30, G1's expiry, the code is `EXPIRED`.
11. *2026-12-01. No ledger write since use 10.* The cache's entry ended at its horizon, so the daemon decides again.
    The next delivery of m2 is **refused**, `DENIED` at `place:home/andy`. m1 is still allowed.
12. *Imprint.* Public health asks to keep m1. R1′ doesn't list `imprint`, so Andy's own layer, first in the order of
    6.5, refuses: **refused**, `NO_ALLOW` at `place:home/andy`. Had Andy allowed it, C1 still doesn't list `imprint`,
    so the county's ceiling would refuse it with `NO_ALLOW` at la-county. Had both allowed it, the kept copy in
    `ph-coordinator`'s store would carry Andy as a co-subject (P25), so parks could reach it only with his yes. A
    subject Andy recorded on m1 later would reach the copy at its next decision, since both are on this ledger (7.4).
13. *2026-12-15T00:00:00Z.* R1′ ends. The next delivery of m1 is **refused** with `EXPIRED`: R1′ is a candidate whose
    effective end has passed, and R1 is revoked, so it is not one. The sweep removes the placements within a pass.
    The content delivered in use 1 is still in that session's context, and the receipt says so. A verbatim
    `remember` of m1 by `ph-coordinator` (section 10):
    - within 24 hours of an allowed delivery of m1, such as just after use 1 on 2026-11-02, is refused, since no
      `imprint` is allowed;
    - at this use's time, passes. No delivery of m1 in this example falls in the 24 hours before
      2026-12-15T00:00:00Z, so the guard finds no receipt, and the kept memory carries no source subjects. That is
      section 10's known limit on time. It is latent in step 1, because `ph-coordinator` is a fixture (section 10).
14. *Andy lists his uses.* `engram-permissions uses --collection collection:andy/medical-history` shows:
    - `ph-coordinator`'s allowed recall of m1 and m2;
    - the allowed delivery of m1;
    - the refused m3 read;
    - the refused m2 read on 2026-12-01;
    - the refused imprint;
    - the expired read.

    Each row shows place, agent, purpose, records and time. It shows no filtered recalls, which are counts, never
    attributed to a person (9.1). Public health's stewards see the same uses at their places, with Andy as a
    pseudonym, and the filtered counts.

## 14. Step 1, later steps, non-goals, anti-goals

### Step 1 (this spec builds it)

One person's stores and the local city on one machine:

- the pure model: names and copy refs, selectors, matching with history, dominance, `decide` with its codes, `until`
  and horizon, `need` with named memories, bulk uses, P36's reading of a co-subject's layer inside the owner's home,
  boxes, the gluing check and ineffective parts;
- the ledger, its log and projections, `rebuild`, `PlaceRules` export, and the receipts file;
- `engram-permissions`: `init`, `migrate`, `gate`, `rebuild` (5.6), `person`, `agent`, `store`, `place` (register,
  parent, steward, retire, show), `group`, `collection`, `subject`, `allow`, `deny`, `revoke`, `shorten`, `narrow`,
  `grant`, `revoke-grant`, `proposals`, `sign`, `decline`, `uses`, `check`, `sweep`, `explain` (decide a described
  use, single or bulk, and print why), `report shadow`;
- the daemon: decisions before retrieval, each placement decided with its copy h (12.2), the cache with its horizon,
  receipts, the annotation, the placement audience with its `group:outside-home` rule (12.1), and the effective gate
  over the houses it serves (12.3);
- the receivers: passing `permission` through in `neighbors.py` and the context runtime, and the receipt extension;
- `share` through records, grants and proposals, refusing `group:outside-home` as an argument; `unshare` unchanged;
  the read-only tool `permissions(focus="uses" | "rules" | "proposals" | "grants", ...)` for agents acting for the
  person; the `permit` tool (12.1); the sweep; pending lane notes; the `remember` guard; kept-copy subjects, genome
  sync included, and a copy's subjects read through `copies` (7.4); migration 029, which also marks a house made
  while a raised ledger exists (12.3); the gate.

**The person's yes in step 1** is section 7.6: whose yes it is, how it is given, the acts that need it, and its known
limits.

### Later steps (separate specs, in order)

1. **Network (step 2).** People say yes in the station's browser, and the station signs each record with
   `PeerIdentity.sign_record` under new kinds (`permission-record`, `permission-revocation`, `permission-grant`,
   `place-registration`), added to `RECORD_KEYS` (`peer/superyak_peer/identity.py:76-83`) and checked by
   `verify_record` (`:189-199`). The imprints spec already defines the first station-signed kinds,
   `imprint-permission` and `imprint-receipt` (its sections 8 and 12). Each `imprint-permission` wraps records in the
   5.1 form, less the five ledger-only fields (5.1), so a `permission-record` signs the same form, and step 2 adds no
   second one (Rio Grande's call, from the interface pass). From then on, an outside-home allow needs the `browser`
   channel. Requesters authenticate as station ships. Each person says yes for themselves, so co-subjects and
   self-claims become real (7.4). Receipts about a person go to their home ledger. Withdrawal notices go to every holder
   with a receipt, and so do subjects and lane-limited denies recorded later on a source that a holder keeps a copy of
   (5.3, 7.4). The `remember` guard learns of deliveries decided elsewhere (section 10). The imprints spec's transport
   lands here. Step 2 also decides what a subject sees of another subject's home in receipts (9.2). As written, a
   subject sees the records and outcome of every receipt that names them, so a co-subject such as Jenn would see
   Andy's home's layer and record ids, while 9.4 keeps home rules readable only by their person (the check of
   revision 4, BS3).
2. **County stations (step 3).** The county's root place and stewards, its ceiling, joint places, public
   `PlaceRules` pages, the place view of receipts. A decider keeps copies of the `PlaceRules` of every place in the
   chains it decides for, and refuses when a copy is older than a bound the county sets. **A question step 3 must
   answer:** home rules are private (9.4), but whoever decides a use of Andy's memory must evaluate his home layer
   (6.3, item 1). So either the person's own machine decides every use of their memories, or the records of a home
   that reach a place are disclosed to that place's decider. This spec does not choose.
3. **Data classes (step 4).** A shared vocabulary such as `class:health`, so places can write rules about kinds of
   content. Labels cut both ways (a label can match an allow or a deny), so only the person sets one. A name detector
   that only adds co-subjects (7.4). Andy answered on 2026-10-26 whether memories that mention other people may
   move (A6). P36 (6.3) applies his answer, and section 19 says how.
4. **Routes on the rail.** The trail spec and its later steps use `route` across lighthouses, one edge per answer use
   (6.4).

### Non-goals

- Encrypting copies, attesting purposes, or erasing content from an agent's context or from a transcript.
- A claim of compliance with any health-privacy or records law. The county's counsel decides that.
- Checking a store's own sessions recalling their own store. That is the person's own memory in their own home. It
  leaves no receipt, which departs from the vision's principle 5; section 19 puts it to Andy.
- Instincts, dream residue, task contexts and the knowledge graph as objects. They never leave.
- A consensus screen for several people. Each person says yes alone, and the meet combines them.
- Removing a place's parent edge, deleting a place, or giving a root a parent.
- A selector that names the copy h. No selector names h in this spec. h reaches a decision only through the holding
  place's layers (6.1, section 8).

### Anti-goals (failure even if the code works)

- **Widening by an agent.** Any agent act that makes a use allowed which no person-signed record or envelope covers,
  or that removes a person's deny (L4).
- **Widening by a derived signal.** A lane move, a write-time lane or store choice, a classifier, an embedding or a
  category that adds an allowed use outside a home (L5, P28).
- **Picking a winner.** Resolving a disagreement by anything other than the meet and a person.
- **Overriding a no.** A use allowed against a deny that matches it in a required layer, P36's included (6.3).
- **Content in receipts.** A receipt holding content or query text.
- **Secret place rules.** A place's decisions that cite rules its people can't read (homes excepted, 9.4).
- **Trusting the requester's clock.** A requester's time extending any record.
- **Existence leaks.** A requester learning that a refused memory exists (P23). A bulk refusal names no object
  (6.4).
- **A showing decided in bulk.** A use decided as one bulk use whose answer names an object or shows content to an
  agent. Only counts, rates and digests may leave a bulk use (6.4, P33).
- **Waiting caches.** A revocation, an expiry or a dated start that takes effect later than the next decision at or
  after its time (L8).
- **Failing open.** A missing, unreadable or unknown gate, a house that should carry the ledger's id and doesn't, or
  a config edit, that turns checks off once the gate has been raised (12.3, P21). Also a lowered gate that serves an
  outside-home placement (12.1, P29).

## 15. Constants (calibration hypotheses unless marked)

| Constant | Value | Purpose |
|---|---|---|
| Records per layer | 256 effective | bounds a decision |
| Audience entries / list values / memories per selector | 32 / 64 / 512 | bounds a record |
| Purposes per record | 16 | bounds a record |
| Subjects per object | 8 | bounds `Req`; for a kept copy, the union with its source's subjects (7.4) |
| Collection size | 100,000 | bounds membership checks |
| Collection name | 80 characters | room for `legacy-group-<g>` (12.3) |
| Places per ledger / parents per place / name depth | 1,024 / 4 / 8 segments | bounds dominance |
| Ancestors per place | 16, itself included | bounds `Req`: 8 subjects + 16 + 16 + 2 legacy + 1 restriction ≤ 43 layers (fixed to match 6.4) |
| Memories named per answer use on a road or trail | 32 | bounds what one answer names to an agent, and what one decision costs (6.4); bulk uses waive it |
| Objects per bulk use | 512 when its receipt names them (such as an imprint batch, or one of the evaluation's `read` batches); 100,000 when they are derived and never named | bounds a bulk decision and its receipt (6.4, 9.1); a larger set is several bulk uses. 512 is the `memories` list bound and 100,000 the collection size (fixed to match) |
| Memories named per bulk use | 100,000, by all its roads and trails together | with the row above, bounds a bulk decision to 400,000 (object, action) pairs (6.4); a larger set is several bulk uses. The collection size (fixed to match) |
| `copies` chain read at a decision | 4 links | bounds a copy's subjects (7.4); a longer chain is refused when the copy is made |
| Outside-home allow lifetime | 366 days | renewal by the person |
| Grant chain / lifetime | 3 links (a root's depth at most 2) / 720 hours | spec A's defaults (fixed to match) |
| `replaces` chain | 16 | bounds rule 4 of 5.3 |
| Proposal lifetime | 7 days | |
| Box cap | 4,096 | bounds the check |
| Boxes per record | `64 × (1 + k)`, k the grant chains behind its members | bounds the check (the box cap still applies) |
| Joint places checked per change | 64 | bounds the check |
| Sweep per pass | 256 placements | bounds startup work |
| Eligible-set cache | 64 entries and 96 MB, whichever comes first | bounds daemon memory (12.2); the 96 MB is Rio Grande's call, from the daemon's memory budget (below) |
| Placements per published house | 20,000 | bounds a cache rebuild on a Pi |
| Eligible-set rebuild | 2 s on the station's Raspberry Pi 5 | the Pi budget (12.2) |
| Bulk decision | 40 s on the station's Raspberry Pi 5, for a bulk `imprint` of 100,000 derived objects whose `need` names 100,000 memories, the largest that "Objects per bulk use" and "Memories named per bulk use" allow | the Pi budget for one bulk use at its largest (6.4), and so for `explain` on one (U24). It is the rebuild's rate: the rebuild makes 20,000 (object, action) decisions in 2 s, and this use at most 400,000 (three actions on each derived object, and `recall` on each memory) |
| `remember` guard | 200 receipts, 24 hours | bounds the check on each `remember`; its known limits are in section 10 |
| Houses read for the `off` rule | 64 | bounds the effective gate (12.3); with more houses, a reader reads closed |
| Receipt retention | 400 days, then monthly counts | Open for Andy for the county |
| Use list | counts, then at most 200 rows, newest first | bounds one `uses` listing (9.3) |
| Annotation | 240 characters; names cut at 32 | context cost per item |
| Confirmation code | 6 characters | step 1 terminal yes |
| Short id prefix | at least 4 hex, unique on the ledger | 4.1 |
| Receipt short form | `#` and 8 hex | the agent's handle on a receipt (4.1, 11); fixed to match the trail spec's receipts |
| Peak resident memory | 512 MB per process, measured on the Pi | Andy's decision of 2026-10-26 (A7; vision, principle 4). The number, and the 2 GB Raspberry Pi it is for, are Rio Grande's call (P37). It holds for the daemon and for each operation U24 measures (below) |
| Reference ledger | 100,000 memories, each with 8 subjects (its store's owner and 7 co-subjects, each added by an act of its own), 3 lane notes (a first note, then one re-lane, in passes of 256) and one collection membership (in collect acts of 10,000); 41 ledger layers of 256 effective records in U24's mix; and the log rows that wrote them all, about 811,000 | the ledger U24 measures memory on. Rio Grande's call: the collection size, the subjects bound and a decision's 41 ledger layers, each at its bound |
| Per-object rows a State holds | 65,536 rows, and 65,536 log times | bounds a State whatever the store's size (5.6). Rio Grande's call |
| Records per ledger | 16,384, revoked and replaced ones included; a write past it is refused (5.4), and a ledger past it reads as unreadable (5.6) | a State holds the records whole, and the daemon's budget holds only up to about 20,200 records (below). Records grow with acts and places, not with the store. Reading them per layer lifts the bound, and is due before a ledger needs more. Rio Grande's call |
| Objects per `collect` or `uncollect` act | 10,000; a larger set is several acts (5.4) | bounds one act's body in `perform` and in `rebuild` (below). Rio Grande's call |
| Frames deciding at once | 2 | bounds the daemon's States (12.2). Rio Grande's call |
| Candidates per recall | 20, whatever `k` the frame names | bounds a recall's receipt and its `use_subjects` rows (12.2, 9.1). Fixed to match engram's client (`engram/lighthouse_client.py:17`); Rio Grande's call |
| Receipt fold batch | 4,096 receipts per transaction, read one at a time | bounds the fold's transaction; its memory is one receipt (9.1). Rio Grande's call |
| Box refs per State | 2,000,000 memory refs in the sets held at once: a State's kept layer boxes, plus the current check's sets; past it, "could not check" | bounds the check's memory, as the box cap bounds its boxes (8, U15). Rio Grande's call |
| A systemd unit's memory | `MemoryMax=512M` or less on each unit this work adds; step 1 adds none | Andy's decision; the number is Rio Grande's call |

Everything runs on a Raspberry Pi. It needs only Python's standard library and `sqlite3`: the vision allows numpy,
and nothing here needs it, or a GPU. Every pass is bounded by the table. The definitions in sections 4 to 8 are the
connector standard. An implementation conforms when it gives the same decisions on the shared fixtures (test F1), as
the local city's two policy evaluators must agree (local-city spec, section 4.4).

**Memory** (revision 7). Andy, 2026-10-26: "remember the ram limitations of this machine, build this so that it can
run easily with small amounts of hardware." (A7) Rio Grande's call on what that means is the vision's principle 4
(P37). The target is a Raspberry Pi with 2 GB of RAM. Every process this work adds peaks under 512 MB resident,
measured on the Pi. On the reference ledger above, and with its records at their bound, each of these peaks under
512 MB (U24; the budget below):

- the daemon, serving recall and read frames for a house of 20,000 placements, with its cache full;
- one eligible-set rebuild for 20,000 placements (12.2);
- one bulk decision at its largest: 100,000 objects whose roads and trails name 100,000 memories, not grouped (6.4);
- `Ledger.state()` (5.6);
- `perform`, one act with its gluing check at the box refs bound (5.6, 8), which every writing command and
  `migrate` run;
- `engram-permissions rebuild`, `check` and `uses` (5.6, 8, 9.3);
- the receipts fold (9.1).

What grows with the store or the ledger streams or runs in bounded batches. Nothing holds a whole store, a whole log,
a dense matrix or a whole graph:

- a State reads per-object rows and log times when decisions ask, through its bounded cache. It holds the records
  whole only up to their bound, 16,384 (5.4, 5.6);
- `perform` holds one State at a time, and an act's body holds at most 10,000 collection members (5.4, 5.6);
- `rebuild` reads the log row by row (5.6);
- the fold reads one receipt at a time, in batches (9.1), and a recall's receipt names at most 20 refs (12.2);
- a bulk decision keeps, per object, only its subjects and which actions it decided, and keeps the earliest effective
  end as it goes (6.4);
- the decisions of an eligible set share equal citations, and the cache is bounded in bytes as well as entries
  (12.2);
- a gluing check shares sets where it can, and stops at the box refs bound (8).

The embedder is shared and never loaded twice: the daemon embeds through the shared embedder service and never loads
a model (12.2). Measured on the station's Pi on 2026-10-26, before these bounds, and scaled to the reference ledger
from measured sizes per row:
- `Ledger.state()` peaked at about 1.4 GB on the reference ledger;
- `rebuild`'s read of the whole log came to about 845 MB;
- one eligible set at 20,000 placements and 43 layers held about 182 MB, so the cache's 64 entries could reach about
  11.4 GB.

**The budget** (revision 7; Rio Grande's call). MB means 2^20 bytes, as systemd's `512M` does. Each figure is an
estimate. It adds the measured resident high-water of importing the daemon's modules, 30.3 MB, to traced sizes from
unit sizes measured on the station's Pi on 2026-10-26 with `tracemalloc` (Python 3.13). Each part is rounded to
0.1 MB before it is added. "At the bounds" means 16,384 records (5.4), full row and time caches, at most 20 candidates
per recall, and the largest receipt and act this spec writes. The units are:
- a record in a State, 4,126 B; a record's table row while a State builds, 2,877 B;
- a per-object row, 404 B; a log time, 97 B. So a full row cache is 65,536 × 404 B = 25.3 MB, and a full time
  cache 65,536 × 97 B = 6.1 MB;
- at the reference ledger's 10,496 records, 41.3 MB in a State and 28.8 MB while it builds. At 16,384 records,
  16,384 × 4,126 B = 64.5 MB and 16,384 × 2,877 B = 45.0 MB;
- so a State with full caches is 41.3 + 25.3 + 6.1 = 72.7 MB at the reference, and 64.5 + 25.3 + 6.1 = 95.9 MB at
  the bounds.

| Operation | Parts | Reference ledger | At the bounds | Margin at the bounds |
|---|---|---|---|---|
| `Ledger.state()` | 30.3 + the records' table rows while it builds + the records; then its row and time caches fill (+ 25.3 + 6.1) | 30.3 + 28.8 + 41.3 = 100.4; 131.8 with full caches | 30.3 + 45.0 + 64.5 = 139.8; 171.2 | 340.8 |
| Eligible-set rebuild, 20,000 placements | 30.3 + a State + the set 16.0 + `made` 1.8 + placements 6.0 | 126.8 | 150.0 | 362.0 |
| Bulk decision at its largest (6.4) | 30.3 + a State + the run 47.5 + the caller's 100,000 trail refs 13.6 | 164.1 | 187.3 | 324.7 |
| The fold (9.1) | 30.3 + one receipt + one connection's page cache 2.0 | a recall of 20 refs with 8 subjects each: 160 (subject, ref) pairs × 671 B = 0.1, so 32.4 | a named bulk receipt of 512 objects with 8 subjects each, 4,096 pairs × 671 B = 2.6, citing 256 records in each of 40 consent layers for 3 actions, 30,720 ids × 37 B = 1.1, held about 3 times = 3.3: 38.2 | 473.8 |
| The daemon (12.2) | 30.3 + 2 frames × (a State + a set being built 23.8 + met decisions 15.5 + objects 7.2) + the cache 96.0 + page caches 15.6; then one frame's build transient | 30.3 + 2 × 119.2 + 96.0 + 15.6 = 380.3; + 28.8 = 409.1 | 30.3 + 2 × 142.4 + 96.0 + 15.6 = 426.7; + 45.0 = 471.7 | 40.3 |
| `perform`, one act and its gluing check | 30.3 + one State + box refs 80.0 + the act's insert list, 10,000 × 753 B = 7.2 | 190.2 | 213.4 | 298.6 |
| `check` (8) | 30.3 + a State + box refs 80.0 | 183.0 | 206.2 | 305.8 |
| `uses` views (9.3) | 30.3 + a State + the 200 rows shown, each at most about 40 KB in step 1, held about twice: 15.6 | 118.6 | 141.8 | 370.2 |
| `rebuild` (5.6) | 30.3 + its largest log row, a `collect` act of 10,000 members, measured replaying at 35.7 + two connections' page caches 3.9 | 69.9 | 69.9 | 442.1 |

Where the parts come from:
- **The fold.** Verifying one receipt was measured at 671 B per (subject, ref) pair: 102.4 MB for one recall of
  20,000 refs with 8 subjects each. The largest receipt step 1 writes is a named bulk receipt, such as an imported
  imprint batch with its co-subjects, at 512 refs × 8 subjects. A receipt's `cited` holds at most 256 records for
  each of 40 consent ledger layers and 3 actions, as the row, its canonical JSON and their UTF-8 bytes. Before this
  revision the fold held a whole batch: 4,096 recalls of 20,000 refs each would have held 4,096 × 20,000 × 89 B =
  6,953 MB of `returned` alone.
- **The daemon.** A frame is 72.7 + 46.5 = 119.2 MB at the reference and 95.9 + 46.5 = 142.4 MB at the bounds. Each
  recall's receipt adds at most 160 pairs × 492 B = 0.1 MB, measured at 492 B a pair (75.1 MB for one receipt of
  20,000 refs with 8 subjects each). Without the cap of 20 candidates, two such receipts at once would add 150.2 MB.
  The cache holds 6 eligible sets at the bound: 6 × 15.99 MB = 95.9 MB.
- **The records bound.** The daemon's parts that don't grow with the records come to 30.3 + 2 × (25.3 + 6.1 + 46.5)
  + 96.0 + 15.6 = 297.7 MB. Each record adds 2 × 4,126 B in two States and 2,877 B in one build: 11,129 B = 0.0106 MB.
  So the daemon fits only up to (512 − 297.7) / 0.0106 = about 20,200 records. At 32,768, revision 7's first draft,
  it would reach 297.7 + 32,768 × 11,129 B (347.8) = 645.5 MB, or 555.6 MB without the build. At 16,384 it is
  297.7 + 16,384 × 11,129 B (173.9) = 471.6 MB, which is the table's 471.7 with its parts rounded first.
- **`perform`.** One State at a time (5.6): 30.3 + 72.7 + 80.0 + 7.2 = 190.2 at the reference, 30.3 + 95.9 + 80.0 +
  7.2 = 213.4 at the bounds. Before the check, a `collect` act at its bounds holds the collection's members as a set
  of at most 100,000 refs (16.8) and its body at 10,000 members, measured at 4,009 B a member with its first lane
  note (38.2): 30.3 + 95.9 + 16.8 + 38.2 = 181.2, under the figure. Holding three States, as `perform` does today
  (5.6), would be 30.3 + 3 × 95.9 + 45.0 + 80.0 = 443.0 at the bounds. A `collect` of 100,000 members in one act would
  hold 100,000 × 4,009 B = 382.3 MB of body, and its replay in `rebuild` 100,000 × 3,742 B = 356.9 MB.
- **`uses`.** In step 1 the largest row a view shows is a recall's: 20 refs, and at most 20 records cited in each of
  40 consent layers, 40 × 20 × 37 B = 29,600 B, with its other columns under 40 KB. So 200 rows × 40 KB = 7.8 MB,
  held about twice.
- **`migrate`** runs once, on the ledger it has just made, so its States hold few records. Its acts are `perform`'s,
  each `collect` of at most 500 members (`engram/permission_cli.py:755`), and the share rows it reads carry no
  content (`engram/migrations/027_shared_memories.sql:1-11`). U24 measures it.
- **The engram server** is not a process this work adds. It already peaks at about 320 MB with the shared embedder
  (`engram/CLAUDE.md:44-45`, measured 2026-10-02). This work adds to it, one permissions call at a time, at most what
  one `perform` holds above its imports, when `permit` writes: 159.9 MB at the reference and 183.1 MB at the bounds.
  So the server may reach about 480 MB and 503 MB. It also folds at each start (`engram/server.py:2205`), one receipt
  at a time. 512 MB doesn't bind it, since this work doesn't add it.

**Margin** (Rio Grande's call). The figures are traced bytes over a measured base, and how far resident memory runs
above traced bytes was not measured. The daemon at the records bound leaves the least, 40.3 MB (8 %). If a daemon run
in U24 reads 480 MB or more, the first lever is a cache of 64 MB (32 MB less). The second is one frame at a time (one
frame less: 119.2 MB at the reference, 142.4 MB at the bounds).

## 16. Components

| Component | Responsibility |
|---|---|
| `engram/permissions.py` | Pure functions: name and copy-ref grammars, selector parsing and checks, dominance and ancestry, matching with history, `need` with named memories, `decide` for single and bulk uses with its codes and a candidate's grant chains, `until` and horizon, boxes with collection expansion, narrowing and envelope checks, the gluing check and ineffective parts, proposal words. P36's reading of a co-subject's layer for a qualifying use (6.3). Shared citations in an eligible set, a bulk decision's small working set per object, and the box refs bound (15, "Memory"). No I/O. |
| `engram/permission_ledger.py` | The ledger: schema, log with hash chain, projections, `state(seq)` with its bounded reads of per-object rows (5.6), the records bound and the act bound (5.4), `perform` holding one State at a time (5.6), `rebuild` reading the log row by row, read-only open, the gate and the effective-gate rule over houses, marking every house with the ledger's id at the raise, a copy's subjects through `copies`, `PlaceRules` export, proposals, kept-copy rows, the sweep's queries. |
| `engram/permission_uses.py` | The receipts file: writes in `BEGIN IMMEDIATE` with the hash chain, single and bulk receipts (named and counted, 9.1), owner view, which marks imported station rows and counts them apart (9.3), place view with pseudonyms, the retention fold in batches, one receipt at a time, each batch with its anchor (9.1). The imported rows themselves are written in 9.1's imported form by the imprints spec's `import-receipts` (its section 15). |
| `engram/permission_cli.py` | `engram-permissions` (section 14), acting only as the ledger owner, with the terminal yes. A command that adds or removes more than 10,000 collection members splits them into acts under its one yes (5.4). `gate` refuses a raise without a published house (12.3), and `explain` takes single and bulk uses. A `[project.scripts]` entry and a `py-modules` entry in `engram/pyproject.toml`. |
| `engram/lighthouse_daemon.py` | Decisions before retrieval and read, each placement with its object and copy h (12.2), the cache with the horizon and the change counter, receipts, the `permission` member, the placement audience, stripping `group:outside-home` from every policy's audiences under every gate and with no ledger, and adding it back only under `enforce` (12.1), the effective gate over the houses it serves (12.3), the cache's byte bound, at most 2 frames deciding at once, at most 20 candidates per recall, and the shared embedder only (12.2). |
| `engram/lighthouse_client.py`, `engram/neighbors.py`, `engram/context_lighthouse.py` | Accept and pass `permission`, rendered as one line; the receipt extension. |
| `engram/sharing.py`, `engram/server.py` | `share` through records, refusing `group:outside-home` as an argument; `record_id` and `source_instance_id`; the `permissions` and `permit` tools; the sweep; the `remember` guard reading `permission-uses.db`; kept-copy subjects; the lane listener; the effective gate over the published house (12.3). |
| `engram/storage.py` | The two-call lane listener hook in `set_episode_lanes`. Migration 029's step in the migration loop: inside 029's transaction, it writes `permissions_ledger_id`, or `unreadable`, into a house created while a raised ledger exists (12.3), as the loop runs `_assign_instance_id` for 028 (`engram/storage.py:228-230`). |
| `engram/federation.py` | Kept-copy subjects for synced genome episodes. |
| `engram/policy_gen.py` | Refuses a group named `outside-home`. |
| `engram/migrations/029_share_identity.sql` | `shared_memories.source_instance_id`, `shared_memories.record_id`, and the placements' change counter with its triggers. Marking a new house is `Storage`'s step for 029 (row above), since it reads the ledger, another file. |
| `engram/tests/test_permissions*.py`, fixtures in `engram/tests/fixtures/permissions/` | Section 17. |
| `engram/config.py` | `load_config` warns when `config.toml` has a `[permissions]` section, which it ignores, and names `engram-permissions gate` (12.3). Nothing else: the ledger's path is fixed (5.5) and the gate lives in the ledger (12.3). |
| `engram/CLAUDE.md` | A "Permissions" paragraph, Key Files rows, and the rule that agents never run, for the person, any `engram-permissions` command that writes (7.6). |

## 17. Tests the builder must include

Each test is named, written first, and seen failing first. The property tests use `random.Random` with a recorded
seed, 500 cases each, as spec A does. Their oracle is a small brute-force evaluator in the test, written from sections
5 and 6 over a small finite universe, never from `permissions.py`.

**Property tests (monotonicity and safety)**

- **PT1 Meet.** For random layers and uses, adding any layer to `Req` never turns a refusal into an allow (L1).
- **PT2 Narrowing ops.** For a random layer and a random op from 7.2's narrowing list, every use allowed after is
  allowed before (L3). Every narrowing op is also tried on random consent-layer denies, and each attempt is refused
  or filed as a proposal (P27).
- **PT3 Delegation.** For random chains of up to 3 links, every effective record's matches, and every match through
  a grant-backed membership, lie within `(Sig⁺ ∪ Env) \ Sig⁻` (L4). A child wider than its parent in any field is
  refused, and so is a fourth link.
- **PT4 Nesting and dominance.** On random DAGs of up to 12 places: what is allowed at a place is within each
  ancestor's layer at that place; an allow to `place:Z` never matches a place with a path around Z; adding a parent
  edge to a place that has one never adds an allowed use; a parent edge on a root is refused (L2, 4.3, P26).
- **PT5 Unchecked changes.** Random lane moves, pending notes and removals from collections, groups and places never
  add an allowed use (L5).
- **PT6 Replacements.** Replacements draw random selectors and random validity intervals, some later or earlier than
  their original's. After random registry changes, a replacement never matches a use, at any time, that its chain
  doesn't (5.3 rule 4).
- **PT7 Subjects.** Adding subjects never adds an allowed use. A road's subjects include its endpoints'. A kept copy
  carries every subject of its source, and an allow at the keeper's place alone never lets it out (L6, P25). A subject
  added to a source after a copy was made, on the same ledger, refuses the copy's next use too, through chains of up
  to 4 copies; a deeper chain is refused when made (7.4).
- **PT8 Revocation and expiry.** A record revoked at `seq` s is never cited at s or later. No use at or after
  `valid_until` is allowed by it.
- **PT9 Boxes.** Intersection, difference, emptiness and subset agree with brute force on universes of up to 3 values
  per dimension and 4 time points.
- **PT10 Determinism.** The same decision, cited records, `until` and horizon, whatever the insertion order, and after
  replaying the log to the same `seq`. A State that reads per-object rows when asked (5.6), asked only after later
  ledger writes that add, remove and re-lane those rows, decides as a State read whole at its own `seq` (revision 7).
- **PT11 Gluing.** Δ and ineffective parts from boxes equal those of a brute-force oracle with the same collection
  expansion, at the current state. A fixture covers the collection case: m in C1 and C2, own allows C1, parent A
  allows C2, parent B allows C3. It must report a disagreement.
- **PT12 Horizon.** For random states and uses, the decision is the same at every time in `[t, horizon)`, and
  `horizon ≤ until` (L8).

**Unit and regression**

- **U1** The ConnectionPolicy counterexample (6.2): narrowing A's selector turns a deny into an allow under
  most-specific-wins.
- **U2** Names and places: grammars; the name rule; no cycles; a root refuses a parent; a joint place waits for every
  parent's steward; depth and count limits; retiring a place stops its sub-places; retiring a person; one place per
  agent.
- **U3** Write rules: an outside-home allow needs purposes and an end at most 366 days out; an inside-home allow may
  use `"*"` and no end; an outside-home memory allow without a finite `memories` or `collections` list is refused, and
  so is a road allow without a finite `stores` list (P28); each bound in 5.4 refuses with its reason, among them the
  16,385th record of a ledger and a `collect` act of 10,001 objects, while a revocation at the records bound is
  written; a CLI command that adds 25,000 members writes 3 acts under one yes (revision 7).
- **U4** Who may set what, as one table: actors (the person, a steward, an agent with a valid, expired, revoked or
  too-deep grant, an agent without one, another person) against the acts in 7.1. Each cell is allowed, refused or a
  proposal, as 7.1 says. A grantee can give its own grant up.
- **U5** Co-subjects: a memory about Andy and Jenn is refused on Andy's yes alone, for every use P36 doesn't cover
  (U29 tests the ones it does); Andy can remove a co-subject his
  agent added; he can't remove one Jenn claimed herself or one a kept copy carries; a self-claim appears in Andy's
  list; a co-subject added to a source is written even when a copy's subjects would then number more than 8, and the
  copy's next use is refused with `BOUND` (7.4).
- **U6** Lanes: a memory moved from personal to work after a work-lane allow is not covered; one moved from work to
  personal stops being covered; a deny on personal still matches after a move to work; a failing first note refuses
  the re-lane.
- **U7** Backing: revoking a grant ends its `share` records and `collect` memberships and keeps person-backed
  replacements and every deny the agent wrote.
- **U8** Receipts: a recall writes one receipt with returned refs and a filtered count and no subjects for filtered
  copies; a read writes one per item; none holds content or query text; a subject sees only receipts whose
  `use_subjects` named them at the time; pseudonyms are stable in a place and differ across places; agents in a place
  see no filtered counts; home rules are not exported; the hash chains verify and one changed byte fails; every
  receipt carries its copy h; rows in 9.1's imported form are marked with their station and counted apart from local
  ones, `uses --action X` matches each row's own action, and `uses --object` finds an imported memory row (9.1,
  9.3); an agent's view of its own refused read, single or bulk, shows "not allowed" with no code, layer, action or
  cited record, while the owner's list shows the layer; a steward's view shows a refusal's layer as the place's id
  when the place is not a home, and as the person's pseudonym when it is a home, and shows no home's record ids
  (9.2; the final check after repair, AS2).
- **U9** Daemon: `enforce` needs both decisions; `shadow` delivers by the legacy path and records both; the ledger's
  bytes are unchanged and `total_changes` is 0; a frame's `at` in the future extends nothing; the cache recomputes on
  a new `seq`, a new change count, and at the horizon; refused copies never appear among candidates; a refused read
  item has `content: null`, `audiences: []` and no `permission`; the client accepts `permission` and still rejects any
  other unknown member; the 20,001st placement is refused; the cache holds at most 96 MB by its estimate, the
  estimate is 1.0 to 1.6 times a measure, and an entry larger than 96 MB is not kept; at most 2 frames decide at once,
  and the others wait; a recall frame with `k` = 21 or more returns at most 20 candidates, and its receipt names at
  most 20 refs; a ledger read that fails during a decision serves nothing under `enforce` (12.2, revision 7).
- **U10** Receivers: `permission` reaches each delivered item in `response["neighbors"]["delivered"]` as one line of at
  most 240 characters, with long place names cut and `+N`, and the receipt's short form has 8 hex; the context
  runtime's `_evidence` carries it; the RecallReceipt still validates against its schema, with the
  `engram:permissions` extension.
- **U11** `share` under `enforce`: with no covering allow it changes nothing and returns the `permit` call; with one,
  it places a copy with the placement audience (P29) and `record_id`; `permit` inside a grant's envelope writes a grant-backed
  record, and outside it files a proposal; `unshare` always works.
- **U12** Sweep: after a revocation or an expiry the placements go within one pass, at most 256, and the copy goes
  with its last share row; it settles pending lane notes.
- **U13** Migration:
  - shares become memberships of one collection per legacy audience, with one allow each;
  - a fixture with more than 256 shares migrates;
  - a row whose source fell back to the default store fails the digest check, is listed, and is refused under
    `enforce`;
  - in shadow, on a fixture with `commons`, two groups and both legacy policies, the legacy path allows nothing the
    new one refuses, except listed rows;
  - each source store's bytes are unchanged while `source_instance_id` is filled;
  - every house, the published house among them, and each source store are registered with Andy's home as their
    place, and use 1's holding place resolves (12.3 step 2; the re-check's RN6).
- **U14** Proposals: one at a time; they expire after 7 days; their words come from the body, never from the agent;
  `sign` prints the full selector; signing writes a person-backed record with its `proposal_id`; declining writes
  nothing else.
- **U15** Gluing and ineffective parts: each is reported to the right stewards, at single-parent and joint places;
  the check reruns after a registry change; hitting the box cap, or the box refs bound (15), reports "could not
  check".
- **U16** Gate:
  - with no ledger, the existing daemon, neighbor and sharing tests pass unchanged;
  - a `[permissions]` section in `config.toml`, or a config that fails to parse, changes no mode, and the section
    logs one warning that names `engram-permissions gate`;
  - once the gate has been raised, each of these fails closed: a deleted ledger, an unreadable ledger, a ledger with
    another `ledger_id`, and an unknown `meta.gate`;
  - closed serves nothing and refuses `share`;
  - only the terminal yes moves the gate;
  - a raise with no published house is refused;
  - the raise marks every house; a house created after the raise gets the ledger's id at creation, and one created
    while the ledger can't be read gets `unreadable` and reads closed;
  - a deleted ledger reads closed for every reader, even one whose house was made after the deletion, while any
    house still carries the id;
  - a publisher house added to the daemon's config without the id, under a raised ledger, reads closed until
    `gate` marks it;
  - with no ledger and more than 64 houses, a reader reads closed (the re-check's RS6, for every house case above).
- **U17** `remember`: verbatim delivered content is refused unless `imprint` is allowed, whether it came through
  `neighbors.py` or the context runtime; when allowed, the kept memory carries its source's subjects; a co-subject
  added to the source afterwards refuses the kept copy's next use; with a co-subject (`person:amy`) recorded on m1
  after its delivery, so that `place:home/amy` is the first failing layer, the guard's reply to an agent that doesn't
  act for the owner, and that agent's view of the receipt, name no code, layer or action (section 10; the check of
  revision 4, BS1).
- **U18** The terminal yes: refused without a terminal; a wrong code writes nothing; no command acts as anyone but
  the ledger owner; each act in the table of 7.6 is refused through the MCP tools (filed as a proposal) and works
  only with the yes.
- **U19** Horizon: a deny dated to start later refuses at its start, with no ledger write in between; a grant-backed
  membership stops counting at its grant's expiry, with no write; `until` is cited per (layer, action); a legacy
  policy rule whose `validUntil` comes before the decision's `until` refuses from the next request after it, while
  the annotation shows the ledger's `until` (6.5 step 6; the re-check's RN3).
- **U20** Audience: `place:Z` needs the agent's acts-for place within Z's domain; `self` and own-group allows don't
  match outside the home; putting an agent in a place needs its principal; a second place is refused.
- **U21** Subjects and houses: an object in an unregistered store, a placement with no `source_instance_id`, or a use
  whose copy h names an unregistered store, is refused with `NO_LAYER`; the same ref held in two houses is decided
  with each house's place (6.1, 6.3).
- **U22** Roads, trails and bulk uses:
  - a route answer that shows a summary needs `read` and `inject_context` on that memory, and one that names a
    memory needs `recall`;
  - a `recall`, `read` or `imprint` of a trail needs `recall` on every memory it names, and is refused when one of
    them may not be recalled (P35; the re-check's RS4);
  - an answer use naming 33 memories is refused with `BOUND`, and so is a trail of 33 touches used as one edge; an
    answer that walks 5 roads is 5 `route` uses with 5 receipts;
  - a bulk `route` over 3 trails of 40 touches each, from which only counts leave, is allowed when every per-object
    use is, with one counted receipt naming no object; the same trails as answer uses are refused with `BOUND`;
  - a named bulk use, an imprint batch, writes one receipt holding its count and the SHA-256 of its sorted objects,
    with their `use_subjects` rows (9.1);
  - a bulk use with one failing object is refused with that object's code, layer and action, and the refusal names
    no object; its `cited`, `until` and `horizon` follow 6.4;
  - a bulk use of 100,001 derived objects, or a named one of 513, is refused with `BOUND` before any object is
    decided, and with `UNKNOWN_REQUESTER` when its requester is also unregistered;
  - a counted bulk use over derived trails whose touches name 100,001 distinct memories is refused with `BOUND`
    before any object is decided; the same trails split into two bulk uses, each naming at most 100,000, are each
    decided object by object (6.4, "Named memories"; the check of revision 4, BS2);
  - a bulk use with an object that has no subject is refused with `NO_LAYER`, and one with an object of 9 subjects
    with `BOUND`, unless an earlier object in ref order fails first (6.5, step 1);
  - the imprints spec's `Need(trail-evaluation)` and `Need(admission)` on a fixture imprint, decided by this spec's
    `decide`, give that spec's verdicts (P33; the re-check's RMF1). One fixture imprint carries no co-subject. A
    second, kept in the owner's home, has memories that carry a co-subject with no layer, as at a station in step 1:
    each of its uses is allowed under P36, as that spec's check allows it (6.3; its section 8).
- **U23** Placement audience: each row of the mapping table in 12.1, including an allow naming two groups (the
  re-check's RN5); a `group:outside-home` placement is never served under `off` or `shadow`, or with no ledger, even
  when a hand-written policy lists `group:outside-home` for the receiver (the re-check's RS1); `share` refuses the
  name as an argument; `policy_gen.py` refuses a group named `outside-home`.
- **U24** The Pi budget: on a generated fixture of 20,000 placements and 43 layers of 256 records, one eligible-set
  rebuild takes at most 2 s on the station's Raspberry Pi 5. On a fixture of 100,000 derived roads and trails that
  name 100,000 memories, the largest bulk use 6.4 allows, against the same layers, `explain` on one bulk `imprint`
  takes at most 40 s there, with objects that don't group (the final check's FN3). Its trails have 512 touches each,
  the trail spec's cap, so the decision reads 51.2 million touches though it makes at most 400,000 decisions (the
  cross-check's XN3). Marked slow, and run on the Pi.
  - **Memory** (revision 7). Each of these runs on the reference ledger (15) in a fresh process of its own:
    - the two timed decisions above;
    - `Ledger.state()`;
    - `perform` of an `allow` in a parent's layer of a joint place, whose gluing checks meet collections of 100,000
      members, and of a `collect` of 10,000 members into a collection that holds 90,000 (5.4, 5.6);
    - `rebuild`, whose log holds that `collect` act;
    - `check`, and `uses` for the owner and for a place;
    - the fold of 100,000 receipts, each a recall that cites 43 layers and returns 20 refs with 8 subjects each,
      among them, in the first batch, 64 named bulk receipts at the largest: 512 objects with 8 subjects each,
      citing 256 records in each of 40 consent layers for 3 actions (9.1);
    - a daemon serving recall and read frames from 3 threads, for a house of 20,000 of the ledger's memories, with
      its cache filled past 96 MB. It runs once on the reference ledger, and once with 5,888 revoked records added,
      so that the ledger holds 16,384, the records bound.

    `migrate` runs the same way on a house of 20,000 shares with no ledger. Each process's peak resident memory,
    `VmHWM` in `/proc/self/status`, stays under 512 MB, which is 524,288 kB, since MB means 2^20 bytes (15). The test
    records each peak beside its estimate in section 15's budget. Each runs as the user under
    `systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0`, as `engram/CLAUDE.md`'s test command does, so a
    breach fails as an out-of-memory kill. Rio Grande's call: a process's peak doesn't depend on how much RAM the Pi
    has, so the station's 16 GB Pi 5 measures for the 2 GB target. Any error is in the safe direction: this Pi's
    kernel (`6.12.109+rpt-rpi-2712`) uses 16 KB pages (`getconf PAGESIZE` gives 16384), so a resident figure here is
    no lower than on a Pi with 4 KB pages.
- **U25** Lane notes: a failed `UPDATE` settles to the old lane; a crash between the two calls leaves a pending note
  that allows read as neither lane and denies as both; a memory with no note matches no lane-limited allow.
- **U26** Ids: the CLI takes full ids and unique prefixes, and refuses an ambiguous prefix with its matches.
- **U27** Receipt writes: the daemon and a server writing at once keep one valid chain; after the 400-day fold, the
  chain verifies from its anchor; a fold of more than 4,096 receipts works in batches, each with its own anchor, and
  a break in the chain stops it at the batch that holds the break (9.1, revision 7). A receipt younger than the cutoff,
  at a lower `seq` than older ones, stops the fold there: no anchor passes it, and the older ones after it wait for a
  later fold. A fold of receipts whose rows hold 1 MB each keeps one receipt at a time, so its peak doesn't grow with
  the batch's bytes.
- **U28** Refusal codes: a fixture for each code's condition in 6.5, including `EXPIRED` against `GRANT_INVALID` and
  `NOT_YET` on one record, and use 10's read of m4: `GRANT_INVALID` before G1's expiry and `EXPIRED` after, since a
  candidate's chains include those of the memberships it matched through (6.5; the re-check's RS7).
- **U29** The owner's own copies (P36, 6.3; revision 7). m3 is about Andy and Jenn. Andy's layer allows `recall`,
  `read`, `inject_context`, `imprint` and `route` for his own agents inside his home. So that each refusal below falls
  at Jenn's home and not at his (the re-check's RCS3), it also holds outside-home allows for the uses that would
  otherwise fail there: `commons` narrowed by `requesters` to his agent working at an outside place Q and to an agent
  b that acts for Lee and works inside his home, with named purposes and an end date (5.4), one naming m3 for
  `recall`, `read`, `inject_context` and `imprint`, and one naming his store for `route` on roads and trails. Jenn's
  layer is empty in one case, and she is unregistered in another.
  - Qualifying uses are allowed: an `imprint` of m3 by an agent acting for Andy, with P and H inside his home and the
    copy kept there; a named bulk `read` and a counted bulk `route` over trails that name m3, there. The decision
    cites no record in Jenn's layer, and shows it with kind `co-subject`, verdict `silent` or `missing` (6.3).
  - With any one condition false, each is refused as before, `NO_ALLOW` or `NO_LAYER` at `place:home/jenn`: the agent
    is b; P is Q; H is outside his home; the use is an answer use inside the home (a `recall`, `read` or
    `inject_context` of m3, or a `route` answer use on a trail that names m3). Each case first checks that Andy's
    layer allows that use, so the test fails if the refusal comes from his layer.
  - A memory from another person's store (the re-check's RC4). One of Andy's trails also names mj, a memory of Jenn's
    store with Lee recorded on it. Andy's bulk `route` over it at home is refused: `NO_ALLOW` at `place:home/jenn`
    with her layer empty, and `NO_LAYER` when she is unregistered. The trail's own decision qualifies; the `recall` on
    mj doesn't, since its store's owner is Jenn.
  - The `remember` guard's kept store (the re-check's RC4). An agent acting for Andy keeps m3, delivered from a copy
    inside his home, into a store whose `stores` row places it outside his home: refused at `place:home/jenn`. Into a
    store at his home: allowed. Into a store with no `stores` row: refused at `place:home/jenn` too.
  - A place co-subject that is also in `anc(P)` keeps its consent layer (6.3): with that place's layer silent, a
    qualifying use is refused there with `NO_ALLOW`.
  - With a deny in Jenn's layer that matches, each qualifying use is refused, `DENIED` at `place:home/jenn`. A deny
    dated to start later sets `until` and the horizon.
  - A self-claimed co-subject, and a co-subject a kept copy carries (`added_by` = `copy:<source ref>`), are read the
    same way.
  - A retired co-subject's home refuses with `RETIRED`, and a ninth subject with `BOUND`.
  - The kept copy carries Jenn (P25). A later answer use of it at home, and any use of it outside the home, is refused
    at `place:home/jenn`.
  - The oracle (section 17's opening) has P36, and agrees with `decide` on 500 seeded cases that include qualifying
    uses.

**End to end and conformance**

- **E1** Section 13, every step, under `enforce`, with its legacy fixtures, each use's copy h, expected decision,
  refusal code, `until`, horizon, receipt and annotation. Use 2 checks what the agent and the stewards see of the
  refusal (9.2). Use 13 checks both `remember` cases: refused within 24 hours of a delivery of m1, and passing on
  2026-12-15 with no source subjects (section 10's known limit; the final check after repair, AS1).
- **F1** Fixtures: JSON files of a ledger state, uses and expected decisions (`allowed`, `cited`, `refusal`, `until`,
  `horizon`), which any implementation can run. Every use carries its copy h. The fixtures include bulk uses, among
  them the trail evaluation on an imprint of section 6.4's last paragraph. They also include that evaluation and
  admission on an imprint kept in the owner's home whose memories carry a co-subject: allowed when the co-subject has
  no layer, and refused with `DENIED` at their home when their layer denies (P36). `cited` shows that layer with kind
  `co-subject`, as 6.3 fixes it.

## 18. Left to the builder

- Indexes, and the cache's data structure, within the bounds in section 15.
- CLI output formatting and the exact wording of errors, as long as each refusal names its rule. That is for the
  owner's CLI. What an agent that doesn't act for the owner is told of a refusal is fixed by 9.2 and section 10.
- The random generators for the property tests, as long as they reach every op, every membership kind, joint places,
  roots, pending notes, kept copies with chains of up to 4 links, bulk uses, and uses that qualify under P36.

## 19. Open for Andy

- **One permission he pictures an agent setting on its own**, without a person (vision). This spec's answer until he
  names one: none. An agent refuses for itself on its own, and widens only inside an envelope a person signed.
- **What the county sets** (vision): its ceilings, its receipts (how long they are kept, and whether its stewards see
  subjects only as pseudonyms), and who signs its law (who registers `place:la-county` and its stewards).
- **Pseudonyms.** As built, they are a display convention: whoever holds a place's ledger can compute every
  registered person's pseudonym (9.2). If the county needs more, the salts must live out of its decider's reach.
  Andy decides with the county question.
- **The step 1 yes.** Whether a terminal command is enough for his yes inside his own home (7.6, known limits), or he
  wants a passphrase-protected personal key before he sets `enforce`. From step 2, every yes outside his home needs
  the browser either way.
- **Agent shares at home under `enforce`** (12.3, step 4). A home grant lasts at most 720 hours, so his agents' home
  shares stop within 30 days. He may want a longer inside-home grant, which would change spec A's default for this
  table only, or to confirm his agents' shares in bulk with `allow` from time to time.
- **Two departures from the vision's principle 5**, "Every use of a memory leaves a receipt ... Every place publishes
  its rules". Home rules are private (9.4), and a store's own sessions recalling their own store leave no receipt
  (section 14, non-goals). Both follow principle 1, but they change principle 5's words. Andy decides.
- **One departure from the vision's principle 1**, "Anything about a person moves only with that person's yes": P36
  (6.3). Inside the owner's home, his `imprint` and his bulk uses that show nothing to any agent go ahead on a
  co-subject's silence, and only that person's deny stops them. Andy's own answer decided it ("yes you can copy the
  full store", A6), and the vision records that answer in its "Open for Andy", but the principle's words don't say
  it. Rio Grande's call to list it here, as the departures from principle 5 are. Nothing more is asked of Andy.
- **Who decides in the county steps** (section 14, step 3): the person's own machine, or the place's decider with the
  person's records disclosed to it.
- **The license** (vision, principle 3). This spec adds only standard-library code to engram, which has no license
  yet.
- **Memories that mention other people** (family, colleagues, patients). **Answered 2026-10-26, and applied as P36.**
  Andy, the owner, said: "yes you can copy the full store" (A6). The vision records it with Rio Grande's reading:
  memories that mention other people may be copied too; they keep their recorded people as co-subjects; and any use
  of them outside Andy's home still needs those people's yes (P12, P25).
  - **What this spec does with it** (P36, end of 6.3; Rio Grande's call on the form). Revision 6 refused an imprint of
    a memory with a recorded co-subject until that person said yes, even into the owner's own home (7.4). It refused
    whole any bulk use that held one, such as an imprint batch or the trail evaluation's `read` batch (6.4). Revision
    7 widens that, inside the owner's home only. There, the owner's `imprint`, and every bulk use that shows nothing
    to any agent, read each co-subject's layer as a restriction layer, and so do the uses their `need` adds on his
    own memories. A co-subject's silence, or a missing layer, passes, and their deny still refuses. Every use that
    shows content to an agent, and every use outside the owner's home, still needs every subject's yes. A memory that
    mentions someone with no recorded co-subject moves on its owner's yes alone, as before. A name detector may only
    add co-subjects (section 14, step 4). P36 departs from the words of the vision's principle 1 (above).
  - **The other two specs.** The imprints spec (revision 7) ships a memory with a recorded co-subject only in a copy
    kept in the owner's home, with its co-subjects carried. It keeps the memory at home otherwise, and also when a
    co-subject's layer on the owner's ledger denies a use the imprint needs (its D27, D43 and `denied(m)`). Its
    section 8 ("Carried co-subjects in the meet") reads each carried co-subject's layer as a restriction layer under
    P36, as this spec does. The trail spec (revision 9, section 7, "On a full-store imprint", and its section 14) says
    that both specs follow P36. Every step-1 use at a station of a copy kept in the owner's home is a bulk use inside
    that home. That answers that spec's ask (a) (its section 17). Three points remain (the re-check's RC1 and RC2):
    - **Denies in step 1.** A person co-subject's layer is empty in step 1, since the CLI writes no other person's
      layer (7.6). A place co-subject that the owner stewards can hold his deny, since the CLI writes that layer
      (7.6), and P36 lets that deny refuse. The imprints spec's `denied(m)` keeps such a memory at home, so its
      station never decides one.
    - **The bound of 8 subjects.** A road or trail whose memories carry 8 or more distinct co-subjects has 9 or more
      subjects (P24). P36 keeps 6.5's step 1, so this spec refuses the whole bulk use with `BOUND` (6.4, "Nothing else
      is waived"), and so does the build (`engram/permissions.py:1630` on `permissions-core`). The imprints spec's
      finite check doesn't test that bound (its section 8, "The bound of 8 subjects on roads and trails"), and its
      gate holds every imprint with a carried co-subject until the specs are re-checked side by side (its section
      18). This spec's answer for that re-check, unless Rio Grande rules otherwise: the station's check takes the
      bound and refuses, as `decide` does. Lifting the bound for counted bulk uses would be a second widening, with
      its own ruling.
    - **What an imprint carries.** A copy carries its source's subjects as 6.3, item 1 reads them, through `copies`
      too (7.4, "A copy held on another ledger"). As committed in `c795c59`, the imprints spec's `cosubjects(m)` read
      `subjects` rows alone (its section 5.2), as the build's `Ledger.cosubjects` does
      (`engram/permission_ledger.py:574-577`). So a memory that is itself a kept copy, whose source gained a
      co-subject after the copy was made, would ship with no `imprint_subjects` row for that person. Only
      `subjects_of` follows `copies` (`engram/permissions.py:1100-1118`). The fix is that spec's revision after the
      re-check: the set is `subjects_of` at the plan, less the owner, and `denied(m)` and the bound of 8 read the
      same set. The side-by-side re-check confirms it.

    Lifting that spec's hold on approving an imprint whose `others.memories` is above 0 (its section 18) is for its
    own revision, after those points. Under P36 a carried co-subject no longer refuses the trail evaluation on a copy
    kept in the owner's home, unless that person denies.
  - **A fact for his answer, not a decision** (the re-check's RN8). For the same kind of yes, a memory leaving its
    owner's home, this spec asks less. Here a memory that mentions someone with no recorded co-subject moves on the
    owner's yes alone. For a copy kept outside the owner's home, the imprints spec also makes the owner tick a box
    first: "Nothing I am sending is about another person who hasn't agreed to share it, and none of it is patient or
    participant data" (its D27 and section 8). For a copy kept in his home, its revision 7 asks him to acknowledge,
    with counts, that such memories are copied (its D27). This spec has no such confirmation for an outside-home
    allow. The question stays open.
  - **A second fact, not a decision** (the check of revision 4, BS3). Once co-subjects can say yes (step 2), an
    allowed item's annotation names each allowing home (section 11). So an agent shown a memory about Andy and Jenn
    learns both homes from the line. Each said yes to the use, not necessarily to being named.
