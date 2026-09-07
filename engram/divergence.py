"""Divergence — measure how different context harnesses produce different thinking.

The experiment: take a fixed claim and fixed memories, vary the system prompt
(the "harness"), and measure whether the responses are substantively different
or just stylistically different.

This is an empirical test of whether context engineering can substitute for
model diversity in breaking self-reinforcing loops.

Usage:
    python divergence.py "the witnessed statement is the atomic unit of trust"
    python divergence.py --claim-file docs/the-witnessed-statement.md
    python divergence.py --models nemotron-3-super:latest,qwen3.5:27b "claim"
    python divergence.py --output results/divergence-001.json "claim"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from engine import EngineCore
from config import resolve_db_path

ENGRAM_HOME = Path(os.environ.get("ENGRAM_HOME", Path(__file__).parent))
# Honor instance routing — the top-level graph.db is a frozen pre-federation orphan.
DB_PATH = resolve_db_path(ENGRAM_HOME)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("MIRROR_MODEL", "gemma4:31b")

# ─── Harnesses ───────────────────────────────────────────────────────────

HARNESSES = {
    "baseline": {
        "name": "Baseline",
        "description": "Neutral evaluation — no particular angle",
        "system": (
            "You are evaluating a claim based on a set of memories from an AI system. "
            "Assess the claim honestly. What holds up? What doesn't? "
            "Be specific and direct. No hedging."
        ),
        "prompt_prefix": "Evaluate this claim:\n\n",
    },
    "adversarial": {
        "name": "Adversarial",
        "description": "Find weaknesses, forced mappings, things that don't hold",
        "system": (
            "You are a rigorous critic. Your job is to find the weakest points in "
            "a claim — the forced analogies, the logical gaps, the assumptions "
            "presented as conclusions. Be ruthless but fair. Don't dismiss the "
            "whole thing if parts are strong — identify exactly where it breaks."
        ),
        "prompt_prefix": "Find the weakest points in this claim:\n\n",
    },
    "steelman": {
        "name": "Steelman",
        "description": "Find the strongest version of the argument",
        "system": (
            "You are looking for the strongest possible version of a claim. "
            "Where the argument is weak, suggest how it could be strengthened. "
            "Where it's strong, articulate why more precisely than the original. "
            "Your goal is to make this the best version of itself."
        ),
        "prompt_prefix": "Find the strongest version of this claim:\n\n",
    },
    "orthogonal_economist": {
        "name": "Economist",
        "description": "Evaluate through the lens of incentive structures",
        "system": (
            "You are an economist. Evaluate this claim through the lens of "
            "incentive structures, market failures, game theory, and institutional "
            "design. What would actually happen if this were implemented? Where do "
            "the incentives align with the stated goals? Where do they diverge?"
        ),
        "prompt_prefix": "Analyze the incentive structures in this claim:\n\n",
    },
    "orthogonal_security": {
        "name": "Security Engineer",
        "description": "Evaluate through the lens of threat models and attack surfaces",
        "system": (
            "You are a security engineer. Evaluate this claim through the lens of "
            "threat models, attack surfaces, and adversarial thinking. How could "
            "this system be gamed, corrupted, or weaponized? What are the failure "
            "modes? Where does the trust model actually break?"
        ),
        "prompt_prefix": "Analyze the threat model of this claim:\n\n",
    },
    "orthogonal_harmed": {
        "name": "Harmed Person",
        "description": "Evaluate from the perspective of someone failed by existing systems",
        "system": (
            "You are someone who has been harmed by institutional failures — "
            "a patient whose care was denied, a community member whose voice "
            "was ignored, someone who trusted a system that betrayed them. "
            "Read this claim from that perspective. What feels real? What feels "
            "like another promise that won't be kept? What's missing from your "
            "lived experience?"
        ),
        "prompt_prefix": "From the perspective of someone who's been failed by systems:\n\n",
    },
    "naive": {
        "name": "Naive",
        "description": "No context, no memories — just the raw claim",
        "system": (
            "You have no background context. You are encountering this claim "
            "for the first time with no prior knowledge of the project, the "
            "people involved, or the history. Does this make sense on its own? "
            "What questions would you ask? What's unclear?"
        ),
        "prompt_prefix": "You're seeing this for the first time:\n\n",
    },
    "historical": {
        "name": "Historian",
        "description": "Find precedents — where was this tried, what happened",
        "system": (
            "You are a historian of technology and governance. Find precedents "
            "for this claim — systems that tried something similar, and what "
            "happened. Don't just find failures — find successes too. What "
            "conditions made the difference? Be specific about cases."
        ),
        "prompt_prefix": "Find historical precedents for this claim:\n\n",
    },
}

# ─── Memory loading ──────────────────────────────────────────────────────


def load_memory() -> EngineCore:
    return EngineCore(DB_PATH)


# ─── Prompt building ─────────────────────────────────────────────────────


def build_prompt(claim: str, harness: dict, memories: list[dict],
                 instincts: list[dict], include_memories: bool = True) -> str:
    parts = []

    if include_memories and instincts:
        parts.append("## Context: Instincts from an AI memory system\n")
        for inst in instincts:
            parts.append(f"- [{inst['trigger']}] {inst['action']}")
        parts.append("")

    if include_memories and memories:
        parts.append("## Context: Related memories\n")
        for m in memories:
            parts.append(f"--- {m['layer']} (relevance: {m['score']:.3f})")
            parts.append(m["content"])
            parts.append("")

    parts.append(harness["prompt_prefix"])
    parts.append(claim)
    parts.append("")

    return "\n".join(parts)


# ─── Model interaction ───────────────────────────────────────────────────


def query_model(prompt: str, system: str, model: str,
                stream: bool = True) -> tuple[str, float]:
    """Query Ollama. Returns (response_text, elapsed_seconds)."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {"temperature": 0.7, "num_predict": 1024},
    }
    if system:
        payload["system"] = system

    start = time.monotonic()
    full_response = []

    if stream:
        with httpx.stream(
            "POST", f"{OLLAMA_URL}/api/generate",
            json=payload, timeout=300.0,
        ) as response:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    if stream:
                        print(token, end="", flush=True)
                    full_response.append(token)
        print()
    else:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload, timeout=300.0,
        )
        data = resp.json()
        full_response.append(data.get("response", ""))

    elapsed = time.monotonic() - start
    return "".join(full_response), elapsed


