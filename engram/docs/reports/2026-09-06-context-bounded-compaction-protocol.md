# Whole-entry compaction follow-up

The [deadline-only follow-up](2026-09-06-context-compaction-followup-protocol.md)
completed the formerly timed-out request in 140.87 seconds. Its next call
produced valid JSON with available source IDs, but its canonical summary was
6,024 bytes against the 6,000-byte cap. The rejected response and all 100
unavailable preparation outcomes remain part of that separate experiment.

This new profile makes the summary cap a deterministic admission operation.
Validate the entire generated summary's shape and source IDs first, including
entries that may be omitted. Then retain its longest prefix of complete entries
that fits 6,000 canonical JSON UTF-8 bytes. Preserve every retained entry
verbatim; do not truncate text or remap citations. Record raw/admitted byte
counts, omitted entry counts, and omitted entries' source IDs. Keep the raw
model response alongside the admitted representation. Even a malformed or
invented source in an omitted entry fails preparation. An empty admitted summary
is allowed and means lost evidence, not successful continuity.

Prefix admission follows the model's existing output order. It is not an
importance guarantee and can discard useful recent facts. Quality is evaluated
from the resulting answers, never inferred from fitting the cap.

Auxiliary calls configure `model_reasoning_effort="low"` through a per-process
Codex override and retain the 300-second deadline. The 141–149-second observed
summary calls motivate this practical cost change. Answering retains the same
model and original 120-second configuration. This changes two aspects of the
auxiliary workflow; it is not a controlled estimate of either change's isolated
effect. No global Codex configuration or production provider default changes.

As before, import only the original step-zero success, verify the original
failed step-one payload digest, and generate the remaining chronological prefix
without future questions or grading feedback. Use a fresh directory and profile
name. Keep all other original limits, instructions, and 100 questions. Capture
100 new comparator answers only if preparation succeeds, reusing the original
200 answers as explicitly historical comparison records. The three answering
arms are not temporally interleaved. Never replay uncertain or failed calls.

Freeze this profile before calling the model. Preserve every result and report
cost, omissions, provenance checks, and unavailable outcomes. Human factual and
relational ratings remain unset; fitting context or citing IDs is not quality
acceptance.
