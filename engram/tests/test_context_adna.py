import hashlib
import json
import shlex

import pytest

from context_cli import build_parser, make_runtime
from context_compile import Budget, ContextCapacityError
from context_runtime import ContextRuntime
from context_store import ContextStore
from tests.test_context_runtime import RecordingProvider


def project(tmp_path, name="clinic", embedded=False):
    root = tmp_path / name
    content = root / (embedded if isinstance(embedded, str) else ".agentic") if embedded else root
    for leg in ("who", "what", "how"):
        (content / leg).mkdir(parents=True)
    (content / "MANIFEST.md").write_text("# Clinic\nA source of attributed research.\n")
    (content / "who" / "mira.md").write_text("---\nauthor: Mira\n---\nMira studies sleep and keeps uncertainty explicit.\n")
    (content / "what" / "sleep.md").write_text("# Sleep observation\nSleep improved on Tuesday. This is an observation, not a causal conclusion.\n")
    return root, content


def test_cli_adds_explicit_project_to_real_dispatched_context(tmp_path, monkeypatch):
    import context_codex

    root, content = project(tmp_path)
    provider = RecordingProvider()
    monkeypatch.setattr(context_codex, "CodexProvider", lambda **kw: provider)
    args = build_parser().parse_args(["--no-engram", "--adna-project", f"clinic={root}", "chat", "sleep"])
    store = ContextStore(tmp_path / "archive" / "context.db")
    runtime = make_runtime(args, store, tmp_path / "missing.db")
    before = (content / "what" / "sleep.md").read_bytes()
    try:
        runtime.chat("case", "What do the sleep observations establish?")
        supplied = json.dumps(provider.requests[-1])
        assert "Sleep improved on Tuesday" in supplied
        assert "not a causal conclusion" in supplied
        selected = store.manifest("case")["selected"]
        item = next(x for x in selected if x["id"] == "adna:clinic:what/sleep.md")
        assert item["version"] == hashlib.sha256(before).hexdigest()
        assert runtime.read_source("case", item["id"])["text"].startswith("# Sleep observation")
        assert (content / "what" / "sleep.md").read_bytes() == before
        assert not (root / ".engram").exists()
    finally:
        runtime.close()


@pytest.mark.parametrize("embedded", [False, ".agentic", ".adna"])
def test_source_handles_layout_and_preserves_origin_across_moves(tmp_path, embedded):
    from context_adna import AdnaSource

    root, content = project(tmp_path, embedded=embedded)
    source = AdnaSource(root, origin="clinic")
    item = next(c for c in source.search("sleep") if c.id.endswith("what/sleep.md"))
    account = json.loads(item.representations[0])
    assert account["path"] == "what/sleep.md"
    assert account["origin"] == "clinic"
    assert account["leg"] == "what"
    assert not item.required and item.role == "user"
    relocated = tmp_path / "relocated"
    root.rename(relocated)
    moved = AdnaSource(relocated, origin="clinic")
    assert any(c.id == item.id and c.version == item.version for c in moved.search("sleep"))
    assert moved.valid(item)
    assert not source.valid(item)
    other = AdnaSource(relocated, origin="another-peer")
    assert other.read(item.id) is None


def test_changed_deleted_and_replaced_sources_are_invalidated(tmp_path):
    from context_adna import AdnaSource

    root, content = project(tmp_path)
    source = AdnaSource(root, origin="clinic")
    item = next(c for c in source.search("sleep") if c.id.endswith("what/sleep.md"))
    file = content / "what" / "sleep.md"
    file.write_text("# Correction\nThe date was Wednesday.\n")
    assert not source.valid(item)
    file.unlink()
    assert source.read(item.id) is None
    old = tmp_path / "old"
    root.rename(old)
    project(tmp_path)
    assert source.search("sleep") == []


