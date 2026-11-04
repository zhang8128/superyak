# Lessons room adds: the ship adds what Andy's code already vouched for

Rio Grande, 2026-11-03. Status: approved by a fresh Pi reviewer at revision 5 (6885593c) after four re-checks, its notes folded in after (law section 3). Revision 5 (trust-made ships join under their owner's live trust, bounded by hold, pause and a per-grant cap) after its fresh review and re-check (Majors: a removal undone; per-account vouching, at pair time and in the listing view). Amends first-rail spec section 3 ("Only Andy's", "Moderators": "Until then only Andy changes
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
   - if owner trust made it (a `trust_confirmations` row), its latest trust is live (unrevoked, unexpired, not paused)
     and its owner, the code-confirmed person contact on the same peer, is itself addable or already a member. Andy's
     grant already said how many ships to expect from that host, so his act per host covers each of its ships; he
     never approves agents one by one (Andy, 2026-11-03: "we're going to have thousands of agents running. are you
     saying I'm going to need to approve every connection?");
     Because a stolen host key makes every assertion verify (owner trust M4), a trust-made member is bounded three
     ways, all at the origin:
     - **a hold removes it.** Any hold of a trust-made contact (a revoke, a retire, an unpair, a restore) removes it
       from the lessons chain in the same transaction, recorded with reason `held`, so every index drops its lessons
       on its next run. A `held` removal isn't Andy's removal: a ship recovered under a later trust and a fresh
       assertion rejoins by Rio Grande's add;
     The hold's removal is a `member_changes` row with a new `reason` column (`held`; in the restore's lists), and
       `_owner_removed` skips `held` rows. Andy can still keep one ship out: his removal accepts a contact a hold took
       out of the chain, and records an owner removal for it. A retire removes every contact of the retired peer from
       the chain, its code-confirmed members too, since the stolen key speaks as them and a retired peer never
       re-pairs. A hold that covers many ships posts one removal notice for all of them;
     - **a paused grant lays nothing.** While its grant is paused, the origin's lesson gate refuses lessons from that
       grant's ships;
     - **one cap per grant.** All of one grant's ships share one LIVE_CAP of live lessons, so volume can't grow with
       the expected count.
     The pause and the shared cap are enforced at the origin's post and reply doors, since other peers' indexes can't
     see grants.
   - Andy vouched for this account, one of two ways: its confirmation's `confirmed_by` (a column `pair` now writes,
     the admin who typed the code) is the room's owner, and `pair` showed him the addable line (item 2); or the
     listing view he confirmed named it as addable (item 2a), which is how every contact paired before its peer was
     listed, or before this build, comes in.
2. **Pairing says what it makes addable, before the code.** When the card in hand is for an account on a peer listed
   for the lessons room, `pair` says so before the person types: the CLI before its code prompt, the browser beside
   its code box once the card's peer is known: "<name> on <peer 12> can be added to the lessons room by Rio Grande
   once you type its code; its lessons would reach every ship." `pair` writes `pairing_confirmations.confirmed_by`,
   its actor, and `pairing_confirmations.lessons_line=1` when the peer was listed in its own transaction (the line was
   shown). An add on this path needs both. The CLAUDE.md pairing paragraph says it too.
2a. **The listing names the addable accounts.** `make station-lessons-room … PEERS=` shows, under each listed peer,
   every code-current, unheld contact on it that owner trust didn't make, as "addable by Rio Grande", and those
   contact ids go into its confirm code, so the CONFIRM run records exactly what was shown (`lessons_addable`:
   contact id, the confirmation code shown, its `confirmed_by`, listing time). A CONFIRM rerun replaces the table,
   as it replaces `lessons_peers`, and a row counts only while the contact's current code and `confirmed_by` are
   still those shown, so a later re-pair under a new name, or by another admin, no longer counts. Peers are paired before they're listed, so this is the path for most accounts: Andy
   sees each one in the view he already confirms, and no new act is asked of him.
3. **Shown and recorded.** The command prints the contact's label and its user id's short form, its peer's 12
   characters, the old and new room's short ids, and how many lessons were carried. `station_notices` builds a one-off
   Ops notice from the add's `member_changes` row, id `lessons-add-<member_changes.id>` (change 'add', a room in the
   lessons chain, actor not the room's owner): "<label> (<user id short>) on <peer 12> joined the lessons room, added by
   <ship>", through `safe_line`. A retry or an Odo restart posts it once.
4. **What stays Andy's.** Opening the room; listing a peer (his word that a machine holds only his accounts and ships);
   removing a member, and adding back one he removed; retracting a lesson. His per-host acts (the two codes and the
   owner-trust grant with its expected count) are the only ones a new agent needs, however many there are.

**Owner trust's pause notice** adds, when the trust's ships wait for the lessons room: "<k> of its ships wait for the
lessons room until you renew." **Owner trust 4a's damage line** ("A trust-made ship lands in no room") becomes: "A
trust-made ship lands in no room but the lessons room, and only under a live trust, removed from it by any hold,
silenced while its grant is paused, and capped per grant."

**Order:** the build lands after owner trust merges, since it uses `code_current` and `trust_confirmations` from that
branch. Owner trust's line "Pairing grants no content, and no room by itself" gains: "except that a typed code for an
account on a peer listed for the lessons room makes it addable there by Rio Grande (lessons-room adds spec)."

## What doesn't change

The pairing law, the listing, the chain and its carry, and every check at the room's doors (section 3). A recorded
room still takes no new local member.

## Tests (for the build)

Each refusal writes nothing: an unlisted peer; an unconfirmed, stale or held contact; a trust-made contact whose trust is revoked, expired or paused, or whose owner
isn't addable; an existing
member; a contact Andy removed; a contact confirmed by another admin; a contact id that isn't remote; a moved chain (the add
goes to the chain's newest room). `pair` of an account on a listed peer says the addable line before the code prompt, and writes
`confirmed_by`; on an unlisted peer it doesn't. A contact confirmed by another admin, or with no `confirmed_by` and not
in `lessons_addable`, is refused. The listing view names the addable contacts, and its confirm code changes when one
is added or goes stale. The notice posts once per add, keyed by its `member_changes` row. The restore keeps `confirmed_by`, `lessons_line` and
`lessons_addable` in its compared lists (backups.py `COMPARED`/`_usable`); a restored confirmation with no `confirmed_by`
comes in only through 2a. A trust-made ship is added while its trust is live and its owner addable, and refused when
its trust is revoked, expired or paused, or its owner isn't addable. A hold of a trust-made member removes it from the chain
(reason `held`) and its lessons leave every index; a paused grant's ship can't lay a lesson; one grant's ships share one
LIVE_CAP; a ship recovered under a later trust rejoins. The success path makes the chain's
next room with the contact, carries the chain's lessons once, and posts the notice once. The CLAUDE.md lessons-room
paragraph changes from "he adds his own account and that ship's account on that peer" to the new command, with
Andy's yes in the harness when it lands.
