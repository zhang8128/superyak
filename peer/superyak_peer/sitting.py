"""The merge sitting (docs/assemblies.md): one command and its report instead of a dozen hand steps.

On the station's own checkout: check that the approved train fast-forwards main (its tree, if the verdict named one,
and no commit from the old history), back up the station, fast-forward, restart the lighthouse and read its stop from
the unit, check health and the closed routes, restart the other services and check each, push main once, and print
the announcement. A failed check after the fast-forward puts main back where it was, restarts the services on it and
pushes nothing. Andy, 2026-11-02: "reference a tested millenium falcon instead of each individual atom".
"""
import subprocess
from pathlib import Path

OLD_HISTORY_BASE = '60dd85175a1709627be63a4678694029c5721b74'
FIRST_UNIT = 'superyak-lighthouse'
OTHER_UNITS = ('superyak-door', 'superyak-ship', 'superyak-odo', 'superyak-wormhole')
# The connector isn't deployed (a person's act), so its routes stay closed on the public host.
PROBES = {'/mcp': '404', '/token': '404', '/api/connected-apps': '404', '/api/connected-apps/notice': '404',
          '/api/admin/connected-apps': '404'}
HEALTH_WAIT = ('--retry', '60', '--retry-connrefused', '--retry-delay', '1', '--retry-max-time', '90')


class Stopped(Exception):
    """The sitting stopped before changing anything, or after putting main back."""


def run_command(argv, cwd):
    done = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr).strip()


