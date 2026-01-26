# Lean Staffing Matrix

**Module:** Team Management
**Phase:** 28 - Consciousness Optimization & Admin Ops Integration
**Status:** Active

---

## Overview

The Lean Staffing approach ensures A.R.C.H.I.E. operates with minimal viable agent staffing while maintaining full station coverage and contractor failover capabilities.

## Staffing Philosophy

- **1 Primary + 1 Backup per Station** (20 internal agents minimum)
- **Contractors as Failover** (not station-assigned, used after 3 failed attempts)
- **Standby Agents** (preserved for future use, can be reactivated)

---

## Current Station Assignments

| Station | Primary Agent | Backup Agent | Department |
|---------|--------------|--------------|------------|
| **Command** | A.R.C.H.I.E. | General Assistant | Executive Leadership |
| **Consciousness** | Knowledge Curator | Learning Synthesizer | Knowledge Management |
| **HR** | HR Assistant | Compliance Analyst | Human Resources |
| **R&D** | QA Engineer | Code Reviewer | Quality Assurance |
| **Operations** | Operations Coordinator | Financial Analyst | Operations |
| **Engineering** | DevOps Engineer | CodeLlama Specialist | Engineering |
| **Creative** | Creative Content Innovator | Documentation Specialist | Marketing |
| **Security** | Security Analyst | Infrastructure Engineer | Security |
| **Medical** | Health Advisor | Wellness Coach | Healthcare |
| **Away Team** | BD Strategy Analyst | Success Coordinator | Business Development |

---

## Agent Status Categories

### Active (20 Internal)
Agents assigned to bridge stations with active shift schedules.

### Standby (22 Internal)
Unassigned agents preserved for future use. Can be reactivated when needed.

### Contract (36)
External AI providers (Claude, GPT, Grok, Gemini, etc.) available for:
- Escalation after 3 failed internal attempts
- Specialized tasks requiring specific capabilities
- Peak load handling

### Human (1)
Kytran - Executive Leadership oversight

---

## Contractor Failover Logic

When an internal agent fails a task 3 times:

1. **Attempt 1-3:** Same internal agent retries with refined instructions
2. **Escalation:** Task routes to contractor pool
3. **Contractor Selection:** Based on task type and model capabilities:
   - Code tasks: Claude Code Developer, ChatGPT Code Specialist
   - Creative tasks: ChatGPT Creative Specialist
   - General tasks: Grok General Assistant
   - Medical queries: Grok Medical Advisor

### Implementation
See `/mnt/archie_brain/docs/IMPROVEMENT_WORKFLOW_RETRY_ESCALATION.md`

---

## Staffing Metrics

### Coverage Targets
- **100%** Station Coverage (all 10 stations have primary + backup)
- **<30** Active Internal Agents (lean operation)
- **3** Retry Attempts before contractor escalation

### Current Status
```
Active Internal:  20  (target: 20-30)
Standby Internal: 22  (preserved for future)
Active Contracts: 36  (failover pool)
Total Coverage:   100%
```

---

## Database Queries

### View Current Staffing
```sql
SELECT
    bs.station_name,
    a.name as agent_name,
    sa.assignment_type,
    a.status
FROM bridge_stations bs
LEFT JOIN station_assignments sa ON bs.id = sa.station_id AND sa.is_active = true
LEFT JOIN agents a ON sa.agent_id = a.id
ORDER BY bs.id, sa.assignment_type;
```

### Count by Status
```sql
SELECT status, worker_type, COUNT(*) as count
FROM agents
GROUP BY status, worker_type
ORDER BY status, worker_type;
```

### Find Unassigned Agents
```sql
SELECT id, name, department FROM agents
WHERE worker_type = 'internal'
  AND status = 'active'
  AND id NOT IN (SELECT agent_id FROM station_assignments WHERE is_active = true);
```

---

## Reactivating Standby Agents

To bring a standby agent back to active status:

```sql
-- 1. Reactivate the agent
UPDATE agents SET status = 'active' WHERE id = <agent_id>;

-- 2. Assign to a station
INSERT INTO station_assignments (station_id, agent_id, assignment_type, priority, is_active)
VALUES (<station_id>, <agent_id>, 'backup', 2, true);
```

---

## Station Responsibilities

### Command
- Main A.R.C.H.I.E. interface
- Personality and decision routing
- General chat handling

### Consciousness
- Memory management
- Knowledge curation
- Learning synthesis

### HR
- Team management
- Ethics oversight
- Compliance monitoring

### R&D
- Code review
- Testing
- Improvements Lab

### Operations
- CRM, Invoicing, Scheduler
- Financial operations
- Customer support

### Engineering
- Project Builder
- Code Editor
- DevOps tasks

### Creative
- Content creation
- Documentation
- Marketing

### Security
- Backup management
- Infrastructure
- Access control

### Medical
- Wellness modules
- Health advice
- Therapy support

### Away Team
- Web research
- External discovery
- Business development

---

## Related Documentation

- [Shift Scheduler Guide](SHIFT_SCHEDULER_GUIDE.md)
- [Bridge Station Architecture](BRIDGE_STATION_ARCHITECTURE.md)
- [Agent Delegation System](AGENT_DELEGATION_SYSTEM.md)
- [Improvement Workflow Retry Escalation](IMPROVEMENT_WORKFLOW_RETRY_ESCALATION.md)

---

**Last Updated:** 2026-01-17 (Phase 28)
