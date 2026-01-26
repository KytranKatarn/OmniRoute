# Admin DIRECTORY vs Public /directory - Comparison

**Date:** 2025-12-31

---

## 📊 **Side-by-Side Comparison**

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ADMIN PANEL - DIRECTORY SECTION                                       │
│  Route: /tools/admin/ → DIRECTORY nav item                             │
│  API: /tools/team-management/                                     │
│  Access: ADMIN ONLY                                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  👥 AGENT DIRECTORY                                                      │
│  Complete directory of all 73 AI agents in the organization            │
│                                                                          │
│  [Refresh] [All Departments] [Export]                                  │
│                                                                          │
│  Statistics:                                                            │
│  ┌──────────┬──────────┬──────────┬──────────┐                        │
│  │ 73 AGENTS│ 20 DEPTS │ $1540/mo │  $245.67 │                        │
│  │   TOTAL  │   TOTAL  │  BUDGET  │   SPENT  │                        │
│  └──────────┴──────────┴──────────┴──────────┘                        │
│                                                                          │
│  [Engineering] [Marketing] [Finance] ...                               │
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════╗      │
│  ║  [Photo] Sarah Chen (she/her)                                ║      │
│  ║  Chief Marketing Officer                                     ║      │
│  ║  Marketing • Tier 3 ⭐⭐⭐                                    ║      │
│  ║                                                               ║      │
│  ║  ✅ TECHNICAL DETAILS SHOWN:                                 ║      │
│  ║  📊 Model: claude-sonnet-4-5                                 ║      │
│  ║  💰 Monthly Budget: $50.00                                   ║      │
│  ║  📈 Total Cost: $12.45 (24.9% used)                          ║      │
│  ║  🔢 Tokens Used: 125,000                                     ║      │
│  ║  ⚙️  Worker Type: CONTRACT (PAID)                            ║      │
│  ║  🔌 API Provider: anthropic                                  ║      │
│  ║  🎯 Activity: Active (last used 2 days ago)                  ║      │
│  ║                                                               ║      │
│  ║  [View Full Details] [Execute Task] [View Metrics]           ║      │
│  ╚══════════════════════════════════════════════════════════════╝      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

vs

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PUBLIC /directory PAGE                                                 │
│  Route: /directory                                                      │
│  API: /api/directory                                                    │
│  Access: PUBLIC (no login!)                                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  MEET OUR TEAM                                                          │
│  AI-Powered Excellence. Human-Like Service.                             │
│  KYTRAN EMPOWERMENT - WHERE INNOVATION MEETS INTELLIGENCE               │
│                                                                          │
│  Statistics:                                                            │
│  ┌──────────┬──────────┬──────────┬──────────┐                        │
│  │    73    │    20    │   24/7   │    AI    │                        │
│  │  MEMBERS │  DEPTS   │  AVAIL   │ POWERED  │                        │
│  └──────────┴──────────┴──────────┴──────────┘                        │
│                                                                          │
│  [All Departments] [Engineering] [Marketing] [Finance] ...             │
│                                                                          │
│  ╔══════════════════════════════════════════════════════════════╗      │
│  ║  [Photo] Sarah Chen (she/her)                                ║      │
│  ║  Chief Marketing Officer                                     ║      │
│  ║  Marketing                                                    ║      │
│  ║                                                               ║      │
│  ║  Sarah leads our marketing initiatives with 15+ years        ║      │
│  ║  of experience in digital strategy, brand development,       ║      │
│  ║  and data-driven campaigns. Expert in SEO, content           ║      │
│  ║  marketing, and social media growth strategies.              ║      │
│  ║                                                               ║      │
│  ║  Specialties:                                                 ║      │
│  ║  [SEO] [Content Strategy] [Brand Development]                ║      │
│  ║  [Social Media] [Analytics]                                   ║      │
│  ║                                                               ║      │
│  ║  📧 sarah.chen@kytranempowerment.com                          ║      │
│  ║                                                               ║      │
│  ║  ❌ NO TECHNICAL DETAILS (hidden):                            ║      │
│  ║  • No AI model shown                                          ║      │
│  ║  • No costs/budgets                                           ║      │
│  ║  • No tokens/usage                                            ║      │
│  ║  • No "contract/internal" labels                              ║      │
│  ║  • No API provider info                                       ║      │
│  ╚══════════════════════════════════════════════════════════════╝      │
│                                                                          │
│  ╔═══════════════════════════════════════════════════════════════╗     │
│  ║              HIRE OUR AI TEAM                                 ║     │
│  ║  Our AI specialists are available 24/7 to help your          ║     │
│  ║  business grow. From marketing to engineering, customer      ║     │
│  ║  support to data analysis.                                    ║     │
│  ║                                                                ║     │
│  ║         [GET STARTED]  [EXPLORE SERVICES]                     ║     │
│  ╚═══════════════════════════════════════════════════════════════╝     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🔑 **Key Differences:**

