from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import base64
import inspect
from urllib.parse import parse_qs, urlparse

import ai_bridge.external_providers as external_providers
import tools.media_studio.routes as media_studio_routes
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
    apply_ke_branding,
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
    compose_variant_prompt,
    generate_canonical,
    generate_fanout,
    generate_variant,
)


def test_corporate_brand_is_added_once():
    prompt = _apply_corporate_brand("professional portrait")
    assert "professional human corporate portrait" in prompt
    assert _apply_corporate_brand(prompt) == prompt


def test_prompt_never_asks_the_model_for_the_brand_mark():
    """Regression guard: asking for a mark makes SD invent gibberish.

    The prior brand string requested "subtle embossed Kytran Empowerment RAM
    mark" and the model painted a fake logo on the blazer lapel
    (media_library #498) while the negative prompt banned "fake logo". The real
    mark is composited post-generation by apply_ke_branding instead.
    """
    banned = ("RAM mark", "embossed", "architectural branding", "branding accents")
    prompts = [
        _apply_corporate_brand("professional portrait"),
        _compose_identity_prompt("portrait"),
        compose_variant_prompt(preset="ke_corporate"),
        compose_variant_prompt(preset="ai", ke_background=True),
    ]
    for prompt in prompts:
        lowered = prompt.lower()
        for phrase in banned:
            assert phrase.lower() not in lowered, f"{phrase!r} must not be prompt text: {prompt}"


def test_ke_background_prompt_is_photographic():
    """SD responds to concrete visual nouns, not brand abstractions."""
    prompt = compose_variant_prompt(preset="ke_corporate").lower()
    for token in ("office", "bokeh", "depth of field", "bokeh"):
        assert token in prompt
    assert "no readable generated text" not in prompt


def test_ke_corporate_preset_and_toggle_share_one_string():
    """The preset and the stacking toggle must not drift apart."""
    assert compose_variant_prompt(preset="ke_corporate") == compose_variant_prompt(
        preset="ke_corporate", ke_background=True
    )


def test_portrait_negative_prompt_allows_subtle_background_brand():
    negative = _portrait_negative_prompt()
    assert "large logo" in negative
    assert "logo over face" in negative
    assert "watermark" not in negative


def test_generation_paths_apply_corporate_brand():
    for function in (generate_canonical, generate_variant, generate_fanout):
        assert "_compose_identity_prompt" in inspect.getsource(function)
    assert "corporate portrait" in _compose_identity_prompt("portrait")


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
    assert (
        normalize_identity_mode("auto", has_reference=True, model="RealVisXL_V4.0.safetensors")
        == IDENTITY_MODE_FACEID_DETAIL
    )
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


def test_structured_variant_prompt_preserves_identity_and_includes_brief():
    prompt = compose_variant_prompt(
        preset="ai",
        scene="modern office",
        action="waving at the camera",
        framing="full_body",
        expression="confident",
    )
    assert "preserve identity" in prompt.lower()
    assert "modern office" in prompt
    assert "action: waving at the camera" in prompt
    assert "full-body framing" in prompt
    assert "expression: confident" in prompt

    corporate = compose_variant_prompt(preset="ke_corporate", scene="a café")
    assert "office" in corporate
    assert "a café" in corporate


def test_variant_route_forwards_structured_controls():
    source = (Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "routes.py").read_text()
    start = source.index("def api_generate_variant")
    end = source.index("@media_studio_bp.route", start + 1)
    route_source = source[start:end]
    for field in ("preset", "scene", "action", "framing", "expression", "variant_name"):
        assert f'{field}=data.get("{field}")' in route_source


def test_generate_variant_passes_structured_brief_to_generation():
    class Cursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return {
                "identity_prompt": "professional portrait",
                "ip_adapter_ref_path": "/static/media/agents/42/reference.png",
                "canonical_image_path": "/static/media/agents/42/canonical.png",
                "approved": True,
                "display_name": "Test Agent",
                "name": "test-agent",
                "gender": "",
                "ethnicity": "",
                "age_range": "",
                "appearance_notes": "",
            }

    @contextmanager
    def cursor(*_args, **_kwargs):
        yield object(), Cursor()

    with (
        patch.object(portrait_service, "get_db_cursor", cursor),
        patch.object(portrait_service, "_portrait_model_params", return_value={"model": "test-model"}),
        patch.object(
            portrait_service,
            "_identity_generation_params",
            return_value={"identity_mode": "faceid_detail", "identity_weight": 0.85},
        ),
        patch(
            "tools.media_studio.services.generation_service.submit_generation",
            return_value={"queue_id": 19, "status": "pending"},
        ) as submit,
    ):
        result = generate_variant(
            42,
            preset="ai",
            scene="modern office",
            action="waving at the camera",
            framing="full_body",
            expression="confident",
            variant_name="Office wave",
        )

    assert result["queue_id"] == 19
    params = submit.call_args.kwargs["params"]
    assert params["variant_preset"] == "ai"
    assert params["variant_name"] == "Office wave"
    assert params["scene"] == "modern office"
    assert params["action"] == "waving at the camera"
    assert params["framing"] == "full_body"
    assert params["expression"] == "confident"
    assert "action: waving at the camera" in submit.call_args.kwargs["prompt"]


