"""The status monitor follows real worker events without controlling the worker."""

import json
from pathlib import Path
import subprocess
import sys

from workbench.automation import main
from workbench.research_service import WorkerControl


def test_terminal_status_streams_new_activity_and_ctrl_c_leaves_worker_running(tmp_path, monkeypatch, capsys):
    control = WorkerControl(tmp_path)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    with control.lease("worker"):
        control.update({"token": "unchanged", "phase": "analyzing", "model": "test-model",
                        "paper": "First paper", "context_mode": "dynamic"})
        log = control.root / "worker.log"
        log.write_text(json.dumps({"phase": "analyzing", "paper": "First paper"}) + "\n")
        before = control.status_file.read_bytes()
        polls = []

        def advance(_):
            if polls:
                raise KeyboardInterrupt
            polls.append(True)
            with log.open("a") as stream:
                stream.write(json.dumps({"phase": "reading", "paper": "Second paper"}) + "\n")

        monkeypatch.setattr("time.sleep", advance)
        assert main(["--project", str(tmp_path), "research-status"]) == 0
        output = capsys.readouterr().out
        assert "test-model" in output
        assert "dynamic" in output
        assert "Analyzing: First paper" in output
        assert output.count("Reading: Second paper") == 1
        assert "Ctrl-C" in output
        assert control.status()["running"] is True
        assert control.status_file.read_bytes() == before
        assert not (control.root / "stop.json").exists()


def test_once_is_readable_and_does_not_initialize_state(tmp_path, capsys):
    assert main(["--project", str(tmp_path), "research-status", "--once"]) == 0
    assert "not running" in capsys.readouterr().out
    assert not (tmp_path / ".atlas").exists()


def test_json_returns_immediately_even_in_a_terminal(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert main(["--project", str(tmp_path), "research-status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["running"] is False
    assert not (tmp_path / ".atlas").exists()


def test_explicit_follow_works_without_a_terminal_and_waits_for_log_creation(tmp_path, monkeypatch, capsys):
    polls = []

    def advance(_):
        if polls:
            raise KeyboardInterrupt
        polls.append(True)
        root = tmp_path / ".atlas/research"
        root.mkdir(parents=True)
        (root / "worker.log").write_text('{"phase":"starting"}\n')

    monkeypatch.setattr("time.sleep", advance)
    assert main(["--project", str(tmp_path), "research-status", "--follow"]) == 0
    assert "Starting" in capsys.readouterr().out


def test_log_tail_bounds_history_then_preserves_partial_unicode_lines_and_reopens(tmp_path):
    from workbench.research_monitor import LogTail
    log = tmp_path / "worker.log"
    log.write_text("".join(f"past-{index}\n" for index in range(10000)))
    tail = LogTail(log)
    assert tail.read_lines() == [f"past-{index}" for index in range(9980, 10000)]
    encoded = 'Reading: β-cell\n'.encode()
    with log.open("ab") as stream:
        stream.write(encoded[:10])
    assert tail.read_lines() == []
    with log.open("ab") as stream:
        stream.write(encoded[10:])
    assert tail.read_lines() == ["Reading: β-cell"]
    assert tail.read_lines() == []
    log.rename(tmp_path / "worker.old.log")
    log.write_text("restarted\n")
    assert tail.read_lines() == ["restarted"]
    log.write_text("short\n")
    assert tail.read_lines() == ["short"]


def test_cycle_output_preserves_saved_ids_publication_errors_and_wait_time():
    from workbench.research_monitor import format_event
    lines = format_event(json.dumps({"at": "2026-09-07T19:00:00+00:00", "phase": "waiting", "cycles": 3,
        "last_cycle": {"saved": 1, "replayed": 0, "skipped": 2, "draft_count": 8,
                       "record_ids": ["draft-new"], "publication_status": "pending",
                       "errors": [{"error": "quote rejected", "attempts": 2}]}}))
    output = "\n".join(lines)
    assert "1 saved" in output
    assert "2 skipped" in output
    assert "draft-new" in output
    assert "pending" in output
    assert "quote rejected" in output
    assert "attempt 2" in output
    assert format_event('{"next_cycle_at_epoch":1788808722}')[0]


def test_plain_or_malformed_log_lines_remain_visible_without_terminal_controls():
    from workbench.research_monitor import format_event
    for line in ("Traceback: read failed", '{"broken":', "null", "[1,2]", "\x1b[2Junsafe\rtext"):
        rendered = "\n".join(format_event(line))
        assert rendered
        assert "\x1b" not in rendered
        assert "\r" not in rendered


def test_view_refresh_errors_are_visible_separately_from_saved_research():
    from workbench.research_monitor import format_event
    output = "\n".join(format_event(json.dumps({"phase": "waiting", "cycles": 2, "last_cycle": {
        "saved": 1, "publication_status": "current", "research_views": {
            "status": "pending", "errors": ["Generated note was edited; kept unchanged"]}}})))
    assert "1 saved" in output
    assert "Research views pending" in output
    assert "Generated note was edited" in output


def test_truncate_and_regrow_between_polls_does_not_skip_or_split_events(tmp_path):
    from workbench.research_monitor import LogTail
    log = tmp_path / "worker.log"
    log.write_text("old-event\n")
    tail = LogTail(log)
    assert tail.read_lines() == ["old-event"]
    log.write_text("new-event\n")
    assert tail.read_lines() == ["new-event"]
    log.write_text("longer-event-after-truncate\n")
    assert tail.read_lines() == ["longer-event-after-truncate"]


def test_closing_a_follow_pipe_exits_cleanly_without_shutdown_flush_error(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/atlas_research.py"
    root = tmp_path / ".atlas/research"
    root.mkdir(parents=True)
    log = root / "worker.log"
    log.write_text("")
    process = subprocess.Popen([sys.executable, str(script), "--project", str(tmp_path),
                                "research-status", "--follow"], cwd=tmp_path,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert "Atlas researcher" in process.stdout.readline()
        process.stdout.close()
        log.write_text('{"phase":"reading","paper":"New paper"}\n')
        assert process.wait(timeout=5) == 0
        assert process.stderr.read() == ""
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.stderr.close()
