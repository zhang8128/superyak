# Test 4's spec, review 4: the re-check of Serenity's 08a0cd7b (each draw's call named), verbatim

The same fresh reviewer checked bc1e461b..08a0cd7b by diff and section hashes, and rebuilt all 800 worlds from the text
twice in two coding styles (Tardis's session scratchpad, `t4/rebuild.py`, not committed).

---

**Re-check 3, test 4's spec at 08a0cd7b: APPROVED WITH REQUIRED CHANGES (two one-line edits in "The worlds").** With
both made, I approve the spec as a whole. The only further check needed is a diff showing nothing else changed, all of
it inside "The worlds".

**Your claims, verified**
- **Hunks:** every hunk of bc1e461b..08a0cd7b lies inside "The worlds", which runs from line 212 to "## Decided" at
  333. "The worlds" moves from eefd8269 to d108573c.
- **Unchanged sections:** "The policies" is still 003232cd, "The contract" is still f0971788, and "Decided" is
  unchanged.
- **Stage A:** it moves from 381d187c to e48ce781 through bc1e461b alone, and that change is only the fresh
  `default_rng(20261130)` per trap, as I advised.

**1. The worlds are now fixed exactly.** I built all 800 worlds from the text twice, in two coding styles. One passed
Python lists to `rng.choice` and `rng.permutation`; the other passed numpy arrays, using `setdiff1d` and
`flatnonzero`. Both runs produced the same fingerprint, `ceb09639…8fa065e`, on numpy 2.4.3. In review 3, the old text
gave 0 of 400 identical base worlds.

**2. The fingerprint layout leaves one choice open.**
- The layout never says whether `"G"` is in `states`. Adding `"G": {"options": [], "step": {}}` changes the hash to
  `21bcb5f6…`.
- The example shows `"trap": 1, "D": 4, "k": 3` with `"budget": 24`. Trap 1's budget is `2·D·k + 3`, which is 27
  there.

**3. Nothing changes a mechanic or fits the policies.** The named calls only restate draws the text already had, and
`n = max(1, (2k − 1) // 2)` is the earlier rule. The "static table" sentence is equivalent to the dynamic wording: in
trap 4 the only arrival at `Lm` is `step(L{m−1}, key)`, so the observation sits on that one entry. The numpy-version
note and the per-trap bootstrap generator touch reproducibility only.

**Required changes**
1. In the fingerprint paragraph, say that `states` holds every state except `G`, or else name `G`'s entry.
2. In the example, change `"budget": 24` to `27`, or change its trap to 2.

**What I ran**
- The section hashes at 53c0f6e5, bc1e461b and 08a0cd7b, and the hunk line numbers against the section headings.
- `rebuild.py`: all 800 worlds from the text, in both styles, fingerprinted by the stated `json.dumps` layout, plus the
  variant with `G` included. It is in Tardis's scratchpad `t4/`.
