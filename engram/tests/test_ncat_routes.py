"""The route store (docs/superpowers/specs/2026-11-16-v2-walks-into-routes.md, revision 3), row by row of its section 10:
what a right store does, and what a wrong one would do that each test catches."""
import decimal
import hashlib
import itertools
import json
import random
import sqlite3
from fractions import Fraction
from pathlib import Path

import pytest

import ncat_routes as R
from ncat import NCat, NCatError

FIXTURE = Path(__file__).resolve().parents[2] / "docs/superpowers/specs/2026-11-16-v2-walks-into-routes-fixture"
REPO, BASE = "1" * 40, "2" * 40
MARKER = "zq-planted-marker"


def blob(path):
    return hashlib.sha1(path.encode()).hexdigest()


def walk(attempt, steps, standing="passed_verified", source="room", item=None, family="claude", base=BASE):
    """`steps`: each a list of paths named in one step (a bare path is a one-file step)."""
    steps = [[s] if isinstance(s, str) else s for s in steps]
    return {"v": 1, "source": source, "repo": REPO, "base": base, "item": item or f"item-{attempt}", "attempt": attempt,
            "family": family, "verdict": None if standing == "unjudged" else ("passed" if "passed" in standing else "failed"),
            "standing": "unjudged" if source == "ship" else standing,
            "steps": [{"seq": i + 1, "tool": "read", "ok": True, "named": [[p, blob(p)] for p in names], "seen_ms": None,
                       "result_ms": None, "tokens_in": None, "tokens_out": None} for i, names in enumerate(steps)],
            "changed": []}


def line(w):
    return R.canonical(w)


def experiment(tmp_path, walks, budget=R.BUDGET_BYTES, name="routes.db"):
    """Write each walk to its own file and a list of them all, build, and return (store path, list id, files)."""
    d = tmp_path / f"in-{len(list(tmp_path.iterdir()))}"
    d.mkdir()
    files = []
    for w in walks:
        f = d / f"walk-{w['attempt']}.jsonl"
        f.write_bytes(line(w))
        files.append(f)
    lst = listing(walks, files)
    (d / "list.json").write_bytes(lst)
    out = tmp_path / name
    R.build(out, files, d / "list.json", budget_bytes=budget)
    return out, hashlib.sha256(lst).hexdigest(), files


