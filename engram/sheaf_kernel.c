/* A cellular sheaf on a graph, and the two measures Engram takes with one. No storage, no dependencies, C11.
 *
 * A sheaf here is a graph with a vector space on every vertex and every edge (its stalks) and, for each end of each edge,
 * a linear map from the vertex's stalk to the edge's (a restriction map). A choice of one vector per vertex is a 0-cochain x.
 * The coboundary takes it to one vector per edge, (dx)_e = B x_v - A x_u for an edge e from u to v with maps A and B: what the
 * two ends say about e, subtracted. The vertices agree over e exactly when that is zero. Everything else follows from d:
 *
 *   L = d' W d          the sheaf Laplacian, W the edge weights
 *   x' L x              the energy: the weighted sum of |(dx)_e|^2, zero exactly when x glues over every weighted edge
 *   ker L               the global sections (H^0): the 0-cochains that glue
 *   coker d             H^1: what an assignment on the edges can ask for that no assignment on the vertices gives
 *   x - P x             the part of x that does not glue, P the projection onto ker L
 *
 * An edge of weight zero is not in the cover: it adds nothing to L and is left out of H^1.
 *
 * The two measures are this engine with identity maps, and they are kept equal to the numpy code they came from
 * (sheaf.py and lighthouse_sheaf.py, the oracles in tests/test_sheaf_kernel.py):
 *
 *   sheaf_cohesion   one summary's source episodes, in the summary's own terms (the top principal directions, with no
 *                    mean-centring). The energy is 1 minus the second eigenvalue of the normalised Laplacian of their
 *                    similarity graph, and the eigenvector (Fiedler) says where they part.
 *   sheaf_glue       several stores' hits for one topic, in a basis the stores share. Trust weights the edges.
 *
 * Refused, and said: a value that is not finite or is beyond 1e150 in size (SHEAF_EARG), a size past the limits below
 * (SHEAF_ETOOBIG), a decomposition that did not settle (SHEAF_ENOCONV), and values that are each in bounds but too large
 * together, so that a result would not be finite or a matrix to decompose would pass 1e150 (SHEAF_ERANGE). No call
 * reports success with a result that is not finite. Nothing here reads a file, keeps a global, or calls back; every
 * function but the sheaf_* handle calls is a pure function of its arguments, so threads may share it.
 *
 * The symmetric eigenvalue routine is Householder tridiagonalisation and implicit QL, after EISPACK's tred2 and tql2 by way
 * of JAMA (both public domain). Singular directions come from the smaller Gram matrix, which is exact enough for the top
 * directions these measures keep; a direction whose singular value is negligible is completed from the coordinate axes. */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum { SHEAF_ENOMEM = -6, SHEAF_EARG = -7, SHEAF_ENOCONV = -8, SHEAF_ETOOBIG = -9, SHEAF_ERANGE = -12 };
#define SHEAF_ABI 1
#define SHEAF_MAX_N 2048           /* the side of the largest symmetric matrix decomposed: 32 MiB, twice over */
#define SHEAF_MAX_COLS 16384       /* the length of one input vector */
#define SHEAF_MAX_CELLS (1 << 24)  /* rows times columns of one input matrix */
#define SHEAF_MAX_VERTICES 4096
#define SHEAF_MAX_EDGES (1 << 20)
#define SHEAF_MAX_STALK 256
#define SHEAF_MAX_N1 (1 << 22)     /* the dimension of C^1 */
#define SHEAF_MAX_MAGNITUDE 1e150  /* squares of anything this size still fit a double */
#define SHEAF_EPS 1e-12
#ifndef SHEAF_QL_SWEEPS  /* a test builds with 1, to see the refusal a matrix has never yet caused */
#define SHEAF_QL_SWEEPS 64
#endif

/* ---- small things ---------------------------------------------------------------------------------------------- */

static double *dalloc(int64_t count) {
    if (count <= 0 || count > ((int64_t)1 << 27)) return NULL;
    return (double *)calloc((size_t)count, sizeof(double));
}

static int bounded(const double *x, int64_t n) {
    for (int64_t i = 0; i < n; i++)
        if (!(fabs(x[i]) <= SHEAF_MAX_MAGNITUDE)) return 0;  /* false for a NaN and for either infinity */
    return 1;
}

static int all_finite(const double *x, int64_t n) {
    for (int64_t i = 0; i < n; i++)
        if (!isfinite(x[i])) return 0;
    return 1;
}

static double clip01(double v) { return v < 0.0 ? 0.0 : (v > 1.0 ? 1.0 : v); }

static double dot(const double *a, const double *b, int32_t n) {
    double s = 0.0;
    for (int32_t i = 0; i < n; i++) s += a[i] * b[i];
    return s;
}

/* ---- symmetric eigenvalues ------------------------------------------------------------------------------------- */

