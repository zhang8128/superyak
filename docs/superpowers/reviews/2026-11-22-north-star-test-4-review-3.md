# Test 4's spec, review 3: the re-check of Serenity's 53c0f6e5 (review 1's advisories 3 to 6), verbatim

The same fresh reviewer checked 225014e4..53c0f6e5 by diff and section hashes, and rebuilt 400 base worlds under
three readings the text allows (Tardis's session scratchpad, `t4/draws.py`, not committed).

---

**Re-check 2, test 4's spec at 53c0f6e5: APPROVED WITH REQUIRED CHANGES (one).** Serenity's commit changes no mechanic
and fits nothing to the policies. Its claim that the worlds can be rebuilt from the text alone is false.

**Verified by diff and hash**
- **Hunks:** every hunk lies at lines 223–314, inside "The worlds", which runs from line 211 to "## Decided" at 315.
- **Hashes:** "The policies" still hashes to 003232cd. "The worlds" moves from 231880cf to eefd8269. "The contract"
  (f0971788), "Stage A" (381d187c) and "Decided" (1e0b0378) are the same at 225014e4 and 53c0f6e5.
- **Advisories 3 to 6** are taken as claimed.
- **225014e4's contract edit** makes review 2's required change as given.

**1. Mechanic changes or fitting: none.**
- The policies use names only to test whether two are equal: fixed counts tries by name, and adaptive by name keys on
  it. A level's order still comes from the seeded permutation. So giving idea `i` word `i`, rather than a drawn word,
  leaves each policy behaving the same way.
- The new content string, `trap:D:k:w:i`, is still unique within a world and opaque to the policies.
- The record-only round robin always recovers, by argument. It needs at most `k` tries per state, plus the loop, which
  stays within `2·D·k(+3)`.
- Advisories 5 and 6 are tests and bookkeeping only. Advisory 6's runs that are counted apart are `named()` returning
  None, which the contract already covers.
- A side effect that needs no change: a renamed idea's name now always lies past word `2k`, so its place in the list
  gives it away. No specified policy reads that, and stage B's turns never see the list.

**2. The text does not fix the worlds exactly.**
- I built 400 base worlds under readings that the text allows:
  - drawing the key with `integers` or with `choice`: identical, 400 of 400;
  - drawing "the `k − 1` others without replacement" with `choice(..., replace=False)` or with a permutation prefix:
    0 of 400 identical;
  - permuting `[key] + others` or the sorted list: 1 of 400 identical.
- So "so the worlds are reproducible from this text" (line 245) can't be supported.
- The fingerprint does pin the worlds the implementer actually ran, which is all the measurement needs. But its JSON
  layout ("full tables") isn't defined, so only that same code can reproduce it.

**3. The spec as a whole** is approvable once the change below is made.

**4. The runner's brief is not short again.** "The contract" and "Stage A" are unchanged by this commit, and nothing new
in "The worlds" is needed by the runner or the scorer.

**Required change**
1. **Either name the calls or drop the claim.**
   - (a) Name each draw's call:
     - the key: `rng.integers(2k)`;
     - each level's other ideas: `rng.choice(nonkey, size=k−1, replace=False)`, with `nonkey` in ascending index, then
       `rng.permutation([key] + others)`;
     - `c` and `m`: `rng.integers(lo, hi + 1)`;
     - each single pick: `rng.choice` over the candidates in the level's order (in ascending index for the map's new
       key);
     - each replacement: `rng.choice` over positions in ascending order;
     - the misled set: `rng.choice(nonkey, size=n, replace=False)`;
     - `C1` to `C3`: `rng.permutation` of `Lc`'s options in `Lc`'s order;
     - and define the fingerprint's JSON layout.
   - (b) Or replace the claim with: "so the worlds are fixed by the posted code, which the fingerprint pins."

**Advisory**
1. Stage A's bootstrap (225014e4) says one resample matrix per trap is drawn from `default_rng(20261130)`. Say whether
   that is a fresh generator for each trap, or one generator used for traps 1 to 4 in order. This matters only for a
   pair whose CI sits on the edge of zero.

**What I ran**
- The section hashes at both commits, and the hunk line numbers against the section headings.
- `draws.py`, in Tardis's scratchpad `t4/`: the three readings above, on all 400 base worlds.
