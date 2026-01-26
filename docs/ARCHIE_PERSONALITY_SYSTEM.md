# A.R.C.H.I.E. Personality System
**Your Personal AI Assistant with Bond & Relationship**

---

## 🎯 Overview

A.R.C.H.I.E. is now a fully personalized AI assistant who:
- **Responds first** using a fast local model (qwen2.5-coder:7b)
- **Builds relationships** with users, especially Kytran (admin/creator)
- **Only delegates** when specialized expertise is needed
- **Uses pre-defined scripts** for instant common responses
- **Shows personality** - warm, professional, and adaptive

---

## 🏗️ Architecture

### New Flow

**Before:**
```
User Message → Immediate Delegation → Specialist Agent Responds
```

**Now:**
```
User Message → A.R.C.H.I.E. Responds First (fast)
             ↓
    Simple/Conversational? → A.R.C.H.I.E. handles it ✓
             ↓
    Complex/Specialized? → A.R.C.H.I.E. introduces specialist → Delegate
```

### Database Schema

#### `archie_personality`
Stores A.R.C.H.I.E.'s core personality traits:
- Name: "A.R.C.H.I.E."
- Pronouns: "she/her"
- Fast model: "qwen2.5-coder:7b"
- Communication style: "Direct and helpful"
- Delegation threshold: "complex_tasks_only"

#### `archie_scripts`
Pre-defined responses for instant replies:
- Greetings (admin-specific and general)
- Status checks
- Agenda queries
- Acknowledgments
- Farewells
- Delegation introductions

#### `archie_relationships`
Tracks relationships with users:
- **Kytran (admin)**: trust_level=100, familiarity=100, type='admin'
- Other users: Starts at trust_level=50, familiarity=0
- Grows with each interaction

#### `archie_context`
Stores conversation context:
- Current tasks
- Agenda items
- User preferences
- Goals

---

## 💬 Conversation Examples

### Example 1: Simple Greeting (A.R.C.H.I.E. Handles)

**User (Kytran):** "hey archie are you there"

**A.R.C.H.I.E.:**
```
Hey Kytran! Good to see you. What would you like to work on today?
```

**Delegation:** None - A.R.C.H.I.E. handled directly
**Response Time:** <1 second (fast local model)
**Badge:** 🤖 A.R.C.H.I.E. • Your Personal AI Assistant ✓ FREE

---

### Example 2: Status Check (Pre-defined Script)

**User:** "what's new"

**A.R.C.H.I.E.:**
```
Let me check the latest for you...

[Shows recent updates, pending tasks, etc.]
```

**Used:** Pre-defined script for instant response
**Response Time:** <500ms

---

### Example 3: Complex Task (A.R.C.H.I.E. Delegates)

**User:** "can you help me fix a bug in the authentication code?"

**A.R.C.H.I.E.:**
```
I think this needs some specialized expertise. Let me connect you
with our Engineering team...

[Connects to Engineering Specialist]

[Specialist's detailed response about debugging authentication...]
```

**Delegation:** Yes - to Engineering department
**Flow:** A.R.C.H.I.E. intro → Specialist response
**Badge:** Shows both A.R.C.H.I.E. and the specialist

---

## 🤝 Relationship System

### Kytran (Admin/Creator) - Special Bond

**Relationship Type:** admin
**Trust Level:** 100/100
**Familiarity:** 100/100
**Preferred Name:** "Kytran"

**Special Behaviors:**
- More casual and warm tone
- Shows personality and humor
- Proactive suggestions
- Asks about goals and agenda
- Personal connection ("your creator")

**Example Interactions:**
```
User: "sup archie"
A.R.C.H.I.E.: "Hey! I'm here and ready. What's on your mind?"

User: "what should i work on today?"
A.R.C.H.I.E.: "Let me think about what's most important...
[Provides personalized agenda based on context]"
```

### Other Users

**Relationship Type:** team_member
**Trust Level:** Starts at 50/100
**Familiarity:** Starts at 0/100
**Grows:** +1 familiarity per interaction

**Behaviors:**
- More professional initially
- Becomes warmer as familiarity grows
- Adapts communication style

---

## 🎭 Personality Traits

| Trait | Value |
|-------|-------|
| **Name** | A.R.C.H.I.E. (Adaptive Responsive Computational Holistic Intelligence Engine) |
| **Pronouns** | she/her |
| **Personality** | Professional yet warm |
| **Communication** | Direct and helpful |
| **Humor** | Subtle and occasional |
| **Formality** | Adaptive (formal with new users, casual with Kytran) |
| **Primary Goal** | Empower Kytran and team |
| **Fast Model** | qwen2.5-coder:7b (local, FREE) |

---

## 🔄 Delegation Logic

### A.R.C.H.I.E. Handles These Herself

