"""The request, the manifest and the owner's lists (store-copy spec I 7.1, 7.2, D26, R30)."""
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

from imprint import (REQUEST_KEYS, make_plan, manifest_for, objects_for, render_request, request_for, subjects_for,
                     write_owner_lists, write_package)
from imprint_filter import DIGEST_TABLES, canonical, package_rows
from tests.imprint_support import PLAN_NOW, plan_args

IMPRINT_ID = "c0a8f5e2-1b3d-4a6e-8f90-aabbccddeeff"
NOW = 1_761_415_451


def key_tree(req: dict) -> dict:
    """The key tree of a request; ``contents`` is a map of table names, so its leaves are not keys of the form."""
    return {k: (None if k == "contents" or not isinstance(v, dict) else key_tree(v)) for k, v in req.items()}


def plan_rows(tmp_path: Path, **kw):
    """Task 12's PackageRows for the plan_args store, with a disk scratch."""
    store, sel, terms, ctx, *_ = plan_args(tmp_path, **kw)
    conn = sqlite3.connect(store)
    conn.row_factory = sqlite3.Row
    import sqlite_vec
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    return package_rows(conn, sel, terms, ctx), ctx.source_id


def request_and_package(tmp_path: Path):
    plan = make_plan(*plan_args(tmp_path))
    rows, source_id = plan_rows(tmp_path / "pk")
    pkg = tmp_path / "imprint.db"
    write_package(rows, pkg, source_id=source_id, source_ancestry=[], source_complete=True, imprint_id=IMPRINT_ID)
    return request_for(plan, IMPRINT_ID, package_bytes=pkg.stat().st_size), pkg


def test_the_request_has_exactly_the_section_7_1_keys(tmp_path, route_open):
    req = request_for(make_plan(*plan_args(tmp_path, route=True)), IMPRINT_ID, package_bytes=43_188_224)
    assert key_tree(req) == REQUEST_KEYS and req["package"] == {"bytes": 43_188_224, "parts": 11}
    assert set(req["contents"]) <= set(DIGEST_TABLES) and all(v >= 1 for v in req["contents"].values())
    assert not set(req["contents"]) & {"meta", "schema_version", "episode_fts", "sqlite_sequence"}
    assert req["kind"] == "engram-imprint-request" and req["version"] == 1
    assert req["terms"]["audience"] == ["place:home/andy"] and req["terms"]["days"] == 90
    canonical(req)


def test_a_request_without_route_names_no_log_table(tmp_path):
    req = request_for(make_plan(*plan_args(tmp_path, route=False)), IMPRINT_ID, package_bytes=4_194_304)
    assert not {"memory_log", "operation_log"} & set(req["contents"]) and req["package"]["parts"] == 1


def test_the_manifest_agrees_with_the_request(tmp_path):
    req, pkg = request_and_package(tmp_path)
    man = manifest_for(req, pkg, built_at=NOW, engram_commit=None)
    for k in ("imprint_id", "plan_digest", "scope", "contents", "others"):
        assert man[k] == req[k]
    assert man["request_sha256"] == hashlib.sha256(canonical(req)).hexdigest()
    assert len(man["package"]["parts"]) == req["package"]["parts"] and man["vec"] == {"create_version": "v0.1.7"}
    canonical(man)                                    # no float anywhere
    assert man["filter"] == "imprint-filter-v1" and man["engram_commit"] is None
    assert man["embedding"] == {"model": "nomic-ai/nomic-embed-text-v1.5", "dimension": 768}
    assert man["built_at"] == "2025-10-25T18:04:11Z"
    assert man["source"] == {"instance_id": req["source_instance_id"], "identity": "present",
                             "ancestry": req["source_ancestry"], "ancestry_complete": req["source_ancestry_complete"]}
    assert man["schema"]["applied"] == sorted(man["schema"]["applied"]) and man["schema"]["applied"][0] == 1
    assert man["package"]["file"] == "imprint.db" and man["package"]["bytes"] == pkg.stat().st_size
    assert man["package"]["sha256"] == hashlib.sha256(pkg.read_bytes()).hexdigest()
    assert man["package"]["part_bytes"] == 4_194_304


