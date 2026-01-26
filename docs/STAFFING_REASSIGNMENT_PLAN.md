# Staffing Reassignment Plan

**Date:** 2026-01-20
**Status:** PLANNING - Awaiting Approval
**Goal:** Assign all 27 internal unassigned agents to appropriate stations/modules

---

## Current State Analysis

### Summary
| Metric | Count |
|--------|-------|
| Total Active Agents | 65 |
| Assigned to Stations | 35 |
| Unassigned (internal) | 27 |
| Unassigned (contractors) | 7 (CORRECT - for escalation) |

### Problem Areas

1. **MEDICAL Station** - Only 2 agents (Wellness Coach, Health Advisor) cover ALL standalone apps:
   - doc (medical documentation)
   - therapy (mental health)
   - fitness (physical health)
   - **ISSUE:** Same person for therapy and fitness is inefficient

2. **27 Internal Agents Unassigned** - Not contributing to any module

3. **Departments with Zero Station Coverage:**
   - Sales (3 agents)
   - Legal (1 agent)
   - Product (1 agent)

---

## Proposed Station/Module Expansion

### Option A: Expand Existing Stations

| Station | Current Modules | Add Modules | Assign Agents |
|---------|-----------------|-------------|---------------|
| MEDICAL | doc, therapy, fitness | - | Split: 1 per app |
| FINANCE | stockbot, analytics | legal_docs | Tax Assistant, Legal Advisor |
| CREATIVE | media_studio, content_studio, social_media | - | 5 Marketing agents |
| OPERATIONS | crm, invoicing, scheduler, email, automations | sales_dashboard | 3 Sales + 3 Ops agents |
| ENGINEERING | project_builder, website, code_editor, game | - | 2 Code specialists |
| INFRASTRUCTURE | network, server, home_auto | - | 2 Infra specialists |
| HR | team_management, hr_management | - | HR Manager, Data Privacy |
| SECURITY | backup, security, account | compliance_dashboard | Security Specialist |
| RND | blueprint, improvements, sandbox | product_roadmap | Product Manager |

### Option B: Create New Specialized Stations

| New Station | Modules | Agents to Assign |
|-------------|---------|------------------|
| SALES | crm, sales_dashboard (new) | 3 Sales agents |
| LEGAL | legal_docs (new), compliance | Legal Advisor, Data Privacy |
| PRODUCT | product_roadmap (new), improvements | Product Manager |
| THERAPY | therapy | Wellness Therapist (River) |
| FITNESS | fitness | Health specialist |

---

## Detailed Reassignment Plan

### Phase 1: Standalone Apps (MEDICAL Station Split)

**Current:** MEDICAL has Chris Taylor (Wellness Coach) + Dr. Lisa (Health Advisor)

**Problem:** Same 2 people for doc, therapy, fitness

**Solution:** Add specialists from unassigned pool:

| App | Current | Add Agent | Rationale |
|-----|---------|-----------|-----------|
| doc | Chris Taylor | Dr. Amara - Medical Advisor | Healthcare dept, medical focus |
| therapy | Chris Taylor | River - Wellness Therapist | Wellness dept, therapy focus |
| fitness | Dr. Lisa | Keep as is | Health Advisor fits |

**SQL:**
```sql
-- Add Medical Advisor to MEDICAL station for 'doc' app
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active)
SELECT bs.id, 36, 'primary', true FROM bridge_stations bs WHERE bs.station_code = 'MEDICAL';

-- Add Wellness Therapist to MEDICAL station for 'therapy' app
INSERT INTO station_assignments (station_id, agent_id, assignment_type, is_active)
SELECT bs.id, 37, 'primary', true FROM bridge_stations bs WHERE bs.station_code = 'MEDICAL';
```

### Phase 2: Marketing Expansion (CREATIVE Station)

**Current:** 2 agents (Liam, Jordan)
**Unassigned:** 5 Marketing agents

| Agent | Role | Assign As |
|-------|------|-----------|
| Maya - Social Media Manager | Social strategy | primary (social_media) |
| Sienna - Social Media Expert | Content creation | backup (social_media) |
| Luna - Creative Specialist | Creative content | backup (content_studio) |
| Phoenix - Visual Content | Graphics/video | backup (media_studio) |
| Jayden - Community Manager | Community engagement | backup (all) |

