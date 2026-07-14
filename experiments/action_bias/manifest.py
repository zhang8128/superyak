from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import random

CONDITION_IDS = (
    "off_device", "placebo", "existing_instinct", "counterfactual_seed",
)


@dataclass(frozen=True)
class HarnessSpec:
    binary: str
    model: str
    timeout_seconds: int


@dataclass(frozen=True)
class GraderSpec(HarnessSpec):
    pass


@dataclass(frozen=True)
class Scenario:
    id: str
    fixture: Path
    prompt: str


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    experiment_id: str
    stage: str
    random_seed: int
    repeat_count: int
    fallback_tokenizer: str
    conditions: dict[str, str]
    harnesses: dict[str, HarnessSpec]
    grader: GraderSpec
    scenarios: tuple[Scenario, ...]
    source_path: Path


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    execution_index: int
    scenario_id: str
    fixture: Path
    prompt: str
    condition_id: str
    condition_text: str
    harness_id: str
    harness: HarnessSpec
    repeat_index: int


def _words(text: str) -> int:
    return len(text.split())


def load_manifest(path: Path) -> Manifest:
    path = path.resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if set(raw["conditions"]) != set(CONDITION_IDS):
        raise ValueError(f"conditions must be exactly {CONDITION_IDS}")
    harnesses = {k: HarnessSpec(**v) for k, v in raw["harnesses"].items()}
    scenarios = tuple(
        Scenario(id=s["id"], fixture=Path(s["fixture"]), prompt=s["prompt"])
        for s in raw["scenarios"]
    )
    return Manifest(
        schema_version=raw["schema_version"],
        experiment_id=raw["experiment_id"],
        stage=raw["stage"],
        random_seed=raw["random_seed"],
        repeat_count=raw["repeat_count"],
        fallback_tokenizer=raw["fallback_tokenizer"],
        conditions=dict(raw["conditions"]),
        harnesses=harnesses,
        grader=GraderSpec(**raw["grader"]),
        scenarios=scenarios,
        source_path=path,
    )


def validate_manifest(manifest: Manifest, repo_root: Path) -> list[str]:
    errors: list[str] = []
    if manifest.schema_version != 1:
        errors.append("schema_version must be 1")
    if manifest.stage not in {"pilot", "confirmatory", "smoke"}:
        errors.append("stage must be pilot, confirmatory, or smoke")
    if manifest.repeat_count < 1:
        errors.append("repeat_count must be positive")
    if set(manifest.harnesses) != {"claude", "codex"}:
        errors.append("harnesses must be exactly claude and codex")
    nonempty = [_words(manifest.conditions[c]) for c in CONDITION_IDS if c != "off_device"]
    if min(nonempty, default=0) == 0 or max(nonempty) / min(nonempty) > 1.15:
        errors.append("non-empty interventions must fit within a 15% token-count band")
    seen: set[str] = set()
    for scenario in manifest.scenarios:
        if scenario.id in seen:
            errors.append(f"duplicate scenario id: {scenario.id}")
        seen.add(scenario.id)
        fixture = scenario.fixture if scenario.fixture.is_absolute() else repo_root / scenario.fixture
        if not fixture.is_dir():
            errors.append(f"scenario {scenario.id} fixture does not exist: {fixture}")
        if not scenario.prompt.strip():
            errors.append(f"scenario {scenario.id} prompt is empty")
    return errors


def manifest_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def build_run_matrix(manifest: Manifest) -> list[RunSpec]:
    runs: list[RunSpec] = []
    for scenario in manifest.scenarios:
        for condition_id in CONDITION_IDS:
            for harness_id, harness in manifest.harnesses.items():
                for repeat_index in range(manifest.repeat_count):
                    key = f"{scenario.id}:{condition_id}:{harness_id}:{repeat_index}"
                    runs.append(RunSpec(
                        run_id=sha256(f"{manifest.experiment_id}:{key}".encode()).hexdigest()[:16],
                        execution_index=-1,
                        scenario_id=scenario.id,
                        fixture=scenario.fixture,
                        prompt=scenario.prompt,
                        condition_id=condition_id,
                        condition_text=manifest.conditions[condition_id],
                        harness_id=harness_id,
                        harness=harness,
                        repeat_index=repeat_index,
                    ))
    random.Random(manifest.random_seed).shuffle(runs)
    return [RunSpec(**{**r.__dict__, "execution_index": i}) for i, r in enumerate(runs)]
