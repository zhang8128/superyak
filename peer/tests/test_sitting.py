"""The merge sitting (superyak_peer.sitting): real git in a scratch station checkout, stand-ins for the units and HTTP."""
import fcntl
import os
import signal
import subprocess

import pytest

from superyak_peer.sitting import FIRST_UNIT, OTHER_UNITS, PROBES, Interrupted, Sitting, Stopped, run_command


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, name, text='x'):
    (cwd / name).write_text(text)
    git(cwd, 'add', name)
    git(cwd, 'commit', '-q', '-m', name)
    return git(cwd, 'rev-parse', 'HEAD')


@pytest.fixture
def station(tmp_path):
    """A station checkout on main with a pushed origin, and an approved train one merge ahead."""
    origin, repo = tmp_path / 'origin.git', tmp_path / 'station'
    git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(origin))
    git(tmp_path, 'init', '-q', '-b', 'main', str(repo))
    for key, value in (('user.name', 'ship'), ('user.email', 'ship@invalid'), ('commit.gpgsign', 'false')):
        git(repo, 'config', key, value)
    base = commit(repo, 'base')
    git(repo, 'remote', 'add', 'origin', str(origin))
    git(repo, 'push', '-q', 'origin', 'main')
    git(repo, 'checkout', '-q', '-b', 'member')
    commit(repo, 'member')
    git(repo, 'checkout', '-q', '-b', 'train', 'main')
    git(repo, 'merge', '-q', '--no-ff', '-m', 'Merge member into the train', 'member')
    train = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-q', 'main')
    return {'repo': repo, 'origin': origin, 'base': base, 'train': train, 'old': git(repo, 'rev-parse', 'HEAD')}


class Host:
    """Answers systemctl, curl, journalctl and uv as a station would; git runs for real."""

    def __init__(self, repo):
        self.repo, self.calls = repo, []
        self.health, self.probes, self.states, self.restart_codes = '200', dict(PROBES), {}, {}
        self.exec_start = f'{{ path={repo.resolve()}/peer/.venv/bin/python ; argv[]=... }}'
        self.stop = ('Mon 2026-11-02 11:18:15.222427 PST', 'Mon 2026-11-02 11:18:15.592136 PST')
        self.sync_code, self.fail_once, self.signals, self.on_first_curl = 0, None, [], None

    def __call__(self, argv, cwd):
        self.calls.append((tuple(argv), git(self.repo, 'rev-parse', 'HEAD')))
        if self.signals and self.signals[0][0] in (argv[0], tuple(argv[:2])):  # real signals, sent in this order
            os.kill(os.getpid(), self.signals.pop(0)[1])
        if argv[0] == 'curl' and self.on_first_curl:
            action, self.on_first_curl = self.on_first_curl, None
            action()
        if self.fail_once and self.fail_once[0] == argv[0]:  # fails the first such call only
            failure, self.fail_once = self.fail_once[1], None
            raise failure
        if argv[0] == 'curl':
            path = argv[-1].split(':7435', 1)[1]
            return 0, self.health if path == '/api/health' else self.probes[path], ''
        if argv[0] == 'systemctl' and argv[2] == 'show':
            unit = argv[4].removesuffix('.service')
            values = {'ExecStart': self.exec_start, 'ActiveExitTimestamp': self.stop[0],
                      'InactiveEnterTimestamp': self.stop[1], 'ActiveState': self.states.get(unit, 'active'),
                      'NRestarts': '0'}
            if self.states.get(unit) == 'crashing':
                values.update(ActiveState='active', NRestarts='2')
            asked = [a.removeprefix('--property=') for a in argv[5:]]
            return 0, '\n'.join(f'{name}={values[name]}' for name in asked), ''
        if argv[0] == 'systemctl' and argv[2] == 'restart':
            return self.restart_codes.get(argv[3].removesuffix('.service'), 0), '', ''
        if argv[0] == 'journalctl':
            return 0, '', ''
        if argv[0] == 'uv':
            return self.sync_code, '', 'resolution failed' if self.sync_code else ''
        return run_command(argv, cwd)

    def restarts(self):
        return [argv[3].removesuffix('.service') for argv, _ in self.calls if argv[:3] == ('systemctl', '--user', 'restart')]

    def ran(self, program):
        return [argv for argv, _ in self.calls if argv[0] == program]


