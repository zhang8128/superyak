"""Memory, everywhere, for the station's side (store-copy spec I 14.1, 16; plan Task 50, A4, D42, R27).

`test_every_imprint_unit_is_capped_at_512m` runs in every suite. The Pi measurement runs only with ENGRAM_PI_BUDGET=1:
the lighthouse's growth while a 2 GiB package is uploaded part by part and joined, then each peer command of I 14.1's
table as a fresh child under `systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0`, its peak resident size
(`VmHWM`, read as `ru_maxrss` of that one child) under 384 MiB."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import warnings

import pytest

from imprint_support import post, request_doc, station
from test_imprint_confirm import confirm, row
from test_imprint_upload import PART_BYTES, manifest_for_doc, put_manifest, put_part

PEER = Path(__file__).resolve().parents[1]
REPO = PEER.parent
PI = pytest.mark.skipif(os.environ.get('ENGRAM_PI_BUDGET') != '1', reason='Pi measurement (R16, R27)')
PEAK_BUDGET = 384 * 2**20
UNIT_NAME = re.compile(r'--unit=(superyak-imprint-[a-z]+)')


@dataclass
class Unit:
    name: str
    memory_max: str | None
    memory_swap_max: str | None
    limit_data: str | None = None


def units_in_make(text):
    """Each `systemd-run --unit=superyak-imprint-…` line of a Makefile, with the cap its `-p` options set."""
    units = []
    for line in text.splitlines():
        found = UNIT_NAME.search(line)
        if 'systemd-run' in line and found:
            props = dict(p.split('=', 1) for p in re.findall(r'-p ([A-Za-z]+=\S+)', line))
            units.append(Unit(found.group(1), props.get('MemoryMax'), props.get('MemorySwapMax'), props.get('LimitDATA')))
    return units


def unit_in_service(name, text):
    """A `.service` file's [Service] section as a Unit."""
    service = text.split('[Service]', 1)[1] if '[Service]' in text else ''
    props = dict(re.findall(r'^([A-Za-z]+)=(.*)$', service, re.M))
    return Unit(name, props.get('MemoryMax'), props.get('MemorySwapMax'), props.get('LimitDATA'))


def imprint_units_from_the_makefile_and_systemd(repo):
    units = units_in_make((repo / 'Makefile').read_text())
    for path in sorted((repo / 'peer' / 'systemd').glob('superyak-imprint-*.service')):
        units.append(unit_in_service(path.stem, path.read_text()))
    return units


def test_the_unit_readers_see_a_missing_cap():
    assert units_in_make('x:\n\tsystemd-run --user --unit=superyak-imprint-use-$$id -p TimeoutStopSec=60 flock\n') == [
        Unit('superyak-imprint-use', None, None)]
    assert unit_in_service('a', '[Unit]\nMemoryMax=1\n[Service]\nMemoryMax=512M\n') == Unit('a', '512M', None, None)
    assert units_in_make('x:\n\tsystemd-run --user --unit=superyak-imprint-use-$$id -p MemoryMax=512M -p LimitDATA=512M flock\n') == [
        Unit('superyak-imprint-use', '512M', None, '512M')]


@pytest.mark.skipif(not (REPO / 'Makefile').is_file(), reason='needs the parent repository Makefile')
def test_every_imprint_unit_is_capped_at_512m():
    units = imprint_units_from_the_makefile_and_systemd(REPO)
    assert {u.name for u in units} >= {'superyak-imprint-admit', 'superyak-imprint-use', 'superyak-imprint-sweep'}
    for unit in units:                                          # admit, use, sweep
        assert unit.memory_max == '512M' and unit.memory_swap_max == '0', unit.name
        assert unit.limit_data == '512M', unit.name     # what holds where there is no memory controller (review I4)


# ---- The Pi measurement -------------------------------------------------------------------------------------------

