# Lane prep for deploy_static (kytranempowerment.com)

**Reference for `deploy-website`.** Split out so the skill file itself fits a review pass window. The SKILL.md carries the decision rules; this carries the detail.

---

## 2. Lane prep for deploy_static (kytranempowerment.com)

1. **Confirm the work is merged into main** (`git -C /mnt/archie_brain log
   --oneline -1`, tracked site files clean). Deploying ships the TREE; unmerged
   or dirty site work does not go.
2. **Thumbnails:** skip unless `assets/portraits/*.png` changed since the last
   push. Lane cannot regen (no PIL; `archie_platform` HAS PIL but mounts the
   website dir read-only). Portrait changes ⇒ ask Claude/owner to run
   `scripts/publish_website.sh` host-side first. HTML/CSS/JS-only deploys (the
   common case) skip this entirely.
3. **Build the zip** — lane lacks `zip`, so use python stdlib. Canonical
   exclusions (same as `publish_website.sh` — do NOT add exclusions ad-hoc;
   `ds-bundle/` and `qa-screenshots/` ship by parity):
   ```bash
   TS=$(date +%Y%m%d_%H%M%S)
   python3 - "$TS" <<'PY'
   import sys, zipfile, pathlib
   ts = sys.argv[1]
   SRC = pathlib.Path("/mnt/archie_brain/website/kytranempowerment.com")
   OUT = pathlib.Path(f"/mnt/archie_brain/platform_v2/_lane_ship/kytranempowerment.com_{ts}.zip")
   ROOT_DOCS = {"CONTRIBUTING.md","SECURITY.md","CODE_OF_CONDUCT.md",
                "CHANGELOG.md","LICENSE","README.md",".gitignore"}
   skip_dirs = {".git", ".github"}
   names = []
   with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
       for p in sorted(SRC.rglob("*")):
           if not p.is_file(): continue
           rel = p.relative_to(SRC)
           if any(part in skip_dirs for part in rel.parts): continue
           if len(rel.parts) == 1 and rel.name in ROOT_DOCS: continue
           if rel.parts[:2] == ("assets","portraits") and rel.suffix == ".png": continue  # SDXL originals ~97MB
           z.write(p, rel.as_posix()); names.append(rel.as_posix())
   assert "index.html" in names, "refusing: no root index.html — a full-site replace would blank the site"
   print(OUT, f"{OUT.stat().st_size/1e6:.1f} MB", len(names), "files")
   PY
   ```
   Guards (mirroring the script): refuse if no root `index.html`; print size +
   file count. Output lives in `platform_v2/_lane_ship/` — gitignored in both
   trees, readable by host + Claude.
   If the host already ran `publish_website.sh` (zip at host
   `/tmp/kytranempowerment_deploy.zip`), prefer that — Claude's MCP reads it as-is.
4. **Push — lane-native (works once opencode restarts and loads the config):**
   - **Preflight (read-only, proves token + account):** MCP tool
     `hosting_listWebsitesV1` (no args) → expect the account's site list
     containing `kytranempowerment.com`. (Already verified 2026-09-23.)
   - **Push:** `hosting_deployStaticWebsite(domain="kytranempowerment.com",
     archivePath="<path printed by §2.3>", removeArchive=true)` — the MCP
     server runs IN this lane, validates the zip on the lane filesystem,
     uploads it, then triggers deploy. Expect
     `{"upload":{"status":"success"},"deploy":{"status":"success","data":{"message":"Request accepted"}}}`.
     The account username auto-resolves from the domain — never pass or guess it.
   - **Only on the user's explicit "deploy/publish" instruction** — it replaces
     `public_html` entirely; a wrong zip wipes the site (run the §2.3 guards).
   - **Fallback (config not loaded yet, or MCP down):** hand off exactly as
     before — *"Zip ready: `<path>` — ask Claude: deploy kytranempowerment.com
     from archivePath `<path>`."* Claude runs the same tool from his side and
     records with `mark_deploy_pushed`.
   Never delegate `deploy_static` through the fleet — a delegate only marks
   `deploy_pending` and the live site never changes (task #3577).
5. **deploy_vps domains** (if the user asks): delegate one domain at a time
   (single SSH) via `delegate_task_to_fleet(capability="deploy_vps", reason=…)`
   with args `{domain, source_path, changed_files, verify_url, container_name}`;
   B.A.S.E. (agent 139) snapshots → rsyncs → `docker compose up -d --build` →
   verifies → retries once → rolls back on double failure.
