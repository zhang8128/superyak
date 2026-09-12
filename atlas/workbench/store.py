"""SQLite-backed evidence store."""

from __future__ import annotations

from collections import defaultdict, deque
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import unicodedata
from urllib.parse import quote

from .validation import (
    SCHEMA_VERSION,
    STATUSES,
    WorkbenchError,
    normalize_bundle,
    normalize_item,
    normalize_relation,
    validate_record_references,
)


APPLICATION_ID = 0x41545742  # "ATWB"
INSERT_COUNT_KEYS = ("sources", "items", "relations")


def _json(record):
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value):
    return json.loads(value)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalized_title(value):
    folded = unicodedata.normalize("NFKC", value).casefold()
    separated = "".join(
        character if not unicodedata.category(character).startswith(("P", "S")) else " "
        for character in folded
    )
    return " ".join(separated.split())


class Store:
    """Owns persistence, stored-state validation, and status transitions."""

    def __init__(self, path, create=False):
        self.path = Path(path)
        self._connection = None
        existed = self.path.exists()
        if not existed and not create:
            raise WorkbenchError(f"database does not exist: {self.path}")
        if existed:
            self._verify_existing_database()
        try:
            self._connection = sqlite3.connect(self.path, isolation_level=None)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA foreign_keys = ON")
            if existed:
                self._verify_open_connection()
            else:
                self._initialize()
        except (OSError, sqlite3.Error, WorkbenchError) as exc:
            self.close()
            if not existed:
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
            if isinstance(exc, WorkbenchError):
                raise
            raise WorkbenchError(f"cannot open workbench database {self.path}: {exc}") from exc

    def _read_only_connection(self):
        uri_path = quote(str(self.path.resolve()), safe="/")
        return sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)

    def _verify_existing_database(self):
        try:
            with closing(self._read_only_connection()) as connection:
                marker = connection.execute("PRAGMA application_id").fetchone()[0]
                version = connection.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.Error as exc:
            raise WorkbenchError(f"existing file is not a workbench database: {self.path}") from exc
        if marker != APPLICATION_ID or version != SCHEMA_VERSION:
            raise WorkbenchError(f"existing file is not a workbench database: {self.path}")

    def _verify_open_connection(self):
        marker = self._connection.execute("PRAGMA application_id").fetchone()[0]
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if marker != APPLICATION_ID or version != SCHEMA_VERSION:
            raise WorkbenchError(f"existing file is not a workbench database: {self.path}")
        try:
            schema = self._connection.execute(
                "SELECT value FROM metadata WHERE key = ?", ("schema_version",)
            ).fetchone()
        except sqlite3.Error as exc:
            raise WorkbenchError(f"workbench database schema is incomplete: {self.path}") from exc
        if schema is None or schema[0] != str(SCHEMA_VERSION):
            raise WorkbenchError(f"workbench database schema is incompatible: {self.path}")

    def _initialize(self):
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            statements = (
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE sources (id TEXT PRIMARY KEY, record_json TEXT NOT NULL)",
                """CREATE TABLE items (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )""",
                """CREATE TABLE relations (
                    id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )""",
                """CREATE TABLE audit_history (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_json TEXT NOT NULL
                )""",
            )
            for statement in statements:
                self._connection.execute(statement)
            self._connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            self._connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                ("title", "Atlas research workbench"),
            )
            self._connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _records(self, table):
        rows = self._connection.execute(
            f"SELECT record_json FROM {table} ORDER BY id"  # table is an internal constant
        ).fetchall()
        return [_load(row[0]) for row in rows]

    def import_bundle(self, bundle):
        """Atomically import a bundle and return collection insertion counts.

        Imported ``history`` is intentionally ignored: audit events belong to this database.
        """
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing_sources = {record["id"]: record for record in self._records("sources")}
            existing_items = {record["id"]: record for record in self._records("items")}
            existing_relations = {record["id"]: record for record in self._records("relations")}
            normalized = normalize_bundle(
                bundle,
                existing_source_ids=set(existing_sources),
                existing_item_kinds={key: value["kind"] for key, value in existing_items.items()},
            )
            incoming_item_ids = {record["id"] for record in normalized["items"]}
            incoming_relation_ids = {record["id"] for record in normalized["relations"]}
            collision = (set(existing_items) | incoming_item_ids) & (
                set(existing_relations) | incoming_relation_ids
            )
            if collision:
                raise WorkbenchError(
                    f"item and relation IDs must be globally unique: {sorted(collision)[0]}"
                )
            counts = {key: 0 for key in INSERT_COUNT_KEYS}
            collections = (
                ("sources", normalized["sources"], existing_sources),
                ("items", normalized["items"], existing_items),
                ("relations", normalized["relations"], existing_relations),
            )
            for collection, records, existing in collections:
                for record in records:
                    prior = existing.get(record["id"])
                    if prior is not None and _json(prior) != _json(record):
                        raise WorkbenchError(f"conflicting {collection[:-1]} ID: {record['id']}")
            for record in normalized["sources"]:
                if record["id"] not in existing_sources:
                    self._connection.execute(
                        "INSERT INTO sources(id, record_json) VALUES (?, ?)",
                        (record["id"], _json(record)),
                    )
                    counts["sources"] += 1
            for record in normalized["items"]:
                if record["id"] not in existing_items:
                    self._connection.execute(
                        "INSERT INTO items(id, kind, status, record_json) VALUES (?, ?, ?, ?)",
                        (record["id"], record["kind"], record["status"], _json(record)),
                    )
                    counts["items"] += 1
            for record in normalized["relations"]:
                if record["id"] not in existing_relations:
                    self._connection.execute(
                        """INSERT INTO relations(id, subject, predicate, object, status, record_json)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            record["id"], record["subject"], record["predicate"],
                            record["object"], record["status"], _json(record),
                        ),
                    )
                    counts["relations"] += 1
            self._connection.execute(
                "UPDATE metadata SET value = ? WHERE key = ?", (normalized["title"], "title")
            )
            self._connection.commit()
            return counts
        except Exception:
            self._connection.rollback()
            raise

    def export_bundle(self):
        title = self._connection.execute(
            "SELECT value FROM metadata WHERE key = ?", ("title",)
        ).fetchone()[0]
        history = [
            _load(row[0])
            for row in self._connection.execute(
                "SELECT event_json FROM audit_history ORDER BY sequence"
            ).fetchall()
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "title": title,
            "sources": self._records("sources"),
            "items": self._records("items"),
            "relations": self._records("relations"),
            "history": history,
        }

    def get(self, record_id):
        if not isinstance(record_id, str) or not record_id:
            raise WorkbenchError("record ID must not be blank")
        for table in ("items", "relations", "sources"):
            row = self._connection.execute(
                f"SELECT record_json FROM {table} WHERE id = ?", (record_id,)
            ).fetchone()
            if row is not None:
                return _load(row[0])
        raise WorkbenchError(f"record not found: {record_id}")

    def search(self, text="", facets=None, kind=None):
        if not isinstance(text, str):
            raise WorkbenchError("search text must be a string")
        if kind is not None and kind not in {"question", "approach", "claim", "experiment"}:
            raise WorkbenchError(f"unknown item kind: {kind}")
        facets = {} if facets is None else facets
        if not isinstance(facets, dict):
            raise WorkbenchError("facets must be an object")
        for axis, value in facets.items():
            if not isinstance(axis, str) or not isinstance(value, str):
                raise WorkbenchError("facet filters must map strings to strings")
        needle = text.casefold()
        results = []
        for record in self._records("items"):
            if kind is not None and record["kind"] != kind:
                continue
            searchable = f"{record['title']}\n{record['summary']}".casefold()
            if needle not in searchable:
                continue
            if any(value not in record["facets"].get(axis, []) for axis, value in facets.items()):
                continue
            results.append(record)
        return results

    def duplicates(self):
        groups = defaultdict(list)
        for record in self._records("items"):
            groups[_normalized_title(record["title"])].append(record)
        duplicates = [records for records in groups.values() if len(records) > 1]
        return sorted(duplicates, key=lambda records: [record["id"] for record in records])

    def unlocks(self, item_id):
        items = {record["id"]: record for record in self._records("items")}
        if item_id not in items:
            raise WorkbenchError(f"item not found: {item_id}")
        if items[item_id]["status"] == "withdrawn":
            return []
        active_ids = {key for key, record in items.items() if record["status"] != "withdrawn"}
        adjacency = defaultdict(list)
        for edge in self._records("relations"):
            if edge["status"] != "reviewed" or edge["predicate"] not in {"requires", "enables"}:
                continue
            if edge["subject"] not in active_ids or edge["object"] not in active_ids:
                continue
            src, dst = (
                (edge["object"], edge["subject"])
                if edge["predicate"] == "requires"
                else (edge["subject"], edge["object"])
            )
            adjacency[src].append(dst)
        for destinations in adjacency.values():
            destinations.sort()
        visited = {item_id}
        queue = deque([item_id])
        reachable = []
        while queue:
            current = queue.popleft()
            for destination in adjacency[current]:
                if destination in visited:
                    continue
                visited.add(destination)
                reachable.append(items[destination])
                queue.append(destination)
        return reachable

    def set_status(self, record_id, status, reason, actor):
        if status not in STATUSES:
            raise WorkbenchError(f"status is not allowed: {status}")
        if not isinstance(reason, str) or not reason.strip():
            raise WorkbenchError("reason must not be blank")
        if not isinstance(actor, str) or not actor.strip():
            raise WorkbenchError("actor must not be blank")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            found = None
            for table, record_type in (("items", "item"), ("relations", "relation")):
                row = self._connection.execute(
                    f"SELECT record_json FROM {table} WHERE id = ?", (record_id,)
                ).fetchone()
                if row is not None:
                    found = table, record_type, _load(row[0])
                    break
            if found is None:
                raise WorkbenchError(f"record not found: {record_id}")
            table, record_type, record = found
            old_status = record["status"]
            if old_status == "withdrawn" and status != "withdrawn":
                raise WorkbenchError(f"withdrawn record cannot be restored: {record_id}")
            if old_status == status:
                raise WorkbenchError(f"record {record_id} already has status {status}")
            timestamp = _utc_now()
            record["status"] = status
            if status == "reviewed":
                record["reviewed_by"] = actor.strip()
                record["reviewed_at"] = timestamp
            elif status != "withdrawn":
                record["reviewed_by"] = ""
                record["reviewed_at"] = ""
            record = (
                normalize_item(record, f"item {record_id}")
                if record_type == "item"
                else normalize_relation(record, f"relation {record_id}")
            )
            sources = {source["id"] for source in self._records("sources")}
            item_kinds = {item["id"]: item["kind"] for item in self._records("items")}
            validate_record_references(record, source_ids=sources, item_kinds=item_kinds)
            if table == "items":
                self._connection.execute(
                    "UPDATE items SET status = ?, record_json = ? WHERE id = ?",
                    (status, _json(record), record_id),
                )
            else:
                self._connection.execute(
                    "UPDATE relations SET status = ?, record_json = ? WHERE id = ?",
                    (status, _json(record), record_id),
                )
            event = {
                "record_id": record_id,
                "record_type": record_type,
                "from_status": old_status,
                "to_status": status,
                "reason": reason.strip(),
                "actor": actor.strip(),
                "timestamp": timestamp,
            }
            self._connection.execute(
                "INSERT INTO audit_history(event_json) VALUES (?)", (_json(event),)
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
