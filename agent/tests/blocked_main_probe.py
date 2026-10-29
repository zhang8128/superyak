"""Run only by test_lessons_hook.py's test_a_blocked_main_in_process_fails_the_run_rather_than_ending_it_green (its name
keeps pytest from collecting it otherwise). The hook's main(), in pytest's own process, blocked on an index that is a
FIFO, then a test that fails. With the watchdog unarmed in process (conftest), the run can't end green: it blocks
until it is killed. Armed, it would exit 0 at the prompt's limit, and the failing test would never run."""
import io
import json
import os
import sys

from superyak_agent import lessons_hook as lh


def test_a_main_blocked_on_its_index(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    data.mkdir()
    os.mkfifo(data / 'lessons-index.bin')
    settings = tmp_path / 'lessons-hook.json'
    settings.write_text(json.dumps({'ship': 'tardis', 'data_dir': str(data), 'state_dir': str(tmp_path / 'state')}))
    event = {'hook_event_name': 'UserPromptSubmit', 'session_id': 's1', 'prompt': 'a prompt that asks about something'}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(event)))
    lh.main(['--settings', str(settings)])


def test_after_it():
    assert False, 'reached only if the blocked main returned'
