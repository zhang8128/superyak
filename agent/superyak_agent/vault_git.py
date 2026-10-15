"""Stanley's sync key can only fetch and push the station vault: `authorized_keys` forces this
command, which accepts exactly `git-upload-pack` or `git-receive-pack` on one repository."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

VERBS = ('git-upload-pack', 'git-receive-pack')
# The comment is printable ASCII without `"` and `\`: nothing str.splitlines(), a shell or sshd could read as a line end
# or an option, so a comment cannot smuggle in a second (unrestricted) key line.
KEY_LINE = re.compile(r'(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com) '
                      r'[A-Za-z0-9+/]+=*( [\x20\x21\x23-\x5b\x5d-\x7e]*)?')


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


def _write_private(path, data):
    """Replace `path` with `data` (bytes), 0600 from the start, never leaving a half-written file in its place."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(fd, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(fd)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def install_key(key, repo, python, run_agent, authorized_keys):
    """Append one `restrict,command=…` line for `key`. Returns False when the key is already there. Lines already
    in the file are kept byte for byte: it is read and written as bytes and split on b"\\n" only."""
    if '\n' in key or '\r' in key or not KEY_LINE.fullmatch(key.strip()):
        raise ValueError('Give one SSH public key line, e.g. "ssh-ed25519 AAAA… comment"')
    key = key.strip()
    command = ' '.join([shlex.quote(str(python)), shlex.quote(str(run_agent)), 'vault-git', '--repo',
                        shlex.quote(str(Path(repo).resolve()))])  # sshd runs it through the login shell
    if '"' in command or '\\' in command:
        raise ValueError('Paths with quotes or backslashes are not supported')
    path = Path(authorized_keys)
    data = path.read_bytes() if path.exists() else b''
    blob = key.split()[1].encode()
    if any(blob in line.split() for line in data.split(b'\n')):
        return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        _write_private(path.with_name(path.name + '.bak-wormhole'), data)
    if data and not data.endswith(b'\n'):
        data += b'\n'
    _write_private(path, data + f'restrict,command="{command}" {key}\n'.encode())
    return True
