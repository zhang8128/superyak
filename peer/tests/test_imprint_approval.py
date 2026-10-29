"""Andy's approval, denial and the hand-off (spec I 10, A2; plan Task 29)."""
import stat

import pytest

from superyak_peer.__main__ import describe_decision
from superyak_peer.common import Problem
from imprint_support import ship_shortens, station
from test_imprint_confirm import row
from test_imprint_upload import allowed_with_all_parts


def received(tmp_path):
    """A station holding Sam's imprint in status `received`, with its staged bytes."""
    st, made, _ = allowed_with_all_parts(tmp_path, nbytes=100)
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").json()["status"] == "received"
    st.request_id = made["id"]
    st.imprint_id = row(st, made["id"])["imprint_id"]
    return st


def staging(st):
    return st.store.data_dir / "imprints" / st.request_id


def receipts(st):
    return st.store.imprint_receipts(st.request_id)


def approved_docking(path):
    st = station(path)
    docking = st.store.start_docking("defiant", "laptop")
    return st.store.station_decide("andy", docking["id"][:6], True)


def test_approve_by_short_id_hands_off_and_records_the_root(tmp_path):
    st = received(tmp_path)
    item, result = st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    imp = st.root / st.imprint_id
    assert sorted(p.name for p in imp.iterdir()) == ["approved.json", "imprint.db", "manifest.json", "permission.json"]
    assert (st.root / f"{st.imprint_id}.state").is_dir() and stat.S_IMODE(imp.stat().st_mode) == 0o700
    assert row(st, st.request_id)["imprints_root"] == str(st.root.resolve()) and not staging(st).exists()
    assert [r["record"]["event"] for r in receipts(st)][-1] == "approved"


def test_deny_deletes_everything_and_writes_receipts(tmp_path):
    st = received(tmp_path)
    st.store.station_decide("andy", st.request_id[:4], False, imprints_root=st.root)
    assert not staging(st).exists() and not (st.root / st.imprint_id).exists()
    assert [r["record"]["event"] for r in receipts(st)][-2:] == ["denied", "deleted"]
    found = row(st, st.request_id)
    assert found["status"] == "deleted" and found["delete_reason"] == "denied"


def test_an_audience_other_than_the_approvers_home_is_refused(tmp_path):
    st = received(tmp_path)
    with pytest.raises(Problem, match="place:home/jenn"):
        st.store.station_decide("jenn", st.request_id[:4], True, imprints_root=st.root)
    assert row(st, st.request_id)["status"] == "received" and staging(st).exists()


def test_existing_directories_or_a_tombstone_refuse_the_hand_off(tmp_path):
    st = received(tmp_path); (st.root / "tombstones").mkdir(parents=True)
    (st.root / "tombstones" / f"{st.imprint_id}.json").write_text("{}")
    before = receipts(st)
    with pytest.raises(Problem):
        st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    assert row(st, st.request_id)["status"] == "received" and receipts(st) == before and staging(st).exists()


@pytest.mark.parametrize("name", ["", ".state"])
def test_an_existing_directory_refuses_the_hand_off(tmp_path, name):
    st = received(tmp_path); (st.root / (st.imprint_id + name)).mkdir()
    before = receipts(st)
    with pytest.raises(Problem):
        st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    assert row(st, st.request_id)["status"] == "received" and receipts(st) == before and staging(st).exists()


def test_an_approval_names_the_full_imprint_id_for_the_makefile(tmp_path):
    st = received(tmp_path)
    lines = describe_decision(*st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)).splitlines()
    assert lines[-1] == f"ADMIT: {st.imprint_id}" and sum(l.startswith("ADMIT: ") for l in lines) == 1
    assert lines[0] == f"Approved {st.request_id[:4]}. Admitting in the background; see make station-imprints."
    assert "ADMIT: " not in describe_decision(*approved_docking(tmp_path / "dock"))


def test_a_denial_is_described(tmp_path):
    st = received(tmp_path)
    out = describe_decision(*st.store.station_decide("andy", st.request_id[:4], False, imprints_root=st.root))
    assert out == f"Denied the imprint {st.request_id[:4]}; its bytes are deleted."


def test_a_refusal_at_approval_is_a_denial_naming_the_term(tmp_path):
    st = received(tmp_path); ship_shortens(st, to=st.clock[0] + 10); st.clock[0] += 20
    st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    denied = [r["record"] for r in receipts(st) if r["record"]["event"] == "denied"][0]
    assert denied["detail"] == {"term": "end"} and row(st, st.request_id)["status"] == "deleted"
    assert not staging(st).exists() and not (st.root / st.imprint_id).exists()


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_a_request_that_cannot_be_read_back_is_not_approved(tmp_path, damage):    # final review M3
    st = received(tmp_path)
    staged = staging(st) / "request.json"
    if damage == "changed":
        staged.write_bytes(staged.read_bytes().replace(b'"days":90', b'"days":91'))
    else:
        staged.unlink()
    with pytest.raises(Problem, match="cannot be read back"):
        st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    assert row(st, st.request_id)["status"] == "received" and not (st.root / st.imprint_id).exists()
    assert "approved" not in [r["record"]["event"] for r in receipts(st)]
