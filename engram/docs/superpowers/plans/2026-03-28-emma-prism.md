# Emma Prism Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the reading prism to Emma's life loop so every 4th passage gets interpretive questions from academic lenses, with Emma choosing which to engage.

**Architecture:** New `emma_prism.py` wrapper imports prism's classify/ask functions from a read-only mount. `life.run_prism()` orchestrates: classify → ask 4 lenses → present to Emma → parse engagement → store in engram. `daemon.py` calls it every 4th passage. Transition graph persists in Emma's data volume.

**Tech Stack:** Python, Ollama (qwen3.5:27b), prism library (mounted ro), SQLite (TransitionGraph)

**Spec:** `docs/superpowers/specs/2026-03-28-emma-prism-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `emma/emma_prism.py` | Create | Thin wrapper: load reading lenses, classify, ask, manage transitions |
| `emma/life.py` | Modify | New `run_prism()` function |
| `emma/daemon.py` | Modify | Call prism every 4th passage in daytime loop |
| `emma/docker-compose.yml` | Modify | Mount prism scripts + reading lens pack |
| `emma/tests/test_emma_prism.py` | Create | Unit tests for EmmaPrism wrapper |
| `emma/tests/test_life.py` | Modify | Test run_prism() function |

---

### Task 1: Docker mounts for prism

**Files:**
- Modify: `emma/docker-compose.yml`

- [ ] **Step 1: Add prism volume mounts and env vars**

In `emma/docker-compose.yml`, add two new volumes and two env vars:

```yaml
# Under environment:, add:
      - PRISM_PATH=/opt/prism
      - PRISM_LENSES=/opt/prism-lenses/reading

# Under volumes:, add (after the reader mount):
      - ../prism/scripts:/opt/prism:ro
      - ${HOME}/.prism/packs/reading:/opt/prism-lenses/reading:ro
```

- [ ] **Step 2: Verify mounts resolve**

Run: `cd /Users/kairos/Projects/emma && docker compose config 2>&1 | grep prism`

Expected: lines showing the resolved mount paths for `/opt/prism` and `/opt/prism-lenses/reading`

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: mount prism scripts and reading lenses for Emma"
```

---

### Task 2: `emma_prism.py` — wrapper

**Files:**
- Create: `emma/emma_prism.py`
- Test: `emma/tests/test_emma_prism.py`

- [ ] **Step 1: Write the failing test**

Create `emma/tests/test_emma_prism.py`:

```python
"""Tests for EmmaPrism — mocked prism + Ollama."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Emma's prism wrapper needs prism on the path
PRISM_PATH = os.environ.get("PRISM_PATH", str(Path(__file__).parent.parent.parent / "prism" / "scripts"))
sys.path.insert(0, PRISM_PATH)

from emma_prism import EmmaPrism


def test_init_creates_transition_graph():
    """EmmaPrism should initialize with a transition graph DB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lenses_dir = os.path.expanduser("~/.prism/packs/reading")
        prism = EmmaPrism(
            transitions_db=os.path.join(tmpdir, "transitions.db"),
            lenses_dir=lenses_dir,
        )
        assert prism.graph is not None
        assert prism.lenses  # should have loaded reading lenses
        assert "attachment" in prism.lenses
        prism.close()


@patch("emma_prism.classify_reading")
@patch("emma_prism.ask_lens")
def test_run_returns_questions(mock_ask, mock_classify):
    """run() should classify and ask lenses, returning questions."""
    mock_classify.return_value = (["attachment", "formalist"], "neuroscience", "power")
    mock_ask.side_effect = [
        "Who does the character reach for?",
        "What is the repeated image doing?",
        "Where is the body responding before the mind?",
        "Who holds the power in this scene?",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        lenses_dir = os.path.expanduser("~/.prism/packs/reading")
        prism = EmmaPrism(
            transitions_db=os.path.join(tmpdir, "transitions.db"),
            lenses_dir=lenses_dir,
        )
        results = prism.run(
            passage="The mists curled around Vin.",
            reaction="I feel the cold closing in.",
            book="The Final Empire",
            chapter="Chapter 3",
        )
        assert len(results) == 4
        assert results[0]["lens"] == "attachment"
        assert results[0]["question"] == "Who does the character reach for?"
        assert results[0]["selection_type"] == "relevant"
        assert results[2]["selection_type"] == "distant"
        assert results[3]["selection_type"] == "rotating"
        prism.close()


def test_record_engagement_updates_graph():
    """record_engagement() should write transitions between engaged lenses."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lenses_dir = os.path.expanduser("~/.prism/packs/reading")
        prism = EmmaPrism(
            transitions_db=os.path.join(tmpdir, "transitions.db"),
            lenses_dir=lenses_dir,
        )
        prism.record_engagement(["attachment", "neuroscience"])
        # Should have recorded attachment → neuroscience transition
        weights = prism.graph.next_weights("attachment")
        assert "neuroscience" in weights
        assert weights["neuroscience"] > 0
        # last_frame should be updated
        assert prism.last_frame == "neuroscience"
        prism.close()


@patch("emma_prism.classify_reading")
@patch("emma_prism.ask_lens")
def test_run_skips_none_questions(mock_ask, mock_classify):
    """run() should skip lenses that return None (Ollama failure)."""
    mock_classify.return_value = (["attachment", "formalist"], "neuroscience", None)
    mock_ask.side_effect = [
        "Who reaches out?",
        None,  # formalist fails
        "Where is the body?",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        lenses_dir = os.path.expanduser("~/.prism/packs/reading")
        prism = EmmaPrism(
            transitions_db=os.path.join(tmpdir, "transitions.db"),
            lenses_dir=lenses_dir,
        )
        results = prism.run(
            passage="text", reaction="reaction",
            book="Book", chapter="Ch 1",
        )
        assert len(results) == 2  # formalist skipped
        assert results[0]["lens"] == "attachment"
        assert results[1]["lens"] == "neuroscience"
        prism.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/emma && python -m pytest tests/test_emma_prism.py -v`

