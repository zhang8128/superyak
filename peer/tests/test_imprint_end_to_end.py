"""One imprint end to end, in a temporary directory: the plan and build on a source store (the engram commands, in
their own project), the send through a test station, the owner's yes, the approval, admission, a second look at the
status, the withdrawal and the saved receipts checked (store-imprint spec I 6 to 13; plan Task 49). Nothing live.
Skipped in the standalone peer bundle, as test_ship_agent.py is."""
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

MAKE_SOURCE = '''
import sys
from pathlib import Path
from tests.imprint_support import ep, new_store, sem, vec
store = new_store(Path(sys.argv[1]), "src")
for i in range(1, 4):
    ep(store, f"e{i}", content=f"{sys.argv[2]} voyage note {i}", session="sx", at=f"2026-10-25T10:0{i}:00+00:00")
    vec(store, "episode", f"e{i}", seed=i)
sem(store, "s1", sources=["e1"], at="2026-10-25T12:00:00+00:00")
vec(store, "semantic", "s1", seed=99)
store.conn.commit()
store.close()
'''
PEER_VERIFY = f'uv run --locked --project {PEER} python -m superyak_peer verify-imprint'
FLAGS = ['--lanes', 'work', '--layers', 'episode,semantic', '--until', '2026-10-27T00:00:00Z',
         '--audience', 'place:home/andy', '--json']


def clean_env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ('VIRTUAL_ENV', 'ENGRAM_HOME', 'SUPERYAK_HOME')}
    return {**env, 'HOME': str(tmp_path / 'user-home'), 'PYTHONDONTWRITEBYTECODE': '1'}


def run(cmd, cwd, env, **kw):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600, **kw)


def test_an_imprint_end_to_end(tmp_path, monkeypatch):
    from superyak_agent import imprint as imprint_module
    from superyak_agent.imprint import Imprint
    from superyak_agent.station import StationClient

    env = clean_env(tmp_path)
    (tmp_path / 'user-home').mkdir()
    home, engram_home = tmp_path / 'superyak', tmp_path / 'engram-home'
    canary = 'canary-' + uuid.uuid4().hex
    made = run(['uv', 'run', '--locked', 'python', '-c', 'import sys; sys.path.insert(0, "."); exec(sys.argv.pop(1))',
                MAKE_SOURCE, str(tmp_path), canary], ENGRAM, env)
    assert made.returncode == 0, made.stderr
    source = tmp_path / 'src.db'

    def engram(*args):
        return run(['uv', 'run', '--locked', 'python', 'imprint.py', *args], ENGRAM, env)

    # No sleeping: the first send finds the owner has not said yes and gives up waiting.
    now = [1000.0]
    monkeypatch.setattr(imprint_module, 'time', SimpleNamespace(time=lambda: now[0],
                        sleep=lambda seconds: now.__setitem__(0, now[0] + 10_000)))     # this module's clock only

    st = station(tmp_path)

    def transport(method, url, headers, data):
        response = st.voyager.request(method, url.removeprefix('http://testserver'), headers=headers, content=data)
        return response.status_code, response.content

    agent = Imprint(home, StationClient('http://testserver', transport=transport), out=lambda *a: None)
    agent.context()
    planned = engram('plan', '--store', str(source), '--engram-home', str(engram_home), '--superyak-home', str(home), *FLAGS)
    assert planned.returncode == 0, planned.stderr
    plan = json.loads(planned.stdout)['id']
    built = engram('build', '--plan', plan, '--superyak-home', str(home), '--engram-home', str(engram_home))
    assert built.returncode == 0, built.stderr

    assert agent.send(plan[:8]) == 'waiting-for-you'
    folder = next(p.parent for p in (home / 'imprints').glob('*/send.json'))
    imprint_id = folder.name
    saved = json.loads((folder / 'send.json').read_text())
    assert (folder / 'imprint.db').is_file()
    # The owner says yes in the browser, with the password and the ticked check.
    assert confirm(st.sam, {'id': saved['request_id'], 'code': saved['code']}).status_code == 200
    assert agent.send(plan[:8]) == 'received'
    st.store.station_decide('andy', saved['request_id'][:4], True, imprints_root=st.root)
    assert st.store.station_imprint_admit_begin(imprint_id, root=st.root, operator='andy')['allowed'] is True
    admitted = engram('admit', '--id', imprint_id, '--imprints-dir', str(st.root), '--verify-cmd', PEER_VERIFY)
    assert admitted.returncode == 0, admitted.stdout + admitted.stderr
    st.store.station_imprint_sync(root=st.root)
    assert agent.send(plan[:8]) == 'admitted'
    assert not (folder / 'imprint.db').exists()                    # the local copy goes once the imprint is admitted
    raw = (tmp_path / 'peer' / 'peer.sqlite3').read_bytes()
    assert canary.encode() not in raw and b'"scope"' not in raw    # the station's database holds no memory text

    agent.withdraw(imprint_id[:8])
    assert not (st.root / imprint_id).exists() and (st.root / 'tombstones' / f'{imprint_id}.json').is_file()
    assert agent.status(imprint_id[:8])['status'] == 'deleted'
    verify = run([sys.executable, '-m', 'superyak_peer', 'verify-imprint', '--dir', str(folder), '--home', str(home)],
                 PEER, env)
    assert verify.returncode == 0, verify.stdout + verify.stderr
    last = max(folder.joinpath('receipts').glob('*.json'), key=lambda p: int(p.name.split('-')[0]))
    assert json.loads(last.read_text())['record']['event'] == 'deleted'
