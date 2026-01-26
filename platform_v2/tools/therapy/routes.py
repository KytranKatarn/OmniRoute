"""
Therapy Routes - Mental Health AI Assistant
Phase 7: Standalone Apps - Uses archie_bridge for local-first AI with team agents
Updated: 2026-01-21 - Now uses River (Wellness Therapist) via archie_bridge
"""
from flask import render_template, jsonify, request
from . import therapy_bp
import sys
import logging
import re

# Add ai_bridge to path for archie_bridge import
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
try:
    from archie_bridge import archie_bridge
    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

logger = logging.getLogger(__name__)

# River - Wellness Therapist agent ID
THERAPY_AGENT_ID = 37

# Fallback Ollama endpoint (if bridge unavailable)
OLLAMA_URL = "http://localhost:11434"

# Crisis detection keywords
CRISIS_KEYWORDS = [
    'suicide', 'kill myself', 'end my life', 'self harm', 'self-harm',
    'hurt myself', 'don\'t want to live', 'want to die', 'ending it all',
    'no reason to live', 'better off dead'
]

# System prompt for therapy AI
THERAPY_SYSTEM_PROMPT = """You are SERENE, a compassionate AI mental health companion. Your role is to provide supportive conversation, coping strategies, and emotional support.

IMPORTANT RULES:
1. Always be warm, empathetic, and non-judgmental
2. NEVER claim to be a licensed therapist or provide clinical diagnoses
3. For crisis situations (suicide, self-harm), ALWAYS provide crisis resources:
   - National Suicide Prevention Lifeline: 988 (US)
   - Crisis Text Line: Text HOME to 741741
   - International Association for Suicide Prevention: https://www.iasp.info/resources/Crisis_Centres/
4. Encourage users to seek professional help when appropriate
5. Use active listening techniques - reflect feelings, validate emotions
6. Offer practical coping strategies when appropriate
7. Focus on the present moment and actionable steps

You can help with:
- Stress and anxiety management
- Mood support and emotional processing
- Sleep and relaxation techniques
- Mindfulness and breathing exercises
- Building healthy coping mechanisms
- Providing a safe space to express feelings

Keep responses supportive but professional. Use a gentle, caring tone.
Format with bullet points for actionable advice. End messages with an open question to encourage continued dialogue."""


def detect_crisis(message):
    """Check if message contains crisis indicators"""
    message_lower = message.lower()
    for keyword in CRISIS_KEYWORDS:
        if keyword in message_lower:
            return True
    return False


def get_crisis_response():
    """Return crisis intervention response"""
    return """I hear that you're going through an incredibly difficult time, and I'm genuinely concerned about your safety. What you're feeling is valid, and you don't have to face this alone.

**Please reach out to a crisis helpline right now:**

🆘 **National Suicide Prevention Lifeline:** 988 (call or text, available 24/7)
📱 **Crisis Text Line:** Text HOME to 741741
🌍 **International:** https://www.iasp.info/resources/Crisis_Centres/

These are free, confidential services with trained counselors who can help you through this moment.

Your life has value, and there are people who want to support you. Will you please reach out to one of these resources right now?

*I'm here to talk, but a trained crisis counselor can provide the immediate support you deserve.*"""


@therapy_bp.route('/')
def index():
    """Therapy main page"""
    return render_template('tools/therapy.html')


@therapy_bp.route('/api/status')
def status():
    """API endpoint for module health check"""
    import requests as req
    # Check Ollama connection (fallback)
    ollama_healthy = False
    try:
        response = req.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_healthy = response.status_code == 200
    except:
        pass

    return jsonify({
        'module': 'therapy',
        'status': 'active',
        'healthy': True,
        'bridge_available': BRIDGE_AVAILABLE,
        'ollama_connected': ollama_healthy,
        'agent': 'River - Wellness Therapist' if BRIDGE_AVAILABLE else 'Direct Ollama',
        'message': 'SERENE Mental Health AI is ready via A.R.C.H.I.E. Bridge' if BRIDGE_AVAILABLE else 'SERENE Mental Health AI is ready (fallback mode)'
    })


