"""Mal: a resident participant that answers rooms it belongs to.

It signs in like any participant, polls its rooms, and asks a local
`claude -p` for each reply. It holds no admin rights; the only extra it has
is the trusted local listing of pending access requests, which it announces
in the room titled "Lighthouse".
"""
import argparse
from http.cookies import SimpleCookie
import json
import logging
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

log = logging.getLogger('superyak.responder')
POLL_SECONDS = 30
HISTORY = 30
MAX_FAILURES = 3
NOTICE_ROOM = 'Lighthouse'
FALLBACK = "I couldn't answer this one. Andy can check the responder log on the lighthouse."
PERSONA = (
    'You are Mal, the resident agent on the Superyak lighthouse, a Raspberry Pi that '
    "hosts Andy's peer-to-peer workspace on the aDNA network. You are replying in a "
    'private chat room. Reply with only the message text: plain, warm, concise. '
    'You cannot run commands, edit files, grant access or change accounts; say so '
    'and suggest asking Andy when that is what someone needs. Use the aDNA tools '
    'when a question concerns the aDNA network or its published vaults.'
)


class UrllibHttp:
    """Loopback transport; keeps the session cookie even when marked Secure."""
    def __init__(self, base_url, origin=None):
        self.base, self.origin = base_url.rstrip('/'), origin or base_url.rstrip('/')
        self.cookie, self.csrf = '', ''

    def request(self, method, path, json_body=None):
        headers = {'content-type': 'application/json', 'origin': self.origin, 'x-csrf-token': self.csrf}
        if self.origin != self.base:
            # Loopback client of a server behind `serve --proxy-headers`: present as the proxy would.
            scheme, _, host = self.origin.partition('://')
            headers.update({'host': host, 'x-forwarded-proto': scheme})
        if self.cookie:
            headers['cookie'] = self.cookie
        data = None if json_body is None else json.dumps(json_body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw, cookies = response.status, response.read(), response.headers.get_all('set-cookie') or []
        except urllib.error.HTTPError as error:
            status, raw, cookies = error.code, error.read(), []
        for header in cookies:
            for morsel in SimpleCookie(header).values():
                self.cookie = f'{morsel.key}={morsel.value}'
        payload = json.loads(raw) if raw else None
        if path == '/api/login' and status == 200:
            self.csrf = payload['csrf_token']
        return status, payload


def claude_ask(mcp_config=None, model=None, timeout=300):
    """Build the default reply function: `claude -p` with no built-in tools."""
    def ask(history, title):
        transcript = '\n\n'.join(f'{m["author"]}: {m["body"]}' for m in history)
        prompt = f'Room: {title}\n\nRecent messages, oldest first:\n\n{transcript}\n\nWrite your reply to the last message.'
        command = ['claude', '-p', '--output-format', 'text', '--tools', '', '--permission-mode', 'dontAsk',
                   '--no-session-persistence', '--strict-mcp-config', '--append-system-prompt', PERSONA]
        if mcp_config:
            command += ['--mcp-config', str(mcp_config), '--allowedTools', 'mcp__adna']
        if model:
            command += ['--model', model]
        result = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=Path.home())
        reply = result.stdout.strip()
        if result.returncode or not reply:
            raise RuntimeError(f'claude exited {result.returncode}: {result.stderr.strip()[:500]}')
        return reply[:20000]
    return ask