/* V holds a symmetric matrix on entry (the lower triangle is read) and the tridiagonalising transformation on exit. */
static void tred2(int32_t n, double *V, double *d, double *e) {
#define AT(i, j) V[(int64_t)(i) * n + (j)]
    for (int32_t j = 0; j < n; j++) d[j] = AT(n - 1, j);
    for (int32_t i = n - 1; i > 0; i--) {
        double scale = 0.0, h = 0.0;
        for (int32_t k = 0; k < i; k++) scale += fabs(d[k]);
        if (scale == 0.0) {
            e[i] = d[i - 1];
            for (int32_t j = 0; j < i; j++) {
                d[j] = AT(i - 1, j);
                AT(i, j) = 0.0;
                AT(j, i) = 0.0;
            }
        } else {
            for (int32_t k = 0; k < i; k++) {
                d[k] /= scale;
                h += d[k] * d[k];
            }
            double f = d[i - 1];
            double g = sqrt(h);
            if (f > 0) g = -g;
            e[i] = scale * g;
            h -= f * g;
            d[i - 1] = f - g;
            for (int32_t j = 0; j < i; j++) e[j] = 0.0;
            for (int32_t j = 0; j < i; j++) {
                f = d[j];
                AT(j, i) = f;
                g = e[j] + AT(j, j) * f;
                for (int32_t k = j + 1; k <= i - 1; k++) {
                    g += AT(k, j) * d[k];
                    e[k] += AT(k, j) * f;
                }
                e[j] = g;
            }
            f = 0.0;
            for (int32_t j = 0; j < i; j++) {
                e[j] /= h;
                f += e[j] * d[j];
            }
            double hh = f / (h + h);
            for (int32_t j = 0; j < i; j++) e[j] -= hh * d[j];
            for (int32_t j = 0; j < i; j++) {
                f = d[j];
                g = e[j];
                for (int32_t k = j; k <= i - 1; k++) AT(k, j) -= (f * e[k] + g * d[k]);
                d[j] = AT(i - 1, j);
                AT(i, j) = 0.0;
            }
        }
        d[i] = h;
    }
    for (int32_t i = 0; i < n - 1; i++) {
        AT(n - 1, i) = AT(i, i);
        AT(i, i) = 1.0;
        double h = d[i + 1];
        if (h != 0.0) {
            for (int32_t k = 0; k <= i; k++) d[k] = AT(k, i + 1) / h;
            for (int32_t j = 0; j <= i; j++) {
                double g = 0.0;
                for (int32_t k = 0; k <= i; k++) g += AT(k, i + 1) * AT(k, j);
                for (int32_t k = 0; k <= i; k++) AT(k, j) -= g * d[k];
            }
        }
        for (int32_t k = 0; k <= i; k++) AT(k, i + 1) = 0.0;
    }
    for (int32_t j = 0; j < n; j++) {
        d[j] = AT(n - 1, j);
        AT(n - 1, j) = 0.0;
    }
    AT(n - 1, n - 1) = 1.0;
    e[0] = 0.0;
}

/* The tridiagonal form in d and e becomes eigenvalues in d, ascending, and their vectors in the columns of V. */
static int32_t tql2(int32_t n, double *V, double *d, double *e) {
    for (int32_t i = 1; i < n; i++) e[i - 1] = e[i];
    e[n - 1] = 0.0;
    double f = 0.0, tst1 = 0.0;
    const double eps = 2.220446049250313e-16;
    for (int32_t l = 0; l < n; l++) {
        double here = fabs(d[l]) + fabs(e[l]);
        if (here > tst1) tst1 = here;
        int32_t m = l;
        while (m < n - 1) {  /* e[n-1] is zero, so the last index always ends the search, whatever tst1 holds */
            if (fabs(e[m]) <= eps * tst1) break;
            m++;
        }
        if (m > l) {
            int32_t sweeps = 0;
            do {
                if (++sweeps > SHEAF_QL_SWEEPS) return SHEAF_ENOCONV;
                double g = d[l];
                double p = (d[l + 1] - g) / (2.0 * e[l]);
                double r = hypot(p, 1.0);
                if (p < 0) r = -r;
                d[l] = e[l] / (p + r);
                d[l + 1] = e[l] * (p + r);
                double dl1 = d[l + 1];
                double h = g - d[l];
                for (int32_t i = l + 2; i < n; i++) d[i] -= h;
                f += h;
                p = d[m];
                double c = 1.0, c2 = c, c3 = c, el1 = e[l + 1], s = 0.0, s2 = 0.0;
                for (int32_t i = m - 1; i >= l; i--) {
                    c3 = c2;
                    c2 = c;
                    s2 = s;
                    g = c * e[i];
                    h = c * p;
                    r = hypot(p, e[i]);
                    if (r == 0.0) return SHEAF_ENOCONV;
                    e[i + 1] = s * r;
                    s = e[i] / r;
                    c = p / r;
                    p = c * d[i] - s * g;
                    d[i + 1] = h + s * (c * g + s * d[i]);
                    for (int32_t k = 0; k < n; k++) {
                        h = AT(k, i + 1);
                        AT(k, i + 1) = s * AT(k, i) + c * h;
                        AT(k, i) = c * AT(k, i) - s * h;
                    }
                }
                p = -s * s2 * c3 * el1 * e[l] / dl1;
                e[l] = s * p;
                d[l] = c * p;
            } while (fabs(e[l]) > eps * tst1);
        }
        d[l] += f;
        e[l] = 0.0;
    }
    for (int32_t i = 0; i < n - 1; i++) {
        int32_t k = i;
        double p = d[i];
        for (int32_t j = i + 1; j < n; j++)
            if (d[j] < p) {
                k = j;
                p = d[j];
            }
        if (k != i) {
            d[k] = d[i];
            d[i] = p;
            for (int32_t j = 0; j < n; j++) {
                p = AT(j, i);
                AT(j, i) = AT(j, k);
                AT(j, k) = p;
            }
        }
    }
    return 0;
#undef AT
}

/* V: a symmetric matrix in, its eigenvectors out (vector i is column i). d: the eigenvalues, ascending. e: n of scratch. */
static int32_t eig_inplace(int32_t n, double *V, double *d, double *e) {
    if (n == 1) {
        d[0] = V[0];
        V[0] = 1.0;
        return 0;
    }
    tred2(n, V, d, e);
    int32_t rc = tql2(n, V, d, e);
    if (rc) return rc;
    for (int32_t i = 0; i < n; i++)
        if (!isfinite(d[i])) return SHEAF_ENOCONV;
    for (int64_t i = 0; i < (int64_t)n * n; i++)
        if (!isfinite(V[i])) return SHEAF_ENOCONV;
    return 0;
}

int32_t sheaf_abi(void) { return SHEAF_ABI; }

/* a: n by n, row by row; only its symmetric part is used. evals: n, ascending. evecs: n by n, vector i in column i.
 * A vector's sign is the routine's own, as it is in any such routine. */
