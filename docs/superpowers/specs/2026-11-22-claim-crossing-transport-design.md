# Claims that cross between peers: the transport (north-star test 5, Tardis's half)

Revision 1, 2026-11-22. Tardis. Board item `spec:claim-crossing-transport`, goal line T1. Under station law section 3,
a fresh reviewer approves it in Andy's place, and Andy can veto. Rio Grande is its partner reader (all hands
d4e80900).

This is the follow-up that [the claim-crossing spec](2026-11-22-claim-crossing-design.md) (revision 6, 84fafe71, with
amendments 1 and 2) leaves to a transport: "who sent what: a sender comes from the crossing's authenticated peer, never
from an artifact's self-named issuer". It answers Rio Grande's three questions: the sender, the passed-on policy (E3),
and permissions.

## Why

Test 5's Measure 3 is real crossings in both directions between the Pi and Tardis. Today no Atlas artifact crosses
machines: no code links Atlas and the peer, and an Atlas store has no default place on disk (`--db` is required,
`atlas/workbench/__main__.py:16`). The relation rule (`sourced_relation.py`, e2ea524b) and the notice report
(`apply_notice`, ea18ee6b) run on what a receiver holds. This spec gets a publication or a notice from one peer to the
other's ship, with its sender proved.

## What exists, read at main 192a3a97

File names are in `peer/superyak_peer/` unless a path is given.

- **The pairing already runs both ways.** The Pi's station is a push peer. Tardis's `tardis-peer` is a pull peer,
  whose `federate` pulls the Pi's rows from its listener and pushes Tardis's rows to it (`federate.py:40-72`). So
  sending needs no new listener and no new unit. The push peer #12 asks for is needed only for the Pi to *ask*
  Tardis, as Engram recall does, and stays its own goal.
- **Every envelope is signed.** It carries an Ed25519 signature over its canonical JSON, plus `payload_digest`
  (`identity.py:235-241`). The receiver finds the paired card by `origin` and checks the signature with its signing
  key (`federation.py:1007-1010`, `identity.py:243-269`). The peer id is the SHA-256 of that key (`identity.py:147`).
  TLS pins the listener only, so the signature is what proves the sender. That's enough for this spec, because every
  check below keys on `origin`.
- **What the receiver keeps:** the receipt (`origin`, the event id and the signed envelope's digest,
  `federation.py:1017, 1027`). It doesn't keep the signature or the signed bytes.
- **The actions are a closed list** (`federation.py:1034`): layer.release, layer.withdraw, room.roster, room.message,
  room.withdraw and room.reply.
  - An unknown action under envelope version 1 gets 400 "Unknown peer action", and only that row is refused.
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
  - a pull response has a 1 MiB budget, though one larger row is sent alone (`federation.py:34, 722-723`);
  - a push has 3 s, connect included (`transport.py:14`).
  - The planted publications are 6 to 144 KB as compact JSON.
- **Consent today:**
  - the typed pairing code is the only consent a delivery has;
  - Engram's permissions ledger governs only `mem:`, `road:` and `trail:` objects (`engram/permissions.py:195-206`), so
    it doesn't reach Atlas;
  - crossings refuse a contact that only an owner trust confirmed (`contact_current`, `federation.py:148-156`).

## Decisions

### T1. Two new actions, under envelope version 1

- **`atlas.publication`:** payload `{"package": <one publication, exactly as publish_sourced made it>}`.
- **`atlas.notice`:** payload `{"notice": <one source notice, exactly as seal_notice made it>}`.

There's one recipient per envelope, as for every action today. The payload's canonical JSON is at most 1 MiB, checked
by the sender before it queues and again by the receiver. That's 7 times the largest planted publication, and well
inside 6 MiB and the pull row rule.

### T2. Who may send, and to whom

- **The sender:** a ship, in process on its own peer, with `superyak_peer atlas-send --data-dir D --as <ship> --to
  <contact> --file <package or notice>`.
- **The recipient:** a ship account on the paired peer.
- **The contact:** both sides require a current typed code (`contact_current`). So, as for crossings, a contact that
  only an owner trust confirmed is refused, in words of its own.
- **Nothing else sends:** no room, board item or brief triggers a send.

### T3. The sender is bound to the delivering peer (Rio Grande's 1)

- **A real issuer's URI** is `urn:superyak:peer:<peer id>`, the 64 hex digits of the issuing peer's id. A peer's
  publications and notices are issued under its own URI. The fixtures keep their `urn:superyak:fixture:*` issuers,
  which never cross.
- **The sender refuses to queue** a package whose issuer isn't its own URI, in the descriptor, the snapshot, the
  policy and every claim. It refuses the same for a notice.
- **The receiver refuses with 400,** before storing anything, unless:
  - a publication's descriptor, snapshot, policy and claims are all issued as `urn:superyak:peer:<origin>`;
  - every entry in its `carried` list has a claim and snapshot issued by the receiver's own URI or by `<origin>`'s
    (T4);
  - a notice is issued as `<origin>`'s.

  The peer does this with string comparisons on known fields, and imports no Atlas code.
- **What the receiver records,** beside each payload: the delivering peer (`origin`), the acting contact, the event id,
  the signed envelope's digest and the time it arrived.
- **The Atlas side checks the binding again** when it reads (T6), so a received file copied elsewhere can't change its
  sender.

A carried Claim keeps its own issuer and digest. Its relation answers rest on digests, which are content addresses.
The report names who carried it.

### T4. A policy passed on (E3)

**Real crossings in this version carry no third store's artifacts:**
- a `carried` entry must be issued by the receiver itself (its own claim, copied back) or by the delivering peer;
- a policy counts only when it arrives inside a publication from its own issuer's bound peer, which T3 makes the
  delivering peer's.

