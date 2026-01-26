# A.R.C.H.I.E. PLATFORM - CANONICAL EXECUTION PLAN

**Version:** 5.0
**Date:** January 6, 2026
**Status:** AUTHORITATIVE REFERENCE
**Author:** Senior Systems Architect (Claude Code)

---

## EXECUTIVE SUMMARY

This document is the **Single Source of Truth** for A.R.C.H.I.E. platform implementation. It reconciles current codebase, documentation, and architectural intent into one unified plan.

**Key Decisions:**
- ✅ "Terminal" → "Dashboard" (terminology standardized)
- ✅ Dashboard = Central control plane with role-based modules
- ✅ Local LLM first (Ollama), self-hostable system
- ✅ App Builder = Flagship module (GPT-Pilot style)
- ✅ Modular architecture with permission-based access

---

## 1. CURRENT STATE AUDIT

### 1.1 What EXISTS ✅

**Infrastructure (Operational)**
```
Flask 3.0.0 + PostgreSQL 16 + Docker Compose
Ollama qwen2.5-coder:7b (local LLM, zero cost)
128 database tables (fully normalized)
Git repository (initialized 2026-01-06)
```

**Dashboard (Main UI) - OPERATIONAL**
- URL: http://192.168.1.200:3000/dashboard
- 3 active tools: A.R.C.H.I.E. Chat, Code Editor, Dashboard
- 9 placeholder tool cards (not implemented)
- Navigation tabs: 6 tabs (1 active, 5 placeholders)

**Admin Modules - OPERATIONAL**
- 73+ AI agents with full profiles
- Self-improvement workflow (v4.0 complete, 19 files, 10,575 lines)
- Consciousness system (long-term memory, knowledge base)
- Backup manager (11-component backups, auto-rollback)
- GitHub integration (basic)

**Cursor IDE Integration ✅ v1.0 COMPLETE (2026-01-06)**
- Git branch isolation (sandbox-proposal-{id})
- Automatic commit detection (<1 second)
- Hybrid knowledge search (30% keyword + 70% semantic, 768-dim embeddings)
- Real-time SSE updates
- 8 new files, 3,000+ lines

**Database: 128 Tables**
- 18+ agent management tables
- 7 consciousness/memory tables
- 7 improvement workflow tables
- 12+ SaaS business tables
- 10+ infrastructure tables

### 1.2 What is PARTIAL 🚧

**Module Skeletons**
- app_builder/ (directory exists, no routes)
- game_builder/ (directory exists, no routes)
- website_builder/ (directory exists, no routes)

**Navigation Issues**
- ADMIN tab not linked to (deprecated - see standalone modules)
- 5 placeholder tabs (no routes)

### 1.3 What is MISSING ❌

**Critical Modules (Not Built)**
1. App Creation Module (Flagship) - GPT-Pilot orchestration
2. Website Builder - Wysiwyg/code editor with deployment
3. Social Media Module - AI content generation + scheduling
4. Figma Integration - Design import and code generation
5. Mining Pool - Dual-use AI/mining architecture
6. RAG Enhancements - Re-ranking, citations, deduplication

**Infrastructure Gaps**
- Module registration system
- Docker execution sandbox
- Design ingestion pipeline
- Real-time collaboration (WebSockets)

### 1.4 Conflicts RESOLVED ✅

- ✅ Terminal → Dashboard standardized
- ✅ Multiple backup systems → Unified Backup Manager
- ✅ Knowledge fragmentation → Hybrid search

### 1.5 Conflicts REMAINING ⚠️

- Website Builder vs Site Manager (overlap in purpose)
- Agent Directory visibility (needs public route for SaaS)

---

## 2. CANONICAL ARCHITECTURE

### 2.1 System Layers (7 Layers)

