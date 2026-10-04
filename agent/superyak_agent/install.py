"""Register the station tools, the optional hook and the watcher service on this machine."""
import json
import os
from pathlib import Path
import platform
import plistlib
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


def install_hook(settings_path, command):
    settings_path = Path(settings_path)
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    entries = settings.setdefault('hooks', {}).setdefault('UserPromptSubmit', [])
    if any(h.get('command') == command for entry in entries for h in entry.get('hooks', [])):
        return False
    if settings_path.exists():
        shutil.copy2(settings_path, settings_path.with_name(settings_path.name + '.bak-superyak'))
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    entries.append({'hooks': [{'type': 'command', 'command': command, 'timeout': 10}]})
    _write_settings(settings_path, settings)
    return True


def remove_hook(settings_path, command):
    settings_path = Path(settings_path)
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    entries = settings.get('hooks', {}).get('UserPromptSubmit', [])
    kept = [e for e in entries if not any(h.get('command') == command for h in e.get('hooks', []))]
    if len(kept) == len(entries):
        return False
    settings['hooks']['UserPromptSubmit'] = kept
    _write_settings(settings_path, settings)
    return True


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


def register_claude(name, argv, out):
    if subprocess.run(['claude', 'mcp', 'get', name], capture_output=True).returncode == 0:
        return
    subprocess.run(['claude', 'mcp', 'add', '--scope', 'user', name, '--', *[str(a) for a in argv]], check=True, capture_output=True)
    out(f'Registered the {name} tools with Claude Code.')


def setup_adna(out, root=None):
    root = Path(root or Path.home() / 'aDNA' / 'aDNA.aDNA')
    node, npm, git = shutil.which('node'), shutil.which('npm'), shutil.which('git')
    version = subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip().lstrip('v') if node else ''
    if not (node and npm and git) or int(version.split('.')[0] or 0) < 20:
        out('aDNA tools skipped: they need Node.js 20 or newer, npm and git. Install Node.js and run make dock again.')
        return None
    dist = root / 'mcp' / 'dist' / 'index.js'
    if not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([git, 'clone', '--depth', '1', ADNA_REPO, str(root)], check=True)
    if not dist.exists():
        subprocess.run([npm, 'ci', '--ignore-scripts'], cwd=root / 'mcp', check=True)
        subprocess.run([npm, 'run', 'build'], cwd=root / 'mcp', check=True)
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
    config_path = Path(config_path)
    home, mcp_argv = config_path.parent, [sys.executable, str(RUN_AGENT), 'mcp', '--config', str(config_path)]
    adna_dist = setup_adna(out) if adna else None
    write_private(home / 'run-mcp.json', run_mcp_config(config_path, adna_dist))
    if shutil.which('claude'):
        register_claude('station', mcp_argv, out)
        if adna_dist:
            register_claude('adna', [shutil.which('node'), adna_dist], out)
    else:
        out('Claude Code not found; skipped registering the station tools for it.')
    codex = Path.home() / '.codex' / 'config.toml'
    if (shutil.which('codex') or codex.exists()) and register_codex(codex, 'station', mcp_argv):
        out('Registered the station tools with Codex.')
    if hook and install_hook(Path.home() / '.claude' / 'settings.json', hook_command(config_path)):
        out('Added the station hook: new room messages appear at the start of each Claude Code turn.')
    if service:
        install_service([sys.executable, str(RUN_AGENT), 'watch', '--config', str(config_path),
                         '--state', str(home / 'ship-state.json'), '--mcp-config', str(home / 'run-mcp.json')], out)


def uninstall_all(config_path, out=print):
    config_path = Path(config_path)
    config = read_json(config_path)
    if config and config.get('key'):
        try:
            client_for(config).revoke_key()
        except (StationError, OSError) as error:
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
    remove_hook(Path.home() / '.claude' / 'settings.json', hook_command(config_path))
    for path in (config_path, config_path.parent / 'run-mcp.json'):
        path.unlink(missing_ok=True)
    out('Undocked: key revoked, watcher stopped, station tools and hook removed.')
