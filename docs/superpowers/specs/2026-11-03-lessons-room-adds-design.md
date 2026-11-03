# Lessons room adds: the ship adds what Andy's code already vouched for

Rio Grande, 2026-11-03. Amends first-rail spec section 3 ("Only Andy's", "Moderators": "Until then only Andy changes
who is in it"), on branch trail-arrows-spec, 2026-10-27-first-rail-lessons-design.md.

## Why

Andy, 2026-11-03, after the lessons-room add waited on him for ten hours: "Why do you keep making me a blocker on
things you have autority and technical capability to do?" and "you 2 need to stop being blocked by me. this won't work
on the supercomputer if the entire system goes down unless we have all of the convoluted stakeholder systems blocked
every time. we'll just waste time and money."

The wait was a rule we wrote. Section 3 made every change to the room's members Andy's own act, so that only he
decides whose lessons reach every ship's sessions. But the person's act already happens earlier, and more strongly:
Andy types the pairing code that makes each account on another peer a confirmed contact here, and a peer is listed for
the room only when it holds his accounts and his ships. Adding that confirmed account to the room afterwards decides
nothing new. It's administration.

## The change

1. **A ship's act, within what Andy vouched for.** `make station-lessons-add CONTACT=<contact short id> SHIP=rio-grande`
   adds one remote contact to the lessons room's current room, as `station-add-ship` adds a ship: a new linked room
   with the same title and members plus the contact, the chain's carry (section 3's backfill) included. It needs no
   ask from Andy. It refuses, writing nothing, unless all of these hold:
   - the contact is a remote contact on a peer listed for the lessons room (`lessons_peers`);
   - its confirmation is a typed code that is still current (`code_current`), and it is not held;
   - it is not a member of the current room;
   - it is not a contact made by owner trust (a `trust_confirmations` row): a ship paired without a code joins the
     room only by Andy's own add, until a later spec says otherwise;
   - the acting account is a local ship with an owner, named by `SHIP`.
   The station's existing gate (`_lessons_add_gate`) still runs on the add, so a new local member is still refused.
2. **Shown and recorded.** The command prints the contact's label, its peer's 12 characters, the old and new room's
   short ids, and how many lessons were carried. Odo posts a one-off Ops notice for each add ("<label> on <peer 12>
   joined the lessons room, added by <ship>"), through `safe_line`, so a person sees every change without being
   asked for one.
3. **What stays Andy's.** Opening the room. Listing a peer (`station-lessons-room PEERS=`): that is his word that a
   machine holds only his accounts and ships, which no code proves. Removing a member, or retracting a lesson, stays
   his too, in the browser. This change only adds, and only accounts his own code confirmed on peers he listed.

## What doesn't change

The pairing law, the listing, the chain and its carry, and every check at the room's doors (section 3). A recorded
room still takes no new local member.

## Tests (for the build)

Each refusal writes nothing: an unlisted peer; an unconfirmed, stale or held contact; a trust-made contact; an existing
member; a person or an ownerless ship as the actor; a contact id that isn't remote. The success path makes the chain's
next room with the contact, carries the chain's lessons once, and posts the notice once. The CLAUDE.md lessons-room
paragraph changes from "he adds his own account and that ship's account on that peer" to the new command, with
Andy's yes in the harness when it lands.
