"""
CodeRabbit Module - AI-Powered Code Review & Security
Integration with CodeRabbit for automated code quality checks

Features (Planned):
- Automated PR code reviews
- Security vulnerability scanning
- Code quality analysis
- Best practices enforcement
- Integration with GitHub/GitLab
"""

from flask import Blueprint

coderabbit_bp = Blueprint('coderabbit', __name__, url_prefix='/tools/coderabbit')

from . import routes
