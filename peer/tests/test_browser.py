"""Real-browser acceptance flows for the same-origin personal home."""
from superyak_peer.identity import pairing_code, show_code

from contextlib import contextmanager
import json
import os
import re
import uuid
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

from superyak_peer import peer_routes
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
def browser_peer(tmp_path, request, monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    local_demo = getattr(request, "param", False)
    if local_demo:
        from superyak_peer.__main__ import seed_demo
        seed_demo(tmp_path / "browser-peer")
    # "Check delivery now" dials only from serve --sync's worker (plan P11). Its timed passes would race a test's
    # "Pending delivery" check, so under the marker the worker passes only when the button wakes it.
    sync_worker = request.node.get_closest_marker("sync_worker") is not None
    if sync_worker:
        monkeypatch.setattr(peer_routes, "SYNC_SECONDS", 3600)
    # The remote connector (Task 9b's pages) is on only under its marker, at connector_support's public origin.
    from connector_support import PUBLIC_ORIGIN
    connector = request.node.get_closest_marker("connector") is not None
    app = create_app(tmp_path / "browser-peer", allowed_origins=[base_url] + ([PUBLIC_ORIGIN] if connector else []),
                     local_demo=local_demo, sync_enabled=sync_worker, public_origin=PUBLIC_ORIGIN if connector else None)
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
    expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
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


def test_the_sign_in_page_says_it_is_a_prototype_and_links_what_superyak_is(browser_peer):
    """Tardis's cold walk (goal 4, T4): before any account, a stranger reads that this is a prototype not for real
    patient information, in the README's own words, and finds what Superyak is in one click. It stays true on any peer:
    whose home it is is left to a station's own welcome."""
    with sync_playwright() as playwright, signed_out_browser(playwright) as page:
        page.goto(browser_peer["base_url"] + "/")
        expect(page.get_by_text("Superyak's first use is medical research, and it's a prototype", exact=False)).to_be_visible()
        expect(page.locator(".login-note").get_by_text("please don't put real patient information in it yet", exact=False)).to_be_visible()
        link = page.get_by_role("link", name="What is Superyak?")
        expect(link).to_be_visible()
        expect(link).to_have_attribute("href", "https://github.com/zhang8128/superyak#readme")


def test_the_sign_in_page_tells_a_stranger_how_to_get_an_account(browser_peer):
    """T4's baseline walk: the sign-in page offered a token box and nothing for someone not yet invited. Any peer's
    owner invites its people, so the page says to ask them."""
    with sync_playwright() as playwright, signed_out_browser(playwright) as page:
        page.goto(browser_peer["base_url"] + "/")
        expect(page.get_by_text("No account? The person who runs this home invites people: ask them for an invitation.",
                                exact=True)).to_be_visible()


def test_the_sign_in_page_speaks_to_a_visitor_about_this_home_not_theirs(browser_peer):
    """Tardis's T4 (goal 4), by the visitor-access spec section 3: every peer serves this page, so it stays generic.
    A stranger reading someone else's station meets "this home", never "your home", and no undefined "peer"."""
    with sync_playwright() as playwright, signed_out_browser(playwright) as page:
        page.goto(browser_peer["base_url"] + "/")
        expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
        expect(page.get_by_text("Free, open-source and self-hosted.", exact=False)).to_be_visible()
        # The second cold walk: "Write privately" beside "its owner can read" read as private from the owner too, and
        # "home" was never said to be anything. "version" of what, it asked as well.
        expect(page.get_by_text("A home is a small server someone runs for the people they invite.", exact=False)).to_be_visible()
        # Its reader: "only" was a guarantee nothing makes. The words are in clear on disk, so whoever runs the machine,
        # and any AI agent they run on it, can read them. So each clause here says what's true, and each is pinned.
        words = page.locator("main").inner_text()
        assert "Keep notes no other account can open until you share them" in words
        assert "make public only what you choose." in words
        assert "Whoever runs this home can read everything stored on it, and so can any AI agent they run on its computer." in words
        assert "Room messages go to every member: an AI agent's copy goes on to its AI company" in words
        # Its re-check: a copy on another home doesn't "stay" there. That home's owner reads it, and its member may be a ship.
        assert "a member on another home gets a copy kept there under that home's rules." in words
        assert "The room says which, above its messages." in words
        assert "only you" not in words.lower()
        assert "write privately" not in page.locator("main").inner_text().lower()
        assert "the version you mean" not in page.locator("main").inner_text().lower()
        assert "personal home" not in page.locator("main").inner_text().lower()  # personal to whom, it asked
        expect(page.get_by_text("An account here lives on this home, not with a company.", exact=True)).to_be_visible()
        words = page.locator("main").inner_text().lower()
        assert "your home" not in words
        assert "peer" not in words
    with urlopen(browser_peer["base_url"] + "/") as response:
        shell = response.read().decode()
    assert "Opening your home" not in shell and "Opening this home" in shell


def test_an_invitation_link_on_a_phone_goes_to_what_is_left_to_fill_in(browser_peer):
    """The form sits far below the Sign in fields on a phone, so the link used to land a person on the wrong form."""
    with sync_playwright() as playwright, signed_out_browser(playwright, viewport={"width": 390, "height": 844}) as page:
        page.goto(browser_peer["base_url"] + "/#activate?token=made-up&username=someone&name=Someone")
        password = page.locator('#redeem-form input[name="password"]')
        expect(password).to_be_focused()
        expect(password).to_be_in_viewport()


def test_the_old_promises_are_gone_from_every_screen():
    """A short list of words that promised more than the code does, so they don't come back. Stored words are in clear on
    disk, so whoever runs the machine, and any AI agent they run on it, can read them, and a room may have a ship or
    another home in it. What this can't catch is a new way of saying it: that takes a reader of the code."""
    static = Path(__file__).resolve().parents[1] / "superyak_peer" / "static"
    words = "\n".join(path.read_text() for path in (*static.glob("*.js"), static / "index.html", static / "consent.html"))
    for promise in (r"(?i)\bprivate (room|chat|conversation|message)s?\b", r"(?i)\bonly you\b",
                    r"(?i)\b(nobody|no one)( else)? can\b", r"(?i)\bprivate (place|workspace|first|work)\b",
                    r"(?i)\bstays? private\b", r"(?i)\bimported content stays\b", r"(?i)\bimporting is private\b",
                    r"(?i)\bimport(ed)? privately\b", r"(?i)\bsaved? (them )?privately\b", r"(?i)\bkeep it private\b",
                    r"(?i)\bonly your account\b", r"(?i)\bnever to a cloud model\b", r"(?i)\baway from claude\b",
                    r"(?i)\bfrom cloud models?\b", r"(?i)\bkeeps their copy\b", r"(?i)\bmarks? (is|are) their own\b",
                    r"(?i)\bno ships or connected apps\b"):
        assert not re.search(promise, words), promise


def test_a_signed_in_person_is_told_who_can_read_where_they_work(browser_peer):
    """The inside labels lean on this. The sidebar is hidden on a phone, so Home says it too."""
    who = "Whoever runs this home, who may not be you, can read everything stored on it, and so can any AI agent they run on its computer."
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            expect(page.get_by_test_id("who-can-read")).to_have_text(who)
            expect(page.locator(".sidebar-foot")).to_have_text(who)
            assert "Private chat" not in page.locator("main").inner_text()
        for width, height in ((390, 844), (375, 667), (320, 568)):  # the fixed bar covers the foot of a small screen
            with signed_in_browser(playwright, browser_peer, "patient", viewport={"width": width, "height": height}) as (page, _):
                line = page.get_by_test_id("who-can-read").bounding_box()
                assert line["y"] + line["height"] <= page.locator(".sidebar").bounding_box()["y"]


def test_a_saved_draft_says_what_no_other_account_can_do(browser_peer):
    """The sentence meant for drafts sat in a branch nothing reached, so it's asserted on a rendered draft, beside the
    source panel's own sentence on the same page."""
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        page.get_by_role("link", name="My sharing layers").click()
        expect(page.get_by_text("No other account can open imported records.")).to_be_visible()
        page.get_by_role("button", name="New layer").click()
        page.get_by_label("What do you want to share?").fill("Fictional words.")
        page.get_by_role("button", name="Save private draft").click()
        expect(page.get_by_text("No other account can open your saved draft.")).to_be_visible()


@pytest.mark.parametrize("kind, label, says", [
    ("selected-records", "Papers and records · No other account can open it", True),
    ("file", "Files and datasets", False),
])
def test_a_source_only_says_no_other_account_where_that_holds(browser_peer, kind, label, says):
    """A file in a file source can be attached to a release, so from a public release an anonymous visitor could fetch what its page called
    no other account's. Only records keep the claim."""
    name = "Source " + uuid.uuid4().hex[:6]
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        page.get_by_role("link", name="Research & data", exact=True).click()
        page.get_by_role("button", name="New source", exact=True).click()
        page.get_by_label("Source name", exact=True).fill(name)
        page.get_by_label("Source type", exact=True).select_option(kind)
        page.get_by_role("button", name="Create source", exact=True).click()
        expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
        eyebrow = page.locator("main .eyebrow").filter(has_text=label.split(" · ")[0]).first
        expect(eyebrow).to_have_text(label, ignore_case=True)
        assert ("no other account" in eyebrow.inner_text().lower()) is says  # the eyebrow's text is upper-cased by CSS


def test_an_invitation_link_with_only_a_token_goes_to_the_username(browser_peer):
    with sync_playwright() as playwright, signed_out_browser(playwright, viewport={"width": 390, "height": 844}) as page:
        page.goto(browser_peer["base_url"] + "/#activate?token=made-up")
        expect(page.locator('#redeem-form input[name="username"]')).to_be_focused()


def test_the_sign_in_pages_tile_shows_and_its_help_clears_the_button(browser_peer):
    """The second cold walk: the S tile vanished on the dark panel, and `.login-panel > p` outranked `.login-help`."""
    with sync_playwright() as playwright, signed_out_browser(playwright) as page:
        page.goto(browser_peer["base_url"] + "/")
        expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
        style = "e => getComputedStyle(e).%s"
        tile, panel = page.locator(".login-story .brand-mark"), page.locator(".login-story")
        shade = tile.evaluate(style % "backgroundColor")
        assert shade != panel.evaluate(style % "backgroundColor") and shade != "rgba(0, 0, 0, 0)"
        assert page.locator(".login-panel > .login-help").first.evaluate(style % "marginTop") == "16px"


def test_on_a_phone_the_sign_in_form_is_on_the_first_screen_with_who_can_read(browser_peer):
    """The page's words grew past a screen, and a returning person shouldn't scroll for the form. The owner line stays on
    that first screen, and neither the page nor the card overflows."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        try:
            page = context.new_page()
            page.goto(browser_peer["base_url"] + "/")
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
            box = page.locator("#password").bounding_box()
            assert box["y"] + box["height"] < 844
            help_line = page.get_by_text("This home is run by its owner, who can read what's stored here.", exact=True)
            assert help_line.bounding_box()["y"] < 844
            assert page.evaluate("document.documentElement.scrollWidth") == 390
            assert page.locator(".login-wrap").evaluate("e => e.scrollWidth <= e.clientWidth")  # it hides its own overflow
        finally:
            context.close()
            browser.close()


def test_before_making_an_account_a_person_is_told_who_can_read_and_that_its_a_prototype(browser_peer):
    """The re-check of the phone order: someone with an invitation link could make an account with the page's main facts
    a screen and more below the button, so the form says them itself, at every width."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        try:
            page = context.new_page()
            page.goto(browser_peer["base_url"] + "/")
            page.get_by_text("Use an invitation", exact=True).click()
            facts = page.get_by_test_id("before-an-account")
            expect(facts).to_have_text("Whoever runs this home, and any AI agent they run on its computer, can read what's "
                                       "stored here. It's a prototype: please don't put real patient information in it yet.")
            # Above the new password, so a phone's keyboard doesn't cover them, and tied to it, since a screen reader starts
            # at that field and would otherwise read on past them.
            assert facts.bounding_box()["y"] < page.locator("#new-password").bounding_box()["y"]
            assert page.locator("#new-password").get_attribute("aria-describedby") == "before-an-account"
        finally:
            context.close()
            browser.close()


def test_before_a_password_the_sign_in_page_says_the_owner_can_read_the_home(browser_peer):
    """Rio Grande, on T4's branch: whoever runs a home reads what's stored on it, and a person should know that before
    typing a password into someone else's home. Until now it was said only in the README."""
    with sync_playwright() as playwright, signed_out_browser(playwright) as page:
        page.goto(browser_peer["base_url"] + "/")
        expect(page.get_by_text("This home is run by its owner, who can read what's stored here.", exact=True)).to_be_visible()


ABOUT = ("A Superyak home: a free, open-source, self-hosted place for the parts of your life you choose to share. Its "
         "owner invites the people in it and can read what's stored here. Superyak's first use is medical research, and "
         "it's a prototype: please don't put real patient information in it yet.")


def test_without_javascript_the_page_still_says_what_superyak_is(browser_peer):
    """T4's walks: a fetcher that runs no JavaScript saw only "Opening your home…". The first fix put the text in
    <noscript>, and the live walk still saw nothing: that fetcher's HTML-to-text step drops <noscript> and <head>. So the
    text is ordinary shell content, and this reads it two ways: as such a text step does, and in a browser with
    scripts off."""
    with urlopen(browser_peer["base_url"] + "/") as response:
        page = response.read().decode()
    assert f'<meta name="description" content="{ABOUT}">' in page
    assert f'<meta property="og:description" content="{ABOUT}">' in page
    body = re.sub(r"<(head|script|style|noscript)\b.*?</\1>", " ", page, flags=re.S | re.I)
    link = re.search(r'<a href="([^"]+)"[^>]*>What is Superyak\?</a>', body)
    assert link and link.group(1) == "https://github.com/zhang8128/superyak#readme"
    text = " ".join(re.sub(r"<[^>]+>", " ", body).split())
    assert ABOUT in text
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(java_script_enabled=False)
        try:
            shell = context.new_page()
            shell.goto(browser_peer["base_url"] + "/")
            expect(shell.get_by_text(ABOUT, exact=False)).to_be_visible()
            # The second cold walk: "Opening this home…" alone looked stuck, with no way to tell what to do next. Read as
            # inner text, since Playwright's text locators and aria snapshot skip <noscript>, which this browser does show.
            assert "This page can't finish opening without JavaScript, and signing in needs it." in shell.locator("body").inner_text()
            assert "Ask the person who runs this home for an invitation." in shell.locator("body").inner_text()
            line = shell.locator(".loading-page noscript p")
            assert line.evaluate("p => getComputedStyle(p).textAlign") == "center"
            assert line.evaluate("p => getComputedStyle(p).maxWidth") == "440px"
            shell.set_viewport_size({"width": 390, "height": 844})
            for text in (line, shell.locator(".loading-about")):  # a gutter at phone width, for both paragraphs
                assert text.bounding_box()["x"] >= 16
            expect(shell.get_by_role("link", name="What is Superyak?")).to_have_attribute(
                "href", "https://github.com/zhang8128/superyak#readme")
        finally:
            context.close()
            browser.close()


def test_once_the_app_loads_the_shell_description_is_gone(browser_peer):
    """Rio Grande: the shell shows for a moment to everyone while app.js loads, so it reads as plain "what this is";
    once the app renders its first view, the shell is replaced."""
    with sync_playwright() as playwright, signed_out_browser(playwright) as page:
        page.goto(browser_peer["base_url"] + "/")
        expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
        expect(page.get_by_text("Its owner invites the people in it", exact=False)).to_have_count(0)


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
        page.get_by_role('button', name='Import', exact=True).click()
        expect(page.get_by_role('heading', name='Fictional study', exact=True)).to_be_visible()
        expect(page.locator('.evidence-card .eyebrow', has_text='Source record')).to_have_text(
            'Source record · No other account can open it', ignore_case=True)
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
        # The heading already shows the other tab's name, so it can't tell that the reload finished; the button goes
        # only when it has, and a save clicked while it runs is dropped (fix:browser-source-layer-flakes, CI b918196e)
        expect(page.get_by_role('button', name='Load latest source settings', exact=True)).to_be_hidden()
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
        page.get_by_role('button', name='Import', exact=True).click()
        expect(page.get_by_role('dialog')).to_contain_text('Connection lost')
        first = service.history(actor, source['id'])['imports']
        assert len(first) == 1 and first[0]['status'] == 'succeeded'
        page.get_by_role('button', name='Import', exact=True).click()
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
        expect(page.get_by_role('heading', name='Sign in to this home')).to_be_visible()
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
                    "Build your sharing layers at your own pace. Save them, "
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


def reads_settled(page, *, held=0):
    """Until only the `held` reads are out, and have been for a moment. wait_for_load_state("networkidle") fires once per page
    load, so after a click it says nothing about the reads that click started. Needs watch_reads."""
    deadline, quiet = time.monotonic() + 10, 0
    while quiet < 4:
        assert time.monotonic() < deadline, f"still out: {[request.url for request in page.reads_out]}"
        page.wait_for_timeout(40)
        quiet = quiet + 1 if len(page.reads_out) <= held else 0


def watch_reads(page):
    out = page.reads_out = set()
    page.on("request", lambda request: out.add(request))
    page.on("requestfinished", lambda request: out.discard(request))
    page.on("requestfailed", lambda request: out.discard(request))


def two_rooms_with_x_open(page, store, owner, *members):
    x, y = store.create_room(owner, "Room X", list(members)), store.create_room(owner, "Room Y", list(members))
    watch_reads(page)
    page.goto(page.url.split("#")[0])
    page.get_by_role("link", name="Chats").first.click()
    page.get_by_role("button", name="Room X").click()
    expect(page.get_by_role("heading", name="Room X")).to_be_visible()
    reads_settled(page)  # the address's own read has landed and drawn, so nothing replaces the box below
    return x, y


def held_routes(page, pattern):
    """Holds the first read that matches and lets the rest through: a room's address reads it a second time."""
    held = []

    def hold(route):
        if held:
            route.continue_()
        else:
            held.append(route)
    page.route(pattern, hold)
    return held


def wait_for_hold(page, held):
    deadline = time.monotonic() + 10
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(20)
    assert held, "the held read never left"


def y_opening(page, y):
    """Y's board read is out: the person clicked Y and X is still on screen. Returns the held read, to release."""
    held = held_routes(page, f"**/api/chats/{y['id']}/board")
    page.get_by_role("button", name="Room Y").click()
    wait_for_hold(page, held)
    expect(page.get_by_role("heading", name="Room X")).to_be_visible()
    assert page.evaluate("state.room.title") == "Room X"  # state.room is the room on screen, until the next is ready to draw
    return held


def y_opening_from_a_long_room(page, y):
    held = held_routes(page, f"**/api/chats/{y['id']}/board")
    page.get_by_role("button", name="Room Y").click()
    wait_for_hold(page, held)
    return held


def release(held):
    for route in held:
        route.continue_()


def read_room(page, room):
    return page.evaluate("id => fetch(`/api/chats/${id}`).then(r => r.json())", room["id"])


def bodies(page, room):
    return [m["body"] for m in read_room(page, room)["messages"]]


def test_a_message_goes_to_the_room_on_screen_while_another_opens(browser_peer):
    """While the next room loads, the old room and its composer are on screen. Send has to mean the room the person is looking at,
    or their words reach people they didn't mean to tell. So does what they type: it's kept as that room's draft."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.fill("Meant for X")
            held = y_opening(page, y)
            box.press("End")
            box.press_sequentially(", still")  # typed mid-switch: it's X's words
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == "Meant for X, still"
            assert page.evaluate("(id) => readChatDraft(id).body", y["id"]) == ""
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text(re.compile("^Message saved"))
            expect(page.locator(".messages")).to_contain_text("Meant for X, still")  # shown where it went, while X is on screen
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            assert bodies(page, x) == ["Meant for X, still"] and bodies(page, y) == []
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == ""  # sent, so nothing to keep
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("")


def test_a_page_drawn_again_while_another_room_opens_still_means_the_room_on_screen(browser_peer):
    """Anything can draw the page mid-switch: a sync, a dialog closing. It draws X, because X is what's on screen, and it keeps X's words."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            held = y_opening(page, y)
            page.evaluate("render()")
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            box = page.get_by_role("textbox", name="Message", exact=True)
            expect(box).to_have_value("Meant for X")
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text(re.compile("^Message saved"))
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            assert bodies(page, x) == ["Meant for X"] and bodies(page, y) == []


def test_a_message_sent_as_the_person_moves_on_stays_out_of_the_way_and_still_reads_the_delivery(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            posts = held_routes(page, f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            wait_for_hold(page, posts)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            with page.expect_response("**/api/sync"):  # or the message reads "Saved here" while a delivery is owed
                release(posts)
            reads_settled(page)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            assert bodies(page, x) == ["Meant for X"] and bodies(page, y) == []
            assert "Meant for X" not in page.locator("main").inner_text()  # the answer doesn't land in the room they're in
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == ""


def test_a_send_that_fails_after_the_person_moved_on_says_where_the_words_are(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            posts = held_routes(page, f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            wait_for_hold(page, posts)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            for route in posts:
                route.abort()
            expect(page.locator(".notice.error")).to_have_text("Your message to Room X may not have been sent. Connection lost. It's still in the box there, so check that room before sending it again.")
            expect(page.locator(".words-kept")).to_have_text("Your message to Room X may not have been sent. Connection lost. It's still in the box there, so check that room before sending it again.")  # a room opens at its newest, far below the flash
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == "Meant for X"
            page.unroute(f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Room X").click()
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("Meant for X")


def test_a_lost_answer_then_a_retry_posts_once(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Once")
            lost = []

            def lose_the_answer(route):  # the post reached the station; the person never heard
                lost.append(route.fetch())
                route.abort()
            page.route(f"**/api/chats/{x['id']}/messages", lose_the_answer)
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text(re.compile("still here"))
            page.unroute(f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text("Message saved")
            assert lost and bodies(page, x) == ["Once"]


def test_a_mark_goes_to_the_room_on_screen_while_another_opens(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            page.get_by_role("button", name=re.compile("^Mark this room$")).click()
            page.wait_for_function("(id) => fetch(`/api/chats/${id}`).then(r => r.json()).then(room => !!room.cloud)", arg=x["id"])
            assert not read_room(page, y).get("cloud")
            release(held)


def test_a_removal_goes_to_the_room_on_screen_while_another_opens(browser_peer):
    users = browser_peer["users"]
    store, owner, family = browser_peer["app"].state.store, users["patient"]["id"], users["family"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner, family)
            held = y_opening(page, y)
            page.get_by_role("button", name=re.compile("^Remove .* from this room")).first.click()
            page.wait_for_function("([id, who]) => fetch(`/api/chats/${id}`).then(r => r.json()).then(room => !room.member_ids.includes(who))", arg=[x["id"], family])
            assert family in read_room(page, y)["member_ids"]
            release(held)


def test_a_dialog_opened_for_the_room_on_screen_closes_when_another_room_opens(browser_peer):
    users = browser_peer["users"]
    store, owner = browser_peer["app"].state.store, users["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            page.get_by_role("button", name="Change participants").click()
            expect(page.get_by_role("dialog")).to_be_visible()
            address_read = held_routes(page, re.compile(rf"/api/chats/{y['id']}(\?|$)"))  # Y is drawn, and the address is still reading it
            release(held)
            wait_for_hold(page, address_read)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            expect(page.get_by_role("dialog")).to_have_count(0)  # it never goes on for the next room, whose members it would change
            release(address_read)
            reads_settled(page)
            assert read_room(page, y)["member_ids"] == [owner] and read_room(page, x)["member_ids"] == [owner]


def test_words_typed_in_a_board_form_stay_with_the_room_on_screen(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            page.locator(".room-board input, .room-board textarea").first.fill("Meant for X's board")
            assert page.evaluate("state.boardPost && state.boardPost.roomId") == x["id"]
            release(held)


def test_a_late_answer_for_a_room_the_person_left_doesnt_take_them_back(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            held = held_routes(page, re.compile(rf"/api/chats/{x['id']}(\?|$)"))
            page.get_by_role("button", name="Room X").click()
            wait_for_hold(page, held)
            page.get_by_role("button", name="Room Y").click()
            reads_settled(page, held=1)
            release(held)
            reads_settled(page)
            assert page.evaluate("state.room.title") == "Room Y" and y["id"] in page.evaluate("location.hash")
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()


def test_a_late_answer_at_an_address_the_person_left_changes_nothing_good_or_bad(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            for land in (lambda route: route.continue_(), lambda route: route.abort()):
                held = held_routes(page, re.compile(rf"/api/chats/{y['id']}(\?|$)"))
                page.evaluate("(id) => { location.hash = `chats/${id}`; }", y["id"])  # the address's read, loadRoute's
                wait_for_hold(page, held)
                page.get_by_role("button", name="Room X").click()
                reads_settled(page, held=1)
                for route in held:
                    land(route)
                reads_settled(page)
                page.unroute(re.compile(rf"/api/chats/{y['id']}(\?|$)"))
                assert page.evaluate("state.room.title") == "Room X"
                expect(page.get_by_role("heading", name="Room X")).to_be_visible()


def test_a_board_read_answered_after_the_person_left_stays_out(browser_peer):
    """A board read after an action, not the one that opens a room."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = held_routes(page, f"**/api/chats/{x['id']}/board")
            page.evaluate("void loadBoard(state.room)")
            wait_for_hold(page, held)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            release(held)
            reads_settled(page)
            assert page.evaluate("state.board.roomId") == y["id"]


def test_a_late_board_for_a_room_the_person_left_stays_out(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            page.get_by_role("button", name="Room X").click()
            reads_settled(page, held=1)
            release(held)
            reads_settled(page)
            assert page.evaluate("state.room.title") == "Room X" and page.evaluate("state.board.roomId") == x["id"]


def test_an_address_whose_room_wont_load_leaves_nothing_to_send_to(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            page.route(re.compile(rf"/api/chats/{y['id']}(\?|$)"), lambda route: route.abort())
            page.evaluate("(id) => { location.hash = `chats/${id}`; }", y["id"])
            expect(page.get_by_role("heading", name="Room X")).to_have_count(0)
            expect(page.get_by_role("button", name="Send message")).to_have_count(0)
            assert page.evaluate("state.room") is None
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == "Meant for X"  # they're still X's, for when it opens
            assert bodies(page, x) == []


def test_going_to_another_page_isnt_undone_by_a_late_room(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            page.get_by_role("link", name="My sharing layers").first.click()
            page.wait_for_function("() => location.hash.startsWith('#layers')")
            reads_settled(page, held=1)
            release(held)
            reads_settled(page)
            assert page.evaluate("location.hash").startswith("#layers")


def test_a_room_read_for_one_account_doesnt_land_for_the_next(browser_peer):
    """A session can end without a sign-out (a 401 goes straight to the sign-in page), so the room read for the last account is
    still out when the next one signs in. Stood in for by changing who's signed in while each kind of open is held."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            for go_to_y in ("void openChat(id)", "location.hash = `chats/${id}`"):
                held = held_routes(page, f"**/api/chats/{y['id']}/board")
                page.evaluate(f"(id) => {{ {go_to_y}; }}", y["id"])
                wait_for_hold(page, held)
                me = page.evaluate("state.me")
                page.evaluate("state.me = { ...state.me, id: 'the-next-account' }")
                release(held)
                reads_settled(page)
                page.unroute(f"**/api/chats/{y['id']}/board")
                assert page.evaluate("state.room.title") == "Room X"
                page.evaluate("(me) => { state.me = me; }", me)
                page.evaluate("(id) => { state.selectedChatId = id; location.hash = `chats/${id}`; }", x["id"])
                reads_settled(page)


def test_a_late_room_doesnt_land_after_sign_out(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            page.evaluate("logout()")
            page.wait_for_function("() => state.me === null")
            release(held)
            reads_settled(page)
            assert page.evaluate("state.room") is None and page.evaluate("state.selectedChatId") is None


def test_a_room_slow_to_open_says_so_on_the_row_pressed_and_not_on_the_page(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            row = page.get_by_role("button", name=re.compile("^Room Y"))
            expect(row).to_contain_text("Opening…")
            expect(row).to_have_attribute("aria-busy", "true")
            assert page.evaluate("document.querySelector('main').hasAttribute('aria-busy')") is False  # X is still there to read
            page.evaluate("render()")  # a draw replaces the row, and the mark stays
            expect(row).to_contain_text("Opening…")
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            expect(page.locator(".pressed-note")).to_have_count(0)
            expect(row).not_to_have_attribute("aria-busy", "true")


def test_a_room_that_answers_in_time_shows_no_mark(browser_peer):
    """Timers fire in order, so this holds however slow the machine is."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            two_rooms_with_x_open(page, store, owner)
            page.evaluate("""async () => {
              window.marks = 0;
              new MutationObserver(() => { window.marks += document.querySelectorAll('.pressed-note').length; }).observe(document.body, { childList: true, subtree: true });
              await whilePressed('.composer', 'Opening…', () => new Promise((resolve) => setTimeout(resolve, 100)));
              await new Promise((resolve) => setTimeout(resolve, 400));
            }""")
            assert page.evaluate("window.marks") == 0


def test_a_room_that_wont_open_ends_the_mark_and_says_so(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            pattern = re.compile(rf"/api/chats/{y['id']}(\?|$)")
            held = held_routes(page, pattern)
            page.get_by_role("button", name="Room Y").click()
            wait_for_hold(page, held)
            row = page.get_by_role("button", name=re.compile("^Room Y"))
            expect(row).to_contain_text("Opening…")  # a row that said this for good is the state a walker hits on a bad link
            for route in held:
                route.abort()
            expect(page.locator(".notice.error")).to_have_text("Room Y didn't open. Connection lost. Try it again.")
            expect(page.locator(".pressed-note")).to_have_count(0)
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            assert page.evaluate("state.selectedChatId") == x["id"] and page.evaluate("state.room.title") == "Room X"
            page.unroute(pattern)
            page.get_by_role("button", name="Room Y").click()  # another try is a new open
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()


def test_pressing_another_room_moves_the_mark(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            z = store.create_room(owner, "Room Z", [])
            page.goto(page.url.split("#")[0] + f"#chats/{x['id']}")
            page.reload()
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            reads_settled(page)
            held_y = y_opening(page, y)
            expect(page.get_by_role("button", name=re.compile("^Room Y"))).to_contain_text("Opening…")
            held_z = held_routes(page, f"**/api/chats/{z['id']}/board")
            page.get_by_role("button", name=re.compile("^Room Z")).click()
            wait_for_hold(page, held_z)
            expect(page.get_by_role("button", name=re.compile("^Room Z"))).to_contain_text("Opening…")
            expect(page.locator(".pressed-note")).to_have_count(1)
            release(held_y)  # Y's late answer doesn't take Z's mark away
            reads_settled(page, held=1)
            expect(page.get_by_role("button", name=re.compile("^Room Z"))).to_contain_text("Opening…")
            release(held_z)
            expect(page.get_by_role("heading", name="Room Z")).to_be_visible()
            expect(page.locator(".pressed-note")).to_have_count(0)


def test_someone_typing_as_the_next_room_arrives_is_told_where_their_words_are(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.click()
            box.press_sequentially("Meant for X")
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            expect(page.locator(".words-kept")).to_have_text("Your words are kept in Room X.")
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == "Meant for X"  # the sentence is true
            page.get_by_role("button", name="Room X").click()
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            reads_settled(page)
            expect(page.locator(".words-kept")).to_have_count(0)
            expect(box).to_have_value("Meant for X")


def test_a_message_sent_during_a_same_room_read_stays(browser_peer):
    """The room on screen takes a new read at once; what's sent during its board read isn't replaced by that older answer."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            for words, read_again in (("By the address", lambda: page.evaluate("void loadRoute()")), ("By a click", lambda: page.get_by_role("button", name="Room X").click())):
                refresh_held = held_routes(page, f"**/api/chats/{x['id']}/board")
                read_again()
                wait_for_hold(page, refresh_held)
                page.get_by_role("textbox", name="Message", exact=True).fill(words)
                page.get_by_role("button", name="Send message").click()
                expect(page.locator(".messages")).to_contain_text(words)
                reads_settled(page, held=1)
                release(refresh_held)
                reads_settled(page)
                page.unroute(f"**/api/chats/{x['id']}/board")
                expect(page.locator(".messages")).to_contain_text(words)
                expect(page.get_by_text("No messages yet")).to_have_count(0)


def test_a_same_room_read_brings_what_arrived(browser_peer):
    users = browser_peer["users"]
    store, owner, family = browser_peer["app"].state.store, users["patient"]["id"], users["family"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner, family)
            store.send_message(family, x["id"], "from-sam", "From Sam")
            page.evaluate("loadRoute().then(() => render())")
            expect(page.locator(".messages")).to_contain_text("From Sam")


def test_a_same_room_read_for_the_last_account_stays_out(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            held = held_routes(page, re.compile(rf"/api/chats/{x['id']}(\?|$)"))
            page.evaluate("void loadRoute()")
            wait_for_hold(page, held)
            page.evaluate("state.room.heldByThisAccount = true; state.me = { ...state.me, id: 'the-next-account' }")
            release(held)
            reads_settled(page)
            assert page.evaluate("state.room.heldByThisAccount") is True  # the answer read for the last account didn't replace it


def test_a_mark_answered_after_the_next_room_opens_names_its_room(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            mark = held_routes(page, f"**/api/chats/{x['id']}/cloud")
            page.get_by_role("button", name=re.compile("^Mark this room$")).click()
            wait_for_hold(page, mark)
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            release(mark)
            expect(page.locator(".notice")).to_have_text("Room X is kept away from ships and connected apps on this home.")  # never read as being about Y
            reads_settled(page)
            assert read_room(page, x).get("cloud") and not read_room(page, y).get("cloud")


def test_clearing_a_mark_goes_to_the_room_on_screen_while_another_opens(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            store.mark_room(owner, x["id"], earlier=False)
            store.mark_room(owner, y["id"], earlier=False)
            page.reload()
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            reads_settled(page)
            held = y_opening(page, y)
            page.get_by_role("button", name="Clear my mark").click()
            expect(page.locator(".notice")).to_contain_text("Your mark on Room X is cleared.")
            reads_settled(page, held=1)
            assert not read_room(page, x).get("cloud") and read_room(page, y).get("cloud")
            release(held)
            reads_settled(page)


def test_after_a_room_fails_to_open_nothing_opens_it_by_itself(browser_peer):
    """A selection left on the failed room would open it at the next refresh, under whatever the person just did."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.evaluate("() => { location.hash = 'chats'; }")  # the address no longer names a room, so the selection decides what a refresh opens
            reads_settled(page)
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            pattern = re.compile(rf"/api/chats/{y['id']}(\?|$)")
            page.route(pattern, lambda route: route.abort())
            page.get_by_role("button", name="Room Y").click()
            expect(page.locator(".notice.error")).to_contain_text("Room Y didn't open.")
            expect(page.locator(".words-kept")).to_contain_text("Room Y didn't open.")  # at the box too, for a reader far below the flash
            page.unroute(pattern)
            page.get_by_role("button", name=re.compile("^Mark this room$")).click()
            expect(page.locator(".notice")).to_have_text("Room X is kept away from ships and connected apps on this home.")
            reads_settled(page)
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()


def test_a_removal_refreshed_after_the_next_room_opens_stays_out_and_says_so(browser_peer):
    users = browser_peer["users"]
    store, owner, family = browser_peer["app"].state.store, users["patient"]["id"], users["family"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner, family)
            refresh_held = held_routes(page, re.compile(rf"/api/chats/{x['id']}(\?|$)"))
            page.get_by_role("button", name=re.compile("^Remove .* from this room")).first.click()
            wait_for_hold(page, refresh_held)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            release(refresh_held)
            reads_settled(page)
            assert page.evaluate("state.room.title") == "Room Y"  # never flips back under what they're typing
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()


def test_a_removal_answered_after_the_next_room_opens_says_which_room(browser_peer):
    users = browser_peer["users"]
    store, owner, family = browser_peer["app"].state.store, users["patient"]["id"], users["family"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner, family)
            held = y_opening(page, y)
            removal = held_routes(page, f"**/api/chats/{x['id']}/participants/**")
            page.get_by_role("button", name=re.compile("^Remove .* from this room")).first.click()
            wait_for_hold(page, removal)
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            release(removal)
            expect(page.locator(".notice")).to_contain_text("no longer has access to Room X on this home")
            reads_settled(page)
            assert family not in read_room(page, x)["member_ids"] and family in read_room(page, y)["member_ids"]


def test_adding_members_goes_to_the_room_the_dialog_opened_for_while_another_opens(browser_peer):
    users = browser_peer["users"]
    store, owner, doctor = browser_peer["app"].state.store, users["patient"]["id"], users["doctor"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            with page.expect_request(f"**/api/chats/{x['id']}/participants") as posted:
                dialog.get_by_role("button", name="Start a new linked chat").click()
            assert posted.value
            release(held)
            reads_settled(page)
            assert doctor not in read_room(page, y)["member_ids"]


def test_a_new_chat_form_stays_a_new_chat_when_the_address_moves_under_it(browser_peer):
    """loadRoute clears the dialog's state before it's drawn away. The form says what it's for, or a new chat with a
    doctor becomes a linked copy of the room behind it, and the doctor reads that room's board."""
    users = browser_peer["users"]
    store, owner, doctor = browser_peer["app"].state.store, users["patient"]["id"], users["doctor"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("button", name="New chat").first.click()
            dialog = page.locator("dialog")
            dialog.locator("#chat-title").fill("Just me and the doctor")
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            held = held_routes(page, re.compile(rf"/api/chats/{y['id']}(\?|$)"))
            page.evaluate("(id) => { location.hash = `chats/${id}`; }", y["id"])
            wait_for_hold(page, held)
            assert page.evaluate("state.chatDialog") is None and dialog.is_visible()  # the window: state cleared, form still up
            with page.expect_request("**/api/chats") as posted:
                dialog.get_by_role("button", name="Create chat").click()
            assert posted.value.method == "POST"
            release(held)
            reads_settled(page)
            assert [room["title"] for room in store.list_rooms(doctor)] == ["Just me and the doctor"]
            assert doctor not in read_room(page, x)["member_ids"]


def test_a_send_that_failed_before_the_next_room_drew_is_said_again_there(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            held = y_opening(page, y)
            posts = held_routes(page, f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            wait_for_hold(page, posts)
            for route in posts:
                route.abort()
            expect(page.locator("#chat-status")).to_contain_text("Your message is still here")
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            expect(page.locator(".words-kept")).to_have_text("Your message may not have been sent. It's still in the box in Room X, so check that room before sending it again.")
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == "Meant for X"


def test_a_send_that_fails_after_the_account_changed_says_nothing(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            posts = held_routes(page, f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            wait_for_hold(page, posts)
            page.evaluate("state.me = { ...state.me, id: 'the-next-account' }")
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            for route in posts:
                route.abort()
            reads_settled(page)
            expect(page.locator(".notice")).to_have_count(0)


def test_a_failed_read_of_the_room_on_screen_leaves_it_there_and_says_so(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            pattern = re.compile(rf"/api/chats/{x['id']}(\?|$)")
            page.route(pattern, lambda route: route.abort())
            page.evaluate("loadRoute().then(() => render())")
            expect(page.locator(".notice.error")).to_contain_text("Room X couldn't be refreshed. Connection lost.")
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            expect(page.get_by_role("button", name="Send message")).to_be_visible()


def test_a_room_whose_board_wont_load_still_opens(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            _x, y = two_rooms_with_x_open(page, store, owner)
            page.route(f"**/api/chats/{y['id']}/board", lambda route: route.abort())
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()


def test_a_new_room_being_made_leaves_the_room_on_screen_until_it_can_draw(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            two_rooms_with_x_open(page, store, owner)
            page.get_by_role("button", name="New chat").first.click()
            dialog = page.locator("dialog")
            dialog.locator("#chat-title").fill("Room Z")
            held = held_routes(page, re.compile(r"/api/chats/[0-9a-f]+/board"))
            dialog.get_by_role("button", name="Create chat").click()
            wait_for_hold(page, held)
            assert page.evaluate("state.room.title") == "Room X"
            release(held)
            expect(page.get_by_role("heading", name="Room Z")).to_be_visible()


def test_typing_on_as_the_next_room_draws_never_reaches_its_box(browser_peer):
    """Pinned for any change that restores focus across a draw: the first half stays with X, the rest goes nowhere, and nothing
    lands in Y's box, where Send would carry it to Y's members."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.click()
            box.press_sequentially("first half")
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            page.keyboard.type(" second half")
            reads_settled(page)
            page.keyboard.type(" third half")
            expect(box).to_have_value("")
            assert page.evaluate("(id) => readChatDraft(id).body", y["id"]) == ""
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == "first half"


def test_a_board_write_answered_after_the_next_room_opens_names_its_room_and_leaves_that_rooms_item_alone(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x = store.create_room(owner, "Room X", [])
            y = store.create_room(owner, "Room Y", [])
            for room in (x, y):
                store.post_item(owner, room["id"], "spec:same", "Same key", "spec")
            page.goto(page.url.split("#")[0] + f"#chats/{x['id']}")
            page.reload()
            panel = page.locator(".room-board")
            settle(page, ready=panel)
            watch_reads(page)  # after the reload: what it cancels never reports back
            reads_settled(page)
            panel.get_by_role("button", name="Drop spec:same").click()
            confirm = panel.get_by_role("button", name="Yes, drop spec:same")
            expect(confirm).to_be_visible()
            settle(page)
            drop = held_routes(page, f"**/api/chats/{x['id']}/board/drop")
            confirm.click()
            wait_for_hold(page, drop)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            release(drop)
            expect(page.locator(".notice")).to_have_text("Room X: Item dropped.")
            reads_settled(page)
            assert page.evaluate("document.activeElement?.closest?.('.board-item') ?? null") is None  # Y's item with the same key
    open_keys = lambda room: [i["key"] for i in store.room_board(owner, room["id"]) if i["state"] == "open"]
    assert open_keys(x) == [] and open_keys(y) == ["spec:same"]


def test_a_brief_conflict_refreshed_after_the_next_room_opens_stays_out(browser_peer):
    users = browser_peer["users"]
    store, owner = browser_peer["app"].state.store, users["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner, users["family"]["id"])
            store.save_brief(owner, x["id"], "Plan for everyone.", 0)
            page.reload()
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            reads_settled(page)
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            store.save_brief(owner, x["id"], "Plan for everyone, revised.", 1)  # another tab
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            dialog.get_by_role("checkbox", name="Carry the room brief").check()
            refresh_held = held_routes(page, re.compile(rf"/api/chats/{x['id']}(\?|$)"))
            dialog.get_by_role("button", name="Start a new linked chat").click()
            wait_for_hold(page, refresh_held)
            page.evaluate("(id) => { location.hash = `chats/${id}`; }", y["id"])
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            release(refresh_held)
            reads_settled(page)
            assert page.evaluate("state.room.title") == "Room Y"
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()


def test_a_send_that_failed_then_went_through_isnt_called_unsent(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            page.route(f"**/api/chats/{x['id']}/messages", lambda route: route.abort())
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_contain_text("Your message is still here")
            page.unroute(f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text("Message saved")
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            expect(page.locator(".words-kept")).to_have_count(0)


def test_the_box_says_whose_words_these_are_even_with_the_heading_screens_away(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            for n in range(25):
                store.send_message(owner, x["id"], f"m{n}", f"A long enough message to fill the screen, number {n}")
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload()
            line = page.locator("#composer-to")
            expect(line).to_have_text("To Room X")
            reads_settled(page)
            box = page.get_by_role("textbox", name="Message", exact=True)
            assert box.get_attribute("aria-describedby") == "composer-to"
            held = y_opening_from_a_long_room(page, y)
            box.scroll_into_view_if_needed()
            expect(line).to_have_text("Room Y is opening. This still goes to Room X.")
            assert page.evaluate("document.querySelector('#composer-to').getBoundingClientRect().top >= 0")
            assert page.evaluate("document.querySelector('#composer-to').getBoundingClientRect().bottom <= innerHeight")
            page.evaluate("render()")
            expect(line).to_have_text("Room Y is opening. This still goes to Room X.")
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            expect(line).to_have_text("To Room Y")


def test_a_room_that_wont_open_puts_the_line_at_the_box_back(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            pattern = re.compile(rf"/api/chats/{y['id']}(\?|$)")
            held = held_routes(page, pattern)
            page.get_by_role("button", name="Room Y").click()
            wait_for_hold(page, held)
            expect(page.locator("#composer-to")).to_have_text("Room Y is opening. This still goes to Room X.")
            for route in held:
                route.abort()
            expect(page.locator(".notice.error")).to_contain_text("Room Y didn't open.")
            expect(page.locator("#composer-to")).to_have_text("To Room X")


def test_the_mark_leaves_the_row_as_it_was(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 844})
                row = page.get_by_role("button", name=re.compile("^Room Y"))
                before = row.locator("strong").bounding_box()
                held = held_routes(page, f"**/api/chats/{y['id']}/board")
                row.click()
                wait_for_hold(page, held)
                expect(row).to_contain_text("Opening…")
                after = row.locator("strong").bounding_box()
                assert after["height"] == before["height"] and after["width"] >= before["width"] * 0.9, (width, before, after)
                release(held)
                expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
                reads_settled(page)
                page.unroute(f"**/api/chats/{y['id']}/board")
                page.get_by_role("button", name="Room X").click()
                expect(page.get_by_role("heading", name="Room X")).to_be_visible()
                reads_settled(page)


def test_a_new_press_ends_the_last_ones_timer_and_the_room_on_screen_gets_no_mark(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            z = store.create_room(owner, "Room Z", [])
            page.reload()
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            reads_settled(page)
            held = [held_routes(page, f"**/api/chats/{room['id']}/board") for room in (y, z)]
            page.evaluate("""(ids) => { openChat(ids[0]); openChat(ids[1]); }""", [y["id"], z["id"]])  # inside the 300 ms
            wait_for_hold(page, held[1])
            page.wait_for_timeout(500)
            expect(page.get_by_role("button", name=re.compile("^Room Y"))).not_to_contain_text("Opening…")
            expect(page.get_by_role("button", name=re.compile("^Room Z"))).to_contain_text("Opening…")
            for routes in held:
                release(routes)
            reads_settled(page)
            page.unroute(f"**/api/chats/{y['id']}/board")
            page.unroute(f"**/api/chats/{z['id']}/board")
            on_screen = page.evaluate("state.room.id")
            again = held_routes(page, f"**/api/chats/{on_screen}/board")
            page.evaluate("(id) => { openChat(id); }", on_screen)
            wait_for_hold(page, again)
            page.wait_for_timeout(500)
            expect(page.locator(".pressed-note")).to_have_count(0)
            release(again)


def test_signing_out_inside_the_wait_ends_the_mark_and_says_nothing(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = held_routes(page, f"**/api/chats/{y['id']}/board")
            page.evaluate("(id) => { openChat(id); logout(); }", y["id"])
            page.wait_for_function("() => state.me === null")
            page.wait_for_timeout(500)
            assert page.evaluate("state.pressed") is None
            assert "Opening" not in page.evaluate("announcer.textContent")
            release(held)


def test_the_mark_and_the_kept_line_are_announced(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            page.wait_for_function("() => announcer.textContent === 'Opening…'")
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.click()
            box.press_sequentially("Meant for X")
            release(held)
            page.wait_for_function("() => announcer.textContent === 'Your words are kept in Room X.'")


def test_nothing_of_the_last_account_stays_when_the_identity_changes(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.evaluate("(id) => { state.composerNote = { roomId: id, words: 'Your words are kept in a private title.' }; state.unsentIn = id; }", x["id"])
            page.evaluate("bindEditorIdentity({ ...state.me, id: 'the-next-account' })")
            for field in ("room", "selectedChatId", "composerNote", "unsentIn", "pressed"):
                assert page.evaluate(f"state.{field}") is None, field


def test_a_new_room_answered_after_the_account_changed_stays_out(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            two_rooms_with_x_open(page, store, owner)
            page.get_by_role("button", name="New chat").first.click()
            dialog = page.locator("dialog")
            dialog.locator("#chat-title").fill("A private new room")
            held = held_routes(page, re.compile(r"/api/chats/[0-9a-f]+/board"))
            dialog.get_by_role("button", name="Create chat").click()
            wait_for_hold(page, held)
            page.evaluate("state.me = { ...state.me, id: 'the-next-account' }")
            release(held)
            reads_settled(page)
            assert page.evaluate("state.room.title") == "Room X"


def test_a_removal_during_a_same_room_read_stays_removed(browser_peer):
    users = browser_peer["users"]
    store, owner, family = browser_peer["app"].state.store, users["patient"]["id"], users["family"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner, family)
            remove = page.get_by_role("button", name=re.compile("^Remove .* from this room"))
            expect(remove).to_have_count(1)
            held = held_routes(page, f"**/api/chats/{x['id']}/board")
            page.evaluate("void loadRoute().then(() => render())")
            wait_for_hold(page, held)
            remove.click()
            expect(remove).to_have_count(0)
            reads_settled(page, held=1)
            release(held)
            reads_settled(page)
            expect(remove).to_have_count(0)


def test_an_older_same_room_read_doesnt_take_back_a_message(browser_peer):
    """Answered before the send but delivered after it and after the send's own refresh: nothing else would restore the message."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            older = []

            def hold_the_answer(route):
                if older:
                    route.continue_()
                else:
                    older.append((route, route.fetch()))
            pattern = re.compile(rf"/api/chats/{x['id']}(\?|$)")
            page.route(pattern, hold_the_answer)
            page.get_by_role("button", name="Room X").click()
            wait_for_hold(page, older)
            page.get_by_role("textbox", name="Message", exact=True).fill("Quick words")
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text("Message saved")
            reads_settled(page, held=1)
            route, response = older[0]
            route.fulfill(response=response)
            reads_settled(page)
            expect(page.locator(".messages")).to_contain_text("Quick words")


def test_the_dialogs_board_warning_survives_a_same_room_read(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            store.post_item(owner, x["id"], "spec:open", "An open item", "spec")
            read = held_routes(page, re.compile(rf"/api/chats/{x['id']}(\?|$)"))
            page.evaluate("void loadRoute()")
            wait_for_hold(page, read)
            items = held_routes(page, f"**/api/chats/{x['id']}/board")
            page.get_by_role("button", name="Change participants").click()
            wait_for_hold(page, items)
            release(read)
            reads_settled(page, held=1)
            release(items)
            page.wait_for_function("() => state.chatBoard !== undefined")


def test_answers_for_a_room_left_name_it(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            refusal = {"error": "This room was replaced by a newer linked room; post in the room that continues it"}
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            page.route(f"**/api/chats/{x['id']}/messages", lambda route: route.fulfill(status=409, json=refusal))
            held = held_routes(page, f"**/api/chats/{y['id']}/board")
            page.get_by_role("button", name="Room Y").click()
            wait_for_hold(page, held)
            posts = held_routes(page, f"**/api/chats/{x['id']}/cloud")
            page.get_by_role("button", name=re.compile("^Mark this room$")).click()
            wait_for_hold(page, posts)
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            for route in posts:
                route.fulfill(status=409, json={"error": "Refused for a reason"})
            expect(page.locator(".notice.error")).to_have_text("Room X: Refused for a reason")


def test_a_send_refused_after_moving_on_reads_as_about_that_room(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            posts = held_routes(page, f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            wait_for_hold(page, posts)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            posts[0].fulfill(status=409, json={"error": "This room was replaced; post in the room that continues it"})
            expect(page.locator(".notice.error")).to_have_text("Your message to Room X wasn't sent. This room was replaced; post in the room that continues it. It's still in the box there.")


def test_a_brief_saved_after_moving_on_names_its_room(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.evaluate("(id) => { state.briefEdit = { roomId: id, body: '', revision: 0 }; }", x["id"])
            page.evaluate("render()")
            box = page.locator("#brief-body")
            box.fill("The plan for X")
            saves = held_routes(page, f"**/api/chats/{x['id']}/brief")
            page.get_by_role("button", name="Save brief").click()
            wait_for_hold(page, saves)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            release(saves)
            expect(page.locator(".notice").first).to_have_text("Room X: Room brief saved.")


def test_a_board_post_answered_after_moving_on_leaves_the_caret_out_of_the_next_rooms_form(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.locator("#board-key").fill("spec:x")
            page.locator("#board-title").fill("X's item")
            posts = held_routes(page, f"**/api/chats/{x['id']}/board")
            page.locator("#board-title").press("Enter")
            wait_for_hold(page, posts)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            release(posts)
            expect(page.locator(".notice").first).to_have_text("Room X: Item posted.")
            reads_settled(page)
            assert page.evaluate("document.activeElement.id") != "board-key"


def test_the_kept_line_is_true_or_absent(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            box = page.get_by_role("textbox", name="Message", exact=True)
            # a failed send whose words were then deleted: nothing's in the box to speak of
            box.fill("Meant for X")
            page.route(f"**/api/chats/{x['id']}/messages", lambda route: route.abort())
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_contain_text("Your message is still here")
            page.unroute(f"**/api/chats/{x['id']}/messages")
            box.fill("")
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            expect(page.locator(".words-kept")).to_have_count(0)
            # a room that's no longer theirs: no line about it
            page.evaluate("state.composerNote = { roomId: 'not-a-room-of-theirs', words: 'Your words are kept in Gone.' }; render()")
            expect(page.locator(".words-kept")).to_have_count(0)


def test_the_kept_line_goes_once_those_words_are_sent(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.fill("Meant for X")
            held = y_opening(page, y)
            posts = held_routes(page, f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            wait_for_hold(page, posts)
            box.click()
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            expect(page.locator(".words-kept")).to_have_text("Your words are kept in Room X.")
            release(posts)
            expect(page.locator(".words-kept")).to_have_count(0)
            reads_settled(page)


def test_a_send_whose_answer_was_lost_doesnt_say_it_wasnt_sent(browser_peer):
    """The home took it and only the answer was lost, so "wasn't sent" would be false, and a person who rewords it sends it twice."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            posts = held_routes(page, f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Send message").click()
            wait_for_hold(page, posts)
            assert posts[0].fetch().ok  # it reached the home
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            posts[0].abort()
            words = "Your message to Room X may not have been sent. Connection lost. It's still in the box there, so check that room before sending it again."
            expect(page.locator(".notice.error")).to_have_text(words)
            expect(page.locator(".words-kept")).to_have_text(words)
            assert bodies(page, x) == ["Meant for X"]
            page.unroute(f"**/api/chats/{x['id']}/messages")
            page.get_by_role("button", name="Room X").click()
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            reads_settled(page)
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("Meant for X")
            page.get_by_role("button", name="Send message").click()  # the same words again: its client id makes it the same message
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("")
            reads_settled(page)
            assert bodies(page, x) == ["Meant for X"]


@pytest.mark.parametrize("status, json, reason, said_later", [
    (403, {"error": "Only members can post"}, "Only members can post.", "Your message wasn't sent. It's still in the box in Room X."),
    (502, {"error": "Bad gateway"}, "Bad gateway. It may have reached the room anyway.", "Your message may not have been sent. It's still in the box in Room X, so check that room before sending it again."),
])
def test_only_a_refusal_says_a_message_wasnt_sent(browser_peer, status, json, reason, said_later):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            page.route(f"**/api/chats/{x['id']}/messages", lambda route: route.fulfill(status=status, json=json))
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text(f"{reason} Your message is still here.")
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            expect(page.locator(".words-kept")).to_have_text(said_later)


@pytest.mark.parametrize("answer", [
    {"content_type": "text/html", "body": "<html><body>Sign in to this network</body></html>"},
    {"content_type": "application/json", "body": '{"id": "cut sho'},
], ids=["a sign-in page", "cut short"])
def test_a_200_that_isnt_the_homes_answer_doesnt_read_as_sent(browser_peer, answer):
    """A proxy or a sign-in page can answer 200 with no JSON, and an answer can be cut short. Neither is a yes, and the box was once emptied."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.fill("Meant for X")
            page.route(f"**/api/chats/{x['id']}/messages", lambda route: route.fulfill(status=200, **answer)
                       if route.request.method == "POST" else route.fallback())
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text(
                "Connection lost. It may have reached the room anyway. Your message is still here.")
            expect(box).to_have_value("Meant for X")
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == "Meant for X"


@pytest.mark.parametrize("asked", ["**/api/**", "**/api/me"], ids=["every question", "who's signed in"])
def test_a_page_opened_behind_a_sign_in_page_doesnt_take_it_for_the_person(browser_peer, asked):
    """A 200 page in the way isn't anyone, whether it answers everything or only the question of who's signed in."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.route(asked, lambda route: route.fulfill(status=200, content_type="text/html", body="<p>Sign in to this network</p>"))
            page.goto(page.url.split("#")[0])
            expect(page.get_by_text("Connection lost. Try again when this home is reachable.")).to_be_visible()
            assert page.evaluate("state.me") is None


@pytest.mark.parametrize("fails", ["an error", "a lost connection"])
def test_a_home_that_wont_open_says_so_and_tries_again(browser_peer, fails):
    """/api/me answers and /api/home doesn't: render returned early on the missing home, so a signed-in person stayed on
    "Opening this home…" with no message (a reader's finding 3, all hands 08929c34). Now the page says the home didn't
    open and why, Try again opens it once the home answers, and Sign out is there if it never does."""
    def fail(route):
        if fails == "an error":
            route.fulfill(status=500, content_type="application/json", body='{"error": "This home could not read its data."}')
        else:
            route.abort("failed")
    said = "This home could not read its data." if fails == "an error" else "Connection lost. Try again when this home is reachable."
    asked = []
    def count_and_fail(route):
        asked.append(route.request.url)
        fail(route)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.route("**/api/home", count_and_fail)
            page.goto(page.url.split("#")[0])
            expect(page.get_by_role("heading", name="This home didn't open", exact=True)).to_be_visible()
            expect(page.locator("#main-content")).to_contain_text(said)
            expect(page.get_by_text("Opening this home…")).to_have_count(0)
            expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible()
            before = len(asked)
            page.get_by_role("button", name="Try again", exact=True).click()  # still failing: it asks again and says so again
            for _ in range(100):
                if len(asked) > before:
                    break
                page.wait_for_timeout(50)
            assert len(asked) == before + 1
            expect(page.get_by_role("button", name="Try again", exact=True)).to_be_enabled()
            expect(page.get_by_role("button", name="Try again", exact=True)).to_be_focused()
            expect(page.locator("#main-content")).to_contain_text(said)
            before = len(asked)
            page.evaluate("location.hash = 'layers'")  # a route on the failed page tries the home again, never a script error
            for _ in range(100):
                if len(asked) > before:
                    break
                page.wait_for_timeout(50)
            assert len(asked) == before + 1
            expect(page.get_by_role("heading", name="This home didn't open", exact=True)).to_be_visible()
            expect(page.locator("#main-content")).to_contain_text(said)
            expect(page.locator("#main-content")).not_to_contain_text("Cannot")
            page.evaluate("location.hash = 'home'")
            expect(page.locator("#main-content")).to_contain_text(said)
            page.unroute("**/api/home")
            page.get_by_role("button", name="Try again", exact=True).click()
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            expect(page.locator("#app")).not_to_contain_text(said)  # the announcer outside it keeps its last words


def test_a_sign_out_that_fails_on_a_home_that_wont_open_says_so(browser_peer):
    """The re-check's S1: with the home unreachable, Sign out's failure set a flag only the account dialog shows, and
    the failed page has no dialog, so nothing was said. Now the page says sign-out couldn't be completed, and why."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.route("**/api/home", lambda route: route.abort("failed"))
            page.goto(page.url.split("#")[0])
            expect(page.get_by_role("heading", name="This home didn't open", exact=True)).to_be_visible()
            page.route("**/api/logout", lambda route: route.abort("failed"))
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.locator("#main-content")).to_contain_text("Sign-out could not be completed. Connection lost.")
            page.unroute("**/api/logout")
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()


def test_an_imprint_link_opened_on_a_home_that_wont_open_keeps_its_code(browser_peer):
    """The second re-check's S1: an imprint confirm link opened in the failed page's tab kept its code until the home
    answered, then lost it when a route on that page began trying the home again. Now the code is taken first, and once
    the home answers, Try again asks for the imprint's preview."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.route("**/api/home", lambda route: route.abort("failed"))
            page.goto(page.url.split("#")[0])
            expect(page.get_by_role("heading", name="This home didn't open", exact=True)).to_be_visible()
            previews = []
            page.on("request", lambda request: previews.append(request.url) if "/api/imprints/code/" in request.url else None)
            page.evaluate("location.hash = 'imprint?code=abc123'")
            expect(page.get_by_role("heading", name="This home didn't open", exact=True)).to_be_visible()
            page.wait_for_function("() => !location.hash.startsWith('#imprint?')")  # taken from the address bar
            page.unroute("**/api/home")
            page.get_by_role("button", name="Try again", exact=True).click()
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            for _ in range(100):
                if previews:
                    break
                page.wait_for_timeout(50)
            assert any(url.endswith("/api/imprints/code/abc123") for url in previews), previews


def test_a_failed_send_is_said_again_when_the_chats_link_closes_the_room_on_a_phone(browser_peer):
    """On a phone the Chats link is the way between rooms, and it takes the status at the box away with the room."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient", viewport={"width": 390, "height": 844}) as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            page.route(f"**/api/chats/{x['id']}/messages", lambda route: route.abort())
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_contain_text("Your message is still here")
            page.get_by_role("link", name="Chats").first.click()
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_count(0)
            expect(page.locator(".notice.error")).to_have_text("Your message may not have been sent. It's still in the box in Room X, so check that room before sending it again.")
            assert page.evaluate("state.unsentIn") is None
            assert page.evaluate("(id) => readChatDraft(id).body", x["id"]) == "Meant for X"


@pytest.mark.parametrize("leave", ["logout()", "showLogin('Your session ended. Sign in again.')"])
def test_a_rooms_title_doesnt_stay_for_the_sign_in_page(browser_peer, leave):
    """The announcer is in the page, where a screen reader finds it, and the next person on this browser is at the sign-in page."""
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            page.route(f"**/api/chats/{x['id']}/messages", lambda route: route.abort())
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_contain_text("Your message is still here")
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            expect(page.locator("#announcer")).to_contain_text("Room X")
            page.evaluate(leave)
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
            expect(page.locator("#announcer")).to_have_text("")


def test_a_brief_whose_answer_was_lost_doesnt_say_it_wasnt_saved(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.evaluate("(id) => { state.briefEdit = { roomId: id, body: '', revision: 0 }; }", x["id"])
            page.evaluate("render()")
            page.locator("#brief-body").fill("The plan for X")
            saves = held_routes(page, f"**/api/chats/{x['id']}/brief")
            page.get_by_role("button", name="Save brief").click()
            wait_for_hold(page, saves)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            saves[0].abort()
            expect(page.locator(".notice.error")).to_have_text("Room X: the brief may not have been saved. Your text is still in its editor.")


def test_a_failed_send_is_said_on_a_page_without_a_composer(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("textbox", name="Message", exact=True).fill("Meant for X")
            page.route(f"**/api/chats/{x['id']}/messages", lambda route: route.abort())
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_contain_text("Your message is still here")
            page.get_by_role("link", name="My sharing layers").first.click()
            expect(page.locator(".notice.error")).to_have_text("Your message may not have been sent. It's still in the box in Room X, so check that room before sending it again.")


def test_the_kept_line_shows_on_a_replaced_room_too(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    users = browser_peer["users"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            page.evaluate("""(id) => {
              state.home.chats = [...state.home.chats, { id: 'its-successor', title: 'Successor', linked_room_id: id, member_ids: [] }];
              state.composerNote = { roomId: id, words: 'Words for the line' };
              render();
            }""", x["id"])
            expect(page.locator(".composer-replaced .words-kept")).to_have_text("Words for the line")


def test_a_read_refused_for_a_session_that_ended_goes_to_sign_in(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            _x, y = two_rooms_with_x_open(page, store, owner)
            page.route(re.compile(rf"/api/chats/{y['id']}(\?|$)"), lambda route: route.fulfill(status=401, json={"error": "Sign in required"}))
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_text("Your session ended. Sign in again.")).to_be_visible()


def test_a_conflict_in_the_window_is_said_in_the_dialog(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            page.route(f"**/api/chats/{x['id']}/participants", lambda route: route.fulfill(status=409, json={"error": "This room was replaced"}))
            page.evaluate("() => { state.chatDialog = null; }")  # as loadRoute leaves it, with the form still up
            dialog.get_by_role("button", name="Start a new linked chat").click()
            expect(dialog.get_by_role("alert")).to_contain_text("This room was replaced")


def test_a_read_landing_before_the_sends_own_refresh_keeps_the_message(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            older, refresh = [], []

            def hold(route):
                if not older:
                    older.append((route, route.fetch()))
                elif not refresh:
                    refresh.append(route)
                else:
                    route.continue_()
            page.route(re.compile(rf"/api/chats/{x['id']}(\?|$)"), hold)
            page.get_by_role("button", name="Room X").click()
            wait_for_hold(page, older)
            page.get_by_role("textbox", name="Message", exact=True).fill("Quick words")
            page.get_by_role("button", name="Send message").click()
            wait_for_hold(page, refresh)
            route, response = older[0]
            route.fulfill(response=response)
            reads_settled(page, held=1)
            expect(page.locator(".messages")).to_contain_text("Quick words")
            release(refresh)
            reads_settled(page)


def test_a_conflict_answered_after_moving_on_stays_out_of_the_next_room(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.get_by_role("button", name="Change participants").click()
            dialog = page.locator("dialog")
            dialog.get_by_role("checkbox", name="Dr. Morgan").check()
            posts = held_routes(page, f"**/api/chats/{x['id']}/participants")
            dialog.get_by_role("button", name="Start a new linked chat").click()
            wait_for_hold(page, posts)
            page.evaluate("(id) => { location.hash = `chats/${id}`; }", y["id"])
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            posts[0].fulfill(status=409, json={"error": "This room was replaced"})
            expect(page.locator(".notice.error")).to_have_text("Room X: This room was replaced")
            expect(page.locator("dialog")).to_have_count(0)  # no dialog over Y for a conflict in X


def test_nothing_said_to_the_last_account_stays_for_the_next(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            two_rooms_with_x_open(page, store, owner)
            page.get_by_role("button", name=re.compile("^Mark this room$")).click()
            expect(page.locator(".notice")).to_have_text("Room X is kept away from ships and connected apps on this home.")
            page.evaluate("state.transitionNote = 'Sam no longer has access'; announcer.textContent = 'Your words are kept in Room X.'")
            page.evaluate("bindEditorIdentity({ ...state.me, id: 'the-next-account' })")
            for field in ("flash", "transitionNote"):
                assert page.evaluate(f"state.{field}") is None, field
            assert page.evaluate("announcer.textContent") == ""


@pytest.mark.parametrize("press, route", [
    ("^Mark this room$", "cloud"),
    ("^Remove .* from this room", "participants/**"),
])
def test_a_late_answer_names_no_room_to_the_next_account(browser_peer, press, route):
    users = browser_peer["users"]
    store, owner = browser_peer["app"].state.store, users["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner, users["family"]["id"])
            answers = held_routes(page, f"**/api/chats/{x['id']}/{route}")
            page.get_by_role("button", name=re.compile(press)).first.click()
            wait_for_hold(page, answers)
            page.evaluate("state.me = { ...state.me, id: 'the-next-account' }")
            release(answers)
            reads_settled(page)
            expect(page.locator(".notice")).to_have_count(0)


def test_a_brief_refused_after_moving_on_says_so_and_keeps_the_words(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.evaluate("(id) => { state.briefEdit = { roomId: id, body: '', revision: 0 }; }", x["id"])
            page.evaluate("render()")
            page.locator("#brief-body").fill("The plan for X")
            saves = held_routes(page, f"**/api/chats/{x['id']}/brief")
            page.get_by_role("button", name="Save brief").click()
            wait_for_hold(page, saves)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            saves[0].fulfill(status=400, json={"error": "A brief is at most 4,000 characters"})
            expect(page.locator(".notice.error")).to_have_text("Room X: the brief wasn't saved. Your text is still in its editor.")
            assert page.evaluate("state.briefEdit.body") == "The plan for X"


def test_a_brief_refused_after_another_editor_took_its_place_doesnt_promise_the_words(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            page.evaluate("(id) => { state.briefEdit = { roomId: id, body: '', revision: 0 }; }", x["id"])
            page.evaluate("render()")
            page.locator("#brief-body").fill("The plan for X")
            saves = held_routes(page, f"**/api/chats/{x['id']}/brief")
            page.get_by_role("button", name="Save brief").click()
            wait_for_hold(page, saves)
            page.get_by_role("button", name="Room Y").click()
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page, held=1)
            page.evaluate("(id) => { state.briefEdit = { roomId: id, body: '', revision: 0 }; }", y["id"])
            saves[0].fulfill(status=400, json={"error": "A brief is at most 4,000 characters"})
            expect(page.locator(".notice.error")).to_have_text("Room X: the brief wasn't saved.")


def test_a_brief_answered_after_the_session_ended_leaves_no_editor_stuck(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            for answer in ({"status": 400, "json": {"error": "A brief is at most 4,000 characters"}}, None):
                page.evaluate("(id) => { state.briefEdit = { roomId: id, body: '', revision: 0 }; }", x["id"])
                page.evaluate("render()")
                page.locator("#brief-body").fill("The plan for X")
                saves = held_routes(page, f"**/api/chats/{x['id']}/brief")
                page.get_by_role("button", name="Save brief").click()
                wait_for_hold(page, saves)
                me = page.evaluate("state.me")
                page.evaluate("state.me = { ...state.me, id: 'the-next-account' }")
                saves[0].fulfill(**answer) if answer else saves[0].continue_()
                reads_settled(page)
                page.unroute(f"**/api/chats/{x['id']}/brief")
                assert page.evaluate("state.briefEdit ? state.briefEdit.saving : false") is False
                page.evaluate("(me) => { state.me = me; state.briefEdit = null; }", me)


def signed_out_as_a_read_answers(page, peer, held, *, next_signs_in):
    """A read was out as the person signed out, and it answers on the sign-in page or once the next person is in."""
    page.get_by_role("button", name="Account and sign out").click()
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
    if next_signs_in:
        page.get_by_label("Username", exact=True).fill("organizer")
        page.get_by_label("Password", exact=True).fill(peer["password"])
        page.get_by_role("button", name="Sign in").click()
        expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
    held[0].continue_()
    reads_settled(page)
    page.wait_for_timeout(200)  # an announcement lands on the next frame
    assert page.evaluate("state.flash") is None
    assert page.evaluate("document.querySelector('#announcer').textContent") == ""
    expect(page.get_by_text("Room X")).to_have_count(0)


@pytest.mark.parametrize("next_signs_in", [False, True])
def test_a_brief_saved_as_the_person_signs_out_names_no_room_to_the_next(browser_peer, next_signs_in):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            page.evaluate("(id) => { state.briefEdit = { roomId: id, body: '', revision: 0 }; }", x["id"])
            page.evaluate("render()")
            page.locator("#brief-body").fill("The plan for X")
            held = held_routes(page, re.compile(rf"/api/chats/{x['id']}(\?|$)"))  # the read after the save
            page.get_by_role("button", name="Save brief").click()
            wait_for_hold(page, held)
            signed_out_as_a_read_answers(page, browser_peer, held, next_signs_in=next_signs_in)


@pytest.mark.parametrize("next_signs_in", [False, True])
def test_a_mark_made_as_the_person_signs_out_names_no_room_to_the_next(browser_peer, next_signs_in):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, _y = two_rooms_with_x_open(page, store, owner)
            held = held_routes(page, re.compile(rf"/api/chats/{x['id']}(\?|$)"))  # refresh's read, after the mark
            page.get_by_role("button", name=re.compile("^Mark this room$")).click()
            wait_for_hold(page, held)
            signed_out_as_a_read_answers(page, browser_peer, held, next_signs_in=next_signs_in)


def test_a_read_refused_at_an_address_for_a_session_that_ended_goes_to_sign_in(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            _x, y = two_rooms_with_x_open(page, store, owner)
            page.route(re.compile(rf"/api/chats/{y['id']}(\?|$)"), lambda route: route.fulfill(status=401, json={"error": "Sign in required"}))
            page.evaluate("(id) => { location.hash = `chats/${id}`; }", y["id"])
            expect(page.get_by_text("Your session ended. Sign in again.")).to_be_visible()


def test_a_room_title_kept_for_that_line_goes_at_sign_out(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            held = y_opening(page, y)
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.click()
            box.press_sequentially("Meant for X")
            release(held)
            expect(page.locator(".words-kept")).to_have_text("Your words are kept in Room X.")
            page.evaluate("logout()")
            page.wait_for_function("() => state.me === null")
            assert page.evaluate("state.composerNote") is None


def test_no_word_about_kept_words_when_nobody_was_typing(browser_peer):
    store, owner = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            x, y = two_rooms_with_x_open(page, store, owner)
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.fill("Left here on purpose")
            page.get_by_role("button", name="Room Y").click()  # focus left the box to press this
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            expect(page.locator(".words-kept")).to_have_count(0)
            page.get_by_role("button", name="Room X").click()
            expect(page.get_by_role("heading", name="Room X")).to_be_visible()
            reads_settled(page)
            box.fill("   ")
            held = y_opening(page, y)
            box.click()  # in the box, with only spaces in it
            release(held)
            expect(page.get_by_role("heading", name="Room Y")).to_be_visible()
            reads_settled(page)
            expect(page.locator(".words-kept")).to_have_count(0)


def test_chat_keeps_unsent_text_and_membership_change_starts_empty_room(browser_peer):
    """Break caught: a network error drops text or exposes old messages to a new member."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, context):
            page.get_by_role("link", name="Chats", exact=True).click()
            page.get_by_role("button", name="New chat").click()
            page.get_by_label("Chat title").fill("Care planning")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("checkbox", name="Dr. Morgan").check()
            page.get_by_role("button", name="Create chat").click()
            page.get_by_role("textbox", name="Message", exact=True).fill("This belongs to the original room.")
            page.get_by_role("button", name="Send message").click()
            # wait on what the send produces, its last render's status (app.js sendMessage), never on text already shown
            expect(page.locator("#chat-status")).to_have_text("Message saved")
            expect(page.get_by_text("This belongs to the original room.")).to_be_visible()

            page.get_by_role("textbox", name="Message", exact=True).fill("Keep this through a connection problem.")
            context.set_offline(True)
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text("Connection lost. It may have reached the room anyway. Your message is still here.")
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value(
                "Keep this through a connection problem."
            )
            context.set_offline(False)
            page.reload()
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value(
                "Keep this through a connection problem."
            )
            page.get_by_role("button", name="Send message").click()
            # the restored draft is the textarea's own text, so the message's text matched before the send answered,
            # and the send's render could land after Taylor was checked, unchecking it (run 40860178482)
            expect(page.locator("#chat-status")).to_have_text("Message saved")
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("")
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
            expect(page.get_by_text("Account support does not open anyone's chats or drafts.")).to_be_visible()
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
            expect(page.get_by_text("Account created. Sign in with your new password.")).to_be_visible()
            if browser_peer['local_demo']:
                expect(page.get_by_text('Sign in with another account', exact=True)).to_be_visible()
                page.get_by_text('Sign in with another account', exact=True).click()
            page.get_by_label("Username", exact=True).fill("newperson")
            page.get_by_label("Password", exact=True).fill("another-long-password")
            page.get_by_role("button", name="Sign in").click()
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()


def preview_remote_card(page, browser_peer):
    page.get_by_role("link", name="Connections", exact=True).click()
    page.get_by_label("Peer card").fill(json.dumps(browser_peer["remote_card"]))
    page.get_by_role("button", name="Preview peer card").click()
    expect(page.get_by_role("heading", name="Casey Remote")).to_be_visible()


def test_show_my_peer_card_shows_the_code_apart_from_the_card(browser_peer):
    """fix:pairing-code (plan review SF7): the code isn't in the copyable card, so one copy never carries both."""
    browser_peer["app"].state.federation.endpoint = "https://localhost:7435"
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Connections", exact=True).click()
            page.get_by_role("button", name="Show my peer card").click()
            card = browser_peer["app"].state.federation.card(browser_peer["users"]["patient"]["id"])
            code = show_code(pairing_code(card))
            shown = page.get_by_test_id("my-pairing-code")
            expect(shown).to_contain_text(code)
            expect(shown).to_contain_text("Type this on the other machine. Never send it with the card.")
            flash = page.locator(".notice[role=status]").first.inner_text()
            assert card["peer_id"] in flash and code not in flash and pairing_code(card) not in flash


def test_the_code_box_starts_empty_and_an_empty_or_wrong_code_pairs_nothing(browser_peer):
    code = pairing_code(browser_peer["remote_card"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            preview_remote_card(page, browser_peer)
            box = page.get_by_label("Type the code shown on the other machine")
            expect(box).to_have_value("")
            content = page.content()
            assert code not in content and show_code(code) not in content  # the preview never shows it
            page.get_by_role("button", name="Pair this peer").click()
            expect(page.locator(".notice.error")).to_have_text("Type the pairing code shown on the other machine")
            page.get_by_label("Type the code shown on the other machine").fill("0" * 32)
            page.get_by_role("button", name="Pair this peer").click()
            expect(page.locator(".notice.error")).to_contain_text("That code doesn't match this card.")
            expect(page.get_by_role("heading", name="Casey Remote")).to_have_count(0)  # the preview is cleared
            expect(page.get_by_role("button", name="Disconnect peer and 1 contact")).to_have_count(0)
    assert browser_peer["app"].state.federation.connections(browser_peer["users"]["organizer"]["id"]) == []


def test_the_right_code_typed_with_enter_pairs_and_survives_a_re_render(browser_peer):
    code = show_code(pairing_code(browser_peer["remote_card"]))
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            preview_remote_card(page, browser_peer)
            box = page.get_by_label("Type the code shown on the other machine")
            box.fill(code[:10])
            page.get_by_role("button", name="Check delivery now").click()  # refresh() renders the page again
            # wait on what the click produces, its render with its flash, never on the value already there before it
            # (fix:pairing-code-test-refresh-race): a late render could land during the typing below, or replace the
            # pairing's flash before it's checked, and the value check alone passed before any re-render happened
            expect(page.locator(".notice[role=status]")).to_have_text("Delivery status refreshed")
            expect(page.get_by_label("Type the code shown on the other machine")).to_have_value(code[:10])
            page.get_by_label("Type the code shown on the other machine").fill(code)
            page.get_by_label("Type the code shown on the other machine").press("Enter")
            expect(page.locator("#main-content").get_by_text("Peer paired. Nothing has been shared automatically.")
                   ).to_be_visible()
            expect(page.get_by_text(f"Pairing code: {code}")).to_be_visible()
            expect(page.get_by_text("Confirmed by typing", exact=True)).to_be_visible()


def test_pairing_pending_delivery_and_peer_wide_disconnect_states(browser_peer):
    """Break caught: pairing shares implicitly or canceled delivery looks retryable."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            page.get_by_role("link", name="Connections", exact=True).click()
            page.get_by_label("Peer card").fill(json.dumps(browser_peer["remote_card"]))
            page.get_by_role("button", name="Preview peer card").click()
            expect(page.get_by_role("heading", name="Casey Remote")).to_be_visible()
            expect(page.get_by_text(browser_peer["remote_card"]["fingerprint"])).to_be_visible()
            page.get_by_label("Type the code shown on the other machine").fill(
                show_code(pairing_code(browser_peer["remote_card"]))
            )
            page.get_by_role("button", name="Pair this peer").click()
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
            page.get_by_role("button", name="New chat").click()
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
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()


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
            page.get_by_role("button", name="New chat").click()
            page.get_by_label("Chat title").fill("First audience")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("checkbox", name="Dr. Morgan").check()
            page.get_by_role("button", name="Create chat").click()
            expect(page.get_by_role("heading", name="First audience")).to_be_visible()
            room_id = decode_fragment_id(page.url)

            page.get_by_role("button", name="New chat").click()
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
            expect(page.get_by_text("Sam Family no longer has access on this home; remote removal requires acknowledgement")).to_be_visible()

            with signed_in_browser(playwright, browser_peer, "family") as (family, _):
                family.goto(browser_peer["base_url"] + f"/#chats/{room_id}")
                expect(family.get_by_role("heading", name="First audience")).to_have_count(0)


def list_under(control, heading):
    """The list right under a heading, so changing a word of either fails: "It can:" over these items is the promise itself."""
    return control.locator(f'xpath=.//p[normalize-space()="{heading}"]/following-sibling::ul[1]/li')


def test_the_mark_says_what_it_enforces_and_what_it_cant_stop(browser_peer):
    """A person relies on the mark at the moment they set it, so it says there what it keeps out, what one mark does to
    everyone, and what it can't do. The sign-in page's line isn't on screen then. A member someone else has marked for is
    told it already holds, and why they might add theirs. A cold walker stopped at the second sentence of a paragraph,
    so it starts with what a person most wants to know, and the rest is lists."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    limits = ["stop whoever runs this home, or an AI agent they run on its computer, reading or changing it",
              "take back what a ship or app has already read",
              "stop a member copying the words or giving them to an AI"]
    room = store.create_room(users["patient"]["id"], "To be marked", [users["family"]["id"]])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        page.goto(f"{base}/#chats/{room['id']}")
        page.reload()
        control = page.locator(".cloud-control")
        expect(control).to_contain_text("Mark this room to keep AI agents with an account on this home (ships) and connected apps, such as Claude, out of it. Everyone in it still reads it, and people on this home can still be added.")
        expect(list_under(control, "One member's mark holds for the whole room:")).to_have_text([
            "No ship can join, and any ship here has to be removed first.", "No member's connected app can read it.",
            "Nobody new from another home can join.",
            "Only the member who set it can clear it, and only while they're in the room. If they leave or are removed, it stays."])
        expect(list_under(control, "It can't:")).to_have_text(limits)
        expect(control).not_to_contain_text("another home, who may be")  # nobody on another home here
        page.get_by_role("button", name="Mark this room").click()
        expect(page.locator(".notice", has_text="To be marked is kept away from ships and connected apps on this home.")).to_be_visible()
        expect(control).to_contain_text("You've marked this room, so AI agents with an account on this home (ships) and connected apps, such as Claude, are kept out of it, every member's connected apps included. Everyone in it still reads it. It stays until you clear it, and you can clear it only while you're in the room.")
        expect(control).to_contain_text("another member's mark would still hold")
        expect(control).not_to_contain_text("earlier rooms")  # this one has none
        expect(list_under(control, "It can't:")).to_have_text(limits)
        expect(page.locator(".split-detail").get_by_text("Marked · 1 mark (yours)", exact=True)).to_be_visible()
        with signed_in_browser(playwright, browser_peer, "family") as (other, _):
            other.goto(f"{base}/#chats/{room['id']}")
            theirs = other.locator(".cloud-control")
            expect(theirs).to_contain_text("A member has marked this room, so AI agents with an account on this home (ships) and connected apps, such as Claude, are already kept out of it, every member's connected apps included. Everyone in it still reads it.")
            expect(theirs).to_contain_text("Only the member who set a mark can clear it, and only while they're in the room. If they leave or are removed, it stays.")
            expect(theirs).to_contain_text("Add your own and it still holds if they clear theirs.")
            expect(list_under(theirs, "It can't:")).to_have_text(limits)
            expect(other.locator(".split-detail").get_by_text("Marked · 1 mark", exact=True)).to_be_visible()
            other.get_by_role("button", name="Add my mark too").click()
            expect(other.locator(".split-detail").get_by_text("Marked · 2 marks (one yours)", exact=True)).to_be_visible()
            other.get_by_role("button", name="Clear my mark").click()
            expect(other.locator(".notice", has_text="Your mark on To be marked is cleared. Other members' marks still stand.")).to_be_visible()
        page.get_by_role("button", name="Clear my mark").click()
        expect(page.locator(".notice", has_text="Your mark on To be marked is cleared. This room has no marks now.")).to_be_visible()


def test_adding_my_mark_still_offers_the_earlier_rooms_and_says_so_only_if_marked(browser_peer):
    """Another member's mark on the continuing room leaves the choice about the earlier one this person is in. Ticked, the
    control says those marks stay. Unticked, it says nothing of them, because there are none."""
    base, store = browser_peer["base_url"], browser_peer["app"].state.store
    patient, family, doctor = (browser_peer["users"][name]["id"] for name in ("patient", "family", "doctor"))
    first = store.create_room(patient, "Kept close", [family])["id"]
    second = store.add_participants(patient, first, [doctor])["id"]
    store.mark_room(doctor, second)
    stays = "Your marks on its earlier rooms stay."
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "family") as (page, _):
        page.goto(f"{base}/#chats/{second}")
        box = page.get_by_role("checkbox", name="Mark the 1 earlier room you're in too")
        expect(box).to_be_checked()
        box.uncheck()
        page.get_by_role("button", name="Add my mark too").click()
        expect(page.get_by_role("button", name="Clear my mark")).to_be_visible()
        expect(page.locator(".cloud-control")).not_to_contain_text(stays)  # she unticked it, and has none there
        with store.transaction() as db:
            assert db.execute("SELECT count(*) FROM room_cloud WHERE room_id=? AND member_id=?", (first, family)).fetchone()[0] == 0
        page.get_by_role("button", name="Clear my mark").click()
        page.get_by_role("button", name="Add my mark too").click()
        expect(page.locator(".cloud-control")).to_contain_text(stays)
        with store.transaction() as db:
            assert db.execute("SELECT count(*) FROM room_cloud WHERE room_id=? AND member_id=?", (first, family)).fetchone()[0] == 1


def test_a_member_marks_a_room_and_every_member_sees_the_badge(browser_peer):
    """Never to a cloud model (connector plan, Task 2): a member marks a continuing room and, by default, the earlier
    room they're in; every member sees the badge with its count, and only the marker sees "(yours)"."""
    store = browser_peer["app"].state.store
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Chats", exact=True).click()
            page.get_by_role("button", name="New chat").click()
            page.get_by_label("Chat title").fill("Kept close")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("button", name="Create chat").click()
            expect(page.get_by_role("heading", name="Kept close")).to_be_visible()
            first = decode_fragment_id(page.url)
            page.get_by_role("button", name="Change participants").click()
            page.get_by_role("checkbox", name="Dr. Morgan").check()
            page.get_by_role("button", name="Start a new linked chat").click()
            expect(page.get_by_text("New room · earlier messages stay in the original chat")).to_be_visible()
            second = decode_fragment_id(page.url)
            assert second != first

            with signed_in_browser(playwright, browser_peer, "family") as (family, _):
                family.goto(browser_peer["base_url"] + f"/#chats/{second}")
                expect(family.get_by_role("heading", name="Kept close")).to_be_visible()
                expect(family.get_by_role("checkbox", name="Mark the 1 earlier room you're in too")).to_be_checked()
                family.get_by_role("button", name="Mark this room").click()
                expect(family.locator(".split-detail").get_by_text("Marked · 1 mark (yours)")).to_be_visible()
                expect(family.locator(".split-list").get_by_text("Marked · 1 mark (yours)")).to_have_count(2)
                expect(family.get_by_role("button", name="Clear my mark")).to_be_visible()
                expect(family.get_by_text("Clearing takes your mark off this room only, and another member's mark would still hold. Your marks on its earlier rooms stay.")).to_be_visible()

            page.reload()
            expect(page.locator(".split-detail").get_by_text("Marked · 1 mark", exact=True)).to_be_visible()
        with store.transaction() as db:
            marked = {r[0] for r in db.execute("SELECT room_id FROM room_cloud")}
        assert marked == {first, second}


def test_the_mark_controls_say_what_they_do(browser_peer):
    """Rio Grande's section 2 of room-cloud-ui (M1, S2, N1, N2): unticking the earlier rooms marks this room alone;
    "Clear my mark" clears it; the owner's add dialog says the new room keeps the mark; a room with a member on another
    home says what still goes there; a received or replaced room offers no mark; the badge shows a number only."""
    store = browser_peer["app"].state.store
    patient, family, doctor = (browser_peer["users"][name]["id"] for name in ("patient", "family", "doctor"))
    first = store.create_room(patient, "Kept close", [family])["id"]
    second = store.add_participants(patient, first, [doctor])["id"]
    with store.transaction() as db:  # a member on another home, as federation stores one (no pairing in a test)
        db.execute("INSERT OR IGNORE INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", ("b" * 64,))
        db.execute("INSERT INTO remote_contacts VALUES(?,?,?,?)", ("remote_willa", "b" * 64, "willa", "Willa Away"))
    across = store.create_room(patient, "Across homes", [family, "remote_willa"])["id"]

    def marked():
        with store.transaction() as db:
            return {r[0] for r in db.execute("SELECT room_id FROM room_cloud")}
    base = browser_peer["base_url"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.goto(base + f"/#chats/{second}")
            page.get_by_role("checkbox", name="Mark the 1 earlier room you're in too").uncheck()
            page.get_by_role("button", name="Mark this room").click()
            expect(page.get_by_role("button", name="Clear my mark")).to_be_visible()
            assert marked() == {second}  # unticked: this room alone

            with signed_in_browser(playwright, browser_peer, "patient") as (owner, _):
                owner.goto(base + f"/#chats/{second}")
                owner.get_by_role("button", name="Change participants").click()
                expect(owner.get_by_text("The new room keeps the mark: no ship, and no one on another home, can join it.")).to_be_visible()
                owner.goto(base + f"/#chats/{across}")
                expect(owner.get_by_role("heading", name="Across homes")).to_be_visible()
                expect(owner.locator(".cloud-control")).to_contain_text("stop what's said here still going to a member already on another home, who may be a person or a ship, under that home's rules. Their home isn't told about the mark.")
                assert owner.evaluate("cloudControl({id: 'x', origin: 'a-peer', member_ids: []}, false)") == ""
                assert "Mark this room" not in owner.evaluate("cloudControl({id: 'x', member_ids: []}, true)")
                assert "<b>" not in owner.evaluate("cloudBadge({cloud: {count: '<b>1</b>', mine: false}})")

            page.get_by_role("button", name="Clear my mark").click()
            expect(page.get_by_role("button", name="Mark this room")).to_be_visible()
            assert marked() == set()


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
            # "Private draft saved" still shows from the first save, so wait for this save's own answer before
            # reading the store (fix:browser-source-layer-flakes: about 1 in 8 on the Mac read it in flight)
            with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith(f"/api/layers/{layer_id}")):
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
            page.get_by_role("button", name="New chat").click()
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
            page.get_by_role("button", name="New chat").click()
            page.get_by_label("Chat title").fill("Removal boundary")
            page.get_by_role("checkbox", name="Sam Family").check()
            page.get_by_role("button", name="Create chat").click()
            expect(page.get_by_role("heading", name="Removal boundary")).to_be_visible()
            room_id = decode_fragment_id(page.url)
            page.get_by_role("button", name="Remove Sam Family from this room").click()
            expect(page.locator("#main-content").get_by_text("Sam Family no longer has access on this home; remote removal requires acknowledgement. Latest room status is unavailable.")).to_be_visible()
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
            expect(page.locator('#main-content').get_by_text('Imported. Recorded audiences did not grant access.', exact=True)).to_be_visible()
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
                expect(page.get_by_role('heading', name='Sign in to this home')).to_be_visible()
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
    browser_peer['app'].state.federation.pair(admin, browser_peer['remote_card'], code=pairing_code(browser_peer['remote_card']))
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


@pytest.mark.sync_worker
def test_delivery_waiting_acknowledgement_refresh_and_unsaved_state(browser_peer, tmp_path):
    app = browser_peer['app']
    fed, store = app.state.federation, app.state.store
    owner = browser_peer['users']['organizer']['id']
    remote = Store(tmp_path / 'delivery-peer')
    recipient = remote.create_user('remote', 'Casey Delivery', 'long-password', is_admin=True)['id']
    other = Federation(remote, endpoint='https://remote.example:7443')
    fed.endpoint = 'https://local.example:7443'
    contact = fed.pair(owner, other.card(recipient), code=pairing_code(other.card(recipient)))
    back = other.pair(recipient, fed.card(owner), code=pairing_code(fed.card(owner)))
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
            # federation pull spec §8: a failed row reads "Retrying", with the peer's next attempt
            expect(page.get_by_text("peer to acknowledge withdrawal — retrying, next attempt", exact=False)).to_be_visible()
            expect(page.get_by_text('remote acknowledgement unknown', exact=False)).to_be_visible()
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
            page.get_by_role('button', name='New chat').click()
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
        expect(page.get_by_text('Account created. Sign in with your new password.', exact=True)).to_be_visible()
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


def test_the_ship_banner_says_what_crosses_the_bridge_and_never_counts_wormhole_as_claude(browser_peer):
    """Break caught: a bridged room's banner names only Claude, or a room whose only ship is Wormhole says Claude reads it."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    wormhole = store.create_station_ship("wormhole", "Wormhole")
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(users["patient"]["id"], started["id"], started["code"])
    only_bridge = store.create_room(users["patient"]["id"], "Lattice", [wormhole["id"]])
    both = store.create_room(users["patient"]["id"], "Ops", [ship["id"], wormhole["id"]])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        page.goto(f"{base}/#chats/{only_bridge['id']}")
        page.reload()
        banner = page.locator(".ship-banner")
        expect(banner).to_contain_text("Wormhole bridges this room to Stanley's aDNA lattice.")
        expect(banner).to_contain_text("copied there with its author's name and this room's title, outside this station")
        expect(banner).not_to_contain_text("Claude")
        page.goto(f"{base}/#chats/{both['id']}")
        page.reload()
        expect(banner).to_contain_text("Ships in this room send its text to Claude.")
        expect(banner).to_contain_text("Aboard: Serenity.")
        expect(banner).to_contain_text("Wormhole bridges this room to Stanley's aDNA lattice.")


def test_the_banner_says_a_room_with_members_on_another_home_is_copied_there(browser_peer):
    """fix:banner-room-with-remote-members (the banner review's outside note): a room with members on another home
    copies its title and messages to their homes, and no banner said so. It names them, escaped, says what crosses and
    what stays, and that this home can't tell a person there from a ship that sends text to Claude (the section 2's
    MF1). Two members on one home aren't called two homes (S2). A received room says its home is the other one (S4)."""
    base, store = browser_peer["base_url"], browser_peer["app"].state.store
    patient, family = (browser_peer["users"][name]["id"] for name in ("patient", "family"))
    with store.transaction() as db:  # a member on another home, as federation stores one (no pairing in a test)
        db.execute("INSERT OR IGNORE INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", ("b" * 64,))
        db.execute("INSERT INTO remote_contacts VALUES(?,?,?,?)", ("remote_willa", "b" * 64, "willa", "Willa <b>Away</b>"))
    across = store.create_room(patient, "Across homes", [family, "remote_willa"])["id"]
    local = store.create_room(patient, "At home", [family])["id"]
    one = ("Willa <b>Away</b>: this room's title and messages are copied to their home; its brief and board stay here. "
           "That home keeps its own copy under its own rules, and this home can't always tell whether the member is a person or "
           "a ship that sends text to Claude.")
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        page.goto(f"{base}/#chats/{across}")
        page.reload()
        banner = page.locator(".ship-banner")
        expect(banner).to_contain_text("A member of this room isn't on this home.")
        expect(banner).to_contain_text(one)
        expect(banner).not_to_contain_text("Ships in this room send its text to Claude.")
        page.goto(f"{base}/#chats/{local}")
        page.reload()
        expect(page.get_by_role("heading", name="At home")).to_be_visible()
        expect(page.locator(".ship-banner")).to_have_count(0)
        two = page.evaluate("shipBanner({member_ids: ['remote_willa', 'remote_omar'], members: []})")
        assert "Some members of this room aren't on this home." in two and "Willa &lt;b&gt;Away&lt;/b&gt;, " in two
        assert ("this room's title and messages are copied to each one's home; its brief and board stay here. Each home "
                "keeps its own copy under its own rules, and this home can't always tell whether a member there is a person or "
                "a ship that sends text to Claude.") in two
        assert "other homes" not in two  # both may be on one home
        received = page.evaluate("shipBanner({origin: 'a-peer', member_ids: ['remote_willa'], members: []})")
        assert "This room's home is another home." in received and "Willa" not in received
        assert ("What you write here is copied there and to each member's home, under their rules. This home can't see "
                "whether ships there send it to Claude.") in received


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
            expect(page.get_by_text("Only your own ships get these, and only once you turn on a version. A ship sends them to its AI company.")).to_be_visible()
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
            expect(panel.get_by_text("Members on other homes don't get this. A ship aboard, or an app a member connected, sends it to its AI company.")).to_be_visible()
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
    """Two real mouse clicks `gap` ms apart on the same spot, as a hurried double click lands. A room opens at its newest,
    so a person scrolls to the button first; the two clicks themselves don't scroll."""
    locator.scroll_into_view_if_needed()
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


def test_a_board_write_made_while_the_next_room_loads_goes_to_the_room_on_screen(browser_peer):
    """M-1: room A's panel is still on screen while room B's board loads, so a click on A's confirm drops A's item, the one
    the person was asked about, and never B's. state.room stays A until B is ready to draw."""
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
    assert open_keys(room_a) == []


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
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
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
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
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


def test_a_marked_rooms_brief_doesnt_say_a_ship_sends_it_on(browser_peer):
    """No ship can be aboard a marked room and a connected app is refused, so that half of the brief's line would
    contradict the mark beside it."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "Kept away", [users["family"]["id"]])
    store.mark_room(users["patient"]["id"], room["id"])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        page.goto(f"{base}/#chats/{room['id']}")
        page.reload()
        brief = page.locator(".room-brief")
        expect(brief).to_contain_text("Members on other homes don't get this.")
        expect(brief).not_to_contain_text("sends it to its AI company")


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
            expect(page.locator(".room-brief")).to_contain_text("Members on other homes don't get this. A ship aboard, or an app a member connected, sends it to its AI company.")
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
    room offers neither "Change participants" nor Remove (both answer 409 there, the moderators plan's ruling 7), and its
    replacement does."""
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
            expect(page.get_by_role("button", name="Remove Sam Family from this room")).to_have_count(0)  # removal answers 409 REPLACED_REMOVE (ruling 7)
            expect(page.get_by_role("button", name="Change participants")).to_have_count(0)
            page.goto(f"{base}/#chats/{replacement['id']}")
            page.reload()
            expect(page.get_by_role("button", name="Change participants")).to_be_visible()


def test_a_replaced_room_takes_no_message_and_keeps_the_unsent_text(browser_peer):
    """fix:send-message-refuses-replaced-room: once another tab's add replaces the room, the page shows no composer,
    only where to post and the unsent text to copy; the station would answer 409 (test_room_board pins it). The room
    that continues it takes the message."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    room = store.create_room(patient, "Care planning", [users["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            draft = "Typed before the add. <b>kept as text</b> " + "x" * 400  # one long word: it must wrap, not widen
            page.get_by_role("textbox", name="Message", exact=True).fill(draft)
            replacement = store.add_participants(patient, room["id"], [users["organizer"]["id"]])  # another tab
            page.reload()
            expect(page.get_by_text("This room was replaced by a newer linked room; post in the room that continues it.")).to_be_visible()
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="Send message")).to_have_count(0)
            expect(page.locator("pre.draft-kept")).to_have_text(draft)
            assert page.locator("pre.draft-kept b").count() == 0  # the kept text is escaped, never markup
            assert page.locator("pre.draft-kept").evaluate("e => e.scrollWidth <= e.parentElement.clientWidth")
            assert [m["body"] for m in store.get_room(patient, room["id"])["messages"]] == []
            page.goto(f"{base}/#chats/{replacement['id']}")
            page.reload()
            page.get_by_role("textbox", name="Message", exact=True).fill("In the room that continues it.")
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_have_text("Message saved")


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


def until(page, ready, what):
    """Polls here, in Python. A page.wait_for_function whose body returns a fetch's promise doesn't wait: a promise is truthy."""
    for _ in range(100):
        if ready():
            return
        page.wait_for_timeout(50)
    raise AssertionError(what)


def a_layer_open_with_unsaved_words(page, base, store, patient, **fields):
    layer = store.create_layer(patient, {"title": "A note", "body": "Released words", **fields})
    store.activate_layer(patient, layer["id"], layer["version"])
    page.goto(f"{base}/#layers/{layer['id']}")
    page.reload()
    body = page.locator("#layer-body")
    expect(body).to_have_value("Released words")
    body.fill("Released words, and more not saved yet")
    return layer, body


def test_turning_off_a_public_link_with_unsaved_words_keeps_the_words_and_the_link_off(browser_peer):
    """The draft narrows with a revoke, so its version moves under an open editor. Their words must survive, and saving them
    must not put the public link back."""
    base, store, patient = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, body = a_layer_open_with_unsaved_words(page, base, store, patient, public=True)
            page.get_by_role("button", name="Turn off public link").click()
            expect(page.get_by_role("button", name="Turn off public link")).to_have_count(0)
            expect(body).to_have_value("Released words, and more not saved yet")
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: "more not saved" in store.get_layer(patient, layer["id"])["body"], "the words were never saved")
            assert store.get_layer(patient, layer["id"])["public"] is False  # saving what was on screen didn't turn it back on


@pytest.mark.parametrize("route", ["person", "space", "public"])
def test_saving_before_the_page_redraws_doesnt_bring_back_who_was_just_removed(browser_peer, route):
    """The page hasn't redrawn, so a Save reads the boxes on screen, and the version the revoke's answer gave. It saves, with no
    false conflict, and without who was just removed."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    space = store.create_space(patient, "Care", "care-circle", [family])
    audience = {"person": {"audience_users": [family]}, "space": {"audience_spaces": [space["id"]]}, "public": {"public": True}}[route]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, _body = a_layer_open_with_unsaved_words(page, base, store, patient, **audience)
            redraw = []
            page.route("**/api/home", lambda held: redraw.append(held))  # the refresh after the revoke: the page stays as it is
            page.get_by_role("button", name=re.compile("^(Stop sharing directly with Sam|Turn off Care|Turn off public link)")).first.click()
            until(page, lambda: redraw, "the refresh never started")
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: "more not saved" in store.get_layer(patient, layer["id"])["body"], "the Save was refused")
            for held in redraw:
                held.continue_()
            page.unroute("**/api/home")
    saved = store.get_layer(patient, layer["id"])
    assert saved["audience_users"] == [] and saved["audience_spaces"] == [] and saved["public"] is False


@pytest.mark.parametrize("off", ["person", "public"])
def test_a_second_tab_saving_its_text_doesnt_undo_a_revoke_made_in_the_first(browser_peer, off):
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    audience = {"audience_users": [family]} if off == "person" else {"public": True}
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, _body = a_layer_open_with_unsaved_words(page, base, store, patient, **audience)
            revoke = {"user_ids": [family]} if off == "person" else {"public": True}
            store.revoke_layer_routes(patient, layer["id"], {"revision": 1, **revoke})  # the first tab
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            page.get_by_role("button", name=re.compile("Save my text")).click()
            until(page, lambda: "more not saved" in store.get_layer(patient, layer["id"])["body"], "the text was never saved")
            expect(page.locator(".notice").first).to_contain_text("Who can see it stays as the latest draft has it")
    saved = store.get_layer(patient, layer["id"])
    assert saved["audience_users"] == [] and saved["public"] is False


def test_a_refresh_doesnt_hide_a_real_conflict_with_another_tab(browser_peer):
    """Any refresh gives the page the newest draft. The words on screen were begun from an older one, so their Save still meets
    the other tab's, and doesn't overwrite it."""
    base, store, patient = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, body = a_layer_open_with_unsaved_words(page, base, store, patient)
            store.save_layer(patient, layer["id"], {"version": store.get_layer(patient, layer["id"])["version"], "body": "The other tab's words"})
            page.evaluate("refresh()")
            page.wait_for_load_state("domcontentloaded")
            until(page, lambda: page.evaluate("state.home.layers.find((item) => item.id === state.selectedLayerId).body") == "The other tab's words", "the refresh never landed")
            expect(body).to_have_value("Released words, and more not saved yet")
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            expect(page.get_by_role("button", name=re.compile("Save my text"))).to_be_visible()
            assert store.get_layer(patient, layer["id"])["body"] == "The other tab's words"
            page.get_by_role("button", name=re.compile("Save my text")).click()  # their choice, and then it's theirs
            until(page, lambda: "more not saved" in store.get_layer(patient, layer["id"])["body"], "the text never saved")


def test_a_file_uploaded_after_a_refresh_doesnt_hide_a_real_conflict(browser_peer):
    base, store, patient = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, _body = a_layer_open_with_unsaved_words(page, base, store, patient)
            store.save_layer(patient, layer["id"], {"version": store.get_layer(patient, layer["id"])["version"], "body": "The other tab's words"})
            page.evaluate("refresh()")
            until(page, lambda: page.evaluate("state.home.layers.find((item) => item.id === state.selectedLayerId).body") == "The other tab's words", "the refresh never landed")
            page.locator("#file-upload").set_input_files({"name": "care-note.txt", "mimeType": "text/plain", "buffer": b"A note."})
            expect(page.get_by_text("care-note.txt uploaded")).to_be_visible()
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            expect(page.get_by_role("button", name=re.compile("Save my text"))).to_be_visible()
            assert store.get_layer(patient, layer["id"])["body"] == "The other tab's words"


def the_page_layer(page, field):
    return page.evaluate(f"state.home.layers.find((item) => item.id === state.selectedLayerId).{field}")


@pytest.mark.parametrize("trigger", ["revoke", "refresh"])
def test_a_first_keystroke_while_a_refresh_is_out_still_meets_the_other_tab(browser_peer, trigger):
    """No edit yet, and another tab saves. A refresh gives the page the newest draft before it redraws the form, so for one round
    trip the form shows the old words under the page's new version. Words typed then were begun from the old version, and their
    Save meets the other tab's (train-1116 reader's S1)."""
    base, store, patient = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    layer = store.create_layer(patient, {"title": "A note", "body": "Released words", "public": True})
    store.activate_layer(patient, layer["id"], layer["version"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#layers/{layer['id']}")
            page.reload()
            body = page.locator("#layer-body")
            expect(body).to_have_value("Released words")
            store.save_layer(patient, layer["id"], {"version": layer["version"], "body": "The other tab's words"})
            revisions = f"**/api/layers/{layer['id']}/revisions"
            held = []
            page.route(revisions, lambda route: held.append(route))  # the refresh's route load: the form isn't redrawn yet
            if trigger == "revoke":
                page.get_by_role("button", name="Turn off public link").click()
            else:
                page.evaluate("() => { refresh(); }")
            until(page, lambda: held, "the refresh's route load never started")
            assert the_page_layer(page, "body") == "The other tab's words"  # the page has the newest draft
            expect(body).to_have_value("Released words")  # the form doesn't, yet
            body.press("End")
            body.press_sequentially(", and mine")
            for route in held:
                route.continue_()
            page.unroute(revisions)
            expect(body).to_have_value("Released words, and mine")
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            expect(page.get_by_role("button", name=re.compile("Save my text"))).to_be_visible()
            assert store.get_layer(patient, layer["id"])["body"] == "The other tab's words"


@pytest.mark.parametrize("route", ["public", "person"])
def test_a_revoke_whose_refresh_fails_doesnt_bring_back_who_was_turned_off(browser_peer, route):
    """The revoke lands and narrows the draft, and the refresh after it fails. The editor is drawn from the page's copy, which must
    have narrowed with its version, so the next Save keeps them off (train-1116 reader's S2)."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    audience = {"public": True} if route == "public" else {"audience_users": [family]}
    layer = store.create_layer(patient, {"title": "A note", "body": "Released words", **audience})
    store.activate_layer(patient, layer["id"], layer["version"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#layers/{layer['id']}")
            page.reload()
            body = page.locator("#layer-body")
            expect(body).to_have_value("Released words")
            page.route("**/api/home", lambda held: held.abort())
            page.get_by_role("button", name="Turn off public link" if route == "public" else re.compile("^Stop sharing directly with Sam")).first.click()
            until(page, lambda: store.get_layer(patient, layer["id"])["version"] == layer["version"] + 1, "the revoke never landed")
            expect(page.locator(".notice").first).to_contain_text("Connection lost")
            page.unroute("**/api/home")
            box = page.locator('#layer-form [name="public"]' if route == "public" else f'#layer-form [name="audience-user"][value="{family}"]')
            expect(box).not_to_be_checked()
            body.fill("Released words, and a typo fixed")
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: "typo" in store.get_layer(patient, layer["id"])["body"], "the Save didn't go through")
    saved = store.get_layer(patient, layer["id"])
    assert saved["public"] is False and saved["audience_users"] == []


@pytest.mark.parametrize("next_signs_in", [False, True])
def test_a_layer_saved_as_the_person_signs_out_says_nothing_to_the_next(browser_peer, next_signs_in):
    """The Save's answer comes after the person signed out: nothing flashes, and no sign-in-again asks the next person
    (train-1116 reader's N2)."""
    base, store, patient = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            watch_reads(page)
            layer, _body = a_layer_open_with_unsaved_words(page, base, store, patient)
            held = held_routes(page, re.compile(rf"/api/layers/{layer['id']}$"))
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            wait_for_hold(page, held)
            signed_out_as_a_read_answers(page, browser_peer, held, next_signs_in=next_signs_in)
            assert not page.evaluate("state.reauth")


@pytest.mark.parametrize("next_signs_in", [False, True])
def test_saving_my_text_as_the_person_signs_out_says_nothing_to_the_next(browser_peer, next_signs_in):
    base, store, patient = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            watch_reads(page)
            layer, _body = a_layer_open_with_unsaved_words(page, base, store, patient)
            store.save_layer(patient, layer["id"], {"version": layer["version"], "body": "The other tab's words"})
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            expect(page.get_by_role("button", name=re.compile("Save my text"))).to_be_visible()
            held = held_routes(page, re.compile(rf"/api/layers/{layer['id']}$"))  # the latest draft's read
            page.get_by_role("button", name=re.compile("Save my text")).click()
            wait_for_hold(page, held)
            signed_out_as_a_read_answers(page, browser_peer, held, next_signs_in=next_signs_in)
    assert store.get_layer(patient, layer["id"])["body"] == "The other tab's words"


def test_two_saves_in_a_row_arent_a_conflict(browser_peer):
    base, store, patient = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, body = a_layer_open_with_unsaved_words(page, base, store, patient)
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: "more not saved" in store.get_layer(patient, layer["id"])["body"], "the first save")
            expect(page.locator(".notice").first).to_have_text("Private draft saved")
            body.fill("And a second go")
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: store.get_layer(patient, layer["id"])["body"] == "And a second go", "the second save")
            expect(page.get_by_role("button", name=re.compile("Save my text"))).to_have_count(0)


def test_words_typed_while_a_save_is_out_save_after_it_with_no_false_conflict(browser_peer):
    base, store, patient = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, body = a_layer_open_with_unsaved_words(page, base, store, patient)
            puts = []
            page.route(f"**/api/layers/{layer['id']}", lambda route: puts.append(route) if route.request.method == "PUT" and not puts else route.continue_())
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: puts, "the save never left")
            body.press("End")
            body.press_sequentially(", still typing")
            puts[0].continue_()
            until(page, lambda: "more not saved" in store.get_layer(patient, layer["id"])["body"], "the first save")
            page.wait_for_timeout(200)
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: "still typing" in store.get_layer(patient, layer["id"])["body"], "the later words never saved")
            expect(page.get_by_role("button", name=re.compile("Save my text"))).to_have_count(0)


@pytest.mark.parametrize("narrows", [True, False])
def test_a_revoke_doesnt_hide_a_real_conflict_with_another_tab(browser_peer, narrows):
    """Another tab saved first. Whether or not the revoke changes the draft, this tab's Save has to meet that, not overwrite it."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, _body = a_layer_open_with_unsaved_words(page, base, store, patient, audience_users=[family])
            fresh = store.get_layer(patient, layer["id"])
            other_tab = {"version": fresh["version"], "body": "The other tab's words"}
            if not narrows:
                other_tab["audience_users"] = []  # the release still names them, and this draft no longer does
            store.save_layer(patient, layer["id"], other_tab)
            redraw = []
            page.route("**/api/home", lambda held: redraw.append(held))  # before the redraw: after it, any refresh picks up the newest version (boarded)
            page.get_by_role("button", name=re.compile("^Stop sharing directly with Sam")).click()
            until(page, lambda: redraw, "the refresh never started")
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            expect(page.get_by_role("button", name=re.compile("Save my text"))).to_be_visible()
            assert store.get_layer(patient, layer["id"])["body"] == "The other tab's words"  # not overwritten
            for held in redraw:
                held.continue_()
            page.unroute("**/api/home")


def test_words_typed_while_a_second_tabs_text_saves_dont_bring_back_who_was_turned_off(browser_peer):
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, body = a_layer_open_with_unsaved_words(page, base, store, patient, audience_users=[family])
            store.revoke_layer_routes(patient, layer["id"], {"revision": 1, "user_ids": [family]})  # the first tab
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            puts = []
            page.route(f"**/api/layers/{layer['id']}", lambda route: puts.append(route) if route.request.method == "PUT" and not puts else route.continue_())
            page.get_by_role("button", name=re.compile("Save my text")).click()
            until(page, lambda: puts, "the save never left")
            body.press("End")
            body.press_sequentially(", still typing")
            puts[0].continue_()
            until(page, lambda: "more not saved" in store.get_layer(patient, layer["id"])["body"], "the text never saved")
            page.unroute(f"**/api/layers/{layer['id']}")
            page.wait_for_timeout(200)
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: "still typing" in store.get_layer(patient, layer["id"])["body"], "the later words never saved")
    assert store.get_layer(patient, layer["id"])["audience_users"] == []


def test_a_revoke_answered_after_opening_another_layer_leaves_its_boxes_alone(browser_peer):
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            other = store.create_layer(patient, {"title": "Beta", "body": "B", "audience_users": [family]})
            layer, _body = a_layer_open_with_unsaved_words(page, base, store, patient, audience_users=[family])
            held = []
            page.route(f"**/api/layers/{layer['id']}/revoke", lambda route: held.append(route))
            page.get_by_role("button", name=re.compile("^Stop sharing directly with Sam")).click()
            until(page, lambda: held, "the revoke never started")
            page.get_by_role("button", name="Beta").click()
            expect(page.get_by_label("Layer title")).to_have_value("Beta")
            redraw = []
            page.route("**/api/home", lambda route: redraw.append(route))
            held[0].continue_()
            until(page, lambda: redraw, "the revoke never answered")
            box = page.locator(f'#layer-form [name="audience-user"][value="{family}"]')
            expect(box).to_be_checked()  # it's Beta's, and Beta's sharing hasn't changed
            for route in redraw:
                route.continue_()
            page.unroute("**/api/home")
    assert family in store.get_layer(patient, other["id"])["audience_users"]


@pytest.mark.parametrize("route", ["person", "space"])
def test_removing_someone_with_unsaved_words_keeps_the_words_and_them_out(browser_peer, route):
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    space = store.create_space(patient, "Care", "care-circle", [family])
    audience = {"audience_users": [family]} if route == "person" else {"audience_spaces": [space["id"]]}
    gone = lambda layer: not (store.get_layer(patient, layer["id"])["audience_users"] or store.get_layer(patient, layer["id"])["audience_spaces"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            layer, body = a_layer_open_with_unsaved_words(page, base, store, patient, **audience)
            page.get_by_role("button", name=re.compile("^(Stop sharing directly with Sam|Turn off Care)")).click()
            until(page, lambda: gone(layer), "the revoke never landed")
            page.wait_for_function("() => !document.querySelector('[data-action=\"revoke-route\"]')")
            expect(body).to_have_value("Released words, and more not saved yet")
            page.get_by_role("button", name=re.compile("^Save")).first.click()
            until(page, lambda: "more not saved" in store.get_layer(patient, layer["id"])["body"], "the words were never saved")
    assert gone(layer)


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
    paired = here.pair(users["organizer"]["id"], browser_peer["remote_card"], code=pairing_code(browser_peer["remote_card"]))  # pairing is an admin's act
    card = Federation(store, endpoint="https://localhost:7435").card(patient)  # this station's identity, an endpoint
    contact = there.pair(casey, card, code=pairing_code(card))
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
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
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


def test_a_long_room_opens_on_the_newest_hundred_and_loads_earlier(browser_peer):
    """Break caught: opening a long room fetches and draws all of it, or earlier messages cannot be reached."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    for i in range(150):
        store.send_message(users["patient"]["id"], room["id"], f"m{i}", f"message {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            messages = page.locator(".messages .message p")
            expect(messages).to_have_count(100)
            expect(messages.first).to_have_text("message 50")
            expect(messages.last).to_have_text("message 149")
            page.get_by_role("button", name="Load earlier messages").click()
            expect(messages).to_have_count(150)
            assert messages.all_inner_texts() == [f"message {i}" for i in range(150)]
            expect(page.get_by_role("button", name="Load earlier messages")).to_have_count(0)


NEWEST_ON_SCREEN = """() => {
    const bar = document.querySelector(".sidebar");  // a phone's bottom bar sits over the page
    const floor = getComputedStyle(bar).position === "fixed" ? bar.getBoundingClientRect().top : innerHeight;
    const uncovered = (node) => {
        const box = node.getBoundingClientRect();
        const covering = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return box.top >= 0 && box.bottom <= floor && node.contains(covering);
    };
    return uncovered([...document.querySelectorAll(".messages .message")].pop()) && uncovered(document.querySelector(".composer"));
}"""


@pytest.mark.parametrize("size", [{"width": 1280, "height": 960}, {"width": 390, "height": 844}], ids=["desktop", "phone"])
@pytest.mark.parametrize("who", ["patient", "family"], ids=["owner", "member"])
def test_a_busy_room_opens_with_its_newest_message_on_screen(browser_peer, size, who):
    """Break caught: a busy room opens at the oldest message shown, about 12 screens above the newest, or with the newest
    under a phone's bottom bar and the box to answer in off the screen (spec D1). An owner has more below the box."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    for i in range(150):
        store.send_message(users["patient"]["id"], room["id"], f"m{i}", f"message {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, who) as (page, _):
            page.set_viewport_size(size)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()  # by reload
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            assert page.evaluate(NEWEST_ON_SCREEN)
            page.goto(f"{base}/#home")  # and by the route entering it from another view
            expect(page.locator(".messages")).to_have_count(0)
            page.evaluate("scrollTo(0, 0)")
            page.goto(f"{base}/#chats/{room['id']}")
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            assert page.evaluate(NEWEST_ON_SCREEN)


def test_at_the_end_of_a_room_the_box_covers_nothing(browser_peer):
    """Break caught: the composer's sticky rule, under .split-view's overflow, lifted it 134 px on a phone, over the newest
    message for good, for a member with nothing below the box to scroll to. It's part of the page now."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    for i in range(150):
        store.send_message(users["patient"]["id"], room["id"], f"m{i}", f"message {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            page.evaluate("scrollTo(0, document.scrollingElement.scrollHeight)")
            assert page.evaluate("""() => {
                const newest = [...document.querySelectorAll(".messages .message")].pop().getBoundingClientRect();
                return newest.bottom <= document.querySelector(".composer").getBoundingClientRect().top;
            }""")


def test_no_words_show_through_the_phones_bar(browser_peer):
    """Break caught: a message under the phone's bottom bar shows through and reads as a muddle."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    store.send_message(users["patient"]["id"], room["id"], "m1", "message 1")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 1")
            assert page.evaluate('getComputedStyle(document.querySelector(".sidebar")).backgroundColor').startswith("rgb(")


NEWEST_READABLE = """() => {
    const box = [...document.querySelectorAll(".messages .message")].pop().getBoundingClientRect();
    const covering = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return box.top >= 0 && box.bottom <= innerHeight && !!covering?.closest(".message");
}"""
PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 960}


def _busy_room(browser_peer, count=150, title="City of AI"):
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], title, [users["family"]["id"]])
    for i in range(count):
        store.send_message(users["patient"]["id"], room["id"], f"{title}-{i}", f"message {i}")
    return room


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_your_own_message_is_on_screen_after_you_send_it(browser_peer, size):
    """Break caught: with the composer stuck, what you send lands behind it, and the page says "Message saved"."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(size)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            for words in ("first of mine", "second of mine"):
                page.get_by_role("textbox", name="Message", exact=True).fill(words)
                page.get_by_role("button", name="Send message").click()
                expect(page.locator(".messages .message p").last).to_have_text(words)
                expect(page.locator("#chat-status")).to_have_text("Message saved")
                assert page.evaluate(NEWEST_ON_SCREEN)


# A room shows its new messages (docs/superpowers/specs/2026-11-04-a-room-shows-new-messages-design.md). The page asks
# every 5 s, give or take a fifth, so a message posted now shows within about 6 s and a failure's wait doubles from there.
NEW_MESSAGE_SHOWS_MS = 9000


ON_SCREEN_UNCOVERED = """(selector) => {
    const bar = document.querySelector(".sidebar");
    const floor = getComputedStyle(bar).position === "fixed" ? bar.getBoundingClientRect().top : innerHeight;
    const node = document.querySelector(selector), box = node.getBoundingClientRect();
    const covering = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return box.top >= 0 && box.bottom <= floor && node.contains(covering);
}"""


def _open_room(page, base, room, size=DESKTOP):
    page.set_viewport_size(size)
    page.goto(f"{base}/#chats/{room['id']}")
    page.reload()
    expect(page.get_by_role("textbox", name="Message", exact=True)).to_be_visible()


def _someone_says(browser_peer, room, words, who="patient"):
    return browser_peer["app"].state.store.send_message(browser_peer["users"][who]["id"], room["id"], f"said-{len(words)}-{time.monotonic_ns()}", words)


def _until(page, condition, timeout_ms=8000):
    """wait_for_function evaluates its text inside the page, and the page's own policy refuses that."""
    deadline = time.monotonic() + timeout_ms / 1000
    while not page.evaluate(condition):
        assert time.monotonic() < deadline, f"never came true: {condition}"
        page.wait_for_timeout(50)


def _hold_first_ask(page, room):
    """Holds the first read of what's new and lets the rest through."""
    held = []
    page.route(f"**/api/chats/{room['id']}?since=*", lambda route: route.continue_() if held else held.append(route))
    return held


def _shown_words(page):
    return page.locator(".messages .message p").all_text_contents()


def _ask_soon(page):
    """Runs the next ask now: most of these tests are about what an answer does, not the wait for it."""
    page.evaluate("() => { clearTimeout(roomAskTimer); roomAskTimer = null; askRoom(); }")  # returns at once: a held answer would hold this too


def test_a_new_message_shows_in_an_open_room_with_nothing_done(browser_peer):
    """Break caught by a real read: an open room made no requests in 45 s, and another member's message showed only after a click."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            box = page.get_by_role("textbox", name="Message", exact=True)
            box.click()
            page.keyboard.type("half a sentence")
            page.evaluate("window.keptBox = document.querySelector('#message-body')")
            _someone_says(browser_peer, room, "arrived by itself")
            expect(page.locator(".messages .message p").last).to_have_text("arrived by itself", timeout=NEW_MESSAGE_SHOWS_MS)
            assert page.evaluate("window.keptBox === document.querySelector('#message-body')")
            assert page.evaluate("document.activeElement === window.keptBox")
            assert page.evaluate("[window.keptBox.selectionStart, window.keptBox.value]") == [15, "half a sentence"]
            _until(page, "announcer.textContent === '1 new message'")


def test_an_answer_with_nothing_new_changes_nothing_on_the_page(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.evaluate("""() => {
                window.keptList = document.querySelector('.messages');
                window.keptSeq = state.room.seq;
                window.changes = 0;
                new MutationObserver((records) => { window.changes += records.length; }).observe(window.keptList, { childList: true, subtree: true });
                const message = document.querySelector('.messages .message p');
                getSelection().selectAllChildren(message);
            }""")
            selected = page.evaluate("getSelection().toString()")
            with page.expect_response(lambda r: f"/api/chats/{room['id']}?since=" in r.url):
                _ask_soon(page)
            page.wait_for_timeout(100)
            assert page.evaluate("window.changes") == 0
            assert page.evaluate("window.keptList === document.querySelector('.messages')")
            assert page.evaluate("getSelection().toString()") == selected and selected


def test_an_arrival_leaves_a_selection_a_dialog_and_an_open_panel_alone(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.evaluate("getSelection().selectAllChildren(document.querySelector('.messages .message p'))")
            selected = page.evaluate("getSelection().toString()")
            page.evaluate("""() => {
                const panel = document.querySelector('.messages').parentElement.appendChild(document.createElement('details'));
                panel.id = 'kept-panel'; panel.open = true; window.keptPanel = panel;
                const dialog = document.querySelector('.messages').parentElement.appendChild(document.createElement('dialog'));
                dialog.id = 'kept-dialog'; dialog.show(); window.keptDialog = dialog;
            }""")
            _someone_says(browser_peer, room, "arrived behind them")
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_have_text("arrived behind them")
            assert page.evaluate("getSelection().toString()") == selected and selected
            assert page.evaluate("window.keptPanel.isConnected && window.keptPanel.open")
            assert page.evaluate("window.keptDialog.isConnected && window.keptDialog.open")


def test_a_hidden_tab_asks_nothing_and_coming_back_asks_at_once(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    set_visibility = """(seen) => {
        Object.defineProperty(document, 'visibilityState', { value: seen, configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
    }"""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.evaluate(set_visibility, "hidden")
            asks = []
            page.on("request", lambda request: asks.append(request.url) if f"/api/chats/{room['id']}?since=" in request.url else None)
            _someone_says(browser_peer, room, "said while hidden")
            page.wait_for_timeout(7000)
            assert asks == [] and page.evaluate("roomAskTimer") is None
            assert "said while hidden" not in _shown_words(page)
            page.evaluate(set_visibility, "visible")
            expect(page.locator(".messages .message p").last).to_have_text("said while hidden", timeout=1500)


def test_leaving_the_room_stops_asking_and_a_late_answer_changes_nothing(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            held = []
            page.route(f"**/api/chats/{room['id']}?since=*", lambda route: held.append(route))
            _someone_says(browser_peer, room, "answered too late")
            _ask_soon(page)
            _until(page, "roomAsking")
            page.goto(f"{base}/#home")
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            assert len(held) == 1
            held[0].continue_()
            _until(page, "!roomAsking")
            assert page.evaluate("roomAskTimer") is None
            assert page.locator(".message").count() == 0


def test_one_ask_at_a_time(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            held = []
            page.route(f"**/api/chats/{room['id']}?since=*", lambda route: held.append(route))
            _ask_soon(page)
            _until(page, "roomAsking")
            _ask_soon(page)
            page.wait_for_timeout(7000)
            assert len(held) == 1
            held[0].continue_()
            page.unroute(f"**/api/chats/{room['id']}?since=*")
            _until(page, "!roomAsking")
            _until(page, "roomAskTimer !== null")


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_at_the_newest_the_page_follows_a_new_message(browser_peer, size):
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room, size)
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            _someone_says(browser_peer, room, "stays in view " * 12)
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_contain_text("stays in view")
            _until(page, NEWEST_ON_SCREEN)
            expect(page.get_by_role("button", name="New messages")).to_be_hidden()
            _someone_says(browser_peer, room, "too long to fit " * 700)
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_contain_text("too long to fit")
            _until(page, "() => { const box = [...document.querySelectorAll('.messages .message')].pop().getBoundingClientRect(); return box.top >= 0 && box.top < innerHeight; }")  # its start


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_an_owner_at_the_newest_is_followed_with_room_management_below_the_box(browser_peer, size):
    """The spec measured from the page's end. A room's management sits below the composer, so an owner never gets within 120 px of it."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            _open_room(page, base, room, size)
            expect(page.locator(".room-management")).to_have_count(1)
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            _someone_says(browser_peer, room, "for the owner", "family")
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_have_text("for the owner")
            _until(page, NEWEST_ON_SCREEN)
            expect(page.get_by_role("button", name="New messages")).to_be_hidden()


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_scrolled_up_to_read_the_page_stays_and_a_button_goes_to_the_newest(browser_peer, size):
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room, size)
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            page.evaluate("window.scrollTo(0, 400)")
            _until(page, "window.scrollY === 400")
            _someone_says(browser_peer, room, "while you read")
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_have_text("while you read")
            assert page.evaluate("window.scrollY") == 400
            button = page.get_by_role("button", name="New messages")
            expect(button).to_be_visible()
            assert page.evaluate(ON_SCREEN_UNCOVERED, ".new-messages")  # to_be_visible says yes at 10,000 px below the window
            box = button.bounding_box()
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)  # click() would scroll to it first
            _until(page, NEWEST_ON_SCREEN)
            expect(button).to_be_hidden()
            assert page.evaluate("document.activeElement === document.querySelector('.messages')")  # not the box: a phone's keyboard
            page.evaluate("window.scrollTo(0, 400)")
            _someone_says(browser_peer, room, "and another")
            _ask_soon(page)
            expect(button).to_be_visible()
            page.evaluate("window.scrollTo(0, document.scrollingElement.scrollHeight)")  # reaching it by hand ends it too
            expect(button).to_be_hidden()


def test_a_failed_ask_waits_longer_says_so_after_three_and_keeps_the_draft(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.get_by_role("textbox", name="Message", exact=True).fill("kept through it all")
            reach = page.locator("#room-reach")
            page.route(f"**/api/chats/{room['id']}?since=*", lambda route: route.abort())
            page.evaluate("""() => {
                window.asked = [];
                const original = window.setTimeout;
                window.setTimeout = (run, wait) => { if (run === askRoom) window.asked.push(wait); return original(run, wait); };
            }""")
            for failed in (1, 2):
                _ask_soon(page)
                _until(page, "!roomAsking")
                expect(reach).to_be_hidden()
            _ask_soon(page)
            _until(page, "!roomAsking")
            expect(reach).to_have_text("Can't reach this home. New messages will show when it's back.")
            for more in range(3):
                _ask_soon(page)
                _until(page, "!roomAsking")
            longest = page.evaluate("window.asked")
            for (wait, base_wait) in zip(longest, (10000, 20000, 40000, 60000, 60000, 60000)):
                assert base_wait * 0.8 <= wait <= base_wait * 1.2
            assert len(longest) == 6
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("kept through it all")
            page.unroute(f"**/api/chats/{room['id']}?since=*")
            _someone_says(browser_peer, room, "back again")
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_have_text("back again")
            expect(reach).to_be_hidden()
            expect(page.get_by_role("textbox", name="Message", exact=True)).to_have_value("kept through it all")
            assert page.evaluate("roomAskFailures") == 0


def test_a_200_that_isnt_a_room_counts_as_a_failed_ask(browser_peer):
    """A sign-in page in the way answers 200. The room on screen stays the room."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.route(f"**/api/chats/{room['id']}?since=*", lambda route: route.fulfill(status=200, content_type="text/html", body="<p>Sign in</p>"))
            _ask_soon(page)
            _until(page, "!roomAsking")
            assert page.evaluate("roomAskFailures") == 1
            assert page.evaluate("state.room.id") == room["id"]
            assert _shown_words(page)[-1] == "message 2"


def test_a_session_that_ended_goes_to_sign_in_and_keeps_the_draft(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.get_by_role("textbox", name="Message", exact=True).fill("kept for after")
            who = page.evaluate("draftKey(state.room.id)")
            page.route(f"**/api/chats/{room['id']}?since=*", lambda route: route.fulfill(status=401, json={"error": "Sign in"}))
            _ask_soon(page)
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
            expect(page.get_by_text("Your session ended.")).to_be_visible()
            assert "kept for after" in page.evaluate("(key) => sessionStorage.getItem(key)", who)
            assert page.evaluate("roomAskTimer") is None


@pytest.mark.parametrize("status", [403, 404])
def test_a_room_that_refuses_stops_asking_and_loads_the_route(browser_peer, status):
    """Removed, or the room is gone."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.get_by_role("textbox", name="Message", exact=True).fill("not touched")
            who = page.evaluate("draftKey(state.room.id)")
            page.route(f"**/api/chats/{room['id']}**", lambda route: route.fulfill(status=status, json={"error": "Not available"}))
            _ask_soon(page)
            expect(page.locator(".message")).to_have_count(0)
            _until(page, "state.room === null && !roomAsking")
            page.wait_for_timeout(200)
            assert page.evaluate("roomAskTimer") is None
            assert "not touched" in page.evaluate("(key) => sessionStorage.getItem(key)", who)


def test_a_message_sorting_earlier_goes_on_the_end_where_a_render_draws_it_too(browser_peer):
    """A step in the station's clock gives a message an older `created`, and paging's seq cursor brings it in anyway.
    Holding it back hid it, and what came after it. It shows at the end until the room is reopened: chat paging's known limit."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            first = page.evaluate("state.room.messages[0]")
            older = {**first, "id": "from-a-peer", "body": "said earlier elsewhere", "created": first["created"]}
            page.route(f"**/api/chats/{room['id']}?since=*", lambda route: route.fulfill(json={
                **page_room(browser_peer, room), "messages": [older], "seq": 999999, "more": False, "paged": True,
                "total": 4, "first_position": 0}))
            _ask_soon(page)
            _until(page, "state.room.seq === 999999")
            assert _shown_words(page)[-1] == "said earlier elsewhere"
            page.evaluate("render()")
            assert _shown_words(page)[-1] == "said earlier elsewhere"
            assert _shown_words(page).count("said earlier elsewhere") == 1


def page_room(browser_peer, room):
    """The fields a room's answer carries, for a stub: only its messages differ here."""
    return {"id": room["id"], "title": room["title"], "owner_id": room["owner_id"], "member_ids": room["member_ids"]}


def test_your_own_send_isnt_shown_twice_when_an_ask_carries_it_too(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            answers = []
            page.route(f"**/api/chats/{room['id']}/messages", lambda route: answers.append(route) if route.request.method == "POST" else route.fallback())
            page.get_by_role("textbox", name="Message", exact=True).fill("only once")
            page.get_by_role("button", name="Send message").click()
            _until(page, "document.querySelector('#chat-status').textContent === 'Sending…'")
            assert len(answers) == 1
            answer = answers[0].fetch()  # the home has it, and the page hasn't heard
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_have_text("only once")
            answers[0].fulfill(response=answer)
            expect(page.locator("#chat-status")).to_have_text("Message saved")
            assert _shown_words(page).count("only once") == 1
            _ask_soon(page)
            _until(page, "!roomAsking")
            assert _shown_words(page).count("only once") == 1


def test_after_an_arrival_a_render_keeps_it_and_the_next_ask_doesnt_fetch_it_again(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            _someone_says(browser_peer, room, "kept by a render")
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_have_text("kept by a render")
            page.evaluate("render()")
            expect(page.locator(".messages .message p").last).to_have_text("kept by a render")
            with page.expect_response(lambda r: f"/api/chats/{room['id']}?since=" in r.url) as asked:
                _ask_soon(page)
            assert asked.value.json()["messages"] == []
            assert _shown_words(page).count("kept by a render") == 1


def test_an_answer_for_a_room_no_longer_on_screen_appends_nothing(browser_peer):
    """While the next room loads, state.room can already be that room, with the last room's list still drawn."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.evaluate("document.querySelector('.messages').dataset.room = 'another-room'")
            _someone_says(browser_peer, room, "not for this list")
            _ask_soon(page)
            _until(page, "state.room.messages.some((message) => message.body === 'not for this list')")
            assert "not for this list" not in _shown_words(page)


@pytest.mark.parametrize("other", ["send", "earlier", "board"])
def test_an_ask_overlapping_another_read_shows_every_message_once(browser_peer, other):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 150)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            held = _hold_first_ask(page, room)
            _someone_says(browser_peer, room, "one")
            _ask_soon(page)
            _until(page, "roomAsking")
            if other == "send":
                page.get_by_role("textbox", name="Message", exact=True).fill("two")
                page.get_by_role("button", name="Send message").click()
                expect(page.locator("#chat-status")).to_have_text("Message saved")
            elif other == "earlier":
                page.get_by_role("button", name="Load earlier messages").click()
                _until(page, "state.room.first_position === 0")
            else:
                page.evaluate("refreshRoom(state.room).then((answer) => { state.room = answer; render(); })")
                _until(page, "state.room.messages.some((message) => message.body === 'one')")
            held[0].continue_()
            _until(page, "!roomAsking")
            _ask_soon(page)
            _until(page, "!roomAsking")
            words = _shown_words(page)
            expected = {"one", "message 149"} | ({"two"} if other == "send" else set())
            for said in expected:
                assert words.count(said) == 1, said
            ids = page.evaluate("state.room.messages.map((message) => message.id)")
            assert len(ids) == len(set(ids))


def test_a_poll_held_past_a_newer_refresh_changes_nothing_and_the_order_stays_right(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            held = _hold_first_ask(page, room)
            _someone_says(browser_peer, room, "first")
            _ask_soon(page)
            _until(page, "roomAsking")
            answer = held[0].fetch()
            _someone_says(browser_peer, room, "second")
            page.evaluate("refreshRoom(state.room).then((fresh) => { state.room = fresh; render(); })")
            _until(page, "state.room.messages.some((message) => message.body === 'second')")
            seq = page.evaluate("state.room.seq")
            held[0].fulfill(response=answer)
            _until(page, "!roomAsking")
            assert page.evaluate("state.room.seq") == seq
            assert _shown_words(page)[-2:] == ["first", "second"]


def test_a_poll_doesnt_start_while_another_refresh_is_on_its_way(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            held = _hold_first_ask(page, room)
            page.evaluate("() => { window.other = refreshRoom(state.room); }")  # returns at once: the held answer would hold this too
            _until(page, "refreshesRunning === 1")
            _ask_soon(page)
            page.wait_for_timeout(100)
            assert page.evaluate("roomAsking") is False
            assert len(held) == 1
            assert page.evaluate("roomAskTimer") is not None
            held[0].continue_()
            _until(page, "refreshesRunning === 0")


def test_your_reply_in_a_received_room_isnt_shown_twice_when_the_host_has_it(browser_peer):
    """A queued reply has a local id, and the host's copy has its own. A received room's answer is the whole room."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            me = page.evaluate("state.me.id")
            queued = page.evaluate("""(me) => {
                const shown = state.room.messages[0];
                const queued = { ...shown, id: 'local-copy', author_id: me, body: 'my reply' };
                state.room = { ...state.room, paged: false, messages: [...state.room.messages, queued] };
                render();
                return queued;
            }""", me)
            assert _shown_words(page).count("my reply") == 1
            whole = page.evaluate("state.room.messages.filter((message) => message.id !== 'local-copy')")
            answer = {**page_room(browser_peer, room), "messages": [*whole, {**queued, "id": "hosts-copy"},
                      {**queued, "id": "host-said", "author_id": whole[0]["author_id"], "body": "the host answers"}]}
            page.route(f"**/api/chats/{room['id']}", lambda route: route.fulfill(json=answer))
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_have_text("the host answers")
            assert _shown_words(page).count("my reply") == 1
            _until(page, "announcer.textContent === '1 new message'")  # your own words coming back aren't news


def test_a_room_read_whole_at_each_ask_waits_longer_as_it_grows(browser_peer):
    """Run on the Pi: a received room of 5,000 messages is 1.9 MB an ask, which at 5 s is 11 GB in 8 hours from one tab."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            assert page.evaluate("roomAskWait(state.room)") == 5000
            assert page.evaluate("roomAskWait({ paged: false, messages: [] })") == 30000
            assert page.evaluate("roomAskWait({ paged: false, messages: new Array(1000) })") == 30000
            assert page.evaluate("roomAskWait({ paged: false, messages: new Array(5000) })") == 150000
            assert page.evaluate("roomAskFailures = 3; roomAskWait({ paged: false, messages: [] })") == 60000
            assert page.evaluate("roomAskFailures = 3; roomAskWait({ paged: false, messages: new Array(5000) })") == 150000
            page.evaluate("roomAskFailures = 0")


def test_an_arrival_while_sends_sync_waits_stays_on_screen(browser_peer):
    """Send's own refresh has returned, so an ask can run, and Send used to assign its older answer after sync."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            held = []
            page.route("**/api/sync", lambda route: route.continue_() if held else held.append(route))
            page.get_by_role("textbox", name="Message", exact=True).fill("mine")
            page.get_by_role("button", name="Send message").click()
            _until(page, "state.room.messages.some((message) => message.body === 'mine') && refreshesRunning === 0 && document.querySelector('#chat-status').textContent.startsWith('Message saved.')")
            assert len(held) == 1
            _someone_says(browser_peer, room, "while sync waits")
            _ask_soon(page)
            expect(page.locator(".messages .message p").last).to_have_text("while sync waits")
            held[0].continue_()
            expect(page.locator("#chat-status")).to_have_text("Message saved")
            assert _shown_words(page)[-2:] == ["mine", "while sync waits"]
            assert page.evaluate("state.room.messages.at(-1).body") == "while sync waits"


def test_a_sync_that_fails_first_still_draws_what_sends_refresh_brought(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.evaluate("() => { clearTimeout(roomAskTimer); roomAskTimer = null; }")
            held = _hold_first_ask(page, room)
            page.route("**/api/sync", lambda route: route.abort())
            _someone_says(browser_peer, room, "in send's refresh")
            page.get_by_role("textbox", name="Message", exact=True).fill("mine")
            page.get_by_role("button", name="Send message").click()
            _until(page, "refreshesRunning === 1")
            page.wait_for_timeout(200)  # the sync has failed by now
            assert len(held) == 1
            held[0].continue_()
            expect(page.locator(".notice")).to_contain_text("Message saved. Latest room status is unavailable.")
            assert "in send's refresh" in _shown_words(page) and "mine" in _shown_words(page)


def test_a_long_wait_for_a_big_received_room_doesnt_carry_into_the_next_room(browser_peer):
    """A reader ran it: 30.9 s for a message in the room switched to, and by the code up to 180 s after a 5,000-message room."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    other = _busy_room(browser_peer, 3, title="Room B")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.evaluate("""() => {
                state.room = { ...state.room, paged: false };
                clearTimeout(roomAskTimer); roomAskTimer = null;
                roomAskFailures = 2;
                keepAskingRoom();
            }""")
            page.locator(".split-list .item", has_text="Room B").click()
            expect(page.get_by_role("heading", name="Room B")).to_be_visible()
            assert page.evaluate("roomAskFailures") == 0
            _someone_says(browser_peer, other, "soon after the switch")
            expect(page.locator(".messages .message p").last).to_have_text("soon after the switch", timeout=NEW_MESSAGE_SHOWS_MS)


def test_an_ask_that_hangs_gives_up_and_counts_as_a_failure(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.evaluate("""() => {
                window.gaveUpAfter = [];
                AbortSignal.timeout = (after) => { window.gaveUpAfter.push(after); return AbortSignal.abort(); };
            }""")
            _ask_soon(page)
            _until(page, "!roomAsking && roomAskFailures === 1")
            assert page.evaluate("window.gaveUpAfter") == [30000]
            assert page.evaluate("roomAskTimer") is not None


def test_being_removed_says_so_shows_your_words_and_takes_the_room_off_the_list(browser_peer):
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.get_by_role("textbox", name="Message", exact=True).fill("half a thought <b>kept</b>")
            store.remove_participant(users["patient"]["id"], room["id"], users["family"]["id"])
            _ask_soon(page)
            notice = page.locator(".split-detail .notice")
            expect(notice).to_contain_text("You can't open that room any more.")
            expect(notice.locator("pre.draft-kept")).to_have_text("half a thought <b>kept</b>")
            expect(page.locator(".split-list .item", has_text="City of AI")).to_have_count(0)
            assert page.evaluate("state.room") is None and page.evaluate("roomAskTimer") is None
            page.goto(f"{base}/#home")
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            page.goto(f"{base}/#chats")
            expect(page.locator(".split-detail .notice")).to_have_count(0)


def test_a_refused_ask_after_the_account_changed_goes_to_sign_in_and_leaves_nothing_on_screen(browser_peer):
    """Another tab signed in as someone else: the ask is refused, and the first person's room mustn't stay for them."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.get_by_role("textbox", name="Message", exact=True).fill("the first person's draft")
            page.route(f"**/api/chats/{room['id']}?since=*", lambda route: route.fulfill(status=404, json={"error": "Not available"}))
            page.evaluate("state.me = { ...state.me, id: 'the-first-person' }")  # the home now answers as someone else
            _ask_soon(page)
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
            assert page.evaluate("state.room") is None and page.evaluate("state.me") is None
            expect(page.locator(".message")).to_have_count(0)
            expect(page.get_by_text("the first person's draft")).to_have_count(0)


def test_removed_with_a_failed_send_says_only_what_is_true(browser_peer):
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.get_by_role("textbox", name="Message", exact=True).fill("never reached them")
            store.remove_participant(users["patient"]["id"], room["id"], users["family"]["id"])
            page.get_by_role("button", name="Send message").click()
            expect(page.locator("#chat-status")).to_contain_text("Your message is still here")
            _ask_soon(page)
            notice = page.locator(".split-detail .notice")
            expect(notice).to_contain_text("You can't open that room any more.")
            expect(notice.locator("pre.draft-kept")).to_have_text("never reached them")
            expect(page.locator(".notice.error")).to_have_count(0)  # not "still in the box", which they can't open
            assert page.evaluate("state.unsentIn") is None


def test_a_send_whose_sync_fails_says_nothing_to_the_next_account(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            held = []
            page.route("**/api/sync", lambda route: held.append(route))
            page.get_by_role("textbox", name="Message", exact=True).fill("mine")
            page.get_by_role("button", name="Send message").click()
            _until(page, "state.room.messages.some((message) => message.body === 'mine') && refreshesRunning === 0")
            page.evaluate("state.me = { ...state.me, id: 'the-next-account' }")
            held[0].abort()
            page.wait_for_timeout(300)
            assert page.evaluate("state.flash") is None


def test_a_leftover_timer_asks_nothing_for_the_next_person_signing_in(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            asks = []
            page.on("request", lambda request: asks.append(request.url) if "?since=" in request.url else None)
            page.evaluate("""() => {
                const me = state.me, room = state.room;
                clearTimeout(roomAskTimer); roomAskTimer = null;
                showLogin();
                if (state.room !== null) throw new Error('the room outlived the person');
                state.me = me; state.room = room;   // the moment during a sign-in with a person and no home
                askRoom();
                state.me = null; state.room = null;
            }""")
            page.wait_for_timeout(200)
            assert asks == []
            expect(page.locator(".notice.error")).to_have_count(0)


def test_an_ask_held_across_opening_the_room_leaves_load_earlier_working(browser_peer):
    """first_position went to 0 with 101 of 151 messages held, and the button did nothing."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 150)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            page.get_by_role("button", name="Load earlier messages").click()
            _until(page, "state.room.first_position === 0")
            held = _hold_first_ask(page, room)
            _someone_says(browser_peer, room, "one more")
            _ask_soon(page)
            _until(page, "roomAsking")
            page.locator(".split-list .item", has_text="City of AI").click()
            _until(page, "state.room.first_position === 51")
            held[0].continue_()
            _until(page, "!roomAsking")
            _until(page, "state.room.first_position + state.room.messages.length === state.room.total")
            page.get_by_role("button", name="Load earlier messages").click()
            _until(page, "state.room.first_position === 0 && state.room.messages.length === 151")


def test_a_replaced_room_can_say_it_cant_reach_this_home(browser_peer):
    base, room = browser_peer["base_url"], _busy_room(browser_peer, 3)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            _open_room(page, base, room)
            page.evaluate("() => { state.home.chats = [...state.home.chats, { id: 'newer', title: 'Newer', linked_room_id: state.room.id }]; state.roomUnreachable = true; render(); }")
            expect(page.locator(".composer-replaced #room-reach")).to_be_visible()


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_clicking_a_room_opens_it_at_its_newest(browser_peer, size):
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(size)
            page.goto(f"{base}/#chats")
            page.locator(".split-list .item", has_text="City of AI").click()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            assert page.evaluate(NEWEST_ON_SCREEN)


def test_signing_in_again_opens_the_room_at_its_newest(browser_peer):
    """Break caught: the page remembers the room drawn before the sign-out, so it opens at the top."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            page.get_by_role("button", name="Account and sign out").click()
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.get_by_role("heading", name="Sign in to this home")).to_be_visible()
            page.goto(f"{base}/#chats/{room['id']}")
            page.get_by_label("Username", exact=True).fill("family")
            page.get_by_label("Password", exact=True).fill(browser_peer["password"])
            page.get_by_role("button", name="Sign in").click()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            assert page.evaluate(NEWEST_ON_SCREEN)


def test_the_rooms_stay_reachable_from_the_end_of_a_long_room(browser_peer):
    """Break caught: opening at the newest leaves the room list 10,000 px up. On a desktop it stays beside the room; on a
    phone, where it stacks above, the Chats link goes back to it."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    for i in range(26):  # a phone's list is long: the Chats link must land at its start, not its end
        store.create_room(users["patient"]["id"], f"Room {i}", [users["family"]["id"]])
    FIRST_ROOM = """() => { const box = document.querySelector(".split-list .item").getBoundingClientRect();
        const covering = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return box.top >= 0 && box.bottom <= innerHeight && !!covering?.closest(".item"); }"""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(DESKTOP)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            assert page.evaluate(FIRST_ROOM)
            page.set_viewport_size(PHONE)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            assert not page.evaluate(FIRST_ROOM)
            page.get_by_role("link", name="Chats").click()
            expect(page.locator(".messages")).to_have_count(0)
            assert page.evaluate(FIRST_ROOM)
            assert page.evaluate('(() => { const l = document.querySelector(".split-list .item-list"); return l.scrollHeight <= l.clientHeight; })()')


@pytest.mark.parametrize("size", [{"width": 390, "height": 500}, {"width": 667, "height": 375}], ids=["short", "landscape"])
def test_on_a_short_screen_the_newest_can_be_read(browser_peer, size):
    """Where the box and the newest can't both fit, the newest wins: the words are what opened the room."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(size)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            assert page.evaluate(NEWEST_READABLE)


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_a_message_too_long_to_fit_opens_at_its_start(browser_peer, size):
    """Break caught: a long newest message shows neither its start nor its end, or only its end."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, count=30)
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    store.send_message(users["patient"]["id"], room["id"], "long", "A long one. " + "word " * 1200)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(size)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_contain_text("A long one.")
            top = page.evaluate('[...document.querySelectorAll(".messages .message")].pop().getBoundingClientRect().top')
            assert 0 <= top <= 100


def test_an_empty_room_on_a_phone_shows_its_box(browser_peer):
    """Break caught: with many rooms above it, clicking an empty room changes nothing a person can see."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    for i in range(30):
        store.create_room(users["patient"]["id"], f"Room {i}", [users["family"]["id"]])
    store.create_room(users["patient"]["id"], "An empty one", [users["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(PHONE)
            page.goto(f"{base}/#chats")
            page.locator(".split-list .item", has_text="An empty one").click()
            expect(page.get_by_role("heading", name="An empty one")).to_be_attached()
            expect(page.locator("#composer-to")).to_have_text("To An empty one")  # the page draws twice: measure in one step
            page.wait_for_function("""() => {
                const box = document.querySelector(".composer").getBoundingClientRect();
                return box.top >= 0 && box.bottom <= document.querySelector(".sidebar").getBoundingClientRect().top;
            }""")


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_the_box_and_the_list_say_which_room_this_is(browser_peer, size):
    """Break caught: opening at the newest puts the title 10,000 px up, and nothing else names the room, so a person can
    post in the wrong one."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer, title="Plans <b>for</b> May")
    other = browser_peer["app"].state.store.create_room(browser_peer["users"]["patient"]["id"], "Another", [browser_peer["users"]["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(size)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            expect(page.locator("#composer-to")).to_have_text("To Plans <b>for</b> May")
            expect(page.locator("#composer-to")).to_be_in_viewport(ratio=1)
            assert page.get_by_role("textbox", name="Message", exact=True).get_attribute("aria-describedby") == "composer-to"
            current = page.locator('.split-list .item[aria-current="true"]')
            expect(current).to_have_count(1)
            expect(current).to_contain_text("Plans <b>for</b> May")
            expect(current).to_have_class(re.compile(r"\bselected\b"))
            page.goto(f"{base}/#chats/{other['id']}")
            expect(page.locator("#composer-to")).to_have_text("To Another")
            expect(page.locator('.split-list .item[aria-current="true"]')).to_contain_text("Another")


def test_the_room_list_keeps_its_place_through_a_render(browser_peer):
    """Break caught: the desktop list scrolls by itself, and each render reset it, so the room a person clicked jumped away."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    for i in range(40):
        store.create_room(users["patient"]["id"], f"Room {i}", [users["family"]["id"]])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(DESKTOP)
            page.goto(f"{base}/#chats")
            expect(page.locator(".split-list .item").first).to_be_visible()
            assert page.evaluate('(() => { const l = document.querySelector(".split-list .item-list"); l.scrollTop = 600; return l.scrollTop; })()') == 600
            page.evaluate("render()")
            assert page.evaluate('document.querySelector(".split-list .item-list").scrollTop') == 600


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_a_link_out_of_a_room_starts_the_next_view_at_its_top(browser_peer, size):
    """Break caught: a long room's scroll carried over, so Home opened at its bottom."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(size)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            assert page.evaluate("scrollY") > 1000
            page.get_by_role("link", name="Home", exact=True).click()
            expect(page.locator(".messages")).to_have_count(0)
            assert page.evaluate("scrollY") == 0


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_back_and_forward_are_left_to_the_browser(browser_peer, size):
    """Break caught: resetting the page on leaving a room lost a person's place on Back, and a scroll memory of our own
    landed them at the end of the view on Forward then Back."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(size)
            page.goto(f"{base}/#home")
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            page.evaluate("scrollTo(0, 400)")
            page.goto(f"{base}/#chats/{room['id']}")
            expect(page.locator("#composer-to")).to_have_text("To City of AI")
            page.go_back()
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            page.wait_for_timeout(100)
            assert page.evaluate("scrollY") == 400
            page.evaluate("scrollTo(0, 200)")
            page.go_forward()
            expect(page.locator("#composer-to")).to_have_text("To City of AI")
            page.go_back()
            expect(page.get_by_role("heading", name="Your home", exact=True)).to_be_visible()
            page.wait_for_timeout(100)
            assert page.evaluate("scrollY") == 200


def test_a_send_that_ends_after_you_moved_on_does_not_pull_you_back(browser_peer):
    """Break caught: a slow Send ends while the person is reading another room, and that room jumps to its newest."""
    base, room = browser_peer["base_url"], _busy_room(browser_peer)
    other = _busy_room(browser_peer, title="Another room")
    held = []
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.set_viewport_size(DESKTOP)
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator("#composer-to")).to_have_text("To City of AI")
            page.route("**/api/chats/*/messages", lambda route: held.append(route) if route.request.method == "POST" else route.continue_())
            page.get_by_role("textbox", name="Message", exact=True).fill("sent on the way out")
            page.get_by_role("button", name="Send message").click()
            page.goto(f"{base}/#chats/{other['id']}")
            expect(page.locator("#composer-to")).to_have_text("To Another room")
            page.evaluate("scrollTo(0, 40)")
            assert held
            with page.expect_response("**/api/sync"):
                held[0].continue_()
            page.wait_for_timeout(300)
            assert page.evaluate("scrollY") == 40


def test_a_later_render_of_a_room_leaves_the_reader_where_they_are(browser_peer):
    """Break caught: every render jumps a person reading older messages back to the newest (spec D1)."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    for i in range(150):
        store.send_message(users["patient"]["id"], room["id"], f"m{i}", f"message {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("message 149")
            page.evaluate("scrollTo(0, 500)")
            page.evaluate("render()")
            assert page.evaluate("scrollY") == 500
            page.evaluate("scrollTo(0, 0)")
            more = page.get_by_role("button", name="Load earlier messages")
            more.scroll_into_view_if_needed()
            line = page.locator(".messages .message", has_text="message 50").first
            before = line.bounding_box()["y"]
            more.click()
            expect(page.locator(".messages .message p")).to_have_count(150)
            assert abs(line.bounding_box()["y"] - before) <= 2  # Load earlier keeps the reader's line


def test_moving_to_another_room_opens_that_room_at_its_newest(browser_peer):
    """Break caught: the page only notices leaving the view, so a longer room opens where a shorter one's end was."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    first = store.create_room(users["patient"]["id"], "First room", [users["family"]["id"]])
    second = store.create_room(users["patient"]["id"], "Second room", [users["family"]["id"]])
    for room, count in ((first, 20), (second, 120)):
        for i in range(count):
            store.send_message(users["patient"]["id"], room["id"], f"{room['id']}-{i}", f"{room['title']} {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "family") as (page, _):
            page.goto(f"{base}/#chats/{first['id']}")
            page.reload()
            expect(page.locator(".messages .message p").last).to_have_text("First room 19")
            page.locator(".split-list .item", has_text="Second room").click()  # a real click, from the end of the first
            expect(page.locator(".messages .message p").last).to_have_text("Second room 119")
            assert page.evaluate(NEWEST_ON_SCREEN)


def test_a_refresh_appends_a_new_message_once(browser_peer):
    """Break caught: a refresh after a brief save drops the messages shown, or shows a new one twice."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    for i in range(3):
        store.send_message(users["patient"]["id"], room["id"], f"m{i}", f"message {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            expect(page.locator(".messages .message p")).to_have_count(3)
            store.send_message(users["family"]["id"], room["id"], "late", "A word that arrived while you read.")
            panel = page.locator(".room-brief")
            panel.get_by_role("button", name="Edit brief").click()
            panel.get_by_label("Edit brief").fill("A brief.")
            panel.get_by_role("button", name="Save brief").click()
            expect(page.locator(".notice", has_text="Room brief saved.")).to_be_visible()
            shown = page.locator(".messages .message p").all_inner_texts()  # the brief's station notice joins them
            assert shown[:3] == ["message 0", "message 1", "message 2"]
            assert shown.count("A word that arrived while you read.") == 1


def test_a_sent_message_takes_its_place_among_those_that_arrived_first(browser_peer):
    """Break caught: after a send, a message that arrived while the reader typed is shown below the sent one until reload."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    for i in range(3):
        store.send_message(users["patient"]["id"], room["id"], f"m{i}", f"message {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            messages = page.locator(".messages .message p")
            expect(messages).to_have_count(3)
            store.send_message(users["family"]["id"], room["id"], "late", "A question while you typed.")
            page.get_by_role("textbox", name="Message", exact=True).fill("My answer to it.")
            page.get_by_role("button", name="Send message").click()
            expect(messages).to_have_count(5)
            expect(page.locator("#chat-status")).to_have_text("Message saved")
            shown = messages.all_inner_texts()
            page.reload()
            expect(messages).to_have_count(5)
            assert shown == messages.all_inner_texts()


def test_a_generic_refresh_keeps_the_earlier_messages_the_reader_loaded(browser_peer):
    """Break caught: a refresh reloads the newest hundred and drops the earlier messages the reader asked for."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    for i in range(150):
        store.send_message(users["patient"]["id"], room["id"], f"m{i}", f"message {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            messages = page.locator(".messages .message p")
            expect(messages).to_have_count(100)
            page.get_by_role("button", name="Load earlier messages").click()
            expect(messages).to_have_count(150)
            store.send_message(users["family"]["id"], room["id"], "late", "A word that arrived.")
            page.evaluate("refresh()")
            expect(messages).to_have_count(151)
            assert messages.all_inner_texts() == [f"message {i}" for i in range(150)] + ["A word that arrived."]
            expect(page.get_by_role("button", name="Load earlier messages")).to_have_count(0)


def test_a_remote_room_still_opens(browser_peer):
    """Break caught: a paired peer's room, which has no pages, fails to open or loses its messages."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    peer, patient = "b" * 64, users["patient"]["id"]
    payload = {
        "title": "Remote room", "owner_id": f"{peer}:casey", "created": 1000.0, "last_activity": 1002.0,
        "members": [{"peer": peer, "id": "casey"}], "member_ids": [f"{peer}:casey", patient],
        "messages": [
            {"id": f"r{i}", "room_id": "remote-1", "author_id": f"{peer}:casey", "client_message_id": f"c{i}",
             "body": f"remote word {i}", "epoch": 1, "created": 1000.0 + i}
            for i in range(3)
        ],
    }
    with store.transaction() as db:
        db.execute("INSERT INTO peers VALUES(?,?,1)", (peer, "{}"))
        db.execute("INSERT INTO inbox VALUES(?,?,?,?,?,?,?)", (peer, "remote-1", "room", patient, 1, "casey", json.dumps(payload)))
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{quote(peer + ':remote-1', safe='')}")
            page.reload()
            expect(page.get_by_role("heading", name="Remote room")).to_be_visible()
            assert page.locator(".messages .message p").all_inner_texts() == [f"remote word {i}" for i in range(3)]
            expect(page.get_by_role("button", name="Load earlier messages")).to_have_count(0)


def test_load_earlier_skips_nothing_after_a_message_arrives_above_the_window(browser_peer):
    """Section 2 review M2: a since refresh brings a peer row whose older `created` puts it above the shown window.
    The window then starts one lower than first_position says, and Load earlier used to skip that one message."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    room = store.create_room(users["patient"]["id"], "City of AI", [users["family"]["id"]])
    for i in range(150):
        store.send_message(users["patient"]["id"], room["id"], f"m{i}", f"message {i}")
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            messages = page.locator(".messages .message p")
            expect(messages).to_have_count(100)
            with store.transaction() as db:
                created = db.execute("SELECT created FROM messages WHERE client_message_id='m10'").fetchone()[0]
                db.execute("INSERT INTO peer_messages VALUES(?,?,?,?,?,?,?)",
                           ("late-peer", room["id"], f"{'a' * 64}:remote", "late", "A relayed word from long ago.", 1, created + 1e-6))
                store.emit(db, "chat.message", room["id"], 1, {"message_id": "late-peer", "author_id": f"{'a' * 64}:remote"})
            page.evaluate("refresh()")
            expect(messages).to_have_count(101)  # it shows at the end until the room is reopened (a spec Known limit)
            page.get_by_role("button", name="Load earlier messages").click()
            expect(messages).to_have_count(151)
            assert messages.all_inner_texts() == [f"message {i}" for i in range(150)] + ["A relayed word from long ago."]
            expect(page.get_by_role("button", name="Load earlier messages")).to_have_count(0)


# Federation pull, plan Task 9 (spec §8, plan RG and nits 14 and 20): what the listener's page says about pull peers,
# deliveries that wait, retry or were refused, and how delivery to each peer is going.

def test_a_pull_peer_reads_fetches_from_us_and_its_rows_wait_for_pull(browser_peer, tmp_path):
    import time
    app = browser_peer['app']
    store, fed = app.state.store, app.state.federation
    mac = Store(tmp_path / 'mac')
    mo = mac.create_user('mo', 'Mo Mac', 'long-mac-password', is_admin=True)['id']
    mac.claim_federation_mode('pull')
    card = Federation(mac, endpoint=None).card(mo)
    assert card['endpoint'] is None and card['delivery'] == 'pull'
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, 'organizer') as (page, _):
            page.get_by_role('link', name='Connections', exact=True).click()
            page.get_by_label('Peer card').fill(json.dumps(card))
            page.get_by_role('button', name='Preview peer card').click()
            expect(page.get_by_text('Fetches from us: it has no address', exact=False)).to_be_visible()
            page.get_by_label('Type the code shown on the other machine').fill(show_code(pairing_code(card)))
            page.get_by_role('button', name='Pair this peer').click()
            expect(page.get_by_text('Fetches from us · no pull yet')).to_be_visible()
            expect(page.locator('.card', has_text='Mo Mac').get_by_text('Endpoint:', exact=False)).to_have_count(0)
            page.get_by_role('link', name='My sharing layers').click()
            open_new_layer(page)
            page.get_by_label('Layer title').fill('For the Mac')
            page.get_by_role('checkbox', name='Mo Mac').check()
            page.get_by_role('button', name='Save private draft').click()
            expect(page.get_by_text('Saved version 2', exact=True)).to_be_visible()
            page.get_by_role('button', name='Preview audience').click()
            page.get_by_role('button', name='Turn on version 2').click()
            page.get_by_role('link', name='Connections', exact=True).click()
            expect(page.locator('.item', has_text='For the Mac → Mo Mac').get_by_text('Share update · Waiting for pull')).to_be_visible()
            # RG's N5: a pull peer's failed row (a walk's local fault) is still its next pull's: no "Retrying", no Retry.
            # Rendered directly, since the page shows the same before and after a refresh, so a wait couldn't tell them apart.
            failed = {'status': 'failed', 'peer_mode': 'pull', 'action': 'layer.release', 'id': 'k', 'resource_id': 'r',
                      'peer_id': 'p', 'revision': 2, 'attempts': 1, 'resource_title': 'For the Mac', 'contact_name': 'Mo Mac',
                      'next_attempt': None}
            html = page.evaluate('row => deliveryCard(row)', failed)
            assert 'Share update · Waiting for pull' in html and 'retry-delivery' not in html, html
            with store.transaction() as db:  # what a served pull records (federation.py's _serve_pull)
                db.execute('UPDATE peer_delivery SET last_pull=? WHERE mode=?', (time.time(), 'pull'))
            page.get_by_role('button', name='Check delivery now').click()  # never dials here: no --sync, no pull peer to dial
            page.get_by_role('link', name='My sharing layers').click()
            page.get_by_role('link', name='Connections', exact=True).click()
            expect(page.get_by_text('Fetches from us · last pull', exact=False)).to_be_visible()


def test_delivery_labels_retrying_not_delivered_and_too_large_to_pull(browser_peer):
    import time
    app = browser_peer['app']
    store, fed = app.state.store, app.state.federation
    owner = browser_peer['users']['organizer']['id']
    fed.endpoint = 'https://local.example:7443'
    remote_card = browser_peer['remote_card']
    contact = fed.pair(owner, remote_card, code=pairing_code(remote_card))['id']
    layers = {}
    for title in ('Retried update', 'Refused update', 'Oversized update'):
        layer = store.create_layer(owner, {'title': title, 'audience_users': [contact]})
        store.activate_layer(owner, layer['id'], 1)
        layers[title] = layer['id']
    fed.collect()
    now = time.time()
    with store.transaction() as db:  # the outcomes test_federation_outcomes drives for real, set directly here
        db.execute("UPDATE outbox SET status='failed' WHERE resource_id=?", (layers['Retried update'],))
        db.execute("UPDATE outbox SET status='refused', last_error='409 Revision already used' WHERE resource_id=?",
                   (layers['Refused update'],))
        db.execute("UPDATE outbox SET status='refused', last_error='413 Too large to pull' WHERE resource_id=?",
                   (layers['Oversized update'],))
        db.execute("UPDATE peer_delivery SET failures=1, next_attempt=?, failing_since=?, last_pull=?, "
                   "last_problem='403 Peer authentication failed, and words the other peer chose' WHERE peer_id=?",
                   (now + 120, now - 60, now - 30, remote_card['peer_id']))
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, 'organizer') as (page, _):
            page.get_by_role('link', name='Connections', exact=True).click()
            retried = page.locator('.item', has_text='Retried update → Casey Remote')
            expect(retried.get_by_text('Share update · Retrying, next attempt', exact=False)).to_be_visible()
            expect(retried.get_by_role('button', name='Retry')).to_be_visible()
            refused = page.locator('.item', has_text='Refused update → Casey Remote')
            expect(refused.get_by_text('Share update · Not delivered (409)')).to_be_visible()
            expect(refused.get_by_role('button', name='Retry')).to_be_visible()
            oversized = page.locator('.item', has_text='Oversized update → Casey Remote')
            expect(oversized.get_by_text('Too large to deliver by pull: make the release smaller', exact=False)).to_be_visible()
            expect(oversized.get_by_role('button', name='Retry')).to_have_count(0)
            expect(page.get_by_text('Revision already used', exact=False)).to_have_count(0)  # the peer's own words never show
            peer = page.locator('.card', has_text='Casey Remote').filter(has_text='Fingerprint')
            expect(peer.get_by_text('Failing since', exact=False)).to_be_visible()
            expect(peer.get_by_text('1 failure · next attempt', exact=False)).to_be_visible()
            expect(peer.get_by_text('1 failure · next attempt', exact=False)).to_contain_text('· 403')  # SF3: the code only
            expect(peer.get_by_text('words the other peer chose', exact=False)).to_have_count(0)
            expect(peer.get_by_text('Last pulled', exact=False)).to_be_visible()  # SF2: a pull apart from a delivery
            assert page.evaluate("deliveryText('mystery')") == 'Delivery status unknown'  # never "Saved here"
            assert page.evaluate("deliveryText('refused')") == 'Not delivered'  # a refused reply's own label (spec §8)
            refused.get_by_role('button', name='Retry').click()
            expect(page.locator('.item', has_text='Refused update → Casey Remote').get_by_text('Not delivered', exact=False)).to_have_count(0)


# ---- Remote connector, Task 5: the sign-in and consent page (spec "The consent page"), seen as a stranger would see
# it on a phone (Tardis's cold look). The browser reaches https://home.example, which is routed to the app itself, so
# the page runs at the connector's real public origin with no TLS server. ----

CONSENT_ORIGIN = 'https://home.example'
CONSENT_CALLBACK = 'https://claude.ai/api/mcp/auth_callback'
CONSENT_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'
CONSENT_LINES = (
    "Claude wants to read the rooms you choose on this home. It can't post or change anything.",
    "What Claude reads can't be taken back.",
    "Claude's HIPAA agreement doesn't cover connectors.",
    "Room text can contain instructions written by other people. Don't let a chat that uses this connector send email "
    "or post elsewhere without checking.",
    "This home's super admins can see that this connection exists and can end it. Their page doesn't show which rooms it "
    "reads, but whoever runs this home's computer can look that up.",
    "Allow only if you just started connecting from your own Claude account.",
)


@pytest.fixture
def connector_home(tmp_path):
    from fastapi.testclient import TestClient
    clock = [1000000.0]
    app = create_app(tmp_path / 'home', clock=lambda: clock[0], allowed_origins=[CONSENT_ORIGIN],
                     public_origin=CONSENT_ORIGIN)
    store = app.state.store
    sam = store.create_user('sam@example.org', 'Sam Example', 'long-password-sam')
    jenn = store.create_user('jenn@example.org', 'Jenn Example', 'long-password-jenn')
    rooms = {'plain': store.create_room(sam['id'], 'Care plan', [])['id']}
    growing = store.create_room(sam['id'], 'Growing', [])['id']
    rooms['growing'] = store.add_participants(sam['id'], growing, [jenn['id']])['id']
    rooms['marked'] = store.create_room(sam['id'], 'Night notes', [])['id']
    rooms['markup'] = store.create_room(sam['id'], '<img src=x id=planted> notes', [])['id']  # a person's words, as text
    with store.transaction() as db:
        db.execute('INSERT INTO room_cloud VALUES(?,?,?)', (rooms['marked'], sam['id'], clock[0]))
    client = TestClient(app, base_url=CONSENT_ORIGIN, client=('203.0.113.5', 50000), follow_redirects=False)
    client_id = client.post('/register', json={'redirect_uris': [CONSENT_CALLBACK], 'client_name': 'Claude'}).json()['client_id']
    return {'app': app, 'client': client, 'client_id': client_id, 'clock': clock, 'rooms': rooms, 'store': store}


@contextmanager
def consent_browser(playwright, home, landed):
    """A phone-sized browser whose https://home.example is the app, and whose Claude callback records where it was
    sent."""
    def via_app(route):
        request = route.request
        headers = {k: v for k, v in request.all_headers().items() if k.lower() not in ('host', 'content-length')}
        answer = home['client'].request(request.method, request.url, headers=headers, content=request.post_data_buffer)
        route.fulfill(status=answer.status_code, body=answer.content,
                      headers={k: v for k, v in answer.headers.items() if k.lower() != 'content-length'})

    def at_claude(route):
        landed.append(route.request.url)
        route.fulfill(status=200, content_type='text/html', body='<p>Back at Claude</p>')
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 390, 'height': 844})
    context.route(lambda url: url.startswith(CONSENT_ORIGIN + '/'), via_app)  # a predicate: a glob's ? is a wildcard
    context.route(lambda url: url.startswith('https://claude.ai/'), at_claude)
    try:
        yield context.new_page()
    finally:
        context.close()
        browser.close()


def start_connecting(page, home):
    """/authorize as Claude sends it, then the consent page it sends the browser to. The 303 is followed here, not by
    the browser: a fulfilled route's redirect isn't routed again, and the unit tests pin that redirect."""
    sent = home['client'].get('/authorize', params={
        'response_type': 'code', 'client_id': home['client_id'], 'redirect_uri': CONSENT_CALLBACK, 'state': 'st-1',
        'code_challenge': CONSENT_CHALLENGE, 'code_challenge_method': 'S256', 'resource': CONSENT_ORIGIN + '/mcp',
        'scope': 'rooms.read offline_access'})
    assert sent.status_code == 303, sent.text
    page.goto(sent.headers['location'])


def fits_the_phone(page):
    return page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')


def sign_in_to_consent(page):
    page.get_by_label('Username', exact=True).fill('sam@example.org')
    page.get_by_label('Password', exact=True).fill('long-password-sam')
    page.get_by_role('button', name='Sign in').click()
    expect(page.get_by_text('Signed in as Sam Example')).to_be_visible()


def test_the_consent_page_as_a_stranger_sees_it_on_a_phone(connector_home):
    """The cold look: before signing in, only the sign-in form, and nothing about the person's rooms. After it, what
    the app is (by its redirect host, its own name only in quotes), what it may do, each line the spec asks for, the
    rooms with none chosen and the marked one unchoosable, and Allow only once something is chosen. Nothing overflows
    the phone's width. Allow sends the browser to Claude with a code, the state and iss."""
    from urllib.parse import parse_qs, urlsplit
    home, landed = connector_home, []
    with sync_playwright() as playwright:
        with consent_browser(playwright, home, landed) as page:
            start_connecting(page, home)
            expect(page.get_by_role('heading', name='Connect an app to your home')).to_be_visible()
            expect(page.get_by_text('Care plan')).to_have_count(0)
            # read once, then cleared from the address and its history: on a shared profile a request left there could be
            # signed into by someone else within its ten minutes, and the rebind would take the consent over (Tardis)
            assert page.url == CONSENT_ORIGIN + '/assets/consent.html' and page.evaluate('location.hash') == ''
            assert fits_the_phone(page)
            sign_in_to_consent(page)
            expect(page.get_by_role('heading', name='Claude (claude.ai)')).to_be_visible()
            expect(page.get_by_text('It calls itself "Claude".')).to_be_visible()
            for line in CONSENT_LINES:
                expect(page.get_by_text(line, exact=True)).to_be_visible()
            plain, marked = page.get_by_label('Care plan'), page.get_by_label('Night notes')
            expect(plain).not_to_be_checked()
            expect(marked).to_be_disabled()
            expect(page.get_by_text('Kept from connected apps')).to_be_visible()
            expect(page.get_by_text('Growing: earlier part of Growing')).to_be_visible()
            expect(page.get_by_text('<img src=x id=planted> notes')).to_be_visible()
            assert page.locator('#planted').count() == 0  # shown as text, never made into an element
            allow = page.get_by_role('button', name='Allow')
            expect(allow).to_be_disabled()
            plain.check()
            expect(allow).to_be_enabled()
            plain.uncheck()
            expect(allow).to_be_disabled()
            page.get_by_label('All my rooms, including new ones').check()
            expect(allow).to_be_enabled()
            assert fits_the_phone(page)
            allow.click()
            expect(page.get_by_text('Back at Claude')).to_be_visible()
    [url] = landed
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(CONSENT_CALLBACK + '?') and set(query) == {'code', 'state', 'iss'}
    assert (query['state'], query['iss']) == ('st-1', CONSENT_ORIGIN)
    with home['store'].transaction() as db:
        assert [row['rooms'] for row in db.execute('SELECT rooms FROM connector_grants')] == ['*']


@pytest.mark.parametrize("who, line", [
    ("jenn@example.org", "Growing: earlier part, not marked. An app with all your rooms can read it."),
    ("sam@example.org", "Growing: earlier part of Growing"),
])
def test_a_marked_rooms_earlier_part_says_if_the_mark_doesnt_cover_it(connector_home, who, line):
    """A member's mark covers the rooms they were in. Jenn joined only the continuing room, so the earlier part stays open
    to an all-rooms app, under a row that says it's kept. Sam was in both."""
    home, landed = connector_home, []
    with home['store'].transaction() as db:
        marker = db.execute('SELECT id FROM users WHERE username=?', (who,)).fetchone()[0]
    home['store'].mark_room(marker, home['rooms']['growing'])
    with sync_playwright() as playwright:
        with consent_browser(playwright, home, landed) as page:
            start_connecting(page, home)
            sign_in_to_consent(page)
            expect(page.get_by_text(line, exact=True)).to_be_visible()


def test_the_consent_page_says_when_a_request_has_expired_and_offers_no_form(connector_home):
    home, landed = connector_home, []
    with sync_playwright() as playwright:
        with consent_browser(playwright, home, landed) as page:
            start_connecting(page, home)
            home['clock'][0] += 600
            page.get_by_label('Username', exact=True).fill('sam@example.org')
            page.get_by_label('Password', exact=True).fill('long-password-sam')
            page.get_by_role('button', name='Sign in').click()
            expect(page.get_by_text('This request has expired. Go back to Claude and connect again.')).to_be_visible()
            expect(page.get_by_label('Password', exact=True)).to_have_count(0)
    assert landed == []


def test_deny_on_the_consent_page_sends_access_denied(connector_home):
    from urllib.parse import parse_qs, urlsplit
    home, landed = connector_home, []
    with sync_playwright() as playwright:
        with consent_browser(playwright, home, landed) as page:
            start_connecting(page, home)
            sign_in_to_consent(page)
            page.get_by_role('button', name='Deny').click()
            expect(page.get_by_text('Back at Claude')).to_be_visible()
    [url] = landed
    assert {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()} == {
        'error': 'access_denied', 'state': 'st-1', 'iss': CONSENT_ORIGIN}


def test_switch_person_on_the_consent_page_hands_the_request_to_the_second_person(connector_home):
    """The re-check's R10: Switch person sends the token the page holds, so the second person's sign-in takes the
    request over, and their Allow makes their grant."""
    home, landed = connector_home, []
    with sync_playwright() as playwright:
        with consent_browser(playwright, home, landed) as page:
            start_connecting(page, home)
            sign_in_to_consent(page)
            page.get_by_role('button', name='Switch person').click()
            page.get_by_label('Username', exact=True).fill('jenn@example.org')
            page.get_by_label('Password', exact=True).fill('long-password-jenn')
            page.get_by_role('button', name='Sign in').click()
            expect(page.get_by_text('Signed in as Jenn Example')).to_be_visible()
            page.get_by_label('All my rooms, including new ones').check()
            page.get_by_role('button', name='Allow').click()
            expect(page.get_by_text('Back at Claude')).to_be_visible()
    with home['store'].transaction() as db:
        [(person,)] = db.execute('SELECT users.username FROM connector_grants JOIN users ON users.id=connector_grants.person_id')
    assert person == 'jenn@example.org' and len(landed) == 1


# ---- Remote connector, Task 9b: Connected apps, the new-connection notice and the admins' view (spec "Receipts and
# revoking"). The connector is on under the `connector` marker, and each connection is made by its real flow. ----

def connect_claude(peer, username, rooms):
    """A connection made as Claude makes one (register, /authorize, the sign-in, Allow with `rooms`, /token) for a
    browser person, and a reader that calls read_room with its access token."""
    from types import SimpleNamespace
    from connector_support import a_fragment, decide, exchange, mcp, register, rpc, sent_back, sign_in
    home = SimpleNamespace(app=peer["app"], store=peer["app"].state.store)
    client = register(home.app).json()["client_id"]
    view = sign_in(home, a_fragment(home, client), username, password=peer["password"])
    assert view.status_code == 200, view.text
    _, query = sent_back(decide(home, view.json(), rooms=rooms))
    access = exchange(home, client, query["code"]).json()["access_token"]
    return lambda room: mcp(home, rpc("tools/call", {"name": "read_room", "arguments": {"room": room}}), access)


def connected_apps(page):
    page.get_by_role("link", name="Connected apps").click()
    expect(page.get_by_role("heading", name="Connected apps", level=1)).to_be_visible()
    return page.locator(".app-item")


@pytest.mark.connector
def test_a_connection_says_it_cant_read_a_room_marked_since(browser_peer):
    """The list says what the app reads, so a room a member has marked since says it can't, in place of a badge that reads
    as being about the app's reading at all. An all-rooms connection says what it leaves out, in the row and in the form."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care, lab = (store.create_room(patient, title, [])["id"] for title in ("Care plan", "Lab notes"))
    connect_claude(browser_peer, "patient", [care, lab])
    store.mark_room(patient, lab)
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        rooms = connected_apps(page).locator(".app-rooms")
        expect(rooms.locator("li", has_text="Lab notes")).to_have_text("Lab notes: it can't read this one, because a member has marked it.")
        expect(rooms.locator("li", has_text="Care plan")).to_have_text("Care plan")
        page.get_by_role("button", name="Change rooms").click()
        expect(page.get_by_text("Except rooms a member keeps from ships and apps.")).to_be_visible()


@pytest.mark.connector
def test_an_all_rooms_connection_says_what_it_leaves_out(browser_peer):
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    store.create_room(patient, "Care plan", [])
    connect_claude(browser_peer, "patient", "*")
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        expect(connected_apps(page).locator(".app-rooms")).to_have_text("It reads all your rooms on this home, including new ones, except rooms a member keeps from ships and apps.")


@pytest.mark.connector
def test_connected_apps_shows_a_connection_changes_its_rooms_and_revokes_after_the_ask(browser_peer):
    """Spec "Receipts and revoking": the app by host, its rooms by title, the line about disconnecting in Claude, and a
    rooms change Claude meets on its next call. Revoke asks in place, ends nothing before the confirm, sends one revoke
    for a double click, and then ends the connection at once. A room title written as HTML shows as text."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care, lab = (store.create_room(patient, title, [])["id"] for title in ("Care plan", "<b>Lab</b> notes"))
    read = connect_claude(browser_peer, "patient", [care, lab])
    store.mark_room(patient, store.create_room(patient, "Kept away", [])["id"])  # never offered
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        revokes = []
        page.on("request", lambda request: revokes.append(request.url) if request.method == "POST" and request.url.endswith("/revoke") else None)
        item = connected_apps(page)
        expect(page.get_by_text("Disconnecting in Claude doesn't end the connection here. Revoke does.")).to_be_visible()
        expect(item).to_have_count(1)
        expect(item.locator("h2")).to_have_text("Claude (claude.ai)")
        rooms = item.locator(".app-rooms")
        expect(rooms).to_contain_text("Care plan")
        expect(rooms).to_contain_text("<b>Lab</b> notes")
        assert page.locator("#main-content b").count() == 0
        item.get_by_role("button", name="Change rooms").click()
        expect(item.get_by_label("These rooms")).to_be_focused()  # the form's first control
        expect(item.get_by_label("Kept away")).to_have_count(0)
        item.get_by_label("Care plan").uncheck()
        item.get_by_role("button", name="Save rooms").click()
        expect(page.locator(".notice", has_text="Rooms saved. Claude reads them from its next call.")).to_be_visible()
        expect(rooms).not_to_contain_text("Care plan")
        assert read(care).json()["result"]["isError"] is True and read(lab).json()["result"]["isError"] is False
        item.get_by_role("button", name="Revoke").click()
        expect(item).to_contain_text("Revoke this connection? Claude stops reading your rooms at once.")
        expect(item.get_by_role("button", name="Cancel")).to_be_focused()
        item.get_by_role("button", name="Cancel").click()  # the safe choice changes nothing
        expect(item.locator(".app-ask")).to_have_count(0)
        expect(item.get_by_role("button", name="Revoke")).to_be_focused()
        item.get_by_role("button", name="Revoke").click()
        assert read(lab).status_code == 200 and revokes == []  # nothing ends before the confirm
        page.get_by_role("link", name="Chats", exact=True).click()  # an open ask doesn't outlive the page (N3)
        item = connected_apps(page)
        expect(item.locator(".app-ask")).to_have_count(0)
        item.get_by_role("button", name="Revoke").click()
        item.get_by_role("button", name="Yes, revoke").dblclick()
        expect(item).to_contain_text("You revoked it")
        expect(rooms).to_contain_text("It could read these rooms:")  # past tense once it has ended
        expect(item.get_by_role("button", name="Revoke")).to_have_count(0)
        expect(item.get_by_role("button", name="Change rooms")).to_have_count(0)
        expect(page.locator(".connector-notice")).to_have_count(0)
        assert len(revokes) == 1
    assert read(lab).status_code == 401


@pytest.mark.connector
def test_the_new_connection_notice_shows_on_every_page_and_its_revoke_asks_first(browser_peer):
    """Spec "The new-connection notice": for 7 days after a connection is made the page says "Claude was connected on
    <date>. Not you? Revoke." Its Revoke opens that connection's ask on Connected apps, with Cancel focused."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care = store.create_room(patient, "Care plan", [])["id"]
    read = connect_claude(browser_peer, "patient", [care])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        notice = page.locator(".connector-notice")
        expect(notice).to_contain_text("Claude was connected on")
        expect(notice).to_contain_text("Not you?")
        page.get_by_role("link", name="Chats", exact=True).click()
        expect(notice).to_be_visible()
        notice.get_by_role("button", name="Revoke").click()
        expect(page.get_by_role("heading", name="Connected apps", level=1)).to_be_visible()
        ask = page.locator(".app-ask")
        expect(ask.get_by_role("button", name="Cancel")).to_be_focused()
        ask.get_by_role("button", name="Yes, revoke").click()
        expect(page.locator(".app-item")).to_contain_text("You revoked it")
        expect(notice).to_have_count(0)
        with store.transaction() as db:  # a reason nobody recorded reads `unknown` (9a's N1), said in words
            db.execute("UPDATE connector_grants SET revoked_why=NULL")
        page.reload()
        expect(page.locator(".app-item")).to_contain_text("Why it ended wasn't recorded.")
    assert read(care).status_code == 401


@pytest.mark.connector
def test_a_room_that_continues_in_a_new_one_is_offered_not_added(browser_peer):
    """Spec: "<title> continues in a new room. Let Claude read it?" The new room is added only when the person says so.
    A listed room it can no longer read (marked since) is left out of that change and named, so the home doesn't refuse
    the whole of it (Tardis's nit on 0a5ffc9f)."""
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    care, notes = (store.create_room(users["patient"]["id"], title, [])["id"] for title in ("Care plan", "Old notes"))
    read = connect_claude(browser_peer, "patient", [care, notes])
    later = store.add_participants(users["patient"]["id"], care, [users["family"]["id"]])["id"]
    with store.transaction() as db:  # a time a restore left damaged shows as such, never as 1970 (9a's M1)
        db.execute("UPDATE connector_grants SET created='soon'")
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        store.mark_room(users["patient"]["id"], notes)  # after the home page loaded: #apps reads the home again (S3)
        item = connected_apps(page)
        expect(item).to_contain_text("Connected a time not recorded")
        expect(item).to_contain_text("Care plan continues in a new room. Let Claude read it?")
        assert read(later).json()["result"]["isError"] is True
        item.get_by_role("button", name="Let Claude read the new Care plan").click()
        expect(page.locator(".notice", has_text="Rooms saved. Claude reads them from its next call. Left out, since Claude can't read them now: Old notes.")).to_be_visible()
        expect(item).not_to_contain_text("continues in a new room")
    assert read(later).json()["result"]["isError"] is False


@pytest.mark.connector
def test_receipts_show_what_was_read_a_page_at_a_time_and_start_again_when_the_list_changed(browser_peer):
    """Each receipt says when, which tool and which rooms, by title as shown now. Show earlier reads the next page by its
    cursor; a cursor whose receipt has gone starts the list again from the newest, never an error (Rio Grande's nit on
    72889183)."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care = store.create_room(patient, "<i>Care</i> plan", [])["id"]
    read = connect_claude(browser_peer, "patient", [care])
    for _ in range(24):
        assert read(care).status_code == 200
    store.mark_room(patient, care)
    assert read(care).json()["result"]["isError"] is True  # the newest is a refusal, its room named once with why
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        earlier = []
        page.on("request", lambda request: earlier.append(request.url) if "/receipts?" in request.url and "before=" in request.url else None)
        item = connected_apps(page)
        item.get_by_role("button", name="Show what it read").click()
        receipts = item.locator(".receipt")
        expect(receipts).to_have_count(20)
        expect(receipts.first).to_have_text(re.compile(r"^[^·]+ · Read a room · Refused: <i>Care</i> plan \(a member keeps it from ships and apps\)$"))
        expect(receipts.nth(1)).to_have_text(re.compile(r"^[^·]+ · Read a room · Read: <i>Care</i> plan$"))
        assert page.locator("#main-content i").count() == 0
        item.get_by_role("button", name="Show earlier").dblclick()  # one read at a time: the next page once
        expect(receipts).to_have_count(25)
        assert len(earlier) == 1, earlier
        expect(item.get_by_role("button", name="Show earlier")).to_have_count(0)
        page.reload()
        item = connected_apps(page)
        item.get_by_role("button", name="Show what it read").click()
        expect(item.locator(".receipt")).to_have_count(20)
        with store.transaction() as db:  # the page's cursor, the 20th newest, goes before the next page is asked for
            db.execute("DELETE FROM connector_reads WHERE id=(SELECT id FROM connector_reads ORDER BY rowid DESC LIMIT 1 OFFSET 19)")
        item.get_by_role("button", name="Show earlier").click()
        expect(page.locator(".notice", has_text="The list changed while you read it, so it starts again from the newest.")).to_be_visible()
        expect(item.locator(".receipt")).to_have_count(20)
        expect(item.get_by_role("button", name="Show earlier")).to_be_visible()


@pytest.mark.connector
def test_a_super_admin_sees_each_connection_but_never_its_rooms_and_can_revoke_it(browser_peer):
    """Spec "The home's admins": super admins see each connection's person, app, made, last used and end, and revoke it;
    never its rooms or receipts. An admin who isn't a super admin sees no such section."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care = store.create_room(patient, "Care plan", [])["id"]
    read = connect_claude(browser_peer, "patient", [care])
    with store.transaction() as db:  # a name written as HTML shows as text
        db.execute("UPDATE users SET name='<b>Alex</b> Patient' WHERE id=?", (patient,))
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            page.get_by_role("link", name="Connections", exact=True).click()
            expect(page.get_by_role("heading", name="Connections", level=1)).to_be_visible()
            expect(page.locator(".connector-admin")).to_have_count(0)
        with store.transaction() as db:
            db.execute("UPDATE users SET is_super_admin=1 WHERE username='organizer'")
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            page.get_by_role("link", name="Connections", exact=True).click()
            section = page.locator(".connector-admin")
            expect(section.get_by_role("heading", name="Connected apps on this home")).to_be_visible()
            item = section.locator(".app-admin-item")
            expect(item).to_have_count(1)
            expect(item).to_contain_text("<b>Alex</b> Patient (@patient)")  # two people can share a name (N5)
            expect(item).to_contain_text("claude.ai")
            expect(section).not_to_contain_text("Care plan")
            assert section.locator("b").count() == 0
            item.get_by_role("button", name="Revoke").click()
            expect(item.get_by_role("button", name="Cancel")).to_be_focused()
            item.get_by_role("button", name="Yes, revoke").click()
            expect(item).to_contain_text("Ended")
    assert read(care).status_code == 401


def test_without_the_connector_there_is_no_connected_apps_link_or_notice(browser_peer):
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        expect(page.get_by_role("link", name="Connections", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="Connected apps")).to_have_count(0)
        expect(page.locator(".connector-notice")).to_have_count(0)



@pytest.mark.connector
def test_on_a_phone_every_nav_link_sits_in_the_bar_and_takes_a_click(browser_peer):
    """The phone's nav drew links over each other, and then hid half of them in a row that gave no sign it scrolled (the
    reader's S1). At 390px, the most common phone width, all ten links show in a two-row bar, none over another, and the
    last one takes a real click: Playwright checks what the pointer would hit."""
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient", viewport={"width": 390, "height": 844}) as (page, _):
        bar = page.locator(".sidebar").bounding_box()
        boxes = [link.bounding_box() for link in page.locator(".nav a").all()]
        assert len(boxes) == 10
        for box in boxes:
            assert 0 <= box["x"] and box["x"] + box["width"] <= 390, box  # in view, not scrolled off the bar's end
            assert bar["y"] <= box["y"] and box["y"] + box["height"] <= bar["y"] + bar["height"] + 0.5, (box, bar)
            assert box["height"] <= 60, box  # a link the size of its cell, not stretched
        for i, first in enumerate(boxes):
            for second in boxes[i + 1:]:
                apart = (first["x"] + first["width"] <= second["x"] + 0.5 or second["x"] + second["width"] <= first["x"] + 0.5
                         or first["y"] + first["height"] <= second["y"] + 0.5 or second["y"] + second["height"] <= first["y"] + 0.5)
                assert apart, (first, second)
        page.get_by_role("link", name="Connected apps").click()
        expect(page.get_by_role("heading", name="Connected apps", level=1)).to_be_visible()


@pytest.mark.connector
def test_on_a_laptop_screen_the_last_nav_link_is_reachable(browser_peer):
    """M2: the desktop sidebar was 100vh and never scrolled, so on a 1366x768 laptop (a 657px viewport in Chrome) the
    last link, Connected apps, sat below the fold and no click could reach it. Fonts differ (the Mac fits it at 657px),
    so the test uses a shorter window, where every platform's last link is below the fold."""
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient", viewport={"width": 1366, "height": 520}) as (page, _):
        page.get_by_role("link", name="Connected apps").click()
        expect(page.get_by_role("heading", name="Connected apps", level=1)).to_be_visible()


@pytest.mark.connector
def test_the_notice_names_every_connection_of_the_last_7_days(browser_peer):
    """M1: the notice named only the newest live connection, so a thief's connection two days old was hidden the moment
    the person connected their own Claude. Each live connection made in the last 7 days has its own line and Revoke."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care = store.create_room(patient, "Care plan", [])["id"]
    older = connect_claude(browser_peer, "patient", [care])
    with store.transaction() as db:
        db.execute("UPDATE connector_grants SET created=created-2*86400")  # made two days ago
    newer = connect(browser_peer, "patient", [care], "st-newer")
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        lines = page.locator(".connector-notice li")
        expect(lines).to_have_count(2)
        expect(lines.first).to_contain_text("Claude was connected on")
        lines.nth(1).get_by_role("button", name="Revoke").click()  # the older one
        ask = page.locator(".app-ask")
        expect(ask.get_by_role("button", name="Cancel")).to_be_focused()
        ask.get_by_role("button", name="Yes, revoke").click()
        expect(lines).to_have_count(1)
    assert older(care).status_code == 401 and newer(care).status_code == 200


@pytest.mark.connector
def test_narrowing_from_all_rooms_says_why_an_earlier_room_is_not_offered(browser_peer):
    """N2 (9a's N9): a connection to all rooms has no list to keep an earlier room by, so the form offers only current
    rooms, and says so."""
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    care = store.create_room(users["patient"]["id"], "Care plan", [])["id"]
    connect_claude(browser_peer, "patient", "*")
    store.add_participants(users["patient"]["id"], care, [users["family"]["id"]])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        item = connected_apps(page)
        item.get_by_role("button", name="Change rooms").click()
        expect(item.locator(".app-rooms-form")).to_contain_text(
            "A room that continues in a newer one is offered as the newer room: an earlier room can't be added here.")
        expect(item.get_by_label("Care plan")).to_have_count(1)  # the current one only


@pytest.mark.connector
def test_a_room_marked_after_the_page_loaded_is_not_offered(browser_peer):
    """S3: Connected apps reads the home again, so a room a member marked after the page loaded isn't offered, even one
    the connection doesn't list (the list's own marks cover only its rooms)."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care, other = (store.create_room(patient, title, [])["id"] for title in ("Care plan", "Other room"))
    connect_claude(browser_peer, "patient", [care])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        store.mark_room(patient, other)  # after the home page loaded
        item = connected_apps(page)
        item.get_by_role("button", name="Change rooms").click()
        expect(item.get_by_label("Care plan")).to_have_count(1)
        expect(item.get_by_label("Other room")).to_have_count(0)


@pytest.mark.connector
def test_a_second_connections_receipts_open_while_the_first_still_loads(browser_peer):
    """N4: one receipt read at a time for each connection, not for the page: the first connection's read is held open
    while the second's list opens."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care, lab = (store.create_room(patient, title, [])["id"] for title in ("Care plan", "Lab notes"))
    one, two = connect_claude(browser_peer, "patient", [care]), connect(browser_peer, "patient", [lab], "st-two")
    one(care)
    two(lab)
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        items = connected_apps(page)
        held = []
        page.route(lambda url: "/receipts?" in url, lambda route: held.append(route) if not held else route.continue_())
        items.nth(0).get_by_role("button", name="Show what it read").click()
        items.nth(1).get_by_role("button", name="Show what it read").click()
        expect(items.nth(1).locator(".receipt")).to_have_count(1)
        held[0].continue_()
        expect(items.nth(0).locator(".receipt")).to_have_count(1)


# ---- The reader's six probes on 0a5ffc9f (City of AI 55352599), verbatim but for the `connector` marker each needs
# here. They kill the eight mutants the tests above missed. ----
EVIL = '"><img src=x onerror="window.__xss=1">'


def connect(peer, username, rooms, state):
    """connect_claude with its own `state`, so a second connection in the same second is its own request."""
    from types import SimpleNamespace
    from connector_support import a_fragment, decide, exchange, mcp, register, rpc, sent_back, sign_in
    home = SimpleNamespace(app=peer["app"], store=peer["app"].state.store)
    client = register(home.app).json()["client_id"]
    view = sign_in(home, a_fragment(home, client, state=state), username, password=peer["password"])
    assert view.status_code == 200, view.text
    _, query = sent_back(decide(home, view.json(), rooms=rooms))
    access = exchange(home, client, query["code"]).json()["access_token"]
    return lambda room: mcp(home, rpc("tools/call", {"name": "read_room", "arguments": {"room": room}}), access)


def xss_free(page):
    assert page.evaluate("window.__xss") is None
    assert page.locator("#main-content img, #main-content b, #main-content i").count() == 0


@pytest.mark.connector
def test_p1_titles_with_markup_in_every_place_the_page_shows_them(browser_peer):
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    care = store.create_room(patient, "<b>Care</b>" + EVIL, [])["id"]
    long = store.create_room(patient, "L" * 200, [])["id"]
    read = connect_claude(browser_peer, "patient", [care, long])
    assert read(care).status_code == 200 and read(long).status_code == 200
    store.add_participants(patient, care, [users["family"]["id"]])  # care continues in a new room: the offer
    for viewport in ({"width": 1440, "height": 960}, {"width": 390, "height": 844}):
        with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient", viewport=viewport) as (page, _):
            item = connected_apps(page)
            expect(item).to_contain_text("<b>Care</b>" + EVIL + " continues in a new room.")
            add = item.locator('[data-action="app-room-add"]')
            assert EVIL in add.get_attribute("aria-label")
            xss_free(page)
            item.get_by_role("button", name="Show what it read").click()
            expect(item.locator(".receipt")).to_have_count(2)
            xss_free(page)
            item.get_by_role("button", name="Change rooms").click()
            expect(item.locator(".app-rooms-form")).to_be_visible()
            expect(item.locator(".app-rooms-form")).to_contain_text("<b>Care</b>" + EVIL)
            xss_free(page)
            width = page.evaluate("document.documentElement.clientWidth")
            assert page.evaluate("document.scrollingElement.scrollWidth") <= width, viewport


@pytest.mark.connector
def test_p3_admin_section_never_asks_for_or_shows_rooms_or_receipts_whatever_the_server_sends(browser_peer):
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    connect_claude(browser_peer, "patient", [store.create_room(patient, "Care plan", [])["id"]])
    with store.transaction() as db:
        db.execute("UPDATE users SET is_super_admin=1 WHERE username='organizer'")
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
        asked = []
        page.on("request", lambda request: asked.append(request.url) if "/connected-apps" in request.url else None)
        def widened(route):
            answer = route.fetch()
            items = answer.json()
            for item in items:
                item.update(rooms=[{"room": "r1", "title": "Secret room", "cloud": False, "continues_in": None}],
                            all_rooms=False, receipts=[{"at": 1, "tool": "read_room", "rooms_read": [{"room": "r1", "title": "Secret room"}]}],
                            why="refresh_reused", usable=True)
            route.fulfill(response=answer, body=json.dumps(items))
        page.route("**/api/admin/connected-apps", widened)
        page.get_by_role("link", name="Connections", exact=True).click()
        section = page.locator(".connector-admin")
        expect(section.locator(".app-admin-item")).to_have_count(1)
        expect(section).not_to_contain_text("Secret room")
        expect(section).not_to_contain_text("renewal")
        expect(page.locator("#main-content")).not_to_contain_text("Secret room")
        expect(section.locator('[data-action="app-receipts"], [data-action="app-rooms-edit"]')).to_have_count(0)
        section.locator('[data-action="app-admin-revoke"]').click()
        section.get_by_role("button", name="Yes, revoke").click()
        expect(section.locator(".app-admin-item")).to_contain_text("Ended")
        others = [url for url in asked if "/api/admin/connected-apps" not in url and not url.endswith("/api/connected-apps/notice")]
        assert others == [], others


@pytest.mark.connector
def test_p4_a_revoke_that_meets_an_ended_connection_409(browser_peer):
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    read = connect_claude(browser_peer, "patient", [store.create_room(patient, "Care plan", [])["id"]])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        item = connected_apps(page)
        item.get_by_role("button", name="Revoke").click()
        with store.transaction() as db:
            [(grant,)] = db.execute("SELECT id FROM connector_grants").fetchall()
        store.connected_app_revoke(patient, grant)  # ended behind the page's back (another tab)
        item.get_by_role("button", name="Yes, revoke").click()
        expect(page.locator(".notice.error")).to_contain_text("This connection has ended")
        expect(item).to_contain_text("You revoked it")
        expect(item.locator(".app-ask")).to_have_count(0)
        expect(item.get_by_role("button", name="Revoke")).to_have_count(0)
        expect(page.locator(".connector-notice")).to_have_count(0)
    assert read is not None


@pytest.mark.connector
def test_p5_a_rooms_save_that_meets_a_mark_400(browser_peer):
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    patient, family = users["patient"]["id"], users["family"]["id"]
    care = store.create_room(patient, "Care plan", [family])["id"]
    lab = store.create_room(patient, "Lab notes", [])["id"]
    connect_claude(browser_peer, "patient", [care, lab])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        item = connected_apps(page)
        item.get_by_role("button", name="Change rooms").click()
        item.get_by_label("Lab notes").uncheck()
        store.mark_room(family, care)  # a member marks Care plan while the form is open
        item.get_by_role("button", name="Save rooms").click()
        expect(page.locator(".notice.error")).to_contain_text("A member has marked that room")
    with store.transaction() as db:
        [(rooms,)] = db.execute("SELECT rooms FROM connector_grants").fetchall()
    assert set(json.loads(rooms)) == {care, lab}


@pytest.mark.connector
def test_p9_receipts_of_two_connections_stay_apart(browser_peer):
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    care, lab = (store.create_room(patient, title, [])["id"] for title in ("Care plan", "Lab notes"))
    one = connect_claude(browser_peer, "patient", [care])
    two = connect(browser_peer, "patient", [lab], "st-two")
    for _ in range(3):
        one(care)
    two(lab)
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        items = connected_apps(page)
        expect(items).to_have_count(2)
        for index in range(2):
            items.nth(index).get_by_role("button", name="Show what it read").click()
        for index in range(2):  # both read at once now (N4), so wait for each list before reading it
            expect(items.nth(index).locator(".receipt").first).to_be_visible()
        texts = [items.nth(index).locator(".receipt").all_inner_texts() for index in range(2)]
        assert sorted(len(t) for t in texts) == [1, 3]
        for t in texts:
            assert len({line.split(" · ")[-1] for line in t}) == 1


@pytest.mark.connector
def test_p13_change_rooms_keeps_an_earlier_room_the_connection_holds(browser_peer):
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    patient = users["patient"]["id"]
    care = store.create_room(patient, "Care plan", [])["id"]
    lab = store.create_room(patient, "Lab notes", [])["id"]
    connect_claude(browser_peer, "patient", [care, lab])
    store.add_participants(patient, care, [users["family"]["id"]])
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "patient") as (page, _):
        item = connected_apps(page)
        item.get_by_role("button", name="Change rooms").click()
        checked = item.locator('input[name="app-room"]:checked').evaluate_all("(els) => els.map((el) => el.value)")
        assert care in checked and lab in checked, checked
        item.get_by_label("Lab notes").uncheck()
        item.get_by_role("button", name="Save rooms").click()
        expect(page.locator(".notice", has_text="Rooms saved.")).to_be_visible()
    with store.transaction() as db:
        [(rooms,)] = db.execute("SELECT rooms FROM connector_grants").fetchall()
    assert json.loads(rooms) == [care]


def test_a_long_name_with_no_spaces_never_pushes_connections_sideways_on_a_phone(browser_peer):
    """The 9b reader's N6 (probe P2): an account named with 200 letters and no space overflowed Connections at 390px
    through the older `.item`, so the page scrolled sideways and its buttons left the screen."""
    store, patient = browser_peer["app"].state.store, browser_peer["users"]["patient"]["id"]
    with store.transaction() as db:
        db.execute("UPDATE users SET name=? WHERE id=?", ("L" * 200, patient))
    with sync_playwright() as playwright, signed_in_browser(playwright, browser_peer, "organizer", viewport={"width": 390, "height": 844}) as (page, _):
        page.get_by_role("link", name="Connections", exact=True).click()
        expect(page.get_by_text("L" * 200).first).to_be_visible()
        width = page.evaluate("document.documentElement.clientWidth")
        assert page.evaluate("document.scrollingElement.scrollWidth") <= width
