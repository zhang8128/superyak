"""Grants (spec A step 3, merge 3b: G7-G14 of docs/superpowers/specs/2026-10-15-grants-step3-design.md)."""
import base64
import pytest
from superyak_peer.common import uid
from superyak_peer.grants import short_id
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, verify_record
from test_instructions import docked
from test_signatures import card_of, raw_sign

DAY = 86400


def make(store, issuer, grantee, targets, rooms='*', hours=24, budget=5):
    """A grant stored through the store method POST /api/grants uses once its checks pass (G8): its id."""
    with store.transaction() as db:
        return store._insert_grant(db, issuer['id'], grantee['id'], [ship['id'] for ship in targets], rooms, hours, budget)


def validity(store, grant_id):
    with store.transaction() as db:
        return store._grant_validity(db, db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone())


def charge(store, grant_id, *ages):
    """One budget use per age, that many seconds before now, each under its own ticket id."""
    with store.transaction() as db:
        for age in ages:
            db.execute('INSERT INTO budget_uses(grant_id, ticket_id, created) VALUES(?,?,?)', (grant_id, uid(), store.clock() - age))


def narrowed(store, monkeypatch, **changes):
    """Test 6: the policy narrowed after the grant was made, by replacing _grant_policy (G7's one function)."""
    defaults = type(store)._grant_policy
    monkeypatch.setattr(store, '_grant_policy', lambda db: {**defaults(store, db), **changes})


def revoke_by_hand(store, grant_id, by, reason='revoked'):
    with store.transaction() as db:
        db.execute('UPDATE grants SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?',
                   (store.clock(), by and by['id'], reason, grant_id))


def test_a_new_grant_is_valid_and_its_short_id_is_four_characters(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    assert validity(store, grant) == (True, None)
    assert short_id(grant) == '#' + grant[:4] and len(short_id(grant)) == 5


def test_a_revoked_grant_names_who_revoked_it_even_once_expired(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    store.rename_user(users[0]['id'], 'Andy\n@serenity')  # a name is a person's text: one safe line in a reason
    grant = make(store, users[0], users[1], [ship], hours=1)
    revoke_by_hand(store, grant, users[0])
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} was revoked by Andy (at)serenity')
    clock[0] += 3600  # expired too: the revoked reason comes first (test 6)
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} was revoked by Andy (at)serenity')
    restored = make(store, users[0], users[1], [ship])
    revoke_by_hand(store, restored, None, 'restored')  # the restore reconcile records no person (G13)
    assert validity(store, restored) == (False, f'Grant #{restored[:4]} was revoked')


def test_a_grant_expires_at_its_expiry_time(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], hours=1)  # made at 1000000.0, so it expires at 1003600.0
    clock[0] += 3599
    assert validity(store, grant) == (True, None)
    clock[0] += 1
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} expired 1970-01-12 14:46 UTC')


def test_a_narrowed_policy_takes_effect_at_the_next_check(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], hours=24)
    policy = f"Grant #{grant[:4]} is no longer allowed by the station's policy"
    for changes, expected in (({'max_expiry_hours': 24}, (True, None)),  # exactly its lifetime still fits
                              ({'max_expiry_hours': 23}, (False, f'Grant #{grant[:4]} lasts longer than the station now allows')),
                              ({'max_depth': 1}, (True, None)),  # a root is a chain of one link
                              ({'max_depth': 0}, (False, policy)),
                              ({'grantees': {users[1]['id']}}, (True, None)),
                              ({'grantees': {users[3]['id']}}, (False, policy))):
        narrowed(store, monkeypatch, **changes)
        assert validity(store, grant) == expected, changes


def test_the_budget_counts_builds_in_the_last_24_hours_only(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], budget=2)
    charge(store, grant, DAY, DAY - 1)  # exactly 24 hours old no longer counts; a second younger does
    assert validity(store, grant) == (True, None)
    charge(store, grant, 0)
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} has used its 2 builds for the last 24 hours')
    single = make(store, users[0], users[1], [ship], budget=1)
    charge(store, single, 10)
    assert validity(store, single) == (False, f'Grant #{single[:4]} has used its 1 build for the last 24 hours')


def test_an_issuer_who_no_longer_owns_every_target_holds_no_valid_grant(env):
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    grant = make(store, users[0], users[1], [serenity, rio])
    with store.transaction() as db:  # by hand: ownership never changes today, but a restored or edited database could
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (users[3]['id'], rio['id']))
    assert validity(store, grant) == (False, 'Patient no longer owns Rio Grande')


