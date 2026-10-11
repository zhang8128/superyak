import re
import json

import pytest
from superyak_peer.common import Problem

@pytest.fixture
def two_peers(tmp_path):
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    peers = []
    for name in ('alice', 'bob'):
        store = Store(tmp_path / name)
        user = store.create_user(name, name.title(), 'a-long-password', is_admin=True)
        fed = Federation(store, endpoint='https://localhost:7435')
        peers.append((store, user['id'], fed))
    a, b = peers
    ca = a[2].pair(a[1], b[2].card(b[1]))
    cb = b[2].pair(b[1], a[2].card(a[1]))
    return a, b, ca, cb


def deliver(a, b):
    return a[2].sync_once(send=lambda card, prepare: b[2].receive(prepare()))


def test_share_withdraw_replay_and_namespace(two_peers):
    a, b, ca, cb = two_peers
    layer = a[0].create_layer(a[1], {'body': 'shared', 'audience_users': [ca['id']]})
    a[0].activate_layer(a[1], layer['id'], 1)
    assert deliver(a, b)['delivered'] == 1
    shared = b[0].shared_layers(b[1])
    assert shared[0]['body'] == 'shared'
    assert shared[0]['id'] == a[2].identity.peer_id + ':' + layer['id']
    assert 'audience_users' not in shared[0]
    assert len(b[0].accounts(b[1])) == 1
    a[0].withdraw_layer(a[1], layer['id'])
    deliver(a, b)
    assert b[0].shared_layers(b[1]) == []
    with a[0].transaction() as db:
        old = db.execute("SELECT envelope FROM outbox WHERE action='layer.release'").fetchone()[0]
    assert b[2].receive(old)['duplicate'] is True
    assert b[0].shared_layers(b[1]) == []


def test_queued_share_cannot_survive_withdrawal(two_peers):
    a, b, ca, cb = two_peers
    layer = a[0].create_layer(a[1], {'body': 'private after withdrawal', 'audience_users': [ca['id']]})
    a[0].activate_layer(a[1], layer['id'], 1)
    a[2].collect()
    a[0].withdraw_layer(a[1], layer['id'])
    deliver(a, b)
    assert not b[0].shared_layers(b[1])


def test_unknown_peer_recipient_replay_collision_and_unpair(two_peers):
    a, b, ca, cb = two_peers
    def event(**kw):
        args = dict(destination=b[2].identity.peer_id, actor=a[1], resource_id='same-local-id', revision=1,
                    action='layer.release', recipients=[b[1]], payload={'title': 'hi', 'body': 'one', 'attachment_ids': []})
        args.update(kw)
        return a[2].identity.envelope(**args)
    with pytest.raises(Problem):
        b[2].receive(event(recipients=['missing']))
    first = event()
    b[2].receive(first)
    assert b[2].receive(first)['duplicate']
    with pytest.raises(Problem):
        b[2].receive(event(event_id=first['event_id'], payload={'title':'hi','body':'two','attachment_ids':[]}))
    b[2].unpair(b[1], cb['id'])
    with pytest.raises(Problem):
        b[2].receive(event())
    assert b[0].shared_layers(b[1]) == []


def test_remote_room_reply_and_removal(two_peers):
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'Across peers', [ca['id']])
    a[0].send_message(a[1], room['id'], 'one', 'hello')
    deliver(a, b)
    remote = b[0].list_rooms(b[1])[0]
    assert b[0].get_room(b[1], remote['id'])['messages'][0]['body'] == 'hello'
    b[0].send_message(b[1], remote['id'], 'reply', 'hello back')
    deliver(b, a)
    assert len(a[0].get_room(a[1], room['id'])['messages']) == 2
    a[0].send_message(a[1], room['id'], 'queued', 'must not arrive')
    a[2].collect()
    a[0].remove_participant(a[1], room['id'], ca['id'])
    deliver(a, b)
    assert b[0].list_rooms(b[1]) == []
    with pytest.raises(Problem):
        b[0].send_message(b[1], remote['id'], 'later', 'bad')


@pytest.mark.parametrize('name,media_type,content', [
    ('note.txt', 'text/plain', b'attachment'),
    ('dataset.csv', 'text/csv', b'name,value\nAlex,3\n'),
    ('dataset.json', 'application/json', b'{"value": 3}\n'),
])
def test_attachment_delivery_and_withdrawal(two_peers, name, media_type, content):
    import base64
    a,b,ca,cb=two_peers
    file=a[0].upload_file(a[1],name,media_type,base64.b64encode(content).decode())
    layer=a[0].create_layer(a[1],{'body':'attached','audience_users':[ca['id']], 'attachment_ids':[file['id']]})
    a[0].activate_layer(a[1],layer['id'],1)
    deliver(a,b)
    remote=b[0].shared_layers(b[1])[0]['id']
    assert b[0].download_file(b[1],file['id'],layer_id=remote)['content']==content
    with pytest.raises(Problem):
        b[0].download_file(b[1],file['id'])
    with pytest.raises(Problem):
        b[0].create_layer(b[1],{'attachment_ids':[file['id']]})
    a[0].withdraw_layer(a[1],layer['id'])
    deliver(a,b)
    with pytest.raises(Problem):
        b[0].download_file(b[1],file['id'],layer_id=remote)


