"""Places against routes on 49 team workers' first readings (Serenity's workers-ordered-reads.json, all hands 7ea1fa5e).

For each worker, in the order they ran: its history is the earlier workers. Two histories are read: every earlier worker,
and Serenity's "same area" (an earlier worker whose brief names a file this one's brief names). Each history is built
as a ship's store (ship-share 1, walks of source "ship"), each step naming one file at its first reading.

The goals are the files the worker's brief named. Two lists, the brief's files left out of both:
  route   - the store's route to each brief file, in brief order, then every other file by places rank;
  places  - files ranked by how many distinct earlier workers read them, ties by byte order.
Scored at 5, 10 and 16 against the files the worker read that its brief had not named. A reading, not a result.

    uv run --offline --extra dev python compare_workers.py <workers-ordered-reads.json> <out-dir>
"""
import hashlib, json, sys
from collections import Counter
from pathlib import Path

import ncat_routes as R

data = json.loads(Path(sys.argv[1]).read_bytes())
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
workers = sorted(data["workers"], key=lambda w: w["order"])
KS = (5, 10, 16)
REPO, BASE = "1" * 40, "2" * 40
# Not files of the repository: the team's own plan files, which the export's path rule folded under team/ (all hands
# dcb78cd1). The repository's own paths under team/ start team/superyak_team/.
NOT_THE_REPOSITORY = ("team/teams/",)


def ours(p):
    return R.plain_path(p) and not p.startswith(NOT_THE_REPOSITORY)


def walk_of(w):
    reads = [p for p in w["files_read_in_order_of_first_reading"] if ours(p)]
    return {"v": 1, "source": "ship", "repo": REPO, "base": BASE, "item": f"item-{w['worker']}",
            "attempt": f"a{w['order']:03d}-{w['worker']}", "family": "codex" if w["program"] == "codex" else "claude",
            "verdict": None, "standing": "unjudged",
            "steps": [{"seq": i, "tool": "read", "ok": True, "named": [[p, hashlib.sha1(p.encode()).hexdigest()]],
                       "seen_ms": None, "result_ms": None, "tokens_in": None, "tokens_out": None}
                      for i, p in enumerate(reads)],
            "changed": []}


rows, skipped = [], Counter()
for w in workers:
    brief = [p for p in w["files_its_brief_named"] if ours(p)]
    target = {p for p in w["files_read_in_order_of_first_reading"] if ours(p)} - set(brief)
    if not brief or not target:
        skipped["no brief file or nothing read beyond it"] += 1
        continue
    earlier = [x for x in workers if x["order"] < w["order"] and x["files_read_in_order_of_first_reading"]]
    area = [x for x in earlier if {p for p in x["files_its_brief_named"] if ours(p)} & set(brief)]
    for history_name, history in (("all earlier", earlier), ("same area", area)):
        if not history:
            skipped[f"{history_name}: no history"] += 1
            continue
        d = out / f"{w['order']:03d}-{history_name.replace(' ', '-')}"
        d.mkdir(exist_ok=True)
        files = []
        for x in history:
            f = d / f"walk-{x['order']:03d}.jsonl"
            f.write_bytes(R.canonical(walk_of(x)))
            files.append(f)
        R.build(d / "routes.db", files)
        q = R.canonical({"v": 1, "repo": REPO, "list": None, "measure": {"name": "ship-share", "version": 1},
                         "goals": brief})
        with R.open_store(d / "routes.db") as s:
            answer = json.loads(s.ask(q))
        count = Counter(p for x in history for p in set(x["files_read_in_order_of_first_reading"]) if ours(p))
        places = [p for p in sorted(count, key=lambda p: (-count[p], p.encode())) if p not in brief]
        route_first = []
        for a in answer["answers"]:
            for p in (a.get("route") or {}).get("paths", []):
                if p not in brief and p not in route_first:
                    route_first.append(p)
        route = route_first + [p for p in places if p not in route_first]
        row = {"worker": w["worker"], "order": w["order"], "mode": w["mode"], "history": history_name,
               "earlier": len(history), "target": len(target), "route_len": len(route_first),
               "brief_routed": sum(1 for a in answer["answers"] if a.get("route"))}
        for name, seq in (("route", route), ("places", places)):
            for k in KS:
                row[f"{name}@{k}"] = len(set(seq[:k]) & target) / len(target)
        rows.append(row)

(out / "rows.json").write_text(json.dumps(rows, indent=1))
print("skipped:", dict(skipped))
mean = lambda v: sum(v) / len(v) if v else float("nan")
med = lambda v: sorted(v)[len(v) // 2] if v else float("nan")
for history_name in ("all earlier", "same area"):
    rs = [r for r in rows if r["history"] == history_name]
    if not rs:
        continue
    print(f"\n{history_name}: {len(rs)} workers; target median {med([r['target'] for r in rs])} files; route beyond the "
          f"brief median {med([r['route_len'] for r in rs])} files; brief files with a route median "
          f"{med([r['brief_routed'] for r in rs])}")
    for k in KS:
        a = [r[f"route@{k}"] for r in rs]
        b = [r[f"places@{k}"] for r in rs]
        d = [x - y for x, y in zip(a, b)]
        print(f"  @{k:2d}: route mean {mean(a):.3f} | places mean {mean(b):.3f} | route - places mean {mean(d):+.3f}; "
              f"route better {sum(x > 0 for x in d)}, worse {sum(x < 0 for x in d)}, same {sum(x == 0 for x in d)}")
