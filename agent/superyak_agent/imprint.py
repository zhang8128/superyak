"""The owner's agent sends a store copy (an imprint) to the station: `context` and `send` (store-imprint I 9, 13, D24).

Nothing of the package leaves before the owner's yes: `send` posts only `request.json`, then waits for the owner to
confirm in the browser (the agent never types the password or ticks the check). After the yes it sends the manifest,
then each part the station does not hold, one at a time, then `complete`. Standard library only."""
import fcntl
import json
import time
from pathlib import Path

from .station import StationError, read_json, write_private

PART_BYTES = 4_194_304            # one part on the wire; the agent holds at most one (I 9, D42)
POLL_SECONDS = 15
PART_RETRIES = 3                  # a 429 from the station's part limiter waits a minute, then tries the part again
FINAL = ('admitted', 'declined', 'denied', 'failed', 'deleted')   # after these the local imprint.db goes (D24)
BUSY = 'Another make imprint-send of this plan is running.'
HEX = frozenset('0123456789abcdef')


class ImprintRefused(Exception):
    """A refusal the command prints; `code` is its exit status."""
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


class Imprint:
    def __init__(self, home, client, out=print):
        self.home, self.client, self.out = Path(home), client, out
        self.root = self.home / 'imprints'

    def context(self):
        """What the station says a ship needs to ask for a copy (its name, its owner's, the operator's, the station's
        id and its imprints), kept in `imprints/context.json` (R7)."""
        found = self.client.request('GET', '/api/imprints')
        write_private(self.root / 'context.json', found)
        return found

    def _imprint_of(self, plan_prefix):
        prefix = (plan_prefix or '').strip().lower()
        if len(prefix) < 4 or not set(prefix) <= HEX:
            raise ImprintRefused('Name a plan by at least its first 4 characters, as the dry run showed them.')
        found = sorted((self.root / 'plans').glob(f'{prefix}*.json'))
        if not found:
            raise ImprintRefused(f'There is no plan {prefix}. Run the plan again.')
        if len(found) > 1:
            raise ImprintRefused(f'More than one plan starts with {prefix}; give more of its characters.')
        try:
            imprint_id = json.loads(found[0].read_text()).get('imprint_id')
        except (OSError, ValueError, AttributeError):
            imprint_id = None
        if not isinstance(imprint_id, str) or not (self.root / imprint_id / 'request.json').is_file():
            raise ImprintRefused(f'The plan {prefix} is not built. Run make imprint-send, which builds it first.')
        return imprint_id

    def send(self, plan_prefix, *, wait=540):
        imprint_id = self._imprint_of(plan_prefix)
        folder = self.root / imprint_id
        with open(folder / 'send.lock', 'a+') as lock:       # RF5: one send of an imprint at a time
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ImprintRefused(BUSY, 4) from None
            return self._send(folder, imprint_id, wait)

    def _send(self, folder, imprint_id, wait):
        saved = read_json(folder / 'send.json')
        if saved is None:
            made = self.client.request('POST', '/api/imprints', raw=(folder / 'request.json').read_bytes())
            saved = {'imprint_id': imprint_id, 'request_id': made['id'], 'code': made['code'],
                     'expires': made['expires'], 'confirm_url': made['confirm_url']}
            write_private(folder / 'send.json', saved)
            self.out(f'Imprint {imprint_id[:4]}, request {made["id"][:4]}. Code {made["code"]}.')
            self.out(f'Open {made["confirm_url"]} in your browser, check the code matches, choose your station password '
                     f'and tick the box. Nothing leaves this machine until you say yes.')
        deadline = time.time() + wait
        while True:
            status = self.client.request('GET', f'/api/imprints/{saved["request_id"]}')
            state = status.get('status')
            if state == 'allowed':
                return self._upload(folder, saved, status)
            if state == 'deleted':
                state = self._deleted_as(status)
            if state in FINAL:
                self._drop_local_copy(imprint_id)
                return state
            if state != 'requested':          # received, approved, deleting, expired: the station's word, as it is
                return state
            time.sleep(POLL_SECONDS)
            if time.time() >= deadline:
                return 'waiting-for-you'

    def _deleted_as(self, status):
        """The station's `deleted` carries its reason in the last `deleted` receipt; `denied` and `failed` are reasons."""
        reason = None
        for receipt in status.get('receipts') or []:
            record = receipt.get('record') or {}
            if record.get('event') == 'deleted':
                reason = (record.get('detail') or {}).get('reason')
        if reason:
            self.out(f'Deleted: {reason}.')
        return reason if reason in ('denied', 'failed') else 'deleted'

    def _upload(self, folder, saved, status):
        base = f'/api/imprints/{saved["request_id"]}'
        manifest = json.loads((folder / 'manifest.json').read_text())
        package = manifest['package']
        count, size = len(package['parts']), int(package['part_bytes'])
        if not 0 < size <= PART_BYTES:
            raise ImprintRefused('The manifest names a part longer than 4 MiB.')
        try:
            self.client.request('PUT', f'{base}/manifest', raw=(folder / 'manifest.json').read_bytes())
        except StationError as error:
            if error.status != 409 or 'already has its manifest' not in error.message:
                raise
        held = set(status.get('held') or [])
        todo = [n for n in range(count) if n not in held]
        with open(folder / 'imprint.db', 'rb') as package_file:
            for done, n in enumerate(todo, 1):
                self.out(f'Sending part {done} of {len(todo)}.')
                self._put_part(package_file, base, n, size, int(package['bytes']))
        self.client.request('POST', f'{base}/complete', body={})
        self.out('The station has every part.')
        return 'received'

    def _put_part(self, package_file, base, n, size, total):
        for attempt in range(PART_RETRIES):
            package_file.seek(n * size)
            data = package_file.read(min(size, total - n * size))      # one part in hand at a time
            try:
                self.client.request('PUT', f'{base}/parts/{n}', raw=data)
                return
            except StationError as error:
                if error.status != 429 or attempt == PART_RETRIES - 1:
                    raise
            finally:
                del data
            time.sleep(60)

    def _drop_local_copy(self, imprint_id):
        """The package goes once the imprint is over; the manifest, plan, owner lists and receipts stay (D24)."""
        (self.root / imprint_id / 'imprint.db').unlink(missing_ok=True)
