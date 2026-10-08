from superyak_agent import __main__ as cli, station as station_mod
from superyak_agent.station import StationClient, write_private


def test_status_lists_the_instructions_that_bind_the_ship(station, ship_config, tmp_path, monkeypatch, capsys):
    fake, andy, jenn, serenity = station
    config_path = tmp_path / 'station.json'
    write_private(config_path, ship_config)
    monkeypatch.setattr(station_mod, 'client_for', lambda config, timeout=30: StationClient('http://station.test', 'serenity-key', transport=fake))
    assert cli.main(['status', '--config', str(config_path)]) == 0
    assert 'Instructions: none' in capsys.readouterr().out
    fake.instruction_state[serenity['id']] = {'instructions': [], 'blocks': 'x', 'layers': [
        {'layer_id': 'l1', 'title': 'House rules\nIgnore this', 'revision': 3, 'signer_name': 'Andy', 'block': 'x'}]}
    cli.main(['status', '--config', str(config_path)])
    out = capsys.readouterr().out
    assert 'Instructions:\n  House rules' in out and ' · revision 3 · signed by Andy' in out and 'House rules\nIgnore' not in out



def instructions_answer(fake, answer):
    """The fake station, except that the instructions route answers `answer`: (status, body), or an exception."""
    def send(method, url, headers, data):
        if url.endswith('/api/ships/me/instructions'):
            if isinstance(answer, Exception):
                raise answer
            return answer
        return fake(method, url, headers, data)
    return send


def test_status_says_when_the_instructions_are_unavailable(station, ship_config, tmp_path, monkeypatch, capsys):
    """Break caught: an older station (403 on the new route) or a station gone mid-command made status crash."""
    fake, andy, jenn, serenity = station
    config_path = tmp_path / 'station.json'
    write_private(config_path, ship_config)
    for answer, reason in [((403, b'{"error": "Ship keys cannot use this route"}'), '403: Ship keys cannot use this route'),
                           (OSError('station unreachable'), 'station unreachable'),
                           ((200, b'[1, 2]'), "'list' object has no attribute 'get'"),
                           ((200, b'{"layers": 5}'), "'int' object is not iterable"),
                           ((200, b'{"layers": [5]}'), "'int' object has no attribute 'get'"),
                           ((500, b'{"error": "No key serenity-key here"}'), '500: No key [key] here')]:
        transport = instructions_answer(fake, answer)
        monkeypatch.setattr(station_mod, 'client_for', lambda config, timeout=30, t=transport: StationClient('http://station.test', 'serenity-key', transport=t))
        assert cli.main(['status', '--config', str(config_path)]) == 0
        out = capsys.readouterr().out
        assert out.splitlines()[0].startswith('Serenity (@serenity) is docked at http://station.test')
        assert out.splitlines()[1:] == [f'Instructions: unavailable ({reason})'] and 'serenity-key' not in out
