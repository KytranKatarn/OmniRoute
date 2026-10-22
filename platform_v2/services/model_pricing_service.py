"""ONE pricing source for the platform's token economy.

WHY THIS EXISTS
---------------
Measured 2026-10-21: ``task_execution_log.cost`` was **0 on every one of its
2,127,074 rows**. Not "small" — zero. The DS9 tab therefore showed "not
tracked" rather than a ``$0.00`` that reads like a real spend of nothing.

The reason was three pricing sources that all missed:

  * ``provider_pricing`` (this platform's table) — 23 hand-seeded rows from
    2025-12-29, covering models the platform stopped using months ago.
  * ``ai_bridge.archie_bridge.calculate_cost`` — an inline dict labelled
    "as of Dec 2024", covering a generation of models that is gone.
  * The DS9's own table (``DEFAULT_PRICING`` / ``KNOWN_MODEL_PRICING``) — 38
    providers and 1,001 model entries, current, and the only one that covers
    what the gateway actually dispatches.

So the platform was pricing against a table nobody updates, while the table
that IS current lived in the gateway and was never read.

THE FIX: the gateway is the pricing source of truth, and the platform reads
it. ``GET /api/pricing`` on the DS9 returns the same structure the gateway
itself uses. This module fetches it, caches it, mirrors it into
``provider_pricing`` (so the platform can still price while the gateway is
down), and resolves a price for any ``(provider, model)`` pair.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
The gateway's own ``getModelPricing`` ends with a FALLBACK ESTIMATE — an
unknown model is priced at $5/$15 per 1M and flagged ``isEstimated``. That is
right for the gateway (it needs a number to rank models by cost) and wrong
for accounting. An invented number that lands in a ledger reads as a fact.

So here, an unknown model resolves to ``None`` — NOT TRACKED — and the caller
writes NULL rather than 0. A model known to be FREE resolves to a price of
0.0, which is a real, known price and is written as 0. Those are different
facts and this module keeps them apart.

    price = resolve_price("claude", "claude-fable-5-1")
    # -> {"input_per_1m": 10.0, "output_per_1m": 50.0, "source": "ds9", "is_free": False}
    cost = compute_cost("claude", "claude-fable-5-1", 1_000_000, 1_000_000)
    # -> 60.0
    compute_cost("some-provider", "some-unknown-model", 100, 100)
    # -> None   (NOT tracked — never a fabricated 0.0)
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DS9_API_BASE_URL = os.getenv("DS9_API_BASE_URL", "http://host.docker.internal:20129").rstrip("/")
DS9_PRICING_PATH = os.getenv("DS9_PRICING_PATH", "/api/pricing")

# The gateway is reachable under different names depending on WHERE the code
# runs: inside the platform container ``host.docker.internal`` resolves, and
# on the host it does not (it is a Docker-internal alias) while 127.0.0.1 does.
# Both are tried, in order, so the same code works in both places.
DS9_BASE_URL_CANDIDATES = [
    DS9_API_BASE_URL,
    os.getenv("DS9_API_BASE_URL_LOCAL", "http://127.0.0.1:20129").rstrip("/"),
]

# How long a fetched pricing table is trusted before it is refreshed.
PRICING_TTL_SECONDS = float(os.getenv("MODEL_PRICING_TTL_SECONDS", "900"))
PRICING_FETCH_TIMEOUT = float(os.getenv("MODEL_PRICING_FETCH_TIMEOUT", "15"))

# Free providers: a call to these costs nothing, and that is a KNOWN price.
# Deliberately SMALL. The gateway has a much wider "explicit free" list, but
# that list drives its ROUTING (which models a free tier may use), not
# accounting. `ollama_cloud` is on the gateway's free list because the platform
# dispatches local-model calls through it, and calling it "free" would have
# reported 9,975 paid cloud calls as $0.00 — exactly the lie this module
# exists to stop. Local `ollama` IS free (no API cost at all).
#
# A provider/model is otherwise priced by the gateway's table, including the
# entries that are 0/0 — those are KNOWN-FREE prices and are reported as $0.00.
FREE_PROVIDERS = {
    "ollama",  # local models: no API cost
    "cloudflare-playground",
    "cfp",
    "duckduckgo-web",
    "devin-cli-agentic",
    "uncloseai",
    "aihorde",
    "opencode-zen",
}

# The OFFLINE FLOOR: used only when the gateway's table has nothing to say.
# The gateway's table ALWAYS WINS over this map, because the gateway is the
# source of truth and the two have been known to disagree (groq is 0/0 in the
# gateway's table — a free tier — while a hand-written map said $0.59/$0.79).
# Entries here are restricted to models the gateway does not price at all.
KNOWN_MODEL_PRICING: Dict[Tuple[str, str], Dict[str, float]] = {
    ("cohere", "command-a-03-2025"): {"input": 2.5, "output": 10.0},
    ("cohere", "command-r"): {"input": 0.5, "output": 1.5},
    ("cohere", "command"): {"input": 1.0, "output": 2.0},
}

_lock = threading.Lock()
_cache: Dict[str, Dict[str, Dict[str, float]]] = {}
_cache_fetched_at: float = 0.0
_cache_source: str = "empty"
_model_index: Dict[str, Dict[str, float]] = {}


def normalize_model(model: Optional[str]) -> str:
    """The gateway's own normalization: last path segment, lowercased.

    Model ids arrive namespaced (``cfp/zai-org/glm-5.2``,
    ``turboderp/Qwen3.8-27B-exl3``), and the gateway prices those by their last
    segment. The platform must agree or the same call prices differently on
    the two sides of the fence.
    """
    if not model:
        return ""
    return str(model).split("/")[-1].strip().lower()


# Local inference: the platform's own mesh nodes and browsers. No API cost —
# this is a fact about the channel, not an estimate.
LOCAL_PROVIDERS = {
    "fleet_node",
    "fleet-node",
    "local",
    "ollama",
    "ollama_local",
    "ollama-vision",
    "ollama_vision",
    "browser",
    "browser_headed",
    "internal",
}

# A trailing snapshot/version suffix: -0731, -0613, -20241022. Stripped so a
# dated model id resolves to its base price (deepseek-v4-flash-0731 ->
# deepseek-v4-flash). A single digit is NOT stripped, so claude-haiku-5-5 is
# left alone.
_DATE_SUFFIX_RE = re.compile(r"^(.*?)-(\d{2,8})$")


def model_candidates(model: Optional[str]) -> list:
    """Progressively simpler spellings of a model id, most specific first.

    The platform's ledger records the ids the gateway ACTUALLY dispatched,
    which are often a little more specific than the ids the pricing table is
    keyed by:

      * ``minimax-m2.5:cloud``  -> ``minimax-m2.5``   (Ollama-style variant tag)
      * ``deepseek-v4-flash-0731`` -> ``deepseek-v4-flash`` (snapshot suffix)

    Each candidate is tried against the pricing table in order, so the most
    specific match still wins.
    """
    if not model:
        return []
    segment = str(model).split("/")[-1].strip().lower()
    if not segment:
        return []
    out = [segment]
    if ":" in segment:
        base = segment.split(":", 1)[0].strip()
        if base and base not in out:
            out.append(base)
    # Strip up to two trailing date suffixes from each spelling.
    for candidate in list(out):
        current = candidate
        for _ in range(2):
            match = _DATE_SUFFIX_RE.match(current)
            if not match or not match.group(1):
                break
            current = match.group(1)
            if current not in out:
                out.append(current)
    return out


def _price_from_entry(entry: Any) -> Optional[Dict[str, float]]:
    """Pull a numeric input/output price out of a pricing-table entry."""
    if not isinstance(entry, dict):
        return None
    inp = entry.get("input")
    out = entry.get("output")
    if inp is None and out is None:
        return None
    try:
        inp = float(inp if inp is not None else 0)
        out = float(out if out is not None else 0)
    except (TypeError, ValueError):
        return None
    return {"input": inp, "output": out}


def _reindex() -> None:
    """Build the model-only index used by the cross-provider fallback."""
    global _model_index
    index: Dict[str, Dict[str, float]] = {}
    for provider_models in _cache.values():
        for model, price in provider_models.items():
            # Index every spelling of the id, so a lookup for a tag-stripped or
            # snapshot-stripped variant finds it.
            for name in model_candidates(model):
                if not name:
                    continue
                existing = index.get(name)
                if existing is None or (existing["input"] == 0 and price["input"] != 0):
                    # Prefer a non-zero price: a 0/0 row is "free", and a paid row
                    # for the same model id is the more specific truth.
                    index[name] = price
    _model_index = index


def _fetch_ds9_pricing() -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """GET the gateway's pricing table. Returns None if it cannot be reached."""
    key = (os.getenv("OMNIROUTE_API_KEY") or "").strip()
    if not key:
        logger.debug("model pricing: OMNIROUTE_API_KEY not set — skipping DS9 fetch")
        return None

    import json

    last_error = "no candidate base URL"
    for base in DS9_BASE_URL_CANDIDATES:
        url = f"{base}{DS9_PRICING_PATH}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(req, timeout=PRICING_FETCH_TIMEOUT) as resp:
                raw = json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            last_error = f"{base}: {exc}"
            continue

        if not isinstance(raw, dict):
            last_error = f"{base}: unexpected payload type {type(raw).__name__}"
            continue

        out: Dict[str, Dict[str, Dict[str, float]]] = {}
        for provider, models in raw.items():
            if not isinstance(models, dict):
                continue
            entry: Dict[str, Dict[str, float]] = {}
            for model, price in models.items():
                parsed = _price_from_entry(price)
                if parsed is not None:
                    entry[str(model)] = parsed
            if entry:
                out[str(provider)] = entry
        if out:
            return out
        last_error = f"{base}: no priced models in payload"

    logger.warning("model pricing: DS9 pricing fetch failed (%s)", last_error)
    return None


