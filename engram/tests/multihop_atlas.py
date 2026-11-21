"""Atlas's research_corpus for the multihop tests, without leaving a `workbench` module behind.

research_poc.atlas_bridge activates its frozen Atlas snapshot only while no other `workbench` module is loaded, and
pytest imports every test module before running any test. A multihop test that imported atlas/workbench at module
level therefore broke all 16 bridge tests in CI (11-21). research_corpus.py imports only the standard library, so it
loads here by file path under a private name; `atlas_workbench` lends it the `workbench` names for one test that runs
code importing it by name, and monkeypatch puts sys.modules back after.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parents[2] / "atlas"
SOURCE = ATLAS / "workbench" / "research_corpus.py"
PRIVATE = "_engram_tests_research_corpus"


def research_corpus():
    if not SOURCE.exists():
        pytest.skip("atlas isn't beside engram here", allow_module_level=True)
    if PRIVATE not in sys.modules:
        spec = importlib.util.spec_from_file_location(PRIVATE, SOURCE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[PRIVATE] = module  # registered before running, as an import would
        spec.loader.exec_module(module)
    return sys.modules[PRIVATE]


@pytest.fixture
def atlas_workbench(monkeypatch):
    """`workbench.research_corpus` importable by name for this test only."""
    module = research_corpus()
    package = types.ModuleType("workbench")
    package.research_corpus = module
    monkeypatch.setitem(sys.modules, "workbench", package)
    monkeypatch.setitem(sys.modules, "workbench.research_corpus", module)
    return module


def loaded_from_atlas():
    """Names of modules loaded from atlas/workbench itself (a frozen snapshot's copy lives elsewhere)."""
    root = (ATLAS / "workbench").resolve()
    return sorted(name for name, module in list(sys.modules.items())
                  if (name == "workbench" or name.startswith("workbench."))
                  and getattr(module, "__file__", None) and Path(module.__file__).resolve().is_relative_to(root))
