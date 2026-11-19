## Required facts

1. A peer card may now be of a second version, which marks a peer that can't be reached from outside and so initiates its own fetches of waiting traffic from a reachable listener; such a card has no network address. — task: "Please add a second version of the peer card" — tests: test_a_v2_card_means_pull_and_its_variants_are_refused
2. There is no second-version card for a peer reached at its address: a second-version card that has an address, or that does not mark its peer as one that fetches, is rejected as an invalid card is today (400). — task: "There is no second-version card for a peer" — tests: test_a_v2_card_means_pull_and_its_variants_are_refused
3. A first-version card that carries that mark, whatever it says, or that has no address, a third-version card, and a version given as true rather than a number are rejected the same way. — task: "and so are a first-version card that carries" — tests: test_a_v2_card_means_pull_and_its_variants_are_refused
4. First-version cards are validated exactly as before. — task: "First-version cards are checked exactly as they are today." — tests: test_a_v1_card_is_byte_identical_to_todays
5. A peer building its own card is reached at its address by default, and the first-version card it builds is byte for byte the one it built before this change. — task: "When a peer builds its own card" — tests: test_a_v1_card_is_byte_identical_to_todays
6. Asked for a card for a peer that fetches, a peer builds a second-version card with no address; asked for one that fetches but given an address, or one reached at its address but given none, it rejects the card as invalid; asked for any other way of being reached, it raises an error. — task: "Asked for a card for a peer that fetches" / "Asked for one that fetches but given an address" — tests: test_a_v2_card_means_pull_and_its_variants_are_refused
7. A second-version card's pairing code covers the whole card: it differs when the key and the peer's id change, when the person on the card changes, and from the same peer's first-version card. — task: "The pairing code of a second-version card" — tests: test_a_v2_cards_code_covers_its_key_and_participant
8. A peer signs its own fetch request with its Ed25519 key, the same way it signs the signed packets peers send each other and its records, so that the signing covers every part of the request. — task: "A peer should sign its own fetch request" — tests: test_a_pull_requests_signature_is_its_own
9. A peer refuses to sign anything but a complete fetch request of its own: nothing missing and nothing extra, marked as a fetch request, naming itself as the asking peer (another asking peer, a request marked as anything else, or an extra part is refused). — task: "It should refuse to sign anything" — tests: test_a_pull_requests_signature_is_its_own
10. A fetch request checked against a card is accepted only when it is complete with nothing extra, is marked as a fetch request, names the card's peer as the asking peer, and its signing verifies under the card's key. — task: "Checking a fetch request against a card" — tests: test_a_pull_requests_signature_is_its_own
11. Any part of a fetch request changed after signing, or a check against another peer's card, is rejected with status 403, and the rejection explains why. — task: "Anything else, including any part changed" — tests: test_a_pull_requests_signature_is_its_own
12. A fetch request, a signed packet and a signed record never pass as one another: a packet fails the fetch-request check, a fetch request fails the packet check, a fetch request (with or without its signing) fails the record check, and the mark that makes a request a fetch request is reserved so no record type may take it. — task: "Because all three are signed the same way" — tests: test_a_pull_requests_signature_is_its_own
13. The strict JSON reader keeps the 6 MiB cap packets have today as its default, rejecting a larger body with status 413, but takes a caller's own cap, larger (for the reply to a fetch) or smaller, and enforces the cap named. — task: "Finally, the strict JSON reader keeps" — tests: test_parse_takes_an_explicit_limit

## Withheld facts

`peer/superyak_peer/identity.py`
`identity.py`
`peer/tests/test_identity.py`
`test_identity.py`
`validate_card`
`CARD_KEYS`
`PULL_KEYS`
`RECORD_KEYS`
`MAX_ENVELOPE`
`sign_pull`
`verify_pull`
`verify_envelope`
`verify_record`
`pairing_code`
`PeerIdentity`
`load_or_create`
`.card(`
`.envelope(`
`parse(`
`canonical(`
`limit=`
`delivery`
`'pull'`
`'push'`
`'version'`
`'kind'`
`origin`
`destination`
`nonce`
`'at'`
`'limit'`
`budget`
`'ack'`
`'refused'`
`'signature'`
`'endpoint'`
`signing_key`
`peer_id`
`certificate`
`fingerprint`
`'participant'`
`event_id`
`'code'`
`base64`
`Problem`
`ValueError`
`delivery is push or pull`
`Not a pull request this peer signs`
`Peer authentication failed`
`Envelope too large`
`Invalid peer card`
`_pull_request`
`test_a_v2_card_means_pull_and_its_variants_are_refused`
`test_a_v1_card_is_byte_identical_to_todays`
`test_a_v2_cards_code_covers_its_key_and_participant`
`test_a_pull_requests_signature_is_its_own`
`test_parse_takes_an_explicit_limit`

Ordinary word: `version` — the card already carries a version number people see; a second version of the card is the request itself and cannot be said without the word.
Ordinary word: `card` — the peer card is the thing people already exchange and compare; the change is to it, so the word cannot be avoided.
Ordinary word: `code` — "pairing code" is the existing name of the short code people compare; the task never uses the word for a declined event's reason.

- Shape (moved from required facts 1–3): the second-version card holds every first-version key (version, peer_id, signing_key, certificate, fingerprint, endpoint, participant), its endpoint key present with the value None, and one more key, delivery, with the value pull; version 2 with delivery push or None, or without delivery, and version 1 with any delivery key or endpoint None, are refused.
- Shape: a peer's card method takes the endpoint and the participant positionally and the delivery as a keyword only, defaulting to push; pull with endpoint None gives the version 2 card, which is returned validated; a delivery other than push or pull raises ValueError (moved from required fact 6).
- Shape (moved from required fact 9): a pull request has exactly eleven keys: version, kind (pull), origin, destination, nonce, at, limit, budget, ack, refused and signature; in the tests each element of refused is a dict with event_id and code.
- Shape (moved from required fact 8): the signing method takes the request without signature and returns a new dict with signature added, as base64 text, over the canonical JSON of the request without its signature.
- Shape (moved from required fact 10): refusals to sign are ValueError, not the module's HTTP problem class.
- Shape (moved from required fact 11): the pull verifier takes (card, request) and returns the request unchanged; it raises the module's HTTP problem class with status 403.
- Shape: the parser takes the raw body and a keyword limit defaulting to the envelope cap (6 * 1024 * 1024), and raises the problem class with status 413 above it.
- Shape: card refusals are the problem class with status 400.
- Tests with no behaviour to state: none (the check that pull is not among the record kinds is stated as fact 12; the ValueError class and the returned request in test_a_pull_requests_signature_is_its_own check only a shape, withheld above).
