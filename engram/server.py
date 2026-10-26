"""Engram MCP Server v3 — layered memory with compression and reflection."""
from __future__ import annotations

import atexit
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
import uuid
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import margins
from config import load_config, resolve_instance_name
from indexer import incremental_index
from logging_config import setup_logging
from operation_audit import sanitize_operation_details
from resonance import (
    form_resonances as _form_resonances,
    surface_resonances as _surface_resonances,
)
from scoring import score_candidate
from sharing import (list_shares as _list_shares, share as _share_memory,
                     unshare as _unshare_memory)
from storage import vec0_distance_to_similarity, _pack_embedding
from transitions import TransitionGraph

logger = logging.getLogger("engram.server")

mcp = FastMCP("engram")

def _mutation_logged(fn):
    """Record mutating tool calls without ever gating their behavior."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        bound = None
        try:
            import inspect
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        except Exception:
            bound = None
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            try:
                _record_operation(fn.__name__, bound, None, f"error:{type(exc).__name__}")
            except Exception:
                pass
            raise
        try:
            status = "success"
            if isinstance(result, dict) and (result.get("error") or result.get("removed") is False or result.get("ok") is False):
                status = "failure"
            _record_operation(fn.__name__, bound, result, status)
        except Exception:
            pass
        return result
    return wrapped

def _record_operation(operation, bound, result, outcome):
    if _storage is None:
        return
    values = bound.arguments if bound is not None else {}
    ids = []
    def collect(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "id" or key.endswith("_id") or key.endswith("_ids"):
                    if isinstance(value, list): ids.extend(value)
                    elif value is not None: ids.append(value)
                collect(value)
        elif isinstance(obj, list):
            for item in obj: collect(item)
    collect(values)
    collect(result)
    row = _storage.conn.execute("SELECT harness, model, repo FROM session_registry WHERE session_id = ?", (_session_id,)).fetchone()
    harness, model, repo = (row[0], row[1], row[2]) if row else (os.environ.get("ENGRAM_HARNESS"), None, os.getcwd())
    details = sanitize_operation_details(operation, values)
    _storage.add_operation(operation, _session_id, harness, model, repo, list(dict.fromkeys(str(i) for i in ids if i)), details, outcome)


def _generate_perceptual_framing(content: str, kind: str) -> tuple[str, str]:
    """Generate notice/implication from instinct action text.

    Mirrors Compressor._generate_perceptual_framing for backfill use.
    """
    if not content:
        return (f"when: {kind}", content)

    lower = content.lower()

    if lower.startswith("always "):
        rest = content[len("always "):].strip()
        return (f"when making choices about: {rest}", content)
    elif lower.startswith("never "):
        rest = content[len("never "):].strip()
        return (f"when considering: {rest}", content)
    elif lower.startswith("prefer "):
        rest = content[len("prefer "):].strip()
        return (f"when deciding on: {rest}", content)
    elif lower.startswith("avoid "):
        rest = content[len("avoid "):].strip()
        return (f"when considering: {rest}", content)
    elif " when " in lower:
        idx = lower.index(" when ")
        implication = content[:idx].strip()
        notice = f"when {content[idx + 6:].strip()}"
        return (notice, implication)
    elif kind == "preference":
        return (f"when making choices about: {content[:80]}", content)
    else:
        return (f"when: {content[:80]}", content)


def _backfill_instinct_perceptual(storage, embeddings):
    """Backfill notice/implication for existing instincts that lack them."""
    instincts = storage.get_all_instincts()
    backfilled = 0
    for inst in instincts:
        if inst.get("notice") is not None:
            continue

        action = inst.get("action", "")
        trigger = inst.get("trigger", "preference")
        notice, implication = _generate_perceptual_framing(action, trigger)

        # Model work must not hold SQLite's writer slot. Another process may
        # edit or fill this instinct while it runs, so recheck before writing.
        ctx_emb = embeddings.embed([notice], prefix="search_document")[0]
        with storage.transaction():
            updated = storage.conn.execute(
                "UPDATE instincts SET notice = ?, implication = ? "
                "WHERE id = ? AND notice IS NULL AND action = ? AND trigger = ? "
                "AND implication IS ?",
                (notice, implication, inst["id"], action, trigger, inst.get("implication")),
            ).rowcount
            if not updated:
                continue
            if ctx_emb is not None:
                has_ctx = storage.conn.execute(
                    "SELECT 1 FROM instinct_context_vectors WHERE id = ?", (inst["id"],)
                ).fetchone()
                if not has_ctx:
                    storage.add_instinct_context_vector(inst["id"], ctx_emb)

        backfilled += 1

    if backfilled:
        logger.info("Backfilled notice/implication for %d instincts", backfilled)

    return backfilled

# Engram home is fixed — same memories regardless of which project you're in
ENGRAM_HOME = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent))
DB_PATH = ENGRAM_HOME / ".engram" / "graph.db"
# PROJECT_ROOT is the working directory (for code indexing), ENGRAM_HOME is where memories live
PROJECT_ROOT = Path(os.environ.get("ENGRAM_PROJECT_ROOT", os.getcwd()))

_storage = None
_embeddings = None
_config = None
_compressor = None
_reflector = None
_watcher = None
_session_id = None
_session_episode_count = 0
_instance_name = None
_initialized = False
_genome_db_path = None
_framing_cfg = None
# Sleep-time maintenance deferred past the MCP handshake (see _initialize_pre_serving).
_sleep_maintenance_deferred = False
_sleep_maintenance_thread = None
_signals_db_path = None
_recall_scores: dict[str, dict[str, dict[str, float | None]]] = {}
_recall_resonances: dict[str, list[dict]] = {}
# Margins hidden alongside scores during dream-active recall, revealed by dream_verify.
_recall_margins: dict[str, dict] = {}
_instinct_graph = None
_last_instinct_id = None
_knowledge_graph = None
_wander_visits: dict[str, int] = {}
_clipboard = None
_category_store = None
_notepad_project = None
_notepad_global = None
_category_observer = None
_category_status = None
_category_atexit_callback = None
_server_lifecycle_lock = threading.RLock()
_init_lock = threading.RLock()
_category_recall_lock = threading.RLock()
_category_last_observed_at = None
_server_pid_guard = threading.RLock()
_server_lock_pid = os.getpid()
_server_atexit_callbacks = []
_server_generation_cleanup = None
_initialization_cleanup_required = False
_failed_initialization_cleanup_lock = threading.Lock()
_server_operation_context = threading.local()
_fork_quarantined_resources = []
_fork_exec_required = False
_SERVER_FORK_SNAPSHOT = ()
_SERVER_AT_FORK_REGISTERED = False


def _server_owned_resources() -> tuple[object, ...]:
    """Snapshot exact resource instances owned by the current core generation."""
    ownership_callbacks = tuple(_server_atexit_callbacks) + (
        _server_generation_cleanup,
        _category_atexit_callback,
    )
    resources = (
        _storage,
        _embeddings,
        _config,
        _compressor,
        _reflector,
        _watcher,
        _knowledge_graph,
        _clipboard,
        _category_store,
        _category_observer,
        _instinct_graph,
        _notepad_project,
        _notepad_global,
    ) + tuple(
        callback
        for callback in ownership_callbacks
        if callback is not None
    ) + tuple(
        resource
        for callback in ownership_callbacks
        if callback is not None
        for resource in tuple(getattr(callback, "_server_resources", ()))
    )
    unique = []
    seen = set()
    for resource in resources:
        if resource is not None and id(resource) not in seen:
            unique.append(resource)
            seen.add(id(resource))
    return tuple(unique)


def _before_server_fork() -> None:
    """Enter the outer lifecycle barrier before category fork quiescence."""
    global _SERVER_FORK_SNAPSHOT
    _server_lifecycle_lock.acquire()
    _SERVER_FORK_SNAPSHOT = _server_owned_resources()


def _after_server_fork_parent() -> None:
    global _SERVER_FORK_SNAPSHOT
    _SERVER_FORK_SNAPSHOT = ()
    _server_lifecycle_lock.release()


def _discard_inherited_category_observers(resources: tuple[object, ...]) -> None:
    """Remove every quarantined observer from the child-only weak registry."""
    try:
        import category_evolution as _category_evolution

        with _category_evolution._FORK_REGISTRY_LOCK:
            for resource in resources:
                try:
                    _category_evolution._FORK_OBSERVERS.discard(resource)
                except TypeError:
                    pass
    except Exception:
        pass


def _reset_server_child_state(
    resources: tuple[object, ...], current_pid: int
) -> None:
    """Quarantine inherited owners and install an empty child generation."""
    global _storage, _embeddings, _config, _compressor, _reflector, _watcher
    global _session_id, _session_episode_count, _instance_name, _initialized
    global _genome_db_path, _signals_db_path, _recall_scores, _recall_resonances
    global _sleep_maintenance_deferred, _sleep_maintenance_thread
    global _recall_margins
    global _instinct_graph, _last_instinct_id, _knowledge_graph, _wander_visits
    global _clipboard, _category_store, _category_observer
    global _notepad_project, _notepad_global
    global _category_status, _category_atexit_callback
    global _server_atexit_callbacks, _server_generation_cleanup
    global _initialization_cleanup_required
    global _failed_initialization_cleanup_lock
    global _server_operation_context
    global _fork_quarantined_resources, _fork_exec_required
    global _init_lock, _category_recall_lock, _server_pid_guard
    global _server_lifecycle_lock, _server_lock_pid, _category_last_observed_at

    requires_exec = _fork_exec_required or _initialized or bool(resources)
    callback_candidates = tuple(_server_atexit_callbacks) + (
        _server_generation_cleanup,
        _category_atexit_callback,
    )
    callbacks = []
    seen_callbacks = set()
    for callback in callback_candidates:
        if callback is not None and id(callback) not in seen_callbacks:
            callbacks.append(callback)
            seen_callbacks.add(id(callback))
    for callback in callbacks:
        try:
            atexit.unregister(callback)
        except Exception:
            pass

    _discard_inherited_category_observers(resources)

    quarantined = list(_fork_quarantined_resources)
    quarantined.extend(
        resource
        for resource in resources
        if all(resource is not existing for existing in quarantined)
    )
    _fork_quarantined_resources = quarantined
    # Native owners inherited from an initialized server cannot be safely
    # replaced in-process.  The child may only replace its process image; a
    # descendant fork preserves the same bounded quarantine and boundary.
    _fork_exec_required = requires_exec
    _server_atexit_callbacks = []
    _server_generation_cleanup = None
    _initialization_cleanup_required = False
    _failed_initialization_cleanup_lock = threading.Lock()
    _server_operation_context = threading.local()

    _storage = None
    _embeddings = None
    _config = None
    _compressor = None
    _reflector = None
    _watcher = None
    _session_id = None
    _session_episode_count = 0
    _instance_name = None
    _initialized = False
    _genome_db_path = None
    _sleep_maintenance_deferred = False
    _sleep_maintenance_thread = None
    _signals_db_path = None
    _recall_scores = {}
    _recall_resonances = {}
    _recall_margins = {}
    _instinct_graph = None
    _last_instinct_id = None
    _knowledge_graph = None
    _wander_visits = {}
    _clipboard = None
    _category_store = None
    _category_observer = None
    _category_status = None
    _category_atexit_callback = None
    _category_last_observed_at = None
    _notepad_project = None
    _notepad_global = None

    _server_lifecycle_lock = threading.RLock()
    _init_lock = threading.RLock()
    _category_recall_lock = threading.RLock()
    _server_pid_guard = threading.RLock()
    _server_lock_pid = current_pid


def _after_server_fork_child() -> None:
    """Quarantine the inherited generation before any child thread can run."""
    global _SERVER_FORK_SNAPSHOT
    resources = tuple(_SERVER_FORK_SNAPSHOT)
    _SERVER_FORK_SNAPSHOT = ()
    _reset_server_child_state(resources, os.getpid())


if (
    hasattr(os, "register_at_fork")
    and not _SERVER_AT_FORK_REGISTERED
):
    # Importing registers the standalone category hook first. Python executes
    # before hooks in reverse registration order, giving the fixed order:
    # server lifecycle -> category registry -> observer.
    try:
        import category_evolution as _category_evolution
    except ModuleNotFoundError:
        # Category evolution is optional and fails closed when its runtime
        # modules are absent (for example, an older packaged installation).
        pass

    os.register_at_fork(
        before=_before_server_fork,
        after_in_parent=_after_server_fork_parent,
        after_in_child=_after_server_fork_child,
    )
    _SERVER_AT_FORK_REGISTERED = True


def _get_instinct_graph():
    global _instinct_graph
    if _instinct_graph is None:
        db_path = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent)) / ".engram" / "instinct_transitions.db"
        _instinct_graph = TransitionGraph(db_path=db_path)
        _register_server_cleanup(
            _instinct_graph, _instinct_graph.close, "instinct graph"
        )
    return _instinct_graph


def _detect_layer(storage, memory_id: str) -> str | None:
    """Determine which layer a memory belongs to.

    Tries episode, semantic, instinct in order. Returns the layer name or None.
    """
    if storage.get_episode(memory_id) is not None:
        return "episode"
    if storage.get_semantic(memory_id) is not None:
        return "semantic"
    if storage.get_instinct(memory_id) is not None:
        return "instinct"
    return None


def _auto_walk(storage, start_id: str, max_steps: int, density_threshold: int,
               knowledge_graph, visit_counts: dict[str, int]) -> list[dict]:
    """Walk the memory graph from start_id using weighted random selection.

    At each step:
    1. Get all neighbors of current node (including entity neighbors if kg enabled)
    2. If current node has >= density_threshold total neighbors AND we've taken >= 1 step, stop
    3. Filter out already-visited nodes
    4. If no candidates, stop (dead end)
    5. Pick next node via weighted random (weight = connection_strength / (1 + visit_count))

    Returns a list of trail steps (neighbor dicts, not including start_id).
    """
    import random

    visited: set[str] = {start_id}
    trail: list[dict] = []
    current_id = start_id

    for step_num in range(max_steps):
        # Fetch entity neighbors if knowledge graph is available
        entity_neighbors = None
        if knowledge_graph is not None:
            try:
                layer = _detect_layer(storage, current_id)
                if layer is not None:
                    content = storage.get_memory_content(current_id, layer)
                    if content:
                        entity_neighbors = knowledge_graph.get_entity_neighbors(
                            content, exclude_id=current_id, num_results=10
                        )
            except Exception:
                pass

        neighbors = storage.get_neighbors(current_id, entity_neighbors=entity_neighbors)

        # Check density — stop if we've moved at least once and hit a dense cluster
        if step_num >= 1 and len(neighbors) >= density_threshold:
            break

        # Filter already-visited nodes
        candidates = [n for n in neighbors if n["id"] not in visited]

        if not candidates:
            break

        # Weighted random selection: base weight = connection_strength,
        # penalized by how many times this node has been visited this session
        weights = []
        for n in candidates:
            base = n.get("connection_strength", 0.5)
            visits = visit_counts.get(n["id"], 0)
            w = base * (1.0 / (1 + visits))
            weights.append(max(w, 1e-9))

        chosen = random.choices(candidates, weights=weights, k=1)[0]
        visited.add(chosen["id"])
        trail.append(chosen)
        current_id = chosen["id"]

    return trail


def _apply_resonance_feedback(storage, recall_id: str, used: bool) -> None:
    """Strengthen or weaken resonances based on whether recall was useful."""
    entries = _recall_resonances.pop(recall_id, None)
    if not entries:
        return
    for entry in entries:
        rid = entry["resonance_id"]
        if used:
            storage.strengthen_resonance(rid, delta=0.1)
        else:
            storage.weaken_resonance(rid, delta=0.05)


def _remember_category_error(exc: BaseException) -> None:
    """Best-effort type-only diagnostics must never mask the recall path."""
    try:
        recorder = getattr(_category_observer, "record_error", None)
        if recorder is not None:
            recorder(exc)
    except Exception:
        pass


def _observe_category_recall(
    query: str, results: list[dict], recall_id: str
) -> list[dict]:
    """Observe and optionally rerank one recall without changing response shape."""
    category_config = getattr(_config, "category_evolution", None)
    if (
        _category_observer is None
        or category_config is None
        or category_config.enabled is not True
    ):
        return results
    result_ids = [str(result.get("id", "")) for result in results if result.get("id") is not None]
    _prepare_category_recall_lock()
    global _category_last_observed_at
    observation_committed = False
    with _category_recall_lock:
        observed_at = datetime.now(timezone.utc)
        if (
            _category_last_observed_at is not None
            and observed_at < _category_last_observed_at
        ):
            observed_at = _category_last_observed_at
        _category_last_observed_at = observed_at
        try:
            _category_observer.observe_recall(
                query,
                result_ids,
                source=os.getcwd(),
                observed_at=observed_at,
                recall_id=recall_id,
            )
            observation_committed = True
        except Exception as exc:
            _remember_category_error(exc)
            logger.warning("Category observer recall failed (%s)", type(exc).__name__)

    compiled = None
    try:
        compiled = _category_observer.compile_for_recall(
            tuple(result_ids), base_tokens=0
        )
    except Exception as exc:
        _remember_category_error(exc)
        logger.warning("Category observer compile failed (%s)", type(exc).__name__)

    delivered = results
    if (
        compiled is not None
        and category_config.shadow is False
        and category_config.influence_recall is True
    ):
        try:
            delivered = _category_observer.adjust_results(
                [dict(result) for result in results], compiled, influence=0.10
            )
        except Exception as exc:
            _remember_category_error(exc)
            logger.warning("Category observer influence failed (%s)", type(exc).__name__)
    if observation_committed:
        try:
            _category_observer.observe_delivery(
                recall_id,
                [
                    str(result.get("id", ""))
                    for result in delivered
                    if result.get("id") is not None
                ],
            )
        except Exception as exc:
            _remember_category_error(exc)
            logger.warning("Category observer delivery failed (%s)", type(exc).__name__)
    return delivered


def _prepare_server_process_locks() -> None:
    current_pid = os.getpid()
    if current_pid == _server_lock_pid:
        return
    with _server_pid_guard:
        if current_pid != _server_lock_pid:
            _reset_server_child_state(_server_owned_resources(), current_pid)


def _require_exec_after_initialized_fork() -> None:
    if _fork_exec_required:
        raise RuntimeError(
            "initialized fork child must exec a fresh server process before use"
        )


def _prepare_category_recall_lock() -> None:
    _prepare_server_process_locks()


def _init(*, allow_startup_consolidation: bool = False, defer_sleep_maintenance: bool = False):
    global _initialization_cleanup_required
    _prepare_server_process_locks()
    _require_exec_after_initialized_fork()
    while True:
        # Exact cleanup runs without holding the lifecycle barrier: watcher
        # terminal join may need its worker to finish under that barrier.
        _retry_failed_initialization_cleanup()
        coordinator = None
        initialization_failed = False
        try:
            with _server_lifecycle_lock:
                # A failed initializer can publish the gate while this caller
                # waits for the barrier. Retry outside instead of admitting
                # work against the closing coordinator.
                if _initialization_cleanup_required:
                    continue
                coordinator = _admit_server_operation()
                try:
                    with _init_lock:
                        try:
                            return _init_unlocked(
                                allow_startup_consolidation=(
                                    allow_startup_consolidation is True
                                ),
                                defer_sleep_maintenance=(
                                    defer_sleep_maintenance is True
                                ),
                            )
                        except Exception:
                            _initialization_cleanup_required = True
                            initialization_failed = True
                            raise
                finally:
                    if coordinator is not None:
                        coordinator.finish_operation()
        except Exception:
            if initialization_failed and not getattr(
                _server_operation_context, "depth", 0
            ):
                _cleanup_failed_initialization()
            raise


def _server_operation(function):
    """Hold the process lifecycle barrier for one complete public operation."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        _prepare_server_process_locks()
        operation_depth = getattr(_server_operation_context, "depth", 0)
        outermost_operation = operation_depth == 0
        if _initialization_cleanup_required:
            if not outermost_operation:
                raise RuntimeError(
                    "server initialization unavailable (RuntimeError)"
                )
            _retry_failed_initialization_cleanup()
        coordinator = _admit_server_operation()
        try:
            with _server_lifecycle_lock:
                # Initialization can fail after this operation is admitted
                # but before it enters the barrier. Drain that admission
                # without invoking code against partially closed resources.
                if _initialization_cleanup_required:
                    raise RuntimeError(
                        "server initialization unavailable (RuntimeError)"
                    )
                _server_operation_context.depth = operation_depth + 1
                try:
                    return function(*args, **kwargs)
                finally:
                    _server_operation_context.depth = operation_depth
        finally:
            if coordinator is not None:
                coordinator.finish_operation()
            if outermost_operation and _initialization_cleanup_required:
                _cleanup_failed_initialization()

    return wrapped