def listing(walks, files, measure=("share", 1)):
    turns = sorted(({"attempt": w["attempt"], "item": w["item"], "base": w["base"], "standing": w["standing"],
                     "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for w, f in zip(walks, files)),
                   key=lambda e: e["attempt"])
    return json.dumps({"v": 1, "repo": REPO, "measure": {"name": measure[0], "version": measure[1]}, "turns": turns},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def ask(store, goals, list_id, measure=("share", 1)):
    q = {"v": 1, "repo": REPO, "list": list_id, "measure": {"name": measure[0], "version": measure[1]}, "goals": goals}
    with R.open_store(store) as s:
        return json.loads(s.ask(R.canonical(q)))


def route_of(answer, i=0):
    return answer["answers"][i]["route"]


# ------------------------------------------------------------------ the fixture, normative


def fixture_answer():
    """The fixture's answer, with `kernel` the digest of the kernel source in use: byte for byte otherwise (spec, section 8)."""
    expected = json.loads((FIXTURE / "answer.json").read_bytes())
    expected["kernel"] = R._kernel_digest()
    return R.canonical(expected)


def test_the_fixture_is_answered_byte_for_byte(tmp_path):
    out = tmp_path / "routes.db"
    walks = sorted(FIXTURE.glob("walk-*.jsonl"))
    R.build(out, walks, FIXTURE / "list.json")
    with R.open_store(out) as s:
        assert s.ask((FIXTURE / "question.json").read_bytes()) == fixture_answer()
        assert s.check() > 0
    R.build(out, list(reversed(walks)), FIXTURE / "list.json")   # files given in another order: the same bytes
    with R.open_store(out) as s:
        assert s.ask((FIXTURE / "question.json").read_bytes()) == fixture_answer()
    assert json.loads((FIXTURE / "answer.json").read_bytes())["kernel"] == "511bacd017146586"   # the kernel at v2 487f44bb


def test_every_answer_names_the_store_and_the_kernel_in_the_rooms_version_words(tmp_path):
    import re
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a"])])
    answer = ask(out, ["a", "nowhere"], list_id)
    assert answer["store"] == R.STORE_VERSION == "3" and answer["kernel"] == R._kernel_digest()
    for value in (answer["store"], answer["kernel"]):
        assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value)


# ------------------------------------------------------------------ the path rule


@pytest.mark.parametrize("path", ["a" * 512, "a/b-c_d.e", "x", "a.b/c"])
def test_the_path_rule_accepts(path):
    assert R.plain_path(path)


@pytest.mark.parametrize("path", ["a" * 513, "two words", 'quote".txt', "é.txt", "/a", "a//b", "./a", "a/..", "", "a/.",
                                  "tab\tx", "back\\slash", "a/", None, 7])
def test_the_path_rule_refuses(path):
    assert not R.plain_path(path)


# ------------------------------------------------------------------ a walk file, read as written


def test_a_walk_file_is_read_as_written():
    w = walk("t1", [["a", "b", "c"], [], "d"], standing="failed")
    w["steps"][1]["named"] = []
    w["steps"][0]["tokens_in"], w["steps"][0]["seen_ms"] = 12, 340
    w["changed"] = [["d", "changed"], ["new", "added"], ["old", "removed"]]
    (back,) = R.read_walks(line(w), "f")
    assert back == w
    assert [v[0] for v in R.visits(back)] == ["a", "b", "c", "d"]


REFUSALS = [
    ("a field missing", lambda w: w.pop("family")),
    ("an unknown key", lambda w: w.update({MARKER: 1})),
    ("a wrong type", lambda w: w.update({"steps": MARKER})),
    ("a seq that goes back", lambda w: w["steps"][1].update({"seq": 1})),
    ("a path with ..", lambda w: w["steps"][0]["named"][0].__setitem__(0, f"a/../{MARKER}")),
    ("a blob of 39 hex", lambda w: w["steps"][0]["named"][0].__setitem__(1, "a" * 39)),
    ("a bool for an integer", lambda w: w["steps"][0].update({"seen_ms": True})),
    ("an unknown standing", lambda w: w.update({"standing": MARKER})),
    ("a ship walk that isn't unjudged", lambda w: w.update({"source": "ship"})),
]


@pytest.mark.parametrize("why, change", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_a_bad_walk_is_refused_by_place_and_never_repeats_a_value(why, change):
    w = walk("t1", ["a", "b"])
    change(w)
    with pytest.raises(R.Refused) as refused:
        R.read_walks(line(w), "f.jsonl")
    assert MARKER not in str(refused.value) and "f.jsonl line 1" in str(refused.value), why


def test_a_lines_limit_is_its_bytes_before_the_newline():
    # The room's spec asks that both sides count a walk line alike: 1 MiB before the newline is read, one byte more is not.
    exact = b"x" * R.MAX_LINE + b"\n"
    over = b"x" * (R.MAX_LINE + 1) + b"\n"
    with pytest.raises(R.Refused) as at_limit:
        R.read_walks(exact, "f")
    with pytest.raises(R.Refused) as past_limit:
        R.read_walks(over, "f")
    assert "not one JSON object" in str(at_limit.value) and "longer than 1 MiB" in str(past_limit.value)


def test_steps_numbered_from_0_are_read_and_a_detour_can_be_at_seq_0(tmp_path):
    # The room numbers a turn's steps from 0 (the lead, on the first pilot's 21 real walks); revision 4 refused them.
    def from_zero(w):
        for step in w["steps"]:
            step["seq"] -= 1
        return w
    walks = [from_zero(walk("t1", ["target", "b"])), from_zero(walk("t2", [["a", "target"]])),
             from_zero(walk("t3", ["target"]))]
    assert [s["seq"] for s in walks[0]["steps"]] == [0, 1] and walks[1]["steps"][0]["seq"] == 0
    (back,) = R.read_walks(line(walks[0]), "f")
    assert back == walks[0]
    out, list_id, _ = experiment(tmp_path, walks)
    r = route_of(ask(out, ["target"], list_id))
    assert r["paths"] == ["target"]
    assert [(d["attempt"], d["visit"], d["seq"]) for d in r["detours"]] == [("t2", 2, 0)]   # a detour at seq 0
    with R.open_store(out) as s:
        assert s.check() > 0
    for bad in (-1, None, True):
        w = walk("t9", ["a", "b"])
        w["steps"][0]["seq"] = bad
        with pytest.raises(R.Refused):
            R.read_walks(line(w), "f")
    w = walk("t9", ["a", "b"])
    w["steps"][1]["seq"] = w["steps"][0]["seq"]
    with pytest.raises(R.Refused):
        R.read_walks(line(w), "f")


@pytest.mark.parametrize("data", [b"\xff\xfe\n", ('{"v": NaN}\n').encode(), b'{"v":1,"v":1}\n',
                                  (json.dumps({MARKER: "x" * (1 << 20)}) + "\n").encode(), line(walk("t", ["a"]))[:-1]])
def test_bytes_that_are_no_walk_are_refused_without_their_content(data):
    with pytest.raises(R.Refused) as refused:
        R.read_walks(data, "f.jsonl")
    assert MARKER not in str(refused.value)


# ------------------------------------------------------------------ only listed turns teach


def write_inputs(tmp_path, walks):
    d = tmp_path / "w"
    d.mkdir(exist_ok=True)
    files = {}
    for w in walks:
        files[f"walk-{w['attempt']}.jsonl"] = line(w)
    return files


def test_only_listed_turns_teach_and_an_unverified_pass_is_kept_but_counts_nowhere(tmp_path):
    walks = [walk("t1", ["a", "goal"]), walk("t2", ["b", "goal"], standing="passed_unverified")]
    out, list_id, _ = experiment(tmp_path, walks)
    answer = ask(out, ["goal", "b"], list_id)
    assert answer["taught"] == 1 and route_of(answer)["paths"] == ["a", "goal"]
    assert all(road["turns"] == 1 for road in route_of(answer)["roads"])
    assert answer["answers"][1] == {"goal": "b", "none": "not_taught"}
    assert answer["list"] == list_id and answer["for_experiment"] is True


def admission_cases():
    a, b = walk("t1", ["a"]), walk("t2", ["b"])
    files = {"a.jsonl": line(a), "b.jsonl": line(b)}

    def lst(walks_files, **change):
        turns = sorted(({"attempt": w["attempt"], "item": w["item"], "base": w["base"], "standing": w["standing"],
                         "sha256": hashlib.sha256(data).hexdigest()} for w, data in walks_files), key=lambda e: e["attempt"])
        obj = {"v": 1, "repo": REPO, "measure": {"name": "share", "version": 1}, "turns": turns, **change}
        return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

    good = lst([(a, files["a.jsonl"]), (b, files["b.jsonl"])])
    other_repo = dict(walk("t3", ["c"]), repo="9" * 40)
    ship = walk("t4", ["d"], source="ship")
    yield "an unlisted file", good, {**files, "c.jsonl": line(walk("t3", ["c"]))}
    yield "a second copy of an entry", good, {**files, "copy.jsonl": files["a.jsonl"]}
    yield "a listed entry left out", good, {"a.jsonl": files["a.jsonl"]}
    two = files["a.jsonl"] + files["b.jsonl"]
    yield "a file with two walks", lst([(a, two)]), {"two.jsonl": two}
    yield "another repository's walk", lst([(other_repo, line(other_repo))]), {"o.jsonl": line(other_repo)}
    after = files["a.jsonl"] + line(ship)
    yield "a ship's walk after a room line", lst([(a, after)]), {"s.jsonl": after}
    wrong = dict(a, standing="failed", verdict="failed")
    yield "a standing other than the list's", lst([(a, line(wrong))]), {"a.jsonl": line(wrong)}
    yield "a measure this store has not", lst([(a, files["a.jsonl"])], measure={"name": "share", "version": 2}), \
        {"a.jsonl": files["a.jsonl"]}
    yield "a list not in its form", good.replace(b",", b", ", 1), files
    unsorted = json.loads(good)
    unsorted["turns"].reverse()
    yield "a list not sorted", json.dumps(unsorted, sort_keys=True, separators=(",", ":")).encode(), files


@pytest.mark.parametrize("why, list_bytes, files", list(admission_cases()), ids=[c[0] for c in admission_cases()])
def test_admission_refuses(why, list_bytes, files):
    with pytest.raises(R.Refused):
        R.admit(list_bytes, files)


def test_a_re_exported_file_after_a_standing_changes_is_refused_by_its_hash(tmp_path):
    w = walk("t1", ["a"])
    files = {"a.jsonl": line(w)}
    lst = json.dumps({"v": 1, "repo": REPO, "measure": {"name": "share", "version": 1}, "turns": [
        {"attempt": "t1", "item": w["item"], "base": BASE, "standing": "passed_verified",
         "sha256": hashlib.sha256(files["a.jsonl"]).hexdigest()}]}, sort_keys=True, separators=(",", ":")).encode()
    R.admit(lst, files)
    demoted = dict(w, standing="passed_unverified")
    with pytest.raises(R.Refused):
        R.admit(lst, {"a.jsonl": line(demoted)})


# ------------------------------------------------------------------ a ship's store is apart


def test_a_ships_store_routes_under_its_own_measure_and_never_carries_experiment_flags(tmp_path):
    walks = [walk("s1", ["a", "b"], source="ship"), walk("s2", ["a", "c"], source="ship")]
    f = tmp_path / "ship.jsonl"
    f.write_bytes(b"".join(line(w) for w in walks))
    out = tmp_path / "ship.db"
    R.build(out, [f])
    answer = ask(out, ["b"], None, measure=("ship-share", 1))
    assert answer["list"] is None and answer["for_experiment"] is False and answer["taught"] == 2
    assert route_of(answer)["paths"] == ["a", "b"]
    with pytest.raises(R.Refused):   # an experiment's question to a ship's store
        ask(out, ["b"], "0" * 64)
    with pytest.raises(R.Refused):   # a ship's walk to an experiment's build
        R.admit(listing([walks[0]], [f]), {"ship.jsonl": line(walks[0])})


# ------------------------------------------------------------------ visits and roads


def test_visits_and_roads_and_what_counts():
    one = walk("t1", ["a", "a", "b", "a", ["c", "d", "e"]])          # read then edit is one visit; leave and come back is two
    net = R.Network([one, walk("t2", ["a", "b"]), walk("t3", ["a", "b"]), walk("t4", [])], R.SHARE)
    assert [v[0] for v in R.visits(one)] == ["a", "b", "a", "c", "d", "e"]
    assert net.N == 4                                                   # a taught turn that named nothing counts
    assert net.k[None, "a"] == 3 and net.k["a", "b"] == 3              # t1 walked a to b once: k counts turns
    assert net.k["c", "d"] == 1 and net.k["d", "e"] == 1                # three files in one step, two roads
    assert ("a", "a") not in net.k


def test_two_turns_that_walked_alike_are_one_cell_and_two_turns(tmp_path):
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "x", "g"]), walk("t2", ["a", "x", "g"]),
                                            walk("t3", ["b", "g"]), walk("t4", ["b", "g"]), walk("t5", ["b", "g"])])
    with sqlite3.connect(out) as db:
        cells = {c for (c,) in db.execute("SELECT way_cell FROM detour WHERE path = 'g'")}
    answer = ask(out, ["g"], list_id)
    assert [d["attempt"] for d in route_of(answer)["detours"]] == ["t1", "t2"] and len(cells) == 1


