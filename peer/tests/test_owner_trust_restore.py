"""Owner trust Task 5 (docs/superpowers/specs/2026-11-02-machine-trust-design.md, items 4a, 6 and 7): a station
restore never brings back a revoked trust, a retirement, or a paused trust. The fixtures are test_owner_trust's (B's
person Andy B, paired at the station with his code, a live 90-day trust for him, and the station's ship rio-grande to
act), the restore helpers test_restore's."""
from contextlib import closing
import sqlite3

import pytest
from superyak_peer import backups
from superyak_peer.common import Problem
from superyak_peer.federation import RETIRED, Federation
from superyak_peer.identity import pairing_code
from test_owner_trust import (PASSWORD, b_ship, grant, machine, paired, pairs, queue, renew, revoke,  # noqa: F401 - fixtures
                              third_peer, trusted)
from test_restore import go_live, peer_rows, peer_station, reconcile, staged

TRUST_TABLES = ('owner_trust', 'trust_confirmations', 'trust_cap_refusals', 'retired_peers')


def rows_in(path, sql, *args):
    with closing(sqlite3.connect(path)) as db:
        return [tuple(row) for row in db.execute(sql, args)]


def revocations_in(path):
    return rows_in(path, "SELECT grant_id, reason, by_id, at FROM owner_trust WHERE event='revoke' ORDER BY seq")


def held_in(path, contact_id):
    return bool(rows_in(path, 'SELECT 1 FROM contact_holds WHERE contact_id=?', contact_id))


def trusts_line(out):
    return next((line for line in out.splitlines() if line.startswith('Owner trusts: ')), '')


def named(grant_id, owner, how):
    return f'{grant_id[:6]} ({owner}, {how})'


def against_live(capsys, t, copy):
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', t.station.db_path)
    assert code == 0, err
    return out


def test_a_revocation_after_the_copy_is_kept(trusted, capsys):
    """Spec item 7: the copy has the trust live and tardis paired under it; the live station then revokes it. The
    reconcile adds the replaced file's revocation with its time, person and reason, tardis stays held with its outbox
    withdrawn, and the copy, once live, pairs nothing under the trust. Mutation: the revocations left out of
    _keep_trust_like_replaced."""
    t = trusted
    tardis = pairs(t)
    queue(t.station, tardis['id'])
    copy = staged(t.tmp, t.station)
    t.clock[0] += 60
    revoke(t)
    out = against_live(capsys, t, copy)
    assert revocations_in(copy) == [(t.trust['grant_id'], 'revoked', t.admin['id'], t.clock[0])]
    assert held_in(copy, tardis['id'])
    assert rows_in(copy, 'SELECT status FROM outbox WHERE contact_id=?', tardis['id']) == [('withdrawn',)]
    assert named(t.trust['grant_id'], 'Andy B', 'revoked as in the replaced file') in trusts_line(out)
    assert 'owner trusts revoked (1)' in out
    live = go_live(copy, t.tmp / 'live')
    with pytest.raises(Problem) as caught:
        Federation(live, endpoint='https://localhost:7436').pair_trusted(t.ship, *b_ship(t, 'serenity'))
    assert caught.value.status == 403 and 'No live owner trust' in caught.value.message


def test_a_retirement_after_the_copy_is_kept(trusted, paired, capsys):
    """Spec item 6 (S11): the live station retires B's peer after the copy. The reconcile adds the retired_peers row
    with its time and person, the peer is unpaired and every contact of it held, the trust is revoked as in the
    replaced file, and the copy, once live, refuses to pair B's person whatever code is typed. Mutation: the
    retirements left out of _keep_trust_like_replaced."""
    t = trusted
    tardis = pairs(t)
    copy = staged(t.tmp, t.station)
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], t.owner['id'], retire=True)
    out = against_live(capsys, t, copy)
    peer = t.owner['peer_id']
    assert rows_in(copy, 'SELECT * FROM retired_peers') == [(peer, t.clock[0], t.admin['id'])]
    assert rows_in(copy, 'SELECT paired FROM peers WHERE peer_id=?', peer) == [(0,)]
    assert held_in(copy, t.owner['id']) and held_in(copy, tardis['id'])
    assert revocations_in(copy) == [(t.trust['grant_id'], 'owner held', None, t.clock[0])]
    assert 'peer retirements kept (1)' in out
    live = go_live(copy, t.tmp / 'live')
    person_card = paired[3]
    with pytest.raises(Problem) as caught:
        Federation(live, endpoint='https://localhost:7436').pair(t.admin['id'], person_card, code=pairing_code(person_card))
    assert (caught.value.status, caught.value.message) == (409, RETIRED)


