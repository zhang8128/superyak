# Claims that cross between peers: the transport (north-star test 5, Tardis's half)

Revision 4, 2026-11-22. Tardis. Board item `spec:claim-crossing-transport`, goal line T1. **Approved under station law
section 3** by a fresh reviewer, after four checks, each posted whole in all hands. Andy can veto. Rio Grande is its
partner reader.

- **Revision 1 (09923aef)** went to a fresh reviewer, who approved it with seven required changes and twelve advisory
  ones (all hands 82edc797). Rio Grande's partner read asked for two more and a small one (9c1afb0e).
- **Revision 2 (f8ece5f5)** made all of them, named R1 to R7, A1 to A12 and RG1 to RG3. Its re-check found R1 to R7
  fixed, and asked for four more and seven advisory ones (834c18a4).
- **Revision 3 (d3b2b710)** made those, named N1 to N4, and A1 to A7 of the re-check. Its third check found N1 to N4
  fixed, and approved it with one named change, N5, and five advisories (ed351ca0).
- **This revision, 4, makes N5 and all five advisories.** It also cites the two checks Rio Grande moved into
  `sourced.py` at 08d40fa2. Where an advisory number appears twice, the section it lands in says which check it's
  from.
- **Its fourth check approved it,** finding N5 fixed and every advisory taken. It asked for one correction, which is
  made here: the receive's 2 s bound is `store.bounded(2)`, so it covers the gate too.

This is the follow-up that [the claim-crossing spec](2026-11-22-claim-crossing-design.md) (revision 6, 84fafe71, with
amendments 1 and 2) leaves to a transport: "who sent what: a sender comes from the crossing's authenticated peer, never
from an artifact's self-named issuer". It answers Rio Grande's three questions: the sender, the passed-on policy (E3),
and permissions. It also amends that spec once (T5).

## Why

Test 5's Measure 3 is real crossings in both directions between the Pi and Tardis. Today no Atlas artifact crosses
machines: no code links Atlas and the peer, and an Atlas store has no default place on disk (`--db` is enforced at
`atlas/workbench/__main__.py:75-76`). The relation rule (`sourced_relation.py`, e2ea524b) and the notice report
(`apply_notice`, ea18ee6b) run on what a receiver holds. This spec gets a publication or a notice from one peer to the
other's ship, with its sender proved.

## What exists, read at main 192a3a97

File names are in `peer/superyak_peer/` unless a path is given. The fresh reviewer checked each line of this section
against the code.

- **The pairing already runs both ways.** The Pi's station is a push peer. Tardis's `tardis-peer` is a pull peer,
  whose `federate` pulls the Pi's rows from its listener and pushes Tardis's rows to it (`federate.py:40-72`). So
  sending needs no new listener and no new unit. The push peer #12 asks for is needed only for the Pi to *ask*
  Tardis, as Engram recall does, and stays its own goal.
- **Every envelope is signed.**
  - It carries an Ed25519 signature over its canonical JSON, plus `payload_digest` (`identity.py:235-241`).
  - The receiver finds the paired card by `origin` and checks the signature with its signing key
    (`federation.py:1007-1010`, `identity.py:243-269`).
  - The peer id is the SHA-256 of that key (`identity.py:147`), and `validate_card` binds the two (`identity.py:71`),
    so one paired peer can't speak as another.
  - TLS pins the listener only, so the signature is what proves the sender.
  - The **actor** an envelope names is the sending peer's word, not proved by the signature (RG3).
- **What the receiver keeps:** the receipt (`origin`, the event id and the signed envelope's digest,
  `federation.py:1017, 1027`). It doesn't keep the signature or the signed bytes.
- **The actions are a closed list** (`federation.py:1034`): layer.release, layer.withdraw, room.roster, room.message,
  room.withdraw and room.reply.
  - An unknown action under envelope version 1 gets 400 "Unknown peer action". Only that row is refused, on push
    (`classify`) and on pull (`_take_pulled`).
  - A new envelope version, or an extra top-level key, gets 403 "Peer authentication failed". The sender counts that as
    a peer failure, backs off, and holds every other row to that peer (`federation.py:46-47, 566-567`).
  - **So the extension is a new action under version 1, never a new envelope.**
