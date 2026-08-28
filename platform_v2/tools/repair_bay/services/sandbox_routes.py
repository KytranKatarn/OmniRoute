"""
Sandbox Routes - Full A.R.C.H.I.E. Interface in Isolated Environment
Provides /sandbox/dashboard and /sandbox/admin routes with schema separation
"""

from flask import (
    Blueprint,
    render_template,
    session,
    redirect,
    url_for,
    g,
    flash,
)
from flask_login import login_required, current_user
from functools import wraps

sandbox_bp = Blueprint("sandbox", __name__, url_prefix="/sandbox")


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            flash("Admin access required", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)

    return decorated_function


def sandbox_mode(f):
    """
    Decorator to set database schema to 'sandbox' for all sandbox routes
    All queries will use SET search_path TO sandbox, public;
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Set sandbox mode flag in session
        session["sandbox_mode"] = True
        session["db_schema"] = "sandbox"

        # Store in g for template access
        g.sandbox_mode = True
        g.db_schema = "sandbox"

        return f(*args, **kwargs)

    return decorated_function


@sandbox_bp.route("/")
@login_required
@sandbox_mode
def index():
    """Redirect to sandbox dashboard"""
    return redirect(url_for("sandbox.dashboard"))


@sandbox_bp.route("/dashboard")
@login_required
@sandbox_mode
def dashboard():
    """
    Render full dashboard in sandbox mode
    Uses 'sandbox' schema for all database queries
    """
    return render_template("dashboard.html", sandbox_mode=True, schema_name="sandbox")


@sandbox_bp.route("/admin")
@login_required
@admin_required
@sandbox_mode
def admin():
    """
    Render full admin panel in sandbox mode
    Uses 'sandbox' schema for all database queries
    """
    return render_template(
        "tools/admin.html",
        sandbox_mode=True,
        schema_name="sandbox",
        sandbox_prefix="/sandbox",
    )


# Mirror all tool routes under /sandbox/tools/
@sandbox_bp.route("/tools/admin/")
@login_required
@admin_required
@sandbox_mode
def tools_admin():
    """
    Proxy to admin panel - calls production admin route but with sandbox mode
    """
    # Import the production admin index function
    from tools.admin.routes import index as admin_index

    # Call it - it will see sandbox_mode=True in session
    # and use sandbox schema for all queries
    return admin_index()


@sandbox_bp.route("/tools/code_editor/")
@sandbox_bp.route("/tools/code_editor/<path:subpath>")
@login_required
@sandbox_mode
def tools_code_editor(subpath=None):
    """
    Code editor in sandbox mode
    """
    return render_template(
        "repair_bay/code_editor.html",
        sandbox_mode=True,
        schema_name="sandbox",
        sandbox_prefix="/sandbox",
    )


@sandbox_bp.route("/tools/improvements/")
@sandbox_bp.route("/tools/improvements/<path:subpath>")
@login_required
@sandbox_mode
def tools_improvements(subpath=None):
    """
    Improvements tool in sandbox mode
    """
    return render_template(
        "tools/improvements.html",
        sandbox_mode=True,
        schema_name="sandbox",
        sandbox_prefix="/sandbox",
    )


@sandbox_bp.route("/exit")
@login_required
def exit_sandbox():
    """Exit sandbox mode and return to production"""
    # Clear sandbox mode from session
    session.pop("sandbox_mode", None)
    session.pop("db_schema", None)

    # Redirect to production dashboard
    return redirect(url_for("main.dashboard"))


# API routes for sandbox-specific operations
@sandbox_bp.route("/api/status")
@login_required
@sandbox_mode
def api_status():
    """Get current sandbox status"""
    from flask import jsonify
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import os
    from database import _get_db_password

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Set search path to sandbox
    cur.execute("SET search_path TO sandbox, public")

    # Get sandbox info
    cur.execute(
        """
        SELECT
            COUNT(*) as table_count
        FROM information_schema.tables
        WHERE table_schema = 'sandbox'
    """
    )
    table_count = cur.fetchone()["table_count"]

    # Get current proposal using sandbox
    cur.execute(
        """
        SELECT
            si.id as sandbox_id,
            si.proposal_id,
            si.status,
            si.created_at,
            ip.title,
            ip.category
        FROM sandbox_instances si
        JOIN improvement_proposals ip ON si.proposal_id = ip.id
        WHERE si.destroyed_at IS NULL
        AND si.status IN ('ready', 'testing', 'tested', 'applying_changes')
        ORDER BY si.created_at DESC
        LIMIT 1
    """
    )
    current_proposal = cur.fetchone()

    cur.close()
    conn.close()

    return jsonify(
        {
            "success": True,
            "sandbox_mode": True,
            "schema_name": "sandbox",
            "table_count": table_count,
            "current_proposal": dict(current_proposal) if current_proposal else None,
        }
    )


@sandbox_bp.route("/api/compare")
@login_required
@admin_required
@sandbox_mode
def api_compare():
    """Compare sandbox vs production schemas"""
    from flask import jsonify
    from tools.repair_bay.services.sandbox_schema import SchemaSandboxManager

    manager = SchemaSandboxManager()
    result = manager.compare_schemas("sandbox", "public")

    return jsonify(result)


# ============================================================================
# API PROXIES - Forward all tool API calls with sandbox mode enabled
# ============================================================================


@sandbox_bp.route("/tools/admin/<path:api_path>", methods=["GET", "POST", "PUT", "DELETE"])
@login_required
@sandbox_mode
def proxy_admin_api(api_path):
    """
    Proxy all admin API calls to the admin blueprint
    But with sandbox mode enabled so queries use sandbox schema
    """
    from flask import current_app, request as flask_request

    # Set sandbox mode in session for the API call
    session["sandbox_mode"] = True
    session["db_schema"] = "sandbox"

    # Forward to the original admin blueprint endpoint
    # The admin routes will see sandbox_mode=True in session
    # and db_schema='sandbox', so all queries will use sandbox schema
    with current_app.test_request_context(
        f"/tools/admin/{api_path}",
        method=flask_request.method,
        data=flask_request.data,
        headers=flask_request.headers,
    ):
        try:
            # Import the admin blueprint to access its view functions

            # Get the view function for this endpoint
            # Flask will match the route and call the appropriate function
            response = current_app.full_dispatch_request()
            return response
        except Exception as e:
            from flask import jsonify

            return jsonify({"success": False, "error": str(e)}), 500


@sandbox_bp.route("/tools/improvements/<path:api_path>", methods=["GET", "POST", "PUT", "DELETE"])
@login_required
@sandbox_mode
def proxy_improvements_api(api_path):
    """Proxy improvements API calls with sandbox mode"""
    session["sandbox_mode"] = True
    session["db_schema"] = "sandbox"

    from flask import current_app, request as flask_request

    with current_app.test_request_context(
        f"/tools/improvements/{api_path}",
        method=flask_request.method,
        data=flask_request.data,
        headers=flask_request.headers,
    ):
        try:
            response = current_app.full_dispatch_request()
            return response
        except Exception as e:
            from flask import jsonify

            return jsonify({"success": False, "error": str(e)}), 500


@sandbox_bp.route("/tools/code_editor/<path:api_path>", methods=["GET", "POST", "PUT", "DELETE"])
@login_required
@sandbox_mode
def proxy_code_editor_api(api_path):
    """Proxy code editor API calls with sandbox mode"""
    session["sandbox_mode"] = True
    session["db_schema"] = "sandbox"

    from flask import current_app, request as flask_request

    with current_app.test_request_context(
        f"/tools/code_editor/{api_path}",
        method=flask_request.method,
        data=flask_request.data,
        headers=flask_request.headers,
    ):
        try:
            response = current_app.full_dispatch_request()
            return response
        except Exception as e:
            from flask import jsonify

            return jsonify({"success": False, "error": str(e)}), 500
