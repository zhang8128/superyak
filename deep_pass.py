"""Between-session deep pass — counterfactual perception.

Runs structural and gap-specific lenses against passages that sessions
missed. Stores results as episodes. Called during sleep-time consolidation.
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEEP_PASS_MODEL = os.environ.get("ENGRAM_DEEP_PASS_MODEL", "qwen3:8b")
READER_DB = os.environ.get("READER_DB", str(Path.home() / ".reader" / "reader.db"))
STRUCTURAL_LENS_DIR = Path.home() / ".prism" / "packs" / "deep-pass"


def _call_ollama(system_prompt: str, user_prompt: str, timeout: int = 120) -> str:
    """Call Ollama with patient retry for shared GPU."""
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": DEEP_PASS_MODEL,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                    "options": {"temperature": 0.7},
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()["response"]
        except (requests.ConnectionError, requests.Timeout):
            if attempt < 2:
                logger.info("Ollama busy, waiting 30s (attempt %d/3)", attempt + 1)
                time.sleep(30)
            else:
                raise


def _format_passages_batch(passages: list[dict]) -> str:
    """Format multiple passages + reactions for a batch lens."""
    parts = []
    for i, p in enumerate(passages, 1):
        parts.append(
            f"--- Passage {i} ---\n{p['passage']}\n\nReader's reaction: {p['reaction']}"
        )
    return "\n\n".join(parts)


def run_structural_lenses(
    passages: list[dict],
    lenses: list[dict],
) -> list[dict]:
    """Run structural (batch) lenses across all passages.

    Each lens gets the full batch text. Returns list of
    {lens_name, lens_type, observation}. Skips lenses that fail.
    """
    if not passages:
        return []

    batch_text = _format_passages_batch(passages)
    results = []

    for lens in lenses:
        try:
            observation = _call_ollama(
                system_prompt=lens["prompt"],
                user_prompt=batch_text,
            )
            results.append({
                "lens_name": lens["name"],
                "lens_type": "structural",
                "observation": observation,
            })
        except Exception as e:
            logger.warning("Structural lens '%s' failed: %s", lens["name"], e)
            continue

    return results


def find_gap_domains(
    fired_history: dict[str, int],
    available_lenses: list[dict],
) -> list[dict]:
    """Find lens domains with zero fires.

    Args:
        fired_history: {lens_name: fire_count}
        available_lenses: List of lens dicts with name, domain, etc.

    Returns list of lens dicts with zero fires.
    """
    gaps = []
    for lens in available_lenses:
        if fired_history.get(lens["name"], 0) == 0:
            gaps.append(lens)
    return gaps


def run_gap_lenses(
    passages: list[dict],
    gap_lenses: list[dict],
) -> list[dict]:
    """Run gap-specific lenses — generated prompts for blind spot domains.

    For each gap lens, generates a prompt using its domain and sources.
    Returns list of {lens_name, lens_type, observation}.
    """
    if not passages or not gap_lenses:
        return []

    batch_text = _format_passages_batch(passages)
    results = []

    for lens in gap_lenses:
        domain = lens.get("domain", lens["name"])
        sources = lens.get("sources", [])
        source_text = f" Drawing on: {', '.join(sources)}." if sources else ""

        prompt = (
            f"These passages were read without attention to {domain}.{source_text} "
            f"What might this perspective notice that the reader didn't? "
            f"Don't summarize the passages. Identify what was missed."
        )

        try:
            observation = _call_ollama(
                system_prompt=prompt,
                user_prompt=batch_text,
            )
            results.append({
                "lens_name": lens["name"],
                "lens_type": "gap",
                "observation": observation,
            })
        except Exception as e:
            logger.warning("Gap lens '%s' failed: %s", lens["name"], e)
            continue

    return results


def load_structural_lenses() -> list[dict]:
    """Load structural lens definitions from YAML pack at ~/.prism/packs/deep-pass/."""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not available; cannot load structural lenses")
        return []

    lenses = []
    if not STRUCTURAL_LENS_DIR.exists():
        return lenses

    for path in sorted(STRUCTURAL_LENS_DIR.glob("*.yaml")):
        try:
            with open(path) as f:
                lens = yaml.safe_load(f)
            if lens and lens.get("mode") == "batch":
                lenses.append(lens)
        except Exception as e:
            logger.warning("Failed to load structural lens %s: %s", path, e)

    return lenses


def load_reading_lenses() -> list[dict]:
    """Load in-session reading lens definitions from ~/.prism/packs/reading/."""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not available; cannot load reading lenses")
        return []

    lens_dir = Path.home() / ".prism" / "packs" / "reading"
    lenses = []
    if not lens_dir.exists():
        return lenses

    for path in sorted(lens_dir.glob("*.yaml")):
        try:
            with open(path) as f:
                lens = yaml.safe_load(f)
            if lens:
                lenses.append(lens)
        except Exception as e:
            logger.warning("Failed to load reading lens %s: %s", path, e)

    return lenses


def get_recent_passages() -> list[dict]:
    """Fetch passage/reaction pairs from the reader's most recent session."""
    import sqlite3

    if not Path(READER_DB).exists():
        return []

    try:
        conn = sqlite3.connect(READER_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT passage, reaction FROM reactions
            WHERE session_id = (
                SELECT session_id FROM reactions ORDER BY created_at DESC LIMIT 1
            )
            ORDER BY position
            """
        ).fetchall()
        conn.close()
        return [{"passage": r["passage"], "reaction": r["reaction"]} for r in rows]
    except Exception as e:
        logger.warning("Failed to read passages from reader DB: %s", e)
        return []


def get_fired_history() -> dict[str, int]:
    """Get lens fire counts from the prism transition graph."""
    import sqlite3

    transitions_db = Path.home() / ".prism" / "reading-transitions.db"
    if not transitions_db.exists():
        return {}

    try:
        conn = sqlite3.connect(str(transitions_db))
        rows = conn.execute(
            "SELECT name, fired FROM nodes WHERE fired > 0"
        ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.warning("Failed to read fired history: %s", e)
        return {}


def deep_pass(storage, embeddings, session_id: str | None = None) -> dict:
    """Run the between-session deep pass.

    Called during sleep-time consolidation. Runs structural and gap lenses
    against missed passages, stores results as episodes.

    Returns summary: {structural_count, gap_count, skipped_reason?}
    """
    passages = get_recent_passages()
    if not passages:
        return {"structural_count": 0, "gap_count": 0, "skipped_reason": "no reading data"}

    structural_lenses = load_structural_lenses()
    structural_results = run_structural_lenses(passages, structural_lenses)

    fired = get_fired_history()
    reading_lenses = load_reading_lenses()
    gap_domains = find_gap_domains(fired, reading_lenses)
    gap_results = run_gap_lenses(passages, gap_domains)

    # Store all results as episodes
    all_results = structural_results + gap_results
    for result in all_results:
        episode_id = str(uuid.uuid4())
        content = (
            f"[Deep pass — {result['lens_type']}:{result['lens_name']}] "
            f"{result['observation']}"
        )
        context = {
            "deep_pass": True,
            "lens_type": result["lens_type"],
            "lens_name": result["lens_name"],
        }
        embedding = embeddings.embed([content], prefix="search_document")[0]
        storage.add_episode(
            episode_id,
            session_id,
            content,
            embedding=embedding,
            context=context,
        )
        storage.set_episode_source(
            episode_id,
            f"prism:deep-pass:{result['lens_type']}:{result['lens_name']}",
        )

    return {
        "structural_count": len(structural_results),
        "gap_count": len(gap_results),
    }
