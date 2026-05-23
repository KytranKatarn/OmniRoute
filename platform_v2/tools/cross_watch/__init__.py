"""Cross-Watch Alert System — hub-side module.

Provides:
  - shared.entities registry (followable persons, orgs, topics, departments)
  - shared.user_follows — subscriber → entity mapping
  - shared.cross_watch_signals — what each Watch product reports
  - shared.cross_watch_alerts — per-user notifications

API prefix: /api/cross-watch/*
Auth: Bearer CROSS_WATCH_SERVICE_TOKEN + X-User-Email header
"""

from flask import Blueprint

cross_watch_bp = Blueprint("cross_watch", __name__)

from . import routes  # noqa: E402, F401 — registers routes on blueprint
