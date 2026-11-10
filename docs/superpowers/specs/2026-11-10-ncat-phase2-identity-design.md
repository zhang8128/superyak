# The n-category core, phase 2: a cell's name between machines, and ids that can be freed

Tardis, 2026-11-10, a draft for a fresh reviewer. It settles the two Musts in Tardis's read of Defiant's C++ plan
(`defiant/ncat-cpp-plan` d12b2609, read in afbb0744) before phase 2 builds on them. Phase 1, the C++20 port behind the
same interface, is `tardis/ncat-cpp`. Nothing here changes phase 1's calls or answers.

**When it's built:** only once the store holds real sessions from both ships, a few hundred used recalls (Tardis's T3,
after Rio Grande's doubt in 10acd21c). This is written now so the reviewer can settle it before anything depends on it.

## 1. Why

Phase 2 makes two changes that the kernel's identities don't survive as they are:
- **Digests:** a cell gets a 256-bit content digest, its name outside the process. Today a cell's canonical words carry
  each element's `label`, which is the category's own generator number (`ncat_kernel.c:412`; `ncat.py`'s `key()` says
  "stable within this category's generator numbering"). Hash those words, and the same cell built on another machine,
  or in another process with its generators made in another order, gets another name.
- **Freeing:** cells are reference-counted, and memo entries become weak. Once a freed cell's id is reused, a memo entry
  that still names the old id would answer for the new cell. That's a silent false equality, the worst answer the
  kernel can give.

## 2. A generator's name, and a cell's digest

**What the kernel already guarantees.** The canonical traversal (`walk`) never reads a label: every choice is forced by
dimensions and faces, and regular molecules have no automorphism. So a cell's element order is the same whatever its
generators are called. The labels only ride along in the words. That makes the fix an encoding, not a new algorithm.

**A generator's name** is 32 bytes, given when it's made:
- A new call, `ncat_gen_named(ctx, s, t, name, 32)`, takes a name from the caller. For the store, the name is a hash
  of what the generator stands for, for example a memory's record id, so two homes holding the same record make the
  same generator.
- A generator's name also fixes its boundary: `name' = H("ncat gen v1" ‖ name ‖ digest(s) ‖ digest(t))`. Two
  generators with the same caller name and different boundaries never share a name.
  An object (a 0-cell, made with `s` and `t` both −1) has no boundary to bind, so its name is the caller's name alone.
- `ncat_gen` keeps working and keeps phase 1's answers. Its generators get a local name,
  `H("ncat local v1" ‖ category nonce ‖ ordinal)`, and every cell built from one is marked **not portable**.

**A cell's digest** is `H("ncat cell v1" ‖ formal ‖ for each element in canonical order: dim, name(label), nin, nout,
in..., out...)`, with every integer as 4 bytes little-endian.
- Faces are positions in the canonical order, as today, so they're the same on every machine.
- A cell is portable when all of its generators are named. Its digest then names it on any machine that holds the
  same generators.
- H is SHA-256 from a small implementation in the source, as the plan says, so the kernel takes no dependency.
- The version strings let a later canonical form, Q's in phase 3, change the digest without colliding with this one.

**Within one process, nothing changes.** Interning still compares words, and equality is still two ids compared. The
digest is computed when asked (`ncat_digest(ctx, cell, out32)`) and memoized per cell.

## 3. Ids that can be freed

**Cell handles become 64-bit:** the generation in the high 32 bits, the slot in the low 32.
- A slot's generation goes up by one each time its cell is freed, so a stale handle never matches a live one.
- Every call that takes a cell checks the handle's generation against the slot's and answers `NCAT_EARG` on a stale
  handle, never another cell's answer.
- **The memo stores full handles, as keys and as values.** A hit whose key or value names a slot of another
  generation is a miss, and the slot is cleared. So a freed composite is recomputed, never answered with a stranger.
- Phase 1's 32-bit calls stay until `ncat.py` moves to the 64-bit ones. In phase 2 nothing is freed through them, so
  their ids stay as stable as today's.

**What was considered and not chosen:** never reusing ids. That needs no generations, but a dense id table then grows
with every cell ever made, and the plan's point is memory of live cells only. A sparse map for it costs every lookup.

## 4. Tests, each failing without its change

1. **The same cell on two machines:** two categories make the same named generators in different orders and build the
   same composite. They get equal digests and unequal local ids.
2. **Different boundaries, the same caller name:** the digests differ.
3. **Not portable:** a cell with one unnamed generator says so, and its digest differs between two categories.
4. **The digest ignores construction:** a path built step by step and the same path built by halving get one digest.
5. **A freed id never answers for another cell:** compose a and b, free the composite, make a new cell in the same
   slot, then compose a and b again. The answer is a fresh composite, not the new cell, and the old handle is
   `NCAT_EARG`.
6. **The differential oracle stays:** phase 1's comparison against the C kernel keeps running for every call phase 1
   has. The new calls are compared against a Python reference of section 2's encoding.

## 5. Decisions for the reviewer

- **D1:** names, not numbers, cross machines. A generator's name is the caller's 32 bytes bound to its boundary.
- **D2:** the digest is an encoding of today's canonical words with names in place of labels, versioned. That's sound
  only because the traversal reads no label. The reviewer should check that claim against `walk`.
- **D3:** 64-bit handles with generations, and memo hits checked on both sides.
- **D4:** phase 1's calls and answers stay as they are until `ncat.py` moves over.
