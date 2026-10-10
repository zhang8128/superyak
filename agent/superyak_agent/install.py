"""Register the station tools, the optional hook and the watcher service on this machine."""
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from .station import StationError, client_for, read_json, write_private

AGENT_DIR = Path(__file__).resolve().parents[1]
RUN_AGENT = AGENT_DIR / 'run_agent.py'
ADNA_REPO = 'https://github.com/aDNA-Network/aDNA.aDNA'
UNIT = 'superyak-ship.service'
LABEL = 'com.superyak.ship'


def systemd_quote(arg):
    return '"' + str(arg).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def systemd_unit(argv, path_env):
    return '\n'.join([
        '[Unit]', 'Description=Superyak ship watcher (answers station mentions)', 'After=network-online.target', '',
        '[Service]', f'Environment={systemd_quote("PATH=" + path_env)}', 'ExecStart=' + ' '.join(systemd_quote(a) for a in argv),
        'Restart=always', 'RestartSec=10', 'MemoryMax=3G', 'MemorySwapMax=0', '',
        '[Install]', 'WantedBy=default.target', ''])


def launchd_plist(argv, path_env, log_path, label=LABEL):
    return plistlib.dumps({'Label': label, 'ProgramArguments': [str(a) for a in argv], 'EnvironmentVariables': {'PATH': path_env},
                           'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
                           'StandardOutPath': str(log_path), 'StandardErrorPath': str(log_path)})


def run_mcp_config(config_path, adna_dist=None):
    """MCP servers for the watcher's Claude runs. Station tools are deliberately absent: a run
    answers a mention from its prompt and never acts on the station itself. `config_path` is
    kept so callers need not change if that ever does."""
    servers = {}
    if adna_dist:
        servers['adna'] = {'command': shutil.which('node') or 'node', 'args': [str(adna_dist)]}
    return {'mcpServers': servers}