def sitting(station, host, **options):
    backups, lines = [], []
    during_backup = options.pop('during_backup', None)

    def backup():
        backups.append(git(station['repo'], 'rev-parse', 'HEAD'))
        if during_backup:
            during_backup()
        return '/backups/peer-1.sqlite3'

    options.setdefault('settle', 0)
    options.setdefault('pause', lambda _seconds: None)
    made = Sitting(station['repo'], options.pop('train', station['train']), host='station.invalid', backup=backup,
                   base=station['base'], run=host, say=lines.append, **options)
    return made, backups, lines


def head(station):
    return git(station['repo'], 'rev-parse', 'HEAD')


def origin_main(station):
    return git(station['origin'], 'rev-parse', 'refs/heads/main')


def assert_put_back(station, host, lines):
    """Main and its files are the old ones, the units restarted on them, and nothing was pushed."""
    assert head(station) == station['old'] == origin_main(station)
    assert not (station['repo'] / 'member').exists() and not git(station['repo'], 'status', '--porcelain')
    assert host.restarts()[-5:] == [FIRST_UNIT, *OTHER_UNITS]
    assert {short for argv, short in host.calls if argv[:3] == ('systemctl', '--user', 'restart')}.issuperset({station['old']})
    assert not [argv for argv in host.ran('git') if argv[1] == 'push']
    assert 'SITTING: put main back' in lines[-1] and '/backups/peer-1.sqlite3' in lines[-1]


def test_a_good_sitting_backs_up_first_restarts_the_lighthouse_first_and_pushes_the_commit_once(station):
    host = Host(station['repo'])
    made, backups, lines = sitting(station, host)
    assert made.sit() == 0
    assert head(station) == station['train'] == origin_main(station)
    assert backups == [station['old']]  # backed up while main was still the old one
    assert host.restarts() == [FIRST_UNIT, *OTHER_UNITS]
    assert [argv for argv in host.ran('git') if argv[1] == 'push'] == [
        ('git', 'push', 'origin', f"{station['train']}:refs/heads/main")]
    assert host.ran('uv') == []  # the train doesn't touch peer's lock
    report = '\n'.join(lines)
    assert 'Merge member into the train' in report and 'health HTTP 200' in report and '(0.37 s)' in report
    assert 'SITTING: done' in lines[-1]


def test_a_dry_run_changes_nothing(station):
    host = Host(station['repo'])
    made, backups, lines = sitting(station, host, dry_run=True)
    assert made.sit() == 0
    assert head(station) == origin_main(station) == station['old']
    assert backups == [] and host.restarts() == []
    assert lines[-1] == 'SITTING: dry run, nothing changed'


def test_no_push_leaves_origin_and_says_the_push_is_owed(station):
    host = Host(station['repo'])
    made, _, lines = sitting(station, host, push=False)
    assert made.sit() == 0
    assert head(station) == station['train'] and origin_main(station) == station['old']
    assert not [argv for argv in host.ran('git') if argv[1] == 'push']
    assert 'NOT pushed' in lines[-1] and f"git push origin {station['train']}:refs/heads/main" in lines[-1]


@pytest.mark.parametrize('broken', ['health', 'route', 'failed unit', 'crashing unit', 'restart refused', 'slow stop',
                                    'lighthouse restart refused', 'lighthouse failed'])
