"""Stable human note names, recoverable link migration, and native graph defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote, unquote

from .automation import _directory, _read, _save, _sync_directory


KINDS = {"question": "Question", "claim": "Finding", "approach": "Method", "experiment": "Experiment"}
FOLDERS = {"r": "Records", "s": "Sources", "view": "Lighthouses"}


def _files(project):
    # Obsidian ignores hidden directories. Never follow a vault symlink.
    for directory, folders, files in os.walk(project, followlinks=False):
        folders[:] = [name for name in folders if not name.startswith(".")
                      and not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.suffix in (".md", ".canvas") and not path.is_symlink():
                yield path


def _stem(label, title):
    title = unicodedata.normalize("NFC", title)
    title = re.sub(r'[\\/:*?"<>|#\[\]^\x00-\x1f\x7f]', " ", title)
    title = " ".join(title.split()).strip(" .") or "Untitled"
    stem = f"{label} - {title}"
    if len(stem.encode("utf-8")) > 150:
        stem = stem.encode("utf-8")[:150].decode("utf-8", errors="ignore")
        stem = stem.rsplit(" ", 1)[0] if " " in stem[len(label) + 3:] else stem
    return stem.rstrip(" .")


def _valid_path(value):
    path = Path(value)
    if (len(path.parts) != 3 or path.parts[0] != "Research" or path.parts[1] not in FOLDERS.values()
            or path.suffix != ".md" or path.name.startswith(".")):
        raise ValueError("Invalid saved Obsidian note path")
    return path


def _backup(project, path, content):
    from .research_views import _existing, _hash, _replace
    root = project / ".atlas/research/obsidian-backups"
    relative = path.relative_to(project)
    directory = root / _hash(content)
    for parent in [root, directory, *[directory.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts))]]:
        _directory(parent)
    destination = directory / relative
    old = _existing(destination)
    if old is not None and old != content:
        raise ValueError(f"Obsidian backup was changed: {destination}")
    _replace(destination, content, old)
    if _existing(destination) != content:
        raise ValueError(f"Could not verify Obsidian backup: {destination}")
    for parent in [destination.parent, *destination.parent.parents]:
        _sync_directory(parent)
        if parent == root:
            break


def note_paths(project, snapshot):
    """Persist allocations before moving notes, so interruption can be retried."""
    from .research_views import START, END, _existing, _hash, _name
    registry_path = project / ".atlas/research/note-paths.json"
    registry = _read(registry_path) if registry_path.exists() else {"version": 1, "paths": {}, "moves": {}, "pending": False}
    if (not isinstance(registry, dict) or registry.get("version") != 1
            or not isinstance(registry.get("paths"), dict) or not isinstance(registry.get("moves"), dict)):
        raise ValueError("Invalid Obsidian note registry; kept existing notes unchanged")
    for value in [*registry["paths"].values(), *registry["moves"].keys(), *registry["moves"].values()]:
        _valid_path(value)
    paths = registry["paths"]
    reserved = {unicodedata.normalize("NFC", path.stem).casefold() for path in _files(project)}
    reserved.update(Path(value).stem.casefold() for value in paths.values())
    entries = [("r", item["id"], KINDS[item["kind"]], item["title"]) for item in snapshot["bundle"]["items"]]
    entries += [("s", item["id"], "Source", item["title"]) for item in snapshot["bundle"]["sources"]]
    entries += [("view", name, "Collection", name.capitalize()) for name in snapshot["views"]]
    for prefix, identifier, label, title in sorted(entries):
        key = f"{prefix}:{identifier}"
        if key in paths:
            continue
        stem = _stem(label, title)
        candidate, number = stem, 1
        while candidate.casefold() in reserved:
            number += 1
            candidate = f"{stem} ({number})"
        reserved.add(candidate.casefold())
        relative = Path("Research") / FOLDERS[prefix] / (candidate + ".md")
        paths[key] = str(relative)
        legacy = relative.parent / _name(prefix, identifier)
        if (project / legacy).exists() or (project / legacy).is_symlink():
            registry["moves"][str(legacy)] = str(relative)
            registry["pending"] = True
    _save(registry_path, registry, replace=True)
    moves = []
    for old, new in registry["moves"].items():
        source, destination = project / old, project / new
        previous = _existing(source)
        if previous is None:
            continue
        match = START.match(previous)
        end = previous.find(END, match.end()) if match else -1
        if not match or end < 0 or _hash(previous[match.end():end]) != match[1]:
            raise ValueError(f"Legacy generated note was edited or is unowned; kept unchanged: {source}")
        existing = _existing(destination)
        if existing is not None and existing != previous:
            raise ValueError(f"Both legacy and readable notes exist with different content: {source}")
        moves.append((source, destination, previous, existing))
    # A conflict or backup failure must not strand an earlier note's links.
    for source, _, previous, _ in moves:
        _backup(project, source, previous)
    for source, destination, previous, existing in moves:
        if existing is None:
            # Hard-link creation cannot overwrite an existing destination.
            os.link(source, destination)
            _sync_directory(destination.parent)
        if _existing(source) != previous:
            raise ValueError(f"Note changed during migration; retry: {source}")
        source.unlink()
        _sync_directory(source.parent)
    grouped = [{identifier: project / paths[f"{prefix}:{identifier}"]
                for p, identifier, _, _ in entries if p == prefix} for prefix in FOLDERS]
    return (*grouped, registry)


def repair_links(project, registry):
    """Repair link destinations, preserving prose and backing up each changed file."""
    if not registry.get("pending"):
        return
    from .research_views import START, END, _existing, _hash, _replace
    replacements = {}
    for old, new in registry["moves"].items():
        for left, right in ((old, new), (old.removeprefix("Research/"), new.removeprefix("Research/")),
                            (Path(old).name, Path(new).name)):
            replacements[left] = right
            replacements[left[:-3]] = right[:-3]

    def destination(value, path):
        target, marker, fragment = value.partition("#")
        decoded = unquote(target)
        changed = replacements.get(decoded)
        if changed is None and not re.match(r"[a-zA-Z][\w+.-]*:", decoded):
            absolute = Path(os.path.normpath(path.parent / decoded))
            if absolute.is_relative_to(project):
                relative = str(absolute.relative_to(project))
                mapped = registry["moves"].get(relative)
                if mapped is not None:
                    changed = os.path.relpath(project / mapped, path.parent)
        return changed + marker + fragment if changed is not None else value

    def prose(text, path):
        text = re.sub(r"\[\[([^\]|]+)(\|[^\]]*)?\]\]",
                      lambda m: "[[" + destination(m[1], path) + (m[2] or "") + "]]", text)
        def md_link(match):
            old = match[2].strip("<>")
            new = destination(old, path)
            return match[0] if old == new else match[1] + quote(new, safe="/#") + match[3]
        text = re.sub(r'''(\[[^\]\n]*\]\()(<[^>\n]+>|[^)\s]+)((?:[ \t]+(?:"[^"\n]*"|'[^'\n]*'|\([^\n)]*\)))?[ \t]*\))''', md_link, text)
        return re.sub(r"(?m)^( {0,3}\[[^\]\n]+\]:[ \t]*)(<[^>\n]+>|[^\s]+)([^\n]*)$", md_link, text)

    def markdown(text, path):
        # A literal link in an example is not an Obsidian link destination.
        protected = re.compile(r"(?m)^ {0,3}(?:>[ \t]*)*(`{3,}|~{3,})[^\n]*\n[\s\S]*?^ {0,3}(?:>[ \t]*)*\1[ \t]*(?:\n|$)|(`+)[\s\S]*?\2")
        parts, start = [], 0
        for match in protected.finditer(text):
            parts.extend((prose(text[start:match.start()], path), match[0]))
            start = match.end()
        parts.append(prose(text[start:], path))
        return "".join(parts)

    def json_links(value, path):
        if isinstance(value, dict):
            return {key: (replacements.get(entry, entry) if key in ("file", "title") and isinstance(entry, str)
                          else markdown(entry, path) if key == "text" and isinstance(entry, str)
                          else json_links(entry, path)) for key, entry in value.items()}
        if isinstance(value, list):
            return [json_links(entry, path) for entry in value]
        # Workspace lastOpenFiles is a list of paths.
        return replacements.get(value, value) if isinstance(value, str) else value

    candidates = list(_files(project))
    config = project / ".obsidian"
    if config.is_dir() and not config.is_symlink():
        candidates += [config / name for name in ("workspace.json", "bookmarks.json")]
    for path in candidates:
        if path == project / "Research/Atlas Map.canvas":
            continue  # The canvas exporter preserves edited maps byte-for-byte.
        previous = _existing(path)
        if previous is None:
            continue
        if path.suffix in (".json", ".canvas"):
            data = json.loads(previous)
            updated = json_links(data, path)
            content = previous if updated == data else json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
        else:
            match = START.match(previous)
            end = previous.find(END, match.end()) if match else -1
            if match and end >= 0:
                body = previous[match.end():end]
                if _hash(body) != match[1]:
                    continue
                body = markdown(body, path)
                content = f"<!-- atlas-research:v1 {_hash(body)} -->\n{body}{END}" + markdown(previous[end + len(END):], path)
            else:
                content = markdown(previous, path)
        if content != previous:
            if (project / "Research/Preserved edits") in path.parents and path.suffix == ".canvas":
                # Retain the exact historical copy and provide a usable linked layout.
                number = 1
                while True:
                    suffix = f" ({number})" if number > 1 else ""
                    companion = path.parent / f"Your research map{suffix}.canvas"
                    existing = _existing(companion)
                    if existing is None or existing == content:
                        _replace(companion, content, existing)
                        _sync_directory(companion.parent)
                        break
                    number += 1
            else:
                _backup(project, path, previous)
                _replace(path, content, previous)
                _sync_directory(path.parent)
    registry["pending"] = False
    _save(project / ".atlas/research/note-paths.json", registry, replace=True)


def configure_graph(project):
    """Set up this vault once; subsequent exports respect human customization."""
    from .research_views import _existing, _replace
    marker = project / ".atlas/research/obsidian-graph.json"
    if marker.exists():
        return
    directory = project / ".obsidian"
    _directory(directory)
    path = directory / "graph.json"
    previous = _existing(path)
    graph = json.loads(previous) if previous else {}
    if not isinstance(graph, dict):
        raise ValueError("Obsidian graph settings must be an object")
    if previous is not None:
        _backup(project, path, previous)
    graph.update({"search": 'path:"Research/Records" -tag:#atlas/archived -tag:#atlas/withdrawn',
                  "showTags": False, "showAttachments": False, "hideUnresolved": True,
                  "showOrphans": True, "showArrow": False, "textFadeMultiplier": 0,
                  "collapse-filter": False, "collapse-color-groups": False,
                  "colorGroups": [{"query": f"tag:#atlas/{kind}", "color": {"a": 1, "rgb": color}}
                                  for kind, color in (("question", 0xE5AD46), ("claim", 0x639EF5),
                                                      ("approach", 0x51BFA4), ("experiment", 0xBB8FE8))]})
    _replace(path, json.dumps(graph, indent=2) + "\n", previous)
    _sync_directory(path.parent)
    _save(marker, {"version": 1}, replace=True)


GRAPH_GUIDE = """# Explore the research graph

