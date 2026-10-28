import pytest
from permissions import (RuleError, STAR, check_id, home_of, parse_copy_ref, parse_object_ref,
                         parse_selector, person_of_home, receipt_short, resolve_prefix, selector_json,
                         short_id)

def test_u2_identifier_grammars():
    assert check_id("person", "person:andy") == "person:andy"
    assert check_id("agent", "agent:ph-coordinator") == "agent:ph-coordinator"
    assert check_id("agent", "agent:Engram_1") == "agent:Engram_1"
    assert check_id("place", "place:la-county/public-health/clinic-3")
    assert check_id("place", "place:home/andy")
    assert check_id("collection", "collection:andy/" + "a" * 80)
    assert home_of("person:andy") == "place:home/andy"
    assert person_of_home("place:home/andy") == "person:andy"
    assert person_of_home("place:la-county") is None
    for kind, bad in [("place", "place:home"), ("place", "place:" + "/".join("a" * 9)),
                      ("place", "place:" + "/".join(["b" * 63] * 5)),  # 319 characters > 255
                      ("place", "place:home/andy/den"), ("group", "group:outside-home"),
                      ("collection", "collection:andy/" + "a" * 81), ("record", "r-" + "a" * 31)]:
        with pytest.raises(RuleError):
            check_id(kind, bad)
    with pytest.raises(RuleError, match="255"):
        check_id("place", "place:" + "/".join(["b" * 63] * 5))
    assert check_id("record", "r-" + "a" * 32) and check_id("use", "u-" + "0" * 32)

def test_rf4_ids_refuse_newline_case_and_non_ascii():
    for kind, bad in [("person", "person:andy\n"), ("person", "person:Andy"), ("person", "person:аndy"),
                      ("place", "place:la-county\n"), ("place", "place:La-County"), ("agent", "agent:eng ram"),
                      ("record", "r-" + "A" * 32), ("record", "r-" + "a" * 32 + "\n")]:
        with pytest.raises(RuleError):
            check_id(kind, bad)

def test_rule_error_text():
    with pytest.raises(RuleError) as e:
        check_id("person", "person:Andy")
    assert e.value.rule.startswith("4.1") and str(e.value).startswith(e.value.rule + ": ")

def test_object_and_copy_refs():
    assert parse_object_ref("mem:9b1e/episode/m1") == ("memory", "9b1e", "episode", "m1")
    assert parse_object_ref("trail:9b1e/t7").kind == "trail"
    assert parse_object_ref("road:9b1e/c1") == ("road", "9b1e", None, "c1")
    assert parse_copy_ref("imprint:" + "5d" * 32 + "/c0a8f5e2").station == "5d" * 32
    assert parse_copy_ref("store:9b1e") == ("store", "9b1e", None)
    for bad in ["mem:9b1e/instinct/i1", "store:", "imprint:abc"]:
        with pytest.raises(RuleError):
            (parse_copy_ref if bad.startswith(("store", "imprint")) else parse_object_ref)(bad)

DOC = {"audience": ["place:la-county/public-health"], "requesters": "*",
       "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                   "collections": ["collection:andy/medical-history"], "memories": "*"},
       "actions": ["read", "recall", "inject_context"], "purposes": ["care-coordination"]}

def test_selector_canonical_form_and_bounds():
    doc = {**DOC, "actions": ["recall", "read", "inject_context"]}
    sel = parse_selector(doc)
    assert sel.actions == ("inject_context", "read", "recall") and sel.memories == STAR
    assert parse_selector(selector_json(sel)) == sel
    for key, value in [("audience", "*"), ("audience", [f"group:g{i:02d}" for i in range(33)]),
                       ("purposes", [f"p{i}" for i in range(17)]), ("actions", ["recall", "recall"])]:
        with pytest.raises(RuleError):
            parse_selector({**doc, key: value})
    with pytest.raises(RuleError):
        parse_selector({**doc, "objects": {**doc["objects"], "memories": [f"mem:s/episode/m{i}" for i in range(513)]}})
    ok = parse_selector({**doc, "objects": {**doc["objects"], "memories": [f"mem:s/episode/m{i}" for i in range(512)]}})
    assert len(ok.memories) == 512

def test_selector_keys_values_and_reserved_group():
    bad_docs = [{k: v for k, v in DOC.items() if k != "purposes"},
                {**DOC, "extra": 1},
                {**DOC, "objects": {k: v for k, v in DOC["objects"].items() if k != "lanes"}},
                {**DOC, "objects": {**DOC["objects"], "bogus": "*"}},
                {**DOC, "audience": ["group:outside-home"]},
                {**DOC, "requesters": ["group:outside-home"]},
                {**DOC, "audience": ["place:Bad"]},
                {**DOC, "actions": ["delete"]},
                {**DOC, "purposes": []}]
    for d in bad_docs:
        with pytest.raises(RuleError):
            parse_selector(d)
    with pytest.raises(RuleError):
        parse_selector("not json")

def test_selector_road_and_trail_dimensions_must_be_star():
    doc = {"audience": ["self"], "requesters": "*", "actions": ["route"], "purposes": "*",
           "objects": {"kinds": ["road"], "stores": ["s1"], "layers": "*", "lanes": ["work"],
                       "collections": "*", "memories": "*"}}
    with pytest.raises(RuleError, match="5.2"):
        parse_selector(doc)
    # R25: kinds "*" counts too
    with pytest.raises(RuleError, match="5.2"):
        parse_selector({**doc, "objects": {**doc["objects"], "kinds": "*"}})
    parse_selector({**doc, "objects": {**doc["objects"], "lanes": "*"}})

def test_u26_prefix_resolution():
    ids = ["r-7f3a" + "0" * 28, "r-7f3b" + "0" * 28, "r-0b9e" + "1" * 28]
    assert resolve_prefix(ids, "r-0b9e") == ids[2] and resolve_prefix(ids, ids[0]) == ids[0]
    with pytest.raises(RuleError, match="r-7f3a.*r-7f3b"):
        resolve_prefix(ids, "r-7f3")
    with pytest.raises(RuleError):
        resolve_prefix(ids, "r-0b9")  # fewer than 4 hex
    ids2 = ["r-7f3a" + "0" * 28, "r-7f3a" + "1" * 28]
    with pytest.raises(RuleError, match="r-7f3a0.*r-7f3a1"):
        resolve_prefix(ids2, "r-7f3a")
    assert short_id(ids[0]) == "#7f3a" and receipt_short("u-5e21a9c0" + "f" * 24) == "#5e21a9c0"