def test_a_failed_check_puts_main_back_restarts_on_it_and_pushes_nothing(station, broken):
    host = Host(station['repo'])
    if broken == 'health':
        host.health = '000'
    elif broken == 'route':
        host.probes['/mcp'] = '200'
    elif broken == 'failed unit':
        host.states['superyak-odo'] = 'failed'
    elif broken == 'crashing unit':
        host.states['superyak-door'] = 'crashing'
    elif broken == 'restart refused':
        host.restart_codes['superyak-ship'] = 1
    elif broken == 'lighthouse restart refused':
        host.restart_codes[FIRST_UNIT] = 1
    elif broken == 'lighthouse failed':
        host.states[FIRST_UNIT] = 'failed'
    else:  # a slow stop is reported, not a failure
        host.stop = ('Mon 2026-11-02 11:18:15.000000 PST', 'Mon 2026-11-02 11:18:23.500000 PST')
        made, _, lines = sitting(station, host)
        assert made.sit() == 0 and any('(8.50 s, past the 5 s grace' in line for line in lines)
        return
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert_put_back(station, host, lines)
    assert {'health': 'health answered 000', 'route': '/mcp answered 200, not 404',
            'failed unit': 'superyak-odo is failed', 'crashing unit': 'superyak-door is active, with 2 restarts',
            'restart refused': 'superyak-ship did not restart', 'lighthouse restart refused': f'{FIRST_UNIT} did not restart',
            'lighthouse failed': f'{FIRST_UNIT} is failed'}[broken] in lines[-1]


@pytest.mark.parametrize('error', [RuntimeError('curl crashed'), Interrupted('SIGTERM'), KeyboardInterrupt()])
def test_a_crash_or_a_signal_after_the_fast_forward_puts_main_back(station, error):
    host = Host(station['repo'])
    host.fail_once = ('curl', error)  # the first health check, after the fast-forward
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert_put_back(station, host, lines)
    assert type(error).__name__ in lines[-1]


def test_a_refused_push_leaves_the_station_on_the_train_and_says_so(station):
    hook = station['origin'] / 'hooks' / 'pre-receive'
    hook.write_text('#!/bin/sh\necho refused by origin >&2\nexit 1\n')
    hook.chmod(0o755)
    host = Host(station['repo'])
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert head(station) == station['train'] and origin_main(station) == station['old']
    assert 'the station runs' in lines[-1] and 'Push it again by hand' in lines[-1]


@pytest.mark.parametrize('lock_input', ['peer/uv.lock', 'peer/pyproject.toml'])
def test_a_train_that_changes_peers_lock_syncs_before_the_restart_and_again_when_put_back(station, lock_input):
    repo = station['repo']
    git(repo, 'checkout', '-q', 'train')
    (repo / 'peer').mkdir()
    commit(repo, lock_input, 'new lock')
    train = head(station)
    git(repo, 'checkout', '-q', 'main')
    host = Host(repo)
    host.sync_code = 1
    made, _, lines = sitting(station, host, train=train)
    assert made.sit() == 1
    synced_on = [short for argv, short in host.calls if argv[0] == 'uv']
    assert synced_on == [train, station['old']]  # the new lock, then the old one after putting main back
    assert all('--locked' in argv for argv in host.ran('uv'))
    assert host.restarts() == []  # a failed sync restarts nothing
    assert head(station) == station['old'] and 'uv sync failed' in lines[-1]
    assert 'nothing was restarted on it' in lines[-1] and 'and restarted' not in lines[-1]
    dry, _, dry_lines = sitting(station, Host(repo), train=train, dry_run=True)
    assert dry.sit() == 0 and any('runs uv sync before the restart' in line for line in dry_lines)


def test_not_a_fast_forward_is_refused_before_the_backup(station):
    commit(station['repo'], 'only-on-main')
    git(station['repo'], 'push', '-q', 'origin', 'main')
    host = Host(station['repo'])
    made, backups, _ = sitting(station, host)
    with pytest.raises(Stopped, match='not a fast-forward'):
        made.sit()
    assert backups == [] and host.restarts() == []


@pytest.mark.parametrize('case', ['branch name', 'other tree', 'old history', 'dirty', 'origin ahead', 'untracked',
                                  'other checkout', 'second sitting'])
