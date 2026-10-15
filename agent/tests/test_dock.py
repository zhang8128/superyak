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
