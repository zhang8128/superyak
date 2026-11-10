/* The loop-free fragment of the free strict n-category on a regular polygraph. No storage, no dependencies, C11.
 *
 * A cell is a pasting shape with a label on every element: a graded poset whose elements have oriented faces, and a map
 * to the generators. It need not be injective, so a loop used twice is two elements with one label and the order of use
 * stays (a chain table would make them commute). Shapes are regular molecules (Hadzihasanovic), which have no automorphism,
 * so a traversal that makes only choices the shape forces puts every element in one canonical order. Two cells are equal
 * exactly when their canonical words are equal, and cells are interned, so equality is comparing two integers.
 *
 * Composing along k glues the output k-boundary of one to the input k-boundary of the other. An identity is the same shape
 * one formal dimension higher, and gluing along a boundary that is the whole of one side gives the other side, so the unit
 * laws hold with nothing to do. Associativity, globularity and interchange are tested, not assumed (tests/test_ncat.py).
 *
 * Refused, and said: a generator with an identity boundary (it would bring Eckmann-Hilton), a generator whose boundary is
 * not round, and a shape that isn't loop-free in Steiner's sense (NCAT_ENOTLOOPFREE). That condition is sufficient for a shape to
 * determine its cell, not necessary, so the refusal is cautious: from dimension 3, a composite can be refused whose cell is in fact
 * determined (a spec reviewer's example, 2026-11-07). Composition is therefore partial from dimension 3. From dimension 4 it also
 * refuses real torsion, where the free category tells two orders apart and the shape can't (Rio Grande's example). A traversal
 * that can't finish is refused with its own code (NCAT_EWALK). Sizes are bounded, and a context has a budget. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define NCAT_MAX_DIM 15
enum { NCAT_ENOTCOMPOSABLE = -1, NCAT_EDEGENERATE = -2, NCAT_ENOTPARALLEL = -3, NCAT_ENOTROUND = -4,
       NCAT_ENOTLOOPFREE = -5, NCAT_ENOMEM = -6, NCAT_EARG = -7, NCAT_EWALK = -8, NCAT_ETOOBIG = -9, NCAT_EBUDGET = -10,
       NCAT_EWORK = -11 };
#define NCAT_EUNSUPPORTED NCAT_EWALK
/* Well inside int32 for every count and offset the kernel computes, with room for both sides of a composite. */
#define NCAT_MAX_ELEMENTS (1 << 22)
#define NCAT_MAX_WORDS (1 << 26)

typedef struct {
    int32_t formal, shape, n, nwords;
    int32_t *words;  /* per element, in canonical order: dim, label, nin, nout, in..., out... */
    int32_t *off;    /* n offsets into words */
    uint64_t hash;
} Cell;

/* A shape being worked on, in no particular order. */
typedef struct {
    int32_t n, cap, pool_len, pool_cap;
    int32_t *dim, *label, *in_at, *in_n, *out_at, *out_n, *pool;
} Host;

typedef struct { int32_t a, b, k, val; } MemoSlot;

#ifndef NCAT_MASK_MAX  /* a test build may set it small, to reach the cap; ncat_kernel.cpp is the kernel, this its oracle */
#define NCAT_MASK_MAX ((1u << 30) - 1)  /* the largest table or memo mask: one more doubling would still fit 32 bits */
#endif
enum { U_MS, U_SEEN, U_FACE, U_OUT, U_DOWNST, U_INFRONT, U_DONE, U_COUNT };
enum { I_S, I_SEQ, I_F, I_L, I_DOWN, I_STACKLESS, I_COUNT };

typedef struct {
    Cell *cells;
    int32_t ncells, cap_cells;
    int32_t *table;  /* interning, open addressing, -1 empty */
    uint32_t table_mask;
    MemoSlot *memo;  /* composites and boundaries asked before; a = -1 empty */
    uint32_t memo_mask, memo_used;
    int32_t ngens;
    int64_t bytes_held, bytes_budget;  /* every held cell's memory with its overheads, and the most allowed */
    int64_t work, work_limit;          /* steps taken by the call in progress, and the most one call may take */
    /* traversal scratch, grown as needed */
    int32_t scr_n, scr_d;
    uint64_t stamp;   /* 64 bits: no run of calls can wrap it, so a mark never meets an old one */
    uint64_t *scr_u;
    int32_t *scr_i;
} Ctx;

/* ------------------------------------------------------------------ interning */

static uint64_t hash_words(const int32_t *w, int32_t n, int32_t formal)
{
    uint64_t h = 0x9E3779B97F4A7C15ULL ^ (uint64_t)(uint32_t)formal;
    for (int32_t i = 0; i < n; i++) {
        h ^= (uint64_t)(uint32_t)w[i];
        h *= 0xff51afd7ed558ccdULL;
        h ^= h >> 29;
    }
    return h;
}

static int grow_table(Ctx *c)
{
    if (c->table_mask >= NCAT_MASK_MAX) return NCAT_ETOOBIG;  /* intern refuses first; this only guards */
    uint32_t cap = (c->table_mask + 1) * 2;
    int32_t *t = malloc(sizeof(int32_t) * cap);
    if (!t) return NCAT_ENOMEM;
    memset(t, 0xff, sizeof(int32_t) * cap);
    for (int32_t i = 0; i < c->ncells; i++) {
        uint32_t at = (uint32_t)c->cells[i].hash & (cap - 1);
        while (t[at] >= 0) at = (at + 1) & (cap - 1);
        t[at] = i;
    }
    free(c->table);
    c->table = t;
    c->table_mask = cap - 1;
    return 0;
}

/* What a held cell costs: its words and offsets, its struct, the allocator's overhead on its two blocks, its slot in the interning
 * table at the table's worst load, and two memo slots for the composite or boundary that made it. Measured against resident memory
 * by tests/test_ncat.py. */
static int64_t cell_bytes(int32_t nwords, int32_t n)
{
    return (int64_t)nwords * 4 + (int64_t)(n ? n : 1) * 4 + 2 * 32;
}

