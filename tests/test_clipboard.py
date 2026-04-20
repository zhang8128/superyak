"""Tests for the clipboard module."""

import time
import tempfile
from pathlib import Path

import pytest

from clipboard import Clipboard


@pytest.fixture
def cb(tmp_path):
    db = tmp_path / "clipboard.db"
    c = Clipboard(db_path=db, max_chars=2000)
    yield c
    c.close()


class TestPins:
    def test_pin_and_list(self, cb):
        pid = cb.pin("current goal: build clipboard")
        pins = cb.pins()
        assert len(pins) == 1
        assert pins[0]["text"] == "current goal: build clipboard"
        assert pins[0]["id"] == pid

    def test_unpin(self, cb):
        pid = cb.pin("temporary note")
        assert cb.unpin(pid)
        assert len(cb.pins()) == 0

    def test_unpin_matching(self, cb):
        cb.pin("watch for: memory overload")
        cb.pin("watch for: context drift")
        cb.pin("unrelated pin")
        removed = cb.unpin_matching("watch for")
        assert removed == 2
        assert len(cb.pins()) == 1

    def test_priority_ordering(self, cb):
        cb.pin("low priority", priority=0)
        cb.pin("high priority", priority=10)
        cb.pin("medium priority", priority=5)
        pins = cb.pins()
        assert pins[0]["text"] == "high priority"
        assert pins[1]["text"] == "medium priority"
        assert pins[2]["text"] == "low priority"


class TestReminders:
    def test_add_and_list(self, cb):
        rid = cb.add_reminder("check context budget", trigger_type="every_n_steps", trigger_value=5)
        rems = cb.reminders()
        assert len(rems) == 1
        assert rems[0]["id"] == rid

    def test_remove(self, cb):
        rid = cb.add_reminder("temp reminder")
        assert cb.remove_reminder(rid)
        assert len(cb.reminders()) == 0

    def test_step_trigger(self, cb):
        cb.add_reminder("step check", trigger_type="every_n_steps", trigger_value=3)
        # Steps 1, 2 — no fire
        cb.step()
        cb.step()
        fired = cb._check_reminders(time.time())
        assert len(fired) == 0
        # Step 3 — fire
        cb.step()
        fired = cb._check_reminders(time.time())
        assert len(fired) == 1
        assert fired[0]["text"] == "step check"

    def test_interval_trigger(self, cb):
        cb.add_reminder("time check", trigger_type="interval_seconds", trigger_value=0.1)
        # Immediately — last_fired is 0, so interval has passed
        fired = cb._check_reminders(time.time())
        assert len(fired) == 1

    def test_once_trigger_fires_once(self, cb):
        target = time.time() - 1  # already in the past
        cb.add_reminder("one-shot", trigger_type="once_at", trigger_value=target, repeat=False)
        fired = cb._check_reminders(time.time())
        assert len(fired) == 1
        # Should be removed since repeat=False
        assert len(cb.reminders()) == 0

    def test_repeating_reminder_persists(self, cb):
        cb.add_reminder("recurring", trigger_type="every_n_steps", trigger_value=2, repeat=True)
        cb.step()
        cb.step()
        fired = cb._check_reminders(time.time())
        assert len(fired) == 1
        # Still exists
        assert len(cb.reminders()) == 1


class TestCompose:
    def test_empty_clipboard(self, cb):
        result = cb.compose()
        assert result == ""

    def test_pins_appear(self, cb):
        cb.pin("remember: Danielle likes dark roast")
        result = cb.compose()
        assert "dark roast" in result
        assert "[pinned]" in result

    def test_reminders_appear_when_fired(self, cb):
        cb.add_reminder("breathe", trigger_type="every_n_steps", trigger_value=1)
        cb.step()
        result = cb.compose()
        assert "breathe" in result
        assert "[reminders]" in result

    def test_budget_respected(self, cb):
        cb_small = Clipboard(db_path=cb.db_path, max_chars=100)
        for i in range(20):
            cb_small.pin(f"pin number {i} with some extra text to fill space")
        result = cb_small.compose()
        assert len(result) <= 200  # some overhead for headers
        cb_small.close()

    def test_compose_with_situation(self, cb):
        # Without a real engram DB, situation-based pull returns empty
        # but compose should still work with just pins
        cb.pin("working on memory architecture")
        result = cb.compose(situation="clipboard design")
        assert "memory architecture" in result


class TestStats:
    def test_stats(self, cb):
        cb.pin("a")
        cb.add_reminder("b")
        cb.step()
        cb.step()
        s = cb.stats
        assert s["pins"] == 1
        assert s["reminders"] == 1
        assert s["steps"] == 2
