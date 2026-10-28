"""The agent wheel names every module the package imports (agent/pyproject.toml's only-include): an editable checkout
hides a missing one, and a wheel without it fails at import (hook.py imports claims, __main__ project_dock)."""
from pathlib import Path
import tomllib

AGENT = Path(__file__).resolve().parents[1]


def test_the_wheel_lists_every_module_in_the_package():
    listed = set(tomllib.loads((AGENT / 'pyproject.toml').read_text())['tool']['hatch']['build']['targets']['wheel']['only-include'])
    modules = {f'superyak_agent/{path.name}' for path in (AGENT / 'superyak_agent').glob('*.py')}
    assert modules - listed == set(), 'add these to only-include in agent/pyproject.toml'
