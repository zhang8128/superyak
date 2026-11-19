## Required facts

1. A ship of this station that has an owner can pair another peer's ship with no typed pairing code, only within a live owner trust a person granted, and only when every check holds. — task: "Let one of this station's ships that has an owner" — tests: test_a_ship_pairs_and_shows_its_owner_first
2. Every refusal says why. — task: "Nothing is written until they all pass, and each refusal" — tests: every refusal test checks a word of the message
3. An actor that is not a ship of this station with an owner (an admin or person, a station ship with no owner, an unknown account) is refused with 403, and this check comes before any other, even with a malformed card. — task: "Anyone but such a ship" — tests: test_only_a_ship_with_an_owner_pairs
4. A malformed card (for example one with an extra field) is refused with 400. — task: "The ship's card must be well formed (400)" — tests: test_a_card_of_a_peer_not_paired_here
5. A card of a peer not paired here, or no longer paired, is refused with 409, with a reason explaining why. — task: "The ship's card must be well formed (400), come from a peer" — tests: test_a_card_of_a_peer_not_paired_here
6. A card of a retired peer is refused with 409. — task: "The ship's card must be well formed (400), come from a peer" — tests: test_a_card_of_a_peer_not_paired_here
7. The card must equal the peer's paired card in everything but the account it identifies; a card that differs anywhere else (its network address, for one) is refused with 409. — task: "The ship's card must be well formed ... and match that paired card" — tests: test_a_card_whose_other_fields_differ
8. The ship's assertion must verify against the paired card's key and be in date; a changed record or a signature by another key is refused with 400. — task: "The ship's signed assertion must verify" — tests: test_a_forged_card_from_a_public_card
9. The account the card identifies, its id and its name both, must be exactly the ship the assertion names, else 400 (a public person card altered to identify the ship is refused). — task: "The ship's signed assertion must verify ... and name exactly the account the card identifies" — tests: test_a_participant_that_differs_from_the_assertions, test_a_forged_card_from_a_public_card
10. The owner is the contact with the assertion's peer and owner id together, never the id alone; an owner of the same id on another peer is not covered by this owner's trust. — task: "The owner is the contact with the assertion's peer" — tests: test_an_owner_on_another_peer
11. The owner's pairing code must have been typed and still be current, else 409, with a reason that makes clear it is the owner that failed the check. — task: "The owner is the contact ...; its code must have been typed" — tests: test_a_trust_whose_owners_code_was_never_typed
12. A held owner is refused with 409. — task: "The owner is the contact ...; its code must have been typed ... and it must not be held" — tests: test_a_held_owner
13. With no live trust for that owner (never granted, revoked, or past its end) the pairing is refused with 403; a trust still pairs one second before its end and refuses from its end time on. — task: "A live trust must cover that owner" — tests: test_no_trust, test_an_expired_trust
14. A trust's ending leaves the peer paired and the ships it already paired in place and not held. — task: "A live trust must cover that owner ... and its ending leaves the peer" — tests: test_an_expired_trust
15. The assertion must date from strictly after the owner's trust was last revoked, even under a newer trust; one from at or before it is refused with 403, explaining why. — task: "The assertion must date from strictly after" — tests: test_an_assertion_issued_before_a_revocation
16. The ship's name must be 2 to 32 lowercase letters, digits and dashes, starting with a letter, else 400. — task: "The ship's name must be 2 to 32 lowercase letters" — tests: test_names_that_fail_ship_name_or_collide
17. The name must not match, by full Unicode case-folding, any local account's login name or display name or any person contact's name (a contact not paired by a trust), else 409. — task: "The ship's name must be 2 to 32 ... and match no local account's" — tests: test_names_that_fail_ship_name_or_collide
18. Ships of the same name on different peers may both be paired, each showing with its own owner. — task: "the same name on another peer is fine" — tests: test_a_ships_name_may_repeat_on_another_host
19. A ship that is already a contact here is refused with 409, including when its id is a person contact's id (no trust relabels a person). — task: "The ship must not already be a contact here" — tests: test_a_contact_that_already_exists
20. Each trust pairs at most 200 ships a UTC day; the next is refused with 429, the reason giving the limit of 200. — task: "Each trust pairs at most 200 ships a UTC day" / "The next gets 429" — tests: test_the_cap
21. A new UTC day counts afresh. — task: "The next gets 429 ... and a new UTC day starts afresh" — tests: test_the_cap
22. Each refusal at the cap is tallied per trust per UTC day (1, then 2) and nothing else is written. — task: "Cap refusals are tallied per trust per day" — tests: test_the_cap
23. No other refusal writes anything (no contact, confirmation, hold, peer or trust change). — task: "Cap refusals are tallied ...; no other refusal writes anything" / "Nothing is written until they all pass" — tests: every refusal test (each compares table counts before and after)
24. Every check runs in one transaction that takes the write lock first, so two pairings at once at 199 that day pair exactly one, the other is refused with 429, and the cap refusal is tallied once, in its own transaction after the pairing's rolls back. — task: "Cap refusals are tallied per trust per day, in their own transaction" / "Run the checks in one transaction" — tests: test_two_pairings_at_the_cap_pair_one
25. A pairing adds exactly one contact (on the ship's peer, with the ship's id and its own name, not held) and one confirmation record holding the grant, the acting ship, the signed assertion as canonical JSON, the time and the UTC day; nothing else changes. — task: "A pairing adds one contact on the ship's peer" — tests: test_a_ship_pairs_and_shows_its_owner_first
26. The result tells the caller that the trust, not a typed code, vouched for the pairing, and which grant. — task: "A pairing adds one contact ...; it reports that the trust, not a typed code" — tests: test_a_ship_pairs_and_shows_its_owner_first
27. The program gains one display label for every contact, there for any screen to use: a contact paired by a trust reads as its owner's ship, the owner's current name then the ship's name, still after the trust is revoked or the contact held, and an owner's rename shows; a person contact reads as its own name. The new command's success line uses it; the commit changes no other existing display. — task: "Give every contact one display form" — tests: test_a_ship_pairs_and_shows_its_owner_first, test_a_ships_name_may_repeat_on_another_host, test_pair_trusted_cli_pairs_with_no_terminal_and_no_code
28. A command lets a ship do this with no terminal and nothing on standard input, given the data directory, the card file, the assertion file and its own account. — task: "Add a command a ship runs" — tests: test_pair_trusted_cli_pairs_with_no_terminal_and_no_code
29. The command reads each file strictly, at most 6 MiB per file, and refuses a missing file, a directory, a file that is not JSON, one over 6 MiB, or one that is not a valid assertion (an extra field). — task: "It reads each file strictly, at most 6 MiB per file" / "A missing file, a directory" — tests: test_pair_trusted_cli_refuses_bad_files
30. The command refuses when there is no peer database (from the change), and when the account named is a person or does not exist, the line explaining why. — task: "A missing file, ... no peer database, or an account that is a person" — tests: test_pair_trusted_cli_pairs_with_no_terminal_and_no_code
31. A refusal of the command exits 1 with a single safe error line on standard error whose explanation is limited to 200 characters (the command's own prefix is outside that bound) and nothing on standard output. A refusal for any of the input or account failures of facts 29 and 30 writes nothing; a refusal at the daily cap still records its tally (fact 22). — task: "A missing file, ... each ends it with exit 1" / "None of these writes anything" — tests: test_pair_trusted_cli_refuses_bad_files, test_pair_trusted_cli_pairs_with_no_terminal_and_no_code
32. On success the command exits 0, leaves standard error empty, and prints one line giving the new contact's display label and saying the trust vouched for it. — task: "Success exits 0" — tests: test_pair_trusted_cli_pairs_with_no_terminal_and_no_code
33. The command never prints a pairing code, in either of its forms. — task: "It never prints a pairing code." — tests: test_pair_trusted_cli_refuses_bad_files, test_pair_trusted_cli_pairs_with_no_terminal_and_no_code

## Withheld facts

`peer/superyak_peer/__main__.py`
`__main__.py`
`peer/superyak_peer/federation.py`
`federation.py`
`peer/superyak_peer/owner_trust.py`
`owner_trust.py`
`peer/tests/test_owner_trust.py`
`test_owner_trust.py`
`pair_trusted`
`_pair_trusted`
`pair_trusted_command`
`pair-trusted`
`.pair_trusted(`
`TRUST_CAP`
`NOT_A_TRUSTED_SHIP`
`_AtCap`
`_name_taken`
`contact_labels`
`SELECT label`
`label`
`trust_cap_refusals`
`trust_confirmations`
`remote_contacts`
`contact_holds`
`pairing_confirmations`
`retired_peers`
`FROM peers`
`users`
`owner_trust`
`acting_ship_id`
`grant_id`
`confirmed_by`
`confirmed`
`refused`
`contact_id`
`ship_id`
`ship_name`
`owner_id`
`owner_user_id`
`user_id`
`peer_id`
`username`
`kind`
`issued`
`participant`
`event`
`'revoke'`
`seq`
`row['confirmed']`
`row['day']`
`row['assertion']`
`refused=refused+1`
`--data-dir`
`data-dir`
`--card`
`--assertion`
`--as`
`Federation(`
`.pair(`
`create_station_ship`
`grant_owner_trust`
`_new_ship`
`make_ship_assertion`
`check_ship_assertion`
`PeerIdentity`
`pairing_code`
`live_trust`
`_eligible`
`validate_card`
`canonical(`
`SHIP_NAME`
`safe_line`
`identity.parse`
`MAX_ENVELOPE`
`Problem(`
`BEGIN IMMEDIATE`
`Only a ship of this station with an owner pairs within an owner trust`
`That peer is not paired here: a person pairs it with its code first`
`This peer was retired; it comes back only as a new identity`
`This card differs from the peer's paired card`
`The card's participant is not the ship its assertion names`
`The ship's owner:`
`No live owner trust covers that owner`
`The assertion was issued before this owner's trust was last revoked; export a fresh one`
`A ship's name is 2 to 32 lowercase letters, digits and dashes, starting with a letter`
`That name is a local account or a person contact here`
`That ship is already a contact here`
`This owner trust has paired its`
`ships for today (UTC); try again tomorrow`
`This owner trust has paired its 200 ships for today (UTC); try again tomorrow`
`No peer database at`
`pair-trusted: `
`confirmed by owner trust`
`Paired <label>, confirmed by owner trust.`
`'ship of ' ||`
`ship of <owner>: <name>`
`ship of`
`an unknown owner`
`test_a_ship_pairs_and_shows_its_owner_first`
`test_only_a_ship_with_an_owner_pairs`
`test_no_trust`
`test_an_expired_trust`
`test_a_trust_whose_owners_code_was_never_typed`
`test_a_held_owner`
`test_a_card_of_a_peer_not_paired_here`
`test_a_card_whose_other_fields_differ`
`test_a_participant_that_differs_from_the_assertions`
`test_a_forged_card_from_a_public_card`
`test_an_owner_on_another_peer`
`test_an_assertion_issued_before_a_revocation`
`test_names_that_fail_ship_name_or_collide`
`test_a_ships_name_may_repeat_on_another_host`
`test_a_contact_that_already_exists`
`test_the_cap`
`test_two_pairings_at_the_cap_pair_one`
`test_pair_trusted_cli_refuses_bad_files`
`test_pair_trusted_cli_pairs_with_no_terminal_and_no_code`
`def trusted`
`def counts`
`def refuses`
`def pairs`
`b_ship`
`third_peer`
`label_of`
`utc_day`
`pair_trusted_cli`
`no_code`
`COUNTED = (`

Ordinary word: `card` — an option's name too, but the peer card is the existing thing the user hands over; no other word names it.
Ordinary word: `assertion` — an option's name too, but the signed assertion is the existing thing a ship's export writes; no other word names it.
Ordinary word: `as` — an option's name too, but a common English word.
Ordinary word: `pair` — an existing method's name too, but pairing is the act the user asks for.
Ordinary word: `canonical` — a function's name too, but how the stored assertion is serialised (canonical JSON) is a requirement.
Ordinary word: `day` — a column's name too, but the cap of 200 is per UTC day, a requirement.
Ordinary word: `name` — a column's name too, but the ship's name and its rule (2 to 32 characters) are requirements.
Ordinary word: `id` — a column's name too, but the owner is matched by peer and id together, a requirement.
Ordinary word: `station` — a field of the assertion too, but the program's and the user's word for this host.
Ordinary word: `paired` — a column's name too, but whether a peer is paired is the existing state the checks turn on.
Ordinary word: `at` — a column's name too, but a common preposition.

- Shape: the federation object's new method takes the acting account's id, the ship's card (a dict) and its signed assertion (a dict with record and signature), and returns the new contact's row as a dict plus a field saying owner trust confirmed it and the grant's id; a refusal raises the program's error type carrying a status and a message.
- Shape: the cap is a module constant equal to 200 in the federation module, and the test imports it.
- Shape: the label is read from a database view of (id, label) over every contact, which the tests query by contact id; it is 'ship of ' then the owner's current name (or 'an unknown owner') then ': ' then the contact's name for any contact with a trust confirmation, from its latest confirmation's grant, and the contact's own name otherwise.
- Shape: the confirmation record is a row with its id, contact id, grant id, the assertion as canonical JSON text, the acting ship's id, the confirmed time and the UTC day as YYYY-MM-DD; the cap refusals are rows of (grant id, day, refused count), one per grant and day.
- Shape: the command is run as python -m superyak_peer with a subcommand and four options (the data directory, the card, the assertion, the acting account), and the test reads its exit code, stdout and stderr; a refusal's line is the subcommand's name, a colon and a space, then the reason cut to 200 characters; success prints 'Paired ', the label, then ', confirmed by owner trust.'
- Tests with no behaviour to state: none; each test maps to a fact above. The tests check the exact success line and the exact label text, which the task gives only as their content (owner's name then ship's name; the trust vouched for it), not as wording.
