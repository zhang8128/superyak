"""Task 26: engram-permissions, the terminal yes, `init` and the registry commands (P 4.4, 7.6, 14; R12, R24)."""
import argparse

import pytest

import permission_cli
from permission_cli import NoTerminal, confirm, main
from permission_ledger import Ledger
from permissions import GluingReport
from tests.permissions_support import (CLI_M1 as M1, CLI_M1_CREATED_AT as M1_CREATED_AT, T, cli_home,
                                       cli_home_with_store, fake_tty, ledger_bytes, log_rows)

HOME = "place:home/andy"


def option_names(parser):
    names = set()
    for action in parser._actions:
        names.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                names |= option_names(sub)
    return names


def registry_argvs():
    """One command for every registry subcommand that writes, in an order each one can run."""
    return [
        ["person", "add", "jenn"],
        ["person", "add", "amy"],
        ["person", "retire", "amy"],
        ["place", "register", "place:la-county", "--name", "LA County"],
        ["place", "register", "place:la-county/parks", "--parent", "place:la-county"],
        ["place", "register", "place:la-county/health", "--parent", "place:la-county"],
        ["place", "register", "place:la-county/old", "--parent", "place:la-county"],
        ["place", "parent", "place:la-county/parks", "place:la-county/health"],
        ["place", "steward", "add", "place:la-county/parks", "person:jenn"],
        ["place", "steward", "remove", "place:la-county/parks", "person:jenn"],
        ["place", "retire", "place:la-county/old"],
        ["agent", "add", "rio", "--acts-for", HOME],
        ["agent", "place", "rio", HOME],
        ["agent", "unplace", "rio", HOME],
        ["store", "add", "other-store", "--name", "other", "--place", HOME],
        ["group", "set", "group:crew", "agent:rio"],
        ["collection", "add", "collection:andy/c", M1],
        ["collection", "remove", "collection:andy/c", M1],
        ["subject", "add", M1, "person:jenn"],
        ["subject", "remove", M1, "person:jenn"],
    ]


def latest_lane_note_row(home, ref):
    led = Ledger.open(home)
    try:
        note = led.state().lane_notes[ref][-1]
        return note.lane, note.at
    finally:
        led.close()


def main_in(root, argv, monkeypatch):
    monkeypatch.setenv("ENGRAM_HOME", str(root))
    return main(argv)


def test_u18_refused_without_a_terminal(cli_home, monkeypatch, capsys):
    monkeypatch.setattr(permission_cli, "TTY", str(cli_home / "no-such-tty"))
    before = ledger_bytes(cli_home)
    assert main(["person", "add", "jenn"]) == 3 and ledger_bytes(cli_home) == before


def test_u18_a_wrong_code_writes_nothing(cli_home, fake_tty):
    fake_tty.answer("wrong1")
    before = ledger_bytes(cli_home)
    assert main(["person", "add", "jenn"]) == 3 and ledger_bytes(cli_home) == before


def test_no_answer_is_a_wrong_code_and_writes_nothing(cli_home, fake_tty, monkeypatch):
    monkeypatch.setattr(permission_cli, "TTY_WAIT", 0.05)
    before = ledger_bytes(cli_home)
    assert main(["person", "add", "jenn"]) == 3 and ledger_bytes(cli_home) == before


def test_r12_a_usage_error_is_argparses_2_not_the_yes_code(cli_home, fake_tty):
    with pytest.raises(SystemExit) as exit_:
        main(["person", "add"])                       # the handle is missing
    assert exit_.value.code == 2


def test_r12_the_code_is_six_characters_from_the_alphabet():
    for _ in range(200):
        code = permission_cli._code()
        assert len(code) == 6 and set(code) <= set("abcdefghjkmnpqrstuvwxyz23456789")
    assert len({permission_cli._code() for _ in range(20)}) > 1


def test_confirm_prints_the_words_then_the_change_then_the_code(fake_tty, capsys):
    fake_tty.answer_the_printed_code()
    assert confirm("THE WORDS", "THE CHANGE") is True
    out = capsys.readouterr().out
    assert out.index("THE WORDS") < out.index("THE CHANGE") < out.index("code: " + fake_tty.code)


