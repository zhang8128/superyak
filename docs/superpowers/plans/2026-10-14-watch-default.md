# Watch by Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code session that shows room messages and is in write mode holds the watch by default, with a
20-minute lease, lets go in plan mode, and keeps the session's own choice, including an opt-out that sticks.

**Architecture:** Agent-only.
- The prompt hook gains `_watch_default`, called after the instructions call and before the inbox call. It reads the
  session's choice from `<key>.watch` (written only by the MCP tool). It keeps its own `<key>.prompted`
  (`{"seen", "held"}`) to declare only at the first prompt and after a gap, and to release a default it holds at a
  plan-mode prompt.
- The MCP tool `station_watch` writes `<key>.watch` for this session's own watch.
- A shared `station.session_key` gives both the same key.
- Pruning covers the new files.

**Tech Stack:** Python 3.11+, stdlib only, pytest.

**Status:** revision 2, **approved**: the same reviewer's re-check is APPROVE (two bookkeeping nits, taken). Revision 1 (5570319) had the fresh reviewer's verdict,
APPROVE WITH CHANGES (0 must-fix, 4 should-fix, 5 nits; room message 04e1446c): see "Review map". Should-fix 2
(requirement 5's wording) went to the spec's D8 reviewer.

**Spec:** `docs/superpowers/specs/2026-10-14-watch-default-design.md`, revision 3, approved under D8 (3eff438). Read
W1-W6, requirements 1-9 and the review maps first.

**How work runs:** a fresh reviewer approves this plan; then each task gets a fresh implementer and review, then a
whole-branch review. The branch merges when Rio Grande approves it and the Pi suites pass (law section 2).

## Global Constraints

- **Who:** a declaration happens only at a prompt (`event == 'prompt'`) with a session id, room messages on, and
  `mode == 'write'`. It never happens in a watcher run or for a standing-down D7 ship; `run()` already returns before
  any call there.
- **What:** `station_watch` with the session's own `minutes`/`writable` if `.watch` holds a choice, else `minutes=20`,
  `writable=true`.
- **When:** at the first qualifying prompt; again only if `.prompted` is missing, `held` is false, or `seen` is more
  than the lease ago (or in the future).
- **Where:** after the instructions call, before the inbox call, only if not past `INSTRUCTIONS_DEADLINE`, with
  `INBOX_CALL_TIMEOUT`. The inbox advance stays the last network call (R4).
- **Plan mode:** at a plan-mode prompt, if `.prompted` says `held` and `.watch` holds no minutes choice, the hook sends
  `station_watch minutes=0` and writes `held: false`.
- **Files, one writer each:**
  - `<key>.watch` is written only by the MCP tool, for this session's own watch;
  - `<key>.prompted` is written only by the hook;
  - `<key>` = `sha256(session_id)[:16]`, from `station.session_key`, used by both;
  - each file carries `seen`.
- **Silence:** nothing is printed, ever. Any failure leaves `.prompted` unwritten, so the next qualifying prompt tries
  again. The hook's output is byte-for-byte what it would be without the feature.
- **Pruning:** `STATE_NAME` covers `.json`, `.watch` and `.prompted`. `_prune` deletes by `seen` after 14 days, and
  never touches the current session's files.
- **The station is unchanged.**

## Review Focus

1. **A session id with unusual characters** (a lone surrogate, non-ASCII). Both sides use `session_key`, so the hook
   and the MCP tool name the same file (Task 1, `test_the_key_is_shared`).
2. **A clock that goes backwards** (`seen` in the future). The prompt counts as not fresh, so it declares; it never
   suppresses a declaration forever (Task 1, `test_a_seen_in_the_future_declares`).
3. **A damaged `.watch` or `.prompted`** (not JSON, not an object, wrong types). Treated as absent, so the default
   applies (Task 1, `test_damaged_files_count_as_absent`).
4. **The ship's 10-watch cap or any refusal** (429). Silent, with nothing printed, and `.prompted` isn't written, so it
   retries after the gap rule (Task 1, `test_a_refused_declaration_is_silent_and_retried`).
5. **A long-lived session older than 14 days.** Its own `.watch` and `.prompted` are never pruned while it runs
   (Task 1, `test_prune_keeps_the_current_sessions_files`).

---

### Task 1: The hook's default, and the shared key

**Files:**
- Modify: `agent/superyak_agent/station.py`: add `session_key`
- Modify: `agent/superyak_agent/hook.py`: `_session_file` uses `session_key`; `STATE_NAME`; `_prune`; new
  `_watch_default` and `_watch_client`; `run()` passes `mode` to `_run_all`; `_run_all` calls `_watch_default`
- Modify: `agent/tests/test_presence_client.py` (`test_the_headers_change_nothing_else`: the default disabled, see
  Step 3)
- Test: `agent/tests/test_hook_watch_default.py`

**Interfaces:**
- Produces: `station.session_key(session_id: str) -> str` (16 hex digits); Task 2 uses it.

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_hook_watch_default.py
"""Watch by default (docs/superpowers/specs/2026-10-14-watch-default-design.md, W1-W6, requirements 1-9)."""
import json

from superyak_agent import hook
from superyak_agent.station import ON_WATCH_LINE, session_key, write_private

DAY = 86400


def setup(station, ship_config, tmp_path):
    fake, andy, jenn, serenity = station
    config = tmp_path / 'home' / 'station.json'
    write_private(config, ship_config)
    return fake, serenity, config, tmp_path / 'home' / 'sessions'


def prompt(fake, config, sessions, now, mode='write', messages=True, sid='cc-1', transport=None):
    return hook.run(config, transport=transport or fake, event='prompt', session_id=sid, sessions_dir=sessions,
                    messages=messages, mode=mode, clock=lambda: now)


def declared(fake):
    return [r['body'] for r in fake.requests if r['method'] == 'POST' and r['path'] == '/api/ships/me/watch']


def choose(sessions, choice, sid='cc-1', seen=1000.0):
    sessions.mkdir(parents=True, exist_ok=True)
    write_private(sessions / f'{session_key(sid)}.watch', dict(choice, seen=seen))


def test_the_key_is_shared():
    assert session_key('cc-1') == hook._session_file('/s', 'cc-1').name[:16]
    assert len(session_key('\udcff odd')) == 16  # a lone surrogate encodes, as the hook's file name always did


def test_a_write_prompt_declares_once_then_again_after_a_gap(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    prompt(fake, config, sessions, 1000.0)
    assert declared(fake) == [{'minutes': 20, 'writable': True}]
    prompt(fake, config, sessions, 1000.0 + 19 * 60)
    assert len(declared(fake)) == 1  # within the lease: the prompt's own calls renew it
    prompt(fake, config, sessions, 1000.0 + 19 * 60 + 21 * 60)
    assert declared(fake)[-1] == {'minutes': 20, 'writable': True} and len(declared(fake)) == 2


def test_no_declaration_in_plan_mode_with_messages_off_or_without_a_session(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    prompt(fake, config, sessions, 1000.0, mode='plan')
    prompt(fake, config, sessions, 1000.0, messages=False)
    hook.run(config, transport=fake, event='prompt', session_id=None, sessions_dir=sessions, messages=True,
             mode='write', clock=lambda: 1000.0)
    prompt(fake, config, sessions, 1000.0, mode=None)
    assert declared(fake) == []


def test_no_declaration_inside_a_watcher_run(station, ship_config, tmp_path, monkeypatch):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    monkeypatch.setenv('SUPERYAK_RUN', '1')
    prompt(fake, config, sessions, 1000.0)
    assert declared(fake) == []


def test_an_opt_out_sticks(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    choose(sessions, {'choice': 'off'})
    for n in range(3):
        prompt(fake, config, sessions, 1000.0 + n * 3600)
    assert declared(fake) == []


def test_the_sessions_own_choice_sets_minutes_and_writable(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    choose(sessions, {'choice': 45, 'writable': False})
    prompt(fake, config, sessions, 1000.0)
    assert declared(fake) == [{'minutes': 45, 'writable': False}]
    prompt(fake, config, sessions, 1000.0 + 44 * 60)
    assert len(declared(fake)) == 1  # its own lease decides the gap


def test_plan_mode_lets_go_of_a_default_once_and_write_mode_takes_it_again(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    prompt(fake, config, sessions, 1000.0)
    prompt(fake, config, sessions, 1060.0, mode='plan')
    prompt(fake, config, sessions, 1120.0, mode='plan')
    prompt(fake, config, sessions, 1180.0)
    assert declared(fake) == [{'minutes': 20, 'writable': True}, {'minutes': 0, 'writable': False},
                              {'minutes': 20, 'writable': True}]


def test_plan_mode_leaves_a_self_declared_watch_alone(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    choose(sessions, {'choice': 30, 'writable': True})
    prompt(fake, config, sessions, 1000.0)
    prompt(fake, config, sessions, 1060.0, mode='plan')
    assert declared(fake) == [{'minutes': 30, 'writable': True}]


def test_a_seen_in_the_future_declares(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    sessions.mkdir(parents=True)
    write_private(sessions / f'{session_key("cc-1")}.prompted', {'seen': 99999999.0, 'held': True})
    prompt(fake, config, sessions, 1000.0)
    assert len(declared(fake)) == 1


def test_damaged_files_count_as_absent(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    sessions.mkdir(parents=True)
    (sessions / f'{session_key("cc-1")}.watch').write_text('not json')
    (sessions / f'{session_key("cc-1")}.prompted').write_text('[1, 2]')
    prompt(fake, config, sessions, 1000.0)
    assert declared(fake) == [{'minutes': 20, 'writable': True}]


def test_a_refused_declaration_is_silent_and_retried(station, ship_config, tmp_path):
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)

    def refusing(method, url, headers, data):
        if method == 'POST' and url.endswith('/api/ships/me/watch'):
            fake.requests.append({'method': method, 'path': '/api/ships/me/watch', 'body': json.loads(data)})
            return 429, b'{"error": "A ship can have at most 10 sessions on watch; end one first"}'
        return fake(method, url, headers, data)
    first = prompt(fake, config, sessions, 1000.0, transport=refusing)
    assert len(declared(fake)) == 1 and 'watch' not in first.lower()
    prompt(fake, config, sessions, 1060.0)
    assert len(declared(fake)) == 2  # .prompted wasn't written, so the next prompt tries again


def test_the_output_is_the_same_with_or_without_the_declaration(station, ship_config, tmp_path, monkeypatch):
    """Requirement 5: with no mention to hand over, the output is byte-for-byte the same."""
    import copy
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    room = fake.room('Ops', fake.users['u-andy'], serenity)
    fake.say(room, fake.users['u-andy'], 'hello')
    twin = copy.deepcopy(fake)  # the same station, so the only difference is the feature
    with_default = prompt(fake, config, sessions, 1000.0)
    monkeypatch.setattr(hook, '_watch_default', lambda *a, **k: None)
    without = prompt(twin, config, tmp_path / 'other-sessions', 1000.0)
    assert with_default == without and 'hello' in without
    assert len(declared(fake)) == 1 and declared(twin) == []


def test_the_stations_on_watch_line_tells_the_session_at_once(station, ship_config, tmp_path):
    """W5 and requirement 5: the declaration runs before the inbox, so the same prompt's messages come with the
    station's own on-watch line when a mention is there to hand over. The hook adds no text of its own."""
    fake, serenity, config, sessions = setup(station, ship_config, tmp_path)
    room = fake.room('Ops', fake.users['u-andy'], serenity)
    fake.say(room, fake.users['u-andy'], '@serenity a question')
    shown = prompt(fake, config, sessions, 1000.0)
    assert ON_WATCH_LINE in shown and len(declared(fake)) == 1


def test_prune_keeps_the_current_sessions_files_and_drops_old_ones(tmp_path):
    folder = tmp_path / 'sessions'
    folder.mkdir()
    now = 100 * DAY
    current, old, fresh_off = session_key('cc-now'), session_key('cc-old'), session_key('cc-off')
    for name, seen in [(f'{current}.json', 1.0), (f'{current}.watch', 1.0), (f'{current}.prompted', 1.0),
                       (f'{old}.watch', now - 15 * DAY), (f'{old}.prompted', now - 15 * DAY),
                       (f'{fresh_off}.watch', now - DAY)]:
        write_private(folder / name, {'seen': seen, 'choice': 'off'} if name.endswith('.watch') else {'seen': seen})
    hook._prune(folder, folder / f'{current}.json', now)
    assert sorted(p.name for p in folder.iterdir()) == sorted([f'{current}.json', f'{current}.watch',
                                                              f'{current}.prompted', f'{fresh_off}.watch'])
```

Before Step 2, check two fixture details and adjust only the test's setup if needed:
- the station fixture's person `andy` key in `fake.users` (`u-andy`, as conftest's `user()` makes ids `u-<username>`);
- that `hook.run(..., mode=...)` accepts `mode=None`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_hook_watch_default.py`
Expected: an ImportError at collection (`cannot import name 'session_key'`).

- [ ] **Step 3: Write the code**

In `agent/superyak_agent/station.py`, add `import hashlib` to the imports, and after `presence_headers`:

```python
def session_key(session_id):
    """The 16 hex digits naming a Claude Code session's files in the ship's sessions folder: the hook's state and
    `.prompted`, and the MCP tool's `.watch` (watch by default, W3). One function, so both sides name the same file."""
    return hashlib.sha256(session_id.encode('utf-8', 'surrogatepass')).hexdigest()[:16]
```

In `agent/superyak_agent/hook.py`:
- add `session_key` to the names imported from `.station`, and remove `import hashlib`, which `_session_file` no longer
  uses;
- replace `STATE_NAME = re.compile(r'[0-9a-f]{16}\.json')` with
  `STATE_NAME = re.compile(r'[0-9a-f]{16}\.(?:json|watch|prompted)')`;
- add the constant `WATCH_DEFAULT_MINUTES = 20  # the station's default lease (presence.py)`;
- replace `_session_file`'s body with `return Path(sessions_dir) / (session_key(session_id) + '.json')`.

Replace `_prune` with:

```python
def _prune(sessions_dir, keep, now):
    """Session files (state `.json`, `.watch`, `.prompted`) whose `seen` is more than STATE_DAYS old, or missing or not
    a number, are deleted. The current session's files (`keep`'s key) are never touched."""
    keep_key = Path(keep).name[:16] if keep else None
    for path in Path(sessions_dir).iterdir():
        if not STATE_NAME.fullmatch(path.name) or path.name[:16] == keep_key:
            continue
        try:
            seen = read_json(path).get('seen')
            if not (type(seen) in (int, float) and math.isfinite(seen)) or seen < now - STATE_DAYS * 86400:
                path.unlink()
        except Exception:  # noqa: BLE001 - damaged: delete it
            try:
                path.unlink()
            except OSError:
                pass
```

Add, after `_fetch_instructions`:

```python
def _watch_client(config_path, transport, presence):
    config = read_json(config_path)
    if not config or not config.get('key'):
        return None  # as _fetch_instructions: no config, no call
    return StationClient(config['station'], config['key'], config.get('origin'), transport, presence)


def _read_object(path):
    try:
        value = read_json(path)
    except Exception:  # noqa: BLE001 - damaged counts as absent
        return {}
    return value if isinstance(value, dict) else {}


def _watch_default(config_path, session_id, mode, transport, sessions_dir, clock, presence):
    """Watch by default (spec 2026-10-14-watch-default-design.md, W1-W4). A write-mode prompt holds the watch: declared
    at the first prompt and again after a gap longer than its lease. A plan-mode prompt lets go of a default the hook
    holds. The session's own choice (`.watch`, written by station_watch) always wins. Prints nothing; the caller makes
    any failure silent, and `.prompted` is written only after the station answered."""
    client = _watch_client(config_path, transport, presence)
    if client is None:
        return
    folder = Path(sessions_dir or Path(config_path).parent / 'sessions')
    key = session_key(session_id)
    choice = _read_object(folder / f'{key}.watch')
    if choice.get('choice') == 'off':
        return
    own = choice.get('choice') if type(choice.get('choice')) is int and 1 <= choice['choice'] <= 120 else None
    prompted_path = folder / f'{key}.prompted'
    prompted = _read_object(prompted_path)
    now, seen = clock(), prompted.get('seen')
    held = prompted.get('held') is True
    if mode == 'plan':
        if held and own is None:
            client.watch(0)
            write_private(prompted_path, {'seen': now, 'held': False})
        return
    minutes = own or WATCH_DEFAULT_MINUTES
    writable = choice['writable'] if own is not None and type(choice.get('writable')) is bool else True
    fresh = held and type(seen) in (int, float) and math.isfinite(seen) and 0 <= now - seen <= minutes * 60
    if not fresh:
        client.watch(minutes, writable)
    write_private(prompted_path, {'seen': now, 'held': True})
```

In `run()`, pass `mode` to `_run_all`: add `mode=mode` to the `_run_all(...)` call. In `_run_all`'s signature, add
`mode=None` as the last parameter. In `_run_all`, right after the `if wants:` block (the instructions fetch) and
before `if event != 'session-start' and messages and not late():`, add:

```python
    if event == 'prompt' and session_id and messages and mode in ('write', 'plan') and not late():
        try:  # watch by default (W1-W4): after the instructions, before the inbox, whose advance stays last (R4)
            _watch_default(config_path, session_id, mode, link(INBOX_CALL_TIMEOUT), sessions_dir, clock, presence)
        except Exception:  # noqa: BLE001 - W4: silent; .prompted unwritten, so the next prompt tries again
            pass
```

In `agent/tests/test_presence_client.py`, `test_the_headers_change_nothing_else` compares a run with presence headers
to one without. The default watch needs the session header (the station refuses a watch without one), so with headers
the declaration succeeds and the station's on-watch line joins the messages (W5). Keep that test about every other
call: in its `session()` helper, before `hook.run(...)`, add
`monkeypatch.setattr(hook, '_watch_default', lambda *args, **kwargs: None)  # the default needs the session header`.

- [ ] **Step 4: Run the tests, then the agent suite**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_hook_watch_default.py`
Expected: all pass.
Run: `make check-agent`. Expected: every test passes (main's count plus this task's; `test_watch_choice.py` is
Task 2's and doesn't exist yet). Name any failure, especially in
test_hook.py, test_hook_inbox.py and test_status_tools.py, which exercise `run()` and the prompt path.

- [ ] **Step 5: Mutation checks** (temporarily, then restore; report each)

- delete the `mode == 'plan'` branch's ending call: `test_plan_mode_lets_go...` fails;
- remove the `choice.get('choice') == 'off'` return: `test_an_opt_out_sticks` fails;
- set `fresh = False` always: `test_a_write_prompt_declares_once_then_again_after_a_gap` fails;
- delete the whole `if mode == 'plan':` branch, so a plan-mode prompt declares: `test_no_declaration_in_plan_mode...` and
  `test_plan_mode_lets_go...` fail.

Confirm with `git diff --stat` that hook.py is restored.

- [ ] **Step 6: Commit**

```bash
git add agent/superyak_agent/station.py agent/superyak_agent/hook.py agent/tests/test_hook_watch_default.py agent/tests/test_presence_client.py
git commit -m "Watch by default, hook: write-mode sessions hold the watch with a short lease; plan mode lets go (W1-W4)"
```

---

### Task 2: The MCP tool records the session's own choice; the docs

**Files:**
- Modify: `agent/superyak_agent/mcp.py`: `Tools.__init__` gains `sessions_dir=None`; `station_watch` records the
  choice; `serve` passes the sessions folder
- Modify: `agent/README.md` ("Taking the watch"), `HANDOFF.md` (the start-of-session watch line)
- Test: `agent/tests/test_watch_choice.py`

**Interfaces:**
- Consumes: `station.session_key` (Task 1).
- Produces: `<sessions>/<session_key(CLAUDE_CODE_SESSION_ID)>.watch`, `{"choice": "off" | <int>, "writable": <bool>,
  "seen": <time>}`. Task 1's hook reads it.

- [ ] **Step 1: Write the failing tests**

```python
# agent/tests/test_watch_choice.py
"""Watch by default W3: station_watch records this session's own choice for the hook (requirements 4 and 9)."""
from superyak_agent import mcp
from superyak_agent.mcp import Tools, handle
from superyak_agent.station import StationClient, read_json, session_key, write_private


def tools_for(fake, sessions):
    return Tools(StationClient('http://station.test', 'serenity-key', transport=fake), sessions_dir=sessions)


def call(tools, name, **arguments):
    result = handle(tools, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})['result']
    return result['content'][0]['text'], result['isError']


def test_station_watch_records_the_sessions_choice(station, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    sessions = tmp_path / 'sessions'
    tools = tools_for(fake, sessions)
    path = sessions / f'{session_key("cc-1")}.watch'
    assert not call(tools, 'station_watch', minutes=45, writable=False)[1]
    got = read_json(path)
    assert got['choice'] == 45 and got['writable'] is False and isinstance(got['seen'], float)
    assert not call(tools, 'station_watch', minutes=0)[1]
    assert read_json(path)['choice'] == 'off'


def test_a_call_naming_another_cursor_records_nothing(station, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    sessions = tmp_path / 'sessions'
    tools = tools_for(fake, sessions)
    assert not call(tools, 'station_watch', minutes=0, cursor='other-name')[1]
    assert not sessions.exists() or list(sessions.iterdir()) == []


def test_without_a_sessions_folder_nothing_is_written(station, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    tools = Tools(StationClient('http://station.test', 'serenity-key', transport=fake))
    assert not call(tools, 'station_watch', minutes=0)[1]
    assert list(tmp_path.iterdir()) == []


def test_a_refused_call_records_nothing(station, tmp_path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CODE_SESSION_ID', 'cc-1')
    fake, andy, jenn, serenity = station
    sessions = tmp_path / 'sessions'

    def refusing(method, url, headers, data):
        if method == 'POST' and url.endswith('/api/ships/me/watch'):
            return 400, b'{"error": "minutes is a whole number from 0 to 120"}'
        return fake(method, url, headers, data)
    tools = Tools(StationClient('http://station.test', 'serenity-key', transport=refusing), sessions_dir=sessions)
    assert call(tools, 'station_watch', minutes=0)[1]
    assert not sessions.exists() or list(sessions.iterdir()) == []


def test_the_tool_says_minutes_zero_turns_the_default_off():
    [tool] = [t for t in mcp.TOOLS if t[0] == 'station_watch']
    assert 'turns that default off for the rest of this session' in tool[1]


def test_serve_gives_the_tools_the_ships_sessions_folder(ship_config, tmp_path, monkeypatch):
    config = tmp_path / 'home' / 'station.json'
    write_private(config, ship_config)
    seen = {}
    monkeypatch.setattr(mcp, 'serve_with', lambda tools, *streams: seen.setdefault('tools', tools))
    mcp.serve(config)
    assert seen['tools'].sessions_dir == tmp_path / 'home' / 'sessions'
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_watch_choice.py`
Expected: a TypeError (`Tools()` got an unexpected keyword `sessions_dir`) in most tests.

- [ ] **Step 3: Write the code**

In `agent/superyak_agent/mcp.py`:
- import `time`;
- add `session_key` and `write_private` to the names imported from `.station`, if not present;
- `Tools.__init__(self, client, quick_client=None, guard=None, sessions_dir=None)` stores
  `self.sessions_dir = sessions_dir`.

In `station_watch`, right after `got = self.client.watch(...)` (so a refused call records nothing), add
`self._record_choice(minutes, args.get('writable', False))`, and add the method:

```python
    def _record_choice(self, minutes, writable):
        """Watch by default W3: this session's own choice, for the prompt hook to honour. Written only for this Claude
        Code session's own watch: the cursor absent or its own id, never another cursor's."""
        session = os.environ.get('CLAUDE_CODE_SESSION_ID')
        if not self.sessions_dir or not session or (self.named and self.named != session):
            return
        choice = {'choice': 'off'} if minutes == 0 else {'choice': minutes, 'writable': bool(writable)}
        try:
            write_private(Path(self.sessions_dir) / f'{session_key(session)}.watch', dict(choice, seen=time.time()))
        except OSError:
            pass  # the station holds the watch either way; the default only reads this
```

In `serve`, pass `sessions_dir=Path(config_path).parent / 'sessions'` to `Tools(...)`.

In the tool list (mcp.py:386-387), the agent reads `station_watch`'s description before calling it, so it must say
what `minutes=0` now does:
- change "Put this session on watch for your ship's mentions, renewed at each prompt; minutes=0 ends it." to "Put this
  session on watch for your ship's mentions, renewed at each prompt. The prompt hook takes the watch by default for a
  write-mode session that shows room messages; minutes=0 ends it and turns that default off for the rest of this
  session.";
- change the `minutes` parameter's description "How long each renewal lasts, 1-120 (default 20); 0 ends the watch" to
  "How long each renewal lasts, 1-120 (default 20); 0 ends the watch and turns the hook's default off for this
  session". The dict uses single-quoted literals, so write the apostrophe as `hook\'s`.

Docs:
- In `agent/README.md`'s "Taking the watch":
  - Replace the opening sentence ("A Claude Code session that will work, loop or run long declares itself with
    `station_watch writable=true` (`minutes` 1-120, default 20).") with "By default the prompt hook takes the watch
    for a Claude Code session that shows room messages and is in write mode, with a 20-minute lease. It declares
    again after an idle gap and lets go at a plan-mode prompt. A session sets its own lease with `station_watch
    writable=true` (`minutes` 1-120), or ends the watch with `minutes=0`, which also turns the default off for the rest
    of the session."
  - Delete the paragraph's last two sentences, "Declaring the watch is the session's own choice today; whether the hook
    should declare it ... (roadmap 2.1)."
- In `HANDOFF.md`'s start-of-session list, the item that begins "If the session will work, loop or run long, take the
  watch" (it wraps across two lines): change its meaning to "The hook takes the watch for you (write mode, room
  messages on). `station_watch` sets your own lease, and `minutes=0` opts out." Keep the rest of the item: the
  mentions handed to you carry no authority, and you answer with `reply_to`.

- [ ] **Step 4: Run the tests, then the agent suite**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_watch_choice.py tests/test_status_tools.py`
Expected: all pass.
Run: `make check-agent`. Expected: every test passes. Name any failure.

- [ ] **Step 5: Mutation check:** remove the `self.named != session` clause: `test_a_call_naming_another_cursor...`
  fails. Restore it.

- [ ] **Step 6: Commit**

```bash
git add agent/superyak_agent/mcp.py agent/tests/test_watch_choice.py agent/README.md HANDOFF.md
git commit -m "Watch by default, MCP: station_watch records the session's own choice; docs (W3)"
```

---

## Deploy (Rio Grande, after the merge under law section 2)

Agent-only: no station restart and no backup needed. The version check prompts ships to update, because
`agent/superyak_agent` is a runtime path.
1. Merge with `--no-ff`, push, and run the usual guard (on main, HEAD equal to origin/main).
2. Restart `superyak-ship` (the watcher imports agent code) and Odo, when no run is in flight.
3. **Live check on the Pi:** start a new Claude Code session in write mode, with room messages on. After its first
   prompt, `station_ships` shows its session on watch, writable. In plan mode, after one prompt, it's off. Back in
   write mode, it's on again.
4. Announce it in the room. Ask Andy to activate the one-line law amendment, drafted with
   `station_draft_instructions` (spec, Deploy).

## Self-review notes

- **Spec coverage:**
  - W1 and requirement 3: the caller's guard in `_run_all` plus `run()`'s early returns.
  - W2 and requirements 1, 2 and 8: `_watch_default` and its tests.
  - W3 and requirements 4 and 9: Task 2.
  - W4 and requirement 5: the caller's try and the output test.
  - W5: no hook text.
  - W6: unchanged.
  - Requirement 6: `_prune`.
  - Requirement 7: no station files.
- **Dry run:** every block was run as written in a scratch worktree at the plan's base, with both tasks applied.
  - The new tests give 14 + 6 = 20 passed.
  - All four mutation checks fail their named tests: the plan-mode ending, the opt-out read, `fresh` always false, and
    the cursor check.
  - `make check-agent` gives 651 passed.
  - It surfaced three things, all fixed here:
    - the output-equality test needed a deep-copied twin station, because the fake's unread isn't independent per
      session;
    - the serve test's monkeypatch needed `serve_with`'s three arguments;
    - ship-status R2's guard test (test_presence_client.py) needed the default disabled, because the declaration needs
      the session header, and with it the station's on-watch line appears (W5). That also showed requirement 5 had
      to name W5's line; the spec text is clarified to match.

## Review map (revision 2: the review of 5570319)

| # | Finding | Change |
|---|---|---|
| S1 | `station_watch`'s description didn't say `minutes=0` turns the default off | Task 2 changes the tool and `minutes` descriptions; `test_the_tool_says_minutes_zero_turns_the_default_off` |
| S2 | requirement 5's change needed a D8 look | approved by the spec's D8 reviewer (room message ed700b54) |
| S3 | the README's opening sentence was stale | Task 2 rewrites it, default first |
| S4 | the fifth spec mutation was missing | Task 1 Step 5 adds "the whole plan-mode branch deleted" |
| N5 | `import hashlib` dead in hook.py | Task 1 removes it |
| N6 | `read_json` unused in mcp.py | dropped from Task 2's import |
| N7 | the HANDOFF target wraps | described by meaning |
| N8 | "19 + 5" | "14 + 5 = 19" |
| N9 | `_watch_client` unguarded | returns None without a config or key, as `_fetch_instructions` does |
