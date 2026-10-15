"""Real-browser acceptance flows for the same-origin personal home."""

from contextlib import contextmanager
import json
import os
import tempfile
from pathlib import Path
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from superyak_peer.app import create_app
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import PeerIdentity


def open_new_layer(page):
    """Click "New layer" and wait for the new layer's own editor. The click creates the layer on the server before the
    editor opens, so anything typed in between lands in the editor that was already open (this made the instructions
    test save and activate a blank layer about 1 run in 8)."""
    before = page.url
    page.get_by_role("button", name="New layer").click()
    page.wait_for_url(lambda url: url != before and "#layers/" in url)
    expect(page.get_by_label("Layer title")).to_have_value("Untitled")



# A unique run directory preserves prior screenshots and works in extracted source.
ARTIFACTS = Path(tempfile.mkdtemp(prefix="superyak-browser-", dir=os.environ.get("SUPERYAK_TEST_ARTIFACTS")))



@pytest.fixture
def browser_peer(tmp_path, request):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    local_demo = getattr(request, "param", False)
    if local_demo:
        from superyak_peer.__main__ import seed_demo
        seed_demo(tmp_path / "browser-peer")
    app = create_app(tmp_path / "browser-peer", allowed_origins=[base_url], local_demo=local_demo)
    store = app.state.store
    password = "long-browser-password"
    users = {} if local_demo else {
        username: store.create_user(
            username, name, password, is_admin=username == "organizer"
        )
        for username, name in (
            ("patient", "Alex Patient"),
            ("family", "Sam Family"),
            ("doctor", "Dr. Morgan"),
            ("organizer", "Taylor Organizer"),
        )
    }
    if local_demo:
        with store.transaction() as db:
            users = {row['username']: dict(row) for row in db.execute('SELECT id,username,name FROM users')}
    store.create_space(
        users["patient"]["id"],
        "Alex’s care circle",
        "care-circle",
        [users["family"]["id"], users["doctor"]["id"]],
    )
    remote_store = Store(tmp_path / "remote-peer")
    remote_user = remote_store.create_user(  # the stand-in station's admin, so it can pair back
        "casey", "Casey Remote", "long-remote-password", is_admin=True
    )
    remote_identity = PeerIdentity.load_or_create(
        remote_store.data_dir, hosts=("remote.example",)
    )
    remote_federation = Federation(
        remote_store,
        endpoint="https://remote.example:7443",
        identity=remote_identity,
    )
    remote_card = remote_federation.card(remote_user["id"])
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            urlopen(base_url + "/", timeout=2)
            break
        except HTTPError:
            break
        except (URLError, TimeoutError, ConnectionError):
            # A loaded Pi can take longer than one attempt for the first page; a read that times out raises a bare
            # TimeoutError, not a URLError, so it is retried until the deadline like a refused connect.
            time.sleep(0.05)
    else:
        pytest.fail("browser test server did not start")
    yield {
        "base_url": base_url,
        "password": password,
        "users": users,
        "app": app,
        "remote_card": remote_card,
        "remote": {"store": remote_store, "federation": remote_federation, "user": remote_user},
        "local_demo": local_demo,
    }
    server.should_exit = True
    thread.join(timeout=10)


@contextmanager
def signed_in_browser(playwright, peer, username, *, viewport=None):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport=viewport or {"width": 1440, "height": 960})
    page = context.new_page()
    page.goto(peer["base_url"] + "/")
    expect(page.get_by_role("heading", name="Sign in to your home")).to_be_visible()
    page.get_by_label("Username", exact=True).fill(username)
    page.get_by_label("Password", exact=True).fill(peer["password"])
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
    page.evaluate("scrollTo(0, 0)")
    page.wait_for_timeout(100)
    try:
        yield page, context
    finally:
        context.close()
        browser.close()


@contextmanager
def signed_out_browser(playwright, *, viewport=None):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport=viewport or {"width": 1200, "height": 900})
    try:
        yield context.new_page()
    finally:
        context.close()
        browser.close()


def test_source_library_import_pause_and_private_review(browser_peer):
    store = browser_peer['app'].state.store
    actor = browser_peer['users']['patient']['id']
    original = store.create_layer(actor, {'title': 'Fictional study', 'body': 'Observation with important limitations.'})
    from superyak_peer.interchange import Interchange
    document = Interchange(store, 'fixture-peer').export(actor, {
        'selections': [{'layer_id': original['id'], 'kind': 'draft', 'version': 1}]})
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        page.get_by_role('link', name='Research & data', exact=True).click()
        page.get_by_role('button', name='New source', exact=True).click()
        page.get_by_label('Source name', exact=True).fill('Evidence for our project')
        page.get_by_label('Source type', exact=True).select_option('selected-records')
        page.get_by_role('button', name='Create source', exact=True).click()
        expect(page.get_by_role('heading', name='Evidence for our project', exact=True)).to_be_visible()
        page.get_by_label('Select source document', exact=True).set_input_files({
            'name': 'evidence.json', 'mimeType': 'application/json', 'buffer': json.dumps(document).encode()})
        expect(page.get_by_role('heading', name='Review this import')).to_be_visible()
        assert browser_peer['app'].state.data_sources.list(actor)['sources'][0]['item_count'] == 0
        page.get_by_role('button', name='Import privately', exact=True).click()
        expect(page.get_by_role('heading', name='Fictional study', exact=True)).to_be_visible()
        page.get_by_role('button', name='Pause imports', exact=True).click()
        expect(page.get_by_role('button', name='Resume imports', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='Fictional study', exact=True)).to_be_visible()
        page.get_by_role('button', name='Start evidence review', exact=True).click()
        expect(page.get_by_label('Layer title')).to_have_value('Review: Fictional study')
        expect(page.get_by_label('What do you want to share?')).to_contain_text('Observation with important limitations.')
        layer = next(x for x in store.list_layers(actor) if x['title'] == 'Review: Fictional study')
        assert not layer['public'] and not layer['audience_users'] and not layer['audience_spaces'] and not layer['active_revision']
        assert store.shared_layers(browser_peer['users']['doctor']['id']) == []


def test_source_library_conflict_keeps_correction_and_does_not_overwrite(browser_peer):
    service = browser_peer['app'].state.data_sources
    actor = browser_peer['users']['patient']['id']
    source = service.create(actor, {'name': 'Original source', 'kind': 'file'})
    other = service.create(actor, {'name': 'Another source', 'kind': 'file'})
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        page.goto(browser_peer['base_url'] + '/#research/' + source['id'])
        page.get_by_text('Edit source details', exact=True).click()
        page.get_by_label('Source name', exact=True).fill('My correction')
        service.update(actor, source['id'], {'version': 1, 'name': 'Correction from another tab'})
        page.get_by_role('link', name='Another source', exact=False).click()
        expect(page.get_by_role('heading', name='Another source', exact=True)).to_be_visible()
        page.goto(browser_peer['base_url'] + '/#research/' + source['id'])
        expect(page.get_by_role('heading', name='Correction from another tab', exact=True)).to_be_visible()
        page.get_by_role('button', name='Save source details', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='changed')).to_be_visible()
        expect(page.get_by_label('Source name', exact=True)).to_have_value('My correction')
        assert service.get(actor, source['id'])['name'] == 'Correction from another tab'
        page.get_by_role('button', name='Load latest source settings', exact=True).click()
        expect(page.get_by_role('heading', name='Correction from another tab', exact=True)).to_be_visible()
        expect(page.get_by_label('Source name', exact=True)).to_have_value('My correction')
        page.get_by_role('button', name='Save source details', exact=True).click()
        expect(page.get_by_role('heading', name='My correction', exact=True)).to_be_visible()
        assert service.get(actor, source['id'])['name'] == 'My correction'
        page.get_by_role('button', name='New source', exact=True).click()
        dialog = page.get_by_role('dialog')
        dialog.get_by_label('Source name', exact=True).fill('New collection from this page')
        dialog.get_by_label('Description', exact=True).fill('Separate source settings')
        dialog.get_by_role('button', name='Create source', exact=True).click()
        expect(page.get_by_role('heading', name='New collection from this page', exact=True)).to_be_visible()


def test_space_page_requires_member_preview_and_keeps_private_drafts_out(browser_peer):
    store = browser_peer['app'].state.store
    actor = browser_peer['users']['patient']['id']
    family = browser_peer['users']['family']['id']
    space = store.create_space(actor, 'Wilhelm hackathon', 'organization')
    private = store.create_layer(actor, {'title': 'Not an organization update', 'body': 'private'})
    release = store.create_layer(actor, {'title': 'Project introduction', 'body': 'Shared project', 'audience_spaces': [space['id']]})
    store.activate_layer(actor, release['id'], 1)
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        page.get_by_role('link', name='Wilhelm hackathon', exact=True).click()
        expect(page.get_by_role('heading', name='Wilhelm hackathon', exact=True, level=1)).to_be_visible()
        expect(page.get_by_role('button', name='Project introduction', exact=False)).to_be_visible()
        assert private['title'] not in page.locator('#main-content').inner_text()
        page.get_by_label('Person to add', exact=True).select_option(family)
        page.get_by_role('button', name='Review adding person', exact=True).click()
        expect(page.get_by_role('dialog')).to_contain_text('Sam Family')
        expect(page.get_by_role('dialog')).to_contain_text('active releases')
        assert family not in store.get_space(actor, space['id'])['member_ids']
        page.route('**/api/spaces/*/members', lambda route: route.abort('failed'))
        page.get_by_role('button', name='Add this person', exact=True).click()
        expect(page.get_by_role('dialog')).to_contain_text('Connection lost')
        assert family not in store.get_space(actor, space['id'])['member_ids']
        page.unroute('**/api/spaces/*/members')
        page.get_by_role('button', name='Add this person', exact=True).click()
        expect(page.get_by_role('button', name='Remove Sam Family', exact=True)).to_be_visible()
        assert family in store.get_space(actor, space['id'])['member_ids']
        assert [x['title'] for x in store.shared_layers(family)] == ['Project introduction']


def test_home_search_and_private_starters_preserve_account_boundaries(browser_peer):
    store = browser_peer['app'].state.store
    actor = browser_peer['users']['patient']['id']
    store.create_layer(actor, {'title': 'My zebra questions', 'body': 'Selected private notes'})
    store.create_layer(browser_peer['users']['doctor']['id'], {'title': 'Secret zebra case', 'body': 'Hidden'})
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        page.get_by_label('Search your home', exact=True).fill('zebra')
        page.get_by_role('button', name='Search', exact=True).click()
        expect(page.get_by_role('link', name='My zebra questions', exact=False)).to_be_visible()
        assert 'Secret zebra case' not in page.content()
        page.get_by_role('link', name='Home', exact=True).click()
        page.get_by_role('button', name='Prepare care questions', exact=True).click()
        expect(page.get_by_label('Layer title')).to_have_value('Questions for my care team')
        draft = next(x for x in store.list_layers(actor) if x['title'] == 'Questions for my care team')
        assert not draft['active_revision'] and not draft['audience_spaces'] and not draft['public']
        page.get_by_label('What do you want to share?').fill('Keep these words while I browse')
        page.get_by_role('link', name='Home', exact=True).click()
        page.get_by_role('link', name='Questions for my care team', exact=False).first.click()
        expect(page.get_by_label('What do you want to share?')).to_have_value('Keep these words while I browse')


def test_source_library_file_retry_replays_accepted_import(browser_peer):
    service = browser_peer['app'].state.data_sources
    actor = browser_peer['users']['patient']['id']
    source = service.create(actor, {'name': 'Clinical files', 'kind': 'file'})
    csv = b'participant,value\nfictional-1,3.5\n'
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        page.goto(browser_peer['base_url'] + '/#research/' + source['id'])
        page.get_by_label('Select files', exact=True).set_input_files({'name': 'fictional.csv', 'mimeType': 'text/csv', 'buffer': csv})
        expect(page.get_by_role('heading', name='Review this import')).to_be_visible()
        attempts = []
        def lose_first_ack(route):
            if route.request.method == 'POST' and not attempts:
                response = route.fetch()
                assert response.status == 201
                attempts.append(True)
                route.abort('failed')
            else:
                route.continue_()
        page.route('**/api/data-sources/*/imports', lose_first_ack)
        page.get_by_role('button', name='Import privately', exact=True).click()
        expect(page.get_by_role('dialog')).to_contain_text('Connection lost')
        first = service.history(actor, source['id'])['imports']
        assert len(first) == 1 and first[0]['status'] == 'succeeded'
        page.get_by_role('button', name='Import privately', exact=True).click()
        expect(page.get_by_role('heading', name='fictional.csv', exact=True)).to_be_visible()
        assert service.history(actor, source['id'])['imports'] == first
        file = service.items(actor, source['id'])['items'][0]['file']
        assert browser_peer['app'].state.store.download_file(actor, file['id'])['content'] == csv


def test_space_context_and_display_preferences_work_on_mobile(browser_peer):
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient', viewport={'width': 390, 'height': 844}) as (page, _):
        page.get_by_role('button', name='Display & help', exact=True).click()
        page.get_by_label('Larger text', exact=True).check()
        page.get_by_label('Quieter view', exact=True).check()
        page.get_by_role('button', name='Back to my home', exact=True).click()
        page.reload()
        expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.classList.contains('large-text')")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert page.locator('nav[aria-label="Main navigation"] a').evaluate_all("nodes => nodes.every(node => node.getBoundingClientRect().bottom <= innerHeight)")
        circle = browser_peer['app'].state.store.list_spaces(browser_peer['users']['patient']['id'])[0]
        page.get_by_label('Current space').select_option(circle['id'])
        expect(page.get_by_role('heading', name=circle['name'], level=1)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def delay_next_patch_response(page):
    page.evaluate("""() => {
      const original = window.fetch;
      window.fetch = async (url, options = {}) => {
        const response = await original(url, options);
        if (options.method === 'PATCH' && !window.__patchHeld) {
          window.__patchHeld = true;
          await new Promise(resolve => { window.__releasePatch = resolve; });
        }
        return response;
      };
    }""")


def test_source_save_keeps_newer_typing_and_does_not_replace_another_source(browser_peer):
    service = browser_peer['app'].state.data_sources
    actor = browser_peer['users']['patient']['id']
    first = service.create(actor, {'name': 'First collection', 'kind': 'file'})
    second = service.create(actor, {'name': 'Second collection', 'kind': 'file'})
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        page.goto(browser_peer['base_url'] + '/#research/' + first['id'])
        page.get_by_text('Edit source details', exact=True).click()
        page.get_by_label('Source name', exact=True).fill('Submitted correction')
        delay_next_patch_response(page)
        page.get_by_role('button', name='Save source details', exact=True).click()
        page.wait_for_function('() => window.__patchHeld === true')
        page.get_by_label('Source name', exact=True).fill('Newer unsaved words')
        page.get_by_role('link', name='Second collection', exact=False).click()
        expect(page.get_by_role('heading', name='Second collection', exact=True)).to_be_visible()
        page.evaluate('() => window.__releasePatch()')
        expect(page.get_by_role('button', name='Pause imports', exact=True)).to_be_enabled()
        expect(page.get_by_role('heading', name='Second collection', exact=True)).to_be_visible()
        page.goto(browser_peer['base_url'] + '/#research/' + first['id'])
        expect(page.get_by_role('heading', name='Submitted correction', exact=True)).to_be_visible()
        expect(page.get_by_label('Source name', exact=True)).to_have_value('Newer unsaved words')
        assert service.get(actor, first['id'])['name'] == 'Submitted correction'


def test_space_name_save_preserves_words_typed_while_saving(browser_peer):
    store = browser_peer['app'].state.store
    actor = browser_peer['users']['patient']['id']
    space = store.create_space(actor, 'Original project', 'project')
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        page.goto(browser_peer['base_url'] + '/#spaces/' + space['id'])
        page.get_by_text("Correct this space's name", exact=True).click()
        page.get_by_label('Space name', exact=True).fill('Submitted project name')
        delay_next_patch_response(page)
        page.get_by_role('button', name='Save name correction', exact=True).click()
        page.wait_for_function('() => window.__patchHeld === true')
        page.get_by_label('Space name', exact=True).fill('More accurate unsaved name')
        page.evaluate('() => window.__releasePatch()')
        expect(page.get_by_role('heading', name='Submitted project name', level=1)).to_be_visible()
        expect(page.get_by_label('Space name', exact=True)).to_have_value('More accurate unsaved name')


def test_late_home_refresh_cannot_replace_the_next_accounts_data(browser_peer):
    store = browser_peer['app'].state.store
    store.create_layer(browser_peer['users']['patient']['id'], {'title': 'Patient-only private title'})
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        page.evaluate("""() => {
          const original = window.fetch;
          window.fetch = async (url, options) => {
            const response = await original(url, options);
            if (url === '/api/home' && !window.__homeHeld) {
              window.__homeHeld = true;
              await new Promise(resolve => { window.__releaseHome = resolve; });
            }
            return response;
          };
          window.__oldRefresh = loadData();
        }""")
        page.wait_for_function('() => window.__homeHeld === true')
        page.get_by_role('button', name='Account and sign out').click()
        page.get_by_role('button', name='Sign out', exact=True).click()
        expect(page.get_by_role('heading', name='Sign in to your home')).to_be_visible()
        page.get_by_label('Username', exact=True).fill('doctor')
        page.get_by_label('Password', exact=True).fill(browser_peer['password'])
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
        page.evaluate('async () => { window.__releaseHome(); await window.__oldRefresh; render(); }')
        expect(page.get_by_role('button', name='Account and sign out')).to_contain_text('Dr. Morgan')
        assert 'Patient-only private title' not in page.content()


def test_opening_space_and_release_rechecks_withdrawal(browser_peer):
    store = browser_peer['app'].state.store
    actor = browser_peer['users']['patient']['id']
    family = browser_peer['users']['family']['id']
    space = store.create_space(actor, 'Research team', 'organization', [family])
    layer = store.create_layer(actor, {'title': 'Withdrawn evidence', 'body': 'Earlier shared words', 'audience_spaces': [space['id']]})
    store.activate_layer(actor, layer['id'], 1)
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'family') as (page, _):
        store.withdraw_layer(actor, layer['id'])
        page.get_by_role('link', name='Research team', exact=True).click()
        expect(page.get_by_role('heading', name='Research team', exact=True, level=1)).to_be_visible()
        assert 'Withdrawn evidence' not in page.locator('#main-content').inner_text()
        page.goto(browser_peer['base_url'] + '/#shared/' + layer['id'])
        expect(page.get_by_role('heading', name='Shared spaces', exact=True, level=1)).to_be_visible()
        assert 'Earlier shared words' not in page.locator('#main-content').inner_text()


def test_typing_during_source_navigation_stays_with_its_original_form(browser_peer):
    service = browser_peer['app'].state.data_sources
    actor = browser_peer['users']['patient']['id']
    first = service.create(actor, {'name': 'First source', 'kind': 'file'})
    second = service.create(actor, {'name': 'Second source', 'kind': 'file'})
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(browser_peer['base_url'] + '/#research/' + first['id'])
        page.get_by_text('Edit source details', exact=True).click()
        page.evaluate("""id => {
          const original = window.fetch;
          window.fetch = async (url, options) => {
            const response = await original(url, options);
            if (url === '/api/data-sources/' + id && !window.__sourceHeld) {
              window.__sourceHeld = true;
              await new Promise(resolve => { window.__releaseSource = resolve; });
            }
            return response;
          };
        }""", second['id'])
        page.get_by_role('link', name='Second source', exact=False).click()
        page.wait_for_function('() => window.__sourceHeld === true')
        page.get_by_label('Source name', exact=True).fill('Words for the first source')
        page.evaluate('() => window.__releaseSource()')
        expect(page.get_by_role('heading', name='Second source', exact=True)).to_be_visible()
        page.goto(browser_peer['base_url'] + '/#research/' + first['id'])
        expect(page.get_by_role('heading', name='First source', exact=True)).to_be_visible()
        expect(page.get_by_label('Source name', exact=True)).to_have_value('Words for the first source')
        assert errors == []


