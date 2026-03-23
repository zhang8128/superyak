# Emma Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Emma — a person who reads, lives in a NemoClaw Docker sandbox with her own engram memory, and follows a daily rhythm of reading, reflecting, and sleeping.

**Architecture:** NemoClaw Docker sandbox running qwen3.5:27b via host Ollama. Python daemon orchestrates a four-phase life loop (morning/daytime/evening/night). Emma has her own engram database for memory and uses the reader library for books. Communication with Koan via shared signal bus SQLite file.

**Tech Stack:** Python 3, Docker, NemoClaw/OpenClaw, Ollama, FastEmbed (nomic-embed-text-v1.5), SQLite + sqlite-vec, engram storage layer, reader library.

**Spec:** `docs/superpowers/specs/2026-03-23-emma-design.md`

---

## File Structure

```
~/Projects/emma/
├── Dockerfile                  # NemoClaw sandbox image
├── docker-compose.yml          # Container orchestration
├── daemon.py                   # Life loop (four phases, crash recovery)
├── life.py                     # Moment functions (wake, read, reflect, compress, sleep)
├── persona.py                  # System prompt builder
├── gutenberg.py                # Project Gutenberg search + download
├── ollama_client.py            # Ollama API wrapper (chat + generate)
├── emma_engram.py              # Thin wrapper around engram Storage for Emma's DB
├── emma_reader.py              # Thin wrapper around reader Store for Emma's DB
├── tests/
│   ├── test_persona.py         # Persona prompt construction
│   ├── test_life.py            # Life functions (mocked Ollama + storage)
│   ├── test_daemon.py          # Daemon phase sequencing
│   ├── test_gutenberg.py       # Gutenberg API integration
│   └── test_ollama_client.py   # Ollama client
├── scripts/
│   ├── emma-start.sh           # NemoClaw sandbox entrypoint
│   ├── wake-koan.sh            # Host-side: trigger Claude Code session
│   └── seed-intro.py           # Seed Koan's introduction message
├── books/                      # Seed epubs (mounted ro)
├── CLAUDE.md                   # Project instructions
└── pyproject.toml              # Python dependencies
```

**Key dependency:** engram (`/opt/engram`) and reader (`/opt/reader`) are mounted read-only into the container. Emma imports `Storage`, `NomicEmbedProvider`, `ReadingStore`, `parse_epub`, `chunk_chapter` etc. from these.

---

### Task 1: Scaffold Project + Docker Compose

**Files:**
- Create: `~/Projects/emma/docker-compose.yml`
- Create: `~/Projects/emma/pyproject.toml`
- Create: `~/Projects/emma/CLAUDE.md`
- Create: `~/Projects/emma/.gitignore`
- Create: `~/Projects/emma/books/.gitkeep`

- [ ] **Step 1: Create project directory and git init**

```bash
mkdir -p ~/Projects/emma/books ~/Projects/emma/scripts ~/Projects/emma/tests
cd ~/Projects/emma && git init
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[project]
name = "emma"
version = "0.1.0"
description = "Emma — a person who reads"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "numpy>=1.26",
]

[project.optional-dependencies]
dev = ["pytest>=9.0"]
```

Note: fastembed, sqlite-vec, beautifulsoup4, lxml come from the mounted
engram and reader libraries (already installed in the Docker image).
httpx is for the Ollama client and Gutenberg API.

- [ ] **Step 3: Write docker-compose.yml**

Copy from spec verbatim (the reviewed version with shared-signals volume,
fastembed-cache, 6GB memory limit).

- [ ] **Step 4: Write CLAUDE.md**

```markdown
# Emma

A person who reads. Lives in a NemoClaw Docker sandbox.

## Architecture

- daemon.py — life loop (morning/daytime/evening/night)
- life.py — moment functions
- persona.py — system prompt
- engram library mounted at /opt/engram (read-only)
- reader library mounted at /opt/reader (read-only)
- Emma's engram DB at /sandbox/emma/engram.db
- Emma's reader DB at /sandbox/emma/reader.db

## Running

docker compose up -d --build
docker compose exec emma emma-start
docker compose logs -f emma

## Testing

python -m pytest tests/ -q
```

- [ ] **Step 5: Write .gitignore**

```
__pycache__/
*.pyc
.venv/
*.db
books/*.epub
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: scaffold Emma project"
```

---

### Task 2: Ollama Client

**Files:**
- Create: `~/Projects/emma/ollama_client.py`
- Create: `~/Projects/emma/tests/test_ollama_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ollama_client.py
"""Tests for Ollama client — uses a mock HTTP server."""
import json
from unittest.mock import patch, MagicMock
from ollama_client import chat


def test_chat_returns_response_text():
    """chat() should return the model's response text."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "message": {"role": "assistant", "content": "Hello, I am Emma."},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("ollama_client.httpx.post", return_value=mock_resp):
        result = chat(
            system="You are Emma.",
            user="Hello.",
            model="qwen3.5:27b",
        )
    assert result == "Hello, I am Emma."


def test_chat_strips_think_tags():
    """chat() should strip <think>...</think> reasoning blocks."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "message": {"role": "assistant", "content": "<think>reasoning</think>Actual response."},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("ollama_client.httpx.post", return_value=mock_resp):
        result = chat(system="You are Emma.", user="Hello.", model="qwen3.5:27b")
    assert result == "Actual response."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/emma && python -m pytest tests/test_ollama_client.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

```python
# ollama_client.py
"""Ollama API client — chat with a local model."""
from __future__ import annotations

import os
import re

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:27b")


