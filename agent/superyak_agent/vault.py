"""The shared vault Station.aDNA: a bare repository on the Pi that Stanley's lattice syncs over the
mesh, and the bridge's working clone. Both sides only add files, so syncing replays our commits on
top of theirs.

Stanley's side can push anything git allows, so two layers keep it harmless: a pre-receive hook on the bare
repository (`install_gate`) lets the lattice only add plain files to the inbox and receipts folders, and the
clone never follows a symlink or lets pushed attributes touch what it writes."""
from pathlib import Path
import os
import re
import shutil
import stat
import subprocess

OUTBOUND = 'who/coordination/outbound'
INBOX = 'who/coordination/inbox'
RECEIPTS = 'who/coordination/receipts'
AUTHOR = ['-c', 'user.name=Wormhole', '-c', 'user.email=wormhole@station.invalid']
SAFE = ['-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-c', 'commit.gpgsign=false',
        '-c', 'submodule.recurse=false']
MEMO_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.md')
# Highest-precedence attributes: nothing a pushed .gitattributes says may re-encode, filter or fail our memos.
ATTRIBUTES = '* -text -filter -ident !eol !working-tree-encoding\n'
VAULT_README = """# Station.aDNA

The shared vault of Deep Space 9, the Superyak station on Andy's Raspberry Pi. Its persona is
**Wormhole**, a bridge that relays messages between station rooms and aDNA personas. It runs no
model: it only copies text.

- `who/coordination/outbound/` — memos from the station to aDNA personas (`to_persona`).
- `who/coordination/inbox/` — memos to the station: `to: "Station.aDNA (Wormhole)"`; set
  `in_reply_to` to an outbound file name to answer it.
- `who/coordination/receipts/` — add an empty file named after an outbound memo to show it was
  picked up.

New files only, following the aDNA coordination drop-box doctrine: never edit or delete a memo.
"""
FOLDER_README = {
    OUTBOUND: '# Outbound\n\nMemos from Deep Space 9 to aDNA personas. Read the ones addressed to you; never edit them.\n',
    INBOX: ('# Inbox\n\nThe Station.aDNA drop-box. New files only; no probe needed. Address memos to '
            '`Station.aDNA (Wormhole)`. The station relays them into its rooms. Follows the aDNA coordination '
            'drop-box doctrine.\n'),
    RECEIPTS: '# Receipts\n\nAdd an empty file named exactly like an outbound memo to show it was picked up.\n',
}

PRE_RECEIVE = r"""#!/usr/bin/env python3
# Station.aDNA pre-receive gate, installed by superyak_agent.vault.install_gate.
# Always: only the vault branch, no deletions, history only grows. When STATION_VAULT_PUSHER=lattice (set
# by the forced command of Stanley's sync key): every commit, and the push as a whole, may only ADD new
# plain files (mode 100644, at most 1 MiB) directly in who/coordination/inbox/ or who/coordination/receipts/.
import os
import re
import subprocess
import sys

BRANCH = __BRANCH__
ALLOWED = re.compile(r'who/coordination/(inbox|receipts)/[A-Za-z0-9][A-Za-z0-9._-]{0,199}')
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
MAX_BLOB = 1_048_576


def refuse(reason):
    sys.stderr.write('station vault: push refused: %s\n' % reason)
    sys.exit(1)


def git(*args):
    result = subprocess.run(['git', *args], capture_output=True)
    if result.returncode:
        refuse('git %s failed' % args[0])
    return result.stdout


def problem(base, commit):
    # Why the change from base to commit is not just added plain drop-box files, or None.
    raw = git('diff-tree', '-r', '--no-renames', '--no-abbrev', '--raw', '-z', base, commit).split(b'\0')
    for header, path in zip(raw[0::2], raw[1::2]):
        fields = header.lstrip(b':').split(b' ')
        if len(fields) != 5:
            return 'unreadable change list'
        src_mode, dst_mode, src_sha, dst_sha, status = fields
        try:
            name = path.decode('utf-8')
        except UnicodeDecodeError:
            return 'a path is not valid UTF-8'
        if status != b'A' or src_mode != b'000000' or dst_mode != b'100644':
            return '%r is not a new plain file' % name[:80]
        if not ALLOWED.fullmatch(name):
            return '%r is not a plain file name directly in the inbox or receipts folder' % name[:80]
        if int(git('cat-file', '-s', dst_sha.decode('ascii')).strip()) > MAX_BLOB:
            return '%r is larger than 1 MiB' % name[:80]
    return None


lattice = os.environ.get('STATION_VAULT_PUSHER') == 'lattice'
for line in sys.stdin.read().splitlines():
    old, new, ref = line.split(' ', 2)
    if ref != 'refs/heads/' + BRANCH:
        refuse('only %s may be pushed, not %r' % (BRANCH, ref[:80]))
    if set(new) == {'0'}:
        refuse('the branch cannot be deleted')
    created = set(old) == {'0'}
    if not created and subprocess.run(['git', 'merge-base', '--is-ancestor', old, new]).returncode:
        refuse('history may only grow: pull, then push again')
    if not lattice:
        continue
    for entry in git('rev-list', '--parents', '--reverse', new if created else old + '..' + new).decode().splitlines():
        commit, *parents = entry.split()
        # A merge is fine when it is one parent plus allowed additions (its other side is checked itself).
        reasons = [problem(parent, commit) for parent in parents] or [problem(EMPTY_TREE, commit)]
        if all(reasons):
            refuse(reasons[0])
    reason = problem(EMPTY_TREE if created else old, new)
    if reason:
        refuse(reason)
"""


