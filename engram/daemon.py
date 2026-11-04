"""Engram daemon — async local agent that runs as a background service.

Talk to it from this machine: CLI, scripts, other agents, claw. It listens on loopback unless --host names another
address, and it has no authentication.
It persists between messages, maintains conversation state, and can
call Claude Code for heavy lifting.

Usage:
    python daemon.py                        # Start daemon (default: nemotron-3-super)
    python daemon.py --model qwen3.5:27b    # Use different model
    python daemon.py --port 7432            # Custom port
    python daemon.py --host 0.0.0.0         # Listen beyond loopback (no authentication: read the warning)

Client (from another terminal):
    curl -X POST http://localhost:7432/chat -H 'Content-Type: application/json' -d '{"message": "hello"}'
    curl http://localhost:7432/status
    curl http://localhost:7432/recall?q=ostrom+commons
    curl http://localhost:7432/core
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent))
from local_agent import LocalAgent

logger = logging.getLogger("engram.daemon")

DEFAULT_PORT = int(os.environ.get("ENGRAM_DAEMON_PORT", "7432"))
DEFAULT_MODEL = os.environ.get("LOCAL_AGENT_MODEL", "gemma4:31b")


def allowed_hosts(bound_host: str, local_ip: str | None, extra: list[str] | None = None) -> frozenset[str]:
    """The host names a request may carry: loopback, the bound host, the detected local IP when bound to every
    interface, and any --allow-host. A web page can't make a browser send another (DNS rebinding sends its own)."""
    names = {"127.0.0.1", "localhost"}
    if bound_host in ("0.0.0.0", ""):  # both bind every interface
        if local_ip:
            names.add(local_ip)
    elif bound_host not in LOOPBACK:
        names.add(bound_host)
    names.update(_host_name(name) for name in extra or [])  # a Host's port is never compared, so drop one here
    return frozenset(name.lower() for name in names)


def _split_host(value: str) -> tuple[str, int]:
    """A Host header's name and port (80 when it names none)."""
    name, sep, port = value.rpartition(":")
    if sep and port.isascii() and port.isdigit():
        return name.lower(), int(port)
    return value.lower(), 80


def _host_name(value: str) -> str:
    """The name in a Host header, without its port."""
    return _split_host(value)[0]


def _same_origin(origin: str, host: str | None, allowed: frozenset[str]) -> bool:
    """An Origin is ours when it is http and names the request's own host and port (any name we know, with no Host:
    a forwarded port, `ssh -L 9000:localhost:7432`, still matches its own Host)."""
    try:
        parsed = urlparse(origin)
        port = parsed.port or 80
    except ValueError:  # an Origin urlparse can't read (``http://[evil``) is not ours
        return False
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    if host is None:
        return parsed.hostname.lower() in allowed
    return (parsed.hostname.lower(), port) == _split_host(host)


# Answers no page may frame (the chat page can reach /chat, which can run Claude Code).
_NO_FRAMING = (("X-Frame-Options", "DENY"), ("Content-Security-Policy", "frame-ancestors 'none'"))
_CHAT_PAGE_PATHS = ("/", "/chat")


