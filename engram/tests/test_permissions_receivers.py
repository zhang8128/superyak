"""Task 22: the receivers accept, pass and show the daemon's permission annotation (P 11, 12.1)."""
from copy import deepcopy
import re

import pytest

import neighbors
from lighthouse_client import NeighborUnavailable, validate_read
from lighthouse_protocol import content_digest
from lighthouse_receipts import validate_receipt
from tests.test_lighthouse_client import ALLOW, read_item, read_reply, selected
from tests.test_neighbors import CONTEXT, NOW, Log, policy
from permissions import annotation_line

RECEIPT = "u-5e21a9c0" + "0" * 24
PERMISSION_OBJ = {
    "laid_by": "andy (engram)",
    "allowed_by": [{"place": "place:home/andy", "records": ["r-7f3a" + "0" * 20]},
                   {"place": "place:la-county", "records": ["r-0b9e" + "0" * 20]}],
    "until": "2027-01-31T00:00:00Z", "receipt": RECEIPT,
}
CONTENT = "Shared bridge note: allergy to penicillin."


def reply_with(**changes):
    item = read_item()
    for key, value in changes.items():
        item["permission" if key == "permission" else key] = value
    return read_reply([item])


def test_u9_the_client_accepts_permission_and_still_rejects_any_other_member():
    [got] = validate_read(reply_with(permission=PERMISSION_OBJ), selected=[selected()])
    assert got["permission"] == PERMISSION_OBJ
    [plain] = validate_read(read_reply(), selected=[selected()])
    assert "permission" not in plain
    for bad in [reply_with(extra=1), reply_with(permission={**PERMISSION_OBJ, "x": 1}),
                reply_with(permission={k: v for k, v in PERMISSION_OBJ.items() if k != "until"}),
                reply_with(permission={**PERMISSION_OBJ, "receipt": 5}),
                reply_with(permission={**PERMISSION_OBJ, "allowed_by": [{"place": "p"}]}),
                reply_with(permission="a line")]:
        with pytest.raises(NeighborUnavailable):
            validate_read(bad, selected=[selected()])


def test_a_refused_item_with_a_permission_member_is_still_skipped():
    reply = read_reply([read_item(content=None, audiences=[], permission=PERMISSION_OBJ)])
    assert validate_read(reply, selected=[selected()]) == []


