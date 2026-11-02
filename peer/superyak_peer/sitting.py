"""The merge sitting: one command and its report instead of a dozen hand steps.

On the station's own checkout: check that the approved train commit fast-forwards main (its tree, if the verdict
named one, no commit from the old history, nothing untracked where the train adds a file, the units running from this
checkout), back up the station, fast-forward, sync peer's environment when the train changes its lock, restart the
lighthouse and read its stop from the unit, check health and that the connector's routes stay closed, restart the
other services, let them settle and check each, push the exact commit once, and print the report for the
announcement. A failed check, a crash or a signal after the fast-forward puts main back, restarts on it and pushes
nothing. Andy, 2026-11-02: "reference a tested millenium falcon instead of each individual atom".

It takes minutes: run it in the background, or with a 10-minute timeout, from a shell or tmux, never from a run
that superyak-ship woke (restarting superyak-ship stops the watcher that holds that run).
"""
import fcntl
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

OLD_HISTORY_BASE = '60dd85175a1709627be63a4678694029c5721b74'
FIRST_UNIT = 'superyak-lighthouse'
OTHER_UNITS = ('superyak-door', 'superyak-ship', 'superyak-odo', 'superyak-wormhole')
# The connector isn't deployed (a person's act), so its routes stay closed on the public host.
PROBES = {'/mcp': '404', '/token': '404', '/api/connected-apps': '404', '/api/connected-apps/notice': '404',
          '/api/admin/connected-apps': '404'}
HEALTH_WAIT = ('--max-time', '5', '--retry', '60', '--retry-connrefused', '--retry-delay', '1', '--retry-max-time', '90')
PROBE_WAIT = ('--max-time', '10')
SETTLE_SECONDS = 15  # a unit that dies at import reads active for a moment after its restart
SLOW_STOP_SECONDS = 6  # past the lighthouse's 5 s grace (SHUTDOWN_GRACE)
LOCKED_INPUTS = ('peer/uv.lock', 'peer/pyproject.toml')  # the units run peer/.venv as it is
COMMIT_ID = re.compile(r'[0-9a-f]{7,40}')


class Stopped(Exception):
    """The sitting stopped before the fast-forward, with main unchanged."""


class Interrupted(BaseException):
    """A signal arrived while main was moved."""


class Signals:
    """While main is moved: the first SIGTERM, SIGHUP or SIGINT raises Interrupted; every later one, and any during
    the put-back, is only counted, so nothing cuts the put-back short. `uv run` forwards a signal to its child, so a
    single ^C or SIGTERM can arrive twice."""

    TRAPPED = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)

    def __init__(self):
        self.raised, self.held, self.saved = False, 0, {}

    def __enter__(self):
        try:
            for sig in self.TRAPPED:
                self.saved[sig] = signal.signal(sig, self._arrived)
        except ValueError:  # not the main thread: nothing to trap
            pass
        return self

    def _arrived(self, signum, _frame):
        if self.raised:
            self.held += 1
            return
        self.raised = True
        raise Interrupted(signal.Signals(signum).name)

    def hold(self):
        """From here on every signal is only counted (the put-back)."""
        self.raised = True

    def __exit__(self, *_exc):
        for sig, handler in self.saved.items():
            signal.signal(sig, handler)
        return False


def say_now(line):
    """Each report line reaches a log at once: a background run's log shows where it is, and a SIGKILL keeps it."""
    print(line, flush=True)


def run_command(argv, cwd):
    done = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def stop_seconds(exited, inactive):
    """Seconds between two systemd timestamps ('Mon 2026-11-02 11:18:15.222427 PST'), or None if unreadable."""
    try:
        def parse(value):
            return datetime.strptime(' '.join(value.split()[1:3]), '%Y-%m-%d %H:%M:%S.%f')
        return (parse(inactive) - parse(exited)).total_seconds()
    except (ValueError, IndexError, AttributeError):
        return None


