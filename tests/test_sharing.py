import pytest

from sharing import AUDIENCE_COMMONS, ShareRecord, validate_audience


def test_commons_and_group_audiences_accepted():
    assert validate_audience(AUDIENCE_COMMONS) == "commons"
    assert validate_audience("group:engram-system") == "group:engram-system"
    assert validate_audience("group:a") == "group:a"


@pytest.mark.parametrize("bad", [
    "", "COMMONS", "commons ", "group:", "group:Engram", "group:-x", "group:x_y",
    "group:" + "a" * 65, "world", "group:a:b", None, 3,
])
def test_bad_audiences_fail_closed(bad):
    with pytest.raises((ValueError, TypeError)):
        validate_audience(bad)


def test_share_record_is_frozen_and_complete():
    rec = ShareRecord(share_id="s", memory_id="m", source_instance="engram", source_id="e",
                      layer="episode", audience="commons", reason="why",
                      content_digest="d", shared_at="2026-09-02T00:00:00Z")
    assert rec.layer == "episode"
    with pytest.raises(Exception):
        rec.audience = "group:x"
