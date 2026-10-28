"""Every touch an imprint gives is one its source gives (store-copy spec I 16, "Recall rows"; the trail spec's I6, XS1)."""
import pytest
from imprint import build, make_plan
from tests.imprint_support import (HOME, exactly_one_target_answers, iso_of, kept_recalls, mixed_lane_recall_store,
                                   order_within_recalls, plan_args, recalls_of, touches_from)


@pytest.mark.parametrize("fixture", ["nothing_at_or_after_t1", "as_of_t1_nothing_at_t1"])
def test_every_package_touch_is_a_source_touch(tmp_path, fixture):
    store, t1 = mixed_lane_recall_store(tmp_path, fixture)   # route; a mixed-lane recall; a used recall of one target
    built = build(make_plan(*plan_args(tmp_path, store=lambda _: store, route=True, until=iso_of(t1))).id,
                  home=HOME(tmp_path), now=t1)
    as_of = t1 if fixture == "as_of_t1_nothing_at_t1" else t1 + 7200
    pkg, src = touches_from(built.dir / "imprint.db", as_of), touches_from(store.db_path, as_of)
    assert {t.kind for t in pkg} == {"wrote", "cited"} and any(t.suggested for t in pkg)   # not vacuous
    assert any(t.suggested is False and t.kind == "cited" for t in pkg)
    assert len(src) > len(pkg)                       # the mixed-lane recall's touch stays home
    for t in pkg:
        twin = [s for s in src if (s.session, s.memory, s.kind, s.time) == (t.session, t.memory, t.kind, t.time)]
        assert twin and (not t.suggested or twin[0].suggested)
    assert order_within_recalls(pkg) == order_within_recalls(src, only=recalls_of(pkg))
    assert len(order_within_recalls(pkg)) >= 3
    assert exactly_one_target_answers(built.dir / "imprint.db") == exactly_one_target_answers(
        store.db_path, only=kept_recalls(built))
