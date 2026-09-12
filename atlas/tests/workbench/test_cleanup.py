import hashlib
import json

import pytest

from workbench import Store, WorkbenchError
from workbench.cleanup import clean_vault, write_cleanup


def note(vault, name, node_id, summary, dependencies="", layer="math", domain="dynamical-systems"):
    path = vault / "Nodes" / layer / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {node_id}\nlayer: {layer}\ndomain: {domain}\n---\n"
        f"# {name}\n\n## Summary\n\n{summary}\n\n## Dependencies\n\n{dependencies}\n",
        encoding="utf-8",
    )
    return path


def decisions(vault, merges=None):
    manifest = {p.relative_to(vault).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((vault / "Nodes").rglob("*.md"))}
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1, "source_manifest_sha256": digest,
        "layer_facets": {"math": {"discipline": ["mathematics"]}},
        "domain_facets": {"dynamical-systems": {"method": ["dynamical-systems"]}},
        "merges": merges or [], "annotations": [], "keep_separate": [],
    }


def test_explicit_merge_preserves_accounts_redirects_edges_and_deduplicates_observations(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "original", "a", "First formulation.", "### Enables\n- [[target]]\n")
    note(vault, "duplicate", "b", "Second formulation with extra scope.", "### Enables\n- [[target]]\n")
    note(vault, "target", "c", "Separate question.", "### Enabled By\n- [[duplicate]]\n")
    config = decisions(vault, [{"canonical": "legacy:a", "aliases": ["legacy:b"],
                               "title": "Combined question", "rationale": "Same task; retain both descriptions."}])
    before = {p: p.read_bytes() for p in vault.rglob("*.md")}

    bundle, audit = clean_vault(vault, config)

    assert before == {p: p.read_bytes() for p in vault.rglob("*.md")}
    assert [r["id"] for r in bundle["items"]] == ["legacy:a", "legacy:c"]
    combined = bundle["items"][0]
    assert "First formulation." in combined["summary"]
    assert "Second formulation with extra scope." in combined["summary"]
    assert combined["facets"] == {"discipline": ["mathematics"], "method": ["dynamical-systems"]}
    assert combined["provenance"]["legacy_layer"] == "math"
    assert audit["aliases"] == {"legacy:b": "legacy:a"}
    assert len(audit["original_items"]) == 3
    assert len(bundle["relations"]) == 1
    edge = bundle["relations"][0]
    assert (edge["subject"], edge["predicate"], edge["object"]) == ("legacy:a", "enables", "legacy:c")
    assert len(audit["relation_observations"][edge["id"]]) == 3
    with Store(tmp_path / "clean.db", create=True) as store:
        assert store.import_bundle(bundle) == {"items": 2, "sources": 0, "relations": 1}
        assert store.unlocks("legacy:a") == []
        assert store.duplicates() == []
    assert all(r["status"] == "proposed" for r in bundle["items"] + bundle["relations"])
    assert clean_vault(vault, config) == (bundle, audit)


def test_requires_direction_and_withheld_links_are_auditable(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "first", "a", "First.", "### Requires\n- [[second]]\n- [[missing]]\n- [[first]]\n\n## Other\n- [[ignored]]\n")
    note(vault, "second", "b", "Second.", "### Enabled By\n- [[first]]\n")
    bundle, audit = clean_vault(vault, decisions(vault))
    edges = {(e["subject"], e["predicate"], e["object"]) for e in bundle["relations"]}
    assert edges == {("legacy:a", "requires", "legacy:b"), ("legacy:a", "enables", "legacy:b")}
    assert {r["reason"] for r in audit["withheld_links"]} == {"missing_target", "self_dependency"}
    assert audit["counts"]["link_observations"] == 4
    assert len(audit["opposed_dependency_pairs"]) == 1


def test_similar_titles_and_shared_methods_do_not_trigger_implicit_merges(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Causal inference", "a", "General inference.")
    note(vault, "Causal-inference", "b", "Inference in aging.")
    bundle, audit = clean_vault(vault, decisions(vault))
    assert len(bundle["items"]) == 2
    assert audit["aliases"] == {}


def test_ambiguous_and_merge_created_self_links_are_withheld(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "same", "a", "A.", "### Enables\n- [[same]]\n- [[alias]]\n")
    note(vault, "same", "b", "B.", layer="physics")
    note(vault, "alias", "c", "C.")
    config = decisions(vault, [{"canonical": "legacy:a", "aliases": ["legacy:c"],
                               "title": "A", "rationale": "Duplicate task."}])
    config["layer_facets"]["physics"] = {"discipline": ["physics"]}
    bundle, audit = clean_vault(vault, config)
    assert bundle["relations"] == []
    assert {r["reason"] for r in audit["withheld_links"]} == {"ambiguous_target", "self_dependency"}


def test_source_drift_unknown_categories_and_bad_merge_decisions_fail_closed(tmp_path):
    vault = tmp_path / "vault"
    source = note(vault, "first", "a", "First.")
    config = decisions(vault)
    source.write_text(source.read_text() + "Changed after review.\n")
    with pytest.raises(WorkbenchError, match="manifest"):
        clean_vault(vault, config)
    config = decisions(vault)
    config["layer_facets"] = {}
    with pytest.raises(WorkbenchError, match="unmapped"):
        clean_vault(vault, config)
    config = decisions(vault, [{"canonical": "legacy:a", "aliases": ["legacy:missing"],
                               "title": "A", "rationale": "Missing record."}])
    with pytest.raises(WorkbenchError, match="merge"):
        clean_vault(vault, config)


@pytest.mark.parametrize("invalid_facets", [
    {"discipline": "mathematics"}, {"discipline": [" "]},
    {"discipline": None}, {"": ["mathematics"]},
])
def test_malformed_facet_decisions_do_not_silently_change_classification(tmp_path, invalid_facets):
    vault = tmp_path / "vault"
    note(vault, "first", "a", "First.")
    config = decisions(vault)
    config["layer_facets"]["math"] = invalid_facets
    with pytest.raises(WorkbenchError, match="facet"):
        clean_vault(vault, config)


def test_publication_requires_new_directory_and_keeps_source_vault_read_only(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "first", "a", "First.")
    config = decisions(vault)
    with pytest.raises(WorkbenchError, match="inside.*vault"):
        write_cleanup(vault, config, vault / "generated")
    output = tmp_path / "cleaned"
    write_cleanup(vault, config, output)
    assert json.loads((output / "graph.json").read_text())["items"][0]["id"] == "legacy:a"
    assert "First." in (output / "index.html").read_text()
    assert (output / "audit.json").is_file()
    with pytest.raises(WorkbenchError, match="exists"):
        write_cleanup(vault, config, output)
    source = next(vault.rglob("*.md"))
    source.write_text(source.read_text() + "Changed.\n")
    with pytest.raises(WorkbenchError, match="manifest"):
        write_cleanup(vault, config, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
