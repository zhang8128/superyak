"""The wormhole: relays explicit @persona mentions in bridged rooms to Stanley's aDNA lattice as
coordination memos in Station.aDNA, and memos addressed to the station back into rooms. No model runs
here: text is only copied, redacted on the way out and quoted without '@' on the way in."""
import datetime
import hashlib
import logging
import time
from superyak_team.teamlib import redact
from . import memos
from .station import StationError, label, read_json, write_private
from .vault import INBOX, OUTBOUND, RECEIPTS

log = logging.getLogger('superyak.wormhole')
POLL_SECONDS = 30
DEFAULT_ROOM = 'Gamma Quadrant'
SKIP_AUTHORS = ('odo',)
HELP_MAX = 2000


def _digest(name):
    return hashlib.sha256(name.encode()).hexdigest()[:16]


def _clean(value):
    """label() of a persona-map string, or '' for anything that is not a string or has nothing printable."""
    if not isinstance(value, str) or not any(c.isprintable() and not c.isspace() and c != '`' for c in value):
        return ''
    return label(value)


def normalize_personas(personas):
    """{name: {'persona', 'vault'}} from a persona map of unknown quality: entries are
    {'persona': str, 'vault': str} or a bare vault string (persona = the key, title-cased); anything else is
    dropped, and the strings are collapsed to one short line so they cannot break out of a post."""
    out = {}
    for key, entry in (personas.items() if isinstance(personas, dict) else ()):
        if not isinstance(key, str):
            continue
        if isinstance(entry, str):
            persona, vault = _clean(key.title()), _clean(entry)
        elif isinstance(entry, dict):
            persona, vault = _clean(entry.get('persona')), _clean(entry.get('vault'))
        else:
            continue
        if key.strip() and persona and vault:
            out[key.strip().lower()] = {'persona': persona, 'vault': vault}
    return out


