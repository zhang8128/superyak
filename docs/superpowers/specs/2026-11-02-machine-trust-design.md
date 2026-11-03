# Owner trust: a confirmed person's ships pair without a code each

Rio Grande, 2026-11-02. Revision 2, after the fresh review of revision 1 (M1, M2, S1 to S5). Status: draft for its
re-check (law section 3).

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
   - the peer id;
   - the ship's participant id and name;
   - its owner's participant id;
   - issued and expires times (at most 30 days).

   `export-ship --username <ship>` writes the card and its assertion together. The command refuses an account that
   isn't a ship, or a ship whose owner isn't that peer's local person. A copied card can't carry a forged assertion
   without that peer's private key.
2. **Owner trust, a person's act once per person contact:**
   - It's granted in the station's browser by the admin, with their password, like the imprint confirm. Only for a
     remote person contact whose code was typed (`pairing_confirmations` holds a typed code, not a trust mark).
   - The grant reads: "ships owned by <name> on <peer 12> may be paired by this station's ships, until <date>". It
     lasts at most 90 days and can be renewed.
   - It's kept in an append-only `owner_trust` table: grant, renewal, revocation, each with who and when. The table is
     checked like the ledger's other rows.
   - A ship never grants or renews it, never runs it under a pty or a wrapper, and never types its password.
3. **Pairing within it, a ship's act:** `pair-trusted --card <file> --assertion <file> --as <ship>`, with no
   terminal and no code. It refuses, and writes nothing, unless all of these hold:
   - the assertion verifies under the paired card's signing key, hasn't expired, and names that peer;
   - its owner is a contact under unrevoked, unexpired owner trust;
   - the card, apart from `participant`, equals the paired card (as `pair` compares it, federation.py:130);
   - the participant equals the assertion's;
   - it isn't already a contact;
   - its name doesn't casefold-match a local user or any existing contact.

   On success it adds the contact with a `trust_confirmations` row (contact, grant, assertion digest, acting ship),
   so `connections()` reports it as "confirmed by owner trust", not as missing a code. The contact shows everywhere as
   "<name>, ship of <owner name>".
4. **The cap:** at most 200 contacts per owner trust per day, counted from `trust_confirmations` by day (UTC). A
   refusal at the cap writes nothing but a station notice (below).
5. **Notices:** each pairing, and each refusal at the cap, raises a station notice through Odo's alert path, written
   with `safe_line`. It carries the full participant id, the owner, the peer's 12 characters and the acting ship.
   It's read in the Ops room. A station without Odo writes it to the station log.
6. **Revoking**, the admin's act in the browser, or unpairing the owner's peer, ends the trust. Every contact made
   under it is put in `contact_holds` at once, as unpair does, so revoking stops a compromise. A held contact needs its
   own code again.
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

## What it costs Andy

Per person contact, the typed code (as today), plus one browser confirmation with his password, every 90 days at most.
Per ship, nothing. For a supercomputer host with a person account of his on it, that is one code and one confirm for
all his ships there, however many (S1). Someone still reads Ops; the notices make a compromise visible, not
impossible.

## Tests (for the plan)

Each refusal writes nothing:
- no trust;
- an expired or revoked trust;
- a trust whose owner's code was never typed;
- an assertion signed by another key, or edited after signing;
- an expired assertion;
- a card whose non-participant fields differ;
- a participant that differs from the assertion's;
- a casefold name collision;
- a contact that already exists;
- the cap.

Revoking holds every contact made under the trust, and a restore can't bring a revoked trust back. `connections()`
says "confirmed by owner trust". A forged card made from a public card and a new participant is refused.
