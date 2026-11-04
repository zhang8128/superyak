"""Ship home and crossing plan, Task 12: remote deliveries and the guard (spec 2.5's second rule; P16, S7, S8, M1, nit 8,
the plan re-check's items 2 to 4). Every remote item delivered is recorded beside the receiving store, by the digests of
its normalized text and of each sentence of 12 words or more, and every tool that stores text refuses a copy of one,
on its raw arguments, in every gate mode, before it writes anything."""
import sqlite3
import threading
import time
from pathlib import Path

import pytest

import remote_deliveries as rd

NOW = 1_800_000_000
DAY = 86400
# A delivered item: one sentence of 15 words, then a short one.
ITEM = ("The lighthouse crossing records every delivered passage beside the receiving store for ninety whole days. "
        "It keeps no copy.")
LONG = "The lighthouse crossing records every delivered passage beside the receiving store for ninety whole days."
SHORT_ITEM = "Bridges need steady upstream support always."  # 6 words
PUBLISHER = "urn:superyak:" + "c" * 64 + ":ship:" + "d" * 32


def delivered(*texts, disclosure="disc-1"):
    return [dict(disclosureId=disclosure, publisher=PUBLISHER, memoryId=f"m{n}", content=t)
            for n, t in enumerate(texts)]


@pytest.fixture
def record(tmp_path):
    path = rd.path_for(tmp_path / "graph.db")
    rd.record(path, delivered(ITEM, SHORT_ITEM), now=NOW)
    return path


# ---------------------------------------------------------------- normalizing and splitting (P16, S8)

def test_the_record_lives_beside_the_store():
    assert rd.path_for("/srv/x/.engram/instances/tardis/graph.db") == Path(
        "/srv/x/.engram/instances/tardis/remote-deliveries.db")
    for nowhere in (":memory:", "", None):
        with pytest.raises(ValueError):
            rd.path_for(nowhere)


@pytest.mark.parametrize("text, expected", [
    ("  Hello\t\tWORLD \n again ", "hello world again"),
    ("Ｆｕｌｌｗｉｄｔｈ text", "fullwidth text"),        # NFKC
    ("Straße", "strasse"),                              # casefold
    ("- a list item", "a list item"),
    ("> - a quoted list item", "a quoted list item"),
    ("1. first", "first"), ("2) second", "second"), ("* star", "star"), ("+ plus", "plus"),
    ("an item - with a dash", "an item - with a dash"),
    ("-no space", "-no space"),
])
def test_normalize(text, expected):
    assert rd.normalize(text) == expected


def test_sentences_split_after_end_marks_and_at_newlines_before_normalizing():
    text = "One two. Three four! Five six? Seven\nEight nine.Ten"
    assert rd.sentences(text) == ["one two.", "three four!", "five six?", "seven", "eight nine.ten"]
    assert rd.sentences("- a listed line\n> a quoted line") == ["a listed line", "a quoted line"]


def test_digests_count_only_sentences_of_12_words_or_more():
    item, sentences = rd.digests(ITEM)
    assert item == rd.digest(rd.normalize(ITEM))
    assert sentences == [rd.digest(rd.normalize(LONG))]
    assert rd.digests(SHORT_ITEM)[1] == []


# ---------------------------------------------------------------- recording and refusing

def test_record_writes_item_and_sentence_digests_privately(record):
    with sqlite3.connect(record) as db:
        rows = db.execute("SELECT disclosure_id, publisher, memory_id, part, digest, at FROM remote_deliveries "
                          "ORDER BY memory_id, part").fetchall()
    assert rows == [("disc-1", PUBLISHER, "m0", "item", rd.digest(rd.normalize(ITEM)), NOW),
                    ("disc-1", PUBLISHER, "m0", "sentence", rd.digest(rd.normalize(LONG)), NOW),
                    ("disc-1", PUBLISHER, "m1", "item", rd.digest(rd.normalize(SHORT_ITEM)), NOW)]
    assert record.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(record) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


@pytest.mark.parametrize("text", [ITEM, LONG, "  " + ITEM.upper() + "  ", "- " + LONG, "> " + ITEM, "> - " + LONG,
                                  "1. " + LONG, "2) " + ITEM, "* " + LONG, "Some words first.\n" + LONG,
                                  "My note says this. " + LONG + " And then more."])
