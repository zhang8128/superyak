from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import torch
from safetensors.torch import load_file
from superyak_tuning.trainer import (
    _actual_attention_targets,
    _encode_completion,
    run_training,
)
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import (
    AutoModelForCausalLM,
    Gemma4ForCausalLM,
    Gemma4TextConfig,
    PreTrainedTokenizerFast,
)

CHAT_TEMPLATE = """{% for message in messages %}{{ message['role'] + ' ' + message['content'] + ' ' + eos_token + ' ' }}{% endfor %}{% if add_generation_prompt %}{{ 'assistant ' }}{% endif %}"""


@pytest.fixture(scope="module")
def tiny_model_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    model_dir = tmp_path_factory.mktemp("tiny-gemma4")
    config = Gemma4TextConfig(
        vocab_size=64,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        head_dim=8,
        max_position_embeddings=128,
        sliding_window=32,
        layer_types=["full_attention"],
        vocab_size_per_layer_input=64,
        hidden_size_per_layer_input=16,
        attention_k_eq_v=False,
        pad_token_id=0,
        eos_token_id=1,
        bos_token_id=2,
    )
    # Gemma 4's heterogeneous defaults widen full-attention heads. Keep this
    # local diagnostic model intentionally tiny.
    config.per_layer_config = {}
    torch.manual_seed(123)
    Gemma4ForCausalLM(config).save_pretrained(model_dir, safe_serialization=True)

    vocab = {
        "<pad>": 0,
        "<eos>": 1,
        "<bos>": 2,
        "<unk>": 3,
        "system": 4,
        "user": 5,
        "assistant": 6,
        "patient": 7,
        "reports": 8,
        "fever": 9,
        "culture": 10,
        "pending": 11,
        "state": 12,
        "uncertainty": 13,
        "and": 14,
        "seek": 15,
        "urgent": 16,
        "care": 17,
        "if": 18,
        "breathing": 19,
        "worsens": 20,
        "assay": 21,
        "control": 22,
        "failed": 23,
        "repeat": 24,
        "the": 25,
        "run": 26,
        "before": 27,
        "interpreting": 28,
        "results": 29,
    }
    tokenizer_impl = Tokenizer(WordLevel(vocab=vocab, unk_token="<unk>"))
    tokenizer_impl.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=tokenizer_impl,
        bos_token="<bos>",
        eos_token="<eos>",
        unk_token="<unk>",
        pad_token="<pad>",
        chat_template=CHAT_TEMPLATE,
    )
    tokenizer.save_pretrained(model_dir)
    return model_dir


def _records() -> list[dict]:
    return [
        {
            "id": "clinical-1",
            "group_id": "person-1",
            "source_ids": ["local-clinical"],
            "split": "train",
            "messages": [
                {"role": "user", "content": "patient reports fever culture pending"},
                {
                    "role": "assistant",
                    "content": "state uncertainty and seek urgent care if breathing worsens",
                },
            ],
        },
        {
            "id": "biotech-1",
            "group_id": "assay-1",
            "source_ids": ["local-biotech"],
            "split": "train",
            "messages": [
                {"role": "user", "content": "assay control failed"},
                {
                    "role": "assistant",
                    "content": "repeat the run before interpreting results",
                },
            ],
        },
        {
            "id": "held-out",
            "group_id": "person-2",
            "source_ids": ["local-clinical"],
            "split": "test",
            "messages": [
                {"role": "user", "content": "patient reports fever"},
                {"role": "assistant", "content": "seek care"},
            ],
        },
    ]


def _settings(max_steps: int) -> dict:
    return {
        "device": "cpu",
        "max_steps": max_steps,
        "sequence_length": 64,
        "rank": 2,
        "alpha": 4,
        "learning_rate": 0.01,
        "seed": 7,
    }


def _lineage() -> dict:
    return {
        "model": {"sha256": "prepared-model-digest"},
        "snapshot": {"sha256": "private-snapshot-digest"},
    }