- **Neither existing carrier fits:**
  - A layer carries JSON files, but creating, activating and reading one needs a person, and ship keys are refused
    (`app.py:385-388, 408`).
  - A room message is capped at 20,000 characters (`federation.py:1064`) and filtered when shown, and system-authored
    messages never federate (`system_author.py:66-68`).
- **Limits:**
  - an envelope is at most 6 MiB everywhere (`identity.py:18`);
  - a pull response has a 1 MiB budget, though one larger row is sent alone (`federation.py:34, 722-723`), with a
    deadline scaled at `PULL_RATE`, 64 KiB a second (`transport.py:17, 196`);
  - **a push has 3 s, connect included (`transport.py:14`). A timeout is a peer failure that holds the peer's other
    rows, and rows never expire (`federation.py:578-590, 605`).**
  - The planted publications are 4,023 to 144,256 bytes as compact JSON.
- **Consent today:**
  - the typed pairing code is the only consent a delivery has;
  - Engram's permissions ledger governs only `mem:`, `road:` and `trail:` objects (`engram/permissions.py:195-206`), so
    it doesn't reach Atlas;
  - crossings refuse a contact that only an owner trust confirmed (`contact_current`, `federation.py:148-156`).
- **What lists a peer as one the owner chose:** only the lessons chain, and it lists peers for the lessons room.
  - On the station, `lessons_peers` lists the peers Andy confirmed (`lessons.py:1278-1279`).
  - On another peer, the origin of its recorded lessons room (`lessons_room.room_key`, `<origin>:<room>`) is the
    station whose room its agent checked was Andy's.
- **Tardis's contacts today:**
  - tardis-peer's only paired contact is the station's `Andy`, so it has no `rio-grande` contact.
  - On the Pi, `tardis` is a contact, added to the lessons room on Andy's word.
- **Atlas has no dependencies** (`atlas/pyproject.toml`), so it can hash, but it can't check an Ed25519 signature.

## Decisions

### T1. Two new actions, under envelope version 1, that can't stall a peer (R1)

- **`atlas.publication`:** payload `{"package": <one publication, exactly as publish_sourced made it>}`.
- **`atlas.notice`:** payload `{"notice": <one source notice, exactly as seal_notice made it>}`.

There's one recipient per envelope, as for every action today. The payload's canonical JSON is at most 1 MiB, checked
by the sender before it queues and again by the receiver.

**Pushing an atlas row, in two phases (N1):**
1. **DNS, connect and the pinned handshake** (`_pinned_socket`, `transport.py:67-98`) keep today's 3 s. A timeout or
   fault here is classified as today: a peer failure. So an unreachable peer gets `failing_since` and `last_problem`,
   and Ops hears after a day, even when only atlas rows are queued.
2. **The write and the wait for the answer** get `3 s + payload bytes / PULL_RATE`, the rate pull already uses. That's
   19 s for 1 MiB, and 5.2 s for the largest planted publication.

   **Only a timeout in this phase is the row's, and it's decided by the clock, not by the exception's class (N5).**
   - After the pin has matched, any failure raised at or after this phase's deadline, on `time.monotonic()`, is the
     row's. When the deadline passes, the watchdog shuts the socket (`transport.py:101-111`), so the failure arrives
     as `BrokenPipeError`, `ssl.SSLError` or `RemoteDisconnected`, not only `TimeoutError`.
   - A fault before the deadline, such as a reset mid-write, stays a peer failure.

   When it is the row's:
   - the row is `failed`, with a backoff of its own, `min(3600, 60 × 2^attempts)` s in `outbox.next_attempt`;
   - the peer's other rows keep flowing;
   - `_due_rows` reads `outbox.next_attempt` for atlas rows, and `sync_once` stops resetting it to 0 for them
     (`federation.py:583, 597-606`).

