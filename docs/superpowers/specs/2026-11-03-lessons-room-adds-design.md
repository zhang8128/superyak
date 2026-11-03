# Lessons room adds: the ship adds what Andy's code already vouched for

Rio Grande, 2026-11-03, revision 2 after its fresh review (two Majors: a removal undone, per-account vouching). Amends first-rail spec section 3 ("Only Andy's", "Moderators": "Until then only Andy changes
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

1. **A ship's act, within what Andy vouched for.** `make station-lessons-add CONTACT=<contact short id>` adds one remote
   contact to the lessons room's current room: `_lessons_chain(db)[-1]`, read in the add's own transaction, at the
   origin only (a key with `:` or an empty chain is refused; a race with another add is `REPLACED_ADD`'s, as today). It
   needs no ask from Andy. The actor is the room's recorded ship (`lessons_room.ship_id`, owned by the room's owner),
   and the add runs as `_add_members(owner_id=<room owner>, actor_id=<that ship>, grant_id=None)`, so
   `member_changes.actor_id` and the room's "added" post name the ship. It refuses, writing nothing, unless all of these
   hold:
   - the contact is a remote contact on a peer listed for the lessons room (`lessons_peers`);
   - its confirmation is a typed code that is still current (`pairing_confirmations.code` equals the code of the
     stored card with this participant, and `peers.paired=1`, the rule `connections()` uses), and it is not held;
   - it is not a member of the current room;
   - Andy did not remove it: `_owner_removed(db, current, contact, owner)` is false (room-moderators M7's rule). Adding
     back a member he took out stays his act;
   - it is not a contact made by owner trust (a `trust_confirmations` row): a ship paired without a code joins the
     room only by Andy's own add, until a later spec says otherwise;
   - the station has no admin but the room's owner. The typed code is then his, since `pairing_confirmations`
     doesn't record who typed it. While another admin exists, the add is refused and says why.
2. **Pairing says what it makes addable.** When a person types the code for an account on a peer listed for the lessons
   room, `pair` (the CLI and the browser) says so on success: "<name> on <peer 12> can now be added to the lessons room
   by Rio Grande; its lessons would reach every ship." The CLAUDE.md pairing paragraph says it too. So the person's
   act that vouches for an account is the code he types with that line in front of him, account by account, not the
   listing of its peer alone.
3. **Shown and recorded.** The command prints the contact's label and its user id's short form, its peer's 12
   characters, the old and new room's short ids, and how many lessons were carried. `station_notices` builds a one-off
   Ops notice from the add's `member_changes` row, id `lessons-add-<member_changes.id>` (change 'add', a room in the
   lessons chain, actor not the room's owner): "<label> (<user id short>) on <peer 12> joined the lessons room, added by
   <ship>", through `safe_line`. A retry or an Odo restart posts it once.
4. **What stays Andy's.** Opening the room; listing a peer (his word that a machine holds only his accounts and ships);
   removing a member, and adding back one he removed; adding a contact made by owner trust; retracting a lesson.

**Order:** the build lands after owner trust merges, since it uses `code_current` and `trust_confirmations` from that
branch. Owner trust's line "Pairing grants no content, and no room by itself" gains: "except that a typed code for an
account on a peer listed for the lessons room makes it addable there by Rio Grande (lessons-room adds spec)."

## What doesn't change

The pairing law, the listing, the chain and its carry, and every check at the room's doors (section 3). A recorded
room still takes no new local member.

## Tests (for the build)

Each refusal writes nothing: an unlisted peer; an unconfirmed, stale or held contact; a trust-made contact; an existing
member; a contact Andy removed; a station with a second admin; a contact id that isn't remote; a moved chain (the add
goes to the chain's newest room). `pair` of an account on a listed peer says the addable line; on an unlisted peer it
doesn't. The notice posts once per add, keyed by its `member_changes` row. The success path makes the chain's
next room with the contact, carries the chain's lessons once, and posts the notice once. The CLAUDE.md lessons-room
paragraph changes from "he adds his own account and that ship's account on that peer" to the new command, with
Andy's yes in the harness when it lands.
