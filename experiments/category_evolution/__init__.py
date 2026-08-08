"""Falsifiable, disposable evaluation helpers for evolving-category memory.

Exports are lazy so the isolated ranking worker can import this package without
loading the fixture module that owns adjudication truth.
"""

from importlib import import_module

__all__ = [
    "boundary_metrics",
    "false_transfer_rate",
    "fixture_cohort",
    "fixture_hash",
    "mean_reciprocal_rank",
]


_EXPORT_MODULES = {
    "boundary_metrics": ".metrics",
    "false_transfer_rate": ".metrics",
    "fixture_cohort": ".fixtures",
    "fixture_hash": ".fixtures",
    "mean_reciprocal_rank": ".metrics",
}


def __getattr__(name: str):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
