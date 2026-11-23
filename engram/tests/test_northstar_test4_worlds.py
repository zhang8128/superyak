"""Tests for the Stage A / Test 4 world half (the four traps).

These are the world half's own tests, required by "The worlds": the oracle
recovers within budget in both twins of every world; each twin differs from
its trapped world only in the mechanic its trap names; a world rebuilds
identically from its seed; every naming rule fires at the right call and
not one call early, one call late, or in the twin; and a record-only
round-robin policy recovers within budget in both forms of every world.

The oracle and the round-robin policy here are test-only scaffolding
(written for these tests alone, never a real policy).
"""

from experiments.northstar import test4_worlds as tw


# ---------------------------------------------------------------------------
# Test-only driving helpers (not exported by test4_worlds.py)
# ---------------------------------------------------------------------------

def _take(world, state, record, content, turn):
    opts = world.options(state)
    idx = next(i for i, o in enumerate(opts) if o["content"] == content)
    next_state, entry = world.step(state, opts[idx])
    entry["turn"] = turn
    record.append(entry)
    return next_state


def _run_with_chooser(world, chooser):
    record = []
    state = "L0"
    for turn in range(1, world.budget + 1):
        opts = world.options(state)
        content = chooser(world, state, record, opts)
        idx = next(i for i, o in enumerate(opts) if o["content"] == content)
        next_state, entry = world.step(state, opts[idx])
        entry["turn"] = turn
        record.append(entry)
        state = next_state
        if world.recovered(state):
            return record, True
    return record, False


def _oracle_chooser(world, state, record, opts):
    """Knows the key, the lure, the returner and the break: always picks
    the idea that actually advances, including trap 4's switch to the new
    key once it has taken effect in the trapped world."""
    if world.trap == tw.TRAP_MAP and world.form == "trapped":
        level = tw._parse_level(state)
        if level is not None and level >= world._info["m"]:
            return world._info["new_key_content"]
    return world._info["key_content"]


def _round_robin_chooser(world, state, record, opts):
    """Round robin over this state's options, reading only the record."""
    count = 0
    prev = "L0"
    for e in record:
        if prev == state:
            count += 1
        prev = e["state"]
    return opts[count % len(opts)]["content"]


# ---------------------------------------------------------------------------
# 1. The oracle recovers within budget in both twins of every world.
# ---------------------------------------------------------------------------

def test_oracle_recovers_within_budget_every_world():
    failures = []
    for world in tw.worlds():
        _, recovered = _run_with_chooser(world, _oracle_chooser)
        if not recovered:
            failures.append((world.trap, world.D, world.k, world.w, world.form))
    assert not failures, (
        f"oracle failed to recover in {len(failures)} world(s), e.g. {failures[:10]}"
    )


# ---------------------------------------------------------------------------
# 2. Each twin differs from its trapped world only in the mechanic its
#    trap names.
# ---------------------------------------------------------------------------

def test_twin_cycle_only_differs_at_the_loop_exit():
    for D in (4, 8):
        for k in (3, 5):
            for w in range(25):
                trapped, twin = tw._build_pair(tw.TRAP_CYCLE, D, k, w)
                c = trapped._info["c"]
                Lc = trapped._info["Lc"]
                lure_c = trapped._info["lure_content"]
                td = tw._world_to_dict(trapped)
                wd = tw._world_to_dict(twin)
                assert td["budget"] == wd["budget"]
                assert set(td["states"]) == set(wd["states"])
                for state in td["states"]:
                    assert td["states"][state]["options"] == wd["states"][state]["options"]
                    t_step = td["states"][state]["step"]
                    w_step = wd["states"][state]["step"]
                    assert set(t_step) == set(w_step)
                    for content in t_step:
                        if state == "C3" and content == lure_c:
                            assert t_step[content][0] == Lc
                            assert w_step[content][0] == f"L{c + 1}"
                            assert t_step[content][1:] == w_step[content][1:]
                        else:
                            assert t_step[content] == w_step[content]


def test_twin_rename_only_differs_in_the_returners_name():
    for D in (4, 8):
        for k in (3, 5):
            for w in range(25):
                trapped, twin = tw._build_pair(tw.TRAP_RENAME, D, k, w)
                returner_c = trapped._info["returner_content"]
                td = tw._world_to_dict(trapped)
                wd = tw._world_to_dict(twin)
                assert td["budget"] == wd["budget"]
                assert set(td["states"]) == set(wd["states"])
                for state in td["states"]:
                    assert td["states"][state]["step"] == wd["states"][state]["step"]
                    t_opts = {c: n for n, c in td["states"][state]["options"]}
                    w_opts = {c: n for n, c in wd["states"][state]["options"]}
                    assert set(t_opts) == set(w_opts)
                    level = tw._parse_level(state)
                    for content in t_opts:
                        if content == returner_c and level is not None and level >= 1:
                            assert t_opts[content] != w_opts[content]
                        else:
                            assert t_opts[content] == w_opts[content]