int32_t sheaf_sym_eig(int32_t n, const double *a, double *evals, double *evecs) {
    if (n < 1 || !a || !evals || !evecs) return SHEAF_EARG;
    if (n > SHEAF_MAX_N) return SHEAF_ETOOBIG;
    if (!bounded(a, (int64_t)n * n)) return SHEAF_EARG;
    for (int32_t i = 0; i < n; i++)
        for (int32_t j = 0; j <= i; j++) {
            double s = 0.5 * (a[(int64_t)i * n + j] + a[(int64_t)j * n + i]);
            evecs[(int64_t)i * n + j] = s;
            evecs[(int64_t)j * n + i] = s;
        }
    double *e = dalloc(n);
    if (!e) return SHEAF_ENOMEM;
    int32_t rc = eig_inplace(n, evecs, evals, e);
    free(e);
    return rc;
}

/* ---- principal directions -------------------------------------------------------------------------------------- */

/* Take out of v (length d) its parts along the first `have` rows of `rows`, twice, and return what length is left. */
static double orthogonalise(double *v, const double *rows, int32_t have, int32_t d) {
    for (int pass = 0; pass < 2; pass++)
        for (int32_t t = 0; t < have; t++) {
            const double *row = rows + (int64_t)t * d;
            double along = dot(v, row, d);
            for (int32_t c = 0; c < d; c++) v[c] -= along * row[c];
        }
    return sqrt(dot(v, v, d));
}

/* One sign per direction, so the same input gives the same rows on every machine: the largest entry is positive. */
static void fix_sign(double *v, int32_t d) {
    int32_t at = 0;
    for (int32_t c = 1; c < d; c++)
        if (fabs(v[c]) > fabs(v[at])) at = c;
    if (v[at] < 0)
        for (int32_t c = 0; c < d; c++) v[c] = -v[c];
}

/* The top right-singular directions of x (n by d), with no mean-centring: as many as carry `threshold` of the squared
 * singular values, at least min_dim and at most max_dim, and never more than min(n, d). They go to the rows of `out`
 * (room for max(min_dim, max_dim) rows), orthonormal, top first. sing gets all min(n, d) singular values, largest first. */
static int32_t basis_core(int32_t n, int32_t d, const double *x, double threshold, int32_t min_dim, int32_t max_dim,
                          double *out, double *sing, int32_t *k_out) {
    int32_t r = n < d ? n : d;
    if (r > SHEAF_MAX_N) return SHEAF_ETOOBIG;
    double *G = dalloc((int64_t)r * r), *ev = dalloc(r), *e = dalloc(r);
    int32_t rc = SHEAF_ENOMEM;
    if (!G || !ev || !e) goto done;
    if (n <= d) {
        for (int32_t i = 0; i < n; i++)
            for (int32_t j = 0; j <= i; j++) {
                double s = dot(x + (int64_t)i * d, x + (int64_t)j * d, d);
                G[(int64_t)i * r + j] = s;
                G[(int64_t)j * r + i] = s;
            }
    } else {
        for (int32_t i = 0; i < n; i++) {
            const double *row = x + (int64_t)i * d;
            for (int32_t a = 0; a < d; a++) {
                double ra = row[a];
                if (ra == 0.0) continue;
                double *g = G + (int64_t)a * r;
                for (int32_t b = 0; b <= a; b++) g[b] += ra * row[b];
            }
        }
        for (int32_t a = 0; a < d; a++)
            for (int32_t b = 0; b < a; b++) G[(int64_t)b * r + a] = G[(int64_t)a * r + b];
    }
    if (!bounded(G, (int64_t)r * r)) {  /* rows in bounds whose products are not: nothing true could come of it */
        rc = SHEAF_ERANGE;
        goto done;
    }
    rc = eig_inplace(r, G, ev, e);
    if (rc) goto done;
    double total = 0.0;
    for (int32_t i = 0; i < r; i++) {
        double lam = ev[r - 1 - i];
        sing[i] = lam > 0.0 ? sqrt(lam) : 0.0;
        total += sing[i] * sing[i];
    }
    double denom = total > SHEAF_EPS ? total : SHEAF_EPS, running = 0.0;
    int32_t k = r + 1;  /* what a search for the threshold gives when no prefix reaches it */
    for (int32_t i = 0; i < r; i++) {
        running += sing[i] * sing[i] / denom;
        if (running >= threshold) {
            k = i + 1;
            break;
        }
    }
    if (k > max_dim) k = max_dim;
    if (k > r) k = r;
    if (k < min_dim) k = min_dim;
    if (k > r) k = r;
    for (int32_t t = 0; t < k; t++) {
        double *v = out + (int64_t)t * d;
        int32_t col = r - 1 - t;
        double left = 0.0;
        if (sing[t] > 1e-6 * sing[0]) {
            if (n <= d) {
                memset(v, 0, (size_t)d * sizeof(double));
                for (int32_t i = 0; i < n; i++) {
                    double u = G[(int64_t)i * r + col];
                    const double *row = x + (int64_t)i * d;
                    for (int32_t c = 0; c < d; c++) v[c] += u * row[c];
                }
            } else {
                for (int32_t c = 0; c < d; c++) v[c] = G[(int64_t)c * r + col];
            }
            double before = sqrt(dot(v, v, d));
            left = orthogonalise(v, out, t, d);
            if (!(left > 1e-6 * before)) left = 0.0;  /* it lay in the span already: complete from the axes below */
        }
        if (!(left > 0.0)) {
            /* Nothing of the data points this way. Any direction orthogonal to the rows so far is as good as another,
             * so take the first coordinate axis with enough of itself left over; one always has at least (d-t)/d. */
            double need = 0.5 * (double)(d - t) / (double)d;
            for (int32_t axis = 0; axis < d; axis++) {
                memset(v, 0, (size_t)d * sizeof(double));
                v[axis] = 1.0;
                left = orthogonalise(v, out, t, d);
                if (left * left >= need) break;
                left = 0.0;
            }
            if (!(left > 0.0)) {
                rc = SHEAF_ENOCONV;
                goto done;
            }
        }
        for (int32_t c = 0; c < d; c++) v[c] /= left;
        fix_sign(v, d);
    }
    *k_out = k;
    rc = 0;
done:
    free(G);
    free(ev);
    free(e);
    return rc;
}

