"""Hermetic tests for chronicle_gmail_attachments (slice 06).

No live Gmail, no DB. All external seams (gmail_service, _get_attachment_bytes,
upsert_attachment, _account_for_import, _candidate_emails) are monkeypatched, and
STORAGE_ROOT is redirected to a pytest tmp_path.
"""

import hashlib
import os

import services.chronicle_gmail_attachments as a


def test_safe_name():
    assert a._safe_name("../../etc/passwd") == "passwd"
    assert a._safe_name("a/b.pdf") == "b.pdf"
    assert a._safe_name("") == "attachment"
    assert a._safe_name(None) == "attachment"


def test_download_saves_and_registers(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(a, "_account_for_import", lambda i: 7)
    monkeypatch.setattr(a, "_candidate_emails", lambda i, l: [(101, "m1")])
    monkeypatch.setattr(
        a.gmail_service,
        "get_email",
        lambda account_id, gmail_id: {
            "attachments": [
                {
                    "filename": "doc.pdf",
                    "mimeType": "application/pdf",
                    "size": 5,
                    "attachmentId": "att1",
                }
            ]
        },
    )
    monkeypatch.setattr(a, "_get_attachment_bytes", lambda *args: b"hello")

    calls = []

    def fake_upsert(email_id, filename, mime_type, size_bytes, sha256, stored_path):
        calls.append((email_id, filename, mime_type, size_bytes, sha256, stored_path))
        return (1, True)

    monkeypatch.setattr(a, "upsert_attachment", fake_upsert)

    result = a.run_attachment_download(16)

    expected_path = os.path.join(str(tmp_path), "16", "att", "101", "doc.pdf")
    assert os.path.exists(expected_path)
    with open(expected_path, "rb") as fh:
        assert fh.read() == b"hello"

    expected_sha = hashlib.sha256(b"hello").hexdigest()
    assert calls == [(101, "doc.pdf", "application/pdf", 5, expected_sha, expected_path)]

    assert result == {
        "import_id": 16,
        "emails_processed": 1,
        "attachments_saved": 1,
        "errors": 0,
    }


def test_per_attachment_error_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(a, "_account_for_import", lambda i: 7)
    monkeypatch.setattr(a, "_candidate_emails", lambda i, l: [(101, "m1")])
    monkeypatch.setattr(
        a.gmail_service,
        "get_email",
        lambda account_id, gmail_id: {
            "attachments": [
                {"filename": "bad.pdf", "mimeType": "application/pdf", "size": 5, "attachmentId": "att1"},
                {"filename": "good.pdf", "mimeType": "application/pdf", "size": 5, "attachmentId": "att2"},
            ]
        },
    )

    def flaky_bytes(account_id, gmail_id, attachment_id):
        if attachment_id == "att1":
            raise RuntimeError("boom")
        return b"hello"

    monkeypatch.setattr(a, "_get_attachment_bytes", flaky_bytes)
    monkeypatch.setattr(a, "upsert_attachment", lambda *args: (1, True))

    result = a.run_attachment_download(16)

    assert result["attachments_saved"] == 1
    assert result["errors"] == 1


def test_get_email_error_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(a, "_account_for_import", lambda i: 7)
    monkeypatch.setattr(a, "_candidate_emails", lambda i, l: [(101, "m1")])

    def raise_get_email(account_id, gmail_id):
        raise RuntimeError("gmail down")

    monkeypatch.setattr(a.gmail_service, "get_email", raise_get_email)
    monkeypatch.setattr(a, "_get_attachment_bytes", lambda *args: b"hello")
    monkeypatch.setattr(a, "upsert_attachment", lambda *args: (1, True))

    result = a.run_attachment_download(16)

    assert result["errors"] == 1
    assert result["attachments_saved"] == 0


def test_no_account_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(a, "_account_for_import", lambda i: None)

    calls = []
    monkeypatch.setattr(a.gmail_service, "get_email", lambda *args, **kwargs: calls.append(args) or {})

    result = a.run_attachment_download(16)

    assert result == {
        "import_id": 16,
        "emails_processed": 0,
        "attachments_saved": 0,
        "errors": 0,
    }
    assert calls == []


def test_attachment_without_id_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(a, "_account_for_import", lambda i: 7)
    monkeypatch.setattr(a, "_candidate_emails", lambda i, l: [(101, "m1")])
    monkeypatch.setattr(
        a.gmail_service,
        "get_email",
        lambda account_id, gmail_id: {
            "attachments": [{"filename": "noid.pdf", "mimeType": "application/pdf", "size": 5}]
        },
    )

    called = []
    monkeypatch.setattr(a, "_get_attachment_bytes", lambda *args: called.append(args) or b"hello")
    monkeypatch.setattr(a, "upsert_attachment", lambda *args: (1, True))

    result = a.run_attachment_download(16)

    assert result["attachments_saved"] == 0
    assert result["errors"] == 0
    assert called == []