### Phase 3: Sales Coverage (OPERATIONS or New Station)

**Unassigned:** 3 Sales agents
- Sarah - Sales Agent Tier 1
- Marcus - Sales Agent Tier 2
- Priya - Account Manager

**Option A:** Add to OPERATIONS (has CRM module)
**Option B:** Create SALES station with new sales_dashboard module

**Recommendation:** Option A - Add to OPERATIONS since CRM is sales-related

### Phase 4: HR & Compliance

**Current HR Station:** ATHENA (Ethics) + Michael (HR Assistant)
**Unassigned:**
- Isabella - HR Manager (should be primary!)
- Priya - Data Privacy Officer (Compliance)

**Solution:**
- Make Isabella HR Manager the PRIMARY on HR station
- Add Data Privacy Officer to HR or SECURITY

### Phase 5: Engineering & Infrastructure

**ENGINEERING Unassigned:**
- Dr. Alexis - Senior Developer
- Morgan - Code Specialist

**INFRASTRUCTURE Unassigned:**
- Jordan - Home Assistant Specialist
- Morgan - Network Monitoring Specialist

**Solution:** Add as backups to their respective stations

### Phase 6: Remaining Agents

| Agent | Department | Assign To | Role |
|-------|------------|-----------|------|
| Cameron - Travel Coordinator | Admin | ADMIN | backup |
| Nathan - Contracts Specialist | BD | AWAY_TEAM | backup |
| Victoria - Operations Lead | Ops | OPERATIONS | primary |
| David - Project Manager | Ops | RND | backup |
| Alex - Shipping Coordinator | Ops | OPERATIONS | backup |
| Sophia - Tax Assistant | Finance | FINANCE | backup |
| Rebecca - Legal Advisor | Legal | SECURITY | backup |
| Devon - Security Specialist | Security | SECURITY | backup |
| Marcus - Product Manager | Product | RND | backup |
| Riley - General Assistant | General | ADMIN | backup |
| Phoenix - General Assistant | General | SUPPORT | backup |

---

## After Reassignment Summary

| Station | Before | After | Modules |
|---------|--------|-------|---------|
| ADMIN | 3 | 5 | admin_tools, general_tasks |
| AWAY_TEAM | 2 | 3 | web_scraper, research, data_collector |
| COMMAND | 2 | 2 | archie_chat |
| CONSCIOUSNESS | 2 | 2 | consciousness |
| CREATIVE | 2 | 7 | media_studio, content_studio, social_media |
| DOCUMENTATION | 2 | 2 | docs_manager, technical_writing |
| ENGINEERING | 2 | 4 | project_builder, website, code_editor, game |
| FINANCE | 2 | 3 | stockbot, analytics |
| HR | 2 | 4 | team_management, hr_management |
| INFRASTRUCTURE | 2 | 4 | network, server, home_automation |
| MEDICAL | 2 | 4 | doc, therapy, fitness |
| OPERATIONS | 2 | 8 | crm, invoicing, scheduler, email, automations |
| QA | 2 | 2 | qa_dashboard, test_runner |
| RND | 2 | 4 | blueprint, improvements, sandbox |
| SECURITY | 2 | 5 | backup, security, account |
| SUPPORT | 4 | 5 | call_center, store_builder |

**Total Assigned:** 62 (was 35)
**Contractors (correctly unassigned):** 7

---

## Questions for Approval

1. **SALES:** Create new SALES station or add to OPERATIONS?
2. **LEGAL:** Create new LEGAL station or add Legal Advisor to SECURITY?
3. **Standalone Apps:** Should doc/therapy/fitness each have dedicated primary agents?
4. **New Modules Needed:** Should we create placeholder modules for:
   - sales_dashboard
   - legal_docs
   - product_roadmap
   - compliance_dashboard

---

## Execution Checklist

- [ ] Approve station assignments
- [ ] Run SQL to add agents to stations
- [ ] Update bridge_stations modules array if needed
- [ ] Create placeholder modules if approved
- [ ] Verify in Bridge UI
- [ ] Update documentation
- [ ] Commit changes
