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


def test_attachment_delivery_and_withdrawal(two_peers):
    import base64
    a,b,ca,cb=two_peers
    file=a[0].upload_file(a[1],'note.txt','text/plain',base64.b64encode(b'attachment').decode())
    layer=a[0].create_layer(a[1],{'body':'attached','audience_users':[ca['id']], 'attachment_ids':[file['id']]})
    a[0].activate_layer(a[1],layer['id'],1)
    deliver(a,b)
    remote=b[0].shared_layers(b[1])[0]['id']
    assert b[0].download_file(b[1],file['id'],layer_id=remote)['content']==b'attachment'
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
