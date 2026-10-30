"""`run_agent.py hold`: the one PreToolUse entry on Bash, for checklists and lessons (spec, The hold; Rulings 13, 31-36).

It runs before every Bash command on every ship, so it never stalls one, prints a deny, a list as context past the cap,
or nothing (never allow, ask or updatedInput), and never raises. Standard library only, plus acting, checklists,
checklist_firing, holds and the two providers: never station, claims, hook, urllib.request or http.client.

The main thread checks only the payload (plan review M2). A daemon worker runs the acting-ship check, finds and renders
the lists, then takes the session record's lock, all within READ_SECONDS of `started`; under the lock it asks the
providers and builds the output. It saves the record and publishes the output in one step under a small lock (S1), so
an output the main thread takes was recorded, and a worker not yet saving at HOLD_SECONDS is abandoned and never
saves. A save already under way then gets SAVE_SECONDS more, and its output is printed once it lands (M3); only a save
stalled past that too is recorded unseen.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

from superyak_agent import acting, checklist_firing as fp, checklist_hold, holds, lessons_hold

RERUN = 'Re-run the same command if you still want it.'
RERUN_TOOL = 'Call it again if you still want it.'  # a held tool's call has no command to re-run (lesson-holds item 8)
WORKER = 'superyak-hold'


class _Run:
    def __init__(self):
        self.read = threading.Event()   # the record is taken, or the worker stopped early
        self.lock = threading.Lock()    # the save and the publish, against the main thread giving up
        self.state = threading.Lock()   # decides, once, between the save going ahead and the main thread giving up
        self.abandoned = False
        self.saving = False
        self.result = None


def _call(payload):
    """(command, session id, cwd, transcript, tool call) for a main agent's Bash call or call to a held tool, else None.
    A held tool's command is its own name, never anything from its input (spec lesson-holds-on-tool-calls, item 2), so
    a post's text matches nothing. No file I/O (M2)."""
    if not isinstance(payload, dict) or payload.get('hook_event_name') != 'PreToolUse':
        return None
    tool = payload.get('tool_name')
    if not isinstance(tool, str) or tool != 'Bash' and tool not in lessons_hold.HELD_TOOLS:
        return None
    if payload.get('agent_id') is not None:   # a subagent is never held (D14)
        return None
    tool_input = payload.get('tool_input')
    command = tool if tool != 'Bash' else tool_input.get('command') if isinstance(tool_input, dict) else None
    session = payload.get('session_id')
    if not isinstance(command, str) or not isinstance(session, str) or not session:   # Ruling 8
        return None
    cwd, transcript = payload.get('cwd'), payload.get('transcript_path')
    return (command, session, cwd if isinstance(cwd, str) else None, transcript if isinstance(transcript, str) else None,
            tool != 'Bash')


def _output(**fields):
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', **fields}}


def _lesson(hold) -> bool:
    return (isinstance(hold, holds.Hold) and hold.kind == 'lesson' and isinstance(hold.text, str)
            and 0 < len(hold.text.encode('utf-8', 'surrogatepass')) <= holds.LESSON_BYTES)


def _lessons(ask, command, record, now, limit):
    """The lessons provider's Holds, checked against the seam, which only the entry can guarantee (Ruling 44): a list
    of at most `limit` lesson Holds, each with text of 1 to LESSON_BYTES bytes, leaving a record that still serializes.
    Anything else, a raise of any kind included, gives none and puts the record back as it was: a result is dropped,
    never cut, and a lesson's failure never silences a checklist."""
    before = json.dumps(record)
    try:
        got = ask(command, record, now, limit)
        if isinstance(got, list) and len(got) <= limit and all(_lesson(h) for h in got):
            json.dumps(record)
            return got
    except BaseException:  # noqa: BLE001 - another ship's code: SystemExit and KeyboardInterrupt are its failures too
        pass
    record.clear()
    record.update(json.loads(before))
    return []


def _log(path, lines):
    for line in lines:
        try:
            holds.append_line(path, line)
        except Exception:  # noqa: BLE001 - a failed write (or a bad clock) drops the line, never the hold
            pass


class _NoLists:
    """At a tool call the hold asks only the lessons provider (lesson-holds item 7): no checklist, and no pass spent."""
    def candidates(self, command, record, now, limit):
        return []

    def spend(self, command, record):
        return False


