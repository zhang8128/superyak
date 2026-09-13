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
