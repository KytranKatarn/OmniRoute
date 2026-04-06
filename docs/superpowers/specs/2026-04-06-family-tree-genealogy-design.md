# Family Tree Module — AI-Powered Genealogy

**Date:** 2026-04-06
**Status:** Approved
**Category:** APPLICATIONS (module_registry.py)
**Route:** `/tools/family-tree`
**Blueprint:** `family_tree_bp`
**CSS Prefix:** `ft-`

---

## Overview

An AI-powered genealogy module for the A.R.C.H.I.E. platform that functions as an autonomous family tree research assistant. Unlike traditional genealogy platforms (Ancestry, FamilySearch) where users manually search records, this module dispatches specialized AI agents to search public records, OCR documents, match faces in photos, and build family trees automatically — with human-in-the-loop confirmation for all additions.

**Primary Use Case:** Personal family research for Portuguese → France → Canada migration path, designed for standalone extraction and resale.

**Architectural Approach:** Agent-Per-Task — dedicated AI agents for each genealogy capability, coordinated by a lead genealogist agent, dispatched through Bridge.

---

## 1. Agent Team (5 New Agents)

All agents registered through `agent_service.create_agent()` and managed by Department HQ. Follow acronym naming convention.

| Agent | Full Name | Department | Director | Role |
|-------|-----------|------------|----------|------|
| **H.E.R.I.T.A.G.E.** | Historical Exploration, Research, Investigation & Trace of Ancestral Genealogy Engine | Research & Development | D.A.R.W.I.N. | Lead genealogist — coordinates research, analyzes gaps, builds tree, presents findings |
| **S.C.R.O.L.L.** | Source, Census & Record Online Lookup Liaison | Research & Development | D.A.R.W.I.N. | Searches FamilySearch, WikiTree, NARA, Chronicling America, Europeana |
| **Q.U.I.L.L.** | Query, Uncover & Interpret Legacy Letters | Research & Development | D.A.R.W.I.N. | Document OCR (Tesseract for print, Transkribus for handwriting), extracts structured data |
| **V.I.S.A.G.E.** | Visual Identification & Similarity Analysis for Genealogy Evidence | Creative & Design | M.U.S.E. | Face detection, embedding generation (InsightFace), cross-photo matching, era estimation |
| **R.E.S.T.O.R.E.** | Reconstruction & Enhancement of Scarred, Torn or Ruined Evidence | Creative & Design | M.U.S.E. | Photo colorization, restoration, upscaling via ComfyUI |

**Department Assignment:** 3 agents to R&D (ENGINEERING floor), 2 agents to Creative & Design (CREATIVE floor).

---

## 2. Data Sources & External Integrations

### Free APIs (Priority Order)

| # | Source | Auth | Data | Coverage | Rate Limits |
|---|--------|------|------|----------|-------------|
| 1 | **FamilySearch API** | OAuth2 (free account) | 1.4B+ indexed records — births, marriages, deaths, census, immigration, parish records. Portuguese Arquivo Nacional Torre do Tombo records indexed here. | Canada, US, Europe (Portugal, France) | ~1000 req/min (throttled) |
| 2 | **WikiTree API** | API key (free) | 35M+ profiles in collaborative world tree. Cross-reference and profile matching. | Global | Reasonable use |
| 3 | **Chronicling America API** | None (open) | Historical newspapers 1690-1963. Obituaries, immigration announcements, community news. | US + some Canadian | No documented limit |
| 4 | **NARA Catalog API** | None (open) | US National Archives — immigration ship manifests, naturalization records, military records. | US | No documented limit |
| 5 | **Europeana API** | API key (free) | 50M+ European cultural heritage objects — photographs, documents, church records metadata. | Europe | Reasonable use |
| 6 | **Geni API** | OAuth2 (free tier) | Supplemental world tree data, profile matching. | Global | Limited free tier |

### Portuguese Records (Specialized)