class Responder:
    def __init__(self, http, username, password, state_path, ask, store=None):
        self.http, self.username, self.password = http, username, password
        self.state_path, self.ask, self.store = Path(state_path), ask, store
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.state.setdefault('rooms', {})
        self.state.setdefault('failures', {})
        self.state.setdefault('announced', [])
        self.me = None

    def _save(self):
        tmp = self.state_path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(self.state, stream)
        os.replace(tmp, self.state_path)

    def _call(self, method, path, body=None):
        status, data = self.http.request(method, path, body)
        if status == 401:
            self._login()
            status, data = self.http.request(method, path, body)
        if status >= 400:
            raise RuntimeError(f'{method} {path}: {status} {data}')
        return data

    def _login(self):
        status, data = self.http.request('POST', '/api/login', {'username': self.username, 'password': self.password})
        if status != 200:
            raise RuntimeError(f'login failed: {status} {data}')
        self.me = data['user']['id']

    def cycle(self):
        """One poll. Returns the number of messages posted."""
        if self.me is None:
            self._login()
        rooms = [room for room in self._call('GET', '/api/chats') if ':' not in room['id']]
        posted = self._announce(rooms)
        names = {row['id']: row['name'] for row in self._call('GET', '/api/contacts')}
        for room in rooms:
            seen = self.state['rooms'].get(room['id'], {})
            if seen.get('activity') == room['last_activity']:
                continue
            posted += self._answer(room, seen, names)
            self._save()
        return posted

    def _answer(self, summary, seen, names):
        room = self._call('GET', f'/api/chats/{summary["id"]}')
        messages = room['messages']
        cursor = seen.get('cursor')
        new = [m for m in messages if cursor is None or [m['created'], m['id']] > cursor]
        others = [m for m in new if m['author_id'] != self.me]
        record = {'activity': summary['last_activity'], 'cursor': [messages[-1]['created'], messages[-1]['id']] if messages else cursor}
        if not others:
            self.state['rooms'][room['id']] = record
            return 0
        target = others[-1]
        index = messages.index(target)
        history = [{'author': 'Mal' if m['author_id'] == self.me else names.get(m['author_id'], 'Someone'), 'body': m['body']}
                   for m in messages[max(0, index + 1 - HISTORY):index + 1]]
        try:
            reply = self.ask(history, room['title'])
        except Exception as error:  # noqa: BLE001 - any failure is retried next cycle
            failures = self.state['failures'][target['id']] = self.state['failures'].get(target['id'], 0) + 1
            log.warning('reply to %s failed (%d/%d): %s', target['id'], failures, MAX_FAILURES, error)
            if failures < MAX_FAILURES:
                return 0
            reply = FALLBACK
        self.state['failures'].pop(target['id'], None)
        sent = self._call('POST', f'/api/chats/{room["id"]}/messages', {'client_message_id': f'reply-{target["id"]}', 'body': reply})
        record['cursor'] = max(record['cursor'], [sent['created'], sent['id']])
        # Our own post changes last_activity; refetch it next cycle only if others wrote since.
        record['activity'] = max(summary['last_activity'], sent['created'])
        self.state['rooms'][room['id']] = record
        return 1

    def _announce(self, rooms):
        if self.store is None:
            return 0
        pending = [r for r in self.store.pending_access_requests() if r['id'] not in self.state['announced']]
        target = next((room for room in rooms if room['title'] == NOTICE_ROOM), None)
        if not pending or target is None:
            return 0
        for request in pending:
            body = f'{request["name"]} is asking for access. Approve or deny it under Accounts → Access requests.'
            self._call('POST', f'/api/chats/{target["id"]}/messages', {'client_message_id': f'access-{request["id"]}', 'body': body})
            self.state['announced'].append(request['id'])
        self._save()
        return len(pending)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='superyak-responder')
    parser.add_argument('--base-url', default='http://127.0.0.1:7435')
    parser.add_argument('--origin', help='Origin/Host the server expects, if not the base URL')
    parser.add_argument('--credentials', type=Path, required=True, help='JSON {"username","password"}, mode 0600')
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, help='Lighthouse data dir, for trusted access-request notices')
    parser.add_argument('--mcp-config', type=Path)
    parser.add_argument('--model')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    credentials = json.loads(args.credentials.read_text())
    store = None
    if args.data_dir:
        from .db import Store
        store = Store(args.data_dir)
    responder = Responder(UrllibHttp(args.base_url, args.origin), credentials['username'], credentials['password'],
                          args.state, claude_ask(args.mcp_config, args.model), store=store)
    while True:
        try:
            posted = responder.cycle()
            if posted:
                log.info('posted %d message(s)', posted)
        except Exception:  # noqa: BLE001 - keep the resident loop alive
            log.exception('cycle failed')
            responder.me = None
        if args.once:
            return
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
