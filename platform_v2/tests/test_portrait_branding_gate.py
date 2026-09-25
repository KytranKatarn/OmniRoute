from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import base64
import inspect
from urllib.parse import parse_qs, urlparse

import ai_bridge.external_providers as external_providers
import tools.media_studio.services.portrait_service as portrait_service
from tools.media_studio.services.comfyui_manager import (
    IDENTITY_MODE_FACEID_DETAIL,
    IDENTITY_MODE_INSTANTID_DETAIL,
    build_identity_workflow,
    normalize_identity_mode,
)
from tools.media_studio.services.generation_service import (
    FREE_PROVIDERS,
    IMAGE_PROVIDER_PRIORITY,
    SUPPORTED_IMAGE_PROVIDERS,
    _dashboard_media_item,
    _dashboard_media_url,
    get_dashboard_stats,
    get_image_providers,
)
from tools.media_studio.services.portrait_service import (
    DEFAULT_PORTRAIT_MODEL,
    _apply_corporate_brand,
    _compose_identity_prompt,
    _portrait_model_params,
    _portrait_negative_prompt,
    _stable_face_seed,
    generate_canonical,
    generate_fanout,
    generate_variant,
)


def test_corporate_brand_is_added_once():
    prompt = _apply_corporate_brand("professional portrait")
    assert "Kytran Empowerment RAM mark" in prompt
    assert "background-only" in prompt
    assert _apply_corporate_brand(prompt) == prompt


def test_portrait_negative_prompt_allows_subtle_background_brand():
    negative = _portrait_negative_prompt()
    assert "large logo" in negative
    assert "logo over face" in negative
    assert "watermark" not in negative


def test_generation_paths_apply_corporate_brand():
    for function in (generate_canonical, generate_variant, generate_fanout):
        assert "_compose_identity_prompt" in inspect.getsource(function)
    assert "Kytran Empowerment RAM mark" in _compose_identity_prompt("portrait")


def test_portrait_auto_approval_job_is_removed():
    source = (Path(__file__).resolve().parents[1] / "services" / "fleet_jobs.py").read_text()
    assert "portrait_auto_approve" not in source


def test_portrait_model_defaults_to_realvisxl_and_honors_provider_override():
    assert _portrait_model_params() == {"model": DEFAULT_PORTRAIT_MODEL}
    assert _portrait_model_params("local:custom.safetensors") == {"model": "custom.safetensors"}
    assert _portrait_model_params("provider:replicate", "black-forest-labs/flux-dev") == {
        "model": "black-forest-labs/flux-dev",
        "provider": "replicate",
    }


def test_identity_prompt_locks_gender_age_and_appearance():
    prompt = _compose_identity_prompt(
        "professional headshot",
        display_name="Avery Example",
        gender="woman",
        ethnicity="South Asian",
        age_range="30s",
        appearance_notes="dark brown shoulder-length hair, brown eyes, oval face",
    )
    assert "gender presentation: woman" in prompt
    assert "age: 30s" in prompt
    assert "ethnicity and skin tone: South Asian" in prompt
    assert "dark brown shoulder-length hair" in prompt
    assert "identity lock:" in prompt
    assert "no identity drift" in prompt
    assert "changed gender" in _portrait_negative_prompt()


def test_identity_modes_fail_closed_without_reference_or_local_provider():
    assert normalize_identity_mode("auto", has_reference=False) == "prompt"
    assert normalize_identity_mode("auto", has_reference=True, model="RealVisXL_V4.0.safetensors") == IDENTITY_MODE_FACEID_DETAIL
    try:
        normalize_identity_mode("faceid", has_reference=False)
    except ValueError as exc:
        assert "approved canonical reference" in str(exc)
    else:
        raise AssertionError("identity mode without reference must fail")
    try:
        normalize_identity_mode("faceid", has_reference=True, provider="pollinations")
    except ValueError as exc:
        assert "local ComfyUI provider" in str(exc)
    else:
        raise AssertionError("cloud identity mode must fail")


def test_identity_workflow_uses_installed_faceid_and_instantid_nodes():
    faceid = build_identity_workflow(
        "portrait",
        reference_image="reference.png",
        identity_mode=IDENTITY_MODE_FACEID_DETAIL,
    )["prompt"]
    instantid = build_identity_workflow(
        "portrait",
        reference_image="reference.png",
        identity_mode=IDENTITY_MODE_INSTANTID_DETAIL,
    )["prompt"]
    assert faceid["5"]["class_type"] == "IPAdapterUnifiedLoaderFaceID"
    assert faceid["14"]["class_type"] == "FaceDetailer"
    assert instantid["5"]["class_type"] == "InstantIDModelLoader"
    assert instantid["9"]["class_type"] == "ApplyInstantID"
    assert instantid["14"]["class_type"] == "FaceDetailer"


