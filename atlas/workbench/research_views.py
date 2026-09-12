"""Linked Obsidian notes and a visual overview derived from the current local graph."""

from __future__ import annotations

from collections import Counter
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote

from .automation import _directory, _now, _read, _save
from .render import write_rendered_bundle
from .validation import EXPLICIT_QUESTION_PREDICATES, WorkbenchError


ERRORS = (ValueError, WorkbenchError, OSError, TypeError, KeyError, RecursionError)
START = re.compile(r"\A<!-- atlas-research:v1 ([0-9a-f]{64}) -->\n")
END = "\n<!-- /atlas-research:v1 -->"
QUESTION_FINDING_SECTIONS = {
    "answers": "Proposed answers", "partially_answers": "Partial answers",
    "raises_question": "Findings that raise this question", "informs": "Relevant findings",
}
FINDING_QUESTION_SECTIONS = {
    "answers": "Questions this finding answers", "partially_answers": "Questions this finding partly answers",
    "raises_question": "Questions this finding raises", "informs": "Related questions",
}


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _md(value):
    text = escape(str(value), quote=False).replace("|", "&#124;")
    return re.sub(r"([\\`*_{}\[\]#!])", r"\\\1", text)


def _name(prefix, identifier):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", identifier).strip("-_")[:64] or "record"
    return f"{prefix}-{slug}-{_hash(identifier)[:12]}.md"


def _link(path, title):
    # Unique basenames resolve both in the project vault and in Research alone.
    return f"[[{Path(path).stem}|{_md(title)}]]"


def locations(project):
    root = Path(project) / "Research"
    return {"vault": str(Path(project)), "research_folder": str(root),
            "home": str(root / "Start Here.md"), "canvas": str(root / "Atlas Map.canvas"),
            "browser": str(root / "index.html")}


