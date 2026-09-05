"""Tests for consumer/admin_mail.py — the Citadel-resident admin mail dashboard
(#6318 relocation). No live network calls: imaplib.IMAP4_SSL and
smtplib.SMTP_SSL are replaced with minimal fakes shaped to admin_mail.py's
exact call signatures. No DB dependency — this blueprint deliberately touches
no database, so tests build a standalone Flask app around just this blueprint
rather than the full consumer app (which needs Postgres for billing init).
"""

import base64
from pathlib import Path

import pytest
from flask import Flask

import consumer.admin_mail as admin_mail

TEMPLATES_DIR = str(Path(__file__).resolve().parent.parent / "consumer" / "templates")


def _basic_auth_header(user, pw):
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture()
def app():
    flask_app = Flask("admin_mail_test", template_folder=TEMPLATES_DIR)
    flask_app.register_blueprint(admin_mail.admin_mail_bp)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Fakes — shaped to admin_mail.py's exact imaplib/smtplib call sites, not a
# general-purpose IMAP/SMTP simulator.
# ---------------------------------------------------------------------------

class FakeIMAP:
    """Stands in for imaplib.IMAP4_SSL. UID 999 is reserved to simulate a
    message that no longer exists (FETCH returns NO), for the 404 path."""

    last_instance = None

    def __init__(self, host=None, port=None, timeout=None):
        self.host = host
        self.logged_in = None
        FakeIMAP.last_instance = self

    def login(self, user, password):
        self.logged_in = (user, password)

    def select(self, mailbox, readonly=False):
        return ("OK", [b"2"])

    def uid(self, command, *args):
        if command == "SEARCH":
            crit = args[-1]
            if crit == "ALL":
                return ("OK", [b"101 102"])
            if crit == "UNSEEN":
                return ("OK", [b"102"])
            return ("OK", [b""])
        if command == "FETCH":
            uid, spec = args[0], args[1]
            if uid == "999":
                return ("NO", None)
            if "HEADER.FIELDS (SUBJECT FROM DATE)" in spec:
                flags = b"1 (FLAGS (\\Seen))" if uid == "101" else b"1 (FLAGS ())"
                header = (
                    b"Subject: Test Subject " + uid.encode() + b"\r\n"
                    b"From: Someone <someone@example.com>\r\n"
                    b"Date: Mon, 01 Jan 2026 00:00:00 +0000\r\n\r\n"
                )
                return ("OK", [(flags, header)])
            if "MESSAGE-ID" in spec:
                return ("OK", [(b"", b"Message-ID: <orig-" + uid.encode() + b"@example.com>\r\n")])
            if spec == "(BODY.PEEK[])":
                raw = (
                    b"Subject: Test Subject\r\n"
                    b"From: Someone <someone@example.com>\r\n"
                    b"To: contact@what-the-fact.com\r\n"
                    b"Date: Mon, 01 Jan 2026 00:00:00 +0000\r\n"
                    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
                    b"Hello, this is the body.\r\n"
                )
                return ("OK", [(b"", raw)])
        return ("NO", None)

    def append(self, folder, flags, date, message):
        return ("OK", [None])

    def logout(self):
        pass


class FakeIMAPXSS(FakeIMAP):
    """Same as FakeIMAP but the message subject/body carry a script-injection
    attempt, for the XSS test."""

    def uid(self, command, *args):
        if command == "FETCH" and args[1] == "(BODY.PEEK[])":
            raw = (
                b"Subject: <script>alert(1)</script>\r\n"
                b"From: Attacker <attacker@example.com>\r\n"
                b"To: contact@what-the-fact.com\r\n"
                b"Date: Mon, 01 Jan 2026 00:00:00 +0000\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
                b"<script>alert(2)</script> body text\r\n"
            )
            return ("OK", [(b"", raw)])
        return super().uid(command, *args)


