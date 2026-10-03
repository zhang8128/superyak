"""Ask a Superyak lighthouse for an account, wait for approval, then redeem it.

Standard library only, so a fresh clone needs nothing but Python 3:

    python3 peer/scripts/request_access.py https://smart.example.ts.net

Progress is saved in ~/.superyak/access-request.json, so rerunning resumes.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

STATE = Path.home() / '.superyak' / 'access-request.json'
POLL_SECONDS = 30


def call(base, method, path, data=None):
    request = urllib.request.Request(
        base + path,
        method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={'content-type': 'application/json', 'origin': base},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            message = json.load(error).get('error', error.reason)
        except ValueError:
            message = error.reason
        raise SystemExit(f'{error.code}: {message}') from None


def save(state):
    STATE.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(state, stream, indent=2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('lighthouse', help='Lighthouse URL, e.g. https://smart.example.ts.net')
    args = parser.parse_args(argv)
    base = args.lighthouse.rstrip('/')
    if urllib.parse.urlsplit(base).scheme != 'https':
        raise SystemExit('Use the lighthouse HTTPS address')

    state = json.loads(STATE.read_text()) if STATE.exists() else None
    if state and state.get('lighthouse') != base:
        raise SystemExit(f'{STATE} belongs to {state.get("lighthouse")}; remove it to ask a different lighthouse')
    if not state:
        name = input('Your name: ').strip()
        contact = input('How Andy can recognise you (email or phone): ').strip()
        note = input('A note for Andy (optional): ').strip()
        created = call(base, 'POST', '/api/access-requests', {'name': name, 'contact': contact, 'note': note})
        state = {'lighthouse': base, 'id': created['id'], 'secret': created['secret'], 'name': name}
        save(state)
        print('Request sent. Let Andy know; he approves it from Accounts on the lighthouse.')

    if 'token' not in state:
        query = '/api/access-requests/' + urllib.parse.quote(state['id']) + '?' + urllib.parse.urlencode({'secret': state['secret']})
        while True:
            status = call(base, 'GET', query)
            if status.get('token'):
                state['token'] = status['token']
                save(state)
                break
            if status['status'] != 'pending':
                STATE.unlink()
                raise SystemExit(f'Your request was {status["status"]}. Run this again to ask anew.')
            print(f'Waiting for approval… (checking every {POLL_SECONDS} seconds; Ctrl-C to stop and resume later)')
            time.sleep(POLL_SECONDS)

    print('Approved. Choose how you sign in.')
    username = input('Username (lowercase letters, digits, . _ -): ').strip()
    while True:
        password = getpass.getpass('Password (12+ characters): ')
        if password == getpass.getpass('Repeat password: '):
            break
        print('Those did not match.')
    call(base, 'POST', '/api/invitations/redeem', {'token': state['token'], 'username': username, 'name': state['name'], 'password': password})
    STATE.unlink()
    print(f'Your account is ready. Sign in at {base}/ as {username}.')


if __name__ == '__main__':
    sys.exit(main())
