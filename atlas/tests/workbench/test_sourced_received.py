"""North-star test 5's transport, the receiving side in Atlas (docs/superpowers/specs/2026-11-22-claim-crossing-transport-
design.md, T6): `received(file, own_publications)` reads what the peer's `atlas-received` wrote. It checks the file's
sender against its key and every artifact's issuer against that sender, a carried claim against what this store really
published, and a notice against what it names. Then Atlas's own validation runs. The signature itself is the peer's
`atlas-verify`; Atlas has no Ed25519, so this is a consistency check."""
import base64
import hashlib
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ATLAS))
from workbench.sourced import publish_sourced, seal_notice, source_key  # noqa: E402
from workbench.sourced_received import received  # noqa: E402
from workbench.sourced_relation import held_claims, relation  # noqa: E402

AT = "2026-11-22T10:00:00Z"
KEYS = {name: bytes([n]) * 32 for n, name in enumerate(("pi", "tardis", "third"), start=1)}
PEER = {name: hashlib.sha256(key).hexdigest() for name, key in KEYS.items()}


def uri(name):
    return f"urn:superyak:peer:{PEER[name]}"


def publication(name, *, sources, items, carried=(), rules=None, peer=None):
    issuer = uri(peer or name)
    bundle = {"schema_version": 1, "title": f"{name} store", "sources": sources, "items": items, "relations": []}
    return publish_sourced(bundle, {
        "issuer": issuer, "name": f"{name} store", "origin": f"{issuer}:collection",
        "context": {"id": f"{issuer}:context", "path": ["research"]}, "item_ids": [i["id"] for i in items],
        "issued_at": AT, "rules": rules or [], "copied_from": {}, "carried": list(carried)})


def source(sid, url, title="A shared paper", year=2024):
    return {"id": sid, "title": title, "url": url, "year": year, "citation": ""}


def claim(iid, *sources):
    return {"id": iid, "kind": "claim", "title": f"Claim {iid}", "summary": "A fictional result.",
            "status": "source_reported", "evidence": [{"source_id": s, "locator": "p1"} for s in sources]}


def kept(sender, receiver, body, *, kind="publication"):
    """What `atlas-received` writes, without the signature Atlas can't check."""
    envelope = {"version": 1, "event_id": "e" * 32, "origin": PEER[sender], "destination": PEER[receiver],
                "actor": {"peer": PEER[sender], "id": "ship"}, "action": f"atlas.{kind}",
                "payload": {"package" if kind == "publication" else "notice": body}}
    return {"format": "atlas-received", "version": 1, "envelope": envelope,
            "signing_key": base64.b64encode(KEYS[sender]).decode(), "receiver": PEER[receiver],
            "delivered": {"origin": PEER[sender], "actor": "ship", "event_id": "e" * 32}}


@pytest.fixture
def stores():
    pi = publication("pi", sources=[source("pi-S1", "https://journal.example/a")], items=[claim("P1", "pi-S1")])
    tardis = publication("tardis", sources=[source("t-S1", "https://www.journal.example/a/")],
                         items=[claim("T1", "t-S1")])
    return pi, tardis


def test_a_received_publication_feeds_relation_as_the_fixtures_do(stores):
    pi, tardis = stores
    got = received(kept("pi", "tardis", pi), [tardis])
    assert got["origin"] == PEER["pi"] and got["package"] == pi
    held = held_claims([tardis, got["package"]])
    answer = relation(pi["claims"][0]["digest"], tardis["claims"][0]["digest"], held)
    assert answer["answer"] == "same sources"


@pytest.mark.parametrize("edit, words", [
    (lambda k: k["delivered"].__setitem__("origin", "f" * 64), "The file's sender doesn't match its key"),
    (lambda k: k.__setitem__("signing_key", base64.b64encode(KEYS["third"]).decode()), "The file's sender doesn't match its key"),
    (lambda k: k["envelope"].__setitem__("action", "room.message"), "Not a received atlas file"),
])
def test_a_file_whose_sender_was_edited_fails_the_consistency_check(stores, edit, words):
    pi, tardis = stores
    file = kept("pi", "tardis", pi)
    edit(file)
    with pytest.raises(ValueError, match=words):
        received(file, [tardis])