- **Arquivo Nacional Torre do Tombo** — parish records back to 1500s, accessed via FamilySearch API
- **Civil registration** (post-1911) — births, marriages, deaths
- **Church records** (pre-1911) — baptisms, marriages, burials
- **Emigration records** — Junta de Emigração archives

### Canadian Records

- Census 1825-1921 (via FamilySearch)
- Immigration/ship manifests (NARA + FamilySearch)
- Provincial vital statistics (via FamilySearch — no direct provincial APIs exist)

### French Records

- Departmental archives (via FamilySearch + Europeana)
- Civil registration (état civil)
- Transit/immigration records for Portuguese diaspora

### AI/ML Libraries

| Tool | Purpose | Integration |
|------|---------|-------------|
| **Tesseract** (pytesseract) | OCR for printed documents | Q.U.I.L.L. agent |
| **Transkribus API** | Handwritten text recognition (500 pages/month free) | Q.U.I.L.L. agent |
| **InsightFace** | Face detection + embedding generation | V.I.S.A.G.E. agent |
| **CLIP** | Era/style estimation from clothing | V.I.S.A.G.E. agent |
| **splink** | Probabilistic record linkage/deduplication | S.C.R.O.L.L. agent |
| **ged4py** | GEDCOM 5.5.1 import/export | Tree service |
| **ComfyUI** | Photo restoration/colorization (existing) | R.E.S.T.O.R.E. agent |

---

## 3. Database Schema

All tables prefixed `family_` for clean standalone extraction. Scoped by `user_id` for future multi-user/SaaS support.

### family_persons