Open **Graph view** from the ribbon or command palette. Zoom in to read titles; select a node to open its evidence.

| Color | Record |
| --- | --- |
| Gold | Question |
| Blue | Finding |
| Green | Method |
| Purple | Proposed experiment |

The default filter shows research records. Source papers and collection indexes stay accessible from each note.
Isolated findings remain visible, so you can see where connections are still missing.

## Choose your view

- Research: `path:"Research/Records" -tag:#atlas/archived -tag:#atlas/withdrawn`
- Include papers: `(path:"Research/Records" OR path:"Research/Sources") -tag:#atlas/archived -tag:#atlas/withdrawn`
- Questions: `tag:#atlas/question`
- Your neighborhood: open a research note, then use **Open local graph** from the command palette. Increase depth to explore further.

The filter and colors are configured once. Your later graph settings are preserved across Atlas refreshes.
If you open the Research folder as its own vault, use `path:Records` instead of `path:"Research/Records"`.

## Read a connection

A native graph line means the notes are linked. Open **Connected research** for the relationship, direction, rationale, and review status.
Links and colors do not indicate scientific validation. Technical IDs and provenance are available in each note's collapsed **Technical details** callout.
For labeled arrows, open [[Atlas Map.canvas|Atlas Map]].

## Keep your observations

Write under **Personal notes**. Atlas retains that section when it refreshes.
Readable filenames stay stable, including when two records share a title. Internal record IDs stay in the evidence store.
Migration backups live outside the graph in `.atlas/research/obsidian-backups`.
Previously edited canvases keep an exact original copy. A **Your research map** companion copy preserves the layout with updated links.

See [Obsidian Graph view](https://obsidian.md/help/plugins/graph) for graph controls and [Search](https://obsidian.md/help/plugins/search) for filters.
"""
