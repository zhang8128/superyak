"""The mention watcher: one Claude run at a time; the watcher, not the agent, posts replies."""
import json
import logging
import subprocess
import time
from superyak_team.teamlib import redact
from .runs import RunTimeout
from .station import MESSAGE_LIMIT, StationError, describe, fence_message, label, read_json, write_private

log = logging.getLogger('superyak.agent')
POLL_SECONDS = 30
HISTORY = 30
HISTORY_CHARS = 2000  # each earlier message; the mentioning message, the request, is never cut
MAX_FAILURES = 3
SHIP_EXCHANGES_PER_HOUR = 5
ANSWERED_KEPT = 500
NOTICE_ROOM = 'Ops'
FALLBACK = "I couldn't answer this one. My owner can check the watcher log on this machine."
TIMEOUT_NOTE = 'This took longer than my time limit, so I stopped. Try a smaller request.'
UNKNOWN = {'id': None, 'username': 'unknown', 'name': 'someone', 'kind': 'unknown', 'owner_id': None}


def build_prompt(room, mention, ship, mode):
    members = {m['id']: m for m in room.get('members', [])}
    messages, ids = room['messages'], [m['id'] for m in room['messages']]
    end = ids.index(mention['message_id']) + 1 if mention['message_id'] in ids else len(messages)
    quoted = [fence_message(members.get(m['author_id']), m['body'], MESSAGE_LIMIT if m['id'] == mention['message_id'] else HISTORY_CHARS)
              for m in messages[max(0, end - HISTORY):end]]
    author = mention['author']
    if mode == 'build':
        task = ('You are in builder mode, in a fresh git worktree of the repository. Make the change the last message asks '
                'for, run the relevant tests, and end with a short summary of what you changed. Do not commit or push; the '
                'watcher commits your work on its own branch.')
    else:
        task = ('You are in read-only mode: you can read and search the repository and use the aDNA tools, but '
                f'you cannot run commands or change files. If the request needs changes, say what you would do and that '
                f'{label(author["name"])} can ask the ship\'s owner.')
    return (f'Room: {label(room["title"])}\n\nRecent messages, oldest first:\n\n' + '\n\n'.join(quoted) +
            f'\n\nThe last message, from {describe(author)}, mentions you (@{ship}). {task}\n')


def format_reply(result):
    if not result.branch:
        return result.reply
    lines = [result.reply, '', f'Branch `{result.branch}`, commit {result.commit[:9]} (not pushed).']
    if result.stat:
        lines += ['', result.stat[-1500:]]
    return '\n'.join(lines)


