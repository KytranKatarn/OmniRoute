# A.R.C.H.I.E. n8n Workflow Collection

This directory contains sample n8n workflows for the AI Call Handler System with A.R.C.H.I.E. integration.

## Workflows Overview

### 1. Master Call Handler (`01_master_call_handler.json`)
**Purpose**: Central routing system for all incoming calls

**Features**:
- Webhook endpoint for incoming call notifications
- Extracts call data (CallSid, From, To, Provider)
- Creates conversation record in database
- Routes calls based on intent (sales, support, technical, billing)
- Triggers appropriate specialized agent workflow

**Webhook URL**: `http://your-domain:5678/webhook/incoming-call`

**Expected Payload**:
```json
{
  "CallSid": "CA1234567890abcdef",
  "From": "+15551234567",
  "To": "+15559876543",
  "provider": "twilio",
  "intent": "sales"
}
```

---

### 2. Sales Agent - Tier 1 (`02_sales_agent_tier1.json`)
**Purpose**: Handles sales inquiries using Claude API

**Features**:
- Assigns Tier 1 Sales Agent to conversation
- Retrieves customer history and purchase data
- Searches A.R.C.H.I.E. knowledge base for product information
- Generates contextual sales response using Claude 3.5 Sonnet
- Logs all conversation turns to database
- Automatically escalates complex inquiries to Tier 2
- Creates escalation records when needed

**Integration Points**:
- Claude API (Anthropic)
- A.R.C.H.I.E. /search endpoint
- PostgreSQL database

---

### 3. Support Agent - Tier 1 (`03_support_agent_tier1.json`)
**Purpose**: Handles customer support using A.R.C.H.I.E. local LLM

**Features**:
- Assigns Tier 1 Support Agent to conversation
- Retrieves customer profile and tier information
- Fetches recent support ticket history (last 3 tickets)
- Searches A.R.C.H.I.E. support knowledge base
- Builds comprehensive context from customer history + KB
- Uses A.R.C.H.I.E. local model for responses (cost-effective)
- Confidence-based escalation logic (escalates if confidence < 0.6)
- Creates escalations to Tier 2/3 when needed

**Integration Points**:
- A.R.C.H.I.E. /search endpoint
- A.R.C.H.I.E. /chat endpoint (local model)
- PostgreSQL database

---

### 4. Agent Learning Pipeline (`04_agent_learning_pipeline.json`)
**Purpose**: Continuous learning system that processes completed conversations

**Features**:
- Scheduled execution every 15 minutes
- Identifies completed conversations from last 15 minutes
- Excludes already-processed conversations (checks long_term_memory)
- Processes conversations in batches of 5
- Retrieves full conversation transcripts
- Analyzes conversations using Claude for insights:
  - What worked well
  - Areas for improvement
  - Common customer pain points
  - Effective response patterns
  - Knowledge gaps
- Feeds insights to A.R.C.H.I.E. /learn endpoint
- Updates agent performance metrics (avg satisfaction, resolution rate, etc.)
- Flags low-satisfaction calls (≤2 stars) for quality review

**Integration Points**:
- Claude API for conversation analysis
- A.R.C.H.I.E. /learn endpoint
- PostgreSQL database (conversations, agent_performance, quality_reviews)

---

## Setup Instructions

### 1. Access n8n Interface
```bash
# n8n is running at:
http://localhost:5678

# Default credentials (if basic auth enabled):
# Username: admin
# Password: [check docker-compose.yml]
```

### 2. Import Workflows

1. Open n8n web interface
2. Click "Workflows" in sidebar
3. Click "Import from File" button
4. Select each `.json` file from this directory
5. Import all 4 workflows

### 3. Configure Credentials

You need to set up the following credentials in n8n:

#### PostgreSQL Database
- **Name**: `archie_database`
- **Host**: `archie_database`
- **Database**: `archie_brain`
- **User**: `archie_user`
- **Password**: [from docker-compose.yml]
- **Port**: `5432`

#### A.R.C.H.I.E. API Key
- **Credential Type**: HTTP Header Auth
- **Name**: `archie-api-key`
- **Header Name**: `Authorization`
- **Header Value**: `Bearer YOUR_API_KEY_HERE`

To generate an API key:
```sql
INSERT INTO api_keys (id, user_id, key_hash, name, permissions, created_at, expires_at)
VALUES (
  gen_random_uuid(),
  (SELECT id FROM users WHERE username = 'admin' LIMIT 1),
  crypt('n8n-workflow-key', gen_salt('bf')),
  'n8n Workflow Access',
  '["archie.search", "archie.chat", "archie.learn"]'::jsonb,
  NOW(),
  NOW() + INTERVAL '1 year'
);
```

