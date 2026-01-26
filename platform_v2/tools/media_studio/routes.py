"""
Media Studio Routes
Create images, videos & shorts with AI
Phase 5: Module Consolidation - CREATION Category
Phase 51: Local-First Image Generation (Fooocus) + Vision Analysis

Integrated with archie_bridge for:
- LOCAL image generation (Fooocus - FREE)
- DALL-E 3 fallback (paid)
- Vision/image analysis (minicpm-v, llava - FREE)
- Usage tracking and cost logging
- Learning from generation patterns
"""
from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from . import media_studio_bp
import sys
import os

# Add ai_bridge to path
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
try:
    from archie_bridge import (
        generate_image as bridge_generate_image,
        generate_image_local as bridge_generate_image_local,
        generate_image_smart as bridge_generate_image_smart,
        analyze_image as bridge_analyze_image,
        enhance_image_prompt as bridge_enhance_prompt,
        check_fooocus_health
    )
    BRIDGE_AVAILABLE = True
except ImportError as e:
    BRIDGE_AVAILABLE = False
    print(f"Warning: archie_bridge not fully available: {e}")
    # Fallback stubs
    def check_fooocus_health():
        return False


@media_studio_bp.route('/')
def index():
    """Media Studio main page"""
    return render_template('tools/media_studio.html')


@media_studio_bp.route('/api/status')
def status():
    """API endpoint for module health check"""
    fooocus_status = check_fooocus_health() if BRIDGE_AVAILABLE else False

    return jsonify({
        'module': 'media_studio',
        'status': 'active',
        'healthy': True,
        'message': 'Media Studio is operational',
        'capabilities': {
            'local_image_generation': fooocus_status,
            'cloud_image_generation': True,
            'vision_analysis': True
        }
    })


@media_studio_bp.route('/api/media', methods=['GET'])
def get_media():
    """Get all media items (placeholder - will connect to database)"""
    return jsonify({
        'success': True,
        'media': [],
        'message': 'Media storage coming soon'
    })


@media_studio_bp.route('/api/media', methods=['POST'])
def upload_media():
    """Upload media file (placeholder)"""
    return jsonify({
        'success': True,
        'message': 'File upload coming soon'
    })


@media_studio_bp.route('/api/generate', methods=['POST'])
@login_required
def generate_image():
    """
    Generate image using AI - LOCAL FIRST routing.

    Supports three modes:
    - 'auto': Smart routing (local first, DALL-E fallback)
    - 'fooocus': Force local Fooocus generation
    - 'dall-e-3': Force DALL-E 3 (paid)

    Request body:
        prompt: Text description of image
        model: 'auto' (default), 'fooocus', or 'dall-e-3'
        style: 'realistic', 'anime', 'artistic', 'cinematic', 'digital-art'
        size: '1024x1024', '1024x1792', '1792x1024'
        quality: 'standard' (default) or 'hd'
        enhance_prompt: boolean - use AI to enhance prompt (default: false)
        prefer_local: boolean - prefer free local generation (default: true)
        agent_id: Optional agent ID for attribution
        task_type: Optional task categorization (default: 'image_generation')
    """
    data = request.get_json() or {}
    prompt = data.get('prompt', '')
    model = data.get('model', 'auto')
    style = data.get('style', 'realistic')
    size = data.get('size', '1024x1024')
    quality = data.get('quality', 'standard')
    enhance = data.get('enhance_prompt', False)
    prefer_local = data.get('prefer_local', True)
    agent_id = data.get('agent_id')
    task_type = data.get('task_type', 'image_generation')

    if not prompt:
        return jsonify({
            'success': False,
            'error': 'Prompt is required'
        }), 400

    if not BRIDGE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Image generation service not available. archie_bridge not loaded.'
        }), 503

    # Optionally enhance the prompt using AI
    original_prompt = prompt
    if enhance:
        try:
            prompt = bridge_enhance_prompt(prompt, style)
        except Exception as e:
            print(f"Warning: Prompt enhancement failed: {e}")
            # Continue with original prompt

    # Route based on model selection
    if model == 'auto':
        # Smart routing: local first, DALL-E fallback
        result = bridge_generate_image_smart(
            prompt=prompt,
            style=style,
            size=size,
            quality=quality,
            prefer_local=prefer_local,
            requesting_agent=agent_id,
            task_type=task_type
        )
    elif model == 'fooocus':
        # Force local Fooocus
        result = bridge_generate_image_local(
            prompt=prompt,
            style=style,
            size=size,
            requesting_agent=agent_id,
            task_type=task_type
        )
    else:
        # DALL-E or other paid models
        # Map style to DALL-E style parameter
        dalle_style = 'vivid' if style in ['anime', 'artistic', 'digital-art'] else 'natural'
        result = bridge_generate_image(
            prompt=prompt,
            model=model,
            size=size,
            quality=quality,
            style=dalle_style,
            requesting_agent=agent_id,
            task_type=task_type
        )

    if result.get('success'):
        response = {
            'success': True,
            'image_url': result.get('image_url'),
            'model': result.get('model'),
            'provider': result.get('provider'),
            'cost': result.get('cost', 0.0),
            'duration_ms': result.get('duration_ms'),
            'metadata': result.get('metadata', {}),
        }

        # Include routing info if available
        if 'routing' in result:
            response['routing'] = result['routing']

        # Include prompt info if enhanced
        if enhance:
            response['original_prompt'] = original_prompt
            response['enhanced_prompt'] = prompt

        # Include revised prompt from DALL-E if available
        if result.get('revised_prompt'):
            response['revised_prompt'] = result['revised_prompt']

        return jsonify(response)
    else:
        return jsonify({
            'success': False,
            'error': result.get('error', 'Image generation failed'),
            'model': result.get('model'),
            'provider': result.get('provider')
        }), 500


