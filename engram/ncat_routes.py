"""Walks into roads, and a route back: the store's side of the route offered to a turn.

Spec: docs/superpowers/specs/2026-11-16-v2-walks-into-routes.md (revision 7, store "3"), against the room's
docs/superpowers/specs/2026-11-16-v2-a-route-offered.md. The room writes walk files and a list of the turns that may
teach; this reads them, keeps their roads, routes and detours as cells on the n-category kernel, in a file rebuilt whole
and renamed into place, and answers a route for each file the room asks for, with the same bytes on any machine.

Two layers. `network` and `answer` are pure: everything is worked out from the walks, exactly, with no kernel. `build`
makes the cells through the kernel in the spec's fixed order and writes the file; `RouteStore.check` replays every cell,
recomputes everything the pure layer works out, and compares. A query reads the finished file and makes no cell.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import heapq
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from pathlib import Path

import ncat
from ncat import ERRORS, NCat, NCatError
from ncat_store import BUDGET_BYTES, _compose, _fsync

FORMAT = 1
PATH_RULE = 1
# The store's version in every answer: raised whenever an answer's bytes could change for the same walks, list and
# question. The kernel's is the digest of the kernel source that built the store's cells. Version 2: blobs are every
# taught step's, not only each visit's first (w50's C4). A file built by another version is refused, to be built again.
STORE_VERSION = "3"
DETOURS_KEPT = 16        # a goal's detours kept, the cheapest; the rest are only counted (spec section 6, store "3")
MAX_LINE = 1 << 20       # a walk line's bytes before its newline
MAX_LIST = 4 << 20       # the list's bytes
MAX_QUESTION = 1 << 20   # a question's bytes
MAX_FILE = 64 << 20      # a walk file's bytes, refused before it is read
MAX_WALKS = 10_000       # walks in one store
MAX_NAMED = 1_000_000    # named files over all of a store's steps, counted before any network or cell is made
MAX_DEPTH = 8            # JSON nesting: a walk needs 5, a list 3, a question 2
FAMILIES = ("claude", "codex", "script")                            # the room's (room/src/history.rs)
TOOLS = ("read", "edit", "write", "search", "shell", "other")       # the room's Tool (room/src/types.rs)
SHARE = ("share", 1)
SHIP_SHARE = ("ship-share", 1)
TEACHES = {SHARE: ("passed_verified",), SHIP_SHARE: ("unjudged",)}
STANDINGS = ("passed_verified", "passed_unverified", "failed", "unjudged")
VERDICTS = ("passed", "failed", None)
CHANGES = ("added", "changed", "removed")
PATH_BYTES = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-")
HEX = frozenset("0123456789abcdef")
WALK_KEYS = ("attempt", "base", "changed", "family", "item", "repo", "source", "standing", "steps", "v", "verdict")
STEP_KEYS = ("named", "ok", "result_ms", "seen_ms", "seq", "tokens_in", "tokens_out", "tool")
LIST_KEYS = ("measure", "repo", "turns", "v")
ENTRY_KEYS = ("attempt", "base", "item", "sha256", "standing")
QUESTION_KEYS = ("goals", "list", "measure", "repo", "v")
META_KEYS = ("budget", "for_experiment", "kernel", "list", "measure", "repo", "store", "v")
DIGITS = frozenset("0123456789")
STRING = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"')
BRACKET = re.compile(r"[\[\]{}]")


def _kernel_digest():
    """The digest of the kernel source the loader builds from: `ncat.SOURCE`, an installed wheel's shared copy included."""
    return hashlib.sha256(ncat.SOURCE.read_bytes()).hexdigest()[:16]


def _dec(n):
    """A whole number's decimal digits, exactly, with no ceiling: `str(int)` stops at 4,300 digits."""
    return str(Decimal(n))


def _undec(text):
    """The whole number a string of decimal digits names, exactly, with no ceiling; anything else is refused."""
    if not isinstance(text, str) or not text or not set(text) <= DIGITS or (len(text) > 1 and text[0] == "0"):
        raise ValueError("not a whole number's digits")
    return int(Decimal(text))


class Refused(ValueError):
    """Input the spec refuses. The message names a place, never a value or a key the input chose."""


class IntegrityError(RuntimeError):
    """The file doesn't hold what its walks make: rebuild it."""


class Busy(RuntimeError):
    """Another build of the same file holds the lock."""


class TooDeep(ValueError):
    """JSON nested past MAX_DEPTH, refused before it is parsed."""


# ------------------------------------------------------------------ reading and admitting


def plain_path(path):
    """The room's rule (v2/crates/room/src/walk.rs, plain_path), exactly."""
    if not isinstance(path, str):
        return False
    data = path.encode("utf-8", "surrogatepass")
    return (0 < len(data) <= 512 and not path.startswith("/") and all(b in PATH_BYTES for b in data)
            and all(part not in ("", ".", "..") for part in path.split("/")))


