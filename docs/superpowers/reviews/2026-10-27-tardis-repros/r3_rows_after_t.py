"""Rows already in the State but logged after `at`: a removed placement still admits, a new co-subject is skipped."""
import sys
sys.path.insert(0, "tests")
from permissions_support import World, T
from permissions import decide, Use, subjects_of

w = World()
w.person("jenn")
rio = w.agent("rio-grande", "place:home/andy", at="place:home/andy")
w.store("S")
M = "mem:S/episode/m1"
w.allow("place:home/andy", audience=["self"], actions=["recall"])
t = w.now
w.tick(1)                        # the next write is logged one second after the caller read its clock
w.subject(M, "person:jenn")      # Jenn (registered, empty home layer) becomes a co-subject
w.leave(rio)                     # and Rio Grande is removed from Andy's home
s = w.state()
u = Use(rio, "place:home/andy", M, "store:S", "recall", "p", t)
print("subjects at t:", subjects_of(s, M, t))
d = decide(s, u)
print("decide at t (state includes both writes):", d.allowed, d.refusal)
d2 = decide(s, Use(rio, "place:home/andy", M, "store:S", "recall", "p", t + 1))
print("decide at t+1:", d2.allowed, d2.refusal)