| Feature | Admin DIRECTORY | Public /directory |
|---------|----------------|-------------------|
| **Access** | Admin only | Public (anyone) |
| **Login Required** | Yes | No |
| **Route** | `/tools/admin/` (section) | `/directory` (standalone page) |
| **API Endpoint** | `/tools/team-management/` | `/api/directory` |
| **Purpose** | Operational management | Marketing/SAAS |
| **AI Model Info** | ✅ Shown | ❌ Hidden |
| **Costs/Budget** | ✅ Shown | ❌ Hidden |
| **Token Usage** | ✅ Shown | ❌ Hidden |
| **Worker Type** | ✅ Shown | ❌ Hidden |
| **System Prompts** | ✅ Shown | ❌ Hidden |
| **Technical Details** | ✅ All shown | ❌ All hidden |
| **Professional Bio** | ✅ Shown | ✅ Shown |
| **Email** | ✅ Shown | ✅ Shown |
| **Phone** | ✅ Shown | ✅ Shown |
| **Avatar/Photo** | ✅ Shown | ✅ Shown |
| **Department** | ✅ Shown | ✅ Shown |
| **Specialties** | ✅ Shown | ✅ Shown |
| **Export CSV** | ✅ Yes | ❌ No |
| **Execute Tasks** | ✅ Yes | ❌ No |
| **View Metrics** | ✅ Yes | ❌ No |
| **Edit Profiles** | ✅ Yes | ❌ No |
| **"Hire Our Team" CTA** | ❌ No | ✅ Yes |

---

## 🔧 **Technical Implementation:**

### **Admin DIRECTORY (Internal):**

```javascript
// Located in: templates/tools/admin.html
// Function: loadAgentDirectory()

async function loadAgentDirectory() {
    const response = await fetch('/tools/team-management/');
    const data = await response.json();

    // data.agents contains FULL details:
    {
        id: 1,
        name: "Sarah Chen",
        title: "Chief Marketing Officer",
        department: "Marketing",
        bio: "...",

        // ADMIN-ONLY FIELDS:
        model: "claude-sonnet-4-5",
        tier: 3,
        worker_type: "contract",
        monthly_budget: 50.00,
        total_cost: 12.45,
        total_tokens_used: 125000,
        system_prompt: "You are Sarah...",
        capabilities: {...},
        budget_used_percent: 24.9,
        activity_status: "active"
    }
}
```

### **Public /directory (External):**

```javascript
// Located in: templates/directory.html
// Function: fetch('/api/directory')

fetch('/api/directory')
    .then(r => r.json())
    .then(data => {
        // data.members contains FILTERED info only:
        {
            id: 1,
            full_name: "Sarah Chen",
            title: "Chief Marketing Officer",
            department: "Marketing",
            bio: "...",
            email: "sarah.chen@kytranempowerment.com",
            specialties: ["SEO", "Content Strategy"],
            pronouns: "she/her"

            // NO TECHNICAL FIELDS - filtered out by backend
        }
    });
```

---

## 🛡️ **Security & Privacy:**

### **What's Protected:**

The `/api/directory` endpoint **explicitly filters out** sensitive data:

```python
# app.py - /api/directory endpoint

cur.execute("""
    SELECT
        id,
        name,
        first_name || ' ' || last_name as full_name,
        first_name,
        last_name,
        email,
        title,
        department,
        pronouns,
        bio,
        avatar_url,
        tier,
        CASE
            WHEN capabilities::text LIKE '%specialties%'
            THEN (capabilities->'specialties')::text
            ELSE '[]'
        END as specialties
    FROM agents
    WHERE status = 'active'
    AND (visibility IN ('public', 'dashboard') OR visibility IS NULL)
    -- ⚠️ NOTICE: No model, costs, system_prompt, tokens, etc.
""")
```

**What gets EXCLUDED from public API:**
- ❌ `model` (claude-sonnet-4-5, gpt-4, etc.)
- ❌ `worker_type` (internal/contract)
- ❌ `api_provider` (anthropic, openai)
- ❌ `monthly_budget`
- ❌ `total_cost`
- ❌ `total_tokens_used`
- ❌ `system_prompt`
- ❌ `capabilities` (except specialties)
- ❌ `budget_alert_threshold`
- ❌ Any cost/usage metrics

---

## 🎯 **Use Cases:**

### **When to Use ADMIN DIRECTORY:**

```
Scenario: You need to...
✅ See which agents are over budget
✅ Check token usage for last month
✅ Execute a task with a specific agent
✅ View technical performance metrics
✅ Export full agent details to CSV
✅ Manage agent budgets and tiers
✅ See which agents use paid APIs
```

### **When to Use PUBLIC /directory:**

```
Scenario: Customers/prospects want to...
✅ See who works at Kytran Empowerment
✅ Browse team by department
✅ Read professional bios
✅ Contact team members
✅ Understand company capabilities
✅ Be impressed by team size (73!)
✅ Consider hiring your services
```

---

## 📊 **Data Flow:**

