"""Contractor health probing (DS9 PR 3) — measure what each contractor actually does.

This OBSERVES. It never dispatches, never reorders routing, and never mutates
`is_active` or `dispatchable`. It writes one `contractor_health` row per probe; ranking
reads the history afterwards. That separation is deliberate: a probe that could disable a
provider would be able to take the fleet offline by misreading one timeout.

Why this exists
---------------
`contractor_providers.tier_position` is a hand-typed integer — a wish about preference that
never changes when reality differs. Nothing recorded whether a contractor could serve at
all, how fast it answered, or which model it *actually* returned. The concrete cost was
already paid: `pollinations` sat in the table looking like a text provider when its
`/v1/chat/completions` is refused as an image-generation model, and OmniRoute's two ids
literally marked `:free` both return 502 while the unmarked ones work. None of that was
visible anywhere.

Three cadences, because probing is not free and the upstreams are rate-limited
-------------------------------------------------------------------------------------
`opencode-zen` refuses third-party gateways outright ("OpenCode's free tier can only be
used from within OpenCode"). Probing it hard is how a free tier gets withdrawn. So:

    health   every 15 min — one cheap request: does it answer at all?
    latency  hourly       — a real completion, giving a number worth ranking on
    full     daily        — enumerate models, so `observed_model` can be corrected

All three write the same table and are distinguished by `probe_kind`, so one history query
answers both "is it up" and "how slow is it".

What "class" means, and why it is assigned here
------------------------------------------------
`provider_class` (migration 486) is left NULL until something observes the provider. This
module is that something. It classifies from MEASUREMENT, never from the provider's name —
the `omniroute_*_free` rows are the reason: both marked-`:free` ids 502 while the unmarked
ones return 200, so a name-based classifier would be exactly inverted.

Status vocabulary, matching the table's CHECK
----------------------------------------------
    ok            answered
    no_key        configured but no credential available
    auth_error    the credential was refused (401/403)
    rate_limited  refused for volume (429)
    unsupported   answered, but not for this capability — e.g. an image model asked to chat
    unreachable   no response at all
    error         anything else; `detail` carries the reason

`unsupported` is separated from `error` because it is the single most useful distinction
here: it is how `pollinations` is correctly identified without being called broken.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Statuses that mean "the credential is the problem", as opposed to the service being down.
#: These are the ones an operator can act on by fixing configuration rather than waiting.
ACTIONABLE_STATUSES = frozenset({"no_key", "auth_error", "unsupported"})

#: Statuses that are worth NOT alerting on immediately: a single unreachable probe on a
#: free-tier provider is noise, and a monitor people mute monitors nothing.
TRANSIENT_STATUSES = frozenset({"unreachable", "error", "rate_limited"})

#: Default probe timeouts. Short on purpose — this runs every 15 minutes against providers
#: that may hang, and a 120s default would let one wedged provider stall the whole scan.
DEFAULT_HEALTH_TIMEOUT_S = 8
DEFAULT_LATENCY_TIMEOUT_S = 45

#: A latency sample above this is recorded but treated as unusable for ranking. Measured
#: cold and idle, `deepseek-coder-v2:16b` took ~70s for twelve tokens; under load that is
#: worse, and a number that large would otherwise dominate any average it entered.
LATENCY_CEILING_MS = 60_000


def classify_status(
    *,
    http_status: Optional[int] = None,
    has_key: bool = True,
    reached: bool = True,
    unsupported: bool = False,
) -> str:
    """Map a probe outcome onto the table's status vocabulary.

    Split out from the probe itself so the classification is testable without a network,
    and so the ordering of the checks is explicit rather than emergent.
    """
    if not has_key:
        return "no_key"
    if not reached:
        return "unreachable"
    if unsupported:
        # Checked before the status code because the gateway answers an image model on a
        # chat request with 400 plus an explanatory body — a 400 that is information, not
        # failure, and lumping it in with generic errors is what hid pollinations.
        return "unsupported"
    if http_status in (401, 403):
        return "auth_error"
    if http_status == 429:
        return "rate_limited"
    if http_status is not None and 200 <= http_status < 300:
        return "ok"
    if http_status is not None:
        return "error"
    return "unreachable"


def classify_provider_class(*, has_key: bool, status: str, is_cloud_proxy: bool) -> str:
    """Assign `provider_class` from what the probe observed.

    Deliberately narrow. It will only claim `keyless` or `image_only` from direct evidence
    and leaves everything else alone, because a wrong guess here changes dispatch
    eligibility:

      keyless     no credential is required AND the provider answered
      image_only  the provider answered, but refused to chat
      paid        a credential is required — whether it costs money is the operator's
                  decision about the key they hold, not something a probe can infer
      NULL        anything else, meaning "not yet measured"

    A provider that requires a key is NOT called `paid` on the strength of holding one:
    the six keyed providers in this table span free-tier and metered, and only real usage
    data distinguishes them.
    """
    if status == "unsupported":
        return "image_only"
    if not has_key:
        # No credential. If it still answered, it is genuinely keyless.
        return "keyless" if status == "ok" else "local"
    if status == "ok":
        # Credential required and the call succeeded. paid vs free_tier needs usage data,
        # which this probe does not gather — leave it unclaimed rather than guess.
        return "paid" if is_cloud_proxy else "free_tier"
    return "free_tier"


def record_observation(
    provider_key: str,
    *,
    probe_kind: str,
    status: str,
    latency_ms: Optional[int] = None,
    observed_model: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Write one observation. Never raises — a failed write must not abort the scan."""
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO contractor_health
                    (provider_key, probe_kind, status, latency_ms, observed_model, detail)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (provider_key, probe_kind, status, latency_ms, observed_model, detail),
            )
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not break the scan
        logger.warning(
            "contractor_health: could not record %s/%s (%s: %s)",
            provider_key,
            probe_kind,
            exc.__class__.__name__,
            exc,
        )


