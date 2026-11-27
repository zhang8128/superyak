"""The opt-in `hold_gc` fixture's own guards (board item test:timing-tests-hold-gc, Tardis's design): a full
collection first, the collector off for the timed span, and its earlier state back whatever happens."""
from __future__ import annotations

import gc
import weakref

import pytest

from tests.gc_hold import held_gc


class _Node:
    pass


def _cycle_with_a_watch():
    a, b = _Node(), _Node()
    a.other, b.other = b, a          # a reference cycle: only the cyclic collector frees it
    return weakref.ref(a)


def test_it_collects_before_the_span_so_old_garbage_cant_pause_inside_it():
    gc.disable()
    try:
        watch = _cycle_with_a_watch()
        assert watch() is not None   # the cycle is still alive with the collector off
        with held_gc():
            assert watch() is None   # freed on entry, before the timed span begins
    finally:
        gc.enable()


def test_the_collector_is_off_inside_and_on_after():
    assert gc.isenabled()
    with held_gc():
        assert not gc.isenabled()
    assert gc.isenabled()


def test_it_comes_back_on_when_the_span_raises():
    with pytest.raises(RuntimeError):
        with held_gc():
            raise RuntimeError("a failed timing assert")
    assert gc.isenabled()


def test_a_collector_already_off_stays_off():
    gc.disable()
    try:
        with held_gc():
            assert not gc.isenabled()
        assert not gc.isenabled()    # it restores what it found, never forces the collector on
    finally:
        gc.enable()


def test_it_never_freezes(monkeypatch):
    monkeypatch.setattr(gc, "freeze", lambda: pytest.fail("gc.freeze moves every live object out of collection"))
    with held_gc():
        pass


def test_the_fixture_holds_it(hold_gc):
    assert not gc.isenabled()
