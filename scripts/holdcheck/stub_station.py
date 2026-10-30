"""A stub `station` MCP server for the lesson-holds per-tool check: station_post and station_claim exist, post nothing,
and log each call that reaches them (so a held call shows as never arriving)."""
import json
import sys
from pathlib import Path

LOG = Path(__file__).with_name('server-calls.jsonl')
TOOLS = [
    {'name': 'station_post', 'description': 'Post a message to a room (stub: posts nothing).',
     'inputSchema': {'type': 'object', 'properties': {'room': {'type': 'string'}, 'text': {'type': 'string'}},
                     'required': ['room', 'text']}},
    {'name': 'station_claim', 'description': 'Claim a board item (stub: claims nothing).',
     'inputSchema': {'type': 'object', 'properties': {'room': {'type': 'string'}, 'key': {'type': 'string'}},
                     'required': ['room', 'key']}},
]
for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    method, ident = message.get('method'), message.get('id')
    if ident is None:
        continue  # a notification
    if method == 'initialize':
        result = {'protocolVersion': message.get('params', {}).get('protocolVersion', '2024-11-05'),
                  'capabilities': {'tools': {}}, 'serverInfo': {'name': 'station', 'version': 'stub'}}
    elif method == 'tools/list':
        result = {'tools': TOOLS}
    elif method == 'tools/call':
        with LOG.open('a') as log:
            log.write(json.dumps(message.get('params', {})) + '\n')
        result = {'content': [{'type': 'text', 'text': 'stub: nothing was posted or claimed'}]}
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': 'not found'}}), flush=True)
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': ident, 'result': result}), flush=True)