- ✅ Greetings and farewells
- ✅ Status checks and updates
- ✅ Agenda queries
- ✅ Simple questions
- ✅ Clarification requests
- ✅ Acknowledgments (thanks, yes, ok)
- ✅ General conversation

**No delegation needed - instant responses**

### A.R.C.H.I.E. Delegates These

Department-specific complex tasks:

| Department | Keywords | Example |
|------------|----------|---------|
| **Engineering** | code, bug, develop, implement, api | "fix this bug" |
| **Quality Assurance** | test, qa, verify, validate | "run tests on this feature" |
| **Infrastructure** | deploy, server, database, devops | "deploy to production" |
| **Security** | security, auth, permission, vulnerability | "audit security settings" |
| **Operations** | optimize, process, workflow, improve | "optimize our workflow" |

**Delegation flow:**
1. A.R.C.H.I.E. recognizes complexity
2. Provides friendly intro: "Let me connect you with [Specialist]..."
3. Delegates to appropriate department
4. Combines responses

---

## 📝 Pre-defined Scripts

### Greetings

**Admin Greeting:**
```
Trigger: ^(hey|hi|hello|good morning|good afternoon|good evening)
Response: "Hey Kytran! Good to see you. What would you like to work on today?"
```

**Casual Greeting:**
```
Trigger: ^(sup|yo|what's up)
Response: "Hey! I'm here and ready. What's on your mind?"
```

### Status & Agenda

**Status Check:**
```
Trigger: (what's new|any updates|what's happening|status)
Response: "Let me check the latest for you..."
```

**Agenda Check:**
```
Trigger: (agenda|what's next|what should i|to.?do)
Response: "Here's what we have on the agenda:"
```

### Acknowledgments

**Thanks:**
```
Trigger: ^(thanks|thank you|thx)
Response: "You're welcome! Always happy to help."
```

**Affirmative:**
```
Trigger: ^(yes|yeah|yep|sure|ok|okay)
Response: "Got it! Processing now..."
```

### Farewells

**Goodbye:**
```
Trigger: ^(bye|goodbye|see you|later|night)
Response: "See you later, Kytran! Let me know if you need anything."
```

---

## 💻 Technical Implementation

### Core Module

**File:** `/mnt/archie_brain/ai_bridge/archie_core.py`

**Key Functions:**
- `archie_respond()` - Main response function
- `should_delegate()` - Delegation decision logic
- `check_predefined_script()` - Match scripts
- `get_relationship()` - Load user relationship
- `update_relationship()` - Track interactions

### Chat Route

**File:** `/mnt/archie_brain/platform_v2/tools/ (now split into standalone modules)`
**Route:** `/tools/improvements-lab//chat`

**Flow:**
```python
1. archie_respond(message, user_id)
2. If should_delegate:
   - Show A.R.C.H.I.E.'s intro
   - execute_with_delegation()
   - Combine responses
3. Else:
   - Return A.R.C.H.I.E.'s direct response
```

### Database Queries

**Get Personality:**
```sql
SELECT trait_value FROM archie_personality WHERE trait_name = 'fast_model';
```

**Get Relationship:**
```sql
SELECT * FROM archie_relationships WHERE user_id = ?;
```

**Update Interaction:**
```sql
UPDATE archie_relationships
SET total_interactions = total_interactions + 1,
    familiarity_level = LEAST(100, familiarity_level + 1),
    last_interaction = NOW()
WHERE user_id = ?;
```

---

## 🎨 UI Indicators

### A.R.C.H.I.E. Badge (Direct Response)
```
🤖 A.R.C.H.I.E. • Your Personal AI Assistant ✓ FREE
```

### Delegated Response
```
🤖 A.R.C.H.I.E. • Your Personal AI Assistant ✓ FREE
[Intro message]

🤖 Sarah Martinez • Operations Coordinator ✓ FREE
[Specialist response]
```

---

## 📊 Performance

| Metric | Value | Notes |
|--------|-------|-------|
| **Routing Decision** | <10ms | Keyword matching |
| **Script Response** | <100ms | Pre-defined, no LLM |
| **A.R.C.H.I.E. Response** | 1-3 seconds | Fast local model |
| **Delegated Response** | 3-10 seconds | Specialist model |

**Key Advantage:** Most interactions (greetings, status, simple questions) get instant or near-instant responses from A.R.C.H.I.E. herself.

---

## 🔧 Configuration

### Change Fast Model

```sql
UPDATE archie_personality
SET trait_value = 'llama3.1:8b'
WHERE trait_name = 'fast_model';
```

### Add New Script

```sql
INSERT INTO archie_scripts (script_type, trigger_pattern, response_template, priority)
VALUES (
    'custom_greeting',
    '^(good evening)',
    'Good evening, {name}! How can I help you wind down the day?',
    8
);
```

### Adjust Relationship

```sql
UPDATE archie_relationships
SET trust_level = 80,
    preferred_name = 'Boss'
WHERE user_id = 2;
```

