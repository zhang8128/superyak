// The native sheaf core: docs/standard/sheaf.md, version 1, in C++20 behind a narrow C ABI.
//
// It answers the same questions as engram/sheaf_core.py, which is its oracle, and it is written differently on
// purpose: ranks come from a one-sided Jacobi singular value decomposition here and from LAPACK there, so the two
// agreeing is evidence and not an echo. Jacobi needs nothing but a compiler, and it is slower than LAPACK: about
// 28 times at 480 unknowns, and past roughly 900 it refuses on its work budget. Counting sections of a set sheaf
// is where this file is the fast one.
//
// Every function is stateless, takes plain arrays, and is safe to call from several threads at once. Nothing
// throws across the ABI: each call returns 0, or a negative code and no answer. Every call has a byte budget and a
// work budget and refuses rather than exceed either.
//
//   0 ok   -1 bad argument   -2 over the byte budget   -3 out of memory   -4 over the work budget
//
// A vector sheaf is passed flat:
//   n_nodes, node_dim[n_nodes]
//   n_edges, tail[n_edges], head[n_edges] (node numbers), edge_dim[n_edges]
//   maps[maps_len]: for each edge in order, its tail map then its head map, each row by row
// A set sheaf the same way, with stalk sizes for dimensions, and maps[maps_len] holding, for each edge, the tail
// map (one edge-element number per element of the tail's stalk) then the head map.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <new>
#include <vector>

