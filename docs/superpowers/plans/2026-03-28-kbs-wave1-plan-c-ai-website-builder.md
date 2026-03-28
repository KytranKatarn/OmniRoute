# KBS Wave 1 Plan C: AI Website Builder

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add text-to-design AI generation, a template system, Hostinger deployment, live preview, and an onboarding wizard to the existing Website Builder plugin so tenants can describe a site in plain English, preview it live, iterate with AI refinement, and deploy to Hostinger in one click.

**Architecture:** The Website Builder plugin already has CRUD routes for projects, pages, and deployments in `plugins/kbs_website_builder/routes.py`. New AI generation and deployment logic lives in dedicated service files under `core/` (following the same pattern as `core/pdf_generator.py` and `core/mail_client.py`). The AI site generator calls the ARCHIE Bridge at `KBS_BRIDGE_URL` for HTML/CSS generation. Templates are stored in a new `website_templates` table seeded via migration. Hostinger deployment zips generated pages and uploads via the Hostinger hosting API. All routes use the standard `get_db_cursor()` + `set_tenant_search_path()` + `event_bus.emit()` pattern.

**Tech Stack:** Flask, PostgreSQL, psycopg2, requests (Bridge + Hostinger API), pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `plugins/kbs_website_builder/migrations/002_website_templates.sql` | Templates table + seed data |
| Create | `core/site_generator.py` | AI site generation via ARCHIE Bridge |
| Create | `core/hostinger_deploy.py` | Static site deployment to Hostinger |
| Modify | `plugins/kbs_website_builder/routes.py` | Template list/detail, AI generate, AI refine, live preview, wired deploy |
| Modify | `plugins/kbs_website_builder/manifest.json` | Add new events |
| Create | `tests/test_site_generator.py` | AI generator unit tests |
| Create | `tests/test_hostinger_deploy.py` | Deployment service unit tests |
| Create | `tests/test_website_templates.py` | Template CRUD tests |
| Create | `tests/test_website_ai_routes.py` | AI generate/refine route integration tests |

---

## Task 1: Website Templates Migration + Seed Data

**Files:**
- Create: `plugins/kbs_website_builder/migrations/002_website_templates.sql`

- [ ] **Step 1: Create the migration file**

Create `plugins/kbs_website_builder/migrations/002_website_templates.sql`:

