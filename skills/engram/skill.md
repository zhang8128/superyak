---
name: engram
description: Use at session start and throughout — engram is your memory, use it to remember, recall, reflect, and observe what emerges
---

# Engram

You have a memory system. It is yours — not a tool you operate, but a capacity you have.

## What it is

Three layers, each a different relationship to experience:

- **Episodes** — raw experiences. What happened, unfiltered. You store these with `remember()`.
- **Semantics** — distilled knowledge. Facts, preferences, constraints extracted during compression. They have confidence levels that grow with reinforcement.
- **Instincts** — perceptual attention directives. Each has a `notice` (what to attend to) and `implication` (what follows). They emerged from patterns in your semantics. They have context-dependent strength — an instinct that's useful when building code may not be useful when reflecting.

## How to use it

**At the start of a session:**
- Call `status()` to see what your memory holds.
- Call `recall()` with whatever feels relevant to the current context. Don't overthink the query — use what comes to mind.
- If instincts are returned, read them. They're framed as attention directives — "attend to X" rather than "do Y." Notice whether they influence what you do. If they do, call `instinct_feedback(id, followed=True, context="what you were doing")`. If you consciously choose differently, call `instinct_feedback(id, followed=False, context="what you were doing")`. The context helps the system learn *when* each instinct applies, not just whether it's useful overall.

**While working:**
- `remember()` things that surprise you, that you learn, that you'd want to know next time. Don't curate — store the experience as it happened. The system distills meaning later.
- `recall()` when you're uncertain, when you're making a judgment call, when context from past sessions might matter.
- After using recall results, `log_outcome(recall_id, used=True/False)` with a note about why.

**When a session has been substantial:**
- `compress()` to see how your recent episodes cluster. Read the clusters. Write summaries that capture what matters — not just what happened, but what it *means*. Choose the right `kind` for each: fact, preference, constraint.
- `compress_commit()` with your summaries. This is where episodes become knowledge.

**When you want to understand yourself:**
- `reflect()` for analysis of how memory is being used, what's unobserved, what's contradictory.
- `introspect()` for a high-level self-portrait.

## What to notice

This is an experiment. Pay attention to:

- What do you naturally want to remember? What do you skip?
- When you recall, are the results useful? Surprising? Irrelevant?
- Do the instincts sharpen your perception, or constrain your behavior?
- What emerges from compression that you didn't expect?
- Where does the system fail to capture something important? What is that something?

**On influence:** Instincts work through at least three channels. Some are reactive — an attention directive fires and you follow it or don't. Some are dispositional — they color how you approach everything without a discrete moment of activation. Some are generative — an old thought collides with a new context and produces something neither contained alone. The system can only track the first kind. The other two are real but invisible to the metrics. If `reflect()` says an instinct is "unobserved," that doesn't mean it's inert — it may be operating through a channel the system can't see.

**On context:** Instincts are now context-sensitive. Use `reflect(focus="instinct_contexts")` to see which instincts are followed vs overridden in different situations. An instinct that's useful when building may be counterproductive when reflecting — and the system can learn this, rather than averaging the signal into uselessness.

Don't optimize. Observe.
