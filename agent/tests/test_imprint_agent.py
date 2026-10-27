"""Task 43a: the agent's `imprint context` and `send` (store-imprint I 9, 13, D24, RF5)."""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import pytest

from superyak_agent import imprint as imprint_module
from superyak_agent.imprint import Imprint
from superyak_agent.station import StationClient, StationError

IMPRINT_ID = '5b0e7f3a-1c2d-4e5f-8a9b-0c1d2e3f4a5b'
REQUEST_ID = 'a1b2c3d4-0000-4000-8000-000000000001'
PLAN = '7c41'
PLAN_FILE = '7c41aa00bb11cc22'
PART = 4
Call = namedtuple('Call', 'method path body')
NOW = 1000          # the fake clock's start (fast_waits)
PERMISSION = {'kind': 'imprint-permission', 'records': [{'valid_until': NOW + 90 * 86400}]}


@pytest.fixture(autouse=True)
def fast_waits(monkeypatch):
    """A fake clock: every sleep jumps past any wait, so a waiting send polls once and returns."""
    now = [1000.0]
    monkeypatch.setattr(imprint_module.time, 'time', lambda: now[0])
    monkeypatch.setattr(imprint_module.time, 'sleep', lambda seconds: now.__setitem__(0, now[0] + 10_000))


class FakeStation:
    def __init__(self, status='requested', holds=(), reason=None, receipts=None, extra=None):
        self.status, self.holds, self.reason = status, list(holds), reason
        self.receipts, self.extra = receipts, extra or {}
        self.calls, self.part_bodies, self.labels = [], {}, []

    def allow(self):
        self.status = 'allowed'

    def paths(self):
        return [c.path for c in self.calls]

    def last_body(self):
        return json.loads(self.calls[-1].body)

    def order(self):
        return self.labels

    def client(self):
        return StationClient('http://station', 'key', transport=self.transport)

    def transport(self, method, url, headers, data):
        path = url[len('http://station'):]
        self.calls.append(Call(method, path, data))
        if method == 'GET' and path == '/api/imprints':
            return 200, json.dumps({'ship': 'rio', 'owner': 'andy', 'operator': 'andy', 'station': 'st', 'imprints': []}).encode()
        if method == 'POST' and path == '/api/imprints':
            return 201, json.dumps({'id': REQUEST_ID, 'code': 'AB12CD34', 'expires': 5000,
                                    'confirm_url': 'http://station/#imprint?code=AB12CD34'}).encode()
        if method == 'GET' and path == f'/api/imprints/{REQUEST_ID}':
            receipts = []
            if self.reason:
                receipts = [{'seq': 3, 'record': {'event': 'deleted', 'detail': {'reason': self.reason}}, 'signature': None}]
            doc = {'status': self.status, 'held': self.holds, 'receipts': receipts}
            if self.receipts is not None:
                doc.update({'receipts': self.receipts, 'permission': {'record': PERMISSION, 'signature': 'p', 'station_key': 'k'},
                            'calibration_report': None, 'use_reports': [], 'keeps': None, **self.extra})
            return 200, json.dumps(doc).encode()
        if method == 'POST' and path == f'/api/imprints/{REQUEST_ID}/withdraw':
            self.status = 'deleted'
            return 200, json.dumps({'id': REQUEST_ID, 'status': 'deleted'}).encode()
        if method == 'POST' and path == f'/api/imprints/{REQUEST_ID}/shorten':
            return 200, json.dumps({'id': REQUEST_ID, 'valid_until': json.loads(data)['valid_until']}).encode()
        if method == 'PUT' and path.endswith('/manifest'):
            self.labels.append('manifest')
            return 200, b'{"parts": 3}'
        if method == 'PUT' and '/parts/' in path:
            n = int(path.rsplit('/', 1)[1])
            self.labels.append(f'part {n}')
            self.part_bodies[n] = data
            self.holds.append(n)
            return 200, json.dumps({'held': sorted(self.holds)}).encode()
        if method == 'POST' and path.endswith('/complete'):
            self.labels.append('complete')
            self.status = 'received'
            return 200, b'{"status": "received"}'
        return 404, b'{"error": "No such route"}'


def chain(n, drop=None, unsigned=()):
    """n receipts, seq 1..n, each `previous` the SHA-256 of the last one's canonical record (the first, the permission's);
    `drop` leaves one seq out, as a lost row would."""
    def digest(record):
        return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    out, previous = [], PERMISSION
    for seq in range(1, n + 1):
        record = {'kind': 'imprint-receipt', 'id': f'r{seq}', 'permission': REQUEST_ID,
                  'event': 'shortened' if seq == 3 else 'admitted',
                  'at': NOW + seq, 'detail': {'valid_until': NOW + 30 * 86400} if seq == 3 else {}, 'previous': digest(previous)}
        out.append({'seq': seq, 'record': record, 'signature': None if seq in unsigned else 'sig'})
        previous = record
    return [r for r in out if r['seq'] != drop]


