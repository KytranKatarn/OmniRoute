import os
from services.audit_pipeline import resolve_proposal_source


def test_app_core_resolves_to_real_file():
    # platform_v2/app.py exists on disk
    abs_path, display, status = resolve_proposal_source("[APP_CORE]/app.py")
    assert status == "ok"
    assert display == "platform_v2/app.py"
    assert abs_path is not None and os.path.isfile(abs_path)


def test_ai_bridge_resolves_to_real_file():
    abs_path, display, status = resolve_proposal_source("[AI_BRIDGE]/archie_bridge.py")
    assert status == "ok"
    assert display == "ai_bridge/archie_bridge.py"
    assert abs_path is not None and os.path.isfile(abs_path)


def test_dispatch_routing_is_skip():
    abs_path, display, status = resolve_proposal_source("[dispatch_routing]/agents/C.O.D.E.X./documentation")
    assert status == "skip"
    assert abs_path is None
    assert display == "[dispatch_routing]/agents/C.O.D.E.X./documentation"  # unchanged


def test_offplatform_standalone_is_missing():
    # standalone_what_the_fact has NO _PLACEHOLDER_MAP entry -> unresolved -> missing
    abs_path, display, status = resolve_proposal_source("standalone_what_the_fact/app.py")
    assert status == "missing"
    assert abs_path is None


def test_deleted_platform_file_is_missing():
    abs_path, display, status = resolve_proposal_source(
        "platform_v2/tools/media_hub/routes.py"  # media_hub consolidated to standalone
    )
    assert status == "missing"
    assert abs_path is None


def test_empty_path_is_missing():
    abs_path, display, status = resolve_proposal_source("")
    assert status == "missing"
    assert abs_path is None


def test_ok_display_matches_substituted_path_for_prompt():
    # dispatch_proposal_fix uses display_path in the agent prompt (**File:** {file_path}).
    # For a resolvable [APP_CORE] path it must be the substituted platform_v2/ path, not the label.
    _abs, display, status = resolve_proposal_source("[APP_CORE]/services/audit_pipeline.py")
    assert status == "ok"
    assert display == "platform_v2/services/audit_pipeline.py"
