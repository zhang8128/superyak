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
    remote_user = remote_store.create_user(
        "casey", "Casey Remote", "long-remote-password"
    )
    remote_identity = PeerIdentity.load_or_create(
        remote_store.data_dir, hosts=("remote.example",)
    )
    remote_card = Federation(
        remote_store,
        endpoint="https://remote.example:7443",
        identity=remote_identity,
    ).card(remote_user["id"])
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
            expect(dialog.get_by_text("Only the brief is carried. Earlier messages stay with their original participants.")).to_be_visible()
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
