"""The station's Makefile targets for imprints (I 10, 12; R15, R20, R23, R29, D29, D42, XN2). Every run is `make` with
systemd-run, systemctl and uv shimmed on PATH and HOME in tmp_path; no real unit starts and no station is touched."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

PEER = Path(__file__).resolve().parents[1]
REPO = PEER.parent
pytestmark = pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make'), reason='needs the parent repository Makefile')

ID1, ID2 = 'c0a8f5e2-0000-4000-8000-000000000001', 'c0a8f5e2-0000-4000-8000-000000000002'
FULL_ID = ID1
# make exits 2 for any failing recipe and reports the recipe's own status as 'Error N' on stderr (CLAUDE.md, make dock).
MARKERS = ('station-imprint-admit-begin', 'imprint.py admit', 'station-imprint-sync')

SHIM = '''#!{python}
import json, os, subprocess, sys
name, argv = os.path.basename(sys.argv[0]), sys.argv[1:]
env = json.loads(os.environ.get('SHIM', '{{}}'))
joined = ' '.join(argv)
def log():
    with open(env['log'], 'a') as out:
        out.write(json.dumps([name] + argv) + '\\n')
loaded = env.get('loaded', [])
if name == 'systemd-run':
    log()
    unit = next(a for a in argv if a.startswith('--unit='))[7:]
    sys.exit(1 if unit in loaded else 0)
if name == 'systemctl':
    log()
    print('loaded' if argv[-1] in loaded else 'not-found')
    sys.exit(0)
if 'station-imprint-unit-env' in argv:        # the one real peer command: it is the rule under test
    real = {{**os.environ, 'PYTHONPATH': env['peer']}}
    sys.exit(subprocess.run([sys.executable, '-m', 'superyak_peer', 'station-imprint-unit-env'], env=real).returncode)
if '--resolve' in argv:
    print(env['full_id'])
    sys.exit(0)
log()
if 'station-approve' in argv:
    print('Approved c0a8. Admitting in the background; see make station-imprints.')
    if env.get('admit_line'):
        print('ADMIT: ' + env['admit_line'])
elif '--awaiting-admission' in argv:
    print('\\n'.join(env.get('awaiting', [])))
elif 'station-imprint-admit-begin' in argv:
    sys.exit(env.get('begin_exit', 0))
elif 'station-imprint-use-begin' in argv:
    print('0b5d0c1e-1111-4222-8333-444444444444')
'''


class Calls(list):
    stdout = ''
    stderr = ''
    returncode = 0


def IMPRINTS_OF(base):
    return Path(base) / 'home' / '.engram' / 'imprints'


def fake_home(base, runtime):
    home = Path(base) / 'home'
    (home / '.config' / 'superyak').mkdir(parents=True, exist_ok=True)
    IMPRINTS_OF(base).mkdir(parents=True, exist_ok=True)
    if runtime is not None:
        (home / '.config' / 'superyak' / 'runtime.json').write_text(json.dumps(runtime))
    return home


def other_runtime(base):
    path = Path(base) / 'other-runtime.json'
    path.write_text(json.dumps({'embedder_socket': '/run/other/embed.sock'}))
    return path


@contextlib.contextmanager
def held_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def run_make(base, args, shim, home=None, env=None, make_vars=None):
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    bin_dir = base / 'bin'
    bin_dir.mkdir(exist_ok=True)
    for name in ('uv', 'systemd-run', 'systemctl'):
        (bin_dir / name).write_text(SHIM.format(python=sys.executable))
        (bin_dir / name).chmod(0o755)
    log = base / 'calls.jsonl'
    log.write_text('')
    home = home or fake_home(base, {})
    state = {'log': str(log), 'peer': str(PEER), 'full_id': FULL_ID, **shim}
    full_env = {**os.environ, 'HOME': str(home), 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'SHIM': json.dumps(state), **(env or {})}
    cmd = ['make', '-s', '-C', str(REPO), *args, *[f'{k}={v}' for k, v in (make_vars or {}).items()]]
    done = subprocess.run(cmd, env=full_env, capture_output=True, text=True, timeout=120)
    calls = Calls(json.loads(line) for line in log.read_text().splitlines())
    calls.stdout, calls.stderr, calls.returncode = done.stdout, done.stderr, done.returncode
    return done, calls


def make_use(base, home, loaded=False, imprints_root_missing=False, lane=None, env=None, make_vars=None):
    if imprints_root_missing:
        shutil.rmtree(IMPRINTS_OF(base))
    args = ['station-imprint-use', f'ID={FULL_ID[:4]}', 'USE=trail-evaluation'] + ([f'LANE={lane}'] if lane else [])
    shim = {'loaded': [f'superyak-imprint-use-{FULL_ID}'] if loaded else []}
    return run_make(base, args, shim, home, env, make_vars)


def make_approve(base, admit_line, awaiting, loaded=(), lock_held=False):
    fake_home(base, {})
    shim = {'admit_line': admit_line, 'awaiting': awaiting, 'loaded': list(loaded)}
    with held_lock(IMPRINTS_OF(base) / '.jobs.lock') if lock_held else contextlib.nullcontext():
        _, calls = run_make(base, ['station-approve', 'ID=c0a8'], shim)
    return calls


def make_admit_all(base, awaiting, loaded):
    fake_home(base, {})
    return run_make(base, ['station-imprint-admit'], {'awaiting': awaiting, 'loaded': list(loaded)})[1]


def make_admit(base, imprint_id, begin_exit=0):
    fake_home(base, {})
    return run_make(base, ['station-imprint-admit', f'ID={imprint_id}'], {'begin_exit': begin_exit})[1]


def dry_run(base, *args):
    fake_home(base, {})
    done = subprocess.run(['make', '-n', '-C', str(REPO), *args], env={**os.environ, 'HOME': str(Path(base) / 'home')},
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return [seg.replace('"', '') for seg in done.stdout.replace('\n', ' ').split(';') if any(m in seg for m in MARKERS)]


def step_of(call):
    text = call if isinstance(call, str) else ' '.join(call)
    return next(m for m in MARKERS if m in text)


class Unit:
    def __init__(self, argv):
        self.argv = argv
        self.name = next(a for a in argv if a.startswith('--unit='))[7:]
        start = argv.index('TimeoutStopSec=60') + 1
        self.env_options = argv[start:argv.index('flock')]


def started_unit(base, home, env=None, make_vars=None):
    done, calls = make_use(base, home, env=env, make_vars=make_vars)
    assert done.returncode == 0, done.stderr + done.stdout
    return Unit([c for c in calls if c[0] == 'systemd-run'][0])


def first_attempt(calls):
    return [c for c in calls if c[0] == 'systemd-run'][0]


@pytest.mark.parametrize('runtime,expected', [
    ({'embedder_socket': '/run/user/1000/embed.sock'}, ['--setenv=ENGRAM_EMBEDDER_SOCKET=/run/user/1000/embed.sock']),
    ({}, ['-p', 'UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET']), ({'embedder_socket': None}, ['-p', 'UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET']),
    (None, ['-p', 'UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET'])])
def test_the_use_unit_gets_the_socket_exactly_when_runtime_json_names_one(tmp_path, runtime, expected):
    home = fake_home(tmp_path, runtime)
    unit = started_unit(tmp_path, home, env={'SUPERYAK_RUNTIME_CONFIG': str(other_runtime(tmp_path))}, make_vars={'RUNTIME_CONFIG': '/elsewhere'})
    assert unit.env_options == expected
    assert not ('--setenv=ENGRAM_EMBEDDER_SOCKET' in ' '.join(unit.argv) and 'UnsetEnvironment=ENGRAM_EMBEDDER_SOCKET' in unit.argv)
    assert {'-p', 'TimeoutStopSec=60', 'MemoryMax=512M', 'MemorySwapMax=0', 'RuntimeMaxSec=1800'} <= set(unit.argv)
    assert unit.argv[unit.argv.index('flock'):unit.argv.index('flock') + 3] == ['flock', '-n', f'{IMPRINTS_OF(tmp_path)}/.jobs.lock']
    assert unit.name == f'superyak-imprint-use-{FULL_ID}' and not [a for a in unit.argv if a.startswith('LANE=')]


def test_a_socket_path_with_a_space_stays_one_argument(tmp_path):
    home = fake_home(tmp_path, {'embedder_socket': '/run/my dir/embed.sock'})
    unit = started_unit(tmp_path, home)
    assert unit.env_options == ['--setenv=ENGRAM_EMBEDDER_SOCKET=/run/my dir/embed.sock']


def test_a_lane_reaches_the_inner_command(tmp_path):
    done, calls = make_use(tmp_path, fake_home(tmp_path, {}), lane='work')
    assert done.returncode == 0 and 'Started a use of c0a8 in the background; see make station-imprints.' in done.stdout
    argv = first_attempt(calls)
    assert argv[argv.index('flock'):][-4:] == ['station-imprint-use-run', f'ID={FULL_ID}', 'USE=trail-evaluation', 'LANE=work']


@pytest.mark.parametrize('bad', [{'embedder_socket': 'relative/sock'}, {'embedder_socket': 3}])
def test_a_bad_socket_stops_the_use_before_the_unit(tmp_path, bad):
    done, calls = make_use(tmp_path, fake_home(tmp_path, bad))
    assert done.returncode != 0 and calls == [] and 'absolute path' in done.stderr


def test_a_second_use_of_one_imprint_starts_nothing(tmp_path):
    done, calls = make_use(tmp_path, fake_home(tmp_path, {}), loaded=True)
    assert done.returncode != 0 and 'Error 3' in done.stderr and 'A use of c0a8 is already running; see make station-imprints.' in done.stdout
    assert [c for c in calls if c[0] == 'systemd-run'] == [first_attempt(calls)]


def test_approve_starts_only_the_approved_imprints_unit(tmp_path):
    calls = make_approve(tmp_path, admit_line=ID2, awaiting=[ID1, ID2], loaded=[f'superyak-imprint-admit-{ID1}'])
    units = [c for c in calls if c[0] == 'systemd-run']
    assert [u[u.index('--user') + 1] for u in units] == [f'--unit=superyak-imprint-admit-{ID2}']
    assert {'TimeoutStopSec=60', 'MemoryMax=512M', 'MemorySwapMax=0', 'RuntimeMaxSec=3600'} <= set(units[0])   # I 10, "Time"
    dock = make_approve(tmp_path / 'dock', admit_line=None, awaiting=[ID1])                   # a docking's approval
    assert not [c for c in dock if c[0] == 'systemd-run' or 'imprint.py' in ' '.join(c) or '--awaiting-admission' in c]
    assert 'ADMIT:' not in calls.stdout and 'Approved c0a8.' in calls.stdout


def test_a_failed_start_after_approval_says_so_and_exits_1(tmp_path):
    calls = make_approve(tmp_path, admit_line=ID2, awaiting=[ID2], loaded=[f'superyak-imprint-admit-{ID2}'])
    assert calls.returncode != 0 and 'Error 1' in calls.stderr and 'Approved c0a8, but its admission did not start. Run make station-imprint-admit.' in calls.stdout


def test_the_no_id_resume_skips_a_loaded_unit(tmp_path):
    calls = make_admit_all(tmp_path, awaiting=[ID1, ID2], loaded=[f'superyak-imprint-admit-{ID1}'])
    assert [u[u.index('--user') + 1] for u in calls if u[0] == 'systemd-run'] == [f'--unit=superyak-imprint-admit-{ID2}']


def test_one_imprint_job_at_a_time(tmp_path):
    with held_lock(IMPRINTS_OF(tmp_path) / '.jobs.lock'):               # another job is running (R29)
        done, calls = make_use(tmp_path, fake_home(tmp_path, {}))
        assert done.returncode != 0 and 'Error 3' in done.stderr and 'Another imprint job is running on the station' in done.stdout
        assert not [c for c in calls if c[0] == 'systemd-run']
        approve = make_approve(tmp_path / 'a', admit_line=ID2, awaiting=[ID2], lock_held=True)
        assert not [c for c in approve if c[0] == 'systemd-run'] and 'its admission waits' in approve.stdout
        assert approve.returncode != 0 and 'Error 1' in approve.stderr and 'Approved c0a8, but another imprint job is running, so its admission waits. Run make station-imprint-admit when that job ends.' in approve.stdout
    calls = make_admit_all(tmp_path / 'b', awaiting=[ID1, ID2], loaded=[])
    assert len([u for u in calls if u[0] == 'systemd-run']) == 1 and '1 more waits' in calls.stdout
    missing, calls = make_use(tmp_path / 'c', fake_home(tmp_path / 'c', {}), imprints_root_missing=True)   # flock exits 66
    assert missing.returncode != 0 and "can't be taken: 66" in missing.stdout and 'Another imprint job' not in missing.stdout
    assert not [c for c in calls if c[0] == 'systemd-run']                       # R29; the check's nit 2


def test_admit_runs_only_when_begin_allows(tmp_path):
    calls = make_admit(tmp_path, FULL_ID, begin_exit=3)                     # refused, or begun already (R24)
    assert [step_of(c) for c in calls] == ['station-imprint-admit-begin', 'station-imprint-sync']


def test_station_imprint_admit_runs_begin_admit_and_sync_in_order(tmp_path):
    lines = dry_run(tmp_path, 'station-imprint-admit', f'ID={FULL_ID}')
    assert [step_of(l) for l in lines] == ['station-imprint-admit-begin', 'imprint.py admit', 'station-imprint-sync']
    assert all(f'--imprints-dir {IMPRINTS_OF(tmp_path)}' in l for l in lines if 'imprints' in l)
    assert '--verify-cmd uv run --locked --project ' + str(REPO / 'peer') + ' python -m superyak_peer verify-imprint' in lines[1]
