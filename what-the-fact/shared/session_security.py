"""Session signing configuration shared by the consumer and tech applications."""

import os
import secrets


def session_signing_key(environ=None):
    """Require a configured key, with random ephemeral keys for explicit local dev.

    Development keys intentionally change on each app creation. Multi-worker or
    persistent sessions must configure FLASK_SECRET_KEY, including in development.
    """
    environ = os.environ if environ is None else environ
    configured = environ.get("FLASK_SECRET_KEY", "")
    if configured:
        return configured
    if environ.get("WTF_ALLOW_INSECURE_SECRET") == "1":
        return secrets.token_urlsafe(48)
    raise RuntimeError("FLASK_SECRET_KEY must be configured")