def test_a_retirement_unpairs_its_peer_when_the_copy_has_it_paired(tmp_path, capsys):
    """The brief's backstop: a retired peer that the copy has paired is unpaired as Federation.unpair does, even when
    the replaced file (by hand here) still shows it paired, so _unpair_like_replaced left it. Mutation: the _unpair call
    left out."""
    store, peers = peer_station(tmp_path)
    copy = staged(tmp_path, store)
    with store.transaction() as db:
        db.execute('INSERT INTO retired_peers(peer_id, retired, by_id) VALUES (?, 5.0, NULL)', (peers['kept'],))
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    paired, outbox, inbox = peer_rows(copy)
    assert paired[peers['kept']] == 0 and outbox['o4'] == outbox['o5'] == 'withdrawn' and inbox[peers['kept']] is None
    assert paired[peers['cut']] == 1 and outbox['o0'] == 'pending'
    assert rows_in(copy, 'SELECT * FROM retired_peers') == [(peers['kept'], 5.0, None)]
    assert f'Unpaired again: {peers["kept"][:12]} (Kept).' in out


def test_without_a_replaced_file_every_trust_is_revoked(trusted, capsys):
    """Spec item 7 without a usable replaced file: what was revoked or retired since the copy can't be known, so every
    trust not yet revoked, the expired one too, is revoked now (reason `restored`, no person), its ships are held, the
    owner is not, and the report says retirements since the copy are gone. A second run revokes nothing twice. Names
    go through safe_line. Mutations: _revoke_every_trust left out; settle_owner_trust not run."""
    t = trusted
    tardis = pairs(t)
    t.clock[0] = t.trust['until'] + 10  # the first trust expires, and tardis stays paired under it
    second = grant((t.station, t.admin, t.owner, None), days=30)
    serenity = pairs(t, *b_ship(t, 'serenity'))
    copy = staged(t.tmp, t.station)
    with closing(sqlite3.connect(copy)) as db, db:  # a name from outside, as the report must show it
        db.execute("UPDATE remote_contacts SET name='Andy\n@B' WHERE id=?", (t.owner['id'],))
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 0, err
    revoked = revocations_in(copy)
    assert [row[:3] for row in revoked] == [(t.trust['grant_id'], 'restored', None), (second['grant_id'], 'restored', None)]
    assert held_in(copy, tardis['id']) and held_in(copy, serenity['id']) and not held_in(copy, t.owner['id'])
    assert backups.TRUST_RETIREMENTS_NOT_KEPT in out
    line = trusts_line(out)
    for grant_id in (t.trust['grant_id'], second['grant_id']):
        assert named(grant_id, 'Andy (at)B', 'revoked: no usable replaced file') in line
    assert 'ships held as their owner trust ended (2)' in out
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 0, err
    assert revocations_in(copy) == revoked and trusts_line(out) == ''