/* The context's own arrays at their current sizes: cells, the interning table, the memo and the traversal's scratch. */
static int64_t fixed_bytes(const Ctx *c)
{
    return (int64_t)c->cap_cells * (int64_t)sizeof(Cell) + ((int64_t)c->table_mask + 1) * 4 +
           ((int64_t)c->memo_mask + 1) * (int64_t)sizeof(MemoSlot) +
           (int64_t)c->scr_n * c->scr_d * (U_COUNT * (int64_t)sizeof(uint64_t) + I_COUNT * (int64_t)sizeof(int32_t));
}

/* Would growing by more bytes take the context past its budget? */
static int over_budget(const Ctx *c, int64_t more) { return c->bytes_held + fixed_bytes(c) + more > c->bytes_budget; }

/* Takes ownership of words. Returns the cell's id, the same id for the same cell. */
static int32_t intern(Ctx *c, int32_t formal, int32_t shape, int32_t n, int32_t *words, int32_t nwords)
{
    if (n > NCAT_MAX_ELEMENTS || nwords > NCAT_MAX_WORDS) { free(words); return NCAT_ETOOBIG; }
    uint64_t h = hash_words(words, nwords, formal);
    uint32_t at = (uint32_t)h & c->table_mask;
    while (c->table[at] >= 0) {
        Cell *o = &c->cells[c->table[at]];
        if (o->hash == h && o->formal == formal && o->nwords == nwords &&
            memcmp(o->words, words, sizeof(int32_t) * (size_t)nwords) == 0) {
            free(words);
            return c->table[at];
        }
        at = (at + 1) & c->table_mask;
    }
    int64_t bytes = cell_bytes(nwords, n);
    int64_t growth = 0;  /* the arrays that would double for this cell */
    if (c->ncells == c->cap_cells) growth += (int64_t)c->cap_cells * (int64_t)sizeof(Cell);
    if ((uint32_t)(c->ncells + 1) * 2 > c->table_mask) {
        if (c->table_mask >= NCAT_MASK_MAX) { free(words); return NCAT_ETOOBIG; }  /* refused before anything changes */
        growth += ((int64_t)c->table_mask + 1) * 4 * 2;
    }
    if (over_budget(c, bytes + growth)) { free(words); return NCAT_EBUDGET; }
    if (c->ncells == c->cap_cells) {
        if (c->cap_cells > INT32_MAX / 2) { free(words); return NCAT_ETOOBIG; }
        int32_t cap = c->cap_cells * 2;
        Cell *nc = realloc(c->cells, sizeof(Cell) * (size_t)cap);
        if (!nc) { free(words); return NCAT_ENOMEM; }
        c->cells = nc;
        c->cap_cells = cap;
    }
    int32_t *off = malloc(sizeof(int32_t) * (size_t)(n ? n : 1));
    if (!off) { free(words); return NCAT_ENOMEM; }
    for (int32_t i = 0, p = 0; i < n; i++) {
        off[i] = p;
        p += 4 + words[p + 2] + words[p + 3];
    }
    int32_t id = c->ncells++;
    Cell *cell = &c->cells[id];
    cell->formal = formal; cell->shape = shape; cell->n = n; cell->nwords = nwords;
    cell->words = words; cell->off = off; cell->hash = h;
    c->bytes_held += bytes;
    c->table[at] = id;
    if ((uint32_t)c->ncells * 2 > c->table_mask) {
        int r = grow_table(c);
        if (r < 0) return r;
    }
    return id;
}

/* ------------------------------------------------------------------ memo */

static int32_t memo_get(Ctx *c, int32_t a, int32_t b, int32_t k)
{
    uint64_t h = ((uint64_t)(uint32_t)a * 0x9E3779B97F4A7C15ULL) ^ ((uint64_t)(uint32_t)b * 0xC2B2AE3D27D4EB4FULL) ^ (uint64_t)(uint32_t)k;
    h ^= h >> 31;
    uint32_t at = (uint32_t)h & c->memo_mask;
    while (c->memo[at].a != -1) {
        if (c->memo[at].a == a && c->memo[at].b == b && c->memo[at].k == k) return c->memo[at].val;
        at = (at + 1) & c->memo_mask;
    }
    return INT32_MIN;
}

static int memo_put(Ctx *c, int32_t a, int32_t b, int32_t k, int32_t val)
{
    if ((c->memo_used + 1) * 2 > c->memo_mask) {
        if (c->memo_mask >= NCAT_MASK_MAX) return 0;  /* a memo at its largest only forgets; the answer stands */
        uint32_t cap = (c->memo_mask + 1) * 2;
        if (over_budget(c, (int64_t)cap * (int64_t)sizeof(MemoSlot))) return 0;  /* a full memo only forgets; the answer stands */
        MemoSlot *m = malloc(sizeof(MemoSlot) * cap);
        if (!m) return NCAT_ENOMEM;
        for (uint32_t i = 0; i < cap; i++) m[i].a = -1;
        MemoSlot *old = c->memo;
        uint32_t oldcap = c->memo_mask + 1;
        c->memo = m;
        c->memo_mask = cap - 1;
        c->memo_used = 0;
        for (uint32_t i = 0; i < oldcap; i++)
            if (old[i].a != -1) memo_put(c, old[i].a, old[i].b, old[i].k, old[i].val);
        free(old);
    }
    uint64_t h = ((uint64_t)(uint32_t)a * 0x9E3779B97F4A7C15ULL) ^ ((uint64_t)(uint32_t)b * 0xC2B2AE3D27D4EB4FULL) ^ (uint64_t)(uint32_t)k;
    h ^= h >> 31;
    uint32_t at = (uint32_t)h & c->memo_mask;
    while (c->memo[at].a != -1) at = (at + 1) & c->memo_mask;
    c->memo[at].a = a; c->memo[at].b = b; c->memo[at].k = k; c->memo[at].val = val;
    c->memo_used++;
    return 0;
}

/* ------------------------------------------------------------------ hosts */

static void host_free(Host *h)
{
    free(h->dim); free(h->label); free(h->in_at); free(h->in_n); free(h->out_at); free(h->out_n); free(h->pool);
    memset(h, 0, sizeof(*h));
}

