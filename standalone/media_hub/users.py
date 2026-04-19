"""
Standalone User Model + Bootstrap
=================================
Flask-Login-backed user model for the standalone Media Hub container.
Only used when MEDIA_HUB_STANDALONE=1 — in platform-embedded mode the
ARCHIE users table is authoritative and this file is never imported.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db_cursor

log = logging.getLogger(__name__)


@dataclass
class User(UserMixin):
    id: int
    username: str
    is_admin: bool
    is_active: bool = True

    def get_id(self) -> str:
        return str(self.id)


def _row_to_user(row) -> Optional[User]:
    if not row:
        return None
    # Works whether the cursor returns tuple or RealDictRow
    if isinstance(row, dict):
        return User(
            id=row["id"],
            username=row["username"],
            is_admin=row["is_admin"],
            is_active=row["is_active"],
        )
    id_, username, _hash, is_admin, is_active, _c, _l = row
    return User(id=id_, username=username, is_admin=is_admin, is_active=is_active)


def load_user(user_id: str) -> Optional[User]:
    """Flask-Login user_loader."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            "SELECT id, username, password_hash, is_admin, is_active, created_at, last_login_at "
            "FROM media_hub_users WHERE id = %s AND is_active = TRUE",
            (uid,),
        )
        return _row_to_user(cur.fetchone())


def authenticate(username: str, password: str) -> Optional[User]:
    with get_db_cursor(cursor_factory=None, commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id, username, password_hash, is_admin, is_active, created_at, last_login_at "
            "FROM media_hub_users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
        if not row:
            return None
        _id, _u, pw_hash, is_admin, is_active, *_ = row
        if not is_active or not check_password_hash(pw_hash, password):
            return None
        cur.execute("UPDATE media_hub_users SET last_login_at = CURRENT_TIMESTAMP WHERE id = %s", (_id,))
    return User(id=_id, username=_u, is_admin=is_admin, is_active=is_active)


def create_user(username: str, password: str, is_admin: bool = False) -> User:
    pw_hash = generate_password_hash(password)
    with get_db_cursor(cursor_factory=None, commit=True) as (_conn, cur):
        cur.execute(
            "INSERT INTO media_hub_users (username, password_hash, is_admin) "
            "VALUES (%s, %s, %s) RETURNING id",
            (username, pw_hash, is_admin),
        )
        new_id = cur.fetchone()[0]
    return User(id=new_id, username=username, is_admin=is_admin, is_active=True)


def list_users() -> list:
    with get_db_cursor(cursor_factory=None) as (_c, cur):
        cur.execute(
            "SELECT id, username, is_admin, is_active, created_at, last_login_at "
            "FROM media_hub_users ORDER BY id"
        )
        return [
            {
                "id": r[0],
                "username": r[1],
                "is_admin": r[2],
                "is_active": r[3],
                "created_at": r[4],
                "last_login_at": r[5],
            }
            for r in cur.fetchall()
        ]


def count_admins() -> int:
    with get_db_cursor(cursor_factory=None) as (_c, cur):
        cur.execute("SELECT COUNT(*) FROM media_hub_users WHERE is_admin = TRUE AND is_active = TRUE")
        return cur.fetchone()[0]


def get_user(user_id: int) -> Optional[User]:
    with get_db_cursor(cursor_factory=None) as (_c, cur):
        cur.execute(
            "SELECT id, username, password_hash, is_admin, is_active, created_at, last_login_at "
            "FROM media_hub_users WHERE id = %s",
            (user_id,),
        )
        return _row_to_user(cur.fetchone())


def set_password(user_id: int, new_password: str) -> None:
    with get_db_cursor(cursor_factory=None, commit=True) as (_c, cur):
        cur.execute(
            "UPDATE media_hub_users SET password_hash = %s WHERE id = %s",
            (generate_password_hash(new_password), user_id),
        )


def set_active(user_id: int, active: bool) -> None:
    with get_db_cursor(cursor_factory=None, commit=True) as (_c, cur):
        cur.execute(
            "UPDATE media_hub_users SET is_active = %s WHERE id = %s",
            (active, user_id),
        )


def set_admin(user_id: int, is_admin: bool) -> None:
    # Guard: never leave zero active admins
    if not is_admin and count_admins() <= 1:
        u = get_user(user_id)
        if u and u.is_admin:
            raise ValueError("Cannot demote the last active admin")
    with get_db_cursor(cursor_factory=None, commit=True) as (_c, cur):
        cur.execute(
            "UPDATE media_hub_users SET is_admin = %s WHERE id = %s",
            (is_admin, user_id),
        )


def delete_user(user_id: int) -> None:
    # Guard: never delete the last admin
    u = get_user(user_id)
    if u and u.is_admin and count_admins() <= 1:
        raise ValueError("Cannot delete the last active admin")
    with get_db_cursor(cursor_factory=None, commit=True) as (_c, cur):
        cur.execute("DELETE FROM media_hub_users WHERE id = %s", (user_id,))


def bootstrap_admin_if_empty() -> None:
    """If the users table is empty and MEDIA_HUB_ADMIN_PASSWORD is set,
    create the initial admin. Safe to call on every app boot — no-ops
    once any user exists."""
    admin_pw = os.getenv("MEDIA_HUB_ADMIN_PASSWORD")
    if not admin_pw:
        log.info("bootstrap_admin: MEDIA_HUB_ADMIN_PASSWORD not set — skipping")
        return
    with get_db_cursor(cursor_factory=None) as (_conn, cur):
        cur.execute("SELECT COUNT(*) FROM media_hub_users")
        (count,) = cur.fetchone()
    if count > 0:
        log.info("bootstrap_admin: %d user(s) already exist — skipping", count)
        return
    create_user("admin", admin_pw, is_admin=True)
    log.info("bootstrap_admin: created initial admin user")
