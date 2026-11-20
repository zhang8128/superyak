/* The sheaf kernel checked against itself, with no Python and no numpy, so it can run under the address and
 * undefined-behaviour sanitizers (tests/test_sheaf_kernel.py builds and runs it that way). It prints one line and exits 0,
 * or says what failed and exits 1. The kernel is included, not linked, so its static functions are under the sanitizers too. */
#include "../sheaf_kernel.c"

#include <stdio.h>

static uint64_t state = 0x9E3779B97F4A7C15ull;
static int checks = 0;

static double uniform(void) {  /* in [0, 1) */
    state = state * 6364136223846793005ull + 1442695040888963407ull;
    return (double)(state >> 11) / 9007199254740992.0;
}

static double noise(void) { return 2.0 * uniform() - 1.0; }

#define CHECK(cond, ...)                                    \
    do {                                                    \
        checks++;                                           \
        if (!(cond)) {                                      \
            fprintf(stderr, "line %d: ", __LINE__);         \
            fprintf(stderr, __VA_ARGS__);                   \
            fprintf(stderr, "\n");                          \
            exit(1);                                        \
        }                                                   \
    } while (0)

static void check_eig(int32_t n) {
    double *a = dalloc((int64_t)n * n), *w = dalloc(n), *v = dalloc((int64_t)n * n);
    CHECK(a && w && v, "out of memory");
    for (int32_t i = 0; i < n; i++)
        for (int32_t j = 0; j <= i; j++) a[(int64_t)i * n + j] = a[(int64_t)j * n + i] = noise();
    CHECK(sheaf_sym_eig(n, a, w, v) == 0, "eig of %d refused", n);
    for (int32_t i = 1; i < n; i++) CHECK(w[i - 1] <= w[i], "eigenvalues of %d out of order", n);
    double worst = 0.0, loose = 0.0;
    for (int32_t i = 0; i < n; i++)
        for (int32_t j = 0; j < n; j++) {
            double back = 0.0, gram = 0.0;
            for (int32_t c = 0; c < n; c++) {
                back += v[(int64_t)i * n + c] * w[c] * v[(int64_t)j * n + c];
                gram += v[(int64_t)c * n + i] * v[(int64_t)c * n + j];
            }
            if (fabs(back - a[(int64_t)i * n + j]) > worst) worst = fabs(back - a[(int64_t)i * n + j]);
            if (fabs(gram - (i == j)) > loose) loose = fabs(gram - (i == j));
        }
    CHECK(worst < 1e-10 * n && loose < 1e-10 * n, "eig of %d: rebuilt to %g, orthonormal to %g", n, worst, loose);
    free(a);
    free(w);
    free(v);
}

static void check_basis(int32_t n, int32_t d, int rank_one, int zero) {
    int32_t kmax = 8, k = 0, r = n < d ? n : d;
    double *x = dalloc((int64_t)n * d), *rows = dalloc((int64_t)kmax * d), *sing = dalloc(r);
    CHECK(x && rows && sing, "out of memory");
    for (int32_t i = 0; i < n; i++)
        for (int32_t c = 0; c < d; c++)
            x[(int64_t)i * d + c] = zero ? 0.0 : (rank_one ? (double)(c + 1) : noise() / (1.0 + c));
    CHECK(sheaf_basis(n, d, x, 0.9, 2, kmax, rows, sing, &k) == 0, "basis of %d by %d refused", n, d);
    CHECK(k >= 1 && k <= kmax && k <= r && (k >= 2 || r < 2), "basis of %d by %d kept %d", n, d, k);
    for (int32_t i = 1; i < r; i++) CHECK(sing[i - 1] >= sing[i] && sing[i] >= 0, "singular values out of order");
    for (int32_t a = 0; a < k; a++)
        for (int32_t b = 0; b <= a; b++) {
            double g = dot(rows + (int64_t)a * d, rows + (int64_t)b * d, d);
            CHECK(fabs(g - (a == b)) < 1e-9, "basis rows %d and %d of %d by %d: %g", a, b, n, d, g);
        }
    free(x);
    free(rows);
    free(sing);
}

