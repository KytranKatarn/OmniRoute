"""
User account management — standalone Media Hub.

Admin-only at /admin/users:
    list / create / delete / enable-disable / toggle-admin / reset-password
Any authenticated user at /profile:
    change own password

Mounted at app level (not inside the media_hub blueprint) so the URLs
are clean and not shielded by the media_hub auth gate — we apply our
own decorator that also enforces admin-only where appropriate.
"""

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for, abort
from flask_login import current_user, login_required

from users import (
    authenticate,
    count_admins,
    create_user,
    delete_user,
    get_user,
    list_users,
    set_active,
    set_admin,
    set_password,
)


user_mgmt_bp = Blueprint("user_mgmt", __name__)


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


@user_mgmt_bp.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    error = None
    notice = None

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                username = (request.form.get("username") or "").strip()
                password = request.form.get("password") or ""
                is_admin = request.form.get("is_admin") == "on"
                if not username or not password:
                    error = "Username and password are required."
                elif len(password) < 8:
                    error = "Password must be at least 8 characters."
                else:
                    create_user(username, password, is_admin=is_admin)
                    notice = f"Created user {username}."
            elif action in {"enable", "disable", "toggle_admin", "reset_password", "delete"}:
                uid = int(request.form["user_id"])
                if uid == current_user.id and action in {"disable", "toggle_admin", "delete"}:
                    error = "You cannot modify your own admin/active status from this screen."
                else:
                    if action == "enable":
                        set_active(uid, True)
                        notice = "User enabled."
                    elif action == "disable":
                        set_active(uid, False)
                        notice = "User disabled."
                    elif action == "toggle_admin":
                        target = get_user(uid)
                        set_admin(uid, not target.is_admin)
                        notice = "Admin flag toggled."
                    elif action == "reset_password":
                        new_pw = request.form.get("new_password") or ""
                        if len(new_pw) < 8:
                            error = "New password must be at least 8 characters."
                        else:
                            set_password(uid, new_pw)
                            notice = "Password reset."
                    elif action == "delete":
                        delete_user(uid)
                        notice = "User deleted."
        except ValueError as e:
            error = str(e)

    users = list_users()
    return render_template(
        "admin_users.html",
        users=users,
        current_user_id=current_user.id,
        admin_count=count_admins(),
        error=error,
        notice=notice,
    )


@user_mgmt_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    error = None
    notice = None
    if request.method == "POST":
        current_pw = request.form.get("current_password") or ""
        new_pw = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if not authenticate(current_user.username, current_pw):
            error = "Current password is wrong."
        elif len(new_pw) < 8:
            error = "New password must be at least 8 characters."
        elif new_pw != confirm:
            error = "New password and confirmation do not match."
        else:
            set_password(current_user.id, new_pw)
            notice = "Password changed."
    return render_template("profile.html", error=error, notice=notice)
