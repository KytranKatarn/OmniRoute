"""Regression: a permanently-refused delegation must not burn its retry budget.

2026-09-27: eighteen `translate` delegations each spent three full retry rounds
against ``minimax-m2.5``, which Ollama Cloud had retired on 2026-07-31 and
answered with a hard ``410 Gone``. Identical doomed call, three times over, then
parked as 'blocked' for 33h.

Two properties are pinned here, and the second matters more than the first:

  1. A PERMANENT refusal (410 Gone / retirement / dead credential) is cancelled
     on the FIRST failure instead of consuming the retry budget.
  2. A TRANSIENT failure — above all GPU contention — is NOT reclassified.
     Cancelling those would silently destroy recoverable work, which is a far
     worse failure than a slow retry.
"""

from __future__ import annotations

import pathlib
import re
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SVC = ROOT / "services" / "delegation_service.py"


def _classifier():
    """Compile ONLY ``_is_permanent_dispatch_failure`` from the real source.

    Deliberately does NOT import delegation_service. The function is pure (it
    only uses ``re``), so it can be lifted out with ``ast`` and exercised
    without touching ``sys.modules`` at all.

    That matters more than it looks. An earlier version of this file stubbed
    ``sys.modules['database']`` and restored it afterwards — but restoring
    *removed* the entry, which made a later ``from database import
    get_db_cursor`` import the real module EARLY, before conftest had pointed
    the suite at its isolated test DB. ``database.py`` caches connection
    config at import time, so the next test got a cursor of ``None`` and died
    with a TypeError in a completely unrelated file
    (test_model_dispatch_reaper). Never mutate global import state in a test.
    """
    import ast
    import re as _re

    src = SVC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_is_permanent_dispatch_failure":
            ns = {"re": _re, "Any": object}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SVC), "exec"), ns)
            return ns["_is_permanent_dispatch_failure"]
    raise AssertionError("_is_permanent_dispatch_failure not found in delegation_service.py")


@pytest.fixture(scope="module")
def svc():
    return _classifier()


# ── permanent: must short-circuit the retry budget ──────────────────────────
PERMANENT = [
    # the exact 2026-09-27 refusal
    'Dispatcher refused: Ollama Cloud API error: 410 - {"error":"minimax-m2.5 was '
    'retired at 2026-07-31 00:00:00 -0700 PDT"}',
    "HTTP 410 Gone",
    "410 Gone: model removed",
    "minimax-m2.5 was retired at 2026-07-31",
    "qwen3 has been retired by the provider",
    "model is no longer available on this endpoint",
    "401 Unauthorized: invalid api key",
    "403 Forbidden: permission denied for this model",
    "404 model 'foo:7b' not found",
]


@pytest.mark.parametrize("err", PERMANENT)
def test_permanent_refusals_are_classified_permanent(svc, err):
    assert svc(err) is True, f"should be permanent, would otherwise burn 3 doomed retries: {err[:70]}"


# ── transient: MUST stay retryable ──────────────────────────────────────────
# These are the ones that would be destroyed by an over-broad classifier. The
# fleet sees all of them routinely under GPU contention.
TRANSIENT = [
    "timeout after 240s — Starbase did not return for model=qwen2.5:7b",
    "timeout after 600s",
    "request timed out",
    "the remote end closed the connection without response",
    'HTTP 500 from Starbase: {"error":"llama runner process has terminated"}',
    "server busy, please try again. maximum concurrency reached",
    "ConnectionError: Max retries exceeded with url: /api/generate",
    "429 too many requests",
    "503 service unavailable",
    "HTTP 502 Bad Gateway",
    "llama runner process has terminated unexpectedly",
    "",
    None,
]


@pytest.mark.parametrize("err", TRANSIENT)
def test_transient_failures_stay_retryable(svc, err):
    assert svc(err) is False, f"MUST keep its 3 attempts — cancelling this destroys recoverable work: {err!r}"


def test_bare_404_without_model_is_not_permanent(svc):
    """A 404 on some other endpoint is not a dead model."""
    assert svc("HTTP 404 Not Found: /tasks/9") is False


def test_gpu_contention_phrases_never_classify_permanent(svc):
    """Belt and braces: the exact phrasings seen in the 24h failure dump."""
    blob = (
        "timeout after 300s - Starbase - A.R.C.H.I.E. did not return for model=qwen2.5:7b\n"
        "server busy, please try again. maximum concurrency reached\n"
        "llama runner process has terminated\n"
        "Connection aborted. RemoteDisconnected"
    )
    assert svc(blob) is False


# ── wiring: the classifier must actually gate the budget ────────────────────
def test_mark_task_failed_consults_the_classifier(svc):
    src = SVC.read_text(encoding="utf-8")
    m = re.search(r"def mark_task_failed\(.*?(?=\ndef |\n# ---)", src, re.S)
    assert m, "could not locate mark_task_failed"
    body = m.group(0)
    assert "_is_permanent_dispatch_failure(error)" in body, (
        "mark_task_failed no longer consults the classifier — the short-circuit "
        "has been disconnected and permanent refusals will retry again"
    )
    assert (
        "permanent or (cap > 0 and attempts >= cap)" in body
    ), "give_up must OR in `permanent`, or the budget still gates it"


def test_permanent_cancellation_is_labelled(svc):
    """A cancelled row must say it was non-retryable, not just 'gave up'."""
    src = SVC.read_text(encoding="utf-8")
    assert "'permanent', TRUE" in src
    assert "NON-RETRYABLE" in src
    # And it must be visible in the panel, which reads blockers.
    assert re.search(
        r"status = 'cancelled'.{0,200}blockers = %s", src, re.S
    ), "the permanent branch must also stamp blockers, or the cancel is silent"


def test_permanent_failures_alert(svc):
    """Silence is what let 18 rows rot. The refusal must be announced."""
    src = SVC.read_text(encoding="utf-8")
    # Anchor on the alert specifically — there is more than one `if permanent:`
    # in mark_task_failed (the SQL branch comes first), so match the one that
    # follows the work_notes insert.
    m = re.search(r"INSERT INTO work_notes.*?\)(\s*if permanent:.*?emit_delegation_event\()", src, re.S)
    assert m, "a permanent refusal must raise an alert, not fail silently"
    tail = src[m.start(1) : m.start(1) + 2000]
    # Alerting must never break the write path.
    assert "except Exception" in tail, "the alert is unguarded and can break the write"


def test_module_parses():
    import ast

    ast.parse(SVC.read_text(encoding="utf-8"))
