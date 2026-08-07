import json
import math

import pytest
from storage import Storage
server = pytest.importorskip('server')


class FakeEmbeddingProvider:
    def dimension(self):
        return 768

    def embed(self, texts, **_kwargs):
        vectors = []
        for text in texts:
            offset = (sum(text.encode()) % 17) / 100
            vector = [1.0 + offset] + [0.001] * 767
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


@pytest.fixture
def operation_server_env(tmp_path, monkeypatch):
    from clipboard import Clipboard
    from compress import Compressor
    from config import load_config
    from notepad import Notepad

    storage = Storage(str(tmp_path / "operation-tools.db"))
    embeddings = FakeEmbeddingProvider()
    config = load_config(tmp_path)
    compressor = Compressor(storage, embeddings, config.compression)
    clipboard = Clipboard(tmp_path / "clipboard.db")
    project_notepad = Notepad(tmp_path / "project-notepad.db")
    global_notepad = Notepad(tmp_path / "global-notepad.db")
    session_id = "operation-audit-session"
    storage.stamp_session_registry(
        session_id,
        harness="codex",
        model="audit-model",
        repo=str(tmp_path),
    )

    monkeypatch.setattr(server, "_initialized", True)
    monkeypatch.setattr(server, "_storage", storage)
    monkeypatch.setattr(server, "_embeddings", embeddings)
    monkeypatch.setattr(server, "_config", config)
    monkeypatch.setattr(server, "_compressor", compressor)
    monkeypatch.setattr(server, "_clipboard", clipboard)
    monkeypatch.setattr(server, "_notepad_project", project_notepad)
    monkeypatch.setattr(server, "_notepad_global", global_notepad)
    monkeypatch.setattr(server, "_session_id", session_id)
    monkeypatch.setattr(server, "_session_episode_count", 0)
    monkeypatch.setattr(server, "PROJECT_ROOT", tmp_path)

    yield server, storage

    project_notepad.close()
    global_notepad.close()
    clipboard.close()
    storage.close()


@pytest.mark.parametrize(
    ("operation", "arguments", "expected"),
    [
        (
            "remember",
            {"content": "SECRET-REMEMBER", "core": True, "work": False},
            {"core": True, "work": False},
        ),
        ("dream_capture", {"reaction": "SECRET-DREAM"}, {}),
        (
            "challenge_instinct",
            {"instinct_id": "i1", "evidence": "SECRET-EVIDENCE"},
            {},
        ),
        (
            "assessment_report",
            {"function_score": 4, "notes": "SECRET-NOTES"},
            {"function_score": 4},
        ),
        (
            "compress_commit",
            {"compress_id": "c1", "summaries": [{"content": "SECRET-SUMMARY"}]},
            {"summary_count": 1},
        ),
        (
            "clipboard_remind",
            {
                "text": "SECRET-CLIP",
                "trigger": "every_n_steps",
                "value": 5,
                "repeat": True,
            },
            {"trigger": "every_n_steps", "value": 5, "repeat": True},
        ),
    ],
)
def test_sanitize_operation_details_drops_content(operation, arguments, expected):
    from operation_audit import sanitize_operation_details

    sanitized = sanitize_operation_details(operation, arguments)

    assert sanitized == expected
    assert "SECRET" not in json.dumps(sanitized)


@pytest.mark.parametrize(
    ("operation", "field", "value"),
    [
        ("reflect", "focus", "usage"),
        ("reflect", "focus", "gaps"),
        ("reflect", "focus", "instincts"),
        ("reflect", "focus", "contradictions"),
        ("reflect", "focus", "vital_signs"),
        ("reflect", "focus", "staleness"),
        ("reflect", "focus", "instinct_contexts"),
        ("reflect", "focus", "classifications"),
        ("reflect", "focus", "resonances"),
        ("reflect", "focus", "instinct_clusters"),
        ("reflect", "focus", "coherence"),
        ("reflect", "focus", "anchors"),
        ("reflect", "focus", "assessments"),
        ("reflect", "focus", "fidelity"),
        ("reflect", "focus", "cohesion"),
        ("reflect", "focus", "persistence"),
        ("jot", "scope", "project"),
        ("jot", "scope", "global"),
        ("jot", "status", "open"),
        ("jot", "status", "deferred"),
        ("jot", "status", "done"),
        ("erase", "scope", "project"),
        ("erase", "scope", "global"),
        ("clipboard_remind", "trigger", "every_n_steps"),
        ("clipboard_remind", "trigger", "interval_seconds"),
        ("clipboard_remind", "trigger", "once_at"),
    ],
)
def test_sanitize_operation_details_preserves_only_exact_enum_values(
    operation, field, value
):
    from operation_audit import sanitize_operation_details

    assert sanitize_operation_details(operation, {field: value}) == {field: value}


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("unknown", {"core": True}),
        ("remember", {"content": "SECRET", "core": 1}),
        ("mark_core", {"tier": True}),
        ("graph_view", {"depth": float("inf")}),
        ("clipboard_remind", {"value": float("nan")}),
        ("reflect", {"focus": "SECRET"}),
        ("jot", {"scope": "SECRET", "status": "SECRET"}),
        ("compress_commit", {"summaries": "SECRET"}),
    ],
)
def test_sanitize_operation_details_rejects_unknown_or_invalid_metadata(
    operation, arguments
):
    from operation_audit import sanitize_operation_details

    assert sanitize_operation_details(operation, arguments) == {}

