"""Checklists S-a: one copy of the acting-ship rule, importable without the station client."""
import subprocess
import sys
import tomllib
from pathlib import Path
from superyak_agent import acting, claims, station
from ships_fakes import isolate_git, make_repo

AGENT = Path(__file__).resolve().parents[1]
MOVED = ('NAME', 'Repo', 'Unreadable', 'machine_home', 'ships_root', 'project_home', 'kind_of', 'project_root',
         'registry_path', 'claim_files', 'read_registry', 'read_json_quiet', 'match', 'session_project', 'verdict')


def test_acting_imports_only_the_standard_library():
    code = ('import sys, superyak_agent.acting; print(sorted(m for m in sys.modules '
            'if m.startswith(("superyak", "urllib.request", "http.client"))))')
    done = subprocess.run([sys.executable, '-c', code], cwd=AGENT, capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "['superyak_agent', 'superyak_agent.acting']"


def test_claims_and_station_hand_out_the_same_objects():
    assert all(getattr(claims, name) is getattr(acting, name) for name in MOVED)
    assert station.session_key is acting.session_key and acting.session_key('abc') == 'ba7816bf8f01cfea'


def test_acting_home_is_the_project_ship_in_its_claim_and_the_machine_ship_elsewhere(monkeypatch, tmp_path):
    isolate_git(monkeypatch, tmp_path)
    repo = make_repo(tmp_path / 'bricks')
    claims.claim('serenity-bricks', repo)
    assert acting.acting_home(str(repo / 'sub')) == claims.project_home('serenity-bricks')
    assert acting.acting_home(str(tmp_path)) == acting.machine_home() == acting.acting_home(None)


def test_every_agent_module_is_in_the_wheel_inventory():
    wheel = tomllib.loads((AGENT / 'pyproject.toml').read_text())['tool']['hatch']['build']['targets']['wheel']
    assert {f'superyak_agent/{p.name}' for p in (AGENT / 'superyak_agent').glob('*.py')} <= set(wheel['only-include'])