# ------------------------------------------------------------------ the route


def test_a_route_is_stitched_and_the_first_walks_way_is_a_detour(tmp_path):
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a.txt", "b.txt", "target.txt"]), walk("t2", ["b.txt", "x.txt"])])
    r = route_of(ask(out, ["target.txt"], list_id))
    assert r["paths"] == ["b.txt", "target.txt"] and r["roads_n"] == 2
    assert [(x["from"], x["to"], x["witness"]) for x in r["roads"]] == [(None, "b.txt", "t2"), ("b.txt", "target.txt", "t1")]
    assert [d["attempt"] for d in r["detours"]] == ["t1"]
    with R.open_store(out) as s:
        s.check()


def every_simple_way(net, goal):
    paths = net.paths
    for n in range(1, len(paths) + 1):
        for way in itertools.permutations(paths, n):
            if way[-1] == goal and all(road in net.k for road in zip((None,) + way, way)):
                yield list(way)


def oracle(net, goal):
    ways = list(every_simple_way(net, goal))
    if not ways:
        return None
    best = max(net.share(w) for w in ways)
    return min((w for w in ways if net.share(w) == best), key=lambda w: [p.encode() for p in w])


def test_the_search_agrees_with_every_simple_way_on_a_thousand_sets_drawn_at_random():
    rng = random.Random(16)
    names = ["a", "b", "c", "d", "e", "ab", "b/c"]
    for case in range(1000):
        walks = []
        for t in range(rng.randint(1, 5)):
            steps = [rng.sample(names, rng.randint(0, 2)) for _ in range(rng.randint(0, 6))]
            walks.append(walk(f"t{t}", steps))
        net = R.Network(walks, R.SHARE)
        for goal in net.paths:
            assert net.route(goal) == oracle(net, goal), (case, goal)


def test_cheaper_by_the_measure_not_by_roads_and_empty_turns_move_the_prices():
    base = [walk("t1", ["a", "b", "target"]), walk("t2", ["a", "b", "target"]), walk("t3", ["b", "x"])]
    net = R.Network(base, R.SHARE)
    assert net.route("target") == ["a", "b", "target"] and net.share(["a", "b", "target"]) == Fraction(8, 27)
    assert net.share(["b", "target"]) == Fraction(2, 9) and net.detours("target", ["a", "b", "target"]) == ([], 0)
    tie = R.Network(base + [walk("e1", [])], R.SHARE)
    assert tie.share(["a", "b", "target"]) == tie.share(["b", "target"]) == Fraction(1, 8)
    assert tie.route("target") == ["a", "b", "target"]                   # a tie goes to the first in byte order
    two = R.Network(base + [walk("e1", []), walk("e2", [])], R.SHARE)
    assert two.route("target") == ["b", "target"] and two.share(["b", "target"]) == Fraction(2, 25)


def test_zero_cost_cycles_give_a_simple_route_first_in_byte_order():
    walks = [walk(f"t{i}", ["a", "b", "a", "c"]) for i in range(3)]     # every road walked by every turn: all cost nothing
    net = R.Network(walks, R.SHARE)
    assert all(k == 3 for k in net.k.values()) and net.share(["a", "b", "a", "c"]) == 1
    assert net.route("c") == ["a", "c"] and net.route("b") == ["a", "b"]
    assert net.route("a") == ["a"]


# ------------------------------------------------------------------ exact, and the same bytes


def test_the_same_bytes_whatever_order_or_context(tmp_path):
    walks = [walk("t1", ["a", "b", "g"]), walk("t2", ["c", "b", "g"]), walk("t3", ["b", "g"]), walk("t4", ["b", "x"])]
    out1, list_id, _ = experiment(tmp_path, walks, name="one.db")
    out2, list_id2, _ = experiment(tmp_path, list(reversed(walks)), name="two.db")
    assert list_id == list_id2
    q = R.canonical({"v": 1, "repo": REPO, "list": list_id, "measure": {"name": "share", "version": 1},
                     "goals": ["g", "x", "g", "b"]})
    with R.open_store(out1) as s:
        first = s.ask(q)
    with decimal.localcontext() as ctx:   # the ambient context changed: the answer is not
        ctx.prec, ctx.rounding = 5, decimal.ROUND_DOWN
        with R.open_store(out2) as s:
            assert s.ask(q) == first
    answer = json.loads(first)
    assert [a["goal"] for a in answer["answers"]] == ["g", "x", "g", "b"] and answer["answers"][0] == answer["answers"][2]
    assert [d["attempt"] for d in answer["answers"][0]["route"]["detours"]] == ["t1", "t2"]
    assert R.nats(Fraction(1, 2)) == "0.693147181" and R.nats(Fraction(1)) == "0.000000000"
    near = (Fraction(10**20 + 1, 10**21), Fraction(10**20, 10**21))
    assert float(near[0]) == float(near[1]) and near[0] != near[1] and R.cost(near[0])["num"] != R.cost(near[1])["num"]


# ------------------------------------------------------------------ a detour is real


def test_detours_with_a_shared_road_and_a_repeated_file_are_kept_and_checked(tmp_path):
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "b", "target"]), walk("t2", ["a", "b", "a", "b", "target"]),
                                            walk("t3", ["b", "target"]), walk("t4", ["b", "target"]),
                                            walk("t5", ["b", "target"])])
    r = route_of(ask(out, ["target"], list_id))
    assert r["paths"] == ["b", "target"]
    assert {d["attempt"]: d["paths"] for d in r["detours"]} == {"t1": ["a", "b", "target"],
                                                                "t2": ["a", "b", "a", "b", "target"]}
    with R.open_store(out) as s:
        assert s.check() > 0