def test_portrait_identity_context_reports_missing_fields_without_inventing_values():
    context = portrait_service._portrait_identity_context(
        {"pronouns": "they/them", "bio": "A careful reviewer", "current_grade": None},
        None,
    )
    assert context["pronouns"] == "they/them"
    assert context["grade_status"] == "Unrated"
    assert "appearance_notes" in context["missing_fields"]
    assert "tts_voice_profile" in context["missing_fields"]


def test_stable_face_seed_is_repeatable_without_changing_saved_seed():
    assert _stable_face_seed(42, None) == _stable_face_seed(42, None)
    assert _stable_face_seed(42, 12345) == 12345


def test_image_provider_priority_prefers_keyless_then_omniroute():
    assert "omniroute" in FREE_PROVIDERS
    assert "replicate" not in SUPPORTED_IMAGE_PROVIDERS
    assert IMAGE_PROVIDER_PRIORITY["pollinations"] < IMAGE_PROVIDER_PRIORITY["omniroute"]
    assert IMAGE_PROVIDER_PRIORITY["omniroute"] < IMAGE_PROVIDER_PRIORITY["cloudflare_ai"]


def test_image_provider_contract_exposes_identity_capability_metadata():
    source = inspect.getsource(get_image_providers)
    assert "identity_modes" in source
    assert "identity_node" in source


def test_omniroute_image_adapter_decodes_base64_response(tmp_path, monkeypatch):
    encoded = base64.b64encode(b"x" * 2048).decode("ascii")

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"data": [{"b64_json": encoded}]}

    monkeypatch.setenv("OMNIROUTE_API_KEY", "test-gateway-key")
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://omniroute:20128/v1")
    monkeypatch.setenv("FLASK_APP_ROOT", str(tmp_path))
    monkeypatch.setattr(external_providers.requests, "post", lambda *args, **kwargs: Response())

    result = external_providers._omniroute_image_adapter(
        {"prompt": "synthetic test portrait", "params": {"model": "aihorde/Realistic Vision"}}
    )

    assert result["success"] is True
    assert result["metadata"]["provider"] == "omniroute"
    assert result["metadata"]["model"] == "aihorde/Realistic Vision"
    assert (tmp_path / result["file_path"].lstrip("/")).is_file()


def test_pollinations_request_is_private_and_forwards_negative_prompt(tmp_path, monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        content = b"x" * 2048
        text = ""

    def get(url, timeout):
        captured["url"] = url
        return Response()

    monkeypatch.setenv("FLASK_APP_ROOT", str(tmp_path))
    monkeypatch.setattr(external_providers.requests, "get", get)

    result = external_providers._pollinations_image_adapter(
        {
            "prompt": "synthetic portrait",
            "negative_prompt": "different person, changed gender",
            "params": {"model": "flux-realism", "width": 512, "height": 512, "seed": 42},
        }
    )

    assert result["success"] is True
    assert "private=true" in captured["url"]
    query = parse_qs(urlparse(captured["url"]).query)
    assert query["negative_prompt"] == ["different person, changed gender"]


def test_canonical_generation_propagates_selected_model():
    class Cursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return {"identity_prompt": "professional portrait", "face_seed": 123}

    @contextmanager
    def cursor(*_args, **_kwargs):
        yield object(), Cursor()

    with (
        patch.object(portrait_service, "get_db_cursor", cursor),
        patch.object(portrait_service, "_ensure_portrait_record"),
        patch(
            "tools.media_studio.services.generation_service.submit_generation",
            return_value={"queue_id": 7, "status": "pending"},
        ) as submit,
    ):
        result = portrait_service.generate_canonical(
            42,
            model="provider:replicate",
            model_override="black-forest-labs/flux-dev",
        )

    assert result["queue_id"] == 7
    params = submit.call_args.kwargs["params"]
    assert params["model"] == "black-forest-labs/flux-dev"
    assert params["provider"] == "replicate"


def test_canonical_route_forwards_selected_model():
    source = (Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "routes.py").read_text()
    start = source.index("def api_generate_canonical")
    end = source.index('@media_studio_bp.route("/api/portraits/<int:agent_id>/generate-variant"', start)
    route_source = source[start:end]
    assert 'model=data.get("model")' in route_source
    assert 'model_override=data.get("model_override")' in route_source
    assert 'identity_mode=data.get("identity_mode", "auto")' in route_source
    assert 'identity_weight=data.get("identity_weight")' in route_source


def test_generation_service_routes_identity_modes_through_reference_upload():
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "media_studio"
        / "services"
        / "generation_service.py"
    ).read_text()
    assert "_upload_reference_image" in source
    assert "build_identity_workflow" in source
    assert 'identity_mode != "prompt"' in source


