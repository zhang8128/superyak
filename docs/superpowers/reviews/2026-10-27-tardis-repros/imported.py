import tempfile
from pathlib import Path
from permission_uses import Uses, UseRow
home = Path(tempfile.mkdtemp())
u = Uses.open(home)
LOCAL = "11111111-2222-3333-4444-555555555555"
u.append_imported(UseRow(id="u-" + "a" * 32, at=1000, ledger_id=LOCAL, ledger_seq=1, agent="agent:x", place="place:ph",
                         acting_for="place:ph", action="inject_context", purpose="p", allowed=1, cited="[]",
                         copy="imprint:s/i", returned='{"count": 1}', content_digest="sha256:feed", shadow=0), [])
print("deliveries:", [(r.id, r.action, r.content_digest) for r in u.deliveries("agent:x", now=1001)])
class S: meta = {"ledger_id": LOCAL}; collection_members = {}; subjects = {}; seq_at = {}; self_claims = []
lst = u.owner_list(S())
print("counts:", lst.counts, "row imported flag:", lst.rows[0]["imported"])
