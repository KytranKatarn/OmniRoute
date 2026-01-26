"""
AI Model Fine-tuning Module
Phase 46: Custom AI model training interface
"""
from flask import Blueprint

fine_tuning_bp = Blueprint('fine_tuning', __name__, url_prefix='/tools/fine-tuning')

from . import routes