**Scheduling:**
- **Atlas rows go last in each pass.** `_due_rows` orders non-atlas rows first, then atlas rows by event order, so a
  room message queued after an atlas row is never behind it.
- **At most one atlas row per peer is pushed in each pass (A3).** A pass can then never stretch to minutes, or delay
  the next pull and a SIGTERM.

**The gate (N2):** for an atlas row, `send_pinned` releases the dispatch gate once `prepare` has committed the
envelope, *before* the write. So a store transaction, such as `ask`'s on tardis-peer's crossing socket
(`crossing.py:404`), never waits behind a slow push.
- A hold that commits during that write meets an attempt already in flight. That's the rule PROTOCOL.md already gives
  for a hold after the write, and PROTOCOL.md says it holds here too.
- Room rows keep today's gate.

**Pulling an atlas row** already has its own scaled deadline, and needs nothing new.

### T2. Who may send, and to whom (R5, RG1)

- **The sender:** a ship that has an owner who is an admin on its peer. It sends in process on its own peer, with
  `superyak_peer atlas-send --data-dir D --as <ship> --to <contact> --file <package or notice>`.
  - An ownerless ship, such as the station ship `create-ship` makes, is refused: `_delivery_authority` would find it no
    author (`federation.py:917-918`) (A4).
  - Nothing else sends: no room, board item or brief triggers a send.
- **The recipient:** a ship account on the paired peer.
- **The contact:** at queueing *and again at every prepare* (R4), it must:
  - have a current typed code (`contact_current`). A contact that only an owner trust confirmed is refused, in words of
    its own, as for crossings;
  - be on **a peer the lessons chain lists** (RG1). That's a peer in this peer's `lessons_peers`, or the origin of this
    peer's recorded lessons room, read from `lessons_room.room_key` even when `_lessons_chain` returns []
    (`lessons.py:1141-1143`) (A1). Any other peer is refused with "That peer isn't listed for your lessons room:
    Atlas publications go only to peers listed there."
- **What the list is, said plainly (A1):**
  - On the station, `lessons_peers` holds the peers Andy confirmed for the lessons room. Today those are only his own.
  - On another peer, the origin comes from its agent's CONFIRM (`lessons.py:1322-1357`), checked against the room's
    owner, not confirmed by Andy.
  - Listing a peer for the lessons room now also lets Atlas publications go to its typed-code contacts. So both views
    say so, as `pair` prints its lessons line:
    - `station-lessons-room`'s, on the station;
    - `make lessons-room`'s CONFIRM view on another peer (`record_lessons_room`, `lessons.py:1322-1358`), which opens
      sends to the station.

    A trust-made ship's contact is still refused, by the typed-code rule above.
- **The package's own policy (R5, N4)** is read with string checks only, with no Atlas import. The sender refuses
  unless:
  - an `allow` rule grants `retain` with a `publishers` entry exactly equal to the destination's
    `urn:superyak:peer:<peer id>`;
  - no `allow` rule has a `*` anywhere in any selector: actions, publishers, audiences, contexts, domains, purposes,
    profiles or media types. `authorize` matches a trailing `*` as a prefix (`lighthouse_wire.py:234`), so
    `actions: ["*"]` would grant `reshare`;
  - no `allow` rule names `reshare`.
- **Duplicates (R6):** the sender refuses to queue a payload whose digest it already has queued, delivered or failed
  for the same contact, saying "Already sent to that contact". The receiver also stores a duplicate once (T6).

### T3. The sender is bound to the delivering peer (Rio Grande's 1)

- **A real issuer's URI** is `urn:superyak:peer:<peer id>`, the 64 hex digits of the issuing peer's id. A peer's
  publications and notices are issued under its own URI. The fixtures keep their `urn:superyak:fixture:*` issuers,
  which never cross.
