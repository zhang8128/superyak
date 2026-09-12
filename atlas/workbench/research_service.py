"""Single-process lifecycle and CLI for continuous local literature research."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

from .automation import ResearchInbox, _directory, _now, _read, _save
from .research_context import ContextBudget


DEFAULT_MODEL = "qwen3.8:27b-mlx"
DEFAULT_ROLES = ("research", "audit", "question", "overlap", "connect")
ROOT = Path(__file__).resolve().parents[1]


class WorkerControl:
    def __init__(self, project):
        self.project = Path(project).resolve(strict=True)
        self.root = self.project / ".atlas/research"
        self.status_file = self.root / "worker.json"
        self.supervision_file = self.root / "supervision.json"

    def supervision(self):
        self._check_paths()
        if not self.supervision_file.exists() and not self.supervision_file.is_symlink():
            return None
        values = _read(self.supervision_file)
        if (not isinstance(values, dict) or type(values.get("enabled")) is not bool
                or not isinstance(values.get("options"), dict)):
            raise ValueError("Invalid research supervision configuration")
        return values

    def _check_paths(self):
        for directory in (self.project / ".atlas", self.root):
            if directory.is_symlink():
                raise ValueError(f"Worker state cannot be a symlink: {directory}")

    @contextmanager
    def lease(self, name):
        self._check_paths()
        for directory in (self.project / ".atlas", self.root):
            _directory(directory)
        descriptor = os.open(self.root / f"{name}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Worker lock must be a regular file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("Research worker already running or launch in progress") from error
            yield
        finally:
            os.close(descriptor)

    def _running(self):
        self._check_paths()
        lock = self.root / "worker.lock"
        if not lock.exists() and not lock.is_symlink():
            return False
        descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Worker lock must be a regular file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True
        finally:
            os.close(descriptor)

    def status(self):
        running = self._running()
        result = _read(self.status_file) if self.status_file.exists() else {}
        if not running:
            result = result | {"last_phase": result.get("phase"), "phase": "not_running"}
        return result | {"running": running, "project": str(self.project),
                         "supervision_enabled": bool((self.supervision() or {}).get("enabled")),
                         "live_graph": str(self.root / "index.html"), "log": str(self.root / "worker.log")}

    def update(self, values):
        _save(self.status_file, values | {"updated_at": _now()}, replace=True)

    def should_stop(self, token):
        path = self.root / "stop.json"
        return path.exists() and _read(path).get("token") == token

    def stop(self):
        status = self.status()
        # Persist pause without waiting for an in-progress launch/health check.
        # Managed children check this intent too, closing the fork-time race.
        if desired := self.supervision():
            _save(self.supervision_file, desired | {"enabled": False}, replace=True)
            status["supervision_enabled"] = False
        if not status["running"]:
            return status | {"stop_requested": False}
        if not status.get("token"):
            raise ValueError("Worker is acquiring its lease; retry stop after startup completes")
        _save(self.root / "stop.json", {"token": status["token"], "requested_at": _now()}, replace=True)
        return status | {"stop_requested": True,
                         "note": "Stops at the next checkpoint; automatic restart is paused until start."}


def _validate_options(options):
    values = {"model": DEFAULT_MODEL, "ollama_url": "http://127.0.0.1:11434", "interval": 60.0,
              "batch_size": 3, "question_ids": [], "cycles": None, "roles": list(DEFAULT_ROLES)} | options
    from .research_workers import ROLES
    if (not isinstance(values["roles"], list) or not values["roles"]
            or any(not isinstance(role, str) or role not in ROLES for role in values["roles"])):
        raise ValueError("Choose worker roles from " + ", ".join(ROLES))
    if not 1 <= values["interval"] <= 86400:
        raise ValueError("interval must be between 1 and 86400 seconds")
    if type(values["batch_size"]) is not int or not 1 <= values["batch_size"] <= 5:
        raise ValueError("batch size must be between 1 and 5")
    if values["cycles"] is not None and (type(values["cycles"]) is not int or values["cycles"] < 1):
        raise ValueError("cycles must be a positive integer")
    return values


def start(project, options, *, supervised=False):
    control = WorkerControl(project)
    if supervised and control.supervision() is None:
        return control.status() | {"started": False, "supervision_enabled": False}
    with control.lease("launch"):
        desired = control.supervision()
        if supervised:
            if not desired or not desired["enabled"]:
                return control.status() | {"started": False, "supervision_enabled": False}
            options = desired["options"]
        current = control.status()
        if current["running"]:
            if desired and not supervised:
                _save(control.supervision_file, {"enabled": True, "options": current["options"]}, replace=True)
                current["supervision_enabled"] = True
            return current | {"already_running": True}
        options = _validate_options(options)
        if supervised and options["cycles"] is not None:
            raise ValueError("Automatic supervision requires continuous research, without a cycle limit")
        if desired and not supervised:
            _save(control.supervision_file, {"enabled": options["cycles"] is None, "options": options}, replace=True)
        from .research_model import Ollama
        Ollama(options["model"], base_url=options["ollama_url"]).check()
        if desired and not (control.supervision() or {}).get("enabled") and options["cycles"] is None:
            return control.status() | {"started": False}
        # Fail configuration errors before detaching a process.
        snapshot = ResearchInbox(project).snapshot()
        selected = {q["id"] for q in snapshot["bundle"]["items"] if q["kind"] == "question"
                    and q["status"] != "withdrawn" and any(q["id"] in ids for ids in snapshot["views"].values())}
        if not selected or set(options["question_ids"]) - selected:
            raise ValueError("Choose active questions from the configured publication views")
        token = uuid.uuid4().hex
        arguments = [sys.executable, "-m", "workbench.research_service", "--project", str(control.project),
                     "run", "--token", token, "--model", options["model"], "--ollama-url", options["ollama_url"],
                     "--interval", str(options["interval"]), "--batch-size", str(options["batch_size"])]
        for question in options["question_ids"]:
            arguments.extend(["--question", question])
        for role in options["roles"]:
            arguments.extend(["--role", role])
        if options["cycles"] is not None:
            arguments.extend(["--cycles", str(options["cycles"])])
        elif desired:
            arguments.append("--supervised")
        log = control.root / "worker.log"
        descriptor = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a") as stream:
            process = subprocess.Popen(arguments, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = control.status()
            if status.get("token") == token and status["running"]:
                return status | {"started": True, "already_running": False}
            if process.poll() is not None:
                raise RuntimeError(f"Worker exited during startup (code {process.returncode}); inspect {log}")
            time.sleep(0.05)
        return {"started": True, "ready": False, "pid": process.pid, "token": token, "log": str(log),
                "note": "Process launched; inspect research-status before retrying start."}


def run_worker(project, options, token=None, *, supervised=False):
    from .research_model import Ollama
    from .research_runner import ResearchRunner
    from .research_sources import EuropePMC

    options = _validate_options(options)
    token = token or uuid.uuid4().hex
    control = WorkerControl(project)
    interrupted = threading.Event()
    previous_handlers = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.signal(signum, lambda *_: interrupted.set())
    stopped = lambda: (interrupted.is_set() or control.should_stop(token)
                       or (supervised and not (control.supervision() or {}).get("enabled")))
    values = {"token": token, "pid": os.getpid(), "phase": "starting", "started_at": _now(),
              "model": options["model"], "options": options, "cycles": 0,
              "context_mode": "dynamic", "context_budget": asdict(ContextBudget(output_reserve=1800)),
              "source_review": "enabled", "worker_roles": options["roles"]}

    def update(**change):
        values.update(change)
        control.update(values)
        print(json.dumps({"at": _now(), **change}, ensure_ascii=False), flush=True)

    try:
        with control.lease("worker"):
            update(phase="starting")
            try:
                if stopped():
                    update(phase="stopped", stopped_at=_now(), stop_requested=True)
                    return 0
                model = Ollama(options["model"], base_url=options["ollama_url"])
                model.check()
                runner = ResearchRunner(project, provider=EuropePMC(), model=model,
                                        question_ids=options["question_ids"], should_stop=stopped,
                                        progress=update, batch_size=options["batch_size"])
                rotation = None
                if options["roles"] != ["research"]:
                    from .research_workers import WorkerRotation
                    rotation = WorkerRotation(runner, roles=options["roles"])
                failures = 0
                while not stopped():
                    result = rotation.cycle() if rotation else runner.cycle()
                    # A rejected paper answer uses its bounded job attempts;
                    # it does not indicate a service outage affecting other papers.
                    operational_errors = any(error.get("kind") not in {"invalid_analysis", "invalid_review", "invalid_connection", "invalid_input", "invalid_graph"}
                                             for error in result["errors"])
                    failures = failures + 1 if operational_errors else 0
                    update(phase="waiting", cycles=values["cycles"] + 1, last_cycle=result,
                           question_agenda=result.get("question_agenda", {}),
                           **({"worker_metrics": rotation.metrics()} if rotation else {}),
                           last_error=result["errors"][-1] if result["errors"] else None)
                    if options["cycles"] and values["cycles"] >= options["cycles"]:
                        break
                    if failures >= 5 and not stopped() and (control.supervision() or {}).get("enabled"):
                        update(phase="recovering", restart_requested=True,
                               last_error="Repeated operational failures; supervisor will restart from saved jobs.")
                        return 1
                    delay = max(options["interval"], min(900, 30 * 2 ** min(failures, 5))) if failures else options["interval"]
                    update(next_cycle_at_epoch=time.time() + delay)
                    deadline = time.monotonic() + delay
                    while not stopped() and time.monotonic() < deadline:
                        interrupted.wait(min(1, max(0, deadline - time.monotonic())))
                update(phase="stopped", stopped_at=_now(), stop_requested=stopped())
                return 2 if options["cycles"] and values.get("last_cycle", {}).get("errors") else 0
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
                update(phase="error", last_error=str(error), stopped_at=_now())
                return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def add_commands(commands):
    for command in ("start", "run"):
        parser = commands.add_parser(command, help="Start continuous local research" if command == "start" else "Run research in the foreground")
        parser.add_argument("--model", default=DEFAULT_MODEL)
        parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
        parser.add_argument("--question", action="append", default=[], help="Existing active question ID; repeat to select several")
        parser.add_argument("--interval", type=float, default=60, help="Seconds between passes; failures back off")
        parser.add_argument("--batch-size", type=int, default=3, help="Papers processed per pass (1–5)")
        parser.add_argument("--role", action="append", choices=DEFAULT_ROLES,
                            help="Worker role; repeat to override the default order: " + ", ".join(DEFAULT_ROLES))
        parser.add_argument("--cycles", type=int, help="Stop after this many passes; default keeps running")
        if command == "run":
            parser.add_argument("--token", help=argparse.SUPPRESS)
            parser.add_argument("--supervised", action="store_true", help=argparse.SUPPRESS)
    commands.add_parser("stop", help="Request a graceful research-worker stop")
    commands.add_parser("supervise", help="Resume an enabled unattended worker if it is not running")
    review = commands.add_parser("review-backlog", help="Assess saved bot claims against cached source passages")
    review.add_argument("--model", default=DEFAULT_MODEL)
    review.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    review.add_argument("--limit", type=int, default=10, help="Maximum new assessments; unchanged cached reviews are skipped")
    review.add_argument("--record", action="append", default=[], help="Saved bot record ID; repeat to select records")
    status_parser = commands.add_parser("research-status", help="Follow research activity in a terminal; JSON snapshot when piped")
    mode = status_parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Show a readable snapshot and recent activity, then exit")
    mode.add_argument("--json", action="store_true", help="Return the machine-readable status snapshot and exit")
    mode.add_argument("--follow", action="store_true", help="Follow readable activity even when output is redirected")


def dispatch(args):
    if args.command == "review-backlog":
        from .research_model import Ollama
        from .research_review import review_backlog
        model = Ollama(args.model, base_url=args.ollama_url)
        model.check()
        control = WorkerControl(args.project)
        with control.lease("review"):
            return review_backlog(args.project, model, limit=args.limit, record_ids=args.record)
    if args.command == "stop":
        return WorkerControl(args.project).stop()
    if args.command == "supervise":
        result = start(args.project, {}, supervised=True)
        return {key: result.get(key) for key in ("running", "started", "already_running", "supervision_enabled")}
    if args.command == "research-status":
        control = WorkerControl(args.project)
        if args.json or not (args.once or args.follow or sys.stdout.isatty()):
            return control.status()
        from .research_monitor import monitor
        return monitor(control, follow=not args.once)
    options = {"model": args.model, "ollama_url": args.ollama_url, "interval": args.interval,
               "batch_size": args.batch_size, "question_ids": args.question, "cycles": args.cycles}
    if args.role is not None:
        options["roles"] = args.role
    if args.command == "start":
        return start(args.project, options)
    return run_worker(args.project, options, args.token, supervised=args.supervised)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    add_commands(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(argv)
    try:
        result = dispatch(args)
        if type(result) is int:
            return result
        print(json.dumps(result, ensure_ascii=False))
        return 2 if args.command == "review-backlog" and result.get("errors") else 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
