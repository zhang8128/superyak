"""Research exports preserve evidence, resolve links, and leave personal notes intact."""

import json
from pathlib import Path
import re
import shutil

import pytest

from workbench.automation import ResearchInbox


@pytest.fixture
def project(tmp_path):
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "workbench/data", tmp_path / "workbench/data")
    return tmp_path


@pytest.fixture
def draft():
    return {"idempotency_key": "vault-check", "kind": "claim", "title": "A scoped finding",
            "summary": "A proposed interpretation with an independent outcome check.",
            "views": ["prediction", "regulation"],
            "context": {"scope": "Only the observed cells", "limitations": "Not independently validated"},
            "evidence": [{"source_id": "s-cellrank", "locator": "Abstract", "note": "A source-backed test fixture."}],
            "links": [{"predicate": "informs", "target": "q-fate", "rationale": "Motivates validation."}]}


def test_refresh_exports_complete_linked_research_and_visual_map(project):
    inbox = ResearchInbox(project)
    before = (project / "workbench/data/cell_fate.json").read_bytes()
    result = inbox.refresh()
    views = result.get("research_views")
    assert views is not None, "refresh must publish the Obsidian research views"
    assert views["status"] == "current"
    assert views["record_count"] == 17
    assert views["source_count"] == 6
    notes = list((project / "Research").rglob("*.md"))
    stems = {path.stem for path in notes}
    for path in notes:
        for target in re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", path.read_text()):
            assert target in stems or (project / "Research" / target).is_file(), (path, target)
    home = Path(views["home"]).read_text()
    assert "How well can measured cellular state predict cell fate" in home
    assert "Atlas Map.canvas" in home
    assert "17 records" in home
    canvas = json.loads(Path(views["canvas"]).read_text())
    identifiers = {node["id"] for node in canvas["nodes"]}
    assert canvas["edges"]
    assert all(edge["fromNode"] in identifiers and edge["toNode"] in identifiers for edge in canvas["edges"])
    assert "Cell fate" in Path(views["browser"]).read_text()
    assert (project / "workbench/data/cell_fate.json").read_bytes() == before


def test_record_automatically_exports_status_evidence_scope_and_same_identity_in_two_views(project, draft):
    inbox = ResearchInbox(project)
    receipt = inbox.record(draft, "test-session")
    assert receipt.get("research_views", {}).get("status") == "current"
    records = list((project / "Research/Records").glob("*.md"))
    matching = [path for path in records if "# A scoped finding" in path.read_text()]
    assert len(matching) == 1
    text = matching[0].read_text()
    for expected in ("proposed", "Only the observed cells", "Not independently validated", "Abstract",
                     "A source-backed test fixture", "test-session", "informs", "Motivates validation"):
        assert expected in text
    assert "s-cellrank" in text
    assert all(matching[0].stem in path.read_text() for path in (project / "Research/Lighthouses").glob("*.md"))


def test_refresh_preserves_annotations_and_avoids_rewriting_unchanged_notes(project):
    inbox = ResearchInbox(project)
    first = inbox.refresh()
    assert "research_views" in first
    home = Path(first["research_views"]["home"])
    with home.open("a") as stream:
        stream.write("\nMy own [[Personal idea]] stays here.\n")
    stamp = home.stat().st_mtime_ns
    assert inbox.refresh()["research_views"]["status"] == "current"
    assert home.stat().st_mtime_ns == stamp
    assert "My own [[Personal idea]] stays here." in home.read_text()


def test_edited_generated_text_is_preserved_and_does_not_prevent_capture(project, draft):
    inbox = ResearchInbox(project)
    first = inbox.refresh()
    assert "research_views" in first
    home = Path(first["research_views"]["home"])
    edited = home.read_text().replace("# Atlas research", "# My edited research", 1)
    home.write_text(edited)
    receipt = inbox.record(draft, "test-session")
    assert receipt["recorded"] is True
    assert receipt["publication_status"] == "current"
    assert receipt["research_views"]["status"] == "pending"
    assert "edited" in str(receipt["research_views"]["errors"])
    assert home.read_text() == edited
    assert any("A scoped finding" in path.read_text() for path in (project / "Research/Records").glob("*.md"))
    assert len(list((project / ".atlas/drafts").glob("*.json"))) == 1