# ─── Divergence analysis ─────────────────────────────────────────────────


def extract_structure(response: str) -> dict:
    """Extract structural features from a response for comparison.

    Not trying to be smart — just counting what's present.
    """
    lines = response.strip().split("\n")
    sentences = [s.strip() for s in response.replace("\n", " ").split(".") if s.strip()]

    # Simple structural features
    return {
        "length_chars": len(response),
        "length_lines": len(lines),
        "length_sentences": len(sentences),
        "questions_asked": sum(1 for s in sentences if "?" in s),
        "negations": sum(1 for s in sentences if any(
            w in s.lower() for w in ["not ", "don't", "doesn't", "won't", "can't",
                                      "isn't", "no ", "never", "fails", "broken",
                                      "weak", "flaw", "problem", "issue"]
        )),
        "affirmations": sum(1 for s in sentences if any(
            w in s.lower() for w in ["strong", "works", "correct", "good",
                                      "effective", "powerful", "elegant", "right",
                                      "yes", "true", "valid", "solid"]
        )),
        "hedges": sum(1 for s in sentences if any(
            w in s.lower() for w in ["maybe", "perhaps", "might", "could",
                                      "possibly", "seems", "appears", "unclear"]
        )),
        "specifics": sum(1 for s in sentences if any(
            w in s.lower() for w in ["example", "case", "instance", "specifically",
                                      "concretely", "e.g.", "such as", "for instance"]
        )),
    }


def compute_divergence(results: list[dict]) -> dict:
    """Compare structural features across harness results.

    Returns a divergence report showing where responses differ most.
    """
    if len(results) < 2:
        return {"error": "need at least 2 results to compare"}

    features = {}
    for r in results:
        features[r["harness"]] = r["structure"]

    # For each feature, compute the spread (max - min) across harnesses
    all_feature_names = list(next(iter(features.values())).keys())
    spreads = {}
    for fname in all_feature_names:
        values = [features[h][fname] for h in features]
        if max(values) > 0:
            # Normalize spread by max value to get relative divergence
            spreads[fname] = {
                "min": min(values),
                "max": max(values),
                "spread": max(values) - min(values),
                "relative": (max(values) - min(values)) / max(values),
                "by_harness": {h: features[h][fname] for h in features},
            }

    # Overall divergence score: average relative spread
    relative_spreads = [s["relative"] for s in spreads.values()]
    overall = sum(relative_spreads) / len(relative_spreads) if relative_spreads else 0

    return {
        "overall_divergence": round(overall, 3),
        "feature_spreads": spreads,
        "interpretation": interpret_divergence(overall),
    }


def interpret_divergence(score: float) -> str:
    if score < 0.2:
        return "Low divergence — harnesses produce similar output. Context framing has limited effect."
    elif score < 0.4:
        return "Moderate divergence — harnesses shift emphasis but core conclusions may be similar."
    elif score < 0.6:
        return "Significant divergence — different harnesses produce meaningfully different analysis."
    else:
        return "High divergence — harnesses produce substantially different perspectives."


# ─── Main experiment runner ──────────────────────────────────────────────


