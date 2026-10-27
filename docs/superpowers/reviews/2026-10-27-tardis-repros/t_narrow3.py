import sys, os, json, re, shutil
from pathlib import Path
from drive import run
W = __import__("os").environ["W"]  # the repository checkout at the reviewed head
sys.path.insert(0, W + "/engram")
home = Path(sys.argv[1]); shutil.rmtree(home, ignore_errors=True); home.mkdir(parents=True)
IID = "0b7b3c2e-1111-4111-8111-111111111111"
M1, M2 = f"mem:{IID}/episode/m1", f"mem:{IID}/episode/m2"
def sel(coll, until_any=False):
    return json.dumps({"audience": ["place:home/doctor"], "requesters": "*", "actions": ["inject_context", "read", "recall"],
        "purposes": "*", "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                    "collections": coll, "memories": "*"}})
def go(*args):
    rc, out = run(home, list(args))
    last = [l for l in out.strip().splitlines() if l.strip()][-1]
    print(rc, " ".join(args[:2]), "->", last[:150]); return rc, out
go("init")
go("collection", "add", "doctor/med", M1)
rc, out = go("allow", "--layer", "place:home/doctor", "--selector", sel(["collection:doctor/med"]), "--until", "2027-01-31")
rid = re.search(r"Done: (r-[0-9a-f]+)", out).group(1)
# no agent works in home yet: the 'narrow' drops the collection, the 'shorten' then pushes the end out
rc, out = go("narrow", rid, "--selector", sel("*"))
rid2 = re.search(r"Done: (r-[0-9a-f]+)", out).group(1)
rc, out = go("shorten", rid2, "--until", "2027-12-31")
rid3 = re.search(r"Done: (r-[0-9a-f]+)", out).group(1)
go("agent", "add", "helper", "--acts-for", "person:doctor")
go("agent", "place", "helper", "place:home/doctor")
go("store", "add", IID, "--name", "main")
from permission_ledger import Ledger
from permissions import share_cover, decide, Use, placement_still_counts
led = Ledger.open_read_only(home); st = led.state()
r3 = st.records[rid3]
print("live record", rid3, "collections", r3.selector.collections, "valid_until", r3.valid_until)
at = 1811808000  # 2027-06-01, after the original end
for obj in (M1, M2):
    print(obj[-2:], "share_cover@2027-06:", share_cover(st, owner="person:doctor", obj=obj, audience="place:home/doctor", at=at),
          "| decide@2027-06:", decide(st, Use("agent:helper", "place:home/doctor", obj, "store:" + IID, "read", "care", at)).allowed)
