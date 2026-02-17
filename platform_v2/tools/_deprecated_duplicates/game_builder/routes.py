"""
Game Builder Routes (Placeholder)
"""

from flask import render_template_string, jsonify
from . import game_builder_bp

COMING_SOON_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Game Builder - Coming Soon</title>
    <style>
        body { background: #000; color: #00FF00; font-family: monospace; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .container { text-align: center; border: 2px solid #00FF00; padding: 60px; max-width: 600px; }
        h1 { font-size: 3rem; margin-bottom: 20px; }
        .icon { font-size: 5rem; margin-bottom: 20px; }
        p { opacity: 0.7; line-height: 1.8; }
        .status { color: #FFA500; margin-top: 30px; padding: 10px; border: 1px solid #FFA500; display: inline-block; }
        a { color: #00FF00; }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">🎮</div>
        <h1>GAME BUILDER</h1>
        <p>Build games with AI-powered tools<br>Mission editor • Asset manager • Enemy AI designer</p>
        <div class="status">⚠️ COMING SOON</div>
        <p style="margin-top: 30px;"><a href="/dashboard">← Back to Dashboard</a></p>
    </div>
</body>
</html>
"""


@game_builder_bp.route("/")
def index():
    return render_template_string(COMING_SOON_HTML)


@game_builder_bp.route("/api/status")
def status():
    return jsonify(
        {
            "module": "game_builder",
            "status": "coming_soon",
            "healthy": False,
            "message": "Module not yet implemented",
        }
    )
