"""The shared embedder runs one ONNX run at a time, and a waiting query goes
before a waiting batch (the Pi, 2026-11-04: a lighthouse crossing's query
embed waited about 2 minutes behind one 4,096-text code-index request)."""

from __future__ import annotations

import hashlib
import random
import shutil
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest

import embedder_service
from embedder_service import EmbedderServer, _Lane
from embeddings import (
    EmbedderUnavailableError, NomicEmbedProvider, RemoteEmbedProvider, _token_budget_batches,
)


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

    def embed_units(self, texts, *, prefix):
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
        order = [(texts[0], prefix) for texts, prefix in provider.calls]
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
        units = provider.embed_units(texts, prefix=prefix)
        assert sorted(i for unit in units for i in unit) == list(range(len(texts)))
        for unit in units:
            alone = [f"{prefix}: {texts[i]}" for i in unit]
            assert _token_budget_batches(alone) == [list(range(len(unit)))]


class BatchSensitiveModel:
    """Stands in for fastembed's TextEmbedding: each vector depends on its text and on the whole run it was in
    (contents, size, position), so any change in how texts are grouped or ordered changes the vectors.
    (From the fresh reviewer's probe, 2026-11-04.)"""

    def __init__(self):
        self.runs = []

    def embed(self, docs, batch_size):
        docs = list(docs)
        assert batch_size == len(docs)
        self.runs.append(tuple(docs))
        key = hashlib.sha256("\x00".join(docs).encode()).digest()
        out = []
        for pos, doc in enumerate(docs):
            digest = hashlib.sha256(key + pos.to_bytes(4, "big") + doc.encode()).digest()
            out.append(np.random.default_rng(int.from_bytes(digest[:8], "big")).standard_normal(768))
        return iter(out)


def _nomic_with_fake_model():
    provider = NomicEmbedProvider(idle_seconds=0)
    provider._model = BatchSensitiveModel()
    return provider


def test_served_unit_by_unit_equals_the_whole_request_in_process():
    rng = random.Random(4)
    for trial in range(300):
        # Lengths near the 2,048-token cap (6,120 characters and up) are where a drift in grouping shows.
        lengths = [rng.choice([0, 1, 2, 3, 50, 51, 52, 1000, 6127, 6128, 6129, 6131, 9000, rng.randint(0, 12000)])
                   for _ in range(rng.randint(1, 120))]
        texts = ["".join(rng.choice("abcdefgh xyz\n") for _ in range(n)) for n in lengths]
        prefix = rng.choice(["search_document", "search_query", "clustering", ""])
        inproc = _nomic_with_fake_model()
        whole = inproc.embed(texts, prefix=prefix)
        served = _nomic_with_fake_model()
        server = EmbedderServer.__new__(EmbedderServer)  # respond() only; no socket
        server.provider, server.model_name, server.lane = served, served.MODEL_NAME, _Lane()
        answer = server.respond({"op": "embed", "texts": texts, "prefix": prefix})
        assert answer["ok"] is True, trial
        assert answer["vectors"] == whole, trial
        assert sorted(served._model.runs) == sorted(inproc._model.runs), trial


def test_a_provider_raising_mid_request_frees_the_lane(socket_dir):
    class Raising(UnitProvider):
        def embed(self, texts, *, prefix="search_document"):
            if len(self.calls) == 1:
                self.calls.append((list(texts), prefix))
                raise MemoryError("out of room on unit 2")
            return super().embed(texts, prefix=prefix)

    provider = Raising(unit_size=2)
    server = _serve(socket_dir / "e.sock", provider)
    try:
        remote = RemoteEmbedProvider(str(socket_dir / "e.sock"))
        with pytest.raises(EmbedderUnavailableError, match="out of room on unit 2"):
            remote.embed(["a", "b", "c", "d"])
        after = RemoteEmbedProvider(str(socket_dir / "e.sock"), response_timeout=5)  # a held lane fails, not hangs
        assert after.embed(["e"]) == [_vector("e")]
        assert after.embed(["f?"], prefix="search_query") == [_vector("f?")]
    finally:
        server.shutdown()
        server.server_close()


def test_units_that_miss_a_text_are_refused_before_any_work(socket_dir):
    class Gappy(UnitProvider):
        def embed_units(self, texts, *, prefix):
            return [[0], [2]]

    provider = Gappy()
    server = _serve(socket_dir / "e.sock", provider)
    try:
        with pytest.raises(EmbedderUnavailableError, match="exactly once"):
            RemoteEmbedProvider(str(socket_dir / "e.sock")).embed(["a", "b", "c"])
        assert provider.calls == []
    finally:
        server.shutdown()
        server.server_close()


def _wait_for(condition, seconds=5):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert condition()