def test_completion_encoding_masks_prompt_and_keeps_native_answer_tokens(
    tiny_model_dir: Path,
) -> None:
    tokenizer = PreTrainedTokenizerFast.from_pretrained(
        tiny_model_dir, local_files_only=True
    )
    messages = _records()[0]["messages"]
    prefix = tokenizer.apply_chat_template(
        messages[:-1], tokenize=True, add_generation_prompt=True
    )["input_ids"]
    full = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=False
    )["input_ids"]

    encoded = _encode_completion(tokenizer, messages, sequence_length=64)

    assert encoded["input_ids"].tolist() == full
    assert encoded["labels"][: len(prefix)].tolist() == [-100] * len(prefix)
    assert encoded["labels"][len(prefix) :].tolist() == full[len(prefix) :]


def test_attention_target_discovery_allows_gemma4_shared_key_value_projection() -> None:
    config = Gemma4TextConfig(
        vocab_size=32,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        head_dim=8,
        max_position_embeddings=32,
        sliding_window=16,
        layer_types=["full_attention"],
        vocab_size_per_layer_input=32,
        hidden_size_per_layer_input=16,
        attention_k_eq_v=True,
    )
    config.per_layer_config = {}
    model = Gemma4ForCausalLM(config)

    targets = _actual_attention_targets(model)

    assert {name.rsplit(".", 1)[-1] for name in targets} == {
        "q_proj",
        "k_proj",
        "o_proj",
    }
    assert all(name.startswith("model.layers.") for name in targets)


def test_attention_target_discovery_rejects_missing_projection_in_any_layer() -> None:
    config = Gemma4TextConfig(
        vocab_size=32,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=2,
        num_key_value_heads=1,
        head_dim=8,
        max_position_embeddings=32,
        sliding_window=16,
        layer_types=["full_attention", "full_attention"],
        vocab_size_per_layer_input=32,
        hidden_size_per_layer_input=16,
        attention_k_eq_v=False,
    )
    config.per_layer_config = {}
    model = Gemma4ForCausalLM(config)
    model.model.layers[1].self_attn.o_proj = torch.nn.Identity()

    with pytest.raises(TypeError, match=r"layer 1.*o_proj"):
        _actual_attention_targets(model)


def test_real_gemma4_lora_updates_adapter_preserves_base_and_resumes(
    tiny_model_dir: Path, tmp_path: Path
) -> None:
    run_dir = tmp_path / "private-run"
    first = run_training(tiny_model_dir, _records(), run_dir, _settings(1), _lineage())

    assert first["completed_steps"] == 1
    assert first["data_cursor"] == 1
    assert first["all_gradients_finite"] is True
    assert first["gradient_norms"] and first["gradient_norms"][0] > 0
    assert first["frozen_weights_unchanged"] is True
    assert all(".self_attn." in name for name in first["actual_targets"])
    assert {name.rsplit(".", 1)[-1] for name in first["actual_targets"]} == {
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
    }
    assert (run_dir / "adapter" / "adapter_model.safetensors").is_file()
    assert (run_dir / "optimizer.pt").is_file()
    assert (run_dir / "state.json").is_file()
    assert (run_dir.stat().st_mode & 0o077) == 0

    first_adapter = load_file(run_dir / "adapter" / "adapter_model.safetensors")
    assert any(
        torch.count_nonzero(value).item() > 0
        for name, value in first_adapter.items()
        if "lora_B" in name
    )

    resumed = run_training(
        tiny_model_dir,
        _records(),
        run_dir,
        _settings(2),
        _lineage(),
        resume=True,
    )

    assert resumed["completed_steps"] == 2
    assert resumed["data_cursor"] == 2
    assert resumed["resumed"] is True
    second_adapter = load_file(run_dir / "adapter" / "adapter_model.safetensors")
    assert any(
        not torch.equal(first_adapter[name], second_adapter[name])
        for name in first_adapter
    )

    source = AutoModelForCausalLM.from_pretrained(
        tiny_model_dir,
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.float32,
        attn_implementation="eager",
    )
    source_q = source.model.layers[0].self_attn.q_proj.weight.detach().clone()
    del source
    from peft import PeftModel

    trained = PeftModel.from_pretrained(
        AutoModelForCausalLM.from_pretrained(
            tiny_model_dir,
            local_files_only=True,
            trust_remote_code=False,
            dtype=torch.float32,
            attn_implementation="eager",
        ),
        run_dir / "adapter",
    )
    trained_q = trained.base_model.model.model.layers[
        0
    ].self_attn.q_proj.base_layer.weight.detach()
    assert torch.equal(source_q, trained_q)

    run_manifest = json.loads((run_dir / "run.json").read_text())
    assert run_manifest["lineage"] == _lineage()
    assert run_manifest["immutable_settings"]["rank"] == 2


