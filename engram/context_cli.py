"""Opt-in dynamic Engram chat: python -m context_cli --help."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import parse_qs, urlparse

from context_compile import Budget, ContextCapacityError
from context_provider import ProviderError, ResponsesProvider
from context_runtime import ContextRuntime
from context_sources import EngramSource
from context_store import ContextStore, StoreConflict


def build_parser():
    parser = argparse.ArgumentParser(description="Engram automatic context runtime")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--instance")
    parser.add_argument("--engram-db", type=Path)
    parser.add_argument("--no-engram", action="store_true", help="Disable local Engram memory retrieval")
    parser.add_argument("--adna-project", action="append", default=[], metavar="INSTANCE=PATH",
                        help="Use an explicit aDNA project as read-only context; repeat for distinct origins")
    parser.add_argument("--lighthouse-context", help="Explicit Lighthouse context for this chat process, e.g. memory/technical")
    parser.add_argument("--lighthouse-purpose", help="Explicit Lighthouse purpose; requires --lighthouse-context and --instance")
    parser.add_argument("--provider", choices=("codex", "responses"), default="codex")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--context-window", type=int, help="Verified model context capacity; required for API mode")
    parser.add_argument("--input-ceiling", type=int, default=24_000)
    parser.add_argument("--soft-target", type=int, default=12_000)
    parser.add_argument("--max-output", type=int, default=8_000)
    parser.add_argument("--margin", type=int, default=1000)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--strict", action="store_true", help="Reject adapters without per-model-call counting")
    parser.add_argument("--thread", default="default")
    sub = parser.add_subparsers(dest="command", required=True)
    from context_coding_cli import add_code_parser
    add_code_parser(sub)
    chat = sub.add_parser("chat", help="Chat interactively, or send one message")
    chat.add_argument("message", nargs="?")
    chat.add_argument("--event-id", help="Idempotent client ID for a one-shot message")
    serve = sub.add_parser("serve", help="Serve the local chat UI")
    serve.add_argument("--port", type=int, default=7433)
    sub.add_parser("status")
    inspect = sub.add_parser("inspect", help="Inspect the latest context manifest")
    inspect.add_argument("--manifest-id")
    correction = sub.add_parser("correct", help="Record an explicit durable correction or pin")
    correction.add_argument("key")
    correction.add_argument("content")
    unpin = sub.add_parser("unpin")
    unpin.add_argument("key")
    forget = sub.add_parser("forget", help="Delete a thread's local archive and derived context")
    forget.add_argument("--yes", action="store_true", help="Confirm deletion of the selected thread")
    return parser


def resolve_paths(args):
    home = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent)).resolve()
    if args.instance and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.instance):
        raise ValueError("Instance must be a simple name, not a path")
    instance = home / ".engram"
    if args.instance:
        instance = instance / "instances" / args.instance
    return (args.data_dir or instance / "context-runtime").resolve(), (args.engram_db or instance / "graph.db").resolve()


def make_runtime(args, store, memory):
    from context_adna import parse_projects
    adna = parse_projects(args.adna_project)
    instance = validate_lighthouse_args(args, memory)
    if args.provider == "responses" and not args.context_window:
        raise ValueError("API mode requires --context-window from a verified model profile; API billing is separate")
    if args.strict and args.provider == "codex":
        raise ValueError("Codex subscription adapter operates between episodes; strict mode needs a per-call integration")
    budget = Budget(input_ceiling=args.input_ceiling, soft_target=args.soft_target, context_window=args.context_window or 40_000, output_reserve=args.max_output, margin=args.margin, require_strict=args.strict or args.provider == "responses")
    if args.provider == "codex":
        from context_codex import CodexProvider
        provider = CodexProvider(model=args.model, timeout=args.timeout)
    else:
        provider = ResponsesProvider(model=args.model, timeout=args.timeout)
    sources = () if args.no_engram else (EngramSource(memory),)
    sources += adna
    if instance is not None:
        from context_lighthouse import LighthouseSource
        sources += (LighthouseSource(store, receiver=args.instance, instance_dir=instance,
                                    context_id=args.lighthouse_context, purpose=args.lighthouse_purpose),)
    return ContextRuntime(store, provider, budget, sources=sources)


def validate_lighthouse_args(args, memory):
    context, purpose = args.lighthouse_context, args.lighthouse_purpose
    if context is None and purpose is None:
        return None
    from lighthouse_receiver_config import NAME, context_ref
    if (not context or not purpose or not args.instance or not NAME.fullmatch(args.instance)
            or args.command not in {'chat', 'serve'} or len(purpose) > 256):
        raise ValueError('Lighthouse needs --instance, --lighthouse-context and --lighthouse-purpose on chat or serve')
    context_ref(context)
    home = Path(os.environ.get('ENGRAM_HOME', Path(__file__).resolve().parent)).resolve()
    instance = home / '.engram' / 'instances' / args.instance
    if memory != (instance / 'graph.db').resolve() or not memory.is_file():
        raise ValueError('Lighthouse needs the existing named receiver database; a different --engram-db is not supported')
    return instance


def make_server(runtime, port=7433):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Conversation text does not belong in HTTP access logs.

        def _json(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self):
            allowed = {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in allowed or (origin and urlparse(origin).netloc not in allowed):
                self._json({"error": "Local origin required"}, 403)
                return False
            return True

        def _error(self, exc):
            status = 409 if isinstance(exc, StoreConflict) else 422 if isinstance(exc, ContextCapacityError) else 502 if isinstance(exc, ProviderError) else 500 if isinstance(exc, sqlite3.Error) else 400
            self._json({"error": str(exc), "kind": type(exc).__name__}, status)

        def do_GET(self):
            if not self._allowed():
                return
            parsed = urlparse(self.path)
            args = parse_qs(parsed.query)
            thread = args.get("thread_id", ["default"])[0]
            try:
                runtime.store._check_thread(thread)
                if parsed.path == "/":
                    path = Path(__file__).with_name("context_chat.html")
                    if not path.exists():
                        path = Path(sys.prefix) / "share" / "engram" / "context_chat.html"
                    body = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                elif parsed.path in {"/status", "/health"}:
                    self._json(runtime.status(thread))
                elif parsed.path == "/context":
                    self._json(runtime.store.manifest(thread, args.get("id", [None])[0]))
                elif parsed.path == "/history":
                    self._json(runtime.store.recent(thread, 30))
                elif parsed.path == "/source":
                    self._json(runtime._tool(thread, {"name": "archive_read", "arguments": json.dumps({"id": args.get("id", [""])[0], "offset": int(args.get("offset", [0])[0]), "limit": 4096})}))
                else:
                    self._json({"error": "Unknown endpoint"}, 404)
            except (ValueError, OSError, sqlite3.Error, StoreConflict, ContextCapacityError, ProviderError) as exc:
                self._error(exc)

        def do_POST(self):
            if not self._allowed():
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json({"error": "JSON body required"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 300_000:
                    self._json({"error": "Request body exceeds size limit or is empty"}, 413)
                    return
                self.connection.settimeout(10)
                try:
                    data = json.loads(self.rfile.read(length))
                except RecursionError as exc:
                    raise ValueError("JSON nesting exceeds parser limit") from exc
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                thread = data.get("thread_id", "default")
                runtime.store._check_thread(thread)
                path = urlparse(self.path).path
                if path == "/chat":
                    self._json(runtime.chat(thread, data.get("message"), event_id=data.get("event_id")))
                elif path == "/correct":
                    key, content = data.get("key"), data.get("content")
                    if not isinstance(key, str) or not isinstance(content, str):
                        raise ValueError("Correction needs a key and content")
                    self._json(runtime.correct(thread, key, content))
                elif path == "/unpin":
                    key = data.get("key")
                    if not isinstance(key, str):
                        raise ValueError("Unpin needs a key")
                    with runtime.store.lease(thread):
                        runtime.store.unpin(thread, key)
                    self._json({"unpinned": key})
                else:
                    self._json({"error": "Unknown endpoint"}, 404)
            except (ValueError, OSError, sqlite3.Error, StoreConflict, ContextCapacityError, ProviderError) as exc:
                self._error(exc)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    store = None
    runtime = None
    try:
        directory, memory = resolve_paths(args)
        validate_lighthouse_args(args, memory)
        from context_adna import parse_projects
        parse_projects(args.adna_project)
        store = ContextStore(directory / "context.db")
        if args.command == "code":
            from context_coding_cli import run_code
            return run_code(args, store, memory)
        if args.command in {"status", "inspect", "unpin", "forget", "correct"}:
            if args.command == "status":
                result = store.status(args.thread)
            elif args.command == "inspect":
                result = store.manifest(args.thread, args.manifest_id)
            elif args.command == "forget":
                if not args.yes:
                    raise ValueError("Deleting an archive requires forget --yes")
                store.forget_thread(args.thread)
                result = {"forgotten_thread": args.thread}
            else:
                with store.lease(args.thread):
                    if args.command == "correct":
                        result = store.record_state(args.thread, args.key, args.content)
                    else:
                        store.unpin(args.thread, args.key)
                        result = {"unpinned": args.key}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        runtime = make_runtime(args, store, memory)
        if args.command == "serve":
            server = make_server(runtime, args.port)
            print(f"Engram: http://127.0.0.1:{server.server_port} ({runtime.provider.capabilities['budget_scope']} context, {runtime.provider.capabilities['billing']})", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        elif args.message is not None:
            print(json.dumps(runtime.chat(args.thread, args.message, args.event_id), ensure_ascii=False, indent=2))
        else:
            print(f"Engram · {args.model} · {runtime.provider.capabilities['billing']} · Ctrl-D to leave")
            while True:
                try:
                    message = input("You: ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if message.strip():
                    try:
                        print(runtime.chat(args.thread, message)["response"])
                    except (ValueError, StoreConflict, ContextCapacityError, ProviderError) as exc:
                        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    except (ValueError, OSError, sqlite3.Error, StoreConflict, ContextCapacityError, ProviderError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if runtime is not None:
            runtime.close()
        elif store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
