"""Classify Ollama warm-load POST outcomes for the model-health job.

Single source of truth for which HTTP responses from the ``/api/...`` warm POSTs
are *hub contention* (retry next cycle — deferred, never a failure) versus a
*real* model problem (counted as failed, surfaced as an error).

KB #270033: warm-load timeouts were found to be contention on a busy hub queue,
not model-health failures, and counting them errored the ``ollama_model_health``
route every busy cycle (wasting a VRAM-drift misdiagnosis). The same is true of
the non-200 statuses that contend with a load already in flight:

* ``409`` — Ollama returns this when the exact model is *already loading* on
  another request (a concurrent dispatch beat the health check to the load).
  The model IS coming up; retry next cycle.
* ``503`` / ``429`` — the hub queue is busy or rate-limited; the warm POST did
  not even get scheduled. Transient by nature.

Anything else — notably ``404`` (model was uninstalled/renamed) and ``400``/
``500`` (deterministic load/param failures) — stays FAILED so a genuinely broken
model keeps producing a real signal instead of being masked by a deferral.
"""

#: Status codes that mean "hub was busy/loading", not "model is broken".
TRANSIENT_WARM_STATUS_CODES = frozenset({409, 429, 503})

_OUTCOME_RELOADED = "reloaded"
_OUTCOME_DEFERRED = "deferred"
_OUTCOME_FAILED = "failed"

#: Public constants for callers, so the strings never drift in the call site.
OUTCOME_RELOADED = _OUTCOME_RELOADED
OUTCOME_DEFERRED = _OUTCOME_DEFERRED
OUTCOME_FAILED = _OUTCOME_FAILED


def classify_ollama_warm_status(status_code: int) -> str:
    """Map a warm-load HTTP status code to its outcome.

    Returns one of ``OUTCOME_RELOADED``, ``OUTCOME_DEFERRED``, ``OUTCOME_FAILED``.
    ``200`` is a successful reload; transient contention codes are deferred;
    everything else is a real failure.
    """
    if status_code == 200:
        return OUTCOME_RELOADED
    if status_code in TRANSIENT_WARM_STATUS_CODES:
        return OUTCOME_DEFERRED
    return OUTCOME_FAILED