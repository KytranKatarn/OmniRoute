"""
Website Studio AI Assistant
===========================
AI-powered assistance for website design and content generation.
Uses the ARCHIE AI Bridge for intelligent suggestions.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-12
"""

import os
import sys
import json
from typing import Optional, Dict, List

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from ai_bridge.archie_bridge import archie_bridge
    from ai_bridge.knowledge_retrieval import get_relevant_knowledge

    AI_BRIDGE_AVAILABLE = True
except ImportError as e:
    AI_BRIDGE_AVAILABLE = False
    print(f"[WebsiteStudio] AI Bridge not available: {e}")


def suggest_website_design(description: str, website_type: str = None, user_id: int = None) -> Dict:
    """
    Use AI to suggest website design based on user description.

    Args:
        description: What the user wants their website to be
        website_type: Type of website (business, portfolio, blog, store, etc.)
        user_id: User ID for personalization

    Returns:
        Dict with suggested design, structure, and features
    """
    if not AI_BRIDGE_AVAILABLE:
        return {
            "success": False,
            "error": "AI Bridge not available",
            "fallback": get_fallback_suggestions(website_type),
        }

    try:
        # Get relevant knowledge for context
        context = get_relevant_knowledge(f"website design {description} {website_type or ''}", limit=5)

        prompt = f"""You are a web design expert. A user wants to create a website:

Description: {description}
Website Type: {website_type or 'general'}

Based on this, provide a JSON response with:
1. "suggested_pages": Array of recommended pages (e.g., ["Home", "About", "Services", "Contact"])
2. "design_style": Recommended style (e.g., "modern minimalist", "bold creative", "professional corporate")
3. "color_scheme": Suggested colors with purpose (e.g., {{"primary": "#2563eb", "secondary": "#1e40af", "accent": "#f59e0b"}})
4. "key_features": Array of features to include (e.g., ["contact form", "image gallery", "testimonials"])
5. "layout_type": Recommended layout ("single-page", "multi-page", "landing-page")
6. "content_sections": For each page, key sections to include

Respond ONLY with valid JSON, no markdown or explanation."""

        result = archie_bridge(prompt, context=context, user_id=user_id, enable_memory=False)
        response = result.get("response", "") if result.get("success") else ""

        # Try to parse JSON from response
        try:
            # Clean response if needed
            json_str = response.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]

            suggestions = json.loads(json_str)
            return {"success": True, "suggestions": suggestions}
        except json.JSONDecodeError:
            return {
                "success": True,
                "suggestions": {
                    "raw_response": response,
                    "fallback": get_fallback_suggestions(website_type),
                },
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "fallback": get_fallback_suggestions(website_type),
        }


def generate_page_content(
    page_name: str,
    website_description: str,
    business_name: str = None,
    tone: str = "professional",
) -> Dict:
    """
    Generate content for a specific page.

    Args:
        page_name: Name of the page (e.g., "About", "Services")
        website_description: Overall website description
        business_name: Name of the business/project
        tone: Content tone (professional, friendly, creative, formal)

    Returns:
        Dict with generated content sections
    """
    if not AI_BRIDGE_AVAILABLE:
        return {"success": False, "error": "AI Bridge not available"}

    try:
        prompt = f"""Generate website content for a "{page_name}" page.

Website: {website_description}
Business/Project Name: {business_name or 'Not specified'}
Tone: {tone}

Provide JSON with:
1. "headline": Main headline for the page
2. "subheadline": Supporting subheadline
3. "sections": Array of content sections, each with "title" and "content"
4. "cta": Call-to-action text and button label

Keep content concise and engaging. Respond ONLY with valid JSON."""

        result = archie_bridge(prompt, enable_memory=False)
        response = result.get("response", "") if result.get("success") else ""

        try:
            json_str = response.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]

            content = json.loads(json_str)
            return {"success": True, "content": content}
        except json.JSONDecodeError:
            return {"success": True, "content": {"raw_response": response}}

    except Exception as e:
        return {"success": False, "error": str(e)}