```sql
CREATE TABLE family_persons (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    maiden_name VARCHAR(255),
    gender VARCHAR(20),
    birth_date DATE,
    birth_date_approx BOOLEAN DEFAULT FALSE,
    birth_place VARCHAR(500),
    death_date DATE,
    death_date_approx BOOLEAN DEFAULT FALSE,
    death_place VARCHAR(500),
    notes TEXT,
    confidence_score DECIMAL(3,2) DEFAULT 1.00,
    source_type VARCHAR(50) DEFAULT 'user_input',
    avatar_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### family_relationships

```sql
CREATE TABLE family_relationships (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    person_a_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    person_b_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL,
    -- Types: parent_child, spouse, sibling
    start_date DATE,
    end_date DATE,
    confidence_score DECIMAL(3,2) DEFAULT 1.00,
    source_id INTEGER REFERENCES family_sources(id),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(person_a_id, person_b_id, relationship_type)
);
```

### family_documents

```sql
CREATE TABLE family_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_type VARCHAR(50),
    document_type VARCHAR(100),
    -- Types: birth_certificate, marriage_record, immigration_paper, letter, photo, other
    ocr_text TEXT,
    ocr_status VARCHAR(20) DEFAULT 'pending',
    -- Status: pending, processing, completed, failed
    extracted_data JSONB,
    linked_person_id INTEGER REFERENCES family_persons(id),
    uploaded_at TIMESTAMP DEFAULT NOW()
);
```

### family_sources

```sql
CREATE TABLE family_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    source_type VARCHAR(50) NOT NULL,
    -- Types: familysearch, wikitree, nara, chronicling_america, europeana, geni, document_upload, user_input
    external_id VARCHAR(500),
    title VARCHAR(500),
    url VARCHAR(1000),
    citation TEXT,
    retrieved_at TIMESTAMP DEFAULT NOW()
);
```

### family_research_queue

```sql
CREATE TABLE family_research_queue (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    person_id INTEGER REFERENCES family_persons(id),
    research_type VARCHAR(50) NOT NULL,
    -- Types: find_parents, find_spouse, find_children, immigration, vital_record, newspaper_mention
    query_params JSONB,
    status VARCHAR(20) DEFAULT 'queued',
    -- Status: queued, searching, found_matches, reviewed, no_results
    agent_name VARCHAR(100),
    results JSONB,
    confidence_score DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
```

### family_face_embeddings

```sql
CREATE TABLE family_face_embeddings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    document_id INTEGER NOT NULL REFERENCES family_documents(id) ON DELETE CASCADE,
    person_id INTEGER REFERENCES family_persons(id),
    embedding VECTOR(512),
    bounding_box JSONB,
    cluster_id INTEGER,
    estimated_era VARCHAR(50),
    confidence_score DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### family_person_sources (junction table)

```sql
CREATE TABLE family_person_sources (
    person_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES family_sources(id) ON DELETE CASCADE,
    field_name VARCHAR(100),
    PRIMARY KEY (person_id, source_id, field_name)
);
```

---

## 4. AI Research Pipeline

### Autonomous Research Flow

```
User seeds tree with known family members
         │
         ▼
H.E.R.I.T.A.G.E. analyzes tree gaps
"Grandmother born ~1935, Portugal — no parents known"
         │
         ▼
Creates research_queue entries for each gap
         │
         ├──→ S.C.R.O.L.L. searches FamilySearch for Portuguese parish records
         ├──→ S.C.R.O.L.L. searches WikiTree for matching profiles
         ├──→ S.C.R.O.L.L. searches Chronicling America for immigration mentions
         │    (parallel — each is an independent search)
         ▼
Results scored by splink probabilistic matching
"Found baptism record: Maria da Silva, 1934, Aveiro — 87% match"
         │
         ▼
H.E.R.I.T.A.G.E. presents findings with confidence scores
User reviews: Accept / Reject / Maybe
         │
         ▼
Accepted matches added to tree → new gaps identified → cycle repeats
```

### Document Upload Pipeline

```
User uploads photo of birth certificate
         │
         ▼
Q.U.I.L.L. runs OCR
  - Tesseract for printed text
  - Transkribus API for handwritten text
         │
         ▼
LLM extracts structured data via Bridge dispatch:
{ name: "Manuel da Silva", birth_date: "1902-03-15",
  birthplace: "Aveiro, Portugal", parents: ["José da Silva", "Ana Ferreira"] }
         │
         ▼
H.E.R.I.T.A.G.E. matches to existing tree persons or creates new entries
Sources linked via family_person_sources
```

### Photo Pipeline

```
User uploads batch of old family photos
         │
         ├──→ V.I.S.A.G.E. detects faces → generates 512-dim embeddings (InsightFace)
         ├──→ V.I.S.A.G.E. estimates era from clothing/style (CLIP + LLM)
         ├──→ V.I.S.A.G.E. clusters faces across photos → "These 5 photos contain the same person"
         │
         ▼
User labels clusters: "That's grandpa Manuel"
Face embeddings linked to family_persons
         │
         ▼
R.E.S.T.O.R.E. offers restoration/colorization on selected photos (ComfyUI)
```

### Bridge Dispatch Rules

- All LLM inference goes through Bridge dispatcher (ADR-013)
- S.C.R.O.L.L. uses external API clients directly for record searches (not LLM)
- S.C.R.O.L.L. uses LLM via Bridge for result analysis and name matching
- Q.U.I.L.L. uses Tesseract/Transkribus directly for OCR, LLM via Bridge for data extraction
- V.I.S.A.G.E. uses InsightFace directly for embeddings, LLM via Bridge for era estimation
- R.E.S.T.O.R.E. uses ComfyUI directly (existing integration)

---

## 5. UI Design — 5-Tab LCARS Interface

### Tab Structure

| Tab | Icon | Content | Primary Agent |
|-----|------|---------|---------------|
| **Tree** | 🌳 | Interactive family tree visualization | H.E.R.I.T.A.G.E. |
| **Research** | 🔍 | AI research queue, active searches, findings review | S.C.R.O.L.L. |
| **Documents** | 📄 | Upload zone, OCR status, extracted data preview | Q.U.I.L.L. |
| **Photos** | 📸 | Gallery, face detection, clusters, restore/colorize | V.I.S.A.G.E. + R.E.S.T.O.R.E. |
| **Timeline** | 📊 | Vertical timeline, migration path map | H.E.R.I.T.A.G.E. |

### Tree View

- Interactive tree rendered in JS (d3.js or custom SVG)
- Color-coded nodes:
  - **Cyan** = confirmed by user
  - **Green** = found in records (with source)
  - **Orange dashed** = AI currently researching
  - **Red** = gap/unknown
- Click node → person detail panel (dates, places, sources, linked documents/photos)
- Actions: Add Person, Import GEDCOM, Export GEDCOM
- Zoom/pan for large trees, responsive at 480/768/1024px

### Research Tab

- **Active Research** panel — currently running searches with progress
- **Findings** panel — matches awaiting review with confidence scores
- Accept/Reject/Maybe buttons per finding
- Source citation shown for each match
- "Research this person" button on any tree node to queue new searches

### Documents Tab

- Drag-and-drop upload zone (accepts images and PDFs)
- Document list with OCR status indicators (pending/processing/completed/failed)
- Extracted data preview with field highlighting
- "Link to person" dropdown to connect document to tree
- View original alongside extracted data

### Photos Tab

- Photo gallery grid
- Face detection overlays on hover
- Face cluster groups ("Same person" groupings)
- Label faces → link to tree person
- Restore/Colorize buttons per photo (dispatches to R.E.S.T.O.R.E.)
- Before/after comparison for restored photos

### Timeline Tab

- Vertical timeline of all family events (births, marriages, deaths, immigration)
- Historical context overlays (e.g., Portuguese emigration waves, Canadian immigration policy changes)
- Map view showing migration path: Portugal → France → Canada
- Filterable by person, event type, date range

---

## 6. Module File Structure

```
platform_v2/tools/family_tree/
├── __init__.py                  # register_*_routes(bp, admin_required) — ADR-045
├── routes.py                    # Dashboard, tree CRUD, GEDCOM import/export
├── research_routes.py           # AI research queue, findings review, accept/reject
├── document_routes.py           # Upload, OCR status, extracted data, link to person
├── photo_routes.py              # Upload, face detection, clustering, restore trigger
├── timeline_routes.py           # Timeline data, map coordinates, event aggregation
├── services/
│   ├── tree_service.py          # Family tree CRUD, relationship management, recursive queries
│   ├── research_service.py      # FamilySearch/WikiTree/NARA/Chronicling America/Europeana clients
│   ├── ocr_service.py           # Tesseract + Transkribus integration
│   ├── face_service.py          # InsightFace embeddings, DBSCAN clustering
│   └── gedcom_service.py        # Import/export via ged4py
├── templates/
│   └── family_tree.html         # Main template (5 tabs, extends base.html)
└── static/
    ├── css/family-tree.css      # ft- prefix, LCARS themed
    └── js/family-tree.js        # Tree renderer, research UI, upload handlers, face labeling
```

### Registration

- `module_registry.py` — Category: `APPLICATIONS`
- `rbac.py` — Permission: `family_tree` (add to both admin and user roles)
- Blueprint: `family_tree_bp`, prefix `/tools/family-tree`
- Template folder: `template_folder="templates"` (has own templates/ subdir)

---

## 7. Resale & Standalone Extraction Strategy

### Phase 1 — ARCHIE Module (Build First)

- Build as `platform_v2/tools/family_tree/` following standard patterns
- Own tables in archie DB (all prefixed `family_*`)
- Uses Bridge dispatch, agent_service, existing ComfyUI
- Personal use for family research

### Phase 2 — Standalone Extraction (When Ready to Sell)

- Follow standalone extraction playbook (`.claude/rules/standalone-extraction.md`)
- Own repo: product name TBD
- SQLite default, PostgreSQL option
- Own auth with "Sign in with Kytran" OAuth
- Own Docker container, own subdomain
- Tier 1 → Tier 2 → Tier 3 checklist

### Resale Pricing Model

| Tier | Price | Features |
|------|-------|----------|
| **Free** | $0 | Manual tree building, GEDCOM import/export, 5 AI searches/month |
| **Explorer** | ~$15/mo | Unlimited AI research, document OCR, 50 photo uploads/month |
| **Heritage** | ~$30/mo | Everything + photo restoration, face matching, priority research queue, full newspaper search |

### Competitive Differentiation

- AI does the research (Ancestry makes users search manually)
- Specialized Portuguese/French/Canadian record knowledge
- Photo restoration + face matching built in
- Conversation-based research, not form-fill
- Privacy-first: self-hosted option, data stays with user
- GEDCOM export — users can leave anytime (trust builder)

### Extraction-Ready Design Decisions

- All DB tables use `family_` prefix — clean separation
- Services layer wraps all external API calls — swap implementations without touching routes
- No imports from other ARCHIE modules except Bridge dispatch (replaceable with direct API calls in standalone)
- Face embeddings stored locally, never sent to cloud
- Per-user data isolation (`user_id` on all tables) from day one

---

## 8. Post-Implementation Integration Checklist

After the module is built and functional, these platform-wide updates are required:

### Department HQ Updates
- [ ] Register 5 new agents via `agent_service.create_agent()` with proper acronym names
- [ ] Assign 3 agents to R&D (D.A.R.W.I.N.), 2 to Creative & Design (M.U.S.E.)
- [ ] Verify agents appear in Department HQ roster, agent profiles, and directory

### Directory & Website Updates
- [ ] Update platform directory/org chart to include new agents
- [ ] Update agent count in any platform status displays
- [ ] Add Family Tree to the website product/feature showcase
- [ ] Update kytranempowerment.com with product listing when ready for resale

### Dev HQ Updates
- [ ] Create project in unified_projects via MCP
- [ ] Log architectural decisions via MCP
- [ ] Register in Code Health scanner (`STANDALONE_PRODUCTS` in `code_metrics_service.py`) when extracted
- [ ] Update project understanding via MCP after each phase

### Compare / Showcase
- [ ] Add to platform comparison page — highlight AI genealogist vs manual Ancestry search
- [ ] Prepare demo: seed a tree → AI finds records → document OCR → face matching → restored photo
- [ ] Before/after screenshots for photo restoration feature
- [ ] Migration path visualization (Portugal → France → Canada) as showcase piece

### Module Registry
- [ ] Add to `module_registry.py` under APPLICATIONS category
- [ ] Add to `rbac.py` with `family_tree` permission
- [ ] Verify module appears on dashboard

---

## 9. Dependencies & Prerequisites

### Python Packages (add to requirements.txt)

```
pytesseract>=0.3.10
ged4py>=0.4.0
insightface>=0.7.3
onnxruntime>=1.16.0
scikit-learn>=1.3.0
splink>=3.9.0
```

### System Dependencies (Dockerfile)

```
tesseract-ocr
tesseract-ocr-por  # Portuguese language pack
tesseract-ocr-fra  # French language pack
```

### External Account Setup

- FamilySearch developer account + OAuth app registration (free)
- Europeana API key (free, instant)
- Transkribus account (free tier, 500 pages/month)

### Existing Infrastructure Used

- Bridge dispatcher (LLM inference)
- ComfyUI (photo restoration — already running)
- Agent service (agent lifecycle)
- Department HQ (agent management)
- PostgreSQL (existing archie database)

---

## 10. Out of Scope (For Now)

- DNA integration (23andMe/AncestryDNA APIs are restricted)
- Collaborative trees (multi-user editing same tree)
- Mobile app (responsive web is sufficient)
- Paid record databases (Ancestry.com, FindMyPast — no public APIs)
- Real-time record monitoring/alerts
- Family tree merging between users
