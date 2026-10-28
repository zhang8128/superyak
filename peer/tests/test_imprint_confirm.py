"""The confirm view, the owner's yes and the signed permission (spec I 8, 9; plan Task 25)."""
import base64
import json
import uuid

from fastapi.testclient import TestClient

from superyak_peer import imprints
from superyak_peer.identity import INNER_RECORD_KEYS, RECORD_KEYS, canonical, verify_station_record
from superyak_peer.imprints import (CHECK_TEXT, CHECK_TEXT_AT_HOME, CHECK_TEXT_AT_HOME_NONE, OTHERS_AT_HOME_NONE_WORDS,
                                    OTHERS_AWAY_WORDS)
from imprint_support import request_doc, station, post

SAM_PASSWORD = "long-password-sam"
ANDY_PASSWORD = "long-password-andy"
ANCESTOR = str(uuid.uuid4())
DAY = 86400


def confirm(client, made, *, csrf=True, password=SAM_PASSWORD, attest=True):
    headers = {} if csrf else {"x-csrf-token": ""}
    return client.post(f"/api/imprints/{made['id']}/confirm", headers=headers,
                       json={"code": made["code"], "password": password, "attest": attest})


def row(st, request_id):
    with st.store.transaction() as db:
        found = db.execute("SELECT * FROM imprint_requests WHERE id=?", (request_id,)).fetchone()
        return dict(found)


def station_key(st):
    return base64.b64encode(st.store._station_identity().public_key).decode()


def made_with(st, doc, ship="voyager"):
    made = post(st, doc, ship).json()
    return made


def confirmed_permission(tmp_path, route=False):
    st = station(tmp_path)
    made = made_with(st, request_doc(route=route))
    assert confirm(st.sam, made).status_code == 200
    return json.loads(row(st, made["id"])["permission"])


def sorted_distinct(value):
    return value == "*" or (isinstance(value, list) and value == sorted(set(value)))


def outside_home_allow_ok(r):
    """The permissions spec's P 5.4 for an allow that leaves a home, as the tests write it: finite purposes, an end
    at most 366 days after the start, memories only by collection, roads and trails by a finite stores list, sorted
    distinct lists and integer times (P13, P14, P28)."""
    s, o = r["selector"], r["selector"]["objects"]
    times = [r[k] for k in ("valid_from", "valid_until", "anchor", "created")]
    if any(type(t) is not int for t in times) or not r["valid_from"] < r["valid_until"] <= r["valid_from"] + 366 * DAY:
        return False
    if not s["purposes"] or s["purposes"] == "*" or r["effect"] != "allow":
        return False
    for key in ("audience", "requesters", "actions", "purposes"):
        if not sorted_distinct(s[key]):
            return False
    if not isinstance(o["stores"], list) or not o["stores"] or not all(sorted_distinct(o[k]) for k in ("kinds", "stores")):
        return False
    if o["kinds"] == ["memory"]:
        return isinstance(o["collections"], list) and bool(o["collections"]) and o["memories"] == "*" and sorted_distinct(o["collections"])
    return o["kinds"] == ["road", "trail"] and (o["layers"], o["lanes"], o["collections"], o["memories"]) == ("*",) * 4