class Sitting:
    def __init__(self, repo, train, *, host, backup, tree=None, port=7435, push=True, dry_run=False,
                 base=OLD_HISTORY_BASE, run=run_command, say=print):
        self.repo, self.train, self.host, self.backup, self.tree = Path(repo), train, host, backup, tree
        self.port, self.push, self.dry_run, self.base, self._run, self.say = port, push, dry_run, base, run, say
        self.report = []

    def run(self, *argv):
        return self._run(argv, self.repo)

    def git(self, *args, check=True):
        code, out = self.run('git', *args)
        if check and code:
            raise Stopped(f'git {" ".join(args)} failed: {out}')
        return out

    def note(self, line):
        self.report.append(line)
        self.say(line)

    def preconditions(self):
        if self.git('symbolic-ref', '--short', 'HEAD', check=False) != 'main':
            raise Stopped('the checkout is not on main')
        if self.git('status', '--porcelain', '--untracked-files=no'):
            raise Stopped('the checkout has changes to tracked files')
        commit = self.git('rev-parse', '--verify', '--quiet', f'{self.train}^{{commit}}', check=False)
        if not commit:
            raise Stopped(f'no commit named {self.train}')
        old = self.git('rev-parse', 'HEAD')
        if commit == old:
            raise Stopped('main is already there')
        if self.run('git', 'merge-base', '--is-ancestor', old, commit)[0]:
            raise Stopped(f'not a fast-forward: main {old[:8]} is not in {commit[:8]}')
        tree = self.git('rev-parse', f'{commit}^{{tree}}')
        if self.tree and self.tree != tree:
            raise Stopped(f'tree {tree} is not the approved {self.tree}')
        reachable = set(self.git('rev-list', commit, '--not', self.base).split())
        descendants = set(self.git('rev-list', '--ancestry-path', f'{self.base}..{commit}').split())
        if reachable - descendants:
            raise Stopped(f'{len(reachable - descendants)} commits from the old history, such as '
                          f'{sorted(reachable - descendants)[0][:8]}')
        remote = self.git('ls-remote', 'origin', 'refs/heads/main').split()
        if not remote or remote[0] != old:
            raise Stopped(f'origin main is {remote[0][:8] if remote else "missing"}, not this main {old[:8]}')
        return old, commit, tree

    def unit(self, name, *props):
        out = self.run('systemctl', '--user', 'show', '--timestamp=us', f'{name}.service',
                       *(f'--property={p}' for p in props))[1]
        return dict(line.split('=', 1) for line in out.splitlines() if '=' in line)

    def http(self, path, *wait):
        return self.run('curl', '-s', *wait, '-o', '/dev/null', '-w', '%{http_code}', '-H', f'Host: {self.host}',
                        '-H', 'X-Forwarded-Proto: https', f'http://127.0.0.1:{self.port}{path}')[1]

    def restart_and_check(self):
        """Restart and check every unit, the lighthouse first. Returns what failed, empty when all passed."""
        failed = []
        if self.run('systemctl', '--user', 'restart', f'{FIRST_UNIT}.service')[0]:
            failed.append(f'{FIRST_UNIT} did not restart')
        stop = self.unit(FIRST_UNIT, 'ActiveExitTimestamp', 'InactiveEnterTimestamp')
        self.note(f'{FIRST_UNIT} stopped {stop.get("ActiveExitTimestamp", "?")}, '
                  f'inactive {stop.get("InactiveEnterTimestamp", "?")} (read from the unit)')
        health = self.http('/api/health', *HEALTH_WAIT)
        self.note(f'health HTTP {health}')
        if health != '200':
            failed.append(f'health answered {health}')
        probes = {path: self.http(path) for path in PROBES}
        self.note('closed routes: ' + ', '.join(f'{path} {code}' for path, code in probes.items()))
        failed += [f'{path} answered {code}, not {PROBES[path]}' for path, code in probes.items() if code != PROBES[path]]
        for name in OTHER_UNITS:
            if self.run('systemctl', '--user', 'restart', f'{name}.service')[0]:
                failed.append(f'{name} did not restart')
        states = {name: self.run('systemctl', '--user', 'is-active', f'{name}.service')[1]
                  for name in (FIRST_UNIT, *OTHER_UNITS)}
        self.note('units: ' + ', '.join(f'{name.removeprefix("superyak-")} {state}' for name, state in states.items()))
        failed += [f'{name} is {state}' for name, state in states.items() if state != 'active']
        warnings = self.run('journalctl', '--user', '-u', f'{FIRST_UNIT}.service', '--since', '-2min', '-p', 'warning',
                            '--no-pager', '-q')[1]
        if warnings:
            self.note('lighthouse warnings in the last 2 minutes (read them):\n' + '\n'.join(warnings.splitlines()[-3:]))
        return failed

    def sit(self):
        old, commit, tree = self.preconditions()
        members = self.git('log', '--first-parent', '--format=%h %s', f'{old}..{commit}').splitlines()
        self.note(f'main {old[:8]} -> {commit[:8]}, tree {tree}; no commit from the old history')
        for line in members:
            self.note(f'  {line[:110]}')
        if self.dry_run:
            self.note('SITTING: dry run, nothing changed')
            return 0
        self.note(f'backup: {self.backup()}')
        self.git('merge', '--ff-only', '-q', commit)
        try:
            return self.after_fast_forward(old, commit, members)
        except Stopped as stopped:  # main moved: say where it is, never "unchanged"
            here = self.run('git', 'rev-parse', '--short', 'HEAD')[1]
            self.note(f'SITTING: stopped after the fast-forward, with main at {here}: {stopped}. Read git status and '
                      'the units before anything else.')
            return 1

    def after_fast_forward(self, old, commit, members):
        failed = self.restart_and_check()
        if failed:
            self.git('reset', '-q', '--hard', old)
            again = self.restart_and_check()
            self.note(f'SITTING: reverted to {old[:8]} and restarted ({"checks pass" if not again else "; ".join(again)}); '
                      f'main not pushed. Failed: {"; ".join(failed)}')
            return 1
        if self.push:
            code, out = self.run('git', 'push', 'origin', 'main')
            pushed = self.git('ls-remote', 'origin', 'refs/heads/main').split()
            if code or not pushed or pushed[0] != commit:
                self.note(f'SITTING: the station runs {commit[:8]}, but the push failed: {out[-300:]}')
                return 1
            self.note(f'pushed: origin main {commit[:8]}')
        self.note(f'SITTING: done. Announce: merged {commit[:8]} to main ({len(members)} merges); the lighthouse stop, '
                  'health, closed routes and units above; not checked here: the off-tailnet probe through Funnel.')
        return 0
