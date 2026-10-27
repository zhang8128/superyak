"""Task 44: the owner's check of a saved imprint, with nothing but local files and no key (I 12, R9, R21)."""
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from superyak_peer.identity import canonical
from superyak_peer.imprints import verify_imprint_dir

PEER = Path(__file__).resolve().parent.parent


def run_peer(argv):
    return subprocess.run([sys.executable, '-m', 'superyak_peer', *argv], cwd=PEER, capture_output=True, text=True, timeout=120)


def make_key():
    key = ed25519.Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(raw).decode(), hashlib.sha256(raw).hexdigest()


def sign(key, record):
    return base64.b64encode(key.sign(canonical(record))).decode()


def inner(n, days=1):
    return {'id': f'r-{n:032x}', 'layer': 'place:home/sam', 'effect': 'allow', 'selector': {}, 'valid_from': 1,
            'valid_until': 1 + days * 86400,
            'anchor': 1, 'backing': 'person', 'set_by': 'person:sam', 'channel': 'browser', 'under_grant': None,
            'proposal_id': None, 'replaces': None, 'reason': 'x', 'created': 1}


def permission_record(station):
    return {'kind': 'imprint-permission', 'station': station, 'id': 'req1', 'owner': 'person:sam', 'owner_id': 'o', 'ship_id': 's',
            'imprint_id': 'c0a8f5e2', 'source_instance_id': '3f2a', 'request_sha256': 'a' * 64, 'plan_digest': 'b' * 64,
            'attestation': 'no-unconsented-others-v1', 'created': 1, 'records': [inner(1)]}


def permission_file(tmp_path, ok=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    key, public, station = make_key()
    record = permission_record(station)
    signature = sign(key, record)
    if not ok:
        record['owner_id'] = 'someone-else'
    path = tmp_path / 'permission.json'
    path.write_text(json.dumps({'record': record, 'signature': signature, 'station_key': public}))
    return path


IMPRINT = 'c0a8f5e2'
REQUEST = {'kind': 'engram-imprint-request', 'imprint_id': IMPRINT, 'terms': {'days': 1}}


def saved_imprint(parent, receipts=3, new_key=False, unsigned_last=False, request=REQUEST):
    """What `make imprint-status` leaves in `parent/<imprint id>/`: request.json (what this machine sent),
    permission.json and receipts/<seq>-<imprint id>.json."""
    folder = parent / IMPRINT
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'request.json').write_bytes(json.dumps(request, sort_keys=True).encode())
    key, public, station = make_key()
    if not new_key:
        # the same station for every imprint of one test home: a fixed seed
        key = ed25519.Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b'station').digest())
        raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        public, station = base64.b64encode(raw).decode(), hashlib.sha256(raw).hexdigest()
    permission = permission_record(station) | {'request_sha256': hashlib.sha256(
        json.dumps(request, sort_keys=True).encode()).hexdigest()}
    (folder / 'permission.json').write_text(json.dumps({'record': permission, 'signature': sign(key, permission), 'station_key': public}))
    (folder / 'receipts').mkdir()
    previous = permission
    for seq in range(1, receipts + 1):
        record = {'kind': 'imprint-receipt', 'station': station, 'id': f'rc-{seq}', 'permission': 'req1', 'event': 'received',
                  'actor_id': 'o', 'at': 100 + seq, 'detail': {}, 'previous': hashlib.sha256(canonical(previous)).hexdigest()}
        signature = None if unsigned_last and seq == receipts else sign(key, record)
        (folder / 'receipts' / f'{seq}-c0a8f5e2.json').write_text(json.dumps({'seq': seq, 'record': record, 'signature': signature}))
        previous = record
    return folder


def verified(d):
    return json.loads((d / 'verified.json').read_text())['verified']


def test_a_removed_receipt_is_detected(tmp_path):
    d = saved_imprint(tmp_path / 'i', receipts=5)
    (d / 'receipts' / sorted(os.listdir(d / 'receipts'))[2]).unlink()
    out = verify_imprint_dir(d, home=tmp_path / 'home')
    assert out['chain'] == 'broken' and len(verified(d)) == 2


def test_a_changed_station_key_is_a_loud_warning_not_a_pass(tmp_path):
    verify_imprint_dir(saved_imprint(tmp_path / 'a'), home=tmp_path / 'home')
    b = saved_imprint(tmp_path / 'b', new_key=True)
    done = run_peer(['verify-imprint', '--dir', str(b), '--home', str(tmp_path / 'home')])
    assert done.returncode == 1 and 'station key changed' in done.stdout.lower()
    assert verified(b) == []


