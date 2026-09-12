"""Read-only Europe PMC retrieval with bounded, reproducible passage excerpts."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from http.client import HTTPException
from html.parser import HTMLParser
import json
import math
import re
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request
from xml.etree import ElementTree

from .research_http import _NoRedirect, _remaining, open_with_deadline

API_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PASSAGE_CHAR_LIMIT = 18000


_REQUEST_STATE = threading.local()
_REQUEST_SLOTS = {lane: threading.BoundedSemaphore(1) for lane in ("paper", "model")}


# The single transport boundary is replaceable in tests; adapters never follow
# provider-supplied URLs, redirects, or model-generated URLs.
def urlopen(request, *, timeout):
    return open_with_deadline(request, timeout=timeout, deadline=_REQUEST_STATE.deadline,
                              use_environment_proxy=_REQUEST_STATE.lane == "paper")


def _request_bytes(request: Request, timeout: float, max_bytes: int, *, lane: str = "paper") -> bytes:
    """Bound elapsed time, including DNS, headers, and continuously arriving body data.

    Absolute socket deadlines cover headers and body, and prevent late dispatch
    after DNS/connect. One daemon per fixed lane bounds an uninterruptible DNS
    call without blocking the other lane. A lane remains occupied until its
    worker cleans up; retries cannot accumulate abandoned threads.
    """
    deadline = time.monotonic() + _timeout(timeout)
    slot = _REQUEST_SLOTS[lane]
    if not slot.acquire(blocking=False):
        raise RuntimeError(f"Previous {lane} HTTP request is still finishing; one request may be in flight in this lane")
    done, cancelled = threading.Event(), threading.Event()
    state_lock = threading.Lock()
    state = {"response": None}

    def receive():
        try:
            _REQUEST_STATE.deadline = deadline
            _REQUEST_STATE.lane = lane
            _remaining(deadline)
            with urlopen(request, timeout=timeout) as response:
                with state_lock:
                    state["response"] = response
                if cancelled.is_set():
                    raise TimeoutError("HTTP request deadline expired")
                body = response.read(max_bytes + 1)
                _remaining(deadline)
            if len(body) > max_bytes:
                raise RuntimeError(f"HTTP response exceeds size limit ({max_bytes} bytes)")
            state["body"] = body
        except (OSError, URLError, HTTPException) as exc:
            if isinstance(exc, HTTPError):
                exc.close()
            state["error"] = RuntimeError(f"HTTP request failed: {exc}")
        except Exception as exc:
            state["error"] = exc
        finally:
            slot.release()
            done.set()

    try:
        threading.Thread(target=receive, name=f"atlas-http-{lane}", daemon=True).start()
    except Exception:
        slot.release()
        raise
    if not done.wait(max(0, deadline - time.monotonic())):
        cancelled.set()
        with state_lock:
            response = state["response"]
        # shutdown wakes a blocked read without taking BufferedReader's lock.
        # Closing the response here could itself block; its worker owns close.
        try:
            response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
        except (AttributeError, OSError):
            pass
        raise RuntimeError(f"HTTP request deadline exceeded ({timeout} seconds)")
    if "error" in state:
        raise state["error"]
    return state["body"]


def _json_response(request: Request, timeout: float, max_bytes: int, *, lane: str = "paper") -> dict:
    try:
        value = json.loads(_request_bytes(request, timeout, max_bytes, lane=lane))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Provider returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Provider JSON response must be an object")
    return value


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be a positive finite number")
    return value


def _space(text: str) -> str:
    return " ".join(text.split())


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "br", "div", "h2", "h3", "h4", "title", "sec"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        self.handle_starttag(tag, [])


def _plain(value) -> str:
    if not isinstance(value, str):
        return ""
    parser = _Text()
    parser.feed(value)
    return _space("".join(parser.parts))


def _paper(raw: dict, search_url: str) -> dict:
    title = _plain(raw.get("title"))
    abstract = _plain(raw.get("abstractText"))
    if not title:
        raise ValueError("missing title")
    if not abstract:
        raise ValueError("missing abstract")
    year_text = str(raw.get("pubYear", ""))
    if not re.fullmatch(r"\d{4}", year_text):
        raise ValueError("invalid publication year")
    year = int(year_text)
    if not 1000 <= year <= date.today().year + 1:
        raise ValueError("invalid publication year")
    if raw.get("firstPublicationDate"):
        try:
            date.fromisoformat(raw["firstPublicationDate"])
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid publication date") from exc
    doi = str(raw.get("doi") or "").strip().lower()
    if doi and not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
        doi = ""
    pmcid = str(raw.get("pmcid") or "").upper()
    if not re.fullmatch(r"PMC\d+", pmcid):
        pmcid = ""
    identifier = str(raw.get("id") or "")
    provider_source = str(raw.get("source") or "")
    if doi:
        key, url = f"doi:{doi}", "https://doi.org/" + quote(doi, safe="/():;._-")
    elif pmcid:
        key, url = f"pmcid:{pmcid}", f"https://europepmc.org/articles/{pmcid}"
    elif identifier and re.fullmatch(r"[A-Z]+", provider_source):
        key = f"europepmc:{provider_source}:{identifier}"
        url = f"https://europepmc.org/article/{provider_source}/{quote(identifier, safe='')}"
    else:
        raise ValueError("missing stable provider identity")
    types = raw.get("pubTypeList", {})
    publication_types = types.get("pubType", []) if isinstance(types, dict) else []
    if not isinstance(publication_types, list):
        publication_types = []
    publication_types = [value.strip() for value in publication_types if isinstance(value, str) and value.strip()]
    author = _plain(raw.get("authorString"))
    journal = _plain(raw.get("journalTitle"))
    journal_info = raw.get("journalInfo")
    if not journal and isinstance(journal_info, dict) and isinstance(journal_info.get("journal"), dict):
        journal = _plain(journal_info["journal"].get("title"))
    citation = f"{author + '. ' if author else ''}{title}. {journal + '. ' if journal else ''}({year})."
    if doi:
        citation += f" DOI: {doi}."
    source = {"id": "s-epmc-" + hashlib.sha256(key.encode()).hexdigest()[:20],
              "title": title, "url": url, "year": year, "citation": citation}
    return {"key": key, "doi": doi, "pmcid": pmcid, "id": identifier, "provider_id": identifier,
            "provider_source": provider_source, "title": title, "year": year,
            "citation": citation, "source": source, "abstract": abstract,
            "publication_types": publication_types, "search_url": search_url,
            "is_open_access": raw.get("isOpenAccess") == "Y"}


def _passages(entries: list[tuple[str, str]]) -> list[dict[str, str]]:
    passages = []
    remaining = PASSAGE_CHAR_LIMIT
    for locator, text in entries:
        text = _space(text)
        if not text or remaining <= 0:
            continue
        excerpt = text[:remaining].rstrip()
        if len(text) > remaining and " " in excerpt:
            excerpt = excerpt.rsplit(" ", 1)[0]
        if not excerpt:
            continue
        index = len(passages) + 1
        passages.append({"id": f"p{index:04d}", "locator": f"{locator}, paragraph {index}", "text": excerpt})
        remaining -= len(excerpt)
        if len(text) > len(excerpt):
            break
    return passages


def _xml_passages(content: bytes) -> list[dict[str, str]]:
    if re.search(br"<!ENTITY\b", content, re.IGNORECASE):
        raise ValueError("XML entity declarations are not supported")
    root = ElementTree.fromstring(content)
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    excluded = {"ref-list", "ref", "table-wrap", "table", "fig", "supplementary-material"}
    for parent in root.iter():
        previous = None
        for child in list(parent):
            if child.tag in excluded:
                # Keep prose following an omitted block, without retaining its
                # captions/cells or accidentally joining surrounding words.
                tail = " " + (child.tail or "")
                if previous is None:
                    parent.text = (parent.text or "") + tail
                else:
                    previous.tail = (previous.tail or "") + tail
                parent.remove(child)
            else:
                previous = child
    body = root.find("body")
    if body is None:
        raise ValueError("full text has no article body")
    entries = []
    for abstract in root.findall("./front/article-meta/abstract"):
        paragraphs = abstract.findall(".//p")
        if paragraphs:
            entries.extend(("Abstract", "".join(p.itertext())) for p in paragraphs)
        else:
            entries.append(("Abstract", "".join(abstract.itertext())))

    def visit(node, sections):
        if node.tag == "sec":
            title = node.find("title")
            if title is not None:
                sections = [*sections, _space("".join(title.itertext()))]
        if node.tag == "p":
            entries.append((" / ".join(sections) or "Body", "".join(node.itertext())))
        else:
            for child in node:
                visit(child, sections)

    visit(body, [])
    if not any(locator != "Abstract" and _space(text) for locator, text in entries):
        raise ValueError("full text has no readable body paragraphs")
    return _passages(entries)


class EuropePMC:
    def __init__(self, timeout: float = 30):
        self.timeout = _timeout(timeout)

    def search(self, query: str, cursor: str = "*", limit: int = 5) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError("query must be nonblank and at most 2000 characters")
        if not isinstance(cursor, str) or not cursor or len(cursor) > 10000:
            raise ValueError("cursor must be a nonblank bounded string")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
            raise ValueError("limit must be between 1 and 25")
        url = API_BASE + "/search?" + urlencode({
            "query": f"({query.strip()}) AND HAS_ABSTRACT:Y", "format": "json",
            "resultType": "core", "pageSize": limit, "cursorMark": cursor,
        })
        result = _json_response(Request(url, headers={"Accept": "application/json"}), self.timeout, 4 * 1024 * 1024)
        result_list = result.get("resultList")
        rows = result_list.get("result") if isinstance(result_list, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Europe PMC resultList.result must be a list")
        papers, skipped = [], []
        for raw in rows:
            try:
                if not isinstance(raw, dict):
                    raise ValueError("result must be an object")
                papers.append(_paper(raw, url))
            except ValueError as exc:
                skipped.append({"id": str(raw.get("id", "")) if isinstance(raw, dict) else "", "reason": str(exc)})
        papers.sort(key=lambda paper: not any(
            kind.lower() in {"journal article", "research-article", "research article", "preprint"}
            for kind in paper["publication_types"]
        ) or any(kind.lower() == "review" for kind in paper["publication_types"]))
        next_cursor = result.get("nextCursorMark")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor or not rows:
            next_cursor = None
        return {"papers": papers, "next_cursor": next_cursor, "skipped": skipped}

    def read(self, paper: dict) -> dict:
        abstract = paper.get("abstract")
        if not isinstance(abstract, str) or not abstract.strip():
            raise ValueError("paper has no readable abstract")
        coverage = "abstract_only"
        coverage_note = "No valid PMC full-text identifier is available; only the provider abstract was read."
        passages = _passages([("Abstract", abstract)])
        document_url = paper["search_url"]
        pmcid = paper.get("pmcid", "")
        if isinstance(pmcid, str) and re.fullmatch(r"PMC\d+", pmcid):
            full_text_url = f"{API_BASE}/{pmcid}/fullTextXML"
            try:
                content = _request_bytes(Request(full_text_url, headers={"Accept": "application/xml"}), self.timeout, 10 * 1024 * 1024)
                passages = _xml_passages(content)
                coverage = "full_text_excerpt"
                coverage_note = "Selected normalized abstract/body paragraphs, capped at 18000 characters; references, tables and figures are omitted."
                document_url = full_text_url
            except (RuntimeError, ValueError, ElementTree.ParseError) as exc:
                coverage_note = f"Full text unavailable ({exc}); only the provider abstract was read."
        serialized = json.dumps(passages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {"source": dict(paper["source"]), "passages": passages, "coverage": coverage,
                "coverage_note": coverage_note, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "content_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                "document_url": document_url, "publication_types": list(paper.get("publication_types", []))}
