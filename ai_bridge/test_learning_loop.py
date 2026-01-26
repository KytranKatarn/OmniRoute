"""
Test A.R.C.H.I.E.'s Learning Loop with Emotional Intelligence
Tests the complete flow:
1. Ingest conversations with auto-tagging
2. Emotional analysis and trust tracking
3. RAG retrieval of similar conversations
4. Personality development
"""
import json
from conversation_ingest import (
    ingest_conversation,
    retrieve_similar_conversations,
    get_archie_personality
)
from emotional_intelligence import (
    analyze_sentiment,
    analyze_trust_impact,
    generate_personality_traits
)

def test_learning_loop():
    print("=" * 80)
    print("🧠 A.R.C.H.I.E. Learning Loop Test")
    print("=" * 80)

    # Test 1: Positive interaction
    print("\n📝 Test 1: Ingesting a positive Python conversation...")
    result1 = ingest_conversation(
        user_message="Great job! That Python code works perfectly. Thank you for explaining the database connection!",
        ai_response="I'm glad I could help! Here's the Python code to connect to PostgreSQL:\n```python\nimport psycopg2\nconn = psycopg2.connect(host='localhost', database='mydb', user='user', password='pass')\n```",
        user_id=None,  # No user tracking for this test
        source='test',
        model='deepseek-coder-v2:16b',
        provider='ollama'
    )

    if result1.get('success'):
        print("✅ Successfully ingested conversation!")
        print(f"   Memory ID: {result1.get('memory_id')}")
        print(f"   Tags: {', '.join(result1.get('tags_applied', []))}")
        print(f"   Sentiment: {result1.get('sentiment', {}).get('sentiment')} (confidence: {result1.get('sentiment', {}).get('confidence')})")
        print(f"   Trust Delta: {result1.get('trust_impact', {}).get('trust_delta')}")
        print(f"   Importance Score: {result1.get('importance_score')}")
    else:
        print(f"❌ Failed: {result1.get('error')}")
        if result1.get('traceback'):
            print(result1['traceback'])

    # Test 2: Negative/critical interaction
    print("\n📝 Test 2: Ingesting a critical database conversation...")
    result2 = ingest_conversation(
        user_message="This SQL query is wrong. It's not selecting the right columns. Please fix it.",
        ai_response="You're right, I apologize for the error. Here's the corrected SQL:\n```sql\nSELECT name, email, created_at FROM users WHERE status = 'active';\n```",
        user_id=None,
        source='test',
        model='llama3.1:8b',
        provider='ollama'
    )

    if result2.get('success'):
        print("✅ Successfully ingested conversation!")
        print(f"   Memory ID: {result2.get('memory_id')}")
        print(f"   Tags: {', '.join(result2.get('tags_applied', []))}")
        print(f"   Sentiment: {result2.get('sentiment', {}).get('sentiment')}")
        print(f"   User Emotion: {result2.get('sentiment', {}).get('user_emotion')}")
        print(f"   Trust Delta: {result2.get('trust_impact', {}).get('trust_delta')}")
        print(f"   Should Double Check: {result2.get('trust_impact', {}).get('should_double_check')}")
    else:
        print(f"❌ Failed: {result2.get('error')}")

    # Test 3: Curious/learning interaction
    print("\n📝 Test 3: Ingesting a curious API conversation...")
    result3 = ingest_conversation(
        user_message="How do I create a REST API endpoint in Flask? I want to learn!",
        ai_response="Great question! I love explaining this. Here's how to create a Flask API endpoint:\n```python\nfrom flask import Flask, jsonify\napp = Flask(__name__)\n\n@app.route('/api/users', methods=['GET'])\ndef get_users():\n    return jsonify({'users': []})\n```",
        user_id=None,
        source='test',
        model='nous-hermes2',
        provider='ollama'
    )

    if result3.get('success'):
        print("✅ Successfully ingested conversation!")
        print(f"   Memory ID: {result3.get('memory_id')}")
        print(f"   Tags: {', '.join(result3.get('tags_applied', []))}")
        print(f"   User Emotion: {result3.get('sentiment', {}).get('user_emotion')}")
        print(f"   Tone: {result3.get('sentiment', {}).get('tone')}")
    else:
        print(f"❌ Failed: {result3.get('error')}")

    # Test 4: RAG Retrieval
    print("\n" + "=" * 80)
    print("🔍 Test 4: RAG Retrieval - Finding similar conversations...")
    print("=" * 80)

    queries = [
        "How do I use Python to connect to a database?",
        "I need help with SQL queries",
        "Show me how to create an API"
    ]

    for query in queries:
        print(f"\n📊 Query: '{query}'")
        similar = retrieve_similar_conversations(
            query=query,
            user_id=None,  # Search all conversations
            max_results=3,
            min_importance=0.3
        )

        if similar:
            print(f"   Found {len(similar)} similar conversations:")
            for i, conv in enumerate(similar, 1):
                print(f"   {i}. Tags: {', '.join(conv.get('tags', []))}")
                print(f"      Importance: {conv.get('importance', 0):.2f}")
                print(f"      Summary: {conv.get('summary', '')[:80]}...")
        else:
            print("   No similar conversations found")

    # Test 5: Personality Evolution
    print("\n" + "=" * 80)
    print("🎭 Test 5: A.R.C.H.I.E.'s Personality Traits")
    print("=" * 80)

    personality = get_archie_personality()
    print(f"\n   Confidence Level: {personality.get('confidence_level', 0.5):.2f}")
    print(f"   Cautiousness: {personality.get('cautiousness', 0.5):.2f}")
    print(f"   Enthusiasm: {personality.get('enthusiasm', 0.6):.2f}")
    print(f"   Empathy: {personality.get('empathy', 0.6):.2f}")
    print(f"   Curiosity: {personality.get('curiosity', 0.9):.2f}")
    print(f"   Summary: {personality.get('personality_summary', 'developing')}")
    if 'total_interactions' in personality:
        print(f"   Total Interactions: {personality['total_interactions']}")

    print("\n" + "=" * 80)
    print("✅ Learning Loop Test Complete!")
    print("=" * 80)

    print("\n💡 Next Steps:")
    print("   1. Check the database to see stored conversations")
    print("   2. Try querying with different tags")
    print("   3. Watch personality evolve with more interactions")
    print("   4. Test the ingestion API endpoint at POST /api/ingest/conversation")

if __name__ == '__main__':
    try:
        test_learning_loop()
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