def _load_db_pricing() -> Dict[str, Dict[str, Dict[str, float]]]:
    """Read the mirrored pricing table out of ``provider_pricing``.

    This is the offline floor: if the gateway is unreachable, the platform can
    still price from the last successful mirror.
    """
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT provider, model, input_cost_per_1m, output_cost_per_1m "
                "FROM provider_pricing WHERE model <> '*'"
            )
            rows = cur.fetchall() or []
    except Exception as exc:  # noqa: BLE001 - pricing must never break a request
        logger.debug("model pricing: DB mirror read failed (%s)", exc)
        return out

    for row in rows:
        try:
            provider = str(row["provider"])
            model = str(row["model"])
            inp = float(row["input_cost_per_1m"] or 0)
            outp = float(row["output_cost_per_1m"] or 0)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        out.setdefault(provider, {})[model] = {"input": inp, "output": outp}
    return out


def refresh(force: bool = False) -> int:
    """Refresh the pricing cache from the gateway. Returns the entry count.

    Never raises. On failure the previous cache (or the DB mirror) stands.
    """
    global _cache, _cache_fetched_at, _cache_source
    now = time.monotonic()
    with _lock:
        if not force and _cache and (now - _cache_fetched_at) < PRICING_TTL_SECONDS:
            return sum(len(m) for m in _cache.values())

    fetched = _fetch_ds9_pricing()
    mirrored = _load_db_pricing()
    if fetched:
        merged = {k: dict(v) for k, v in fetched.items()}
        for provider, models in mirrored.items():
            merged.setdefault(provider, {}).update(models)
        source = "ds9"
    elif mirrored:
        merged = mirrored
        source = "db-mirror"
    else:
        merged = {}
        source = "empty"

    with _lock:
        _cache = merged
        _cache_fetched_at = now
        _cache_source = source
        _reindex()
    logger.info(
        "model pricing: refreshed from %s — %d providers, %d models",
        source,
        len(merged),
        sum(len(m) for m in merged.values()),
    )
    return sum(len(m) for m in merged.values())


