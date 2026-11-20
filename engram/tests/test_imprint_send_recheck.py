"""Imprint spec revision 9 (2026-11-20-imprint-send-rechecks-ledger.md, approved at draft 4; board item
fix:imprint-send-rechecks-ledger): each send asks the owner's ledger the build's questions again. Each test here fails
on the code before the change."""
import json
import shutil

import pytest

from imprint import build, make_plan, read_plan
from imprint_filter import PlanRefused
from permission_ledger import Ledger, ledger_path
from tests.imprint_support import EH, HOME, NOW, plan_args

ELSEWHERE = "The permissions ledger this plan read is not the one here. Run the plan again."
BEFORE_9 = "This plan was saved before each send asked the permissions ledger again. Run the plan again."


def _saved(tmp_path, plan):
    return HOME(tmp_path) / "imprints" / "plans" / f"{plan.id}.json"


# ---- T1: the plan records the ledger it read ----------------------------------------------------------------------

def test_the_plan_records_the_ledger_it_read(tmp_path):
    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"})
    plan = make_plan(*args)
    saved = json.loads(_saved(tmp_path, plan).read_text())
    assert saved["ledger"] == str(ledger_path(EH(tmp_path)).resolve())


def test_a_plan_with_no_ledger_records_none(tmp_path):
    plan = make_plan(*plan_args(tmp_path, owner="andy", ledger=None))
    saved = json.loads(_saved(tmp_path, plan).read_text())
    assert "ledger" in saved and saved["ledger"] is None


@pytest.mark.parametrize("step", ["read", "build"])
@pytest.mark.parametrize("where", ["another", "none"])
def test_read_and_build_refuse_another_ledger(tmp_path, step, where):
    plan = make_plan(*plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"}))
    other = tmp_path / "other"
    other.mkdir()
    if where == "another":
        Ledger.create(other, "andy", now=NOW).close()
    with pytest.raises(PlanRefused, match=ELSEWHERE):
        if step == "read":
            read_plan(plan.id, home=HOME(tmp_path), engram_home=other, limit=99)
        else:
            build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=other)


@pytest.mark.parametrize("step", ["read", "build"])
def test_read_and_build_refuse_a_ledger_that_appeared(tmp_path, step):
    plan = make_plan(*plan_args(tmp_path, owner="andy", ledger=None))
    Ledger.create(EH(tmp_path), "andy", now=NOW).close()
    with pytest.raises(PlanRefused, match=ELSEWHERE):
        if step == "read":
            read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
        else:
            build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))


@pytest.mark.parametrize("step", ["read", "build"])
def test_a_plan_saved_before_revision_9_refuses(tmp_path, step):
    plan = make_plan(*plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"}))
    path = _saved(tmp_path, plan)
    saved = json.loads(path.read_text())
    del saved["ledger"]
    path.write_text(json.dumps(saved))
    with pytest.raises(PlanRefused, match=BEFORE_9):
        if step == "read":
            read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
        else:
            build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))


def test_the_same_ledger_reads_and_builds(tmp_path):
    plan = make_plan(*plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"}))
    read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
    build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))


# ---- T2: the build writes the semantics' sources ------------------------------------------------------------------

def _built(tmp_path, **kw):
    plan = make_plan(*plan_args(tmp_path, owner="andy", **kw))
    return build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))


def test_the_build_writes_each_shipped_semantics_sources_with_their_lanes(tmp_path):
    built = _built(tmp_path, cosubjects={"e2": "person:jenn"})
    path = built.dir / "sources.json"
    assert json.loads(path.read_text()) == [["s1", "e1", "work"]]
    assert path.read_text().startswith("[\n") and (path.stat().st_mode & 0o777) == 0o600     # R30's form


def test_the_build_writes_sources_json_with_no_semantic(tmp_path):
    built = _built(tmp_path, cosubjects={"e2": "person:jenn"}, exclude=("s1",))
    assert json.loads((built.dir / "sources.json").read_text()) == []


# ---- T3: each send asks the ledger again ---------------------------------------------------------------------------

from dataclasses import replace  # noqa: E402

from imprint import SendRefused, recheck  # noqa: E402
from permission_ledger import LedgerUnreadable  # noqa: E402
from tests.imprint_support import (_ins, _put, add_subject, deny, iid, link_copies, ref_of,  # noqa: E402
                                   retire, write_denies)

STAYS = r"Your permissions changed since this imprint was built: \d+ memor(y|ies) would now stay home\. Nothing was sent\."


