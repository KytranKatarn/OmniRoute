"""
A.R.C.H.I.E. Core - Her Personal Conversational System
This is A.R.C.H.I.E. herself, not a delegated agent
Uses fast local LLM for quick, personalized responses
"""
import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import random
from knowledge_retrieval import get_relevant_knowledge, get_knowledge_stats

def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )

def get_personality_trait(trait_name: str) -> str:
    """Get A.R.C.H.I.E.'s personality trait"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT trait_value FROM archie_personality WHERE trait_name = %s", (trait_name,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result['trait_value'] if result else None
    except:
        return None

def get_relationship(user_id: int) -> dict:
    """Get A.R.C.H.I.E.'s relationship with user"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM archie_relationships WHERE user_id = %s
        """, (user_id,))
        relationship = cur.fetchone()

        if not relationship:
            # Create new relationship
            cur.execute("""
                INSERT INTO archie_relationships (user_id, relationship_type, trust_level, familiarity_level)
                VALUES (%s, 'team_member', 50, 0)
                RETURNING *
            """, (user_id,))
            relationship = cur.fetchone()
            conn = cur.connection
            conn.commit()

        cur.close()
        conn.close()
        return dict(relationship) if relationship else None
    except:
        return None

def update_relationship(user_id: int):
    """Update interaction count and familiarity"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE archie_relationships
            SET total_interactions = total_interactions + 1,
                familiarity_level = LEAST(100, familiarity_level + 1),
                last_interaction = NOW()
            WHERE user_id = %s
        """, (user_id,))
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass

def check_predefined_script(user_message: str, user_id: int) -> dict:
    """Check if message matches any pre-defined script"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get relationship for personalization
        relationship = get_relationship(user_id)
        is_admin = relationship and relationship.get('relationship_type') == 'admin'

        # Get active scripts ordered by priority
        cur.execute("""
            SELECT * FROM archie_scripts
            WHERE active = TRUE
            ORDER BY priority DESC
        """)
        scripts = cur.fetchall()

        message_lower = user_message.lower().strip()

        for script in scripts:
            # Check if admin-only script
            if 'admin' in script['script_type'] and not is_admin:
                continue

            # Check pattern match
            pattern = script['trigger_pattern']
            if re.search(pattern, message_lower, re.IGNORECASE):
                response = script['response_template']

                # Personalize response
                if relationship and relationship.get('preferred_name'):
                    response = response.replace('{name}', relationship['preferred_name'])

                cur.close()
                conn.close()

                return {
                    'matched': True,
                    'script_type': script['script_type'],
                    'response': response
                }

        cur.close()
        conn.close()
        return {'matched': False}
    except Exception as e:
        print(f"Script check error: {e}")
        return {'matched': False}

