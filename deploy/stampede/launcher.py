"""Local allowlisted staging and resumable SSH/Slurm launch orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile
import tempfile
from typing import Protocol, Sequence
import uuid

from .config import resolve_run_id, validate_config


_ALLOWED_EXACT = {
    "deploy/__init__.py",
    "deploy/stampede/__init__.py",
    "deploy/stampede/__main__.py",
    "deploy/stampede/bootstrap.sh",
    "deploy/stampede/cluster.py",
    "deploy/stampede/config.example.json",
    "deploy/stampede/config.py",
    "deploy/stampede/experiment.py",
    "deploy/stampede/export.py",
    "deploy/stampede/launcher.py",
    "deploy/stampede/profiles.py",
    "deploy/stampede/probe.py",
    "deploy/stampede/provider.py",
    "deploy/stampede/simulate.py",
    "engram/pyproject.toml",
    "engram/uv.lock",
    "scripts/atlas.py",
    "atlas/pyproject.toml",
    "atlas/uv.lock",
    "atlas/IMPORT-MANIFEST.json",
    "atlas/README.md",
    "atlas/scripts/atlas_research.py",
    "atlas/scripts/check_lighthouse_interop.py",
    "atlas/workbench/data/cell_fate.json",
    "atlas/workbench/data/lighthouse-automation.json",
    "atlas/workbench/data/lighthouses/prediction.json",
    "atlas/workbench/data/lighthouses/regulation.json",
    "atlas/workbench/data/archive_cleanup.json",
    "atlas/workbench/static/page.html",
    "atlas/workbench/static/workbench.css",
    "atlas/workbench/static/workbench.js",
}
_CORPUS_SUFFIXES = {".json", ".txt", ".md", ".yaml", ".yml"}
_ENGRAM_RESOURCE_SUFFIXES = {".sql", ".json", ".txt"}
_REMOTE_ABSOLUTE = re.compile(r"/[A-Za-z0-9._/-]+\Z")
_JOB_ID = re.compile(r"[0-9]+\Z")
_SBATCH_STATES = {
    "BOOT_FAIL", "CANCELLED", "COMPLETED", "CONFIGURING", "COMPLETING",
    "DEADLINE", "FAILED", "NODE_FAIL", "OUT_OF_MEMORY", "PENDING",
    "PREEMPTED", "RUNNING", "SUSPENDED", "TIMEOUT",
}


class LauncherError(RuntimeError):
    """A safe launcher failure."""


class RemoteCommandError(LauncherError):
    """An SSH or SCP boundary returned a definite error."""


class DeploymentUncertainError(LauncherError):
    """Submission may have happened and requires human reconciliation."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandBoundary(Protocol):
    def run(self, argv: Sequence[str], *, timeout: float | None = None) -> CommandResult:
        """Run an argv-only external command."""


class SubprocessBoundary:
    """Real argv-only SSH/SCP command boundary."""

    def run(self, argv: Sequence[str], *, timeout: float | None = None) -> CommandResult:
        try:
            completed = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RemoteCommandError(f"command boundary failed: {type(error).__name__}") from error
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _allowed_source(path: Path, source: Path) -> bool:
    try:
        relative = path.relative_to(source)
    except ValueError:
        return False
    if path.is_symlink() or not path.is_file() or any(part.startswith(".") for part in relative.parts):
        return False
    posix = relative.as_posix()
    if posix in _ALLOWED_EXACT:
        return True
    top = relative.parts[0] if relative.parts else ""
    if top in {"research_poc", "research_tasks"}:
        return len(relative.parts) == 2 and path.suffix == ".py"
    if top == "atlas":
        return (len(relative.parts) == 3 and relative.parts[1] == "workbench"
                and path.suffix == ".py")
    if top == "deploy":
        return (
            len(relative.parts) >= 4
            and relative.parts[:3] == ("deploy", "stampede", "corpus")
            and path.suffix in _CORPUS_SUFFIXES
        )
    if top == "engram":
        if len(relative.parts) == 2 and path.suffix == ".py":
            return True
        if len(relative.parts) >= 3 and relative.parts[1] in {
            "migrations", "prompts", "schemas"
        }:
            return path.suffix in _ENGRAM_RESOURCE_SUFFIXES
    return False


