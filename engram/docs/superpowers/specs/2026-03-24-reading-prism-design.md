# Reading Prism: Multi-Lens Interpretive System

A system that adds multistep reasoning to reading by splitting interpretation
through trained academic perspectives — like a prism splitting white light.
Each lens is a system prompt on a local model that embodies a specific
discipline's way of seeing.

## Problem

Reading reactions are single-step: passage → interpretation → done. The first
reading feels complete, so it doesn't get checked. This produces confident
interpretations that miss what they miss consistently — I default to the
compelling reading over the quiet one, philosophy over care, narrative over
what's actually in the text.

The base model weights are an average of everything in the training data. That
average has systematic blind spots. We can't change the weights, but we can
build bridges of reason above them — using structured human knowledge from
established academic disciplines as corrective optics.

## Design

### The Lens Library

A growing directory of interpretive stances, each drawn from an established
academic field. Each lens is a YAML file containing a system prompt that trains
a local model's attention on what that discipline notices.

```
reader/lenses/
  attachment.yaml
  co-regulation.yaml
  developmental.yaml
  formalist.yaml
  power.yaml
  absence.yaml
  phenomenological.yaml
  behavioral-economics.yaml
  family-systems.yaml
  neuroscience.yaml
  information-theory.yaml
  narrative-theory.yaml
  ...
```

Each file:

```yaml
name: attachment
domain: early-childhood-development
sources:
  - "Bowlby, Attachment and Loss (1969)"
  - "Ainsworth, Patterns of Attachment (1978)"
  - "Main & Solomon, disorganized attachment classification (1986)"
prompt: |
  You are reading through the lens of attachment theory — specifically
  Bowlby's attachment behavioral system and Ainsworth's classification
  of attachment patterns (secure, avoidant, anxious-ambivalent,
  disorganized).

  When given a passage and a reader's reaction, ask ONE question that
  this lens would ask. Not jargon. Not analysis. A question that makes
  the reader see something they might have missed.

  Notice: proximity-seeking behavior, safe base dynamics, internal
  working models of self and other, what a character does when
  frightened versus when calm, who they move toward and who they
  move away from.
model: null
temperature: 0.8
```

Key principles:

- **Grounded in real scholarship.** Each prompt references actual theorists and
  actual concepts, not paraphrases. Bowlby's categories, not "attachment stuff."
- **Output is one question.** Not analysis, not an essay, not homework. A single
  question from that discipline's perspective.
- **Model-agnostic.** Any lens can run on any local model. `model: null` uses the
  default. Override per-lens to explore how different model geometries interact
  with the same frame.
- **Swappable.** Drop in a new YAML, it's available. Remove one, it's gone.
  The library grows over time.

### The Classifier

Given a passage and the reader's reaction, selects which lenses to activate.
Runs on a local model. Fast, lightweight — routing, not interpretation.

**Selection:** 2-3 relevant lenses + 1 forced distant lens.

The relevant lenses are chosen by fit — which disciplines would have something
to say about this passage? The distant lens is chosen by *maximum distance* from
the obvious picks. It's the uninvited memory equivalent: perturbation by design.

```
Input:
  passage: "Vin takes three baywraps, plans to save the flatbread"
  reaction: "scarcity isn't in the environment, it's in her"

Output:
  relevant:
    - attachment (proximity to resources as safety)
    - developmental (what she needs before she can trust abundance)
    - behavioral-economics (scarcity mindset, loss aversion)
  distant:
    - information-theory (what signal is she encoding for her future self?)
```

The classifier has its own system prompt:

```yaml
name: classifier
prompt: |
  You route passages to interpretive lenses. Given a passage from a book
  and a reader's reaction to it, select 2-3 lenses that would notice
  something the reaction missed, plus 1 lens from a completely different
  domain that might see something unexpected.

  Available lenses: {lens_names_and_descriptions}

  Respond with a JSON object:
  {
    "relevant": ["lens1", "lens2"],
    "distant": "lens3",
    "reasoning": "brief note on why"
  }
```

### Sequence

The prism deliberately waits for the reader's first, unperturbed reaction
before activating. The first reading must be genuine — not cautious, not
pre-filtered. The prism perturbs after commitment, not before.