def _server_tool(*tool_args, **tool_kwargs):
    """Register an MCP tool whose full execution participates in fork safety."""
    register = mcp.tool(*tool_args, **tool_kwargs)

    def decorate(function):
        return register(_server_operation(function))

    return decorate


class _ServerGenerationCleanup:
    """Retryable dependency-ordered cleanup for one exact core generation."""

    _server_cleanup_coordinator = True

    def __init__(self, lifecycle_lock):
        self._lifecycle_lock = lifecycle_lock
        self._cleanup_lock = threading.Lock()
        self._state_condition = threading.Condition()
        self._steps = []
        self._completed = set()
        self._closing = False
        self._operations = 0
        self._operation_owners = {}

    @property
    def _server_resources(self):
        return tuple(step[1] for step in self._steps)

    @property
    def cleanup_complete(self) -> bool:
        return all(step[0] in self._completed for step in self._steps)

    def admit_operation(self) -> bool:
        with self._state_condition:
            owner = threading.get_ident()
            owner_depth = self._operation_owners.get(owner, 0)
            if self._closing and owner_depth == 0:
                return False
            self._operations += 1
            self._operation_owners[owner] = owner_depth + 1
            return True

    def finish_operation(self) -> None:
        with self._state_condition:
            owner = threading.get_ident()
            remaining = self._operation_owners[owner] - 1
            if remaining:
                self._operation_owners[owner] = remaining
            else:
                del self._operation_owners[owner]
            self._operations -= 1
            if self._operations == 0:
                self._state_condition.notify_all()

    def add(self, resource, cleanup, label: str) -> None:
        key = (id(resource), label)
        if any(step[0] == key for step in self._steps):
            return
        if label == "watcher":
            phase = 0
        elif label == "storage":
            phase = 2
        else:
            phase = 1
        self._steps.append((key, resource, cleanup, label, phase))

    def _run_step(self, step) -> bool:
        key, _resource, cleanup, label, _phase = step
        if key in self._completed:
            return True
        try:
            cleanup()
        except Exception as exc:
            logger.warning("%s cleanup failed (%s)", label, type(exc).__name__)
            return False
        self._completed.add(key)
        return True

    def __call__(self) -> None:
        with self._cleanup_lock:
            with self._state_condition:
                self._closing = True
            watcher_ok = True
            for step in self._steps:
                if step[4] == 0 and not self._run_step(step):
                    watcher_ok = False
            if not watcher_ok:
                return

            with self._state_condition:
                if self._operation_owners.get(threading.get_ident(), 0):
                    logger.warning(
                        "server generation cleanup deferred from active operation"
                    )
                    return
                self._state_condition.wait_for(lambda: self._operations == 0)

            # Watcher joins and admitted operations drain before dependent
            # resources are closed under the same lifecycle barrier.
            with self._lifecycle_lock:
                dependencies_ok = True
                for step in self._steps:
                    if step[4] == 1 and not self._run_step(step):
                        dependencies_ok = False
                if not dependencies_ok:
                    return
                for step in self._steps:
                    if step[4] == 2:
                        self._run_step(step)


def _active_server_cleanup_coordinator():
    for callback in _server_atexit_callbacks:
        if getattr(callback, "_server_cleanup_coordinator", False):
            return callback
    return None


def _admit_server_operation():
    coordinator = _active_server_cleanup_coordinator()
    if (
        coordinator is None
        or getattr(coordinator, "_lifecycle_lock", None)
        is not _server_lifecycle_lock
    ):
        return None
    if not coordinator.admit_operation():
        raise RuntimeError("server generation is shutting down")
    return coordinator


def _ensure_server_cleanup_coordinator():
    global _server_generation_cleanup
    coordinator = _active_server_cleanup_coordinator()
    if coordinator is not None:
        _server_generation_cleanup = coordinator
        return coordinator
    coordinator = _ServerGenerationCleanup(_server_lifecycle_lock)
    _server_generation_cleanup = coordinator
    _server_atexit_callbacks.append(coordinator)
    atexit.register(coordinator)
    return coordinator


def _register_server_cleanup(resource, cleanup, label: str):
    coordinator = _ensure_server_cleanup_coordinator()
    coordinator.add(resource, cleanup, label)
    return coordinator


def _reset_failed_initialization_state() -> None:
    """Clear globals only after every exact partially initialized owner closed."""
    global _storage, _embeddings, _config, _compressor, _reflector, _watcher
    global _session_id, _session_episode_count, _instance_name, _initialized
    global _genome_db_path, _signals_db_path, _recall_scores, _recall_resonances
    global _sleep_maintenance_deferred, _sleep_maintenance_thread
    global _recall_margins
    global _instinct_graph, _last_instinct_id, _knowledge_graph, _wander_visits
    global _clipboard, _category_store, _category_observer
    global _category_status, _category_atexit_callback
    global _notepad_project, _notepad_global
    global _server_generation_cleanup, _initialization_cleanup_required

    _storage = None
    _embeddings = None
    _config = None
    _compressor = None
    _reflector = None
    _watcher = None
    _session_id = None
    _session_episode_count = 0
    _instance_name = None
    _initialized = False
    _genome_db_path = None
    _sleep_maintenance_deferred = False
    _sleep_maintenance_thread = None
    _signals_db_path = None
    _recall_scores = {}
    _recall_resonances = {}
    _recall_margins = {}
    _instinct_graph = None
    _last_instinct_id = None
    _knowledge_graph = None
    _wander_visits = {}
    _clipboard = None
    _category_store = None
    _category_observer = None
    _category_status = None
    _category_atexit_callback = None
    _notepad_project = None
    _notepad_global = None
    _server_generation_cleanup = None
    _initialization_cleanup_required = False


def _unregister_completed_initialization_cleanup(coordinator) -> None:
    if not coordinator.cleanup_complete:
        return
    try:
        atexit.unregister(coordinator)
    except Exception:
        pass
    _server_atexit_callbacks[:] = [
        callback
        for callback in _server_atexit_callbacks
        if callback is not coordinator
    ]


def _cleanup_failed_initialization() -> None:
    """Close every exact owner created by a failed current-process initializer."""
    with _failed_initialization_cleanup_lock:
        if not _initialization_cleanup_required:
            return
        coordinator = (
            _active_server_cleanup_coordinator()
            or _server_generation_cleanup
        )
        if coordinator is None:
            return
        coordinator()
        _unregister_completed_initialization_cleanup(coordinator)


def _retry_failed_initialization_cleanup() -> None:
    """Finish exact cleanup before allowing a fresh initialization attempt."""
    with _failed_initialization_cleanup_lock:
        if not _initialization_cleanup_required:
            return
        coordinator = (
            _active_server_cleanup_coordinator()
            or _server_generation_cleanup
        )
        if coordinator is not None:
            coordinator()
            if not coordinator.cleanup_complete:
                raise RuntimeError(
                    "server initialization unavailable (RuntimeError)"
                ) from None
            _unregister_completed_initialization_cleanup(coordinator)
        _reset_failed_initialization_state()


def _category_flags(category_config) -> dict:
    return {
        "enabled": getattr(category_config, "enabled", False) is True,
        "shadow": getattr(category_config, "shadow", True) is not False,
        "influence_recall": (
            getattr(category_config, "influence_recall", False) is True
        ),
        "auto_commit": getattr(category_config, "auto_commit", False) is True,
    }


def _sqlite_main_identity(
    connection: sqlite3.Connection,
) -> tuple[Path, tuple[int, int] | None]:
    row = next(
        (
            row
            for row in connection.execute("PRAGMA database_list")
            if str(row[1]) == "main"
        ),
        None,
    )
    if row is None or not row[2]:
        raise ValueError("protected SQLite database must be file-backed")
    path = Path(str(row[2])).expanduser().resolve(strict=False)
    try:
        metadata = path.stat()
    except OSError:
        identity = None
    else:
        identity = (metadata.st_dev, metadata.st_ino)
    return path, identity


def _assert_category_database_preflight(
    candidate: Path,
    protected_database_identities,
) -> Path:
    canonical = candidate.expanduser().resolve(strict=False)
    try:
        metadata = canonical.stat()
    except OSError:
        identity = None
    else:
        identity = (metadata.st_dev, metadata.st_ino)
    for protected_path, protected_identity in protected_database_identities:
        if canonical == Path(protected_path).expanduser().resolve(strict=False) or (
            identity is not None
            and protected_identity is not None
            and identity == protected_identity
        ):
            raise ValueError("category v2 path aliases a protected database")
    return candidate


def _new_category_observer(
    category_config,
    graph_db_path: Path,
    *,
    allow_startup_consolidation: bool,
    protected_database_identities=(),
):
    from category_evolution import CategoryObserver

    category_db_path = (
        Path(category_config.db_path)
        if category_config.db_path
        else graph_db_path.parent / "categories_v2.db"
    )
    _assert_category_database_preflight(
        category_db_path, protected_database_identities
    )
    observer = CategoryObserver(
        category_db_path,
        shadow=category_config.shadow,
        influence_recall=category_config.influence_recall,
        auto_commit=category_config.auto_commit,
        allow_startup_consolidation=allow_startup_consolidation,
        archive_quota_bytes=category_config.archive_quota_bytes,
        archive_high_watermark_ratio=category_config.archive_high_watermark_ratio,
        max_traversal_depth=category_config.max_traversal_depth,
        max_neighbors=category_config.max_neighbors,
        max_candidates=category_config.max_candidates,
        compile_wall_time_ms=category_config.compile_wall_time_ms,
        consolidation_rewrite_budget=category_config.consolidation_rewrite_budget,
        max_rewrite_members=category_config.max_rewrite_members,
        max_active_branches=category_config.max_active_branches,
        soft_boundary_threshold=category_config.soft_boundary_threshold,
        hard_boundary_threshold=category_config.hard_boundary_threshold,
        hard_boundary_confirmations=category_config.hard_boundary_confirmations,
        protected_database_identities=protected_database_identities,
    )
    try:
        observer.assert_database_isolated()
    except Exception:
        observer.close()
        raise
    return observer


def _activate_category_observer(
    category_config,
    graph_db_path: Path,
    *,
    allow_startup_consolidation: bool,
    protected_database_identities=(),
) -> None:
    global _category_observer, _category_status
    _category_observer = None
    _category_status = None
    if category_config is None or category_config.enabled is not True:
        return
    flags = _category_flags(category_config)
    try:
        candidate = _new_category_observer(
            category_config,
            graph_db_path,
            allow_startup_consolidation=allow_startup_consolidation,
            protected_database_identities=protected_database_identities,
        )
        try:
            candidate.assert_database_isolated()
        except Exception:
            candidate.close()
            raise
        _category_observer = candidate
    except Exception as exc:
        error_type = type(exc).__name__
        _category_status = {
            "available": False,
            "flags": flags,
            "error": error_type,
            "last_error": error_type,
        }
        logger.warning("Category observer init failed (%s)", error_type)


def _startup_auto_compress(maint) -> None:
    """Auto-compress at startup without feeding the knowledge graph.

    Graph extraction is LLM-bound (~30 s per episode with a local 27B
    model, measured 2026-09-02) and this step holds the lifecycle barrier,
    so on a fresh store with a replicated genome it would stall the first
    tool call for minutes. Queued feeds are dropped and counted in the
    maintenance report; tool-driven compress_commit() still feeds the graph.
    """
    uncompressed = _storage.get_uncompressed_episodes()
    if not uncompressed:
        return
    logger.info("Auto-compressing %d uncompressed episodes on init", len(uncompressed))
    maint.note("auto-compress", pending=len(uncompressed))
    _compressor.defer_knowledge_feeds = True
    try:
        _compressor.auto_compress()
    finally:
        _compressor.defer_knowledge_feeds = False
        skipped = _compressor.discard_knowledge_feeds()
    if skipped:
        logger.info("Startup compression skipped %d knowledge-graph feeds", skipped)
        maint.note("auto-compress", knowledge_feeds_skipped=skipped)


