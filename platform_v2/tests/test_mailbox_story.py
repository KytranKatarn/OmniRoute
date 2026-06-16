"""Unit tests for the Mailbox Story Extractor extraction engine (libpff/pffexport-based).

Hermetic: the pffexport binary + DB cursor are stubbed; parsers run on synthetic pffexport
output dirs in tmp_path. No live DB, no pffexport, no PST needed.
"""

import os
import types
from contextlib import contextmanager

import services.mailbox_extract_service as svc

OUTLOOK_HEADERS = (
    "Message:\n"
    "Client submit time:\t\tOct 05, 2022 18:34:59.000000000 UTC\n"
    "Subject:\t\tRE: Discussion SOW NEGCS\n"
    "Sender name:\t\tChristian Roy\n"
    "Sender email address:\t\t/O=PWGSC-TPSGC/CN=ROYC6\n"
)
RECIPIENTS = (
    "Display name:\tCaetano, Terry\n"
    "Email address:\tterry@pwgsc.gc.ca\n"
    "Recipient type:\tTo\n"
    "\n"
    "Display name:\tGuy, Eric\n"
    "Email address:\t/o=PWGSC/cn=GUYE\n"
    "Recipient type:\tCc\n"
)
INTERNET_HEADERS = (
    "From: Christian Roy <christian.roy@pwgsc.gc.ca>\n"
    "To: terry@pwgsc.gc.ca\n"
    "Message-ID: <abc123@pwgsc.gc.ca>\n"
    "Subject: RE: Discussion SOW NEGCS\n"
    "\n"
)


def _make_msg_dir(base, name="Message00001", attach=False, internet=True):
    d = os.path.join(base, name)
    os.makedirs(d)
    open(os.path.join(d, "OutlookHeaders.txt"), "w").write(OUTLOOK_HEADERS)
    open(os.path.join(d, "Recipients.txt"), "w").write(RECIPIENTS)
    open(os.path.join(d, "Message.txt"), "w").write("Bonjour,\n\nMario devrait vous envoyer les plans.")
    if internet:
        open(os.path.join(d, "InternetHeaders.txt"), "w").write(INTERNET_HEADERS)
    if attach:
        os.makedirs(os.path.join(d, "Attachments"))
    return d


# ---------- parsers (pure) ----------


def test_parse_date():
    dt = svc._parse_date("Oct 05, 2022 18:34:59.000000000 UTC")
    assert dt is not None and dt.year == 2022 and dt.month == 10 and dt.day == 5
    assert svc._parse_date("garbage") is None
    assert svc._parse_date("") is None


def test_parse_recipients(tmp_path):
    p = tmp_path / "Recipients.txt"
    p.write_text(RECIPIENTS)
    r = svc._parse_recipients(str(p))
    assert "Terry" in r["to"] and "terry@pwgsc.gc.ca" in r["to"]  # SMTP shown when present
    assert "Guy, Eric" in r["cc"]  # Exchange DN → display name only


def test_parse_pff_message_prefers_internet_headers(tmp_path):
    d = _make_msg_dir(str(tmp_path), attach=True, internet=True)
    rec = svc._parse_pff_message(d, "Inbox")
    assert rec["folder"] == "Inbox"
    assert rec["from_addr"] == "Christian Roy <christian.roy@pwgsc.gc.ca>"  # from InternetHeaders
    assert rec["to_addrs"] == "terry@pwgsc.gc.ca"
    assert rec["message_id"] == "<abc123@pwgsc.gc.ca>"
    assert rec["subject"] == "RE: Discussion SOW NEGCS"
    assert rec["sent_at"] is not None
    assert rec["has_attachments"] is True
    assert "Bonjour" in rec["body_text"]


def test_parse_pff_message_falls_back_to_outlook(tmp_path):
    # No InternetHeaders → use Outlook Sender name + Recipients.
    d = _make_msg_dir(str(tmp_path), internet=False)
    rec = svc._parse_pff_message(d, "Sent")
    assert rec["from_addr"] == "Christian Roy"  # DN sender → name only
    assert "Caetano, Terry" in rec["to_addrs"]
    assert rec["has_attachments"] is False


def test_clean_folder():
    assert svc._clean_folder("Top of Outlook data file/Personal Archive") == "Personal Archive"
    assert "attached" in svc._clean_folder("Top of Outlook data file/Calendrier/Appointment1/Attachments/Attachment1")


# ---------- extract_pst (stub pffexport + DB) ----------


class _FakeCur:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self.store.append((sql, params))


def _patch_db(monkeypatch):
    store = []

    @contextmanager
    def _fake_db(commit=True):
        yield (None, _FakeCur(store))

    monkeypatch.setattr(svc, "get_db_cursor", _fake_db)
    return store


def _marked_error(store):
    return any("status='error'" in s for s, _ in store)


def test_extract_pst_success_inserts_rows(tmp_path, monkeypatch):
    store = _patch_db(monkeypatch)
    out = tmp_path / "eml"

    def fake_run(cmd, *a, **k):
        # emulate pffexport creating <out>/pff.export/Inbox/Message00001/
        _make_msg_dir(str(out / "pff.export" / "Inbox"))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(svc.subprocess, "run", fake_run)
    assert svc.extract_pst(1, str(tmp_path / "x.pst"), str(out)) == 1
    sqls = " ".join(s for s, _ in store)
    assert "INSERT INTO mailbox_emails" in sqls
    assert "status='extracted'" in sqls
    assert not _marked_error(store)


def test_extract_pst_skips_non_message_items(tmp_path, monkeypatch):
    store = _patch_db(monkeypatch)
    out = tmp_path / "eml"

    def fake_run(cmd, *a, **k):
        # an Appointment item (not Message) → must be skipped
        d = out / "pff.export" / "Calendrier" / "Appointment00001"
        d.mkdir(parents=True)
        (d / "OutlookHeaders.txt").write_text("Appointment:\nSubject:\t\tMeeting\n")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(svc.subprocess, "run", fake_run)
    assert svc.extract_pst(1, str(tmp_path / "x.pst"), str(out)) == 0
    assert not any("INSERT INTO mailbox_emails" in s for s, _ in store)


def test_extract_pst_marks_error_on_timeout(tmp_path, monkeypatch):
    import subprocess as _sp

    store = _patch_db(monkeypatch)
    monkeypatch.setattr(
        svc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(_sp.TimeoutExpired("pffexport", 1))
    )
    assert svc.extract_pst(1, str(tmp_path / "x.pst"), str(tmp_path / "eml")) == 0
    assert _marked_error(store)


def test_extract_pst_marks_error_when_no_output(tmp_path, monkeypatch):
    store = _patch_db(monkeypatch)
    # subprocess "succeeds" but creates no export dir → error
    monkeypatch.setattr(
        svc.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr="boom")
    )
    assert svc.extract_pst(1, str(tmp_path / "x.pst"), str(tmp_path / "eml")) == 0
    assert _marked_error(store)


def test_decode_rfc2047_subject():
    # =?utf-8?B?...?= encoded-word -> readable text
    assert svc._dh("=?utf-8?B?SU5WSVRBVElPTg==?=") == "INVITATION"
    assert svc._dh("plain subject") == "plain subject"
    assert svc._dh(None) is None
