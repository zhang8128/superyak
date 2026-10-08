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

