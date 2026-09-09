"""CLI and MCP adapters preserve the session bridge's public contract."""

import json
import asyncio
import os
import sys
from contextlib import contextmanager

import pytest

import session_cli


SENDER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def test_mcp_caller_metadata_wins_over_inherited_process_identity(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", SENDER)
    assert session_cli.caller({"threadId": OTHER}) == OTHER
    with pytest.raises(ValueError):
        session_cli.caller({"threadId": "malformed"})


def test_cli_ask_uses_the_calling_codex_session(monkeypatch, capsys):
    monkeypatch.setenv("CODEX_THREAD_ID", SENDER)

    class Bridge:
        def ask(self, target, question, sender):
            assert (target, question, sender) == (OTHER, "What changed?", SENDER)
            return {"request_id": "receipt", "status": "queued"}

    @contextmanager
    def connected(**kwargs):
        yield Bridge()

    monkeypatch.setattr(session_cli, "connect", connected)
    assert session_cli.main(["ask", OTHER, "What changed?"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "queued"


def test_missing_mcp_identity_cannot_impersonate_an_operator(monkeypatch):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    with pytest.raises(ValueError, match="caller identity"):
        session_cli.caller({}, required=True)


def test_mcp_stdio_exposes_three_tools_without_an_identity_argument():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "session_cli", "mcp"], env=dict(os.environ))
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                listing = await client.list_tools()
                assert {tool.name for tool in listing.tools} == {"sessions_list", "session_ask", "session_result"}
                ask = next(tool for tool in listing.tools if tool.name == "session_ask")
                assert set(ask.inputSchema["properties"]) == {"target_session", "question"}
                invalid = await client.call_tool("session_result", {"request_id": "bad"})
                assert invalid.isError

    asyncio.run(check())
