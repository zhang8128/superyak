import base64

import pytest

from superyak_peer.identity import PeerIdentity, verify_record, verify_station_record


def public_b64(ident):
    return base64.b64encode(ident.public_key).decode()


def example_permission(station):
    inner = {"id": "r-" + "5b0d" * 8, "layer": "place:home/sam", "effect": "allow",
             "selector": {"audience": ["place:home/andy"], "requesters": ["agent:station-imprints"],
                          "objects": {"kinds": ["memory"], "stores": ["3f2a9c1e"], "layers": "*", "lanes": "*",
                                      "collections": ["collection:sam/imprint-c0a8f5e2"], "memories": "*"},
                          "actions": ["imprint", "read", "recall"], "purposes": ["calibration"]},
             "valid_from": 1792951950, "valid_until": 1800727950, "anchor": 1792951950, "backing": "person",
             "set_by": "person:sam", "channel": "browser", "under_grant": None, "proposal_id": None,
             "replaces": None, "reason": "imprint c0a8 at Deep Space 9", "created": 1792951950}
    return {"kind": "imprint-permission", "station": station, "id": "a" * 32, "owner": "person:sam",
            "owner_id": "u1", "ship_id": "s1", "imprint_id": "c0a8f5e2", "source_instance_id": "3f2a9c1e",
            "request_sha256": "0" * 64, "plan_digest": "9d3e", "attestation": "no-unconsented-others-v1",
            "created": 1792951950, "records": [inner]}


def example_receipt(station):
    return {"kind": "imprint-receipt", "station": station, "id": "b" * 32, "permission": "a" * 32,
            "event": "approved", "actor_id": None, "at": 1792956600, "detail": {}, "previous": "1" * 64}


def test_both_kinds_sign_with_exactly_their_keys(tmp_path):
    ident = PeerIdentity.load_or_create(tmp_path / "id")
    perm, receipt = example_permission(ident.peer_id), example_receipt(ident.peer_id)
    for record in (perm, receipt):
        assert verify_station_record(public_b64(ident), record, ident.sign_record(record))
        with pytest.raises(ValueError):
            ident.sign_record({**record, "extra": 1})


def test_verify_station_record_is_false_for_anything_else(tmp_path):
    ident, other = PeerIdentity.load_or_create(tmp_path / "a"), PeerIdentity.load_or_create(tmp_path / "b")
    perm = example_permission(ident.peer_id)
    sig = ident.sign_record(perm)
    inner_extra = {**perm, "records": [{**perm["records"][0], "revoked": None}]}
    for key, record, signature in [(public_b64(other), perm, sig), (public_b64(ident), {**perm, "station": other.peer_id}, sig),
                                   (public_b64(ident), {**perm, "kind": "imprint-receipt"}, sig),
                                   (public_b64(ident), inner_extra, sig), (public_b64(ident), perm, "not base64!"),
                                   ("!!", perm, sig), (public_b64(ident), ["not", "a", "dict"], sig)]:
        assert verify_station_record(key, record, signature) is False


def test_an_imprint_record_is_no_grant_and_no_envelope(tmp_path):
    ident = PeerIdentity.load_or_create(tmp_path / "id")
    perm = example_permission(ident.peer_id)
    assert not verify_record(ident.card("https://smart.example", {"id": "andy", "name": "Andy"}),
                             {**perm, "kind": "grant"}, ident.sign_record(perm))