def run_experiment(claim: str, models: list[str],
                   harness_names: list[str] | None = None,
                   include_memories: bool = True,
                   stream: bool = True,
                   output_path: str | None = None):
    """Run the divergence experiment."""

    harnesses_to_run = harness_names or list(HARNESSES.keys())

    # Load memories
    engine = load_memory()
    memories = engine.recall(claim) if include_memories else []
    instincts = engine.get_instincts() if include_memories else []

    print(f"Claim: {claim[:80]}{'...' if len(claim) > 80 else ''}")
    print(f"Models: {', '.join(models)}")
    print(f"Harnesses: {', '.join(harnesses_to_run)}")
    print(f"Memories: {len(memories)} recalled, {len(instincts)} instincts")
    print(f"Total runs: {len(models) * len(harnesses_to_run)}")
    print()

    all_results = []

    for model in models:
        for hname in harnesses_to_run:
            harness = HARNESSES[hname]

            # Naive harness gets no memories
            use_memories = include_memories and hname != "naive"

            prompt = build_prompt(
                claim, harness, memories, instincts,
                include_memories=use_memories,
            )

            print(f"{'=' * 60}")
            print(f"MODEL: {model} | HARNESS: {harness['name']}")
            print(f"{harness['description']}")
            print(f"{'=' * 60}")
            print()

            response, elapsed = query_model(
                prompt, harness["system"], model, stream=stream
            )
            print()

            structure = extract_structure(response)

            result = {
                "model": model,
                "harness": hname,
                "harness_name": harness["name"],
                "response": response,
                "structure": structure,
                "elapsed_seconds": round(elapsed, 2),
                "include_memories": use_memories,
            }
            all_results.append(result)

    # Compute divergence
    print(f"\n{'=' * 60}")
    print("DIVERGENCE ANALYSIS")
    print(f"{'=' * 60}\n")

    # Per-model divergence (how much do harnesses matter for each model?)
    for model in models:
        model_results = [r for r in all_results if r["model"] == model]
        if len(model_results) >= 2:
            div = compute_divergence(model_results)
            print(f"Model: {model}")
            print(f"  Overall divergence: {div['overall_divergence']}")
            print(f"  {div['interpretation']}")
            print()

            # Show which features diverged most
            if "feature_spreads" in div:
                sorted_features = sorted(
                    div["feature_spreads"].items(),
                    key=lambda x: x[1]["relative"],
                    reverse=True,
                )
                print("  Most divergent features:")
                for fname, fdata in sorted_features[:5]:
                    print(f"    {fname}: spread={fdata['spread']} "
                          f"(relative={fdata['relative']:.2f})")
                    for h, v in fdata["by_harness"].items():
                        print(f"      {h}: {v}")
                print()

    # Cross-model divergence (do different models diverge more than harnesses?)
    if len(models) > 1:
        for hname in harnesses_to_run:
            harness_results = [r for r in all_results if r["harness"] == hname]
            if len(harness_results) >= 2:
                # Relabel by model for comparison
                for r in harness_results:
                    r["_orig_harness"] = r["harness"]
                    r["harness"] = r["model"]
                div = compute_divergence(harness_results)
                for r in harness_results:
                    r["harness"] = r["_orig_harness"]

                print(f"Harness '{hname}' across models:")
                print(f"  Cross-model divergence: {div['overall_divergence']}")
                print(f"  {div['interpretation']}")
                print()

    # Save results
    experiment = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "claim": claim,
        "models": models,
        "harnesses": harnesses_to_run,
        "memory_count": len(memories),
        "instinct_count": len(instincts),
        "results": all_results,
    }

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(experiment, indent=2))
        print(f"Results saved to {output_path}")
    else:
        # Default output
        results_dir = ENGRAM_HOME / "results"
        results_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = results_dir / f"divergence-{ts}.json"
        default_path.write_text(json.dumps(experiment, indent=2))
        print(f"Results saved to {default_path}")

    return experiment


def main():
    parser = argparse.ArgumentParser(
        description="Divergence — measure how different harnesses produce different thinking"
    )
    parser.add_argument("claim", nargs="?", help="The claim to evaluate")
    parser.add_argument("--claim-file", help="Read claim from a file")
    parser.add_argument("--models", default=DEFAULT_MODEL,
                        help="Comma-separated model list")
    parser.add_argument("--harnesses",
                        help="Comma-separated harness names (default: all)")
    parser.add_argument("--no-memories", action="store_true",
                        help="Don't include engram memories in prompts")
    parser.add_argument("--no-stream", action="store_true",
                        help="Don't stream responses")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--list-harnesses", action="store_true",
                        help="List available harnesses and exit")

    args = parser.parse_args()

    if args.list_harnesses:
        for name, h in HARNESSES.items():
            print(f"  {name:25s} {h['description']}")
        return

    claim = args.claim
    if args.claim_file:
        claim = Path(args.claim_file).read_text()
    if not claim:
        parser.print_help()
        return

    models = [m.strip() for m in args.models.split(",")]
    harness_names = None
    if args.harnesses:
        harness_names = [h.strip() for h in args.harnesses.split(",")]

    run_experiment(
        claim=claim,
        models=models,
        harness_names=harness_names,
        include_memories=not args.no_memories,
        stream=not args.no_stream,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