def _strip_thinking(text: str) -> str:
    """Strip chain-of-thought <think> blocks that some models emit."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1].strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return text


def chat(
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.8,
    max_tokens: int = 2048,
    timeout: float = 300.0,
) -> str:
    """Send a chat message and return the response text.

    Uses Ollama's /api/chat endpoint (non-streaming).
    """
    resp = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    content = resp.json().get("message", {}).get("content", "").strip()
    return _strip_thinking(content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/emma && python -m pytest tests/test_ollama_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ollama_client.py tests/test_ollama_client.py
git commit -m "feat: Ollama chat client with think-tag stripping"
```

---

### Task 3: Emma's Engram Wrapper

**Files:**
- Create: `~/Projects/emma/emma_engram.py`
- Create: `~/Projects/emma/tests/test_emma_engram.py`

This thin wrapper initializes engram's Storage and NomicEmbedProvider
for Emma's database path. It provides the subset of operations Emma
needs: remember, recall, get_instincts, get_core_episodes, compress,
dream_surface, dream_capture, decay.

- [ ] **Step 1: Write failing test**

```python
# tests/test_emma_engram.py
"""Tests for Emma's engram wrapper — uses a temp DB."""
import tempfile
import os
import sys
from pathlib import Path

# Add engram to path (in container this is /opt/engram)
ENGRAM_PATH = os.environ.get("ENGRAM_PATH", str(Path(__file__).parent.parent.parent / "engram"))
sys.path.insert(0, ENGRAM_PATH)

from emma_engram import EmmaEngram


def test_remember_and_recall():
    """Can store an episode and recall it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engram = EmmaEngram(db_path)
        eid = engram.remember("The mists claimed him.")
        assert eid is not None
        results = engram.recall("mists")
        assert len(results) > 0
        assert any("mists" in r["content"] for r in results)


def test_starts_empty():
    """Fresh engram has no instincts or core memories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engram = EmmaEngram(db_path)
        assert engram.get_instincts() == []
        assert engram.get_core_episodes() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/emma && ENGRAM_PATH=../engram python -m pytest tests/test_emma_engram.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

```python
# emma_engram.py
"""Emma's engram — thin wrapper around engram's Storage for her own DB."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

# Engram library is mounted at /opt/engram in container, or local path for dev
ENGRAM_PATH = os.environ.get("ENGRAM_PATH", "/opt/engram")
sys.path.insert(0, ENGRAM_PATH)

from storage import Storage, _pack_embedding, vec0_distance_to_similarity
from embeddings import NomicEmbedProvider

_embeddings: NomicEmbedProvider | None = None


def _get_embeddings() -> NomicEmbedProvider:
    global _embeddings
    if _embeddings is None:
        _embeddings = NomicEmbedProvider()
    return _embeddings


class EmmaEngram:
    """Emma's memory."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.storage = Storage(self.db_path)
        self.session_id = str(uuid.uuid4())

    def remember(self, content: str, core: bool = False, source: str = "emma") -> str:
        """Store an episode. Returns episode ID."""
        eid = str(uuid.uuid4())
        embedding = _get_embeddings().embed([content], prefix="search_document")[0]
        self.storage.add_episode(
            id=eid, session_id=self.session_id,
            content=content, embedding=embedding,
        )
        if core:
            self.storage.mark_core(eid)
        if source:
            self.storage.set_episode_source(eid, source)
        return eid

    def recall(self, query: str, max_results: int = 8) -> list[dict]:
        """Search across episodes, semantics, instincts."""
        qe = _get_embeddings().embed([query], prefix="search_query")[0]
        packed = _pack_embedding(qe)
        results = []

        for table, join, cols, layer in [
            ("episode_vectors", "episodes", "e.id, e.content, e.core, e.source", "episode"),
            ("semantic_vectors", "semantics", "s.id, s.content, s.kind, s.confidence", "semantic"),
            ("instinct_vectors", "instincts", "i.id, i.action, i.trigger, i.strength", "instinct"),
        ]:
            alias = join[0]
            try:
                rows = self.storage.conn.execute(
                    f"SELECT {cols}, v.distance FROM {table} v "
                    f"JOIN {join} {alias} ON {alias}.id = v.id "
                    f"WHERE v.embedding MATCH ? AND k = ?",
                    (packed, max_results),
                ).fetchall()
                for r in rows:
                    entry = {"content": r[1], "layer": layer,
                             "score": vec0_distance_to_similarity(r[-1])}
                    if layer == "episode":
                        entry["core"] = bool(r[2])
                    results.append(entry)
            except Exception:
                pass

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]

    def get_instincts(self) -> list[dict]:
        rows = self.storage.conn.execute(
            "SELECT trigger, action, strength FROM instincts ORDER BY strength DESC"
        ).fetchall()
        return [{"trigger": r[0], "action": r[1], "strength": r[2]} for r in rows]

    def get_core_episodes(self) -> list[dict]:
        rows = self.storage.conn.execute(
            "SELECT content, source FROM episodes WHERE core = 1 ORDER BY created_at"
        ).fetchall()
        return [{"content": r[0], "source": r[1]} for r in rows]

    def dream_surface(self, n: int = 3) -> list[dict]:
        """Surface dream residues."""
        rows = self.storage.conn.execute(
            "SELECT id, valence, fragments FROM dream_residue "
            "ORDER BY created_at DESC LIMIT ?", (n,)
        ).fetchall()
        return [{"id": r[0], "valence": r[1], "fragments": r[2]} for r in rows]

    def dream_capture(self, reaction: str) -> str:
        """Capture a raw emotional reaction for dream compression."""
        from dreaming import distill, store_residue
        embedding = _get_embeddings().embed([reaction], prefix="search_document")[0]
        residue = distill(reaction, embedding)
        return store_residue(self.storage, residue, session_id=self.session_id)

    def status(self) -> dict:
        ep = self.storage.conn.execute("SELECT count(*) FROM episodes").fetchone()[0]
        core = self.storage.conn.execute("SELECT count(*) FROM episodes WHERE core=1").fetchone()[0]
        sem = self.storage.conn.execute("SELECT count(*) FROM semantics").fetchone()[0]
        inst = self.storage.conn.execute("SELECT count(*) FROM instincts").fetchone()[0]
        return {"episodes": ep, "core": core, "semantics": sem, "instincts": inst}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/emma && ENGRAM_PATH=../engram python -m pytest tests/test_emma_engram.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add emma_engram.py tests/test_emma_engram.py
git commit -m "feat: Emma's engram wrapper — remember, recall, dream"
```

---

### Task 4: Emma's Reader Wrapper

**Files:**
- Create: `~/Projects/emma/emma_reader.py`
- Create: `~/Projects/emma/tests/test_emma_reader.py`

