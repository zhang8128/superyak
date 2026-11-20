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
