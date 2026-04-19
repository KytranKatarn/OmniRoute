# syntax=docker/dockerfile:1.7
# Build context: repo root (see docker-compose.yml)
#
# Media Hub standalone image — Tier 1 of Project #273 extraction playbook.
# See .claude/rules/standalone-extraction.md for the compliance contract.

FROM python:3.11-slim AS base

# Security: no root, no cache bloat, pinned base tag above.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r mediahub --gid 10001 \
    && useradd  -r -g mediahub --uid 10001 --home /app --shell /sbin/nologin mediahub

WORKDIR /app

# Install deps first (stable layer)
COPY standalone/media_hub/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Standalone shims (database.py, app.py, auth, users) land at /app/ so Python
# resolves them first.
COPY standalone/media_hub/database.py    /app/database.py
COPY standalone/media_hub/app.py         /app/app.py
COPY standalone/media_hub/auth_routes.py /app/auth_routes.py
COPY standalone/media_hub/users.py       /app/users.py
COPY standalone/media_hub/user_routes.py /app/user_routes.py
COPY standalone/media_hub/templates/     /app/templates/
COPY standalone/media_hub/scripts/       /app/scripts/

# Platform templates the Media Hub route renders directly
# (the blueprint static/standalone base is already inside tools/media_hub/
#  via #2151; these two live in platform_v2/templates and need lifting).
COPY platform_v2/templates/tools/media_hub.html          /app/templates/tools/media_hub.html
COPY platform_v2/templates/includes/lcars-header.html    /app/templates/includes/lcars-header.html

# Platform /static/ assets the Media Hub template hard-codes references to.
# Flask(__name__) default static_folder=./static → served at /static/*.
COPY platform_v2/static/css/media-hub.css      /app/static/css/media-hub.css
COPY platform_v2/static/css/lcars-header.css   /app/static/css/lcars-header.css
COPY platform_v2/static/css/lcars-frames.css   /app/static/css/lcars-frames.css
COPY platform_v2/static/js/media-hub.js        /app/static/js/media-hub.js
COPY platform_v2/static/js/media-hub-sw.js     /app/static/js/media-hub-sw.js
COPY platform_v2/static/js/lcars-header.js     /app/static/js/lcars-header.js
COPY platform_v2/static/manifest.json          /app/static/manifest.json
COPY platform_v2/static/icons/                 /app/static/icons/

# The Media Hub module itself — this is the whole product
COPY platform_v2/tools/media_hub/ /app/tools/media_hub/

# Standalone is always in standalone mode by construction
ENV MEDIA_HUB_STANDALONE=1 \
    PYTHONPATH=/app

USER mediahub

EXPOSE 8105

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8105/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8105", "--workers", "2", "--timeout", "60", "app:app"]
