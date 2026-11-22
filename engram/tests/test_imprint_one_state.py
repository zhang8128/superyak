"""One checked State per plan, read and build (store-copy spec revision 8; plan Task 8a; board item
fix:imprint-filter-verified-read). Revision 7 read the ledger with direct SQL that no check covers; these tests fail
on it, and pass when every ledger fact comes from one `Ledger.state()` with a closing key read."""
import errno
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

import imprint_filter
from imprint import build, make_plan, read_plan
from imprint_filter import PlanRefused
from permission_ledger import Ledger, LedgerUnreadable, StateRows, _forget_verified, ledger_path
from tests.imprint_support import (EH, GENOME_ID, HOME, NOW, _ins, _put, add_subject, count_state, ctx, deny,
                                   ep, iid, link_copies, new_store, plan_args, ref_of, remove_cosubject, retire,
                                   splice_page)
from tests.test_permissions_premerge_fixes import _tear_index, _unstamp

ENGRAM = Path(__file__).resolve().parent.parent
UNREADABLE = "The permissions ledger can't be read; nothing was planned."
CHANGED = "The permissions ledger changed while it was read; nothing was planned. Run it again."

# Revision 7's two queries, kept here as the oracles the State's answers are held to (I 16, revision 8).
COSUBJECTS_SQL = """
WITH RECURSIVE chain(ref, links) AS (
  SELECT :ref, 0
  UNION
  SELECT copies.source, chain.links + 1 FROM chain JOIN copies ON copies.object = chain.ref
   WHERE chain.links < :max_links)
SELECT subjects.subject FROM chain JOIN subjects
    ON subjects.object = chain.ref AND subjects.removed_seq IS NULL
UNION
SELECT stores.owner FROM chain JOIN stores
    ON chain.ref LIKE 'mem:%'
   AND stores.instance_id = substr(chain.ref, 5, instr(substr(chain.ref, 5), '/') - 1)
   AND stores.imprint_of IS NULL
EXCEPT SELECT :owner
ORDER BY 1 LIMIT :limit
"""
REFUSALS_SQL = """
SELECT 'deny' AS kind, id FROM records
 WHERE effect = 'deny' AND revoked IS NULL AND (valid_until IS NULL OR valid_until > :now) AND layer != :home
UNION ALL SELECT 'retired', id FROM persons WHERE retired_seq IS NOT NULL
UNION ALL SELECT 'retired', id FROM places WHERE retired_seq IS NOT NULL
"""


def _plans(tmp_path):
    return list((HOME(tmp_path) / "imprints" / "plans").glob("*.json"))


def _read_only(args, *, close=True):
    """``plan_args`` with its writable fixture ledger closed and a read-only one in its place, as a plan opens it."""
    args = list(args)
    if close:
        args[3].ledger.close()
    _forget_verified()                              # what a new process starts with
    args[3] = replace(args[3], ledger=Ledger.open_read_only(EH(args[5].parent)))
    return args


def _no_imprint(tmp_path):
    return list((HOME(tmp_path) / "imprints").glob("*/request.json")) == [] and \
        list((HOME(tmp_path) / "imprints").glob("*/imprint.db")) == []