static int host_init(Host *h, int32_t cap, int32_t pool_cap)
{
    memset(h, 0, sizeof(*h));
    if (cap < 1) cap = 1;
    if (pool_cap < 1) pool_cap = 1;
    h->cap = cap; h->pool_cap = pool_cap;
    h->dim = malloc(sizeof(int32_t) * (size_t)cap); h->label = malloc(sizeof(int32_t) * (size_t)cap);
    h->in_at = malloc(sizeof(int32_t) * (size_t)cap); h->in_n = malloc(sizeof(int32_t) * (size_t)cap);
    h->out_at = malloc(sizeof(int32_t) * (size_t)cap); h->out_n = malloc(sizeof(int32_t) * (size_t)cap);
    h->pool = malloc(sizeof(int32_t) * (size_t)pool_cap);
    if (!h->dim || !h->label || !h->in_at || !h->in_n || !h->out_at || !h->out_n || !h->pool) { host_free(h); return NCAT_ENOMEM; }
    return 0;
}

/* Adds a cell's elements. map[i] >= 0 means that element is already there as map[i]; map[i] < 0 means add it. On return
 * map[i] is each element's index in the host. */
static void host_load(Host *h, const Cell *c, int32_t *map)
{
    for (int32_t i = 0; i < c->n; i++)
        if (map[i] < 0) {
            const int32_t *w = c->words + c->off[i];
            map[i] = h->n;
            h->dim[h->n] = w[0]; h->label[h->n] = w[1];
            h->in_n[h->n] = 0; h->out_n[h->n] = 0; h->in_at[h->n] = 0; h->out_at[h->n] = 0;
            h->n++;
        }
    for (int32_t i = 0; i < c->n; i++) {
        const int32_t *w = c->words + c->off[i];
        int32_t e = map[i];
        if (h->in_n[e] || h->out_n[e] || w[2] + w[3] == 0) continue;  /* already has its faces, from the other side of a gluing */
        h->in_at[e] = h->pool_len; h->in_n[e] = w[2];
        for (int32_t j = 0; j < w[2]; j++) h->pool[h->pool_len++] = map[w[4 + j]];
        h->out_at[e] = h->pool_len; h->out_n[e] = w[3];
        for (int32_t j = 0; j < w[3]; j++) h->pool[h->pool_len++] = map[w[4 + w[2] + j]];
    }
}

/* ------------------------------------------------------------------ the traversal */


typedef struct {
    Ctx *c; const Host *h;
    int32_t N, D;
} Walk;

static uint64_t *uarr(Walk *w, int d, int which) { return w->c->scr_u + ((size_t)d * U_COUNT + (size_t)which) * (size_t)w->N; }
static int32_t *iarr(Walk *w, int d, int which) { return w->c->scr_i + ((size_t)d * I_COUNT + (size_t)which) * (size_t)w->N; }

static int walk_ready(Walk *w, const Host *h, int32_t D)
{
    Ctx *c = w->c;
    w->h = h; w->N = h->n > 0 ? h->n : 1; w->D = D + 2;
    if (c->scr_n < w->N || c->scr_d < w->D) {
        int32_t n = c->scr_n > w->N ? c->scr_n : w->N, dd = c->scr_d > w->D ? c->scr_d : w->D;
        /* the working space counts against the budget too, beside what's held */
        int64_t scratch = (int64_t)n * dd * (U_COUNT * (int64_t)sizeof(uint64_t) + I_COUNT * (int64_t)sizeof(int32_t));
        int64_t old = (int64_t)c->scr_n * c->scr_d * (U_COUNT * (int64_t)sizeof(uint64_t) + I_COUNT * (int64_t)sizeof(int32_t));
        if (over_budget(c, scratch - old)) return NCAT_EBUDGET;
        free(c->scr_u); free(c->scr_i);
        c->scr_u = calloc((size_t)n * (size_t)dd * U_COUNT, sizeof(uint64_t));
        c->scr_i = malloc(sizeof(int32_t) * (size_t)n * (size_t)dd * I_COUNT);
        c->scr_n = n; c->scr_d = dd;
        c->stamp = 0;
        if (!c->scr_u || !c->scr_i) { c->scr_n = 0; c->scr_d = 0; return NCAT_ENOMEM; }
    }
    w->N = c->scr_n;  /* the stride is the buffer's, so a smaller shape uses the same layout */
    w->D = c->scr_d;
    return 0;
}

/* Closes F and L under faces, into S at depth d. Returns its size. */
static int32_t closure(Walk *w, int d, const int32_t *F, int32_t nF, const int32_t *L, int32_t nL)
{
    const Host *h = w->h;
    int32_t *S = iarr(w, d, I_S);
    uint64_t *ms = uarr(w, d, U_MS);
    uint64_t st = ++w->c->stamp;
    int32_t n = 0;
    for (int32_t i = 0; i < nF; i++) if (ms[F[i]] != st) { ms[F[i]] = st; S[n++] = F[i]; }
    for (int32_t i = 0; i < nL; i++) if (ms[L[i]] != st) { ms[L[i]] = st; S[n++] = L[i]; }
    w->c->work += n;
    for (int32_t i = 0; i < n; i++) {   /* S doubles as the worklist */
        int32_t e = S[i];
        for (int32_t j = 0; j < h->in_n[e]; j++) { int32_t f = h->pool[h->in_at[e] + j]; if (ms[f] != st) { ms[f] = st; S[n++] = f; } }
        for (int32_t j = 0; j < h->out_n[e]; j++) { int32_t f = h->pool[h->out_at[e] + j]; if (ms[f] != st) { ms[f] = st; S[n++] = f; } }
    }
    return n;
}

/* The canonical order of the closed subset S at depth d, into seq at depth d. Every choice is forced by the shape: the input
 * boundary first, by the same rule one dimension down; then each top element, taking the one whose input comes earliest in
 * the current front's own order, and moving the front past it. Returns the length, or a negative error. */