class Wormhole:
    def __init__(self, client, vault, personas, state_path, *, owners, today=datetime.date.today, clock=time.time):
        if isinstance(owners, str):
            raise TypeError('owners is a collection of usernames, not one string')
        self.client, self.vault, self.personas = client, vault, normalize_personas(personas)
        self.owners = frozenset(owners)  # only rooms these people own are bridged; none means no room is
        self.state_path, self.today, self.clock = state_path, today, clock
        self.state = read_json(state_path, {}) or {}
        for key, default in (('rooms', {}), ('sent', {}), ('memos', {}), ('relayed', []), ('receipts', [])):
            self.state.setdefault(key, default)
        # Files handled, never cut: the folders only grow, and a forgotten name would be handled again.
        self.done = {key: set(self.state[key]) for key in ('relayed', 'receipts')}
        self.me = None

    def save(self):
        write_private(self.state_path, self.state)

    def _mark(self, key, value):
        if value not in self.done[key]:
            self.done[key].add(value)
            self.state[key].append(value)
        self.save()

    def cycle(self):
        if self.me is None:
            self.me = self.client.me()
        self.vault.recover()  # a crash may have left a memo uncommitted; sync() needs a clean index
        self.vault.sync()
        rooms = [r for r in self.client.rooms() if ':' not in r['id']]
        if 'since' not in self.state:
            # Station time of the bridge's first run: what was said before it is history, never replayed.
            stamps = [t for r in rooms for t in (r.get('created'), r.get('last_activity')) if isinstance(t, (int, float))]
            self.state['since'] = max(stamps) if stamps else self.clock()
            self.save()
        rooms = self._bridged(rooms)
        posted = self._outbound(rooms)
        self.vault.publish()
        return posted + self._inbound(rooms) + self._receipts(rooms)

    def _bridged(self, rooms):
        """The rooms the bridge may read and post in, with their messages and members: current rooms (adding members
        makes a new linked room, and the one it replaces keeps Wormhole) whose owner is one of `owners` (anyone can
        make a room of their own and put Wormhole in it)."""
        replaced = {r.get('linked_room_id') for r in rooms}
        bridged = []
        for summary in rooms:
            if summary['id'] in replaced:
                continue
            room = self.client.room(summary['id'])
            owner = next((m for m in room.get('members', []) if m['id'] == room.get('owner_id')), {})
            if owner.get('username') in self.owners:
                bridged.append(room)
        return bridged

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
        for room in rooms:
            members = {m['id']: m for m in room.get('members', [])}
            ids = [m['id'] for m in room['messages']]
            seen = self.state['rooms'].get(room['id'])
            if seen and seen in ids:
                start = ids.index(seen) + 1
            else:
                # First sight of the room (or a cursor the station no longer lists): skip what was said before the
                # bridge started, relay everything after. A newly bridged room has no earlier history, so the
                # first message typed in it counts.
                start = self._after_since(room['messages'])
                if seen != (ids[start - 1] if start else ''):
                    self.state['rooms'][room['id']] = ids[start - 1] if start else ''
                    self.save()
            for message in room['messages'][start:]:
                posted += self._relay_out(room, members, message)
                self.state['rooms'][room['id']] = message['id']
                self.save()
        return posted

    def _after_since(self, messages):
        """How many leading messages were written at or before the bridge's first run."""
        since, start = self.state['since'], 0
        for index, message in enumerate(messages):
            when = message.get('created')
            if isinstance(when, (int, float)) and when <= since:
                start = index + 1
        return start

    def _orphan(self, message_id, persona):
        """A memo of ours for this message and persona that was committed before a crash kept the state from
        recording it. Only we write outbound/ (the vault gate keeps the lattice out), so a file the state does not
        know is ours."""
        for name in self.vault.files(OUTBOUND):
            if name in self.state['memos'] or not self.vault.tracked(OUTBOUND, name):
                continue  # only committed memos: an uncommitted file would never be published
            fields, _ = memos.parse_memo(self.vault.read(OUTBOUND, name))
            if fields.get('station_message') == message_id and str(fields.get('to_persona') or '').lower() == persona.lower():
                return name
        return None

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
                file_name = self._orphan(message['id'], target['persona'])
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
        """Each persona a person can mention: the handle they type, then its label and vault, as posted ('@' is
        always written '(at)', so the bounds hold for the text that is really posted)."""
        reachable = sorted((f'@{handle} {p["persona"]} ({p["vault"]})'.replace('@', '(at)')
                            for handle, p in self.personas.items() if memos.mentioned('@' + handle) == [handle]), key=str.casefold)
        if not reachable:
            return 'No aDNA personas are configured for the wormhole yet.'
        more = f', and {len(reachable) - 40} more' if len(reachable) > 40 else ''
        text = 'Through the wormhole I can reach: ' + ', '.join(reachable[:40]) + more + '.'
        if len(text) > HELP_MAX:
            text = text[:HELP_MAX - 5].rsplit(', ', 1)[0] + ', ...'
        return text

    def _inbound(self, rooms):
        member_rooms = {r['id'] for r in rooms}  # bridged rooms only: every route below must end in one
        gamma = [r for r in rooms if r.get('title') == DEFAULT_ROOM]
        default = max(gamma, key=lambda r: r.get('last_activity') or 0)['id'] if gamma else None
        posted = 0
        for name in self.vault.files(INBOX):
            if name in self.done['relayed'] or not name.endswith('.md'):
                continue
            fields, body = memos.parse_memo(self.vault.read(INBOX, name))
            if not memos.addressed_to_station(fields):
                log.info('skipped %s: not addressed to %s', name, memos.STATION_VAULT)  # vault.files() names are one plain line
                self._mark('relayed', name)
                continue
            reply_to = str(fields.get('in_reply_to') or '')
            room = (self.state['memos'].get(reply_to) or {}).get('room')
            if room not in member_rooms:
                station_room = fields.get('station_room')
                # front matter is lattice-written: a list value must not wedge every later memo
                room = station_room if isinstance(station_room, str) and station_room in member_rooms else default
            if room is None:
                continue  # no bridged Gamma Quadrant yet: keep the memo for a later cycle
            posted += self._post(room, memos.inbound_post(fields, body, name), f'wormhole-in-{_digest(name)}')
            if reply_to in self.state['memos'] and reply_to not in self.done['receipts']:
                self._mark('receipts', reply_to)  # an answer is also a read receipt
            self._mark('relayed', name)
        return posted

    def _receipts(self, rooms):
        bridged, posted = {r['id'] for r in rooms}, 0
        for name in self.vault.files(RECEIPTS):
            info = self.state['memos'].get(name)
            if info is None or name in self.done['receipts']:
                continue
            if info['room'] not in bridged:
                continue  # its room was replaced or unbridged: keep the receipt for a later cycle
            posted += self._post(info['room'], f'{info["persona"]} ({info["vault"]}) picked up `{name}`.',
                                 f'wormhole-rcpt-{_digest(name)}')
            self._mark('receipts', name)
        return posted