def latest_observation(provider_key: str, probe_kind: Optional[str] = None) -> Optional[dict]:
    """Most recent row for one provider, optionally of one cadence."""
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=False) as (_conn, cur):
            if probe_kind:
                cur.execute(
                    """
                    SELECT provider_key, probe_kind, status, latency_ms,
                           observed_model, detail, created_at
                      FROM contractor_health
                     WHERE provider_key = %s AND probe_kind = %s
                     ORDER BY created_at DESC
                     LIMIT 1
                    """,
                    (provider_key, probe_kind),
                )
            else:
                cur.execute(
                    """
                    SELECT provider_key, probe_kind, status, latency_ms,
                           observed_model, detail, created_at
                      FROM contractor_health
                     WHERE provider_key = %s
                     ORDER BY created_at DESC
                     LIMIT 1
                    """,
                    (provider_key,),
                )
            row = cur.fetchone()
        return dict(row) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "contractor_health: read failed for %s (%s: %s)",
            provider_key,
            exc.__class__.__name__,
            exc,
        )
        return None


def rank_providers() -> list[dict[str, Any]]:
    """Order contractors by OBSERVED health then latency, replacing tier_position.

    Ranked by what happened, not by what was typed:

      ok providers first, ordered by their most recent usable latency
      then unmeasured, then failing — a provider nobody has sampled is unknown, not bad
      then image_only, which is functional but not for text

    A provider with no latency sample yet sorts after every provider that has one. It is
    never given an invented latency, because a NULL is an honest "not sampled" and a made-up
    number would quietly become the ranking.

    Requires PR 1 (`contractor_providers.provider_class`, #3640). That column is part of
    what this ranking is FOR — ordering by class is how an image-only provider stops being
    offered as a text one — so rather than degrade to a NULL class when the column is
    absent, this returns empty and logs. A ranking that silently ignored `provider_class`
    would look correct while reintroducing the exact confusion this work exists to remove.
    """
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (provider_key)
                           provider_key, probe_kind, status, latency_ms, observed_model
                      FROM contractor_health
                     ORDER BY provider_key, created_at DESC
                ),
                best_latency AS (
                    SELECT DISTINCT ON (provider_key)
                           provider_key, latency_ms
                      FROM contractor_health
                     WHERE latency_ms IS NOT NULL
                       AND latency_ms <= %s
                     ORDER BY provider_key, created_at DESC
                )
                SELECT cp.provider_key, cp.display_name, cp.provider_class,
                       cp.is_active, cp.dispatchable,
                       l.status, l.latency_ms, l.observed_model, b.latency_ms AS best_ms
                  FROM contractor_providers cp
             LEFT JOIN latest        l ON l.provider_key = cp.provider_key
             LEFT JOIN best_latency b ON b.provider_key = cp.provider_key
                """,
                (LATENCY_CEILING_MS,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        # Loudly empty rather than a partial ranking. The most likely cause is PR 1 not
        # being applied yet, and returning rows with a NULL class would hide that.
        logger.warning(
            "contractor_health: rank query failed, returning empty (%s: %s). "
            "If PR 1 (#3640) is not applied this is expected.",
            exc.__class__.__name__,
            exc,
        )
        return []

    def sort_key(row: dict[str, Any]):
        status = row.get("status")
        if status == "ok":
            tier = 0
        elif status is None:
            tier = 1  # never probed — unknown, not bad
        elif row.get("provider_class") == "image_only":
            tier = 2  # works, just not for text
        else:
            tier = 3
        best = row.get("best_ms")
        return (tier, best if best is not None else float("inf"), row["provider_key"])

    ranked = sorted(rows, key=sort_key)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked


def prune(days: int = 30) -> int:
    """Drop observations older than `days`. Returns rows removed."""
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "DELETE FROM contractor_health WHERE created_at < NOW() - make_interval(days => %s)",
                (days,),
            )
            return cur.rowcount
    except Exception as exc:  # noqa: BLE001
        logger.warning("contractor_health: prune failed (%s: %s)", exc.__class__.__name__, exc)
        return 0


def scan(
    probe_kind: str = "health",
    providers: Optional[list[dict[str, Any]]] = None,
    timeout_s: Optional[int] = None,
) -> dict[str, Any]:
    """Probe each provider once and record the outcome.

    `providers` defaults to every configured contractor. `timeout_s` is per provider and
    deliberately short — see DEFAULT_HEALTH_TIMEOUT_S for why.

    A provider that raises is recorded as `error` with the exception text and the scan
    CONTINUES. One wedged contractor must never prevent the other twenty-nine from being
    measured, which is the whole reason this is a loop with per-item isolation.
    """
    if timeout_s is None:
        timeout_s = DEFAULT_LATENCY_TIMEOUT_S if probe_kind == "latency" else DEFAULT_HEALTH_TIMEOUT_S

    if providers is None:
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=False) as (_conn, cur):
                cur.execute(
                    """
                    SELECT provider_key, base_url, default_model,
                           auth_env_var, is_cloud_proxy, capabilities
                      FROM contractor_providers
                    """
                )
                providers = [dict(r) for r in cur.fetchall()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("contractor_health: could not list providers (%s)", exc)
            return {"ok": False, "error": str(exc), "probed": 0, "results": []}

    results: list[dict[str, Any]] = []
    for provider in providers:
        key = provider.get("provider_key") or ""
        started = time.time()
        try:
            outcome = _probe_one(provider, probe_kind, timeout_s)
            latency_ms = int((time.time() - started) * 1000)
            record_observation(
                key,
                probe_kind=probe_kind,
                status=outcome["status"],
                latency_ms=latency_ms if outcome["status"] == "ok" else None,
                observed_model=outcome.get("observed_model"),
                detail=outcome.get("detail"),
            )
            results.append({"provider_key": key, **outcome})
        except Exception as exc:  # noqa: BLE001 - isolate every provider
            elapsed = int((time.time() - started) * 1000)
            record_observation(
                key,
                probe_kind=probe_kind,
                status="error",
                detail=f"{exc.__class__.__name__}: {exc}"[:400],
            )
            results.append(
                {
                    "provider_key": key,
                    "status": "error",
                    "detail": f"{exc.__class__.__name__}: {exc}"[:400],
                    "latency_ms": elapsed,
                }
            )

    return {
        "ok": True,
        "probe_kind": probe_kind,
        "probed": len(results),
        "results": results,
        "summary": summarize(results),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, int]:
    """Count results per status."""
    out: dict[str, int] = {}
    for r in results:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def _probe_one(provider: dict[str, Any], probe_kind: str, timeout_s: int) -> dict[str, Any]:
    """One provider, one request. Network lives here so `scan` stays testable."""
    import os

    import requests

    key = provider.get("provider_key") or ""
    base_url = (provider.get("base_url") or "").rstrip("/")
    model = provider.get("default_model")

    env_var = provider.get("auth_env_var")
    api_key = os.environ.get(env_var) if env_var else None

    if not base_url:
        # No key is the more actionable of the two problems, so report that one.
        return {
            "status": classify_status(has_key=bool(api_key), reached=False),
            "detail": "no base_url",
        }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # BOTH cadences spend a minimal completion. A `/models` GET is not enough, and that is
    # not a theoretical concern — measured 2026-10-05 against the five OmniRoute rows:
    #
    #     GET /v1/models        -> 200 for ALL FIVE      (so health said "ok")
    #     POST /chat/completions-> 502, 403, 403, 200, 200
    #
    # All three broken ones answered `/models` happily, so a reachability-only probe ranked
    # them 1st, 2nd and 4th. `max_tokens: 1` keeps the cost at the floor while still forcing
    # the provider to actually generate — which is the only thing that distinguishes "lists
    # models" from "can serve one". A provider that answers `/models` but 403s a completion
    # is exactly the case this ranking exists to surface.
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model or "unknown",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout_s)
    except requests.exceptions.Timeout:
        return {"status": "unreachable", "detail": f"timeout after {timeout_s}s"}
    except requests.exceptions.RequestException as exc:
        return {"status": "unreachable", "detail": f"{exc.__class__.__name__}: {exc}"[:200]}

    unsupported = False
    observed = None
    detail = None
    if resp.status_code == 400:
        # An image-only model refuses a chat request with 400 AND says so. Reading the
        # body is what separates "unsupported" from "broken".
        try:
            body = resp.text or ""
        except Exception:  # noqa: BLE001
            body = ""
        if "image" in body.lower() and "generation" in body.lower():
            unsupported = True
            detail = body[:300]
    if payload is not None and resp.ok:
        try:
            observed = (resp.json() or {}).get("model")
        except Exception:  # noqa: BLE001
            observed = None

    return {
        "status": classify_status(
            http_status=resp.status_code,
            has_key=True,  # a missing key was handled above, not here
            reached=True,
            unsupported=unsupported,
        ),
        "observed_model": observed,
        "detail": detail,
    }
