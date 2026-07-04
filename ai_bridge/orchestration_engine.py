"""Back-compat shim for ai_bridge.orchestration_engine.

The real module now lives at
``platform_v2.tools.department_hq.services.orchestration_engine`` — this
stub re-exports its public API so existing callers keep working during
the Project #244 transition.

Remove once every call site has been migrated to the new path. Deprecated
as of 2026-04-11.
"""

import warnings

warnings.warn(
    "ai_bridge.orchestration_engine is deprecated — import from "
    "tools.department_hq.services.orchestration_engine instead",
    DeprecationWarning,
    stacklevel=2,
)

from tools.department_hq.services.orchestration_engine import *  # noqa: F401,F403

from tools.department_hq.services.orchestration_engine import (  # noqa: F401
    OrchestrationEngine,
)
