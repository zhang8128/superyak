# Kairos Platform: Bus + Ledger — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the event bus (from blocks) and hash-chained ledger (from agi/claw) into the kairos monorepo as `kplatform/bus` and `kplatform/ledger` — the communication and audit infrastructure.

**Architecture:** Bus is async typed pub/sub with request/response correlation and scoped isolation. Ledger is thread-safe, hash-chained, append-only JSONL with fsync, verification, and recovery. SignalBus (cross-worker messaging) already exists in `kplatform/memory/federation.py` and stays there — it's a different abstraction (persistent queue vs pub/sub).

**Tech Stack:** Python 3.12+, asyncio, threading (RLock for ledger), no external dependencies

**Spec:** `docs/superpowers/specs/2026-03-21-kairos-platform-design.md`

**Source:** `blocks/event-bus/src/event_bus.py` (97 LOC), `agi/src/agi/ledger.py` (154 LOC)

---

## File Structure

```
kplatform/
  bus/
    __init__.py               -- exports: Bus, ScopedBus, create_bus
    bus.py                    -- async pub/sub with request/response correlation
  ledger/
    __init__.py               -- exports: Ledger, LedgerCorruptionError
    ledger.py                 -- hash-chained append-only JSONL
tests/
  platform/
    bus/
      __init__.py
      test_bus.py             -- pub/sub, request/response, scoping, concurrency
    ledger/
      __init__.py
      test_ledger.py          -- append, verify, recover, threading
```

**Key decisions:**
- Bus is async (matches blocks source), tests use `pytest-asyncio`
- Ledger uses plain dict entries (not typed EventType enum) — more flexible
- Genesis hash is `"0" * 64` (standardized from agi/claw)
- Bus auto-logs to ledger deferred to integration layer (not baked into bus itself)
- No `unsubscribe()` method — matches blocks source. Tests can check `_handlers` directly.

---

### Task 1: Ledger

**Files:**
- Create: `kplatform/ledger/__init__.py`
- Create: `kplatform/ledger/ledger.py`
- Create: `tests/platform/ledger/__init__.py`
- Create: `tests/platform/ledger/test_ledger.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/platform/ledger/test_ledger.py
import json
import threading
from pathlib import Path

from kplatform.ledger import Ledger, LedgerCorruptionError


def test_append_and_read(tmp_path):
    path = tmp_path / "test.jsonl"
    ledger = Ledger(path)
    entry = ledger.append({"event": "goal_submitted", "goal": "test"})
    assert entry["seq"] == 1
    assert entry["event"] == "goal_submitted"
    assert "hash" in entry
    assert "prev_hash" in entry
    entries = ledger.read_all()
    assert len(entries) == 1


def test_hash_chain(tmp_path):
    path = tmp_path / "test.jsonl"
    ledger = Ledger(path)
    e1 = ledger.append({"event": "first"})
    e2 = ledger.append({"event": "second"})
    assert e2["prev_hash"] == e1["hash"]
    assert e1["prev_hash"] == "0" * 64


def test_verify_valid(tmp_path):
    path = tmp_path / "test.jsonl"
    ledger = Ledger(path)
    for i in range(5):
        ledger.append({"event": f"entry_{i}"})
    assert ledger.verify() is True


def test_verify_tampered(tmp_path):
    path = tmp_path / "test.jsonl"
    ledger = Ledger(path)
    for i in range(3):
        ledger.append({"event": f"entry_{i}"})
    # Tamper with the file
    lines = path.read_text().strip().split("\n")
    entry = json.loads(lines[1])
    entry["event"] = "TAMPERED"
    lines[1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    # Re-read
    ledger2 = Ledger(path)
    import pytest
    with pytest.raises(LedgerCorruptionError):
        ledger2.verify()


def test_get_recent(tmp_path):
    path = tmp_path / "test.jsonl"
    ledger = Ledger(path)
    for i in range(10):
        ledger.append({"event": f"entry_{i}"})
    recent = ledger.get_recent(3)
    assert len(recent) == 3
    assert recent[0]["seq"] == 8
    assert recent[2]["seq"] == 10


def test_recover_truncates_corruption(tmp_path):
    path = tmp_path / "test.jsonl"
    ledger = Ledger(path)
    for i in range(5):
        ledger.append({"event": f"entry_{i}"})
    # Corrupt last line
    lines = path.read_text().strip().split("\n")
    lines[-1] = "NOT VALID JSON"
    path.write_text("\n".join(lines) + "\n")
    ledger2 = Ledger(path)
    valid = ledger2.recover()
    assert valid == 4
    assert len(ledger2.read_all()) == 4


def test_thread_safety(tmp_path):
    path = tmp_path / "test.jsonl"
    ledger = Ledger(path)
    errors = []

    def writer(n):
        try:
            for i in range(10):
                ledger.append({"thread": n, "i": i})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    entries = ledger.read_all()
    assert len(entries) == 40
    assert ledger.verify() is True


def test_empty_ledger(tmp_path):
    path = tmp_path / "test.jsonl"
    ledger = Ledger(path)
    assert ledger.read_all() == []
    assert ledger.verify() is True
    assert ledger.get_last_hash() == "0" * 64
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/platform/ledger/test_ledger.py -v`

