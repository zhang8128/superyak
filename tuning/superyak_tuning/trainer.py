"""Recoverable, local-only Gemma 4 text-attention LoRA training."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import torch
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from torch import Tensor, nn
from transformers import AutoModelForCausalLM, AutoTokenizer, Gemma4ForCausalLM

DEFAULT_SETTINGS: dict[str, Any] = {
    "device": "xpu",
    "max_steps": 20,
    "sequence_length": 1024,
    "rank": 16,
    "alpha": 32,
    "learning_rate": 5e-5,
    "seed": 20260913,
    "gradient_accumulation_steps": 1,
}

_SUPPORTED_SETTINGS = frozenset(DEFAULT_SETTINGS)


def _canonical_json(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "training lineage and records must be JSON-compatible"
        ) from exc
    return rendered.encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _normalized_settings(settings: dict) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise TypeError("settings must be an object")
    unknown = sorted(set(settings) - _SUPPORTED_SETTINGS)
    if unknown:
        raise ValueError(f"unsupported training settings: {', '.join(unknown)}")
    effective = {**DEFAULT_SETTINGS, **settings}

    if effective["device"] not in {"cpu", "xpu", "mps"}:
        raise ValueError("device must be one of cpu, xpu, or mps")
    for name in (
        "max_steps",
        "sequence_length",
        "rank",
        "alpha",
        "seed",
        "gradient_accumulation_steps",
    ):
        value = effective[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
    if effective["max_steps"] < 1:
        raise ValueError("max_steps must be at least 1")
    if effective["sequence_length"] < 2:
        raise ValueError("sequence_length must be at least 2")
    if effective["rank"] < 1 or effective["alpha"] < 1:
        raise ValueError("rank and alpha must be positive")
    if effective["seed"] < 0:
        raise ValueError("seed must be non-negative")
    if effective["gradient_accumulation_steps"] < 1:
        raise ValueError("gradient_accumulation_steps must be at least 1")
    learning_rate = effective["learning_rate"]
    if isinstance(learning_rate, bool) or not isinstance(learning_rate, (int, float)):
        raise TypeError("learning_rate must be a number")
    if not math.isfinite(float(learning_rate)) or learning_rate <= 0:
        raise ValueError("learning_rate must be a positive finite number")
    effective["learning_rate"] = float(learning_rate)
    return effective


def _validate_train_records(records: list[dict]) -> list[dict]:
    if not isinstance(records, list):
        raise TypeError("records must be a list")
    if any(not isinstance(record, dict) for record in records):
        raise TypeError("each record must be an object")
    train_records = [record for record in records if record.get("split") == "train"]
    if not train_records:
        raise ValueError("no training records were provided")
    for record in train_records:
        messages = record.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("each training record must contain messages")
        final = messages[-1]
        if not isinstance(final, dict) or final.get("role") != "assistant":
            raise ValueError(
                "each training record must end with a final assistant completion"
            )
        content = final.get("content")
        if not isinstance(content, str):
            raise TypeError("the final assistant completion must be a string")
        if not content.strip():
            raise ValueError("the final assistant completion must be non-empty")
        for message in messages:
            if (
                not isinstance(message, dict)
                or not isinstance(message.get("role"), str)
                or not isinstance(message.get("content"), str)
            ):
                raise TypeError("each message must have string role and content fields")

    # The order is independent of caller ordering and remains bounded by the
    # supplied training split. The seed rotates the sorted order deterministically.
    ordered = sorted(
        train_records,
        key=lambda record: (
            str(record.get("id", "")),
            str(record.get("group_id", "")),
            _canonical_json(record),
        ),
    )
    return ordered


def _as_token_ids(value: Any) -> list[int]:
    if isinstance(value, Tensor):
        value = value.tolist()
    if isinstance(value, Mapping):
        value = value["input_ids"]
    if value and isinstance(value[0], list):
        if len(value) != 1:
            raise ValueError("chat template unexpectedly returned a batch")
        value = value[0]
    return [int(token_id) for token_id in value]


def _encode_completion(
    tokenizer: Any, messages: list[dict], sequence_length: int
) -> dict[str, Tensor]:
    """Tokenize a chat while supervising only its final assistant completion."""
    if not messages or messages[-1].get("role") != "assistant":
        raise ValueError("messages must end with a final assistant completion")
    answer = messages[-1].get("content")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("the final assistant completion must be non-empty")

    try:
        prefix_ids = _as_token_ids(
            tokenizer.apply_chat_template(
                messages[:-1], tokenize=True, add_generation_prompt=True
            )
        )
        full_ids = _as_token_ids(
            tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=False
            )
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(
            "the local tokenizer could not apply its chat template"
        ) from exc

    if not prefix_ids or full_ids[: len(prefix_ids)] != prefix_ids:
        raise ValueError(
            "the tokenizer chat template does not preserve the native assistant prefix"
        )
    input_ids = full_ids[:sequence_length]
    if len(input_ids) <= len(prefix_ids):
        raise ValueError("the final assistant completion was truncated away")

    labels = [-100] * len(prefix_ids) + input_ids[len(prefix_ids) :]
    if not any(label != -100 for label in labels[1:]):
        raise ValueError("the final assistant completion produced an all-masked loss")
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long),
        "attention_mask": torch.ones(len(input_ids), dtype=torch.long),
        "labels": torch.tensor(labels, dtype=torch.long),
    }


def _validate_device(device_name: str) -> tuple[torch.device, torch.dtype]:
    if device_name == "cpu":
        return torch.device("cpu"), torch.float32
    if device_name == "mps":
        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is not available")
        return torch.device("mps"), torch.float32

    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("XPU training requires an allocated SLURM compute job")
    if not hasattr(torch, "xpu") or not torch.xpu.is_available():
        raise RuntimeError("XPU was requested but no XPU device is available")
    return torch.device("xpu"), torch.bfloat16


def _actual_attention_targets(model: nn.Module) -> list[str]:
    layers = getattr(getattr(model, "model", None), "layers", None)
    if layers is None or len(layers) == 0:
        raise ValueError("the prepared Gemma 4 text model has no text layers")

    targets: list[str] = []
    required = ("q_proj", "k_proj", "o_proj")
    for index, layer in enumerate(layers):
        attention = getattr(layer, "self_attn", None)
        if attention is None:
            raise ValueError(f"text layer {index} has no self_attn block")
        prefix = f"model.layers.{index}.self_attn"
        for suffix in required:
            if not isinstance(getattr(attention, suffix, None), nn.Linear):
                raise TypeError(
                    f"text layer {index} has no supported linear {suffix} projection"
                )
            targets.append(f"{prefix}.{suffix}")

        value_projection = getattr(attention, "v_proj", None)
        if value_projection is not None:
            if not isinstance(value_projection, nn.Linear):
                raise ValueError(
                    f"text layer {index} has an unsupported v_proj projection"
                )
            targets.append(f"{prefix}.v_proj")

    return sorted(targets)


def _sampled_frozen_digest(model: nn.Module) -> str:
    digest = hashlib.sha256()
    sampled = 0
    for name, parameter in model.named_parameters():
        if parameter.requires_grad or "lora_" in name:
            continue
        values = parameter.detach().reshape(-1)
        if values.numel() == 0:
            continue
        sample = values[: min(256, values.numel())].to(
            device="cpu", dtype=torch.float32
        )
        digest.update(name.encode("utf-8"))
        digest.update(sample.contiguous().numpy().tobytes())
        sampled += 1
        if sampled == 12:
            break
    if sampled == 0:
        raise RuntimeError(
            "no frozen base weights were available for the training audit"
        )
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_json(payload) + b"\n")
    os.replace(temporary, path)


def _move_optimizer_state(
    optimizer: torch.optim.Optimizer, device: torch.device
) -> None:
    for state in optimizer.state.values():
        for key, value in state.items():
            if isinstance(value, Tensor):
                state[key] = value.to(device)


def _capture_rng_state(device_name: str) -> dict[str, Any]:
    state: dict[str, Any] = {"cpu": torch.get_rng_state()}
    if device_name == "xpu":
        state["xpu"] = torch.xpu.get_rng_state_all()
    elif device_name == "mps":
        state["mps"] = torch.mps.get_rng_state()
    return state


def _restore_rng_state(state: dict[str, Any], device_name: str) -> None:
    torch.set_rng_state(state["cpu"])
    if device_name == "xpu":
        torch.xpu.set_rng_state_all(state["xpu"])
    elif device_name == "mps":
        torch.mps.set_rng_state(state["mps"])


def _save_checkpoint(
    run_dir: Path,
    model: PeftModel,
    optimizer: torch.optim.Optimizer,
    *,
    completed_steps: int,
    data_cursor: int,
    gradient_norms: list[float],
    device_name: str,
    run_identity: str,
) -> Path:
    checkpoints = run_dir / "checkpoints"
    checkpoints.mkdir(mode=0o700, exist_ok=True)
    checkpoint = checkpoints / f"step-{completed_steps:08d}"
    temporary_checkpoint = checkpoints / f".step-{completed_steps:08d}.tmp"
    if temporary_checkpoint.exists():
        shutil.rmtree(temporary_checkpoint)
    if checkpoint.exists():
        # A checkpoint ahead of the published state pointer is an orphan left
        # by an interrupted save. Recomputing from the prior pointer is safe.
        shutil.rmtree(checkpoint)
    temporary_checkpoint.mkdir(mode=0o700)
    adapter = temporary_checkpoint / "adapter"
    model.save_pretrained(adapter, safe_serialization=True)
    torch.save(
        {
            "optimizer": optimizer.state_dict(),
            "rng": _capture_rng_state(device_name),
        },
        temporary_checkpoint / "optimizer.pt",
    )
    checkpoint_state = {
        "run_identity": run_identity,
        "completed_steps": completed_steps,
        "data_cursor": data_cursor,
        "gradient_norms": gradient_norms,
        "checkpoint": checkpoint.name,
    }
    _write_json(temporary_checkpoint / "state.json", checkpoint_state)
    os.replace(temporary_checkpoint, checkpoint)
    adapter = checkpoint / "adapter"

    # Publish the pointer last, after the new immutable checkpoint is complete.
    _write_json(run_dir / "state.json", checkpoint_state)
    shutil.copy2(checkpoint / "optimizer.pt", run_dir / "optimizer.pt")
    final_adapter = run_dir / "adapter"
    if final_adapter.exists():
        shutil.rmtree(final_adapter)
    shutil.copytree(adapter, final_adapter)
    return checkpoint


def _load_checkpoint_state(run_dir: Path, run_identity: str) -> tuple[dict, Path]:
    try:
        pointer = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        checkpoint_name = pointer["checkpoint"]
        expected_name = f"step-{int(pointer.get('completed_steps', -1)):08d}"
    except (
        OSError,
        json.JSONDecodeError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "the training run has no valid recoverable checkpoint"
        ) from exc
    if checkpoint_name != expected_name:
        raise ValueError("the training run's checkpoint pointer is invalid")
    checkpoint = run_dir / "checkpoints" / checkpoint_name
    if not checkpoint.is_dir():
        raise ValueError("the training run's latest checkpoint is missing")
    try:
        checkpoint_state = json.loads(
            (checkpoint / "state.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("the checkpoint metadata is missing or invalid") from exc
    if not isinstance(checkpoint_state, dict):
        raise TypeError("the checkpoint metadata must be an object")
    if checkpoint_state.get("run_identity") != run_identity:
        raise ValueError("checkpoint identity does not match the requested run")
    if checkpoint_state != pointer:
        raise ValueError("the published pointer does not match checkpoint metadata")
    return checkpoint_state, checkpoint


def _validate_saved_adapter_targets(
    adapter_dir: Path, actual_targets: list[str]
) -> None:
    try:
        config = json.loads(
            (adapter_dir / "adapter_config.json").read_text(encoding="utf-8")
        )
        saved_targets = config["target_modules"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("the saved adapter configuration is invalid") from exc
    if (
        not isinstance(saved_targets, list)
        or any(not isinstance(target, str) for target in saved_targets)
        or sorted(saved_targets) != actual_targets
    ):
        raise ValueError("saved adapter targets do not match the prepared text model")


def run_training(
    model_dir: Path,
    records: list[dict],
    output_dir: Path,
    settings: dict,
    lineage: dict,
    resume: bool = False,
) -> dict:
    """Train or resume a local Gemma 4 LoRA and return an audit receipt."""
    model_dir = Path(model_dir)
    run_dir = Path(output_dir)
    effective = _normalized_settings(settings)
    train_records = _validate_train_records(records)
    # Validate serializability without retaining participant content in the run log.
    _canonical_json(lineage)
    records_sha256 = _sha256(train_records)
    immutable_settings = {
        key: value for key, value in effective.items() if key != "max_steps"
    }
    identity_payload = {
        "schema_version": 1,
        "immutable_settings": immutable_settings,
        "lineage": lineage,
        "records_sha256": records_sha256,
    }
    run_identity = _sha256(identity_payload)
    device, dtype = _validate_device(effective["device"])

    state: dict[str, Any] | None = None
    checkpoint: Path | None = None
    if resume:
        try:
            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                "resume requested but the training run is missing"
            ) from exc
        if manifest.get("lineage") != lineage:
            raise ValueError("resume lineage does not match the existing run")
        if manifest.get("immutable_settings") != immutable_settings:
            raise ValueError("resume settings do not match the existing run")
        if manifest.get("records_sha256") != records_sha256:
            raise ValueError("resume training records do not match the existing run")
        if manifest.get("run_identity") != run_identity:
            raise ValueError("resume identity does not match the existing run")
        state, checkpoint = _load_checkpoint_state(run_dir, run_identity)
        if effective["max_steps"] < state["completed_steps"]:
            raise ValueError("max_steps cannot be lower than the completed step count")
    elif run_dir.exists():
        raise FileExistsError(f"training run directory already exists: {run_dir}")

    torch.manual_seed(effective["seed"])
    load_kwargs: dict[str, Any] = {
        "local_files_only": True,
        "trust_remote_code": False,
        "dtype": dtype,
    }
    if effective["device"] == "cpu":
        load_kwargs["attn_implementation"] = "eager"
    model = AutoModelForCausalLM.from_pretrained(model_dir, **load_kwargs)
    if (
        not isinstance(model, Gemma4ForCausalLM)
        or model.config.model_type != "gemma4_text"
    ):
        raise ValueError("the prepared model must be a Gemma4ForCausalLM text model")
    model.config.use_cache = False
    model.to(device)
    tokenizer = AutoTokenizer.from_pretrained(
        model_dir, local_files_only=True, trust_remote_code=False
    )
    if not tokenizer.chat_template:
        raise ValueError("the prepared tokenizer has no chat template")
    encoded_records = [
        _encode_completion(tokenizer, record["messages"], effective["sequence_length"])
        for record in train_records
    ]

    actual_targets = _actual_attention_targets(model)
    if resume:
        assert checkpoint is not None
        if manifest.get("actual_targets") != actual_targets:
            raise ValueError("resume attention targets do not match the existing run")
        _validate_saved_adapter_targets(checkpoint / "adapter", actual_targets)
        model = PeftModel.from_pretrained(
            model, checkpoint / "adapter", is_trainable=True
        )
    else:
        model = get_peft_model(
            model,
            LoraConfig(
                r=effective["rank"],
                lora_alpha=effective["alpha"],
                target_modules=actual_targets,
                lora_dropout=0.0,
                bias="none",
                task_type=TaskType.CAUSAL_LM,
            ),
        )
    model.to(device)
    trainable = [
        (name, parameter)
        for name, parameter in model.named_parameters()
        if parameter.requires_grad
    ]
    if not trainable or any(
        "lora_" not in name or "router" in name or "expert" in name
        for name, _ in trainable
    ):
        raise RuntimeError("only LoRA text-attention parameters may be trainable")
    frozen_before = _sampled_frozen_digest(model)

    optimizer = torch.optim.AdamW(
        [parameter for _, parameter in trainable], lr=effective["learning_rate"]
    )
    completed_steps = 0
    data_cursor = 0
    gradient_norms: list[float] = []
    if resume:
        assert state is not None and checkpoint is not None
        try:
            saved = torch.load(
                checkpoint / "optimizer.pt", map_location="cpu", weights_only=True
            )
            optimizer.load_state_dict(saved["optimizer"])
            _restore_rng_state(saved["rng"], effective["device"])
            _move_optimizer_state(optimizer, device)
            completed_steps = int(state["completed_steps"])
            data_cursor = int(state["data_cursor"])
            gradient_norms = [float(value) for value in state["gradient_norms"]]
        except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise ValueError("the recoverable optimizer checkpoint is invalid") from exc

    if not resume:
        run_dir.mkdir(parents=True, mode=0o700)
        os.chmod(run_dir, 0o700)
        _write_json(
            run_dir / "run.json",
            {
                **identity_payload,
                "run_identity": run_identity,
                "initial_max_steps": effective["max_steps"],
                "actual_targets": actual_targets,
            },
        )

    model.train()
    latest_checkpoint = checkpoint
    accumulation = effective["gradient_accumulation_steps"]
    while completed_steps < effective["max_steps"]:
        optimizer.zero_grad(set_to_none=True)
        for _ in range(accumulation):
            record_index = (data_cursor + effective["seed"]) % len(encoded_records)
            example = encoded_records[record_index]
            batch = {
                key: value.unsqueeze(0).to(device) for key, value in example.items()
            }
            loss = model(**batch).loss
            if loss is None or not torch.isfinite(loss):
                raise RuntimeError("training produced a non-finite loss")
            (loss / accumulation).backward()
            data_cursor += 1

        squared_norm = 0.0
        for _, parameter in trainable:
            if parameter.grad is None:
                continue
            if not torch.isfinite(parameter.grad).all():
                raise RuntimeError("training produced non-finite adapter gradients")
            squared_norm += float(parameter.grad.detach().float().norm().item()) ** 2
        gradient_norm = math.sqrt(squared_norm)
        if not math.isfinite(gradient_norm) or gradient_norm <= 0:
            raise RuntimeError("training produced no finite adapter gradient")
        gradient_norms.append(gradient_norm)
        optimizer.step()
        completed_steps += 1
        latest_checkpoint = _save_checkpoint(
            run_dir,
            model,
            optimizer,
            completed_steps=completed_steps,
            data_cursor=data_cursor,
            gradient_norms=gradient_norms,
            device_name=effective["device"],
            run_identity=run_identity,
        )

    frozen_after = _sampled_frozen_digest(model)
    frozen_unchanged = frozen_before == frozen_after
    if not frozen_unchanged:
        raise RuntimeError("a sampled frozen base weight changed during LoRA training")

    return {
        "run_identity": run_identity,
        "run_dir": str(run_dir),
        "completed_steps": completed_steps,
        "max_steps": effective["max_steps"],
        "data_cursor": data_cursor,
        "actual_targets": actual_targets,
        "trainable_parameters": [name for name, _ in trainable],
        "gradient_norms": gradient_norms,
        "all_gradients_finite": all(math.isfinite(value) for value in gradient_norms),
        "frozen_weights_unchanged": frozen_unchanged,
        "checkpoint": str(latest_checkpoint) if latest_checkpoint else None,
        "adapter_dir": str(run_dir / "adapter"),
        "resumed": resume,
    }