def test_confirm_raises_no_terminal_before_printing_anything(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(permission_cli, "TTY", str(tmp_path / "none"))
    with pytest.raises(NoTerminal):
        confirm("WORDS", "CHANGE")
    assert capsys.readouterr().out == ""


def test_confirm_reads_one_line_and_leaves_the_next(fake_tty):
    fake_tty.answer("nope")
    fake_tty.answer_the_printed_code()
    assert confirm("w", "c") is False
    assert confirm("w", "c") is True


def test_r24_init_names_the_login_as_owner_and_refuses_a_second_ledger(tmp_path, fake_tty, monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setattr(permission_cli, "_login_name", lambda: "andy")
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 0
    assert "Create a ledger owned by person:andy" in capsys.readouterr().out
    assert Ledger.open(tmp_path).meta()["owner"] == "person:andy"
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 1                                      # a ledger exists
    monkeypatch.setattr(permission_cli, "_login_name", lambda: "Andy Z")
    assert main_in(tmp_path / "other", ["init"], monkeypatch) == 1  # a login that is not a handle
    assert not (tmp_path / "other" / ".engram" / "permissions.db").exists()


def test_init_without_the_yes_makes_no_ledger(tmp_path, fake_tty, monkeypatch):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setattr(permission_cli, "_login_name", lambda: "andy")
    fake_tty.answer("wrong1")
    assert main(["init"]) == 3
    assert not (tmp_path / ".engram" / "permissions.db").exists()


def test_a_command_with_no_ledger_is_refused_and_says_to_run_init(tmp_path, fake_tty, monkeypatch, capsys):
    fake_tty.answer_the_printed_code()
    assert main_in(tmp_path, ["person", "add", "jenn"], monkeypatch) == 1
    assert "init" in capsys.readouterr().err


def test_u18_no_registry_command_acts_as_anyone_but_the_owner(cli_home_with_store, fake_tty):
    for argv in registry_argvs():
        fake_tty.answer_the_printed_code()
        assert main(argv) == 0, argv
    rows = [row for row in log_rows(cli_home_with_store) if row["channel"] == "terminal"]
    assert len(rows) > len(registry_argvs()) and {row["actor"] for row in rows} == {"person:andy"}
    assert not option_names(permission_cli.build_parser()) & {"--as", "--actor", "--person", "--by", "--owner"}


def test_every_registry_command_needs_the_yes(cli_home_with_store, fake_tty):
    for argv in registry_argvs():
        before = ledger_bytes(cli_home_with_store)
        fake_tty.answer("wrong1")
        assert main(argv) == 3 and ledger_bytes(cli_home_with_store) == before, argv
        fake_tty.answer_the_printed_code()
        assert main(argv) == 0, argv


def test_a_command_prints_its_words_and_the_whole_change_before_the_code(cli_home, fake_tty, capsys):
    capsys.readouterr()
    fake_tty.answer_the_printed_code()
    assert main(["place", "register", "place:la-county", "--name", "LA County"]) == 0
    out = capsys.readouterr().out
    assert out.index("Register place:la-county") < out.index("LA County") < out.index("code:")
    assert out.index("person:andy") < out.index("code:")           # the default steward is in the change


def test_a_rule_refusal_exits_1_names_the_rule_and_writes_nothing(cli_home, fake_tty, capsys):
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "jenn"]) == 0
    before = ledger_bytes(cli_home)
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "jenn"]) == 1 and ledger_bytes(cli_home) == before
    assert "already registered" in capsys.readouterr().err


def test_a_bad_id_is_refused_by_the_rule_not_a_traceback(cli_home, fake_tty, capsys):
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "Not A Handle"]) == 1
    assert "refused" in capsys.readouterr().err


def test_a_place_under_a_parent_the_owner_does_not_steward_waits_as_a_proposal(cli_home, fake_tty, capsys):
    for argv in (["person", "add", "jenn"],
                 ["place", "register", "place:co"],
                 ["place", "register", "place:co/mine", "--parent", "place:co"],
                 ["place", "register", "place:co/hers", "--parent", "place:co", "--steward", "person:jenn"]):
        fake_tty.answer_the_printed_code()
        assert main(argv) == 0
    capsys.readouterr()
    fake_tty.answer_the_printed_code()
    assert main(["place", "register", "place:co/joint", "--parent", "place:co/mine",
                 "--parent", "place:co/hers"]) == 0
    out = capsys.readouterr().out
    assert "proposal" in out and "p-" in out