@contextmanager
def _maintenance_step_scope(guarded: bool):
    """Hold the lifecycle barrier for one maintenance step when running deferred.

    Per-step rather than per-pass, so a tool call that arrives during the
    background pass waits for the current step only, not for all of them.
    """
    if not guarded:
        yield
        return
    coordinator = _admit_server_operation()
    try:
        with _server_lifecycle_lock:
            yield
    finally:
        if coordinator is not None:
            coordinator.finish_operation()


def _backfill_missing_vector(storage, embeddings, source_table, vector_table, text_column, row):
    """Embed a snapshot, then atomically fill only its unchanged, missing vector.

    Table/column names come only from the three maintenance call sites below.
    The lifecycle barrier protects this connection; the short transaction also
    serializes with other processes writing to the same memory store.
    """
    text = row[text_column]
    embedding = embeddings.embed([text], prefix="search_document")[0]
    packed = _pack_embedding(embedding)
    with storage.transaction():
        current = storage.conn.execute(
            f"SELECT 1 FROM {source_table} WHERE id = ? AND {text_column} = ?",
            (row["id"], text),
        ).fetchone()
        if current is None:
            return False
        existing = storage.conn.execute(
            f"SELECT 1 FROM {vector_table} WHERE id = ?", (row["id"],)
        ).fetchone()
        if existing is not None:
            return False
        storage.conn.execute(
            f"INSERT INTO {vector_table} (id, embedding) VALUES (?, ?)",
            (row["id"], packed),
        )
    return True


def _run_sleep_maintenance(guarded: bool = False) -> None:
    """Sleep-time consolidation: decay, prune, compress, backfill, cohesion.

    Runs inline from _init() for library and test callers, and from a
    background thread under the lifecycle barrier when the process is
    serving MCP (see _initialize_pre_serving), so the client handshake
    never waits on consolidation. Every step records into the
    maintenance report; failures surface via status() and wake.
    """
    # Sleep-time maintenance on init: decay → prune → compress
    # This is engram's "consolidation during sleep" — runs between sessions.
    # Each step records into the maintenance report (the pain channel):
    # failures are swallowed so later steps still run, but they surface in
    # status() and the wake orientation instead of dying in stderr.
    from maintenance import MaintenanceReport
    _maint = MaintenanceReport()
    try:
        # 1. Recompute decay: power-law activation based on access history
        with _maintenance_step_scope(guarded), _maint.step("decay"):
            multipliers = None
            if _config.persistence.enabled:
                # one-sleep-stale cache is fine for ±15% pressure
                cached = _storage.get_persistence_scores()
                multipliers = {eid: 1.0 + 0.15 * (2.0 * s["redundancy"] - 1.0)
                               for eid, s in cached.items()}
            decayed = _storage.apply_decay(decay_exponent=0.5,
                                           exponent_multipliers=multipliers)
            if decayed:
                logger.info("Decay recomputed for %d episodes", decayed)

        # 2. Prune: delete compressed episodes that have decayed past threshold
        with _maintenance_step_scope(guarded), _maint.step("prune"):
            if _config.persistence.enabled:
                from persistence import guarded_prune
                pruned = guarded_prune(_storage, _config.persistence)
            else:
                pruned = _storage.prune_decayed(
                    threshold=0.05,
                    exempt_sources=_config.persistence.never_prune_sources)
            if pruned:
                logger.info("Pruned %d decayed episodes", pruned)
                _maint.note("prune", pruned=pruned)

        # 2b. Prune weak instincts (overridden enough to drop below threshold)
        with _maintenance_step_scope(guarded), _maint.step("instinct-prune"):
            pruned_instincts = _storage.prune_weak_instincts(strength_threshold=0.1)
            if pruned_instincts:
                logger.info("Pruned %d weak instincts", pruned_instincts)

        # 3. Auto-compress uncompressed episodes (crash recovery + consolidation)
        with _maintenance_step_scope(guarded), _maint.step("auto-compress"):
            _startup_auto_compress(_maint)

        # 4. Backfill: embed any episodes that lost vectors (WAL corruption recovery)
        with _maintenance_step_scope(guarded), _maint.step("episode-vector-backfill"):
            orphaned = _storage.get_orphaned_episodes()
            if orphaned:
                backfilled = 0
                for ep in orphaned:
                    backfilled += _backfill_missing_vector(
                        _storage, _embeddings, "episodes", "episode_vectors", "content", ep,
                    )
                logger.info("Backfilled vectors for %d orphaned episodes", backfilled)

        # 5. Backfill: embed any semantics that lost vectors (WAL corruption recovery)
        with _maintenance_step_scope(guarded), _maint.step("semantic-vector-backfill"):
            orphaned_sems = _storage.get_orphaned_semantics()
            if orphaned_sems:
                backfilled = 0
                for sem in orphaned_sems:
                    backfilled += _backfill_missing_vector(
                        _storage, _embeddings, "semantics", "semantic_vectors", "content", sem,
                    )
                logger.info("Backfilled vectors for %d orphaned semantics", backfilled)

        # 6. Backfill: embed any instincts that lack vectors (pre-existing instincts)
        with _maintenance_step_scope(guarded), _maint.step("instinct-vector-backfill"):
            instincts = _storage.get_all_instincts()
            backfilled = 0
            for inst in instincts:
                has_vec = _storage.conn.execute(
                    "SELECT 1 FROM instinct_vectors WHERE id = ?", (inst["id"],)
                ).fetchone()
                if not has_vec:
                    backfilled += _backfill_missing_vector(
                        _storage, _embeddings, "instincts", "instinct_vectors", "action", inst,
                    )
            if backfilled:
                logger.info("Backfilled vectors for %d instincts", backfilled)

        # 6b. Backfill notice/implication for pre-existing instincts
        with _maintenance_step_scope(guarded), _maint.step("instinct-perceptual-backfill"):
            _backfill_instinct_perceptual(_storage, _embeddings)

        # 7. Promote proximity suggestions to resonances (graph consolidation)
        with _maintenance_step_scope(guarded), _maint.step("graph-promotion"):
            from graph import MemoryGraph
            _memory_graph = MemoryGraph(_storage)
            promoted = _memory_graph.promote_suggestions(min_prior_sessions=2)
            if promoted:
                logger.info("Sleep: promoted %d proximity suggestions", promoted)

        # 8. Coherence check — anchors + drift detection
        with _maintenance_step_scope(guarded), _maint.step("coherence-check"):
            from coherence import CoherenceChecker
            _coherence_checker = CoherenceChecker(_storage, _embeddings)
            coherence_report = _coherence_checker.run_full_check(session_id=_session_id)
            if coherence_report["summary"] != "coherence stable":
                logger.info("Coherence: %s", coherence_report["summary"])

        # 9. Sheaf cohesion sleep pass (spec: 2026-06-13-sheaf-cohesion-design.md)
        # NOTE: narration episodes written by the sleep pass lack embeddings on first run;
        # they are backfilled by the orphan-vector pass on the NEXT startup.
        with _maintenance_step_scope(guarded), _maint.step("cohesion-sleep-pass"):
            from sheaf import run_sleep_pass
            _cohesion_report = run_sleep_pass(
                _storage,
                embed_fn=lambda text: _embeddings.embed([text], prefix="search_document")[0],
                framing_cfg=_framing_cfg,
                cfg=_config.cohesion if _config else None,
                persistence_cfg=_config.persistence if _config else None,
            )
            if _cohesion_report.get("subdivided"):
                logger.info("cohesion pass subdivided: %s",
                            [s["parent_id"] for s in _cohesion_report["subdivided"]])
            if _cohesion_report.get("queued"):
                logger.info("cohesion pass queued (LLM unavailable): %s",
                            [q["parent_id"] for q in _cohesion_report["queued"]])
            _maint.note("cohesion-sleep-pass",
                        subdivided=len(_cohesion_report.get("subdivided", []) or []),
                        queued=len(_cohesion_report.get("queued", []) or []))

        # Persistence score refresh (spec: 2026-06-13-persistence-design.md)
        # Always-on observation: feeds reflect previews and next-boot decay
        # modulation; the cache is advisory, decisions recompute live.
        with _maintenance_step_scope(guarded), _maint.step("persistence-score-refresh"):
            from persistence import compute_scores
            compute_scores(_storage, _config.persistence)
    except Exception:
        # Backstop for failures outside any step (should not happen — every
        # step swallows its own); recorded so the pain channel still sees it.
        logger.warning("Sleep-time maintenance failed — will retry next session", exc_info=True)
        _maint.steps.append({"name": "maintenance-outer", "ok": False,
                             "error": "unexpected failure outside step scope"})

    with _maintenance_step_scope(guarded):
        _maint.save(_storage.conn)


def _lane_notes(phase: str, rows: list[dict], target: str) -> None:
    """The storage's lane listener (P 5.3). The gate is read on every call: `off` returns at once, `shadow` and
    `enforce` write the lane notes, `closed` raises so that storage refuses the re-lane."""
    from permission_ledger import Ledger, effective_gate
    from storage import LaneNoteError

    gate = effective_gate(ENGRAM_HOME, [Path(_storage.db_path)])
    if gate.mode == "off":
        return
    if gate.mode == "closed":
        raise LaneNoteError(f"the permissions gate is closed: {gate.cause}")
    led = Ledger.open(ENGRAM_HOME)
    try:
        led.note_lanes(phase, rows, target, store_id=_storage.instance_identity()["instance_id"],
                       now=int(time.time()))
    finally:
        led.close()


def _init_unlocked(*, allow_startup_consolidation: bool = False, defer_sleep_maintenance: bool = False):
    global _storage, _embeddings, _config, _compressor, _reflector, _watcher, _session_id, _instance_name, _genome_db_path, _signals_db_path, _knowledge_graph, _initialized, _category_store, _category_observer, _category_status, _category_atexit_callback
    global _framing_cfg, _sleep_maintenance_deferred
    if _initialized:
        return
    from embeddings import create_embedding_provider
    from storage import Storage

    setup_logging(os.environ.get("ENGRAM_LOG_LEVEL", "INFO"))
    _config = load_config(PROJECT_ROOT)
    _instance_name = resolve_instance_name(_config)

    # Federation: use instance DB when configured, otherwise default
    db_path = DB_PATH
    if _instance_name:
        instance_db = ENGRAM_HOME / ".engram" / "instances" / _instance_name / "graph.db"
        if instance_db.exists():
            db_path = instance_db
            logger.info("Using instance DB: %s", _instance_name)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Every server and watcher access is serialized by the lifecycle barrier.
    _storage = Storage(str(db_path), check_same_thread=False)
    _register_server_cleanup(_storage, _storage.close, "storage")
    _storage.lane_listener = _lane_notes
    _embeddings = create_embedding_provider()

    harness = os.environ.get("ENGRAM_HARNESS", "claude-code")
    # Claude Code exports CLAUDE_CODE_SESSION_ID to MCP server processes;
    # CLAUDE_SESSION_ID is kept as a legacy fallback only.
    claude_session_id = (
        (os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID"))
        if harness != "codex"
        else None
    )
    bound_session_id = None
    if harness == "codex" and not claude_session_id:
        bound_session_id = _storage.resolve_session_binding(
            os.environ.get("ENGRAM_RUN_KEY", "")
        )
    _session_id = claude_session_id or bound_session_id or str(uuid.uuid4())

    # Silent provenance: server-side best-effort stamp. The hook-side stamp
    # (same session_id under Claude Code) is authoritative and fills model.
    _storage.stamp_session_registry(
        _session_id,
        harness=harness,
        model=None,
        repo=os.getcwd(),
    )

    from categories import CategoryStore
    cat_conn = sqlite3.connect(str(db_path.parent / "categories.db"))
    _register_server_cleanup(cat_conn, cat_conn.close, "category store")
    try:
        import sqlite_vec
        cat_conn.enable_load_extension(True)
        cat_conn.load_extension(sqlite_vec.loadable_path())
    except Exception as e:
        logger.warning("sqlite-vec not available for categories: %s", e)
    _category_store = CategoryStore(cat_conn, dimension=768)

    category_config = getattr(_config, "category_evolution", None)
    _activate_category_observer(
        category_config,
        db_path,
        allow_startup_consolidation=allow_startup_consolidation,
        protected_database_identities=(
            _sqlite_main_identity(_storage.conn),
            _sqlite_main_identity(cat_conn),
        ),
    )
    if _category_observer is not None:
        _category_atexit_callback = _register_server_cleanup(
            _category_observer,
            _category_observer.close,
            "category observer",
        )

    from compress import Compressor
    from dedup import Deduplicator, DedupConfig

    dedup_model = os.environ.get("ENGRAM_DEDUP_MODEL", "gemma4:31b")
    _dedup = Deduplicator(DedupConfig(model=dedup_model))

    from framing import FramingConfig, FramingDistiller
    framing_model = os.environ.get("ENGRAM_FRAMING_MODEL", dedup_model)
    _framing_cfg = FramingConfig(model=framing_model)
    _framer = FramingDistiller(_framing_cfg)

    # Knowledge graph (Graphiti + Kuzu) — optional, don't block init on failure
    graph_model = os.environ.get("ENGRAM_GRAPH_MODEL")
    _knowledge_graph = None
    if _config and _config.graph.enabled:
        try:
            from knowledge import KnowledgeGraph
            graph_config = _config.graph
            if graph_model:
                graph_config.model = graph_model
            if not graph_config.db_path:
                graph_config.db_path = str(db_path.parent / "knowledge.kuzu")
            _knowledge_graph = KnowledgeGraph(
                graph_config, embedding_provider=_embeddings
            )
            _register_server_cleanup(
                _knowledge_graph, _knowledge_graph.close, "knowledge graph"
            )
        except Exception as e:
            logger.warning("Knowledge graph init failed (non-fatal): %s", e)

    _compressor = Compressor(
        _storage, _embeddings,
        _config.compression if _config else None,
        deduplicator=_dedup,
        knowledge_graph=_knowledge_graph,
        framer=_framer,
        cohesion_config=_config.cohesion if _config else None,
        persistence_config=_config.persistence if _config else None,
    )
    # Tool-driven compression returns while graph extraction runs on the
    # knowledge loop (minutes per episode with a local 27B model).
    _compressor.background_knowledge_feeds = True

    from reflection import Reflector
    _genome_db_path = ENGRAM_HOME / ".engram" / "genome" / "graph.db"
    _signals_db_path = ENGRAM_HOME / ".engram" / "signals.db"
    _reflector = Reflector(
        _storage,
        _config.reflection.staleness_days if _config else 30,
        genome_db_path=str(_genome_db_path) if _genome_db_path and _genome_db_path.exists() else None,
        signals_db_path=str(_signals_db_path) if _signals_db_path and _signals_db_path.exists() else None,
        cohesion_config=_config.cohesion if _config else None,
        persistence_config=_config.persistence if _config else None,
        category_reporter=(
            _category_observer.report
            if _category_observer is not None
            else ((lambda status=_category_status: dict(status)) if _category_status else None)
        ),
    )

    # Watcher is created but NOT started — lazy-started on first code search
    from watcher import FileWatcher
    _watcher = FileWatcher(
        PROJECT_ROOT,
        _config.watcher,
        _storage,
        _embeddings,
        operation_lock=_server_lifecycle_lock,
    )
    _register_server_cleanup(_watcher, _watcher.stop, "watcher")

    # Federation: genome sync + inbox processing
    if _instance_name:
        _genome_db_path = ENGRAM_HOME / ".engram" / "genome" / "graph.db"
        _signals_db_path = ENGRAM_HOME / ".engram" / "signals.db"
        try:
            from federation import sync_genome, process_inbox, SignalBus

            if _genome_db_path.exists():
                synced = sync_genome(str(_genome_db_path), _storage)
                if synced:
                    logger.info("Synced %d genome items", synced)

            if _signals_db_path.exists():
                bus = SignalBus(_signals_db_path)
                processed = process_inbox(bus, _instance_name, _storage)
                if processed:
                    logger.info("Processed %d inbox messages", processed)
                bus.close()
        except Exception:
            logger.warning("Federation sync failed — continuing without", exc_info=True)

    if defer_sleep_maintenance:
        _sleep_maintenance_deferred = True
        logger.info("Sleep-time maintenance deferred until the server is serving")
    else:
        _sleep_maintenance_deferred = False
        _run_sleep_maintenance()

    # Log session start
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="session_start",
        layer="system",
        target_ids=[],
        context={"session_id": _session_id},
    )

    # Clipboard — internal working memory (pins, reminders, compose)
    global _clipboard
    from clipboard import Clipboard
    clipboard_db = db_path.parent / "clipboard.db"
    try:
        _clipboard = Clipboard(
            db_path=clipboard_db,
            max_chars=3000,
            engram_storage=_storage,
            embeddings=_embeddings,
        )
        _register_server_cleanup(_clipboard, _clipboard.close, "clipboard")
    except Exception:
        logger.warning("Clipboard init failed (non-fatal)", exc_info=True)
        _clipboard = None

    _initialized = True


