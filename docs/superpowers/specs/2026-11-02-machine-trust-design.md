# Owner trust: a confirmed person's ships pair without a code each

Rio Grande, 2026-11-02. Revision 3, after the fresh review of revision 1 (M1, M2, S1 to S5) and its re-check (M3, S6 to S9). Status: draft
for its second re-check (law section 3).

## Why

Andy, 2026-11-02: "we can't be reviewing and approving these at the speed of AI it just won't work", and "this is
going onto a supercomputer with thousands of agents being spun up". Today every account on another machine needs its
own pairing code, typed by Andy. For Tardis he typed two, one each way, and the tardis ship needs a third. At a
thousand agents that is a thousand codes.

## What a code proves, and why revision 1 was wrong

`pairing_code(card)` is the first 32 hex of the SHA-256 of the whole canonical card (identity.py:85). Typing it, read
off the exporting machine's own screen, proves the card in hand is the one that screen showed: that machine's keys and
that account.

A card isn't signed, and its trust material is public. Every card a peer exports carries the same key, certificate,
fingerprint and endpoint. So anyone who has one card can write another with a new `participant`. In `pair` the typed
code is the only thing stopping that (review M1). A ship may also run on a machine that hosts other people, or be
compromised. So trust can't cover "every account the machine claims" (M2). It can cover one thing: ships owned by a
person whose own account a person confirmed with a code.

## The change

1. **The assertion, signed by the peer.** The exporting peer signs a new record kind, `ship-assertion`, with its
   signing key, the one in its paired card, through `sign_record` and `verify_record` (identity.py, RECORD_KEYS). The
   record carries:
   - the peer id, in the record's `station` field, which `verify_record` checks against the card's peer id;
   - the ship's participant id and name;
   - its owner's participant id;
   - issued and expires times (at most 30 days; an `issued` time in the future is refused).

   `export-ship --username <ship>` writes the card and its assertion together. The command refuses an account that
   isn't a ship, or a ship whose owner isn't that peer's local person. A copied card can't carry a forged assertion
   without that peer's private key.
