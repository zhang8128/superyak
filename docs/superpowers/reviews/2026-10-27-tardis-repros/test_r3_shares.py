"""Repro: a non-owner agent's server is refused the ledger's rules but `shares` lists every placement."""
import server
import sharing
from storage import Storage
from tests.permissions_support import keep_world  # noqa: F401
from tests.test_recall_margins import engram_server_env  # noqa: F401


def test_shares_lists_owner_placements_to_a_non_owner_agent(keep_world):
    assert server._agent_ref() == "agent:ph-coordinator"
    assert server.permissions(focus="rules") == {"error": "only agents acting for the ledger owner can read this"}
    src = Storage(str(keep_world.root / "andy-src.db"))
    src.add_episode(id="jenn-1", session_id=None, content="Jenn: [condition] test positive, 2026-10-01", episode_type="x")
    src.conn.commit()
    with server._published_house_storage() as (_p, house):
        sharing.share(source_storage=src, published_storage=house, source_id="jenn-1", layer="episode",
                      audience="group:jenn-care", reason="Jenn's [condition] result for her care group",
                      source_instance="default", source_instance_id="andy-store")
    out = server.shares()
    print(out)
    assert out["shares"][0]["reason"] == "Jenn's [condition] result for her care group"
    assert out["shares"][0]["audience"] == "group:jenn-care"