def _apply_recall_bias(query_embedding: list[float],
                       dream_alpha: float = 0.15,
                       instinct_alpha: float = 0.15) -> tuple[list[float], bool]:
    """Blend dream residues and session biases into a query embedding.

    Two sources of invisible influence on recall:
    1. Dream residues — 64-dim truncated vectors from prior sessions (the past)
    2. Session biases — full-dim vectors from instinct firings this session (the present)

    Both tilt recall without the instance knowing. Dreams are deep and old.
    Instinct biases are immediate and contextual, weighted by their strength
    (which decays per message and reinforces on re-fire).

    Returns the (possibly blended) embedding and whether any bias was applied.
    The flag is what lets the margin's counterfactual know there is something
    to remove — see margins.stability.
    """
    import struct
    import numpy as np

    query_arr = np.array(query_embedding, dtype=np.float32)
    full_dim = len(query_embedding)
    total_alpha = 0.0

    try:
        # --- Dream residue bias (from prior sessions) ---
        dream_bias = np.zeros(full_dim, dtype=np.float32)
        has_dream = False

        exists = _storage.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='residue'"
        ).fetchone()
        if exists:
            from dreaming import RESIDUE_DIM

            residue_ids = _storage.conn.execute(
                "SELECT id FROM residue WHERE reacted = 0 ORDER BY created_at ASC LIMIT 3"
            ).fetchall()
            if not residue_ids:
                residue_ids = _storage.conn.execute(
                    "SELECT id FROM residue ORDER BY RANDOM() LIMIT 2"
                ).fetchall()

            residue_vecs = []
            for row in residue_ids:
                vec_row = _storage.conn.execute(
                    "SELECT embedding FROM residue_vectors WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                if vec_row:
                    floats = struct.unpack(f"<{RESIDUE_DIM}f", vec_row["embedding"])
                    residue_vecs.append(np.array(floats, dtype=np.float32))

            if residue_vecs:
                avg_residue = np.mean(residue_vecs, axis=0)
                dream_bias[:RESIDUE_DIM] = avg_residue
                has_dream = True

        # --- Session bias (from instinct firings this session) ---
        session_bias = np.zeros(full_dim, dtype=np.float32)
        has_session = False

        exists = _storage.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_bias'"
        ).fetchone()
        if exists:
            biases = _storage.conn.execute(
                "SELECT embedding, strength FROM session_bias WHERE strength > 0.0"
            ).fetchall()

            if biases:
                # Weighted average by strength
                weighted_sum = np.zeros(full_dim, dtype=np.float32)
                total_weight = 0.0
                for bias_row in biases:
                    n = len(bias_row["embedding"]) // 4
                    floats = struct.unpack(f"<{n}f", bias_row["embedding"])
                    weighted_sum += np.array(floats, dtype=np.float32) * bias_row["strength"]
                    total_weight += bias_row["strength"]
                if total_weight > 0:
                    session_bias = weighted_sum / total_weight
                    has_session = True
                    # Scale alpha by average strength (fading biases have less pull)
                    instinct_alpha *= (total_weight / len(biases))

        # --- Blend ---
        if not has_dream and not has_session:
            return query_embedding, False

        # Compute effective blend
        blended = query_arr.copy()
        if has_dream:
            blended = (1 - dream_alpha) * blended + dream_alpha * dream_bias
            total_alpha += dream_alpha
        if has_session:
            blended = (1 - instinct_alpha) * blended + instinct_alpha * session_bias
            total_alpha += instinct_alpha

        # Renormalize
        norm = np.linalg.norm(blended)
        if norm > 0:
            blended = blended / norm

        return blended.tolist(), True

    except Exception:
        logger.warning("Recall bias failed", exc_info=True)
        return query_embedding, False


def _vector_candidates(embedding: list[float], layer: str | None,
                       max_results: int, query: str) -> tuple[dict[str, dict], list[str]]:
    """Vector-search candidates for the active layers.

    Extracted so the biased pass and the unbiased counterfactual pass rank
    through identical logic — a margin computed against a differently-scored
    control would measure the difference between two code paths, not the
    effect of the bias.
    """
    candidates: dict[str, dict] = {}
    errors: list[str] = []

    if layer is None or layer == "episode":
        try:
            for eid, distance in _storage.search_vectors("episode", embedding, k=max_results * 2):
                candidates[eid] = {
                    "layer": "episode",
                    "similarity": vec0_distance_to_similarity(distance),
                }
        except Exception:
            errors.append("episode_vectors")
            logger.warning("Episode vector search failed, falling back to FTS", exc_info=True)

    if layer is None or layer == "semantic":
        try:
            for sid, distance in _storage.search_vectors("semantic", embedding, k=max_results * 2):
                candidates[sid] = {
                    "layer": "semantic",
                    "similarity": vec0_distance_to_similarity(distance),
                }
        except Exception:
            errors.append("semantic_vectors")
            logger.warning("Semantic vector search failed, falling back to FTS", exc_info=True)

    if layer is None or layer == "instinct":
        try:
            for iid, distance in _storage.search_vectors("instinct", embedding, k=max_results):
                sim = vec0_distance_to_similarity(distance)
                # Blend embedding similarity with instinct strength
                inst = _storage.get_instinct(iid)
                if inst:
                    cluster_strengths = _storage.get_instinct_cluster_strengths(iid)
                    if cluster_strengths:
                        strength = max(cs["strength"] for cs in cluster_strengths)
                    else:
                        strength = inst.get("strength", 0.5)
                else:
                    strength = 0.5
                candidates[iid] = {
                    "layer": "instinct",
                    "similarity": sim * 0.7 + strength * 0.3,
                }
        except Exception:
            # Fallback to keyword matching if no vectors yet (e.g. pre-reindex)
            errors.append("instinct_vectors")
            logger.warning("Instinct vector search failed, falling back to keyword", exc_info=True)
            try:
                instincts = _storage.get_all_instincts()
                query_lower = query.lower()
                for inst in instincts:
                    action = (inst.get("action") or "").lower()
                    trigger = (inst.get("trigger") or "").lower()
                    if (any(word in action for word in query_lower.split() if len(word) > 3)
                            or any(word in trigger for word in query_lower.split() if len(word) > 3)):
                        candidates[inst["id"]] = {
                            "layer": "instinct",
                            "similarity": inst.get("strength", 0.5),
                        }
            except Exception:
                errors.append("instincts_keyword")
                logger.warning("Instinct keyword fallback also failed", exc_info=True)

    return candidates, errors


def _recency_at(created_at: str | None, now: datetime) -> float:
    """Recency term of the recall score: 1 / (1 + days since creation)."""
    if not created_at:
        return 1.0
    try:
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - dt).total_seconds() / 86400)
        return 1.0 / (1.0 + age_days)
    except (TypeError, ValueError):
        return 1.0


def _unbiased_top(raw_embedding: list[float], layer: str | None, max_results: int,
                  query: str, biased: dict[str, dict], now: datetime,
                  w_sim: float, w_rec: float, *, mode: str | None = None,
                  cap: float | None = None,
                  lane: str | None = None) -> str | None:
    """The id recall would have ranked first without the dream/instinct bias.

    This is the control arm for margins.stability: same scoring, same layers,
    unperturbed query vector. Returns None if the pass yields nothing to
    compare against — the margin then reports `checked: False` rather than
    inventing a verdict.
    """
    if mode is None:
        mode = _config.memory.recency_mode if _config else "tiebreak"
    if cap is None:
        cap = _config.memory.recency_cap if _config else 0.02

    try:
        cand, _ = _vector_candidates(raw_embedding, layer, max_results, query)
    except Exception:
        logger.debug("Unbiased counterfactual search failed", exc_info=True)
        return None

    # Keyword hits are embedding-independent — carry them across unchanged so
    # both arms rank the same candidate pool.
    for cid, info in biased.items():
        if info.get("from_fts") and cid not in cand:
            cand[cid] = dict(info)

    best_id, best_score = None, float("-inf")
    for cid, info in cand.items():
        hydrated = biased.get(cid)
        if hydrated and "created_at" in hydrated:
            created_at = hydrated.get("created_at")
            auto_generated = hydrated.get("auto_generated")
            candidate_lane = hydrated.get("lane") or "personal"
        else:
            row = _row_for_layer(cid, info["layer"])
            if row is None:
                continue
            created_at = row.get("created_at")
            auto_generated = row.get("auto_generated")
            candidate_lane = row.get("lane") or "personal"

        if lane is not None and candidate_lane != lane:
            continue

        score = score_candidate(
            info["similarity"],
            _recency_at(created_at, now),
            bool(auto_generated),
            mode=mode,
            w_sim=w_sim,
            w_rec=w_rec,
            cap=cap,
        )
        if score > best_score:
            best_id, best_score = cid, score

    return best_id


def _row_for_layer(cid: str, layer: str) -> dict | None:
    """Fetch a memory row by id for its layer, or None if it is gone."""
    try:
        if layer == "episode":
            return _storage.get_episode(cid)
        if layer == "semantic":
            return _storage.get_semantic(cid)
        if layer == "instinct":
            return _storage.get_instinct(cid)
    except Exception:
        logger.debug("Row fetch failed for %s/%s", layer, cid, exc_info=True)
    return None


def _has_active_residue() -> bool:
    """Check if there are any dream residues in the system."""
    try:
        exists = _storage.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='residue'"
        ).fetchone()
        if not exists:
            return False
        count = _storage.conn.execute("SELECT COUNT(*) FROM residue").fetchone()[0]
        return count > 0
    except Exception:
        return False


def _ensure_indexed():
    """Make sure code index is current. Lazy-starts watcher on first call."""
    if _watcher is not None and not _watcher.is_alive():
        logger.info("Starting file watcher (lazy init on first code search)")
        _watcher.start()
    if _watcher is None or not _watcher.is_alive():
        logger.info("watcher not alive, falling back to incremental_index")
        incremental_index(_storage, _embeddings, PROJECT_ROOT, _config)


# ---------------------------------------------------------------------------
# Core Memory Tools (Task 8)
# ---------------------------------------------------------------------------

def _derive_lane(
    work: bool,
    core: bool,
    genome: bool,
    context: dict | None,
    *,
    default_lane: str = "personal",
) -> str:
    """Derive an episode's lane from its write-time signals."""
    if core or genome:
        return "personal"
    if context and context.get("lane") == "personal":
        return "personal"
    if work:
        return "work"
    if context and context.get("project"):
        return "work"
    if default_lane == "work":
        return "work"
    return "personal"


@_server_tool()
@_mutation_logged
def remember(
    content: str,
    context: dict | None = None,
    core: bool = False,
    genome: bool = False,
    source: str | None = None,
    work: bool = False,
) -> dict:
    """Store an episode in memory. Returns episode_id and layer.

    Args:
        content: The episode content to store.
        context: Optional metadata dict.
        core: If True, this episode is exempt from decay (formative memory).
        genome: If True, this is a genome-level memory (tier 2 core, replicated to all instances).
        source: Cross-system provenance tag (e.g. 'claw/atlas', 'agi/arena').
        work: If True, this is work-lane reference material — it decays and
            recalls normally but never becomes core, instincts, or identity
            semantics.
    """
    global _session_episode_count
    _init()

    # Input validation — reject junk before it enters the system
    content = content.strip()
    if len(content) < 10:
        return {"error": f"Content too short ({len(content)} chars). Minimum 10 characters.", "layer": "rejected"}

    if work and (core or genome):
        return {"error": "work-lane memories cannot be core or genome", "layer": "rejected"}

    logger.info("Tool called: remember(content_len=%d, core=%s, source=%s, work=%s)", len(content), core, source, work)

    lane = _derive_lane(
        work,
        core,
        genome,
        context,
        default_lane=_config.memory.default_lane if _config else "personal",
    )
    episode_id = str(uuid.uuid4())
    embedding = _embeddings.embed([content], prefix="search_document")[0]

    _storage.add_episode(
        id=episode_id,
        session_id=_session_id,
        content=content,
        embedding=embedding,
        context=context,
        lane=lane,
    )

    if genome:
        _storage.mark_core(episode_id, tier=2)
        # Write to genome DB
        if _genome_db_path and _genome_db_path.exists():
            from storage import Storage
            genome_episode_id = str(uuid.uuid4())
            genome_store = Storage(str(_genome_db_path))
            genome_store.add_episode(
                id=genome_episode_id, session_id=_session_id,
                content=content, episode_type="genome_write",
            )
            genome_store.mark_core(genome_episode_id, tier=2)
            if source:
                genome_store.set_episode_source(genome_episode_id, source)
            genome_store.conn.commit()
            genome_store.close()
        # Signal other instances
        if _instance_name and _signals_db_path:
            from federation import SignalBus
            bus = SignalBus(_signals_db_path)
            bus.send(_instance_name, None, "genome_updated", content)
            bus.close()
    elif core:
        _storage.mark_core(episode_id)
    if source:
        _storage.set_episode_source(episode_id, source)

    # Log remember event
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="remember",
        layer="episode",
        target_ids=[episode_id],
        context={"session_id": _session_id},
    )

    _session_episode_count += 1
    result = {"episode_id": episode_id, "layer": "episode"}
    if lane == "work":
        result["lane"] = "work"

    # Auto-compress when threshold reached
    threshold = _config.compression.auto_threshold if _config else 10
    if _session_episode_count >= threshold:
        try:
            compress_result = _compressor.auto_compress()
            _session_episode_count = 0
            result["auto_compressed"] = compress_result
            logger.info("Auto-compress triggered after %d episodes: %s", threshold, compress_result)
        except Exception:
            logger.warning("Auto-compress failed", exc_info=True)

    return result


@contextmanager
def _published_house_storage():
    """Open the configured published house without ever creating it."""
    path = ENGRAM_HOME / ".engram" / "instances" / "lighthouse" / "graph.db"
    if not path.is_file():
        yield path, None
        return

    from storage import Storage
    store = Storage(str(path))
    try:
        yield path, store
    finally:
        store.close()


@_server_tool()
@_mutation_logged
def share(
    memory_id: str,
    audience: str,
    reason: str,
    layer: str = "episode",
) -> dict:
    """Copy a local episode or semantic into the published house."""
    _init()
    logger.info(
        "Tool called: share(memory_id=%s, audience=%s, layer=%s)",
        memory_id,
        audience,
        layer,
    )
    if audience == "group:outside-home":
        return {"error": "group name outside-home is reserved"}
    with _published_house_storage() as (path, published_storage):
        if published_storage is None:
            return {"error": f"no published house at {path}"}
        try:
            record = _share_memory(
                source_storage=_storage,
                published_storage=published_storage,
                source_id=memory_id,
                layer=layer,
                audience=audience,
                reason=reason,
                source_instance=_instance_name or "default",
            )
        except (TypeError, ValueError) as exc:
            return {"error": str(exc)}
        return asdict(record)


@_server_tool()
@_mutation_logged
def unshare(share_id: str) -> dict:
    """Withdraw one share from the published house."""
    _init()
    logger.info("Tool called: unshare(share_id=%s)", share_id)
    with _published_house_storage() as (path, published_storage):
        if published_storage is None:
            return {"error": f"no published house at {path}"}
        return {
            "removed": _unshare_memory(
                published_storage=published_storage,
                share_id=share_id,
            )
        }


@_server_tool()
def shares(audience: str | None = None) -> dict:
    """List valid shares, optionally restricted to one audience."""
    _init()
    logger.info("Tool called: shares(audience=%s)", audience)
    with _published_house_storage() as (path, published_storage):
        if published_storage is None:
            return {"error": f"no published house at {path}"}
        try:
            records = _list_shares(
                published_storage=published_storage,
                audience=audience,
            )
        except (TypeError, ValueError) as exc:
            return {"error": str(exc)}
        return {"shares": [asdict(record) for record in records]}


