"""Engram configuration — loads .engram/config.toml with sensible defaults."""

from __future__ import annotations

import os
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
    core_innovation_floor: float = 0.05


@dataclass
class ClassificationConfig:
    model: str = "gemma4:31b"
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
    # "tiebreak" caps recency so it decides near-ties only; "additive" is
    # the historical similarity*w_sim + recency*w_rec formula.
    recency_mode: str = "tiebreak"
    recency_cap: float = 0.02  # provisional — equals the near-tie threshold
    # Lane an untagged remember() gets in this instance.
    default_lane: str = "personal"


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
class CohesionConfig:
    # gate stays inert until read-only calibration clears it (spec: acceptance)
    enabled: bool = False
    dl_cost: float = 0.15
    variance_threshold: float = 0.90
    max_subspace_dim: int = 8
    min_episodes: int = 3
    sleep_budget: int = 3


@dataclass
class PersistenceConfig:
    # forgetting stays inert until read-only calibration clears it (spec)
    enabled: bool = False
    min_split_band: float = 0.10
    redundancy_floor: float = 0.85
    protect_threshold: float = 0.6
    generativity_threshold: float = 0.0  # 0 disables until calibrated
    cold_uninvited_p: float = 0.05


@dataclass
class CategoryEvolutionConfig:
    enabled: bool = False
    shadow: bool = True
    influence_recall: bool = False
    auto_commit: bool = False
    db_path: str = ""
    archive_quota_bytes: int = 3_000_000_000_000
    archive_high_watermark_ratio: float = 0.90
    interpreted_max_dimension: int = 2
    max_traversal_depth: int = 4
    max_neighbors: int = 64
    max_candidates: int = 50_000
    compile_wall_time_ms: int = 500
    consolidation_event_interval: int = 250
    consolidation_rewrite_budget: int = 32
    max_rewrite_members: int = 32
    max_active_branches: int = 4
    soft_boundary_threshold: float = 0.35
    hard_boundary_threshold: float = 0.65
    hard_boundary_confirmations: int = 2


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
    cohesion: CohesionConfig = field(default_factory=CohesionConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    category_evolution: CategoryEvolutionConfig = field(default_factory=CategoryEvolutionConfig)
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
recency_mode = "tiebreak"
recency_cap = 0.02
default_lane = "personal"

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
model = "gemma4:31b"
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

[cohesion]
enabled = false
dl_cost = 0.15
variance_threshold = 0.90
max_subspace_dim = 8
min_episodes = 3
sleep_budget = 3

[persistence]
enabled = false
min_split_band = 0.10
redundancy_floor = 0.85
protect_threshold = 0.6
generativity_threshold = 0.0
cold_uninvited_p = 0.05

[category_evolution]
enabled = false
shadow = true
influence_recall = false
auto_commit = false
db_path = ""
archive_quota_bytes = 3000000000000
archive_high_watermark_ratio = 0.90
interpreted_max_dimension = 2
max_traversal_depth = 4
max_neighbors = 64
max_candidates = 50000
compile_wall_time_ms = 500
consolidation_event_interval = 250
consolidation_rewrite_budget = 32
max_rewrite_members = 32
max_active_branches = 4
soft_boundary_threshold = 0.35
hard_boundary_threshold = 0.65
hard_boundary_confirmations = 2
"""


def load_config(project_root: Path | None = None) -> EngramConfig:
    """Load config from .engram/config.toml, creating defaults if missing."""
    import logging
    from dataclasses import fields as dataclass_fields

    if project_root is None:
        project_root = Path.cwd()

    config_dir = project_root / ".engram"
    config_file = config_dir / "config.toml"

    if not config_file.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file.write_text(_DEFAULT_TOML)

    raw = tomllib.loads(config_file.read_text())

    def load_section(name: str, config_type):
        values = raw.get(name, {})
        allowed = {item.name for item in dataclass_fields(config_type)}
        for key in sorted(set(values) - allowed):
            logging.getLogger("engram.config").warning(
                "Ignoring unknown config key [%s].%s in %s",
                name,
                key,
                config_file,
            )
        return config_type(
            **{key: value for key, value in values.items() if key in allowed}
        )

    return EngramConfig(
        embedding=load_section("embedding", EmbeddingConfig),
        indexing=load_section("indexing", IndexingConfig),
        extraction=load_section("extraction", ExtractionConfig),
        entity_resolution=load_section(
            "entity_resolution", EntityResolutionConfig
        ),
        memory=load_section("memory", MemoryConfig),
        watcher=load_section("watcher", WatcherConfig),
        communities=load_section("communities", CommunityConfig),
        ranking=load_section("ranking", RankingConfig),
        compression=load_section("compression", CompressionConfig),
        classification=load_section("classification", ClassificationConfig),
        reflection=load_section("reflection", ReflectionConfig),
        signals=load_section("signals", SignalsConfig),
        resonance=load_section("resonance", ResonanceConfig),
        graph=load_section("graph", GraphConfig),
        cohesion=load_section("cohesion", CohesionConfig),
        persistence=load_section("persistence", PersistenceConfig),
        category_evolution=load_section(
            "category_evolution", CategoryEvolutionConfig
        ),
        instance=raw.get("instance"),
        session_context=raw.get("session_context"),
    )


def resolve_instance_name(
    config: EngramConfig | None,
    default_instance: str | None = None,
) -> str | None:
    """Choose a project binding, falling back to the configured default."""
    if config and config.instance:
        return config.instance
    if default_instance is None:
        default_instance = os.environ.get("ENGRAM_DEFAULT_INSTANCE")
    if default_instance:
        return default_instance.strip() or None
    return None


def resolve_db_path(
    engram_home: Path,
    project_root: Path | None = None,
    default_instance: str | None = None,
) -> Path:
    """Resolve the active graph.db, honoring instance routing.

    An explicit project binding wins. Otherwise ``ENGRAM_DEFAULT_INSTANCE``
    supplies the binding for projects that have not opted into a distinct
    identity. If the selected store does not exist, the legacy top-level
    ``.engram/graph.db`` remains the compatibility fallback.
    """
    import logging

    default = engram_home / ".engram" / "graph.db"
    config_root = project_root or engram_home
    try:
        config = load_config(config_root)
    except Exception as error:
        logging.getLogger("engram.config").warning(
            "Could not load config %s: %s; falling back to %s",
            config_root / ".engram" / "config.toml",
            error,
            default,
        )
        config = None
    instance_name = resolve_instance_name(config, default_instance)
    if instance_name:
        instance_db = engram_home / ".engram" / "instances" / instance_name / "graph.db"
        if instance_db.exists():
            return instance_db
        logging.getLogger("engram.config").warning(
            "Configured instance store %s does not exist; falling back to %s",
            instance_db,
            default,
        )
    return default
