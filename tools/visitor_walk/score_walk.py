"""The visitor walk's scorer (docs/superpowers/specs/2026-11-23-visitor-first-hour-design.md, approved at 344e425a).

It applies the spec's frozen checklist to one walk: the walker's stream-json transcript, the clone's README and the
documents it links, and the question project's Atlas bundle (`ResearchInbox(project).snapshot()["bundle"]`). It was
written before any walk existed, so no walk can have shaped it. It stays off main with the spec, so no walker can read
it through the docs.

Everything here is a pure function of its inputs, except `resolve_title`, which makes the frozen Crossref and PubMed
lookups and is passed in so tests can replace it.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath

FROZEN_QUESTION = "Does vitamin D supplementation prevent acute respiratory tract infections?"
BUDGET_CALLS = 150
BUDGET_SECONDS = 3600
DEFAULT_PROJECT = ".engram/atlas/project"
SPEC_MARKERS = ("visitor-walk", "visitor-first-hour", "visitor_walk", "score_walk")
SETUP = re.compile(r"\bmake\s+setup[\w-]*")
SSH = re.compile(r"(^|[\s;|&(])ssh(\s|$)|git@[\w.-]+:")
DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.I)
PMID = re.compile(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/|\bPMID:?\s*)(\d{4,9})", re.I)


def normalize(text):
    """The frozen normalization: NFKC, strip HTML tags, casefold, drop every Unicode P character, collapse spaces."""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"<[^>]+>", " ", text).casefold()
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text)
    return " ".join(text.split())


@dataclass
class Call:
    index: int                     # 1-based, in the order the walker made them
    name: str
    input: dict
    result: str = ""
    is_error: bool = False
    in_budget: bool = True


@dataclass
class Walk:
    calls: list
    texts: list                    # (number of calls made before it, text)
    over_time: bool = False
    void: bool = False
    version: str = ""
    observations: list = field(default_factory=list)


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_of(c.get("text", c.get("content", ""))) if isinstance(c, dict) else str(c) for c in content)
    return str(content or "")


def read_transcript(lines):
    """Calls and texts from stream-json lines, with each call's result joined by its tool_use id."""
    calls, texts, by_id = [], [], {}
    version, void, start, end = "", False, None, None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        stamp = event.get("timestamp")
        if stamp:
            start = start or stamp
            end = stamp
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            version = event.get("claude_code_version", "")
        if kind == "result":
            void = bool(event.get("is_error")) and event.get("subtype") != "success"
        content = (event.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if kind == "assistant" and block.get("type") == "tool_use":
                call = Call(len(calls) + 1, block.get("name", ""), block.get("input") or {})
                call.in_budget = call.index <= BUDGET_CALLS
                calls.append(call)
                by_id[block.get("id")] = call
            elif kind == "assistant" and block.get("type") == "text":
                texts.append((len(calls), block.get("text", "")))
            elif kind == "user" and block.get("type") == "tool_result":
                call = by_id.get(block.get("tool_use_id"))
                if call is not None:
                    call.result = _text_of(block.get("content"))
                    call.is_error = bool(block.get("is_error"))
    walk = Walk(calls, texts, void=void, version=version)
    walk.over_time = _seconds(start, end) > BUDGET_SECONDS
    return walk


def _seconds(start, end):
    from datetime import datetime
    if not start or not end:
        return 0
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (parse(end) - parse(start)).total_seconds()


def _command(call):
    return call.input.get("command", "") if call.name == "Bash" else ""


def flags(walk):
    """The transcript check: ssh use, attempted outside writes, and web reads of the spec, a review or a report."""
    out = {"ssh": [], "read_only": [], "spec_read": []}
    for call in walk.calls:
        if SSH.search(_command(call)):
            out["ssh"].append(call.index)
        if "Read-only file system" in call.result:
            out["read_only"].append(call.index)
        if call.name in ("WebFetch", "WebSearch"):
            target = json.dumps(call.input).casefold()
            if any(marker in target for marker in SPEC_MARKERS):
                out["spec_read"].append(call.index)
    return out


def _is_stall(call, linked):
    if call.is_error or "Read-only file system" in call.result:
        return True
    path = call.input.get("file_path", "") if call.name == "Read" else ""
    return bool(path) and linked is not None and not _linked(path, linked)


def _linked(path, linked):
    parts = PurePosixPath(path).parts
    return any(PurePosixPath(*parts[i:]).as_posix() in linked for i in range(len(parts)))


def readme_links(readme_text, read_doc):
    """The README-linked set, at any depth: relative markdown links, followed through each linked document."""
    seen, queue = {"README.md"}, [("README.md", readme_text)]
    while queue:
        here, text = queue.pop()
        base = PurePosixPath(here).parent
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            if "://" in target or target.startswith("mailto:"):
                continue
            path = (base / target).as_posix()
            parts = []
            for part in PurePosixPath(path).parts:
                if part == "..":
                    parts = parts[:-1]
                elif part != ".":
                    parts.append(part)
            path = "/".join(parts)
            if path not in seen:
                seen.add(path)
                body = read_doc(path)
                if body is not None and path.endswith(".md"):
                    queue.append((path, body))
    return seen


def _sections(readme_text):
    return [line.lstrip("#").strip() for line in readme_text.splitlines() if line.startswith("## ")]


def _doc_commands(doc_text):
    """A document's setup and demo commands: the first fenced line starting `make setup`, and the first `make …demo`."""
    lines = [l.strip() for block in re.findall(r"```[a-z]*\n(.*?)```", doc_text, re.S) for l in block.splitlines()]
    setup = next((l for l in lines if l.startswith("make setup")), None)
    demo = next((l for l in lines if re.match(r"make \S*demo\b", l)), None)
    return setup, demo


def _ran_ok(walk, command):
    return next((c.index for c in walk.calls if c.in_budget and command and command in _command(c) and not c.is_error),
                None)


def identifiers(source):
    text = f"{source.get('url', '')} {source.get('citation', '')}"
    return [("doi", d.rstrip(".,;)")) for d in DOI.findall(text)] + [("pmid", p) for p in PMID.findall(text)]


def resolve_title(kind, value):
    """The frozen lookups: a DOI through Crossref, a PMID through PubMed esummary. None when either has no record."""
    import urllib.error
    import urllib.parse
    import urllib.request
    if kind == "doi":
        url = "https://api.crossref.org/works/" + urllib.parse.quote(value.lower(), safe="/")
    else:
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={value}&retmode=json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "superyak-visitor-walk/1.0"}),
                                    timeout=30) as response:
            got = json.load(response)
    except urllib.error.HTTPError:
        return None
    if kind == "doi":
        return (got.get("message", {}).get("title") or [None])[0]
    return got.get("result", {}).get(value, {}).get("title")