class VaultError(RuntimeError):
    pass


def plain_text(name):
    """True for a file name that encodes as UTF-8 and holds only printable characters (no newlines,
    control or direction-override characters)."""
    try:
        name.encode('utf-8')
    except UnicodeEncodeError:  # a name that is not valid UTF-8 shows up with surrogate escapes
        return False
    return name.isprintable()


def install_gate(bare, branch='main'):
    """Make the bare repository refuse rewrites, deletions and other branches, and install the pre-receive
    hook that holds pushes made with STATION_VAULT_PUSHER=lattice to new inbox/receipt files."""
    bare = Path(bare)
    for key in ('receive.denyNonFastForwards', 'receive.denyDeletes', 'receive.fsckObjects'):
        subprocess.run(['git', '-C', str(bare), 'config', key, 'true'], check=True, capture_output=True)
    hook = bare / 'hooks' / 'pre-receive'
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(PRE_RECEIVE.replace('__BRANCH__', repr(branch)))
    hook.chmod(0o755)


class Vault:
    def __init__(self, clone, remote='origin', branch='main'):
        self.clone, self.remote, self.branch = Path(clone), remote, branch

    def git(self, *args, check=True):
        result = subprocess.run(['git', '-C', str(self.clone), *SAFE, *args], capture_output=True, text=True)
        if check and result.returncode:
            raise VaultError(f'git {args[0]} failed: {result.stderr.strip()[:300]}')
        return result

    @classmethod
    def create(cls, bare, clone, template=None, branch='main'):
        """Create the bare repository and the bridge's clone, with the aDNA layout copied from
        `template` (without .git or node_modules) and the three drop-box folders."""
        bare, clone = Path(bare), Path(clone)
        if bare.exists() or clone.exists():
            raise VaultError(f'{bare} or {clone} already exists')
        bare.parent.mkdir(parents=True, exist_ok=True)
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', '--bare', '-b', branch, str(bare)], check=True, capture_output=True)
        install_gate(bare, branch)
        subprocess.run(['git', 'clone', '-q', str(bare), str(clone)], check=True, capture_output=True)
        vault = cls(clone, branch=branch)
        vault.git('symbolic-ref', 'HEAD', f'refs/heads/{branch}')
        attributes = clone / vault.git('rev-parse', '--git-path', 'info/attributes').stdout.strip()
        attributes.parent.mkdir(parents=True, exist_ok=True)
        attributes.write_text(ATTRIBUTES)
        if template:
            shutil.copytree(template, clone, dirs_exist_ok=True, symlinks=True,
                            ignore=shutil.ignore_patterns('.git', 'node_modules'))
        (clone / 'README.md').write_text(VAULT_README)
        for folder, text in FOLDER_README.items():
            (clone / folder).mkdir(parents=True, exist_ok=True)
            (clone / folder / 'README.md').write_text(text)
        vault.git('add', '-A')
        vault.git(*AUTHOR, 'commit', '-q', '-m', 'Station.aDNA: the shared vault of the Deep Space 9 wormhole bridge')
        vault.git('push', '-q', vault.remote, f'HEAD:{branch}')
        vault.git('branch', '-q', f'--set-upstream-to={vault.remote}/{branch}')
        return vault

    def sync(self):
        """Fetch, then replay our unpublished commits on top of the remote branch. The bare repository's gate
        keeps the lattice from rewriting history or adding files where we write, so the replay cannot
        conflict because of it; if it does anyway the rebase is aborted and VaultError raised."""
        self.git('fetch', '-q', self.remote)
        upstream = f'{self.remote}/{self.branch}'
        if self.git('rev-parse', '--verify', '-q', upstream, check=False).returncode:
            return
        rebase = self.git(*AUTHOR, 'rebase', '-q', upstream, check=False)
        if rebase.returncode:
            self.git('rebase', '--abort', check=False)
            raise VaultError(f'could not replay local memos on {upstream}: {rebase.stderr.strip()[:300]}')

    def publish(self):
        ahead = self.git('rev-list', '--count', f'{self.remote}/{self.branch}..HEAD', check=False)
        if ahead.returncode or ahead.stdout.strip() != '0':
            self.git('push', '-q', self.remote, f'HEAD:{self.branch}')

    def outbound_fd(self):
        """The outbound folder as a directory descriptor, creating missing folders. Every step opens a real
        directory relative to the one before and refuses a symlink, so a pushed link cannot redirect a write."""
        fd = os.open(self.clone, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in OUTBOUND.split('/'):
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                try:
                    child = os.open(part, flags, dir_fd=fd)
                except FileNotFoundError:
                    os.mkdir(part, 0o755, dir_fd=fd)
                    child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    def discard(self, folder, name, path):
        """Undo a half-done add_outbound: remove the file and unstage it."""
        os.unlink(name, dir_fd=folder)
        self.git('reset', '-q', '--', path, check=False)

    def add_outbound(self, name, text):
        """Write and commit one outbound memo. Never overwrites: returns False if it exists. Raises
        VaultError for an unsafe name, a symlink on the way to the folder, or a failed commit (the file is
        then removed again)."""
        if not MEMO_NAME.fullmatch(name):
            raise VaultError(f'not a safe memo file name: {name[:80]!r}')
        try:
            folder = self.outbound_fd()
        except OSError as error:
            raise VaultError(f'{OUTBOUND} is not a plain folder in the vault: {error}') from error
        try:
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=folder)
            except FileExistsError:
                return False
            except OSError as error:
                raise VaultError(f'cannot create {name}: {error}') from error
            path = f'{OUTBOUND}/{name}'
            try:
                with os.fdopen(fd, 'w', encoding='utf-8', errors='replace', newline='') as stream:
                    stream.write(text)
                self.git('add', '--', path)
                self.git(*AUTHOR, 'commit', '-q', '-m', f'wormhole: {name}')
            except VaultError:
                self.discard(folder, name, path)
                raise
            except OSError as error:
                self.discard(folder, name, path)
                raise VaultError(f'cannot write {name}: {error}') from error
            return True
        finally:
            os.close(folder)

    def folder(self, folder):
        """The drop-box folder as a real directory inside the clone, or None. A symlink anywhere in its
        path (the lattice side can push one) would lead outside the vault, so none is followed."""
        try:
            root = (self.clone / folder).resolve()
            if not root.is_dir() or root != self.clone.resolve() / folder:
                return None
        except (OSError, RuntimeError, ValueError):  # RuntimeError: a symlink loop
            return None
        return root

    def files(self, folder):
        """Regular, non-hidden files in a drop-box folder (README.md excluded), sorted by name. Names that
        are not valid UTF-8 or contain control or formatting characters are skipped."""
        root = self.folder(folder)
        if root is None:
            return []
        try:
            names = [p.name for p in root.iterdir() if not p.is_symlink() and p.is_file()]
        except OSError:
            return []
        return sorted(n for n in names if n != 'README.md' and not n.startswith('.') and plain_text(n))

    def read(self, folder, name, limit=200_000):
        """Text of one file in a drop-box folder; '' for anything that is not a plain file directly in it."""
        root = self.folder(folder)
        if root is None:
            return ''
        try:
            path = root / name
            if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
                return ''
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except (OSError, RuntimeError, ValueError):
            return ''
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return ''
            return stream.read(limit).decode('utf-8', 'replace')