def test_a_goal_keeps_its_sixteen_cheapest_detours_in_attempt_order_and_counts_the_rest(tmp_path):
    """Store "3": twenty dearer turns. The ten cheaper ones have the later names, so keeping by name, not by cost, keeps
    the wrong ten; the ten dearer ones tie, so the edge goes to the earliest six by bytes; the kept are listed by name."""
    route = [walk(f"r{i:02d}", ["b", "g"]) for i in range(30)]
    cheaper = [walk(f"z{i:02d}", ["a", "b", "g"]) for i in range(10)]           # share (10/N)(10/N)(50/N)
    dearer = [walk(f"e{i:02d}", [f"u{i:02d}", "b", "g"]) for i in range(10)]    # share (1/N)(1/N)(50/N): all tie
    out, list_id, _ = experiment(tmp_path, route + cheaper + dearer)
    r = route_of(ask(out, ["g"], list_id))
    assert r["paths"] == ["b", "g"] and R.DETOURS_KEPT == 16
    assert [d["attempt"] for d in r["detours"]] == [f"e{i:02d}" for i in range(6)] + [f"z{i:02d}" for i in range(10)]
    assert r["detours_more"] == 4 and len(r["detours"]) + r["detours_more"] == 20
    with R.open_store(out) as s:
        assert s.check() > 0
    db = sqlite3.connect(out)
    for goal in ("g", "b"):   # b has the same twenty dearer ways, one road shorter: only the kept are cells
        assert db.execute("SELECT count(*) FROM detour WHERE path = ?", (goal,)).fetchone() == (16,)
        assert db.execute("SELECT count(*) FROM generator WHERE kind = 'detour' AND ref LIKE ?",
                          (f'["{goal}",%',)).fetchone() == (16,)
    assert db.execute("SELECT more FROM goal WHERE path = 'b'").fetchone() == (4,)
    made = [json.loads(ref)[1] for (ref,) in db.execute(
        "SELECT ref FROM generator WHERE kind = 'detour' AND ref LIKE '[\"g\",%' ORDER BY id")]
    assert made == [d["attempt"] for d in r["detours"]]   # the cells too are made in attempt order (section 7)
    db.close()


def test_the_sixteen_are_chosen_by_exact_cost_where_floats_all_say_zero():
    """Seventeen dearer ways whose shares all underflow to 0.0 as floats. The one with the latest name is the cheapest
    by exact comparison, so it is kept; a ranking by float sees seventeen ties and drops it for the earlier names."""
    route = [walk(f"r{i:04d}", ["b", "g"]) for i in range(1000)]   # N over 1,000: each lone road's share is under 1/1000
    far = [walk(f"a{i:02d}", [f"a{i:02d}-{j:03d}" for j in range(115)] + ["b", "g"]) for i in range(16)]
    near = walk("z99", [f"z99-{j:03d}" for j in range(109)] + ["b", "g"])
    net = R.Network(route + far + [near], R.SHARE)
    kept, more = net.detours("g", net.route("g"))
    ways = {w["attempt"]: way for w, way, _, _ in kept}
    assert all(float(net.share(way)) == 0.0 for way in ways.values())   # floats can't tell any of them apart
    assert "z99" in ways and more == 1 and "a15" not in ways             # exact: z99 is cheaper than every a
    assert [w["attempt"] for w, *_ in kept] == [f"a{i:02d}" for i in range(15)] + ["z99"]


def test_nats_takes_nothing_from_the_process_default_context(tmp_path, monkeypatch):   # w83
    """A caller that traps Inexact, or shrinks the exponent's range, in decimal.DefaultContext changes no answer: the
    store's context gives every setting itself."""
    import decimal
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "b", "g"]), walk("t2", ["b", "g"]), walk("t3", ["b", "g"])])
    before = ask(out, ["g", "b"], list_id)
    monkeypatch.setitem(decimal.DefaultContext.traps, decimal.Inexact, True)
    monkeypatch.setattr(decimal.DefaultContext, "Emax", 2)
    monkeypatch.setattr(decimal.DefaultContext, "Emin", -2)
    assert ask(out, ["g", "b"], list_id) == before
    assert R.nats(Fraction(1, 3)) == "1.098612289" and R.nats(Fraction(1, 10 ** 9)) == "20.723265837"


def test_a_goal_with_no_detour_says_none_left_out(tmp_path):
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["b", "g"]), walk("t2", ["b", "g"])])
    r = route_of(ask(out, ["g"], list_id))
    assert r["detours"] == [] and r["detours_more"] == 0


@pytest.mark.parametrize("tamper", [
    "UPDATE goal SET more = 1 WHERE path = 'target'",
    "UPDATE detour SET visit = visit + 1",
    "UPDATE detour SET attempt = 't3'",
    "UPDATE detour SET way = '[\"b\",\"target\"]'",
    "UPDATE detour SET num = '1', den = '1'",
    "UPDATE generator SET ref = '[\"target\",\"t9\"]' WHERE kind = 'detour'",
    "UPDATE goal SET route = '[\"a\",\"b\",\"target\"]' WHERE path = 'target'",
    "UPDATE composite SET recipe = '[\"then\",0,[]]' WHERE dim = 1 AND rowid = 1",
    "DELETE FROM detour WHERE attempt = 't1'",
    "UPDATE walk SET body = CAST(replace(CAST(body AS TEXT), '\"a\"', '\"c\"') AS BLOB) WHERE attempt = 't1'",
], ids=["a count left out", "visit", "turn", "way", "saving", "generator", "route", "recipe", "a lost detour",
        "a walk"])
def test_a_tampered_store_fails_its_check(tmp_path, tamper):
    out, _, _ = experiment(tmp_path, [walk("t1", ["a", "b", "target"]), walk("t2", ["b", "target"]),
                                      walk("t3", ["b", "target"])])
    db = sqlite3.connect(out)
    db.execute(tamper)
    db.commit()
    db.close()
    with pytest.raises(R.IntegrityError), R.open_store(out) as s:
        s.check()


def test_the_kernel_refuses_a_detour_whose_ends_do_not_meet():
    cat = NCat(budget_bytes=1 << 24)
    start, a, b, c = (cat.object() for _ in range(4))
    to_b, to_c = cat.generator(start, b), cat.generator(start, c)
    with pytest.raises(NCatError):
        cat.generator(to_b, to_c)


# ------------------------------------------------------------------ what is not there is said


def test_each_kind_of_absence_in_its_precedence(tmp_path):
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["only-failed"], standing="failed")])
    answer = ask(out, ["only-failed", "nowhere"], list_id)
    assert answer["taught"] == 0
    assert [a["none"] for a in answer["answers"]] == ["no_history", "no_history"]
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a"]), walk("t2", ["u"], standing="passed_unverified")],
                                 name="two.db")
    answer = ask(out, ["nowhere", "u", "a"], list_id)
    assert [a.get("none") for a in answer["answers"]] == ["never_named", "not_taught", None]


def test_a_kernel_refusal_is_said_with_its_code(tmp_path):
    walks = [walk(f"t{i}", [f"p{j}" for j in range(i, i + 12)] + ["goal"]) for i in range(6)]
    found = None
    for budget in range(20_000, 400_000, 4_000):   # just enough for the cells every goal needs, not for every route
        try:
            out, list_id, _ = experiment(tmp_path, walks, budget=budget, name=f"b{budget}.db")
        except NCatError:
            continue
        with R.open_store(out) as s:
            refused = [g for (g,) in s._db.execute("SELECT path FROM goal WHERE code IS NOT NULL")]
            assert s.check() > 0   # a refusal replays as a refusal
        if refused:
            found = (out, list_id, refused[0])
            break
    assert found, "no budget refused a goal while the build stood"
    out, list_id, goal = found
    (a,) = ask(out, [goal], list_id)["answers"]
    assert a["none"] == "refused" and a["code"] == -10 and a["reason"]


# ------------------------------------------------------------------ a question is the store's