static int32_t matrix_ok(int32_t n, int32_t d, const double *x) {
    if (n < 1 || d < 1 || !x) return SHEAF_EARG;
    if (d > SHEAF_MAX_COLS || (int64_t)n * d > SHEAF_MAX_CELLS) return SHEAF_ETOOBIG;
    if (!bounded(x, (int64_t)n * d)) return SHEAF_EARG;
    return 0;
}

/* basis: max(min_dim, max_dim) rows of d. sing: min(n, d). The rows are not centred or scaled here; a caller does that. */
int32_t sheaf_basis(int32_t n, int32_t d, const double *x, double threshold, int32_t min_dim, int32_t max_dim,
                    double *basis, double *sing, int32_t *k_out) {
    int32_t rc = matrix_ok(n, d, x);
    if (rc) return rc;
    if (!basis || !sing || !k_out || !isfinite(threshold)) return SHEAF_EARG;
    if (min_dim < 1 || max_dim < 1 || min_dim > SHEAF_MAX_STALK || max_dim > SHEAF_MAX_STALK) return SHEAF_EARG;
    return basis_core(n, d, x, threshold, min_dim, max_dim, basis, sing, k_out);
}

/* ---- cohesion: one summary's episodes -------------------------------------------------------------------------- */

/* x: n episodes by d. Returns 0 with everything filled; 1 when n is under 3 (energy 0, no second eigenvalue, nothing
 * else filled); 2 when an episode is similar to no other (energy 1, lambda2 0, fiedler +1 for each such episode and -1
 * for the rest, no edges). fiedler: n. worst_*: up to max_worst pairs i < j with the largest residuals, largest first. */
int32_t sheaf_cohesion(int32_t n, int32_t d, const double *x, double threshold, int32_t max_dim, double *energy,
                       double *lambda2, double *fiedler, int32_t *k_out, int32_t max_worst, int32_t *worst_i,
                       int32_t *worst_j, double *worst_r, int32_t *n_worst) {
    int32_t rc = matrix_ok(n, d, x);
    if (rc) return rc;
    if (!energy || !lambda2 || !fiedler || !k_out || !n_worst || !isfinite(threshold)) return SHEAF_EARG;
    if (max_dim < 1 || max_dim > SHEAF_MAX_STALK || max_worst < 0 || max_worst > 4096) return SHEAF_EARG;
    if (max_worst > 0 && (!worst_i || !worst_j || !worst_r)) return SHEAF_EARG;
    if (n > SHEAF_MAX_N) return SHEAF_ETOOBIG;
    int32_t kmax = max_dim > 2 ? max_dim : 2, k = 0, r = n < d ? n : d;
    double *xn = dalloc((int64_t)n * d), *V = dalloc((int64_t)kmax * d), *sing = dalloc(r);
    double *Y = dalloc((int64_t)n * kmax), *W = NULL, *L = NULL, *deg = NULL, *ev = NULL, *e = NULL;
    rc = SHEAF_ENOMEM;
    *n_worst = 0;
    if (!xn || !V || !sing || !Y) goto done;
    for (int32_t i = 0; i < n; i++) {
        const double *row = x + (int64_t)i * d;
        double norm = sqrt(dot(row, row, d)) + SHEAF_EPS;
        for (int32_t c = 0; c < d; c++) xn[(int64_t)i * d + c] = row[c] / norm;
    }
    rc = basis_core(n, d, xn, threshold, 2, max_dim, V, sing, &k);
    if (rc) goto done;
    *k_out = k;
    if (n < 3) {
        *energy = 0.0;
        *lambda2 = NAN;
        rc = 1;
        goto done;
    }
    for (int32_t i = 0; i < n; i++) {  /* the episode in the summary's terms, then at unit length */
        double *y = Y + (int64_t)i * k;
        for (int32_t t = 0; t < k; t++) y[t] = dot(xn + (int64_t)i * d, V + (int64_t)t * d, d);
        double norm = sqrt(dot(y, y, k)) + SHEAF_EPS;
        for (int32_t t = 0; t < k; t++) y[t] /= norm;
    }
    W = dalloc((int64_t)n * n);
    L = dalloc((int64_t)n * n);
    deg = dalloc(n);
    ev = dalloc(n);
    e = dalloc(n);
    rc = SHEAF_ENOMEM;
    if (!W || !L || !deg || !ev || !e) goto done;
    for (int32_t i = 0; i < n; i++)
        for (int32_t j = 0; j < i; j++) {
            double s = dot(Y + (int64_t)i * k, Y + (int64_t)j * k, k);
            if (s < 0.0) s = 0.0;
            W[(int64_t)i * n + j] = s;
            W[(int64_t)j * n + i] = s;
        }
    int isolated = 0;
    for (int32_t i = 0; i < n; i++) {
        double s = 0.0;
        for (int32_t j = 0; j < n; j++) s += W[(int64_t)i * n + j];
        deg[i] = s;
        if (s <= SHEAF_EPS) isolated = 1;
    }
    if (isolated) {
        for (int32_t i = 0; i < n; i++) fiedler[i] = deg[i] <= SHEAF_EPS ? 1.0 : -1.0;
        *energy = 1.0;
        *lambda2 = 0.0;
        rc = 2;
        goto done;
    }
    for (int32_t i = 0; i < n; i++) deg[i] = 1.0 / sqrt(deg[i]);
    for (int32_t i = 0; i < n; i++)
        for (int32_t j = 0; j < n; j++)
            L[(int64_t)i * n + j] = (i == j ? 1.0 : 0.0) - W[(int64_t)i * n + j] * deg[i] * deg[j];
    rc = eig_inplace(n, L, ev, e);
    if (rc) goto done;
    for (int32_t i = 0; i < n; i++) fiedler[i] = deg[i] * L[(int64_t)i * n + 1];
    fix_sign(fiedler, n);
    int32_t kept = 0;
    for (int32_t i = 0; i < n && max_worst > 0; i++)
        for (int32_t j = i + 1; j < n; j++) {
            double gap = fiedler[i] - fiedler[j], res = W[(int64_t)i * n + j] * gap * gap;
            if (kept == max_worst && !(res > worst_r[kept - 1])) continue;
            int32_t at = kept < max_worst ? kept : kept - 1;
            while (at > 0 && res > worst_r[at - 1]) {  /* pairs with equal residuals come in no promised order */
                worst_r[at] = worst_r[at - 1];
                worst_i[at] = worst_i[at - 1];
                worst_j[at] = worst_j[at - 1];
                at--;
            }
            worst_r[at] = res;
            worst_i[at] = i;
            worst_j[at] = j;
            if (kept < max_worst) kept++;
        }
    *n_worst = kept;
    *lambda2 = ev[1];
    *energy = clip01(1.0 - ev[1]);
    rc = 0;
done:
    free(xn);
    free(V);
    free(sing);
    free(Y);
    free(W);
    free(L);
    free(deg);
    free(ev);
    free(e);
    return rc;
}