def _hex(value, lengths=(40, 64)):
    return isinstance(value, str) and len(value) in lengths and set(value) <= HEX


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _refuse_constant(_):
    raise ValueError("not JSON")


def _pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a key twice")
    return dict(pairs)


def _depth(text):
    """How deep the JSON's brackets nest, outside its strings."""
    depth = deepest = 0
    for bracket in BRACKET.findall(STRING.sub('""', text)):
        depth += 1 if bracket in "[{" else -1
        deepest = max(deepest, depth)
    return deepest


def _json(text):
    if _depth(text) > MAX_DEPTH:
        raise TooDeep
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_refuse_constant)
    except RecursionError:   # a backstop: the bound above refuses first
        raise TooDeep from None


def _keys(obj, keys, place):
    if not isinstance(obj, dict) or sorted(obj) != sorted(keys):
        raise Refused(f"{place} must be an object with exactly the spec's fields")


def _word(value, words, place):
    if value not in words or (value is not None and not isinstance(value, str)):
        raise Refused(f"{place} is not one of its words")


def _walk(obj, place):
    """One walk, checked field by field (spec section 2)."""
    _keys(obj, WALK_KEYS, place)
    if obj["v"] != FORMAT or not _int(obj["v"]):
        raise Refused(f"{place}.v is not {FORMAT}")
    _word(obj["source"], ("room", "ship"), f"{place}.source")
    for field in ("repo", "base"):
        if not _hex(obj[field]):
            raise Refused(f"{place}.{field} is not 40 or 64 lowercase hex")
    _word(obj["family"], FAMILIES, f"{place}.family")
    for field in ("item", "attempt"):
        if not isinstance(obj[field], str) or not obj[field] or not obj[field].isascii() or not obj[field].isprintable():
            raise Refused(f"{place}.{field} is not a printable ASCII id")
    _word(obj["verdict"], VERDICTS, f"{place}.verdict")
    _word(obj["standing"], STANDINGS, f"{place}.standing")
    if (obj["standing"] == "unjudged") != (obj["source"] == "ship"):
        raise Refused(f"{place}.standing is unjudged exactly when the walk is a ship's")
    if not isinstance(obj["steps"], list):
        raise Refused(f"{place}.steps is not a list")
    last = -1   # the room numbers a turn's steps from 0
    for i, step in enumerate(obj["steps"]):
        sp = f"{place}.steps[{i}]"
        _keys(step, STEP_KEYS, sp)
        if not _int(step["seq"]) or step["seq"] <= last:
            raise Refused(f"{sp}.seq is not a non-negative integer above the last")
        last = step["seq"]
        _word(step["tool"], TOOLS, f"{sp}.tool")
        if not isinstance(step["ok"], bool):
            raise Refused(f"{sp}.ok is not true or false")
        for field in ("seen_ms", "result_ms", "tokens_in", "tokens_out"):
            if step[field] is not None and (not _int(step[field]) or step[field] < 0):
                raise Refused(f"{sp}.{field} is not a non-negative integer or null")
        if not isinstance(step["named"], list):
            raise Refused(f"{sp}.named is not a list")
        for j, pair in enumerate(step["named"]):
            if not isinstance(pair, list) or len(pair) != 2:
                raise Refused(f"{sp}.named[{j}] is not a [path, blob] pair")
            if not plain_path(pair[0]):
                raise Refused(f"{sp}.named[{j}][0] is not a plain path")
            if not _hex(pair[1]):
                raise Refused(f"{sp}.named[{j}][1] is not 40 or 64 lowercase hex")
    if not isinstance(obj["changed"], list):
        raise Refused(f"{place}.changed is not a list")
    for j, pair in enumerate(obj["changed"]):
        if not isinstance(pair, list) or len(pair) != 2 or not plain_path(pair[0]) or pair[1] not in CHANGES:
            raise Refused(f"{place}.changed[{j}] is not a [plain path, change] pair")
    return obj


