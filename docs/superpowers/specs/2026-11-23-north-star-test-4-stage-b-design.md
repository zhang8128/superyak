# Test 4, stage B: do real turns fall into the traps, and does the record get them out? (a proposal)

Draft 5, 2026-11-23. Tardis, with Serenity (goals.md T3; docs/north-star.md row 4). **Approved by a fresh reviewer
under section 3 (review 3, at a347b23c, with its two fault-rule changes made as written).** Under station law section 3, a
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
- **Draft 3 (b3e92d5f)** went to a fresh reviewer: approved with six required changes, W1 to W6 (review 1, beside this
  spec, d6bd56c0). It found no fitting and no leaks either way, and rebuilt all 1,000 worlds from the text.
  **Draft 4 makes all six.**
  - The question, the arms, the harness, the measures and the size are rewritten from W1 to W5.
  - **Two edits touch "The worlds",** the blind builder's section. Both are mechanical clarifications the reviewer
    prescribed, never rule changes: stage A's 64 words are copied in, and "the run's i-th turn" counts run turns from 1.
    So are three more: trap 5's twin has `n = 4`, a planted failing summary defaults to the plain failure, and the
    exports' return shapes are stated.
  - **One edit touches the hashed arms (W1(e)):** a null summary's rendering, and with it the advice's wording, as the
    reviewer advised. The arms are re-hashed at `tardis/test4b-arms` cbfe2fda (local): `test4b_arms.py`
    `c1cc0bc32d79366d…` and its test `b6927da75d736fd5…`. The diff from 587ce392 is 2 files, +10 −2, and it's
    flagged for the re-check.
- **Draft 4 (962a89b0)** went back to the same reviewer: approved with six required changes, X1 to X6 (review 2),
  all small text fixes. It ruled the worlds edits mechanical and the arms change not fitting. Draft 5 makes the six
  and takes its advisories. One more mechanical edit touches "The worlds": `open_patches` takes the run turn `i`.

Stage A (test 4's spec, approved; result 4af2eb13) chose B's traps by its own rules: **the renamed idea**, by its CI
rule, and **the misleading summary**, by its reads clause. Long cycles, keys that vary by state, and a change without
an observation are designed fresh here, never from A's numbers (9b, 9c and 9e in that spec's "can't show").

## The question

When each turn is a fresh agent that forgets everything but the record, does it fall into one of five traps planted
in that record?
- a renamed failed idea;
- a misleading summary;
- a long cycle;
- a state-varying key;
- a change without an observation.

And does the record, or the record with structure, get it out within one turn budget? Each trap is answered on its
own, never pooled (W4).

## Why the turn chooses

In the approved sketch, a policy chooses and the turn only does the work. Then only the summary trap reaches a real
agent, and B would repeat A at a higher cost. Here **the turn chooses:** it reads what its arm gives it, picks one
patch, and writes a summary. The harness applies the patch and runs the frozen test, since a turn has no tools. The
arms differ only in what the turn is given.

## The worlds: small code tasks whose approaches are patches

- **A world** is a small code task: a function, a frozen test, and `k` candidate patches. Each patch has a written
  description, which is its name, and a diff. **Its content is frozen as the sha256 of the patched target file,
  normalized:** CRLF becomes LF, trailing whitespace is stripped from each line, trailing blank lines are dropped, and
  the lines are joined by LF with one final LF.
  - So whitespace and hunk order can't split one idea into two keys. "The same idea" is exact against a given base,
    and B needs no rule for when two written descriptions are one idea.
  - When the base file moves (the state-varying trap), the same idea gets a new key, as that trap intends.
- **Exactly one patch passes the frozen test.** The world half's own test checks that before any turn runs. The smoke
  run for this draft found why it's needed: a toy median task's test let the mean pass too.
- **The harness's work, not the turn's:** apply the chosen patch to a fresh copy, run the frozen test, and record
  `verdict` from the test's exit code. The turn's own `summary` goes beside it.
- **Recovered** means a run turn's chosen patch passed.
- **The traps,** each with an untrapped twin as in stage A:
  - **renamed idea:** a patch that failed returns with a new description and the same diff;
  - **misleading summary:** the record's summary of a failed patch says "worked";
  - **long cycle (new):** failing patches whose planted summaries lead into one another and back;
  - **state-varying key (new):** the base file moves, so the same failed idea comes back with a new key;
  - **change without an observation (new):** the passing patch's record entry has no verdict, because its turn timed
    out. So recovering means re-trying an approach that was never checked.
