# Website Designer Module

**Last Updated:** 2026-01-21
**Status:** Phase 2 Complete (Polish & Enhanced UI)
**Route:** `/tools/website-studio`
**Version:** 5.33.0

---

## Overview

The Website Designer is a chat-based website editing tool that allows users to modify websites through natural language conversations with A.R.C.H.I.E.

### Primary Use Cases

1. **Admin Website Management**
   - Edit www.kytranempowerment.com via chat
   - Deploy changes to GitHub Pages
   - Manage site files through Git integration

2. **Client Website Mockups** (Planned)
   - Create demo websites for potential clients
   - Show website design examples
   - Export or deploy client previews

---

## Current Features (Phase 1)

### Chat Designer Tab

The main interface with a 3-column grid layout:

| Panel | Purpose | Width |
|-------|---------|-------|
| **Chat** (Left) | Talk to A.R.C.H.I.E. to describe changes | 300px |
| **File Tree** (Center-Left) | Hierarchical folder/file navigation | 200px |
| **Main Area** (Right) | Preview + Code tabs with Monaco Editor | Flexible |

#### Chat Capabilities
- Natural language website editing requests
- AI generates code changes with diff preview
- Apply or cancel changes with one click
- Auto-commit on apply (configurable)

#### File Tree Panel (NEW in v5.33.0)
- Hierarchical folder structure with expand/collapse
- File type icons (HTML, CSS, JS, images, etc.)
- Modified status indicators (orange dot) from git status
- Click-to-open files in Monaco editor
- Auto-refresh after save, apply, or commit
- Lucide icons for visual clarity

#### Preview Features
- Live iframe preview of current file
- Viewport toggles: Mobile (375px) | Tablet (768px) | Desktop (100%)
- Auto-refresh after applying changes
- Base href injection for relative paths

#### Code Panel
- **Monaco Editor** with full syntax highlighting
- File tabs for quick switching
- Save and Revert buttons
- Language detection based on file extension

### Projects Tab

Manage multiple website projects:

| Feature | Description |
|---------|-------------|
| Create Project | Name, description, template selection |
| Project Cards | Shows page count, status, last updated |
| Edit Project | Opens project editor (future) |
| Deploy Project | Deploy to GitHub Pages |

**Templates Available:**
- Blank
- Business
- Portfolio
- Landing Page

### Client Mockup Templates (NEW v5.33.0 - WD-5)

11 production-ready templates across 3 categories:

| Category | Templates | Description |
|----------|-----------|-------------|
| **Business** | Modern Landing, Creative Portfolio, Bold Agency | Professional business sites |
| **E-commerce** | Storefront, Product Listing, Product Detail, Cart, Checkout, Subscription | Full e-commerce flow |
| **Application** | SaaS Landing, Admin Dashboard | App interfaces |

**Template Features:**
- Complete HTML + CSS files
- Variable substitution (`{{company_name}}`, `{{tagline}}`, etc.)
- Responsive design
- Modern styling with CSS custom properties

**API Endpoints:**
```
GET  /api/templates                          - List all templates by category
GET  /api/templates/<category>/<template_id> - Get specific template with content
POST /api/projects/<id>/apply-template       - Apply template to project
```

### Git Tab

Full Git integration for version control:

| Feature | Description |
|---------|-------------|
| Repository Info | Shows repo name, branch, last sync |
| Commit Templates | Dropdown with feat/fix/style/content/docs/refactor prefixes (NEW) |
| Commit Form | Create commits with custom messages |
| Changed Files | Lists modified/added/deleted files with checkboxes |
| Commit History | Recent commits with SHA and metadata |
| Pull/Push | Sync with remote repository |
| Deploy | One-click deploy to GitHub Pages |

#### Git Tab Improvements (v5.33.0)
- **Commit Message Templates**: Dropdown with standard prefixes (feat:, fix:, style:, content:, docs:, refactor:)
- **Auto-apply Template**: Selecting a template prepends it to the commit message
- **Template Reset**: Dropdown resets after successful commit
- **File Tree Refresh**: File tree refreshes after commit to clear modified indicators

---

## Technical Architecture

### Backend Files

| File | Purpose | Lines |
|------|---------|-------|
| `tools/website_studio/routes.py` | Flask routes and API endpoints | ~1,500 |
| `tools/website_studio/chat_handler.py` | Chat-to-code pipeline | ~400 |
| `tools/website_studio/ai_assistant.py` | AI design suggestions | ~200 |
| `templates/tools/website_studio.html` | Frontend UI | ~1,480 |

### API Endpoints

#### Chat-Based Editing
```
POST /api/chat           - Send message to A.R.C.H.I.E.
POST /api/apply-changes  - Apply AI-generated changes
GET  /api/preview        - Get file content for preview
GET  /api/site-context   - Get site structure
GET  /api/chat/history   - Get chat history
POST /api/chat/history   - Save chat message
```