def _work(run, call, home, now, read_by, hold_by, monotonic, lessons):
    command, session, cwd, transcript, tool_call = call
    if not (home / 'station.json').is_file():   # an undocked machine gets no ship home and no sessions folder (Ruling 44)
        return
    if acting.verdict(home, acting.session_project(cwd))[0] != 'act':   # inside the read window (M2)
        return
    lists_here = _NoLists() if tool_call else checklist_hold.provider(home, cwd, command)
    path = holds.record_path(home / 'sessions', session)
    with holds.open_record(path, read_by, monotonic) as opened:
        if monotonic() >= read_by:
            return   # late: the main thread has given up
        run.read.set()
        record = opened.data
        holds.touch(record, now, cwd)
        record['session'] = {'id': session, 'transcript': transcript}
        count = checklist_hold.held(record)   # before any provider: one can't move the cap (Ruling 44)
        left = count < holds.HOLDS_PER_SESSION
        noted = json.dumps(record.get('lessons'), sort_keys=True)   # the provider's own entries, before it is asked
        lists = lists_here.candidates(command, record, now, fp.LISTS_PER_EVENT)
        got = _lessons(lessons or lessons_hold.candidates, command, record, now,
                       holds.HOLDS_PER_SESSION - len(lists)) if left else []
        if left and (lists or got):
            parts = [checklist_hold.first_line(record, lists[0])] if lists else []
            parts += [h.text for h in lists + got] + [RERUN_TOOL if tool_call else RERUN]
            record['holds'] = count + 1
            result = _output(permissionDecision='deny', permissionDecisionReason='\n\n'.join(parts))
        else:   # the command goes through, and spends its passes: a re-run's is saved though nothing prints (M1)
            spent = lists_here.spend(command, record)
            if lists:   # past the cap: lists reach the model with the command's result; lessons don't (R2)
                result = _output(additionalContext='\n\n'.join(h.text for h in lists))
            elif spent or json.dumps(record.get('lessons'), sort_keys=True) != noted:
                result = None   # saved though nothing prints: a pass spent, or what a provider noted (S2)
            else:
                return
        with run.lock:
            with run.state:
                if run.abandoned or monotonic() > hold_by:
                    return
                run.saving = True
            opened.save()
            run.result = result
    _log(home / 'checklists' / 'fired.jsonl', checklist_hold.fired_lines(record, lists, path.stem, now))


def _guarded(run, *args):
    try:
        _work(run, *args)
    except BaseException:  # noqa: BLE001 - a failed hold prints nothing
        pass
    finally:
        run.read.set()


def _take(run, hold_by, monotonic):
    """The published output, or None after telling the worker it is abandoned. A save under way at the deadline gets
    SAVE_SECONDS more, so what it records is printed (M3); a worker not yet saving is abandoned and never saves."""
    got = run.lock.acquire(timeout=max(0.0, hold_by - monotonic()))
    if not got:
        with run.state:
            run.abandoned = True
            saving = run.saving
        if saving:
            got = run.lock.acquire(timeout=fp.SAVE_SECONDS)
    try:
        if got and run.result is not None:
            return run.result
        run.abandoned = True
        return None
    finally:
        if got:
            run.lock.release()


def decide(payload: dict, home: Path, now: float, started: float, monotonic=time.monotonic, lessons=None) -> dict | None:
    """The JSON object to print for this PreToolUse call, or None. `started` is the monotonic time the hold began;
    `lessons` defaults to lessons_hold.candidates, looked up at call time."""
    if os.environ.get('SUPERYAK_RUN') not in (None, '', 'hook'):
        return None   # a watcher or teamd run (D8)
    call = _call(payload)
    if call is None:
        return None
    read_by, hold_by = started + fp.READ_SECONDS, started + fp.HOLD_SECONDS
    run = _Run()
    try:
        worker = threading.Thread(target=_guarded, name=WORKER, daemon=True,
                                  args=(run, call, Path(home), now, read_by, hold_by, monotonic, lessons))
        worker.start()
    except Exception:  # noqa: BLE001 - no thread to be had: no hold
        return None
    if run.read.wait(max(0.0, read_by - monotonic())):
        worker.join(max(0.0, hold_by - monotonic()))
    return _take(run, hold_by, monotonic)


def _home(argv):
    config = acting.machine_home() / 'station.json'
    for i, arg in enumerate(argv):
        if arg == '--config' and i + 1 < len(argv):
            config = Path(argv[i + 1])
        elif arg.startswith('--config='):
            config = Path(arg[len('--config='):])
    return config.expanduser().parent


def main(argv: list[str], stdin=None, stdout=None, clock=time.time, monotonic=time.monotonic) -> int:
    """Always 0. `--config` (default ~/.superyak/station.json) names the ship home; unknown flags are ignored. Bad input
    prints nothing (S9). stdin and stdout default to sys's at call time."""
    started = monotonic()   # Ruling 13: the 150 ms and the 1 s run from here
    try:
        stdin = sys.stdin if stdin is None else stdin
        stdout = sys.stdout if stdout is None else stdout
        home = _home(argv)
        if stdin.isatty():
            return 0
        result = decide(json.loads(stdin.read()), home, clock(), started, monotonic)
        if result is not None:
            try:
                stdout.write(json.dumps(result) + '\n')
                stdout.flush()
            except BaseException:  # noqa: BLE001 - the reader has gone
                _quiet(stdout)
    except BaseException:  # noqa: BLE001 - a hook must never break a Bash call
        pass
    return 0


def _quiet(stdout):
    """Point stdout's descriptor at /dev/null after a failed write, so the interpreter's flush at exit can't fail too
    and exit 120 (Ruling 44)."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, stdout.fileno())
        finally:
            os.close(devnull)
    except Exception:  # noqa: BLE001 - not a real file (a test's StringIO): nothing to flush at exit
        pass