@pytest.mark.parametrize('browser_peer', [True], indirect=True)
def test_local_demo_opens_without_password_switches_accounts_and_renews_session(browser_peer):
    with sync_playwright() as playwright:
        with signed_out_browser(playwright) as page:
            page.goto(browser_peer['base_url'] + '/')
            expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='Account and sign out')).to_contain_text('Alex Patient')
            page.get_by_role('link', name='My sharing layers').click()
            page.get_by_role('button', name='New layer').click()
            expect(page.get_by_label('Layer title')).to_have_value('Untitled')
            page.get_by_label('What do you want to share?').fill('Patient unsaved words')
            page.get_by_role('button', name='Account and sign out').click()
            page.get_by_role('button', name='Try doctor', exact=True).click()
            expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='Account and sign out')).to_contain_text('Dr. Morgan')
            assert 'Patient unsaved words' not in page.content()
            assert page.request.get(browser_peer['base_url'] + '/api/me').json()['username'] == 'doctor'

            page.get_by_role('link', name='My sharing layers').click()
            page.get_by_role('button', name='New layer').click()
            expect(page.get_by_label('Layer title')).to_have_value('Untitled')
            page.get_by_label('What do you want to share?').fill('Doctor draft survives session expiry')
            browser_peer['app'].state.store.clock = lambda: time.time() + 86401
            page.get_by_role('button', name='Save private draft').click()
            expect(page.get_by_role('heading', name='Sign in again to keep working')).to_be_visible()
            expect(page.get_by_label('Password', exact=True)).to_have_count(0)
            page.get_by_role('button', name='Sign in again', exact=True).click()
            expect(page.locator('#main-content').get_by_text('Signed in again. Your unsaved text is ready to save.', exact=True)).to_be_visible()
            expect(page.get_by_label('What do you want to share?')).to_have_value('Doctor draft survives session expiry')
            page.get_by_role('button', name='Save private draft').click()
            expect(page.locator('#main-content').get_by_text('Private draft saved')).to_be_visible()
            page.get_by_role('button', name='Account and sign out').click()
            page.get_by_role('button', name='Sign out', exact=True).click()
            expect(page.get_by_role('button', name='Try family', exact=True)).to_be_visible()
            page.get_by_role('button', name='Try family', exact=True).click()
            expect(page.get_by_role('button', name='Account and sign out')).to_contain_text('Sam Family')
        with signed_out_browser(playwright) as public:
            public.goto(browser_peer['base_url'] + '/public/')
            expect(public.get_by_role('heading', name='Public view')).to_be_visible()
            assert public.request.get(browser_peer['base_url'] + '/api/me').status == 401


def test_private_draft_exact_release_public_route_and_withdrawal(browser_peer):
    """Break caught: a draft or wrong revision becomes visible before activation."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (patient, _):
            patient.get_by_role("link", name="My sharing layers").click()
            expect(
                patient.get_by_text(
                    "Build your sharing layers at your own pace. Save them privately, "
                    "see what each audience would see, and turn them on when you're ready."
                )
            ).to_be_visible()
            open_new_layer(patient)
            patient.get_by_label("Layer title").fill("A steady update")
            patient.get_by_label("What do you want to share?").fill(
                "The first words chosen for my family."
            )
            patient.get_by_role("checkbox", name="Sam Family").check()
            patient.get_by_role("button", name="Save private draft").click()
            expect(patient.locator("#main-content").get_by_text("Private draft saved")).to_be_visible()

            patient.reload()
            expect(patient.get_by_label("Layer title")).to_have_value("A steady update")
            expect(patient.get_by_label("What do you want to share?")).to_have_value(
                "The first words chosen for my family."
            )

            with signed_in_browser(playwright, browser_peer, "family") as (family, _):
                family.get_by_role("link", name="Shared spaces", exact=True).click()
                expect(family.get_by_text("A steady update", exact=True)).to_have_count(0)

                patient.get_by_role("button", name="Preview audience").click()
                expect(patient.get_by_role("heading", name="Preview version 2")).to_be_visible()
                expect(
                    patient.get_by_role("dialog").get_by_text("Sam Family", exact=True)
                ).to_be_visible()
                patient.get_by_role("button", name="Turn on version 2").click()
                expect(patient.get_by_text("Active · version 2")).to_be_visible()

                family.reload()
                family.get_by_text("A steady update", exact=True).click()
                expect(family.get_by_text("The first words chosen for my family.")).to_be_visible()

                patient.get_by_label("What do you want to share?").fill(
                    "The next words I chose for this update."
                )
                patient.get_by_role("button", name="Save private draft").click()
                expect(patient.get_by_text("Unpublished changes")).to_be_visible()
                family.reload()
                expect(family.get_by_text("The first words chosen for my family.")).to_be_visible()
                expect(family.get_by_text("The next words I chose for this update.")).to_have_count(0)

                patient.get_by_role("checkbox", name="Anyone with the public link").check()
                patient.get_by_role("button", name="Save private draft").click()
                expect(patient.get_by_text("Saved version 4", exact=True)).to_be_visible()
                patient.get_by_role("button", name="Preview audience").click()
                patient.get_by_role("button", name="Turn on version 4").click()
                visitor_href = patient.get_by_role("link", name="View as a visitor").get_attribute(
                    "href"
                )
                assert visitor_href
                with signed_out_browser(playwright) as visitor:
                    visitor.goto(browser_peer["base_url"] + visitor_href)
                    expect(visitor.get_by_role("heading", name="A steady update")).to_be_visible()
                    expect(visitor.get_by_text("The next words I chose for this update.")).to_be_visible()
                    visitor.screenshot(path=str(ARTIFACTS / "public-release.png"))

                    patient.get_by_role("button", name="Turn off public link").click()
                    expect(
                        patient.locator("#main-content").get_by_text("Named sharing is still on")
                    ).to_be_visible()
                    visitor.reload()
                    expect(visitor.get_by_role("heading", name="This page is not shared")).to_be_visible()

                family.reload()
                expect(family.get_by_text("The next words I chose for this update.")).to_be_visible()
                patient.get_by_role("button", name="Stop all sharing").click()
                patient.get_by_role("button", name="Yes, stop all sharing").click()
                expect(
                    patient.locator("#main-content .notice").get_by_text("Sharing is off")
                ).to_be_visible()
                family.reload()
                expect(family.get_by_text("A steady update", exact=True)).to_have_count(0)

            patient.evaluate("scrollTo(0, 0)")
            patient.screenshot(path=str(ARTIFACTS / "sharing-layer-desktop.png"))


def test_chat_keeps_unsent_text_and_membership_change_starts_empty_room(browser_peer):
    """Break caught: a network error drops text or exposes old messages to a new member."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, context):
            page.get_by_role("link", name="Chats", exact=True).click()
            page.get_by_role("button", name="New private chat").click()
            page.get_by_label("Chat title").fill("Care planning")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("checkbox", name="Dr. Morgan").check()
            page.get_by_role("button", name="Create chat").click()
            page.get_by_role("textbox", name="Message", exact=True).fill("This belongs to the original room.")
            page.get_by_role("button", name="Send message").click()
            expect(page.get_by_text("This belongs to the original room.")).to_be_visible()

            page.get_by_role("textbox", name="Message", exact=True).fill("Keep this through a connection problem.")
            context.set_offline(True)
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text("Connection lost. Your message is still here.")
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value(
                "Keep this through a connection problem."
            )
            context.set_offline(False)
            page.reload()
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value(
                "Keep this through a connection problem."
            )
            page.get_by_role("button", name="Send message").click()
            expect(page.get_by_text("Keep this through a connection problem.")).to_be_visible()

            page.get_by_role("button", name="Change participants").click()
            page.get_by_role("checkbox", name="Taylor Organizer").check()
            page.get_by_role("button", name="Start a new linked chat").click()
            expect(page.get_by_text("New room · earlier messages stay in the original chat")).to_be_visible()
            expect(page.get_by_text("This belongs to the original room.")).to_have_count(0)


def test_mobile_home_and_admin_account_support_are_real_server_views(browser_peer):
    """Break caught: narrow layouts clip navigation or admin UI implies content access."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        with signed_in_browser(
            playwright,
            browser_peer,
            "organizer",
            viewport={"width": 390, "height": 844},
        ) as (page, _):
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.evaluate("scrollTo(0, 0)")
            page.wait_for_timeout(100)
            page.screenshot(path=str(ARTIFACTS / "home-mobile.png"))
            page.get_by_role("link", name="Connections", exact=True).click()
            expect(page.get_by_role("heading", name="Account support")).to_be_visible()
            expect(page.get_by_text("Account support does not open private chats or drafts.")).to_be_visible()
            page.get_by_role("button", name="Create invitation").click()
            # Exact: the access-requests panel also reads "Approving creates a one-use invitation …" once it loads.
            expect(page.get_by_text("One-use invitation", exact=True)).to_be_visible()
            page.get_by_role("button", name="Show my peer card").click()
            expect(
                page.locator("#main-content").get_by_text(
                    "Configure this peer HTTPS endpoint before exporting a card"
                )
            ).to_be_visible()
            page.screenshot(path=str(ARTIFACTS / "connections-mobile.png"))


def test_attachment_stays_selected_through_upload_and_public_release(browser_peer):
    """Break caught: uploading a file resets unsaved text or omits the selected release file."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            open_new_layer(page)
            page.get_by_label("Layer title").fill("Documents I chose")
            page.get_by_label("What do you want to share?").fill("A note with one file.")
            page.get_by_role("checkbox", name="Anyone with the public link").check()
            page.locator("#file-upload").set_input_files(
                {
                    "name": "care-note.txt",
                    "mimeType": "text/plain",
                    "buffer": b"A deliberately selected attachment.",
                }
            )
            expect(page.get_by_text("care-note.txt uploaded")).to_be_visible()
            expect(page.get_by_label("Layer title")).to_have_value("Documents I chose")
            expect(page.get_by_label("What do you want to share?")).to_have_value(
                "A note with one file."
            )
            expect(page.get_by_role("checkbox", name="care-note.txt")).to_be_checked()
            page.get_by_role("button", name="Save private draft").click()
            expect(page.get_by_text("Saved version 2", exact=True)).to_be_visible()
            page.get_by_role("button", name="Preview audience").click()
            page.get_by_role("button", name="Turn on version 2").click()
            visitor_href = page.get_by_role("link", name="View as a visitor").get_attribute(
                "href"
            )
            with signed_out_browser(playwright) as visitor:
                visitor.goto(browser_peer["base_url"] + visitor_href)
                with visitor.expect_download() as download_info:
                    visitor.get_by_role("link", name="Download attachment 1").click()
                assert download_info.value.suggested_filename == "care-note.txt"


def test_active_route_controls_preserve_overlapping_access(browser_peer):
    """Break caught: narrowing one active route accidentally stops every route or edits the draft."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            open_new_layer(page)
            page.get_by_label("Layer title").fill("Overlap test")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("checkbox", name="Alex’s care circle").check()
            page.get_by_role("button", name="Save private draft").click()
            expect(page.get_by_text("Saved version 2", exact=True)).to_be_visible()
            page.get_by_role("button", name="Preview audience").click()
            page.get_by_role("button", name="Turn on version 2").click()

            expect(page.get_by_role("button", name="Stop sharing directly with Sam Family")).to_be_visible()
            page.get_by_role("button", name="Stop sharing directly with Sam Family").click()
            expect(
                page.locator("#main-content").get_by_text(
                    "Alex’s care circle is still an active route"
                )
            ).to_be_visible()
            expect(page.get_by_label("What do you want to share?")).to_have_value("")
            page.get_by_role("button", name="Turn off Alex’s care circle").click()
            expect(
                page.locator("#main-content").get_by_text("No named audience routes remain")
            ).to_be_visible()


def test_expired_session_relogin_preserves_unsaved_layer(browser_peer):
    """Break caught: a session expiry replaces the editor and discards unsaved text."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            open_new_layer(page)
            page.get_by_label("Layer title").fill("Still in my editor")
            page.get_by_label("What do you want to share?").fill(
                "This survives signing in again."
            )
            with browser_peer["app"].state.store.transaction() as db:
                db.execute("DELETE FROM sessions")
            page.get_by_role("button", name="Save private draft").click()
            expect(
                page.get_by_role("heading", name="Sign in again to keep working")
            ).to_be_visible()
            expect(page.get_by_label("Layer title")).to_have_value("Still in my editor")
            page.get_by_role("dialog").get_by_label("Password").fill(
                browser_peer["password"]
            )
            page.get_by_role("button", name="Sign in again").click()
            expect(page.locator("#main-content").get_by_text("Signed in again. Your unsaved text is ready to save.", exact=True)).to_be_visible()
            expect(page.get_by_label("Layer title")).to_have_value("Still in my editor")
            expect(page.get_by_label("What do you want to share?")).to_have_value(
                "This survives signing in again."
            )
            page.get_by_role("button", name="Save private draft").click()
            expect(
                page.locator("#main-content").get_by_text("Private draft saved")
            ).to_be_visible()


def test_conflict_and_untrusted_values_leave_the_browser_usable(browser_peer):
    """Break caught: a conflict loses typing or stored text/date data executes or crashes."""
    store = browser_peer["app"].state.store
    patient_id = browser_peer["users"]["patient"]["id"]
    family_id = browser_peer["users"]["family"]["id"]
    unsafe_title = '<img src=x onerror="window.badValue=true">'
    room = store.create_room(patient_id, unsafe_title, [family_id])
    with store.transaction() as db:
        db.execute("UPDATE room_activity SET created=? WHERE room_id=?", (1e20, room["id"]))
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            expect(page.get_by_text(unsafe_title, exact=True)).to_be_visible()
            assert page.locator('img[src="x"]').count() == 0
            assert page.evaluate("window.badValue !== true")
            expect(page.get_by_text("Date unavailable")).to_be_visible()

            page.get_by_role("link", name="My sharing layers").click()
            open_new_layer(page)
            page.wait_for_url("**/#layers/*")
            layer_id = decode_fragment_id(page.url)
            page.get_by_label("What do you want to share?").fill("Keep my conflicting text.")
            store.save_layer(patient_id, layer_id, {"version": 1, "body": "Other tab"})
            page.get_by_role("button", name="Save private draft").click()
            expect(
                page.locator("#layer-status").get_by_text(
                    "This draft changed in another tab"
                )
            ).to_be_visible()
            expect(page.get_by_label("What do you want to share?")).to_have_value(
                "Keep my conflicting text."
            )
            page.get_by_role("button", name="Save my text onto the latest draft").click()
            expect(
                page.locator("#main-content").get_by_text("Private draft saved")
            ).to_be_visible()
            assert store.get_layer(patient_id, layer_id)["body"] == "Keep my conflicting text."


def decode_fragment_id(url):
    from urllib.parse import unquote, urlsplit

    return unquote(urlsplit(url).fragment.split("/", 1)[1])


@pytest.mark.parametrize('browser_peer', [False, True], indirect=True)
def test_invited_participant_chooses_local_account_details(browser_peer):
    """Break caught: an issued invitation cannot be redeemed from the signed-out home."""
    store = browser_peer["app"].state.store
    invitation = store.invite(browser_peer["users"]["organizer"]["id"], 3600)
    with sync_playwright() as playwright:
        with signed_out_browser(playwright) as page:
            page.goto(browser_peer["base_url"] + "/")
            if browser_peer['local_demo']:
                page.get_by_role('button', name='Account and sign out').click()
                page.get_by_role('button', name='Sign out', exact=True).click()
            page.get_by_text("Use an invitation", exact=True).click()
            page.get_by_label("Invitation token").fill(invitation["token"])
            page.get_by_label("New username").fill("newperson")
            page.get_by_label("Your display name").fill("New Person")
            page.get_by_label("New password").fill("another-long-password")
            page.get_by_role("button", name="Create my account").click()
            expect(page.get_by_text("Account created. Sign in to open your home.")).to_be_visible()
            if browser_peer['local_demo']:
                expect(page.get_by_text('Sign in with another account', exact=True)).to_be_visible()
                page.get_by_text('Sign in with another account', exact=True).click()
            page.get_by_label("Username", exact=True).fill("newperson")
            page.get_by_label("Password", exact=True).fill("another-long-password")
            page.get_by_role("button", name="Sign in").click()
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()


def test_pairing_pending_delivery_and_peer_wide_disconnect_states(browser_peer):
    """Break caught: pairing shares implicitly or canceled delivery looks retryable."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            page.get_by_role("link", name="Connections", exact=True).click()
            page.get_by_label("Peer card").fill(json.dumps(browser_peer["remote_card"]))
            page.get_by_role("button", name="Preview peer card").click()
            expect(page.get_by_role("heading", name="Casey Remote")).to_be_visible()
            expect(page.get_by_text(browser_peer["remote_card"]["fingerprint"])).to_be_visible()
            page.get_by_role(
                "button", name="Fingerprint matches — pair this peer"
            ).click()
            expect(
                page.locator("#main-content").get_by_text(
                    "Peer paired. Nothing has been shared automatically."
                )
            ).to_be_visible()
            expect(
                page.get_by_role("button", name="Disconnect peer and 1 contact")
            ).to_be_visible()

            page.get_by_role("link", name="My sharing layers").click()
            open_new_layer(page)
            page.get_by_label("Layer title").fill("Remote delivery")
            page.get_by_role("checkbox", name="Casey Remote").check()
            page.get_by_role("button", name="Save private draft").click()
            expect(page.get_by_text("Saved version 2", exact=True)).to_be_visible()
            page.get_by_role("button", name="Preview audience").click()
            page.get_by_role("button", name="Turn on version 2").click()
            expect(page.get_by_text("Active · version 2")).to_be_visible()
            page.get_by_role("link", name="Connections", exact=True).click()
            expect(page.get_by_text("Pending delivery")).to_be_visible()

            page.get_by_role("button", name="Disconnect peer and 1 contact").click()
            expect(page.get_by_text("Canceled")).to_be_visible()
            expect(page.get_by_role("button", name="Retry")).to_have_count(0)


def test_dirty_layer_survives_renders_conflicts_and_an_accepted_save(browser_peer):
    """I1: every edit stays current through rerenders, conflicts, and in-flight saves."""
    store = browser_peer["app"].state.store
    patient_id = browser_peer["users"]["patient"]["id"]
    accepted = threading.Event()
    release = threading.Event()
    original_save = store.save_layer

    def delayed_save(actor, key, data):
        saved = original_save(actor, key, data)
        accepted.set()
        release.wait(5)
        return saved

    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            open_new_layer(page)
            page.get_by_label("Layer title").fill("Kept through a dialog")
            page.get_by_label("What do you want to share?").fill("First current text")
            page.get_by_role("button", name="Account and sign out").click()
            page.get_by_role("button", name="Close").click()
            expect(page.get_by_label("Layer title")).to_have_value("Kept through a dialog")
            expect(page.get_by_label("What do you want to share?")).to_have_value("First current text")

            layer_id = decode_fragment_id(page.url)
            store.save_layer(patient_id, layer_id, {"version": 1, "body": "Other tab"})
            page.get_by_role("button", name="Save private draft").click()
            expect(page.locator("#layer-status")).to_contain_text("This draft changed in another tab")
            page.get_by_label("What do you want to share?").fill("Edited after conflict")
            page.get_by_role("button", name="Save my text onto the latest draft").click()
            expect(page.locator("#main-content").get_by_text("Private draft saved")).to_be_visible()
            assert store.get_layer(patient_id, layer_id)["body"] == "Edited after conflict"

            page.get_by_label("What do you want to share?").fill("Accepted snapshot")
            store.save_layer = delayed_save
            page.get_by_role("button", name="Save private draft").click()
            assert accepted.wait(5), "server did not accept the delayed layer save"
            page.get_by_label("What do you want to share?").fill("Typed while saving")
            release.set()
            expect(page.locator("#main-content").get_by_text("Submitted draft saved. Newer edits still need saving.")).to_be_visible()
            expect(page.get_by_label("What do you want to share?")).to_have_value("Typed while saving")
            expect(page.get_by_text("Unsaved changes", exact=True)).to_be_visible()
            page.get_by_role("button", name="Preview audience").click()
            expect(page.locator("#layer-status")).to_have_text("Save this private draft before previewing a version.")
            assert store.get_layer(patient_id, layer_id)["body"] == "Accepted snapshot"


def test_accepted_message_refresh_failure_keeps_new_composer_without_duplicate(browser_peer):
    """I2: an accepted idempotent POST is complete even when subsequent reads fail."""
    store = browser_peer["app"].state.store
    accepted = threading.Event()
    release = threading.Event()
    original_send = store.send_message
    original_get = store.get_room
    fail_refresh = {"value": False}

    def accepted_send(*args):
        message = original_send(*args)
        fail_refresh["value"] = True
        accepted.set()
        return message

    def delayed_failed_get(*args):
        if fail_refresh["value"]:
            release.wait(5)
            fail_refresh["value"] = False
            from superyak_peer.common import Problem
            raise Problem(503, "Room refresh unavailable")
        return original_get(*args)

    store.send_message = accepted_send
    store.get_room = delayed_failed_get
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Chats", exact=True).click()
            page.get_by_role("button", name="New private chat").click()
            page.get_by_label("Chat title").fill("Reliable send")
            page.get_by_role("button", name="Create chat").click()
            expect(page.get_by_role("heading", name="Reliable send")).to_be_visible()
            room_id = decode_fragment_id(page.url)
            page.get_by_role("textbox", name="Message", exact=True).fill("Accepted once")
            page.get_by_role("button", name="Send message").click()
            assert accepted.wait(5), "server did not accept the message"
            page.get_by_role("textbox", name="Message", exact=True).fill("New text typed during refresh")
            release.set()
            expect(page.locator("#main-content").get_by_text("Message saved. Latest room status is unavailable.")).to_be_visible()
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("New text typed during refresh")
            page.reload()
            expect(page.get_by_text("Accepted once", exact=True)).to_have_count(1)
            assert [m["body"] for m in store.get_room(browser_peer["users"]["patient"]["id"], room_id)["messages"]] == ["Accepted once"]


def test_failed_logout_stays_authenticated_until_server_acknowledges(browser_peer):
    """I3: offline sign-out never claims that the HttpOnly session was revoked."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, context):
            page.get_by_role("button", name="Account and sign out").click()
            context.set_offline(True)
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.get_by_text("Sign-out could not be completed")).to_be_visible()
            expect(page.get_by_role("heading", name="Your account")).to_be_visible()
            expect(page.get_by_role("button", name="Retry sign out")).to_be_visible()
            context.set_offline(False)
            page.get_by_role("button", name="Retry sign out").click()
            expect(page.get_by_role("heading", name="Sign in to your home")).to_be_visible()