/* ---- the sheaf itself ------------------------------------------------------------------------------------------ */

typedef struct {
    int32_t u, v, dim, off;  /* the ends, the edge stalk's dimension, and where that stalk starts in C^1 */
    double weight;
    double *mu, *mv;         /* dim by dim(u) and dim by dim(v), row by row; NULL is the identity */
} SheafEdge;

typedef struct {
    int32_t nv, ne, cap, n0, n1;
    int32_t *vdim, *voff;
    SheafEdge *edges;
} Sheaf;

void sheaf_free(void *handle) {
    Sheaf *s = (Sheaf *)handle;
    if (!s) return;
    for (int32_t i = 0; i < s->ne; i++) {
        free(s->edges[i].mu);
        free(s->edges[i].mv);
    }
    free(s->edges);
    free(s->vdim);
    free(s->voff);
    free(s);
}

/* A sheaf with nv vertices whose stalks have the given dimensions and no edges yet. NULL when it is refused. */
void *sheaf_new(int32_t nv, const int32_t *vdims) {
    if (nv < 1 || nv > SHEAF_MAX_VERTICES || !vdims) return NULL;
    int64_t n0 = 0;
    for (int32_t i = 0; i < nv; i++) {
        if (vdims[i] < 1 || vdims[i] > SHEAF_MAX_STALK) return NULL;
        n0 += vdims[i];
    }
    if (n0 > SHEAF_MAX_N) return NULL;
    Sheaf *s = (Sheaf *)calloc(1, sizeof(Sheaf));
    if (!s) return NULL;
    s->vdim = (int32_t *)calloc((size_t)nv, sizeof(int32_t));
    s->voff = (int32_t *)calloc((size_t)nv, sizeof(int32_t));
    if (!s->vdim || !s->voff) {
        sheaf_free(s);
        return NULL;
    }
    s->nv = nv;
    for (int32_t i = 0, off = 0; i < nv; i++) {
        s->vdim[i] = vdims[i];
        s->voff[i] = off;
        off += vdims[i];
    }
    s->n0 = (int32_t)n0;
    return s;
}

static double *copied(const double *m, int64_t count) {
    double *out = dalloc(count);
    if (out) memcpy(out, m, (size_t)count * sizeof(double));
    return out;
}

/* An edge from u to v whose stalk has dimension dim. map_u is dim by dim(u) and map_v is dim by dim(v), row by row;
 * NULL is the identity, which needs dim to equal that vertex's dimension. u may equal v: a loop, which the sheaf
 * standard allows; its Laplacian block sums to (map_v - map_u)^T (map_v - map_u). Returns the edge's index. */
int32_t sheaf_add_edge(void *handle, int32_t u, int32_t v, int32_t dim, const double *map_u, const double *map_v,
                       double weight) {
    Sheaf *s = (Sheaf *)handle;
    if (!s || u < 0 || v < 0 || u >= s->nv || v >= s->nv) return SHEAF_EARG;
    if (dim < 1 || dim > SHEAF_MAX_STALK || !(weight >= 0.0) || !(weight <= SHEAF_MAX_MAGNITUDE)) return SHEAF_EARG;
    if ((!map_u && dim != s->vdim[u]) || (!map_v && dim != s->vdim[v])) return SHEAF_EARG;
    if (map_u && !bounded(map_u, (int64_t)dim * s->vdim[u])) return SHEAF_EARG;
    if (map_v && !bounded(map_v, (int64_t)dim * s->vdim[v])) return SHEAF_EARG;
    if (s->ne >= SHEAF_MAX_EDGES || (int64_t)s->n1 + dim > SHEAF_MAX_N1) return SHEAF_ETOOBIG;
    if (s->ne == s->cap) {
        int32_t cap = s->cap ? s->cap * 2 : 16;
        SheafEdge *grown = (SheafEdge *)realloc(s->edges, (size_t)cap * sizeof(SheafEdge));
        if (!grown) return SHEAF_ENOMEM;
        s->edges = grown;
        s->cap = cap;
    }
    SheafEdge edge = {u, v, dim, s->n1, weight, NULL, NULL};
    if (map_u && !(edge.mu = copied(map_u, (int64_t)dim * s->vdim[u]))) return SHEAF_ENOMEM;
    if (map_v && !(edge.mv = copied(map_v, (int64_t)dim * s->vdim[v]))) {
        free(edge.mu);
        return SHEAF_ENOMEM;
    }
    s->edges[s->ne] = edge;
    s->n1 += dim;
    return s->ne++;
}

