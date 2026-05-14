# DHQ Contractors + Fleet Content Swap — Implementation Plan (PR 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the PROVIDER BUDGETS section from the Fleet tab panel into the Contractors tab panel, where it belongs conceptually alongside the provider definitions.

**Architecture:** Pure HTML cut-and-paste between two `dhq-panel` divs plus one JS line added to `loadContractors()` to trigger budget table population. No routes, no CSS changes, no backend changes required. `loadFleetUsage()` already contains a `if (!tbody) return;` guard so existing Fleet calls silently no-op once the element moves to the Contractors DOM.

**Tech Stack:** Jinja2 HTML template, vanilla JS. Platform is Flask in Docker at 192.168.1.200:3000. Restart: `docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform`.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `platform_v2/tools/department_hq/templates/department_hq.html` | Modify | Delete PROVIDER BUDGETS from Fleet panel; paste into Contractors panel |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Modify | Add `loadFleetUsage()` call inside `loadContractors()` so budget table populates |

**Key line references (verified from source on branch feat/dispatch-history):**
- Fleet panel `id="panel-fleet"` starts at ~line 381
- PROVIDER BUDGETS block in Fleet: lines 443–449 (7 lines)
- Contractors panel: `id="panel-contractors"` starts at line 459
- Last content div in Contractors: `id="contractorDefinitionsContent"` at line 468
- `loadContractors()` in JS: starts at line 3838, `renderContractors()` call closes at line 3854

---

## Task 1: Delete PROVIDER BUDGETS Block from Fleet Panel

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html:443-449`

- [ ] **Step 1: Read lines 440–452 to confirm content**

Read lines 440–452 and confirm that lines 443–449 contain the `<!-- Budget Table -->` comment followed by the `fleetBudgetSection` div, and that line 450 is the closing `</div>` of the Fleet inner content area (do NOT delete line 450).

- [ ] **Step 2: Delete lines 443–449**

Remove these 7 lines:
```html
      <!-- Budget Table -->
      <div class="dhq-dispatch-section" style="display:none;" id="fleetBudgetSection">
        <div class="dhq-section-title">PROVIDER BUDGETS</div>
        <table style="width:100%;font-size:0.75rem;border-collapse:collapse;">
          <tbody id="fleetBudgetTableBody"></tbody>
        </table>
      </div>
```

After deletion, line 450 (`          </div>`) must remain — it closes the Fleet inner padding div.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "refactor(dhq-fleet): remove PROVIDER BUDGETS section from Fleet panel"
```

---

## Task 2: Insert PROVIDER BUDGETS Block into Contractors Panel

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

- [ ] **Step 1: Find the Contractors panel insertion point**

After Task 1's 7-line deletion, find `id="contractorDefinitionsContent"` in the file. Read 5 lines around it to confirm:
```html
      <div id="contractorProvidersContent"></div>
      <div id="contractorDefinitionsContent"></div>
          </div>    ← do NOT touch — this closes the inner padding div
```

- [ ] **Step 2: Insert PROVIDER BUDGETS block after contractorDefinitionsContent**

After the line containing `<div id="contractorDefinitionsContent"></div>`, insert (note: `style="display:none;"` removed — should always be visible here):

```html
      <!-- Budget Table -->
      <div class="dhq-dispatch-section" id="fleetBudgetSection">
        <div class="dhq-section-title">PROVIDER BUDGETS</div>
        <table style="width:100%;font-size:0.75rem;border-collapse:collapse;">
          <tbody id="fleetBudgetTableBody"></tbody>
        </table>
      </div>
```

- [ ] **Step 3: Verify insertion**

Read 10 lines around the insertion point. Confirm:
1. `contractorDefinitionsContent` div comes immediately before the new block
2. No `style="display:none;"` on the new block
3. The closing `</div>` of the inner padding div follows immediately after

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "refactor(dhq-contractors): add PROVIDER BUDGETS section to Contractors panel"
```

---

## Task 3: Wire Budget Table Population into loadContractors()

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js:3854`

- [ ] **Step 1: Read loadContractors() (lines 3838–3860)**

Confirm this structure at lines 3854-3855:
```javascript
        renderContractors(data.providers || [], routingMode, {
            creed_total_24h: data.creed_total_24h || 0,
            creed_blocked_24h: data.creed_blocked_24h || 0
        });       ← line 3854
    } catch (e) { ← line 3855
```

- [ ] **Step 2: Insert loadFleetUsage() call after line 3854**

After the closing `});` of `renderContractors()` and before `} catch (e) {`, add:

```javascript
        loadFleetUsage();
```

Result:
```javascript
        renderContractors(data.providers || [], routingMode, {
            creed_total_24h: data.creed_total_24h || 0,
            creed_blocked_24h: data.creed_blocked_24h || 0
        });
        loadFleetUsage();
    } catch (e) {
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(dhq-contractors): call loadFleetUsage() from loadContractors to populate budget table"
```

---

## Task 4: Deploy, Verify, and Open PR

- [ ] **Step 1: Restart**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 5
```

- [ ] **Step 2: Verify Fleet tab has no PROVIDER BUDGETS section**

Navigate to `http://192.168.1.200:3000/tools/department-hq?tab=fleet`. Confirm no "PROVIDER BUDGETS" heading appears.

- [ ] **Step 3: Verify Contractors tab shows PROVIDER BUDGETS**

Navigate to `?tab=contractors`. Confirm:
1. "PROVIDER BUDGETS" section heading is visible
2. The budget table is populated (providers appear with spend/budget columns)
3. No JS console errors

- [ ] **Step 4: Verify no JS errors from Fleet calls**

Switch back to Fleet tab. Open browser console. Confirm no errors related to `fleetBudgetTableBody` — the `if (!tbody) return;` guard means Fleet calls now silently no-op.

- [ ] **Step 5: Push and create PR**

```bash
git push origin feat/dispatch-history
gh pr create \
  --title "feat(dhq): move PROVIDER BUDGETS from Fleet to Contractors tab (PR 3/5)" \
  --body "$(cat <<'EOF'
## Summary
Moves the PROVIDER BUDGETS section from panel-fleet to panel-contractors, where it belongs conceptually. Contractors = Tier 3 cloud AI services (HuggingFace, Cloudflare, etc.) with budget management — Provider Budgets shows spend against that budget.

## Changes
- Deleted PROVIDER BUDGETS block from Fleet panel (lines 443-449)
- Added PROVIDER BUDGETS block to Contractors panel (after contractorDefinitionsContent)
- Added `loadFleetUsage()` call inside `loadContractors()` so budget table populates on Contractors tab load
- `style="display:none;"` removed — section always visible in Contractors context

## Behaviour
- Fleet tab: no PROVIDER BUDGETS section
- Contractors tab: PROVIDER BUDGETS visible and populated
- Existing Fleet `loadFleetUsage()` calls no-op silently via existing `if (!tbody) return;` guard

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Merge via /merge-pr**

Use `/merge-pr <PR_NUMBER>` — never `gh pr merge` directly.
