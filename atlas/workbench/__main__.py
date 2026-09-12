"""Command-line interface for the local evidence workbench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .legacy import import_vault
from .store import Store, WorkbenchError


def _parser():
    parser = argparse.ArgumentParser(prog="python -m workbench")
    parser.add_argument("--db", type=Path, help="workbench SQLite database")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("init", help="initialize a marked workbench database")
    import_parser = subcommands.add_parser("import", help="import a portable JSON bundle")
    import_parser.add_argument("bundle", type=Path)
    search_parser = subcommands.add_parser("search", help="search item titles and summaries")
    search_parser.add_argument("query", nargs="?", default="")
    search_parser.add_argument("--facet", action="append", default=[], metavar="AXIS=VALUE")
    search_parser.add_argument("--kind", choices=("question", "approach", "claim", "experiment"))
    show_parser = subcommands.add_parser("show", help="show one item, relation, or source")
    show_parser.add_argument("id")
    subcommands.add_parser("duplicates", help="find normalized exact-title candidates")
    unlocks_parser = subcommands.add_parser("unlocks", help="show reviewed prerequisite reachability")
    unlocks_parser.add_argument("id")
    review_parser = subcommands.add_parser("review", help="change a record status with an audit event")
    review_parser.add_argument("id")
    review_parser.add_argument("--status", required=True)
    review_parser.add_argument("--reason", required=True)
    review_parser.add_argument("--actor", required=True)
    subcommands.add_parser("export", help="export the portable bundle and local history")
    vault_parser = subcommands.add_parser("import-vault", help="import proposed questions from legacy notes")
    vault_parser.add_argument("vault", type=Path)
    render_parser = subcommands.add_parser("render", help="render a self-contained HTML workbench")
    render_parser.add_argument("--output", required=True, type=Path)
    return parser


def _facets(values):
    facets = {}
    for value in values:
        if "=" not in value:
            raise WorkbenchError(f"facet must use axis=value: {value}")
        axis, selection = value.split("=", 1)
        if not axis.strip() or not selection.strip():
            raise WorkbenchError(f"facet must use nonblank axis=value: {value}")
        if axis in facets and facets[axis] != selection:
            raise WorkbenchError(f"facet axis repeated with conflicting values: {axis}")
        facets[axis] = selection
    return facets


def _read_bundle(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkbenchError(f"cannot read JSON bundle {path}: {exc}") from exc


def _emit(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _run(arguments):
    if arguments.db is None:
        raise WorkbenchError("--db is required")
    if arguments.command == "init":
        with Store(arguments.db, create=True):
            pass
        return {"database": str(arguments.db), "initialized": True}
    with Store(arguments.db) as store:
        if arguments.command == "render":
            from .render import write_rendered_bundle

            write_rendered_bundle(store.export_bundle(), arguments.output, arguments.db)
            return {"output": str(arguments.output)}
        if arguments.command == "import":
            return store.import_bundle(_read_bundle(arguments.bundle))
        if arguments.command == "search":
            return store.search(arguments.query, facets=_facets(arguments.facet), kind=arguments.kind)
        if arguments.command == "show":
            return store.get(arguments.id)
        if arguments.command == "duplicates":
            return store.duplicates()
        if arguments.command == "unlocks":
            return store.unlocks(arguments.id)
        if arguments.command == "review":
            store.set_status(arguments.id, arguments.status, arguments.reason, arguments.actor)
            return store.get(arguments.id)
        if arguments.command == "export":
            return store.export_bundle()
        if arguments.command == "import-vault":
            return import_vault(store, arguments.vault)
    raise WorkbenchError(f"unknown command: {arguments.command}")


def main(argv=None):
    parser = _parser()
    try:
        result = _run(parser.parse_args(argv))
    except WorkbenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
