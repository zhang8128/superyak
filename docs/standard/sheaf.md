# The Superyak sheaf standard, version 1

This page defines what Superyak means by a sheaf, by gluing and by cohomology, exactly enough that someone who has
never seen Superyak's code can implement it and check their answers. The files in
[`sheaf-known-answers/`](sheaf-known-answers/) are the test: each holds a small sheaf and the answer any correct
implementation gives.

Nobody owns these definitions. They are ordinary mathematics (cellular sheaves on a graph). What this page adds is a
file format, a rule for rounding, and the known answers.

**Scope of version 1.** Sheaves on a finite graph, with vector-space stalks or finite-set stalks. Cohomology is that
of the graph: H⁰ and H¹. Pairs of parallel routes ("faces") are used to compare the routes, and they do not enter the
cohomology. Version 1 says nothing about where a sheaf's maps come from.

## 1. The base

A **base** is a finite list of **nodes**, each with a unique name, and a finite list of **edges**. Each edge has a
**tail** node and a **head** node. The orientation is bookkeeping: reversing an edge (and swapping its two maps)
changes no answer on this page. Parallel edges and loops are allowed. Edges are numbered from 0 in the order listed.

A **route** is a list of steps. A step is an edge number and a direction: `+1` goes tail to head, `−1` goes head to
tail. Each step must start where the last one ended. A **face** is two routes with the same start and the same end.

## 2. A sheaf of vector spaces

It assigns:
- to each node v a dimension n(v) ≥ 0; the stalk is ℝ^n(v);
- to each edge e a dimension m(e) ≥ 0; the stalk is ℝ^m(e);
- to each edge e two matrices with m(e) rows: the **tail map** A(e), with n(tail) columns, and the **head map**
  B(e), with n(head) columns. They carry a node's data to where the two ends are compared.

**Local data** x is one vector x(v) per node. Its **residual** on edge e is the vector

    r(e) = B(e) · x(head e) − A(e) · x(tail e)

The map x ↦ r is linear. It is the **coboundary** δ, a matrix with Σ m(e) rows and Σ n(v) columns.

- A **global section** is local data with every residual zero. The global sections form the space **H⁰** = ker δ.
- **H¹** is the space of edge data modulo residuals: ℝ^(Σ m(e)) / im δ.
- So dim H¹ = Σ m(e) − Σ n(v) + dim H⁰.

H⁰ is what all the nodes can agree on. H¹ counts the independent ways edge-by-edge comparisons can fail to come from
any single assignment. On a tree H¹ is always zero for surjective maps; it takes a loop to make one.

### 2.1 Rounding

On real data a rank is a judgement, so the judgement is part of every answer.

Let σ₁ ≥ σ₂ ≥ … be the singular values of δ. With a tolerance `tol` (default 10⁻⁹), a singular value counts as zero
when σ ≤ tol · σ₁. If δ is the zero matrix, or has no rows or no columns, every singular value counts as zero. Then

    dim H⁰ = Σ n(v) − (the number of singular values that do not count as zero)

An implementation reports the tolerance it actually used. If it cannot honour the requested one, it uses a larger one
and says so. It also reports the **gap**: the smallest singular value it kept and the largest it dropped, each
divided by σ₁. A wide gap means the rank is not in doubt.

### 2.2 Gluing

Local data x **glues** when every residual has Euclidean length at most `glue_tol` (default 10⁻⁹, an absolute
length). An implementation reports:
- the length of each residual, in edge order;
- the edges whose residual is longer than `glue_tol`;
- the **nearest global section**: the point of H⁰ closest to x in Euclidean distance, and the squared distance.

### 2.3 Comparing two routes

Crossing edge e from tail to head carries a vector by T = B(e)⁺ · A(e), where ⁺ is the Moore–Penrose pseudo-inverse.
From head to tail it is A(e)⁺ · B(e). A route's **transport** is the product of its steps' matrices, the first step
rightmost. The **holonomy** of a face is the transport along its first route minus the transport along its second.
It is zero when the two routes carry data the same way. An implementation reports its Frobenius norm.

## 3. A sheaf of finite sets

It assigns:
- to each node and each edge a finite set of strings, its stalk;
- to each edge e two total functions into its stalk: the tail map from the tail's stalk, the head map from the
  head's.

**Local data** picks one element x(v) from each node's stalk. It **glues** when, on every edge, the tail map of
x(tail) equals the head map of x(head). The edges where they differ are the **residual edges**. A **global section**
is local data that glues. An implementation reports the number of global sections.

There is no rounding here: answers are exact. Counting sections can take time exponential in the size of a densely
looped base, so an implementation may refuse a file as too large, and must say that it refused. It must never return
a guess.

The permission check in Superyak is of this kind: a stalk is a set of allowed uses, and restriction is intersection.
For such a sheaf, subsets that agree in pairs always glue, to their union
([`set-powerset-union.json`](sheaf-known-answers/set-powerset-union.json)). The twisted triangle
([`set-twisted-triangle.json`](sheaf-known-answers/set-twisted-triangle.json)) shows the other case: every edge can
be satisfied alone, and no assignment satisfies them all.

## 4. The file format

A file is one JSON object, in UTF-8.

| Field | Meaning |
|---|---|
| `standard` | the string `superyak-sheaf/1` |
| `kind` | `vector` or `set` |
| `nodes` | a list of `{"id": name, "dim": n}` for `vector`, or `{"id": name, "stalk": [strings]}` for `set` |
| `edges` | a list of `{"tail": name, "head": name, "dim": m, "tail_map": M, "head_map": M}` for `vector`; for `set`, `"stalk": [strings]` in place of `dim`, and each map is an object from every element of the node's stalk to an element of the edge's stalk |
| `faces` | optional, `vector` only: a list of `{"a": route, "b": route}`, a route being a list of `[edge number, 1 or -1]` |
| `local` | optional: an object from every node name to its vector (a list of n numbers) or its element |
| `tol`, `glue_tol` | optional numbers, `vector` only |
| `why` | optional text for readers |
| `expect` | optional: the answers this file claims, as in the table below |

A matrix M is a list of rows, each a list of numbers, or the string `identity`, which is allowed only when the edge
and the node have the same dimension. Numbers must be finite. Names are non-empty strings and unique among nodes.
Anything else in the file is an error, and an implementation refuses the file.

| `expect` field | Kind | Meaning |
|---|---|---|
| `dim_h0`, `dim_h1` | vector | the dimensions |
| `glued` | both | whether `local` glues |
| `residual_edges` | both | the edge numbers where it does not, ascending |
| `residuals` | vector | each residual's length, in edge order |
| `distance_squared` | vector | squared distance from `local` to the nearest global section |
| `holonomy_frobenius` | vector | one number per face |
| `sections` | set | the number of global sections |

Numbers in `expect` are compared to within 10⁻⁹.

## 5. Conforming

An implementation conforms to version 1 when, for every file in [`sheaf-known-answers/`](sheaf-known-answers/), it
computes every field that the file's `expect` names and matches it. Superyak's own implementation is checked this
way:

```sh
engram-sheaf check docs/standard/sheaf-known-answers/*.json
```

The known answers were written from the definitions above and worked by hand. If Superyak's code and this page ever
disagree, the page is right and the code has a bug.
