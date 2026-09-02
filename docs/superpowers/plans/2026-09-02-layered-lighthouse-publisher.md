# Layered Lighthouse, Publisher Side Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make sharing an explicit act with an audience, replace the publisher daemon's work-lane rule with an audience filter, and generate receiver policies from a group file.

**Architecture:** One new module `sharing.py` owns the share record and the share/unshare operations against the published house. One new module `policy_gen.py` turns `.engram/groups.toml` plus an instance name into a receiver policy artifact. `lighthouse_daemon.py` swaps its lane filter for an audience filter. `server.py` gains two MCP tools. No change to lanes, decay, core promotion, or instinct formation.

**Tech Stack:** Python 3.11+, SQLite via the existing `Storage` class, the existing `lighthouse_policy` and `lighthouse_protocol` modules. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-02-layered-lighthouse-design.md`

## Global Constraints

- Base ref: the branch head named in the human brief, cut from `main`.
- Test command from your worktree root: `.venv/bin/python -m pytest tests/ -q`. Baseline at the base ref: `1705 passed`. Any failure outside your allowed files is a stop-and-report, not a fix.
- Never restart, kill, or reconnect the running Engram MCP server. The human restarts it.
- Never write to `.engram/instances/*/graph.db` or `.engram/genome/graph.db` from a test. Tests build their own stores in `tmp_path`.
- The daemon's four safety properties are invariants, not features: deny by default, policy evaluated before retrieval, read-only store access, every disclosure logged. A test that weakens any of them is a stop-and-report.
- Audience vocabulary is closed: `commons`, or `group:<name>` where `<name>` matches `[a-z][a-z0-9-]{0,63}`. Anything else fails closed.
- The policy extension key for audiences is exactly `engram:audiences`, a list of audience strings, on the policy artifact's `extensions` object.
- `server.py` is a shared file. dev1 lands its two tool registrations first; dev2 rebases across them.
- Commit after every green test. Never push.

---

## File Structure

| File | Responsibility |
|---|---|
| `migrations/027_shared_memories.sql` | the `shared_memories` table in the published house |
| `sharing.py` | share record, `share`, `unshare`, `list_shares`, audience validation |
| `policy_gen.py` | `.engram/groups.toml` to a receiver policy artifact |
| `lighthouse_daemon.py` | audience filter replaces the work-lane filter |
| `server.py` | `share` and `unshare` MCP tools |
| `tests/test_sharing.py`, `tests/test_policy_gen.py`, `tests/test_daemon_audiences.py` | one per module |

Ownership: **dev1** owns Tasks 1, 2, 5 (migration, sharing module, MCP tools). **dev2** owns Tasks 3, 4 (policy generator, daemon audience filter). Only `server.py` is shared, and only dev1 touches it in this plan.

## Interfaces shared across tasks

```python
# sharing.py
AUDIENCE_COMMONS = "commons"
GROUP_RE = re.compile(r"group:[a-z][a-z0-9-]{0,63}\Z")

@dataclass(frozen=True, slots=True)
class ShareRecord:
    share_id: str          # uuid4
    memory_id: str         # id in the published house (a fresh uuid4 for the copy)
    source_instance: str
    source_id: str
    layer: str             # "episode" | "semantic"
    audience: str          # "commons" | "group:<name>"
    reason: str
    content_digest: str    # lighthouse_protocol.content_digest of the content
    shared_at: str         # RFC3339 UTC

def validate_audience(value: str) -> str: ...          # returns value or raises ValueError
def share(*, source_storage, published_storage, source_id, layer, audience, reason,
          source_instance, now=None) -> ShareRecord: ...
def unshare(*, published_storage, share_id) -> bool: ...
def list_shares(*, published_storage, audience=None) -> list[ShareRecord]: ...
def audiences_for(published_storage, memory_id: str) -> set[str]: ...
```

```python
# policy_gen.py
def load_groups(path: Path) -> dict[str, list[str]]: ...      # {group_name: [instance, ...]}
def audiences_for_instance(groups: dict[str, list[str]], instance: str) -> list[str]: ...
def build_receiver_policy(*, instance: str, publisher: str, groups: dict[str, list[str]],
                          issued_at: str, valid_from: str, valid_until: str) -> dict: ...
def write_receiver_policy(path: Path, artifact: dict) -> str: ...   # returns the digest
```

---

### Task 1: Migration and share record (dev1)

**Files:**
- Create: `migrations/027_shared_memories.sql`
- Create: `sharing.py` (record and validation only)
- Test: `tests/test_sharing.py`

**Interfaces:**
- Produces: `ShareRecord`, `AUDIENCE_COMMONS`, `GROUP_RE`, `validate_audience`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sharing.py
import pytest

from sharing import AUDIENCE_COMMONS, ShareRecord, validate_audience


def test_commons_and_group_audiences_accepted():
    assert validate_audience(AUDIENCE_COMMONS) == "commons"
    assert validate_audience("group:engram-system") == "group:engram-system"
    assert validate_audience("group:a") == "group:a"


@pytest.mark.parametrize("bad", [
    "", "COMMONS", "commons ", "group:", "group:Engram", "group:-x", "group:x_y",
    "group:" + "a" * 65, "world", "group:a:b", None, 3,
])
def test_bad_audiences_fail_closed(bad):
    with pytest.raises((ValueError, TypeError)):
        validate_audience(bad)


def test_share_record_is_frozen_and_complete():
    rec = ShareRecord(share_id="s", memory_id="m", source_instance="engram", source_id="e",
                      layer="episode", audience="commons", reason="why",
                      content_digest="d", shared_at="2026-09-02T00:00:00Z")
    assert rec.layer == "episode"
    with pytest.raises(Exception):
        rec.audience = "group:x"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sharing.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sharing'`

- [ ] **Step 3: Write the migration**

```sql
-- migrations/027_shared_memories.sql
CREATE TABLE IF NOT EXISTS shared_memories (
    share_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    source_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    audience TEXT NOT NULL,
    reason TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    shared_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shared_memories_memory ON shared_memories(memory_id);
CREATE INDEX IF NOT EXISTS idx_shared_memories_audience ON shared_memories(audience);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shared_memories_source
    ON shared_memories(source_instance, source_id, audience);
```

- [ ] **Step 4: Write the record and validation**

```python
# sharing.py
"""Explicit sharing into the published house, with an audience.

Sharing is an act, not a derivation. A shared row is a COPY: the private
original keeps decaying and compressing on its own terms, and withdrawing a
share never deletes a memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

AUDIENCE_COMMONS = "commons"
GROUP_RE = re.compile(r"group:[a-z][a-z0-9-]{0,63}\Z")


@dataclass(frozen=True, slots=True)
class ShareRecord:
    share_id: str
    memory_id: str
    source_instance: str
    source_id: str
    layer: str
    audience: str
    reason: str
    content_digest: str
    shared_at: str


def validate_audience(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("audience must be a string")
    if value == AUDIENCE_COMMONS or GROUP_RE.fullmatch(value):
        return value
    raise ValueError(f"unknown audience: {value!r}")
```

- [ ] **Step 5: Run to verify it passes, then commit**

Run: `.venv/bin/python -m pytest tests/test_sharing.py -q` (all PASS)

```bash
git add migrations/027_shared_memories.sql sharing.py tests/test_sharing.py
git commit -m "sharing: shared_memories table and closed audience vocabulary"
```

---

### Task 2: Share and unshare against the published house (dev1)

**Files:**
- Modify: `sharing.py`
- Test: `tests/test_sharing.py`

**Interfaces:**
- Consumes: `Storage`, `lighthouse_protocol.content_digest`.
- Produces: `share`, `unshare`, `list_shares`, `audiences_for`.

Behaviour fixed here. `share` reads the source row from the calling instance's storage, refuses if absent, copies its content into the published house as a NEW episode or semantic with a fresh id, records the row in `shared_memories`, and returns the record. Re-sharing the same `(source_instance, source_id, audience)` is idempotent: it returns the existing record without a second copy. Sharing the same source to a second audience creates a second record pointing at the SAME published `memory_id`. `unshare` deletes the share row, and deletes the published copy only when no other share row references that `memory_id`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_sharing.py
import uuid

from sharing import audiences_for, list_shares, share, unshare
from storage import Storage

MIGRATIONS = "migrations"


def _stores(tmp_path):
    src = Storage(str(tmp_path / "src.db"), migrations_dir=MIGRATIONS)
    pub = Storage(str(tmp_path / "pub.db"), migrations_dir=MIGRATIONS)
    return src, pub


def _episode(src, content="a lived thing"):
    eid = str(uuid.uuid4())
    src.add_episode(id=eid, session_id=None, content=content, episode_type="test")
    src.conn.commit()
    return eid


def test_share_copies_content_and_records_provenance(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    rec = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
                audience="commons", reason="worth meeting me through", source_instance="engram")
    assert rec.source_id == eid and rec.source_instance == "engram" and rec.audience == "commons"
    assert rec.memory_id != eid
    copied = pub.get_episode(rec.memory_id)
    assert copied is not None and copied["content"] == "a lived thing"
    assert src.get_episode(eid) is not None


def test_share_is_idempotent_per_audience(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    a = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r", source_instance="engram")
    b = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r2", source_instance="engram")
    assert a.share_id == b.share_id
    assert len(list_shares(published_storage=pub)) == 1


def test_second_audience_reuses_one_published_copy(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    a = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r", source_instance="engram")
    b = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="group:crossing", reason="r", source_instance="engram")
    assert a.memory_id == b.memory_id and a.share_id != b.share_id
    assert audiences_for(pub, a.memory_id) == {"commons", "group:crossing"}


def test_unshare_keeps_the_copy_while_another_audience_holds_it(tmp_path):
    src, pub = _stores(tmp_path)
    eid = _episode(src)
    a = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="commons", reason="r", source_instance="engram")
    b = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="group:crossing", reason="r", source_instance="engram")
    assert unshare(published_storage=pub, share_id=a.share_id) is True
    assert pub.get_episode(a.memory_id) is not None
    assert unshare(published_storage=pub, share_id=b.share_id) is True
    assert pub.get_episode(b.memory_id) is None
    assert unshare(published_storage=pub, share_id=b.share_id) is False


def test_missing_source_and_bad_audience_fail_closed(tmp_path):
    src, pub = _stores(tmp_path)
    with pytest.raises(ValueError):
        share(source_storage=src, published_storage=pub, source_id=str(uuid.uuid4()),
              layer="episode", audience="commons", reason="r", source_instance="engram")
    eid = _episode(src)
    with pytest.raises(ValueError):
        share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
              audience="everyone", reason="r", source_instance="engram")
    with pytest.raises(ValueError):
        share(source_storage=src, published_storage=pub, source_id=eid, layer="instinct",
              audience="commons", reason="r", source_instance="engram")
    assert list_shares(published_storage=pub) == []


def test_list_shares_filters_by_audience(tmp_path):
    src, pub = _stores(tmp_path)
    e1, e2 = _episode(src, "one"), _episode(src, "two")
    share(source_storage=src, published_storage=pub, source_id=e1, layer="episode",
          audience="commons", reason="r", source_instance="engram")
    share(source_storage=src, published_storage=pub, source_id=e2, layer="episode",
          audience="group:crossing", reason="r", source_instance="engram")
    assert len(list_shares(published_storage=pub, audience="commons")) == 1
    assert len(list_shares(published_storage=pub)) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sharing.py -q`
Expected: FAIL on `ImportError` for `share`

- [ ] **Step 3: Implement**

Add to `sharing.py`. Layer must be `episode` or `semantic`; `instinct` is never shareable.

**The copy carries the source's vector.** `Storage.get_vector(layer, id)` returns the stored embedding or `None`, and `add_episode`/`add_semantic` accept an `embedding` argument. Read the source vector and pass it through, so a shared row is searchable the moment it is shared and no embedder is needed inside `share`. A source row with no vector yet copies as `None` and becomes searchable after the next maintenance pass; say so in the docstring.

```python
import uuid
from datetime import datetime, timezone

from lighthouse_protocol import content_digest

SHAREABLE_LAYERS = ("episode", "semantic")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def share(*, source_storage, published_storage, source_id, layer, audience, reason,
          source_instance, now=None) -> ShareRecord:
    audience = validate_audience(audience)
    if layer not in SHAREABLE_LAYERS:
        raise ValueError(f"layer {layer!r} is not shareable")
    getter = source_storage.get_episode if layer == "episode" else source_storage.get_semantic
    row = getter(source_id)
    if row is None:
        raise ValueError(f"no {layer} {source_id!r} in the source instance")

    existing = published_storage.conn.execute(
        "SELECT * FROM shared_memories WHERE source_instance = ? AND source_id = ? AND audience = ?",
        (source_instance, source_id, audience),
    ).fetchone()
    if existing is not None:
        return ShareRecord(**{k: existing[k] for k in ShareRecord.__slots__})

    sibling = published_storage.conn.execute(
        "SELECT memory_id FROM shared_memories WHERE source_instance = ? AND source_id = ? LIMIT 1",
        (source_instance, source_id),
    ).fetchone()
    content = row.get("content", "")
    if sibling is not None:
        memory_id = sibling["memory_id"]
    else:
        memory_id = str(uuid.uuid4())
        vector = source_storage.get_vector(layer, source_id)
        if layer == "episode":
            published_storage.add_episode(id=memory_id, session_id=None, content=content,
                                          episode_type="shared", embedding=vector)
        else:
            published_storage.add_semantic(id=memory_id, content=content,
                                           kind=row.get("kind", "fact"),
                                           confidence=row.get("confidence", 0.5),
                                           embedding=vector, source_episode_ids=[])

    record = ShareRecord(
        share_id=str(uuid.uuid4()), memory_id=memory_id, source_instance=source_instance,
        source_id=source_id, layer=layer, audience=audience, reason=reason,
        content_digest=content_digest(content), shared_at=now or _now(),
    )
    published_storage.conn.execute(
        "INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer,"
        " audience, reason, content_digest, shared_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (record.share_id, record.memory_id, record.source_instance, record.source_id,
         record.layer, record.audience, record.reason, record.content_digest, record.shared_at),
    )
    published_storage.conn.commit()
    return record


def unshare(*, published_storage, share_id) -> bool:
    row = published_storage.conn.execute(
        "SELECT memory_id, layer FROM shared_memories WHERE share_id = ?", (share_id,)
    ).fetchone()
    if row is None:
        return False
    published_storage.conn.execute("DELETE FROM shared_memories WHERE share_id = ?", (share_id,))
    remaining = published_storage.conn.execute(
        "SELECT COUNT(*) FROM shared_memories WHERE memory_id = ?", (row["memory_id"],)
    ).fetchone()[0]
    if remaining == 0:
        table = "episodes" if row["layer"] == "episode" else "semantics"
        vectors = "episode_vectors" if row["layer"] == "episode" else "semantic_vectors"
        published_storage.conn.execute(f"DELETE FROM {vectors} WHERE id = ?", (row["memory_id"],))
        published_storage.conn.execute(f"DELETE FROM {table} WHERE id = ?", (row["memory_id"],))
    published_storage.conn.commit()
    return True


def list_shares(*, published_storage, audience=None) -> list[ShareRecord]:
    sql = "SELECT * FROM shared_memories"
    args: tuple = ()
    if audience is not None:
        sql += " WHERE audience = ?"
        args = (validate_audience(audience),)
    sql += " ORDER BY shared_at, share_id"
    return [ShareRecord(**{k: r[k] for k in ShareRecord.__slots__})
            for r in published_storage.conn.execute(sql, args)]


def audiences_for(published_storage, memory_id: str) -> set[str]:
    return {r[0] for r in published_storage.conn.execute(
        "SELECT audience FROM shared_memories WHERE memory_id = ?", (memory_id,))}
```

- [ ] **Step 4: Run to verify it passes, then commit**

```bash
.venv/bin/python -m pytest tests/test_sharing.py -q
git add sharing.py tests/test_sharing.py
git commit -m "sharing: share and unshare against the published house"
```

---

### Task 3: Policy generator from the group file (dev2)

**Files:**
- Create: `policy_gen.py`
- Test: `tests/test_policy_gen.py`

**Interfaces:**
- Consumes: `lighthouse_protocol.artifact_digest`, `lighthouse_policy.load_policy`.
- Produces: `load_groups`, `audiences_for_instance`, `build_receiver_policy`, `write_receiver_policy`.

The generated artifact must be accepted by the existing `load_policy` unchanged, and its digest must be computed by the existing `artifact_digest`, so the TypeScript kit continues to agree.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_policy_gen.py
import json

import pytest

from lighthouse_policy import load_policy
from lighthouse_protocol import artifact_digest
from policy_gen import (audiences_for_instance, build_receiver_policy, load_groups,
                        write_receiver_policy)

GROUPS = """
[groups.engram-system]
members = ["engram", "why"]

[groups.crossing]
members = ["engram", "lighthouse"]
"""


def _groups(tmp_path):
    p = tmp_path / "groups.toml"
    p.write_text(GROUPS)
    return load_groups(p)


def test_load_groups(tmp_path):
    g = _groups(tmp_path)
    assert g == {"engram-system": ["engram", "why"], "crossing": ["engram", "lighthouse"]}


def test_audiences_include_commons_and_every_group_joined(tmp_path):
    g = _groups(tmp_path)
    assert audiences_for_instance(g, "engram") == ["commons", "group:crossing", "group:engram-system"]
    assert audiences_for_instance(g, "why") == ["commons", "group:engram-system"]
    assert audiences_for_instance(g, "stranger") == ["commons"]


def test_bad_group_names_and_members_fail_closed(tmp_path):
    for bad in ('[groups."Engram"]\nmembers = ["a"]\n', '[groups.ok]\nmembers = "engram"\n',
                '[groups.ok]\nmembers = []\n', '[groups.ok]\nmembers = ["Engram"]\n'):
        p = tmp_path / "bad.toml"
        p.write_text(bad)
        with pytest.raises(ValueError):
            load_groups(p)


def test_built_policy_loads_and_digests(tmp_path):
    g = _groups(tmp_path)
    art = build_receiver_policy(instance="engram", publisher="lighthouse", groups=g,
                                issued_at="2026-09-02T00:00:00Z", valid_from="2026-09-01T00:00:00Z",
                                valid_until="2027-01-01T00:00:00Z")
    assert art["issuer"] == "urn:engram:engram"
    assert art["payload"]["rules"][0]["publishers"] == ["urn:engram:lighthouse"]
    assert art["extensions"]["engram:audiences"] == ["commons", "group:crossing", "group:engram-system"]
    assert art["digest"] == artifact_digest(art)          # artifact_digest returns the whole dict
    assert art["digest"]["algorithm"] == "sha-256"
    path = tmp_path / "lighthouse-policy.json"
    digest = write_receiver_policy(path, art)
    assert digest == art["digest"]["value"]  # write_receiver_policy returns the hex value
    load_policy(path)  # must not raise


def test_regeneration_is_byte_stable(tmp_path):
    g = _groups(tmp_path)
    kw = dict(instance="engram", publisher="lighthouse", groups=g,
              issued_at="2026-09-02T00:00:00Z", valid_from="2026-09-01T00:00:00Z",
              valid_until="2027-01-01T00:00:00Z")
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write_receiver_policy(a, build_receiver_policy(**kw))
    write_receiver_policy(b, build_receiver_policy(**kw))
    assert a.read_bytes() == b.read_bytes()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_policy_gen.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'policy_gen'`

- [ ] **Step 3: Implement**

Read `.engram/instances/lighthouse/lighthouse-policy.json` first: the generated rule must use the same field set (`actions`, `audiences`, `claimMediaTypes`, `contexts`, `domains`, `effect`, `id`, `profiles`, `publishers`, `purposes`, `requiredAttestations`, `requiredEvidence`, `validFrom`, `validUntil`) so `load_policy` accepts it. Audiences are sorted with `commons` first, then group audiences alphabetically. Write with `json.dumps(..., sort_keys=True, indent=1)` for byte stability.

- [ ] **Step 4: Run to verify it passes, then commit**

```bash
.venv/bin/python -m pytest tests/test_policy_gen.py -q
git add policy_gen.py tests/test_policy_gen.py
git commit -m "policy_gen: receiver policies generated from the group file"
```

---

### Task 4: Daemon audience filter replaces the lane filter (dev2)

**Files:**
- Modify: `lighthouse_daemon.py`
- Test: `tests/test_daemon_audiences.py`
- Read but do not modify: `tests/test_lighthouse_daemon.py`

**Interfaces:**
- Consumes: `sharing.audiences_for` (dev1's Task 2; if not yet on your branch, cherry-pick that single commit and report it to the lead).
- Produces: `retrieve(store, embeddings, query, k, allowed_audiences: frozenset[str]) -> list[dict]`, and the daemon passing the audiences the evaluated policy allows.

Every returned entry gains `"audiences"`, the sorted intersection of the row's audiences with the allowed set. The `"lane"` key is dropped from the entry: it was always the constant `"work"` and no longer describes anything.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_daemon_audiences.py
"""The daemon serves what was shared to an audience the receiver may see."""
import uuid

import pytest

from lighthouse_daemon import retrieve
from sharing import share
from storage import Storage
from tests.test_lighthouse_daemon import FakeEmbeddings

MIGRATIONS = "migrations"


@pytest.fixture
def published(tmp_path):
    src = Storage(str(tmp_path / "src.db"), migrations_dir=MIGRATIONS)
    pub = Storage(str(tmp_path / "pub.db"), migrations_dir=MIGRATIONS)
    ids = {}
    for name, audience in (("alpha", "commons"), ("beta", "group:crossing"), ("gamma", "group:research")):
        eid = str(uuid.uuid4())
        text = f"{name} content about rivers"
        src.add_episode(id=eid, session_id=None, content=text, episode_type="test",
                        embedding=FakeEmbeddings().embed([text])[0])
        src.conn.commit()
        rec = share(source_storage=src, published_storage=pub, source_id=eid, layer="episode",
                    audience=audience, reason="r", source_instance="engram")
        ids[name] = rec.memory_id
    return pub, ids


def test_only_allowed_audiences_are_returned(published):
    pub, ids = published
    out = retrieve(pub, FakeEmbeddings(), "rivers", 10, frozenset({"commons"}))
    assert [e["memoryId"] for e in out] == [ids["alpha"]]
    assert out[0]["audiences"] == ["commons"]


def test_group_audience_widens_the_result(published):
    pub, ids = published
    out = retrieve(pub, FakeEmbeddings(), "rivers", 10, frozenset({"commons", "group:crossing"}))
    assert {e["memoryId"] for e in out} == {ids["alpha"], ids["beta"]}


def test_empty_allowed_set_returns_nothing(published):
    pub, _ = published
    assert retrieve(pub, FakeEmbeddings(), "rivers", 10, frozenset()) == []


def test_unshared_rows_are_never_returned(published, tmp_path):
    pub, _ = published
    orphan = str(uuid.uuid4())
    text = "rivers but never shared"
    pub.add_episode(id=orphan, session_id=None, content=text, episode_type="test",
                    embedding=FakeEmbeddings().embed([text])[0])
    pub.conn.commit()
    out = retrieve(pub, FakeEmbeddings(), "rivers", 10, frozenset({"commons", "group:crossing", "group:research"}))
    assert orphan not in {e["memoryId"] for e in out}


def test_entries_have_no_lane_key(published):
    pub, _ = published
    out = retrieve(pub, FakeEmbeddings(), "rivers", 10, frozenset({"commons"}))
    assert "lane" not in out[0] and "audiences" in out[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_daemon_audiences.py -q`
Expected: FAIL, `retrieve() takes 4 positional arguments but 5 were given`

- [ ] **Step 3: Implement**

In `lighthouse_daemon.py`, replace the two work-lane checks (the row filter inside `retrieve` and the one in the read path near line 296) with a `shared_memories` lookup. Compute the allowed set once from the evaluated policy's `extensions["engram:audiences"]`, intersected with what the matched rule permits, and pass it into `retrieve`. A row with no share record is never returned. Keep the existing ordering, the disclosure logging, and the read-only access unchanged.

- [ ] **Step 4: Run the daemon's own suite too, then commit**

```bash
.venv/bin/python -m pytest tests/test_daemon_audiences.py tests/test_lighthouse_daemon.py -q
git add lighthouse_daemon.py tests/test_daemon_audiences.py
git commit -m "daemon: serve by audience instead of by lane"
```

---

### Task 5: The share and unshare MCP tools (dev1)

**Files:**
- Modify: `server.py`
- Test: `tests/test_share_tools.py`

**Interfaces:**
- Consumes: `sharing.share`, `sharing.unshare`, `sharing.list_shares`.
- Produces: MCP tools `share(memory_id, audience, reason, layer="episode")` and `unshare(share_id)`, plus `shares(audience=None)` for listing.

Register them next to the other `@_server_tool()` definitions and follow the existing pattern exactly: call `_init()` first, log the call, return a plain dict. The published house is `ENGRAM_HOME/.engram/instances/lighthouse/graph.db`; resolve it the way `_genome_db_path` is resolved and fail with a clear error when it does not exist.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_share_tools.py
import pytest

import server
from tests.test_recall_margins import engram_server_env, seed  # noqa: F401


def test_share_returns_a_record_and_unshare_removes_it(engram_server_env):
    seed()
    episode = server.remember(content="a thing worth sharing")
    out = server.share(memory_id=episode["episode_id"], audience="commons", reason="meeting me")
    assert out["audience"] == "commons" and out["share_id"]
    assert any(s["share_id"] == out["share_id"] for s in server.shares()["shares"])
    assert server.unshare(share_id=out["share_id"])["removed"] is True
    assert server.shares()["shares"] == []


def test_bad_audience_is_an_error_not_a_crash(engram_server_env):
    seed()
    episode = server.remember(content="another thing")
    out = server.share(memory_id=episode["episode_id"], audience="everyone", reason="r")
    assert "error" in out and "audience" in out["error"]


def test_sharing_an_unknown_memory_is_an_error(engram_server_env):
    seed()
    out = server.share(memory_id="00000000-0000-4000-8000-000000000000", audience="commons", reason="r")
    assert "error" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_share_tools.py -q`
Expected: FAIL with `AttributeError: module 'server' has no attribute 'share'`

- [ ] **Step 3: Implement, then run the full suite**

```bash
.venv/bin/python -m pytest tests/ -q
```
Expected: the 1705 baseline plus every new test, 0 failed.

- [ ] **Step 4: Commit**

```bash
git add server.py tests/test_share_tools.py
git commit -m "server: share, unshare, and shares tools"
```

---

## Integration and acceptance

Lead merges dev1 then dev2 (dev1 owns `server.py`; dev2 rebases if needed) into `team/<slug>/integration`. Acceptance:

1. `.venv/bin/python -m pytest tests/ -q` shows the 1705 baseline plus all new tests, 0 failed.
2. `git diff --name-only <base>..<head>` contains only: `migrations/027_shared_memories.sql`, `sharing.py`, `policy_gen.py`, `lighthouse_daemon.py`, `server.py`, and the four new test files.
3. `grep -n "!= \"work\"" lighthouse_daemon.py` returns nothing: the lane rule is gone.
4. The daemon's existing suite still passes, proving deny-by-default, policy-before-retrieval, read-only access, and disclosure logging are intact.
5. No push. The human restarts the MCP server, generates the real policies, and migrates the three existing published rows.

## Self-review notes

Spec coverage: share as an act with provenance and copy semantics (Tasks 1, 2), closed audience vocabulary (Task 1), group file to receiver policy with the `engram:audiences` extension (Task 3), audience filter replacing the lane rule (Task 4), the MCP surface (Task 5). Deliberately not here: the receiver arm, the call site, the transition and impasse triggers, the retrospective margin study, and the sheaf overlap instrument. Those are the receiver-side plan. Type consistency: `ShareRecord` fields are identical in Tasks 1, 2, and 5; `audiences_for` is defined in Task 2 and consumed in Task 4; `audiences_for_instance` returns the same sorted list shape that Task 4 intersects against.
