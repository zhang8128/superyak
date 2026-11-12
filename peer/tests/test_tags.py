"""The public-route-bound plan, Task 7a: tags, the keys and every mint site. Invitations and activations carry
`<random>.<kid>.<exp>.<tag>`, HMAC-SHA256 under their label's key, truncated to 16 bytes. Each mint site's credential
redeems once: the invite route, serve's approval, and the CLI's approval while serve runs. The two flows that mint
before any serve still work: bootstrap-super-admin, and the runbook's --renew-activation before the lighthouse starts.
The keys are made by serve at start or by a mint command, and never loaded by Store.__init__."""
import json
import time

from fastapi.testclient import TestClient
import pytest

from superyak_peer import tags
from superyak_peer.__main__ import main
from superyak_peer.app import create_app
from superyak_peer.auth import INVITATION_TOKEN, token_hash
from superyak_peer.db import Store

KEY, KID, NOW = b'k' * 32, '0a1b2c3d', 1_800_000_000


def test_a_tag_checks_for_its_own_label_key_and_time_only():
    good = tags.mint('invitation', KEY, KID, NOW + 60)
    assert tags.TAGGED.fullmatch(good) and len(good) <= tags.CREDENTIAL_MAX and INVITATION_TOKEN.fullmatch(good)
    keys = {KID: KEY}
    assert tags.check('invitation', keys, good, NOW)
    assert not tags.check('activation', keys, good, NOW)  # another label's tag
    assert not tags.check('invitation', {'ffffffff': KEY}, good, NOW)  # an unknown kid
    assert not tags.check('invitation', {KID: b'x' * 32}, good, NOW)  # another key under the same kid
    assert not tags.check('invitation', keys, good, NOW + 60)  # expired at its exp
    random, kid, exp, tag = good.split('.')
    for changed in (f'{random[:-1]}A.{kid}.{exp}.{tag}' if random[-1] != 'A' else f'{random[:-1]}B.{kid}.{exp}.{tag}',
                    f'{random}.{kid}.{int(exp) + 1}.{tag}', f'{random}.{kid}.{exp}.{tag[:-1]}{"A" if tag[-1] != "A" else "B"}'):
        assert not tags.check('invitation', keys, changed, NOW)
    for junk in ('', 'x' * 43, good + '.', good.replace('.', '-'), good + 'x' * 100, None, 7):
        assert not tags.check('invitation', keys, junk, NOW)
    with pytest.raises(ValueError):
        tags.mint('session', KEY, KID, NOW)


def test_the_invitation_pattern_takes_both_forms_and_nothing_else():
    assert INVITATION_TOKEN.fullmatch('a' * 43)  # an untagged invitation made before the deploy
    assert INVITATION_TOKEN.fullmatch(tags.mint('activation', KEY, KID, NOW))
    for junk in ('a' * 42, 'a' * 44, 'a' * 43 + '.0a1b2c3d.1.short', 'a' * 43 + '.0A1B2C3D.1.' + 'b' * 22):
        assert not INVITATION_TOKEN.fullmatch(junk)


def meta_keys(data_dir):
    with Store(data_dir, signing=False).reading() as db:
        return {row[0]: json.loads(row[1]) for row in db.execute("SELECT key, value FROM system_meta WHERE key LIKE 'tag_key:%'")}


def test_a_store_alone_makes_no_key_and_loads_none(tmp_path):
    store = Store(tmp_path / 'home')
    assert store.tag_keys is None and meta_keys(tmp_path / 'home') == {}


def test_serve_makes_every_labels_key_at_start_and_a_second_start_keeps_them(tmp_path):
    app = create_app(tmp_path / 'home', allowed_origins=['http://testserver'])
    first = meta_keys(tmp_path / 'home')
    assert set(first) == {'tag_key:invitation', 'tag_key:activation'}
    assert first['tag_key:invitation']['kid'] != first['tag_key:activation']['kid']
    assert {label: list(keys) for label, keys in app.state.store.tag_keys.items()} == {
        label: [first[f'tag_key:{label}']['kid']] for label in tags.LABELS}
    again = create_app(tmp_path / 'home', allowed_origins=['http://testserver'])
    assert meta_keys(tmp_path / 'home') == first and again.state.store.tag_keys == app.state.store.tag_keys


def test_two_processes_making_a_key_at_once_both_use_the_one_that_won(tmp_path):
    """INSERT OR IGNORE under the gate, then a re-read: the loser reads the winner's key, never its own."""
    one, two = Store(tmp_path / 'home'), Store(tmp_path / 'home')
    with one.transaction() as db:
        won = tags.label_key(db, 'invitation')
    with two.transaction() as db:
        assert tags.label_key(db, 'invitation') == won


