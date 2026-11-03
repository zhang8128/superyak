"""Owner trust Task 5 (docs/superpowers/specs/2026-11-02-machine-trust-design.md, items 4a, 6 and 7): a station
restore never brings back a revoked trust, a retirement, or a paused trust. The fixtures are test_owner_trust's (B's
person Andy B, paired at the station with his code, a live 90-day trust for him, and the station's ship rio-grande to
act), the restore helpers test_restore's."""
from contextlib import closing
import sqlite3
import time

import pytest
from superyak_peer import backups
from superyak_peer.common import Problem
from superyak_peer.federation import RETIRED, Federation
from superyak_peer.identity import PeerIdentity, pairing_code
from test_owner_trust import (PASSWORD, PAUSED, b_ship, grant, machine, paired, pairs, queue, renew,  # noqa: F401 - fixtures
                              revoke, third_peer, trusted, utc_day)
from test_restore import docked, go_live, peer_rows, peer_station, reconcile, staged

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

def test_a_retirement_is_kept_from_a_replaced_file_lacking_another_trust_table(trusted, capsys):
    """The parked Task 5 item: a replaced file lacking trust_cap_refusals is treated as absent (every trust revoked), but
    its retired_peers rows are still copied and the peer unpaired, so a retirement is never silently lost, and the report
    no longer says retirements were not kept. Mutation: the retirements read only from a usable replaced file."""
    t = trusted
    tardis = pairs(t)
    copy = staged(t.tmp, t.station)
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], t.owner['id'], retire=True)
    with closing(sqlite3.connect(t.station.db_path)) as db:
        db.execute('DROP TABLE trust_cap_refusals')
        db.commit()
    out = against_live(capsys, t, copy)
    assert 'treated as absent' in out and 'peer retirements kept (1)' in out
    assert rows_in(copy, 'SELECT * FROM retired_peers') == [(t.owner['peer_id'], t.clock[0], t.admin['id'])]
    assert rows_in(copy, 'SELECT paired FROM peers WHERE peer_id=?', t.owner['peer_id']) == [(0,)]
    assert held_in(copy, tardis['id'])
    assert 'Peers retired since the copy were not kept' not in out


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
    assert backups.TRUST_RETIREMENTS_NOT_KEPT in out and backups.TRUSTS_RESTORED in out
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
    assert named(t.trust['grant_id'], 'Andy B', 'revoked: paused in the replaced file; ' + backups.PAUSE_LOST) in trusts_line(out)
    assert "its pairings since the copy are lost; if you didn't expect them, unpair that peer as retired before granting again" in out


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
    """A copy taken before this build, against a replaced file that has the trust tables, gains every owner trust
    table, trigger, index and view in the reconcile's own transaction (one statement at a time: executescript would
    commit it), skipping nothing, and a retirement since the copy is kept in it. Without a replaced file it gains none
    (the re-review's ruling: there is no trust, and the station's start makes them). Mutation: the tables not made
    with a replaced file (the reconcile fails)."""
    t = trusted
    copy = staged(t.tmp, t.station)
    before_owner_trust(copy)
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], t.owner['id'], retire=True)
    code, out, err = reconcile(capsys, '--db', copy, *(('--replaced', t.station.db_path) if compared else ()))
    assert code == 0, err
    assert not any(line.startswith('Skipped') for line in out.splitlines()), out
    if compared:
        assert trust_objects(copy) == trust_objects(t.station.db_path) != []
        assert rows_in(copy, 'SELECT peer_id FROM retired_peers') == [(t.owner['peer_id'],)] and trusts_line(out) == ''
    else:
        assert trust_objects(copy) == [] and backups.TRUST_RETIREMENTS_NOT_KEPT in out
    live = go_live(copy, t.tmp / 'live')
    assert trust_objects(live.db_path) == trust_objects(t.station.db_path)


@pytest.mark.parametrize('failing', ['_unpair_named', '_write_mark'])  # between the settles, and after the second
@pytest.mark.parametrize('compared', [True, False])
@pytest.mark.parametrize('old_copy', [False, True])
def test_a_failure_after_the_trust_steps_changes_no_byte(trusted, capsys, monkeypatch, compared, old_copy, failing):
    """Ruling 4: the owner trust steps run in the reconcile's one transaction, its new tables included, so a step after
    them that fails, between the two settles or after both, leaves the copy byte for byte unchanged. Mutation: a step
    committing (executescript)."""
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

    monkeypatch.setattr(backups, failing, fails)
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


