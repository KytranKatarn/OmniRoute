from flask_login import current_user
from werkzeug.exceptions import Forbidden


def authenticated_user_id(requested=None):
    user_id = getattr(current_user, "id", None)
    if user_id is None:
        raise Forbidden(description="Authentication is required")
    if requested is not None and str(requested) != str(user_id):
        raise Forbidden(description="The requested user does not match the authenticated user")
    try:
        return int(user_id)
    except (TypeError, ValueError) as exc:
        raise Forbidden(description="Authenticated user identity is invalid") from exc