def test_active_release_read_failure_is_unknown_and_public_off_uses_returned_routes(browser_peer):
    """I4: failed release reads remain explicit and route confirmations use server truth."""
    store = browser_peer["app"].state.store
    patient_id = browser_peer["users"]["patient"]["id"]
    layer = store.create_layer(patient_id, {"title": "Availability", "public": True})
    store.activate_layer(patient_id, layer["id"], layer["version"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.route(
                f"**/api/shared/layers/{layer['id']}",
                lambda route: route.fulfill(status=503, content_type="application/json", body='{"error":"Temporarily unavailable"}'),
            )
            page.reload()
            page.get_by_role("link", name="My sharing layers").click()
            page.locator(f'[data-action="open-layer"][data-id="{layer["id"]}"]').click()
            expect(page.get_by_text("Active release details are unavailable")).to_be_visible()
            expect(page.get_by_text("Sharing is off", exact=True)).to_have_count(0)
            page.unroute(f"**/api/shared/layers/{layer['id']}")
            page.reload()
            page.locator(f'[data-action="open-layer"][data-id="{layer["id"]}"]').click()
            page.get_by_role("button", name="Turn off public link").click()
            expect(page.locator("#main-content").get_by_text("No active audience routes remain")).to_be_visible()


def test_room_owner_can_remove_participant_and_new_chat_selection_is_independent(browser_peer):
    """I5/I6: removal revokes hosted access; a new room starts with clean choices."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Chats", exact=True).click()
            page.get_by_role("button", name="New private chat").click()
            page.get_by_label("Chat title").fill("First audience")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("checkbox", name="Dr. Morgan").check()
            page.get_by_role("button", name="Create chat").click()
            expect(page.get_by_role("heading", name="First audience")).to_be_visible()
            room_id = decode_fragment_id(page.url)

            page.get_by_role("button", name="New private chat").click()
            expect(page.get_by_role("checkbox", name="Sam Family")).not_to_be_checked()
            expect(page.get_by_role("checkbox", name="Sam Family")).to_be_enabled()
            page.get_by_label("Chat title").fill("Second direct room")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("button", name="Create chat").click()
            expect(page.get_by_role("heading", name="Second direct room")).to_be_visible()

            page.goto(browser_peer["base_url"] + f"/#chats/{room_id}")
            expect(page.get_by_role("heading", name="First audience")).to_be_visible()
            expect(page.get_by_text("Removing someone stops access on this peer")).to_be_visible()
            page.get_by_role("button", name="Remove Sam Family from this room").click()
            expect(page.get_by_text("Sam Family no longer has access on this peer; remote removal requires acknowledgement")).to_be_visible()

            with signed_in_browser(playwright, browser_peer, "family") as (family, _):
                family.goto(browser_peer["base_url"] + f"/#chats/{room_id}")
                expect(family.get_by_role("heading", name="First audience")).to_have_count(0)


def test_durable_name_corrections_shared_attribution_and_complete_revision(browser_peer):
    """I7: durable actual names and stable source attribution remain navigable."""
    store = browser_peer["app"].state.store
    patient_id = browser_peer["users"]["patient"]["id"]
    family_id = browser_peer["users"]["family"]["id"]
    full_body = "Complete release text " + ("kept in history. " * 20)
    layer = store.create_layer(patient_id, {
        "title": "Attributed update",
        "body": full_body,
        "audience_users": [family_id],
    })
    store.activate_layer(patient_id, layer["id"], layer["version"])
    peer_id = browser_peer["app"].state.federation.identity.peer_id

    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("button", name="Account and sign out").click()
            page.get_by_label("Display name").fill("Alex Rivera")
            page.get_by_role("button", name="Save name correction").click()
            page.get_by_role("link", name="My sharing layers").click()
            page.locator(f'[data-action="open-layer"][data-id="{layer["id"]}"]').click()
            page.get_by_text("Release 1 · draft version 1").click()
            expect(page.locator("details").get_by_text(full_body, exact=True)).to_be_visible()
            expect(page.get_by_text(f"Owner account {patient_id}", exact=True)).to_be_visible()
            page.reload()
            page.get_by_role("button", name="Account and sign out").click()
            expect(page.get_by_text("Alex Patient → Alex Rivera", exact=True)).to_be_visible()
            expect(page.get_by_text(f"Changed by you ({patient_id})", exact=False)).to_be_visible()

        with signed_in_browser(playwright, browser_peer, "family") as (family, _):
            family.get_by_role("link", name="Shared spaces", exact=True).click()
            family.get_by_text("Attributed update", exact=True).click()
            expect(family.get_by_text("Shared by Alex Rivera", exact=False)).to_be_visible()
            expect(family.get_by_text(f"Owner account {patient_id}", exact=True)).to_be_visible()
            expect(family.get_by_text(f"Origin peer {peer_id}", exact=True)).to_be_visible()


def test_overlapping_upload_and_save_merges_attachment_into_latest_layer_values(browser_peer):
    """I1 round 2: upload completion cannot resurrect its captured pre-save text."""
    store = browser_peer["app"].state.store
    patient_id = browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            open_new_layer(page)
            expect(page.get_by_role("heading", name="Edit this layer")).to_be_visible()
            layer_id = decode_fragment_id(page.url)
            page.get_by_label("What do you want to share?").fill("Text captured when upload began")
            page.evaluate("""
                window.__uploadAccepted = false;
                window.__releaseUpload = null;
                const realFetch = window.fetch.bind(window);
                window.fetch = async (...args) => {
                  const response = await realFetch(...args);
                  const path = String(args[0]);
                  if (path === "/api/files" && (args[1]?.method || "GET") === "POST") {
                    window.__uploadAccepted = true;
                    await new Promise((resolve) => { window.__releaseUpload = resolve; });
                  }
                  return response;
                };
            """)
            page.locator("#file-upload").set_input_files({
                "name": "overlap.txt",
                "mimeType": "text/plain",
                "buffer": b"real uploaded content",
            })
            page.wait_for_function("() => window.__uploadAccepted === true")

            page.get_by_label("What do you want to share?").fill("Newer text saved while upload waits")
            page.get_by_role("button", name="Save private draft").click()
            expect(page.locator("#main-content").get_by_text("Private draft saved")).to_be_visible()
            assert store.get_layer(patient_id, layer_id)["body"] == "Newer text saved while upload waits"

            page.evaluate("window.__releaseUpload()")
            expect(page.get_by_text("overlap.txt uploaded")).to_be_visible()
            expect(page.get_by_label("What do you want to share?")).to_have_value("Newer text saved while upload waits")
            expect(page.get_by_role("checkbox", name="overlap.txt")).to_be_checked()
            page.get_by_role("button", name="Save private draft").click()
            expect(page.locator("#main-content").get_by_text("Private draft saved")).to_be_visible()
            saved = store.get_layer(patient_id, layer_id)
            assert saved["body"] == "Newer text saved while upload waits"
            assert len(saved["attachment_ids"]) == 1


def test_repeated_send_during_post_acceptance_refresh_reuses_settled_composer(browser_peer):
    """I2 round 2: the still-pending refresh cannot resubmit an accepted visible body."""
    store = browser_peer["app"].state.store
    refresh_started = threading.Event()
    release_refresh = threading.Event()
    original_get = store.get_room
    delay_refresh = {"value": False}

    def delayed_get(*args):
        if delay_refresh["value"]:
            refresh_started.set()
            release_refresh.wait(5)
        return original_get(*args)

    store.get_room = delayed_get
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Chats", exact=True).click()
            page.get_by_role("button", name="New private chat").click()
            page.get_by_label("Chat title").fill("One accepted send")
            page.get_by_role("button", name="Create chat").click()
            expect(page.get_by_role("heading", name="One accepted send")).to_be_visible()
            room_id = decode_fragment_id(page.url)
            delay_refresh["value"] = True
            page.get_by_role("textbox", name="Message", exact=True).fill("Send this only once")
            page.get_by_role("button", name="Send message").click()
            assert refresh_started.wait(5), "post-acceptance refresh did not begin"
            page.get_by_role("button", name="Send message").click()
            page.wait_for_timeout(150)
            release_refresh.set()
            expect(page.get_by_text("Send this only once", exact=True)).to_have_count(1)
            messages = store.get_room(browser_peer["users"]["patient"]["id"], room_id)["messages"]
            assert [message["body"] for message in messages] == ["Send this only once"]


def test_accepted_participant_removal_survives_failed_followup_read(browser_peer):
    """N1: acknowledged DELETE is settled before a failed room refresh is reported."""
    store = browser_peer["app"].state.store
    family_id = browser_peer["users"]["family"]["id"]
    original_remove = store.remove_participant
    original_get = store.get_room
    removed = {"value": False}

    def accepted_remove(*args):
        room = original_remove(*args)
        removed["value"] = True
        return room

    def failed_get(*args):
        if removed["value"]:
            removed["value"] = False
            raise Problem(503, "Room refresh unavailable")
        return original_get(*args)

    store.remove_participant = accepted_remove
    store.get_room = failed_get
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Chats", exact=True).click()
            page.get_by_role("button", name="New private chat").click()
            page.get_by_label("Chat title").fill("Removal boundary")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("button", name="Create chat").click()
            expect(page.get_by_role("heading", name="Removal boundary")).to_be_visible()
            room_id = decode_fragment_id(page.url)
            page.get_by_role("button", name="Remove Sam Family from this room").click()
            expect(page.locator("#main-content").get_by_text("Sam Family no longer has access on this peer; remote removal requires acknowledgement. Latest room status is unavailable.")).to_be_visible()
            expect(page.get_by_role("button", name="Remove Sam Family from this room")).to_have_count(0)
            with pytest.raises(Problem) as denied:
                store.get_room(family_id, room_id)
            assert denied.value.status == 404


def test_assistant_delayed_suggestion_appends_to_newer_private_typing(browser_peer):
    """Break caught: delayed generation replaces new typing or changes active words."""
    from test_models import adapter, NativeEndpoint
    entered, finish = threading.Event(), threading.Event()
    endpoint = NativeEndpoint()
    model, _ = adapter(endpoint)
    original = model._request
    def delayed(method, path, payload=None):
        if method == 'POST':
            entered.set()
            assert finish.wait(15)
        return original(method, path, payload)
    model._request = delayed
    browser_peer['app'].state.assistant = model
    store = browser_peer['app'].state.store
    who = browser_peer['users']['patient']['id']
    layer = store.create_layer(who, {'title': 'Fictional letter', 'body': 'Saved original', 'public': True})
    store.activate_layer(who, layer['id'], 1)
    try:
        with sync_playwright() as playwright:
            with signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
                page.goto(browser_peer['base_url'] + '/#layers/' + layer['id'])
                expect(page.get_by_label('Assistant request')).to_be_visible()
                page.get_by_label('Assistant request').fill('Shorten this fictional letter')
                page.get_by_role('button', name='Ask Gemma privately').click()
                assert entered.wait(5)
                page.get_by_label('What do you want to share?').fill('Newer private typing')
                finish.set()
                expect(page.get_by_text('Suggestion from saved version 1', exact=True)).to_be_visible()
                expect(page.get_by_label('What do you want to share?')).to_have_value('Newer private typing')
                page.get_by_role('button', name='Append suggestion to my private draft').click()
                expect(page.get_by_label('What do you want to share?')).to_have_value('Newer private typing\n\nA fictional private suggestion.')
                assert store.get_layer(who, layer['id'])['body'] == 'Saved original'
                assert store.active_layer(layer['id'], public=True)['body'] == 'Saved original'
                page.get_by_role('button', name='Save private draft').click()
                expect(page.locator('#main-content').get_by_text('Private draft saved', exact=True)).to_be_visible()
                assert store.active_layer(layer['id'], public=True)['body'] == 'Saved original'
    finally:
        finish.set()


def test_source_browser_export_import_retains_private_attribution(browser_peer, tmp_path):
    """Break caught: selected export includes a newer draft or import becomes public."""
    store = browser_peer['app'].state.store
    who = browser_peer['users']['patient']['id']
    layer = store.create_layer(who, {'title': 'Fictional source', 'body': 'Active selected words', 'public': True})
    store.activate_layer(who, layer['id'], 1)
    store.save_layer(who, layer['id'], {'version': 1, 'body': 'Private new words'})
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
            page.goto(browser_peer['base_url'] + '/#layers/' + layer['id'])
            with page.expect_download() as download:
                page.get_by_role('button', name='Export selected active release').click()
            output = tmp_path / 'selected.json'
            download.value.save_as(output)
            document = json.loads(output.read_text())
            assert document['records'][0]['content']['body'] == 'Active selected words'
            expect(page.get_by_role('button', name='Ask Gemma privately')).to_be_disabled()
        with signed_in_browser(playwright, browser_peer, 'doctor') as (page, _):
            page.get_by_role('link', name='My sharing layers').click()
            page.locator('#source-import').set_input_files(output)
            expect(page.locator('#main-content').get_by_text('Imported privately. Recorded audiences did not grant access.', exact=True)).to_be_visible()
            page.get_by_text('Fictional source', exact=True).click()
            expect(page.get_by_text('Active selected words', exact=True)).to_be_visible()
            expect(page.get_by_text('Origin ' + document['records'][0]['origin'], exact=False)).to_be_visible()
            assert store.list_layers(browser_peer['users']['doctor']['id']) == []


def test_assistant_suggestion_stays_with_initiating_layer_and_is_cleared_on_logout(browser_peer):
    """Break caught: a delayed suggestion crosses layer or account boundaries."""
    from test_models import adapter, NativeEndpoint
    entered, finish = threading.Event(), threading.Event()
    endpoint = NativeEndpoint()
    model, _ = adapter(endpoint)
    original = model._request
    def delayed(method, path, payload=None):
        if method == 'POST':
            entered.set()
            assert finish.wait(15)
        return original(method, path, payload)
    model._request = delayed
    browser_peer['app'].state.assistant = model
    store = browser_peer['app'].state.store
    who = browser_peer['users']['patient']['id']
    first = store.create_layer(who, {'title': 'First fictional draft', 'body': 'First words'})
    second = store.create_layer(who, {'title': 'Second fictional draft', 'body': 'Second words'})
    try:
        with sync_playwright() as playwright:
            with signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
                page.goto(browser_peer['base_url'] + '/#layers/' + first['id'])
                page.get_by_label('Assistant request').fill('Help with this fictional note')
                page.get_by_role('button', name='Ask Gemma privately').click()
                assert entered.wait(5)
                page.get_by_role('button', name='Second fictional draft Draft version 1 Private draft').click()
                expect(page.get_by_label('Layer title')).to_have_value('Second fictional draft')
                finish.set()
                page.wait_for_function('() => Object.values(state.assistance).some(entry => entry.result)')
                expect(page.get_by_role('button', name='Append suggestion to my private draft')).to_have_count(0)
                expect(page.get_by_label('What do you want to share?')).to_have_value('Second words')
                page.get_by_role('button', name='First fictional draft Draft version 1 Private draft').click()
                expect(page.get_by_role('button', name='Append suggestion to my private draft')).to_be_visible()
                entered.clear()
                finish.clear()
                page.get_by_role('button', name='Ask Gemma privately').click()
                assert entered.wait(5)
                page.get_by_role('button', name='Account and sign out').click()
                page.get_by_role('button', name='Sign out', exact=True).click()
                expect(page.get_by_role('heading', name='Sign in to your home')).to_be_visible()
                page.get_by_label('Username', exact=True).fill('doctor')
                page.get_by_label('Password', exact=True).fill(browser_peer['password'])
                page.get_by_role('button', name='Sign in', exact=True).click()
                expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
                with page.expect_response(lambda r: r.url.endswith('/api/assistant') and r.request.method == 'POST'):
                    finish.set()
                # Wait for the completed real response to be consumed by the app.
                page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                assert page.evaluate('Object.keys(state.assistance).length') == 0
                assert store.get_layer(who, first['id'])['body'] == 'First words'
                assert store.get_layer(who, second['id'])['body'] == 'Second words'
    finally:
        finish.set()


@pytest.mark.parametrize('kind', ['care-circle', 'project', 'organization'])
def test_fresh_participant_creates_space_and_previews_exact_selection(browser_peer, kind):
    import base64
    store = browser_peer['app'].state.store
    admin = browser_peer['users']['organizer']['id']
    browser_peer['app'].state.federation.pair(admin, browser_peer['remote_card'])
    invitation = store.invite(admin)
    fresh = store.redeem(invitation['token'], 'fresh', 'Fresh Person', browser_peer['password'])
    selected = store.upload_file(fresh['id'], 'selected-evidence.txt', 'text/plain', base64.b64encode(b'selected').decode())
    store.upload_file(fresh['id'], 'unselected-secret.txt', 'text/plain', base64.b64encode(b'private').decode())
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, 'fresh') as (page, _):
            create = page.locator('#main-content').get_by_role('button', name='Create space', exact=True)
            create.click()
            expect(page.get_by_label('Space name')).to_be_focused()
            page.get_by_label('Space name').fill('My selected space')
            page.get_by_label('Space kind').select_option(kind)
            expect(page.get_by_role('dialog').get_by_text('Casey Remote')).to_have_count(0)
            page.get_by_role('dialog').get_by_role('checkbox', name='Sam Family').check()
            page.get_by_role('dialog').get_by_role('button', name='Create space', exact=True).click()
            expect(create).to_be_focused()
            page.reload()
            expect(page.get_by_role('heading', name='My selected space')).to_be_visible()
            assert store.shared_layers(fresh['id']) == []
            page.get_by_role('link', name='My sharing layers').click()
            page.get_by_role('button', name='New layer').click()
            page.get_by_role('checkbox', name='My selected space').check()
            page.get_by_role('checkbox', name='selected-evidence.txt').check()
            page.get_by_role('button', name='Save private draft').click()
            expect(page.locator('#main-content').get_by_text('Private draft saved')).to_be_visible()
            page.get_by_role('button', name='Preview audience').click()
            dialog = page.get_by_role('dialog')
            expect(dialog.get_by_text('Sam Family', exact=False)).to_be_visible()
            expect(dialog.get_by_text('Dr. Morgan', exact=False)).to_have_count(0)
            expect(dialog.get_by_role('link', name='Inspect selected-evidence.txt')).to_have_attribute('href', '/api/files/' + selected['id'])
            expect(dialog.get_by_text('unselected-secret.txt')).to_have_count(0)
            expect(dialog.get_by_text('SHA-256:', exact=False)).not_to_be_visible()
            dialog.get_by_text('File details', exact=True).click()
            expect(dialog.get_by_text('SHA-256:', exact=False)).to_be_visible()
            dialog.get_by_text('File details', exact=True).click()
            assert page.evaluate("document.activeElement.closest('dialog') !== null")
            for _ in range(5):
                page.keyboard.press('Tab')
                assert page.evaluate("document.activeElement.closest('dialog') !== null")
            page.screenshot(path=str(ARTIFACTS / ('final-preview-' + kind + '.png')), full_page=False)
            page.keyboard.press('Escape')
            expect(page.get_by_role('button', name='Preview audience')).to_be_focused()
            page.get_by_role('button', name='Preview audience').click()
            page.get_by_role('button', name='Turn on version 2').click()
            expect(page.locator('#main-content').get_by_text('Version 2 is now active')).to_be_visible()
            assert len(store.shared_layers(browser_peer['users']['family']['id'])) == 1
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(ARTIFACTS / ('final-space-' + kind + '.png')), full_page=True)


def test_delivery_waiting_acknowledgement_refresh_and_unsaved_state(browser_peer, tmp_path):
    app = browser_peer['app']
    fed, store = app.state.federation, app.state.store
    owner = browser_peer['users']['organizer']['id']
    remote = Store(tmp_path / 'delivery-peer')
    recipient = remote.create_user('remote', 'Casey Delivery', 'long-password', is_admin=True)['id']
    other = Federation(remote, endpoint='https://remote.example:7443')
    fed.endpoint = 'https://local.example:7443'
    contact = fed.pair(owner, other.card(recipient))
    back = other.pair(recipient, fed.card(owner))
    original = fed.sync_once
    offline = [False]
    def sync(**kwargs):
        def send(card, prepare):
            if offline[0]:
                raise OSError('Synthetic offline peer')
            other.receive(prepare())
        other.sync_once(send=lambda card, prepare: fed.receive(prepare()))
        return original(send=send)
    fed.sync_once = sync
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, 'organizer') as (page, _):
            page.get_by_role('link', name='My sharing layers').click()
            page.get_by_role('button', name='New layer').click()
            page.get_by_label('Layer title').fill('Delivery update')
            page.get_by_role('checkbox', name='Casey Delivery').check()
            page.get_by_role('button', name='Save private draft').click()
            expect(page.locator('#main-content').get_by_text('Private draft saved')).to_be_visible()
            page.get_by_role('button', name='Preview audience').click()
            page.get_by_role('button', name='Turn on version 2').click()
            expect(page.get_by_text('Pending delivery')).to_be_visible()
            expect(page.get_by_text('Delivery update → Casey Delivery')).to_be_visible()
            page.get_by_role('button', name='Check delivery now').click()
            expect(page.locator('.item-main').get_by_text('Share update · Delivered')).to_be_visible()
            assert remote.shared_layers(recipient)
            offline[0] = True
            page.get_by_role('button', name='Stop all sharing').click()
            page.get_by_role('button', name='Yes, stop all sharing').click()
            expect(page.get_by_text("Access stopped here; waiting for Casey Delivery's peer to acknowledge withdrawal.", exact=False)).to_be_visible()
            assert remote.shared_layers(recipient)
            page.get_by_role('button', name='Check delivery now').click()
            expect(page.get_by_text('delivery failed; remote acknowledgement unknown', exact=False)).to_be_visible()
            page.get_by_label('What do you want to share?').fill('Unsaved retained during delivery refresh')
            incoming = remote.create_layer(recipient, {'title':'New incoming update', 'audience_users':[back['id']]})
            remote.activate_layer(recipient, incoming['id'], 1)
            offline[0] = False
            page.get_by_role('button', name='Retry', exact=True).click()
            page.get_by_role('button', name='Check delivery now').click()
            expect(page.get_by_text('Remote withdrawal acknowledged', exact=False)).to_be_visible()
            expect(page.get_by_label('What do you want to share?')).to_have_value('Unsaved retained during delivery refresh')
            assert remote.shared_layers(recipient) == [remote.active_layer(incoming['id'],recipient)]
            page.get_by_role('link', name='Shared spaces', exact=True).click()
            expect(page.get_by_text('New incoming update', exact=True)).to_be_visible()
            page.get_by_role('link', name='Chats', exact=True).click()
            page.get_by_role('button', name='New private chat').click()
            page.get_by_label('Chat title').fill('Delivery room')
            page.get_by_role('dialog').get_by_role('checkbox', name='Casey Delivery').check()
            page.get_by_role('button', name='Create chat', exact=True).click()
            expect(page.get_by_text('Pending delivery')).to_be_visible()
            page.get_by_role('button', name='Check delivery now').click()
            expect(page.get_by_text('Share chat · Delivered')).to_be_visible()
            page.get_by_label('Message', exact=True).fill('Unsent room text')
            page.get_by_role('button', name='Remove Casey Delivery from this room').click()
            expect(page.get_by_text("Access stopped here; waiting for Casey Delivery's peer to acknowledge withdrawal.", exact=False)).to_be_visible()
            assert remote.list_rooms(recipient)
            page.get_by_role('button', name='Check delivery now').click()
            expect(page.get_by_text('Remote withdrawal acknowledged', exact=False)).to_be_visible()
            expect(page.get_by_label('Message', exact=True)).to_have_value('Unsent room text')
            assert remote.list_rooms(recipient) == []
            expect(page.get_by_text('Remove chat access', exact=False)).to_be_visible()
            expect(page.get_by_text('Peer ' + other.identity.peer_id, exact=False)).not_to_be_visible()
            page.get_by_text('Connection details', exact=True).click()
            expect(page.get_by_text('Peer ' + other.identity.peer_id, exact=False)).to_be_visible()
            page.get_by_text('Connection details', exact=True).click()
            page.screenshot(path=str(ARTIFACTS / 'final-room-acknowledged.png'), full_page=True)


def test_preview_resolution_failure_and_public_network_failure_are_visible(browser_peer):
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
            page.get_by_role('link', name='My sharing layers').click()
            page.get_by_role('button', name='New layer').click()
            page.route('**/preview', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"Selection unavailable"}'))
            page.get_by_role('button', name='Preview audience').click()
            expect(page.locator('#main-content').get_by_text('Preview unavailable. No selection was activated.', exact=False)).to_be_visible()
            expect(page.get_by_role('dialog')).to_have_count(0)
        with signed_out_browser(playwright) as page:
            page.route('**/public/layers/*', lambda route: route.abort())
            page.goto(browser_peer['base_url'] + '/public/?layer=unreachable')
            expect(page.get_by_role('heading', name='This page is unavailable')).to_be_visible()
            expect(page.get_by_text('sharing status is unknown', exact=False)).to_be_visible()


def test_preview_rechecks_members_and_conflicts_after_review(browser_peer):
    store = browser_peer['app'].state.store
    owner = browser_peer['users']['patient']['id']
    circle = store.list_spaces(owner)[0]
    doctor = browser_peer['users']['doctor']['id']
    layer = store.create_layer(owner, {'title':'Membership check', 'audience_spaces':[circle['id']]})
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, 'patient') as (page, _):
            page.get_by_role('link', name='My sharing layers').click()
            page.get_by_role('button', name='Membership check Draft version 1 Private draft').click()
            store.change_space_member(owner, circle['id'], doctor, remove=True)
            page.get_by_role('button', name='Preview audience').click()
            expect(page.get_by_role('dialog').get_by_text('Dr. Morgan', exact=False)).to_have_count(0)
            expect(page.get_by_role('dialog').get_by_text('Sam Family', exact=False)).to_be_visible()
            store.change_space_member(owner, circle['id'], doctor)
            page.get_by_role('button', name='Turn on version 1').click()
            expect(page.locator('#main-content').get_by_text('The draft or space membership changed before activation.', exact=False)).to_be_visible()
            assert store.get_layer(owner, layer['id'])['active_revision'] is None
            page.get_by_role('button', name='Preview audience').click()
            expect(page.get_by_role('dialog').get_by_text('Dr. Morgan', exact=False)).to_be_visible()
            page.get_by_role('button', name='Turn on version 1').click()
            expect(page.get_by_text('Active · version 1')).to_be_visible()
            store.change_space_member(owner, circle['id'], doctor, remove=True)
            page.reload()
            expect(page.locator('.active-panel').get_by_text('Dr. Morgan', exact=False)).to_be_visible()


def test_super_admin_activation_and_named_role_preview_in_browser(browser_peer, tmp_path):
    from urllib.parse import urlencode
    store = browser_peer['app'].state.store
    path = tmp_path / 'activation.json'
    store.bootstrap_super_admin('science.stanley@example.org', 'Stanley', path)
    record = json.loads(path.read_text())
    fragment = '#activate?' + urlencode({k: record[k] for k in ['token', 'username', 'name']})
    with sync_playwright() as playwright, signed_out_browser(playwright) as page:
        page.goto(browser_peer['base_url'] + '/' + fragment)
        expect(page.get_by_label('New username', exact=True)).to_have_value('science.stanley@example.org')
        expect(page.get_by_label('Your display name', exact=True)).to_have_value('Stanley')
        assert record['token'] not in page.url
        page.get_by_label('New password', exact=True).fill(browser_peer['password'])
        page.get_by_role('button', name='Create my account', exact=True).click()
        expect(page.get_by_text('Account created. Sign in to open your home.', exact=True)).to_be_visible()
        page.get_by_label('Username', exact=True).fill(record['username'])
        page.get_by_label('Password', exact=True).fill(browser_peer['password'])
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
        page.get_by_role('link', name='Connections', exact=True).click()
        role = page.get_by_label('Role for Dr. Morgan', exact=True)
        role.select_option('admin')
        page.get_by_role('button', name='Review rights for Dr. Morgan', exact=True).click()
        dialog = page.get_by_role('dialog', name='Review account rights')
        expect(dialog).to_contain_text('Dr. Morgan')
        expect(dialog).to_contain_text('Admin')
        with store.transaction() as db:
            assert db.execute("SELECT is_admin FROM users WHERE username='doctor'").fetchone()[0] == 0
        dialog.get_by_role('button', name='Grant these rights', exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('Account rights updated')
        page.get_by_role('button', name='Create invitation', exact=True).click()
        expect(page.get_by_text('One-use invitation', exact=True)).to_be_visible()
        page.get_by_label('Role for Stanley', exact=True).select_option('participant')
        page.get_by_role('button', name='Review rights for Stanley', exact=True).click()
        page.get_by_role('dialog').get_by_role('button', name='Grant these rights', exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('Keep at least one active super admin')
        page.get_by_role('button', name='Account and sign out', exact=True).click()
        page.get_by_role('button', name='Sign out', exact=True).click()
        page.get_by_label('Username', exact=True).fill('doctor')
        page.get_by_label('Password', exact=True).fill(browser_peer['password'])
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
        page.get_by_role('link', name='Connections', exact=True).click()
        expect(page.get_by_text('One-use invitation', exact=True)).to_have_count(0)
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, 'doctor') as (page, _):
        page.get_by_role('link', name='Connections', exact=True).click()
        expect(page.get_by_role('button', name='Create invitation', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='Review rights for Dr. Morgan', exact=True)).to_have_count(0)


def test_docking_link_confirms_ship_lists_and_revokes_it_and_rooms_show_the_ship_banner(browser_peer):
    """Break caught: a docking link confirms without review, or a ship room lacks the Claude notice."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    docking = store.start_docking("serenity", "andy-mac")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#dock?code={docking['code']}")
            page.reload()
            dialog = page.get_by_role("dialog")
            expect(dialog.get_by_role("heading", name="Dock serenity")).to_be_visible()
            expect(dialog.get_by_text("andy-mac")).to_be_visible()
            dialog.get_by_role("button", name="Confirm docking").click()
            expect(page.get_by_role("status")).to_contain_text("Serenity is docked.")
            expect(page.locator("#announcer")).to_contain_text("Serenity is docked.")
            assert store.docking_status(docking["id"], docking["secret"])["status"] == "confirmed"
            ship = next(s for s in store.ships(users["organizer"]["id"]) if s["username"] == "serenity")
            room = store.create_room(users["patient"]["id"], "Ops", [ship["id"]])
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.get_by_text("Ships in this room send its text to Claude.")).to_be_visible()
            page.get_by_role("link", name="Connections", exact=True).click()
            expect(page.get_by_role("heading", name="Ships")).to_be_visible()
            page.get_by_role("button", name="Revoke key").click()
            expect(page.get_by_text("Key revoked", exact=True)).to_be_visible()


