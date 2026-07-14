from experiments.action_bias.records import append_jsonl, completed_ids


def test_append_jsonl_and_completed_ids_survive_partial_line(tmp_path):
    path = tmp_path / "runs.jsonl"
    append_jsonl(path, {"run_id": "a", "status": "completed"})
    with path.open("a") as f:
        f.write('{"run_id":"partial"')
    assert completed_ids(path) == {"a"}
