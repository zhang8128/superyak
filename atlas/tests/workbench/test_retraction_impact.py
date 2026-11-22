"""Issue #9's smallest slice: what a source's retraction does to what depends on it, read-only, in Atlas's store."""
import pytest

from workbench import Store, WorkbenchError


def source(source_id):
    return {"id": source_id, "title": f"Paper {source_id}", "url": f"https://example.org/{source_id}", "year": 2024,
            "citation": f"Author ({source_id})"}


def cites(*source_ids):
    return [{"source_id": s, "locator": f"Fig. {i + 1}", "note": "result"} for i, s in enumerate(source_ids)]


def claim(record_id, *source_ids, kind="claim", **changes):
    record = {"id": record_id, "kind": kind, "title": f"Title {record_id}", "summary": f"Summary {record_id}"}
    if source_ids:
        record["evidence"] = cites(*source_ids)
    record.update(changes)
    return record


def relation(record_id, subject, predicate, object_id, *source_ids, status="reviewed"):
    return {"id": record_id, "subject": subject, "predicate": predicate, "object": object_id, "status": status,
            "rationale": "Scoped inference", "context": {"system": "test"}, "evidence": cites(*source_ids),
            "reviewed_by": "Reviewer" if status == "reviewed" else "",
            "reviewed_at": "2026-09-07T12:00:00Z" if status == "reviewed" else ""}


def store_with(tmp_path, sources, items, relations):
    store = Store(tmp_path / "w.db", create=True)
    store.import_bundle({"schema_version": 1, "title": "T", "sources": [source(s) for s in sources],
                         "items": items, "relations": relations})
    return store


def verdicts(report):
    return {entry["id"]: entry["verdict"] for entry in report["items"]}


def chain(tmp_path, b_sources):
    """The issue's case: paper A -> claim B -> hypothesis C -> decision D, inferences backed by paper S."""
    return store_with(tmp_path, ["A", "E", "S"],
                      [claim("B", *b_sources), claim("C"), claim("D", kind="approach")],
                      [relation("B-C", "B", "supports", "C", "S"), relation("C-D", "C", "supports", "D", "S")])


def test_an_independent_source_keeps_the_chain_supported(tmp_path):
    with chain(tmp_path, ["A", "E"]) as store:
        report = store.retraction_impact("A")
        assert verdicts(report) == {"B": "still supported", "C": "still supported", "D": "still supported"}
        assert [e["path"] for e in report["items"]] == [["A", "B"], ["A", "B", "C"], ["A", "B", "C", "D"]]
        assert report["retracted"] == ["A"]


def test_without_it_the_whole_chain_loses_its_support(tmp_path):
    with chain(tmp_path, ["A"]) as store:
        assert verdicts(store.retraction_impact("A")) == {"B": "unsupported", "C": "unsupported", "D": "unsupported"}


def test_support_further_down_holds_what_is_below_it(tmp_path):
    items = [claim("B", "A"), claim("C", "F"), claim("D", kind="approach")]
    rels = [relation("B-C", "B", "supports", "C", "S"), relation("C-D", "C", "supports", "D", "S")]
    with store_with(tmp_path, ["A", "F", "S"], items, rels) as store:
        assert verdicts(store.retraction_impact("A")) == {"B": "unsupported", "C": "still supported",
                                                           "D": "still supported"}


def test_many_citations_of_one_source_count_once_and_a_cycle_does_not_keep_itself_alive(tmp_path):
    items = [claim("B", "A", "A"), claim("B2", "A"), claim("C")]
    rels = [relation("B-C", "B", "supports", "C", "S"), relation("C-B", "C", "supports", "B", "S"),
            relation("B2-C", "B2", "supports", "C", "S")]
    with store_with(tmp_path, ["A", "S"], items, rels) as store:
        report = store.retraction_impact("A")
        assert verdicts(report) == {"B": "unsupported", "B2": "unsupported", "C": "unsupported"}
        assert len(report["items"]) == 3                       # each item once, however many routes reach it


def test_a_relation_backed_only_by_the_retracted_source_stops_carrying_support(tmp_path):
    items = [claim("B", "E"), claim("C")]
    with store_with(tmp_path, ["A", "E"], items, [relation("B-C", "B", "supports", "C", "A")]) as store:
        assert verdicts(store.retraction_impact("A")) == {"C": "unsupported"}


