"""Real-browser acceptance flows for the same-origin personal home."""

from contextlib import contextmanager
import json
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
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import PeerIdentity


ARTIFACTS = (
    Path(__file__).resolve().parents[2]
    / ".superpowers/sdd/2026-09-12-peer-home/task-3-artifacts"
)


@pytest.fixture
def browser_peer(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    app = create_app(tmp_path / "browser-peer", allowed_origins=[base_url])
    store = app.state.store
    password = "long-browser-password"
    users = {
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
            expect(page.get_by_text("Connection lost. Your message is still here.")).to_be_visible()
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


def test_invited_participant_chooses_local_account_details(browser_peer):
    """Break caught: an issued invitation cannot be redeemed from the signed-out home."""
    store = browser_peer["app"].state.store
    invitation = store.invite(browser_peer["users"]["organizer"]["id"], 3600)
    with sync_playwright() as playwright:
        with signed_out_browser(playwright) as page:
            page.goto(browser_peer["base_url"] + "/")
            page.get_by_text("Use an invitation", exact=True).click()
            page.get_by_label("Invitation token").fill(invitation["token"])
            page.get_by_label("New username").fill("newperson")
            page.get_by_label("Your display name").fill("New Person")
            page.get_by_label("New password").fill("another-long-password")
            page.get_by_role("button", name="Create my account").click()
            expect(page.get_by_text("Account created. Sign in to open your home.")).to_be_visible()
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
            page.get_by_role("button", name="Preview audience").click()
            page.get_by_role("button", name="Turn on version 2").click()
            expect(page.get_by_text("Active · version 2")).to_be_visible()
            browser_peer["app"].state.federation.collect()
            page.get_by_role("link", name="Connections").click()
            page.reload()
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
            expect(page.get_by_text("Removing someone ends their access to this hosted room")).to_be_visible()
            page.get_by_role("button", name="Remove Sam Family from this room").click()
            expect(page.get_by_text("Sam Family no longer has access to this room")).to_be_visible()

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
