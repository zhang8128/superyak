"""A use begins on the station: decided, given a uuid4, a use-started receipt and an allow file (spec I 12, D41, R23;
plan Task 37)."""
import json
import re
import stat
from types import SimpleNamespace

import pytest

from superyak_peer.__main__ import main as cli
from superyak_peer.identity import canonical
from imprint_support import NOW, seed_imprint
from test_imprint_admission import effective_end_of, approved, begin, receipts, row, state_of, write_result

USE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
ALLOW_KEYS = {"kind", "use_id", "instance_id", "use", "actions", "purpose", "requester", "acting_for", "place",
              "records", "decided_at", "valid_until"}


def admitted(tmp_path, route=True, n=4):
    """A station holding Sam's imprint in status `admitted`, with N roads and trails in its `admitted` receipt."""
    st = approved(tmp_path, route=route)
    begin(st)
    write_result(st, status="admitted", roads_and_trails=n if route else 0)
    st.store.station_imprint_sync(root=st.root)
    assert row(st)["status"] == "admitted"
    contents = json.loads((st.root / st.imprint_id / "manifest.json").read_text())["contents"]
    st.count = contents.get("episodes", 0) + contents.get("semantics", 0)
    return st


def lets_sam_route(st):
    """A second live imprint of Sam's that allows route, so his layer permits it while the first copy's ceiling doesn't."""
    other = seed_imprint(st, status="admitted", id="b" * 32, imprint_id="feed0001",
                         source_instance_id=row(st)["source_instance_id"])
    with st.store.transaction() as db:
        permission = json.loads(db.execute("SELECT permission FROM imprint_requests WHERE id=?", (other,)).fetchone()[0])
        selector = permission["records"][0]["selector"]
        selector["actions"] = ["imprint", "read", "recall", "route"]
        selector["purposes"] = ["calibration", "trail-evaluation"]
        selector["objects"]["kinds"] = ["memory", "road", "trail"]
        db.execute("UPDATE imprint_requests SET permission=? WHERE id=?", (canonical(permission).decode(), other))


def admitted_with_fault(tmp_path, fault):
    if fault == "not_admitted":
        return approved(tmp_path, route=True)
    st = admitted(tmp_path, route=fault != "no_route", n=4)
    if fault == "withdrawn":
        with st.store.transaction() as db:
            st.store._append_imprint_receipt(db, st.request_id, "withdrawn", st.ids["sam"], {}, sign=False)
    elif fault == "ended":
        st.clock[0] = effective_end_of(st) + 1
    elif fault == "no_route":
        lets_sam_route(st)
    return st


def operator_for(fault):
    return "jenn" if fault == "other_operator" else "andy"


def run_peer_cli(st, argv):
    base = ["--data-dir", str(st.store.data_dir), "--imprints-dir", str(st.root)]
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli([*argv, *base])
        except SystemExit as stopped:
            code = stopped.code or 0
    return SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


def test_an_allowed_use_writes_its_receipt_then_its_allow_file(tmp_path):
    st = admitted(tmp_path, route=True, n=4)
    out = st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    path = st.root / f"{st.imprint_id}.state" / "uses" / f"{out['use_id']}.allow.json"
    allow = json.loads(path.read_text())
    assert USE_ID.fullmatch(out["use_id"]) and set(allow) == ALLOW_KEYS and allow["actions"] == ["read", "recall", "route"]
    assert (allow["requester"], allow["acting_for"], allow["place"]) == ("agent:station-imprints", "person:andy", "place:home/andy")
    started = receipts(st)[-1]["record"]
    assert started["event"] == "use-started" and started["detail"]["objects"] == {"imprint": st.imprint_id, "count": st.count, "roads_and_trails": 4}
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert (allow["kind"], allow["use_id"], allow["instance_id"], allow["use"], allow["purpose"]) == (
        "imprint-use-allow", out["use_id"], st.imprint_id, "trail-evaluation", "trail-evaluation")
    assert allow["decided_at"] == NOW and allow["valid_until"] == effective_end_of(st) and allow["records"]
    assert started["detail"] == {"use": "trail-evaluation", "use_id": out["use_id"], "actions": ["read", "recall", "route"],
                                 "purpose": "trail-evaluation", "objects": started["detail"]["objects"]}


@pytest.mark.parametrize("fault,term", [("not_admitted", "status"), ("withdrawn", "withdrawal"), ("ended", "end"),
                                        ("other_operator", "audience"), ("no_route", "ceiling")])
def test_a_refused_use_writes_a_refused_receipt_and_nothing_else(tmp_path, fault, term):
    st = admitted_with_fault(tmp_path, fault)
    out = st.store.station_imprint_use_begin(operator_for(fault), st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert out == {"allowed": False, "term": term} and not list((st.root / f"{st.imprint_id}.state").glob("uses/*"))
    assert receipts(st)[-1]["record"]["event"] == "refused" and receipts(st)[-1]["record"]["detail"]["term"] == term


def test_the_command_prints_only_the_use_id(tmp_path):
    st = admitted(tmp_path, route=True, n=0)
    done = run_peer_cli(st, ["station-imprint-use-begin", "--id", st.imprint_id[:4], "--use", "trail-evaluation", "--as", "andy"])
    assert done.returncode == 0 and USE_ID.fullmatch(done.stdout.strip()) and len(done.stdout.splitlines()) == 1


# Added by the task: what the brief's seven tests leave open.

def test_the_command_exits_3_when_refused_and_prints_no_use_id(tmp_path):
    st = admitted(tmp_path, route=True, n=1)               # the command runs on the real clock, so refuse by audience
    done = run_peer_cli(st, ["station-imprint-use-begin", "--id", st.imprint_id[:4], "--use", "trail-evaluation", "--as", "jenn"])
    assert done.returncode == 3 and done.stdout == "" and "audience" in done.stderr


def test_a_refused_receipt_after_admission_carries_the_count_and_before_it_does_not(tmp_path):
    st = admitted_with_fault(tmp_path, "withdrawn")
    st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert receipts(st)[-1]["record"]["detail"] == {"use": "trail-evaluation", "actions": ["read", "recall", "route"],
                                                    "purpose": "trail-evaluation", "term": "withdrawal", "roads_and_trails": 4}
    st = admitted_with_fault(tmp_path / "again", "not_admitted")
    st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert "roads_and_trails" not in receipts(st)[-1]["record"]["detail"]


def test_two_uses_get_two_ids_and_a_removed_state_directory_is_never_recreated(tmp_path):
    st = admitted(tmp_path, route=True, n=1)
    a = st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    b = st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert a["use_id"] != b["use_id"] and len(list((state_of(st) / "uses").glob("*.allow.json"))) == 2
    import shutil
    shutil.rmtree(state_of(st))
    from superyak_peer.common import Problem
    before = [r["record"]["event"] for r in receipts(st)]
    with pytest.raises(Problem):
        st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert not state_of(st).exists() and [r["record"]["event"] for r in receipts(st)] == before


def test_an_unknown_use_a_short_prefix_and_an_unknown_imprint_are_problems(tmp_path):
    from superyak_peer.common import Problem
    st = admitted(tmp_path, route=True, n=1)
    for prefix, use in ((st.imprint_id[:4], "calibration"), (st.imprint_id[:3], "trail-evaluation"), ("ffff", "trail-evaluation")):
        with pytest.raises(Problem):
            st.store.station_imprint_use_begin("andy", prefix, use, root=st.root)