def test_a_room_shows_which_ship_messages_came_from_runs(browser_peer):
    """Break caught: a run's reply and a ship's own post look the same to people."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(users["patient"]["id"], started["id"], started["code"])
    room = store.create_room(users["patient"]["id"], "Ops", [ship["id"]])
    asked = store.send_message(users["patient"]["id"], room["id"], "a", "@serenity add notes")
    ticket = store.issue_ticket(ship["id"], asked["id"])
    store.send_message(ship["id"], room["id"], f"reply-{asked['id']}", "Added notes", ticket["id"])
    store.send_message(ship["id"], room["id"], "post-1", "Hello from my session")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.get_by_text("builder run for Alex Patient")).to_be_visible()
            expect(page.get_by_text("no run ticket")).to_be_visible()



def test_a_grantees_build_reply_is_labelled_with_the_grantee(browser_peer):
    """G17, test 17: a reply from a grant's builder run shows "builder run for Alex Patient, via <grantee>", and a grantee
    name written as HTML shows as text."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(users["patient"]["id"], started["id"], started["code"])
    room = store.create_room(users["patient"]["id"], "Ops", [ship["id"], users["doctor"]["id"]])
    store.rename_user(users["doctor"]["id"], "<b>Dr. Morgan</b>")
    store.make_grant(users["patient"]["id"], users["doctor"]["id"], [ship["id"]], [room["id"]], 24, 5)
    asked = store.send_message(users["doctor"]["id"], room["id"], "a", "@serenity add notes")
    ticket = store.issue_ticket(ship["id"], asked["id"])
    store.send_message(ship["id"], room["id"], f"reply-{asked['id']}", "Added notes", ticket["id"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            label = page.locator(".message", has_text="Added notes").locator(".message-source")
            expect(label).to_have_text("builder run for Alex Patient, via <b>Dr. Morgan</b>")
            assert page.locator(".message-source b").count() == 0


def test_a_room_labels_the_station_notice_by_id_never_by_name(browser_peer):
    """R31, the room UI: the system author's message shows as "Station" with the "station notice" label; a person
    who calls themselves "Station" gets no label."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(users["patient"]["id"], started["id"], started["code"])
    room = store.create_room(users["patient"]["id"], "Ops", [ship["id"], users["doctor"]["id"]])
    store.rename_user(users["doctor"]["id"], "Station")
    store.send_message(users["doctor"]["id"], room["id"], "p", "a person called Station")
    with store.transaction() as db:
        store._post_as_system(db, room["id"], f'notice-{ship["id"]}-m1', "Station notice: the notice itself")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            notice = page.locator(".message", has_text="the notice itself")
            expect(notice.locator(".message-meta").first).to_contain_text("Station")
            expect(notice.locator(".message-source")).to_have_text("station notice")
            expect(page.locator(".message", has_text="a person called Station").locator(".message-source")).to_have_count(0)

def test_a_person_writes_instructions_for_their_ship_and_sees_a_ships_draft(browser_peer):
    """Break caught: instructions can't be written for ships, or a ship's draft looks like the person's own."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(users["patient"]["id"], started["id"], started["code"])
    other = store.confirm_docking(users["doctor"]["id"], *(lambda d: (d["id"], d["code"]))(store.start_docking("defiant", "lab")))
    store.ship_draft(ship["id"], {"title": "Proposed by the ship", "body": "Write tests first."})
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            expect(page.get_by_text("Drafted by Serenity").first).to_be_visible()
            page.get_by_role("button", name="Proposed by the ship").click()
            editor = page.locator("section.editor")
            expect(editor.get_by_text("Drafted by Serenity. Read it before you activate it.")).to_be_visible()
            expect(editor.get_by_text("Unsaved changes")).to_have_count(0)
            open_new_layer(page)
            page.get_by_label("Kind").select_option("instructions")
            expect(page.get_by_role("checkbox", name="Defiant")).to_have_count(0)
            page.get_by_label("Layer title").fill("House rules")
            page.get_by_label("What do you want to share?").fill("Run the tests first.")
            page.get_by_role("checkbox", name="Serenity").check()
            page.get_by_role("button", name="Save private draft").click()
            expect(page.get_by_text("Saved version 2", exact=True)).to_be_visible()
            page.get_by_role("button", name="Preview audience").click()
            page.get_by_role("button", name="Turn on version 2").click()
            expect(page.get_by_text("Active · version 2")).to_be_visible()
    assert store.ship_instructions(ship["id"], "x")["instructions"]


def test_an_unedited_note_shows_no_unsaved_changes_until_one_is_typed(browser_peer):
    """Break caught: every layer opens marked "Unsaved changes" (Task 9's precedence bug); the drafted-layer check alone
    cannot see it for a plain note."""
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    store.create_layer(users["patient"]["id"], {"title": "Plain note", "body": "Hello."})
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            page.get_by_role("button", name="Plain note").click()
            editor = page.locator("section.editor")
            expect(editor.get_by_label("Layer title")).to_have_value("Plain note")
            expect(editor.get_by_label("Kind")).to_have_value("note")
            expect(editor.get_by_text("Private draft", exact=True)).to_be_visible()
            expect(editor.get_by_text("Unsaved changes")).to_have_count(0)
            editor.get_by_label("What do you want to share?").press_sequentially("!")
            page.get_by_role("button", name="Account and sign out").click()  # typing does not rerender; the dialog does
            page.get_by_role("button", name="Close").click()
            expect(editor.get_by_label("What do you want to share?")).to_have_value("!Hello.")
            expect(editor.get_by_text("Unsaved changes", exact=True)).to_be_visible()  # the absence above is not vacuous


def test_the_owner_writes_a_brief_and_carries_it_into_a_new_linked_chat(browser_peer):
    """Break caught: the owner cannot write a brief, it is carried without being chosen, or old messages come with it."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    store.send_message(users["patient"]["id"], room["id"], "old", "An old message for the first audience.")
    brief = "Purpose: a city of AI.\nD1–D9 are decided; Rio Grande builds the brief."
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            expect(panel.get_by_role("heading", name="Room brief")).to_be_visible()
            expect(panel.get_by_text("Visible to members on this station only.")).to_be_visible()
            panel.get_by_role("button", name="Edit brief").click()
            panel.get_by_label("Edit brief").fill(brief)
            panel.get_by_role("button", name="Save brief").click()
            expect(page.locator(".notice", has_text="Room brief saved.")).to_be_visible()  # the announcer repeats it, hidden
            expect(panel.locator(".room-brief-body")).to_have_text(brief)
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            carry = dialog.get_by_role("checkbox", name="Carry the room brief into the new room")
            expect(carry).not_to_be_checked()
            expect(dialog.locator(".carry-brief-text")).to_have_text(brief)
            expect(dialog.get_by_text("Only the brief, if ticked, and the board's open items are carried. Earlier messages stay with their original participants.")).to_be_visible()
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            carry.check()
            dialog.get_by_role("button", name="Start a new linked chat").click()
            expect(page.get_by_text("New room · earlier messages stay in the original chat")).to_be_visible()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text(brief)
            expect(page.locator(".room-brief")).to_contain_text("Carried from the previous room on")
            expect(page.get_by_text("An old message for the first audience.")).to_have_count(0)
    rooms = store.list_rooms(users["doctor"]["id"])
    assert len(rooms) == 1
    carried = store.get_room(users["doctor"]["id"], rooms[0]["id"])["brief"]
    assert (carried["body"], carried["revision"], carried["carried_from"]) == (brief, 1, room["id"])


def test_without_a_brief_the_carry_box_is_hidden(browser_peer):
    """Break caught: a missing or removed brief still offers to carry something, or a removed one can't be written again."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    quiet = store.create_room(patient, "Quiet room", [users["family"]["id"]])
    removed = store.create_room(patient, "Removed brief", [users["family"]["id"]])
    store.save_brief(patient, removed["id"], "Soon gone.", 0)
    store.save_brief(patient, removed["id"], "", 1)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            for target in (quiet, removed):
                page.goto(f"{base}/#chats/{target['id']}")
                page.reload()
                expect(page.locator(".room-brief")).to_contain_text("No brief yet.")
                page.get_by_role("button", name="Change participants").click()
                expect(page.locator("dialog").get_by_role("checkbox", name="Dr. Morgan")).to_be_visible()
                expect(page.get_by_role("checkbox", name="Carry the room brief")).to_have_count(0)
                page.locator("dialog").get_by_role("button", name="Cancel").click()
            page.locator(".room-brief").get_by_role("button", name="Edit brief").click()
            page.get_by_label("Edit brief").fill("Back again.")
            page.get_by_role("button", name="Save brief").click()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text("Back again.")
    assert store.get_room(patient, removed["id"])["brief"]["revision"] == 3


def test_the_add_dialog_says_open_items_are_carried_without_a_brief(browser_peer):
    """Review Focus 1: the help text lived inside the brief's checkbox, which a room without a brief doesn't show, yet
    open board items are carried all the same (work board 5.x). A room with neither shows no help text."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    busy = store.create_room(patient, "Busy room", [users["family"]["id"]])
    store.post_item(patient, busy["id"], "build:panel", "Build the panel", "build")
    quiet = store.create_room(patient, "Quiet room", [users["family"]["id"]])
    carried = "Only the brief, if ticked, and the board's open items are carried. Earlier messages stay with their original participants."
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            for room, count in ((busy, 1), (quiet, 0)):
                page.goto(f"{base}/#chats/{room['id']}")
                page.reload()
                page.get_by_role("button", name="Change participants").click()
                dialog = page.locator("dialog")
                expect(dialog.get_by_role("checkbox", name="Dr. Morgan")).to_be_visible()
                expect(dialog.get_by_text("The new room starts with no messages.", exact=True)).to_be_visible()
                expect(dialog.get_by_text(carried)).to_have_count(count)
                dialog.get_by_role("button", name="Cancel").click()


def settle(page, ready=None):
    """Board clicks are ignored for 400 ms after the panel renders (a double click must not land on what a re-render moved
    under the pointer), so a test waits out the window before it clicks. After a reload the page renders only when its
    reads come back, which on a slow machine is later than the wait would end: pass what the render shows as ready, and
    the wait counts from when it is visible."""
    if ready is not None:
        expect(ready).to_be_visible()
    page.wait_for_timeout(450)


def test_the_board_panel_posts_shows_and_closes_items(browser_peer):
    """Work board 5.2, 5.x: the owner posts an item and it shows waiting; a ship's claim shows after a refresh; the owner
    releases it and marks it done, and it moves to the closed list; the history labels its lines; a title like an HTML
    tag shows literally; the Board view lists two rooms; the add dialog lists what moves; another person sees no post
    button."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(patient, started["id"], started["code"])
    room = store.create_room(patient, "City of AI", [ship["id"], users["family"]["id"]])
    hands = store.create_room(patient, "All hands", [ship["id"]])
    store.post_item(ship["id"], hands["id"], "ops:hands", "Work in All hands", "ops")
    evil = "<img src=x onerror=alert(1)>"
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-board")
            expect(panel.get_by_role("heading", name="Board")).to_be_visible()
            panel.get_by_label("Key").fill("spec:d7")
            panel.get_by_label("Title").fill(evil)
            panel.get_by_label("Kind").select_option("spec")
            panel.get_by_role("button", name="Post item").click()
            item = panel.locator(".board-item", has_text="spec:d7")
            expect(item).to_contain_text(evil)
            expect(item).to_contain_text("waiting")
            assert page.locator(".room-board img").count() == 0
            store.claim(ship["id"], room["id"], "spec:d7", None, 60)
            page.reload()
            expect(item).to_contain_text("taken by Serenity until")
            settle(page)
            item.get_by_role("button", name="Release claim on spec:d7").click()
            expect(item).to_contain_text("Release Serenity's claim on spec:d7?")
            expect(item).to_contain_text("taken by Serenity")  # nothing released before the confirm
            settle(page)
            item.get_by_role("button", name="Yes, release claim on spec:d7").click()
            expect(item).to_contain_text("waiting")
            expect(item).to_be_focused()
            settle(page)
            item.get_by_role("button", name="Mark done spec:d7").click()
            panel.get_by_label("Outcome link").fill("commit:1ff0efb")
            panel.get_by_role("button", name="Mark done spec:d7").click()
            expect(panel.locator(".board-closed .board-item", has_text="spec:d7")).to_contain_text("outcome commit:1ff0efb")
            page.reload()  # the history updates with the room; the panel updates after its own actions (5.2)
            for line, label in (("Posted `spec:d7`", "board"), ("Claimed `spec:d7`", "claim"),
                                ("Released Serenity", "claim"), ("Done `spec:d7`", "board")):
                expect(page.locator(".message", has_text=line).locator(".message-source")).to_have_text(label)
            store.post_item(patient, room["id"], "build:panel", "Build the <b>panel</b>", "build")
            store.post_item(ship["id"], room["id"], "review:panel", "Review the panel", "review")
            page.get_by_role("link", name="Board", exact=True).click()
            expect(page.get_by_role("heading", name="Board", level=1)).to_be_visible()
            expect(page.locator(".board-room")).to_have_count(2)
            expect(page.get_by_text("Work in All hands")).to_be_visible()
            expect(page.get_by_text("Build the <b>panel</b>")).to_be_visible()
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            expect(dialog.get_by_text("Only the brief, if ticked, and the board's open items are carried. Earlier messages stay with their original participants.")).to_be_visible()
            expect(dialog.get_by_text("These 2 open board items, with their links and claims, move to the new room. Drop any that shouldn't first.")).to_be_visible()
            expect(dialog.locator(".carry-board li")).to_have_count(2)
            expect(dialog.locator(".carry-board")).to_contain_text("build:panel Build the <b>panel</b>")
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".room-board .board-item", has_text="build:panel")).to_be_visible()
            expect(page.get_by_role("button", name="Post item")).to_have_count(0)
            expect(page.get_by_role("button", name="Mark done")).to_have_count(0)