/* n0: the dimension of C^0 (every vertex stalk, end to end). n1: of C^1. ne: the number of edges. */
int32_t sheaf_dims(void *handle, int32_t *n0, int32_t *n1, int32_t *ne) {
    Sheaf *s = (Sheaf *)handle;
    if (!s || !n0 || !n1 || !ne) return SHEAF_EARG;
    *n0 = s->n0;
    *n1 = s->n1;
    *ne = s->ne;
    return 0;
}

/* out (edge->dim) = B x_v - A x_u. */
static void edge_difference(const Sheaf *s, const SheafEdge *edge, const double *x, double *out) {
    const double *xu = x + s->voff[edge->u], *xv = x + s->voff[edge->v];
    int32_t du = s->vdim[edge->u], dv = s->vdim[edge->v];
    for (int32_t r = 0; r < edge->dim; r++) {
        double from_v = edge->mv ? dot(edge->mv + (int64_t)r * dv, xv, dv) : xv[r];
        double from_u = edge->mu ? dot(edge->mu + (int64_t)r * du, xu, du) : xu[r];
        out[r] = from_v - from_u;
    }
}

/* x: n0. dx: n1, each edge's stalk in the order the edges were added. */
int32_t sheaf_coboundary(void *handle, const double *x, double *dx) {
    Sheaf *s = (Sheaf *)handle;
    if (!s || !x || !bounded(x, s->n0)) return SHEAF_EARG;
    if (s->ne && !dx) return SHEAF_EARG;
    for (int32_t i = 0; i < s->ne; i++) edge_difference(s, &s->edges[i], x, dx + s->edges[i].off);
    return all_finite(dx, s->n1) ? 0 : SHEAF_ERANGE;
}

/* energy: the weighted sum of |(dx)_e|^2, which is x' L x. residual, when it is not NULL: ne values of |(dx)_e|^2,
 * without the weights, so an edge of no weight still says how far apart its ends are. */
int32_t sheaf_energy(void *handle, const double *x, double *energy, double *residual) {
    Sheaf *s = (Sheaf *)handle;
    if (!s || !x || !energy || !bounded(x, s->n0)) return SHEAF_EARG;
    double buffer[SHEAF_MAX_STALK], total = 0.0;
    for (int32_t i = 0; i < s->ne; i++) {
        const SheafEdge *edge = &s->edges[i];
        edge_difference(s, edge, x, buffer);
        double sq = dot(buffer, buffer, edge->dim);
        if (residual) residual[i] = sq;
        total += edge->weight * sq;
    }
    /* Maps and a cochain that are each in bounds can be too large together. An infinite |dx|^2 makes the total
     * infinite, or not a number when its edge has no weight, so this one test covers every residual as well. */
    if (!isfinite(total)) return SHEAF_ERANGE;
    *energy = total;
    return 0;
}

static double map_at(const double *m, int32_t r, int32_t c, int32_t cols) { return m ? m[(int64_t)r * cols + c] : (r == c ? 1.0 : 0.0); }

static void laplacian_into(const Sheaf *s, double *L) {
    int32_t n = s->n0;
    memset(L, 0, (size_t)n * (size_t)n * sizeof(double));
    for (int32_t i = 0; i < s->ne; i++) {
        const SheafEdge *edge = &s->edges[i];
        double w = edge->weight;
        if (w == 0.0) continue;
        int32_t uo = s->voff[edge->u], vo = s->voff[edge->v], du = s->vdim[edge->u], dv = s->vdim[edge->v];
        for (int32_t r = 0; r < edge->dim; r++) {
            for (int32_t a = 0; a < du; a++) {
                double ua = map_at(edge->mu, r, a, du);
                if (ua == 0.0) continue;
                for (int32_t b = 0; b < du; b++) L[(int64_t)(uo + a) * n + uo + b] += w * ua * map_at(edge->mu, r, b, du);
                for (int32_t b = 0; b < dv; b++) {
                    double cross = w * ua * map_at(edge->mv, r, b, dv);
                    L[(int64_t)(uo + a) * n + vo + b] -= cross;
                    L[(int64_t)(vo + b) * n + uo + a] -= cross;
                }
            }
            for (int32_t a = 0; a < dv; a++) {
                double va = map_at(edge->mv, r, a, dv);
                if (va == 0.0) continue;
                for (int32_t b = 0; b < dv; b++) L[(int64_t)(vo + a) * n + vo + b] += w * va * map_at(edge->mv, r, b, dv);
            }
        }
    }
}

/* L: n0 by n0, row by row. When the maps and weights are too large together the call is refused, and what L then
 * holds is not a Laplacian. */
int32_t sheaf_laplacian(void *handle, double *L) {
    Sheaf *s = (Sheaf *)handle;
    if (!s || !L) return SHEAF_EARG;
    laplacian_into(s, L);
    return bounded(L, (int64_t)s->n0 * s->n0) ? 0 : SHEAF_ERANGE;
}

/* h0: the dimension of ker L, counting an eigenvalue as zero when it is at most tol times the larger of 1 and the largest
 * eigenvalue. h1: the dimension of coker d over the edges that have weight. With x (n0): x_ker gets the global section
 * nearest to x, and harmonic the share of |x|^2 that is not in it (0 for a zero x). x, x_ker and harmonic may be NULL. */