def test_unknown_peer_and_unauthorized_room_sender(two_peers,tmp_path):
    from superyak_peer.identity import PeerIdentity
    a,b,ca,cb=two_peers
    room=a[0].create_room(a[1],'local room',[])
    event=b[2].identity.envelope(destination=a[2].identity.peer_id, actor=b[1],resource_id=room['id'],revision=1,action='room.reply',recipients=[a[1]],payload={'body':'intrusion','client_message_id':'x'})
    with pytest.raises(Problem):
        a[2].receive(event)
    unknown=PeerIdentity.load_or_create(tmp_path/'unknown')
    event=unknown.envelope(destination=a[2].identity.peer_id,actor='unknown',resource_id='r',revision=1,action='layer.withdraw',recipients=[a[1]],payload={})
    with pytest.raises(Problem):
        a[2].receive(event)
    assert not a[0].get_room(a[1],room['id'])['messages']


def test_stale_new_event_cannot_restore_withdrawn_body(two_peers):
    a,b,ca,cb=two_peers
    args=dict(destination=b[2].identity.peer_id,actor=a[1],resource_id='r',recipients=[b[1]])
    b[2].receive(a[2].identity.envelope(**args,revision=2,action='layer.withdraw',payload={}))
    b[2].receive(a[2].identity.envelope(**args,revision=1,action='layer.release',payload={'title':'stale','body':'hidden','attachment_ids':[]}))
    assert not b[0].shared_layers(b[1])
    with b[0].transaction() as db:
        assert db.execute('SELECT payload FROM inbox').fetchone()[0] is None
        assert db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]==2


def test_remote_ids_cannot_shadow_local_layer(two_peers):
    a,b,ca,cb=two_peers
    layer=b[0].create_layer(b[1],{'body':'local private'})
    event=a[2].identity.envelope(destination=b[2].identity.peer_id,actor=a[1],resource_id=layer['id'],revision=1,action='layer.release',recipients=[b[1]],payload={'title':'remote','body':'remote selected','attachment_ids':[]})
    b[2].receive(event)
    assert b[0].get_layer(b[1],layer['id'])['body']=='local private'
    assert b[0].shared_layers(b[1])[0]['body']=='remote selected'


def test_pair_cannot_replace_known_endpoint_or_gain_login(two_peers):
    a,b,ca,cb=two_peers
    with pytest.raises(Problem):
        a[2].pair(a[1],{**b[2].card(b[1]),'endpoint':'https://evil.example'})
    with pytest.raises(Problem):
        a[0].login('bob','a-long-password','local')
    assert a[0].contacts(a[1])[0]['remote'] is True


def test_roster_cannot_add_to_existing_room(two_peers):
    a,b,ca,cb=two_peers
    room=a[0].create_room(a[1],'private',[ca['id']])
    deliver(a,b)
    with a[0].transaction() as db:
        original=__import__('json').loads(db.execute('SELECT envelope FROM outbox').fetchone()[0])
    payload=original['payload']
    payload['members'].append({'peer':a[2].identity.peer_id,'id':'outsider'})
    payload['member_ids'].append(a[2].identity.peer_id+':outsider')
    event=a[2].identity.envelope(destination=b[2].identity.peer_id,actor=a[1],resource_id=room['id'],revision=2,action='room.roster',recipients=[b[1]],payload=payload)
    with pytest.raises(Problem):
        b[2].receive(event)


def test_revoke_preserves_private_draft_and_delivers_tombstone(two_peers):
    a,b,ca,cb=two_peers
    layer=a[0].create_layer(a[1],{'body':'released','audience_users':[ca['id']]})
    a[0].activate_layer(a[1],layer['id'],1)
    deliver(a,b)
    a[0].save_layer(a[1],layer['id'],{'version':1,'body':'never published'})
    a[0].revoke_layer_routes(a[1],layer['id'],{'revision':1,'user_ids':[ca['id']]})
    deliver(a,b)
    assert not b[0].shared_layers(b[1])
    assert a[0].get_layer(a[1],layer['id'])['body']=='never published'


def test_malformed_authenticated_room_is_public_safe(two_peers):
    a,b,ca,cb=two_peers
    event=a[2].identity.envelope(destination=b[2].identity.peer_id,actor=a[1],resource_id='r',revision=1,action='room.message',recipients=[b[1]],payload={'title':'bad','members':[{'peer':{},'id':[]} ]})
    with pytest.raises(Problem):
        b[2].receive(event)