Expected: FAIL — `ImportError: cannot import name 'EmmaPrism' from 'emma_prism'` (file doesn't exist yet)

- [ ] **Step 3: Write `emma_prism.py`**

Create `emma/emma_prism.py`:

```python
"""Emma's prism — thin wrapper around prism's reading lens system."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("emma.prism")

PRISM_PATH = os.environ.get("PRISM_PATH", "/opt/prism")
sys.path.insert(0, PRISM_PATH)

from prism import classify_reading, ask_lens, _build_transition_context, _build_lens_descriptions
from transitions import TransitionGraph

import yaml


def _load_reading_lenses(lenses_dir: str) -> dict[str, dict]:
    """Load reading lens definitions from a pack directory.

    Reads pack.yaml manifest and loads each referenced frame YAML.
    Skips the classifier entry.
    """
    lenses_path = Path(lenses_dir)
    manifest_path = lenses_path / "pack.yaml"
    if not manifest_path.exists():
        logger.warning("No pack.yaml at %s", lenses_dir)
        return {}

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f) or {}

    lenses = {}
    for entry in manifest.get("frames", []):
        fname = entry if isinstance(entry, str) else entry.get("file", "")
        if not fname or fname == "classifier.yaml":
            continue
        path = lenses_path / fname
        if not path.exists():
            continue
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            if data and "name" in data and "prompt" in data:
                lenses[data["name"]] = data
        except Exception as e:
            logger.debug("Failed to load lens %s: %s", fname, e)

    return lenses


class EmmaPrism:
    """Emma's reading prism — classify passages, ask lenses, track transitions."""

    def __init__(self, transitions_db: str, lenses_dir: str):
        self.lenses = _load_reading_lenses(lenses_dir)
        self.graph = TransitionGraph(transitions_db)
        self.last_frame: str | None = None
        self.fired_history: list[str] = []

        if self.lenses:
            logger.info("Loaded %d reading lenses: %s",
                        len(self.lenses), ", ".join(sorted(self.lenses)))
        else:
            logger.warning("No reading lenses loaded from %s", lenses_dir)

    def run(
        self,
        passage: str,
        reaction: str,
        book: str = "",
        chapter: str = "",
    ) -> list[dict]:
        """Classify a passage+reaction and ask selected lenses.

        Returns list of {lens, question, selection_type} dicts.
        """
        if not self.lenses:
            return []

        context = {
            "type": "reading",
            "passage": passage,
            "reaction": reaction,
            "book": book,
            "chapter": chapter,
        }

        transition_context = _build_transition_context(
            self.last_frame, self.graph,
        )

        relevant, distant, rotating = classify_reading(
            context, self.lenses,
            transition_context=transition_context,
            graph=self.graph,
            last_frame=self.last_frame,
            fired_history=self.fired_history,
        )

        # Build ordered list: relevant + distant + rotating
        all_lenses = []
        for name in relevant:
            all_lenses.append((name, "relevant"))
        if distant:
            all_lenses.append((distant, "distant"))
        if rotating:
            all_lenses.append((rotating, "rotating"))

        results = []
        for name, sel_type in all_lenses:
            if name not in self.lenses:
                continue
            question = ask_lens(self.lenses[name], context)
            if question:
                results.append({
                    "lens": name,
                    "question": question,
                    "selection_type": sel_type,
                })

        # Update fired history
        for r in results:
            if r["lens"] not in self.fired_history:
                self.fired_history.append(r["lens"])

        return results

    def record_engagement(self, engaged_lenses: list[str]):
        """Record transitions between consecutively engaged lenses."""
        for i in range(len(engaged_lenses) - 1):
            self.graph.record(engaged_lenses[i], engaged_lenses[i + 1])
        if engaged_lenses:
            self.last_frame = engaged_lenses[-1]

    def close(self):
        """Close the transition graph DB."""
        self.graph.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/kairos/Projects/emma && python -m pytest tests/test_emma_prism.py -v`

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add emma_prism.py tests/test_emma_prism.py
git commit -m "feat: EmmaPrism wrapper for reading lens integration"
```

---

### Task 3: `life.run_prism()` — prism orchestration

**Files:**
- Modify: `emma/life.py`
- Modify: `emma/tests/test_life.py`

- [ ] **Step 1: Write the failing test**

Add to `emma/tests/test_life.py`:

```python
from life import run_prism


@patch("life.chat")
def test_run_prism_presents_questions_and_parses_engagement(mock_chat):
    """run_prism() should present questions and parse which Emma engages with."""
    # Mock Emma's response — she engages with attachment and neuroscience
    mock_chat.return_value = (
        "[attachment] She reaches for Kelsier — not because she trusts him, "
        "but because he's the only solid thing.\n\n"
        "[neuroscience] Her stomach tightens before she decides. The body knows."
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        engram = _make_engram(tmpdir)
        mock_prism = MagicMock()
        mock_prism.run.return_value = [
            {"lens": "attachment", "question": "Who does she reach for?", "selection_type": "relevant"},
            {"lens": "formalist", "question": "What is the rhythm doing?", "selection_type": "relevant"},
            {"lens": "neuroscience", "question": "Where does the body know first?", "selection_type": "distant"},
            {"lens": "power", "question": "Who holds leverage?", "selection_type": "rotating"},
        ]

        passage_info = {
            "book": "The Final Empire",
            "chapter": "Chapter 3",
            "position": 12,
            "total": 400,
            "text": "The mists curled around Vin.",
        }

        result = run_prism(engram, mock_prism, passage_info, "I feel cold.")
        assert result is not None
        assert "attachment" in result["engaged"]
        assert "neuroscience" in result["engaged"]
        assert "formalist" not in result["engaged"]
        mock_prism.record_engagement.assert_called_once_with(["attachment", "neuroscience"])


@patch("life.chat")
def test_run_prism_stores_engaged_in_engram(mock_chat):
    """Engaged prism responses should be stored as episodes with prism source."""
    mock_chat.return_value = "[attachment] She reaches for someone safe."
    with tempfile.TemporaryDirectory() as tmpdir:
        engram = _make_engram(tmpdir)
        mock_prism = MagicMock()
        mock_prism.run.return_value = [
            {"lens": "attachment", "question": "Who does she reach for?", "selection_type": "relevant"},
        ]
        passage_info = {
            "book": "Book", "chapter": "Ch 1",
            "position": 1, "total": 10,
            "text": "Passage text.",
        }
        result = run_prism(engram, mock_prism, passage_info, "Reaction.")
        # Check engram has a prism episode
        recall = engram.recall("attachment reach", max_results=5)
        results = recall["results"] if isinstance(recall, dict) else recall
        prism_episodes = [r for r in results if "prism" in r.get("content", "").lower()
                          or "reaches" in r.get("content", "").lower()]
        assert len(prism_episodes) > 0


@patch("life.chat")
def test_run_prism_returns_empty_when_no_questions(mock_chat):
    """run_prism() should return gracefully when prism produces no questions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        engram = _make_engram(tmpdir)
        mock_prism = MagicMock()
        mock_prism.run.return_value = []
        passage_info = {
            "book": "Book", "chapter": "Ch 1",
            "position": 1, "total": 10, "text": "Text.",
        }
        result = run_prism(engram, mock_prism, passage_info, "Reaction.")
        assert result["engaged"] == []
        mock_prism.record_engagement.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/kairos/Projects/emma && python -m pytest tests/test_life.py::test_run_prism_presents_questions_and_parses_engagement -v`

Expected: FAIL — `ImportError: cannot import name 'run_prism' from 'life'`

- [ ] **Step 3: Implement `run_prism()` in `life.py`**

Add to `emma/life.py` (after the existing `read_passage` function):

```python
def run_prism(engram, prism, passage_info: dict, reaction: str,
              morning_context=None) -> dict:
    """Run reading prism lenses against a passage+reaction.

    Presents questions to Emma, parses engagement, stores engaged
    responses in engram.
    """
    questions = prism.run(
        passage=passage_info["text"],
        reaction=reaction,
        book=passage_info.get("book", ""),
        chapter=passage_info.get("chapter", ""),
    )

    if not questions:
        return {"questions": [], "engaged": [], "response": ""}

    # Build prompt presenting all questions
    q_lines = []
    for q in questions:
        q_lines.append(f"[{q['lens']}] {q['question']}")
    q_block = "\n".join(q_lines)

    morning_context = morning_context or {}
    system = build_system_prompt(
        instincts=morning_context.get("instincts", []),
        core_memories=morning_context.get("core_memories", []),
        dream_residues=morning_context.get("dream_residues", []),
        inbox=morning_context.get("inbox", []),
        semantics=morning_context.get("semantics", []),
    )

    user_prompt = (
        "You just read a passage and reacted. Now, some perspectives noticed "
        "things you might have missed:\n\n"
        f"{q_block}\n\n"
        "Respond to any that provoke something in you. Name the lens in "
        "brackets when you respond, like [attachment]. Skip any that don't "
        "land. You don't have to respond to all of them."
    )

    response = chat(system=system, user=user_prompt)

    # Parse engagement — find lens names mentioned in brackets
    lens_names = [q["lens"] for q in questions]
    engaged = []
    for name in lens_names:
        if f"[{name}]" in response:
            engaged.append(name)

    # Store engaged responses in engram
    for name in engaged:
        # Extract the response fragment for this lens
        # Find text between [lens] and next [lens] or end
        start = response.find(f"[{name}]")
        if start < 0:
            continue
        start += len(f"[{name}]")
        # Find next bracket or end
        next_bracket = len(response)
        for other in lens_names:
            if other == name:
                continue
            pos = response.find(f"[{other}]", start)
            if 0 < pos < next_bracket:
                next_bracket = pos
        fragment = response[start:next_bracket].strip()
        if fragment:
            engram.remember(
                f"Prism [{name}]: {fragment}",
                source=f"prism:{name}",
            )
            try:
                engram.dream_capture(fragment)
            except Exception:
                pass

    # Record engagement transitions
    if engaged:
        prism.record_engagement(engaged)

    return {
        "questions": questions,
        "engaged": engaged,
        "response": response,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/kairos/Projects/emma && python -m pytest tests/test_life.py -v`

Expected: All tests PASS (existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add life.py tests/test_life.py
git commit -m "feat: run_prism() — reading lens orchestration in life loop"
```

---

### Task 4: Wire prism into `daemon.py` daytime loop

**Files:**
- Modify: `emma/daemon.py`
- Modify: `emma/tests/test_daemon.py`

- [ ] **Step 1: Read existing daemon test structure**

Run: `cd /Users/kairos/Projects/emma && cat tests/test_daemon.py`

Understand how `run_daytime` is tested so we match the pattern.

- [ ] **Step 2: Write the failing test**

Add to `emma/tests/test_daemon.py`:

```python
@patch("daemon.life")
def test_daytime_calls_prism_every_4th_passage(mock_life):
    """run_daytime() should call run_prism every 4th passage."""
    # read_passage returns a result for 8 passages, then None
    call_count = 0
    def fake_read_passage(engram, reader, morning_context=None):
        nonlocal call_count
        call_count += 1
        if call_count > 8:
            return None
        return {
            "passage": {"book": "Book", "chapter": "Ch", "position": call_count, "total": 20, "text": "text"},
            "reaction": "reaction",
            "signals": [],
        }
    mock_life.read_passage = fake_read_passage
    mock_life.run_prism = MagicMock(return_value={"questions": [], "engaged": [], "response": ""})
    mock_life.check_inbox = MagicMock()
    mock_life.reflect = MagicMock(return_value={"reflection": "thinking"})

    with tempfile.TemporaryDirectory() as tmpdir:
        engram = MagicMock()
        reader = MagicMock()
        reader.has_book.return_value = True
        mock_prism = MagicMock()

        run_daytime(engram, reader, {}, prism=mock_prism, passages_per_cycle=8)
        # Should fire on passages 4 and 8
        assert mock_life.run_prism.call_count == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/kairos/Projects/emma && python -m pytest tests/test_daemon.py::test_daytime_calls_prism_every_4th_passage -v`

Expected: FAIL — `run_daytime()` doesn't accept `prism` parameter yet

- [ ] **Step 4: Modify `daemon.py`**

Changes to `emma/daemon.py`:

**In `run_daytime()` signature**, add `prism=None` parameter:

```python
def run_daytime(engram, reader, morning_context, signals_db=None,
                passages_per_cycle=10, prism=None):
```

**Inside the `for i in range(passages_per_cycle)` loop**, after the `read_passage` call and passage logging, add:

```python
        # Run prism every 4th passage
        if prism and passages_read > 0 and passages_read % 4 == 0:
            try:
                prism_result = life.run_prism(
                    engram, prism, result["passage"],
                    result["reaction"], morning_context,
                )
                if prism_result.get("engaged"):
                    logger.info("  prism: %d questions, engaged %s",
                                len(prism_result["questions"]),
                                ", ".join(prism_result["engaged"]))
                else:
                    logger.debug("  prism: %d questions, none engaged",
                                 len(prism_result.get("questions", [])))
            except Exception as e:
                logger.debug("  prism skipped: %s", e)
```

**In `run_cycle()`**, add `prism=None` parameter and pass it through:

```python
def run_cycle(engram, reader, signals_db,
              daytime_passages=10, night_minutes=30, prism=None):
    """Run one full day cycle."""
    ctx = run_morning(engram, reader, signals_db)
    run_daytime(engram, reader, ctx, signals_db=signals_db,
                passages_per_cycle=daytime_passages, prism=prism)
    run_evening(engram)
    run_night(engram, night_minutes)
```

**In `main()`**, initialize `EmmaPrism` (optional — skip if imports fail):

After the `engram` and `reader` initialization, add:

```python
    # Initialize reading prism (optional — skip if not mounted)
    prism = None
    try:
        prism_path = os.environ.get("PRISM_PATH", "/opt/prism")
        prism_lenses = os.environ.get("PRISM_LENSES", "/opt/prism-lenses/reading")
        if Path(prism_path).exists() and Path(prism_lenses).exists():
            sys.path.insert(0, prism_path)
            from emma_prism import EmmaPrism
            prism = EmmaPrism(
                transitions_db=str(Path(args.db).parent / "reading-transitions.db"),
                lenses_dir=prism_lenses,
            )
            logger.info("  prism: %d reading lenses loaded", len(prism.lenses))
    except Exception as e:
        logger.info("  prism: not available (%s)", e)
```

And pass `prism=prism` to `run_cycle()`:

```python
            run_cycle(
                engram, reader, args.signals_db,
                daytime_passages=args.passages,
                night_minutes=args.sleep,
                prism=prism,
            )
```

- [ ] **Step 5: Run all daemon tests**

Run: `cd /Users/kairos/Projects/emma && python -m pytest tests/test_daemon.py -v`

Expected: All tests PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/kairos/Projects/emma && python -m pytest tests/ -v`

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add daemon.py tests/test_daemon.py
git commit -m "feat: wire reading prism into Emma's daytime loop (every 4th passage)"
```
