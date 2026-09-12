"""Provider metadata and text provenance at the HTTP boundary."""

import hashlib
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest


def record(**changes):
    return {
        "id": "12345", "source": "MED", "pmid": "12345", "pmcid": "PMC12345",
        "doi": "10.1234/Example", "title": "A <i>cell fate</i> study",
        "authorString": "Smith A, Jones B", "pubYear": "2024",
        "firstPublicationDate": "2024-02-29", "journalTitle": "Cell Example",
        "abstractText": "<h4>Results</h4><p>Cells adopted a stable fate.</p>",
        "isOpenAccess": "Y", "pubTypeList": {"pubType": ["Journal Article"]},
        **changes,
    }


def transport(monkeypatch, responses):
    from workbench import research_sources
    requests = []

    def open_response(request, *, timeout):
        requests.append((request, timeout))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response if isinstance(response, bytes) else json.dumps(response).encode())

    monkeypatch.setattr(research_sources, "urlopen", open_response)
    return requests


def search_response(*records, cursor="next-page"):
    return {"hitCount": len(records), "nextCursorMark": cursor,
            "resultList": {"result": list(records)}}


def test_search_preserves_provider_identity_and_cursor_and_explicitly_skips_invalid_records(monkeypatch):
    from workbench.research_sources import EuropePMC

    requests = transport(monkeypatch, [search_response(
        record(), record(id="bad-date", firstPublicationDate="2024-02-30"),
        record(id="no-title", title=" "), record(id="no-abstract", abstractText=""),
    )])
    result = EuropePMC().search("cell fate", cursor="older+page")
    assert len(result["papers"]) == 1
    paper = result["papers"][0]
    assert paper["key"] == "doi:10.1234/example"
    assert paper["source"]["url"] == "https://doi.org/10.1234/example"
    assert paper["source"]["title"] == "A cell fate study"
    assert paper["source"]["year"] == 2024
    assert "Smith A, Jones B" in paper["source"]["citation"]
    assert paper["publication_types"] == ["Journal Article"]
    assert paper["provider_id"] == "12345"
    assert paper["provider_source"] == "MED"
    assert result["next_cursor"] == "next-page"
    assert {entry["id"] for entry in result["skipped"]} == {"bad-date", "no-title", "no-abstract"}
    assert all(entry["reason"] for entry in result["skipped"])
    url = urlsplit(requests[0][0].full_url)
    assert url.hostname == "www.ebi.ac.uk"
    query = parse_qs(url.query)
    assert query["cursorMark"] == ["older+page"]
    assert query["pageSize"] == ["5"]
    assert "HAS_ABSTRACT:Y" in query["query"][0]
    assert 0 < requests[0][1] <= 120