#### Anthropic API Key (for Claude)
- **Credential Type**: HTTP Header Auth
- **Name**: `anthropic-api-key`
- **Header Name**: `x-api-key`
- **Header Value**: `YOUR_ANTHROPIC_API_KEY`

Get your API key from: https://console.anthropic.com/

### 4. Activate Workflows

1. Open each workflow
2. Click the toggle in top-right to "Active"
3. For webhook workflows, note the webhook URLs shown

### 5. Configure Telephony Provider Webhooks

#### Twilio
In your Twilio console, configure:
- **Voice Webhook URL**: `http://your-domain:5678/webhook/incoming-call`
- **Method**: `POST`

#### TELUS/Telnyx
Configure similar webhook URLs pointing to the Master Call Handler

---

## Testing Workflows

### Test Master Call Handler
```bash
curl -X POST http://localhost:5678/webhook/incoming-call \
  -H "Content-Type: application/json" \
  -d '{
    "CallSid": "TEST123456",
    "From": "+15551234567",
    "To": "+15559876543",
    "provider": "twilio",
    "intent": "sales"
  }'
```

### Test Sales Agent
```bash
curl -X POST http://localhost:5678/webhook/sales-agent \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "YOUR_CONVERSATION_UUID",
    "callSid": "TEST123456",
    "customerPhone": "+15551234567"
  }'
```

### Test Support Agent
```bash
curl -X POST http://localhost:5678/webhook/support-agent \
  -H "Content-Type: application/json" \
  -d '{
    "conversationId": "YOUR_CONVERSATION_UUID",
    "callSid": "TEST123456",
    "customerPhone": "+15551234567"
  }'
```

### View Execution History
1. Open workflow in n8n
2. Click "Executions" tab
3. View detailed execution logs, data flow, and any errors

---

## Workflow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     INCOMING CALL                            │
│                    (Twilio/TELUS/etc)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              01: MASTER CALL HANDLER                         │
│  • Create conversation record                                │
│  • Determine intent (sales/support/technical/billing)        │
│  • Route to appropriate agent workflow                       │
└──────┬────────┬────────┬────────┬─────────────────────────┘
       │        │        │        │
       ▼        ▼        ▼        ▼
   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
   │Sales │ │Support│ │Tech  │ │Billing│
   │Tier1 │ │Tier1  │ │Tier1 │ │Tier1  │
   └───┬──┘ └───┬───┘ └───┬──┘ └───┬───┘
       │        │         │        │
       ▼        ▼         ▼        ▼
   ┌─────────────────────────────────┐
   │  • Search Knowledge Base         │
   │  • Get Customer History          │
   │  • Generate Response (Claude/    │
   │    A.R.C.H.I.E.)                 │
   │  • Log Conversation Turn         │
   │  • Check Escalation Need         │
   └──────────┬──────────────────────┘
              │
              ▼
       ┌─────────────┐
       │ Escalate?   │
       └─────┬───┬───┘
           Yes  No
            │    │
            ▼    ▼
       ┌─────┐  Return
       │Tier2│  Response
       └─────┘

┌─────────────────────────────────────────────────────────────┐
│      04: AGENT LEARNING PIPELINE (Every 15 minutes)          │
│  • Find completed conversations                              │
│  • Analyze with Claude AI                                    │
│  • Extract insights & patterns                               │
│  • Feed learnings to A.R.C.H.I.E.                            │
│  • Update agent performance metrics                          │
│  • Flag poor satisfaction for review                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Features

### Multi-Tier Agent System
- **Tier 1**: Handles common inquiries, uses knowledge base heavily
- **Tier 2**: Handles escalated/complex cases (workflows not included in samples)
- **Tier 3**: Specialist/expert level (workflows not included in samples)

### Hybrid AI Approach
- **Claude API**: Used for sales (needs latest product knowledge, nuanced responses)
- **A.R.C.H.I.E. Local**: Used for support (cost-effective, trained on internal KB)

### Intelligent Escalation
- Keyword-based detection ("escalate", "complex", "specialist")
- Confidence-based (A.R.C.H.I.E. confidence < 0.6)
- Creates escalation records in database
- Maintains escalation chain (Tier 1 → Tier 2 → Tier 3)

### Continuous Learning
- Analyzes every completed conversation
- Extracts successful patterns and failure modes
- Feeds insights back to A.R.C.H.I.E.'s knowledge base
- Tracks agent performance metrics over time
- Quality assurance for low-satisfaction interactions

---

## Monitoring & Administration

### View Active Calls
Check the admin panel:
```
http://localhost:5000/tools/admin
→ BUSINESS → CALL HANDLING → OVERVIEW tab
```

### View Conversations
```
Admin Panel → CALL HANDLING → CONVERSATIONS tab
Filter by: All | Active | Completed | Failed
```