def test_a_question_of_another_list_repository_or_measure_is_refused_not_answered(tmp_path):
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a"])])
    ask(out, ["a"], list_id)
    for change in ({"list": "0" * 64}, {"repo": "9" * 40}, {"measure": {"name": "ship-share", "version": 1}},
                   {"measure": {"name": "share", "version": True}}, {"goals": ["a b"]}, {"v": 2}):
        q = {"v": 1, "repo": REPO, "list": list_id, "measure": {"name": "share", "version": 1}, "goals": ["a"], **change}
        with pytest.raises(R.Refused), R.open_store(out) as s:
            s.ask(R.canonical(q))


# ------------------------------------------------------------------ the store is the store


def test_a_failed_build_leaves_the_old_file_and_a_good_one_replaces_it(tmp_path):
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "b"])])
    before = out.read_bytes()
    with pytest.raises(NCatError):
        experiment(tmp_path, [walk("t2", ["c", "d"])], budget=64)   # too small for the start: the build stops
    assert out.read_bytes() == before
    assert not [p for p in tmp_path.iterdir() if ".tmp-" in p.name]
    experiment(tmp_path, [walk("t3", ["e"])])
    with R.open_store(out) as s:
        assert [a["route"]["paths"] for a in json.loads(s.ask(R.canonical(
            {"v": 1, "repo": REPO, "list": s.list, "measure": {"name": "share", "version": 1}, "goals": ["e"]})))["answers"]] \
            == [["e"]]


def test_nothing_in_recall_reads_the_route_store():
    engram = Path(R.__file__).resolve().parent
    readers = [p.name for p in engram.glob("*.py") if p.name != "ncat_routes.py" and "ncat_routes" in p.read_text()]
    assert readers == []


# ------------------------------------------------------------------ w50's named changes on 2d1a2dac, each its probe


def test_two_listed_turns_with_one_digest_are_refused():   # C2
    a = walk("t1", ["a"])
    data = line(a)
    entry = {"attempt": "t1", "item": a["item"], "base": BASE, "standing": "passed_verified",
             "sha256": hashlib.sha256(data).hexdigest()}
    lst = json.dumps({"v": 1, "repo": REPO, "measure": {"name": "share", "version": 1},
                      "turns": [dict(entry, attempt="t0"), entry]}, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(R.Refused):
        R.read_list(lst)
    with pytest.raises(R.Refused):
        R.admit(lst, {"a.jsonl": data})


@pytest.mark.parametrize("field", ["family", "tool"])
def test_a_family_or_tool_outside_the_rooms_words_is_refused(field):   # C3
    planted = MARKER.replace("-", "_")
    w = walk("t1", ["a"])
    if field == "family":
        w["family"] = planted
    else:
        w["steps"][0]["tool"] = planted
    with pytest.raises(R.Refused) as refused:
        R.read_walks(line(w), "f")
    assert planted not in str(refused.value)
    for word in R.FAMILIES:
        R.read_walks(line(walk("t1", ["a"], family=word)), "f")
    for word in R.TOOLS:
        ok = walk("t1", ["a"])
        ok["steps"][0]["tool"] = word
        R.read_walks(line(ok), "f")


def test_a_file_seen_at_two_blobs_in_a_row_is_one_visit_with_both_blobs(tmp_path):   # C4
    w = walk("s1", ["a", "b"], source="ship")
    w["steps"][0]["named"] = [["a", "1" * 40], ["a", "2" * 40]]
    assert [v[0] for v in R.visits(w)] == ["a", "b"]
    f = tmp_path / "ship.jsonl"
    f.write_bytes(line(w))
    out = tmp_path / "ship.db"
    R.build(out, [f])
    r = route_of(ask(out, ["a"], None, measure=("ship-share", 1)))
    assert r["paths"] == ["a"] and r["blobs"] == {"a": ["1" * 40, "2" * 40]}


def test_a_library_the_old_loader_named_for_this_source_is_not_reused(tmp_path, monkeypatch):   # w73 1
    """The old loader hashed the source, then compiled the file by rereading it, so a library in its cache may hold
    other bytes than the ones it is named for. The new loader's names carry a cache format, so none is taken."""
    import os
    import platform
    import sys
    import ncat
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs.get("input")))
        Path(argv[argv.index("-o") + 1]).write_bytes(b"")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(ncat.subprocess, "run", fake_run)
    source = ncat.SOURCE.read_bytes()
    compiler = next(c for c in ncat.COMPILERS if os.access(c, os.X_OK))
    flags = ncat.FLAGS + (ncat.LINUX_FLAGS if sys.platform.startswith("linux") else ())
    machine = f"{sys.platform} {platform.machine()}"
    old_tag = hashlib.blake2b(source + compiler.encode() + " ".join(flags).encode() + machine.encode(),
                              digest_size=12).hexdigest()   # the old loader's name for this source
    cache = tmp_path / "superyak" / "ncat"
    cache.mkdir(parents=True, mode=0o700)
    old = cache / f"ncat-{old_tag}.so"
    old.write_bytes(b"compiled by the old loader, from bytes the file held a moment later")
    old.chmod(0o700)
    salted = hashlib.blake2b(ncat.CACHE_FORMAT + source + compiler.encode() + " ".join(flags).encode()
                             + machine.encode(), digest_size=12).hexdigest()
    clash = cache / f"ncat-{salted}.so"   # an old-loader name that equals this loader's digest: w78's history
    clash.write_bytes(b"compiled by the old loader under a name this digest also gives")
    clash.chmod(0o700)
    built = ncat._built(source)
    assert built.name == f"ncat-2-{salted}.so"                  # a namespace the old loader never wrote in
    assert built not in (old, clash) and len(seen) == 1          # compiled again, neither old name taken
    argv, given = seen[0]
    assert argv[argv.index("-x") + 1:argv.index("-x") + 3] == ["c", "-"] and given == source   # from the bytes hashed
    assert ncat._built(source) == built and len(seen) == 1     # and its own name is then reused


@pytest.mark.parametrize("damage", ["a long listing", "a long header", "a deep header", "a long walk", "many walks",
                                    "a garbled walk", "a walk stored as text", "a zero denominator", "a deep route",
                                    "a list stored as text", "a NUL in a text list", "a deep list", "a key stored as blob",
                                    "a right list stored as text", "a zero share", "a share above one",
                                    "roads_n as text", "a refusal's words as blob", "a refusal with no words",
                                    "a refusal's code as text"])