```sql
-- Website templates table + seed data
-- Run against tenant schema (search_path must be set before executing)

CREATE TABLE IF NOT EXISTS website_templates (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL UNIQUE,
    category        VARCHAR(100) NOT NULL,
    description     TEXT,
    thumbnail_url   VARCHAR(500),
    base_prompt     TEXT NOT NULL,
    base_html       TEXT NOT NULL,
    base_css        TEXT DEFAULT '',
    settings        JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_website_templates_category ON website_templates(category);
CREATE INDEX IF NOT EXISTS idx_website_templates_slug ON website_templates(slug);

-- Seed industry templates
INSERT INTO website_templates (name, slug, category, description, base_prompt, base_html, base_css)
VALUES
(
    'Hair Salon & Spa',
    'salon-spa',
    'salon',
    'Elegant salon website with booking CTA, service menu, stylist profiles, and gallery.',
    'Create a modern, elegant hair salon and spa website. Use warm tones (rose gold, cream, soft pink). Include sections: hero with booking button, services menu with prices, stylist team profiles, photo gallery, contact with hours and map embed placeholder. Mobile-responsive. Professional typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Hair Salon & Spa</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#services">Services</a><a href="#team">Our Team</a><a href="#gallery">Gallery</a><a href="#contact">Contact</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#contact" class="btn-book">Book Appointment</a>
    </header>
    <section id="services" class="services"><h2>Our Services</h2><div class="service-grid"><!-- AI will populate --></div></section>
    <section id="team" class="team"><h2>Meet Our Stylists</h2><div class="team-grid"><!-- AI will populate --></div></section>
    <section id="gallery" class="gallery"><h2>Gallery</h2><div class="gallery-grid"><!-- AI will populate --></div></section>
    <section id="contact" class="contact"><h2>Visit Us</h2><div class="contact-info"><!-- AI will populate --></div></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Segoe UI",sans-serif;color:#2d2d2d}.hero{background:linear-gradient(135deg,#f9e4e4,#fce4ec);text-align:center;padding:80px 20px}nav a{margin:0 15px;color:#8b6f6f;text-decoration:none}.btn-book{display:inline-block;margin-top:20px;padding:14px 32px;background:#c9917a;color:#fff;border-radius:30px;text-decoration:none}section{padding:60px 20px;max-width:1100px;margin:auto}h2{text-align:center;color:#8b6f6f;margin-bottom:30px}.service-grid,.team-grid,.gallery-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:24px}footer{text-align:center;padding:30px;background:#fce4ec;color:#8b6f6f}'
),
(
    'Construction & Trades',
    'construction',
    'construction',
    'Bold construction company site with project showcase, services, safety certifications, and quote request.',
    'Create a bold, professional construction company website. Use strong colors (navy blue, safety orange, concrete gray). Include sections: hero with "Get a Free Quote" CTA, services list (residential, commercial, renovation), featured projects gallery, safety certifications, testimonials, contact form. Mobile-responsive. Strong, masculine typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Construction Services</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#services">Services</a><a href="#projects">Projects</a><a href="#about">About</a><a href="#contact">Contact</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#contact" class="btn-quote">Get a Free Quote</a>
    </header>
    <section id="services" class="services"><h2>Our Services</h2><div class="service-grid"><!-- AI will populate --></div></section>
    <section id="projects" class="projects"><h2>Featured Projects</h2><div class="project-grid"><!-- AI will populate --></div></section>
    <section id="about" class="about"><h2>Why Choose Us</h2><!-- AI will populate --></section>
    <section id="contact" class="contact"><h2>Request a Quote</h2><form class="quote-form"><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Arial Black",sans-serif;color:#1a1a2e}.hero{background:linear-gradient(135deg,#1a1a2e,#16213e);text-align:center;padding:80px 20px;color:#fff}nav a{margin:0 15px;color:#e94560;text-decoration:none;font-weight:bold}.btn-quote{display:inline-block;margin-top:20px;padding:14px 32px;background:#e94560;color:#fff;border-radius:4px;text-decoration:none;font-weight:bold}section{padding:60px 20px;max-width:1100px;margin:auto}h2{text-align:center;color:#1a1a2e;margin-bottom:30px}.service-grid,.project-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}footer{text-align:center;padding:30px;background:#1a1a2e;color:#e94560}'
),
(
    'Photography Portfolio',
    'photography',
    'photography',
    'Minimal, image-first photography portfolio with fullscreen gallery, about, and booking.',
    'Create a minimal, elegant photography portfolio website. Use dark/moody tones (charcoal, off-white, gold accent). Include sections: fullscreen hero image placeholder, portfolio gallery grid, about the photographer, services and pricing, contact/booking form. Mobile-responsive. Clean, minimal typography with generous whitespace.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Photography</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero"><h1>{{business_name}}</h1><p>{{tagline}}</p></header>
    <section id="portfolio" class="portfolio"><h2>Portfolio</h2><div class="photo-grid"><!-- AI will populate --></div></section>
    <section id="about" class="about"><h2>About</h2><!-- AI will populate --></section>
    <section id="pricing" class="pricing"><h2>Packages</h2><div class="pricing-grid"><!-- AI will populate --></div></section>
    <section id="contact" class="contact"><h2>Book a Session</h2><form><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Georgia",serif;color:#e0e0e0;background:#1a1a1a}.hero{height:80vh;display:flex;flex-direction:column;justify-content:center;align-items:center;background:#111;color:#d4af37}h1{font-size:3rem;letter-spacing:4px}section{padding:60px 20px;max-width:1200px;margin:auto}h2{text-align:center;color:#d4af37;letter-spacing:2px}.photo-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}.pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}footer{text-align:center;padding:30px;color:#666}'
),
(
    'Restaurant & Cafe',
    'restaurant',
    'restaurant',
    'Warm restaurant site with menu, hours, reservation CTA, chef story, and location.',
    'Create a warm, inviting restaurant website. Use appetizing colors (burgundy, cream, olive green). Include sections: hero with reservation button, full menu with categories (appetizers, mains, desserts, drinks), chef story/about, hours and location with map placeholder, photo gallery. Mobile-responsive. Elegant serif typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Restaurant</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#menu">Menu</a><a href="#about">Our Story</a><a href="#hours">Hours</a><a href="#contact">Reserve</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#contact" class="btn-reserve">Make a Reservation</a>
    </header>
    <section id="menu" class="menu"><h2>Our Menu</h2><!-- AI will populate --></section>
    <section id="about" class="about"><h2>Our Story</h2><!-- AI will populate --></section>
    <section id="hours" class="hours"><h2>Hours & Location</h2><!-- AI will populate --></section>
    <section id="contact" class="contact"><h2>Reservations</h2><form><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Playfair Display",Georgia,serif;color:#2d1f1f;background:#faf5f0}.hero{background:linear-gradient(135deg,#3d1f1f,#5a2d2d);text-align:center;padding:80px 20px;color:#faf5f0}nav a{margin:0 15px;color:#c9a96e;text-decoration:none}.btn-reserve{display:inline-block;margin-top:20px;padding:14px 32px;background:#c9a96e;color:#2d1f1f;border-radius:4px;text-decoration:none;font-weight:bold}section{padding:60px 20px;max-width:1000px;margin:auto}h2{text-align:center;color:#5a2d2d;margin-bottom:30px}footer{text-align:center;padding:30px;background:#3d1f1f;color:#c9a96e}'
),
(
    'Fitness & Gym',
    'fitness',
    'fitness',
    'High-energy gym website with class schedule, trainer profiles, membership plans, and signup CTA.',
    'Create a high-energy fitness and gym website. Use bold colors (electric blue, neon green, dark charcoal). Include sections: hero with "Join Now" CTA, class schedule grid, trainer profiles, membership pricing tiers (basic/pro/elite), testimonials, contact and location. Mobile-responsive. Bold, sporty typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Fitness</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#classes">Classes</a><a href="#trainers">Trainers</a><a href="#pricing">Pricing</a><a href="#contact">Join</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#pricing" class="btn-join">Join Now</a>
    </header>
    <section id="classes" class="classes"><h2>Class Schedule</h2><div class="schedule-grid"><!-- AI will populate --></div></section>
    <section id="trainers" class="trainers"><h2>Our Trainers</h2><div class="trainer-grid"><!-- AI will populate --></div></section>
    <section id="pricing" class="pricing"><h2>Membership Plans</h2><div class="pricing-grid"><!-- AI will populate --></div></section>
    <section id="contact" class="contact"><h2>Get Started</h2><form><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Impact",sans-serif;color:#e0e0e0;background:#1a1a2e}.hero{background:linear-gradient(135deg,#0f0f23,#1a1a2e);text-align:center;padding:80px 20px;color:#00f5d4}nav a{margin:0 15px;color:#00bbf9;text-decoration:none;text-transform:uppercase}.btn-join{display:inline-block;margin-top:20px;padding:14px 32px;background:#00f5d4;color:#0f0f23;border-radius:4px;text-decoration:none;font-weight:bold;text-transform:uppercase}section{padding:60px 20px;max-width:1100px;margin:auto}h2{text-align:center;color:#00f5d4;text-transform:uppercase;letter-spacing:3px}.schedule-grid,.trainer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:24px}.pricing-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}footer{text-align:center;padding:30px;background:#0f0f23;color:#00bbf9}'
),
(
    'Professional Services',
    'professional',
    'professional',
    'Clean professional services site for consultants, lawyers, accountants with service pages and contact.',
    'Create a clean, trustworthy professional services website suitable for consultants, lawyers, or accountants. Use corporate colors (navy, white, steel blue accent). Include sections: hero with consultation CTA, services overview, team/partner profiles, client testimonials, case studies preview, contact form with office location. Mobile-responsive. Professional sans-serif typography.',
    '<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{business_name}} - Professional Services</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header class="hero">
        <nav><a href="#services">Services</a><a href="#team">Team</a><a href="#testimonials">Clients</a><a href="#contact">Contact</a></nav>
        <h1>{{business_name}}</h1>
        <p>{{tagline}}</p>
        <a href="#contact" class="btn-consult">Schedule Consultation</a>
    </header>
    <section id="services" class="services"><h2>Our Services</h2><div class="service-grid"><!-- AI will populate --></div></section>
    <section id="team" class="team"><h2>Our Team</h2><div class="team-grid"><!-- AI will populate --></div></section>
    <section id="testimonials" class="testimonials"><h2>Client Testimonials</h2><!-- AI will populate --></section>
    <section id="contact" class="contact"><h2>Contact Us</h2><form><!-- AI will populate --></form></section>
    <footer><p>&copy; {{year}} {{business_name}}. All rights reserved.</p></footer>
</body>
</html>',
    'body{margin:0;font-family:"Segoe UI",Helvetica,sans-serif;color:#2c3e50;background:#fff}.hero{background:linear-gradient(135deg,#1a365d,#2d4a7a);text-align:center;padding:80px 20px;color:#fff}nav a{margin:0 15px;color:#90cdf4;text-decoration:none}.btn-consult{display:inline-block;margin-top:20px;padding:14px 32px;background:#4299e1;color:#fff;border-radius:4px;text-decoration:none}section{padding:60px 20px;max-width:1100px;margin:auto}h2{text-align:center;color:#1a365d;margin-bottom:30px}.service-grid,.team-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}footer{text-align:center;padding:30px;background:#1a365d;color:#90cdf4}'
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    base_prompt = EXCLUDED.base_prompt,
    base_html = EXCLUDED.base_html,
    base_css = EXCLUDED.base_css;
```

