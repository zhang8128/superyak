"""A clock that starts on a fixed date and then ticks with the real elapsed time.

Tests that give a policy or a publisher a window (validFrom, validUntil) pass this as the component's clock, so the
window is judged against a date the test chose rather than against the day the suite runs. It ticks, not freezes, so
a test that waits for a deadline or a turn to run out still sees time pass. Pinned a few days after the dates the
lighthouse tests write into their frames and policies (2026-09-01 .. 2026-09-06), and well inside their windows."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

PINNED_START = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


def pinned_clock(start: datetime = PINNED_START):
    began = time.monotonic()
    return lambda: start + timedelta(seconds=time.monotonic() - began)


def pinned_datetime(start: datetime = PINNED_START):
    """A stand-in for the `datetime` name inside a module that reads the real clock with no clock argument:
    monkeypatch.setattr(module, 'datetime', pinned_datetime()). Only `now` is pinned; the rest is datetime."""
    clock = pinned_clock(start)

    class PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = clock()
            return moment if tz is None else moment.astimezone(tz)
    return PinnedDatetime