def test_a_stored_file_is_measured_before_it_is_read(tmp_path, monkeypatch, damage):   # w73 2
    """Opening or answering from a damaged store refuses it as damage, having fetched nothing past a bound: the
    listing and header are measured inside SQLite first, and no stored value comes out whole past a walk's bound."""
    out, list_id, _ = experiment(tmp_path, [walk("t1", [f"p{i}" for i in range(10)] + ["g"]),
                                            walk("t2", [f"q{i}" for i in range(10)] + ["g"])])
    db = sqlite3.connect(out)
    if damage == "a long listing":
        db.execute("UPDATE listing SET body = zeroblob(?)", (R.MAX_LIST + 1,))
    elif damage == "a long header":
        db.execute("UPDATE meta SET value = ? WHERE key = 'budget'", ("9" * 5000,))   # well formed, only too long
    elif damage == "a deep header":
        db.execute("UPDATE meta SET value = ? WHERE key = 'measure'", ("[" * 2000 + "]" * 2000,))   # 4,000 bytes
    elif damage == "a garbled walk":
        db.execute("UPDATE walk SET body = CAST('not a walk' AS BLOB) WHERE attempt = 't1'")
    elif damage == "a walk stored as text":
        db.execute("UPDATE walk SET body = CAST(body AS TEXT) WHERE attempt = 't1'")
    elif damage == "a zero denominator":
        db.execute("UPDATE goal SET den = '0' WHERE path = 'g'")
    elif damage == "a deep route":
        db.execute("UPDATE goal SET route = ? WHERE path = 'g'", ("[" * 10000 + "]" * 10000,))
    elif damage == "a list stored as text":   # 4 MiB of characters, 8 MiB of bytes
        db.execute("UPDATE listing SET body = ?", ("\u00e9" * R.MAX_LIST,))
    elif damage == "a NUL in a text list":    # SQLite's length() of TEXT stops at a NUL
        db.execute("UPDATE listing SET body = ?", ("\x00" + "x" * (R.MAX_LIST + 1),))
    elif damage == "a deep list":             # 4,000 bytes, nested 2,000 deep
        db.execute("UPDATE listing SET body = ?", (b"[" * 2000 + b"]" * 2000,))
    elif damage == "a zero share":            # nats of 0 raised decimal's InvalidOperation from ask
        db.execute("UPDATE goal SET num = '0' WHERE path = 'g'")
    elif damage == "a share above one":       # answered with a negative nats
        db.execute("UPDATE goal SET num = '2', den = '1' WHERE path = 'g'")
    elif damage == "roads_n as text":         # answered as a string
        db.execute("UPDATE goal SET roads_n = 'wrong' WHERE path = 'g'")
    elif damage == "a refusal's words as blob":   # escaped as a TypeError while the answer was written
        db.execute("UPDATE goal SET code = -10, reason = CAST('over budget' AS BLOB) WHERE path = 'g'")
    elif damage == "a refusal with no words":     # w83: answered, exit 0, without the refusal-type guard
        db.execute("UPDATE goal SET code = -10, reason = NULL WHERE path = 'g'")
    elif damage == "a refusal's code as text":
        db.execute("UPDATE goal SET code = 'over', reason = 'over budget' WHERE path = 'g'")
    elif damage == "a right list stored as text":
        db.execute("UPDATE listing SET body = CAST(body AS TEXT)")
    elif damage == "a key stored as blob":
        db.execute("UPDATE meta SET key = CAST(key AS BLOB) WHERE key = 'budget'")
    (listing_bytes,) = db.execute("SELECT length(CAST(body AS BLOB)) FROM listing").fetchone()
    (shortest_walk,) = db.execute("SELECT min(length(body)) FROM walk").fetchone()
    db.commit()
    db.close()
    if damage == "a long walk":   # the store opens, its listing within the bound, and its walks past it
        assert listing_bytes < shortest_walk
        monkeypatch.setattr(R, "MAX_FILE", listing_bytes)
    if damage == "many walks":
        monkeypatch.setattr(R, "MAX_WALKS", 1)
    with pytest.raises(R.IntegrityError) as caught:
        ask(out, ["g"], list_id)
    if damage == "a walk stored as text":
        assert "not the type it was written as" in str(caught.value)
    with pytest.raises(R.IntegrityError), R.open_store(out) as s:
        s.check()
    assert R.main(["check", "--store", str(out)]) == 3      # damage, never a traceback or "the kernel stopped" (5)
    import io
    import sys

    class Stdin:
        buffer = io.BytesIO(R.canonical({"v": 1, "repo": REPO, "list": list_id,
                                         "measure": {"name": "share", "version": 1}, "goals": ["g"]}))
    monkeypatch.setattr(sys, "stdin", Stdin())
    assert R.main(["ask", "--store", str(out)]) == 3


@pytest.mark.parametrize("damage", ["UPDATE detour SET num = den", "UPDATE detour SET num = '0'",
                                    "UPDATE detour SET seq = 'late'", "UPDATE detour SET way = '[]'",
                                    "UPDATE detour SET way = '[7,\"g\"]'"],
                         ids=["no dearer", "a zero share", "seq as text", "no way", "a way with a number in it"])
def test_a_damaged_detour_row_is_damage_when_answering_too(tmp_path, damage):   # the board's edges, for detours
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "g"]), walk("t2", ["g"]), walk("t3", ["g"])])
    assert route_of(ask(out, ["g"], list_id))["detours"]
    db = sqlite3.connect(out)
    db.execute(damage)
    db.commit()
    db.close()
    with pytest.raises(R.IntegrityError):
        ask(out, ["g"], list_id)
    with pytest.raises(R.IntegrityError), R.open_store(out) as s:
        s.check()


def test_a_header_or_list_too_long_is_never_fetched(tmp_path, monkeypatch):   # w78 5
    """The header and the list are measured inside SQLite: when one is too long, the query that would fetch it is
    never run."""
    queries = []

    class Recording(sqlite3.Connection):
        def execute(self, sql, *args):
            queries.append(sql)
            return super().execute(sql, *args)
    real = sqlite3.connect
    monkeypatch.setattr(R.sqlite3, "connect", lambda *a, **k: real(*a, factory=Recording, **k))
    for damage, fetch in ((("UPDATE meta SET key = ? WHERE key = 'budget'", ("k" * (R.MAX_HEADER + 1),)),
                           "SELECT key, value FROM meta"),
                          (("UPDATE listing SET body = zeroblob(?)", (R.MAX_LIST + 1,)), "SELECT body FROM listing")):
        out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "g"]), walk("t2", ["g"])])
        db = real(out)
        db.execute(*damage)
        db.commit()
        db.close()
        queries.clear()
        with pytest.raises(R.IntegrityError):
            R.RouteStore(out)
        assert queries and fetch not in queries, (fetch, queries)


def test_a_stored_header_is_parsed_only_after_its_depth_is_measured(tmp_path, monkeypatch):   # w78 5
    import types
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "g"])])
    db = sqlite3.connect(out)
    db.execute("UPDATE meta SET value = ? WHERE key = 'measure'", ("[" * 2000 + "]" * 2000,))
    db.commit()
    db.close()
    parsed = []

    def loads(text, **kw):
        parsed.append(text)
        return json.loads(text, **kw)
    monkeypatch.setattr(R, "json", types.SimpleNamespace(loads=loads, dumps=json.dumps))
    with pytest.raises(R.IntegrityError):
        R.RouteStore(out)
    assert all(R._depth(t) <= R.MAX_DEPTH for t in parsed)   # the deep one never reached the parser


def test_stored_bounds_take_their_last_byte(tmp_path, monkeypatch):   # w78 5
    """A header value of exactly 4 KiB opens and answers, one byte more is damage; a stored walk of exactly the
    length limit is fetched, one byte more is damage."""
    for extra, opens in ((0, True), (1, False)):
        out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "g"]), walk("t2", ["g"])])
        db = sqlite3.connect(out)
        db.execute("UPDATE meta SET value = ? WHERE key = 'budget'", ("1" + "0" * (R.MAX_HEADER - 1 + extra),))
        db.commit()
        db.close()
        if opens:
            assert ask(out, ["g"], list_id)["taught"] == 2
        else:
            with pytest.raises(R.IntegrityError):
                ask(out, ["g"], list_id)
    out, list_id, _ = experiment(tmp_path, [walk("t1", [f"p{i}" for i in range(10)] + ["g"]),
                                            walk("t2", [f"q{i}" for i in range(10)] + ["g"])])
    db = sqlite3.connect(out)
    (longest,) = db.execute("SELECT max(length(body)) FROM walk").fetchone()
    db.close()
    monkeypatch.setattr(R, "MAX_FILE", longest)
    assert ask(out, ["g"], list_id)["taught"] == 2
    monkeypatch.setattr(R, "MAX_FILE", longest - 1)
    with pytest.raises(R.IntegrityError):
        ask(out, ["g"], list_id)


