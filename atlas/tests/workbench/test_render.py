import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from workbench import render
from workbench.store import Store, WorkbenchError
from test_cli import run_cli


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


@pytest.fixture
def bundle():
    return {
        "schema_version": 1, "title": "A <local> workbench",
        "sources": [{"id": "s", "title": "Primary paper", "url": "https://example.org/paper?a=1&b=2",
                     "year": 2024, "citation": "Researcher (2024)"}],
        "items": [
            {"id": "q", "kind": "question", "title": "Which fate?", "summary": "Compare alternatives",
             "facets": {"scale": ["molecular", "cellular"], "method": ["lineage tracing"]}},
            {"id": "c", "kind": "claim", "title": "A scoped finding", "summary": "Restricted finding",
             "status": "source_reported", "context": {"limitation": "Only this system"},
             "evidence": [{"source_id": "s", "locator": "Discussion, paragraph 3", "note": "Reported boundary"}]},
        ],
        "relations": [{"id": "r", "subject": "c", "predicate": "informs", "object": "q",
                       "rationale": "Our proposed interpretation"}],
    }


def test_render_preserves_unsafe_strings_as_data_without_executable_markup(bundle):
    attack = '</script><script>alert(1)</script><img src=x onerror=alert(2)>'
    bundle["title"] = attack
    bundle["items"][0]["title"] = attack
    bundle["items"][0]["provenance"] = {"path": "file:///private/local.md"}
    html = render.render_bundle(bundle)
    page = Page(html)
    assert attack not in html
    assert not any(tag == "img" or "onerror" in attrs for tag, attrs in page.tags)
    assert not any(attrs.get("href", "").startswith("file:") for _, attrs in page.tags)
    assert attack in "".join(page.text)
    start = html.index('<script id="bundle-data" type="application/json">')
    raw_json = html[start:].split(">", 1)[1].split("</script>", 1)[0]
    assert all(character not in raw_json for character in "<>&")
    assert json.loads(raw_json)["title"] == attack


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,hello", "file:///tmp/paper", "https://[bad"])
def test_render_rejects_unsafe_or_malformed_source_urls(bundle, url):
    bundle["sources"][0]["url"] = url
    with pytest.raises(WorkbenchError, match="url"):
        render.render_bundle(bundle)


def test_details_include_evidence_relations_scope_and_local_withdrawal_history(tmp_path, bundle):
    with Store(tmp_path / "db", create=True) as store:
        store.import_bundle(bundle)
        store.set_status("c", "withdrawn", "Scope was overstated", "Local reader")
        html = render.render_bundle(store.export_bundle())
    page = Page(html)
    visible_text = " ".join(page.text)
    for value in ("Discussion, paragraph 3", "Only this system", "Our proposed interpretation",
                  "proposed", "withdrawn", "Scope was overstated", "Local reader", "informs"):
        assert value in visible_text
    assert any(attrs.get("href") == "https://example.org/paper?a=1&b=2" for _, attrs in page.tags)


def test_page_exposes_labeled_search_facets_status_controls_and_empty_states(bundle):
    page = Page(render.render_bundle(bundle))
    ids = {attrs["id"] for _, attrs in page.tags if "id" in attrs}
    labeled = {attrs["for"] for tag, attrs in page.tags if tag == "label" and "for" in attrs}
    assert {"search", "kind", "status"} <= ids & labeled
    selects = [attrs for tag, attrs in page.tags if tag == "select" and "data-facet" in attrs]
    assert {attrs["data-facet"] for attrs in selects} == {"scale", "method"}
    assert all(attrs["id"] in labeled for attrs in selects)
    text = " ".join(page.text)
    assert "No records match" in text
    assert "prerequisites have not been adjudicated" in text
    empty = Page(render.render_bundle({"schema_version": 1, "title": "Empty", "sources": [], "items": [], "relations": []}))
    assert "No questions in this collection" in " ".join(empty.text)


def initialized(tmp_path, bundle):
    db = tmp_path / "workbench.db"
    source = tmp_path / "source.json"
    source.write_text(json.dumps(bundle))
    assert run_cli("--db", db, "init").returncode == 0
    assert run_cli("--db", db, "import", source).returncode == 0
    return db, source


def test_render_cli_creates_and_replaces_only_its_own_html(tmp_path, bundle):
    db, _ = initialized(tmp_path, bundle)
    output = tmp_path / "view.html"
    first = run_cli("--db", db, "render", "--output", output)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["output"] == str(output)
    assert "Which fate?" in output.read_text()
    before = output.read_bytes()
    second = run_cli("--db", db, "render", "--output", output)
    assert second.returncode == 0, second.stderr
    assert output.read_bytes() == before


