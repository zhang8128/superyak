"""Breaks the kernel one way at a time and runs the kernel's tests against each. Every mutant here should be caught, except those
marked equivalent, each with the reason it can't change an answer. Run from engram/: python experiments/ncat/mutants.py
[--kernel cpp|c]. The kernel is the C++ port (ncat_kernel.cpp) by default; --kernel c breaks the C oracle the same ways."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ENGRAM = Path(__file__).resolve().parents[2]
KERNELS = {'cpp': ('ncat_kernel.cpp', ['/usr/bin/c++', '-std=c++20']), 'c': ('ncat_kernel.c', ['/usr/bin/cc', '-std=c11'])}
EQUIVALENT = {
    'faces not sorted': 'face lists keep their atom\'s canonical order through every copy, so sorting changes nothing',
    'formal ignored at interning': 'the hash already holds the formal dimension, so two cells that differ there never meet',
    'unit law not special-cased': 'gluing a cell that is all boundary gives the other side, which is what the shortcut returns',
}
MUTANTS = [
    ('boundary sign flipped', 'if (sign < 0) for (int32_t j = 0; j < h->out_n[e]; j++) mark', 'if (sign > 0) for (int32_t j = 0; j < h->out_n[e]; j++) mark'),
    ('composing skips the boundary check', 'if (ba != bb) return NCAT_ENOTCOMPOSABLE;', ''),
    ('faces not sorted', 'qsort(words + at, (size_t)h->in_n[e], sizeof(int32_t), cmp_i32);', ''),
    ('labels dropped from the words', 'words[p++] = h->dim[e]; words[p++] = h->label[e];', 'words[p++] = h->dim[e]; words[p++] = 0;'),
    ('round check off for the source', 'if (!rs) return NCAT_ENOTROUND;', ''),
    ('degenerate check off', 'if (S.shape != m || T.shape != m) return NCAT_EDEGENERATE;', ''),
    ('parallel check off', 'if (bs != bt) return NCAT_ENOTPARALLEL;', ''),
    ('formal ignored at interning', 'o->formal == formal && ', ''),
    ('boundary misses lower maximal elements', 'else if (h->dim[e] < k && face[e] != st) L[nL++] = e;', ''),
    ('walk misses lower maximal elements', 'else if (h->dim[e] < n - 1 && face[e] != st) L[nL++] = e;', ''),
    ("glue doesn't identify the boundary", 'for (int32_t i = 0; i < nb; i++) mapb[ob[i]] = mapa[oa[i]];', ''),
    ('composite keeps the wrong formal', 'int32_t formal = A.formal > B.formal ? A.formal : B.formal;', 'int32_t formal = A.formal;'),
    ("atom's output gets the input", 'h.pool[h.pool_len++] = mt[i]; h.out_n[x]++;', 'h.pool[h.pool_len++] = ms[i < S.n ? i : 0]; h.out_n[x]++;'),
    ('unit law not special-cased', 'if (A.shape <= k) id = with_formal(c, b, formal);', 'if (0) id = with_formal(c, b, formal);'),
    ('loop check off', 'if (top < 3) return 1;', 'return 1;'),
    ('loop check only at i = top - 2', 'for (int32_t i = 0; i < top && result == 1; i++) {', 'for (int32_t i = top - 2; i < top - 1 && result == 1; i++) {'),
    ('loop check skips dimension 3', 'if (top < 3) return 1;', 'if (top < 4) return 1;'),
    ('loop check only on top elements', 'if (h->dim[x] <= i) continue;\n            int32_t ncl = 0;', 'if (h->dim[x] != top) continue;\n            int32_t ncl = 0;'),
    ('loop check skips generators', '''            int lf = loop_free(c, &h);
            if (lf < 0) id = lf;
            else if (!lf) id = NCAT_ENOTLOOPFREE;
            else {
                Walk w = { .c = c };
                id = walk_ready(&w, &h, d);''', '''            int lf = 1;
            if (lf < 0) id = lf;
            else if (!lf) id = NCAT_ENOTLOOPFREE;
            else {
                Walk w = { .c = c };
                id = walk_ready(&w, &h, d);'''),
    ("the budget isn't counted", 'c->bytes_held += bytes;', ''),
    ("the work limit is ignored", 'c->work_limit = steps; return 0;', 'return 0;'),
    ("scratch isn't budgeted", '        if (over_budget(c, scratch - old)) return NCAT_EBUDGET;\n', ''),
    ("the context's own arrays aren't budgeted", 'return c->bytes_held + fixed_bytes(c) + more > c->bytes_budget;', 'return c->bytes_held + more > c->bytes_budget;'),
    ("words don't check a negative cap", 'cap < 0 || ', ''),
]
# Where the port's text differs from the C kernel's, the same break written in the port's words.
IN_CPP = {
    'faces not sorted': ('std::sort(words.get() + at, words.get() + p);\n        at = p;', 'at = p;'),
    'formal ignored at interning': ('o.formal == formal && ', ''),
    'loop check skips generators': ('''            int lf = loop_free(c, &h);
            if (lf < 0) id = lf;
            else if (!lf) id = NCAT_ENOTLOOPFREE;
            else {
                Walk w{c};
                id = walk_ready(&w, &h, d);''', '''            int lf = 1;
            if (lf < 0) id = lf;
            else if (!lf) id = NCAT_ENOTLOOPFREE;
            else {
                Walk w{c};
                id = walk_ready(&w, &h, d);'''),
    'the work limit is ignored': ('c->work_limit = steps; return (int32_t)0;', 'return (int32_t)0;'),
}
TESTS = ('catalan or beads or sheets or refused or composing or loops or parallel or same_however or units or globular or torsion '
         'or tangled or determined or exchanges or budget or checks_its_own or separate_blocks or dimension_2 or counts_everything or work')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    kernel = argv[argv.index('--kernel') + 1] if '--kernel' in argv else 'cpp'
    filename, compiler = KERNELS[kernel]
    source = (ENGRAM / filename).read_text()
    work = Path(tempfile.mkdtemp(prefix='ncat-mutants-', dir=os.environ.get('TMPDIR')))
    work.chmod(0o700)
    survivors = []
    for name, before, after in MUTANTS:
        if kernel == 'cpp' and name in IN_CPP:
            before, after = IN_CPP[name]
        assert source.count(before) == 1, name
        mutant = work / f'm{Path(filename).suffix}'
        mutant.write_text(source.replace(before, after))
        library = work / f'm{len(survivors)}-{abs(hash(name))}.so'
        subprocess.run([*compiler, '-O1', '-shared', '-fPIC', str(mutant), '-o', str(library)], check=True)
        library.chmod(0o700)
        try:
            run = subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_ncat.py', '-q', '-x', '-p', 'no:cacheprovider', '-k', TESTS],
                                 cwd=ENGRAM, env={**os.environ, 'NCAT_TEST_SO': str(library)}, capture_output=True, timeout=120)
            caught = run.returncode != 0
        except subprocess.TimeoutExpired:
            caught = True
        verdict = 'caught' if caught else ('equivalent' if name in EQUIVALENT else 'SURVIVED')
        print(f'{verdict:10} {name}' + (f'  ({EQUIVALENT[name]})' if not caught and name in EQUIVALENT else ''), flush=True)
        if not caught and name not in EQUIVALENT:
            survivors.append(name)
    return 1 if survivors else 0


if __name__ == '__main__':
    sys.exit(main())
