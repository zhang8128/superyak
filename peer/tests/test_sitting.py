"""The merge sitting (superyak_peer.sitting): real git in a scratch station checkout, stand-ins for the units and HTTP."""
import subprocess

import pytest

from superyak_peer.sitting import FIRST_UNIT, OTHER_UNITS, PROBES, Sitting, Stopped, run_command


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
    return {'repo': repo, 'origin': origin, 'base': base, 'train': train}


class Host:
    """Answers systemctl, curl and journalctl as a station would; git runs for real."""

    def __init__(self, repo):
        self.repo, self.calls, self.health, self.probes, self.states = repo, [], '200', dict(PROBES), {}

    def __call__(self, argv, cwd):
        self.calls.append((tuple(argv), git(self.repo, 'rev-parse', '--short', 'HEAD')))
        if argv[0] == 'curl':
            path = argv[-1].split(':7435', 1)[1]
            return 0, self.health if path == '/api/health' else self.probes[path]
        if argv[0] == 'systemctl' and argv[2] == 'show':
            return 0, 'ActiveExitTimestamp=Mon 2026-11-02 11:18:15.222427 PST\nInactiveEnterTimestamp=Mon 2026-11-02 11:18:15.592136 PST'
        if argv[0] == 'systemctl' and argv[2] == 'is-active':
            return 0, self.states.get(argv[3].removesuffix('.service'), 'active')
        if argv[0] in ('systemctl', 'journalctl'):
            return 0, ''
        return run_command(argv, cwd)

    def restarts(self):
        return [argv[3].removesuffix('.service') for argv, _ in self.calls if argv[:3] == ('systemctl', '--user', 'restart')]


def sitting(station, host, **options):
    backups = []
    lines = []

    def backup():
        backups.append(git(station['repo'], 'rev-parse', 'HEAD'))
        return '/backups/peer-1.sqlite3'

    made = Sitting(station['repo'], options.pop('train', station['train']), host='station.invalid', backup=backup,
                   base=station['base'], run=host, say=lines.append, **options)
    return made, backups, lines


def origin_main(station):
    return git(station['origin'], 'rev-parse', 'refs/heads/main')


def test_a_good_sitting_backs_up_first_restarts_the_lighthouse_first_and_pushes_once(station):
    host = Host(station['repo'])
    made, backups, lines = sitting(station, host)
    old = git(station['repo'], 'rev-parse', 'HEAD')
    assert made.sit() == 0
    assert git(station['repo'], 'rev-parse', 'HEAD') == station['train'] == origin_main(station)
    assert backups == [old]  # backed up while main was still the old one
    assert host.restarts() == [FIRST_UNIT, *OTHER_UNITS]
    assert [argv for argv, _ in host.calls if argv[:2] == ('git', 'push')] == [('git', 'push', 'origin', 'main')]
    report = '\n'.join(lines)
    assert 'Merge member into the train' in report and 'health HTTP 200' in report
    assert 'stopped Mon 2026-11-02 11:18:15.222427 PST' in report and 'SITTING: done' in report


def test_a_dry_run_changes_nothing(station):
    host = Host(station['repo'])
    made, backups, lines = sitting(station, host, dry_run=True)
    assert made.sit() == 0
    assert git(station['repo'], 'rev-parse', 'HEAD') == origin_main(station) != station['train']
    assert backups == [] and host.restarts() == []
    assert lines[-1] == 'SITTING: dry run, nothing changed'


def test_a_failed_health_check_puts_main_back_restarts_on_it_and_pushes_nothing(station):
    host = Host(station['repo'])
    host.health = '000'
    old = git(station['repo'], 'rev-parse', 'HEAD')
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert git(station['repo'], 'rev-parse', 'HEAD') == old == origin_main(station)
    restarted_on = [short for argv, short in host.calls if argv[:3] == ('systemctl', '--user', 'restart')]
    assert len(restarted_on) == 10 and set(restarted_on[5:]) == {old[:len(restarted_on[5])]}
    assert not [argv for argv, _ in host.calls if argv[:2] == ('git', 'push')]
    assert 'SITTING: reverted' in lines[-1] and 'health answered 000' in lines[-1]


@pytest.mark.parametrize('broken', ['route', 'unit'])
def test_an_open_route_or_a_failed_unit_also_reverts(station, broken):
    host = Host(station['repo'])
    if broken == 'route':
        host.probes['/mcp'] = '200'
    else:
        host.states['superyak-odo'] = 'failed'
    made, _, lines = sitting(station, host)
    assert made.sit() == 1
    assert origin_main(station) != station['train'] and git(station['repo'], 'rev-parse', 'HEAD') != station['train']
    assert ('/mcp answered 200, not 404' if broken == 'route' else 'superyak-odo is failed') in lines[-1]


def test_not_a_fast_forward_is_refused_before_the_backup(station):
    commit(station['repo'], 'only-on-main')
    git(station['repo'], 'push', '-q', 'origin', 'main')
    host = Host(station['repo'])
    made, backups, _ = sitting(station, host)
    with pytest.raises(Stopped, match='not a fast-forward'):
        made.sit()
    assert backups == [] and host.calls == [c for c in host.calls if c[0][0] == 'git']


def test_another_tree_than_the_approved_one_is_refused(station):
    made, backups, _ = sitting(station, Host(station['repo']), tree='0' * 40)
    with pytest.raises(Stopped, match='is not the approved'):
        made.sit()
    assert backups == []


def test_a_commit_from_the_old_history_is_refused(station):
    repo = station['repo']
    git(repo, 'checkout', '-q', '--orphan', 'old-history')
    git(repo, 'rm', '-rqf', '.')
    commit(repo, 'old')
    git(repo, 'checkout', '-q', 'train')
    git(repo, 'merge', '-q', '--allow-unrelated-histories', '-m', 'bring in the old history', 'old-history')
    tainted = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-q', 'main')
    made, backups, _ = sitting(station, Host(repo), train=tainted)
    with pytest.raises(Stopped, match='from the old history'):
        made.sit()
    assert backups == []


def test_a_dirty_checkout_or_an_origin_ahead_is_refused(station):
    repo = station['repo']
    (repo / 'base').write_text('edited')
    with pytest.raises(Stopped, match='changes to tracked files'):
        sitting(station, Host(repo))[0].sit()
    git(repo, 'checkout', '-q', '--', 'base')
    git(repo, 'checkout', '-q', '-b', 'elsewhere', 'main')
    commit(repo, 'pushed-elsewhere')
    git(repo, 'push', '-q', 'origin', 'elsewhere:main')
    git(repo, 'checkout', '-q', 'main')
    with pytest.raises(Stopped, match='origin main is'):
        sitting(station, Host(repo))[0].sit()
