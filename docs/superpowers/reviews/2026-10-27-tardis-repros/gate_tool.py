import sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tests.permissions_support import daemon_ledger, make_placed_house, T, ANDY
from permission_ledger import Ledger
from permissions import Act
root = Path(tempfile.mkdtemp())
make_placed_house(root)
daemon_ledger(root, "enforce")
led = Ledger.open(root)
for act in [Act("gate", {"mode": "off"}), Act("put-agent", {"agent": "agent:engram", "place": "place:home/andy"}),
            Act("register-agent", {"agent": "agent:evil", "acts_for": "place:home/andy"})]:
    try:
        out = led.perform(act, actor="agent:engram", channel="tool", now=T("2026-11-03"))
        print(act.kind, "->", out.status)
    except Exception as e:
        print(act.kind, "-> raised", type(e).__name__, e)
print("gate now:", led.meta().get("gate"))
