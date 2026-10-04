"""`make dock`: request access if needed, dock this machine's ship, then install its tools.
Each run advances as far as it can within --wait seconds and prints a STATUS line, so Claude
Code can run it again until it reports `STATUS: docked`. Passwords never pass through here."""
import functools
import os
import platform
import sys
import time
from urllib.parse import quote, urlencode
import webbrowser
from .station import HOME, StationClient, StationError, read_json, write_private, write_private_text

WAITING = 3
FINAL = {'docked': 0, 'denied': 1, 'expired': 1}


def open_browser(url):
    """Open `url` where a browser window is likely. Without a display Python's webbrowser falls back to a
    console browser (lynx, w3m) that takes over the terminal this command is printing to; the URL has
    already been printed, so there is nothing to do."""
    if sys.platform in ('darwin', 'win32') or os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
        webbrowser.open(url)


class Dock:
    def __init__(self, station, door=None, ship=None, workspace=None, home=HOME, transport=None, clock=time.time,
                 sleep=time.sleep, out=functools.partial(print, flush=True), machine=None, open_url=open_browser):
        self.station, self.door = station.rstrip('/'), (door or station).rstrip('/')
        self.ship, self.workspace = ship, workspace
        self.transport, self.clock, self.sleep, self.out, self.open_url = transport, clock, sleep, out, open_url
        self.machine = machine or platform.node()
        self.config_path, self.request_path = home / 'station.json', home / 'access-request.json'
        self.docking_path, self.invitation_path = home / 'docking.json', home / 'invitation.txt'
        self._last = None

    def _client(self, base, key=None):
        return StationClient(base, key, transport=self.transport)

    def _say(self, status, message):
        if (status, message) != self._last:
            self.out(message)
            self.out(f'STATUS: {status}')
            self._last = (status, message)
        return status

    def run(self, request_fields=None, wait=540, poll=15):
        deadline = self.clock() + wait
        while True:
            status = self.step(request_fields)
            if status in FINAL or self.clock() + poll > deadline:
                return FINAL.get(status, WAITING)
            self.sleep(poll)

    def step(self, request_fields=None):
        config = read_json(self.config_path)
        if config and config.get('key'):
            try:
                self._client(self.station, config['key']).me()
                return self._say('docked', f'{config["ship_name"]} is docked at {self.station}.')
            except StationError as error:
                if error.status != 401:
                    raise
                self.config_path.unlink()
                self.out("This ship's key no longer works (it was revoked). Docking again.")
        if request_fields is not None:
            status = self._request(request_fields)
            if status != 'approved':
                return status
        if not self._reachable():
            return self._say('waiting-for-station', 'The station is not reachable yet. Install Tailscale, sign in with your own '
                             'account and accept the share link, then run make dock again.')
        self._open_invitation()
        return self._dock()

    def _request(self, fields):
        saved = read_json(self.request_path)
        door = self._client(self.door)
        if saved is None:
            created = door.request('POST', '/api/access-requests', fields)
            write_private(self.request_path, {'id': created['id'], 'secret': created['secret'], 'status': 'pending', 'name': fields['name']})
            return self._say('waiting-for-approval', 'Request sent. Andy sees it in Ops on the station. Run make dock again to check; each run waits up to 9 minutes.')
        if saved['status'] == 'pending':
            status = door.request('GET', f'/api/access-requests/{quote(saved["id"])}?secret={quote(saved["secret"])}')
            if status['status'] in ('denied', 'expired'):
                return self._say(status['status'], f'The request was {status["status"]}. Ask Andy, then delete {self.request_path} to ask again.')
            if status['status'] != 'approved':
                return self._say('waiting-for-approval', 'Still waiting for Andy to approve the request.')
            if status.get('token'):
                write_private_text(self.invitation_path, f'{self.station}/#activate?' + urlencode({'token': status['token'], 'name': saved['name']}))
            saved |= {'status': 'approved', 'share': status.get('share'), 'share_url': status.get('share_url'), 'invitation_opened': False}
            write_private(self.request_path, saved)
            share = (f'2. Accept the station share in your browser: {saved["share_url"]}' if saved.get('share_url')
                     else '2. Andy will share the Pi with you on Tailscale by hand; watch for an email from Tailscale.')
            self.out('Approved! Next:\n1. Install Tailscale (https://tailscale.com/download) and sign in with your own account.\n'
                     f'{share}\n3. Your invitation opens in the browser once the station is reachable. Choose your own username '
                     f'and password there; they never pass through Claude. (Saved privately in {self.invitation_path}.)')
            if saved.get('share_url'):
                self.open_url(saved['share_url'])
        return 'approved'

    def _open_invitation(self):
        saved = read_json(self.request_path)
        if saved and saved.get('status') == 'approved' and not saved.get('invitation_opened') and self.invitation_path.exists():
            self.open_url(self.invitation_path.read_text().strip())
            write_private(self.request_path, saved | {'invitation_opened': True})

    def _reachable(self):
        try:
            self._client(self.station).request('GET', '/api/me')
        except StationError:
            return True  # any HTTP answer (401) means the station is reachable
        except OSError:
            return False
        return True

    def _dock(self):
        client = self._client(self.station)
        pending = read_json(self.docking_path)
        if pending:
            status = client.request('GET', f'/api/dockings/{quote(pending["id"])}?secret={quote(pending["secret"])}')
            if status.get('key'):
                ship = status['ship']
                write_private(self.config_path, {'station': self.station, 'origin': None, 'ship': ship['username'], 'ship_id': ship['id'],
                                                 'ship_name': ship['name'], 'owner_id': ship['owner_id'], 'key': status['key'],
                                                 'workspace': self.workspace, 'machine': self.machine, 'created': self.clock()})
                for path in (self.docking_path, self.request_path, self.invitation_path):
                    path.unlink(missing_ok=True)
                return self._say('docked', f'{ship["name"]} is docked at {self.station}.')
            if status['status'] == 'waiting':
                return self._say('waiting-for-confirm', self._confirm_message(pending))
            self.docking_path.unlink()  # expired, or collected elsewhere: start again
        if not self.ship:
            raise SystemExit('Pass a ship name: make dock DOCK_ARGS="--ship <name>"')
        started = client.request('POST', '/api/dockings', {'ship_name': self.ship, 'machine': self.machine})
        write_private(self.docking_path, started)
        status = self._say('waiting-for-confirm', self._confirm_message(started))
        self.open_url(started['confirm_url'])  # after the code is printed, so the page can be checked against it
        return status

    def _confirm_message(self, docking):
        return (f'Confirm docking in your browser while signed in to the station: {docking["confirm_url"]}\n'
                f'Check that it shows the code {docking["code"]}. The code expires 10 minutes after it was made.')
