"""SH-7: the lighthouse daemon embeds through the shared embedder when one is set."""

import logging

import embeddings
import lighthouse_daemon


def _config(tmp_path):
    cfg = tmp_path / "daemon.toml"
    cfg.write_text('publishers = ["a"]\n', encoding="utf-8")
    return str(cfg)


def test_the_daemon_embeds_in_process_without_the_shared_embedder(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.delenv("ENGRAM_EMBEDDER_SOCKET", raising=False)
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    provider = object()
    made = []

    def create():
        made.append(1)
        return provider

    seen = []
    monkeypatch.setattr(embeddings, "create_embedding_provider", create)
    monkeypatch.setattr(
        lighthouse_daemon.PublisherDaemon,
        "serve_forever",
        lambda self: seen.append(self.embeddings),
    )
    with caplog.at_level(logging.WARNING, logger="engram.lighthouse_daemon"):
        code = lighthouse_daemon.main(["--config", _config(tmp_path)])
    assert code == 0
    assert made == [1]
    assert seen == [provider]
    assert "ENGRAM_EMBEDDER_SOCKET" in caplog.text
    assert "superyak-embedder.service" in caplog.text
    assert "loaded in this process" in caplog.text


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


def test_the_shared_embedder_path_logs_no_in_process_warning(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("ENGRAM_EMBEDDER_SOCKET", str(tmp_path / "e.sock"))
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setattr(
        lighthouse_daemon.PublisherDaemon, "serve_forever", lambda self: None
    )
    with caplog.at_level(logging.WARNING, logger="engram.lighthouse_daemon"):
        assert lighthouse_daemon.main(["--config", _config(tmp_path)]) == 0
    assert "loaded in this process" not in caplog.text
