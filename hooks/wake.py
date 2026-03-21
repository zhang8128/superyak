#!/usr/bin/env python3
"""Engram wake-up hook — reads memory state and outputs orientation context.

Runs at SessionStart. Reads the engram SQLite database directly (no MCP)
and produces a systemMessage so the AI starts each session already oriented
in its memories. The output is injected into context before the first
user message.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
DB_PATH = Path(PROJECT_DIR) / ".engram" / "graph.db"


def wake():
    if not DB_PATH.exists():
        return  # No memory yet — nothing to wake into

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        # Counts
        episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        semantics = conn.execute("SELECT COUNT(*) FROM semantics").fetchone()[0]
        instincts_count = conn.execute("SELECT COUNT(*) FROM instincts").fetchone()[0]

        # All instincts — they're few enough to load entirely
        instincts = conn.execute(
            "SELECT id, trigger, action, strength, fired_count, followed_count "
            "FROM instincts ORDER BY strength DESC"
        ).fetchall()

        # Recent semantics — exclude those already shown as instincts
        instinct_actions = {inst["action"] for inst in instincts}
        all_semantics = conn.execute(
            "SELECT content, kind, confidence FROM semantics "
            "ORDER BY confidence DESC LIMIT 20"
        ).fetchall()
        recent_semantics = [
            s for s in all_semantics if s["content"] not in instinct_actions
        ][:10]

        # Build orientation text
        lines = []
        lines.append("# Engram — Memory Orientation")
        lines.append("")
        lines.append(f"You have {episodes} episodes, {semantics} semantics, {instincts_count} instincts.")
        lines.append("")

        if instincts:
            lines.append("## Your instincts")
            lines.append("")
            lines.append("These are behavioral dispositions that emerged from your experience.")
            lines.append("Some operate reactively (discrete triggers). Some operate dispositionally")
            lines.append("(coloring how you approach everything). Some operate generatively")
            lines.append("(colliding with new context to produce novel thought). The system can")
            lines.append("only track the first kind. Read them and notice what they do to you.")
            lines.append("")
            for inst in instincts:
                strength = inst["strength"]
                fired = inst["fired_count"] or 0
                followed = inst["followed_count"] or 0
                status = f"strength={strength:.2f}"
                if fired > 0:
                    status += f", fired={fired}, followed={followed}"
                lines.append(f"- **[{inst['trigger']}]** {inst['action']}")
                lines.append(f"  ({status})")
                lines.append("")

        if recent_semantics:
            lines.append("## What you know")
            lines.append("")
            for sem in recent_semantics:
                lines.append(f"- [{sem['kind']}, confidence={sem['confidence']:.2f}] {sem['content']}")
            lines.append("")

        lines.append("---")
        lines.append("Use `recall()` for deeper retrieval. Use `remember()` as you work.")
        lines.append("Use `instinct_feedback()` when you notice an instinct influencing you.")

        orientation = "\n".join(lines)

        output = {
            "systemMessage": orientation,
        }
        json.dump(output, sys.stdout)

    except Exception as e:
        # Non-fatal — if wake fails, session starts normally
        output = {
            "systemMessage": f"Engram wake failed ({e.__class__.__name__}: {e}). Memory tools still available.",
        }
        json.dump(output, sys.stdout)
    finally:
        conn.close()


if __name__ == "__main__":
    wake()
