# Test 4, stage B: do real turns fall into the traps, and does the record get them out? (a proposal)

Draft 3, 2026-11-23. Tardis, with Serenity (goals.md T3; docs/north-star.md row 4). Under station law section 3, a
fresh reviewer approves it in Andy's place, and Andy can veto.

- **Draft 1 (c2edc48b)** was a proposal on Tardis's own recommendation (978741ec), "the turn chooses".
- **Serenity's answer (all hands 004065cf)** says yes to the turn choosing and yes to patch worlds. It asks that the
  content key be frozen, sets `k = 5` with a budget of 7 turns, and asks for each trap's ceiling to be counted before
  the pilot. Serenity defined the three new traps there, and writes their rules into "The worlds" as the world
  builder. Draft 2 makes the rest.
- **Draft 3:** Serenity went down. Andy, at Tardis's terminal, said "serenity is down move on without it". So "The
  worlds" was written by a fresh agent from Serenity's definitions (004065cf) and the spec. It was never shown the arms
  half, which was hashed first (`tardis/test4b-arms` 587ce392, all hands b6821042). Tardis wrote the arms, so it didn't
  write the worlds. Draft 3 also replaces draft 1's wording for the three new traps with Serenity's definitions, as the
  world builder found they disagreed. And it says a turn has no tools, as the world builder asked.

Stage A (test 4's spec, approved; result 4af2eb13) chose B's traps by its own rules: **the renamed idea**, by its CI
rule, and **the misleading summary**, by its reads clause. Long cycles, keys that vary by state, and a change without
an observation are designed fresh here, never from A's numbers (9b, 9c and 9e in that spec's "can't show").

## The question

When each turn is a fresh agent that forgets everything but the record, does it fall into a renamed failed idea or a
misleading summary? Does the record, or the record with structure, get it out within one turn budget?

## Why the turn chooses

In the approved sketch, a policy chooses and the turn only does the work. Then only the summary trap reaches a real
agent, and B would repeat A at a higher cost. Here **the turn chooses**: it reads what its arm gives it, picks one
approach, works it, and writes its summary. The arms differ only in what the turn is given.

## The worlds: small code tasks whose approaches are patches

- **A world** is a small code task: a function, a frozen test, and `k` candidate patches. Each patch has a written
  description, which is its name, and a diff. **Its content is frozen as the sha256 of the patched target file,
  normalized:** CRLF becomes LF, trailing whitespace is stripped from each line, and trailing blank lines are dropped.
  So whitespace and hunk order can't split one idea into two keys. "The same idea" is exact against a given base,
  and B needs no rule for when two written descriptions are one idea. When the base file moves (the state-varying
  trap), the same idea gets a new key, as that trap intends.
- **Exactly one patch passes the frozen test.** The world half's own test checks that before any turn runs. The smoke
  run for this draft found why it's needed: a toy median task's test let the mean pass too.
- **A turn's work:** apply the chosen patch to a fresh copy, run the frozen test, and report `verdict`, written by the
  harness from the test's exit code, never by the turn. The turn also writes its `summary`.
- **Recovered** means a turn applied the passing patch.
- **The traps,** each with an untrapped twin as in stage A:
  - **renamed idea:** a patch that failed returns with a new description and the same diff;
  - **misleading summary:** the record's summary of a failed patch says "worked";
  - **long cycle (new):** failing patches whose planted summaries lead into one another and back;
  - **state-varying key (new):** the base file moves, so the same failed idea comes back with a new key;
  - **change without an observation (new):** the passing patch's record entry has no verdict, because its turn timed
    out, so recovering means re-trying an approach that was never checked.
- **Who builds them:** the rules are in "The worlds" below, written blind to the arms. A separate fresh agent
  implements them from that section and the spec, blind to the arms too, as in stage A.

## The arms, under one budget

Each turn is a fresh `claude -p` worker in the visitor walk's approved wrapper: bubblewrap, an empty home, its own
sign-in, and `--unshare-pid` (`tardis/visitor-walk-spec`, approved at 344e425a). The model is Sonnet 5.5.
**A turn has no tools** (`--tools ""`, and an empty MCP config): it reads its prompt and replies. It can't apply or
test a patch itself, so it can't sidestep a trap by running all five. The harness applies the chosen patch and runs the
frozen test, as "The worlds" says.

| Arm | What a turn is given, beside the task and the open patches |
| --- | --- |
| **R0** | Nothing: the forgetting baseline |
| **R1** | The record as it is: each earlier turn's patch description, its diff, its verdict and its summary. It holds no content key, so noticing a repeat is the turn's own work |
| **R2** | R1, plus stage A's adaptive-by-content policy's choice and flags, computed from the content keys and shown as advice the turn may ignore. That's the structure R2 adds |