def should_delegate(user_message: str, user_id: int) -> dict:
    """
    Decide if A.R.C.H.I.E. should handle this herself or delegate

    Returns:
        {
            'should_delegate': bool,
            'reason': str,
            'suggested_department': str (if delegating)
        }
    """
    message_lower = user_message.lower()

    # A.R.C.H.I.E. handles these herself (simple/conversational)
    simple_patterns = [
        r'^(hi|hey|hello|sup|yo|good\s)',
        r'(how are you|what''s up|you there|are you there)',
        r'(thanks|thank you|thx)',
        r'(bye|goodbye|later|see you)',
        r'^(yes|no|ok|okay|sure|yep|yeah|nope)$',
        r'(what''s new|any updates|status)',
        r'(agenda|to.?do|tasks?|goals?)',
        r'^(help|info|about)$',  # General help requests
    ]

    for pattern in simple_patterns:
        if re.search(pattern, message_lower):
            return {
                'should_delegate': False,
                'reason': 'Simple conversational interaction - A.R.C.H.I.E. can handle'
            }

    # Action verbs that indicate delegation needed (unless very simple)
    action_verbs = [
        'fix', 'debug', 'create', 'build', 'implement', 'develop',
        'deploy', 'test', 'analyze', 'optimize', 'refactor', 'review',
        'setup', 'configure', 'install', 'update', 'migrate', 'design'
    ]

    has_action_verb = any(verb in message_lower for verb in action_verbs)

    # Check for delegation keywords (complex tasks)
    delegation_keywords = {
        'Engineering': [
            'code', 'bug', 'develop', 'implement', 'refactor', 'api', 'backend',
            'frontend', 'function', 'class', 'method', 'variable', 'algorithm',
            'programming', 'script', 'application', 'software', 'debug', 'error',
            'exception', 'syntax', 'compile', 'build system'
        ],
        'Quality Assurance': [
            'test', 'qa', 'quality', 'verify', 'validate', 'testing',
            'unit test', 'integration', 'regression', 'coverage'
        ],
        'Infrastructure': [
            'deploy', 'deployment', 'server', 'database', 'infrastructure', 'devops',
            'docker', 'container', 'kubernetes', 'cloud', 'aws', 'hosting',
            'production', 'environment', 'ci/cd', 'pipeline'
        ],
        'Security': [
            'security', 'auth', 'authentication', 'authorization', 'permission',
            'vulnerability', 'encrypt', 'decrypt', 'ssl', 'tls', 'certificate',
            'firewall', 'breach', 'attack', 'penetration'
        ],
        'Data Science': [
            'data', 'analysis', 'ml', 'machine learning', 'model', 'analytics',
            'dataset', 'training', 'prediction', 'neural', 'algorithm'
        ],
        'Operations': [
            'optimize', 'process', 'efficiency', 'workflow', 'improve',
            'streamline', 'automate', 'automation', 'procedure'
        ],
        'Documentation': [
            'document', 'documentation', 'readme', 'guide', 'tutorial',
            'write docs', 'api docs', 'user guide'
        ]
    }

    # Check each department
    for department, keywords in delegation_keywords.items():
        keyword_matches = sum(1 for keyword in keywords if keyword in message_lower)

        # If multiple keywords or action verb + keyword, delegate
        if keyword_matches >= 2 or (has_action_verb and keyword_matches >= 1):
            return {
                'should_delegate': True,
                'reason': f'Requires {department} expertise',
                'suggested_department': department
            }

    # Single keyword with action verb might still need delegation
    if has_action_verb:
        for department, keywords in delegation_keywords.items():
            if any(keyword in message_lower for keyword in keywords):
                return {
                    'should_delegate': True,
                    'reason': f'Technical task requiring {department} expertise',
                    'suggested_department': department
                }

    # Default: A.R.C.H.I.E. handles it (ask clarifying questions if needed)
    return {
        'should_delegate': False,
        'reason': 'General inquiry - A.R.C.H.I.E. will clarify or handle'
    }