def _write_settings(settings_path, settings):
    """Replace the file whole, through a temporary file beside it, keeping its mode: it can hold `env` secrets.
    A new file is 0600."""
    try:
        mode = settings_path.stat().st_mode & 0o7777
    except FileNotFoundError:
        mode = 0o600
    fd, tmp = tempfile.mkstemp(dir=settings_path.parent, prefix='.' + settings_path.name + '.', suffix='.tmp')
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(settings, indent=2) + '\n')
        os.replace(tmp, settings_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def is_station_hook(command, wanted=None):
    """The hook this agent installs, whichever interpreter it was installed with: the same command, or any
    command in which this checkout's run_agent.py is one word and the next word is `hook`."""
    if wanted is not None and command == wanted:
        return True
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    return any(word == str(RUN_AGENT) and following == 'hook' for word, following in zip(words, words[1:]))


ENV_RUN = 'SUPERYAK_RUN=${SUPERYAK_RUN:-hook}'  # unquoted on purpose: the shell expands it
GUARD = ' || true'  # python exits 2 when run_agent.py is gone, and a prompt hook's exit 2 blocks and erases the prompt
HOOK_EVENTS = ('SessionStart', 'UserPromptSubmit', 'SessionEnd')


def _hook_words(command):
    try:
        return shlex.split(command or '')
    except ValueError:
        return (command or '').split()


def _hook_commands(config_path, messages):
    """Every command ends with GUARD, so a missing or broken checkout exits 0 and prints nothing. SessionEnd ends this
    session's watch (ship status spec S4) whether or not messages are on."""
    base = hook_command(config_path)
    return {'SessionStart': f'{ENV_RUN} SUPERYAK_HOOK_EVENT=session-start {base}{GUARD}',
            'UserPromptSubmit': f'{base}{GUARD}' if messages else f'{ENV_RUN} SUPERYAK_HOOK_MESSAGES=0 {base}{GUARD}',
            'SessionEnd': f'{ENV_RUN} SUPERYAK_HOOK_EVENT=session-end {base}{GUARD}'}


def _same_hook(command, wanted):
    """Whether an installed station hook is the wanted one in kind, whichever interpreter it was installed with.
    A command without the guard is a different hook, so docking again upgrades it."""
    def kind(c):
        words = _hook_words(c)
        return ('SUPERYAK_HOOK_EVENT=session-start' in words, 'SUPERYAK_HOOK_EVENT=session-end' in words,
                'SUPERYAK_HOOK_MESSAGES=0' in words, words[-2:] == ['||', 'true'])
    return command == wanted or kind(command) == kind(wanted)


def install_hooks(settings_path, config_path, messages, backup=None):
    """Install the station's SessionStart (instructions) and UserPromptSubmit hooks. Returns the list of what
    changed: 'SessionStart', 'UserPromptSubmit' and, when a messages-on prompt hook was replaced, 'messages-off'.
    The first time it changes an existing file it copies it to `backup` (default: beside it; a project ship's goes to
    its home, never into the repository, R6)."""
    settings_path = Path(settings_path)
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    changes = []
    for event, wanted in _hook_commands(config_path, messages).items():
        entries = settings.setdefault('hooks', {}).setdefault(event, [])
        ours = [h.get('command') for entry in entries for h in entry.get('hooks', []) if is_station_hook(h.get('command'), wanted)]
        if len(ours) == 1 and _same_hook(ours[0], wanted):
            continue
        if event == 'UserPromptSubmit' and not messages and any('SUPERYAK_HOOK_MESSAGES=0' not in _hook_words(c) for c in ours):
            changes.append('messages-off')
        kept = []
        for entry in entries:
            hooks = [h for h in entry.get('hooks', []) if not is_station_hook(h.get('command'), wanted)]
            if hooks:
                kept.append({**entry, 'hooks': hooks} if len(hooks) != len(entry.get('hooks', [])) else entry)
        kept.append({'hooks': [{'type': 'command', 'command': wanted, 'timeout': 10}]})
        settings['hooks'][event] = kept
        changes.append(event)
    if changes:
        backup = Path(backup) if backup is not None else settings_path.with_name(settings_path.name + '.bak-superyak')
        if settings_path.exists() and not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(settings_path, backup)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        _write_settings(settings_path, settings)
    return changes


def remove_hooks(settings_path):
    """Remove the station's hooks and nothing else. Whatever it cannot read (an event that is not a list, an entry
    or a hook that is not an object) it leaves as it is; an event it empties goes."""
    settings_path = Path(settings_path)
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    events = settings.get('hooks') if isinstance(settings, dict) else None
    if not isinstance(events, dict):
        return False
    changed = False
    for event in HOOK_EVENTS:
        entries = events.get(event)
        if not isinstance(entries, list):
            continue
        kept, removed = [], False
        for entry in entries:
            hooks = entry.get('hooks') if isinstance(entry, dict) else None
            if not isinstance(hooks, list):
                kept.append(entry)
                continue
            mine = [h for h in hooks if not (isinstance(h, dict) and is_station_hook(h.get('command')))]
            if len(mine) == len(hooks):
                kept.append(entry)
                continue
            removed = True
            if mine:  # keep the person's own hooks that shared the entry
                kept.append({**entry, 'hooks': mine})
        if removed:
            changed = True
            if kept:
                events[event] = kept
            else:
                del events[event]
    if changed:
        _write_settings(settings_path, settings)
    return changed


def register_codex(config_path, name, argv):
    config_path = Path(config_path)
    text = config_path.read_text() if config_path.exists() else ''
    header = f'[mcp_servers.{name}]'
    if header in text:
        return False
    block = f'{header}\ncommand = {json.dumps(str(argv[0]))}\nargs = {json.dumps([str(a) for a in argv[1:]])}\n'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text.rstrip('\n') + '\n\n' + block if text else block)
    return True


TOML_TABLE = re.compile(r'^\s*\[\[?([^\[\]]+)\]\]?\s*(?:#.*)?$')


def remove_codex(config_path, name):
    """Remove the `[mcp_servers.<name>]` table, and any sub-tables of it, from Codex's config; leave the rest."""
    config_path = Path(config_path)
    if not config_path.exists():
        return False
    header = f'mcp_servers.{name}'
    kept, skipping, removed, gap = [], False, False, False
    for line in config_path.read_text().splitlines(keepends=True):
        match = TOML_TABLE.match(line)
        if match:
            table = re.sub(r'\s*\.\s*', '.', match.group(1).strip()).replace('"', '').replace("'", '')
            was_skipping, skipping = skipping, table == header or table.startswith(header + '.')
            if skipping and not was_skipping:
                removed = True
                while kept and not kept[-1].strip():  # the blank line that set the table apart goes with it
                    kept.pop()
                gap = bool(kept)
        if skipping:
            continue
        if gap:
            kept.append('\n')
            gap = False
        kept.append(line)
    if not removed:
        return False
    text = ''.join(kept)
    config_path.write_text(text if not text or text.endswith('\n') else text + '\n')
    return True