def test_only_the_ships_owner_sees_and_confirms(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    assert st.jenn.get(f"/api/imprints/code/{made['code']}").status_code == 404
    assert st.andy.get(f"/api/imprints/code/{made['code']}").status_code == 404
    assert confirm(st.jenn, made).status_code == 404 and confirm(st.sam, made).status_code == 200


def test_csrf_password_and_the_check_are_required(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    assert confirm(st.sam, made, csrf=False).status_code == 403
    assert confirm(st.sam, made, password="wrong").status_code == 401
    assert confirm(st.sam, made, attest=False).status_code == 400
    assert row(st, made["id"])["status"] == "requested"


def test_a_wrong_password_counts_toward_the_login_limits(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    for _ in range(8):
        confirm(st.sam, made, password="wrong")
    anonymous = TestClient(st.app, base_url="http://testserver"); anonymous.headers["origin"] = "http://testserver"
    assert anonymous.post("/api/login", json={"username": "sam", "password": SAM_PASSWORD}).status_code == 429


def test_a_code_confirms_only_its_own_request_and_counts_nothing_otherwise(tmp_path):
    """One request's code with another request's id is a 404 before the password is checked (review N3)."""
    st = station(tmp_path); first, second = post(st, request_doc()).json(), post(st, request_doc()).json()
    with st.store.transaction() as db:
        before = sorted(tuple(r) for r in db.execute("SELECT * FROM login_attempts"))
    crossed = st.sam.post(f"/api/imprints/{first['id']}/confirm",
                          json={"code": second["code"], "password": "wrong-wrong-wrong", "attest": True})
    assert crossed.status_code == 404
    with st.store.transaction() as db:
        assert sorted(tuple(r) for r in db.execute("SELECT * FROM login_attempts")) == before
    assert row(st, first["id"])["status"] == row(st, second["id"])["status"] == "requested"
    assert confirm(st.sam, second).status_code == 200 and row(st, first["id"])["status"] == "requested"


def test_the_code_is_single_use_and_expires(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    assert confirm(st.sam, made).status_code == 200 and confirm(st.sam, made).status_code == 404
    late = post(st, request_doc()).json(); st.clock[0] += 601
    assert confirm(st.sam, late).status_code == 404
    assert st.sam.get(f"/api/imprints/code/{late['code']}").status_code == 404


def test_the_permission_is_signed_in_the_confirming_transaction(tmp_path, monkeypatch):
    st = station(tmp_path); doc = request_doc(route=True); made = post(st, doc).json()
    assert confirm(st.sam, made).status_code == 200
    stored = row(st, made["id"])
    record = json.loads(stored["permission"])
    assert stored["status"] == "allowed" and stored["station_key"] == station_key(st) and stored["code_hash"] is None
    assert stored["expires"] == int(st.clock[0]) + 7 * DAY and stored["decided_by"] == st.ids["sam"]
    assert verify_station_record(station_key(st), record, stored["permission_signature"])
    assert set(record) == RECORD_KEYS["imprint-permission"] and all(set(r) == INNER_RECORD_KEYS for r in record["records"])
    assert record["attestation"] == "no-unconsented-others-v1" and record["id"] == made["id"]
    r_m, r_t = record["records"]
    assert r_m["selector"]["objects"]["collections"] == [f"collection:sam/imprint-{doc['imprint_id']}"]
    assert (r_m["selector"]["objects"]["layers"], r_m["selector"]["objects"]["lanes"]) == ("*", "*")
    assert r_m["selector"]["purposes"] == ["calibration", "trail-evaluation"]
    assert r_m["selector"]["actions"] == ["imprint", "read", "recall"] and r_t["selector"]["actions"] == ["imprint", "read", "recall", "route"]
    assert r_t["selector"]["objects"]["stores"] == [doc["source_instance_id"]] and r_t["selector"]["purposes"] == ["trail-evaluation"]
    assert r_m["valid_until"] == int(st.clock[0]) + 90 * DAY and r_m["reason"] == f"imprint {doc['imprint_id'][:4]} at Deep Space 9"
    assert r_m["id"].startswith("r-") and len(r_m["id"]) == 34 and r_m["id"] != r_t["id"]
    failing = post(st, request_doc()).json()
    identity = st.store._station_identity()
    real = identity.sign_record
    def explode_after_sign(record):
        real(record)
        raise RuntimeError("after the signature")
    monkeypatch.setattr(identity, "sign_record", explode_after_sign)
    broken = TestClient(st.app, base_url="http://testserver", raise_server_exceptions=False)
    broken.headers["origin"] = "http://testserver"
    login = broken.post("/api/login", json={"username": "sam", "password": SAM_PASSWORD}).json()
    broken.headers["x-csrf-token"] = login["csrf_token"]
    assert confirm(broken, failing).status_code == 500
    after = row(st, failing["id"])
    assert after["permission"] is None and after["status"] == "requested" and after["code_hash"] is not None


def test_a_route_less_request_has_one_record(tmp_path):
    record = confirmed_permission(tmp_path, route=False)
    assert len(record["records"]) == 1 and record["records"][0]["selector"]["purposes"] == ["calibration"]


def test_records_pass_the_outside_home_write_rules_as_written_from_p_5_4(tmp_path):
    record = confirmed_permission(tmp_path, route=True)
    assert len(record["records"]) == 2
    for r in record["records"]:
        assert outside_home_allow_ok(r)


def test_the_view_shows_every_field_but_kind_and_version(tmp_path):
    st = station(tmp_path); doc = request_doc(route=True, ancestry=[ANCESTOR]); made = post(st, doc).json()
    view = json.dumps(st.sam.get(f"/api/imprints/code/{made['code']}").json())
    for shown in (doc["imprint_id"][:4], made["id"][:4], doc["plan_digest"][:8], "the whole 64-character digest is sent",
                  ANCESTOR[:4], "lineage complete", "1204", "41.2 MiB", "the station's imprint agent, acting for andy",
                  "when either was last recalled", CHECK_TEXT, "Nothing is kept with no end.", "voyager", "test-host"):
        assert shown in view, shown
    assert doc["plan_digest"] not in view and "engram-imprint-request" not in view


def test_the_view_without_route_says_what_stays(tmp_path):
    st = station(tmp_path); made = post(st, request_doc(route=False)).json()
    view = json.dumps(st.sam.get(f"/api/imprints/code/{made['code']}").json())
    assert "stay on your machine" in view and "route over" not in view


def test_the_check_and_attestation_follow_where_the_copy_lives(tmp_path):
    st = station(tmp_path)
    home = st.serenity.post("/api/imprints", content=canonical(request_doc(owner_ship="serenity",
        **{"others.memories": 37, "others.people": 3, "contents.imprint_subjects": 40}))).json()
    view = json.dumps(st.andy.get(f"/api/imprints/code/{home['code']}").json())
    assert "37 of these memories have other people recorded on them (3 people)" in view and "patients" in view
    assert CHECK_TEXT not in view and "outside my home" in view
    assert confirm(st.andy, home, password=ANDY_PASSWORD).status_code == 200
    assert json.loads(row(st, home["id"])["permission"])["attestation"] == "others-copied-at-home-v1"
    away = post(st, request_doc()).json()
    view = json.dumps(st.sam.get(f"/api/imprints/code/{away['code']}").json())
    assert CHECK_TEXT in view and OTHERS_AWAY_WORDS in view and "recorded on them (" not in view
    confirm(st.sam, away)
    assert json.loads(row(st, away["id"])["permission"])["attestation"] == "no-unconsented-others-v1"


def test_both_home_texts_say_only_what_is_true(tmp_path):
    st = station(tmp_path)
    some = st.serenity.post("/api/imprints", content=canonical(request_doc(owner_ship="serenity",
        **{"others.memories": 37, "others.people": 3, "contents.imprint_subjects": 40}))).json()
    view = json.dumps(st.andy.get(f"/api/imprints/code/{some['code']}").json())
    assert CHECK_TEXT_AT_HOME.format(n=37, p=3) in view and CHECK_TEXT_AT_HOME_NONE not in view
    assert "They are copied on my yes alone, with no one else recorded on them." in view
    none = st.serenity.post("/api/imprints", content=canonical(request_doc(owner_ship="serenity"))).json()
    view = json.dumps(st.andy.get(f"/api/imprints/code/{none['code']}").json())
    assert CHECK_TEXT_AT_HOME_NONE in view and OTHERS_AT_HOME_NONE_WORDS in view
    assert "no one but me is recorded on them" in view and "co-subjects" not in view and "their yes" not in view
    assert confirm(st.andy, none, password=ANDY_PASSWORD).status_code == 200
    assert json.loads(row(st, none["id"])["permission"])["attestation"] == "others-copied-at-home-v1"


def test_decline_removes_staging_at_once_and_keeps_a_content_free_row(tmp_path):
    st = station(tmp_path); made = post(st, request_doc()).json()
    assert st.jenn.post(f"/api/imprints/{made['id']}/decline").status_code == 404
    assert st.sam.post(f"/api/imprints/{made['id']}/decline").status_code == 200
    assert not (tmp_path / "peer" / "imprints" / made["id"]).exists() and row(st, made["id"])["status"] == "declined"
    assert confirm(st.sam, made).status_code == 404
