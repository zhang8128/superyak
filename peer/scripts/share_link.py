"""Create the station's reusable Tailscale share link. Run once, on the Pi, in a terminal.

Tailscale cannot create device invites with an OAuth client, so this uses a short-lived API
access token you generate at https://login.tailscale.com/admin/settings/keys and then delete.
The token is read without echo (or from TS_API_KEY) and never saved. Standard library only."""
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

API = 'https://api.tailscale.com/api/v2'
DEFAULT_OUT = Path.home() / '.config' / 'superyak' / 'tailscale-share-url'


def device_id():
    status = json.loads(subprocess.run(['tailscale', 'status', '--self', '--json'], capture_output=True, text=True, check=True).stdout)
    return status['Self']['ID']


def create_link(token, device, opener=urllib.request.urlopen):
    request = urllib.request.Request(
        f'{API}/device/{device}/device-invites', method='POST',
        data=json.dumps([{'multiUse': True, 'allowExitNode': False}]).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    with opener(request, timeout=30) as response:
        url = json.loads(response.read())[0]['inviteUrl']
    if not url.startswith('https://login.tailscale.com/'):
        raise ValueError(f'Unexpected invite URL: {url[:80]}')
    return url


def write_private(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text + '\n')
    os.replace(tmp, path)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out = Path(argv[0]) if argv else DEFAULT_OUT
    token = os.environ.get('TS_API_KEY') or getpass.getpass('Tailscale API access token (input hidden): ')
    url = create_link(token.strip(), device_id())
    write_private(out, url)
    print(f'Share link saved to {out}. Approved requesters receive it once.')
    print('Now delete the API access token at https://login.tailscale.com/admin/settings/keys')
    return 0


if __name__ == '__main__':
    sys.exit(main())
