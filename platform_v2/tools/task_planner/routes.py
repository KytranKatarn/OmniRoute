"""
Task Planner Routes
KytranMotionAI - Local-first, AI-powered task planner and calendar assistant

Features:
- Automatic task scheduling into available calendar slots
- AI prioritization using GPT4All (local LLM)
- Conflict detection and dynamic rescheduling
- Daily and weekly planning summaries
- Google Calendar / CalDAV integration
- Time blocking for deep work
- Dashboard to launch other Kytran tools (Shorts Studio, Stock Bot, etc.)

Architecture:
- Local-first (JSON storage)
- GPT4All for AI scoring
- CalDAV/Google Calendar API sync
- Modular tool ecosystem integration
"""
from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user

task_planner_bp = Blueprint('task_planner', __name__,
                           url_prefix='/tools/task-planner',
                           template_folder='templates')

@task_planner_bp.route('/')
@login_required
def index():
    """Task Planner main page (Coming Soon)"""
    return render_template('coming_soon.html',
                         module_name="Task Planner",
                         module_icon="📅",
                         module_description="KytranMotionAI - AI-powered task scheduler inspired by Motion App. Automatically schedule tasks, detect conflicts, and replan dynamically. Integrates with Google Calendar and serves as your central dashboard for all Kytran tools.")

@task_planner_bp.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'module': 'task_planner',
        'version': '1.0.0',
        'ready': False,
        'message': 'Coming Soon - GPT4All & Calendar integration'
    })

@task_planner_bp.route('/modules')
def get_modules():
    """Get integrated modules launchable from planner"""
    return jsonify({
        'integrated_modules': [
            {'name': 'Shorts Studio', 'icon': '🎥', 'route': '/tools/shorts-studio'},
            {'name': 'Stock Bot', 'icon': '📈', 'route': '/tools/stock-bot'},
            {'name': 'Course Builder', 'icon': '📖', 'route': '/tools/course-builder'},
            {'name': 'Mindset Coach', 'icon': '🪀', 'route': '/tools/mindset-coach'}
        ]
    })
