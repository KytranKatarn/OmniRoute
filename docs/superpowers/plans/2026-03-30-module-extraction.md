# Module Extraction — Phase 1 + 1b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete 5 duplicate monolith modules already in KBS, disable 2 more with dependencies, clean up the dashboard, and add standalone product launcher cards.

**Architecture:** Remove module directories, deregister from module_registry.py and rbac.py, delete templates. For modules with external dependencies (social_media, google_work_suite), disable from dashboard but keep code until dependencies are refactored. Add "external" module type to registry for standalone product launcher cards.

**Tech Stack:** Flask, Python, Jinja2

---

## File Structure

### Files to Delete
| Path | Reason |
|------|--------|
| `platform_v2/tools/crm/` | Replaced by kbs_crm |
| `platform_v2/tools/invoicing/` | Replaced by kbs_invoicing |
| `platform_v2/tools/store_builder/` | Replaced by kbs_store |
| `platform_v2/tools/call_center/` | Replaced by kbs_call_center |
| `platform_v2/tools/content_studio/` | Replaced by kbs_content_studio |
| `platform_v2/templates/tools/crm.html` | If exists outside module |
| `platform_v2/templates/tools/invoicing.html` | If exists outside module |
| `platform_v2/templates/tools/store_builder.html` | If exists outside module |
| `platform_v2/templates/tools/call_center.html` | If exists outside module |
| `platform_v2/templates/tools/content_studio.html` | If exists outside module |

### Files to Modify
| Path | Change |
|------|--------|
| `platform_v2/module_registry.py` | Remove 5 module entries, disable 2 (social_media, google_work_suite), add 6 external standalone entries |
| `platform_v2/rbac.py` | Remove permissions for deleted modules |
| `platform_v2/templates/dashboard_dynamic.html` | Add rendering for external module cards (open in new tab) |
| `platform_v2/dashboard_generator.py` | Support external module type in dashboard data |

### NOT deleting (have external dependencies)
| Module | Depends on it | Action |
|--------|--------------|--------|
| `tools/social_media/` | media_studio imports publishing_service | Set `enabled=False` in registry, keep code |
| `tools/google_work_suite/` | backup_manager, doc, therapy import services | Set `enabled=False` in registry, keep code |
| `tools/website_studio/` | Need to verify no dependencies first | Delete if clean |

---

### Task 1: Delete 5 Clean Modules

**Files:**
- Delete: `platform_v2/tools/crm/` (entire directory)
- Delete: `platform_v2/tools/invoicing/` (entire directory)
- Delete: `platform_v2/tools/store_builder/` (entire directory)
- Delete: `platform_v2/tools/call_center/` (entire directory)
- Delete: `platform_v2/tools/content_studio/` (entire directory)

- [ ] **Step 1: Verify no external dependencies on these 5 modules**

```bash
cd /mnt/archie_brain
grep -r "from tools.crm" platform_v2/ --include="*.py" -l | grep -v "tools/crm/"
grep -r "from tools.invoicing" platform_v2/ --include="*.py" -l | grep -v "tools/invoicing/"
grep -r "from tools.store_builder" platform_v2/ --include="*.py" -l | grep -v "tools/store_builder/"
grep -r "from tools.call_center" platform_v2/ --include="*.py" -l | grep -v "tools/call_center/"
grep -r "from tools.content_studio" platform_v2/ --include="*.py" -l | grep -v "tools/content_studio/"
```

Expected: No results outside the module directories themselves. If any results appear, note the dependency and handle it before deleting.

Also check for `import tools.crm`, `import tools.invoicing`, etc. with the same exclusion pattern.

- [ ] **Step 2: Also check website_studio**

```bash
grep -r "from tools.website_studio" platform_v2/ --include="*.py" -l | grep -v "tools/website_studio/"
grep -r "import tools.website_studio" platform_v2/ --include="*.py" -l | grep -v "tools/website_studio/"
```

If clean, add website_studio to the delete list. If it has dependencies, keep it like social_media.

- [ ] **Step 3: Delete the module directories**

```bash
rm -rf platform_v2/tools/crm/
rm -rf platform_v2/tools/invoicing/
rm -rf platform_v2/tools/store_builder/
rm -rf platform_v2/tools/call_center/
rm -rf platform_v2/tools/content_studio/
# Also delete website_studio if Step 2 was clean:
rm -rf platform_v2/tools/website_studio/
```

- [ ] **Step 4: Delete standalone template files (if they exist outside module dirs)**

