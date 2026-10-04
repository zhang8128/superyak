"""The wormhole: relays explicit @persona mentions in bridged rooms to Stanley's aDNA lattice as
coordination memos in Station.aDNA, and memos addressed to the station back into rooms. No model runs
here: text is only copied, redacted on the way out and quoted without '@' on the way in."""
import datetime
import hashlib
import logging
from superyak_team.teamlib import redact
from . import memos
from .station import StationError, read_json, write_private
from .vault import INBOX, OUTBOUND, RECEIPTS

log = logging.getLogger('superyak.wormhole')
POLL_SECONDS = 30
DEFAULT_ROOM = 'Gamma Quadrant'
SKIP_AUTHORS = ('odo',)
KEPT = 5000


def _digest(name):
    return hashlib.sha256(name.encode()).hexdigest()[:16]


class Wormhole:
    def __init__(self, client, vault, personas, state_path, today=datetime.date.today):
        self.client, self.vault, self.personas = client, vault, personas
        self.state_path, self.today = state_path, today
        self.state = read_json(state_path, {}) or {}
        for key, default in (('rooms', {}), ('sent', {}), ('memos', {}), ('relayed', []), ('receipts', [])):
            self.state.setdefault(key, default)
        self.me = None

    def save(self):
        write_private(self.state_path, self.state)

    def _mark(self, key, value):
        self.state[key] = (self.state[key] + [value])[-KEPT:]
        self.save()

    def cycle(self):
        if self.me is None:
            self.me = self.client.me()
        self.vault.sync()
        rooms = [r for r in self.client.rooms() if ':' not in r['id']]
        posted = self._outbound(rooms)
        self.vault.publish()
        return posted + self._inbound(rooms) + self._receipts()

    def _post(self, room_id, text, client_message_id):
        try:
            self.client.post(room_id, text.replace('@', '(at)'), client_message_id)
            return 1
        except StationError as error:
            if error.status not in (403, 404, 409):
                raise
            log.warning('could not post %s: %s', client_message_id, error)
            return 0

    def _outbound(self, rooms):
        posted = 0
        for summary in rooms:
            room = self.client.room(summary['id'])
            members = {m['id']: m for m in room.get('members', [])}
            ids = [m['id'] for m in room['messages']]
            if room['id'] not in self.state['rooms']:
                self.state['rooms'][room['id']] = ids[-1] if ids else ''  # first sight: no history replay
                self.save()
                continue
            seen = self.state['rooms'][room['id']]
            start = ids.index(seen) + 1 if seen in ids else 0
            for message in room['messages'][start:]:
                posted += self._relay_out(room, members, message)
                self.state['rooms'][room['id']] = message['id']
                self.save()
        return posted

    def _relay_out(self, room, members, message):
        author = members.get(message['author_id'], {})
        if message['author_id'] == self.me['id'] or author.get('username') in SKIP_AUTHORS:
            return 0
        names, posted = memos.mentioned(message['body']), 0
        if 'wormhole' in names:
            posted += self._post(room['id'], self._help(), f'wormhole-help-{message["id"]}')
        for name in names:
            target = self.personas.get(name)
            if not target:
                continue
            key = f'{message["id"]}:{name}'
            file_name = self.state['sent'].get(key)
            if file_name is None:
                taken = set(self.state['memos']) | set(self.vault.files(OUTBOUND))
                file_name, text = memos.outbound_memo(
                    day=self.today(), persona=target['persona'], vault=target['vault'],
                    author=author.get('name') or 'someone', room_title=room['title'], room_id=room['id'],
                    message_id=message['id'], text=redact(message['body']), taken=taken)
                self.vault.add_outbound(file_name, text)
                self.state['sent'][key] = file_name
                self.state['memos'][file_name] = {'room': room['id'], 'persona': target['persona'], 'vault': target['vault']}
                self.save()
            posted += self._post(room['id'], f'Sent to {target["persona"]} ({target["vault"]}) as `{file_name}`.',
                                 f'wormhole-out-{message["id"]}-{name[:40]}')
        return posted

    def _help(self):
        reachable = sorted(f'{p["persona"]} ({p["vault"]})' for p in self.personas.values())
        if not reachable:
            return 'No aDNA personas are configured for the wormhole yet.'
        more = f', and {len(reachable) - 40} more' if len(reachable) > 40 else ''
        return 'Through the wormhole I can reach: ' + ', '.join(reachable[:40]) + more + '.'

    def _inbound(self, rooms):
        member_rooms = {r['id'] for r in rooms}
        gamma = [r for r in rooms if r.get('title') == DEFAULT_ROOM]
        default = max(gamma, key=lambda r: r.get('last_activity') or 0)['id'] if gamma else None
        posted = 0
        for name in self.vault.files(INBOX):
            if name in self.state['relayed'] or not name.endswith('.md'):
                continue
            fields, body = memos.parse_memo(self.vault.read(INBOX, name))
            if not memos.addressed_to_station(fields):
                self._mark('relayed', name)
                continue
            reply_to = str(fields.get('in_reply_to') or '')
            room = (self.state['memos'].get(reply_to) or {}).get('room')
            if room not in member_rooms:
                station_room = fields.get('station_room')
                # front matter is lattice-written: a list value must not wedge every later memo
                room = station_room if isinstance(station_room, str) and station_room in member_rooms else default
            if room is None:
                continue  # no Gamma Quadrant yet: keep the memo for a later cycle
            posted += self._post(room, memos.inbound_post(fields, body, name), f'wormhole-in-{_digest(name)}')
            if reply_to in self.state['memos'] and reply_to not in self.state['receipts']:
                self._mark('receipts', reply_to)  # an answer is also a read receipt
            self._mark('relayed', name)
        return posted

    def _receipts(self):
        posted = 0
        for name in self.vault.files(RECEIPTS):
            info = self.state['memos'].get(name)
            if info is None or name in self.state['receipts']:
                continue
            posted += self._post(info['room'], f'{info["persona"]} ({info["vault"]}) picked up `{name}`.',
                                 f'wormhole-rcpt-{_digest(name)}')
            self._mark('receipts', name)
        return posted