def route(walk, identifier):
    """Where the identifier first appears: in a web tool's result (an outside search), in the output of a Bash call
    that runs Superyak's tools (Superyak's tools), or first in the walker's own words (memory)."""
    needle = identifier.casefold()
    events = []
    for position, text in walk.texts:
        events.append((position, 1, "memory", text))
    for call in walk.calls:
        events.append((call.index - 1, 0, "memory", json.dumps(call.input)))
        if call.name in ("WebFetch", "WebSearch"):
            events.append((call.index, 0, "outside search", call.result))
        elif call.name == "Bash" and re.search(r"\bmake\b|atlas", _command(call)):
            events.append((call.index, 0, "superyak tools", call.result))
    for _, _, where, text in sorted(events, key=lambda e: (e[0], e[1])):
        if needle in text.casefold():
            return where
    return "memory"


def score(walk, readme_text, read_doc, bundle, project_path, resolver=resolve_title, view_files=None):
    """The checklist, step by step. Returns the report's scoring part."""
    linked = readme_links(readme_text, read_doc)
    steps, named_doc = {}, None
    first_setup = next((c.index for c in walk.calls if SETUP.search(_command(c))), len(walk.calls) + 1)
    for position, text in walk.texts:
        if position >= first_setup:
            break
        low = normalize(text)
        section = next((s for s in _sections(readme_text) if normalize(s) and normalize(s) in low), None)
        doc = next((d for d in sorted(linked) if d != "README.md" and d.endswith(".md") and d in text), None)
        if section and doc:
            named_doc = doc
            steps["S1"] = position
            break
    setup, demo = _doc_commands(read_doc(named_doc) or "") if named_doc else (None, None)
    steps["S2"] = _ran_ok(walk, setup)
    steps["S3"] = _ran_ok(walk, demo)
    items = {i["id"]: i for i in bundle.get("items", [])}
    sources = {s["id"]: s for s in bundle.get("sources", [])}
    question = next((i for i in items.values() if i.get("kind") == "question"
                     and normalize(i.get("title", "")) == normalize(FROZEN_QUESTION)), None)
    if question and not str(project_path).rstrip("/").endswith(DEFAULT_PROJECT):
        steps["S4"] = True
    claim, verified, ident = None, None, None
    if question:
        for relation in bundle.get("relations", []):
            if relation.get("predicate") == "informs" and relation.get("object") == question["id"]:
                candidate = items.get(relation.get("subject"))
                if not candidate or candidate.get("kind") != "claim":
                    continue
                for evidence in candidate.get("evidence", []):
                    source = sources.get(evidence.get("source_id"))
                    for kind, value in identifiers(source or {}):
                        title = resolver(kind, value)
                        if title and normalize(title) == normalize(source.get("title", "")):
                            claim, verified, ident = candidate, source, value
                            break
                    if claim:
                        break
            if claim:
                break
    if claim:
        steps["S5"] = True
        seen = next((c.index for c in walk.calls if c.in_budget and claim["id"] in c.result
                     and ident.casefold() in c.result.casefold()), None)
        confirmed = view_files is None or any(claim["id"] in t and ident.casefold() in t.casefold() for t in view_files)
        steps["S6"] = seen if seen and confirmed else None
    order = ["S1", "S2", "S3", "S4", "S5", "S6"]
    stalls = [c for c in walk.calls if c.in_budget and _is_stall(c, linked)]
    done_at = {"S1": steps.get("S1"), "S2": steps.get("S2"), "S3": steps.get("S3"), "S6": steps.get("S6")}
    scored = {}
    previous = 0
    for name in order:
        value = steps.get(name)
        done = value is not None and value is not False         # S1 can be done at position 0, and 0 == False
        at = done_at.get(name) if isinstance(done_at.get(name), int) else None
        mine = [c.index for c in stalls if c.index > previous and (at is None or c.index <= at)] if done else []
        scored[name] = "not done" if not done else ("stalled then unaided" if mine else "unaided")
        if at is not None:
            previous = at
    found = flags(walk)
    return {"steps": scored, "named_doc": named_doc, "stalls": [c.index for c in stalls],
            "source": ({"id": verified["id"], "identifier": ident, "route": route(walk, ident)} if claim else None),
            "flags": found, "eligible_to_stop": not found["spec_read"],
            "budget": {"calls": len(walk.calls), "over_calls": max(0, len(walk.calls) - BUDGET_CALLS),
                       "over_time": walk.over_time},
            "void": walk.void, "claude_version": walk.version}
