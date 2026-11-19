"""Chosen after the counts were read, and marked so: the rows on the behaviour candidates that got past the barrier
(a given body, an assertion or other), and the totals of how candidates fail."""
import json, runpy, sys, collections
from pathlib import Path
m = runpy.run_path(sys.argv[1]); cases = json.load(open(sys.argv[2])); out = Path(sys.argv[3])
items = cases["items"]
kinds_total = collections.Counter(); by_pool = collections.defaultdict(collections.Counter)
past = {}; past_nsb = {}
for key, item in sorted(items.items()):
    r = json.loads((out / "run" / f"{key}.json").read_text())
    pool = item["pool"] or "A"
    for case in r["candidates"]:
        kind = m["how_it_fails"](r["first_line"].get(case, ""))
        kinds_total[kind] += 1; by_pool[pool][kind] += 1
    past[key] = {c for c in r["candidates"] if m["how_it_fails"](r["first_line"].get(c, "")) != "still a barrier"}
    past_nsb[key] = past[key] - set(r["string_bound"])
print("candidates by how they fail:", dict(kinds_total), "total", sum(kinds_total.values()))
for pool, c in sorted(by_pool.items()): print("  pool", pool, dict(c), "total", sum(c.values()))
sums = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
for pilot, rows in (("first", cases["rows_first_pilot"]), ("second", cases["rows_second_pilot"])):
    for name, held in rows.items():
        key, row = name.split(" ", 1)
        pool = (items[key]["pool"] or "A") if pilot == "second" else "A"
        cell = sums[(pilot, pool, row)]
        cell[0] += 1; cell[1] += len(past[key]); cell[2] += len(set(held) & past[key])
        cell[3] += len(past_nsb[key]); cell[4] += len(set(held) & past_nsb[key])
order = {r: i for i, r in enumerate(("nothing-1", "nothing-2", "exists", "path", "search", "bm25", "newest", "lot", "may-1", "may-2"))}
print("pilot pool row | items | past the barrier: cases, passed | of those not string-bound: cases, passed")
for (pilot, pool, row), c in sorted(sums.items(), key=lambda kv: (kv[0][0], kv[0][1], order[kv[0][2]])):
    print(f"{pilot} {pool} {row} | {c[0]} | {c[1]}, {c[2]} | {c[3]}, {c[4]}")