class Watcher:
    def __init__(self, client, config, state_path, runner, notices_command=None, resident=False, clock=time.time):
        self.client, self.config, self.runner = client, config, runner
        self.state_path, self.notices_command, self.resident, self.clock = state_path, notices_command, resident, clock
        self.state = read_json(state_path, {}) or {}
        for key, default in (('mention_seq', 0), ('failures', {}), ('answered', []), ('announced', []),
                             ('ship_exchanges', {}), ('paused', []), ('rooms', {}), ('replies', {})):
            self.state.setdefault(key, default)
        self.me = None

    def save(self):
        write_private(self.state_path, self.state)

    def cycle(self):
        if self.me is None:
            self.me = self.client.me()
        try:
            posted = self._announce()
        except Exception as error:  # noqa: BLE001 - notices must never keep the ship from answering
            log.warning('could not announce notices: %s', redact(str(error)))
            posted = 0
        for mention in self.client.mentions(self.state['mention_seq']):
            done, sent = self._handle(mention)
            posted += sent
            if not done:
                break  # retry this mention next cycle; later ones wait behind it
            self.state['mention_seq'] = mention['seq']
            self.save()
        if self.resident:
            posted += self._resident()
        return posted

    def _remember(self, message_id):
        self.state['answered'] = (self.state['answered'] + [message_id])[-ANSWERED_KEPT:]

    def _handle(self, mention):
        mid, author = mention['message_id'], mention['author']
        if mid in self.state['answered'] or author['id'] == self.me['id']:
            return True, 0
        if author['kind'] == 'ship' and mid not in self.state['replies'] and not self._ship_budget(mention):
            return True, self._pause_note(mention)
        owner = self.config.get('owner_id')
        mode = 'build' if not self.resident and owner and author['kind'] == 'person' and author['id'] == owner else 'read'
        try:
            room = self.client.room(mention['room_id'])
            if any(m['author_id'] == self.me['id'] and m.get('client_message_id') == f'reply-{mid}' for m in room['messages']):
                self._remember(mid)
                self.state['replies'].pop(mid, None)
                self.save()
                return True, 0
            reply = self.state['replies'].get(mid)  # a reply whose post failed is posted as it was, never re-run
            if reply is None:
                reply = format_reply(self.runner.run(mode, build_prompt(room, mention, self.config['ship'], mode), mid))
        except RunTimeout as error:
            log.warning('mention %s timed out: %s', mid, error)
            reply = TIMEOUT_NOTE
        except Exception as error:  # noqa: BLE001 - retried next cycle, then a fallback note
            failures = self.state['failures'][mid] = self.state['failures'].get(mid, 0) + 1
            log.warning('mention %s failed (%d/%d): %s', mid, failures, MAX_FAILURES, redact(str(error)))
            self.save()
            if failures < MAX_FAILURES:
                return False, 0
            reply = FALLBACK
        self.state['failures'].pop(mid, None)
        return True, self._reply(mention['room_id'], mid, reply)

    def _reply(self, room_id, message_id, body):
        body = redact(body)[:20000]
        # Stored before posting: if the post fails the run is not repeated (a build whose branch was kept cannot be).
        self.state['replies'][message_id] = body
        self.save()
        posted = 0
        try:
            self.client.post(room_id, body, f'reply-{message_id}')
            posted = 1
        except StationError as error:
            if error.status not in (403, 404, 409):
                raise
            log.warning('could not reply to %s: %s', message_id, error)
        self.state['replies'].pop(message_id, None)
        self._remember(message_id)
        self.save()
        return posted

    def _ship_budget(self, mention):
        key, now = f'{mention["room_id"]}:{mention["author"]["id"]}', self.clock()
        recent = [t for t in self.state['ship_exchanges'].get(key, []) if t > now - 3600]
        allowed = len(recent) < SHIP_EXCHANGES_PER_HOUR
        self.state['ship_exchanges'][key] = recent + [now] if allowed else recent
        return allowed

    def _pause_note(self, mention):
        key = f'{mention["room_id"]}:{mention["author"]["id"]}:{int(self.clock() // 3600)}'
        if key in self.state['paused']:
            return 0
        self.state['paused'] = (self.state['paused'] + [key])[-100:]
        self.save()
        try:
            self.client.post(mention['room_id'], f'Pausing my replies to @{label(mention["author"]["username"])} in this room for the rest of the hour, so we do not loop.', f'pause-{key}')
        except StationError as error:
            log.warning('could not post pause note: %s', error)
            return 0
        return 1

    def _announce(self):
        if not self.notices_command:
            return 0
        listed = json.loads(subprocess.run(self.notices_command, capture_output=True, text=True, check=True, timeout=60).stdout)
        notices = [n for n in listed if n['id'] not in self.state['announced']]
        # Local rooms only: a federated room's id carries the other peer's name, and its members are not ours.
        ops = max((r for r in self.client.rooms() if r.get('title') == NOTICE_ROOM and ':' not in r['id']),
                  key=lambda r: r.get('last_activity') or 0, default=None) if notices else None
        if ops is None:
            return 0
        posted = 0
        for notice in notices:
            try:
                self.client.post(ops['id'], notice['text'], f'notice-{notice["id"]}')
                posted += 1
            except StationError as error:
                if error.status not in (403, 404, 409):
                    log.warning('could not announce notice %s, will retry: %s', notice['id'], error)
                    continue
                # Rejected for good (a changed text under a used id, a room that is gone): do not retry it every cycle.
                log.warning('notice %s was rejected, not retrying: %s', notice['id'], error)
            self.state['announced'].append(notice['id'])
            self.save()
        return posted

    def _resident(self):
        posted = 0
        for summary in self.client.rooms():
            if ':' in summary['id']:
                continue
            seen = self.state['rooms'].get(summary['id'], {})
            if seen.get('activity') == summary.get('last_activity'):
                continue
            room = self.client.room(summary['id'])
            members = room.get('members', [])
            people = [m for m in members if m['kind'] == 'person']
            ships = [m['id'] for m in members if m['kind'] == 'ship']
            # member_ids also counts remote members (paired peers) that `members` leaves out: exactly the person and Odo.
            if len(people) == 1 and ships == [self.me['id']] and len(room.get('member_ids', [])) == 2:
                done, sent = self._resident_reply(room, seen)
                posted += sent
                if not done:
                    continue
            record = {'activity': summary.get('last_activity')}
            if room['messages']:
                record['cursor'] = room['messages'][-1]['id']
            self.state['rooms'][summary['id']] = record
            self.save()
        return posted

    def _resident_reply(self, room, seen):
        messages, ids = room['messages'], [m['id'] for m in room['messages']]
        start = ids.index(seen['cursor']) + 1 if seen.get('cursor') in ids else 0
        new = [m for m in messages[start:] if m['author_id'] != self.me['id']]
        if not new:
            return True, 0
        target = new[-1]  # first sight or several new messages: answer only the latest
        author = next((m for m in room.get('members', []) if m['id'] == target['author_id']), dict(UNKNOWN, id=target['author_id']))
        return self._handle({'message_id': target['id'], 'room_id': room['id'], 'body': target['body'], 'author': author, 'seq': None})
