"""A recall crosses wherever a receiver is enabled (docs/superpowers/specs/2026-11-04-recall-crosses-by-default-design.md).

The remote case, a `[[remote_publishers]]` entry whose context equals `default_context`, lands with whichever of this and
tardis/crossing merges second: neither branch alone has both halves."""
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import socket
import time

import pytest

import neighbors
import lighthouse_receiver_config as receiver_config
from lighthouse_validation import bounded_read, load_owned_policy
from tests.test_neighbors import policy
from tests.test_recall_margins import engram_server_env, seed  # noqa: F401  (the fixture)

ENGRAM = Path(neighbors.__file__).resolve().parent
RUNTIME = ENGRAM.parent / "scripts" / "runtime.py"
CONTEXT = "memory/technical"


def receiver(tmp_path, *lines, name="engram"):
    """A receiver instance with a toml of `lines`, and a storage standing in for its store."""
    instance = tmp_path / ".engram" / "instances" / name
    instance.mkdir(parents=True, exist_ok=True)
    (instance / "graph.db").write_text("")
    (instance / "lighthouse-receiver.toml").write_text("\n".join((
        "enabled = true", 'publishers = ["why"]', 'socket_path = "s.sock"', 'policy_path = "policy.json"', *lines)) + "\n")
    return instance, type("S", (), {"db_path": instance / "graph.db"})()


def recording_arm(monkeypatch):
    calls = []

    def arm(**kw):
        calls.append(kw)
        return dict(sources=[], selected=[], delivered=[], receipt_id="r", degraded=False, diagnostics=[])
    monkeypatch.setattr(neighbors, "neighbor_arm", arm)
    return calls


def attach_default(tmp_path, storage=None, name="engram", response=None):
    response = dict(recall_id="turn", results=["local"]) if response is None else response
    return neighbors.attach_default(response, query="q", purpose="session-recall", storage=storage, session_id="s",
                                    receiver=name, engram_home=tmp_path)


def attach_explicit(tmp_path, storage, context=CONTEXT):
    return neighbors.attach_neighbors(dict(recall_id="turn", results=["local"]), query="q", context_id=context,
                                      purpose="session-recall", storage=storage, session_id="s", receiver="engram",
                                      engram_home=tmp_path)


# ---------------------------------------------------------------- the owner's switch

def test_without_the_key_a_recall_stays_as_it_is_and_makes_no_call(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)

    def fail(*a, **kw): raise AssertionError("nothing asked, so no neighbor call")
    monkeypatch.setattr(neighbors, "attach_neighbors", fail)
    _, storage = receiver(tmp_path)
    response = attach_default(tmp_path, storage)
    assert response == dict(recall_id="turn", results=["local"])
    assert calls == []


@pytest.mark.parametrize("name", [None, "", "../up", 7])
def test_no_named_receiver_is_inert(tmp_path, monkeypatch, name):
    calls = recording_arm(monkeypatch)
    assert attach_default(tmp_path, None, name) == dict(recall_id="turn", results=["local"])
    assert calls == []


def test_a_name_that_walks_out_of_instances_reads_nothing_there(tmp_path, monkeypatch):
    """`../up` would reach .engram/up/lighthouse-receiver.toml, a toml nobody chose for a receiver."""
    calls = recording_arm(monkeypatch)
    (tmp_path / ".engram" / "instances").mkdir(parents=True)
    up = tmp_path / ".engram" / "up"
    up.mkdir()
    (up / "lighthouse-receiver.toml").write_text(
        f'enabled = true\npublishers = ["why"]\nsocket_path = "s"\npolicy_path = "p"\ndefault_context = "{CONTEXT}"\n')
    assert attach_default(tmp_path, None, "../up") == dict(recall_id="turn", results=["local"])
    assert calls == []


def test_no_receiver_file_is_inert(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)
    assert attach_default(tmp_path, None) == dict(recall_id="turn", results=["local"])
    assert calls == []


def test_a_disabled_receiver_with_the_key_is_inert(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)
    instance, storage = receiver(tmp_path, f'default_context = "{CONTEXT}"')
    path = instance / "lighthouse-receiver.toml"
    path.write_text(path.read_text().replace("enabled = true", "enabled = false"))
    assert attach_default(tmp_path, storage) == dict(recall_id="turn", results=["local"])
    assert calls == []