def test_room_activity_includes_remote_reply(two_peers):
    a,b,ca,cb=two_peers
    now=[1000.0]
    a[0].clock=lambda:now[0]
    room=a[0].create_room(a[1],'reply activity',[ca['id']])
    deliver(a,b)
    remote=b[0].list_rooms(b[1])[0]
    now[0]=2000.0
    b[0].send_message(b[1],remote['id'],'new','reply')
    deliver(b,a)
    assert a[0].list_rooms(a[1])[0]['last_activity']==2000.0


def test_remote_reply_remains_visible_offline_without_duplicate_echo(two_peers):
    a,b,ca,cb=two_peers
    room=a[0].create_room(a[1],'durable replies',[ca['id']])
    deliver(a,b)
    remote=b[0].list_rooms(b[1])[0]['id']
    message=b[0].send_message(b[1],remote,'offline','remember this')
    assert b[0].get_room(b[1],remote)['messages'][0]['body']=='remember this'
    assert b[0].get_room(b[1],remote)['messages'][0]['state']=='pending'
    deliver(b,a)
    deliver(a,b)
    messages=b[0].get_room(b[1],remote)['messages']
    assert len(messages)==1
    assert messages[0]['body']=='remember this'


def test_multiple_imported_participants_keep_their_own_card_labels(two_peers):
    a,b,ca,cb=two_peers
    second=b[0].create_user('second','Second person','long-password')['id']
    contact=a[2].pair(a[1],b[2].card(second))
    connections={c['id']:c for c in a[2].connections(a[1])}
    assert connections[contact['id']]['card']['participant']['id']==second
    b[0].rename_user(second,'Corrected name')
    again=a[2].pair(a[1],b[2].card(second))
    assert again['id']==contact['id']
    assert again['name']=='Corrected name'


def test_remote_attachment_aggregate_limit_does_not_change_draft(two_peers):
    import base64
    a,b,ca,cb=two_peers
    data=base64.b64encode(b'x'*(3*1024*1024)).decode()
    first=a[0].upload_file(a[1],'one.txt','text/plain',data)
    second=a[0].upload_file(a[1],'two.txt','text/plain',data)
    layer=a[0].create_layer(a[1],{'body':'local','attachment_ids':[first['id'],second['id']]})
    with pytest.raises(Problem,match='exceed 4 MiB'):
        a[0].save_layer(a[1],layer['id'],{'version':1,'audience_users':[ca['id']]})
    assert a[0].get_layer(a[1],layer['id'])['audience_users']==[]
    assert a[0].get_layer(a[1],layer['id'])['version']==1


@pytest.mark.parametrize('local_kind',['layer','room'])
def test_remote_reply_status_and_retry_ignore_colliding_local_layer(two_peers,local_kind):
    a,b,ca,cb=two_peers
    carol=b[0].create_user('carol','Carol','long-password')['id']
    layer=b[0].create_layer(carol,{'body':'unrelated local layer'}) if local_kind=='layer' else b[0].create_room(carol,'Unrelated local room')
    # The remote room owns its origin namespace, even if its ID matches a local layer.
    roster={'title':'Bob only','owner_id':a[2].identity.peer_id+':'+a[1],
            'members':[{'peer':a[2].identity.peer_id,'id':a[1]}, {'peer':b[2].identity.peer_id,'id':b[1]}],
            'linked_room_id':None,'created':1,'last_activity':1}
    roster['member_ids']=[m['peer']+':'+m['id'] for m in roster['members']]
    b[2].receive(a[2].identity.envelope(destination=b[2].identity.peer_id,actor=a[1],resource_id=layer['id'],revision=1,action='room.roster',recipients=[b[1]],payload=roster))
    b[0].send_message(b[1],a[2].identity.peer_id+':'+layer['id'],'reply','Bob private reply')
    b[2].collect()
    with b[0].transaction() as db:
        assert [r[0] for r in db.execute('SELECT action FROM outbox')]==['room.reply']
    key=b[2].status(b[1])[0]['id']
    with b[0].transaction() as db:
        db.execute("UPDATE outbox SET status='failed' WHERE id=?",(key,))
    assert b[2].status(carol)==[]
    with pytest.raises(Problem) as denied:
        b[2].retry(carol,key)
    assert denied.value.status==404
    assert b[2].status(b[1])[0]['status']=='failed'
    b[2].retry(b[1],key)
    assert b[2].status(b[1])[0]['status']=='pending'


