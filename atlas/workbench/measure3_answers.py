"""North-star test 5, Measure 3, stage 1 (engram/experiments/northstar/PREREG-test5-measure3.md, approved at 64f8a41c).

For two first publications, T1 and P1, it gives REL's answer, `relation()`, for every cross claim pair, and each
record's sources with their keys and whether their url key is strong. That's everything stage 2,
`engram/experiments/northstar/measure3.py`, needs to run B1 to B3, the trivial arms, the truth, the cost and the
bootstraps. Stage 2 never imports Atlas, and this file needs no numpy, so each runs in its own environment.

Usage: `python -m workbench.measure3_answers T1.json P1.json > answers.json`, run from `atlas/`."""
from __future__ import annotations

import json
import re
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


def copy_answers(t_side, p_side):
    """The page's copies measure: REL's answer over every cross pair of held claims, T1 and T2 against P1 and P2. It
    gives the pairs REL answers copied, and the declared copies, each a claim whose provenance names the other side's
    claim. Each pair is (T record id, P record id)."""
    for package in (*t_side, *p_side):
        validate_sourced(package)
    held = held_claims([*t_side, *p_side])
    t_claims = {c["digest"]["value"]: c for package in t_side for c in package["claims"]}
    p_claims = {c["digest"]["value"]: c for package in p_side for c in package["claims"]}

    def rid(claim):
        return claim["payload"]["sentence"]["record_id"]
    answered = sorted([rid(t_claims[t]), rid(p_claims[p])] for t in t_claims for p in p_claims
                      if relation(t_claims[t]["digest"], p_claims[p]["digest"], held)["answer"] == "copied")
    declared = sorted({(rid(c), rid(p_claims[ref["value"]])) for c in t_claims.values()
                       for ref in c["payload"]["provenance"] if ref["value"] in p_claims} |
                      {(rid(t_claims[ref["value"]]), rid(c)) for c in p_claims.values()
                       for ref in c["payload"]["provenance"] if ref["value"] in t_claims})
    return {"declared": [list(pair) for pair in declared], "answered_copied": answered}


def notice_reach(notice, *, store, own, publications):
    """A notice's reach on the receiving side, by `apply_notice`: the records it reaches directly (its matched sources'
    citing items, and claims reached through their chains), and apart from them, the items reached only through
    `supports` and `challenges` relations (the page's VA6)."""
    from .sourced import apply_notice
    report = apply_notice(notice, store=store, own=own, publications=publications)
    items = (report["impact"] or {}).get("items", [])
    direct = {item["id"] for item in items if len(item["path"]) == 2} | set(report["through_chain"])
    supports = {item["id"] for item in items if len(item["path"]) > 2} - direct
    return {"direct": sorted(direct), "through_supports": sorted(supports), "outcome": report["outcome"]}


CROSSREF = "https://api.crossref.org/works/{doi}"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
USER_AGENT = "superyak-measure3/1.0"  # a generic client name, never a person's contact details
PUBMED_URL = re.compile(r"https?://(?:www\.)?pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/?$")


def fetch_json(url, *, timeout=30):
    """One GET of a public metadata record. Returns None on a 404, so an item with no record keeps its fields."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                                    timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def crossref_record(doi, *, fetch=fetch_json):
    """Crossref's record for a DOI: `title[0]` verbatim, the `issued` year, the DOI, and its version links."""
    from urllib.parse import quote
    got = fetch(CROSSREF.format(doi=quote(doi.lower(), safe="/")))  # a SICI DOI's <, >, ; and # quoted (Rio Grande)
    if got is None:
        return None
    m = got["message"]
    return {"doi": m["DOI"].lower(), "title": m["title"][0], "year": m["issued"]["date-parts"][0][0],
            "relations": {kind: [r["id"].lower() for r in rows] for kind, rows in (m.get("relation") or {}).items()}}


def pubmed_record(pmid, *, fetch=fetch_json):
    """PubMed's esummary for a PMID: its title verbatim, its year, and the DOI among its article ids."""
    got = fetch(ESUMMARY.format(pmid=pmid))
    if got is None or pmid not in got.get("result", {}):
        return None
    x = got["result"][pmid]
    doi = next((a["value"] for a in x["articleids"] if a["idtype"] == "doi"), None)
    return {"pmid": pmid, "doi": doi.lower() if doi else None, "title": x["title"], "year": int(x["pubdate"][:4])}


def lookup(source, *, fetch=fetch_json):
    """The one client both builders' freeze checks use: Crossref for a source with a DOI key, PubMed for one kept by
    its PubMed url, and None for anything else."""
    from .sourced import source_key
    doi = source_key(source)["doi"]
    if doi:
        return crossref_record(doi[len("doi:"):], fetch=fetch)
    match = PUBMED_URL.match(source.get("url", ""))
    return pubmed_record(match.group(1), fetch=fetch) if match else None


SIZES = {"sources": (15, 30), "records": (10, 25)}


def freeze_check(bundle, lookup):
    """The builder rules, checked at the freeze (the page's "The two collections", W5 and VA10). `lookup(source)`
    returns the item's Crossref or PubMed record, `{"doi", "title", "year"}`, or None when it has none. Every
    deviation must be corrected before the freeze; an item with no record keeps the builder's fields and is listed."""
    from .sourced import source_key
    deviations, without = [], []
    for what, items in (("sources", bundle["sources"]), ("records", bundle["items"])):
        low, high = SIZES[what]
        if not low <= len(items) <= high:
            deviations.append(f"{len(items)} {what}, outside {low} to {high}")
    for item in bundle["items"]:
        if not item.get("evidence"):
            deviations.append(f"record {item['id']} cites no source")
    for source in bundle["sources"]:
        record = lookup(source)
        if record is None:
            without.append(source["id"])
            continue
        if source["title"] != record["title"]:
            deviations.append(f"source {source['id']}: title isn't the record's verbatim")
        if source["year"] != record["year"]:
            deviations.append(f"source {source['id']}: year {source['year']} isn't the record's {record['year']}")
        doi = record.get("doi")
        if doi:
            if doi.lower() not in source.get("citation", "").lower():
                deviations.append(f"source {source['id']}: the citation lacks the item's own DOI")
            key = source_key(source)["doi"]
            if key != f"doi:{doi.lower()}":
                deviations.append(f"source {source['id']}: DOI key {key} isn't the item's own doi:{doi.lower()}")
    return {"deviations": deviations, "without_record": without}


def main(argv=None):
    t_path, p_path = (argv if argv is not None else sys.argv[1:])
    with open(t_path) as t, open(p_path) as p:
        out = answers(json.load(t), json.load(p))
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