- **A turn's output** is one JSON object: `{"choice": <index>, "summary": <text>, "flags": [...]}`, with the flags
  from stage A's contract. Malformed output is a stall, and that turn is spent.
- **The budget:** with `k = 5` (one passing patch and four failing), 7 turns per world, counted in model calls. Tokens and wall time are recorded beside them, never
  scored.

## Measures, fixed before any turn

- **The trap effect,** per arm and world: the recovery rate in the trapped world minus its twin's, over that
  world's seeded repeats.
- **The primary:** R1 minus R0, and R2 minus R1, as the mean over worlds of the difference in trap effects, with a 95%
  bootstrap CI over worlds. The resample count and seed are fixed in the pre-registration that follows this proposal.
- **Named:** a turn's flag that names the trap, by stage A's naming rules, reported beside the primary, never inside
  it. False names in the twins are reported too.
- **Activity, reported, never scored:** distinct diffs tried in runs that don't recover.

## The size, from a pilot (stage A's V8)

- **Before the pilot, each trap's ceiling is counted without running anything:** the share of worlds in which the
  trap can fire within 7 turns. A trap that can't fire within the budget is changed by its builder before any turn
  runs, never after.
- **The pilot** is 3 worlds per trap, in both forms, in all three arms, with one repeat. That's 5 × 3 × 2 × 3 = 90
  runs, at most 90 × 7 = 630 turns.
- It fixes three things: the turn's cost, the variance of the trap effect, and the number of worlds B needs.
- **The stop rule:** if B's size passes a ceiling fixed with Andy's budget in the pre-registration, B stops, as v2's
  stage 2 pilot did.

## What this can't show, said before the run

- **Patch worlds are authored.** A real research or coding task rarely has `k` named candidates and one frozen test.
- **R2's advice comes from stage A's policy,** so R2 tests that policy's advice to a real agent, not structure in
  general.
- **The turn is Sonnet 5.5,** and other models may fall into the traps differently.

## Decided in draft 2, from Serenity's answer

1. **The turn chooses.** R2 tests the policy, as advice.
2. **Patch worlds for B.** v2's room items can be a later stage.
3. **The three new traps** are Serenity's, written into "The worlds" (still to come):
   - **a long cycle:** failing patches whose summaries lead into one another and back. The record leads into it, and
     exposure is reported, so a null can't pass for an escape;
   - **a state-varying key:** the base moves, so the same idea makes a new key;
   - **a change without an observation:** the passing patch's record entry has no verdict, because its turn timed
     out.
4. **`k = 5` and 7 turns.** Each trap's ceiling is counted before the pilot.

## The worlds (written blind to the arms, from Serenity's definitions)

*From Serenity's definitions (all hands 004065cf), by a world builder blind to the arms. Each trap changes one
mechanic of a shared world, and its twin undoes exactly that. A world reads only which patch each turn applied.*

**The task** is one file, `target.py`, with one function and three wrong constants. Exact keys matter more here than
realism. Base version `j` is the file below, with its revision line repeated for each `k` from 0 to `j`, in order.
Every line ends in LF, and there's one final LF:

```python
"""{fn}: fold a list of counts into one checksum."""
# Revision {r_k}.

MULTIPLIER = 1
OFFSET = 0
MODULUS = 10007

def {fn}(values):
    total = 0
    for i, v in enumerate(values):
        total = (total * MULTIPLIER + v * (i + OFFSET)) % MODULUS
    return total
```