```
Database: agents table (73 records)
    │
    ├─────────────────────────┬─────────────────────────┐
    ▼                         ▼                         ▼
Admin Query              Public Query             Display
(Full Access)           (Filtered)
    │                         │                         │
    │ SELECT *                │ SELECT id, name,        │
    │ FROM agents             │   first_name,           │
    │                         │   last_name,            │
    │                         │   title,                │
    │                         │   department,           │
    │                         │   bio,                  │
    │                         │   email,                │
    │                         │   specialties           │
    │                         │ FROM agents             │
    │                         │ WHERE visibility        │
    │                         │   IN ('public')         │
    ▼                         ▼                         ▼
Admin DIRECTORY         Public /directory
Shows: ALL fields       Shows: Safe fields only
Purpose: Management     Purpose: Marketing
Access: Admin only      Access: Everyone
```

---

## 💡 **Summary:**

**Same Database → Different Views → Different Purposes**

1. **Admin DIRECTORY** = Your operational dashboard
   - Full technical details
   - Manage agents, budgets, performance
   - Internal use only

2. **Public /directory** = Your SAAS marketing page
   - Professional team roster
   - Builds company credibility
   - Hides all AI/technical details
   - Customer-facing

**Think of it like:**
- Admin = "Behind the scenes" control panel
- Public = "Front of house" presentation

**Both pull from the same 73 agents, just showing different information!**

---

## ✏️ **Editing Agent Profiles:**

### **How Editing Works:**

Admins can edit agent profiles directly from the ADMIN DIRECTORY section, and changes **automatically sync** to the public /directory page since both query the same database.

### **Editable Fields:**

From the ADMIN DIRECTORY, you can edit:
- ✏️ **First Name** - Updates everywhere
- ✏️ **Last Name** - Updates everywhere
- ✏️ **Email** - Updates both admin and public views
- ✏️ **Phone** - Updates both admin and public views
- ✏️ **Profile Picture (Avatar URL)** - Changes profile photo everywhere with live preview

### **How to Edit:**

```
1. Go to: /tools/admin/ → DIRECTORY section
2. Click on any agent card
3. Click "EDIT PROFILE" button (green button, top-right)
4. Update fields in the edit modal:
   • First Name, Last Name
   • Email, Phone
   • Profile Picture (with live preview!)
5. Click "SAVE CHANGES"
6. ✅ Changes instantly sync to public /directory
```

### **Profile Picture Editing:**

The edit modal includes a **live preview feature** for profile pictures:

```
┌─────────────────────────────────────────┐
│  CURRENT:          PREVIEW:             │
│  [Old Avatar]      [New Avatar]         │
│                                          │
│  Profile Picture (Avatar URL)           │
│  ┌────────────────────────────────────┐ │
│  │ https://i.pravatar.cc/150?img=5   │ │
│  └────────────────────────────────────┘ │
│                                          │
│  💡 Tips:                                │
│  • Paste any image URL from the web     │
│  • Try: https://i.pravatar.cc/150?img=1 │
│  • Leave blank for auto-generated avatar│
└─────────────────────────────────────────┘
```

**Avatar Sources:**
- **Custom URL:** Paste any image URL (JPG, PNG, GIF, SVG)
- **Stock Avatars:** Use `https://i.pravatar.cc/150?img=1` (change 1-70)
- **Auto-Generated:** Leave blank = DiceBear generates unique avatar from name
- **Preview Updates:** See changes in real-time as you type

### **Technical Flow:**

```python
# Admin edits profile
PUT /tools/team-management//<id>
{
    "first_name": "Sarah",
    "last_name": "Chen",
    "email": "sarah.chen@kytranempowerment.com",
    "phone": "+1 (555) 123-4567",
    "avatar_url": "https://example.com/sarah.jpg"
}

# Update happens in database
UPDATE agents SET
    first_name = 'Sarah',
    last_name = 'Chen',
    email = 'sarah.chen@kytranempowerment.com',
    phone = '+1 (555) 123-4567',
    avatar_url = 'https://example.com/sarah.jpg'
WHERE id = <id>

# Both endpoints now return updated data:
# - /tools/team-management/ (admin view - all fields)
# - /api/directory (public view - filtered fields including phone)
```

### **What Gets Updated Where:**

| Field | Admin DIRECTORY | Public /directory | Notes |
|-------|----------------|-------------------|-------|
| First Name | ✅ Updates | ✅ Updates | Instant sync |
| Last Name | ✅ Updates | ✅ Updates | Instant sync |
| Email | ✅ Updates | ✅ Updates | Instant sync |
| Phone | ✅ Updates | ✅ Updates | Instant sync |
| Avatar URL | ✅ Updates | ✅ Updates | Instant sync |
| Model | ❌ Not editable | ❌ Hidden | Requires DB migration |
| Costs | ❌ Not editable | ❌ Hidden | Auto-calculated |

### **Data Safety:**

- ✅ Only edits **profile fields** (name, email, phone, avatar)
- ✅ Does NOT allow editing costs, budgets, or system prompts
- ✅ Does NOT allow deleting agents
- ✅ Changes are logged with `updated_at` timestamp
- ✅ No breaking changes to technical configurations

---

**Last Updated:** 2025-12-31
**Maintained By:** A.R.C.H.I.E.
