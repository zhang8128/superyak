"""Task 45: verified station receipts become the owner's use rows; the use list shows the copy (I 12, YN2, YN6)."""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from imprint import import_receipts
from imprint_copies import copies_held
from permission_uses import Uses
from tests.imprint_support import (IMPRINT_ID, T, add_verified, first_ref, imported_home, imported_rows, is_copy_subject,
                                   ledger_home, render, render_list, saved_receipts, shipped_refs, state_of,
                                   subject_pairs, subject_rows)

ENGRAM = Path(__file__).resolve().parent.parent


def test_memory_rows_are_per_action_purpose_and_batch(tmp_path):
    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, memories=1300, route=False, receipts=["admitted"])
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    rows = imported_rows(led_home)
    assert Counter((r["action"], r["purpose"]) for r in rows) == {(a, "calibration"): 3 for a in ("imprint", "read", "recall")}
    assert sum(json.loads(r["returned"])["count"] for r in rows if r["action"] == "read") == 1300
    assert subject_rows(led_home, action="read") == 1300


def test_carried_co_subjects_get_their_own_use_subjects_rows(tmp_path):
    led_home = ledger_home(tmp_path, owner="andy")
    home = imported_home(tmp_path, owner="andy", memories=3, receipts=["admitted"], subjects={0: ["person:jenn", "person:lee"]})
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    assert subject_rows(led_home, action="read") == 5
    assert {s for s, ref in subject_pairs(led_home, action="read") if s != "person:andy"} == {"person:jenn", "person:lee"}


def test_roads_and_trails_rows_split_at_100000_and_are_null_without_a_count(tmp_path):
    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, route=True, receipts=[("admitted", 150_000)])
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    counted = [r for r in imported_rows(led_home) if r["purpose"] == "trail-evaluation" and r["object"] is None and is_copy_subject(r)]
    assert sorted(json.loads(r["returned"])["count"] for r in counted if r["action"] == "imprint") == [50_000, 100_000]
    for receipt in (("denied", None, "end"), ("failed", None, "end")):
        lh, h = ledger_home(tmp_path / receipt[0]), imported_home(tmp_path / receipt[0], route=True, receipts=[receipt])
        import_receipts(IMPRINT_ID, home=h, engram_home=lh)
        assert {r["returned"] for r in imported_rows(lh) if is_copy_subject(r)} == {None}


def test_the_use_list_finds_an_imprint_use_by_a_shipped_ref_and_shows_the_copy(tmp_path):
    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, memories=10, receipts=["admitted"])
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    uses = Uses.open(led_home)
    try:
        listed = uses.owner_list(state_of(led_home), obj=first_ref(home), copies=copies_held(home))
    finally:
        uses.close()
    assert listed.rows and "copy held at Deep Space 9 (imprint c0a8), deletion not confirmed" in render(listed)
    add_verified(home, "deleted")
    assert "deletion not confirmed" not in render_list(led_home, home)


def test_importing_twice_adds_nothing_and_no_station_receipt_names_a_memory(tmp_path):
    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, memories=10, receipts=["admitted", "use-finished"])
    first = import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    assert import_receipts(IMPRINT_ID, home=home, engram_home=led_home) == 0 and first > 0
    assert not any(ref in json.dumps(r) for r in saved_receipts(home) for ref in shipped_refs(home))


def test_the_copies_module_loads_no_numpy():
    done = subprocess.run([sys.executable, "-c", "import imprint_copies, sys; print('numpy' in sys.modules, 'imprint' in sys.modules)"],
                          cwd=ENGRAM, capture_output=True, text=True, check=True)
    assert done.stdout.split() == ["False", "False"]


def test_no_ledger_means_nothing_is_done(tmp_path):
    home = imported_home(tmp_path, receipts=["admitted"])
    assert import_receipts(IMPRINT_ID, home=home, engram_home=tmp_path / "none") == 0
    assert not (tmp_path / "none").exists()


def test_unverified_receipts_and_failures_without_a_term_are_not_imported(tmp_path):
    led_home = ledger_home(tmp_path)
    home = imported_home(tmp_path, receipts=["failed", "denied"])
    add_verified(home, "admitted", verified=False)
    assert import_receipts(IMPRINT_ID, home=home, engram_home=led_home) == 0


def test_a_refusal_is_a_refused_row_with_its_code_and_the_ends_are_the_effective_end(tmp_path):
    led_home = ledger_home(tmp_path)
    home = imported_home(tmp_path, route=True, receipts=[("admitted", 10), ("refused", 10, "end")])
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    refused = [r for r in imported_rows(led_home) if not r["allowed"]]
    assert refused and all(json.loads(r["refusal"]) == {"code": "EXPIRED", "layer": None, "action": r["action"]} for r in refused)
    assert {r["until"] for r in imported_rows(led_home)} == {T("2027-01-30")}
    assert all(r["agent"] == "agent:station-imprints" and r["object"] is None and r["horizon"] is None
               and r["copy"] == f"imprint:{'5' * 64}/{IMPRINT_ID}" for r in imported_rows(led_home))


def test_the_command_imports_and_says_how_many(tmp_path, capsys):
    import imprint

    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, receipts=["admitted"])
    assert imprint.main(["import-receipts", "--id", IMPRINT_ID[:4], "--superyak-home", str(home),
                         "--engram-home", str(led_home)]) == 0
    assert "3 uses imported" in capsys.readouterr().out


def test_the_uses_command_shows_the_copy_first_and_imports_nothing_it_does_not_hold(tmp_path, monkeypatch, capsys):
    import permission_cli

    led_home, home = ledger_home(tmp_path), imported_home(tmp_path, memories=4, receipts=["admitted"])
    import_receipts(IMPRINT_ID, home=home, engram_home=led_home)
    monkeypatch.setenv("ENGRAM_HOME", str(led_home))
    monkeypatch.setenv("SUPERYAK_HOME", str(home))
    assert permission_cli.main(["uses"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "copy held at Deep Space 9 (imprint c0a8), deletion not confirmed"
    assert permission_cli.main(["uses", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["copies"][0]["imprint_id"] == IMPRINT_ID
    monkeypatch.setenv("SUPERYAK_HOME", str(tmp_path / "nothing-here"))
    assert permission_cli.main(["uses", "--json"]) == 0
    assert json.loads(capsys.readouterr().out).get("copies") is None