def test_refusals_change_nothing(station, case):
    repo, host, train, options = station['repo'], Host(station['repo']), station['train'], {}
    message = {'branch name': 'must be the approved commit id', 'other tree': 'is not the approved',
               'old history': 'from the old history', 'dirty': 'changes to tracked files', 'origin ahead': 'origin main is',
               'untracked': 'the train adds member', 'other checkout': 'does not run from',
               'second sitting': 'another merge sitting'}[case]
    held = None
    if case == 'branch name':
        train = 'train'
    elif case == 'other tree':
        options['tree'] = '0' * 40
    elif case == 'old history':
        git(repo, 'checkout', '-q', '--orphan', 'old-history')
        git(repo, 'rm', '-rqf', '.')
        commit(repo, 'old')
        git(repo, 'checkout', '-q', 'train')
        git(repo, 'merge', '-q', '--allow-unrelated-histories', '-m', 'bring in the old history', 'old-history')
        train = head(station)
        git(repo, 'checkout', '-q', 'main')
    elif case == 'dirty':
        (repo / 'base').write_text('edited')
    elif case == 'origin ahead':
        git(repo, 'checkout', '-q', '-b', 'elsewhere', 'main')
        commit(repo, 'pushed-elsewhere')
        git(repo, 'push', '-q', 'origin', 'elsewhere:main')
        git(repo, 'checkout', '-q', 'main')
    elif case == 'untracked':
        (repo / 'member').write_text('a local file the fast-forward would overwrite')
    elif case == 'other checkout':
        host.exec_start = '{ path=/elsewhere/superyak/peer/.venv/bin/python ; argv[]=... }'
    else:
        held = open(repo / '.git' / 'merge-sitting.lock', 'w')
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before = head(station)
    made, backups, _ = sitting(station, host, train=train, **options)
    try:
        with pytest.raises(Stopped, match=message):
            made.sit()
    finally:
        if held:
            held.close()
    assert backups == [] and host.restarts() == [] and head(station) == before
    if case == 'untracked':
        assert (repo / 'member').read_text() == 'a local file the fast-forward would overwrite'


def test_a_fast_forward_that_fails_changes_nothing_and_restarts_nothing(station):
    host = Host(station['repo'])
    original = host.__call__

    def merge_refused(argv, cwd):
        if argv[:2] == ('git', 'merge'):
            return 1, '', 'refused'
        return original(argv, cwd)
    made, backups, _ = sitting(station, merge_refused)
    with pytest.raises(Stopped, match='the fast-forward did not happen'):
        made.sit()
    assert head(station) == station['old'] and host.restarts() == [] and backups == [station['old']]