namespace {

constexpr int32_t OK = 0, BAD = -1, BUDGET = -2, NOMEM = -3, WORK = -4;
constexpr double PINV_TOL = 1e-12;   // the standard, section 2.3
constexpr int MAX_SWEEPS = 80;

struct Refuse { int32_t code; };

// Counts work in units of one floating-point multiply-add, and refuses past the budget.
struct Work {
    int64_t left;
    void spend(int64_t n) {
        if (n > left) throw Refuse{WORK};
        left -= n;
    }
};

int64_t mul(int64_t a, int64_t b) {
    int64_t out;
    if (a < 0 || b < 0 || __builtin_mul_overflow(a, b, &out)) throw Refuse{BAD};
    return out;
}

int64_t add(int64_t a, int64_t b) {
    int64_t out;
    if (a < 0 || b < 0 || __builtin_add_overflow(a, b, &out)) throw Refuse{BAD};
    return out;
}

struct Graph {
    int32_t n_nodes = 0, n_edges = 0;
    const int32_t *size = nullptr, *tail = nullptr, *head = nullptr, *esize = nullptr;
    std::vector<int64_t> node_off;   // offset of each node in C0 (vector sheaves)
    std::vector<int64_t> map_off;    // offset of each edge's tail map in maps
    int64_t c0 = 0, c1 = 0, maps_len = 0;
};

// Checks the shape shared by both kinds of sheaf. `per_entry` says how a map's length follows from its sizes.
template <class MapLen>
Graph graph(int32_t n_nodes, const int32_t *size, int32_t n_edges, const int32_t *tail, const int32_t *head,
            const int32_t *esize, int64_t maps_len, bool have_maps, MapLen map_len) {
    if (n_nodes < 0 || n_edges < 0 || maps_len < 0) throw Refuse{BAD};
    if ((n_nodes > 0 && !size) || (n_edges > 0 && (!tail || !head || !esize))) throw Refuse{BAD};
    Graph g;
    g.n_nodes = n_nodes, g.n_edges = n_edges, g.size = size, g.tail = tail, g.head = head, g.esize = esize;
    g.node_off.resize(static_cast<size_t>(n_nodes) + 1);
    for (int32_t v = 0; v < n_nodes; v++) {
        if (size[v] < 0) throw Refuse{BAD};
        g.node_off[v] = g.c0;
        g.c0 = add(g.c0, size[v]);
    }
    g.node_off[n_nodes] = g.c0;
    g.map_off.resize(static_cast<size_t>(n_edges) + 1);
    for (int32_t e = 0; e < n_edges; e++) {
        if (esize[e] < 0 || tail[e] < 0 || tail[e] >= n_nodes || head[e] < 0 || head[e] >= n_nodes)
            throw Refuse{BAD};
        g.map_off[e] = g.maps_len;
        g.maps_len = add(g.maps_len, add(map_len(esize[e], size[tail[e]]), map_len(esize[e], size[head[e]])));
        g.c1 = add(g.c1, esize[e]);
    }
    g.map_off[n_edges] = g.maps_len;
    if (g.maps_len != maps_len || (maps_len > 0 && !have_maps)) throw Refuse{BAD};
    return g;
}

struct Vector {
    Graph g;
    const double *maps = nullptr;
    const double *tail_map(int32_t e) const { return maps + g.map_off[e]; }
    const double *head_map(int32_t e) const {
        return maps + g.map_off[e] + static_cast<int64_t>(g.esize[e]) * g.size[g.tail[e]];
    }
};

Vector vector_sheaf(int32_t n_nodes, const int32_t *node_dim, int32_t n_edges, const int32_t *tail,
                    const int32_t *head, const int32_t *edge_dim, const double *maps, int64_t maps_len) {
    Vector F;
    F.g = graph(n_nodes, node_dim, n_edges, tail, head, edge_dim, maps_len, maps != nullptr,
                [](int64_t m, int64_t n) { return mul(m, n); });
    F.maps = maps;
    for (int64_t i = 0; i < maps_len; i++)
        if (!std::isfinite(maps[i])) throw Refuse{BAD};
    return F;
}

void budget(int64_t doubles, int64_t budget_bytes) {
    if (budget_bytes < 0) throw Refuse{BAD};
    if (mul(doubles, 8) > budget_bytes) throw Refuse{BUDGET};
}

// A dense matrix held column by column, which is how Jacobi reads it.
struct Columns {
    int64_t rows = 0, cols = 0;
    std::vector<double> a;
    Columns(int64_t r, int64_t c) : rows(r), cols(c), a(static_cast<size_t>(mul(r, c)), 0.0) {}
    double *col(int64_t j) { return a.data() + j * rows; }
    const double *col(int64_t j) const { return a.data() + j * rows; }
};

// One-sided Jacobi (Hestenes). On return the columns of A are orthogonal, A_in * V = A_out, and the singular
// values are the column lengths, sorted longest first with V's columns in the same order.
struct Svd {
    Columns av, v;
    std::vector<double> sigma;
};

Svd jacobi(Columns a, Work &work) {
    const int64_t m = a.rows, n = a.cols;
    Columns v(n, n);
    for (int64_t j = 0; j < n; j++) v.col(j)[j] = 1.0;
    const double eps = std::numeric_limits<double>::epsilon();
    // A column this short is zero to working precision. Turning two such columns against each other would only
    // chase rounding noise, and a matrix wider than it is tall always has some.
    double scale = 0;
    for (double x : a.a) scale += x * x;
    const double tiny = eps * eps * scale;
    for (int sweep = 0; sweep < MAX_SWEEPS; sweep++) {
        bool turned = false;
        for (int64_t p = 0; p + 1 < n; p++) {
            for (int64_t q = p + 1; q < n; q++) {
                work.spend(3 * m);
                double *x = a.col(p), *y = a.col(q);
                double alpha = 0, beta = 0, gamma = 0;
                for (int64_t i = 0; i < m; i++) alpha += x[i] * x[i], beta += y[i] * y[i], gamma += x[i] * y[i];
                if (alpha <= tiny || beta <= tiny || std::fabs(gamma) <= eps * std::sqrt(alpha * beta)) continue;
                turned = true;
                const double zeta = (beta - alpha) / (2 * gamma);
                const double t = (zeta >= 0 ? 1.0 : -1.0) / (std::fabs(zeta) + std::sqrt(1 + zeta * zeta));
                const double c = 1 / std::sqrt(1 + t * t), s = c * t;
                work.spend(2 * (m + n));
                for (int64_t i = 0; i < m; i++) {
                    const double xi = x[i], yi = y[i];
                    x[i] = c * xi - s * yi, y[i] = s * xi + c * yi;
                }
                double *vx = v.col(p), *vy = v.col(q);
                for (int64_t i = 0; i < n; i++) {
                    const double xi = vx[i], yi = vy[i];
                    vx[i] = c * xi - s * yi, vy[i] = s * xi + c * yi;
                }
            }
        }
        if (!turned) break;
        if (sweep + 1 == MAX_SWEEPS) throw Refuse{WORK};   // it did not settle: refuse, never guess
    }
    std::vector<double> length(static_cast<size_t>(n));
    for (int64_t j = 0; j < n; j++) {
        double sum = 0;
        const double *x = a.col(j);
        for (int64_t i = 0; i < m; i++) sum += x[i] * x[i];
        length[j] = std::sqrt(sum);
    }
    std::vector<int64_t> order(static_cast<size_t>(n));
    for (int64_t j = 0; j < n; j++) order[j] = j;
    std::stable_sort(order.begin(), order.end(), [&](int64_t i, int64_t j) { return length[i] > length[j]; });
    Svd out{Columns(m, n), Columns(n, n), std::vector<double>(static_cast<size_t>(n))};
    for (int64_t j = 0; j < n; j++) {
        std::copy_n(a.col(order[j]), m, out.av.col(j));
        std::copy_n(v.col(order[j]), n, out.v.col(j));
        out.sigma[j] = length[order[j]];
    }
    return out;
}

// The coboundary, dense: one block row per edge, the head map minus the tail map. A loop's two maps add up.
Columns coboundary(const Vector &F) {
    Columns d(F.g.c1, F.g.c0);
    int64_t row = 0;
    for (int32_t e = 0; e < F.g.n_edges; e++) {
        const int64_t m = F.g.esize[e];
        const int32_t t = F.g.tail[e], h = F.g.head[e];
        const double *A = F.tail_map(e), *B = F.head_map(e);
        for (int64_t i = 0; i < m; i++) {
            for (int64_t j = 0; j < F.g.size[h]; j++) d.col(F.g.node_off[h] + j)[row + i] += B[i * F.g.size[h] + j];
            for (int64_t j = 0; j < F.g.size[t]; j++) d.col(F.g.node_off[t] + j)[row + i] -= A[i * F.g.size[t] + j];
        }
        row += m;
    }
    return d;
}

struct Rank {
    int64_t rank = 0;
    double top = 0, kept_min = std::nan(""), dropped_max = std::nan("");
    Columns basis;   // c0 x (c0 - rank), orthonormal columns: the global sections
    Rank() : basis(0, 0) {}
};

Rank cohomology(const Vector &F, double tol, int64_t budget_bytes, Work &work) {
    if (!(std::isfinite(tol) && tol >= 0 && tol < 1)) throw Refuse{BAD};
    const int64_t n0 = F.g.c0, n1 = F.g.c1;
    Rank out;
    if (n0 == 0 || n1 == 0) {
        budget(mul(n0, n0), budget_bytes);
        out.basis = Columns(n0, n0);
        for (int64_t j = 0; j < n0; j++) out.basis.col(j)[j] = 1.0;
        return out;
    }
    budget(add(mul(3, mul(n0, n1)), mul(3, mul(n0, n0))), budget_bytes);
    Svd svd = jacobi(coboundary(F), work);
    out.top = svd.sigma[0];
    while (out.rank < n0 && out.top > 0 && svd.sigma[out.rank] > tol * out.top) out.rank++;
    if (out.rank > 0) out.kept_min = svd.sigma[out.rank - 1] / out.top;
    if (out.rank < n0) out.dropped_max = out.top > 0 ? svd.sigma[out.rank] / out.top : 0.0;
    out.basis = Columns(n0, n0 - out.rank);
    for (int64_t j = out.rank; j < n0; j++) std::copy_n(svd.v.col(j), n0, out.basis.col(j - out.rank));
    return out;
}

// pinv(M) for a row-major rows x cols matrix, returned row-major cols x rows.
std::vector<double> pinv(const double *M, int64_t rows, int64_t cols, Work &work) {
    std::vector<double> out(static_cast<size_t>(mul(cols, rows)), 0.0);
    if (rows == 0 || cols == 0) return out;
    Columns a(rows, cols);
    for (int64_t i = 0; i < rows; i++)
        for (int64_t j = 0; j < cols; j++) a.col(j)[i] = M[i * cols + j];
    Svd svd = jacobi(std::move(a), work);
    const double top = svd.sigma[0];
    for (int64_t k = 0; k < cols; k++) {
        const double s = svd.sigma[k];
        if (!(top > 0) || s <= PINV_TOL * top) break;
        const double *u = svd.av.col(k), *v = svd.v.col(k);   // u here is sigma times the left vector
        work.spend(rows * cols);
        for (int64_t i = 0; i < cols; i++)
            for (int64_t j = 0; j < rows; j++) out[i * rows + j] += v[i] * u[j] / (s * s);
    }
    return out;
}

// row-major product: (r x k) times (k x c)
std::vector<double> product(const std::vector<double> &a, const double *b, int64_t r, int64_t k, int64_t c,
                            Work &work) {
    std::vector<double> out(static_cast<size_t>(mul(r, c)), 0.0);
    work.spend(mul(mul(r, k), c));
    for (int64_t i = 0; i < r; i++)
        for (int64_t l = 0; l < k; l++) {
            const double x = a[i * k + l];
            if (x == 0) continue;
            for (int64_t j = 0; j < c; j++) out[i * c + j] += x * b[l * c + j];
        }
    return out;
}

template <class Body>
int32_t guarded(Body body) noexcept {
    try {
        body();
        return OK;
    } catch (const Refuse &r) {
        return r.code;
    } catch (const std::bad_alloc &) {
        return NOMEM;
    } catch (...) {
        return BAD;
    }
}

}  // namespace