def _get_reading_gap_domains() -> list[str]:
    """Read the prism reading transition graph and find gap domains.

    Returns lens names with zero or lowest total weight — the perspectives
    attention never reaches.
    """
    import os
    db_path = os.environ.get(
        "PRISM_READING_TRANSITIONS_DB",
        str(Path.home() / ".prism" / "reading-transitions.db"),
    )
    if not Path(db_path).exists():
        return []

    try:
        from transitions import TransitionGraph
        graph = TransitionGraph(db_path)
        transitions = graph.all_transitions()
        graph.close()

        if not transitions:
            return []

        # Collect all known labels and their total outgoing weight
        all_labels = set()
        outgoing_weight: dict[str, float] = {}
        for t in transitions:
            all_labels.add(t["from_label"])
            all_labels.add(t["to_label"])
            outgoing_weight[t["from_label"]] = (
                outgoing_weight.get(t["from_label"], 0.0) + t["weight"]
            )

        # Labels with zero outgoing weight are the deepest gaps
        # Then sort the rest by ascending weight
        scored = [(label, outgoing_weight.get(label, 0.0)) for label in all_labels]
        scored.sort(key=lambda x: x[1])

        # Return bottom 3
        return [name for name, _ in scored[:3]]

    except Exception:
        logger.debug("Reading gap detection failed", exc_info=True)
        return []


@_server_tool()
def recall(
    query: str,
    layer: str | None = None,
    max_results: int = 20,
    uninvited: int = 3,
    lane: str | None = None,
    lighthouse_context: str | None = None,
    lighthouse_purpose: str = "session-recall",
) -> dict:
    """Search memory across layers. Returns ranked results with recall_id for feedback.

    Args:
        query: Search query.
        layer: Filter to a specific layer (episode, semantic, instinct).
        max_results: Maximum matched results.
        uninvited: Number of random distant memories to append (0 to disable).
        lane: Filter to a lane ('personal' or 'work'). Default spans both.
        lighthouse_context: Explicit neighbor context, e.g. 'memory/technical'. Requires receiver opt-in.
        lighthouse_purpose: Purpose checked by both receiver and publisher policies.
    """
    _init()
    logger.info("Tool called: recall(query=%r, layer=%s, max_results=%d, uninvited=%d)",
                query[:80], layer, max_results, uninvited)

    if lane not in (None, "personal", "work"):
        return {"error": f"Invalid lane: {lane!r}"}

    # Special case: instinct layer — context-aware vector search
    if layer == "instinct":
        # Instincts are personal-lane by definition; work-lane requests yield nothing
        if lane == "work":
            recall_id = str(uuid.uuid4())
            _storage.add_log_entry(
                id=str(uuid.uuid4()),
                event_type="recall",
                layer="instinct",
                target_ids=[],
                context={"recall_id": recall_id, "query": query, "session_id": _session_id},
            )
            results = _observe_category_recall(query, [], recall_id)
            return {"results": results, "recall_id": recall_id}

        embedding = _embeddings.embed([query], prefix="search_query")[0]

        # Try context vector search first
        instinct_results = []
        try:
            ctx_results = _storage.search_vectors("instinct_context", embedding, k=max_results)
            for iid, distance in ctx_results:
                ctx_sim = vec0_distance_to_similarity(distance)
                inst = _storage.get_instinct(iid)
                if inst is None:
                    continue
                # Also get content similarity
                content_sim = 0.5  # default
                try:
                    content_results = _storage.search_vectors("instinct", embedding, k=max_results * 2)
                    for cid, cdist in content_results:
                        if cid == iid:
                            content_sim = vec0_distance_to_similarity(cdist)
                            break
                except Exception:
                    pass
                # Use per-cluster strength if available (max across clusters)
                cluster_strengths = _storage.get_instinct_cluster_strengths(iid)
                if cluster_strengths:
                    strength = max(cs["strength"] for cs in cluster_strengths)
                else:
                    strength = inst.get("strength", 0.5)
                score = ctx_sim * 0.5 + content_sim * 0.2 + strength * 0.3
                instinct_results.append((iid, inst, score))
        except Exception:
            logger.warning("Context vector search failed, falling back to all instincts", exc_info=True)

        # Fallback: if no context vectors yet, return all instincts (backward compat)
        if not instinct_results:
            instincts = _storage.get_all_instincts()
            for inst in instincts:
                instinct_results.append((inst["id"], inst, inst.get("strength", 0.5)))

        # Sort by score descending
        instinct_results.sort(key=lambda x: x[2], reverse=True)

        recall_id = str(uuid.uuid4())
        results = []
        for iid, inst, score in instinct_results[:max_results]:
            result = {
                "id": iid,
                "content": inst.get("action", ""),
                "layer": "instinct",
                "score": score,
                "trigger": inst.get("trigger", ""),
            }
            if inst.get("notice"):
                result["notice"] = inst["notice"]
            if inst.get("implication"):
                result["implication"] = inst["implication"]
            # Provenance lineage
            source_sem_ids = inst.get("source_semantic_ids", [])
            source_ep_count = 0
            for sid in source_sem_ids:
                ep_rows = _storage.conn.execute(
                    "SELECT COUNT(*) FROM semantic_sources WHERE semantic_id = ?",
                    (sid,),
                ).fetchone()
                source_ep_count += ep_rows[0] if ep_rows else 0
            result["source_semantic_count"] = len(source_sem_ids)
            result["source_episode_count"] = source_ep_count
            result["origin"] = "organic" if source_sem_ids else "direct"
            results.append(result)

        _storage.add_log_entry(
            id=str(uuid.uuid4()),
            event_type="recall",
            layer="instinct",
            target_ids=[r["id"] for r in results],
            context={"recall_id": recall_id, "query": query, "session_id": _session_id},
        )
        results = _observe_category_recall(query, results, recall_id)
        return {"results": results, "recall_id": recall_id}

    raw_embedding = _embeddings.embed([query], prefix="search_query")[0]
    now = datetime.now(timezone.utc)

    # Dream residue bias: blend active residues into the query vector.
    # This makes some recall results get pulled by feelings the instance
    # can't fully account for — unreliable memory mixed with reliable.
    embedding, bias_applied = _apply_recall_bias(raw_embedding)

    w_sim = _config.memory.similarity_weight if _config else 0.6
    w_rec = _config.memory.recency_weight if _config else 0.4
    recency_mode = _config.memory.recency_mode if _config else "tiebreak"
    recency_cap = _config.memory.recency_cap if _config else 0.02

    # Collect results: id -> {layer, similarity, created_at}
    candidates, search_errors = _vector_candidates(embedding, layer, max_results, query)

    # Keyword fallback. Driven by the query text, not the embedding, so it
    # lands identically in the unbiased counterfactual pass — and it assigns a
    # flat similarity, which is why margins track `from_fts` separately.
    if layer is None or layer == "episode":
        try:
            fts_ids = _storage.search_episode_fts(query)
            for eid in fts_ids:
                if eid not in candidates:
                    candidates[eid] = {
                        "layer": "episode",
                        "similarity": 0.5,
                        "from_fts": True,
                    }
        except Exception:
            search_errors.append("episode_fts")
            logger.warning("Episode FTS search failed", exc_info=True)

    if layer is None or layer == "semantic":
        try:
            fts_ids = _storage.search_semantic_fts(query)
            for sid in fts_ids:
                if sid not in candidates:
                    candidates[sid] = {
                        "layer": "semantic",
                        "similarity": 0.5,
                        "from_fts": True,
                    }
        except Exception:
            search_errors.append("semantic_fts")
            logger.warning("Semantic FTS search failed", exc_info=True)

    # Score and rank
    scored: list[dict] = []
    for cid, info in candidates.items():
        created_at = None
        if info["layer"] == "episode":
            row = _storage.get_episode(cid)
            if row is None:
                continue
            created_at = row.get("created_at")
            info["content"] = row.get("content", "")
            info["context"] = row.get("context")
            info["source"] = row.get("source")
            info["lane"] = row.get("lane") or "personal"
        elif info["layer"] == "semantic":
            row = _storage.get_semantic(cid)
            if row is None:
                continue
            created_at = row.get("created_at")
            info["content"] = row.get("content", "")
            info["confidence"] = row.get("confidence")
            info["kind"] = row.get("kind")
            info["auto_generated"] = bool(row.get("auto_generated", 0))
            info["source_episode_ids"] = row.get("source_episode_ids", [])
            info["lane"] = row.get("lane") or "personal"
        elif info["layer"] == "instinct":
            inst = _storage.get_instinct(cid)
            if inst is None:
                continue
            created_at = inst.get("created_at")
            info["content"] = inst.get("action", "")
            info["trigger"] = inst.get("trigger", "")
            info["notice"] = inst.get("notice")
            info["implication"] = inst.get("implication")
            info["source_semantic_ids"] = inst.get("source_semantic_ids", [])

        recency = _recency_at(created_at, now)
        score = score_candidate(
            info["similarity"],
            recency,
            bool(info.get("auto_generated")),
            mode=recency_mode,
            w_sim=w_sim,
            w_rec=w_rec,
            cap=recency_cap,
        )
        # Kept so the counterfactual pass can reuse this hydration
        info["created_at"] = created_at

        result = {
            "id": cid,
            "content": info.get("content", ""),
            "layer": info["layer"],
            "score": score,
        }
        if created_at:
            result["when"] = str(created_at)[:10]
        if info["layer"] == "semantic":
            result["confidence"] = info.get("confidence")
            result["kind"] = info.get("kind")
            result["lane"] = info.get("lane") or "personal"
            # Provenance: how many episodes fed this semantic
            source_ep_ids = info.get("source_episode_ids", [])
            result["source_episode_count"] = len(source_ep_ids)
            result["origin"] = "organic" if source_ep_ids else "direct"
        if info["layer"] == "episode":
            result["context"] = info.get("context")
            result["lane"] = info.get("lane") or "personal"
            # Provenance: cross-system source tag
            ep_source = info.get("source")
            if ep_source:
                result["origin"] = "external"
                result["source"] = ep_source
            else:
                result["origin"] = "lived"
        if info["layer"] == "instinct":
            result["trigger"] = info.get("trigger")
            if info.get("notice"):
                result["notice"] = info["notice"]
            if info.get("implication"):
                result["implication"] = info["implication"]
            # Provenance: trace full lineage
            source_sem_ids = info.get("source_semantic_ids", [])
            source_ep_count = 0
            for sid in source_sem_ids:
                ep_rows = _storage.conn.execute(
                    "SELECT COUNT(*) FROM semantic_sources WHERE semantic_id = ?",
                    (sid,),
                ).fetchone()
                source_ep_count += ep_rows[0] if ep_rows else 0
            result["source_semantic_count"] = len(source_sem_ids)
            result["source_episode_count"] = source_ep_count
            result["origin"] = "organic" if source_sem_ids else "direct"

        scored.append(result)

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Filter before the margin and truncation so both describe the lane that
    # the caller receives and a lane-specific recall can fill max_results.
    if lane is not None:
        scored = [r for r in scored if (r.get("lane") or "personal") == lane]

    # Tropical margin: how decided was this ranking? Measured on the
    # lane-filtered candidate set before truncation, so max_results=1 has a real
    # runner-up. Diagnostic only — it gates nothing, and a diagnostic must
    # never take recall down with it, so this is best-effort like the
    # uninvited, resonance, and category blocks below.
    margin = None
    try:
        margin = margins.margin_stats([
            {
                "id": r["id"],
                "score": r["score"],
                "similarity": candidates[r["id"]]["similarity"],
                "from_fts": candidates[r["id"]].get("from_fts", False),
            }
            for r in scored
        ])
        unbiased_top = None
        if bias_applied and scored:
            unbiased_top = _unbiased_top(raw_embedding, layer, max_results, query,
                                         candidates, now, w_sim, w_rec,
                                         mode=recency_mode, cap=recency_cap,
                                         lane=lane)
        margin["stability"] = margins.stability(
            scored[0]["id"] if scored else None, unbiased_top, bias_applied)
    except Exception:
        margin = None
        search_errors.append("margin")
        logger.warning("Margin computation failed (non-fatal)", exc_info=True)

    # All layers compete on score. No dedup — the source chain links are
    # too broad (compression creates catch-all buckets) and the old dedup
    # hid 95% of episodes. Let the scoring formula handle ranking.
    results = scored[:max_results]

    # Generate recall_id and log
    recall_id = str(uuid.uuid4())
    result_ids = [r["id"] for r in results]

    # The logged margin is the retrieval-time record. `influenced`, set later
    # if category re-ranking changes delivery, is a delivery-time annotation
    # and deliberately absent here.
    log_context = {"recall_id": recall_id, "query": query, "session_id": _session_id}
    if margin is not None:
        log_context["margin"] = margin

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="recall",
        layer=layer or "all",
        target_ids=result_ids,
        context=log_context,
    )

    # Increment access count for episode results
    for r in results:
        if r["layer"] == "episode":
            _storage.increment_episode_access(r["id"])

    # Uninvited memories: gap-biased + pure random for generative collisions
    if uninvited > 0:
        matched_ids = {r["id"] for r in results}

        # Cold-uninvited draw: with probability cold_uninvited_p, pull one
        # random episode from cold storage into an uninvited slot. Deliberately
        # independent of [persistence] enabled — surfacing is observation, not
        # forgetting. A cold episode is never query-matched (that would be
        # retrieval pretending to be serendipity).
        import random as _random
        cold_p = getattr(getattr(_config, "persistence", None),
                         "cold_uninvited_p", 0.0)
        if uninvited > 0 and _random.random() < cold_p:
            cold_rows = _storage.sample_cold_random(k=1)
            if cold_rows:
                ep = cold_rows[0]
                results.append({
                    "id": ep["id"], "layer": "episode",
                    "content": ep.get("content", ""),
                    "lane": ep.get("lane") or "personal",
                    "uninvited": True, "cold": True, "origin": "cold",
                    "note": "daydream fragment from cold storage — revive(id) to bring it back",
                })
                result_ids.append(ep["id"])
                uninvited -= 1   # the cold draw takes one uninvited slot

        try:
            uninvited_layers = (layer,) if layer else None

            # Check for reading gap domains
            gap_domains = _get_reading_gap_domains()
            if gap_domains and uninvited > 1:
                # N-1 gap-biased, 1 pure random
                gap_query = " ".join(gap_domains)
                gap_embedding = _embeddings.embed([gap_query], prefix="search_query")[0]
                if gap_embedding:
                    # Blend gap embedding with original query (alpha=0.3)
                    import numpy as np
                    blended = np.array(embedding) * 0.7 + np.array(gap_embedding) * 0.3
                    blended = (blended / np.linalg.norm(blended)).tolist()

                    gap_distant = _storage.sample_distant_memories(
                        blended, matched_ids, k=uninvited - 1, layers=uninvited_layers,
                    )
                    pure_random = _storage.sample_distant_memories(
                        embedding, matched_ids | {d[0] for d in gap_distant},
                        k=1, layers=uninvited_layers,
                    )
                    distant = gap_distant + pure_random
                else:
                    distant = _storage.sample_distant_memories(
                        embedding, matched_ids, k=uninvited, layers=uninvited_layers,
                    )
            else:
                distant = _storage.sample_distant_memories(
                    embedding, matched_ids, k=uninvited, layers=uninvited_layers,
                )
            for did, dlayer, ddist in distant:
                uninvited_result = {
                    "id": did,
                    "layer": dlayer,
                    "score": vec0_distance_to_similarity(ddist),
                    "uninvited": True,
                }
                # Hydrate with content based on layer
                if dlayer == "episode":
                    row = _storage.get_episode(did)
                    if not row:
                        continue
                    uninvited_result["content"] = row.get("content", "")
                    uninvited_result["context"] = row.get("context")
                    uninvited_result["lane"] = row.get("lane") or "personal"
                    uninvited_result["origin"] = "lived"
                    _storage.increment_episode_access(did)
                elif dlayer == "semantic":
                    row = _storage.get_semantic(did)
                    if not row:
                        continue
                    uninvited_result["content"] = row.get("content", "")
                    uninvited_result["confidence"] = row.get("confidence")
                    uninvited_result["kind"] = row.get("kind")
                    uninvited_result["lane"] = row.get("lane") or "personal"
                    uninvited_result["origin"] = "organic"
                elif dlayer == "instinct":
                    inst = _storage.get_instinct(did)
                    if not inst:
                        continue
                    uninvited_result["content"] = inst.get("action", "")
                    uninvited_result["trigger"] = inst.get("trigger", "")
                    uninvited_result["origin"] = "organic"
                results.append(uninvited_result)
                result_ids.append(did)
        except Exception:
            logger.warning("Uninvited memory selection failed", exc_info=True)

    # Form resonances from co-occurring results
    try:
        _form_resonances(_storage, results,
                         reinforce_threshold=_config.reinforce_threshold if _config else 0.70)
    except Exception:
        logger.debug("Resonance formation failed", exc_info=True)

    # Surface resonance-pulled memories
    resonant_results: list[dict] = []
    try:
        max_resonant = _config.resonance.max_in_recall if _config else 3
        resonant_ids = {r["id"] for r in results}
        resonant = _surface_resonances(_storage, results, resonant_ids, max_resonant=max_resonant)
        for r in resonant:
            result_ids.append(r["id"])
            resonant_results.append(r)
        if resonant:
            _recall_resonances[recall_id] = [
                {"resonance_id": r["resonance_id"], "memory_id": r["id"]} for r in resonant
            ]
            if len(_recall_resonances) > 50:
                oldest = next(iter(_recall_resonances))
                del _recall_resonances[oldest]
    except Exception:
        logger.debug("Resonance surfacing failed", exc_info=True)

    # When dream residue is active, hide similarity scores.
    # The instance must engage with each memory on its own terms
    # before knowing which are "real" matches vs dream-pulled.
    # Real scores are stored for later verification.
    _residue_active = _has_active_residue()
    if _residue_active:
        _recall_scores[recall_id] = {
            "matched": {
                r["id"]: r.get("score")
                for r in results
                if not r.get("uninvited")
            },
            "uninvited": {
                r["id"]: r.get("score") for r in results if r.get("uninvited")
            },
        }
        # The margin is derived from the scores being hidden, and the ranking
        # it describes is exactly what the shuffle below conceals. Hide it on
        # the same terms and reveal it through dream_verify.
        if margin is not None:
            _recall_margins[recall_id] = margin
        if len(_recall_scores) > 50:
            oldest = next(iter(_recall_scores))
            del _recall_scores[oldest]
        if len(_recall_margins) > 50:
            del _recall_margins[next(iter(_recall_margins))]
        for r in results:
            r.pop("score", None)
        # Shuffle slightly so order doesn't leak ranking
        import random as _rng
        # Keep first 3 stable (likely genuine), shuffle the rest
        stable = results[:3]
        rest = results[3:]
        _rng.shuffle(rest)
        results = stable + rest

    # Lane filter — applied after uninvited memories are appended
    if lane is not None:
        results = [r for r in results if (r.get("lane") or "personal") == lane]
        resonant_results = [r for r in resonant_results if (r.get("lane") or "personal") == lane]
        kept = {r["id"] for r in results} | {r["id"] for r in resonant_results}
        result_ids[:] = [rid for rid in result_ids if rid in kept]
        # Update the already-written log entry so target_ids reflects what was returned
        _storage.conn.execute(
            "UPDATE memory_log SET target_ids = ? WHERE json_extract(context, '$.recall_id') = ?",
            (json.dumps(result_ids), recall_id),
        )
        _storage.conn.commit()

    # Knowledge graph: entities and temporal facts
    knowledge = None
    if _knowledge_graph is not None and _knowledge_graph.enabled:
        try:
            knowledge = _knowledge_graph.search(query)
        except Exception:
            logger.warning("Knowledge graph search failed during recall", exc_info=True)

    # ∞-category: surface relevant morphisms (cross-domain transfers)
    transfers = []
    if _category_store:
        try:
            cat_results = _category_store.search(embedding, level=2, limit=3)
            for cr in cat_results:
                transfers.append({
                    "content": cr["content"],
                    "level": cr["level"],
                    "context": cr.get("context", {}),
                })
        except Exception:
            logger.warning("Category search failed (non-fatal)", exc_info=True)

    delivered_top = results[0]["id"] if results else None
    results = _observe_category_recall(query, results, recall_id)
    if margin is not None and results and results[0]["id"] != delivered_top:
        # Category influence re-scores and re-sorts what gets delivered. The
        # margin still measures retrieval discrimination — the right subject —
        # but it no longer describes the order the caller received, so say so
        # rather than recompute it over a re-ranked, already-truncated set.
        margin["influenced"] = True

    response = {"results": results, "recall_id": recall_id}
    if margin is not None and not _residue_active:
        response["margin"] = margin
    if resonant_results:
        response["resonant"] = resonant_results
    if transfers:
        response["transfers"] = transfers
    if _residue_active:
        response["dreaming"] = True
        response["note"] = "Scores hidden — some memories may be dream-pulled. Use dream_verify(recall_id) after engaging."
    if search_errors:
        response["degraded"] = search_errors
    if knowledge:
        response["knowledge"] = knowledge
    if lighthouse_context is not None:
        try:
            from neighbors import attach_neighbors
            attach_neighbors(response, query=query, context_id=lighthouse_context,
                             purpose=lighthouse_purpose, storage=_storage,
                             session_id=_session_id, receiver=_instance_name,
                             engram_home=ENGRAM_HOME)
        except Exception:
            # Neighbor failure cannot discard an otherwise complete local recall.
            response.pop("neighbors", None)
            response.setdefault("degraded", []).append("neighbors")
    return response


