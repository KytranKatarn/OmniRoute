"""Kytran News Watch — Real-Time Global Intelligence Dashboard."""

import os

from flask import (
    Flask,
    redirect,
    render_template_string,
    request,
    send_from_directory,
    session,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from auth import auth_bp
from kytran_auth import KytranAuth

LANDING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>KYTRAN NEWS WATCH — Real-Time Global Intelligence</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600;700;900&family=IBM+Plex+Mono:wght@300;400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --kn-cyan: #00e5ff;
      --kn-gold: #fbbf24;
      --kn-green: #10b981;
      --kn-red: #ef4444;
      --kn-purple: #8b5cf6;
      --kn-bg: #0a0a1a;
      --kn-panel: #111827;
      --kn-border: #1f2937;
      --kn-text: #e2e8f0;
      --kn-muted: #64748b;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: var(--kn-bg);
      color: var(--kn-text);
      font-family: 'IBM Plex Mono', monospace;
      font-size: 14px;
      line-height: 1.6;
      min-height: 100vh;
    }

    /* ── NAV ── */
    .kn-nav {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 2rem;
      height: 56px;
      background: #080814;
      border-bottom: 2px solid var(--kn-cyan);
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .kn-nav-brand {
      font-family: 'Orbitron', sans-serif;
      font-size: 13px;
      font-weight: 700;
      color: var(--kn-cyan);
      letter-spacing: 0.15em;
      text-decoration: none;
    }
    .kn-nav-cta {
      font-family: 'Orbitron', sans-serif;
      font-size: 11px;
      font-weight: 600;
      color: var(--kn-bg);
      background: var(--kn-cyan);
      border: none;
      padding: 8px 18px;
      letter-spacing: 0.1em;
      cursor: pointer;
      text-decoration: none;
      clip-path: polygon(8px 0%, 100% 0%, calc(100% - 8px) 100%, 0% 100%);
      transition: background 0.2s, color 0.2s;
    }
    .kn-nav-cta:hover { background: var(--kn-gold); }

    /* ── HERO ── */
    .kn-hero {
      text-align: center;
      padding: 100px 2rem 80px;
      position: relative;
      overflow: hidden;
    }
    .kn-hero::before {
      content: '';
      position: absolute;
      inset: 0;
      background:
        radial-gradient(ellipse 60% 40% at 50% 0%, rgba(0,229,255,0.06) 0%, transparent 70%),
        radial-gradient(ellipse 40% 30% at 80% 80%, rgba(139,92,246,0.05) 0%, transparent 60%);
      pointer-events: none;
    }
    .kn-hero-eyebrow {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 11px;
      letter-spacing: 0.3em;
      color: var(--kn-cyan);
      text-transform: uppercase;
      margin-bottom: 16px;
    }
    .kn-hero-title {
      font-family: 'Orbitron', sans-serif;
      font-size: clamp(28px, 5vw, 52px);
      font-weight: 900;
      letter-spacing: 0.08em;
      line-height: 1.1;
      color: #fff;
      text-shadow: 0 0 40px rgba(0,229,255,0.3);
      margin-bottom: 12px;
    }
    .kn-hero-title span { color: var(--kn-cyan); }
    .kn-hero-subtitle {
      font-size: 15px;
      color: #94a3b8;
      max-width: 600px;
      margin: 0 auto 40px;
      line-height: 1.7;
    }
    .kn-hero-cta {
      display: inline-block;
      font-family: 'Orbitron', sans-serif;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.15em;
      color: var(--kn-bg);
      background: var(--kn-cyan);
      padding: 14px 40px;
      text-decoration: none;
      clip-path: polygon(12px 0%, 100% 0%, calc(100% - 12px) 100%, 0% 100%);
      transition: background 0.2s, box-shadow 0.2s;
      box-shadow: 0 0 24px rgba(0,229,255,0.25);
    }
    .kn-hero-cta:hover {
      background: var(--kn-gold);
      box-shadow: 0 0 32px rgba(251,191,36,0.35);
    }
    .kn-hero-powered {
      margin-top: 20px;
      font-size: 11px;
      color: var(--kn-muted);
      letter-spacing: 0.1em;
    }
    .kn-hero-powered span { color: var(--kn-purple); }

    /* ── DIVIDER ── */
    .kn-divider {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 0 2rem;
      margin: 0 auto;
      max-width: 1100px;
    }
    .kn-divider-line {
      flex: 1;
      height: 1px;
      background: linear-gradient(to right, transparent, var(--kn-border), transparent);
    }
    .kn-divider-label {
      font-family: 'Orbitron', sans-serif;
      font-size: 10px;
      letter-spacing: 0.2em;
      color: var(--kn-muted);
    }

    /* ── FEATURES ── */
    .kn-section {
      padding: 48px 2rem;
      max-width: 1100px;
      margin: 0 auto;
    }
    .kn-section-title {
      font-family: 'Orbitron', sans-serif;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.25em;
      color: var(--kn-cyan);
      text-transform: uppercase;
      margin-bottom: 8px;
    }
    .kn-section-sub {
      font-size: 12px;
      color: var(--kn-muted);
      margin-bottom: 28px;
      letter-spacing: 0.05em;
    }
    .kn-features-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
    }
    .kn-feature-card {
      background: var(--kn-panel);
      border: 1px solid var(--kn-border);
      border-top: 3px solid var(--kn-cyan);
      padding: 24px 20px;
      position: relative;
    }
    .kn-feature-card::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 1px;
      background: linear-gradient(to right, var(--kn-cyan), transparent);
      opacity: 0.4;
    }
    .kn-feature-icon {
      font-size: 24px;
      margin-bottom: 12px;
    }
    .kn-feature-title {
      font-family: 'Orbitron', sans-serif;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.15em;
      color: var(--kn-cyan);
      margin-bottom: 8px;
    }
    .kn-feature-desc {
      font-size: 12px;
      color: var(--kn-muted);
      line-height: 1.6;
    }

    /* ── STATS ── */
    .kn-stats-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
    }
    .kn-stat-card {
      background: var(--kn-panel);
      border: 1px solid var(--kn-border);
      border-top: 3px solid var(--kn-cyan);
      padding: 20px 16px;
      text-align: center;
    }
    .kn-stat-value {
      font-family: 'Orbitron', sans-serif;
      font-size: 26px;
      font-weight: 700;
      color: var(--kn-cyan);
      line-height: 1;
      margin-bottom: 6px;
    }
    .kn-stat-label {
      font-size: 10px;
      letter-spacing: 0.2em;
      color: var(--kn-muted);
      text-transform: uppercase;
    }

    /* ── FOOTER ── */
    .kn-footer {
      text-align: center;
      padding: 40px 2rem;
      border-top: 1px solid var(--kn-border);
      margin-top: 40px;
    }
    .kn-footer-text {
      font-size: 11px;
      color: var(--kn-muted);
      letter-spacing: 0.1em;
    }
    .kn-footer-text a {
      color: var(--kn-cyan);
      text-decoration: none;
    }
    .kn-footer-text a:hover { text-decoration: underline; }

    /* ── CTA BOTTOM ── */
    .kn-cta-section {
      text-align: center;
      padding: 60px 2rem;
    }
    .kn-cta-section .kn-hero-cta {
      margin-bottom: 12px;
    }
    .kn-cta-sub {
      font-size: 11px;
      color: var(--kn-muted);
      letter-spacing: 0.08em;
    }

    /* ── RESPONSIVE ── */
    @media (max-width: 768px) {
      .kn-features-grid { grid-template-columns: 1fr; }
      .kn-stats-grid { grid-template-columns: repeat(2, 1fr); }
      .kn-hero { padding: 60px 1.5rem 50px; }
      .kn-nav { padding: 0 1rem; }
    }
    @media (max-width: 480px) {
      .kn-stats-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <!-- NAV -->
  <nav class="kn-nav">
    <a href="/" class="kn-nav-brand">K.N.W.</a>
    <a href="/auth/kytran/login?next=/dashboard" class="kn-nav-cta">SIGN IN</a>
  </nav>

  <!-- HERO -->
  <section class="kn-hero">
    <div class="kn-hero-eyebrow">KYTRAN EMPOWERMENT INC.</div>
    <h1 class="kn-hero-title">KYTRAN <span>NEWS WATCH</span></h1>
    <p class="kn-hero-subtitle">
      AI-powered global event monitoring across conflicts, disasters, weather,
      cyber threats, and more. Live data from 500+ sources with interactive
      geospatial visualization.
    </p>
    <a href="/auth/kytran/login?next=/dashboard" class="kn-hero-cta">SIGN IN WITH KYTRAN</a>
    <div class="kn-hero-powered">Powered by <span>Kytran Intelligence Engine</span></div>
  </section>

  <!-- DIVIDER -->
  <div class="kn-divider">
    <div class="kn-divider-line"></div>
    <div class="kn-divider-label">REAL-TIME GLOBAL INTELLIGENCE</div>
    <div class="kn-divider-line"></div>
  </div>

  <!-- FEATURES -->
  <section class="kn-section">
    <div class="kn-section-title">CAPABILITIES</div>
    <div class="kn-section-sub">Comprehensive situational awareness powered by AI</div>
    <div class="kn-features-grid">
      <div class="kn-feature-card">
        <div class="kn-feature-icon">&#x1F30D;</div>
        <div class="kn-feature-title">GEOSPATIAL MAP</div>
        <div class="kn-feature-desc">Interactive 3D globe with real-time event plotting, cluster analysis, and regional drill-down.</div>
      </div>
      <div class="kn-feature-card">
        <div class="kn-feature-icon">&#x26A0;</div>
        <div class="kn-feature-title">THREAT DETECTION</div>
        <div class="kn-feature-desc">AI-classified severity levels for conflicts, cyber attacks, natural disasters, and geopolitical events.</div>
      </div>
      <div class="kn-feature-card">
        <div class="kn-feature-icon">&#x1F4E1;</div>
        <div class="kn-feature-title">LIVE FEEDS</div>
        <div class="kn-feature-desc">Aggregated intelligence from 500+ global sources with real-time updates and source verification.</div>
      </div>
      <div class="kn-feature-card">
        <div class="kn-feature-icon">&#x1F50D;</div>
        <div class="kn-feature-title">DEEP ANALYSIS</div>
        <div class="kn-feature-desc">AI-generated summaries, trend analysis, and predictive assessments for emerging situations.</div>
      </div>
      <div class="kn-feature-card">
        <div class="kn-feature-icon">&#x1F6E1;</div>
        <div class="kn-feature-title">ALERT SYSTEM</div>
        <div class="kn-feature-desc">Configurable alerts by region, category, and severity. Push notifications for critical events.</div>
      </div>
      <div class="kn-feature-card">
        <div class="kn-feature-icon">&#x1F4CA;</div>
        <div class="kn-feature-title">ANALYTICS</div>
        <div class="kn-feature-desc">Historical trend data, event correlation, and statistical breakdowns across all monitored categories.</div>
      </div>
    </div>
  </section>

  <!-- DIVIDER -->
  <div class="kn-divider">
    <div class="kn-divider-line"></div>
    <div class="kn-divider-label">PLATFORM METRICS</div>
    <div class="kn-divider-line"></div>
  </div>

  <!-- STATS -->
  <section class="kn-section">
    <div class="kn-stats-grid">
      <div class="kn-stat-card">
        <div class="kn-stat-value">500+</div>
        <div class="kn-stat-label">DATA SOURCES</div>
      </div>
      <div class="kn-stat-card">
        <div class="kn-stat-value">24/7</div>
        <div class="kn-stat-label">MONITORING</div>
      </div>
      <div class="kn-stat-card">
        <div class="kn-stat-value">8</div>
        <div class="kn-stat-label">EVENT CATEGORIES</div>
      </div>
      <div class="kn-stat-card">
        <div class="kn-stat-value">&lt;30s</div>
        <div class="kn-stat-label">UPDATE LATENCY</div>
      </div>
    </div>
  </section>

  <!-- CTA BOTTOM -->
  <section class="kn-cta-section">
    <a href="/auth/kytran/login?next=/dashboard" class="kn-hero-cta">ACCESS THE DASHBOARD</a>
    <div class="kn-cta-sub">Sign in with your Kytran account to access real-time intelligence</div>
  </section>

  <!-- FOOTER -->
  <footer class="kn-footer">
    <div class="kn-footer-text">
      Powered by <a href="https://kytranempowerment.com">Kytran Intelligence Engine</a>
      &nbsp;&middot;&nbsp; &copy; 2026 Kytran Empowerment Inc.
    </div>
  </footer>
</body>
</html>
"""


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    # --- Proxy Fix (behind Caddy) ---
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # --- Session & Security Config ---
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = (
        os.environ.get("SESSION_COOKIE_SECURE", "true").lower() in ("true", "1")
    )

    # --- KytranAuth SSO ---
    kytran_auth = KytranAuth()
    app.config["KYTRAN_CLIENT_ID"] = os.environ.get("KYTRAN_CLIENT_ID", "news-watch")
    kytran_auth.init_app(app)

    # --- Auth Blueprint ---
    app.register_blueprint(auth_bp)

    # --- CORS (locked down) ---
    allowed_origins = os.environ.get(
        "CORS_ORIGINS", "https://thenews.kytranempowerment.com"
    ).split(",")

    @app.after_request
    def add_cors(response):
        origin = request.headers.get("Origin", "")
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST"
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

    # --- Landing Page (public) ---
    @app.route("/")
    def index():
        if "kytran_user" in session:
            return redirect("/dashboard")
        return render_template_string(LANDING_HTML)

    # --- Dashboard: serve the news PWA (auth required) ---
    @app.route("/dashboard")
    @kytran_auth.login_required
    def dashboard():
        return send_from_directory("news_app", "index.html")

    @app.route("/dashboard/<path:filename>")
    @kytran_auth.login_required
    def dashboard_files(filename):
        return send_from_directory("news_app", filename)

    # Serve news app sub-directories behind auth
    @app.route("/js/<path:filename>")
    @kytran_auth.login_required
    def serve_js(filename):
        return send_from_directory("news_app/js", filename)

    @app.route("/css/<path:filename>")
    @kytran_auth.login_required
    def serve_css(filename):
        return send_from_directory("news_app/css", filename)

    @app.route("/data/<path:filename>")
    @kytran_auth.login_required
    def serve_data(filename):
        return send_from_directory("news_app/data", filename)

    @app.route("/images/<path:filename>")
    @kytran_auth.login_required
    def serve_images(filename):
        return send_from_directory("news_app/images", filename)

    @app.route("/icons/<path:filename>")
    @kytran_auth.login_required
    def serve_icons(filename):
        return send_from_directory("news_app/icons", filename)

    # --- Health endpoint ---
    @app.route("/api/health")
    def health():
        return {"status": "ok", "service": "kytran-news-watch", "version": "1.0.0"}

    # --- Logout ---
    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=8080, debug=False)
