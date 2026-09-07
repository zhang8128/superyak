# Emma Prism Integration — Design Spec

**Date:** 2026-03-28
**Status:** Approved

## Summary

Add the reading prism to Emma's life loop. Every 4th passage, the prism fires:
classifier selects 4 lenses (2 relevant + 1 distant + 1 rotating), each produces
a question, Emma sees all 4 and responds to whichever provoke her. Engaged
responses become engram episodes and dream captures. A transition graph learns
which lens sequences emerge from her reading.

## Decisions

- **Inline prism** — fires after reaction, same turn (not delayed to next passage)
- **Sampled every 4 passages** — preserves reading rhythm
- **Model-selected engagement** — Emma picks which questions land, ignores the rest
- **Mount prism read-only** — same pattern as engram/reader mounts

## Data Flow

```
read_passage() [every passage]:
  passage → model reaction → store episode → dream capture → advance

read_passage() [every 4th passage, additionally]:
  passage + reaction → prism classifier → 4 lenses
  → 4 questions presented to Emma in single prompt
  → Emma responds to what provokes, ignores what doesn't
  → engaged responses stored as episodes (source="prism:{lens}")
  → engaged responses forwarded as dream captures
  → transition graph updated with engaged lens sequence
```

## Files

| File | Change |
|------|--------|
| `emma/docker-compose.yml` | Mount prism scripts + reading lens pack |
| `emma/life.py` | New `run_prism()` function |
| `emma/daemon.py` | Track passage count, call prism every 4th |
| `emma/emma_prism.py` | **New.** Thin wrapper: load lenses, classify, ask, manage transitions |

## `emma_prism.py`

Thin wrapper following the pattern of `emma_engram.py` and `emma_reader.py`.

```python
class EmmaPrism:
    def __init__(self, transitions_db: str, lenses_dir: str):
        # Import from /opt/prism (mounted read-only)
        # Load reading lenses from /opt/prism-lenses/reading/
        # Initialize TransitionGraph at transitions_db

    def run(self, passage: str, reaction: str, book: str, chapter: str) -> list[dict]:
        # Build context dict: {"type": "reading", "passage", "reaction", "book", "chapter"}
        # classify_reading(context, lenses, transition_context, graph, last_frame, fired_history)
        # ask_lens() for each selected lens
        # Return [{lens, question, selection_type}, ...]

    def record_engagement(self, engaged_lenses: list[str]):
        # Record consecutive pairs in transition graph
        # Update last_frame and fired_history
```

Imports: `prism.classify_reading`, `prism.ask_lens`, `prism.load_lenses`,
`transitions.TransitionGraph`. All from `/opt/prism`.

Lenses loaded from `/opt/prism-lenses/reading/` via `resolve_frames()` or
direct YAML loading from the pack directory.

Transition graph stored at `/sandbox/emma/reading-transitions.db` — persistent
volume, Emma-specific, separate from the coding prism's host-side graph.

State tracked across the daytime phase (not persisted between cycles):
- `last_frame`: last engaged lens name (for transition context)
- `fired_history`: ordered list of all fired lenses this cycle (for rotating slot)

## `life.py` — `run_prism()`

New function:

```python
def run_prism(engram, prism, passage_info, reaction, morning_context) -> dict:
    # 1. prism.run(passage, reaction, book, chapter) → questions
    # 2. Build prompt: present all questions, ask Emma to respond to what provokes
    # 3. Parse: match lens names in response to identify engagement
    # 4. For each engaged lens:
    #    - engram.remember(content, source=f"prism:{lens}")
    #    - engram.dream_capture(response_fragment)
    # 5. prism.record_engagement(engaged_lenses)
    # 6. Return {questions, engaged, response}
```

The prompt to Emma:

```
You just read a passage and reacted. Now, some perspectives noticed things
you might have missed:

[attachment] Who does Vin move toward when she's afraid?
[formalist] What is the repeated word doing to the rhythm of this paragraph?
[behavioral-economics] What is Kelsier framing as a loss vs a gain here?
[neuroscience] Where in this scene does a character's body know before their mind?

Respond to any that provoke something in you. Name the lens when you respond.
Skip any that don't land. You don't have to respond to all of them.
```

Engagement parsing: scan response for lens names (bracketed `[attachment]` or
plain mentions). Any lens mentioned in the response counts as engaged.

## `daemon.py` changes

In `run_daytime()`:
- Initialize `EmmaPrism` with transitions DB and lenses directory
- After `read_passage()`, if `passages_read % 4 == 0` and `passages_read > 0`:
  call `run_prism()`
- Log which lenses fired and which Emma engaged with

The prism is optional — if imports fail (prism not mounted) or Ollama is
unavailable, skip silently. Emma's reading loop is never blocked by prism.

## Docker mount additions

```yaml
volumes:
  # existing
  - emma-data:/sandbox/emma
  - ${HOME}/.engram/shared:/sandbox/shared
  - ../engram:/opt/engram:ro
  - ../reader:/opt/reader:ro
  # new
  - ../prism/scripts:/opt/prism:ro
  - ${HOME}/.prism/packs/reading:/opt/prism-lenses/reading:ro
```

Environment addition:
```yaml
environment:
  PRISM_PATH: /opt/prism
  PRISM_LENSES: /opt/prism-lenses/reading
```

## Scope Boundaries

**We build:**
- `emma_prism.py` wrapper
- `run_prism()` in life.py
- Prism call in daemon.py daytime loop
- Docker mount config

**We don't build:**
- No reader schema changes (no `prism_questions` table)
- No between-session deep pass
- No lens evolution or retirement
- No changes to prism itself (API already supports reading)
- No changes to engram
- No prism during morning/evening/night phases