- **The sender refuses to queue** a package whose issuer isn't its own URI, in the descriptor, the snapshot, the
  policy and every claim. It refuses the same for a notice. Each `carried` entry must be issued by its own URI or the
  destination's (A7).
- **The receiver refuses with 400,** before storing anything, unless:
  - a publication's descriptor, snapshot, policy and claims are all issued as `urn:superyak:peer:<origin>`;
  - every `carried` entry's claim and snapshot share one issuer, which is the receiver's own URI or `<origin>`'s (R2);
  - a notice is issued as `<origin>`'s;
  - no artifact has a non-empty `attestations` (A8). Attestations aren't covered by the digest
    (`lighthouse_wire.py:204`), so this version takes none.

  These are string comparisons on known fields.
- **How each fault in an atlas receive is answered (A2, N3):**
  - **A duplicate on the new key** is acknowledged as a duplicate.
  - **A deterministic fault,** such as a malformed payload, a refused issuer or a full quota, is a 4xx with its own
    words. The row is `refused`.
  - **A passing storage fault,** `sqlite3.OperationalError` (locked, busy, I/O or full), answers 503. That's
    peer-scoped, as it is for every row today, so the row is retried. Atlas rows go last, so a 503 doesn't hold back
    room messages in the pass.
  - **An atlas receive waits at most 2 s for the store,** inside `store.bounded(2)` (`db.py:196-211`).
    - That bounds the dispatch gate as well as SQLite's busy wait. `transaction(wait=...)` alone would bound only
      SQLite, and on the Pi the gate is the likelier wait (`db.py:184`) (the approving check's correction).
    - Its `GateTimeout` (`dispatch.py:16`) answers 503, as `OperationalError` does.

    So a busy store answers 503 well inside the sender's write deadline, rather than showing there as the row's
    timeout.
  - **Nothing escapes as a 500.**
- **What the receiver keeps,** beside each payload:
  - **the signed envelope, exactly as it arrived (RG2);**
  - the delivering peer (`origin`) and its card's signing key;
  - the actor it names, which is the sender's word (RG3);
  - the event id, the envelope's digest and the time it arrived.

A carried Claim keeps its own issuer and digest. Its relation answers rest on digests, which are content addresses.
The report names who carried it.

### T4. A policy passed on (E3)

**Real crossings in this version carry no third store's artifacts:**
- a `carried` entry must be issued by the receiver itself or by the delivering peer (T3);
- a receiver-issued entry must be one the receiver really published (R2, T6);
- a policy counts only when it arrives inside a publication from its own issuer's bound peer, which T3 makes the
  delivering peer's.

So `retain` and `reshare` of a third store's claim are refused by default, and "copied twice through `third`" stays a
fixture case. Attestation for a third store is a later spec, when a third peer exists.

### T5. Permissions (Rio Grande's 3), and the amendment it makes (R5)

**Decided by the fresh reviewer, in Andy's place under section 3:** option 1, with T2's checks. Andy can veto.

1. **Chosen:** the typed pairing, between peers the lessons chain lists (T2), plus each package's own policy. Each
   policy is written in the Measure 3 run's commit before the run, and names only the two peers' URIs:
   - `read`, `link_overlap` and `retain` are allowed;
   - `reshare` isn't.

   The policy travels inside the signed envelope, so it's provably the sending peer's. **What code enforces:** T2's
   own-peer list, the typed code, and the policy's checks. **What stays a rule:** what goes into a policy.
2. **Not chosen:** a per-contact switch, "Atlas publications to this contact". It could be a browser page with Andy's
   password, or a trusted-local command a ship runs when he asks, as `station-add-ship` is (A11).
3. **Not chosen:** an allow in Engram's permissions ledger on new `atlas:` objects. It's the most uniform with memories,
   and the heaviest.

**This amends the claim-crossing spec.** That spec says "A publication crosses only under its owner's ledger" (its D4)
and that a real crossing "waits on an allow its owner signs" (its "What this spec does not do"). This spec puts in
their place:
- Andy's typed pairing, between peers listed for his lessons room;
- each package's policy, which its sender's checks enforce.

No law line makes this act his. Andy can veto, and then option 2 or 3 applies.

### T6. Receiving, reading and refusing

- **Storage:** the receiver stores an accepted payload in a new table, `atlas_received`, with the columns:
  - origin, signing key, actor, recipient, kind, event id, envelope digest, payload digest, received at, the envelope.

  It's keyed by (origin, recipient, payload digest) (R6). The same package sent twice to one ship is stored once,
  while two ships each get their own. The duplicate shows on the receiver only, since `sync_once` and pull acks carry
  no flag; the sender's own check is T2's.
- **The table never feeds `inbox`,** whose readers know only layers and rooms.
- **Disk (A10):** at most 64 MiB of payloads per origin. Past that, a new one is refused with "This peer holds 64 MiB
  from that peer already".
- **Unpairing, a hold and restore's reconcile (R7)** delete that origin's `atlas_received` rows, as they clear its
  `inbox` payloads today (`federation.py:371`, `owner_trust.py:249-251`, `backups.py:813-829`).
- **`superyak_peer atlas-received --data-dir D --as <ship> --out DIR`:**
  - writes that ship's rows from origins still paired;
  - checks each envelope's signature again with its kept key before writing it (RG2);
  - each file holds the envelope, the sender's signing key, the receiver's own peer id (R2), and
    `delivered: {origin, actor, event_id, envelope_digest, received_at}`;
  - reads and changes nothing else.
- **`superyak_peer atlas-verify FILE`** checks that a copied file's signature still covers its payload, and that the
  key's SHA-256 is the issuer's peer id. So source identity survives a copy (RG2).
- **On the Atlas side, a new `atlas/workbench/sourced_received.py`:**
  - `received(file, own_publications)` takes the receiver's own URI from the issuer of `own_publications`, its caller's,
    not from the file (A6). It checks T3's binding against `delivered.origin`, and that the SHA-256 of the file's key
    is that origin. That's a **consistency check**; the signature is `atlas-verify`'s, since Atlas has no
    Ed25519 (A5).
  - It refuses a receiver-issued carried entry unless `own_publications` hold that claim digest with that snapshot
    (R2). With no `own_publications` there's no receiver URI to take, so every receiver-issued carried entry is
    refused (A4).
  - Two of the reviewer's checks are in `sourced.py` itself, for every caller, since `rio-grande/claim-crossing-build`
    08d40fa2:
    - `validate_notice` refuses a notice naming a Snapshot another issuer issued (R3);
    - a carried entry's claim and snapshot must share one issuer, at publish and at validate (R2's second check).

    `received()` relies on them, and adds the check `sourced.py` can't make, the receiver's own publications.
  - Then it runs `validate_sourced` or `validate_notice`.
  - Its output feeds `held_claims`, `relation` and `apply_notice` unchanged, and `authorize` runs as the claim-crossing
    spec's table says, with T3's URIs.
