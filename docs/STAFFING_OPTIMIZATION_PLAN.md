# A.R.C.H.I.E. Staffing Optimization Plan

**Date**: January 20, 2026
**Status**: Ready for Review
**Goal**: Optimize staffing to prioritize LOCAL LLMs and establish 7 Contract Workers for external APIs

---

## Current State Analysis

### Agent Distribution by Model Type

| Model Type | Count | Percentage | Status |
|------------|-------|------------|--------|
| **LOCAL (Ollama)** | 20 | 34.5% | Should be PRIMARY |
| **External API** | 37 | 63.8% | Should be CONTRACTORS only |
| **Human** | 1 | 1.7% | Kytran (Fixed) |

### External API Usage (EXPENSIVE)
- claude-sonnet-4: 24 agents
- claude-opus-4: 7 agents
- gpt-4/gpt-4o: 2 agents
- grok-beta: 3 agents

### Available Local LLMs (16 models)
```
MODEL                    SIZE     BEST FOR
-------------------------------------------------
deepseek-coder-v2:16b    8.9 GB   Code, Engineering
deepseek-coder:33b       18 GB    Complex Code
codellama:latest         3.8 GB   Code Generation
qwen2.5-coder:7b         4.7 GB   Code, Operations
mixtral:8x7b             26 GB    General, Analysis
command-r:latest         18 GB    RAG, Documentation
llama3.1:8b              4.9 GB   General Tasks
llama3:latest            4.7 GB   General Tasks
mistral:latest           4.4 GB   General Tasks
nous-hermes2:latest      6.1 GB   Reasoning, Medical
dolphin3:latest          4.9 GB   Creative, Uncensored
phi3:mini                2.2 GB   Quick Tasks
gemma2:2b                1.6 GB   Light Tasks
aya:8b                   4.8 GB   Multilingual
deepseek-coder:latest    776 MB   Quick Code
deepseek-coder-v2:latest 8.9 GB   Code (alias)
```

---

## Proposed Staffing Structure

### 1. Bridge Station Assignments (Primary + Backup)

| Station | Department Focus | Primary Agent | Primary LLM | Backup Agent | Backup LLM |
|---------|------------------|---------------|-------------|--------------|------------|
| **COMMAND** | Executive Leadership | A.R.C.H.I.E. (Fixed) | deepseek-coder-v2:16b | Kytran (Fixed) | human |
| **CONSCIOUSNESS** | Knowledge Management | Knowledge Curator | deepseek-coder-v2:16b | Learning Synthesizer | deepseek-coder-v2:16b |
| **HR** | Human Resources + Ethics | ATHENA | deepseek-coder-v2:16b | HR Assistant | llama3.1:8b |
| **R&D** | Engineering + QA | Solutions Architect | deepseek-coder:33b | Code Reviewer | deepseek-coder-v2:16b |
| **OPERATIONS** | Operations + Finance | Operations Coordinator | deepseek-coder-v2:16b | Financial Analyst | mixtral:8x7b |
| **ENGINEERING** | Engineering + Infra | DevOps Engineer | deepseek-coder-v2:16b | CodeLlama Specialist | codellama:latest |
| **CREATIVE** | Marketing + Content | Creative Content Innovator | dolphin3:latest | Content Writer | mistral:latest |
| **SECURITY** | Security + Compliance | Security Analyst | deepseek-coder:33b | Compliance Analyst | deepseek-coder-v2:16b |
| **MEDICAL** | Healthcare + Wellness | Wellness Coach | nous-hermes2 | Health Advisor | llama3.1:8b |
| **AWAY_TEAM** | Sales + BD + Support | BD Strategy Analyst | llama3.1:8b | Success Coordinator | nous-hermes2 |

### 2. Contract Workers (7 External API Agents)

These are GENERIC agents for tasks requiring external API capabilities:

| Contract Worker | Provider | Model | Specialty |
|-----------------|----------|-------|-----------|
| **ChatGPT Contractor** | OpenAI | gpt-4o | Code Generation, Analysis |
| **Claude Contractor** | Anthropic | claude-sonnet-4 | Complex Reasoning, Writing |
| **Gemini Contractor** | Google | gemini-pro | Research, Multimodal |
| **CoPilot Contractor** | Microsoft | copilot | Code Assistance |
| **Deepseek Contractor** | Deepseek | deepseek-chat | Code, Chinese Markets |
| **Grok Contractor** | xAI | grok-beta | Real-time Info, X Integration |
| **Perplexity Contractor** | Perplexity | pplx-online | Web Research, Citations |

### 3. Department-to-Station Mapping

| Department | Primary Station | Secondary Station |
|------------|-----------------|-------------------|
| Administration | OPERATIONS | COMMAND |
| Business Development | AWAY_TEAM | OPERATIONS |
| Compliance | SECURITY | HR |
| Customer Success | AWAY_TEAM | OPERATIONS |
| Customer Support | AWAY_TEAM | MEDICAL |
| Documentation | CONSCIOUSNESS | R&D |
| Engineering | ENGINEERING | R&D |
| Ethics & Governance | HR | COMMAND |
| Executive Leadership | COMMAND | - |
| Finance | OPERATIONS | SECURITY |
| General | OPERATIONS | AWAY_TEAM |
| Healthcare | MEDICAL | HR |
| Human Resources | HR | COMMAND |
| Infrastructure | ENGINEERING | SECURITY |
| Knowledge Management | CONSCIOUSNESS | R&D |
| Legal | SECURITY | HR |
| Marketing | CREATIVE | AWAY_TEAM |
| Operations | OPERATIONS | COMMAND |
| Product | R&D | OPERATIONS |
| Quality Assurance | R&D | ENGINEERING |
| Sales | AWAY_TEAM | OPERATIONS |
| Security | SECURITY | ENGINEERING |
| Wellness | MEDICAL | HR |