def test_a_publication_issued_as_another_peer_is_refused(stores):
    pi, tardis = stores
    as_third = publication("pi", sources=[source("pi-S1", "https://journal.example/a")], items=[claim("P1", "pi-S1")],
                           peer="third")
    with pytest.raises(ValueError, match="must all be issued by the peer that delivered it"):
        received(kept("pi", "tardis", as_third), [tardis])


def test_a_carried_claim_issued_as_the_receivers_own_must_be_one_it_published(stores):
    pi, tardis = stores
    real = {"claim": tardis["claims"][0], "snapshot": tardis["snapshot"]}
    honest = publication("pi", sources=[source("pi-S1", "https://journal.example/a")], items=[claim("P1", "pi-S1")],
                         carried=[real])
    assert received(kept("pi", "tardis", honest), [tardis])["package"] == honest
    forged_tardis = publication("tardis", sources=[source("t-S9", "https://elsewhere.example/z", "Never said")],
                                items=[claim("T9", "t-S9")])
    forged = publication("pi", sources=[source("pi-S1", "https://journal.example/a")], items=[claim("P1", "pi-S1")],
                         carried=[{"claim": forged_tardis["claims"][0], "snapshot": forged_tardis["snapshot"]}])
    with pytest.raises(ValueError, match="this store never published"):
        received(kept("pi", "tardis", forged), [tardis])


def test_with_no_own_publications_every_receiver_issued_carried_claim_is_refused(stores):
    pi, tardis = stores
    carrying = publication("pi", sources=[source("pi-S1", "https://journal.example/a")], items=[claim("P1", "pi-S1")],
                           carried=[{"claim": tardis["claims"][0], "snapshot": tardis["snapshot"]}])
    with pytest.raises(ValueError, match="carried claim"):
        received(kept("pi", "tardis", carrying), [])


def test_a_carried_claim_from_a_third_issuer_is_refused(stores):
    pi, tardis = stores
    third = publication("third", sources=[source("h-S1", "https://journal.example/a")], items=[claim("H1", "h-S1")])
    carrying = publication("pi", sources=[source("pi-S1", "https://journal.example/a")], items=[claim("P1", "pi-S1")],
                           carried=[{"claim": third["claims"][0], "snapshot": third["snapshot"]}])
    with pytest.raises(ValueError, match="carried claim"):
        received(kept("pi", "tardis", carrying), [tardis])


def notice_for(pi, record_id="pi-S1"):
    keys = source_key(source(record_id, "https://journal.example/a"))
    return seal_notice({"notice": "retraction", "record_id": record_id, "keys": keys}, [pi["snapshot"]], uri("pi"),
                       {"id": f"{uri('pi')}:context", "path": ["research"]}, AT)


def test_a_notice_is_read_against_what_it_names(stores):
    pi, tardis = stores
    notice = notice_for(pi)
    assert received(kept("pi", "tardis", notice, kind="notice"), [tardis], received_publications=[pi])["notice"] == notice


def test_an_early_notice_names_the_snapshot_it_waits_for(stores):
    pi, tardis = stores
    with pytest.raises(ValueError) as caught:
        received(kept("pi", "tardis", notice_for(pi), kind="notice"), [tardis])
    assert pi["snapshot"]["digest"]["value"][:12] in str(caught.value) and "not held here yet" in str(caught.value)


def test_a_notice_issued_by_anyone_but_its_sender_is_refused(stores):
    pi, tardis = stores
    with pytest.raises(ValueError, match="must be issued by the peer that delivered it"):
        received(kept("tardis", "pi", notice_for(pi), kind="notice"), [pi], received_publications=[pi])


def test_a_notice_naming_another_issuers_snapshot_is_refused(stores):
    pi, tardis = stores
    keys = source_key(source("t-S1", "https://www.journal.example/a/"))
    notice = seal_notice({"notice": "retraction", "record_id": "t-S1", "keys": keys}, [tardis["snapshot"]], uri("pi"),
                         {"id": f"{uri('pi')}:context", "path": ["research"]}, AT)
    with pytest.raises(ValueError, match="another issuer"):
        received(kept("pi", "tardis", notice, kind="notice"), [tardis], received_publications=[pi])
