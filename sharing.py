"""Explicit sharing into the published house, with an audience.

Sharing is an act, not a derivation. A shared row is a COPY: the private
original keeps decaying and compressing on its own terms, and withdrawing a
share never deletes a memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

AUDIENCE_COMMONS = "commons"
GROUP_RE = re.compile(r"group:[a-z][a-z0-9-]{0,63}\Z")


@dataclass(frozen=True, slots=True)
class ShareRecord:
    share_id: str
    memory_id: str
    source_instance: str
    source_id: str
    layer: str
    audience: str
    reason: str
    content_digest: str
    shared_at: str


def validate_audience(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("audience must be a string")
    if value == AUDIENCE_COMMONS or GROUP_RE.fullmatch(value):
        return value
    raise ValueError(f"unknown audience: {value!r}")
