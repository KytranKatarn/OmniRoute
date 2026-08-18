"""Guards for the public-edge rate limiter (tasks #5747 / #5748).

Measured 2026-08-18 against production, anonymously, from outside the network:

  * 6 of the 11 ``/api/cross-watch/*`` routes returned HTTP 200 with real data,
    with no auth and no rate limit.  ``consumer/cross_watch.py`` carried ZERO
    auth decorators; the 5 user-scoped routes failed closed only by accident, at
    the hub, because an empty ``X-User-Email`` resolved to no user (404).
  * ``/api/proxy/articles/<id>/analyze`` was a POST with no auth and no limit
    that enqueues LLM work on the hub.
  * 19 of 29 ``/api/*`` routes in ``consumer/routes.py`` had no limit at all.
  * ``featured_story`` bucketed by ``request.remote_addr`` — behind Caddy the
    GATEWAY ip for every visitor — so all traffic shared ONE bucket and a single
    caller could 429 everybody.

These tests exec ``consumer/rate_policy.py`` BY PATH and it imports nothing
outside the stdlib.  That is deliberate: KB #290497 records a guard suite whose
helpers pulled in Flask, so every test silently reported ``s`` (skipped) while
pytest still printed "passed".  If this file ever needs Flask to run, the bug it
guards has stopped being guarded.
"""

import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOD = ROOT / "consumer" / "rate_policy.py"
ROUTES = ROOT / "consumer" / "routes.py"
CROSS_WATCH = ROOT / "consumer" / "cross_watch.py"


def _load():
    """Load the policy module by path — stdlib-only, so this can never skip."""
    spec = importlib.util.spec_from_file_location("_rate_policy", MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rp = _load()


# ── the module must stay import-free ─────────────────────────────────────────

def test_policy_module_imports_nothing_heavy():
    """The whole point of the split: no Flask/SQLAlchemy/project imports.

    If this fails, the tests below can start skipping silently and the suite
    will still report success (KB #290497).

    Parsed with ``ast`` rather than grepped as text: a substring scan matches the
    module's own docstring (which names the very libraries it avoids) and fails
    on a correct file. Only real import statements count.
    """
    import ast

    tree = ast.parse(MOD.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import — i.e. a project import
            if node.level:
                imported.add(f".{node.module or ''}")
            elif node.module:
                imported.add(node.module.split(".")[0])

    allowed = {"math", "time", "typing", "__future__", "collections"}
    offenders = sorted(m for m in imported if m not in allowed)
    assert not offenders, (
        f"rate_policy.py must stay stdlib-only; found imports {offenders}. "
        "A heavy import here makes every guard below skippable (KB #290497)."
    )


# ── bucket algorithm ─────────────────────────────────────────────────────────

def test_bucket_allows_under_limit():
    bucket = []
    for i in range(5):
        allowed, retry = rp.bucket_allow(bucket, now=1000.0 + i, limit=10, window=60)
        assert allowed is True
        assert retry == 0
    assert len(bucket) == 5


def test_bucket_denies_at_limit():
    bucket = []
    for i in range(10):
        rp.bucket_allow(bucket, now=1000.0 + i, limit=10, window=60)
    allowed, retry = rp.bucket_allow(bucket, now=1010.0, limit=10, window=60)
    assert allowed is False
    assert retry >= 1, "a denial must always tell the caller when to come back"
    assert retry <= 61


def test_bucket_window_rolls_off():
    """Old entries expire — a limiter that never forgets is a permanent ban."""
    bucket = []
    for i in range(10):
        rp.bucket_allow(bucket, now=1000.0 + i, limit=10, window=60)
    allowed, _ = rp.bucket_allow(bucket, now=1000.0, limit=10, window=60)
    assert allowed is False
    # Well past the window: everything expires, caller is allowed again.
    allowed, retry = rp.bucket_allow(bucket, now=2000.0, limit=10, window=60)
    assert allowed is True
    assert retry == 0
    assert len(bucket) == 1, "expired entries must be dropped, not accumulated"


def test_bucket_denial_does_not_append():
    """A denied request must not extend the window — otherwise hammering the
    endpoint keeps the caller locked out forever."""
    bucket = []
    for i in range(3):
        rp.bucket_allow(bucket, now=1000.0 + i, limit=3, window=60)
    before = len(bucket)
    rp.bucket_allow(bucket, now=1005.0, limit=3, window=60)
    rp.bucket_allow(bucket, now=1006.0, limit=3, window=60)
    assert len(bucket) == before


# ── worker division ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "total,workers,expected",
    [
        (60, 4, 15),   # the real deployed case: --workers 4
        (60, 1, 60),
        (60, 2, 30),
        (5, 4, 1),     # small budgets must not round to zero
        (1, 8, 1),
        (0, 4, 1),     # nonsense input must not lock everyone out
        (60, 0, 60),   # workers<1 is treated as 1, not a divide-by-zero
    ],
)
def test_effective_limit(total, workers, expected):
    assert rp.effective_limit(total, workers) == expected


def test_effective_limit_never_zero():
    for total in range(0, 20):
        for workers in range(1, 17):
            assert rp.effective_limit(total, workers) >= 1


# ── classification ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path,tier",
    [
        ("/api/proxy/articles/123/analyze", "expensive"),
        ("/api/proxy/articles/123/flag", "write"),
        ("/api/newsletter/subscribe", "write"),
        ("/api/cross-watch/entities", "proxy_read"),
        ("/api/cross-watch/search", "proxy_read"),
        ("/api/proxy/map-data", "proxy_read"),
        ("/api/v1/articles", "default"),
        ("/api/v1/blindspot", "default"),
        ("/api/stats", "default"),
    ],
)
def test_classify(path, tier):
    assert rp.classify(path) == tier


