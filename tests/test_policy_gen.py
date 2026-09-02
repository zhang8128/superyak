import json

import pytest

from lighthouse_policy import load_policy
from lighthouse_protocol import artifact_digest
from policy_gen import (audiences_for_instance, build_receiver_policy, load_groups,
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


def test_built_policy_loads_and_digests(tmp_path):
    g = _groups(tmp_path)
    art = build_receiver_policy(instance="engram", publisher="lighthouse", groups=g,
                                issued_at="2026-09-02T00:00:00Z", valid_from="2026-09-01T00:00:00Z",
                                valid_until="2027-01-01T00:00:00Z")
    assert art["issuer"] == "urn:engram:engram"
    assert art["payload"]["rules"][0]["publishers"] == ["urn:engram:lighthouse"]
    assert art["extensions"]["engram:audiences"] == ["commons", "group:crossing", "group:engram-system"]
    assert art["digest"] == artifact_digest(art)          # artifact_digest returns the whole dict
    assert art["digest"]["algorithm"] == "sha-256"
    path = tmp_path / "lighthouse-policy.json"
    digest = write_receiver_policy(path, art)
    assert digest == art["digest"]["value"]  # write_receiver_policy returns the hex value
    load_policy(path)  # must not raise


def test_regeneration_is_byte_stable(tmp_path):
    g = _groups(tmp_path)
    kw = dict(instance="engram", publisher="lighthouse", groups=g,
              issued_at="2026-09-02T00:00:00Z", valid_from="2026-09-01T00:00:00Z",
              valid_until="2027-01-01T00:00:00Z")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write_receiver_policy(a, build_receiver_policy(**kw))
    write_receiver_policy(b, build_receiver_policy(**kw))
    assert a.read_bytes() == b.read_bytes()
