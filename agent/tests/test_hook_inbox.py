"""Station inbox, step 5: with a Claude Code session id the hook reads that session's cursor on the station (spec I8,
R4). It shows an oldest-first prefix within its budget, then advances through the last message it showed, as the last
thing that can fail; anything not shown stays unread. Without a session id it keeps the old behaviour until the shared
stdin helper (spec A step 2) passes one."""
from superyak_agent import hook
from superyak_agent.station import write_private


def run(fake, config_path, session_id):
    return hook.run(config_path, session_id=session_id, transport=fake)


def write_config(ship_config, tmp_path):
    path = tmp_path / 'home' / 'station.json'
    write_private(path, ship_config)
    return path


def test_each_session_sees_a_new_message_once(station, ship_config, tmp_path):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, jenn, serenity)
    fake.say(room, jenn, 'Lunch at noon?')
    one, two = run(fake, config_path, 'session-one'), run(fake, config_path, 'session-two')
    assert 'Lunch at noon?' in one and 'quoted message' in one
    assert two == ''  # a new session starts where the ship has read furthest
    fake.say(room, jenn, 'Moved to one')
    assert 'Moved to one' in run(fake, config_path, 'session-one') and 'Moved to one' in run(fake, config_path, 'session-two')
    assert run(fake, config_path, 'session-one') == '' and run(fake, config_path, 'session-two') == ''


def test_the_first_turn_is_not_silent_any_more(station, ship_config, tmp_path):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, serenity)
    fake.say(room, andy, 'posted before this session started')
    assert 'posted before this session started' in run(fake, config_path, 'fresh')


def test_messages_left_out_for_space_stay_unread_for_the_next_turn(station, ship_config, tmp_path):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, serenity)
    for n in range(25):
        fake.say(room, andy, f'note {n:02d} ' + 'y' * 300)
    first = run(fake, config_path, 's1')
    shown = [n for n in range(25) if f'note {n:02d} ' in first]
    assert shown == list(range(len(shown))) and 0 < len(shown) < 25 and len(first) <= hook.MAX_CHARS
    assert '`station_unread`' in first
    second = run(fake, config_path, 's1')
    assert f'note {len(shown):02d} ' in second and 'note 00 ' not in second


def test_when_advance_fails_nothing_is_printed_and_the_messages_stay_unread(station, ship_config, tmp_path):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, serenity)
    fake.say(room, andy, 'keep me')

    def broken_advance(method, url, headers, data):
        if url.endswith('/api/ships/me/unread/advance'):
            raise OSError('connection dropped')
        return fake(method, url, headers, data)
    assert hook.run(config_path, session_id='s1', transport=broken_advance, clock=lambda: 1000.0) == ''
    assert 'keep me' in hook.run(config_path, session_id='s1', transport=fake, clock=lambda: 1061.0)  # after the unreachable minute


def test_when_formatting_fails_the_cursor_never_moves(station, ship_config, tmp_path, monkeypatch):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, serenity)
    fake.say(room, andy, 'keep me too')
    advanced = []

    def watching(method, url, headers, data):
        if url.endswith('/advance'):
            advanced.append(url)
        return fake(method, url, headers, data)

    def boom(*args, **kwargs):
        raise RuntimeError('formatting broke')
    with monkeypatch.context() as patch:
        patch.setattr(hook, 'fence_message', boom)
        assert hook.run(config_path, session_id='s1', transport=watching) == ''
    assert advanced == []
    assert 'keep me too' in run(fake, config_path, 's1')


def test_an_unreachable_station_prints_nothing_and_keeps_the_position(station, ship_config, tmp_path):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, serenity)
    fake.say(room, andy, 'while the station was down')
    fake.down = True
    assert hook.run(config_path, session_id='s1', transport=fake, clock=lambda: 1000.0) == ''
    fake.down = False
    assert hook.run(config_path, session_id='s1', transport=fake, clock=lambda: 1030.0) == ''  # it waits a minute to call again
    assert 'while the station was down' in hook.run(config_path, session_id='s1', transport=fake, clock=lambda: 1061.0)


def test_inside_a_watcher_run_the_hook_reads_nothing(station, ship_config, tmp_path, monkeypatch):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, serenity)
    fake.say(room, andy, 'for the person, not the run')
    monkeypatch.setenv('SUPERYAK_RUN', '1')
    assert run(fake, config_path, 's1') == '' and fake.unread_calls == []


def test_a_ships_message_keeps_its_provenance_label(station, ship_config, tmp_path):
    from superyak_agent.station import source_label
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    rio = fake.user('rio-grande', 'Rio Grande', 'ship', andy['id'], key='rio-key')
    room = fake.room('Ops', andy, serenity, rio)
    posted = fake.say(room, rio, 'a ship speaking')
    expected = source_label({'source': fake.source_of(posted)})
    assert expected and f'({expected})' in run(fake, config_path, 's1')


def test_the_hook_reads_its_session_id_from_claude_codes_stdin():
    import io
    assert hook.session_from_stdin(io.StringIO('{"session_id": "abc-123", "prompt": "hi"}')) == 'abc-123'
    assert hook.session_from_stdin(io.StringIO('not json')) is None
    assert hook.session_from_stdin(io.StringIO('{"session_id": 5}')) is None
    assert hook.session_from_stdin(io.StringIO('')) is None


