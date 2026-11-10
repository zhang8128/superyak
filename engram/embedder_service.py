"""Shared embedding service: one model, many Engram processes.

Every Engram server, hook and daemon used to load nomic-embed-text-v1.5
itself, about 1 GB resident each. Four sessions held four copies, and
simultaneous startup maintenance OOM-killed a 19 GB machine (2026-10-01).
This service holds the one model and runs one ONNX run at a time, so the
machine-wide embedding peak stays bounded however many agents connect. The
model loads on the first request and is dropped after
ENGRAM_EMBED_IDLE_SECONDS (default 300) without one. With 0 (keep the model) the
service loads it once it is listening, in a background thread, so the first
request after a restart finds it loaded (the Pi, 2026-11-09: a reload takes 2 s
and a crossing's asker gives up after about 1 s).

A large request is embedded unit by unit (the provider's own token-budget
batches), and a waiting query (prefix search_query) takes the lane before a
waiting batch unit, so a recall waits at most one unit, not one request. Batch
requests still run one at a time in arrival order (the
Pi, 2026-11-04: a lighthouse crossing's query waited about 2 minutes behind a
4,096-text code-index request).
A request may say how long its caller will still wait (remaining_ms). The
service stamps its arrival on its own monotonic clock and, each time one of its
units gets the lane, drops it if that time has run out, so a caller that gave
up no longer holds the lane (the Pi, 2026-11-09: a short text took 74 s behind
abandoned requests). A request that names no deadline runs to the end, as before.
Clients select it with ENGRAM_EMBEDDER_SOCKET (see embeddings.py).

Protocol: one request per connection over a Unix socket. Each message is a
4-byte big-endian length followed by that many bytes of UTF-8 JSON.

    {"op": "info"}
        -> {"ok": true, "model": ..., "dimension": 768, "loaded": true}
           loaded: whether the model is in memory now (absent if the provider can't say)
    {"op": "embed", "texts": [...], "prefix": "search_document", "remaining_ms": 900}
        -> {"ok": true, "model": ..., "dimension": 768, "vectors": [[...], ...]}
        -> {"ok": false, "error": "expired"}  when remaining_ms ran out first
    remaining_ms is optional: a finite, non-negative number of milliseconds.
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
import collections
import json
import logging
import math
import os
import socketserver
import struct
import threading
from contextlib import contextmanager
from pathlib import Path
from time import monotonic

logger = logging.getLogger("engram.embedder")

MAX_MESSAGE_BYTES = 64 * 1024 * 1024
MAX_TEXTS = 4096
CHUNK_TEXTS = 16  # texts per lane hold for a provider that names no units of its own
QUERY_PREFIX = "search_query"
WARM_TEXT = "warm"
EXPIRED = {"ok": False, "error": "expired"}
_HEADER = struct.Struct(">I")


class _Expired(Exception):
    """A request's remaining_ms ran out before one of its units got the lane."""


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
    """One inference at a time. A waiting query goes before a waiting batch
    unit, and batch requests take their units in arrival order, one request at
    a time, as they ran before the lane.

    After QUERY_RUN_MAX query holds in a row while a batch unit waits, that
    unit goes next: a query stream can't hold a batch off for ever, and a
    query still waits at most one unit. Because only the oldest batch request
    runs, one request's partial vectors are held at a time."""

    QUERY_RUN_MAX = 8

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._busy = False
        self._queries_waiting = 0
        self._batches: collections.deque[int] = collections.deque()  # unfinished batch requests, oldest first
        self._next_ticket = 0
        self._waiting: set[int] = set()  # batch requests with a unit waiting for the lane
        self._query_run = 0

    @property
    def queries_waiting(self) -> int:
        with self._cond:
            return self._queries_waiting

    @property
    def batches_waiting(self) -> int:
        with self._cond:
            return len(self._waiting)

    @contextmanager
    def batch_request(self):
        """A batch request's place in line; its units run only at the front."""
        with self._cond:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._batches.append(ticket)
        try:
            yield ticket
        finally:
            with self._cond:
                self._batches.remove(ticket)
                self._cond.notify_all()

    def _head_waiting(self) -> bool:
        return bool(self._batches) and self._batches[0] in self._waiting

    def _may_take(self, ticket: int | None) -> bool:
        if self._busy:
            return False
        if ticket is None:  # a query
            return not (self._query_run >= self.QUERY_RUN_MAX and self._head_waiting())
        if self._batches[0] != ticket:
            return False
        return self._queries_waiting == 0 or self._query_run >= self.QUERY_RUN_MAX

    @contextmanager
    def hold(self, ticket: int | None = None):
        """Hold the lane for one unit: a query's (ticket None) or a batch request's."""
        with self._cond:
            if ticket is None:
                self._queries_waiting += 1
            else:
                self._waiting.add(ticket)
            took = False
            try:
                while not self._may_take(ticket):
                    self._cond.wait()
                took = True
            finally:
                if ticket is None:
                    self._queries_waiting -= 1
                else:
                    self._waiting.discard(ticket)
                if not took:  # left by an exception: let the next waiter re-check
                    self._cond.notify_all()
            if ticket is None:
                self._query_run = self._query_run + 1 if self._head_waiting() else 0
            else:
                self._query_run = 0
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
        arrived = monotonic()
        loaded = self._model_loaded()
        info = {"ok": True, "model": self.model_name, "dimension": self.provider.dimension()}
        op = request.get("op")
        if op == "info":
            return info if loaded is None else {**info, "loaded": loaded}
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
        remaining = request.get("remaining_ms")
        if remaining is not None:
            try:  # float() of an int past about 309 digits raises OverflowError: the same refusal
                remaining = None if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) \
                    else float(remaining)
            except OverflowError:
                remaining = None
            if remaining is None or not math.isfinite(remaining) or remaining < 0:
                return {"ok": False, "error": "remaining_ms must be a finite, non-negative number of milliseconds"}
        deadline = None if remaining is None else arrived + remaining / 1000
        if not texts:
            return {**info, "vectors": []}
        units_of = getattr(self.provider, "embed_units", None)
        if callable(units_of):
            units = [list(unit) for unit in units_of(texts, prefix=prefix)]  # iterators would be spent by the check
        else:
            units = [list(range(start, min(start + CHUNK_TEXTS, len(texts))))
                     for start in range(0, len(texts), CHUNK_TEXTS)]
        if sorted(i for unit in units for i in unit) != list(range(len(texts))):
            return {"ok": False, "error": "the provider's units don't cover each text exactly once"}
        try:
            if prefix == QUERY_PREFIX:
                vectors = self._embed_units(texts, prefix, units, None, deadline)
            else:
                with self.lane.batch_request() as ticket:
                    vectors = self._embed_units(texts, prefix, units, ticket, deadline)
        except _Expired as expired:
            logger.info("dropped an expired %s request: %d of %d texts embedded, %.0f ms after it arrived "
                        "with %.0f ms left; model %s when it arrived",
                        "query" if prefix == QUERY_PREFIX else "batch", expired.args[0],
                        len(texts), (monotonic() - arrived) * 1000, remaining,
                        {True: "loaded", False: "not loaded", None: "of unknown state"}[loaded])
            return dict(EXPIRED)
        return {**info, "vectors": vectors}

    def _model_loaded(self) -> bool | None:
        is_loaded = getattr(self.provider, "is_loaded", None)
        return bool(is_loaded()) if callable(is_loaded) else None

    def keeps_model(self) -> bool:
        """True when the provider never drops its model (idle setting 0)."""
        return getattr(self.provider, "_idle_seconds", None) == 0

    def warm(self) -> bool:
        """Load the model with one embed of a fixed short text, through the lane. Never raises."""
        started = monotonic()
        try:
            with self.lane.hold(None):
                self.provider.embed([WARM_TEXT], prefix=QUERY_PREFIX)
        except Exception:
            logger.exception("warming the model failed; it will load on the first request")
            return False
        logger.info("model loaded at start in %.1f s", monotonic() - started)
        return True

    def warm_in_background(self) -> threading.Thread | None:
        """With the model kept, warm it on a thread so the socket answers at once. Otherwise do nothing."""
        if not self.keeps_model():
            return None
        thread = threading.Thread(target=self.warm, name="embedder-warm", daemon=True)
        thread.start()
        return thread

    def _embed_units(self, texts: list[str], prefix: str, units: list[list[int]], ticket: int | None,
                     deadline: float | None = None) -> list:
        vectors: list = [None] * len(texts)
        done = 0
        for unit in units:
            with self.lane.hold(ticket):
                if deadline is not None and monotonic() >= deadline:  # checked at its turn, so it runs nothing
                    raise _Expired(done)
                part = self.provider.embed([texts[i] for i in unit], prefix=prefix)
            for index, vector in zip(unit, part, strict=True):
                vectors[index] = vector
            done += len(unit)
        return vectors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="embedder_service")
    parser.add_argument("--socket", required=True, type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("ENGRAM_LOG_LEVEL", "INFO"))

    from embeddings import NomicEmbedProvider

    server = EmbedderServer(args.socket, NomicEmbedProvider())
    logger.info("serving %s on %s", server.model_name, args.socket)
    server.warm_in_background()
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
