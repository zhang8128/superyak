"""The daemon's decisions, receipts and annotation (P 11, 12.2; Task 20)."""
import json

import pytest

from permission_ledger import Ledger, ledger_path
from permissions import (ANNOTATION_CHARS, MAX_PLACEMENTS, annotation, annotation_line, receipt_short, short_id)
from tests.permissions_support import (
    M1, M1_ID, M1_ITEM, M3_ITEM, M3_TEXT, SHARED_ID, T, at, daemon_with_no_ledger, e1_daemon_at, enforce_daemon,
    house_before_029, make_uses_file_unwritable, raised_daemon, read, receipt_rows, recall, remove_receiver_settings,
    shadow_daemon, spy_on_retrieve, write_receiver_policy,
)


def test_u9_enforce_needs_both_decisions(tmp_path):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=False)
    assert d.read(M1_ITEM)["content"] is None
    d = enforce_daemon(tmp_path / "b", legacy_allows=False, ledger_allows=True)
    assert d.read(M1_ITEM)["content"] is None
    d = enforce_daemon(tmp_path / "c", legacy_allows=True, ledger_allows=True)
    assert d.read(M1_ITEM)["content"]


def test_u9_shadow_delivers_by_the_legacy_path_and_records_both(tmp_path):
    d = shadow_daemon(tmp_path, legacy_allows=True, ledger_allows=False)
    item = d.read(M1_ITEM)
    assert item["content"] and "permission" not in item
    [row] = receipt_rows(tmp_path, action="inject_context")
    assert row["shadow"] == 1 and row["allowed"] == 0
    assert any(c["kind"] == "legacy" for c in json.loads(row["cited"]))
    d = shadow_daemon(tmp_path / "ok", legacy_allows=True, ledger_allows=True)
    assert d.read(M1_ITEM)["permission"]                      # R9: both allow, so the item is annotated
    assert receipt_rows(tmp_path / "ok")[-1]["shadow"] == 1


def test_u9_the_ledger_bytes_are_unchanged_and_total_changes_is_0(tmp_path, monkeypatch):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=True)
    changes, close = [], Ledger.close
    monkeypatch.setattr(Ledger, "close", lambda self: (changes.append(self.conn.total_changes), close(self))[1])
    before = ledger_path(tmp_path).read_bytes()
    d.recall()
    d.read(M1_ITEM)
    assert ledger_path(tmp_path).read_bytes() == before and changes and sum(changes) == 0


def test_u9_a_frame_at_in_the_future_extends_nothing(tmp_path):
    d, _ = e1_daemon_at(tmp_path, T("2027-01-31"))            # R1 ends here
    assert d.read(M1_ITEM, frame_at="2026-12-01T00:00:00Z")["content"] is None
    d, _ = e1_daemon_at(tmp_path / "b", T("2026-11-02"))
    assert d.read(M1_ITEM, frame_at="2030-01-01T00:00:00Z")["content"]


def test_u9_refused_copies_never_appear_among_candidates(tmp_path, monkeypatch):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows_only={M1})   # m2 and m3 placed, both refused
    ranked = spy_on_retrieve(monkeypatch, d)
    reply = d.recall(query=M3_TEXT, k=5)                      # the query that would rank m3 first
    assert {c["memoryId"] for c in reply["candidates"]} == {M1_ID}
    assert ranked[-1] == frozenset({M1_ID})                   # refused before ranking, not dropped after it
    [row] = receipt_rows(tmp_path, action="recall")
    assert json.loads(row["returned"]) == [M1] and row["filtered"] == 2 and row["shadow"] == 0


def test_a_shadow_recall_ranks_every_copy_and_records_what_it_would_filter(tmp_path, monkeypatch):
    d = shadow_daemon(tmp_path, legacy_allows=True, ledger_allows_only={M1})
    ranked = spy_on_retrieve(monkeypatch, d)
    assert len(d.recall(query=M3_TEXT, k=5)["candidates"]) == 3 and ranked[-1] is None
    [row] = receipt_rows(tmp_path, action="recall")
    assert row["shadow"] == 1 and row["filtered"] == 2


def test_e1_cited_holds_the_publishers_and_the_receivers_legacy_layers(tmp_path):
    d, ids = e1_daemon_at(tmp_path, T("2026-11-02"))
    d.read(M1_ITEM)
    [row] = receipt_rows(tmp_path, action="inject_context")
    assert {c["layer"] for c in json.loads(row["cited"]) if c["kind"] == "legacy"} == {"publisher", "receiver"}
    remove_receiver_settings(tmp_path, "ph-coordinator")
    assert d.read(M1_ITEM)["content"] is None                 # with no receiver policy its legacy layer refuses


