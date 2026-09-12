"""Readable graph names must survive migration, collisions, and future refreshes."""

import copy
import json
from pathlib import Path
import re
import shutil

import pytest

from workbench.automation import ResearchInbox
from workbench.research_views import _name, _note, export_research


@pytest.fixture
def project(tmp_path):
    shutil.copytree(Path(__file__).resolve().parents[2] / "workbench/data", tmp_path / "workbench/data")
    (tmp_path / ".atlas").mkdir()
    return tmp_path


def test_graph_names_and_colors_are_human_and_preferences_survive_refresh(project):
    snapshot = ResearchInbox(project).snapshot()
    result = export_research(project, snapshot, "test")
    assert result["status"] == "current", result["errors"]
    notes = list((project / "Research/Records").glob("*.md"))
    assert any(path.name.startswith("Question - How well") for path in notes)
    assert not any(re.search(r"[0-9a-f]{12}", path.name) for path in notes)
    for path in notes:
        assert "#atlas/" in path.read_text()
        assert "> [!info]- Technical details" in path.read_text()
    graph_path = project / ".obsidian/graph.json"
    graph = json.loads(graph_path.read_text())
    assert 'path:"Research/Records"' in graph["search"]
    assert len(graph["colorGroups"]) == 4
    graph["search"] = "my custom query"
    graph_path.write_text(json.dumps(graph))
    assert export_research(project, snapshot, "test")["status"] == "current"
    assert json.loads(graph_path.read_text())["search"] == "my custom query"


def test_migration_preserves_annotations_and_repairs_wikilinks_markdown_and_workspace(project):
    snapshot = ResearchInbox(project).snapshot()
    item = snapshot["bundle"]["items"][0]
    directory = project / "Research/Records"
    directory.mkdir(parents=True)
    old = directory / _name("r", item["id"])
    _note(old, "# Old generated note")
    with old.open("a") as stream:
        stream.write(f"\nMy annotation with [[{old.stem}#Evidence|its evidence]].\n")
    personal = project / "My notes.md"
    personal.write_text(f"See [[{old.stem}]] and [[Research/Records/{old.stem}|my label]].\n"
                        f"[Evidence](Research/Records/{old.name}#Evidence)\nLiteral ID: {old.stem}\n")
    (project / ".obsidian").mkdir()
    workspace = project / ".obsidian/workspace.json"
    workspace.write_text(json.dumps({"main": {"file": str(old.relative_to(project))}, "custom": 42}))
    result = export_research(project, snapshot, "test")
    assert result["status"] == "current", result["errors"]
    assert not old.exists()
    new = next(path for path in directory.glob("*.md") if f"Record ID: {item['id']}" in path.read_text())
    assert "My annotation" in new.read_text()
    assert f"[[{new.stem}#Evidence|its evidence]]" in new.read_text()
    assert f"[[{new.stem}]]" in personal.read_text()
    assert f"[[Research/Records/{new.stem}|my label]]" in personal.read_text()
    assert f"{new.name.replace(' ', '%20')}#Evidence" in personal.read_text()
    assert f"Literal ID: {old.stem}" in personal.read_text()
    assert json.loads(workspace.read_text()) == {"main": {"file": str(new.relative_to(project))}, "custom": 42}
    assert list((project / ".atlas/research/obsidian-backups").rglob("My notes.md"))


def test_duplicate_titles_keep_assigned_names_and_do_not_clobber_personal_files(project):
    snapshot = ResearchInbox(project).snapshot()
    item = snapshot["bundle"]["items"][0]
    item["title"] = "Same title"
    folder = project / "Research/Records"
    folder.mkdir(parents=True)
    personal = folder / "Method - Same title.md"
    personal.write_text("My own note")
    assert export_research(project, snapshot, "test")["status"] == "current"
    first = next(path for path in folder.glob("*.md") if f"Record ID: {item['id']}" in path.read_text())
    duplicate = copy.deepcopy(item)
    duplicate["id"] = "a-new-duplicate"
    snapshot["bundle"]["items"].append(duplicate)
    assert export_research(project, snapshot, "test")["status"] == "current"
    assert first.exists()
    assert personal.read_text() == "My own note"
    same = [path for path in folder.glob("*.md") if "Same title" in path.name]
    assert len(same) == 3
    assert len({path.stem.casefold() for path in same}) == 3


def test_edited_legacy_generated_text_is_not_destroyed(project):
    snapshot = ResearchInbox(project).snapshot()
    item = snapshot["bundle"]["items"][0]
    old = project / "Research/Records" / _name("r", item["id"])
    old.parent.mkdir(parents=True)
    _note(old, "# Original")
    content = old.read_text().replace("Original", "User edit")
    old.write_text(content)
    result = export_research(project, snapshot, "test")
    assert result["status"] == "pending"
    assert old.read_text() == content


def test_preflight_conflict_does_not_partially_rename_a_batch(project):
    snapshot = ResearchInbox(project).snapshot()
    first, second = sorted(snapshot["bundle"]["items"], key=lambda item: item["id"])[:2]
    folder = project / "Research/Records"
    folder.mkdir(parents=True)
    old = folder / _name("r", first["id"])
    conflict = folder / _name("r", second["id"])
    _note(old, "# Original")
    _note(conflict, "# Original")
    conflict.write_text(conflict.read_text().replace("Original", "User edit"))
    assert export_research(project, snapshot, "test")["status"] == "pending"
    assert old.is_file()