def test_analyze_status_is_a_cheap_read_not_expensive():
    """The UI polls /analyze/status while an analysis runs.  If it inherited the
    'expensive' tier from the '/analyze' substring it would 429 its own progress
    polling after 5 checks — the guard must not over-fire."""
    assert rp.classify("/api/proxy/articles/123/analyze/status") == "proxy_read"


def test_unknown_path_falls_back_to_bounded_not_unlimited():
    """A route nobody classified must still be limited.  'Unknown' is exactly how
    19 routes ended up unbounded in the first place."""
    assert rp.classify("/api/something/nobody/thought/about") == rp.DEFAULT_TIER
    assert rp.classify("") == rp.DEFAULT_TIER
    limit, window = rp.limits_for("no-such-tier")
    assert limit > 0 and window > 0


def test_expensive_is_stricter_than_read():
    """Ordering invariant: work that costs the hub GPU time must never be more
    permissive than a plain read."""
    exp_limit, exp_window = rp.limits_for("expensive")
    read_limit, read_window = rp.limits_for("default")
    assert exp_limit / exp_window < read_limit / read_window


# ── dict growth ──────────────────────────────────────────────────────────────

def test_prune_drops_expired_callers():
    buckets = {f"ip{i}": [1000.0] for i in range(50)}
    buckets["live"] = [9000.0]
    removed = rp.prune(buckets, now=9000.0, window=60, max_keys=1000)
    assert removed == 50
    assert list(buckets) == ["live"], "an active caller must survive pruning"


def test_prune_bounds_the_dict_under_key_pressure():
    """The limiter's own dict was an unbounded memory-growth vector."""
    buckets = {f"ip{i}": [1000.0 + i] for i in range(500)}
    rp.prune(buckets, now=1000.0, window=10_000, max_keys=100)
    assert len(buckets) <= 100


def test_prune_evicts_the_quietest_first():
    """Under key pressure an ACTIVE abuser must be the last to have their bucket
    forgiven — evicting them would reset their budget."""
    buckets = {"quiet": [1000.0], "busy": [1990.0]}
    rp.prune(buckets, now=2000.0, window=10_000, max_keys=1)
    assert "busy" in buckets
    assert "quiet" not in buckets


def test_prune_handles_empty():
    assert rp.prune({}, now=1.0, window=60, max_keys=10) == 0


# ── wiring: assert the source actually uses this ─────────────────────────────

def test_featured_story_no_longer_buckets_by_gateway_ip():
    """consumer/routes.py:3551 passed request.remote_addr, which behind Caddy is
    the gateway IP for EVERY visitor — one shared global bucket, so a single
    caller could 429 the whole site."""
    src = ROUTES.read_text()
    assert "_api_rate_ok(request.remote_addr)" not in src, (
        "featured_story must use the client-IP-aware helper, not remote_addr"
    )


