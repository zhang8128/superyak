"""Issue #8's corpus v0: pages from a Wikipedia multistream dump become corpus records."""
import bz2

from experiments.multihop.wiki_dump import canonical, clean, lead, parse_pages, read_streams, records

PAGE = """<page><title>{title}</title><ns>{ns}</ns><id>{pid}</id>{redirect}<revision><id>{rid}</id>
<text bytes="1" xml:space="preserve">{text}</text></revision></page>"""


def page(title, pid, rid, text="", ns=0, redirect=None):
    from xml.sax.saxutils import escape, quoteattr
    r = f"<redirect title={quoteattr(redirect)} />" if redirect else ""
    return PAGE.format(title=escape(title), ns=ns, pid=pid, rid=rid, redirect=r, text=escape(text))


LOTUS = ("{{Infobox band|name=Lotus}}'''Lotus''' is a [[rock music|rock]] band whose singer was [[Ann Vale]].<ref>A "
         "source</ref> It formed in [[Leeds]].[[File:Lotus.jpg|thumb|The [[band]] live]]<!-- note -->\n\n"
         "It toured with [[Kestrel (band)|Kestrel]] and {{lang|fr|''les amis''}}.\n\n== History ==\nLater [[Moss]].")


def test_lead_stops_at_the_first_heading():
    assert lead("Intro text.\n\n== History ==\nMore.") == "Intro text."
    assert lead("No headings at all.") == "No headings at all."


def test_clean_keeps_the_words_and_collects_the_links():
    text, links = clean(lead(LOTUS))
    assert text == "Lotus is a rock band whose singer was Ann Vale. It formed in Leeds.\n\nIt toured with Kestrel and ."
    assert links == ["Rock music", "Ann Vale", "Leeds", "Kestrel (band)"]   # in order, no File: link, nothing from below


def test_nested_templates_tables_and_refs_go():
    text, links = clean("A {{x|{{y|[[Hidden]]}}}} B {| class=t\n| [[InTable]] |} C <ref name=r/> D <ref>[[InRef]]</ref> E")
    assert text == "A B C D E"
    assert links == []


def test_canonical_titles_follow_mediawiki():
    assert canonical("ann_vale") == "Ann vale"
    assert canonical("  Leeds#Geography ") == "Leeds"
    assert canonical("") == ""


def test_records_resolve_redirects_and_keep_only_articles():
    pages = [
        {"title": "Lotus (band)", "ns": 0, "page_id": 11, "rev_id": 101, "redirect": None, "text": LOTUS},
        {"title": "Ann Vale", "ns": 0, "page_id": 12, "rev_id": 102, "redirect": None, "text": "Ann Vale sings."},
        {"title": "Rock music", "ns": 0, "page_id": 13, "rev_id": 103, "redirect": None, "text": "Rock is music."},
        {"title": "Kestrel (band)", "ns": 0, "page_id": 14, "rev_id": 104, "redirect": "Kestrels", "text": "#REDIRECT"},
        {"title": "Kestrels", "ns": 0, "page_id": 15, "rev_id": 105, "redirect": None, "text": "Kestrels play."},
        {"title": "Talk:Lotus", "ns": 1, "page_id": 16, "rev_id": 106, "redirect": None, "text": "chat"},
        {"title": "Empty", "ns": 0, "page_id": 17, "rev_id": 107, "redirect": None, "text": "{{stub}}"},
    ]
    out = {r["title"]: r for r in records(pages)}
    assert set(out) == {"Lotus (band)", "Ann Vale", "Rock music", "Kestrels"}
    assert out["Lotus (band)"]["links"] == ["Rock music", "Ann Vale", "Leeds", "Kestrels"]   # the redirect resolved
    assert (out["Lotus (band)"]["page_id"], out["Lotus (band)"]["rev_id"]) == (11, 101)


def test_streams_are_read_by_the_index_offsets(tmp_path):
    header = "<mediawiki><siteinfo><sitename>Test</sitename></siteinfo>"
    groups = [[page("Lotus (band)", 11, 101, LOTUS), page("Ann Vale", 12, 102, "Ann Vale sings.")],
              [page("Kestrels", 15, 105, "Kestrels play.")]]
    blobs = [bz2.compress(header.encode())] + [bz2.compress("".join(g).encode()) for g in groups]
    blobs.append(bz2.compress(b"</mediawiki>"))
    dump = tmp_path / "dump.xml.bz2"
    dump.write_bytes(b"".join(blobs))
    offsets, at = [], 0
    for blob in blobs:
        offsets.append(at)
        at += len(blob)
    index = tmp_path / "index.txt.bz2"
    lines = [f"{offsets[1]}:11:Lotus (band)", f"{offsets[1]}:12:Ann Vale", f"{offsets[2]}:15:Kestrels"]
    index.write_bytes(bz2.compress(("\n".join(lines) + "\n").encode()))
    first = list(parse_pages(read_streams(dump, index, streams=1)))
    assert [p["title"] for p in first] == ["Lotus (band)", "Ann Vale"]
    both = list(parse_pages(read_streams(dump, index, streams=2)))
    assert [p["page_id"] for p in both] == [11, 12, 15] and both[0]["rev_id"] == 101
    assert both[0]["text"] == LOTUS


