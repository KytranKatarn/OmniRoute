"""AI site generation service — calls ARCHIE Bridge for HTML/CSS generation."""

import logging
import re

import requests

logger = logging.getLogger(__name__)


class SiteGenerationError(Exception):
    """Raised when site generation fails."""

    pass


def _build_generation_prompt(
    prompt: str, business_name: str, template_context: dict | None = None
) -> str:
    """Build the full prompt sent to ARCHIE Bridge for site generation."""
    parts = []

    if template_context:
        base_prompt = template_context.get("base_prompt", "")
        base_html = template_context.get("base_html", "")
        base_css = template_context.get("base_css", "")
        parts.append(
            f"You are a web designer. Use this template as a starting point:\n\n"
            f"TEMPLATE DESIGN DIRECTION:\n{base_prompt}\n\n"
            f"TEMPLATE HTML STRUCTURE:\n{base_html}\n\n"
            f"TEMPLATE CSS:\n{base_css}\n\n"
            f"BUSINESS NAME: {business_name}\n\n"
            f"USER REQUEST: {prompt}\n\n"
        )
    else:
        parts.append(
            f"You are a web designer. Generate a complete, modern, mobile-responsive website.\n\n"
            f"BUSINESS NAME: {business_name}\n\n"
            f"USER REQUEST: {prompt}\n\n"
        )

    parts.append(
        "REQUIREMENTS:\n"
        "- Return ONLY valid HTML with embedded <style> tags (single self-contained file)\n"
        "- Mobile-responsive with viewport meta tag\n"
        "- Professional, modern design with appropriate color scheme\n"
        "- Include all sections with realistic placeholder content\n"
        "- Use semantic HTML5 elements\n"
        "- No external dependencies (no CDN links)\n"
        "- Replace {{business_name}} with the actual business name\n"
        "- Do NOT include any markdown code fences, just raw HTML\n"
    )

    return "\n".join(parts)


def _build_refinement_prompt(refinement_prompt: str, current_html: str) -> str:
    """Build the prompt for refining an existing site."""
    return (
        f"You are a web designer. Here is the current website HTML:\n\n"
        f"CURRENT SITE:\n{current_html}\n\n"
        f"USER REFINEMENT REQUEST: {refinement_prompt}\n\n"
        f"REQUIREMENTS:\n"
        f"- Return the COMPLETE updated HTML (not just the changed parts)\n"
        f"- Keep all existing sections unless the user asks to remove them\n"
        f"- Maintain the same design language and color scheme unless asked to change\n"
        f"- Mobile-responsive\n"
        f"- No external dependencies\n"
        f"- Do NOT include any markdown code fences, just raw HTML\n"
    )


def _extract_html(raw_response: str) -> str:
    """Extract clean HTML from Bridge response, stripping markdown fences if present."""
    text = raw_response.strip()

    # Strip markdown code fences if the model wrapped the output
    fence_match = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Ensure it looks like HTML
    if not text.startswith("<!DOCTYPE") and not text.startswith("<html"):
        # Try to find the HTML start
        html_start = text.find("<!DOCTYPE")
        if html_start == -1:
            html_start = text.find("<html")
        if html_start >= 0:
            text = text[html_start:]

    return text


def _call_bridge(prompt: str, bridge_url: str, bridge_api_key: str) -> str:
    """Call the ARCHIE Bridge and return the raw response text."""
    try:
        response = requests.post(
            f"{bridge_url}/api/bridge",
            json={
                "prompt": prompt,
                "model": "qwen2.5-coder:7b",
                "max_tokens": 4096,
            },
            headers={"Authorization": f"Bearer {bridge_api_key}"},
            timeout=120,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise SiteGenerationError("Bridge request timed out after 120 seconds")
    except Exception as exc:
        raise SiteGenerationError(f"Bridge request failed: {exc}")

    data = response.json()
    raw = data.get("response", "")
    if not raw:
        raise SiteGenerationError("Bridge returned empty response")

    return raw


def generate_site(
    prompt: str,
    business_name: str,
    bridge_url: str,
    bridge_api_key: str,
    template_context: dict | None = None,
) -> dict:
    """Generate a website from a text prompt via ARCHIE Bridge.

    Args:
        prompt: User's description of the site they want.
        business_name: Name of the business for the site.
        bridge_url: ARCHIE Bridge base URL (from KBS_BRIDGE_URL).
        bridge_api_key: ARCHIE Bridge API key (from KBS_BRIDGE_API_KEY).
        template_context: Optional dict with base_prompt, base_html, base_css from a template.

    Returns:
        dict with keys: html (str), prompt_used (str)

    Raises:
        SiteGenerationError: If Bridge call fails or returns invalid data.
    """
    full_prompt = _build_generation_prompt(prompt, business_name, template_context)

    logger.info(
        "Generating site for '%s' (template: %s)",
        business_name,
        bool(template_context),
    )
    raw = _call_bridge(full_prompt, bridge_url, bridge_api_key)
    html = _extract_html(raw)

    return {
        "html": html,
        "prompt_used": full_prompt,
    }


def refine_site(
    refinement_prompt: str,
    current_html: str,
    bridge_url: str,
    bridge_api_key: str,
) -> dict:
    """Refine an existing site based on user feedback via ARCHIE Bridge.

    Args:
        refinement_prompt: What the user wants changed.
        current_html: The current site HTML to modify.
        bridge_url: ARCHIE Bridge base URL.
        bridge_api_key: ARCHIE Bridge API key.

    Returns:
        dict with keys: html (str), prompt_used (str)

    Raises:
        SiteGenerationError: If Bridge call fails.
    """
    full_prompt = _build_refinement_prompt(refinement_prompt, current_html)

    logger.info("Refining site: %s", refinement_prompt[:80])
    raw = _call_bridge(full_prompt, bridge_url, bridge_api_key)
    html = _extract_html(raw)

    return {
        "html": html,
        "prompt_used": full_prompt,
    }