def test_read_labels_and_hashes_exact_normalized_full_text_passages(monkeypatch):
    from workbench.research_sources import EuropePMC

    xml = b'''<article><front><article-meta><abstract><p>Cells adopted a stable fate.</p></abstract>
    </article-meta></front><body><sec><title>Results</title><p>Lineage <italic>tracking</italic>
    established the result.</p><sec><title>Controls</title><p>Three controls agreed.</p></sec></sec>
    </body><back><ref-list><ref><mixed-citation>Unrelated citation.</mixed-citation></ref></ref-list></back></article>'''
    requests = transport(monkeypatch, [search_response(record()), xml])
    provider = EuropePMC()
    document = provider.read(provider.search("cell fate")["papers"][0])
    assert document["coverage"] == "full_text_excerpt"
    assert [p["text"] for p in document["passages"]] == [
        "Cells adopted a stable fate.", "Lineage tracking established the result.", "Three controls agreed.",
    ]
    assert len({p["id"] for p in document["passages"]}) == 3
    assert "Results" in document["passages"][1]["locator"]
    assert "Controls" in document["passages"][2]["locator"]
    assert "paragraph" in document["passages"][2]["locator"]
    assert requests[1][0].full_url.endswith("/PMC12345/fullTextXML")
    assert document["document_url"] == requests[1][0].full_url
    serialized = json.dumps(document["passages"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert document["content_sha256"] == hashlib.sha256(serialized.encode()).hexdigest()
    assert document["retrieved_at"].endswith("+00:00")


@pytest.mark.parametrize("response", [
    HTTPError("https://www.ebi.ac.uk/", 404, "Not found", {}, None),
    b"<article><body><p>broken XML",
    b"<article><body/></article>",
])
def test_unavailable_or_invalid_full_text_is_explicit_abstract_fallback(monkeypatch, response):
    from workbench.research_sources import EuropePMC

    transport(monkeypatch, [search_response(record()), response])
    provider = EuropePMC()
    document = provider.read(provider.search("cell fate")["papers"][0])
    assert document["coverage"] == "abstract_only"
    assert document["coverage_note"]
    assert "Cells adopted a stable fate." in document["passages"][0]["text"]
    assert "Abstract" in document["passages"][0]["locator"]
    assert document["document_url"].startswith("https://www.ebi.ac.uk/europepmc/webservices/rest/search?")


def test_full_text_prompt_budget_is_bounded_without_claiming_complete_coverage(monkeypatch):
    from workbench.research_sources import EuropePMC

    paragraphs = "".join(f"<p>Paragraph {i}. " + "word " * 2000 + "</p>" for i in range(5))
    transport(monkeypatch, [search_response(record()), f"<article><body><sec><title>Results</title>{paragraphs}</sec></body></article>".encode()])
    provider = EuropePMC()
    document = provider.read(provider.search("fate")["papers"][0])
    assert 0 < sum(len(p["text"]) for p in document["passages"]) <= 18000
    assert document["coverage"] == "full_text_excerpt"


def test_search_rejects_oversized_and_malformed_responses(monkeypatch):
    from workbench.research_sources import EuropePMC

    transport(monkeypatch, [b"x" * (4 * 1024 * 1024 + 1), {"resultList": {"result": "invalid"}}])
    with pytest.raises(RuntimeError, match="size|large|limit"):
        EuropePMC().search("fate")
    with pytest.raises(ValueError, match="result"):
        EuropePMC().search("fate")


def test_untrusted_urls_and_malformed_pmcids_never_become_requests(monkeypatch):
    from workbench.research_sources import EuropePMC

    requests = transport(monkeypatch, [search_response(record(
        pmcid="../../private", fullTextUrlList={"fullTextUrl": [{"url": "http://localhost/private"}]},
    ))])
    provider = EuropePMC()
    document = provider.read(provider.search("fate")["papers"][0])
    assert document["coverage"] == "abstract_only"
    assert len(requests) == 1


def test_preprints_and_articles_precede_reviews_and_cursor_exhaustion_is_explicit(monkeypatch):
    from workbench.research_sources import EuropePMC

    transport(monkeypatch, [search_response(
        record(id="review", doi="10.1234/review", pubTypeList={"pubType": ["Review"]}),
        record(id="preprint", doi="10.1234/preprint", pubTypeList={"pubType": ["Preprint"]}),
        cursor="*",
    )])
    result = EuropePMC().search("fate")
    assert result["papers"][0]["key"] == "doi:10.1234/preprint"
    assert result["next_cursor"] is None


@pytest.mark.parametrize(("changes", "key", "url"), [
    ({"doi": ""}, "pmcid:PMC12345", "https://europepmc.org/articles/PMC12345"),
    ({"doi": "", "pmcid": ""}, "europepmc:MED:12345", "https://europepmc.org/article/MED/12345"),
])
def test_provider_identity_is_stable_without_doi(monkeypatch, changes, key, url):
    from workbench.research_sources import EuropePMC

    transport(monkeypatch, [search_response(record(**changes)), search_response(record(**changes))])
    first = EuropePMC().search("fate")["papers"][0]
    repeated = EuropePMC().search("lineage")["papers"][0]
    assert first["key"] == key
    assert first["source"]["url"] == url
    assert first["source"]["id"] == repeated["source"]["id"]


def test_core_record_journal_info_is_in_citation(monkeypatch):
    from workbench.research_sources import EuropePMC

    transport(monkeypatch, [search_response(record(journalTitle=None,
        journalInfo={"journal": {"title": "Provider journal"}, "yearOfPublication": 2024}))])
    paper = EuropePMC().search("fate")["papers"][0]
    assert "Provider journal" in paper["source"]["citation"]


def test_incomplete_http_body_is_reported_as_provider_failure(monkeypatch):
    from workbench.research_sources import EuropePMC

    transport(monkeypatch, [IncompleteRead(b"partial", 100)])
    with pytest.raises(RuntimeError, match="HTTP"):
        EuropePMC().search("fate")


def test_provider_redirect_is_rejected_without_following_arbitrary_target():
    from urllib.request import Request
    from workbench.research_sources import _NoRedirect

    with pytest.raises(HTTPError, match="Redirect"):
        _NoRedirect().redirect_request(Request("https://www.ebi.ac.uk/test"), io.BytesIO(),
                                      302, "Found", {}, "http://127.0.0.1/private")


def test_entity_xml_falls_back_without_including_expanded_text(monkeypatch):
    from workbench.research_sources import EuropePMC

    transport(monkeypatch, [search_response(record()),
        b'<!DOCTYPE article [<!ENTITY fake "Injected result">]><article><body><p>&fake;</p></body></article>'])
    provider = EuropePMC()
    document = provider.read(provider.search("fate")["papers"][0])
    assert document["coverage"] == "abstract_only"
    assert "Injected result" not in str(document["passages"])


@pytest.fixture
def dripping_http_server():
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if self.path == "/headers":
                    data = b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndata"
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "40")
                    self.end_headers()
                    data = b"x" * 40
                for byte in data:
                    self.connection.sendall(bytes([byte]))
                    if stop.wait(0.02):
                        break
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", stop
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)