static void check_cohesion(int32_t n, int32_t d, int clusters, int32_t max_worst) {
    double *x = dalloc((int64_t)n * d), *f = dalloc(n), wr[64], energy = -1, lam = -1;
    int32_t wi[64], wj[64], k = 0, kept = -1;
    CHECK(x && f, "out of memory");
    for (int32_t i = 0; i < n; i++)
        for (int32_t c = 0; c < d; c++)
            x[(int64_t)i * d + c] = 0.3 * noise() + ((c % clusters) == (i % clusters) ? 1.0 : 0.0);
    int32_t rc = sheaf_cohesion(n, d, x, 0.9, 8, &energy, &lam, f, &k, max_worst, wi, wj, wr, &kept);
    CHECK(rc == (n < 3 ? 1 : 0) || rc == 2, "cohesion of %d by %d gave %d", n, d, rc);
    CHECK(energy >= 0.0 && energy <= 1.0, "energy %g", energy);
    int32_t pairs = n * (n - 1) / 2;
    if (rc == 0) {
        CHECK(kept == (max_worst < pairs ? max_worst : pairs), "kept %d of %d pairs, room for %d", kept, pairs, max_worst);
        for (int32_t t = 0; t < kept; t++) {
            CHECK(wi[t] >= 0 && wi[t] < wj[t] && wj[t] < n, "a worst pair out of range");
            CHECK(t == 0 || wr[t - 1] >= wr[t], "worst pairs out of order");
        }
    } else {
        CHECK(kept == 0, "a trivial answer kept %d pairs", kept);
    }
    free(x);
    free(f);
}

static void check_isolated(void) {  /* one episode pointing the other way has no similarity left to anyone */
    enum { n = 5, d = 4 };
    double x[n * d] = {0}, f[n], energy, lam;
    int32_t k, kept;
    for (int32_t i = 0; i < n; i++) x[i * d] = i == 3 ? -1.0 : 1.0;
    CHECK(sheaf_cohesion(n, d, x, 0.9, 8, &energy, &lam, f, &k, 0, NULL, NULL, NULL, &kept) == 2, "not seen as isolated");
    CHECK(energy == 1.0 && lam == 0.0 && f[3] == 1.0 && f[0] == -1.0, "isolated answer wrong");
}

/* A cycle of n vertices with stalk R^d everywhere and identity maps, but minus the identity on one end of the last
 * edge when twisted. Untwisted it has H^0 = H^1 = d; twisted it has neither. */
static void check_cycle(int32_t n, int32_t d, int twisted) {
    int32_t dims[64], h0 = -1, h1 = -1;
    double minus[SHEAF_MAX_STALK * 8] = {0};
    for (int32_t i = 0; i < n; i++) dims[i] = d;
    for (int32_t i = 0; i < d; i++) minus[i * d + i] = -1.0;
    void *s = sheaf_new(n, dims);
    CHECK(s, "no sheaf");
    for (int32_t i = 0; i < n; i++) {
        int last = i == n - 1;
        CHECK(sheaf_add_edge(s, i, (i + 1) % n, d, NULL, twisted && last ? minus : NULL, 1.0 + i) == i, "edge refused");
    }
    CHECK(sheaf_sections(s, 1e-9, &h0, &h1, NULL, NULL, NULL) == 0, "sections refused");
    CHECK(h0 == (twisted ? 0 : d) && h1 == (twisted ? 0 : d), "cycle %d of R^%d twisted %d: h0 %d h1 %d", n, d, twisted, h0, h1);
    sheaf_free(s);
}