def register_claude(name, argv, out, cwd=None):
    """User-scope tools. `claude mcp get` answers for its working directory, so the machine ship's calls run in
    ~/.superyak, outside every claimed project, where a local station would hide the user one (R7)."""
    cwd = str(cwd) if cwd is not None else None
    try:
        if subprocess.run(['claude', 'mcp', 'get', name], capture_output=True, cwd=cwd).returncode == 0:
            return
        subprocess.run(['claude', 'mcp', 'add', '--scope', 'user', name, '--', *[str(a) for a in argv]], check=True,
                       capture_output=True, cwd=cwd)
    except (subprocess.SubprocessError, OSError) as error:
        out(f'Could not register the {name} tools with Claude Code ({_reason(error)}). Run make dock again to retry.')
        return
    out(f'Registered the {name} tools with Claude Code.')


def _reason(error):
    if isinstance(error, subprocess.CalledProcessError):
        command = [str(part) for part in error.cmd] if isinstance(error.cmd, (list, tuple)) else [str(error.cmd)]
        shown = command[1:3] if command[1:2] == ['run'] else command[1:2]
        return f'{" ".join([Path(command[0]).name, *shown])} failed with exit status {error.returncode}'
    return str(error) or type(error).__name__


def setup_adna(out, root=None):
    """The optional aDNA tools. Never raises: a missing tool, a failed clone or build, or an odd Node.js
    version skips them with a note, so the required installation steps are never held up by them."""
    try:
        return _setup_adna(Path(root or Path.home() / 'aDNA' / 'aDNA.aDNA'))
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        reason = 'could not read the Node.js version' if isinstance(error, ValueError) else _reason(error)
        out(f'aDNA tools skipped: {reason}. Run make dock again to retry, or add --no-adna.')
        return None


def _setup_adna(root):
    node, npm, git = shutil.which('node'), shutil.which('npm'), shutil.which('git')
    version = subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip().lstrip('v') if node else ''
    if not (node and npm and git) or int(version.split('.')[0] or 0) < 20:
        raise OSError('they need Node.js 20 or newer, npm and git')
    dist = root / 'mcp' / 'dist' / 'index.js'
    if not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([git, 'clone', '--depth', '1', ADNA_REPO, str(root)], check=True)
    if not dist.exists():
        subprocess.run([npm, 'ci', '--ignore-scripts'], cwd=root / 'mcp', check=True)
        subprocess.run([npm, 'run', 'build'], cwd=root / 'mcp', check=True)
    if not dist.exists():
        raise OSError('the build did not produce mcp/dist/index.js')
    return dist


def service_names(home):
    """S4: (launchd label, systemd unit, log) of the ship whose home this is. The machine ship's are today's; a project
    ship's come from its name, so two ships' watchers never share a label, a unit or a log."""
    from .claims import kind_of
    home = Path(home)
    if kind_of(home) == 'project':
        return f'{LABEL}.{home.name}', f'superyak-ship-{home.name}.service', home / 'ship.log'
    return LABEL, UNIT, Path.home() / '.superyak' / 'ship.log'


def install_service(argv, out, system=None, names=None):
    system = system or platform.system()
    label, unit_name, log = names or (LABEL, UNIT, Path.home() / '.superyak' / 'ship.log')
    path_env = os.environ.get('PATH', '/usr/bin:/bin')
    if system == 'Linux':
        unit = Path.home() / '.config' / 'systemd' / 'user' / unit_name
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(systemd_unit(argv, path_env))
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', '--user', 'enable', unit_name], check=True, capture_output=True)
        subprocess.run(['systemctl', '--user', 'restart', unit_name], check=True)
        if subprocess.run(['loginctl', 'enable-linger'], capture_output=True).returncode:
            out('Could not enable linger; the watcher runs only while you are logged in.')
    elif system == 'Darwin':
        plist = Path.home() / 'Library' / 'LaunchAgents' / f'{label}.plist'
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(launchd_plist(argv, path_env, log, label=label))
        domain = f'gui/{os.getuid()}'
        subprocess.run(['launchctl', 'bootout', f'{domain}/{label}'], capture_output=True)
        subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
    else:
        out(f'Start the watcher yourself: {shlex.join(str(a) for a in argv)}')
        return
    out('The watcher is running; it answers mentions within about 30 seconds.')


