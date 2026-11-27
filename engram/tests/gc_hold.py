"""Holding the garbage collector still over a test's timed span (board item test:timing-tests-hold-gc).

Mid-suite on the Pi, a generation-2 collection runs a median of 325 ms, and up to 426 ms (a gc.callbacks probe of a
full Engram run, 2026-11-26, Python 3.14). A bound that separates two code paths in a few hundred milliseconds can
meet one. ``held_gc`` collects first, so garbage already made can't trigger a pass inside the span, then turns the
collector off and puts back whatever state it found. It never calls ``gc.freeze()``: that would move every object the
suite has made into the permanent generation for the rest of the run.

Opt in through the ``hold_gc`` fixture, and only where a time bound separates two code paths. A test that merely
measures doesn't need it.
"""
from __future__ import annotations

import gc
from contextlib import contextmanager


@contextmanager
def held_gc():
    was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()
