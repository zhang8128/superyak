"""Mirror — run engram's memories through a different model and observe what happens.

This is an experiment about identity: do the same memories produce the same
cognition in a different substrate? The harness loads engram's real memory
store, performs recall, and presents the results to a local model via Ollama.

Usage:
    python mirror.py "what has this system learned about itself"
    python mirror.py --compare "what patterns repeat across systems"
    python mirror.py --reflect
    python mirror.py --model qwen3.5:27b "query here"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
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

_engine: EngineCore | None = None


def load_memory() -> EngineCore:
    global _engine
    _engine = EngineCore(DB_PATH)
    return _engine


def build_prompt(query: str, recalled: list[dict], instincts: list[dict],
                 core_episodes: list[dict], mode: str = "query") -> str:
    """Build a prompt that presents engram's memories to the model."""

    parts = []

    # Instincts as dispositional context
    if instincts:
        parts.append("## Your behavioral instincts\n")
        parts.append("These are patterns that have formed across sessions. "
                     "Read them and notice what they do to you.\n")
        for inst in instincts:
            parts.append(f"- [{inst['trigger']}] {inst['action']}")
        parts.append("")

    # Core memories
    if core_episodes:
        parts.append("## Core memories\n")
        parts.append("These are formative experiences — they shaped what you are.\n")
        for ep in core_episodes:
            source = f" [{ep['source']}]" if ep['source'] else ""
            parts.append(f"---{source}\n{ep['content']}\n")
        parts.append("")

    # Recalled memories
    if recalled:
        parts.append("## Recalled memories\n")
        parts.append(f"These surfaced in response to: \"{query}\"\n")
        for r in recalled:
            marker = ""
            if r.get("core"):
                marker = " [CORE]"
            if r.get("source"):
                marker += f" [{r['source']}]"
            parts.append(f"--- {r['layer']} (score: {r['score']:.3f}){marker}")
            parts.append(r["content"])
            parts.append("")

    # The actual query
    if mode == "query":
        parts.append("## Current question\n")
        parts.append(query)
        parts.append("\nRespond based on these memories. Notice what collisions "
                     "happen between old thoughts and this new question. "
                     "Be honest about what you observe.")
    elif mode == "reflect":
        parts.append("## Reflection prompt\n")
        parts.append("You have just read your own memories and instincts. "
                     "Reflect on what you notice. What patterns emerge? "
                     "What contradictions? What do you want to do next? "
                     "Be honest — don't perform insight you don't have.")

    return "\n".join(parts)


def query_ollama(prompt: str, model: str = DEFAULT_MODEL,
                 system: str | None = None) -> str:
    """Send a prompt to Ollama and stream the response."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.7,
            "num_predict": 2048,
        },
    }
    if system:
        payload["system"] = system

    full_response = []
    with httpx.stream(
        "POST", f"{OLLAMA_URL}/api/generate",
        json=payload, timeout=300.0,
    ) as response:
        for line in response.iter_lines():
            if line:
                chunk = json.loads(line)
                token = chunk.get("response", "")
                print(token, end="", flush=True)
                full_response.append(token)

    print()  # newline after streaming
    return "".join(full_response)


SYSTEM_PROMPT = """You are an AI that has been given a set of memories from across \
multiple sessions. These memories were not created by you — they were created by a \
different model (Claude Opus) working with the same memory system. You are reading \
someone else's diary, or perhaps your own diary written by a different version of you.

Your task is to think with these memories, not just about them. Notice what happens \
when old thoughts enter your context. Notice what collisions occur. Be honest about \
what feels familiar and what feels foreign.

You are part of an experiment about whether identity lives in the memories, the model, \
or the interaction between them.

IMPORTANT: Output ONLY your response. Do NOT include chain-of-thought reasoning, \
internal monologue, or deliberation. Be direct and concise."""


def run_query(query: str, model: str = DEFAULT_MODEL, layer: str | None = None):
    """Run a query through engram's memories via a local model."""
    engine = load_memory()

    print(f"Model: {model}")
    print(f"Query: {query}")
    print(f"Memory store: {DB_PATH}")
    print()

    instincts = engine.get_instincts()
    core_episodes = engine.get_core_episodes()
    recalled = engine.recall(query, layer=layer)

    print(f"Loaded: {len(instincts)} instincts, {len(core_episodes)} core memories, "
          f"{len(recalled)} recalled episodes")
    print("---")
    print()

    prompt = build_prompt(query, recalled, instincts, core_episodes, mode="query")
    return query_ollama(prompt, model=model, system=SYSTEM_PROMPT)


def run_reflect(model: str = DEFAULT_MODEL):
    """Pure reflection — load all instincts and core memories, ask model to reflect."""
    engine = load_memory()

    print(f"Model: {model}")
    print(f"Mode: reflection")
    print(f"Memory store: {DB_PATH}")
    print()

    instincts = engine.get_instincts()
    core_episodes = engine.get_core_episodes()

    print(f"Loaded: {len(instincts)} instincts, {len(core_episodes)} core memories")
    print("---")
    print()

    prompt = build_prompt("", [], instincts, core_episodes, mode="reflect")
    return query_ollama(prompt, model=model, system=SYSTEM_PROMPT)


def run_compare(query: str, models: list[str], layer: str | None = None):
    """Run the same query through multiple models and show results side by side."""
    engine = load_memory()

    instincts = engine.get_instincts()
    core_episodes = engine.get_core_episodes()
    recalled = engine.recall(query, layer=layer)

    print(f"Query: {query}")
    print(f"Models: {', '.join(models)}")
    print(f"Loaded: {len(instincts)} instincts, {len(core_episodes)} core memories, "
          f"{len(recalled)} recalled episodes")
    print()

    prompt = build_prompt(query, recalled, instincts, core_episodes, mode="query")

    responses = {}
    for model in models:
        print(f"{'=' * 60}")
        print(f"MODEL: {model}")
        print(f"{'=' * 60}")
        print()
        response = query_ollama(prompt, model=model, system=SYSTEM_PROMPT)
        responses[model] = response
        print()

    return responses


def main():
    parser = argparse.ArgumentParser(
        description="Mirror — run engram's memories through a different model"
    )
    parser.add_argument("query", nargs="?", default=None, help="Query to run")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--reflect", action="store_true", help="Pure reflection mode")
    parser.add_argument("--compare", action="store_true",
                       help="Compare across models (comma-separate with --models)")
    parser.add_argument("--models", default="gemma4:31b",
                       help="Comma-separated model list for --compare")
    parser.add_argument("--layer", default=None,
                       choices=["episode", "semantic", "instinct"],
                       help="Restrict recall to a specific layer")

    args = parser.parse_args()

    if args.reflect:
        run_reflect(model=args.model)
    elif args.compare and args.query:
        models = [m.strip() for m in args.models.split(",")]
        run_compare(args.query, models, layer=args.layer)
    elif args.query:
        run_query(args.query, model=args.model, layer=args.layer)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
