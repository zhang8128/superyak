def test_private_room_denies_nonmembers_and_admin(env):
    _, clients, users, _ = env
    room = clients[0].post('/api/chats', json={'title': 'Private chat', 'member_ids': [users[3]['id']]}).json()
    key = room['id']
    for client in clients[1:3]:
        assert client.get(f'/api/chats/{key}').status_code == 404
        assert client.post(f'/api/chats/{key}/messages', json={'client_message_id': 'bad', 'body': 'intrude'}).status_code == 404
        assert key not in client.get('/api/home').text

def test_new_audience_gets_linked_empty_room_and_removal_revokes(env):
    app, clients, users, _ = env
    patient, doctor, _, family = clients
    room = patient.post('/api/chats', json={'title': 'Private chat', 'member_ids': [users[3]['id']]}).json()
    key = room['id']
    message = patient.post(f'/api/chats/{key}/messages', json={'client_message_id': 'one', 'body': 'old secret'}).json()
    repeated = patient.post(f'/api/chats/{key}/messages', json={'client_message_id': 'one', 'body': 'old secret'}).json()
    assert repeated['id'] == message['id']
    assert patient.post(f'/api/chats/{key}/messages', json={'client_message_id': 'one', 'body': 'changed'}).status_code == 409
    linked = patient.post(f'/api/chats/{key}/participants', json={'member_ids': [users[1]['id']]}).json()
    assert linked['linked_room_id'] == key
    assert doctor.get(f'/api/chats/{key}').status_code == 404
    assert doctor.get('/api/chats/' + linked['id']).json()['messages'] == []
    assert patient.delete(f'/api/chats/{key}/participants/' + users[3]['id']).status_code == 200
    assert family.get(f'/api/chats/{key}').status_code == 404
    assert not app.state.store.can_deliver_message(message['id'], users[3]['id'], 1)
    assert patient.get(f'/api/chats/{key}').json()['epoch'] == 2

def test_home_orders_authorized_chats_by_latest_activity(env):
    _, clients, users, clock = env
    patient, doctor = clients[:2]
    old = patient.post('/api/chats', json={'title': 'Older shared room', 'member_ids': [users[1]['id']]}).json()
    clock[0] += 10
    newer = patient.post('/api/chats', json={'title': 'Newer shared room', 'member_ids': [users[1]['id']]}).json()
    assert doctor.get('/api/home').json()['chats'][0]['id'] == newer['id']
    clock[0] += 10
    patient.post('/api/chats/' + old['id'] + '/messages', json={'client_message_id': 'recent', 'body': 'A new message'})
    clock[0] += 10
    private = patient.post('/api/chats', json={'title': 'Private latest room'}).json()
    summaries = doctor.get('/api/home').json()['chats']
    assert [room['id'] for room in summaries] == [old['id'], newer['id']]
    assert summaries[0]['created'] == 1000000.0
    assert summaries[0]['last_activity'] == 1000020.0
    assert summaries[1]['last_activity'] == 1000010.0
    assert private['id'] not in doctor.get('/api/home').text
    assert all('messages' not in room for room in summaries)
    # Equal timestamps sort by stable ID, regardless of construction order.
    same_time = patient.post('/api/chats', json={'title': 'Same time', 'member_ids': [users[1]['id']]}).json()
    patient.post('/api/chats/' + newer['id'] + '/messages', json={'client_message_id': 'tie', 'body': 'Same timestamp'})
    assert [room['id'] for room in doctor.get('/api/chats').json()][:2] == sorted([same_time['id'], newer['id']])