def test_withdrawn_records_carry_nothing_and_a_challenge_can_be_lost(tmp_path):
    items = [claim("B", "A"), claim("C", "F"), claim("G", "A"), claim("H")]
    rels = [relation("B-H", "B", "supports", "H", "S", status="withdrawn"),
            relation("G-C", "G", "challenges", "C", "S")]
    with store_with(tmp_path, ["A", "F", "S"], items, rels) as store:
        got = verdicts(store.retraction_impact("A"))
        assert got == {"B": "unsupported", "G": "unsupported", "C": "challenge lost"}   # H isn't reached


def test_a_lost_challenge_reaches_an_unsourced_target_and_an_unsourced_supporter_holds_nothing_up(tmp_path):
    items = [claim("B", "A"), claim("C")]
    rels = [relation("B-C", "B", "challenges", "C", "S")]
    with store_with(tmp_path, ["A", "S"], items, rels) as store:
        assert verdicts(store.retraction_impact("A"))["C"] == "challenge lost"
    items2 = [claim("B", "A"), claim("C"), claim("X")]
    rels2 = [relation("B-C", "B", "supports", "C", "S"), relation("X-C", "X", "supports", "C", "S")]
    (tmp_path / "2").mkdir()
    with store_with(tmp_path / "2", ["A", "S"], items2, rels2) as store:
        assert verdicts(store.retraction_impact("A")) == {"B": "unsupported", "C": "unsupported"}


def test_it_is_read_only_and_idempotent(tmp_path):
    with chain(tmp_path, ["A", "E"]) as store:
        before = store.export_bundle()
        first = store.retraction_impact("A")
        assert store.retraction_impact(["A", "A"]) == first
        assert store.export_bundle() == before


def test_unknown_or_missing_sources_are_refused(tmp_path):
    with chain(tmp_path, ["A", "E"]) as store:
        for bad in ("nope", [], ["A", "nope"], 7):
            with pytest.raises(WorkbenchError):
                store.retraction_impact(bad)


def test_what_was_believed_at_a_time(tmp_path):
    with chain(tmp_path, ["A", "E"]) as store:
        assert store.history_as_of("B", "2000-01-01T00:00:00Z") == {"id": "B", "status": "proposed", "events": []}
        store.set_status("B", "reviewed", "checked against E", "Reviewer")
        store.set_status("B", "withdrawn", "A retracted", "Reviewer")
        events = store.export_bundle()["history"]
        first, second = events[-2]["timestamp"], events[-1]["timestamp"]
        assert store.history_as_of("B", "2000-01-01T00:00:00Z")["status"] == "proposed"
        at_first = store.history_as_of("B", first)
        assert at_first["status"] in {"reviewed", "withdrawn"} and at_first["events"][0]["reason"] == "checked against E"
        assert store.history_as_of("B", second)["status"] == "withdrawn"
        assert [e["to_status"] for e in store.history_as_of("B", second)["events"]] == ["reviewed", "withdrawn"]
        with pytest.raises(WorkbenchError):
            store.history_as_of("nope", second)
        with pytest.raises(WorkbenchError):
            store.history_as_of("B", "yesterday")


def test_a_withdrawn_item_is_neither_reported_nor_holds_anything_up(tmp_path):
    items = [claim("B", "A", status="withdrawn"), claim("W", "E", status="withdrawn"), claim("C", "A")]
    rels = [relation("W-C", "W", "supports", "C", "S", status="proposed")]
    with store_with(tmp_path, ["A", "E", "S"], items, rels) as store:
        assert verdicts(store.retraction_impact("A")) == {"C": "unsupported"}


def test_a_challenger_that_keeps_its_grounding_loses_no_challenge(tmp_path):
    items = [claim("G", "A", "E"), claim("C", "F")]
    with store_with(tmp_path, ["A", "E", "F", "S"], items, [relation("G-C", "G", "challenges", "C", "S")]) as store:
        assert verdicts(store.retraction_impact("A")) == {"G": "still supported", "C": "still supported"}