#### Git Operations
```
GET  /api/git/status     - Get changed files
GET  /api/git/files      - List repository files
GET  /api/git/tree       - Get hierarchical file tree (NEW v5.33.0)
GET  /api/git/file       - Read file content
PUT  /api/git/file       - Write file content
POST /api/git/commit     - Create commit
POST /api/git/pull       - Pull from remote
POST /api/git/push       - Push to remote
GET  /api/git/commits    - Get commit history
```

#### Projects
```
GET    /api/projects              - List projects
POST   /api/projects              - Create project
GET    /api/projects/<id>         - Get project details
PUT    /api/projects/<id>         - Update project
DELETE /api/projects/<id>         - Delete project
POST   /api/projects/<id>/deploy  - Deploy project
```

#### Deployment
```
POST /api/deploy-to-github-pages  - One-click deploy to GitHub Pages
```

### AI Integration

Uses **Ollama deepseek-coder-v2:16b** (local, free) for code generation.

The chat handler builds context by:
1. Getting file tree of repository
2. Reading contents of web files (HTML, CSS, JS)
3. Formatting system prompt with site context
4. Parsing AI response for `<file_changes>` XML blocks

---

## Repository Configuration

| Setting | Value |
|---------|-------|
| Admin Repo | `KytranKatarn/kytranempowerment-site` |
| Clone Path | `/tmp/website-repo` |
| Target Site | www.kytranempowerment.com |
| Hosting | GitHub Pages |
| DNS | Hostinger |

---

## Known Issues / TODO

### Fixed in v5.33.0
1. ~~**File Browser** - Doesn't show folder structure clearly~~ - Now has hierarchical tree
2. ~~**Monaco Editor** - Basic textarea~~ - Monaco Editor integrated with syntax highlighting
3. ~~**Git Tab** - Basic commit form~~ - Added commit templates and auto-refresh

### Current Issues
1. **Preview Panel** - May not display correctly if repo not cloned
2. **SSE Streaming** - Chat responses are still request-response (not streaming)

### Planned Improvements
1. ~~Better file tree with folder hierarchy~~ **DONE**
2. ~~Monaco Editor integration for syntax highlighting~~ **DONE**
3. Split view for diff comparison
4. ~~Template gallery for client mockups~~ **DONE** (WD-5)
5. Export to ZIP for client delivery
6. Custom domain configuration per project
7. Real-time SSE streaming for chat responses (WD-3)

---

## How It Works

### Chat-to-Code Flow

```
1. User: "Make the header blue"
           ↓
2. A.R.C.H.I.E. receives message + site context
           ↓
3. AI generates response with <file_changes> XML
           ↓
4. System parses changes, shows diff preview
           ↓
5. User clicks [Apply] or [Cancel]
           ↓
6. Changes applied to files, auto-committed
           ↓
7. Preview refreshes, git status updates
           ↓
8. User can [Deploy] when ready
```

### File Change Format

The AI returns changes in this XML format:

```xml
<file_changes>
<file path="index.html">
<change type="replace">
<old_content>
<!-- exact content to replace -->
</old_content>
<new_content>
<!-- new content -->
</new_content>
</change>
</file>
</file_changes>
```

Supported change types:
- `replace` - Find and replace content
- `insert` - Insert after/before target
- `create` - Create new file

---

## Usage Examples

### Example 1: Style Change
```
User: "Make the navigation bar sticky at the top"

A.R.C.H.I.E.: I'll add sticky positioning to your navigation.
Here's the change to styles.css:

[Diff Preview]
- nav { padding: 20px; }
+ nav { padding: 20px; position: sticky; top: 0; z-index: 100; }

[Apply] [Cancel]
```

### Example 2: Content Update
```
User: "Update the About page to mention our new AI services"

A.R.C.H.I.E.: I'll update the About page content.

[Diff Preview showing the change]

[Apply] [Cancel]
```

### Example 3: Add New Section
```
User: "Add a testimonials section to the home page"

A.R.C.H.I.E.: I'll create a testimonials section for you.

[Diff Preview showing new HTML]

[Apply] [Cancel]
```

---

## Configuration

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `GITHUB_TOKEN` | Token for GitHub API access |
| `HOSTINGER_API_KEY` | Hostinger DNS management |

### User Settings

Settings stored in `website_builder_projects` table:
- `chat_history` - JSON array of chat messages
- `settings` - Project-specific configuration

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `website_builder_projects` | Project metadata |
| `website_builder_pages` | Page content per project |
| `website_deployments` | Deployment history |
| `user_integrations` | GitHub/Vercel/Netlify credentials |

---

## Related Documentation

- `/docs/UI_STYLE_GUIDE.md` - Platform styling guide
- `/docs/MODULE_REGISTRY_STATUS.md` - Module status overview
- `/mnt/archie_brain/ai_bridge/` - AI Bridge documentation

---

*This module is actively being developed. Features may change.*