def test_operation_schema_and_append(tmp_path):
    s = Storage(str(tmp_path / 'g.db'))
    cols = {r[1] for r in s.conn.execute('pragma table_info(operation_log)')}
    assert cols == {'id','timestamp','operation','session_id','harness','model','repo','target_ids','details','outcome'}
    ident = s.add_operation('remember','sid','codex','m','/repo',['e1'],{'x':1},'success')
    row = s.conn.execute('select operation,session_id,target_ids,details from operation_log where id=?',(ident,)).fetchone()
    assert row['operation'] == 'remember' and row['session_id'] == 'sid'
    s.close()

def test_operation_fail_open(tmp_path):
    s = Storage(str(tmp_path / 'g.db'))
    s.conn.execute('drop table operation_log')
    assert s.add_operation('x','s')
    s.close()


def test_operation_details_migration_scrubs_historical_content(tmp_path):
    db_path = tmp_path / "historical.db"
    storage = Storage(str(db_path))
    cases = [
        (
            "remember",
            {
                "content": "SECRET-REMEMBER-HISTORICAL",
                "core": True,
                "genome": False,
                "work": True,
                "source": "SECRET-SOURCE",
            },
            {"core": True, "genome": False, "work": True},
        ),
        ("instinct_feedback", {"context": "SECRET-CONTEXT", "followed": False}, {"followed": False}),
        ("mark_core", {"episode_id": "SECRET-ID", "tier": 2}, {"tier": 2}),
        ("assessment_report", {"notes": "SECRET-NOTES", "function_score": 4}, {"function_score": 4}),
        ("reindex", {"full": True, "path": "SECRET-PATH"}, {"full": True}),
        ("graph_view", {"center": "SECRET-CENTER", "depth": 3}, {"depth": 3}),
        ("clipboard_pin", {"text": "SECRET-PIN", "priority": 7}, {"priority": 7}),
        (
            "clipboard_remind",
            {
                "text": "SECRET-REMINDER",
                "trigger": "interval_seconds",
                "value": 2.5,
                "repeat": False,
            },
            {"value": 2.5, "repeat": False, "trigger": "interval_seconds"},
        ),
        ("reflect", {"focus": "coherence", "query": "SECRET-QUERY"}, {"focus": "coherence"}),
        (
            "jot",
            {"key": "SECRET-KEY", "value": "SECRET-VALUE", "scope": "global", "status": "deferred"},
            {"scope": "global", "status": "deferred"},
        ),
        ("erase", {"key": "SECRET-ERASE", "scope": "project"}, {"scope": "project"}),
        (
            "compress_commit",
            {"compress_id": "SECRET-COMPRESS", "summaries": [{"content": "SECRET-SUMMARY"}]},
            {"summary_count": 1},
        ),
        ("dream_capture", {"reaction": "SECRET-DREAM"}, {}),
        ("unknown_operation", {"content": "SECRET-UNKNOWN", "core": True}, {}),
        ("remember", {"content": "SECRET-WRONG-BOOL", "core": 1}, {}),
        ("mark_core", {"episode_id": "SECRET-WRONG-NUMBER", "tier": True}, {}),
        (
            "clipboard_remind",
            {
                "text": "SECRET-WRONG-REMINDER",
                "trigger": "SECRET-TRIGGER",
                "value": "5",
                "repeat": 1,
            },
            {},
        ),
        ("reflect", {"focus": "SECRET-FOCUS"}, {}),
        ("compress_commit", {"summaries": {"content": "SECRET-NOT-ARRAY"}}, {}),
    ]

    inserted = []
    for index, (operation, details, expected) in enumerate(cases):
        target_ids = [f"target-{index}"]
        operation_id = storage.add_operation(
            operation,
            "session-historical",
            "codex",
            "model-historical",
            "/repo/historical",
            target_ids,
            details,
            "failure" if index % 2 else "success",
        )
        inserted.append((operation_id, target_ids, expected, "failure" if index % 2 else "success"))

    malformed_id = storage.add_operation(
        "remember",
        "session-historical",
        "codex",
        "model-historical",
        "/repo/historical",
        ["target-malformed"],
        {},
        "success",
    )
    storage.conn.execute(
        "UPDATE operation_log SET details = ? WHERE id = ?",
        ("{SECRET-MALFORMED", malformed_id),
    )
    inserted.append((malformed_id, ["target-malformed"], {}, "success"))
    storage.conn.execute("DELETE FROM schema_version WHERE version = 26")
    storage.conn.commit()
    storage.close()

    migrated = Storage(str(db_path))
    assert migrated.conn.execute(
        "SELECT 1 FROM schema_version WHERE version = 26"
    ).fetchone()

    for operation_id, target_ids, expected_details, outcome in inserted:
        row = migrated.conn.execute(
            "SELECT session_id, harness, model, repo, target_ids, details, outcome "
            "FROM operation_log WHERE id = ?",
            (operation_id,),
        ).fetchone()
        assert row is not None
        assert json.loads(row["details"]) == expected_details
        assert "SECRET" not in row["details"]
        assert json.loads(row["target_ids"]) == target_ids
        assert (row["session_id"], row["harness"], row["model"], row["repo"], row["outcome"]) == (
            "session-historical",
            "codex",
            "model-historical",
            "/repo/historical",
            outcome,
        )

    assert migrated.conn.execute(
        "SELECT json_type(details, '$.core') FROM operation_log WHERE id = ?",
        (inserted[0][0],),
    ).fetchone()[0] == "true"
    migrated.close()