def test_rs1_the_publishers_layer_answers_each_action_with_the_frames_one_decision(tmp_path):
    d, ids = e1_daemon_at(tmp_path, T("2026-11-02"))
    item = d.read(M1_ITEM)
    assert item["content"] and item["permission"]             # E1's use 1 is delivered: inject_context never asked
    [row] = receipt_rows(tmp_path, action="inject_context")
    publisher = [c for c in json.loads(row["cited"]) if c["kind"] == "legacy" and c["layer"] == "publisher"]
    assert {(c["action"], c["verdict"]) for c in publisher} == {(x, "allow") for x in ("recall", "read",
                                                                                       "inject_context")}
    write_receiver_policy(tmp_path, "ph-coordinator", actions=["recall", "read"])   # the receiver drops inject_context
    assert d.read(M1_ITEM)["content"] is None                 # the receiver's layer answers per action
    row = receipt_rows(tmp_path, action="inject_context")[-1]
    assert json.loads(row["refusal"]) == {"code": "LEGACY_DENY", "layer": "receiver", "action": "inject_context"}


def test_r27_a_house_without_029_serves_nothing_under_shadow_and_enforce_and_warns(tmp_path, caplog):
    for mode in ("shadow", "enforce"):
        d, pub = raised_daemon(tmp_path / mode, mode=mode, house=house_before_029)
        assert d.handle_frame(recall(pub))["candidates"] == []
        assert all(i["content"] is None for i in d.handle_frame(read(pub, SHARED_ID))["items"])
        assert "029" in caplog.text and pub in caplog.text
    d, pub = daemon_with_no_ledger(tmp_path / "off", house=house_before_029)
    assert d.handle_frame(recall(pub))["candidates"]          # off: as today
    assert [i["content"] is not None for i in d.handle_frame(read(pub, SHARED_ID))["items"]] == [True]


def test_u9_a_refused_read_item_has_null_content_empty_audiences_and_no_permission(tmp_path):
    item = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=False).read(M3_ITEM)
    assert item["content"] is None and item["audiences"] == [] and "permission" not in item
    assert set(item["decision"]) == {"effect", "ruleId", "code"}


def test_e1_use_1_annotation_line(tmp_path):
    d, ids = e1_daemon_at(tmp_path, T("2026-11-02"))
    item = d.read(M1_ITEM)
    line = annotation_line(item["permission"])
    assert line == (f"laid by andy (engram) · allowed by home/andy {short_id(ids.R1)}, la-county {short_id(ids.C1)}, "
                    f"public-health {short_id(ids.H1)}, clinic-3 {short_id(ids.L1)} · until 2027-01-31 · "
                    f"receipt {receipt_short(ids.last_receipt())}")
    assert item["permission"]["until"] == "2027-01-31T00:00:00Z"
    assert item["permission"]["receipt"] == ids.last_receipt()
    assert [(a["place"], a["records"]) for a in item["permission"]["allowed_by"]] == [
        ("place:home/andy", [ids.R1]), ("place:la-county", [ids.C1]), ("place:la-county/public-health", [ids.H1]),
        ("place:la-county/public-health/clinic-3", [ids.L1])]


def test_a_receipt_names_the_object_the_copy_the_subjects_and_the_digest(tmp_path):
    d, ids = e1_daemon_at(tmp_path, T("2026-11-02"))
    d.read(M1_ITEM)
    d.read(M3_ITEM)
    allowed, refused = receipt_rows(tmp_path, action="inject_context")
    assert allowed["object"] == M1 and allowed["copy"] == "store:HOUSE" and allowed["allowed"] == 1
    assert allowed["agent"] == "agent:ph-coordinator" and allowed["shadow"] == 0 and allowed["content_digest"]
    assert allowed["ledger_id"] and allowed["ledger_seq"] > 0
    assert refused["allowed"] == 0 and refused["content_digest"] is None


def test_the_annotation_line_truncates_long_names_and_drops_from_the_end():
    def obj(places, laid_by="andy (engram)", until=None):
        return {"laid_by": laid_by, "allowed_by": [{"place": p, "records": ["r-" + "ab12" * 8]} for p in places],
                "until": until, "receipt": "u-" + "cd34" * 8}
    long_name = "x" * 40
    line = annotation_line(obj([f"place:la-county/{long_name}"], laid_by="y" * 40))
    assert "y" * 31 + "…" in line and "y" * 32 not in line and "x" * 31 + "…" in line
    assert line == (f"laid by {'y' * 31}… · allowed by {'x' * 31}… #ab12 · receipt #cd34cd34")
    short = annotation_line(obj(["place:home/andy", "place:la-county"]))
    assert short == "laid by andy (engram) · allowed by home/andy #ab12, la-county #ab12 · receipt #cd34cd34"
    many = obj([f"place:la-county/p{i:02d}-" + "z" * 20 for i in range(30)], until="2027-01-31T00:00:00Z")
    line = annotation_line(many)
    assert len(line) <= ANNOTATION_CHARS and "+" in line.split(" · ")[1].split(", ")[-1]
    kept = line.split(" · ")[1].removeprefix("allowed by ").split(", ")
    assert kept[0].startswith("p00-") and kept[-1] == f"+{30 - (len(kept) - 1)}"
    assert line.endswith("until 2027-01-31 · receipt #cd34cd34")
    twin = annotation_line(obj(["place:la-county/clinic", "place:other/clinic"]))
    assert "la-county/clinic #ab12, other/clinic #ab12" in twin