def test_a_query_stream_holds_a_batch_unit_off_at_most_query_run_max_holds():
    lane = _Lane()
    order, release = [], threading.Event()

    def first_query():
        with lane.hold():
            order.append("q0")
            release.wait(5)

    def batch():
        with lane.batch_request() as ticket:
            with lane.hold(ticket):
                order.append("b")

    def query(i):
        with lane.hold():
            order.append(f"q{i}")

    holder = threading.Thread(target=first_query)
    holder.start()
    _wait_for(lambda: order == ["q0"])
    threads = [threading.Thread(target=batch)]
    threads[0].start()
    _wait_for(lambda: lane.batches_waiting == 1)
    threads += [threading.Thread(target=query, args=(i,)) for i in range(1, 21)]
    for thread in threads[1:]:
        thread.start()
    _wait_for(lambda: lane.queries_waiting == 20)
    release.set()
    for thread in [holder, *threads]:
        thread.join(5)
    assert order.index("b") == 1 + _Lane.QUERY_RUN_MAX
    assert len(order) == 22


def test_batch_requests_take_their_units_in_arrival_order(socket_dir):
    provider = UnitProvider(unit_size=1)
    provider.gate = threading.Event()
    server = _serve(socket_dir / "e.sock", provider)
    path = str(socket_dir / "e.sock")
    try:
        first = threading.Thread(target=lambda: RemoteEmbedProvider(path).embed(["a1", "a2", "a3"]), daemon=True)
        first.start()
        assert provider.entered.wait(5)
        second = threading.Thread(target=lambda: RemoteEmbedProvider(path).embed(["b1", "b2", "b3"]), daemon=True)
        second.start()
        _wait_for(lambda: server.lane.batches_waiting == 1)
        query = threading.Thread(
            target=lambda: RemoteEmbedProvider(path).embed(["q?"], prefix="search_query"), daemon=True)
        query.start()
        _wait_for(lambda: server.lane.queries_waiting == 1)
        provider.gate.set()
        for thread in (first, second, query):
            thread.join(5)
        assert [texts[0] for texts, _ in provider.calls] == ["a1", "q?", "a2", "a3", "b1", "b2", "b3"]
    finally:
        provider.gate.set()
        server.shutdown()
        server.server_close()


def test_a_later_batch_request_waits_for_the_earlier_one_to_finish():
    lane = _Lane()
    order, release = [], threading.Event()

    def holder():
        with lane.hold():
            release.wait(5)

    with lane.batch_request() as first:
        held = threading.Thread(target=holder)
        held.start()
        _wait_for(lambda: lane.queries_waiting == 0 and not release.is_set() and held.is_alive())

        def later():
            with lane.batch_request() as ticket:
                with lane.hold(ticket):
                    order.append("b1")

        second = threading.Thread(target=later)
        second.start()
        _wait_for(lambda: lane.batches_waiting == 1)
        release.set()
        held.join(5)
        time.sleep(0.2)  # the lane is free, and the earlier request is between units
        assert order == []
        with lane.hold(first):
            order.append("a1")
    second.join(5)
    assert order == ["a1", "b1"]


def test_units_given_as_iterators_still_answer_every_vector(socket_dir):
    class Lazy(UnitProvider):
        def embed_units(self, texts, *, prefix):
            return (iter(unit) for unit in super().embed_units(texts, prefix=prefix))

    provider = Lazy(unit_size=2)
    server = _serve(socket_dir / "e.sock", provider)
    try:
        texts = ["a", "bb", "ccc"]
        assert RemoteEmbedProvider(str(socket_dir / "e.sock")).embed(texts) == [_vector(t) for t in texts]
    finally:
        server.shutdown()
        server.server_close()


def test_after_a_batch_unit_queries_go_first_again():
    lane = _Lane()
    order, release = [], threading.Event()

    def first_query():
        with lane.hold():
            order.append("q0")
            release.wait(5)

    def batch():
        with lane.batch_request() as ticket:
            for name in ("b1", "b2"):
                with lane.hold(ticket):
                    order.append(name)

    def query(i):
        with lane.hold():
            order.append(f"q{i}")

    holder = threading.Thread(target=first_query)
    holder.start()
    _wait_for(lambda: order == ["q0"])
    threads = [threading.Thread(target=batch)]
    threads[0].start()
    _wait_for(lambda: lane.batches_waiting == 1)
    threads += [threading.Thread(target=query, args=(i,)) for i in range(1, 31)]
    for thread in threads[1:]:
        thread.start()
    _wait_for(lambda: lane.queries_waiting == 30)
    release.set()
    for thread in [holder, *threads]:
        thread.join(5)
    gap = order.index("b2") - order.index("b1")
    # The run starts over after b1: b2 waits another QUERY_RUN_MAX queries (one more if a query took the lane
    # before the batch thread asked for b2's turn), never goes straight after b1.
    assert gap in (_Lane.QUERY_RUN_MAX + 1, _Lane.QUERY_RUN_MAX + 2), order
