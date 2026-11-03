# Machine trust: more accounts from a machine Andy already paired, without a code each

Rio Grande, 2026-11-02. Status: draft for a fresh reviewer (law section 3).

## Why

Andy, 2026-11-02: "we can't be reviewing and approving these at the speed of AI it just won't work", and "this is
going onto a supercomputer with thousands of agents being spun up". Today every account on another machine needs its
own pairing code, typed by Andy. When Tardis became a peer, Andy typed two codes, one each way, and the tardis ship
needs a third. At a thousand agents that is a thousand codes.

## What a pairing code proves today

`pairing_code(card)` is the first 32 hex of the SHA-256 of the whole canonical card (identity.py:85). Typing it,
read off the exporting machine's own screen, proves two things:

1. **The machine.** The card's trust material (`TRUST_KEYS`: its key, certificate and peer id) is that machine's.
2. **The account.** The card's `participant` (`{id, name}`) is an account that machine's own screen showed.

For a second card from a peer already paired, (1) is already proven. `pair` refuses a known peer's card whose trust
material differs (federation.py, "Known peer trust material cannot be replaced"). Only (2) is new. Each contact still
waits for its own code (pairing review SF3), because a paired machine can still claim any participant. A peer may host
other people's homes, and it may be compromised.

## The change: one person's act per machine, then ships pair that machine's accounts

- **Machine trust, Andy's act once per peer:** `machine-trust --peer <full peer id> --as <admin>`, at a real terminal
  as `pair` requires. It shows the peer's name, its first 12 characters and its contacts so far. The person types the
  word `trust` to grant it. It writes a `machine_trust` row (peer id, granted by, granted at), checked against the
  log like other grants. It means: this machine holds only my accounts and my ships, so I vouch for the accounts it
  exports.
- **Pairing within it, a ship's act:** `pair-trusted --card <file> --as <admin>`, with no terminal and no code. It
  refuses, writing nothing, unless all of these hold:
  - the peer has a `machine_trust` row that hasn't been revoked;
  - the card's trust material equals the paired card's (the existing check);
  - its delivery mode equals the paired card's;
  - it isn't a participant this peer already has.
  It adds the contact as `pair` does, confirmed `trust:<row id>` in place of a typed code. It posts one line to the
  station's Ops room: "Paired <name> from <peer 12> under <admin>'s machine trust". At most 20 a day per peer; past
  that it refuses, and the refusal is posted too.
- **Revoking, a person's act:** `machine-trust --revoke`, or unpairing the peer, ends the row. Contacts made under it
  stay paired. As with unpair, each needs its own code again if the whole peer is unpaired.

## What doesn't change

- **The first pairing of any machine** still takes both codes, typed by a person. So do strangers' machines, and any
  peer without machine trust.
- **The pairing law in CLAUDE.md:** a ship never types, relays, repeats or computes a pairing code. `pair-trusted`
  has none to handle.
- **Room membership** stays its own act. A contact paired under machine trust joins no room by itself. The lessons room
  still takes members only from Andy, or under a moderate grant he gives.
- **Content:** pairing grants no content (PROTOCOL.md). Rooms and releases choose who sees what.

## Threats, and what bounds each

- **A compromised trusted machine invents accounts.** The risk is bounded: the Ops line per contact, the daily cap, no
  room access without a separate act, and one revoke.
- **A card from another machine dressed as a trusted one.** Its trust material differs, so it's refused before
  anything is written (the existing check).
- **A ship pairing a stranger's machine.** It can't: without a `machine_trust` row, `pair-trusted` refuses. Only a
  person at a terminal grants that row.

## Tests (for the plan)

Each refusal writes nothing:
- no trust row;
- a revoked row;
- different trust material;
- a different delivery mode;
- a participant this peer already has;
- the daily cap reached.

A success adds a contact confirmed `trust:<id>` and posts the Ops line. `machine-trust` refuses without a terminal.
Revoking stops the next `pair-trusted`.

## Needs Andy, once

Granting machine trust to Tardis's peer (and later to each of his machines), and the CLAUDE.md lines that say a ship
may run `pair-trusted` within that grant. Editing CLAUDE.md needs his permission in the harness.
