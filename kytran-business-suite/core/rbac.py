from functools import wraps

from flask import abort, session


def require_role(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            role = session.get("tenant_role", "viewer")
            if role not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)

        return wrapper

    return decorator


def is_owner():
    return session.get("tenant_role") == "owner"


def is_admin_or_above():
    return session.get("tenant_role") in ("owner", "admin")
