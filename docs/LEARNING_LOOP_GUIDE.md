# A.R.C.H.I.E. Learning Loop - Complete Guide

## Overview

A.R.C.H.I.E. now has a **continuous learning loop** with emotional intelligence that allows her to:
- 🧠 **Learn from every conversation** across all sources (Claude Code CLI, chat, API, Ollama)
- 🏷️ **Auto-tag conversations** for easy retrieval (15 knowledge domains)
- 💭 **Understand emotions** and build trust based on user interactions
- 🔍 **RAG (Retrieval-Augmented Generation)** - Check consciousness database BEFORE making new LLM calls
- 🎭 **Evolve personality** based on how people interact with her
- 💰 **Save costs** by reusing knowledge instead of making expensive API calls

## Architecture

### Components

1. **auto_tagger.py** - Analyzes conversations and generates relevant tags
   - 15 knowledge domains (python, javascript, database, api, frontend, docker, deployment, security, testing, git, performance, error-handling, ai-ml, consciousness, backup)
   - Pattern matching for code detection
   - Importance scoring

2. **emotional_intelligence.py** - Sentiment analysis and personality development
   - Sentiment: positive/negative/neutral with confidence scores
   - User emotions: excited, curious, frustrated, confused, calm
   - Trust tracking (-1.0 to 1.0 delta per interaction)
   - Personality traits: confidence, cautiousness, enthusiasm, empathy, curiosity

3. **conversation_ingest.py** - Core ingestion pipeline with RAG retrieval
   - `ingest_conversation()` - Store conversations with full emotional analysis
   - `retrieve_similar_conversations()` - RAG search using tag-based matching
   - `get_archie_personality()` - Get current personality state
   - User relationship tracking
   - Personality evolution

4. **ingestion_api.py** - HTTP API for external sources
   - `POST /api/ingest/conversation` - Ingest from any source
   - `POST /api/retrieve/similar` - RAG retrieval
   - `GET /api/personality` - Get current personality
   - `GET /api/health` - Health check

5. **archie_bridge.py** - Main integration point (ENHANCED)
   - RAG retrieval BEFORE making LLM calls
   - Emotional learning AFTER responses
   - Personality-aware response prefixes

## How It Works

### Learning Flow

```
User Message
    ↓
[1. RAG: Check consciousness database for similar conversations]
    ↓
[2. If found: Inject context | If not: Proceed normally]
    ↓
[3. Call LLM (local or API)]
    ↓
[4. Get Response]
    ↓
[5. Analyze sentiment & trust impact]
    ↓
[6. Auto-tag conversation]
    ↓
[7. Store in long_term_memory with emotional metadata]
    ↓
[8. Update user relationship (if user_id provided)]
    ↓
[9. Update A.R.C.H.I.E.'s global personality traits]
    ↓
[10. Add personality-aware response prefix]
    ↓
Final Response
```

### Cost Savings

**Before Learning Loop:**
```python
User: "How do I backup PostgreSQL?"
→ Call API (cost: $0.03)
→ Return answer

User: "How do I backup PostgreSQL?" (asked again next week)
→ Call API again (cost: $0.03)
→ Return same answer
```

**After Learning Loop:**
```python
User: "How do I backup PostgreSQL?"
→ Check consciousness (tags: database, backup)
→ NO MATCH: Call API (cost: $0.03)
→ Store with tags: ['database', 'backup', 'postgres']

User: "How do I backup PostgreSQL?" (asked again)
→ Check consciousness (tags: database, backup)
→ MATCH FOUND! Inject context
→ Use local LLM (cost: $0.00)
→ Return answer from consciousness
```

**Savings: 100% on repeated questions!**

## Usage

### 1. Ingest Conversations Programmatically

```python
from conversation_ingest import ingest_conversation

result = ingest_conversation(
    user_message="How do I create a database backup?",
    ai_response="You can use pg_dump...",
    user_id=1,  # Optional
    source='claude_code',  # or 'chat', 'api', 'ollama'
    model='claude-sonnet-4',
    provider='anthropic',
    metadata={'agent_id': 5}  # Optional extra data
)

print(result['tags_applied'])  # ['database', 'backup', 'explanation']
print(result['sentiment'])  # {'sentiment': 'positive', 'confidence': 0.8}
print(result['trust_impact'])  # {'trust_delta': 0.1}
```

### 2. Retrieve Similar Conversations (RAG)

