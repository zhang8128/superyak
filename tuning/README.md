# Clinical and biotech tuning

Standalone Apache-2.0 tools for local clinical records, biomedical evidence,
assay results, sequencing QC, and recoverable text-attention LoRA training.
Identifiable clinical records and confidential biotech inputs are supported.
There is no medical-topic filter or categorical patient-data exclusion.

This component works on operator-selected local files. It does not require a
central data service. Peer account authentication, dashboard source selection,
and distributed adapter exchange are separate integrations still to build.
No command publishes data or adapters or submits a cluster job automatically.

## Install

From the repository root, on macOS or Linux:

```sh
make setup-tuning
make check-tuning
make tuning TUNING_ARGS='--help'
```

The root `make setup` and `make check` targets include this component with the
CPU `train` extra. The focused commands above install or check only `tuning/`.

Python 3.11+ is supported; the measured Mac environment used Python 3.12.11.
The default `train` extra pins Torch 2.14.0, Transformers 5.17.0, and PEFT 0.20.0.
Linux uses PyTorch's CPU wheel index for this extra. The tests build a tiny local
Gemma 4 model and perform real optimization and resume without downloading weights.

On an Intel GPU Linux host, choose the separate locked XPU environment:

```sh
make setup-tuning TUNING_EXTRA=xpu
make check-tuning TUNING_EXTRA=xpu
```

