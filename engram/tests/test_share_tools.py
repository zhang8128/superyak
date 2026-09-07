from pathlib import Path

import server
from tests.test_recall_margins import engram_server_env, seed  # noqa: F401


MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _published_house(tmp_path):
    from storage import Storage
    path = tmp_path / ".engram" / "instances" / "lighthouse" / "graph.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Storage(str(path), migrations_dir=MIGRATIONS_DIR)
    store.close()
    return path


def test_share_returns_a_record_and_unshare_removes_it(engram_server_env, tmp_path):
    _published_house(tmp_path)
    seed()
    episode = server.remember(content="a thing worth sharing")

    out = server.share(
        memory_id=episode["episode_id"], audience="commons", reason="meeting me"
    )

    assert out["audience"] == "commons" and out["share_id"]
    assert any(
        item["share_id"] == out["share_id"]
        for item in server.shares(audience="commons")["shares"]
    )
    assert server.unshare(share_id=out["share_id"])["removed"] is True
    assert server.shares()["shares"] == []


def test_bad_audience_is_an_error_not_a_crash(engram_server_env, tmp_path):
    _published_house(tmp_path)
    seed()
    episode = server.remember(content="another thing")

    out = server.share(
        memory_id=episode["episode_id"], audience="everyone", reason="r"
    )

    assert "error" in out and "audience" in out["error"]


def test_sharing_an_unknown_memory_is_an_error(engram_server_env, tmp_path):
    _published_house(tmp_path)
    seed()

    out = server.share(
        memory_id="00000000-0000-4000-8000-000000000000",
        audience="commons",
        reason="r",
    )

    assert "error" in out


def test_share_tools_fail_without_creating_a_missing_published_house(
    engram_server_env, tmp_path
):
    path = tmp_path / ".engram" / "instances" / "lighthouse" / "graph.db"
    error = {"error": f"no published house at {path}"}

    assert server.share(memory_id="missing", audience="commons", reason="r") == error
    assert server.shares() == error
    assert server.unshare(share_id="missing") == error
    assert not path.exists()
    assert not path.parent.exists()
