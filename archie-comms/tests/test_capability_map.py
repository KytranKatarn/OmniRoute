"""resolve_capability never silently defaults to `code` (#6654)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import capability_map as cm


def test_default_is_conversation_never_code():
    assert cm.resolve_capability() == "conversation"
    assert cm.resolve_capability(tab="chat") == "conversation"
    assert cm.resolve_capability(is_plan_request=True) == "conversation"
    assert cm.resolve_capability(crew_target="V.I.G.I.L.") == "conversation"


def test_explicit_work_type_reaches_a_dev_capability():
    assert cm.resolve_capability(work_type="code") == "code"
    assert cm.resolve_capability(work_type="creative") == "creative"
    assert cm.resolve_capability(work_type="visual_design") == "visual_design"


def test_unknown_work_type_falls_back_to_conversation():
    assert cm.resolve_capability(work_type="something_random") == "conversation"
    assert cm.resolve_capability(work_type="") == "conversation"
    assert cm.resolve_capability(work_type=None) == "conversation"


def test_comms_may_only_send_the_allowlisted_set():
    assert cm.ALLOWED == {"conversation", "summarize", "notification", "code", "creative", "visual_design"}
    # conversation is on the sovereignty COMPANY_DATA list on the platform — it must
    # never be a cloud-eligible default here.
    assert cm.is_allowed("conversation") and not cm.is_allowed("fact_check")
