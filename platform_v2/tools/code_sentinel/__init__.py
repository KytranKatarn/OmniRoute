"""
Code Sentinel Module - AI-Powered Code Health & Quality Analysis
Local-first code scanning with AI/Ollama and Bridge routing

Features:
- Local code health scanning
- Multi-agent team analysis
- Issue tracking and quality scores
- Bridge routing to specialized agents
"""

from flask import Blueprint

code_sentinel_bp = Blueprint('code_sentinel', __name__, url_prefix='/tools/code_sentinel')

from . import routes
