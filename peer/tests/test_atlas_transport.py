"""North-star test 5's transport (docs/superpowers/specs/2026-11-22-claim-crossing-transport-design.md, revision 4 with
amendment 1): sourced publications and notices sent ship to ship as atlas.publication and atlas.notice, with every
issuer bound to the delivering peer. The peer imports no Atlas code, so these packages carry only the fields the peer
reads; Atlas's own validation runs on the receiving side, after `atlas-received`."""
import hashlib
import json

import pytest

from conftest import paired
from superyak_peer.common import Problem
from superyak_peer.identity import canonical, verify_envelope

ONE_MIB = 1024 * 1024


def uri(fed):
    return f'urn:superyak:peer:{fed.identity.peer_id}'


def rules(destination, *, actions=('read', 'link_overlap', 'retain'), publishers=None, effect='allow'):
    return [{'id': 'r1', 'effect': effect, 'actions': list(actions), 'publishers': publishers or [destination],
             'audiences': ['self'], 'contexts': ['urn:x:context'], 'domains': ['research'], 'purposes': ['research'],
             'profiles': ['urn:superyak:profile:atlas-sourced'],
             'claimMediaTypes': ['application/vnd.superyak.atlas-sourced-claim+json']}]


def package(issuer, destination, *, carried=(), policy_rules=None, attestations=None, pad=0):
    """The fields of a sourced publication the transport reads (spec T2, T3), and nothing Atlas would need."""
    def artifact(kind, **extra):
        value = {'kind': kind, 'issuer': issuer, 'id': f'{issuer}:{kind}', **extra}
        if attestations is not None:
            value['attestations'] = attestations
        return value
    return {'format': 'atlas-sourced-publication', 'version': 1,
            'descriptor': artifact('LighthouseDescriptor'),
            'snapshot': artifact('Snapshot', payload={'pad': 'x' * pad}),
            'policy': artifact('ConnectionPolicy', payload={'rules': policy_rules if policy_rules is not None
                                                             else rules(destination)}),
            'claims': [artifact('Claim')],
            'carried': [{'claim': {'kind': 'Claim', 'issuer': c}, 'snapshot': {'kind': 'Snapshot', 'issuer': s}}
                        for c, s in carried]}


@pytest.fixture
def atlas_peers(lessons_peers):
    """lessons_peers, with amendment 1's one pairing: rio-grande's card typed into Tardis's peer."""
    pi, pi_fed, pi_ids = lessons_peers['peers']['pi']
    tardis, tardis_fed, t_ids = lessons_peers['peers']['tardis']
    contact_rio = paired(tardis_fed, t_ids['andy'], pi_fed.card(pi_ids['rio-grande']))['id']
    t_ids['rio-contact'] = contact_rio
    return lessons_peers


def parts(net):
    (pi, pi_fed, pi_ids), (tardis, tardis_fed, t_ids) = net['peers']['pi'], net['peers']['tardis']
    return pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids


def received(store, ship):
    with store.reading() as db:
        return [dict(r) for r in db.execute('SELECT * FROM atlas_received WHERE recipient=? ORDER BY received_at', (ship,))]


# --- 1. send and receive ---------------------------------------------------------------------------------------------