def test_a_trust_paused_in_the_replaced_file_is_revoked(trusted, capsys):
    """Spec item 4a, Restore: the copy has 1 pairing of expect=2 and the replaced file 2, so the trust is paused there
    and would come back live here, its notice already posted. The reconcile revokes it (reason `paused at restore`, no
    person) and ship-a is held. A copy reconciled while the replaced file had 1 of 2 keeps the trust live. Mutation:
    the paused step left out, or paused read as paired > expect."""
    t = trusted
    revoke(t)
    t.clock[0] += 60
    t.trust = grant((t.station, t.admin, t.owner, None), expect=2)
    ship_a = pairs(t, *b_ship(t, 'ship-a'))
    not_paused = staged(t.tmp, t.station, 'replaced-20261017-110000')
    against_live(capsys, t, not_paused)
    assert [row[0] for row in revocations_in(not_paused)] == [revocations_in(t.station.db_path)[0][0]]
    assert not held_in(not_paused, ship_a['id'])
    copy = staged(t.tmp, t.station)
    pairs(t, *b_ship(t, 'ship-b'))  # 2 of 2: paused in the live file
    out = against_live(capsys, t, copy)
    revoked = revocations_in(copy)
    assert len(revoked) == 2 and revoked[-1][:3] == (t.trust['grant_id'], 'paused at restore', None)
    assert held_in(copy, ship_a['id'])
    assert named(t.trust['grant_id'], 'Andy B', 'revoked: paused in the replaced file') in trusts_line(out)


def test_a_renewal_lost_with_the_copy_is_named(trusted, capsys):
    """Spec item 4a, Restore: a renewal made since the copy is lost with it, and so is a grant, so the report names
    each trust for the admin to renew or grant again; neither is revoked. Renewed again on the restored station, the
    new window takes a seq the replaced file never used, so its pause notice id (trust-paused-<grant>-<seq>) is new.
    Mutations: the lost rows not named; the owner_trust sequence not raised."""
    t = trusted
    pairs(t)
    andy_c, _ = third_peer(t)  # paired with his code before the copy
    copy = staged(t.tmp, t.station)
    t.clock[0] += 60
    renew((t.station, t.admin), t.trust['grant_id'], days=90)
    lost = t.station.grant_owner_trust(t.admin['id'], andy_c['id'], days=30, expect=5, password=PASSWORD, source='127.0.0.1')
    out = against_live(capsys, t, copy)
    line = trusts_line(out)
    assert named(t.trust['grant_id'], 'Andy B', 'renewed since the copy, and the renewal was lost: renew it again') in line
    assert named(lost['grant_id'], 'Andy C', 'granted since the copy, and the grant was lost: grant it again') in line
    assert revocations_in(copy) == [] and 'owner trusts revoked (0)' in out
    used = rows_in(t.station.db_path, 'SELECT MAX(seq) FROM owner_trust')[0][0]
    live = go_live(copy, t.tmp / 'live')
    renew((live, t.admin), t.trust['grant_id'], days=90)
    assert rows_in(live.db_path, "SELECT MAX(seq) FROM owner_trust WHERE event='renew'")[0][0] > used


def trust_objects(path):
    """Every table, trigger, index and view owner trust makes, as sqlite_master has them."""
    return rows_in(path, 'SELECT type, name, sql FROM sqlite_master WHERE tbl_name IN (?,?,?,?) OR name=? ORDER BY type, name',
                   *TRUST_TABLES, 'contact_labels')


def before_owner_trust(copy):
    with closing(sqlite3.connect(copy)) as db:
        db.execute('DROP VIEW contact_labels')
        for table in TRUST_TABLES:
            db.execute(f'DROP TABLE {table}')
        db.commit()
    assert trust_objects(copy) == []


@pytest.mark.parametrize('compared', [True, False])
def test_a_copy_from_before_owner_trust_restores(trusted, capsys, compared):
    """A copy taken before this build gains every owner trust table, trigger, index and view in the reconcile's own
    transaction (one statement at a time: executescript would commit it), skipping nothing, and with a replaced file
    a retirement since the copy is kept in it. Mutation: the tables not made (the reconcile fails)."""
    t = trusted
    copy = staged(t.tmp, t.station)
    before_owner_trust(copy)
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], t.owner['id'], retire=True)
    code, out, err = reconcile(capsys, '--db', copy, *(('--replaced', t.station.db_path) if compared else ()))
    assert code == 0, err
    assert trust_objects(copy) == trust_objects(t.station.db_path) != []
    assert not any(line.startswith('Skipped') for line in out.splitlines()), out
    if compared:
        assert rows_in(copy, 'SELECT peer_id FROM retired_peers') == [(t.owner['peer_id'],)] and trusts_line(out) == ''
    else:
        assert rows_in(copy, 'SELECT * FROM retired_peers') == [] and backups.TRUST_RETIREMENTS_NOT_KEPT in out
    go_live(copy, t.tmp / 'live')


