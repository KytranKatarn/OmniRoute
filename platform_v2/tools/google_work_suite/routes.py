from flask import request, jsonify, redirect, session, render_template
from flask_login import login_required, current_user
import psycopg2.extras

from . import google_work_suite_bp


def _verify_ownership(account_id):
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT owner_type, owner_id FROM google_accounts WHERE id = %s",
            (account_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        if row["owner_id"] == current_user.id:
            return True
        if getattr(current_user, "is_admin", False):
            return True
        return False


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------


@google_work_suite_bp.route("/")
@login_required
def index():
    return render_template("tools/google_work_suite.html")


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------


@google_work_suite_bp.route("/oauth/authorize")
@login_required
def oauth_authorize():
    from .services import get_auth_url

    owner_type = request.args.get("owner_type", "user")
    owner_id = int(request.args.get("owner_id", current_user.id))

    auth_url, state = get_auth_url(owner_type, owner_id)
    session["google_oauth_state"] = state
    return redirect(auth_url)


@google_work_suite_bp.route("/oauth/callback")
@login_required
def oauth_callback():
    from .services import handle_callback

    code = request.args.get("code")
    state = request.args.get("state")
    expected_state = session.pop("google_oauth_state", None)

    if not state or state != expected_state:
        return jsonify({"error": "Invalid OAuth state"}), 400

    result = handle_callback(code, state)
    if result.get("success"):
        return redirect("/tools/google-work-suite")
    return jsonify({"error": result.get("error", "OAuth callback failed")}), 400


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


@google_work_suite_bp.route("/api/accounts")
@login_required
def list_accounts():
    from .services import list_accounts as svc_list_accounts

    accounts = svc_list_accounts(owner_type="user", owner_id=current_user.id)

    if getattr(current_user, "is_admin", False):
        agent_accounts = svc_list_accounts(owner_type="agent", owner_id=None)
        accounts = accounts + agent_accounts

    # Serialize datetimes
    serialized = []
    for acct in accounts:
        row = dict(acct)
        for key, val in row.items():
            if hasattr(val, "isoformat"):
                row[key] = val.isoformat()
        serialized.append(row)

    return jsonify(serialized)


@google_work_suite_bp.route("/api/accounts/<int:account_id>", methods=["DELETE"])
@login_required
def disconnect_account(account_id):
    from .services import disconnect_account as svc_disconnect

    if not _verify_ownership(account_id):
        return jsonify({"error": "Not found or permission denied"}), 403

    result = svc_disconnect(account_id, "user", current_user.id)
    if result.get("success"):
        return jsonify({"success": True})
    return jsonify({"error": result.get("error", "Failed to disconnect")}), 400


# ---------------------------------------------------------------------------
# Email — inbox
# ---------------------------------------------------------------------------


@google_work_suite_bp.route("/api/inbox/<int:account_id>")
@login_required
def get_inbox(account_id):
    from .services import get_inbox as svc_get_inbox

    if not _verify_ownership(account_id):
        return jsonify({"error": "Not found or permission denied"}), 403

    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    label = request.args.get("label", "INBOX")

    result = svc_get_inbox(account_id, page, per_page, label)

    # Serialize datetimes
    messages = result.get("messages", [])
    for msg in messages:
        for key, val in msg.items():
            if hasattr(val, "isoformat"):
                msg[key] = val.isoformat()

    return jsonify(result)


@google_work_suite_bp.route("/api/email/<int:account_id>/<gmail_id>")
@login_required
def get_email(account_id, gmail_id):
    from .services import get_email as svc_get_email

    if not _verify_ownership(account_id):
        return jsonify({"error": "Not found or permission denied"}), 403

    result = svc_get_email(account_id, gmail_id)
    return jsonify(result)


@google_work_suite_bp.route("/api/email/send", methods=["POST"])
@login_required
def send_email():
    from .services import send_email as svc_send_email

    data = request.get_json() or {}
    account_id = data.get("account_id")
    to = data.get("to")
    subject = data.get("subject")
    body = data.get("body")
    reply_to_id = data.get("reply_to_id")

    if not account_id or not to:
        return jsonify({"error": "account_id and to are required"}), 400

    if not _verify_ownership(int(account_id)):
        return jsonify({"error": "Not found or permission denied"}), 403

    result = svc_send_email(account_id, to, subject, body, reply_to_id)
    if result.get("success"):
        return jsonify(result)
    return jsonify({"error": result.get("error", "Failed to send email")}), 400


@google_work_suite_bp.route("/api/email/sync/<int:account_id>", methods=["POST"])
@login_required
def sync_inbox(account_id):
    from .services import sync_inbox as svc_sync_inbox

    if not _verify_ownership(account_id):
        return jsonify({"error": "Not found or permission denied"}), 403

    result = svc_sync_inbox(account_id)
    return jsonify({"success": result.get("success", False), "count": result.get("count", 0)})


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@google_work_suite_bp.route("/api/rules/<int:account_id>")
@login_required
def get_rules(account_id):
    from database import get_db_cursor

    if not _verify_ownership(account_id):
        return jsonify({"error": "Not found or permission denied"}), 403

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, account_id, name, conditions, actions, created_at, updated_at "
            "FROM google_email_rules WHERE account_id = %s ORDER BY id",
            (account_id,),
        )
        rows = cur.fetchall()

    rules = []
    for row in rows:
        r = dict(row)
        for key, val in r.items():
            if hasattr(val, "isoformat"):
                r[key] = val.isoformat()
        rules.append(r)

    return jsonify(rules)


@google_work_suite_bp.route("/api/rules/<int:account_id>", methods=["POST"])
@login_required
def create_rule(account_id):
    from database import get_db_cursor

    if not _verify_ownership(account_id):
        return jsonify({"error": "Not found or permission denied"}), 403

    data = request.get_json() or {}
    name = data.get("name")
    conditions = data.get("conditions", {})
    actions = data.get("actions", {})

    if not name:
        return jsonify({"error": "name is required"}), 400

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO google_email_rules (account_id, name, conditions, actions) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (
                account_id,
                name,
                psycopg2.extras.Json(conditions),
                psycopg2.extras.Json(actions),
            ),
        )
        rule_id = cur.fetchone()["id"]

    return jsonify({"success": True, "rule_id": rule_id})


@google_work_suite_bp.route("/api/rules/<int:account_id>/<int:rule_id>", methods=["DELETE"])
@login_required
def delete_rule(account_id, rule_id):
    from database import get_db_cursor

    if not _verify_ownership(account_id):
        return jsonify({"error": "Not found or permission denied"}), 403

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM google_email_rules WHERE id = %s AND account_id = %s",
            (rule_id, account_id),
        )

    return jsonify({"success": True})