_LAUNCHER = ('import os, resource, signal, subprocess, sys\n'
             "lim = int(os.environ.pop('IMPRINT_DATA_LIMIT')); wall = float(os.environ.pop('IMPRINT_WALL'))\n"
             'p = subprocess.Popen(sys.argv[1:], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True,\n'
             '                     preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_DATA, (lim, lim)))\n'
             'try:\n'
             '    err, code = p.communicate(timeout=wall)[1], p.returncode\n'
             'except subprocess.TimeoutExpired:\n'
             '    os.killpg(p.pid, signal.SIGKILL); err, code = p.communicate()[1] or "", 124\n'
             'sys.stderr.write((err or "")[-1500:])\n'
             'print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024, code)\n')

CAP_BYTES = 512 * 2**20
HARD_DATA_LIMIT = CAP_BYTES          # the units' LimitDATA=512M: what holds where MemoryMax is ignored (review I4)


def memory_cap_enforced(controllers=None):
    """True when `systemd-run --user --scope -p MemoryMax=…` is applied here: the user manager must hold `memory`."""
    if controllers is None:
        uid = os.getuid()
        try:
            controllers = Path(f'/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/cgroup.controllers').read_text()
        except OSError:
            return False
    return 'memory' in controllers.split()


def capped(argv, env):
    """`argv` under the 512M scope where systemd-run exists, with the hard data limit and a wall-clock kill in the
    launcher either way; warns when the cap itself is not applied."""
    if shutil.which('systemd-run'):
        argv = ['systemd-run', '--user', '--scope', '--quiet', '-p', 'MemoryMax=512M', '-p', 'MemorySwapMax=0'] + argv
        if not memory_cap_enforced():
            warnings.warn('MemoryMax=512M is not applied here (the user manager has no memory controller); '
                          "the child's RLIMIT_DATA and wall-clock kill are the only backstop", stacklevel=3)
    return argv, {**(os.environ if env is None else env), 'IMPRINT_DATA_LIMIT': str(HARD_DATA_LIMIT), 'IMPRINT_WALL': '1800'}



def mib(n):
    return round(n / 2**20, 1)


def child_peak_rss(*, cmd, env=None, ok=(0,)):
    """Peak resident bytes of the command `cmd` in a fresh child under the 512M scope; its exit status must be in `ok`."""
    argv, env = capped([str(a) for a in cmd], env)
    out = subprocess.run([sys.executable, '-c', _LAUNCHER, *argv], cwd=PEER, env=env, capture_output=True, text=True,
                         timeout=1860)
    assert out.returncode == 0 and out.stdout.split(), out.stderr[-2000:]
    peak, status = (int(x) for x in out.stdout.split()[-2:])
    assert status in ok, (cmd[:4], status, out.stderr[-1500:])
    return peak


def high_water():
    """This process's `VmHWM` in bytes."""
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmHWM:'):
            return int(line.split()[1]) * 1024
    raise AssertionError('no VmHWM')