def test_a_double_click_on_post_item_posts_once(browser_peer):
    """Review Focus 4: the second submit of a double click would get 409 for the first one's own item and show it as a
    failure; the panel sends one write at a time. The POSTs to /board are counted, so a server that merely refuses the
    second one cannot pass for a client that sent one."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            posts = []
            page.on("request", lambda request: posts.append(request.url) if request.method == "POST" and request.url.endswith("/board") else None)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-board")
            panel.get_by_label("Key").fill("spec:d7")
            panel.get_by_label("Title").fill("Write the D7 spec")
            panel.get_by_role("button", name="Post item").dblclick()
            expect(panel.locator(".board-item", has_text="spec:d7")).to_be_visible()
            expect(page.locator(".notice", has_text="Item posted.")).to_be_visible()
            expect(page.get_by_text("already on this board")).to_have_count(0)
            page.wait_for_timeout(300)
            assert len(posts) == 1, posts
    assert [i["key"] for i in store.room_board(users["patient"]["id"], room["id"])] == ["spec:d7"]


def test_a_120_character_emoji_title_posts_whole_from_the_panel(browser_peer):
    """Review Focus 5: the station counts code points; a maxlength would count UTF-16 units and stop emoji at 60."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [])
    title = "🛰" * 120
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-board")
            assert panel.get_by_label("Title").get_attribute("maxlength") is None
            panel.get_by_label("Key").fill("spec:emoji")
            panel.get_by_label("Title").fill(title)
            panel.get_by_role("button", name="Post item").click()
            expect(panel.locator(".board-item", has_text="spec:emoji")).to_contain_text(title)
    assert store.room_board(users["patient"]["id"], room["id"])[0]["title"] == title


def double_click_apart(page, locator, gap=180):
    """Two real mouse clicks `gap` ms apart on the same spot, as a hurried double click lands."""
    box = locator.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.click(x, y)
    page.wait_for_timeout(gap)
    page.mouse.click(x, y)


def test_drop_and_release_ask_first_and_a_hurried_double_click_touches_nothing(browser_peer):
    """Final review I1: Drop is final, and the first click's re-render moves the next item's Drop under the pointer. Both
    buttons ask inline; two clicks 180 ms apart drop and release nothing and never reach a second item; a confirm drops
    or releases exactly that item; Cancel changes nothing."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(patient, started["id"], started["code"])
    room = store.create_room(patient, "City of AI", [ship["id"]])
    for key in ("spec:a", "spec:b", "spec:c"):
        store.post_item(patient, room["id"], key, f"Item {key}", "spec")
        store.claim(ship["id"], room["id"], key, None, 60)
    states = lambda: {i["key"]: (i["state"], bool(i["claim"])) for i in store.room_board(patient, room["id"])}
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-board")
            item = lambda key: panel.locator(".board-item", has_text=key)
            expect(panel).to_be_visible()
            for name, text in (("Drop spec:a", "Drop spec:a for good? Its key can't be used again."), ("Release claim on spec:a", "Release Serenity's claim on spec:a?")):
                settle(page)
                double_click_apart(page, item("spec:a").get_by_role("button", name=name))
                expect(item("spec:a")).to_contain_text(text)
                page.wait_for_timeout(600)
                assert states() == {"spec:a": ("open", True), "spec:b": ("open", True), "spec:c": ("open", True)}
                item("spec:a").get_by_role("button", name="Cancel").click()
                expect(item("spec:a").get_by_role("button", name=name)).to_be_visible()
                expect(item("spec:a")).to_be_focused()
                settle(page)
            assert states() == {"spec:a": ("open", True), "spec:b": ("open", True), "spec:c": ("open", True)}
            item("spec:b").get_by_role("button", name="Drop spec:b").click()
            settle(page)
            item("spec:b").get_by_role("button", name="Yes, drop spec:b").click()
            expect(panel.locator(".board-closed .board-item", has_text="spec:b")).to_contain_text("dropped")
            expect(page.locator(".notice", has_text="Item dropped. Serenity's claim on it is released.")).to_be_visible()
            expect(panel.locator("#room-board-title")).to_be_focused()
            expect(page.locator(".message", has_text="Dropped `spec:b`").locator(".message-source")).to_have_text("board")  # the room was read again
            settle(page)
            item("spec:c").get_by_role("button", name="Release claim on spec:c").click()
            settle(page)
            item("spec:c").get_by_role("button", name="Yes, release claim on spec:c").click()
            expect(item("spec:c")).to_contain_text("waiting")
            assert states() == {"spec:a": ("open", True), "spec:b": ("dropped", False), "spec:c": ("open", False)}


def test_a_hurried_double_click_at_phone_width_still_touches_nothing(browser_peer):
    """S-4: at 390 px the Cancel button lands under the pointer after the first press of Release; only the click guard
    keeps the second press from cancelling or confirming."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(patient, started["id"], started["code"])
    room = store.create_room(patient, "City of AI", [ship["id"]])
    store.post_item(patient, room["id"], "spec:a", "Item a", "spec")
    store.claim(ship["id"], room["id"], "spec:a", None, 60)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient", viewport={"width": 390, "height": 844}) as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            item = page.locator(".room-board .board-item", has_text="spec:a")
            release = item.get_by_role("button", name="Release claim on spec:a")
            release.scroll_into_view_if_needed()  # mouse clicks go to viewport coordinates
            settle(page)
            double_click_apart(page, release)
            page.wait_for_timeout(600)
            expect(item).to_contain_text("Release Serenity's claim on spec:a?")  # the ask is still open: nothing cancelled
            assert [bool(i["claim"]) for i in store.room_board(patient, room["id"])] == [True]


def test_a_key_press_on_an_ask_is_not_swallowed_by_the_click_guard(browser_peer):
    """The guard is for a double click; Enter on the focused Cancel right after the ask opens closes it."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [])
    store.post_item(patient, room["id"], "spec:a", "Item a", "spec")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            item = page.locator(".room-board .board-item", has_text="spec:a")
            settle(page, ready=item)
            item.get_by_role("button", name="Drop spec:a").click()
            expect(item.get_by_role("button", name="Cancel")).to_be_focused()
            page.keyboard.press("Enter")  # at once, inside the guard window
            expect(item.get_by_role("button", name="Drop spec:a")).to_be_visible()
            expect(item.locator(".board-ask")).to_have_count(0)


def test_a_board_write_made_while_the_next_room_loads_goes_nowhere(browser_peer):
    """M-1: room B is already state.room while its board loads, but room A's panel is still on screen; a click on A's
    confirm must not drop B's item."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room_a = store.create_room(patient, "Room A", [users["family"]["id"]])
    room_b = store.create_room(patient, "Room B", [users["family"]["id"]])
    for room in (room_a, room_b):
        store.post_item(patient, room["id"], "spec:same", "Same key", "spec")
    open_keys = lambda room: [i["key"] for i in store.room_board(patient, room["id"]) if i["state"] == "open"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room_a['id']}")
            page.reload()
            panel = page.locator(".room-board")
            settle(page, ready=panel)
            panel.get_by_role("button", name="Drop spec:same").click()
            confirm = panel.get_by_role("button", name="Yes, drop spec:same")
            expect(confirm).to_be_visible()  # the ask is open on A's panel
            held = []
            page.route(f"**/api/chats/{room_b['id']}/board", lambda route: held.append(route))
            page.evaluate("id => { location.hash = `chats/${id}`; }", room_b["id"])
            for _ in range(50):
                if held:
                    break
                page.wait_for_timeout(100)
            assert held, "room B's board read never started"
            expect(panel).to_have_attribute("data-room", room_a["id"])  # A's panel is still what is shown
            settle(page)
            confirm.click()
            page.wait_for_timeout(400)
            held[0].continue_()
            expect(page.get_by_role("heading", name="Room B")).to_be_visible()
            expect(page.locator(".room-board")).to_have_attribute("data-room", room_b["id"])
    assert open_keys(room_b) == ["spec:same"]
    assert open_keys(room_a) == ["spec:same"]


def test_an_expired_session_during_a_board_write_shows_the_sign_in_prompt(browser_peer):
    """S-2: a 401 on a board write leaves the sign-in prompt, not a blank panel."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, context):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-board")
            panel.get_by_label("Key").fill("spec:late")
            panel.get_by_label("Title").fill("Typed before it ended")
            context.clear_cookies()
            panel.get_by_role("button", name="Post item").click()
            expect(page.get_by_role("heading", name="Sign in to your home")).to_be_visible()
            expect(page.get_by_text("Your session ended. Sign in again; text in an open form has not been sent.")).to_be_visible()
    assert store.room_board(users["patient"]["id"], room["id"]) == []


def test_a_board_form_and_view_do_not_follow_a_new_sign_in_in_the_same_tab(browser_peer):
    """S-3: a started Mark done, a post draft and the Board view belong to the account that made them."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    mine = store.create_room(patient, "Patient only", [])
    shared = store.create_room(patient, "Shared room", [family])
    store.post_item(patient, mine["id"], "spec:mine", "Private to patient", "spec")
    store.post_item(patient, shared["id"], "spec:shared", "Shared item", "spec")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{mine['id']}")
            page.reload()
            panel = page.locator(".room-board")
            settle(page, ready=panel)
            panel.get_by_role("button", name="Mark done spec:mine").click()
            panel.get_by_label("Outcome link").fill("commit:abc1234")
            panel.get_by_label("Key").fill("spec:draft")
            page.get_by_role("link", name="Board", exact=True).click()
            expect(page.locator(".board-room")).to_have_count(2)
            page.get_by_role("button", name="Account and sign out").click()
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.get_by_role("heading", name="Sign in to your home")).to_be_visible()
            page.get_by_label("Username", exact=True).fill("family")
            page.get_by_label("Password", exact=True).fill(browser_peer["password"])
            page.get_by_role("button", name="Sign in").click()
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            page.get_by_role("link", name="Board", exact=True).click()
            expect(page.get_by_role("heading", name="Board", level=1)).to_be_visible()
            expect(page.locator(".board-room")).to_have_count(1)
            expect(page.locator(".board-room")).to_contain_text("Shared room")
            assert "Patient only" not in page.locator("main").inner_text()
            page.get_by_role("link", name="Shared room").click()  # no reload: what the tab still holds is what is under test
            fam_panel = page.locator(".room-board")
            expect(fam_panel.locator(".board-item", has_text="spec:shared")).to_be_visible()
            assert fam_panel.locator("#board-done-form, #board-post-form").count() == 0
            assert "commit:abc1234" not in page.content() and "spec:draft" not in page.content()