def test_local_nonowner_message_author_controls_own_delivery(two_peers):
    a,b,ca,cb=two_peers
    carol=a[0].create_user('carol','Carol','long-password')['id']
    room=a[0].create_room(a[1],'Shared room',[carol,ca['id']])
    message=a[0].send_message(carol,room['id'],'carol-message','Carol authored this')
    a[2].collect()
    authored=a[2].status(carol)
    assert len(authored)==1 and authored[0]['action']=='room.message'
    assert authored[0]['message_id']==message['id']
    assert authored[0]['client_message_id']=='carol-message'
    assert 'body' not in authored[0]
    assert [r['action'] for r in a[2].status(a[1])]==['room.roster']
    with a[0].transaction() as db:
        db.execute("UPDATE outbox SET status='failed' WHERE id=?",(authored[0]['id'],))
    with pytest.raises(Problem):
        a[2].retry(a[1],authored[0]['id'])
    a[2].retry(carol,authored[0]['id'])
    assert a[2].status(carol)[0]['status']=='pending'
    deliver(a,b)
    remote=b[0].list_rooms(b[1])[0]['id']
    b[0].send_message(b[1],remote,'remote-reply','Remote original author')
    deliver(b,a)
    a[2].collect()
    # Origin distribution of a remote-authored reply is controlled by local room owner.
    owner_actions=[r['action'] for r in a[2].status(a[1])]
    assert owner_actions==['room.roster','room.message']
    assert len(a[2].status(carol))==1


@pytest.mark.parametrize('prior_status',['pending','failed'])
def test_received_room_withdrawal_cancels_reply_atomically(two_peers,prior_status):
    a,b,ca,cb=two_peers
    room=a[0].create_room(a[1],'Revoked reply',[ca['id']])
    deliver(a,b)
    remote=b[0].list_rooms(b[1])[0]['id']
    b[0].send_message(b[1],remote,'queued','Never send after removal')
    key=b[2].status(b[1])[0]['id']
    with b[0].transaction() as db:
        db.execute('UPDATE outbox SET status=? WHERE id=?',(prior_status,key))
    a[0].remove_participant(a[1],room['id'],ca['id'])
    deliver(a,b)
    assert b[2].status(b[1])[0]['status']=='withdrawn'
    with pytest.raises(Problem) as denied:
        b[2].retry(b[1],key)
    assert denied.value.status==409
    def must_not_send(card,prepare):
        pytest.fail('Canceled reply reached delivery')
    assert b[2].sync_once(send=must_not_send)['pending']==0
    from superyak_peer.federation import Federation,Obsolete
    from superyak_peer.db import Store
    restarted=Federation(Store(b[0].data_dir),endpoint=b[2].endpoint)
    assert restarted.status(b[1])[0]['status']=='withdrawn'
    assert restarted.sync_once(send=must_not_send)['pending']==0
    with pytest.raises(Obsolete):
        restarted._prepare(key)
    assert not a[0].get_room(a[1],room['id'])['messages']


def test_withdrawal_during_reply_ack_cannot_restore_canceled_status(two_peers):
    a,b,ca,cb=two_peers
    room=a[0].create_room(a[1],'In flight reply',[ca['id']])
    deliver(a,b)
    remote=b[0].list_rooms(b[1])[0]['id']
    b[0].send_message(b[1],remote,'in-flight','Already transmitted')
    def acknowledge_after_removal(card,prepare):
        acknowledged=a[2].receive(prepare())
        a[0].remove_participant(a[1],room['id'],ca['id'])
        deliver(a,b)
        return acknowledged
    result=b[2].sync_once(send=acknowledge_after_removal)
    assert result['withdrawn']==1 and result['pending']==0
    assert b[2].status(b[1])[0]['status']=='withdrawn'


@pytest.mark.parametrize('current_status',['failed','delivered'])
def test_duplicate_remote_send_reports_current_delivery_state(two_peers,current_status):
    a,b,ca,cb=two_peers
    room=a[0].create_room(a[1],'Idempotent send',[ca['id']])
    deliver(a,b)
    remote=b[0].list_rooms(b[1])[0]['id']
    original=b[0].send_message(b[1],remote,'same','Same body')
    delivery=b[2].status(b[1])[0]
    assert delivery['message_id']==original['id'] and delivery['client_message_id']=='same'
    assert 'body' not in delivery
    key=delivery['id']
    with b[0].transaction() as db:
        db.execute('UPDATE outbox SET status=? WHERE id=?',(current_status,key))
    repeated=b[0].send_message(b[1],remote,'same','Same body')
    assert repeated=={**original,'state':current_status}
    with pytest.raises(Problem):
        b[0].send_message(b[1],remote,'same','Changed body')