- [ ] **Step 3: Write ledger.py**

```python
# kplatform/ledger/ledger.py
"""Hash-chained append-only ledger backed by JSONL."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class LedgerCorruptionError(Exception):
    """Raised when ledger hash chain is broken."""
    pass


class Ledger:
    """Thread-safe, hash-chained, append-only JSONL ledger."""

    GENESIS_HASH = "0" * 64

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._lock = threading.RLock()
        self._last_hash = self.GENESIS_HASH
        self._seq = 0

        if self._path.exists():
            self._load_state()

    def _load_state(self) -> None:
        """Read existing entries to recover last hash and sequence."""
        entries = self._read_raw()
        if entries:
            self._last_hash = entries[-1]["hash"]
            self._seq = entries[-1]["seq"]

    def append(self, data: dict) -> dict:
        """Append an entry to the ledger. Thread-safe, fsync'd."""
        with self._lock:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "ts": datetime.now(timezone.utc).isoformat(),
                "prev_hash": self._last_hash,
                **data,
            }
            entry["hash"] = self._compute_hash(entry)
            self._last_hash = entry["hash"]

            line = json.dumps(entry, sort_keys=True) + "\n"
            with open(self._path, "a") as f:
                f.write(line)
                f.flush()
                import os
                os.fsync(f.fileno())

            return entry

    def read_all(self) -> list[dict]:
        """Read all entries."""
        with self._lock:
            return self._read_raw()

    def get_recent(self, n: int) -> list[dict]:
        """Get the most recent n entries."""
        with self._lock:
            entries = self._read_raw()
            return entries[-n:] if len(entries) >= n else entries

    def get_last_hash(self) -> str:
        """Get the hash of the last entry, or genesis hash if empty."""
        with self._lock:
            return self._last_hash

    def verify(self) -> bool:
        """Verify the hash chain. Raises LedgerCorruptionError if broken."""
        with self._lock:
            entries = self._read_raw()
            prev_hash = self.GENESIS_HASH
            for entry in entries:
                if entry["prev_hash"] != prev_hash:
                    raise LedgerCorruptionError(
                        f"Broken chain at seq {entry['seq']}: "
                        f"expected prev_hash {prev_hash}, got {entry['prev_hash']}"
                    )
                expected_hash = self._compute_hash(
                    {k: v for k, v in entry.items() if k != "hash"}
                )
                if entry["hash"] != expected_hash:
                    raise LedgerCorruptionError(
                        f"Hash mismatch at seq {entry['seq']}: "
                        f"expected {expected_hash}, got {entry['hash']}"
                    )
                prev_hash = entry["hash"]
            return True

    def recover(self) -> int:
        """Truncate corrupt trailing entries. Returns count of valid entries."""
        with self._lock:
            entries = self._read_raw()
            valid = []
            prev_hash = self.GENESIS_HASH
            for entry in entries:
                try:
                    if entry["prev_hash"] != prev_hash:
                        break
                    expected = self._compute_hash(
                        {k: v for k, v in entry.items() if k != "hash"}
                    )
                    if entry["hash"] != expected:
                        break
                    valid.append(entry)
                    prev_hash = entry["hash"]
                except (KeyError, TypeError):
                    break

            # Rewrite file with valid entries only
            with open(self._path, "w") as f:
                for entry in valid:
                    f.write(json.dumps(entry, sort_keys=True) + "\n")
                f.flush()
                import os
                os.fsync(f.fileno())

            self._last_hash = valid[-1]["hash"] if valid else self.GENESIS_HASH
            self._seq = valid[-1]["seq"] if valid else 0
            return len(valid)

    def _read_raw(self) -> list[dict]:
        """Read and parse JSONL file."""
        if not self._path.exists():
            return []
        entries = []
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        break  # Stop at first unparseable line
        return entries

    @staticmethod
    def _compute_hash(entry: dict) -> str:
        """SHA-256 of the JSON-serialized entry (without 'hash' field)."""
        raw = json.dumps(entry, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()
```

- [ ] **Step 4: Write __init__.py**

```python
# kplatform/ledger/__init__.py
"""Hash-chained append-only audit ledger."""

from kplatform.ledger.ledger import Ledger, LedgerCorruptionError

__all__ = ["Ledger", "LedgerCorruptionError"]
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/platform/ledger/test_ledger.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add kplatform/ledger/ tests/platform/ledger/
git commit -m "feat(ledger): hash-chained append-only JSONL with verify and recover"
```

