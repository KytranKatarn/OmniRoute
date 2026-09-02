"""Guard: the fleet warm-up list must not pre-warm a model that cannot GPU-fit (#6261).

Source-parsed, no imports of fleet_jobs (heavy import-time side effects) and no DB,
so this cannot silently SKIP.

🔴 THE LESSON: warming is not free. It is a VRAM RESERVATION held for the whole
KEEP_ALIVE (60m). On 2026-09-01 the K.I.N. `workforce_planning` ping was the ONLY
thing loading gemma3:12b (measured: 4 runs/90min from module_source='fleet_warmup',
zero other consumers). At 9.9GB it took HALF the hub's 20GB, leaving ~3GB per card —
too little for a 5.9GB qwen2.5:7b, the platform's highest-volume model, which demoted
to CPU at ~8.5 min/request. A keep-alive job caused the cold-load starvation it exists
to prevent.
"""
from __future__ import annotations

import pathlib
import re

_SRC = pathlib.Path(__file__).resolve().parents[1] / "services" / "fleet_jobs.py"


def _warmup_block() -> str:
    src = _SRC.read_text()
    m = re.search(r"warmup_capabilities\s*=\s*\[(.*?)\n    \]", src, re.DOTALL)
    assert m, "could not locate warmup_capabilities — did the list move?"
    return m.group(1)


def _entries(block: str) -> list[str]:
    """Capability names in ACTIVE entries only — commented-out lines don't count."""
    live = "\n".join(l for l in block.splitlines() if not l.strip().startswith("#"))
    return re.findall(r'\(\s*"([a-z_]+)"', live)


def test_workforce_planning_is_NOT_warmed():
    """gemma3:12b (9.9GB) cannot GPU-fit this fleet; warming it only denies residency
    to models that can. Re-add ONLY with a real consumer AND hardware that holds it."""
    assert "workforce_planning" not in _entries(_warmup_block()), (
        "workforce_planning warms gemma3:12b (9.9GB, no real consumer) — see #6261"
    )


def test_the_reason_survives_in_the_source():
    """An unexplained deletion gets 'restored' by the next reader. Keep the why."""
    block = _warmup_block()
    assert "#6261" in block and "gemma3" in block, (
        "the removal rationale must stay next to the list"
    )


def test_the_list_is_not_empty_and_still_warms_the_hot_models():
    """Non-vacuity: if the parse broke or the list emptied, the guard above would pass
    for entirely the wrong reason."""
    caps = _entries(_warmup_block())
    assert len(caps) >= 5, f"warm-up list looks broken/empty: {caps}"
    for essential in ("fact_check", "code_review"):
        assert essential in caps, f"{essential} must stay warm — it is high-volume"
