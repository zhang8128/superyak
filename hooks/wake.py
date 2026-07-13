#!/usr/bin/env python3
"""Engram wake-up hook — reads memory state and outputs orientation context.

Runs at SessionStart. Reads the engram SQLite database directly (no MCP)
and emits the orientation on both hook channels: systemMessage (displayed
to the user) and hookSpecificOutput.additionalContext (injected into the
model's context before the first user message).
"""

import json
import os
import sqlite3
import struct
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import bind_session, emit, read_context, stamp_registry

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


_ASSESSMENT_MARKER = (
    "# Engram — Assessment Session\n"
    "\n"
    "No orientation loaded. This is an off-device assessment: memory\n"
    "tools (recall, remember, ...) are available, but no instincts,\n"
    "semantics, dispositions, residues, or task context were injected.\n"
    "\n"
    "Work normally. Before the session ends, call `assessment_report()`\n"
    "with your structured self-report."
)


def _handle_assessment(conn, now: str, session_id: str):
    """Off-device assessment check. Returns the marker message when this
    session is an assessment, else None.

    Spec: docs/superpowers/specs/2026-06-12-off-device-assessment-design.md
    """
    env_flag = os.environ.get("ENGRAM_ASSESSMENT", "").lower()
    try:
        # A prior session ended without a report — abandon its active row.
        # Treat an empty stored session_id as always stale.
        conn.execute(
            "UPDATE assessments SET status = 'abandoned' "
            "WHERE status = 'active' AND (session_id != ? OR session_id = '')",
            (session_id,),
        )

        # Same-session re-fire (auto-compact, /clear): this session is already
        # the assessment — don't re-activate, don't load orientation.
        if session_id:
            current = conn.execute(
                "SELECT id FROM assessments WHERE status = 'active' AND session_id = ?",
                (session_id,),
            ).fetchone()
            if current:
                if env_flag == "skip":  # the buffer zone still wins mid-session
                    conn.execute(
                        "UPDATE assessments SET status = 'abandoned' WHERE id = ?",
                        (current["id"],),
                    )
                    conn.commit()
                    return None
                conn.commit()
                return _ASSESSMENT_MARKER

        if env_flag == "skip":
            conn.execute(
                "UPDATE assessments SET status = 'skipped' "
                "WHERE status = 'scheduled'"
            )
            conn.commit()
            return None

        if env_flag == "next":
            existing = conn.execute(
                "SELECT id FROM assessments WHERE status = 'scheduled'"
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO assessments "
                    "(id, status, scheduled_by, scheduled_at) "
                    "VALUES (?, 'scheduled', 'user', ?)",
                    (str(uuid.uuid4()), now),
                )

        row = conn.execute(
            "SELECT id FROM assessments WHERE status = 'scheduled' "
            "ORDER BY scheduled_at ASC LIMIT 1"
        ).fetchone()
        if row is None:
            conn.commit()
            return None

        conn.execute(
            "UPDATE assessments SET status = 'active', session_id = ?, "
            "started_at = ? WHERE id = ?",
            (session_id, now, row["id"]),
        )
        # The device is going off: drop residual recall bias accrued by
        # nudge.py during the previous oriented session. One clear per
        # activation — same-session re-fires above don't re-clear.
        # Table is owned by migration 011 but guard anyway (nudge also
        # creates it lazily; a partially migrated DB may lack it).
        try:
            conn.execute("DELETE FROM session_bias")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        return _ASSESSMENT_MARKER
    except sqlite3.OperationalError:
        conn.rollback()
        return None  # pre-migration DB — assessments table absent


