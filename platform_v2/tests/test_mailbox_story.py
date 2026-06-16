"""Unit tests for the Mailbox Story Extractor extraction engine.

Pure / hermetic: parse_eml needs only temp files; extract_pst's branches are
exercised with the readpst subprocess and the DB cursor stubbed, so these run
anywhere (no live DB, no readpst binary).
"""

import subprocess
import types
from contextlib import contextmanager

import services.mailbox_extract_service as svc

GOV = (
    "From: Jane Auditor <jane.auditor@tbs-sct.gc.ca>\n"
    "To: vendor <ops@contractor.example>\n"
    "Cc: oversight@pco-bcp.gc.ca\n"
    "Date: Tue, 03 Jun 2026 14:05:00 -0400\n"
    "Subject: RE: Contract 24-0098 deliverable 3\n"
    "Message-ID: <gov-001@tbs-sct.gc.ca>\n"
    "MIME-Version: 1.0\n"
    'Content-Type: multipart/mixed; boundary="b1"\n\n'
    "--b1\nContent-Type: text/plain\n\nPlease find the signed deliverable attached.\n\n"
    '--b1\nContent-Type: application/pdf; name="d3.pdf"\n'
    'Content-Disposition: attachment; filename="d3.pdf"\n\nJVBERi0xLjQK\n--b1--\n'
)
PLAIN = (
    "From: scheduler@contractor.example\n"
    "To: jane.auditor@tbs-sct.gc.ca\n"
    "Date: Mon, 02 Jun 2026 09:00:00 -0400\n"
    "Subject: Kickoff meeting Thursday\n"
    "Message-ID: <c-002@contractor.example>\n"
    "In-Reply-To: <gov-001@tbs-sct.gc.ca>\n\n"
    "Confirming the kickoff for project Northstar on Thursday.\n"
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return str(p)


# ---------- parse_eml (pure) ----------


def test_parse_eml_multipart_with_attachment(tmp_path):
    rec = svc.parse_eml(_write(tmp_path, "1.eml", GOV), "Inbox")
    assert rec["folder"] == "Inbox"
    assert rec["from_addr"] == "jane.auditor@tbs-sct.gc.ca"
    assert rec["to_addrs"] == "ops@contractor.example"
    assert rec["cc_addrs"] == "oversight@pco-bcp.gc.ca"
    assert rec["has_attachments"] is True
    assert "deliverable" in (rec["body_text"] or "").lower()
    assert rec["sent_at"] is not None


def test_parse_eml_plain_threading(tmp_path):
    rec = svc.parse_eml(_write(tmp_path, "2.eml", PLAIN), "Sent")
    assert rec["has_attachments"] is False
    assert rec["in_reply_to"] == "<gov-001@tbs-sct.gc.ca>"
    assert rec["from_addr"] == "scheduler@contractor.example"


def test_parse_eml_bad_date_never_raises(tmp_path):
    rec = svc.parse_eml(_write(tmp_path, "3.eml", "From: a@b.com\nDate: not-a-date\nSubject: x\n\nbody"), "")
    assert rec["sent_at"] is None
    assert rec["subject"] == "x"


def test_parse_eml_missing_headers_never_raises(tmp_path):
    rec = svc.parse_eml(_write(tmp_path, "4.eml", "\nbody only"), "")
    assert rec["from_addr"] is None
    assert rec["subject"] is None
    assert rec["has_attachments"] is False


# ---------- extract_pst error handling (stub subprocess + DB) ----------


class _FakeCur:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self.store.append((sql, params))

    def fetchone(self):
        return {"id": 1}


def _patch_db(monkeypatch):
    store = []

    @contextmanager
    def _fake_db(commit=True):
        yield (None, _FakeCur(store))

    monkeypatch.setattr(svc, "get_db_cursor", _fake_db)
    return store


def _marked_error(store):
    return any("status='error'" in s for s, _ in store)


def test_extract_pst_marks_error_on_timeout(tmp_path, monkeypatch):
    store = _patch_db(monkeypatch)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="readpst", timeout=1)

    monkeypatch.setattr(svc.subprocess, "run", boom)
    assert svc.extract_pst(1, str(tmp_path / "x.pst"), str(tmp_path / "eml")) == 0
    assert _marked_error(store)


def test_extract_pst_marks_error_when_readpst_missing(tmp_path, monkeypatch):
    store = _patch_db(monkeypatch)

    def boom(*a, **k):
        raise FileNotFoundError("readpst")

    monkeypatch.setattr(svc.subprocess, "run", boom)
    assert svc.extract_pst(1, str(tmp_path / "x.pst"), str(tmp_path / "eml")) == 0
    assert _marked_error(store)


def test_extract_pst_marks_error_on_nonzero_exit(tmp_path, monkeypatch):
    store = _patch_db(monkeypatch)
    monkeypatch.setattr(
        svc.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="bad pst"),
    )
    assert svc.extract_pst(1, str(tmp_path / "x.pst"), str(tmp_path / "eml")) == 0
    assert _marked_error(store)


def test_extract_pst_success_inserts_rows(tmp_path, monkeypatch):
    store = _patch_db(monkeypatch)
    inbox = tmp_path / "eml" / "Inbox"
    inbox.mkdir(parents=True)
    (inbox / "1.eml").write_text(PLAIN)
    monkeypatch.setattr(
        svc.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert svc.extract_pst(1, str(tmp_path / "x.pst"), str(tmp_path / "eml")) == 1
    assert any("INSERT INTO mailbox_emails" in s for s, _ in store)
    assert any("status='extracted'" in s for s, _ in store)
    assert not _marked_error(store)
