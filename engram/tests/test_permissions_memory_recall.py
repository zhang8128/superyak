"""A recall returns at most 20 candidates, whatever k the frame asks for (SH-14; P 12.2, 15)."""
import json

from lighthouse_protocol import recall_frame
from tests.permissions_support import (DAEMON_RECEIVER, HOUSE_NAME, _daemon_frame_kwargs, _daemon_over,
                                       daemon_ledger, make_placed_house, receipt_rows, write_receiver_files)
from tests.test_lighthouse_daemon import NOW


def _recall(tmp_path, k, n=50):
    pub = make_placed_house(tmp_path, ns=range(1, n + 1))
    daemon_ledger(tmp_path, "enforce")
    write_receiver_files(tmp_path, DAEMON_RECEIVER)
    daemon = _daemon_over(tmp_path, [pub])
    frame = recall_frame(**_daemon_frame_kwargs(HOUSE_NAME), query="m", k=k, at=NOW)
    return daemon.handle_frame(frame)


def test_a_recall_returns_at_most_20(tmp_path):
    reply = _recall(tmp_path, 50)
    assert reply["kind"] == "recall_result"
    assert len(reply["candidates"]) == 20
    [row] = receipt_rows(tmp_path, action="recall")
    assert len(json.loads(row["returned"])) == 20


def test_a_small_k_returns_as_it_does_today(tmp_path):
    reply = _recall(tmp_path, 5)
    assert len(reply["candidates"]) == 5