def test_a_publication_crosses_from_the_pi_to_tardis_with_who_delivered_it(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    sent = package(uri(pi_fed), uri(tardis_fed))
    queued = pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', sent)
    assert queued['state'] == 'pending'
    assert atlas_peers['deliver']('pi', 'tardis')['delivered'] >= 1
    [row] = received(tardis, t_ids['tardis'])
    assert row['origin'] == pi_fed.identity.peer_id and row['actor'] == pi_ids['rio-grande']
    assert row['kind'] == 'publication'
    envelope = json.loads(row['envelope'])
    assert verify_envelope(canonical(envelope), pi_fed.card(pi_ids['rio-grande']), tardis_fed.identity.peer_id)
    assert canonical(envelope['payload']['package']) == canonical(sent)
    assert row['payload_digest'] == hashlib.sha256(canonical({'package': sent})).hexdigest()


def test_and_from_tardis_to_the_pi(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    sent = package(uri(tardis_fed), uri(pi_fed))
    tardis.atlas_send(t_ids['tardis'], t_ids['rio-contact'], 'publication', sent)
    atlas_peers['deliver']('tardis', 'pi')
    [row] = received(pi, pi_ids['rio-grande'])
    assert row['origin'] == tardis_fed.identity.peer_id and row['actor'] == t_ids['tardis']


def test_without_rio_grande_as_a_contact_tardis_refuses_what_it_sends_as_amendment_1_says(lessons_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(lessons_peers)
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', package(uri(pi_fed), uri(tardis_fed)))
    lessons_peers['deliver']('pi', 'tardis')
    assert received(tardis, t_ids['tardis']) == []
    with pi.reading() as db:
        row = db.execute("SELECT status, last_error FROM outbox WHERE action='atlas.publication'").fetchone()
    assert (row['status'], row['last_error']) == ('refused', '403 Unknown remote participant')


# --- 2. the receiver's refusals (T3) --------------------------------------------------------------------------------

def envelope_from_pi(net, payload, *, action='atlas.publication', recipient=None, event_id='e' + 'a' * 31):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(net)
    return canonical(pi_fed.identity.envelope(
        destination=tardis_fed.identity.peer_id, actor=pi_ids['rio-grande'], resource_id='r' * 64, revision=1,
        action=action, recipients=[recipient or t_ids['tardis']], payload=payload, event_id=event_id))


def refused_at_tardis(net, payload, words, **kw):
    tardis_fed = net['peers']['tardis'][1]
    with pytest.raises(Problem) as caught:
        tardis_fed.receive(envelope_from_pi(net, payload, **kw))
    assert (caught.value.status, caught.value.message) == (400, words)
    assert received(net['peers']['tardis'][0], net['peers']['tardis'][2]['tardis']) == []


def test_tardis_refuses_a_publication_issued_by_anyone_but_its_sender(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(tardis_fed), uri(tardis_fed))},
                      "A publication's artifacts must all be issued by the peer that delivered it")


def test_tardis_refuses_a_carried_entry_from_a_third_issuer(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    third = 'urn:superyak:peer:' + 'c' * 64
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed), carried=[(third, third)])},
                      'A carried claim must be the receiver\'s own or the sender\'s')


def test_tardis_refuses_a_carried_entry_whose_claim_and_snapshot_issuers_differ(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed),
                                                       carried=[(uri(pi_fed), uri(tardis_fed))])},
                      "A carried claim's issuer isn't its snapshot's issuer")


def test_tardis_takes_a_carried_entry_that_is_its_own_or_the_senders(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    payload = {'package': package(uri(pi_fed), uri(tardis_fed),
                                  carried=[(uri(tardis_fed), uri(tardis_fed)), (uri(pi_fed), uri(pi_fed))])}
    assert tardis_fed.receive(envelope_from_pi(atlas_peers, payload))['ok']
    assert len(received(tardis, t_ids['tardis'])) == 1


def test_tardis_refuses_an_artifact_with_attestations(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed), attestations=[{'by': 'x'}])},
                      'This version takes no attestations')


def test_tardis_refuses_an_atlas_payload_for_a_person(atlas_peers):
    _, pi_fed, _, _, tardis_fed, t_ids = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed))},
                      'Atlas publications go only to a ship', recipient=t_ids['andy'])


def test_tardis_refuses_a_payload_over_one_mib(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed), pad=ONE_MIB)},
                      'An atlas payload is at most 1 MiB')