@pytest.fixture
def crossing_with_ledger(tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    policy(path)
    names = ["place:" + "x" * 60 + str(i) for i in range(8)]
    permission = {**PERMISSION_OBJ, "laid_by": "a" * 50,
                  "allowed_by": [{"place": n, "records": ["r-%08x" % i + "0" * 16]} for i, n in enumerate(names)]}

    def call(self, frame, *, deadline=None):
        if frame["kind"] == "recall":
            return dict(protocolVersion="0.1", kind="recall_result", turnId="publisher-turn",
                        queryDigest=content_digest(frame["query"]), context=frame["context"],
                        candidates=[dict(memoryId="m1", rank=1, layer="episode", lane="personal",
                                         audiences=["commons"], contentDigest=content_digest(CONTENT))],
                        decision=ALLOW, disclosureId="d1")
        return dict(protocolVersion="0.1", kind="read_result", disclosureId="d2", items=[
            dict(memoryId="m1", content=CONTENT, audiences=["commons"], decision=ALLOW,
                 permission=deepcopy(permission))])
    monkeypatch.setattr(neighbors.LighthouseClient, "call", call)
    return dict(query="q", context=deepcopy(CONTEXT), purpose="session-recall", k=1, storage=Log(),
                session_id="s", recall_id="t", receiver="engram", publishers=["why"],
                socket_path=tmp_path / "s.sock", policy_path=path, now=lambda: NOW), permission


def test_u10_permission_reaches_each_delivered_item_as_one_line(crossing_with_ledger):
    args, _ = crossing_with_ledger
    out = neighbors.neighbor_arm(**args)
    for item in out["delivered"]:
        assert isinstance(item["permission"], str) and len(item["permission"]) <= 240
        assert "\n" not in item["permission"] and re.search(r"receipt #[0-9a-f]{8}$", item["permission"])
    assert "…" in out["delivered"][0]["permission"] and re.search(r"\+\d+", out["delivered"][0]["permission"])


def test_u10_the_recall_receipt_validates_with_the_engram_permissions_extension(crossing_with_ledger):
    args, permission = crossing_with_ledger
    neighbors.neighbor_arm(**args)
    receipt = args["storage"].entries[0]["context"]["receipt"]
    validate_receipt(receipt)
    ext = receipt["extensions"]["engram:permissions"]
    assert set(ext) == {"receipts", "records"}
    assert ext["receipts"] == [RECEIPT]
    assert ext["records"] == sorted(r for e in permission["allowed_by"] for r in e["records"])


@pytest.fixture
def context_crossing(tmp_path, monkeypatch):
    from context_lighthouse import LighthouseSource
    from context_store import ContextStore
    instance = tmp_path / '.engram' / 'instances' / 'engram'
    instance.mkdir(parents=True)
    (instance / 'graph.db').touch()
    (instance / 'lighthouse-receiver.toml').write_text(
        'enabled = true\npublishers = ["why"]\nsocket_path = "s.sock"\npolicy_path = "policy.json"\n')
    policy(instance / 'policy.json')
    state = {"reads": 0, "refuse": False}

    def call(self, frame, *, deadline=None):
        if frame["kind"] == "recall":
            return dict(protocolVersion="0.1", kind="recall_result", turnId="publisher-turn",
                        queryDigest=content_digest(frame["query"]), context=frame["context"],
                        candidates=[dict(memoryId="m1", rank=1, layer="episode", lane="personal",
                                         audiences=["commons"], contentDigest=content_digest(CONTENT))],
                        decision=ALLOW, disclosureId="d1")
        state["reads"] += 1
        receipt = "u-%08x" % state["reads"] + "0" * 24
        item = dict(memoryId="m1", content=CONTENT, audiences=["commons"], decision=ALLOW,
                    permission={**PERMISSION_OBJ, "receipt": receipt})
        if state["refuse"]:
            item.update(content=None, audiences=[])
            del item["permission"]
        return dict(protocolVersion="0.1", kind="read_result", disclosureId="d2", items=[item])
    monkeypatch.setattr(neighbors.LighthouseClient, "call", call)
    store = ContextStore(tmp_path / 'context.db')
    source = LighthouseSource(store, receiver='engram', instance_dir=instance,
                              context_id='memory/technical', purpose='session-recall')
    yield source, state
    store.close()


def test_u10_the_context_runtime_evidence_carries_it(context_crossing):
    from context_lighthouse import _version
    source = context_crossing[0].for_turn('t', 'turn')
    [candidate] = source.search("allergy", limit=1)
    line = candidate.representations[0]
    assert re.search(r"receipt #[0-9a-f]{8}", line) and "laid by andy (engram)" in line
    assert line.count(annotation_line(PERMISSION_OBJ)[:20]) >= 1
    plain = {k: v for k, v in source.entries[candidate.id]["item"].items() if k != "permission"}
    assert _version(plain) == candidate.version


def test_evidence_turns_an_object_into_its_line_and_keeps_a_string():
    from context_lighthouse import _evidence
    base = {"publisher": "p", "memoryId": "m", "layer": "episode", "lane": "personal",
            "audiences": ["commons"], "contentDigest": {}, "content": "c"}
    assert annotation_line(PERMISSION_OBJ) in _evidence({**base, "permission": PERMISSION_OBJ})
    assert "a line" in _evidence({**base, "permission": "a line"})
    assert "permission" not in _evidence(base)


def test_mf1_a_candidate_with_a_permission_line_survives_prepare_dispatch(context_crossing):
    source, state = context_crossing; source = source.for_turn('t', 'turn')
    [candidate] = source.search("allergy", limit=1)
    before = state["reads"]
    invalid, info = source.prepare_dispatch([candidate], "0" * 64)
    assert invalid == set() and info["invalidated_ids"]  == []
    assert state["reads"] == before + 1


def test_mf1_a_re_read_that_is_now_refused_still_drops_the_candidate(context_crossing):
    source, state = context_crossing; source = source.for_turn('t', 'turn')
    [candidate] = source.search("allergy", limit=1)
    state["refuse"] = True
    invalid, _ = source.prepare_dispatch([candidate], "0" * 64)
    assert invalid == {candidate.id}
