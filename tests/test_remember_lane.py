"""Lane is derived at write time, not only from the work flag."""

from __future__ import annotations

import server
from tests.test_recall_margins import engram_server_env  # noqa: F401


def _lane(episode_id: str) -> str:
    return server._storage.get_episode(episode_id)["lane"] or "personal"


def test_project_tag_derives_work_lane(engram_server_env):
    out = server.remember(
        content="deployed the rowing tenant to staging",
        context={"project": "hyper-nimbus"},
    )
    assert _lane(out["episode_id"]) == "work"
    assert out["lane"] == "work"


def test_explicit_personal_lane_wins_over_project_tag(engram_server_env):
    out = server.remember(
        content="the reader session with Danielle tonight",
        context={"project": "reader", "lane": "personal"},
    )
    assert _lane(out["episode_id"]) == "personal"
    assert "lane" not in out


def test_work_flag_still_derives_work_lane(engram_server_env):
    out = server.remember(content="client review answers pending", work=True)
    assert _lane(out["episode_id"]) == "work"


def test_explicit_personal_lane_overrides_work_flag(engram_server_env):
    out = server.remember(
        content="personal note written during a work session",
        context={"lane": "personal"},
        work=True,
    )
    assert _lane(out["episode_id"]) == "personal"
    assert "lane" not in out


def test_no_signal_stays_personal(engram_server_env):
    out = server.remember(content="a quiet thought with no project attached")
    assert _lane(out["episode_id"]) == "personal"


def test_core_with_project_tag_stays_personal(engram_server_env):
    out = server.remember(
        content="the day the contract for Region 1 came through",
        context={"project": "guyana"},
        core=True,
    )
    assert _lane(out["episode_id"]) == "personal"


def test_pure_derivation_rules():
    assert server._derive_lane(False, False, False, {"project": "x"}) == "work"
    assert (
        server._derive_lane(
            False, False, False, {"project": "x", "lane": "personal"}
        )
        == "personal"
    )
    assert server._derive_lane(True, False, False, None) == "work"
    assert (
        server._derive_lane(
            True, False, False, {"lane": "personal", "project": "x"}
        )
        == "personal"
    )
    assert server._derive_lane(True, True, False, None) == "personal"
    assert server._derive_lane(True, False, True, None) == "personal"
    assert server._derive_lane(False, True, False, {"project": "x"}) == "personal"
    assert server._derive_lane(False, False, True, {"project": "x"}) == "personal"
    assert server._derive_lane(False, False, False, {"project": ""}) == "personal"


def test_default_config_stores_personal_for_untagged_episode(engram_server_env):
    server._init()
    assert server._config.memory.default_lane == "personal"
    out = server.remember(content="an untagged note in a default instance")
    assert _lane(out["episode_id"]) == "personal"


def test_work_default_lane_stores_work_for_untagged_episode(engram_server_env):
    server._init()
    server._config.memory.default_lane = "work"
    out = server.remember(content="an untagged note in a work-only instance")
    assert _lane(out["episode_id"]) == "work"
    assert out["lane"] == "work"


def test_work_default_lane_is_overridden_by_personal_context(engram_server_env):
    server._init()
    server._config.memory.default_lane = "work"
    out = server.remember(
        content="something personal written in a work instance",
        context={"lane": "personal"},
    )
    assert _lane(out["episode_id"]) == "personal"


def test_work_default_lane_never_makes_core_episode_work(engram_server_env):
    server._init()
    server._config.memory.default_lane = "work"
    out = server.remember(
        content="a formative moment recorded in a work instance", core=True
    )
    assert _lane(out["episode_id"]) == "personal"


def test_pure_derivation_with_default_lane():
    assert (
        server._derive_lane(
            False, False, False, None, default_lane="work"
        )
        == "work"
    )
    assert (
        server._derive_lane(
            False, False, False, None, default_lane="personal"
        )
        == "personal"
    )
    assert (
        server._derive_lane(
            False,
            False,
            False,
            {"lane": "personal"},
            default_lane="work",
        )
        == "personal"
    )
    assert (
        server._derive_lane(False, True, False, None, default_lane="work")
        == "personal"
    )
    assert (
        server._derive_lane(False, False, True, None, default_lane="work")
        == "personal"
    )
    assert (
        server._derive_lane(
            False,
            False,
            False,
            {"project": "x"},
            default_lane="personal",
        )
        == "work"
    )
