"""Back-compat shim for ai_bridge.smart_router.

The real module now lives at
``platform_v2.tools.department_hq.services.smart_router`` — this stub
re-exports its public API so existing callers keep working during the
Project #244 transition.

Remove once every call site has been migrated to the new path. Deprecated
as of 2026-04-11.
"""
import warnings

warnings.warn(
    "ai_bridge.smart_router is deprecated — import from "
    "tools.department_hq.services.smart_router instead",
    DeprecationWarning,
    stacklevel=2,
)

from tools.department_hq.services.smart_router import *  # noqa: F401,F403

from tools.department_hq.services.smart_router import (  # noqa: F401
    TIER_ORDER,
    CAPABILITY_ROUTING,
    get_router,
    classify_task,
)