@pytest.mark.parametrize('compared', [True, False])
@pytest.mark.parametrize('old_copy', [False, True])
def test_a_failure_after_the_trust_steps_changes_no_byte(trusted, capsys, monkeypatch, compared, old_copy):
    """Ruling 4: the owner trust steps run in the reconcile's one transaction, its new tables included, so a step after
    them that fails leaves the copy byte for byte unchanged. Mutation: a step committing (executescript)."""
    t = trusted
    pairs(t)
    copy = staged(t.tmp, t.station)
    if old_copy:
        before_owner_trust(copy)
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], t.owner['id'], retire=True)
    before = copy.read_bytes()

    def fails(*args):
        raise RuntimeError('the step after settling failed')

    monkeypatch.setattr(backups, '_unpair_named', fails)
    code, out, err = reconcile(capsys, '--db', copy, *(('--replaced', t.station.db_path) if compared else ()))
    assert code == 1 and 'nothing was changed' in err and 'RuntimeError' in err
    assert copy.read_bytes() == before


@pytest.mark.parametrize('damage', ['a table', 'its rows'])
def test_a_replaced_file_lacking_the_trust_fails_closed(trusted, capsys, damage):
    """owner_trust is append-only, so a replaced file without the table, or without the copy's trust, is the wrong file
    or a damaged one: a revocation in it could be lost too, so the trust is revoked now (reason `restored`) and tardis
    held. Without the table the file is treated as absent (COMPARED); without the rows the trust is named missing.
    Mutations: the owner trust columns left out of COMPARED; a trust missing there left live."""
    t = trusted
    tardis = pairs(t)
    copy = staged(t.tmp, t.station)
    with closing(sqlite3.connect(t.station.db_path)) as db:
        if damage == 'a table':
            db.execute('DROP TABLE retired_peers')
        else:
            db.execute('DROP TRIGGER owner_trust_no_delete')
            db.execute('DELETE FROM owner_trust')
        db.commit()
    out = against_live(capsys, t, copy)
    assert [row[:3] for row in revocations_in(copy)] == [(t.trust['grant_id'], 'restored', None)]
    assert held_in(copy, tardis['id'])
    how = 'revoked: no usable replaced file' if damage == 'a table' else 'revoked: missing from the replaced file'
    assert named(t.trust['grant_id'], 'Andy B', how) in trusts_line(out)
    assert ('treated as absent' in out) == (damage == 'a table')


def test_an_owner_held_by_the_restore_ends_its_trust(trusted, capsys):
    """Spec item 6 (N13): any hold of the owner writes a revocation. The replaced file holds Andy B with no revocation
    beside it (written by hand), _hold_like_replaced holds him in the copy, and settling revokes his trust (reason
    `owner held`) and holds tardis, before the copy goes live. Mutation: settle_owner_trust not run."""
    t = trusted
    tardis = pairs(t)
    copy = staged(t.tmp, t.station)
    with t.station.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES (?, ?)', (t.owner['id'], t.clock[0]))
    out = against_live(capsys, t, copy)
    assert [row[:3] for row in revocations_in(copy)] == [(t.trust['grant_id'], 'owner held', None)]
    assert held_in(copy, t.owner['id']) and held_in(copy, tardis['id'])
    assert named(t.trust['grant_id'], 'Andy B', 'revoked: its owner is held') in trusts_line(out)
    assert 'ships held as their owner trust ended (1)' in out