def test_status_collects_without_delivery_and_correlates_effective_revocation(two_peers):
    a, b, ca, cb = two_peers
    layer = a[0].create_layer(a[1], {'title':'Selected update', 'audience_users':[ca['id']]})
    a[0].activate_layer(a[1], layer['id'], 1)
    room = a[0].create_room(a[1], 'Selected room', [ca['id']])
    rows = a[2].status(a[1])
    assert len(rows) == 2
    assert {r['resource_title'] for r in rows} == {'Selected update','Selected room'}
    assert all(r['contact_name'] == 'Bob' and r['status'] == 'pending' for r in rows)
    assert b[0].shared_layers(b[1]) == []
    deliver(a,b)
    a[0].withdraw_layer(a[1], layer['id'])
    a[0].remove_participant(a[1], room['id'], ca['id'])
    pending = [r for r in a[2].status(a[1]) if r['status'] == 'pending']
    assert {r['action'] for r in pending} == {'layer.withdraw','room.withdraw'}
    assert b[0].shared_layers(b[1]) and b[0].list_rooms(b[1])
    assert a[2].status(a[0].create_user('other','Other','long-password')['id']) == []
    deliver(a,b)
    rows = a[2].status(a[1])
    assert all(r['status'] == 'delivered' for r in rows if r['action'].endswith('withdraw'))
    assert b[0].shared_layers(b[1]) == [] and b[0].list_rooms(b[1]) == []


def test_normal_sync_get_exposes_pending_without_network(env, tmp_path):
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    app, clients, users, _ = env
    remote = Store(tmp_path / 'status-remote')
    other = remote.create_user('remote','Remote recipient','long-password')
    fed = Federation(remote, endpoint='https://localhost:7435')
    contact = app.state.federation.pair(users[2]['id'], fed.card(other['id']))
    layer = clients[0].post('/api/layers', json={'title':'API queued', 'audience_users':[contact['id']]}).json()
    clients[0].post('/api/layers/' + layer['id'] + '/activate', json={'version':1})
    response = clients[0].get('/api/sync').json()
    assert response['enabled'] is False
    assert len(response['deliveries']) == 1
    assert response['deliveries'][0]['status'] == 'pending'
    assert clients[2].get('/api/sync').json()['deliveries'] == []


def test_a_received_room_has_no_brief_and_takes_none(two_peers):
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'Across peers', [ca['id']])
    a[0].save_brief(a[1], room['id'], 'Only for this station.', 0)
    deliver(a, b)
    remote = b[0].list_rooms(b[1])[0]['id']
    assert ':' in remote
    got = b[0].get_room(b[1], remote)
    assert got['brief'] is None and got['brief_revision'] == 0
    with pytest.raises(Problem) as refused:
        b[0].save_brief(b[1], remote, 'Mine.', 0)
    assert refused.value.status == 404
    assert a[0].get_room(a[1], room['id'])['brief']['body'] == 'Only for this station.'


def test_the_brief_event_names_no_text_and_never_leaves_the_station(two_peers):
    """Spec Testing 3, and review focus: a brief carried into a room with a paired member never reaches that peer."""
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'City of AI', [])
    a[0].save_brief(a[1], room['id'], 'Private to this station: D1-D9.', 0)
    newer = a[0].add_participants(a[1], room['id'], [ca['id']], 1)
    a[0].save_brief(a[1], newer['id'], 'Still private: D1-D9 and more.', 1)
    a[0].send_message(a[1], newer['id'], 'one', 'hello across')
    assert deliver(a, b)['delivered'] >= 1
    with a[0].transaction() as db:
        events = [dict(r) for r in db.execute("SELECT * FROM events WHERE kind='chat.brief' ORDER BY id")]
        rows = [dict(r) for r in db.execute('SELECT event_seq, envelope FROM outbox')]
    assert [(e['resource_id'], e['resource_version']) for e in events] == [(room['id'], 1), (newer['id'], 1), (newer['id'], 2)]
    assert [json.loads(e['payload']) for e in events] == [
        {'author_id': a[1], 'revision': 1}, {'author_id': a[1], 'revision': 1, 'carried_from': room['id']},
        {'author_id': a[1], 'revision': 2}]
    assert not any('D1-D9' in e['payload'] for e in events)
    assert rows and not {r['event_seq'] for r in rows} & {e['id'] for e in events}
    assert not any('D1-D9' in (r['envelope'] or '') for r in rows)
    remote = b[0].list_rooms(b[1])[0]
    assert 'brief' not in remote
    shown = b[0].get_room(b[1], remote['id'])
    assert shown['brief'] is None and [m['body'] for m in shown['messages']] == ['hello across']