def _writer(home, script):
    """Run ``script`` with ``led``, a writable ledger of ``home``, in a child process: a write from this process
    would close a descriptor on the file and drop the plan's own POSIX locks (0d7b15ec)."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; "
            "from permission_ledger import Ledger; from tests.imprint_support import _put, _ins; "
            f"led = Ledger.open(Path(sys.argv[2])); {script}; led.close()")
    subprocess.run([sys.executable, "-I", "-c", code, str(ENGRAM), str(home)], check=True, cwd=ENGRAM)


def _overwrite(path: Path, data: bytes):
    """Write ``data`` over ``path`` in place (same inode), from a child process, after a pause that moves ctime."""
    time.sleep(0.02)
    code = "import sys; f = open(sys.argv[1], 'r+b'); f.write(sys.stdin.buffer.read()); f.truncate(); f.close()"
    subprocess.run([sys.executable, "-I", "-c", code, str(path)], input=data, check=True)


# ---- one State per process ------------------------------------------------------------------------------------

@pytest.mark.parametrize("denies", [None, {"person:lee": [deny(actions=["read"], purposes=["calibration"])]}],
                         ids=["calm", "a-deny"])
def test_each_process_reads_the_ledger_through_one_state(tmp_path, monkeypatch, denies):
    calls = count_state(monkeypatch)
    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn", "e2": "person:lee"}, denies=denies)
    plan = make_plan(*args)
    assert len(calls) == 1, "plan"
    read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
    assert len(calls) == 2, "read"
    build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    assert len(calls) == 4, "build"                 # the build's State, then its send check's own (revision 9, 6)
    assert not hasattr(imprint_filter, "COSUBJECTS_SQL") and not hasattr(imprint_filter, "REFUSALS_SQL")


# ---- the State's answers against revision 7's queries ------------------------------------------------------------

def test_the_state_answers_as_the_queries_did(tmp_path):
    from imprint_filter import LedgerFacts

    s = new_store(tmp_path, "s")
    for i in ("plain", "lee", "gone", "copy", "chain", "far", "place", "other", "loose", "imp", "noted"):
        ep(s, i)
    args = plan_args(tmp_path, owner="andy", store=lambda _: s, cosubjects={
        "lee": "person:lee", "gone": ["person:jenn", "person:kim"], "place": "place:la-county/parks"},
        denies={"person:lee": [deny(actions=["read"], purposes=["calibration"])],
                "person:jenn": [deny(revoked=True), deny(valid_until=NOW - 1), deny(audience=["place:la-county/parks"])]})
    led = args[3].ledger
    remove_cosubject(led, "gone", "person:kim", by="person:andy")
    other, imp, src = "1" * 8 + "-1111-4111-8111-" + "1" * 12, "2" * 8 + "-2222-4222-8222-" + "2" * 12, GENOME_ID
    _put(led, "register-store", other, {"insert": [_ins("stores", instance_id=other, name="other", owner="person:sam",
                                                         place="place:home/sam", created_seq="@seq")]})
    _put(led, "register-store", imp, {"insert": [_ins("stores", instance_id=imp, name="imp", owner="person:ava",
                                                       place="place:home/ava", imprint_of=iid(s), created_seq="@seq")]})
    add_subject(led, f"mem:{src}/episode/g1", "person:ola")
    link_copies(led, [ref_of(s, "copy"), f"mem:{src}/episode/g1"])                       # a source unregistered
    link_copies(led, [ref_of(s, "other"), f"mem:{other}/episode/o1"])                    # another owner's store
    link_copies(led, [ref_of(s, "imp"), f"mem:{imp}/episode/i1"])                        # an imprint's store
    chain = [ref_of(s, "chain")] + [f"mem:{src}/episode/c{k}" for k in range(1, 7)]
    link_copies(led, chain)
    add_subject(led, chain[4], "person:near")                                            # 4 links up: counted
    add_subject(led, chain[5], "person:past")                                            # 5 up: past the bound
    retire(led, "person:ava")
    _put(led, "fixture-lane", "noted", {"insert": [_ins("lane_notes", object=ref_of(s, "noted"), lane="personal",
                                                        at=NOW - 10, seq="@seq")]})
    _put(led, "fixture-lane", "noted", {"insert": [_ins("lane_notes", object=ref_of(s, "noted"), lane="pending",
                                                        at=NOW - 5, seq="@seq")]})
    conn = led.conn
    facts = LedgerFacts(led, owner="andy", now=NOW, terms=args[2])
    for id in ("plain", "lee", "gone", "copy", "chain", "far", "place", "other", "loose", "imp", "noted"):
        ref = ref_of(s, id)
        want = frozenset(r[0] for r in conn.execute(COSUBJECTS_SQL, {
            "ref": ref, "max_links": 4, "owner": "person:andy", "limit": imprint_filter.MAX_SUBJECTS}))
        assert facts.cosubjects(ref) == want, id
        note = conn.execute("SELECT lane FROM lane_notes WHERE object=? ORDER BY at DESC, seq DESC, rowid DESC "
                            "LIMIT 1", (ref,)).fetchone()
        assert facts.latest_lane_note(ref) == (None if note is None else note[0]), id
    assert facts.cosubjects(ref_of(s, "chain")) == {"person:near"}
    for store_id in (iid(s), other, imp, "3" * 36):
        row = conn.execute("SELECT instance_id, name, owner, place, imprint_of, created_seq FROM stores "
                           "WHERE instance_id=?", (store_id,)).fetchone()
        assert facts.store_row(store_id) == (None if row is None else dict(row)), store_id
    found = {(r[0], r[1]) for r in conn.execute(REFUSALS_SQL, {"now": NOW, "home": "place:home/andy"})}
    assert facts.any == bool(found)
    assert {i for k, i in found if k == "retired"} == {"person:ava"}
    assert facts.retired("person:ava") and not facts.retired("person:lee")
    assert facts.refuses(ref_of(s, "lee"), "person:lee") and not facts.refuses(ref_of(s, "gone"), "person:jenn")


# ---- a torn page hides nothing -------------------------------------------------------------------------------------

def _tear_case(tmp_path, case):
    """Each case on a ledger with no deny outside the owner's home and no retirement (but the records case, which
    holds lee's deny alone): the memory that ships under revision 7, and the tear."""
    cos = {"e1": "person:lee"} if case in ("subjects", "records") else {}
    denies = {"person:lee": [deny(actions=["read"], purposes=["calibration"])]} if case == "records" else None
    args = plan_args(tmp_path, owner="andy", episodes=4, cosubjects=cos, denies=denies, ledger=True)
    led, s_ref = args[3].ledger, lambda id: f"mem:{args[3].source_id}/episode/{id}"
    home = EH(tmp_path)
    if case == "copies":                         # e2 is a copy of a source that records lee, linked alone
        add_subject(led, f"mem:{GENOME_ID}/episode/g1", "person:lee")
        link_copies(led, [s_ref("e2"), f"mem:{GENOME_ID}/episode/g1"])
    if case == "stores":                         # e3's chain reaches a registered store that lee owns
        lees = "4" * 8 + "-4444-4444-8444-" + "4" * 12
        _put(led, "register-store", lees, {"insert": [_ins("stores", instance_id=lees, name="lee", owner="person:lee",
                                                            place="place:home/lee", created_seq="@seq")]})
        link_copies(led, [s_ref("e3"), f"mem:{lees}/episode/l1"])
    if case == "lane":                           # e4's re-lane is not settled
        _put(led, "fixture-lane", "e4", {"insert": [_ins("lane_notes", object=s_ref("e4"), lane="pending",
                                                         at=NOW - 60, seq="@seq")]})
    led.close()
    if case == "subjects":
        _tear_index(home, "subjects_object", f"NOT (object = '{s_ref('e1')}' AND subject = 'person:lee')")
    elif case == "lane":
        _tear_index(home, "lane_notes_object", f"object != '{s_ref('e4')}'")
    elif case == "copies":
        splice_page(home, "sqlite_autoindex_copies_1", "DELETE FROM copies WHERE object = ?", (s_ref("e2"),))
    elif case == "stores":
        splice_page(home, "sqlite_autoindex_stores_1", "DELETE FROM stores WHERE owner = 'person:lee'", ())
    else:
        splice_page(home, "records", "DELETE FROM records WHERE layer = 'place:home/lee'", ())
    _forget_verified()
    args = list(args)
    args[3] = replace(args[3], ledger=Ledger.open_read_only(home))
    return args


