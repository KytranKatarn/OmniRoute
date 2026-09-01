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
#
# ⚠️ THREADS, NOT WORKERS — and the distinction is load-bearing twice over.
#
# THE BUG THIS FIXES. With the default SYNC worker, gunicorn's worker loop is
#   notify() -> accept() -> handle()
# and handle() runs the request INLINE. A request that takes longer than
# --timeout means the worker never reaches notify() again, so the master
# concludes it is hung and SIGKILLs it — taking the LISTENER down with it.
# One slow request therefore took the ENTIRE service offline, including
# /api/health, which is why the container sat `unhealthy` while the process was
# alive and happily logging. Measured 2026-09-01, a clean hourly signature:
#
#   08:22:03 WORKER TIMEOUT -> boot      09:22:03 WORKER TIMEOUT -> boot
#   08:24:04 WORKER TIMEOUT -> boot      09:24:04 WORKER TIMEOUT -> boot
#      (killed 121s after booting; then healthy for ~58 min; repeat)
#
# The gthread worker keeps its accept/notify loop on the MAIN thread and runs
# requests in a thread pool, so the heartbeat survives a slow request and only
# ONE thread is occupied by it.
#
# WHY NOT MORE WORKERS. `start_background_services()` (watchdog + queue + triage
# + briefing) is started from app import, so N workers = N of each — N watchdogs
# alerting, N queue processors racing the same rows. Same trap as the platform's
# --workers 4 (KB #282671), plus the OAuth reason above. Threads give
# concurrency while keeping exactly one of each background service.
#
# THREAD SAFETY: database.get_db_cursor() opens a FRESH psycopg2 connection per
# call and closes it in `finally` — no shared connection, no module-level pool —
# so concurrent handlers do not share DB state.
#
# --access-logfile: there was NO access log, which is exactly why the hourly
# stall could not be attributed to a caller. %(M)d prints per-request ms, so the
# next slow request names itself instead of needing to be inferred.
CMD ["gunicorn", "--bind", "0.0.0.0:3002", \
     "--workers", "1", \
     "--threads", "8", \
     "--worker-class", "gthread", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--access-logformat", "%(h)s \"%(r)s\" %(s)s %(b)s %(M)dms", \
     "app_comms:app"]