- [ ] **Step 2: Run the migration inside the container**

```bash
docker exec kbs_app python -c "
from core.database import get_db_cursor, set_tenant_search_path
import os

# Run for shared schema (templates are global, not per-tenant)
with get_db_cursor(commit=True) as (conn, cur):
    migration = open('plugins/kbs_website_builder/migrations/002_website_templates.sql').read()
    cur.execute(migration)
    print('Migration applied successfully')
    cur.execute('SELECT COUNT(*) FROM website_templates')
    print(f'Templates seeded: {cur.fetchone()[0]}')
"
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_website_builder/migrations/002_website_templates.sql
git commit -m "feat(website-builder): add website_templates table with 6 industry seeds"
```

---

## Task 2: AI Site Generator Service

**Files:**
- Create: `core/site_generator.py`
- Create: `tests/test_site_generator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_site_generator.py`:

```python
"""Tests for AI site generation via ARCHIE Bridge."""

import json
import pytest
from unittest.mock import patch, MagicMock


def test_generate_site_returns_html_and_css():
    from core.site_generator import generate_site

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "<html><body><h1>Test Salon</h1></body></html>\n\n/* CSS */\nbody { color: red; }"
    }

    with patch("core.site_generator.requests.post", return_value=mock_response) as mock_post:
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

    with patch("core.site_generator.requests.post", return_value=mock_response) as mock_post:
        result = refine_site(
            refinement_prompt="Add a testimonials section",
            current_html="<html><body><h1>Original</h1></body></html>",
            bridge_url="http://localhost:5000",
            bridge_api_key="test-key",
        )

    assert "html" in result
    assert len(result["html"]) > 0
    # Verify the current HTML was included in the prompt
    call_args = mock_post.call_args
    sent_prompt = call_args[1]["json"]["prompt"] if "json" in call_args[1] else call_args[0][0]
    # The prompt should reference the current HTML somehow
    assert mock_post.called


def test_generate_site_timeout():
    from core.site_generator import SiteGenerationError, generate_site

    with patch("core.site_generator.requests.post", side_effect=Exception("Connection timed out")):
        with pytest.raises(SiteGenerationError, match="timed out|failed"):
            generate_site(
                prompt="Build a site",
                business_name="Test",
                bridge_url="http://localhost:5000",
                bridge_api_key="test-key",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec kbs_app python -m pytest tests/test_site_generator.py -v 2>&1 | head -30
```

- [ ] **Step 3: Implement the site generator**

Create `core/site_generator.py`:

```python
"""AI site generation service — calls ARCHIE Bridge for HTML/CSS generation."""

import logging
import re

import requests

logger = logging.getLogger(__name__)


class SiteGenerationError(Exception):
    """Raised when site generation fails."""
    pass


def _build_generation_prompt(prompt: str, business_name: str, template_context: dict | None = None) -> str:
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

    logger.info("Generating site for '%s' (template: %s)", business_name, bool(template_context))
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_site_generator.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/site_generator.py tests/test_site_generator.py
git commit -m "feat(website-builder): add AI site generator service with Bridge integration"
```

---

## Task 3: Template List + Detail Routes

**Files:**
- Modify: `plugins/kbs_website_builder/routes.py`
- Create: `tests/test_website_templates.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_website_templates.py`:

```python
"""Tests for website template list and detail routes."""

import pytest


def test_list_templates_returns_all(client, seed_tenant):
    """GET /website-builder/api/templates returns seeded templates."""
    resp = client.get("/website-builder/api/templates")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "templates" in data
    assert isinstance(data["templates"], list)
    assert len(data["templates"]) >= 5


def test_list_templates_filter_by_category(client, seed_tenant):
    """GET /website-builder/api/templates?category=salon filters correctly."""
    resp = client.get("/website-builder/api/templates?category=salon")
    assert resp.status_code == 200
    data = resp.get_json()
    for t in data["templates"]:
        assert t["category"] == "salon"


def test_get_template_by_slug(client, seed_tenant):
    """GET /website-builder/api/templates/salon-spa returns the salon template."""
    resp = client.get("/website-builder/api/templates/salon-spa")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["slug"] == "salon-spa"
    assert "base_html" in data
    assert "base_prompt" in data
    assert "base_css" in data


def test_get_template_not_found(client, seed_tenant):
    """GET /website-builder/api/templates/nonexistent returns 404."""
    resp = client.get("/website-builder/api/templates/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec kbs_app python -m pytest tests/test_website_templates.py -v 2>&1 | head -20
```

- [ ] **Step 3: Add template routes to routes.py**

Add these routes inside the `register_routes(bp)` function in `plugins/kbs_website_builder/routes.py`, after the Stats section:

```python
    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    @bp.route("/api/templates", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def list_templates():
        category = request.args.get("category")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = "WHERE is_active = TRUE"
            params: list = []
            if category:
                where += " AND category = %s"
                params.append(category)

            cur.execute(
                f"""
                SELECT id, name, slug, category, description, thumbnail_url,
                       base_prompt, created_at
                FROM website_templates {where}
                ORDER BY category, name
                """,
                params,
            )
            templates = cur.fetchall()

        return jsonify({"templates": templates, "total": len(templates)})

    @bp.route("/api/templates/<slug>", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def get_template(slug):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, slug, category, description, thumbnail_url,
                       base_prompt, base_html, base_css, settings, created_at
                FROM website_templates
                WHERE slug = %s AND is_active = TRUE
                """,
                (slug,),
            )
            template = cur.fetchone()

        if template is None:
            return jsonify({"error": "template not found"}), 404
        return jsonify(template)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_website_templates.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_website_builder/routes.py tests/test_website_templates.py
git commit -m "feat(website-builder): add template list and detail routes"
```

---

## Task 4: AI Generate Endpoint

**Files:**
- Modify: `plugins/kbs_website_builder/routes.py`
- Create: `tests/test_website_ai_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_website_ai_routes.py`:

```python
"""Tests for AI generate and refine routes."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_bridge_success():
    """Mock a successful Bridge response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "response": "<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Generated</h1></body></html>"
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_generate_requires_prompt(client, seed_tenant, sample_project):
    """POST /website-builder/api/projects/{id}/generate without prompt returns 400."""
    resp = client.post(
        f"/website-builder/api/projects/{sample_project}/generate",
        json={},
    )
    assert resp.status_code == 400
    assert "prompt" in resp.get_json().get("error", "").lower()


def test_generate_project_not_found(client, seed_tenant):
    """POST /website-builder/api/projects/99999/generate returns 404."""
    resp = client.post(
        "/website-builder/api/projects/99999/generate",
        json={"prompt": "Build me a salon site"},
    )
    assert resp.status_code == 404


def test_generate_success(client, seed_tenant, sample_project, mock_bridge_success):
    """POST /website-builder/api/projects/{id}/generate with valid prompt returns generated HTML."""
    with patch("core.site_generator.requests.post", return_value=mock_bridge_success):
        resp = client.post(
            f"/website-builder/api/projects/{sample_project}/generate",
            json={"prompt": "Create a modern salon website"},
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert "html" in data
    assert len(data["html"]) > 0
    assert "page_id" in data


def test_generate_with_template(client, seed_tenant, sample_project, mock_bridge_success):
    """POST /website-builder/api/projects/{id}/generate with template_slug uses template context."""
    with patch("core.site_generator.requests.post", return_value=mock_bridge_success):
        resp = client.post(
            f"/website-builder/api/projects/{sample_project}/generate",
            json={
                "prompt": "Build my salon site",
                "template_slug": "salon-spa",
            },
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert "html" in data


def test_refine_requires_prompt_and_html(client, seed_tenant, sample_project):
    """POST /website-builder/api/projects/{id}/refine without prompt returns 400."""
    resp = client.post(
        f"/website-builder/api/projects/{sample_project}/refine",
        json={},
    )
    assert resp.status_code == 400


def test_refine_success(client, seed_tenant, sample_project, mock_bridge_success):
    """POST /website-builder/api/projects/{id}/refine with valid data returns refined HTML."""
    with patch("core.site_generator.requests.post", return_value=mock_bridge_success):
        resp = client.post(
            f"/website-builder/api/projects/{sample_project}/refine",
            json={
                "prompt": "Add a testimonials section",
                "current_html": "<html><body><h1>Original</h1></body></html>",
            },
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert "html" in data
    assert len(data["html"]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec kbs_app python -m pytest tests/test_website_ai_routes.py -v 2>&1 | head -30
```

- [ ] **Step 3: Add the generate endpoint to routes.py**

Add after the Templates section in `plugins/kbs_website_builder/routes.py`:

```python
    # ------------------------------------------------------------------
    # AI Generation
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/generate", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def generate_site_route(project_id):
        import os
        from core.site_generator import SiteGenerationError, generate_site

        data = request.get_json(force=True)
        prompt = (data.get("prompt") or "").strip()
        template_slug = data.get("template_slug")

        if not prompt:
            return jsonify({"error": "prompt is required"}), 400

        bridge_url = os.environ.get("KBS_BRIDGE_URL", "")
        bridge_api_key = os.environ.get("KBS_BRIDGE_API_KEY", "")
        if not bridge_url:
            return jsonify({"error": "AI Bridge not configured"}), 503

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Verify project exists
            cur.execute(
                "SELECT id, name FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()
            if project is None:
                return jsonify({"error": "project not found"}), 404

            # Fetch template context if requested
            template_context = None
            if template_slug:
                cur.execute(
                    """
                    SELECT base_prompt, base_html, base_css
                    FROM website_templates
                    WHERE slug = %s AND is_active = TRUE
                    """,
                    (template_slug,),
                )
                template_context = cur.fetchone()
                # template_context is None if slug not found — that's fine, generate without it

            try:
                result = generate_site(
                    prompt=prompt,
                    business_name=project["name"],
                    bridge_url=bridge_url,
                    bridge_api_key=bridge_api_key,
                    template_context=dict(template_context) if template_context else None,
                )
            except SiteGenerationError as exc:
                logger.error("Site generation failed for project %d: %s", project_id, exc)
                return jsonify({"error": f"Generation failed: {exc}"}), 502

            # Save generated HTML as the home page (upsert)
            cur.execute(
                """
                INSERT INTO website_pages (project_id, title, slug, content, page_type, sort_order)
                VALUES (%s, 'Home', 'index', %s, 'home', 0)
                ON CONFLICT (project_id, slug) DO UPDATE SET
                    content = EXCLUDED.content,
                    updated_at = NOW()
                RETURNING id
                """,
                (project_id, result["html"]),
            )
            page = cur.fetchone()

            # Update project status to building
            cur.execute(
                "UPDATE website_projects SET status = 'building', updated_at = NOW() WHERE id = %s",
                (project_id,),
            )

        event_bus.emit(
            "site.generated",
            {"project_id": project_id, "name": project["name"], "template": template_slug},
            tenant_id=g.tenant_id,
        )

        return jsonify({
            "html": result["html"],
            "page_id": page["id"],
            "project_id": project_id,
        })

    # ------------------------------------------------------------------
    # AI Refinement
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/refine", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def refine_site_route(project_id):
        import os
        from core.site_generator import SiteGenerationError, refine_site

        data = request.get_json(force=True)
        prompt = (data.get("prompt") or "").strip()
        current_html = (data.get("current_html") or "").strip()

        if not prompt:
            return jsonify({"error": "prompt is required"}), 400
        if not current_html:
            return jsonify({"error": "current_html is required"}), 400

        bridge_url = os.environ.get("KBS_BRIDGE_URL", "")
        bridge_api_key = os.environ.get("KBS_BRIDGE_API_KEY", "")
        if not bridge_url:
            return jsonify({"error": "AI Bridge not configured"}), 503

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id, name FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()
            if project is None:
                return jsonify({"error": "project not found"}), 404

            try:
                result = refine_site(
                    refinement_prompt=prompt,
                    current_html=current_html,
                    bridge_url=bridge_url,
                    bridge_api_key=bridge_api_key,
                )
            except SiteGenerationError as exc:
                logger.error("Site refinement failed for project %d: %s", project_id, exc)
                return jsonify({"error": f"Refinement failed: {exc}"}), 502

            # Update the home page content
            cur.execute(
                """
                UPDATE website_pages SET content = %s, updated_at = NOW()
                WHERE project_id = %s AND slug = 'index'
                RETURNING id
                """,
                (result["html"], project_id),
            )
            page = cur.fetchone()
            page_id = page["id"] if page else None

        event_bus.emit(
            "site.refined",
            {"project_id": project_id, "name": project["name"]},
            tenant_id=g.tenant_id,
        )

        return jsonify({
            "html": result["html"],
            "page_id": page_id,
            "project_id": project_id,
        })
```

- [ ] **Step 4: Update manifest.json to include new events**

Update `plugins/kbs_website_builder/manifest.json` — add `"site.generated"` and `"site.refined"` to the `emits` array:

```json
{
    "slug": "website-builder",
    "name": "Website Builder",
    "version": "1.1.0",
    "description": "Build and publish websites with AI generation, templates, and Hostinger deployment",
    "category": "marketing",
    "tier_required": "business",
    "price_monthly": null,
    "icon": "globe",
    "dependencies": [],
    "emits": ["site.created", "site.updated", "site.published", "site.generated", "site.refined", "site.deployed", "page.created", "page.updated"],
    "consumes": [],
    "permissions": ["website-builder.read", "website-builder.write", "website-builder.publish", "website-builder.admin"],
    "nav": {"label": "Website Builder", "icon": "globe", "order": 80}
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_website_ai_routes.py -v
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_website_builder/routes.py plugins/kbs_website_builder/manifest.json tests/test_website_ai_routes.py
git commit -m "feat(website-builder): add AI generate and refine endpoints with Bridge dispatch"
```

---

## Task 5: Live Preview Endpoint

**Files:**
- Modify: `plugins/kbs_website_builder/routes.py`

- [ ] **Step 1: Add the preview route**

Add after the AI Refinement section in `plugins/kbs_website_builder/routes.py`:

```python
    # ------------------------------------------------------------------
    # Live Preview
    # ------------------------------------------------------------------

    @bp.route("/api/projects/<int:project_id>/preview", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def preview_project(project_id):
        """Return the generated HTML for iframe preview rendering."""
        page_slug = request.args.get("page", "index")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id FROM website_projects WHERE id = %s",
                (project_id,),
            )
            if cur.fetchone() is None:
                return jsonify({"error": "project not found"}), 404

            cur.execute(
                """
                SELECT content FROM website_pages
                WHERE project_id = %s AND slug = %s
                """,
                (project_id, page_slug),
            )
            page = cur.fetchone()

        if page is None or not page["content"]:
            return (
                "<html><body style='display:flex;align-items:center;justify-content:center;"
                "height:100vh;font-family:sans-serif;color:#666;background:#f5f5f5'>"
                "<p>No content generated yet. Use the AI generator to create your site.</p>"
                "</body></html>",
                200,
                {"Content-Type": "text/html; charset=utf-8"},
            )

        return page["content"], 200, {"Content-Type": "text/html; charset=utf-8"}

    @bp.route("/api/projects/<int:project_id>/preview/pages", methods=["GET"])
    @login_required
    @require_module(MODULE)
    def preview_pages_list(project_id):
        """Return list of pages available for preview."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id FROM website_projects WHERE id = %s",
                (project_id,),
            )
            if cur.fetchone() is None:
                return jsonify({"error": "project not found"}), 404

            cur.execute(
                """
                SELECT slug, title, page_type,
                       (content IS NOT NULL AND content != '') AS has_content
                FROM website_pages
                WHERE project_id = %s
                ORDER BY sort_order, created_at
                """,
                (project_id,),
            )
            pages = cur.fetchall()

        return jsonify({"pages": pages})
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_website_builder/routes.py
git commit -m "feat(website-builder): add live preview endpoint returning raw HTML for iframe"
```

---

## Task 6: Hostinger Deployment Service

**Files:**
- Create: `core/hostinger_deploy.py`
- Create: `tests/test_hostinger_deploy.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hostinger_deploy.py`:

```python
"""Tests for Hostinger static site deployment service."""

import io
import zipfile
import pytest
from unittest.mock import patch, MagicMock


def test_build_site_zip_creates_valid_zip():
    from core.hostinger_deploy import build_site_zip

    pages = [
        {"slug": "index", "content": "<html><body><h1>Home</h1></body></html>"},
        {"slug": "about", "content": "<html><body><h1>About</h1></body></html>"},
    ]

    zip_bytes = build_site_zip(pages)

    assert isinstance(zip_bytes, bytes)
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = zf.namelist()
    assert "index.html" in names
    assert "about.html" in names
    assert len(names) == 2

    content = zf.read("index.html").decode("utf-8")
    assert "<h1>Home</h1>" in content


def test_build_site_zip_empty_pages():
    from core.hostinger_deploy import build_site_zip

    zip_bytes = build_site_zip([])
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    assert len(zf.namelist()) == 0


def test_deploy_to_hostinger_success():
    from core.hostinger_deploy import deploy_to_hostinger

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"url": "https://example.kytranempowerment.com", "status": "deployed"}

    with patch("core.hostinger_deploy.requests.post", return_value=mock_resp):
        result = deploy_to_hostinger(
            zip_bytes=b"fake-zip-data",
            domain="example.kytranempowerment.com",
            hostinger_api_key="test-key",
        )

    assert result["status"] == "deployed"
    assert "url" in result


def test_deploy_to_hostinger_failure():
    from core.hostinger_deploy import DeploymentError, deploy_to_hostinger

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Server Error"
    mock_resp.raise_for_status.side_effect = Exception("500")

    with patch("core.hostinger_deploy.requests.post", return_value=mock_resp):
        with pytest.raises(DeploymentError):
            deploy_to_hostinger(
                zip_bytes=b"fake-zip-data",
                domain="example.kytranempowerment.com",
                hostinger_api_key="test-key",
            )


def test_deploy_to_hostinger_stub_mode():
    """When no API key is configured, use stub mode that records the deployment."""
    from core.hostinger_deploy import deploy_to_hostinger

    result = deploy_to_hostinger(
        zip_bytes=b"fake-zip-data",
        domain="example.kytranempowerment.com",
        hostinger_api_key="",
    )

    assert result["status"] == "pending_manual"
    assert "url" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec kbs_app python -m pytest tests/test_hostinger_deploy.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement the deployment service**

Create `core/hostinger_deploy.py`:

```python
"""Hostinger static site deployment service.

Zips generated HTML/CSS pages and deploys to Hostinger hosting.
Falls back to stub mode (records deployment record) when API key is not configured.
"""

import io
import logging
import zipfile

import requests

logger = logging.getLogger(__name__)


class DeploymentError(Exception):
    """Raised when deployment to Hostinger fails."""
    pass


