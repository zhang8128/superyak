import tempfile
from pathlib import Path
from permission_uses import Uses, UseRow
from permissions import RETENTION_DAYS

home = Path(tempfile.mkdtemp())
u = Uses.open(home)
old, now = 1_700_000_000, 1_700_000_000 + (RETENTION_DAYS + 5) * 86400
base = dict(at=old, ledger_id="L", ledger_seq=3, agent="agent:x", place="place:ph", acting_for="place:ph",
            purpose="care-coordination", cited="[]")
obj = "mem:abc/episode/e1"
u.append(UseRow(**base, action="read", allowed=0, object=obj, shadow=0), [("person:andy", obj)])   # real refusal
u.append(UseRow(**base, action="read", allowed=0, object=obj, shadow=1), [("person:andy", obj)])   # shadow: legacy delivered
u.append(UseRow(**base, action="recall", allowed=1, returned="[]", filtered=20), [])               # recall that returned nothing
print("folded", u.fold(now=now))
for r in u.conn.execute("SELECT * FROM uses_monthly"):
    print(dict(r))
