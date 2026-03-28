"""Tests for AI site generation via ARCHIE Bridge."""

import pytest
from unittest.mock import patch, MagicMock


def test_generate_site_returns_html_and_css():
    from core.site_generator import generate_site

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "<html><body><h1>Test Salon</h1></body></html>\n\n/* CSS */\nbody { color: red; }"
    }

    with patch(
        "core.site_generator.requests.post", return_value=mock_response
    ) as mock_post:
        result = generate_site(
            prompt="Create a salon website for Glamour Studio",
            business_name="Glamour Studio",
            bridge_url="http://localhost:5000",
            bridge_api_key="test-key",
        )

    assert "html" in result
    assert isinstance(result["html"], str)
    assert len(result["html"]) > 0
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "Bearer test-key" in str(call_kwargs)


def test_generate_site_with_template_context():
    from core.site_generator import generate_site

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "<html><body><h1>My Salon</h1><section>Services</section></body></html>"
    }

    template_context = {
        "base_prompt": "Create a modern hair salon website",
        "base_html": "<html><body>{{content}}</body></html>",
        "base_css": "body { font-family: sans-serif; }",
    }

    with patch("core.site_generator.requests.post", return_value=mock_response):
        result = generate_site(
            prompt="Add a booking page",
            business_name="My Salon",
            bridge_url="http://localhost:5000",
            bridge_api_key="test-key",
            template_context=template_context,
        )

    assert "html" in result
    assert len(result["html"]) > 0


def test_generate_site_bridge_error_raises():
    from core.site_generator import SiteGenerationError, generate_site

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = Exception("500 Server Error")

    with patch("core.site_generator.requests.post", return_value=mock_response):
        with pytest.raises(SiteGenerationError):
            generate_site(
                prompt="Build me a site",
                business_name="Test Co",
                bridge_url="http://localhost:5000",
                bridge_api_key="test-key",
            )


def test_refine_site_sends_current_html():
    from core.site_generator import refine_site

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "<html><body><h1>Updated</h1><p>New paragraph</p></body></html>"
    }

    with patch(
        "core.site_generator.requests.post", return_value=mock_response
    ) as mock_post:
        result = refine_site(
            refinement_prompt="Add a testimonials section",
            current_html="<html><body><h1>Original</h1></body></html>",
            bridge_url="http://localhost:5000",
            bridge_api_key="test-key",
        )

    assert "html" in result
    assert len(result["html"]) > 0
    assert mock_post.called


def test_generate_site_timeout():
    from core.site_generator import SiteGenerationError, generate_site

    with patch(
        "core.site_generator.requests.post",
        side_effect=Exception("Connection timed out"),
    ):
        with pytest.raises(SiteGenerationError, match="timed out|failed"):
            generate_site(
                prompt="Build a site",
                business_name="Test",
                bridge_url="http://localhost:5000",
                bridge_api_key="test-key",
            )


def test_extract_html_strips_markdown_fences():
    from core.site_generator import _extract_html

    raw = '```html\n<!DOCTYPE html><html><body>Hello</body></html>\n```'
    result = _extract_html(raw)
    assert result.startswith("<!DOCTYPE html>")
    assert "```" not in result


def test_extract_html_finds_html_in_preamble():
    from core.site_generator import _extract_html

    raw = "Here is your website:\n\n<!DOCTYPE html><html><body>Hi</body></html>"
    result = _extract_html(raw)
    assert result.startswith("<!DOCTYPE html>")


def test_build_generation_prompt_without_template():
    from core.site_generator import _build_generation_prompt

    prompt = _build_generation_prompt("Build a salon", "Glamour Studio")
    assert "Glamour Studio" in prompt
    assert "Build a salon" in prompt
    assert "REQUIREMENTS" in prompt


def test_build_generation_prompt_with_template():
    from core.site_generator import _build_generation_prompt

    ctx = {
        "base_prompt": "Modern salon",
        "base_html": "<html></html>",
        "base_css": "body{}",
    }
    prompt = _build_generation_prompt("Customize it", "Test Salon", ctx)
    assert "TEMPLATE DESIGN DIRECTION" in prompt
    assert "Modern salon" in prompt