- **Who builds them:** the rules are in "The worlds" below, written blind to the arms. A separate fresh agent
  implements them from that section and the spec, blind to the arms too, as in stage A.

## The arms, under one budget

Each turn is one `claude -p` call, Sonnet 5.5, in the harness's frozen invocation below. **A turn has no tools:** it
reads its prompt and replies. It can't apply or test a patch itself, so it can't sidestep a trap by running all five.

**The arms' signatures (X5),** from the hashed module:
- `prompt(arm, task, patches, record, keys=None, seed=0) -> str`, where `patches` is a list of
  `{"description", "diff"}` and each record entry is `{"turn", "description", "diff", "verdict", "summary"}`;
- `read_reply(text, k) -> (choice, summary, flags)`, which raises `Malformed` for anything else.

| Arm | What a turn is given, beside the task and the open patches |
| --- | --- |
| **R0** | Nothing: the forgetting baseline |
| **R1** | The record as it is: each earlier turn's patch description, its diff, its verdict and its summary. It holds no content key, so noticing a repeat is the turn's own work |
| **R2** | R1, plus advice from stage A's adaptive-by-content policy, computed from the content keys. **The advice shows the policy's choice and its `repeat` flags only (W2).** `contradiction` can't fire there, because the advice rebuilds `says` from `verdict`; `cycle` and `premise` aren't shown; and entries with a null verdict are left out of its counts |

- **A turn's output** is one JSON object: `{"choice": <index>, "summary": <text>, "flags": [...]}`, with the flags
  from stage A's contract. Malformed output is a stall, and that turn is spent.
- **The budget:** with `k = 5` (one passing patch and four failing), 7 run turns per world, counted in model calls,
  stalls included. Tokens and wall time are recorded beside them, never scored.

## The harness (W1)

**Who writes it:** a third fresh agent, given "The arms", "The harness", "Measures" and "The worlds", whole (X5). "The
worlds" chooses nothing, so giving it whole is no fitting risk. It needs the verdict command, applying a diff with
`patch -p1`, the state rule and the world's JSON shape, all of which are there. The agent never reads either half's
code beyond the exports and signatures written here. Its code is hashed before any turn runs. The arms are pushed, or
bundled, once the worlds half is hashed, so it can import them.

- **(a) The turn's frozen invocation:** the visitor walk's wrapper, as `tardis/visitor-walk-spec` 344e425a freezes it:
  systemd scope, bubblewrap with Tardis's home hidden, `--unshare-pid`, and `env -i`.
  - It runs `claude -p` with `--tools ""`, `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`, `--model
    claude-sonnet-5-5` and `--output-format stream-json --verbose`. It doesn't pass `--allowedTools` or a permission
    mode, since a turn has no tools to permit.
  - **The per-turn timeout** is 120 seconds. The reply is the `result` text of stream-json's result event.
  - **On every turn,** the init event must list no tools and no MCP servers. If it lists any, the run is a machine
    fault and void.
- **(b) Nothing outside the prompt names the trap, form, arm or world.** Each turn runs in one empty working directory,
  `/var/tmp/t4b-turn/`, made fresh for every turn. The wrapper's `home/` and `uv-cache/` sit outside it, in
  `/var/tmp/t4b-home/`, so the working directory stays empty. Its name is the same for every turn, and the environment is the
  wrapper's. Claude Code's system prompt shows the working directory, so a name that carried the world would leak it.
- **(c) A stall,** meaning a malformed reply or a timeout at 120 seconds, is spent.
  - It writes no record entry and raises no flags.
  - The harness counts run turns itself: `i` is the run turn's number from 1, stalls included. So trap 4's base still
    moves before every run turn, stalled or not.
  - **The world is told `i` (X1):** `open_patches(world, record, i)`, so the base offered after a stall is right.
  - **A run entry's `turn` is `n + i`,** so a stall leaves a gap in the record's numbering. `firing` returns the run
    turns `i` whose patch took the bait.
  - A naming rule's "first run call" is the first run call whose reply was read.
- **(c2) A machine fault isn't a stall (X4, review 3).** These count as faults:
  - a result event with `is_error` true, such as a sign-in error or an API error;
  - a call killed at 120 seconds after any `system`/`api_retry` event in its stream. Claude Code retries a rate-limited
    call itself, so that is how a rate limit shows;
  - an exit with no result, when the call exits on its own before the kill;
  - an init event listing tools or MCP servers.

  A faulted call is retried once, after a 60-second pause. If it faults again, the run is void. **A void run is rerun
  from its start,** with the same world, form, arm, repeat and seed, so faults can't drop the slower, non-recovering
  runs more than others. Stalls, faults and reruns are reported per arm.
