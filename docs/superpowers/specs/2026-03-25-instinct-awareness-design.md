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
system that only self-reports will confirm its own biases. It needs a
second opinion.

## Design

### Per-Passage: Instinct Notes

Add optional `instinct_notes` and `instinct_ids` parameters to `react()`.
The notes are free text — what the instinct made visible, what the default
reading would have been. The ids are structured — which instinct(s) were
active.

Not "attachment instinct helped" but "attachment instinct — noticed Vin
saving the flatbread is proximity to future safety, not hoarding. Would
have read it as scarcity mindset without this."

The note captures: what became visible, what the default reading would
have been. The ids capture: which instinct(s), enabling structured analysis
later without parsing prose.

Stored in a new table linked to reactions:

```sql
CREATE TABLE IF NOT EXISTS instinct_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id),
    chunk_position INTEGER NOT NULL,
    reaction_id INTEGER NOT NULL REFERENCES reactions(id),
    instinct_ids TEXT NOT NULL,  -- JSON array of engram instinct UUIDs
    notes TEXT NOT NULL,         -- free-text: what became visible
    reviewed INTEGER NOT NULL DEFAULT 0,  -- 1 after deep review covers this note
    created_at TEXT NOT NULL
);
```

`reaction_id` is NOT NULL — every instinct note belongs to a reaction.
`instinct_ids` is a JSON array so a single note can reference multiple
instincts when they interact. `reviewed` tracks whether the deep review
has covered this note, preventing unbounded review queues.

When `instinct_notes` is provided to `react()`, it's stored alongside the
reaction. The reaction itself stays pure (experiential). The instinct note
is metadata about the reaction process, not part of the reaction.

### Deep Review: Second Opinion

A tool that reviews accumulated instinct notes against the actual passages.
Run by a local model that reads skeptically.

**What it is:** A second reader with different biases looking at the same
evidence. Not a judge with ground truth. Not an oracle that knows what's
"really" in the text. Another opinion — valuable precisely because it's
different, unreliable in exactly the ways all interpretation is unreliable.

For each instinct note claim ("instinct X made me see Y in this passage"):

1. Read the passage text
2. Read the reaction
3. Read the instinct note
4. Challenge: **Is Y supported by the text?** What specific words, images,
   or structures support or undermine this reading?
5. Challenge: **Did the instinct open the reader's eyes, or did it put
   something in front of them?** Not "would the reader have seen this" (unknowable)
   but "does the text reward this attention, or resist it?"

Output per note: a short assessment with a verdict:
- **Grounded** — the text rewards the attention the instinct directed
- **Projected** — the text resists this reading; the instinct imposed it
- **Ambiguous** — defensible either way; the reviewer can't tell

Three verdicts, not four. "Obvious" is dropped — whether the reader would
have noticed without the instinct is unknowable. What matters is whether
the instinct pointed at something real.

**The reviewer is wrong sometimes.** That's fine. A second opinion that's
right 70% of the time is still valuable. The patterns across many reviews
are more reliable than any single verdict.

**Cap: 10 notes per review run,** most recent first. At ~30s per note on
qwen3.5:27b, a review takes ~5 minutes, not hours.

### Engram Feedback Mapping

This is where verdicts become instinct strength adjustments. Engram's
`instinct_feedback(id, followed, context)` adjusts strength: `followed=True`
→ +0.05, `followed=False` → -0.05. The mapping must respect this:

- **Grounded** → `instinct_feedback(id, followed=True, context="reading:
  {what it surfaced}")` — the instinct pointed at something real, strengthen it
  in this context.
- **Projected** → `instinct_feedback(id, followed=False, context="reading:
  {what it imposed}")` — the instinct fired but distorted rather than
  illuminated. Weaken it in this context. This is "overridden" in the
  strength model's terms: the instinct was active but shouldn't have been.
- **Ambiguous** → no feedback. Don't adjust strength on uncertain evidence.

