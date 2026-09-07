"""Tree-sitter code indexer with incremental git diff updates."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("engram.indexer")

import tree_sitter_javascript as tsjavascript
import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser, Query, QueryCursor

# --- Language setup ---

PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjavascript.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())

LANGUAGE_MAP: dict[str, Language] = {
    "python": PY_LANGUAGE,
    "javascript": JS_LANGUAGE,
    "typescript": TS_LANGUAGE,
}

EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# --- Symbol extraction queries ---

_PY_QUERIES = {
    "function": "(function_definition name: (identifier) @name) @def",
    "class": "(class_definition name: (identifier) @name) @def",
    "method": "(class_definition body: (block (function_definition name: (identifier) @name) @def))",
    "import": "[(import_statement) @import (import_from_statement) @import]",
}

_JS_QUERIES = {
    "function": "(function_declaration name: (identifier) @name) @def",
    "class": "(class_declaration name: (identifier) @name) @def",
    "method": "(method_definition name: (property_identifier) @name) @def",
    "arrow": "(variable_declarator name: (identifier) @name value: (arrow_function) @def)",
    "import": "(import_declaration) @import",
}

QUERIES: dict[str, dict[str, str]] = {
    "python": _PY_QUERIES,
    "javascript": _JS_QUERIES,
    "typescript": _JS_QUERIES,  # TS uses same node types as JS for these
}


def _node_text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _body_preview(node, source_bytes: bytes, max_len: int = 300) -> str:
    text = _node_text(node, source_bytes)
    return text[:max_len]


# --- Public API ---


def get_changed_files(project_root: Path, last_commit: str | None) -> list[Path] | None:
    """Get files changed since last_commit via git diff. Returns None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
    except FileNotFoundError:
        return None

    if last_commit is None:
        return None  # No baseline — caller should do full reindex

    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACDMR", last_commit, "HEAD"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    files = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line:
            files.append(project_root / line)
    return files


def _run_query(lang: Language, query_str: str, root_node) -> list[tuple[int, dict]]:
    """Run a tree-sitter query and return matches as (pattern_index, captures) tuples."""
    q = Query(lang, query_str)
    cursor = QueryCursor(q)
    return list(cursor.matches(root_node))


def _first(nodes):
    """Extract single node from a capture (which is always a list in v0.25)."""
    if isinstance(nodes, list):
        return nodes[0]
    return nodes


def parse_file(file_path: Path, language: str) -> list[dict]:
    """Parse a source file, return list of symbol dicts."""
    if language not in LANGUAGE_MAP:
        return []

    lang = LANGUAGE_MAP[language]
    parser = Parser(lang)
    source = file_path.read_bytes()
    tree = parser.parse(source)

    queries = QUERIES.get(language, {})
    symbols: list[dict] = []
    seen_methods: set[int] = set()

    # Extract methods first so we can exclude them from function results
    if "method" in queries:
        for _, captures in _run_query(lang, queries["method"], tree.root_node):
            name_node = _first(captures.get("name"))
            def_node = _first(captures.get("def"))
            if name_node:
                name = _node_text(name_node, source)
                seen_methods.add(name_node.id)
                symbols.append({
                    "name": name,
                    "kind": "method",
                    "line": name_node.start_point.row + 1,
                    "body_preview": _body_preview(def_node or name_node, source),
                })

    # Extract functions (excluding methods already found)
    if "function" in queries:
        for _, captures in _run_query(lang, queries["function"], tree.root_node):
            name_node = _first(captures.get("name"))
            def_node = _first(captures.get("def"))
            if name_node:
                if name_node.id in seen_methods:
                    continue
                name = _node_text(name_node, source)
                symbols.append({
                    "name": name,
                    "kind": "function",
                    "line": name_node.start_point.row + 1,
                    "body_preview": _body_preview(def_node or name_node, source),
                })

    # Extract classes
    if "class" in queries:
        for _, captures in _run_query(lang, queries["class"], tree.root_node):
            name_node = _first(captures.get("name"))
            def_node = _first(captures.get("def"))
            if name_node:
                name = _node_text(name_node, source)
                symbols.append({
                    "name": name,
                    "kind": "class",
                    "line": name_node.start_point.row + 1,
                    "body_preview": _body_preview(def_node or name_node, source),
                })

    # Extract arrow functions (JS/TS)
    if "arrow" in queries:
        for _, captures in _run_query(lang, queries["arrow"], tree.root_node):
            name_node = _first(captures.get("name"))
            def_node = _first(captures.get("def"))
            if name_node:
                name = _node_text(name_node, source)
                symbols.append({
                    "name": name,
                    "kind": "function",
                    "line": name_node.start_point.row + 1,
                    "body_preview": _body_preview(def_node or name_node, source),
                })

    return symbols


def extract_edges(file_path: Path, symbols: list[dict], language: str) -> list[dict]:
    """Extract structural edges (imports) from parsed file."""
    if language not in LANGUAGE_MAP:
        return []

    lang = LANGUAGE_MAP[language]
    parser = Parser(lang)
    source = file_path.read_bytes()
    tree = parser.parse(source)

    queries = QUERIES.get(language, {})
    edges: list[dict] = []

    if "import" not in queries:
        return edges

    for _, captures in _run_query(lang, queries["import"], tree.root_node):
        imp_node = _first(captures.get("import"))
        if imp_node:
            text = _node_text(imp_node, source)
            target = _import_target(text, language)
            if target:
                edges.append({
                    "kind": "imports",
                    "source": str(file_path),
                    "target": target,
                    "text": text.strip(),
                })

    return edges