def _bundle_files(source: Path) -> list[Path]:
    if not source.is_dir():
        raise LauncherError(f"source root is not a directory: {source}")
    return sorted(
        (path for path in source.rglob("*") if _allowed_source(path, source)),
        key=lambda path: path.relative_to(source).as_posix(),
    )


def prepare_bundle(source: str | Path, destination: str | Path) -> Path:
    """Create a deterministic archive containing only executable project sources."""
    source_path = Path(source).resolve()
    destination_path = Path(destination)
    files = _bundle_files(source_path)
    if not any(path.relative_to(source_path).as_posix() == "deploy/stampede/bootstrap.sh" for path in files):
        raise LauncherError("allowlisted source is missing deploy/stampede/bootstrap.sh")

    entries = []
    for path in files:
        content = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(source_path).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )
    manifest = json.dumps(
        {"files": entries, "format": "superyak-stampede-source-v1"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode() + b"\n"

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(f".{destination_path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                    manifest_info = tarfile.TarInfo("bundle-manifest.json")
                    manifest_info.size = len(manifest)
                    manifest_info.mode = 0o644
                    manifest_info.mtime = 0
                    archive.addfile(manifest_info, io.BytesIO(manifest))
                    for path, entry in zip(files, entries, strict=True):
                        content = path.read_bytes()
                        info = tarfile.TarInfo(entry["path"])
                        info.size = len(content)
                        info.mode = 0o755 if path.suffix == ".sh" else 0o644
                        info.mtime = 0
                        archive.addfile(info, io.BytesIO(content))
        os.replace(temporary, destination_path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return destination_path


def generate_batch_script(
    config: dict,
    remote_run_dir: str | Path,
    *,
    submission_generation: int = 1,
) -> str:
    """Render the fixed Slurm entrypoint with validated directives and quoted paths."""
    config = validate_config(config, require_launch=True)
    run_id = resolve_run_id(config)
    run_dir = str(remote_run_dir)
    if not run_dir.startswith("/"):
        raise LauncherError("remote run directory must be absolute")
    if not isinstance(submission_generation, int) or isinstance(submission_generation, bool) or submission_generation < 1:
        raise LauncherError("submission generation must be a positive integer")
    job_name = f"sy-{run_id}-g{submission_generation}"
    quoted_run = shlex.quote(run_dir)
    lines = [
        "#!/bin/bash",
        f"#SBATCH --job-name={job_name}",
        f"#SBATCH --account={config['account']}",
        f"#SBATCH --partition={config['partition']}",
        f"#SBATCH --nodes={config['nodes']}",
        f"#SBATCH --ntasks={config['nodes']}",
        "#SBATCH --ntasks-per-node=1",
        f"#SBATCH --time={config['walltime']}",
        "#SBATCH --signal=B:USR1@240",
        f"#SBATCH --output={run_dir}/logs/slurm-%j.out",
        f"#SBATCH --error={run_dir}/logs/slurm-%j.err",
        "set -euo pipefail",
        f"RUN_DIR={quoted_run}",
        'mkdir -p "$RUN_DIR/logs"',
        'export PYTHONPATH="$RUN_DIR/source:$RUN_DIR/source/engram${PYTHONPATH:+:$PYTHONPATH}"',
        "export TACC_TASKS_PER_NODE=1",
        'exec "$RUN_DIR/.venv/bin/python" -m deploy.stampede.cluster batch --run-dir "$RUN_DIR"',
        "",
    ]
    return "\n".join(lines)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Launcher:
    """Prepare, stage, submit, reconcile, inspect, and fetch one campaign."""

    def __init__(
        self,
        *,
        source_root: str | Path,
        state_root: str | Path,
        boundary: CommandBoundary | None = None,
    ):
        self.source_root = Path(source_root).resolve()
        self.state_root = Path(state_root).resolve()
        self.boundary = boundary or SubprocessBoundary()

    def _run(self, argv: Sequence[str], *, timeout: float = 120) -> CommandResult:
        return self.boundary.run([str(item) for item in argv], timeout=timeout)

    def _ssh(self, login: str, command: str, *, timeout: float = 120) -> CommandResult:
        return self._run(["ssh", "-o", "BatchMode=no", "--", login, command], timeout=timeout)

    def _state_path(self, run_id: str) -> Path:
        return self.state_root / run_id / "state.json"

    def _read_state(self, run_id: str) -> dict:
        try:
            value = json.loads(self._state_path(run_id).read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise LauncherError(f"local state unavailable for run {run_id}") from error
        if not isinstance(value, dict) or value.get("run_id") != run_id:
            raise LauncherError(f"local state is invalid for run {run_id}")
        return value

    def _write_state(self, state: dict) -> dict:
        state = {**state, "updated_at": _now()}
        _atomic_json(self._state_path(state["run_id"]), state)
        return state

    def _remote_work(self, login: str) -> str:
        command = "\n".join(
            [
                "set -eu",
                "# SUPER YAK WORK ROOT",
                'if [ -z "${WORK:-}" ]; then echo "TACC WORK is not set" >&2; exit 78; fi',
                'printf "%s\\n" "$WORK"',
            ]
        )
        result = self._ssh(login, command, timeout=60)
        work = result.stdout.strip()
        if result.returncode != 0 or not _REMOTE_ABSOLUTE.fullmatch(work) or ".." in PurePosixPath(work).parts:
            detail = result.stderr.strip() or "TACC WORK was not a safe absolute path"
            raise RemoteCommandError(f"cannot resolve remote WORK: {detail}")
        return work

    def _remote_run_dir(self, config: dict) -> str:
        work = self._remote_work(config["login"])
        return f"{work}/{config['remote_subdir']}/runs/{config['run_id']}"

    @staticmethod
    def _job_name(run_id: str, generation: int) -> str:
        return f"sy-{run_id}-g{generation}"

    def plan(self, raw_config: dict) -> dict:
        config = validate_config(raw_config)
        config["run_id"] = resolve_run_id(config)
        files = _bundle_files(self.source_root)
        return {
            "run_id": config["run_id"],
            "ready_to_deploy": bool(config["login"] and config["account"]),
            "missing": [key for key in ("login", "account") if not config[key]],
            "budget": {"nodes": config["nodes"], "walltime": config["walltime"]},
            "comparison_runs": 4 * len(config["populations"]) * len(config["concurrency"]) + 4,
            "community_runs": 1 if config["community_population"] > 0 else 0,
            "cells": (
                4 * len(config["populations"]) * len(config["concurrency"])
                + 4
                + (1 if config["community_population"] > 0 else 0)
            ),
            "community_population": config["community_population"],
            "data_mode": config["data_mode"],
            "source_files": len(files),
            "remote": f"{config['login'] or '<login>'}:$WORK/{config['remote_subdir']}/runs/{config['run_id']}",
            "hardware_verified": False,
        }

    def _reconcile(self, state: dict) -> dict | None:
        remote = state["remote_run_dir"]
        generation = int(state.get("submission_generation", 1))
        job_name = self._job_name(state["run_id"], generation)
        marker = f"{remote}/submissions/{generation:06d}.json"
        command = "\n".join(
            [
                "set -eu",
                "# SUPER YAK RECONCILE",
                f"marker={shlex.quote(marker)}",
                f"job_name={shlex.quote(job_name)}",
                'if [ -f "$marker" ]; then printf "MARKER\\t"; cat "$marker"; exit 0; fi',
                'job_id=$(squeue -h -n "$job_name" -o "%i" 2>/dev/null | head -n 1 || true)',
                'if [ -n "$job_id" ]; then printf "ACTIVE\\t%s\\n" "$job_id"; exit 0; fi',
                'history=$(sacct -X -n -S 2020-01-01 --name "$job_name" -o JobIDRaw,State -P 2>/dev/null | head -n 1 || true)',
                'if [ -n "$history" ]; then printf "HISTORY\\t%s\\n" "$history"; exit 0; fi',
                'printf "NONE\\n"',
            ]
        )
        result = self._ssh(state["login"], command, timeout=90)
        if result.returncode != 0:
            return None
        kind, _, payload = result.stdout.strip().partition("\t")
        if kind == "NONE":
            return None
        if kind == "MARKER":
            try:
                record = json.loads(payload)
            except json.JSONDecodeError:
                return {"phase": "uncertain", "healthy": False, "reason": "invalid remote submission marker"}
            job_id = str(record.get("job_id", ""))
            if not _JOB_ID.fullmatch(job_id) or record.get("generation") != generation:
                return {"phase": "uncertain", "healthy": False, "reason": "invalid remote job ID"}
            return {"phase": "submitted", "healthy": False, "job_id": job_id, "reconciled": True}
        if kind == "ACTIVE" and _JOB_ID.fullmatch(payload.strip()):
            return {"phase": "submitted", "healthy": False, "job_id": payload.strip(), "reconciled": True}
        if kind == "HISTORY":
            job_id, _, slurm_state = payload.partition("|")
            slurm_state = slurm_state.split()[0].upper() if slurm_state else ""
            if _JOB_ID.fullmatch(job_id) and slurm_state in _SBATCH_STATES:
                active = slurm_state in {"PENDING", "CONFIGURING", "RUNNING", "COMPLETING"}
                if slurm_state == "COMPLETED":
                    phase = "job_finished"
                elif active:
                    phase = "submitted"
                else:
                    phase = "failed"
                return {
                    "phase": phase,
                    "healthy": False,
                    "complete": False,
                    "job_id": job_id,
                    "slurm_state": slurm_state,
                    "reconciled": True,
                }
        return {"phase": "uncertain", "healthy": False, "reason": "unrecognized reconciliation response"}

    def _stage(self, state: dict, local_run: Path) -> None:
        remote = state["remote_run_dir"]
        login = state["login"]
        mkdir = self._ssh(login, f"mkdir -p {shlex.quote(remote)}", timeout=60)
        if mkdir.returncode != 0:
            raise RemoteCommandError(f"remote staging failed: {mkdir.stderr.strip() or 'mkdir failed'}")
        for name in ("source.tar.gz", "config.json", "batch.sh"):
            result = self._run(
                ["scp", "--", str(local_run / name), f"{login}:{remote}/{name}"],
                timeout=600,
            )
            if result.returncode != 0:
                raise RemoteCommandError(f"remote staging failed: {result.stderr.strip() or name}")
        unpack = " && ".join(
            [
                f"cd {shlex.quote(remote)}",
                "mkdir -p source logs",
                "tar -xzf source.tar.gz -C source",
                f"bash source/deploy/stampede/bootstrap.sh {shlex.quote(remote)}",
            ]
        )
        result = self._ssh(login, unpack, timeout=1800)
        if result.returncode != 0:
            raise RemoteCommandError(f"remote bootstrap failed: {result.stderr.strip() or 'unknown error'}")

    def _submit(self, state: dict) -> CommandResult:
        remote = state["remote_run_dir"]
        generation = int(state["submission_generation"])
        marker = f"{remote}/submissions/{generation:06d}.json"
        latest = f"{remote}/submission.json"
        lock = f"{remote}/.submit.lock"
        job_name = self._job_name(state["run_id"], generation)
        command = "\n".join(
            [
                "set -eu",
                f"marker={shlex.quote(marker)}",
                f"latest={shlex.quote(latest)}",
                f"lock={shlex.quote(lock)}",
                f"job_name={shlex.quote(job_name)}",
                f"generation={generation}",
                f"mkdir -p {shlex.quote(remote + '/submissions')}",
                'if [ -f "$marker" ]; then cat "$marker"; exit 0; fi',
                'if ! mkdir "$lock" 2>/dev/null; then echo "submission reconciliation in progress" >&2; exit 75; fi',
                'trap \'rmdir "$lock" 2>/dev/null || true\' EXIT HUP INT TERM',
                'if [ -f "$marker" ]; then cat "$marker"; exit 0; fi',
                'existing=$(squeue -h -n "$job_name" -o "%i" 2>/dev/null | head -n 1 || true)',
                'if [ -n "$existing" ]; then job_id="$existing"; else',
                f"  raw=$(cd {shlex.quote(remote)} && sbatch --parsable batch.sh)",
                '  job_id=${raw%%;*}',
                "fi",
                'case "$job_id" in (*[!0-9]*|\"\") echo "invalid Slurm job ID" >&2; exit 76;; esac',
                f"tmp={shlex.quote(marker)}.tmp.$$",
                'printf \'{"generation":%s,"job_id":"%s","job_name":"%s","state":"submitted"}\\n\' "$generation" "$job_id" "$job_name" > "$tmp"',
                'mv "$tmp" "$marker"',
                'latest_tmp="$latest.tmp.$$"',
                'cp "$marker" "$latest_tmp" && mv "$latest_tmp" "$latest"',
                'cat "$marker"',
            ]
        )
        return self._ssh(state["login"], command, timeout=120)

    def _finish_submission_attempt(self, state: dict) -> dict:
        result = self._submit(state)
        if result.returncode == 0:
            try:
                marker = json.loads(result.stdout)
                job_id = str(marker["job_id"])
                generation = marker["generation"]
            except (json.JSONDecodeError, KeyError, TypeError):
                job_id = ""
                generation = None
            if _JOB_ID.fullmatch(job_id) and generation == state["submission_generation"]:
                return self._write_state(
                    {**state, "phase": "submitted", "healthy": False, "job_id": job_id, "reason": ""}
                )

        reconciled = self._reconcile(state)
        if reconciled is not None and reconciled["phase"] != "uncertain":
            return self._write_state({**state, **reconciled})
        reason = "submission response was ambiguous; manual reconciliation required before retry"
        self._write_state({**state, "phase": "uncertain", "healthy": False, "reason": reason})
        raise DeploymentUncertainError(reason)

    def _remote_campaign_status(self, state: dict) -> CommandResult:
        remote = state["remote_run_dir"]
        command = "\n".join(
            [
                "set -eu",
                "# SUPER YAK CAMPAIGN STATUS",
                f"status={shlex.quote(remote + '/status.json')}",
                'if [ -f "$status" ]; then printf "STATUS\\t"; cat "$status"; else printf "MISSING\\n"; fi',
            ]
        )
        return self._ssh(state["login"], command, timeout=90)

    def _job_state(self, state: dict) -> tuple[str, str]:
        job_id = str(state.get("job_id", ""))
        if not _JOB_ID.fullmatch(job_id):
            raise DeploymentUncertainError("current Slurm job ID is unavailable; reconciliation required")
        command = "\n".join(
            [
                "set -eu",
                "# SUPER YAK JOB STATE",
                f"job_id={job_id}",
                'active=$(squeue -h -j "$job_id" -o "%T" 2>/dev/null | head -n 1 || true)',
                'if [ -n "$active" ]; then printf "ACTIVE\\t%s\\n" "$active"; exit 0; fi',
                'record=$(sacct -X -n -j "$job_id" -o JobIDRaw,State -P 2>/dev/null | awk -F\'|\' -v id="$job_id" \'$1 == id {print; exit}\' || true)',
                'if [ -z "$record" ]; then printf "UNKNOWN\\n"; exit 0; fi',
                'state=${record#*|}; state=${state%% *}; state=${state%%+}',
                'case "$state" in',
                '  COMPLETED|FAILED|CANCELLED|TIMEOUT|PREEMPTED|NODE_FAIL|OUT_OF_MEMORY|BOOT_FAIL|DEADLINE) printf "TERMINAL\\t%s\\n" "$state";;',
                '  *) printf "UNKNOWN\\t%s\\n" "$state";;',
                "esac",
            ]
        )
        result = self._ssh(state["login"], command, timeout=90)
        if result.returncode != 0:
            raise DeploymentUncertainError(
                f"cannot verify prior Slurm job: {result.stderr.strip() or 'SSH failed'}"
            )
        kind, _, slurm_state = result.stdout.strip().partition("\t")
        if kind not in {"ACTIVE", "TERMINAL"} or slurm_state not in _SBATCH_STATES:
            raise DeploymentUncertainError("prior Slurm job state is unknown; reconciliation required")
        return kind, slurm_state

    def deploy(self, raw_config: dict) -> dict:
        config = validate_config(raw_config, require_launch=True)
        config["run_id"] = resolve_run_id(config)
        run_id = config["run_id"]
        local_run = self.state_root / run_id
        local_run.mkdir(parents=True, exist_ok=True)
        bundle = local_run / "source.tar.gz"
        config_path = local_run / "config.json"
        state_path = self._state_path(run_id)
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=local_run) as temporary:
            candidate_dir = Path(temporary)
            candidate_bundle = prepare_bundle(self.source_root, candidate_dir / "source.tar.gz")
            candidate_config = candidate_dir / "config.json"
            _atomic_json(candidate_config, config)
            identity = {
                "bundle_sha256": _digest(candidate_bundle),
                "config_sha256": _digest(candidate_config),
            }

            if state_path.exists():
                state = self._read_state(run_id)
                if any(state.get(key) != value for key, value in identity.items()):
                    raise LauncherError(f"run {run_id} already exists with different inputs")
                if (
                    not bundle.is_file()
                    or not config_path.is_file()
                    or _digest(bundle) != identity["bundle_sha256"]
                    or _digest(config_path) != identity["config_sha256"]
                ):
                    raise LauncherError(f"local artifacts are invalid for run {run_id}")
                remote_run = state["remote_run_dir"]
            else:
                os.replace(candidate_bundle, bundle)
                os.replace(candidate_config, config_path)
                remote_run = self._remote_run_dir(config)
                state = self._write_state(
                    {
                        "run_id": run_id,
                        "phase": "prepared",
                        "healthy": False,
                    "complete": False,
                    "submission_attempted": False,
                    "submission_generation": 1,
                    "submission_history": [],
                        "login": config["login"],
                        "remote_run_dir": remote_run,
                        **identity,
                    }
                )

        reconciled = self._reconcile(state)
        if reconciled is not None:
            if reconciled["phase"] != "uncertain":
                return self._write_state({**state, **reconciled})
            state = self._write_state({**state, **reconciled})
            raise DeploymentUncertainError(reconciled["reason"])
        if state.get("submission_attempted"):
            state = self._write_state(
                {
                    **state,
                    "phase": "uncertain",
                    "healthy": False,
                    "complete": False,
                    "reason": "submission outcome remains unknown; manual reconciliation required",
                }
            )
            raise DeploymentUncertainError(state["reason"])

        batch_path = local_run / "batch.sh"
        batch_path.write_text(
            generate_batch_script(
                config,
                remote_run,
                submission_generation=state["submission_generation"],
            )
        )
        try:
            self._stage(state, local_run)
        except RemoteCommandError as error:
            self._write_state({**state, "phase": "failed", "healthy": False, "reason": str(error)})
            raise
        state = self._write_state(
            {**state, "phase": "submission_pending", "healthy": False, "submission_attempted": True}
        )
        return self._finish_submission_attempt(state)

    def resume(self, run_id: str) -> dict:
        validate_config({"run_id": run_id})
        state = self._read_state(run_id)
        if state.get("submission_attempted") and state.get("phase") in {
            "submission_pending", "resume_pending", "uncertain"
        }:
            reconciled = self._reconcile(state)
            if reconciled is not None and reconciled["phase"] != "uncertain":
                return self._write_state({**state, **reconciled})
            raise DeploymentUncertainError(
                "submission outcome remains unknown; manual reconciliation required"
            )

        config_path = self.state_root / run_id / "config.json"
        bundle_path = self.state_root / run_id / "source.tar.gz"
        try:
            config = validate_config(json.loads(config_path.read_text()), require_launch=True)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise LauncherError(f"saved configuration is invalid for run {run_id}") from error
        if config["run_id"] != run_id:
            raise LauncherError(f"saved configuration does not identify run {run_id}")
        if (
            not bundle_path.is_file()
            or _digest(bundle_path) != state.get("bundle_sha256")
            or _digest(config_path) != state.get("config_sha256")
        ):
            raise LauncherError(f"saved inputs are incomplete or changed for run {run_id}")

        campaign = self._remote_campaign_status(state)
        if campaign.returncode != 0:
            raise DeploymentUncertainError(
                f"cannot verify remote campaign status: {campaign.stderr.strip() or 'SSH failed'}"
            )
        kind, _, payload = campaign.stdout.strip().partition("\t")
        if kind == "STATUS":
            try:
                remote_status = json.loads(payload)
            except json.JSONDecodeError as error:
                raise DeploymentUncertainError("remote campaign status is invalid") from error
            status_job_id = str(remote_status.get("job_id", ""))
            current_job_id = str(state.get("job_id", ""))
            if (
                remote_status.get("status") == "completed"
                and remote_status.get("hardware_verified") is True
                and (not status_job_id or status_job_id == current_job_id)
            ):
                raise LauncherError(f"run {run_id} is already complete")
        elif kind != "MISSING":
            raise DeploymentUncertainError("remote campaign status is unrecognized")

        job_kind, slurm_state = self._job_state(state)
        if job_kind != "TERMINAL":
            raise LauncherError(f"run {run_id} still has an active Slurm job ({slurm_state})")

        generation = int(state.get("submission_generation", 1)) + 1
        history = list(state.get("submission_history", []))
        history.append(
            {
                "generation": int(state.get("submission_generation", 1)),
                "job_id": state["job_id"],
                "slurm_state": slurm_state,
                "verified_terminal_at": _now(),
            }
        )
        batch_path = self.state_root / run_id / "batch.sh"
        batch_path.write_text(
            generate_batch_script(config, state["remote_run_dir"], submission_generation=generation)
        )
        upload = self._run(
            [
                "scp", "--", str(batch_path),
                f"{state['login']}:{state['remote_run_dir']}/batch.sh",
            ],
            timeout=600,
        )
        if upload.returncode != 0:
            raise RemoteCommandError(f"resume batch staging failed: {upload.stderr.strip() or 'scp failed'}")

        next_state = {key: value for key, value in state.items() if key != "job_id"}
        next_state = self._write_state(
            {
                **next_state,
                "phase": "resume_pending",
                "healthy": False,
                "complete": False,
                "reason": "",
                "submission_attempted": True,
                "submission_generation": generation,
                "submission_history": history,
            }
        )
        return self._finish_submission_attempt(next_state)

    def status(self, run_id: str) -> dict:
        validate_config({"run_id": run_id})
        state = self._read_state(run_id)
        base_state = {key: value for key, value in state.items() if key != "last_status"}
        remote = state["remote_run_dir"]
        command = "\n".join(
            [
                "set -eu",
                f"status={shlex.quote(remote + '/status.json')}",
                'if [ -f "$status" ]; then printf "STATUS\\t"; cat "$status"; exit 0; fi',
                f"job_id={shlex.quote(str(state.get('job_id', '')))}",
                'if [ -n "$job_id" ]; then slurm=$(squeue -h -j "$job_id" -o "%T" 2>/dev/null | head -n 1 || true); else slurm=""; fi',
                'if [ -n "$slurm" ]; then printf "SLURM\\t%s\\n" "$slurm"; else printf "MISSING\\n"; fi',
            ]
        )
        result = self._ssh(state["login"], command, timeout=90)
        if result.returncode != 0:
            observed = {
                **base_state,
                "phase": "unverified",
                "healthy": False,
                "complete": False,
                "reason": result.stderr.strip() or "remote status check failed",
            }
        else:
            kind, _, payload = result.stdout.strip().partition("\t")
            if kind == "STATUS":
                try:
                    remote_status = json.loads(payload)
                except json.JSONDecodeError:
                    remote_status = {}
                remote_phase = remote_status.get("status")
                status_job_id = str(remote_status.get("job_id", ""))
                current_job_id = str(state.get("job_id", ""))
                if status_job_id and current_job_id and status_job_id != current_job_id:
                    observed = {
                        **base_state,
                        "phase": "submitted",
                        "healthy": False,
                        "complete": False,
                        "reason": "remote campaign status belongs to a previous Slurm job",
                        "previous_job_status": remote_status,
                    }
                    self._write_state({**base_state, "last_status": observed})
                    return observed
                hardware_verified = remote_status.get("hardware_verified") is True
                known_phase = remote_phase in {
                    "running", "completed", "partial", "failed", "interrupted"
                }
                scheduler_override = None
                if remote_phase == "running" and hardware_verified:
                    try:
                        job_kind, slurm_state = self._job_state(state)
                    except DeploymentUncertainError as error:
                        scheduler_override = {
                            "phase": "unverified",
                            "healthy": False,
                            "complete": False,
                            "reason": str(error),
                            "stale_remote_status": remote_status,
                        }
                    else:
                        if job_kind == "TERMINAL":
                            scheduler_override = {
                                "phase": "job_finished" if slurm_state == "COMPLETED" else "failed",
                                "healthy": False,
                                "complete": False,
                                "slurm_state": slurm_state,
                                "stale_remote_status": remote_status,
                            }
                        elif slurm_state not in {"RUNNING", "COMPLETING"}:
                            scheduler_override = {
                                "phase": "submitted",
                                "healthy": False,
                                "complete": False,
                                "slurm_state": slurm_state,
                                "stale_remote_status": remote_status,
                            }
                if scheduler_override is not None:
                    observed = {**base_state, **scheduler_override}
                else:
                    complete = remote_phase == "completed" and hardware_verified
                    healthy = remote_phase in {"running", "completed"} and hardware_verified
                    if remote_phase == "completed" and not hardware_verified:
                        phase = "unverified"
                    else:
                        phase = remote_phase if known_phase else "unverified"
                    observed = {
                        **base_state,
                        "phase": phase,
                        "healthy": healthy,
                        "complete": complete,
                        "remote_status": remote_status,
                    }
            elif kind == "SLURM" and payload.upper() in _SBATCH_STATES:
                slurm_state = payload.upper()
                observed = {
                    **base_state,
                    "phase": "submitted",
                    "healthy": False,
                    "complete": False,
                    "slurm_state": slurm_state,
                }
            else:
                observed = {
                    **base_state,
                    "phase": "unverified",
                    "healthy": False,
                    "complete": False,
                    "reason": "no remote status or active Slurm job was found",
                }
        self._write_state({**base_state, "last_status": observed})
        return observed

    def fetch(self, run_id: str, destination: str | Path) -> Path:
        validate_config({"run_id": run_id})
        state = self._read_state(run_id)
        remote = state["remote_run_dir"]
        token = uuid.uuid4().hex
        remote_archive = f"{remote}/exports/export-{token}.tar.gz"
        remote_manifest = remote_archive + ".manifest.json"
        python_path = f"{remote}/source:{remote}/source/engram"
        command = "\n".join(
            [
                "set -eu",
                "# SUPER YAK EXPORT",
                f"cd {shlex.quote(remote + '/source')}",
                f"PYTHONPATH={shlex.quote(python_path)} {shlex.quote(remote + '/.venv/bin/python')} "
                f"-m deploy.stampede.export --run-dir {shlex.quote(remote)} "
                f"--output {shlex.quote(remote_archive)}",
            ]
        )
        result = self._ssh(state["login"], command, timeout=600)
        if result.returncode != 0:
            raise RemoteCommandError(f"remote fetch preparation failed: {result.stderr.strip()}")
        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RemoteCommandError("remote export returned invalid metadata") from error
        if (
            not isinstance(metadata, dict)
            or metadata.get("archive") != remote_archive
            or metadata.get("manifest_path") != remote_manifest
            or not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("archive_sha256", "")))
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(metadata.get("export_manifest_sha256", ""))
            )
        ):
            raise RemoteCommandError("remote export metadata failed validation")
        destination_path = Path(destination).resolve()
        destination_path.mkdir(parents=True, exist_ok=True)
        local_archive = destination_path / f"{run_id}-artifacts.tar.gz"
        local_manifest = local_archive.with_name(local_archive.name + ".manifest.json")
        temporary_archive = destination_path / f".{local_archive.name}.{token}.tmp"
        temporary_manifest = destination_path / f".{local_manifest.name}.{token}.tmp"
        try:
            for remote_path, local_path in (
                (remote_archive, temporary_archive),
                (remote_manifest, temporary_manifest),
            ):
                result = self._run(
                    ["scp", "--", f"{state['login']}:{remote_path}", str(local_path)],
                    timeout=1800,
                )
                if result.returncode != 0:
                    raise RemoteCommandError(f"artifact fetch failed: {result.stderr.strip()}")
            sidecar = json.loads(temporary_manifest.read_text())
            if (
                sidecar.get("archive_sha256") != metadata["archive_sha256"]
                or sidecar.get("export_manifest_sha256")
                != metadata["export_manifest_sha256"]
                or _digest(temporary_archive) != metadata["archive_sha256"]
            ):
                raise RemoteCommandError("fetched export digest validation failed")
            os.replace(temporary_archive, local_archive)
            os.replace(temporary_manifest, local_manifest)
        except (OSError, json.JSONDecodeError) as error:
            raise RemoteCommandError("fetched export manifest is invalid") from error
        finally:
            for temporary_path in (temporary_archive, temporary_manifest):
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
        self._write_state(
            {
                **state,
                "last_fetch": {
                    "archive": str(local_archive),
                    "manifest": str(local_manifest),
                    "archive_sha256": metadata["archive_sha256"],
                    "export_manifest_sha256": metadata["export_manifest_sha256"],
                    "fetched_at": _now(),
                },
            }
        )
        return local_archive
