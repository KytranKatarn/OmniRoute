"""
Website Studio Module
=====================
AI-assisted website building with deployment capabilities.

Features:
- Create and manage website projects
- AI-powered design suggestions and content generation
- GitHub Pages, Vercel, Netlify deployment
- Custom domain configuration
- Per-user integrations (GitHub, Cloudflare, etc.)

Author: A.R.C.H.I.E. Platform
Date: 2026-01-12
"""

from .routes import website_studio_bp

__all__ = ['website_studio_bp']
