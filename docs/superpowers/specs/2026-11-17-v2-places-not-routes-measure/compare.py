"""Places against routes, offline, on walks that exist (all hands fd38a8b8, the measure written before the run).

For each turn: its history is the other items' taught turns, never its own item's. The store is built from that history.
Two lists, each with the turn's goals (its changed files) left out:
  route   - the store's route to each goal, in goal order, then every other file by places rank (so both lists hold the
            same files and differ only in order);
  places  - files ranked by how many distinct taught turns named them, ties by byte order.
Scored at 5, 10 and 16 against the distinct files the turn named, leaving out what it was given: its goals, its tests
(any path with a /tests/ part or a test_ name) and its check (.yak-check/). Reported with and without the files every
history turn named. A reading, not a result: n is small and the turns are close neighbours.

    uv run --offline --extra dev python compare.py <walks-dir> <out-dir>
"""
import hashlib, json, sys
from collections import Counter
from pathlib import Path

import ncat_routes as R

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
files = sorted(src.glob("*.json"), key=lambda f: int(f.stem))
walks = [(f, json.loads(f.read_bytes())) for f in files]
KS = (5, 10, 16)


def named(w):
    return [p for s in w["steps"] for p, _ in s["named"]]


def given(p, goals):
    return p in goals or "/tests/" in f"/{p}" or Path(p).name.startswith("test_") or p.startswith(".yak-check/")


rows = []
for f, w in walks:
    history = [(g, x) for g, x in walks if x["item"] != w["item"] and x["standing"] == "passed_verified"]
    if not history:
        continue
    goals = [p for p, _ in w["changed"]]
    hdir = out / f"h-{f.stem}"
    hdir.mkdir(exist_ok=True)
    turns = sorted(({"attempt": x["attempt"], "item": x["item"], "base": x["base"], "standing": x["standing"],
                     "sha256": hashlib.sha256(g.read_bytes()).hexdigest()} for g, x in history), key=lambda e: e["attempt"])
    lst = json.dumps({"v": 1, "repo": w["repo"], "measure": {"name": "share", "version": 1}, "turns": turns},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    (hdir / "list.json").write_bytes(lst)
    store = hdir / "routes.db"
    R.build(store, [g for g, _ in history], hdir / "list.json")
    q = R.canonical({"v": 1, "repo": w["repo"], "list": hashlib.sha256(lst).hexdigest(),
                     "measure": {"name": "share", "version": 1}, "goals": goals})
    with R.open_store(store) as s:
        answer = json.loads(s.ask(q))
    count = Counter(p for _, x in history for p in set(named(x)))
    places = [p for p in sorted(count, key=lambda p: (-count[p], p.encode())) if p not in goals]
    route_first = []
    for a in answer["answers"]:
        for p in (a.get("route") or {}).get("paths", []):
            if p not in goals and p not in route_first:
                route_first.append(p)
    route = route_first + [p for p in places if p not in route_first]
    everyone = {p for p in count if count[p] == len(history)}
    read = {p for p in named(w) if not given(p, goals)}
    for drop_common in (False, True):
        target = read - everyone if drop_common else read
        if not target:
            continue
        row = {"turn": f.stem, "item": w["item"], "standing": w["standing"], "history": len(history),
               "drop_common": drop_common, "target": len(target), "route_len": len(route_first)}
        for name, lst_ in (("route", route), ("places", places)):
            seq = [p for p in lst_ if not (drop_common and p in everyone)]
            for k in KS:
                row[f"{name}@{k}"] = len(set(seq[:k]) & target) / len(target)
        rows.append(row)

(out / "rows.json").write_text(json.dumps(rows, indent=1))
for drop_common in (False, True):
    rs = [r for r in rows if r["drop_common"] == drop_common]
    if not rs:
        continue
    print(f"\n{'without' if drop_common else 'with'} the files every history turn named: {len(rs)} turns, "
          f"target median {sorted(r['target'] for r in rs)[len(rs) // 2]} files, route median "
          f"{sorted(r['route_len'] for r in rs)[len(rs) // 2]} files beyond the goals")
    for k in KS:
        a = sorted(r[f"route@{k}"] for r in rs)
        b = sorted(r[f"places@{k}"] for r in rs)
        diff = sorted(r[f"route@{k}"] - r[f"places@{k}"] for r in rs)
        mean = lambda v: sum(v) / len(v)
        print(f"  @{k:2d}: route mean {mean(a):.2f} median {a[len(a)//2]:.2f} | places mean {mean(b):.2f} median "
              f"{b[len(b)//2]:.2f} | route - places: mean {mean(diff):+.2f}, better {sum(d > 0 for d in diff)}, "
              f"worse {sum(d < 0 for d in diff)}, same {sum(d == 0 for d in diff)}")
