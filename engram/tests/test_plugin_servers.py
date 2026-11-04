"""The plugin's MCP servers start on any machine it's installed on. A server tied to one person's home directory shows
as failed at every session start everywhere else (found by Tardis's first session with the plugin, 2026-11-04)."""
import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]


def _servers():
    return json.loads((PLUGIN / '.mcp.json').read_text())['mcpServers']


def test_no_plugin_server_names_one_machines_home():
    for name, server in _servers().items():
        text = json.dumps(server)
        assert '/Users/' not in text and '/home/' not in text, f'{name} is tied to one machine: {text}'


def test_the_plugins_own_servers_stay():
    assert {'engram', 'team'} <= set(_servers())