def test_rf1_no_receipt_no_content(tmp_path, caplog):
    d = enforce_daemon(tmp_path, legacy_allows=True, ledger_allows=True)
    make_uses_file_unwritable(tmp_path)
    assert d.read(M1_ITEM)["content"] is None and "receipt" in caplog.text
    assert d.recall()["candidates"] == []                     # a recall with no receipt returns nothing
    s = shadow_daemon(tmp_path / "s", legacy_allows=True, ledger_allows=True)
    make_uses_file_unwritable(tmp_path / "s")
    assert s.read(M1_ITEM)["content"] and s.recall()["candidates"]    # shadow: the legacy path, with a warning


def _serves_once_its_set_is_built(d, pub):
    """A frame that finds the eligible set still building serves nothing, and rightly (P 12.2): the build goes on
    in its own thread past the frame's wait. So ask once to start it, wait for it to finish, and ask again."""
    from tests.permissions_support import wait_for_builds
    d.handle_frame(recall(pub))
    wait_for_builds(d)
    return d.handle_frame(recall(pub))["candidates"]


def _the_bound_cases(tmp_path, caplog):
    d, pub = raised_daemon(tmp_path / "over", mode="enforce", placements=MAX_PLACEMENTS + 1)
    assert d.handle_frame(recall(pub))["candidates"] == []
    assert all(i["content"] is None for i in d.handle_frame(read(pub, SHARED_ID))["items"])
    assert "20,000" in caplog.text and pub in caplog.text
    assert "eligible set building" not in caplog.text        # the bound refused it, not a build still under way
    assert not d._builds and not d._build_threads            # over the bound no set is ever built
    d, pub = raised_daemon(tmp_path / "at", mode="enforce", placements=MAX_PLACEMENTS)
    assert _serves_once_its_set_is_built(d, pub)             # at the bound it still serves
    d, pub = raised_daemon(tmp_path / "shadow", mode="shadow", placements=MAX_PLACEMENTS + 1)
    assert d.handle_frame(recall(pub))["candidates"]         # shadow: the legacy path decides (no build is waited on)


def test_more_than_20000_placements_serve_nothing_under_enforce(tmp_path, caplog):   # P 12.2, "Bounds"
    _the_bound_cases(tmp_path, caplog)


def test_the_bound_cases_hold_when_the_build_outlasts_the_frames_wait(tmp_path, monkeypatch, caplog):
    """The Pi at load 5-8: the set at the bound takes longer than REBUILD_WAIT_S (1 s) to build, so a frame asked
    at once serves nothing. The test waits for the build instead of assuming it is quick."""
    from tests.test_permissions_daemon_cache import _slow_eligible_set
    _slow_eligible_set(monkeypatch, delay=2.5)
    _the_bound_cases(tmp_path, caplog)


def _audience_refused(tmp_path, mode):
    """Ledger allows M1; the publisher's audience list for the receiver omits the item's audience."""
    d = (shadow_daemon if mode == "shadow" else enforce_daemon)(tmp_path)
    from tests.permissions_support import write_publisher_policy
    write_publisher_policy(tmp_path, receiver_audiences=["group:other"])
    return d


def test_shadow_receipt_keeps_the_ledgers_verdict_when_the_audience_path_refuses(tmp_path):
    d = _audience_refused(tmp_path, "shadow")
    item = d.read(M1_ITEM)
    assert item["content"] is None                            # the legacy path still decides delivery
    row = receipt_rows(tmp_path, action="inject_context")[-1]
    assert row["shadow"] == 1 and row["allowed"] == 1         # the ledger's verdict
    assert row["refusal"] is None                             # the ledger's own (final review M8)
    assert {"layer": "publisher", "kind": "audience", "action": "inject_context", "verdict": "deny",
            "record": None, "version": None} in json.loads(row["cited"])


def test_enforce_receipt_says_not_allowed_when_the_audience_path_refuses(tmp_path):
    d = _audience_refused(tmp_path, "enforce")
    assert d.read(M1_ITEM)["content"] is None
    row = receipt_rows(tmp_path, action="inject_context")[-1]
    assert row["shadow"] == 0 and row["allowed"] == 0
    assert json.loads(row["refusal"])["code"] == "LEGACY_DENY"


@pytest.mark.parametrize("mode", ["enforce", "shadow"])
def test_a_closed_gate_logs_its_cause_once_per_request(tmp_path, caplog, mode):
    from tests.permissions_support import delete_ledger, read as read_frame
    d, pub = raised_daemon(tmp_path, mode=mode)
    delete_ledger(tmp_path)
    for allowed in (True, False):
        if not allowed:
            write_receiver_policy(tmp_path, "ph-coordinator", actions=[])   # frame decision becomes deny
        caplog.clear()
        d.handle_frame(read_frame(pub, SHARED_ID))
        assert sum("gate closed" in r.getMessage() for r in caplog.records) == 1
