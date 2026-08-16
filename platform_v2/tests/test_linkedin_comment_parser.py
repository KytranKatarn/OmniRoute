"""Tests for the LinkedIn own-comment parser + Chronicle mapping (#5644 slice 2).

Hermetic: no browser, no DB. The card fixtures in
`tests/fixtures/linkedin_own_comment_cards.json` are REAL cards captured from Terry's
/recent-activity/comments/ tab on 2026-08-16 with the long prose lines shortened — the
structure (marker order, chrome lines, timestamps, the two-comment card) is untouched,
because a synthetic fixture would only re-encode my assumptions about the markup.

The properties pinned here are the ones where a wrong answer looks exactly like a right
one: post text leaking into the comment, the two-comment collision, and a permalink built
from the wrong activity id.
"""

import json
import pathlib

import pytest

import services.chronicle_linkedin_source as L
from services.linkedin_comment_parser import (
    parse_own_comments,
    parse_parent_activity,
    post_url_for,
)

_FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "linkedin_own_comment_cards.json").read_text())


# ---------------- parser ----------------
def test_single_card_yields_one_comment():
    got = parse_own_comments(_FX["single"]["raw_text"])
    assert len(got) == 1
    assert got[0]["text"]
    assert got[0]["age"]


def test_two_comment_card_yields_both_and_they_differ():
    """He commented TWICE on one post. Returning one (or the same one twice) silently
    loses half the sample — and is what a URN-keyed id would have done."""
    got = parse_own_comments(_FX["double"]["raw_text"])
    assert len(got) == 2
    assert got[0]["text"] != got[1]["text"]


def test_post_body_never_leaks_into_the_comment():
    """THE correctness property: the card renders the POST above his comment. If the
    parser starts too early the stored 'voice sample' is someone else's writing."""
    card = _FX["single"]["raw_text"]
    lines = [ln.strip() for ln in card.split("\n") if ln.strip()]
    post_author = lines[2]  # "<name> commented on this" is line 2
    text = parse_own_comments(card)[0]["text"]
    assert post_author not in text
    assert "commented on this" not in text
    assert "Feed post number" not in text


def test_chrome_and_counters_are_stripped():
    text = parse_own_comments(_FX["single"]["raw_text"])[0]["text"]
    for junk in ("Like", "Reply", "Load more comments", "impressions", "• You"):
        assert junk not in text


def test_missing_self_marker_returns_empty_not_a_guess():
    assert parse_own_comments("Feed post number 1\nSomeone Else\nA post body\nLike\nComment") == []
    assert parse_own_comments("") == []
    assert parse_own_comments(None) == []


def test_header_without_timestamp_is_skipped_rather_than_guessed():
    """No timestamp => the card shape changed; inventing a body start would capture his
    headline as his comment."""
    card = "Terry Caetano\n   • You\nFounder, Kytran Empowerment\nnot-a-timestamp\nbody text\nLike"
    assert parse_own_comments(card) == []


def test_truncation_is_reported():
    card = "Terry Caetano\n   • You\nFounder\n3h\nThis is the visible part of a long comment\n" "…more\nLike\nReply"
    got = parse_own_comments(card)
    assert len(got) == 1
    assert got[0]["truncated"] is True
    assert "…more" not in got[0]["text"]


# ---------------- permalink derivation ----------------
def test_parent_activity_comes_from_inside_the_urn():
    """The card's own data-urn is the 'X commented on this' wrapper and mismatched the
    real parent on 5/5 measured cards — building the link from it points at the wrong post."""
    urn = "urn:li:comment:(activity:7494433315593027584,7494732556052119552)"
    assert parse_parent_activity(urn) == "7494433315593027584"
    assert post_url_for(urn) == ("https://www.linkedin.com/feed/update/urn:li:activity:7494433315593027584/")


def test_bare_comment_urn_has_no_derivable_post():
    assert parse_parent_activity("urn:li:comment:12345") is None
    assert post_url_for("urn:li:comment:12345") is None
    assert post_url_for("") is None


def test_fixture_urn_parses():
    assert parse_parent_activity(_FX["single"]["comment_urn"])


