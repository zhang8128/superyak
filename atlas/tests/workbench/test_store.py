import json
import sqlite3

import pytest

from workbench import Store, WorkbenchError


SOURCE = {
    "id": "paper:1",
    "title": "A primary paper",
    "url": "https://example.org/paper",
    "year": 2024,
    "citation": "Researcher et al. (2024)",
}


def bundle(*, sources=None, items=None, relations=None, title="Test"):
    return {
        "schema_version": 1,
        "title": title,
        "sources": [] if sources is None else sources,
        "items": [] if items is None else items,
        "relations": [] if relations is None else relations,
    }


def item(record_id, kind="question", **changes):
    record = {
        "id": record_id,
        "kind": kind,
        "title": f"Title {record_id}",
        "summary": f"Summary {record_id}",
    }
    record.update(changes)
    return record


def evidence():
    return [{"source_id": "paper:1", "locator": "Fig. 1", "note": "Scoped result"}]


def reviewed_relation(record_id, subject, predicate, object_id, **changes):
    record = {
        "id": record_id,
        "subject": subject,
        "predicate": predicate,
        "object": object_id,
        "status": "reviewed",
        "rationale": "Scoped prerequisite",
        "context": {"system": "test"},
        "evidence": evidence(),
        "reviewed_by": "Reviewer",
        "reviewed_at": "2026-09-07T12:00:00Z",
    }
    record.update(changes)
    return record


def test_multi_facet_record_keeps_one_identity(tmp_path):
    data = {
        "schema_version": 1,
        "title": "Test",
        "sources": [],
        "items": [
            {
                "id": "q",
                "kind": "question",
                "title": "Cell fate",
                "summary": "Predict fate",
                "facets": {
                    "subject": ["gene regulation"],
                    "scale": ["molecular", "cellular"],
                },
            }
        ],
        "relations": [],
    }
    with Store(tmp_path / "test.db", create=True) as store:
        assert store.import_bundle(data) == {"sources": 0, "items": 1, "relations": 0}
        assert [x["id"] for x in store.search(facets={"scale": "molecular"})] == ["q"]
        assert [x["id"] for x in store.search(facets={"scale": "cellular"})] == ["q"]
        assert len(store.export_bundle()["items"]) == 1


def test_import_is_idempotent_but_conflicting_ids_roll_back_atomically(tmp_path):
    original = bundle(sources=[SOURCE], items=[item("q")])
    with Store(tmp_path / "test.db", create=True) as store:
        assert store.import_bundle(original) == {"sources": 1, "items": 1, "relations": 0}
        assert store.import_bundle(original) == {"sources": 0, "items": 0, "relations": 0}

        conflicting = bundle(
            sources=[{**SOURCE, "citation": "Different citation"}, {**SOURCE, "id": "paper:2"}],
            items=[item("new")],
        )
        with pytest.raises(WorkbenchError, match="conflicting.*paper:1"):
            store.import_bundle(conflicting)

        exported = store.export_bundle()
        assert [source["id"] for source in exported["sources"]] == ["paper:1"]
        assert [record["id"] for record in exported["items"]] == ["q"]


def test_bad_or_dangling_evidence_rejects_every_record(tmp_path):
    invalid = bundle(
        sources=[SOURCE],
        items=[
            item("q"),
            item(
                "claim",
                "claim",
                status="source_reported",
                evidence=[{"source_id": "missing", "locator": "p. 4", "note": "Claim"}],
            ),
        ],
    )
    with Store(tmp_path / "test.db", create=True) as store:
        with pytest.raises(WorkbenchError, match="unknown source"):
            store.import_bundle(invalid)
        assert store.export_bundle()["sources"] == []
        assert store.export_bundle()["items"] == []


@pytest.mark.parametrize(
    "data, message",
    [
        ({**bundle(), "mystery": True}, "unknown field"),
        (bundle(sources=[{**SOURCE, "abstract": "not portable"}]), "unknown field"),
        (bundle(items=[{**item("q"), "score": 0.9}]), "unknown field"),
        (
            bundle(items=[item("q"), item("a", "approach")], relations=[{
                "id": "r", "subject": "q", "predicate": "addresses", "object": "a",
                "rationale": "wrong direction",
            }]),
            "endpoint types",
        ),
        (
            bundle(items=[item("q", status="reviewed", reviewed_by=" ", reviewed_at="2026-09-07")]),
            "reviewed_by",
        ),
    ],
)
def test_schema_and_semantic_validation_rejects_invalid_bundles(tmp_path, data, message):
    with Store(tmp_path / "test.db", create=True) as store:
        with pytest.raises(WorkbenchError, match=message):
            store.import_bundle(data)
        assert store.export_bundle()["items"] == []


def test_global_item_relation_ids_are_unique(tmp_path):
    data = bundle(
        items=[item("q"), item("a", "approach")],
        relations=[{
            "id": "q",
            "subject": "a",
            "predicate": "addresses",
            "object": "q",
            "rationale": "Candidate approach",
        }],
    )
    with Store(tmp_path / "test.db", create=True) as store:
        with pytest.raises(WorkbenchError, match="globally unique"):
            store.import_bundle(data)


