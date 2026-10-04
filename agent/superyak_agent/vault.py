"""The shared vault Station.aDNA: a bare repository on the Pi that Stanley's lattice syncs over the
mesh, and the bridge's working clone. Both sides only add files, so syncing replays our commits on
top of theirs."""
from pathlib import Path
import shutil
import subprocess

OUTBOUND = 'who/coordination/outbound'
INBOX = 'who/coordination/inbox'
RECEIPTS = 'who/coordination/receipts'
AUTHOR = ['-c', 'user.name=Wormhole', '-c', 'user.email=wormhole@station.invalid']
SAFE = ['-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-c', 'commit.gpgsign=false',
        '-c', 'protocol.file.allow=always']
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


class VaultError(RuntimeError):
    pass


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
        subprocess.run(['git', 'clone', '-q', str(bare), str(clone)], check=True, capture_output=True)
        vault = cls(clone, branch=branch)
        vault.git('symbolic-ref', 'HEAD', f'refs/heads/{branch}')
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
        """Fetch, then replay our unpublished commits on top of the remote branch."""
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

    def add_outbound(self, name, text):
        """Write and commit one outbound memo. Never overwrites: returns False if it exists."""
        path = self.clone / OUTBOUND / name
        if path.exists() or path.is_symlink():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.git('add', '--', f'{OUTBOUND}/{name}')
        self.git(*AUTHOR, 'commit', '-q', '-m', f'wormhole: {name}')
        return True

    def folder(self, folder):
        """The drop-box folder as a real directory inside the clone, or None. A symlink anywhere in its
        path (the lattice side can push one) would lead outside the vault, so none is followed."""
        root = (self.clone / folder).resolve()
        if not root.is_dir() or root != self.clone.resolve() / folder:
            return None
        return root

    def files(self, folder):
        """Regular, non-hidden files in a drop-box folder (README.md excluded), sorted by name."""
        root = self.folder(folder)
        if root is None:
            return []
        return sorted(p.name for p in root.iterdir()
                      if not p.is_symlink() and p.is_file() and p.name != 'README.md' and not p.name.startswith('.'))

    def read(self, folder, name, limit=200_000):
        """Text of one file in a drop-box folder; '' for anything that is not a plain file directly in it."""
        root = self.folder(folder)
        if root is None:
            return ''
        path = root / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
            return ''
        with open(path, 'rb') as stream:
            return stream.read(limit).decode('utf-8', 'replace')