def _import_target(text: str, language: str) -> str | None:
    """Extract the module/package name from an import statement text."""
    text = text.strip()
    if language == "python":
        # "from X import Y" -> X
        if text.startswith("from "):
            parts = text.split()
            if len(parts) >= 2:
                return parts[1]
        # "import X" -> X
        elif text.startswith("import "):
            parts = text.split()
            if len(parts) >= 2:
                return parts[1].rstrip(",")
    elif language in ("javascript", "typescript"):
        # "import ... from 'X'" -> X
        if "from" in text:
            # Find the string after from
            idx = text.rfind("from")
            rest = text[idx + 4:].strip().strip("'\";")
            return rest
    return None


def _entity_id(relative_path: str, symbol_name: str) -> str:
    return f"symbol:{relative_path}::{symbol_name}"


def _file_entity_prefix(relative_path: str) -> str:
    return f"symbol:{relative_path}::"


def index_file(
    storage,
    embedding_provider,
    file_path: Path,
    language: str,
    project_root: Path,
) -> None:
    """Index a single file: parse symbols, create entities, create edges, embed."""
    relative_path = str(file_path.relative_to(project_root))

    # Delete existing symbols for this file
    _delete_file_symbols(storage, relative_path)

    symbols = parse_file(file_path, language)
    logger.debug("File indexed: %s (%d symbols)", relative_path, len(symbols))
    if not symbols:
        return

    edges = extract_edges(file_path, symbols, language)

    # Build embedding texts
    embed_texts = []
    for sym in symbols:
        text = f"{sym['kind']} {sym['name']} in {relative_path}: {sym['body_preview'][:200]}"
        embed_texts.append(text)

    embeddings = embedding_provider.embed(embed_texts)

    # Store entities
    for sym, emb in zip(symbols, embeddings):
        eid = _entity_id(relative_path, sym["name"])
        metadata = {
            "file": relative_path,
            "line": sym["line"],
            "kind": sym["kind"],
            "language": language,
        }
        storage.add_entity(
            id=eid,
            name=sym["name"],
            entity_type="symbol",
            description=f"{sym['kind']} {sym['name']} in {relative_path}",
            metadata=metadata,
            embedding=emb,
        )

    # Store import edges as relationships (best-effort, targets may not exist as entities)
    for edge in edges:
        # We create a lightweight relationship; target entity may not exist
        # so we skip foreign-key-dependent storage for now
        pass


def _delete_file_symbols(storage, relative_path: str) -> None:
    """Delete all symbol entities for a given file."""
    prefix = _file_entity_prefix(relative_path)
    # Query all entities matching this file
    rows = storage.conn.execute(
        "SELECT id FROM entities WHERE entity_type = 'symbol' AND id LIKE ?",
        (prefix + "%",),
    ).fetchall()
    for row in rows:
        storage.delete_entity(row[0])


def _get_current_commit(project_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _is_git_repo(project_root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _should_exclude(path: Path, exclude_patterns: list[str]) -> bool:
    parts = path.parts
    for pattern in exclude_patterns:
        if pattern in parts:
            return True
    return False


def incremental_index(storage, embedding_provider, project_root: Path, config) -> int:
    """Check git diff, re-index changed files. Returns count of files re-indexed."""
    if not _is_git_repo(project_root):
        return 0

    last_commit = storage.get_meta("last_indexed_commit")
    if last_commit is None:
        # No previous index — do full reindex
        return full_reindex(storage, embedding_provider, project_root, config)

    changed = get_changed_files(project_root, last_commit)
    if changed is None:
        return 0

    current_commit = _get_current_commit(project_root)

    count = 0
    for fpath in changed:
        ext = fpath.suffix
        lang = EXTENSION_MAP.get(ext)
        if lang is None:
            continue

        # Check exclusions
        try:
            rel = fpath.relative_to(project_root)
        except ValueError:
            continue
        if _should_exclude(rel, config.indexing.exclude):
            continue

        if not fpath.exists():
            # File was deleted — remove its symbols
            _delete_file_symbols(storage, str(rel))
            count += 1
        else:
            index_file(storage, embedding_provider, fpath, lang, project_root)
            count += 1

    if current_commit:
        storage.set_meta("last_indexed_commit", current_commit)

    logger.info("Incremental index: %d files re-indexed", count)
    return count


def full_reindex(storage, embedding_provider, project_root: Path, config) -> int:
    """Full reindex of all source files. Returns count of files indexed."""
    count = 0
    for ext, lang in EXTENSION_MAP.items():
        for fpath in project_root.rglob(f"*{ext}"):
            try:
                rel = fpath.relative_to(project_root)
            except ValueError:
                continue
            if _should_exclude(rel, config.indexing.exclude):
                continue

            index_file(storage, embedding_provider, fpath, lang, project_root)
            count += 1

    # Record current commit if in a git repo
    current_commit = _get_current_commit(project_root)
    if current_commit:
        storage.set_meta("last_indexed_commit", current_commit)

    logger.info("Full reindex: %d files indexed", count)
    return count
