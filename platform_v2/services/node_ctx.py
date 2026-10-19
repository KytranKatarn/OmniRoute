"""One ``num_ctx`` per (node, model) so a node never reloads a runner to change context size (#7349).

Ollama treats a different ``num_ctx`` as a different runner: the loaded model is unloaded and loaded
again. On Defiant (RTX 3070, 8 GB, one request at a time) two callers disagreed about the context size
of the SAME model: F.O.R.G.E. reviews and their keep-warm ask for 8192 (``forge:review_num_ctx``) while
every other dispatch (What The Fact fact_check/bias, ...) sends none and gets Ollama's default 4096. The
runner therefore flips 4096 <-> 8192, and each flip is a reload that queues every request behind it.

``remote_nodes.extra_capabilities.num_ctx_default`` is a map ``{model: num_ctx}``. When a dispatch to
that node for that model carries no ``num_ctx`` of its own, this module supplies the node's value, so
all callers land on the one runner. A caller that sets ``num_ctx`` explicitly (reviews) always wins, and a
node or model with no entry is untouched (no behaviour change until the map is set).

The map value for the review model must equal ``forge:review_num_ctx`` or reviews would again force a
reload; the F.O.R.G.E. keep-warm reads this same map for that reason.
"""

from __future__ import annotations

import json
from typing import Mapping, Optional

_MIN_CTX, _MAX_CTX = 512, 32768


def _as_dict(extra_capabilities) -> dict:
    if isinstance(extra_capabilities, Mapping):
        return dict(extra_capabilities)
    if isinstance(extra_capabilities, (str, bytes)):
        try:
            data = json.loads(extra_capabilities)
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
    return {}


def node_default_ctx(extra_capabilities, model: str) -> Optional[int]:
    """The node's configured context size for *model*, or None. Never raises."""
    mapping = _as_dict(extra_capabilities).get("num_ctx_default")
    if not isinstance(mapping, Mapping) or not model:
        return None
    for key in (model, model.replace(":latest", "")):
        if key in mapping:
            try:
                n = int(mapping[key])
            except (TypeError, ValueError):
                return None
            return n if _MIN_CTX <= n <= _MAX_CTX else None
    return None


_MIN_LEG_CAP, _MAX_LEG_CAP = 60, 600


def node_leg_timeout_cap(extra_capabilities, capability: str) -> Optional[int]:
    """The node's per-capability fleet-leg timeout cap in seconds, or None (#7349). Never raises.

    ``remote_nodes.extra_capabilities.fleet_leg_timeout`` is ``{capability: seconds}``, e.g.
    ``{"code_review": 120}`` on Defiant. It exists because the dispatcher floors every fleet leg at 240s
    for cold-load headroom (KB #266396), which is wrong for a node whose model is resident and whose
    review legs are bimodal: of 2,016 successful Defiant review legs in 7 days only ~27 took over 120s
    (p99 of ALL its generate calls is 60s), while 222 sat until the 600s timeout and 73% of those were
    followed within ~90s by a retry that succeeded. A stuck first attempt then costs 2 minutes, not 10.

    Per node AND per capability on purpose: the hub's review legs have a 106s median and What The Fact
    fact_check legs legitimately run longer, so a global cap would hurt them. No entry = no change.
    """
    mapping = _as_dict(extra_capabilities).get("fleet_leg_timeout")
    if not isinstance(mapping, Mapping) or not capability or capability not in mapping:
        return None
    try:
        n = int(mapping[capability])
    except (TypeError, ValueError):
        return None
    return n if _MIN_LEG_CAP <= n <= _MAX_LEG_CAP else None


def narrowed_leg_timeout(timeout: int, extra_capabilities, capability: str) -> int:
    """*timeout* narrowed to the node's cap for *capability*. NEVER widens: a cap above the budget the
    caller already granted is ignored, so this can only make a leg fail faster, not run longer."""
    cap = node_leg_timeout_cap(extra_capabilities, capability)
    return cap if cap and cap < timeout else timeout


def apply_node_default_ctx(options: Optional[dict], extra_capabilities, model: str) -> Optional[dict]:
    """Return *options* with the node's default ``num_ctx`` added when the caller set none."""
    if options and options.get("num_ctx"):
        return options  # the caller's explicit value always wins
    ctx = node_default_ctx(extra_capabilities, model)
    if ctx is None:
        return options
    merged = dict(options or {})
    merged["num_ctx"] = ctx
    return merged
