"""A failed lazy read anywhere in a frame: nothing served under enforce, legacy under shadow (P 5.6, 12.2; SH-4B)."""
import logging

import pytest

import lighthouse_daemon
import permissions
from permission_ledger import LedgerUnreadable, LogTimes, StateRows
from tests.permissions_support import M1, M1_ITEM, enforce_daemon, shadow_daemon


class Armed:
    """Lazy readers that fail once ``armed`` is set; each test arms them at the point a frame first touches them."""
    on = False


def _fail(kind):
    def fail(self, *a, **k):
        if Armed.on:
            raise LedgerUnreadable(f"the permission ledger's {kind} could not be read: disk I/O error")
        return original[kind](self, *a, **k)
    return fail


original = {"rows": StateRows._query, "log": LogTimes._query}


def _arm_at(monkeypatch, owner, name):
    """Arm the failing readers on entry to ``owner.name``."""
    Armed.on = False
    monkeypatch.setattr(StateRows, "_query", _fail("rows"))
    monkeypatch.setattr(LogTimes, "_query", _fail("log"))
    real = getattr(owner, name)

    def wrapper(*a, **k):
        Armed.on = True
        return real(*a, **k)
    monkeypatch.setattr(owner, name, wrapper)


POINTS = [
    pytest.param(permissions, "agent_place_at", id="agent_place_at"),
    pytest.param(permissions, "eligible_set", id="eligible_set"),
    pytest.param(lighthouse_daemon._LedgerSide, "recall_set", id="recall_set"),
    pytest.param(lighthouse_daemon._LedgerSide, "read_item", id="read_item"),
]


@pytest.fixture(autouse=True)
def _disarm():
    yield
    Armed.on = False


@pytest.mark.parametrize("owner,name", POINTS)
def test_enforce_recall_serves_nothing_with_a_warning(tmp_path, monkeypatch, caplog, owner, name):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=True)
    _arm_at(monkeypatch, owner, name)
    with caplog.at_level(logging.WARNING):
        reply = d.recall()
    if name == "read_item":
        return                                            # a read-only point: the recall never reaches it
    assert reply["candidates"] == []
    assert "permission ledger" in caplog.text


@pytest.mark.parametrize("owner,name", POINTS)
def test_enforce_read_serves_null_content_with_a_warning(tmp_path, monkeypatch, caplog, owner, name):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=True)
    _arm_at(monkeypatch, owner, name)
    with caplog.at_level(logging.WARNING):
        item = d.read(M1_ITEM)
    if name in ("recall_set", "eligible_set"):
        return                                            # recall-only points
    assert item["content"] is None and item["audiences"] == [] and "permission" not in item
    assert "permission ledger" in caplog.text


@pytest.mark.parametrize("owner,name", POINTS)
def test_shadow_answers_as_the_legacy_path_does(tmp_path, monkeypatch, caplog, owner, name):
    d = shadow_daemon(tmp_path, legacy_allows=True, ledger_allows=False)
    legacy_ids = {c["memoryId"] for c in shadow_daemon(tmp_path / "ref", legacy_allows=True,
                                                       ledger_allows=False).recall()["candidates"]}
    assert legacy_ids
    _arm_at(monkeypatch, owner, name)
    with caplog.at_level(logging.WARNING):
        assert {c["memoryId"] for c in d.recall()["candidates"]} == legacy_ids
        item = d.read(M1_ITEM)
    assert item["content"] and "permission" not in item


def test_a_failure_in_one_read_item_does_not_error_the_frame_under_enforce(tmp_path, monkeypatch):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=True)
    _arm_at(monkeypatch, lighthouse_daemon._LedgerSide, "read_item")
    assert d.read(M1_ITEM)["content"] is None


def test_the_cli_refuses_naming_the_ledger_when_a_lazy_read_fails(tmp_path, monkeypatch, capsys):
    import permission_cli
    from permission_ledger import Ledger
    enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=True)
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setattr(StateRows, "_query", _fail("rows"))
    monkeypatch.setattr(LogTimes, "_query", _fail("log"))
    real_state = Ledger.state

    def state_then_fail(self, *a, **k):         # the State is built; every read after it is lazy
        got = real_state(self, *a, **k)
        Armed.on = True
        return got
    monkeypatch.setattr(Ledger, "state", state_then_fail)
    for argv in [["explain", "--agent", "agent:engram", "--place", "place:home/andy",
                                       "--object", M1, "--copy", "store:x", "--action", "recall",
                                       "--purpose", "p"]]:
        Armed.on = False
        code = permission_cli.main(argv)
        err = capsys.readouterr().err
        assert code != 0 and "ledger" in err and "could not be read" in err, (argv, err)


def _subjects_fail(monkeypatch):
    def fail(*a, **k):
        raise LedgerUnreadable("the permission ledger's rows could not be read: disk I/O error")
    monkeypatch.setattr(permissions, "subjects_of", fail)       # the receipts' last lazy read, in a recall or a read


def test_a_failed_read_while_naming_the_subjects_of_a_recall_receipt(tmp_path, monkeypatch, caplog):
    _subjects_fail(monkeypatch)
    with caplog.at_level(logging.WARNING):
        assert enforce_daemon(tmp_path / "e").recall()["candidates"] == []
    assert "permission ledger" in caplog.text
    assert shadow_daemon(tmp_path / "s", legacy_allows=True, ledger_allows=False).recall()["candidates"]


def test_a_failed_read_while_naming_the_subjects_of_an_item_receipt(tmp_path, monkeypatch):
    _subjects_fail(monkeypatch)
    assert enforce_daemon(tmp_path / "e").read(M1_ITEM)["content"] is None
    assert shadow_daemon(tmp_path / "s", legacy_allows=True, ledger_allows=False).read(M1_ITEM)["content"]
