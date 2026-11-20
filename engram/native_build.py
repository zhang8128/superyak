"""Build one of Engram's C files into a shared library, once for each source, compiler and machine, in a cache that is
this user's alone. It takes the care `ncat.py` takes for the n-category kernel: the compiler is one of three fixed paths
and never one found on PATH, it runs with a two-entry environment, and a cache folder or library that someone else could
write is refused, because either could hand us someone's code. `ncat.py` keeps its own copy of this until its C++ port
lands; a fix to one belongs in both."""
import hashlib
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path

# -ffp-contract=off: no fused multiply-add, so an arm64 build and an x86-64 build do the same arithmetic.
FLAGS = ('-std=c11', '-O2', '-fPIC', '-shared', '-fstack-protector-strong', '-D_FORTIFY_SOURCE=2', '-Wall',
         '-ffp-contract=off')
LINUX_FLAGS = ('-Wl,-z,relro', '-Wl,-z,now', '-Wl,-z,noexecstack')
COMPILERS = ('/usr/bin/cc', '/usr/bin/gcc', '/usr/bin/clang')  # never one found on PATH
BUILD_ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}


def source(name):
    """The C file beside this module, or where an installed wheel keeps it with the other shared files."""
    path = Path(__file__).with_name(name)
    return path if path.exists() else Path(sys.prefix) / 'share' / 'engram' / name


def compiler():
    return next((c for c in COMPILERS if os.access(c, os.X_OK)), None)


def private(path, kind, who):
    """Ours alone: owned by this user, and nobody else may write it."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise RuntimeError(f"{who} won't use {path}: the {kind} must be this user's own, and writable by nobody else")


def built(src, who, libs=()):
    """The path of the library built from `src`, building it first when this cache has none for it. `who` names the
    cache folder and the library; `libs` are linked after the source (for example '-lm')."""
    text = src.read_bytes()
    cc = compiler()
    if cc is None:
        raise RuntimeError(f'{who} needs a C compiler at ' + ', '.join(COMPILERS[:-1]) + f' or {COMPILERS[-1]}')
    flags = FLAGS + (LINUX_FLAGS if sys.platform.startswith('linux') else ())
    machine = f'{sys.platform} {platform.machine()}'  # a home shared across architectures keeps one library each
    tag = hashlib.blake2b(text + cc.encode() + ' '.join(flags + tuple(libs)).encode() + machine.encode(),
                          digest_size=12).hexdigest()
    cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'superyak' / who
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    private(cache, 'cache folder', who)
    out = cache / f'{who}-{tag}.so'
    if not out.exists():
        partial = cache / f'.{out.name}.{os.getpid()}'
        try:
            subprocess.run([cc, *flags, str(src), '-o', str(partial), *libs], check=True, capture_output=True,
                           env=BUILD_ENV)
            partial.chmod(0o700)
            partial.replace(out)
        finally:
            partial.unlink(missing_ok=True)
    private(out, 'library', who)
    return out