def test_collection_add_passes_each_memorys_lane_and_created_at(cli_home_with_store, fake_tty):
    fake_tty.answer_the_printed_code()
    assert main(["collection", "add", "collection:andy/c", M1]) == 0
    assert latest_lane_note_row(cli_home_with_store, M1) == ("personal", M1_CREATED_AT)


def test_collection_add_shows_the_lane_it_read_before_the_yes(cli_home_with_store, fake_tty, capsys):
    capsys.readouterr()
    fake_tty.answer_the_printed_code()
    assert main(["collection", "add", "collection:andy/c", M1]) == 0
    out = capsys.readouterr().out
    assert out.index(M1) < out.index("personal") < out.index("code:")


def test_collection_add_of_a_memory_whose_store_is_not_here_warns_and_adds_it_without_a_lane(
        cli_home_with_store, fake_tty, capsys):
    capsys.readouterr()
    gone = "mem:elsewhere/episode/x1"
    fake_tty.answer_the_printed_code()
    assert main(["collection", "add", "collection:andy/c", gone]) == 0
    out = capsys.readouterr().out
    assert "no lane" in out and out.index("no lane") < out.index("code:")
    led = Ledger.open(cli_home_with_store)
    try:
        assert gone not in led.state().lane_notes
    finally:
        led.close()


def test_collection_remove_of_a_member_works_and_a_new_collection_is_made_by_add(cli_home_with_store, fake_tty):
    for argv in (["collection", "add", "collection:andy/c", M1], ["collection", "remove", "collection:andy/c", M1]):
        fake_tty.answer_the_printed_code()
        assert main(argv) == 0
    led = Ledger.open(cli_home_with_store)
    try:
        assert "collection:andy/c" in led.state().collections
    finally:
        led.close()


def test_store_add_registers_it_for_the_owner_with_defaults(cli_home, fake_tty):
    fake_tty.answer_the_printed_code()
    assert main(["store", "add", "s1"]) == 0
    row = Ledger.open(cli_home).store_row("s1")
    assert row["owner"] == "person:andy" and row["place"] == HOME and row["name"] == "s1"


def test_a_write_runs_the_sweep_and_a_refused_one_does_not(cli_home, fake_tty, monkeypatch):
    calls = []
    monkeypatch.setattr(permission_cli, "run_sweep", lambda led, now: calls.append(now))
    fake_tty.answer("wrong1")
    assert main(["person", "add", "jenn"]) == 3
    assert calls == []
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "jenn"]) == 0
    assert len(calls) == 1


def test_a_failing_sweep_never_changes_the_exit_code(cli_home, fake_tty, monkeypatch, capsys):
    from permission_ledger import Gate
    from tests.permissions_support import make_house

    def boom(*a, **k):
        raise RuntimeError("sweep broke")
    make_house(cli_home, "lighthouse")
    monkeypatch.setattr(permission_cli, "effective_gate", lambda *a, **k: Gate("shadow"))
    monkeypatch.setattr(permission_cli, "_sweep_house", boom)
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "jenn"]) == 0
    assert "sweep broke" in capsys.readouterr().err


def test_the_gluing_reports_that_notify_the_owner_are_printed(monkeypatch, capsys):
    mine = GluingReport("place:a", (), (), False, frozenset({"person:andy"}))
    theirs = GluingReport("place:b", (), (), False, frozenset({"person:jenn"}))
    monkeypatch.setattr(permission_cli, "disagreement_words", lambda state, report: f"WORDS for {report.place}")
    permission_cli._print_reports(object(), [mine, theirs], "person:andy")
    out = capsys.readouterr().out
    assert "WORDS for place:a" in out and "place:b" not in out


def test_times_take_a_date_or_rfc_3339_utc():
    assert permission_cli._when("2026-11-02") == T("2026-11-02")
    assert permission_cli._when("2026-11-02T10:30:00Z") == T("2026-11-02") + 10 * 3600 + 30 * 60
    for bad in ("2026-11-02T10:30:00+01:00", "tomorrow", "2026-13-01", ""):
        with pytest.raises(argparse.ArgumentTypeError):
            permission_cli._when(bad)
