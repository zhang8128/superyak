"""Durable session research drafts with automatic local Lighthouse publication."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

from .lighthouse import overlap, publish, read_json, validate_publication
from .lighthouse_wire import digest
from . import research_graph
from .validation import WorkbenchError, normalize_bundle, normalize_item, normalize_source


CONFIG = "workbench/data/lighthouse-automation.json"
MAX_DRAFT_BYTES = 64 * 1024
MAX_DRAFTS = 1000


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _text(value, label, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be nonblank text of at most {maximum} characters")
    return value


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _read(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"Expected a regular, non-symlink file: {path}")
    return read_json(path)


def _directory(path):
    if path.is_symlink():
        raise ValueError(f"State directory cannot be a symlink: {path}")
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"Expected a directory: {path}")


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _save(path, value, *, replace=False):
    if path.is_symlink():
        raise ValueError(f"Output cannot be a symlink: {path}")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".write-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        _sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ResearchInbox:
    """Own a project's immutable draft journal and derived publication versions."""

    def __init__(self, project):
        self.project = Path(project).resolve(strict=True)
        self.state = self.project / ".atlas"

    def _local_file(self, relative):
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError("Configured input paths must be project-relative")
        path = self.project / relative
        if not path.resolve().is_relative_to(self.project):
            raise ValueError("Configured input escapes the project")
        return path

    def _configuration(self):
        config = _read(self.project / CONFIG)
        if not isinstance(config, dict) or set(config) != {"version", "bundle", "views"}:
            raise ValueError("Automation config requires version, bundle, and views")
        if type(config["version"]) is not int or config["version"] != 1:
            raise ValueError("Unsupported automation config version")
        views = config["views"]
        if not isinstance(views, dict) or not 1 <= len(views) <= 8:
            raise ValueError("Configure between one and eight views")
        if any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", name) for name in views):
            raise ValueError("Invalid configured view name")
        return config

    def _draft(self, raw, view_names):
        required = {"idempotency_key", "kind", "title", "summary", "views"}
        optional = {"context", "facets", "sources", "evidence", "links"}
        if not isinstance(raw, dict) or required - set(raw) or set(raw) - required - optional:
            raise ValueError("Draft requires idempotency_key, kind, title, summary, views; unknown fields are refused")
        if len(_json_bytes(raw)) > MAX_DRAFT_BYTES:
            raise ValueError("Draft exceeds 64 KiB")
        _text(raw["idempotency_key"], "idempotency_key")
        views = raw["views"]
        if (not isinstance(views, list) or not views or any(not isinstance(v, str) for v in views)
                or len(set(views)) != len(views) or set(views) - set(view_names)):
            raise ValueError("Choose distinct configured views explicitly")
        item = normalize_item({
            "id": "draft-validation", "kind": raw["kind"], "title": raw["title"],
            "summary": raw["summary"], "context": raw.get("context", {}),
            "facets": raw.get("facets", {}), "evidence": raw.get("evidence", []),
        })
        if not isinstance(raw.get("sources", []), list) or not isinstance(raw.get("links", []), list):
            raise ValueError("sources and links must be lists")
        sources = [normalize_source(source) for source in raw.get("sources", [])]
        if len({s["id"] for s in sources}) != len(sources):
            raise ValueError("Duplicate draft source ID")
        links = deepcopy(raw.get("links", []))
        for link in links:
            if not isinstance(link, dict) or set(link) != {"predicate", "target", "rationale"}:
                raise ValueError("Links require predicate, target, and rationale")
            for field in link:
                _text(link[field], f"link.{field}", 4000)
        result = {key: item[key] for key in ("kind", "title", "summary", "context", "facets", "evidence")}
        result.update(idempotency_key=raw["idempotency_key"], views=sorted(views), sources=sources, links=links)
        digest(result)
        return result

    @staticmethod
    def _identifier(session_id, key):
        return "draft-" + digest({"session_id": session_id, "key": key})["value"]

    def _entries(self, view_names):
        if self.state.is_symlink() or (self.state / "drafts").is_symlink():
            raise ValueError("Inbox state cannot be a symlink")
        files = sorted((self.state / "drafts").glob("*.json"))
        if len(files) > MAX_DRAFTS:
            raise ValueError("Inbox exceeds 1000 drafts")
        entries = []
        for path in files:
            entry = _read(path)
            if not isinstance(entry, dict) or set(entry) != {"version", "id", "session_id", "recorded_at", "request_digest", "draft"}:
                raise ValueError("Malformed stored draft entry")
            if type(entry["version"]) is not int or entry["version"] != 1:
                raise ValueError("Unsupported stored draft version")
            _text(entry["session_id"], "stored session_id")
            timestamp = datetime.fromisoformat(entry["recorded_at"])
            if timestamp.tzinfo is None:
                raise ValueError("Stored capture time requires a timezone")
            normalized = self._draft(entry["draft"], view_names)
            expected_id = self._identifier(entry["session_id"], normalized["idempotency_key"])
            if (entry["id"] != expected_id or path.name != expected_id + ".json"
                    or entry["request_digest"] != digest(normalized) or normalized != entry["draft"]):
                raise ValueError("Stored draft integrity mismatch")
            entries.append(entry)
        return entries

    def _graph_entries(self, view_names):
        if self.state.is_symlink() or (self.state / "graph-drafts").is_symlink():
            raise ValueError("Graph inbox state cannot be a symlink")
        files = sorted((self.state / "graph-drafts").glob("*.json"))
        if len(files) > research_graph.MAX_GRAPH_DRAFTS:
            raise ValueError("Graph inbox exceeds its draft capacity")
        entries = []
        for path in files:
            if path.stat().st_size > research_graph.MAX_GRAPH_DRAFT_BYTES * 2:
                raise ValueError("Stored graph draft exceeds its size limit")
            entries.append(research_graph.validate_entry(_read(path), path, view_names))
        return entries

    def _inputs(self, extra=None):
        config = self._configuration()
        bundle = normalize_bundle(_read(self._local_file(config["bundle"])))
        configurations = {name: _read(self._local_file(path)) for name, path in config["views"].items()}
        entries = self._entries(configurations)
        graph_entries = self._graph_entries(configurations)
        if extra is not None:
            entries.append(extra)
        sources = {source["id"]: source for source in bundle["sources"]}
        for entry in entries:
            draft = entry["draft"]
            for source in draft["sources"]:
                if source["id"] in sources and sources[source["id"]] != source:
                    raise ValueError(f"Conflicting source ID: {source['id']}")
                sources[source["id"]] = source
            item = {key: deepcopy(draft[key]) for key in ("kind", "title", "summary", "context", "facets", "evidence")}
            item.update(id=entry["id"], status="proposed", provenance={
                "capture": "session_draft", "session_id": entry["session_id"],
                "recorded_at": entry["recorded_at"], "idempotency_key": draft["idempotency_key"],
            })
            bundle["items"].append(item)
            for index, link in enumerate(draft["links"]):
                bundle["relations"].append({
                    "id": f"{entry['id']}:link:{index}", "subject": entry["id"],
                    "predicate": link["predicate"], "object": link["target"], "status": "proposed",
                    "rationale": link["rationale"], "context": deepcopy(draft["context"]),
                    "evidence": deepcopy(draft["evidence"]),
                })
            for name in draft["views"]:
                configurations[name]["item_ids"].append(entry["id"])
        bundle["sources"] = list(sources.values())
        research_graph.compose_graph(bundle, configurations, graph_entries)
        bundle = normalize_bundle(bundle)
        for collection in ("items", "sources", "relations"):
            bundle[collection].sort(key=lambda record: record["id"])
        for value in configurations.values():
            value["item_ids"] = sorted(value["item_ids"])
        return bundle, configurations, entries + graph_entries

    @contextmanager
    def _lock(self):
        _directory(self.state)
        for name in ("drafts", "graph-drafts", "publications"):
            _directory(self.state / name)
        descriptor = os.open(self.state / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Inbox lock must be a regular file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Research inbox is busy; no record was submitted by this call") from exc
            yield
        finally:
            os.close(descriptor)

    @staticmethod
    def _generation(bundle, configurations):
        return digest({"bundle": bundle, "configurations": configurations})["value"]

    def _read_generation(self, generation):
        if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{64}", generation):
            raise ValueError("Invalid publication generation identifier")
        directory = self.state / "publications" / generation
        if directory.parent.is_symlink() or directory.is_symlink():
            raise ValueError("Publication directories cannot be symlinks")
        manifest = _read(directory / "manifest.json")
        old_fields = {"generation", "generated_at", "draft_count", "views"}
        graph_fields = {"graph_draft_count", "graph_record_count", "graph_relation_count"}
        if (not isinstance(manifest, dict)
                or set(manifest) not in (old_fields, old_fields | graph_fields)
                or manifest["generation"] != generation or type(manifest["draft_count"]) is not int
                or not 0 <= manifest["draft_count"] <= MAX_DRAFTS):
            raise ValueError("Malformed publication manifest")
        for field, maximum in (("graph_draft_count", research_graph.MAX_GRAPH_DRAFTS),
                               ("graph_record_count", research_graph.MAX_GRAPH_DRAFTS),
                               ("graph_relation_count", research_graph.MAX_GRAPH_DRAFTS * research_graph.MAX_GRAPH_RELATIONS)):
            if type(manifest.get(field, 0)) is not int or not 0 <= manifest.get(field, 0) <= maximum:
                raise ValueError("Malformed publication graph counts")
        if datetime.fromisoformat(manifest["generated_at"]).tzinfo is None:
            raise ValueError("Publication time requires a timezone")
        views = manifest["views"]
        if (not isinstance(views, dict) or not 1 <= len(views) <= 8
                or any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", name) for name in views)):
            raise ValueError("Invalid manifest view names")
        bundle = normalize_bundle(_read(directory / "bundle.json"))
        packages = {}
        for name, description in views.items():
            package = validate_publication(_read(directory / f"{name}.json"))
            if description != {"records": len(package["claims"]), "snapshot_digest": package["snapshot"]["digest"]}:
                raise ValueError("Publication manifest does not match its artifacts")
            packages[name] = package
        for receiver in packages:
            for offered in packages:
                if receiver != offered:
                    saved = _read(directory / f"{receiver}-receives-{offered}.json")
                    expected = overlap(packages[receiver], packages[offered], manifest["generated_at"])
                    if saved != expected:
                        raise ValueError("Saved overlap report does not match its publications and evaluation time")
        return manifest, bundle, packages

    @staticmethod
    def _validate_inputs(manifest, saved_bundle, packages, bundle, configurations, entries):
        counts = research_graph.journal_counts(entries)
        if (saved_bundle != bundle or set(packages) != set(configurations)
                or any(manifest.get(name, 0) != count for name, count in counts.items())):
            raise ValueError("Cached publication does not match its inputs")
        for name, config in configurations.items():
            if packages[name] != publish(bundle, config | {"issued_at": manifest["generated_at"]}):
                raise ValueError("Cached publication does not match its configured view")

    def _refresh(self):
        bundle, configurations, entries = self._inputs()
        generation = self._generation(bundle, configurations)
        destination = self.state / "publications" / generation
        if destination.is_symlink():
            raise ValueError("Publication generation cannot be a symlink")
        if destination.exists():
            manifest, saved_bundle, packages = self._read_generation(generation)
            self._validate_inputs(manifest, saved_bundle, packages, bundle, configurations, entries)
        else:
            temporary = Path(tempfile.mkdtemp(prefix=".generation-", dir=destination.parent))
            try:
                issued_at = _now()
                packages = {}
                for name, config in configurations.items():
                    packages[name] = validate_publication(publish(bundle, config | {"issued_at": issued_at}))
                    _save(temporary / f"{name}.json", packages[name])
                _save(temporary / "bundle.json", bundle)
                for receiver in packages:
                    for offered in packages:
                        if receiver != offered:
                            _save(temporary / f"{receiver}-receives-{offered}.json",
                                  overlap(packages[receiver], packages[offered], issued_at))
                manifest = {
                    "generation": generation, "generated_at": issued_at,
                    **research_graph.journal_counts(entries),
                    "views": {name: {"records": len(package["claims"]),
                                     "snapshot_digest": package["snapshot"]["digest"]}
                              for name, package in packages.items()},
                }
                _save(temporary / "manifest.json", manifest)
                os.rename(temporary, destination)
                _sync_directory(destination.parent)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        _save(self.state / "current.json", manifest, replace=True)
        from .research_views import export_research
        views = export_research(self.project, {"bundle": bundle, "views": {
            name: list(config["item_ids"]) for name, config in configurations.items()}}, generation)
        return manifest | {"research_views": views}

    def refresh(self):
        with self._lock():
            return self._refresh()

    def record(self, draft, session_id):
        _text(session_id, "session_id")
        normalized = self._draft(draft, self._configuration()["views"])
        identifier = self._identifier(session_id, normalized["idempotency_key"])
        with self._lock():
            path = self.state / "drafts" / f"{identifier}.json"
            entry = {"version": 1, "id": identifier, "session_id": session_id,
                     "recorded_at": _now(), "request_digest": digest(normalized), "draft": normalized}
            duplicate = path.exists()
            if duplicate:
                previous = _read(path)
                if previous["request_digest"] != entry["request_digest"]:
                    raise ValueError("Idempotency key already records different content; retain it and use a new key for a new finding")
            else:
                bundle, configurations, entries = self._inputs(extra=entry)
                counts = research_graph.journal_counts(entries)
                if counts["draft_count"] + counts["graph_record_count"] > MAX_DRAFTS:
                    raise ValueError("Inbox is full (1000 drafts)")
                # Validate the complete graph and publication profile before durable capture.
                for config in configurations.values():
                    publish(bundle, config)
                _save(path, entry)
            receipt = {"recorded": True, "record_id": identifier, "session_id": session_id,
                       "duplicate": duplicate, "views": normalized["views"]}
            try:
                manifest = self._refresh()
            except (ValueError, WorkbenchError, OSError, TypeError, KeyError, RecursionError) as error:
                return receipt | {"publication_status": "pending", "generation": None,
                                  "error": str(error), "recovery": "Draft saved. Run refresh; keep the same idempotency key."}
            return receipt | {"publication_status": "current", "generation": manifest["generation"],
                              "research_views": manifest["research_views"]}

    def record_graph(self, proposal, session_id, *, guard=None):
        """Atomically save one grounded question and links, or existing-item links.

        The optional worker guard checks current eligibility under the capture
        lock. An existing receipt replays without rechecking its old inputs.
        Independent proposals for an existing edge fail without capturing a
        second account; reassessments belong in the separate review journal.
        """
        _text(session_id, "session_id")
        normalized = research_graph.normalize_proposal(proposal, self._configuration()["views"])
        identifier = research_graph.graph_identifier(session_id, normalized["idempotency_key"])
        with self._lock():
            path = self.state / "graph-drafts" / f"{identifier}.json"
            duplicate = path.exists()
            if duplicate:
                entry = research_graph.validate_entry(_read(path), path, self._configuration()["views"])
                if entry["request_digest"] != research_graph.graph_digest(normalized):
                    raise ValueError("Idempotency key already records different content; retain it and use a new key")
            else:
                bundle, configurations, entries = self._inputs()
                if research_graph.journal_counts(entries)["graph_draft_count"] >= research_graph.MAX_GRAPH_DRAFTS:
                    raise ValueError("Graph inbox is full")
                counts = research_graph.journal_counts(entries)
                if normalized["question"] is not None and counts["draft_count"] + counts["graph_record_count"] >= MAX_DRAFTS:
                    raise ValueError("Inbox is full (1000 draft records)")
                snapshot = {"bundle": bundle, "views": {name: list(config["item_ids"])
                                                        for name, config in configurations.items()}}
                research_graph.validate_expected(normalized, snapshot)
                source_digests, views = research_graph.capture_metadata(normalized, snapshot)
                entry = {"version": research_graph.GRAPH_VERSION, "id": identifier, "session_id": session_id,
                         "recorded_at": _now(), "request_digest": research_graph.graph_digest(normalized),
                         "proposal": normalized, "source_digests": source_digests, "views": views}
                entry["capture_digest"] = research_graph.graph_digest(entry)
                if len(_json_bytes(entry)) > research_graph.MAX_GRAPH_DRAFT_BYTES * 2:
                    raise ValueError("Stored graph draft exceeds its size limit")
                research_graph.validate_entry(entry, path, configurations)
                # Validate a separate prospective graph; the guard sees the
                # unchanged current graph it must assess, never its own output.
                prospective, profiles = deepcopy(bundle), deepcopy(configurations)
                research_graph.compose_graph(prospective, profiles, [entry])
                prospective = normalize_bundle(prospective)
                for config in profiles.values():
                    publish(prospective, config)
                if guard is not None:
                    guard(snapshot)
                _save(path, entry)
            receipt = {"recorded": True, "duplicate": duplicate, "graph_draft_id": identifier,
                       "record_ids": [identifier + ":question"] if normalized["question"] is not None else [],
                       "relation_ids": [f"{identifier}:link:{index}" for index in range(len(normalized["relations"]))],
                       "session_id": session_id, "views": entry["views"]}
            try:
                manifest = self._refresh()
            except (ValueError, WorkbenchError, OSError, TypeError, KeyError, RecursionError) as error:
                return receipt | {"publication_status": "pending", "generation": None,
                                  "error": str(error), "recovery": "Graph draft saved. Run refresh; keep the same idempotency key."}
            return receipt | {"publication_status": "current", "generation": manifest["generation"],
                              "research_views": manifest["research_views"]}

    def _status(self, bundle, configurations, entries):
        expected = self._generation(bundle, configurations)
        from .research_views import export_status
        pointer = self.state / "current.json"
        result = {
            "project": str(self.project), **research_graph.journal_counts(entries),
            "record_count": len(bundle["items"]), "relation_count": len(bundle["relations"]),
            "generation": None, "publication_status": "pending", "overlaps": {},
            "expected_generation": expected, "views": list(configurations),
            "recording": "agent-selected drafts; deterministic save and refresh",
            "research_views": export_status(self.project, expected),
        }
        if pointer.exists() or pointer.is_symlink():
            try:
                current = _read(pointer)
                manifest, saved_bundle, packages = self._read_generation(current["generation"])
                if manifest != current:
                    raise ValueError("Current pointer differs from the complete generation manifest")
                if current["generation"] == expected:
                    self._validate_inputs(manifest, saved_bundle, packages, bundle, configurations, entries)
                result["generation"] = current["generation"]
                result["publication_status"] = "current" if current["generation"] == expected else "pending"
                result["publications"] = {
                    name: str(self.state / "publications" / current["generation"] / f"{name}.json")
                    for name in packages
                }
                result["bundle"] = str(self.state / "publications" / current["generation"] / "bundle.json")
                result["policy_evaluated_at"] = _now()
                for receiver in packages:
                    for offered in packages:
                        if receiver != offered:
                            report = overlap(packages[receiver], packages[offered], result["policy_evaluated_at"])
                            result["overlaps"][f"{receiver}<-{offered}"] = {
                                "status": report["status"], "shared_records": len(report["record_pairs"]),
                            }
            except (ValueError, WorkbenchError, OSError, TypeError, KeyError, RecursionError) as error:
                result.update(publication_status="invalid", error=str(error))
        return result

    def status(self):
        return self._status(*self._inputs())

    def snapshot(self):
        """Read the complete current graph and explicit view membership."""
        bundle, configurations, _ = self._inputs()
        return {"bundle": bundle, "views": {name: list(config["item_ids"])
                                             for name, config in configurations.items()}}

    def context(self, query="", limit=10):
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("Query must be text of at most 1000 characters")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20")
        bundle, configurations, entries = self._inputs()
        sources = {source["id"]: source for source in bundle["sources"]}
        matches = [record for record in bundle["items"]
                   if query.casefold() in (record["title"] + " " + record["summary"] + " " + record["id"]).casefold()]
        return {
            "status": self._status(bundle, configurations, entries), "matches": len(matches), "truncated": len(matches) > limit,
            "records": [{"record": record, "views": [name for name, config in configurations.items()
                                                       if record["id"] in config["item_ids"]],
                         "sources": [sources[identifier] for identifier in sorted({e["source_id"] for e in record["evidence"]})]}
                        for record in matches[:limit]],
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    recording = commands.add_parser("record", help="Save an attributed research draft and refresh its views")
    recording.add_argument("draft", type=Path)
    recording.add_argument("--session", default=None, help="Operator attribution; defaults to CODEX_THREAD_ID")
    graph_recording = commands.add_parser("record-graph", help="Atomically save a question and links, or existing-item links")
    graph_recording.add_argument("draft", type=Path)
    graph_recording.add_argument("--session", default=None, help="Operator attribution; defaults to CODEX_THREAD_ID")
    context = commands.add_parser("context", help="Search existing research with evidence and capture status")
    context.add_argument("query", nargs="?", default="")
    context.add_argument("--limit", type=int, default=10)
    commands.add_parser("refresh", help="Refresh configured views without extending their grants")
    commands.add_parser("status", help="Inspect capture and publication state")
    opening = commands.add_parser("open", help="Refresh and open the research browser or Obsidian notes")
    opening.add_argument("--obsidian", action="store_true", help="Open Research/Start Here.md in Obsidian")
    commands.add_parser("mcp", help="Serve the optional local MCP interface over stdio")
    from .research_service import add_commands, dispatch
    add_commands(commands)
    args = parser.parse_args(argv)
    try:
        if args.command in {"start", "run", "stop", "research-status", "supervise", "review-backlog"}:
            result = dispatch(args)
            if type(result) is int:
                return result
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            return 2 if args.command == "review-backlog" and result.get("errors") else 0
        inbox = ResearchInbox(args.project)
        if args.command == "mcp":
            from .automation_mcp import create_server
            create_server(inbox).run()
            return 0
        if args.command in {"record", "record-graph"}:
            if args.draft.stat().st_size > MAX_DRAFT_BYTES:
                raise ValueError("Draft exceeds 64 KiB")
            recorder = inbox.record_graph if args.command == "record-graph" else inbox.record
            result = recorder(_read(args.draft), args.session or os.environ.get("CODEX_THREAD_ID"))
        elif args.command == "context":
            result = inbox.context(args.query, args.limit)
        elif args.command == "refresh":
            result = inbox.refresh()
        elif args.command == "open":
            from .research_views import open_view
            result = inbox.refresh()
            result["opened"] = open_view(result["research_views"], obsidian=args.obsidian)
        else:
            result = inbox.status()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 2 if result.get("recorded") and result.get("publication_status") == "pending" else 0
    except (ValueError, WorkbenchError, OSError, RuntimeError, TypeError, KeyError, RecursionError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