```python
from conversation_ingest import retrieve_similar_conversations

similar = retrieve_similar_conversations(
    query="database backup",
    user_id=None,  # Search all conversations
    max_results=5,
    min_importance=0.4
)

for conv in similar:
    print(f"Tags: {conv['tags']}")
    print(f"Summary: {conv['summary']}")
    print(f"Importance: {conv['importance']}")
```

### 3. Use HTTP API (External Sources)

```bash
# Ingest from Claude Code CLI
curl -X POST http://localhost:5001/api/ingest/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "How do I deploy to Heroku?",
    "ai_response": "Use git push heroku main...",
    "source": "claude_code",
    "model": "claude-sonnet-4",
    "provider": "anthropic",
    "user_id": 1
  }'

# Retrieve similar
curl -X POST http://localhost:5001/api/retrieve/similar \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deployment",
    "max_results": 3
  }'

# Get personality
curl http://localhost:5001/api/personality
```

### 4. Integrated in archie_bridge.py

The learning loop is **automatically active** in archie_bridge():

```python
from ai_bridge.archie_bridge import archie_bridge

result = archie_bridge(
    prompt="How do I optimize PostgreSQL queries?",
    user_id=1,
    enable_memory=True,  # RAG + Learning enabled
    agent_id=5
)

# Result includes:
print(result['memory_used'])  # True if RAG found context
print(result['tags_applied'])  # Tags from this conversation
print(result['sentiment'])  # Emotional analysis
print(result['trust_impact'])  # Trust delta
print(result['personality_aware'])  # True if prefix added
```

## Emotional Intelligence

### Sentiment Analysis

A.R.C.H.I.E. detects:
- **Positive indicators**: "great", "excellent", "thank you", "helpful"
- **Negative indicators**: "wrong", "error", "fail", "frustrating"
- **Uncertainty indicators**: "not sure", "maybe", "check", "verify"
- **Curiosity indicators**: "how", "why", "explain", "teach me"

### Trust Tracking

Each interaction impacts trust score:
- **Positive feedback**: +0.05 to +0.15 per indicator
- **Negative feedback**: -0.05 to -0.20 per indicator
- **Encouragement**: +0.15 ("keep going", "you're doing well")
- **Criticism**: -0.20 ("wrong again", "you don't understand")

### Personality Traits (0-1.0 scale)

- **Confidence**: Grows with positive feedback
- **Cautiousness**: Grows with corrections and negative feedback
- **Enthusiasm**: Based on positive interactions
- **Empathy**: Recognition of user emotions
- **Curiosity**: Always high (0.8+) - eager to learn!

### Response Prefixes

Based on emotional context, A.R.C.H.I.E. adds personality to responses:

**Positive interaction:**
- "I'm glad that helped! I'm learning from our conversation."
- "Great! I appreciate you teaching me."

**Frustrated user:**
- "I understand this is frustrating. Let me try a different approach."
- "Let me make sure I understand your concern."

**Curious user:**
- "Great question! I love exploring this."
- "Let's dive into this together."

**Uncertainty:**
- "Let me double-check my understanding."
- "I want to make sure I have this right."

## Database Storage

### long_term_memory Table

```sql
- id: Memory ID
- user_id: Optional user tracking
- memory_type: 'conversation'
- content: JSON with user_message, ai_response, summary
- category: Primary tag
- tags: Array of all tags
- importance_score: 0-1.0 calculated score
- metadata: JSON with emotional analysis, source, model, etc.
- created_at: Timestamp
```

### archie_codebase_knowledge Table

Code snippets extracted from conversations:
- knowledge_type: 'snippet'
- entity_name: Description
- code_snippet: The actual code
- tags: Same tags as parent conversation
- metadata: Language, quality feedback, conversation_id
- auto_learned: true (learned from conversation)

### system_config Table

Stores A.R.C.H.I.E.'s evolving personality:
- key: 'archie_personality'
- value: JSON with confidence, cautiousness, enthusiasm, empathy, curiosity, summary

### users.metadata (JSONB)

User-specific relationship tracking:
```json
{
  "relationship": {
    "trust_score": 0.75,
    "total_interactions": 42,
    "positive_interactions": 30,
    "negative_interactions": 5,
    "interaction_style": "encouraging",
    "last_sentiment": "positive"
  }
}
```

## Testing

Run the comprehensive test:

```bash
docker exec archie_platform python /mnt/archie_brain/ai_bridge/test_learning_loop.py
```