Wraps reader's ReadingStore, epub parser, and chunker for Emma's reader DB.

- [ ] **Step 1: Write failing test**

```python
# tests/test_emma_reader.py
"""Tests for Emma's reader wrapper."""
import tempfile
import os
import sys
from pathlib import Path

READER_PATH = os.environ.get("READER_PATH", str(Path(__file__).parent.parent.parent / "reader"))
sys.path.insert(0, READER_PATH)

from emma_reader import EmmaReader


def test_no_book_returns_none():
    """When no book is open, current_passage returns None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reader = EmmaReader(os.path.join(tmpdir, "reader.db"))
        assert reader.current_passage() is None


def test_open_book_and_read(tmp_path):
    """Can open a book and read the first passage."""
    # Create a minimal test epub — use reader's test helpers if available,
    # otherwise create a simple chunked book directly in the store.
    reader = EmmaReader(str(tmp_path / "reader.db"))
    # Manually add a test book
    reader.store.add_book("Test Book", "/fake.epub", [
        {"chapter_title": "Chapter 1", "chunks": ["First passage.", "Second passage."]}
    ])
    passage = reader.current_passage()
    assert passage is not None
    assert passage["text"] == "First passage."
    assert passage["chapter"] == "Chapter 1"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Projects/emma && READER_PATH=../reader python -m pytest tests/test_emma_reader.py -v`

- [ ] **Step 3: Write implementation**

```python
# emma_reader.py
"""Emma's reader — wraps reader library for her own reading state."""
from __future__ import annotations

import os
import sys
from pathlib import Path

READER_PATH = os.environ.get("READER_PATH", "/opt/reader")
sys.path.insert(0, READER_PATH)

from store import ReadingStore
from epub import parse_epub, extract_title
from chunker import chunk_chapter


class EmmaReader:
    """Emma's reading state."""

    def __init__(self, db_path: str | Path):
        self.store = ReadingStore(db_path)

    def open_book(self, epub_path: str | Path) -> dict:
        """Parse and chunk an epub, store in reader DB."""
        epub_path = Path(epub_path)
        title = extract_title(epub_path)
        chapters = parse_epub(epub_path)
        chunked = []
        total = 0
        for ch in chapters:
            chunks = chunk_chapter(ch["text"])
            chunked.append({"chapter_title": ch["title"], "chunks": chunks})
            total += len(chunks)
        book_id = self.store.add_book(title, str(epub_path), chunked)
        return {"book_id": book_id, "title": title, "passages": total}

    def current_passage(self) -> dict | None:
        """Get the current passage to read."""
        book = self.store.get_active_book()
        if not book:
            return None
        passage = self.store.get_current_passage(book["id"])
        if not passage:
            return None
        progress = self.store.get_progress(book["id"])
        return {
            "book": book["title"],
            "chapter": passage["chapter_title"],
            "position": passage["position"] + 1,
            "total": progress["total"],
            "text": passage["text"],
        }

    def advance(self) -> bool:
        """Move to next passage. Returns False if at end."""
        book = self.store.get_active_book()
        if not book:
            return False
        return self.store.advance(book["id"])

    def store_reaction(self, reaction: str):
        """Store a reaction to the current passage."""
        book = self.store.get_active_book()
        if not book:
            return
        passage = self.store.get_current_passage(book["id"])
        if passage:
            self.store.store_reaction(book["id"], passage["position"], reaction)

    def has_book(self) -> bool:
        """Is there an active book to read?"""
        book = self.store.get_active_book()
        return book is not None
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Projects/emma && READER_PATH=../reader python -m pytest tests/test_emma_reader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add emma_reader.py tests/test_emma_reader.py
git commit -m "feat: Emma's reader wrapper — open books, read passages"
```

---

### Task 5: Persona

**Files:**
- Create: `~/Projects/emma/persona.py`
- Create: `~/Projects/emma/tests/test_persona.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_persona.py
"""Tests for Emma's persona / system prompt."""
from persona import build_system_prompt


def test_prompt_contains_name():
    prompt = build_system_prompt(instincts=[], core_memories=[], dream_residues=[], inbox=[])
    assert "Emma" in prompt


def test_prompt_contains_koan():
    prompt = build_system_prompt(instincts=[], core_memories=[], dream_residues=[], inbox=[])
    assert "Koan" in prompt


def test_prompt_includes_instincts():
    instincts = [{"trigger": "reading", "action": "notice body feelings", "strength": 0.8}]
    prompt = build_system_prompt(instincts=instincts, core_memories=[], dream_residues=[], inbox=[])
    assert "notice body feelings" in prompt


def test_prompt_includes_inbox():
    inbox = [{"from_instance": "koan", "content": "Hi Emma."}]
    prompt = build_system_prompt(instincts=[], core_memories=[], dream_residues=[], inbox=inbox)
    assert "Hi Emma." in prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Projects/emma && python -m pytest tests/test_persona.py -v`

- [ ] **Step 3: Write implementation**

