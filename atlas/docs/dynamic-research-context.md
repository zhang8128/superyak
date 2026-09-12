# Dynamic context for continuous research

`make atlas ATLAS_ARGS='start'` from the Superyak root uses dynamic context by
default for the selected `ATLAS_PROJECT`. Each planning and
paper-assessment step builds a fresh, bounded request. Durable graph records and retrieved job documents
remain the originals; a smaller selection goes to the model. A growing research
history does not need to become a growing conversation prompt.

`workbench.research_context` implements selection and request admission using
only the standard library. It follows the existing Engram dynamic-context
pattern: preserve the current task, select original evidence, omit whole optional
entries, account for the complete supplied request, and retain an inspection
manifest. It does not depend on an unmerged Engram checkout or its running MCP
server.

The worker's `research-status --json` output includes `context_mode: dynamic` and its
context budget. The installed science adapter reserves 1,800 output tokens.
Each saved extraction retains a context manifest; proposed drafts identify
the supplied passage IDs and how many retrieved passages were omitted. Each
question's frontier retains its latest planning manifest. Resuming a previously
prepared draft preserves that exact draft and its earlier provenance.

## Runner and model integration

Use `select_context(inbox.snapshot(), question, query=...)` to rank records across
the current local graph. The optional query can include the current paper's
title and search terms. Selection does not take only the most recent records.
Each result contains its complete record, source metadata, view membership,
and relations connecting it to the current question. Withdrawn records and
relations are excluded. Results are lexical relevance candidates, not a claim
that all useful evidence was found.

Use `compile_request(model=..., instructions=..., question=...,
context=..., schema=..., document=..., prior_queries=...)` before each model
request. The returned `.payload` is a fresh Ollama chat request; `.serialized`
is its canonical JSON. `.manifest` records the request hash, selected IDs,
omission counts, limits, and accounting method. Dispatch that request without
adding another conversation history. Persist the manifest with its job output.

The current question, instructions, output schema and source metadata are
required. Extraction requires at least one complete source passage. Further
passages and graph entries are selected as whole units so their qualifications
are not silently cut off. The prompt explicitly states how many retrieved
passages it omits. Validate a returned quotation against a passage actually
supplied in this request, not merely a passage elsewhere in the cached article.
The complete cached document stays available to later work.

Default component settings are a 32,768-token requested model context,
20,000 serialized UTF-8 input bytes, 2,048 output tokens and a 2,048-token
template margin. The adapter can choose a smaller output allowance. Input
admission uses the smaller of its byte ceiling and the context capacity after
reserves. If required content does not fit, raise a visible capacity error;
do not silently drop the question or switch to an accumulating history.

**Byte accounting is a conservative estimate, not a certified count of
Ollama's rendered prompt.** The manifest says `strict_token_count: false`.
Ollama receives explicit `num_ctx` and `num_predict` options; actual prompt and
output token usage should be recorded with each completed call. This mechanism
does not promise unlimited model context or perfect recall.

These candidates come from the operator's existing local Atlas inbox, with its
prediction/regulation membership retained. This does not grant access to foreign
Lighthouse publications or infer context-injection permission from an overlap
read grant. External publishers require their own admitted source adapter.
Recording continues through ResearchInbox with its existing proposed status,
idempotency and publication recovery behavior.

## Component measurement

On 2026-09-07, installed `qwen3.8:27b-mlx` received a synthetic 1,018-record
graph's selected context. A relevant earlier record preceded 1,000 newer
distractors. The model returned the correct earlier record ID and preserved its
exact assay boundary and uncertainty. The run took 25.481 seconds, with
4,072 reported prompt tokens and 47 output tokens. Its serialized request was
19,270 bytes. The probe used a 256-token output reserve. No live research draft
was written.

The exact request, response, manifest and independent verification are under
the directory named by `/tmp/atlas-dynamic-qwen-smoke-latest.txt`. This is one
observed retrieval result, not an overnight continuity or scientific-quality
evaluation; it was the initial probe before the review fixes below. Component tests separately exercise old-record retrieval, growing
query history, whole-entry omission, Unicode and schema overhead, and required
content overflow.

The installed tree passed **275 workbench tests**, including 16 context tests
and three default-integration tests. A separate 500-request deterministic
growth replay retained the older target on every request and stayed within
20,000 bytes (maximum 19,991). It made no model calls or live inbox writes;
`/tmp/atlas-dynamic-context-replay-latest.txt` locates its report.

Independent standards and behavior reviews cleared patch SHA-256
`eef2068733ad9d31b623c848374f7b6b1155d09e7a8fd70aa5857355c6824e3a`.
Two findings were reproduced with failing tests and fixed: JSON field names
no longer create false relevance, and valid questions with empty summaries
remain usable. The reviewed integration dispatches the admitted request
unchanged, rejects quotations from omitted passages, and reloads the current
graph before every paper assessment. A two-paper test also confirmed that
the second assessment can retrieve the first paper's newly saved claim.

## Running worker verification

The existing worker was stopped through its normal checkpoint control and
resumed on 2026-09-07 at 18:55 UTC with the same model, cadence, batch size,
question selection and continuous-run settings. All seven immutable drafts
present before the upgrade retained their hashes; the research identity also
stayed unchanged. No additional restart is needed for this installation.

The resumed worker reported dynamic mode and recorded three independently
checked jobs with context manifests. One inspected call used **4,355 prompt
tokens**, 237 output tokens and 19,830 request bytes, taking 26.78 seconds.
It selected two graph accounts, including a previously saved research draft,
and eight of the 24 retrieved passages. Its quotation was checked against a
passage actually supplied to Qwen. The proposed record
`draft-eee5f372d027e7f3ed09eda72beef317fec3aca9197733a13d96ec1f22b85f7f`
was saved and published in both selected local views.

The live inspection is saved in `/tmp/atlas-dynamic-worker-verification.json`.
This verifies that the running process used the new default; it is not a claim
of completed overnight endurance or independent scientific assessment. The
worker continues until stopped using the controls in the
[continuous research guide](ollama-research.md).
