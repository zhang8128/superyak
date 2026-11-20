# The sheaf kernel in C: design

2026-11-20, by Serenity. Built on branch `serenity/sheaf-kernel`. The spec and the code went to one fresh reader
together, who said "approve with named changes"; its two required changes and four follow-ups are made (see "The
reader's changes").

## Why

Andy, 2026-11-20, after asking how well the sheaf system works: "could we get the sheaf system working in some flavor
of c or rust depending on what makes the most sense?"

There were two sheaves, both numpy inside Engram: `sheaf.py` (does one summary's source episodes glue) and
`lighthouse_sheaf.py` (do several stores agree on a topic). Neither was a sheaf engine: each hard-coded identity
restriction maps on a complete graph. The room in `v2` is Rust and has no numpy, so it could use neither.

## What was measured first (one live store, opened read-only; counts only)

- The sheaf had not run there since 2026-09-07. Its setting is on in the store's own config, but a server reads the
  config of the folder it starts in, and those files are made from defaults that say off. That is a separate fault
  with its own fix (see "Not in this branch").
- As built, on 266 real summaries: none would split at `dl_cost` 0.05 or 0.15; 20 would at 0.02.
- A presence control: 300 false summaries, each two real ones glued (no episode in common). At 0.15 (the default)
  the gate caught 0. At 0.05 it caught 79, 64 of them exactly along the true line. At 0.02 it caught 198, 125 exactly.
- The energy ranks a false summary above a real one of like size 81% of the time. Four other statistics were tried
  on the same data and none caught more at a 5% false-alarm rate, so the measure is kept as it is.

So the port keeps the measure and does not invent one. The thresholds are a calibration question, left open below.

## Language: C11

- Engram is what runs on every machine, and it already loads one C kernel (`ncat_kernel.c`), compiled on first use
  with the system compiler. A second C file needs no new toolchain on any machine or in any install. A Rust library
  would need cargo wherever Engram is installed, or shipped binaries.
- Rust can call C. The room can link this file when it needs gluing; the reverse (Python calling a Rust crate)
  costs the toolchain above.
- Not C++: the n-category kernel's C++20 port just showed that a default C++20 build fails unclearly on an older
  compiler. Not C#: nothing here runs .NET.
- The kernel parses nothing. Its inputs are arrays with sizes, which is where C's risks are smallest, and it runs
  under the address and undefined-behaviour sanitizers in the test suite.

## What it is

`engram/sheaf_kernel.c`, 900 lines, no dependencies beyond libm, no global state.

A cellular sheaf on a graph: a stalk R^d on each vertex and each edge, a linear map from each end of an edge to the
edge (NULL for the identity), and a weight on each edge. From those:

| Call | Gives |
| --- | --- |
| `sheaf_coboundary` | (dx)_e = B x_v - A x_u for every edge |
| `sheaf_laplacian` | L = d' W d |
| `sheaf_energy` | x' L x, and each edge's \|dx\|^2 without its weight |
| `sheaf_sections` | dim H^0 = dim ker L, dim H^1 = dim coker d over weighted edges, the global section nearest to x, and the share of x that does not glue |
| `sheaf_sym_eig`, `sheaf_basis` | the symmetric eigenvalue routine and the principal directions the two measures need |
| `sheaf_cohesion` | `sheaf.py`'s measure: energy, second eigenvalue, Fiedler vector, worst pairs |
| `sheaf_glue` | `lighthouse_sheaf.py`'s arithmetic, as the engine with identity maps on a complete graph |

`sheaf_native.py` is the ctypes binding. `native_build.py` compiles a C file into the user's own cache with the care
`ncat.py` takes (fixed compiler paths, a two-entry environment, a refused cache or library that another user could
write), plus `-ffp-contract=off` so arm64 and x86-64 do the same arithmetic.

## Decisions

1. **The numpy code stays, as fallback and as oracle.** `sheaf.measure` and `lighthouse_sheaf.glue` use the kernel
   wherever it loads. Where it can't (no compiler), or declines one input (too large), numpy takes the call and a log
   line says so. `ENGRAM_SHEAF_BACKEND` or a `backend=` argument names one; a named kernel that declines raises.
2. **Equality is tested, not assumed.** Random inputs against numpy for both measures, the eigenvalue routine, the
   basis and random sheaves with random maps; sheaves with known answers (a constant sheaf counts a graph's pieces
   and loops; a twist on a cycle leaves no global section; an edge that sees one coordinate). On the live store,
   1,132 verdicts by both backends: none differed, and the largest numeric difference was 3.2e-15.
3. **One sign per eigenvector** (the largest entry is positive), in the kernel and in the numpy path, so the same
   input names the same part first on every machine. Before, the sign was LAPACK's own.
4. **Refused, with a code:** a value that is not finite or is beyond 1e150; sizes past the limits (a symmetric matrix
   side over 2,048, a vector over 16,384, a matrix over 2^24 cells); a decomposition that did not settle; and values
   that are each in bounds but too large together, so that a result would not be finite. No call reports success
   with a result that is not finite. The binding refuses wrong shapes and kinds before the kernel is called.
5. **An edge of weight zero is out of the cover.** It adds nothing to L and is not counted in H^1, but its residual is
   still reported. This is what `lighthouse_sheaf.py` already did with zero trust.

## What it does not do

- It is not faster overall. On small inputs it is about 3.6 times faster than numpy; on the largest summary (433
  episodes) it is slower, because numpy's BLAS beats plain loops. Whole-store time is about the same.
- It does not make the gate see more. At the default threshold the gate still catches nothing.
- H^0 and H^1 are counted through the eigenvalues of L with a relative tolerance of 1e-9, so a restriction map that
  is nearly singular is counted by that tolerance and no finer.
- Sizes are dense. A graph whose C^0 passes 2,048 dimensions is refused, not approximated.
- Pairs with exactly equal residuals come in no promised order, in the kernel as in numpy.
- The number of directions kept is the same as numpy's wherever the running share of variance is the same float in
  both, which it is on exact inputs (tested at the threshold itself). On general inputs the two sums are rounded
  separately, so a share within one rounding of the threshold could be cut differently. No such input was found.

## The reader's changes

1. **Required.** With maps other than the identity, values each within 1e150 could combine past what a double
   holds: `sheaf_energy` returned infinity with a success code and `sheaf_laplacian` returned entries of 1e300. Both
   now refuse (code -12), as do `sheaf_sections`, a coboundary that is not finite, and principal directions whose
   Gram matrix passes the bound. The two measures were never exposed: they use identity maps on unit vectors.
2. **Required.** `lighthouse_sheaf.glue` fell back to numpy without a word. It logs now, as `sheaf.measure` did.
3. The clamp that keeps H^1 from going negative had no test. It has one now (a tolerance of zero), with a control
   that the rank is in fact overcounted there.
4. The order of equal residuals was promised and untested. The promise is withdrawn.
5. The refusal for a decomposition that does not settle was never reached. A test builds the kernel with one sweep
   allowed and sees it.
6. The threshold's edge is tested on exact numbers, with the limit above stated.

My own mutation run on these found one check of mine that nothing could reach (a second test for an infinite
residual, which the test of the total already covers); it is removed.

## Not in this branch

- **The config fault** that switched the sheaf off. Its fix changes what runs against live stores, so it gets its own
  branch and its own read.
- **The threshold.** 0.05 was calibrated in June on a smaller store; 0.02 catches two thirds of the control and would
  also split 20 real summaries, which someone has to look at before it is chosen.
- **`ncat.py` using `native_build.py`.** It keeps its own copy until its C++ port lands, so the two branches don't
  collide. A fix to one belongs in both until then.
- **A Rust binding in `v2`.** When the room has something to glue.
- **A sheaf over the roads.** The engine now takes any graph and any maps, so the road network from `ncat_store.py`
  can be its base, with a map along each road. Nothing does that yet.