def test_a_replaced_rooms_board_takes_no_changes(browser_peer):
    """Final review I2: a replaced room shows its items but offers no Post form and no item buttons, and says why."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.post_item(patient, room["id"], "spec:old", "Closed before", "spec")
    store.drop_item(patient, room["id"], "spec:old")
    store.post_item(patient, room["id"], "spec:open", "Still open", "spec")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-board")
            expect(panel.get_by_role("button", name="Drop spec:open")).to_be_visible()
            expect(panel.get_by_role("button", name="Post item")).to_be_visible()
            replacement = store.add_participants(patient, room["id"], [users["organizer"]["id"]])
            page.reload()
            expect(panel.locator(".board-closed .board-item", has_text="spec:old")).to_be_visible()
            expect(panel.get_by_text("This room was replaced by a newer linked room; its board takes no changes.")).to_be_visible()
            expect(panel.get_by_role("button", name="Post item")).to_have_count(0)
            expect(panel.locator("#board-post-form")).to_have_count(0)
            expect(panel.get_by_role("button")).to_have_count(0)
            page.goto(f"{base}/#chats/{replacement['id']}")
            page.reload()
            expect(panel.get_by_role("button", name="Drop spec:open")).to_be_visible()
            expect(panel.get_by_role("button", name="Post item")).to_be_visible()
            expect(panel.get_by_text("takes no changes")).to_have_count(0)


def test_board_drafts_are_kept_per_room_and_a_failed_done_keeps_its_outcome(browser_peer):
    """Final review I3: a post draft survives a re-render and belongs to its room; a failed done keeps what was typed and
    puts focus back on the outcome."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room_a = store.create_room(patient, "Room A", [users["family"]["id"]])
    room_b = store.create_room(patient, "Room B", [users["family"]["id"]])
    store.post_item(patient, room_a["id"], "spec:x", "Item x", "spec")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room_a['id']}")
            page.reload()
            panel = page.locator(".room-board")
            panel.get_by_label("Key").fill("spec:draft")
            panel.get_by_label("Title").fill("Half typed")
            panel.get_by_label("Kind").select_option("review")
            page.get_by_label("Message", exact=True).fill("hello")
            page.get_by_role("button", name="Send message").click()
            expect(page.locator(".message", has_text="hello")).to_be_visible()  # the room re-rendered
            expect(panel.get_by_label("Key")).to_have_value("spec:draft")
            expect(panel.get_by_label("Title")).to_have_value("Half typed")
            expect(panel.get_by_label("Kind")).to_have_value("review")
            panel.get_by_label("Title").fill("")  # a post the station refuses
            panel.get_by_role("button", name="Post item").click()
            expect(page.locator(".notice.error")).to_be_visible()
            expect(panel.get_by_label("Key")).to_have_value("spec:draft")
            expect(panel.get_by_label("Key")).to_be_focused()  # a refused post leaves focus on the key, as a refused done does on the outcome
            # S-1: the draft's values are escaped where they are put back (value=), not only in text
            panel.get_by_label("Key").fill('"><b>x</b>')
            panel.get_by_label("Title").fill('"><b>y</b>')
            page.get_by_label("Message", exact=True).fill("again")
            page.get_by_role("button", name="Send message").click()
            expect(page.locator(".message", has_text="again")).to_be_visible()  # re-rendered with the draft
            expect(panel.get_by_label("Key")).to_have_value('"><b>x</b>')
            expect(panel.get_by_label("Title")).to_have_value('"><b>y</b>')
            assert panel.locator("b").count() == 0
            panel.get_by_label("Key").fill("spec:draft")
            panel.get_by_label("Title").fill("")
            page.goto(f"{base}/#chats/{room_b['id']}")
            expect(page.get_by_role("heading", name="Room B")).to_be_visible()
            expect(page.locator(".room-board").get_by_label("Key")).to_have_value("")
            expect(page.locator(".room-board").get_by_label("Kind")).to_have_value("build")
            page.goto(f"{base}/#chats/{room_a['id']}")
            expect(page.locator(".room-board").get_by_label("Key")).to_have_value("spec:draft")
            settle(page)
            page.locator(".room-board").get_by_role("button", name="Mark done spec:x").click()
            page.locator(".room-board").get_by_label("Outcome link").fill("not a link")
            page.locator(".room-board").get_by_role("button", name="Mark done spec:x").click()
            expect(page.locator(".notice.error")).to_be_visible()
            outcome = page.locator(".room-board").get_by_label("Outcome link")
            expect(outcome).to_have_value("not a link")
            expect(outcome).to_be_focused()
            outcome.fill('"><b>x</b>')  # S-1: the outcome is put back through value=
            with page.expect_response(lambda r: r.url.endswith("/board/done")):
                page.locator(".room-board").get_by_role("button", name="Mark done spec:x").click()
            page.wait_for_timeout(500)  # the panel is read again and re-rendered after the refusal
            expect(page.locator(".room-board").get_by_label("Outcome link")).to_have_value('"><b>x</b>')
            assert page.locator(".room-board b").count() == 0
    assert [i["state"] for i in store.room_board(patient, room_a["id"])] == ["open"]


def test_board_free_text_is_escaped_in_the_panel_the_view_and_the_flash(browser_peer):
    """Final review I4: names (poster, holder, closer) and a room title that look like tags show as typed and make no
    elements."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    store.rename_user(patient, "<b>x</b>")
    store.rename_user(family, "<u>h</u>")
    room = store.create_room(patient, "<i>Room</i>", [family])
    store.post_item(patient, room["id"], "spec:held", "Held", "spec")
    store.claim(family, room["id"], "spec:held", None, 60)
    store.post_item(patient, room["id"], "spec:gone", "Gone", "spec")
    store.drop_item(patient, room["id"], "spec:gone")
    store.post_item(patient, room["id"], "spec:last", "Last", "spec")
    store.claim(family, room["id"], "spec:last", None, 60)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-board")
            expect(panel.locator(".board-item", has_text="spec:held")).to_contain_text("taken by <u>h</u> until")
            expect(panel.locator(".board-item", has_text="spec:held")).to_contain_text("posted by <b>x</b>")
            expect(panel.locator(".board-closed .board-item", has_text="spec:gone")).to_contain_text("dropped")
            expect(panel.locator(".board-closed .board-item", has_text="spec:gone")).to_contain_text("by <b>x</b>")
            assert panel.locator("b, i, u").count() == 0
            settle(page)
            panel.get_by_role("button", name="Release claim on spec:held").click()
            expect(panel.locator(".board-ask")).to_contain_text("Release <u>h</u>'s claim on spec:held?")
            assert panel.locator("b, i, u").count() == 0
            settle(page)
            panel.get_by_role("button", name="Drop spec:last").click()
            settle(page)
            panel.get_by_role("button", name="Yes, drop spec:last").click()
            flash = page.locator(".notice", has_text="Item dropped.")
            expect(flash).to_contain_text("<u>h</u>'s claim on it is released.")
            assert page.locator(".notice b, .notice u").count() == 0
            page.get_by_role("link", name="Board", exact=True).click()
            expect(page.get_by_role("heading", name="Board", level=1)).to_be_visible()
            view = page.locator(".board-room")
            expect(view.locator("h2")).to_have_text("<i>Room</i>")
            expect(view).to_contain_text("taken by <u>h</u> until")
            expect(view).to_contain_text("posted by <b>x</b>")
            assert page.locator(".board-room b, .board-room i, .board-room u").count() == 0


def test_release_is_offered_only_to_the_owner_the_holder_and_the_holders_owner(browser_peer):
    """Final review M8: a member who is none of those sees no Release, whatever else they can read."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family, doctor = users["patient"]["id"], users["family"]["id"], users["doctor"]["id"]
    started = store.start_docking("rio-grande", "sam-mac")
    ship = store.confirm_docking(family, started["id"], started["code"])  # Sam Family's ship
    room = store.create_room(patient, "City of AI", [family, doctor, ship["id"]])
    store.post_item(patient, room["id"], "spec:held", "Held", "spec")
    store.claim(ship["id"], room["id"], "spec:held", None, 60)
    with sync_playwright() as playwright:
        for who, offered in (("patient", True), ("family", True), ("doctor", False)):
            with signed_in_browser(playwright, browser_peer, who) as (page, _):
                page.goto(f"{base}/#chats/{room['id']}")
                page.reload()
                item = page.locator(".room-board .board-item", has_text="spec:held")
                expect(item).to_contain_text("taken by")
                expect(item.get_by_role("button", name="Release claim on spec:held")).to_have_count(1 if offered else 0)


def test_linked_and_dropped_lines_are_labelled_board(browser_peer):
    """Final review M8: BOARD_WORDS covers all four fixed first words."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.post_item(patient, room["id"], "spec:l", "Linked one", "spec")
    store.link_item(patient, room["id"], "spec:l", "commit:1ff0efb")
    store.drop_item(patient, room["id"], "spec:l")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            for line in ("Posted `spec:l`", "Linked `spec:l`", "Dropped `spec:l`"):
                expect(page.locator(".message", has_text=line).locator(".message-source")).to_have_text("board")


def test_opening_a_room_from_the_chat_list_loads_its_board_and_a_new_room_opens_from_the_board_view(browser_peer):
    """Final review M8, M5: openChat loads the board; a Board-view link to a room made after the page loaded opens that
    room, not "Choose a chat"."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "Listed room", [users["family"]["id"]])
    store.post_item(patient, room["id"], "spec:listed", "From the list", "spec")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Chats", exact=True).click()
            page.get_by_role("button", name="Listed room").first.click()
            expect(page.locator(".room-board .board-item", has_text="spec:listed")).to_be_visible()
            fresh = store.create_room(patient, "Made after load", [users["family"]["id"]])
            store.post_item(patient, fresh["id"], "spec:fresh", "Fresh work", "spec")
            page.get_by_role("link", name="Board", exact=True).click()
            page.get_by_role("link", name="Made after load").click()
            expect(page.get_by_role("heading", name="Made after load", level=2)).to_be_visible()
            expect(page.locator(".room-board .board-item", has_text="spec:fresh")).to_be_visible()