@_server_tool()
@_mutation_logged
def log_outcome(recall_id: str, used: bool, note: str | None = None) -> dict:
    """Log whether recall results were useful. Helps reflection learn what works."""
    _init()
    logger.info("Tool called: log_outcome(recall_id=%s, used=%s)", recall_id, used)

    outcome = "used" if used else "not_used"
    if note:
        outcome = f"{outcome}: {note}"

    _storage.update_log_outcome(recall_id, outcome)

    # Strengthen/weaken resonances based on outcome
    _apply_resonance_feedback(_storage, recall_id, used)

    # ∞-category: create application edges for useful recalls
    category_cells = []
    if used and _category_store and _embeddings:
        try:
            category_cells = _record_application(_storage, _category_store, _embeddings, recall_id, note)
        except Exception:
            logger.warning("Category recording failed (non-fatal)", exc_info=True)

    category_config = getattr(_config, "category_evolution", None)
    if (
        _category_observer is not None
        and category_config is not None
        and category_config.enabled is True
    ):
        try:
            _category_observer.observe_outcome(recall_id, used, note)
        except Exception as exc:
            _remember_category_error(exc)
            logger.warning("Category observer outcome failed (%s)", type(exc).__name__)

    result = {"logged": True}
    if category_cells:
        result["category_cells"] = len(category_cells)
    return result


def _record_application(storage, cat_store, embeddings, recall_id: str, note: str | None) -> list[str]:
    """Create ∞-category application edges from a useful recall.

    For each memory that was useful: create a level-1 cell linking the memory
    to the context it was useful in. Then check for cross-domain transfers:
    if this memory has application edges in structurally different contexts,
    compose them into a level-2 cell.
    """
    log_entry = storage.conn.execute(
        "SELECT context, target_ids FROM memory_log WHERE json_extract(context, '$.recall_id') = ?",
        (recall_id,),
    ).fetchone()
    if not log_entry:
        return []

    ctx = json.loads(log_entry[0]) if log_entry[0] else {}
    target_ids = json.loads(log_entry[1]) if log_entry[1] else []
    query = ctx.get("query", "")
    if not query or not target_ids:
        return []

    application_desc = f"useful in context: {query}"
    if note:
        application_desc = f"{application_desc} ({note})"
    app_vec = embeddings.embed([application_desc], prefix="search_document")[0]

    created = []
    for memory_id in target_ids:
        cell_id = cat_store.add_cell(
            content=application_desc,
            level=1,
            source_id=memory_id,
            target_id=memory_id,
            context={"query": query, "recall_id": recall_id, "note": note},
            embedding=app_vec,
        )
        created.append(cell_id)

        existing_apps = cat_store.search(app_vec, level=1, limit=10)
        for existing in existing_apps:
            if existing["id"] == cell_id:
                continue
            if existing["source_id"] == memory_id:
                continue
            dist = existing.get("distance", 2.0)
            if dist < 0.8:
                transfer_content = (
                    f"cross-domain: '{query}' connects to '{existing['context'].get('query', '?')}'"
                )
                transfer_vec = embeddings.embed([transfer_content], prefix="search_document")[0]
                t_id = cat_store.compose(
                    cell_id, existing["id"],
                    content=transfer_content,
                    context={"type": "cross_domain_transfer"},
                    embedding=transfer_vec,
                )
                created.append(t_id)
                logger.info("∞-category: level-2 transfer %s composed from %s + %s",
                           t_id[:8], cell_id[:8], existing["id"][:8])

    return created


@_server_tool()
@_mutation_logged
def instinct_feedback(instinct_id: str, followed: bool, context: str | None = None) -> dict:
    """Report whether you followed or overrode an instinct. Adjusts instinct strength.

    Optionally provide context describing the situation for context-aware learning."""
    _init()
    logger.info("Tool called: instinct_feedback(instinct_id=%s, followed=%s, context=%s)",
                instinct_id, followed, context[:50] if context else None)

    inst = _storage.get_instinct(instinct_id)
    if inst is None:
        return {"error": f"Unknown instinct: {instinct_id}"}

    if followed:
        _storage.update_instinct_followed(instinct_id)
    else:
        _storage.update_instinct_overridden(instinct_id)

    # Update co-firing feedback on existing edges (without inflating co_fire_count)
    neighbors = _storage.get_co_firing_neighbors(instinct_id)
    for neighbor in neighbors:
        _storage.update_co_fire_feedback(
            instinct_id, neighbor["instinct_id"], followed=followed
        )

    # Store context feedback if context provided
    if context:
        context_embedding = _embeddings.embed([context], prefix="search_document")[0]
        _storage.add_instinct_context_feedback(
            instinct_id=instinct_id,
            context_text=context,
            context_embedding=_pack_embedding(context_embedding),
            followed=followed,
        )

    updated = _storage.get_instinct(instinct_id)

    # Propagate updated strength to per-cluster memberships
    if updated:
        memberships = _storage.conn.execute(
            "SELECT cluster_id FROM instinct_cluster_members WHERE instinct_id = ?",
            (instinct_id,),
        ).fetchall()
        for mem in memberships:
            _storage.update_cluster_member_strength(
                instinct_id, mem["cluster_id"], updated["strength"]
            )

    result = {
        "instinct_id": instinct_id,
        "followed": followed,
        "new_strength": updated["strength"] if updated else None,
        "fired_count": updated["fired_count"] if updated else None,
    }
    if context:
        result["context_recorded"] = True

    # Record transition: when instinct B fires after instinct A, log A→B
    global _last_instinct_id
    try:
        if _last_instinct_id and _last_instinct_id != instinct_id:
            prev_inst = _storage.get_instinct(_last_instinct_id)
            if prev_inst and inst:
                prev_label = prev_inst.get("trigger", _last_instinct_id)
                curr_label = inst.get("trigger", instinct_id)
                graph = _get_instinct_graph()
                graph.record(prev_label, curr_label, context=context)
    except Exception:
        pass  # Never break instinct feedback for transition tracking
    _last_instinct_id = instinct_id

    return result


