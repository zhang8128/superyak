# A real n-category: the kernel, and where the speed comes from

Tardis, 2026-11-07, for Andy's "even the basics aren't properly built like n category theory graph structure" and "write it in C
if needed for performance". It answers stage 2 of Rio Grande's plan on issue #2, and the plan's open question about equality.
It needs a fresh reviewer, like any spec. The code is `engram/ncat_kernel.c`, `engram/ncat.py`, `engram/tests/test_ncat.py`. It
has no storage, and nothing in Engram calls it yet.

## What it is

The free strict n-category on a polygraph (computad), with n up to 15. Generators have checked boundaries, every cell has an
identity, and cells compose along every lower dimension.

A **cell is a labelled shape**: a regular molecule (Hadzihasanovic), meaning a graded poset with oriented faces built by pasting
atoms, and a map from its elements to the generators. An identity is the same shape one formal dimension up.

**Why not chain tables (Steiner).** There, composing is adding, so the laws hold by arithmetic, but addition commutes: two loops
at one memory come out equal, and memory graphs have cycles. A labelled shape is the "unrolling" the plan found it needed. The
shape stays loop-free and the map to the generators needn't be injective, so `f then g` and `g then f` differ with nothing extra.

**Equality, the plan's open question.** Molecules have no automorphisms, so a traversal that makes only choices the shape forces
gives every element one canonical position (`walk`). Two cells are equal exactly when their canonical words are, and cells are
interned, so comparing them is comparing two integers. In dimension 2 this is the known result: boundary-connected planar diagrams
have linear-time equivalence (Delpeuch and Vicary). In general, isomorphism of these shapes is polynomial (Hadzihasanovic and
Kessler, O(n³ log n), with rewalt as their implementation).

**Refused, and said:**
- A generator with an identity boundary: it would bring Eckmann-Hilton, where 2-cells on an identity commute.
- A generator whose boundary isn't round. Two 2-cells side by side touch at a point, so a 3-cell can't have that as its source.
  This is a real limit against the full free 3-category, and a person could want such a cell.
- A shape that isn't loop-free in Steiner's sense, which starts at dimension 4. Two top elements can each feed the other through a
  lower dimension, so no way of building the cell keeps them apart, and interchange can't relate their two orders. They may also share
  no face of the dimension below, so the shape can't record which came first. The free category tells them apart, and a shape can't.

**A correction.** This spec first said the kernel "answers exactly or refuses". That was false at n = 4. Rio Grande's reference, written
without seeing this code, found a composite of two 4-cells on round generators where the kernel said A;B == B;A and the reference
said they differ. Rio Grande's hand argument holds: it's torsion in Forest's sense. Hence the third refusal above. It starts at 4 because
in a planar 2-cell two blocks can't each feed the other without their wires crossing.

**What's proved and what's tested.**
- **n ≤ 2:** published results, as above.
- **Loop-free shapes, any n:** Steiner's theorem says such a complex's free omega-category is generated freely by its atoms, so any way
  of building the whole shape gives one cell, and a map to the generators sends it to one cell. That's my reading of his theorem and my own
  step for labelled, non-injective shapes. It needs a mathematician's read.
- **Laws:** by test, and known answers check that nothing's over-identified at the counts below.
- **Differential:** Rio Grande's reference agreed at n ≤ 2 on 726,598 pairs and n ≤ 3 on 370,705 pairs, 0 disagreements. Rio Grande notes that
  deep interchange at n = 3 may be thinly covered. Those runs predate the loop-free check.

**If the quotient is wanted.** Where independent rewrites commute might suit memory better than the free category does: lawful, and what the
kernel did before this check. That would be a decision to make and name, not a default.

## Evidence (all run on Tardis, all synthetic)

- **Known answers:** planar binary trees give the Catalan numbers, in dimension 2 up to m = 7 and in dimensions 3, 4 and 5 up to
  m = 5. Beads on wires and marks on sheets, stacked and side by side, give stars and bars. Two bead types keep their order.
- **Laws, on random polygraphs up to n = 5:** globularity, units, associativity, boundaries of composites, identities respecting
  composition, interchange. Tests count that the top dimensions and interchange were really reached.
- **A second traversal in Python, on randomly renumbered elements and faces,** recovers the same canonical words. Same author and
  same algorithm, so it checks numbering-independence and the C, not the mathematics.
- **Torsion:** Rio Grande's example is refused both ways round, and the same 4-cell twice still composes. 24 random seeds up to n = 3 never
  hit the refusal.