@pytest.mark.parametrize('first', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_real_signals_put_main_back_and_later_ones_are_held(station, first):
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    host = Host(station['repo'])
    # one during the health check, then two more while main is put back (uv run forwards a signal twice)
    host.signals = [('curl', first), (('git', 'reset'), signal.SIGTERM), (('systemctl', '--user'), signal.SIGINT)]
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert_put_back(station, host, lines)
    assert 'Interrupted' in lines[-1] and '2 more signals arrived and were held' in lines[-1]
    assert {sig: signal.getsignal(sig) for sig in before} == before  # the station's own handlers are back


def test_a_signal_during_the_push_is_reported_and_main_stays_on_the_train(station):
    host = Host(station['repo'])
    original = host.__call__

    def push_interrupted(argv, cwd):
        if argv[:2] == ('git', 'push'):
            raise Interrupted('SIGTERM')
        return original(argv, cwd)
    made, _, lines = sitting(station, push_interrupted)
    assert made.sit() == 1
    assert head(station) == station['train'] and 'interrupted (SIGTERM) during the push' in lines[-1]


def test_a_tracked_edit_during_the_sitting_is_kept_and_main_is_not_put_back_over_it(station):
    host = Host(station['repo'])
    host.health = '000'
    host.on_first_curl = lambda: (station['repo'] / 'member').write_text('an edit made mid-sitting')
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert head(station) == station['train']
    assert (station['repo'] / 'member').read_text() == 'an edit made mid-sitting'
    assert 'putting it back was refused' in lines[-1]


def test_main_moved_elsewhere_mid_sitting_is_left_as_it_is(station):
    host = Host(station['repo'])
    host.health = '000'
    host.on_first_curl = lambda: commit(station['repo'], 'someone-else')
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert 'neither' in lines[-1] and 'left as it is' in lines[-1]


def test_main_moving_during_the_backup_stops_before_the_fast_forward(station):
    host = Host(station['repo'])
    made, _, _ = sitting(station, host, during_backup=lambda: commit(station['repo'], 'during-backup'))
    with pytest.raises(Stopped, match='main moved during the backup'):
        made.sit()
    assert host.restarts() == []


def test_the_waits_are_bounded_and_the_units_settle(station):
    host, pauses = Host(station['repo']), []
    tree = git(station['repo'], 'rev-parse', f"{station['train']}^{{tree}}")
    made, _, _ = sitting(station, host, settle=7, pause=pauses.append, tree=tree[:8])
    assert made.sit() == 0  # the approved tree passes, named short as a verdict names it
    assert pauses == [7]
    health = [argv for argv in host.ran('curl') if argv[-1].endswith('/api/health')]
    probes = [argv for argv in host.ran('curl') if not argv[-1].endswith('/api/health')]
    assert health and all('--max-time' in argv and '--retry-connrefused' in argv for argv in health)
    assert len(probes) == len(PROBES) and all('--max-time' in argv for argv in probes)


def test_a_branch_named_like_a_commit_id_is_refused(station):
    name = 'abcdef1' if not station['train'].startswith('abcdef1') else 'fedcba1'
    git(station['repo'], 'branch', name, station['train'])
    made, backups, _ = sitting(station, Host(station['repo']), train=name)
    with pytest.raises(Stopped, match=f'{name} names'):
        made.sit()
    assert backups == []


@pytest.mark.parametrize('flags, expected', [([], {'dry_run': False, 'push': True}),
                                             (['--dry-run'], {'dry_run': True, 'push': True}),
                                             (['--no-push'], {'dry_run': False, 'push': False})])
def test_the_cli_passes_dry_run_and_no_push(monkeypatch, tmp_path, flags, expected):
    import superyak_peer.sitting as sitting_module
    from superyak_peer.__main__ import main
    seen = {}

    class Recorder:
        def __init__(self, repo, train, **options):
            seen.update(options, train=train)

        def sit(self):
            return 0
    monkeypatch.setattr(sitting_module, 'Sitting', Recorder)
    main(['merge-sitting', '--repo', str(tmp_path), '--train', 'abc1234', '--host', 'h', '--data-dir', str(tmp_path), *flags])
    assert {key: seen[key] for key in expected} == expected and seen['train'] == 'abc1234'


def test_the_cli_never_ends_a_sitting_without_a_sitting_line(monkeypatch, tmp_path, capsys):
    import superyak_peer.sitting as sitting_module
    from superyak_peer.__main__ import main

    class Crashing:
        def __init__(self, *_args, **_options):
            pass

        def sit(self):
            raise KeyboardInterrupt()
    monkeypatch.setattr(sitting_module, 'Sitting', Crashing)
    with pytest.raises(SystemExit) as ended:
        main(['merge-sitting', '--repo', str(tmp_path), '--train', 'abc1234', '--host', 'h', '--data-dir', str(tmp_path)])
    assert ended.value.code == 1 and 'SITTING: ended by KeyboardInterrupt' in capsys.readouterr().err


def test_the_default_settle_outlasts_a_unit_dying_at_import():
    from superyak_peer.sitting import SETTLE_SECONDS
    assert SETTLE_SECONDS >= 10  # Restart=on-failure brings a unit back within seconds; it must be seen restarting


def test_a_signal_during_a_put_back_that_a_failed_check_started_is_held(station):
    host = Host(station['repo'])
    host.health = '000'  # no signal starts this put-back
    host.signals = [(('git', 'reset'), signal.SIGTERM)]
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert_put_back(station, host, lines)
    assert '1 more signals arrived and were held' in lines[-1]


def test_a_fast_forward_cut_short_says_the_checkout_is_partly_written(station):
    host = Host(station['repo'])
    original = host.__call__

    def merge_cut_short(argv, cwd):
        if argv[:2] == ('git', 'merge'):
            (station['repo'] / 'base').write_text('half of the checkout')
            raise Interrupted('SIGTERM')
        return original(argv, cwd)
    made, _, _ = sitting(station, merge_cut_short)
    with pytest.raises(Stopped, match='partly written files'):
        made.sit()
    assert host.restarts() == []