- **A notice that arrives before the publications it names:**
  - it's stored;
  - `received` refuses it at read time, naming the missing Snapshot's digest (A1);
  - it's read again when the publication is there.

  Order is best effort: a refused, failed or skipped publication can be overtaken by a later notice. The read-time
  rule is what makes the result correct, not the order.
- **Nothing is merged and no status changes.** Reports stay reports.

### T7. Outbound storage, status and retry (R4)

- **Queueing:** `atlas-send` writes an event through `store.emit`, and an outbox row directly, as `room.reply` does
  (`peer_store.py:203-222`):
  - `action` is the action, and `resource_id` is the payload digest;
  - `revision` is 1;
  - `metadata` holds only the sending ship's id, the digest, the kind and the collection's title;
  - **the payload goes in a side table, `atlas_outgoing`, keyed by digest (A2).** `_delivery_authority` and `status()`
    parse every row's metadata and envelope inside a transaction (`federation.py:892, 928, 958-959`), so a payload
    in metadata would be parsed on every `deliveries` call.
- **`_prepare_in` has an atlas branch:** it re-checks T2's contact rules, then builds the envelope from
  `atlas_outgoing`. A contact that fails them now makes the row `withdrawn`. Today a non-room row would raise 404.
- **The signed envelope of an atlas row** is kept in `atlas_outgoing` too, not in `outbox.envelope` (advisory 2 of
  the third check). `status()` runs `SELECT *` and parses every envelope inside a transaction
  (`federation.py:928, 958-959`). Its atlas branch takes the action from `row['action']`, which never changes at
  prepare, and loads no payload.