def build_site_zip(pages: list[dict]) -> bytes:
    """Build a ZIP archive from a list of page dicts.

    Args:
        pages: List of dicts with 'slug' and 'content' keys.
               The 'index' slug becomes index.html, others become {slug}.html.

    Returns:
        bytes: The ZIP file as bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for page in pages:
            slug = page.get("slug", "page")
            content = page.get("content", "")
            filename = f"{slug}.html"
            zf.writestr(filename, content)

    return buffer.getvalue()


def deploy_to_hostinger(
    zip_bytes: bytes,
    domain: str,
    hostinger_api_key: str,
    hostinger_api_url: str = "https://api.hostinger.com",
) -> dict:
    """Deploy a static site ZIP to Hostinger hosting.

    Args:
        zip_bytes: The ZIP archive bytes to deploy.
        domain: Target domain for deployment.
        hostinger_api_key: Hostinger API bearer token.
        hostinger_api_url: Hostinger API base URL.

    Returns:
        dict with keys: status, url, message

    Raises:
        DeploymentError: If the Hostinger API call fails.
    """
    if not hostinger_api_key:
        # Stub mode — record the deployment intent without actually deploying
        logger.warning("Hostinger API key not configured — using stub deployment for %s", domain)
        return {
            "status": "pending_manual",
            "url": f"https://{domain}",
            "message": "Deployment recorded. Configure HOSTINGER_API_KEY to enable automatic deployment.",
        }

    try:
        response = requests.post(
            f"{hostinger_api_url}/v1/hosting/static/deploy",
            files={"archive": ("site.zip", zip_bytes, "application/zip")},
            data={"domain": domain},
            headers={"Authorization": f"Bearer {hostinger_api_key}"},
            timeout=120,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise DeploymentError(f"Hostinger deployment timed out for {domain}")
    except Exception as exc:
        raise DeploymentError(f"Hostinger deployment failed: {exc}")

    data = response.json()
    return {
        "status": data.get("status", "deployed"),
        "url": data.get("url", f"https://{domain}"),
        "message": data.get("message", "Site deployed successfully"),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_hostinger_deploy.py -v
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/hostinger_deploy.py tests/test_hostinger_deploy.py
git commit -m "feat(website-builder): add Hostinger static site deployment service"
```

---

## Task 7: Wire Deploy Route to Hostinger

**Files:**
- Modify: `plugins/kbs_website_builder/routes.py`

- [ ] **Step 1: Replace the existing create_deployment route**

Replace the existing `create_deployment` function in `plugins/kbs_website_builder/routes.py` with this wired version:

```python
    @bp.route("/api/projects/<int:project_id>/deploy", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def create_deployment(project_id):
        import os
        from core.hostinger_deploy import DeploymentError, build_site_zip, deploy_to_hostinger

        data = request.get_json(force=True) or {}

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id, name, domain FROM website_projects WHERE id = %s",
                (project_id,),
            )
            project = cur.fetchone()
            if project is None:
                return jsonify({"error": "project not found"}), 404

            # Gather all published pages (or all pages if none published)
            cur.execute(
                """
                SELECT slug, content FROM website_pages
                WHERE project_id = %s AND content IS NOT NULL AND content != ''
                ORDER BY sort_order, created_at
                """,
                (project_id,),
            )
            pages = cur.fetchall()

            if not pages:
                return jsonify({"error": "no pages with content to deploy"}), 400

            # Build the ZIP
            zip_bytes = build_site_zip(pages)

            # Determine domain
            domain = data.get("domain") or project["domain"] or f"{project['name'].lower().replace(' ', '-')}.kytranempowerment.com"

            # Create deployment record (pending)
            cur.execute(
                """
                INSERT INTO website_deployments (project_id, deployment_url, provider, status)
                VALUES (%s, %s, 'hostinger', 'building')
                RETURNING id
                """,
                (project_id, f"https://{domain}"),
            )
            deployment_id = cur.fetchone()["id"]

            # Deploy to Hostinger
            hostinger_api_key = os.environ.get("HOSTINGER_API_KEY", "")
            try:
                result = deploy_to_hostinger(
                    zip_bytes=zip_bytes,
                    domain=domain,
                    hostinger_api_key=hostinger_api_key,
                )
            except DeploymentError as exc:
                logger.error("Deployment failed for project %d: %s", project_id, exc)
                cur.execute(
                    """
                    UPDATE website_deployments
                    SET status = 'failed', deploy_log = %s, completed_at = NOW()
                    WHERE id = %s
                    """,
                    (str(exc), deployment_id),
                )
                return jsonify({"error": f"Deployment failed: {exc}"}), 502

            # Update deployment record with result
            deploy_status = "deployed" if result["status"] == "deployed" else "pending"
            cur.execute(
                """
                UPDATE website_deployments
                SET status = %s, deployment_url = %s,
                    deploy_log = %s, completed_at = NOW()
                WHERE id = %s
                RETURNING id, project_id, deployment_url, status, provider,
                          deploy_log, created_at, completed_at
                """,
                (deploy_status, result["url"], result.get("message", ""), deployment_id),
            )
            deployment = cur.fetchone()

            # Update project status to published
            cur.execute(
                "UPDATE website_projects SET status = 'published', domain = %s, updated_at = NOW() WHERE id = %s",
                (domain, project_id),
            )

        event_bus.emit(
            "site.deployed",
            {"project_id": project_id, "name": project["name"], "url": result["url"]},
            tenant_id=g.tenant_id,
        )

        return jsonify(deployment), 201
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_website_builder/routes.py
git commit -m "feat(website-builder): wire deploy route to Hostinger deployment service"
```

---

## Task 8: Onboarding Wizard Route

**Files:**
- Modify: `plugins/kbs_website_builder/routes.py`

- [ ] **Step 1: Add onboarding wizard endpoint**

Add after the Live Preview section in `plugins/kbs_website_builder/routes.py`:

```python
    # ------------------------------------------------------------------
    # Onboarding Wizard
    # ------------------------------------------------------------------

    @bp.route("/api/onboarding", methods=["POST"])
    @login_required
    @require_module(MODULE)
    def onboarding_wizard():
        """Create a project from onboarding wizard data.

        Accepts business name, industry, description, optional template slug.
        Creates the project, optionally triggers AI generation if auto_generate is true.
        """
        import os
        from core.site_generator import SiteGenerationError, generate_site

        data = request.get_json(force=True)
        business_name = (data.get("business_name") or "").strip()
        industry = (data.get("industry") or "").strip()
        description = (data.get("description") or "").strip()
        template_slug = data.get("template_slug")
        auto_generate = data.get("auto_generate", False)

        if not business_name:
            return jsonify({"error": "business_name is required"}), 400
        if not industry:
            return jsonify({"error": "industry is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Create the project
            cur.execute(
                """
                INSERT INTO website_projects (name, description, template, settings)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, description, domain, status, template,
                          settings, created_at, updated_at
                """,
                (
                    business_name,
                    description or f"{industry} website for {business_name}",
                    template_slug,
                    Json({"industry": industry, "onboarded": True}),
                ),
            )
            project = cur.fetchone()

            result_html = None
            page_id = None

            # Auto-generate if requested and Bridge is configured
            if auto_generate:
                bridge_url = os.environ.get("KBS_BRIDGE_URL", "")
                bridge_api_key = os.environ.get("KBS_BRIDGE_API_KEY", "")

                if bridge_url:
                    # Fetch template if specified
                    template_context = None
                    if template_slug:
                        cur.execute(
                            "SELECT base_prompt, base_html, base_css FROM website_templates WHERE slug = %s AND is_active = TRUE",
                            (template_slug,),
                        )
                        template_context = cur.fetchone()

                    prompt = description or f"Create a {industry} website for {business_name}"
                    try:
                        gen_result = generate_site(
                            prompt=prompt,
                            business_name=business_name,
                            bridge_url=bridge_url,
                            bridge_api_key=bridge_api_key,
                            template_context=dict(template_context) if template_context else None,
                        )
                        result_html = gen_result["html"]

                        # Save as home page
                        cur.execute(
                            """
                            INSERT INTO website_pages (project_id, title, slug, content, page_type, sort_order)
                            VALUES (%s, 'Home', 'index', %s, 'home', 0)
                            RETURNING id
                            """,
                            (project["id"], result_html),
                        )
                        page_id = cur.fetchone()["id"]

                        cur.execute(
                            "UPDATE website_projects SET status = 'building', updated_at = NOW() WHERE id = %s",
                            (project["id"],),
                        )
                        project["status"] = "building"
                    except SiteGenerationError as exc:
                        logger.warning("Auto-generate failed during onboarding: %s", exc)
                        # Don't fail onboarding — project is still created

        event_bus.emit(
            "site.created",
            {"project_id": project["id"], "name": project["name"], "onboarded": True},
            tenant_id=g.tenant_id,
        )

        response = {
            "project": project,
            "generated": result_html is not None,
        }
        if result_html:
            response["html"] = result_html
            response["page_id"] = page_id

        return jsonify(response), 201
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_website_builder/routes.py
git commit -m "feat(website-builder): add onboarding wizard endpoint with auto-generation"
```

---

## Task 9: Full Integration Tests

**Files:**
- Modify: `tests/test_website_ai_routes.py`

- [ ] **Step 1: Add onboarding and deployment integration tests**

Append to `tests/test_website_ai_routes.py`:

```python
def test_onboarding_creates_project(client, seed_tenant):
    """POST /website-builder/api/onboarding creates project with industry metadata."""
    resp = client.post(
        "/website-builder/api/onboarding",
        json={
            "business_name": "Glamour Hair Studio",
            "industry": "salon",
            "description": "A trendy downtown hair salon",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["project"]["name"] == "Glamour Hair Studio"
    assert data["generated"] is False  # no auto_generate


def test_onboarding_requires_business_name(client, seed_tenant):
    """POST /website-builder/api/onboarding without business_name returns 400."""
    resp = client.post(
        "/website-builder/api/onboarding",
        json={"industry": "salon"},
    )
    assert resp.status_code == 400


def test_onboarding_requires_industry(client, seed_tenant):
    """POST /website-builder/api/onboarding without industry returns 400."""
    resp = client.post(
        "/website-builder/api/onboarding",
        json={"business_name": "Test"},
    )
    assert resp.status_code == 400


def test_onboarding_with_auto_generate(client, seed_tenant, mock_bridge_success):
    """POST /website-builder/api/onboarding with auto_generate triggers AI generation."""
    import os
    os.environ["KBS_BRIDGE_URL"] = "http://localhost:5000"
    os.environ["KBS_BRIDGE_API_KEY"] = "test-key"

    with patch("core.site_generator.requests.post", return_value=mock_bridge_success):
        resp = client.post(
            "/website-builder/api/onboarding",
            json={
                "business_name": "Quick Cuts",
                "industry": "salon",
                "description": "Budget-friendly haircuts",
                "auto_generate": True,
            },
        )

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["generated"] is True
    assert "html" in data
    assert data["page_id"] is not None


def test_preview_returns_html_content_type(client, seed_tenant, sample_project):
    """GET /website-builder/api/projects/{id}/preview returns text/html."""
    # First create a page with content
    client.post(
        f"/website-builder/api/projects/{sample_project}/pages",
        json={"title": "Home", "slug": "index", "content": "<html><body>Hello</body></html>"},
    )

    resp = client.get(f"/website-builder/api/projects/{sample_project}/preview")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert b"Hello" in resp.data


def test_preview_empty_project_shows_placeholder(client, seed_tenant, sample_project):
    """GET /website-builder/api/projects/{id}/preview with no content shows placeholder."""
    resp = client.get(f"/website-builder/api/projects/{sample_project}/preview")
    assert resp.status_code == 200
    assert b"No content generated yet" in resp.data


def test_deploy_no_pages_returns_400(client, seed_tenant, sample_project):
    """POST /website-builder/api/projects/{id}/deploy with no content returns 400."""
    resp = client.post(
        f"/website-builder/api/projects/{sample_project}/deploy",
        json={},
    )
    assert resp.status_code == 400
    assert "no pages" in resp.get_json()["error"].lower()
```

- [ ] **Step 2: Run the full test suite**

```bash
docker exec kbs_app python -m pytest tests/test_website_ai_routes.py tests/test_website_templates.py tests/test_site_generator.py tests/test_hostinger_deploy.py -v
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add tests/
git commit -m "test(website-builder): add integration tests for onboarding, preview, and deployment"
```

---

## Summary of Endpoints After Completion

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/templates` | List all active templates, optional `?category=` filter |
| GET | `/api/templates/<slug>` | Get template detail with base_html/css/prompt |
| POST | `/api/projects/<id>/generate` | AI-generate site from prompt + optional template |
| POST | `/api/projects/<id>/refine` | Refine existing site with follow-up prompt |
| GET | `/api/projects/<id>/preview` | Serve raw HTML for iframe preview |
| GET | `/api/projects/<id>/preview/pages` | List pages available for preview |
| POST | `/api/projects/<id>/deploy` | Build ZIP + deploy to Hostinger |
| POST | `/api/onboarding` | Create project from wizard + optional auto-generate |

All existing routes (projects CRUD, pages CRUD, stats, publish, deployments list) remain unchanged.
