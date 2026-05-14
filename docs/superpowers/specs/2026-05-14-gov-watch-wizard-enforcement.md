# Gov Watch Supplier Profile Wizard Enforcement

**Date:** 2026-05-14
**Task:** T17 — May 2026 Revenue Sprint
**Scope:** Hard-redirect new Gov Watch users to the profile wizard on first login, block dismiss until all 6 steps are complete, add "None apply" escape hatches for steps 3–5, and LCARS-polish the wizard UI.

---

## Context

The wizard exists (`/wizard`, `procure/wizard.py`) with 6-step completion tracking. The gaps:
1. `_check_wizard_needed()` only sets `session["show_wizard"]` — no hard redirect
2. `wizard_dismiss` route sets `session["wizard_dismissed"] = True` with no completion check — bypasses gate
3. Steps 3 (certifications), 4 (diversity), 5 (insurance/clearances) use `any([...])` — suppliers with none are permanently blocked
4. `wizard.html` lacks LCARS styling

Source: `/mnt/standalone/kytran-gov-watch/` (VPS deployment — deploy via `scp` + `docker compose up -d --build`)

---

## Changes

### 1. Hard redirect `before_request` hook — `app.py`

Add after the existing `_select_oauth_client` hook (line 55):

```python
@app.before_request
def _enforce_wizard_completion():
    """Hard-redirect authenticated users with incomplete profile to the wizard."""
    # Skip non-page requests and wizard/auth/static routes
    exempt_prefixes = ("/wizard", "/auth", "/static", "/api/", "/login", "/logout")
    if any(request.path.startswith(p) for p in exempt_prefixes):
        return

    user = getattr(g, "user", None) or session.get("user")
    if not user:
        return

    email = user.get("email", "")
    if not email:
        return

    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT p.*, pe.* FROM user_profiles p "
            "LEFT JOIN profile_ext pe ON pe.user_email = p.email "
            "WHERE p.email = %s",
            (email,),
        )
        row = cur.fetchone() or {}
        cur.close()
        conn.close()
    except Exception:
        return

    from procure.wizard import _compute_completion

    comp = _compute_completion(row, row)
    if comp["first_incomplete"] < 7:
        return redirect(url_for("wizard_bp.wizard_page"))
```

**Note:** Also remove the now-redundant `session["show_wizard"]` soft-banner check from `app.py` line ~1433 and the `_check_wizard_needed()` call — the `before_request` hook replaces it.

### 2. Block `wizard_dismiss` unless profile complete — `procure/wizard.py`

Replace the current `wizard_dismiss` handler (line 136):

```python
@wizard_bp.route("/wizard/api/dismiss", methods=["POST"])
def wizard_dismiss():
    """Only allow dismiss when all 6 steps are complete."""
    user = getattr(g, "user", None) or session.get("user")
    email = (user or {}).get("email", "")
    if not email:
        return jsonify({"error": "not authenticated"}), 401

    try:
        conn = get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM user_profiles WHERE email = %s", (email,))
        profile = cur.fetchone() or {}
        cur.execute("SELECT * FROM profile_ext WHERE user_email = %s", (email,))
        ext = cur.fetchone() or {}
        cur.close()
        conn.close()
    except Exception as exc:
        log.error("wizard_dismiss: %s", exc)
        return jsonify({"error": "db error"}), 500

    comp = _compute_completion(profile, ext)
    if comp["first_incomplete"] < 7:
        return jsonify({
            "error": "incomplete",
            "message": "Complete all 6 steps before accessing tenders.",
            "first_incomplete": comp["first_incomplete"],
        }), 403

    session.pop("show_wizard", None)
    return jsonify({"ok": True})
```

### 3. "None apply" escape hatches for steps 3–5

**DB migration** — add three boolean columns to `user_profiles` (or to `profile_ext` — whichever table the wizard writes to):

```sql
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS none_apply_certifications BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS none_apply_diversity       BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS none_apply_insurance       BOOLEAN DEFAULT FALSE;
```

Run via:
```bash
docker exec kytran_gov_watch_db psql -U govwatch -d govwatch -c "ALTER TABLE user_profiles ..."
```
(Check `cfg.dsn` in app for actual DB container name and credentials.)