def test_the_first_check_that_fails_is_the_reason(env, monkeypatch):
    """G9's order, one pair of neighbours at a time: each grant fails two checks, and the earlier one is the reason."""
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    spent_and_lost = make(store, users[0], users[1], [rio], budget=1)  # 4 (budget) before 5 (ownership)
    charge(store, spent_and_lost, 10)
    with store.transaction() as db:
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (users[3]['id'], rio['id']))
    assert validity(store, spent_and_lost) == (False, f'Grant #{spent_and_lost[:4]} has used its 1 build for the last 24 hours')
    spent = make(store, users[0], users[1], [serenity], budget=1)  # 3 (policy) before 4 (budget)
    charge(store, spent, 10)
    narrowed(store, monkeypatch, max_depth=0)
    assert validity(store, spent) == (False, f"Grant #{spent[:4]} is no longer allowed by the station's policy")
    long = make(store, users[0], users[1], [serenity], hours=24)  # 2 (expired) before 3 (lifetime)
    narrowed(store, monkeypatch, max_expiry_hours=1)
    clock[0] += DAY
    assert validity(store, long) == (False, f'Grant #{long[:4]} expired 1970-01-13 13:46 UTC')


def grant_row(store, grant_id):
    with store.transaction() as db:
        return dict(db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone())


def stored_grant_record(store, grant_id):
    with store.transaction() as db:
        return store._grant_record(db, grant_id)


def test_a_grants_signature_verifies_and_its_record_has_exactly_g12s_keys(env, tmp_path):
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    room = store.create_room(users[0]['id'], 'Ops', [users[1]['id']])
    grant = make(store, users[0], users[1], [serenity, rio], rooms=[room['id']], hours=48, budget=3)
    identity, record, signature = store._station_identity(), stored_grant_record(store, grant), grant_row(store, grant)['signature']
    card = card_of(identity)
    assert set(record) == RECORD_KEYS['grant']
    assert record == {'kind': 'grant', 'station': identity.peer_id, 'id': grant, 'issuer_id': users[0]['id'],
                      'grantee_id': users[1]['id'], 'actions': ['direct'], 'targets': [serenity['id'], rio['id']],
                      'rooms': [room['id']], 'expires': 1000000.0 + 48 * 3600, 'budget': 3, 'depth': 0, 'confirm': 'none',
                      'parent_id': None, 'charter_layer_id': None, 'charter_revision': None, 'follow': 0,
                      'created': 1000000.0}
    assert verify_record(card, record, signature)
    assert not verify_record(card, {**record, 'budget': 4}, signature)  # one changed value
    flipped = bytearray(base64.b64decode(signature))
    flipped[0] ^= 1
    assert not verify_record(card, record, base64.b64encode(bytes(flipped)).decode())
    other = PeerIdentity.load_or_create(tmp_path / 'other')
    named_other = {**record, 'station': other.peer_id}
    assert not verify_record(card, named_other, raw_sign(identity, named_other))  # names another station
    added = {**record, 'session': 'x'}
    assert not verify_record(card, added, raw_sign(identity, added))  # a key a later step might add
    missing = {key: value for key, value in record.items() if key != 'follow'}
    assert not verify_record(card, missing, raw_sign(identity, missing))
    forged = {**record, 'station': '0' * 64}
    assert not verify_record({**card, 'peer_id': '0' * 64}, forged, raw_sign(identity, forged))  # peer id isn't the key's hash
    anywhere = make(store, users[0], users[1], [serenity])
    assert stored_grant_record(store, anywhere)['rooms'] == '*'  # '"*"' parsed, not the stored text
    assert verify_record(card, stored_grant_record(store, anywhere), grant_row(store, anywhere)['signature'])


def test_a_grant_whose_signing_fails_is_not_stored(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')

    def refuse(self, record):
        raise ValueError('no key')

    monkeypatch.setattr(PeerIdentity, 'sign_record', refuse)
    with pytest.raises(ValueError):
        make(store, users[0], users[1], [ship])
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM grants').fetchone()[0] == 0  # signed in the insert's transaction, or not at all


def test_a_station_holding_grants_does_not_start_without_its_identity(tmp_path):
    """G4b, from merge 3b: a grant is a signed record, so a station holding one refuses to start without identity.json;
    and a new station's first grant still creates the identity (the row being signed doesn't count itself)."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    owner, other = store.create_user('owner', 'Owner', 'long-password'), store.create_user('other', 'Other', 'long-password')
    ship, _ = docked(store, owner['id'], 'serenity')
    assert not (store.data_dir / 'identity.json').exists()
    grant = make(store, owner, other, [ship])  # the station's first signature
    assert verify_record(card_of(PeerIdentity.load_or_create(store.data_dir)), stored_grant_record(store, grant),
                         grant_row(store, grant)['signature'])
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM revision_signatures').fetchone()[0] == 0  # the grant is the only record
    (store.data_dir / 'identity.json').unlink()
    with pytest.raises(ValueError, match='identity.json'):
        Store(store.data_dir)