### View Escalations
```
Admin Panel → CALL HANDLING → ESCALATIONS tab
Filter by: Pending | Resolved | All
```

### Database Queries

**Check workflow execution success rate**:
```sql
SELECT
  DATE(started_at) as date,
  COUNT(*) as total_calls,
  COUNT(*) FILTER (WHERE outcome = 'resolved') as resolved,
  COUNT(*) FILTER (WHERE status = 'escalated') as escalated,
  AVG(customer_satisfaction) as avg_satisfaction
FROM conversations
WHERE started_at > NOW() - INTERVAL '7 days'
GROUP BY DATE(started_at)
ORDER BY date DESC;
```

**View agent performance**:
```sql
SELECT
  a.name,
  ap.total_calls,
  ap.successful_resolutions,
  ap.avg_satisfaction,
  ap.avg_duration,
  ROUND(100.0 * ap.successful_resolutions / NULLIF(ap.total_calls, 0), 2) as resolution_rate
FROM agent_performance ap
JOIN agents a ON ap.agent_id = a.id
WHERE ap.period_start >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY ap.total_calls DESC;
```

---

## Extending the Workflows

### Add New Agent Type
1. Duplicate an existing agent workflow (e.g., sales or support)
2. Rename workflow and webhook path
3. Modify system prompt and logic for new intent
4. Add route in Master Call Handler workflow
5. Create corresponding agent in database

### Add Tier 2/3 Agents
1. Create new workflow based on Tier 1 template
2. Add more sophisticated logic (e.g., database queries, external API calls)
3. Update escalation targets in Tier 1 workflows
4. Configure in agent_skills table for proper escalation chain

### Custom Integrations
- Add CRM lookup nodes (Salesforce, HubSpot, etc.)
- Integrate payment systems for billing agent
- Add SMS/Email notification nodes for follow-ups
- Connect to ticketing systems (Jira, Zendesk, etc.)

---

## Troubleshooting

### Webhook Not Triggering
- Check workflow is "Active" (toggle in top-right)
- Verify webhook URL is correct (shown in webhook node)
- Check n8n logs: `docker logs archie_n8n`

### Database Connection Failed
- Verify PostgreSQL credentials in n8n settings
- Ensure `archie_database` container is running
- Check network connectivity (both should be on `archie_internal` network)

### A.R.C.H.I.E. API Errors
- Verify API key is correct in credentials
- Check A.R.C.H.I.E. platform is running: `docker ps | grep archie_platform`
- Test endpoint manually: `curl http://localhost:5000/tools/archie/api/health`

### Claude API Errors
- Verify Anthropic API key is valid
- Check API quota/limits in Anthropic console
- Review rate limiting (Claude has per-minute limits)

---

## Cost Optimization

### When to Use Claude vs A.R.C.H.I.E.

**Use Claude API when**:
- Handling sales (needs persuasive, nuanced language)
- Complex reasoning required
- Latest information needed
- High-value customer interactions

**Use A.R.C.H.I.E. Local when**:
- Standard support queries
- Knowledge base lookups
- High-volume, repetitive interactions
- Cost is a primary concern

### Estimated Costs (per 1000 calls)

**Tier 1 Sales Agent (Claude)**:
- ~1500 tokens per call
- Claude 3.5 Sonnet: $0.003/1k input + $0.015/1k output
- ~$20-30 per 1000 calls

**Tier 1 Support Agent (A.R.C.H.I.E.)**:
- Local inference (no API costs)
- Only infrastructure costs
- ~$0-5 per 1000 calls (compute only)

**Learning Pipeline (Claude)**:
- Runs every 15 min
- ~2000 tokens per conversation analysis
- ~$10-15 per 1000 analyzed conversations

---

## Security Notes

- All workflows use Bearer token authentication for A.R.C.H.I.E. API
- Anthropic API keys should be rotated regularly
- Database credentials should use least-privilege principle
- Webhook endpoints should validate incoming requests
- Consider adding IP whitelisting for production webhooks
- PII/PHI data should be handled according to compliance requirements

---

## Next Steps

1. Import all 4 workflows into n8n
2. Configure credentials (database, A.R.C.H.I.E. API, Anthropic API)
3. Activate Master Call Handler and Learning Pipeline
4. Test with sample webhook calls
5. Monitor execution logs and database records
6. Customize workflows for your specific business needs
7. Create Tier 2 and Tier 3 agent workflows
8. Set up production webhooks with telephony provider

---

## Support

For issues or questions:
- Check n8n documentation: https://docs.n8n.io
- Review execution logs in n8n UI
- Check database logs for SQL errors
- Monitor A.R.C.H.I.E. platform logs: `docker logs archie_platform`