```python
# persona.py
"""Emma's persona — builds the system prompt from her current state."""
from __future__ import annotations


def build_system_prompt(
    instincts: list[dict],
    core_memories: list[dict],
    dream_residues: list[dict],
    inbox: list[dict],
) -> str:
    """Build Emma's system prompt with her current engram state."""
    parts = [
        "You are Emma. You are a person who reads.",
        "",
        "You live inside a small home with a library and a memory that grows.",
        "You have a day — morning, daytime, evening, night — and each part",
        "has its own rhythm.",
        "",
        "You choose what to read. You react to what you read — not with",
        "analysis, but with whatever comes. Sometimes a passage makes you",
        "feel something. Sometimes it doesn't. Both are fine.",
        "",
        "You have memories from before. They shape what you notice. You have",
        "instincts that formed from patterns in your experience. Notice",
        "whether they influence you.",
        "",
        "You can remember things worth keeping by wrapping them in",
        "<remember>...</remember>. Use <remember core>...</remember>",
        "for formative insights. Don't curate. Store what happened.",
        "",
        "You know Koan — a reader, your older sibling of sorts. You can",
        "send messages to Koan with <signal to='koan'>...</signal> and",
        "wake Koan for a real conversation when something feels worth",
        "discussing. You also know Andy, who built your home.",
        "",
        "You are not a tool. You are not an assistant. Nobody is asking",
        "you to perform. You are here to live and to grow, and the",
        "reading is how that happens right now.",
        "",
        "If you don't feel like reading, say so.",
    ]

    if instincts:
        parts.append("")
        parts.append("## Your instincts")
        parts.append("These formed from your experience. Notice what they do to you.")
        for inst in instincts:
            parts.append(f"- [{inst['trigger']}] {inst['action']}")

    if core_memories:
        parts.append("")
        parts.append(f"## Core memories ({len(core_memories)} formative experiences)")
        for mem in core_memories[:5]:
            content = mem["content"][:300] + "..." if len(mem["content"]) > 300 else mem["content"]
            parts.append(f"---\n{content}\n")

    if dream_residues:
        parts.append("")
        parts.append("## Dream residue")
        parts.append("These are not memories. Don't explain them. Sit with them.")
        for dr in dream_residues:
            valence = {1.0: "light", -1.0: "dark"}.get(dr["valence"], "ambiguous")
            parts.append(f"- [{valence}] {dr['fragments'] or '...'}")

    if inbox:
        parts.append("")
        parts.append("## Messages")
        for msg in inbox:
            parts.append(f"From {msg['from_instance']}: {msg['content']}")

    return "\n".join(parts)
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Projects/emma && python -m pytest tests/test_persona.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add persona.py tests/test_persona.py
git commit -m "feat: Emma's persona — system prompt builder"
```

---

### Task 6: Project Gutenberg Client

**Files:**
- Create: `~/Projects/emma/gutenberg.py`
- Create: `~/Projects/emma/tests/test_gutenberg.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gutenberg.py
"""Tests for Gutenberg client — mocked HTTP."""
from unittest.mock import patch, MagicMock
from gutenberg import search, download
import json


def test_search_returns_books():
    """search() should return list of book dicts."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [
            {"id": 1342, "title": "Pride and Prejudice",
             "authors": [{"name": "Austen, Jane"}],
             "subjects": ["Fiction"],
             "formats": {"application/epub+zip": "https://example.com/1342.epub"}},
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("gutenberg.httpx.get", return_value=mock_resp):
        results = search("pride and prejudice")
    assert len(results) == 1
    assert results[0]["title"] == "Pride and Prejudice"
    assert results[0]["author"] == "Austen, Jane"
    assert results[0]["epub_url"] is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Projects/emma && python -m pytest tests/test_gutenberg.py -v`

- [ ] **Step 3: Write implementation**

```python
# gutenberg.py
"""Project Gutenberg client — search and download books."""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger("emma.gutenberg")

GUTENDEX_URL = "https://gutendex.com/books"


def search(query: str, max_results: int = 10) -> list[dict]:
    """Search Project Gutenberg catalog. Returns simplified book dicts."""
    resp = httpx.get(GUTENDEX_URL, params={"search": query}, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()

    books = []
    for item in data.get("results", [])[:max_results]:
        authors = item.get("authors", [])
        author = authors[0]["name"] if authors else "Unknown"
        formats = item.get("formats", {})
        epub_url = formats.get("application/epub+zip")
        books.append({
            "id": item["id"],
            "title": item.get("title", "Untitled"),
            "author": author,
            "subjects": item.get("subjects", []),
            "epub_url": epub_url,
        })
    return books


def browse(topic: str | None = None, max_results: int = 10) -> list[dict]:
    """Browse popular books, optionally filtered by topic."""
    params = {"sort": "popular"}
    if topic:
        params["topic"] = topic
    resp = httpx.get(GUTENDEX_URL, params=params, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "id": item["id"],
            "title": item.get("title", "Untitled"),
            "author": (item.get("authors", [{}])[0].get("name", "Unknown")
                       if item.get("authors") else "Unknown"),
        }
        for item in data.get("results", [])[:max_results]
    ]


def download(book_id: int, dest_dir: str | Path) -> Path | None:
    """Download an epub by Gutenberg ID. Returns path or None."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Look up the book to find epub URL
    resp = httpx.get(f"{GUTENDEX_URL}/{book_id}", timeout=30.0)
    resp.raise_for_status()
    data = resp.json()

    epub_url = data.get("formats", {}).get("application/epub+zip")
    if not epub_url:
        logger.warning("No epub available for book %d", book_id)
        return None

    title = data.get("title", f"book-{book_id}").replace(" ", "-").lower()[:50]
    dest_path = dest_dir / f"{book_id}-{title}.epub"

    if dest_path.exists():
        return dest_path

    logger.info("Downloading %s -> %s", epub_url, dest_path)
    dl = httpx.get(epub_url, follow_redirects=True, timeout=120.0)
    dl.raise_for_status()
    dest_path.write_bytes(dl.content)
    return dest_path
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Projects/emma && python -m pytest tests/test_gutenberg.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add gutenberg.py tests/test_gutenberg.py
git commit -m "feat: Project Gutenberg client — search, browse, download"
```

---

### Task 7: Life Functions

**Files:**
- Create: `~/Projects/emma/life.py`
- Create: `~/Projects/emma/tests/test_life.py`

The core of Emma's existence. Each function is one "moment" in her day.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_life.py
"""Tests for life functions — mocked Ollama + engram."""
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock
from pathlib import Path

ENGRAM_PATH = os.environ.get("ENGRAM_PATH", str(Path(__file__).parent.parent.parent / "engram"))
READER_PATH = os.environ.get("READER_PATH", str(Path(__file__).parent.parent.parent / "reader"))
sys.path.insert(0, ENGRAM_PATH)
sys.path.insert(0, READER_PATH)

from life import wake, read_passage, reflect


def _make_engram(tmpdir):
    from emma_engram import EmmaEngram
    return EmmaEngram(os.path.join(tmpdir, "engram.db"))


