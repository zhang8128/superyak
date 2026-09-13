# Clinical and biotech tuning implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent implementation/review and execute continuously under the user's approval.

**Goal:** Deliver runnable clinical/biotech dataset, selected-model, LoRA training, and evaluation tools.

**Architecture:** A standalone `tuning/superyak_tuning` package uses standard-library control/data code and optional pinned Torch/Transformers/PEFT training dependencies. Existing live peer services are preserved.

**Tech Stack:** Python >=3.11, pytest, optional torch 2.14.0, transformers 5.17.0, peft 0.20.0, gguf, safetensors, Hugging Face Hub.

**Spec:** `docs/superpowers/specs/2026-09-13-clinical-tuning-design.md`

## Global constraints

- Clinical and biotech are supported domains, including identifiable/confidential input for permitted local use.
- Missing source-use permissions are false; public visibility does not authorize training or publication.
- The selected HauhauCS Q4_K_M revision/hash is fixed in the spec; no silent base substitution.
- No model/data/endpoint credentials or participant content in ordinary logs or source control.
- No live demo reset, Atlas restart, cluster submission with invented credentials, or external transfer of private records.
- One implementation agent works only on trainer files while root handles data, model, CLI, and integration; use independent reviews.

### Task 1: Dataset snapshots and model preparation (root)

Files: `tuning/superyak_tuning/{data,models,__init__}.py`, `tuning/tests/test_data.py`, `tuning/tests/test_models.py`, `tuning/pyproject.toml`.

Interfaces: `snapshot_dataset(input_path: Path, output_dir: Path, purpose: str) -> dict`; `read_snapshot(path: Path, purpose: str) -> tuple[dict, list[dict]]`; `selected_model() -> dict`; `download_model(output_dir: Path) -> dict`; `prepare_model(gguf_path: Path, output_dir: Path) -> dict`; `verify_prepared(path: Path) -> dict`.

- [ ] Add tests that import a fictional identifiable clinical record with local-training consent, reject missing grants and split leakage, and detect modified snapshots.
- [ ] Verify failure with `python -m pytest tuning/tests/test_data.py` before implementing.
- [ ] Implement canonical manifest/JSONL snapshots and attached-file integrity; no automatic export to third parties.
- [ ] Test the exact GGUF manifest and tampered prepared-model inventory; implement explicit hash-verified download/materialization.
- [ ] Run covering tests and retain command evidence.

Example contract:
```python
manifest, rows = read_snapshot(snapshot, purpose="local_training")
assert all(row["split"] in {"train", "dev", "test"} for row in rows)
lineage = verify_prepared(prepared_model)
```

### Task 2: Recoverable LoRA training (implementation agent)

Files: `tuning/superyak_tuning/trainer.py`, `tuning/tests/test_trainer.py`; may add a focused helper under a new trainer-specific filename. Do not modify root-owned package/CLI/data/model files.

Interfaces: `run_training(model_dir: Path, records: list[dict], output_dir: Path, settings: dict, lineage: dict, resume: bool = False) -> dict`. The caller validates prepared model and source grants. `records` have `id`, `group_id`, `source_ids`, `split`, and `messages: [{role, content}]`. `lineage` is a JSON-compatible object containing model/source/snapshot digests. Include it in immutable run identity and reject changed lineage on resume.

Supported settings: `device` (`cpu`, `xpu`, `mps`), `max_steps`, `sequence_length`, `rank`, `alpha`, `learning_rate`, `seed`; optional `gradient_accumulation_steps` default 1. Initial defaults: XPU, 20 steps, 1024 tokens, rank 16, alpha 32, learning rate 5e-5, seed 20260913. Set attention-only target suffixes q/k/v/o projections, restricted to the text model; leave routed experts/router and base frozen. Inspect actual targets. Handle absent v projections without accidental vision/router targeting.

- [ ] Write a real CPU test with a tiny locally constructed Gemma4ForCausalLM and local tokenizer. It must show an actual adapter optimizer update, sampled frozen weights unchanged, saved adapter/checkpoint, and continued training after resume.
- [ ] Write mismatch tests for altered settings/lineage on resume, invalid/no assistant completions, and XPU without allocation. Observe failures before implementation.
- [ ] Load only local prepared model/tokenizer (`local_files_only=True`), with `trust_remote_code=False`. Use a matching text causal model, eager attention for CPU diagnostics, float32 CPU and BF16 XPU. Verify native final-completion loss masking by comparing prefix/full tokenization, refuse all-masked/truncated-away answers.
- [ ] Use ordinary AdamW and a bounded deterministic record order over `split=train`. Fail if no train rows. Allow clinical/biotech content; no topic filtering or invented labels.
- [ ] Record finite gradients and actual targets; checkpoint model adapter, optimizer, RNG, data cursor/step into a new private run directory. Resume requires the same identity and can increase max_steps. Avoid loading untrusted pickle; use appropriate safe Torch loading for own tensor/state checkpoints.
- [ ] Run the CPU test with actual Torch/PEFT, then covering tests, commit only owned files, and write a report with measured evidence and unresolved Intel limits.

Invocation example:
```python
receipt = run_training(model_dir, rows, run_dir,
    {"device": "cpu", "max_steps": 2, "sequence_length": 128,
     "rank": 2, "alpha": 4, "learning_rate": 1e-3, "seed": 7}, lineage)
assert receipt["completed_steps"] == 2
```

### Task 3: Domain evaluation, CLI, and integration (root)

Files: `tuning/superyak_tuning/{evaluation,__main__}.py`, `tuning/examples/*`, `tuning/tests/test_evaluation.py`, `tuning/tests/test_cli.py`, `tuning/README.md`, root Makefile/README/model policy/HANDOFF.

Interfaces: CLI `model`, `snapshot`, `download`, `prepare`, `train`, `evaluate`, `slurm`; `evaluate_cases(cases: list[dict], endpoint: str, model: str, output_dir: Path) -> dict`. Local loopback Ollama endpoint uses exact model identity, explicit request timeout and bounded outputs. Export response evidence to private run directory; report deterministic checks as mechanical diagnostics, with clinical validation pending.

- [ ] Test clinical/biotech fixture evaluations using an in-process HTTP server, including engagement, evidence IDs, failed requests, duplicate cases, and no fabricated pass from empty output.
- [ ] Implement the CLI contracts and help, a domain-focused dataset example, clinical/biotech baseline cases, and a Slurm script generator using explicit local paths/account and allocated XPU. It must not submit jobs.
- [ ] Run end-to-end snapshot/model/CLI smoke checks and tiny-model trainer integration. Download the selected model to an ignored cache and run a bounded real local baseline if runtime allows, preserving the existing demo model.
- [ ] Document exact commands and actual limits; update model policy to record user-selected derivative and clinical/biotech purpose.
- [ ] Obtain task and whole-branch review, resolve findings, run final relevant checks, and integrate/push under standing authorization.
