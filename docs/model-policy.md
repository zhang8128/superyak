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

## Clinical/biotech training selection — September 13

Kairos explicitly selected **HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced**
as the starting model and affirmed that clinical and biotech data are intended
workloads, including permitted identifiable clinical and confidential biotech
records. This supersedes the prior candidate-only treatment of this derivative.
Its base publisher is Google; derivative publisher is HauhauCS. Eligibility here
rests on explicit user selection, not an assertion of the maintainer's nationality.

The [tuning package](../tuning/README.md) pins the Q4_K_M revision, size and SHA-256,
records GGUF conversion lineage, and refuses silent base substitutions. The
selected model is installed separately as `superyak-clinical-gemma4-balanced:q4_k_m`.
[Eight fictional baseline cases](reports/2026-09-13-clinical-tuning-baseline.md)
produced six exact-check passes and no detected blanket refusals. Clinical
validation and full-size Intel training remain unestablished.

Clinical and biotech subject matter is not itself a refusal condition. Model
access, local/shared training, and adapter publication each retain their own
source-use grants; public visibility never grants all of them. The current CLI
uses operator-declared local grants, not authenticated participant consent APIs.
Kairos subsequently selected this same variant for the local peer demo. The peer
guard now pins `superyak-clinical-gemma4-balanced:q4_k_m` and its measured Ollama
manifest digest `964dccf2e808c93bda5236b30231b1e72cadd9f12336fb505471f49add9810c4`.
The September 12 `gemma4:31b` measurement below remains a historical result.

## Measured peer application state

On September 13, the explicitly selected HauhauCS variant replaced the local
demo's model pin. A fresh browser entry and one fictional source-grounded drafting
request returned HTTP 200 in 5.21 seconds. All 25 existing content tables and the
credentials were unchanged through reload and verification. This verifies one
private suggestion through the peer; it does not establish clinical accuracy or
an adapter-training improvement.

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