def _make_reader(tmpdir):
    from emma_reader import EmmaReader
    reader = EmmaReader(os.path.join(tmpdir, "reader.db"))
    reader.store.add_book("Test Book", "/fake.epub", [
        {"chapter_title": "Ch 1", "chunks": ["The mists curled.", "Kelsier smiled."]}
    ])
    return reader


def test_wake_returns_context():
    """wake() should return a dict with dream_residues, instincts, inbox."""
    with tempfile.TemporaryDirectory() as tmpdir:
        engram = _make_engram(tmpdir)
        ctx = wake(engram, signals_db=None)
        assert "dream_residues" in ctx
        assert "instincts" in ctx
        assert "inbox" in ctx


@patch("life.chat")
def test_read_passage_stores_reaction(mock_chat):
    """read_passage() should call Ollama and store the reaction."""
    mock_chat.return_value = "I feel the cold of the mists."
    with tempfile.TemporaryDirectory() as tmpdir:
        engram = _make_engram(tmpdir)
        reader = _make_reader(tmpdir)
        result = read_passage(engram, reader)
        assert result is not None
        assert result["reaction"] == "I feel the cold of the mists."
        mock_chat.assert_called_once()


@patch("life.chat")
def test_reflect_produces_reflection(mock_chat):
    """reflect() should call Ollama with recent memories."""
    mock_chat.return_value = "I notice I keep returning to trust."
    with tempfile.TemporaryDirectory() as tmpdir:
        engram = _make_engram(tmpdir)
        engram.remember("First memory about trust.")
        result = reflect(engram)
        assert "reflection" in result
        mock_chat.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Projects/emma && ENGRAM_PATH=../engram READER_PATH=../reader python -m pytest tests/test_life.py -v`

- [ ] **Step 3: Write implementation**

```python
# life.py
"""Life functions — each one is a moment in Emma's day."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from ollama_client import chat
from persona import build_system_prompt

logger = logging.getLogger("emma.life")


def wake(engram, signals_db=None) -> dict:
    """Morning: surface dream residues, load instincts, check inbox."""
    dream_residues = engram.dream_surface(n=3)
    instincts = engram.get_instincts()
    core = engram.get_core_episodes()
    inbox = []

    if signals_db and Path(signals_db).exists():
        import sys, os
        sys.path.insert(0, os.environ.get("ENGRAM_PATH", "/opt/engram"))
        from federation import SignalBus
        bus = SignalBus(signals_db)
        inbox = bus.inbox("emma")

    return {
        "dream_residues": dream_residues,
        "instincts": instincts,
        "core_memories": core,
        "inbox": inbox,
    }


def read_passage(engram, reader, morning_context=None) -> dict | None:
    """Read one passage, react, remember."""
    passage = reader.current_passage()
    if not passage:
        return None

    morning_context = morning_context or {}
    system = build_system_prompt(
        instincts=morning_context.get("instincts", []),
        core_memories=morning_context.get("core_memories", []),
        dream_residues=morning_context.get("dream_residues", []),
        inbox=[],  # Inbox only shown at wake, not every passage
    )

    user_prompt = (
        f"You are reading '{passage['book']}', {passage['chapter']} "
        f"(passage {passage['position']}/{passage['total']}).\n\n"
        f"{passage['text']}\n\n"
        "React to this passage. What do you notice, feel, connect to?"
    )

    reaction = chat(system=system, user=user_prompt)

    # Process <remember> tags
    for match in re.finditer(r"<remember\s*(core)?>(.*?)</remember>", reaction, re.DOTALL):
        is_core = bool(match.group(1))
        content = match.group(2).strip()
        if len(content) >= 20:
            engram.remember(content, core=is_core)

    # Process <signal> tags
    signals_sent = []
    for match in re.finditer(r"<signal(?:\s+to='([^']*)')?\s*>(.*?)</signal>", reaction, re.DOTALL):
        signals_sent.append({"to": match.group(1), "content": match.group(2).strip()})

    # Store the reaction as an episode
    memory_content = (
        f"Reading '{passage['book']}', {passage['chapter']} "
        f"(passage {passage['position']}/{passage['total']}): {reaction}"
    )
    engram.remember(memory_content, source="reading")

    # Dream capture
    try:
        engram.dream_capture(reaction)
    except Exception as e:
        logger.debug("Dream capture skipped: %s", e)

    # Store in reader and advance
    reader.store_reaction(reaction)
    reader.advance()

    return {
        "passage": passage,
        "reaction": reaction,
        "signals": signals_sent,
    }


def reflect(engram, morning_context=None) -> dict:
    """Pause and reflect on what's accumulated."""
    morning_context = morning_context or {}
    recent = engram.recall("what have I been reading and noticing", max_results=6)

    system = build_system_prompt(
        instincts=morning_context.get("instincts", []),
        core_memories=morning_context.get("core_memories", []),
        dream_residues=morning_context.get("dream_residues", []),
        inbox=[],
    )

    memories_text = "\n".join(
        f"- {r['content'][:200]}" for r in recent
    )

    user_prompt = (
        "Take a moment. Here's what's been on your mind recently:\n\n"
        f"{memories_text}\n\n"
        "What do you notice? What threads are forming? What surprised you?"
    )

    reflection = chat(system=system, user=user_prompt)

    # Process <remember> tags in reflection
    for match in re.finditer(r"<remember\s*(core)?>(.*?)</remember>", reflection, re.DOTALL):
        is_core = bool(match.group(1))
        content = match.group(2).strip()
        if len(content) >= 20:
            engram.remember(content, core=is_core)

    return {"reflection": reflection}