static int32_t walk(Walk *w, int d, int32_t nS)
{
    const Host *h = w->h;
    const int32_t *S = iarr(w, d, I_S);
    int32_t *seq = iarr(w, d, I_SEQ);
    int32_t n = -1;
    for (int32_t i = 0; i < nS; i++) if (h->dim[S[i]] > n) n = h->dim[S[i]];
    if (n < 0) return 0;
    w->c->work += nS;
    if (w->c->work > w->c->work_limit) return NCAT_EWORK;
    if (n == 0) {
        if (nS != 1) return NCAT_EWALK;
        seq[0] = S[0];
        return 1;
    }
    if (d + 1 >= w->D) return NCAT_EWALK;
    uint64_t *face = uarr(w, d, U_FACE), *outm = uarr(w, d, U_OUT), *downst = uarr(w, d, U_DOWNST);
    uint64_t *infront = uarr(w, d, U_INFRONT), *seen = uarr(w, d, U_SEEN), *done = uarr(w, d, U_DONE);
    int32_t *down = iarr(w, d, I_DOWN), *F = iarr(w, d, I_F), *L = iarr(w, d, I_L);
    uint64_t st = ++w->c->stamp;
    int32_t tops = 0, nF = 0, nL = 0;
    for (int32_t i = 0; i < nS; i++) {
        int32_t e = S[i];
        for (int32_t j = 0; j < h->in_n[e]; j++) face[h->pool[h->in_at[e] + j]] = st;
        for (int32_t j = 0; j < h->out_n[e]; j++) face[h->pool[h->out_at[e] + j]] = st;
        if (h->dim[e] == n) {
            tops++;
            for (int32_t j = 0; j < h->out_n[e]; j++) {
                int32_t f = h->pool[h->out_at[e] + j];
                if (outm[f] == st) return NCAT_EWALK;  /* a molecule's facet has at most one coface of each sign */
                outm[f] = st;
            }
            for (int32_t j = 0; j < h->in_n[e]; j++) {
                int32_t f = h->pool[h->in_at[e] + j];
                if (downst[f] == st) return NCAT_EWALK;
                downst[f] = st; down[f] = e;
            }
        }
    }
    for (int32_t i = 0; i < nS; i++) {
        int32_t e = S[i];
        if (h->dim[e] == n - 1 && outm[e] != st) { F[nF++] = e; infront[e] = st; }
        else if (h->dim[e] < n - 1 && face[e] != st) L[nL++] = e;
    }
    int32_t cnt = walk(w, d + 1, closure(w, d + 1, F, nF, L, nL));
    if (cnt < 0) return cnt;
    const int32_t *front = iarr(w, d + 1, I_SEQ);
    int32_t ns = 0;
    for (int32_t i = 0; i < cnt; i++) { seen[front[i]] = st; seq[ns++] = front[i]; }
    while (tops > 0) {
        int32_t x = -1;
        for (int32_t i = 0; i < cnt && x < 0; i++) {
            int32_t f = front[i];
            if (h->dim[f] != n - 1 || infront[f] != st || downst[f] != st || done[down[f]] == st) continue;
            int32_t cand = down[f], ready = 1;
            for (int32_t j = 0; j < h->in_n[cand] && ready; j++) if (infront[h->pool[h->in_at[cand] + j]] != st) ready = 0;
            if (ready) x = cand;
        }
        if (x < 0) return NCAT_EWALK;
        done[x] = st; tops--;
        if (seen[x] != st) { seen[x] = st; seq[ns++] = x; }
        for (int32_t j = 0; j < h->in_n[x]; j++) infront[h->pool[h->in_at[x] + j]] = 0;
        int32_t kept = 0;
        for (int32_t i = 0; i < nF; i++) if (infront[F[i]] == st) F[kept++] = F[i];
        nF = kept;
        for (int32_t j = 0; j < h->out_n[x]; j++) {
            int32_t f = h->pool[h->out_at[x] + j];
            if (infront[f] == st) return NCAT_EWALK;
            infront[f] = st; F[nF++] = f;
        }
        if (w->c->work > w->c->work_limit) return NCAT_EWORK;
        cnt = walk(w, d + 1, closure(w, d + 1, F, nF, L, nL));
        if (cnt < 0) return cnt;
        for (int32_t i = 0; i < cnt; i++) if (seen[front[i]] != st) { seen[front[i]] = st; seq[ns++] = front[i]; }
    }
    return ns == nS ? ns : NCAT_EWALK;
}

static int cmp_i32(const void *a, const void *b) { int32_t x = *(const int32_t *)a, y = *(const int32_t *)b; return (x > y) - (x < y); }

/* Interns the closed subset of the host that S at depth 0 holds, with the given formal dimension. If order is non-NULL it
 * gets the elements in canonical order. */
static int32_t canon(Walk *w, int32_t nS, int32_t formal, int32_t *order)
{
    const Host *h = w->h;
    int32_t got = walk(w, 0, nS);
    if (got < 0) return got;
    const int32_t *seq = iarr(w, 0, I_SEQ);
    int32_t *pos = malloc(sizeof(int32_t) * (size_t)(h->n ? h->n : 1));
    if (!pos) return NCAT_ENOMEM;
    int64_t nwords = 0;
    int32_t shape = 0;
    for (int32_t i = 0; i < got; i++) {
        int32_t e = seq[i];
        pos[e] = i;
        nwords += 4 + h->in_n[e] + h->out_n[e];
        if (h->dim[e] > shape) shape = h->dim[e];
    }
    int32_t *words = malloc(sizeof(int32_t) * (size_t)(nwords ? nwords : 1));
    if (!words) { free(pos); return NCAT_ENOMEM; }
    int32_t p = 0;
    for (int32_t i = 0; i < got; i++) {
        int32_t e = seq[i];
        words[p++] = h->dim[e]; words[p++] = h->label[e]; words[p++] = h->in_n[e]; words[p++] = h->out_n[e];
        int32_t at = p;
        for (int32_t j = 0; j < h->in_n[e]; j++) words[p++] = pos[h->pool[h->in_at[e] + j]];
        qsort(words + at, (size_t)h->in_n[e], sizeof(int32_t), cmp_i32);
        at = p;
        for (int32_t j = 0; j < h->out_n[e]; j++) words[p++] = pos[h->pool[h->out_at[e] + j]];
        qsort(words + at, (size_t)h->out_n[e], sizeof(int32_t), cmp_i32);
    }
    if (order) memcpy(order, seq, sizeof(int32_t) * (size_t)got);
    free(pos);
    return intern(w->c, formal, shape, got, words, p);
}

