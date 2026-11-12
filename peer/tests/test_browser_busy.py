"""The public-route-bound plan, Task 5: the page waits once. A 503 that carries x-superyak-busy was refused before the
home did anything (spec R3), so app.js's api() and consent.js's post() ask again once, after its Retry-After plus up to
1 s. A second marked 503 shows the error; a 503 without the mark (a proxy's, or the home's own failure) is never asked
again."""
from playwright.sync_api import expect, sync_playwright
import pytest

from test_browser import (browser_peer, connector_home, consent_browser, signed_out_browser,  # noqa: F401 - fixtures
                          start_connecting)

BUSY_ERROR = {'error': 'This home is busy; try again shortly'}


def answering(log, busy_times, marked=True):
    """A route handler: the first `busy_times` requests get a 503 (marked or not, Retry-After 0), the rest go on."""
    def handle(route):
        log.append(route.request.method)
        if len(log) <= busy_times:
            headers = {'retry-after': '0', **({'x-superyak-busy': '1'} if marked else {})}
            route.fulfill(status=503, json=BUSY_ERROR, headers=headers)
        else:
            route.fallback()
    return handle


def sign_in(page, peer):
    page.goto(peer['base_url'] + '/')
    page.get_by_label('Username', exact=True).fill('patient')
    page.get_by_label('Password', exact=True).fill(peer['password'])
    page.get_by_role('button', name='Sign in').click()


def test_the_app_asks_once_more_after_a_marked_503_and_signs_in(browser_peer):
    log = []
    with sync_playwright() as playwright:
        with signed_out_browser(playwright) as page:
            page.route('**/api/login', answering(log, 1))
            sign_in(page, browser_peer)
            expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
    assert log == ['POST', 'POST']


def test_the_app_shows_a_second_marked_503(browser_peer):
    log = []
    with sync_playwright() as playwright:
        with signed_out_browser(playwright) as page:
            page.route('**/api/login', answering(log, 2))
            sign_in(page, browser_peer)
            expect(page.get_by_text('This home is busy; try again shortly')).to_be_visible()
            page.wait_for_timeout(1500)  # past any second wait
    assert log == ['POST', 'POST']


def test_the_app_never_asks_again_after_an_unmarked_503(browser_peer):
    log = []
    with sync_playwright() as playwright:
        with signed_out_browser(playwright) as page:
            page.route('**/api/login', answering(log, 1, marked=False))
            sign_in(page, browser_peer)
            expect(page.get_by_text('This home is busy; try again shortly')).to_be_visible()
            page.wait_for_timeout(1500)  # a retry, had there been one, would have come by now
    assert log == ['POST']


def consent_sign_in(page):
    page.get_by_label('Username', exact=True).fill('sam@example.org')
    page.get_by_label('Password', exact=True).fill('long-password-sam')
    page.get_by_role('button', name='Sign in').click()


@pytest.mark.parametrize('busy_times, marked, shown, asked', [
    (1, True, 'Signed in as Sam Example', 2),
    (2, True, 'Your home is busy just now. Try again in a moment.', 2),
    (1, False, 'The connection to your home was lost. Try again.', 1),
])
def test_the_consent_page_asks_once_more_only_after_a_marked_503(connector_home, busy_times, marked, shown, asked):
    log, landed = [], []
    with sync_playwright() as playwright:
        with consent_browser(playwright, connector_home, landed) as page:
            start_connecting(page, connector_home)
            page.route('**/authorize/signin', answering(log, busy_times, marked))
            consent_sign_in(page)
            expect(page.get_by_text(shown)).to_be_visible()
            page.wait_for_timeout(1500)
    assert len(log) == asked


WAITS = """() => {
  const wait = (status, headers) => busyWait({ status, headers: new Headers(headers) });
  const marked = { 'x-superyak-busy': '1' };
  return {
    zero: wait(503, { ...marked, 'retry-after': '0' }), hour: wait(503, { ...marked, 'retry-after': '3600' }),
    junk: wait(503, { ...marked, 'retry-after': 'soon' }), none: wait(503, marked),
    unmarked: wait(503, { 'retry-after': '0' }), ok: wait(200, marked),
  };
}"""


def waits_are_bounded(waits):
    """Retry-After plus up to 1 s, at most 5 s of it; an unreadable or missing one is 1 s; unmarked or not a 503, none."""
    assert 0 <= waits['zero'] < 1000 and 5000 <= waits['hour'] < 6000
    assert 1000 <= waits['junk'] < 2000 and 1000 <= waits['none'] < 2000
    assert waits['unmarked'] is None and waits['ok'] is None


def test_the_apps_wait_is_its_retry_after_capped_at_5_s_plus_up_to_1_s(browser_peer):
    with sync_playwright() as playwright:
        with signed_out_browser(playwright) as page:
            page.goto(browser_peer['base_url'] + '/')
            expect(page.get_by_role('heading', name='Sign in to this home')).to_be_visible()
            waits_are_bounded(page.evaluate(WAITS))


def test_the_consent_pages_wait_is_bounded_the_same_way(connector_home):
    landed = []
    with sync_playwright() as playwright:
        with consent_browser(playwright, connector_home, landed) as page:
            start_connecting(page, connector_home)
            expect(page.get_by_label('Username', exact=True)).to_be_visible()
            waits_are_bounded(page.evaluate(WAITS))
