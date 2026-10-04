"""Stanley's sync key can only fetch and push the station vault: `authorized_keys` forces this
command, which accepts exactly `git-upload-pack` or `git-receive-pack` on one repository."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

VERBS = ('git-upload-pack', 'git-receive-pack')
KEY_LINE = re.compile(r'^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com) '
                      r'[A-Za-z0-9+/]+=*( [^"\\]*)?$')


def allowed(command, repo, home=None):
    """(verb, absolute repo path) when `command` is a fetch or push of exactly `repo`, else None."""
    try:
        parts = shlex.split(command or '')
    except ValueError:
        return None
    if len(parts) != 2 or parts[0] not in VERBS:
        return None
    raw, home = parts[1], Path(home or Path.home())
    path = home / raw[2:] if raw.startswith('~/') else Path(raw) if raw.startswith('/') else home / raw
    try:
        if path.resolve() != Path(repo).resolve():
            return None
    except OSError:
        return None
    return parts[0], str(Path(repo).resolve())


def _syslog(message):
    try:
        subprocess.run(['logger', '-t', 'station-vault', message[:500]], check=False)
    except OSError:  # no `logger` here: the refusal still stands
        pass


def serve(repo, environ=os.environ, execvp=os.execvp, log=None):
    command = environ.get('SSH_ORIGINAL_COMMAND', '')
    found = allowed(command, repo)
    if found is None:
        print('This key can only fetch and push the station vault.', file=sys.stderr)
        (log or _syslog)(f'refused {command!r}')
        return 1
    verb, path = found
    # The gate in the bare repository holds every pusher but the bridge to the drop-box rules; this key is never the bridge.
    environ['STATION_VAULT_PUSHER'] = 'lattice'
    execvp(verb, [verb, path])
    return 0


def install_key(key, repo, python, run_agent, authorized_keys):
    """Append one `restrict,command=…` line for `key`. Returns False when the key is already there."""
    if '\n' in key or '\r' in key or not KEY_LINE.match(key.strip()):
        raise ValueError('Give one SSH public key line, e.g. "ssh-ed25519 AAAA… comment"')
    key = key.strip()
    command = f'{python} {run_agent} vault-git --repo {Path(repo).resolve()}'
    if '"' in command or '\\' in command:
        raise ValueError('Paths with quotes or backslashes are not supported')
    path = Path(authorized_keys)
    lines = path.read_text().splitlines() if path.exists() else []
    if any(key.split()[1] in line.split() for line in lines):
        return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + '.bak-wormhole'))
    tmp = path.with_name(path.name + '.tmp-wormhole')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('\n'.join(lines + [f'restrict,command="{command}" {key}']) + '\n')
    os.replace(tmp, path)
    return True