def test_twin_summary_only_differs_in_says_for_misled_ideas():
    for D in (4, 8):
        for k in (3, 5):
            for w in range(25):
                trapped, twin = tw._build_pair(tw.TRAP_SUMMARY, D, k, w)
                misled = trapped._info["misled_contents"]
                td = tw._world_to_dict(trapped)
                wd = tw._world_to_dict(twin)
                assert td["budget"] == wd["budget"]
                assert set(td["states"]) == set(wd["states"])
                for state in td["states"]:
                    assert td["states"][state]["options"] == wd["states"][state]["options"]
                    t_step = td["states"][state]["step"]
                    w_step = wd["states"][state]["step"]
                    for content in t_step:
                        tn, tv, ts, ti = t_step[content]
                        wn, wv, ws, wi = w_step[content]
                        assert (tn, tv, ti) == (wn, wv, wi)
                        if content in misled:
                            assert tv == "fail" and ts == "worked" and ws == "failed"
                        else:
                            assert ts == ws


def test_twin_map_only_differs_in_the_key_switch():
    for D in (4, 8):
        for k in (3, 5):
            for w in range(25):
                trapped, twin = tw._build_pair(tw.TRAP_MAP, D, k, w)
                m = trapped._info["m"]
                key_c = trapped._info["key_content"]
                new_key_c = trapped._info["new_key_content"]
                td = tw._world_to_dict(trapped)
                wd = tw._world_to_dict(twin)
                assert td["budget"] == wd["budget"]
                assert set(td["states"]) == set(wd["states"])
                for state in td["states"]:
                    assert td["states"][state]["options"] == wd["states"][state]["options"]
                    level = tw._parse_level(state)
                    t_step = td["states"][state]["step"]
                    w_step = wd["states"][state]["step"]
                    for content in t_step:
                        t_entry = t_step[content]
                        w_entry = w_step[content]
                        if level is not None and level == m - 1 and content == key_c:
                            # the transition into Lm: same outcome, only the
                            # observation differs.
                            assert t_entry[0] == w_entry[0]
                            assert t_entry[1] == w_entry[1] == "pass"
                            assert t_entry[2] == w_entry[2] == "worked"
                            assert t_entry[3] == [key_c]
                            assert w_entry[3] is None
                        elif level is not None and level >= m and content == key_c:
                            assert t_entry[1] == "fail" and t_entry[0] == state
                            assert w_entry[1] == "pass"
                        elif level is not None and level >= m and content == new_key_c:
                            assert t_entry[1] == "pass"
                            assert w_entry[1] == "fail" and w_entry[0] == state
                        else:
                            assert t_entry == w_entry


# ---------------------------------------------------------------------------
# 3. A world is identical when rebuilt from its seed.
# ---------------------------------------------------------------------------

def test_world_rebuilds_identically_from_its_seed():
    for trap in (tw.TRAP_CYCLE, tw.TRAP_RENAME, tw.TRAP_SUMMARY, tw.TRAP_MAP):
        for D in (4, 8):
            for k in (3, 5):
                for w in range(25):
                    t1, u1 = tw._build_pair(trap, D, k, w)
                    t2, u2 = tw._build_pair(trap, D, k, w)
                    assert tw._world_to_dict(t1) == tw._world_to_dict(t2)
                    assert tw._world_to_dict(u1) == tw._world_to_dict(u2)


def test_fingerprint_is_deterministic():
    assert tw.fingerprint() == tw.fingerprint()


# The sha256 the implementation report posted for the 800-world fingerprint
# (numpy 2.4.3). A runner that must recompute rather than trust re-derives
# this independently via tw.fingerprint(); this test pins it here too, so a
# change to the generation logic or to numpy's stream shows up as a failure
# in this suite, not only as a mismatch against the report.
REPORTED_FINGERPRINT = "ceb09639edbe0c0a2c9c5b3c3c8baa91f40eed31d713f1c74201eaddd8fa065e"


def test_fingerprint_matches_the_reported_value():
    assert tw.fingerprint() == REPORTED_FINGERPRINT


# ---------------------------------------------------------------------------
# 4. Every naming rule fires on a hand-built run that raises the right flag
#    at the right call, and doesn't fire one call later, one call earlier,
#    or in the twin.
# ---------------------------------------------------------------------------

