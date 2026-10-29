"""The owner's agent sends a store copy (an imprint) to the station: `context` and `send` (store-imprint I 9, 13, D24).

Nothing of the package leaves before the owner's yes: `send` posts only `request.json`, then waits for the owner to
confirm in the browser (the agent never types the password or ticks the check). After the yes it sends the manifest,
then each part the station does not hold, one at a time, then `complete`. Standard library only.

`status`, `withdraw` and `shorten` (I 12, 13) follow: the receipts are saved and their chain checked here; a signature
is the station's, checked by the peer's `verify-imprint` (Task 44), not by this agent."""
import fcntl
import functools
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .station import StationError, label, read_json, write_private

PART_BYTES = 4_194_304            # one part on the wire; the agent holds at most one (I 9, D42)
POLL_SECONDS = 15
PART_RETRIES = 3                  # a 429 from the station's part limiter waits a minute, then tries the part again
FINAL = ('admitted', 'declined', 'denied', 'failed', 'deleted', 'expired')   # after these the local imprint.db goes (D24)
BUSY = 'Another make imprint-send of this plan is running.'
HEX = frozenset('0123456789abcdef')
MAX_SEQ = 2**53                   # a receipt's seq is a bounded non-negative int before it names a file (review I2)
MALFORMED = 'The station sent receipts this agent cannot read; nothing was saved. Run make imprint-status again later.'


class ImprintRefused(Exception):
    """A refusal the command prints; `code` is its exit status."""
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


