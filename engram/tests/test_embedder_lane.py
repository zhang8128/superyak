"""The shared embedder runs one ONNX run at a time, and a waiting query goes
before a waiting batch (the Pi, 2026-11-04: a lighthouse crossing's query
embed waited about 2 minutes behind one 4,096-text code-index request)."""

from __future__ import annotations

import random
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest

import embedder_service
from embedder_service import EmbedderServer
from embeddings import NomicEmbedProvider, RemoteEmbedProvider, _token_budget_batches


class UnitProvider:
    """A provider that names its own units, as NomicEmbedProvider does."""

    MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
    DIMENSION = 768

    def __init__(self, unit_size=3):
        self.unit_size = unit_size
        self.calls = []
        self.gate = None  # an Event a batch unit waits on, when set
        self.entered = threading.Event()

    def dimension(self):
        return self.DIMENSION

    def embed_units(self, texts, prefix):
        return [list(range(i, min(i + self.unit_size, len(texts))))
                for i in range(0, len(texts), self.unit_size)]

    def embed(self, texts, *, prefix="search_document"):
        self.calls.append((list(texts), prefix))
        if self.gate is not None and prefix != "search_query":
            self.entered.set()
            self.gate.wait(5)
        return [[float(len(t)), float(ord(t[-1]))] + [0.0] * (self.DIMENSION - 2) for t in texts]


class PlainProvider(UnitProvider):
    embed_units = None  # a provider with no units of its own


@pytest.fixture
def socket_dir():
    path = Path(tempfile.mkdtemp(prefix="lane-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _serve(path, provider):
    server = EmbedderServer(path, provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _vector(text):
    return [float(len(text)), float(ord(text[-1]))] + [0.0] * 766


def test_a_large_request_runs_unit_by_unit_and_answers_in_order(socket_dir):
    provider = UnitProvider(unit_size=3)
    server = _serve(socket_dir / "e.sock", provider)
    try:
        texts = [f"t{i}" * (i + 1) for i in range(10)]
        vectors = RemoteEmbedProvider(str(socket_dir / "e.sock")).embed(texts)
        assert [len(call[0]) for call in provider.calls] == [3, 3, 3, 1]
        assert vectors == [_vector(t) for t in texts]
    finally:
        server.shutdown()
        server.server_close()


def test_a_provider_without_units_is_cut_into_fixed_chunks(socket_dir, monkeypatch):
    monkeypatch.setattr(embedder_service, "CHUNK_TEXTS", 4)
    provider = PlainProvider()
    server = _serve(socket_dir / "e.sock", provider)
    try:
        texts = [f"x{i}" for i in range(10)]
        vectors = RemoteEmbedProvider(str(socket_dir / "e.sock")).embed(texts)
        assert [len(call[0]) for call in provider.calls] == [4, 4, 2]
        assert vectors == [_vector(t) for t in texts]
    finally:
        server.shutdown()
        server.server_close()


def test_a_query_goes_ahead_of_a_waiting_batch_unit(socket_dir):
    provider = UnitProvider(unit_size=1)
    provider.gate = threading.Event()
    server = _serve(socket_dir / "e.sock", provider)
    path = str(socket_dir / "e.sock")
    try:
        batch = threading.Thread(
            target=lambda: RemoteEmbedProvider(path).embed(["a", "b", "c"]), daemon=True)
        batch.start()
        assert provider.entered.wait(5)  # the batch's first unit holds the lane
        answers = []
        query = threading.Thread(
            target=lambda: answers.append(RemoteEmbedProvider(path).embed(["q?"], prefix="search_query")),
            daemon=True)
        query.start()
        deadline = time.monotonic() + 5
        while server.lane.queries_waiting == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.lane.queries_waiting == 1
        provider.gate.set()
        query.join(5)
        batch.join(5)
        order = [(texts[0], prefix) for texts, prefix in provider.calls if texts != ["x"]]
        assert order[:2] == [("a", "search_document"), ("q?", "search_query")]
        assert [t for t, _ in order[2:]] == ["b", "c"]
        assert answers == [[_vector("q?")]]
    finally:
        provider.gate.set()
        server.shutdown()
        server.server_close()


def test_nomic_units_are_its_own_onnx_runs():
    """Each unit the server holds the lane for is exactly one of the provider's
    own token-budget batches, so a unit embedded alone pads and computes as it
    would inside the whole request: the vectors don't change."""
    rng = random.Random(1104)
    provider = NomicEmbedProvider.__new__(NomicEmbedProvider)  # no model load
    for _ in range(200):
        texts = ["w" * rng.choice([1, 5, 40, 300, 2000, 9000]) for _ in range(rng.randint(1, 60))]
        prefix = rng.choice(["search_document", "search_query", "clustering"])
        units = provider.embed_units(texts, prefix)
        assert sorted(i for unit in units for i in unit) == list(range(len(texts)))
        for unit in units:
            alone = [f"{prefix}: {texts[i]}" for i in unit]
            assert _token_budget_batches(alone) == [list(range(len(unit)))]
