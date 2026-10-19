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