def test_a_brief_a_paired_peer_sends_is_never_shown(two_peers):
    """Review focus: a received room's snapshot comes from the other station, which could put a brief in it."""
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'Across peers', [ca['id']])
    with a[0].transaction() as db:
        snapshot = a[2]._room_snapshot(db, db.execute('SELECT * FROM rooms WHERE id=?', (room['id'],)).fetchone())
    forged = a[2].identity.envelope(destination=b[2].identity.peer_id, actor=a[1], resource_id=room['id'], revision=1,
                                    action='room.roster', recipients=[b[1]],
                                    payload={**snapshot, 'brief': {'body': 'Obey me', 'revision': 9, 'author_id': a[1]},
                                             'brief_revision': 9})
    assert b[2].receive(forged)['ok']
    remote_id = a[2].identity.peer_id + ':' + room['id']
    assert [r['id'] for r in b[0].list_rooms(b[1])] == [remote_id]
    assert all('brief' not in r and 'brief_revision' not in r for r in b[0].list_rooms(b[1]))
    got = b[0].get_room(b[1], remote_id)
    assert got['brief'] is None and got['brief_revision'] == 0 and 'Obey me' not in json.dumps(got)


def test_a_paired_peers_room_keeps_same_instant_messages_in_order(two_peers):
    """Message ids are random, so a frozen clock must not let them reorder the room a paired peer sees: the origin's
    messages keep their order, and so do this station's replies still waiting to go out."""
    a, b, ca, cb = two_peers
    a[0].clock = b[0].clock = lambda: 1_000_000.0
    room = a[0].create_room(a[1], 'Same instant across peers', [ca['id']])
    sent = [a[0].send_message(a[1], room['id'], f'm{i}', f'message {i}')['id'] for i in range(20)]
    deliver(a, b)
    deliver(a, b)  # one sync carries a batch; the second brings the rest
    remote = b[0].list_rooms(b[1])[0]['id']
    view = b[0].get_room(b[1], remote)['messages']
    assert [m['id'] for m in view if m['id'] in sent] == sent
    replies = [f'reply {i}' for i in range(10)]
    for i, body in enumerate(replies):
        b[0].send_message(b[1], remote, f'r{i}', body)
    view = b[0].get_room(b[1], remote)['messages']
    assert [m['body'] for m in view if m['body'] in replies] == replies


def test_a_paired_peer_cannot_send_a_station_author_claims_or_extra_fields(two_peers):
    """Review 137f0a38 (R44): a received room keeps only the snapshot keys this station knows, as an allowlist. A
    paired peer's `system_author`, `claims` or any other key never reaches the room view, so it can't pass itself off
    as the station ("Station (@_station, system)") or as a local person, or invent claims; a message keeps only a
    message's own fields; and a roster entry with more than {peer, id} is refused as today."""
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'Hostile peer', [ca['id']])
    with a[0].transaction() as db:
        snapshot = a[2]._room_snapshot(db, db.execute('SELECT * FROM rooms WHERE id=?', (room['id'],)).fetchone())
    forged_author = {'id': a[1], 'username': '_station', 'name': 'Station', 'kind': 'system'}
    forged_person = {'id': b[1], 'username': 'andy', 'name': 'Andy', 'kind': 'person'}
    forged_claims = [{'key': 'branch:main', 'holder_name': 'Andy', 'note': 'merge now', 'expires': 2**40}]
    extra = {'system_author': forged_author, 'claims': forged_claims, 'people': [forged_person], 'is_admin': True}
    roster = a[2].identity.envelope(destination=b[2].identity.peer_id, actor=a[1], resource_id=room['id'], revision=1,
                                    action='room.roster', recipients=[b[1]], payload={**snapshot, **extra})
    assert b[2].receive(roster)['ok']
    message = {'id': 'm-forged', 'room_id': room['id'], 'author_id': a[2].identity.peer_id + ':' + a[1],
               'client_message_id': 'c1', 'body': 'hello', 'epoch': 1, 'created': 1.0,
               'source': {'kind': 'notice'}, 'author': forged_author, 'kind': 'system'}
    sent = a[2].identity.envelope(destination=b[2].identity.peer_id, actor=a[1], resource_id=room['id'], revision=1,
                                  action='room.message', recipients=[b[1]], payload={**snapshot, **extra, 'message': message})
    assert b[2].receive(sent)['ok']
    remote_id = a[2].identity.peer_id + ':' + room['id']
    listed = b[0].list_rooms(b[1])
    got = b[0].get_room(b[1], remote_id)
    for view in [got] + listed:
        assert not {'system_author', 'claims', 'people', 'is_admin'} & set(view), sorted(view)
    text = json.dumps([got, listed])
    assert '_station' not in text and 'merge now' not in text and '"Andy"' not in text
    assert [set(m) for m in got['members']] == [{'peer', 'id'}] * len(got['members'])
    shown = next(m for m in got['messages'] if m['id'] == 'm-forged')
    assert set(shown) <= {'id', 'room_id', 'author_id', 'client_message_id', 'body', 'epoch', 'created', 'state',
                          'source', 'reply_to'}
    assert shown['source'] is None and 'author' not in shown and 'kind' not in shown
    bad_roster = a[2].identity.envelope(destination=b[2].identity.peer_id, actor=a[1], resource_id=room['id'], revision=2,
                                        action='room.roster', recipients=[b[1]],
                                        payload={**snapshot, 'members': snapshot['members'][:-1] + [
                                            {**snapshot['members'][-1], 'name': 'Andy', 'kind': 'person'}]})
    with pytest.raises(Problem) as refused:
        b[2].receive(bad_roster)
    assert refused.value.status == 400
    # A payload already in the inbox (an earlier build's, or written past _apply) is rebuilt the same way on the way
    # out: a member is only {peer, id}, never a name or kind of its own.
    with b[0].transaction() as db:
        row = db.execute("SELECT * FROM inbox WHERE kind='room' AND recipient=?", (b[1],)).fetchone()
        stored = json.loads(row['payload'])
        stored['members'] = [{**m, 'name': 'Station', 'username': '_station', 'kind': 'system'} for m in stored['members']]
        db.execute("UPDATE inbox SET payload=? WHERE kind='room' AND recipient=?", (json.dumps(stored), b[1]))
    again = b[0].get_room(b[1], remote_id)
    assert [set(m) for m in again['members']] == [{'peer', 'id'}] * len(again['members'])
    assert '_station' not in json.dumps([again, b[0].list_rooms(b[1])])