def _ensure_loaded() -> None:
    with _lock:
        if _cache:
            return
    refresh(force=True)


def mirror_to_db() -> int:
    """Write the fetched pricing table into ``provider_pricing``.

    Keeps the platform's table in step with the gateway's, so the platform can
    still price while the gateway is down. Returns rows upserted.
    """
    _ensure_loaded()
    with _lock:
        snapshot = {k: dict(v) for k, v in _cache.items()}
    if not snapshot:
        return 0
    try:
        from datetime import date

        from database import get_db_cursor

        rows = []
        for provider, models in snapshot.items():
            for model, price in models.items():
                rows.append((provider, model, price["input"], price["output"], date.today()))
        if not rows:
            return 0
        with get_db_cursor(commit=True) as (conn, cur):
            from psycopg2.extras import execute_values

            execute_values(
                cur,
                """
                INSERT INTO provider_pricing
                    (provider, model, input_cost_per_1m, output_cost_per_1m,
                     effective_date, notes)
                VALUES %s
                ON CONFLICT (provider, model, effective_date) DO UPDATE
                SET input_cost_per_1m = EXCLUDED.input_cost_per_1m,
                    output_cost_per_1m = EXCLUDED.output_cost_per_1m,
                    notes = EXCLUDED.notes
                """,
                [(p, m, i, o, d, "mirrored from DS9 /api/pricing") for (p, m, i, o, d) in rows],
            )
        return len(rows)
    except Exception as exc:  # noqa: BLE001 - mirroring must never break pricing
        logger.warning("model pricing: mirror to DB failed (%s)", exc)
        return 0


