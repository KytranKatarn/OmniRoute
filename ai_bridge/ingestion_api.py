"""
A.R.C.H.I.E. Bridge Conversation Ingestion API
HTTP endpoint to receive conversations from ANY source

Usage:
    POST /api/ingest/conversation
    {
        "user_message": "How do I...",
        "ai_response": "You can...",
        "source": "claude_code",  # or "chat", "api", "ollama", etc.
        "model": "claude-sonnet-4",
        "provider": "anthropic",
        "user_id": 1,  # optional
        "metadata": {}  # optional
    }

This allows:
- Claude Code CLI sessions to be captured
- Chat conversations to be stored
- API calls to be logged
- Local LLM conversations to be remembered
"""
from flask import Flask, request, jsonify
from conversation_ingest import ingest_conversation, retrieve_similar_conversations, get_archie_personality

app = Flask(__name__)

@app.route('/api/ingest/conversation', methods=['POST'])
def ingest_conversation_endpoint():
    """
    Ingest a conversation into A.R.C.H.I.E.'s consciousness

    POST /api/ingest/conversation
    {
        "user_message": str (required),
        "ai_response": str (required),
        "source": str (optional, default="unknown"),
        "model": str (optional),
        "provider": str (optional),
        "user_id": int (optional),
        "metadata": dict (optional)
    }

    Returns:
        {
            "success": bool,
            "memory_id": int,
            "tags_applied": List[str],
            "sentiment": Dict,
            "trust_impact": Dict,
            "personality_update": Dict
        }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'No JSON data provided'
            }), 400

        # Validate required fields
        if 'user_message' not in data or 'ai_response' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required fields: user_message, ai_response'
            }), 400

        # Ingest conversation
        result = ingest_conversation(
            user_message=data['user_message'],
            ai_response=data['ai_response'],
            user_id=data.get('user_id'),
            source=data.get('source', 'unknown'),
            model=data.get('model'),
            provider=data.get('provider'),
            metadata=data.get('metadata')
        )

        return jsonify(result), 200 if result.get('success') else 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/retrieve/similar', methods=['POST'])
def retrieve_similar_endpoint():
    """
    Retrieve similar conversations from consciousness (RAG retrieval)

    POST /api/retrieve/similar
    {
        "query": str (required),
        "user_id": int (optional),
        "max_results": int (optional, default=5),
        "min_importance": float (optional, default=0.3)
    }

    Returns:
        {
            "success": bool,
            "conversations": [
                {
                    "id": int,
                    "user_message": str,
                    "ai_response": str,
                    "summary": str,
                    "tags": List[str],
                    "importance": float,
                    "created_at": str
                }
            ],
            "count": int
        }
    """
    try:
        data = request.get_json()

        if not data or 'query' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required field: query'
            }), 400

        conversations = retrieve_similar_conversations(
            query=data['query'],
            user_id=data.get('user_id'),
            max_results=data.get('max_results', 5),
            min_importance=data.get('min_importance', 0.3)
        )

        return jsonify({
            'success': True,
            'conversations': conversations,
            'count': len(conversations)
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/personality', methods=['GET'])
def get_personality_endpoint():
    """
    Get A.R.C.H.I.E.'s current personality traits

    GET /api/personality

    Returns:
        {
            "success": bool,
            "personality": {
                "confidence_level": float,
                "cautiousness": float,
                "enthusiasm": float,
                "empathy": float,
                "curiosity": float,
                "personality_summary": str,
                "total_interactions": int
            }
        }
    """
    try:
        personality = get_archie_personality()

        return jsonify({
            'success': True,
            'personality': personality
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'archie_bridge_ingestion_api',
        'version': '1.0.0'
    }), 200

if __name__ == '__main__':
    # Run API server
    app.run(host='0.0.0.0', port=5001, debug=True)
