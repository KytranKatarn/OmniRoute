---
name: archie-bridge-agent
description: How to create and register new AI agents in the A.R.C.H.I.E. Bridge system
---

# Creating Bridge Agents

## Database Registration
```sql
INSERT INTO agents (name, display_name, station_code, role, personality, llm_model, status, is_active)
VALUES ('agent_code', 'Display Name', 'STATION', 'Role Title', 'Personality description', 'model:tag', 'active', true);
```

## Station Codes
COMMAND, ANALYTICS, CREATIVE, ENGINEERING, COMMUNICATIONS, RESEARCH, SECURITY, LOGISTICS, DIPLOMATIC, OPERATIONS

## Dispatch Pattern
```python
from ai_bridge.archie_bridge import archie_bridge as ai_bridge
result = ai_bridge(prompt=message, system_prompt=system_prompt, user_id=user_id, enable_memory=False)
response = result.get('response', '') if isinstance(result, dict) else str(result)
```

## Multi-Agent Pattern
Use threading.Thread for parallel dispatch, collect results, feed to synthesizer agent.
