"""Which already-loaded Ollama models the startup warm-up may evict (#7329, #6106).

The warm-up used to ``unload_model`` EVERYTHING in ``/api/ps`` before reloading
(Project #240 #1761, written when KEEP_ALIVE was infinite). With KEEP_ALIVE=60m that throws
the busiest model (qwen2.5:7b) out of VRAM on every platform/scheduler restart, and it is
reloaded into whatever VRAM the other models left it.

Eviction is now limited to the two cases that justify it:

* ``stale_keep_alive`` -- the runner will not expire on its own (infinite / far-future
  ``expires_at``), which is the original reason for the eviction.
* ``stranded`` -- a GPU-intended model sitting on the CPU (``size_vram == 0``). Reloading
  it gives placement another chance at a card. Models whose Modelfile pins ``num_gpu 0``
  are CPU by design and are NOT stranded.

Anything else (resident on a GPU with a normal expiry, or CPU-by-design) is kept.
Pure: no I/O. ``is_cpu_pinned`` is injected so the caller supplies the Modelfile lookup.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, List, Mapping, Tuple

# KEEP_ALIVE is 60m; warm loads use 5-35m. Anything beyond 2h will not drain on its own.
MAX_HEALTHY_EXPIRY = timedelta(hours=2)

_FRAC = re.compile(r"(\.\d{6})\d+")

Decision = Tuple[str, str]  # (model, reason)


def parse_expires_at(raw) -> datetime | None:
    """Parse Ollama's ``expires_at`` (RFC3339 with up to 9 fractional digits). None if unreadable."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(_FRAC.sub(r"\1", raw.replace("Z", "+00:00")))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def plan_evictions(
    ps_models: Iterable[Mapping],
    *,
    now: datetime,
    is_cpu_pinned: Callable[[str], bool],
) -> Tuple[List[Decision], List[Decision]]:
    """Split ``/api/ps`` models into ``(evict, keep)`` lists of ``(model, reason)``."""
    evict: List[Decision] = []
    keep: List[Decision] = []
    for m in ps_models:
        name = m.get("name")
        if not name:
            continue
        expires = parse_expires_at(m.get("expires_at"))
        if expires is None or expires - now > MAX_HEALTHY_EXPIRY:
            evict.append((name, "stale_keep_alive"))
        elif (m.get("size_vram") or 0) == 0 and (m.get("size") or 0) > 0 and not is_cpu_pinned(name):
            evict.append((name, "stranded"))
        elif (m.get("size_vram") or 0) > 0:
            keep.append((name, "resident_on_gpu"))
        else:
            keep.append((name, "cpu_by_design"))
    return evict, keep