def read_walks(data, name):
    """A walk file's bytes, as its walks: JSON Lines, every line a walk. Refused whole at the first bad line."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(f"{name} is not UTF-8") from None
    if not text.endswith("\n"):
        raise Refused(f"{name} does not end its last line")
    walks = []
    lines = text[:-1].split("\n")
    if len(lines) > MAX_WALKS:
        raise Refused(f"{name} holds more than {MAX_WALKS} walks")
    for n, line in enumerate(lines, 1):
        if len(line.encode()) > MAX_LINE:
            raise Refused(f"{name} line {n} is longer than 1 MiB")
        try:
            obj = _json(line)
        except TooDeep:
            raise Refused(f"{name} line {n} is nested deeper than {MAX_DEPTH}") from None
        except ValueError:
            raise Refused(f"{name} line {n} is not one JSON object") from None
        walks.append(_walk(obj, f"{name} line {n}"))
    return walks


def read_list(data):
    """The room's list (its spec, section 3): its bytes, checked to be exactly the form, and its parts."""
    if len(data) > MAX_LIST:
        raise Refused("the list is longer than 4 MiB")
    try:
        obj = _json(data.decode("utf-8"))
    except TooDeep:
        raise Refused(f"the list is nested deeper than {MAX_DEPTH}") from None
    except (UnicodeDecodeError, ValueError):
        raise Refused("the list is not one JSON object in UTF-8") from None
    _keys(obj, LIST_KEYS, "the list")
    try:
        again = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    except UnicodeEncodeError:   # a lone surrogate, which no UTF-8 list can hold
        raise Refused("the list is not in its form: keys sorted, no spaces, nothing after") from None
    if again != data:
        raise Refused("the list is not in its form: keys sorted, no spaces, nothing after")
    if obj["v"] != 1 or not _int(obj["v"]) or not _hex(obj["repo"]):
        raise Refused("the list's v or repo is not the form's")
    _keys(obj["measure"], ("name", "version"), "the list's measure")
    if (obj["measure"]["name"], obj["measure"]["version"]) != SHARE or not _int(obj["measure"]["version"]):
        raise Refused("the list's measure is not one this store has")
    if not isinstance(obj["turns"], list):
        raise Refused("the list's turns is not a list")
    attempts = []
    for i, entry in enumerate(obj["turns"]):
        _keys(entry, ENTRY_KEYS, f"the list's turns[{i}]")
        if not all(isinstance(entry[k], str) for k in ("attempt", "item")) or not _hex(entry["base"]) \
                or not _hex(entry["sha256"], (64,)) or entry["standing"] not in STANDINGS[:3]:
            raise Refused(f"the list's turns[{i}] does not have the form's fields")
        attempts.append(entry["attempt"])
    if attempts != sorted(attempts) or len(set(attempts)) != len(attempts):
        raise Refused("the list's turns are not sorted by attempt, each once")
    if len({e["sha256"] for e in obj["turns"]}) != len(obj["turns"]):   # two turns with one file would be admitted as one
        raise Refused("the list names one walk file's digest for two turns")
    if len(obj["turns"]) > MAX_WALKS:
        raise Refused(f"the list names more than {MAX_WALKS} turns")
    return obj


def admit(list_bytes, files):
    """An experiment's walks: `files` maps a name to its bytes. Every listed turn's file once, and nothing else."""
    listed = read_list(list_bytes)
    by_hash = {e["sha256"]: e for e in listed["turns"]}
    given, walks = set(), []
    for name in sorted(files):
        digest = hashlib.sha256(files[name]).hexdigest()
        entry = by_hash.get(digest)
        if entry is None:
            raise Refused(f"{name} is on no entry of the list")
        if digest in given:
            raise Refused(f"{name} is a second copy of an entry")
        given.add(digest)
        found = read_walks(files[name], name)
        if len(found) != 1:
            raise Refused(f"{name} holds more than one walk")
        walk = found[0]
        if walk["source"] != "room":
            raise Refused(f"{name} is a ship's walk")
        if walk["repo"] != listed["repo"]:
            raise Refused(f"{name} is another repository's walk")
        if any(walk[k] != entry[k] for k in ("attempt", "item", "base", "standing")):
            raise Refused(f"{name} is not the turn its entry names")
        walks.append(walk)
    if len(given) != len(by_hash):
        raise Refused(f"{len(by_hash) - len(given)} listed turn(s) have no file")
    return listed, walks


def ship_walks(files):
    """A ship's store's walks: every one a ship's, of one repository, each attempt once."""
    walks = []
    for name in sorted(files):
        for walk in read_walks(files[name], name):
            if walk["source"] != "ship":
                raise Refused(f"{name} holds a room's walk; a ship's store takes ships' walks only")
            walks.append(walk)
    if len({w["repo"] for w in walks}) > 1:
        raise Refused("the walks are of more than one repository")
    if len({w["attempt"] for w in walks}) != len(walks):
        raise Refused("an attempt is given twice")
    return walks


# ------------------------------------------------------------------ the network, exactly


def visits(walk):
    """A walk's visits (spec section 4): its steps' named lists joined, a repeat of the visit just before dropped. Each is
    (path, blob, seq)."""
    out = []
    for step in walk["steps"]:
        for path, blob in step["named"]:
            if not out or out[-1][0] != path:
                out.append((path, blob, step["seq"]))
    return out


