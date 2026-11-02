"""A probe, not a test: run engram's tests with the clock moved ahead, to find tests that pin a calendar date against
the real clock before the calendar reaches them (fix:engram-tests-calendar: U12 broke main's CI on 2026-11-01).

    cd engram && SHIFT_DAYS=35 LIGHTHOUSE_REPO=../lighthouse uv run --locked --extra dev \
        python -m pytest -p tests.clockshift tests/test_permissions_*.py

It moves `time.time` and the store's `storage._now_iso` SHIFT_DAYS ahead (0 by default; negative moves back). It can't
move `datetime.now` called elsewhere, a file's mtime or SQLite's 'now', so a failure that compares one of those with a
shifted value is the probe's own artifact: read each failure's error before calling it a bomb. Check it catches one
first: main's U12 test before 9938006e passes at SHIFT_DAYS=-2 and fails at 0 after 2026-11-01."""
import datetime as _dt
import os
import time as _time

DAYS = float(os.environ.get('SHIFT_DAYS', '0'))
_real_time = _time.time


def pytest_configure(config):
    import storage
    offset = _dt.timedelta(days=DAYS)
    storage._now_iso = lambda: (_dt.datetime.now(_dt.timezone.utc) + offset).isoformat()
    _time.time = lambda: _real_time() + DAYS * 86400