def test_load_settings_keeps_its_shape_for_every_other_caller(tmp_path):
    """context_lighthouse.py, lighthouse_daemon.py and neighbor_arm's **settings take what load_settings returns."""
    instance, _ = receiver(tmp_path, f'default_context = "{CONTEXT}"')
    settings = receiver_config.load_settings(instance / "lighthouse-receiver.toml")
    assert set(settings) == {"publishers", "socket_path", "policy_path", "k", "timeout_s"}
    assert receiver_config.load_settings(instance / "absent.toml") is None
    (instance / "off.toml").write_text("enabled = false\n")
    assert receiver_config.load_settings(instance / "off.toml") is None


# ---------------------------------------------------------------- crossing

def test_the_key_makes_a_recall_cross_and_says_it_was_a_default(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)
    _, storage = receiver(tmp_path, f'default_context = "{CONTEXT}"')
    response = attach_default(tmp_path, storage)
    assert [c["context"]["id"] for c in calls] == [CONTEXT]
    assert calls[0]["purpose"] == "session-recall"
    assert response["neighbors"]["by_default"] is True
    assert response["neighbors"]["context"] == CONTEXT
    assert response["results"] == ["local"]


def test_an_explicit_context_wins_and_keeps_its_own_deadline(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)
    _, storage = receiver(tmp_path, 'default_context = "other/place"', "timeout_s = 5.0")
    response = attach_explicit(tmp_path, storage)
    assert calls[0]["context"]["id"] == CONTEXT
    assert calls[0]["timeout_s"] == 5.0
    assert response["neighbors"]["by_default"] is False
    assert response["neighbors"]["context"] == CONTEXT


@pytest.mark.parametrize("name, toml, code", [(None, None, "NO_RECEIVER"), ("engram", "enabled = false\n", "RECEIVER_DISABLED")])
def test_an_explicit_crossing_that_reaches_nobody_still_says_what_it_asked(tmp_path, name, toml, code):
    instance, storage = receiver(tmp_path)
    if toml:
        (instance / "lighthouse-receiver.toml").write_text(toml)
    response = neighbors.attach_neighbors(dict(results=["local"]), query="q", context_id=CONTEXT, purpose="session-recall",
                                          storage=storage, session_id="s", receiver=name, engram_home=tmp_path)
    assert response["neighbors"]["diagnostics"] == [{"code": code}]
    assert response["neighbors"]["context"] == CONTEXT and response["neighbors"]["by_default"] is False


def test_a_default_crossing_has_the_tighter_deadline(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)
    _, storage = receiver(tmp_path, f'default_context = "{CONTEXT}"', "timeout_s = 5.0")
    attach_default(tmp_path, storage)
    assert calls[0]["timeout_s"] == neighbors.DEFAULT_DEADLINE_S == 1.0


def test_a_shorter_configured_timeout_stands(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)
    _, storage = receiver(tmp_path, f'default_context = "{CONTEXT}"', "timeout_s = 0.25")
    attach_default(tmp_path, storage)
    assert calls[0]["timeout_s"] == 0.25


@pytest.mark.parametrize("value", ['7', '""', '"../up"', '"a b"', '"/rooted"', '"memory//technical"', '["memory"]',
                                   '{ a = 1 }', '"' + "x" * 600 + '"', 'true', '"memory/\\ud7ff"'])
def test_a_bad_value_is_invalid_config_and_a_recall_says_so(tmp_path, monkeypatch, value):
    calls = recording_arm(monkeypatch)
    instance, storage = receiver(tmp_path, f"default_context = {value}")
    with pytest.raises(ValueError, match="INVALID"):
        receiver_config.load_settings(instance / "lighthouse-receiver.toml")
    response = attach_default(tmp_path, storage)
    assert calls == []
    assert response["results"] == ["local"]
    assert response["degraded"] == ["neighbors"]
    assert response["neighbors"]["diagnostics"] == [{"code": "RECEIVER_CONFIG_INVALID"}]
    assert response["neighbors"]["by_default"] is True
    assert response["neighbors"]["context"] is None


