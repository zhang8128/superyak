# arc-see: Perceptual Lens System for ARC-AGI-3

**Date:** 2026-03-26
**Status:** Design
**Repo:** ~/Projects/arc-see

## Thesis

The bottleneck in ARC-AGI-3 isn't reasoning — it's perception. Humans look at
a 64x64 grid and immediately see objects, boundaries, movement, goals. Models
see 4,096 numbers. If we can make the agent *see*, action selection becomes
tractable.

## Approach

Combinatorial lens composition with a memory graph. No RL, no trained models
in v1. Classical CV primitives compose into perceptual frames. An in-game
memory graph records what the agent perceived, what it did, and what happened.
The graph replaces a learned policy.

## ARC-AGI-3 Environment

- 64x64 grid, 16 colors
- 7 actions: ACTION1-5 (simple), ACTION6 (click with x,y coordinates 0-63), ACTION7 (undo)
- Turn-based: observe state → submit action → observe result
- No instructions, no stated goals
- Hundreds of games, 8-10 levels per game, new mechanics per level
- Scoring: RHAE = (human_actions / ai_actions), per-level, averaged per-game
- Full game history available (grids are 4KB each, memory is not a constraint)

## Core Loop

```
observe(grid) → perceive(lenses) → score(combinations) → consult(graph) → act → record → observe...
```

1. **Observe** — receive raw 64x64 grid from API
2. **Perceive** — run all 12 primitive lenses, score pairwise combinations by entropy reduction, surface top-5
3. **Consult** — query memory graph: "from states perceived like this, what happened when I took action X?"
4. **Act** — graph has suggestion → follow it. No suggestion (cold start) → explore guided by most informative lens combination
5. **Record** — add (perceived_state, action, perceived_next_state, lens_scores) to memory graph

Early turns are exploration (lens-guided). As the graph fills, it shifts to
exploitation (graph-guided). No explicit switch — graph confidence naturally
takes over.

## Lens System

### Primitives

13 lenses, each a pure function. Spatial, structural, and relational lenses
take one grid. Temporal lenses take two or more grids (full history available).

