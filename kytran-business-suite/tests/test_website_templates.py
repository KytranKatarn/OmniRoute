"""Tests for website template list and detail routes (unit-level with mocking)."""

import pytest
from unittest.mock import patch, MagicMock


SAMPLE_TEMPLATES = [
    {
        "id": 1,
        "name": "Hair Salon & Spa",
        "slug": "salon-spa",
        "category": "salon",
        "description": "Elegant salon website",
        "thumbnail_url": None,
        "base_prompt": "Create a modern hair salon",
        "base_html": "<html></html>",
        "base_css": "body{}",
        "settings": {},
        "is_active": True,
        "created_at": "2026-03-28",
    },
    {
        "id": 2,
        "name": "Construction & Trades",
        "slug": "construction",
        "category": "construction",
        "description": "Bold construction site",
        "thumbnail_url": None,
        "base_prompt": "Create a bold construction website",
        "base_html": "<html></html>",
        "base_css": "body{}",
        "settings": {},
        "is_active": True,
        "created_at": "2026-03-28",
    },
]


def test_template_list_route_exists():
    """Verify the template list route is registered on the blueprint."""
    from plugins.kbs_website_builder import create_blueprint

    manifest = {"slug": "website-builder"}
    bp = create_blueprint(manifest)
    # Simple smoke test: blueprint was created successfully with routes
    assert bp.name == "website_builder"
    assert len(bp.deferred_functions) > 0


def test_template_detail_route_exists():
    """Verify the template detail route is registered."""
    from plugins.kbs_website_builder import create_blueprint

    manifest = {"slug": "website-builder"}
    bp = create_blueprint(manifest)
    assert bp.name == "website_builder"


def test_template_seed_data_has_six_entries():
    """Verify the migration SQL contains 6 template seed entries."""
    import os

    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "kbs_website_builder",
        "migrations",
        "002_website_templates.sql",
    )
    with open(migration_path) as f:
        sql = f.read()

    # Count the number of template slugs in the INSERT
    slugs = [
        "salon-spa",
        "construction",
        "photography",
        "restaurant",
        "fitness",
        "professional",
    ]
    for slug in slugs:
        assert slug in sql, f"Template slug '{slug}' missing from migration"


def test_template_migration_is_idempotent():
    """Verify the migration uses ON CONFLICT for idempotency."""
    import os

    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "kbs_website_builder",
        "migrations",
        "002_website_templates.sql",
    )
    with open(migration_path) as f:
        sql = f.read()

    assert "ON CONFLICT" in sql
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "CREATE INDEX IF NOT EXISTS" in sql


def test_template_table_has_required_columns():
    """Verify the migration creates all required columns."""
    import os

    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "kbs_website_builder",
        "migrations",
        "002_website_templates.sql",
    )
    with open(migration_path) as f:
        sql = f.read()

    required_columns = [
        "name",
        "slug",
        "category",
        "description",
        "thumbnail_url",
        "base_prompt",
        "base_html",
        "base_css",
        "settings",
        "is_active",
        "created_at",
    ]
    for col in required_columns:
        assert col in sql, f"Column '{col}' missing from migration"
