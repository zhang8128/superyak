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


def launchd_plist(argv, path_env, log_path):
    return plistlib.dumps({'Label': LABEL, 'ProgramArguments': [str(a) for a in argv], 'EnvironmentVariables': {'PATH': path_env},
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
    tmp = settings_path.with_name(settings_path.name + '.tmp')
    tmp.write_text(json.dumps(settings, indent=2) + '\n')
    os.replace(tmp, settings_path)


def is_station_hook(command, wanted=None):
    """The hook this agent installs, whichever interpreter it was installed with: the same command, or any
    command that runs this checkout's run_agent.py with the word `hook`."""
    command = command or ''
    if wanted is not None and command == wanted:
        return True
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    return str(RUN_AGENT) in command and 'hook' in words


ENV_RUN = 'SUPERYAK_RUN=${SUPERYAK_RUN:-hook}'  # unquoted on purpose: the shell expands it
HOOK_EVENTS = ('SessionStart', 'UserPromptSubmit')


def _hook_words(command):
    try:
        return shlex.split(command or '')
    except ValueError:
        return (command or '').split()


def _hook_commands(config_path, messages):
    base = hook_command(config_path)
    return {'SessionStart': f'{ENV_RUN} SUPERYAK_HOOK_EVENT=session-start {base}',
            'UserPromptSubmit': base if messages else f'{ENV_RUN} SUPERYAK_HOOK_MESSAGES=0 {base}'}


def _same_hook(command, wanted):
    """Whether an installed station hook is the wanted one in kind, whichever interpreter it was installed with."""
    def kind(c):
        words = _hook_words(c)
        return ('SUPERYAK_HOOK_EVENT=session-start' in words, 'SUPERYAK_HOOK_MESSAGES=0' in words)
    return command == wanted or kind(command) == kind(wanted)


def install_hooks(settings_path, config_path, messages):
    """Install the station's SessionStart (instructions) and UserPromptSubmit hooks. Returns the list of what
    changed: 'SessionStart', 'UserPromptSubmit' and, when a messages-on prompt hook was replaced, 'messages-off'."""
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
        backup = settings_path.with_name(settings_path.name + '.bak-superyak')
        if settings_path.exists() and not backup.exists():
            shutil.copy2(settings_path, backup)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        _write_settings(settings_path, settings)
    return changes


def remove_hooks(settings_path):
    settings_path = Path(settings_path)
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    changed = False
    for event in HOOK_EVENTS:
        kept = []
        for entry in settings.get('hooks', {}).get(event, []):
            hooks = [h for h in entry.get('hooks', []) if not is_station_hook(h.get('command'))]
            if len(hooks) == len(entry.get('hooks', [])):
                kept.append(entry)
                continue
            changed = True
            if hooks:  # keep the person's own hooks that shared the entry
                kept.append({**entry, 'hooks': hooks})
        if changed and event in settings.get('hooks', {}):
            settings['hooks'][event] = kept
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


def register_claude(name, argv, out):
    try:
        if subprocess.run(['claude', 'mcp', 'get', name], capture_output=True).returncode == 0:
            return
        subprocess.run(['claude', 'mcp', 'add', '--scope', 'user', name, '--', *[str(a) for a in argv]], check=True, capture_output=True)
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


def install_service(argv, out, system=None):
    system = system or platform.system()
    path_env = os.environ.get('PATH', '/usr/bin:/bin')
    if system == 'Linux':
        unit = Path.home() / '.config' / 'systemd' / 'user' / UNIT
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(systemd_unit(argv, path_env))
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', '--user', 'enable', UNIT], check=True, capture_output=True)
        subprocess.run(['systemctl', '--user', 'restart', UNIT], check=True)
        if subprocess.run(['loginctl', 'enable-linger'], capture_output=True).returncode:
            out('Could not enable linger; the watcher runs only while you are logged in.')
    elif system == 'Darwin':
        plist = Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(launchd_plist(argv, path_env, Path.home() / '.superyak' / 'ship.log'))
        domain = f'gui/{os.getuid()}'
        subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True)
        subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
    else:
        out(f'Start the watcher yourself: {shlex.join(str(a) for a in argv)}')
        return
    out('The watcher is running; it answers mentions within about 30 seconds.')


def hook_command(config_path):
    return shlex.join([sys.executable, str(RUN_AGENT), 'hook', '--config', str(config_path)])


def install_all(config_path, *, hook=False, adna=True, service=True, out=print):
    """The required steps come first so that nothing optional can hold them up: the watcher's tool config
    (without aDNA), the station tools for Claude Code and Codex, the hook, the watcher service. Then the
    optional aDNA tools; if they install, the watcher's tool config is rewritten to include them (each run
    reads the file afresh) and they are registered with Claude Code."""
    config_path = Path(config_path)
    home, mcp_argv = config_path.parent, [sys.executable, str(RUN_AGENT), 'mcp', '--config', str(config_path)]
    write_private(home / 'run-mcp.json', run_mcp_config(config_path))
    if shutil.which('claude'):
        register_claude('station', mcp_argv, out)
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
    if service:
        install_service([sys.executable, str(RUN_AGENT), 'watch', '--config', str(config_path),
                         '--state', str(home / 'ship-state.json'), '--mcp-config', str(home / 'run-mcp.json')], out)
    adna_dist = setup_adna(out) if adna else None
    if adna_dist:
        write_private(home / 'run-mcp.json', run_mcp_config(config_path, adna_dist))
        out('Added the aDNA tools to the watcher.')
        if shutil.which('claude'):
            register_claude('adna', [shutil.which('node'), adna_dist], out)


def uninstall_all(config_path, out=print):
    config_path = Path(config_path)
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
        subprocess.run(['claude', 'mcp', 'remove', '--scope', 'user', 'station'], capture_output=True)
    remove_codex(Path.home() / '.codex' / 'config.toml', 'station')
    remove_hooks(Path.home() / '.claude' / 'settings.json')
    for path in (config_path, config_path.parent / 'run-mcp.json'):
        path.unlink(missing_ok=True)
    local = 'watcher stopped, station tools and hook removed'
    if revoked is False:
        out(f'Undocked on this machine ({local}), but the key was NOT revoked on the station: ask an admin to revoke it.')
    else:
        out(f'Undocked: {"key revoked, " if revoked else ""}{local}.')
