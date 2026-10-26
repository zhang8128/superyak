"""Task 28: engram-permissions migrate, P 12.3 step 2 (U13; the re-check's RN6; ledger ruling 'Task 28, FM1')."""
import getpass
import json
import re
import sqlite3
import uuid
from pathlib import Path

import pytest

import permission_cli
from permission_cli import main
from permission_ledger import PUBLISHED_HOUSE, Ledger, houses
from permissions import Layer, Use, decide, required_layers
from sharing import share as share_memory
from storage import Storage
from tests.permissions_support import (DAEMON_CLOCK, DAEMON_RECEIVER, T, Rig, _daemon_over, at, counter_row,
                                       fake_tty, house_before_029, house_dir, ledger_bytes, raise_gate, receipt_rows,
                                       share_columns, write_receiver_files)
from tests.test_lighthouse_daemon import unit

NOW = T("2026-11-01")
CREATED = "2026-10-01T00:00:00+00:00"
GROUPS = '[groups.team]\nmembers = ["engram", "scout"]\n\n[groups.lab]\nmembers = ["scout"]\n'
RECEIVERS = ["engram", "scout"]
UNMATCHED = {"mem-unmatched"}                      # the memory id of the row whose source fell back


# ---------------------------------------------------------------- helpers named in the brief