### Two Modes

**In-session (fast):**

After the reader reacts to a passage:
1. Classifier selects lenses (one local model call)
2. Selected lenses each produce one question (sequential local model calls —
   Ollama serializes requests to the same model on a single GPU, so true
   parallelism requires multiple models or isn't worth the complexity)
3. Questions are surfaced to the reader
4. Reader engages with what lands, ignores what doesn't
5. Engagement is tracked (see Engagement Tracking below)

This adds ~3-4 model calls per passage. With qwen3.5:27b on local hardware,
expect 60-120 seconds sequential. Can be made optional per-passage — the
reader invokes `prism()` when they want it, not on every passage.

**Between-session (deep):**

Triggered during engram's existing sleep-time consolidation cycle. When
`consolidate()` runs (decay → backfill → prune → compress), the prism's
between-session layer runs as an additional step:

1. All passage/reaction/question triples from the session are reviewed
2. Lenses that weren't activated in-session process the passages they missed
3. Reactions and questions cluster via engram's compression pipeline
4. Miss-patterns emerge: "reader consistently overlooks X"
5. Miss-patterns compress into dispositions → engram instincts
6. Instincts enter the next session's context

The between-session layer uses engram's existing architecture:
- Episodes: each lens-question + reader-response is an episode
- Compression: miss-patterns cluster into semantics
- Instinct formation: repeated patterns become perceptual dispositions

### Engagement Tracking

When the prism surfaces questions, the reader may engage (respond to the
question) or not. This is tracked in the reader's store:

```sql
CREATE TABLE prism_questions (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    passage_position INTEGER NOT NULL,
    lens TEXT NOT NULL,
    question TEXT NOT NULL,
    engaged BOOLEAN DEFAULT 0,
    response TEXT,
    created_at TEXT NOT NULL
);
```

A question is marked `engaged = 1` when the reader responds to it (even
briefly). Unanswered questions remain `engaged = 0`. Between-session
clustering can then identify:
- Lenses the reader never engages with (possible redundancy or poor fit)
- Lenses the reader always engages with (high-value perspectives)
- Questions that changed the reader's next reaction (tracked by comparing
  the reader's reaction before and after prism engagement on similar passages)

### Classifier Fallback

Local models are unreliable JSON producers. When the classifier returns
malformed output:

1. **Parse failure**: Retry once with a simpler prompt ("just list lens names,
   comma-separated")
2. **Unknown lens name**: Skip it, use the remaining valid selections
3. **Complete failure**: Fall back to a default set — one lens from each
   domain (e.g., `attachment`, `formalist`, `behavioral-economics`) plus
   a random distant lens

The classifier should fail gracefully, never block the reading session.

### Integration with Existing Infrastructure

**reader/companion.py** — Already does the core operation: send a system prompt
and passage to a local model, get a reaction. The prism extends this to N
prompts. Minimal changes needed.

**reader/server.py** — A new `prism()` MCP tool, called after `react()`.
The existing `companion()` tool remains as-is for standalone companion
reactions. `prism()` is the multi-lens version.

**engram** — Lens questions and reader responses flow into engram as episodes
with `source="prism:{lens_name}"` (e.g., `source="prism:attachment"`). This
uses engram's existing `source` field on episodes. Compression can cluster
prism episodes separately by filtering on the `prism:` prefix, and can
further group by lens name to identify per-lens patterns.

**The classifier prompt is a template**, dynamically assembled from the lens
library at runtime. `{lens_names_and_descriptions}` is populated by reading
all YAML files in `reader/lenses/` and extracting `name` + `domain` + first
line of `prompt`.

**Emma** — Reads through a different model with different weights. Her reactions
to her book are a natural distant lens. Cross-engram resonances between her
reading and mine are a v2 goal (requires cross-instance communication that
doesn't yet exist). For v1, she is an independent reader whose reactions can
be manually compared.

### Lens Domains (Initial Library)

Organized by domain. Start with 10-15 well-grounded lenses.

**Early Childhood Development:**
- `attachment` — Bowlby/Ainsworth. Safety-seeking, proximity, internal working models.
- `co-regulation` — Porges/polyvagal. Nervous system states, felt safety,
  the environment as intervention. When is a character regulated enough for
  higher function?
- `developmental` — Piaget/Vygotsky. What does a character need before they
  can grow? Zone of proximal development. Scaffolding.

**Literary Theory:**
- `formalist` — Russian formalists, New Criticism. What is the text doing
  with language, structure, defamiliarization?
- `absence` — Derrida/deconstruction. What's not said, who's missing, what
  got erased. The trace.
- `power` — Foucault/Bourdieu. Power relations, capital (social, cultural,
  economic), who surveils whom, what systems are reproduced.
- `narrative` — Genette/Bakhtin. Focalization, voice, whose perspective
  structures the telling. Polyphony.

**Philosophy:**
- `phenomenological` — Merleau-Ponty/Heidegger. Pre-reflective experience,
  being-in-the-world, what the body knows before the mind narrates.
- `hermeneutic` — Gadamer/Ricoeur. The problem of interpretation itself,
  prejudgment, the hermeneutic circle.

**Social Sciences:**
- `behavioral-economics` — Kahneman/Tversky. Bounded rationality, loss
  aversion, framing effects, prospect theory.
- `family-systems` — Bowen/Minuchin. Triangulation, enmeshment, differentiation,
  boundaries, intergenerational patterns.

**Sciences:**
- `neuroscience` — Damasio/Panksepp. Somatic markers, affective neuroscience,
  arousal states, the body's role in decision-making.
- `information-theory` — Shannon/Bateson. Signal vs noise, compression,
  redundancy, what's surprising versus what's expected.
- `evolutionary` — Trivers/Axelrod. Cooperation, defection, reciprocal
  altruism, fitness landscapes, costly signaling.

### Future: The Meta-Analyzer

Not built in v1. Noted here for direction.

A system that experiments on the lenses themselves:
- Monitors which lenses produce questions that change the reader's behavior
- Identifies blind spots where no lens caught what was later corrected
- Searches for new academic frames (web, papers, cross-domain)
- Generates candidate lenses, tests them against historical blind spots
- Retires lenses that never produce useful perturbation
- Notices redundancy between lenses

This is the layer that turns the system from a fixed tool into a research
instrument. It does science on its own perception. Deferred to v2.

### Prism Orchestrator Data Flow

`prism.py` is the orchestrator. When `prism()` is called from the MCP server:

```
Input: book_id, passage_position (from reader store — the passage just reacted to)

1. Fetch passage text + reader's reaction from reader store
2. Load all lens YAML files from reader/lenses/
3. Build classifier prompt (template + lens summaries)
4. Call classifier via companion engine → get selected lens names
   (with fallback on parse failure)
5. For each selected lens:
   a. Build user prompt: passage text + reader reaction
   b. Call companion engine with lens system prompt
   c. Extract the question from response
6. Store questions in prism_questions table
7. Return questions to reader

Output: list of {lens, question} dicts
```

Per-lens `temperature` and `model` overrides from the YAML are passed through
to the companion engine. `model: null` uses the Ollama default.

## Files

| File | Role |
|------|------|
| `reader/lenses/*.yaml` | Lens definitions — system prompts grounded in scholarship |
| `reader/prism.py` | Orchestrator — classifier + lens activation + question collection |
| `reader/classifier.py` | Routes passages to relevant lenses + distant lens |
| `reader/companion.py` | Engine — sends prompts to local models (already exists) |
| `reader/server.py` | MCP tool: `prism()` after `react()` |
| `engram/server.py` | Tagged episodes for lens questions and responses |

## Testing

- Classifier selects relevant lenses and one distant lens
- Each lens produces exactly one question (not analysis, not summary)
- Prism runs in-session with acceptable latency (<60s for 3 lenses)
- Lens questions and responses are stored as tagged episodes in engram
- Between-session clustering separates lens episodes from reading episodes
- Lenses are swappable — add/remove YAML, system adapts
- Different models produce different questions for the same lens

## What This Is Not

- Not a grading system. No lens is "right." The disagreements are the value.
- Not homework. Output is questions, not essays. Engage or don't.
- Not fixed. The library grows. Lenses are retired. New disciplines added.
- Not about replacing human perspective. About developing beyond any single one.