def test_a_file_named_by_any_path_like_object_is_read(tmp_path):   # w73 3
    from pathlib import PurePosixPath

    class Named:
        def __init__(self, path):
            self.path = path if isinstance(path, bytes) else str(path)

        def __fspath__(self):
            return self.path
    import os
    walks = sorted(FIXTURE.glob("walk-*.jsonl"))
    kinds = {"str": str, "bytes": os.fsencode, "PurePosixPath": PurePosixPath, "fspath str": Named,
             "fspath bytes": lambda p: Named(os.fsencode(p))}
    for name, kind in kinds.items():
        out = tmp_path / f"{name.replace(' ', '-')}.db"
        R.build(out, [kind(w) for w in walks], kind(FIXTURE / "list.json"))
        with R.open_store(out) as s:
            assert s.ask((FIXTURE / "question.json").read_bytes()) == fixture_answer(), name
    with open(walks[0], "rb") as stream, pytest.raises(TypeError):   # a stream is no file's name, for walk or list
        R.build(tmp_path / "s.db", [stream])
    with open(FIXTURE / "list.json", "rb") as stream, pytest.raises(TypeError):
        R.build(tmp_path / "s.db", walks, stream)


def test_each_bound_takes_its_last_byte_and_refuses_the_next(tmp_path, monkeypatch, capsys):   # w73 4
    import sys
    one = walk("t1", ["a", "g"])
    f = tmp_path / "walk-t1.jsonl"
    f.write_bytes(line(one))
    lst = listing([one], [f])
    lf = tmp_path / "list.json"
    lf.write_bytes(lst)
    monkeypatch.setattr(R, "MAX_FILE", len(line(one)))
    monkeypatch.setattr(R, "MAX_LIST", len(lst))
    R.build(tmp_path / "at.db", [f], lf)                        # exactly at both bounds: built
    monkeypatch.setattr(R, "MAX_FILE", len(line(one)) - 1)
    with pytest.raises(R.Refused, match="longer than 64 MiB"):
        R.build(tmp_path / "past.db", [f], lf)
    monkeypatch.setattr(R, "MAX_FILE", len(line(one)))
    monkeypatch.setattr(R, "MAX_LIST", len(lst) - 1)
    with pytest.raises(R.Refused, match="longer than 4 MiB"):
        R.build(tmp_path / "past.db", [f], lf)
    empty = tmp_path / "walk-empty.jsonl"
    empty.write_bytes(b"")
    with pytest.raises(R.Refused) as caught:
        R.build(tmp_path / "empty.db", [empty])
    assert "longer than" not in str(caught.value)              # empty is refused as no walk, not as too long
    monkeypatch.setattr(R, "MAX_FILE", 64 << 20)   # the store opens under its real bounds again
    monkeypatch.setattr(R, "MAX_LIST", 4 << 20)
    question = R.canonical({"v": 1, "repo": REPO, "list": hashlib.sha256(lst).hexdigest(),
                            "measure": {"name": "share", "version": 1}, "goals": ["g"]})

    class Stdin:
        def __init__(self, data):
            self.buffer = __import__("io").BytesIO(data)
    for bound, data, code in ((len(question), question, 0), (len(question) - 1, question, 2), (len(question), b"", 2)):
        monkeypatch.setattr(R, "MAX_QUESTION", bound)
        monkeypatch.setattr(sys, "stdin", Stdin(data))
        assert R.main(["ask", "--store", str(tmp_path / "at.db")]) == code, (bound, len(data))
    out = capsys.readouterr()
    assert out.err.count("longer than 1 MiB") == 1 and '"taught":1' in out.out


def test_the_kernel_digest_is_of_the_source_the_loaded_library_was_built_from(tmp_path, monkeypatch):   # C5, R2
    """Loaded fresh from an installed wheel's copy, the digest is that copy's. Then the source changes on disk in the
    same long-lived process: the library in use is still the old one, and so is the digest a new store records."""
    import ncat
    import ncat_store
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))   # a fresh build, not the cached library
    monkeypatch.delenv("NCAT_TEST_SO", raising=False)
    monkeypatch.setattr(ncat, "_lib", None)
    monkeypatch.setattr(ncat, "_lib_source", None)
    shared = tmp_path / "share" / "engram" / "ncat_kernel.c"   # an installed wheel's place for it
    shared.parent.mkdir(parents=True)
    shared.write_bytes(ncat.SOURCE.read_bytes() + b"\n/* the installed copy */\n")
    monkeypatch.setattr(ncat, "SOURCE", shared)
    monkeypatch.setattr(ncat_store, "__file__", str(tmp_path / "site-packages" / "ncat_store.py"))   # nothing beside it
    loaded = hashlib.sha256(shared.read_bytes()).hexdigest()[:16]
    assert R._kernel_digest() == loaded
    shared.write_bytes(shared.read_bytes() + b"/* changed after the library was loaded */\n")
    assert R._kernel_digest() == loaded != hashlib.sha256(shared.read_bytes()).hexdigest()[:16]
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a"])])
    assert ask(out, ["a"], list_id)["kernel"] == loaded


def test_a_walk_whose_fraction_outgrows_4300_digits_builds_answers_and_checks(tmp_path):   # C6
    import sys
    if not 0 < sys.get_int_max_str_digits() < 4516:
        pytest.skip("the digit ceiling isn't in force here")
    long = walk("t1", [["a", "b"] * 7500 + ["goal"]])   # 735 KB, one step: a and b 7,500 times, then the goal
    out, list_id, _ = experiment(tmp_path, [long, walk("t2", [])])
    r = route_of(ask(out, ["goal"], list_id))
    assert r["paths"] == ["a", "b", "goal"] and r["cost"]["num"] == "1" and r["cost"]["den"] == "8"
    (detour,) = r["detours"]
    assert detour["roads_n"] == 15001 and detour["cost"]["num"] == "1" and len(detour["cost"]["den"]) == 4516
    assert int(R._undec(detour["cost"]["den"])) == 2 ** 15001
    with R.open_store(out) as s:
        assert s.check() > 0


DEEP = b"[" * 10000 + b"0" + b"]" * 10000


def test_deep_json_is_refused_where_it_is_read(tmp_path):   # C7
    with pytest.raises(R.Refused, match="nested deeper than 8"):
        R.read_walks(DEEP + b"\n", "f")
    with pytest.raises(R.Refused, match="nested deeper than 8"):
        R.read_list(DEEP)
    out, _, _ = experiment(tmp_path, [walk("t1", ["a"])])
    with pytest.raises(R.Refused, match="nested deeper than 8"), R.open_store(out) as s:
        s.ask(DEEP)
    past = b"[" * 9 + b"0" + b"]" * 9   # past the bound by one, and refused by it, not by the schema
    with pytest.raises(R.Refused, match="nested deeper than 8"):
        R.read_walks(past + b"\n", "f")
    at = b'["' + b"[" * 3 + b'", ' + b"[" * 7 + b"0" + b"]" * 7 + b"]"   # depth 8; brackets in a string don't count
    with pytest.raises(R.Refused, match="not one JSON object|must be an object"):
        R.read_walks(at + b"\n", "f")