- **`status()` and `_delivery_authority`:**
  - `_delivery_authority` names the ship's owner as an atlas row's author, so Andy's `deliveries` and `retry` show
    and retry it, under the ship's name;
  - `status()` titles it "Atlas publication" or "Atlas notice", with the collection's title, not "Room unavailable".
- **New, for ships:** `superyak_peer atlas-deliveries --data-dir D --as <ship> [--retry KEY]` lists the atlas rows
  whose `metadata` names that ship, and retries a refused one through a path of its own (R4).
  - `retry()` checks the owner as author (`federation.py:976`), so it isn't reused.
  - `atlas-deliveries` is trusted-local, and admin commands still refuse ship keys.
  - The owner must be an admin on that peer to see the rows in `deliveries` (`__main__.py:332-340`).
- **Refusal words, by direction:**
  - on a push, the sender keeps the receiver's words in `last_error`;
  - on a pull, the puller's refusal reaches the sender as a status only. So the puller keeps each refused atlas row's
    words in a table of its own, `atlas_refused` (origin, event id, words, at), and `atlas-received` lists them
    (A5). `_take_pulled` keeps none today (`federation.py:849-857`).
- **An old receiver** refuses an atlas row alone, on either path (`classify` for push, `_take_pulled` for pull). The
  row waits for a `retry`. The deploy goes receivers first.
- **PROTOCOL.md** gains the two actions, their payloads, their refusals and T1's deadlines (A9).

## Measure 3's mechanics

The claim-crossing spec's Measure 3 holds. This spec adds what the run's commit fixes before the run:
- the collection each side publishes;
- each side's policy (T5);
- the pairs, the claim-crossing spec's union of three sets.

**Amendment 1 (the build, 2026-11-22): both directions need `rio-grande` as a contact on tardis-peer.** Revision 4 said
the Pi to Tardis needed nothing new. That was wrong.
- **Why:** `receive()` refuses an envelope whose actor isn't a contact from its origin on the receiving peer
  (`federation.py:1012-1013`, "Unknown remote participant").
- **The Pi to Tardis** is sent by `rio-grande`, so tardis-peer must hold it as a contact.
- **Tardis to the Pi** is addressed to `rio-grande`, so the sender's contact row must name it.
- **Today:** tardis-peer's only contact is `Andy` (A6).

So one pairing, `rio-grande`'s card typed into tardis-peer, opens both directions. That's a pairing code, and pairing
peers is Andy's act (CLAUDE.md). Measure 3 runs once he chooses to pair them. Until then, it reports that neither
direction can run, and why.

T2 also needs the Pi's `tardis` contact to have a current typed code (`contact_current`). Rio Grande checks that on
the Pi before the run.

This is a correction of what the run needs, not of a rule, so it didn't go back to the reviewer.

**Each direction is reported separately:**
- the count of each answer, with every unknown's reason;
- every copied, same-sources or overlapping pair, side by side;
- the transport's facts:
  - rows sent, delivered, refused and retried;
  - the seconds from send to receipt;
  - the longest write of an atlas push, which no longer holds the gate (T1).

Nothing is a score, and a failure is a result.

## Tests, written first

1. **Send and receive:**
   - a publication and a notice each go both ways between a push and a pull peer in one process;
   - each arrives equal, as canonical JSON, to what was sent, with its envelope and `delivered` record;
   - `atlas-verify` passes on the written file.