def test_part_hashes_cover_the_package_in_part_sized_pieces(tmp_path, monkeypatch):
    import imprint
    req, pkg = request_and_package(tmp_path)
    monkeypatch.setattr(imprint, "PART_BYTES", 100_000)
    req = dict(req, package={"bytes": pkg.stat().st_size, "parts": -(-pkg.stat().st_size // 100_000)})
    man = manifest_for(req, pkg, built_at=NOW, engram_commit="abc")
    data = pkg.read_bytes()
    assert man["package"]["parts"] == [hashlib.sha256(data[i:i + 100_000]).hexdigest()
                                       for i in range(0, len(data), 100_000)]
    assert man["package"]["part_bytes"] == 100_000 and man["engram_commit"] == "abc"


def test_the_terminal_prints_the_request_and_what_the_station_keeps(tmp_path):
    text = render_request(request_for(make_plan(*plan_args(tmp_path, ancestry=["3f2a9c1e-5b7d-4c2a-9e1f-0a6b8c4d2e10"])), IMPRINT_ID, 1))
    assert "This goes to the station now, before you say yes." in text and "Nothing is kept with no end." in text
    assert "30 days" in text and "400 days" in text and "3f2a" in text and IMPRINT_ID[:4] in text


def test_others_carry_counts_and_no_name(tmp_path):
    plan = make_plan(*plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn", "e2": ["person:jenn", "person:lee"]}))
    req = request_for(plan, IMPRINT_ID, package_bytes=4_194_304)
    assert req["others"] == {"memories": 2, "people": 2} and req["contents"]["imprint_subjects"] == 3
    assert "jenn" not in json.dumps(req) and "lee" not in json.dumps(req)
    away = request_for(make_plan(*plan_args(tmp_path / "away", owner="sam", cosubjects={"e1": "person:jenn"})), IMPRINT_ID, 1)
    assert away["others"] == {"memories": 0, "people": 0} and "imprint_subjects" not in away["contents"]


def test_the_owners_lists_are_json_one_element_per_line(tmp_path):
    rows, source_id = plan_rows(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"})
    write_owner_lists(tmp_path / "out", rows, source_id)
    for name in ("objects.json", "subjects.json"):
        lines = (tmp_path / "out" / name).read_text().splitlines()
        assert lines[0] == "[" and lines[-1] == "]" and json.loads("\n".join(lines)) == [json.loads(l.rstrip(",")) for l in lines[1:-1]]
        assert all(l.endswith(",") for l in lines[1:-2]) and not lines[-2].endswith(",")


def test_the_lists_are_sorted_by_ref(tmp_path):
    rows, source_id = plan_rows(tmp_path, owner="andy", cosubjects={"e2": ["person:lee", "person:jenn"], "e1": "person:jenn"})
    objs = list(objects_for(rows, source_id))
    assert objs == sorted(objs) and all(o.startswith(f"mem:{source_id}/") for o in objs)
    assert f"mem:{source_id}/semantic/s1" in objs and len(objs) == len(set(objs))
    subs = list(subjects_for(rows, source_id))
    assert subs == sorted(subs) and len(subs) == 3
    assert subs[0] == [f"mem:{source_id}/episode/e1", "person:jenn"]
    assert subs[-1] == [f"mem:{source_id}/episode/e2", "person:lee"]


def test_subjects_sort_by_layer_before_id():
    fake = SimpleNamespace(rows={"imprint_subjects": [      # the rows come by id, then layer
        {"memory_id": "a", "layer": "semantic", "subject": "person:x"},
        {"memory_id": "b", "layer": "episode", "subject": "person:x"},
        {"memory_id": "b", "layer": "semantic", "subject": "person:y"}]})
    got = list(subjects_for(fake, "S"))
    assert got == sorted(got) == [["mem:S/episode/b", "person:x"], ["mem:S/semantic/a", "person:x"],
                                  ["mem:S/semantic/b", "person:y"]]


def test_an_empty_list_is_still_json(tmp_path):
    rows, source_id = plan_rows(tmp_path, owner="sam")
    write_owner_lists(tmp_path / "out", rows, source_id)
    assert json.loads((tmp_path / "out" / "subjects.json").read_text()) == []