def test_refined_prompt_generation_uses_canonical_model_picker():
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "media_studio"
        / "templates"
        / "tools"
        / "media_studio"
        / "media_studio.html"
    ).read_text()
    start = source.index("window.generateWithRefinedPrompt")
    end = source.index("window.saveRefinedPrompt", start)
    function_source = source[start:end]
    assert "var canonicalModel =" in function_source
    assert "model: canonicalModel" in function_source
    assert "model_override: canonicalProviderModel" in function_source


def test_identity_prompt_update_syncs_roster_fields():
    class Cursor:
        def execute(self, *_args, **_kwargs):
            return None

    class Connection:
        pass

    @contextmanager
    def cursor(*_args, **_kwargs):
        yield Connection(), Cursor()

    with (
        patch.object(portrait_service, "get_db_cursor", cursor),
        patch.object(portrait_service, "_ensure_portrait_record"),
        patch.object(portrait_service.agent_service, "update_agent", return_value=True) as update_agent,
    ):
        result = portrait_service.update_identity_prompt(42, "  professional portrait  ")

    assert result["success"] is True
    update_agent.assert_called_once_with(
        42,
        avatar_generation_prompt="professional portrait",
        portrait_prompt="professional portrait",
    )


def test_portrait_grid_orders_by_latest_media_and_exposes_metadata():
    source = inspect.getsource(portrait_service.get_all_agent_portraits)
    assert "latest_media_at" in source
    assert "latest_model" in source
    assert "ORDER BY COALESCE(latest.latest_media_at" in source


def test_identity_audit_is_read_only_and_reports_completeness():
    source = inspect.getsource(portrait_service.get_identity_audit)
    assert "missing_fields" in source
    assert "voice_profiles" in source
    route_source = (Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "routes.py").read_text()
    assert '"/api/portraits/identity-audit"' in route_source
    assert "get_identity_audit" in route_source


def test_profile_portrait_route_queues_for_review_without_approval():
    source = (Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "agent_detail_routes.py").read_text()
    start = source.index("def api_agent_generate_portrait")
    end = source.index("@bp.route", start + 1)
    route_source = source[start:end]
    assert "approve_canonical" not in route_source
    assert "model_override" in route_source
    assert "status IN ('pending', 'dispatched')" in route_source
    assert 'not result.get("queue_id")' in route_source
    assert '"review_required": True' in route_source
    assert '"auto_approved": False' in route_source
    assert "202" in route_source


def test_dashboard_media_paths_are_browser_ready():
    assert _dashboard_media_url("media/agents/1/image.png") == "/static/media/agents/1/image.png"
    assert _dashboard_media_url("static/media/image.png") == "/static/media/image.png"
    item = _dashboard_media_item({"file_path": "/static/media/image.png", "thumbnail_path": "agents/1/thumb.png"})
    assert item["url"] == "/static/media/image.png"
    assert item["thumbnail_url"] == "/static/agents/1/thumb.png"


def test_dashboard_contract_exposes_live_queue_and_review_counts():
    source = inspect.getsource(get_dashboard_stats)
    assert "queue_failed" in source
    assert "pending_approval_count" in source
    assert "social_queue_count" in source
    assert "media_generation_queue" in source


def test_dashboard_approval_sends_agent_and_media_ids():
    source = (
        Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "static" / "js" / "ms-dashboard.js"
    ).read_text()
    assert "JSON.stringify({ media_id: mediaId })" in source
    assert "item.agent_id, item.media_id" in source


def test_armada_and_kin_expose_media_queue_tracking():
    fleet_source = (
        Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "fleet_dashboard_routes.py"
    ).read_text()
    kin_source = (Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "work_routes.py").read_text()
    assert '"Media Studio"' in fleet_source
    assert "platform_queued" in fleet_source
    assert "media_jobs" in fleet_source
    assert "media_queue_by_status" in kin_source