def test_tardis_refuses_a_payload_with_other_keys(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_tardis(atlas_peers, {'package': package(uri(pi_fed), uri(tardis_fed)), 'extra': 1},
                      'Invalid atlas payload')


def test_a_notice_must_be_issued_by_its_sender(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    notice = {'kind': 'Claim', 'issuer': uri(tardis_fed), 'id': 'n1'}
    refused_at_tardis(atlas_peers, {'notice': notice}, "A notice must be issued by the peer that delivered it",
                      action='atlas.notice')


def test_the_same_package_to_one_ship_is_kept_once(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    payload = {'package': package(uri(pi_fed), uri(tardis_fed))}
    assert tardis_fed.receive(envelope_from_pi(atlas_peers, payload)) == {'ok': True, 'duplicate': False}
    again = envelope_from_pi(atlas_peers, payload, event_id='e' + 'b' * 31)  # a second send, signed afresh
    assert tardis_fed.receive(again) == {'ok': True, 'duplicate': True}
    assert len(received(tardis, t_ids['tardis'])) == 1


# --- 3. the sender's refusals (T2, T3) ------------------------------------------------------------------------------

def refused_at_pi(net, words, *, ship=None, contact=None, kind='publication', payload=None):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(net)
    with pytest.raises(Problem) as caught:
        pi.atlas_send(ship or pi_ids['rio-grande'], contact or pi_ids['contact'], kind,
                      payload if payload is not None else package(uri(pi_fed), uri(tardis_fed)))
    assert caught.value.message == words
    with pi.reading() as db:
        assert db.execute("SELECT COUNT(*) FROM outbox WHERE action LIKE 'atlas.%'").fetchone()[0] == 0


def test_the_pi_refuses_to_send_a_package_it_did_not_issue(atlas_peers):
    _, _, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_pi(atlas_peers, 'A package you send must be issued by this peer',
                  payload=package(uri(tardis_fed), uri(tardis_fed)))


def test_the_pi_refuses_a_policy_with_no_exact_retain_for_the_destination(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_pi(atlas_peers, "The package's policy must allow the destination to retain it, by its exact name",
                  payload=package(uri(pi_fed), uri(tardis_fed), policy_rules=rules(uri(tardis_fed), actions=['read'])))


@pytest.mark.parametrize('change', [{'actions': ['*']}, {'actions': ['re*']}, {'publishers': ['urn:superyak:peer:*']},
                                    {'contexts': ['*']}])
def test_the_pi_refuses_a_policy_with_a_wildcard_anywhere(atlas_peers, change):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    policy = rules(uri(tardis_fed)) + [{**rules(uri(tardis_fed))[0], 'id': 'r2', **change}]
    refused_at_pi(atlas_peers, "The package's policy may hold no wildcard",
                  payload=package(uri(pi_fed), uri(tardis_fed), policy_rules=policy))


def test_the_pi_refuses_a_policy_that_allows_reshare(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_pi(atlas_peers, "The package's policy may not allow reshare",
                  payload=package(uri(pi_fed), uri(tardis_fed),
                                  policy_rules=rules(uri(tardis_fed), actions=['read', 'retain', 'reshare'])))


def test_the_pi_refuses_a_carried_entry_from_a_third_issuer(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    third = 'urn:superyak:peer:' + 'c' * 64
    refused_at_pi(atlas_peers, "A carried claim must be this peer's own or the destination's",
                  payload=package(uri(pi_fed), uri(tardis_fed), carried=[(third, third)]))


def test_the_pi_refuses_a_contact_on_a_peer_the_lessons_chain_does_not_list(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    with pi.transaction() as db:
        db.execute('DELETE FROM lessons_peers')
    refused_at_pi(atlas_peers, "That peer isn't listed for your lessons room: Atlas publications go only to peers "
                               "listed there")


def test_tardis_may_send_to_the_origin_of_its_recorded_lessons_room(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    with tardis.reading() as db:
        assert db.execute('SELECT COUNT(*) FROM lessons_peers').fetchone()[0] == 0  # as on the real tardis-peer
    assert tardis.atlas_send(t_ids['tardis'], t_ids['rio-contact'], 'publication',
                             package(uri(tardis_fed), uri(pi_fed)))['state'] == 'pending'


def test_the_pi_refuses_a_contact_without_a_current_typed_code(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    with pi.transaction() as db:
        db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (pi_ids['contact'],))
    refused_at_pi(atlas_peers, 'That contact has no current typed code: Atlas publications need one')


def test_the_pi_refuses_a_person_sender_and_an_ownerless_ship(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    refused_at_pi(atlas_peers, 'Only a ship sends Atlas publications', ship=pi_ids['andy'])
    with pi.transaction() as db:
        db.execute('UPDATE users SET owner_id=NULL WHERE id=?', (pi_ids['rio-grande'],))
    refused_at_pi(atlas_peers, 'A ship with no owner who is an admin here sends no Atlas publications')


def test_the_pi_refuses_a_second_send_of_one_digest_to_one_contact(atlas_peers):
    pi, pi_fed, pi_ids, tardis, tardis_fed, t_ids = parts(atlas_peers)
    sent = package(uri(pi_fed), uri(tardis_fed))
    pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', sent)
    with pytest.raises(Problem) as caught:
        pi.atlas_send(pi_ids['rio-grande'], pi_ids['contact'], 'publication', sent)
    assert caught.value.message == 'Already sent to that contact'


def test_the_pi_refuses_a_payload_over_one_mib_before_queueing(atlas_peers):
    _, pi_fed, _, _, tardis_fed, _ = parts(atlas_peers)
    refused_at_pi(atlas_peers, 'An atlas payload is at most 1 MiB',
                  payload=package(uri(pi_fed), uri(tardis_fed), pad=ONE_MIB))