```bash
rm -f platform_v2/templates/tools/crm.html
rm -f platform_v2/templates/tools/invoicing.html
rm -f platform_v2/templates/tools/store_builder.html
rm -f platform_v2/templates/tools/call_center.html
rm -f platform_v2/templates/tools/content_studio.html
rm -f platform_v2/templates/tools/website_studio.html
```

Some may not exist (template might be inside the module dir). That's fine — `rm -f` won't error.

- [ ] **Step 5: Commit the deletions**

```bash
git add -A
git commit -m "chore: delete 5-6 monolith modules replaced by Kytran Business Suite

Removed: crm, invoicing, store_builder, call_center, content_studio
(+ website_studio if clean)
These modules are fully replicated in KBS (port 8091)."
```

---

### Task 2: Update Module Registry — Remove Deleted, Disable Dependants

**Files:**
- Modify: `platform_v2/module_registry.py`

- [ ] **Step 1: Read module_registry.py**

Read the full file to find the exact ModuleDefinition entries for all target modules. Note line numbers for each.

- [ ] **Step 2: Remove deleted module entries**

Remove the `ModuleDefinition(...)` entries for: `crm`, `invoicing`, `store_builder`, `call_center`, `content_studio`, and `website_studio` (if deleted in Task 1).

- [ ] **Step 3: Disable modules with dependencies**

For `social_media` and `google_work_suite`, set `enabled=False` in their ModuleDefinition entries. This hides them from the dashboard but keeps the code available for imports.

Find lines like:
```python
ModuleDefinition(
    id="social_media",
    ...
    enabled=True,
```
Change to `enabled=False`.

Same for `google_work_suite`.

- [ ] **Step 4: Add external module type support**

Add a new field to the `ModuleDefinition` dataclass. Find the dataclass definition and add:

```python
@dataclasses.dataclass
class ModuleDefinition:
    ...
    external_url: str = ""  # If set, module opens this URL in new tab instead of internal route
```

- [ ] **Step 5: Add 6 standalone product entries**

Add a new category or use an existing one. Add these entries after the existing module definitions:

```python
# ── Standalone Products (external) ─────────────────────────────────────
ModuleDefinition(
    id="kytran_system_ops",
    name="Kytran System Operations",
    description="Server management + compliance engine",
    icon="server",
    category=ModuleCategory.ADMIN_OPERATIONS,
    route="/external/kso",
    external_url="http://192.168.1.200:8085",
    priority=1,
    tags=["standalone", "product"],
),
ModuleDefinition(
    id="kytran_business_suite",
    name="Kytran Business Suite",
    description="Modular SaaS platform — CRM, invoicing, store, website builder, and more",
    icon="briefcase",
    category=ModuleCategory.SAAS_SERVICES,
    route="/external/kbs",
    external_url="http://192.168.1.200:8091",
    priority=1,
    tags=["standalone", "product"],
),
ModuleDefinition(
    id="kytran_gov_watch",
    name="Kytran Gov Watch",
    description="Government tender monitoring — P.R.O.C.U.R.E. intelligence",
    icon="landmark",
    category=ModuleCategory.APPLICATIONS,
    route="/external/gov",
    external_url="http://192.168.1.200:8102",
    priority=2,
    tags=["standalone", "product"],
),
ModuleDefinition(
    id="kytran_market_watch",
    name="Kytran Market Watch",
    description="Market intelligence + autonomous trading — M.A.R.K.E.T. agent",
    icon="trending-up",
    category=ModuleCategory.APPLICATIONS,
    route="/external/market",
    external_url="http://192.168.1.200:8101",
    priority=2,
    tags=["standalone", "product"],
),
ModuleDefinition(
    id="kytran_news",
    name="Kytran News",
    description="Global intelligence dashboard — 18 layers, real-time feeds",
    icon="newspaper",
    category=ModuleCategory.APPLICATIONS,
    route="/external/news",
    external_url="http://192.168.1.200:8097",
    priority=2,
    tags=["standalone", "product"],
),
ModuleDefinition(
    id="kytran_legal_watch",
    name="Kytran Legal Watch",
    description="Legal intelligence and case monitoring",
    icon="scale",
    category=ModuleCategory.APPLICATIONS,
    route="/external/legal",
    external_url="http://192.168.1.200:8100",
    priority=2,
    tags=["standalone", "product"],
),
```