def test_portrait_grid_exposes_department_and_variant_metadata():
    source = inspect.getsource(portrait_service.get_all_agent_portraits)
    assert "a.title, a.department" in source
    assert "latest_variant_name" in source
    assert "metadata->>'variant_name'" in source


def test_portrait_delete_route_protects_agent_canonical_assets():
    source = (Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "routes.py").read_text()
    start = source.index("def api_delete_media")
    end = source.index("@media_studio_bp.route", start + 1)
    route_source = source[start:end]
    assert 'owner_type") == "agent"' in route_source
    assert "canonical_image_path" in route_source
    assert "Only agent portrait variants" in route_source
    assert 'getattr(current_user, "is_admin"' in route_source
    assert 'delete_media(media_id, "agent"' in route_source


def test_delete_route_soft_deletes_agent_variant_for_admin():
    item = {
        "owner_type": "agent",
        "owner_id": 42,
        "media_type": "image",
        "file_path": "/static/media/agents/42/variant.png",
        "metadata": {"asset_type": "portrait"},
    }
    with (
        patch.object(media_studio_routes, "current_user", SimpleNamespace(id=7, is_admin=True, is_super_admin=False)),
        patch.object(media_studio_routes, "jsonify", side_effect=lambda payload: payload),
        patch("tools.media_studio.services.gallery_service.get_media_detail", return_value=item),
        patch("tools.media_studio.services.gallery_service.delete_media", return_value=True) as delete,
        patch(
            "tools.media_studio.services.portrait_service.get_agent_portrait",
            return_value={"canonical_image_path": "/static/canonical.png"},
        ),
    ):
        response = media_studio_routes.api_delete_media.__wrapped__(9)

    assert response == {"status": "deleted", "owner_type": "agent"}
    delete.assert_called_once_with(9, "agent", 42)


def test_delete_route_rejects_non_admin_agent_variant():
    item = {
        "owner_type": "agent",
        "owner_id": 42,
        "media_type": "image",
        "file_path": "/static/media/agents/42/variant.png",
        "metadata": {"asset_type": "portrait"},
    }
    with (
        patch.object(media_studio_routes, "current_user", SimpleNamespace(id=7, is_admin=False, is_super_admin=False)),
        patch.object(media_studio_routes, "jsonify", side_effect=lambda payload: payload),
        patch("tools.media_studio.services.gallery_service.get_media_detail", return_value=item),
        patch("tools.media_studio.services.gallery_service.delete_media") as delete,
    ):
        response, status = media_studio_routes.api_delete_media.__wrapped__(9)

    assert status == 403
    assert "administrator" in response["error"]
    delete.assert_not_called()


def test_delete_route_rejects_canonical_portrait():
    item = {
        "owner_type": "agent",
        "owner_id": 42,
        "media_type": "image",
        "file_path": "/static/canonical.png",
        "metadata": {"asset_type": "portrait"},
    }
    with (
        patch.object(media_studio_routes, "current_user", SimpleNamespace(id=7, is_admin=True, is_super_admin=False)),
        patch.object(media_studio_routes, "jsonify", side_effect=lambda payload: payload),
        patch("tools.media_studio.services.gallery_service.get_media_detail", return_value=item),
        patch(
            "tools.media_studio.services.portrait_service.get_agent_portrait",
            return_value={"canonical_image_path": "/static/canonical.png"},
        ),
        patch("tools.media_studio.services.gallery_service.delete_media") as delete,
    ):
        response, status = media_studio_routes.api_delete_media.__wrapped__(9)

    assert status == 409
    assert "Canonical portraits" in response["error"]
    delete.assert_not_called()


def test_portrait_template_has_structured_brief_and_filters():
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "media_studio"
        / "templates"
        / "tools"
        / "media_studio"
        / "media_studio.html"
    ).read_text()
    for marker in (
        "ms-variant-preset",
        "ms-variant-scene",
        "ms-variant-action",
        "ms-variant-framing",
        "ms-variant-expression",
        "ms-variant-name",
        "ms-portrait-search",
        "ms-portrait-status-filter",
        "ms-portrait-sort",
        "filterPortraits",
    ):
        assert marker in source