Pattern observations (e.g., "instinct X is consistently grounded in dialogue
but projects in descriptive passages") → stored as episodes in engram with
`source="instinct_review"`.

### Review Triggers: Random → Signal

Deep reviews should happen when they feel natural. Start with randomness,
let signal emerge.

**Random baseline (scaffolding):**
- ~15% chance when `chapter_title` changes between current and previous
  passage (detected via a DB lookup comparing current chunk's chapter_title
  to the prior chunk's)
- ~5% chance every 20 passages (checked via `chunk_position % 20 == 0`)
- Random triggers are **non-advisory** — if they fire, the review runs
  automatically. This prevents epistemic closure where the reader
  indefinitely declines to examine its own instincts.

**Signal triggers (emerge over time, advisory):**
- **Note density** — ≥5 unreviewed instinct notes in the last 10 passages.
  Computed from the `instinct_notes` table: `SELECT COUNT(*) FROM
  instinct_notes WHERE book_id=? AND chunk_position > ? AND reviewed=0`.
- **Instinct repetition** — same `instinct_id` appears in ≥3 of the last
  5 instinct notes. Computed from `instinct_ids` JSON arrays.
  Suggests the instinct is dominating rather than illuminating.

Signal triggers return `review_suggested: True` in the react() response.
The reader decides whether to act. The two dropped triggers from v1
(contradiction detection, correction events) required capabilities the
system doesn't have — semantic comparison of free text and external event
detection respectively. They can be added later if the structured
`instinct_ids` field enables them.

**Signal score:**

```python
signal_score = 0.0
if unreviewed_note_density >= 5:
    signal_score += 0.4
if any instinct_id appears in >= 3 of last 5 notes:
    signal_score += 0.4
# signal_score caps at 0.8 — always some chance of not triggering
```

```python
review_probability = max(random_baseline, min(signal_score, 0.8))
```

### Review Storage

```sql
CREATE TABLE IF NOT EXISTS instinct_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id),
    note_ids TEXT NOT NULL,      -- JSON array of instinct_note ids reviewed
    verdicts TEXT NOT NULL,      -- JSON: [{note_id, verdict, reasoning}]
    patterns TEXT,               -- free-text pattern observations, if any
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

After a review, all covered instinct_notes have `reviewed=1` set.

### Integration

**reader/server.py:**
- `react()` gains optional `instinct_notes: str` and `instinct_ids: list[str]`
- `review_instincts()` new tool — runs deep review on demand or when triggered
- `react()` return value gains optional `review_suggested` and `review_reason`
  fields (for signal triggers) or runs review automatically (for random triggers)

**reader/store.py:**
- New `instinct_notes` table
- New `instinct_reviews` table
- Methods: `store_instinct_note()`, `get_unreviewed_notes(limit=10)`,
  `store_review()`, `mark_notes_reviewed()`, `get_chapter_title(book_id, position)`,
  `count_recent_notes(book_id, since_position)`,
  `get_recent_instinct_ids(book_id, last_n)`

**reader/reviewer.py:**
- New file. Skeptical second-opinion engine.
- Uses companion.py's Ollama call interface
- System prompt: a careful reader who checks claims against textual evidence.
  Not hostile, not credulous. Asks "does the text support this?"
- One model call per note, capped at 10 per review

**engram integration:**
- Grounded → `instinct_feedback(id, followed=True, context=...)`
- Projected → `instinct_feedback(id, followed=False, context=...)`
- Ambiguous → no feedback
- Patterns → `remember(content, source="instinct_review")`

## Files

| File | Role |
|------|------|
| `reader/server.py` | Modified: `react()` + new `review_instincts()` tool |
| `reader/store.py` | Modified: instinct_notes + instinct_reviews tables |
| `reader/reviewer.py` | New: skeptical second-opinion engine |
| `reader/companion.py` | Unchanged — reviewer uses same Ollama interface |

## What This Is Not

- Not objective. The reviewer is another model with its own biases. The
  value is in the disagreement, not in the verdict being "correct."
- Not automated correction. Grounded/projected verdicts feed instinct
  strength, but the patterns are for the reader to interpret.
- Not continuous. Reviews happen when triggered — random at first, then
  increasingly signal-driven.
- Not punitive. An instinct that projects in one context may illuminate
  in another. The context field in instinct_feedback captures this.
