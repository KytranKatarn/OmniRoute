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

import json
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

#: Ollama Cloud's NATIVE generate endpoint. Not an OpenAI-compatible /chat/completions — the
#: two cloud-proxy contractors carry the sentinel base_url "ollama_cloud_proxy" precisely
#: because they are reached through here instead of their own HTTP endpoint.
OLLAMA_CLOUD_GENERATE_URL = "https://ollama.com/api/generate"


def _redact(text: str, secret: Optional[str]) -> str:
    """Blank out the credential if the upstream echoed it back into an error body.

    Error bodies get stored in `contractor_health.detail` and rendered into the Contractors
    tab's tooltip. An upstream that reflects the Authorization header — some gateways do,
    and a malformed-token error frequently quotes it — would otherwise persist a live key
    into a history table and then into the DOM.

    Only the exact secret is replaced, so ordinary prose containing the word "Bearer" or a
    substring of the key is left readable.
    """
    if not text or not secret:
        return text or ""
    return text.replace(secret, "***")


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
    if unsupported:
        # Checked before the status code because the gateway answers an image model on a
        # chat request with 400 plus an explanatory body — a 400 that is information, not
        # failure, and lumping it in with generic errors is what hid pollinations.
        return "unsupported"
    if reached and http_status is not None and 200 <= http_status < 300:
        # A 2xx settles the question whether or not a credential was sent. This check has to
        # come BEFORE the `not has_key` branch, because a provider that served this request
        # without a key has demonstrated it needs none — and while `not has_key` came first,
        # that success was unreachable, so `keyless` could never be detected at all.
        return "ok"
    if not has_key:
        # Nothing was sent, so a rejection is not evidence of a bad credential. `no_key` means
        # "no credential available", `auth_error` means "the credential we had was refused".
        # Collapsing them is what reported deepseek, openrouter and replicate as auth_error
        # when the honest answer is that no key is configured for them at all.
        return "no_key"
    if not reached:
        return "unreachable"
    if http_status in (401, 403):
        return "auth_error"
    if http_status == 429:
        return "rate_limited"
    if http_status is not None:
        return "error"
    return "unreachable"


def classify_provider_class(
    *,
    has_key: bool,
    status: str,
    free_allowance: Optional[int] = None,
) -> Optional[str]:
    """Assign `provider_class` from what the probe observed, or None for "still unmeasured".

    Deliberately narrow, because a wrong guess here changes dispatch eligibility:

      keyless     no credential is required AND the provider answered
      image_only  the provider answered, but refused to chat
      free_tier   the provider answered AND its config DECLARES a free allowance
      paid        never assigned here — see below
      None        everything else, including every failure

    `paid` is never inferred. This function used to end in

        return "paid" if is_cloud_proxy else "free_tier"

    which asserted `paid` from `is_cloud_proxy` — a flag that says how a provider is REACHED
    ("delegate to Ollama Cloud"), not what it costs. It contradicted this very docstring, and
    it was wrong on the live roster: minimax_cloud and qwen3_cloud both declare
    `rate_limits.free.weekly_limit = 7000`, they have never been dispatched, and the weekly
    rotation in `pick_free_text_provider` is built around exactly those allowances. Filing
    them as `paid` would have put the platform's own free-tier providers in the money bucket.
    The parameter is gone rather than ignored, so the same mistake cannot be re-made by
    passing the flag again.

    Cost now comes from `free_allowance` — the provider's own DECLARED allowance, which is
    config intent rather than a guess. Absent that, a keyed provider that answered stays
    unmeasured: a probe genuinely cannot tell a free allowance from a metered one.

    A failure is never evidence of cost. This function used to end in `return "free_tier"`,
    which filed a provider returning 401/403/500/timeout under the bucket that IS
    auto-eligible. Against the real roster that stamped `free_tier` on 13 of the 18
    unmeasured contractors, converting "we could not measure this" into "safe to dispatch".
    """
    if status == "unsupported":
        return "image_only"
    if status == "ok":
        if not has_key:
            # It answered with no credential, so it needs none. That is direct evidence.
            return "keyless"
        if free_allowance:
            # The config declares a free allowance, so this is not a metered provider.
            return "free_tier"
    # No allowance declared, or the probe failed: claim nothing.
    return None


