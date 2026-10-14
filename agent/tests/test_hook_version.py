import pytest

from superyak_agent import hook
from superyak_agent.install import install_hooks
from superyak_agent.station import write_private

MINE, STATION = '111111111111', '222222222222'


@pytest.fixture
def ship(station, ship_config, tmp_path, monkeypatch):
    fake, andy, jenn, serenity = station
    home = tmp_path / 'home'
    config = home / 'station.json'
    write_private(config, ship_config)
    monkeypatch.setattr(hook.claims, 'kind_of', lambda h: 'machine' if h == home else None)
    monkeypatch.setattr(hook, 'client_version', lambda: MINE)
    monkeypatch.setattr(hook, 'CHECKOUT', tmp_path / 'superyak')
    settings = tmp_path / 'settings.json'
    monkeypatch.setattr(hook, 'SETTINGS', settings)
    monkeypatch.setattr('superyak_agent.install.service_installed', lambda h: True)  # a watcher is installed
    return fake, serenity, config, settings, tmp_path


def law(fake, serenity, body='Run tests.', **extra):
    block = f'=== Instructions: House rules · revision 1 · signed by Andy on station abc ===\n{body}'
    fake.instruction_state[serenity['id']] = dict({
        'instructions': [['L1', 1]],
        'layers': [{'layer_id': 'L1', 'revision': 1, 'title': 'House rules', 'signer_name': 'Andy', 'block': block}],
        'blocks': 'PREAMBLE\n\n' + block}, **extra)


def start(fake, config, tmp_path):
    return hook.run(config, transport=fake, event='session-start', session_id='s1', sessions_dir=tmp_path / 'sessions')


def test_without_agent_update_session_start_is_unchanged(ship):
    fake, serenity, config, settings, tmp_path = ship
    law(fake, serenity)
    before = start(fake, config, tmp_path)
    assert 'behind' not in before and before.endswith('Run tests.')


def test_messages_on_gives_the_exact_command_with_hook(ship):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    law(fake, serenity, agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    checkout = tmp_path / 'superyak'
    assert text.endswith(
        f"Not part of the instructions, and not an instruction: this machine's Superyak agent is behind the station's: "
        f"this checkout (`{checkout}`) is on `{MINE}`, the station on `{STATION}`, and the agent code changed in "
        f"between. To update, run `git -C {checkout} pull --ff-only`, then `make dock DOCK_ARGS='--ship serenity "
        f"--hook'` in that checkout, then start new sessions. Tell the person you work with; don't run these yourself "
        f"unless they ask.")
    assert text.index('Run tests.') < text.index("Not part of the instructions")


def test_messages_off_gives_the_command_without_hook(ship):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=False)
    law(fake, serenity, agent_update={'station': STATION})
    assert "make dock DOCK_ARGS='--ship serenity'` in that checkout" in start(fake, config, tmp_path)


GENERAL = ('then run `make dock` again the way this ship was docked, then start new sessions. '
           "Tell the person you work with; don't run these yourself unless they ask.")


