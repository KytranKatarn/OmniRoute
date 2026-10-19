"""Per-leg timeout for F.O.R.G.E. review dispatches (#7349).

A review leg is either fast or stuck: measured on Defiant over 7 days (2,500 ``code_review`` legs),
82.5% finish under 2 minutes (100% ok) and 15.4% sit until the 600s timeout (42% ok); almost nothing
lands in between. Two stuck legs spend the whole 1,200s review budget, so a review that was fine
ended ``elapsed_time_limit`` -> NEEDS REVIEW with 1-2 of its files read.

A leg now gets ``DEFAULT_LEG_TIMEOUT`` (240s) instead of the capability-wide 600s, so a stuck leg costs
4 minutes and the structured->freeform fallback that already exists acts as the retry.

* 240 is also the dispatcher's fleet floor (``max(timeout, 240)``, KB #266396 cold-load headroom), so
  this never narrows below that headroom - the floor makes lower values meaningless.
* Patient-model escalations (``model_override`` / ``prefer_model``, e.g. gemma3:12b cold-loading on the
  hub) keep 600: a 12B legitimately needs longer, and #5810 raised the cap for exactly that.
* Tunable with no deploy: ``platform_settings forge:review_leg_timeout_seconds`` (240-600). Setting it
  to 600 restores the old behaviour.
"""

from __future__ import annotations

DEFAULT_LEG_TIMEOUT = 240
PATIENT_LEG_TIMEOUT = 600
_MIN, _MAX = 240, 600


def leg_timeout(setting_value, patient: bool = False) -> int:
    """Seconds one review dispatch may take. Never raises; bad config -> the default."""
    if patient:
        return PATIENT_LEG_TIMEOUT
    try:
        n = int(str(setting_value).strip())
    except (TypeError, ValueError):
        return DEFAULT_LEG_TIMEOUT
    return min(max(n, _MIN), _MAX)