def test_render_refuses_database_source_unrelated_and_symlink_outputs(tmp_path, bundle):
    db, source = initialized(tmp_path, bundle)
    unrelated = tmp_path / "notes.html"
    unrelated.write_text("Important notes")
    marked = tmp_path / "generated.html"
    assert run_cli("--db", db, "render", "--output", marked).returncode == 0
    alias = tmp_path / "alias.html"
    alias.symlink_to(marked)
    hardlink = tmp_path / "database-alias.html"
    hardlink.hardlink_to(db)
    for output in (db, source, unrelated, alias, hardlink):
        before = output.read_bytes()
        result = run_cli("--db", db, "render", "--output", output)
        assert result.returncode == 2, result.stderr
        assert result.stdout == ""
        assert output.read_bytes() == before
    assert alias.is_symlink()


def test_atomic_render_failure_preserves_previous_document_and_cleans_tempfile(tmp_path, bundle, monkeypatch):
    db, _ = initialized(tmp_path, bundle)
    output = tmp_path / "view.html"
    assert run_cli("--db", db, "render", "--output", output).returncode == 0
    before = output.read_bytes()
    files_before = set(tmp_path.iterdir())

    def fail_replace(source, destination):
        # Real temporary file must contain a complete document before replacement.
        assert Path(source).read_text().endswith("</html>\n")
        raise OSError("simulated filesystem replacement failure")

    monkeypatch.setattr(render.os, "replace", fail_replace)
    with pytest.raises(WorkbenchError, match="replacement failure"):
        render.write_rendered_bundle(bundle, output, db)
    assert output.read_bytes() == before
    assert set(tmp_path.iterdir()) == files_before


def test_render_missing_database_does_not_create_any_output(tmp_path):
    db, output = tmp_path / "missing.db", tmp_path / "view.html"
    result = run_cli("--db", db, "render", "--output", output)
    assert result.returncode == 2
    assert "does not exist" in result.stderr
    assert not db.exists() and not output.exists()


def test_large_collection_bounds_question_preview_and_keeps_all_records_searchable():
    data = {
        "schema_version": 1, "title": "Many questions", "sources": [], "relations": [],
        "items": [{"id": f"q-{index:03d}", "kind": "question", "title": f"Question {index}", "summary": "Proposed legacy question"} for index in range(100)],
    }
    page = Page(render.render_bundle(data))
    assert sum(attrs.get("class") == "question-card" for _, attrs in page.tags) == 2
    assert sum("data-list-id" in attrs for _, attrs in page.tags) == 100
    assert sum("data-record-id" in attrs for _, attrs in page.tags) == 100
    assert "Showing 2 of 100 questions" in " ".join(page.text)
    assert any(attrs.get("href") == "#workspace" and attrs.get("class") == "browse-all" for _, attrs in page.tags)


@pytest.mark.parametrize("status", ["proposed", "source_reported", "reviewed"])
def test_question_card_labels_connected_test_with_its_actual_status(bundle, status):
    bundle["items"].append({
        "id": "e", "kind": "experiment", "title": "Outcome comparison", "summary": "Test the prediction",
        "status": status, "reviewed_by": "Local reader" if status == "reviewed" else "",
        "reviewed_at": "2026-09-07T12:00:00Z" if status == "reviewed" else "",
    })
    bundle["relations"].append({"id": "test-link", "subject": "e", "predicate": "tests", "object": "q"})
    html = render.render_bundle(bundle)
    connected_test = Page(html.split('<p class="next-test">', 1)[1].split('</p>', 1)[0])
    assert "Connected test" in connected_test.text
    assert "Proposed next test" not in connected_test.text
    assert status.replace("_", "-") in connected_test.text
    assert any(attrs.get("class") == f"badge {status}" for _, attrs in connected_test.tags)


@pytest.mark.parametrize("count, expected", [
    (0, "0 questions · 0 approaches · 0 claims · 0 experiments · 0 sources"),
    (1, "1 question · 1 approach · 1 claim · 1 experiment · 1 source"),
    (2, "2 questions · 2 approaches · 2 claims · 2 experiments · 2 sources"),
])
def test_collection_counts_use_correct_singular_and_plural_labels(bundle, count, expected):
    bundle["items"] = [
        {"id": f"{kind}-{index}", "kind": kind, "title": "Record", "summary": "Scope"}
        for kind in ("question", "approach", "claim", "experiment") for index in range(count)
    ]
    bundle["sources"] = [{**bundle["sources"][0], "id": f"s-{index}"} for index in range(count)]
    bundle["relations"] = []
    html = render.render_bundle(bundle)
    counts = Page(html.split('<p class="collection-counts">', 1)[1].split('</p>', 1)[0])
    assert counts.text[0] == expected


@pytest.mark.parametrize("count, expected", [(0, "0 records"), (1, "1 record"), (2, "2 records")])
def test_initial_browser_count_uses_correct_record_label(bundle, count, expected):
    bundle["items"] = [{"id": f"q-{index}", "kind": "question", "title": "Question", "summary": "Scope"} for index in range(count)]
    bundle["relations"] = []
    html = render.render_bundle(bundle)
    initial_count = Page(html.split('<p id="result-count"', 1)[1].split('>', 1)[1].split('</p>', 1)[0])
    assert initial_count.text == [expected]