def test_a_lone_surrogate_in_the_list_is_refused():   # C7
    with pytest.raises(R.Refused):
        R.read_list(b'{"measure":{},"repo":"\\ud800","turns":[],"v":1}')


def test_byte_bounds_are_checked_before_reading(tmp_path):   # C7
    big = tmp_path / "big.jsonl"
    with open(big, "wb") as f:
        f.truncate(R.MAX_FILE + 1)   # sparse: read to one byte past the bound, then refused
    with pytest.raises(R.Refused, match="longer than 64 MiB"):
        R.build(tmp_path / "x.db", [big])
    with pytest.raises(R.Refused, match="longer than 4 MiB"):
        R.read_list(b" " * (R.MAX_LIST + 1))
    out, _, _ = experiment(tmp_path, [walk("t1", ["a"])])
    with pytest.raises(R.Refused, match="longer than 1 MiB"), R.open_store(out) as s:
        s.ask(b" " * (R.MAX_QUESTION + 1))


def test_reads_are_bounded_by_what_is_read_not_by_a_size_the_file_reports(tmp_path, monkeypatch, capsys):   # R1
    """/dev/zero reports a size of 0 and never ends: a walk file or a list read from it is refused one byte past its
    bound. The CLI reads a question the same way, one byte past 1 MiB and no more."""
    import sys
    monkeypatch.setattr(R, "MAX_FILE", 1000)
    monkeypatch.setattr(R, "MAX_LIST", 1000)
    endless = Path("/dev/zero")
    assert endless.stat().st_size == 0
    with pytest.raises(R.Refused, match="longer than 64 MiB"):
        R.build(tmp_path / "x.db", [endless])
    good = tmp_path / "walk-t1.jsonl"
    good.write_bytes(line(walk("t1", ["a"], source="ship")))
    with pytest.raises(R.Refused, match="longer than 4 MiB"):
        R.build(tmp_path / "x.db", [good], endless)
    out, _, _ = experiment(tmp_path, [walk("t1", ["a"])])
    asked = []

    class Endless:   # a stdin whose bytes never end, and which says how much was asked of it
        def read(self, n=-1):
            asked.append(n)
            return b" " * (n if n >= 0 else 1 << 24)

    class Stdin:
        buffer = Endless()

    monkeypatch.setattr(sys, "stdin", Stdin())
    assert R.main(["ask", "--store", str(out)]) == 2
    assert "longer than 1 MiB" in capsys.readouterr().err and asked == [R.MAX_QUESTION + 1]


def test_a_seq_past_2_63_less_1_is_refused_and_the_largest_kept_is_stored_and_checked(tmp_path):   # R3
    w = walk("t2", ["a", "g"])
    w["steps"][1]["seq"] = R.MAX_SEQ
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["g"]), walk("t3", ["g"]), w])
    (d,) = route_of(ask(out, ["g"], list_id))["detours"]
    assert (d["attempt"], d["seq"]) == ("t2", 2 ** 63 - 1)
    with R.open_store(out) as s:
        assert s.check() > 0
    w["steps"][1]["seq"] = R.MAX_SEQ + 1
    with pytest.raises(R.Refused, match=r"steps\[1\]\.seq is past 2\^63 - 1"):
        R.read_walks(line(w), "walk-t2.jsonl")


def test_aggregate_bounds_are_checked_before_any_network(tmp_path, monkeypatch):   # C7
    walks = [walk(f"s{i}", ["a", "b"], source="ship") for i in range(3)]
    f = tmp_path / "ships.jsonl"
    f.write_bytes(b"".join(line(w) for w in walks))
    monkeypatch.setattr(R, "MAX_WALKS", 2)
    with pytest.raises(R.Refused, match="more than 2"):
        R.build(tmp_path / "x.db", [f])
    monkeypatch.setattr(R, "MAX_WALKS", 10)
    monkeypatch.setattr(R, "MAX_NAMED", 5)
    monkeypatch.setattr(R, "Network", lambda *a: pytest.fail("a network was made past the bound"))
    with pytest.raises(R.Refused, match="more than 5 files"):
        R.build(tmp_path / "x.db", [f])


def test_the_cli_calls_deep_input_a_refusal_not_a_kernel_stop(tmp_path, monkeypatch, capsys):   # C7
    import io
    import sys
    out, _, _ = experiment(tmp_path, [walk("t1", ["a"])])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(DEEP)))
    assert R.main(["ask", "--store", str(out)]) == 2
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize("damage", [
    "UPDATE walk SET taught = 0",
    "UPDATE walk SET family = 'codex' WHERE attempt = 't1'",
    "UPDATE walk SET item = 'other' WHERE attempt = 't2'",
    "UPDATE walk SET standing = 'failed' WHERE attempt = 't2'",
    "UPDATE listing SET body = CAST('{}' AS BLOB)",
], ids=["taught", "family", "item", "standing", "listing"])
def test_a_damaged_walk_row_or_list_fails_the_check(tmp_path, damage):   # C8
    out, list_id, _ = experiment(tmp_path, [walk("t1", ["a", "g"]), walk("t2", ["g"])])
    db = sqlite3.connect(out)
    db.execute(damage)
    db.commit()
    db.close()
    with pytest.raises(R.IntegrityError), R.open_store(out) as s:
        s.check()


@pytest.mark.parametrize("damage", [
    "UPDATE meta SET value = 'not-a-digest' WHERE key = 'kernel'",
    "UPDATE meta SET value = '\"unbound-list\"' WHERE key = 'list'",
    "UPDATE meta SET value = 'false' WHERE key = 'for_experiment'",
    "UPDATE meta SET value = '1' WHERE key = 'store'",
    "UPDATE meta SET value = '[\"ship-share\", 1]' WHERE key = 'measure'",
    "UPDATE meta SET value = '0' WHERE key = 'budget'",
    "DELETE FROM listing",
    "INSERT INTO meta VALUES ('extra', '1')",
    "UPDATE meta SET value = '[\"share\",true]' WHERE key = 'measure'",
    "UPDATE meta SET value = '[\"share\",1.0]' WHERE key = 'measure'",
    "UPDATE meta SET value = '[\"share\",1,1]' WHERE key = 'measure'",
], ids=["kernel", "list", "flag", "store version", "measure", "budget", "no listing", "extra key", "version true",
        "version 1.0", "a third part"])
def test_a_damaged_header_is_refused_when_the_store_is_opened(tmp_path, damage):   # C8
    out, _, _ = experiment(tmp_path, [walk("t1", ["a"])])
    db = sqlite3.connect(out)
    db.execute(damage)
    db.commit()
    db.close()
    with pytest.raises(R.IntegrityError):
        R.RouteStore(out)


def test_a_ships_store_that_claims_to_be_an_experiments_is_refused(tmp_path):   # C8
    f = tmp_path / "ship.jsonl"
    f.write_bytes(line(walk("s1", ["a"], source="ship")))
    out = tmp_path / "ship.db"
    R.build(out, [f])
    db = sqlite3.connect(out)
    db.execute("UPDATE meta SET value = 'true' WHERE key = 'for_experiment'")
    db.commit()
    db.close()
    with pytest.raises(R.IntegrityError):
        R.RouteStore(out)
