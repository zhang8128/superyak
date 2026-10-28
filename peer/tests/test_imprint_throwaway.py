"""The throwaway-store test (test A, before Andy's own store; City of AI, 2026-10-27): 20 synthetic memories with a
canary each, an exclude file run through the real --exclude path, the refusal of a typo and of a right id in upper
case ("2 of the 4 ids"), then 3 of 3 matched and 17 of 20 sent; the owner's yes, the approval, admission; the 3
excluded canaries in no file on the station and the 17 kept ones in the admitted store (the control); then the source
store deleted, and the receipts fetched, verified and imported on their own, twice. Set IMPRINT_THROWAWAY_REPORT to a
path to keep every count as JSON. Skipped in the standalone peer bundle, as the end-to-end test is. Tardis wrote it."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
AGENT, ENGRAM, PEER = REPO / 'agent', REPO / 'engram', REPO / 'peer'
pytestmark = pytest.mark.skipif(not (AGENT / 'superyak_agent').is_dir() or not (ENGRAM / 'imprint.py').is_file(),
                                reason='needs agent/ and engram/ from the full repository')
if (AGENT / 'superyak_agent').is_dir():
    sys.path[:0] = [str(AGENT), str(AGENT.parent / 'team')]

from imprint_support import station
from test_imprint_confirm import confirm

REPORT = os.environ.get('IMPRINT_THROWAWAY_REPORT')
TAG = uuid.uuid4().hex[:12]
EXCLUDED = ('e03', 'e07', 'e15')
MAKE_SOURCE = '''
import sys
from pathlib import Path
from tests.imprint_support import ep, new_store, vec
store = new_store(Path(sys.argv[1]), "src")
tag, excluded = sys.argv[2], set(sys.argv[3].split(","))
for i in range(1, 21):
    mid = f"e{i:02d}"
    kind = "excl" if mid in excluded else "kept"
    ep(store, mid, content=f"{kind}-canary-{tag}-{mid} voyage note {i}", session="sx",
       at=f"2026-10-25T10:{i:02d}:00+00:00")
    vec(store, "episode", mid, seed=i)
store.conn.commit()
store.close()
'''
MAKE_LEDGER = '''
import sys
from pathlib import Path
from permission_ledger import Ledger
Ledger.create(Path(sys.argv[1]), "sam", now=1761415451).close()
'''
PEER_VERIFY = f'uv run --locked --project {PEER} python -m superyak_peer verify-imprint'
SCOPE = ['--lanes', 'work', '--layers', 'episode', '--until', '2026-10-27T00:00:00Z', '--audience', 'place:home/andy']


def clean_env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ('VIRTUAL_ENV', 'ENGRAM_HOME', 'SUPERYAK_HOME')}
    return {**env, 'HOME': str(tmp_path / 'user-home'), 'PYTHONDONTWRITEBYTECODE': '1'}


def run(cmd, cwd, env):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def scan(root, needles):
    """{needle: [files holding it]} over every file under root."""
    found = {n: [] for n in needles}
    for path in (p for p in Path(root).rglob('*') if p.is_file()):
        data = path.read_bytes()
        for n in needles:
            if n.encode() in data:
                found[n].append(str(path.relative_to(root)))
    return found


def test_throwaway_store_a(tmp_path, monkeypatch):
    from superyak_agent import imprint as imprint_module
    from superyak_agent.imprint import Imprint
    from superyak_agent.station import StationClient

    report = {'tag': TAG}
    env = clean_env(tmp_path)
    (tmp_path / 'user-home').mkdir()
    home, engram_home = tmp_path / 'superyak', tmp_path / 'engram-home'
    made = run(['uv', 'run', '--locked', 'python', '-c', 'import sys; sys.path.insert(0, "."); exec(sys.argv.pop(1))',
                MAKE_SOURCE, str(tmp_path), TAG, ','.join(EXCLUDED)], ENGRAM, env)
    assert made.returncode == 0, made.stderr
    source = tmp_path / 'src.db'

    def engram(*args):
        return run(['uv', 'run', '--locked', 'python', 'imprint.py', *args], ENGRAM, env)

    def plan(*extra, as_json=True):
        return engram('plan', '--store', str(source), '--engram-home', str(engram_home), '--superyak-home', str(home),
                      *SCOPE, *extra, *(['--json'] if as_json else []))

    now = [1000.0]
    monkeypatch.setattr(imprint_module, 'time', SimpleNamespace(time=lambda: now[0],
                        sleep=lambda seconds: now.__setitem__(0, now[0] + 10_000)))
    st = station(tmp_path)

    def transport(method, url, headers, data):
        response = st.voyager.request(method, url.removeprefix('http://testserver'), headers=headers, content=data)
        return response.status_code, response.content

    agent = Imprint(home, StationClient('http://testserver', transport=transport), out=lambda *a: None)
    agent.context()

    # 1. The exclude file Andy's way, 4 ids: 2 right, a typo, and a right id in upper case.
    exclude = tmp_path / 'exclude.txt'
    exclude.write_text('e03\ne07\ne7x\nE15\n')
    refused = plan('--exclude', str(exclude), as_json=False)
    report['first'] = {'file': exclude.read_text().split(), 'exit': refused.returncode,
                       'said': (refused.stdout + refused.stderr).strip()}
    assert refused.returncode != 0
    assert report['first']['said'].startswith('2 of the 4 ids in --exclude name no memory')
    assert "'e7x'" in report['first']['said'] and "'E15'" in report['first']['said']
    assert "'e03'" not in report['first']['said'] and "'e07'" not in report['first']['said']

    # 2. Fixed: 3 of 3 match, and 17 of the 20 go.
    exclude.write_text('e03\ne07\ne15\n')
    dry = plan('--exclude', str(exclude), as_json=False)
    planned = plan('--exclude', str(exclude))
    assert dry.returncode == 0 and planned.returncode == 0, dry.stderr + planned.stderr
    saved_plan = json.loads(planned.stdout)
    report['second'] = {'file': exclude.read_text().split(), 'dry_run': dry.stdout.strip(),
                        'plan_counts': saved_plan.get('counts'), 'plan_exclude': saved_plan.get('exclude')}
    plan_id = saved_plan['id']

    # 3. Build, send, the owner's yes, the approval, admission.
    built = engram('build', '--plan', plan_id, '--superyak-home', str(home), '--engram-home', str(engram_home))
    assert built.returncode == 0, built.stderr
    report['send_1'] = agent.send(plan_id[:8])
    folder = next(p.parent for p in (home / 'imprints').glob('*/send.json'))
    imprint_id = folder.name
    saved = json.loads((folder / 'send.json').read_text())
    report['confirm'] = confirm(st.sam, {'id': saved['request_id'], 'code': saved['code']}).status_code
    report['send_2'] = agent.send(plan_id[:8])
    st.store.station_decide('andy', saved['request_id'][:4], True, imprints_root=st.root)
    report['admit_begin'] = st.store.station_imprint_admit_begin(imprint_id, root=st.root, operator='andy')['allowed']
    admitted = engram('admit', '--id', imprint_id, '--imprints-dir', str(st.root), '--verify-cmd', PEER_VERIFY)
    report['admit'] = {'exit': admitted.returncode, 'said': (admitted.stdout + admitted.stderr).strip()[-1500:]}
    assert admitted.returncode == 0, admitted.stdout + admitted.stderr
    st.store.station_imprint_sync(root=st.root)
    report['send_3'] = agent.send(plan_id[:8])

    # 4. The excluded memories are nowhere on the station; the kept ones are in the admitted store (the control).
    excluded = [f'excl-canary-{TAG}-{m}' for m in EXCLUDED]
    kept = [f'kept-canary-{TAG}-e{i:02d}' for i in range(1, 21) if f'e{i:02d}' not in EXCLUDED]
    station_files = {**scan(st.root, excluded + kept), **{}}
    peer_db = scan(tmp_path / 'peer', excluded + kept)
    report['excluded_found_on_station'] = {n: station_files[n] + peer_db[n] for n in excluded}
    report['kept_found_in_imprints_dir'] = sum(1 for n in kept if station_files[n])
    report['kept_found_in_station_db'] = sum(1 for n in kept if peer_db[n])
    report['owner_folder_after_admission'] = sorted(p.name for p in folder.iterdir())

    # 5. The source store goes; the receipts stand on their own.
    for gone in [p for p in tmp_path.iterdir() if p.name.startswith(('src.db', 'cold.db'))]:  # with -wal and -shm
        gone.unlink()
    report['source_left'] = sorted(p.name for p in tmp_path.glob('src*'))
    report['status_after_delete'] = agent.status(imprint_id[:8])  # as make imprint-status does: fetch, then verify
    report['owner_folder_after_status'] = sorted(p.name for p in folder.iterdir())
    verify = run([sys.executable, '-m', 'superyak_peer', 'verify-imprint', '--dir', str(folder), '--home', str(home)],
                 PEER, env)
    report['verify_after_delete'] = {'exit': verify.returncode, 'said': (verify.stdout + verify.stderr).strip()[-800:]}
    ledger = run(['uv', 'run', '--locked', 'python', '-c', 'import sys; sys.path.insert(0, "."); exec(sys.argv.pop(1))',
                  MAKE_LEDGER, str(engram_home)], ENGRAM, env)
    assert ledger.returncode == 0, ledger.stderr
    imported = engram('import-receipts', '--id', imprint_id[:8], '--superyak-home', str(home),
                      '--engram-home', str(engram_home))
    again = engram('import-receipts', '--id', imprint_id[:8], '--superyak-home', str(home),
                   '--engram-home', str(engram_home))
    report['import_receipts'] = {'exit': imported.returncode, 'said': (imported.stdout + imported.stderr).strip(),
                                 'again_exit': again.returncode, 'again_said': (again.stdout + again.stderr).strip()}
    report['receipts'] = sorted(p.name for p in folder.joinpath('receipts').glob('*.json'))
    if REPORT:
        Path(REPORT).write_text(json.dumps(report, indent=2))

    assert report['second']['plan_counts']['excluded'] == 3 and report['second']['plan_counts']['exclude_ids'] == 3
    assert 'Episodes            17' in report['second']['dry_run']
    assert (report['send_1'], report['confirm'], report['send_2'], report['admit_begin'], report['send_3']) == (
        'waiting-for-you', 200, 'received', True, 'admitted')
    assert all(not found for found in report['excluded_found_on_station'].values())
    assert report['kept_found_in_imprints_dir'] == 17 and report['kept_found_in_station_db'] == 0
    assert report['source_left'] == [] and report['status_after_delete']['chain'] == 'intact'
    assert verify.returncode == 0 and 'receipts verified, 0 not yet signed; key pinned' in report['verify_after_delete']['said']
    assert imported.returncode == 0 and imported.stdout.strip() == f"{len(report['receipts'])} uses imported."
    assert again.returncode == 0 and again.stdout.strip() == '0 uses imported.'
