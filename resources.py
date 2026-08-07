"""Resolve runtime assets from a source checkout or an installed wheel."""

from __future__ import annotations

import sys
from pathlib import Path


_SOURCE_ROOT = Path(__file__).resolve().parent
_INSTALL_ROOT = Path(sys.prefix) / "share" / "engram"


def resource_path(relative: str) -> Path:
    """Return the source or installed path for an Engram runtime asset."""
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise ValueError("Engram resource path must be relative")
    if ".." in relative_path.parts:
        raise ValueError("Engram resource path cannot contain parent traversal")

    source_path = _SOURCE_ROOT / relative_path
    if source_path.exists():
        return source_path

    installed_path = _INSTALL_ROOT / relative_path
    if installed_path.exists():
        return installed_path

    return source_path
