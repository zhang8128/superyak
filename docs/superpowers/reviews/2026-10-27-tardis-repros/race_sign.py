"""Two terminals sign the same proposal at once: the act is applied twice."""
import tempfile
from pathlib import Path
from permissions import Act
from permission_ledger import Ledger
from tests.permissions_support import e1_ledger_with_g1, parks_body, T

tmp = Path(tempfile.mkdtemp())
a = e1_ledger_with_g1(tmp)
b = Ledger.open(a.root)
now = T("2026-11-04")
p = a.perform(Act("allow", parks_body()), actor="agent:rio-grande", channel="tool", now=now)
before = {r for r in a.state().records}
orig = a._append
def interleaved(*args, **kw):
    a._append = orig
    out = b.perform(Act("sign", {"proposal": p.ref}), actor="person:andy", channel="terminal", now=now)
    print("B signed:", out.status, out.ref)
    return orig(*args, **kw)
a._append = interleaved
out = a.perform(Act("sign", {"proposal": p.ref}), actor="person:andy", channel="terminal", now=now)
print("A signed:", out.status, out.ref)
s = a.state()
new = [s.records[r] for r in s.records if r not in before]
print("new records from one proposal:", len(new), [(r.id, r.proposal_id == p.ref, r.revoked_seq) for r in new])
print("proposal status", s.proposals[p.ref].status, "decided_seq", s.proposals[p.ref].decided_seq)