static void host_all(Walk *w)
{
    int32_t *S = iarr(w, 0, I_S);
    for (int32_t i = 0; i < w->h->n; i++) S[i] = i;
}

/* The elements of the boundary, closed, into S at depth 0: the k-elements not on the other side of a (k+1)-element, and
 * every element below k with nothing above it. sign: -1 input, +1 output. */
static int32_t boundary_set(Walk *w, int32_t k, int sign)
{
    const Host *h = w->h;
    uint64_t *mark = uarr(w, 0, U_OUT), *face = uarr(w, 0, U_FACE);
    uint64_t st = ++w->c->stamp;
    int32_t *F = iarr(w, 0, I_F);
    int32_t *L = iarr(w, 0, I_L);
    int32_t nF = 0, nL = 0;
    for (int32_t e = 0; e < h->n; e++) {
        for (int32_t j = 0; j < h->in_n[e]; j++) face[h->pool[h->in_at[e] + j]] = st;
        for (int32_t j = 0; j < h->out_n[e]; j++) face[h->pool[h->out_at[e] + j]] = st;
        if (h->dim[e] == k + 1) {
            if (sign < 0) for (int32_t j = 0; j < h->out_n[e]; j++) mark[h->pool[h->out_at[e] + j]] = st;
            else for (int32_t j = 0; j < h->in_n[e]; j++) mark[h->pool[h->in_at[e] + j]] = st;
        }
    }
    for (int32_t e = 0; e < h->n; e++) {
        if (h->dim[e] == k && mark[e] != st) F[nF++] = e;
        else if (h->dim[e] < k && face[e] != st) L[nL++] = e;
    }
    /* closure() writes S at its depth, and reads F and L only until it has them. */
    return closure(w, 0, F, nF, L, nL);
}

static int host_of(Host *h, const Cell *a, int32_t extra, int32_t extra_pool, int32_t *map)
{
    int r = host_init(h, a->n + extra, a->nwords + extra_pool);
    if (r < 0) return r;
    for (int32_t i = 0; i < a->n; i++) map[i] = -1;
    host_load(h, a, map);
    return 0;
}

/* The boundary as a cell, and if order is given, its elements in canonical order as indices of the cell's own elements. */
static int32_t boundary_ordered(Ctx *c, int32_t a, int32_t k, int sign, int32_t *order, int32_t *norder)
{
    const Cell cell = c->cells[a];
    int32_t *map = malloc(sizeof(int32_t) * (size_t)(cell.n ? cell.n : 1));
    if (!map) return NCAT_ENOMEM;
    Host h;
    int r = host_of(&h, &cell, 0, 0, map);
    if (r < 0) { free(map); return r; }
    Walk w = { .c = c };
    r = walk_ready(&w, &h, cell.shape);
    int32_t id = r;
    if (r >= 0) {
        int32_t nS = boundary_set(&w, k, sign);
        id = canon(&w, nS, k, order);
        if (norder) *norder = nS;
    }
    host_free(&h);
    free(map);
    return id;
}

/* Steiner's loop-free condition, for every i: the relation a <_i b, when a's output i-boundary and b's input i-boundary share an
 * i-element, has no cycle. Where it holds the shape's free omega-category is generated freely by its atoms, so any way of
 * building the whole shape gives the one cell, and a labelled shape determines its cell. Dimensions 2 and below always hold it,
 * and tests assert that dimension 3 has done so. Returns 1, 0, or a negative error. */