---

## Migration Plan

### Phase 1: Reassign Agents to Local LLMs

Update 37 agents currently on external APIs to use local Ollama models:

```sql
-- Example reassignments (grouped by specialty)

-- Engineering/Code agents -> deepseek-coder-v2:16b or codellama
UPDATE agents SET model = 'deepseek-coder-v2:16b' WHERE department = 'Engineering' AND model LIKE 'claude%';

-- Operations agents -> qwen2.5-coder:7b or mixtral:8x7b
UPDATE agents SET model = 'qwen2.5-coder:7b' WHERE department = 'Operations' AND model LIKE 'claude%';

-- Marketing/Creative agents -> dolphin3:latest or mistral:latest
UPDATE agents SET model = 'dolphin3:latest' WHERE department = 'Marketing' AND model LIKE 'claude%';

-- General/Admin agents -> llama3.1:8b or mistral:latest
UPDATE agents SET model = 'llama3.1:8b' WHERE department = 'Administration' AND model LIKE 'claude%';
```

### Phase 2: Create 7 Contract Worker Agents

```sql
INSERT INTO agents (name, model, department, title, tier, status, capabilities, system_prompt)
VALUES
('ChatGPT Contractor', 'gpt-4o', 'Contract Workers', 'External Code Specialist', 4, 'active', '["code_generation","analysis","api_integration"]', 'You are a contract worker for A.R.C.H.I.E. platform...'),
('Claude Contractor', 'claude-sonnet-4-20250514', 'Contract Workers', 'External Reasoning Specialist', 4, 'active', '["complex_reasoning","writing","analysis"]', '...'),
('Gemini Contractor', 'gemini-pro', 'Contract Workers', 'External Research Specialist', 4, 'active', '["research","multimodal","analysis"]', '...'),
('CoPilot Contractor', 'copilot', 'Contract Workers', 'External Code Assistant', 4, 'active', '["code_completion","ide_integration"]', '...'),
('Deepseek Contractor', 'deepseek-chat', 'Contract Workers', 'External Code Specialist', 4, 'active', '["code_generation","chinese_market"]', '...'),
('Grok Contractor', 'grok-beta', 'Contract Workers', 'External Info Specialist', 4, 'active', '["real_time_info","x_integration"]', '...'),
('Perplexity Contractor', 'pplx-online', 'Contract Workers', 'External Research Specialist', 4, 'active', '["web_research","citations"]', '...');
```

### Phase 3: Assign All Stations (Primary + Backup)

```sql
-- Clear existing assignments and reassign
DELETE FROM station_assignments WHERE station_id != 1; -- Keep COMMAND

-- Insert new assignments for all stations
INSERT INTO station_assignments (station_id, agent_id, assignment_type, priority, is_active)
SELECT bs.id, a.id, 'primary', 1, TRUE
FROM bridge_stations bs
CROSS JOIN agents a
WHERE (bs.station_code = 'CONSCIOUSNESS' AND a.name = 'Knowledge Curator')
   OR (bs.station_code = 'HR' AND a.name = 'ATHENA')
   OR (bs.station_code = 'R&D' AND a.name = 'Solutions Architect')
   -- etc.
```

### Phase 4: Update LLM Routing

Move LLM Connections Monitor from Bridge to Team Management module.

---

## LLM Assignment Strategy by Role

| Role Type | Recommended Local LLM | Reason |
|-----------|----------------------|--------|
| **Code/Engineering** | deepseek-coder-v2:16b | Best code generation |
| **Complex Code** | deepseek-coder:33b | Larger context, complex logic |
| **Quick Code** | codellama:latest | Fast, lightweight |
| **Operations/Business** | qwen2.5-coder:7b | Good balance |
| **Analysis/Reasoning** | mixtral:8x7b | Strong reasoning |
| **Creative/Marketing** | dolphin3:latest | Uncensored creativity |
| **Documentation** | command-r:latest | Great for RAG |
| **General Tasks** | llama3.1:8b | Versatile |
| **Medical/Wellness** | nous-hermes2 | Thoughtful responses |
| **Quick Tasks** | phi3:mini | Fast, low resource |
| **Multilingual** | aya:8b | Multi-language support |

---

## Expected Benefits

1. **Cost Reduction**: 90%+ reduction in API costs by using local LLMs
2. **Speed**: Local LLMs have lower latency (no network roundtrip)
3. **Privacy**: Data stays local, not sent to external APIs
4. **Availability**: No dependency on external API uptime
5. **Full Coverage**: All 10 stations staffed with Primary + Backup
6. **Flexibility**: Contract workers available for specialized tasks

---

## Implementation Checklist

- [ ] Review and approve this plan
- [ ] Run Phase 1: Reassign agents to local LLMs
- [ ] Run Phase 2: Create 7 contract worker agents
- [ ] Run Phase 3: Assign all stations (Primary + Backup)
- [ ] Run Phase 4: Move LLM Monitor to Team Management
- [ ] Test all modules (Bridge, Team Management)
- [ ] Update documentation

---

## Questions for Review

1. Should we keep some high-tier agents on external APIs for critical tasks?
2. Are the department-to-station mappings correct?
3. Should contract workers be visible in the Bridge or only in Team Management?
4. Do we need after-hours staffing rotation?

---

*Generated: 2026-01-20*