def test_generation_completion_preserves_variant_brief_metadata():
    source = (
        Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "services" / "generation_service.py"
    ).read_text()
    for field in ("variant_name", "variant_preset", "scene", "action", "framing", "expression"):
        assert field in source


def test_generation_service_routes_identity_modes_through_reference_upload():
    source = (
        Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "services" / "generation_service.py"
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


def test_ke_corporate_background_stacks_on_any_style_preset():
    prompt = compose_variant_prompt(preset="ai", ke_background=True)
    assert "restrained futuristic cyan and violet interface accents" in prompt
    assert "skyline bokeh" in prompt
    assert "shallow depth of field" in prompt

    stacked = compose_variant_prompt(preset="professional", scene="a café", ke_background=True)
    assert "professional corporate portrait" in stacked
    assert "a café" in stacked
    assert "skyline bokeh" in stacked

    plain = compose_variant_prompt(preset="ke_corporate")
    assert compose_variant_prompt(preset="ke_corporate", ke_background=True) == plain


def test_generate_variant_sets_ke_branding_metadata():
    class Cursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return {
                "identity_prompt": "professional portrait",
                "ip_adapter_ref_path": "/static/media/agents/42/reference.png",
                "canonical_image_path": "/static/media/agents/42/canonical.png",
                "approved": True,
                "display_name": "Test Agent",
                "name": "test-agent",
                "gender": "",
                "ethnicity": "",
                "age_range": "",
                "appearance_notes": "",
            }

    @contextmanager
    def cursor(*_args, **_kwargs):
        yield object(), Cursor()

    def run(**kwargs):
        with (
            patch.object(portrait_service, "get_db_cursor", cursor),
            patch.object(portrait_service, "_portrait_model_params", return_value={"model": "test-model"}),
            patch.object(
                portrait_service,
                "_identity_generation_params",
                return_value={"identity_mode": "faceid_detail", "identity_weight": 0.85},
            ),
            patch(
                "tools.media_studio.services.generation_service.submit_generation",
                return_value={"queue_id": 19, "status": "pending"},
            ) as submit,
        ):
            generate_variant(42, **kwargs)
        return submit.call_args.kwargs["params"]

    params = run(preset="ai", ke_background=True)
    assert params["variant_branding"] == "ke_corporate"

    params = run(preset="ke_corporate")
    assert params["variant_branding"] == "ke_corporate"

    params = run(preset="professional")
    assert "variant_branding" not in params


def test_variant_route_forwards_ke_background():
    source = (Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "routes.py").read_text()
    start = source.index("def api_generate_variant")
    end = source.index("@media_studio_bp.route", start + 1)
    route_source = source[start:end]
    assert 'ke_background=bool(data.get("ke_background"))' in route_source


def test_generation_completion_preserves_ke_branding_metadata():
    source = (
        Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "services" / "generation_service.py"
    ).read_text()
    assert "variant_branding" in source


def test_portrait_detail_exposes_agent_type_and_identity_fields():
    source = inspect.getsource(portrait_service.get_agent_portrait)
    for field in ("a.worker_type, a.is_department_ai", "a.gender", "a.ethnicity", "a.age_range", "a.appearance_notes"):
        assert field in source


def test_identity_suggest_and_save_routes_exist_with_admin_gate_on_save():
    route_source = (Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "routes.py").read_text()
    suggest_start = route_source.index("identity-suggest")
    assert "@media_studio_bp.route" in route_source[suggest_start - 200 : suggest_start]
    assert "suggest_identity_fields" in route_source

    save_start = route_source.index("identity-fields")
    assert "api_save_identity_fields" in route_source
    assert "save_identity_fields" in route_source


def test_identity_fields_save_uses_agent_service_single_writer():
    with patch.object(portrait_service.agent_service, "update_identity", return_value=True) as update:
        result = portrait_service.save_identity_fields(
            42,
            appearance_notes="  dark brown shoulder-length hair  ",
            gender="woman",
            ethnicity="South Asian",
            age_range="30s",
        )
    assert result["success"] is True
    update.assert_called_once_with(
        42,
        appearance_notes="dark brown shoulder-length hair",
        gender="woman",
        ethnicity="South Asian",
        age_range="30s",
    )


def test_suggest_identity_fields_requires_approved_reference():
    class Cursor:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return {"name": "Test Agent", "approved": False, "ip_adapter_ref_path": None, "canonical_image_path": None}

    @contextmanager
    def cursor(*_args, **_kwargs):
        yield object(), Cursor()

    with patch.object(portrait_service, "get_db_cursor", cursor):
        result = portrait_service.suggest_identity_fields(42)

    assert result["success"] is False
    assert "approved reference image is required" in result["error"]


def test_parse_identity_fields_draft_extracts_json_and_falls_back():
    parsed = portrait_service._parse_identity_fields_draft(
        'Here you go: {"appearance_notes": "dark hair, brown eyes", "gender": "woman", "ethnicity": "South Asian", "age_range": "30s"}'
    )
    assert parsed == {
        "appearance_notes": "dark hair, brown eyes",
        "gender": "woman",
        "ethnicity": "South Asian",
        "age_range": "30s",
    }

    spaced = portrait_service._parse_identity_fields_draft('{"appearance": "short black hair", "age range": "40s"}')
    assert spaced["appearance_notes"] == "short black hair"
    assert spaced["age_range"] == "40s"
    assert spaced["gender"] == ""

    fallback = portrait_service._parse_identity_fields_draft("just a plain description")
    assert fallback["appearance_notes"] == "just a plain description"
    assert fallback["gender"] == ""
    assert fallback["ethnicity"] == ""
    assert fallback["age_range"] == ""

    assert portrait_service._parse_identity_fields_draft("") == {
        "appearance_notes": "",
        "gender": "",
        "ethnicity": "",
        "age_range": "",
    }


def test_portrait_template_has_ke_toggle_identity_fields_editor_and_default_preset():
    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "media_studio"
        / "templates"
        / "tools"
        / "media_studio"
        / "media_studio.html"
    ).read_text()
    for marker in (
        "ms-variant-ke",
        "ms-id-appearance",
        "ms-id-gender",
        "ms-id-ethnicity",
        "ms-id-age",
        "suggestIdentityFields",
        "saveIdentityFields",
        "_fillIdentityFields",
    ):
        assert marker in source
    assert "isAI ? 'ai' : 'professional'" in source
    assert "identity-suggest" in source
    assert "identity-fields" in source