@pytest.mark.parametrize("path", ["/body", "/headers"])
def test_elapsed_deadline_covers_slow_drip_headers_and_body(dripping_http_server, path):
    from workbench.research_sources import _request_bytes

    base_url, stop = dripping_http_server
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="deadline|timed out"):
            _request_bytes(Request(base_url + path), timeout=0.12, max_bytes=100)
        assert time.monotonic() - started < 0.5
    finally:
        stop.set()


def test_timeout_before_response_returns_promptly_and_retries_do_not_accumulate_threads(monkeypatch):
    from workbench import research_sources

    release = threading.Event()
    exited = threading.Event()
    opened = []
    workers = []

    def stuck_open(request, *, timeout):
        workers.append(threading.current_thread())
        opened.append(request.full_url)
        release.wait(1)
        exited.set()
        return io.BytesIO(b"late")

    monkeypatch.setattr(research_sources, "urlopen", stuck_open)
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="deadline|timed out"):
            research_sources._request_bytes(Request("http://127.0.0.1/slow"), 0.05, 100)
        for _ in range(5):
            with pytest.raises(RuntimeError, match="finishing|in flight"):
                research_sources._request_bytes(Request("http://127.0.0.1/retry"), 0.05, 100)
        assert time.monotonic() - started < 0.4
        assert opened == ["http://127.0.0.1/slow"]
    finally:
        release.set()
        assert exited.wait(1)
        workers[0].join(timeout=1)
        assert not workers[0].is_alive()
    monkeypatch.setattr(research_sources, "urlopen", lambda *args, **kwargs: io.BytesIO(b"recovered"))
    assert research_sources._request_bytes(Request("http://127.0.0.1/recovered"), 0.5, 100) == b"recovered"


def test_uninterruptible_open_does_not_delay_process_shutdown():
    code = '''
import io
import time
from urllib.request import Request
from workbench import research_sources
def stuck_open(*args, **kwargs):
    time.sleep(10)
    return io.BytesIO(b"late")
research_sources.urlopen = stuck_open
try:
    research_sources._request_bytes(Request("http://127.0.0.1/slow"), 0.05, 100)
except RuntimeError:
    print("deadline returned")
'''
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=2)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "deadline returned"


def test_xml_omits_nested_figures_tables_and_references_but_keeps_surrounding_text(monkeypatch):
    from workbench.research_sources import EuropePMC

    xml = b'''<article><front><article-meta><abstract><p>Abstract result.
    <fig><caption><p>Hidden abstract caption.</p></caption></fig> Remaining abstract text.</p></abstract></article-meta></front>
    <body><sec><title>Results</title><p>Cells <italic>changed</italic> fate.
    <fig><caption><p>Hidden figure caption.</p></caption></fig> Controls agreed.
    <table-wrap><table><tr><td>Hidden table cell.</td></tr></table></table-wrap> The result persisted.
    <ref-list><ref><mixed-citation>Hidden reference.</mixed-citation></ref></ref-list> Further work remains.
    <ref><mixed-citation>Hidden standalone reference.</mixed-citation></ref>
    <supplementary-material><p>Hidden supplement.</p></supplementary-material> Final observation.</p>
    </sec></body></article>'''
    transport(monkeypatch, [search_response(record()), xml])
    provider = EuropePMC()
    document = provider.read(provider.search("fate")["papers"][0])
    assert [p["text"] for p in document["passages"]] == [
        "Abstract result. Remaining abstract text.",
        "Cells changed fate. Controls agreed. The result persisted. Further work remains. Final observation.",
    ]
    assert document["coverage"] == "full_text_excerpt"
