from flask import Flask, jsonify


def create_app(config=None):
    """Flask application factory."""
    from core.config import Config

    cfg = config or Config()

    app = Flask(
        __name__,
        template_folder="../shared/templates",
        static_folder="../shared/theme",
        static_url_path="/static/theme",
    )

    app.secret_key = cfg.KBS_SECRET_KEY
    app.config["KBS_PORT"] = cfg.KBS_PORT
    app.config["KBS_DEBUG"] = cfg.KBS_DEBUG
    app.config["KBS_DOMAIN"] = cfg.KBS_DOMAIN
    app.config["KBS_DEFAULT_TIER"] = cfg.KBS_DEFAULT_TIER
    app.config["kbs_config"] = cfg

    # Health endpoint (no auth)
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "product": "Kytran Business Suite"})

    # Auth blueprint
    from core.auth import auth_bp, init_login_manager

    init_login_manager(app)
    app.register_blueprint(auth_bp, url_prefix="/auth")

    # Kytran SSO — "Sign in with Kytran" OAuth
    from core.kytran_auth import KytranAuth
    from core.kytran_auth_routes import kytran_sso_bp

    kytran_auth = KytranAuth()
    kytran_auth.init_app(app)
    app.register_blueprint(kytran_sso_bp)

    # Tenant middleware
    from core.tenant import load_tenant

    app.before_request(load_tenant)

    # Marketplace blueprint
    from core.marketplace import marketplace_bp

    app.register_blueprint(marketplace_bp, url_prefix="/marketplace")

    # Onboarding blueprint
    from core.onboarding import onboarding_bp

    app.register_blueprint(onboarding_bp, url_prefix="/onboarding")

    # Dashboard stats API
    from core.dashboard_stats import dashboard_stats_bp

    app.register_blueprint(dashboard_stats_bp)

    # Admin dashboard
    from core.admin_dashboard import admin_bp

    app.register_blueprint(admin_bp, url_prefix="/admin")

    # Team management
    from core.team_management import team_bp

    app.register_blueprint(team_bp)

    # Landing page (public) — shown to unauthenticated visitors
    @app.route("/landing")
    def landing():
        from flask import render_template
        return render_template("landing.html")

    # Dashboard
    @app.route("/")
    @app.route("/dashboard")
    def dashboard():
        from flask import g, redirect, render_template, url_for
        from flask_login import current_user

        if not current_user.is_authenticated:
            return render_template("landing.html")

        # Get enabled plugins for this tenant
        enabled_plugins = []
        if hasattr(g, "tenant_id") and g.tenant_id:
            from core.tenant import get_enabled_modules

            enabled_slugs = get_enabled_modules()
            plugins = app.extensions.get("kbs_plugins", {})
            for slug, meta in plugins.items():
                if slug in enabled_slugs:
                    manifest = meta.get("manifest", {})
                    enabled_plugins.append(
                        {
                            "slug": slug,
                            "name": meta.get("name", slug),
                            "icon": manifest.get("icon", "box"),
                            "description": manifest.get("description", ""),
                            "url": f"/plugins/{slug}/",
                            "nav_order": manifest.get("nav", {}).get("order", 99),
                        }
                    )
            enabled_plugins.sort(key=lambda p: p["nav_order"])

        return render_template("dashboard.html", plugins=enabled_plugins)

    # Custom domain API
    @app.route("/api/settings/domain", methods=["POST"])
    def connect_custom_domain():
        from flask import g, jsonify as jf, request as req
        from flask_login import current_user as cu

        if not cu.is_authenticated:
            return jf({"error": "authentication required"}), 401

        data = req.get_json() or {}
        domain = data.get("domain", "").strip()
        if not domain:
            return jf({"error": "domain is required"}), 400

        tenant_tier = g.tenant.get("tier", "free")
        if tenant_tier == "free":
            return jf({"error": "Custom domains require a paid plan"}), 402

        try:
            from core.subdomain_manager import provision_custom_domain

            result = provision_custom_domain(domain, g.tenant_id)
            return jf(result)
        except Exception as exc:
            return jf({"error": str(exc)}), 500

    # Settings API (API keys + webhooks)
    from core.settings_api_routes import settings_api_bp

    app.register_blueprint(settings_api_bp)

    # Register plugins
    from core.plugin_loader import register_plugins

    register_plugins(app)

    return app