static int loop_free(Ctx *ctx, const Host *h)
{
    int32_t top = 0;
    for (int32_t e = 0; e < h->n; e++) if (h->dim[e] > top) top = h->dim[e];
    if (top < 3) return 1;
    size_t cap_edges = 1024;
    int32_t *from = malloc(sizeof(int32_t) * cap_edges), *to = malloc(sizeof(int32_t) * cap_edges);
    int32_t *cl = malloc(sizeof(int32_t) * (size_t)h->n), *indeg = malloc(sizeof(int32_t) * (size_t)h->n);
    int32_t *head = malloc(sizeof(int32_t) * (size_t)h->n), *queue = malloc(sizeof(int32_t) * (size_t)h->n);
    int32_t *nextedge = NULL;
    uint64_t *in_cl = calloc((size_t)h->n, sizeof(uint64_t)), *not_in = calloc((size_t)h->n, sizeof(uint64_t)), *not_out = calloc((size_t)h->n, sizeof(uint64_t));
    int result = (from && to && cl && indeg && head && queue && in_cl && not_in && not_out) ? 1 : NCAT_ENOMEM;
    uint64_t st = 0;
    for (int32_t i = 0; i < top && result == 1; i++) {
        size_t nedges = 0;
        for (int32_t x = 0; x < h->n && result == 1; x++) {
            if (h->dim[x] <= i) continue;
            int32_t ncl = 0;
            st++;
            in_cl[x] = st; cl[ncl++] = x;
            for (int32_t c = 0; c < ncl; c++) {
                int32_t e = cl[c];
                for (int32_t j = 0; j < h->in_n[e]; j++) { int32_t f = h->pool[h->in_at[e] + j]; if (in_cl[f] != st) { in_cl[f] = st; cl[ncl++] = f; } }
                for (int32_t j = 0; j < h->out_n[e]; j++) { int32_t f = h->pool[h->out_at[e] + j]; if (in_cl[f] != st) { in_cl[f] = st; cl[ncl++] = f; } }
            }
            ctx->work += ncl;  /* the closure just walked, which also bounds the edges it adds below */
            if (ctx->work > ctx->work_limit) { result = NCAT_EWORK; break; }
            for (int32_t c = 0; c < ncl; c++) {
                int32_t e = cl[c];
                if (h->dim[e] != i + 1) continue;
                for (int32_t j = 0; j < h->in_n[e]; j++) not_out[h->pool[h->in_at[e] + j]] = st;   /* an input of something: not on the output side */
                for (int32_t j = 0; j < h->out_n[e]; j++) not_in[h->pool[h->out_at[e] + j]] = st;  /* an output of something: not on the input side */
            }
            for (int32_t c = 0; c < ncl; c++) {
                int32_t e = cl[c];
                if (h->dim[e] != i) continue;
                if (nedges + 2 > cap_edges) {
                    if (cap_edges > (size_t)INT32_MAX / 2) { result = NCAT_ETOOBIG; break; }  /* head and nextedge index edges as int32 */
                    /* both arrays at their new size, whole: they're the call's own, beside what the category holds */
                    if (over_budget(ctx, (int64_t)cap_edges * 2 * 2 * (int64_t)sizeof(int32_t))) { result = NCAT_EBUDGET; break; }
                    cap_edges *= 2;
                    int32_t *nf = realloc(from, sizeof(int32_t) * cap_edges), *nt = realloc(to, sizeof(int32_t) * cap_edges);
                    if (nf) from = nf;
                    if (nt) to = nt;
                    if (!nf || !nt) { result = NCAT_ENOMEM; break; }
                }
                if (not_out[e] != st) { from[nedges] = x; to[nedges] = e; nedges++; }  /* x, then what's on its output */
                if (not_in[e] != st) { from[nedges] = e; to[nedges] = x; nedges++; }   /* what's on x's input, then x */
            }
        }
        if (result != 1) break;
        /* Kahn's algorithm over elements and i-elements together: a cycle here is a cycle of <_i. */
        free(nextedge);
        nextedge = malloc(sizeof(int32_t) * (nedges ? nedges : 1));
        if (!nextedge) { result = NCAT_ENOMEM; break; }
        for (int32_t e = 0; e < h->n; e++) { indeg[e] = 0; head[e] = -1; }
        for (size_t m = 0; m < nedges; m++) {
            nextedge[m] = head[from[m]];
            head[from[m]] = (int32_t)m;
            indeg[to[m]]++;
        }
        int32_t qh = 0, qt = 0, seen = 0;
        for (int32_t e = 0; e < h->n; e++) if (indeg[e] == 0) queue[qt++] = e;
        while (qh < qt) {
            int32_t e = queue[qh++];
            seen++;
            for (int32_t m = head[e]; m >= 0; m = nextedge[m]) if (--indeg[to[m]] == 0) queue[qt++] = to[m];
        }
        if (seen != h->n) result = 0;
    }
    free(from); free(to); free(cl); free(indeg); free(head); free(queue); free(nextedge); free(in_cl); free(not_in); free(not_out);
    return result;
}

/* ------------------------------------------------------------------ the public kernel */

Ctx *ncat_new(void)
{
    Ctx *c = calloc(1, sizeof(Ctx));
    if (!c) return NULL;
    c->cap_cells = 64;
    c->cells = malloc(sizeof(Cell) * 64);
    c->table = malloc(sizeof(int32_t) * 256);
    c->table_mask = 255;
    c->memo = malloc(sizeof(MemoSlot) * 256);
    c->memo_mask = 255;
    if (!c->cells || !c->table || !c->memo) { free(c->cells); free(c->table); free(c->memo); free(c); return NULL; }
    memset(c->table, 0xff, sizeof(int32_t) * 256);
    for (int i = 0; i < 256; i++) c->memo[i].a = -1;
    c->bytes_budget = (int64_t)1 << 30;  /* 1 GiB; ncat_set_budget changes it */
    c->work_limit = (int64_t)1 << 30;    /* steps per call; ncat_set_work changes it */
    return c;
}

void ncat_free(Ctx *c)
{
    if (!c) return;
    for (int32_t i = 0; i < c->ncells; i++) { free(c->cells[i].words); free(c->cells[i].off); }
    free(c->cells); free(c->table); free(c->memo); free(c->scr_u); free(c->scr_i); free(c);
}

int32_t ncat_formal(Ctx *c, int32_t a) { return a >= 0 && a < c->ncells ? c->cells[a].formal : NCAT_EARG; }
int32_t ncat_shape(Ctx *c, int32_t a) { return a >= 0 && a < c->ncells ? c->cells[a].shape : NCAT_EARG; }
int32_t ncat_size(Ctx *c, int32_t a) { return a >= 0 && a < c->ncells ? c->cells[a].n : NCAT_EARG; }
int32_t ncat_ncells(Ctx *c) { return c->ncells; }
int64_t ncat_held(Ctx *c) { return c->bytes_held + fixed_bytes(c); }
int32_t ncat_set_budget(Ctx *c, int64_t bytes) { if (bytes < 0) return NCAT_EARG; c->bytes_budget = bytes; return 0; }
int32_t ncat_set_work(Ctx *c, int64_t steps) { if (steps < 1) return NCAT_EARG; c->work_limit = steps; return 0; }
int32_t ncat_ngens(Ctx *c) { return c->ngens; }

/* The canonical words, so the host can address a cell by what it is. Returns how many; copies at most cap. */
int32_t ncat_words(Ctx *c, int32_t a, int32_t *buf, int32_t cap)
{
    if (a < 0 || a >= c->ncells || cap < 0 || (cap > 0 && !buf)) return NCAT_EARG;
    const Cell *cell = &c->cells[a];
    if (buf) memcpy(buf, cell->words, sizeof(int32_t) * (size_t)(cell->nwords < cap ? cell->nwords : cap));
    return cell->nwords;
}

static int32_t boundary_in(Ctx *c, int32_t a, int32_t k, int32_t sign)
{
    if (a < 0 || a >= c->ncells || k < 0 || k > NCAT_MAX_DIM || (sign != -1 && sign != 1)) return NCAT_EARG;
    if (k >= c->cells[a].formal) return a;
    int32_t key_a = a, key_b = -2 - sign, got = memo_get(c, key_a, key_b, k);
    if (got != INT32_MIN) return got;
    int32_t id = boundary_ordered(c, a, k, sign, NULL, NULL);
    if (id >= 0) { int r = memo_put(c, key_a, key_b, k, id); if (r < 0) return r; }
    return id;
}

