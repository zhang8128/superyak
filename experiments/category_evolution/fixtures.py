"""Fixed, vocabulary-isolated cohorts for category evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import random
from typing import Literal, Mapping

from category_context import ContextObservation


_SEED = 20260807
_DOMAINS = ("conversation", "coding", "reading_media", "planning")
_WORDS = {
    "development": (
        ("dialogue", "speaker", "reply", "agenda"),
        ("module", "function", "branch", "terminal"),
        ("article", "chapter", "citation", "playlist"),
        ("milestone", "backlog", "calendar", "owner"),
    ),
    "holdout": (
        ("interview", "guest", "remark", "topic"),
        ("repository", "method", "revision", "console"),
        ("documentary", "volume", "footnote", "broadcast"),
        ("roadmap", "queue", "schedule", "steward"),
    ),
}


@dataclass(frozen=True)
class BoundaryCase:
    domain: str
    structure: str
    kind: Literal["explicit", "abrupt", "gradual"]
    expected_boundary: bool
    observations: tuple[ContextObservation, ...]
    expected_decisions: tuple[bool, ...]


@dataclass(frozen=True)
class RankingCase:
    domain: str
    query: str
    direct_query: str
    relevant_variant: Literal[0, 1]
    negative_transfer_truth: bool


@dataclass(frozen=True)
class FixtureCohort:
    name: Literal["development", "holdout"]
    seed: int
    cases: tuple[BoundaryCase, ...]
    rankings: tuple[RankingCase, ...]
    vocabulary: frozenset[str]


def fixture_cohort(name: Literal["development", "holdout"], *, seed: int = _SEED) -> FixtureCohort:
    """Build a deterministic cohort; labels belong to this harness, never production code."""
    if name not in _WORDS:
        raise ValueError("cohort must be development or holdout")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    cases: list[BoundaryCase] = []
    rankings: list[RankingCase] = []
    vocabulary: set[str] = set()
    for domain_index, (domain, words) in enumerate(zip(_DOMAINS, _WORDS[name], strict=True)):
        vocabulary.update(words)
        cases.extend(_domain_cases(domain, words))
        rankings.append(RankingCase(
            domain=domain,
            query=f"{words[0]} {words[1]}",
            direct_query=f"{words[2]} {words[3]}",
            relevant_variant=domain_index // 2,
            negative_transfer_truth=True,
        ))
    random.Random(seed).shuffle(cases)
    random.Random(seed ^ 0x5A5A).shuffle(rankings)
    return FixtureCohort(name, seed, tuple(cases), tuple(rankings), frozenset(vocabulary))


def fixture_hash(cohort: FixtureCohort) -> str:
    """Hash canonical, sorted fixture content independently of process/hash order."""
    if not isinstance(cohort, FixtureCohort):
        raise TypeError("cohort must be a FixtureCohort")
    payload = {
        "name": cohort.name,
        "seed": cohort.seed,
        "cases": sorted((_case_payload(case) for case in cohort.cases), key=_canonical_json),
        "rankings": sorted((_ranking_payload(case) for case in cohort.rankings), key=_canonical_json),
        "vocabulary": sorted(cohort.vocabulary),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _domain_cases(domain: str, words: tuple[str, str, str, str]) -> list[BoundaryCase]:
    base, target, source, tool = words
    initial = _observation(base, source, tool, minute=0)
    gradual_changed = _observation(target, source, tool, minute=1)
    abrupt_changed = _observation(f"{target}_goal", f"{source}_entity", f"{tool}_tool", minute=1)
    same = _observation(base, source, tool, minute=1)
    restored = _observation(base, source, tool, minute=2)
    overlap = ContextObservation(
        goal={base: 0.8, target: 0.2}, entities={source: 1.0}, tools={tool: 1.0},
        observed_at=datetime(2026, 8, 7, tzinfo=timezone.utc) + timedelta(minutes=1),
    )
    source_only = ContextObservation(
        goal={base: 1.0}, entities={source: 1.0}, tools={tool: 1.0}, sources={target: 1.0},
        observed_at=datetime(2026, 8, 7, tzinfo=timezone.utc) + timedelta(minutes=1),
    )
    branch = _observation(f"{target}_branch", f"{source}_branch", f"{tool}_branch", minute=2)
    explicit = ContextObservation(**{**asdict(gradual_changed), "explicit_boundary": True})
    return [
        BoundaryCase(domain, "explicit-change", "explicit", True, (initial, explicit), (False, True)),
        BoundaryCase(domain, "confirmed-abrupt-change", "abrupt", True,
                     (initial, abrupt_changed, abrupt_changed), (False, False, True)),
        BoundaryCase(domain, "confirmed-gradual-change", "gradual", True,
                     (initial, gradual_changed, gradual_changed), (False, False, True)),
        BoundaryCase(domain, "stable-control", "gradual", False, (initial, same), (False, False)),
        BoundaryCase(domain, "return-to-prior", "abrupt", True,
                     (initial, abrupt_changed, abrupt_changed, restored, restored), (False, False, True, False, True)),
        BoundaryCase(domain, "overlap-control", "gradual", False, (initial, overlap), (False, False)),
        BoundaryCase(domain, "source-only-control", "gradual", False, (initial, source_only), (False, False)),
        BoundaryCase(domain, "fork-reconciliation", "abrupt", True,
                     (initial, abrupt_changed, abrupt_changed, branch, branch, restored, restored),
                     (False, False, True, False, True, False, True)),
    ]


def _observation(goal: str, entity: str, tool: str, *, minute: int) -> ContextObservation:
    return ContextObservation(
        goal={goal: 1.0},
        entities={entity: 1.0},
        tools={tool: 1.0},
        observed_at=datetime(2026, 8, 7, tzinfo=timezone.utc) + timedelta(minutes=minute),
    )


def _case_payload(case: BoundaryCase) -> Mapping[str, object]:
    return {
        "domain": case.domain,
        "structure": case.structure,
        "kind": case.kind,
        "expected_boundary": case.expected_boundary,
        "expected_decisions": list(case.expected_decisions),
        "observations": [
            {
                "goal": dict(observation.goal), "entities": dict(observation.entities),
                "participants": dict(observation.participants), "tools": dict(observation.tools),
                "sources": dict(observation.sources), "attention": dict(observation.attention),
                "observed_at": observation.observed_at.isoformat(),
                "explicit_boundary": observation.explicit_boundary,
            }
            for observation in case.observations
        ],
    }


def _ranking_payload(case: RankingCase) -> Mapping[str, object]:
    return {
        "domain": case.domain, "query": case.query, "direct_query": case.direct_query,
        "relevant_variant": case.relevant_variant,
        "negative_transfer_truth": case.negative_transfer_truth,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