def test_a_full_page_that_all_fits_says_more_without_a_false_count(station, ship_config, tmp_path, monkeypatch):
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    room = fake.room('Ops', andy, serenity)
    for n in range(25):
        fake.say(room, andy, f'tiny {n}')
    monkeypatch.setattr(hook, 'MAX_CHARS', 100000)
    text = run(fake, config_path, 's1')
    assert 'more unread' in text and '0+' not in text and '0 more' not in text


def test_deeply_nested_stdin_never_breaks_the_hook():
    import io
    assert hook.session_from_stdin(io.StringIO('[' * 100000 + ']' * 100000)) is None


def test_the_hooks_two_station_calls_fit_inside_claude_codes_hook_timeout():
    # unread then advance: each call's timeout times two must stay well under the 10 s hook timeout, or Claude Code
    # could stop the hook after the advance and before the text is printed (R4).
    assert 2 * hook.INBOX_CALL_TIMEOUT <= 7


def fleet(fake, andy, serenity):
    """Andy's ships put together in a room he owns, as in "Superyak: all hands"."""
    rio = fake.user('rio-grande', 'Rio Grande', 'ship', andy['id'], key='rio-key')
    tardis = fake.user('tardis', 'Tardis', 'ship', andy['id'], key='tardis-key')
    return rio, tardis, fake.room('Superyak: all hands', andy, serenity, rio, tardis)


def test_breakout_noise_never_holds_back_a_persons_message(station, ship_config, tmp_path):
    """R13, the hook's half (breakouts S6): 30 messages in two breakouts, then a person's message. The hook sends
    breakouts=mentions, so the person's message shows at the first prompt, and one line per breakout counts what the
    station left out and names the call that shows it. Counted once: the next prompt is silent."""
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    rio, tardis, hands = fleet(fake, andy, serenity)
    alpha, beta = fake.breakout('Alpha', rio, serenity), fake.breakout('Beta', tardis, serenity)
    for n in range(15):
        fake.say(alpha, rio, f'alpha {n}')
        fake.say(beta, tardis, f'beta {n}')
    person = fake.say(hands, andy, 'Serenity, a question from Andy')
    text = run(fake, config_path, 's1')
    assert [r['query'] for r in fake.requests if r['path'] == '/api/ships/me/unread'] == ['breakouts=mentions']
    assert person['body'] in text and 'alpha 0' not in text and 'beta 14' not in text
    assert text.endswith(f'\n\n15 new in breakout Alpha; `station_read room={alpha}` shows them\n\n'
                         f'15 new in breakout Beta; `station_read room={beta}` shows them')
    assert run(fake, config_path, 's1') == ''


def test_a_breakout_message_is_labelled_ships_only(station, ship_config, tmp_path):
    """Breakouts S6: a breakout message that mentions the ship shows, labelled "breakout, ships only"; a message from
    any other room keeps today's header."""
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    rio, tardis, hands = fleet(fake, andy, serenity)
    alpha = fake.breakout('Alpha', rio, serenity)
    asked = fake.say(alpha, rio, '@serenity over to you')
    said = fake.say(hands, andy, 'and from me')
    text = run(fake, config_path, 's1')
    assert f'Room Alpha (breakout, ships only), message {asked["id"]} (no run ticket):\n' in text
    assert f'Room Superyak: all hands, message {said["id"]}:\n' in text


def test_breakout_counts_show_even_when_no_message_does(station, ship_config, tmp_path):
    """Breakouts S6: when every new message is breakout noise, the station has already passed it, so the hook still
    says how many, and has nothing to advance through."""
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    rio, tardis, hands = fleet(fake, andy, serenity)
    alpha = fake.breakout('Alpha', rio, serenity)
    for n in range(3):
        fake.say(alpha, rio, f'alpha {n}')
    text = run(fake, config_path, 's1')
    assert text == hook.HEADER + f'\n\n3 new in breakout Alpha; `station_read room={alpha}` shows them'
    assert not any(r['path'].endswith('/advance') for r in fake.requests)
    assert run(fake, config_path, 's1') == ''


def test_the_breakout_count_lines_fit_the_hooks_budget(station, ship_config, tmp_path):
    """Breakouts S6: at most five count lines, then one line for the rest, and the person's messages still lead, all
    inside the hook's 4,000 characters; what doesn't fit stays unread."""
    fake, andy, jenn, serenity = station
    config_path = write_config(ship_config, tmp_path)
    rio, tardis, hands = fleet(fake, andy, serenity)
    for n in range(8):
        fake.say(fake.breakout(f'{n} ' + 'B' * 78, rio, serenity), rio, 'noise')
    for n in range(25):
        fake.say(hands, andy, f'note {n:02d} ' + 'y' * 300)
    text = run(fake, config_path, 's1')
    assert len(text) <= hook.MAX_CHARS and 'note 00 ' in text and '`station_unread`' in text
    assert [line[:5] for line in text.splitlines() if ' new in breakout ' in line] == ['1 new'] * 5
    assert text.endswith('\n\n3 more breakouts have new messages; `station_rooms` lists them')
    shown = [n for n in range(25) if f'note {n:02d} ' in text]
    assert f'note {len(shown):02d} ' in run(fake, config_path, 's1')
