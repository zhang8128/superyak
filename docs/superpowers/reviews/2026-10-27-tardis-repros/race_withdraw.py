"""Two writers: andy withdraws R1 on the terminal while rio-grande's shorten of R1 (read before) commits."""
import sys, tempfile
from pathlib import Path
from permissions import Act
from permission_ledger import Ledger
from tests.permissions_support import e1_ledger_with_g1, T

tmp = Path(tempfile.mkdtemp())
a = e1_ledger_with_g1(tmp)            # process A (the engram server)
ids = a.ids
b = Ledger.open(a.root)               # process B (the CLI)
orig = a._append
def interleaved(*args, **kw):
    a._append = orig
    out = b.perform(Act("revoke", {"record": ids.R1, "reason": "withdrawn"}), actor="person:andy",
                    channel="terminal", now=T("2026-11-10"))
    print("B withdrew R1 at seq", out.seq)
    return orig(*args, **kw)
a._append = interleaved
out = a.perform(Act("shorten", {"record": ids.R1, "valid_until": T("2026-12-15")}), actor="agent:rio-grande",
                channel="tool", now=T("2026-11-10"))
s = a.state()
r1, r1p = s.records[ids.R1], s.records[out.ref]
print("A shorten:", out.status, "seq", out.seq)
print("R1 revoked_seq", r1.revoked_seq, "revoked_by", r1.revoked_by, "reason", r1.revoke_reason)
print("R1' live:", r1p.revoked_seq is None, "backing", r1p.backing, "valid_until", r1p.valid_until)
print("log verifies:", a.verify())