def resolve_price(provider: Optional[str], model: Optional[str]) -> Optional[Dict[str, Any]]:
    """Resolve the price for one call. ``None`` means NOT TRACKED.

    Resolution order:

      1. a FREE CHANNEL -> 0.0 (a known price). The channel decides what the
         platform PAYS. A model reached through the Cloudflare Playground costs
         the platform nothing, whatever the model's list price says — and the
         gateway's table prices the MODEL, not the channel.
      2. the gateway's table, provider-scoped, exact model id
      3. the gateway's table, provider-scoped, normalized model id
      4. the gateway's table, model id only (any provider) — this is what prices
         ``minimax-m2.5`` for a call the platform made through ``ollama_cloud``:
         the gateway dispatches it under a different provider id but prices the
         MODEL the same way.
      5. the offline floor (KNOWN_MODEL_PRICING), for models the gateway does
         not price at all

    The gateway's table is checked before the floor, because the gateway is the
    source of truth and the two have been known to disagree.

    The gateway's final fallback — an ESTIMATE for unknown models — is
    deliberately NOT reproduced. An estimate in a ledger reads as a fact.
    """
    if not model:
        return None
    prov = (provider or "").strip().lower()
    candidates = model_candidates(model)
    if not candidates:
        return None

    # 1. a free channel is a known price of zero
    if prov in FREE_PROVIDERS or prov in LOCAL_PROVIDERS:
        return {
            "input_per_1m": 0.0,
            "output_per_1m": 0.0,
            "source": "free-channel" if prov in FREE_PROVIDERS else "local-channel",
            "is_free": True,
        }

    _ensure_loaded()
    with _lock:
        table = {k: dict(v) for k, v in _cache.items()}
        model_index = dict(_model_index)

    # 2 & 3. provider-scoped
    if prov:
        models = table.get(prov) or table.get(provider or "") or {}
        for candidate in candidates:
            hit = _price_from_entry(models.get(candidate))
            if hit is not None:
                return {
                    "input_per_1m": hit["input"],
                    "output_per_1m": hit["output"],
                    "source": "ds9",
                    "is_free": hit["input"] == 0 and hit["output"] == 0,
                }

    # 4. model-only, any provider
    for candidate in candidates:
        hit = model_index.get(candidate)
        if hit is not None:
            return {
                "input_per_1m": hit["input"],
                "output_per_1m": hit["output"],
                "source": "ds9-model-only",
                "is_free": hit["input"] == 0 and hit["output"] == 0,
            }

    # 5. the offline floor
    for candidate in candidates:
        hit = KNOWN_MODEL_PRICING.get((prov, candidate))
        if hit:
            return {
                "input_per_1m": hit["input"],
                "output_per_1m": hit["output"],
                "source": "builtin",
                "is_free": hit["input"] == 0 and hit["output"] == 0,
            }

    return None


