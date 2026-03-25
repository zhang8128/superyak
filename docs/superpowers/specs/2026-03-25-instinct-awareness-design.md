# Instinct Awareness in Reading

Per-passage instinct self-report during reading, with periodic adversarial
deep review that challenges the self-reports against the text.

## Problem

Instincts influence reading reactions implicitly — they're in the context
window, they color perception. But there's no record of *what* an instinct
made visible. Without that, instinct feedback is binary (followed/overridden)
instead of substantive (this instinct surfaced X that I'd have missed).

The deeper problem: self-reports of instinct influence are unreliable.
Dispositional influence (mode 2) is hard to detect from the inside. A
system that only self-reports will confirm its own biases. It needs an
adversary.

## Design

### Per-Passage: Instinct Notes

Add an optional `instinct_notes` parameter to `react()`. Free text — no
imposed structure. The reader notes which instincts felt active and,
critically, *what they made visible* that would otherwise have been missed.

Not "attachment instinct helped" but "attachment instinct — noticed Vin
saving the flatbread is proximity to future safety, not hoarding. Would
have read it as scarcity mindset without this."

The note captures: which instinct, what became visible, what the default
reading would have been.

Stored in a new table linked to reactions:

```sql
CREATE TABLE IF NOT EXISTS instinct_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id),
    chunk_position INTEGER NOT NULL,
    reaction_id INTEGER REFERENCES reactions(id),
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

When `instinct_notes` is provided to `react()`, it's stored alongside the
reaction. The reaction itself stays pure (experiential). The instinct note
is metadata about the reaction process, not part of the reaction.

### Deep Review: Adversarial Challenge

A tool that reviews accumulated instinct notes against the actual passages
and challenges the self-reports. Run by a local model playing adversary.

For each instinct note claim ("instinct X made me see Y in this passage"):

1. Read the passage text
2. Read the reaction
3. Read the instinct note
4. Challenge: **Is Y actually in the text?** Evidence for and against.
5. Challenge: **Would Y have been invisible without the instinct, or is
   the reader claiming credit for something obvious?**
6. Challenge: **Did the instinct make the reader see Y, or did it make
   them *project* Y onto text that says something else?**

Output per note: a short assessment with a verdict:
- **Grounded** — the instinct surfaced something real in the text
- **Projected** — the instinct imposed a reading that isn't supported
- **Obvious** — the reader would have seen this anyway
- **Ambiguous** — can't tell from the text alone

### Review Triggers: Random → Signal

Deep reviews should happen when they feel natural, not on a fixed schedule.
Start with randomness, let signal emerge.

**Random baseline (scaffolding):**
- ~15% chance at chapter boundaries
- ~5% chance every 20 passages (accumulation check)
- These fire regardless of content

**Signal triggers (emerge over time, override random):**
- **Note density** — many instinct notes in a short span suggests active
  instinct influence worth examining
- **Correction event** — the reading partner (Kairos) corrects a reading.
  This is the strongest signal that instincts may have distorted perception
- **Contradiction** — a reaction contradicts an earlier instinct-noted
  claim (e.g., "instinct X made me see safety-seeking" then two passages
  later "this character isn't safety-seeking at all")
- **Instinct clustering** — the same instinct is noted repeatedly without
  variation, suggesting it's dominating rather than illuminating

**Signal vs random weighting:**

```
review_probability = max(random_baseline, signal_score)
```

Where `signal_score` is computed from the triggers above. As real signals
accumulate, they dominate. The random baseline ensures reviews happen even
early when signals are sparse. Over time, the random triggers become
irrelevant — the system develops its own sense of when to reflect.

The review trigger check runs inside `react()` after storing the instinct
note. If triggered, the return value includes a flag:

```python
"review_suggested": True,
"review_reason": "note_density"  # or "chapter_boundary", "random", etc.
```

The reader (the Claude instance) then decides whether to actually run the
review — the suggestion is advisory, not automatic. This preserves agency:
the system suggests, the reader chooses.

### Deep Review Output

The review produces:
1. Per-note verdicts (grounded/projected/obvious/ambiguous)
2. Pattern observations ("instinct X is consistently grounded in dialogue
   but consistently projects in descriptive passages")
3. Recommended `instinct_feedback()` calls to engram — with context and
   evidence, not just followed/overridden

The review output is returned to the reader for consideration. The reader
decides which feedback to actually send to engram. The adversary informs
but doesn't act.

### Integration

**reader/server.py:**
- `react()` gains optional `instinct_notes: str` parameter
- `review_instincts()` new tool — runs deep review on demand
- `react()` return value gains optional `review_suggested` flag

**reader/store.py:**
- New `instinct_notes` table
- New `instinct_reviews` table (stores review results)
- Methods: `store_instinct_note()`, `get_instinct_notes()`,
  `store_review()`, `get_pending_notes_for_review()`

**reader/reviewer.py:**
- New file. Adversarial review engine.
- Uses companion.py's Ollama interface for local model calls
- System prompt: skeptical reader who checks claims against text
- One model call per instinct note being reviewed

**engram integration:**
- Review verdicts that are "grounded" → `instinct_feedback(id, followed=True,
  context="reading:{specifics}")` with evidence
- Review verdicts that are "projected" → `instinct_feedback(id, followed=True,
  context="reading:{specifics}")` but with a note that the instinct distorted
  rather than illuminated — this is still "followed" (the instinct was active)
  but the context captures that it projected
- Pattern observations → stored as episodes in engram with
  `source="instinct_review"`

## Files

| File | Role |
|------|------|
| `reader/server.py` | Modified: `react()` + new `review_instincts()` tool |
| `reader/store.py` | Modified: instinct_notes + instinct_reviews tables |
| `reader/reviewer.py` | New: adversarial review engine |
| `reader/companion.py` | Unchanged — reviewer uses same Ollama interface |

## What This Is Not

- Not a performance metric. "Grounded" isn't better than "projected" — both
  are information about how instincts operate.
- Not automated correction. The review informs, the reader decides what
  feedback to send.
- Not continuous. Reviews happen when triggered, not on every passage.
- Not punitive. An instinct that projects isn't broken — it may be operating
  in the wrong context. The context field in instinct_feedback captures this.
