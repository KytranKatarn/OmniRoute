"""Task #4553 — quality scorer routes through DHQ cluster dispatch, not a
direct model call, and parses the response robustly.

The old scorer made a direct Ollama call with a 120s timeout that failed
~100% of the time under hub-GPU contention, permanently marking every entry
'error'. It now goes through services.cluster_dispatch.queued_dispatch_text
(full cluster, queue-and-wait). These tests pin the new contract by mocking
that helper — no network, no DB (save_to_db=False).
"""

from unittest.mock import patch

from services.quality_scoring_service import score_entry

_GOOD = '{"relevance":0.8,"accuracy":0.7,"actionability":0.6,"uniqueness":0.5,"reason":"specific and actionable"}'
_LOW = '{"relevance":0.1,"accuracy":0.1,"actionability":0.1,"uniqueness":0.1,"reason":"generic filler"}'
# Unterminated reason string -> json.loads fails -> regex fallback extracts the 4 numbers
_MALFORMED = '{"relevance":0.9,"accuracy":0.8,"actionability":0.7,"uniqueness":0.6,"reason":"oops}'


def test_score_entry_uses_cluster_dispatch_and_parses_valid_json():
    with patch("services.cluster_dispatch.queued_dispatch_text", return_value=_GOOD) as mock_dispatch:
        result = score_entry(1, "Title", "Some content", "vault_note", save_to_db=False)
    # It must route through the cluster helper — never a direct model call.
    assert mock_dispatch.called
    _, kwargs = mock_dispatch.call_args
    assert kwargs.get("capability") == "classify"
    assert kwargs.get("json_mode") is True
    assert kwargs.get("module_id") == "quality_scorer"
    # 0.8*.30 + 0.7*.25 + 0.6*.25 + 0.5*.20 = 0.665 -> round() = 0.66 (IEEE754),
    # >= 0.5 -> scored
    assert result is not None
    assert result["review_status"] == "scored"
    assert result["quality_score"] == 0.66


def test_score_entry_low_scores_rejected():
    with patch("services.cluster_dispatch.queued_dispatch_text", return_value=_LOW):
        result = score_entry(2, "T", "C", "conversation_memory", save_to_db=False)
    assert result is not None
    assert result["quality_score"] < 0.3
    assert result["review_status"] == "rejected"


def test_score_entry_none_when_dispatch_returns_none():
    # Transient (busy cluster / poll timeout) OR hard failure -> None so the
    # job's retry counter decides; it must NOT fabricate a score.
    with patch("services.cluster_dispatch.queued_dispatch_text", return_value=None):
        assert score_entry(3, "T", "C", "vault_note", save_to_db=False) is None


def test_score_entry_malformed_json_falls_back_to_regex():
    with patch("services.cluster_dispatch.queued_dispatch_text", return_value=_MALFORMED):
        result = score_entry(4, "T", "C", "vault_note", save_to_db=False)
    assert result is not None
    # Numbers recovered by the regex fallback (0.9/0.8/0.7/0.6)
    assert result["dimensions"]["relevance"] == 0.9
    assert result["reason"] == "parsed from malformed JSON"


def test_score_entry_empty_response_is_none():
    with patch("services.cluster_dispatch.queued_dispatch_text", return_value=""):
        assert score_entry(5, "T", "C", "vault_note", save_to_db=False) is None
