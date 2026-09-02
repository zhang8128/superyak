import json

import pytest

from lighthouse_policy import load_policy
from lighthouse_protocol import artifact_digest
from policy_gen import (audiences_for_instance, build_publisher_policy, load_groups,
                        write_receiver_policy)

GROUPS = """
[groups.engram-system]
members = ["engram", "why"]

[groups.crossing]
members = ["engram", "lighthouse"]
"""


def _groups(tmp_path):
    p = tmp_path / "groups.toml"
    p.write_text(GROUPS)
    return load_groups(p)


def test_load_groups(tmp_path):
    g = _groups(tmp_path)
    assert g == {"engram-system": ["engram", "why"], "crossing": ["engram", "lighthouse"]}


def test_audiences_include_commons_and_every_group_joined(tmp_path):
    g = _groups(tmp_path)
    assert audiences_for_instance(g, "engram") == ["commons", "group:crossing", "group:engram-system"]
    assert audiences_for_instance(g, "why") == ["commons", "group:engram-system"]
    assert audiences_for_instance(g, "stranger") == ["commons"]


def test_bad_group_names_and_members_fail_closed(tmp_path):
    for bad in ('[groups."Engram"]\nmembers = ["a"]\n', '[groups.ok]\nmembers = "engram"\n',
                '[groups.ok]\nmembers = []\n', '[groups.ok]\nmembers = ["Engram"]\n'):
        p = tmp_path / "bad.toml"
        p.write_text(bad)
        with pytest.raises(ValueError):
            load_groups(p)


def test_publisher_policy_has_receiver_rules_and_audience_map(tmp_path):
    g = _groups(tmp_path)
    art = build_publisher_policy(
        publisher="lighthouse", receivers=["engram", "why", "stranger"], groups=g,
        issued_at="2026-09-02T00:00:00Z", valid_from="2026-09-01T00:00:00Z",
        valid_until="2027-01-01T00:00:00Z",
    )
    assert art["issuer"] == "urn:engram:lighthouse"
    assert art["id"] == "urn:policy:lighthouse-publisher"
    assert [rule["publishers"] for rule in art["payload"]["rules"]] == [
        ["urn:engram:engram"], ["urn:engram:why"], ["urn:engram:stranger"],
    ]
    assert art["extensions"]["engram:audiences"] == {
        "urn:engram:engram": ["commons", "group:crossing", "group:engram-system"],
        "urn:engram:why": ["commons", "group:engram-system"],
        "urn:engram:stranger": ["commons"],
    }
    fields = {
        "actions", "audiences", "claimMediaTypes", "contexts", "domains", "effect",
        "id", "profiles", "publishers", "purposes", "requiredAttestations",
        "requiredEvidence", "validFrom", "validUntil",
    }
    assert all(set(rule) == fields for rule in art["payload"]["rules"])


def test_built_publisher_policy_loads_and_digests(tmp_path):
    g = _groups(tmp_path)
    art = build_publisher_policy(
        publisher="lighthouse", receivers=["engram"], groups=g,
        issued_at="2026-09-02T00:00:00Z", valid_from="2026-09-01T00:00:00Z",
        valid_until="2027-01-01T00:00:00Z",
    )
    assert art["digest"] == artifact_digest(art)          # artifact_digest returns the whole dict
    assert art["digest"]["algorithm"] == "sha-256"
    path = tmp_path / "lighthouse-policy.json"
    digest = write_receiver_policy(path, art)
    assert digest == art["digest"]["value"]  # write_receiver_policy returns the hex value
    load_policy(path)  # must not raise


def test_regeneration_is_byte_stable(tmp_path):
    g = _groups(tmp_path)
    kw = dict(publisher="lighthouse", receivers=["engram", "why"], groups=g,
              issued_at="2026-09-02T00:00:00Z", valid_from="2026-09-01T00:00:00Z",
              valid_until="2027-01-01T00:00:00Z")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write_receiver_policy(a, build_publisher_policy(**kw))
    write_receiver_policy(b, build_publisher_policy(**kw))
    assert a.read_bytes() == b.read_bytes()