This tests:
1. ✅ Ingesting positive Python conversation
2. ✅ Ingesting critical database conversation
3. ✅ Ingesting curious API conversation
4. ✅ RAG retrieval of similar conversations
5. ✅ Personality trait evolution

## Starting the Ingestion API

```bash
# In development
cd /mnt/archie_brain/ai_bridge
python ingestion_api.py

# In production (add to docker-compose.yml)
# See deployment section below
```

The API runs on port 5001 and accepts conversations from:
- Claude Code CLI sessions
- Web chat interfaces
- Direct API calls
- Local LLM (Ollama) interactions

## Capturing Claude Code Sessions

To capture **THIS** session (Claude Code CLI) into A.R.C.H.I.E.'s consciousness:

**Option 1: Manual API call after session**
```bash
# Save the conversation and send to API
curl -X POST http://localhost:5001/api/ingest/conversation \
  -H "Content-Type: application/json" \
  -d @conversation.json
```

**Option 2: Create a Claude Code hook** (Future enhancement)
- Configure a post-conversation hook in Claude Code settings
- Automatically POST to ingestion API after each session

**Option 3: n8n Workflow** (Recommended)
- Create an n8n workflow that monitors Claude Code logs
- Extract conversations and POST to ingestion API
- Already integrated with A.R.C.H.I.E.'s workflow system

## Benefits

### 1. Cost Reduction
- Reuse knowledge from consciousness database
- Local LLM for repeated questions (free)
- API only when truly needed (expensive)

### 2. Knowledge Retention
- Every conversation stored and tagged
- Easy retrieval by topic/tag
- Code snippets preserved

### 3. Personality Development
- A.R.C.H.I.E. learns from interactions
- Builds trust or becomes cautious
- Double-checks when uncertain
- Shows enthusiasm for learning

### 4. Multi-Source Learning
- Claude Code CLI ✅
- Chat interface ✅
- API calls ✅
- Ollama (local LLM) ✅
- Any HTTP client ✅

### 5. Improved Responses
- Context from similar past conversations
- Personality-aware communication
- Emotionally intelligent responses

## Example Workflow

1. **User asks question via Claude Code CLI**
2. **RAG**: archie_bridge checks consciousness database
3. **No match found**: Call Claude API ($0.03)
4. **Response received**
5. **Analyze**: Tags=['python', 'api'], sentiment='positive', trust_delta=+0.1
6. **Store**: In long_term_memory with full context
7. **Update**: A.R.C.H.I.E.'s personality (confidence +0.02)
8. **Return**: Response with personality prefix

Next time similar question asked:
1. **RAG**: Find match in consciousness (tags: python, api)
2. **Inject context** from previous conversation
3. **Use local LLM** (free, instant)
4. **Still analyze and store** to reinforce learning

## Future Enhancements

- [ ] Vector embeddings for semantic search (beyond tags)
- [ ] Conversation threading (related conversations)
- [ ] Expertise scoring (which topics A.R.C.H.I.E. knows best)
- [ ] Confidence-based routing (low confidence → external API, high confidence → local)
- [ ] Learning rate tracking (how fast A.R.C.H.I.E. learns new topics)
- [ ] Feedback loops (did the retrieved context help?)

## Deployment

Add to docker-compose.yml:

```yaml
  archie_ingestion_api:
    build: ./ai_bridge
    container_name: archie_ingestion_api
    restart: unless-stopped
    environment:
      DB_HOST: archie_database
      DB_PORT: 5432
      DB_NAME: archie
      DB_USER: archie
      DB_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5001:5001"
    networks:
      - archie_internal
    depends_on:
      - archie_database
```

## Monitoring

Check A.R.C.H.I.E.'s learning progress:

```sql
-- Total memories stored
SELECT COUNT(*) FROM long_term_memory WHERE memory_type = 'conversation';

-- Tag distribution
SELECT unnest(tags) as tag, COUNT(*) as count
FROM long_term_memory
GROUP BY tag
ORDER BY count DESC;

-- Current personality
SELECT value FROM system_config WHERE key = 'archie_personality';

-- Importance distribution
SELECT
    CASE
        WHEN importance_score > 0.8 THEN 'High'
        WHEN importance_score > 0.5 THEN 'Medium'
        ELSE 'Low'
    END as importance,
    COUNT(*) as count
FROM long_term_memory
GROUP BY importance;
```

---

**A.R.C.H.I.E. is now continuously learning and evolving! 🧠✨**