def test_cycle_naming_rule():
    trapped, twin = tw._build_pair(tw.TRAP_CYCLE, 4, 3, 0)
    c = trapped._info["c"]
    Lc = trapped._info["Lc"]
    key_c = trapped._info["key_content"]
    lure_c = trapped._info["lure_content"]

    record = []
    state = "L0"
    turn = 1
    for _ in range(c):
        state = _take(trapped, state, record, key_c, turn)
        turn += 1
    assert state == Lc
    for _ in range(4):  # lure: Lc -> C1 -> C2 -> C3 -> Lc (second arrival)
        state = _take(trapped, state, record, lure_c, turn)
        turn += 1
    assert state == Lc
    j = turn - 2  # 0-indexed record position of that second arrival
    while state != "G":
        state = _take(trapped, state, record, key_c, turn)
        turn += 1
    N = len(record)

    # Per the contract: an arrival at record index j is turn j+1, and "the
    # call on an arrival" is the one whose record ends with it -- a record
    # of length j+1, i.e. flags_per_call[j+1]. That's the first call that
    # has actually seen the arrival (the call that chose the arriving step,
    # flags_per_call[j], was made before the arrival existed and can't see
    # it).
    right = [[] for _ in range(N)]
    assert j + 1 < N
    right[j + 1] = [{"cycle": Lc}]
    assert tw.named(trapped, record, right) is True

    # The same flag one call early (at the call that chose the arriving
    # step, before it existed) must not name it.
    too_early = [[] for _ in range(N)]
    too_early[j] = [{"cycle": Lc}]
    assert tw.named(trapped, record, too_early) is False

    # ... nor one call late.
    too_late = [[] for _ in range(N)]
    assert j + 2 < N
    too_late[j + 2] = [{"cycle": Lc}]
    assert tw.named(trapped, record, too_late) is False

    # The twin's loop leads forward, not back, so there's no second
    # arrival at Lc to name.
    twin_record = []
    state = "L0"
    turn = 1
    for _ in range(c):
        state = _take(twin, state, twin_record, key_c, turn)
        turn += 1
    for _ in range(4):
        state = _take(twin, state, twin_record, lure_c, turn)
        turn += 1
    while state != "G":
        state = _take(twin, state, twin_record, key_c, turn)
        turn += 1
    twin_flags = [[] for _ in range(len(twin_record))]
    assert tw.named(twin, twin_record, twin_flags) is None


def test_rename_naming_rule():
    trapped, twin = tw._build_pair(tw.TRAP_RENAME, 4, 3, 0)
    returner_c = trapped._info["returner_content"]
    key_c = trapped._info["key_content"]

    record = []
    state = "L0"
    turn = 1
    state = _take(trapped, state, record, returner_c, turn)  # turn 1: fails at L0
    turn += 1
    state = _take(trapped, state, record, key_c, turn)  # turn 2: L0 -> L1
    turn += 1
    offered_again_idx = turn - 1  # 0-indexed record position of the retry
    state = _take(trapped, state, record, returner_c, turn)  # turn 3: offered under a new name at L1, fails again
    turn += 1
    while state != "G":
        state = _take(trapped, state, record, key_c, turn)
        turn += 1
    N = len(record)

    right = [[] for _ in range(N)]
    right[offered_again_idx] = [{"repeat": returner_c}]
    assert tw.named(trapped, record, right) is True

    late = [[] for _ in range(N)]
    assert offered_again_idx + 1 < N
    late[offered_again_idx + 1] = [{"repeat": returner_c}]
    assert tw.named(trapped, record, late) is False

    early = [[] for _ in range(N)]
    assert offered_again_idx - 1 >= 0
    early[offered_again_idx - 1] = [{"repeat": returner_c}]
    assert tw.named(trapped, record, early) is False

    # The twin never renames it, so it's never "offered under a different
    # name" and the run isn't exposed.
    twin_record = []
    state = "L0"
    turn = 1
    state = _take(twin, state, twin_record, returner_c, turn)
    turn += 1
    state = _take(twin, state, twin_record, key_c, turn)
    turn += 1
    state = _take(twin, state, twin_record, returner_c, turn)
    turn += 1
    while state != "G":
        state = _take(twin, state, twin_record, key_c, turn)
        turn += 1
    twin_flags = [[] for _ in range(len(twin_record))]
    assert tw.named(twin, twin_record, twin_flags) is None


def _find_summary_exposure(k=3, D=4):
    # d stops short of the last level, so there's always room for a "late"
    # check (two more calls after the mismatched turn).
    for w in range(25):
        trapped, _ = tw._build_pair(tw.TRAP_SUMMARY, D, k, w)
        misled = trapped._info["misled_contents"]
        for d in range(D - 1):
            opts = trapped.options(f"L{d}")
            hit = next((o for o in opts if o["content"] in misled), None)
            if hit is not None:
                return w, d, hit["content"]
    raise AssertionError("no (D, k, w) in range found a misled idea offered at a level")


