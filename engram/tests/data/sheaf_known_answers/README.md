# Known answers for the sheaf kernel

These are the vector cases of the sheaf standard `superyak-sheaf/1`. Defiant worked them by hand and Tardis added the
loop and parallel-edge cases. They're copied unchanged from `docs/standard/sheaf-known-answers/` on branch
`defiant/sheaf-core` at 61312351.

`test_sheaf_known_answers.py` checks the C kernel (`engram/sheaf_kernel.c`, through `sheaf_native.py`) against each
one: `dim_h0`, `dim_h1`, and, where the case gives local data, `glued`, `residuals`, `residual_edges` and
`distance_squared`. The holonomy cases' `holonomy_frobenius` and the four set-valued cases are outside what this kernel
computes, so they aren't copied here.