def test_a_stream_with_a_dtd_or_an_entity_is_refused():
    import pytest
    bomb = b'<!DOCTYPE p [<!ENTITY a "aaaa">]><page><title>&a;</title></page>'
    with pytest.raises(ValueError):
        list(parse_pages([bomb]))
    with pytest.raises(ValueError):
        list(parse_pages([b'<page><title>x</title></page><!ENTITY b "b">']))


def test_records_drop_self_links_and_oversized_leads():
    pages = [{"title": "Loop", "ns": 0, "page_id": 1, "rev_id": 1, "redirect": None, "text": "[[Loop]] and [[Other]]."},
             {"title": "Huge", "ns": 0, "page_id": 2, "rev_id": 2, "redirect": None, "text": "word " * 4000},
             {"title": "Edge", "ns": 0, "page_id": 3, "rev_id": 3, "redirect": None, "text": "x" * 18000}]
    out = {r["title"]: r for r in records(pages)}
    assert out["Loop"]["links"] == ["Other"]
    assert "Huge" not in out and "Edge" in out


def test_links_outside_the_articles_are_not_collected_and_repeats_count_once():
    text, links = clean("See [[Wikipedia:Policy]], [[wikt:yak|yak]], [[:fr:Paris]] and [[Yak]], the [[yak|yaks]].")
    assert links == ["Yak"]
    assert text == "See , yak, and Yak, the yaks."


def test_build_corpus_end_to_end_on_a_synthetic_dump(tmp_path):
    import json
    import sys
    from pathlib import Path
    import pytest
    atlas = Path(__file__).resolve().parents[2] / "atlas"
    if not (atlas / "workbench" / "research_corpus.py").exists():
        pytest.skip("atlas isn't beside engram here")
    sys.path.insert(0, str(atlas))
    from workbench.research_corpus import FrozenCorpus
    from experiments.multihop import build_corpus

    header = "<mediawiki><siteinfo><sitename>Test</sitename></siteinfo>"
    groups = [[page("Lotus (band)", 11, 101, LOTUS), page("Ann Vale", 12, 102, "Ann Vale sings."),
               page("Kestrel (band)", 14, 104, "#REDIRECT [[Kestrels]]", redirect="Kestrels")],
              [page("Kestrels", 15, 105, "Kestrels play."), page("Talk:Lotus", 16, 106, "chat", ns=1)],
              [page("Late", 17, 107, "Not in a one-stream slice.")]]
    blobs = [bz2.compress(header.encode())] + [bz2.compress("".join(g).encode()) for g in groups]
    blobs.append(bz2.compress(b"</mediawiki>"))
    dump = tmp_path / "dump.xml.bz2"
    dump.write_bytes(b"".join(blobs))
    offsets, at = [], 0
    for blob in blobs:
        offsets.append(at)
        at += len(blob)
    lines = [f"{offsets[1]}:11:Lotus (band)", f"{offsets[1]}:12:Ann Vale", f"{offsets[1]}:14:Kestrel (band)",
             f"{offsets[2]}:15:Kestrels", f"{offsets[2]}:16:Talk:Lotus", f"{offsets[3]}:17:Late"]
    index = tmp_path / "index.txt.bz2"
    index.write_bytes(bz2.compress(("\n".join(lines) + "\n").encode()))

    out = tmp_path / "corpus.sqlite3"
    assert build_corpus.main(["--dump", str(dump), "--index", str(index), "--snapshot", "2026-11-07",
                              "--out", str(out), "--work", str(tmp_path / "work"), "--streams", "2"]) == 0
    corpus = FrozenCorpus(out)
    assert corpus.manifest["id"] == "enwiki-20261107-s2"
    assert corpus.manifest["counts"] == {"pages": 5, "articles": 3, "redirects": 1, "skipped_empty_or_long": 0,
                                         "other_namespaces": 1}
    assert corpus.manifest["inputs"][0]["bytes"] == [offsets[1], offsets[3]]   # exactly the two streams read
    assert corpus.links("Lotus (band)") == ["Ann Vale", "Kestrels"]           # the redirect resolved, in the corpus
    assert [p["title"] for p in corpus.search("Kestrels play")["papers"]][0] == "Kestrels"
    assert corpus.search("Late")["papers"] == []
    with pytest.raises(FileExistsError):
        build_corpus.first_pass(dump, index, 1, tmp_path / "work")             # a work directory is never reused
    parallel = tmp_path / "parallel.sqlite3"
    assert build_corpus.main(["--dump", str(dump), "--index", str(index), "--snapshot", "2026-11-07", "--out",
                              str(parallel), "--work", str(tmp_path / "work2"), "--streams", "2", "--workers", "2"]) == 0
    assert FrozenCorpus(parallel).digest == corpus.digest                      # any number of workers, one corpus
    everything = tmp_path / "all.sqlite3"
    assert build_corpus.main(["--dump", str(dump), "--index", str(index), "--snapshot", "2026-11-07", "--out",
                              str(everything), "--work", str(tmp_path / "work3"), "--workers", "2"]) == 0
    assert FrozenCorpus(everything).manifest["counts"]["articles"] == 4         # all three streams: "Late" too
