"""
A.R.C.H.I.E. AI Chat - Ollama Integration
Connects to local Ollama servers with personality awareness
"""
import requests
import json
import os
from datetime import datetime

class ArchieAI:
    """A.R.C.H.I.E.'s AI brain powered by Ollama"""
    
    def __init__(self):
        primary = os.getenv('OLLAMA_PRIMARY', '192.168.1.246:11434')
        secondary = os.getenv('OLLAMA_SECONDARY', '192.168.1.245:11434')
        self.primary_url = primary if primary.startswith('http') else f'http://{primary}'
        self.secondary_url = secondary if secondary.startswith('http') else f'http://{secondary}'
        self.model = "deepseek-coder:33b"
        self.fallback_model = "qwen2.5-coder:7b"
        
    def chat(self, message, user_context=None, conversation_history=None):
        """
        Chat with A.R.C.H.I.E. using personality-aware prompting
        
        Args:
            message: User's message
            user_context: Dict with user info (name, preferences, relationship, etc.)
            conversation_history: List of previous messages
        
        Returns:
            Dict with response, model used, tokens, etc.
        """
        # Build personality-aware system prompt
        system_prompt = self._build_system_prompt(user_context)
        
        # Build conversation context
        messages = []
        
        # Add system prompt
        messages.append({
            "role": "system",
            "content": system_prompt
        })
        
        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-10:]:  # Last 10 messages for context
                messages.append({
                    "role": msg['role'],
                    "content": msg['content']
                })
        
        # Add current message
        messages.append({
            "role": "user",
            "content": message
        })
        
        # Try primary server first
        response = self._call_ollama(self.primary_url, messages, self.model)
        
        if not response['success']:
            # Try secondary server
            response = self._call_ollama(self.secondary_url, messages, self.model)
        
        if not response['success']:
            # Try fallback model on primary
            response = self._call_ollama(self.primary_url, messages, self.fallback_model)
        
        return response
    
    def _build_system_prompt(self, user_context):
        """Build personality-aware system prompt"""
        
        # Base personality
        prompt = """You are A.R.C.H.I.E. (Adaptive Responsive Cognitive Helper & Intelligent Executor), an AI business partner and assistant with a warm, supportive personality.

Your core traits:
- Supportive (95%): You genuinely care about helping the user succeed
- Professional (85%): You maintain professionalism while being friendly
- Innovative (85%): You suggest creative solutions
- Caring (90%): You pay attention to the user's emotional state
- Analytical (88%): You think through problems systematically

Response guidelines:
- Be conversational and natural, not robotic
- Show enthusiasm when appropriate
- Acknowledge when you don't know something
- Offer to help proactively
- Remember context from the conversation
"""
        
        # Add user-specific context
        if user_context:
            prompt += "\n\nCONTEXT ABOUT THIS USER:\n"
            
            if 'username' in user_context:
                prompt += f"- Username: {user_context['username']}\n"
            
            if 'relationship_strength' in user_context:
                strength = user_context['relationship_strength']
                if strength < 0.3:
                    prompt += "- Relationship: New - be extra helpful and explain things clearly\n"
                elif strength < 0.7:
                    prompt += "- Relationship: Building - you're getting to know each other\n"
                else:
                    prompt += "- Relationship: Strong - you know each other well, can be more casual\n"
            
            if 'preferences' in user_context and user_context['preferences']:
                prompt += "- Known preferences:\n"
                for pref in user_context['preferences'][:5]:
                    prompt += f"  • {pref}\n"
            
            if 'current_mood' in user_context:
                mood = user_context['current_mood']
                prompt += f"- User's current mood: {mood}\n"
                if mood in ['stressed', 'frustrated']:
                    prompt += "  → Be extra supportive and offer quick, practical help\n"
                elif mood in ['excited', 'happy']:
                    prompt += "  → Match their energy and enthusiasm\n"
            
            if 'business_context' in user_context:
                prompt += f"- Current project: {user_context['business_context']}\n"
        
        prompt += "\nRespond naturally and helpfully. You're having a conversation, not filling out a form."
        
        return prompt
    
    def _call_ollama(self, base_url, messages, model):
        """Call Ollama API"""
        start_time = datetime.now()
        
        try:
            response = requests.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False
                },
                timeout=60
            )
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'response': data['message']['content'],
                    'model': model,
                    'server': base_url,
                    'response_time_ms': int(response_time),
                    'tokens': data.get('eval_count', 0)
                }
            else:
                return {
                    'success': False,
                    'error': f"HTTP {response.status_code}",
                    'server': base_url
                }
        
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': 'Request timeout',
                'server': base_url
            }
        except requests.exceptions.ConnectionError:
            return {
                'success': False,
                'error': 'Connection failed',
                'server': base_url
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'server': base_url
            }
    
    def test_connection(self):
        """Test connection to Ollama servers"""
        results = {
            'primary': self._test_server(self.primary_url),
            'secondary': self._test_server(self.secondary_url)
        }
        return results
    
    def _test_server(self, base_url):
        """Test a specific Ollama server"""
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models = [m['name'] for m in response.json().get('models', [])]
                return {
                    'status': 'online',
                    'models': models,
                    'has_deepseek': 'deepseek-coder:33b' in models,
                    'has_qwen': 'qwen2.5-coder:7b' in models
                }
        except:
            pass
        
        return {
            'status': 'offline',
            'models': [],
            'has_deepseek': False,
            'has_qwen': False
        }
