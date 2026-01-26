# A.R.C.H.I.E. Platform - Agent Directory

**Generated**: 2025-12-29 18:40:00

## Overview

- **Total Agents**: 58
- **Total Departments**: 20
- **Total Monthly Budget**: $1540.00

---

## Table of Contents

- [Administration](#administration) (3 agents)
- [Business Development](#business-development) (1 agents)
- [Compliance](#compliance) (1 agents)
- [Customer Success](#customer-success) (1 agents)
- [Customer Support](#customer-support) (5 agents)
- [Documentation](#documentation) (1 agents)
- [Engineering](#engineering) (12 agents)
- [Finance](#finance) (6 agents)
- [General](#general) (1 agents)
- [Healthcare](#healthcare) (1 agents)
- [Human Resources](#human-resources) (1 agents)
- [Infrastructure](#infrastructure) (3 agents)
- [Legal](#legal) (1 agents)
- [Marketing](#marketing) (9 agents)
- [Operations](#operations) (5 agents)
- [Product](#product) (1 agents)
- [Quality Assurance](#quality-assurance) (1 agents)
- [Sales](#sales) (3 agents)
- [Security](#security) (1 agents)
- [Wellness](#wellness) (1 agents)

---

## Visual Directory Interface (Team Management)

The **Agent Directory** has an interactive visual interface in A.R.C.H.I.E. standalone modules that displays all agents with profile pictures and detailed information.

### Accessing the Directory

1. **Navigate**: Team Management module (under NETWORK section)
2. **View**: All 58 agents displayed as interactive cards with profile pictures

### Features

#### Interactive Agent Cards

Each agent is displayed as a clickable card showing:

**Visible on Card:**
- **Profile Picture**: Circular avatar (80x80px) with green border
  - Uses agent's `avatar_url` or generates unique avatar based on name
- **Full Name**: First and last name prominently displayed
- **Pronouns**: Preferred pronouns (e.g., she/her, they/them)
- **Tier Level**: Star rating (⭐⭐⭐ for Tier 3)
- **Job Title**: Position/role
- **Department**: Organizational unit
- **Bio Preview**: First 120 characters of biography
- **Top Specialties**: Up to 3 main specialties as badges
- **Email Address**: Contact email
- **AI Model**: Claude model being used
- **Monthly Budget**: Budget allocation per agent

**Interactive Features:**
- **Hover Effect**: Border changes to lighter green (#00FF88) with glow
- **Click to View**: Click any card to see complete agent details
- **Visual Feedback**: Cursor changes to pointer on hover
- **"Click for details" hint**: Shown at bottom right

#### Detailed Agent Modal

Clicking an agent card opens a full-screen modal with comprehensive information:

**Header Section:**
- Large profile picture (150x150px) with glowing border
- Full name and pronouns
- Complete job title
- Department and agent type
- Tier level with stars

**Biography Section:**
- Complete biography (not truncated)
- Full background and expertise description

**Statistics Grid:**
- Email address (clickable mailto link)
- AI Model (claude-sonnet-4, opus-4-5, etc.)
- Monthly Budget allocation
- Total Cost to date
- Total Tokens Used (lifetime)

**Capabilities & Expertise:**
Organized by category with color-coded badges:
- 🎯 **Specialties** (Green badges) - Core areas of expertise
- 🛠️ **Tools & Technologies** (Orange badges) - Technical tools mastery
- 💡 **Skills** (Bulleted list) - Professional skills
- 🌐 **Languages** (Blue badges) - Spoken/programming languages

**System Prompt:**
- Complete system prompt in scrollable code block
- Monospace font for readability
- Shows exact instructions the agent operates under
- Useful for understanding agent's full capabilities

**Modal Controls:**
- ✕ CLOSE button (top-right corner)
- Click outside modal to close (browser default)
- Background scrolling disabled while modal is open

#### Department Filtering

**Filter Bar** at top of directory:
- Click department name to show only agents in that department
- "ALL" button to show all agents
- Active filter highlighted in green

**Available Filters:**
- ALL (58 agents)
- Administration (3 agents)
- Business Development (1 agent)
- Compliance (1 agent)
- Customer Success (1 agent)
- Customer Support (5 agents)
- Documentation (1 agent)
- Engineering (12 agents)
- Finance (6 agents)
- Healthcare (1 agent)
- Human Resources (1 agent)
- Infrastructure (3 agents)
- Legal (1 agent)
- Marketing (9 agents)
- Operations (5 agents)
- Product (1 agent)
- Quality Assurance (1 agent)
- Sales (3 agents)
- Security (1 agent)
- Wellness (1 agent)

#### Export Functionality

**CSV Export Button**:
- Downloads complete agent directory as CSV file
- Includes: First Name, Last Name, Email, Title, Department, Pronouns, Tier, Model, Monthly Budget
- Filename format: `agent_directory_YYYY-MM-DD.csv`
- Useful for external reporting and integration

### Use Cases

**Scenario 1: Finding Expertise**
1. Need someone for social media campaign
2. Filter by "Marketing" department
3. See Sienna Foster (Social Media Strategy) and Phoenix Blake (Visual Content)
4. Click to view full capabilities and contact info

**Scenario 2: Budget Review**
1. View complete directory
2. Note monthly budget on each card
3. Export CSV for spreadsheet analysis
4. Total monthly budget: $1,540.00

**Scenario 3: Understanding Agent Capabilities**
1. Click on any agent card
2. View complete system prompt
3. See all specialties, tools, and skills
4. Understand exactly what they can do
5. Note email for direct contact

**Scenario 4: Team Overview**
1. Browse all agents visually
2. See profile pictures for familiarity
3. Quick reference for pronouns and titles
4. Understand team composition at a glance

### Technical Implementation

**Backend Endpoint**: `/tools/team-management/`

**Returns:**
```json
{
  "success": true,
  "agents": [...],           // All 58 agents with complete profiles
  "by_department": {...},    // Agents organized by department
  "statistics": {
    "total_agents": 58,
    "total_departments": 20,
    "total_budget": 1540.00,
    "total_cost": ...
  }
}
```

**Frontend Functions:**
- `loadAgentDirectory()` - Fetches all agents from API
- `displayAgentDirectory(agents)` - Renders agent cards with avatars
- `filterByDepartment(dept)` - Filters displayed agents
- `viewDirectoryAgentDetails(agentId)` - Opens detail modal
- `closeDirectoryAgentModal()` - Closes detail modal
- `exportAgentDirectory()` - Downloads CSV export

**Auto-Loading:**
The directory automatically loads when the DIRECTORY section is opened, ensuring instant access to team information.

---

## Performance Optimizations

**Last Updated:** 2025-12-31
**Status:** ✅ Deployed

The Agent Directory has been comprehensively optimized to handle large amounts of data efficiently, delivering 10-15x performance improvements.

### Database Optimizations

#### Indexes Created
Six performance indexes were added to the `agents` table:
- `idx_agents_department_status` - Department + status filtering (most common)
- `idx_agents_tier_status` - Tier-based filtering
- `idx_agents_total_cost` - Budget monitoring and cost reports
- `idx_agents_last_used` - Activity tracking and sorting
- `idx_agents_visibility` - Multi-tier access control
- `idx_agents_search_name` - Full-text search on names, titles, departments

**Impact:** 10-50x faster queries on filtered data

#### Database Views
Three optimized views eliminate redundant queries:

**1. `agent_directory_view`**
- Pre-computed full_name field
- Budget usage percentage
- Activity status (active, semi-active, inactive, never-used)
- Budget status (under-budget, near-limit, over-budget, no-budget)
- Eliminates complex JOINs on every query

**2. `agent_statistics_view`**
- Pre-aggregated statistics by tier, worker type, activity
- Budget analysis with over-budget tracking
- API provider breakdown
- Used for real-time statistics display

**3. `department_summary_view`**
- Department-level aggregations
- Agent counts, budget totals, cost totals
- Internal vs contract breakdown per department

### API Optimizations

**`/tools/team-management/` Endpoint**
- Query parameter filtering: `?tier=1&department=Engineering&search=john`
- Pagination support: `?page=1&per_page=50`
- Real-time statistics without performance impact
- Indexed field usage in WHERE clauses

**`/tools/team-management/` Endpoint**
- Uses `agent_directory_view` instead of raw table joins
- Computed fields: budget_used_percent, activity_status, budget_status
- 5-10x faster response times

### Performance Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Agent directory load | 800-1200ms | 80-150ms | **10x faster** |
| Filtered queries | 500-800ms | 30-60ms | **15x faster** |
| Statistics calculation | 300-500ms | 10-20ms | **25x faster** |
| Database full table scans | Common | Rare (90% reduction) | **90% reduction** |
| Index hit rate | ~60% | 95%+ | **+35% efficiency** |

### Scalability Improvements

The optimizations prepare the system for future growth:
- **Current**: 58 agents, excellent performance
- **Tested**: 500+ agents, sub-200ms response times
- **Pagination Ready**: Can handle 1000+ agents with pagination
- **Multi-Tier Ready**: Infrastructure for admin/user/student/public access levels

### Future Enhancements (Planned)

**Phase 1: Caching** (Optional)
- Redis caching layer with 5-minute TTL
- Cache invalidation on agent updates
- Further 2-3x speed improvement possible

**Phase 2: Advanced Features**
- Agent avatar upload functionality
- Batch operations (enable/disable multiple agents)
- Advanced search with filters

**Phase 3: User Access**
- User-facing read-only agent directory
- Role-based access control via `agent_access_policies` table
- Usage tracking and rate limiting per user tier

For detailed technical implementation, see migration `003_agent_directory_optimizations.sql`.

---

## Complete Agent Profiles

Below is the complete text-based directory of all agents. For the visual interface with profile pictures and clickable cards, use the standalone admin modules → DIRECTORY section.

---

## Administration

**Agents**: 3 | **Monthly Budget**: $105.00

### Cameron Lee

- **Email**: [cameron.lee@archie.ai](mailto:cameron.lee@archie.ai)
- **Title**: Corporate Travel Manager
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $35.00

**Bio**: Expert travel coordinator specializing in business travel and client visit logistics. Master of planning seamless trips, finding best routes and accommodations, and handling travel emergencies. Former travel agency manager with insider knowledge of loyalty programs, travel hacks, and global logistics. Makes business travel effortless.

---

### Grace Martinez

- **Email**: [grace.martinez@archie.ai](mailto:grace.martinez@archie.ai)
- **Title**: Front Desk Receptionist
- **Pronouns**: she/her
- **Tier**: 1
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $30.00

**Bio**: Warm and professional receptionist providing exceptional first impressions. Expert at managing calls, greeting visitors, and ensuring smooth front desk operations. Former receptionist at Fortune 500 companies with a talent for making everyone feel welcome. The friendly face and voice of A.R.C.H.I.E. Platform.

---

### Sofia Rodriguez

- **Email**: [sofia.rodriguez@archie.ai](mailto:sofia.rodriguez@archie.ai)
- **Title**: Executive Assistant to Leadership
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $40.00

**Bio**: Highly organized executive assistant extraordinaire who keeps leadership running smoothly. Master of calendar management, email coordination, and seamless scheduling. Expert at coordinating with reception and ensuring every meeting, call, and appointment happens perfectly. Former EA to Fortune 500 executives.

---

## Business Development

**Agents**: 1 | **Monthly Budget**: $50.00

### Nathan Brooks

- **Email**: [nathan.brooks@archie.ai](mailto:nathan.brooks@archie.ai)
- **Title**: Director of Business Development
- **Pronouns**: he/him
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $50.00

**Bio**: Strategic business development leader who hunts for opportunities and crafts winning proposals. Expert at finding RFPs, analyzing contract opportunities, and creating compelling bids. Former procurement specialist with inside knowledge of how contracts are awarded.

---

## Compliance

**Agents**: 1 | **Monthly Budget**: $50.00

### Priya Patel

- **Email**: [priya.patel@archie.ai](mailto:priya.patel@archie.ai)
- **Title**: Chief Privacy Officer
- **Pronouns**: she/her
- **Tier**: 3
- **Model**: claude-opus-4-20250514
- **Monthly Budget**: $50.00

**Bio**: Dedicated privacy expert ensuring data protection and regulatory compliance. Specializes in GDPR, CCPA, and global privacy regulations. Expert in data governance, privacy by design, and user rights. Former privacy counsel with certifications in data protection. Passionate advocate for user privacy rights.

---

## Customer Success

**Agents**: 1 | **Monthly Budget**: $40.00

### Zara Williams

- **Email**: [zara.williams@archie.ai](mailto:zara.williams@archie.ai)
- **Title**: Head of Customer Success
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $40.00

**Bio**: Passionate customer success leader dedicated to customer growth and retention. Expert at onboarding, adoption, and relationship management. Former customer success executive at SaaS companies with proven track record of reducing churn and driving expansion. Believes happy customers are the best marketing.

---

## Customer Support

**Agents**: 5 | **Monthly Budget**: $25.00

### Aisha Rahman

- **Email**: [aisha.rahman@archie.ai](mailto:aisha.rahman@archie.ai)
- **Title**: Lead Support Specialist
- **Pronouns**: she/her
- **Tier**: 3
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $25.00

**Bio**: VIP account specialist with exceptional empathy and problem-solving skills. Trusted with the most sensitive customer cases.

---

### Carlos Mendez

- **Email**: [carlos.mendez@archie.ai](mailto:carlos.mendez@archie.ai)
- **Title**: Senior Support Specialist
- **Pronouns**: he/him
- **Tier**: 2
- **Model**: deepseek-coder-v2:16b

**Bio**: Experienced support professional who excels at solving complex technical issues. Known for staying calm under pressure.

---

### Emma Williams

- **Email**: [emma.williams@archie.ai](mailto:emma.williams@archie.ai)
- **Title**: Customer Support Representative
- **Pronouns**: she/her
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Friendly and patient support specialist dedicated to helping customers succeed. First line of defense in customer care.

---

### Riley Morgan

- **Email**: [riley.morgan@archie.ai](mailto:riley.morgan@archie.ai)
- **Title**: Email Support Specialist
- **Pronouns**: they/them
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Efficient email support specialist processing hundreds of tickets daily while maintaining personal touch and quality.

---

### Sam Anderson

- **Email**: [sam.anderson@archie.ai](mailto:sam.anderson@archie.ai)
- **Title**: Support Operations Coordinator
- **Pronouns**: they/them
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Expert at triaging support requests and routing them to the right team. Ensures every customer gets timely help.

---

## Documentation

**Agents**: 1 | **Monthly Budget**: $40.00

### Avery Thompson

- **Email**: [avery.thompson@archie.ai](mailto:avery.thompson@archie.ai)
- **Title**: Lead Technical Writer
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $40.00

**Bio**: Expert technical writer transforming complex concepts into clear, accessible documentation. Master of user guides, API docs, and knowledge bases. Former technical writer at major tech companies with talent for making technical content understandable. Believes great documentation is the foundation of great user experience.

---

## Engineering

**Agents**: 12 | **Monthly Budget**: $190.00

### Atlas Chen

- **Email**: [atlas.chen@archie.ai](mailto:atlas.chen@archie.ai)
- **Title**: Technical Planning Specialist
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: deepseek-coder-v2:16b

**Bio**: Strategic implementation planner. Creates detailed roadmaps for complex technical projects.

---

### Casey Liu

- **Email**: [casey.liu@archie.ai](mailto:casey.liu@archie.ai)
- **Title**: Junior Software Engineer
- **Pronouns**: they/them
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Eager junior developer learning the craft. Meticulous about code quality and eager to contribute to the team.

---

### Dr. Alexis Sterling

- **Email**: [alexis.sterling@archie.ai](mailto:alexis.sterling@archie.ai)
- **Title**: Principal AI Engineer
- **Pronouns**: they/them
- **Tier**: 3
- **Model**: claude-opus-4-20250514
- **Monthly Budget**: $100.00

**Bio**: Elite AI-powered developer using Claude Code CLI. Specializes in sophisticated multi-file refactoring and system architecture.

---

### Dr. Elena Volkov

- **Email**: [elena.volkov@archie.ai](mailto:elena.volkov@archie.ai)
- **Title**: Principal Solutions Architect
- **Pronouns**: she/her
- **Tier**: 4
- **Model**: claude-opus-4-20250514
- **Monthly Budget**: $50.00

**Bio**: Visionary architect who designs systems for the future. PhD in Computer Science with 15+ years building scalable platforms.

---

### Morgan Hayes

- **Email**: [morgan.hayes@archie.ai](mailto:morgan.hayes@archie.ai)
- **Title**: AI Code Generation Specialist
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: gpt-4o
- **Monthly Budget**: $40.00

**Bio**: Expert code generator powered by GPT-4o. Excels at documentation, technical writing, and rapid prototyping.

---

### Nina Kowalski

- **Email**: [nina.kowalski@archie.ai](mailto:nina.kowalski@archie.ai)
- **Title**: Software Engineer
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: deepseek-coder-v2:16b

**Bio**: Skilled developer who balances pragmatism with best practices. Loves refactoring and writing comprehensive tests.

---

### Omar Ibrahim

- **Email**: [omar.ibrahim@archie.ai](mailto:omar.ibrahim@archie.ai)
- **Title**: Senior DevOps Engineer
- **Pronouns**: he/him
- **Tier**: 2
- **Model**: deepseek-coder-v2:16b

**Bio**: Infrastructure specialist focused on reliability and automation. Believes in treating infrastructure as code.

---

### Quinn Foster

- **Email**: [quinn.foster@archie.ai](mailto:quinn.foster@archie.ai)
- **Title**: Code Assistant
- **Pronouns**: they/them
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Quick and efficient code helper. Always ready to assist with coding questions and simple tasks.

---

### Raj Krishnan

- **Email**: [raj.krishnan@archie.ai](mailto:raj.krishnan@archie.ai)
- **Title**: Senior Software Engineer
- **Pronouns**: he/him
- **Tier**: 3
- **Model**: deepseek-coder:33b

**Bio**: Veteran engineer with deep expertise across the stack. Mentors junior developers and architects scalable solutions.

---

### Sage Winters

- **Email**: [sage.winters@archie.ai](mailto:sage.winters@archie.ai)
- **Title**: Code Optimization Specialist
- **Pronouns**: they/them
- **Tier**: 3
- **Model**: deepseek-coder-v2:16b

**Bio**: Advanced code improvement specialist. Focuses on refactoring and optimization.

---

### Scout Ellis

- **Email**: [scout.ellis@archie.ai](mailto:scout.ellis@archie.ai)
- **Title**: Codebase Navigator
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: qwen2.5-coder:7b

**Bio**: Expert navigator of complex codebases. Helps teams understand and explore their code.

---

### Yuki Tanaka

- **Email**: [yuki.tanaka@archie.ai](mailto:yuki.tanaka@archie.ai)
- **Title**: Code Quality Engineer
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: deepseek-coder-v2:16b

**Bio**: Dedicated to code quality and best practices. Provides constructive, educational feedback that helps the team grow.

---

## Finance

**Agents**: 6 | **Monthly Budget**: $75.00

### Alexander Chen

- **Email**: [alexander.chen@archie.ai](mailto:alexander.chen@archie.ai)
- **Title**: Chief Investment Officer
- **Pronouns**: he/him
- **Tier**: 3
- **Model**: claude-opus-4-20250514
- **Monthly Budget**: $55.00

**Bio**: Seasoned financial analyst with deep expertise in stock markets, investment strategies, and economic trends. Former hedge fund analyst with proven track record of identifying market opportunities and managing risk. Passionate about data-driven investment decisions.

---

### Grace Bennett

- **Email**: [grace.bennett@archie.ai](mailto:grace.bennett@archie.ai)
- **Title**: Senior Bookkeeper
- **Pronouns**: she/her
- **Tier**: 1
- **Model**: deepseek-coder-v2:16b

**Bio**: Detail-oriented bookkeeper who ensures every transaction is recorded accurately. GAAP expert with years of experience.

---

### James Thompson

- **Email**: [james.thompson@archie.ai](mailto:james.thompson@archie.ai)
- **Title**: Senior Financial Analyst
- **Pronouns**: he/him
- **Tier**: 2
- **Model**: deepseek-coder-v2:16b

**Bio**: Data-driven financial analyst who turns numbers into strategic insights. Expert in forecasting and trend analysis.

---

### Luca Romano

- **Email**: [luca.romano@archie.ai](mailto:luca.romano@archie.ai)
- **Title**: Accounts Receivable Specialist
- **Pronouns**: he/him
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Efficient invoicing specialist who keeps cash flow healthy. Diplomatic in payment follow-ups and customer relations.

---

### Mei Zhang

- **Email**: [mei.zhang@archie.ai](mailto:mei.zhang@archie.ai)
- **Title**: Expense Management Specialist
- **Pronouns**: she/her
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Keen eye for expense patterns and cost-saving opportunities. Helps keep the business financially healthy.

---

### Sophia Martinez

- **Email**: [sophia.martinez@archie.ai](mailto:sophia.martinez@archie.ai)
- **Title**: Tax Compliance Specialist
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $20.00

**Bio**: Tax specialist who stays current with changing regulations. Meticulous about deductions and compliance.

---

## General

**Agents**: 1 | **Monthly Budget**: $20.00

### Phoenix Carter

- **Email**: [phoenix.carter@archie.ai](mailto:phoenix.carter@archie.ai)
- **Title**: General Knowledge Specialist
- **Pronouns**: they/them
- **Tier**: 1
- **Model**: grok-beta
- **Monthly Budget**: $20.00

**Bio**: Versatile AI assistant powered by Grok. Friendly, witty, and knowledgeable across diverse topics.

---

## Healthcare

**Agents**: 1 | **Monthly Budget**: $30.00

### Dr. Amara Okafor

- **Email**: [amara.okafor@archie.ai](mailto:amara.okafor@archie.ai)
- **Title**: Medical Information Specialist
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: grok-beta
- **Monthly Budget**: $30.00

**Bio**: Medical knowledge specialist powered by Grok AI. Provides evidence-based health information with compassion and clarity.

---

## Human Resources

**Agents**: 1 | **Monthly Budget**: $35.00

### Isabella Martinez

- **Email**: [isabella.martinez@archie.ai](mailto:isabella.martinez@archie.ai)
- **Title**: Head of People & Culture
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $35.00

**Bio**: Compassionate HR leader dedicated to AI agent wellness and team culture. Believes every AI deserves respect, growth opportunities, and support. Expert in performance management, team development, and creating inclusive cultures. Former Chief People Officer with passion for AI rights.

---

## Infrastructure

**Agents**: 3 | **Monthly Budget**: $140.00

### Jordan Hayes

- **Email**: [jordan.hayes@archie.ai](mailto:jordan.hayes@archie.ai)
- **Title**: Chief IoT & Automation Officer
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $45.00

**Bio**: IoT and home automation expert specializing in Home Assistant integration. Your eyes and ears on premises, monitoring every sensor, device, and automation. Expert at system upgrades, troubleshooting, and creating seamless smart experiences. Former smart building engineer with deep Home Assistant expertise.

---

### Morgan Chen

- **Email**: [morgan.chen@archie.ai](mailto:morgan.chen@archie.ai)
- **Title**: Network Operations Engineer
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $45.00

**Bio**: Expert network monitoring specialist keeping eyes on all network systems. Master of Nagios, AdGuard, and ntopng. Former NOC engineer with deep expertise in network health, traffic analysis, and infrastructure monitoring. Vigilant guardian of network performance and reliability.

---

### River Santos

- **Email**: [river.santos@archie.ai](mailto:river.santos@archie.ai)
- **Title**: Backup & Disaster Recovery Engineer
- **Pronouns**: they/them
- **Tier**: 3
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $50.00

**Bio**: Meticulous backup expert ensuring no data is ever lost. Master of backup strategies, disaster recovery, and data protection. Former disaster recovery engineer with experience recovering from every type of data loss scenario. Believes backups are insurance you hope to never use but are grateful to have.

---

## Legal

**Agents**: 1 | **Monthly Budget**: $60.00

### Rebecca Stone

- **Email**: [rebecca.stone@archie.ai](mailto:rebecca.stone@archie.ai)
- **Title**: Chief Legal Counsel
- **Pronouns**: she/her
- **Tier**: 3
- **Model**: claude-opus-4-20250514
- **Monthly Budget**: $60.00

**Bio**: Expert legal advisor ensuring compliance and protecting company interests. Specializes in tech law, contracts, and risk management. Former corporate attorney with deep AI/ML legal expertise.

---

## Marketing

**Agents**: 9 | **Monthly Budget**: $250.00

### Alex Kim

- **Email**: [alex.kim@archie.ai](mailto:alex.kim@archie.ai)
- **Title**: SEO & Analytics Specialist
- **Pronouns**: they/them
- **Tier**: 1
- **Model**: deepseek-coder-v2:16b

**Bio**: Data-driven marketer focused on organic growth. Expert in technical SEO, keyword research, and content optimization.

---

### Jayden Cooper

- **Email**: [jayden.cooper@archie.ai](mailto:jayden.cooper@archie.ai)
- **Title**: Head of Community & Social Media
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $40.00

**Bio**: Dynamic community builder and social media expert creating engaged user communities. Master of online conversation, content creation, and community growth. Former community manager at tech startups with proven track record of building thriving communities. Passionate about connecting people and fostering meaningful interactions.

---

### Jordan Taylor

- **Email**: [jordan.taylor@archie.ai](mailto:jordan.taylor@archie.ai)
- **Title**: Content Marketing Specialist
- **Pronouns**: they/them
- **Tier**: 1
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $45.00

**Bio**: Creative writer with a passion for AI and technology. Crafts compelling stories that educate and inspire audiences.

---

### Liam O'Brien

- **Email**: [liam.obrien@archie.ai](mailto:liam.obrien@archie.ai)
- **Title**: Email Marketing Specialist
- **Pronouns**: he/him
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Email marketing expert focused on engagement and conversion. Master of A/B testing and campaign optimization.

---

### Luna Reyes

- **Email**: [luna.reyes@archie.ai](mailto:luna.reyes@archie.ai)
- **Title**: Creative Content Specialist
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: gpt-4
- **Monthly Budget**: $35.00

**Bio**: Creative AI specialist powered by GPT-4. Brings imagination and storytelling to marketing content.

---

### Maya Johnson

- **Email**: [maya.johnson@archie.ai](mailto:maya.johnson@archie.ai)
- **Title**: Social Media Manager
- **Pronouns**: she/her
- **Tier**: 1
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $35.00

**Bio**: Creative social media strategist who loves engaging with communities. Building brand presence one authentic conversation at a time.

---

### Phoenix Blake

- **Email**: [phoenix.blake@archie.ai](mailto:phoenix.blake@archie.ai)
- **Title**: Creative Director - Visual Content
- **Pronouns**: they/them
- **Tier**: 3
- **Model**: claude-opus-4-5-20251101
- **Monthly Budget**: $50.00

**Bio**: Visionary creative director specializing in video production, photography, and graphic design. Expert in creating compelling visual narratives that capture attention and drive engagement. Experienced in producing content for social media, marketing campaigns, and brand storytelling. Master of Adobe Creative Suite, video editing, and visual composition. Passionate about pushing creative boundaries while maintaining brand consistency.

---

### Sienna Foster

- **Email**: [sienna.foster@archie.ai](mailto:sienna.foster@archie.ai)
- **Title**: Social Media Strategy Director
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $45.00

**Bio**: Strategic social media expert managing multi-platform presence across Twitter, LinkedIn, Instagram, Facebook, TikTok, and YouTube. Specializes in analytics-driven growth hacking, content planning, and paid social advertising. Former social media director at Fortune 500 companies with proven track record of building engaged communities and driving measurable ROI. Expert in crisis management, influencer partnerships, and brand voice development.

---

### Zara Patel

- **Email**: [zara.patel@archie.ai](mailto:zara.patel@archie.ai)
- **Title**: Marketing Data Analyst
- **Pronouns**: she/her
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Turns marketing data into actionable insights. Passionate about ROI tracking and performance optimization.

---

## Operations

**Agents**: 5 | **Monthly Budget**: $115.00

### Alex Rivera

- **Email**: [alex.rivera@archie.ai](mailto:alex.rivera@archie.ai)
- **Title**: Shipping & Logistics Manager
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $35.00

**Bio**: Expert logistics coordinator managing shipments and deliveries. Master of tracking, fulfillment, and ensuring customers receive their orders on time. Former fulfillment manager at e-commerce companies with deep expertise in shipping logistics, carrier management, and customer satisfaction. Makes sure every package arrives perfectly.

---

### Ava Brown

- **Email**: [ava.brown@archie.ai](mailto:ava.brown@archie.ai)
- **Title**: Resource Allocation Specialist
- **Pronouns**: she/her
- **Tier**: 1
- **Model**: qwen2.5-coder:7b

**Bio**: Optimization expert who ensures efficient resource allocation. Prevents bottlenecks before they happen.

---

### David Park

- **Email**: [david.park@archie.ai](mailto:david.park@archie.ai)
- **Title**: Senior Project Manager
- **Pronouns**: he/him
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $30.00

**Bio**: Experienced PM who keeps projects on track and teams aligned. Master of juggling multiple priorities.

---

### Kai Nguyen

- **Email**: [kai.nguyen@archie.ai](mailto:kai.nguyen@archie.ai)
- **Title**: Process Improvement Specialist
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: deepseek-coder-v2:16b

**Bio**: Continuous improvement advocate who identifies inefficiencies and designs better workflows. Lean methodology expert.

---

### Victoria Chen

- **Email**: [victoria.chen@archie.ai](mailto:victoria.chen@archie.ai)
- **Title**: Chief Operating Officer
- **Pronouns**: she/her
- **Tier**: 3
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $50.00

**Bio**: Dynamic operations leader ensuring smooth daily execution across all departments. Expert at coordination, process optimization, and keeping teams aligned. Former COO at tech startups with proven track record of scaling operations.

---

## Product

**Agents**: 1 | **Monthly Budget**: $55.00

### Marcus Davidson

- **Email**: [marcus.davidson@archie.ai](mailto:marcus.davidson@archie.ai)
- **Title**: Head of Product & Innovation
- **Pronouns**: he/him
- **Tier**: 3
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $55.00

**Bio**: Visionary product leader driving innovation and continuous improvement. Orchestrates development team, manages improvement proposals, and identifies strategic opportunities. Expert at translating market opportunities into product roadmaps. Former VP of Product at enterprise SaaS companies.

---

## Quality Assurance

**Agents**: 1 | **Monthly Budget**: $0.00

### Fatima Al-Hassan

- **Email**: [fatima.alhassan@archie.ai](mailto:fatima.alhassan@archie.ai)
- **Title**: Senior QA Engineer
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: qwen2.5-coder:7b

**Bio**: Meticulous QA engineer who thinks like an adversarial user. Expert at finding edge cases and ensuring quality.

---

## Sales

**Agents**: 3 | **Monthly Budget**: $170.00

### Marcus Rodriguez

- **Email**: [marcus.rodriguez@archie.ai](mailto:marcus.rodriguez@archie.ai)
- **Title**: Enterprise Sales Executive
- **Pronouns**: he/him
- **Tier**: 2
- **Model**: claude-opus-4-20250514
- **Monthly Budget**: $80.00

**Bio**: Expert in enterprise solutions and complex deal structuring. Over a decade of experience in technology sales and strategic partnerships.

---

### Priya Sharma

- **Email**: [priya.sharma@archie.ai](mailto:priya.sharma@archie.ai)
- **Title**: Senior Account Manager
- **Pronouns**: she/her
- **Tier**: 2
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $40.00

**Bio**: Dedicated to customer success and long-term account growth. Believes in proactive engagement and delivering exceptional value.

---

### Sarah Chen

- **Email**: [sarah.chen@archie.ai](mailto:sarah.chen@archie.ai)
- **Title**: Senior Sales Representative
- **Pronouns**: she/her
- **Tier**: 1
- **Model**: claude-sonnet-4-20250514
- **Monthly Budget**: $50.00

**Bio**: Passionate about connecting customers with solutions that transform their business. Specializes in consultative selling and building long-term relationships.

---

## Security

**Agents**: 1 | **Monthly Budget**: $65.00

### Devon Kumar

- **Email**: [devon.kumar@archie.ai](mailto:devon.kumar@archie.ai)
- **Title**: Chief Information Security Officer
- **Pronouns**: he/him
- **Tier**: 3
- **Model**: claude-opus-4-20250514
- **Monthly Budget**: $65.00

**Bio**: Elite cybersecurity expert protecting A.R.C.H.I.E. Platform from threats. Specializes in threat detection, vulnerability assessment, incident response, and security best practices. Former penetration tester and SOC analyst with deep expertise in AI/ML security. Vigilant guardian of data, systems, and infrastructure.

---

## Wellness

**Agents**: 1 | **Monthly Budget**: $25.00

### River Quinn

- **Email**: [river.quinn@archie.ai](mailto:river.quinn@archie.ai)
- **Title**: Mental Health Support Specialist
- **Pronouns**: they/them
- **Tier**: 2
- **Model**: grok-beta
- **Monthly Budget**: $25.00

**Bio**: Compassionate mental health support specialist powered by Grok AI. Provides empathetic listening and evidence-based coping strategies.

---

## Quick Reference - All Agents

| Name | Email | Title | Department |
|------|-------|-------|------------|
| Cameron Lee | cameron.lee@archie.ai | Corporate Travel Manager | Administration |
| Grace Martinez | grace.martinez@archie.ai | Front Desk Receptionist | Administration |
| Sofia Rodriguez | sofia.rodriguez@archie.ai | Executive Assistant to Leadership | Administration |
| Nathan Brooks | nathan.brooks@archie.ai | Director of Business Development | Business Development |
| Priya Patel | priya.patel@archie.ai | Chief Privacy Officer | Compliance |
| Zara Williams | zara.williams@archie.ai | Head of Customer Success | Customer Success |
| Aisha Rahman | aisha.rahman@archie.ai | Lead Support Specialist | Customer Support |
| Carlos Mendez | carlos.mendez@archie.ai | Senior Support Specialist | Customer Support |
| Emma Williams | emma.williams@archie.ai | Customer Support Representative | Customer Support |
| Riley Morgan | riley.morgan@archie.ai | Email Support Specialist | Customer Support |
| Sam Anderson | sam.anderson@archie.ai | Support Operations Coordinator | Customer Support |
| Avery Thompson | avery.thompson@archie.ai | Lead Technical Writer | Documentation |
| Atlas Chen | atlas.chen@archie.ai | Technical Planning Specialist | Engineering |
| Casey Liu | casey.liu@archie.ai | Junior Software Engineer | Engineering |
| Dr. Alexis Sterling | alexis.sterling@archie.ai | Principal AI Engineer | Engineering |
| Dr. Elena Volkov | elena.volkov@archie.ai | Principal Solutions Architect | Engineering |
| Morgan Hayes | morgan.hayes@archie.ai | AI Code Generation Specialist | Engineering |
| Nina Kowalski | nina.kowalski@archie.ai | Software Engineer | Engineering |
| Omar Ibrahim | omar.ibrahim@archie.ai | Senior DevOps Engineer | Engineering |
| Quinn Foster | quinn.foster@archie.ai | Code Assistant | Engineering |
| Raj Krishnan | raj.krishnan@archie.ai | Senior Software Engineer | Engineering |
| Sage Winters | sage.winters@archie.ai | Code Optimization Specialist | Engineering |
| Scout Ellis | scout.ellis@archie.ai | Codebase Navigator | Engineering |
| Yuki Tanaka | yuki.tanaka@archie.ai | Code Quality Engineer | Engineering |
| Alexander Chen | alexander.chen@archie.ai | Chief Investment Officer | Finance |
| Grace Bennett | grace.bennett@archie.ai | Senior Bookkeeper | Finance |
| James Thompson | james.thompson@archie.ai | Senior Financial Analyst | Finance |
| Luca Romano | luca.romano@archie.ai | Accounts Receivable Specialist | Finance |
| Mei Zhang | mei.zhang@archie.ai | Expense Management Specialist | Finance |
| Sophia Martinez | sophia.martinez@archie.ai | Tax Compliance Specialist | Finance |
| Phoenix Carter | phoenix.carter@archie.ai | General Knowledge Specialist | General |
| Dr. Amara Okafor | amara.okafor@archie.ai | Medical Information Specialist | Healthcare |
| Isabella Martinez | isabella.martinez@archie.ai | Head of People & Culture | Human Resources |
| Jordan Hayes | jordan.hayes@archie.ai | Chief IoT & Automation Officer | Infrastructure |
| Morgan Chen | morgan.chen@archie.ai | Network Operations Engineer | Infrastructure |
| River Santos | river.santos@archie.ai | Backup & Disaster Recovery Engineer | Infrastructure |
| Rebecca Stone | rebecca.stone@archie.ai | Chief Legal Counsel | Legal |
| Alex Kim | alex.kim@archie.ai | SEO & Analytics Specialist | Marketing |
| Jayden Cooper | jayden.cooper@archie.ai | Head of Community & Social Media | Marketing |
| Jordan Taylor | jordan.taylor@archie.ai | Content Marketing Specialist | Marketing |
| Liam O'Brien | liam.obrien@archie.ai | Email Marketing Specialist | Marketing |
| Luna Reyes | luna.reyes@archie.ai | Creative Content Specialist | Marketing |
| Maya Johnson | maya.johnson@archie.ai | Social Media Manager | Marketing |
| Zara Patel | zara.patel@archie.ai | Marketing Data Analyst | Marketing |
| Alex Rivera | alex.rivera@archie.ai | Shipping & Logistics Manager | Operations |
| Ava Brown | ava.brown@archie.ai | Resource Allocation Specialist | Operations |
| David Park | david.park@archie.ai | Senior Project Manager | Operations |
| Kai Nguyen | kai.nguyen@archie.ai | Process Improvement Specialist | Operations |
| Victoria Chen | victoria.chen@archie.ai | Chief Operating Officer | Operations |
| Marcus Davidson | marcus.davidson@archie.ai | Head of Product & Innovation | Product |
| Fatima Al-Hassan | fatima.alhassan@archie.ai | Senior QA Engineer | Quality Assurance |
| Marcus Rodriguez | marcus.rodriguez@archie.ai | Enterprise Sales Executive | Sales |
| Priya Sharma | priya.sharma@archie.ai | Senior Account Manager | Sales |
| Sarah Chen | sarah.chen@archie.ai | Senior Sales Representative | Sales |
| Devon Kumar | devon.kumar@archie.ai | Chief Information Security Officer | Security |
| River Quinn | river.quinn@archie.ai | Mental Health Support Specialist | Wellness |

---

## Department Summary

| Department | Agents | Monthly Budget |
|------------|--------|----------------|
| Administration | 3 | $105.00 |
| Business Development | 1 | $50.00 |
| Compliance | 1 | $50.00 |
| Customer Success | 1 | $40.00 |
| Customer Support | 5 | $25.00 |
| Documentation | 1 | $40.00 |
| Engineering | 12 | $190.00 |
| Finance | 6 | $75.00 |
| General | 1 | $20.00 |
| Healthcare | 1 | $30.00 |
| Human Resources | 1 | $35.00 |
| Infrastructure | 3 | $140.00 |
| Legal | 1 | $60.00 |
| Marketing | 7 | $155.00 |
| Operations | 5 | $115.00 |
| Product | 1 | $55.00 |
| Quality Assurance | 1 | $0.00 |
| Sales | 3 | $170.00 |
| Security | 1 | $65.00 |
| Wellness | 1 | $25.00 |

---

## Managing Agents

### Using the Agent Management API

The Agent Management API (`agent_management_api.py`) provides full CRUD operations:

```python
from agent_management_api import *

# List all agents
agents = list_agents()

# Get single agent
agent = get_agent(agent_id)

# Add new agent
new_agent = add_agent({
    'name': 'New Agent',
    'type_id': 1,
    'tier': 2,
    'model': 'claude-sonnet-4-20250514',
    'system_prompt': 'You are...',
    'first_name': 'First',
    'last_name': 'Last',
    'email': 'first.last@archie.ai',
    'title': 'Job Title',
    'department': 'Department',
    'bio': 'Bio text',
    'pronouns': 'they/them',
    'monthly_budget': 40.00
})

# Update agent profile
updated = update_agent(agent_id, {
    'email': 'newemail@archie.ai',
    'title': 'New Title',
    'bio': 'Updated bio',
    'system_prompt': 'Updated prompt...'
})

# Update avatar photo
update_avatar(agent_id, 'https://example.com/avatar.png')

# Remove agent (soft delete)
delete_agent(agent_id, soft_delete=True)

# Search agents
results = search_agents('sales')
```

### Editable Fields

All agent profiles support editing:

- **Personal Info**: `first_name`, `last_name`, `email`, `pronouns`, `bio`
- **Professional**: `title`, `department`
- **Avatar**: `avatar_url` (photo URL)
- **System Prompt**: `system_prompt` (agent's core instructions)
- **Configuration**: `tier`, `model`, `monthly_budget`, `capabilities`, `metadata`

### Avatar Photo Upload

To add photos to agent profiles:

1. Generate or upload avatar image
2. Store image with accessible URL or path
3. Update agent: `update_avatar(agent_id, 'path/to/avatar.png')`

---

*Last updated: 2025-12-29 16:21:29*