**Spatial** — what's on the grid?
| Lens | Input | Output |
|------|-------|--------|
| `connected_components` | grid | labeled region array (same shape, integer labels) |
| `edges` | grid | binary edge mask |
| `enclosure` | grid | nested containment tree (what's inside what) |

**Temporal** — what changed?
| Lens | Input | Output |
|------|-------|--------|
| `movement` | grid history | displacement vectors per object |
| `creation_destruction` | grid pair | appeared/disappeared masks |
| `state_change` | grid pair | same-position color-change mask |

**Structural** — what patterns exist?
| Lens | Input | Output |
|------|-------|--------|
| `symmetry` | grid | detected axes (reflective, rotational) |
| `periodicity` | grid | repeating pattern periods and offsets |
| `alignment` | grid | grid-like arrangements, row/column structure |

**Relational** — how do things relate?
| Lens | Input | Output |
|------|-------|--------|
| `proximity` | objects (from spatial) | distance graph between objects |
| `color_correspondence` | grid + objects | color-to-role mapping |
| `size_count` | objects | object sizes and group counts |

**Goal** — where are we going?
| Lens | Input | Output |
|------|-------|--------|
| `goal_detection` | grid | candidate goal pattern (isolated corner/edge shapes) + similarity score to current state |

### Dependencies

- Relational lenses depend on spatial lens output (need objects to relate)
- Temporal lenses need frame history (all frames kept, full trajectory)
- Goal lens runs independently on raw grid

### Combination Scoring

Entropy reduction measures how much a joint annotation reduces uncertainty
about the grid versus either annotation alone.

Example: connected_components finds 5 objects. color_correspondence finds 3
color groups. Combined: each color group maps 1:1 to an object cluster. High
mutual information → high combination score.

**Procedure:**
1. Run all 13 primitives every turn (cheap CV operations)
2. Score all 78 pairwise combinations by entropy reduction
3. Surface top-5 pairs
4. Generate triples only from top-5 pairs, only if pairwise entropy reduction exceeds threshold
5. Top-K combinations (default K=5) passed to graph consultation and action selection

## Memory Graph

Stores the agent's experience within a single game. Does not reset between
levels — accumulates across the full game.

### Nodes

Perceived states — not raw grids, but the top-K lens annotations for that
frame, vectorized. Two grids that look different in pixels but identical
through the lenses map to the same (or nearby) node.

### Edges

Actions taken. Each edge records:
- Action type (ACTION1-7, with coordinates for ACTION6)
- Active lens combinations (what the agent was "seeing" when it chose)
- Outcome: did the state change? How much? New state or revisit?
- Goal delta: did similarity to detected goal increase or decrease?

### Queries

By perception similarity: "I'm seeing X through lenses L — what happened
from similar perceptions before?"

Ranking:
1. Goal progress (prefer actions that increased goal similarity)
2. Novelty of outcome (prefer actions that led to new states)
3. Recency (recent experience weighted higher within a level)

### State Identity

Two perceived states are "the same" when their annotation vectors are within
a similarity threshold. Annotations are vectorized for fast similarity lookup.

## Action Selection

Three modes, blended by graph confidence:

### Exploration (cold start)

No graph data yet. Lens system drives action selection:
- Cycle ACTION1-5 first (one per turn, observe which cause frame changes)
- Focus ACTION6 clicks on structure — object boundaries, color transitions,
  enclosed regions (from lens output)
- Use ACTION7 (undo) aggressively: do → observe → undo = learn a transition
  for 2 actions with no risk

### Exploitation (graph has data)

Graph query returns ranked candidate actions. Follow top candidate. If
surprising result — record it, re-score lens combinations (surprise may
reveal a new useful combination).

### Goal-directed (goal detected)

When the goal lens detects a candidate target pattern:
- Action selection gains a gradient: prefer actions that increase similarity
  to detected goal
- Exploration still needed for mechanics, but exploitation has a direction

### Blend

`confidence = graph_matches_for_current_perception / threshold`

Low confidence → explore. High confidence → exploit. Goal signal modulates
both — even exploration is biased toward the goal when one is detected.

Goal detection is an optional lens, not a hard assumption. Games without a
visible goal indicator fall back to novelty-driven exploration.

## Project Structure

```
arc-see/
├── lenses/
│   ├── __init__.py
│   ├── base.py             # Lens protocol, Annotation types
│   ├── spatial.py          # connected_components, edges, enclosure
│   ├── temporal.py         # movement, creation_destruction, state_change
│   ├── structural.py       # symmetry, periodicity, alignment
│   ├── relational.py       # proximity, color_correspondence, size_count
│   └── goal.py             # goal pattern detection + similarity
├── composer.py             # combination scoring, entropy reduction, top-K
├── graph.py                # memory graph — nodes, edges, queries
├── agent.py                # core loop: observe → perceive → consult → act
├── runner.py               # ARC-AGI-3 API integration, game management
├── config.py               # environment config, API keys, thresholds
├── tests/
│   ├── test_lenses.py
│   ├── test_composer.py
│   ├── test_graph.py
│   └── test_agent.py
├── pyproject.toml
└── README.md
```

## V1 Goal

Make it see. Run on a few games, observe what the lens combinations reveal,
watch how the memory graph fills, see whether combinatorial perception
surfaces game mechanics. Score is secondary to understanding.

## What We're Not Building Yet

- No trained models (CNN, RL). All perception is classical CV.
- No cross-game transfer. Each game starts fresh.
- No LLM in the loop. Pure computation.
- No optimization for RHAE score. Observe first.

These are all future directions if the perception thesis holds.

## Connection to Engram

The memory graph is engram's core loop compressed into a single game:
- Episodes → state-action-state transitions
- Compression → state identity via lens annotations (many raw states → one perceived state)
- Instincts → lens combinations that reliably predict state changes

Cross-game transfer (future) would be literal engram: accumulate which lens
combinations were informative across games, promote patterns to persistent
attention directives. But that's v2.