def test_a_copy_of_a_delivered_item_or_long_sentence_is_refused(record, text):
    assert rd.refused(record, [text], now=NOW)


@pytest.mark.parametrize("text", ["A paraphrase: the crossing keeps digests of what it delivers for three months.",
                                  "It keeps no copy.",                       # a delivered sentence under 12 words
                                  "Note: " + LONG,                           # a long sentence with other words on its line
                                  "We agreed that " + SHORT_ITEM.lower() + " So we wrote it down.",
                                  "Nothing like it at all."])
def test_what_the_guard_does_not_catch_is_kept(record, text):
    """Spec 2.5's limits, said plainly: a paraphrase, a delivered sentence under 12 words, a long one carried with other
    words on its line, and (nit 8) a short item quoted inside a longer note."""
    assert not rd.refused(record, [text], now=NOW)


def test_a_short_item_is_refused_whole(record):
    assert rd.refused(record, [SHORT_ITEM], now=NOW) and rd.refused(record, ["- " + SHORT_ITEM], now=NOW)


def test_any_one_text_refuses_the_lot(record):
    assert rd.refused(record, ["harmless", ITEM], now=NOW)
    assert not rd.refused(record, ["harmless", None, ""], now=NOW)


def test_a_missing_file_means_nothing_was_delivered(tmp_path):
    assert not rd.refused(rd.path_for(tmp_path / "graph.db"), [ITEM], now=NOW)
    assert not rd.path_for(tmp_path / "graph.db").exists()


def test_rows_older_than_90_days_stop_refusing_and_are_pruned_at_most_once_an_hour(tmp_path):
    """S7: rows past 90 days never refuse, and go at a write an hour or more after the last prune; a write sooner
    prunes nothing, even rows already past 90 days, so concurrent writers don't each prune."""
    path = rd.path_for(tmp_path / "graph.db")

    def kept(disclosure):
        with sqlite3.connect(path) as db:
            return db.execute("SELECT COUNT(*) FROM remote_deliveries WHERE disclosure_id=?", (disclosure,)).fetchone()[0]
    rd.record(path, delivered(ITEM, disclosure="a"), now=NOW)                 # the first write prunes (none yet)
    rd.record(path, delivered("A later delivery of no consequence at all.", disclosure="b"), now=NOW + 1000)
    later = NOW + 90 * DAY + 1
    assert not rd.refused(path, [ITEM], now=later)       # past 90 days, even before any prune
    assert kept("a") == 2
    rd.record(path, delivered("A third delivery of no consequence at all.", disclosure="c"), now=later)
    assert kept("a") == 0 and kept("b") == 1            # an hour past the last prune: a's rows go, b is not yet old
    rd.record(path, delivered("A fourth delivery of no consequence at all.", disclosure="d"), now=later + 1500)
    assert kept("b") == 1                                # b is past 90 days now, but the last prune was 1,500 s ago
    rd.record(path, delivered("A fifth delivery of no consequence at all.", disclosure="e"), now=later + 3600)
    assert kept("b") == 0                                # an hour after the last prune, b goes
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM meta WHERE key='last_prune'").fetchone()[0] == str(later + 3600)


# ---------------------------------------------------------------- busy is not unreadable (S7, the plan re-check's item 4)

@pytest.mark.parametrize("make", ["not sqlite", "wrong table"])
def test_an_unreadable_file_raises_unreadable_with_its_cause(tmp_path, make):
    path = rd.path_for(tmp_path / "graph.db")
    if make == "not sqlite":
        path.write_bytes(b"this is not a sqlite file" * 40)
    else:
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE something_else (x)")
    with pytest.raises(rd.Unreadable) as error:
        rd.refused(path, [ITEM], now=NOW)
    assert str(error.value)


def held_exclusively(path):
    """A connection holding the file under an exclusive lock: in WAL, locking_mode=EXCLUSIVE and a write keep every
    other connection out until it closes."""
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("PRAGMA locking_mode=EXCLUSIVE")
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO meta VALUES('held', '1') ON CONFLICT(key) DO UPDATE SET value='1'")
    holder.execute("COMMIT")
    return holder