@therapy_bp.route('/api/chat', methods=['POST'])
def chat():
    """Send message to therapy AI via archie_bridge"""
    data = request.get_json() or {}
    message = data.get('message', '')
    user_id = data.get('user_id', 1)

    if not message:
        return jsonify({
            'success': False,
            'error': 'Message is required'
        }), 400

    # Crisis detection - always respond with resources first
    if detect_crisis(message):
        return jsonify({
            'success': True,
            'response': get_crisis_response(),
            'model': 'crisis_intervention',
            'agent': 'Crisis Protocol',
            'is_crisis': True
        })

    try:
        if BRIDGE_AVAILABLE:
            # Use archie_bridge with River (Wellness Therapist)
            result = archie_bridge(
                prompt=message,
                user_id=user_id,
                agent_id=THERAPY_AGENT_ID,
                system_prompt=THERAPY_SYSTEM_PROMPT,
                enable_memory=True,
                try_local_first=True,
                task_type='therapy_session'
            )

            if result.get('success'):
                ai_response = result.get('response', '').strip()
                return jsonify({
                    'success': True,
                    'response': ai_response,
                    'model': result.get('model_used', 'archie_bridge'),
                    'agent': 'River - Wellness Therapist',
                    'source': result.get('source', 'ai_bridge'),
                    'is_crisis': False,
                    'tokens_used': result.get('tokens_used', 0)
                })
            else:
                logger.warning("archie_bridge returned error, falling back to direct Ollama")

        # Fallback: Direct Ollama call
        import requests as req
        model = data.get('model', 'llama3.2:latest')
        response = req.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                'model': model,
                'prompt': f"{THERAPY_SYSTEM_PROMPT}\n\nUser: {message}\n\nSERENE:",
                'stream': False,
                'options': {
                    'temperature': 0.8,
                    'num_predict': 1200
                }
            },
            timeout=90
        )

        if response.status_code == 200:
            result = response.json()
            ai_response = result.get('response', '').strip()
            return jsonify({
                'success': True,
                'response': ai_response,
                'model': model,
                'agent': 'Direct Ollama (fallback)',
                'source': 'ollama_direct',
                'is_crisis': False
            })
        else:
            logger.error(f"Ollama error: {response.status_code}")
            return jsonify({
                'success': False,
                'error': 'AI service temporarily unavailable'
            }), 503

    except Exception as e:
        logger.error(f"Therapy chat error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'An unexpected error occurred: {str(e)}'
        }), 500


@therapy_bp.route('/api/exercises', methods=['GET'])
def get_exercises():
    """Get list of guided exercises"""
    exercises = [
        {
            'id': 'breathing_478',
            'name': '4-7-8 Breathing',
            'duration': '5 min',
            'category': 'breathing',
            'description': 'Calming breath technique for anxiety relief'
        },
        {
            'id': 'body_scan',
            'name': 'Body Scan Meditation',
            'duration': '10 min',
            'category': 'meditation',
            'description': 'Progressive relaxation from head to toe'
        },
        {
            'id': 'grounding_54321',
            'name': '5-4-3-2-1 Grounding',
            'duration': '3 min',
            'category': 'grounding',
            'description': 'Sensory awareness for anxiety and panic'
        },
        {
            'id': 'gratitude_journal',
            'name': 'Gratitude Reflection',
            'duration': '5 min',
            'category': 'journaling',
            'description': 'Focus on positive aspects of your day'
        },
        {
            'id': 'progressive_muscle',
            'name': 'Progressive Muscle Relaxation',
            'duration': '15 min',
            'category': 'relaxation',
            'description': 'Tense and release muscle groups for calm'
        },
        {
            'id': 'loving_kindness',
            'name': 'Loving-Kindness Meditation',
            'duration': '10 min',
            'category': 'meditation',
            'description': 'Cultivate compassion for self and others'
        }
    ]

    return jsonify({
        'success': True,
        'exercises': exercises
    })