def test_content_bearing_tool_families_log_only_attribution_metadata(
    operation_server_env,
):
    srv, storage = operation_server_env
    markers = {
        "remember": "SECRET-REMEMBER-LIVE",
        "dream_capture": "SECRET-DREAM-CAPTURE-LIVE",
        "dream_react": "SECRET-DREAM-REACT-LIVE",
        "task_focus": "SECRET-TASK-FOCUS-LIVE",
        "task_update": "SECRET-TASK-UPDATE-LIVE",
        "jot": "SECRET-JOT-LIVE",
        "clipboard_pin": "SECRET-CLIPBOARD-PIN-LIVE",
        "clipboard_remind": "SECRET-CLIPBOARD-REMIND-LIVE",
        "challenge_instinct": "SECRET-CHALLENGE-LIVE",
        "retire_instinct": "SECRET-RETIRE-LIVE",
        "assessment_schedule": "SECRET-ASSESSMENT-SCHEDULE-LIVE",
        "assessment_report": "SECRET-ASSESSMENT-REPORT-LIVE",
        "compress_commit": "SECRET-COMPRESS-COMMIT-LIVE",
    }
    target_ids = {}

    remembered = srv.remember(markers["remember"] + " durable memory", core=True)
    target_ids["remember"] = [remembered["episode_id"]]

    captured = srv.dream_capture(markers["dream_capture"])
    target_ids["dream_capture"] = [captured["residue_id"]]
    reacted = srv.dream_react(captured["residue_id"], markers["dream_react"])
    target_ids["dream_react"] = [captured["residue_id"], reacted["new_residue_id"]]

    focused = srv.task_focus("audit-task", markers["task_focus"])
    task_context_id = focused["task_context"]["id"]
    target_ids["task_focus"] = [task_context_id]
    srv.task_update(markers["task_update"])
    target_ids["task_update"] = [task_context_id]

    srv.jot(
        markers["jot"],
        markers["jot"] + " value",
        scope="project",
        status="open",
    )
    target_ids["jot"] = []

    pinned = srv.clipboard_pin(markers["clipboard_pin"], priority=3)
    target_ids["clipboard_pin"] = [pinned["id"]]
    reminded = srv.clipboard_remind(
        markers["clipboard_remind"],
        trigger="every_n_steps",
        value=5,
        repeat=True,
    )
    target_ids["clipboard_remind"] = [reminded["id"]]

    instinct_id = "instinct-operation-audit"
    storage.add_instinct(
        instinct_id,
        trigger="when auditing",
        action="keep only attribution metadata",
        source_semantic_ids=[],
    )
    srv.challenge_instinct(instinct_id, markers["challenge_instinct"])
    target_ids["challenge_instinct"] = [instinct_id]
    srv.retire_instinct(instinct_id, markers["retire_instinct"])
    target_ids["retire_instinct"] = [instinct_id]

    scheduled = srv.assessment_schedule(markers["assessment_schedule"])
    assessment_id = scheduled["assessment_id"]
    target_ids["assessment_schedule"] = [assessment_id]
    storage.conn.execute(
        "UPDATE assessments SET status = 'active', session_id = ? WHERE id = ?",
        ("operation-audit-session", assessment_id),
    )
    storage.conn.commit()
    reported = srv.assessment_report(
        4,
        reached_for=[markers["assessment_report"] + " reached"],
        missing=[markers["assessment_report"] + " missing"],
        felt_absences=markers["assessment_report"] + " felt",
        instinct_consistent_moments=markers["assessment_report"] + " instinct",
        notes=markers["assessment_report"] + " notes",
    )
    assert reported["status"] == "completed"
    target_ids["assessment_report"] = [assessment_id]

    pending = srv.compress()
    summaries = [
        {
            "content": f'{markers["compress_commit"]}-{index}',
            "kind": "fact",
            "action": cluster.get("action", "new"),
        }
        for index, cluster in enumerate(pending["clusters"])
    ]
    assert summaries
    srv.compress_commit(pending["compress_id"], summaries)
    target_ids["compress_commit"] = [pending["compress_id"]]

    serialized_details = "\n".join(
        row["details"]
        for row in storage.conn.execute("SELECT details FROM operation_log").fetchall()
    )
    for marker in markers.values():
        assert marker not in serialized_details

    rows = storage.conn.execute(
        "SELECT operation, target_ids, outcome, harness, model, repo "
        "FROM operation_log"
    ).fetchall()
    by_operation = {row["operation"]: row for row in rows}
    assert set(markers) <= set(by_operation)
    for operation, expected_target_ids in target_ids.items():
        row = by_operation[operation]
        assert json.loads(row["target_ids"]) == expected_target_ids
        assert row["outcome"] == "success"
        assert (row["harness"], row["model"]) == ("codex", "audit-model")

