"""SH-7: the lighthouse daemon embeds through the shared embedder only."""

import logging

import embeddings
import lighthouse_daemon


def _config(tmp_path):
    cfg = tmp_path / "daemon.toml"
    cfg.write_text('publishers = ["a"]\n', encoding="utf-8")
    return str(cfg)


def test_the_daemon_refuses_to_start_without_the_shared_embedder(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.delenv("ENGRAM_EMBEDDER_SOCKET", raising=False)
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    built = []

    class Stub:
        def __init__(self, *a, **k):
            built.append(1)

    monkeypatch.setattr(embeddings, "NomicEmbedProvider", Stub)
    monkeypatch.setattr(
        lighthouse_daemon.PublisherDaemon, "serve_forever", lambda self: None
    )
    with caplog.at_level(logging.ERROR, logger="engram.lighthouse_daemon"):
        code = lighthouse_daemon.main(["--config", _config(tmp_path)])
    assert code != 0
    assert "ENGRAM_EMBEDDER_SOCKET" in caplog.text
    assert built == []


def test_the_daemon_uses_the_shared_embedder(tmp_path, monkeypatch):
    sock = str(tmp_path / "embedder.sock")
    monkeypatch.setenv("ENGRAM_EMBEDDER_SOCKET", sock)
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    seen = []

    def serve(self):
        seen.append(self.embeddings)

    monkeypatch.setattr(lighthouse_daemon.PublisherDaemon, "serve_forever", serve)
    assert lighthouse_daemon.main(["--config", _config(tmp_path)]) == 0
    assert isinstance(seen[0], embeddings.RemoteEmbedProvider)
    assert seen[0]._socket_path == sock
