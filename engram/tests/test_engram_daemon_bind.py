"""engram/daemon.py has no authentication: anyone who reaches it can read and write memories and, unless --no-claude,
run Claude Code with --permission-mode auto. So it listens on loopback unless the person names a host (the section 2
review of share-refuses-captured, note 10, and the daemon branch's own review)."""
import daemon


def test_the_daemon_listens_on_loopback_by_default():
    assert daemon.parse_args([]).host == "127.0.0.1"


def test_a_named_host_is_kept_and_its_warning_names_every_exposure():
    assert daemon.parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"
    warning = daemon.exposure_warning("0.0.0.0", 7432)
    assert "no authentication" in warning and "0.0.0.0:7432" in warning
    assert "read and write your memories" in warning and "--permission-mode auto" in warning


def test_loopback_hosts_carry_no_warning():
    for host in ("127.0.0.1", "localhost"):
        assert daemon.exposure_warning(host, 7432) is None


class _Stop(Exception):
    pass


def _bound(monkeypatch, argv):
    """What main() hands HTTPServer, with the agent and the server faked so nothing listens or loads."""
    seen = {}

    class Agent:
        def __init__(self, **kwargs):
            pass

        def status(self):
            return {"model": "m", "session_id": "s", "episodes": 0, "core": 0, "semantics": 0, "instincts": 0,
                    "claude_enabled": False}

    class Server:
        def __init__(self, address, handler):
            seen["address"] = address

        def serve_forever(self):
            raise _Stop

        def server_close(self):
            pass

    monkeypatch.setattr(daemon, "LocalAgent", Agent)
    monkeypatch.setattr(daemon, "HTTPServer", Server)
    monkeypatch.setattr(daemon.sys, "argv", ["daemon.py", *argv])
    try:
        daemon.main()
    except _Stop:
        pass
    return seen["address"]


def test_main_binds_loopback_by_default_and_the_named_host_otherwise(monkeypatch, capsys):
    assert _bound(monkeypatch, []) == ("127.0.0.1", daemon.DEFAULT_PORT)
    assert "network:" not in capsys.readouterr().out
    assert _bound(monkeypatch, ["--host", "100.64.0.9", "--port", "7999"]) == ("100.64.0.9", 7999)
    out = capsys.readouterr().out
    assert "network:  http://100.64.0.9:7999" in out and "no authentication" in out