@pytest.mark.parametrize("case", ["subjects", "copies", "stores", "lane", "records"])
def test_a_torn_page_refuses_the_plan(tmp_path, case):
    args = _tear_case(tmp_path, case)
    try:
        with pytest.raises(PlanRefused, match="The permissions ledger can't be read; nothing was planned"):
            make_plan(*args)
    finally:
        args[3].ledger.close()
    assert _plans(tmp_path) == []


# ---- a ledger read that fails late ---------------------------------------------------------------------------------

def _late_failure(monkeypatch, how):
    if how == "rows":
        def fail(self, sql, args):
            raise LedgerUnreadable("the permission ledger's rows could not be read: torn")
        monkeypatch.setattr(StateRows, "_query", fail)
    elif how == "sqlite":
        def fail(self, *a, **k):
            raise sqlite3.DatabaseError("database disk image is malformed")
        monkeypatch.setattr(Ledger, "state", fail)
    else:
        def fail(self, *a, **k):
            raise LedgerUnreadable("permissions.db: the ledger changed during this read; retry")
        monkeypatch.setattr(Ledger, "state", fail)


@pytest.mark.parametrize("how", ["rows", "sqlite", "changed"])
@pytest.mark.parametrize("step", ["plan", "read", "build"])
def test_a_ledger_read_that_fails_late_refuses(tmp_path, monkeypatch, step, how):
    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"})
    plan = None if step == "plan" else make_plan(*args)
    _late_failure(monkeypatch, how)
    sentence = "changed while it was read" if how == "changed" else "The permissions ledger can't be read"
    with pytest.raises(PlanRefused, match=sentence):
        if step == "plan":
            make_plan(*args)
        elif step == "read":
            read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
        else:
            build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    assert len(_plans(tmp_path)) == (0 if step == "plan" else 1) and _no_imprint(tmp_path)