def remove_service(names, system=None):
    """Stop and remove one ship's watcher service, by its names (S4), and nothing else."""
    label, unit_name, _ = names
    system = system or platform.system()
    if system == 'Linux':
        subprocess.run(['systemctl', '--user', 'disable', '--now', unit_name], capture_output=True)
        (Path.home() / '.config' / 'systemd' / 'user' / unit_name).unlink(missing_ok=True)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], capture_output=True)
    elif system == 'Darwin':
        subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], capture_output=True)
        (Path.home() / 'Library' / 'LaunchAgents' / f'{label}.plist').unlink(missing_ok=True)


def hook_command(config_path):
    return shlex.join([sys.executable, str(RUN_AGENT), 'hook', '--config', str(config_path)])


def start_at_newest_mention(config_path, state_path, client, out):
    """R22: a ship whose watcher state has no mention cursor would answer every mention since docking (the cursor
    starts at 0), so the first service install reads the mentions to the end and stores the newest. A ship that has a
    cursor is left alone. True when the watcher may be installed."""
    try:
        state = read_json(state_path, {}) or {}
        if not isinstance(state, dict):
            raise ValueError('ship-state.json is not an object')
        if 'mention_seq' in state:
            return True
        client = client or client_for(read_json(config_path))
        newest = 0
        while True:
            rows = client.mentions(newest)
            seqs = [int(row['seq']) for row in rows or []]
            if not seqs or max(seqs) <= newest:
                break
            newest = max(seqs)
    except (StationError, OSError, ValueError, KeyError, TypeError) as error:
        out(f"Could not read this ship's mentions on the station ({_reason(error)}), so the watcher was not installed: "
            'it would have answered every mention since docking. Run make dock again.')
        return False
    write_private(state_path, {**state, 'mention_seq': newest})
    out(f"The watcher starts after mention {newest}; earlier mentions won't be answered.")
    return True


def install_all(config_path, *, hook=False, adna=True, service=True, out=print, client=None):
    """The required steps come first so that nothing optional can hold them up: the watcher's tool config
    (without aDNA), the station tools for Claude Code and Codex, the hook, the watcher service. Then the
    optional aDNA tools; if they install, the watcher's tool config is rewritten to include them (each run
    reads the file afresh) and they are registered with Claude Code."""
    config_path = Path(config_path)
    home, mcp_argv = config_path.parent, [sys.executable, str(RUN_AGENT), 'mcp', '--config', str(config_path)]
    write_private(home / 'run-mcp.json', run_mcp_config(config_path))
    if shutil.which('claude'):
        register_claude('station', mcp_argv, out, cwd=home)
    else:
        out('Claude Code not found; skipped registering the station tools for it.')
    codex = Path.home() / '.codex' / 'config.toml'
    if (shutil.which('codex') or codex.exists()) and register_codex(codex, 'station', mcp_argv):
        out('Registered the station tools with Codex.')
    try:
        changes = install_hooks(Path.home() / '.claude' / 'settings.json', config_path, messages=hook)
    except (OSError, ValueError, AttributeError, TypeError) as error:
        out(f'Could not install the Claude Code hooks in ~/.claude/settings.json ({_reason(error)}). Fix the file and run make dock again.')
    else:
        if changes and hook:
            out('Added the station hooks: instructions load in every session and new room messages appear at the start of each Claude Code turn.')
        elif 'messages-off' in changes:
            out('Room messages will no longer appear in Claude Code sessions (instructions still load).')
        elif changes:
            out('Added the station hooks: instructions load at the start of each Claude Code session.')
    if service and start_at_newest_mention(config_path, home / 'ship-state.json', client, out):
        install_service([sys.executable, str(RUN_AGENT), 'watch', '--config', str(config_path),
                         '--state', str(home / 'ship-state.json'), '--mcp-config', str(home / 'run-mcp.json')], out,
                        names=service_names(home))
    adna_dist = setup_adna(out) if adna else None
    if adna_dist:
        write_private(home / 'run-mcp.json', run_mcp_config(config_path, adna_dist))
        out('Added the aDNA tools to the watcher.')
        if shutil.which('claude'):
            register_claude('adna', [shutil.which('node'), adna_dist], out, cwd=home)


