"""A frozen local corpus as a research source, beside Europe PMC (issues #8 and #10)."""
import hashlib
import sqlite3

import pytest

from workbench.research_corpus import FrozenCorpus, build

MANIFEST = {"id": "wiki-test", "name": "Test Wikipedia", "snapshot": "2026-11-07",
            "url_template": "https://en.wikipedia.org/w/index.php?oldid={rev_id}",
            "inputs": [{"file": "dump.xml.bz2", "sha256": "ab" * 32}], "question_derived": False}

RECORDS = [
    {"title": "Lotus (band)", "page_id": 11, "rev_id": 1001, "text": "Lotus is a band whose singer was Ann Vale.",
     "links": ["Ann Vale", "Nowhere Page"]},
    {"title": "Ann Vale", "page_id": 12, "rev_id": 1002, "text": "Ann Vale later joined the band Kestrel.",
     "links": ["Kestrel (band)"]},
    {"title": "Kestrel (band)", "page_id": 13, "rev_id": 1003, "text": "Kestrel is a band from Leeds.\nIt has  two spaces.",
     "links": []},
]


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    summary = build(RECORDS, MANIFEST, path)
    return FrozenCorpus(path), summary, path


def test_build_counts_and_keeps_only_links_inside_the_corpus(corpus):
    provider, summary, _ = corpus
    assert summary["passages"] == 3
    assert summary["links"] == 2            # "Nowhere Page" isn't in the corpus
    assert provider.links("Lotus (band)") == ["Ann Vale"]
    assert provider.links("Ann Vale") == ["Kestrel (band)"]
    assert provider.links("No Such Title") == []


def test_search_ranks_by_bm25_and_pages_with_a_cursor(corpus):
    provider, _, _ = corpus
    page = provider.search("band singer", limit=1)
    assert [p["title"] for p in page["papers"]] == ["Lotus (band)"]
    assert page["next_cursor"] == "1"
    second = provider.search("band singer", cursor=page["next_cursor"], limit=5)
    assert {p["title"] for p in second["papers"]} == {"Ann Vale", "Kestrel (band)"}
    assert second["next_cursor"] is None
    assert provider.search("zzzz")["papers"] == []
    assert provider.search("band", limit=3)["next_cursor"] is None   # exactly a page: no next one


def test_a_query_with_fts_syntax_is_words_not_operators(corpus):
    provider, _, _ = corpus
    for query in ['band" OR "x', "NEAR(band singer)", "band*", "-band", "title:band", "(", '"']:
        provider.search(query)            # never an FTS5 syntax error


@pytest.mark.parametrize("bad", [dict(query=""), dict(query=" "), dict(query="x" * 2001), dict(query=7),
                                 dict(query="a", cursor=""), dict(query="a", cursor="-1"), dict(query="a", cursor="x"),
                                 dict(query="a", limit=0), dict(query="a", limit=26), dict(query="a", limit=True)])
def test_search_refuses_what_europe_pmc_refuses(corpus, bad):
    provider, _, _ = corpus
    with pytest.raises(ValueError):
        provider.search(**bad)


def test_a_paper_has_the_runners_fields_and_a_stable_source(corpus):
    provider, _, _ = corpus
    paper = provider.search("Leeds")["papers"][0]
    assert paper["key"] == "corpus:wiki-test:13"
    assert paper["source"]["id"] == "s-corpus-" + hashlib.sha256(b"corpus:wiki-test:13").hexdigest()[:20]
    assert set(paper["source"]) == {"id", "title", "url", "year", "citation"}
    assert paper["source"]["url"] == "https://en.wikipedia.org/w/index.php?oldid=1003"
    assert paper["source"]["year"] == 2026
    assert (paper["page_id"], paper["rev_id"]) == (13, 1003)


