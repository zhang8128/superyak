#!/usr/bin/env python3
"""`make mutants`: run a reader's mutants against a reviewed head and print which the tests kill (roadmap-commons step
2, an assembly in place of mutant tables built by hand for each review).

Every mutant runs in a scratch `git worktree add --detach` at the head, never in the reader's tree, and the worktree is
removed at the end, so a kill or a timeout mid-run leaves at most a stray worktree, which the next run names (Rio
Grande's point: a copy-aside restore that dies in between leaves the reviewed tree mutated, and nothing says so).

The spec is a JSON file:

    {"sync": {"agent": ["--extra", "dev"], "peer": []},
     "timeout": 600,
     "mutants": [
       {"name": "the guard gone", "file": "agent/superyak_agent/lessons_hold.py",
        "old": "    if cut in HELD_TOOLS", "new": "    if False",
        "project": "agent", "tests": ["tests/test_lessons_hold.py::test_the_guard"]},
       {"name": "any command", "file": "x.py", "old": "a", "new": "b", "run": ["sh", "-c", "..."], "cwd": "."}]}

`old` is an exact substring that must occur once in the file at the head; a site found 0 or 2+ times is not run and
says how many times it was found. A mutant with `project` runs `pytest -q -x <tests>` in that project's own venv,
made in the worktree with `uv sync --frozen` and the `sync` arguments (agent needs `--extra dev`); the worktree's own
venv, so a subprocess run with `python -I` imports the mutated code too. `sync` may name further projects to make
(agent's lessons tests run peer's). A mutant with `run` runs that command from `cwd` in the worktree instead. Each
distinct command first runs on the unmutated head: one that fails there counts nothing ("baseline fails").

Prints one line per mutant: killed, SURVIVED, killed (timeout), not run, or baseline fails, each with the command's
last line of output. Exit 0 when every mutant was killed, 1 otherwise, 2 for a bad spec or a head git can't find."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PREFIX = 'superyak-mutants-'
DEFAULT_SYNC = {'agent': ['--extra', 'dev']}
FIELDS = ('name', 'file', 'old', 'new')


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def last_line(text):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1].strip() if lines else ''


def read_spec(path):
    """The spec's mutants, checked for shape; SystemExit(2) naming what is wrong."""
    try:
        spec = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise SystemExit(f'mutants: cannot read {path}: {error}') from None
    mutants = spec.get('mutants') if isinstance(spec, dict) else None
    if not isinstance(mutants, list) or not mutants:
        raise SystemExit('mutants: the spec needs a non-empty "mutants" list')
    for number, mutant in enumerate(mutants, 1):
        if not isinstance(mutant, dict) or not all(isinstance(mutant.get(key), str) for key in FIELDS):
            raise SystemExit(f'mutants: mutant {number} needs string "name", "file", "old" and "new"')
        if mutant['old'] == mutant['new'] or not mutant['old']:
            raise SystemExit(f'mutants: {mutant["name"]}: "old" must be non-empty and differ from "new"')
        runs = isinstance(mutant.get('run'), list) and mutant['run'] and all(isinstance(a, str) for a in mutant['run'])
        tests = isinstance(mutant.get('project'), str) and isinstance(mutant.get('tests'), list) and mutant['tests']
        if bool(runs) == bool(tests):
            raise SystemExit(f'mutants: {mutant["name"]}: give either "run" or "project" with "tests"')
    sync = spec.get('sync', {})
    if not isinstance(sync, dict) or not all(isinstance(v, list) for v in sync.values()):
        raise SystemExit('mutants: "sync" maps a project to a list of `uv sync` arguments')
    timeout = spec.get('timeout', 600)
    if type(timeout) not in (int, float) or timeout <= 0:
        raise SystemExit('mutants: "timeout" is a number of seconds')
    return mutants, sync, timeout


def strays(repo):
    """Worktrees an earlier run left (it was killed before it removed them)."""
    listed = git('worktree', 'list', '--porcelain', cwd=repo)
    return [line[len('worktree '):] for line in listed.splitlines()
            if line.startswith('worktree ') and PREFIX in line]


def command(mutant, tree):
    """(argv, cwd) for a mutant's run, inside the worktree."""
    if 'run' in mutant:
        return tuple(mutant['run']), tree / mutant.get('cwd', '.')
    project = tree / mutant['project']
    return (str(project / '.venv' / 'bin' / 'python'), '-m', 'pytest', '-q', '-x', '-p', 'no:cacheprovider',
            *mutant['tests']), project


