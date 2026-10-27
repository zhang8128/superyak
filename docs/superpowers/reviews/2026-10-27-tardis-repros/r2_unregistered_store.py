"""An object in a store with no `stores` row is decided on its co-subjects / copy source instead of NO_LAYER (P32)."""
import sys
sys.path.insert(0, "tests")
from permissions_support import World, T
from permissions import decide, Use, subjects_of

w = World()
w.person("jenn")
rio = w.agent("rio-grande", "place:home/andy", at="place:home/andy")
w.store("S")                                    # Andy's own store
w.store("house", place="place:home/andy")       # the house that serves placements
SRC, COPY = "mem:S/episode/m1", "mem:K/episode/c1"   # K: no stores row
# (a) a kept copy recorded into an unregistered store: record_copy writes these rows without checking K
w.copy(COPY, SRC)
w.subject(COPY, "person:andy")
w.allow("place:home/andy", audience=["self"], actions=["recall"])
s = w.state()
u = Use(rio, "place:home/andy", COPY, "store:house", "recall", "care-coordination", T("2026-11-02"))
print("K registered?", "K" in s.stores, " subjects_of:", subjects_of(s, COPY, u.at))
d = decide(s, u)
print("decision:", d.allowed, d.refusal, [(c.layer, c.verdict) for c in d.cited])
# (b) the same with only a co-subject row (no copy)
w2 = World(); w2.person("jenn")
rio2 = w2.agent("rio-grande", "place:home/andy", at="place:home/andy")
w2.store("house")
w2.subject("mem:K/episode/x", "person:andy")
w2.allow("place:home/andy", audience=["self"], actions=["recall"])
d2 = decide(w2.state(), Use(rio2, "place:home/andy", "mem:K/episode/x", "store:house", "recall", "p", T("2026-11-02")))
print("co-subject only:", d2.allowed, d2.refusal)
