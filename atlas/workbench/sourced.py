"""North-star test 5: Atlas claims that cross with their sources' identity.

The design is docs/superpowers/specs/2026-11-22-claim-crossing-design.md (revision 6, 84fafe71, approved under station
law section 3). This module sits beside `lighthouse.py`'s projection, under its own profile, and builds on
`lighthouse_wire`'s seal, verify and authorize.

This first part is the source keys and the comparison of two sources. A strong key proves sameness, never difference.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit, urlunsplit

from .store import _normalized_title

KEY_FUNCTION = "source_key/1"
DOI_HOSTS = frozenset({"doi.org", "dx.doi.org", "www.doi.org"})
_DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[-._;()/:<>A-Za-z0-9]+", re.IGNORECASE)
_DOI_START = re.compile(r"10\.\d{4,9}/.")  # a prefix, a slash and a suffix: the citation pattern's shape (amendment 1)
_TRAILING = ".,;:"
_PAIRS = {")": "(", "]": "[", ">": "<"}
DEFAULT_PORTS = {"http": 80, "https": 443}


def _strip_trailing(doi: str) -> str:
    """Remove trailing . , ; : and any closing ) ] > while the match holds more closing than opening ones of that
    kind, repeatedly, until none is left (spec E1, G3)."""
    while doi:
        last = doi[-1]
        if last in _TRAILING:
            doi = doi[:-1]
        elif last in _PAIRS and doi.count(last) > doi.count(_PAIRS[last]):
            doi = doi[:-1]
        else:
            break
    return doi


def _doi_from_url(parts) -> str | None:
    """A doi.org url's whole path, decoded and lowercased, never through the regex, so < and > stay in it (C5, D5)."""
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in DOI_HOSTS:
        return None
    path = unquote(parts.path).lstrip("/")
    if path[:4].lower() == "doi:":
        path = path[4:]
    if path.endswith("/"):
        path = path[:-1]
    if not _DOI_START.match(path):
        return None
    return path.lower()


def _doi_from_citation(citation: str) -> str | None:
    """The first DOI in the citation, percent-decoded; none when it holds two distinct ones."""
    found = {_strip_trailing(match).lower() for match in _DOI_IN_TEXT.findall(unquote(citation))}
    found.discard("")
    return found.pop() if len(found) == 1 else None


def _url_key(parts) -> str:
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    if port is not None and port != DEFAULT_PORTS.get(parts.scheme.lower()):
        host = f"{host}:{port}"
    path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    return "url:" + urlunsplit(("https", host, path, parts.query, ""))


def source_key(record: dict) -> dict:
    """An Atlas source's keys: a strong url key (always), a strong DOI key when one is found, and a weak title key."""
    parts = urlsplit(record["url"])
    doi = _doi_from_url(parts)
    if doi is None:
        doi = _doi_from_citation(record.get("citation") or "")
    title = _normalized_title(record.get("title") or "")
    return {"url": _url_key(parts), "doi": f"doi:{doi}" if doi else None,
            "title": f"title:{title}:{record['year']}" if title else None, "fn": KEY_FUNCTION}


def _title_alone(key: dict) -> str | None:
    """The normalised title without the year, as rules 1 and 2 and rule 4 compare it (E4, G1)."""
    if key.get("title") is None:
        return None
    return key["title"].rsplit(":", 1)[0]


def compare_sources(a: dict, b: dict) -> str:
    """Two sources' keys compared by five rules in order; the first that holds wins (D1, E4, G1)."""
    title_a, title_b = _title_alone(a), _title_alone(b)
    same_title = title_a is not None and title_a == title_b
    if a["doi"] and b["doi"] and a["doi"] != b["doi"]:
        return "unclear" if same_title else "distinct"          # rules 2 and 1: a DOI decides
    strong_a = {a["url"], a["doi"]} - {None}
    strong_b = {b["url"], b["doi"]} - {None}
    if strong_a & strong_b or (a["title"] is not None and a["title"] == b["title"]):
        return "match"                                           # rule 3
    if same_title:
        return "unclear"                                         # rule 4: one title, different years
    return "distinct"                                            # rule 5
