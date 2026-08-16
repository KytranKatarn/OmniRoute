"""Hermetic tests for LinkedIn profile -> Chronicle capture (#5644, slice 1).

No DB, no browser sidecar: the pure mappers get canned dicts, and run_profile_ingest is
tested by monkeypatching _fetch_profile_url / _capture_profile / ingest_source +
require_browser_id. Mirrors the style of test_chronicle_linkedin_source.py.

The behaviours pinned here are the ones where a WRONG result would look identical to a
right one (ADR-027): a defaulted identity, a failed capture written as an empty snapshot,
and a re-capture that duplicates an unchanged profile.
"""

import pytest

import services.chronicle_linkedin_source as L

_FIELDS = {
    "success": True,
    "name": "Terry Caetano",
    "headline": "Founder, Kytran Empowerment",
    "location": "Toronto, Ontario, Canada",
    "about": "I build sovereign  Canadian civic AI.",
    "skills": ["Python", "Governance"],
    "experience": ["Founder", "Kytran Empowerment · Full-time"],
    "strategy": {"about": "anchor_id", "skills": "anchor_id", "experience": "anchor_id"},
}


# ---------------- pure mappers ----------------
def test_signature_ignores_volatile_chrome():
    """Follower counts / screenshots churn constantly; they must not mint a new snapshot."""
    a = dict(_FIELDS, connections="500+ connections", screenshot="/profiles/x.png")
    b = dict(_FIELDS, connections="501 connections", screenshot="/profiles/y.png")
    assert L._profile_signature(a) == L._profile_signature(b)


def test_signature_is_whitespace_stable():
    a = dict(_FIELDS, about="I build sovereign  Canadian civic AI.")
    b = dict(_FIELDS, about="I build sovereign Canadian civic AI.")
    assert L._profile_signature(a) == L._profile_signature(b)


def test_signature_changes_when_voice_changes():
    for mutated in (
        dict(_FIELDS, headline="Different headline"),
        dict(_FIELDS, about="Rewritten about section."),
        dict(_FIELDS, skills=["Python", "Governance", "Ethics"]),
        dict(_FIELDS, experience=["Founder"]),
    ):
        assert L._profile_signature(mutated) != L._profile_signature(_FIELDS)


def test_skill_order_ignored_but_experience_order_significant():
    """LinkedIn reorders skills by endorsements (noise); experience order IS the schema."""
    reordered_skills = dict(_FIELDS, skills=["Governance", "Python"])
    assert L._profile_signature(reordered_skills) == L._profile_signature(_FIELDS)

    reordered_exp = dict(_FIELDS, experience=["Kytran Empowerment · Full-time", "Founder"])
    assert L._profile_signature(reordered_exp) != L._profile_signature(_FIELDS)


def test_map_profile_item_shape():
    item = L._map_profile(_FIELDS, "http://li/in/terry")
    assert item["message_id"] == f"li:profile:{L._profile_signature(_FIELDS)}"
    assert item["from_addr"] == "Terry Caetano"
    assert item["folder"] == "linkedin/profile"
    assert item["has_attachments"] is False
    body = item["body_text"]
    assert "Founder, Kytran Empowerment" in body
    assert "sovereign" in body
    assert "- Python" in body
    assert "Profile: http://li/in/terry" in body


# ---------------- orchestrator ----------------
def _wire(monkeypatch, capture, url="http://li/in/terry", agent_id=377):
    calls = {}

    def fake_ingest(kind, account_id, items, **kw):
        calls["kind"] = kind
        calls["items"] = items
        return {"import_id": 17, "inserted": len(items), "skipped": 0}

    monkeypatch.setattr(L, "_fetch_profile_url", lambda a: url)
    monkeypatch.setattr(L, "_capture_profile", lambda a, u: capture)
    monkeypatch.setattr(L, "ingest_source", fake_ingest)
    monkeypatch.setattr("services.signal_accounts.require_browser_id", lambda k: agent_id, raising=False)
    return calls


def test_happy_path_ingests_one_item(monkeypatch):
    calls = _wire(monkeypatch, _FIELDS)
    res = L.run_profile_ingest()
    assert res["status"] == "ok"
    assert res["inserted"] == 1
    assert res["skills_count"] == 2
    assert res["experience_count"] == 2
    assert calls["kind"] == "linkedin"
    assert calls["items"][0]["folder"] == "linkedin/profile"


def test_failed_capture_ingests_nothing(monkeypatch):
    """An auth wall must not overwrite a good snapshot with an empty one."""
    calls = _wire(monkeypatch, {"success": False, "result": "extraction_empty"})
    res = L.run_profile_ingest()
    assert res["status"] == "capture_failed"
    assert res["inserted"] == 0
    assert "items" not in calls  # ingest_source never called


def test_success_but_no_voice_text_ingests_nothing(monkeypatch):
    """success:True with every voice field empty is a broken read, not a blank profile."""
    calls = _wire(
        monkeypatch,
        {"success": True, "name": "Terry", "headline": "", "about": "", "skills": [], "experience": []},
    )
    res = L.run_profile_ingest()
    assert res["status"] == "empty_profile"
    assert res["inserted"] == 0
    assert "items" not in calls


def test_missing_registry_row_is_reported_not_guessed(monkeypatch):
    calls = _wire(monkeypatch, _FIELDS, url=None)
    res = L.run_profile_ingest()
    assert res["status"] == "no_profile_url"
    assert res["inserted"] == 0
    assert "items" not in calls


def test_unknown_account_raises_rather_than_defaulting(monkeypatch):
    """ADR-028: a path that cannot prove its identity refuses. browser_id_for would
    silently return 342 (Kytran) and file HIS profile as this account's voice corpus."""
    from services.signal_accounts import UnknownAccountError

    monkeypatch.setattr(L, "_fetch_profile_url", lambda a: "http://li/in/x")
    monkeypatch.setattr(L, "_capture_profile", lambda a, u: _FIELDS)

    def boom(key):
        raise UnknownAccountError(f"no such account {key!r}")

    monkeypatch.setattr("services.signal_accounts.require_browser_id", boom, raising=False)
    with pytest.raises(UnknownAccountError):
        L.run_profile_ingest(account_key="definitely-not-an-account")


def test_recapture_of_unchanged_profile_reuses_message_id(monkeypatch):
    """Idempotency is carried by the content-addressed message_id — ingest_source skips it."""
    _wire(monkeypatch, _FIELDS)
    first = L.run_profile_ingest()["message_id"]
    second = L.run_profile_ingest()["message_id"]
    assert first == second

    _wire(monkeypatch, dict(_FIELDS, about="A rewritten about section."))
    assert L.run_profile_ingest()["message_id"] != first
