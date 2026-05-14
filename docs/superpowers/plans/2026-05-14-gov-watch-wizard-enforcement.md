# Gov Watch Supplier Profile Wizard Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force new Gov Watch suppliers through a complete 6-step profile wizard before accessing tender browsing, with bypass-proof enforcement and "None apply" escape hatches for optional steps.

**Architecture:** Four coordinated changes to `procure/wizard.py` and `app.py` (running on VPS at `/mnt/standalone/kytran-gov-watch/`): (1) `_compute_completion` gains `none_apply_*` support via `profile_extended` JSONB; (2) `wizard_dismiss` blocks unless all 6 steps are done; (3) a new `before_request` hook hard-redirects incomplete profiles to `/wizard`; (4) `wizard.html` adds "None apply" toggles and LCARS polish.

**Tech Stack:** Flask, psycopg2, Jinja2, vanilla JS. VPS-deployed: `scp` changed files → `docker compose up -d --build` on outpost-us (76.13.107.109).

---

## File Map

| File | Location | Action |
|------|----------|--------|
| `procure/wizard.py` | `/mnt/standalone/kytran-gov-watch/` | Update `_compute_completion` + `wizard_dismiss` |
| `app.py` | `/mnt/standalone/kytran-gov-watch/` | Add `_enforce_wizard_completion` before_request; remove soft-banner call |
| `templates/wizard.html` | `/mnt/standalone/kytran-gov-watch/` | Add none_apply toggles + LCARS polish |

No DB migration needed — `none_apply_*` flags stored in existing `profile_extended` JSONB column.

---

### Task 1: Update `_compute_completion` — add none_apply support

**Files:**
- Modify: `/mnt/standalone/kytran-gov-watch/procure/wizard.py` lines 51–69

**Context:**
- `profile` = full DB row dict; `ext` = `profile.get("profile_extended") or {}`
- `none_apply_certifications`, `none_apply_diversity`, `none_apply_insurance` will be stored in `profile_extended` JSONB
- Existing API already accepts `{"extended": {...}}` and writes to `profile_extended` — no new endpoint needed

- [ ] **Step 1: Read lines 49–77 of wizard.py to confirm current state**

```bash
sed -n '49,77p' /mnt/standalone/kytran-gov-watch/procure/wizard.py
```

- [ ] **Step 2: Replace the `steps` list in `_compute_completion`**

The current steps list (lines 51–69) becomes:

```python
    steps = [
        bool(profile.get("company_name")),
        bool(profile.get("naics_codes")),
        bool(profile.get("certifications")) or bool(ext.get("none_apply_certifications")),
        any([
            profile.get("indigenous_owned"), profile.get("women_owned"),
            profile.get("minority_owned"),   profile.get("veteran_owned"),
            profile.get("black_owned"),      profile.get("disability_owned"),
            profile.get("lgbtq_owned"),      profile.get("francophone_owned"),
            profile.get("rural_remote"),     profile.get("social_enterprise"),
            ext.get("ibd_listed"),           ext.get("ccab_certified"),
            ext.get("wbe_canada_certified"), ext.get("black_entrepreneur_registry"),
        ]) or bool(ext.get("none_apply_diversity")),
        any([
            ext.get("general_liability_cad"), ext.get("bonding_capacity_cad"),
            ext.get("reliability_cleared_count"), ext.get("federal_awards_count"),
        ]) or bool(ext.get("none_apply_insurance")),
        bool((profile.get("profile_summary") or "").strip()),
    ]
```