def test_an_unreadable_toml_says_so_and_keeps_local_results(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)
    instance, storage = receiver(tmp_path)
    (instance / "lighthouse-receiver.toml").write_bytes(b"not = [toml\xff")
    response = attach_default(tmp_path, storage)
    assert calls == [] and response["results"] == ["local"]
    assert response["neighbors"]["diagnostics"] == [{"code": "RECEIVER_CONFIG_INVALID"}]


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_a_toml_path_that_is_no_file_says_so_and_never_hangs(tmp_path, monkeypatch, kind):
    """Every recall now reads this path: a FIFO with no writer would hang every recall, with no deadline over it."""
    calls = recording_arm(monkeypatch)
    instance, storage = receiver(tmp_path)
    path = instance / "lighthouse-receiver.toml"
    path.unlink()
    path.mkdir() if kind == "directory" else os.mkfifo(path)
    response = attach_default(tmp_path, storage)
    assert calls == [] and response["results"] == ["local"]
    assert response["neighbors"]["diagnostics"] == [{"code": "RECEIVER_CONFIG_INVALID"}]


def test_a_policy_that_is_a_fifo_refuses_rather_than_hangs(tmp_path):
    """The same read serves every policy, the daemon's too. A writer holding the FIFO open changes nothing."""
    path = tmp_path / "policy.json"
    os.mkfifo(path)
    writer = os.open(path, os.O_RDWR)
    try:
        with pytest.raises(ValueError):
            load_owned_policy(path, "engram")
    finally:
        os.close(writer)


def test_bounded_read_keeps_its_contract(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"x" * 8)
    assert bounded_read(path, 8) == b"x" * 8
    with pytest.raises(ValueError, match="INPUT_TOO_LARGE"):
        bounded_read(path, 7)
    with pytest.raises(FileNotFoundError):
        bounded_read(tmp_path / "absent", 8)


def test_bounded_read_refuses_a_fifo_for_what_it_is_even_with_valid_text_waiting(tmp_path):
    path = tmp_path / "f"
    os.mkfifo(path)
    writer = os.open(path, os.O_RDWR)
    try:
        os.write(writer, b"enabled = true\n")
        with pytest.raises(ValueError, match="NOT_A_REGULAR_FILE"):
            bounded_read(path, 64)
    finally:
        os.close(writer)


def test_bounded_read_closes_what_it_opened_when_it_refuses(tmp_path, monkeypatch):
    path = tmp_path / "f"
    os.mkfifo(path)
    opened, closed = [], []
    real_open, real_close = os.open, os.close
    monkeypatch.setattr(os, "open", lambda *a, **kw: opened.append(real_open(*a, **kw)) or opened[-1])
    monkeypatch.setattr(os, "close", lambda fd: (closed.append(fd), real_close(fd))[1])
    with pytest.raises(ValueError):
        bounded_read(path, 64)
    assert opened and closed == opened


def test_bounded_read_stops_at_its_cap_and_survives_a_short_read(tmp_path, monkeypatch):
    path = tmp_path / "f"
    path.write_bytes(b"x" * 100)
    returned = []
    real_read = os.read

    def one_at_a_time(fd, n):
        returned.append(real_read(fd, min(n, 1)))
        return returned[-1]
    monkeypatch.setattr(os, "read", one_at_a_time)
    assert bounded_read(path, 200) == b"x" * 100
    returned.clear()
    with pytest.raises(ValueError, match="INPUT_TOO_LARGE"):
        bounded_read(path, 10)
    assert len(b"".join(returned)) == 11, "cap plus one, so a huge file is never read whole"


def test_too_big_a_toml_says_so(tmp_path, monkeypatch):
    calls = recording_arm(monkeypatch)
    instance, storage = receiver(tmp_path)
    (instance / "lighthouse-receiver.toml").write_bytes(b"#" * 20000)
    response = attach_default(tmp_path, storage)
    assert calls == [] and response["neighbors"]["diagnostics"] == [{"code": "RECEIVER_CONFIG_INVALID"}]


