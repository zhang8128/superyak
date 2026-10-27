import sys, os, json, re, shutil, time
from pathlib import Path
from drive import run
W = __import__("os").environ["W"]  # the repository checkout at the reviewed head
sys.path.insert(0, W + "/engram")
home = Path(sys.argv[1]); shutil.rmtree(home, ignore_errors=True); home.mkdir(parents=True)
IID = "0b7b3c2e-1111-4111-8111-111111111111"; M1 = f"mem:{IID}/episode/m1"
sel = json.dumps({"audience": ["place:home/doctor"], "requesters": "*", "actions": ["inject_context", "read", "recall"],
        "purposes": "*", "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                    "collections": ["collection:doctor/med"], "memories": "*"}})
def go(*args):
    rc, out = run(home, list(args))
    last = [l for l in out.strip().splitlines() if l.strip()][-1]
    print(rc, " ".join(args[:3]), "->", last[:170]); return rc, out
go("init")
go("agent", "add", "helper", "--acts-for", "person:doctor")
go("agent", "place", "helper", "place:home/doctor")
go("store", "add", IID, "--name", "main")
go("collection", "add", "doctor/med", M1)
rc, out = go("allow", "--layer", "place:home/doctor", "--selector", sel)
rid = re.search(r"Done: (r-[0-9a-f]+)", out).group(1)
from permission_ledger import Ledger
from permissions import decide, Use
def allowed():
    led = Ledger.open_read_only(home); st = led.state(); led.close()
    return decide(st, Use("agent:helper", "place:home/doctor", M1, "store:" + IID, "read", "care", int(time.time()) + 60)).allowed
print("allowed before retire:", allowed())
go("person", "retire", "doctor")
print("allowed after retire:", allowed())
go("revoke", rid)
go("collection", "remove", "doctor/med", M1)
go("agent", "unplace", "helper", "place:home/doctor")
go("deny", "--layer", "place:home/doctor", "--selector", sel)
print("allowed at the end:", allowed())
