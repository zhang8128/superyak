"""The mention watcher: one Claude run at a time; the watcher, not the agent, posts replies."""
import json
import logging
import subprocess
import time
from superyak_team.teamlib import redact
from .runs import RunTimeout
from .station import MESSAGE_LIMIT, StationError, authors, brief_block, describe, fence_message, label, read_json, source_label, write_private

log = logging.getLogger('superyak.agent')
POLL_SECONDS = 30
HISTORY = 30
HISTORY_CHARS = 2000  # each earlier message; the mentioning message, the request, is never cut
MAX_FAILURES = 3
SHIP_EXCHANGES_PER_HOUR = 5
ANSWERED_KEPT = 500
REPLY_MAX = 20000
NOTICE_ROOM = 'Ops'
FALLBACK = "I couldn't answer this one. My owner can check the watcher log on this machine."
TIMEOUT_NOTE = 'This took longer than my time limit, so I stopped. Try a smaller request.'
UNKNOWN = {'id': None, 'username': 'unknown', 'name': 'someone', 'kind': 'unknown', 'owner_id': None}
DEFERRED_PER_CYCLE = 20  # ship status S5: deferred mentions re-asked per cycle, oldest first
DEFERRED_MAX = 100       # past this a new mention asks for today's ticket, never a deferral it couldn't keep (R10)
READ_ONLY_LINE = "Read-only run: I can read and search, but I can't run commands, fetch branches or change files."