@pytest.fixture()
def completed_run(tiny_model_dir: Path, tmp_path: Path) -> Path:
    run_dir = tmp_path / "completed-run"
    run_training(tiny_model_dir, _records(), run_dir, _settings(1), _lineage())
    return run_dir


def _latest_checkpoint(run_dir: Path) -> Path:
    state = json.loads((run_dir / "state.json").read_text())
    return run_dir / "checkpoints" / state["checkpoint"]


def test_resume_rejects_checkpoint_from_a_different_run(
    tiny_model_dir: Path, completed_run: Path
) -> None:
    checkpoint_state_path = _latest_checkpoint(completed_run) / "state.json"
    checkpoint_state = json.loads(checkpoint_state_path.read_text())
    checkpoint_state["run_identity"] = "foreign-run-identity"
    checkpoint_state_path.write_text(json.dumps(checkpoint_state))

    with pytest.raises(ValueError, match="checkpoint.*identity"):
        run_training(
            tiny_model_dir,
            _records(),
            completed_run,
            _settings(2),
            _lineage(),
            resume=True,
        )


def test_resume_rejects_pointer_metadata_that_differs_from_checkpoint(
    tiny_model_dir: Path, completed_run: Path
) -> None:
    pointer_path = completed_run / "state.json"
    pointer = json.loads(pointer_path.read_text())
    pointer["data_cursor"] += 1
    pointer_path.write_text(json.dumps(pointer))

    with pytest.raises(ValueError, match="pointer.*checkpoint"):
        run_training(
            tiny_model_dir,
            _records(),
            completed_run,
            _settings(2),
            _lineage(),
            resume=True,
        )


def test_resume_rejects_adapter_with_changed_attention_targets(
    tiny_model_dir: Path, completed_run: Path
) -> None:
    adapter_config_path = (
        _latest_checkpoint(completed_run) / "adapter" / "adapter_config.json"
    )
    adapter_config = json.loads(adapter_config_path.read_text())
    adapter_config["target_modules"] = ["model.layers.0.self_attn.q_proj"]
    adapter_config_path.write_text(json.dumps(adapter_config))

    with pytest.raises(ValueError, match="adapter.*targets"):
        run_training(
            tiny_model_dir,
            _records(),
            completed_run,
            _settings(2),
            _lineage(),
            resume=True,
        )


