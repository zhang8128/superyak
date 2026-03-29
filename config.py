"""Engram configuration — loads .engram/config.toml with sensible defaults."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EmbeddingConfig:
    provider: str = "local"
    model: str = "nomic-embed-text-v1.5"
    dimension: int = 768


@dataclass
class IndexingConfig:
    languages: list[str] = field(
        default_factory=lambda: ["python", "typescript", "javascript", "rust", "go"]
    )
    exclude: list[str] = field(
        default_factory=lambda: ["node_modules", ".venv", "__pycache__", "dist", "build"]
    )


@dataclass
class ExtractionConfig:
    provider: str = "heuristic"
    conflict_threshold: float = 0.85


@dataclass
class EntityResolutionConfig:
    name_jaccard_threshold: float = 0.7
    embedding_similarity_threshold: float = 0.9


@dataclass
class CompressionConfig:
    auto_threshold: int = 10
    cluster_similarity: float = 0.75
    reinforce_threshold: float = 0.70
    instinct_confidence: float = 0.75


@dataclass
class ClassificationConfig:
    model: str = "qwen3.5:27b"
    prompt_path: str = "prompts/classify.txt"
    fallback: str = "heuristic"


@dataclass
class ReflectionConfig:
    enabled: bool = True
    log_retention_days: int = 90
    staleness_days: int = 30


@dataclass
class MemoryConfig:
    max_recall_results: int = 20
    graph_expansion_depth: int = 2
    similarity_weight: float = 0.6
    recency_weight: float = 0.4


@dataclass
class WatcherConfig:
    enabled: bool = True
    debounce_ms: int = 500
    extensions: list[str] = field(
        default_factory=lambda: [".py", ".js", ".ts", ".tsx", ".rs", ".go"]
    )


@dataclass
class CommunityConfig:
    min_size: int = 3
    max_depth: int = 3
    sub_cluster_threshold: int = 10
    cache_ttl_seconds: int = 300


@dataclass
class RankingConfig:
    similarity_weight: float = 0.5
    recency_weight: float = 0.3
    degree_weight: float = 0.2


@dataclass
class SignalsConfig:
    retention_days: int = 30


@dataclass
class ResonanceConfig:
    max_in_recall: int = 3


@dataclass
class GraphConfig:
    enabled: bool = True
    model: str = "nemotron-nano"
    ollama_url: str = "http://localhost:11434"
    db_path: str = ""  # set at runtime based on ENGRAM_HOME


@dataclass
class EngramConfig:
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    indexing: IndexingConfig = field(default_factory=IndexingConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    entity_resolution: EntityResolutionConfig = field(default_factory=EntityResolutionConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)
    communities: CommunityConfig = field(default_factory=CommunityConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    reflection: ReflectionConfig = field(default_factory=ReflectionConfig)
    signals: SignalsConfig = field(default_factory=SignalsConfig)
    resonance: ResonanceConfig = field(default_factory=ResonanceConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    instance: str | None = None
    session_context: str | None = None


_DEFAULT_TOML = """\
[embedding]
provider = "local"
model = "nomic-embed-text-v1.5"
dimension = 768

[indexing]
languages = ["python", "typescript", "javascript", "rust", "go"]
exclude = ["node_modules", ".venv", "__pycache__", "dist", "build"]

[extraction]
provider = "heuristic"
conflict_threshold = 0.85

[entity_resolution]
name_jaccard_threshold = 0.7
embedding_similarity_threshold = 0.9

[memory]
max_recall_results = 20
graph_expansion_depth = 2
similarity_weight = 0.6
recency_weight = 0.4

[watcher]
enabled = true
debounce_ms = 500
extensions = [".py", ".js", ".ts", ".tsx", ".rs", ".go"]

[communities]
min_size = 3
max_depth = 3
sub_cluster_threshold = 10
cache_ttl_seconds = 300

[ranking]
similarity_weight = 0.5
recency_weight = 0.3
degree_weight = 0.2

[compression]
auto_threshold = 10
cluster_similarity = 0.75
reinforce_threshold = 0.70
instinct_confidence = 0.75

[classification]
model = "qwen3.5:27b"
prompt_path = "prompts/classify.txt"
fallback = "heuristic"

[reflection]
enabled = true
log_retention_days = 90
staleness_days = 30

[signals]
retention_days = 30

[resonance]
max_in_recall = 3

[graph]
enabled = true
model = "nemotron-nano"
ollama_url = "http://localhost:11434"
"""


def load_config(project_root: Path | None = None) -> EngramConfig:
    """Load config from .engram/config.toml, creating defaults if missing."""
    if project_root is None:
        project_root = Path.cwd()

    config_dir = project_root / ".engram"
    config_file = config_dir / "config.toml"

    if not config_file.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file.write_text(_DEFAULT_TOML)

    raw = tomllib.loads(config_file.read_text())

    return EngramConfig(
        embedding=EmbeddingConfig(**raw.get("embedding", {})),
        indexing=IndexingConfig(**raw.get("indexing", {})),
        extraction=ExtractionConfig(**raw.get("extraction", {})),
        entity_resolution=EntityResolutionConfig(**raw.get("entity_resolution", {})),
        memory=MemoryConfig(**raw.get("memory", {})),
        watcher=WatcherConfig(**raw.get("watcher", {})),
        communities=CommunityConfig(**raw.get("communities", {})),
        ranking=RankingConfig(**raw.get("ranking", {})),
        compression=CompressionConfig(**raw.get("compression", {})),
        classification=ClassificationConfig(**raw.get("classification", {})),
        reflection=ReflectionConfig(**raw.get("reflection", {})),
        signals=SignalsConfig(**raw.get("signals", {})),
        resonance=ResonanceConfig(**raw.get("resonance", {})),
        graph=GraphConfig(**raw.get("graph", {})),
        instance=raw.get("instance"),
        session_context=raw.get("session_context"),
    )