def test_the_answer_says_why_when_the_store_is_not_the_receivers(tmp_path, monkeypatch):
    recording_arm(monkeypatch)
    receiver(tmp_path, f'default_context = "{CONTEXT}"')
    elsewhere = type("S", (), {"db_path": tmp_path / "other.db"})()
    response = attach_default(tmp_path, elsewhere)
    assert response["neighbors"]["diagnostics"] == [{"code": "RECEIVER_CONFIG_INVALID"}]
    assert response["neighbors"]["by_default"] is True
    assert response["neighbors"]["context"] == CONTEXT


# ---------------------------------------------------------------- when the publisher is down or hung

def real_receiver(tmp_path, *lines, sock=None):
    """A receiver with a real policy and a socket path short enough for macOS."""
    instance, storage = receiver(tmp_path, *lines)
    policy(instance / "policy.json")
    if sock is not None:
        path = instance / "lighthouse-receiver.toml"
        path.write_text(path.read_text().replace('"s.sock"', f'"{sock}"'))
    storage.add_log_entry = lambda **kw: None
    return instance, storage


def codes(response):
    return {d["code"] for d in response["neighbors"]["diagnostics"]}


@pytest.fixture
def short_socket():
    path = Path(f"/tmp/eg-{time.monotonic_ns() % 10**10}.sock")
    yield path
    path.unlink(missing_ok=True)


def test_a_hung_publisher_costs_a_default_crossing_only_its_deadline(tmp_path, short_socket):
    _, storage = real_receiver(tmp_path, f'default_context = "{CONTEXT}"', "timeout_s = 5.0", sock=short_socket)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(short_socket))
    server.listen(4)                     # accepts into the backlog and never answers
    try:
        begun = time.monotonic()
        response = attach_default(tmp_path, storage)
        took = time.monotonic() - begun
    finally:
        server.close()
    assert 0.9 < took < 1.6
    assert response["results"] == ["local"]
    assert response["degraded"] == ["neighbors"]
    assert codes(response) == {"TIMEOUT"}


def test_a_hung_publisher_still_gets_an_explicit_crossings_whole_timeout(tmp_path, short_socket):
    _, storage = real_receiver(tmp_path, 'default_context = "other/place"', "timeout_s = 1.5", sock=short_socket)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(short_socket))
    server.listen(4)
    try:
        begun = time.monotonic()
        response = attach_explicit(tmp_path, storage)
        took = time.monotonic() - begun
    finally:
        server.close()
    assert took >= 1.4
    assert codes(response) == {"TIMEOUT"}


def test_a_stopped_daemon_keeps_local_results_and_names_it(tmp_path, short_socket):
    _, storage = real_receiver(tmp_path, f'default_context = "{CONTEXT}"', sock=short_socket)
    begun = time.monotonic()
    response = attach_default(tmp_path, storage)
    assert time.monotonic() - begun < 0.5
    assert response["results"] == ["local"]
    assert response["degraded"] == ["neighbors"]
    assert codes(response) == {"UNAVAILABLE"}


def test_an_expired_receiver_rule_is_named_on_a_default_crossing(tmp_path, short_socket):
    instance, storage = real_receiver(tmp_path, f'default_context = "{CONTEXT}"', sock=short_socket)
    policy(instance / "policy.json", valid_until="2026-02-01T00:00:00Z")
    response = attach_default(tmp_path, storage)
    assert response["degraded"] == ["neighbors"]
    assert response["neighbors"]["diagnostics"][0]["code"] == "OUTSIDE_VALIDITY"


# ---------------------------------------------------------------- the tool, and who doesn't cross

def test_recall_with_no_context_takes_the_default_path(engram_server_env, monkeypatch):
    server = engram_server_env
    seed(2)
    seen = {}

    def default(response, **kw):
        seen.update(kw)
        response["neighbors"] = {"by_default": True}
    monkeypatch.setattr(neighbors, "attach_default", default)
    result = server.recall("rivers", uninvited=0)
    assert result["neighbors"] == {"by_default": True}
    assert seen["query"] == "rivers" and seen["purpose"] == "session-recall"
    assert "context_id" not in seen


