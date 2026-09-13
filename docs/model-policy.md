# Current model requirement

Updated 2026-09-12 from Kairos's instruction: **only American models may be used;
Gemma 4 is acceptable and preferred.** This supersedes the earlier Qwen worker
preference and the Kimi K3 / GLM-5.3 lead assignments, as well as the DeepSeek
alternative. Preserve their historical code and experiment records as history.

Working interpretation: eligibility follows the model's originating/publishing
organization, with Google's Gemma 4 explicitly accepted by Kairos. Model origin,
the inference provider, and the physical processing/storage location are separate
facts. This instruction alone does not establish a US-only hosting requirement
or authorize a new cloud service or destination for private data.

## Measured peer application state

The standalone [peer application](../peer/MODELS_AND_SOURCES.md) now has a
component-scoped server-owned eligibility guard, disabled until explicitly
configured. One authenticated fictional drafting request using the exact
`gemma4:31b` artifact and native local endpoint returned HTTP 200 in 22.562 seconds
on September 12 local time. Its saved draft stayed unchanged and no active release
was created. Later hardening was verified with controlled tests; generation was
not repeated during packaging. The [peer verification report](reports/2026-09-12-peer-home-verification.md)
records scope and limits.

This establishes one successful peer drafting integration. It does not validate
research extraction/review, universal runtime enforcement, cluster capacity, or
a migration of the stopped MG worker. Historical launch defaults remain as below;
Atlas/MG research supervision remains disabled.

## Preferred next family

Google identifies Gemma 4 as a Google DeepMind open-weight family, including a
31B variant. See the [official model card](https://ai.google.dev/gemma/docs/core/model_card_4),
checked September 12. Kairos's preference makes it the next family to use; its
quality and serving performance for this project's tasks still need measurement.

The existing local endpoint's model listing includes `gemma4:31b`, described as
GGUF Q4_K_M, approximately 19.9 GB on disk. The peer measurement above establishes bounded native-API compatibility for one
drafting request. A listing alone establishes neither successful generation nor
structured source extraction or source review.
No replacement worker should be described as verified from this listing alone.

The whole-Stampede3 planning scope remains accepted. The earlier eight persistent
lead identities can remain an organizational starting point; their K3/GLM model
assignments are superseded. Do not transfer Qwen replica counts, memory estimates,
or throughput assumptions to Gemma by replacing model names in the old tables.
Choose actual variants, role assignments, and placement from measured tasks.

## Required behavior

- Apply the origin requirement to every selected model: research and chat models,
  source reviewers, embeddings, rerankers, OCR, speech, and any model-based routing
  or fallback. An American serving company does not make a foreign-origin model
  eligible. Track derivative models to their base model and artifact provenance.
- Before a new deployment, record the selected model artifact/version, originating
  organization, serving provider, and destination. Confirm its eligibility before
  sending an input; names supplied by an endpoint are not sufficient provenance.
- Never fall back to a disallowed or unidentified model. Preserve the task or draft
  and report that an eligible model is unavailable. Manual editing and reading
  already authorized information should remain possible.
- Keep historical outputs attributed to the model that actually produced them.
  Do not relabel a Qwen result as Gemma research or erase earlier failed attempts.
- Preserve existing permissions on data. An eligible model does not acquire access
  to a private layer merely because it can assist with a public draft.

These are current requirements, **not a claim of implemented universal model
enforcement**. Existing CLIs, example configurations, protocol probes, and archived
launch bundles retain earlier model defaults. They must not be launched unchanged
under this requirement. The broader active-runtime inventory and selection guard
need verification before claiming that all deployed components meet it.

The local MG Qwen worker was cooperatively stopped for this policy change;
the final observed stop state is recorded in `HANDOFF.md`. Its project and all
historical results remain intact. No unrelated model service is stopped or
reconfigured by this documentation change.