**Update `_compute_completion` in `procure/wizard.py`:**

Replace lines 53–67 with:

```python
    steps = [
        bool(profile.get("company_name")),
        bool(profile.get("naics_codes")),
        bool(profile.get("certifications")) or bool(profile.get("none_apply_certifications")),
        any([
            profile.get("indigenous_owned"), profile.get("women_owned"),
            profile.get("minority_owned"),   profile.get("veteran_owned"),
            profile.get("black_owned"),      profile.get("disability_owned"),
            profile.get("lgbtq_owned"),      profile.get("francophone_owned"),
            profile.get("rural_remote"),     profile.get("social_enterprise"),
            ext.get("ibd_listed"),           ext.get("ccab_certified"),
            ext.get("wbe_canada_certified"), ext.get("black_entrepreneur_registry"),
        ]) or bool(profile.get("none_apply_diversity")),
        any([
            ext.get("general_liability_cad"), ext.get("bonding_capacity_cad"),
            ext.get("reliability_cleared_count"), ext.get("federal_awards_count"),
        ]) or bool(profile.get("none_apply_insurance")),
        bool((profile.get("profile_summary") or "").strip()),
    ]
```

**Add API endpoints** to set/unset the none_apply flags (PUT to existing `/procure/api/profile`):

The existing profile PUT endpoint already accepts arbitrary fields — just send `{"none_apply_certifications": true}` and it writes to the DB. No new endpoint needed, only the DB columns.

**Update wizard.html** — add a "None apply to my business" toggle button at the bottom of step 3, 4, and 5 panels that POSTs the none_apply flag via the existing profile API.

### 4. LCARS polish — `templates/wizard.html`

Apply Gov Watch dark theme (navy `#0a0f1e`, teal `#00d4ff` accent, `IBM Plex Mono` font):
- Replace any plain Bootstrap/default styling with Gov Watch CSS variables
- Add a horizontal step progress bar at top (6 segments, teal fill for completed steps)
- Step cards: dark surface `#12192e`, teal left border for active step
- Navigation: "Back" + "Save & Continue" buttons matching Gov Watch button style
- Remove "Skip for now" / dismiss links from the wizard UI (enforced by backend anyway)

---

## Files Changed

| File | Location | Action |
|------|----------|--------|
| `app.py` | `/mnt/standalone/kytran-gov-watch/app.py` | Add `_enforce_wizard_completion` before_request; remove soft-banner code |
| `procure/wizard.py` | `/mnt/standalone/kytran-gov-watch/procure/wizard.py` | Update `_compute_completion` + `wizard_dismiss` |
| `templates/wizard.html` | `/mnt/standalone/kytran-gov-watch/templates/wizard.html` | LCARS polish + none_apply toggles |
| DB migration SQL | One-time via docker exec | Add 3 columns to `user_profiles` |

---

## Deployment

Gov Watch is VPS-deployed (no git on VPS). After local edits:
```bash
# Copy changed files to VPS
scp app.py procure/wizard.py templates/wizard.html root@76.13.107.109:/opt/archie-products/kytran-gov-watch/

# Rebuild + restart on VPS
ssh root@76.13.107.109 "cd /opt/archie-products/kytran-gov-watch && docker compose up -d --build kytran_gov_watch"
```

Or hot-patch for template-only changes:
```bash
docker cp templates/wizard.html kytran_gov_watch:/app/templates/ && docker compose restart kytran_gov_watch
```

---

## Out of Scope

- NAICS tree picker redesign (works fine)
- P.R.O.C.U.R.E. matching changes (unchanged)
- Email notifications on profile completion

---

## Testing

1. Log in as a new supplier via Kytran SSO → should be hard-redirected to `/wizard` instead of dashboard
2. Try navigating to `/dashboard` directly while incomplete → should redirect back to `/wizard`
3. On step 3, click "None apply to my business" → step 3 marks green, can proceed
4. Complete all 6 steps → "Enter Gov Watch" button becomes active
5. Click "Enter Dashboard" after completing → no longer redirected, lands on dashboard
6. Reload while logged in with complete profile → no redirect (stays on whatever page)
