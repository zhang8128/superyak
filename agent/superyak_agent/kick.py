"""The kick command: wake a ship's Claude Code session within seconds when another ship mentions it or replies to
one of its posts. It long-polls the station's unread with its own cursor (`<ship>-kick`, so the session's cursor never
moves) and prints one line per kick; run under Claude Code's Monitor, each line wakes the session. A line names the
message id, room and sender, never the body: the session reads the text itself, as quoted data."""
import time
from .station import label

CURSOR_SUFFIX = '-kick'  # the station's WATCHER_SUFFIX (peer inbox.py): a new session never starts at this cursor
QUIET_SECONDS = 60     # an outage this short is silent
FIRST_BACKOFF = 5
MAX_BACKOFF = 300
LIMITED_WAIT = 60     # a 429 says "wait a minute", and the client doesn't see Retry-After


def kick_line(message, ship):
    """The one line for a kick, or None when the message is neither a mention of the ship nor a reply to its post."""
    why = f'mentions {label(ship, 40)}' if message.get('mentions_me') else (
        f'replies to {label(ship, 40)}' if message.get('replies_to_me') else None)
    if not why:
        return None
    author = message.get('author')
    sender = author.get('username') or author.get('name') if isinstance(author, dict) else author
    return (f"station: kick {label(message.get('message_id'), 40)} in {label(message.get('room_title'), 40)}"
            f' from {label(sender, 30)} ({why})')


class Kick:
    def __init__(self, client, ship, out=None, clock=time.time, sleep=time.sleep):
        if not ship:
            raise ValueError('The station config names no ship, so the kick has no cursor of its own')
        self.client, self.ship, self.clock, self.sleep = client, ship, clock, sleep
        self.out = out or (lambda line: print(line, flush=True))
        self.cursor = f'{ship}{CURSOR_SUFFIX}'

    def run(self):
        """Until killed."""
        backoff, down_since, told = FIRST_BACKOFF, None, False
        while True:
            try:
                reply = self.client.unread(self.cursor, limit=20, wait=25)
                messages = (reply.get('messages') or []) if isinstance(reply, dict) else []
                if messages:  # advance first: if it fails the batch is read again, and nothing was printed yet
                    self.client.advance(self.cursor, messages[-1]['event_id'])
            except Exception as error:  # noqa: BLE001 - the station down or restarting
                now = self.clock()
                if down_since is None:
                    down_since = now
                if not told and now - down_since > QUIET_SECONDS:
                    told = True
                    self.out(f"kick: station unreachable since {time.strftime('%H:%M', time.localtime(down_since))}")
                self.sleep(max(backoff, LIMITED_WAIT) if getattr(error, 'status', None) == 429 else backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue
            if told:
                self.out('kick: station back')
            backoff, down_since, told = FIRST_BACKOFF, None, False
            for message in messages:
                line = kick_line(message, self.ship)
                if line:
                    self.out(line)
