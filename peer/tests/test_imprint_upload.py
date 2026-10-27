"""The manifest, resumable parts, the join and the IMPRINT item (spec I 7.2, 9, 10, 14; plan Task 26)."""
import copy
import hashlib
import json
import random
import uuid

from fastapi.testclient import TestClient
import pytest

from superyak_peer import imprints
from superyak_peer.__main__ import describe_pending
from superyak_peer.app import create_app
from superyak_peer.identity import canonical
from superyak_peer.imprints import PART_SIZE as PART_BYTES
from imprint_support import NOW, request_doc, station, post
from test_imprint_confirm import ANDY_PASSWORD, confirm, row

WEEK = 7 * 86400


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put_manifest(st, made, manifest, ship="voyager"):
    raw = manifest if isinstance(manifest, bytes) else canonical(manifest)
    return getattr(st, ship).put(f"/api/imprints/{made['id']}/manifest", content=raw)


def put_part(st, made, n, data, ship="voyager"):
    return getattr(st, ship).put(f"/api/imprints/{made['id']}/parts/{n}", content=data)


def staged(st, made):
    return st.store.data_dir / "imprints" / made["id"]


def part_files(tmp_path, made):
    return sorted(p.name for p in (tmp_path / "peer" / "imprints" / made["id"]).iterdir())


def manifest_for_doc(st, made, data, *, plan_digest=None, differ=None):
    """I 7.2's manifest for the staged request and the package bytes, valid unless `differ` names a shared field
    (set to another well-formed value) or `plan_digest` is given."""
    raw = (staged(st, made) / "request.json").read_bytes()
    request = json.loads(raw)
    parts = [sha(data[i:i + PART_BYTES]) for i in range(0, len(data), PART_BYTES)] or []
    man = {"kind": "engram-imprint-manifest", "version": 1, "imprint_id": request["imprint_id"],
           "filter": "imprint-filter-v1", "plan_digest": plan_digest or request["plan_digest"],
           "request_sha256": sha(raw), "built_at": "2026-10-25T18:04:11Z", "engram_commit": "3269091" + "0" * 33,
           "source": {"instance_id": request["source_instance_id"], "identity": "present",
                      "ancestry": list(request["source_ancestry"]),
                      "ancestry_complete": request["source_ancestry_complete"]},
           "schema": {"applied": [1, 2, 3, 28]}, "embedding": {"model": "nomic-ai/nomic-embed-text-v1.5", "dimension": 768},
           "vec": {"create_version": "v0.1.7"}, "scope": copy.deepcopy(request["scope"]),
           "contents": copy.deepcopy(request["contents"]), "others": copy.deepcopy(request["others"]),
           "package": {"file": "imprint.db", "bytes": len(data), "sha256": sha(data), "part_bytes": PART_BYTES,
                       "parts": parts}}
    if differ:
        other = {"scope": lambda m: m["scope"].update(lanes=["personal"]),
                 "contents": lambda m: m["contents"].update(episodes=m["contents"]["episodes"] + 1),
                 "others": lambda m: m["others"].update(people=1),
                 "imprint_id": lambda m: m.update(imprint_id=str(uuid.uuid4())),
                 "plan_digest": lambda m: m.update(plan_digest="1" * 64),
                 "request_sha256": lambda m: m.update(request_sha256="2" * 64),
                 "source.instance_id": lambda m: m["source"].update(instance_id=str(uuid.uuid4())),
                 "source.ancestry": lambda m: m["source"].update(ancestry=[str(uuid.uuid4())]),
                 "source.ancestry_complete": lambda m: m["source"].update(
                     ancestry_complete=not m["source"]["ancestry_complete"]),
                 "package.bytes": lambda m: m["package"].update(bytes=m["package"]["bytes"] + 1),
                 "package.parts": lambda m: m["package"].update(parts=m["package"]["parts"][:-1] + ["3" * 64, "4" * 64])}
        other[differ](man)
    return man


