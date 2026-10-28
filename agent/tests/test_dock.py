import json
import pytest
from superyak_agent import dock
from superyak_agent.dock import Dock, open_browser


@pytest.fixture
def opened(monkeypatch):
    urls = []
    monkeypatch.setattr(dock.webbrowser, 'open', lambda url: urls.append(url) or True)
    for name in ('DISPLAY', 'WAYLAND_DISPLAY'):
        monkeypatch.delenv(name, raising=False)
    return urls


@pytest.mark.parametrize('platform, env, expected', [
    ('darwin', {}, True), ('win32', {}, True),
    ('linux', {}, False), ('linux', {'DISPLAY': ''}, False), ('freebsd14', {}, False),
    ('linux', {'DISPLAY': ':0'}, True), ('linux', {'WAYLAND_DISPLAY': 'wayland-0'}, True), ('freebsd14', {'DISPLAY': ':0'}, True)])
def test_the_default_opener_opens_a_browser_only_where_a_window_is_likely(monkeypatch, opened, platform, env, expected):
    # On a headless Linux box Python's webbrowser would start a console browser (lynx, w3m) on the terminal
    # that `make dock` is printing to; the URL is already in the printed instructions.
    monkeypatch.setattr(dock.sys, 'platform', platform)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    open_browser('https://station.example/#dock')
    assert opened == (['https://station.example/#dock'] if expected else [])


def test_the_default_opener_is_what_dock_uses_unless_one_is_injected():
    assert Dock('http://station.test').open_url is open_browser
    assert Dock('http://station.test', open_url=print).open_url is print


def test_the_code_and_instructions_are_printed_before_the_browser_opens(tmp_path):
    events = []

    def transport(method, url, headers, data):
        if url.endswith('/api/dockings') and method == 'POST':
            return 201, json.dumps({'id': 'd1', 'code': 'ABCD2345', 'secret': 's', 'expires': 5.0, 'confirm_url': 'http://station.test/#dock?code=ABCD2345'}).encode()
        return 401, b'{"error": "Sign in"}'   # /api/me: any HTTP answer means the station is reachable
    machine = Dock('http://station.test', ship='serenity', workspace=str(tmp_path), home=tmp_path / 'home', transport=transport,
                   out=lambda message: events.append(('say', message)), open_url=lambda url: events.append(('open', url)), machine='mac')
    assert machine.step() == 'waiting-for-confirm'
    assert [kind for kind, _ in events] == ['say', 'say', 'open']
    assert 'ABCD2345' in events[0][1] and events[1][1] == 'STATUS: waiting-for-confirm' and events[2][1] == 'http://station.test/#dock?code=ABCD2345'


def test_the_status_poll_sends_its_secret_in_a_header_not_the_url(tmp_path):
    """Public route spec 4: the docking secret never rides in a URL, where a log could keep it."""
    sent = []

    def transport(method, url, headers, data):
        sent.append((method, url, headers))
        if url.endswith('/api/dockings') and method == 'POST':
            return 201, json.dumps({'id': 'd1', 'code': 'ABCD2345', 'secret': 'the-secret', 'expires': 5.0,
                                    'confirm_url': 'http://station.test/#dock?code=ABCD2345'}).encode()
        if '/api/dockings/d1' in url:
            return 200, b'{"status": "waiting"}'
        return 401, b'{"error": "Sign in required"}'
    machine = Dock('http://station.test', ship='serenity', workspace=str(tmp_path), home=tmp_path / 'home', transport=transport,
                   out=lambda message: None, open_url=lambda url: None, machine='mac')
    assert machine.step() == 'waiting-for-confirm' and machine.step() == 'waiting-for-confirm'
    polls = [(url, headers) for method, url, headers in sent if '/api/dockings/d1' in url]
    assert polls and all('secret' not in url and headers['x-superyak-secret'] == 'the-secret' for url, headers in polls)
    assert all('x-superyak-secret' not in headers for method, url, headers in sent if '/api/dockings/d1' not in url)


REFUSED_PUBLIC = ("STATUS: refused-public (the station docks only over the tailnet. New here: install Tailscale, sign in, "
                  "and accept the station's share link. On one of Andy's machines: check that the station's name resolves "
                  "through MagicDNS)")


def public_station(pending_status=401):
    """A station reached by the public route: /api/me and a new docking get the middleware's 401 (spec 4)."""
    calls = []

    def transport(method, url, headers, data):
        calls.append((method, url))
        if '/api/dockings/d1' in url:
            return pending_status, (b'{"error": "Sign in required"}' if pending_status == 401 else b'{"status": "waiting"}')
        return 401, b'{"error": "Sign in required"}'
    return transport, calls


def test_a_docking_refused_on_the_public_route_ends_the_run_at_once_with_3(tmp_path):
    transport, calls = public_station()
    said, slept = [], []
    machine = Dock('http://station.test', ship='serenity', workspace=str(tmp_path), home=tmp_path / 'home', transport=transport,
                   out=said.append, open_url=lambda url: None, machine='mac', sleep=slept.append, clock=lambda: 0.0)
    assert machine.run(wait=540, poll=15) == 3
    assert said == [REFUSED_PUBLIC] and slept == []
    assert ('POST', 'http://station.test/api/dockings') in calls
    assert not (tmp_path / 'home' / 'station.json').exists() and not (tmp_path / 'home' / 'docking.json').exists()


def test_a_status_poll_refused_on_the_public_route_keeps_the_docking_and_ends_the_run(tmp_path):
    """A docking started over the tailnet, polled on a run that resolved the station publicly: the docking is kept for
    a run that takes the tailnet."""
    home = tmp_path / 'home'
    home.mkdir()
    pending = {'id': 'd1', 'code': 'ABCD2345', 'secret': 's', 'expires': 5.0, 'confirm_url': 'http://station.test/#dock?code=ABCD2345'}
    (home / 'docking.json').write_text(json.dumps(pending))
    transport, calls = public_station()
    said, slept = [], []
    machine = Dock('http://station.test', ship='serenity', workspace=str(tmp_path), home=home, transport=transport,
                   out=said.append, open_url=lambda url: None, machine='mac', sleep=slept.append, clock=lambda: 0.0)
    assert machine.run(wait=540, poll=15) == 3
    assert said == [REFUSED_PUBLIC] and slept == []
    assert json.loads((home / 'docking.json').read_text()) == pending
    assert not [call for call in calls if call[0] == 'POST']  # it never started another docking
