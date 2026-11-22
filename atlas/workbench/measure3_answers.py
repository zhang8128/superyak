"""North-star test 5, Measure 3, stage 1 (engram/experiments/northstar/PREREG-test5-measure3.md, approved at 64f8a41c).

For two first publications, T1 and P1, it gives REL's answer, `relation()`, for every cross claim pair, and each
record's sources with their keys and whether their url key is strong. That's everything stage 2,
`engram/experiments/northstar/measure3.py`, needs to run B1 to B3, the trivial arms, the truth, the cost and the
bootstraps. Stage 2 never imports Atlas, and this file needs no numpy, so each runs in its own environment.

Usage: `python -m workbench.measure3_answers T1.json P1.json > answers.json`, run from `atlas/`."""
from __future__ import annotations

import json
import sys

from .sourced import strong_url, validate_sourced
from .sourced_relation import held_claims, relation


def _records(package):
    """{record id: [its sources in evidence order, each with keys and strong_url]} for one publication."""
    model = package["snapshot"]["payload"]["model"]
    sources = {s["id"]: s for s in model["sources"]}
    out = {}
    for item in model["items"]:
        listed = []
        for evidence in item.get("evidence", []):
            source = sources[evidence["source_id"]]
            listed.append({"id": source["id"], "title": source["title"], "year": source["year"], "url": source["url"],
                           "keys": source["keys"], "strong_url": strong_url(source["keys"]["url"])})
        out[item["id"]] = listed
    return out


def answers(t_package, p_package):
    """REL's answer for every T1 × P1 claim pair, sorted by (T record id, P record id), and each side's records."""
    for package in (t_package, p_package):
        validate_sourced(package)
    held = held_claims([t_package, p_package])
    digests = {side: {c["payload"]["sentence"]["record_id"]: c["digest"] for c in package["claims"]}
               for side, package in (("T", t_package), ("P", p_package))}
    pairs = []
    for t in sorted(digests["T"]):
        for p in sorted(digests["P"]):
            got = relation(digests["T"][t], digests["P"][p], held)
            pairs.append({"t": t, "p": p, "rel": got["answer"], "reason": got["reason"],
                          "link": got["link"]["value"] if got["link"] else None})
    return {"format": "measure3-answers", "version": 1, "rel": "relation() at the checkout's commit",
            "records": {"T": _records(t_package), "P": _records(p_package)}, "pairs": pairs}


def main(argv=None):
    t_path, p_path = (argv if argv is not None else sys.argv[1:])
    with open(t_path) as t, open(p_path) as p:
        out = answers(json.load(t), json.load(p))
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