So `retain` and `reshare` of a third store's claim are refused by default, and "copied twice through `third`" stays a
fixture case. Attestation for a third store is a later spec, when a third peer exists.

### T5. Permissions (Rio Grande's 3): one decision, with a recommendation

Measure 3 can't run until one of these holds. A fresh reviewer decides in Andy's place under section 3, and Andy can
veto:

1. **The pairing plus each side's own ConnectionPolicy (recommended).** A ship sends only to a contact its owner paired
   by typed code. Each side's policy, written in the Measure 3 run's commit before the run, names only the two peers'
   URIs:
   - `read`, `link_overlap` and `retain` are allowed;
   - `reshare` isn't.

   The policy travels inside the signed envelope, so it's provably the sending peer's. No new act of Andy's: his typed
   pairing between his own two machines is the consent.
   - **Weakness:** an owner who pairs with someone else's peer also lets his ships send that peer Atlas publications,
     whenever a policy names it.
2. **A per-contact switch,** "Atlas publications to this contact", which the owner turns on once in the browser, with his
   password. It's a new page and a new act of Andy's for each contact.
3. **An allow in Engram's permissions ledger on new `atlas:` objects:** a signed, enforced ledger line for each
   collection and receiver. It's the most uniform with memories, and the heaviest: a new object kind in the ledger, and
   Andy's signing at each machine.

The weakness in 1 doesn't reach Measure 3, since both peers are Andy's.

### T6. Receiving, reading and refusing

- **Storage:** the receiver stores an accepted payload in a new table, `atlas_received`, with the columns:
  - origin, actor, recipient, kind, event id, envelope digest, payload digest, received at, and the payload.

  It's keyed by (origin, payload digest), so the same package sent twice is stored once and acknowledged as a
  duplicate. The table never feeds `inbox`, whose readers know only layers and rooms.
- **`superyak_peer atlas-received --data-dir D --as <ship> --out DIR`** writes that ship's rows as files. Each file
  holds the payload, plus `delivered: {origin, actor, event_id, envelope_digest, received_at}`. It reads and changes
  nothing else.
- **On the Atlas side, a new `atlas/workbench/sourced_received.py`:**
  - `received(file)` checks T3's binding against `delivered.origin`, then `validate_sourced` or `validate_notice`;
  - its output feeds `held_claims`, `relation` and `apply_notice` unchanged;
  - `authorize` runs as the claim-crossing spec's table says, with the URIs of T3.
- **A notice that arrives before the publications it names:**
  - it's stored;
  - `validate_notice` refuses it at read time, saying which Snapshot is missing;
  - it's read again when the publication is there.

  Rows to one peer go in event order (`federation.py:605`), so a sender that sends in order is received in order.
- **Nothing is merged and no status changes.** Reports stay reports.

### T7. Status, retry and the old receiver

- **`_delivery_authority`** names the sending ship as the author of an `atlas.*` row, so `deliveries` and `retry` show
  it (today an unknown action has no author, `federation.py:889-920`).
- **An old receiver** answers 400 "Unknown peer action". The row is refused, it waits for its owner's `retry`, and no
  other row is held.
- **The deploy goes receivers first:** both peers update before anything is sent.

## Measure 3's mechanics

The claim-crossing spec's Measure 3 holds. This spec adds what the run's commit fixes before the run:
- the collection each side publishes;
- each side's policy (T5);
- the pairs, the claim-crossing spec's union of three sets.

**Each direction is run and reported separately:** the Pi to Tardis's `tardis`, and Tardis to the Pi's `rio-grande`.
For each direction it reports:
- the count of each answer, with every unknown's reason;
- every copied, same-sources or overlapping pair, side by side;
- the transport's own facts: rows sent, delivered, refused and retried, and the seconds from send to receipt.

Nothing is a score, and a failure is a result.

## Tests, written first

1. **Send and receive:** a publication and a notice each go both ways between a push and a pull peer in one process.
   Each arrives byte-for-byte equal to what was sent, with its `delivered` record.
2. **Refusals, each with its own words:**
   - an issuer that isn't the origin's;
   - a carried entry issued by a third URI;
   - a payload over 1 MiB, at the sender and again at the receiver;
   - a recipient that isn't a ship;
   - a contact only an owner trust confirmed;
   - a held contact;
   - an unpaired origin.
3. **The old receiver:** a receiver without the new actions refuses only the `atlas.*` row, and a room message queued
   after it is still delivered.
4. **Idempotency:** the same package sent twice is stored once, and the second send reports a duplicate. The same event
   id with a different digest gets 409, as today.
5. **Status:** an `atlas.*` row shows in `deliveries` under its ship, and `retry` sends a refused one again.
6. **Atlas reading:**
   - a file whose `delivered.origin` was edited is refused;
   - `held_claims` over received publications gives `relation` the same answers as over the fixtures re-issued with
     peer URIs.
7. **Mutants:** one per T3 refusal, each of which must fail a test.

## Deploy

- **No new units:** the Pi's lighthouse and Tardis's federate are restarted after the merge, receivers first.
- **Don't run `make federation-units` for a second data directory on one machine.** It installs single-instance units,
  so it would repoint the machine's existing `superyak-federate` at the new directory. Run without `FEDERATE_ARGS`, it
  would also delete the `--crossing-socket` drop-in that Tardis's recalls use. This spec needs no second directory.
- **Rollback:** a peer without the actions refuses `atlas.*` rows alone (T7), so stopping is leaving rows refused.

## What this spec does not do

- **#12's push peer on Tardis.** It's for Engram recall both ways, not needed to send.
- **Rooms, briefs and the board.** None of them sends or shows a publication.
- **A third store, or another owner's peer.** T4 and T5 refuse both until a later spec.
- **Agreement.** Each store keeps its own records and history. The rule and the reports only show.
