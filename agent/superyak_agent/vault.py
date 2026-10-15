"""The shared vault Station.aDNA: a bare repository on the Pi that Stanley's lattice syncs over the
mesh, and the bridge's working clone. Both sides only add files, so syncing replays our commits on
top of theirs.

Stanley's side can push anything git allows, so two layers keep it harmless: a pre-receive hook on the bare
repository (`install_gate`) lets every pusher except our own Vault (which sets STATION_VAULT_PUSHER=bridge)
only add plain files to the inbox and receipts folders, and the clone never follows a symlink or lets pushed
attributes touch what it writes."""
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
MAX_PUSH_BYTES = 8 * 1024 * 1024  # receive.maxInputSize of the bare repository
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
# CLAUDE.md and AGENTS.md of the vault, in place of the template's generic instructions: an agent of the lattice
# that opens the vault must only add drop-box files, or the gate refuses its whole push, inbox memos included.
VAULT_IDENTITY = """# Station.aDNA

This is Station.aDNA, the shared vault of Deep Space 9 (the Superyak station on Andy's Raspberry Pi).
Its persona is Wormhole, a bridge program that runs no model and only copies text between station rooms
and aDNA personas.

## Read

`who/coordination/outbound/` holds memos from station rooms to aDNA personas; `to_persona` names the
persona each one is for.

## Write

Only new files, and only in these two folders:

- `who/coordination/inbox/`: `.md` memos to the station. Their front matter names `Station.aDNA` in `to`
  or `to_vault` (for example `to: "Station.aDNA (Wormhole)"`). To answer an outbound memo, add
  `in_reply_to: <outbound file name>`.
- `who/coordination/receipts/`: an empty or short file named exactly like the outbound memo you picked up.

Plain files named with letters, digits, `.`, `_` and `-`, at most 1 MiB each and 8 MiB per push, on
`main`. No edits, no deletions, no other folders: the station refuses the whole push otherwise. Keep
session logs, state and other work in your own vault.

## Approvals

A memo may recommend; ratification happens in your own vault.
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
# Always: receive.fsckObjects must be on, only the vault branch, no deletions, history only grows. Unless
# STATION_VAULT_PUSHER=bridge (set by superyak_agent.vault.Vault for its own pushes; the forced command of
# Stanley's sync key sets `lattice`): every commit, and the push as a whole, may only ADD new plain files
# (mode 100644, at most 1 MiB) directly in who/coordination/inbox/ or who/coordination/receipts/.
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


dropbox = os.environ.get('STATION_VAULT_PUSHER') != 'bridge'  # fail closed: any other pusher gets the drop-box rules
lines = sys.stdin.read().splitlines()
if subprocess.run(['git', 'config', '--bool', 'receive.fsckObjects'], capture_output=True).stdout.strip() != b'true':
    refuse('receive.fsckObjects must be true in the repository config')
for line in lines:
    old, new, ref = line.split(' ', 2)
    if ref != 'refs/heads/' + BRANCH:
        refuse('only %s may be pushed, not %r' % (BRANCH, ref[:80]))
    if set(new) == {'0'}:
        refuse('the branch cannot be deleted')
    created = set(old) == {'0'}
    if not created and subprocess.run(['git', 'merge-base', '--is-ancestor', old, new]).returncode:
        refuse('history may only grow: pull, then push again')
    if not dropbox:
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


def bridge_env():
    """The environment of our own pushes: it tells the gate this pusher is the bridge, not the lattice."""
    return {**os.environ, 'STATION_VAULT_PUSHER': 'bridge'}


def set_config(bare, key, value):
    subprocess.run(['git', '-C', str(bare), 'config', '--replace-all', key, value], check=True, capture_output=True)


def install_gate(bare, branch='main', limit=True):
    """Make the bare repository refuse rewrites, deletions, other branches and (with `limit`) pushes over
    MAX_PUSH_BYTES, and install the pre-receive hook that holds every push not made by the bridge to new
    inbox/receipt files. `core.hooksPath` is pinned to `hooks`, relative, so it keeps naming the repository's own
    folder if the repository is moved or restored elsewhere (an absolute path would then point nowhere, and git
    skips a missing hooks folder), while a global setting still cannot switch the hook off. Safe to run again on
    an existing repository: it brings the settings and the hook up to date."""
    bare = Path(bare)
    hooks = bare / 'hooks'
    hooks.mkdir(exist_ok=True)
    settings = {'receive.denyNonFastForwards': 'true', 'receive.denyDeletes': 'true', 'receive.fsckObjects': 'true',
                'core.hooksPath': 'hooks'}
    if limit:
        settings['receive.maxInputSize'] = str(MAX_PUSH_BYTES)
    for key, value in settings.items():
        set_config(bare, key, value)
    hook = hooks / 'pre-receive'
    temporary = hooks / 'pre-receive.tmp'
    temporary.write_text(PRE_RECEIVE.replace('__BRANCH__', repr(branch)))
    temporary.chmod(0o755)
    os.replace(temporary, hook)  # a push that starts meanwhile sees the old hook or the new one, never half of one


class Vault:
    def __init__(self, clone, remote='origin', branch='main'):
        self.clone, self.remote, self.branch = Path(clone), remote, branch

    def git(self, *args, check=True, env=None):
        result = subprocess.run(['git', '-C', str(self.clone), *SAFE, *args], capture_output=True, text=True,
                                errors='replace', env=env)
        if check and result.returncode:
            raise VaultError(f'git {args[0]} failed: {result.stderr.strip()[:300]}')
        return result

    @classmethod
    def create(cls, bare, clone, template=None, branch='main'):
        """Create the bare repository and the bridge's clone, with the aDNA layout copied from
        `template` (without .git or node_modules), the vault's own README.md, CLAUDE.md and AGENTS.md, and the three
        drop-box folders."""
        bare, clone = Path(bare), Path(clone)
        if bare.exists() or clone.exists():
            raise VaultError(f'{bare} or {clone} already exists')
        bare.parent.mkdir(parents=True, exist_ok=True)
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', '--bare', '-b', branch, str(bare)], check=True, capture_output=True)
        install_gate(bare, branch, limit=False)  # the first push carries the whole template, which may be big
        subprocess.run(['git', 'clone', '-q', str(bare), str(clone)], check=True, capture_output=True)
        vault = cls(clone, branch=branch)
        vault.git('symbolic-ref', 'HEAD', f'refs/heads/{branch}')
        attributes = clone / vault.git('rev-parse', '--git-path', 'info/attributes').stdout.strip()
        attributes.parent.mkdir(parents=True, exist_ok=True)
        attributes.write_text(ATTRIBUTES)
        if template:
            shutil.copytree(template, clone, dirs_exist_ok=True, symlinks=True,
                            ignore=shutil.ignore_patterns('.git', 'node_modules'))
        for name, text in (('README.md', VAULT_README), ('CLAUDE.md', VAULT_IDENTITY), ('AGENTS.md', VAULT_IDENTITY)):
            (clone / name).unlink(missing_ok=True)  # a symlink copied from the template is replaced, never written through
            (clone / name).write_text(text)
        for folder, text in FOLDER_README.items():
            (clone / folder).mkdir(parents=True, exist_ok=True)
            (clone / folder / 'README.md').write_text(text)
        vault.git('add', '-A')
        vault.git(*AUTHOR, 'commit', '-q', '-m', 'Station.aDNA: the shared vault of the Deep Space 9 wormhole bridge')
        vault.git('push', '-q', vault.remote, f'HEAD:{branch}', env=bridge_env())
        set_config(bare, 'receive.maxInputSize', str(MAX_PUSH_BYTES))
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

    def listing(self, *args):
        """NUL-separated output of a git listing command, as a list of paths (or fields) with surrogate-escaped
        undecodable bytes, so an odd file name cannot raise."""
        result = subprocess.run(['git', '-C', str(self.clone), *SAFE, *args], capture_output=True)
        if result.returncode:
            raise VaultError(f'git {args[0]} failed: {result.stderr.decode("utf-8", "replace").strip()[:300]}')
        return [part.decode('utf-8', 'surrogateescape') for part in result.stdout.split(b'\0') if part]

    def recover(self):
        """Finish what a crash interrupted in add_outbound, which writes the file, stages it, then commits it.
        New memos left untracked or staged (valid names, plain files, directly in the outbound folder) are
        committed together as one commit; their names are returned. A file that is empty or does not start with
        `---` front matter (a crash between creating it and writing it) is not a memo yet: it stays on disk,
        uncommitted. Anything else staged is unstaged so it cannot block the rebase in sync(); anything else
        uncommitted is left alone."""
        root = self.folder(OUTBOUND)
        staged = self.listing('diff', '--cached', '--name-status', '--no-renames', '-z')
        staged = dict(zip(staged[1::2], staged[0::2]))  # path -> status letter
        candidates = [path for path, status in staged.items() if status == 'A']
        candidates += self.listing('ls-files', '--others', '-z', '--', OUTBOUND)  # ignored ones too: the folder is ours
        found = {}
        for path in candidates:
            folder, _, name = path.rpartition('/')
            try:
                plain = (root is not None and folder == OUTBOUND and MEMO_NAME.fullmatch(name)
                         and self.begins_memo(root / name))
            except (OSError, ValueError):
                plain = False
            if plain:
                found[path] = name
        unwanted = [path for path in staged if path not in found]
        if unwanted:
            self.git('--literal-pathspecs', 'reset', '-q', '--', *unwanted)  # a file named `:(top)x` is no pathspec
        if not found:
            return []
        self.git('add', '-f', '--', *found)  # -f: a template .gitignore must not keep a memo out
        self.git(*AUTHOR, 'commit', '-q', '-m', 'wormhole: recover interrupted memos', '--', *found)
        return sorted(found.values())

    @staticmethod
    def begins_memo(path):
        """True when `path` is a plain file (never a symlink or device) that starts with `---`, a memo's front matter."""
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            return stat.S_ISREG(os.fstat(stream.fileno()).st_mode) and stream.read(3) == b'---'

    def tracked(self, folder, name):
        """True when HEAD holds a plain file `name` directly in `folder`, i.e. it is committed (a memo that is
        only on disk or only staged is not)."""
        if not name or '/' in name or name in ('.', '..'):
            return False
        result = self.git('cat-file', '-t', f'HEAD:{folder}/{name}', check=False)
        return result.returncode == 0 and result.stdout.strip() == 'blob'

    def publish(self):
        ahead = self.git('rev-list', '--count', f'{self.remote}/{self.branch}..HEAD', check=False)
        if ahead.returncode or ahead.stdout.strip() != '0':
            self.git('push', '-q', self.remote, f'HEAD:{self.branch}', env=bridge_env())

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
                self.git('add', '-f', '--', path)  # -f: a template .gitignore must not keep a memo out
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
