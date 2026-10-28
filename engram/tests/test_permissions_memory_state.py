"""state() reads no log body but place names, and log times on demand (SH-1; P 5.4, 5.6, 15)."""
import gc
import tracemalloc

import pytest

import permissions
from permission_ledger import Ledger, LedgerUnreadable
from tests.permissions_memory_support import add_records_by_sql, synthetic_ledger
from tests.permissions_support import ANDY, T, do, raised_daemon, recall

MB = 1 << 20


def _traced(fn):
    gc.collect()
    tracemalloc.start()
    try:
        out = fn()
        gc.collect()
        return out, tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()


def test_state_loads_no_log_body_but_place_names(tmp_path):
    synthetic_ledger(tmp_path, 0, log_rows=1000, body_bytes=64 * 1024)
    led = Ledger.open_read_only(tmp_path)
    try:
        _, (_, peak) = _traced(led.state)
    finally:
        led.close()
    assert peak < 8 * MB, f"state() peaked at {peak / MB:.1f} MB"


def test_state_holds_no_whole_log_index(tmp_path):
    synthetic_ledger(tmp_path, 0, log_rows=200_000)
    led = Ledger.open_read_only(tmp_path)
    try:
        state, (current, _) = _traced(led.state)
        assert current < 4 * MB, f"the State holds {current / MB:.1f} MB"
        assert state.seq == 200_000
        for s in (1, 2, 777, 65_537, 199_999, 200_000):
            assert state.seq_at[s] == 1_000_000 + s
            assert s in state.seq_at
        for s in (0, 200_001, -1):
            assert s not in state.seq_at
            with pytest.raises(KeyError):
                state.seq_at[s]
        early = led.state(10)
        assert [early.seq_at[s] for s in range(1, 11)] == [1_000_000 + s for s in range(1, 11)]
        with pytest.raises(KeyError):
            early.seq_at[11]
        assert 11 not in early.seq_at and len(early.seq_at) == 10
        assert list(early.seq_at) == list(range(1, 11))
    finally:
        led.close()


def test_the_reader_outlives_the_ledger_and_keeps_at_most_the_cap(tmp_path, monkeypatch):
    import permission_ledger
    monkeypatch.setattr(permissions, "STATE_LOG_TIMES", 4)
    synthetic_ledger(tmp_path, 0, log_rows=20)
    led = Ledger.open_read_only(tmp_path)
    state = led.state()
    led.close()
    assert [state.seq_at[s] for s in range(1, 21)] == [1_000_000 + s for s in range(1, 21)]
    assert len(state.seq_at._cache) <= 4
    assert dict(state.seq_at) == {s: 1_000_000 + s for s in range(1, 21)}


def test_place_names_still_come_from_the_log(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    try:
        do(led, ANDY, "register-place", place="place:la-county", parents=(), stewards=(ANDY,), name="LA County")
        seq = led.seq()
        do(led, ANDY, "register-place", place="place:la-county/clinic", parents=("place:la-county",),
           stewards=(ANDY,), name="Clinic 3")
        assert led.state().names["place:la-county/clinic"] == "Clinic 3"
        assert led.state().names["place:la-county"] == "LA County"
        early = led.state(seq)
        assert early.names["place:la-county"] == "LA County"
        assert "place:la-county/clinic" not in early.names
    finally:
        led.close()


def test_state_refuses_past_its_records(tmp_path, monkeypatch):
    synthetic_ledger(tmp_path, 0, records=True, log_rows=3)
    add_records_by_sql(tmp_path, 100)                       # 101 records
    monkeypatch.setattr(permissions, "MAX_RECORDS", 100)
    led = Ledger.open_read_only(tmp_path)
    try:
        with pytest.raises(Exception) as e:
            led.state()
    finally:
        led.close()
    text = str(e.value)
    assert "101" in text and "5.4" in text and "15" in text
    monkeypatch.setattr(permissions, "MAX_RECORDS", 101)
    led = Ledger.open_read_only(tmp_path)
    try:
        assert led.state().seq == 3
    finally:
        led.close()


def test_the_daemon_serves_nothing_past_the_records_bound(tmp_path, monkeypatch):
    daemon, pub = raised_daemon(tmp_path, mode="enforce")
    assert daemon.handle_frame(recall(pub))["candidates"]
    add_records_by_sql(tmp_path, 100)
    monkeypatch.setattr(permissions, "MAX_RECORDS", 100)
    assert daemon.handle_frame(recall(pub))["candidates"] == []



@pytest.mark.parametrize("mode,served", [("enforce", False), ("shadow", True)])
def test_a_failed_lazy_read_serves_nothing(tmp_path, monkeypatch, caplog, mode, served):
    import permission_ledger
    daemon, pub = raised_daemon(tmp_path, mode=mode)
    assert daemon.handle_frame(recall(pub))["candidates"]

    def broken(self, seq):
        raise LedgerUnreadable("the reader failed on its first row read")
    monkeypatch.setattr(permission_ledger.LogTimes, "_fetch", broken)
    # a new ledger row so that the daemon builds a fresh State (and a fresh reader)
    from permission_ledger import Ledger as L
    led = L.open(tmp_path)
    do(led, ANDY, "register-place", place="place:x", parents=(), stewards=(ANDY,), name="X")
    led.close()
    got = daemon.handle_frame(recall(pub))
    assert bool(got.get("candidates")) is served
    assert "the reader failed on its first row read" in caplog.text