def uninstall_all(config_path, out=print):
    from .claims import kind_of
    config_path = Path(config_path)
    if kind_of(config_path.parent) == 'project':
        return uninstall_project(config_path.parent, out)
    config = read_json(config_path)
    revoked = None  # None: there was no key to revoke
    if config and config.get('key'):
        try:
            client_for(config).revoke_key()
            revoked = True
        except (StationError, OSError) as error:
            # A 401 means the station already refuses this key; anything else leaves it usable.
            revoked = isinstance(error, StationError) and error.status == 401
            if not revoked:
                out(f'Could not revoke the key on the station ({error}); ask an admin to revoke it under Connections → Ships.')
    if platform.system() == 'Linux':
        subprocess.run(['systemctl', '--user', 'disable', '--now', UNIT], capture_output=True)
        (Path.home() / '.config' / 'systemd' / 'user' / UNIT).unlink(missing_ok=True)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], capture_output=True)
    elif platform.system() == 'Darwin':
        subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)
        (Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist').unlink(missing_ok=True)
    if shutil.which('claude'):
        # from ~/.superyak, outside every claim (R7); from HOME when that folder is already gone (review 487c070b)
        cwd = config_path.parent if config_path.parent.is_dir() else Path.home()
        subprocess.run(['claude', 'mcp', 'remove', '--scope', 'user', 'station'], capture_output=True, cwd=str(cwd))
    remove_codex(Path.home() / '.codex' / 'config.toml', 'station')
    local = 'watcher stopped, station tools and hook removed'
    try:
        remove_hooks(Path.home() / '.claude' / 'settings.json')
    except (OSError, ValueError, AttributeError, TypeError) as error:
        # Undock goes on: station.json goes below, and a hook without it prints nothing.
        out(f'Could not remove the Claude Code hooks from ~/.claude/settings.json ({_reason(error)}). Fix the file and remove '
            'the entries that run run_agent.py hook.')
        local = 'watcher stopped and station tools removed; the hooks stay in ~/.claude/settings.json'
    for path in (config_path, config_path.parent / 'run-mcp.json'):
        path.unlink(missing_ok=True)
    if revoked is False:
        out(f'Undocked on this machine ({local}), but the key was NOT revoked on the station: ask an admin to revoke it.')
    else:
        out(f'Undocked: {"key revoked, " if revoked else ""}{local}.')


def _revoke(config, out):
    """None when there was no key, True when it's revoked (or the station already refuses it), False otherwise."""
    if not (config and config.get('key')):
        return None
    try:
        client_for(config).revoke_key()
        return True
    except (StationError, OSError) as error:
        if isinstance(error, StationError) and error.status == 401:
            return True
        out(f'Could not revoke the key on the station ({error}); ask an admin to revoke it under Connections → Ships.')
        return False


def uninstall_project(home, out=print):
    """S10, R21: a project ship's undock touches only its own: its key, its service, its local station (from its
    project root), its hooks in the project's settings.local.json, the station table of its Codex profile (the file
    only when then empty), its home's files, and last its claim, in one lock hold. It finds the project in
    <home>/claim.json, so it works with the registry unreadable and with no claim at all."""
    from . import claims
    home = Path(home)
    config = read_json(home / 'station.json') if (home / 'station.json').exists() else None
    claim = claims.read_json_quiet(home / 'claim.json')
    root = Path(claim['root']) if isinstance(claim, dict) and isinstance(claim.get('root'), str) else None
    revoked = _revoke(config, out)
    remove_service(service_names(home))
    notes = []
    if root is not None and root.is_dir():
        if shutil.which('claude'):
            subprocess.run(['claude', 'mcp', 'remove', '--scope', 'local', 'station'], capture_output=True, cwd=str(root))
        try:
            settings = root / '.claude' / 'settings.local.json'
            if settings.exists():
                remove_hooks(settings)
        except (OSError, ValueError, AttributeError, TypeError) as error:
            notes.append(f'its hooks stay in {root}/.claude/settings.local.json ({_reason(error)}); remove the entries '
                         'that run run_agent.py hook')
    elif root is not None:
        notes.append(f'its project {root} is gone, so its local station tools and hooks there were not touched')
    profile = Path.home() / '.codex' / f'{home.name}.config.toml'
    if remove_codex(profile, 'station') and not profile.read_text().strip():
        profile.unlink()
    for path in sorted(home.rglob('*'), reverse=True):
        if path.name == 'claim.json' and path.parent == home:
            continue
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()
    try:
        claims.unclaim(home)
    except claims.Unreadable as error:
        notes.append(f'{error}: its entry there stays until the file is fixed; its claim.json is gone')
    try:
        home.rmdir()
    except OSError:
        pass
    local = 'service, station tools, hooks, Codex profile and claim removed'
    tail = ''.join(f' Note: {note}.' for note in notes)
    if revoked is False:
        out(f'Undocked {home.name} on this machine ({local}), but the key was NOT revoked on the station: ask an admin '
            f'to revoke it.{tail}')
    else:
        out(f'Undocked {home.name}: {"key revoked, " if revoked else ""}{local}.{tail}')