@media_studio_bp.route('/api/analyze', methods=['POST'])
@login_required
def analyze_image():
    """
    Analyze image using local vision model (FREE).

    Request body:
        image_url: URL to fetch image from
        image_base64: Base64 encoded image data
        prompt: Analysis instruction (default: "Describe this image in detail")
        model: Vision model ('minicpm-v:8b', 'llava:7b')
    """
    data = request.get_json() or {}
    image_url = data.get('image_url')
    image_base64 = data.get('image_base64')
    prompt = data.get('prompt', 'Describe this image in detail')
    model = data.get('model')  # None = use default from env

    if not image_url and not image_base64:
        return jsonify({
            'success': False,
            'error': 'Image required. Provide image_url or image_base64'
        }), 400

    if not BRIDGE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Vision analysis service not available.'
        }), 503

    result = bridge_analyze_image(
        image_url=image_url,
        image_base64=image_base64,
        prompt=prompt,
        model=model
    )

    if result.get('success'):
        return jsonify({
            'success': True,
            'analysis': result.get('response'),
            'model': result.get('model'),
            'provider': result.get('provider'),
            'cost': result.get('cost', 0.0),
            'duration_ms': result.get('duration_ms')
        })
    else:
        return jsonify({
            'success': False,
            'error': result.get('error', 'Vision analysis failed'),
            'model': result.get('model')
        }), 500


@media_studio_bp.route('/api/enhance-prompt', methods=['POST'])
@login_required
def enhance_prompt():
    """
    Enhance a basic prompt for better image generation (FREE).

    Request body:
        prompt: Basic description
        style: Target style ('realistic', 'anime', 'artistic', 'cinematic', 'digital-art')
    """
    data = request.get_json() or {}
    prompt = data.get('prompt', '')
    style = data.get('style', 'realistic')

    if not prompt:
        return jsonify({
            'success': False,
            'error': 'Prompt is required'
        }), 400

    if not BRIDGE_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Prompt enhancement service not available.'
        }), 503

    enhanced = bridge_enhance_prompt(prompt, style)

    return jsonify({
        'success': True,
        'original_prompt': prompt,
        'enhanced_prompt': enhanced,
        'style': style
    })


@media_studio_bp.route('/api/shorts', methods=['POST'])
def create_short():
    """Create a short video (placeholder)"""
    data = request.get_json() or {}
    script = data.get('script', '')
    platform = data.get('platform', 'tiktok')
    duration = data.get('duration', 60)
    style = data.get('style', 'talking-head')

    if not script:
        return jsonify({
            'success': False,
            'error': 'Script is required'
        }), 400

    # TODO: Implement shorts creation
    return jsonify({
        'success': True,
        'message': 'Shorts creator coming soon',
        'request': {
            'script': script,
            'platform': platform,
            'duration': duration,
            'style': style
        }
    })


@media_studio_bp.route('/api/models', methods=['GET'])
def get_available_models():
    """Get available AI models for image generation and vision analysis"""

    # Check Fooocus availability
    fooocus_available = check_fooocus_health() if BRIDGE_AVAILABLE else False

    image_models = [
        {
            'id': 'auto',
            'name': 'Smart (Local First)',
            'provider': 'Auto',
            'available': True,
            'cost': 'FREE first, paid fallback',
            'description': 'Tries local Fooocus first, falls back to DALL-E if unavailable'
        },
        {
            'id': 'fooocus',
            'name': 'Fooocus (Local)',
            'provider': 'Local SDXL',
            'available': fooocus_available,
            'cost': 'FREE',
            'description': 'Local Stable Diffusion XL - fast, private, no cost'
        },
        {
            'id': 'dall-e-3',
            'name': 'DALL-E 3',
            'provider': 'OpenAI',
            'available': True,
            'cost': '$0.04-$0.12/image',
            'description': 'High quality, best prompt understanding'
        },
        {
            'id': 'dall-e-2',
            'name': 'DALL-E 2',
            'provider': 'OpenAI',
            'available': True,
            'cost': '$0.016-$0.02/image',
            'description': 'Lower cost, simpler generations'
        }
    ]

    vision_models = [
        {
            'id': 'minicpm-v:8b',
            'name': 'MiniCPM-V 2.6',
            'provider': 'Ollama (Local)',
            'available': True,
            'cost': 'FREE',
            'description': 'Best for OCR, multi-image understanding'
        },
        {
            'id': 'llava:7b',
            'name': 'LLaVA 7B',
            'provider': 'Ollama (Local)',
            'available': True,
            'cost': 'FREE',
            'description': 'General vision tasks, lightweight'
        }
    ]

    styles = [
        {'id': 'realistic', 'name': 'Realistic / Photograph', 'description': 'Photorealistic images'},
        {'id': 'anime', 'name': 'Anime', 'description': 'Japanese animation style'},
        {'id': 'artistic', 'name': 'Artistic', 'description': 'Painterly, fine art style'},
        {'id': 'cinematic', 'name': 'Cinematic', 'description': 'Movie-like, dramatic lighting'},
        {'id': 'digital-art', 'name': 'Digital Art', 'description': 'Sharp, trending on artstation'}
    ]

    return jsonify({
        'success': True,
        'image_models': image_models,
        'vision_models': vision_models,
        'styles': styles,
        'fooocus_status': 'online' if fooocus_available else 'offline',
        'default_model': 'auto',
        'default_style': 'realistic'
    })
