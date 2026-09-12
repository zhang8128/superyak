import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PYTHON = sys.executable
ROOT = Path(__file__).parents[2]


def run_cli(*args):
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [PYTHON, "-m", "workbench", *map(str, args)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_init_import_search_show_review_and_export_emit_json(tmp_path):
    database = tmp_path / "test.db"
    source = {
        "id": "paper",
        "title": "Paper",
        "url": "https://example.org/paper",
        "year": 2025,
        "citation": "Researcher (2025)",
    }
    data = {
        "schema_version": 1,
        "title": "CLI Test",
        "sources": [source],
        "items": [{
            "id": "claim",
            "kind": "claim",
            "title": "A cell-fate claim",
            "summary": "Scoped summary",
            "facets": {"scale": ["cellular"]},
            "evidence": [{"source_id": "paper", "locator": "Fig. 2", "note": "Observation"}],
        }],
        "relations": [],
    }
    source_path = tmp_path / "bundle.json"
    source_path.write_text(json.dumps(data), encoding="utf-8")

    initialized = run_cli("--db", database, "init")
    assert initialized.returncode == 0, initialized.stderr
    assert json.loads(initialized.stdout)["initialized"] is True

    imported = run_cli("--db", database, "import", source_path)
    assert imported.returncode == 0, imported.stderr
    assert json.loads(imported.stdout) == {"sources": 1, "items": 1, "relations": 0}

    searched = run_cli("--db", database, "search", "fate", "--facet", "scale=cellular", "--kind", "claim")
    assert searched.returncode == 0, searched.stderr
    assert [record["id"] for record in json.loads(searched.stdout)] == ["claim"]

    shown = run_cli("--db", database, "show", "claim")
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["title"] == "A cell-fate claim"

    reviewed = run_cli(
        "--db", database, "review", "claim", "--status", "reviewed",
        "--reason", "Evidence checked", "--actor", "Dr Expert",
    )
    assert reviewed.returncode == 0, reviewed.stderr
    assert json.loads(reviewed.stdout)["status"] == "reviewed"

    exported = run_cli("--db", database, "export")
    assert exported.returncode == 0, exported.stderr
    payload = json.loads(exported.stdout)
    assert payload["items"][0]["reviewed_by"] == "Dr Expert"
    assert payload["history"][0]["reason"] == "Evidence checked"


@pytest.mark.parametrize(
    "command",
    [
        ("search", "anything"),
        ("show", "anything"),
        ("duplicates",),
        ("unlocks", "anything"),
        ("export",),
    ],
)
def test_cli_read_commands_do_not_create_a_missing_database(tmp_path, command):
    database = tmp_path / "missing.db"
    result = run_cli("--db", database, *command)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "does not exist" in result.stderr
    assert not database.exists()


def test_cli_invalid_import_is_nonzero_and_leaves_database_unchanged(tmp_path):
    database = tmp_path / "test.db"
    assert run_cli("--db", database, "init").returncode == 0
    before = json.loads(run_cli("--db", database, "export").stdout)
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({
        "schema_version": 1,
        "title": "Bad",
        "sources": [],
        "items": [{"id": "q", "kind": "question", "title": "Q", "summary": "S", "unknown": 1}],
        "relations": [],
    }), encoding="utf-8")

    result = run_cli("--db", database, "import", invalid)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "unknown field" in result.stderr
    assert json.loads(run_cli("--db", database, "export").stdout) == before


def test_cli_import_vault_and_duplicates_are_offline(tmp_path):
    database = tmp_path / "test.db"
    vault = tmp_path / "vault"
    note_dir = vault / "Nodes" / "molecular-bio"
    note_dir.mkdir(parents=True)
    (note_dir / "one.md").write_text(
        "---\nid: old.one\nlayer: molecular-bio\ndomain: fate\n---\n\n# Fate!\n\n## Summary\n\nFirst\n",
        encoding="utf-8",
    )
    (note_dir / "two.md").write_text(
        "---\nid: old.two\nlayer: molecular-bio\ndomain: fate\n---\n\n# Ｆａｔｅ\n\n## Summary\n\nSecond\n",
        encoding="utf-8",
    )
    assert run_cli("--db", database, "init").returncode == 0

    imported = run_cli("--db", database, "import-vault", vault)
    assert imported.returncode == 0, imported.stderr
    assert json.loads(imported.stdout)["items"] == 2
    duplicates = json.loads(run_cli("--db", database, "duplicates").stdout)
    assert [[record["id"] for record in group] for group in duplicates] == [["legacy:old.one", "legacy:old.two"]]


def test_cli_help_lists_render_without_importing_renderer():
    result = run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "render" in result.stdout


def test_cli_malformed_source_url_is_a_clean_validation_error(tmp_path):
    database = tmp_path / "test.db"
    assert run_cli("--db", database, "init").returncode == 0
    invalid = tmp_path / "bad-url.json"
    invalid.write_text(json.dumps({
        "schema_version": 1, "title": "Bad URL", "items": [], "relations": [],
        "sources": [{"id": "s", "title": "Paper", "url": "https://[bad", "year": 2024, "citation": "Citation"}],
    }))
    result = run_cli("--db", database, "import", invalid)
    assert result.returncode == 2
    assert "url" in result.stderr and "Traceback" not in result.stderr
    assert json.loads(run_cli("--db", database, "export").stdout)["sources"] == []