/* Random stalks, maps and weights: x'Lx equals the energy, the nearest global section has none, and it is its own. */
static void check_random_sheaf(int32_t nv, int32_t ne) {
    int32_t dims[32], n0 = 0, n1 = 0, edges = 0, h0, h1;
    double mu[SHEAF_MAX_STALK], mv[SHEAF_MAX_STALK];
    for (int32_t i = 0; i < nv; i++) dims[i] = 1 + (int32_t)(uniform() * 4);
    void *s = sheaf_new(nv, dims);
    CHECK(s, "no sheaf");
    for (int32_t e = 0; e < ne; e++) {
        int32_t u = (int32_t)(uniform() * nv), v = (int32_t)(uniform() * nv), dim = 1 + (int32_t)(uniform() * 3);
        if (u == v) continue;
        for (int32_t i = 0; i < dim * dims[u]; i++) mu[i] = noise();
        for (int32_t i = 0; i < dim * dims[v]; i++) mv[i] = noise();
        double w = e % 5 == 0 ? 0.0 : uniform();
        CHECK(sheaf_add_edge(s, u, v, dim, mu, mv, w) >= 0, "edge refused");
    }
    CHECK(sheaf_dims(s, &n0, &n1, &edges) == 0, "dims refused");
    double *x = dalloc(n0), *near = dalloc(n0), *L = dalloc((int64_t)n0 * n0), *dx = dalloc(n1 + 1), *res = dalloc(edges + 1);
    CHECK(x && near && L && dx && res, "out of memory");
    for (int32_t i = 0; i < n0; i++) x[i] = noise();
    double energy = 0, quad = 0, harmonic = -1, after = -1, again = -1;
    CHECK(sheaf_energy(s, x, &energy, res) == 0 && sheaf_laplacian(s, L) == 0 && sheaf_coboundary(s, x, dx) == 0, "refused");
    for (int32_t i = 0; i < n0; i++)
        for (int32_t j = 0; j < n0; j++) quad += x[i] * L[(int64_t)i * n0 + j] * x[j];
    CHECK(fabs(quad - energy) < 1e-9 * (1.0 + energy), "x'Lx %g but the energy is %g", quad, energy);
    CHECK(sheaf_sections(s, 1e-9, &h0, &h1, x, near, &harmonic) == 0, "sections refused");
    CHECK(h0 >= 0 && h0 <= n0 && h1 >= 0 && harmonic >= -1e-12 && harmonic <= 1.0 + 1e-12, "h0 %d h1 %d harmonic %g", h0, h1, harmonic);
    CHECK(sheaf_energy(s, near, &after, NULL) == 0 && after < 1e-7 * (1.0 + energy), "the nearest section has energy %g", after);
    CHECK(sheaf_sections(s, 1e-9, &h0, &h1, near, x, &again) == 0 && again < 1e-9, "a section is %g outside the sections", again);
    CHECK(sheaf_sections(s, 0.0, &h0, &h1, NULL, NULL, NULL) == 0 && h1 >= 0 && h0 >= 0, "at no tolerance: h0 %d h1 %d", h0, h1);
    free(x);
    free(near);
    free(L);
    free(dx);
    free(res);
    sheaf_free(s);
}