def compute_cost(
    provider: Optional[str],
    model: Optional[str],
    prompt_tokens: Optional[int] = 0,
    completion_tokens: Optional[int] = 0,
) -> Optional[float]:
    """The dollar cost of one call. ``None`` means NOT TRACKED.

    Never returns a fabricated number: an unknown model yields ``None`` so the
    caller can record "unpriced" instead of a false ``$0.00``.
    """
    price = resolve_price(provider, model)
    if price is None:
        return None
    try:
        p_in = float(prompt_tokens or 0)
        p_out = float(completion_tokens or 0)
    except (TypeError, ValueError):
        return None
    if p_in < 0 or p_out < 0:
        return None
    cost = p_in / 1_000_000.0 * float(price["input_per_1m"]) + p_out / 1_000_000.0 * float(price["output_per_1m"])
    return round(cost, 10)


def cost_for_groups(
    groups: Any,
) -> Dict[str, Any]:
    """Price a set of ``(provider, model, prompt_tokens, completion_tokens)`` groups.

    ``groups`` is an iterable of 4-tuples. Returns::

        {"cost": float, "priced_tokens": int, "unpriced_tokens": int,
         "priced_calls": int, "unpriced_calls": int, "unpriced_models": [...]}

    The cost is EXACT, not an estimate: a price is per-token and linear, so
    summing a group's tokens against one price is the same as pricing every
    row in it. Groups whose price is unknown contribute to
    ``unpriced_tokens`` and to ``cost_tracked = False`` — they are never
    silently counted as $0.00.
    """
    total = 0.0
    priced_tokens = 0
    unpriced_tokens = 0
    priced_calls = 0
    unpriced_calls = 0
    unpriced_models: list = []

    for group in groups or []:
        try:
            provider, model, prompt_tokens, completion_tokens = group
        except (TypeError, ValueError):
            continue
        try:
            p_in = int(prompt_tokens or 0)
            p_out = int(completion_tokens or 0)
        except (TypeError, ValueError):
            continue
        tokens = p_in + p_out
        cost = compute_cost(provider, model, p_in, p_out)
        if cost is None:
            unpriced_tokens += tokens
            unpriced_calls += 1
            label = f"{provider or '?'}/{model or '?'}"
            if label not in unpriced_models:
                unpriced_models.append(label)
            continue
        total += cost
        priced_tokens += tokens
        priced_calls += 1

    return {
        "cost": round(total, 10),
        "priced_tokens": priced_tokens,
        "unpriced_tokens": unpriced_tokens,
        "priced_calls": priced_calls,
        "unpriced_calls": unpriced_calls,
        "unpriced_models": unpriced_models[:20],
    }