def build_prompt(room, mention, ship, mode):
    members = authors(room)
    messages, ids = room['messages'], [m['id'] for m in room['messages']]
    end = ids.index(mention['message_id']) + 1 if mention['message_id'] in ids else len(messages)
    quoted = [fence_message(members.get(m['author_id']), m['body'], MESSAGE_LIMIT if m['id'] == mention['message_id'] else HISTORY_CHARS,
                           source=source_label(m))
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
    brief = brief_block(room)  # the owner's brief about the room, whole and fenced like a message, before the history
    return (f'Room: {label(room["title"])}\n\n' + (brief + '\n\n' if brief else '') + 'Recent messages, oldest first:\n\n'
            + '\n\n'.join(quoted) + f'\n\nThe last message, from {describe(author)}, mentions you (@{ship}). {task}\n')


def _budget_place(mention):
    """Where a ship-to-ship budget is kept (S5, R12): per room, but in a breakout across all of them, so a ship's
    mentions are bounded by the mentioning ship alone however many breakouts it shares with this one."""
    return 'breakouts' if mention.get('breakout') else mention['room_id']


def format_reply(result, footer=''):
    lines = [result.reply]
    if result.branch:
        lines += ['', f'Branch `{result.branch}`, commit {result.commit[:9]} (not pushed).']
        if result.stat:
            lines += ['', result.stat[-1500:]]
    text = '\n'.join(lines)
    return text[:REPLY_MAX - len(footer) - 2] + '\n\n' + footer if footer else text


class Watcher:
    def __init__(self, client, config, state_path, runner, notices_command=None, resident=False, clock=time.time):
        self.client, self.config, self.runner = client, config, runner
        self.state_path, self.notices_command, self.resident, self.clock = state_path, notices_command, resident, clock
        self.state = read_json(state_path, {}) or {}
        for key, default in (('mention_seq', 0), ('failures', {}), ('answered', []), ('announced', []),
                             ('ship_exchanges', {}), ('paused', []), ('rooms', {}), ('replies', {}), ('tickets', {}),
                             ('deferred', [])):
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
        for mention in list(self.state['deferred'][:DEFERRED_PER_CYCLE]):  # S5: oldest first; never holds new ones back
            posted += self._handle(mention)[1]
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
        self.state['deferred'] = [d for d in self.state['deferred'] if d['message_id'] != message_id]

    def _handle(self, mention):
        mid, author = mention['message_id'], mention['author']
        if mid in self.state['answered'] or author['id'] == self.me['id']:
            return True, 0
        listed = any(d['message_id'] == mid for d in self.state['deferred'])
        reply = self.state['replies'].get(mid)  # a reply whose post failed is posted as it was, never re-run
        # R37: a new mention from a ship spends its budget here; a listed one only once the station has answered (below).
        if author['kind'] == 'ship' and reply is None and not listed and not self._ship_budget(mention):
            return True, self._pause_note(mention)
        room = None
        try:
            # A listed mention asks for its ticket first and fetches its room only to run (S5), so a mention still
            # deferred costs one request a cycle.
            if reply is not None or not listed:
                room = self.client.room(mention['room_id'])
                if self._posted(room, mid):
                    return True, 0
            if reply is None:
                try:
                    # The station decides the mode now; no ticket, no run. R10: with the deferred list full, a new
                    # mention asks for today's ticket, never a deferral the watcher couldn't keep.
                    ticket = self.client.ticket(mid, listed or len(self.state['deferred']) < DEFERRED_MAX)
                except StationError as error:
                    # R20: a claim or a notice is never answered, and a closed breakout's mention isn't (422); breakouts
                    # R5: nor is one from a breakout this ship has left (404). Done, without a word.
                    if error.status == 422 or (error.status == 404 and mention.get('breakout')):
                        self.state['failures'].pop(mid, None)
                        self._remember(mid)
                        self.save()
                        return True, 0
                    if error.status != 409:
                        raise
                    log.warning('mention %s: its ticket is finished but no reply is in the room', mid)
                    self.state['failures'].pop(mid, None)
                    return True, self._reply(mention['room_id'], mid, FALLBACK)
                decision = ticket.get('decision', 'run')  # R23: a station that sends no decision decides `run`
                if decision in ('defer', 'answered'):
                    self.state['failures'].pop(mid, None)
                    if decision == 'answered':
                        self._finish(mid)  # an earlier run that failed left its ticket running
                        self._remember(mid)  # its session answered it with reply_to: nothing to post
                    elif not listed:  # a breakout's mark is kept: its budget and its 404 depend on it (breakouts R5, R12)
                        self.state['deferred'].append({k: mention[k] for k in ('message_id', 'room_id', 'author', 'seq')}
                                                      | ({'breakout': True} if mention.get('breakout') else {}))
                    self.save()
                    return True, 0
                # R37: only the station's answer spares a re-ask: a run resolving a deferral it held carries
                # `first_deferred`, and a ticket it already issued us was charged when issued. Anything else is new.
                held = 'first_deferred' in ticket or self.state['tickets'].get(mid) == ticket['id']
                self.state['tickets'][mid] = ticket['id']
                self.save()
                if listed and author['kind'] == 'ship' and not held and not self._ship_budget(mention):
                    self._finish(mid)
                    self._remember(mid)
                    self.save()
                    return True, self._pause_note(mention)
                if room is None:
                    room = self.client.room(mention['room_id'])
                    if self._posted(room, mid):
                        return True, 0
                mode = 'read' if self.resident or ticket.get('mode') != 'build' else 'build'  # never above the ticket
                result = self.runner.run(mode, build_prompt(room, mention, self.config['ship'], mode), mid,
                                           instructions=ticket.get('blocks') or '')
                footer = label(ticket.get('footer'), 200).replace('@', '(at)') if mode == 'build' and ticket.get('footer') else ''
                reply = format_reply(result, footer)
                if mode == 'read' and mention.get('seq') is not None:  # S6: the mode the run used; no resident DM reply
                    reply = f'{READ_ONLY_LINE}\n\n{reply}'
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

    def _posted(self, room, message_id):
        """True, and the mention done, when this ship's reply to it is already in the room."""
        if not any(m['author_id'] == self.me['id'] and m.get('client_message_id') == f'reply-{message_id}' for m in room['messages']):
            return False
        self._finish(message_id)
        self._remember(message_id)
        self.state['replies'].pop(message_id, None)
        self.save()
        return True

    def _reply(self, room_id, message_id, body):
        body = redact(body)[:20000]
        # Stored before posting: if the post fails the run is not repeated (a build whose branch was kept cannot be).
        self.state['replies'][message_id] = body
        self.save()
        posted, ticket_id = 0, self.state['tickets'].get(message_id)
        try:
            self.client.post(room_id, body, f'reply-{message_id}', ticket_id, message_id)  # R22: reply_to the mention
            posted = 1
        except StationError as error:
            if error.status not in (403, 404, 409):
                raise
            if error.status == 409 and ticket_id:
                posted = self._post_unlabelled(room_id, message_id, body)
            else:
                log.warning('could not reply to %s: %s', message_id, error)
        self._finish(message_id)
        self.state['replies'].pop(message_id, None)
        self._remember(message_id)
        self.save()
        return posted

    def _post_unlabelled(self, room_id, message_id, body):
        """The ticket can no longer label a reply (finished or expired): the reply still goes out, unlabelled."""
        try:
            self.client.post(room_id, body, f'reply-{message_id}', None, message_id)  # R22
            return 1
        except StationError as error:
            if error.status not in (403, 404, 409):
                raise
            log.warning('could not reply to %s: %s', message_id, error)
            return 0

    def _finish(self, message_id):
        ticket_id = self.state['tickets'].pop(message_id, None)
        if ticket_id:
            try:
                self.client.finish_ticket(ticket_id)
            except (StationError, OSError) as error:  # the station closes it after two hours anyway
                log.warning('could not finish ticket %s: %s', ticket_id, redact(str(error)))

    def _ship_budget(self, mention):
        key, now = f'{_budget_place(mention)}:{mention["author"]["id"]}', self.clock()
        recent = [t for t in self.state['ship_exchanges'].get(key, []) if t > now - 3600]
        allowed = len(recent) < SHIP_EXCHANGES_PER_HOUR
        self.state['ship_exchanges'][key] = recent + [now] if allowed else recent
        return allowed

    def _pause_note(self, mention):
        """One note an hour per budget: per room, or one for all of a ship's breakouts (breakouts S5)."""
        key = f'{_budget_place(mention)}:{mention["author"]["id"]}:{int(self.clock() // 3600)}'
        if key in self.state['paused']:
            return 0
        self.state['paused'] = (self.state['paused'] + [key])[-100:]
        self.save()
        who = f'@{label(mention["author"]["username"])}'
        text = (f'Pausing my replies to {who} for the rest of the hour in breakouts, so we do not loop.' if mention.get('breakout')
                else f'Pausing my replies to {who} in this room for the rest of the hour, so we do not loop.')
        try:
            self.client.post(mention['room_id'], text, f'pause-{key}')
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
        new = [m for m in messages[start:] if m['author_id'] != self.me['id']
               and (m.get('source') or {}).get('kind') not in ('claim', 'notice')]  # R20, R32: never answered
        if not new:
            return True, 0
        target = new[-1]  # first sight or several new messages: answer only the latest
        author = next((m for m in room.get('members', []) if m['id'] == target['author_id']), dict(UNKNOWN, id=target['author_id']))
        return self._handle({'message_id': target['id'], 'room_id': room['id'], 'body': target['body'], 'author': author, 'seq': None})
