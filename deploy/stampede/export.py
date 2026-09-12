"""Create a consistent, digest-checked archive of durable campaign artifacts."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import uuid


_GENERATION = re.compile(r"g-[0-9a-f]{32}\Z")
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_STATIC_FILES = (
    "status.json",
    "bootstrap-status.json",
    "config.json",
    "source.tar.gz",
    "source/bundle-manifest.json",
    "campaign-backend.json",
    "model/manifest.json",
    "model/resolved.json",
    "model/gguf.json",
    "profiles/vllm/installed.json",
    "profiles/vllm/status.json",
    "profiles/vllm/dependencies.lock",
    "profiles/vllm/installed-freeze.txt",
    "profiles/sycl/installed.json",
    "profiles/sycl/status.json",
    "profiles/sycl/dependencies.lock",
    "profiles/sycl/installed-freeze.txt",
)
_LIVE_TREES = ("nodes", "logs", "results")


class ExportError(RuntimeError):
    """A complete, consistent export could not be constructed."""


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExportError(f"invalid JSON artifact: {path}") from error
    if not isinstance(value, dict):
        raise ExportError(f"JSON artifact is not an object: {path}")
    return value


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ExportError(f"artifact is not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if source.is_symlink() or not source.is_dir():
        raise ExportError(f"artifact tree is invalid: {source}")
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file():
            _copy_file(path, destination / path.relative_to(source))


def _copy_cell(cell: Path, export_root: Path) -> dict:
    if not _SAFE_NAME.fullmatch(cell.name):
        raise ExportError(f"unsafe cell directory: {cell.name}")
    lock_path = cell / "snapshot.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pointer = _load_object(cell / "CURRENT")
        generation_name = pointer.get("generation")
        if not isinstance(generation_name, str) or not _GENERATION.fullmatch(generation_name):
            raise ExportError(f"invalid CURRENT generation for {cell.name}")
        generation = cell / "generations" / generation_name
        manifest = _load_object(generation / "manifest.json")
        files = manifest.get("files")
        if not isinstance(files, dict) or "state.json" not in files:
            raise ExportError(f"invalid generation manifest for {cell.name}")

        destination = export_root / "cells" / cell.name
        copied = {}
        for filename, expected in sorted(files.items()):
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or not isinstance(expected, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected)
            ):
                raise ExportError(f"invalid generation manifest entry for {cell.name}")
            source = generation / filename
            if _digest(source) != expected:
                raise ExportError(f"generation digest mismatch: {cell.name}/{filename}")
            target = destination / "generations" / generation_name / filename
            _copy_file(source, target)
            if _digest(target) != expected:
                raise ExportError(f"export digest mismatch: {cell.name}/{filename}")
            copied[filename] = expected

        _copy_file(generation / "manifest.json", destination / "generations" / generation_name / "manifest.json")
        (destination / "CURRENT").write_text(
            json.dumps({"generation": generation_name}, sort_keys=True) + "\n"
        )
        _copy_file(
            destination / "generations" / generation_name / "state.json",
            destination / "result.json",
        )
        if (cell / "scheduler.json").is_file() and not (cell / "scheduler.json").is_symlink():
            _copy_file(cell / "scheduler.json", destination / "scheduler.json")
    return {"cell": cell.name, "generation": generation_name, "files": copied}


def _manifest(export_root: Path, cells: list[dict]) -> dict:
    files = []
    for path in sorted(export_root.rglob("*")):
        if path.is_file() and path.name != "export-manifest.json":
            files.append(
                {
                    "path": path.relative_to(export_root).as_posix(),
                    "sha256": _digest(path),
                    "size": path.stat().st_size,
                }
            )
    return {"format": "superyak-stampede-export-v1", "cells": cells, "files": files}


def _archive_tree(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                    for path in sorted(source.rglob("*")):
                        if not path.is_file() or path.is_symlink():
                            continue
                        info = tarfile.TarInfo(path.relative_to(source).as_posix())
                        info.size = path.stat().st_size
                        info.mode = 0o644
                        info.mtime = 0
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def create_export(run_dir: str | Path, output: str | Path) -> dict:
    """Freeze one complete generation per cell and publish a verified archive."""
    run = Path(run_dir).resolve()
    destination = Path(output).resolve()
    if not run.is_dir():
        raise ExportError(f"run directory does not exist: {run}")
    if not destination.is_relative_to(run) or destination == run:
        raise ExportError("export output must be inside the run directory")

    exports = run / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".freeze-", dir=exports) as temporary:
        frozen = Path(temporary)
        for relative in _STATIC_FILES:
            source = run / relative
            if source.is_file() and not source.is_symlink():
                _copy_file(source, frozen / relative)
        for relative in _LIVE_TREES:
            _copy_tree(run / relative, frozen / relative)

        cells = []
        cells_root = run / "cells"
        if cells_root.exists():
            if cells_root.is_symlink() or not cells_root.is_dir():
                raise ExportError("cells artifact tree is invalid")
            for cell in sorted(cells_root.iterdir()):
                if cell.is_dir() and not cell.is_symlink() and (cell / "CURRENT").is_file():
                    cells.append(_copy_cell(cell, frozen))

        manifest = _manifest(frozen, cells)
        manifest_path = frozen / "export-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        export_manifest_sha256 = _digest(manifest_path)
        _archive_tree(frozen, destination)

    archive_sha256 = _digest(destination)
    sidecar = destination.with_name(destination.name + ".manifest.json")
    sidecar_value = {
        "format": "superyak-stampede-export-sidecar-v1",
        "archive": destination.name,
        "archive_sha256": archive_sha256,
        "export_manifest_sha256": export_manifest_sha256,
        "cells": [item["cell"] for item in cells],
        "files": len(manifest["files"]),
    }
    fd, temporary_name = tempfile.mkstemp(prefix=f".{sidecar.name}.", dir=sidecar.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(sidecar_value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, sidecar)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return {
        "archive": str(destination),
        "archive_sha256": archive_sha256,
        "manifest_path": str(sidecar),
        "export_manifest_sha256": export_manifest_sha256,
        "cells": len(cells),
        "files": len(manifest["files"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = create_export(args.run_dir, args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