def test_only_declared_documents_are_read_and_symlinks_cannot_escape(tmp_path):
    from context_adna import AdnaSource

    root, content = project(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("sleep private outside material")
    (content / "what" / "linked.md").symlink_to(outside)
    (content / "what" / "linked-dir").symlink_to(tmp_path, target_is_directory=True)
    (content / "what" / ".private.md").write_text("sleep hidden material")
    (content / "what" / "credentials.json").write_text('{"secret":"sleep"}')
    (content / "unrelated.md").write_text("sleep unrelated root material")
    source = AdnaSource(root, origin="clinic")
    found = source.search("sleep", limit=32)
    assert {c.id for c in found} == {"adna:clinic:who/mira.md", "adna:clinic:what/sleep.md"}
    for suffix in ["../outside.md", "%2e%2e/outside.md", "/outside.md", "what/linked.md", "what/linked-dir/outside.md", "what/.private.md", "what/credentials.json", "unrelated.md"]:
        assert source.read("adna:clinic:" + suffix) is None
    candidate = next(c for c in found if c.id.endswith("what/sleep.md"))
    file = content / "what" / "sleep.md"
    file.unlink()
    file.symlink_to(outside)
    assert not source.valid(candidate)


def test_limits_and_pages_are_explicit(tmp_path):
    from context_adna import AdnaSource

    root, content = project(tmp_path)
    (content / "what" / "huge.md").write_text("sleep " * 12000)
    source = AdnaSource(root, origin="clinic", max_files=2)
    source.search("sleep")
    assert source.coverage["complete"] is False
    normal = AdnaSource(root, origin="clinic")
    assert not any(c.id.endswith("huge.md") for c in normal.search("sleep"))
    assert normal.coverage["skipped_files"] >= 1
    page = normal.read("adna:clinic:what/sleep.md", offset=2, limit=5)
    assert page["text"] == "Sleep"
    assert page["next_offset"] == 7
    with pytest.raises(ValueError):
        normal.read("adna:clinic:what/sleep.md", offset=-1)


def test_cli_inspect_search_and_read_need_no_provider(tmp_path, capsys):
    from adna_cli import main

    root, _ = project(tmp_path)
    assert main(["inspect", f"clinic={root}"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["origin"] == "clinic" and info["layout"] == "bare"
    assert main(["search", f"clinic={root}", "sleep"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "adna:clinic:what/sleep.md" in [r["id"] for r in result["results"]]
    assert main(["read", f"clinic={root}", "adna:clinic:what/sleep.md"]) == 0
    assert "Tuesday" in json.loads(capsys.readouterr().out)["text"]
    assert main(["read", f"clinic={root}", "adna:other:what/sleep.md"]) == 1
    capsys.readouterr()


def test_projects_are_explicit_and_duplicate_origins_rejected(tmp_path):
    from context_adna import parse_projects

    root, _ = project(tmp_path)
    for specs in [[str(root)], [f"bad:origin={root}"], [f"clinic={root}", f"clinic={root}"]]:
        with pytest.raises(ValueError):
            parse_projects(specs)
    with pytest.raises(ValueError):
        parse_projects([f"clinic={tmp_path / 'absent'}"])


def test_coding_resume_and_source_tools_keep_project_selection(tmp_path):
    from context_adna import AdnaSource
    from context_coding_cli import resume_command
    from context_coding_memory import CodingMemory

    root, _ = project(tmp_path)
    args = build_parser().parse_args(["--adna-project", f"clinic={root}", "--thread", "task", "code", "--repo", str(tmp_path), "inspect"])
    store = ContextStore(tmp_path / "archive" / "context.db")
    try:
        command = shlex.split(resume_command(args, store, tmp_path / "memory.db"))
        assert command[command.index("--adna-project") + 1] == f"clinic={root.resolve()}"
        memory = CodingMemory(store, (AdnaSource(root, origin="clinic"),))
        found = memory.call("task", "archive_search", {"query": "Tuesday"})
        assert any(r["id"] == "adna:clinic:what/sleep.md" for r in found["results"])
        row = memory.call("task", "archive_read", {"id": "adna:clinic:what/sleep.md"})
        assert "Tuesday" in row["text"]
    finally:
        store.close()


def test_chat_search_discovers_omitted_documents_and_tracks_tool_evidence(tmp_path):
    from context_adna import AdnaSource

    root, content = project(tmp_path)
    runtime = ContextRuntime(ContextStore(tmp_path / "context.db"), RecordingProvider(), Budget(),
                             sources=(AdnaSource(root, origin="clinic"),))
    try:
        for name, arguments in [("archive_search", {"query": "Tuesday"}),
                                ("archive_read", {"id": "adna:clinic:what/sleep.md"})]:
            snapshots = []
            result = runtime._tool("case", {"name": name, "arguments": json.dumps(arguments)}, snapshots=snapshots)
            assert "Tuesday" in json.dumps(result)
            assert any(s["id"] == "adna:clinic:what/sleep.md" for s in snapshots)
            runtime._check_active_sources("case", {}, snapshots)
            file = content / "what" / "sleep.md"
            original = file.read_text()
            file.write_text("Wednesday, corrected")
            with pytest.raises(ContextCapacityError, match="changed"):
                runtime._check_active_sources("case", {}, snapshots)
            file.write_text(original)
    finally:
        runtime.close()


def test_source_changed_during_count_is_removed_before_dispatch(tmp_path):
    from context_adna import AdnaSource

    root, content = project(tmp_path)
    provider = RecordingProvider()
    count = provider.count

    def change_during_count(payload):
        (content / "what" / "sleep.md").write_text("Wednesday, corrected")
        return count(payload)

    provider.count = change_during_count
    runtime = ContextRuntime(ContextStore(tmp_path / "context.db"), provider, Budget(),
                             sources=(AdnaSource(root, origin="clinic"),))
    try:
        runtime.chat("case", "sleep observations")
        assert "Tuesday" not in json.dumps(provider.requests)
        assert "adna:clinic:what/sleep.md" not in runtime.store.manifest("case")["selected_ids"]
    finally:
        runtime.close()
