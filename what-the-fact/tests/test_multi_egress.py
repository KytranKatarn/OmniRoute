import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_detect_no_key_returns_error():
    import importlib
    import ingest.multi_egress as me

    orig_key = me._SCOUT_KEY
    me._SCOUT_KEY = ""
    try:
        result = me.detect_geographic_variation("https://example.com")
        assert "error" in result
        assert result["variation_detected"] is False
        assert result["hashes"] == []
    finally:
        me._SCOUT_KEY = orig_key


def test_detect_same_content_no_variation():
    from unittest.mock import patch
    import ingest.multi_egress as me

    with (
        patch.object(me, "_SCOUT_KEY", "test_key"),
        patch.object(me, "_submit_fetch", side_effect=[101, 102]),
        patch.object(me, "_poll_job") as mock_poll,
    ):
        mock_poll.return_value = {"status": "approved", "data": {"body": ["Same content"]}}
        result = me.detect_geographic_variation("https://example.com/article")

    assert result["variation_detected"] is False
    assert len(result["hashes"]) == 2
    assert result["hashes"][0] == result["hashes"][1]


def test_detect_different_content_variation():
    from unittest.mock import patch, call
    import ingest.multi_egress as me

    call_count = 0

    def varying_poll(job_id, **kwargs):
        nonlocal call_count
        call_count += 1
        body = ["Content A"] if call_count == 1 else ["Content B — different"]
        return {"status": "completed", "data": {"body": body}}

    with (
        patch.object(me, "_SCOUT_KEY", "test_key"),
        patch.object(me, "_submit_fetch", side_effect=[201, 202]),
        patch.object(me, "_poll_job", side_effect=varying_poll),
    ):
        result = me.detect_geographic_variation("https://example.com/article")

    assert result["variation_detected"] is True
    assert len(result["hashes"]) == 2
    assert result["hashes"][0] != result["hashes"][1]


def test_failed_poll_excluded_from_hashes():
    from unittest.mock import patch
    import ingest.multi_egress as me

    def mixed_poll(job_id, **kwargs):
        if job_id == 301:
            return {"status": "completed", "data": {"body": ["Some content"]}}
        return {"status": "failed"}

    with (
        patch.object(me, "_SCOUT_KEY", "test_key"),
        patch.object(me, "_submit_fetch", side_effect=[301, 302]),
        patch.object(me, "_poll_job", side_effect=mixed_poll),
    ):
        result = me.detect_geographic_variation("https://example.com/article")

    # Only one successful hash — variation requires 2 distinct hashes
    assert result["variation_detected"] is False
    assert len(result["hashes"]) == 1
    assert len(result["results"]) == 2
    statuses = {r["tier"]: r["status"] for r in result["results"]}
    assert statuses[1] == "ok"
    assert statuses[2] == "failed"