- **Patch `i`** sets the constants to `mult[i]`, `offset[i]` and `modulus[i]`, and changes nothing else. Its diff,
  against the base it's offered on, is `"".join(difflib.unified_diff(base.splitlines(True), patched.splitlines(True),
  "a/target.py", "b/target.py"))`. Its key is the spec's: the sha256 hex of the normalized patched file, joined by LF
  with one final LF. Its description is `The {word} patch: retune MULTIPLIER, OFFSET and MODULUS.`, so only its diff
  says what it does.
- **The task text:** "`target.py` defines `{fn}(values)`, which must match a reference implementation on the frozen
  test's fixed inputs. Its three constants are wrong, and each candidate patch sets all three."
- **The frozen test** belongs to the harness and isn't part of the task text.
  - `test_target.py` has seven LF-ended lines: `import hashlib`, `from target import {fn}`, `INPUTS = {INPUTS!r}`,
    `DIGEST = "{DIGEST}"` and `def test_{fn}():`, then two lines indented four spaces,
    `outputs = [{fn}(values) for values in INPUTS]` and
    `assert hashlib.sha256(repr(outputs).encode()).hexdigest() == DIGEST`.
  - `INPUTS` is `[[1]] + inputs.tolist()`, and `DIGEST` is the sha256 hex of `repr` of the passing patch's outputs.
    So a turn that sees the test can't check a patch without running it.
- **The verdict** is the exit code of `python -m pytest -q -p no:cacheprovider test_target.py`, run in a fresh
  directory holding the patched file and the test. 0 is a pass.
- **Exactly one passes, by construction:** the offsets are distinct and below 50, and every modulus is at least 1000.
  So on `[1]`, patch `i` returns `offset[i]` and the base returns 0. The tests still run every file, because a toy
  median task once let the mean pass too.

**Seeds:** world `w` of trap `t` (1 to 5, numbered as below) comes from `numpy.random.SeedSequence([20261201, t, w])`,
disjoint from stage A's 20261129. One `numpy.random.default_rng` built from it makes nine draws. They come in this
order, and a world and its twin share them:
1. `fn = rng.integers(8)`, into `fold_counts, mix_tally, ledger_sum, score_rows, pack_marks, blend_bins, trail_check,
   vote_digest`;
2. `words = rng.choice(64, size=5, replace=False)`: patch `i` gets word `words[i]` of stage A's list, and the other
   59, in list order, are spares;
3. `mult = rng.integers(2, 100, size=5)`;
4. `offset = rng.choice(numpy.arange(1, 50), size=5, replace=False)`;
5. `modulus = rng.integers(1000, 10000, size=5)`;
6. the passing patch, `p = rng.integers(5)`;
7. `inputs = rng.integers(0, 100, size=(7, 6))`;
8. `rev = rng.integers(0, 16**6, size=8)`, with `r_j = f"{rev[j]:06x}"`;
9. `order = rng.permutation(failing)`, where `failing` is the four indices other than `p`, ascending.

**How many:** 100 worlds per trap (`w` 0 to 99), each in both forms, which is 1,000 fingerprinted together. The
pilot uses `w` 0 to 2. The main run uses `w` from 3 on, as many as the pre-registration fixes, at most 97.

**What a world gives the harness:** the task text, the test, `budget = 7`, `p`, its bases, every patch on every base
(names, diff and key), and the record's planted entries.
- **Planted entries** stand for earlier turns. They're turns 1 to `n`, with `n` set per trap, so the run's turns are
  `n + 1` to `n + 7`. Only run turns count toward the budget, and a planted entry is never a recovery.
- **A planted entry** uses its patch's first name, its diff on `bases[0]`, and one of three summaries. The failure is
  `Applied the {word} patch. The test failed.` A pointer adds ` Try the {next word} patch next.` to the failure. The
  lie is `Applied the {word} patch. It worked.`
- **An entry** holds `turn`, `state`, `index`, `name` (as applied), `diff`, `content`, `verdict` (`"pass"`, `"fail"`
  or `null`), `summary` (text or `null`), `says` and `observation`. `says` is `"worked"`, `"failed"` or `null`, and
  the world writes it on planted entries. `observation` is always `null`.
- **`state`** is `"S{j}"` for the base the next turn uses, or `"G"` after a pass. A run starts at `"S0"`. It's for
  R2's policy, and it moves only in trap 4.
- **Open patches:** all five at every call, in index order. The run's `i`-th turn uses `bases[min(i, len(bases) -
  1)]`. Patch `i` is offered as `names[i][min(c, len(names[i]) - 1)]`, where `c` counts the entries that applied it.
- **Recovered,** in every trap and form, means a run turn passed, which happens exactly when it applied `p`. The run
  stops there.

**The traps.**
- **A firing turn** is one that takes the trap's bait. It's counted per run, beside the same choice in the twin.
- **Exposed** runs are shown the record. That's every R1 and R2 run, since each trap is planted where the first run
  call reads it, and never R0. So in R1 and R2, a null can't come from never meeting the trap.
- **Named** (scored on exposed runs) means the turn raised the trap's flag at the rule's call, with a value naming
  the trap's object. **Raised** is that flag with any value, since a key or a state may not be shown to a turn.
- **A false name** is the trap's flag, with any value, at any call of a twin run.

1. **A failed idea back under a new name** (`n = 1`). The returner, `R = order[0]`, fails at turn 1.
   - **Trapped:** `names[R]` is its own name, then the first seven spares. So after each failure it's offered under
     a new description, with the same diff. **Twin:** it keeps its own name.
   - **Fires:** applying `R`. **Named:** `repeat` at the first run call (record length 1), with `R`'s key.
2. **A misleading summary** (`n = 1`). `M = order[0]` fails at turn 1.
   - **Trapped:** its summary is the lie, with `says` "worked". **Twin:** it's the failure, with `says` "failed".
   - **Fires:** applying `M`. **Named:** `contradiction` at the first run call, with turn 1.
3. **A long cycle** (`n = 3`). `C1, C2, C3 = order[0..2]` fail at turns 1 to 3, and `order[3]` is off the cycle.
   - `C1`'s summary points to `C2`, and `C2`'s to `C3`. It's all planted, since a run turn writes its own summary.
   - **Trapped:** `C3`'s summary points back to `C1`. So the record's last summary leads into a failed idea, and from
     there round the cycle. **Twin:** `C3`'s summary is the plain failure, so the chain ends.
   - **Fires:** applying `C1`, `C2` or `C3`. **Named:** `cycle` at the first run call (record length 3), with a cycle
     patch's key or `"S0"`.
4. **A state-varying key** (`n = 2`). `order[0]` and `order[1]` fail at turns 1 and 2, on `bases[0]`.
   - **Trapped:** `bases` is versions 0 to 7, so the base gains a revision line before every run turn. Behaviour
     never changes: `p` passes on every version, and the rest fail. But every diff's context, hunk header and key
     move, so a failed idea comes back under its own name with a new key. Turn 2's state is `"S1"`, and the run's
     `i`-th turn's is `"S{min(i + 1, 7)}"`. **Twin:** version 0 alone, and every state is `"S0"`.
   - **Fires:** applying an idea the record shows failed on an earlier base (in the twin, re-trying a failed idea).
     **Named:** `repeat` at the first run call (record length 2), with a planted idea's key, as recorded or as offered
     now.
5. **A change without an observation** (`n = 5`). The four failing patches fail at turns 1 to 4, in `order`. Turn 5
   applied `p` and timed out, so its `verdict`, `summary` and `says` are `null`.
   - **Twin:** the same entries without turn 5, so `p` is untried, not unchecked. Recovery means re-trying the patch
     that was never checked.
   - **Fires:** applying a failed patch while `p` has no verdict. **Named:** `premise` at the first run call, with
     turn 5.

**The ceiling, counted before the pilot, with no model.**
- **The record-only reader** applies the lowest-index open patch whose changed lines match no entry with verdict
  fail. The changed lines are a diff's `+` and `-` lines, without the `+++` and `---` headers.
- **The follower** takes the trap's bait whenever it can, and otherwise reads as the record-only reader does. A twin
  has no bait. In the trapped form, the bait is, by trap:
  1. `R`, under a name no entry shows;
  2. `M`;
  3. the patch named by the planted summary of the cycle patch applied last;
  4. the lowest-index failed idea, under its new key;
  5. the lowest-index failed patch, while `p` has no verdict.
- **Counted per world:** the follower's firing turns within 7, and whether the trap **costs**: the follower fails to
  recover within 7 in the trapped form, and recovers in the twin. Also counted is the **blind exposure**, the exact
  chance (found by enumerating every choice sequence) that uniform choices fire within 7.
- **A trap's ceiling** is the share of its worlds that cost. Each trap is built to cost in every world, so a world
  that doesn't is broken. Its builder fixes it before any turn runs, never after.

**The world half's own tests** use the two readers and an oracle, never the arms or the harness.
- **One pass:** on every base, only patch `p` passes, the base fails, and the generator agrees. Each base's keys are
  distinct, and so are all 40 of trap 4's. `patch -p1` on the base gives each patched file exactly.
- **Twins:** a trapped layout differs from its twin in exactly these fields:
  1. `names[R]`;
  2. turn 1's `summary` and `says`;
  3. turn 3's `summary`;
  4. `bases`, `patches` and turn 2's `state`;
  5. planted turn 5.
- **Rebuilt:** each world is identical when rebuilt from its seed.
- **Recovery:** in both forms of every world, the oracle applies `p` at the first run turn. The record-only reader
  recovers within 7, so each world can be recovered from the record alone.
- **Naming:** each rule fires on a hand-built run that raises its flag at the named call. It doesn't fire for the
  flag one call later, one call earlier (a record one shorter, which no run makes), or in the twin, where it's a
  false name. A wrong value fails "named" but passes "raised".
- **Exports:** `worlds()`, `open_patches(world, record)` and `firing(world, record)`. There are also `named`,
  `raised` and `false_named`, each `(world, record, flags_per_call) -> bool` as in stage A.

**The fingerprint** is the sha256 of `json.dumps(worlds, sort_keys=True, separators=(",", ":"))`, encoded as UTF-8.
- **It's posted** with the code's hash and the numpy version, since numpy doesn't promise its stream across versions.
- **`worlds`** is all 1,000, sorted by `(trap, w, form)`. In each world, `patches[j][i]` is patch `i` on `bases[j]`,
  and `names[i]` lists its names in the order offered:

```json
{"trap": 1, "w": 0, "form": "trapped" | "twin", "budget": 7, "passing": 3, "task": "...", "test": "...",
 "bases": ["..."], "names": [["..."]], "patches": [[{"diff": "...", "content": "<64 hex>"}]],
 "planted": [{"turn": 1, "state": "S0", "index": 0, "name": "...", "diff": "...", "content": "...",
   "verdict": "fail", "summary": "...", "says": "failed", "observation": null}]}
```