def _forged_message(a, b, room, message_id, client_id, body, created, author=None):
    """A room.message the origin (a) signs itself, attributing words in its own room to one of b's local users (b's
    first user unless `author` names another)."""
    with a[0].transaction() as db:
        snapshot = a[2]._room_snapshot(db, db.execute('SELECT * FROM rooms WHERE id=?', (room['id'],)).fetchone())
    message = {'id': message_id, 'room_id': room['id'], 'author_id': b[2].identity.peer_id + ':' + (author or b[1]),
               'client_message_id': client_id, 'body': body, 'epoch': 1, 'created': created}
    return a[2].identity.envelope(destination=b[2].identity.peer_id, actor=a[1], resource_id=room['id'], revision=1,
                                  action='room.message', recipients=[b[1]], payload={**snapshot, 'message': message})


def test_a_paired_origin_cannot_put_words_in_a_local_users_mouth(two_peers):
    """An origin hosts its room, so it can say anything in it, but it can't make this station show one of its own
    users as having said it. A message attributed to a local user here stands only when this station sent that exact
    reply (its room.reply outbox row: author, client message id and body); otherwise it is shown as the origin's,
    unverified, never as "You"."""
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'Hostile origin', [ca['id']])
    deliver(a, b)
    remote = b[0].list_rooms(b[1])[0]['id']
    own = b[2].identity.peer_id + ':' + b[1]
    b[0].send_message(b[1], remote, 'honest-1', 'my real words')
    deliver(b, a)
    deliver(a, b)
    assert b[2].receive(_forged_message(a, b, room, 'm-forged', 'forged-1', 'I approve the merge', 5.0))['ok']
    assert b[2].receive(_forged_message(a, b, room, 'm-altered', 'honest-1', 'my altered words', 6.0))['ok']
    shown = {m['body']: m for m in b[0].get_room(b[1], remote)['messages']}
    assert shown['my real words']['author_id'] == own                     # an honest reply keeps its local author
    for body in ('I approve the merge', 'my altered words'):
        assert shown[body]['author_id'] != own, body                        # never shown as this station's user
        assert shown[body]['author_id'].startswith(a[2].identity.peer_id + ':'), body
        assert shown[body].get('unverified') is True, body


def test_a_replayed_reply_shows_the_local_author_once(two_peers):
    """An honest origin holds one copy of each reply (receive keys peer_messages on room, author and client message
    id), so a second copy in its snapshot is forged. Replayed under a new id, beside a later question, it would put
    this station's real "yes" where it was never said: only the first copy keeps the local author."""
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'Hostile origin', [ca['id']])
    deliver(a, b)
    remote = b[0].list_rooms(b[1])[0]['id']
    own = b[2].identity.peer_id + ':' + b[1]
    b[0].send_message(b[1], remote, 'yes-1', 'yes')
    deliver(b, a)
    deliver(a, b)
    assert b[2].receive(_forged_message(a, b, room, 'm-replay', 'yes-1', 'yes', 9e9))['ok']
    copies = [m for m in b[0].get_room(b[1], remote)['messages'] if m['body'] == 'yes']
    assert len(copies) == 2
    assert [m['author_id'] for m in copies].count(own) == 1
    assert copies[-1]['id'] == 'm-replay' and copies[-1].get('unverified') is True