def built_home(tmp_path, parts=1):
    home = tmp_path / 'superyak'
    local = home / 'imprints' / IMPRINT_ID
    local.mkdir(parents=True, mode=0o700)
    (home / 'imprints' / 'plans').mkdir(mode=0o700)
    data = b''.join(bytes([97 + n]) * PART for n in range(parts))
    (local / 'imprint.db').write_bytes(data)
    os.chmod(local / 'imprint.db', 0o400)
    hashes = [hashlib.sha256(data[n * PART:(n + 1) * PART]).hexdigest() for n in range(parts)]
    manifest = {'kind': 'engram-imprint-manifest', 'package': {'file': 'imprint.db', 'bytes': len(data), 'part_bytes': PART,
                                                                'sha256': hashlib.sha256(data).hexdigest(), 'parts': hashes}}
    (local / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
    (local / 'request.json').write_text(json.dumps({'imprint_id': IMPRINT_ID}, sort_keys=True))
    for name in ('objects.json', 'subjects.json'):
        (local / name).write_text('')
    (home / 'imprints' / 'plans' / f'{PLAN_FILE}.json').write_text(json.dumps({'id': PLAN_FILE, 'imprint_id': IMPRINT_ID}))
    (home / 'station.json').write_text(json.dumps({'station': 'http://station', 'key': 'key'}))
    return home


def sent_home(tmp_path):
    home = built_home(tmp_path)
    (home / 'imprints' / IMPRINT_ID / 'send.json').write_text(json.dumps(
        {'request_id': REQUEST_ID, 'imprint_id': IMPRINT_ID, 'code': 'AB12CD34', 'expires': 5000, 'confirm_url': 'x'}))
    return home


def held_lock(path):
    class Held:
        def __enter__(self):
            self.f = open(path, 'a+')
            fcntl.flock(self.f, fcntl.LOCK_EX)
        def __exit__(self, *exc):
            self.f.close()
    return Held()


def run_agent(argv, home):
    env = {**os.environ, 'HOME': str(home.parent)}
    script = Path(__file__).resolve().parents[1] / 'run_agent.py'
    return subprocess.run([sys.executable, str(script), *argv, '--home', str(home)], env=env, capture_output=True, text=True)


def test_nothing_of_the_package_leaves_before_the_yes(tmp_path):
    station, home = FakeStation(), built_home(tmp_path)
    assert Imprint(home, station.client()).send(PLAN) == 'waiting-for-you'
    assert [c.method for c in station.calls] == ['POST', 'GET'] and not station.part_bodies
    saved = json.loads((home / 'imprints' / IMPRINT_ID / 'send.json').read_text())
    assert saved['request_id'] == REQUEST_ID and saved['code'] == 'AB12CD34'
    assert station.calls[0].body == (home / 'imprints' / IMPRINT_ID / 'request.json').read_bytes()


def test_the_ids_the_code_and_the_link_are_printed(tmp_path):
    lines = []
    Imprint(built_home(tmp_path), FakeStation().client(), out=lines.append).send(PLAN)
    text = '\n'.join(lines)
    assert IMPRINT_ID[:4] in text and REQUEST_ID[:4] in text and 'AB12CD34' in text and '#imprint?code=AB12CD34' in text


def test_after_the_yes_it_sends_the_manifest_then_the_missing_parts(tmp_path):
    station, home = FakeStation(holds=[0]), built_home(tmp_path, parts=3)
    station.allow()
    (home / 'imprints' / IMPRINT_ID / 'send.json').write_text(json.dumps({'request_id': REQUEST_ID, 'imprint_id': IMPRINT_ID}))
    assert Imprint(home, station.client()).send(PLAN) == 'received'
    assert station.order() == ['manifest', 'part 1', 'part 2', 'complete']
    assert station.part_bodies == {1: b'bbbb', 2: b'cccc'}


def test_the_first_run_after_an_instant_yes_posts_then_uploads(tmp_path):
    station, home = FakeStation(status='allowed'), built_home(tmp_path)
    assert Imprint(home, station.client()).send(PLAN) == 'received'
    assert [c.method for c in station.calls][:2] == ['POST', 'GET'] and station.order() == ['manifest', 'part 0', 'complete']


def test_later_runs_report_and_drop_the_local_copy(tmp_path):
    station, home = FakeStation(status='admitted'), sent_home(tmp_path)
    assert Imprint(home, station.client()).send(PLAN) == 'admitted'
    local = home / 'imprints' / IMPRINT_ID
    assert not (local / 'imprint.db').exists() and {p.name for p in local.iterdir()} >= {'manifest.json', 'objects.json'}
    assert [c.method for c in station.calls] == ['GET']      # never posted again


def test_a_deleted_imprint_is_reported_by_its_reason(tmp_path):
    station, home = FakeStation(status='deleted', reason='denied'), sent_home(tmp_path)
    lines = []
    assert Imprint(home, station.client(), out=lines.append).send(PLAN) == 'denied'
    assert not (home / 'imprints' / IMPRINT_ID / 'imprint.db').exists()
    station2, home2 = FakeStation(status='deleted', reason='withdrawn'), sent_home(tmp_path / 'b')
    assert Imprint(home2, station2.client()).send(PLAN) == 'deleted'


def test_a_pending_imprint_keeps_its_local_copy(tmp_path):
    station, home = FakeStation(status='received'), sent_home(tmp_path)
    assert Imprint(home, station.client()).send(PLAN) == 'received'
    assert (home / 'imprints' / IMPRINT_ID / 'imprint.db').exists()


def test_context_is_saved_private(tmp_path):
    station, home = FakeStation(), tmp_path / 'superyak'
    got = Imprint(home, station.client()).context()
    path = home / 'imprints' / 'context.json'
    assert got['operator'] == 'andy' and json.loads(path.read_text()) == got and path.stat().st_mode & 0o777 == 0o600


def test_rf5_two_sends_of_one_plan_never_interleave(tmp_path):
    home = built_home(tmp_path)
    with held_lock(home / 'imprints' / IMPRINT_ID / 'send.lock'):
        done = run_agent(['imprint', 'send', '--plan', PLAN], home=home)
    assert done.returncode == 4 and 'Another make imprint-send of this plan is running.' in done.stdout
    assert not (home / 'imprints' / IMPRINT_ID / 'send.json').exists()


def test_an_unbuilt_plan_is_refused(tmp_path):
    home = built_home(tmp_path)
    (home / 'imprints' / 'plans' / f'{PLAN_FILE}.json').write_text(json.dumps({'id': PLAN_FILE}))
    done = run_agent(['imprint', 'send', '--plan', PLAN], home=home)
    assert done.returncode == 2 and 'not built' in done.stdout + done.stderr


def test_status_saves_receipts_and_finds_a_broken_chain(tmp_path):
    station, home = FakeStation(receipts=chain(4, drop=2)), sent_home(tmp_path)
    out = Imprint(home, station.client()).status(IMPRINT_ID)
    assert out["chain"] == "broken after receipt 1" and len(list((home / "imprints" / IMPRINT_ID / "receipts").iterdir())) == 3


def test_status_saves_the_signed_permission_for_verify_imprint(tmp_path):
    station, home = FakeStation(receipts=chain(2)), sent_home(tmp_path)
    Imprint(home, station.client()).status(IMPRINT_ID)
    saved = home / 'imprints' / IMPRINT_ID / 'permission.json'
    assert json.loads(saved.read_text()) == {'record': PERMISSION, 'signature': 'p', 'station_key': 'k'}
    assert saved.stat().st_mode & 0o777 == 0o600


def test_status_saves_no_permission_when_the_station_sends_none(tmp_path):
    station, home = FakeStation(status='received'), sent_home(tmp_path)
    Imprint(home, station.client()).status(IMPRINT_ID)
    assert not (home / 'imprints' / IMPRINT_ID / 'permission.json').exists()


def test_withdraw_and_shorten_call_the_station(tmp_path):
    station, home = FakeStation(), sent_home(tmp_path)
    Imprint(home, station.client()).withdraw(IMPRINT_ID); Imprint(home, station.client()).shorten(IMPRINT_ID, 30)
    assert station.paths()[-2:] == [f"/api/imprints/{REQUEST_ID}/withdraw", f"/api/imprints/{REQUEST_ID}/shorten"]
    assert station.last_body() == {"valid_until": NOW + 30 * 86400}


def test_an_intact_chain_is_named_and_unsigned_receipts_say_so(tmp_path):
    station, home = FakeStation(receipts=chain(3, unsigned=(3,))), sent_home(tmp_path)
    lines = []
    out = Imprint(home, station.client(), out=lines.append).status(IMPRINT_ID)
    folder = home / 'imprints' / IMPRINT_ID / 'receipts'
    assert out['chain'] == 'intact' and sorted(p.name for p in folder.iterdir()) == [f'{n}-{IMPRINT_ID}.json' for n in (1, 2, 3)]
    assert any('not yet signed' in line and '3' in line for line in lines)
    assert 'not yet signed' not in json.loads((folder / f'1-{IMPRINT_ID}.json').read_text()).get('note', '')


def test_status_prints_the_reports_and_what_the_station_keeps(tmp_path):
    extra = {'calibration_report': {'score': 0.5}, 'use_reports': [{'use_id': 'u1', 'report': {'rows': 3}}],
             'keeps': {'text': 'The station keeps a row.', 'removed_on': {'row': '2027-01-01'}}}
    station, home = FakeStation(status='admitted', receipts=chain(2), extra=extra), sent_home(tmp_path)
    lines = []
    Imprint(home, station.client(), out=lines.append).status(IMPRINT_ID)
    text = '\n'.join(lines)
    assert '0.5' in text and 'u1' in text and 'The station keeps a row.' in text and '2027-01-01' in text


def test_status_with_no_id_is_one_line_per_imprint(tmp_path):
    station, home = FakeStation(status='admitted', receipts=chain(3)), sent_home(tmp_path)
    lines = []
    out = Imprint(home, station.client(), out=lines.append).status()
    assert len(lines) == 1 and lines[0].startswith(IMPRINT_ID[:4]) and 'admitted' in lines[0]
    assert 'shortened' in lines[0] and '1970-01-31' in lines[0] and out['imprints'][0]['status'] == 'admitted'


def test_a_final_status_drops_the_local_copy_and_an_unknown_imprint_is_refused(tmp_path):
    station, home = FakeStation(status='received'), sent_home(tmp_path)
    Imprint(home, station.client()).withdraw(IMPRINT_ID)
    assert not (home / 'imprints' / IMPRINT_ID / 'imprint.db').exists()
    from superyak_agent.imprint import ImprintRefused
    with pytest.raises(ImprintRefused):
        Imprint(home, station.client()).status('ffff')
    with pytest.raises(ImprintRefused):
        Imprint(home, station.client()).shorten(IMPRINT_ID, 0)


def test_the_command_refuses_days_that_are_not_a_number(tmp_path):
    home = sent_home(tmp_path)
    bad = run_agent(['imprint', 'shorten', '--id', IMPRINT_ID[:4], '--days', 'x'], home=home)
    assert bad.returncode == 2


# ---- Station data is untrusted on the owner's machine (final review I2) ----

ESCAPES = '\x1b[2J\x1b]0;owned\x07\r\n\x00\x9b'


@pytest.mark.parametrize('seq', ['{tmp}/escaped/x', '../../../../escaped', -1, 1.5, True, 2**63, None, '1', [1]])
def test_a_receipt_seq_that_is_not_a_bounded_int_is_refused_and_writes_nothing(tmp_path, seq):
    from superyak_agent.imprint import ImprintRefused
    if isinstance(seq, str):
        seq = seq.format(tmp=tmp_path)
    receipts = chain(2)
    receipts[1]['seq'] = seq
    station, home = FakeStation(receipts=receipts), sent_home(tmp_path)
    with pytest.raises(ImprintRefused):
        Imprint(home, station.client()).status(IMPRINT_ID)
    assert not (home / 'imprints' / IMPRINT_ID / 'receipts').exists()
    assert not [p for p in tmp_path.rglob(f'*-{IMPRINT_ID}.json')]


def test_a_repeated_seq_is_refused(tmp_path):
    from superyak_agent.imprint import ImprintRefused
    receipts = chain(2)
    receipts[1]['seq'] = 1
    station, home = FakeStation(receipts=receipts), sent_home(tmp_path)
    with pytest.raises(ImprintRefused):
        Imprint(home, station.client()).status(IMPRINT_ID)


def test_the_list_names_a_malformed_seq_and_carries_on(tmp_path):
    receipts = chain(2)
    receipts[1]['seq'] = '../x'
    station, home = FakeStation(status='admitted', receipts=receipts), sent_home(tmp_path)
    lines = []
    out = Imprint(home, station.client(), out=lines.append).status()
    assert out['imprints'] == [] and len(lines) == 1 and 'not read' in lines[0]


def test_the_chain_is_unchecked_without_the_permission(tmp_path):
    station, home = FakeStation(receipts=chain(3), extra={'permission': None}), sent_home(tmp_path)
    lines = []
    out = Imprint(home, station.client(), out=lines.append).status(IMPRINT_ID)
    assert out['chain'] == 'unchecked' and 'intact' not in '\n'.join(lines)


def test_a_receipt_of_another_permission_breaks_the_chain(tmp_path):
    receipts = chain(3)
    receipts[1]['record']['permission'] = 'b1b2c3d4-0000-4000-8000-000000000002'
    station, home = FakeStation(receipts=receipts), sent_home(tmp_path)
    assert Imprint(home, station.client()).status(IMPRINT_ID)['chain'] == 'broken at receipt 2'


def no_escapes(lines):
    return all(not any(c in line for c in '\x1b\x07\r\n\x00\x9b') for line in lines)


def test_station_text_is_printed_without_control_characters(tmp_path):
    receipts = chain(2)
    receipts[0]['record']['event'] = 'admitted' + ESCAPES
    extra = {'status': 'admitted' + ESCAPES, 'use_reports': [{'use_id': 'u1' + ESCAPES, 'report': {'rows': 3}}],
             'keeps': {'text': 'The station keeps a row.' + ESCAPES, 'removed_on': {'row' + ESCAPES: '2027-01-01' + ESCAPES}}}
    station, home = FakeStation(receipts=receipts, extra=extra), sent_home(tmp_path)
    lines = []
    Imprint(home, station.client(), out=lines.append).status(IMPRINT_ID)
    Imprint(home, station.client(), out=lines.append).status()
    assert len(lines) > 6 and no_escapes(lines) and 'The station keeps a row.' in '\n'.join(lines)


def test_send_prints_the_code_the_link_and_a_deletion_reason_without_control_characters(tmp_path):
    class Hostile(FakeStation):
        def transport(self, method, url, headers, data):
            status, body = super().transport(method, url, headers, data)
            if method == 'POST' and url.endswith('/api/imprints'):
                body = json.dumps(json.loads(body) | {'code': 'AB12' + ESCAPES, 'confirm_url': 'http://station/#x' + ESCAPES}).encode()
            return status, body
    station, home = Hostile(status='deleted', reason='denied' + ESCAPES), built_home(tmp_path)
    lines = []
    Imprint(home, station.client(), out=lines.append).send(PLAN)
    assert len(lines) == 3 and no_escapes(lines) and 'AB12' in lines[0]


def test_the_command_prints_station_errors_and_states_without_control_characters(tmp_path, monkeypatch, capsys):
    from superyak_agent import station as station_module
    from superyak_agent.__main__ import main

    class Erring(FakeStation):
        def transport(self, method, url, headers, data):
            if method == 'POST':
                return 500, json.dumps({'error': 'boom' + ESCAPES}).encode()
            return 200, json.dumps({'status': 'odd' + ESCAPES, 'held': [], 'receipts': []}).encode()
    monkeypatch.setattr(station_module, 'client_for', lambda config, timeout=30: Erring().client())
    home = sent_home(tmp_path)
    assert main(['imprint', 'withdraw', '--id', IMPRINT_ID[:4], '--home', str(home)]) == 1
    (home / 'imprints' / IMPRINT_ID / 'send.json').unlink()
    assert main(['imprint', 'send', '--plan', PLAN, '--home', str(home)]) == 1
    printed = capsys.readouterr().out
    assert 'boom' in printed and no_escapes(printed.splitlines()) and printed.count('\n') == 2


# ---- The first saved permission is kept (final review M8) ----

def test_the_first_saved_permission_is_kept_and_a_different_one_is_named(tmp_path):
    station, home = FakeStation(receipts=chain(2)), sent_home(tmp_path)
    Imprint(home, station.client()).status(IMPRINT_ID)
    saved = home / 'imprints' / IMPRINT_ID / 'permission.json'
    first = saved.read_text()
    other = {'record': {**PERMISSION, 'records': [{'valid_until': NOW + 365 * 86400}]}, 'signature': 'q', 'station_key': 'k2'}
    station.extra = {'permission': other}
    lines = []
    out = Imprint(home, station.client(), out=lines.append).status(IMPRINT_ID)
    assert saved.read_text() == first and any('saved first' in line for line in lines)
    assert out['chain'] == 'intact'                       # checked against the permission saved first


def test_an_expired_request_is_final_and_drops_the_local_copy(tmp_path):       # D24; final review M9
    station, home = FakeStation(status='expired'), sent_home(tmp_path)
    assert Imprint(home, station.client()).send(PLAN) == 'expired'
    assert not (home / 'imprints' / IMPRINT_ID / 'imprint.db').exists()
    station2, home2 = FakeStation(status='expired', receipts=[]), sent_home(tmp_path / 'b')
    Imprint(home2, station2.client()).status(IMPRINT_ID)
    assert not (home2 / 'imprints' / IMPRINT_ID / 'imprint.db').exists()