def test_resumed_training_matches_uninterrupted_training(
    tiny_model_dir: Path, tmp_path: Path
) -> None:
    continuous_dir = tmp_path / "continuous"
    resumed_dir = tmp_path / "resumed"
    continuous = run_training(
        tiny_model_dir, _records(), continuous_dir, _settings(2), _lineage()
    )
    run_training(tiny_model_dir, _records(), resumed_dir, _settings(1), _lineage())
    resumed = run_training(
        tiny_model_dir,
        _records(),
        resumed_dir,
        _settings(2),
        _lineage(),
        resume=True,
    )

    continuous_adapter = load_file(
        continuous_dir / "adapter" / "adapter_model.safetensors"
    )
    resumed_adapter = load_file(resumed_dir / "adapter" / "adapter_model.safetensors")
    assert continuous_adapter.keys() == resumed_adapter.keys()
    assert all(
        torch.equal(value, resumed_adapter[name])
        for name, value in continuous_adapter.items()
    )
    assert continuous["data_cursor"] == resumed["data_cursor"] == 2

    continuous_state = torch.load(
        continuous_dir / "optimizer.pt", map_location="cpu", weights_only=True
    )
    resumed_state = torch.load(
        resumed_dir / "optimizer.pt", map_location="cpu", weights_only=True
    )
    assert (
        continuous_state["optimizer"]["param_groups"]
        == resumed_state["optimizer"]["param_groups"]
    )
    assert (
        continuous_state["optimizer"]["state"].keys()
        == resumed_state["optimizer"]["state"].keys()
    )
    for parameter_id, expected in continuous_state["optimizer"]["state"].items():
        actual = resumed_state["optimizer"]["state"][parameter_id]
        assert expected.keys() == actual.keys()
        assert all(torch.equal(value, actual[name]) for name, value in expected.items())
    assert torch.equal(continuous_state["rng"]["cpu"], resumed_state["rng"]["cpu"])


@pytest.mark.parametrize(
    "change",
    [
        {"rank": 4},
        {"sequence_length": 32},
        {"learning_rate": 0.001},
        {"gradient_accumulation_steps": 2},
    ],
)
def test_resume_rejects_changed_immutable_settings(
    tiny_model_dir: Path, completed_run: Path, change: dict
) -> None:
    settings = _settings(2)
    settings.update(change)

    with pytest.raises(ValueError, match="settings.*do not match"):
        run_training(
            tiny_model_dir,
            _records(),
            completed_run,
            settings,
            _lineage(),
            resume=True,
        )


def test_resume_rejects_changed_lineage(
    tiny_model_dir: Path, completed_run: Path
) -> None:
    changed = copy.deepcopy(_lineage())
    changed["snapshot"]["sha256"] = "different-snapshot"

    with pytest.raises(ValueError, match="lineage.*does not match"):
        run_training(
            tiny_model_dir,
            _records(),
            completed_run,
            _settings(2),
            changed,
            resume=True,
        )


@pytest.mark.parametrize(
    "records, message",
    [
        ([], "no training records"),
        ([{**_records()[0], "split": "test"}], "no training records"),
        (
            [{**_records()[0], "messages": [{"role": "user", "content": "fever"}]}],
            "final assistant",
        ),
        (
            [
                {
                    **_records()[0],
                    "messages": [
                        {"role": "user", "content": "fever"},
                        {"role": "assistant", "content": "   "},
                    ],
                }
            ],
            "non-empty",
        ),
    ],
)
def test_invalid_training_records_are_rejected_before_model_loading(
    tmp_path: Path, records: list[dict], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        run_training(
            tmp_path / "missing-model",
            records,
            tmp_path / "run",
            _settings(1),
            _lineage(),
        )


def test_answer_truncated_entirely_away_is_rejected(tiny_model_dir: Path) -> None:
    tokenizer = PreTrainedTokenizerFast.from_pretrained(
        tiny_model_dir, local_files_only=True
    )
    messages = _records()[0]["messages"]
    prefix = tokenizer.apply_chat_template(
        messages[:-1], tokenize=True, add_generation_prompt=True
    )["input_ids"]

    with pytest.raises(ValueError, match="truncated away"):
        _encode_completion(tokenizer, messages, sequence_length=len(prefix))


def test_xpu_requires_an_allocated_job_before_model_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)

    with pytest.raises(RuntimeError, match="allocated.*SLURM"):
        run_training(
            tmp_path / "missing-model",
            _records(),
            tmp_path / "run",
            {**_settings(1), "device": "xpu"},
            _lineage(),
        )
