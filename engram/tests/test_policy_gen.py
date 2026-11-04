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
        ["urn:engram:engram"], ["urn:engram:stranger"], ["urn:engram:why"],
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


def test_receiver_permutations_have_identical_digest_and_bytes(tmp_path):
    g = _groups(tmp_path)
    kw = dict(publisher="lighthouse", groups=g,
              issued_at="2026-09-02T00:00:00Z", valid_from="2026-09-01T00:00:00Z",
              valid_until="2027-01-01T00:00:00Z")
    first = build_publisher_policy(
        receivers=["engram", "why", "stranger"], **kw
    )
    second = build_publisher_policy(
        receivers=["stranger", "engram", "why"], **kw
    )
    assert first["digest"] == second["digest"]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write_receiver_policy(a, first)
    write_receiver_policy(b, second)
    assert a.read_bytes() == b.read_bytes()


# Ship home and crossing plan, Task 10 (P24, S6, "an expiry someone will see"): remote grants, through one helper.

import fcntl
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lighthouse_protocol import verify_artifact_digest
from lighthouse_validation import load_owned_policy

REF = "urn:superyak:" + "a" * 64 + ":store:2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d"
ENGRAM = Path(__file__).resolve().parent.parent


def test_a_generated_policy_takes_a_remote_receiver_by_its_exact_ref(tmp_path):
    from policy_gen import remote_grant
    artifact = build_publisher_policy(publisher="house", receivers=["tardis"], groups={}, issued_at="2026-11-03T00:00:00Z",
                                      valid_from="2026-11-03T00:00:00Z", valid_until="2027-01-01T00:00:00Z",
                                      remote_receivers={REF: ["commons"]})
    [remote] = [r for r in artifact["payload"]["rules"] if REF in r["publishers"]]
    assert remote["publishers"] == [REF] and remote["effect"] == "allow"
    assert artifact["extensions"]["engram:audiences"][REF] == ["commons"]
    path = tmp_path / "policy.json"
    write_receiver_policy(path, artifact)
    assert load_owned_policy(path, "house").rules
    for bad in ("urn:superyak:" + "a" * 64 + ":ship:x", "urn:engram:tardis", REF + "x", "*"):
        with pytest.raises(ValueError):
            build_publisher_policy(publisher="house", receivers=[], groups={}, issued_at="2026-11-03T00:00:00Z",
                                   valid_from="2026-11-03T00:00:00Z", valid_until="2027-01-01T00:00:00Z",
                                   remote_receivers={bad: ["commons"]})
    with pytest.raises(ValueError):
        remote_grant(REF, ["not an audience"], context="memory/technical", purpose="session-recall",
                     valid_from="2026-11-03T00:00:00Z", valid_until="2027-01-01T00:00:00Z")


def _fixture_house(home):
    """instances/why/lighthouse-policy.json as build_publisher_policy writes one, for the local receiver tardis."""
    inst = home / ".engram" / "instances" / "why"
    inst.mkdir(parents=True)
    artifact = build_publisher_policy(publisher="why", receivers=["tardis"], groups={}, issued_at="2026-11-01T00:00:00Z",
                                      valid_from="2026-11-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    write_receiver_policy(inst / "lighthouse-policy.json", artifact)
    return inst / "lighthouse-policy.json"


def grant(home, *extra, ref=REF, audiences=("commons",)):
    args = [sys.executable, "-I", "-m", "policy_gen", "grant-remote", "--engram-home", str(home), "--house", "why",
            "--ref", ref, "--context", "memory/technical", "--purpose", "session-recall"]
    for audience in audiences:
        args += ["--audience", audience]
    return subprocess.run(args + list(extra), cwd=ENGRAM, capture_output=True, text=True, timeout=60)


def test_grant_remote_adds_one_rule_and_one_audience_entry_and_keeps_a_bak(tmp_path):
    path = _fixture_house(tmp_path)
    old = path.read_bytes()
    before = json.loads(old)
    done = grant(tmp_path, audiences=("commons", "group:work"))
    assert done.returncode == 0, done.stderr
    after = json.loads(path.read_text())
    added = [r for r in after["payload"]["rules"] if r not in before["payload"]["rules"]]
    assert len(after["payload"]["rules"]) == len(before["payload"]["rules"]) + 1 and len(added) == 1
    [rule] = added
    assert rule["id"] == "remote:" + "a" * 12 + ":2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d"
    assert (rule["publishers"], rule["actions"], rule["contexts"], rule["purposes"], rule["audiences"]) == (
        [REF], ["recall", "read"], ["memory/technical"], ["session-recall"], ["self"])
    audiences = after["extensions"]["engram:audiences"]
    assert audiences[REF] == ["commons", "group:work"]
    assert {k: v for k, v in audiences.items() if k != REF} == before["extensions"]["engram:audiences"]
    assert load_owned_policy(path, "why").rules and verify_artifact_digest(after)
    assert (path.parent / "lighthouse-policy.json.bak").read_bytes() == old
    start = datetime.fromisoformat(rule["validFrom"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(rule["validUntil"].replace("Z", "+00:00"))
    assert abs((start - datetime.now(timezone.utc)).total_seconds()) < 120   # validFrom is now
    assert end - start == timedelta(days=90)                                 # never open-ended: 90 days by default
    assert rule["validUntil"] in done.stdout                                  # the date is printed


def test_grant_remote_until_sets_the_end_up_to_366_days(tmp_path):
    path = _fixture_house(tmp_path)
    until = (datetime.now(timezone.utc) + timedelta(days=300)).strftime("%Y-%m-%d")
    assert grant(tmp_path, "--until", until).returncode == 0
    [rule] = [r for r in json.loads(path.read_text())["payload"]["rules"] if REF in r["publishers"]]
    assert rule["validUntil"].startswith(until)
    other = _fixture_house(tmp_path / "far")
    before = other.read_bytes()
    too_far = (datetime.now(timezone.utc) + timedelta(days=367)).strftime("%Y-%m-%d")
    done = grant(tmp_path / "far", "--until", too_far)
    assert done.returncode == 1 and "366" in done.stderr and other.read_bytes() == before


@pytest.mark.parametrize("case", ["malformed ref", "a ship ref", "invalid audience", "already granted"])
def test_grant_remote_refuses_and_leaves_the_file_unchanged(tmp_path, case):
    path = _fixture_house(tmp_path)
    if case == "already granted":
        assert grant(tmp_path).returncode == 0
    before = path.read_bytes()
    if case == "malformed ref":
        done = grant(tmp_path, ref=REF[:-1])
    elif case == "a ship ref":
        done = grant(tmp_path, ref="urn:superyak:" + "a" * 64 + ":ship:abc")
    elif case == "invalid audience":
        done = grant(tmp_path, audiences=("Not One",))
    else:
        done = grant(tmp_path)
    assert done.returncode == 1, done.stdout
    assert path.read_bytes() == before


def test_a_second_grant_remote_while_one_edits_is_refused(tmp_path):
    path = _fixture_house(tmp_path)
    before = path.read_bytes()
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # as a running grant-remote holds it
        done = grant(tmp_path)
    finally:
        os.close(fd)
    assert done.returncode == 1 and "another" in done.stderr
    assert path.read_bytes() == before
    assert grant(tmp_path).returncode == 0