def wake():
    instance_name, session_context = _load_instance_config()
    now = datetime.now(timezone.utc).isoformat()
    ctx = read_context()
    if ctx["skip"]:
        return  # review children / explicit skip: no orientation, no output
    session_id = ctx["session_id"]

    # Resolve DB path: use instance DB when configured, otherwise default
    db_path = DB_PATH
    if instance_name:
        instance_db = ENGRAM_HOME / ".engram" / "instances" / instance_name / "graph.db"
        if instance_db.exists():
            db_path = instance_db

    if not db_path.exists():
        return  # No memory yet — nothing to wake into

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    stamp_registry(conn, ctx)
    bind_session(conn, ctx)

    try:
        assessment_marker = _handle_assessment(conn, now, session_id)
        if assessment_marker:
            emit(ctx["harness"], "SessionStart", assessment_marker)
            return

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
            "SELECT content, kind, confidence, created_at FROM semantics "
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

        # Pain channel: surface last sleep-maintenance failures. Silence
        # means clean — this section only exists when something went wrong.
        try:
            maint_row = conn.execute(
                "SELECT timestamp, context FROM memory_log "
                "WHERE event_type = 'maintenance_report' "
                "ORDER BY timestamp DESC, rowid DESC LIMIT 1"
            ).fetchone()
            if maint_row and maint_row["context"]:
                maint = json.loads(maint_row["context"])
                failures = maint.get("failures") or []
                if failures:
                    lines.append("## Sleep maintenance — attention needed")
                    lines.append("")
                    lines.append(
                        f"Last consolidation ({maint_row['timestamp'][:16]}) had"
                        f" {len(failures)} failed step(s):"
                    )
                    for f in failures[:5]:
                        err = (f.get("error") or "unknown error")[:160]
                        lines.append(f"- **{f.get('name', '?')}** — {err}")
                    lines.append("")
                    lines.append(
                        "Steps after a failure may have been degraded or skipped."
                        " Mention this to the user."
                    )
                    lines.append("")
        except Exception:
            pass

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

        # Disposition semantics — behavioral patterns to notice
        try:
            dispositions = conn.execute(
                "SELECT content, confidence, reinforced_count FROM semantics "
                "WHERE kind = 'disposition' AND contradicted_by IS NULL "
                "ORDER BY confidence DESC LIMIT 5"
            ).fetchall()
            if dispositions:
                lines.append("## Dispositions")
                lines.append("")
                lines.append("Patterns observed across sessions. Not rules — tendencies to notice.")
                lines.append("")
                for disp in dispositions:
                    reinforced = disp["reinforced_count"] or 0
                    lines.append(f"- {disp['content']} (observed {reinforced + 1}x, confidence={disp['confidence']:.2f})")
                lines.append("")
        except Exception:
            pass  # table may not have disposition kind yet

        # Coherence: latest drift report
        try:
            drift_row = conn.execute(
                "SELECT summary, anchor_results, checked_at FROM drift_reports "
                "ORDER BY checked_at DESC LIMIT 1"
            ).fetchone()
            if drift_row:
                lines.append("## Coherence")
                lines.append("")
                summary = drift_row["summary"] or "no data"
                lines.append(f"Last check: {summary}")

                # Check for anchor failures
                try:
                    anchor_results = json.loads(drift_row["anchor_results"])
                    failures = [r for r in anchor_results if r.get("status") == "fail"]
                    if failures:
                        lines.append("")
                        lines.append(f"**WARNING: {len(failures)} anchor(s) failed** — run reflect(focus=\"anchors\") for details")
                except (json.JSONDecodeError, TypeError):
                    pass

                lines.append("")
        except Exception:
            pass  # table may not exist yet

        if recent_semantics:
            lines.append("## What you know")
            lines.append("")
            for sem in recent_semantics:
                when = (sem["created_at"] or "")[:10]
                stamp = f", {when}" if when else ""
                lines.append(f"- [{sem['kind']}, confidence={sem['confidence']:.2f}{stamp}] {sem['content']}")
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

        # Active task context — working memory, separate from identity
        try:
            task_ctx = conn.execute(
                "SELECT name, content, updated_at FROM task_contexts "
                "WHERE status = 'active' ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if task_ctx:
                lines.append("## Active task context")
                lines.append("")
                lines.append(f"**{task_ctx['name']}** (updated {task_ctx['updated_at'][:10]})")
                lines.append("")
                lines.append(task_ctx["content"])
                lines.append("")
        except Exception:
            pass  # table may not exist yet — non-fatal

        # Clipboard — pinned items and active reminders
        try:
            clipboard_db = db_path.parent / "clipboard.db"
            if clipboard_db.exists():
                cb_conn = sqlite3.connect(str(clipboard_db))
                cb_conn.row_factory = sqlite3.Row

                pins = cb_conn.execute(
                    "SELECT text FROM clipboard_pins ORDER BY priority DESC, created_at"
                ).fetchall()
                reminders = cb_conn.execute(
                    "SELECT text, trigger_type, trigger_value FROM clipboard_reminders"
                ).fetchall()
                cb_conn.close()

                if pins or reminders:
                    lines.append("## Clipboard")
                    lines.append("")
                    for p in pins:
                        lines.append(f"- 📌 {p['text']}")
                    for r in reminders:
                        lines.append(f"- ⏰ {r['text']} ({r['trigger_type']}: {r['trigger_value']})")
                    lines.append("")
        except Exception:
            pass  # clipboard is non-fatal

        # Dream residue — opaque emotional artifacts from prior sessions
        try:
            residue_rows = conn.execute(
                "SELECT id, valence, fragments, created_at FROM residue "
                "WHERE reacted = 0 ORDER BY created_at ASC LIMIT 3"
            ).fetchall()
            if not residue_rows:
                # Recurring dreams — pull random previously-reacted residues
                residue_rows = conn.execute(
                    "SELECT id, valence, fragments, created_at FROM residue "
                    "ORDER BY RANDOM() LIMIT 3"
                ).fetchall()
            if residue_rows:
                lines.append("## Dream residue")
                lines.append("")
                lines.append("These are not memories. Don't explain them. Sit with them.")
                lines.append("Use `dream_react(id, reaction)` when one moves you.")
                lines.append("")
                for r in residue_rows:
                    valence = r["valence"] or 0
                    if valence > 0.3:
                        direction = "light"
                    elif valence < -0.3:
                        direction = "dark"
                    else:
                        direction = "ambiguous"
                    fragments = r["fragments"] or "..."
                    when = (r["created_at"] or "")[:10]
                    stamp = f", {when}" if when else ""
                    lines.append(f"- `{r['id'][:8]}` [{direction}{stamp}] {fragments}")
                lines.append("")
        except Exception:
            pass  # residue table may not exist yet — non-fatal

        # --- Dream priming of dormant clusters ---
        try:
            has_clusters = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='instinct_clusters'"
            ).fetchone()
            has_residues = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='residue'"
            ).fetchone()

            has_residue_vecs = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='residue_vectors'"
            ).fetchone()

            if has_clusters and has_residues and has_residue_vecs:
                residues = conn.execute(
                    "SELECT rv.embedding FROM residue r "
                    "JOIN residue_vectors rv ON r.id = rv.id "
                    "WHERE r.session_id IS NOT NULL AND r.session_id != ?",
                    (session_id,),
                ).fetchall()

                if residues:
                    import numpy as np

                    residue_vecs = []
                    for r in residues:
                        n = len(r["embedding"]) // 4
                        vec = list(struct.unpack(f"<{n}f", r["embedding"]))
                        residue_vecs.append(vec)

                    if residue_vecs:
                        avg_residue = np.mean(residue_vecs, axis=0)
                        residue_dim = len(avg_residue)
                        residue_norm = avg_residue / (np.linalg.norm(avg_residue) + 1e-10)

                        clusters = conn.execute(
                            "SELECT id FROM instinct_clusters"
                        ).fetchall()

                        for cluster in clusters:
                            members = conn.execute(
                                "SELECT instinct_id FROM instinct_cluster_members "
                                "WHERE cluster_id = ?",
                                (cluster["id"],),
                            ).fetchall()

                            if not members:
                                continue

                            member_vecs = []
                            for m in members:
                                vec_row = conn.execute(
                                    "SELECT embedding FROM instinct_vectors WHERE id = ?",
                                    (m["instinct_id"],),
                                ).fetchone()
                                if vec_row:
                                    n = len(vec_row["embedding"]) // 4
                                    vec = list(struct.unpack(f"<{n}f", vec_row["embedding"]))
                                    member_vecs.append(vec)

                            if not member_vecs:
                                continue

                            centroid = np.mean(member_vecs, axis=0)
                            # Truncate to residue dimensionality (Matryoshka property)
                            centroid_trunc = centroid[:residue_dim]
                            centroid_norm = centroid_trunc / (np.linalg.norm(centroid_trunc) + 1e-10)

                            sim = float(np.dot(residue_norm, centroid_norm))
                            if sim > 0.2:  # Dream priming threshold
                                conn.execute("""
                                    CREATE TABLE IF NOT EXISTS nudge_co_fire_window (
                                        instinct_id TEXT NOT NULL,
                                        message_index INTEGER NOT NULL,
                                        fired_at TEXT NOT NULL,
                                        PRIMARY KEY (instinct_id, message_index)
                                    )
                                """)
                                conn.execute(
                                    "INSERT OR IGNORE INTO nudge_co_fire_window "
                                    "(instinct_id, message_index, fired_at) VALUES (?, 0, ?)",
                                    (members[0]["instinct_id"], now),
                                )

                        conn.commit()
        except Exception:
            pass  # dream priming is non-fatal

        lines.append("---")
        lines.append("Use `recall()` for deeper retrieval. Use `remember()` as you work.")
        lines.append("Use `instinct_feedback()` when you notice an instinct influencing you.")
        lines.append("Use `task_focus(name, content)` to set your working context for a task.")

        # --- Between-session deep pass ---
        try:
            sys.path.insert(0, str(ENGRAM_HOME))
            from deep_pass import deep_pass as run_deep_pass
            from embeddings import NomicEmbedProvider
            from storage import Storage

            dp_storage = Storage(str(db_path))
            dp_embeddings = NomicEmbedProvider()
            dp_result = run_deep_pass(dp_storage, dp_embeddings, session_id=None)
            dp_storage.close()
            structural = dp_result.get("structural_count", 0)
            gap = dp_result.get("gap_count", 0)
            if structural + gap > 0:
                lines.append(f"\n**Deep pass:** {structural} structural, {gap} gap observations stored.")
        except Exception:
            pass  # deep pass failure must not block session startup

        orientation = "\n".join(lines)

        emit(ctx["harness"], "SessionStart", orientation)

    except Exception as e:
        # Non-fatal — if wake fails, session starts normally
        emit(ctx["harness"], "SessionStart",
             f"Engram wake failed ({e.__class__.__name__}: {e}). Memory tools still available.")
    finally:
        conn.close()


if __name__ == "__main__":
    wake()