# ---------------- Chronicle mapping ----------------
def test_two_comments_sharing_one_urn_get_DIFFERENT_message_ids():
    """The collision that a URN-keyed message_id would cause: ingest_source dedups on
    message_id, so the second comment would be silently dropped as a duplicate."""
    urn = "urn:li:comment:(activity:111,222)"
    a = L._map_own_comment({"text": "first comment", "age": "3h"}, urn, "http://p")
    b = L._map_own_comment({"text": "a different second comment", "age": "4h"}, urn, "http://p")
    assert a["message_id"] != b["message_id"]


def test_same_comment_recaptured_is_idempotent():
    urn = "urn:li:comment:(activity:111,222)"
    a = L._map_own_comment({"text": "same words", "age": "3h"}, urn, "http://p")
    b = L._map_own_comment({"text": "same  words", "age": "9h"}, urn, "http://p")  # whitespace/age noise
    assert a["message_id"] == b["message_id"]


def test_mapped_item_shape_and_truncation_note():
    urn = "urn:li:comment:(activity:111,222)"
    it = L._map_own_comment({"text": "hello", "age": "3h", "truncated": True}, urn, "http://p")
    assert it["folder"] == "linkedin/comments_own"
    assert it["from_addr"] == "Terry Caetano"
    assert "On: http://p" in it["body_text"]
    assert "truncated by LinkedIn" in it["body_text"]
    assert it["sent_at"] is not None


def test_approx_sent_at_units():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    assert L._approx_sent_at("3h", now=now) == now - timedelta(hours=3)
    assert L._approx_sent_at("2d", now=now) == now - timedelta(days=2)
    assert L._approx_sent_at("1w", now=now) == now - timedelta(weeks=1)
    # Unparseable stays None rather than defaulting to "now", which would silently claim
    # every old comment was written today.
    assert L._approx_sent_at("just now", now=now) is None
    assert L._approx_sent_at(None, now=now) is None


# ---------------- orchestrator ----------------
def _wire(monkeypatch, capture, agent_id=377):
    calls = {}

    def fake_ingest(kind, account_id, items, **kw):
        calls["items"] = items
        return {"import_id": 17, "inserted": len(items), "skipped": 0}

    monkeypatch.setattr(L, "_fetch_profile_url", lambda a: "http://li/in/terry")
    monkeypatch.setattr(L, "_capture_own_comments", lambda a, u, lim: capture)
    monkeypatch.setattr(L, "ingest_source", fake_ingest)
    monkeypatch.setattr("services.signal_accounts.require_browser_id", lambda k: agent_id, raising=False)
    return calls


def test_ingest_maps_every_comment_on_every_card(monkeypatch):
    calls = _wire(
        monkeypatch,
        {
            "success": True,
            "expanded": 5,
            "items": [
                {"comment_urn": _FX["single"]["comment_urn"], "raw_text": _FX["single"]["raw_text"]},
                {"comment_urn": _FX["double"]["comment_urn"], "raw_text": _FX["double"]["raw_text"]},
            ],
        },
    )
    res = L.run_own_comments_ingest()
    assert res["status"] == "ok"
    assert res["cards"] == 2
    assert res["comments"] == 3  # 1 + 2 — the second card carries two
    assert len({i["message_id"] for i in calls["items"]}) == 3


def test_failed_capture_ingests_nothing(monkeypatch):
    calls = _wire(monkeypatch, {"success": False, "result": "auth_wall"})
    res = L.run_own_comments_ingest()
    assert res["status"] == "capture_failed"
    assert res["inserted"] == 0
    assert "items" not in calls


def test_no_comments_reports_diagnostics_not_a_bare_zero(monkeypatch):
    calls = _wire(monkeypatch, {"success": True, "items": [], "strategy": "none", "containers_seen": 0})
    res = L.run_own_comments_ingest()
    assert res["status"] == "no_comments"
    assert res["strategy"] == "none"
    assert "items" not in calls


def test_unknown_account_raises_rather_than_defaulting(monkeypatch):
    from services.signal_accounts import UnknownAccountError

    monkeypatch.setattr(L, "_fetch_profile_url", lambda a: "http://li/in/x")
    monkeypatch.setattr(L, "_capture_own_comments", lambda a, u, lim: {"success": True, "items": []})

    def boom(key):
        raise UnknownAccountError(f"no such account {key!r}")

    monkeypatch.setattr("services.signal_accounts.require_browser_id", boom, raising=False)
    with pytest.raises(UnknownAccountError):
        L.run_own_comments_ingest(account_key="nope")
