"""Regression: a retired cloud model must never reach the wire.

2026-09-27: eighteen `translate` delegations were routed to `minimax-m2.5`,
which Ollama Cloud had retired on 2026-07-31. Every attempt got a hard
``410 Gone``, retried three times, then sat `blocked` for 33h.

The instructive part is that #5706 had ALREADY fixed this on 2026-08-17 — it
changed the default model and removed the name from the dispatcher's
FREE_CLOUD_MODELS list. It changed nothing about the two things that actually
selected the model:

  * the ``contractor_providers`` row still carried it as ``default_model``
  * ``/api/tags`` still ADVERTISES ``minimax-m2.5:cloud``

Worse, the model #5706 installed as the replacement — ``qwen3-coder-next`` — is
ALSO retired (2026-07-15, verified live on 2026-09-27). So the entire
Ollama Cloud proxy tier was dead, and "fix the contractor row" alone would have
merely moved the 18 jobs onto the next dead model.

The fix therefore lives at the choke point every cloud call passes through
(``ai_bridge/archie_bridge.py``), not in a list of names somebody has to
remember to update.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import sys

import pytest


def _find_bridge() -> pathlib.Path:
    """Locate ai_bridge/archie_bridge.py across both on-disk layouts.

    ARCHIE_BRIDGE_PATH overrides the search. That exists so a mutation check can
    point this suite at a deliberately-broken COPY of the file — patching the
    test source to achieve that is how three wiring tests were silently deleted
    from this file once already (a regex with a lookahead to the last test ate
    everything in between, and the suite then reported green while testing
    nothing). Never edit this file to run a mutation; set the env var.
    """
    override = os.environ.get("ARCHIE_BRIDGE_PATH")
    if override:
        p = pathlib.Path(override)
        assert p.is_file(), f"ARCHIE_BRIDGE_PATH does not exist: {p}"
        return p

    root = pathlib.Path(__file__).resolve().parents[1]
    candidates = [
        root.parent / "ai_bridge" / "archie_bridge.py",
        pathlib.Path("/mnt/archie_brain/ai_bridge/archie_bridge.py"),
    ]
    for base in (root, *root.parents):
        candidates.append(base / "ai_bridge" / "archie_bridge.py")
    for c in candidates:
        if c.is_file():
            return c
    raise AssertionError(
        "could not locate ai_bridge/archie_bridge.py; tried: " + ", ".join(str(c) for c in dict.fromkeys(candidates))
    )


BRIDGE = _find_bridge()


def _src() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _load_guards():
    """Compile RETIRED_CLOUD_MODELS + is_retired_cloud_model without importing
    the bridge module (it pulls in requests, psycopg2, and DB config)."""
    tree = ast.parse(_src())
    wanted = {"RETIRED_CLOUD_MODELS", "is_retired_cloud_model"}
    ns: dict = {}
    for node in tree.body:
        name = None
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.FunctionDef):
            name = node.name
        if name in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(BRIDGE), "exec"), ns)
    assert wanted <= set(ns), f"missing from archie_bridge.py: {wanted - set(ns)}"
    return ns["is_retired_cloud_model"], ns["RETIRED_CLOUD_MODELS"]


@pytest.fixture(scope="module")
def guards():
    return _load_guards()


# ── the guard recognises the retired model, suffix or not ───────────────────
@pytest.mark.parametrize(
    "name",
    [
        "minimax-m2.5",
        "minimax-m2.5:cloud",
        "MiniMax-M2.5",
        "MINIMAX-M2.5:CLOUD",
        " minimax-m2.5 ",
        "qwen3-coder-next",
        "qwen3-coder-next:cloud",
        "QWEN3-CODER-NEXT:CLOUD",
    ],
)
def test_retired_model_is_recognised(guards, name):
    is_retired, _ = guards
    assert is_retired(name) is True, f"{name!r} should be recognised as retired"


@pytest.mark.parametrize(
    "name",
    ["gpt-4o-mini", "llama-3.3-70b-versatile", "", None, "minimax-m3", "command-a-03-2025"],
)
def test_live_models_are_not_retired(guards, name):
    is_retired, _ = guards
    assert is_retired(name) is False, f"{name!r} must NOT be treated as retired"


def test_retirement_entry_explains_itself(guards):
    _, table = guards
    assert "minimax-m2.5" in table, "the 2026-09-27 incident model must be listed"
    why = table["minimax-m2.5"]
    assert "410" in why, "an operator reading this needs to see it is a hard 410"
    assert "2026-07-31" in why, "and when it died"


def test_qwen3_replacement_is_also_listed(guards):
    """qwen3-coder-next was the #5706 REPLACEMENT for minimax. Verified live on
    2026-09-27: it answers 410 Gone too ("retired at 2026-07-15"). Without this
    entry the guard would spend a 300s round trip rediscovering that on every
    dispatch, and the cloud-proxy tier would look half-working."""
    is_retired, table = guards
    assert "qwen3-coder-next" in table, "qwen3-coder-next 410s in production and must be listed as retired"
    assert is_retired("qwen3-coder-next:cloud") is True


# ── WIRING: the guard must actually run, and run BEFORE the network call ────
def _call_body() -> str:
    m = re.search(r"def call_ollama_cloud\(.*?(?=\ndef )", _src(), re.S)
    assert m, "could not locate call_ollama_cloud in archie_bridge.py"
    return m.group(0)


def test_call_ollama_cloud_checks_the_guard():
    """The classifier tests above all pass even if the call site is deleted —
    they exercise the helper, not its use. This is the assertion that actually
    pins the behaviour, and it is the one a careless refactor loses."""
    body = _call_body()
    assert "is_retired_cloud_model(model)" in body, (
        "call_ollama_cloud no longer consults is_retired_cloud_model — the "
        "helper exists but is unwired, so retired models reach the network again"
    )


def test_guard_runs_before_the_request():
    """After the call it saves nothing; the wasted 300s round trip is the cost."""
    body = _call_body()
    guard = body.index("is_retired_cloud_model(model)")
    wire = body.index("requests.post(")
    assert guard < wire, (
        f"the retired-model check is at offset {guard} but requests.post is at "
        f"{wire} — the guard must run BEFORE the network call"
    )


def test_guard_returns_a_normal_shaped_failure():
    """Callers must not need changing, and the refusal must be machine-readable
    so the delegation layer can treat it as non-retryable."""
    body = _call_body()
    seg = body[body.index("is_retired_cloud_model(model)") : body.index("requests.post(")]
    assert '"success": False' in seg, "the refusal must report success=False"
    assert '"non_retryable": True' in seg, "the refusal must be flagged non_retryable so it is not retried"
    assert '"retired": True' in seg


def test_live_410_is_flagged_non_retryable():
    """A model retired upstream AFTER this table was written must still degrade
    correctly rather than stalling the queue for 33h."""
    src = _src()
    assert "response.status_code in (404, 410)" in src, (
        "a live 404/410 must be flagged retired/non_retryable so a model this "
        "table has never heard of cannot stall the queue"
    )


def test_the_default_model_cannot_reach_the_wire_unnoticed():
    """As of 2026-09-27 the default IS a retired model: qwen3-coder-next was the
    #5706 replacement for minimax and it 410s too, so the whole cloud-proxy tier
    is dead. That is a real platform defect, not something to assert away.

    The actionable invariant is the weaker one: whatever the default is, it is
    either live or caught by the guard before any HTTP call. The default is left
    in place deliberately — changing a public signature while the tier is being
    repopulated would ripple through callers — and the guard turns a silent
    410-after-300s into an instant, explicit refusal.
    """
    m = re.search(r'def call_ollama_cloud\(\s*prompt,\s*model="([^"]+)"', _src())
    assert m, "could not read the default model"
    default = m.group(1)
    is_retired, _ = _load_guards()
    if is_retired(default):
        assert "is_retired_cloud_model(model)" in _call_body(), (
            f"default model '{default}' is retired AND unguarded — every caller "
            "that omits model= would still spend a doomed round trip"
        )


# ── the data half: no ACTIVE cloud proxy may point at a dead model ──────────
def test_no_active_cloud_proxy_points_at_a_retired_model(guards):
    """An active contractor on a dead model is exactly how the 33h stall
    happened. Both were deactivated on 2026-09-27; this fails if someone
    re-enables one without fixing the model first.

    Queried in-process rather than via `docker exec` — the suite already runs
    inside the container, where there is no docker CLI to shell out to.
    """
    is_retired, _ = guards
    sys.path.insert(0, "/app")
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT provider_key, default_model, is_active " "FROM contractor_providers WHERE is_cloud_proxy")
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        # conftest points the suite at an ISOLATED test database that carries no
        # contractor_providers seed, so this query is vacuous there. Skip
        # explicitly rather than report a green that proved nothing — an empty
        # table must never read as "the invariant holds".
        pytest.skip(
            "contractor_providers has no cloud-proxy rows in the isolated test "
            "DB (no seed data); verified live instead — see handover"
        )
    for row in rows:
        if row.get("is_active"):
            assert not is_retired(row.get("default_model") or ""), (
                f"contractor '{row.get('provider_key')}' is ACTIVE but its model "
                f"'{row.get('default_model')}' is retired — it will 410 every time"
            )


def test_module_parses():
    ast.parse(_src())