class FakeSMTP:
    sent = []

    def __init__(self, host, port, context=None, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture()
def mock_imap(monkeypatch):
    monkeypatch.setattr(admin_mail.imaplib, "IMAP4_SSL", FakeIMAP)
    return FakeIMAP


@pytest.fixture()
def mock_smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(admin_mail.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


@pytest.fixture()
def admin_env(monkeypatch):
    """The dashboard's own Basic Auth credentials + one configured mailbox."""
    monkeypatch.setenv("WTF_ADMIN_MAIL_USER", "opsuser")
    monkeypatch.setenv("WTF_ADMIN_MAIL_PASSWORD", "opspass")
    monkeypatch.setenv("WTF_MAIL_CONTACT_PASSWORD", "boxpass")
    # Every other mailbox stays unconfigured on purpose (tests status honesty).
    for key in ("WTF_MAIL_TIP_PASSWORD", "WTF_MAIL_PRESS_PASSWORD",
                "WTF_MAIL_API_PASSWORD", "WTF_MAIL_ADMIN_PASSWORD", "WTF_MAIL_SHARED_PASSWORD"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def no_admin_env(monkeypatch):
    """Neither WTF_ADMIN_MAIL_USER nor _PASSWORD set — the fail-closed case."""
    monkeypatch.delenv("WTF_ADMIN_MAIL_USER", raising=False)
    monkeypatch.delenv("WTF_ADMIN_MAIL_PASSWORD", raising=False)


ADMIN_MAIL_ROUTES = [
    ("GET", "/admin/mail"),
    ("GET", "/admin/mail/api/status"),
    ("GET", "/admin/mail/api/inbox?box=contact"),
    ("GET", "/admin/mail/api/message?box=contact&uid=101"),
    ("POST", "/admin/mail/api/send"),
]


# --- (a) fail-closed when unconfigured -------------------------------------

@pytest.mark.parametrize("method,path", ADMIN_MAIL_ROUTES)
def test_fails_closed_when_admin_credentials_unset(client, no_admin_env, method, path):
    """Every route in the blueprint refuses with 503 — never a silent
    pass-through — when the dashboard's own credentials are not configured."""
    resp = client.open(path, method=method, json={} if method == "POST" else None)
    assert resp.status_code == 503
    assert "error" in resp.get_json()


def test_fails_closed_even_with_a_provided_auth_header(client, no_admin_env):
    """Providing SOME credentials must not bypass the unconfigured check —
    there is nothing correct to compare against."""
    resp = client.get("/admin/mail/api/status", headers=_basic_auth_header("anyone", "anything"))
    assert resp.status_code == 503


# --- (b) wrong vs correct credentials ---------------------------------------

def test_rejects_missing_auth_header(client, admin_env):
    resp = client.get("/admin/mail/api/status")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate", "").startswith("Basic")


def test_rejects_wrong_password(client, admin_env):
    resp = client.get("/admin/mail/api/status", headers=_basic_auth_header("opsuser", "wrong"))
    assert resp.status_code == 401


def test_rejects_wrong_username(client, admin_env):
    resp = client.get("/admin/mail/api/status", headers=_basic_auth_header("wronguser", "opspass"))
    assert resp.status_code == 401


def test_accepts_correct_credentials(client, admin_env):
    """No mailbox IMAP call is needed for /status on an unconfigured box —
    this proves the auth gate itself passes on a correct match."""
    resp = client.get("/admin/mail/api/status", headers=_basic_auth_header("opsuser", "opspass"))
    assert resp.status_code == 200
    boxes = {b["key"]: b for b in resp.get_json()["mailboxes"]}
    assert boxes["contact"]["configured"] is True
    assert boxes["tip"]["configured"] is False
    assert boxes["tip"]["error"] == "no password"


def test_dashboard_page_requires_auth_too(client, admin_env):
    """The page itself, not only the API, is behind the gate (before_request
    on the whole blueprint)."""
    resp = client.get("/admin/mail")
    assert resp.status_code == 401
    resp_ok = client.get("/admin/mail", headers=_basic_auth_header("opsuser", "opspass"))
    assert resp_ok.status_code == 200


# --- (c) route logic with mocked IMAP/SMTP ----------------------------------

def _auth(client, method, path, **kw):
    headers = kw.pop("headers", {})
    headers.update(_basic_auth_header("opsuser", "opspass"))
    return client.open(path, method=method, headers=headers, **kw)


def test_status_reports_configured_box_counts(client, admin_env, mock_imap):
    resp = _auth(client, "GET", "/admin/mail/api/status")
    assert resp.status_code == 200
    contact = next(b for b in resp.get_json()["mailboxes"] if b["key"] == "contact")
    assert contact["configured"] is True
    assert contact["total"] == 2
    assert contact["unseen"] == 1
    assert contact["error"] is None


def test_inbox_lists_messages_newest_first(client, admin_env, mock_imap):
    resp = _auth(client, "GET", "/admin/mail/api/inbox?box=contact&limit=10")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["box"] == "contact"
    assert body["address"] == "contact@what-the-fact.com"
    assert body["count"] == 2
    # newest first: SEARCH returned "101 102", reversed -> 102 then 101
    assert [m["uid"] for m in body["messages"]] == ["102", "101"]
    assert body["messages"][0]["seen"] is False  # 102 has no \Seen flag in the fake
    assert body["messages"][1]["seen"] is True   # 101 does


def test_inbox_unknown_box_400(client, admin_env, mock_imap):
    resp = _auth(client, "GET", "/admin/mail/api/inbox?box=notabox")
    assert resp.status_code == 400


def test_message_returns_full_body(client, admin_env, mock_imap):
    resp = _auth(client, "GET", "/admin/mail/api/message?box=contact&uid=101")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["subject"] == "Test Subject"
    assert body["from"] == "Someone <someone@example.com>"
    assert body["to"] == "contact@what-the-fact.com"
    assert "Hello, this is the body." in body["body"]


def test_message_not_found_404(client, admin_env, mock_imap):
    resp = _auth(client, "GET", "/admin/mail/api/message?box=contact&uid=999")
    assert resp.status_code == 404


def test_message_invalid_uid_400(client, admin_env, mock_imap):
    resp = _auth(client, "GET", "/admin/mail/api/message?box=contact&uid=not-a-number")
    assert resp.status_code == 400


def test_send_success_and_threading_headers(client, admin_env, mock_imap, mock_smtp):
    resp = _auth(
        client, "POST", "/admin/mail/api/send",
        json={"box": "contact", "to": "reader@example.com", "subject": "Re: hi",
              "body": "thanks for writing", "uid": "101"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sent"] is True
    assert body["from"] == "contact@what-the-fact.com"
    assert body["to"] == "reader@example.com"
    assert len(FakeSMTP.sent) == 1
    sent_msg = FakeSMTP.sent[0]
    assert sent_msg["To"] == "reader@example.com"
    assert sent_msg["Subject"] == "Re: hi"
    # threading — the fake's Message-ID for uid 101
    assert sent_msg["In-Reply-To"] == "<orig-101@example.com>"
    assert sent_msg["References"] == "<orig-101@example.com>"


def test_send_rejects_invalid_recipient(client, admin_env, mock_imap, mock_smtp):
    resp = _auth(
        client, "POST", "/admin/mail/api/send",
        json={"box": "contact", "to": "not an email", "subject": "x", "body": "y"},
    )
    assert resp.status_code == 400
    assert FakeSMTP.sent == []


def test_send_requires_subject_and_body(client, admin_env, mock_imap, mock_smtp):
    resp = _auth(
        client, "POST", "/admin/mail/api/send",
        json={"box": "contact", "to": "reader@example.com", "subject": "", "body": ""},
    )
    assert resp.status_code == 400


def test_send_unconfigured_mailbox_rejected(client, admin_env, mock_imap, mock_smtp):
    resp = _auth(
        client, "POST", "/admin/mail/api/send",
        json={"box": "tip", "to": "reader@example.com", "subject": "x", "body": "y"},
    )
    assert resp.status_code == 400
    assert FakeSMTP.sent == []


# --- (d) XSS — untrusted mail content is never emitted as executable HTML --

def test_message_html_is_stripped_to_plain_text_and_never_a_raw_tag_in_dashboard_markup(
    client, admin_env, monkeypatch,
):
    """The dashboard SHELL (server-rendered) never embeds message content —
    it is fetched by JS and must be assigned via textContent, which this test
    pins by asserting the shell markup contains no raw script tag AND that
    the JS source uses textContent, never innerHTML, for message fields."""
    resp = _auth(client, "GET", "/admin/mail")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert ".innerHTML" not in html
    assert "textContent" in html


def test_extracted_body_html_is_escaped_plain_text(admin_env):
    """_extract_body/_html_to_text strip tags entirely rather than passing
    raw HTML through — the client renders the result via textContent, but
    the server-side helper itself must not hand back live markup either."""
    from email import message_from_bytes

    raw = (
        b"Subject: hi\r\n"
        b"From: a@example.com\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p>hello <script>alert(1)</script> world</p>"
    )
    msg = message_from_bytes(raw)
    body = admin_mail._extract_body(msg)
    assert "<script>" not in body
    assert "hello" in body and "world" in body


# --- (d.5) accessibility — keyboard-operable list, real form labels --------

def test_message_row_is_keyboard_operable(client, admin_env):
    """The message-list row is the ONLY way to open a message. A
    mouse-only div (click handler, no tabindex/role/keydown) locks out
    keyboard-only and screen-reader users entirely. Pins: each row gets a
    tabindex, a button role, and an Enter/Space keydown handler that calls
    the same activation function as click."""
    resp = _auth(client, "GET", "/admin/mail")
    html = resp.get_data(as_text=True)
    assert "setAttribute('tabindex'" in html
    assert "setAttribute('role', 'button')" in html
    assert "e.key === 'Enter'" in html
    assert "addEventListener('keydown'" in html


def test_reply_form_fields_have_real_labels(client, admin_env):
    """To/Subject/Body inputs must be associated with a real <label> (for/id),
    not just a placeholder attribute — a placeholder is not a programmatic
    label (WCAG 1.3.1/4.1.2) and disappears once the field has a value."""
    resp = _auth(client, "GET", "/admin/mail")
    html = resp.get_data(as_text=True)
    for label_text, input_id in (
        ("To", "amReplyTo"),
        ("Subject", "amReplySubject"),
        ("Reply body", "amReplyBody"),
    ):
        assert "'" + label_text + "'" in html
        assert "for', '" + input_id + "'" in html
        assert "id = '" + input_id + "'" in html


# --- (e) AI triage/draft deliberately not ported ----------------------------

def test_ai_triage_and_wtf_mail_ai_are_not_present_in_this_module():
    """Pins the scope decision documented in admin_mail.py's module
    docstring: this dashboard is read/send only. A future change that adds
    an in-process department_dispatcher call or a wtf_mail_ai reference in
    the CODE (not the explanatory docstring, which names them on purpose to
    document the boundary) would silently reintroduce the Hub dependency
    this relocation exists to remove — fail loud instead."""
    import ast

    src = Path(admin_mail.__file__).read_text()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    doc_node = tree.body[0] if tree.body and isinstance(tree.body[0], ast.Expr) else None
    code_src = "".join(lines[doc_node.end_lineno:]) if doc_node is not None else src
    assert ast.get_docstring(tree), "expected a module docstring to strip before scanning"

    assert "department_dispatcher" not in code_src
    assert "wtf_mail_ai" not in code_src
    assert "dispatch(" not in code_src
    # and the routes that carried that behaviour on the platform side are
    # simply absent here (no triage/draft/ai endpoints at all)
    assert "triage" not in code_src
    assert "/draft" not in code_src
