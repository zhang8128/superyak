"""Horizon/until miss the expiry of a grant behind a membership that a membership-grant's envelope relies on."""
import sys
sys.path.insert(0, "tests")
from permissions_support import World, T
from permissions import decide, Use, selector_json, parse_selector

w = World()
rio = w.agent("rio-grande", "place:home/andy", at="place:home/andy")
helper = w.agent("helper", "place:home/andy", at="place:home/andy")
w.store("S")
C1, C2 = "collection:andy/c1", "collection:andy/c2"
M = "mem:S/episode/m1"
env1 = selector_json(parse_selector({"audience": ["self"], "requesters": "*", "objects": {
    "kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*", "collections": [C2], "memories": "*"},
    "actions": "*", "purposes": "*"}))
env2 = selector_json(parse_selector({"audience": ["self"], "requesters": "*", "objects": {
    "kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*", "collections": "*", "memories": "*"},
    "actions": "*", "purposes": "*"}))
g1 = w.grant("person:andy", helper, "place:home/andy", ops=("collect",), envelope=env1, expires=T("2026-11-30"))
g2 = w.grant("person:andy", helper, "place:home/andy", ops=("collect",), envelope=env2, expires=T("2026-11-05"))
w.collect(C1, [M], backing="grant:" + g1)
w.collect(C2, [M], backing="grant:" + g2)
w.allow("place:home/andy", audience=["self"], collections=[C1], actions=["recall"])
s = w.state()
u = Use(rio, "place:home/andy", M, "store:S", "recall", "care-coordination", T("2026-11-02"))
d = decide(s, u)
print("allowed at 11-02:", d.allowed, "until:", d.until, "horizon:", d.horizon)
print("G2 expires:", T("2026-11-05"), " G1 expires:", T("2026-11-30"))
from dataclasses import replace
d2 = decide(s, replace(u, at=T("2026-11-05")))
print("allowed at 11-05 (same state):", d2.allowed, d2.refusal)
if d.allowed and not d2.allowed and (d.horizon is None or d.horizon > T("2026-11-05")):
    print("BUG: horizon", d.horizon, "is past the time the decision flips; a cache to the horizon serves a stale allow")
