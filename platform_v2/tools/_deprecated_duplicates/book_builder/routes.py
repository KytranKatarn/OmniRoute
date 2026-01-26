"""
Book Builder Routes
Create and publish books with AI assistance
"""
from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user

book_builder_bp = Blueprint('book_builder', __name__,
                           url_prefix='/tools/book-builder',
                           template_folder='templates')

@book_builder_bp.route('/')
@login_required
def index():
    """Book Builder main page (Coming Soon)"""
    return render_template('coming_soon.html',
                         module_name="Book Builder",
                         module_icon="📚",
                         module_description="Create and publish books with AI assistance. Write novels, technical books, guides, and more.")

@book_builder_bp.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'module': 'book_builder',
        'version': '0.1.0',
        'ready': False,
        'message': 'Coming Soon'
    })
