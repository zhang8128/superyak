"""Section 8's pinned test: the lessons hook at a prompt makes no writes at all. It runs the hook as Claude Code does,
`python -B run_agent.py lessons-hook`, under an audit hook (lessons_audit.py), on a marker prompt, and fails on any
file opened for writing, any database opened, or the marker anywhere under the data directory, the hook's state, the
temporary directory or HOME. Then each other event runs after the marker prompt, against a transcript holding the
marker and a prompt-shown id line, and neither reaches the hook's state."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from superyak_agent import lessons_hook as lh
from test_lessons_hook import A, B, C, Rail, failure, lesson, transcript_line

AGENT = Path(__file__).resolve().parents[1]
RUN_AGENT = AGENT / 'run_agent.py'
AUDIT = Path(__file__).with_name('lessons_audit.py')


@pytest.fixture
def world(tmp_path):
    """A peer's rail, with a HOME and a temporary directory of its own, and an earlier event's record in its state."""
    rail = Rail(tmp_path)
    (rail.data / 'record').unlink()  # the stub writes nothing here
    rail.home, rail.tmp = tmp_path / 'home', tmp_path / 'tmp'
    rail.home.mkdir()
    rail.tmp.mkdir()
    rail.state.mkdir()
    (rail.state / f'{lh.session_key("s1")}.json').write_text(json.dumps({'shown': [C], 'commands': [], 'errors': []}))
    rail.marker = f'MARKER-{uuid.uuid4().hex}'
    return rail


def audited(rail, script, *args, stdin=b'', python_flags=('-B',)):
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(rail.home), 'TMPDIR': str(rail.tmp),
           'NOWRITE_PROMPT_LIMIT': '5'}
    return subprocess.run([sys.executable, *python_flags, str(AUDIT), str(script), *args], input=stdin, env=env,
                          capture_output=True, timeout=60)


def everything_under(*folders):
    """(path, bytes) of every file under the folders, the folders' names included in the paths."""
    return [(p, p.read_bytes()) for folder in folders for p in sorted(Path(folder).rglob('*')) if p.is_file()]


def snapshot(folder):
    return {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in Path(folder).rglob('*') if p.is_file()}


def test_the_hook_at_a_prompt_writes_nothing(world):
    world.answers(lesson(A, ship='serenity'), lesson(B, ship='rio-grande'))
    world.shown_at_prompt(lesson('dddddddd-eeeeeeee'))
    before = snapshot(world.state), snapshot(world.data), snapshot(world.tmp)
    event = {'hook_event_name': 'UserPromptSubmit', 'session_id': 's1', 'transcript_path': str(world.transcript),
             'cwd': str(world.root), 'prompt': f'Please look at {world.marker} and tell me what it means, thanks.'}
    done = audited(world, RUN_AGENT, 'lessons-hook', '--settings', str(world.settings), stdin=json.dumps(event).encode())
    assert done.returncode == 0
    context = json.loads(done.stdout)['hookSpecificOutput']['additionalContext']
    assert f'Lesson {A} from serenity' in context and f'Lesson {B} from rio-grande' in context  # it really ran
    audit = done.stderr.decode()
    assert 'AUDIT' not in audit, audit  # no write, no database, and not even the station client imported
    assert (snapshot(world.state), snapshot(world.data), snapshot(world.tmp)) == before
    for path, content in everything_under(world.data, world.state, world.tmp, world.home):
        assert world.marker not in str(path) and world.marker.encode() not in content, path


def test_the_audit_catches_a_write_and_a_database(world):
    """The check above can fail: the same wrapper names a file opened for writing and an opened database."""
    script = world.root / 'writer.py'
    script.write_text(f'open({str(world.tmp / "x")!r}, "w").close()\nimport sqlite3\nsqlite3.connect(":memory:")\n')
    audit = audited(world, script).stderr.decode()
    assert "AUDIT 'write'" in audit and "AUDIT 'import' 'sqlite3'" in audit and "AUDIT 'sqlite3.connect'" in audit
    assert "AUDIT 'imported' 'sqlite3'" in audit
    script.write_text('import os, tempfile\nos.close(tempfile.mkstemp()[0])\n')
    assert "AUDIT 'tempfile.mkstemp'" in audited(world, script).stderr.decode()


def test_the_other_events_after_a_marker_prompt_keep_neither_the_marker_nor_the_prompts_lesson(world):
    """Section 8: the record holds digests and the ids shown at the hook's own events, never what it read from the
    transcript. P was shown at the marker prompt; the stub answers it again, ignoring `seen`."""
    prompt_lesson = '0f0f0f0f-a0a0a0a0'
    with world.transcript.open('a') as stream:
        stream.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': f'Fix {world.marker} please'}}) + '\n')
        stream.write(transcript_line(lh.render([lesson(prompt_lesson, ship='serenity')])) + '\n')
    world.flag('ignore-seen')
    world.answers(lesson(prompt_lesson, ship='serenity'), lesson(A, ship='serenity'))
    events = [('SessionStart', {'cwd': str(world.root), 'source': 'resume'}),
              ('PostToolUseFailure', {'cwd': str(world.root), **failure(command=f'grep {world.marker} -r .',
                                                                        error=f'Exit code 1\nno {world.marker} here')})]
    for name, fields in events:
        event = {'hook_event_name': name, 'session_id': 's1', 'transcript_path': str(world.transcript), **fields}
        done = audited(world, RUN_AGENT, 'lessons-hook', '--settings', str(world.settings), stdin=json.dumps(event).encode())
        assert done.returncode == 0
        if done.stdout:
            assert prompt_lesson not in done.stdout.decode()
    record = json.loads((world.state / f'{lh.session_key("s1")}.json').read_text())
    assert record['shown'] == [C, A]  # A shown once, at session start; the prompt's lesson never
    for path, content in everything_under(world.state):
        assert world.marker not in str(path) and world.marker.encode() not in content, path
        assert prompt_lesson.encode() not in content, path


@pytest.mark.parametrize('stdin', [b'', b'not json', b'[]', b'{"hook_event_name": "UserPromptSubmit"}'])
def test_the_launcher_never_errors_and_prints_nothing_for_nonsense(world, stdin):
    done = audited(world, RUN_AGENT, 'lessons-hook', '--settings', str(world.settings), stdin=stdin)
    assert done.returncode == 0 and done.stdout == b''


def test_main_takes_the_same_path(world, monkeypatch, capsys):
    from superyak_agent.__main__ import main
    monkeypatch.setitem(lh.LIMITS, lh.PROMPT, 5.0)
    world.answers(lesson(A, ship='serenity'))
    event = {'hook_event_name': 'UserPromptSubmit', 'session_id': 's1', 'transcript_path': str(world.transcript),
             'prompt': 'what now'}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(event)))
    assert main(['lessons-hook', '--settings', str(world.settings)]) == 0
    assert f'Lesson {A} from serenity' in capsys.readouterr().out
