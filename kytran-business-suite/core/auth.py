"""
core/auth.py — Authentication for Kytran Business Suite.

Provides:
- User model (Flask-Login UserMixin)
- init_login_manager(app)
- auth_bp Blueprint: /auth/login, /auth/signup, /auth/logout, /auth/sso, /auth/google/callback
"""

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from core.database import create_tenant_schema, get_db_cursor

auth_bp = Blueprint("auth", __name__, template_folder="../shared/templates")
login_manager = LoginManager()


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------


class User(UserMixin):
    """Minimal user model backed by the public.users table."""

    def __init__(self, id, email, name, is_active=True):
        self.id = id
        self.email = email
        self.name = name
        self._is_active = is_active

    @property
    def is_active(self):
        return self._is_active

    @classmethod
    def get_by_id(cls, user_id):
        """Load a User from the DB by primary key. Returns None if not found."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            cur.execute(
                "SELECT id, email, name, is_active FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return cls(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            is_active=row["is_active"],
        )

    @classmethod
    def get_by_email(cls, email):
        """Load a User from the DB by email. Returns None if not found."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            cur.execute(
                "SELECT id, email, name, password_hash, is_active FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return cls(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            is_active=row["is_active"],
        ), row["password_hash"]


# ---------------------------------------------------------------------------
# Login manager setup
# ---------------------------------------------------------------------------


def init_login_manager(app):
    """Configure Flask-Login on the given app."""
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html"), 400

        result = User.get_by_email(email)
        if result is None:
            flash("Invalid email or password.", "error")
            return render_template("login.html"), 401

        user, password_hash = result

        if not check_password_hash(password_hash, password):
            flash("Invalid email or password.", "error")
            return render_template("login.html"), 401

        if not user.is_active:
            flash("Your account is inactive. Please contact support.", "error")
            return render_template("login.html"), 403

        # Find their first tenant
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            cur.execute(
                """
                SELECT tenant_id, role
                FROM tenant_users
                WHERE user_id = %s
                ORDER BY tenant_id
                LIMIT 1
                """,
                (user.id,),
            )
            tu = cur.fetchone()

        if tu is None:
            flash("No tenant associated with this account.", "error")
            return render_template("login.html"), 403

        login_user(user)
        session["tenant_id"] = tu["tenant_id"]
        session["tenant_role"] = tu["role"]

        next_url = request.args.get("next") or url_for("dashboard")
        return redirect(next_url)

    return render_template("login.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        company = request.form.get("company", "").strip()
        password = request.form.get("password", "")

        # Validation
        if not name or not email or not company or not password:
            flash("All fields are required.", "error")
            return render_template("signup.html"), 400

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("signup.html"), 400

        # Check duplicate email
        result = User.get_by_email(email)
        if result is not None:
            flash("An account with that email already exists.", "error")
            return render_template("signup.html"), 409

        password_hash = generate_password_hash(password)

        try:
            with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
                # Create user
                cur.execute(
                    """
                    INSERT INTO users (email, name, password_hash, is_active)
                    VALUES (%s, %s, %s, TRUE)
                    RETURNING id
                    """,
                    (email, name, password_hash),
                )
                user_id = cur.fetchone()["id"]

                # Create tenant (slug from company name)
                slug = _slugify(company)
                cur.execute(
                    """
                    INSERT INTO tenants (name, slug, tier, is_active)
                    VALUES (%s, %s, 'free', TRUE)
                    ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug || '_' || EXTRACT(EPOCH FROM NOW())::int
                    RETURNING id
                    """,
                    (company, slug),
                )
                tenant_id = cur.fetchone()["id"]

                # Link user as owner
                cur.execute(
                    """
                    INSERT INTO tenant_users (tenant_id, user_id, role)
                    VALUES (%s, %s, 'owner')
                    ON CONFLICT DO NOTHING
                    """,
                    (tenant_id, user_id),
                )

                # Enable free-tier modules
                cur.execute(
                    """
                    SELECT slug FROM module_catalog WHERE tier_required = 'free'
                    """
                )
                free_modules = [r["slug"] for r in cur.fetchall()]
                for mod_slug in free_modules:
                    cur.execute(
                        """
                        INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
                        VALUES (%s, %s, TRUE)
                        ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
                        """,
                        (tenant_id, mod_slug),
                    )

        except Exception as exc:
            flash(f"Registration failed: {exc}", "error")
            return render_template("signup.html"), 500

        # Create tenant schema
        try:
            create_tenant_schema(tenant_id)
        except Exception:
            pass  # Non-fatal — schema may already exist

        # Log in the new user
        user = User.get_by_id(user_id)
        login_user(user)
        session["tenant_id"] = tenant_id
        session["tenant_role"] = "owner"

        return redirect(url_for("dashboard"))

    return render_template("signup.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/sso")
def sso():
    from flask import abort

    abort(501)


@auth_bp.route("/google/callback")
def google_callback():
    from flask import abort

    abort(501)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert a company name to a URL-safe slug."""
    import re

    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug.strip("-")
    return slug or "tenant"