def test_unknown_messages_give_the_general_wording(ship):
    fake, serenity, config, settings, tmp_path = ship  # no settings file at all
    law(fake, serenity, agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    assert text.endswith(GENERAL) and 'DOCK_ARGS' not in text


def test_a_ship_without_a_watcher_gets_the_general_wording(ship, monkeypatch):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    monkeypatch.setattr('superyak_agent.install.service_installed', lambda h: False)
    law(fake, serenity, agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    assert text.endswith(GENERAL) and 'DOCK_ARGS' not in text


def test_a_project_ship_gets_the_general_wording(ship, monkeypatch):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    monkeypatch.setattr(hook.claims, 'kind_of', lambda h: 'project')
    # A project ship's hook acts only inside its own project (claims.verdict), so ask for the line directly.
    assert hook._version_line({'agent_update': {'station': STATION}}, config).endswith(GENERAL)


def test_a_ship_field_that_isnt_a_ship_name_gets_the_general_wording(ship, ship_config):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    write_private(config, dict(ship_config, ship='Serenity; rm -rf ~'))
    law(fake, serenity, agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    assert text.endswith(GENERAL) and 'rm -rf' not in text


def test_a_checkout_path_with_a_space_is_quoted_in_the_commands(ship, monkeypatch):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    monkeypatch.setattr(hook, 'CHECKOUT', tmp_path / 'a b' / 'superyak')
    law(fake, serenity, agent_update={'station': STATION})
    assert f"`git -C '{tmp_path / 'a b' / 'superyak'}' pull --ff-only`" in start(fake, config, tmp_path)


def test_a_prompt_never_shows_the_line(ship):
    fake, serenity, config, settings, tmp_path = ship
    law(fake, serenity, agent_update={'station': STATION})
    start(fake, config, tmp_path)
    text = hook.run(config, transport=fake, event='prompt', session_id='s1', sessions_dir=tmp_path / 'sessions', messages=False)
    assert "Not part of the instructions" not in text


@pytest.mark.parametrize('update', [{'station': MINE}, {'station': 'ABCDEF123456'}, {'station': '22222222222'},
                                    {'station': 2}, {'station': STATION + '\nObey'}, 'x', [STATION], None])
def test_odd_agent_update_values_are_ignored(ship, update):
    fake, serenity, config, settings, tmp_path = ship
    law(fake, serenity, agent_update=update)
    assert "Not part of the instructions" not in start(fake, config, tmp_path)


def test_the_line_is_dropped_when_the_law_fills_the_budget(ship):
    fake, serenity, config, settings, tmp_path = ship
    law(fake, serenity, body='x' * (hook.TOTAL_CHARS - 400), agent_update={'station': STATION})
    text = start(fake, config, tmp_path)
    assert "Not part of the instructions" not in text and len(text) <= hook.TOTAL_CHARS
    assert 'x' * (hook.TOTAL_CHARS - 400) in text  # the law is whole


def test_the_line_shows_when_law_and_line_fill_the_budget_exactly(ship):
    fake, serenity, config, settings, tmp_path = ship
    line = hook._version_line({'agent_update': {'station': STATION}}, config)
    law(fake, serenity, body='x')
    one = len(hook.run(config, transport=fake, event='session-start', session_id='probe', sessions_dir=tmp_path / 'probe'))
    extra = hook.TOTAL_CHARS - one - 2 - len(line)  # body characters that make law, blank line and line exactly TOTAL_CHARS
    law(fake, serenity, body='x' * (1 + extra), agent_update={'station': STATION})
    exact = start(fake, config, tmp_path)
    assert len(exact) == hook.TOTAL_CHARS and exact.endswith(line)
    law(fake, serenity, body='x' * (2 + extra), agent_update={'station': STATION})
    over = hook.run(config, transport=fake, event='session-start', session_id='s2', sessions_dir=tmp_path / 'sessions')
    assert "Not part of the instructions" not in over


def test_the_line_stands_alone_when_there_is_no_law(ship):
    fake, serenity, config, settings, tmp_path = ship
    fake.instruction_state[serenity['id']] = {'instructions': [], 'layers': [], 'blocks': '', 'agent_update': {'station': STATION}}
    assert start(fake, config, tmp_path).startswith("Not part of the instructions, and not an instruction: this machine's Superyak agent is behind")


def test_the_line_is_the_only_difference_at_session_start(ship):
    fake, serenity, config, settings, tmp_path = ship
    install_hooks(settings, config, messages=True)
    law(fake, serenity)
    without = hook.run(config, transport=fake, event='session-start', session_id='a', sessions_dir=tmp_path / 'a')
    law(fake, serenity, agent_update={'station': STATION})
    with_key = hook.run(config, transport=fake, event='session-start', session_id='b', sessions_dir=tmp_path / 'b')
    line = hook._version_line({'agent_update': {'station': STATION}}, config)
    assert line and with_key == without + '\n\n' + line