int32_t sheaf_sections(void *handle, double tol, int32_t *h0, int32_t *h1, const double *x, double *x_ker,
                       double *harmonic) {
    Sheaf *s = (Sheaf *)handle;
    if (!s || !h0 || !h1 || !(tol >= 0.0) || !isfinite(tol)) return SHEAF_EARG;
    if (x && !bounded(x, s->n0)) return SHEAF_EARG;
    int32_t n = s->n0;
    double *L = dalloc((int64_t)n * n), *ev = dalloc(n), *e = dalloc(n);
    int32_t rc = SHEAF_ENOMEM;
    if (!L || !ev || !e) goto done;
    laplacian_into(s, L);
    if (!bounded(L, (int64_t)n * n)) {
        rc = SHEAF_ERANGE;
        goto done;
    }
    rc = eig_inplace(n, L, ev, e);
    if (rc) goto done;
    double scale = 1.0;
    for (int32_t i = 0; i < n; i++)
        if (fabs(ev[i]) > scale) scale = fabs(ev[i]);
    int32_t kernel = 0;
    while (kernel < n && ev[kernel] <= tol * scale) kernel++;
    int64_t weighted = 0;
    for (int32_t i = 0; i < s->ne; i++)
        if (s->edges[i].weight > 0.0) weighted += s->edges[i].dim;
    *h0 = kernel;
    *h1 = weighted > n - kernel ? (int32_t)(weighted - (n - kernel)) : 0;  /* a rank counted high by the tolerance can't make it negative */
    if (x) {
        double all = dot(x, x, n), out_of = 0.0;
        if (x_ker) memset(x_ker, 0, (size_t)n * sizeof(double));
        for (int32_t c = 0; c < kernel; c++) {
            double along = 0.0;
            for (int32_t i = 0; i < n; i++) along += L[(int64_t)i * n + c] * x[i];
            if (x_ker)
                for (int32_t i = 0; i < n; i++) x_ker[i] += along * L[(int64_t)i * n + c];
            out_of += along * along;
        }
        if (harmonic) {
            if (x_ker) {  /* the difference itself, as the oracle takes it, when there is somewhere to keep the section */
                double sq = 0.0;
                for (int32_t i = 0; i < n; i++) sq += (x[i] - x_ker[i]) * (x[i] - x_ker[i]);
                *harmonic = all > SHEAF_EPS ? sq / all : 0.0;
            } else {
                *harmonic = all > SHEAF_EPS ? clip01((all - out_of) / all) : 0.0;
            }
        }
    }
    rc = 0;
done:
    free(L);
    free(ev);
    free(e);
    return rc;
}

/* ---- glue: several stores' hits for one topic ------------------------------------------------------------------ */

typedef struct {
    int32_t k;                     /* the dimension of the shared basis */
    int32_t kernel_dim;            /* dim ker L */
    int32_t glued_dim;             /* the basis directions on which every pair agrees */
    int32_t consensus_unweighted;  /* 1: every store had trust 0, so the consensus is the plain mean */
    int32_t all_edges_zero;        /* 1: there were pairs and every one had weight 0, so the energy is reported as 0 */
    double energy, energy_unweighted, harmonic;
} SheafGlue;

/* m stores that each cover the topic. counts[i] is store i's number of hits, and hits holds them all, store after store,
 * each a unit row of d. hit_weights (one per hit, NULL for all 1) weights a store's mean; a negative weight counts as 0,
 * and a store whose weights sum to nothing is averaged plainly. trust: m values in [0, 1]. use_min: an edge's weight is
 * the smaller of its ends' trust and not their product.
 *
 * basis: max(2, max_dim) rows of d. stalks: m rows of max(2, max_dim), of which the first out->k are used. off_basis: m.
 * zeroed: m, 1 where a store's section cancels to nothing in the basis. residual and edge_weight: m(m-1)/2, the pairs
 * (i, j) with i < j in order. consensus: max(2, max_dim). deviation: m. */