/* The same shape, one formal dimension up. */
int32_t ncat_identity(Ctx *c, int32_t a)
{
    if (a < 0 || a >= c->ncells) return NCAT_EARG;
    if (c->cells[a].formal >= NCAT_MAX_DIM) return NCAT_EARG;
    const Cell *cell = &c->cells[a];
    int32_t *words = malloc(sizeof(int32_t) * (size_t)(cell->nwords ? cell->nwords : 1));
    if (!words) return NCAT_ENOMEM;
    memcpy(words, cell->words, sizeof(int32_t) * (size_t)cell->nwords);
    return intern(c, cell->formal + 1, cell->shape, cell->n, words, cell->nwords);
}

static int32_t with_formal(Ctx *c, int32_t a, int32_t formal)
{
    while (a >= 0 && c->cells[a].formal < formal) a = ncat_identity(c, a);
    return a;
}

/* a then b, along their k-boundary. Defined exactly when a's output k-boundary is b's input k-boundary. */
static int32_t compose_in(Ctx *c, int32_t a, int32_t b, int32_t k)
{
    if (a < 0 || a >= c->ncells || b < 0 || b >= c->ncells || k < 0 || k > NCAT_MAX_DIM) return NCAT_EARG;
    int32_t got = memo_get(c, a, b, k);
    if (got != INT32_MIN) return got;
    Cell A = c->cells[a], B = c->cells[b];
    int32_t formal = A.formal > B.formal ? A.formal : B.formal;
    int32_t ba = A.formal > k ? boundary_in(c, a, k, 1) : with_formal(c, a, k);
    int32_t bb = B.formal > k ? boundary_in(c, b, k, -1) : with_formal(c, b, k);
    if (ba < 0) return ba;
    if (bb < 0) return bb;
    /* compare at formal dimension k: a cell shorter than k has been raised to it, a cell whose shape is shorter still matches by shape */
    if (ba != bb) return NCAT_ENOTCOMPOSABLE;
    A = c->cells[a]; B = c->cells[b];
    int32_t id;
    if (A.shape <= k) id = with_formal(c, b, formal);       /* a is all boundary: a unit */
    else if (B.shape <= k) id = with_formal(c, a, formal);  /* b is all boundary: a unit */
    else if ((int64_t)A.n + B.n > NCAT_MAX_ELEMENTS || (int64_t)A.nwords + B.nwords > NCAT_MAX_WORDS) id = NCAT_ETOOBIG;
    else {
        int32_t *oa = malloc(sizeof(int32_t) * (size_t)A.n), *ob = malloc(sizeof(int32_t) * (size_t)B.n);
        int32_t *mapa = malloc(sizeof(int32_t) * (size_t)A.n), *mapb = malloc(sizeof(int32_t) * (size_t)B.n);
        Host h; memset(&h, 0, sizeof(h));
        id = NCAT_ENOMEM;
        if (oa && ob && mapa && mapb) {
            int32_t na = 0, nb = 0;
            int32_t r1 = boundary_ordered(c, a, k, 1, oa, &na);
            int32_t r2 = r1 < 0 ? r1 : boundary_ordered(c, b, k, -1, ob, &nb);
            A = c->cells[a]; B = c->cells[b];
            if (r1 < 0 || r2 < 0) id = r1 < 0 ? r1 : r2;
            else if (na != nb) id = NCAT_EWALK;
            else if (host_init(&h, A.n + B.n, A.nwords + B.nwords) == 0) {
                /* boundary_ordered worked on a host whose index i is element i of the cell, so these are element indices */
                for (int32_t i = 0; i < A.n; i++) mapa[i] = -1;
                host_load(&h, &A, mapa);
                for (int32_t i = 0; i < B.n; i++) mapb[i] = -1;
                for (int32_t i = 0; i < nb; i++) mapb[ob[i]] = mapa[oa[i]];
                host_load(&h, &B, mapb);
                int lf = loop_free(c, &h);
                if (lf < 0) id = lf;
                else if (!lf) id = NCAT_ENOTLOOPFREE;
                else {
                    Walk w = { .c = c };
                    id = walk_ready(&w, &h, A.shape > B.shape ? A.shape : B.shape);
                    if (id >= 0) { host_all(&w); id = canon(&w, h.n, formal, NULL); }
                }
            }
        }
        host_free(&h);
        free(oa); free(ob); free(mapa); free(mapb);
    }
    if (id >= 0) { int r = memo_put(c, a, b, k, id); if (r < 0) return r; }
    return id;
}

/* Is the cell round: at each dimension j below its top, do its two j-boundaries meet only in its (j-1)-boundary? And pure? */
static int is_round(Ctx *c, int32_t s)
{
    const Cell cell = c->cells[s];
    int32_t *map = malloc(sizeof(int32_t) * (size_t)cell.n);
    if (!map) return NCAT_ENOMEM;
    Host h;
    int r = host_of(&h, &cell, 0, 0, map);
    if (r < 0) { free(map); return r; }
    Walk w = { .c = c };
    r = walk_ready(&w, &h, cell.shape);
    uint8_t *m = calloc((size_t)h.n * 4, 1);  /* membership: in-, out-, previous in-, previous out- */
    int round = r < 0 ? r : (m ? 1 : NCAT_ENOMEM);
    if (round == 1) {
        for (int32_t x = 0; x < h.n; x++) {   /* every lower element is a face of something: purity */
            for (int32_t j = 0; j < h.in_n[x]; j++) m[(size_t)h.pool[h.in_at[x] + j] * 4] = 1;
            for (int32_t j = 0; j < h.out_n[x]; j++) m[(size_t)h.pool[h.out_at[x] + j] * 4] = 1;
        }
        for (int32_t e = 0; e < h.n; e++) {
            if (h.dim[e] < cell.shape && !m[(size_t)e * 4]) round = 0;
            m[(size_t)e * 4] = 0;
        }
        for (int32_t j = 0; j < cell.shape && round == 1; j++) {
            for (int side = 0; side < 2; side++) {
                int32_t nS = boundary_set(&w, j, side ? 1 : -1);
                const int32_t *S = iarr(&w, 0, I_S);
                for (int32_t e = 0; e < h.n; e++) m[(size_t)e * 4 + (size_t)side] = 0;
                for (int32_t i = 0; i < nS; i++) m[(size_t)S[i] * 4 + (size_t)side] = 1;
            }
            for (int32_t e = 0; e < h.n && round == 1; e++)
                if (m[(size_t)e * 4] && m[(size_t)e * 4 + 1] && !(j > 0 && (m[(size_t)e * 4 + 2] || m[(size_t)e * 4 + 3]))) round = 0;
            for (int32_t e = 0; e < h.n; e++) {
                m[(size_t)e * 4 + 2] = m[(size_t)e * 4];
                m[(size_t)e * 4 + 3] = m[(size_t)e * 4 + 1];
            }
        }
    }
    free(m);
    host_free(&h);
    free(map);
    return round;
}