def share_rows(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM shared_memories ORDER BY shared_at, share_id")]
    finally:
        con.close()


def instance_id_of(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("SELECT value FROM meta WHERE key = 'instance_id'").fetchone()[0]
    finally:
        con.close()


def source_store_paths(home):
    return [home / ".engram" / "graph.db", home / ".engram" / "instances" / "why" / "graph.db"]


def source_for(home, row):
    name = row["source_instance"]
    return home / ".engram" / ("graph.db" if name == "default" else f"instances/{name}/graph.db")


def migrated_ref(home, audience):
    for r in share_rows(home / PUBLISHED_HOUSE):
        if r["audience"] == audience and r["source_instance_id"]:
            return f"mem:{r['source_instance_id']}/{r['layer']}/{r['source_id']}"
    raise AssertionError(f"no migrated row for {audience}")


def receivers_named_in_policies(home):
    out = set()
    for policy in (home / ".engram" / "instances").glob("*/lighthouse-policy.json"):
        for rule in json.loads(policy.read_text())["payload"]["rules"]:
            out |= {p.removeprefix("urn:engram:") for p in rule["publishers"]}
    return sorted(out)


def unmatched_memory_ids(out):
    return set(re.findall(r"^\s*unmatched (\S+):", out, re.M))


def now():
    return NOW + 86400


def raise_to_gate(home, mode):
    led = Ledger.open(home)
    try:
        raise_gate(led, mode)
    finally:
        led.close()


# ---------------------------------------------------------------- the legacy world

def _as_andy(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setattr(getpass, "getuser", lambda: "andy")
    monkeypatch.setattr(permission_cli, "_now", lambda: NOW)


def _store(path, ids, embed):
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Storage(str(path))
    for eid, text in ids:
        store.add_episode(id=eid, session_id=None, content=text, lane="work" if eid.startswith("l") else "personal",
                          embedding=unit(text) if embed else None)
    store.conn.execute("UPDATE episodes SET created_at = ?", (CREATED,))
    store.conn.commit()
    return store


def _semantic(store, sid, text):
    store.conn.execute(
        "INSERT INTO semantics (id, content, kind, confidence, created_at, auto_generated, content_hash, lane) "
        "VALUES (?, ?, 'fact', 0.5, ?, 0, 'h', 'personal')", (sid, text, CREATED))
    store.conn.commit()


def _publisher_policy(root):
    from lighthouse_protocol import artifact_digest  # noqa: F401  (policy_gen seals its own artifact)
    from policy_gen import build_publisher_policy, load_groups, write_receiver_policy
    groups = load_groups(root / ".engram" / "groups.toml")
    artifact = build_publisher_policy(publisher="lighthouse", receivers=RECEIVERS, groups=groups,
                                      issued_at="2026-09-01T00:00:00Z", valid_from="2026-01-01T00:00:00Z",
                                      valid_until="2028-01-01T00:00:00Z")
    write_receiver_policy(house_dir(root, "lighthouse") / "lighthouse-policy.json", artifact)


def build_legacy(root, *, extra_commons=0, fallback=False, receivers=False, before_029=False):
    """An ENGRAM_HOME with the default store, the instance store `why`, the published house `lighthouse` holding shares
    to commons, group:team and group:lab from both, groups.toml and a generated publisher policy naming two receivers.
    `fallback` adds one row whose named instance has no store (it fell back to the default store); `receivers` writes
    the receivers' own policy files."""
    embed = extra_commons == 0
    text = lambda eid: f"{eid}: shared: a note about {eid}"
    default_ids = [(i, text(i)) for i in ("c1", "t1", "l1", "f1")] + [(f"x{n}", text(f"x{n}")) for n in range(extra_commons)]
    default = _store(root / ".engram" / "graph.db", default_ids, embed)
    _semantic(default, "s1", "s1: a distilled fact")
    why = _store(root / ".engram" / "instances" / "why" / "graph.db", [(i, text(i)) for i in ("c2", "t2", "l2")], embed)
    (root / ".engram" / "groups.toml").write_text(GROUPS)
    rows = [(default, "default", "c1", "episode", "commons"), (default, "default", "t1", "episode", "group:team"),
            (default, "default", "l1", "episode", "group:lab"), (default, "default", "s1", "semantic", "commons"),
            (why, "why", "c2", "episode", "commons"), (why, "why", "t2", "episode", "group:team"),
            (why, "why", "l2", "episode", "group:lab")]
    rows += [(default, "default", f"x{n}", "episode", "commons") for n in range(extra_commons)]
    if fallback:
        rows.append((default, "ghost", "f1", "episode", "commons"))
    if before_029:
        path = house_before_029(root, "lighthouse")
        con = sqlite3.connect(path)
        import hashlib
        for n, (store, instance, sid, layer, audience) in enumerate(rows):
            getter = store.get_episode if layer == "episode" else store.get_semantic
            digest = hashlib.sha256(getter(sid)["content"].encode()).hexdigest()
            con.execute("INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer, "
                        "audience, reason, content_digest, shared_at) VALUES (?, ?, ?, ?, ?, ?, 'test', ?, ?)",
                        (f"sh{n:04d}", "mem-unmatched" if instance == "ghost" else str(uuid.uuid4()),
                         instance, sid, layer, audience, digest, f"2026-10-{n % 28 + 1:02d}"))
        con.commit()
        con.close()
    else:
        house_dir(root, "lighthouse")
        house = Storage(str(root / PUBLISHED_HOUSE))
        for store, instance, sid, layer, audience in rows:
            share_memory(source_storage=store, published_storage=house, source_id=sid, layer=layer,
                         audience=audience, reason="test", source_instance=instance)
        house.close()
    _publisher_policy(root)
    if receivers:
        for r in RECEIVERS:
            write_receiver_files(root, r, publisher="lighthouse")
    default.close()
    why.close()
    return root


@pytest.fixture
def legacy_home(tmp_path, monkeypatch, fake_tty):
    _as_andy(tmp_path, monkeypatch)
    return build_legacy(tmp_path)


@pytest.fixture
def legacy_home_with_300_commons_shares(tmp_path, monkeypatch, fake_tty):
    _as_andy(tmp_path, monkeypatch)
    return build_legacy(tmp_path, extra_commons=300)


@pytest.fixture
def fallback_home(tmp_path, monkeypatch, fake_tty):
    _as_andy(tmp_path, monkeypatch)
    return build_legacy(tmp_path, fallback=True, receivers=True)


@pytest.fixture
def legacy_home_full(tmp_path, monkeypatch, fake_tty):
    _as_andy(tmp_path, monkeypatch)
    return build_legacy(tmp_path, fallback=True, receivers=True)


@pytest.fixture
def legacy_home_before_029(tmp_path, monkeypatch, fake_tty):
    _as_andy(tmp_path, monkeypatch)
    return build_legacy(tmp_path, fallback=True, before_029=True)


def daemon_for(home, receiver):
    from lighthouse_daemon import PublisherStore
    inst = home / ".engram" / "instances" / "lighthouse"
    pub = PublisherStore(name="lighthouse", db_path=inst / "graph.db", policy_path=inst / "lighthouse-policy.json",
                         disclosures_path=inst / "lighthouse-disclosures.db")
    return Rig(_daemon_over(home, [pub], clock=at(DAEMON_CLOCK)), home, receiver=receiver, pub="lighthouse")


def placements(home):
    return sorted({r["memory_id"] for r in share_rows(home / PUBLISHED_HOUSE)})


# ---------------------------------------------------------------- the tests of the brief

def test_u13_shares_become_one_collection_and_one_allow_per_legacy_audience(legacy_home, fake_tty):
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    s = Ledger.open(legacy_home).state()
    assert set(s.collections) == {"collection:andy/legacy-commons", "collection:andy/legacy-group-team",
                                  "collection:andy/legacy-group-lab"}
    assert len([r for r in s.records.values() if r.reason == "legacy share"]) == 3
    assert {r["channel"] for r in Ledger.open(legacy_home).tables()["ledger_log"]} == {"migration"}
    assert set(s.groups) == {"group:team", "group:lab"}
    assert set(s.agents) == {"agent:engram", "agent:scout"}
    for ref in (migrated_ref(legacy_home, "commons"), migrated_ref(legacy_home, "group:lab")):
        assert s.lane_notes[ref][0].lane in ("personal", "work")     # a first lane note, read from the source
    assert s.lane_notes[migrated_ref(legacy_home, "group:lab")][0].lane == "work"
    assert s.lane_notes[migrated_ref(legacy_home, "group:lab")][0].at == T("2026-10-01")


def test_u13_more_than_256_shares_migrate(legacy_home_with_300_commons_shares, fake_tty):
    home = legacy_home_with_300_commons_shares
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    led = Ledger.open(home); s = led.state()
    members = [m for m in led.tables()["collection_members"] if m["collection"] == "collection:andy/legacy-commons"]
    assert len(members) == 300 + 3 and {m["backing"] for m in members} == {"person"}
    commons_allow = [r for r in s.records.values() if r.reason == "legacy share" and "collection:andy/legacy-commons" in str(r.selector)]
    [allow] = commons_allow                                              # one record, within the 256 bound
    house = [r for r in share_rows(home / PUBLISHED_HOUSE) if r["audience"] == "commons"]
    assert len(house) == 300 + 3 and {r["record_id"] for r in house} == {allow.id}
    assert all(r["source_instance_id"] for r in house)


def test_u13_a_row_whose_source_fell_back_is_listed_and_refused_under_enforce(fallback_home, fake_tty, capsys):
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "unmatched" in out
    [bad] = unmatched_memory_ids(out)
    good = next(m for m in placements(fallback_home) if m != bad)
    raise_to_gate(fallback_home, "enforce")
    rig = daemon_for(fallback_home, "scout")
    assert rig.read(good)["content"] is not None                         # a migrated placement is served
    receipts = len(receipt_rows(fallback_home))
    assert rig.read(bad)["content"] is None                              # it has no object: never served
    assert len(receipt_rows(fallback_home)) == receipts                  # and no use to write a receipt for


def test_u13_in_shadow_the_legacy_path_allows_nothing_the_new_one_refuses_except_listed_rows(
        legacy_home_full, fake_tty, capsys):
    # Ruling: a listed row has no object (source_instance_id NULL, as every real row from before 029), so the daemon
    # writes it no receipt (lighthouse_daemon.read_item); `report shadow` lists it as a share with "no object".
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    unmatched = unmatched_memory_ids(capsys.readouterr().out)
    assert len(unmatched) == 1
    raise_to_gate(legacy_home_full, "shadow")
    checked, legacy_refused = 0, set()
    for receiver in receivers_named_in_policies(legacy_home_full):
        rig = daemon_for(legacy_home_full, receiver)
        rig.recall(query="c1: shared: a note about c1")
        for memory_id in placements(legacy_home_full):
            before = len(receipt_rows(legacy_home_full))
            item = rig.read(memory_id)
            if memory_id in unmatched:
                assert len(receipt_rows(legacy_home_full)) == before     # no object, no receipt
                assert item["content"] is not None                       # shadow: the legacy path decides
                continue
            row = receipt_rows(legacy_home_full, action="inject_context")[-1]
            legacy = item["content"] is not None and all(
                c["verdict"] == "allow" for c in json.loads(row["cited"]) if c["kind"] == "legacy")
            if legacy:
                assert row["allowed"] == 1, (receiver, memory_id)
                checked += 1
            elif item["content"] is None:
                legacy_refused.add((f"agent:{receiver}", row["object"]))    # the audience check, which is not cited
    assert checked >= 6
    assert main(["report", "shadow", "--json"]) == 0                     # a reading command: no yes
    report = json.loads(capsys.readouterr().out)
    # Ruling: `report shadow` (Task 27) also lists a read the publisher's audience check refused when the ledger
    # refuses it too, since that check is not a cited legacy layer; so the listed ones must all be such reads.
    assert {(d["agent"], d["object"]) for d in report["disagreements"]} <= legacy_refused
    assert [r["why"] for r in report["would_need_a_proposal"]] == ["no object"]


def test_migrate_opens_the_published_house_with_storage_so_029_runs(legacy_home_before_029, fake_tty):
    # every house built from migrations 001 to 028 only (house_before_029, Task 16)
    house = legacy_home_before_029 / ".engram/instances/lighthouse/graph.db"
    assert not {"source_instance_id", "record_id"} <= share_columns(house)
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    assert {"source_instance_id", "record_id"} <= share_columns(house) and counter_row(house) is not None
    assert all(r["source_instance_id"] for r in share_rows(house) if r["memory_id"] not in UNMATCHED)
    assert [r["source_instance_id"] for r in share_rows(house) if r["memory_id"] in UNMATCHED] == [None]


def test_migrate_refuses_when_a_ledger_exists(legacy_home, fake_tty, capsys):
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    before = ledger_bytes(legacy_home)
    rows = share_rows(legacy_home / PUBLISHED_HOUSE)
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 1
    err = capsys.readouterr().err
    assert ledger_bytes(legacy_home) == before and "already" in err and "share" in err and "collection add" in err
    assert share_rows(legacy_home / PUBLISHED_HOUSE) == rows


def _beside(path):
    """Ruling 'Task 28, FM1': the store's bytes, and the files beside it that start with the store's own file name."""
    return path.read_bytes(), {q.name: q.stat().st_size for q in path.parent.iterdir()
                               if q.name.startswith(path.name) and q != path}


def test_u13_each_source_store_is_byte_identical_while_source_instance_id_is_filled(legacy_home, fake_tty):
    sources = source_store_paths(legacy_home)            # .engram/graph.db and instances/why/graph.db
    before = {p: _beside(p) for p in sources}
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    for p in sources:
        data, beside = _beside(p)
        assert data == before[p][0]
        assert set(beside) <= {p.name + "-wal", p.name + "-shm"} | set(before[p][1])     # nothing but -wal and -shm
        assert beside.get(p.name + "-wal", 0) == before[p][1].get(p.name + "-wal", 0)   # and no frames in -wal
    rows = share_rows(legacy_home / ".engram/instances/lighthouse/graph.db")
    assert rows and all(r["source_instance_id"] == instance_id_of(source_for(legacy_home, r)) for r in rows)


def test_u13_every_house_and_source_store_is_registered_at_andys_home_and_use_1s_holding_place_resolves(
        legacy_home, fake_tty):                          # 12.3 step 2; the re-check's RN6
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    s = Ledger.open(legacy_home).state()
    expected = {instance_id_of(p) for p in houses(legacy_home) + source_store_paths(legacy_home)}
    assert expected <= set(s.stores)
    assert {(s.stores[i].owner, s.stores[i].place) for i in expected} == {("person:andy", "place:home/andy")}
    house_id = instance_id_of(legacy_home / ".engram/instances/lighthouse/graph.db")
    receiver = receivers_named_in_policies(legacy_home)[0]
    u = Use(requester=f"agent:{receiver}", place="place:home/andy", obj=migrated_ref(legacy_home, "commons"),
            copy=f"store:{house_id}", action="recall", purpose="session-recall", at=now())
    assert Layer("place:home/andy", "consent") in required_layers(s, u)   # the holding place resolves
    assert decide(s, u).allowed                          # use 1's shape: a placement decided on its source ref, via h


# ---------------------------------------------------------------- what the brief says in words

def test_the_plan_is_printed_and_written_before_the_yes(legacy_home_full, fake_tty, capsys):
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "commons: 3" in out and "group:team: 2" in out and "group:lab: 2" in out and "unmatched" in out
    [path] = (legacy_home_full / ".engram").glob("permissions-migrate-*.json")
    assert str(path) in out
    doc = json.loads(path.read_text())
    assert len(doc["rows"]) == 7 and len(doc["unmatched"]) == 1


def test_a_wrong_code_writes_no_ledger_and_leaves_no_plan_file(legacy_home, fake_tty):
    fake_tty.answer("wrong1"); assert main(["migrate"]) == 3
    assert not (legacy_home / ".engram" / "permissions.db").exists()
    assert not list((legacy_home / ".engram").glob("permissions-migrate-*"))
    assert all(r["record_id"] is None for r in share_rows(legacy_home / PUBLISHED_HOUSE))


def test_a_house_without_029_other_than_the_published_one_is_listed(legacy_home, fake_tty, capsys):
    house_before_029(legacy_home, "old")
    fake_tty.answer_the_printed_code(); assert main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert "029" in out and "old" in out
    s = Ledger.open(legacy_home).state()
    old_id = instance_id_of(legacy_home / ".engram/instances/old/graph.db")
    assert old_id in s.stores                                   # registered, though not migrated


def test_migrate_refuses_without_a_published_house(tmp_path, monkeypatch, fake_tty, capsys):
    _as_andy(tmp_path, monkeypatch)
    assert main(["migrate"]) == 1 and "published house" in capsys.readouterr().err
    assert not (tmp_path / ".engram" / "permissions.db").exists()
