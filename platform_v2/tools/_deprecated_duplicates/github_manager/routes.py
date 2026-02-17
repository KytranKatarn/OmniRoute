"""GitHub Manager Routes (Placeholder)"""

from flask import render_template_string, jsonify
from . import github_manager_bp

HTML = """
<!DOCTYPE html>
<html>
<head><title>GitHub Manager - Coming Soon</title>
<style>body{background:#000;color:#00FF00;font-family:monospace;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}.container{text-align:center;border:2px solid #00FF00;padding:60px;max-width:600px}h1{font-size:2.5rem;margin-bottom:20px}.icon{font-size:5rem;margin-bottom:20px}p{opacity:0.7;line-height:1.8}.status{color:#FFA500;margin-top:30px;padding:10px;border:1px solid #FFA500;display:inline-block}a{color:#00FF00}</style>
</head>
<body><div class="container"><div class="icon">📦</div><h1>GITHUB MANAGER</h1><p>Repository management UI<br>Issues • PRs • Actions • Branches</p><div class="status">⚠️ COMING SOON</div><p style="margin-top:30px"><a href="/dashboard">← Back to Dashboard</a></p></div></body>
</html>"""


@github_manager_bp.route("/")
def index():
    return render_template_string(HTML)


@github_manager_bp.route("/api/status")
def status():
    return jsonify(
        {
            "module": "github_manager",
            "status": "coming_soon",
            "healthy": False,
            "message": "Module not yet implemented",
        }
    )