class Imprint:
    def __init__(self, home, client, out=functools.partial(print, flush=True)):     # a session reads a pipe (review M1)
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
        """The run that makes the request returns once it has printed the link, so a session can relay it at once
        (the fresh review's M1); later runs wait up to `wait` seconds for the yes, showing the link again first. A run
        that finds the code expired says so and returns `code-expired` at once: nobody can allow it any more."""
        saved = read_json(folder / 'send.json')
        if saved is None:
            made = self.client.request('POST', '/api/imprints', raw=(folder / 'request.json').read_bytes())
            saved = {'imprint_id': imprint_id, 'request_id': made['id'], 'code': made['code'],
                     'expires': made['expires'], 'confirm_url': made['confirm_url']}
            write_private(folder / 'send.json', saved)
            self._show_link(imprint_id, saved)
            return 'waiting-for-you'
        deadline, shown = time.time() + wait, False
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
            if state != 'requested':          # received, approved, deleting: the station's word, as it is
                return state
            if not shown:
                if self._show_link(imprint_id, saved, again=True) == 'code-expired':
                    return 'code-expired'
                shown = True
            time.sleep(POLL_SECONDS)
            if time.time() >= deadline:
                return 'waiting-for-you'

    def _show_link(self, imprint_id, saved, again=False):
        """The two short ids, the code and the confirm link. On a later run whose code has expired (send.json's
        `expires`, as the station tests it), one line says so instead, without the code, and it returns
        `code-expired`."""
        imprint_id, request_id = imprint_id[:4], _shown(saved.get('request_id'))[:4]
        expires = saved.get('expires')
        if again and isinstance(expires, (int, float)) and not isinstance(expires, bool) and expires <= time.time():
            self.out(f'Imprint {imprint_id}, request {request_id}: its code has expired, so it can no longer be '
                     f'allowed. The request ends at the station\'s next hourly sweep, and then you plan again.')
            return 'code-expired'
        self.out(f'Imprint {imprint_id}, request {request_id}. Code {_shown(saved.get("code"))}.')
        self.out(f'Open {_shown(saved.get("confirm_url"), 400)} in your browser yourself. Check that it shows the '
                 f'two short ids above and that the address is the station\'s, tick the box and type your own '
                 f'station password. Don\'t accept a password your browser suggests. Nothing leaves this machine '
                 f'until you say yes. A session relays this link and never opens it.')

    def _deleted_as(self, status):
        """The station's `deleted` carries its reason in the last `deleted` receipt; `denied` and `failed` are reasons."""
        reason = None
        receipts = status.get('receipts')
        for receipt in receipts if isinstance(receipts, list) else []:
            record = receipt.get('record') if isinstance(receipt, dict) else None
            if isinstance(record, dict) and record.get('event') == 'deleted' and isinstance(record.get('detail'), dict):
                reason = record['detail'].get('reason')
        if reason:
            self.out(f'Deleted: {_shown(reason)}.')
        return reason if reason in ('denied', 'failed') else 'deleted'

    def _upload(self, folder, saved, status):
        base = f'/api/imprints/{saved["request_id"]}'
        package = _package_of(folder / 'manifest.json')
        count, size = len(package['parts']), package['part_bytes']
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

    # status, withdraw and shorten (I 12, 13)

    def _resolve(self, wanted):
        """The imprint id for a full id or its first 4 or more characters, among the imprints this machine has sent."""
        prefix = (wanted or '').strip().lower()
        sent = sorted(p.parent.name for p in self.root.glob('*/send.json'))
        found = [i for i in sent if len(prefix) >= 4 and i.startswith(prefix)]
        if len(found) != 1:
            raise ImprintRefused(f'There is no sent imprint {prefix or "(none named)"}.' if not found else
                                 f'More than one imprint starts with {prefix}; give more of its characters.')
        return found[0]

    def _request_id(self, imprint_id):
        saved = read_json(self.root / imprint_id / 'send.json') or {}
        if not isinstance(saved.get('request_id'), str):
            raise ImprintRefused(f'Imprint {imprint_id[:4]} has not been sent.')
        return saved['request_id']

    def status(self, imprint_id=None):
        """With no id, one line per imprint: short id, status, end date and last event. With one, its receipts are saved
        under `imprints/<id>/receipts/`, the chain is checked, and the reports and what the station keeps are printed."""
        if imprint_id is None:
            return self._list()
        imprint_id = self._resolve(imprint_id)
        request_id = self._request_id(imprint_id)
        found = self.client.request('GET', f'/api/imprints/{request_id}')
        receipts = _receipts_of(found)
        folder = self.root / imprint_id / 'receipts'
        for receipt in receipts:
            write_private(_receipt_path(folder, receipt['seq'], imprint_id), receipt)
        kept = self._kept_permission(imprint_id, found.get('permission'))
        chain = self._chain_of({'permission': kept}, receipts, request_id)
        state = found.get('status')
        self.out(f'Imprint {imprint_id[:4]}: {_shown(state)}. Ends {_date(_end_of(found, receipts))}. '
                 f'Receipts: {len(receipts)}, chain {chain}.')
        for receipt in receipts:
            line = f'  {receipt["seq"]}. {_shown(receipt["record"].get("event"))} at {_date(receipt["record"].get("at"))}'
            self.out(line + ('' if receipt.get('signature') else ' (not yet signed)'))
        if found.get('calibration_report') is not None:      # JSON text: every control character comes out escaped
            self.out('Calibration report: ' + json.dumps(found['calibration_report'], sort_keys=True))
        uses = found.get('use_reports')
        for use in uses if isinstance(uses, list) else []:
            if isinstance(use, dict):
                self.out(f'Use {_shown(use.get("use_id"))}: ' + json.dumps(use.get('report'), sort_keys=True))
        keeps = found.get('keeps')
        if isinstance(keeps, dict) and keeps:
            self.out(_shown(keeps.get('text', ''), 2000))
            removed = keeps.get('removed_on')
            for what, day in (removed.items() if isinstance(removed, dict) else ()):
                self.out(f'  {_shown(what)}: removed on {_shown(day)}')
        if state in FINAL:
            self._drop_local_copy(imprint_id)
        return {'imprint_id': imprint_id, 'status': state, 'chain': chain, 'receipts': len(receipts),
                'unsigned': [r['seq'] for r in receipts if not r.get('signature')]}

    def _kept_permission(self, imprint_id, permission):
        """The permission saved the first time the station sent one, which `verify-imprint --dir` reads. A later one
        never replaces it; one that differs is named (final review M8). None until a well-formed one arrives."""
        path = self.root / imprint_id / 'permission.json'
        try:
            saved = read_json(path)
        except (OSError, ValueError):
            saved = path                                    # there but unreadable: kept as it is, for verify to name
        well_formed = isinstance(permission, dict) and all(isinstance(permission.get(k), v) for k, v in
                                                           (('record', dict), ('signature', str), ('station_key', str)))
        if saved is None:
            if not well_formed:
                return None
            write_private(path, permission)
            return permission
        if well_formed and saved != permission:
            self.out('The station sent a permission other than the one saved first; the saved one is kept, and '
                     'verify-imprint checks it.')
        return saved if isinstance(saved, dict) else None

    def _list(self):
        rows = []
        for path in sorted(self.root.glob('*/send.json')):
            imprint_id = path.parent.name
            try:
                found = self.client.request('GET', f'/api/imprints/{self._request_id(imprint_id)}')
                receipts = _receipts_of(found)
            except (StationError, ImprintRefused) as error:
                self.out(f'{imprint_id[:4]}  (not read: {_shown(error, 300)})')
                continue
            last = receipts[-1]['record'].get('event') if receipts else 'none'
            row = {'imprint_id': imprint_id, 'status': found.get('status'), 'ends': _date(_end_of(found, receipts)), 'last_event': last}
            self.out(f'{imprint_id[:4]}  {_shown(row["status"])}  ends {row["ends"]}  last event {_shown(last)}')
            rows.append(row)
            if row['status'] in FINAL:
                self._drop_local_copy(imprint_id)
        return {'imprints': rows}

    @staticmethod
    def _chain_of(found, receipts, request_id):
        """Each receipt names this permission, and its `previous` is the SHA-256 of the one before it (the first, of
        the permission record). Without the permission record the chain is `unchecked`, never `intact` (review I2)."""
        if not receipts:
            return 'empty'
        permission = found.get('permission')
        previous = permission.get('record') if isinstance(permission, dict) else None
        if not isinstance(previous, dict):
            return 'unchecked'
        for n, receipt in enumerate(receipts):
            record = receipt['record']
            if record.get('permission') != request_id:
                return f'broken at receipt {receipt["seq"]}'
            try:
                digest = hashlib.sha256(_canonical(previous)).hexdigest()
            except (TypeError, ValueError):
                digest = None
            if digest is None or record.get('previous') != digest:
                return f'broken after receipt {receipts[n - 1]["seq"]}' if n else 'broken at the first receipt'
            previous = record
        return 'intact'

    def withdraw(self, imprint_id):
        imprint_id = self._resolve(imprint_id)
        return self._act(imprint_id, 'withdraw', {})

    def shorten(self, imprint_id, days):
        imprint_id = self._resolve(imprint_id)
        if type(days) is not int or not 0 < days <= 365:
            raise ImprintRefused('Give a number of days from 1 to 365.')
        return self._act(imprint_id, 'shorten', {'valid_until': int(time.time()) + days * 86400})

    def _act(self, imprint_id, verb, body):
        done = self.client.request('POST', f'/api/imprints/{self._request_id(imprint_id)}/{verb}', body=body)
        if isinstance(done, dict) and done.get('status') in FINAL:
            self._drop_local_copy(imprint_id)
        return done


