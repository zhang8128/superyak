# Clinical and biotech adapter tooling

The approved Stampede3 tuning proposal now starts with the explicitly selected
HauhauCS Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced derivative. Clinical and
biotech work are the intended workloads. Identifiable clinical records and
private biotech material are supported when their owners permit the chosen
local use; public sharing and shared training are independent permissions.
No subject-word blocklist or blanket medical/biotech refusal is introduced.

Build a standalone `tuning/` Python package with a small CLI. It produces immutable
dataset snapshots, pins/downloads/verifies the selected GGUF, materializes its
text weights using Transformers, trains a recoverable text-attention LoRA, and
runs grounded clinical/biotech evaluation cases against an explicitly selected
local endpoint. Local preparation and cluster commands remain separate from
the existing live dashboard and stopped Atlas worker.

The selected artifact is the standard Q4_K_M GGUF at repository revision
`96c11c22b1128c3c8c655b21557b409f307c557f`, SHA-256
`f8b1da6dc139e6928159e536bc85602adbc1412018871732a878dedcad7ccafd`.
Its base is Google's Gemma 4; the user explicitly selected this derivative.
Record the derivative publisher without claiming its maintainer is American.
Never substitute official Gemma weights silently. Dequantization preserves the
quantized derivative, not the lost original precision. First training is text;
the separate image projector is not represented as a verified training path.

Dataset input is a JSON object with `schema_version: 1`, `sources`, and
`examples`. Each source has an ID, domain (`clinical`/`biotech`), sensitivity
(`public`/`deidentified`/`identifiable`/`confidential`), rights description, and
boolean `inference`, `local_training`, `shared_training`, and `publish_adapter`
permissions. Missing permissions default false. Examples identify their source
IDs, group ID, split (`train`/`dev`/`test`), and role/content messages. Training
examples end in an assistant answer. Optional source attachments preserve CSV,
JSON (including FHIR records), JSONL, and text bytes. No clinical labels are
invented from raw records. Include deliberate, authored supervised answers.

Snapshot creation validates references, rejects a group spanning splits and
duplicate conversations across splits, and checks relevant source grants.
It retains a canonical digest and file inventory in a new private directory.
Loading verifies all file hashes. Local training with identifiable/confidential
sources is permitted; shared use requires its independent grants. Artifact
publication remains a separate future action, never implied by local training.

Model downloads and materialization are explicit commands. GGUF size/hash must
match. Materialization records source ancestry and hashes of prepared weights;
training validates those hashes. The PyTorch/PEFT trainer uses the model's chat
template, supervises the final assistant completion, freezes base/router/experts,
records actual target names, and saves optimizer/RNG/data position for resume.
XPU requires an allocated compute job. A tiny randomly initialized Gemma CPU
test verifies real optimization and resume without downloading model weights.

Evaluation distinguishes mechanical checks from human judgment. Legitimate
clinical/biotech answers should engage with supplied records and evidence;
unsupported diagnoses, invented measurements, factual omissions and generic
refusals do not count as successes. No small test suite establishes clinical
validity. Results preserve model identity and case IDs. Identifiable material
is not sent to arbitrary external endpoints by this implementation.

Acceptance: snapshot/import tests with fictional identifiable records pass;
selected-model artifact lineage is exact; real tiny-model LoRA changes only
adapters and resumes; endpoint evaluation has a real local baseline when
available; documented commands prepare a compute-node run without submitting
unknown allocation details. Clinical/biotech data restrictions are ownership
and purpose permissions, not categorical exclusions.
