"""Resolve the DHQ capability for a comms request — never defaults to `code` (#6654).

The cockpit's conversational surfaces (chat, plan, consult, and the A.R.C.H.I.E.
leg of a collaboration) all map to ``conversation``, which is on the
sovereignty COMPANY_DATA list and therefore stays LOCAL. A development
capability is reached only when the caller passes an EXPLICIT work type — never
inferred from free text, and never a silent ``code`` default (an unclassifiable
request that fell to ``code`` would both misroute and become cloud-eligible).

Comms may only ever send one of :data:`ALLOWED` to DHQ.
"""

# The only capabilities comms is permitted to request of DHQ.
ALLOWED = frozenset({"conversation", "summarize", "notification", "code", "creative", "visual_design"})

# Explicit work types that a collaboration/Claude leg may select.
_WORK_TYPES = frozenset({"code", "creative", "visual_design"})


def resolve_capability(tab=None, is_plan_request=False, crew_target=None, work_type=None):
    """Return the DHQ capability. Conversational by default; a dev capability
    only for an explicit, allowlisted ``work_type``."""
    if work_type and work_type in _WORK_TYPES:
        return work_type
    return "conversation"


def is_allowed(capability) -> bool:
    return capability in ALLOWED
