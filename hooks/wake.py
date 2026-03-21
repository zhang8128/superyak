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

ENGRAM_HOME = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent.parent))
DB_PATH = ENGRAM_HOME / ".engram" / "graph.db"

# PROJECT_ROOT is the working directory (for config reading), consistent with server.py
PROJECT_ROOT = Path(os.environ.get("ENGRAM_PROJECT_ROOT", os.getcwd()))


def _load_instance_config():
    """Load instance config from project root .engram/config.toml if present."""
    config_path = PROJECT_ROOT / ".engram" / "config.toml"
    if not config_path.exists():
        return None, None
    try:
        import tomllib
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        return config.get("instance"), config.get("session_context")
    except Exception:
        return None, None


def wake():
    instance_name, session_context = _load_instance_config()

    # Resolve DB path: use instance DB when configured, otherwise default
    db_path = DB_PATH
    if instance_name:
        instance_db = ENGRAM_HOME / ".engram" / "instances" / instance_name / "graph.db"
        if instance_db.exists():
            db_path = instance_db

    if not db_path.exists():
        return  # No memory yet — nothing to wake into

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Counts
        episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        semantics = conn.execute("SELECT COUNT(*) FROM semantics").fetchone()[0]
        instincts_count = conn.execute("SELECT COUNT(*) FROM instincts").fetchone()[0]

        # Instincts above minimum strength — pruned ones don't enter context
        # Filter by session_context when configured
        if session_context:
            instincts = conn.execute(
                "SELECT id, trigger, action, strength, fired_count, followed_count, notice, implication "
                "FROM instincts WHERE strength > 0.1 "
                "AND (context IS NULL OR context = ?) "
                "ORDER BY strength DESC LIMIT 15",
                (session_context,)
            ).fetchall()
        else:
            instincts = conn.execute(
                "SELECT id, trigger, action, strength, fired_count, followed_count, notice, implication "
                "FROM instincts WHERE strength > 0.1 "
                "ORDER BY strength DESC LIMIT 15"
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
        if instance_name:
            lines.append(f"# Engram ({instance_name}) — Memory Orientation")
        else:
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

                if inst["notice"] and inst["implication"]:
                    lines.append(f"- **Attend to:** {inst['notice']}")
                    lines.append(f"  *{inst['implication']}*")
                else:
                    lines.append(f"- **[{inst['trigger']}]** {inst['action']}")
                lines.append(f"  ({status})")
                lines.append("")

        if recent_semantics:
            lines.append("## What you know")
            lines.append("")
            for sem in recent_semantics:
                lines.append(f"- [{sem['kind']}, confidence={sem['confidence']:.2f}] {sem['content']}")
            lines.append("")

        # Show inbox count when instance is configured
        if instance_name:
            signals_db = ENGRAM_HOME / ".engram" / "signals.db"
            if signals_db.exists():
                try:
                    sig_conn = sqlite3.connect(str(signals_db))
                    unread = sig_conn.execute(
                        "SELECT COUNT(*) FROM messages "
                        "WHERE (to_instance = ? OR to_instance IS NULL) "
                        "AND from_instance != ? "
                        "AND seen_by NOT LIKE ?",
                        (instance_name, instance_name, f'%"{instance_name}"%')
                    ).fetchone()[0]
                    sig_conn.close()
                    if unread > 0:
                        lines.append(f"\n📬 {unread} unread signal(s)")
                except Exception:
                    pass  # inbox count is non-fatal

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
