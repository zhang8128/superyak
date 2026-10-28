"""federate (federation pull plan, Task 8): the one process that delivers for a data directory when it isn't served
with --sync. A pass every PASS_SECONDS: in pull mode it first pulls from each paired push peer whose pull is due, then
collects and pushes. Whether a pull is due lives here, in memory (plan P4): at once at start, 60 s after a pull, or a
failure's own backoff, as pull_once says; an overrun of the sleep by more than WAKE_OVERRUN s is a wake, and every peer
is pulled at once (P13). Each step catches and logs its own faults, so one never ends the process. It listens on
nothing: pulls and pushes only dial out."""
import json
import logging
import signal
import time

PASS_SECONDS = 5.0
WAKE_OVERRUN = 30.0  # measured from the end of one pass to the start of the next, so slow rounds never read as a wake
log = logging.getLogger(__name__)


class Federate:
    def __init__(self, federation, *, clock=time.time, sleep=time.sleep, send=None, pass_seconds=PASS_SECONDS):
        self.federation, self.clock, self.sleep, self.send = federation, clock, sleep, send
        self.pass_seconds, self.due, self.last_end, self.stopping = pass_seconds, {}, None, False
        self.seen_requests = None  # "Check delivery now" counts in peer_meta; a change makes every pull due (P11)

    def _requests(self):
        with self.federation.store.transaction() as db:
            row = db.execute("SELECT value FROM peer_meta WHERE key='sync_requests'").fetchone()
        return row[0] if row else None

    def pull_cards(self):
        """The paired push peers' cards: the listeners a pull peer fetches from."""
        with self.federation.store.transaction() as db:
            cards = [json.loads(row[0]) for row in db.execute('SELECT card FROM peers WHERE paired=1')]
        return [card for card in cards if card.get('delivery', 'push') == 'push']

    def run_pass(self):
        now = self.clock()
        woke = self.last_end is not None and now - self.last_end - self.pass_seconds > WAKE_OVERRUN
        requests = self._requests()
        woke, self.seen_requests = woke or requests != self.seen_requests, requests
        if self.federation.store.federation_mode() == 'pull':
            for card in self.pull_cards():
                if self.stopping:
                    return
                peer = card['peer_id']
                if not woke and self.due.get(peer, now) > now:
                    continue
                try:
                    got = self.federation.pull_once(card, send=self.send)
                    self.due[peer] = self.clock() + got['next']
                except Exception:  # noqa: BLE001 - a pull's fault never ends federate
                    log.exception('A pull from %s failed', peer[:8])
                    self.due[peer] = self.clock() + 60
        for name, step in (('collect', self.federation.collect),
                           ('sync', lambda: self.federation.sync_once(send=self.send))):
            if self.stopping:
                return
            try:
                step()
            except Exception:  # noqa: BLE001 - nor does a push's
                log.exception('federate: %s failed', name)
        self.last_end = self.clock()

    def run(self):
        """Passes until SIGTERM, which ends it between steps."""
        def stop(signum, frame):
            self.stopping = True
        signal.signal(signal.SIGTERM, stop)
        while not self.stopping:
            self.run_pass()
            if not self.stopping:
                self.sleep(self.pass_seconds)
