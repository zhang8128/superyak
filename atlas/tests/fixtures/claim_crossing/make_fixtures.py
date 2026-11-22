"""North-star test 5's planted stores, made once and frozen: `python -m tests.fixtures.claim_crossing.make_fixtures`
from atlas/ writes pi.json, tardis.json, third.json, fourth.json and expected.json beside this file.

The design is docs/superpowers/specs/2026-11-22-claim-crossing-design.md (revision 6 and amendment 1). Every answer in
expected.json is derived by hand from the spec's ordered rules, before any receiver rule exists: Tardis writes
`relation()` against these files (T1), and test_claim_crossing_fixtures.py holds the files to this generator byte for
byte. Every DOI is under 10.5555/superyak-fixture-... and nothing here resolves one; every person, title and text is
fictional.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from workbench.lighthouse_wire import digest
from workbench.sourced import SOURCED_PROFILE, SOURCED_SENTENCE, publish_sourced, seal_notice

HERE = Path(__file__).resolve().parent
AT = "2026-11-22T00:00:00Z"
STORES = ("fourth", "third", "pi", "tardis")              # publishing order: a copier after what it copies
PREFIX = {"pi": "P", "tardis": "T", "third": "H", "fourth": "F"}
SOURCE_PREFIX = {"pi": "pi", "tardis": "t", "third": "h", "fourth": "f"}
D = "10.5555/superyak-fixture"


def issuer(store):
    return f"urn:superyak:fixture:{store}"


def context(store):
    return {"id": f"urn:superyak:fixture:{store}:context", "path": ["research", "fixture"]}


class Planted:
    def __init__(self):
        self.sources = {s: [] for s in STORES}
        self.items = {s: [] for s in STORES}
        self.relations = {s: [] for s in STORES}
        self.copies = {s: {} for s in STORES}      # item id -> [("store", item id) or ("unresolved", tag)]
        self.carried = {s: [] for s in STORES}     # [("store", item id)]
        self.pairs = []

    def source(self, store, sid, title, url, year=2024, citation=""):
        full = f"{SOURCE_PREFIX[store]}-{sid}"
        self.sources[store].append({"id": full, "title": title, "url": url, "year": year, "citation": citation})
        return full

    def claim(self, store, iid, title, *sources, copied_from=(), summary="A fictional result."):
        full = f"{PREFIX[store]}-{iid}"
        record = {"id": full, "kind": "claim", "title": title, "summary": summary}
        if sources:
            record["status"] = "source_reported"
            record["evidence"] = [{"source_id": s, "locator": f"p{n + 1}"} for n, s in enumerate(sources)]
        else:
            record["status"] = "proposed"
        self.items[store].append(record)
        if copied_from:
            self.copies[store][full] = list(copied_from)
        return full

    def pair(self, case, a, b, answer, link=None):
        entry = {"case": case, "a": a, "b": b, "answer": answer}
        if link is not None:
            entry["link"] = link
        self.pairs.append(entry)


def ref(store, record_id):
    return {"store": store, "record_id": record_id}


def unresolved(tag):
    return digest({"superyak-fixture-unresolved": tag})


def plant() -> Planted:
    p = Planted()
    u = lambda case, i, n: f"https://journal.example/{case}/{i}/{n}"
    for i in ("a", "b"):
        # 1. copied: Tardis keeps a copy of a Pi claim.
        s = p.source("pi", f"copied-{i}-1", f"Copied source {i}", f"https://doi.org/{D}-copied-{i}")
        a = p.claim("pi", f"copied-{i}", f"Copied claim {i}", s)
        t = p.source("tardis", f"copied-{i}-1", f"Copied source {i}", f"https://doi.org/{D}-copied-{i}")
        b = p.claim("tardis", f"copied-{i}", f"Copied claim {i}", t, copied_from=[("pi", a)])
        p.pair("copied", ref("pi", a), ref("tardis", b), "copied", link=ref("pi", a))

        # 2. copied twice: Pi copies a third claim, and Tardis copies Pi's copy.
        h = p.claim("third", f"twice-{i}", f"Twice claim {i}",
                    p.source("third", f"twice-{i}-1", f"Twice source {i}", f"https://doi.org/{D}-twice-{i}"))
        a = p.claim("pi", f"twice-{i}", f"Twice claim {i}",
                    p.source("pi", f"twice-{i}-1", f"Twice source {i}", f"https://doi.org/{D}-twice-{i}"),
                    copied_from=[("third", h)])
        b = p.claim("tardis", f"twice-{i}", f"Twice claim {i}",
                    p.source("tardis", f"twice-{i}-1", f"Twice source {i}", f"https://doi.org/{D}-twice-{i}"),
                    copied_from=[("pi", a)])
        p.pair("copied twice", ref("pi", a), ref("tardis", b), "copied", link=ref("pi", a))

        # 3. sibling copies of one third claim.
        h = p.claim("third", f"sibling-{i}", f"Sibling claim {i}",
                    p.source("third", f"sibling-{i}-1", f"Sibling source {i}", f"https://doi.org/{D}-sibling-{i}"))
        a = p.claim("pi", f"sibling-{i}", f"Sibling claim {i}",
                    p.source("pi", f"sibling-{i}-1", f"Sibling source {i}", f"https://doi.org/{D}-sibling-{i}"),
                    copied_from=[("third", h)])
        b = p.claim("tardis", f"sibling-{i}", f"Sibling claim {i}",
                    p.source("tardis", f"sibling-{i}-1", f"Sibling source {i}", f"https://doi.org/{D}-sibling-{i}"),
                    copied_from=[("third", h)])
        p.pair("sibling copies", ref("pi", a), ref("tardis", b), "copied", link=ref("third", h))

        # 4. a carried claim: Tardis holds Pi's claim itself, the same digest.
        a = p.claim("pi", f"carried-{i}", f"Carried claim {i}",
                    p.source("pi", f"carried-{i}-1", f"Carried source {i}", u("carried", i, 1)))
        p.carried["tardis"].append(("pi", a))
        p.pair("carried", ref("pi", a), {"store": "tardis", "carried": a}, "copied", link=ref("pi", a))

        # 5. a copy of a claim with no evidence: copied, since rule 1 comes before rule 2.
        a = p.claim("pi", f"bare-{i}", f"Bare claim {i}")
        b = p.claim("tardis", f"bare-{i}", f"Bare claim {i}", copied_from=[("pi", a)])
        p.pair("copy of a claim with no evidence", ref("pi", a), ref("tardis", b), "copied", link=ref("pi", a))

        # 6. both chains share one unresolved digest: copied (C9).
        x = ("unresolved", f"shared-{i}")
        a = p.claim("pi", f"shared-x-{i}", f"Shared-x claim P {i}",
                    p.source("pi", f"shared-x-{i}-1", f"Shared-x source P {i}", u("shared-x-p", i, 1)), copied_from=[x])
        b = p.claim("tardis", f"shared-x-{i}", f"Shared-x claim T {i}",
                    p.source("tardis", f"shared-x-{i}-1", f"Shared-x source T {i}", u("shared-x-t", i, 1)),
                    copied_from=[x])
        p.pair("shared unresolved digest", ref("pi", a), ref("tardis", b), "copied", link={"unresolved": f"shared-{i}"})

        # 7. both root sets empty: unknown.
        a = p.claim("pi", f"empty-{i}", f"Empty claim P {i}")
        b = p.claim("tardis", f"empty-{i}", f"Empty claim T {i}")
        p.pair("both empty", ref("pi", a), ref("tardis", b), "unknown")

        # 8. one empty against one not: unknown.
        a = p.claim("pi", f"half-{i}", f"Half claim P {i}",
                    p.source("pi", f"half-{i}-1", f"Half source {i}", u("half", i, 1)))
        b = p.claim("tardis", f"half-{i}", f"Half claim T {i}")
        p.pair("one empty", ref("pi", a), ref("tardis", b), "unknown")

        # 9. an unresolved digest that isn't shared: unknown (rule 2).
        a = p.claim("pi", f"lone-x-{i}", f"Lone-x claim P {i}",
                    p.source("pi", f"lone-x-{i}-1", f"Lone-x source P {i}", u("lone-x-p", i, 1)))
        b = p.claim("tardis", f"lone-x-{i}", f"Lone-x claim T {i}",
                    p.source("tardis", f"lone-x-{i}-1", f"Lone-x source T {i}", u("lone-x-t", i, 1)),
                    copied_from=[("unresolved", f"lone-{i}")])
        p.pair("unresolved digest", ref("pi", a), ref("tardis", b), "unknown")

        # 10. two different DOIs, one title, different years: unclear, so unknown (rule 6, E4).
        title = f"Two DOIs one title {i}"
        a = p.claim("pi", f"two-dois-{i}", f"Two-DOIs claim P {i}",
                    p.source("pi", f"two-dois-{i}-1", title, f"https://doi.org/{D}-two-dois-{i}-pre", year=2023))
        b = p.claim("tardis", f"two-dois-{i}", f"Two-DOIs claim T {i}",
                    p.source("tardis", f"two-dois-{i}-1", title, f"https://doi.org/{D}-two-dois-{i}-jnl", year=2024))
        p.pair("two DOIs one title", ref("pi", a), ref("tardis", b), "unknown")

        # 11. one DOI written three ways: same sources.
        doi = f"{D}-forms-{i}"
        a = p.claim("pi", f"forms-{i}", f"Forms claim P {i}",
                    p.source("pi", f"forms-{i}-1", f"Forms source P {i}", f"https://doi.org/{doi}"))
        if i == "a":
            other = p.source("tardis", f"forms-{i}-1", f"Forms source T {i}", f"http://dx.doi.org/{doi.upper()}")
        else:
            other = p.source("tardis", f"forms-{i}-1", f"Forms source T {i}", u("forms", i, 1), citation=f"doi: {doi}.)")
        b = p.claim("tardis", f"forms-{i}", f"Forms claim T {i}", other)
        p.pair("one DOI written three ways", ref("pi", a), ref("tardis", b), "same sources")

        # 12. a percent-encoded DOI with < and >, in url form and in citation form: same sources (C5, D3).
        sici = f"{D}-pct-{i}(2026)1:2<3::sy>4.0.co;2-{i}"
        encoded = sici.replace("<", "%3C").replace(">", "%3E")
        a = p.claim("pi", f"pct-{i}", f"Percent claim P {i}",
                    p.source("pi", f"pct-{i}-1", f"Percent source P {i}", f"https://doi.org/{encoded}"))
        b = p.claim("tardis", f"pct-{i}", f"Percent claim T {i}",
                    p.source("tardis", f"pct-{i}-1", f"Percent source T {i}", u("pct", i, 1), citation=f"doi:{sici}"))
        p.pair("percent-encoded DOI", ref("pi", a), ref("tardis", b), "same sources")

        # 13. a DOI in angle brackets in a citation: same sources (E1, G3).
        # The second instance is a SICI-style DOI, with its own < and >, wrapped in <doi:...>: only the wrapper's
        # unpartnered > is stripped (G3).
        doi = f"{D}-angle-{i}" if i == "a" else f"{D}-angle-{i}(2026)1:2<3::sy>4.0.co;2-{i}"
        cite = f"Available at <https://doi.org/{doi}>." if i == "a" else f"<doi:{doi}>"
        a = p.claim("pi", f"angle-{i}", f"Angle claim P {i}",
                    p.source("pi", f"angle-{i}-1", f"Angle source P {i}",
                             f"https://doi.org/{doi.replace('<', '%3C').replace('>', '%3E')}"))
        b = p.claim("tardis", f"angle-{i}", f"Angle claim T {i}",
                    p.source("tardis", f"angle-{i}-1", f"Angle source T {i}", u("angle", i, 1), citation=cite))
        p.pair("DOI in angle brackets", ref("pi", a), ref("tardis", b), "same sources")

        # 14. one publisher url, one side citing a DOI, titles differ: same sources, by url (C6).
        a = p.claim("pi", f"one-doi-{i}", f"One-DOI claim P {i}",
                    p.source("pi", f"one-doi-{i}-1", f"One-DOI source, the sequel {i}", u("one-doi", i, 1),
                             citation=f"doi:{D}-one-doi-{i}"))
        b = p.claim("tardis", f"one-doi-{i}", f"One-DOI claim T {i}",
                    p.source("tardis", f"one-doi-{i}-1", f"One-DOI source {i}", u("one-doi", i, 1)))
        p.pair("shared url, one DOI", ref("pi", a), ref("tardis", b), "same sources")

        # 15. title drift under one DOI: same sources.
        a = p.claim("pi", f"drift-{i}", f"Drift claim P {i}",
                    p.source("pi", f"drift-{i}-1", f"A Study of Drift, Part {i}.", f"https://doi.org/{D}-drift-{i}"))
        b = p.claim("tardis", f"drift-{i}", f"Drift claim T {i}",
                    p.source("tardis", f"drift-{i}-1", f"a study of drift part {i}", f"https://doi.org/{D}-drift-{i}"))
        p.pair("title drift", ref("pi", a), ref("tardis", b), "same sources")

        # 16. a publisher url against a DOI, one title and year: same sources, by title.
        title = f"Publisher or DOI {i}"
        a = p.claim("pi", f"pub-doi-{i}", f"Pub-DOI claim P {i}", p.source("pi", f"pub-doi-{i}-1", title, u("pub-doi", i, 1)))
        b = p.claim("tardis", f"pub-doi-{i}", f"Pub-DOI claim T {i}",
                    p.source("tardis", f"pub-doi-{i}-1", title, f"https://doi.org/{D}-pub-doi-{i}"))
        p.pair("publisher url against DOI", ref("pi", a), ref("tardis", b), "same sources")

        # 17. http against https, titles differ: same sources, by url.
        a = p.claim("pi", f"http-{i}", f"Http claim P {i}",
                    p.source("pi", f"http-{i}-1", f"Http source P {i}", u("http", i, 1).replace("https:", "http:")))
        b = p.claim("tardis", f"http-{i}", f"Http claim T {i}", p.source("tardis", f"http-{i}-1", f"Http source T {i}", u("http", i, 1)))
        p.pair("http against https", ref("pi", a), ref("tardis", b), "same sources")

        # 18. www. against none, titles differ: same sources, by url.
        a = p.claim("pi", f"www-{i}", f"Www claim P {i}",
                    p.source("pi", f"www-{i}-1", f"Www source P {i}", u("www", i, 1).replace("//journal.", "//www.journal.")))
        b = p.claim("tardis", f"www-{i}", f"Www claim T {i}", p.source("tardis", f"www-{i}-1", f"Www source T {i}", u("www", i, 1)))
        p.pair("www against none", ref("pi", a), ref("tardis", b), "same sources")

        # 19. two SICI-style DOIs of one issue, titles differ: distinct by DOI, so independent (C5).
        base = f"{D}-sici-{i}(2026)1:2%3C{{n}}::sy%3E4.0.co;2-x"
        a = p.claim("pi", f"sici-{i}", f"Sici claim P {i}",
                    p.source("pi", f"sici-{i}-1", f"Sici article one {i}", f"https://doi.org/{base.format(n=693)}"))
        b = p.claim("tardis", f"sici-{i}", f"Sici claim T {i}",
                    p.source("tardis", f"sici-{i}-1", f"Sici article two {i}", f"https://doi.org/{base.format(n=701)}"))
        p.pair("two SICI DOIs of one issue", ref("pi", a), ref("tardis", b), "independent")

        # 20. two papers in one proceedings url, different DOIs and titles: distinct by DOI, so independent (D1).
        shared = f"https://proc.example/{i}/vol12.pdf"
        a = p.claim("pi", f"proc-{i}", f"Proc claim P {i}",
                    p.source("pi", f"proc-{i}-1", f"Proceedings paper one {i}", shared, citation=f"doi:{D}-proc-{i}-1"))
        b = p.claim("tardis", f"proc-{i}", f"Proc claim T {i}",
                    p.source("tardis", f"proc-{i}-1", f"Proceedings paper two {i}", shared, citation=f"doi:{D}-proc-{i}-2"))
        p.pair("one proceedings url, two DOIs", ref("pi", a), ref("tardis", b), "independent")

        # 21. doi.org paths that aren't DOIs, titles differ: url keys only, distinct, so independent (D5, amendment 1).
        left, right = (("https://doi.org/help", "https://doi.org/") if i == "a"
                       else ("https://doi.org/10.5555", "https://doi.org/about"))
        a = p.claim("pi", f"not-doi-{i}", f"Not-DOI claim P {i}", p.source("pi", f"not-doi-{i}-1", f"Not-DOI page P {i}", left))
        b = p.claim("tardis", f"not-doi-{i}", f"Not-DOI claim T {i}", p.source("tardis", f"not-doi-{i}-1", f"Not-DOI page T {i}", right))
        p.pair("doi.org path that isn't a DOI", ref("pi", a), ref("tardis", b), "independent")

        # 22. a preprint kept by its arXiv url and its journal version under a DOI, a year apart: unclear by year,
        # so unknown (G1).
        title = f"Preprint and journal {i}"
        a = p.claim("pi", f"arxiv-{i}", f"Arxiv claim P {i}",
                    p.source("pi", f"arxiv-{i}-1", title, f"https://arxiv.org/abs/2601.0000{1 if i == 'a' else 2}", year=2023))
        b = p.claim("tardis", f"arxiv-{i}", f"Arxiv claim T {i}",
                    p.source("tardis", f"arxiv-{i}-1", title, f"https://doi.org/{D}-arxiv-{i}", year=2024))
        p.pair("arXiv preprint against journal DOI", ref("pi", a), ref("tardis", b), "unknown")

        # 23. overlapping: one source shared by DOI, and one source each.
        shared_doi = f"https://doi.org/{D}-overlap-{i}"
        a = p.claim("pi", f"overlap-{i}", f"Overlap claim P {i}",
                    p.source("pi", f"overlap-{i}-1", f"Overlap shared {i}", shared_doi),
                    p.source("pi", f"overlap-{i}-2", f"Overlap own P {i}", u("overlap-p", i, 2)))
        b = p.claim("tardis", f"overlap-{i}", f"Overlap claim T {i}",
                    p.source("tardis", f"overlap-{i}-1", f"Overlap shared {i}", shared_doi),
                    p.source("tardis", f"overlap-{i}-2", f"Overlap own T {i}", u("overlap-t", i, 2)))
        p.pair("overlapping", ref("pi", a), ref("tardis", b), "overlapping")

        # 24. independent: disjoint DOIs (a) or disjoint urls (b), titles differ.
        left = f"https://doi.org/{D}-indep-{i}-p" if i == "a" else u("indep-p", i, 1)
        right = f"https://doi.org/{D}-indep-{i}-t" if i == "a" else u("indep-t", i, 1)
        a = p.claim("pi", f"indep-{i}", f"Indep claim P {i}", p.source("pi", f"indep-{i}-1", f"Indep source P {i}", left))
        b = p.claim("tardis", f"indep-{i}", f"Indep claim T {i}", p.source("tardis", f"indep-{i}-1", f"Indep source T {i}", right))
        p.pair("independent", ref("pi", a), ref("tardis", b), "independent")

        # 25. the C10 limit: Tardis's B leans, by relation, on its copy of Pi's A and cites its own source:
        # (A, B) is independent.
        a = p.claim("pi", f"lean-{i}", f"Lean claim A {i}",
                    p.source("pi", f"lean-{i}-1", f"Lean source A {i}", f"https://doi.org/{D}-lean-{i}-a"))
        copy = p.claim("tardis", f"lean-copy-{i}", f"Lean claim A {i}",
                       p.source("tardis", f"lean-copy-{i}-1", f"Lean source A {i}", f"https://doi.org/{D}-lean-{i}-a"),
                       copied_from=[("pi", a)])
        b = p.claim("tardis", f"lean-{i}", f"Lean claim B {i}",
                    p.source("tardis", f"lean-{i}-1", f"Lean source B {i}", f"https://doi.org/{D}-lean-{i}-b"))
        p.relations["tardis"].append({"id": f"T-lean-rel-{i}", "subject": copy, "predicate": "supports", "object": b})
        p.pair("leans on a copy by relation (stated limit)", ref("pi", a), ref("tardis", b), "independent")

        # 26. consent: a fourth claim Pi copies, which fourth's policy lets Pi retain but not reshare.
        p.claim("fourth", f"consent-{i}", f"Consent claim {i}",
                p.source("fourth", f"consent-{i}-1", f"Consent source {i}", u("consent", i, 1)))
    return p


def rule(rule_id, effect, publishers, actions, store, audiences=("self",)):
    return {"id": rule_id, "effect": effect, "validFrom": "2026-01-01T00:00:00Z", "validUntil": "2027-12-31T23:59:59Z",
            "requiredEvidence": [], "requiredAttestations": [], "publishers": [issuer(p) for p in publishers],
            "profiles": [SOURCED_PROFILE["id"]], "domains": ["research"], "actions": list(actions),
            "contexts": [c for c in ([context(s)["id"] for s in store] if isinstance(store, tuple) else [context(store)["id"]])],
            "claimMediaTypes": [SOURCED_SENTENCE], "purposes": ["research"], "audiences": list(audiences)}


def policies():
    """Each store's own rules: whom it reads (read, link_overlap, evaluated as receiver, contexts of the publishers it
    reads), and whom it lets keep or pass on its claims (retain, reshare, evaluated as publisher, its own context)."""
    return {
        "pi": [rule("pi-reads", "allow", ("tardis", "third", "fourth"), ("read", "link_overlap"), ("tardis", "third", "fourth")),
               rule("pi-lets-tardis-retain", "allow", ("tardis",), ("retain",), "pi")],
        "tardis": [rule("tardis-reads", "allow", ("pi", "third"), ("read", "link_overlap"), ("pi", "third")),
                   rule("tardis-lets-pi-retain", "allow", ("pi",), ("retain",), "tardis")],
        "third": [rule("third-lets-pi-retain", "allow", ("pi",), ("retain",), "third"),
                  rule("third-lets-pi-reshare", "allow", ("pi",), ("reshare",), "third", audiences=("onward",)),
                  rule("third-lets-tardis-retain", "allow", ("tardis",), ("retain",), "third")],
        "fourth": [rule("fourth-lets-pi-retain", "allow", ("pi",), ("retain",), "fourth"),
                   rule("fourth-refuses-pi-reshare", "deny", ("pi",), ("reshare",), "fourth", audiences=("onward",))],
    }


def authorization_cases():
    """The consents "copied twice through third" needs (G2), and one refusal."""
    def request(policy_of, counterparty, action, ctx_store, audience="self"):
        return {"policy_of": policy_of, "request": {
            "publisher": issuer(counterparty), "profile": SOURCED_PROFILE["id"], "domain": "research", "action": action,
            "context": context(ctx_store)["id"], "claimMediaType": SOURCED_SENTENCE, "purpose": "research",
            "audience": audience, "at": AT, "evidence": [], "attestations": []}}
    cases = [
        (request("pi", "third", "read", "third"), True),
        (request("third", "pi", "retain", "third"), True),
        (request("third", "pi", "reshare", "third", "onward"), True),
        (request("tardis", "pi", "read", "pi"), True),
        (request("third", "tardis", "retain", "third"), True),
        (request("fourth", "pi", "retain", "fourth"), True),
        (request("fourth", "pi", "reshare", "fourth", "onward"), False),
    ]
    return [{**entry, "allowed": allowed} for entry, allowed in cases]


def build():
    p = plant()
    rules = policies()
    published = {}

    def resolve(target):
        kind, name = target
        if kind == "unresolved":
            return unresolved(name)
        claim = next(c for c in published[kind]["claims"] if c["payload"]["sentence"]["record_id"] == name)
        return claim["digest"]

    for store in STORES:
        bundle = {"schema_version": 1, "title": f"Planted store: {store}", "sources": p.sources[store],
                  "items": p.items[store], "relations": p.relations[store]}
        carried = []
        for owner, name in p.carried[store]:
            claim = next(c for c in published[owner]["claims"] if c["payload"]["sentence"]["record_id"] == name)
            carried.append({"claim": claim, "snapshot": published[owner]["snapshot"]})
        published[store] = publish_sourced(bundle, {
            "issuer": issuer(store), "name": f"Planted {store}", "origin": f"urn:superyak:fixture:{store}:collection",
            "context": context(store), "item_ids": [i["id"] for i in p.items[store]], "issued_at": AT,
            "rules": rules[store], "copied_from": {k: [resolve(t) for t in v] for k, v in p.copies[store].items()},
            "carried": carried})
    expected = {"spec": "docs/superpowers/specs/2026-11-22-claim-crossing-design.md, revision 6 (84fafe71) and amendment 1",
                "pairs": p.pairs, "authorization": authorization_cases(),
                "unresolved": {tag: unresolved(tag) for tag in sorted({f"shared-{i}" for i in "ab"} | {f"lone-{i}" for i in "ab"})}}
    return published, expected


def _corrected_pi(published):
    """The Pi's later publication: P-copied-a now cites a corrected record with a changed DOI, under a new local
    source id (D10), its lineage naming the frozen Pi Snapshot. The frozen stores are untouched."""
    old = published["pi"]["snapshot"]["payload"]["model"]
    record = next(i for i in old["items"] if i["id"] == "P-copied-a")
    source = {"id": "pi-copied-a-1-v2", "title": "Copied source a", "url": f"https://doi.org/{D}-copied-a-v2",
              "year": 2024, "citation": ""}
    item = {"id": record["id"], "kind": "claim", "title": record["title"], "summary": record["summary"],
            "status": "source_reported", "evidence": [{"source_id": source["id"], "locator": "p1"}]}
    bundle = {"schema_version": 1, "title": "Planted store: pi, corrected", "sources": [source], "items": [item],
              "relations": []}
    return publish_sourced(bundle, {
        "issuer": issuer("pi"), "name": "Planted pi, corrected", "origin": "urn:superyak:fixture:pi:collection",
        "context": context("pi"), "item_ids": [item["id"]], "issued_at": "2026-11-22T01:00:00Z",
        "lineage": [published["pi"]["snapshot"]["digest"]]})


def build_notices(published):
    """Five source notices the Pi issues, and the report Tardis must make of each (spec: "Notices, and how they're
    applied", steps 1 to 6), derived by hand before apply_notice exists."""
    corrected = _corrected_pi(published)
    pi_snapshot = published["pi"]["snapshot"]

    def source_of(snapshot, record_id):
        return next(x for x in snapshot["payload"]["model"]["sources"] if x["id"] == record_id)

    def retraction(snapshot, record_id, reason):
        return seal_notice({"notice": "retraction", "record_id": record_id,
                            "keys": source_of(snapshot, record_id)["keys"], "reason": reason},
                           [snapshot], issuer("pi"), context("pi"), AT)

    notices = {
        "N1": retraction(pi_snapshot, "pi-lean-a-1", "The fictional study was withdrawn."),
        "N2": retraction(pi_snapshot, "pi-pub-doi-a-1", "The fictional publisher page was retracted."),
        "N3": retraction(pi_snapshot, "pi-half-a-1", "No other store holds this source."),
        "N4": seal_notice({"notice": "correction",
                           "old": {"snapshot": pi_snapshot["digest"], "record_id": "pi-copied-a-1",
                                   "keys": source_of(pi_snapshot, "pi-copied-a-1")["keys"]},
                           "new": {"snapshot": corrected["snapshot"]["digest"], "record_id": "pi-copied-a-1-v2",
                                   "keys": source_of(corrected["snapshot"], "pi-copied-a-1-v2")["keys"]},
                           "reason": "The fictional DOI was registered wrongly."},
                          [pi_snapshot, corrected["snapshot"]], issuer("pi"), context("pi"), AT),
        "N5": retraction(corrected["snapshot"], "pi-copied-a-1-v2", "The corrected fictional record was withdrawn."),
    }

    def item(record_id, title, verdict, before, after, path):
        return {"id": record_id, "kind": "claim", "title": title, "verdict": verdict, "grounded_before": before,
                "grounded_after": after, "path": path}

    expected = {
        "N1": {"holding": [], "unclear": [], "matched": [{"source_id": "t-lean-copy-a-1", "by": "doi"}],
               "through_chain": ["T-lean-copy-a"],
               "impact": {"retracted": ["t-lean-copy-a-1"], "items": [
                   item("T-lean-copy-a", "Lean claim A a", "unsupported", True, False,
                        ["t-lean-copy-a-1", "T-lean-copy-a"]),
                   item("T-lean-a", "Lean claim B a", "still supported", True, True,
                        ["t-lean-copy-a-1", "T-lean-copy-a", "T-lean-a"])]},
               "corrected": [], "outcome": "reported"},
        "N2": {"holding": [], "unclear": [], "matched": [{"source_id": "t-pub-doi-a-1", "by": "title"}], "through_chain": [],
               "impact": {"retracted": ["t-pub-doi-a-1"], "items": [
                   item("T-pub-doi-a", "Pub-DOI claim T a", "unsupported", True, False,
                        ["t-pub-doi-a-1", "T-pub-doi-a"])]},
               "corrected": [], "outcome": "reported"},
        "N3": {"holding": [], "unclear": [], "matched": [], "through_chain": [], "impact": None, "corrected": [],
               "outcome": "no impact"},
        "N4": {"holding": [], "unclear": [], "matched": [{"source_id": "t-copied-a-1", "by": "doi"}],
               "through_chain": ["T-copied-a"], "impact": None,
               "corrected": [{"record_id": "T-copied-a", "verdict": "built on the corrected record"}],
               "outcome": "reported"},
        "N5": {"holding": ["N4"], "unclear": [], "matched": [{"source_id": "t-copied-a-1", "by": "doi"}],
               "through_chain": ["T-copied-a"],
               "impact": {"retracted": ["t-copied-a-1"], "items": [
                   item("T-copied-a", "Copied claim a", "unsupported", True, False, ["t-copied-a-1", "T-copied-a"])]},
               "corrected": [], "outcome": "reported"},
    }
    return corrected, notices, expected


def write(target: Path = HERE) -> None:
    published, expected = build()
    for store, package in published.items():
        (target / f"{store}.json").write_text(json.dumps(package, indent=1, sort_keys=True) + "\n")
    (target / "expected.json").write_text(json.dumps(expected, indent=1, sort_keys=True) + "\n")
    corrected, notices, reports = build_notices(published)
    (target / "pi-corrected.json").write_text(json.dumps(corrected, indent=1, sort_keys=True) + "\n")
    (target / "notices.json").write_text(json.dumps(notices, indent=1, sort_keys=True) + "\n")
    (target / "notices-expected.json").write_text(json.dumps(reports, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    write(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE)