def test_previously_unlimited_routes_are_gated():
    """The specific routes measured as unlimited on 2026-08-18."""
    src = ROUTES.read_text()
    # Each block runs from its route decorator to the NEXT route decorator.
    # Do not truncate at "\n@" — a route may carry additional decorators, and
    # cutting there hides the gate that sits below them.
    blocks = re.split(r"\n@bp\.(?:route|get|post)\(", src)
    gated = {}
    for blk in blocks[1:]:
        head = blk.split(")", 1)[0]
        m = re.match(r'["\']([^"\']+)["\']', head)
        if not m:
            continue
        gated[m.group(1)] = "_api_rate_check" in blk or "_news_rate_ok" in blk

    must_be_gated = [
        "/api/v1/blindspot",
        "/api/v1/divergence",
        "/api/v1/ridings",
        "/api/v1/map-data",
        "/api/proxy/articles/<int:article_id>/analyze",
        "/api/proxy/articles/<int:article_id>/flag",
        "/api/newsletter/subscribe",
        "/api/proxy/map-data",
        "/api/proxy/agent-activity",
    ]
    ungated = [r for r in must_be_gated if not gated.get(r)]
    assert not ungated, f"these routes are still unbounded: {ungated}"


def test_internal_set_tier_keeps_its_own_auth():
    """It looked 'unlimited' in the audit but is gated by X-Internal-Key and
    fails closed. Adding a rate limit there would throttle the billing webhook."""
    src = ROUTES.read_text()
    blk = src.split('route("/api/internal/set-tier"', 1)[1].split("\n@bp.", 1)[0]
    assert "X-Internal-Key" in blk
    assert "INTERNAL_API_KEY" in blk


def test_user_scoped_cross_watch_routes_require_a_session():
    """These 5 previously reached the hub with an empty X-User-Email and failed
    closed only by accident, at the hub, leaking {"email": ""} on the way."""
    src = CROSS_WATCH.read_text()
    blocks = re.split(r"\n@cross_watch_bp\.route\(", src)
    guarded = {}
    for blk in blocks[1:]:
        head = blk.split(")", 1)[0]
        m = re.match(r'["\']([^"\']+)["\']', head)
        if not m:
            continue
        guarded[m.group(1)] = "_user_api" in blk or "_require_session" in blk

    user_scoped = [
        "/api/cross-watch/alerts",
        "/api/cross-watch/alerts/<int:alert_id>/read",
        "/api/cross-watch/follow",
        "/api/cross-watch/follow/<int:entity_id>",
        "/api/cross-watch/following",
    ]
    missing = [r for r in user_scoped if not guarded.get(r)]
    assert not missing, f"user-scoped cross-watch routes without a session gate: {missing}"


def test_public_cross_watch_routes_are_rate_limited():
    """Owner decision: these stay public (accountability data) but must be bounded."""
    src = CROSS_WATCH.read_text()
    blocks = re.split(r"\n@cross_watch_bp\.route\(", src)
    limited = {}
    for blk in blocks[1:]:
        head = blk.split(")", 1)[0]
        m = re.match(r'["\']([^"\']+)["\']', head)
        if not m:
            continue
        limited[m.group(1)] = "_public_api" in blk or "_rate_limited" in blk

    public = [
        "/api/cross-watch/entities",
        "/api/cross-watch/procurement",
        "/api/cross-watch/parliament-votes",
        "/api/cross-watch/legal-rulings",
        "/api/cross-watch/civic-events",
        "/api/cross-watch/search",
    ]
    unlimited = [r for r in public if not limited.get(r)]
    assert not unlimited, f"public cross-watch routes still unbounded: {unlimited}"


def test_cross_watch_does_not_echo_the_email_back():
    """The hub's 404 returned {"email": "", ...}, quietly documenting the auth
    model. The edge must reject before that response is ever produced."""
    src = CROSS_WATCH.read_text()
    assert "_require_session" in src, "no session guard present at the WTF edge"


def test_edu_docs_do_not_hardcode_a_stale_limit():
    """edu.html promised '100 requests / hour per IP' while the code enforced
    60/60s. Docs must render the live constant so they cannot drift again."""
    edu = ROOT / "consumer" / "templates" / "edu.html"
    if not edu.exists():
        pytest.fail("consumer/templates/edu.html is missing — update this guard")
    text = edu.read_text()
    assert "100 requests / hour" not in text, (
        "edu.html still advertises a limit the code does not enforce"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
