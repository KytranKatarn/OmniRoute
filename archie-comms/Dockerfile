FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r archie && useradd -r -g archie -m archie

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R archie:archie /app

USER archie

EXPOSE 3002

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:3002/api/health || exit 1

# 1 worker (not 2): the OAuth `state`/PKCE verifier is stored in per-worker in-memory
# (_pending_states in kytran_auth.py). With >1 worker, /auth/kytran/login and the OAuth
# callback can land on different workers → state not found → intermittent "Session Expired".
# This is a single-user admin cockpit, so one worker is plenty. (To restore 2+, move
# _pending_states to a shared store — DB/Redis.)
CMD ["gunicorn", "--bind", "0.0.0.0:3002", "--workers", "1", "--timeout", "120", "app_comms:app"]
