"""The imprint request route and its checks (spec I 7.1, 14; plan Task 24)."""
import stat

from fastapi.testclient import TestClient
import pytest

from superyak_peer import imprints
from superyak_peer.door import create_door
from superyak_peer.identity import canonical
from imprint_support import request_doc, station
from imprint_support import post


def test_routes_take_the_ships_key_and_the_door_has_none(tmp_path):
    st = station(tmp_path)
    assert st.voyager.post("/api/imprints", content=canonical(request_doc())).status_code == 201
    assert st.sam.post("/api/imprints", content=canonical(request_doc())).status_code == 403
    door = TestClient(create_door(tmp_path / "door"), base_url="http://testserver")
    assert door.post("/api/imprints", content=b"{}").status_code == 404


def test_routes_are_off_without_imprints_dir(tmp_path):
    st = station(tmp_path, imprints_dir=None)
    assert st.voyager.post("/api/imprints", content=canonical(request_doc())).status_code == 404
    assert st.voyager.get("/api/imprints").status_code == 404


@pytest.mark.parametrize("change", [
    {"imprint_id": "C0A8F5E2-0000-4000-8000-000000000000"}, {"imprint_id": "c0a8f5e2-0000-1000-8000-000000000000"},
    {"imprint_id": "../../etc"}, {"plan_digest": "9d3e"}, {"scope.until": "2026-10-25 18:00:00"},
    {"scope.until": None}, {"contents.episodes": 1.0}, {"contents.episodes": -1}, {"package.parts": 12},
    {"terms.audience": ["place:home/sam"]}, {"terms.days": 366}, {"contents.memory_log": 3, "terms.actions": ["imprint"]},
    {"contents.episodes": 99_999, "contents.semantics": 2}, {"extra": 1}, {"scope.lanes": ["work", "personal"]},
    {"others.memories": 1, "others.people": 1, "contents.imprint_subjects": 1},   # sam's copy to andy's home
    {"others.memories": 1, "others.people": 0}, {"others.people": 1.0}])
def test_each_format_refuses_a_bad_value(tmp_path, change):
    st = station(tmp_path)
    assert st.voyager.post("/api/imprints", content=canonical(request_doc(**change))).status_code == 400


def test_route_waits_for_trails(tmp_path, route_closed):
    """S1: no trails module ships yet, so a request with route is refused before anything is staged."""
    assert imprints.ROUTE_OPEN is False
    st = station(tmp_path)
    refused = post(st, request_doc())
    assert refused.status_code == 400 and "terms.actions" in refused.json()["error"]
    assert not (tmp_path / "peer" / "imprints").exists() or not any((tmp_path / "peer" / "imprints").iterdir())
    with st.store.transaction() as db:                                  # and no row either (the fresh review's N2)
        assert db.execute("SELECT count(*) FROM imprint_requests").fetchone()[0] == 0
    assert post(st, request_doc(route=False)).status_code == 201


def test_a_duplicate_imprint_id_and_the_limits(tmp_path, monkeypatch):
    st = station(tmp_path); doc = request_doc()
    assert post(st, doc).status_code == 201 and post(st, doc).status_code == 409
    assert post(st, request_doc(source_instance_id=doc["source_instance_id"])).status_code == 409     # D20
    monkeypatch.setattr(imprints, "free_bytes", lambda path: 5 * 2**30)
    assert post(st, request_doc(**{"package.bytes": 2**30, "package.parts": 256})).status_code == 507
    assert post(st, request_doc(**{"package.bytes": 2**31 + 1})).status_code == 400
    assert [post(st, request_doc()).status_code for _ in range(4)][-1] == 429                       # 4 open per ship


def test_the_request_lives_in_staging_and_a_ship_sees_its_owner(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    staged = tmp_path / "peer" / "imprints" / made["id"] / "request.json"
    assert stat.S_IMODE(staged.stat().st_mode) == 0o600 and b'"scope"' not in (tmp_path / "peer" / "peer.sqlite3").read_bytes()
    context = st.voyager.get("/api/imprints").json()
    assert (context["owner"], context["operator"]) == ("sam", "andy")


def test_the_operators_own_copy_may_carry_others(tmp_path):
    st = station(tmp_path)                                   # andy's own ship, serenity, sends to place:home/andy
    doc = request_doc(owner_ship="serenity", **{"others.memories": 2, "others.people": 2, "contents.imprint_subjects": 3})
    assert st.serenity.post("/api/imprints", content=canonical(doc)).status_code == 201


@pytest.mark.parametrize("change", [                       # the counts rule alone, on Andy's own request (the re-check's S5)
    {"others.memories": 0, "others.people": 0, "contents.imprint_subjects": 3},   # the reverse: rows with no count
    {"others.memories": 4, "others.people": 1, "contents.imprint_subjects": 3}])  # more memories than rows
def test_the_counts_rule_on_the_operators_own_request(tmp_path, change):
    st = station(tmp_path)
    assert st.serenity.post("/api/imprints", content=canonical(request_doc(owner_ship="serenity", **change))).status_code == 400


def test_the_answer_carries_the_code_and_the_row_keeps_only_its_hash(tmp_path):
    st = station(tmp_path); doc = request_doc()
    made = post(st, doc).json()
    assert made["confirm_url"] == f"http://testserver/#imprint?code={made['code']}" and len(made["code"]) == 8
    assert made["expires"] == int(st.clock[0]) + 600
    with st.store.transaction() as db:
        row = db.execute("SELECT * FROM imprint_requests WHERE id=?", (made["id"],)).fetchone()
    assert row["status"] == "requested" and row["code_hash"] and made["code"] not in tuple(row)
    assert (row["imprint_id"], row["expires"]) == (doc["imprint_id"], made["expires"])
    assert stat.S_IMODE((tmp_path / "peer" / "imprints" / made["id"]).stat().st_mode) == 0o700


def test_a_person_lists_only_the_imprints_of_their_ships_and_a_big_body_is_refused(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    mine = st.sam.get("/api/imprints").json()["imprints"]
    assert [row["id"] for row in mine] == [made["id"]] and mine[0]["status"] == "requested"
    assert st.jenn.get("/api/imprints").json() == {"imprints": []}
    assert st.voyager.post("/api/imprints", content=b" " * (64 * 1024 + 1)).status_code == 413