def test_unpair_named_holds_an_owner_with_a_dated_revocation(trusted, capsys):
    """Spec item 6 (S10, N13), the coordinator's ruling on Task 5's C1: UNPAIR= naming the owner's peer holds every
    contact of it, the owner too, after the first settle has run, so settling runs again after it. The trust gets its
    revocation (reason `owner held`, dated by the reconcile), the report names it, and the copy, once live, pairs
    nothing. Mutation: the settle after _unpair_named left out (no revocation row, though the owner is held)."""
    t = trusted
    tardis = pairs(t)
    copy = staged(t.tmp, t.station)
    started = time.time()
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', t.station.db_path, '--unpair', t.owner['peer_id'])
    assert code == 0, err
    revoked = revocations_in(copy)
    assert [row[:3] for row in revoked] == [(t.trust['grant_id'], 'owner held', None)] and revoked[0][3] >= started
    assert held_in(copy, t.owner['id']) and held_in(copy, tardis['id'])
    assert named(t.trust['grant_id'], 'Andy B', 'revoked: its owner is held') in trusts_line(out)
    assert 'owner trusts revoked (1)' in out
    live = go_live(copy, t.tmp / 'live')
    with pytest.raises(Problem) as caught:
        Federation(live, endpoint='https://localhost:7436').pair_trusted(t.ship, *b_ship(t, 'serenity'))
    assert caught.value.status == 409


def paused_at_two(t):
    """Andy B's first trust revoked, a new one expecting 2 ships, and ship-a and ship-b paired under it: paused."""
    revoke(t)
    t.clock[0] += 60
    t.trust = grant((t.station, t.admin, t.owner, None), days=30, expect=2)
    return pairs(t, *b_ship(t, 'ship-a')), pairs(t, *b_ship(t, 'ship-b'))


UNCHANGED = 'paused, as in the replaced file: check its ships, then renew or revoke'


@pytest.mark.parametrize('expired', [False, True])
def test_a_trust_paused_in_both_files_stays_paused_and_is_named(trusted, capsys, expired):
    """The Task 5 review's ruling (spec item 4a, Restore): a trust paused before the copy, with nothing lost since, is
    paused in the copy too, so the restore revokes nothing and holds no ship (the natural end of "expect 2" after two
    machines must not cost a re-grant), and the report names it for the admin to check its ships; an expired one the
    same way. Once live, the copy still refuses the next pairing as paused. Mutation: a trust paused there revoked
    whatever the copy holds (the reviewer's probe)."""
    t = trusted
    ship_a, ship_b = paused_at_two(t)
    if expired:
        t.clock[0] = t.trust['until'] + 100
    copy = staged(t.tmp, t.station)
    out = against_live(capsys, t, copy)
    assert revocations_in(copy) == revocations_in(t.station.db_path) and len(revocations_in(copy)) == 1  # the first trust's
    assert not held_in(copy, ship_a['id']) and not held_in(copy, ship_b['id'])
    assert named(t.trust['grant_id'], 'Andy B', UNCHANGED) in trusts_line(out) and 'owner trusts revoked (0)' in out
    if not expired:
        live = go_live(copy, t.tmp / 'live')
        with pytest.raises(Problem) as caught:
            Federation(live, endpoint='https://localhost:7436').pair_trusted(t.ship, *b_ship(t, 'ship-c'))
        assert (caught.value.status, caught.value.message) == (429, PAUSED.format(2))


def test_a_trust_paused_there_under_a_renewal_the_copy_lacks_is_revoked(trusted, capsys):
    """The ruling's other half: the copy has the trust paused under its grant (2 of 2); since the copy it was renewed
    (expect 1) and ship-c paired, pausing it under the renewal. That window is lost with the copy and its notice has
    posted, so the trust is revoked (`paused at restore`), its ships held, and it is not named to renew again.
    Mutation: only the counts compared, not the window's row."""
    t = trusted
    ship_a, ship_b = paused_at_two(t)
    copy = staged(t.tmp, t.station)
    t.clock[0] += 60
    renew((t.station, t.admin), t.trust['grant_id'], days=30, expect=1)
    pairs(t, *b_ship(t, 'ship-c'))
    out = against_live(capsys, t, copy)
    assert revocations_in(copy)[-1][:3] == (t.trust['grant_id'], 'paused at restore', None)
    assert held_in(copy, ship_a['id']) and held_in(copy, ship_b['id'])
    line = trusts_line(out)
    assert named(t.trust['grant_id'], 'Andy B', 'revoked: paused in the replaced file; ' + backups.PAUSE_LOST) in line and 'grant it again' not in line


def test_a_grant_lost_with_the_copy_says_it_had_paused_there(trusted, capsys):
    """M1: a grant made since the copy that paused in the replaced file is lost with the copy, and the report says it
    had paused, so it isn't granted again unthinking. Mutation: the note left out."""
    t = trusted
    andy_c, c_ship = third_peer(t)
    copy = staged(t.tmp, t.station)
    t.clock[0] += 60
    lost = t.station.grant_owner_trust(t.admin['id'], andy_c['id'], days=30, expect=2, password=PASSWORD, source='127.0.0.1')
    for number in (1, 2):
        pairs(t, *c_ship(f'c-ship-{number}', f'c-{number}'))
    out = against_live(capsys, t, copy)
    how = 'granted since the copy, and the grant was lost: grant it again; it had paused there after 2 pairings, and ' + backups.PAUSE_LOST
    assert named(lost['grant_id'], 'Andy C', how) in trusts_line(out)


