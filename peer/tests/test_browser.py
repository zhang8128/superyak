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
            urlopen(base_url + "/", timeout=0.2)
            break
        except HTTPError:
            break
        except URLError:
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
    expect(page.get_by_role("heading", name="Your home")).to_be_visible()
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


@pytest.mark.parametrize('browser_peer', [True], indirect=True)
def test_local_demo_opens_without_password_switches_accounts_and_renews_session(browser_peer):
    with sync_playwright() as playwright:
        with signed_out_browser(playwright) as page:
            page.goto(browser_peer['base_url'] + '/')
            expect(page.get_by_role('heading', name='Your home')).to_be_visible()
            expect(page.get_by_role('button', name='Account and sign out')).to_contain_text('Alex Patient')
            page.get_by_role('link', name='My sharing layers').click()
            page.get_by_role('button', name='New layer').click()
            expect(page.get_by_label('Layer title')).to_have_value('Untitled')
            page.get_by_label('What do you want to share?').fill('Patient unsaved words')
            page.get_by_role('button', name='Account and sign out').click()
            page.get_by_role('button', name='Try doctor', exact=True).click()
            expect(page.get_by_role('heading', name='Your home')).to_be_visible()
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
            patient.get_by_role("button", name="New layer").click()
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
            expect(page.get_by_role("heading", name="Your home")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.evaluate("scrollTo(0, 0)")
            page.wait_for_timeout(100)
            page.screenshot(path=str(ARTIFACTS / "home-mobile.png"))
            page.get_by_role("link", name="Connections").click()
            expect(page.get_by_role("heading", name="Account support")).to_be_visible()
            expect(page.get_by_text("Account support does not open private chats or drafts.")).to_be_visible()
            page.get_by_role("button", name="Create invitation").click()
            expect(page.get_by_text("One-use invitation")).to_be_visible()
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
            page.get_by_role("button", name="New layer").click()
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
            page.get_by_role("button", name="New layer").click()
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
            page.get_by_role("button", name="New layer").click()
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
            page.get_by_role("button", name="New layer").click()
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
            expect(page.get_by_role("heading", name="Your home")).to_be_visible()


def test_pairing_pending_delivery_and_peer_wide_disconnect_states(browser_peer):
    """Break caught: pairing shares implicitly or canceled delivery looks retryable."""
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            page.get_by_role("link", name="Connections").click()
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
            page.get_by_role("button", name="New layer").click()
            page.get_by_label("Layer title").fill("Remote delivery")
            page.get_by_role("checkbox", name="Casey Remote").check()
            page.get_by_role("button", name="Save private draft").click()
            expect(page.get_by_text("Saved version 2", exact=True)).to_be_visible()
            page.get_by_role("button", name="Preview audience").click()
            page.get_by_role("button", name="Turn on version 2").click()
            expect(page.get_by_text("Active · version 2")).to_be_visible()
            page.get_by_role("link", name="Connections").click()
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
            page.get_by_role("button", name="New layer").click()
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
            page.get_by_role("button", name="New layer").click()
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
                expect(page.get_by_role('heading', name='Your home')).to_be_visible()
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