class Network:
    """What a set of walks makes under a measure: N, each road's k and witness, the paths, and every route and detour."""

    def __init__(self, walks, measure):
        self.measure = measure
        teaches = TEACHES[measure]
        self.walks = sorted(walks, key=lambda w: w["attempt"].encode())
        self.taught = [w for w in self.walks if w["standing"] in teaches]
        self.N = len(self.taught)
        self.visits = {w["attempt"]: visits(w) for w in self.walks}
        turns = defaultdict(set)
        for w in self.taught:
            path = [p for p, _, _ in self.visits[w["attempt"]]]
            for road in zip([None] + path, path):
                turns[road].add(w["attempt"])
        self.k = {road: len(t) for road, t in turns.items()}
        self.witness = {road: min(t, key=str.encode) for road, t in turns.items()}
        self.paths = sorted({p for w in self.taught for p, _, _ in self.visits[w["attempt"]]}, key=str.encode)
        self.untaught_paths = sorted({p for w in self.walks if w["standing"] not in teaches
                                      for p, _, _ in self.visits[w["attempt"]]} - set(self.paths), key=str.encode)
        self.out = defaultdict(list)
        for a, b in self.k:
            self.out[a].append(b)
        self.blobs = defaultdict(set)   # every blob a taught step named, apart from the collapsing of visits
        for w in self.taught:
            for step in w["steps"]:
                for p, blob in step["named"]:
                    self.blobs[p].add(blob)

    def roads(self):
        """Every road in the fixed order: by (from, to) bytes, the start before any path."""
        return sorted(self.k, key=lambda r: (r[0] is not None, (r[0] or "").encode(), r[1].encode()))

    def share(self, way):
        """The product of a way's road shares (a way: the paths after the start), a road walked twice counted twice."""
        product = Fraction(1)
        for road in zip([None] + list(way), way):
            product *= Fraction(self.k[road], self.N)
        return product

    def route(self, goal):
        """The cheapest simple way from the start to `goal`, ties to the first in byte order (spec section 6), or None.

        Exact: the best product of shares to every file by a search over fractions (each share is at most 1, so a way's
        product never grows); then, among the roads that keep a file at its best, the first way in byte order to the
        goal that passes no file twice, choosing at each file the first next file that can still reach the goal without
        passing a file already passed. Every such way is a least one, and every least simple way is made of such roads."""
        if self.N == 0 or goal not in self.paths:
            return None
        best = {None: Fraction(1)}
        heap = [(Fraction(-1), 0, None)]
        order = 1
        done = set()
        while heap:
            negative, _, at = heapq.heappop(heap)
            if at in done:
                continue
            done.add(at)
            for nxt in self.out[at]:
                value = -negative * Fraction(self.k[at, nxt], self.N)
                if nxt not in best or value > best[nxt]:
                    best[nxt] = value
                    heapq.heappush(heap, (-value, order, nxt))
                    order += 1
        if goal not in best:
            return None
        tight = {at: sorted((n for n in self.out[at] if at in best and best[at] * Fraction(self.k[at, n], self.N) == best[n]),
                            key=str.encode) for at in list(self.out)}

        def reaches(start, banned):
            seen, stack = {start}, [start]
            while stack:
                at = stack.pop()
                if at == goal:
                    return True
                for n in tight.get(at, ()):
                    if n not in seen and n not in banned:
                        seen.add(n)
                        stack.append(n)
            return False

        way, at, passed = [], None, set()
        while at != goal:
            for n in tight.get(at, ()):   # in byte order: the first next file that can still reach the goal
                if n not in passed and reaches(n, passed):
                    way.append(n)
                    passed.add(n)
                    at = n
                    break
            else:
                raise AssertionError("a reachable goal with no tight simple way")
        return way

    def ways(self, goal):
        """Each taught turn that visited `goal`: (walk, its way to the first visit, visit number, that step's seq)."""
        out = []
        for w in self.taught:
            path = self.visits[w["attempt"]]
            for i, (p, _, seq) in enumerate(path):
                if p == goal:
                    out.append((w, [q for q, _, _ in path[:i + 1]], i + 1, seq))
                    break
        return out

    def detours(self, goal, route):
        """(kept, more): the taught turns whose way to `goal` is dearer than `route`. The DETOURS_KEPT cheapest are kept,
        compared exactly, a tie at the edge going to the earlier attempt by bytes, and listed in attempt order; `more`
        counts the rest."""
        price = self.share(route)
        dearer = [(w, way, visit, seq) for w, way, visit, seq in self.ways(goal) if self.share(way) < price]
        cheapest = sorted(dearer, key=lambda d: (-self.share(d[1]), d[0]["attempt"].encode()))[:DETOURS_KEPT]
        kept = sorted(cheapest, key=lambda d: d[0]["attempt"].encode())
        return kept, len(dearer) - len(kept)


