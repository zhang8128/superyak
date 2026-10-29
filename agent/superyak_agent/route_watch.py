"""The route watch (build:route-watch): the station's public route, checked from off the Pi by a timer on another
machine. A Pi that's down or a Funnel that's off can't report itself, so this runs elsewhere and goes in the way the
internet does: the station's hostname resolved through public DNS, TLS to Funnel's public ingress.

One run makes each check once. It posts one line to a room when a check's answer changes and one line a day that it
is still watching, so silence means healthy, not dead. It writes nothing on the station but those posts: no sign-in,
nothing that moves a cursor, and nothing that marks the ship present. Its key check is GET /api/home with the key,
which the route refuses with a 403 before any ship lookup (peer/tests/test_public_route.py,
test_the_middleware_writes_nothing_for_a_ship_key). A post names a status and, at most, a JSON error string: never a
body, never the key.

Posts that fail wait for the next run, at most PENDING_MAX of them; older ones are dropped and counted in one line
sent first. A state write that fails after a post went out sends that post again next run: a repeated line is the
cheaper failure. TLS uses the system's trust store, which SSL_CERT_FILE or SSL_CERT_DIR can add roots to; nothing
turns verification off."""
import http.client
import json
import socket
import ssl
import time
import urllib.parse
import urllib.request
import uuid

from .station import REPLACED_SEND, StationError, continued, label, read_json, write_private

SIGN_IN = (401, {'error': 'Sign in required'})
SHIP_REFUSED = (403, {'error': 'Ship keys cannot use this route'})
# (name, method, path, sends the ship key, the exact answer; a body of None takes any body)
CHECKS = (
    ('the app', 'GET', '/', False, (200, None)),
    ('health', 'GET', '/api/health', False, (200, {'ok': True})),
    ('anonymous /api/me refused', 'GET', '/api/me', False, SIGN_IN),
    ('anonymous /api/accounts refused', 'GET', '/api/accounts', False, SIGN_IN),
    ('anonymous docking poll refused', 'GET', '/api/dockings/probe', False, SIGN_IN),
    ('anonymous POST /api/dockings refused', 'POST', '/api/dockings', False, SIGN_IN),
    ('the ship key passes the route', 'GET', '/api/home', True, SHIP_REFUSED),
)
OK = 'ok'
DAY = 86400
PENDING_MAX = 10
DROPPED = 'route watch: {} older lines were dropped while the station was unreachable'
DNS = 'https://cloudflare-dns.com/dns-query'
TIMEOUT = 15


def public_address(host, opener=urllib.request.urlopen):
    """The host's first A record from public DNS (over HTTPS), not the tailnet's answer."""
    request = urllib.request.Request(f'{DNS}?{urllib.parse.urlencode({"name": host, "type": "A"})}',
                                     headers={'Accept': 'application/dns-json'})
    with opener(request, timeout=TIMEOUT) as response:
        answer = json.load(response).get('Answer') or []
    for record in answer:
        if record.get('type') == 1 and isinstance(record.get('data'), str):
            return record['data']
    raise OSError(f'public DNS has no address for {host}')


def ask(address, host, method, path, key=None, port=443):
    """One HTTPS request to `address`, verified as `host`: (status, the JSON body or None)."""
    context = ssl.create_default_context()
    conn = http.client.HTTPSConnection(host, port, timeout=TIMEOUT, context=context)
    conn.sock = context.wrap_socket(socket.create_connection((address, port), timeout=TIMEOUT), server_hostname=host)
    headers = {'Host': host, 'Origin': f'https://{host}'}
    body = None
    if method == 'POST':
        body, headers['Content-Type'] = b'{}', 'application/json'
    if key:
        headers['Authorization'] = f'Bearer {key}'
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read(65536)
    finally:
        conn.close()
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    return response.status, data


def verdict(got, expected, key=None):
    """OK, or what came back: the status and at most the JSON error string, with the ship's key cut out of it."""
    status, data = got
    if status == expected[0] and (expected[1] is None or data == expected[1]):
        return OK
    error = data.get('error') if isinstance(data, dict) else None
    if not isinstance(error, str):
        return str(status)
    return f'{status} "{label(error.replace(key, "[key]") if key else error, 60)}"'


def outage(result):
    """A failure that may be the network's: no answer, or a 5xx. Only a second in a row is reported."""
    return result != OK and not result[:3].isdigit() or result[:1] == '5'