/* A new 0-cell when s and t are both -1. Otherwise a new d-cell from s to t, which must be parallel (d-1)-cells, not
 * identities, and round. Returns the generator as a cell. */
static int32_t gen_in(Ctx *c, int32_t s, int32_t t)
{
    int32_t g = c->ngens;
    if (s == -1 && t == -1) {
        int32_t *words = malloc(sizeof(int32_t) * 4);
        if (!words) return NCAT_ENOMEM;
        words[0] = 0; words[1] = g; words[2] = 0; words[3] = 0;
        int32_t id = intern(c, 0, 0, 1, words, 4);
        if (id >= 0) c->ngens++;
        return id;
    }
    if (s < 0 || s >= c->ncells || t < 0 || t >= c->ncells) return NCAT_EARG;
    Cell S = c->cells[s], T = c->cells[t];
    int32_t m = S.formal, d = m + 1;
    if (T.formal != m || d > NCAT_MAX_DIM) return NCAT_ENOTPARALLEL;
    if (S.shape != m || T.shape != m) return NCAT_EDEGENERATE;
    if (m >= 1) {
        for (int sign = -1; sign <= 1; sign += 2) {
            int32_t bs = boundary_in(c, s, m - 1, sign), bt = boundary_in(c, t, m - 1, sign);
            if (bs < 0) return bs;
            if (bt < 0) return bt;
            if (bs != bt) return NCAT_ENOTPARALLEL;
        }
        int rs = is_round(c, s);
        if (rs < 0) return rs;
        if (!rs) return NCAT_ENOTROUND;
        int rt = is_round(c, t);
        if (rt < 0) return rt;
        if (!rt) return NCAT_ENOTROUND;
    }
    S = c->cells[s]; T = c->cells[t];
    int32_t *ms = malloc(sizeof(int32_t) * (size_t)S.n), *mt = malloc(sizeof(int32_t) * (size_t)T.n);
    int32_t *os = malloc(sizeof(int32_t) * (size_t)S.n), *ot = malloc(sizeof(int32_t) * (size_t)T.n);
    int32_t id = NCAT_ENOMEM;
    Host h; memset(&h, 0, sizeof(h));
    if (ms && mt && os && ot && host_init(&h, S.n + T.n + 1, S.nwords + T.nwords + S.n + T.n) == 0) {
        for (int32_t i = 0; i < S.n; i++) ms[i] = -1;
        host_load(&h, &S, ms);
        for (int32_t i = 0; i < T.n; i++) mt[i] = -1;
        id = 0;
        if (m >= 1) {
            for (int sign = -1; sign <= 1 && id >= 0; sign += 2) {
                int32_t ns = 0, nt = 0;
                int32_t r1 = boundary_ordered(c, s, m - 1, sign, os, &ns);
                int32_t r2 = r1 < 0 ? r1 : boundary_ordered(c, t, m - 1, sign, ot, &nt);
                if (r1 < 0 || r2 < 0) id = r1 < 0 ? r1 : r2;
                else if (ns != nt) id = NCAT_EWALK;
                else for (int32_t i = 0; i < nt; i++) {
                    if (mt[ot[i]] >= 0 && mt[ot[i]] != ms[os[i]]) { id = NCAT_EWALK; break; }
                    mt[ot[i]] = ms[os[i]];
                }
            }
            S = c->cells[s]; T = c->cells[t];
        }
        if (id >= 0) {
            host_load(&h, &T, mt);
            int32_t x = h.n++;
            h.dim[x] = d; h.label[x] = g;
            h.in_at[x] = h.pool_len; h.in_n[x] = 0;
            for (int32_t i = 0; i < S.n; i++) if (S.words[S.off[i]] == m) { h.pool[h.pool_len++] = ms[i]; h.in_n[x]++; }
            h.out_at[x] = h.pool_len; h.out_n[x] = 0;
            for (int32_t i = 0; i < T.n; i++) if (T.words[T.off[i]] == m) { h.pool[h.pool_len++] = mt[i]; h.out_n[x]++; }
            int lf = loop_free(c, &h);
            if (lf < 0) id = lf;
            else if (!lf) id = NCAT_ENOTLOOPFREE;
            else {
                Walk w = { .c = c };
                id = walk_ready(&w, &h, d);
                if (id >= 0) { host_all(&w); id = canon(&w, h.n, d, NULL); }
            }
            if (id >= 0) c->ngens++;
        }
    }
    host_free(&h);
    free(ms); free(mt); free(os); free(ot);
    return id;
}

/* The public calls: each starts its own count of work, so one call can't run unbounded, and one that stops early has changed
 * nothing but the memo of what it finished. */
int32_t ncat_boundary(Ctx *c, int32_t a, int32_t k, int32_t sign) { c->work = 0; return boundary_in(c, a, k, sign); }
int32_t ncat_compose(Ctx *c, int32_t a, int32_t b, int32_t k) { c->work = 0; return compose_in(c, a, b, k); }
int32_t ncat_gen(Ctx *c, int32_t s, int32_t t) { c->work = 0; return gen_in(c, s, t); }
