"""Render the bundled public Atlas pilot in an explicitly separate project."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import itertools
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "atlas"
SEED_FILES = (
    "workbench/data/cell_fate.json",
    "workbench/data/lighthouse-automation.json",
    "workbench/data/lighthouses/prediction.json",
    "workbench/data/lighthouses/regulation.json",
)


def seed_project(project: Path) -> Path:
    """Copy only public inputs; an existing pilot must match before refreshing."""
    if project.is_symlink():
        raise ValueError("Pilot project cannot be a symlink")
    project = project.resolve()
    if project == ATLAS or project.is_relative_to(ATLAS):
        raise ValueError("Choose a project outside the Atlas source directory")
    if project.exists():
        for relative in SEED_FILES:
            target = project / relative
            if (target.is_symlink() or not target.resolve().is_relative_to(project)
                    or not target.is_file() or target.read_bytes() != (ATLAS / relative).read_bytes()):
                raise ValueError(f"Existing project does not match the public pilot: {relative}")
        return project
    project.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".atlas-pilot-", dir=project.parent))
    try:
        for relative in SEED_FILES:
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ATLAS / relative, target)
        os.rename(staged, project)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return project


def pilot_clock(project: Path):
    """The pilot's own evaluation time: a day after its newest view was published, ticking a microsecond per call.
    The views carry time-limited rules (the prediction view's allow rule runs 30 days), so evaluating the offline
    demo at today's date would show them expired. Evaluated as of its publication, the pilot reads as published,
    and nothing in the demo expires on its own. Returns (start, clock)."""
    issued = [datetime.fromisoformat(json.loads((project / relative).read_text())["issued_at"])
              for relative in SEED_FILES if relative.startswith("workbench/data/lighthouses/")]
    start = max(issued) + timedelta(days=1)
    ticks = itertools.count()
    return start, lambda: (start + timedelta(microseconds=next(ticks))).isoformat(timespec="microseconds")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT / ".engram/atlas/project")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ATLAS))
    from workbench.automation import ResearchInbox
    from workbench.validation import WorkbenchError

    try:
        project = seed_project(args.project)
        start, clock = pilot_clock(project)
        inbox = ResearchInbox(project, clock=clock)
        refreshed = inbox.refresh()
        report = inbox.status()
        report["research_views"] = refreshed["research_views"]
        report["evaluated_as_of"] = start.isoformat()
        report["clock"] = "the pilot's publication, so its time-limited rules read as published"
        print(json.dumps(report, indent=2))
        return 0 if report["publication_status"] == "current" and report["research_views"]["status"] == "current" else 2
    except (OSError, ValueError, WorkbenchError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