def improve_seo(title: str, description: str, content: str, keywords: List[str] = None) -> Dict:
    """
    Get SEO improvement suggestions.

    Args:
        title: Current page title
        description: Current meta description
        content: Page content
        keywords: Target keywords

    Returns:
        Dict with SEO recommendations
    """
    if not AI_BRIDGE_AVAILABLE:
        return {"success": False, "error": "AI Bridge not available"}

    try:
        prompt = f"""Analyze and improve SEO for this page:

Current Title: {title}
Meta Description: {description}
Target Keywords: {', '.join(keywords) if keywords else 'Not specified'}
Content Preview: {content[:500]}...

Provide JSON with:
1. "improved_title": Better SEO-optimized title (max 60 chars)
2. "improved_description": Better meta description (max 160 chars)
3. "suggested_keywords": Array of relevant keywords
4. "heading_suggestions": Recommendations for H1, H2 structure
5. "content_recommendations": Array of tips to improve content SEO
6. "seo_score": Estimated SEO score (0-100)

Respond ONLY with valid JSON."""

        result = archie_bridge(prompt, enable_memory=False)
        response = result.get("response", "") if result.get("success") else ""

        try:
            json_str = response.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]

            seo = json.loads(json_str)
            return {"success": True, "seo": seo}
        except json.JSONDecodeError:
            return {"success": True, "seo": {"raw_response": response}}

    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_css_styles(design_style: str, color_scheme: Dict = None, components: List[str] = None) -> Dict:
    """
    Generate CSS styles based on design preferences.

    Args:
        design_style: Style description (e.g., "modern minimalist")
        color_scheme: Color palette dict
        components: List of components to style

    Returns:
        Dict with CSS code
    """
    if not AI_BRIDGE_AVAILABLE:
        return {
            "success": False,
            "error": "AI Bridge not available",
            "fallback_css": get_fallback_css(design_style),
        }

    try:
        prompt = f"""Generate modern CSS for a website with:

Design Style: {design_style}
Color Scheme: {json.dumps(color_scheme) if color_scheme else 'Use modern defaults'}
Components: {', '.join(components) if components else 'header, nav, hero, sections, footer'}

Provide clean, modern CSS with:
- CSS custom properties (variables) for colors
- Responsive design (mobile-first)
- Smooth transitions
- Modern typography

Return JSON with:
1. "css_variables": CSS custom properties
2. "base_styles": Reset and base styles
3. "component_styles": Styles for each component
4. "responsive_styles": Media queries

Respond ONLY with valid JSON containing CSS code strings."""

        result = archie_bridge(prompt, enable_memory=False)
        response = result.get("response", "") if result.get("success") else ""

        try:
            json_str = response.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]

            styles = json.loads(json_str)
            return {"success": True, "styles": styles}
        except json.JSONDecodeError:
            return {"success": True, "styles": {"raw_response": response}}

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "fallback_css": get_fallback_css(design_style),
        }


# ============================================================================
# FALLBACK SUGGESTIONS (when AI is unavailable)
# ============================================================================


def get_fallback_suggestions(website_type: str = None) -> Dict:
    """Get fallback suggestions when AI is unavailable"""

    templates = {
        "business": {
            "suggested_pages": ["Home", "About", "Services", "Contact"],
            "design_style": "professional corporate",
            "color_scheme": {
                "primary": "#2563eb",
                "secondary": "#1e40af",
                "accent": "#f59e0b",
            },
            "key_features": [
                "contact form",
                "services showcase",
                "testimonials",
                "team section",
            ],
            "layout_type": "multi-page",
        },
        "portfolio": {
            "suggested_pages": ["Home", "Work", "About", "Contact"],
            "design_style": "modern minimalist",
            "color_scheme": {
                "primary": "#18181b",
                "secondary": "#3f3f46",
                "accent": "#a855f7",
            },
            "key_features": [
                "project gallery",
                "case studies",
                "skills showcase",
                "resume download",
            ],
            "layout_type": "single-page",
        },
        "blog": {
            "suggested_pages": ["Home", "Blog", "Categories", "About", "Contact"],
            "design_style": "clean readable",
            "color_scheme": {
                "primary": "#0f172a",
                "secondary": "#334155",
                "accent": "#0ea5e9",
            },
            "key_features": [
                "post archive",
                "categories",
                "search",
                "newsletter signup",
            ],
            "layout_type": "multi-page",
        },
        "store": {
            "suggested_pages": ["Home", "Products", "Cart", "About", "Contact"],
            "design_style": "modern ecommerce",
            "color_scheme": {
                "primary": "#0d9488",
                "secondary": "#115e59",
                "accent": "#f97316",
            },
            "key_features": [
                "product catalog",
                "shopping cart",
                "checkout",
                "customer reviews",
            ],
            "layout_type": "multi-page",
        },
        "landing": {
            "suggested_pages": ["Home"],
            "design_style": "bold conversion-focused",
            "color_scheme": {
                "primary": "#7c3aed",
                "secondary": "#5b21b6",
                "accent": "#fbbf24",
            },
            "key_features": [
                "hero section",
                "features grid",
                "testimonials",
                "pricing",
                "CTA",
            ],
            "layout_type": "landing-page",
        },
    }

    return templates.get(website_type, templates["business"])


def get_fallback_css(design_style: str = None) -> str:
    """Get fallback CSS when AI is unavailable"""
    return """
:root {
    --color-primary: #2563eb;
    --color-secondary: #1e40af;
    --color-accent: #f59e0b;
    --color-bg: #ffffff;
    --color-text: #1f2937;
    --color-muted: #6b7280;
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
    --shadow-md: 0 4px 6px rgba(0,0,0,0.1);
    --radius: 0.5rem;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: var(--font-sans);
    color: var(--color-text);
    background: var(--color-bg);
    line-height: 1.6;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 1rem;
}

header {
    background: var(--color-bg);
    box-shadow: var(--shadow-sm);
    position: sticky;
    top: 0;
    z-index: 100;
}

nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 0;
}

.hero {
    padding: 4rem 0;
    text-align: center;
}

.hero h1 {
    font-size: 3rem;
    font-weight: 700;
    margin-bottom: 1rem;
}

.btn {
    display: inline-block;
    padding: 0.75rem 1.5rem;
    background: var(--color-primary);
    color: white;
    border-radius: var(--radius);
    text-decoration: none;
    transition: background 0.2s;
}

.btn:hover {
    background: var(--color-secondary);
}

section {
    padding: 4rem 0;
}

footer {
    background: var(--color-text);
    color: white;
    padding: 2rem 0;
    text-align: center;
}

@media (max-width: 768px) {
    .hero h1 {
        font-size: 2rem;
    }
}
"""