def test_the_same_key_passes_and_the_pin_is_written_once(tmp_path):
    a = saved_imprint(tmp_path / 'a')
    assert verify_imprint_dir(a, home=tmp_path / 'home')['pin'] == 'pinned'
    pin = (tmp_path / 'home' / 'imprints' / 'station-key.json').read_text()
    b = saved_imprint(tmp_path / 'b')
    assert verify_imprint_dir(b, home=tmp_path / 'home')['pin'] == 'matches'
    assert (tmp_path / 'home' / 'imprints' / 'station-key.json').read_text() == pin
    assert run_peer(['verify-imprint', '--dir', str(a), '--home', str(tmp_path / 'home')]).returncode == 0
    assert verified(a) == ['rc-1', 'rc-2', 'rc-3']


def test_unsigned_receipts_are_not_verified(tmp_path):
    d = saved_imprint(tmp_path, receipts=3, unsigned_last=True)
    verify_imprint_dir(d, home=tmp_path / 'h')
    assert len(verified(d)) == 2


def test_a_forged_or_foreign_signature_is_not_verified(tmp_path):
    d = saved_imprint(tmp_path / 'i', receipts=3)
    path = d / 'receipts' / '2-c0a8f5e2.json'
    doc = json.loads(path.read_text())
    doc['record']['detail'] = {'edited': True}
    path.write_text(json.dumps(doc))
    out = verify_imprint_dir(d, home=tmp_path / 'h')
    assert verified(d) == ['rc-1'] and out['chain'] == 'broken'


def test_a_permission_that_does_not_verify_verifies_nothing_and_pins_nothing(tmp_path):
    d = saved_imprint(tmp_path / 'i')
    doc = json.loads((d / 'permission.json').read_text())
    doc['record']['owner_id'] = 'x'
    (d / 'permission.json').write_text(json.dumps(doc))
    done = run_peer(['verify-imprint', '--dir', str(d), '--home', str(tmp_path / 'h')])
    assert done.returncode == 1 and verified(d) == [] and not (tmp_path / 'h' / 'imprints' / 'station-key.json').exists()


def test_permission_mode(tmp_path):
    good, bad = permission_file(tmp_path, ok=True), permission_file(tmp_path / 'bad', ok=False)
    assert run_peer(['verify-imprint', '--permission', str(good)]).returncode == 0
    assert run_peer(['verify-imprint', '--permission', str(bad)]).returncode == 1
    assert run_peer(['verify-imprint', '--permission', str(tmp_path / 'missing.json')]).returncode == 1


# ---- The signed permission is for what this machine sent (final review M8) ----

def problems_of(d, tmp_path):
    out = verify_imprint_dir(d, home=tmp_path / 'h')
    return out['ok'], out['problems']


def test_a_saved_imprint_that_matches_what_was_sent_passes(tmp_path):
    assert problems_of(saved_imprint(tmp_path / 'i'), tmp_path) == (True, [])


def test_a_permission_for_another_request_is_a_problem(tmp_path):
    d = saved_imprint(tmp_path / 'i')
    (d / 'request.json').write_bytes(json.dumps(REQUEST | {'terms': {'days': 2}}, sort_keys=True).encode())
    ok, problems = problems_of(d, tmp_path)
    assert not ok and any('another request' in p for p in problems)


def test_a_missing_request_is_a_problem(tmp_path):
    d = saved_imprint(tmp_path / 'i')
    (d / 'request.json').unlink()
    ok, problems = problems_of(d, tmp_path)
    assert not ok and any('request.json' in p for p in problems)


def test_a_permission_for_another_imprint_is_a_problem(tmp_path):
    d = saved_imprint(tmp_path / 'i')
    other = d.rename(d.parent / 'ffff0000')
    ok, problems = problems_of(other, tmp_path)
    assert not ok and any('another imprint' in p for p in problems)


def test_a_permission_longer_or_shorter_than_the_days_asked_is_a_problem(tmp_path):
    d = saved_imprint(tmp_path / 'i', request=REQUEST | {'terms': {'days': 2}})     # signed for 1 day, asked for 2
    ok, problems = problems_of(d, tmp_path)
    assert not ok and any('2 days' in p for p in problems)