def test_recall_naming_a_context_doesnt_take_the_default_path(engram_server_env, monkeypatch):
    """These fakes record and the test looks afterwards: the seam's `except Exception` would swallow an assert in them."""
    server = engram_server_env
    seed(2)
    asked, defaulted = [], []
    monkeypatch.setattr(neighbors, "attach_default", lambda response, **kw: defaulted.append(kw))
    monkeypatch.setattr(neighbors, "attach_neighbors", lambda response, **kw: asked.append(kw["context_id"]))
    assert server.recall("rivers", uninvited=0, lighthouse_context=CONTEXT)["results"]
    assert asked == [CONTEXT] and defaulted == []


def test_a_failure_on_the_default_path_keeps_the_local_recall(engram_server_env, monkeypatch):
    server = engram_server_env
    seed(2)

    def fail(*a, **kw): raise RuntimeError("bad neighbor")
    monkeypatch.setattr(neighbors, "attach_default", fail)
    result = server.recall("rivers", uninvited=0)
    assert result["results"]
    assert "neighbors" in result["degraded"]


def test_instinct_only_recall_doesnt_take_the_default_path(engram_server_env, monkeypatch):
    server = engram_server_env
    defaulted = []
    monkeypatch.setattr(neighbors, "attach_default", lambda response, **kw: defaulted.append(kw))
    result = server.recall("rivers", layer="instinct")
    assert defaulted == [] and "neighbors" not in result and "degraded" not in result


@pytest.mark.parametrize("hook", ["wake.py", "nudge.py", "sleep.py"])
def test_hooks_make_no_neighbor_call(hook):
    text = (ENGRAM / "hooks" / hook).read_text()
    assert "attach_default" not in text and "attach_neighbors" not in text and "neighbor_arm" not in text


# ---------------------------------------------------------------- superyak-runtime status

def runtime_module():
    spec = importlib.util.spec_from_file_location("superyak_runtime_for_test", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_keeps_the_same_key_list_as_the_receiver():
    """runtime.py is standard library only, so it can't import this list, and an unlisted key reads a working
    receiver as invalid."""
    assert runtime_module().RECEIVER_KEYS == receiver_config.SETTINGS_KEYS


def status_of(tmp_path, *lines):
    instance, _ = real_receiver(tmp_path, *lines)
    return runtime_module()._receiver_status(instance, datetime(2026, 11, 4, tzinfo=timezone.utc))


def test_status_reports_the_key_when_set(tmp_path):
    status, _, errors = status_of(tmp_path, f'default_context = "{CONTEXT}"')
    assert status["state"] == "enabled" and errors == []
    assert status["default_context"] == CONTEXT


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_status_calls_a_toml_path_that_is_no_file_invalid_as_a_recall_does(tmp_path, kind):
    instance, _ = real_receiver(tmp_path)
    path = instance / "lighthouse-receiver.toml"
    path.unlink()
    path.mkdir() if kind == "directory" else os.mkfifo(path)
    status, _, errors = runtime_module()._receiver_status(instance, datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert status["state"] == "invalid" and errors


def test_status_with_no_toml_stays_disabled(tmp_path):
    instance, _ = real_receiver(tmp_path)
    (instance / "lighthouse-receiver.toml").unlink()
    status, _, errors = runtime_module()._receiver_status(instance, datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert status["state"] == "disabled" and errors == []


def test_status_raises_no_error_when_absent(tmp_path):
    status, _, errors = status_of(tmp_path)
    assert status["state"] == "enabled" and errors == []
    assert "default_context" not in status


@pytest.mark.parametrize("value", ['7', '""', '"../up"', '"a b"', '"memory//technical"', '"' + "x" * 600 + '"'])
def test_status_calls_a_bad_value_invalid_as_the_receiver_does(tmp_path, value):
    status, _, errors = status_of(tmp_path, f"default_context = {value}")
    assert status["state"] == "invalid"
    assert errors == ["receiver configuration is invalid"]


@pytest.mark.parametrize("value", ["memory/technical", "a", "a.b-c_d/e", "x" * 64 + "/y", "/x", "x/", "a//b", "a b", "../up",
                                   "." + "x", "é", "x" * 65, "/".join(["a"] * 300)])
def test_status_and_the_receiver_agree_on_every_value(tmp_path, value):
    try:
        receiver_config.context_ref(value)
        accepted = True
    except ValueError:
        accepted = False
    assert runtime_module()._valid_context(value) is accepted