def _canonical(value):
    """The peer's canonical JSON: sorted keys, no spaces, UTF-8 as it is."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _package_of(path):
    """The manifest's `package`: its parts a list of digests, `part_bytes` and `bytes` whole numbers. A manifest that
    is not one is refused before anything is sent, not a traceback (the review's Task 43a item)."""
    try:
        package = json.loads(path.read_text())['package']
        ok = (isinstance(package['parts'], list) and all(isinstance(p, str) for p in package['parts'])
              and type(package['part_bytes']) is int and type(package['bytes']) is int)
    except (OSError, ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise ImprintRefused('This imprint\'s manifest.json cannot be read; nothing was sent. Run the plan and '
                             'make imprint-send again.')
    return package


def _shown(value, limit=80):
    """Station text as one printable line: no control or escape characters, no newline, at most `limit` long."""
    return label(value, limit)


def _receipts_of(found):
    """The station's receipts in seq order. Each is an object whose `seq` is an int from 0 to 2**53, none repeated,
    and whose `record` is an object; anything else is refused before a file name is made from it (review I2)."""
    if not isinstance(found, dict):
        raise ImprintRefused(MALFORMED, 1)
    receipts = found.get('receipts')
    receipts = [] if receipts is None else receipts
    if not isinstance(receipts, list) or not all(
            isinstance(r, dict) and type(r.get('seq')) is int and 0 <= r['seq'] <= MAX_SEQ
            and isinstance(r.get('record'), dict) for r in receipts):
        raise ImprintRefused(MALFORMED, 1)
    if len({r['seq'] for r in receipts}) != len(receipts):
        raise ImprintRefused(MALFORMED, 1)
    return sorted(receipts, key=lambda r: r['seq'])


def _receipt_path(folder, seq, imprint_id):
    """`<seq>-<imprint id>.json` inside `folder`, made from the integer; a name that would leave it is refused."""
    path = folder / f'{int(seq):d}-{imprint_id}.json'
    if path.parent != folder or path.name != f'{int(seq):d}-{imprint_id}.json':
        raise ImprintRefused(MALFORMED, 1)
    return path


def _date(seconds):
    if type(seconds) not in (int, float):
        return 'unknown'
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%d')
    except (OverflowError, OSError, ValueError):
        return 'unknown'


def _end_of(found, receipts):
    """The earliest of the permission's records' ends and every shortening's (I 8 item 4)."""
    permission = found.get('permission') if isinstance(found, dict) else None
    record = permission.get('record') if isinstance(permission, dict) else None
    records = record.get('records') if isinstance(record, dict) else None
    ends = [r.get('valid_until') for r in records if isinstance(r, dict)] if isinstance(records, list) else []
    ends += [r['record']['detail'].get('valid_until') for r in receipts
             if r['record'].get('event') == 'shortened' and isinstance(r['record'].get('detail'), dict)]
    ends = [e for e in ends if type(e) is int]
    return min(ends) if ends else None