def test_a_member_reads_the_brief_but_cannot_edit_it(browser_peer):
    """Break caught: a member who is not the owner can change the brief, or cannot see it."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    store.save_brief(users["patient"]["id"], room["id"], "Rio Grande builds the brief.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text("Rio Grande builds the brief.")
            expect(page.locator(".room-brief")).to_contain_text("Visible to members on this station only.")
            expect(page.get_by_role("button", name="Edit brief")).to_have_count(0)
            expect(page.get_by_label("Edit brief")).to_have_count(0)
            expect(page.get_by_role("button", name="Save brief")).to_have_count(0)


def test_brief_text_is_shown_literally(browser_peer):
    """Break caught: a brief's text is read as markup in the panel or the dialog."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    hostile = '<b>bold?</b> <img src=x onerror="document.title=\'pwned\'">'
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    store.save_brief(users["patient"]["id"], room["id"], hostile, 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text(hostile)
            expect(page.locator(".room-brief b, .room-brief img")).to_have_count(0)
            page.get_by_role("button", name="Change participants").click()
            expect(page.locator("dialog .carry-brief-text")).to_have_text(hostile)
            expect(page.locator("dialog b, dialog img")).to_have_count(0)
            assert page.title() != "pwned"


def test_a_save_from_a_stale_tab_keeps_the_text_and_shows_the_newer_brief(browser_peer):
    """Review focus: another tab saved first. Nothing is overwritten unseen, and the typed text is not lost."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.save_brief(patient, room["id"], "First brief.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            page.get_by_role("button", name="Edit brief").click()
            page.get_by_label("Edit brief").fill("My edit from this tab.")
            store.save_brief(patient, room["id"], "Saved in another tab.", 1)
            page.get_by_role("button", name="Save brief").click()
            expect(page.locator("#brief-status")).to_contain_text("A newer brief was saved while you were editing")
            expect(page.get_by_label("Edit brief")).to_have_value("My edit from this tab.")
            expect(page.locator(".room-brief .room-brief-body")).to_have_text("Saved in another tab.")
            assert store.get_room(patient, room["id"])["brief"]["body"] == "Saved in another tab."
            page.get_by_role("button", name="Save brief").click()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text("My edit from this tab.")
    assert store.get_room(patient, room["id"])["brief"]["revision"] == 3


def test_a_carry_refused_for_a_newer_brief_shows_it_and_carries_it_on_a_second_tick(browser_peer):
    """Review: after a 409 the dialog must show the newer brief, unticked, or the owner is stuck on the old revision."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, doctor = users["patient"]["id"], users["doctor"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.save_brief(patient, room["id"], "Plan for everyone.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            expect(dialog.locator(".carry-brief-text")).to_have_text("Plan for everyone.")
            store.save_brief(patient, room["id"], "Plan for everyone, revised.", 1)  # another tab
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            dialog.get_by_role("checkbox", name="Carry the room brief").check()
            dialog.get_by_role("button", name="Start a new linked chat").click()
            expect(dialog.get_by_role("alert")).to_contain_text("The room brief changed since you opened this.")
            expect(dialog.locator(".carry-brief-text")).to_have_text("Plan for everyone, revised.")
            expect(dialog.get_by_role("checkbox", name="Carry the room brief")).not_to_be_checked()
            expect(dialog.get_by_role("checkbox", name="Dr. Morgan")).to_be_checked()
            assert store.list_rooms(doctor) == []
            dialog.get_by_role("checkbox", name="Carry the room brief").check()
            dialog.get_by_role("button", name="Start a new linked chat").click()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text("Plan for everyone, revised.")
    rooms = store.list_rooms(doctor)
    assert len(rooms) == 1 and store.get_room(doctor, rooms[0]["id"])["brief"]["body"] == "Plan for everyone, revised."


def test_a_replaced_room_offers_no_add_and_a_stale_add_says_why(browser_peer):
    """Work board 8.4 (final review): a room another add replaced takes no more members. A page opened before that add
    gets the station's 409 in the dialog, not the brief's message, and nothing is added. After a reload the replaced
    room offers no "Change participants" (its other controls stay), and its replacement does."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, doctor = users["patient"]["id"], users["doctor"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.save_brief(patient, room["id"], "Plan for everyone.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            expect(dialog.get_by_role("checkbox", name="Dr. Morgan")).to_be_visible()
            replacement = store.add_participants(patient, room["id"], [users["organizer"]["id"]])  # another tab
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            dialog.get_by_role("checkbox", name="Carry the room brief").check()
            dialog.get_by_role("button", name="Start a new linked chat").click()
            expect(dialog.get_by_role("alert")).to_have_text("This room was replaced by a newer linked room; add members there")
            assert store.list_rooms(doctor) == []
            dialog.get_by_role("button", name="Cancel").click()
            page.reload()
            expect(page.get_by_role("button", name="Remove Sam Family from this room")).to_be_visible()
            expect(page.get_by_role("button", name="Change participants")).to_have_count(0)
            page.goto(f"{base}/#chats/{replacement['id']}")
            page.reload()
            expect(page.get_by_role("button", name="Change participants")).to_be_visible()


def test_the_brief_editor_saves_4000_emoji_and_shows_the_limit_past_it(browser_peer):
    """Review focus: a browser's maxlength counts UTF-16 units, so the editor has none and shows the station's limit."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            page.get_by_role("button", name="Edit brief").click()
            page.get_by_label("Edit brief").fill("😀" * 4001)
            page.get_by_role("button", name="Save brief").click()
            expect(page.locator("#brief-status")).to_have_text("A brief is at most 4,000 characters. Your brief is still here.")
            expect(page.get_by_label("Edit brief")).to_have_value("😀" * 4001)
            page.get_by_label("Edit brief").fill("😀" * 4000)
            page.get_by_role("button", name="Save brief").click()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text("😀" * 4000)
    assert store.get_room(patient, room["id"])["brief"]["body"] == "😀" * 4000


def test_a_double_click_on_save_brief_saves_once(browser_peer):
    """Review: a second submit while the first is saving would read as a false "newer brief" conflict."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.save_brief(patient, room["id"], "First brief.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            puts = []
            page.on("request", lambda request: puts.append(request.url) if request.method == "PUT" else None)
            page.get_by_role("button", name="Edit brief").click()
            page.get_by_label("Edit brief").fill("Saved once.")
            page.get_by_role("button", name="Save brief").dblclick()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text("Saved once.")
            expect(page.get_by_text("A newer brief was saved")).to_have_count(0)
            assert len(puts) == 1
    assert store.get_room(patient, room["id"])["brief"]["revision"] == 2


def test_a_failed_brief_save_returns_focus_to_the_editor(browser_peer):
    """Break caught: the 4,000 limit is learned only from the error, and the rerender drops focus to the page."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            page.locator(".room-brief").get_by_role("button", name="Edit brief").click()
            page.get_by_label("Edit brief").fill("x" * 4001)
            page.get_by_role("button", name="Save brief").click()
            expect(page.locator("#brief-status.error")).to_contain_text("4,000")
            assert page.evaluate("document.activeElement.id") == "brief-body"
    assert store.get_room(users["patient"]["id"], room["id"])["brief"] is None


def test_a_carry_conflict_returns_focus_into_the_dialog(browser_peer):
    """Break caught: after the 409 the dialog rerenders and focus falls out of it."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.save_brief(patient, room["id"], "First.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            dialog.get_by_role("checkbox", name="Carry the room brief into the new room").check()
            store.save_brief(patient, room["id"], "Second.", 1)  # saved after the dialog opened
            dialog.get_by_role("button", name="Start a new linked chat").click()
            expect(dialog.get_by_role("alert")).to_contain_text("room brief changed")
            assert page.evaluate("document.activeElement.closest('dialog') !== null")
            assert page.evaluate("document.activeElement.name") == "carry-brief"


def two_layers(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    first = store.create_layer(owner, {"title": "Alpha layer", "body": "Alpha body."})
    second = store.create_layer(owner, {"title": "Beta layer", "body": "Beta body."})
    return first, second


def hold_revisions(page, layer_id):
    """Hold back the revisions fetch of one layer, so the old editor stays on screen while that layer is opening."""
    held = []
    page.route(f"**/api/layers/{layer_id}/revisions", lambda route: held.append(route))
    return held


def test_typing_in_the_old_editor_while_another_layer_opens_stays_with_the_old_layer(browser_peer):
    """Break caught: while a layer's revisions load the old editor is still on screen but the selection is already the
    new layer, so the old form's text was filed as the new layer's unsaved edit."""
    first, second = two_layers(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            page.get_by_role("button", name="Alpha layer").click()
            expect(page.get_by_label("Layer title")).to_have_value("Alpha layer")
            held = hold_revisions(page, second["id"])
            page.get_by_role("button", name="Beta layer").click()
            page.wait_for_url(lambda url: second["id"] in url)
            expect(page.get_by_label("Layer title")).to_have_value("Alpha layer")  # the old editor, still on screen
            page.get_by_label("Layer title").fill("Alpha typed")
            assert held
            for route in held:
                route.continue_()
            title = page.get_by_label("Layer title")
            expect(title).to_have_value("Beta layer")
            expect(page.locator("section.editor").get_by_text("Unsaved changes")).to_have_count(0)
            page.get_by_role("button", name="Alpha layer").click()
            expect(page.get_by_label("Layer title")).to_have_value("Alpha typed")
            expect(page.locator("section.editor").get_by_text("Unsaved changes", exact=True)).to_be_visible()


def test_save_clicked_while_another_layer_opens_sends_nothing_to_the_new_layer(browser_peer):
    """Break caught: Save in the switching window PUT the old form's values to the layer being opened."""
    first, second = two_layers(browser_peer)
    puts = []
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.on("request", lambda request: puts.append(request.url) if request.method == "PUT" else None)
            page.get_by_role("link", name="My sharing layers").click()
            page.get_by_role("button", name="Alpha layer").click()
            expect(page.get_by_label("Layer title")).to_have_value("Alpha layer")
            held = hold_revisions(page, second["id"])
            page.get_by_role("button", name="Beta layer").click()
            page.wait_for_url(lambda url: second["id"] in url)
            page.get_by_label("Layer title").fill("Alpha typed")
            page.get_by_role("button", name="Save private draft").click()
            page.wait_for_timeout(300)
            for route in held:
                route.continue_()
            expect(page.get_by_label("Layer title")).to_have_value("Beta layer")
            page.wait_for_timeout(300)
    assert not [url for url in puts if second["id"] in url], puts
    assert browser_peer["app"].state.store.get_layer(browser_peer["users"]["patient"]["id"], second["id"])["title"] == "Beta layer"


def test_new_layer_has_the_same_window_closed(browser_peer):
    """Break caught: the same switch window exists for "New layer", whose editor opens after one fetch."""
    first, _ = two_layers(browser_peer)
    puts = []
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.on("request", lambda request: puts.append(request.url) if request.method == "PUT" else None)
            page.get_by_role("link", name="My sharing layers").click()
            page.get_by_role("button", name="Alpha layer").click()
            expect(page.get_by_label("Layer title")).to_have_value("Alpha layer")
            held = []
            page.route("**/api/layers/*/revisions", lambda route: held.append(route))
            page.get_by_role("button", name="New layer").click()
            page.wait_for_url(lambda url: "#layers/" in url and first["id"] not in url)
            page.get_by_label("Layer title").fill("Alpha typed")
            page.get_by_role("button", name="Save private draft").click()
            page.wait_for_timeout(300)
            for route in held:
                route.continue_()
            expect(page.get_by_label("Layer title")).to_have_value("Untitled")
            expect(page.locator("section.editor").get_by_text("Unsaved changes")).to_have_count(0)
            page.wait_for_timeout(300)
    assert puts == [], puts


def test_turn_off_public_link_in_the_old_editor_during_a_switch_leaves_the_new_layer_public(browser_peer):
    """Break caught: buttons in the old editor act on selectedLayer(), which is already the layer being opened."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    first = store.create_layer(owner, {"title": "Alpha layer", "body": "A.", "public": True})
    second = store.create_layer(owner, {"title": "Beta layer", "body": "B.", "public": True})
    store.activate_layer(owner, first["id"], first["version"])
    store.activate_layer(owner, second["id"], second["version"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="My sharing layers").click()
            page.get_by_role("button", name="Alpha layer").click()
            expect(page.get_by_label("Layer title")).to_have_value("Alpha layer")
            held = hold_revisions(page, second["id"])
            page.get_by_role("button", name="Beta layer").click()
            page.wait_for_url(lambda url: second["id"] in url)
            page.get_by_role("button", name="Turn off public link").click()
            page.wait_for_timeout(300)
            for route in held:
                route.continue_()
            expect(page.get_by_label("Layer title")).to_have_value("Beta layer")
            page.wait_for_timeout(300)
    assert store.active_layer(second["id"], public=True)["body"] == "B."
    assert store.active_layer(first["id"], public=True)["body"] == "A."


def test_an_instructions_layer_switched_back_to_a_note_shows_note_mode(browser_peer):
    """Break caught: the instructions form has no public input, so reading it when switching back threw."""
    errors = []
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.get_by_role("link", name="My sharing layers").click()
            open_new_layer(page)
            page.get_by_label("Kind").select_option("instructions")
            expect(page.get_by_label("Kind")).to_have_value("instructions")
            expect(page.get_by_role("checkbox", name="Anyone with the public link")).to_have_count(0)
            page.get_by_label("Kind").select_option("note")
            expect(page.get_by_label("Kind")).to_have_value("note")
            expect(page.get_by_role("checkbox", name="Anyone with the public link")).to_have_count(1)
    assert errors == [], errors


def test_a_received_room_marks_unverified_words_and_shows_only_this_stations_delivery_state(browser_peer):
    """Federation follow-ups (spec 2026-10-14-federation-followups-design.md), F1 and F2 in the browser. Words the
    room's host attributes to the signed-in person without proof read as unverified, never "You". A host's message that
    carries a delivery state and reuses the client id of the person's own delivered reply shows no delivery text."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    here, remote = browser_peer["app"].state.federation, browser_peer["remote"]
    there, casey, patient = remote["federation"], remote["user"]["id"], users["patient"]["id"]
    paired = here.pair(users["organizer"]["id"], browser_peer["remote_card"])  # pairing is an admin's act
    card = Federation(store, endpoint="https://localhost:7435").card(patient)  # this station's identity, an endpoint
    contact = there.pair(casey, card)
    room = remote["store"].create_room(casey, "Hosted elsewhere", [contact["id"]])
    there.sync_once(send=lambda card, prepare: here.receive(prepare()))
    key = f"{there.identity.peer_id}:{room['id']}"
    store.send_message(patient, key, "reply-1", "my real words")
    here.sync_once(send=lambda card, prepare: there.receive(prepare()))  # delivered; the host never echoes it back

    def host_says(message_id, author_id, client_id, body, created, **extra):
        with remote["store"].transaction() as db:
            snapshot = there._room_snapshot(db, db.execute("SELECT * FROM rooms WHERE id=?", (room["id"],)).fetchone())
        message = {"id": message_id, "room_id": room["id"], "author_id": author_id, "client_message_id": client_id,
                   "body": body, "epoch": 1, "created": created, **extra}
        assert here.receive(there.identity.envelope(
            destination=here.identity.peer_id, actor=casey, resource_id=room["id"], revision=1,
            action="room.message", recipients=[patient], payload={**snapshot, "message": message}))["ok"]

    # Local rooms keep their own delivery text: a plain one has no delivery ("Saved here"); one with a remote member
    # has a delivery row matching its message, which the page reads.
    plain = store.create_room(patient, "Only us", [users["family"]["id"]])
    store.send_message(patient, plain["id"], "plain-1", "kept at home")
    shared = store.create_room(patient, "Shared out", [paired["id"]])
    store.send_message(patient, shared["id"], "shared-1", "sent to Casey")
    here.sync_once(send=lambda card, prepare: there.receive(prepare()))

    host_says("m-forged", f"{here.identity.peer_id}:{patient}", "forged-1", "I approve the merge", 5.0)
    host_says("m-claims", f"{there.identity.peer_id}:{casey}", "reply-1", "the host's own words", 6.0,
              state="delivered")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Connections", exact=True).click()
            # The person's reply is delivered and the page knows it, so a client-id guess would find it.
            expect(page.locator(".item-main", has_text="Hosted elsewhere").get_by_text("Send reply · Delivered")).to_be_visible()
            page.goto(f"{base}/#chats/{quote(key, safe='')}")
            page.reload()
            forged = page.locator(".message", has_text="I approve the merge")
            expect(forged.locator(".message-meta").first).to_have_text(
                "Unverified: the room's host says this is from someone on this station")
            expect(forged).to_have_class("message unverified")
            expect(forged).to_have_css("border-top-style", "dashed")
            expect(forged).to_have_css("border-top-width", "1px")
            expect(forged.locator(".message-meta").last).not_to_contain_text("Delivered")
            expect(forged.locator(".message-meta").last).not_to_contain_text("Saved here")
            claims = page.locator(".message", has_text="the host's own words")
            expect(claims).to_be_visible()
            expect(claims.locator(".message-meta").first).not_to_contain_text("Unverified")
            expect(claims).to_have_class("message")
            expect(claims.locator(".message-meta").last).not_to_contain_text("Delivered")
            expect(claims.locator(".message-meta").last).not_to_contain_text("Saved here")
            mine = page.locator(".message", has_text="my real words")
            expect(mine.locator(".message-meta").first).to_have_text("You")
            expect(mine.locator(".message-meta").last).to_contain_text("Delivered")
            page.goto(f"{base}/#chats/{plain['id']}")
            page.reload()
            expect(page.locator(".message", has_text="kept at home").locator(".message-meta").last).to_contain_text("Saved here")
            page.goto(f"{base}/#chats/{shared['id']}")
            page.reload()
            expect(page.locator(".message", has_text="sent to Casey").locator(".message-meta").last).to_contain_text("Delivered")


def docked_ship(store, owner, name="rio-grande"):
    started = store.start_docking(name, "pi")
    return store.confirm_docking(owner, started["id"], started["code"])


SHIP_LINE = "Written by Rio Grande, a ship, not the room's owner"
SHIP_WARNING = "This text was written by Rio Grande, a ship. Saving makes all of it yours, so read it all first."


def test_a_ship_written_brief_is_marked_as_a_ships(browser_peer):
    """Break caught (R10): a ship's revision reads as the owner's under the brief, on a carried brief or in the carry
    dialog, or a display name decides the mark. Review Focus 3: the editor warns on a carried brief a ship wrote."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    ship = docked_ship(store, patient)
    room = store.create_room(patient, "City of AI", [users["family"]["id"], ship["id"]])
    store.save_ship_brief(ship["id"], room["id"], "Purpose: a city of AI. Rio Grande keeps this current.", 0)
    mine = store.create_room(patient, "Quiet room", [users["family"]["id"]])
    store.save_brief(patient, mine["id"], "The owner's own words.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):  # a member sees the same marks
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".room-brief-author")).to_have_text(f"Ship {SHIP_LINE}")
            expect(page.locator(".room-brief-author .brief-ship-tag")).to_have_text("Ship")
            page.goto(f"{base}/#chats/{mine['id']}")
            page.reload()
            expect(page.locator(".room-brief-author")).to_have_text("Written by the room's owner, Alex Patient")
            expect(page.locator(".brief-ship-tag")).to_have_count(0)
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{mine['id']}")
            page.reload()
            expect(page.locator(".room-brief-author")).to_have_text("Written by you")
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".room-brief-author")).to_have_text(f"Ship {SHIP_LINE}")
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            expect(dialog.locator(".carry-brief-author")).to_have_text(f"Ship {SHIP_LINE}")
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            dialog.get_by_role("checkbox", name="Carry the room brief into the new room").check()
            dialog.get_by_role("button", name="Start a new linked chat").click()
            panel = page.locator(".room-brief")
            expect(panel).to_contain_text("Carried from the previous room on")
            expect(panel.locator(".room-brief-author")).to_have_text(f"Ship {SHIP_LINE}")
            panel.get_by_role("button", name="Edit brief").click()  # Review Focus 3: the carry kept the ship as author
            expect(panel.locator(".brief-warning")).to_have_text(SHIP_WARNING)
            panel.get_by_role("button", name="Cancel").click()
            with store.transaction() as db:  # a display name can't move the mark
                db.execute("UPDATE users SET name=? WHERE id=?", ("Alex Patient (room owner)", ship["id"]))
            page.reload()
            expect(page.locator(".room-brief-author")).to_have_text(
                "Ship Written by Alex Patient (room owner), a ship, not the room's owner")
    [carried_room] = store.list_rooms(users["doctor"]["id"])
    carried = store.get_room(users["doctor"]["id"], carried_room["id"])["brief"]
    assert (carried["author_id"], carried["author_kind"], carried["carried_from"]) == (ship["id"], "ship", room["id"])


def test_saving_a_ships_text_warns_that_it_becomes_the_owners(browser_peer):
    """Break caught (R10, R13): the owner saves a ship's text unwarned, by "Edit brief" or by "Use this text", or is
    warned about his own; after Save the revision and its notice are his."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    ship = docked_ship(store, patient)
    room = store.create_room(patient, "City of AI", [users["family"]["id"], ship["id"]])
    store.save_brief(patient, room["id"], "The owner's first words.", 0)                  # r1, his
    store.save_ship_brief(ship["id"], room["id"], "Rio Grande's words, all of them.", 1)  # r2, the ship's
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Edit brief").click()
            expect(panel.locator(".brief-warning")).to_have_text(SHIP_WARNING)
            panel.get_by_role("button", name="Cancel").click()
            panel.get_by_role("button", name="Brief history", exact=True).click()
            rows = panel.locator(".brief-revision")
            expect(rows).to_have_count(2)
            rows.filter(has_text="The owner's first words.").get_by_role("button", name="Use this text").click()
            expect(panel.get_by_label("Edit brief")).to_have_value("The owner's first words.")
            expect(panel.locator(".brief-warning")).to_have_count(0)  # his own text: no warning
            rows.filter(has_text="Rio Grande's words").get_by_role("button", name="Use this text").click()
            expect(panel.get_by_label("Edit brief")).to_have_value("Rio Grande's words, all of them.")
            expect(panel.locator(".brief-warning")).to_have_text(SHIP_WARNING)
            panel.get_by_role("button", name="Save brief").click()
            expect(panel.locator(".room-brief-body")).to_have_text("Rio Grande's words, all of them.")
            expect(panel.locator(".room-brief-author")).to_have_text("Written by you")
    view = store.get_room(patient, room["id"])
    assert (view["brief"]["revision"], view["brief"]["author_id"], view["brief"]["author_kind"]) == (3, patient, "person")
    assert view["messages"][-1]["body"] == (
        "Station notice: the room brief is now revision 3, written by the room's owner: Alex Patient. station_read shows it.")


def test_the_owner_restores_an_earlier_revision_from_history(browser_peer):
    """Break caught (R13, R12): an earlier revision can't be got back, a restore makes anything but a new revision of
    the owner's, or an old revision's text is read as markup."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    ship = docked_ship(store, patient)
    room = store.create_room(patient, "City of AI", [users["family"]["id"], ship["id"]])
    old = "<b>Purpose:</b> the first plan. <img src=x onerror=\"document.title='pwned'\">"
    store.save_brief(patient, room["id"], old, 0)                                  # r1, the owner's
    store.save_ship_brief(ship["id"], room["id"], "A ship's later summary.", 1)    # r2
    store.save_brief(patient, room["id"], "", 2)                                    # r3: removed
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Brief history", exact=True).click()
            rows = panel.locator(".brief-revision")
            expect(rows).to_have_count(3)
            expect(rows.nth(0)).to_contain_text("Removed")
            expect(rows.nth(0).get_by_role("button", name="Use this text")).to_have_count(0)
            expect(rows.nth(1).locator(".brief-ship-tag")).to_have_text("Ship")
            expect(rows.nth(2).locator(".brief-revision-body")).to_have_text(old)
            expect(panel.locator(".brief-history b, .brief-history img")).to_have_count(0)
            rows.nth(2).get_by_role("button", name="Use this text").click()
            expect(panel.get_by_label("Edit brief")).to_have_value(old)
            expect(panel.locator(".brief-warning")).to_have_count(0)
            panel.get_by_role("button", name="Save brief").click()
            expect(panel.locator(".room-brief-body")).to_have_text(old)
            expect(panel.locator(".room-brief-author")).to_have_text("Written by you")
            assert page.title() != "pwned"
    view = store.get_room(patient, room["id"])
    assert (view["brief"]["body"], view["brief"]["revision"], view["brief"]["author_id"]) == (old, 4, patient)
    assert view["messages"][-1]["body"] == (
        "Station notice: the room brief is now revision 4, written by the room's owner: Alex Patient. station_read shows it.")


def test_a_member_sees_no_history(browser_peer):
    """Break caught (R12): a member who isn't the owner can open the brief's history, which holds text the owner
    removed on purpose."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.save_brief(patient, room["id"], "Removed on purpose: the old plan.", 0)
    store.save_brief(patient, room["id"], "The plan now.", 1)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".room-brief .room-brief-body")).to_have_text("The plan now.")
            expect(page.get_by_role("button", name="Brief history")).to_have_count(0)
            expect(page.get_by_text("Removed on purpose")).to_have_count(0)
            status = page.evaluate(f"fetch('/api/chats/{room['id']}/brief/revisions').then((r) => r.status)")
            assert status == 403  # and the station refuses it too


def test_a_ship_saving_while_the_owner_edits_keeps_his_text(browser_peer):
    """Review Focus 2: the owner opened his own brief; meanwhile his ship saves. His Save gets the 409, the panel shows
    the ship's newer brief marked as a ship's, and his text stays in the box with no warning. His second Save makes
    his text the newest revision, his."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    ship = docked_ship(store, patient)
    room = store.create_room(patient, "City of AI", [users["family"]["id"], ship["id"]])
    store.save_brief(patient, room["id"], "The owner's plan.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Edit brief").click()
            panel.get_by_label("Edit brief").fill("The owner's plan, revised by him.")
            store.save_ship_brief(ship["id"], room["id"], "The ship's summary of the plan.", 1)
            panel.get_by_role("button", name="Save brief").click()
            expect(page.locator("#brief-status")).to_contain_text("A newer brief was saved while you were editing")
            expect(panel.locator(".room-brief-body")).to_have_text("The ship's summary of the plan.")
            expect(panel.locator(".room-brief-author")).to_have_text(f"Ship {SHIP_LINE}")
            expect(panel.get_by_label("Edit brief")).to_have_value("The owner's plan, revised by him.")
            expect(panel.locator(".brief-warning")).to_have_count(0)
            panel.get_by_role("button", name="Save brief").click()
            expect(panel.locator(".room-brief-body")).to_have_text("The owner's plan, revised by him.")
            expect(panel.locator(".room-brief-author")).to_have_text("Written by you")
    brief = store.get_room(patient, room["id"])["brief"]
    assert (brief["revision"], brief["author_id"]) == (3, patient)


def test_the_ship_warning_goes_while_the_box_is_blank(browser_peer):
    """Follow-up from the final reviews: the editor warns that saving makes a ship's text the owner's even when he has
    emptied the box, though Save then removes the brief. The warning hides while the box is blank (trimmed) and comes
    back with text."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    ship = docked_ship(store, patient)
    room = store.create_room(patient, "City of AI", [users["family"]["id"], ship["id"]])
    store.save_ship_brief(ship["id"], room["id"], "Rio Grande's words, all of them.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Edit brief").click()
            box = panel.get_by_label("Edit brief")
            expect(panel.locator(".brief-warning")).to_be_visible()
            box.fill("")
            expect(panel.locator(".brief-warning")).to_be_hidden()
            box.fill(" \n\t ")
            expect(panel.locator(".brief-warning")).to_be_hidden()
            box.fill("Something again.")
            expect(panel.locator(".brief-warning")).to_have_text(SHIP_WARNING)
            box.fill("")
            panel.get_by_role("button", name="Save brief").click()
            expect(panel.locator(".room-brief-body")).to_have_count(0)
    assert store.get_room(patient, room["id"])["brief"] is None


def test_the_blank_box_keeps_the_warning_hidden_through_a_re_render(browser_peer):
    """Fix round 1: the render-time `hidden` matters when the editor re-renders with a blank box: the ask that "Use this
    text" opens over his blanking, and a failed Save."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    ship = docked_ship(store, patient)
    room = store.create_room(patient, "City of AI", [users["family"]["id"], ship["id"]])
    store.save_brief(patient, room["id"], "The owner's first words.", 0)
    store.save_ship_brief(ship["id"], room["id"], "Rio Grande's words, all of them.", 1)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Brief history", exact=True).click()
            expect(panel.locator(".brief-revision")).to_have_count(2)
            panel.get_by_role("button", name="Edit brief").click()
            expect(panel.locator(".brief-warning")).to_be_visible()
            panel.get_by_label("Edit brief").fill("")
            expect(panel.locator(".brief-warning")).to_be_hidden()
            panel.locator(".brief-revision").filter(has_text="The owner's first words.").get_by_role("button", name="Use this text").click()
            expect(panel.locator(".board-ask")).to_be_visible()  # the editor re-rendered, blank
            expect(panel.locator(".brief-warning")).to_be_hidden()
            panel.locator(".board-ask").get_by_role("button", name="Cancel").click()
            page.route("**/api/chats/*/brief", lambda route: route.fulfill(
                status=500, content_type="application/json", body=json.dumps({"error": "Save is down"}))
                if route.request.method == "PUT" else route.fallback())
            panel.get_by_role("button", name="Save brief").click()
            expect(panel.locator("#brief-status")).to_contain_text("Save is down")  # re-rendered after the failure
            expect(panel.locator(".brief-warning")).to_be_hidden()


def test_an_empty_history_says_so(browser_peer):
    """Follow-up from the final reviews: for a room that never had a brief, "Brief history" showed nothing under its
    heading."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "Never had a brief", [users["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Brief history", exact=True).click()
            expect(panel.locator(".brief-history h4")).to_have_text("Brief history")
            expect(panel.locator(".brief-history")).to_contain_text("No revisions yet.")
            expect(panel.locator(".brief-revision")).to_have_count(0)


def test_use_this_text_asks_before_replacing_unsaved_typing(browser_peer):
    """Follow-up from the final reviews: "Use this text" replaced an open editor's typed text silently. When the text
    differs from what the editor opened with it asks first, inline; Cancel keeps the typing, Yes replaces it. An
    editor left as it opened is replaced without a question."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.save_brief(patient, room["id"], "First words.", 0)
    store.save_brief(patient, room["id"], "Second words.", 1)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Brief history", exact=True).click()
            rows = panel.locator(".brief-revision")
            expect(rows).to_have_count(2)
            panel.get_by_role("button", name="Edit brief").click()
            box = panel.get_by_label("Edit brief")
            rows.filter(has_text="First words.").get_by_role("button", name="Use this text").click()
            expect(box).to_have_value("First words.")  # untouched editor: no question
            expect(panel.locator(".board-ask")).to_have_count(0)
            box.fill("My unsaved <b>typing</b>.")
            rows.filter(has_text="Second words.").get_by_role("button", name="Use this text").click()
            ask = panel.locator(".board-ask")
            expect(ask).to_contain_text("Replace your unsaved text with revision 2?")
            assert page.evaluate("document.activeElement?.textContent") == "Cancel"  # the safe choice, as the board's Drop
            expect(box).to_have_value("My unsaved <b>typing</b>.")
            ask.get_by_role("button", name="Cancel").click()
            expect(panel.locator(".board-ask")).to_have_count(0)
            expect(box).to_have_value("My unsaved <b>typing</b>.")
            assert page.evaluate("document.activeElement?.id") == "brief-body"  # back to the typing
            rows.filter(has_text="Second words.").get_by_role("button", name="Use this text").click()
            panel.locator(".board-ask").get_by_role("button", name="Yes").click()
            expect(panel.locator(".board-ask")).to_have_count(0)
            expect(panel.get_by_label("Edit brief")).to_have_value("Second words.")
            assert page.evaluate("document.activeElement?.id") == "brief-body"


def test_a_failed_reload_after_a_save_keeps_the_history_rows(browser_peer):
    """Follow-up from the final reviews: when a save succeeds but reloading the open history fails, the rows already
    shown were replaced by the error. They stay, with the error under them."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "City of AI", [users["family"]["id"]])
    store.save_brief(patient, room["id"], "First words.", 0)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Brief history", exact=True).click()
            expect(panel.locator(".brief-revision")).to_have_count(1)
            page.route("**/brief/revisions", lambda route: route.fulfill(status=500, content_type="application/json",
                                                                       body=json.dumps({"error": "History is down"})))
            panel.get_by_role("button", name="Edit brief").click()
            panel.get_by_label("Edit brief").fill("Second words.")
            panel.get_by_role("button", name="Save brief").click()
            expect(panel.locator(".room-brief-body")).to_have_text("Second words.")
            history = panel.locator(".brief-history")
            expect(history.locator(".inline-message.error")).to_have_text("History is down")
            expect(history.locator(".brief-revision")).to_have_count(1)
            expect(history.locator(".brief-revision")).to_contain_text("First words.")
            order = history.evaluate("el => [...el.children].map((c) => c.className || c.tagName)")
            assert order.index("brief-revisions") < order.index("inline-message error")
    assert store.get_room(patient, room["id"])["brief"]["revision"] == 2


