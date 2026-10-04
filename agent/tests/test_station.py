import pytest
from superyak_agent.station import StationClient, StationError, read_json, write_private


def test_client_sends_key_and_origin_and_reads_rooms(station):
    fake, andy, jenn, serenity = station
    fake.room('Ops', andy, serenity)
    seen = []

    def spy(method, url, headers, data):
        seen.append(headers)
        return fake(method, url, headers, data)
    client = StationClient('http://station.test', 'serenity-key', transport=spy)
    assert client.me()['username'] == 'serenity'
    assert [r['title'] for r in client.rooms()] == ['Ops']
    assert seen[0]['authorization'] == 'Bearer serenity-key' and seen[0]['origin'] == 'http://station.test'


def test_loopback_client_presents_the_public_origin_like_the_proxy(station):
    fake, *_ = station
    seen = []
    client = StationClient('http://127.0.0.1:7435', 'serenity-key', origin='https://smart.example.ts.net',
                           transport=lambda m, u, h, d: (seen.append(h), fake(m, u, h, d))[1])
    client.me()
    assert (seen[0]['origin'], seen[0]['host'], seen[0]['x-forwarded-proto']) == ('https://smart.example.ts.net', 'smart.example.ts.net', 'https')


def test_errors_carry_status_and_message(station):
    fake, *_ = station
    with pytest.raises(StationError) as caught:
        StationClient('http://station.test', 'wrong', transport=fake).rooms()
    assert (caught.value.status, caught.value.message) == (401, 'Invalid ship key')


def test_private_files_are_0600_and_replaced_atomically(tmp_path):
    path = tmp_path / 'home' / 'station.json'
    write_private(path, {'key': 'k1'})
    write_private(path, {'key': 'k2'})
    assert read_json(path) == {'key': 'k2'} and path.stat().st_mode & 0o777 == 0o600
    assert read_json(tmp_path / 'missing.json', {}) == {}