# ---- the ledger moved during the run ---------------------------------------------------------------------------

def _during_close(monkeypatch, act):
    from imprint_filter import LedgerFacts

    real = LedgerFacts.close

    def close(self):
        act()
        return real(self)
    monkeypatch.setattr(LedgerFacts, "close", close)


def _same_counter_copy(path: Path) -> bytes:
    """The ledger's bytes with lee's subject row changed to a name of the same length and the change counter put
    back: the same size and counter, so only ctime tells the key apart."""
    before = path.read_bytes()
    twin = path.with_name("twin.db")
    twin.write_bytes(before)
    con = sqlite3.connect(twin)
    con.execute("UPDATE subjects SET subject = 'person:lea' WHERE subject = 'person:lee'")
    con.commit()
    con.close()
    data = bytearray(twin.read_bytes())
    data[24:28] = before[24:28]
    twin.unlink()
    assert len(data) == len(before)
    return bytes(data)


@pytest.mark.parametrize("move", ["same-counter", "restore-then-appends"])
def test_the_ledger_moved_mid_run_refuses(tmp_path, monkeypatch, move):
    args = plan_args(tmp_path, owner="andy", cosubjects={"e2": "person:jenn"})
    path = ledger_path(EH(tmp_path))
    args[3].ledger.close()                      # bytes are read only while no connection here holds the file
    backup = path.read_bytes()                                      # before lee's row
    led = Ledger.open(EH(tmp_path))
    add_subject(led, f"mem:{args[3].source_id}/episode/e1", "person:lee")
    led.close()
    data = _same_counter_copy(path) if move == "same-counter" else None
    args = _read_only(args, close=False)
    if move == "same-counter":
        _during_close(monkeypatch, lambda: _overwrite(path, data))
    else:
        def restore():
            _overwrite(path, backup)
            _writer(EH(tmp_path), "_put(led, 'fixture-x', 'a', {'insert': []}); _put(led, 'fixture-x', 'b', {'insert': []})")
        _during_close(monkeypatch, restore)
    try:
        with pytest.raises(PlanRefused, match="changed while it was read"):
            make_plan(*args)
    finally:
        args[3].ledger.close()
    assert _plans(tmp_path) == []