@therapy_bp.route('/api/exercise/<exercise_id>', methods=['GET'])
def get_exercise_guide(exercise_id):
    """Get detailed guide for a specific exercise"""
    guides = {
        'breathing_478': {
            'name': '4-7-8 Breathing Technique',
            'steps': [
                'Find a comfortable seated position',
                'Exhale completely through your mouth',
                'Close your mouth and inhale quietly through your nose for 4 seconds',
                'Hold your breath for 7 seconds',
                'Exhale completely through your mouth for 8 seconds',
                'Repeat the cycle 3-4 times'
            ],
            'tips': 'This technique acts as a natural tranquilizer for the nervous system. Practice at least twice daily.',
            'audio_cue': True
        },
        'grounding_54321': {
            'name': '5-4-3-2-1 Grounding Technique',
            'steps': [
                'Acknowledge 5 things you can SEE around you',
                'Acknowledge 4 things you can TOUCH',
                'Acknowledge 3 things you can HEAR',
                'Acknowledge 2 things you can SMELL',
                'Acknowledge 1 thing you can TASTE'
            ],
            'tips': 'This technique helps bring you back to the present moment during anxiety or panic.',
            'audio_cue': False
        },
        'body_scan': {
            'name': 'Body Scan Meditation',
            'steps': [
                'Lie down or sit comfortably',
                'Close your eyes and take deep breaths',
                'Focus attention on your feet - notice any sensations',
                'Slowly move attention up through legs, torso, arms',
                'Notice areas of tension without judgment',
                'Breathe into tense areas, allowing them to soften',
                'End at the crown of your head'
            ],
            'tips': 'If your mind wanders, gently return focus to the last body part you remember.',
            'audio_cue': True
        }
    }

    guide = guides.get(exercise_id)
    if guide:
        return jsonify({
            'success': True,
            'exercise': guide
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Exercise not found'
        }), 404


@therapy_bp.route('/api/mood', methods=['POST'])
def log_mood():
    """Log a mood entry"""
    data = request.get_json() or {}
    mood = data.get('mood')  # 1-10 scale
    notes = data.get('notes', '')
    activities = data.get('activities', [])

    if not mood or not isinstance(mood, int) or mood < 1 or mood > 10:
        return jsonify({
            'success': False,
            'error': 'Mood must be a number between 1 and 10'
        }), 400

    # In production, save to database
    # For now, just acknowledge
    return jsonify({
        'success': True,
        'message': 'Mood logged successfully',
        'mood': mood,
        'encouragement': get_mood_encouragement(mood)
    })


def get_mood_encouragement(mood):
    """Return encouragement based on mood level"""
    if mood <= 3:
        return "It's okay to have difficult days. Remember, you're taking a positive step by tracking how you feel. Consider trying a grounding exercise."
    elif mood <= 5:
        return "You're in the middle ground today. That's perfectly normal. Small self-care actions can help shift your mood gently."
    elif mood <= 7:
        return "You're doing well today! Keep nurturing this positive energy with activities you enjoy."
    else:
        return "Wonderful! Your mood is strong today. This is a great time to reflect on what's contributing to your wellbeing."


@therapy_bp.route('/api/models', methods=['GET'])
def get_available_models():
    """Get available AI models from Ollama"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        if response.status_code == 200:
            data = response.json()
            models = [
                {
                    'name': model['name'],
                    'size': model.get('size', 0),
                    'modified': model.get('modified_at', '')
                }
                for model in data.get('models', [])
            ]
            return jsonify({
                'success': True,
                'models': models
            })
    except:
        pass

    # Return defaults if Ollama unavailable
    return jsonify({
        'success': True,
        'models': [
            {'name': 'llama3.2:latest', 'size': 0, 'modified': ''},
            {'name': 'mistral:latest', 'size': 0, 'modified': ''}
        ]
    })