static void check_glue(int32_t m, int32_t d, int same) {
    int32_t counts[16], zeroed[16], total = 0, kmax = 8, pairs = m * (m - 1) / 2;
    double trust[16];
    for (int32_t i = 0; i < m; i++) {
        counts[i] = 1 + (int32_t)(uniform() * 5);
        total += counts[i];
        trust[i] = uniform();
    }
    double *hits = dalloc((int64_t)total * d), *w = dalloc(total), *rows = dalloc((int64_t)kmax * d);
    double *stalks = dalloc((int64_t)m * kmax), off[16], dev[16], cons[8], *res = dalloc(pairs + 1), *ew = dalloc(pairs + 1);
    CHECK(hits && w && rows && stalks && res && ew, "out of memory");
    for (int32_t i = 0, row = 0; i < m; i++)
        for (int32_t h = 0; h < counts[i]; h++, row++) {
            double norm = 0.0;
            for (int32_t c = 0; c < d; c++) {
                double v = (c == (same ? 0 : i % d) ? 1.0 : 0.0) + (same ? 0.0 : 0.2 * noise());
                hits[(int64_t)row * d + c] = v;
                norm += v * v;
            }
            for (int32_t c = 0; c < d; c++) hits[(int64_t)row * d + c] /= sqrt(norm);
            w[row] = uniform() - 0.1;  /* some negative: they count as nothing */
        }
    SheafGlue out;
    memset(&out, 0, sizeof out);
    int32_t rc = sheaf_glue(m, d, counts, hits, w, trust, m % 2, 0.9, kmax, &out, rows, stalks, off, zeroed, res, ew, cons, dev);
    CHECK(rc == 0, "glue of %d stores refused: %d", m, rc);
    CHECK(out.k >= 1 && out.k <= kmax && out.energy >= 0 && out.energy <= 1 && out.harmonic >= 0 && out.harmonic <= 1, "glue out of range");
    CHECK(out.glued_dim >= 0 && out.glued_dim <= out.k && out.kernel_dim >= 0 && out.kernel_dim <= m * out.k, "glue dimensions");
    if (same) CHECK(out.energy_unweighted < 1e-12 && out.glued_dim == out.k, "identical stores: energy %g, glued %d of %d", out.energy_unweighted, out.glued_dim, out.k);
    for (int32_t e = 0; e < pairs; e++) CHECK(res[e] >= 0 && res[e] <= 4.0 + 1e-9, "a residual of %g", res[e]);
    free(hits);
    free(w);
    free(rows);
    free(stalks);
    free(res);
    free(ew);
}

