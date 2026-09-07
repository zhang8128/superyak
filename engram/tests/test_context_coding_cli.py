import json

import pytest

from context_cli import build_parser, main
from context_coding_cli import approve_terminal, render_event


def test_code_parser_supports_named_tasks_and_limits(tmp_path):
    args = build_parser().parse_args(['--thread', 'parser', 'code', '--repo', str(tmp_path), '--max-episodes', '7', 'Fix parser'])
    assert args.thread == 'parser' and args.task == 'Fix parser'
    assert args.max_episodes == 7
    assert args.episode_seconds == 900
    args = build_parser().parse_args(['--thread', 'parser', 'code', '--repo', str(tmp_path), '--resume'])
    assert args.resume and args.task is None


def test_noninteractive_approvals_decline_without_reading_input(monkeypatch, capsys):
    class NonInteractive:
        def isatty(self): return False
        def readline(self): raise AssertionError('must not read stdin')
    monkeypatch.setattr('sys.stdin', NonInteractive())
    assert approve_terminal({'method': 'item/commandExecution/requestApproval', 'params': {'command': 'echo hello'}}) is False
    assert 'declined' in capsys.readouterr().err.lower()


def test_rendering_escapes_terminal_sequences(capsys):
    render_event({'method': 'item/started', 'params': {'item': {'type': 'commandExecution', 'command': 'echo \x1b[2Jhello\rspoof'}}})
    text = capsys.readouterr().out
    assert '\x1b' not in text and '\r' not in text
    assert 'hello' in text


def test_code_refuses_api_fallback_and_unidentified_resume(tmp_path, capsys):
    for argv, expected in [(['--provider', 'responses', 'code', 'Fix it'], 'subscription'),
                           (['code', '--resume'], '--thread')]:
        assert main(['--data-dir', str(tmp_path), *argv]) == 1
        assert expected in capsys.readouterr().err


def test_cli_paused_result_prints_exact_resume_command(tmp_path, monkeypatch, capsys):
    import context_coding_cli
    class Runtime:
        class Provider:
            def close(self): pass
        provider = Provider()
        def run(self, thread, task, resume):
            assert thread == 'my-task'
            return {'status': 'paused', 'reason': 'Episode limit reached', 'episodes': 1, 'checkpoint': None}
    monkeypatch.setattr(context_coding_cli, 'make_coding_runtime', lambda *a, **kw: Runtime())
    code = main(['--data-dir', str(tmp_path / 'archive data'), '--no-engram', '--thread', 'my-task', 'code', '--repo', str(tmp_path), 'Fix parser'])
    assert code == 2
    output = capsys.readouterr().out
    assert '--resume' in output and 'my-task' in output
    assert '--data-dir' in output and 'archive data' in output
    assert '--no-engram' in output


def test_status_exposes_durable_coding_progress(tmp_path, capsys):
    from context_store import ContextStore
    store = ContextStore(tmp_path / 'context.db')
    store.append('job', 'system', json.dumps({'status': 'paused', 'episodes': 3}), kind='coding_progress')
    store.close()
    assert main(['--data-dir', str(tmp_path), '--thread', 'job', 'status']) == 0
    assert json.loads(capsys.readouterr().out)['coding']['episodes'] == 3