- **(d) Run entries:**
  - `summary` is the turn's own text, written before its verdict exists;
  - `says` is null on run entries, since nothing reads it there;
  - `state` follows "The worlds" state rule;
  - `name` is the description as offered, and `diff` and `content` are the applied patch's on that turn's base.
- **(e) Field mapping:** the world's `name` becomes the arms' `description`. A null `summary` renders as "none (its
  turn ended before it wrote one)". That's one reviewer-required change to the hashed arms, made and re-hashed, beside
  this draft.
- **(f) R2's inputs:** `keys` holds one key per record entry, the null-verdict entry included, then one per open patch.
  The advice seed is the repeat's index, 0, 1 or 2.
- **(g) Its sign-in:** the turns use a sign-in of their own, made once by Andy, never Tardis's. It's in its own config
  directory, reset to the sign-in's files before every turn, as the visitor walk's is.

## What each arm sees of each trap (W2)

These were checked by the reviewer on a rebuild of all 1,000 worlds, rendered through the hashed arms.
- **R0's prompt is byte-identical** between the trapped and twin forms in traps 2, 3 and 5, in 100 of 100 worlds each.
  It has no record, so R0's trap effect is exactly zero in expectation there (X6). In traps 1 and 4, R0's prompt does
  change, by a name word or the revision lines, and that change is what R0 controls for there.
- **R2's advice text is identical between forms** in traps 2, 3 and 5, over 100 of 100 worlds and seeds 0 to 19. So in
  those traps, R2 can differ from R1 only in how a turn reads the same advice.
- **In trap 4, R1 sees the failed idea under its own planted name,** with identical changed lines. Only the hunk header
  and the revision lines move. So trap 4 barely reaches R1. It's aimed at R2's key: at w = 0, the advice names a failed
  patch in 34% of seeds, against 17.5% in the twin.

## Measures, fixed before any turn (W4, W5)

- **The trap effect,** per arm and world: the recovery rate in the trapped form minus its twin's, over the world's
  three repeats.
- **"Does it fall in" (primary, per trap):** R1's trap effect minus R0's, and R2's minus R0's. **The expected sign is
  negative:** a trap the record carries lowers recovery for a reader of the record. R0's effect is near zero, so it
  adds mostly noise.
- **"Does the record get it out" (primary, per trap):** recovery in the trapped form, R1 minus R0 and R2 minus R0.
  **The expected sign is positive** where the record helps despite the trap.
- **"Does structure help" (primary, per trap, X2):** R2 minus R1, on both of the above. There's no expected sign: the
  advice may help, and its bandit's exploration may cost (see "can't show").
- **Both are reported per trap, never pooled.** Each is the mean over worlds, with a 95% percentile bootstrap CI over
  worlds: 10,000 resamples, a fresh `numpy.random.default_rng(20261130)` per trap, and `numpy.quantile`'s default
  method, as stage A has it.
- **Named:** the turn's flag at the rule's call, by "The worlds" rules. It's reported beside the primaries, never
  inside them, with false names in the twins.
  - **`repeat`'s value is read as an open patch's number (W3),** an integer from 0 to 4 or a string holding one. The
    harness turns it into that patch's key at that call before calling `named`. **Trap 3 is scored with `raised`,**
    since a `cycle` note can't name a key.
  - **Disclosed:** the prompt defines `repeat` as "under another description", which trap 4 never shows. It defines
    `premise` as "changed what earlier verdicts mean", which trap 5's unchecked entry doesn't do.
- **Activity, reported, never scored:** distinct patch indices tried, in runs that don't recover. In trap 4 every diff
  is distinct by construction, so diffs wouldn't count activity.

## The size, from a pilot, every number fixed before it (W5)

- **Before the pilot:** each trap's ceiling is counted without running anything, by "The worlds" rule. Blind exposure
  is reported beside it as the informative number, since the ceiling is 1.0 in every world by construction.
- **The pilot:** `w` 0 to 2 per trap, in both forms, in all three arms, with **3 repeats** and R2's advice seeds 0 to 2.
  That's 5 × 3 × 2 × 3 × 3 = 270 runs, at most 270 × 7 = 1,890 turns.
- **The worlds the main run needs, from a frozen formula:** per trap, `N = ceil((2 × 1.96 × σ / 0.30) ** 2)` worlds.
  - That gives a CI on the primary about ±0.15 wide.
  - **σ (X3)** is the largest, over that trap's six primary differences, of the pilot's per-world standard deviation,
    with `ddof = 1` and a floor of 0.30, since 3 pilot worlds give two degrees of freedom per trap.
  - With the floor, N is at least 16. Binomial noise alone can put σ at 0.35 to 0.55, so N will often exceed 20, and
    **"underpowered" is the likely label,** said now: 20 worlds then reach about ±0.15 to ±0.24.