The `xpu` extra resolves Torch 2.14.0+xpu and Triton-XPU from the official
[XPU wheel index](https://download.pytorch.org/whl/xpu/), with their runtime
dependencies. It conflicts with the CPU `train` extra; do not select both.
[PyTorch's Intel guide](https://docs.pytorch.org/docs/2.14/notes/get_start_xpu.html)
describes the required Intel driver. The lock resolves on Linux; actual Stampede3
installation/backward compatibility remains to be measured on an allocated node.
For cluster execution, use the installed `tuning/.venv/bin/python` directly so a
later command does not synchronize the environment back to CPU.

The commands below run from the repository root after setup. `make tuning` runs
inside `tuning/`, so its relative file paths are relative to that directory.

## Exact starting model

The user selected
[HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced](https://huggingface.co/HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced),
a derivative of Google's `gemma-4-26B-A4B-it`. Its derivative publisher is recorded
as HauhauCS; the explicit user selection is the eligibility basis, without
asserting an unverified nationality for the maintainer.

```sh
tuning/.venv/bin/python -m superyak_tuning model
tuning/.venv/bin/python -m superyak_tuning download --output .engram/clinical-model
```

Pinned revision: `96c11c22b1128c3c8c655b21557b409f307c557f`.
Pinned file: `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf`.
SHA-256: `f8b1da6dc139e6928159e536bc85602adbc1412018871732a878dedcad7ccafd`.
Size: 16,796,015,968 bytes. No fallback replaces it with official weights.

The selected repository supplies GGUF weights. The preparation command adapts
Transformers' legacy loader for this Gemma 4 text backbone; the reconstructed
BF16 tensors retain the source quantization loss. This does not recover original
BF16 precision. The initial trainer does not train image/audio encoders or MoE
experts/router. See [Transformers' GGUF guide](https://huggingface.co/docs/transformers/v5.17.0/quantization/gguf).

## Prepare a clinical or biotech dataset

Start from [the fictional dataset](examples/clinical-biotech-dataset.json).
Supply source IDs, domain (`clinical` or `biotech`), sensitivity (`public`,
`deidentified`, `identifiable`, or `confidential`), a rights statement, and
separate boolean grants:

| Grant | Meaning |
| --- | --- |
| `inference` | Use this source in model requests |
| `local_training` | Train a local adapter using this source |
| `shared_training` | Include it in a separately governed shared training task |
| `publish_adapter` | Authorize adapter publication derived from this source |

Missing grants are false. Public visibility does not imply any of these grants;
local training does not imply public sharing. These are declarations made by the
local operator, not signed consent from a peer participant or proof of legal
rights. A training run uses a snapshot specifically bound to `local_training`.
Creating a snapshot for another purpose does not execute that operation.

Examples include `id`, `group_id`, `source_ids`, `split` (`train`, `dev`, `test`),
and conversation `messages` ending in an authored assistant answer. Preserve
units, evidence IDs, subject/sample identifiers, corrections, and uncertainty.
The importer never invents supervision from raw attachments. Group by the patient,
family, experiment or study that must remain in one split. Exact duplicate
conversations across splits and groups spanning splits are rejected; near-duplicate
or semantic leakage still needs dataset review.

Optional source `attachments` are relative paths within the input directory.
CSV, JSON, JSONL, and TXT files retain exact bytes and hashes. Each input or
attachment is limited to 64 MiB; split larger collections into deliberate batches.
Symlinks and paths outside the dataset directory are rejected. This is a bounded
text/file importer, not a full FHIR validator or an image, FASTQ, BAM, or microscopy
pipeline. Structured extracts of those sources can be supplied with provenance.

```sh
tuning/.venv/bin/python -m superyak_tuning snapshot \
  --input tuning/examples/clinical-biotech-dataset.json \
  --output .engram/clinical-snapshot --purpose local_training
```

Snapshots use private directories and hash-checked inventories. Commands refuse
to overwrite existing snapshots or silently mix their purposes. Training consumes
only `train` rows, with loss on the final assistant completion. Native continuation
tokenization handles the selected model's different thinking/generation prefix.
Re-author the source and make a new snapshot when correcting examples or grants.

## Run the selected baseline locally

Use an existing local Ollama server and installed `ollama` CLI:

```sh
tuning/.venv/bin/python -m superyak_tuning install \
  --gguf .engram/clinical-model/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf \
  --receipt .engram/clinical-model/import.json

tuning/.venv/bin/python -m superyak_tuning evaluate \
  --cases tuning/examples/clinical-biotech-cases.json \
  --model-receipt .engram/clinical-model/import.json \
  --output .engram/clinical-baseline
```

The default model name is `superyak-clinical-gemma4-balanced:q4_k_m`.
Import records the verified original GGUF and the resulting local runtime digest;
Ollama can rewrite its blob during conversion. The evaluator checks this receipt
before sending prompts and checks identity again afterward. The receipt trusts
the operator's local Ollama server; it is not remote attestation. Evaluation is
loopback-only, disables ambient HTTP proxies and redirects, and uses bounded
requests. Private answer evidence goes into `results.json`; terminal output gives
counts, not participant records. Treat model-server logs as part of the local
clinical-data environment.

The eight shipped cases deliberately overlap the training examples. They are
engineering diagnostics, not a held-out quality test. Required/forbidden terms
and a narrow refusal heuristic are mechanical checks. They miss paraphrases and
some refusals; every result records `clinical_validation: not_established` and
human review pending. The [first baseline report](../docs/reports/2026-09-13-clinical-tuning-baseline.md)
records six strict passes and no detected refusals, with two reviewed mismatches.

## Materialize and train on allocated compute

The selected GGUF exposes gaps in stock Transformers 5.17: per-layer KV heads,
MoE configuration, and expert/router/scalar tensor names. Preparation supplies
the pinned architecture configuration and scopes the missing tensor-name mappings
to the load. The architecture metadata comes from Google's pinned
[base configuration](https://huggingface.co/google/gemma-4-26B-A4B-it/blob/4d7ae4984b7db7de8f8457170b3f1a419ee76d52/config.json);
all weights come from the selected HauhauCS GGUF. Prepared lineage records both.
Metadata and tensor-shape audits plus real tokenizer checks passed; full tensor
materialization still needs its high-memory compute run.

Stage the selected public weights and permitted dataset to the chosen compute
environment explicitly. The CLI does not transfer private records. Run preparation
on an allocated high-memory node, never a login node:

```sh
/path/to/tuning/.venv/bin/python -m superyak_tuning prepare \
  --gguf /scratch/clinical/model.gguf --output /scratch/clinical/prepared
/path/to/tuning/.venv/bin/python -m superyak_tuning train \
  --model-dir /scratch/clinical/prepared --snapshot /scratch/clinical/snapshot \
  --output /scratch/clinical/run-1 --device xpu --max-steps 20
```

The GGUF preparation floor is 160 GiB **available host RAM**, a conservative
execution guard rather than a measured peak. Legacy materialization may hold
both FP32 source tensors and BF16 destination weights. A prepared model records
source provenance, library versions and every output file hash; missing or
mismatched weights prevent acceptance. [Stampede3's PVC nodes](https://docs.tacc.utexas.edu/hpc/stampede3/#ponte-vecchio-compute-nodes)
have 1 TB host RAM. Full model memory use, tile placement, kernel support and
throughput remain allocated-node experiments.

The initial run uses one visible XPU device, BF16 frozen base weights, rank 16,
alpha 32, q/k/v/o attention targets where present, sequence length 1024,
AdamW at 5e-5, and seed 20260913. It is a compatibility pilot, not distributed
whole-machine training or a promise that every kernel fits a PVC tile.
Use `train --help` for accumulation, rank and other settings. `cpu`/`mps` are
explicit diagnostic choices; a CPU full model loads FP32 and requires far more
memory than the tiny test.

```sh
/path/to/tuning/.venv/bin/python -m superyak_tuning train \
  --model-dir /scratch/clinical/prepared --snapshot /scratch/clinical/snapshot \
  --output /scratch/clinical/run-1 --device xpu --max-steps 40 --resume
```

Each step saves adapter tensors, optimizer, Torch RNG and data cursor. Resume
requires matching model/data lineage and immutable training settings; `max_steps`
can increase. Runs and checkpoints are private local artifacts. Do not expose
adapters trained on private records solely because their raw examples are absent
from the output files; publication has a separate grant and review process.
No adapter publishing command is implemented here.

Generate a reviewable script with actual account, reservation and remote paths:

```sh
tuning/.venv/bin/python -m superyak_tuning slurm \
  --account YOUR_ALLOCATION --reservation YOUR_RESERVATION \
  --python /path/to/tuning/.venv/bin/python \
  --model-dir /scratch/clinical/prepared --snapshot /scratch/clinical/snapshot \
  --run-dir /scratch/clinical/run-1 --output .engram/clinical-job.sh
```

Omit `--reservation` when none applies. The script requests one PVC node for
30 minutes and does not submit itself. `--python`, `--model-dir`, `--snapshot`,
and `--run-dir` are required absolute paths for the compute environment; the
output parent is created privately when missing. XPU training refuses execution
without `SLURM_JOB_ID` and an available XPU. A generated script proves neither
allocation access nor a completed training run.

## Next measurements

Use an independent, reviewed clinical/biotech holdout to compare the selected
baseline with the adapter: extraction and units, correction handling, evidence
attribution, assay/QC calculations, uncertainty, and clinical/biotech engagement.
Track privacy leakage and unintended behavior separately from task utility.
The first real dataset and Stampede3 login/allocation are still needed. No
full-size materialization, Intel backward pass, or improved clinical adapter has
yet been measured. Scaling, peer consent integration, adapter serving and private
peer distribution follow that verified pilot.