def test_refusals_at_the_cap_since_the_copy_are_named(trusted, capsys):
    """M2: a burst of refusals at the cap is a sign of a compromised host, and the copy's counts end where it was
    taken, so the report names each trust refused at the cap more often in the replaced file than here, day by day,
    and revokes nothing. A count the copy holds whole isn't named. Mutation: the cap refusals not compared."""
    t = trusted
    grant_id, day = t.trust['grant_id'], utc_day(t.clock[0])
    with t.station.transaction() as db:
        db.execute('INSERT INTO trust_cap_refusals VALUES (?, ?, 1)', (grant_id, day))
        db.execute("INSERT INTO trust_cap_refusals VALUES ('unchanged-grant', ?, 2)", (day,))
    copy = staged(t.tmp, t.station)
    with t.station.transaction() as db:  # since the copy: 1 more that day, and 2 the next
        db.execute('UPDATE trust_cap_refusals SET refused=refused+1 WHERE grant_id=? AND day=?', (grant_id, day))
        db.execute("INSERT INTO trust_cap_refusals VALUES (?, '2099-01-01', 2)", (grant_id,))
    out = against_live(capsys, t, copy)
    line = trusts_line(out)
    assert named(grant_id, 'Andy B', 'refused at the cap since the copy: 3') in line and 'unchan' not in line
    assert revocations_in(copy) == [] and 'owner trusts revoked (0)' in out


def test_a_retirement_of_a_peer_the_copy_lacks_is_kept(trusted, capsys):
    """M3: a peer paired and retired since the copy isn't in the copy at all; its retirement is kept even so, and once
    live, pair refuses that peer whatever code is typed. Mutation: retirements kept only for peers the copy has."""
    t = trusted
    copy = staged(t.tmp, t.station)
    andy_c, _ = third_peer(t)
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], andy_c['id'], retire=True)
    out = against_live(capsys, t, copy)
    assert rows_in(copy, 'SELECT 1 FROM peers WHERE peer_id=?', andy_c['peer_id']) == []
    assert rows_in(copy, 'SELECT peer_id FROM retired_peers') == [(andy_c['peer_id'],)] and 'peer retirements kept (1)' in out
    person_card = PeerIdentity.load_or_create(t.tmp / 'c').card('https://localhost:7437', {'id': t.owner['user_id'], 'name': 'Andy C'})
    live = go_live(copy, t.tmp / 'live')
    with pytest.raises(Problem) as caught:
        Federation(live, endpoint='https://localhost:7436').pair(t.admin['id'], person_card, code=pairing_code(person_card))
    assert (caught.value.status, caught.value.message) == (409, RETIRED)


def test_a_second_run_on_a_pair_from_before_owner_trust_still_compares(tmp_path, capsys):
    """The re-review's Important finding: the copy and the replaced file both from before owner trust. The first run
    makes no trust table in the copy, so runbook step 5's second run (UNPAIR=) still compares, and takes nothing back
    that a replaced file keeps: the docked ship's key works once live. Mutation: the tables made whatever either file
    has (the second run reads the replaced file as absent and revokes every owned ship's key)."""
    store, peers = peer_station(tmp_path)
    with store.transaction() as db:
        andy = db.execute("SELECT id FROM users WHERE username='andy'").fetchone()[0]
    _, key = docked(store, andy, 'serenity')
    copy = staged(tmp_path, store)
    for path in (store.db_path, copy):
        before_owner_trust(path)
    for extra in ((), ('--unpair', peers['cut'])):
        code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path, *extra)
        assert code == 0, err
        assert 'Compared with the replaced file.' in out.splitlines() and 'Ship keys revoked' not in out, out
    assert trust_objects(copy) == [] and peer_rows(copy)[0][peers['cut']] == 0
    assert go_live(copy, tmp_path / 'live').ship_for_key(key)['username'] == 'serenity'


def test_a_damaged_replaced_file_with_no_expect_fails_closed(trusted, capsys):
    """Re-review minor 2: a grant row whose expect is NULL (the table's CHECK forbids it, so only damage writes one),
    here a grant since the copy, reads as paused there rather than raising. Mutation: the NULL compared with its
    window's count (TypeError, the reconcile refused)."""
    t = trusted
    andy_c, _ = third_peer(t)
    copy = staged(t.tmp, t.station)
    with closing(sqlite3.connect(t.station.db_path)) as db:
        db.execute('PRAGMA ignore_check_constraints=ON')
        db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,expect) "
                   "VALUES ('damaged-grant','grant',?,?,?,?,?,NULL)",
                   (andy_c['peer_id'], andy_c['user_id'], t.clock[0] + 86400, t.admin['id'], t.clock[0]))
        db.commit()
    out = against_live(capsys, t, copy)
    how = 'granted since the copy, and the grant was lost: grant it again; it had paused there after 0 pairings, and ' + backups.PAUSE_LOST
    assert named('damaged-grant', 'Andy C', how) in trusts_line(out)