def test_a_file_held_past_the_busy_timeout_is_busy_for_the_guard_and_the_record(record, monkeypatch):
    monkeypatch.setattr(rd, "BUSY_MS", 200)
    holder = held_exclusively(record)
    try:
        with pytest.raises((rd.RecordBusy, rd.Unreadable)) as read:
            rd.refused(record, [ITEM], now=NOW)
        with pytest.raises((rd.RecordBusy, rd.Unreadable)) as write:
            rd.record(record, delivered("Another delivery that waits on the lock for good."), now=NOW)
    finally:
        holder.close()
    assert (read.type, write.type) == (rd.RecordBusy, rd.RecordBusy)   # busy, never unreadable
    assert str(read.value) == "busy, try again"
    assert rd.BUSY_MS == 200 and rd.refused(record, [ITEM], now=NOW)


def test_the_busy_timeout_is_two_seconds():
    assert rd.BUSY_MS == 2000


def test_a_wal_writer_in_progress_does_not_block_a_guards_read(record):
    writer = sqlite3.connect(record, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO remote_deliveries VALUES('w', 'p', 'm', 'item', 'x', ?)", (NOW,))
        started = time.monotonic()
        assert rd.refused(record, [ITEM], now=NOW)
        assert time.monotonic() - started < 1
    finally:
        writer.execute("ROLLBACK")
        writer.close()


def test_a_read_only_style_wal_file_with_no_sidecars_still_reads(record):
    """The plan re-check's item 4: the guard opens the file read-write, so a WAL file whose -wal and -shm are gone
    reads as what it holds, never as unreadable."""
    for suffix in ("-wal", "-shm"):
        Path(str(record) + suffix).unlink(missing_ok=True)
    assert rd.refused(record, [ITEM], now=NOW)


# ---------------------------------------------------------------- every tool that stores text (M1, the re-check's item 2)

from tests.test_recall_margins import engram_server_env  # noqa: F401,E402 - the real server against a temp home


def snapshot(home):
    """Every row of every table of every store file under the home's .engram, except the remote record itself and
    the tables a refused call may touch with metadata only (operation_log, which _mutation_logged writes for every
    call, and the session registry). The test checks operation_log holds none of the text."""
    import hashlib
    seen = {}
    for path in sorted((Path(home) / ".engram").rglob("*.db")):
        if path.name == "remote-deliveries.db":
            continue
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                                        " AND name NOT IN ('operation_log', 'session_registry')"
                                        " AND sql NOT LIKE 'CREATE VIRTUAL TABLE%'").fetchall():
                rows = con.execute(f'SELECT * FROM "{table}"').fetchall()
                seen[(path.name, table)] = hashlib.sha256(repr(sorted(map(repr, rows))).encode()).hexdigest()
        finally:
            con.close()
    return seen


@pytest.fixture
def guarded(engram_server_env, tmp_path, monkeypatch):  # noqa: F811
    """The real server on a temp home, with ITEM and SHORT_ITEM recorded as delivered from another peer, both
    notepads in the temp home (never ~/.engram), an instinct, a residue, an active task and a recording compressor."""
    import uuid
    import server
    from notepad import Notepad
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    server._init()
    monkeypatch.setattr(server, "_notepad_project", Notepad(tmp_path / ".engram" / "notepad.db"))
    monkeypatch.setattr(server, "_notepad_global", Notepad(tmp_path / ".engram" / "global-notepad.db"))
    instinct = str(uuid.uuid4())
    server._storage.add_instinct(id=instinct, trigger="preference", action="Prefer small careful steps",
                                 source_semantic_ids=[], strength=0.7)
    residue = server.dream_capture("A quiet dream about trains crossing an old stone bridge at night.")["residue_id"]
    server.task_focus("a task", "the plan as it stands")
    commits = []

    class Compressor:
        def commit(self, compress_id, summaries):
            commits.append((compress_id, summaries))
            return {"created": [1]}
    monkeypatch.setattr(server, "_compressor", Compressor())
    rd.record(rd.path_for(server._storage.db_path), delivered(ITEM, SHORT_ITEM), now=int(time.time()))
    return dict(server=server, home=tmp_path, instinct=instinct, residue=residue, commits=commits)