def part_bytes(n, size=PART_BYTES):
    return (n.to_bytes(4, 'big') * (size // 4 + 1))[:size]


def upload_part_by_part(st, *, package_bytes, ship='voyager'):
    """Request, confirm, manifest, every part, complete. One part is in memory at a time. Returns the request's row."""
    parts = -(-package_bytes // PART_BYTES)
    made = post(st, request_doc(**{'package.bytes': package_bytes, 'package.parts': parts}), ship).json()
    assert confirm(st.sam, made).status_code == 200
    sizes = [min(PART_BYTES, package_bytes - n * PART_BYTES) for n in range(parts)]
    whole, hashes = hashlib.sha256(), []
    for n, size in enumerate(sizes):
        data = part_bytes(n, size)
        whole.update(data)
        hashes.append(hashlib.sha256(data).hexdigest())
    manifest = manifest_for_doc(st, made, b'')
    manifest['package'].update(bytes=package_bytes, sha256=whole.hexdigest(), parts=hashes)
    assert put_manifest(st, made, manifest).status_code == 200
    for n, size in enumerate(sizes):
        if n and n % 100 == 0:
            st.clock[0] += 61                                   # the station allows 120 parts a minute a ship
        assert put_part(st, made, n, part_bytes(n, size)).status_code == 200
    assert st.voyager.post(f'/api/imprints/{made["id"]}/complete').json()['status'] == 'received'
    return row(st, made['id'])


def peer_command(st, name, *, request, imprint_id, root):
    data = ['--data-dir', st.store.data_dir]
    imprints = ['--imprints-dir', root]
    short = request[:6]
    args = {
        'station-approve': [*data, '--id', short, '--as', 'andy', *imprints],
        'station-deny': [*data, '--id', short, '--as', 'andy', *imprints],
        'station-imprints': [*data, '--as', 'andy', *imprints],
        'station-imprint-admit-begin': [*data, '--id', imprint_id, '--as', 'andy', *imprints],
        'station-imprint-use-begin': [*data, '--id', imprint_id[:8], '--use', 'trail-evaluation', '--as', 'andy', *imprints],
        'station-imprint-sync': [*data, '--as', 'andy', *imprints],
        'station-imprint-sweep': [*data, *imprints],
        'station-imprint-delete': [*data, '--id', imprint_id[:8], '--as', 'andy', *imprints],
        'station-imprint-unit-env': [],
        'verify-imprint': ['--permission', Path(root) / imprint_id / 'permission.json'],
    }[name]
    return [sys.executable, '-m', 'superyak_peer', name, *args]


@PI
def test_pi_the_lighthouse_and_the_station_commands(tmp_path):
    st = station(tmp_path)
    before = high_water()
    big = upload_part_by_part(st, package_bytes=2 * 2**30)                         # 512 parts, then complete
    growth = high_water() - before
    assert growth < 32 * 2**20, mib(growth)
    print('lighthouse high water grew', mib(growth), 'MiB over a 2 GiB package')
    small = upload_part_by_part(st, package_bytes=100)
    env = {**os.environ, 'HOME': str(tmp_path / 'home')}
    (tmp_path / 'home').mkdir()
    # admit-begin and use-begin must answer 0, so each runs the work of an allowed decision (a receipt, a state file),
    # not a refusal: the package is approved by station-approve, begun by admit-begin, given the result a finished
    # admission leaves (the unit's job, not a peer command's), admitted by station-imprint-sync, and then used.
    state = Path(st.root) / f'{big["imprint_id"]}.state'
    admitted_result = {'status': 'admitted', 'ended_at': int(time.time()), 'checks': 17, 'report_sha256': 'ab' * 32,
                       'skipped': [], 'roads_and_trails': 4, 'sessions_too_large': 0}
    plan = [('station-approve', big, (0,)), ('station-imprints', big, (0,)),
            ('station-imprint-admit-begin', big, (0,)), ('result', big, (0,)),
            ('station-imprint-sync', big, (0,)), ('station-imprint-use-begin', big, (0,)),
            ('station-imprint-sweep', big, (0,)),
            ('station-imprint-unit-env', big, (0,)), ('verify-imprint', big, (0,)),
            ('station-deny', small, (0,)), ('station-imprint-delete', big, (0,))]
    for name, found, ok in plan:
        if name == 'result':
            (state / 'result.json').write_text(json.dumps(admitted_result))
            continue
        cmd = peer_command(st, name, request=found['id'], imprint_id=found['imprint_id'], root=st.root)
        peak = child_peak_rss(cmd=cmd, env=env, ok=ok)
        assert peak < PEAK_BUDGET, (name, mib(peak))
        print(name, mib(peak), 'MiB')
    base = child_peak_rss(cmd=[sys.executable, '-c', 'import superyak_peer.__main__'], env=env)
    print('peer command base (imports alone)', mib(base), 'MiB')


def test_the_cap_guard_reads_the_controllers():
    assert not memory_cap_enforced('cpu pids\n')                   # this Pi: the property is accepted and ignored
    assert memory_cap_enforced('cpu memory pids\n')


def test_a_child_over_the_512_mib_cap_fails_on_its_data_limit():        # the units' LimitDATA=512M (review I4)
    with pytest.raises(AssertionError) as raised:
        child_peak_rss(cmd=[sys.executable, '-c', 'x = bytearray(640 * 2**20)'])
    assert 'MemoryError' in str(raised.value)


def test_a_runaway_child_fails_on_its_own_hard_limit():
    code = "x = bytearray(1536 * 2**20); x[::4096] = b'x' * len(x[::4096])"
    with pytest.raises(AssertionError) as raised:
        child_peak_rss(cmd=[sys.executable, '-c', code])
    assert 'MemoryError' in str(raised.value)
