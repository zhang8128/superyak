from collections import Counter
import json
from pathlib import Path

from workbench.render import render_bundle
from workbench.store import Store
from test_cli import run_cli


PILOT = Path(__file__).parents[2] / "workbench/data/cell_fate.json"


def test_pilot_has_scoped_primary_evidence_and_only_proposed_interpretations(tmp_path):
    assert PILOT.exists(), "The pilot corpus has not been implemented"
    data = json.loads(PILOT.read_text())
    with Store(tmp_path / "db", create=True) as store:
        counts = store.import_bundle(data)
        assert counts["sources"] >= 6
        assert store.import_bundle(data) == {"sources": 0, "items": 0, "relations": 0}
        exported = store.export_bundle()
        kinds = Counter(record["kind"] for record in exported["items"])
        assert kinds["question"] == 2
        assert kinds["approach"] >= 3 and kinds["claim"] >= 8 and kinds["experiment"] >= 2
        source_ids = set()
        for item in exported["items"]:
            assert not item["reviewed_by"] and not item["reviewed_at"]
            if item["kind"] == "claim":
                assert item["status"] == "source_reported"
                assert item["context"]["limitation"]
                assert item["context"]["system"]
                assert item["evidence"]
                for entry in item["evidence"]:
                    assert entry["locator"].strip()
                    source_ids.add(entry["source_id"])
            else:
                assert item["status"] == "proposed"
            if item["kind"] == "experiment":
                assert item["context"]["result_that_would_change_interpretation"]
            if item["kind"] == "question":
                assert {"molecular", "cellular"} <= set(item["facets"]["scale"])
                assert any(r["predicate"] == "addresses" and r["object"] == item["id"] for r in exported["relations"])
                assert store.unlocks(item["id"]) == []
        assert len(source_ids) >= 6
        assert all(r["status"] == "proposed" for r in exported["relations"])
        assert any(r["predicate"] == "challenges" and r["evidence"] for r in exported["relations"])
        question_ids = {x["id"] for x in store.search(kind="question", facets={"scale": "molecular"})}
        assert question_ids == {x["id"] for x in store.search(kind="question", facets={"scale": "cellular"})}


def test_pilot_full_cli_import_export_render_round_trip(tmp_path):
    assert PILOT.exists(), "The pilot corpus has not been implemented"
    db = tmp_path / "pilot.db"
    assert run_cli("--db", db, "init").returncode == 0
    imported = run_cli("--db", db, "import", PILOT)
    assert imported.returncode == 0, imported.stderr
    exported = json.loads(run_cli("--db", db, "export").stdout)
    output = tmp_path / "pilot.html"
    rendered = run_cli("--db", db, "render", "--output", output)
    assert rendered.returncode == 0, rendered.stderr
    assert output.read_text() == render_bundle(exported)
    with Store(tmp_path / "copy.db", create=True) as store:
        store.import_bundle(exported)
        assert store.export_bundle() == exported