class DaemonHandler(BaseHTTPRequestHandler):
    """HTTP handler for the engram daemon."""

    agent: LocalAgent  # Set by the server
    allowed_hosts: frozenset[str] = frozenset({"127.0.0.1", "localhost"})  # set by main() from the bound host

    def end_headers(self) -> None:
        for name, value in _NO_FRAMING:
            self.send_header(name, value)
        super().end_headers()

    def _from_a_page_we_dont_name(self) -> bool:
        """Refuse (403), before any read or write, what a web page we don't name could send: a Host we don't name
        (DNS rebinding), an Origin that isn't this request's own scheme, host and port, and a cross-site or same-site
        request (Fetch Metadata) other than a top-level visit to the chat page. A header a browser always sends but
        a script or curl may not (Host, Sec-Fetch-Site) is not required."""
        host = self.headers.get("Host")
        refused = host is not None and _host_name(host) not in self.allowed_hosts
        origin = self.headers.get("Origin")
        if not refused and origin is not None:
            refused = not _same_origin(origin, host, self.allowed_hosts)
        if not refused and (self.headers.get("Sec-Fetch-Site") or "").lower() in ("cross-site", "same-site"):
            visit = (self.command == "GET"
                     and (self.headers.get("Sec-Fetch-Mode") or "").lower() == "navigate"
                     and (self.headers.get("Sec-Fetch-Dest") or "").lower() == "document"
                     and urlparse(self.path).path in _CHAT_PAGE_PATHS)
            refused = not visit
        if refused:
            self._send_json({"error": "this daemon answers only its own pages and host names; a name it should "
                                      "answer to can be added with --allow-host NAME"}, 403)
        return refused

    def log_message(self, format, *args):
        logger.info(format, *args)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_chat_html(self):
        """Serve the chat UI."""
        html_path = Path(__file__).parent / "chat.html"
        if not html_path.exists():
            self._send_json({"error": "chat.html not found"}, 404)
            return
        body = html_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self._from_a_page_we_dont_name():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path in _CHAT_PAGE_PATHS:
            self._serve_chat_html()
            return

        if path == "/status":
            self._send_json(self.agent.status())

        elif path == "/core":
            core = self.agent.get_core_episodes()
            self._send_json({"count": len(core), "episodes": core})

        elif path == "/recall":
            query = params.get("q", [""])[0]
            if not query:
                self._send_json({"error": "missing ?q= parameter"}, 400)
                return
            results = self.agent.recall(query)
            self._send_json({"query": query, "results": results})

        elif path == "/instincts":
            instincts = self.agent.get_instincts()
            self._send_json({"count": len(instincts), "instincts": instincts})

        elif path == "/claude-status":
            self._send_json(self.agent.claude_status)

        elif path == "/health":
            self._send_json({
                "status": "ok",
                "model": self.agent.model,
                "session_id": self.agent.session_id[:8],
                "conversation_turns": len(self.agent.conversation),
                "claude": self.agent.claude_status["state"],
            })

        else:
            self._send_json({
                "endpoints": {
                    "GET /status": "Memory layer counts and agent state",
                    "GET /health": "Daemon health check",
                    "GET /core": "List core memories",
                    "GET /recall?q=<query>": "Search memories",
                    "GET /instincts": "List behavioral instincts",
                    "POST /chat": "Send a message (JSON body: {\"message\": \"...\"})",
                    "POST /remember": "Store a memory (JSON body: {\"content\": \"...\", \"core\": false})",
                }
            })

    def do_POST(self):
        if self._from_a_page_we_dont_name():
            return
        media_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            # A cross-site form or a no-preflight fetch can send text/plain or a form encoding, never JSON.
            self._send_json({"error": "POST bodies must be application/json"}, 415)
            return
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode() if content_length else "{}"

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/chat":
            message = data.get("message", "").strip()
            if not message:
                self._send_json({"error": "missing 'message' field"}, 400)
                return

            logger.info("Chat: %s", message[:80])
            response = self.agent.chat(message)

            self._send_json({
                "response": response,
                "turn": len(self.agent.conversation) // 2,
            })

        elif path == "/remember":
            content = data.get("content", "").strip()
            if not content:
                self._send_json({"error": "missing 'content' field"}, 400)
                return

            core = data.get("core", False)
            source = data.get("source")
            eid = self.agent.remember(content, core=core, source=source)
            self._send_json({"episode_id": eid, "core": core})

        else:
            self._send_json({"error": f"unknown endpoint: {path}"}, 404)


LOOPBACK = ("127.0.0.1", "localhost")  # HTTPServer is IPv4 only, so ::1 cannot be bound


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Engram daemon — async local agent")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP port")
    parser.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                        help="Another host name requests may carry, such as this machine's tailnet name")
    parser.add_argument("--host", default="127.0.0.1",
                        help="IPv4 address to listen on (default loopback). The daemon has no authentication, so "
                             "another address lets anyone who reaches it read and write your memories and, unless "
                             "--no-claude, run Claude Code with --permission-mode auto.")
    parser.add_argument("--no-claude", action="store_true", help="Disable Claude Code")
    return parser.parse_args(argv)


def exposure_warning(host: str, port: int) -> str | None:
    """The words printed when the daemon listens beyond this machine, or None on loopback."""
    if host in LOOPBACK:
        return None
    return (f"warning: this daemon has no authentication. Anyone who can reach {host}:{port} can read and write your "
            f"memories and, unless --no-claude, run Claude Code with --permission-mode auto. Prefer the default "
            f"loopback.")


def main():
    args = parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    agent = LocalAgent(model=args.model, enable_claude=not args.no_claude)

    DaemonHandler.agent = agent

    # Detect local network IP for phone access
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    DaemonHandler.allowed_hosts = allowed_hosts(args.host, local_ip, args.allow_host)
    server = HTTPServer((args.host, args.port), DaemonHandler)

    status = agent.status()
    print(f"engram daemon")
    print(f"  model:    {status['model']}")
    print(f"  session:  {status['session_id']}")
    print(f"  memory:   {status['episodes']} episodes ({status['core']} core), "
          f"{status['semantics']} semantics, {status['instincts']} instincts")
    print(f"  claude:   {'enabled' if status['claude_enabled'] else 'disabled'}")
    print(f"  local:    http://127.0.0.1:{args.port}")
    warning = exposure_warning(args.host, args.port)
    if warning:
        print(f"  network:  http://{local_ip if args.host == '0.0.0.0' else args.host}:{args.port}")
        print()
        print(warning)
        print("Open the network URL on your phone to chat.")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
