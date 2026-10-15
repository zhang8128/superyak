# Spec A step 3, merge 3a: signed instructions revisions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The station signs every instructions revision with its Ed25519 identity key, backfills the revisions written
before this release (the active station law among them), and serves a revision's signed record to the layer's owner.

**Architecture:** `identity.py` gains a fixed record format (`RECORD_KEYS`), `PeerIdentity.sign_record` and a
`verify_record` that never raises. A new `signatures.py` mixin on `Store` loads the station identity at startup,
builds a revision's record from its stored snapshot, signs it in the transaction that writes the revision, backfills
unsigned revisions at every start, and answers one person route. `layers.py` calls the signer at its two revision
writes.

**Tech Stack:** Python 3.13, FastAPI, SQLite (`sqlite3`, JSON1), `cryptography` (Ed25519), pytest with FastAPI's
`TestClient`. Run tests from `peer/` with `uv run --locked python -m pytest -q`.

**Spec:** `docs/superpowers/specs/2026-10-15-grants-step3-design.md` (approved under D8, revision 3, with G4 amended
by this plan's review, M1), section 1 (G1-G6), Testing 1-4.

**Plan revision 2.** The fresh plan review of dae961a (APPROVE WITH CHANGES: 2 must-fix, 3 should-fix, 8 nits; it
dry-ran every task) is answered here: M1 (the identity is created at the first signature, not at every start), M2
(the bad-card assertion), S1 (creation under the dispatch gate), S2 (title and body from the snapshot), S3 (a second
start signs nothing), and N1-N7. N8 (passing the store's identity to `Federation`) is left out: federation already
reads the same file by path, and the startup test checks the two peer ids match. Spec A (`docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md`) holds
where the step 3 spec is silent.

## Global Constraints

- Record kinds and their exact key sets (G2, G3, G12), verbatim:
  - `instructions-revision`: `{kind, station, layer_id, revision, owner_id, title, body, audience_users, policy, created}`
  - `grant`: `{kind, station, id, issuer_id, grantee_id, actions, targets, rooms, expires, budget, depth, confirm, parent_id, charter_layer_id, charter_revision, follow, created}`
  - `grant-revocation`: `{kind, station, grant, revoked, revoked_by, reason}`
- A signature is base64 Ed25519 over `identity.canonical(record)`, as federation envelopes are (G3).
- `verify_record(card, record, signature)` checks, in this order: `validate_card`; the record is a dict whose `kind`
  is one of the three and whose keys are exactly that kind's set; `record["station"] == card["peer_id"]`; the
  signature. Otherwise False. It never raises (G3).
- Only a revision whose **stored snapshot** has `kind: "instructions"` is signed; never decide from the layer's
  current draft (G2, S3). A note's snapshot has no `kind` key (`peer/API.md`, Instruction layers).
- `policy` is `null` in step 3 (G2).
- The store loads the identity file federation uses (`identity.json` in the data directory) at startup if it exists;
  if that load fails, the station fails to start. A missing file is created (as `PeerIdentity.load_or_create` does)
  only at the first signature, inside the signing transaction (G4 as amended by plan review M1).
- `GET /api/layers/{id}/revisions/{n}/signed` answers the layer's owner only; anyone else gets 404 (the route never
  says whether a layer exists); a ship key gets 403 (G6).
- Every test is named, written first and seen failing first (spec, Testing).
- Repo norms: new modules and test files are listed in `peer/pyproject.toml` (the sdist `only-include` list and, for
  modules, the wheel `only-include` list); `test_packaging.py` checks the inventory.
- Superyak's repository only. The merge goes through section 2 of the station law: Rio Grande approves in the room,
  and the Pi suites pass.

## Review Focus

Inputs the spec implies but its four tests don't name, most likely to bite first. Each is pinned by a test below.

1. A non-ASCII title or body (`Règles · 規則`): `canonical()` writes UTF-8 (`ensure_ascii=False`), and the signature
   must still verify (Task 2, test 2).
2. A layer withdrawn after activation: its revisions stay signed, and the owner can still fetch them (Task 3).
3. A revision number that doesn't exist, and a note's revision: both 404, the same as someone else's layer (Task 3).
4. A second start right after the first: the backfill writes nothing and changes no signature (Task 2).
5. A `kind` that is not a string (a list) or a value `canonical()` refuses (NaN): `verify_record` returns False
   instead of raising (Task 1).
6. A new station: `init`, then the first `card --endpoint https://<host>`. The certificate must still name the host,
   so opening a store must not create the identity (Task 2).
7. The owner asks for revision `2**63` (past SQLite's integers): 404, not a 500 (Task 3).

## File Structure

- Modify `peer/superyak_peer/identity.py`: `RECORD_KEYS`, `_record_shape_ok`, `PeerIdentity.sign_record`,
  `verify_record`. The record format lives beside `canonical()` and the envelope code it mirrors.
- Create `peer/superyak_peer/signatures.py`: the `Signatures` mixin and `SIGNATURE_SCHEMA`. One responsibility: the
  station's signatures on stored records. Merge 3b adds grant records here.
- Modify `peer/superyak_peer/db.py`: the schema, the mixin, and two startup calls.
- Modify `peer/superyak_peer/layers.py`: one call at each of the two `layer_revisions` inserts (lines 128 and 162).
- Modify `peer/superyak_peer/app.py`: one route beside `/api/layers/{key}/revisions` (line 481).
- Modify `peer/API.md`: the Instruction layers paragraph and a new "Signed records" section.
- Modify `peer/pyproject.toml`: `superyak_peer/signatures.py` in both `only-include` lists, `tests/test_signatures.py`
  in the sdist one.
- Create `peer/tests/test_signatures.py`: tests 1-4 and the Review Focus cases.

`peer_store.py`'s `_own_peer_id` stays as it is. It reads the identity lazily and does not cache a failure, and
`test_a_failed_identity_read_is_not_cached` pins that. The new `_station_identity` is a separate cache: loaded at
startup when the file exists, created at the first signature when it doesn't.

---

### Task 1: The record format, `sign_record` and `verify_record`

**Files:**
- Modify: `peer/superyak_peer/identity.py` (after `validate_card`, around line 72; and a method on `PeerIdentity`
  after `card`, around line 130)
- Create: `peer/tests/test_signatures.py`
- Modify: `peer/pyproject.toml` (the sdist `only-include` list: add `"tests/test_signatures.py",` after `"tests/test_ships.py",`)

**Interfaces:**
- Consumes: `canonical`, `validate_card`, `PeerIdentity` (all in `identity.py`).
- Produces:
  - `RECORD_KEYS: dict[str, frozenset[str]]`, keyed by `'instructions-revision'`, `'grant'`, `'grant-revocation'`.
  - `PeerIdentity.sign_record(record: dict) -> str` (base64). Raises `ValueError` for a record that isn't one of
    `RECORD_KEYS`' kinds with exactly its keys, or that names another station.
  - `verify_record(card: dict, record: dict, signature: str) -> bool`. Never raises.

- [ ] **Step 1: Write the failing tests**

Create `peer/tests/test_signatures.py`:

```python
"""Station signatures over records (spec A step 3, merge 3a: G1-G6 of 2026-10-15-grants-step3-design.md)."""
import base64
import pytest
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, canonical, verify_record

ENDPOINT = 'https://station.test'  # a card needs an HTTPS endpoint; any will do for checking signatures


def card_of(identity):
    return identity.card(ENDPOINT, {'id': 'station', 'name': 'Station'})


def revision_record(identity, **changes):
    record = {'kind': 'instructions-revision', 'station': identity.peer_id, 'layer_id': 'l1', 'revision': 2,
              'owner_id': 'u1', 'title': 'House rules', 'body': 'Run the tests.', 'audience_users': ['s1'],
              'policy': None, 'created': 1000.5}
    record.update(changes)
    return record


def raw_sign(identity, record):
    """A signature made with the key directly, past sign_record's own checks, so verify_record's checks are tested."""
    return base64.b64encode(identity.key.sign(canonical(record))).decode()


def test_a_signed_record_verifies_and_one_changed_byte_fails(tmp_path):
    identity = PeerIdentity.load_or_create(tmp_path / 'a')
    card, record = card_of(identity), revision_record(identity)
    signature = identity.sign_record(record)
    assert verify_record(card, record, signature)
    assert not verify_record(card, revision_record(identity, body='Run the tests!'), signature)
    flipped = bytearray(base64.b64decode(signature))
    flipped[0] ^= 1
    assert not verify_record(card, record, base64.b64encode(bytes(flipped)).decode())


def test_a_record_naming_another_station_or_with_other_keys_never_verifies(tmp_path):
    a, b = PeerIdentity.load_or_create(tmp_path / 'a'), PeerIdentity.load_or_create(tmp_path / 'b')
    card = card_of(a)
    assert not verify_record(card_of(b), revision_record(a), a.sign_record(revision_record(a)))  # another station's card
    named_b = revision_record(a, station=b.peer_id)
    assert not verify_record(card, named_b, raw_sign(a, named_b))  # a's key, a's card, but the record names b
    added = {**revision_record(a), 'note': 'x'}
    assert not verify_record(card, added, raw_sign(a, added))
    missing = revision_record(a)
    del missing['policy']
    assert not verify_record(card, missing, raw_sign(a, missing))
    envelope = a.envelope(destination=b.peer_id, actor='u1', resource_id='r1', revision=1, action='room.message',
                          recipients=['u2'], payload={})
    signature = envelope.pop('signature')
    assert not verify_record(card, envelope, signature)  # an envelope without its signature has no record kind


def test_a_bad_card_or_malformed_input_gives_false_and_never_raises(tmp_path):
    identity = PeerIdentity.load_or_create(tmp_path / 'a')
    card, record = card_of(identity), revision_record(identity)
    signature = identity.sign_record(record)
    forged = revision_record(identity, station='0' * 64)  # names the forged id, so only validate_card can refuse it
    assert not verify_record({**card, 'peer_id': '0' * 64}, forged, raw_sign(identity, forged))  # peer id isn't the key's hash
    for args in ((None, record, signature), (card, None, signature), (card, record, None), (card, record, 'not base64!'),
                 (card, {**record, 'kind': ['instructions-revision']}, signature),
                 (card, revision_record(identity, created=float('nan')), signature), ('card', record, signature)):
        assert verify_record(*args) is False


def test_sign_record_refuses_anything_but_this_stations_records(tmp_path):
    a, b = PeerIdentity.load_or_create(tmp_path / 'a'), PeerIdentity.load_or_create(tmp_path / 'b')
    envelope = a.envelope(destination=b.peer_id, actor='u1', resource_id='r1', revision=1, action='room.message',
                          recipients=['u2'], payload={})
    for record in (revision_record(a, station=b.peer_id), {**revision_record(a), 'note': 'x'}, envelope,
                   {**revision_record(a), 'kind': 'grant'}):
        with pytest.raises(ValueError):
            a.sign_record(record)


def test_each_record_kind_signs_and_verifies_with_exactly_its_keys(tmp_path):
    identity = PeerIdentity.load_or_create(tmp_path / 'a')
    card = card_of(identity)
    assert set(RECORD_KEYS) == {'instructions-revision', 'grant', 'grant-revocation'}
    for kind, keys in RECORD_KEYS.items():
        record = {key: None for key in keys} | {'kind': kind, 'station': identity.peer_id}
        assert verify_record(card, record, identity.sign_record(record)), kind
    assert RECORD_KEYS['grant-revocation'] == {'kind', 'station', 'grant', 'revoked', 'revoked_by', 'reason'}
    assert RECORD_KEYS['instructions-revision'] == {'kind', 'station', 'layer_id', 'revision', 'owner_id', 'title',
                                                    'body', 'audience_users', 'policy', 'created'}
    assert RECORD_KEYS['grant'] == {'kind', 'station', 'id', 'issuer_id', 'grantee_id', 'actions', 'targets', 'rooms',
                                    'expires', 'budget', 'depth', 'confirm', 'parent_id', 'charter_layer_id',
                                    'charter_revision', 'follow', 'created'}
```

Add `"tests/test_signatures.py",` to the sdist `only-include` list in `peer/pyproject.toml` (under
`[tool.hatch.build.targets.sdist]`), after `"tests/test_ships.py",`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py`
Expected: collection error, `ImportError: cannot import name 'RECORD_KEYS' from 'superyak_peer.identity'`.

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/identity.py`, after `validate_card` (before `class PeerIdentity`):

```python
# Spec A step 3 (G3, G12): a signed record has exactly its kind's keys and names its station, so no record passes
# as another kind, as a federation envelope (which has no record kind), or as another station's.
RECORD_KEYS = {
    'instructions-revision': frozenset({'kind', 'station', 'layer_id', 'revision', 'owner_id', 'title', 'body',
                                        'audience_users', 'policy', 'created'}),
    'grant': frozenset({'kind', 'station', 'id', 'issuer_id', 'grantee_id', 'actions', 'targets', 'rooms', 'expires',
                        'budget', 'depth', 'confirm', 'parent_id', 'charter_layer_id', 'charter_revision', 'follow',
                        'created'}),
    'grant-revocation': frozenset({'kind', 'station', 'grant', 'revoked', 'revoked_by', 'reason'}),
}

def _record_shape_ok(record):
    return (isinstance(record, dict) and isinstance(record.get('kind'), str)
            and RECORD_KEYS.get(record['kind']) == set(record))
```

In `class PeerIdentity`, after `card`:

```python
    def sign_record(self, record):
        """G3: this station's signature over one of its own records (RECORD_KEYS), base64."""
        if not _record_shape_ok(record) or record['station'] != self.peer_id:
            raise ValueError('Not a record this station signs')
        return base64.b64encode(self.key.sign(canonical(record))).decode()
```

At the end of the module (after `verify_envelope` and anything below it), separated by one blank line as the
module's other top-level definitions are:

```python
def verify_record(card, record, signature):
    """G3: True only for a valid card, a record with exactly its kind's keys that names the card's station, and a
    signature over its canonical JSON by the card's key. Anything else is False."""
    try:
        validate_card(card)
        if not _record_shape_ok(record) or record['station'] != card['peer_id']:
            return False
        key = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(card['signing_key'], validate=True))
        key.verify(base64.b64decode(signature, validate=True), canonical(record))
        return True
    except Exception:  # noqa: BLE001 - a verifier answers False and never raises (G3)
        return False
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py tests/test_identity.py tests/test_packaging.py`
Expected: all pass.

- [ ] **Step 5: Check the tests bite**

Apply each mutation alone, run `tests/test_signatures.py`, see at least one failure, and restore:
- in `verify_record`, drop `or record['station'] != card['peer_id']` → the "names b" assertion fails;
- in `_record_shape_ok`, replace the key-set comparison with `record.get('kind') in RECORD_KEYS` → the added-key
  and missing-key assertions fail (the envelope assertion still passes, since an envelope has no `kind` at all);
- in `verify_record`, drop `validate_card(card)` → the bad-card assertion fails;
- in `sign_record`, drop the `raise` → `test_sign_record_refuses_anything_but_this_stations_records` fails.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/identity.py peer/tests/test_signatures.py peer/pyproject.toml
git commit -m "Grants 3a: a fixed record format, sign_record and verify_record (G3)"
```

---

### Task 2: The store signs instructions revisions, at the write and at startup

**Files:**
- Create: `peer/superyak_peer/signatures.py`
- Modify: `peer/superyak_peer/db.py` (imports, the `Store` bases, the `executescript` list at line 62, two calls at
  the end of `__init__` after `self._backfill_brief_history()`)
- Modify: `peer/superyak_peer/layers.py:128` (in `activate_layer`) and `:162` (in `revoke_layer_routes`)
- Modify: `peer/pyproject.toml` (add `"superyak_peer/signatures.py",` after `"superyak_peer/ships.py",` in both
  `only-include` lists, sdist and wheel)
- Test: `peer/tests/test_signatures.py`

**Interfaces:**
- Consumes: `PeerIdentity.load_or_create`, `PeerIdentity.sign_record`, `RECORD_KEYS` (Task 1); `Store.transaction`,
  `Layers._owned_layer`; `common.require`.
- Produces:
  - `SIGNATURE_SCHEMA: str`
  - `Signatures._load_station_identity(self) -> None` (startup: loads `identity.json` if it exists; raises if it can't)
  - `Signatures._station_identity(self) -> PeerIdentity` (the identity; creates the file if missing, so call it only
    inside a signing transaction, or where a signature already exists)
  - `Signatures._revision_record(self, db, layer_id: str, revision: int) -> dict | None`
  - `Signatures._sign_revision(self, db, layer_id: str, revision: int) -> None`
  - `Signatures._backfill_revision_signatures(self) -> None`
  - Task 3 adds `Signatures.revision_signed(self, actor, layer_id, revision) -> dict` to this module.

- [ ] **Step 1: Write the failing tests**

Add `from test_instructions import activate, docked, new_layer` to the imports at the top of
`peer/tests/test_signatures.py` (tests share helpers this way, e.g. `test_deferrals.py` imports from `test_presence`),
then append:

```python
def signature_rows(store):
    with store.transaction() as db:
        return {(r['layer_id'], r['revision']): r['signature'] for r in db.execute('SELECT * FROM revision_signatures')}


def stored_record(store, layer_id, revision):
    with store.transaction() as db:
        return store._revision_record(db, layer_id, revision)


def test_activation_and_narrowing_sign_each_instructions_revision(env):
    app, clients, users, clock = env
    store = app.state.store
    first, _ = docked(store, users[0]['id'], 'serenity')
    second, _ = docked(store, users[0]['id'], 'rio-grande')
    layer = new_layer(clients[0], kind='instructions', title='Règles · 規則', body='Run the tests. ✓',
                      audience_users=[first['id'], second['id']])
    assert activate(clients[0], layer).status_code == 200
    edited = clients[0].put(f'/api/layers/{layer["id"]}', json={'version': layer['version'], 'title': 'Changed',
                                                                'body': 'Changed draft'})
    assert edited.status_code == 200, edited.text  # the draft moves on; the revisions keep what was activated
    narrowed = clients[0].post(f'/api/layers/{layer["id"]}/revoke', json={'revision': 1, 'user_ids': [second['id']]})
    assert narrowed.status_code == 200, narrowed.text
    rows, card = signature_rows(store), card_of(store._station_identity())
    assert set(rows) == {(layer['id'], 1), (layer['id'], 2)}
    for revision, audience in ((1, [first['id'], second['id']]), (2, [first['id']])):
        record = stored_record(store, layer['id'], revision)
        assert record['audience_users'] == audience and record['policy'] is None
        assert record['title'] == 'Règles · 規則' and record['body'] == 'Run the tests. ✓'
        assert record['owner_id'] == users[0]['id'] and record['station'] == store._station_identity().peer_id
        assert verify_record(card, record, rows[(layer['id'], revision)])


def test_a_note_is_never_signed_and_the_kind_comes_from_the_revision(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    note = new_layer(clients[0], title='Private note', body='mine')
    assert activate(clients[0], note).status_code == 200
    changing = new_layer(clients[0], title='Was a note', body='first')
    assert activate(clients[0], changing).status_code == 200  # revision 1: a note
    saved = clients[0].put(f'/api/layers/{changing["id"]}', json={'version': changing['version'], 'kind': 'instructions',
                                                                  'title': 'Now law', 'body': 'second',
                                                                  'audience_users': [ship['id']]})
    assert saved.status_code == 200, saved.text
    assert activate(clients[0], saved.json()).status_code == 200  # revision 2: instructions
    assert set(signature_rows(store)) == {(changing['id'], 2)}
    assert stored_record(store, changing['id'], 1) is None and stored_record(store, note['id'], 1) is None


def test_startup_signs_each_unsigned_instructions_revision_once(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    law = new_layer(clients[0], kind='instructions', title='Station law', body='Be kind.', audience_users=[ship['id']])
    assert activate(clients[0], law).status_code == 200
    note = new_layer(clients[0], title='Note')
    assert activate(clients[0], note).status_code == 200
    with store.transaction() as db:
        db.execute('DELETE FROM revision_signatures')  # as a station from before this release has them
    from superyak_peer.db import Store
    restarted = Store(store.data_dir)
    rows = signature_rows(restarted)
    assert set(rows) == {(law['id'], 1)}
    assert verify_record(card_of(restarted._station_identity()), stored_record(restarted, law['id'], 1), rows[(law['id'], 1)])
    assert restarted._station_identity().peer_id == app.state.federation.identity.peer_id  # the identity federation uses
    signed, real = [], PeerIdentity.sign_record
    monkeypatch.setattr(PeerIdentity, 'sign_record', lambda self, record: signed.append(record) or real(self, record))
    assert signature_rows(Store(store.data_dir)) == rows and signed == []  # a second start signs nothing


def test_a_station_whose_identity_cannot_be_read_does_not_start(tmp_path):
    from superyak_peer.db import Store
    (tmp_path / 'station').mkdir(mode=0o700)
    (tmp_path / 'station' / 'identity.json').write_text('not json')
    with pytest.raises(ValueError):
        Store(tmp_path / 'station')


def test_a_new_stations_first_card_still_names_its_host(tmp_path, capsys):
    """Plan review M1: opening a store creates no identity, so `card --endpoint` (after `init`) can still put the
    station's host in its certificate, which peers reaching it by hostname check."""
    import json
    from cryptography import x509
    from superyak_peer.__main__ import main
    from superyak_peer.db import Store
    store = Store(tmp_path / 'state')
    assert not (store.data_dir / 'identity.json').exists()
    store.create_user('owner', 'Owner', 'long-password', is_admin=True)
    main(['card', '--data-dir', str(store.data_dir), '--username', 'owner', '--endpoint', 'https://peer.example:7435'])
    certificate = x509.load_pem_x509_certificate(json.loads(capsys.readouterr().out)['certificate'].encode())
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert 'peer.example' in names


def test_the_first_signature_creates_a_missing_identity(tmp_path):
    from superyak_peer.db import Store
    store = Store(tmp_path / 'state')
    owner = store.create_user('owner', 'Owner', 'long-password')
    ship, _ = docked(store, owner['id'], 'serenity')
    layer = store.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Law', 'body': 'Be kind.',
                                             'audience_users': [ship['id']]})
    assert not (store.data_dir / 'identity.json').exists()
    store.activate_layer(owner['id'], layer['id'], layer['version'])
    assert (store.data_dir / 'identity.json').exists()
    card = card_of(PeerIdentity.load_or_create(store.data_dir))
    assert verify_record(card, stored_record(store, layer['id'], 1), signature_rows(store)[(layer['id'], 1)])
```

`test_a_new_stations_first_card_still_names_its_host` passes before this task too: it guards today's behaviour, and the
mutation in Step 5 that creates the identity at every start must fail it.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py`
Expected: the narrowing, note and startup tests fail with `sqlite3.OperationalError: no such table:
revision_signatures` (or `AttributeError: 'Store' object has no attribute '_station_identity'`), the first-signature
test with an `AssertionError` (no identity file is created), the identity test with `Failed: DID NOT RAISE`; the
first-card test passes (see above).

- [ ] **Step 3: Write the implementation**

Create `peer/superyak_peer/signatures.py`:

```python
"""Station signatures (spec A step 3, merge 3a; 2026-10-15-grants-step3-design.md G1-G6): the station's Ed25519
key signs each instructions revision, so a revision can be checked against the station's card. Merge 3b adds grants
and revocations here."""
import json
from .common import require
from .identity import PeerIdentity

SIGNATURE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(layer_id, revision));
'''


class Signatures:
    def _load_station_identity(self):
        """G4: at startup, the identity file federation uses is loaded if it exists (a symlink too, which
        load_or_create refuses), and a store that can't load it doesn't start. A missing one waits for the first
        signature, so a new station's first `card --endpoint` still names its host (plan review M1)."""
        path = self.data_dir / 'identity.json'
        if path.exists() or path.is_symlink():
            self._identity = PeerIdentity.load_or_create(self.data_dir)

    def _station_identity(self):
        """The identity, created if missing. Only a signing transaction creates it: that holds the dispatch gate, so
        two processes can't both create it, and a failed create rolls the signed write back (G4)."""
        if getattr(self, '_identity', None) is None:
            self._identity = PeerIdentity.load_or_create(self.data_dir)
        return self._identity

    def _revision_record(self, db, layer_id, revision):
        """G2: an instructions revision's record, from its stored snapshot; None for a note's revision or none."""
        row = db.execute('SELECT layers.owner_id, layer_revisions.snapshot, layer_revisions.created FROM layer_revisions '
                         'JOIN layers ON layers.id=layer_revisions.layer_id '
                         'WHERE layer_revisions.layer_id=? AND layer_revisions.revision=?', (layer_id, revision)).fetchone()
        snapshot = json.loads(row['snapshot']) if row else {}
        if snapshot.get('kind') != 'instructions':  # the revision's own kind, never the layer's current draft (S3)
            return None
        return {'kind': 'instructions-revision', 'station': self._station_identity().peer_id, 'layer_id': layer_id,
                'revision': revision, 'owner_id': row['owner_id'], 'title': snapshot['title'], 'body': snapshot['body'],
                'audience_users': snapshot['audience_users'], 'policy': None, 'created': row['created']}

    def _sign_revision(self, db, layer_id, revision):
        """G2: in the transaction that writes the revision. A note's revision is not signed."""
        record = self._revision_record(db, layer_id, revision)
        if record is not None:
            db.execute('INSERT INTO revision_signatures VALUES(?,?,?)',
                       (layer_id, revision, self._station_identity().sign_record(record)))

    def _backfill_revision_signatures(self):
        """G5: at every start, each instructions revision without a signature (written before this release) is
        signed once. One transaction, so two starts at once can't both sign the same revision."""
        with self.transaction() as db:
            unsigned = db.execute("SELECT layer_id, revision FROM layer_revisions "
                                  "WHERE json_extract(snapshot, '$.kind')='instructions' AND NOT EXISTS (SELECT 1 FROM "
                                  "revision_signatures WHERE revision_signatures.layer_id=layer_revisions.layer_id "
                                  "AND revision_signatures.revision=layer_revisions.revision)").fetchall()
            for row in unsigned:
                self._sign_revision(db, row['layer_id'], row['revision'])
```

In `peer/superyak_peer/db.py`:
- add the import after `from .breakouts import Breakouts, BREAKOUT_SCHEMA`:
  `from .signatures import Signatures, SIGNATURE_SCHEMA`
- add `Signatures` at the end of the `Store` bases: `..., RoomBoard, Breakouts, Signatures):`
- append `+ SIGNATURE_SCHEMA` to the `executescript(...)` argument at line 62, after `BREAKOUT_SCHEMA`;
- after `self._backfill_brief_history()  # ship briefs S5: after the schema, at every start`, add:

```python
        self._load_station_identity()  # spec A step 3, G4: a station that can't load its identity doesn't start
        self._backfill_revision_signatures()  # G5: after the schema, at every start
```

In `peer/superyak_peer/layers.py`, in `activate_layer`, right after
`db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, version, encode(snapshot), self.clock()))`:

```python
            self._sign_revision(db, key, revision)  # spec A step 3, G2: an instructions revision is signed as it is written
```

and in `revoke_layer_routes`, right after
`db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, active['draft_version'], encode(snapshot), self.clock()))`:

```python
            self._sign_revision(db, key, revision)  # G2: the narrowing's new revision, with its narrower audience
```

In `peer/pyproject.toml`, add `"superyak_peer/signatures.py",` after `"superyak_peer/ships.py",` in the sdist
`only-include` list and in the wheel `only-include` list.

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py tests/test_instructions.py tests/test_layers.py tests/test_federation.py tests/test_packaging.py`
Expected: all pass. `test_a_failed_identity_read_is_not_cached` still passes: it patches `load_or_create` after the
store has started, and `_own_peer_id` keeps its own lazy read.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_signatures.py`, see a failure, restore:
- delete the `_sign_revision` call in `revoke_layer_routes` → the narrowing test fails (no `(layer, 2)` row);
- in `_revision_record`, read the kind from the layer's draft (`SELECT draft FROM layers`) instead of the snapshot →
  the note-then-instructions test fails (revision 1 gets signed by the backfill or the record isn't None);
- delete the `self._load_station_identity()` line in `Store.__init__` → the identity test fails (`DID NOT RAISE`);
- replace that line with `self._station_identity()` (create at every start, the plan's first version) → the
  first-card test fails (the store created `identity.json`; the certificate line, run alone, fails too);
- delete `self._backfill_revision_signatures()` → the startup test fails.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/signatures.py peer/superyak_peer/db.py peer/superyak_peer/layers.py peer/pyproject.toml peer/tests/test_signatures.py
git commit -m "Grants 3a: the store signs each instructions revision, at the write and at startup (G1, G2, G4, G5)"
```

---

### Task 3: The owner reads a signed revision; API.md

**Files:**
- Modify: `peer/superyak_peer/signatures.py` (add `revision_signed`)
- Modify: `peer/superyak_peer/app.py` (a route right after `/api/layers/{key}/revisions`, line 481-483)
- Modify: `peer/API.md` (the "Instruction layers" paragraph near line 238, and a new "## Signed records" section
  before "## Files")
- Test: `peer/tests/test_signatures.py`

**Interfaces:**
- Consumes: `_owned_layer` (Layers), `_revision_record`, `_station_identity` (Task 2), `require`, `actor()` in
  `app.py` (403 for a ship key, via `current_user`).
- Produces: `Signatures.revision_signed(self, actor: str, layer_id: str, revision: int) -> dict` returning
  `{'station', 'record', 'signature'}`; route `GET /api/layers/{key}/revisions/{revision}/signed`.

- [ ] **Step 1: Write the failing tests**

Add `ship_client` to the `from test_instructions import ...` line at the top of `peer/tests/test_signatures.py`,
then append:

```python
def test_only_the_layers_owner_reads_a_signed_revision(env):
    app, clients, users, clock = env
    store = app.state.store
    mine, key = docked(store, users[0]['id'], 'serenity')
    theirs, _ = docked(store, users[1]['id'], 'jenn-ship')
    layer = new_layer(clients[0], kind='instructions', title='Law', body='Be kind.', audience_users=[mine['id'], theirs['id']])
    assert activate(clients[0], layer).status_code == 200
    path = f'/api/layers/{layer["id"]}/revisions/1/signed'
    answer = clients[0].get(path)
    assert answer.status_code == 200, answer.text
    signed = answer.json()
    assert set(signed) == {'station', 'record', 'signature'} and signed['station'] == store._station_identity().peer_id
    assert verify_record(card_of(store._station_identity()), signed['record'], signed['signature'])
    assert clients[1].get(path).status_code == 404  # owns a ship in the audience, but the layer binds only its owner's
    assert clients[2].get(path).status_code == 404  # an admin with no tie to it
    assert clients[0].get('/api/layers/no-such-layer/revisions/1/signed').status_code == 404
    for missing in (7, 0, 2 ** 63):  # none of them is a revision, and 2**63 is past SQLite's integers
        assert clients[0].get(f'/api/layers/{layer["id"]}/revisions/{missing}/signed').status_code == 404
    assert ship_client(app, key).get(path).status_code == 403


def test_a_notes_revision_has_no_signed_record_and_a_withdrawn_layers_still_does(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    note = new_layer(clients[0], title='Note')
    assert activate(clients[0], note).status_code == 200
    assert clients[0].get(f'/api/layers/{note["id"]}/revisions/1/signed').status_code == 404
    law = new_layer(clients[0], kind='instructions', title='Law', body='Be kind.', audience_users=[ship['id']])
    assert activate(clients[0], law).status_code == 200
    assert clients[0].post(f'/api/layers/{law["id"]}/withdraw').status_code == 200
    kept = clients[0].get(f'/api/layers/{law["id"]}/revisions/1/signed')
    assert kept.status_code == 200 and verify_record(card_of(store._station_identity()), kept.json()['record'], kept.json()['signature'])
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py -k "owner_reads or notes_revision"`
Expected: FAIL, the owner's request gets 404 (no such route), not 200.

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/signatures.py`, change the import to `from .common import Problem, require`, and add to
`class Signatures`:

```python
    def revision_signed(self, actor, layer_id, revision):
        """G6: {station, record, signature} for the layer's owner. Anyone else, and any revision without a signature
        (a note's, or one that doesn't exist), gets 404, so the route never says whether a layer exists."""
        with self.transaction() as db:
            self._owned_layer(db, actor, layer_id)
            if not 1 <= revision <= 2 ** 63 - 1:  # past SQLite's integers sqlite3 raises OverflowError; no such revision
                raise Problem(404, 'Not found')
            row = require(db.execute('SELECT signature FROM revision_signatures WHERE layer_id=? AND revision=?',
                                     (layer_id, revision)).fetchone())
            return {'station': self._station_identity().peer_id, 'record': self._revision_record(db, layer_id, revision),
                    'signature': row['signature']}
```

In `peer/superyak_peer/app.py`, right after the `revisions` route (`@app.get('/api/layers/{key}/revisions')` and its
two lines):

```python
    @app.get('/api/layers/{key}/revisions/{revision}/signed')
    def revision_signed(key: str, revision: int, request: Request):
        return store.revision_signed(actor(request), key, revision)
```

In `peer/API.md`, in the route table of "## Layers and publications", add after the
``| GET `/api/layers/{id}/revisions` | — | Immutable revision array; owner only |`` row:

``| GET `/api/layers/{id}/revisions/{n}/signed` | — | `{station, record, signature}` for an instructions revision; owner only (see Signed records) |``

In "## Store interfaces for following tasks", after the paragraph that begins "Trusted transaction helpers:", add:

`Signatures (spec A step 3): `_sign_revision(db,layer_id,revision)` signs an instructions revision inside the
transaction that writes it; `revision_signed(actor,key,revision)` returns its signed record to the layer's owner.`

In "## Instruction layers", replace

`it labels it with its owner's name (a label, not a cryptographic signature; that comes in a later step).`

with these two lines, wrapped at the paragraph's width:

```
it labels it with its owner's name, and the station signs each of its revisions with its Ed25519 key (see
Signed records).
```

and add this section right before `## Files`:

```markdown
## Signed records

The station signs records with its Ed25519 identity key, the one in `identity.json` that federation signs envelopes
with (spec A step 3, `docs/superpowers/specs/2026-10-15-grants-step3-design.md`). A record is a JSON object with
exactly its kind's keys (`identity.RECORD_KEYS`), and its signature is base64 Ed25519 over `identity.canonical(record)`.
Merge 3a signs one kind:

- `instructions-revision`: `{kind, station, layer_id, revision, owner_id, title, body, audience_users, policy, created}`.
  It is written in the transaction that writes a revision whose snapshot has `kind: "instructions"` (an activation or a
  narrowing). `title`, `body` and `audience_users` are the revision's snapshot, `policy` is `null`, and `created` is the
  revision's time. A note's revision is never signed. Revisions written before this release are signed once at the
  next start.

`GET /api/layers/{id}/revisions/{n}/signed` (person) returns `{station, record, signature}` to the layer's owner.
Anyone else, and any revision without a signature, gets 404; a ship key gets 403.

`identity.verify_record(card, record, signature)` returns True only when the card is valid, the record has exactly its
kind's keys (`instructions-revision`, `grant` or `grant-revocation`), its `station` is the card's peer id, and the
signature verifies. It never raises. A card exists only for a station with an HTTPS federation endpoint (`serve
--federation-endpoint`; `card --endpoint` prints one). A station that can't load its identity doesn't start; a new station creates it at its first
signature, so its first card export still names its host. The nightly copies leave out the identity files: a station
rebuilt from a copy without its own `identity.json` gets a new key, and its stored signatures stop verifying against
its new card (the backfill signs only unsigned revisions).
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py`
Expected: all pass.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run the two new tests, see a failure, restore:
- delete `self._owned_layer(db, actor, layer_id)` → the other person and the admin get 200, not 404;
- replace `actor(request)` with `member(request)['id']` in the route → the ship key gets 200 or 404, not 403.

- [ ] **Step 6: Run the whole peer suite**

Run: `cd peer && uv run --locked python -m pytest -q -p no:cacheprovider`
Expected: everything passes. The plan review measured 813 passed and 1 skipped at dae961a, and 824 passed with the
plan's first version; this revision adds two tests, so about 826 passed and 1 skipped on that base (more once the
build branch includes main's newer commits). Report the counts, and any failure by name.

- [ ] **Step 7: Commit**

```bash
git add peer/superyak_peer/signatures.py peer/superyak_peer/app.py peer/API.md peer/tests/test_signatures.py
git commit -m "Grants 3a: the layer's owner reads a revision's signed record; API.md (G6)"
```

---

## After the tasks

- Rebase or merge `main` before section 2 review if it moved.
- Section 2: post the head in "Superyak: city of AI" for Rio Grande; the Pi runs both suites. On merge, the deploy
  restarts the lighthouse; the first start signs the active station law (G5). A live check: as Andy in the browser
  console, `GET /api/layers/c879372542444e4c8f95f2c0db69f8fb/revisions/<active revision>/signed` returns a record that
  verifies against the station's card: `uv run --locked --project peer python -m superyak_peer card --data-dir
"$(STATION_DATA)" --username andy --endpoint https://<the station's host>:<port>` prints it.
