"""
SaaS Manager Module
===================
Multi-tenant organization management, domain routing, and module provisioning.

API Routes (at /tools/saas-manager/...):
- /orgs GET - List organizations
- /orgs POST - Create organization
- /orgs/<id> GET - Organization details
- /orgs/<id>/modules POST - Enable/disable modules
- /orgs/<id>/domains POST - Add domain
- /network/public-ip GET - Public IP status
- /dashboard GET - SaaS overview dashboard
"""

from .saas_manager_routes import saas_manager_bp  # noqa: F401