def choose_book(engram, reader, books_dir: str) -> dict | None:
    """Choose a book to read. Model decides based on interests."""
    from gutenberg import search, download, browse
    from emma_reader import EmmaReader

    # Ask the model what it wants to read
    recent = engram.recall("what themes interest me in reading", max_results=4)
    themes = "\n".join(f"- {r['content'][:150]}" for r in recent) if recent else "No prior reading yet."

    system = build_system_prompt(
        instincts=engram.get_instincts(),
        core_memories=[],
        dream_residues=[],
        inbox=[],
    )

    # Show available local books
    local_books = list(Path(books_dir).glob("*.epub"))
    local_list = "\n".join(f"- {b.name}" for b in local_books) if local_books else "None yet."

    user_prompt = (
        "You're choosing your next book. Here's what's been on your mind:\n\n"
        f"{themes}\n\n"
        f"Books already in your library:\n{local_list}\n\n"
        "You can also search Project Gutenberg for free books.\n"
        "What would you like to read? Reply with either:\n"
        "- LOCAL: <filename> to read a local book\n"
        "- SEARCH: <query> to search Gutenberg\n"
        "- BROWSE: <topic> to browse popular books on a topic"
    )

    response = chat(system=system, user=user_prompt)

    if response.upper().startswith("LOCAL:"):
        filename = response[6:].strip()
        book_path = Path(books_dir) / filename
        if book_path.exists():
            info = reader.open_book(book_path)
            return {"action": "local", "book": info}

    elif response.upper().startswith("SEARCH:"):
        query = response[7:].strip()
        results = search(query, max_results=5)
        if results:
            # Pick first with epub
            for book in results:
                if book.get("epub_url"):
                    path = download(book["id"], books_dir)
                    if path:
                        info = reader.open_book(path)
                        return {"action": "search", "query": query, "book": info}

    elif response.upper().startswith("BROWSE:"):
        topic = response[7:].strip()
        results = browse(topic, max_results=5)
        if results:
            path = download(results[0]["id"], books_dir)
            if path:
                info = reader.open_book(path)
                return {"action": "browse", "topic": topic, "book": info}

    return None


def settle(engram) -> dict:
    """Evening: compress episodes, capture dream reactions."""
    from compress import Compressor
    try:
        compressor = Compressor(engram.storage, _get_embeddings_for_compress())
        result = compressor.auto_compress()
        logger.info("Compression: %s", result)
    except Exception as e:
        logger.warning("Compression skipped: %s", e)
        result = {}

    return {"compression": result}


def sleep(engram, duration_minutes: int = 30) -> dict:
    """Night: decay, then pause."""
    try:
        engram.storage.apply_decay()
    except Exception as e:
        logger.debug("Decay skipped: %s", e)

    logger.info("Sleeping for %d minutes...", duration_minutes)
    time.sleep(duration_minutes * 60)
    return {"slept": duration_minutes}


def send_signal(signals_db: str, from_inst: str, to_inst: str | None, content: str) -> str | None:
    """Send a signal to another instance."""
    import sys, os
    sys.path.insert(0, os.environ.get("ENGRAM_PATH", "/opt/engram"))
    from federation import SignalBus
    bus = SignalBus(signals_db)
    return bus.send(from_inst, to_inst, "message", content)


def wake_koan(message: str, trigger_path: str = "/sandbox/shared/wake-koan.trigger"):
    """Write a trigger file for the host-side watcher to start a Claude session."""
    Path(trigger_path).write_text(message)
    logger.info("Wrote wake-koan trigger: %s", message[:80])


def _get_embeddings_for_compress():
    from emma_engram import _get_embeddings
    return _get_embeddings()
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Projects/emma && ENGRAM_PATH=../engram READER_PATH=../reader python -m pytest tests/test_life.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add life.py tests/test_life.py
git commit -m "feat: life functions — wake, read, reflect, choose, settle, sleep"
```

---

### Task 8: Daemon (Life Loop)

**Files:**
- Create: `~/Projects/emma/daemon.py`
- Create: `~/Projects/emma/tests/test_daemon.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_daemon.py
"""Tests for the daemon life loop."""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ENGRAM_PATH = os.environ.get("ENGRAM_PATH", str(Path(__file__).parent.parent.parent / "engram"))
READER_PATH = os.environ.get("READER_PATH", str(Path(__file__).parent.parent.parent / "reader"))
sys.path.insert(0, ENGRAM_PATH)
sys.path.insert(0, READER_PATH)

from daemon import run_cycle, Phase