TOOLS = {
    "jot project": lambda s, c, t: s.jot("k1", t),
    "jot global": lambda s, c, t: s.jot("k1", t, scope="global"),
    "jot key": lambda s, c, t: s.jot(t, "a harmless value"),
    "task_update": lambda s, c, t: s.task_update(t),
    "task_focus name": lambda s, c, t: s.task_focus(t),
    "task_focus content": lambda s, c, t: s.task_focus("another task", t),
    "dream_capture": lambda s, c, t: s.dream_capture(t),
    "dream_react": lambda s, c, t: s.dream_react(c["residue"], t),
    "clipboard_pin": lambda s, c, t: s.clipboard_pin(t),
    "clipboard_remind": lambda s, c, t: s.clipboard_remind(t),
    "add_anchor content": lambda s, c, t: s.add_anchor("value", t, "an expected answer"),
    "add_anchor expected": lambda s, c, t: s.add_anchor("value", "a harmless anchor", t),
    "challenge_instinct": lambda s, c, t: s.challenge_instinct(c["instinct"], t),
    "retire_instinct": lambda s, c, t: s.retire_instinct(c["instinct"], t),
    "compress_commit": lambda s, c, t: s.compress_commit("c1", [{"content": t, "kind": "fact", "action": "create"}]),
    "log_outcome": lambda s, c, t: s.log_outcome("recall-1", True, note=t),
    "instinct_feedback": lambda s, c, t: s.instinct_feedback(c["instinct"], True, context=t),
    "share": lambda s, c, t: s.share("m1", "commons", reason=t),
    "assessment_report notes": lambda s, c, t: s.assessment_report(3, notes=t),
    "assessment_report lists": lambda s, c, t: s.assessment_report(3, reached_for=["fine", t]),
}


@pytest.mark.parametrize("text", [ITEM, LONG], ids=["item", "sentence"])
@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_every_tool_that_stores_text_refuses_a_delivered_copy_and_writes_nothing(guarded, tool, text):
    s = guarded["server"]
    before = snapshot(guarded["home"])
    strength = s._storage.get_instinct(guarded["instinct"])["strength"]
    out = TOOLS[tool](s, guarded, text)
    assert out == s._REMOTE_REFUSED
    assert snapshot(guarded["home"]) == before
    logged = repr(s._storage.conn.execute("SELECT * FROM operation_log").fetchall())
    assert "lighthouse crossing records" not in logged.lower()      # metadata only: no text left behind
    inst = s._storage.get_instinct(guarded["instinct"])
    assert inst is not None and inst["strength"] == strength     # challenge_instinct and retire_instinct: untouched
    assert guarded["commits"] == []                              # compress_commit: Compressor.commit never ran


def test_the_wrapped_text_a_tool_stores_is_never_what_is_checked(guarded):
    """challenge_instinct stores "Evidence: ..." and retire_instinct "Reason: ...": checked on the stored text, the
    long sentence would carry a prefix on its line and pass. The raw argument is what's checked."""
    s = guarded["server"]
    stored = f"Instinct challenged: \"x\"\nEvidence: {ITEM}"
    assert not rd.refused(rd.path_for(s._storage.db_path), [stored], now=int(time.time()))
    assert s.challenge_instinct(guarded["instinct"], ITEM) == s._REMOTE_REFUSED


def test_a_tool_keeps_text_that_was_never_delivered(guarded):
    s = guarded["server"]
    assert s.clipboard_pin("A note of my own, never delivered by anyone.").get("id")
    assert "error" not in s.jot("k2", "My own plan item.")
    assert s.remember(content="A memory of my own, never delivered by anyone.").get("episode_id")


# ---------------------------------------------------------------- the record in neighbor_arm (P16 order, S7)

from tests.test_neighbors import (CONTEXT as N_CONTEXT, NOW as N_NOW, PEER, REMOTE_TEXT, SHIP, SHIP_REF,  # noqa: E402
                                  FakeCrossingSocket, Log, remote_answer, remote_policy)


