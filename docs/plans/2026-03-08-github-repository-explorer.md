# GitHub Repository Explorer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Full split-pane repository file browser in Consciousness GitHub tab — tree on left, file viewer with syntax highlighting on right, README landing page per repo.

**Architecture:** Backend serves file tree and content from local clones at `/mnt/archie_brain/repos/`. Frontend uses lazy-loaded directory tree, highlight.js for syntax, marked.js for markdown. Explorer overlays existing GitHub tab content (ops terminal, intake, stats remain accessible).

**Tech Stack:** Flask API, os/pathlib for filesystem, highlight.js CDN, marked.js CDN, LCARS CSS

**Dev HQ:** Project #118, Tasks #794-#801

---

### Task 1: Backend API Endpoints

**Files:**
- Modify: `platform_v2/tools/consciousness/github_routes.py`

**Step 1: Add file tree endpoint**

Add `GET /consciousness/github/repo/<int:repo_id>/tree?path=` endpoint:
- Query `github_repositories` for `local_path` and `repo_name`
- If `local_path` is None or doesn't exist, return 404
- Use `os.listdir()` + `os.path.isdir()` to build entries list
- Return `{ repo_name, path, entries: [{ name, type: "dir"|"file", size }] }`
- Sort: directories first, then files, alphabetical within each group
- Security: validate path doesn't escape repo root (no `..`)

**Step 2: Add file content endpoint**

Add `GET /consciousness/github/repo/<int:repo_id>/file?path=` endpoint:
- Same repo lookup and path security validation
- Read file content with `open(full_path, 'r', errors='replace')`
- Detect language from extension for syntax highlighting hint
- Return `{ repo_name, path, filename, content, language, size }`
- Cap file size at 1MB, return truncation notice if exceeded

**Step 3: Add README endpoint**

Add `GET /consciousness/github/repo/<int:repo_id>/readme` endpoint:
- Look for README.md, README, readme.md in repo root
- Return `{ repo_name, content, filename }` or 404 if none found
- Also return basic repo stats: file count, directory count, total size

**Step 4: Test endpoints**

```bash
docker compose restart archie_platform
# Test tree
curl http://192.168.1.200:3000/consciousness/github/repo/1/tree
# Test nested path
curl "http://192.168.1.200:3000/consciousness/github/repo/1/tree?path=src"
# Test file
curl "http://192.168.1.200:3000/consciousness/github/repo/1/file?path=README.md"
# Test readme
curl http://192.168.1.200:3000/consciousness/github/repo/1/readme
```

**Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/github_routes.py
git commit -m "feat(consciousness): add GitHub repo file tree and content API endpoints"
```

---

### Task 2: HTML Structure

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness.html`

**Step 1: Add explorer container to GitHub tab**

After the existing GitHub tab content (stats, ops terminal, intake), add the repo explorer container:
- `#ghRepoExplorer` — hidden by default, shown when a repo card is clicked
- Back button to return to repo list view
- Breadcrumb bar showing current path
- Split pane: `#ghTreePane` (left, 280px) and `#ghViewerPane` (right, flex)
- Landing page container for README display
- File viewer container for syntax-highlighted content
- Include highlight.js and marked.js CDN scripts

**Step 2: Verify template renders**

```bash
docker compose restart archie_platform
# Visit http://192.168.1.200:3000/consciousness and check GitHub tab loads
```

**Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness.html
git commit -m "feat(consciousness): add repo explorer HTML structure to GitHub tab"
```

---

### Task 3: CSS Styling

**Files:**
- Modify: `platform_v2/static/css/consciousness.css` (or inline in template)

**Step 1: Add explorer layout styles**

- `.gh-explorer` — full-width container, hidden by default
- `.gh-explorer-header` — breadcrumbs bar with LCARS purple accent
- `.gh-explorer-split` — flexbox split pane
- `.gh-tree-pane` — 280px fixed width, scrollable, dark background
- `.gh-viewer-pane` — flex-grow, scrollable
- `.gh-tree-item` — hover states, directory vs file icons (CSS unicode)
- `.gh-tree-item.dir::before` content "▸" (collapsed) / "▾" (expanded)
- `.gh-file-viewer` — code block styling matching LCARS theme
- `.gh-landing` — README card with repo stats grid
- `.gh-breadcrumb` — path segments as clickable links

**Step 2: Verify styles**

```bash
docker compose restart archie_platform
# Check explorer container is properly hidden, inspect with devtools
```

**Step 3: Commit**

```bash
git add platform_v2/static/css/consciousness.css
git commit -m "feat(consciousness): add LCARS-styled repo explorer CSS"
```

---

### Task 4: Directory Tree Component (JS)

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1: Add tree loading function**

`loadRepoTree(repoId, path, parentEl)`:
- Fetch `/consciousness/github/repo/{repoId}/tree?path={path}`
- Create DOM elements for each entry using `document.createElement`
- Directories: clickable, lazy-load children on first click (toggle expand/collapse)
- Files: clickable, trigger `loadRepoFile(repoId, fullPath)`
- Show loading spinner during fetch
- Sort: dirs first, then files

**Step 2: Add tree expand/collapse**

- Track expanded state on DOM elements via data attributes
- Click expanded dir: collapse (hide children)
- Click collapsed dir: expand (show children or fetch if not loaded)
- Visual indicators: ▸ collapsed, ▾ expanded

**Step 3: Test tree navigation**

```bash
docker compose restart archie_platform
# Open a repo, verify tree loads, click directories to expand
```

**Step 4: Commit**

```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): add lazy-loaded directory tree component"
```

---

### Task 5: File Viewer Component (JS)

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1: Add file loading function**

`loadRepoFile(repoId, path)`:
- Fetch `/consciousness/github/repo/{repoId}/file?path={path}`
- Update breadcrumbs to show current path
- For code files: create `<pre><code>` element, set textContent (safe), apply highlight.js
- For markdown (.md): render with marked.js into viewer pane using safe rendering
- For images: show `<img>` tag
- For binary/large: show "Binary file" or "File too large" message
- Highlight current file in tree

**Step 2: Add breadcrumb navigation**

`updateBreadcrumbs(repoId, repoName, path)`:
- Split path into segments
- Each segment is clickable — navigates tree to that directory
- Repo name is first breadcrumb (clicks go to landing page)

**Step 3: Test file viewing**

```bash
docker compose restart archie_platform
# Open repo, click files, verify syntax highlighting works
# Test .md, .py, .js, .json files
```

**Step 4: Commit**

```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): add syntax-highlighted file viewer"
```

---

### Task 6: Repo Landing Page (JS)

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1: Add landing page function**

`loadRepoLanding(repoId)`:
- Fetch `/consciousness/github/repo/{repoId}/readme`
- Show repo name, description, stats (files, dirs, size)
- Render README.md content with marked.js (sanitized)
- Show "No README found" if 404
- Display as the default view when opening a repo

**Step 2: Test landing page**

```bash
docker compose restart archie_platform
# Open repo, verify README renders, stats display
```

**Step 3: Commit**

```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): add repo landing page with README"
```

---

### Task 7: Wire Up Repo Cards

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1: Add click handlers to repo cards**

`openRepoExplorer(repoId, repoName)`:
- Hide repo list section, show explorer container
- Load tree for root path
- Load landing page (README + stats)
- Add back button handler to close explorer, show repo list

**Step 2: Add "Explore" button to repo cards**

- In the existing repo card rendering, add an "Explore" button (only if repo has `local_path`)
- Button calls `openRepoExplorer(repoId, repoName)`
- Repos without local clones show "Not cloned" instead

**Step 3: Test full flow**

```bash
docker compose restart archie_platform
# Click repo card -> explorer opens -> browse tree -> view files -> click back
```

**Step 4: Commit**

```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): wire repo cards to explorer with back navigation"
```

---

### Task 8: Deploy and Final Test

**Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

**Step 2: Full integration test**

- Open Consciousness > GitHub tab
- Verify stats, ops terminal, intake still visible
- Click "Explore" on a repo card
- Verify tree loads, README landing page shows
- Navigate directories in tree
- View Python, JS, JSON, MD files
- Use breadcrumbs to navigate back
- Click back button to return to repo list
- Test on repo with no README
- Test on repo with deeply nested directories

**Step 3: Final commit if needed**

```bash
git add -A
git commit -m "feat(consciousness): complete GitHub repository explorer"
```

**Step 4: Update Dev HQ**

- Complete tasks #794-#801 via MCP
- Update project #118 status
- Log architectural decisions