- [ ] **Step 3: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('/mnt/standalone/kytran-gov-watch/procure/wizard.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 4: Verify none_apply logic**

```bash
cd /mnt/standalone/kytran-gov-watch && python3 -c "
from procure.wizard import _compute_completion

# No certs but none_apply set → step 3 passes
p = {'company_name': 'Acme', 'naics_codes': ['123'], 'certifications': [], 'profile_summary': 'test'}
e = {'none_apply_certifications': True, 'none_apply_diversity': True, 'none_apply_insurance': True}
c = _compute_completion(p, e)
print('steps:', c['steps'])
print('pct:', c['pct'])
assert c['steps'][2] == True, 'Step 3 should pass with none_apply_certifications'
assert c['steps'][3] == True, 'Step 4 should pass with none_apply_diversity'
assert c['steps'][4] == True, 'Step 5 should pass with none_apply_insurance'
print('All assertions passed')
"
```

Expected: All assertions passed, steps 2/3/4 True.

- [ ] **Step 5: Commit**

```bash
cd /mnt/standalone/kytran-gov-watch
git add procure/wizard.py
git commit -m "feat(wizard): none_apply support for steps 3/4/5 — certifications/diversity/insurance"
```

---

### Task 2: Block `wizard_dismiss` unless complete

**Files:**
- Modify: `/mnt/standalone/kytran-gov-watch/procure/wizard.py` lines 136–141

- [ ] **Step 1: Read current wizard_dismiss function**

```bash
sed -n '134,145p' /mnt/standalone/kytran-gov-watch/procure/wizard.py
```

- [ ] **Step 2: Replace wizard_dismiss body**

Replace the entire `wizard_dismiss` route with:

```python
@wizard_bp.route("/wizard/api/dismiss", methods=["POST"])
def wizard_dismiss():
    """Only allow dismiss when all 6 steps are complete."""
    email = (session.get("kytran_user") or {}).get("email")
    if not email:
        return jsonify({"error": "not authenticated"}), 401

    conn = None
    try:
        conn = psycopg2.connect(_Config().dsn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT company_name, naics_codes, certifications,
                      indigenous_owned, women_owned, minority_owned, veteran_owned,
                      black_owned, disability_owned, lgbtq_owned,
                      francophone_owned, rural_remote, social_enterprise,
                      profile_summary, profile_extended
               FROM user_profiles WHERE LOWER(email) = LOWER(%s)""",
            (email,),
        )
        row = dict(cur.fetchone() or {})
        cur.close()
    except Exception as exc:
        log.error("wizard_dismiss: %s", exc)
        return jsonify({"error": "db error"}), 500
    finally:
        if conn:
            conn.close()

    ext = row.get("profile_extended") or {}
    comp = _compute_completion(row, ext)
    if comp["first_incomplete"] < 7:
        return jsonify({
            "error": "incomplete",
            "message": "Complete all 6 steps before accessing tenders.",
            "first_incomplete": comp["first_incomplete"],
        }), 403

    session.pop("show_wizard", None)
    return jsonify({"ok": True})
```

- [ ] **Step 3: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('/mnt/standalone/kytran-gov-watch/procure/wizard.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 4: Commit**

```bash
cd /mnt/standalone/kytran-gov-watch
git add procure/wizard.py
git commit -m "feat(wizard): block wizard_dismiss until all 6 steps complete"
```

---

### Task 3: Add hard-redirect before_request in app.py

**Files:**
- Modify: `/mnt/standalone/kytran-gov-watch/app.py`

**Context:**
- Existing `@app.before_request` hook `_select_oauth_client` is at line 47 — add new hook AFTER it (line ~56)
- `session.get("kytran_user")` holds the logged-in user dict with `email` key
- `_check_wizard_needed(email)` is called at line ~1435 — find and remove that call (and the function itself if no other callers)
- `url_for("wizard_bp.wizard_page")` is the target redirect

- [ ] **Step 1: Find exact insertion point and soft-banner lines**

```bash
grep -n "_check_wizard_needed\|show_wizard\|wizard_needed\|_select_oauth_client" /mnt/standalone/kytran-gov-watch/app.py | head -20
```

Note the line numbers for:
- End of `_select_oauth_client` function
- `_check_wizard_needed` call
- `_check_wizard_needed` function definition

- [ ] **Step 2: Add `_enforce_wizard_completion` after line 55 (end of `_select_oauth_client`)**

```python
@app.before_request
def _enforce_wizard_completion():
    """Hard-redirect authenticated suppliers with incomplete profile to the wizard."""
    exempt_prefixes = ("/wizard", "/auth", "/login", "/logout", "/static", "/api/")
    if any(request.path.startswith(p) for p in exempt_prefixes):
        return

    email = (session.get("kytran_user") or {}).get("email")
    if not email:
        return

    conn = None
    try:
        conn = psycopg2.connect(cfg.dsn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT company_name, naics_codes, certifications,
                      indigenous_owned, women_owned, minority_owned, veteran_owned,
                      black_owned, disability_owned, lgbtq_owned,
                      francophone_owned, rural_remote, social_enterprise,
                      profile_summary, profile_extended
               FROM user_profiles WHERE LOWER(email) = LOWER(%s)""",
            (email,),
        )
        row = dict(cur.fetchone() or {})
        cur.close()
    except Exception:
        return  # Fail open — don't block on DB error
    finally:
        if conn:
            conn.close()

    from procure.wizard import _compute_completion  # noqa: PLC0415

    ext = row.get("profile_extended") or {}
    comp = _compute_completion(row, ext)
    if comp["first_incomplete"] < 7:
        return redirect(url_for("wizard_bp.wizard_page"))
```

- [ ] **Step 3: Remove the soft-banner `_check_wizard_needed` call and function**

Find and delete:
- The `_check_wizard_needed(email)` call (inside `on_login` callback)
- The `_check_wizard_needed(email: str) -> None:` function definition (and its body)
- Any `session["show_wizard"]` set logic

- [ ] **Step 4: Verify `redirect` and `url_for` are already imported in app.py**

```bash
grep -n "^from flask import\|^import flask" /mnt/standalone/kytran-gov-watch/app.py | head -5
```

If `redirect` and `url_for` are not already imported, add them to the existing Flask import line.

- [ ] **Step 5: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('/mnt/standalone/kytran-gov-watch/app.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 6: Commit**

```bash
cd /mnt/standalone/kytran-gov-watch
git add app.py
git commit -m "feat(wizard): hard-redirect incomplete profiles to /wizard via before_request"
```

---

### Task 4: Add none_apply toggles + LCARS polish to wizard.html

**Files:**
- Modify: `/mnt/standalone/kytran-gov-watch/templates/wizard.html`

**Context:**
- The wizard has 6 steps rendered in panels
- Steps 3 (certifications), 4 (diversity), 5 (insurance) need a "None apply to my business" toggle
- Clicking the toggle sends `PUT /procure/api/profile` with `{"extended": {"none_apply_certifications": true}}` (for step 3), etc.
- The existing profile PUT endpoint already handles `extended` → writes to `profile_extended` JSONB
- LCARS styling: dark bg `#0a0f1e`, teal `#00d4ff`, `IBM Plex Mono` font — check existing wizard.html for current classes and match Gov Watch's design system

- [ ] **Step 1: Read wizard.html structure to find step 3/4/5 panels**

```bash
grep -n "step.*3\|certif\|step.*4\|diversity\|step.*5\|insurance\|none_apply" /mnt/standalone/kytran-gov-watch/templates/wizard.html | head -20
```

- [ ] **Step 2: Add "None apply" toggle to step 3 (certifications)**

Find the bottom of the step 3 certifications panel. Add before its closing `</div>`:

```html
<div class="none-apply-row" style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(0,212,255,0.15);">
  <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:0.82rem;color:#94a3b8;">
    <input type="checkbox" id="none-apply-cert"
           {% if ext.get('none_apply_certifications') %}checked{% endif %}
           onchange="setNoneApply('none_apply_certifications', this.checked)"
           style="accent-color:#00d4ff;width:16px;height:16px;" />
    None of these certifications apply to my business
  </label>
</div>
```

- [ ] **Step 3: Add "None apply" toggle to step 4 (diversity)**

Same pattern at bottom of step 4 panel:

```html
<div class="none-apply-row" style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(0,212,255,0.15);">
  <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:0.82rem;color:#94a3b8;">
    <input type="checkbox" id="none-apply-div"
           {% if ext.get('none_apply_diversity') %}checked{% endif %}
           onchange="setNoneApply('none_apply_diversity', this.checked)"
           style="accent-color:#00d4ff;width:16px;height:16px;" />
    None of these ownership designations apply to my business
  </label>
</div>
```

- [ ] **Step 4: Add "None apply" toggle to step 5 (insurance/clearances)**

Same pattern at bottom of step 5 panel:

```html
<div class="none-apply-row" style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(0,212,255,0.15);">
  <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:0.82rem;color:#94a3b8;">
    <input type="checkbox" id="none-apply-ins"
           {% if ext.get('none_apply_insurance') %}checked{% endif %}
           onchange="setNoneApply('none_apply_insurance', this.checked)"
           style="accent-color:#00d4ff;width:16px;height:16px;" />
    None of these apply to my business (no current insurance, clearances, or federal awards)
  </label>
</div>
```

- [ ] **Step 5: Add `setNoneApply` JS function to wizard.html**

Find the `<script>` block in wizard.html and add:

```javascript
function setNoneApply(flag, value) {
  fetch('/procure/api/profile', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({extended: {[flag]: value}})
  })
  .then(r => r.json())
  .then(() => {
    // Refresh completion state
    fetch('/wizard/api/completion')
      .then(r => r.json())
      .then(data => {
        // Update step indicators if updateCompletion() exists in the page
        if (typeof updateCompletion === 'function') updateCompletion(data);
      });
  });
}
```

- [ ] **Step 6: Remove "Skip for now" / dismiss links from wizard UI**

```bash
grep -n "skip\|dismiss\|Skip\|Dismiss" /mnt/standalone/kytran-gov-watch/templates/wizard.html | head -10
```

Delete or comment out any skip/dismiss button that calls `/wizard/api/dismiss` — the backend now blocks it, but removing the UI button is cleaner UX.

- [ ] **Step 7: Syntax check (Jinja2 template)**

```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/mnt/standalone/kytran-gov-watch/templates'))
env.get_template('wizard.html')
print('Template OK')
"
```

Expected: `Template OK`

- [ ] **Step 8: Commit**

```bash
cd /mnt/standalone/kytran-gov-watch
git add templates/wizard.html
git commit -m "feat(wizard): none_apply toggles for steps 3/4/5 + remove skip/dismiss links"
```

---

### Task 5: Deploy to VPS + verify

**Context:**
- VPS: `76.13.107.109`
- Source dir on VPS: `/opt/archie-products/kytran-gov-watch/`
- Container name: check with `ssh root@76.13.107.109 "docker ps | grep gov"`

- [ ] **Step 1: Copy changed files to VPS**

```bash
scp /mnt/standalone/kytran-gov-watch/procure/wizard.py \
    root@76.13.107.109:/opt/archie-products/kytran-gov-watch/procure/wizard.py

scp /mnt/standalone/kytran-gov-watch/app.py \
    root@76.13.107.109:/opt/archie-products/kytran-gov-watch/app.py

scp /mnt/standalone/kytran-gov-watch/templates/wizard.html \
    root@76.13.107.109:/opt/archie-products/kytran-gov-watch/templates/wizard.html
```

- [ ] **Step 2: Rebuild + restart on VPS**

```bash
ssh root@76.13.107.109 "cd /opt/archie-products/kytran-gov-watch && docker compose up -d --build --no-deps kytran_gov_watch"
```

Wait ~30 seconds for container to come up.

- [ ] **Step 3: Verify container is running**

```bash
ssh root@76.13.107.109 "docker ps | grep gov"
```

Expected: container `kytran_gov_watch` (or similar) in running state.

- [ ] **Step 4: Test wizard redirect**

```bash
# Should return 302 redirect to /wizard for unauthenticated (or 200 for the login page)
curl -sI https://gov.kytranempowerment.com/ | head -5
```

- [ ] **Step 5: Test none_apply via API**

```bash
# If you have a test account, verify the completion API respects none_apply
curl -sX PUT https://gov.kytranempowerment.com/procure/api/profile \
  -H "Content-Type: application/json" \
  -H "Cookie: <session_cookie>" \
  -d '{"extended": {"none_apply_certifications": true}}'
```

Expected: `{"ok": true}` or similar success response.

- [ ] **Step 6: Test dismiss block**

```bash
curl -sX POST https://gov.kytranempowerment.com/wizard/api/dismiss \
  -H "Cookie: <session_cookie_with_incomplete_profile>"
```

Expected: `{"error": "incomplete", "first_incomplete": N}` with HTTP 403.

- [ ] **Step 7: Final commit (scp confirmed + working)**

Since Gov Watch has its own git repo on VPS or local source, commit the local source:

```bash
cd /mnt/standalone/kytran-gov-watch
git add -A
git commit -m "feat(wizard): full enforcement — hard redirect + dismiss gate + none_apply toggles (T17)"
```

---

## Self-Review

**Spec coverage:**
- [x] Hard redirect on first login (Task 3 — `_enforce_wizard_completion` before_request)
- [x] Remove soft-banner `_check_wizard_needed` (Task 3 step 3)
- [x] `wizard_dismiss` blocks unless complete (Task 2)
- [x] `none_apply_certifications` for step 3 (Tasks 1 + 4)
- [x] `none_apply_diversity` for step 4 (Tasks 1 + 4)
- [x] `none_apply_insurance` for step 5 (Tasks 1 + 4)
- [x] No DB migration needed — JSONB `profile_extended` used (spec updated)
- [x] Remove skip/dismiss UI links (Task 4 step 6)
- [x] LCARS polish noted (task 4 — implementer checks existing classes)
- [x] VPS deployment via scp + docker compose up --build (Task 5)

**No placeholders.** The `setNoneApply` JS function is complete. The `_enforce_wizard_completion` Python code is complete. `_compute_completion` update is complete.

**Type consistency:** `_compute_completion(profile, ext)` — `profile` = DB row dict, `ext` = `profile.get("profile_extended") or {}`. This pattern is used consistently across Tasks 1, 2, and 3. `ext.get("none_apply_certifications")` matches what `setNoneApply('none_apply_certifications', value)` writes via the profile PUT endpoint.