static void check_refusals(void) {
    double a[4] = {1, 2, 2, 1}, w[2], v[4], bad[4] = {1, NAN, 2, 1}, far[4] = {1, 1e200, 1e200, 1}, inf[4] = {INFINITY, 0, 0, 1};
    double rows[16], sing[2], energy, lam, f[2];
    int32_t k, kept, dims[2] = {2, 2}, big[1] = {SHEAF_MAX_STALK + 1}, h0, h1;
    CHECK(sheaf_sym_eig(0, a, w, v) == SHEAF_EARG && sheaf_sym_eig(-3, a, w, v) == SHEAF_EARG, "a size under 1");
    CHECK(sheaf_sym_eig(2, NULL, w, v) == SHEAF_EARG && sheaf_sym_eig(2, a, NULL, v) == SHEAF_EARG, "a missing buffer");
    CHECK(sheaf_sym_eig(SHEAF_MAX_N + 1, a, w, v) == SHEAF_ETOOBIG, "a size over the limit");
    CHECK(sheaf_sym_eig(2, bad, w, v) == SHEAF_EARG && sheaf_sym_eig(2, far, w, v) == SHEAF_EARG, "a value that is not a number, or too far");
    CHECK(sheaf_sym_eig(2, inf, w, v) == SHEAF_EARG, "an infinity");
    CHECK(sheaf_basis(2, 2, bad, 0.9, 2, 8, rows, sing, &k) == SHEAF_EARG, "basis of a NaN");
    CHECK(sheaf_basis(2, 2, a, NAN, 2, 8, rows, sing, &k) == SHEAF_EARG, "a threshold that is not a number");
    CHECK(sheaf_basis(2, 2, a, 0.9, 0, 8, rows, sing, &k) == SHEAF_EARG && sheaf_basis(2, 2, a, 0.9, 2, 0, rows, sing, &k) == SHEAF_EARG, "a dimension of 0");
    CHECK(sheaf_basis(2, 2, a, 0.9, 2, SHEAF_MAX_STALK + 1, rows, sing, &k) == SHEAF_EARG, "a dimension over the limit");
    CHECK(sheaf_basis(1 << 20, 1 << 10, a, 0.9, 2, 8, rows, sing, &k) == SHEAF_ETOOBIG, "more cells than the limit");
    CHECK(sheaf_basis(2, SHEAF_MAX_COLS + 1, a, 0.9, 2, 8, rows, sing, &k) == SHEAF_ETOOBIG, "more columns than the limit");
    CHECK(sheaf_cohesion(2, 2, far, 0.9, 8, &energy, &lam, f, &k, 0, NULL, NULL, NULL, &kept) == SHEAF_EARG, "cohesion of a far value");
    CHECK(sheaf_cohesion(2, 2, a, 0.9, 8, &energy, &lam, f, &k, 4, NULL, NULL, NULL, &kept) == SHEAF_EARG, "room for pairs and nowhere to put them");
    CHECK(sheaf_cohesion(2, 2, a, 0.9, 8, &energy, &lam, f, &k, -1, NULL, NULL, NULL, &kept) == SHEAF_EARG, "room for -1 pairs");
    CHECK(sheaf_new(0, dims) == NULL && sheaf_new(1, big) == NULL && sheaf_new(2, NULL) == NULL, "a sheaf that should be refused");
    void *s = sheaf_new(2, dims);
    CHECK(s, "no sheaf");
    CHECK(sheaf_add_edge(s, 0, 0, 2, NULL, NULL, 1.0) == SHEAF_EARG, "a loop");
    CHECK(sheaf_add_edge(s, 0, 2, 2, NULL, NULL, 1.0) == SHEAF_EARG && sheaf_add_edge(s, -1, 1, 2, NULL, NULL, 1.0) == SHEAF_EARG, "a vertex that is not there");
    CHECK(sheaf_add_edge(s, 0, 1, 1, NULL, NULL, 1.0) == SHEAF_EARG, "an identity between different dimensions");
    CHECK(sheaf_add_edge(s, 0, 1, 2, NULL, NULL, -0.5) == SHEAF_EARG && sheaf_add_edge(s, 0, 1, 2, NULL, NULL, NAN) == SHEAF_EARG, "a weight under 0 or not a number");
    CHECK(sheaf_add_edge(s, 0, 1, 2, bad, NULL, 1.0) == SHEAF_EARG, "a map with a NaN");
    CHECK(sheaf_add_edge(s, 0, 1, 2, NULL, NULL, 1.0) == 0, "a good edge");
    CHECK(sheaf_energy(s, bad, &energy, NULL) == SHEAF_EARG && sheaf_coboundary(s, bad, rows) == SHEAF_EARG, "a cochain with a NaN");
    CHECK(sheaf_sections(s, -1.0, &h0, &h1, NULL, NULL, NULL) == SHEAF_EARG && sheaf_sections(s, NAN, &h0, &h1, NULL, NULL, NULL) == SHEAF_EARG, "a tolerance under 0 or not a number");
    CHECK(sheaf_sections(NULL, 1e-9, &h0, &h1, NULL, NULL, NULL) == SHEAF_EARG && sheaf_energy(NULL, a, &energy, NULL) == SHEAF_EARG, "no sheaf at all");
    sheaf_free(s);
    sheaf_free(NULL);
    /* Each value in bounds, and too large together: refused, never an infinity with a success code. */
    int32_t wide[2] = {SHEAF_MAX_STALK, 1};
    double *map = dalloc(SHEAF_MAX_STALK), *x = dalloc(SHEAF_MAX_STALK + 1), *L = dalloc((int64_t)(SHEAF_MAX_STALK + 1) * (SHEAF_MAX_STALK + 1)), dx[1];
    CHECK(map && x && L, "out of memory");
    for (int32_t i = 0; i < SHEAF_MAX_STALK; i++) map[i] = x[i] = 1e150;
    x[SHEAF_MAX_STALK] = -1e150;
    s = sheaf_new(2, wide);
    CHECK(s && sheaf_add_edge(s, 0, 1, 1, map, NULL, 1.0) == 0, "the wide edge");
    CHECK(sheaf_energy(s, x, &energy, NULL) == SHEAF_ERANGE, "an energy that would be infinite");
    CHECK(sheaf_laplacian(s, L) == SHEAF_ERANGE, "a Laplacian past the bound");
    CHECK(sheaf_sections(s, 1e-9, &h0, &h1, NULL, NULL, NULL) == SHEAF_ERANGE, "sections of a Laplacian past the bound");
    CHECK(sheaf_coboundary(s, x, dx) == 0 && isfinite(dx[0]), "a coboundary that is large and still a number");
    sheaf_free(s);
    free(map);
    free(x);
    free(L);
    double tall[12];
    for (int32_t i = 0; i < 12; i++) tall[i] = 1e100;
    CHECK(sheaf_basis(3, 4, tall, 0.9, 2, 8, rows, sing, &k) == SHEAF_ERANGE, "rows whose products pass the bound");
    SheafGlue out;
    int32_t counts[2] = {1, 1}, none[2] = {1, 0}, zeroed[2];
    double trust[2] = {1, 1}, over[2] = {1, 1.5}, stalks[16], off[2], res[1], ew[1], cons[8], dev[2], unit[4] = {1, 0, 0, 1};
    CHECK(sheaf_glue(2, 2, counts, unit, NULL, trust, 0, 0.9, 8, &out, rows, stalks, off, zeroed, res, ew, cons, dev) == 0, "a good glue");
    CHECK(sheaf_glue(2, 2, none, unit, NULL, trust, 0, 0.9, 8, &out, rows, stalks, off, zeroed, res, ew, cons, dev) == SHEAF_EARG, "a store with no hits");
    CHECK(sheaf_glue(2, 2, counts, unit, NULL, over, 0, 0.9, 8, &out, rows, stalks, off, zeroed, res, ew, cons, dev) == SHEAF_EARG, "trust over 1");
    CHECK(sheaf_glue(2, 2, counts, bad, NULL, trust, 0, 0.9, 8, &out, rows, stalks, off, zeroed, res, ew, cons, dev) == SHEAF_EARG, "hits with a NaN");
    CHECK(sheaf_glue(2, 2, counts, unit, bad, trust, 0, 0.9, 8, &out, rows, stalks, off, zeroed, res, ew, cons, dev) == SHEAF_EARG, "weights with a NaN");
    CHECK(sheaf_glue(0, 2, counts, unit, NULL, trust, 0, 0.9, 8, &out, rows, stalks, off, zeroed, res, ew, cons, dev) == SHEAF_EARG, "no stores");
    CHECK(sheaf_glue(2, 2, counts, unit, NULL, trust, 0, 0.9, 8, &out, rows, stalks, off, zeroed, NULL, ew, cons, dev) == SHEAF_EARG, "pairs and nowhere to put them");
}