# ------------------------------------------------------------------ the answer's bytes


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def nats(fraction):
    """Spec section 8: a fresh context, ROUND_HALF_EVEN, nine places in fixed point, no sign on zero."""
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        x = Decimal(fraction.numerator) / Decimal(fraction.denominator)
        q = (-x.ln()).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN)
        return format(q.copy_abs() if q == 0 else q, "f")


def cost(fraction):
    return {"num": _dec(fraction.numerator), "den": _dec(fraction.denominator), "nats": nats(fraction)}


# ------------------------------------------------------------------ the file

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE listing (body BLOB NOT NULL);
CREATE TABLE walk (attempt TEXT PRIMARY KEY, item TEXT NOT NULL, family TEXT NOT NULL, base TEXT NOT NULL,
                   standing TEXT NOT NULL, taught INTEGER NOT NULL, sha256 TEXT NOT NULL, body BLOB NOT NULL);
CREATE TABLE generator (id INTEGER PRIMARY KEY, dim INTEGER NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
                        key TEXT NOT NULL);
CREATE TABLE composite (key TEXT PRIMARY KEY, dim INTEGER NOT NULL, recipe TEXT NOT NULL);
CREATE TABLE goal (path TEXT PRIMARY KEY, route TEXT, num TEXT, den TEXT, roads_n INTEGER, cell TEXT,
                   code INTEGER, reason TEXT, more INTEGER);
CREATE TABLE detour (path TEXT NOT NULL, attempt TEXT NOT NULL, visit INTEGER NOT NULL, seq INTEGER NOT NULL,
                     way TEXT NOT NULL, num TEXT NOT NULL, den TEXT NOT NULL, way_cell TEXT NOT NULL, gen INTEGER NOT NULL,
                     PRIMARY KEY (path, attempt));