def kind(result):
    """What a result is when runs are compared: ok, an outage of any sort, or the exact wrong answer. A route flapping
    between a timeout, a refused connection and a 503 is one outage (the Pi reviewer's should-fix)."""
    return 'outage' if outage(result) else result


def run_checks(host, key, resolve=public_address, request=ask):
    try:
        address = resolve(host)
    except Exception as error:  # noqa: BLE001 - no address is every check failing the same way
        return {name: f'no public address ({type(error).__name__})' for name, *_ in CHECKS}
    results = {}
    for name, method, path, keyed, expected in CHECKS:
        try:
            results[name] = verdict(request(address, host, method, path, key if keyed else None), expected, key)
        except Exception as error:  # noqa: BLE001 - refused, timed out, TLS: the route isn't answering
            results[name] = f'no answer ({type(error).__name__})'
    return results


def summary(results):
    failing = [name for name, result in results.items() if result != OK]
    passing = f'{len(results) - len(failing)}/{len(results)} pass'
    return passing + (f'; failing: {", ".join(failing)}' if failing else '')


def changes(results, state):
    """The lines for this run, and the results now reported. A change of kind is reported at once when it's a wrong
    HTTP answer below 500 (a running route answering wrong); any other change, the recovery to ok included, only
    when the last run's result was of the same kind."""
    reported, seen = state.get('reported'), state.get('seen') or {}
    if not isinstance(reported, dict):
        return [f'route watch: started; {summary(results)}'], dict(results)
    now_reported, lines = dict(reported), []
    for name, result in results.items():
        before = reported.get(name, OK)
        if kind(result) != kind(before) and (kind(result) not in ('outage', OK)
                                             or kind(seen.get(name, before)) == kind(result)):
            lines.append(f'{name} now {result} (was {before})')
            now_reported[name] = result
    return ([f'route watch: {"; ".join(lines)}'] if lines else []), now_reported


def run_once(config, room, state_path, client=None, now=time.time, resolve=public_address, request=ask,
             dry_run=False, out=print):
    """One run: check, decide, post, keep state. Returns the lines it posted, or in a dry run, which reads the state
    but writes none, the lines it would post."""
    host = urllib.parse.urlsplit(config['station']).hostname
    results = run_checks(host, config['key'], resolve, request)
    try:
        state = read_json(state_path, {}) or {}
    except ValueError:
        state = {}
    state = state if isinstance(state, dict) else {}
    first = not isinstance(state.get('reported'), dict)
    lines, reported = changes(results, state)
    if first:
        state['daily'] = now()  # the started line says it already
    elif now() - (state.get('daily') or 0) >= DAY:
        lines.append(f'route watch: still watching; {summary(reported)}')
        state['daily'] = now()
    if dry_run:
        for name, result in results.items():
            out(f'{"PASS" if result == OK else "FAIL"} {name}' + ('' if result == OK else f': {result}'))
        return lines
    pending = [line for line in state.get('pending') or [] if isinstance(line, str)] + lines
    dropped = state.get('dropped') if type(state.get('dropped')) is int else 0
    configured, followed = room, state.get('followed')
    if isinstance(followed, list) and len(followed) == 2 and followed[0] == configured and isinstance(followed[1], str):
        room = followed[1]  # where an earlier run followed the configured room to, so no extra 409 each run
    queue = ([DROPPED.format(dropped)] if dropped else []) + pending  # the count of lines lost goes first
    sent = 0
    for line in queue:
        try:
            try:
                client.post(room, line, f'route-watch-{uuid.uuid4().hex}')
            except StationError as error:  # the room was replaced: its lines go on in the room that continues it
                current = continued(client.rooms(), room) if error.status == 409 and error.message == REPLACED_SEND else None
                if not current or current == room:  # not a replacement, or a fork, or a continuation without this ship
                    raise
                room = current
                client.post(room, line, f'route-watch-{uuid.uuid4().hex}')
        except Exception:  # noqa: BLE001 - the station unreachable: kept for the next run
            break
        sent += 1
    left = queue[max(sent, 1 if dropped else 0):]
    dropped = 0 if dropped and sent else dropped
    over = max(0, len(left) - PENDING_MAX)  # the oldest go, and are counted
    state.update(reported=reported, seen=results, pending=left[over:], dropped=dropped + over)
    if room != configured:
        state['followed'] = [configured, room]
    else:
        state.pop('followed', None)
    write_private(state_path, state)
    return queue[:sent]