def test_unrelated_and_missing_databases_are_refused_without_mutation(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(WorkbenchError, match="does not exist"):
        Store(missing)
    assert not missing.exists()

    unrelated = tmp_path / "other.db"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE valuable (value TEXT)")
        connection.execute("INSERT INTO valuable VALUES ('keep')")
    before = unrelated.read_bytes()

    with pytest.raises(WorkbenchError, match="not a workbench"):
        Store(unrelated, create=True)
    assert unrelated.read_bytes() == before
    with sqlite3.connect(unrelated) as connection:
        assert connection.execute("SELECT value FROM valuable").fetchone()[0] == "keep"


def test_duplicate_candidates_are_unicode_and_punctuation_normalized_across_facets(tmp_path):
    records = [
        item("a", title="Gene–regulation!", facets={"scale": ["molecular"]}),
        item("b", title="Ｇｅｎｅ regulation", facets={"domain": ["development"]}),
        item("c", title="Different title"),
    ]
    with Store(tmp_path / "test.db", create=True) as store:
        store.import_bundle(bundle(items=records))
        assert [[record["id"] for record in group] for group in store.duplicates()] == [["a", "b"]]


def test_unlocks_uses_reviewed_active_dependencies_with_canonical_direction(tmp_path):
    records = [item("a"), item("b", "approach"), item("c", "experiment"), item("d"), item("e", status="withdrawn")]
    relations = [
        reviewed_relation("requires", "b", "requires", "a"),
        reviewed_relation("enables", "b", "enables", "c"),
        reviewed_relation("cycle", "c", "enables", "a"),
        {
            "id": "unreviewed",
            "subject": "a",
            "predicate": "enables",
            "object": "d",
            "status": "source_reported",
            "rationale": "Not adjudicated",
            "context": {"system": "test"},
        },
        reviewed_relation("withdrawn-endpoint", "c", "enables", "e"),
    ]
    with Store(tmp_path / "test.db", create=True) as store:
        store.import_bundle(bundle(sources=[SOURCE], items=records, relations=relations))
        assert [record["id"] for record in store.unlocks("a")] == ["b", "c"]
        assert store.unlocks("d") == []
        assert store.unlocks("e") == []


def test_failed_promotion_rolls_back_and_withdrawal_keeps_history(tmp_path):
    with Store(tmp_path / "test.db", create=True) as store:
        store.import_bundle(bundle(items=[item("c", "claim")]))

        with pytest.raises(WorkbenchError, match="evidence"):
            store.set_status("c", "reviewed", "Looks sound", "Dr Reviewer")
        assert store.get("c")["status"] == "proposed"
        assert store.export_bundle()["history"] == []

        store.set_status("c", "withdrawn", "Unsupported premise", "Dr Reviewer")
        assert store.get("c")["status"] == "withdrawn"
        history = store.export_bundle()["history"]
        assert len(history) == 1
        assert history[0]["record_id"] == "c"
        assert history[0]["from_status"] == "proposed"
        assert history[0]["to_status"] == "withdrawn"
        assert history[0]["reason"] == "Unsupported premise"
        assert history[0]["actor"] == "Dr Reviewer"
        assert history[0]["timestamp"].endswith("Z")

        with pytest.raises(WorkbenchError, match="withdrawn"):
            store.set_status("c", "proposed", "Try again", "Dr Reviewer")
        assert len(store.export_bundle()["history"]) == 1


def test_reviewed_dependency_requires_evidence_scope_and_rationale(tmp_path):
    with Store(tmp_path / "test.db", create=True) as store:
        store.import_bundle(bundle(items=[item("a"), item("b")], relations=[{
            "id": "r",
            "subject": "a",
            "predicate": "enables",
            "object": "b",
        }]))
        with pytest.raises(WorkbenchError, match="evidence"):
            store.set_status("r", "reviewed", "Reviewed", "Dr Reviewer")
        assert store.get("r")["status"] == "proposed"


def test_export_uses_complete_portable_defaults(tmp_path):
    with Store(tmp_path / "test.db", create=True) as store:
        store.import_bundle(bundle(items=[item("q")], title="Portable"))
        exported = store.export_bundle()
    assert exported["schema_version"] == 1
    assert exported["title"] == "Portable"
    assert set(exported) == {"schema_version", "title", "sources", "items", "relations", "history"}
    assert exported["items"] == [{
        "id": "q",
        "kind": "question",
        "title": "Title q",
        "summary": "Summary q",
        "status": "proposed",
        "context": {},
        "facets": {},
        "evidence": [],
        "provenance": {},
        "reviewed_by": "",
        "reviewed_at": "",
    }]


def test_search_intersects_facets_and_matches_title_or_summary(tmp_path):
    records = [
        item("q1", title="Cell fate map", facets={"scale": ["cellular"], "subject": ["regulation"]}),
        item("q2", summary="A fate comparison", facets={"scale": ["molecular"], "subject": ["regulation"]}),
        item("a", "approach", title="Cell fate method", facets={"scale": ["cellular"], "subject": ["regulation"]}),
    ]
    with Store(tmp_path / "test.db", create=True) as store:
        store.import_bundle(bundle(items=records))
        found = store.search("FATE", facets={"scale": "cellular", "subject": "regulation"}, kind="question")
        assert [record["id"] for record in found] == ["q1"]


def test_evidence_locator_must_not_be_blank(tmp_path):
    bad = item(
        "claim",
        "claim",
        status="source_reported",
        evidence=[{"source_id": "paper:1", "locator": " ", "note": "Scoped result"}],
    )
    with Store(tmp_path / "test.db", create=True) as store:
        with pytest.raises(WorkbenchError, match="locator"):
            store.import_bundle(bundle(sources=[SOURCE], items=[bad]))
        assert store.export_bundle()["sources"] == []
