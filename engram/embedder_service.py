"""Shared embedding service: one model, many Engram processes.

Every Engram server, hook and daemon used to load nomic-embed-text-v1.5
itself, about 1 GB resident each. Four sessions held four copies, and
simultaneous startup maintenance OOM-killed a 19 GB machine (2026-10-01).
This service holds the one model and runs one ONNX run at a time, so the
machine-wide embedding peak stays bounded however many agents connect. The
model loads on the first request and is dropped after
ENGRAM_EMBED_IDLE_SECONDS (default 300) without one.

A large request is embedded unit by unit (the provider's own token-budget
batches), and a waiting query (prefix search_query) takes the lane before a
waiting batch unit, so a recall waits at most one unit, not one request (the
Pi, 2026-11-04: a lighthouse crossing's query waited about 2 minutes behind a
4,096-text code-index request).
Clients select it with ENGRAM_EMBEDDER_SOCKET (see embeddings.py).

Protocol: one request per connection over a Unix socket. Each message is a
4-byte big-endian length followed by that many bytes of UTF-8 JSON.

    {"op": "info"}
        -> {"ok": true, "model": ..., "dimension": 768}
    {"op": "embed", "texts": [...], "prefix": "search_document"}
        -> {"ok": true, "model": ..., "dimension": 768, "vectors": [[...], ...]}
    any failure
        -> {"ok": false, "error": "..."}

Vectors are JSON floats, which round-trip float64 exactly, so a remote
vector is identical to what the in-process provider returns for the same
text and is safe to mix with vectors already stored.

Usage:
    python embedder_service.py --socket /path/to/embedder.sock
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socketserver
import struct
import threading
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("engram.embedder")

MAX_MESSAGE_BYTES = 64 * 1024 * 1024
MAX_TEXTS = 4096
CHUNK_TEXTS = 16  # texts per lane hold for a provider that names no units of its own
QUERY_PREFIX = "search_query"
_HEADER = struct.Struct(">I")


def recv_message(sock) -> dict:
    header = _recv_exact(sock, _HEADER.size)
    (length,) = _HEADER.unpack(header)
    if length > MAX_MESSAGE_BYTES:
        raise ValueError(f"message of {length} bytes exceeds {MAX_MESSAGE_BYTES}")
    payload = json.loads(_recv_exact(sock, length).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("message must be a JSON object")
    return payload


def send_message(sock, payload: dict) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sock.sendall(_HEADER.pack(len(data)) + data)


def _recv_exact(sock, n: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < n:
        chunk = sock.recv(min(n - len(chunks), 1 << 20))
        if not chunk:
            raise ConnectionError("connection closed mid-message")
        chunks.extend(chunk)
    return bytes(chunks)


class _Handler(socketserver.BaseRequestHandler):
    server: "EmbedderServer"

    def handle(self) -> None:
        try:
            request = recv_message(self.request)
            response = self.server.respond(request)
        except Exception as e:  # malformed request: answer, never crash the service
            response = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            send_message(self.request, response)
        except OSError:
            logger.info("client went away before the response was sent")


class _Lane:
    """One inference at a time; a waiting query goes before a waiting batch unit.

    Queries are one or a few texts, so a steady stream of them can delay a
    batch but not starve it for long; a batch can never delay a query by
    more than the one unit already running."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._busy = False
        self._queries_waiting = 0

    @property
    def queries_waiting(self) -> int:
        with self._cond:
            return self._queries_waiting

    @contextmanager
    def hold(self, *, query: bool):
        with self._cond:
            if query:
                self._queries_waiting += 1
            try:
                while self._busy or (not query and self._queries_waiting):
                    self._cond.wait()
            finally:
                if query:
                    self._queries_waiting -= 1
            self._busy = True
        try:
            yield
        finally:
            with self._cond:
                self._busy = False
                self._cond.notify_all()


class EmbedderServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Connections are accepted concurrently; inference runs one unit at a time."""

    daemon_threads = True

    def __init__(self, socket_path: Path, provider) -> None:
        self.provider = provider
        self.model_name = provider.MODEL_NAME
        self.lane = _Lane()
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        if socket_path.is_socket():
            socket_path.unlink()
        old_umask = os.umask(0o177)  # socket readable by this user only
        try:
            super().__init__(str(socket_path), _Handler)
        finally:
            os.umask(old_umask)

    def respond(self, request: dict) -> dict:
        info = {"ok": True, "model": self.model_name, "dimension": self.provider.dimension()}
        op = request.get("op")
        if op == "info":
            return info
        if op != "embed":
            return {"ok": False, "error": f"unknown op: {op!r}"}
        texts = request.get("texts")
        prefix = request.get("prefix", "search_document")
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            return {"ok": False, "error": "texts must be a list of strings"}
        if len(texts) > MAX_TEXTS:
            return {"ok": False, "error": f"{len(texts)} texts exceeds {MAX_TEXTS} per request"}
        if not isinstance(prefix, str):
            return {"ok": False, "error": "prefix must be a string"}
        units_of = getattr(self.provider, "embed_units", None)
        if callable(units_of):
            units = units_of(texts, prefix)
        else:
            units = [list(range(start, min(start + CHUNK_TEXTS, len(texts))))
                     for start in range(0, len(texts), CHUNK_TEXTS)]
        query = prefix == QUERY_PREFIX
        vectors: list = [None] * len(texts)
        for unit in units:
            with self.lane.hold(query=query):
                part = self.provider.embed([texts[i] for i in unit], prefix=prefix)
            for index, vector in zip(unit, part, strict=True):
                vectors[index] = vector
        return {**info, "vectors": vectors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="embedder_service")
    parser.add_argument("--socket", required=True, type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("ENGRAM_LOG_LEVEL", "INFO"))

    from embeddings import NomicEmbedProvider

    server = EmbedderServer(args.socket, NomicEmbedProvider())
    logger.info("serving %s on %s", server.model_name, args.socket)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        args.socket.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