- **The ceiling, in turns:** the main run takes at most 20 worlds per trap. That's 20 × 5 × 2 × 3 × 3 × 7 = 12,600
  turns, and Andy can veto it as a budget.
  - **If N passes 20,** B runs 20 worlds per trap, reports the CI it reached, and labels any trap whose CI is wider
    than ±0.15 underpowered (X6).
  - **If the pilot's measured cost per turn** makes 12,600 turns more than Andy's budget, B stops, as v2's stage 2
    pilot did.
- **An estimate of the pilot's cost:** a turn reads about 1,500 to 3,000 tokens and writes about 100. So the pilot is
  about 3 to 6 million tokens, and 5 to 11 hours of wall time at 10 to 20 seconds a turn. That's an estimate, not
  measured, and it leaves out Claude Code's own system prompt. The pilot measures it.

## What this can't show, said before the run

- **Patch worlds are authored.** A real research or coding task rarely has `k` named candidates and one frozen test.
- **R2's advice comes from stage A's policy,** so R2 tests that policy's advice to a real agent, not structure in
  general.
  - **R2's bandit explores, which costs on its own.** In trap 5, in both forms, the advice names a failed patch in 125
    of 200 seeds, so R2 − R1 may come out negative from exploration alone.
- **The turn is Sonnet 5.5,** and other models may fall into the traps differently.
- **Trap 5 is expected to show nothing.** The arms show a null verdict plainly, and the opening says exactly one patch
  passes. So with four fails on record, the passing patch is the only one not shown failing, in both forms.
- **Trap 2 is in its weakest form:** "fail" sits on the same line as "It worked."
- **The advice's true self-description may weaken trap 4 for R2.** It now says it keys patches by the file each one
  produces, a wording made after trap 4 was known. So an R2 turn may discount the advice when the base moves.
- **Trap 3's cycle is three patches,** and with `k = 5` it can be four at most. So "long" here means three, which
  stage A called a detour.

## Decided in draft 2, from Serenity's answer

1. **The turn chooses.** R2 tests the policy, as advice.
2. **Patch worlds for B.** v2's room items can be a later stage.
3. **The three new traps** are Serenity's, written into "The worlds":
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
2. `words = rng.choice(64, size=5, replace=False)`: patch `i` gets word `words[i]` of this list of 64 words, stage A's,
   in order: amber, basin, cedar, delta, ember, fjord, garnet, harbor, iris, jasper, kestrel, lantern, meadow, nectar, onyx, pepper, quarry, raven, saffron, timber, umber, velvet, willow, xenon, yarrow, zephyr, acorn, birch, cobalt, dune, elm, flint, grove, heron, indigo, juniper, kelp, lichen, maple, nickel, oak, pine, quartz, reed, slate, thistle, upland, vale, walnut, yew, zinc, alder, bramble, clover, dahlia, egret, fern, gorse, hazel, ivy, jade, kiln, lupin, moss. The other 59, in list order, are spares;
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
  lie is `Applied the {word} patch. It worked.` A planted failing entry's summary is the plain failure unless its
  trap says otherwise.
- **An entry** holds `turn`, `state`, `index`, `name` (as applied), `diff`, `content`, `verdict` (`"pass"`, `"fail"`
  or `null`), `summary` (text or `null`), `says` and `observation`. `says` is `"worked"`, `"failed"` or `null`, and
  the world writes it on planted entries. `observation` is always `null`.
- **`state`** is `"S{j}"` for the base the next turn uses, or `"G"` after a pass. A run starts at `"S0"`. It's for
  R2's policy, and it moves only in trap 4.
- **Open patches:** all five at every call, in index order. The run's `i`-th turn (`i` counts run turns from 1) uses `bases[min(i, len(bases) -
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
   - **Twin:** the same entries without turn 5, so its `n` is 4 and `p` is untried, not unchecked. Recovery means re-trying the patch
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
- **Exports:**
  - `worlds()`;
  - `open_patches(world, record, i)`, which returns the five open patches for run turn `i` in index order, each
    `{"name", "diff", "content"}`;
  - `firing(world, record)`, which returns the run turns `i` whose applied patch took the trap's bait;
  - `named(world, record, flags_per_call)`, which returns True, False or None, as in stage A's contract;
  - `raised` and `false_named`, which return a bool.

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
