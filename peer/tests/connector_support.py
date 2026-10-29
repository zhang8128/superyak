"""Shared fixtures for the remote connector's tests (plan 2026-10-28-remote-connector)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PUBLIC_ORIGIN = 'https://home.example'
CALLBACK = 'https://claude.ai/api/mcp/auth_callback'
PUBLIC_CLIENT = ('203.0.113.5', 50000)  # an internet address, as a Funnel request looks after the proxy


@pytest.fixture
def home(tmp_path):
    """A home with the connector on: its public origin is one of its origins, beside the test server's."""
    from superyak_peer.app import create_app
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=['http://testserver', PUBLIC_ORIGIN],
                     public_origin=PUBLIC_ORIGIN)
    return SimpleNamespace(app=app, store=app.state.store, clock=clock)


def public_client(app, **headers):
    """A public request at the public origin, with no Origin header unless one is given (Claude's servers send none)."""
    return TestClient(app, base_url=PUBLIC_ORIGIN, client=PUBLIC_CLIENT, headers=headers)