"""


def _cells(net, budget_bytes):
    """Every cell, through the kernel, in the spec's fixed order (section 7). Returns what to write: generators, composites,
    goals and detours. A refusal of a 0-generator or a road raises; one of a goal's route, way or detour is that goal's."""
    cat = NCat(budget_bytes=budget_bytes)
    generators, composites, goals, detour_rows = [], {}, {}, []

    def made(kind, ref, cell):
        generators.append((len(generators) + 1, cell.dim, kind, ref, cell.key()))
        return cell

    objects = {None: made("start", "null", cat.object())}
    for p in net.paths:
        objects[p] = made("path", json.dumps(p), cat.object())
    roads = {}
    for a, b in net.roads():
        roads[a, b] = made("road", json.dumps([a, b]), cat.generator(objects[a], objects[b]))

    def composite(way):
        parts = [roads[r] for r in zip([None] + way, way)]
        cell = _compose(parts, 0)
        composites[cell.key()] = (cell.dim, json.dumps(["then", 0, [part.key() for part in parts]]))
        return cell

    for goal in net.paths:   # a goal refused part way keeps the generators the kernel made before it: replay makes them too
        route = net.route(goal)
        try:
            route_cell = composite(route)
            rows = []
            kept, more = net.detours(goal, route)   # only the kept become cells
            for w, way, visit, seq in kept:
                way_cell = composite(way)
                gen = made("detour", json.dumps([goal, w["attempt"]]), cat.generator(way_cell, route_cell))
                rows.append((goal, w["attempt"], visit, seq, json.dumps(way), net.share(way), way_cell.key(),
                             generators[-1][0], gen))
        except NCatError as error:
            goals[goal] = (route, None, error.code, ERRORS.get(error.code, f"error {error.code}"), None)
            continue
        goals[goal] = (route, route_cell.key(), None, None, more)
        detour_rows.extend(rows)
    return generators, composites, goals, detour_rows


def _write(path, net, meta, bodies, budget_bytes, list_bytes=None):
    generators, composites, goals, detours = _cells(net, budget_bytes)
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode = DELETE")
        db.executescript(SCHEMA)
        with db:
            db.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
            if list_bytes is not None:
                db.execute("INSERT INTO listing VALUES (?)", (list_bytes,))
            for w in net.walks:
                body = bodies[w["attempt"]]
                db.execute("INSERT INTO walk VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (w["attempt"], w["item"], w["family"], w["base"], w["standing"],
                            int(w["standing"] in TEACHES[net.measure]), hashlib.sha256(body).hexdigest(), body))
            db.executemany("INSERT INTO generator VALUES (?, ?, ?, ?, ?)", generators)
            db.executemany("INSERT INTO composite VALUES (?, ?, ?)", [(k, d, r) for k, (d, r) in sorted(composites.items())])
            for goal, (route, cell, code, reason, more) in goals.items():
                share = net.share(route)
                db.execute("INSERT INTO goal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (goal, json.dumps(route), _dec(share.numerator), _dec(share.denominator), len(route), cell,
                            code, reason, more))
            for goal, attempt, visit, seq, way, share, way_cell, gen_id, _ in detours:
                db.execute("INSERT INTO detour VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (goal, attempt, visit, seq, way, _dec(share.numerator), _dec(share.denominator), way_cell, gen_id))
    finally:
        db.close()
    return {"turns": len(net.walks), "taught": net.N, "paths": len(net.paths), "roads": len(net.k),
            "detours": len(detours), "detours_more": sum(v[4] or 0 for v in goals.values()),
            "refused": sorted(g for g, v in goals.items() if v[2] is not None)}


def build(out, walk_files, list_file=None, budget_bytes=BUDGET_BYTES):
    """Build the store whole and rename it into place. With `list_file`, an experiment's store under `share` 1; without,
    a ship's store under `ship-share` 1. Anything refused, or a kernel refusal of a 0-cell or a road, leaves the old file."""
    out = Path(out).resolve()
    if len(walk_files) > MAX_WALKS:
        raise Refused(f"more than {MAX_WALKS} walk files")
    for f in walk_files:
        if Path(f).stat().st_size > MAX_FILE:
            raise Refused(f"{Path(f).name} is longer than 64 MiB")
    files = {Path(f).name: Path(f).read_bytes() for f in walk_files}
    if len(files) != len(walk_files):
        raise Refused("two walk files have one name")
    list_bytes = None
    if list_file is not None:
        if Path(list_file).stat().st_size > MAX_LIST:
            raise Refused("the list is longer than 4 MiB")
        list_bytes = Path(list_file).read_bytes()
        listed, walks = admit(list_bytes, files)
        measure, repo, list_id = SHARE, listed["repo"], hashlib.sha256(list_bytes).hexdigest()
        bodies = {}
        for name, data in files.items():
            bodies[read_walks(data, name)[0]["attempt"]] = data
    else:
        walks = ship_walks(files)
        measure, list_id = SHIP_SHARE, None
        repo = walks[0]["repo"] if walks else None
        bodies = {w["attempt"]: canonical(w) for w in walks}
    if len(walks) > MAX_WALKS:
        raise Refused(f"more than {MAX_WALKS} walks")
    if sum(len(step["named"]) for w in walks for step in w["steps"]) > MAX_NAMED:
        raise Refused(f"the walks name more than {MAX_NAMED} files in all")
    net = Network(walks, measure)
    meta = {"v": str(FORMAT), "store": STORE_VERSION, "repo": json.dumps(repo), "list": json.dumps(list_id),
            "measure": json.dumps(list(measure)), "budget": str(budget_bytes),
            "for_experiment": json.dumps(list_id is not None), "kernel": _kernel_digest()}
    lock = os.open(f"{out}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(f"another build of {out} is running") from None
        temporary = out.with_name(f"{out.name}.tmp-{os.getpid()}")
        os.close(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        try:
            report = _write(temporary, net, meta, bodies, budget_bytes, list_bytes)
            _fsync(temporary)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        os.replace(temporary, out)
        _fsync(out.parent)
        return report
    finally:
        os.close(lock)


class RouteStore:
    """A finished file: answers read from it, and a check that replays every cell and recomputes every row."""

    def __init__(self, path):
        if not Path(path).is_file():
            raise IntegrityError(f"no route store at {path}; build it")
        self._db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            meta = dict(self._db.execute("SELECT key, value FROM meta"))
            listings = [body for (body,) in self._db.execute("SELECT body FROM listing")]
            if sorted(meta) != sorted(META_KEYS) or meta["v"] != str(FORMAT):
                raise ValueError("header")
            if meta["store"] != STORE_VERSION:
                raise IntegrityError(f"the route store at {path} was built by another store version; build it again")
            self.repo, self.list = json.loads(meta["repo"]), json.loads(meta["list"])
            self.measure = tuple(json.loads(meta["measure"]))
            self.for_experiment = json.loads(meta["for_experiment"])
            self.budget, self.kernel = _undec(meta["budget"]), meta["kernel"]
            self.listing = listings[0] if listings else None
            if not _hex(self.kernel, (16,)) or self.budget <= 0 or self.measure not in TEACHES \
                    or not (self.repo is None or _hex(self.repo)) or len(listings) > 1:
                raise ValueError("header")
            experiment = (self.measure == SHARE and _hex(self.list, (64,)) and self.for_experiment is True
                          and self.listing is not None and self.repo is not None)
            ship = self.measure == SHIP_SHARE and self.list is None and self.for_experiment is False and not listings
            if not (experiment or ship):
                raise ValueError("header")
        except (sqlite3.Error, KeyError, ValueError, TypeError):
            self._db.close()
            raise IntegrityError(f"the route store at {path} can't be read; build it") from None
        except IntegrityError:
            self._db.close()
            raise

    def close(self):
        self._db.close()

    def _walks(self):
        return [_walk(_json(body.decode().rstrip("\n")), f"stored walk {attempt}")
                for attempt, body in self._db.execute("SELECT attempt, body FROM walk ORDER BY attempt")]

    def ask(self, question_bytes):
        """The answer's bytes for a question (spec section 6), or Refused for a question that isn't this store's."""
        if len(question_bytes) > MAX_QUESTION:
            raise Refused("the question is longer than 1 MiB")
        try:
            q = _json(question_bytes.decode("utf-8"))
        except TooDeep:
            raise Refused(f"the question is nested deeper than {MAX_DEPTH}") from None
        except (UnicodeDecodeError, ValueError):
            raise Refused("the question is not one JSON object in UTF-8") from None
        _keys(q, QUESTION_KEYS, "the question")
        _keys(q["measure"], ("name", "version"), "the question's measure")
        if q["v"] != 1 or not _int(q["v"]) or not _int(q["measure"]["version"]) or not isinstance(q["goals"], list) \
                or not all(plain_path(g) for g in q["goals"]):
            raise Refused("the question's v or goals are not the form's")
        if q["repo"] != self.repo or q["list"] != self.list or (q["measure"]["name"], q["measure"]["version"]) != self.measure:
            raise Refused("the question's repo, list or measure is not this store's")
        net = self._network()   # N and what was named, from the stored walks themselves, which the check binds
        N, named = net.N, {p for vs in net.visits.values() for p, _, _ in vs}
        answers = [self._goal(goal, N, named) for goal in q["goals"]]
        return canonical({"v": 1, "store": STORE_VERSION, "kernel": self.kernel, "repo": self.repo, "list": self.list,
                          "for_experiment": self.for_experiment,
                          "measure": {"name": self.measure[0], "version": self.measure[1],
                                      "teaches": sorted(TEACHES[self.measure])},
                          "path_rule": PATH_RULE, "taught": N, "answers": answers})

    def _goal(self, goal, N, named):
        if N == 0:
            return {"goal": goal, "none": "no_history"}
        if goal not in named:
            return {"goal": goal, "none": "never_named"}
        row = self._db.execute("SELECT route, num, den, roads_n, cell, code, reason, more FROM goal WHERE path = ?",
                               (goal,)).fetchone()
        if row is None:
            return {"goal": goal, "none": "not_taught"}
        route, num, den, roads_n, _, code, reason, more = row
        if code is not None:
            return {"goal": goal, "none": "refused", "code": code, "reason": reason}
        route = json.loads(route)
        net = self._network()
        roads = [{"from": a, "to": b, "turns": net.k[a, b], "witness": net.witness[a, b]}
                 for a, b in zip([None] + route, route)]
        families = {w["attempt"]: w for w in net.walks}
        detours = []
        for attempt, visit, seq, way, d_num, d_den in self._db.execute(
                "SELECT attempt, visit, seq, way, num, den FROM detour WHERE path = ?", (goal,)):
            way = json.loads(way)
            detours.append({"attempt": attempt, "item": families[attempt]["item"], "family": families[attempt]["family"],
                            "visit": visit, "seq": seq, "paths": way,
                            "cost": cost(Fraction(_undec(d_num), _undec(d_den))), "roads_n": len(way)})
        detours.sort(key=lambda d: d["attempt"].encode())
        return {"goal": goal, "route": {"paths": route, "roads": roads, "cost": cost(Fraction(_undec(num), _undec(den))),
                                        "roads_n": roads_n, "blobs": {p: sorted(net.blobs[p]) for p in route},
                                        "detours": detours, "detours_more": more}}

    def _network(self):
        if not hasattr(self, "_net"):
            self._net = Network(self._walks(), self.measure)
        return self._net

    def check(self):
        """Every cell replayed through the kernel in the fixed order and compared by key; every goal's route, cost and
        refusal, and every detour's way, visit, seq and saving, recomputed from the stored walks and compared. Returns
        the number of cells checked."""
        try:
            walks = self._walks()
            rows = list(self._db.execute(
                "SELECT attempt, item, family, base, standing, taught, sha256, body FROM walk ORDER BY attempt"))
            teaches = TEACHES[self.measure]
            for (attempt, item, family, base, standing, taught, sha, body), w in zip(rows, walks):
                if hashlib.sha256(body).hexdigest() != sha or (attempt, item, family, base, standing, taught) != \
                        (w["attempt"], w["item"], w["family"], w["base"], w["standing"], int(w["standing"] in teaches)):
                    raise IntegrityError("a walk's row isn't its walk; build the store")
            if any(w["repo"] != self.repo for w in walks):
                raise IntegrityError("a walk is of another repository than the store's; build the store")
            if self.measure == SHARE:
                if hashlib.sha256(self.listing).hexdigest() != self.list:
                    raise IntegrityError("the store's list isn't the list it names; build the store")
                listed, admitted = admit(self.listing, {f"stored-{a}": body for a, *_, body in rows})
                if listed["repo"] != self.repo or sorted(w["attempt"] for w in admitted) != [r[0] for r in rows]:
                    raise IntegrityError("the store's walks aren't its list's turns; build the store")
            else:
                ship_walks({f"stored-{a}": body for a, *_, body in rows})
            net = Network(walks, self.measure)
            expected = _cells(net, self.budget)
            stored_gens = list(self._db.execute("SELECT id, dim, kind, ref, key FROM generator ORDER BY id"))
            stored_comp = {k: (d, r) for k, d, r in self._db.execute("SELECT key, dim, recipe FROM composite")}
            stored_goals = {p: (json.loads(r), c, code, reason, more) for p, r, c, code, reason, more in
                            self._db.execute("SELECT path, route, cell, code, reason, more FROM goal")}
            stored_detours = sorted(self._db.execute(
                "SELECT path, attempt, visit, seq, way, num, den, way_cell, gen FROM detour"))
            stored_goal_costs = {p: (n, d, rn) for p, n, d, rn in self._db.execute("SELECT path, num, den, roads_n FROM goal")}
        except (sqlite3.Error, ValueError, KeyError, TypeError, Refused, NCatError) as error:
            raise IntegrityError(f"the route store can't be read ({type(error).__name__}); build it") from None
        generators, composites, goals, detours = expected
        if stored_gens != generators:
            raise IntegrityError("the generators don't replay to their keys, refs or order; build the store")
        if stored_comp != composites:
            raise IntegrityError("the composites don't rebuild to their keys or recipes; build the store")
        if stored_goals != goals:
            raise IntegrityError("a goal's route, cell, refusal or count of detours left out isn't what its walks make; "
                                 "build the store")
        for goal, (route, _, _, _, _) in goals.items():
            share = net.share(route)
            if stored_goal_costs[goal] != (_dec(share.numerator), _dec(share.denominator), len(route)):
                raise IntegrityError(f"a goal's cost isn't what its walks make; build the store")
        want = sorted((g, a, v, s, w, _dec(sh.numerator), _dec(sh.denominator), wc, gid)
                      for g, a, v, s, w, sh, wc, gid, _ in detours)
        if stored_detours != want:
            raise IntegrityError("a detour's turn, goal, visit, way or saving isn't what its walks make; build the store")
        for g, a, v, s, w, num, den, _, _ in stored_detours:
            if not Fraction(_undec(num), _undec(den)) < net.share(net.route(g)):
                raise IntegrityError("a detour saves nothing; build the store")
        return len(generators) + len(composites)


@contextlib.contextmanager
def open_store(path):
    store = RouteStore(path)
    try:
        yield store
    finally:
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ncat_routes", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build", help="build a store from walk files: an experiment's with --list, a ship's without")
    b.add_argument("--out", required=True)
    b.add_argument("--list")
    b.add_argument("walks", nargs="*")
    a = commands.add_parser("ask", help="answer the question on stdin, its bytes on stdout")
    a.add_argument("--store", required=True)
    c = commands.add_parser("check", help="replay every cell and recompute every row")
    c.add_argument("--store", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            report = build(args.out, args.walks, args.list)
            print(f"{report['turns']} turns, {report['taught']} taught, {report['paths']} paths, {report['roads']} roads, "
                  f"{report['detours']} detours kept and {report['detours_more']} more counted; "
                  f"refused goals: {len(report['refused'])}")
        elif args.command == "ask":
            with open_store(args.store) as store:
                sys.stdout.buffer.write(store.ask(sys.stdin.buffer.read()))
        else:
            with open_store(args.store) as store:
                print(f"{store.check()} cells checked")
    except Refused as error:
        print(f"ncat_routes: refused: {error}", file=sys.stderr)
        return 2
    except IntegrityError as error:
        print(f"ncat_routes: {error}", file=sys.stderr)
        return 3
    except Busy as error:
        print(f"ncat_routes: {error}", file=sys.stderr)
        return 4
    except FileNotFoundError as error:
        print(f"ncat_routes: no such file: {error.filename}", file=sys.stderr)
        return 1
    except (NCatError, RuntimeError) as error:
        print(f"ncat_routes: the kernel stopped the build ({error}); the store is unchanged", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