---

### Task 2: Event Bus

**Files:**
- Create: `kplatform/bus/__init__.py`
- Create: `kplatform/bus/bus.py`
- Create: `tests/platform/bus/__init__.py`
- Create: `tests/platform/bus/test_bus.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/platform/bus/test_bus.py
import asyncio
import pytest
from kplatform.bus import Bus, ScopedBus, create_bus


@pytest.mark.asyncio
async def test_publish_subscribe():
    bus = Bus()
    received = []
    bus.subscribe("test.event", lambda data: received.append(data))
    await bus.publish("test.event", {"msg": "hello"})
    assert len(received) == 1
    assert received[0]["msg"] == "hello"


@pytest.mark.asyncio
async def test_publish_no_subscribers():
    bus = Bus()
    # Should not raise
    await bus.publish("nobody.listens", {"msg": "void"})


@pytest.mark.asyncio
async def test_multiple_subscribers():
    bus = Bus()
    results = []
    bus.subscribe("multi", lambda d: results.append("a"))
    bus.subscribe("multi", lambda d: results.append("b"))
    await bus.publish("multi", {})
    assert results == ["a", "b"]


@pytest.mark.asyncio
async def test_request_response():
    bus = Bus()

    async def handler(data):
        return {"answer": data["question"] * 2}

    bus.subscribe("math.double", handler)
    result = await bus.request("math.double", {"question": 21})
    assert result["answer"] == 42


@pytest.mark.asyncio
async def test_request_timeout():
    bus = Bus()
    # No handler — should timeout
    with pytest.raises(asyncio.TimeoutError):
        await bus.request("no.handler", {"q": 1}, timeout=0.1)


@pytest.mark.asyncio
async def test_request_cleans_up_listener():
    bus = Bus()

    async def handler(data):
        return {"ok": True}

    bus.subscribe("cleanup.test", handler)
    await bus.request("cleanup.test", {"q": 1})
    # Response listener should be removed
    response_key = "cleanup.test.response"
    assert response_key not in bus._handlers or len(bus._handlers[response_key]) == 0


@pytest.mark.asyncio
async def test_scoped_bus_isolation():
    bus = Bus()
    parent_received = []
    child_received = []

    bus.subscribe("event", lambda d: parent_received.append(d))
    scoped = bus.scope("child")
    scoped.subscribe("event", lambda d: child_received.append(d))

    await scoped.publish("event", {"from": "child"})
    assert len(child_received) == 1
    # Parent should NOT receive scoped events (unless forwarded)
    assert len(parent_received) == 0


@pytest.mark.asyncio
async def test_scoped_bus_forward():
    bus = Bus()
    parent_received = []
    bus.subscribe("forwarded", lambda d: parent_received.append(d))

    scoped = bus.scope("child")
    scoped.subscribe("forwarded", scoped.forward("forwarded"))
    await scoped.publish("forwarded", {"from": "child"})
    assert len(parent_received) == 1


@pytest.mark.asyncio
async def test_concurrent_requests():
    bus = Bus()

    async def slow_handler(data):
        await asyncio.sleep(0.01)
        return {"echo": data["val"]}

    bus.subscribe("echo", slow_handler)
    results = await asyncio.gather(
        bus.request("echo", {"val": 1}),
        bus.request("echo", {"val": 2}),
        bus.request("echo", {"val": 3}),
    )
    values = sorted(r["echo"] for r in results)
    assert values == [1, 2, 3]


def test_create_bus():
    bus = create_bus()
    assert isinstance(bus, Bus)


@pytest.mark.asyncio
async def test_publish_none_data():
    bus = Bus()
    received = []
    bus.subscribe("null", lambda d: received.append(d))
    await bus.publish("null")
    assert len(received) == 1
    assert received[0] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/platform/bus/test_bus.py -v`

- [ ] **Step 3: Write bus.py**