def test_read_returns_the_text_byte_for_byte_with_its_article_and_revision(corpus):
    provider, _, _ = corpus
    paper = provider.search("Leeds")["papers"][0]
    document = provider.read(paper)
    text = RECORDS[2]["text"]
    assert [p["text"] for p in document["passages"]] == [text]          # no whitespace folding
    assert "page 13" in document["passages"][0]["locator"] and "revision 1003" in document["passages"][0]["locator"]
    assert document["corpus"]["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert document["corpus"]["id"] == "wiki-test"
    for key in ("source", "passages", "coverage", "coverage_note", "retrieved_at", "content_sha256", "document_url"):
        assert key in document


def test_read_refuses_a_passage_whose_bytes_changed(corpus):
    provider, _, path = corpus
    paper = provider.search("Leeds")["papers"][0]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE passages SET text = text || '!' WHERE page_id = 13")
    with pytest.raises(ValueError, match="hash"):
        FrozenCorpus(path).read(paper)


def test_read_refuses_a_paper_from_another_corpus(corpus):
    provider, _, _ = corpus
    paper = provider.search("Leeds")["papers"][0] | {"key": "corpus:wiki-tesx:13"}  # same length as this one
    with pytest.raises(ValueError):
        provider.read(paper)


def test_the_provider_opens_read_only(corpus):
    provider, _, _ = corpus
    with pytest.raises(sqlite3.OperationalError):
        provider._db.execute("DELETE FROM passages")


def test_build_refuses_duplicates_bad_records_and_a_second_build(tmp_path):
    with pytest.raises(ValueError):
        build(RECORDS + [RECORDS[0]], MANIFEST, tmp_path / "a.sqlite3")
    with pytest.raises(ValueError):
        build([RECORDS[0] | {"rev_id": "x"}], MANIFEST, tmp_path / "b.sqlite3")
    with pytest.raises(ValueError):
        build([RECORDS[0] | {"page_id": 10**18}], MANIFEST, tmp_path / "b2.sqlite3")
    with pytest.raises(ValueError):
        build([RECORDS[0] | {"text": ""}], MANIFEST, tmp_path / "c.sqlite3")
    with pytest.raises(ValueError):
        build(RECORDS, MANIFEST | {"snapshot": "yesterday"}, tmp_path / "d.sqlite3")
    build(RECORDS, MANIFEST, tmp_path / "e.sqlite3")
    with pytest.raises(FileExistsError):
        build(RECORDS, MANIFEST, tmp_path / "e.sqlite3")


def test_the_rest_of_builds_rules(tmp_path):
    selfish = [RECORDS[0] | {"links": ["Lotus (band)", "Ann Vale"]}, RECORDS[1]]
    build(selfish, MANIFEST, tmp_path / "self.sqlite3")
    assert FrozenCorpus(tmp_path / "self.sqlite3").links("Lotus (band)") == ["Ann Vale"]   # no link to itself
    with pytest.raises(ValueError):
        build([RECORDS[0] | {"text": "x" * 18001}], MANIFEST, tmp_path / "long.sqlite3")
    build([RECORDS[0] | {"text": "x" * 18000}], MANIFEST, tmp_path / "edge.sqlite3")
    for bad in ({"url_template": "http://x/{rev_id}"}, {"url_template": "https://x/"}, {"question_derived": None},
                {"id": "Has Spaces"}):
        with pytest.raises(ValueError):
            build(RECORDS, MANIFEST | bad, tmp_path / "bad.sqlite3")
    with pytest.raises(ValueError):
        build([RECORDS[0], RECORDS[0]], MANIFEST, tmp_path / "dup.sqlite3")
    assert not (tmp_path / "dup.sqlite3").exists() and not (tmp_path / "dup.sqlite3.partial").exists()


def test_the_manifest_and_a_content_digest_are_kept(corpus):
    provider, summary, _ = corpus
    assert provider.manifest["snapshot"] == "2026-11-07"
    assert provider.manifest["question_derived"] is False
    assert provider.digest == summary["digest"] and len(summary["digest"]) == 64


def test_hostile_ids_and_queries_are_refused_or_cleaned(corpus):
    provider, _, _ = corpus
    for key in ("corpus:wiki-test:" + "9" * 40, "corpus:wiki-test:0", "corpus:wiki-test:013", "corpus:wiki-test:-1"):
        with pytest.raises(ValueError):
            provider.read({"key": key})
    paper = provider.search("Leeds \ud800 band")["papers"][0]
    paper["search_url"].encode("utf-8")      # the raw query, surrogate and all, never lands in the paper