def backfill_ledger_cost(
    batch_rows: int = 200000,
    max_rows: int = 0,
    since_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Recompute ``task_execution_log.cost`` from the pricing table.

    WHY THIS EXISTS: the ledger's ``cost`` column was 0 on every one of its
    2,127,111 rows, so eight different views (the smart router's cost
    comparison, the consciousness cost view, the dispatch history, the admin
    MCP tools, the media studio) all reported a confident $0.00 for real
    spend. Summing a column that was never written cannot be fixed by reading
    it differently — the column has to be written.

    WHAT IT WRITES:
      * a model whose price is known  -> the computed cost (0.00 for a known-free
        model, which is a real price of zero)
      * a model whose price is NOT known -> NULL

    NULL, not 0, because 0 means "this cost nothing" and an unpublished price
    does not mean that. ``SUM(cost)`` ignores NULLs, so a total over a mixed
    window is a LOWER BOUND — which is true — while a row that was never
    priced no longer masquerades as a row that cost nothing.

    Returns: {"scanned": int, "priced": int, "unpriced": int, "total_cost": float}
    """
    _ensure_loaded()
    try:
        from database import get_db_cursor
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    # 1. Which (provider, model) pairs are in the window, and what does each
    #    one price at? Few distinct pairs -> one UPDATE, not one per row.
    where = "WHERE cost = 0"
    params: list = []
    if since_days:
        where += " AND created_at >= NOW() - make_interval(days => %s)"
        params.append(int(since_days))

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""
                SELECT provider, model_used,
                       COUNT(*) AS rows_n,
                       COALESCE(SUM(COALESCE(prompt_tokens, 0)), 0) AS prompt_tokens,
                       COALESCE(SUM(COALESCE(completion_tokens, 0)), 0) AS completion_tokens
                FROM task_execution_log
                {where}
                GROUP BY provider, model_used
                """,
                params,
            )
            groups = [
                (
                    r["provider"],
                    r["model_used"],
                    int(r["prompt_tokens"] or 0),
                    int(r["completion_tokens"] or 0),
                    int(r["rows_n"] or 0),
                )
                for r in cur.fetchall()
            ]
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    priced_rows: list = []
    unpriced_pairs: list = []
    priced_rows_n = 0
    unpriced_rows_n = 0

    for provider, model, p_in, p_out, rows_n in groups:
        price = resolve_price(provider, model)
        if price is None:
            unpriced_pairs.append((provider, model))
            unpriced_rows_n += rows_n
            continue
        priced_rows.append(
            (
                provider,
                model,
                float(price["input_per_1m"]),
                float(price["output_per_1m"]),
            )
        )
        priced_rows_n += rows_n

    updated = 0
    nulled = 0
    # The window must apply to the UPDATE too, not just to the group discovery:
    # the nightly run only needs to price rows written since the last run, and
    # an unbounded UPDATE re-scans the whole 2.1M-row table every night.
    #
    # The days are interpolated as an int literal, not a placeholder: the
    # execute_values() template allows exactly ONE %s (the VALUES list), and
    # since_days is cast to int here so the interpolation is not injectable.
    days_literal = f"{int(since_days)}" if since_days else ""
    update_window = f" AND tel.created_at >= NOW() - make_interval(days => {days_literal})" if since_days else ""
    null_window = f" AND created_at >= NOW() - make_interval(days => {days_literal})" if since_days else ""

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            if priced_rows:
                from psycopg2.extras import execute_values

                execute_values(
                    cur,
                    f"""
                    UPDATE task_execution_log tel
                    SET cost = (COALESCE(tel.prompt_tokens, 0) * v.in_rate
                                + COALESCE(tel.completion_tokens, 0) * v.out_rate) / 1000000.0
                    FROM (VALUES %s) AS v(provider, model_used, in_rate, out_rate)
                    WHERE tel.cost = 0
                      {update_window}
                      AND tel.provider IS NOT DISTINCT FROM v.provider
                      AND tel.model_used IS NOT DISTINCT FROM v.model_used
                    """,
                    priced_rows,
                )
                updated = cur.rowcount or 0

            # Models with no published price -> NULL, so they stop reading as
            # "this cost nothing".
            for provider, model in unpriced_pairs:
                cur.execute(
                    f"""
                    UPDATE task_execution_log SET cost = NULL
                    WHERE cost = 0
                      {null_window}
                      AND provider IS NOT DISTINCT FROM %s
                      AND model_used IS NOT DISTINCT FROM %s
                    """,
                    (provider, model),
                )
                nulled += cur.rowcount or 0
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "updated": updated, "nulled": nulled}

    logger.info(
        "model pricing: ledger backfill — %d row(s) priced, %d row(s) marked unpriced",
        updated,
        nulled,
    )
    return {
        "scanned": priced_rows_n + unpriced_rows_n,
        "priced": updated,
        "unpriced": nulled,
        "groups_priced": len(priced_rows),
        "groups_unpriced": len(unpriced_pairs),
    }


def pricing_source() -> str:
    """Where the current cache came from: 'ds9', 'db-mirror' or 'empty'."""
    return _cache_source


def stats() -> Dict[str, Any]:
    """A small summary for the DS9 tab / a status endpoint."""
    _ensure_loaded()
    with _lock:
        providers = len(_cache)
        models = sum(len(m) for m in _cache.values())
        age = time.monotonic() - _cache_fetched_at if _cache_fetched_at else None
    return {
        "source": _cache_source,
        "providers": providers,
        "models": models,
        "age_seconds": int(age) if age is not None else None,
        "ttl_seconds": int(PRICING_TTL_SECONDS),
    }