def run(argv, cwd, timeout):
    """(passed, last line), or (None, 'timeout') when the run didn't end in time."""
    env = {k: v for k, v in os.environ.items() if k not in ('VIRTUAL_ENV', 'PYTHONPATH')}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        done = subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f'no result in {timeout} s'
    except OSError as error:
        return False, f'{type(error).__name__}: {error}'
    return done.returncode == 0, last_line(done.stdout + '\n' + done.stderr)


def sync(tree, projects, extra):
    """`uv sync --frozen` in each project the run needs; the projects whose venv couldn't be made."""
    failed = set()
    for project in sorted(projects):
        args = extra.get(project, DEFAULT_SYNC.get(project, []))
        done = subprocess.run(['uv', 'sync', '--frozen', *args], cwd=tree / project, capture_output=True, text=True)
        if done.returncode != 0:
            print(f'uv sync in {project} failed: {last_line(done.stderr)}')
            failed.add(project)
    return failed


def mutate(mutants, tree, extra, timeout):
    """One (name, verdict, last line) per mutant, run in order in the worktree."""
    results, sites = [], {}
    for mutant in mutants:
        path = tree / mutant['file']
        found = path.read_text().count(mutant['old']) if path.is_file() else 0
        sites[mutant['name']] = found
    projects = {m['project'] for m in mutants if 'project' in m} | set(extra)
    broken = sync(tree, projects, extra) if projects else set()
    baselines = {}
    for mutant in mutants:
        name, found = mutant['name'], sites[mutant['name']]
        if found != 1:
            results.append((name, 'not run', f'site found {found} times in {mutant["file"]}, not once'))
            continue
        if mutant.get('project') in broken:
            results.append((name, 'not run', f'no venv for {mutant["project"]}'))
            continue
        argv, cwd = command(mutant, tree)
        if (argv, cwd) not in baselines:
            baselines[argv, cwd] = run(argv, cwd, timeout)
        passed, line = baselines[argv, cwd]
        if not passed:
            results.append((name, 'baseline fails', line))
            continue
        path = tree / mutant['file']
        path.write_text(path.read_text().replace(mutant['old'], mutant['new']))
        try:
            passed, line = run(argv, cwd, timeout)
        finally:
            git('checkout', '--', mutant['file'], cwd=tree)
        if git('status', '--porcelain', '--untracked-files=no', cwd=tree):
            raise SystemExit(f'mutants: the worktree did not come back clean after {name}; stopping')
        verdict = 'killed (timeout)' if passed is None else 'SURVIVED' if passed else 'killed'
        results.append((name, verdict, line))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/mutants.py', description=__doc__.split('\n\n')[0])
    parser.add_argument('spec', help='The JSON spec (see the module docstring)')
    parser.add_argument('--head', default='HEAD', help='The reviewed head (default HEAD)')
    parser.add_argument('--scratch', default=None, help='Where the worktree goes (default: the temp directory)')
    args = parser.parse_args(argv)
    mutants, extra, timeout = read_spec(args.spec)
    try:
        repo = Path(git('rev-parse', '--show-toplevel', cwd=Path.cwd()))
        head = git('rev-parse', '--verify', f'{args.head}^{{commit}}', cwd=repo)
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'mutants: {last_line(error.stderr) or error}') from None
    for stray in strays(repo):
        print(f'A stray worktree from an earlier run: {stray} (git worktree remove --force {stray})')
    base = Path(tempfile.mkdtemp(prefix=PREFIX, dir=args.scratch))
    tree = base / 'tree'
    try:
        git('worktree', 'add', '--detach', str(tree), head, cwd=repo)
        print(f'Mutants at {head[:12]}, in {tree}')
        results = mutate(mutants, tree, extra, timeout)
    finally:
        if tree.exists():
            subprocess.run(['git', 'worktree', 'remove', '--force', str(tree)], cwd=repo, capture_output=True)
        shutil.rmtree(base, ignore_errors=True)
    width = max(len(name) for name, _, _ in results)
    for name, verdict, line in results:
        print(f'{name.ljust(width)}  {verdict}  ({line})')
    killed = sum(verdict.startswith('killed') for _, verdict, _ in results)
    print(f'{killed} of {len(results)} killed')
    return 0 if killed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
