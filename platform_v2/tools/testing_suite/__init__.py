"""
Testing Suite Module
Automated regression testing with test discovery, execution, and reporting

Features:
- Test discovery across codebase
- Automated regression testing
- Test history and trends
- Integration with sandbox testing
- Performance benchmarking

Status: Operational
Version: 1.0.0
"""

from flask import Blueprint

testing_suite_bp = Blueprint('testing_suite', __name__, url_prefix='/tools/testing-suite')

from . import routes