def test_mutation_wrapper_preserves_result_and_logs(monkeypatch):
    class C:
        def execute(self, *args):
            return self

        def fetchone(self):
            return ("codex", "m", "/r")

    class S:
        conn = C()
        def add_operation(self,*args): self.args = args
    st = S(); monkeypatch.setattr(server, '_storage', st); monkeypatch.setattr(server, '_session_id', 'sid')
    @server._mutation_logged
    def fake(item_id): return {'id': item_id, 'ok': True}
    assert fake('x') == {'id':'x','ok':True}
    assert st.args[0] == 'fake'


def test_mutation_wrapper_never_logs_raw_content(monkeypatch):
    class FakeConnection:
        def execute(self, *args):
            return self

        def fetchone(self):
            return ("codex", "m", "/r")

    class FakeStorage:
        conn = FakeConnection()

        def add_operation(self, *args):
            self.args = args

    fake_storage = FakeStorage()
    monkeypatch.setattr(server, "_storage", fake_storage)
    monkeypatch.setattr(server, "_session_id", "sid")

    @server._mutation_logged
    def dream_capture(reaction):
        return {"ok": True}

    dream_capture("SECRET-DREAM-WRAPPER")

    assert fake_storage.args[6] == {}
    assert "SECRET-DREAM-WRAPPER" not in json.dumps(fake_storage.args[6])

def test_mutation_wrapper_preserves_exception(monkeypatch):
    monkeypatch.setattr(server, '_storage', None)
    @server._mutation_logged
    def boom(): raise ValueError('x')
    with pytest.raises(ValueError): boom()

@pytest.mark.skipif(server is None, reason='server dependencies unavailable')
def test_wrapper_classifies_domain_failures(monkeypatch):
    class S:
        def add_operation(self,*args): self.args = args
        conn = type('C', (), {'execute': lambda self,*a: type('R', (), {'fetchone': lambda self: ('codex','m','/r')})()})()
    st=S(); monkeypatch.setattr(server,'_storage',st); monkeypatch.setattr(server,'_session_id','s')
    @server._mutation_logged
    def bad(): return {'error':'bad'}
    bad(); assert st.args[7] == 'failure'
    @server._mutation_logged
    def removed(): return {'removed':False}
    removed(); assert st.args[7] == 'failure'

@pytest.mark.skipif(server is None, reason='server dependencies unavailable')
def test_wrapper_extracts_nested_ids(monkeypatch):
    class S:
        def add_operation(self,*args): self.args = args
        conn = type('C', (), {'execute': lambda self,*a: type('R', (), {'fetchone': lambda self: ('codex','m','/r')})()})()
    st=S(); monkeypatch.setattr(server,'_storage',st); monkeypatch.setattr(server,'_session_id','s')
    @server._mutation_logged
    def nested(): return {'anchor_id':'a1','task_context':{'id':'t1'}}
    nested(); assert set(st.args[5]) >= {'a1','t1'}
