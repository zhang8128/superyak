"""The loop-free fragment of the free strict n-category on a regular polygraph: identities, composition along every lower
dimension, and equality you can trust where it answers. The kernel is C (`ncat_kernel.c`), because equality is decided by
canonicalising a shape at every composition. That file's head says what a cell is and what's refused. No storage, and nothing
steers recall: it's the structure alone.

Safe to share between threads: every call into the kernel holds the GIL (PyDLL) and the category's own lock. Cells from two
categories never mix. A category holds every cell it has made until it's dropped, within a budget of words."""
import ctypes
import hashlib
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path

SOURCE = Path(__file__).with_name('ncat_kernel.c')
if not SOURCE.exists():  # an installed wheel keeps it with the other shared files
    SOURCE = Path(sys.prefix) / 'share' / 'engram' / 'ncat_kernel.c'
MAX_DIM = 15
FLAGS = ('-std=c11', '-O2', '-fPIC', '-shared', '-fstack-protector-strong', '-D_FORTIFY_SOURCE=2', '-Wall')
LINUX_FLAGS = ('-Wl,-z,relro', '-Wl,-z,now', '-Wl,-z,noexecstack')
COMPILERS = ('/usr/bin/cc', '/usr/bin/gcc', '/usr/bin/clang')  # never one found on PATH
ERRORS = {-1: 'not composable: the boundaries differ', -2: 'a generator with an identity boundary is refused',
          -3: "the source and target aren't parallel", -4: "a generator's boundary must be round",
          -5: "this shape isn't loop-free, so the kernel won't say which cell it is (it may still be determined)",
          -6: 'out of memory', -7: 'bad argument', -8: "the traversal couldn't finish this shape",
          -9: 'too large for the kernel', -10: "over this category's budget"}


class NCatError(ValueError):
    def __init__(self, code):
        super().__init__(ERRORS.get(code, f'error {code}'))
        self.code = code


