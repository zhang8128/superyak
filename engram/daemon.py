"""Engram daemon — async local agent that runs as a background service.

Talk to it from anywhere: CLI, scripts, other agents, claw, whatever.
It persists between messages, maintains conversation state, and can
call Claude Code for heavy lifting.

Usage:
    python daemon.py                        # Start daemon (default: nemotron-3-super)
    python daemon.py --model qwen3.5:27b    # Use different model
    python daemon.py --port 7432            # Custom port

Client (from another terminal):
    curl -X POST http://localhost:7432/chat -d '{"message": "hello"}'
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


class DaemonHandler(BaseHTTPRequestHandler):
    """HTTP handler for the engram daemon."""

    agent: LocalAgent  # Set by the server

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
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/chat":
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


def main():
    parser = argparse.ArgumentParser(description="Engram daemon — async local agent")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP port")
    parser.add_argument("--no-claude", action="store_true", help="Disable Claude Code")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    agent = LocalAgent(model=args.model, enable_claude=not args.no_claude)

    DaemonHandler.agent = agent

    bind = "0.0.0.0"  # Accessible on local network (phone, other machines)
    server = HTTPServer((bind, args.port), DaemonHandler)

    # Detect local network IP for phone access
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    status = agent.status()
    print(f"engram daemon")
    print(f"  model:    {status['model']}")
    print(f"  session:  {status['session_id']}")
    print(f"  memory:   {status['episodes']} episodes ({status['core']} core), "
          f"{status['semantics']} semantics, {status['instincts']} instincts")
    print(f"  claude:   {'enabled' if status['claude_enabled'] else 'disabled'}")
    print(f"  local:    http://127.0.0.1:{args.port}")
    print(f"  network:  http://{local_ip}:{args.port}")
    print()
    print("Open the network URL on your phone to chat.")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
