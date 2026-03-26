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

    # Tenant middleware
    from core.tenant import load_tenant

    app.before_request(load_tenant)

    # Marketplace blueprint
    from core.marketplace import marketplace_bp

    app.register_blueprint(marketplace_bp, url_prefix="/marketplace")

    # Dashboard
    @app.route("/")
    @app.route("/dashboard")
    def dashboard():
        from flask import redirect, render_template, url_for
        from flask_login import current_user

        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return render_template("dashboard.html")

    # Register plugins
    from core.plugin_loader import register_plugins

    register_plugins(app)

    return app