def test_research_folder_symlink_does_not_write_elsewhere_or_prevent_capture(project, draft):
    elsewhere = project / "personal"
    elsewhere.mkdir()
    (project / "Research").symlink_to(elsewhere, target_is_directory=True)
    receipt = ResearchInbox(project).record(draft, "test-session")
    assert receipt.get("research_views", {}).get("status") == "pending"
    assert receipt["recorded"] is True
    assert receipt["publication_status"] == "current"
    assert list(elsewhere.iterdir()) == []


def test_edited_canvas_is_preserved_as_a_copy_while_live_map_keeps_updating(project, draft):
    inbox = ResearchInbox(project)
    first = inbox.refresh()
    assert "research_views" in first
    path = Path(first["research_views"]["canvas"])
    canvas = json.loads(path.read_text())
    canvas["nodes"][0]["x"] += 25
    path.write_text(json.dumps(canvas))
    before = path.read_bytes()
    receipt = inbox.record(draft, "test-session")
    assert receipt["research_views"]["status"] == "current"
    copies = list((project / "Research/Preserved edits").glob("*.canvas"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == before
    assert "A scoped finding" in path.read_text()
    assert copies[0].name in Path(receipt["research_views"]["home"]).read_text()
    assert receipt["recorded"] is True
    assert inbox.refresh()["research_views"]["status"] == "current"
    assert list((project / "Research/Preserved edits").glob("*.canvas")) == copies


def test_canvas_backup_failure_keeps_the_edited_original(project, monkeypatch):
    from workbench import research_views

    inbox = ResearchInbox(project)
    path = Path(inbox.refresh()["research_views"]["canvas"])
    canvas = json.loads(path.read_text())
    canvas["nodes"][0]["x"] += 25
    path.write_text(json.dumps(canvas))
    before = path.read_bytes()
    original = research_views._replace

    def no_backup(destination, *args):
        if destination.parent.name == "Preserved edits":
            raise OSError("Backup disk unavailable")
        return original(destination, *args)

    monkeypatch.setattr(research_views, "_replace", no_backup)
    result = inbox.refresh()["research_views"]
    assert result["status"] == "pending"
    assert "Backup disk unavailable" in str(result["errors"])
    assert path.read_bytes() == before


def test_canvas_backup_must_be_durable_before_replacing_original(project, monkeypatch):
    from workbench import automation

    inbox = ResearchInbox(project)
    path = Path(inbox.refresh()["research_views"]["canvas"])
    canvas = json.loads(path.read_text())
    canvas["nodes"][0]["x"] += 25
    path.write_text(json.dumps(canvas))
    before = path.read_bytes()
    original = automation._sync_directory

    def fail_sync(directory):
        if directory.name == "Preserved edits":
            raise OSError("Backup directory sync failed")
        return original(directory)

    monkeypatch.setattr(automation, "_sync_directory", fail_sync)
    result = inbox.refresh()["research_views"]
    assert result["status"] == "pending"
    assert "Backup directory sync failed" in str(result["errors"])
    assert path.read_bytes() == before


def test_foreign_canvas_is_never_replaced_or_adopted(project):
    inbox = ResearchInbox(project)
    path = Path(inbox.refresh()["research_views"]["canvas"])
    content = json.dumps({"nodes": [{"id": "mine", "text": "My personal canvas"}], "edges": []})
    path.write_text(content)
    assert inbox.refresh()["research_views"]["status"] == "pending"
    assert path.read_text() == content


@pytest.mark.parametrize("value", [None, "broken canvas", 7])
def test_non_object_canvas_keeps_saved_record_receipt_and_reports_view_error(project, draft, value):
    inbox = ResearchInbox(project)
    result = inbox.refresh()
    path = Path(result["research_views"]["canvas"])
    content = json.dumps(value)
    path.write_text(content)
    receipt = inbox.record(draft, "test-session")
    assert receipt["recorded"] is True
    assert receipt["publication_status"] == "current"
    assert receipt["research_views"]["status"] == "pending"
    assert path.read_text() == content
    assert len(list((project / ".atlas/drafts").glob("*.json"))) == 1


def test_invalid_saved_export_status_is_reported_without_breaking_inbox_status(project):
    inbox = ResearchInbox(project)
    inbox.refresh()
    (project / ".atlas/research/views.json").write_text("null")
    status = inbox.status()
    assert status["publication_status"] == "current"
    assert status["research_views"]["status"] == "pending"


def test_map_question_anchors_follow_active_view_membership_but_notes_retain_every_question(project):
    for path in (project / "workbench/data/lighthouses").glob("*.json"):
        config = json.loads(path.read_text())
        config["item_ids"] = [identifier for identifier in config["item_ids"] if identifier != "q-regulation"]
        path.write_text(json.dumps(config))
    result = ResearchInbox(project).refresh()["research_views"]
    assert result["status"] == "current"
    canvas = json.loads(Path(result["canvas"]).read_text())
    assert not any("Which gene-regulatory influences" in node["text"] for node in canvas["nodes"])
    assert "Which gene-regulatory influences" in Path(result["home"]).read_text()


def test_external_markdown_and_path_like_ids_cannot_inject_links_or_escape_export(project):
    bundle_path = project / "workbench/data/cell_fate.json"
    bundle = json.loads(bundle_path.read_text())
    source = bundle["sources"][0]
    previous = source["id"]
    source["id"] = "../../unrelated"
    source["title"] = "![[secret]] <script> [[forged]]"
    for record in bundle["items"] + bundle["relations"]:
        for entry in record["evidence"]:
            if entry["source_id"] == previous:
                entry["source_id"] = source["id"]
    bundle_path.write_text(json.dumps(bundle))
    result = ResearchInbox(project).refresh()
    assert result.get("research_views", {}).get("status") == "current"
    text = "\n".join(path.read_text() for path in (project / "Research").rglob("*.md"))
    assert "![[secret]]" not in text
    assert "[[forged]]" not in text
    assert "<script>" not in text
    assert not (project / "unrelated.md").exists()


def test_removed_record_remains_explicitly_archived_without_losing_personal_notes(project):
    inbox = ResearchInbox(project)
    first = inbox.refresh()
    home = Path(first["research_views"]["home"])
    paths = list((project / "Research/Records").glob("*.md"))
    path = next(path for path in paths if "Record ID: a-dynamics" in path.read_text())
    with path.open("a") as stream:
        stream.write("\nPersonal annotation to retain.\n")
    source = project / "workbench/data/cell_fate.json"
    bundle = json.loads(source.read_text())
    bundle["items"] = [item for item in bundle["items"] if item["id"] != "a-dynamics"]
    bundle["relations"] = [r for r in bundle["relations"] if "a-dynamics" not in (r["subject"], r["object"])]
    source.write_text(json.dumps(bundle))
    for config_path in (project / "workbench/data/lighthouses").glob("*.json"):
        config = json.loads(config_path.read_text())
        config["item_ids"] = [identifier for identifier in config["item_ids"] if identifier != "a-dynamics"]
        config_path.write_text(json.dumps(config))
    result = inbox.refresh()["research_views"]
    assert result["status"] == "current"
    assert "no longer in the current Atlas snapshot" in path.read_text()
    assert "Personal annotation to retain." in path.read_text()
    assert "Retired exports" in home.read_text()


@pytest.mark.parametrize("obsidian", [False, True])
def test_open_command_refreshes_current_data_and_selects_requested_view(project, monkeypatch, capsys, obsidian):
    from workbench.automation import main
    import webbrowser
    from urllib.parse import parse_qs, unquote, urlsplit
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    args = ["--project", str(project), "open"] + (["--obsidian"] if obsidian else [])
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["research_views"]["status"] == "current"
    assert len(opened) == 1
    url = urlsplit(opened[0])
    if obsidian:
        assert url.scheme == "obsidian"
        assert Path(parse_qs(url.query)["path"][0]).is_file()
    else:
        assert url.scheme == "file"
        assert "Cell fate" in Path(unquote(url.path)).read_text()
