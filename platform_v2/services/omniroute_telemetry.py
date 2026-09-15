"""Mirror OmniRoute's own call log into task_execution_log.

WHY
---
codex, opencode and the host codex CLI call OmniRoute DIRECTLY over HTTP. They
never touch ``department_dispatcher.dispatch()``, so nothing writes
``task_execution_log`` and nothing enqueues ``dispatch_pending_queue``. Measured
2026-09-14: a host-codex run burned 17,399 tokens and produced ZERO rows, while
the newest ``provider='omniroute'`` row in the platform was four days old.

Consequence: two of the three coding interfaces were invisible to Consciousness →
Token Economy, to A.R.M.A.D.A.'s Dispatch tab and to the dispatch log. A.R.C.H.I.E.
cannot orchestrate what she cannot see, and the Collaboration Tab depends on her
seeing all three.

WHY A COLLECTOR AND NOT A PROXY
-------------------------------
The obvious design is a logging reverse-proxy between the lanes and OmniRoute.
Rejected: it puts a new hop in the inference path, and it has to re-implement
streaming (SSE) correctly or it breaks every lane. OmniRoute ALREADY records
everything we need — ``call_logs`` carries tokens in/out/cache/reasoning,
duration, status, the resolved model and the upstream provider. Reading it costs
the inference path nothing and cannot break a request.

⚠️ WHAT THIS CANNOT DO: TELL THE INTERFACES APART
-------------------------------------------------
Every row in ``call_logs`` carries ``api_key_name='archie-platform'`` — ONE shared
key for every caller. So the gateway physically cannot say whether a call came
from codex, opencode or the host CLI.

It is tempting to read ``requested_model`` as the caller, because the values look
like ``opencode/big-pickle``. THEY ARE NOT. That prefix is OmniRoute's UPSTREAM
PROVIDER (opencode.ai's gateway) — the same list contains ``horde/…``,
``cloudflare-playground/…`` and ``uncloseai/…``. Attributing lanes from it would
produce confident, wrong per-interface numbers.

So these rows are attributed to the GATEWAY, honestly, and the per-interface split
waits on per-lane OmniRoute API keys — at which point ``api_key_name`` becomes the
interface and ``_interface_from()`` below starts returning something real without
any change to the rest of this file.

⚠️ ``worker_type='contract'`` IS LOAD-BEARING, NOT A LABEL
----------------------------------------------------------
The carbon path keys off it: ``carbon_footprint_service.co2_g_sql()`` emits
``WHEN worker_type = 'contract' THEN NULL``, and every Python call site in
``dispatch_routes`` guards ``None if worker_type == 'contract' else co2_g_for(...)``.

That is the ONLY thing stopping these rows being assigned a fabricated carbon
footprint. Carbon here is watts-for-the-model x duration x the CANADA grid factor —
a local-cluster methodology. An OmniRoute call ran on opencode.ai's or horde's
hardware, in an unknown country, on an unknown GPU; the model name ('big-pickle')
matches no local base, so it would silently take the CPU watts constant and produce
a confident number about hardware we do not own and cannot measure.

Changing this to 'ai' or 'internal' would start fabricating that number. Pinned by
``test_omniroute_telemetry.py::test_worker_type_contract_keeps_carbon_n_a``.

TWO SCHEMA FACTS THAT LOOK LIKE BUGS
------------------------------------
* ``call_logs.id`` is a STRING (``'1789423352735-76c216'``), not an integer. The
  watermark compares it with ``>`` as a string — which is fine, and deliberately
  so: it is only ever a tiebreaker WITHIN one millisecond timestamp, and the
  cursor query and the ``ORDER BY`` use the same collation, so the walk is
  self-consistent. Do not "fix" it into an int cast; that raises.
* ``created_at`` is stamped from the CALL's timestamp, not ``now()``. That is what
  makes a first-run backfill safe: rows land in their real historical buckets on
  the Token Economy panel rather than as a spike at import time.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Read-only bind of the archie_omniroute_data volume (docker-compose.yml, mirrored
# onto archie_scheduler — the JOB runs there, and volume drift between the two is a
# documented way to silently degrade scheduled work, KB #263303). The platform runs
# as root and the file is 0644 node:node, so root can read it.
OMNIROUTE_DB = os.getenv("OMNIROUTE_DB_PATH", "/omniroute-data/storage.sqlite")

WATERMARK_KEY = "omniroute:telemetry:watermark"  # "<iso timestamp>|<call_logs.id>"
MAX_BATCH = 500  # bounds one pass; the next cycle continues from the watermark
PROVIDER = "omniroute"

# Serialises concurrent collectors. The watermark is READ and WRITTEN in ONE
# transaction under this lock, so two runs cannot both read the same mark and import
# the same calls twice. The scheduled job is max_instances=1, but a manual
# invocation alongside a scheduled one is exactly the case that would double-count
# the token ledger — and a ledger is the one thing that must not be double-counted.
# try_ (not blocking): if another collector holds it, skip this cycle; the next is
# 10 minutes away and the watermark makes catching up free.
ADVISORY_LOCK_KEY = 0x0DA17E1E

# What a row must carry to be worth a task_execution_log row at all.
REQUIRED_COLUMNS = {
    "id",
    "timestamp",
    "model",
    "provider",
    "status",
    "tokens_in",
    "tokens_out",
    "duration",
    "requested_model",
}


def _interface_from(api_key_name: str | None) -> str:
    """Which coding interface made this call — or 'unknown', honestly.

    ⚠️ Returns 'unknown' for the shared 'archie-platform' key, which is currently
    EVERY row. Deliberately does NOT take requested_model: that is the upstream
    provider, not the caller (see the module docstring). When per-lane keys are
    minted, name them codex-lane / opencode-lane / host-cli and this starts
    returning the real interface with no other change anywhere.
    """
    name = (api_key_name or "").strip().lower()
    for lane in ("codex-lane", "opencode-lane", "host-cli", "codex", "opencode"):
        if name == lane or name.startswith(lane + "-"):
            return lane.replace("-lane", "")
    return "unknown"


def _read_watermark(cur) -> tuple[str, str]:
    """Return (timestamp, id) of the last imported row, or ('','') on a first run."""
    cur.execute("SELECT value FROM platform_settings WHERE key = %s", (WATERMARK_KEY,))
    row = cur.fetchone()
    raw = (row or {}).get("value") or ""
    if "|" in raw:
        ts, _, rid = raw.partition("|")
        return ts, rid
    return "", ""


def _pg_timestamp(iso: str | None) -> str | None:
    """'2026-09-14T22:02:35.120Z' -> '2026-09-14 22:02:35.120' (naive UTC).

    The platform DB runs at timezone=UTC and task_execution_log.created_at is
    `timestamp WITHOUT time zone`, so naive-UTC is the correct storage form here
    (timezone.md: storage UTC, conversion at the display edge). Returns None for
    anything unparseable so the caller can skip the row rather than insert a lie.
    """
    if not iso or not isinstance(iso, str) or len(iso) < 10:
        return None
    return iso.replace("T", " ").replace("Z", "").strip()


def _select_rows(c, ts_mark: str, id_mark: str, max_batch: int):
    """Rows newer than the watermark, oldest first (see the id-is-a-string note)."""
    if ts_mark:
        return c.execute(
            "SELECT * FROM call_logs "
            " WHERE timestamp > ? OR (timestamp = ? AND id > ?) "
            " ORDER BY timestamp, id LIMIT ?",
            (ts_mark, ts_mark, id_mark, max_batch),
        ).fetchall()
    # First run: walk from the beginning. This is a real backfill and it is SAFE
    # because created_at carries each call's own timestamp — the rows land in their
    # true historical buckets, not as a spike at import time.
    return c.execute("SELECT * FROM call_logs ORDER BY timestamp, id LIMIT ?", (max_batch,)).fetchall()


def _import_rows(cur, rows, cols) -> tuple[int, int, int]:
    """Insert one batch. Returns (written, skipped_zero, skipped_bad_timestamp)."""
    written = skipped_zero = skipped_bad = 0
    for r in rows:
        t_in = int(r["tokens_in"] or 0)
        t_out = int(r["tokens_out"] or 0)
        if t_in == 0 and t_out == 0:
            # A 0-token row is a refused or errored call, not inference. Same lesson
            # as the admission gate (fleet.md): counting those as model activity
            # measures the GATE, not the model.
            skipped_zero += 1
            continue

        created = _pg_timestamp(r["timestamp"])
        if created is None:
            skipped_bad += 1
            continue

        key_name = r["api_key_name"] if "api_key_name" in cols else None
        meta = {
            "source": "omniroute_call_logs",
            "omniroute_id": r["id"],
            # UPSTREAM alias (e.g. "opencode/big-pickle") — NOT the caller.
            "requested_model": r["requested_model"],
            "upstream_provider": r["provider"],
            "api_key_name": key_name,
            "interface": _interface_from(key_name),
            "http_status": r["status"],
        }
        for extra in ("tokens_cache_read", "tokens_reasoning"):
            if extra in cols:
                meta[extra] = r[extra]

        # Every value below is a BOUND PARAMETER (%s). psycopg2 adapts them
        # server-side, so no field — json.dumps(meta) included — is ever
        # interpolated into SQL text and none can alter the statement.
        # worker_type='contract' is REQUIRED, not cosmetic: it is what makes
        # carbon n/a for these rows (co2_g_sql emits NULL for 'contract').
        # See the module docstring before changing it.
        cur.execute(
            """
            INSERT INTO task_execution_log
                (agent_name, worker_type, task_type, module_source,
                 model_used, provider, prompt_tokens, completion_tokens,
                 tokens_used, duration_ms, success, capability,
                 request_origin, request_metadata, created_at)
            VALUES (%s, 'contract', 'code', 'omniroute_gateway',
                    %s, %s, %s, %s,
                    %s, %s, %s, 'code',
                    'omniroute', %s, %s)
            """,
            (
                "OmniRoute",
                r["model"] or "unknown",
                PROVIDER,
                t_in,
                t_out,
                t_in + t_out,
                int(r["duration"] or 0),
                int(r["status"] or 0) < 400,
                json.dumps(meta),
                created,
            ),
        )
        written += 1
    return written, skipped_zero, skipped_bad


def collect(dry_run: bool = True, max_batch: int = MAX_BATCH) -> Dict[str, Any]:
    """Copy new OmniRoute call_logs rows into task_execution_log.

    ``dry_run=True`` is the DEFAULT, so an exploratory import cannot inject rows
    into the token ledger. The caller must ask for the write.

    Idempotent via a watermark in ``platform_settings``, read AND written inside a
    single transaction held under ``ADVISORY_LOCK_KEY`` — so neither a crash nor a
    concurrent collector can double-count.

    Returns ``{ok, dry_run, scanned, written, skipped_zero, skipped_bad_ts,
    skipped_locked, watermark, error?}``. Fail-safe: any error returns ok=False.
    """
    out: Dict[str, Any] = {
        "ok": False,
        "dry_run": dry_run,
        "scanned": 0,
        "written": 0,
        "skipped_zero": 0,
        "skipped_bad_ts": 0,
        "skipped_locked": False,
        "watermark": None,
    }

    if not os.path.exists(OMNIROUTE_DB):
        # Not an error worth alarming on: the volume is simply not mounted (e.g. a
        # dev container). Say so once per cycle at warning level and do nothing.
        out["error"] = f"omniroute db not readable at {OMNIROUTE_DB}"
        logger.warning("omniroute_telemetry: %s", out["error"])
        return out

    con = None
    try:
        from database import get_db_cursor

        # immutable=1: OmniRoute writes this DB constantly. A plain read-only open
        # can still touch the -shm/-wal sidecars; immutable promises we never do.
        con = sqlite3.connect(f"file:{OMNIROUTE_DB}?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        c = con.cursor()

        cols = {r["name"] for r in c.execute("PRAGMA table_info(call_logs)")}
        missing = REQUIRED_COLUMNS - cols
        if missing:
            # A third-party schema CAN change under an image bump. Fail LOUD and
            # write nothing, rather than silently logging zeros forever.
            out["error"] = f"call_logs schema changed — missing {sorted(missing)}"
            logger.error("omniroute_telemetry: %s", out["error"])
            return out

        written = skipped_zero = skipped_bad = 0
        watermark = None

        # EVERYTHING that touches the watermark — read, import, write — happens in
        # ONE transaction under an advisory lock. Splitting the read from the write
        # left a window where two collectors could read the same mark and import the
        # same calls twice, double-counting the token ledger (F.O.R.G.E., PR #3339).
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute("SELECT pg_try_advisory_xact_lock(%s) AS got", (ADVISORY_LOCK_KEY,))
            lock_row = cur.fetchone()
            if not (lock_row or {}).get("got"):
                # Another collector is mid-import. Skipping is free: the watermark
                # means the next cycle resumes exactly where that one stops.
                out.update(ok=True, skipped_locked=True)
                logger.info("omniroute_telemetry: another collector holds the lock — skipping this cycle")
                return out

            ts_mark, id_mark = _read_watermark(cur)
            rows = _select_rows(c, ts_mark, id_mark, max_batch)

            out["scanned"] = len(rows)
            if not rows:
                out["ok"] = True
                return out

            watermark = f"{rows[-1]['timestamp']}|{rows[-1]['id']}"
            out["watermark"] = watermark
            if dry_run:
                out["ok"] = True
                return out

            written, skipped_zero, skipped_bad = _import_rows(cur, rows, cols)

            # Same transaction as the inserts: a crash between them cannot leave the
            # watermark ahead of the rows (which would silently drop calls forever).
            cur.execute(
                "INSERT INTO platform_settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (WATERMARK_KEY, watermark),
            )

        out.update(ok=True, written=written, skipped_zero=skipped_zero, skipped_bad_ts=skipped_bad)
        if written or skipped_bad:
            logger.info(
                "omniroute_telemetry: wrote %d row(s) (%d zero-token, %d bad-timestamp " "skipped), watermark %s",
                written,
                skipped_zero,
                skipped_bad,
                watermark,
            )
    except Exception as exc:  # noqa: BLE001 - telemetry must never break the scheduler
        logger.error("omniroute_telemetry failed: %s", exc, exc_info=True)
        out["error"] = str(exc)
    finally:
        if con is not None:
            con.close()
    return out
