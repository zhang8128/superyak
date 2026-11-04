"""engram/daemon.py has no authentication, and its /chat can run Claude Code, so it listens on loopback unless the
person names a host (the section 2 review of share-refuses-captured, note 10)."""
import daemon


def test_the_daemon_listens_on_loopback_by_default():
    assert daemon.parse_args([]).host == "127.0.0.1"


def test_a_named_host_is_kept_and_warned_about():
    assert daemon.parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"
    warning = daemon.exposure_warning("0.0.0.0", 7432)
    assert warning is not None and "no authentication" in warning and "0.0.0.0:7432" in warning


def test_loopback_hosts_carry_no_warning():
    for host in ("127.0.0.1", "localhost", "::1"):
        assert daemon.exposure_warning(host, 7432) is None