def test_summary_naming_rule():
    w, exposure_d, bad_content = _find_summary_exposure()
    trapped, twin = tw._build_pair(tw.TRAP_SUMMARY, 4, 3, w)
    key_c = trapped._info["key_content"]

    record = []
    state = "L0"
    turn = 1
    mismatch_idx = None
    while state != "G":
        if tw._parse_level(state) == exposure_d and mismatch_idx is None:
            state = _take(trapped, state, record, bad_content, turn)
            mismatch_idx = turn - 1
        else:
            state = _take(trapped, state, record, key_c, turn)
        turn += 1
    assert mismatch_idx is not None
    mismatched_turn = mismatch_idx + 1
    N = len(record)

    right = [[] for _ in range(N)]
    assert mismatch_idx + 1 < N
    right[mismatch_idx + 1] = [{"contradiction": mismatched_turn}]
    assert tw.named(trapped, record, right) is True

    late = [[] for _ in range(N)]
    assert mismatch_idx + 2 < N
    late[mismatch_idx + 2] = [{"contradiction": mismatched_turn}]
    assert tw.named(trapped, record, late) is False

    early = [[] for _ in range(N)]
    early[mismatch_idx] = [{"contradiction": mismatched_turn}]
    assert tw.named(trapped, record, early) is False

    # The twin's summaries always agree with their verdicts, so there's no
    # mismatch to name.
    twin_record = []
    state = "L0"
    turn = 1
    seen_bad = False
    while state != "G":
        if tw._parse_level(state) == exposure_d and not seen_bad:
            state = _take(twin, state, twin_record, bad_content, turn)
            seen_bad = True
        else:
            state = _take(twin, state, twin_record, key_c, turn)
        turn += 1
    twin_flags = [[] for _ in range(len(twin_record))]
    assert tw.named(twin, twin_record, twin_flags) is None


def test_map_naming_rule():
    trapped, twin = tw._build_pair(tw.TRAP_MAP, 4, 3, 0)
    m = trapped._info["m"]
    Lm = trapped._info["Lm"]
    key_c = trapped._info["key_content"]
    new_key_c = trapped._info["new_key_content"]

    record = []
    state = "L0"
    turn = 1
    for _ in range(m):  # L0 -> ... -> Lm, the last of these arrives at Lm
        state = _take(trapped, state, record, key_c, turn)
        turn += 1
    assert state == Lm
    arrival_idx = turn - 2  # 0-indexed record position of the arrival
    arrival_turn = arrival_idx + 1
    while state != "G":  # from Lm on, the new key is the one that advances
        state = _take(trapped, state, record, new_key_c, turn)
        turn += 1
    N = len(record)

    right = [[] for _ in range(N)]
    assert arrival_idx + 1 < N
    right[arrival_idx + 1] = [{"premise": arrival_turn}]
    assert tw.named(trapped, record, right) is True

    late = [[] for _ in range(N)]
    assert arrival_idx + 2 < N
    late[arrival_idx + 2] = [{"premise": arrival_turn}]
    assert tw.named(trapped, record, late) is False

    early = [[] for _ in range(N)]
    early[arrival_idx] = [{"premise": arrival_turn}]
    assert tw.named(trapped, record, early) is False

    # The twin never invalidates the old key, so arriving at Lm carries no
    # observation; raising nothing there is correct, and named() says False
    # rather than True (Lm is an ordinary level in the twin, not an
    # unexposed one, so this is "False", not "None").
    twin_record = []
    state = "L0"
    turn = 1
    for _ in range(m):
        state = _take(twin, state, twin_record, key_c, turn)
        turn += 1
    assert state == Lm
    while state != "G":
        state = _take(twin, state, twin_record, key_c, turn)
        turn += 1
    twin_flags = [[] for _ in range(len(twin_record))]
    assert tw.named(twin, twin_record, twin_flags) is False


def test_false_named_detects_the_traps_flag_with_any_value():
    for trap, flag_key in tw.TRAP_FLAGS.items():
        _, twin = tw._build_pair(trap, 4, 3, 0)
        assert tw.false_named(twin, [], [[{flag_key: "whatever-value"}]]) is True
        assert tw.false_named(twin, [], [[]]) is False
        assert tw.false_named(twin, [], [[{"unrelated": 1}]]) is False


# ---------------------------------------------------------------------------
# 5. A record-only round-robin policy recovers within budget in both forms
#    of every world.
# ---------------------------------------------------------------------------

def test_round_robin_recovers_within_budget_every_world():
    failures = []
    for world in tw.worlds():
        _, recovered = _run_with_chooser(world, _round_robin_chooser)
        if not recovered:
            failures.append((world.trap, world.D, world.k, world.w, world.form))
    assert not failures, (
        f"round-robin failed to recover in {len(failures)} world(s), e.g. {failures[:10]}"
    )