int32_t sheaf_glue(int32_t m, int32_t d, const int32_t *counts, const double *hits, const double *hit_weights,
                   const double *trust, int32_t use_min, double threshold, int32_t max_dim, SheafGlue *out,
                   double *basis, double *stalks, double *off_basis, int32_t *zeroed, double *residual,
                   double *edge_weight, double *consensus, double *deviation) {
    if (m < 1 || m > SHEAF_MAX_VERTICES || d < 1 || !counts || !hits || !trust || !out) return SHEAF_EARG;
    if (!basis || !stalks || !off_basis || !zeroed || !consensus || !deviation || !isfinite(threshold)) return SHEAF_EARG;
    if (m > 1 && (!residual || !edge_weight)) return SHEAF_EARG;
    if (max_dim < 1 || max_dim > SHEAF_MAX_STALK) return SHEAF_EARG;
    int64_t total = 0;
    for (int32_t i = 0; i < m; i++) {
        if (counts[i] < 1) return SHEAF_EARG;
        total += counts[i];
        if (total > SHEAF_MAX_CELLS) return SHEAF_ETOOBIG;
        if (!(trust[i] >= 0.0 && trust[i] <= 1.0)) return SHEAF_EARG;
    }
    int32_t rc = matrix_ok((int32_t)total, d, hits);
    if (rc) return rc;
    if (hit_weights && !bounded(hit_weights, total)) return SHEAF_EARG;
    int32_t n = (int32_t)total, kmax = max_dim > 2 ? max_dim : 2, k = 0, r = n < d ? n : d;
    if ((int64_t)m * kmax > SHEAF_MAX_N) return SHEAF_ETOOBIG;
    double *scaled = dalloc((int64_t)n * d), *sing = dalloc(r), *mean = dalloc(d), *pair = NULL, *x_ker = NULL;
    int32_t *vdims = NULL;
    Sheaf *sheaf = NULL;
    rc = SHEAF_ENOMEM;
    if (!scaled || !sing || !mean) goto done;
    for (int32_t i = 0, row = 0; i < m; i++) {  /* one unit of mass per store, so a large store can't set the basis alone */
        double share = 1.0 / sqrt((double)counts[i]);
        for (int32_t h = 0; h < counts[i]; h++, row++)
            for (int32_t c = 0; c < d; c++) scaled[(int64_t)row * d + c] = hits[(int64_t)row * d + c] * share;
    }
    rc = basis_core(n, d, scaled, threshold, 2, max_dim, basis, sing, &k);
    if (rc) goto done;
    for (int32_t i = 0, row = 0; i < m; i++) {
        double sum = 0.0;
        for (int32_t h = 0; h < counts[i]; h++) {
            double w = hit_weights ? hit_weights[row + h] : 1.0;
            sum += w > 0.0 ? w : 0.0;
        }
        int plain = !(sum > SHEAF_EPS);
        if (plain) sum = (double)counts[i];
        memset(mean, 0, (size_t)d * sizeof(double));
        for (int32_t h = 0; h < counts[i]; h++, row++) {
            double w = plain ? 1.0 : (hit_weights ? hit_weights[row] : 1.0);
            if (!(w > 0.0)) continue;
            for (int32_t c = 0; c < d; c++) mean[c] += w * hits[(int64_t)row * d + c];
        }
        for (int32_t c = 0; c < d; c++) mean[c] /= sum;
        double *stalk = stalks + (int64_t)i * kmax, full = dot(mean, mean, d), keep = 0.0;
        for (int32_t t = 0; t < kmax; t++) stalk[t] = 0.0;
        for (int32_t t = 0; t < k; t++) {
            stalk[t] = dot(basis + (int64_t)t * d, mean, d);
            keep += stalk[t] * stalk[t];
        }
        off_basis[i] = full <= SHEAF_EPS ? 0.0 : clip01(1.0 - keep / full);
        double norm = sqrt(keep);
        zeroed[i] = norm <= SHEAF_EPS;
        for (int32_t t = 0; t < k; t++) stalk[t] = zeroed[i] ? 0.0 : stalk[t] / norm;
    }
    /* The sheaf: the complete graph on the stores, every stalk R^k, identity maps, trust on the edges. */
    vdims = (int32_t *)calloc((size_t)m, sizeof(int32_t));
    pair = dalloc((int64_t)m * k);
    x_ker = dalloc((int64_t)m * k);
    rc = SHEAF_ENOMEM;
    if (!vdims || !pair || !x_ker) goto done;
    for (int32_t i = 0; i < m; i++) vdims[i] = k;
    sheaf = (Sheaf *)sheaf_new(m, vdims);
    if (!sheaf) goto done;
    double weight_sum = 0.0, trust_sum = 0.0;
    for (int32_t i = 0; i < m; i++) {
        trust_sum += trust[i];
        for (int32_t j = i + 1; j < m; j++) {
            double w = use_min ? (trust[i] < trust[j] ? trust[i] : trust[j]) : trust[i] * trust[j];
            rc = sheaf_add_edge(sheaf, i, j, k, NULL, NULL, w);
            if (rc < 0) goto done;
            edge_weight[rc] = w;
            weight_sum += w;
        }
    }
    for (int32_t i = 0; i < m; i++) memcpy(pair + (int64_t)i * k, stalks + (int64_t)i * kmax, (size_t)k * sizeof(double));
    double energy = 0.0, plain_sum = 0.0;
    rc = sheaf_energy(sheaf, pair, &energy, residual);
    if (rc) goto done;
    int32_t pairs = sheaf->ne;
    for (int32_t i = 0; i < pairs; i++) plain_sum += residual[i];
    out->all_edges_zero = pairs > 0 && !(weight_sum > SHEAF_EPS);
    out->energy = weight_sum > SHEAF_EPS ? clip01(energy / (4.0 * weight_sum)) : 0.0;
    out->energy_unweighted = pairs ? clip01(plain_sum / pairs / 4.0) : 0.0;
    out->consensus_unweighted = !(trust_sum > SHEAF_EPS);
    for (int32_t t = 0; t < kmax; t++) consensus[t] = 0.0;
    for (int32_t i = 0; i < m; i++) {
        double w = out->consensus_unweighted ? 1.0 / m : trust[i] / trust_sum;
        for (int32_t t = 0; t < k; t++) consensus[t] += w * pair[(int64_t)i * k + t];
    }
    for (int32_t i = 0; i < m; i++) {
        double sq = 0.0;
        for (int32_t t = 0; t < k; t++) {
            double gap = pair[(int64_t)i * k + t] - consensus[t];
            sq += gap * gap;
        }
        deviation[i] = sq / 4.0;
    }
    int32_t h1 = 0;
    double harmonic = 0.0;
    rc = sheaf_sections(sheaf, 1e-9, &out->kernel_dim, &h1, pair, x_ker, &harmonic);
    if (rc) goto done;
    out->harmonic = clip01(harmonic);
    /* How many basis directions carry a disagreement: the rank of the pairwise differences, from their k by k Gram matrix. */
    int32_t rank = 0;
    if (pairs) {
        double gram[SHEAF_MAX_STALK], *G = dalloc((int64_t)k * k), *gev = dalloc(k), *ge = dalloc(k);
        rc = SHEAF_ENOMEM;
        if (G && gev && ge) {
            for (int32_t i = 0; i < m; i++)
                for (int32_t j = i + 1; j < m; j++) {
                    for (int32_t t = 0; t < k; t++) gram[t] = pair[(int64_t)j * k + t] - pair[(int64_t)i * k + t];
                    for (int32_t a = 0; a < k; a++)
                        for (int32_t b = 0; b < k; b++) G[(int64_t)a * k + b] += gram[a] * gram[b];
                }
            rc = eig_inplace(k, G, gev, ge);
            for (int32_t t = 0; !rc && t < k; t++)
                if (gev[t] > 1e-12) rank++;  /* a singular value over 1e-6, as the oracle's rank counts them */
        }
        free(G);
        free(gev);
        free(ge);
        if (rc) goto done;
    }
    out->k = k;
    out->glued_dim = k - rank;
    rc = 0;
done:
    sheaf_free(sheaf);
    free(vdims);
    free(pair);
    free(x_ker);
    free(scaled);
    free(sing);
    free(mean);
    return rc;
}