def test_already_archived_legacy_note_is_excluded_from_default_graph(project):
    folder = project / "Research/Records"
    folder.mkdir(parents=True)
    old = folder / _name("r", "deleted-record")
    _note(old, "# Archived Atlas export\n\n#atlas-archived\n\nOld evidence")
    assert export_research(project, ResearchInbox(project).snapshot(), "test")["status"] == "current"
    assert "#atlas/archived" in old.read_text()


def test_migration_repairs_relative_links_but_leaves_code_examples_unchanged(project):
    snapshot = ResearchInbox(project).snapshot()
    item = snapshot["bundle"]["items"][0]
    old = project / "Research/Records" / _name("r", item["id"])
    old.parent.mkdir(parents=True)
    _note(old, "# Original")
    personal = project / "Research/Sources/My reading notes.md"
    personal.parent.mkdir()
    code = f"`[[{old.stem}]]`\n\n```markdown\n[[{old.stem}]]\n```\n> ~~~markdown\n> [[{old.stem}]]\n> ~~~\n"
    personal.write_text(f'[Evidence](../Records/{old.name}#Evidence "Paper evidence")\n'
                        f'[Reference][ref]\n\n[ref]: ../Records/{old.name} "My reference"\n' + code)
    result = export_research(project, snapshot, "test")
    assert result["status"] == "current", result["errors"]
    new = next(path for path in old.parent.glob("*.md") if f"Record ID: {item['id']}" in path.read_text())
    assert f"../Records/{new.name.replace(' ', '%20')}#Evidence" in personal.read_text()
    assert f'[ref]: ../Records/{new.name.replace(" ", "%20")} "My reference"' in personal.read_text()
    assert code in personal.read_text()


def test_migration_can_resume_after_link_backup_failure(project, monkeypatch):
    from workbench import research_obsidian
    snapshot = ResearchInbox(project).snapshot()
    item = snapshot["bundle"]["items"][0]
    old = project / "Research/Records" / _name("r", item["id"])
    old.parent.mkdir(parents=True)
    _note(old, "# Original")
    personal = project / "My notes.md"
    previous = f"[[{old.stem}]]"
    personal.write_text(previous)
    original = research_obsidian._backup

    def fail_backup(root, path, content):
        if path == personal:
            raise OSError("Disk unavailable")
        original(root, path, content)

    monkeypatch.setattr(research_obsidian, "_backup", fail_backup)
    assert export_research(project, snapshot, "test")["status"] == "pending"
    assert personal.read_text() == previous
    monkeypatch.setattr(research_obsidian, "_backup", original)
    assert export_research(project, snapshot, "test")["status"] == "current"
    assert personal.read_text() != previous


def test_migration_never_repairs_settings_through_a_directory_symlink(project, tmp_path_factory):
    snapshot = ResearchInbox(project).snapshot()
    item = snapshot["bundle"]["items"][0]
    old = project / "Research/Records" / _name("r", item["id"])
    old.parent.mkdir(parents=True)
    _note(old, "# Original")
    elsewhere = tmp_path_factory.mktemp("other-vault-settings")
    workspace = elsewhere / "workspace.json"
    previous = json.dumps({"file": str(old.relative_to(project))})
    workspace.write_text(previous)
    (project / ".obsidian").symlink_to(elsewhere, target_is_directory=True)
    assert export_research(project, snapshot, "test")["status"] == "pending"
    assert workspace.read_text() == previous


def test_unicode_and_case_collisions_produce_safe_stable_filenames(project):
    snapshot = ResearchInbox(project).snapshot()
    original = snapshot["bundle"]["items"][0]
    for number, title in enumerate(("Café / β-cells [1]", "CAFÉ \\ β-cells [1]", "細胞" * 90)):
        item = copy.deepcopy(original)
        item.update(id=f"unicode-{number}", title=title)
        snapshot["bundle"]["items"].append(item)
    assert export_research(project, snapshot, "test")["status"] == "current"
    notes = list((project / "Research/Records").glob("*.md"))
    assert len(notes) == len(snapshot["bundle"]["items"])
    assert len({p.stem.casefold() for p in notes}) == len(notes)
    assert all(len(p.name.encode()) <= 165 for p in notes)
    assert all(not re.search(r'[\\/:*?"<>|#\[\]^]', p.name) for p in notes)


def test_edited_canvas_retains_exact_original_and_gets_a_linked_companion(project):
    from workbench.research_views import _canvas
    snapshot = ResearchInbox(project).snapshot()
    item = snapshot["bundle"]["items"][0]
    old = project / "Research/Records" / _name("r", item["id"])
    old.parent.mkdir(parents=True)
    _note(old, "# Original")
    canvas_path = project / "Research/Atlas Map.canvas"
    canvas = {"nodes": [{"id": "personal", "type": "text", "x": 100, "y": 100,
                         "text": f"[[{old.stem}]]"}], "edges": []}
    _canvas(canvas_path, canvas)
    edited = json.loads(canvas_path.read_text())
    edited["nodes"][0]["x"] = 777
    original = json.dumps(edited)
    canvas_path.write_text(original)
    result = export_research(project, snapshot, "test")
    assert result["status"] == "current", result["errors"]
    preserved = project / "Research/Preserved edits"
    assert next(preserved.glob("Atlas Map-edited-*.canvas")).read_text() == original
    linked = json.loads((preserved / "Your research map.canvas").read_text())
    assert linked["nodes"][0]["x"] == 777
    assert old.stem not in linked["nodes"][0]["text"]
    assert "Your research map.canvas" in (project / "Research/Start Here.md").read_text()