@pytest.fixture
def arm(tmp_path):
    """neighbor_arm's arguments for one remote publisher, asked through a recording `ask`, with a Log storage that
    has a db_path, so its record lands beside it."""
    import copy
    path = tmp_path / "policy.json"
    remote_policy(path, local=())
    log = Log()
    log.db_path = str(tmp_path / "graph.db")
    args = dict(query="private query", context=copy.deepcopy(N_CONTEXT), purpose="session-recall", k=1, storage=log,
                session_id="s", recall_id="local-turn", receiver="engram", publishers=[], policy_path=path,
                now=lambda: N_NOW, remote_publishers=[dict(peer_id=PEER, ship=SHIP, context="memory/technical")],
                receiver_ship="e" * 32, receiver_instance="2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d",
                ask=lambda i, s, p, frame, ms: remote_answer({"frame": frame})["frame"])
    return args, rd.path_for(log.db_path)


def test_a_delivered_remote_item_is_recorded_by_its_reads_disclosure_id(arm):
    import neighbors
    args, path = arm
    result = neighbors.neighbor_arm(**args)
    assert [i["content"] for i in result["delivered"]] == [REMOTE_TEXT]
    assert rd.refused(path, [REMOTE_TEXT], now=int(N_NOW.timestamp()))
    with sqlite3.connect(path) as db:
        assert {r[0] for r in db.execute("SELECT disclosure_id FROM remote_deliveries")} == {"remote-read"}
    receipt = args["storage"].entries[0]["context"]["receipt"]
    assert receipt["extensions"]["engram:readDisclosures"][0]["disclosureId"] == "remote-read"


def test_local_items_are_never_recorded(tmp_path):
    import neighbors
    from tests import test_neighbors as tn
    log = Log()
    log.db_path = str(tmp_path / "graph.db")
    path = tmp_path / "policy.json"
    tn.policy(path)

    def call(self, frame, *, deadline=None):
        if frame["kind"] == "recall":
            return dict(protocolVersion="0.1", kind="recall_result", turnId="t", queryDigest=tn.content_digest(frame["query"]),
                        context=frame["context"], decision=tn.ALLOW, disclosureId="d1",
                        candidates=[dict(memoryId="m1", rank=1, layer="episode", lane="personal", audiences=["commons"],
                                         contentDigest=tn.content_digest("A local share, from this home."))])
        return dict(protocolVersion="0.1", kind="read_result", disclosureId="d2",
                    items=[dict(memoryId="m1", content="A local share, from this home.", audiences=["commons"],
                                decision=tn.ALLOW)])
    original = neighbors.LighthouseClient.call
    neighbors.LighthouseClient.call = call
    try:
        result = neighbors.neighbor_arm(query="q", context=dict(N_CONTEXT), purpose="session-recall", k=1, storage=log,
                                        session_id="s", recall_id="r", receiver="engram", publishers=["why"],
                                        socket_path=tmp_path / "s.sock", policy_path=path, now=lambda: N_NOW)
    finally:
        neighbors.LighthouseClient.call = original
    assert result["delivered"] and not rd.path_for(log.db_path).exists()


def test_the_record_is_written_before_the_receipt(arm, monkeypatch):
    import neighbors
    args, path = arm
    order = []
    real_record, real_receipt = rd.record, neighbors.write_receipt
    monkeypatch.setattr(rd, "record", lambda *a, **k: order.append("record") or real_record(*a, **k))
    monkeypatch.setattr(neighbors, "write_receipt", lambda *a, **k: order.append("receipt") or real_receipt(*a, **k))
    neighbors.neighbor_arm(**args)
    assert order == ["record", "receipt"]


