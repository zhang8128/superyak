"""build:route-watch: the public route checked read-only from off the Pi, a line posted only when a check changes."""
import json
import os
import stat

import pytest

from superyak_agent import route_watch as rw

KEY = 'sk-test-ship-key-never-printed'
CONFIG = {'station': 'https://smart.example.ts.net', 'key': KEY, 'ship': 'tardis'}
ROOM = 'room-city'
GOOD = {name: expected for name, _, _, _, expected in rw.CHECKS}


class Route:
    """The public route as a table of answers by check name; an exception in it is raised."""

    def __init__(self, **answers):
        self.answers, self.calls = dict(GOOD, **answers), []

    def __call__(self, address, host, method, path, key=None):
        self.calls.append((address, host, method, path, key))
        name = next(n for n, m, p, _, _ in rw.CHECKS if (m, p) == (method, path))
        answer = self.answers[name]
        if isinstance(answer, BaseException):
            raise answer
        return answer


class Station:
    def __init__(self, fail=False):
        self.posts, self.fail = [], fail

    def post(self, room_id, body, client_message_id, ticket_id=None, reply_to=None):
        if self.fail:
            raise OSError('station down')
        self.posts.append((room_id, body))
        return {}


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def run(tmp_path, route, station=None, clock=None, **kw):
    return rw.run_once(CONFIG, ROOM, tmp_path / 'route-watch.json', station or Station(), now=clock or Clock(),
                       resolve=lambda host: '203.0.113.9', request=route, **kw)


def test_the_checks_write_nothing_on_the_station():
    """No sign-in, nothing with the key but /api/home (which /api/me isn't: it writes last_used and presence), and only
    one anonymous POST, which the middleware refuses before any route."""
    calls = {(method, path, keyed) for _, method, path, keyed, _ in rw.CHECKS}
    assert not any('login' in path or 'session' in path for _, path, _ in calls)
    assert [(m, p) for m, p, keyed in calls if keyed] == [('GET', '/api/home')]
    assert [(m, p) for m, p, _ in calls if m != 'GET'] == [('POST', '/api/dockings')]
    assert dict((p, e) for _, m, p, k, e in rw.CHECKS if k) == {'/api/home': rw.SHIP_REFUSED}


def test_it_goes_in_through_the_public_address_with_the_station_s_hostname(tmp_path):
    route = Route()
    run(tmp_path, route)
    assert {(a, h) for a, h, *_ in route.calls} == {('203.0.113.9', 'smart.example.ts.net')}
    assert [k for *_, k in route.calls if k] == [KEY]


def test_the_first_run_posts_that_it_started_and_a_quiet_run_posts_nothing(tmp_path):
    station = Station()
    assert run(tmp_path, Route(), station) == ['route watch: started; 7/7 pass']
    assert run(tmp_path, Route(), station) == []
    assert station.posts == [(ROOM, 'route watch: started; 7/7 pass')]


def test_a_running_route_answering_wrong_is_reported_at_once(tmp_path):
    run(tmp_path, Route())
    lines = run(tmp_path, Route(**{'anonymous /api/accounts refused': (200, [{'username': 'andy'}])}))
    assert lines == ['route watch: anonymous /api/accounts refused now 200 (was ok)']


def test_an_outage_is_reported_only_when_it_comes_back_twice(tmp_path):
    run(tmp_path, Route())
    down = Route(health=(503, {'error': 'Station busy'}), **{'the app': ConnectionRefusedError()})
    assert run(tmp_path, down) == []
    assert run(tmp_path, down) == ['route watch: the app now no answer (ConnectionRefusedError) (was ok); '
                                   'health now 503 "Station busy" (was ok)']
    assert run(tmp_path, Route()) == []  # one good run could be a blip too
    assert run(tmp_path, Route()) == ['route watch: the app now ok (was no answer (ConnectionRefusedError)); '
                                      'health now ok (was 503 "Station busy")']


def test_no_public_address_fails_every_check_as_an_outage(tmp_path):
    run(tmp_path, Route())

    def nowhere(host):
        raise OSError('no address')

    for expected in ([], ['route watch: ' + '; '.join(f'{n} now no public address (OSError) (was ok)'
                                                       for n, *_ in rw.CHECKS)]):
        assert rw.run_once(CONFIG, ROOM, tmp_path / 'route-watch.json', Station(), now=Clock(), resolve=nowhere,
                           request=Route()) == expected


def test_a_day_later_it_says_it_is_still_watching(tmp_path):
    clock = Clock()
    run(tmp_path, Route(), clock=clock)
    clock.now += rw.DAY - 1
    assert run(tmp_path, Route(), clock=clock) == []
    clock.now += 1
    assert run(tmp_path, Route(), clock=clock) == ['route watch: still watching; 7/7 pass']


def test_a_post_that_fails_is_kept_and_sent_next_run(tmp_path):
    run(tmp_path, Route())
    wrong = Route(health=(200, {'ok': False}))
    assert run(tmp_path, wrong, Station(fail=True)) == []
    station = Station()
    assert run(tmp_path, wrong, station) == ['route watch: health now 200 (was ok)']
    assert json.loads((tmp_path / 'route-watch.json').read_text())['pending'] == []


def test_a_post_names_a_status_and_an_error_string_never_a_body_or_the_key(tmp_path):
    run(tmp_path, Route())
    leak = Route(**{'the ship key passes the route': (200, {'user': {'name': 'Andy Secret'}, 'chats': ['private']}),
                    'anonymous /api/me refused': (418, {'error': 'teapot ```\n' + KEY})})
    station = Station()
    run(tmp_path, leak, station)  # both wrong answers below 500, so reported at once
    [(_, body)] = station.posts
    assert body == ('route watch: anonymous /api/me refused now 418 "teapot [key]" (was ok); '
                    'the ship key passes the route now 200 (was ok)')
    state = (tmp_path / 'route-watch.json').read_text()
    assert not any(secret in body + state for secret in ('Secret', 'private', KEY))


def test_the_error_string_is_cut_and_the_key_is_never_in_state(tmp_path):
    run(tmp_path, Route(health=(500, {'error': 'x' * 500})))
    state = (tmp_path / 'route-watch.json').read_text()
    assert KEY not in state and 'x' * 61 not in state


def test_the_state_file_is_private_and_a_damaged_one_starts_over(tmp_path):
    run(tmp_path, Route())
    path = tmp_path / 'route-watch.json'
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    path.write_text('{not json')
    assert run(tmp_path, Route()) == ['route watch: started; 7/7 pass']


def test_a_dry_run_prints_each_check_and_posts_and_keeps_nothing(tmp_path):
    printed, station = [], Station()
    run(tmp_path, Route(health=(503, None)), station, dry_run=True, out=printed.append)
    assert station.posts == [] and not (tmp_path / 'route-watch.json').exists()
    assert 'FAIL health: 503' in printed and 'PASS the app' in printed and len(printed) == len(rw.CHECKS)


@pytest.mark.parametrize('result, is_outage', [('ok', False), ('200', False), ('401 "Sign in required"', False),
                                               ('503', True), ('500 "boom"', True), ('no answer (TimeoutError)', True),
                                               ('no public address (OSError)', True)])
def test_what_counts_as_an_outage(result, is_outage):
    assert rw.outage(result) is is_outage