def _made(tmp_path, owner="andy", layers=None, **kw):
    """A plan built, with the fixture's writable ledger kept open for the change made after the build."""
    args = list(plan_args(tmp_path, owner=owner, **kw))
    if layers is not None:
        args[1] = replace(args[1], layers=frozenset(layers))
    plan = make_plan(*args)
    built = build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    (built.dir / "checked.json").unlink(missing_ok=True)           # the build's own check (T4), set aside here
    return args, plan, built


def _ref(args, id, layer="episode"):
    return f"mem:{args[3].source_id}/{layer}/{id}"


def _check(tmp_path, plan):
    return recheck(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path))


def test_a_deny_after_the_build_stops_the_send(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    write_denies(args[3].ledger, "person:jenn", deny())
    with pytest.raises(PlanRefused, match=STAYS) as e:
        _check(tmp_path, plan)
    assert not isinstance(e.value, SendRefused) and "jenn" not in str(e.value)
    assert not (built.dir / "checked.json").exists() and not (built.dir / "refused.json").exists()


def test_a_deny_after_the_request_writes_the_refusal_for_the_agent(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    (built.dir / "send.json").write_text("{}")
    write_denies(args[3].ledger, "person:jenn", deny())
    with pytest.raises(SendRefused):
        _check(tmp_path, plan)
    refused = json.loads((built.dir / "refused.json").read_text())
    assert refused["imprint_id"] == built.imprint_id and refused["count"] >= 1 and isinstance(refused["at"], int)
    assert (built.dir / "refused.json").stat().st_mode & 0o777 == 0o600 and not (built.dir / "checked.json").exists()


def test_an_ordinary_append_passes_and_stamps(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    _put(args[3].ledger, "fixture-x", "a", {"insert": []})
    stamp = _check(tmp_path, plan)
    saved = json.loads((built.dir / "checked.json").read_text())
    assert saved == stamp and saved["imprint_id"] == built.imprint_id and isinstance(saved["seq"], int)
    assert isinstance(saved["at"], int) and (built.dir / "checked.json").stat().st_mode & 0o777 == 0o600


def _bound(led, ref):
    for i in range(8):
        add_subject(led, ref, f"person:p{i}")


@pytest.mark.parametrize("change", ["retired", "bound", "re-lane", "new co-subject"])
def test_each_question_stops_the_send(tmp_path, change):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    led = args[3].ledger
    if change == "retired":
        retire(led, "person:jenn")
    elif change == "bound":
        _bound(led, _ref(args, "e1"))
    elif change == "re-lane":
        _put(led, "fixture-lane", "e1", {"insert": [_ins("lane_notes", object=_ref(args, "e1"), lane="personal",
                                                           at=NOW, seq="@seq")]})
    else:
        add_subject(led, _ref(args, "e2"), "person:lee")              # e2 had none: on a home plan, no deny
    with pytest.raises(PlanRefused, match=STAYS):
        _check(tmp_path, plan)


def test_any_co_subject_on_a_plan_that_leaves_home_stops_the_send(tmp_path):
    args, plan, built = _made(tmp_path, owner="sam", cosubjects={"e1": "person:jenn"})
    add_subject(args[3].ledger, _ref(args, "e2"), "person:lee")
    with pytest.raises(PlanRefused, match=STAYS):
        _check(tmp_path, plan)


def test_a_co_subject_up_a_copies_chain_is_asked(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    led = args[3].ledger
    far = "mem:" + "0" * 32 + "/episode/far"
    link_copies(led, [_ref(args, "e2"), far])
    add_subject(led, far, "person:jenn")
    write_denies(led, "person:jenn", deny())
    with pytest.raises(PlanRefused, match=STAYS):
        _check(tmp_path, plan)


def test_a_semantics_source_episode_is_asked(tmp_path):
    args, plan, built = _made(tmp_path, layers=("semantic",), cosubjects={"e2": "person:jenn"})
    assert json.loads((built.dir / "sources.json").read_text()) == [["s1", "e1", "work"]]
    add_subject(args[3].ledger, _ref(args, "e1"), "person:lee")
    write_denies(args[3].ledger, "person:lee", deny())
    with pytest.raises(PlanRefused, match=r"1 memory would now stay home"):
        _check(tmp_path, plan)


def test_a_ledger_gone_since_the_build_refuses(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    args[3].ledger.close()
    path = ledger_path(EH(tmp_path))
    path.rename(path.with_name("moved.db"))
    with pytest.raises(PlanRefused, match="The permissions ledger this plan read is gone. Nothing was sent."):
        _check(tmp_path, plan)


def test_a_ledger_that_appeared_since_the_build_is_asked(tmp_path):
    args, plan, built = _made(tmp_path, ledger=None)
    from tests.imprint_support import ledger as make_ledger
    from storage import Storage

    store = Storage(str(args[0]))
    led = make_ledger(EH(tmp_path), owner="andy", store=store, cosubjects={"e1": "person:jenn"},
                      denies={"person:jenn": [deny()]})
    led.close()
    store.close()
    with pytest.raises(PlanRefused, match=STAYS):
        _check(tmp_path, plan)


def test_a_package_gone_after_its_request_is_left_to_the_agent(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    (built.dir / "send.json").write_text("{}")
    (built.dir / "checked.json").write_text("{}")
    built.dir.chmod(0o700)
    (built.dir / "imprint.db").unlink()
    assert _check(tmp_path, plan) is None
    assert not (built.dir / "checked.json").exists()


def test_a_package_gone_with_no_request_refuses(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    (built.dir / "imprint.db").unlink()
    with pytest.raises(PlanRefused, match="Run the plan again"):
        _check(tmp_path, plan)


def test_stale_stamps_go_before_the_check(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    (built.dir / "checked.json").write_text('{"imprint_id": "x", "at": 0, "seq": 0}')
    (built.dir / "refused.json").write_text('{"imprint_id": "x", "at": 0, "count": 1}')
    write_denies(args[3].ledger, "person:jenn", deny())
    with pytest.raises(PlanRefused):
        _check(tmp_path, plan)
    assert not (built.dir / "checked.json").exists() and not (built.dir / "refused.json").exists()


def test_an_imprint_built_before_revision_9_refuses(tmp_path):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})
    (built.dir / "sources.json").unlink()
    with pytest.raises(PlanRefused, match="built before each send asked the permissions ledger again"):
        _check(tmp_path, plan)


def test_a_ledger_that_changes_during_the_check_says_nothing_was_sent(tmp_path, monkeypatch):
    args, plan, built = _made(tmp_path, cosubjects={"e1": "person:jenn"})

    def changed(self, *a, **k):
        raise LedgerUnreadable("permissions.db: the ledger changed during this read; retry")
    monkeypatch.setattr(Ledger, "state", changed)
    with pytest.raises(PlanRefused, match="changed while it was read; nothing was sent"):
        _check(tmp_path, plan)


# ---- T4: build checks too, and the CLI's exit 5 -----------------------------------------------------------------

import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import imprint  # noqa: E402

ENGRAM = Path(__file__).resolve().parent.parent


def test_a_fresh_build_stamps_its_check(tmp_path):
    plan = make_plan(*plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"}))
    built = build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    assert json.loads((built.dir / "checked.json").read_text())["imprint_id"] == built.imprint_id


def test_build_if_needed_asks_again(tmp_path):
    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"})
    plan = make_plan(*args)
    build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    write_denies(args[3].ledger, "person:jenn", deny())
    with pytest.raises(PlanRefused, match=STAYS):
        build(plan.id, home=HOME(tmp_path), now=NOW, if_needed=True, engram_home=EH(tmp_path))


def test_a_deny_marked_during_the_build_stops_it_before_any_request(tmp_path, monkeypatch):
    from imprint_filter import LedgerFacts

    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"})
    plan = make_plan(*args)
    real, fired = LedgerFacts.close, []

    def close(self):
        if not fired:                               # the build's own closing read: a writer's deny just before
            fired.append(1)
            code = ("import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; "
                    "from permission_ledger import Ledger; from tests.imprint_support import write_denies, deny; "
                    "led = Ledger.open(Path(sys.argv[2])); write_denies(led, 'person:jenn', deny()); led.close()")
            subprocess.run([sys.executable, "-I", "-c", code, str(ENGRAM), str(EH(tmp_path))], check=True, cwd=ENGRAM)
        return real(self)
    monkeypatch.setattr(LedgerFacts, "close", close)
    with pytest.raises(PlanRefused, match=STAYS):
        build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    assert fired and not list((HOME(tmp_path) / "imprints").glob("*/checked.json"))


def test_the_cli_exits_5_when_a_request_is_out(tmp_path):
    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:jenn"})
    plan = make_plan(*args)
    built = build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    (built.dir / "send.json").write_text("{}")
    write_denies(args[3].ledger, "person:jenn", deny())
    done = subprocess.run([sys.executable, str(ENGRAM / "imprint.py"), "build", "--plan", plan.id[:8], "--if-needed",
                           "--superyak-home", str(HOME(tmp_path)), "--engram-home", str(EH(tmp_path))],
                          cwd=ENGRAM, capture_output=True, text=True, timeout=300)   # build re-execs (R26)
    assert done.returncode == imprint.EXIT_SEND_REFUSED == 5, done.stderr
    assert "would now stay home" in done.stderr and (built.dir / "refused.json").is_file()