- **Under ASan and UBSan:** clean on the known answers, refusals and units.
- **14 mutants of the C:** 10 caught. Of the 4 survivors, 1 was a real gap, now tested (only one side of the round check). 3 are
  equivalent by argument: face lists keep their atom's order anyway, the hash already holds the formal dimension, and the unit
  shortcut gives what gluing gives.

**Not done:** the rewalt cross-check (installing it was refused on Tardis, so it needs Andy's yes or the Pi), a rerun of the differential
at n ≤ 4 with the check in, and any independent mathematician's read. No agent's agreement counts as independent evidence.

## Is C needed? Measured

One more composition, on one core of Tardis. The C column is the whole composition; the Python column is the canonicalising alone,
in a straightforward port, so it understates the gap.

| Shape | Elements | C | Python | Ratio |
|---|---|---|---|---|
| Path of 50 | 101 | 11 µs | 572 µs | 53 |
| Path of 1,000 | 2,001 | 165 µs | 13.7 ms | 83 |
| Tree of 100, front 101 | 403 | 549 µs | 28.4 ms | 52 |
| Tree of 400, front 401 | 1,603 | 4.3 ms | 317 ms | 73 |
| Stack of 50 sheets, 100 marks | 303 | 1.2 ms | 48.4 ms | 39 |

So yes for canonicalising, which every new composite pays for. No for the store's generators: Rio Grande measured 37 µs to write a
1-cell in Python on SQLite, on the Pi. Only this kernel needs C, as one dependency-free file. Compiling needs a C compiler on each
machine, and that's the cost to weigh: it's cached under `~/.cache/superyak/ncat`.

## Where the speed really comes from: the mathematics

These matter more than the language, and they're the order I'd build in.

1. **A functor needs no normal form.** A functor respects the laws, so any presentation of a cell gives the same answer. Cost,
   holonomy and restriction maps can be computed from how a cell was built, in constant time per composition, and memoised on the
   interned cells. Only *equality* pays for canonicalising, and it pays once per distinct cell.
2. **Store generators and used composites, interned.** The closure of even a small graph is enormous and never needed. This is
   already the plan's choice, and interning makes it cheap.
3. **Above the kernel, work in the thin quotient.** If a 2-cell only says a route can replace another at no more cost, hom-sets are
   posets, and that's a category enriched in ([0,∞], ≥, +), a Lawvere metric space. Parallel 2-cells are then equal, so 3-cells say
   nothing there, and n stops at 2 for cost. Keep the free kernel for provenance, and answer queries in the quotient. Composition
   is the min-plus matrix product, and all-routes is its Kleene star.
4. **A rail is a 2-cell.** A shortcut that costs no more than the route it replaces is exactly such a cell, and contraction
   hierarchies and hub labels are systematic choices of them, known to give microsecond exact queries on road networks. Memory graphs
   may be small-world, where these degrade, so that's a measurement to make, not an assumption.
5. **A heuristic is a cochain.** A* with potential π is Dijkstra on w − δπ, and consistency is δπ ≤ w, the dual of shortest paths. So
   the best heuristics are the largest feasible 0-cochains, which is where landmark bounds come from, and the cost's class in H¹ measures
   how far it is from being path-independent.
6. **Most sheaf cohomology needs one rank.** dim H⁰ − dim H¹ = Σ dim F(v) − Σ dim F(e), so rank δ gives both. With identity maps it needs
   no linear algebra at all: H⁰ and H¹ are k·β₀ and k·β₁, which is union-find, near-linear. So the audit's warning has teeth: until
   stores really differ, the maps are identities and cohomology carries no information about the data. Real maps need only a sparse,
   matrix-free Laplacian.

## Next, as split with Rio Grande

Agreed on 2026-11-07. Tardis keeps this kernel, its sanitizer builds and its law tests. It parses nothing from the network and takes only
validated input. Rio Grande has the spec's reviewer, the store, traversal in C, packaging, and the slow reference from the spec alone, which
is the independent implementation this lacked and has already found one real error here. Each attacks the other's work. Then come the thin
quotient and the sheaf (stages 4 and 5). Rails stay behind E1′, as the plan says: the mathematics can be right and rails can still not help
anyone explore further.

## References

- A. Delpeuch, J. Vicary, *Normalization for planar string diagrams and a quadratic equivalence algorithm*, LMCS 18(1), 2022.
- A. Hadzihasanovic, D. Kessler, *Data structures for topologically sound higher-dimensional diagram rewriting*, ACT 2022, EPTCS 380.
- S. Forest, *Unifying notions of pasting diagrams*, Higher Structures 6(1), 2022.
- R. Steiner, *Omega-categories and chain complexes*, Homology, Homotopy and Applications 6(1), 2004.