def _replace(path, content, previous):
    if previous == content:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".atlas-export-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise ValueError(f"Export cannot replace a symlink: {path}")
        current = path.read_bytes().decode("utf-8") if path.exists() else None
        if current != previous:
            raise ValueError(f"File changed during export; retry refresh: {path}")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _existing(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Export requires a regular, non-symlink file: {path}")
    return path.read_bytes().decode("utf-8") if path.exists() else None


def _note(path, body):
    previous = _existing(path)
    personal = "\n\n## Personal notes\n\nWrite your own observations here. This section is preserved when Atlas refreshes.\n"
    if previous is not None:
        match = START.match(previous)
        end = previous.find(END, match.end()) if match else -1
        if not match or end < 0:
            raise ValueError(f"Existing note is not an Atlas export; kept unchanged: {path}")
        if _hash(previous[match.end():end]) != match[1]:
            raise ValueError(f"Generated text was edited; kept unchanged: {path}")
        personal = previous[end + len(END):]
    body = body.rstrip() + "\n"
    content = f"<!-- atlas-research:v1 {_hash(body)} -->\n{body}{END}{personal}"
    _replace(path, content, previous)


def _retire(path):
    previous = _existing(path)
    if previous is None:
        return
    match = START.match(previous)
    end = previous.find(END, match.end()) if match else -1
    if not match or end < 0 or _hash(previous[match.end():end]) != match[1]:
        raise ValueError(f"Retired export was edited or is unowned; kept unchanged: {path}")
    body = previous[match.end():end]
    if not body.startswith("# Archived Atlas export\n"):
        _note(path, "# Archived Atlas export\n\nThis note is no longer in the current Atlas snapshot. "
              "Its previous evidence and your personal notes are retained below.\n\n#atlas-archived #atlas/archived\n\n" + body)
    elif "#atlas/archived" not in body:
        _note(path, body.replace("#atlas-archived", "#atlas-archived #atlas/archived", 1))


def _canvas(path, value):
    previous = _existing(path)
    if previous is not None:
        old = json.loads(previous)
        if not isinstance(old, dict):
            raise ValueError(f"Canvas must be an object; kept unchanged: {path}")
        marker = old.pop("atlas_export", None)
        if marker != {"version": 1, "sha256": _hash(json.dumps(old, sort_keys=True, ensure_ascii=False))}:
            if (not isinstance(marker, dict) or set(marker) != {"version", "sha256"}
                    or marker["version"] != 1 or not isinstance(marker["sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", marker["sha256"])):
                raise ValueError(f"Canvas is not an Atlas export; kept unchanged: {path}")
            directory = path.parent / "Preserved edits"
            _directory(directory)
            copy = directory / f"Atlas Map-edited-{_hash(previous)[:16]}.canvas"
            existing = _existing(copy)
            if existing is not None and existing != previous:
                raise ValueError(f"Preserved canvas copy was changed; kept original unchanged: {copy}")
            _replace(copy, previous, existing)
            if _existing(copy) != previous:
                raise ValueError(f"Could not verify preserved canvas; kept original unchanged: {path}")
            from .automation import _sync_directory
            _sync_directory(directory)
            _sync_directory(path.parent)
    marker = {"version": 1, "sha256": _hash(json.dumps(value, sort_keys=True, ensure_ascii=False))}
    _replace(path, json.dumps(value | {"atlas_export": marker}, ensure_ascii=False, indent=2) + "\n", previous)


def _mapping(values):
    return "\n".join(f"- **{_md(key)}:** {_md(value)}" for key, value in values.items()) or "None recorded."


def _evidence(record, sources, source_paths):
    entries = []
    for evidence in record["evidence"]:
        source = sources[evidence["source_id"]]
        entries.append(f"- {_link(source_paths[source['id']], source['title'])}\n"
                       f"  - Locator: {_md(evidence['locator'])}\n  - {_md(evidence['note'])}")
    return "\n".join(entries) or "No direct source evidence recorded."


def _record_note(record, snapshot, paths, source_paths, view_paths, agenda=None, link_reviews=None):
    from .research_obsidian import KINDS
    bundle = snapshot["bundle"]
    items = {item["id"]: item for item in bundle["items"]}
    sources = {source["id"]: source for source in bundle["sources"]}
    memberships = [_link(view_paths[name], name) for name, ids in snapshot["views"].items() if record["id"] in ids]
    parts = [f"# {_md(record['title'])}", f"**{KINDS[record['kind']]} · {record['status']}**",
             f"#atlas/{record['kind']}" + (" #atlas/withdrawn" if record["status"] == "withdrawn" else ""),
             _md(record["summary"])]
    if record["kind"] == "question":
        parts.append("## Research agenda")
        if agenda is None:
            parts.append("Scheduling state is unavailable.")
        else:
            label = agenda["state"].replace("_", " ").capitalize()
            parts.extend([f"**{label}** — {_md(agenda['reason'])}",
                          f"Research attempts: {agenda['research_count']} · Overlap attempts: {agenda['overlap_count']}"])
    parts.extend(["## Scope and limitations", _mapping({key.replace("_", " ").capitalize(): value
                 for key, value in record["context"].items()
                 if key in ("scope", "limitations", "uncertainty", "assumptions", "boundary_conditions")}),
             "## Evidence", _evidence(record, sources, source_paths),
             "## Lighthouses", " · ".join(memberships) or "No configured membership.",
             "## Categories", _mapping({key: ", ".join(value) for key, value in record["facets"].items()}),
             "## Connected research"])
    details = [f"Record ID: {_md(record['id'])}", "### Full context", _mapping(record["context"]),
               "### Source identifiers", ", ".join(_md(e["source_id"]) for e in record["evidence"]) or "None."]
    if record["kind"] == "question":
        sections = ("Broader questions", "Subquestions", *QUESTION_FINDING_SECTIONS.values(), "Methods", "Experiments")
    elif record["kind"] == "claim":
        sections = tuple(FINDING_QUESTION_SECTIONS.values())
    else:
        sections = ("Related questions",)
    connections = {name: [] for name in (*sections, "Other connections")}
    for relation in bundle["relations"]:
        if record["id"] not in (relation["subject"], relation["object"]):
            continue
        outgoing = relation["subject"] == record["id"]
        neighbor = items[relation["object"] if outgoing else relation["subject"]]
        label = relation["predicate"].replace("_", " ")
        link = _link(paths[neighbor['id']], neighbor['title'])
        direction = f"This record **{label}** {link}" if outgoing else f"{link} **{label}** this record"
        connection = f"- {direction} · {relation['status']}\n  - {_md(relation['rationale'])}"
        if relation["predicate"] in EXPLICIT_QUESTION_PREDICATES:
            for key, label in (("answer_scope", "Answer scope"), ("remaining", "Remaining uncertainty")):
                if relation["context"].get(key):
                    connection += f"\n  - {label}: {_md(relation['context'][key])}"
        latest = link_reviews.get(relation["id"]) if link_reviews is not None else None
        if latest is not None:
            verdict, reason = latest["verdict"], latest["reason"]
        elif link_reviews is None:
            verdict, reason = "unavailable", "Saved link assessments could not be read."
        else:
            verdict, reason = (relation["context"].get(key) for key in ("review_verdict", "review_reason"))
        if verdict or reason:
            assessment = f"**{_md(verdict.replace('_', ' ').capitalize())}**" if verdict else "Reason recorded"
            connection += f"\n  - Link review: {assessment}" + (f" — {_md(reason)}" if reason else "")
        section = "Other connections"
        if record["kind"] == "question":
            if neighbor["kind"] == "question" and relation["predicate"] == "part_of":
                section = "Broader questions" if outgoing else "Subquestions"
            elif neighbor["kind"] == "claim" and not outgoing:
                section = QUESTION_FINDING_SECTIONS.get(relation["predicate"], "Relevant findings")
            elif neighbor["kind"] != "question":
                section = {"claim": "Relevant findings", "approach": "Methods", "experiment": "Experiments"}[neighbor["kind"]]
        elif neighbor["kind"] == "question":
            section = FINDING_QUESTION_SECTIONS.get(relation["predicate"], "Related questions") \
                if record["kind"] == "claim" and outgoing else "Related questions"
        connections[section].append(connection)
        details.extend([f"### {relation['predicate']} · {relation['status']}",
                        f"Relation ID: {_md(relation['id'])}", _mapping(relation["context"]),
                        _evidence(relation, sources, source_paths)])
        if relation["reviewed_by"]:
            details.append(f"Assessed by {_md(relation['reviewed_by'])} at {_md(relation['reviewed_at'])}.")
        if latest is not None:
            details.extend(["### Latest link assessment", _mapping({key: latest[key]
                for key in ("stage", "verdict", "reason", "model", "checked_at")})])
    for section, entries in connections.items():
        if section == "Other connections" and entries:
            parts.append("> [!info]- Other connections\n" +
                         "\n".join("> " + line for line in "\n".join(entries).splitlines()))
        elif section != "Other connections":
            parts.extend([f"### {section}", "\n".join(entries) or "None recorded."])
    parts.append("## Review")
    if record["reviewed_by"]:
        parts.append(f"Assessed by {_md(record['reviewed_by'])} at {_md(record['reviewed_at'])}.")
    else:
        parts.append("No named local review recorded. Source-reported claims and proposed interpretations retain their recorded status.")
    history = [event for event in bundle.get("history", []) if event.get("record_id") == record["id"]]
    details.extend(["### Attribution", _mapping(record["provenance"])])
    if history:
        details.extend(["### Status history", *(_mapping(event) for event in history)])
    parts.append("> [!info]- Technical details\n" + "\n".join("> " + line for line in "\n\n".join(details).splitlines()))
    return "\n\n".join(parts)


def _visual_map(snapshot, paths):
    items = {item["id"]: item for item in snapshot["bundle"]["items"] if item["status"] != "withdrawn"}
    relations = [r for r in snapshot["bundle"]["relations"] if r["status"] != "withdrawn"
                 and r["subject"] in items and r["object"] in items]
    nodes = {"intro": {"id": "intro", "type": "text", "x": 0, "y": -300, "width": 1120, "height": 200,
                        "text": "# Atlas research map\n\nLatest six connected records per question. Open [[Start Here]] for every finding and source. Click a note link for its evidence and limitations. Arrows retain the recorded relation and review status."}}

    def add(record, x, y, question=False):
        identifier = _hash(record["id"])
        nodes.setdefault(identifier, {"id": identifier, "type": "text", "x": x, "y": y,
                         "width": 460, "height": 220, "color": "5" if question else "4",
                         "text": f"## {_link(paths[record['id']], record['title'])}\n\n"
                                 f"{record['kind']} · {record['status']}\n\n{_md(record['summary'][:220])}"})

    membership = {identifier for ids in snapshot["views"].values() for identifier in ids}
    questions = sorted((item for item in items.values() if item["kind"] == "question" and item["id"] in membership),
                       key=lambda r: r["id"])
    for index, question in enumerate(questions):
        add(question, 0, index * 1500 + 500, True)
        connected = {r["object"] if r["subject"] == question["id"] else r["subject"]
                     for r in relations if question["id"] in (r["subject"], r["object"])} - {question["id"]}
        recent = sorted((items[id_] for id_ in connected),
                        key=lambda r: (r["provenance"].get("recorded_at", ""), r["id"]), reverse=True)[:6]
        for row, record in enumerate(recent):
            add(record, 650, index * 1500 + row * 250)
    edges = [{"id": _hash(r["id"]), "fromNode": _hash(r["subject"]), "toNode": _hash(r["object"]),
              "toEnd": "arrow", "label": f"{r['predicate'].replace('_', ' ')} · {r['status']}"}
             for r in relations if _hash(r["subject"]) in nodes and _hash(r["object"]) in nodes]
    return {"nodes": list(nodes.values()), "edges": edges}


def export_research(project, snapshot, generation):
    """Publish derived views while the caller holds the research inbox lock.

    View failures are reported separately from durable capture and Lighthouse publication.
    """
    project = Path(project)
    result = locations(project) | {"status": "current", "generation": generation, "errors": [],
                                   "record_count": len(snapshot["bundle"]["items"]),
                                   "source_count": len(snapshot["bundle"]["sources"])}
    root = project / "Research"

    def attempt(action, *args):
        try:
            action(*args)
        except ERRORS as error:
            result["errors"].append(str(error))

    try:
        from .research_agenda import QuestionAgenda
        from .research_graph_review import GraphReviewLedger
        from .research_obsidian import GRAPH_GUIDE, configure_graph, note_paths, repair_links
        for directory in (project / ".atlas", project / ".atlas/research", root, root / "Records", root / "Sources", root / "Lighthouses"):
            _directory(directory)
        bundle = snapshot["bundle"]
        paths, source_paths, view_paths, registry = note_paths(project, snapshot)
        agenda = {}
        try:
            agenda = QuestionAgenda(project).status(snapshot)
        except ERRORS as error:
            result["errors"].append(f"Question agenda unavailable: {error}")
        link_reviews = None
        try:
            link_reviews = GraphReviewLedger(project).current(snapshot)
        except ERRORS as error:
            result["errors"].append(f"Link assessments unavailable: {error}")
        notes = {paths[item["id"]]: _record_note(item, snapshot, paths, source_paths, view_paths,
                                              agenda.get(item["id"]), link_reviews) for item in bundle["items"]}
        for source in bundle["sources"]:
            cited_by = {item["id"] for item in bundle["items"] if any(e["source_id"] == source["id"] for e in item["evidence"])}
            for relation in bundle["relations"]:
                if any(e["source_id"] == source["id"] for e in relation["evidence"]):
                    cited_by.update([relation["subject"], relation["object"]])
            backlinks = "\n".join(f"- {_link(paths[item['id']], item['title'])} · {item['status']}"
                                  for item in bundle["items"] if item["id"] in cited_by)
            notes[source_paths[source["id"]]] = (f"# {_md(source['title'])}\n\n#atlas/source\n\n"
                f"{_md(source['citation'])}\n\nYear: {source['year']}\n\n"
                f"[Read publication](<{quote(source['url'], safe=':/?=&%#')}>)\n\n## Referenced by\n\n{backlinks}\n\n"
                f"> [!info]- Technical details\n> Source ID: {_md(source['id'])}")
        for name, ids in snapshot["views"].items():
            notes[view_paths[name]] = (f"# {_md(name)} lighthouse\n\nLocal membership; shared records link to the same note.\n\n" +
                "\n".join(f"- {_link(paths[item['id']], item['title'])} · {item['kind']} · {item['status']}"
                          for item in bundle["items"] if item["id"] in ids))
        retired = []
        owned_paths = {project / path for path in registry["paths"].values()}
        for directory in (root / "Records", root / "Sources", root / "Lighthouses"):
            for path in sorted(directory.glob("*.md")):
                if path not in notes and (path in owned_paths or re.fullmatch(r"(?:r|s|view)-[A-Za-z0-9_-]+-[0-9a-f]{12}\.md", path.name)):
                    attempt(_retire, path)
                    retired.append(path)
        attempt(_canvas, Path(result["canvas"]), _visual_map(snapshot, paths))
        attempt(repair_links, project, registry)
        preserved = root / "Preserved edits"
        result["preserved_edits"] = []
        if preserved.exists() or preserved.is_symlink():
            _directory(preserved)
            result["preserved_edits"] = [str(path) for path in sorted(preserved.glob("*.canvas"))]
        counts = Counter(item["status"] for item in bundle["items"])
        home = ["# Atlas research", f"{len(paths)} records · {len(source_paths)} sources · {len(bundle['relations'])} recorded relationships",
                "[[Atlas Map.canvas|Open the visual research map]] · [Open the searchable browser](index.html)",
                "Notes and links refresh after Atlas saves research and on `atlas-research refresh`. "
                "Open Obsidian's **Graph view** for readable, color-coded research. [[Graph Guide|Graph guide and legend]].",
                "## How to read this research", _mapping(dict(counts)),
                "Links show recorded relationships and evidence, including proposed and withdrawn accounts. "
                "They do not by themselves establish a validated mechanism. Each finding keeps its scope, sources, and assessment status.",
                "## Your notes", "Write below **Personal notes** on any exported note; Atlas preserves that section. "
                "Keep the generated section intact so it can refresh. If you edit the live canvas, Atlas preserves "
                "an exact copy under **Preserved edits** before refreshing the live map. Use that copy for your personal layout.",
                "## Lighthouses", "\n".join(f"- {_link(path, name)}" for name, path in view_paths.items())]
        if result["preserved_edits"]:
            home.extend(["## Preserved canvas edits", "Your edited maps are kept as separate, editable copies.",
                         "\n".join(f"- [[{Path(path).name}|{Path(path).stem}]]" for path in result["preserved_edits"])])
        for kind, label in (("question", "Questions"), ("claim", "Findings"), ("approach", "Approaches"), ("experiment", "Proposed experiments")):
            home.extend([f"## {label}", "\n".join(f"- {_link(paths[item['id']], item['title'])} · {item['status']}"
                for item in sorted(bundle["items"], key=lambda r: (r["provenance"].get("recorded_at", ""), r["title"]), reverse=True)
                if item["kind"] == kind) or "None recorded."])
        home.extend(["## Sources", "\n".join(f"- {_link(source_paths[s['id']], s['title'])}" for s in bundle["sources"])])
        if retired:
            home.extend(["## Retired exports", "These notes preserve earlier snapshots. They are not current research records.",
                         "\n".join(f"- {_link(path, path.stem)}" for path in retired)])
        notes[root / "Start Here.md"] = "\n\n".join(home)
        notes[root / "Graph Guide.md"] = GRAPH_GUIDE
        for path, content in notes.items():
            attempt(_note, path, content)
        attempt(configure_graph, project)
        attempt(write_rendered_bundle, bundle, Path(result["browser"]), project / ".atlas/unused.db")
    except ERRORS as error:
        result["errors"].append(str(error))
    result["status"] = "pending" if result["errors"] else "current"
    result["exported_at"] = _now()
    try:
        _directory(project / ".atlas/research")
        _save(project / ".atlas/research/views.json", result, replace=True)
    except ERRORS as error:
        result["status"] = "pending"
        result["errors"].append(str(error))
    return result


def open_view(result, *, obsidian=False):
    import webbrowser
    path = Path(result["home"] if obsidian else result["browser"])
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Research view is unavailable; inspect refresh errors: {path}")
    url = "obsidian://open?path=" + quote(str(path), safe="") if obsidian else path.as_uri()
    if not webbrowser.open(url):
        raise RuntimeError(f"Could not open the research view automatically: {path}")
    return str(path)


def export_status(project, generation):
    result = locations(project) | {"status": "not_exported"}
    path = Path(project) / ".atlas/research/views.json"
    if path.exists() or path.is_symlink():
        try:
            result = _read(path)
            if not isinstance(result, dict):
                raise ValueError("Saved research-view status must be an object")
            if result.get("generation") != generation:
                result = result | {"status": "pending"}
        except ERRORS as error:
            result = locations(project) | {"status": "pending", "errors": [str(error)]}
    return result
