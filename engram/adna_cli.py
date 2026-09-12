"""Inspect, search, and read aDNA sources without starting a model or service."""

import argparse
import json
import sys

from context_adna import parse_projects


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "search", "read"):
        child = sub.add_parser(name)
        child.add_argument("project", help="INSTANCE=PATH; origin is explicit and locally declared")
        if name == "search":
            child.add_argument("query")
        elif name == "read":
            child.add_argument("source_id")
            child.add_argument("--offset", type=int, default=0)
            child.add_argument("--limit", type=int, default=4096)
    args = parser.parse_args(argv)
    try:
        source = parse_projects([args.project])[0]
        if args.command == "inspect":
            result = source.inspect()
        elif args.command == "search":
            result = {"results": [{"id": c.id, "version": c.version,
                                  **json.loads(c.representations[0])} for c in source.search(args.query)],
                      "coverage": source.coverage}
        else:
            result = source.read(args.source_id, offset=args.offset, limit=args.limit)
            if result is None:
                raise ValueError("aDNA source is unavailable or outside the selected project")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
