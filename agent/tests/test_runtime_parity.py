"""Version check V8: the station's RUNTIME_PATHS names every team/ file the agent loads. A fresh interpreter answers,
because under the full suite pytest has already imported team modules before any test runs."""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
ROOT = AGENT.parent
PROBE = r'''
import importlib, json, pkgutil, sys
from pathlib import Path
sys.path[:0] = ['.', '../team']  # run_agent.py's own path
import superyak_agent
for module in pkgutil.iter_modules(superyak_agent.__path__):
    importlib.import_module('superyak_agent.' + module.name)
root = Path('..').resolve()
print(json.dumps(sorted(str(Path(mod.__file__).resolve().relative_to(root)) if getattr(mod, '__file__', None)
                        else '(no file) ' + name  # a namespace package or an extension can't hide from the check
                        for name, mod in list(sys.modules.items())
                        if name == 'superyak_team' or name.startswith('superyak_team.'))))
'''


def runtime_paths():
    """RUNTIME_PATHS from peer/superyak_peer/agent_version.py, read with ast, without importing the peer."""
    tree = ast.parse((ROOT / 'peer' / 'superyak_peer' / 'agent_version.py').read_bytes())
    [node] = [n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'RUNTIME_PATHS']
    return ast.literal_eval(node.value)


def missing_from(paths, files):
    """The files no path names: a path names a file itself, or every file under it when it is a folder."""
    return [f for f in files if not any(f == p or f.startswith(p + '/') for p in paths)]


def agent_team_files():
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    done = subprocess.run([sys.executable, '-c', PROBE], cwd=AGENT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])  # the last line: an import that prints can't break it


def test_runtime_paths_name_every_team_file_the_agent_loads():
    files = agent_team_files()
    assert 'team/superyak_team/workers.py' in files  # the probe really sees the agent's imports
    assert missing_from(runtime_paths(), files) == []


def test_every_runtime_path_still_names_a_file():
    files = agent_team_files()

    def stale(path):  # a team entry must be a file the agent loads; an agent entry must exist
        return path not in files if path.startswith('team/') else not (ROOT / path).exists()
    assert [path for path in runtime_paths() if stale(path)] == []  # a renamed or removed file must leave the list too


def test_the_check_names_a_team_file_left_out_of_the_list():
    paths = tuple(p for p in runtime_paths() if p != 'team/superyak_team/teamlib.py')
    assert missing_from(paths, agent_team_files()) == ['team/superyak_team/teamlib.py']
