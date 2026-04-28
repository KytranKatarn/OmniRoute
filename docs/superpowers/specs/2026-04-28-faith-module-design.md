# Faith Module Design

**Goal:** A spiritual care module pairing F.A.I.T.H. (AI) with Emmanuel Adeyemi (human chaplain) — conversational faith companion, structured spiritual practices, personal journal, and chaplaincy escalation.

**Architecture:** Follows Therapy/Fitness/Doc pattern. `tools/faith/routes.py` (thin handlers) + Bridge dispatch to F.A.I.T.H. (agent_id=352). Emmanuel's voice woven into F.A.I.T.H.'s system context; escalation via email. 4 new DB tables, 12 routes, 3-tab LCARS UI.

**Tech Stack:** Flask Blueprint, Bridge dispatch (archie_bridge + bridge_dispatch fallback), PostgreSQL, mistral:7b (F.A.I.T.H.), Stalwart mail for chaplain email.

---

## Agents

### F.A.I.T.H. (id=352)
- **Role:** AI faith companion — scripture-grounded, all Christian traditions (Catholic, Orthodox, Protestant, Evangelical, Pentecostal, Anglican, Baptist)
- **Model:** `mistral:7b`
- **Department:** Medical & Wellness
- **System prompt addition:** Inject Emmanuel Adeyemi's chaplain voice into context — every response pairs AI depth with pastoral warmth

### Emmanuel Adeyemi (id=360)
- **Role:** Human Spiritual Care Coordinator & Chaplain
- **Integration:** Inline "From the Chaplain" notes appended to F.A.I.T.H. responses (short pastoral reflection drawn from his bio/training) + escalation path for direct contact
- **Escalation:** `POST /api/faith/connect-chaplain` → sends email to `emmanuel@kytranempowerment.com` via Stalwart mail

---

## Module Structure

```
platform_v2/tools/faith/
├── __init__.py
├── routes.py
└── templates/tools/faith.html
```

Blueprint: `faith_bp` registered in `module_registry.py` + `rbac.py` under `applications_concepts`.

---

## UI — 3 Tabs

### Tab 1: Chat
- Chat interface with F.A.I.T.H. (open conversation — scripture questions, theological doubt, prayer, life situations)
- Every AI response includes an inline **"From the Chaplain"** block — a short Emmanuel-voiced pastoral note
- **"Connect with Emmanuel"** button at bottom — opens a compose modal → sends email to Emmanuel
- Crisis detection: keyword scan on user messages → if despair/hopelessness/suicidal ideation detected → surface Emmanuel escalation + Telegram alert

### Tab 2: Practices
Five structured activities (each triggers F.A.I.T.H. to generate/guide, logs to `faith_practices_log`):

| Practice | Description |
|----------|-------------|
| Daily Devotional | Scripture + reflection prompt generated fresh each day |
| Guided Prayer | Step-by-step: thanksgiving → confession → intercession → lament |
| Scripture Search | Topic/emotion/situation query → relevant verses + context |
| Lectio Divina | Four-step slow reading: Lectio → Meditatio → Oratio → Contemplatio |
| Faith Check-In | 1–5 spiritual wellbeing score + open reflection → logged to `faith_checkins` |

### Tab 3: Journal
- Personal spiritual journal (per-user, private)
- Create entries with: title, body, scripture_ref (optional), tags (prayer / reflection / gratitude / doubt / other)
- Past entries listed with date and tag filter
- Journal entries optionally shareable to "Connect with Emmanuel" as context

---

## Routes

| Method | Path | What |
|--------|------|------|
| GET | `/tools/faith` | Module main page |
| GET | `/api/faith/status` | F.A.I.T.H. agent + model status |
| POST | `/api/faith/chat` | Open conversation (session history saved) |
| GET | `/api/faith/devotional` | Today's devotional (generated, cached per day) |
| POST | `/api/faith/prayer` | Guided prayer session |
| POST | `/api/faith/scripture-search` | Scripture search by topic/emotion |
| POST | `/api/faith/lectio` | Lectio divina guided reading |
| POST | `/api/faith/checkin` | Save faith check-in (score + reflection) |
| GET | `/api/faith/checkin/history` | Past check-in records |
| POST | `/api/faith/journal` | Save journal entry |
| GET | `/api/faith/journal` | List journal entries (with tag filter) |
| POST | `/api/faith/connect-chaplain` | Send message to Emmanuel via email |

---

## Database — Migration 174

```sql
CREATE TABLE faith_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    role VARCHAR(20) NOT NULL,  -- 'user' | 'assistant'
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE faith_journal (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title VARCHAR(255),
    content TEXT NOT NULL,
    scripture_ref VARCHAR(255),
    tags VARCHAR(50)[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE faith_checkins (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    score SMALLINT NOT NULL CHECK (score BETWEEN 1 AND 5),
    reflection TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE faith_practices_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    practice_type VARCHAR(50) NOT NULL,  -- 'devotional' | 'prayer' | 'scripture' | 'lectio' | 'checkin'
    notes TEXT,
    completed_at TIMESTAMPTZ DEFAULT NOW()
);
```

Indexes: `faith_sessions(user_id, created_at)`, `faith_journal(user_id, created_at)`, `faith_checkins(user_id, created_at)`.

---

## Bridge Dispatch Pattern

All LLM calls follow the same dual-dispatch pattern as Therapy/Fitness/Doc:

```python
FAITH_AGENT_ID = 352  # F.A.I.T.H.

# Build context including Emmanuel's chaplain voice
system_context = (
    "You are F.A.I.T.H. answering a faith question. "
    "After your response, append a short 'From the Chaplain' note "
    "in the voice of Emmanuel Adeyemi — a Nigerian-Canadian hospital chaplain "
    "with 15 years of interfaith pastoral care. One or two sentences only. "
    "Ground it in lived experience, not theology."
)

result = archie_bridge(
    prompt=user_message,
    user_id=user_id,
    agent_id=FAITH_AGENT_ID,
    system_prompt=system_context,
    enable_memory=True,
    try_local_first=True,
    task_type="faith_companion",
)
```

---

## Crisis Detection

Keyword list (same approach as Therapy): `["can't go on", "no reason to live", "hopeless", "God has abandoned", "ending it", "worthless"]`

On detection:
1. F.A.I.T.H. response includes Emmanuel escalation prompt
2. Telegram alert sent to Kytran via `send_system()`
3. Crisis Text Line / 988 surfaced in UI (same as Therapy)

---

## Emmanuel Email Escalation

`POST /api/faith/connect-chaplain` payload: `{ message, context (optional journal entry IDs) }`

- Sends from `faith@kytranempowerment.com` → `emmanuel@kytranempowerment.com`
- Subject: `Spiritual Care Request — [user display name]`
- Body includes user's message + any shared journal context
- Uses existing `send_email` service (Stalwart relay)

---

## Registration

`module_registry.py`:
```python
{
    "id": "faith",
    "name": "Faith",
    "description": "Spiritual care companion — F.A.I.T.H. + Emmanuel Adeyemi chaplain",
    "icon": "cross",
    "category": "applications_concepts",
    "url": "/tools/faith",
    "blueprint": "faith_bp",
    "status": "enabled",
}
```

`rbac.py`: add `faith` to `APPLICATIONS` permission group.
