"""Unified memory graph — virtual view over engram's relationship types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage import Storage

@dataclass
class Edge:
    source: str
    source_layer: str
    target: str
    target_layer: str
    edge_type: str
    weight: float
    directed: bool

    def __post_init__(self):
        self.weight = max(0.0, min(1.0, self.weight))

@dataclass
class Node:
    id: str
    layer: str
    preview: str