def declared_free_allowance(rate_limits: Any) -> Optional[int]:
    """The provider's own declared free weekly allowance, if it has one.

    Read from config rather than inferred, because this is a statement of intent by whoever
    configured the contractor — not something a probe can discover. Returns None when
    nothing is declared, which the classifier treats as "cost unknown".

    Tolerant of the three shapes this arrives in: a dict, a JSON string (the column is
    JSONB but a hand-edited row can hold text), or None.
    """
    if not rate_limits:
        return None
    data = rate_limits
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    free = data.get("free")
    if not isinstance(free, dict):
        return None
    limit = free.get("weekly_limit")
    if isinstance(limit, bool) or not isinstance(limit, int):
        return None
    return limit if limit > 0 else None


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
                    -- Restricted to the sampling cadences, NOT health.
                    --
                    -- The comment above this CTE promised exactly this filter and the query did not
                    -- have it, so every row carrying a latency qualified -- including the 1-token
                    -- health probes, which run every 15 minutes under an 8s timeout and therefore land
                    -- six times more often than the hourly latency cadence. A health number and a
                    -- ranking sample are different measurements of different things.
                    --
                    -- It bites hardest on a provider that flaps: one good health probe between two
                    -- failures becomes its 'best' latency, which is the opposite of what a ranking is for.
                    --
                    -- Barely changes anything today, because latency_ms is only recorded on an `ok` row
                    -- and only 2 of 30 contractors serve at all. It is the difference between a ranking
                    -- and a coin toss as soon as more of them do.
                       AND probe_kind IN ('latency', 'full')
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
    is_cloud_proxy = bool(provider.get("is_cloud_proxy"))

    env_var = provider.get("auth_env_var")
    api_key = os.environ.get(env_var) if env_var else None

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if is_cloud_proxy:
        # A cloud proxy's base_url is NOT a URL. minimax_cloud and qwen3_cloud both carry the
        # literal string "ollama_cloud_proxy", which fleet_service.py already documents as a
        # "sentinel value that is not a URL at all ... external by definition".
        #
        # Appending /chat/completions to it produced "ollama_cloud_proxy/chat/completions",
        # which is a DNS failure, so BOTH cloud contractors reported `unreachable` — a
        # manufactured diagnosis. They were not unreachable; the probe had asked the wrong
        # question of them. `call_external` has always branched on is_cloud_proxy first and
        # delegated to call_ollama_cloud, which posts to ollama.com's NATIVE generate API.
        #
        # Deliberately NOT routed through call_ollama_cloud: that function calls
        # _log_cloud_usage, so probing through it would charge every health check against the
        # weekly free allowance these rows declare (7000/wk). At one probe per 15 min that is
        # ~672/week — roughly a tenth of the free tier, spent on watching it.
        if not api_key:
            return {"status": "no_key", "detail": "cloud proxy needs OLLAMA_API_KEY"}
        url = OLLAMA_CLOUD_GENERATE_URL
        payload = {
            "model": model or "unknown",
            "prompt": "Reply with exactly: OK",
            "stream": False,
            "options": {"num_predict": 1},
        }
    else:
        if not base_url:
            # No key is the more actionable of the two problems, so report that one.
            return {
                "status": classify_status(has_key=bool(api_key), reached=False),
                "detail": "no base_url",
            }
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model or "unknown",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        }

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

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout_s)
    except requests.exceptions.Timeout:
        return {"status": "unreachable", "detail": f"timeout after {timeout_s}s"}
    except requests.exceptions.RequestException as exc:
        return {"status": "unreachable", "detail": f"{exc.__class__.__name__}: {exc}"[:200]}

    unsupported = False
    observed = None
    detail = None

    # Read the body whenever there is one to read. It used to be read ONLY for the 400
    # image-generation case, so every 401/403/429/5xx recorded detail=NULL and the column
    # the migration was written for — "the upstream's own words ... without anyone having to
    # guess at it again" — was empty for 20 of the 30 contractors on the first real run.
    # gemini's 403 says "Requests to this API ... has been disabled"; that is the entire
    # diagnosis, and it was being thrown away.
    body = ""
    try:
        body = resp.text or ""
    except Exception:  # noqa: BLE001 - a body we cannot read is not a body
        body = ""

    if resp.status_code == 400 and not is_cloud_proxy:
        # An image-only model refuses a chat request with 400 AND says so. Reading the
        # body is what separates "unsupported" from "broken". Skipped for cloud proxies:
        # ollama.com has no image-generation model behind this key, so a 400 there means
        # something else entirely and reading it as "image only" would be a guess.
        if "image" in body.lower() and "generation" in body.lower():
            unsupported = True

    if not resp.ok:
        # Truncated, and with the credential redacted: this body is rendered into the
        # Contractors tab's tooltip, and an upstream that echoes the Authorization header
        # would otherwise persist a live key into a history table.
        detail = _redact(body, api_key)[:300] or None

    if payload is not None and resp.ok:
        try:
            observed = (resp.json() or {}).get("model")
        except Exception:  # noqa: BLE001
            observed = None

    return {
        "status": classify_status(
            http_status=resp.status_code,
            # The REAL value, not a hardcoded True. With `True` here, a provider with no
            # configured credential came back `auth_error` — as if a key had been rejected
            # when none was ever sent — and `no_key` was dead code that no probe could
            # reach. Three contractors (deepseek, openrouter, replicate) have no
            # auth_env_var at all, so all three were mislabelled that way.
            has_key=bool(api_key),
            reached=True,
            unsupported=unsupported,
        ),
        "observed_model": observed,
        "detail": detail,
    }