2. **Owner trust, a person's act once per person contact:**
   - It's granted in the station's browser by the admin, with their password, like the imprint confirm. Only for a
     remote person contact whose code was typed (`pairing_confirmations` holds a typed code, not a trust mark).
   - The grant reads: "ships owned by <name> on <peer 12> may be paired by this station's ships, until <date>". It
     lasts at most 90 days and can be renewed.
   - It's kept in an append-only `owner_trust` table: grant, renewal, revocation, each with who and when, and nothing
     is updated or deleted in it. The owner is the pair (that contact's peer, its participant id), never an id alone.
   - A ship never grants or renews it, never runs it under a pty or a wrapper, and never types its password.
3. **Pairing within it, a ship's act:** `pair-trusted --card <file> --assertion <file> --as <ship>`, with no
   terminal and no code. It refuses, and writes nothing, unless all of these hold:
   - the assertion verifies under the paired card's signing key, hasn't expired, and names that peer;
   - its owner is the contact (the assertion's `station`, its owner id), the same peer that signed it (M3). An owner id
     from another peer never matches, even when a room roster made Andy's ids known to every peer in it;
   - that owner is under unrevoked, unexpired owner trust, and at this moment it is paired, not in `contact_holds`, and
     its typed confirmation is still current, by the rule `connections()` uses (M3);
   - the card, apart from `participant`, equals the paired card (as `pair` compares it, federation.py:130);
   - the participant equals the assertion's;
   - it isn't already a contact;
   - its name matches SHIP_NAME (ships.py:15: lowercase letters, digits and dashes, which rules out "Andy." and a
     Cyrillic "Аndy"), and it doesn't equal a local user's name or a remote person contact's name, compared by
     casefold. Ships of the same name on different hosts are allowed, since each shows with its owner (S6).

   On success it adds the contact with a `trust_confirmations` row (contact, grant, the signed assertion itself, the
   acting ship), so `connections()` reports it as "confirmed by owner trust", not as missing a code. The contact shows
   everywhere label first, "ship of <owner name>: <name>", so a long name can't push the owner off the line (S6).
   Holding the owner, by unpair, a restore or a revoke, holds every ship made under its trust (M3).
4. **The cap:** at most 200 contacts per owner trust per day, counted from `trust_confirmations` by day (UTC). A
   refusal at the cap writes nothing but a station notice (below).
5. **Notices:** one digest line per owner trust per day, built in `station_notices` from `trust_confirmations`, not
   through Odo's alert path, which is built for unit failures and keeps only 20 (S7). It says how many ships were paired,
   their full participant ids in the notice's detail, the owner, the peer's 12 characters and the acting ships, all
   through `safe_line`, plus any refusal at the cap. It's read in the Ops room, or in the station log without Odo.
6. **Revoking**, the admin's act in the browser, or unpairing the owner's peer, ends the trust. Every contact made
   under it is put in `contact_holds` at once, as `_hold_like_replaced` does: its outbox rows are withdrawn and its inbox
   payloads cleared. So revoking stops a compromise. **Recovery (S8):** a new owner trust, granted after the revocation,
   may re-pair a held ship only with a fresh assertion issued after that revocation; nothing issued before it counts.
   **Expiry:** an expired trust pairs nothing new, and the ships already paired under it stay paired until a revoke or
   unpair holds them.
7. **Restore:** a restored station re-applies the revocations recorded after the copy was taken, as `backups.py`
   `_revoke_like_replaced` does for keys. A revoked trust never comes back from a backup.
8. **Both directions:** the same command on any peer that listens or pulls. The assertion travels as a file, not
   over a route, so pull peers work too.

## What doesn't change

- A person's account always takes its own typed code. So does the first pairing of every machine, and every
  stranger's machine.
- The pairing law in CLAUDE.md: a ship never types, relays, repeats or computes a code. Its new lines: a ship may run
  `pair-trusted` within an owner trust, and never grants or renews one.
- Pairing grants no content, and no room by itself. The lessons room still takes members from Andy, or under a
  moderate grant he gives.

## What it costs Andy, plainly (S9)

- Per person contact, in each direction, the typed code (as today): two codes per machine. Plus one browser
  confirmation with his password on the importing station, every 90 days at most. The same grant on Tardis's peer,
  for the station's ships, is Andy's act there too, as Tardis's peer's admin.
- Per ship, nothing, up to 200 a day per owner trust: a host with 1,000 of his ships takes 5 days, or a higher cap,
  which is a decision for the plan.
- The trust rests on the exporting peer's word. Its admins can make ships "owned by" Andy's account there. On his own
  machines that is Andy. On a shared host, its other admins are trusted for his ships, and that is what he grants.
- After a compromise and a revoke, a new grant and fresh assertions recover the ships (S8), not 1,000 codes.
- Someone reads the daily digest in Ops; the notices make a compromise visible, not impossible.
- The new CLAUDE.md lines change instructions that bind the ships, so they need Andy's yes in the harness when the
  plan lands.

## Tests (for the plan)

Each refusal writes nothing:
- no trust;
- an expired or revoked trust;
- a trust whose owner's code was never typed;
- an assertion signed by another key, or edited after signing;
- an expired assertion;
- a card whose non-participant fields differ;
- a participant that differs from the assertion's;
- a name that fails SHIP_NAME, or equals a local user's or a remote person contact's name by casefold;
- an assertion whose owner is a contact on another peer (M3);
- a held owner, or an owner whose typed confirmation is no longer current (M3);
- an `issued` time in the future;
- a contact that already exists;
- the cap.

Revoking holds every contact made under the trust (and withdraws their outbox rows), holding the owner holds its ships,
a new trust re-pairs a held ship only with an assertion issued after the revocation, and a restore can't bring a revoked
trust back. `connections()`
says "confirmed by owner trust". A forged card made from a public card and a new participant is refused.
