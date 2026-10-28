import time
import pytest
from superyak_agent.kick import Kick, kick_line
from superyak_agent.station import StationError


class Stop(BaseException):
    pass


def msg(event, mid, sender='tardis', **flags):
    return {'event_id': event, 'message_id': mid, 'room_title': 'City of AI', 'body': 'SECRET BODY',
            'author': {'username': sender, 'name': sender.title()}, **flags}


class FakeClient:
    """Answers come from a script: a dict is a reply, an exception is raised, Stop ends the loop."""
    def __init__(self, script):
        self.script, self.polls, self.advances = list(script), [], []

    def unread(self, cursor, limit=30, wait=0, breakouts=None):
        self.polls.append((cursor, limit, wait))
        step = self.script.pop(0) if self.script else Stop()
        if isinstance(step, BaseException):
            raise step
        return step

    def advance(self, cursor, to):
        self.advances.append((cursor, to))
        return {}


class Clock:
    def __init__(self):
        self.now, self.sleeps = 1_000_000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def run(script):
    client, clock, lines = FakeClient(script), Clock(), []
    kick = Kick(client, 'rio-grande', out=lines.append, clock=clock, sleep=clock.sleep)
    with pytest.raises(Stop):
        kick.run()
    return client, clock, lines


def test_both_kinds_of_kick_print_one_line_and_other_messages_nothing():
    batch = {'messages': [msg(1, 'm1', mentions_me=True), msg(2, 'm2', replies_to_me=True),
                          msg(3, 'm3'), msg(4, 'm4', mentions_me=False)]}
    client, _, lines = run([batch])
    assert lines == ['station: kick m1 in City of AI from tardis (mentions rio-grande)',
                     'station: kick m2 in City of AI from tardis (replies to rio-grande)']
    assert client.polls[0] == ('rio-grande-kick', 20, 25)


def test_the_cursor_advances_once_per_batch_to_the_last_event_id():
    client, _, _ = run([{'messages': [msg(5, 'a'), msg(6, 'b', mentions_me=True)]}, {'messages': []},
                        {'messages': [msg(9, 'c')]}])
    assert client.advances == [('rio-grande-kick', 6), ('rio-grande-kick', 9)]


def test_a_line_never_holds_the_body_and_fields_are_cleaned():
    bad = msg(1, 'm`1', sender='x\ny', mentions_me=True)
    bad['room_title'] = 'Room\nwith `fence`'
    _, _, lines = run([{'messages': [bad]}])
    assert len(lines) == 1 and '\n' not in lines[0] and '`' not in lines[0] and 'SECRET' not in lines[0]
    assert 'SECRET BODY' not in kick_line(bad, 'rio-grande')


def test_a_short_outage_prints_nothing_and_backs_off():
    down = StationError(502, 'down')
    _, clock, lines = run([down, down, down, {'messages': []}])
    assert lines == [] and clock.sleeps == [5, 10, 20]


def test_a_long_outage_prints_one_unreachable_and_one_back_line():
    down = OSError('refused')
    client, clock, lines = run([down] * 5 + [{'messages': [msg(1, 'm1', mentions_me=True)]}])
    started = time.strftime('%H:%M', time.localtime(1_000_000.0))
    assert clock.sleeps == [5, 10, 20, 40, 80]
    assert lines == [f'kick: station unreachable since {started}', 'kick: station back',
                     'station: kick m1 in City of AI from tardis (mentions rio-grande)']


def test_backoff_is_capped_and_a_429_honors_retry_after():
    limited = StationError(429, 'slow down')
    limited.retry_after = 42
    _, clock, _ = run([limited, {'messages': []}])
    assert clock.sleeps == [42]
    _, clock, _ = run([OSError()] * 9)
    assert max(clock.sleeps) == 300