def requested_with_package(st, nbytes=PART_BYTES + 5, ship="voyager", **changes):
    """A request for a package of `nbytes` pseudo-random bytes. Returns (made, data)."""
    data = random.Random(7).randbytes(nbytes)
    changes.setdefault("package.bytes", nbytes)
    changes.setdefault("package.parts", -(-nbytes // PART_BYTES))
    made = post(st, request_doc(**changes), ship).json()
    return made, data


def allowed_with_manifest(tmp_path, nbytes=PART_BYTES + 5, ship="voyager", **changes):
    tmp_path.mkdir(parents=True, exist_ok=True)
    st = station(tmp_path)
    made, data = requested_with_package(st, nbytes, ship, **changes)
    owner, password = (st.andy, ANDY_PASSWORD) if ship == "serenity" else (st.sam, "long-password-sam")
    assert confirm(owner, made, password=password).status_code == 200
    assert put_manifest(st, made, manifest_for_doc(st, made, data), ship).status_code == 200
    return st, made, data


def allowed_with_all_parts(tmp_path, nbytes=2 * PART_BYTES, ship="voyager", others=None, **changes):
    if others:
        changes.update({"others.memories": others["memories"], "others.people": others["people"],
                        "contents.imprint_subjects": others["memories"] + others["people"]})
    st, made, data = allowed_with_manifest(tmp_path, nbytes, ship, **changes)
    for n in range(-(-nbytes // PART_BYTES)):
        assert put_part(st, made, n, data[n * PART_BYTES:(n + 1) * PART_BYTES], ship).status_code == 200
    return st, made, data


def station_again(tmp_path, st):
    app = create_app(tmp_path / "peer", clock=lambda: st.clock[0], allowed_origins=["http://testserver"],
                     imprints_dir=tmp_path / "imprints")

    class Again:
        voyager = TestClient(app, base_url="http://testserver", headers=dict(st.voyager.headers))
    return Again


def fail_on_second_part(error):
    real, seen = imprints._copy_part, []

    def copy_part(src, dst):
        seen.append(src)
        if len(seen) == 2:
            raise error
        return real(src, dst)
    return copy_part


def test_manifest_before_parts(tmp_path):
    st = station(tmp_path); made, data = requested_with_package(st)
    assert put_manifest(st, made, manifest_for_doc(st, made, data)).status_code == 409          # before allowed
    assert confirm(st.sam, made).status_code == 200
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 409                       # before the manifest
    assert put_manifest(st, made, manifest_for_doc(st, made, data, plan_digest="0" * 64)).status_code == 400
    assert put_manifest(st, made, manifest_for_doc(st, made, data)).status_code == 200
    assert put_manifest(st, made, manifest_for_doc(st, made, data)).status_code == 409          # a second one


@pytest.mark.parametrize("field", ["scope", "contents", "others", "imprint_id", "plan_digest", "request_sha256",
                                   "source.instance_id", "source.ancestry", "source.ancestry_complete",
                                   "package.bytes", "package.parts"])                    # I 7.2's shared fields
def test_a_manifest_that_differs_from_the_request_in_any_shared_field_is_refused(tmp_path, field):
    st = station(tmp_path); made, data = requested_with_package(st); assert confirm(st.sam, made).status_code == 200
    assert put_manifest(st, made, manifest_for_doc(st, made, data, differ=field)).status_code == 400
    assert not (staged(st, made) / "manifest.json").exists()
    assert put_manifest(st, made, manifest_for_doc(st, made, data)).status_code == 200          # nothing was kept


@pytest.mark.parametrize("edit", [
    lambda m: m.update(extra=1), lambda m: m.update(version=2), lambda m: m.update(kind="x"),
    lambda m: m.update(filter="other"), lambda m: m.update(built_at="2026-10-25 18:04:11"),
    lambda m: m["package"].update(sha256="ABC"), lambda m: m["package"].update(part_bytes=1024),
    lambda m: m["package"]["parts"].__setitem__(0, "xyz"), lambda m: m["source"].update(identity="maybe"),
    lambda m: m["source"]["ancestry"].append("NOT-A-UUID"), lambda m: m.update(engram_commit=5),
    lambda m: m["embedding"].update(dimension=7.5)])
def test_manifest_formats(tmp_path, edit):
    st = station(tmp_path); made, data = requested_with_package(st); assert confirm(st.sam, made).status_code == 200
    man = manifest_for_doc(st, made, data)
    edit(man)
    assert put_manifest(st, made, man).status_code == 400


def test_a_manifest_must_be_canonical_and_small(tmp_path):
    st = station(tmp_path); made, data = requested_with_package(st); assert confirm(st.sam, made).status_code == 200
    man = manifest_for_doc(st, made, data)
    assert put_manifest(st, made, json.dumps(man, indent=2).encode()).status_code == 400
    assert put_manifest(st, made, b"x" * (256 * 1024 + 1)).status_code == 413
    assert put_manifest(st, made, canonical(man)).status_code == 200


def test_another_ship_gets_404_on_every_upload_route(tmp_path):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=PART_BYTES)
    rid, other = made["id"], st.other_ship
    assert other.put(f"/api/imprints/{rid}/manifest", content=canonical(manifest_for_doc(st, made, data))).status_code == 404
    assert other.put(f"/api/imprints/{rid}/parts/0", content=data).status_code == 404
    assert other.post(f"/api/imprints/{rid}/complete").status_code == 404
    assert other.get(f"/api/imprints/{rid}").status_code == 404 and st.jenn.get(f"/api/imprints/{rid}").status_code == 404
    assert st.voyager.get(f"/api/imprints/{rid}").json()["held"] == []
    assert st.sam.get(f"/api/imprints/{rid}").json()["status"] == "allowed"
    assert st.voyager.get(f"/api/imprints/{'0' * 32}").status_code == 404


def test_parts(tmp_path):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=2 * PART_BYTES)                  # an exact multiple: 2 parts
    assert put_part(st, made, 0, data[:-1][:PART_BYTES - 1]).status_code == 400              # wrong length
    assert put_part(st, made, 1, data[:PART_BYTES]).status_code == 400                       # wrong hash
    assert put_part(st, made, 2, data[:PART_BYTES]).status_code == 404                       # no such part
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 200
    before = part_files(tmp_path, made)
    assert "part-0" in before and not [n for n in before if n.endswith(".tmp")]
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 200 and part_files(tmp_path, made) == before
    restarted = station_again(tmp_path, st)                                                  # a new Store on the same data
    assert restarted.voyager.get(f"/api/imprints/{made['id']}").json()["held"] == [0]
    assert st.voyager.put(f"/api/imprints/{made['id']}/parts/1", content=b"x" * (6 * 2**20 + 1)).status_code == 413


def test_the_last_part_is_short(tmp_path):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=PART_BYTES + 5)
    assert put_part(st, made, 1, data[PART_BYTES:] + b"x").status_code == 400
    r = put_part(st, made, 1, data[PART_BYTES:])
    assert r.status_code == 200 and r.json() == {"held": [1]}


def test_parts_are_limited_to_120_a_minute_per_ship(tmp_path):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=PART_BYTES)
    codes = [put_part(st, made, 0, data).status_code for _ in range(121)]
    assert codes[:120] == [200] * 120 and codes[120] == 429
    assert put_part(st, made, 0, data, "serenity").status_code == 404                        # another ship has its own count
    st.clock[0] += 61
    assert put_part(st, made, 0, data).status_code == 200