extern "C" {

int32_t sheaf_abi_version(void) noexcept { return 1; }

// out_dims: dim C0, dim C1, dim H0, dim H1. out_stats: sigma_max, kept_min, dropped_max (NaN where there is none).
// basis may be null. If it is not, basis_cap must be at least dim C0 squared, and the first dim C0 * dim H0
// entries are filled row by row: one row per coordinate of C0, one column per global section.
int32_t sheaf_cohomology(int32_t n_nodes, const int32_t *node_dim, int32_t n_edges, const int32_t *tail,
                         const int32_t *head, const int32_t *edge_dim, const double *maps, int64_t maps_len,
                         double tol, int64_t budget_bytes, int64_t budget_work, int64_t *out_dims,
                         double *out_stats, double *basis, int64_t basis_cap) noexcept {
    return guarded([&] {
        if (!out_dims || !out_stats || budget_work < 0) throw Refuse{BAD};
        const Vector F = vector_sheaf(n_nodes, node_dim, n_edges, tail, head, edge_dim, maps, maps_len);
        if (basis && basis_cap < mul(F.g.c0, F.g.c0)) throw Refuse{BAD};
        Work work{budget_work};
        const Rank r = cohomology(F, tol, budget_bytes, work);
        const int64_t h0 = F.g.c0 - r.rank;
        if (basis)
            for (int64_t i = 0; i < F.g.c0; i++)
                for (int64_t j = 0; j < h0; j++) basis[i * h0 + j] = r.basis.col(j)[i];
        out_dims[0] = F.g.c0, out_dims[1] = F.g.c1, out_dims[2] = h0, out_dims[3] = F.g.c1 - r.rank;
        out_stats[0] = r.top, out_stats[1] = r.kept_min, out_stats[2] = r.dropped_max;
    });
}

// x holds the local data, node after node (x_len = dim C0). residuals gets one length per edge, nearest the
// nearest global section (dim C0 numbers), and distance_squared how far x is from it.
int32_t sheaf_glue(int32_t n_nodes, const int32_t *node_dim, int32_t n_edges, const int32_t *tail,
                   const int32_t *head, const int32_t *edge_dim, const double *maps, int64_t maps_len,
                   const double *x, int64_t x_len, double tol, int64_t budget_bytes, int64_t budget_work,
                   double *residuals, double *nearest, double *distance_squared) noexcept {
    return guarded([&] {
        if (!distance_squared || budget_work < 0) throw Refuse{BAD};
        const Vector F = vector_sheaf(n_nodes, node_dim, n_edges, tail, head, edge_dim, maps, maps_len);
        const int64_t n0 = F.g.c0;
        if (x_len != n0 || (n0 > 0 && (!x || !nearest)) || (n_edges > 0 && !residuals)) throw Refuse{BAD};
        for (int64_t i = 0; i < n0; i++)
            if (!std::isfinite(x[i])) throw Refuse{BAD};
        Work work{budget_work};
        for (int32_t e = 0; e < n_edges; e++) {
            const int64_t m = edge_dim[e], nt = node_dim[tail[e]], nh = node_dim[head[e]];
            const double *A = F.tail_map(e), *B = F.head_map(e);
            const double *xt = x + F.g.node_off[tail[e]], *xh = x + F.g.node_off[head[e]];
            work.spend(m * (nt + nh));
            double sum = 0;
            for (int64_t i = 0; i < m; i++) {
                double r = 0;
                for (int64_t j = 0; j < nh; j++) r += B[i * nh + j] * xh[j];
                for (int64_t j = 0; j < nt; j++) r -= A[i * nt + j] * xt[j];
                sum += r * r;
            }
            residuals[e] = std::sqrt(sum);
        }
        const Rank r = cohomology(F, tol, budget_bytes, work);
        const int64_t h0 = n0 - r.rank;
        std::vector<double> y(static_cast<size_t>(n0), 0.0);
        work.spend(2 * n0 * h0);
        for (int64_t j = 0; j < h0; j++) {
            const double *b = r.basis.col(j);
            double dot = 0;
            for (int64_t i = 0; i < n0; i++) dot += b[i] * x[i];
            for (int64_t i = 0; i < n0; i++) y[i] += dot * b[i];
        }
        double dist = 0;
        for (int64_t i = 0; i < n0; i++) dist += (x[i] - y[i]) * (x[i] - y[i]);
        std::copy(y.begin(), y.end(), nearest);
        *distance_squared = dist;
    });
}

// A route is step_edge[i] with step_dir[i] of +1 (tail to head) or -1. out gets the transport matrix row by row;
// out_shape its rows (the end's dimension) and columns (the start's). out_cap must hold it.
int32_t sheaf_transport(int32_t n_nodes, const int32_t *node_dim, int32_t n_edges, const int32_t *tail,
                        const int32_t *head, const int32_t *edge_dim, const double *maps, int64_t maps_len,
                        int32_t n_steps, const int32_t *step_edge, const int32_t *step_dir, int64_t budget_bytes,
                        int64_t budget_work, double *out, int64_t out_cap, int64_t *out_shape) noexcept {
    return guarded([&] {
        if (!out_shape || budget_work < 0 || n_steps <= 0 || !step_edge || !step_dir) throw Refuse{BAD};
        const Vector F = vector_sheaf(n_nodes, node_dim, n_edges, tail, head, edge_dim, maps, maps_len);
        Work work{budget_work};
        int32_t at = -1, start = -1;
        std::vector<double> T;
        for (int32_t i = 0; i < n_steps; i++) {
            const int32_t e = step_edge[i], dir = step_dir[i];
            if (e < 0 || e >= n_edges || (dir != 1 && dir != -1)) throw Refuse{BAD};
            const int32_t src = dir == 1 ? tail[e] : head[e], dst = dir == 1 ? head[e] : tail[e];
            if (at == -1) {
                start = src;
                const int64_t n = node_dim[src];
                budget(mul(n, n), budget_bytes);
                T.assign(static_cast<size_t>(n * n), 0.0);
                for (int64_t j = 0; j < n; j++) T[j * n + j] = 1.0;
            } else if (src != at) {
                throw Refuse{BAD};
            }
            const int64_t m = edge_dim[e], ns = node_dim[src], nd = node_dim[dst], n_start = node_dim[start];
            budget(add(mul(4, mul(m, add(ns, nd))), mul(2, mul(add(ns, nd), n_start))), budget_bytes);
            const double *near = dir == 1 ? F.tail_map(e) : F.head_map(e);
            const double *far = dir == 1 ? F.head_map(e) : F.tail_map(e);
            const std::vector<double> far_inv = pinv(far, m, nd, work);           // nd x m
            const std::vector<double> step = product(far_inv, near, nd, m, ns, work);   // nd x ns
            T = product(step, T.data(), nd, ns, n_start, work);                   // nd x n_start
            at = dst;
        }
        out_shape[0] = node_dim[at], out_shape[1] = node_dim[start];
        const int64_t need = static_cast<int64_t>(T.size());
        if (out_cap < need || (need > 0 && !out)) throw Refuse{BAD};
        std::copy(T.begin(), T.end(), out);
    });
}

// local[v] is the number of the element chosen at node v. bad[e] is set to 1 where the two ends disagree.
int32_t sheaf_glue_sets(int32_t n_nodes, const int32_t *node_size, int32_t n_edges, const int32_t *tail,
                        const int32_t *head, const int32_t *edge_size, const int32_t *maps, int64_t maps_len,
                        const int32_t *local, int32_t *bad) noexcept {
    return guarded([&] {
        const Graph g = graph(n_nodes, node_size, n_edges, tail, head, edge_size, maps_len, maps != nullptr,
                              [](int64_t, int64_t n) { return n; });
        if ((n_nodes > 0 && !local) || (n_edges > 0 && !bad)) throw Refuse{BAD};
        for (int32_t v = 0; v < n_nodes; v++)
            if (local[v] < 0 || local[v] >= node_size[v]) throw Refuse{BAD};
        for (int32_t e = 0; e < n_edges; e++) {
            const int32_t *tm = maps + g.map_off[e], *hm = tm + node_size[tail[e]];
            for (int32_t i = 0; i < node_size[tail[e]]; i++)
                if (tm[i] < 0 || tm[i] >= edge_size[e]) throw Refuse{BAD};
            for (int32_t i = 0; i < node_size[head[e]]; i++)
                if (hm[i] < 0 || hm[i] >= edge_size[e]) throw Refuse{BAD};
            bad[e] = tm[local[tail[e]]] != hm[local[head[e]]];
        }
    });
}

// The number of global sections, by backtracking in breadth-first order. Exact, or it refuses.
int32_t sheaf_count_sections(int32_t n_nodes, const int32_t *node_size, int32_t n_edges, const int32_t *tail,
                             const int32_t *head, const int32_t *edge_size, const int32_t *maps, int64_t maps_len,
                             int64_t budget_steps, int64_t *out_count) noexcept {
    return guarded([&] {
        if (!out_count || budget_steps < 0) throw Refuse{BAD};
        const Graph g = graph(n_nodes, node_size, n_edges, tail, head, edge_size, maps_len, maps != nullptr,
                              [](int64_t, int64_t n) { return n; });
        for (int32_t e = 0; e < n_edges; e++) {
            const int32_t *tm = maps + g.map_off[e];
            const int64_t entries = static_cast<int64_t>(node_size[tail[e]]) + node_size[head[e]];
            for (int64_t i = 0; i < entries; i++)
                if (tm[i] < 0 || tm[i] >= edge_size[e]) throw Refuse{BAD};
        }
        if (n_nodes == 0) {
            *out_count = 1;
            return;
        }
        std::vector<std::vector<int32_t>> touching(static_cast<size_t>(n_nodes));
        for (int32_t e = 0; e < n_edges; e++) {
            touching[tail[e]].push_back(e);
            if (head[e] != tail[e]) touching[head[e]].push_back(e);
        }
        std::vector<int32_t> order, place(static_cast<size_t>(n_nodes), -1);
        order.reserve(static_cast<size_t>(n_nodes));
        for (int32_t root = 0; root < n_nodes; root++) {
            if (place[root] != -1) continue;
            place[root] = -2;
            size_t front = order.size();
            order.push_back(root);
            while (front < order.size()) {
                const int32_t v = order[front++];
                for (int32_t e : touching[v]) {
                    const int32_t w = tail[e] == v ? head[e] : tail[e];
                    if (place[w] == -1) place[w] = -2, order.push_back(w);
                }
            }
        }
        for (int32_t i = 0; i < n_nodes; i++) place[order[i]] = i;
        std::vector<std::vector<int32_t>> checks(static_cast<size_t>(n_nodes));
        for (int32_t i = 0; i < n_nodes; i++)
            for (int32_t e : touching[order[i]])
                if (place[tail[e]] <= i && place[head[e]] <= i) checks[i].push_back(e);
        std::vector<int32_t> chosen(static_cast<size_t>(n_nodes), 0), cursor(static_cast<size_t>(n_nodes) + 1, 0);
        int64_t steps = 0, total = 0;
        int32_t depth = 0;
        while (depth >= 0) {
            if (depth == n_nodes) {
                if (total == std::numeric_limits<int64_t>::max()) throw Refuse{WORK};
                total++, depth--;
                continue;
            }
            const int32_t v = order[depth];
            bool advanced = false;
            while (cursor[depth] < node_size[v]) {
                const int32_t x = cursor[depth]++;
                steps += 1 + static_cast<int64_t>(checks[depth].size());
                if (steps > budget_steps) throw Refuse{WORK};
                chosen[v] = x;
                bool fits = true;
                for (int32_t e : checks[depth]) {
                    const int32_t *tm = maps + g.map_off[e], *hm = tm + node_size[tail[e]];
                    if (tm[chosen[tail[e]]] != hm[chosen[head[e]]]) {
                        fits = false;
                        break;
                    }
                }
                if (fits) {
                    advanced = true;
                    break;
                }
            }
            if (advanced)
                cursor[++depth] = 0;
            else
                depth--;
        }
        *out_count = total;
    });
}

}  // extern "C"