def test_a_marked_append_during_the_run_passes(tmp_path, monkeypatch):
    args = _read_only(plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"}))
    _during_close(monkeypatch, lambda: _writer(EH(tmp_path), "_put(led, 'fixture-x', 'a', {'insert': []})"))
    try:
        make_plan(*args)
    finally:
        args[3].ledger.close()
    assert len(_plans(tmp_path)) == 1


@pytest.mark.parametrize("err", [errno.EIO, errno.ENOENT])
@pytest.mark.parametrize("step", ["plan", "read", "build"])
def test_a_bare_os_error_in_the_closing_read_refuses(tmp_path, monkeypatch, step, err):
    """The reader's 1 on b3eb3497 (all hands bfa9823a): the closing read's ``_read_key`` does os.pread and os.stat,
    and either can raise a bare OSError, an I/O error or the file gone. It reached the caller as a traceback. It
    refuses with the process's sentence and saves nothing: a ledger gone reads as changed, other errors as
    unreadable."""
    import permission_ledger

    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"})
    plan = None if step == "plan" else make_plan(*args)

    def broken(*a, **k):
        raise OSError(err, os.strerror(err))
    _during_close(monkeypatch, lambda: monkeypatch.setattr(permission_ledger, "_read_key", broken))
    sentence = "changed while it was read" if err == errno.ENOENT else "The permissions ledger can't be read"
    with pytest.raises(PlanRefused, match=sentence):
        if step == "plan":
            make_plan(*args)
        elif step == "read":
            read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
        else:
            build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    assert len(_plans(tmp_path)) == (0 if step == "plan" else 1) and _no_imprint(tmp_path)


# ---- an unstamped ledger ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("torn", [False, True])
def test_an_unstamped_ledger_is_checked_by_sqlite(tmp_path, torn):
    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:lee"})
    ref = f"mem:{args[3].source_id}/episode/e1"
    args[3].ledger.close()
    _unstamp(EH(tmp_path))
    if torn:
        _tear_index(EH(tmp_path), "subjects_object", f"NOT (object = '{ref}' AND subject = 'person:lee')")
    _forget_verified()
    args = list(args)
    args[3] = replace(args[3], ledger=Ledger.open_read_only(EH(tmp_path)))
    try:
        if torn:
            with pytest.raises(PlanRefused, match="The permissions ledger can't be read"):
                make_plan(*args)
        else:
            assert make_plan(*args).others == {"memories": 1, "people": 1}
    finally:
        args[3].ledger.close()
    assert len(_plans(tmp_path)) == (0 if torn else 1)


def test_an_append_during_the_run_on_an_unstamped_ledger_refuses(tmp_path, monkeypatch):
    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"})
    args[3].ledger.close()
    _unstamp(EH(tmp_path))
    _forget_verified()
    args = list(args)
    args[3] = replace(args[3], ledger=Ledger.open_read_only(EH(tmp_path)))
    _during_close(monkeypatch, lambda: _writer(EH(tmp_path), "_put(led, 'fixture-x', 'a', {'insert': []})"))
    try:
        with pytest.raises(PlanRefused, match="changed while it was read"):
            make_plan(*args)
    finally:
        args[3].ledger.close()
    assert _plans(tmp_path) == []


# ---- the agent keeps the State lazy --------------------------------------------------------------------------------

def _whole_with_agent(state, place):
    """Revision 7's ``_with_agent``: the State rebuilt whole with the agent, the oracle for the lazy one."""
    from permissions import State

    tables = state.to_tables()
    if imprint_filter.AGENT not in state.agents:
        tables["agents"].append(dict(id=imprint_filter.AGENT, acts_for=place, created_seq=0, retired_seq=None))
    if not state.agent_places.get(imprint_filter.AGENT):
        tables["agent_places"].append(dict(agent=imprint_filter.AGENT, place=place, added_seq=0, removed_seq=None))
    return State.from_tables(tables, seq=state.seq, seq_at={**state.seq_at, 0: 0}, meta=state.meta,
                             names=state.names)


def test_the_agent_keeps_the_state_lazy(tmp_path):
    from imprint_filter import LedgerFacts, SeqZero
    from permission_ledger import LogTimes, RowMap

    s = new_store(tmp_path, "s")
    ids = ("about-jenn", "about-lee", "plain")
    for i in ids:
        ep(s, i)
    args = plan_args(tmp_path, owner="andy", store=lambda _: s,
                     cosubjects={"about-lee": "person:lee", "about-jenn": "person:jenn"},
                     denies={"person:lee": [deny(actions=["read"], purposes=["calibration"])],
                             "person:jenn": [deny(actions=["read"], purposes=["calibration"],
                                                  audience=["place:la-county/parks"])]})   # reaches seq_at[0]
    led = args[3].ledger
    facts = LedgerFacts(led, owner="andy", now=NOW, terms=args[2])
    st = facts.state
    for name in ("subjects", "copies", "lane_notes", "collection_members"):
        assert isinstance(getattr(st, name), RowMap), name
    assert isinstance(st.seq_at, SeqZero) and isinstance(st.seq_at._inner, LogTimes)
    assert imprint_filter.AGENT in st.agents and st.agent_places[imprint_filter.AGENT]
    plain = led.state()
    assert imprint_filter._with_agent(plain, "place:home/andy")._cache is not plain._cache   # its memo is its own
    whole = _whole_with_agent(plain, "place:home/andy")
    oracle = imprint_filter.Refusals.of_state(whole, owner="andy", now=NOW, terms=args[2])
    for i in ids:
        ref = ref_of(s, i)
        for subject in ("person:lee", "person:jenn"):
            assert facts.refuses(ref, subject) == oracle.refuses(ref, subject), (i, subject)
    assert facts.refuses(ref_of(s, "about-lee"), "person:lee")
    assert not facts.refuses(ref_of(s, "about-jenn"), "person:jenn")