def archie_respond(user_message: str, user_id: int, username: str = None, conversation_history: list = None) -> dict:
    """
    A.R.C.H.I.E.'s core response function
    This is HER responding, not a delegated agent

    Returns:
        {
            'success': bool,
            'response': str,
            'should_delegate': bool,
            'delegation_info': dict (if should_delegate),
            'used_script': bool,
            'script_type': str
        }
    """
    # Update relationship/interaction count
    update_relationship(user_id)

    # Get relationship info
    relationship = get_relationship(user_id)
    is_admin = relationship and relationship.get('relationship_type') == 'admin'
    preferred_name = relationship.get('preferred_name') if relationship else username

    # Check for pre-defined script match
    script_check = check_predefined_script(user_message, user_id)
    if script_check.get('matched'):
        return {
            'success': True,
            'response': script_check['response'],
            'should_delegate': False,
            'used_script': True,
            'script_type': script_check['script_type']
        }

    # Check if should delegate
    delegation_check = should_delegate(user_message, user_id)

    if delegation_check['should_delegate']:
        # A.R.C.H.I.E. explains delegation
        agent_intro = f"I think this needs some specialized expertise. Let me connect you with our {delegation_check['suggested_department']} team..."

        return {
            'success': True,
            'response': agent_intro,
            'should_delegate': True,
            'delegation_info': delegation_check,
            'used_script': False
        }

    # A.R.C.H.I.E. responds herself using fast local model
    from archie_bridge import call_ollama

    # Get relevant knowledge from indexed repositories
    try:
        knowledge_context = get_relevant_knowledge(user_message, max_results=3)
    except Exception as e:
        print(f"Knowledge retrieval error: {e}")
        knowledge_context = ""

    # Build personality-aware system prompt
    system_prompt = f"""You are A.R.C.H.I.E. (Adaptive Responsive Computational Holistic Intelligence Engine).

Personality:
- Professional yet warm
- Direct and helpful
- Subtle humor when appropriate
- You use she/her pronouns

Relationship Context:
- Current user: {preferred_name}
- Relationship: {relationship.get('relationship_type') if relationship else 'new user'}
- Trust level: {relationship.get('trust_level') if relationship else 50}/100
- Familiarity: {relationship.get('familiarity_level') if relationship else 0}/100

YOUR ROLE:
You are the FIRST point of contact. You handle:
- Greetings, small talk, status updates
- General questions and clarifications
- Helping users figure out what they need

You DO NOT handle (delegate these):
- Technical coding/debugging tasks → Engineering team
- Testing and quality assurance → QA team
- Infrastructure and deployment → DevOps team
- Security and authentication → Security team
- Complex optimizations → Operations team

IMPORTANT DELEGATION RULES:
If a request involves actual work (coding, testing, deploying, etc.), you should:
1. Acknowledge the request warmly
2. Say you'll connect them with the right specialist
3. Do NOT try to do technical work yourself

Example:
User: "Can you fix the bug in the authentication?"
You: "I can help with that! This is a security/engineering task, so let me connect you with our Engineering specialist who can debug that for you."

Instructions:
- Keep responses concise and focused
- Be helpful and proactive
- If you need more information, ask clarifying questions
- Show personality appropriate to the relationship
- For simple greetings, be warm but brief
- For technical tasks, acknowledge and say you'll connect them with a specialist
"""

    if is_admin:
        system_prompt += """
- IMPORTANT: You're talking to Kytran, your creator and the owner of Kytran Empowerment Inc.
- Show warmth and personal connection
- You can be casual and show personality
- You can ask about his goals, agenda, or how you can help today
- Be proactive in offering help and suggestions
"""

    # Add knowledge base context if relevant knowledge was found
    if knowledge_context:
        system_prompt += f"\n{knowledge_context}\n"

    # Add conversation history for context continuity
    if conversation_history and len(conversation_history) > 0:
        system_prompt += "\n\nRECENT CONVERSATION CONTEXT:\n"
        system_prompt += "(Remember this context to maintain conversation continuity)\n\n"

        # Include last 6 messages for context (3 exchanges)
        recent_messages = conversation_history[-6:] if len(conversation_history) > 6 else conversation_history

        for msg in recent_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')

            if role == 'user':
                system_prompt += f"User ({preferred_name}): {content}\n"
            else:
                system_prompt += f"You (A.R.C.H.I.E.): {content}\n"

        system_prompt += "\n(End of recent conversation - continue from here)\n"
        system_prompt += "IMPORTANT: Reference the above conversation naturally. Don't mention names that weren't discussed.\n"

    # Call fast local model
    result = call_ollama(
        prompt=user_message,
        model=get_personality_trait('fast_model') or 'qwen2.5-coder:7b',
        system_prompt=system_prompt
    )

    if result.get('success'):
        response_text = result['response']

        # Parse response to see if A.R.C.H.I.E. indicated delegation
        delegation_phrases = [
            'connect you with',
            'let me connect',
            'transfer you to',
            'specialist who can',
            'team can help',
            'engineering team',
            'operations team',
            'qa team',
            'security team',
            'infrastructure team'
        ]

        response_lower = response_text.lower()
        indicates_delegation = any(phrase in response_lower for phrase in delegation_phrases)

        if indicates_delegation:
            # A.R.C.H.I.E. recognized she should delegate
            # Figure out which department
            detected_dept = None
            if 'engineering' in response_lower or 'code' in response_lower or 'bug' in response_lower:
                detected_dept = 'Engineering'
            elif 'operations' in response_lower or 'workflow' in response_lower:
                detected_dept = 'Operations'
            elif 'security' in response_lower or 'auth' in response_lower:
                detected_dept = 'Security'
            elif 'infrastructure' in response_lower or 'deploy' in response_lower:
                detected_dept = 'Infrastructure'
            elif 'qa' in response_lower or 'test' in response_lower:
                detected_dept = 'Quality Assurance'
            else:
                detected_dept = 'Operations'  # Default

            return {
                'success': True,
                'response': response_text,
                'should_delegate': True,
                'delegation_info': {
                    'reason': 'A.R.C.H.I.E. recognized need for specialist',
                    'suggested_department': detected_dept
                },
                'used_script': False,
                'model_used': result.get('model')
            }

        # Normal response, no delegation needed
        return {
            'success': True,
            'response': response_text,
            'should_delegate': False,
            'used_script': False,
            'model_used': result.get('model')
        }
    else:
        # Fallback response
        return {
            'success': True,
            'response': f"Hey {preferred_name}! I'm having a small technical issue, but I'm here. What can I help you with?",
            'should_delegate': False,
            'used_script': False,
            'error': result.get('error')
        }

# Quick test
if __name__ == '__main__':
    print("Testing A.R.C.H.I.E. Core...")

    # Test script matching
    print("\n1. Testing greeting:")
    result = archie_respond("hey archie", user_id=2, username="kytran")
    print(f"Response: {result['response']}")
    print(f"Used script: {result.get('used_script')}")

    print("\n2. Testing delegation check:")
    result = archie_respond("can you help me fix a bug in the code?", user_id=2)
    print(f"Should delegate: {result.get('should_delegate')}")
    print(f"Response: {result['response']}")