```python
# kplatform/bus/bus.py
"""Async event bus with typed pub/sub and request/response correlation."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any, Callable


class Bus:
    """Root event bus with pub/sub, request/response, and scoping."""

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def subscribe(self, event_name: str, handler: Callable) -> None:
        """Register a handler for an event. Sync operation."""
        self._handlers.setdefault(event_name, []).append(handler)

    async def publish(self, event_name: str, data: dict | None = None) -> None:
        """Publish an event to all subscribers."""
        handlers = list(self._handlers.get(event_name, []))
        for handler in handlers:
            result = handler(data)
            if inspect.isawaitable(result):
                await result

    async def request(
        self, event_name: str, data: dict, timeout: float = 5.0
    ) -> dict:
        """Publish and wait for a response. Raises asyncio.TimeoutError."""
        request_id = str(uuid.uuid4())
        response_event = f"{event_name}.response"
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def response_handler(response_data):
            if response_data and response_data.get("_request_id") == request_id:
                if not future.done():
                    if "_error" in response_data:
                        future.set_exception(RuntimeError(response_data["_error"]))
                    else:
                        future.set_result(response_data)

        self.subscribe(response_event, response_handler)

        # Wrap original handlers to inject request_id and publish response
        original_handlers = list(self._handlers.get(event_name, []))
        for handler in original_handlers:
            enriched_data = {**data, "_request_id": request_id}
            result = handler(enriched_data)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict):
                await self.publish(response_event, {
                    **result, "_request_id": request_id
                })

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            # Clean up response listener
            if response_event in self._handlers:
                self._handlers[response_event] = [
                    h for h in self._handlers[response_event]
                    if h is not response_handler
                ]

    def scope(self, prefix: str) -> ScopedBus:
        """Create an isolated scoped bus."""
        return ScopedBus(self, prefix)


class ScopedBus:
    """Isolated child bus. Events don't leak to parent without explicit forwarding."""

    def __init__(self, parent: Bus | ScopedBus, prefix: str):
        self._parent = parent
        self._prefix = prefix
        self._handlers: dict[str, list[Callable]] = {}

    def subscribe(self, event_name: str, handler: Callable) -> None:
        self._handlers.setdefault(event_name, []).append(handler)

    async def publish(self, event_name: str, data: dict | None = None) -> None:
        handlers = list(self._handlers.get(event_name, []))
        for handler in handlers:
            result = handler(data)
            if inspect.isawaitable(result):
                await result

    async def request(
        self, event_name: str, data: dict, timeout: float = 5.0
    ) -> dict:
        request_id = str(uuid.uuid4())
        response_event = f"{event_name}.response"
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def response_handler(response_data):
            if response_data and response_data.get("_request_id") == request_id:
                if not future.done():
                    future.set_result(response_data)

        self.subscribe(response_event, response_handler)

        original_handlers = list(self._handlers.get(event_name, []))
        for handler in original_handlers:
            enriched_data = {**data, "_request_id": request_id}
            result = handler(enriched_data)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict):
                await self.publish(response_event, {
                    **result, "_request_id": request_id
                })

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            if response_event in self._handlers:
                self._handlers[response_event] = [
                    h for h in self._handlers[response_event]
                    if h is not response_handler
                ]

    def scope(self, prefix: str) -> ScopedBus:
        return ScopedBus(self, f"{self._prefix}.{prefix}")

    def forward(self, event_name: str) -> Callable:
        """Return a handler that republishes events to the parent bus."""
        parent = self._parent

        async def bridge(data):
            await parent.publish(event_name, data)

        return bridge


def create_bus() -> Bus:
    """Factory for creating a new root bus."""
    return Bus()
```

- [ ] **Step 4: Write __init__.py**

```python
# kplatform/bus/__init__.py
"""Async event bus with typed pub/sub and scoped isolation."""

from kplatform.bus.bus import Bus, ScopedBus, create_bus

__all__ = ["Bus", "ScopedBus", "create_bus"]
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/platform/bus/test_bus.py -v`
Expected: All 11 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/kairos/Projects/kairos
git add kplatform/bus/ tests/platform/bus/
git commit -m "feat(bus): async event bus with request/response and scoped isolation"
```

---

### Task 3: Package Exports and Cross-Module Verification

**Files:**
- Modify: `kplatform/bus/__init__.py` (if needed)
- Modify: `kplatform/ledger/__init__.py` (if needed)

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/kairos/Projects/kairos && uv run pytest tests/ -v --tb=short`
Expected: All tests PASS (53 memory + 8 ledger + 11 bus = 72 tests)

- [ ] **Step 2: Verify imports**

```bash
cd /Users/kairos/Projects/kairos && uv run python -c "
from kplatform.bus import Bus, ScopedBus, create_bus
from kplatform.ledger import Ledger, LedgerCorruptionError
from kplatform.memory import Storage, Compressor, NomicEmbedProvider
print('All platform imports OK')
"
```

- [ ] **Step 3: Commit if any changes needed**

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | Ledger (hash-chained JSONL) | 8 |
| 2 | Event Bus (async pub/sub) | 11 |
| 3 | Cross-module verification | — |
| **Total** | **3 tasks** | **~19 tests** |

## Next Plans

After this plan is complete:
1. **Platform: LLM + Sandbox** — provider abstraction and capability enforcement
2. **Runtime** — daemon, scheduler, dispatcher
3. **Apps** — atlas, arena, ratchet, governor