```
┌─────────────────────────────────────────────────────────┐
│ 1. PRESENTATION LAYER                                   │
│    Dashboard | Dashboard | Study Platform (external)  │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────┐
│ 2. MODULE SYSTEM (Pluggable & Permissioned)             │
│    App Builder | Website Builder | Social Media         │
│    Module Registry + Permission Engine                   │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────┐
│ 3. CORE SERVICES                                         │
│    Auth & RBAC | Logging | Context | Storage (Postgres) │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────┐
│ 4. AI ORCHESTRATION LAYER                                │
│    A.R.C.H.I.E. Consciousness | Agent Manager           │
│    Workflow Orchestrator | Team Assignment               │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────┐
│ 5. LOCAL LLM SERVING                                     │
│    Ollama (qwen) | Embeddings (nomic) | Docker Sandbox  │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────┐
│ 6. KNOWLEDGE & DESIGN INGESTION                          │
│    RAG (hybrid 30/70) | Figma Import | OCR | Search     │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────┴───────────────────────────────┐
│ 7. EXECUTION / SANDBOX LAYER                             │
│    Docker Isolation | Test Runner | Safe Deployment     │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Module Registration (CANONICAL)

**FILE:** `platform_v2/module_registry.py` (TO BE CREATED)

All modules defined in single registry:
- App Builder (flagship, priority 1)
- Website Builder (creation, priority 2)
- Social Media (business, priority 3)
- Code Editor (exists, priority 1)
- Admin Modules (exist, priority 1)
- Mining Pool (infrastructure, priority 4)
- Analytics (infrastructure, priority 3)

Each module has:
- Unique ID, display name, icon, category
- Route, blueprint import path
- Required permissions (list)
- Minimum role (user/premium/admin)
- Health check function
- Enabled flag, beta flag

**Dynamic Registration:** `app.py` imports registry, auto-registers all enabled modules

### 2.3 RBAC Model (CANONICAL)

**FILE:** `platform_v2/rbac.py` (TO BE CREATED)

**Roles (Hierarchical):**
1. PUBLIC (0) - Not logged in
2. USER (10) - Basic authenticated
3. PREMIUM (20) - Paid subscriber
4. ADMIN (90) - Administrator
5. SUPER_ADMIN (100) - System owner

**Permission Mapping:**
- USER: archie:chat, code_editor, read_own, write_own
- PREMIUM: +app_builder, website_builder, social_media
- ADMIN: +admin:access, admin:agents, read_all, write_all
- SUPER_ADMIN: ALL permissions

**Decorator:** `@require_permission(Permission.APP_BUILDER_CREATE)`

---

## 3. MODULE SPECIFICATIONS (CONDENSED)

### 3.1 App Builder (FLAGSHIP)

**Purpose:** Natural language → Full-stack application (GPT-Pilot style)

**Workflow:**
1. **Planning:** Interactive clarification → Detailed plan → User approval
2. **Execution:** Docker sandbox → Git repo → Code generation (backend, frontend, DB)
3. **Testing:** Auto-generated tests → Syntax checks → Health checks
4. **Deployment:** Docker image OR Vercel/Railway → Live URL

**Tech Stack:**
- Orchestrator: Python (Claude Task Master style agent loop)
- Sandbox: Docker (isolated per project)
- Storage: PostgreSQL (app_builder_projects table) + filesystem
- Version Control: Git (auto-initialized)

**API Endpoints:**
- `POST /api/app-builder/create`
- `GET /api/app-builder/status/{id}`
- `POST /api/app-builder/refine/{id}`
- `GET /api/app-builder/download/{id}`
- `POST /api/app-builder/deploy/{id}`

**Permissions:**
- FREE: 1 project/month, 10 files max
- PREMIUM: Unlimited projects, deployment included

**Integration:**
- Knowledge Base: Inject code examples
- Figma: Import designs for frontend (Phase 3)
- GitHub: Push to user's repo (optional)

**Database Tables:** app_builder_projects, app_builder_files, app_builder_chat_history, app_builder_execution_logs

---

### 3.2 Website Builder

**Purpose:** Simplified site creation (vs full-stack apps)

**Differentiation:**
- Website Builder: Marketing sites, blogs, landing pages (static/simple)
- App Builder: Full-stack apps, complex logic, databases

**Features:**
- Template library (50+ pre-made)
- AI generation (natural language → site)
- Wysiwyg editor (drag-and-drop) OR code-server
- SEO tools (meta tags, sitemaps)
- One-click deployment (Vercel/Netlify/Hostinger)

**Transition:** "Upgrade to App" button (Website → App Builder migration)

---

### 3.3 Social Media Module

**Purpose:** AI content generation + multi-platform scheduling + analytics

**Features:**
- Content generation (topic + platform + tone → post + image + hashtags)
- Optimal time calculation (based on analytics)
- Scheduling (calendar view)
- Analytics dashboard (impressions, engagement)
- Brand guidelines (tone, keywords, colors)

**Platforms:** Twitter, LinkedIn, Facebook, Instagram

**Integration:**
- Knowledge Base: Brand guidelines, successful posts
- Figma: Brand assets (colors, fonts)

---

### 3.4 Figma Integration

**Ingestion Pipeline:**
1. Import Figma file (API)
2. Extract components (reusable UI elements)
3. Generate embeddings (semantic search)
4. Store: PostgreSQL (designs table) + filesystem (images)

**Design → Code Mapping:**
- Extract Figma properties (width, height, colors, fonts)
- Generate React/Vue/HTML components
- Inject into App Builder projects

**Versioning:** design_versions table, track Figma version_id, auto-detect updates

**Storage:** Custom (NOT Paperless-ngx) - PostgreSQL for metadata, filesystem for images

---

### 3.5 Mining Pool (Dual-Use Architecture)

**Purpose:** AI workloads (primary) + Mining when idle (passive revenue)

**Resource Arbitration:**
- Priority 1: AI requests (instant preemption)
- Priority 4: Mining (only if idle >5 min)

**Safety:**
- Temperature monitoring (stop at 80°C)
- Power limits (80% max)
- Network isolation (separate VLAN if possible)
- Data separation (mining_pool database, separate from archie)

**Dashboard Controls (Admin Only):**
- Enable/disable mining
- View mode (AI or Mining)
- Earnings tracking
- Hardware stats (temp, power, utilization)

---

## 4. RAG STRATEGY (SYSTEM-WIDE CANONICAL)

### Chunking Method (Layout-Aware Hierarchical)
- **Target:** 500-1000 tokens per chunk
- **Overlap:** 50 tokens between chunks
- **Hierarchy:** Module → Class → Function → Code blocks
- **Implementation:** AST parsing (Python), preserve structure

### Storage (Hybrid)
- **Vector:** PostgreSQL JSONB (768-dim embeddings from nomic-embed-text)
- **Sparse:** PostgreSQL GIN indexes (keywords, tags)
- **Index:** GIN on embedding column

### Re-Ranking (Two-Stage)
1. **Stage 1:** Hybrid search (30% keyword + 70% semantic) → top 50
2. **Stage 2:** Re-rank by:
   - Recency (20%)
   - Importance (15%)
   - User feedback (15%)
   - Contextual relevance (30%)
   - Citations (10%)
   - Original hybrid score (10%)

### Deduplication
- Detect: Cosine similarity >0.95
- Merge: Keep highest importance, merge citations

### Citations
- Format: `[Source: file.py:42]`
- Track: citation_log table
- Update importance scores based on citation count

---

## 5. EXECUTION ROADMAP (6 PHASES)

### PHASE 0: Cleanup & Alignment (1 week) 🔥 CRITICAL

**Goal:** Resolve conflicts, standardize foundation

**Tasks:**
1. Terminal → Dashboard (find/replace all files)
2. Create module_registry.py and rbac.py
3. Link ADMIN tab to (deprecated - see standalone modules)
4. Public /directory route (remove login requirement)
5. Document all 128 tables (ER diagram)

**Deliverables:**
- ✅ All "Terminal" references removed
- ✅ Module registry operational
- ✅ Navigation working
- ✅ Public directory accessible

**DO NOT SKIP THIS PHASE**

---

### PHASE 1: Core Platform (3 weeks)

**Goal:** Production-ready foundation

**Week 1: Infrastructure**
- Enhanced module system (health checks, enable/disable)
- Centralized logging (JSON format, 30-day retention)
- Performance optimization (Redis caching optional, query optimization)

**Week 2: Security**
- RBAC implementation (permission decorators)
- Input validation (all API endpoints)
- Rate limiting (per user/role)
- Backup testing (verify restore)

**Week 3: Developer Experience**
- API documentation (OpenAPI/Swagger)
- Testing framework (unit + integration, >60% coverage)
- Database migrations (Alembic)
- Development setup guide

**Deliverables:**
- ✅ Module health checks working
- ✅ RBAC fully implemented
- ✅ API docs complete
- ✅ Test coverage >60%

**Dependencies:** Phase 0 complete

---

### PHASE 2: App Builder (FLAGSHIP) (6 weeks) 🚀 PRIORITY 1

**Week 1-2: Planning System**
- Orchestrator framework
- Clarification agent (interactive chat)
- Project plan generator
- Plan approval UI
- Database tables

**Week 3-4: Code Generation**
- Docker sandbox setup
- Git integration
- Backend/frontend/DB generators
- Syntax validation

**Week 5: Testing**
- Test generator agent
- Test runner
- Error retry logic
- Health check generator

**Week 6: Deployment**
- Docker image builder
- Deployment integrations (Vercel, Railway)
- Documentation generator
- UI polish

**Success Criteria:**
- ✅ 80% test apps deploy successfully
- ✅ Generation time <20 minutes
- ✅ User satisfaction >8/10
- ✅ No critical vulnerabilities

**Dependencies:** Phase 1 complete

---

### PHASE 3: Design + Knowledge (4 weeks)

**Week 1: Figma Integration**
- Figma API client
- Design import
- Component extraction
- Database schema

**Week 2: Design to Code**
- Component code generator (React/Vue/HTML)
- Style extraction
- App Builder integration

**Week 3: Knowledge Enhancement**
- Layout-aware chunking
- Re-ranking system
- Deduplication
- Citation tracking

**Week 4: Integration**
- Figma → App Builder flow
- Knowledge base in all modules
- Design search

**Dependencies:** Phase 2 complete (App Builder needs design injection)

---

### PHASE 4: Expansion Modules (6 weeks)

**Week 1-2: Website Builder**
- Template library (50+ templates)
- AI generation mode
- Wysiwyg editor OR code-server
- Deployment pipeline
- SEO tools

**Week 3-4: Social Media**
- Content generator
- Platform integrations (APIs)
- Scheduling system
- Analytics dashboard

**Week 5-6: Mining Pool (Admin-only)**
- Resource arbitrator
- Mining configuration
- Dashboard controls
- Hardware monitoring
- Safety constraints

**Dependencies:** Phase 1-3 complete

---

### PHASE 5: Optimization & Scale (4 weeks)

**Week 1: Performance**
- Database indexing review
- API caching (Redis)
- CDN setup
- Background job queue

**Week 2: Scalability**
- Horizontal scaling (multiple containers)
- Load balancer
- Distributed caching
- Session storage (Redis)

**Week 3: Monitoring**
- Prometheus + Grafana
- Log aggregation
- Alerting rules
- SLA monitoring (99.9% uptime)

**Week 4: Security**
- Security audit (OWASP top 10)
- Penetration testing
- Secrets management
- WAF configuration

**Launch Checklist:**
- [ ] 1000 concurrent users tested
- [ ] Security audit passed
- [ ] 99%+ uptime achieved
- [ ] All critical bugs resolved
- [ ] Documentation complete
- [ ] ToS and Privacy Policy ready

---

## 6. RISK & FAILURE MODES

### Architectural Risks

**Risk:** Module coupling (modules depend on each other)
**Mitigation:** Strict interface contracts, API versioning, independent deployments

**Risk:** Database bottleneck (128 tables, complex queries)
**Mitigation:** Indexing strategy, query optimization, read replicas (Phase 5)

**Risk:** Docker resource exhaustion (many sandboxes)
**Mitigation:** Resource limits per container, cleanup cron jobs, max sandboxes per user

### Operational Risks

**Risk:** Ollama downtime (single point of failure)
**Mitigation:** Health checks, auto-restart, fallback to API providers (configurable)

**Risk:** Backup failure (data loss)
**Mitigation:** Daily automated backups, off-site storage, weekly restore tests

**Risk:** Security breach (user data exposed)
**Mitigation:** RBAC enforcement, audit logging, penetration testing, WAF

### AI Hallucination Risks

**Risk:** App Builder generates insecure code
**Mitigation:** Security scanning (bandit, safety), code review prompts, user warnings

**Risk:** Incorrect code that doesn't run
**Mitigation:** Syntax validation, automated testing, retry with error context

**Risk:** Social media generates inappropriate content
**Mitigation:** Content filtering, brand guidelines enforcement, user approval required

### Documentation Drift Risks

**Risk:** Code and docs out of sync
**Mitigation:** This canonical plan as single source of truth, update docs in same PR as code

**Risk:** Module changes break other modules
**Mitigation:** Integration tests, API contracts, changelog per module

---

## 7. WHAT NOT TO BUILD YET

**DO NOT BUILD (Phase 6+):**
- Mobile app (React Native/Flutter)
- Multi-tenancy (organization accounts)
- Advanced analytics (BI dashboards)
- Video generation module
- Game builder module
- External API marketplace
- White-label solution

**WHY:**
- Core modules must be proven first
- User demand unclear
- Complexity vs. value ratio low
- Resource intensive

**WHEN TO BUILD:**
- After Phase 5 complete
- User requests justify effort
- Revenue supports development cost

---

## 8. PARALLELIZATION STRATEGY

**Can Run in Parallel:**
- Phase 1 (Core) + Phase 3 (Figma/Knowledge) - Different teams
- Website Builder (Phase 4) + App Builder (Phase 2) - If separate teams
- Documentation + Testing - Always parallel to development

**Must Run Sequentially:**
- Phase 0 → Phase 1 (foundation required)
- Phase 1 → Phase 2 (module system required)
- Phase 2 → Phase 3 (App Builder needs design injection)
- Phase 4 → Phase 5 (all modules must exist before optimization)

**Recommended Team Structure:**
- Team A: Core Platform (Phase 1)
- Team B: App Builder (Phase 2) - STARTS AFTER Phase 1
- Team C: Design + Knowledge (Phase 3) - Can start with Phase 1
- Team D: Expansion Modules (Phase 4) - STARTS AFTER Phase 2

**Single Developer:** Follow phases sequentially (0 → 1 → 2 → 3 → 4 → 5)

---

## 9. SUCCESS METRICS (PER PHASE)

### Phase 0
- Zero "Terminal" references found in codebase
- Public directory accessible without login
- 100% navigation tabs working

### Phase 1
- API response time <500ms (p95)
- Test coverage >60%
- Zero critical security findings

### Phase 2 (App Builder)
- 80% generated apps deploy successfully
- Generation time <20 minutes average
- User satisfaction >8/10

### Phase 3
- Figma import success >90%
- Knowledge search relevance improved (user feedback)
- Citation tracking operational

### Phase 4
- Website Builder: 90% deployments succeed
- Social Media: Content quality >7/10
- Mining Pool: Zero AI delays

### Phase 5
- System handles 1000 concurrent users
- 99.9% uptime achieved
- Security audit passed (zero critical)

---

## 10. FINAL INSTRUCTIONS

### For Lead Developer:
1. Read entire plan before starting
2. Complete Phase 0 fully (DO NOT SKIP)
3. Use module_registry.py as single source for modules
4. Follow RBAC model for all new routes
5. Write tests for all new code (>60% coverage)
6. Update this document when architectural decisions change

### For Infrastructure Engineer:
1. Ensure Docker setup supports multiple sandboxes
2. Configure Redis for caching (Phase 1)
3. Set up monitoring (Prometheus + Grafana, Phase 5)
4. Test backup/restore weekly
5. Review security checklist (Phase 5)

### For Designer:
1. Dashboard UI must support module registry (dynamic tool cards)
2. Design App Builder UI (chat + progress + preview)
3. Design Figma import workflow
4. Maintain Matrix theme consistency

---

## CANONICAL REFERENCE STATEMENT

**This plan is now the canonical execution reference for A.R.C.H.I.E.**

All implementation work must align with this plan. Any deviations require updating this document first. This document supersedes all previous plans, notes, and TODO lists.

**Version Control:** This plan lives at `/mnt/archie_brain/docs/CANONICAL_EXECUTION_PLAN.md`

**Last Updated:** January 6, 2026
**Next Review:** After Phase 2 completion
**Owner:** System Architect + Lead Developer

---

**END OF CANONICAL PLAN**