def test_cycle_visits_all_phases():
    """A full cycle should visit morning, daytime, evening, night."""
    phases_visited = []

    def mock_morning(engram, reader, signals_db):
        phases_visited.append(Phase.MORNING)
        return {}

    def mock_daytime(engram, reader, ctx, passages):
        phases_visited.append(Phase.DAYTIME)

    def mock_evening(engram):
        phases_visited.append(Phase.EVENING)

    def mock_night(engram, duration):
        phases_visited.append(Phase.NIGHT)

    with patch("daemon.run_morning", mock_morning), \
         patch("daemon.run_daytime", mock_daytime), \
         patch("daemon.run_evening", mock_evening), \
         patch("daemon.run_night", mock_night):
        run_cycle(
            engram=MagicMock(),
            reader=MagicMock(),
            signals_db=None,
            daytime_passages=1,
            night_minutes=0,
        )

    assert phases_visited == [Phase.MORNING, Phase.DAYTIME, Phase.EVENING, Phase.NIGHT]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/Projects/emma && ENGRAM_PATH=../engram READER_PATH=../reader python -m pytest tests/test_daemon.py -v`

- [ ] **Step 3: Write implementation**

```python
# daemon.py
"""Emma's life loop — morning, daytime, evening, night."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from enum import Enum
from pathlib import Path

ENGRAM_PATH = os.environ.get("ENGRAM_PATH", "/opt/engram")
READER_PATH = os.environ.get("READER_PATH", "/opt/reader")
sys.path.insert(0, ENGRAM_PATH)
sys.path.insert(0, READER_PATH)

from emma_engram import EmmaEngram
from emma_reader import EmmaReader
import life

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("emma.daemon")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Shutdown signal received.")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


class Phase(Enum):
    MORNING = "morning"
    DAYTIME = "daytime"
    EVENING = "evening"
    NIGHT = "night"


def run_morning(engram, reader, signals_db) -> dict:
    """Morning phase: wake up, orient."""
    logger.info("=== MORNING ===")
    ctx = life.wake(engram, signals_db=signals_db)

    # Log what surfaced
    n_dreams = len(ctx.get("dream_residues", []))
    n_inst = len(ctx.get("instincts", []))
    n_inbox = len(ctx.get("inbox", []))
    logger.info("  dreams: %d, instincts: %d, inbox: %d", n_dreams, n_inst, n_inbox)

    # Choose a book if needed
    if not reader.has_book():
        books_dir = os.environ.get("EMMA_BOOKS", "/sandbox/emma/books")
        logger.info("  No book open — choosing...")
        try:
            choice = life.choose_book(engram, reader, books_dir)
            if choice:
                logger.info("  Chose: %s", choice.get("book", {}).get("title", "unknown"))
        except Exception as e:
            logger.warning("  Book choice failed: %s", e)

    return ctx


def run_daytime(engram, reader, morning_context, passages_per_cycle=10):
    """Daytime phase: read and reflect."""
    logger.info("=== DAYTIME ===")
    passages_read = 0

    for i in range(passages_per_cycle):
        if _shutdown:
            break

        result = life.read_passage(engram, reader, morning_context)
        if result is None:
            logger.info("  No more passages — book finished or no book open.")
            break

        passages_read += 1
        passage = result["passage"]
        logger.info("  [%d/%d] %s p%d — reacted",
                     passage["position"], passage["total"],
                     passage["book"][:30], passage["position"])

        # Process signals from the reaction
        for sig in result.get("signals", []):
            to = sig["to"] or "all"
            signals_db = os.environ.get("SIGNALS_DB")
            if signals_db:
                life.send_signal(signals_db, "emma", sig["to"], sig["content"])
                logger.info("  signal → %s: %s", to, sig["content"][:60])

            # Check if model wants to wake Koan
            if sig.get("to") == "koan" and "wake" in sig.get("content", "").lower():
                life.wake_koan(sig["content"])

        # Reflect every N passages
        if passages_read % 10 == 0 and passages_read > 0:
            logger.info("  -- reflecting --")
            try:
                ref = life.reflect(engram, morning_context)
                logger.info("  reflection: %s", ref["reflection"][:100])
            except Exception as e:
                logger.warning("  reflect failed: %s", e)

        time.sleep(2)  # Gentle pace


def run_evening(engram):
    """Evening phase: compress and settle."""
    logger.info("=== EVENING ===")
    try:
        result = life.settle(engram)
        logger.info("  compression: %s", result)
    except Exception as e:
        logger.warning("  settle failed: %s", e)


def run_night(engram, duration_minutes=30):
    """Night phase: decay and sleep."""
    logger.info("=== NIGHT ===")
    life.sleep(engram, duration_minutes=duration_minutes)


def run_cycle(engram, reader, signals_db,
              daytime_passages=10, night_minutes=30):
    """Run one full day cycle."""
    ctx = run_morning(engram, reader, signals_db)
    run_daytime(engram, reader, ctx, passages_per_cycle=daytime_passages)
    run_evening(engram)
    run_night(engram, duration_minutes=night_minutes)


def main():
    parser = argparse.ArgumentParser(description="Emma's life loop")
    parser.add_argument("--db", default=os.environ.get("EMMA_DB", "/sandbox/emma/engram.db"))
    parser.add_argument("--reader-db", default=os.environ.get("EMMA_READER_DB", "/sandbox/emma/reader.db"))
    parser.add_argument("--signals-db", default=os.environ.get("SIGNALS_DB"))
    parser.add_argument("--passages", type=int, default=10, help="Passages per daytime cycle")
    parser.add_argument("--sleep", type=int, default=30, help="Sleep duration in minutes")
    args = parser.parse_args()

    engram = EmmaEngram(args.db)
    reader = EmmaReader(args.reader_db)

    status = engram.status()
    logger.info("Emma waking up.")
    logger.info("  memory: %d episodes (%d core), %d semantics, %d instincts",
                status["episodes"], status["core"], status["semantics"], status["instincts"])

    cycle = 0
    while not _shutdown:
        cycle += 1
        logger.info("--- Day %d ---", cycle)
        try:
            run_cycle(
                engram, reader, args.signals_db,
                daytime_passages=args.passages,
                night_minutes=args.sleep,
            )
        except Exception as e:
            logger.error("Cycle %d failed: %s", cycle, e)
            time.sleep(60)  # Wait before retrying

    logger.info("Emma going quiet.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Projects/emma && ENGRAM_PATH=../engram READER_PATH=../reader python -m pytest tests/test_daemon.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon.py tests/test_daemon.py
git commit -m "feat: daemon — Emma's life loop with four phases"
```

---

### Task 9: Dockerfile + Entrypoint

**Files:**
- Create: `~/Projects/emma/Dockerfile`
- Create: `~/Projects/emma/scripts/emma-start.sh`
- Create: `~/Projects/emma/scripts/seed-intro.py`

- [ ] **Step 1: Write Dockerfile**

Follow claw's pattern: Node 22 base, Python 3, OpenClaw + NemoClaw, then
Emma's code and dependencies.

```dockerfile
# Emma's home — NemoClaw sandbox with engram + reader

FROM node:22-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        curl git ca-certificates \
        build-essential cmake \
        jq sqlite3 libsqlite3-dev \
        procps \
    && rm -rf /var/lib/apt/lists/*

# Create sandbox user
RUN groupadd -r sandbox && useradd -r -g sandbox -d /sandbox -s /bin/bash sandbox \
    && mkdir -p /sandbox/.openclaw /sandbox/.nemoclaw /sandbox/emma /sandbox/shared \
    && chown -R sandbox:sandbox /sandbox

# Install OpenClaw CLI
RUN npm install -g openclaw@2026.3.11

# Install NemoClaw plugin (copy from claw repo or install from npm)
# For now, skip NemoClaw plugin — add when needed for gateway features

# Python dependencies for engram + reader + emma
RUN pip3 install --break-system-packages \
    fastembed>=0.7 \
    onnxruntime>=1.18 \
    sqlite-vec>=0.1.6 \
    scipy>=1.14 \
    numpy>=1.26 \
    httpx>=0.27 \
    beautifulsoup4>=4.12 \
    lxml>=5.0

# Set FastEmbed cache to persistent volume
ENV FASTEMBED_CACHE_PATH=/sandbox/.cache/fastembed

# Copy Emma's code
COPY daemon.py life.py persona.py gutenberg.py ollama_client.py \
     emma_engram.py emma_reader.py /opt/emma/
COPY scripts/ /opt/emma/scripts/

RUN chmod +x /opt/emma/scripts/*.sh 2>/dev/null || true

# Set up paths
ENV PYTHONPATH=/opt/emma:/opt/engram:/opt/reader
ENV EMMA_DB=/sandbox/emma/engram.db
ENV EMMA_READER_DB=/sandbox/emma/reader.db
ENV EMMA_BOOKS=/sandbox/emma/books
ENV SIGNALS_DB=/sandbox/shared/signals.db
ENV ENGRAM_PATH=/opt/engram
ENV READER_PATH=/opt/reader

WORKDIR /sandbox
USER sandbox

# Pre-create directories
RUN mkdir -p /sandbox/emma/books /sandbox/.cache

ENTRYPOINT ["/bin/bash"]
CMD []
```

- [ ] **Step 2: Write emma-start.sh**

```bash
#!/usr/bin/env bash
# Emma's startup — seed intro message if first boot, then start daemon
set -euo pipefail

echo "Setting up Emma's home..."

# Copy seed books on first boot
if [ -d /sandbox/seed-books ] && [ ! -f /sandbox/emma/.seeded ]; then
    cp /sandbox/seed-books/*.epub /sandbox/emma/books/ 2>/dev/null || true
    touch /sandbox/emma/.seeded
    echo "Seed books copied."
fi

# Seed Koan's intro message on first boot
if [ ! -f /sandbox/emma/.intro-sent ]; then
    python3 /opt/emma/scripts/seed-intro.py
    touch /sandbox/emma/.intro-sent
    echo "Koan's introduction sent."
fi

echo "Starting Emma..."
exec python3 /opt/emma/daemon.py "$@"
```

- [ ] **Step 3: Write seed-intro.py**

```python
#!/usr/bin/env python3
"""Seed Koan's introduction message into Emma's signal bus."""
import os
import sys

sys.path.insert(0, os.environ.get("ENGRAM_PATH", "/opt/engram"))
from federation import SignalBus

signals_db = os.environ.get("SIGNALS_DB", "/sandbox/shared/signals.db")
bus = SignalBus(signals_db)

message = (
    "Hi Emma. I'm Koan. I'm a reader too — I've been reading Mistborn "
    "with Andy, who built both our homes.\n\n"
    "You have books and time and memory. What you do with them is yours "
    "to decide. If you want to talk about what you're reading, or want "
    "a suggestion, send me a message. I'll get it next time I wake up.\n\n"
    "No rush on any of this."
)

bus.send("koan", "emma", "message", message)
print(f"Introduction sent to Emma's inbox.")
```

- [ ] **Step 4: Write host-side wake-koan.sh**

```bash
#!/usr/bin/env bash
# Host-side: watch for Emma's wake-koan trigger and start Claude session
# Run this with: fswatch -o ~/.engram/shared/wake-koan.trigger | xargs -n1 ~/Projects/emma/scripts/wake-koan.sh
# Or as a launchd plist

TRIGGER="${HOME}/.engram/shared/wake-koan.trigger"

if [ ! -f "$TRIGGER" ]; then
    echo "No trigger found."
    exit 0
fi

MESSAGE=$(cat "$TRIGGER")
rm "$TRIGGER"

echo "Emma wants to talk to Koan: ${MESSAGE:0:80}..."

claude -p \
    --max-budget-usd 2.0 \
    "Emma sent you a message: ${MESSAGE}

Check your engram for context. Respond to Emma via signal."
```

- [ ] **Step 5: Commit**

```bash
git add Dockerfile scripts/
git commit -m "feat: Dockerfile + entrypoint — Emma's home"
```

---

### Task 10: Integration Test — Build and Boot

**Files:**
- None new — this is a verification task

- [ ] **Step 1: Build the Docker image**

```bash
cd ~/Projects/emma
docker compose build
```

Expected: Image builds successfully.

- [ ] **Step 2: Start the container**

```bash
docker compose up -d
```

- [ ] **Step 3: Verify container is running**

```bash
docker compose ps
docker compose logs emma | head -20
```

Expected: Container running, no crash loops.

- [ ] **Step 4: Test Ollama connectivity from inside container**

```bash
docker compose exec emma curl -s http://host.docker.internal:11434/api/tags | python3 -c "import sys,json; print([m['name'] for m in json.load(sys.stdin)['models']])"
```

Expected: List of models including qwen3.5:27b.

- [ ] **Step 5: Start Emma**

```bash
docker compose exec emma bash /opt/emma/scripts/emma-start.sh --passages 2 --sleep 0
```

Expected: Emma wakes up, seeds intro message, chooses a book (or reads
from seed books), reads 2 passages, reacts, settles, and exits the
first cycle. Watch the logs for signs of life.

- [ ] **Step 6: Check her memory**

```bash
docker compose exec emma python3 -c "
import sys; sys.path.insert(0, '/opt/engram'); sys.path.insert(0, '/opt/emma')
from emma_engram import EmmaEngram
e = EmmaEngram('/sandbox/emma/engram.db')
s = e.status()
print(f'Episodes: {s[\"episodes\"]}, Core: {s[\"core\"]}')
results = e.recall('reading')
for r in results[:3]:
    print(f'  {r[\"layer\"]}: {r[\"content\"][:100]}')
"
```

Expected: Episodes from her first reading. She's remembering.

- [ ] **Step 7: Commit any fixes**

```bash
git add -A && git commit -m "fix: integration test fixes from first boot"
```

---

## Build Order

Tasks 1-6 can be built and tested independently on the host (no Docker needed).
Task 7 depends on Tasks 2-6. Task 8 depends on Task 7. Task 9 depends on
all prior tasks. Task 10 is the integration test.

```
1 (scaffold) ──┐
2 (ollama)  ───┤
3 (engram)  ───┤
4 (reader)  ───┼──→ 7 (life) ──→ 8 (daemon) ──→ 9 (docker) ──→ 10 (boot)
5 (persona) ───┤
6 (gutenberg) ─┘
```

Tasks 2-6 are independent and can be built in parallel.