int main(void) {
    int32_t sizes[] = {1, 2, 3, 8, 33, 100};
    for (size_t i = 0; i < sizeof sizes / sizeof *sizes; i++) check_eig(sizes[i]);
    check_basis(1, 5, 0, 0);
    check_basis(6, 40, 0, 0);
    check_basis(50, 12, 0, 0);
    check_basis(7, 9, 1, 0);
    check_basis(9, 7, 1, 0);
    check_basis(4, 6, 0, 1);
    check_basis(6, 4, 0, 1);
    for (int32_t n = 1; n <= 40; n += 3) {
        check_cohesion(n, 24, 1 + n % 3, 10);
        check_cohesion(n, 5, 2, 0);
        check_cohesion(n, 64, 3, 64);
    }
    check_isolated();
    for (int32_t n = 3; n <= 9; n += 3)
        for (int32_t d = 1; d <= 3; d++) {
            check_cycle(n, d, 0);
            check_cycle(n, d, 1);
        }
    for (int32_t round = 0; round < 60; round++) check_random_sheaf(2 + round % 9, 1 + round % 23);
    for (int32_t m = 1; m <= 9; m++) {
        check_glue(m, 12, 0);
        check_glue(m, 3, 0);
        check_glue(m, 12, 1);
    }
    check_refusals();
    printf("ok: %d checks\n", checks);
    return 0;
}
