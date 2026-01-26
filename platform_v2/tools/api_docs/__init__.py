"""
API Documentation Module
Provides OpenAPI/Swagger documentation for all A.R.C.H.I.E. API endpoints
"""
from flask import Blueprint

api_docs_bp = Blueprint('api_docs', __name__, url_prefix='/api-docs')

from . import routes