def test_complete(tmp_path):
    st, made, data = allowed_with_all_parts(tmp_path)
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").json()["status"] == "received"
    joined = tmp_path / "peer" / "imprints" / made["id"] / "imprint.db"
    assert joined.read_bytes() == data and not list(joined.parent.glob("part-*"))
    found = row(st, made["id"])
    assert found["status"] == "received" and found["expires"] == NOW + WEEK
    receipt = st.store.imprint_receipts(made["id"])[-1]
    man = json.loads((joined.parent / "manifest.json").read_bytes())
    assert receipt["record"]["event"] == "received" and receipt["signature"]
    assert receipt["record"]["detail"] == {"bytes": len(data), "sha256": sha(data), "parts": 2,
                                           "manifest_sha256": sha(canonical(man))}
    lines = describe_pending(st.store.station_pending(), st.clock[0], "andy")
    assert "IMPRINT  from sam (ship voyager, machine test-host)" in lines
    notice = [n for n in st.store.station_notices() if n["id"].startswith("imprint-")][0]
    assert notice["text"] == "An imprint is waiting for Andy's review. He decides with make station-pending on the Pi."
    assert "sam" not in notice["text"] and "voyager" not in notice["text"]
    assert "have other people" not in lines                                                  # n = 0: no third line
    st2, made2, _ = allowed_with_all_parts(tmp_path / "home", ship="serenity", others={"memories": 37, "people": 3})
    st2.serenity.post(f"/api/imprints/{made2['id']}/complete")
    assert "37 memories have other people recorded on them (3 people); copied in andy's home as co-subjects" in \
        describe_pending(st2.store.station_pending(), st2.clock[0], "andy")


