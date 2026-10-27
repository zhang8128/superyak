"""``imprint.py use``: runs once, always with ``--lane``, and records how it ended (store-copy spec I 12, D41, D42)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import imprint
from imprint import USE_ID, use
from tests.imprint_support import (STUB_EXIT_1, STUB_EXIT_3, STUB_KILLED, STUB_OK, STUB_PRINTS_ARGV, STUB_PRINTS_ENV,
                                   admitted_imprint, must_not_be_called, raise_, recording_replace, report_exists,
                                   result_of, uses_dir, uses_dirs, with_allow)

ENGRAM = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("bad", ["C0A8F5E2-0000-4000-8000-000000000000", "c0a8f5e2-0000-1000-8000-000000000000", "x", ""])
def test_a_use_id_must_be_a_lowercase_uuid4(tmp_path, bad):
    root, iid_ = admitted_imprint(tmp_path)
    assert use(iid_, bad, root=root, trails_cmd=STUB_OK) == 2 and not uses_dirs(root, iid_)


def test_a_use_runs_once(tmp_path):
    root, iid_, use_id = with_allow(tmp_path)
    assert use(iid_, use_id, root=root, trails_cmd=STUB_OK) == 0
    assert use(iid_, use_id, root=root, trails_cmd=STUB_OK) == 2              # its directory exists


def test_report_then_result_each_atomic(tmp_path, monkeypatch):
    root, iid_, use_id = with_allow(tmp_path)
    order = []
    monkeypatch.setattr(imprint.os, "replace", recording_replace(order))
    use(iid_, use_id, root=root, trails_cmd=STUB_OK)
    assert [Path(dst).name for _, dst in order] == ["report.json", "result.json"]
    result = json.loads(result_of(root, iid_, use_id))
    assert result | {"ended_at": 0} == {"kind": "imprint-use-result", "use_id": use_id, "exit": 0, "error": None,
                                        "report": True, "ended_at": 0}


def test_lane_is_filled_from_a_one_lane_scope_and_refused_for_two(tmp_path):
    root, iid_, use_id = with_allow(tmp_path, lanes=["work"])
    use(iid_, use_id, root=root, trails_cmd=STUB_PRINTS_ARGV)
    argv = json.loads((uses_dir(root, iid_, use_id) / "report.json").read_text())
    assert argv[argv.index("--lane") + 1] == "work" and argv[argv.index("--deadline") + 1] == "1740"
    assert argv == [str(root / iid_ / "imprint.db"), "--evaluate", "--lane", "work", "--seed",
                    str(int(use_id[:8], 16)), "--deadline", "1740", "--json", "--imprint-use", use_id]
    root2, iid2, use2 = with_allow(tmp_path / "two", lanes=["personal", "work"])
    use(iid2, use2, root=root2, trails_cmd=[sys.executable, "-c", "raise SystemExit(99)"])
    assert json.loads(result_of(root2, iid2, use2))["error"] == "ValueError"
    assert json.loads(result_of(root2, iid2, use2))["exit"] is None and not report_exists(root2, iid2, use2)


def test_failures_name_a_class_never_a_message(tmp_path, monkeypatch):
    root, iid_, use_id = with_allow(tmp_path)
    monkeypatch.setattr(imprint, "_run_trails", raise_(OSError("/home/sam/secret path")))
    use(iid_, use_id, root=root, trails_cmd=STUB_OK)
    text = result_of(root, iid_, use_id)
    assert json.loads(text)["error"] == "OSError" and "secret" not in text


def test_exit_statuses_and_signals(tmp_path):
    for stub, exit_, report in ((STUB_EXIT_3, 3, False), (STUB_KILLED, -9, False), (STUB_EXIT_1, 1, False)):
        root, iid_, use_id = with_allow(tmp_path / str(exit_))
        use(iid_, use_id, root=root, trails_cmd=stub)
        assert (json.loads(result_of(root, iid_, use_id))["exit"], report_exists(root, iid_, use_id)) == (exit_, report)


def test_a_tombstone_or_a_passed_end_refuses_before_the_directory(tmp_path):
    for fault in ("tombstone", "ended", "no_allow_file"):
        root, iid_, use_id = with_allow(tmp_path / fault, fault=fault)
        assert use(iid_, use_id, root=root, trails_cmd=STUB_OK) == 2 and not uses_dir(root, iid_, use_id).exists()


def test_the_child_gets_the_scratch_directory_and_the_parent_no_numpy(tmp_path):
    root, iid_, use_id = with_allow(tmp_path)
    assert use(iid_, use_id, root=root, trails_cmd=STUB_PRINTS_ENV) == 0
    env = json.loads((uses_dir(root, iid_, use_id) / "report.json").read_text())
    scratch = str(root / f"{iid_}.state" / "scratch")
    assert env["SQLITE_TMPDIR"] == env["TMPDIR"] == scratch and env["exists"] is True
    assert not (root / f"{iid_}.state" / "scratch").exists()
    assert "numpy" not in subprocess.run([sys.executable, "-c", "import imprint, sys; print(sorted(sys.modules))"],
                                         capture_output=True, text=True, cwd=ENGRAM).stdout


def test_the_use_id_pattern_is_a_uuid4():
    assert USE_ID.fullmatch("c0a8f5e2-0000-4000-8000-000000000000") and not USE_ID.fullmatch("c0a8f5e2-0000-4000-8000-000000000000\n")


def test_the_uses_directory_is_private_and_its_parents_are_never_made(tmp_path):
    root, iid_, use_id = with_allow(tmp_path)
    use(iid_, use_id, root=root, trails_cmd=STUB_OK)
    assert uses_dir(root, iid_, use_id).stat().st_mode & 0o777 == 0o700
    root2, iid2, use2 = with_allow(tmp_path / "gone")
    (root2 / f"{iid2}.state" / "uses" / f"{use2}.allow.json").unlink()
    (root2 / f"{iid2}.state" / "uses").rmdir()
    assert use(iid2, use2, root=root2, trails_cmd=STUB_OK) == 2 and not (root2 / f"{iid2}.state" / "uses").exists()


def test_the_cli_refuses_a_bad_use_id(tmp_path, capsys):
    root, iid_, _ = with_allow(tmp_path)
    assert imprint.main(["use", "--id", iid_, "--use-id", "x", "--imprints-dir", str(root)]) == 2