NOTE: Before adding, verify the actual ports by checking each standalone's docker-compose.yml. The ports above are from memory and may need correction.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/module_registry.py
git commit -m "feat: remove KBS duplicate modules from registry, add standalone product launchers"
```

---

### Task 3: Update RBAC — Remove Dead Permissions

**Files:**
- Modify: `platform_v2/rbac.py`

- [ ] **Step 1: Read rbac.py**

Find the Permission enum entries for deleted modules.

- [ ] **Step 2: Remove permissions for deleted modules**

Remove these Permission enum entries (if they exist):
- `STORE_CREATE = "store:create"`
- `STORE_MANAGE = "store:manage"`
- `TELEPHONY_ACCESS = "telephony:access"`
- `WEBSITE_BUILDER_CREATE = "website_builder:create"`
- `WEBSITE_BUILDER_DEPLOY = "website_builder:deploy"`

Keep `SOCIAL_MEDIA_*` and `GOOGLE_*` permissions (those modules are disabled, not deleted).
Keep `STOCK_BOT_*` permissions (StockBot not deleted yet — Phase 2).

Also check if any role definitions reference these permissions and remove those references.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/rbac.py
git commit -m "chore: remove RBAC permissions for deleted KBS modules"
```

---

### Task 4: Dashboard — Render External Module Cards

**Files:**
- Modify: `platform_v2/dashboard_generator.py`
- Modify: `platform_v2/templates/dashboard_dynamic.html`

- [ ] **Step 1: Read dashboard_generator.py**

Understand `get_user_dashboard_data(user)` and how it builds the category → modules structure. Find where modules are filtered and formatted for the template.

- [ ] **Step 2: Update dashboard_generator.py to pass external_url**

In the function that builds module data for the template, include the `external_url` field in the dict passed to the template. Find where module dicts are built (likely something like):

```python
module_data = {
    "id": module.id,
    "name": module.name,
    ...
}
```

Add:
```python
    "external_url": module.external_url,
```

- [ ] **Step 3: Read dashboard_dynamic.html**

Find the module card rendering loop. Understand the HTML structure of a module card.

- [ ] **Step 4: Update module card rendering for external links**

In the Jinja2 template where module cards are rendered, add a condition for external modules. If `module.external_url` is set, the card should:
- Open the URL in a new tab (`target="_blank"`)
- Show a small "external" badge or icon
- Use a distinct accent color (e.g., gold/amber border)

Find the existing card `<a>` tag (likely something like `<a href="{{ module.route }}"`) and wrap it:

```html
{% if module.external_url %}
<a href="{{ module.external_url }}" target="_blank" rel="noopener"
   class="featured-card external-product"
   data-module-id="{{ module.id }}"
   data-category="{{ module.category }}">
    <div class="external-badge">PRODUCT</div>
{% else %}
<a href="{{ module.route }}"
   class="featured-card"
   data-module-id="{{ module.id }}"
   data-category="{{ module.category }}">
{% endif %}
```

- [ ] **Step 5: Add CSS for external product cards**

Add to the dashboard CSS (either inline in the template or in `static/css/dashboard.css`):

```css
.featured-card.external-product {
    border-color: rgba(251, 191, 36, 0.4);
    position: relative;
}
.featured-card.external-product:hover {
    border-color: rgba(251, 191, 36, 0.8);
    box-shadow: 0 0 20px rgba(251, 191, 36, 0.15);
}
.external-badge {
    position: absolute;
    top: 8px;
    right: 8px;
    background: rgba(251, 191, 36, 0.2);
    color: #fbbf24;
    font-size: 0.6rem;
    font-family: 'Orbitron', monospace;
    padding: 2px 6px;
    border-radius: 3px;
    letter-spacing: 0.05em;
}
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/dashboard_generator.py platform_v2/templates/dashboard_dynamic.html
git commit -m "feat: add standalone product launcher cards to dashboard with gold accent"
```

---

### Task 5: Deploy and Verify

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Check for import errors**

```bash
docker logs --tail 50 archie_platform 2>&1 | grep -iE "error|import|traceback"
```

Expected: No errors related to deleted modules. The dynamic import in app.py should simply skip modules that no longer exist in the registry.

- [ ] **Step 3: Browser test dashboard**

Open `http://192.168.1.200:3000/dashboard` and verify:
- Deleted modules (CRM, Invoicing, Store Builder, etc.) no longer appear
- Disabled modules (Social Media, Google Work Suite) no longer appear
- 6 standalone product cards appear with gold PRODUCT badge
- Clicking a standalone card opens the external URL in a new tab
- All existing internal modules still work

- [ ] **Step 4: Verify no broken routes**

```bash
# Check that deleted module routes return 404 (not 500)
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/crm
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/invoicing
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/store-builder
```

Expected: 302 (redirect to login) or 404, NOT 500.

- [ ] **Step 5: Final commit with any fixes**

```bash
git add -A
git commit -m "chore: Phase 1 complete — monolith cleanup + standalone dashboard launchers"
```
