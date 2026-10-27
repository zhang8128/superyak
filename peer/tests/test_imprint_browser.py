"""The imprint confirm view and Accounts, Imprints, in a real browser (spec I 8, 9, 12)."""
import socket
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from imprint_support import post, request_doc, seed_imprint, station
from superyak_peer.imprints import CHECK_TEXT, CHECK_TEXT_AT_HOME, CHECK_TEXT_AT_HOME_NONE

SAM_PASSWORD, ANDY_PASSWORD = 'long-password-sam', 'long-password-andy'


@pytest.fixture
def imprint_browser(tmp_path, chromium, request):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    st = station(tmp_path, allowed_origins=('http://testserver', url), **getattr(request, 'param', {}))
    server = uvicorn.Server(uvicorn.Config(st.app, host='127.0.0.1', port=port, log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            urlopen(url + '/', timeout=2)
            break
        except HTTPError:
            break
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.05)
    else:
        pytest.fail('browser test server did not start')

    def request(ship='voyager', **changes):
        if changes.get('others', {}).get('memories'):   # I 7.1: the rows the others come from are counted
            changes['contents.imprint_subjects'] = changes['others']['memories'] + 3
        response = post(st, request_doc(**changes), ship=ship)
        assert response.status_code == 201, response.text
        return response.json()

    def admitted(owner='sam'):
        return seed_imprint(st, status='admitted', owner=owner)

    yield SimpleNamespace(url=url, station=st, request=request, admitted=admitted, browser=chromium)
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def chromium():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


def signed_in(imprint_browser, username):
    page = imprint_browser.browser.new_context(viewport={'width': 1440, 'height': 960}).new_page()
    page.goto(imprint_browser.url + '/')
    page.get_by_label('Username', exact=True).fill(username)
    page.get_by_label('Password', exact=True).fill('long-password-' + username)
    page.get_by_role('button', name='Sign in').click()
    expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
    return page


def test_the_confirm_view_needs_the_check_and_the_password(imprint_browser):
    page = signed_in(imprint_browser, 'sam'); made = imprint_browser.request()
    page.goto(f"{imprint_browser.url}/#imprint?code={made['code']}")
    expect(page.get_by_text('the whole 64-character digest is sent')).to_be_visible()
    expect(page.get_by_text('when either was last recalled')).to_be_visible()
    page.get_by_label('Password').fill(SAM_PASSWORD); page.get_by_role('button', name='Allow').click()
    expect(page.get_by_text('Tick the box')).to_be_visible()
    page.get_by_label(CHECK_TEXT).check(); page.get_by_role('button', name='Allow').click()
    expect(page.get_by_text('Allowed')).to_be_visible()


def test_the_operators_own_copy_shows_the_counts_and_the_acknowledgment(imprint_browser):
    page = signed_in(imprint_browser, 'andy')
    made = imprint_browser.request(ship='serenity', others={'memories': 37, 'people': 3})
    page.goto(f"{imprint_browser.url}/#imprint?code={made['code']}")
    expect(page.get_by_text('37 of these memories have other people recorded on them (3 people)')).to_be_visible()
    page.get_by_label(CHECK_TEXT_AT_HOME.format(n=37, p=3)).check()
    page.get_by_label('Password').fill(ANDY_PASSWORD); page.get_by_role('button', name='Allow').click()
    expect(page.get_by_text('Allowed')).to_be_visible()


def test_the_operators_own_copy_at_n_0_promises_no_co_subject(imprint_browser):   # I 8, M2; the re-check's S5
    page = signed_in(imprint_browser, 'andy')
    made = imprint_browser.request(ship='serenity', others={'memories': 0, 'people': 0})
    page.goto(f"{imprint_browser.url}/#imprint?code={made['code']}")
    expect(page.get_by_label(CHECK_TEXT_AT_HOME_NONE)).to_be_visible()
    expect(page.get_by_text('co-subjects')).to_have_count(0)


def test_accounts_imprints_withdraw(imprint_browser):
    page = signed_in(imprint_browser, 'sam'); imprint_browser.admitted()
    page.goto(f'{imprint_browser.url}/#accounts'); page.get_by_role('button', name='Withdraw').click()
    page.get_by_role('button', name='Yes, withdraw').click()
    expect(page.get_by_text('deleted')).to_be_visible()


@pytest.mark.parametrize('imprint_browser', [{'imprints_dir': None}], indirect=True)
def test_without_the_imprint_routes_the_accounts_section_is_not_shown(imprint_browser):   # R8
    page = signed_in(imprint_browser, 'sam')
    expect(page.get_by_role('link', name='Accounts')).to_have_count(0)
    page.goto(f'{imprint_browser.url}/#accounts')
    expect(page.get_by_role('heading', name='Imprints')).to_have_count(0)


def test_a_wrong_password_keeps_the_view_open_and_declining_sends_nothing(imprint_browser):
    page = signed_in(imprint_browser, 'sam'); made = imprint_browser.request()
    page.goto(f"{imprint_browser.url}/#imprint?code={made['code']}")
    page.get_by_label(CHECK_TEXT).check(); page.get_by_label('Password').fill('not the password')
    page.get_by_role('button', name='Allow').click()
    expect(page.get_by_text('Invalid password')).to_be_visible()
    page.get_by_role('button', name='Decline').click()
    expect(page.get_by_text('Declined')).to_be_visible()
    assert imprint_browser.station.store.list_imprints(imprint_browser.station.ids['sam'])[0]['status'] == 'declined'
