"""Read-only, scrolling terminal view of the existing research worker log."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import stat
import sys
import time


def _text(value):
    # Paper titles and error text can originate outside this process.
    return "".join(char if char.isprintable() else " " for char in str(value))


def _error(value):
    if isinstance(value, dict):
        message = str(value.get("error", value))
        if value.get("attempts"):
            message += f" (attempt {value['attempts']})"
        return message
    return str(value)


def _agenda_lines(agenda):
    if not isinstance(agenda, dict):
        return []
    entries = [entry for entry in agenda.values() if isinstance(entry, dict)]
    counts = [(state.replace("_", " "), sum(entry.get("state") == state for entry in entries))
              for state in ("active", "queued", "parked", "needs_reassessment")]
    research = [entry.get("research_count", 0) for entry in entries]
    overlap = [entry.get("overlap_count", 0) for entry in entries]
    research = [count for count in research if type(count) is int and count >= 0]
    overlap = [count for count in overlap if type(count) is int and count >= 0]
    return ["Question agenda: " + " · ".join(f"{count} {label}" for label, count in counts),
            f"Question progress: {sum(count > 0 for count in research)} questions researched · "
            f"{sum(research)} research attempts · {sum(overlap)} overlap attempts"]


def format_event(line):
    """Keep worker events legible and preserve unrecognized diagnostics."""
    try:
        event = json.loads(line)
        if not isinstance(event, dict):
            return [_text(line)]
        stamp = datetime.fromisoformat(event["at"]).astimezone().strftime("%H:%M:%S") if event.get("at") else ""
        prefix = f"[{stamp}] " if stamp else ""
        phase = event.get("phase")
        labels = {"starting": "Starting researcher", "planning": "Planning",
                  "searching": "Searching", "reading": "Reading", "analyzing": "Analyzing", "reviewing": "Checking source support",
                  "recording": "Saving proposed finding", "publishing": "Refreshing Lighthouse views",
                  "working": "Starting role", "connecting": "Comparing source-checked claims",
                  "reviewing_connection": "Checking proposed connections",
                  "waiting": "Waiting", "stopped": "Research worker stopped", "error": "Research worker error"}
        messages = []
        if phase:
            message = labels.get(phase, str(phase))
            detail_field = {"searching": "query", "planning": "question", "reading": "paper",
                            "analyzing": "paper", "reviewing": "paper", "recording": "paper",
                            "working": "worker_role", "connecting": "question", "reviewing_connection": "question"}.get(phase)
            detail = event.get(detail_field)
            messages.append(message + (f": {detail}" if detail else ""))
        cycle = event.get("last_cycle")
        if isinstance(cycle, dict):
            messages.append(f"Pass {event.get('cycles', '?')} complete: {cycle.get('saved', 0)} saved, "
                            f"{cycle.get('links_added', 0)} links added, "
                            f"{cycle.get('replayed', 0)} replayed, {cycle.get('skipped', 0)} skipped; " +
                            (f"{cycle['held']} held after review; " if "held" in cycle else "") +
                            f"Lighthouse views {cycle.get('publication_status', 'unknown')}" +
                            (f"; {cycle['draft_count']} total drafts" if "draft_count" in cycle else ""))
            messages.extend(f"Saved record: {identifier}" for identifier in cycle.get("record_ids", []))
            if cycle.get("worker_role"):
                messages.append(f"Role: {cycle['worker_role']} · {cycle.get('reviewed', 0)} assessments · "
                                f"{cycle.get('seconds', 0)} seconds")
            messages.extend(f"Error: {_error(error)}" for error in cycle.get("errors", []))
            if isinstance(cycle.get("research_views"), dict):
                views = cycle["research_views"]
                messages.append(f"Research views {views.get('status', 'unknown')} · Obsidian notes and map")
                messages.extend(f"View update: {_error(error)}" for error in views.get("errors", []))
        elif event.get("last_error"):
            messages.append(f"Error: {_error(event['last_error'])}")
        messages.extend(_agenda_lines(event.get("question_agenda")))
        if event.get("next_cycle_at_epoch") is not None:
            when = datetime.fromtimestamp(event["next_cycle_at_epoch"]).astimezone().strftime("%H:%M:%S %Z")
            messages.append(f"Next pass at {when}")
        return [_text(prefix + message) for message in messages] if messages else [_text(line)]
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return [_text(line)]


class LogTail:
    """Read recent history once, then complete appended lines across log replacement."""

    def __init__(self, path):
        self.path = Path(path)
        self.identity = None
        self.offset = 0
        self.pending = b""
        self.anchor = b""

    def read_lines(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return []
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Worker log must be a regular file")
            identity = (info.st_dev, info.st_ino)
            first = self.identity is None
            replaced = identity != self.identity or info.st_size < self.offset
            if not replaced and self.anchor:
                stream.seek(self.offset - len(self.anchor))
                replaced = stream.read(len(self.anchor)) != self.anchor
            if replaced:
                self.offset, self.pending = 0, b""
            self.identity = identity
            if first:
                self.offset = max(0, info.st_size - 65536)
            stream.seek(self.offset)
            data = stream.read(65536)
            if first and self.offset:
                data = data.partition(b"\n")[2]
            self.offset = stream.tell()
            # Detect truncate-and-regrow between polls, even at the same size.
            anchor_start = max(0, self.offset - 128)
            stream.seek(anchor_start)
            self.anchor = stream.read(self.offset - anchor_start)
        lines = (self.pending + data).split(b"\n")
        self.pending = lines.pop()
        if first:
            lines = lines[-20:]
        return [line.decode("utf-8", errors="replace") for line in lines if line]


def monitor(control, *, follow):
    """Observe the worker; interrupting this function never requests a worker stop."""
    try:
        status = control.status()

        def show(message):
            print(_text(message), flush=True)

        state = "running" if status["running"] else "not running"
        show(f"Atlas researcher — {state}")
        show(f"Model: {status.get('model', 'not started')} | Context: {status.get('context_mode', 'unknown')} | "
             f"Phase: {status.get('phase', 'unknown')} | Completed passes: {status.get('cycles', 0)}")
        if status.get("worker_roles"):
            show(f"Roles: {', '.join(status['worker_roles'])} | Active: {status.get('worker_role', 'research')}")
        for message in _agenda_lines(status.get("question_agenda")):
            show(message)
        for field in ("question", "paper"):
            if status.get(field):
                show(f"Latest {field}: {status[field]}")
        if status.get("last_error"):
            show(f"Last error: {_error(status['last_error'])}")
        show(f"Live graph: {status['live_graph']}")
        show(f"Obsidian notes: {Path(status['project']) / 'Research/Start Here.md'}")
        show(f"Log: {status['log']}")
        if not status["running"]:
            show("Start research with: atlas-research start")
        if follow:
            show("Following activity. Ctrl-C exits this monitor; it does not stop research.")
        show("Recent activity (up to 20 events):")
        tail = LogTail(status["log"])
        while True:
            control._check_paths()
            for line in tail.read_lines():
                for message in format_event(line):
                    show(message)
            if not follow:
                return 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nMonitor closed. No worker stop requested.", flush=True)
        return 0
    except BrokenPipeError:
        # Prevent Python's shutdown flush from retrying the closed consumer.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
