# Test 4's spec, review 2: the re-check of draft 3 (bf1097c0) against review 1, verbatim

The same fresh reviewer as review 1 checked draft 3 by diff and by section hashes, and ran draft 3's four policies on
its own world code (Tardis's session scratchpad, `t4/draft3.py` and `draft3.log`, not committed; its numbers are
indicative only, not stage A's).

---

**Re-check of draft 3 (bf1097c0) against review 1: APPROVED WITH REQUIRED CHANGES.** All nine of review 1's required
changes are made as required. Draft 3's own choice of who writes the runner brings in one new gap, which is the single
required change below.

**What I checked, by diff and hash**
- **Hashes.** "The policies", from its heading to "## Stage A", hashes to 8b56bd8e…ba48b1d at bdf0eba5 and
  003232cd…d473fa at bf1097c0. "The worlds" hashes to 231880cf at both commits, and "Decided" is unchanged. The diff
  touches nothing after "## The worlds".
- **The nine changes:**
  - **V1 and V2:** the "exact forms" paragraph covers everything review 1 listed.
  - **V3:** the per-call generators are exactly as I gave them, with seeds 0–19 shared by a world and its twin.
  - **V4:** fixed's reading is the one the text forces.
  - **V5:** the `premise` drop is stated, and the timing of `contradiction` and `premise` is stated.
  - **V6:** the trap effect, the pairs, the bootstrap and naming kept outside the ceiling are all as required.
  - **V7:** the traps are named for stage B now.
  - **V8:** B's sizing claim is replaced, and my advisory 7 (what a real turn works on in B) is taken.
  - **V9:** points (a) to (e) are added, with advisory 1's disclosure.
- **The three choices you asked me to judge:**
  - **(i)** Raising `repeat` at every call is sound. It matches trap 2's naming rule and the original wording.
  - **(ii)** Counting the start as the first arrival at "L0" is harmless. No world returns to L0, and it agrees with
    the arrival definition.
  - **(iii)** Raising `contradiction` and `premise` once is sound. No choice, naming call or false name depends on it.
- **The `premise` drop including its own turn** is the literal reading of "earlier verdicts" for an observation made on
  arrival, and it moves one count.
- **Fitting:** nothing in "The policies" reads as chosen from a world rule or from my numbers. Each change is either my
  text or a reading I showed the text forced. The one number added, fixed's 52 of 100, is labelled as mine and not
  stage A's.

**Required change**
1. **The runner's brief lacks what it needs.** The third agent reads only "The contract" and "Stage A", which leaves
   three gaps:
   - The policy seeds (0–19, shared by a world and its twin) appear only in "The policies", line 122.
   - The list of 800 worlds appears only in "The worlds", lines 204–206 and 259–261.
   - The contract never says how the agent builds a world, finds its twin or gets the policies. It also doesn't say
     which flag counts as "the trap's flag" for a false name, so the agent can't compute false names.

   Fix: add three items to the exact forms. This touches only the contract, so the policies section's hash stays as it
   is.
   - **(a)** The world half exports `worlds()`, which yields every world with its trap (1–4), D, k, w and form. It
     also exports `false_named(world, record, flags_per_call) -> bool`, which is true when the trap's flag (1 `cycle`,
     2 `repeat`, 3 `contradiction`, 4 `premise`, any value) appears at any call of a twin run.
   - **(b)** The policy half exports `fixed`, `random`, `adaptive_name` and `adaptive_content`.
   - **(c)** The policy seeds are 0 to 19, the same in a world and its twin.

**Advisory**
1. **False names are zero by construction** under the arrival definitions. No twin arrives at a state twice, renames a
   content, has a summary disagree with its verdict, or carries an observation. My draft-3 run found 0 false names in
   2,000 runs for every policy and trap. Say that this checks the code, and is not a finding.
2. **"Raised once" (lines 117–119):** write "once for each such turn". No scored quantity depends on it.
3. **The CI rule has no minimum effect.** These numbers come from my own world code, so they are indicative only:
   - The renamed idea goes to B on fixed's 48-point loss (CI +0.38 to +0.58).
   - The map goes to B on adaptive's 0.55-point loss (CI −0.95 to −0.20 points against fixed).
   - The cycle stays out of B, since all its CIs include zero.

   Don't add a threshold now: any threshold chosen after seeing these numbers decides the map's fate knowingly. B's
   pilot and its affordability rule limit the cost.
4. **One knife-edge:** on the map, adaptive by name against random has an upper bound that rounds to −0.0000. Whether
   it excludes zero depends on the percentile method. Name numpy's default (linear), and say whether all pairs share
   one resample matrix. No trap's fate turns on this in my run.

**What I ran**
- The section hashes above.
- `draft3.py`: draft 3's four policies exactly as written, on my world code, with 100 world pairs per trap and 20
  seeds. That means the generators, fixed's round robin, `cycle` on a later arrival, flags raised once, `repeat` at
  every call, and the `premise` drop including its own turn. It applies V6's bootstrap as specified: 10,000 resamples,
  `default_rng(20261130)`, percentile interval. Named on exposure was 1.00 for each adaptive policy at every trap it can
  flag, and 0 elsewhere.
- Files are in Tardis's scratchpad `t4/`: the script is `draft3.py` and its output is `draft3.log`.
