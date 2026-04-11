"""Back-compat shim for ai_bridge.bridge_dispatcher.

The real module now lives at
``platform_v2.tools.department_hq.services.bridge_dispatcher`` — this
stub re-exports its public API so existing callers keep working during
the Project #244 transition.

Remove once every call site has been migrated to the new path. Deprecated
as of 2026-04-11.
"""
import warnings

warnings.warn(
    "ai_bridge.bridge_dispatcher is deprecated — import from "
    "tools.department_hq.services.bridge_dispatcher instead",
    DeprecationWarning,
    stacklevel=2,
)

# Star re-export covers the public API surface.
from tools.department_hq.services.bridge_dispatcher import *  # noqa: F401,F403

# Explicit re-exports for the most-used names — protects against __all__
# limitations and makes the forwarding explicit for IDE navigation.
from tools.department_hq.services.bridge_dispatcher import (  # noqa: F401
    BridgeDispatcher,
    DispatchResult,
    get_dispatcher,
    dispatch,
    dispatch_json,
)