def test_a_failed_record_suppresses_the_delivery_and_writes_no_receipt(arm, monkeypatch):
    import neighbors
    args, path = arm
    monkeypatch.setattr(rd, "record", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
    result = neighbors.neighbor_arm(**args)
    assert result["delivered"] == [] and result["receipt_id"] is None and result["degraded"] is True
    assert result["diagnostics"][0] == {"code": "RECORD_FAILED"}
    assert args["storage"].entries == []


def test_a_busy_record_suppresses_the_delivery_as_record_busy(arm, monkeypatch):
    import neighbors
    args, path = arm
    monkeypatch.setattr(rd, "record", lambda *a, **k: (_ for _ in ()).throw(rd.RecordBusy("busy, try again")))
    result = neighbors.neighbor_arm(**args)
    assert result["delivered"] == [] and result["diagnostics"][0] == {"code": "RECORD_BUSY"}
    assert args["storage"].entries == []


def test_a_storage_with_no_place_for_the_record_delivers_nothing(arm):
    import neighbors
    args, path = arm
    del args["storage"].db_path
    result = neighbors.neighbor_arm(**args)
    assert result["delivered"] == [] and result["diagnostics"][0] == {"code": "RECORD_FAILED"}


def test_two_sessions_of_one_ship_each_deliver_and_each_guard_refuses_the_others_text(tmp_path, monkeypatch):
    """S2, P19's condition 2: two Storage connections on one store, as two sessions, deliver through their own
    attach_neighbors at once. Both receipts and both sets of rows land in the one record beside the store, so either
    session's guard refuses the text the other received. This is the interim's named limit, until the host."""
    import neighbors
    from storage import Storage
    instance = tmp_path / ".engram" / "instances" / "engram"
    instance.mkdir(parents=True)
    remote_policy(instance / "policy.json", local=())
    (instance / "lighthouse-receiver.toml").write_text(
        'enabled = true\npublishers = []\npolicy_path = "policy.json"\ncrossing_socket = "crossing.sock"\n'
        f'receiver_ship = "{"e" * 32}"\n[[remote_publishers]]\npeer_id = "{PEER}"\nship = "{SHIP}"\n'
        'context = "memory/technical"\n')
    Storage(str(instance / "graph.db")).close()
    texts = {"rivers": "Rivers carry the silt that builds the delta, season after season, without any hurry at all.",
             "bridges": "Bridges stand on the piers that the old engineers sank deep below the riverbed long ago."}
    together = threading.Barrier(2, timeout=10)

    def ask_crossing(receiver_instance, receiver_ship, publisher, frame, deadline_ms, *, socket_path):
        from lighthouse_protocol import content_digest
        if frame["kind"] == "recall":
            together.wait()
            query = frame["query"]
            return dict(protocolVersion="0.1", kind="recall_result", turnId=f"turn-{query}",
                        queryDigest=content_digest(query), context=frame["context"], disclosureId=f"trace-{query}",
                        decision={"effect": "allow", "ruleId": "r", "code": None},
                        candidates=[dict(memoryId=f"m-{query}", rank=1, layer="episode", lane="work",
                                         audiences=["commons"], contentDigest=content_digest(texts[query]))])
        query = frame["turnId"].removeprefix("turn-")
        return dict(protocolVersion="0.1", kind="read_result", disclosureId=f"read-{query}",
                    items=[dict(memoryId=f"m-{query}", content=texts[query], audiences=["commons"],
                                decision={"effect": "allow", "ruleId": "r", "code": None})])
    monkeypatch.setattr(neighbors, "ask_crossing", ask_crossing)
    results, paths = {}, {}

    def run(query):
        storage = Storage(str(instance / "graph.db"))   # each session its own connection, on its own thread
        try:
            paths[query] = rd.path_for(storage.db_path)
            results[query] = neighbors.attach_neighbors({"results": [], "recall_id": f"r-{query}"}, query=query,
                                                        context_id="memory/technical", purpose="session-recall",
                                                        storage=storage, session_id=f"s-{query}", receiver="engram",
                                                        engram_home=tmp_path)
        finally:
            storage.close()
    threads = [threading.Thread(target=run, args=(q,)) for q in texts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    for query, text in texts.items():
        assert [i["content"] for i in results[query]["neighbors"]["delivered"]] == [text]
    with sqlite3.connect(instance / "graph.db") as db:
        assert db.execute("SELECT COUNT(*) FROM memory_log WHERE event_type = 'lighthouse_receipt'").fetchone()[0] == 2
    assert paths["rivers"] == paths["bridges"]
    record = paths["rivers"]
    with sqlite3.connect(record) as db:
        assert {r[0] for r in db.execute("SELECT disclosure_id FROM remote_deliveries")} == {"read-rivers",
                                                                                             "read-bridges"}
    assert rd.refused(record, [texts["bridges"]], now=int(time.time()))   # session rivers' guard, bridges' text
    assert rd.refused(record, [texts["rivers"]], now=int(time.time()))    # and the reverse