@pytest.fixture
def station(tmp_path):
    """On the real clock: the CLI's own Store, in the approval test, reads it."""
    app = create_app(tmp_path / 'home', allowed_origins=['http://testserver'])
    store = app.state.store
    admin = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    client = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    answer = client.post('/api/login', json={'username': 'andy', 'password': 'long-password-andy'})
    client.headers['x-csrf-token'] = answer.json()['csrf_token']
    return app, store, admin, client, store.clock


def redeems_once(app, token, username, name='A Person'):
    stranger = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    form = {'token': token, 'username': username, 'name': name, 'password': 'long-password-new'}
    assert stranger.post('/api/invitations/redeem', json=form).status_code == 201
    assert stranger.post('/api/invitations/redeem', json={**form, 'username': username + '2'}).status_code == 400


def tagged_for(store, label, token, now):
    return tags.check(label, store.tag_keys[label], token, now)


def test_the_invite_routes_invitation_is_tagged_and_redeems_once(station):
    app, store, _, client, clock = station
    made = client.post('/api/invitations', json={'expires_in': 3600}).json()
    assert tagged_for(store, 'invitation', made['token'], clock()) and made['id'] == token_hash(made['token'])
    assert not tagged_for(store, 'activation', made['token'], clock())
    redeems_once(app, made['token'], 'invited')


def requested(app):
    door = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    asked = door.post('/api/access-requests', json={'name': 'Eve', 'contact': 'eve@example.org', 'note': ''})
    assert asked.status_code == 201, asked.text
    return door, asked.json()


def test_serves_approval_mints_a_tagged_invitation_that_redeems_once(station):
    app, store, _, client, clock = station
    door, asked = requested(app)
    assert client.post(f"/api/access-requests/{asked['id']}/approve").status_code == 200
    token = door.get(f"/api/access-requests/{asked['id']}", params={'secret': asked['secret']}).json()['token']
    assert tagged_for(store, 'invitation', token, clock())
    redeems_once(app, token, 'eve')


def test_the_clis_approval_while_serve_runs_uses_serves_key(station, capsys):
    """station-approve's own Store makes no new key (serve made it at start) and mints under the same kid."""
    app, store, _, _, clock = station
    door, asked = requested(app)
    main(['station-approve', '--data-dir', str(store.data_dir), '--id', asked['id'][:8], '--as', 'andy'])
    capsys.readouterr()
    token = door.get(f"/api/access-requests/{asked['id']}", params={'secret': asked['secret']}).json()['token']
    assert tagged_for(store, 'invitation', token, clock())
    redeems_once(app, token, 'eve')


def activation(path):
    return json.loads(path.read_text())


def test_bootstrap_before_any_serve_makes_the_key_and_its_activation_redeems_once(tmp_path, capsys):
    """peer/README.md's first steps: the CLI mints before serve ever ran, so the CLI makes the activation key, and
    serve's start loads that one."""
    home, claim = tmp_path / 'home', tmp_path / 'activation.json'
    main(['bootstrap-super-admin', '--data-dir', str(home), '--username', 'stanley', '--name', 'Stanley',
          '--activation-file', str(claim)])
    capsys.readouterr()
    made = meta_keys(home)
    assert set(made) == {'tag_key:activation'}  # only the label it minted
    app = create_app(home, allowed_origins=['http://testserver'])
    assert list(app.state.store.tag_keys['activation']) == [made['tag_key:activation']['kid']]
    record = activation(claim)
    assert tags.check('activation', app.state.store.tag_keys['activation'], record['token'], time.time())
    redeems_once(app, record['token'], 'stanley', 'Stanley')


def test_a_renewed_activation_before_the_lighthouse_starts_redeems_once_and_the_old_one_never(tmp_path, capsys):
    """station-restore.md step 7: --renew-activation runs before step 8 starts the lighthouse."""
    home = tmp_path / 'home'
    first, renewed = tmp_path / 'first.json', tmp_path / 'renewed.json'
    common = ['--data-dir', str(home), '--username', 'stanley', '--name', 'Stanley']
    main(['bootstrap-super-admin', *common, '--activation-file', str(first)])
    main(['bootstrap-super-admin', *common, '--activation-file', str(renewed), '--renew-activation'])
    capsys.readouterr()
    app = create_app(home, allowed_origins=['http://testserver'])
    stranger = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    old = {'token': activation(first)['token'], 'username': 'stanley', 'name': 'Stanley', 'password': 'long-password-new'}
    assert stranger.post('/api/invitations/redeem', json=old).status_code == 400
    redeems_once(app, activation(renewed)['token'], 'stanley', 'Stanley')


def test_an_untagged_invitation_from_before_the_deploy_still_redeems_once(station):
    app, store, admin, _, clock = station
    old = 'u' * 43
    with store.transaction() as db:
        db.execute('INSERT INTO invitations(token_hash,creator_id,expires) VALUES(?,?,?)', (token_hash(old), admin['id'], clock() + 3600))
    redeems_once(app, old, 'early')
