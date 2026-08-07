"""Resolve runtime assets from a source checkout or an installed wheel."""

from __future__ import annotations

import sys
from pathlib import Path


_SOURCE_ROOT = Path(__file__).resolve().parent
_INSTALL_ROOT = Path(sys.prefix) / "share" / "engram"


def resource_path(relative: str) -> Path:
    """Return the source or installed path for an Engram runtime asset."""
    source_path = _SOURCE_ROOT / relative
    if source_path.exists():
        return source_path

    installed_path = _INSTALL_ROOT / relative
    if installed_path.exists():
        return installed_path

    return source_path
