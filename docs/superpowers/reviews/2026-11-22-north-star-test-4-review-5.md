# Test 4's spec, review 5: the final verdict on 50ec901e, verbatim

The same fresh reviewer checked 08a0cd7b..50ec901e by diff and section hashes, and gave its verdict on the spec as a
whole. Its rebuild script is in Tardis's session scratchpad (`t4/rebuild.py`, not committed).

---

**Review 5, test 4's spec at 50ec901e: APPROVED.** This is the final verdict on the spec as a whole.

**Diff check**
- The diff from 08a0cd7b to 50ec901e changes the spec only at the two edits review 4 asked for, both inside "The
  worlds" (lines 212–333). Git shows them as one hunk at line 323, not two.
  - The example's budget is now 27.
  - `states` now holds every state except `G`.
- The section hashes match your claims:

  | Section | Hash | Changed? |
  |---|---|---|
  | The worlds | 6170a0ce | yes, by these two edits |
  | The policies | 003232cd | no |
  | The contract | f0971788 | no |
  | Stage A | e48ce781 | no |
  | Decided | 1e0b0378 | no |

- The only other file 5cb18ee3 adds is review 4, under docs/superpowers/reviews/.

**The verdict on the whole**
- Every required change from reviews 1 to 4 is made.
- The policies section has changed since draft 2 (8b56bd8e) only through review 1's V2 to V5. Those were readings the
  text already forced or that I wrote, and I checked them in review 2.
- The world rules are unchanged in mechanics since bdf0eba5. The edits since then were tests, the named draws and the
  fingerprint.
- Neither half is fitted to the other.
- The runner's brief, "The contract" plus "Stage A", holds everything the runner needs.

**One check for the build:** building all 800 worlds as the text says, with `G` left out of `states`, gives the
fingerprint `ceb09639edbe0c0a2c9c5b3c3c8baa91f40eed31d713f1c74201eaddd8fa065e` on numpy 2.4.3. The fresh world
implementer's fingerprint should match it on that numpy version. If it doesn't, one of the two builds has a bug, and it
should be found before any policy runs.

The script that produced it is `rebuild.py` in Tardis's scratchpad `t4/`.
