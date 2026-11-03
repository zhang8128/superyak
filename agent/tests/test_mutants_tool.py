"""scripts/mutants.py (`make mutants`), run as a reader runs it, against a throwaway repo whose checks are plain commands
(roadmap-commons step 2: the mutant run as one assembly)."""
import json
import re
import subprocess
import sys
from pathlib import Path
import pytest

TOOL = Path(__file__).resolve().parents[2] / 'scripts' / 'mutants.py'
pytestmark = pytest.mark.skipif(not TOOL.is_file(), reason='needs scripts/ from the full repository')
CALC = 'def double(x):\n    return x * 2\n\n\nLIMIT = 2\n'
CHECK = 'import calc\nassert calc.double(2) == 4 and calc.double(0) == 0\n'


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'calc.py').write_text(CALC)
    (repo / 'check.py').write_text(CHECK)
    git(repo, 'add', '.')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'calc')
    return repo


def mutant(name, old, new, run=('check.py',)):
    return {'name': name, 'file': 'calc.py', 'old': old, 'new': new, 'run': [sys.executable, '-B', *run]}


def mutants(repo, tmp_path, *items, head=None):
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps({'mutants': list(items)}))
    scratch = tmp_path / 'scratch'
    scratch.mkdir(exist_ok=True)
    done = subprocess.run([sys.executable, '-I', str(TOOL), str(spec), '--scratch', str(scratch),
                           *(('--head', head) if head else ())], cwd=repo, capture_output=True, text=True, timeout=120)
    return done.returncode, done.stdout + done.stderr


VERDICT = re.compile(r'(\S.*?) {2,}(killed \(timeout\)|killed|SURVIVED|not run|baseline fails)  \(')


def verdicts(out):
    return {found[1]: found[2] for found in map(VERDICT.match, out.splitlines()) if found}


def test_each_mutant_is_killed_survives_or_is_not_run_and_the_readers_tree_is_untouched(repo, tmp_path):
    """A mutant the check catches is killed, one it can't tell apart survives, and a site that isn't found exactly once
    is not run, saying how often it was found (Rio Grande's point: an ambiguous site caught two bad mutants). The
    reader's tree, an uncommitted edit included, is left as it was, and no worktree is left behind. Mutations: the
    count check dropped (a missing site is run and counted), the run made in the reader's tree."""
    (repo / 'calc.py').write_text(CALC + '# the reader is still editing\n')
    code, out = mutants(repo, tmp_path, mutant('times three', 'x * 2', 'x * 3'), mutant('plus itself', 'x * 2', 'x + x'),
                        mutant('missing', 'x * 4', 'x * 5'), mutant('twice', '2', '3'))
    assert code == 1, out
    assert verdicts(out) == {'times three': 'killed', 'plus itself': 'SURVIVED', 'missing': 'not run', 'twice': 'not run'}
    assert 'site found 0 times' in out and 'site found 2 times' in out and '1 of 4 killed' in out
    assert (repo / 'calc.py').read_text() == CALC + '# the reader is still editing\n'
    assert git(repo, 'worktree', 'list').count('\n') == 0 and not list((tmp_path / 'scratch').iterdir())


def test_every_mutant_killed_exits_0_and_a_head_is_read_as_committed(repo, tmp_path):
    """The run is at the reviewed head, not the working tree: here the head's own calc.py. Mutation: the worktree made
    from the reader's checkout instead of the head."""
    first = git(repo, 'rev-parse', 'HEAD')
    (repo / 'calc.py').write_text(CALC.replace('x * 2', 'x * 2  # later'))
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qam', 'later')
    code, out = mutants(repo, tmp_path, mutant('times three', 'x * 2\n', 'x * 3\n'), head=first)
    assert code == 0 and verdicts(out) == {'times three': 'killed'} and f'Mutants at {first[:12]}' in out, out


def test_a_check_that_fails_unmutated_counts_nothing(repo, tmp_path):
    """Each command first runs on the unmutated head; one that fails there kills nothing. Mutation: no baseline (the
    mutant is counted as killed)."""
    (repo / 'broken.py').write_text('raise SystemExit(1)\n')
    git(repo, 'add', 'broken.py')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'broken')
    code, out = mutants(repo, tmp_path, mutant('times three', 'x * 2', 'x * 3', run=('broken.py',)))
    assert code == 1 and verdicts(out) == {'times three': 'baseline fails'}, out


def test_a_kill_shows_the_assert_it_died_on(repo, tmp_path):
    """A failed run shows its first pytest failure line beside the verdict, so a reader sees which check a mutant died
    on, not only that it died (the carry's reader caught two mutants dying on another check than their test named).
    Mutation: the failure line left out (the table shows only the summary)."""
    (repo / 'explain.py').write_text('import calc\nif calc.double(2) != 4:\n    print("E       assert (6 == 4)")\n'
                                     '    raise SystemExit(1)\n')
    git(repo, 'add', 'explain.py')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'explain')
    code, out = mutants(repo, tmp_path, mutant('times three', 'x * 2', 'x * 3', run=('explain.py',)))
    assert code == 0 and verdicts(out) == {'times three': 'killed'}, out
    assert 'E assert (6 == 4)' in next(line for line in out.splitlines() if line.startswith('times three')), out


def test_a_stray_worktree_from_an_earlier_run_is_named(repo, tmp_path):
    """A run killed before it cleaned up leaves its worktree; the next run says where, and how to remove it."""
    stray = tmp_path / 'superyak-mutants-old' / 'tree'
    git(repo, 'worktree', 'add', '--detach', str(stray), 'HEAD')
    code, out = mutants(repo, tmp_path, mutant('times three', 'x * 2', 'x * 3'))
    assert code == 0 and f'A stray worktree from an earlier run: {stray}' in out, out


@pytest.mark.parametrize('bad', [{}, {'mutants': []}, {'mutants': [mutant('m', 'x * 2', 'x * 3')], 'timeout': 0},
                                 {'mutants': [mutant('m', 'x * 2', 'x * 3')], 'sync': {'agent': '--extra dev'}}])
def test_a_spec_of_the_wrong_shape_is_refused_before_anything_runs(repo, tmp_path, bad):
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps(bad))
    done = subprocess.run([sys.executable, '-I', str(TOOL), str(spec)], cwd=repo, capture_output=True, text=True)
    assert done.returncode == 2 and done.stderr.startswith('mutants: ') and git(repo, 'worktree', 'list').count('\n') == 0


def test_a_mutant_of_the_wrong_shape_is_not_run_and_the_rest_are(repo, tmp_path):
    """Rio Grande's note on b831314e: one mutant's bad shape no longer stops the spec; it is not run, with the reason,
    as a site not found once is. Mutation: a shape problem raised (the run stops, and the good mutant isn't run)."""
    code, out = mutants(repo, tmp_path, mutant('times three', 'x * 2', 'x * 3'),
                        {'name': 'no new', 'file': 'calc.py', 'old': 'x'}, mutant('same', 'x * 2', 'x * 2'),
                        {'name': 'both', 'file': 'calc.py', 'old': 'x * 2', 'new': 'x', 'run': ['true'],
                         'project': 'agent', 'tests': ['t']}, 'not a mutant')
    assert code == 1, out
    assert verdicts(out) == {'times three': 'killed', 'no new': 'not run', 'same': 'not run', 'both': 'not run',
                             'mutant 5': 'not run'}
    assert 'needs string "name", "file", "old" and "new"' in out and 'differ from "new"' in out and 'either "run"' in out
