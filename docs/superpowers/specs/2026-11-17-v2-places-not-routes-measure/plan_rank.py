"""For each of Serenity's 52 items: the best rank, among places named by the walks Tardis holds, of any document that
holds one of the item's new names. The measure as posted before the run (all hands 44c0de38)."""
import json, sys
from collections import Counter
from pathlib import Path

items_file, pilot_dir, probe_dir, workers_file = map(Path, sys.argv[1:5])
items = json.loads(items_file.read_bytes())["items"]
walks = []
for d in (pilot_dir, probe_dir):
    for f in sorted(d.glob("*.json")):
        w = json.loads(f.read_bytes())
        walks.append({p for s in w["steps"] for p, _ in s["named"]})
for w in json.loads(workers_file.read_bytes())["workers"]:
    walks.append({p for p in w["files_read_in_order_of_first_reading"] if not p.startswith("team/teams/")})
count = Counter(p for w in walks for p in w)
ranked = sorted(count, key=lambda p: (-count[p], p.encode()))
rank = {p: i + 1 for i, p in enumerate(ranked)}
EVERYONE = {"README.md", "CLAUDE.md", "HANDOFF.md", "AGENTS.md"}
rows = []
for it in items:
    docs = {p for paths in it["held"].values() for p in paths if isinstance(p, str)}
    best = min((rank[p] for p in docs if p in rank), default=None)
    best_plain = min((rank[p] for p in docs if p in rank and p not in EVERYONE), default=None)
    rows.append((it["commit"][:8], it["part"], len(docs), best, best_plain,
                 sorted((rank[p], p, count[p]) for p in docs if p in rank)[:3]))
print(f"walks {len(walks)} (pilot {len(list(pilot_dir.glob('*.json')))}, probes {len(list(probe_dir.glob('*.json')))}, "
      f"workers {len(walks) - len(list(pilot_dir.glob('*.json'))) - len(list(probe_dir.glob('*.json')))}); places {len(ranked)}")
for label, i in (("any document", 3), ("leaving out README/CLAUDE/HANDOFF/AGENTS", 4)):
    v = [r[i] for r in rows]
    print(f"{label}: absent {sum(x is None for x in v)}, within 5 {sum(x is not None and x <= 5 for x in v)}, "
          f"6-16 {sum(x is not None and 5 < x <= 16 for x in v)}, beyond 16 {sum(x is not None and x > 16 for x in v)}")
print("hits, excluding the four:")
for r in rows:
    if r[4] is not None:
        print("  ", r[0], r[1], "best", r[4], [(rk, p, c) for rk, p, c in r[5] if p not in EVERYONE][:2])
