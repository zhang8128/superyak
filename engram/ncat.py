"""A strict n-category, free on its generators: identities, composition along every lower dimension, and equality you can
trust. The kernel is C (`ncat_kernel.c`), because equality is decided by canonicalising a shape at every composition. See
that file's head for what a cell is and what's refused. No storage and nothing steers recall: it's the structure alone."""
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).with_name('ncat_kernel.c')
if not SOURCE.exists():  # an installed wheel keeps it with the other shared files
    SOURCE = Path(sys.prefix) / 'share' / 'engram' / 'ncat_kernel.c'
ERRORS = {-1: 'not composable: the boundaries differ', -2: 'a generator with an identity boundary is refused',
          -3: "the source and target aren't parallel", -4: "a generator's boundary must be round",
          -5: "this shape isn't loop-free, so it doesn't determine its cell", -6: 'out of memory', -7: 'bad argument'}


class NCatError(ValueError):
    def __init__(self, code):
        super().__init__(ERRORS.get(code, f'error {code}'))
        self.code = code


def _built(flags=('-O2',)):
    source = SOURCE.read_bytes()
    tag = hashlib.blake2b(source + ' '.join(flags).encode(), digest_size=12).hexdigest()
    # Never a shared folder such as /tmp: what's here gets loaded and run.
    cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'superyak' / 'ncat'
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    out = cache / f'ncat-{tag}.so'
    if not out.exists():
        compiler = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
        if not compiler:
            raise RuntimeError('ncat needs a C compiler')
        partial = cache / f'{out.name}.{os.getpid()}'
        subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', *flags, str(SOURCE), '-o', str(partial)], check=True)
        partial.replace(out)
    return out


def _load():
    lib = ctypes.CDLL(os.environ.get('NCAT_SO') or str(_built()))
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
    return lib


_lib = None


def _kernel():
    global _lib
    if _lib is None:
        _lib = _load()
    return _lib


def _checked(value):
    if value < 0:
        raise NCatError(value)
    return value


class Cell:
    """A cell, equal to another exactly when the free n-category says so. Immutable."""
    __slots__ = ('cat', 'id')

    def __init__(self, cat, cell_id):
        self.cat, self.id = cat, cell_id

    def __eq__(self, other):
        return isinstance(other, Cell) and other.cat is self.cat and other.id == self.id

    def __hash__(self):
        return hash((id(self.cat), self.id))

    def __repr__(self):
        return f'<{self.dim}-cell {self.key()[:8]} over {self.size} elements>'

    @property
    def dim(self):
        return self.cat._lib.ncat_formal(self.cat._ptr, self.id)

    @property
    def shape_dim(self):
        """Below `dim` when the cell is an identity."""
        return self.cat._lib.ncat_shape(self.cat._ptr, self.id)

    @property
    def size(self):
        return self.cat._lib.ncat_size(self.cat._ptr, self.id)

    def source(self, k=None):
        return self.cat._cell(self.cat._lib.ncat_boundary(self.cat._ptr, self.id, self.dim - 1 if k is None else k, -1))

    def target(self, k=None):
        return self.cat._cell(self.cat._lib.ncat_boundary(self.cat._ptr, self.id, self.dim - 1 if k is None else k, 1))

    def identity(self):
        return self.cat._cell(self.cat._lib.ncat_identity(self.cat._ptr, self.id))

    def then(self, other, k=None):
        """self, then other, along their k-boundary: by default the highest one the two can share."""
        if k is None:
            k = min(self.dim, other.dim) - 1
        return self.cat._cell(self.cat._lib.ncat_compose(self.cat._ptr, self.id, other.id, k))

    def words(self):
        count = self.cat._lib.ncat_words(self.cat._ptr, self.id, None, 0)
        buf = (ctypes.c_int32 * count)()
        self.cat._lib.ncat_words(self.cat._ptr, self.id, buf, count)
        return list(buf)

    def key(self):
        """What the cell is, as a content address. Stable within this category's generator numbering."""
        data = self.dim.to_bytes(4, 'little') + b''.join(w.to_bytes(4, 'little') for w in self.words())
        return hashlib.blake2b(data, digest_size=16).hexdigest()


class NCat:
    """A polygraph: generators with checked boundaries, and the free strict n-category on them."""

    def __init__(self):
        self._lib = _kernel()
        self._ptr = self._lib.ncat_new()
        if not self._ptr:
            raise MemoryError

    def __del__(self):
        ptr, self._ptr = getattr(self, '_ptr', None), None
        if ptr:
            self._lib.ncat_free(ptr)

    def _cell(self, value):
        return Cell(self, _checked(value))

    def object(self):
        return self._cell(self._lib.ncat_gen(self._ptr, -1, -1))

    def generator(self, source, target):
        return self._cell(self._lib.ncat_gen(self._ptr, source.id, target.id))

    @property
    def cells_held(self):
        return self._lib.ncat_ncells(self._ptr)