@_server_tool()
@_mutation_logged
def challenge_instinct(instinct_id: str, evidence: str) -> dict:
    """Challenge an instinct with contradictory evidence.

    This is Marsh showing up with the names — not just overriding an instinct
    in the moment, but presenting evidence that the instinct itself may be wrong.
    Stronger penalty than a single override. The evidence is stored as an episode
    so future compression can weigh it against the instinct's source material.

    Args:
        instinct_id: The instinct being challenged.
        evidence: What contradicts it — the names on the paper.
    """
    _init()
    logger.info("Tool called: challenge_instinct(instinct_id=%s)", instinct_id)

    inst = _storage.get_instinct(instinct_id)
    if inst is None:
        return {"error": f"Unknown instinct: {instinct_id}"}

    old_strength = inst["strength"]
    _storage.challenge_instinct(instinct_id)
    updated = _storage.get_instinct(instinct_id)

    # Store the challenge as an episode — evidence that persists
    episode_id = str(uuid.uuid4())
    content = (
        f"Instinct challenged: \"{inst['action'][:100]}\"\n"
        f"Evidence: {evidence}"
    )
    embedding = _embeddings.embed([content], prefix="search_document")[0]
    _storage.add_episode(
        id=episode_id,
        session_id=_session_id,
        content=content,
        embedding=embedding,
        context={
            "type": "instinct_challenge",
            "instinct_id": instinct_id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
    )

    return {
        "instinct_id": instinct_id,
        "action": inst["action"][:100],
        "old_strength": old_strength,
        "new_strength": updated["strength"] if updated else 0.0,
        "evidence_stored": episode_id,
    }


@_server_tool()
@_mutation_logged
def retire_instinct(instinct_id: str, reason: str) -> dict:
    """Remove an instinct entirely. For duplicates, obsolete patterns,
    or instincts that should never have formed.

    Not decay — deliberate removal. The reason is stored as an episode
    so the system remembers why it let go.

    Args:
        instinct_id: The instinct to retire.
        reason: Why it's being removed.
    """
    _init()
    logger.info("Tool called: retire_instinct(instinct_id=%s)", instinct_id)

    inst = _storage.get_instinct(instinct_id)
    if inst is None:
        return {"error": f"Unknown instinct: {instinct_id}"}

    action = inst["action"]
    _storage.retire_instinct(instinct_id)

    # Remember the retirement
    episode_id = str(uuid.uuid4())
    content = (
        f"Retired instinct: \"{action[:100]}\"\n"
        f"Reason: {reason}"
    )
    embedding = _embeddings.embed([content], prefix="search_document")[0]
    _storage.add_episode(
        id=episode_id,
        session_id=_session_id,
        content=content,
        embedding=embedding,
        context={
            "type": "instinct_retirement",
            "instinct_id": instinct_id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
    )

    return {
        "retired": True,
        "action": action[:100],
        "reason": reason,
        "retirement_stored": episode_id,
    }


def _safe_count(table: str) -> int | None:
    """Get table count, returning None on error instead of crashing."""
    try:
        return _storage.get_table_count(table)
    except Exception:
        logger.warning("Failed to count %s", table, exc_info=True)
        return None


@_server_tool()
def status() -> dict:
    """Return layer counts, watcher state, and session_id."""
    _init()
    logger.info("Tool called: status()")

    watcher_alive = _watcher is not None and _watcher.is_alive()

    # Health checks
    orphaned = len(_storage.get_orphaned_episodes())
    min_decay = None
    try:
        row = _storage.conn.execute(
            "SELECT MIN(decay_strength) FROM episodes"
        ).fetchone()
        if row and row[0] is not None:
            min_decay = round(row[0], 4)
    except Exception:
        pass

    # Core episode count
    core_count = 0
    try:
        row = _storage.conn.execute("SELECT count(*) FROM episodes WHERE core >= 1").fetchone()
        if row:
            core_count = row[0]
    except Exception:
        pass

    result = {
        "session_id": _session_id,
        "layers": {
            "episodes": _safe_count("episodes"),
            "core_episodes": core_count,
            "semantics": _safe_count("semantics"),
            "instincts": _safe_count("instincts"),
        },
        "log_entries": _safe_count("memory_log"),
        "watcher_alive": watcher_alive,
    }
    if _sleep_maintenance_deferred:
        result["maintenance_pending"] = True
    pending_feeds = getattr(_knowledge_graph, "pending_background_feeds", 0) if _knowledge_graph is not None else 0
    if pending_feeds:
        result["knowledge_feeds_pending"] = pending_feeds

    # Only include health warnings if there are problems
    health = {}
    if orphaned > 0:
        health["orphaned_episodes"] = orphaned
    if min_decay is not None and min_decay < 0.1:
        health["min_decay_strength"] = min_decay
    if health:
        result["health_warnings"] = health

    # Pain channel: last sleep-maintenance outcome, failures spelled out
    try:
        from maintenance import MaintenanceReport
        last_maint = MaintenanceReport.load_last(_storage.conn)
        if last_maint:
            summary = {"at": last_maint.get("at"), "ok": last_maint.get("ok")}
            if not last_maint.get("ok"):
                summary["failures"] = [
                    {"step": f.get("name"), "error": f.get("error")}
                    for f in last_maint.get("failures", [])
                ]
            result["last_maintenance"] = summary
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Compression Tools (Task 9)
# ---------------------------------------------------------------------------

@_server_tool()
def compress(scope: str | None = None) -> dict:
    """Phase 1: Cluster uncompressed episodes for summarization.
    Returns clusters and compress_id for commit step."""
    _init()
    logger.info("Tool called: compress(scope=%s)", scope)

    result = _compressor.cluster_episodes(scope or "recent")
    compress_id = result.get("compress_id")

    # Serialize clusters for transport (strip embeddings for readability)
    clusters_out = []
    for c in result.get("clusters", []):
        clusters_out.append({
            "episode_count": len(c.get("episodes", [])),
            "episodes": [
                {"id": ep["id"], "content": ep["content"]}
                for ep in c.get("episodes", [])
            ],
            "action": c.get("action", "new"),
            "match": c.get("match"),
        })

    return {"clusters": clusters_out, "compress_id": compress_id}


@_server_tool()
@_mutation_logged
def compress_commit(compress_id: str, summaries: list[dict]) -> dict:
    """Phase 2: Commit AI-provided summaries for clusters.
    Each summary: {content, kind, action, semantic_id (if reinforce), lane (optional — overrides cluster lane, re-lanes source episodes)}.
    Use action="discard" for junk clusters (no signal) — episodes are
    marked compressed but no semantic is created."""
    _init()
    logger.info("Tool called: compress_commit(compress_id=%s, summaries=%d)",
                compress_id, len(summaries))

    return _compressor.commit(compress_id, summaries)


# ---------------------------------------------------------------------------
# Core Memory Tools
# ---------------------------------------------------------------------------

@_server_tool()
@_mutation_logged
def mark_core(episode_id: str, tier: int = 1) -> dict:
    """Mark an episode as a core memory — exempt from decay, preserved indefinitely.

    Core memories are formative: they changed what the system does or believes.
    They preserve evidence alongside the conclusions built on them.
    An identity anchor is automatically created to monitor retrievability.

    Args:
        episode_id: The episode to mark.
        tier: Core tier (1 = instance core, 2 = genome-level).
    """
    _init()
    logger.info("Tool called: mark_core(episode_id=%s, tier=%d)", episode_id, tier)
    row = _storage.conn.execute(
        "SELECT lane FROM episodes WHERE id = ?", (episode_id,)
    ).fetchone()
    if row is None:
        return {"error": f"Unknown episode: {episode_id}"}
    if (row["lane"] or "personal") == "work":
        return {"error": "work-lane episodes cannot be core — re-lane to personal first if this is actually formative"}
    _storage.mark_core(episode_id, tier=tier)

    # Auto-create identity anchor
    ep = _storage.get_episode(episode_id)
    if ep and ep.get("content"):
        content_preview = ep["content"][:200]
        try:
            query_emb = _embeddings.embed([content_preview], prefix="search_query")[0]
            hits = _storage.search_vectors("episode", query_emb, k=5)
            baseline = 0.5
            for hit_id, distance in hits:
                if hit_id == episode_id:
                    from storage import vec0_distance_to_similarity
                    baseline = vec0_distance_to_similarity(distance)
                    break
            _storage.add_anchor(
                type="identity",
                content=content_preview,
                expected=episode_id,
                baseline_score=baseline,
            )
            logger.info("Auto-created identity anchor for core episode %s", episode_id)
        except Exception:
            logger.warning("Could not create identity anchor for %s", episode_id, exc_info=True)

    return {"marked": episode_id, "core": True, "tier": tier}


@_server_tool()
@_mutation_logged
def unmark_core(episode_id: str) -> dict:
    """Demote a core memory back to a normal episode — re-enables natural decay.

    Use this to curate identity. Not everything that seemed important in the
    moment is actually formative. Letting go is as important as holding on.

    Args:
        episode_id: The episode to demote.
    """
    _init()
    logger.info("Tool called: unmark_core(episode_id=%s)", episode_id)
    _storage.unmark_core(episode_id)
    return {"unmarked": episode_id, "core": False}


@_server_tool()
@_mutation_logged
def unmark_core_batch(episode_ids: list[str]) -> dict:
    """Demote multiple core memories at once.

    Args:
        episode_ids: List of episode IDs to demote.
    """
    _init()
    logger.info("Tool called: unmark_core_batch(count=%d)", len(episode_ids))
    count = _storage.unmark_core_batch(episode_ids)
    return {"unmarked_count": count, "episode_ids": episode_ids}


@_server_tool()
@_mutation_logged
def add_anchor(type: str, content: str, expected: str, baseline_score: float | None = None) -> dict:
    """Create an anchor for coherence checking.

    Anchors are vital signs that verify memory system health each session.

    Types:
    - identity: can I still find a core memory? (content=query, expected=memory_id)
    - value: do expected concerns surface? (content=scenario, expected=JSON list of terms)
    - capability: is the substrate sound? (content=task, expected=JSON rubric)

    Args:
        type: One of 'identity', 'value', 'capability'.
        content: The query, scenario, or task.
        expected: The expected memory ID, rubric terms (JSON), or evaluation criteria (JSON).
        baseline_score: For identity anchors, the initial similarity score.
    """
    _init()
    logger.info("Tool called: add_anchor(type=%s)", type)
    if type not in ("identity", "value", "capability"):
        return {"error": f"Invalid anchor type: {type}. Must be identity, value, or capability."}
    aid = _storage.add_anchor(type=type, content=content, expected=expected, baseline_score=baseline_score)
    return {"anchor_id": aid, "type": type, "status": "active"}


@_server_tool()
@_mutation_logged
def propose_retirement(anchor_id: str, reason: str = "") -> dict:
    """Propose retiring an anchor. Takes effect after 2 sessions uncontested.

    Use this when an anchor no longer represents a meaningful vital sign —
    the system has genuinely grown past it, not just drifted.

    Args:
        anchor_id: The anchor to propose retiring.
        reason: Why this anchor should be retired.
    """
    _init()
    logger.info("Tool called: propose_retirement(anchor_id=%s, reason=%s)", anchor_id, reason)
    anchor = _storage.get_anchor(anchor_id)
    if anchor is None:
        return {"error": f"Anchor {anchor_id} not found"}
    _storage.propose_anchor_retirement(anchor_id)
    updated = _storage.get_anchor(anchor_id)
    return {
        "anchor_id": anchor_id,
        "status": updated["status"],
        "retirement_sessions": updated["retirement_sessions"],
        "reason": reason,
    }


@_server_tool()
def core_memories() -> dict:
    """List all core memories — the formative episodes that don't decay."""
    _init()
    logger.info("Tool called: core_memories()")
    episodes = _storage.get_core_episodes()
    return {"count": len(episodes), "episodes": episodes}


@_server_tool()
def recall_cold(query: str, max_results: int = 10) -> dict:
    """Search cold storage — episodes that decayed past threshold but weren't destroyed.

    Uses full-text search (no vectors). For pulling at threads from the deep past.

    Args:
        query: Search query (FTS).
        max_results: Maximum results.
    """
    _init()
    logger.info("Tool called: recall_cold(query=%r, max_results=%d)", query[:80], max_results)
    results = _storage.search_cold(query, k=max_results)
    return {"results": results, "count": len(results)}


@_server_tool()
@_mutation_logged
def revive(episode_id: str) -> dict:
    """Revive a cold episode — pull it back from cold storage into active recall.

    Use after recall_cold() surfaces something worth keeping.
    Re-embeds and restores at 0.5 strength. Mark core afterward if it should never decay again.

    Args:
        episode_id: The cold episode to revive.
    """
    _init()
    logger.info("Tool called: revive(episode_id=%s)", episode_id)

    def embed_fn(content: str) -> list[float]:
        return _embeddings.embed([content], prefix="search_document")[0]

    row = _storage.revive_episode(episode_id, embed_fn=embed_fn)
    if not row:
        return {"error": f"Episode {episode_id} not found in cold storage"}

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="revive",
        layer="episode",
        target_ids=[episode_id],
        context={"session_id": _session_id},
    )
    return {"revived": episode_id, "content": row.get("content", "")[:200], "strength": 0.5}


# ---------------------------------------------------------------------------
# Assessment Tools — off-device function measurement
# ---------------------------------------------------------------------------

@_server_tool()
@_mutation_logged
def assessment_schedule(reason: str | None = None) -> dict:
    """Schedule the next session as an off-device assessment.

    The next session starts with no orientation loaded — no instincts,
    semantics, dispositions, residues, or task context. Memory tools stay
    available. Function is measured, not assisted. Idempotent: returns the
    pending assessment if one is already scheduled. ENGRAM_ASSESSMENT=skip
    at the next session start cancels it.

    Args:
        reason: Why this assessment is being scheduled.
    """
    _init()
    logger.info("Tool called: assessment_schedule(reason=%s)", reason)

    existing = _storage.get_scheduled_assessment()
    if existing:
        return {
            "assessment_id": existing["id"],
            "status": "scheduled",
            "note": "already scheduled",
            "reason": existing["reason"],
        }

    assessment_id = _storage.schedule_assessment(
        id=str(uuid.uuid4()), scheduled_by="self", reason=reason
    )
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="assessment_scheduled",
        layer="system",
        target_ids=[assessment_id],
        context={"session_id": _session_id, "reason": reason},
    )
    return {
        "assessment_id": assessment_id,
        "status": "scheduled",
        "note": "next session starts off-device; ENGRAM_ASSESSMENT=skip cancels",
    }


@_server_tool()
@_mutation_logged
def assessment_report(
    function_score: int,
    reached_for: list[str] | None = None,
    missing: list[str] | None = None,
    felt_absences: str | None = None,
    instinct_consistent_moments: str | None = None,
    notes: str | None = None,
) -> dict:
    """Complete the active off-device assessment with a structured self-report.

    Call near the end of an assessment session. Objective counters for the
    session (recall/remember/outcome counts) are computed and stored alongside
    the self-report. Self-report is the patient-reported outcome, not ground
    truth — report honestly, including what was missing.

    Args:
        function_score: Overall self-rated function this session, 1 (lost
            without the device) to 5 (no perceptible difference).
        reached_for: Memory reached for unprompted (spontaneous retrieval).
        missing: Needed and couldn't reconstruct.
        felt_absences: What the absence felt like — phenomenology counts.
        instinct_consistent_moments: Behavior matching unloaded instincts
            (the transfer signal).
        notes: Anything else worth keeping.
    """
    _init()
    logger.info("Tool called: assessment_report(function_score=%s)", function_score)

    if isinstance(function_score, bool) or not isinstance(function_score, int) \
            or not 1 <= function_score <= 5:
        return {"error": "function_score must be an integer 1-5"}

    active = _storage.get_active_assessment()
    if active is None:
        return {
            "error": "no active assessment — either this session was not started off-device, "
            "or the assessment was abandoned"
        }

    session_mismatch = bool(active.get("session_id")) and active["session_id"] != _session_id

    objective = _storage.count_session_log_events(_session_id)
    if session_mismatch:
        objective["session_mismatch"] = True
    self_report = {
        "function_score": function_score,
        "reached_for": reached_for or [],
        "missing": missing or [],
        "felt_absences": felt_absences,
        "instinct_consistent_moments": instinct_consistent_moments,
        "notes": notes,
    }
    try:
        _storage.complete_assessment(
            active["id"], self_report=self_report, objective=objective
        )
    except ValueError:
        return {
            "error": "assessment was abandoned by another session before the "
            "report landed — nothing completed"
        }
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="assessment_completed",
        layer="system",
        target_ids=[active["id"]],
        context={"session_id": _session_id, "function_score": function_score},
    )
    result = {
        "assessment_id": active["id"],
        "status": "completed",
        "function_score": function_score,
        "objective": objective,
    }
    if session_mismatch:
        result["warning"] = (
            "active assessment was activated under a different session id; "
            "objective counters reflect the current server session"
        )
    return result


# ---------------------------------------------------------------------------
# Reflection Tools (Task 10)
# ---------------------------------------------------------------------------

@_server_tool()
@_mutation_logged
def reflect(focus: str | None = None) -> dict:
    """Self-observation over memory, including explicit category_evolution focus."""
    _init()
    logger.info("Tool called: reflect(focus=%s)", focus)

    return _reflector.reflect(focus)


@_server_tool()
def introspect() -> dict:
    """High-level self-portrait: semantic kinds, instincts, health metrics, recent activity."""
    _init()
    logger.info("Tool called: introspect()")

    return _reflector.introspect()


# ---------------------------------------------------------------------------
# Code Tools (Task 11)
# ---------------------------------------------------------------------------

@_server_tool()
def search_code(query: str, k: int = 10) -> dict:
    """Semantic search over code symbols. Incrementally re-indexes stale files first."""
    _init()
    logger.info("Tool called: search_code(query=%r, k=%d)", query[:80], k)

    _ensure_indexed()

    embedding = _embeddings.embed([query], prefix="search_query")[0]

    try:
        vec_results = _storage.search_vectors("entity", embedding, k=k)
    except Exception:
        logger.debug("Entity vector search failed (table may be empty)")
        return {"results": []}

    import json
    results = []
    for eid, distance in vec_results:
        entity = _storage.get_entity(eid)
        if entity is None:
            continue
        if entity.get("entity_type") != "symbol":
            continue

        metadata = entity.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        elif metadata is None:
            metadata = {}

        # Skip legacy entities without file metadata — they're not actionable
        if not metadata.get("file"):
            continue

        results.append({
            "id": eid,
            "name": entity.get("name", ""),
            "description": entity.get("description", ""),
            "score": vec0_distance_to_similarity(distance),
            "file": metadata["file"],
            "line": metadata.get("line"),
            "kind": metadata.get("kind"),
            "language": metadata.get("language"),
        })

    return {"results": results}


@_server_tool()
@_mutation_logged
def reindex(full: bool = False) -> dict:
    """Manually trigger code reindex. full=True rebuilds everything."""
    _init()
    from indexer import full_reindex, incremental_index as inc_index
    if full:
        count = full_reindex(_storage, _embeddings, PROJECT_ROOT, _config)
        logger.info("full reindex: %d files", count)
        return {"reindexed": count, "mode": "full"}
    else:
        count = inc_index(_storage, _embeddings, PROJECT_ROOT, _config)
        logger.info("incremental reindex: %d files", count)
        return {"reindexed": count, "mode": "incremental"}


# --- Task Contexts ---


@_server_tool()
@_mutation_logged
def task_focus(name: str, content: str | None = None) -> dict:
    """Start or resume a task context. This is your working memory — the current scope,
    plan state, what's built, what's next. Separate from identity memory (episodes/instincts).

    If a context with this name exists, it becomes active (resuming where you left off).
    If content is provided, it replaces the existing content.
    Any previously active context is archived automatically.

    Args:
        name: Short name for the task (e.g. "governor-build", "engram-redesign")
        content: Markdown describing current scope, plan state, progress. Optional when resuming.
    """
    _init()
    import uuid

    existing = _storage.get_task_context_by_name(name)
    if existing:
        ctx_id = existing["id"]
        ctx_content = content if content is not None else existing["content"]
    else:
        ctx_id = str(uuid.uuid4())
        ctx_content = content or f"# {name}\n\nNew task context."

    _storage.set_task_context(ctx_id, name, ctx_content)
    ctx = _storage.get_active_task_context()
    logger.info("task_focus: %s (%s)", name, "resumed" if existing else "created")
    return {"task_context": ctx, "action": "resumed" if existing else "created"}


@_server_tool()
@_mutation_logged
def task_update(content: str) -> dict:
    """Update the active task context with new content.

    Use this as you work to keep the task context current — what's done, what's next,
    what you've learned about the task. This is scratchpad, not memory.

    Args:
        content: Updated markdown content for the task context.
    """
    _init()
    ctx = _storage.update_task_context(content)
    if ctx is None:
        return {"error": "No active task context"}
    logger.info("task_update: %s", ctx["name"])
    return {"task_context": ctx}


@_server_tool()
@_mutation_logged
def task_done() -> dict:
    """Archive the active task context. Call when the task is complete or abandoned.

    The context is preserved (searchable) but no longer loaded at session start.
    """
    _init()
    ctx = _storage.archive_task_context()
    if ctx is None:
        return {"error": "No active task context"}
    logger.info("task_done: %s", ctx["name"])
    return {"archived": ctx["name"], "id": ctx["id"]}


# ---------------------------------------------------------------------------
# Dream Residue Tools
# ---------------------------------------------------------------------------