def test_the_pending_item_in_words_and_made_safe(tmp_path):
    st, made, data = allowed_with_all_parts(tmp_path)
    assert [i for i in st.store.station_pending() if i["kind"] == "imprint"] == []           # not before `received`
    st.voyager.post(f"/api/imprints/{made['id']}/complete")
    with st.store.transaction() as db:
        db.execute("UPDATE dockings SET machine=? WHERE ship_id=?", ("sam-laptop\n@andy RE-DOCK forged", st.ids["voyager"]))
    text = describe_pending(st.store.station_pending(), st.clock[0], "andy")
    first, *rest = text.split("\n")[1:]
    assert first.startswith(made["id"][:4] + "  IMPRINT  from sam (ship voyager, machine sam-laptop (at)andy RE-DOCK forged):")
    assert "store " + json.loads((staged(st, made) / "request.json").read_bytes())["source_instance_id"][:8] in first
    assert "1,204 episodes and 88 semantics" in first
    assert all(line.startswith("      ") for line in rest) and "work lane, since 2026-01-01" in rest[0]
    assert "for place:home/andy; recall, read, imprint, route;" in " ".join(rest)
    assert "purposes calibration, trail-evaluation; ends 2027-" in " ".join(rest)


def test_complete_needs_the_manifest_and_every_part(tmp_path):
    st = station(tmp_path); made, data = requested_with_package(st, 2 * PART_BYTES)
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").status_code == 409        # not allowed
    assert confirm(st.sam, made).status_code == 200
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").status_code == 409        # no manifest
    assert put_manifest(st, made, manifest_for_doc(st, made, data)).status_code == 200
    put_part(st, made, 0, data[:PART_BYTES])
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").status_code == 409        # a part missing
    assert row(st, made["id"])["status"] == "allowed"
    put_part(st, made, 1, data[PART_BYTES:])
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").status_code == 200
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").status_code == 409        # once


def test_a_package_whose_whole_hash_differs_is_refused(tmp_path):
    st = station(tmp_path); made, data = requested_with_package(st, PART_BYTES)
    assert confirm(st.sam, made).status_code == 200
    man = manifest_for_doc(st, made, data); man["package"]["sha256"] = "5" * 64
    assert put_manifest(st, made, man).status_code == 200
    assert put_part(st, made, 0, data).status_code == 200
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").status_code == 400
    folder = staged(st, made)
    assert not (folder / "imprint.db").exists() and not list(folder.glob("*.tmp")) and (folder / "part-0").exists()
    assert row(st, made["id"])["status"] == "allowed"


def test_rf2_failed_join_leaves_no_partial_file(tmp_path, monkeypatch):
    st, made, data = allowed_with_all_parts(tmp_path)
    monkeypatch.setattr(imprints, "_copy_part", fail_on_second_part(OSError(28, "No space left on device")))
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").status_code == 507
    staged_dir = tmp_path / "peer" / "imprints" / made["id"]
    assert not (staged_dir / "imprint.db").exists() and not list(staged_dir.glob("*.tmp")) and len(list(staged_dir.glob("part-*"))) == 2
    assert row(st, made["id"])["status"] == "allowed"
    monkeypatch.undo()
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").json()["status"] == "received"