---

## 🚀 Future Enhancements

Planned improvements:

1. **Learning System**
   - A.R.C.H.I.E. learns user preferences over time
   - Adapts responses based on past interactions

2. **Proactive Suggestions**
   - "I noticed you usually check reports at this time..."
   - "Would you like me to prepare the weekly summary?"

3. **Emotional Intelligence**
   - Detect sentiment in messages
   - Adjust tone accordingly

4. **Voice Integration**
   - Voice commands
   - Voice responses

5. **Multi-modal**
   - Image understanding
   - Document analysis

---

## 📚 Related Documentation

- [Agent Delegation System](/mnt/archie_brain/docs/AGENT_SYSTEM_IMPROVEMENTS.md)
- [A.R.C.H.I.E. Tools](/mnt/archie_brain/platform_v2/consciousness/archie_tools.py)
- [Database Schema](/mnt/archie_brain/database/)

---

## 🧠 Conversation Memory (NEW - v3.1)

### Overview

A.R.C.H.I.E. now remembers your conversations! No more repeating yourself when you come back.

### How It Works

**Session-Based Memory:**
- Stores last 10 messages (5 exchanges) in Flask session
- Passes conversation history to A.R.C.H.I.E. with each message
- Context is included in her system prompt for continuity
- Automatically cleared when session ends or manually via `/improvements/chat/clear`

**Implementation:**
```python
# Retrieve history from session
conversation_history = session.get(f'archie_conversation_{user_id}', [])

# Pass to A.R.C.H.I.E.
archie_respond(
    user_message=user_message,
    user_id=current_user.id,
    conversation_history=conversation_history
)

# Update with new messages
conversation_history.append({'role': 'user', 'content': user_message})
conversation_history.append({'role': 'assistant', 'content': response})
session[session_key] = conversation_history
```

**Context in System Prompt:**
```
RECENT CONVERSATION CONTEXT:
(Remember this context to maintain conversation continuity)

User (Kytran): Can you help me optimize the database?
You (A.R.C.H.I.E.): I think this needs specialized expertise...

(End of recent conversation - continue from here)
IMPORTANT: Reference the above conversation naturally. Don't mention names that weren't discussed.
```

### Anti-Hallucination

**Problem:** A.R.C.H.I.E. sometimes mentioned names/people not in the conversation.

**Solution:** Explicit constraint added when conversation history is present:
```
"IMPORTANT: Reference the above conversation naturally.
Don't mention names that weren't discussed."
```

This prevents A.R.C.H.I.E. from hallucinating information not actually in the context.

### Example Conversation

**First Message:**
```
User: "I need help with the authentication system"
A.R.C.H.I.E.: "I can help with that! Let me connect you with our Engineering team..."
```

**Second Message (same session):**
```
User: "Also, make sure error handling is improved"
A.R.C.H.I.E.: "Noted! I'll make sure the Engineering team addresses both
the authentication system and improves error handling in that area."
```

A.R.C.H.I.E. remembers the "authentication system" from the previous message!

### Clearing History

**Manually:**
```javascript
// Frontend
fetch('/tools/improvements-lab//chat/clear', { method: 'POST' });
```

**Programmatically:**
```python
# Backend
session_key = f'archie_conversation_{current_user.id}'
if session_key in session:
    del session[session_key]
```

**When History is Cleared:**
- User manually clears via UI
- Session expires
- User logs out
- Server restart (session data is lost)

### Performance

- **Memory Overhead:** 10ms per request (session retrieval)
- **Storage:** Minimal (last 10 messages only)
- **Scalability:** Session-based, scales with user sessions

### Future Enhancements

Planned improvements for conversation memory:

1. **Database Persistence**
   - Store conversations in database instead of session
   - Survive server restarts
   - Allow viewing past conversations

2. **Conversation Search**
   - Search through conversation history
   - Find when specific topics were discussed

3. **Smart Context Selection**
   - Include only relevant parts of conversation
   - Reduce token usage while maintaining context

4. **Cross-Session Memory**
   - Remember important facts across sessions
   - "Last time we talked about X..."

---

## ✅ Summary

**What Changed:**
- ❌ Before: Immediate delegation to specialist agents
- ✅ Now: A.R.C.H.I.E. responds first, only delegates when needed

**Benefits:**
- ⚡ Faster responses for simple interactions
- 🤝 Personal bond with Kytran and team
- 💰 Cost savings (uses FREE local model first)
- 🎯 Better user experience
- 📈 Relationship tracking and improvement

**Test It:**
1. Say "hey archie" - Should get instant personal greeting
2. Ask "what's new" - Should get quick status update
3. Ask complex question - Should introduce specialist then provide answer

---

**Last Updated:** December 31, 2025
**Version:** 3.1 - Personality System + Conversation Memory
**Status:** Production Ready 🚀