class Sitting:
    def __init__(self, repo, train, *, host, backup, tree=None, port=7435, push=True, dry_run=False,
                 base=OLD_HISTORY_BASE, settle=SETTLE_SECONDS, run=run_command, say=say_now, pause=time.sleep):
        self.repo, self.train, self.host, self.backup, self.tree = Path(repo), train, host, backup, tree
        self.port, self.push, self.dry_run, self.base, self.settle = port, push, dry_run, base, settle
        self._run, self.say, self.pause = run, say, pause
        self.report, self.restarted = [], False

    def run(self, *argv):
        return self._run(argv, self.repo)

    def git(self, *args, check=True):
        code, out, err = self.run('git', *args)
        if check and code:
            raise Stopped(f'git {args[0]} failed: {err or out}')
        return out

    def note(self, line):
        self.report.append(line)
        self.say(line)

    def unit(self, name, *props):
        out = self.run('systemctl', '--user', 'show', '--timestamp=us', f'{name}.service',
                       *(f'--property={p}' for p in props))[1]
        return dict(line.split('=', 1) for line in out.splitlines() if '=' in line)

    def http(self, path, wait):
        return self.run('curl', '-s', *wait, '-o', '/dev/null', '-w', '%{http_code}', '-H', f'Host: {self.host}',
                        '-H', 'X-Forwarded-Proto: https', f'http://127.0.0.1:{self.port}{path}')[1]

    def preconditions(self):
        if not COMMIT_ID.fullmatch(self.train):
            raise Stopped(f'TRAIN must be the approved commit id, not a name: {self.train!r}')
        if self.git('symbolic-ref', '--short', 'HEAD', check=False) != 'main':
            raise Stopped('the checkout is not on main')
        if self.git('status', '--porcelain', '--untracked-files=no'):
            raise Stopped('the checkout has changes to tracked files')
        commit = self.git('rev-parse', '--verify', '--quiet', f'{self.train}^{{commit}}', check=False)
        if not commit:
            raise Stopped(f'no commit {self.train}')
        if not commit.startswith(self.train):  # a branch whose name looks like a commit id
            raise Stopped(f'{self.train} names {commit[:8]}, not a commit starting with it')
        old = self.git('rev-parse', 'HEAD')
        if commit == old:
            raise Stopped('main is already there')
        if self.run('git', 'merge-base', '--is-ancestor', old, commit)[0]:
            raise Stopped(f'not a fast-forward: main {old[:8]} is not in {commit[:8]}')
        tree = self.git('rev-parse', f'{commit}^{{tree}}')
        if self.tree:
            approved = self.git('rev-parse', '--verify', '--quiet', f'{self.tree}^{{tree}}', check=False)
            if not COMMIT_ID.fullmatch(self.tree) or approved != tree or not approved.startswith(self.tree):
                raise Stopped(f'tree {tree} is not the approved {self.tree}')
        reachable = set(self.git('rev-list', commit, '--not', self.base).split())
        old_history = reachable - set(self.git('rev-list', '--ancestry-path', f'{self.base}..{commit}').split())
        if old_history:
            raise Stopped(f'{len(old_history)} commits from the old history, such as {sorted(old_history)[0][:8]}')
        remote = self.git('ls-remote', 'origin', 'refs/heads/main').split()
        if not remote or remote[0] != old:
            raise Stopped(f'origin main is {remote[0][:8] if remote else "missing"}, not this main {old[:8]}')
        added = [path for path in self.git('diff', '-z', '--name-only', '--diff-filter=A', old, commit).split('\0')
                 if path and ((self.repo / path).exists() or (self.repo / path).is_symlink())]
        if added:
            raise Stopped(f'the train adds {added[0]}, which is already here untracked; move it aside')
        if f'{self.repo.resolve()}/' not in self.unit(FIRST_UNIT, 'ExecStart').get('ExecStart', ''):
            raise Stopped(f'{FIRST_UNIT} does not run from {self.repo.resolve()}')
        return old, commit, tree

    def locked_inputs_changed(self, old, commit):
        return bool(self.git('diff', '--name-only', old, commit, '--', *LOCKED_INPUTS, check=False))

    def sync(self):
        code, _, err = self.run('uv', 'sync', '--locked', '-q', '--project', 'peer')  # the units run peer/.venv
        self.note(f'peer environment synced to {self.git("rev-parse", "--short", "HEAD", check=False)}'
                  + ('' if not code else f': FAILED, {err[-200:]}'))
        return [] if not code else ['uv sync failed']

    def restart_and_check(self):
        """Restart and check every unit, the lighthouse first. Returns what failed, empty when all passed."""
        failed, self.restarted = [], True
        if self.run('systemctl', '--user', 'restart', f'{FIRST_UNIT}.service')[0]:
            failed.append(f'{FIRST_UNIT} did not restart')
        stop = self.unit(FIRST_UNIT, 'ActiveExitTimestamp', 'InactiveEnterTimestamp')
        seconds = stop_seconds(stop.get('ActiveExitTimestamp'), stop.get('InactiveEnterTimestamp'))
        took = 'unreadable' if seconds is None else f'{seconds:.2f} s'
        slow = seconds is not None and seconds > SLOW_STOP_SECONDS
        self.note(f'{FIRST_UNIT} stop, read from the unit: {stop.get("ActiveExitTimestamp", "?")} to '
                  f'{stop.get("InactiveEnterTimestamp", "?")} ({took}{", past the 5 s grace: read why" if slow else ""})')
        health = self.http('/api/health', HEALTH_WAIT)
        self.note(f'health HTTP {health}')
        if health != '200':
            failed.append(f'health answered {health}')
        probes = {path: self.http(path, PROBE_WAIT) for path in PROBES}
        self.note('closed routes: ' + ', '.join(f'{path} {code}' for path, code in probes.items()))
        failed += [f'{path} answered {code}, not {PROBES[path]}' for path, code in probes.items() if code != PROBES[path]]
        for name in OTHER_UNITS:
            if self.run('systemctl', '--user', 'restart', f'{name}.service')[0]:
                failed.append(f'{name} did not restart')
        self.pause(self.settle)
        states = {name: self.unit(name, 'ActiveState', 'NRestarts') for name in (FIRST_UNIT, *OTHER_UNITS)}
        self.note(f'units after {self.settle} s: ' + ', '.join(
            f'{name.removeprefix("superyak-")} {state.get("ActiveState", "?")} ({state.get("NRestarts", "?")} restarts)'
            for name, state in states.items()))
        failed += [f'{name} is {state.get("ActiveState", "unreadable")}, with {state.get("NRestarts", "?")} restarts'
                   for name, state in states.items()
                   if state.get('ActiveState') != 'active' or state.get('NRestarts') != '0']
        warnings = self.run('journalctl', '--user', '-u', f'{FIRST_UNIT}.service', '--since', '-2min', '-p', 'warning',
                            '--no-pager', '-q')[1]
        if warnings:
            self.note('lighthouse warnings in the last 2 minutes (read them):\n' + '\n'.join(warnings.splitlines()[-3:]))
        return failed

    def put_back(self, old, commit, failed, backup, resync, signals):
        signals.hold()
        here = self.git('rev-parse', 'HEAD', check=False)
        if here == commit:
            code, _, err = self.run('git', 'reset', '-q', '--keep', old)
            if code:
                self.note(f'SITTING: main is still at {commit[:8]}: putting it back was refused ({err[-200:]}). Read git '
                          f'status and the units now. Failed: {"; ".join(failed)}')
                return
        elif here != old:
            self.note(f'SITTING: main is at {here[:8]}, neither {old[:8]} nor the train; left as it is. Read git status '
                      f'and the units now. Failed: {"; ".join(failed)}')
            return
        def held():
            return f' {signals.held} more signals arrived and were held.' if signals.held else ''
        if resync and self.sync():
            self.note(f'SITTING: put main back to {old[:8]}, but its uv sync failed, so nothing was restarted on it: the '
                      f'units may still run {commit[:8]}. Read them now. Nothing pushed. Failed: {"; ".join(failed)}. '
                      f'The backup taken first: {backup}.{held()}')
            return
        again = self.restart_and_check()
        self.note(f'SITTING: put main back to {old[:8]} and restarted ({"checks pass" if not again else "; ".join(again)}); '
                  f'nothing pushed. Failed: {"; ".join(failed)}. The backup taken first: {backup}.{held()}')

    def sit(self):
        lock_path = self.repo / self.git('rev-parse', '--git-path', 'merge-sitting.lock')
        with open(lock_path, 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Stopped('another merge sitting is running on this checkout') from None
            return self._sit()

    def _sit(self):
        old, commit, tree = self.preconditions()
        members = self.git('log', '--first-parent', '--format=%h %s', f'{old}..{commit}').splitlines()
        self.note(f'main {old[:8]} -> {commit[:8]}, tree {tree}; no commit from the old history')
        for line in members:
            self.note(f'  {line[:110]}')
        if self.locked_inputs_changed(old, commit):
            self.note('  the train changes peer\'s lock inputs: the sitting runs uv sync before the restart')
        if self.dry_run:
            self.note('SITTING: dry run, nothing changed')
            return 0
        backup = self.backup()
        self.note(f'backup: {backup}')
        if self.git('rev-parse', 'HEAD') != old:
            raise Stopped('main moved during the backup')
        with Signals() as signals:
            return self._move(old, commit, members, backup, signals)

    def _move(self, old, commit, members, backup, signals):
        resync = self.locked_inputs_changed(old, commit)
        try:
            self.git('merge', '--ff-only', '-q', commit)
            failed = (self.sync() if resync else []) or self.restart_and_check()
        except BaseException as error:  # a crash or a signal with main moved: put it back, then report it
            signals.hold()
            if not self.restarted and self.git('rev-parse', 'HEAD', check=False) == old:
                lock = self.repo / self.git('rev-parse', '--git-path', 'index.lock', check=False)
                left = f'; git left {lock}: remove it once no git runs here' if lock.exists() else ''
                if self.git('status', '--porcelain', '--untracked-files=no', check=False):
                    left += '; the checkout has partly written files: read git status before anything else'
                raise Stopped(f'the fast-forward did not happen: {type(error).__name__} {error}{left}') from error
            failed = [f'{type(error).__name__} {error}'.strip()]
        if failed:
            self.put_back(old, commit, failed, backup, resync, signals)
            return 1
        if not self.push:
            self.note(f'SITTING: done, and main is NOT pushed (NO_PUSH). Once the fix is live and checked, push it: '
                      f'git push origin {commit}:refs/heads/main')
            return 0
        try:
            code, _, err = self.run('git', 'push', 'origin', f'{commit}:refs/heads/main')
            remote = self.run('git', 'ls-remote', 'origin', 'refs/heads/main')[1].split()
        except Interrupted as signal_name:
            self.note(f'SITTING: interrupted ({signal_name}) during the push; the station runs {commit[:8]}. Read '
                      'origin main before anything else.')
            return 1
        if code or not remote or remote[0] != commit:
            self.note(f'SITTING: the station runs {commit[:8]}, but origin main is '
                      f'{remote[0][:8] if remote else "unreadable"}: {err[-300:] or "the push did not land"}. Push it '
                      f'again by hand: git push origin {commit}:refs/heads/main')
            return 1
        self.note(f'pushed: origin main {commit[:8]}')
        self.note(f'SITTING: done. Merged {commit[:8]} to main ({len(members)} merges); the report above is the '
                  'announcement. Not checked here: the off-tailnet probe through Funnel.')
        return 0