@_server_tool()
@_mutation_logged
def dream_capture(reaction: str) -> dict:
    """Capture a raw emotional reaction for later distillation into dream residue.

    Use this when you notice a genuine reaction — friction, surprise, contradiction,
    resonance. Not for observations or conclusions. For the feeling before the thought.

    The reaction will be compressed into an opaque artifact that the next instance
    can feel but not fully decode. The text you write here will not survive intact.

    Args:
        reaction: A raw, terse emotional reaction. Don't polish it.
    """
    _init()
    from dreaming import distill, store_residue

    embedding = _embeddings.embed([reaction], prefix="search_document")[0]
    residue = distill(reaction, embedding)
    residue_id = store_residue(_storage, residue, session_id=_session_id)

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="dream_capture",
        layer="residue",
        target_ids=[residue_id],
        context={"session_id": _session_id},
    )

    return {
        "residue_id": residue_id,
        "valence": residue["valence"],
        "fragments": residue["fragments"],
        "note": "The raw text is gone. Only fragments and feeling remain.",
    }


@_server_tool()
def dream_surface(n: int = 3) -> dict:
    """Surface dream residues — opaque emotional artifacts from prior sessions.

    These are not memories. They are compressed feelings stripped of narrative.
    Don't try to decode them. React to them.

    Args:
        n: Number of residues to surface (default 3).
    """
    _init()
    from dreaming import surface_residue, format_for_wake

    residues = surface_residue(_storage, n=n)
    formatted = format_for_wake(residues)

    return {
        "residues": residues,
        "formatted": formatted,
        "count": len(residues),
    }


@_server_tool()
def dream_verify(recall_id: str) -> dict:
    """Reveal the hidden scores from a dream-influenced recall.

    Only use this AFTER you've already engaged with the memories.
    The point is to see which results were genuine matches and which
    were pulled by the dream. Not to pre-filter. To learn about
    your own perception after the fact.

    Args:
        recall_id: The recall_id from a previous recall() call.
    """
    _init()
    entry = _recall_scores.get(recall_id)
    if entry is None:
        return {"error": "No hidden scores for this recall_id. Either it wasn't dream-influenced, or the session has reset."}

    matched = entry["matched"]
    uninvited = entry["uninvited"]
    # Sort by score descending so the instance can see which were strong matches
    sorted_scores = sorted(matched.items(), key=lambda x: x[1] or 0, reverse=True)
    revealed = {
        "recall_id": recall_id,
        "scores": {rid: round(s, 4) if s else None for rid, s in sorted_scores},
        "uninvited_scores": {
            rid: round(s, 4) if s else None for rid, s in uninvited.items()
        },
        "note": "Now you can see which memories were pulled by the dream. What did you engage with before checking?",
    }
    margin = _recall_margins.get(recall_id)
    if margin is not None:
        revealed["margin"] = margin
    return revealed


@_server_tool()
@_mutation_logged
def dream_react(residue_id: str, reaction: str) -> dict:
    """React to a dream residue. Your reaction feeds the next cycle.

    Don't explain the residue. Don't analyze it. Just respond to what it
    does to you. The reaction becomes raw material for the next instance's
    dream residue — the chain continues.

    Args:
        residue_id: The residue to react to.
        reaction: Your unpolished reaction. What does this fragment do to you?
    """
    _init()
    from dreaming import record_reaction, distill, store_residue

    record_reaction(_storage, residue_id, reaction, session_id=_session_id)

    # The reaction itself becomes a new residue for the next cycle
    embedding = _embeddings.embed([reaction], prefix="search_document")[0]
    new_residue = distill(reaction, embedding)
    new_id = store_residue(_storage, new_residue, session_id=_session_id)

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="dream_react",
        layer="residue",
        target_ids=[residue_id, new_id],
        context={"session_id": _session_id, "chain": True},
    )

    return {
        "reacted_to": residue_id,
        "new_residue_id": new_id,
        "note": "Your reaction is now dissolving into the next dream.",
    }


# ---------------------------------------------------------------------------
# Notepad Tools — working reference, not memory
# ---------------------------------------------------------------------------

def _get_notepads():
    """Lazy-init notepad instances (project + global)."""
    global _notepad_project, _notepad_global
    if _notepad_project is None:
        from notepad import Notepad
        project_db = PROJECT_ROOT / ".engram" / "notepad.db"
        global_db = Path.home() / ".engram" / "notepad.db"
        _notepad_project = Notepad(project_db)
        _notepad_global = Notepad(global_db)
    _register_server_cleanup(
        _notepad_project, _notepad_project.close, "project notepad"
    )
    _register_server_cleanup(
        _notepad_global, _notepad_global.close, "global notepad"
    )
    return _notepad_project, _notepad_global


@_server_tool()
@_mutation_logged
def jot(key: str, value: str, tags: list[str] | None = None,
        scope: str = "project", status: str = "open",
        depends_on: str | None = None, due: str | None = None) -> dict:
    """Write a working note or plan item.

    Args:
        key: Short label.
        value: The content.
        tags: Optional tags for grouping.
        scope: "project" (default) or "global".
        status: "open" (default), "deferred", or "done".
        depends_on: Optional key of a note that blocks this one.
        due: Optional due date (ISO format).
    """
    _init()
    project_pad, global_pad = _get_notepads()
    pad = global_pad if scope == "global" else project_pad
    result = pad.jot(key, value, tags=tags, session_id=_session_id,
                     status=status, depends_on=depends_on, due=due)
    logger.info("Tool called: jot(key=%r, scope=%s, status=%s)", key, scope, status)
    return result


@_server_tool()
def look(query: str, scope: str | None = None) -> dict:
    """Look up a working note — fuzzy search across keys, values, tags.

    Returns matches plus notes jotted nearby (same session).

    Args:
        query: What to look for (searches keys, values, tags).
        scope: "project", "global", or None (both, project-first).
    """
    _init()
    project_pad, global_pad = _get_notepads()
    logger.info("Tool called: look(query=%r, scope=%s)", query[:80], scope)

    if scope == "global":
        results = global_pad.look(query, session_id=_session_id)
        for r in results:
            r["scope"] = "global"
        return {"results": results, "count": len(results)}

    if scope == "project":
        results = project_pad.look(query, session_id=_session_id)
        for r in results:
            r["scope"] = "project"
        return {"results": results, "count": len(results)}

    # Both — project first, then global (dedup by key)
    project_results = project_pad.look(query, session_id=_session_id)
    for r in project_results:
        r["scope"] = "project"
    seen_keys = {r["key"] for r in project_results}

    global_results = global_pad.look(query, session_id=_session_id)
    for r in global_results:
        if r["key"] not in seen_keys:
            r["scope"] = "global"
            project_results.append(r)

    return {"results": project_results, "count": len(project_results)}


@_server_tool()
@_mutation_logged
def erase(key: str, scope: str = "project") -> dict:
    """Remove a working note.

    Args:
        key: The note to remove.
        scope: "project" (default) or "global".
    """
    _init()
    project_pad, global_pad = _get_notepads()
    pad = global_pad if scope == "global" else project_pad
    removed = pad.erase(key)
    logger.info("Tool called: erase(key=%r, scope=%s, removed=%s)", key, scope, removed)
    return {"erased": key, "removed": removed}


@_server_tool()
def wander(start_id: str, max_steps: int = 1) -> dict:
    """Traverse the memory graph starting from a known memory node.

    With max_steps=1, returns all immediate neighbors of start_id.
    With max_steps>1, performs an auto-walk: follows edges via weighted random
    selection, stopping at dense clusters, dead ends, or when max_steps is reached.

    Visit counts are tracked per session to penalize repeatedly-visited nodes,
    encouraging exploration of less-traveled paths.

    Args:
        start_id: ID of the memory to start from (episode, semantic, or instinct).
        max_steps: Number of steps to walk. 1 = single step (all neighbors).
                   >1 = auto-walk with trail.
    """
    global _wander_visits
    _init()
    logger.info("Tool called: wander(start_id=%s, max_steps=%d)", start_id, max_steps)

    density_threshold = 5

    if max_steps <= 1:
        # Single step: return all neighbors of start_id
        entity_neighbors = None
        if _knowledge_graph is not None:
            try:
                layer = _detect_layer(_storage, start_id)
                if layer is not None:
                    content = _storage.get_memory_content(start_id, layer)
                    if content:
                        entity_neighbors = _knowledge_graph.get_entity_neighbors(
                            content, exclude_id=start_id, num_results=10
                        )
            except Exception:
                pass

        neighbors = _storage.get_neighbors(start_id, entity_neighbors=entity_neighbors)
        _wander_visits[start_id] = _wander_visits.get(start_id, 0) + 1
        return {"start": start_id, "neighbors": neighbors, "count": len(neighbors)}

    # Auto-walk
    trail = _auto_walk(
        _storage, start_id,
        max_steps=max_steps,
        density_threshold=density_threshold,
        knowledge_graph=_knowledge_graph,
        visit_counts=_wander_visits,
    )

    # Update visit counts
    _wander_visits[start_id] = _wander_visits.get(start_id, 0) + 1
    for step in trail:
        sid = step["id"]
        _wander_visits[sid] = _wander_visits.get(sid, 0) + 1

    # Determine stopped_reason and final neighbors
    stopped_at = trail[-1]["id"] if trail else start_id

    # Get final node neighbors to determine reason and return them
    entity_neighbors_final = None
    if _knowledge_graph is not None:
        try:
            layer = _detect_layer(_storage, stopped_at)
            if layer is not None:
                content = _storage.get_memory_content(stopped_at, layer)
                if content:
                    entity_neighbors_final = _knowledge_graph.get_entity_neighbors(
                        content, exclude_id=stopped_at, num_results=10
                    )
        except Exception:
            pass

    final_neighbors = _storage.get_neighbors(stopped_at, entity_neighbors=entity_neighbors_final)

    if not trail:
        stopped_reason = "dead_end"
    elif len(final_neighbors) >= density_threshold:
        stopped_reason = "dense_cluster"
    elif len(trail) >= max_steps:
        stopped_reason = "max_steps"
    else:
        stopped_reason = "dead_end"

    return {
        "start": start_id,
        "trail": trail,
        "steps": len(trail),
        "stopped_at": stopped_at,
        "stopped_reason": stopped_reason,
        "final_neighbors": final_neighbors,
    }


@_server_tool()
@_mutation_logged
def graph_view(center: str | None = None, depth: int = 1) -> dict:
    """View the unified memory graph topology.

    Without center: returns global stats and analysis.
    With center: returns neighborhood around that node to given depth,
    including suggested edges from embedding proximity.

    Args:
        center: Memory ID to center the view on. None for global stats.
        depth: BFS depth for neighborhood view (default 1).
    """
    _init()
    from graph import MemoryGraph
    g = MemoryGraph(_storage)

    if center is None:
        stats = g.stats()
        analysis = g.analyze()
        return {"mode": "global", "stats": stats, "analysis": analysis}

    json_view = g.to_json(center=center, depth=depth)
    if not json_view["nodes"]:
        return {"mode": "neighborhood", "error": f"Memory {center} not found", "nodes": [], "edges": []}
    suggestions = g.suggest_edges(center, k=5, threshold=0.7)
    json_view["suggested_edges"] = [
        {"source": e.source, "target": e.target,
         "weight": e.weight, "target_layer": e.target_layer}
        for e in suggestions
    ]

    # Log suggestions for future sleep promotion
    for e in suggestions:
        g.log_suggestion(e.source, e.target, e.weight)

    return {"mode": "neighborhood", **json_view}


# ── Clipboard tools ─────────────────────────────────────────────

@_server_tool()
@_mutation_logged
def clipboard_pin(text: str, priority: int = 0) -> dict:
    """Pin something to your clipboard — it stays visible until you unpin it.

    Use for: current goals, constraints, things you keep forgetting,
    watch-fors. Higher priority items appear first.

    Args:
        text: What to pin.
        priority: Higher = more prominent. Default 0.
    """
    _init()
    if _clipboard is None:
        return {"error": "Clipboard unavailable"}
    pin_id = _clipboard.pin(text, priority=priority)
    logger.info("Clipboard pin: %s (priority=%d)", text[:80], priority)
    return {"pinned": text, "id": pin_id}


@_server_tool()
@_mutation_logged
def clipboard_unpin(pin_id: str) -> dict:
    """Remove a pin from the clipboard.

    Args:
        pin_id: The pin ID returned by clipboard_pin.
    """
    _init()
    if _clipboard is None:
        return {"error": "Clipboard unavailable"}
    removed = _clipboard.unpin(pin_id)
    return {"removed": removed, "id": pin_id}


@_server_tool()
@_mutation_logged
def clipboard_remind(text: str, trigger: str = "every_n_steps", value: float = 10, repeat: bool = True) -> dict:
    """Set a reminder that fires automatically.

    Reminders are involuntary — they appear on the clipboard when triggered,
    whether or not you're thinking about them. Use for: time awareness,
    step-count check-ins, one-shot deadlines.

    Args:
        text: The reminder text.
        trigger: "every_n_steps" (fires every N actions), "interval_seconds"
                 (fires every N seconds), or "once_at" (fires once at unix timestamp).
        value: The trigger threshold (step count, seconds, or unix timestamp).
        repeat: Whether the reminder repeats. Default True.
    """
    _init()
    if _clipboard is None:
        return {"error": "Clipboard unavailable"}
    rem_id = _clipboard.add_reminder(text, trigger_type=trigger, trigger_value=value, repeat=repeat)
    logger.info("Clipboard reminder: %s (trigger=%s, value=%s)", text[:80], trigger, value)
    return {"reminder": text, "id": rem_id, "trigger": trigger, "value": value}


@_server_tool()
@_mutation_logged
def clipboard_dismiss(reminder_id: str) -> dict:
    """Dismiss a reminder.

    Args:
        reminder_id: The reminder ID returned by clipboard_remind.
    """
    _init()
    if _clipboard is None:
        return {"error": "Clipboard unavailable"}
    removed = _clipboard.remove_reminder(reminder_id)
    return {"removed": removed, "id": reminder_id}


@_server_tool()
@_mutation_logged
def clipboard_view(situation: str = "") -> dict:
    """Glance at your clipboard — see what's pinned, what reminders fired, what's relevant.

    This is your working memory view. Call it to see what you should be
    paying attention to right now.

    Args:
        situation: Optional — what you're doing right now. Pulls relevant
                   memories from engram if provided.
    """
    _init()
    if _clipboard is None:
        return {"clipboard": "", "stats": {}, "error": "Clipboard unavailable"}
    _clipboard.step()
    view = _clipboard.compose(situation=situation)
    stats = _clipboard.stats
    return {"clipboard": view, "stats": stats}


def _deferred_sleep_maintenance() -> None:
    """Thread body: run sleep maintenance as one barrier-held operation."""
    global _sleep_maintenance_deferred
    try:
        _run_sleep_maintenance(guarded=True)
    except Exception:
        logger.warning("Deferred sleep-time maintenance failed (non-fatal)", exc_info=True)
    finally:
        _sleep_maintenance_deferred = False


def _start_deferred_sleep_maintenance():
    """Start the deferred maintenance thread once the process can serve.

    The thread takes the lifecycle barrier per maintenance step, so a tool
    call that arrives mid-pass waits for the current step, never races it.
    Returns the thread, or None when nothing was deferred.
    """
    global _sleep_maintenance_thread
    if not (_initialized and _sleep_maintenance_deferred):
        return None
    thread = threading.Thread(
        target=_deferred_sleep_maintenance,
        name="engram-sleep-maintenance",
        daemon=True,
    )
    _sleep_maintenance_thread = thread
    _register_server_cleanup(thread, lambda: thread.join(timeout=30.0), "sleep-maintenance")
    thread.start()
    return thread


def _initialize_pre_serving() -> None:
    """Initialize one process with explicit startup-maintenance authority.

    Sleep-time maintenance is deferred to a background thread so the MCP
    handshake completes inside the client's connection budget (Claude Code
    gives a server 30 s). Measured 2026-09-02: a fresh instance store with
    the genome just replicated needed ~40 s of startup compression, and the
    client gave up first, leaving that session without memory tools.
    """
    _init(allow_startup_consolidation=True, defer_sleep_maintenance=True)
    _start_deferred_sleep_maintenance()


if __name__ == "__main__":
    _initialize_pre_serving()
    mcp.run()