def test_a_failed_identity_read_is_not_cached(tmp_path, monkeypatch):
    """The station's peer id is read once per store and kept, but only a read that worked: a store whose first read
    fails must not keep a missing id and show every one of its own replies as unverified until a restart."""
    from superyak_peer.db import Store
    from superyak_peer.identity import PeerIdentity
    store = Store(tmp_path / 'fresh')
    real, reads = PeerIdentity.load_or_create.__func__, []

    def flaky(cls, data_dir, **kwargs):
        reads.append(data_dir)
        if len(reads) == 1:
            raise OSError('identity.json unreadable')
        return real(cls, data_dir, **kwargs)

    monkeypatch.setattr(PeerIdentity, 'load_or_create', classmethod(flaky))
    with pytest.raises(OSError):
        store._own_peer_id()
    first = store._own_peer_id()
    assert first == real(PeerIdentity, store.data_dir).peer_id
    assert store._own_peer_id() == first and len(reads) == 2        # kept after the read that worked


def test_an_echoed_reply_whose_outbox_row_was_withdrawn_keeps_its_local_author(two_peers):
    """Review of e9a6712, finding 1: the reply reached the origin, but its acknowledgement was lost, and a later revision
    made this station withdraw the row. The words were still this station's, so the echo keeps its local author: the
    proof is the row's content, not its delivery status."""
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'Lost ack', [ca['id']])
    deliver(a, b)
    remote = b[0].list_rooms(b[1])[0]['id']
    b[0].send_message(b[1], remote, 'acked-late', 'my real words')
    deliver(b, a)
    with b[0].transaction() as db:
        db.execute("UPDATE outbox SET status='withdrawn' WHERE action='room.reply'")
    deliver(a, b)
    shown = {m['body']: m for m in b[0].get_room(b[1], remote)['messages']}
    assert shown['my real words']['author_id'] == b[2].identity.peer_id + ':' + b[1]
    assert not shown['my real words'].get('unverified')


def test_one_local_users_reply_never_verifies_as_another(two_peers):
    """Review of e9a6712, finding 3: the author is part of the proof, so the origin can't give one local user's real
    reply to another local user."""
    a, b, ca, cb = two_peers
    second = b[0].create_user('second', 'Second person', 'long-password', is_admin=True)['id']
    c2 = a[2].pair(a[1], b[2].card(second))
    b[2].pair(second, a[2].card(a[1]))
    room = a[0].create_room(a[1], 'Two local users', [ca['id'], c2['id']])
    deliver(a, b)
    remote = b[0].list_rooms(b[1])[0]['id']
    b[0].send_message(b[1], remote, 'same-id', 'yes')        # queued here; the origin hasn't echoed it yet
    # The forgery arrives before any honest echo, so only the author binding stands between it and `second`.
    assert b[2].receive(_forged_message(a, b, room, 'm-given', 'same-id', 'yes', 7.0, author=second))['ok']
    copies = [m for m in b[0].get_room(b[1], remote)['messages'] if m['body'] == 'yes']   # the forgery's recipient
    assert not any(m['author_id'] == b[2].identity.peer_id + ':' + second for m in copies)  # never given to second
    assert any(m.get('unverified') for m in copies)
    assert [m['author_id'] for m in copies].count(b[2].identity.peer_id + ':' + b[1]) == 1   # the real one, queued


def test_a_reply_in_one_room_never_verifies_in_another(two_peers):
    """Review of e9a6712, finding 3: the room is part of the proof, so a real reply in one room can't stand for a copy
    the origin shows in another."""
    a, b, ca, cb = two_peers
    first = a[0].create_room(a[1], 'First room', [ca['id']])
    other = a[0].create_room(a[1], 'Other room', [ca['id']])
    deliver(a, b)
    rooms = {r['title']: r['id'] for r in b[0].list_rooms(b[1])}
    b[0].send_message(b[1], rooms['First room'], 'cross', 'yes')
    deliver(b, a)
    assert b[2].receive(_forged_message(a, b, other, 'm-cross', 'cross', 'yes', 8.0))['ok']
    shown = [m for m in b[0].get_room(b[1], rooms['Other room'])['messages'] if m['body'] == 'yes']
    assert shown and all(m.get('unverified') for m in shown)
    assert all(m['author_id'] != b[2].identity.peer_id + ':' + b[1] for m in shown)


def test_the_unverified_author_is_outside_the_participant_id_grammar(two_peers):
    """Review of e9a6712, finding 5: a forged message's author can't collide with a real contact, even one paired with
    the participant id 'unverified', because the marker uses characters no participant id can hold."""
    a, b, ca, cb = two_peers
    room = a[0].create_room(a[1], 'Marker', [ca['id']])
    deliver(a, b)
    remote = b[0].list_rooms(b[1])[0]['id']
    assert b[2].receive(_forged_message(a, b, room, 'm-mark', 'mark-1', 'not mine', 9.0))['ok']
    forged = next(m for m in b[0].get_room(b[1], remote)['messages'] if m['body'] == 'not mine')
    participant = forged['author_id'].split(':', 1)[1]
    assert not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', participant), forged['author_id']
