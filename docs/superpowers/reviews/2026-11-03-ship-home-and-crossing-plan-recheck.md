# Plan re-check: ship home and crossings (plan revision 2, de6d98af)

**Verdict: APPROVE WITH CHANGES.** M1 and M2 are closed, and the nine Should-fixes are applied. The four items below
are small. Each can be folded in during the build, and none needs another re-read.

## Closed

- **M1:**
  - The guard covers all eleven tools on their raw arguments, before any write. Every write site cited matches:
    server.py:3448, 3455, 3500, 3506, 3654, 4105, 4260 and 4576.
  - `challenge_instinct` and `retire_instinct` are checked before they change the instinct.
  - Each tool has its own mutant, plus mutants for the wrapped text and for the late placement.
  - `_mutation_logged` records metadata only (server.py:68-87), so a refused call leaves no text behind.
- **M2:**
  - `_parents` (permissions.py:575-576) is read from the state of each frame (lighthouse_daemon.py:876).
  - The sharpened test is right. A `self` allow fails at a root place. After `add-parent`, dominators(outside-home)
    holds the home, so without M2's check the home layer, the outside-home layer and the holding place would all pass,
    and it would deliver.
- **The rest:**
  - S1: the records match `Selector`, and `home_of` gives `place:home/<owner>`.
  - S3: the flock copies `federation_lock` (dispatch.py:34-45).
  - S6: `grant-remote`.
  - S7: WAL, with busy told apart from unreadable.
  - S8, S9, nits 1 to 7, and B1 to B8.
  - The new citations I checked all match.

## Still open

**1. S4's test doesn't kill S4's mutant.**
- Both of Task 8's cases decide the same way under the mutant, where denies lose their wildcards too:
  - "a `*` deny refuses when no exact allow names it" is refused anyway, as `NO_MATCHING_ALLOW`;
  - "an exact allow beats a `*` deny" passes either way.
- *Fix:* add a tie. Take a deny with `publishers: ["*"]` and an exact purpose, and an allow with the exact ref and
  `purposes: ["*"]`. The deny must win, with `EXPLICIT_DENY` and its rule id. Under the mutant, the allow wins.

**2. Spec 2.5 still says "every tool that stores text at the home".** These tools store free text unguarded, though
none of them is a memory or reaches `wake`:
- `log_outcome`'s `note` (server.py:3255);
- `instinct_feedback`'s `context` (:3380);
- `share`'s `reason`, which goes into the published house (:2383);
- `assessment_report`'s free-text fields (:3904-3948).

*Fix:* guard them, or narrow the sentence and name them as exceptions. This one was left out of my first review.

**3. The stated limit after nit 8 is narrower than the gap.** Any delivered sentence under 12 words is never recorded,
whatever the size of its item. A 12-word sentence with a non-marker prefix on the same line ("Note: …") is not caught
either. *Fix:* state the general rule: only whole items, and whole sentences of 12 words or more, match after markers
are stripped.

**4. Small build details:**
- **The WAL guard.** It must not call a WAL file with no `-wal` or `-shm` "unreadable" when it opens it read-only, or
  every write is refused. Open it read-write, or test that case.
- **`federation-listen` on a held `crossing.lock`.** It exits 1, which also stops events and pulls. Say that's
  intended, or start without the socket and log.
- **`grant-remote`.** Name its rule id and `validFrom`. Guard against two runs at once, with a lock or a digest
  compare before the rename.
