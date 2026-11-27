"""Holding the garbage collector still over a test's timed span (board item test:timing-tests-hold-gc).

Mid-suite on the Pi, a generation-2 collection runs a median of 325 ms, and up to 426 ms (a gc.callbacks probe of a
full Engram run, 2026-11-26, Python 3.14). A bound that separates two code paths in a few hundred milliseconds can
meet one. ``held_gc`` turns the collector off, so no automatic pass can start inside the span, and puts back whatever
state it found. It runs one full collection first, so the span starts from a clean heap; that costs about one pass
(a median of 325 ms mid-suite) at setup, outside the span. An explicit ``gc.collect()`` still runs while it's held:
the only one on a code path today is the embedder's idle unload (embeddings.py:207). It never calls ``gc.freeze()``:
that would move every object the suite has made into the permanent generation for the rest of the run.

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
        else:
            gc.disable()