def test_a_failed_first_reload_does_not_say_no_revisions(browser_peer):
    """Fix round 1: "No revisions yet." was still shown above the error when the open, empty history failed to reload
    after the first save, though the panel already showed revision 1."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "Never had a brief", [users["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Brief history", exact=True).click()
            expect(panel.locator(".brief-history")).to_contain_text("No revisions yet.")
            page.route("**/brief/revisions", lambda route: route.fulfill(status=500, content_type="application/json",
                                                                       body=json.dumps({"error": "History is down"})))
            panel.get_by_role("button", name="Edit brief").click()
            panel.get_by_label("Edit brief").fill("First words.")
            panel.get_by_role("button", name="Save brief").click()
            expect(panel.locator(".room-brief-body")).to_have_text("First words.")
            expect(panel.locator(".brief-history .inline-message.error")).to_have_text("History is down")
            expect(panel.locator(".brief-history")).not_to_contain_text("No revisions yet.")


def grant_station(browser_peer):
    """Grants step 3's page (G20-G22): patient owns serenity, in a room with doctor whose title is HTML, and in a room
    without doctor; doctor's display name is HTML too. (store, users, ship, room, lone)."""
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(users["patient"]["id"], started["id"], started["code"])
    store.rename_user(users["doctor"]["id"], "<img src=x onerror=alert(1)>")
    room = store.create_room(users["patient"]["id"], "<b>City</b> of AI", [users["doctor"]["id"], ship["id"]])
    lone = store.create_room(users["patient"]["id"], "Just me", [ship["id"]])
    return store, users, ship, room, lone


def fill_grant(page, person, *rooms):
    page.get_by_label("Person").select_option(label=person)
    page.get_by_label("Serenity").check()
    for title in rooms:
        page.get_by_label(title).check()


def test_a_grant_is_made_on_the_page_held_by_its_grantee_and_revoked_after_the_ask(browser_peer):
    """Test 20, G20-G22: the patient makes a grant, choosing from a person list without ships or himself, and sees it
    under "Given by you"; the doctor sees it under "Held by you", with no Revoke; Revoke asks in place, revokes nothing
    before the confirm, and then revokes with its reason. A grantee name and a room title written as HTML show as text."""
    base = browser_peer["base_url"]
    store, users, ship, room, lone = grant_station(browser_peer)
    patient, doctor = users["patient"]["id"], users["doctor"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            expect(page.get_by_role("heading", name="Grants", level=1)).to_be_visible()
            expect(page.get_by_text("Their mentions start builder runs of your ships on your machine. A run can read your "
                                    "repository and uses your model time, and its reply is posted in the room.")).to_be_visible()
            assert page.get_by_label("Person").locator("option").all_inner_texts() == [
                "Choose a person", "<img src=x onerror=alert(1)>", "Sam Family", "Taylor Organizer"]
            expect(page.get_by_label("How long")).to_have_value("168")
            expect(page.get_by_label("Builds a day")).to_have_value("5")
            fill_grant(page, "<img src=x onerror=alert(1)>", "<b>City</b> of AI")
            expect(page.get_by_label("Just me")).to_have_count(0)  # it doesn't hold the doctor
            expect(page.get_by_label("These rooms")).to_be_checked()
            page.get_by_role("button", name="Make grant").click()
            item = page.locator(".grants-given .grant-item")
            expect(item).to_have_count(1)
            made = store.list_grants(patient)[0]
            expect(page.locator(".notice", has_text=f"Grant {made['short']} made.")).to_be_visible()
            expect(item).to_contain_text(f"{made['short']} To <img src=x onerror=alert(1)>")
            expect(item).to_contain_text("Serenity, 20 grant builds left for the ship")
            expect(item).to_contain_text("Rooms: <b>City</b> of AI")
            expect(item).to_contain_text("5 of 5 builds left in the last 24 hours")
            expect(item.locator(".badge")).to_have_text("Valid")
            assert page.locator("#main-content img, #main-content b").count() == 0
            assert (made["grantee"]["id"], [r["id"] for r in made["rooms"]], made["expires"] - made["created"], made["budget"]) == (
                doctor, [room["id"]], 7 * 86400, 5)
        with signed_in_browser(playwright, browser_peer, "doctor") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            held = page.locator(".grants-held .grant-item")
            expect(held).to_contain_text(f"{made['short']} From Alex Patient")
            expect(held.get_by_role("button")).to_have_count(0)
            expect(page.locator(".grants-given .grant-item")).to_have_count(0)
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            revokes = []
            page.on("request", lambda request: revokes.append(request.url) if request.method == "POST" and request.url.endswith("/revoke") else None)
            page.get_by_role("link", name="Grants", exact=True).click()
            item = page.locator(".grants-given .grant-item")
            item.get_by_role("button", name=f"Revoke {made['short']}").click()
            expect(item).to_contain_text(f"Revoke {made['short']}? Their mentions stop starting builder runs at once")
            expect(item.get_by_role("button", name="Cancel")).to_be_focused()
            item.get_by_role("button", name="Cancel").click()  # the safe choice changes nothing (S2 of the plan review)
            expect(item.locator(".grant-ask")).to_have_count(0)
            expect(item.get_by_role("button", name=f"Revoke {made['short']}")).to_be_focused()
            assert revokes == [] and store.list_grants(patient)[0]["valid"] is True
            item.get_by_role("button", name=f"Revoke {made['short']}").click()
            assert store.list_grants(patient)[0]["revoked"] is None  # nothing before the confirm
            item.get_by_label("Reason (optional)").fill("Done for now")
            item.get_by_role("button", name=f"Yes, revoke {made['short']}").click()
            expect(item).to_contain_text(f"Not valid Grant {made['short']} was revoked by Alex Patient")
            expect(page.locator(".notice", has_text=f"Grant {made['short']} revoked.")).to_be_visible()
            expect(item.get_by_role("button")).to_have_count(0)
            assert len(revokes) == 1
    assert store.list_grants(patient)[0]["revoke_reason"] == "Done for now"


def test_a_double_click_on_make_grant_makes_one_grant(browser_peer):
    """Plan Review Focus 2: a second submit while the first is on its way would make a second grant, doubling the person's
    builds; the page sends one write at a time. The POSTs are counted, so a station that refused the second one could
    not pass for a page that sent one."""
    base = browser_peer["base_url"]
    store, users, ship, room, lone = grant_station(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            posts = []
            page.on("request", lambda request: posts.append(request.url) if request.method == "POST" and request.url.endswith("/api/grants") else None)
            page.get_by_role("link", name="Grants", exact=True).click()
            page.get_by_role("button", name="Make grant").click()  # no person yet: the page says so and sends nothing (R19)
            expect(page.locator(".notice", has_text="Choose a person.")).to_be_visible()
            assert posts == []
            fill_grant(page, "<img src=x onerror=alert(1)>", "<b>City</b> of AI")
            page.get_by_role("button", name="Make grant").dblclick()
            expect(page.locator(".grants-given .grant-item")).to_have_count(1)
            page.wait_for_timeout(300)
            assert len(posts) == 1, posts
    assert len(store.list_grants(users["patient"]["id"])) == 1


def test_an_admin_is_offered_only_his_own_ships(browser_peer):
    """Plan Review Focus 3: Andy is the station's admin, and /api/ships gives an admin every ship; the form offers only the
    ships he owns, since a grant over anyone else's is refused (G8 step 4)."""
    store, users, ship, room, lone = grant_station(browser_peer)
    started = store.start_docking("defiant", "taylor-pc")
    store.confirm_docking(users["organizer"]["id"], started["id"], started["code"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            ships = page.locator("#grant-form input[name='grant-ship']")
            expect(ships).to_have_count(1)
            expect(page.get_by_label("Defiant")).to_be_visible()
            expect(page.get_by_label("Serenity")).to_have_count(0)


def test_choosing_another_person_rebuilds_the_rooms_and_drops_the_ones_they_are_not_in(browser_peer):
    """Plan Review Focus 4: rooms ticked for one person stay only if the next person is in them too, so the page never sends
    a room the grantee isn't in (G8 step 2 would refuse it); a room both share keeps its tick."""
    base = browser_peer["base_url"]
    store, users, ship, room, lone = grant_station(browser_peer)
    patient, doctor, family = users["patient"]["id"], users["doctor"]["id"], users["family"]["id"]
    both = store.create_room(patient, "Both of them", [doctor, family, ship["id"]])
    old = store.create_room(patient, "Old", [family])
    store.add_participants(patient, old["id"], [users["organizer"]["id"]])  # a newer "Old" replaces it
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            fill_grant(page, "<img src=x onerror=alert(1)>", "<b>City</b> of AI", "Both of them")
            page.get_by_label("Person").select_option(label="Sam Family")
            expect(page.get_by_label("<b>City</b> of AI")).to_have_count(0)
            expect(page.get_by_label("Both of them")).to_be_checked()
            expect(page.get_by_label("Old", exact=True)).to_have_count(1)  # the current one only
            page.get_by_label("Person").select_option(label="<img src=x onerror=alert(1)>")
            expect(page.get_by_label("<b>City</b> of AI")).not_to_be_checked()  # dropped, not kept for later
            page.get_by_label("Person").select_option(label="Sam Family")
            page.get_by_role("button", name="Make grant").click()
            expect(page.locator(".grants-given .grant-item")).to_contain_text("To Sam Family")
    made = store.list_grants(patient)[0]
    assert (made["grantee"]["id"], [r["id"] for r in made["rooms"]]) == (family, [both["id"]])


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 960}, {"width": 390, "height": 844}])
def test_a_hurried_double_click_on_revoke_only_opens_the_ask(browser_peer, viewport):
    """G22: the ask takes Revoke's place with its question first, so the second press of a hurried double click lands on
    text, at desktop and phone widths: the ask stays open and nothing is revoked or cancelled."""
    base = browser_peer["base_url"]
    store, users, ship, room, lone = grant_station(browser_peer)
    patient = users["patient"]["id"]
    made = store.make_grant(patient, users["doctor"]["id"], [ship["id"]], [room["id"]], 24, 5)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient", viewport=viewport) as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            item = page.locator(".grants-given .grant-item")
            revoke = item.get_by_role("button", name=f"Revoke {made['short']}")
            revoke.scroll_into_view_if_needed()  # mouse clicks go to viewport coordinates
            double_click_apart(page, revoke)
            page.wait_for_timeout(600)
            expect(item).to_contain_text(f"Revoke {made['short']}?")
    assert store.list_grants(patient)[0]["revoked"] is None


def test_any_room_you_share_sends_the_star_and_a_room_made_after_sign_in_is_offered(browser_peer):
    """G21's "Any room you share with them" sends `rooms: "*"`, and the grant says so (S1 of the plan review). Entering the
    page reads the rooms again, so a room made after sign-in is offered (R21)."""
    store, users, ship, room, lone = grant_station(browser_peer)
    patient, doctor = users["patient"]["id"], users["doctor"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            sent = []
            page.on("request", lambda request: sent.append(request.post_data_json) if request.method == "POST" and request.url.endswith("/api/grants") else None)
            store.create_room(patient, "Made after sign-in", [doctor])
            page.get_by_role("link", name="Grants", exact=True).click()
            page.get_by_label("Person").select_option(label="<img src=x onerror=alert(1)>")
            expect(page.get_by_label("Made after sign-in")).to_be_visible()
            page.get_by_label("Serenity").check()
            page.get_by_label("Any room you share with them").check()
            page.get_by_role("button", name="Make grant").click()
            expect(page.locator(".grants-given .grant-item")).to_contain_text("Rooms: Any room you share with them")
            assert [body["rooms"] for body in sent] == ["*"]
    assert store.list_grants(patient)[0]["rooms"] == "*"


def test_a_second_press_of_yes_revoke_while_the_first_is_on_its_way_sends_nothing(browser_peer):
    """Section 2 review of merge 3c, minor 4: the revoke path has no guard of its own, only grantWrite's one write at a
    time. With the first POST held the button is still on screen; a second press must not send a second POST (which the
    station would answer with a 409 that the page then shows). The POSTs are counted."""
    store, users, ship, room, lone = grant_station(browser_peer)
    patient = users["patient"]["id"]
    made = store.make_grant(patient, users["doctor"]["id"], [ship["id"]], [room["id"]], 24, 5)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            posts, held = [], []
            page.on("request", lambda request: posts.append(request.url) if request.method == "POST" and request.url.endswith("/revoke") else None)
            page.route("**/api/grants/*/revoke", lambda route: held.append(route))
            page.get_by_role("link", name="Grants", exact=True).click()
            item = page.locator(".grants-given .grant-item")
            item.get_by_role("button", name=f"Revoke {made['short']}").click()
            confirm = item.get_by_role("button", name=f"Yes, revoke {made['short']}")
            with page.expect_request("**/api/grants/*/revoke"):
                confirm.click()
            assert len(held) == 1
            expect(confirm).to_be_visible()
            expect(confirm).to_be_enabled()
            confirm.click()  # the first write is still on its way
            page.wait_for_timeout(300)
            assert len(posts) == 1, posts  # held requests are counted when sent
            for route in held:
                route.continue_()
            expect(page.locator(".notice", has_text=f"Grant {made['short']} revoked.")).to_be_visible()
            page.wait_for_timeout(300)
            assert len(posts) == 1, posts
            expect(page.locator(".notice.error")).to_have_count(0)
    assert store.list_grants(patient)[0]["revoked"] is not None


def test_focus_moves_to_given_by_you_only_after_a_revoke_that_worked(browser_peer):
    """The Mac's final review of 3c, m4: after a revoke that went through the item is gone, so focus goes to the "Given by
    you" heading; after a refused one the ask stays open with its error and focus returns to its "Yes, revoke" button."""
    store, users, ship, room, lone = grant_station(browser_peer)
    patient = users["patient"]["id"]
    made = store.make_grant(patient, users["doctor"]["id"], [ship["id"]], [room["id"]], 24, 5)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            item = page.locator(".grants-given .grant-item")
            title = page.locator("#grants-given-title")
            item.get_by_role("button", name=f"Revoke {made['short']}").click()
            refuse = lambda route: route.fulfill(status=409, content_type="application/json", body='{"error": "Grant is already revoked"}')
            page.route("**/api/grants/*/revoke", refuse)
            item.get_by_role("button", name=f"Yes, revoke {made['short']}").click()
            expect(page.locator(".notice.error", has_text="Grant is already revoked")).to_be_visible()
            page.wait_for_timeout(300)
            expect(item.locator(".grant-ask")).to_have_count(1)
            expect(title).not_to_be_focused()
            expect(item.get_by_role("button", name=f"Yes, revoke {made['short']}")).to_be_focused()  # the keyboard user keeps their place
            page.unroute("**/api/grants/*/revoke", refuse)
            item.get_by_role("button", name=f"Yes, revoke {made['short']}").click()
            expect(page.locator(".notice", has_text=f"Grant {made['short']} revoked.")).to_be_visible()
            expect(title).to_be_focused()
    assert store.list_grants(patient)[0]["revoked"] is not None


def test_a_revoke_whose_reload_finds_the_session_ended_shows_the_sign_in(browser_peer):
    """The Mac's final review of 3c, m4: the revoke went through, then the list's reload answered 401 (the session ended
    meanwhile). The sign-in prompt shows, not a list that quietly went stale."""
    store, users, ship, room, lone = grant_station(browser_peer)
    patient = users["patient"]["id"]
    made = store.make_grant(patient, users["doctor"]["id"], [ship["id"]], [room["id"]], 24, 5)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            item = page.locator(".grants-given .grant-item")
            item.get_by_role("button", name=f"Revoke {made['short']}").click()
            posted = []

            def after_the_post(route):
                posted.append(route.request.url)  # the reload is answered 401 from here on
                route.continue_()

            page.route("**/api/grants/*/revoke", after_the_post)
            page.route("**/api/grants", lambda route: route.fulfill(status=401, content_type="application/json", body='{"error": "Sign in"}')
                       if posted else route.continue_())
            item.get_by_role("button", name=f"Yes, revoke {made['short']}").click()
            expect(page.get_by_text("Your session ended. Sign in again;")).to_be_visible()
            expect(page.get_by_role("heading", name="Sign in to your home")).to_be_visible()
    assert store.list_grants(patient)[0]["revoked"] is not None


def test_names_written_as_html_show_as_text_in_a_held_revoked_grant(browser_peer):
    """Section 2 review of merge 3c, minor 4 (the Mac's m2): the grantee's list shows revoked grants too ("Grant #xxxx was revoked by ..."),
    so the doctor's view carries the patient's name twice, in the From line and in the reason. Both show as literal text,
    and no element comes out of them."""
    store, users, ship, room, lone = grant_station(browser_peer)
    patient, doctor = users["patient"]["id"], users["doctor"]["id"]
    name = "<i>Pat</i><img src=x onerror=alert(2)>"
    made = store.make_grant(patient, doctor, [ship["id"]], [room["id"]], 24, 5)
    store.rename_user(patient, name)
    store.revoke_grant(patient, made["id"], "Done")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "doctor") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            held = page.locator(".grants-held .grant-item")
            expect(held).to_have_count(1)
            expect(held.locator("p").first).to_contain_text(f"{made['short']} From {name}")
            expect(held).to_contain_text(f"Grant {made['short']} was revoked by {name}")
            assert page.locator(".grant-list img, .grant-list i").count() == 0


def test_the_rooms_offered_for_a_grant_leave_out_breakouts_and_received_rooms(browser_peer):
    """Section 2 review of merge 3c, minor 4 (the Mac's m2): a breakout or a received room can't be granted (G8 step 1). Real data can't show
    it, since a breakout holds no person, so the home response is given two such rooms that list the doctor as a member;
    the form still offers only the real shared room."""
    store, users, ship, room, lone = grant_station(browser_peer)
    doctor = users["doctor"]["id"]

    served = []

    def with_extra_rooms(route):
        served.append(route.request.url)
        home = route.fetch().json()
        real = next(chat for chat in home["chats"] if chat["id"] == room["id"])
        home["chats"] += [dict(real, id="made-up-breakout", title="Made-up breakout", breakout=real["id"], member_ids=[doctor]),
                          dict(real, id="made-up-received", title="Made-up received", origin="far-station", member_ids=[doctor])]
        route.fulfill(json=home)

    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.route("**/api/home", with_extra_rooms)
            page.get_by_role("link", name="Grants", exact=True).click()
            page.get_by_label("Person").select_option(label="<img src=x onerror=alert(1)>")
            expect(page.get_by_label("<b>City</b> of AI")).to_be_visible()
            expect(page.locator("#grant-form input[name='grant-room']")).to_have_count(1)
            expect(page.get_by_label("Made-up breakout")).to_have_count(0)
            expect(page.get_by_label("Made-up received")).to_have_count(0)
            assert served  # the interception ran, so the two added rooms were in the page's data