def _private(path, kind):
    """Ours alone: owned by this user, and nobody else may write it. A shared or loose cache could hand us someone's code."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise RuntimeError(f"ncat won't use {path}: the {kind} must be this user's own, and writable by nobody else")


def _built():
    source = SOURCE.read_bytes()
    compiler = next((c for c in COMPILERS if os.access(c, os.X_OK)), None)
    if compiler is None:
        raise RuntimeError('ncat needs a C compiler at /usr/bin/cc, /usr/bin/gcc or /usr/bin/clang')
    flags = FLAGS + (LINUX_FLAGS if sys.platform.startswith('linux') else ())
    tag = hashlib.blake2b(source + compiler.encode() + ' '.join(flags).encode(), digest_size=12).hexdigest()
    cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'superyak' / 'ncat'
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private(cache, 'cache folder')
    out = cache / f'ncat-{tag}.so'
    if not out.exists():
        partial = cache / f'.{out.name}.{os.getpid()}'
        try:
            subprocess.run([compiler, *flags, str(SOURCE), '-o', str(partial)], check=True, capture_output=True)
            partial.chmod(0o700)
            partial.replace(out)
        finally:
            partial.unlink(missing_ok=True)
    _private(out, 'library')
    return out


def _load():
    chosen = os.environ.get('NCAT_TEST_SO')  # tests only, such as a sanitizer build; never set it for a service
    path = Path(chosen) if chosen else _built()
    if chosen:
        _private(path, 'library')
    lib = ctypes.PyDLL(str(path))  # PyDLL holds the GIL through each call
    lib.ncat_new.restype = ctypes.c_void_p
    lib.ncat_free.argtypes = [ctypes.c_void_p]
    for name, args in (('ncat_gen', 2), ('ncat_compose', 3), ('ncat_boundary', 3), ('ncat_identity', 1), ('ncat_formal', 1),
                       ('ncat_shape', 1), ('ncat_size', 1)):
        fn = getattr(lib, name)
        fn.argtypes = [ctypes.c_void_p] + [ctypes.c_int32] * args
        fn.restype = ctypes.c_int32
    lib.ncat_words.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.c_int32]
    lib.ncat_words.restype = ctypes.c_int32
    lib.ncat_ncells.argtypes = [ctypes.c_void_p]
    lib.ncat_ncells.restype = ctypes.c_int32
    lib.ncat_held.argtypes = [ctypes.c_void_p]
    lib.ncat_held.restype = ctypes.c_int64
    lib.ncat_set_budget.argtypes = [ctypes.c_void_p, ctypes.c_int64]
    lib.ncat_set_budget.restype = ctypes.c_int32
    return lib


_lib, _lib_lock = None, threading.Lock()


def _kernel():
    global _lib
    with _lib_lock:
        if _lib is None:
            _lib = _load()
        return _lib


def _dim(k):
    if type(k) is not int or not 0 <= k <= MAX_DIM:
        raise NCatError(-7)
    return k


def _checked(value):
    if value < 0:
        raise NCatError(value)
    return value


class Cell:
    """A cell, equal to another exactly when the free n-category says so. Immutable, and tied to its category."""
    __slots__ = ('_cat', '_id')

    def __init__(self, cat, cell_id):
        object.__setattr__(self, '_cat', cat)
        object.__setattr__(self, '_id', cell_id)

    def __setattr__(self, name, value):
        raise AttributeError('a cell is immutable')

    @property
    def cat(self):
        return self._cat

    @property
    def id(self):
        return self._id

    def __eq__(self, other):
        return isinstance(other, Cell) and other._cat is self._cat and other._id == self._id

    def __hash__(self):
        return hash((id(self._cat), self._id))

    def __repr__(self):
        return f'<{self.dim}-cell {self.key()[:8]} over {self.size} elements>'

    @property
    def dim(self):
        return self._cat._call('ncat_formal', self._id)

    @property
    def shape_dim(self):
        """Below `dim` when the cell is an identity."""
        return self._cat._call('ncat_shape', self._id)

    @property
    def size(self):
        return self._cat._call('ncat_size', self._id)

    def source(self, k=None):
        return self._cat._cell(self._cat._call('ncat_boundary', self._id, _dim(self.dim - 1 if k is None else k), -1))

    def target(self, k=None):
        return self._cat._cell(self._cat._call('ncat_boundary', self._id, _dim(self.dim - 1 if k is None else k), 1))

    def identity(self):
        return self._cat._cell(self._cat._call('ncat_identity', self._id))

    def then(self, other, k=None):
        """self, then other, along their k-boundary: by default the highest one the two can share."""
        self._cat._own(other)
        if k is None:
            k = min(self.dim, other.dim) - 1
        return self._cat._cell(self._cat._call('ncat_compose', self._id, other._id, _dim(k)))

    def words(self):
        with self._cat._lock:
            count = _checked(self._cat._lib.ncat_words(self._cat._ptr, self._id, None, 0))
            buf = (ctypes.c_int32 * count)()
            _checked(self._cat._lib.ncat_words(self._cat._ptr, self._id, buf, count))
        return list(buf)

    def key(self):
        """What the cell is, as a content address. Stable within this category's generator numbering."""
        data = self.dim.to_bytes(4, 'little') + b''.join(w.to_bytes(4, 'little') for w in self.words())
        return hashlib.blake2b(data, digest_size=16).hexdigest()


class NCat:
    """A polygraph: generators with checked boundaries, and the cells they compose into. Dropping it frees every cell."""

    def __init__(self, budget_words=1 << 27):
        if type(budget_words) is not int or budget_words < 0:
            raise NCatError(-7)
        self._lib = _kernel()
        self._lock = threading.RLock()
        self._ptr = self._lib.ncat_new()
        if not self._ptr:
            raise MemoryError
        _checked(self._lib.ncat_set_budget(self._ptr, budget_words))

    def __del__(self):
        ptr, self._ptr = getattr(self, '_ptr', None), None
        if ptr:
            self._lib.ncat_free(ptr)

    def _call(self, name, *args):
        with self._lock:
            return _checked(getattr(self._lib, name)(self._ptr, *args))

    def _cell(self, value):
        return Cell(self, value)

    def _own(self, cell):
        if not isinstance(cell, Cell) or cell._cat is not self:
            raise NCatError(-7)

    def object(self):
        return self._cell(self._call('ncat_gen', -1, -1))

    def generator(self, source, target):
        self._own(source)
        self._own(target)
        return self._cell(self._call('ncat_gen', source._id, target._id))

    @property
    def cells_held(self):
        return self._call('ncat_ncells')

    @property
    def words_held(self):
        with self._lock:
            return self._lib.ncat_held(self._ptr)
