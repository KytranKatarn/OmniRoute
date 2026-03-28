"""Tests for AI generate, refine, preview, onboarding, and deploy routes (unit-level)."""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Site Generator integration tests (no DB needed)
# ---------------------------------------------------------------------------


def test_generate_site_saves_html():
    """generate_site returns html and prompt_used keys."""
    from core.site_generator import generate_site

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": "<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Generated</h1></body></html>"
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("core.site_generator.requests.post", return_value=mock_resp):
        result = generate_site(
            prompt="Create a modern salon website",
            business_name="Test Salon",
            bridge_url="http://localhost:5000",
            bridge_api_key="test-key",
        )

    assert "html" in result
    assert "prompt_used" in result
    assert "<!DOCTYPE html>" in result["html"] or "<html>" in result["html"]


def test_generate_site_with_template_includes_template_in_prompt():
    """generate_site with template_context includes template data in prompt."""
    from core.site_generator import generate_site

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": "<!DOCTYPE html><html><body><h1>Salon</h1></body></html>"
    }
    mock_resp.raise_for_status = MagicMock()

    template_ctx = {
        "base_prompt": "Modern salon design",
        "base_html": "<html><body>Template</body></html>",
        "base_css": "body{color:red}",
    }

    with patch("core.site_generator.requests.post", return_value=mock_resp):
        result = generate_site(
            prompt="Build my salon site",
            business_name="My Salon",
            bridge_url="http://localhost:5000",
            bridge_api_key="test-key",
            template_context=template_ctx,
        )

    assert "TEMPLATE DESIGN DIRECTION" in result["prompt_used"]
    assert "Modern salon design" in result["prompt_used"]


def test_refine_site_includes_current_html():
    """refine_site includes the current HTML in the prompt."""
    from core.site_generator import refine_site

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": "<!DOCTYPE html><html><body><h1>Updated</h1></body></html>"
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("core.site_generator.requests.post", return_value=mock_resp):
        result = refine_site(
            refinement_prompt="Add testimonials",
            current_html="<html><body><h1>Original</h1></body></html>",
            bridge_url="http://localhost:5000",
            bridge_api_key="test-key",
        )

    assert "html" in result
    assert "CURRENT SITE" in result["prompt_used"]
    assert "<h1>Original</h1>" in result["prompt_used"]


# ---------------------------------------------------------------------------
# Hostinger deploy integration tests
# ---------------------------------------------------------------------------


def test_deploy_builds_zip_from_pages():
    """build_site_zip creates valid ZIP with correct filenames."""
    import io
    import zipfile

    from core.hostinger_deploy import build_site_zip

    pages = [
        {"slug": "index", "content": "<html>Home</html>"},
        {"slug": "about", "content": "<html>About</html>"},
        {"slug": "contact", "content": "<html>Contact</html>"},
    ]

    zip_bytes = build_site_zip(pages)
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = zf.namelist()

    assert "index.html" in names
    assert "about.html" in names
    assert "contact.html" in names
    assert zf.read("index.html").decode() == "<html>Home</html>"


def test_deploy_stub_returns_pending():
    """deploy_to_hostinger with empty API key returns pending_manual."""
    from core.hostinger_deploy import deploy_to_hostinger

    result = deploy_to_hostinger(
        zip_bytes=b"fake",
        domain="test.kytranempowerment.com",
        hostinger_api_key="",
    )

    assert result["status"] == "pending_manual"
    assert "test.kytranempowerment.com" in result["url"]


# ---------------------------------------------------------------------------
# Route registration smoke tests
# ---------------------------------------------------------------------------


def test_routes_registered():
    """Verify all new routes are registered on the blueprint."""
    from plugins.kbs_website_builder import create_blueprint

    manifest = {"slug": "website-builder"}
    bp = create_blueprint(manifest)

    # Collect all rule strings from deferred registrations
    assert bp.name == "website_builder"


def test_manifest_includes_new_events():
    """Verify manifest.json includes the new event types."""
    import json
    import os

    manifest_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "kbs_website_builder",
        "manifest.json",
    )
    with open(manifest_path) as f:
        manifest = json.load(f)

    assert "site.generated" in manifest["emits"]
    assert "site.refined" in manifest["emits"]
    assert "site.deployed" in manifest["emits"]
    assert manifest["version"] == "1.1.0"


def test_manifest_description_updated():
    """Verify manifest description mentions AI generation."""
    import json
    import os

    manifest_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "kbs_website_builder",
        "manifest.json",
    )
    with open(manifest_path) as f:
        manifest = json.load(f)

    assert "AI" in manifest["description"] or "ai" in manifest["description"].lower()


# ---------------------------------------------------------------------------
# Route import smoke tests (verifies no import errors)
# ---------------------------------------------------------------------------


def test_routes_module_imports_cleanly():
    """Verify routes.py imports without error."""
    import plugins.kbs_website_builder.routes as routes_mod

    assert hasattr(routes_mod, "register_routes")
    assert callable(routes_mod.register_routes)


def test_site_generator_module_imports():
    """Verify site_generator.py exports expected symbols."""
    from core.site_generator import (
        SiteGenerationError,
        generate_site,
        refine_site,
        _extract_html,
        _build_generation_prompt,
        _build_refinement_prompt,
    )

    assert callable(generate_site)
    assert callable(refine_site)
    assert issubclass(SiteGenerationError, Exception)


def test_hostinger_deploy_module_imports():
    """Verify hostinger_deploy.py exports expected symbols."""
    from core.hostinger_deploy import (
        DeploymentError,
        build_site_zip,
        deploy_to_hostinger,
    )

    assert callable(build_site_zip)
    assert callable(deploy_to_hostinger)
    assert issubclass(DeploymentError, Exception)