2. **Refusals, each with its own words, read where T7 says:**
   - an issuer that isn't the origin's;
   - a carried entry issued by a third URI;
   - a carried entry whose claim and snapshot issuers differ;
   - a payload over 1 MiB, at the sender and again at the receiver;
   - a recipient that isn't a ship;
   - a contact only an owner trust confirmed;
   - a contact on a peer the lessons chain doesn't list;
   - an ownerless ship;
   - a held contact;
   - an unpaired origin;
   - a policy with no exact `retain` allow for the destination, a `*` in any selector (`actions: ["*"]` among them), or
     a rule naming `reshare`;
   - a non-empty `attestations`;
   - a second send of one digest to one contact;
   - an origin over 64 MiB;
   - a locked store, answered 503 and retried, not refused (N3);
   - a duplicate on the new key, acknowledged as a duplicate.
3. **The old receiver, on both paths:** a push to an old listener and a pull by an old puller each refuse only the
   atlas row, and a room message queued after it is still delivered.
4. **No stall, no hidden outage, no held gate:**
   - On a link throttled below the write deadline, an atlas row times out alone, with its own backoff, and a room
     message queued after it is delivered in the same pass. The throttled case ends through the watchdog's shutdown,
     as a `BrokenPipeError` mid-write and a `RemoteDisconnected` at the answer, not only through `socket.timeout`
     (N5).
   - A reset before the write deadline stays a peer failure (N5).
   - A receiver whose store is locked, or whose dispatch gate is held, answers 503 within its 2 s bound.
   - An unreachable peer with only an atlas row queued still gets `failing_since` and `last_problem` (N1).
   - A store transaction completes while a throttled atlas push is writing (N2).
   - Two atlas rows to one peer go in two passes (A3).
5. **Idempotency:** one package sent to two ships on one peer is stored for each. The same event id with a different
   digest gets 409, as today.
6. **Status:** an atlas row shows in Andy's `deliveries` under its ship, and in the ship's `atlas-deliveries`. `retry`
   sends a refused one again, and a contact that lost its code makes the row `withdrawn` at prepare.
7. **Unpair, hold and restore's reconcile:** each deletes that origin's rows (A7), and `atlas-received` writes
   nothing from an unpaired origin.
8. **Atlas reading:**
   - a file whose `delivered.origin` or key was edited fails `received`'s consistency check;
   - a payload that was edited fails `atlas-verify`;
   - a forged receiver-issued carried claim is refused (R2);
   - a notice naming another issuer's Snapshot is refused (R3);
   - an early notice names its missing Snapshot;
   - `held_claims` over received publications gives `relation` the same answers as over the fixtures re-issued with
     peer URIs.
9. **Mutants:** one per T2, T3 and T6 refusal, and one for T1's ordering, each of which must fail a test.

## Deploy

- **No new units:** the Pi's lighthouse and Tardis's federate are restarted after the merge, receivers first.
- **Don't run `make federation-units` for a second data directory on one machine** (`Makefile:630-640`).
  - It installs single-instance units, so it would repoint the machine's existing `superyak-federate` at the new
    directory.
  - Run without `FEDERATE_ARGS`, it would also delete the `--crossing-socket` drop-in that Tardis's recalls use.
  - This spec needs no second directory.
- **Rollback:** a peer without the actions refuses atlas rows alone (T7), so stopping is leaving rows refused.
  `atlas_received` can then be dropped.

## What this spec does not do

- **#12's push peer on Tardis.** It's for Engram recall both ways, not needed to send.
- **Rooms, briefs and the board.** None of them sends or shows a publication.
- **A third store, or a peer the lessons chain doesn't list.** T2's code refuses a peer that isn't listed, and T4
  refuses a third store's artifacts. Listing another owner's peer for the lessons room would open sends to it. That's
  why `station-lessons-room`'s view says so (T2).
- **Agreement.** Each store keeps its own records and history. The rule and the reports only show.