# --- KE mark compositing -------------------------------------------------
# The mark cannot be rendered by the model (see the prompt regression guard
# above), so it is stamped on deterministically after generation.


def _gradient_png(path, size=(512, 512)):
    from PIL import Image

    img = Image.new("RGB", size, (120, 140, 170))
    for x in range(size[0]):
        v = int(120 + (x / size[0]) * 80)
        for y in range(size[1]):
            img.putpixel((x, y), (v, v + 20, 200 - v // 2))
    img.save(path, "PNG")
    return path


def test_apply_ke_branding_stamps_the_real_mark_in_the_corner(tmp_path):
    from PIL import Image, ImageChops

    logo = tmp_path / "logo.png"
    Image.new("RGBA", (64, 76), (200, 30, 30, 255)).save(logo)
    target = _gradient_png(tmp_path / "portrait.png")

    before = Image.open(target).convert("RGB")
    assert apply_ke_branding(str(target), logo_path=str(logo)) is True
    after = Image.open(target).convert("RGB")

    # The mark must land in the bottom-right corner...
    w, h = after.size
    corner = after.crop((int(w * 0.6), int(h * 0.6), w, h))
    corner_before = before.crop((int(w * 0.6), int(h * 0.6), w, h))
    assert ImageChops.difference(corner, corner_before).getbbox() is not None
    # ...and the top of the frame must stay untouched (scrim is bottom-only).
    top = after.crop((0, 0, w, int(h * 0.4)))
    top_before = before.crop((0, 0, w, int(h * 0.4)))
    assert ImageChops.difference(top, top_before).getbbox() is None


def test_apply_ke_branding_is_silent_on_missing_assets(tmp_path):
    """A branding failure must never fail the generation it decorates."""
    assert apply_ke_branding(str(tmp_path / "nope.png"), logo_path=str(tmp_path / "no.png")) is False
    target = _gradient_png(tmp_path / "ok.png")
    assert apply_ke_branding(str(target), logo_path=str(tmp_path / "absent.png")) is False


def test_apply_ke_branding_preserves_jpeg_sources(tmp_path):
    from PIL import Image

    logo = tmp_path / "logo.png"
    Image.new("RGBA", (64, 76), (10, 200, 90, 255)).save(logo)
    target = tmp_path / "photo.jpg"
    Image.new("RGB", (400, 400), (30, 60, 90)).save(target, "JPEG")

    assert apply_ke_branding(str(target), logo_path=str(logo)) is True
    with Image.open(target) as img:
        assert img.format == "JPEG"


def test_generation_completion_brands_only_ke_corporate():
    source = inspect.getsource(
        __import__(
            "tools.media_studio.services.generation_service",
            fromlist=["on_generation_complete"],
        ).on_generation_complete
    )
    assert "apply_ke_branding(dest_path)" in source
    assert 'params.get("variant_branding") == "ke_corporate"' in source
    assert "ke_logo_applied" in source
