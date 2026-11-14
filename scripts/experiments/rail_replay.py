"""Replay: does "where you stand now" predict the next file better than the task does?

Reads Claude Code session transcripts for one repository and cuts each into turns: what the agent
touched between one prompt (a person's, or a timer's) and the next. A turn's walk is the ordered
list of repo files it read, edited, or named in a shell command. Roads are laid from the earlier
turns. Then, at every step of each later turn, seven predictors guess which file the turn opens
next that it has not opened yet, and each is scored by whether the true file is in its top k. A
looser score counts any file the turn goes on to open.

It prints counts and rates only. It never prints a prompt, a path or any file content.

Usage: python3 -I rail_replay.py <projects dir> [--drop-repeated] [--test-share 0.3] -- <folder prefix>
(the folder prefix starts with a dash, so it goes after "--")
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}
REPO_PREFIX = re.compile(
    r"^(?:/Users/[^/]+/Projects|/home/[^/]+)/superyak[^/]*/(?:\.worktrees/[^/]+/)?"
)
WORD = re.compile(r"[a-z][a-z0-9_]{2,}")
KS = (1, 5, 10)
# Most reading in these sessions is done in the shell (sed, grep, git show, pytest), not with the
# file tools, so a walk also takes the repo files a shell command names.
TOP = ("engram", "peer", "docs", "scripts", "agent", "lighthouse", "atlas", "team", "deploy", "tests",
       "tuning", "research_poc", "research_tasks")
IN_COMMAND = re.compile(
    r"(?<![\w./-])((?:" + "|".join(TOP) + r")/[\w./-]+\.(?:py|md|js|ts|json|toml|sh|c|h|cpp|html|css|ya?ml|txt|service|sql)"
    r"|Makefile|README\.md|CLAUDE\.md|HANDOFF\.md)(?![\w/-])"
)


def files_in_command(command: str) -> list[str]:
    out = []
    for m in IN_COMMAND.finditer(command):
        rel = m.group(1)
        if "/.venv/" not in rel and "node_modules/" not in rel:
            out.append(rel)
    return out


def repo_relative(path: str) -> str | None:
    """A repo-relative path, or None for a file outside the repository."""
    m = REPO_PREFIX.match(path)
    if not m:
        return None
    rel = path[m.end():]
    if not rel or rel.startswith((".git/", ".venv/", "node_modules/")) or "/.venv/" in rel:
        return None
    return rel


def read_session(path: str):
    """The turns of one transcript: (time, prompt words, walk) for each stretch between two prompts.

    A ship's session runs for days and holds many tasks, so the unit of a walk is the turn: what
    the agent touched between one prompt (a person's, or a timer's) and the next.
    """
    turns = []
    when = None
    words: list[str] = []
    walk: list[str] = []

    def close():
        if when and walk:
            turns.append((when, words, walk))

    with open(path, "rb") as f:
        for raw in f:
            is_user = b'"type":"user"' in raw
            if b'"tool_use"' not in raw and not is_user:
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            content = (row.get("message") or {}).get("content")
            if row.get("type") == "user":
                if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                ):
                    continue
                text = content if isinstance(content, str) else " ".join(
                    b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"
                )
                if not text or text.lstrip().startswith(("<local-command", "<command-name")):
                    continue
                close()
                when = row.get("timestamp") if isinstance(row.get("timestamp"), str) else when
                words, walk = WORD.findall(text.lower()[:4000]), []
            elif row.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    inp = b.get("input") or {}
                    found: list[str] = []
                    if b.get("name") in FILE_TOOLS or b.get("name") == "Grep":
                        fp = inp.get("file_path") or inp.get("path")
                        rel = repo_relative(fp) if isinstance(fp, str) else None
                        if rel and "." in os.path.basename(rel):
                            found.append(rel)
                    elif b.get("name") == "Bash" and isinstance(inp.get("command"), str):
                        found = files_in_command(inp["command"])
                    for rel in found:
                        if not walk or walk[-1] != rel:
                            walk.append(rel)
    close()
    return turns


def top(scores: dict, seen: set, k: int) -> list[str]:
    return [f for f, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])) if f not in seen][:k]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("projects")
    ap.add_argument("prefix")
    ap.add_argument("--test-share", type=float, default=0.3)
    ap.add_argument("--min-files", type=int, default=3)
    ap.add_argument("--drop-repeated", action="store_true",
                    help="leave out turns whose prompt opens with words seen in 3 or more turns (timer ticks)")
    args = ap.parse_args(argv)

    sessions = []
    paths = sorted(glob.glob(os.path.join(args.projects, args.prefix + "*", "*.jsonl")))
    n_turns = 0
    for p in paths:
        for when, words, walk in read_session(p):
            n_turns += 1
            if len(set(walk)) >= args.min_files:
                sessions.append((when, words, walk))
    if args.drop_repeated:
        sig = Counter(tuple(w[:25]) for _, w, _ in sessions)
        before = len(sessions)
        sessions = [t for t in sessions if sig[tuple(t[1][:25])] < 3]
        print(f"dropped {before - len(sessions)} turns with a repeated prompt")
    sessions.sort(key=lambda s: s[0])
    n = len(sessions)
    cut = int(n * (1 - args.test_share))
    history, test = sessions[:cut], sessions[cut:]
    print(f"transcripts read: {len(paths)}; turns that touched a repo file: {n_turns}; turns with >= {args.min_files} repo files: {n}")
    print(f"history: {len(history)} turns ({history[0][0][:10]} to {history[-1][0][:10]}); "
          f"test: {len(test)} turns ({test[0][0][:10]} to {test[-1][0][:10]})")

    # Roads and the other tables, from history only.
    popularity: Counter = Counter()
    follows: dict = defaultdict(Counter)       # a -> next new file after a (ordered, adjacent)
    later: dict = defaultdict(Counter)         # a -> any file first opened later in the session
    together: dict = defaultdict(Counter)      # a -> any file in the same session (unordered)
    by_dir: dict = defaultdict(Counter)
    doc_freq: Counter = Counter()
    hist_vecs = []
    for _, words, walk in history:
        firsts = list(dict.fromkeys(walk))     # order of first opening
        for f in firsts:
            popularity[f] += 1
            by_dir[os.path.dirname(f)][f] += 1
        for i, a in enumerate(firsts):
            if i + 1 < len(firsts):
                follows[a][firsts[i + 1]] += 1
            for b in firsts[i + 1:]:
                later[a][b] += 1
            for b in firsts:
                if b != a:
                    together[a][b] += 1
        doc_freq.update(set(words))
        hist_vecs.append((Counter(words), Counter(firsts)))
    n_hist = len(history)

    def tfidf(c: Counter) -> dict:
        v = {w: tf * math.log((1 + n_hist) / (1 + doc_freq[w])) for w, tf in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}

    hist_tfidf = [(tfidf(c), files) for c, files in hist_vecs]

    names = ["popularity", "same folder", "task (similar first prompt)", "together (unordered)",
             "road: next after here", "road: anything later from here", "road + task"]
    hits = {name: Counter() for name in names}
    rr = Counter()
    any_hits = {name: Counter() for name in names}
    any_cap = 0
    points = 0
    known_target = 0

    for _, words, walk in test:
        firsts = list(dict.fromkeys(walk))
        q = tfidf(Counter(words))
        sims = sorted(((sum(q.get(w, 0.0) * x for w, x in v.items()), files) for v, files in hist_tfidf),
                      key=lambda t: -t[0])[:10]
        task_scores: Counter = Counter()
        for s, files in sims:
            if s > 0:
                for f in files:
                    task_scores[f] += s
        for i in range(len(firsts) - 1):
            here, target = firsts[i], firsts[i + 1]
            seen = set(firsts[: i + 1])
            points += 1
            known_target += target in popularity
            future = set(firsts[i + 1:])
            any_cap += any(f in popularity for f in future)
            recent = firsts[max(0, i - 2): i + 1][::-1]          # here, then the two before it
            road_next: Counter = Counter()
            road_later: Counter = Counter()
            tog: Counter = Counter()
            for depth, a in enumerate(recent):
                w = 0.5 ** depth
                for b, c in follows[a].items():
                    road_next[b] += w * c
                for b, c in later[a].items():
                    road_later[b] += w * c
                for b, c in together[a].items():
                    tog[b] += w * c
            both: Counter = Counter()
            mx_r = max(road_later.values(), default=0) or 1
            mx_t = max(task_scores.values(), default=0) or 1
            for f in set(road_later) | set(task_scores):
                both[f] = road_later.get(f, 0) / mx_r + task_scores.get(f, 0) / mx_t
            scored = {
                "popularity": popularity,
                "same folder": by_dir[os.path.dirname(here)],
                "task (similar first prompt)": task_scores,
                "together (unordered)": tog,
                "road: next after here": road_next,
                "road: anything later from here": road_later,
                "road + task": both,
            }
            for name, scores in scored.items():
                ranked = top(scores, seen, max(KS))
                for k in KS:
                    hits[name][k] += target in ranked[:k]
                    any_hits[name][k] += bool(future & set(ranked[:k]))
                if target in ranked:
                    rr[name] += 1.0 / (ranked.index(target) + 1)

    print(f"prediction points: {points}; target file ever seen in history: {known_target} "
          f"({100 * known_target / max(points, 1):.1f}%), which caps every predictor")
    print(f"{'predictor':34} {'hit@1':>7} {'hit@5':>7} {'hit@10':>7} {'MRR@10':>7}")
    for name in names:
        row = " ".join(f"{100 * hits[name][k] / max(points, 1):6.1f}%" for k in KS)
        print(f"{name:34} {row} {rr[name] / max(points, 1):7.3f}")
    print(f"\nA looser target: any file the turn goes on to open. Reachable at {100 * any_cap / max(points, 1):.1f}% of points.")
    print(f"{'predictor':34} {'any@1':>7} {'any@5':>7} {'any@10':>7}")
    for name in names:
        row = " ".join(f"{100 * any_hits[name][k] / max(points, 1):6.1f}%" for k in KS)
        print(f"{name:34} {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
