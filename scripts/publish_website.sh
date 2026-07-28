#!/usr/bin/env bash
# publish_website.sh — one-command portrait-to-live pipeline
#
# Regenerates web-sized JPEG thumbnails from the current platform portraits,
# syncs the archie_brain website source to /mnt/standalone/websites/ (where
# the deploy-website skill reads from), and prepares a deploy zip at
# /tmp/kytranempowerment_deploy.zip ready for Hostinger.
#
# After this script runs, ask Claude to deploy (MCP hosting_deployStaticWebsite)
# or invoke the /deploy-website skill directly. Both read the prepared zip.
#
# Usage:
#   ./scripts/publish_website.sh            # regen + sync + zip
#   ./scripts/publish_website.sh --no-thumb # skip thumb regen (just sync+zip)
#   ./scripts/publish_website.sh --dry-run  # show what would happen
#
# Exit codes:
#   0  all steps succeeded, zip ready for deploy
#   1  config / path error
#   2  thumbnail generation failed
#   3  rsync failed
#   4  zip creation failed

set -euo pipefail

# ───── config ────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_SITE="$REPO_ROOT/website/kytranempowerment.com"
DST_SITE="/mnt/standalone/websites/kytranempowerment.com"
DEPLOY_ZIP="/tmp/kytranempowerment_deploy.zip"
THUMB_SCRIPT="$REPO_ROOT/scripts/generate_portrait_thumbnails.py"

# ───── flags ─────────────────────────────────────────────────────────────
DO_THUMBS=1
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --no-thumb|--no-thumbs) DO_THUMBS=0 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "unknown flag: $arg" >&2
      exit 1
      ;;
  esac
done

say() { printf "\033[1;36m[publish]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[publish]\033[0m %s\n" "$*" >&2; }
die() { printf "\033[1;31m[publish]\033[0m %s\n" "$*" >&2; exit "${2:-1}"; }

# ───── sanity ────────────────────────────────────────────────────────────
[ -d "$SRC_SITE" ] || die "source site not found: $SRC_SITE" 1
[ -d "$DST_SITE" ] || die "standalone dest not found: $DST_SITE (create it or fix path)" 1

if [ "$DRY_RUN" = "1" ]; then
  say "DRY RUN — no changes will be made"
fi

# ───── 1. regenerate thumbnails ──────────────────────────────────────────
if [ "$DO_THUMBS" = "1" ]; then
  say "regenerating portrait thumbnails"
  if [ ! -f "$THUMB_SCRIPT" ]; then
    warn "thumbnail script not found, skipping: $THUMB_SCRIPT"
  elif [ "$DRY_RUN" = "1" ]; then
    say "  would run: python3 $THUMB_SCRIPT"
  else
    python3 "$THUMB_SCRIPT" || die "thumbnail generation failed" 2
  fi
else
  say "skipping thumbnail regen (--no-thumb)"
fi

# ───── 1b. sweep thumbs staged by approve_canonical ────────────────────
# The Flask container mounts the website dir read-only, so
# portrait_service._sync_website_thumb writes under
# platform_v2/static/media/thumbs/ when called from inside the container.
# Mirror those into the website repo here so they ship on the next deploy.
STAGING_DIR="$REPO_ROOT/platform_v2/static/media/thumbs"
DST_PORTRAIT_DIR="$SRC_SITE/assets/portraits"
if [ -d "$STAGING_DIR" ] && [ -n "$(ls -A "$STAGING_DIR" 2>/dev/null)" ]; then
  staged_count=$(find "$STAGING_DIR" -maxdepth 1 -name '*.jpg' | wc -l)
  say "sweeping $staged_count staged thumb(s) from $STAGING_DIR → $DST_PORTRAIT_DIR"
  if [ "$DRY_RUN" = "1" ]; then
    find "$STAGING_DIR" -maxdepth 1 -name '*.jpg' -print | head -5
    say "  would cp -u $STAGING_DIR/*.jpg $DST_PORTRAIT_DIR/"
  else
    mkdir -p "$DST_PORTRAIT_DIR"
    # -u only copies if source is newer; -p preserves mtimes so the next
    # generate_portrait_thumbnails run doesn't rewrite them.
    cp -up "$STAGING_DIR"/*.jpg "$DST_PORTRAIT_DIR"/
  fi
fi

# ───── 2. rsync archie_brain → standalone (skipped if symlinked) ────────
# If $DST_SITE resolves to the same canonical path as $SRC_SITE (because
# /mnt/standalone/websites/<domain> is now a symlink to the archie_brain
# source — done 2026-04-20, task #7), rsync would be a self-copy. Detect
# and skip.
SRC_REAL="$(readlink -f "$SRC_SITE")"
DST_REAL="$(readlink -f "$DST_SITE")"
if [ "$SRC_REAL" = "$DST_REAL" ]; then
  say "standalone is symlinked to the source — skipping rsync (same canonical path: $SRC_REAL)"
else
  say "syncing website source → standalone"
  if [ "$DRY_RUN" = "1" ]; then
    rsync -avn --delete "$SRC_SITE/" "$DST_SITE/" | tail -15
  else
    rsync -a --delete "$SRC_SITE/" "$DST_SITE/" || die "rsync failed" 3
  fi
fi

# ───── 3. create deploy zip ─────────────────────────────────────────────
say "creating deploy zip"
if [ "$DRY_RUN" = "1" ]; then
  say "  would create: $DEPLOY_ZIP"
else
  rm -f "$DEPLOY_ZIP"
  (
    cd "$DST_SITE"
    # assets/portraits/*.png are the SDXL ORIGINALS. The site serves the JPEG
    # thumbs generated from them; measured 2026-07-28, the whole site references
    # exactly three .png files and none of them live in portraits/. Shipping the
    # originals put ~97 MB of never-requested bytes (77% of a 126 MB payload)
    # into a full-site upload that REPLACES public_html on every deploy. They are
    # already gitignored for the same reason.
    zip -rq "$DEPLOY_ZIP" . \
      -x ".git/*" ".github/*" \
      -x "assets/portraits/*.png" \
      -x "CONTRIBUTING.md" "SECURITY.md" "CODE_OF_CONDUCT.md" \
      -x "CHANGELOG.md" "LICENSE" "README.md" ".gitignore"
  ) || die "zip creation failed" 4

  zip_size=$(du -h "$DEPLOY_ZIP" | cut -f1)
  zip_files=$(unzip -Z1 "$DEPLOY_ZIP" 2>/dev/null | wc -l)
  say "zip ready: $DEPLOY_ZIP ($zip_size, $zip_files files)"
  # Guard the one thing a full-site replace can silently destroy: an empty or
  # index-less archive would wipe public_html and serve nothing.
  unzip -Z1 "$DEPLOY_ZIP" 2>/dev/null | grep -qx "index.html" \
    || die "refusing: $DEPLOY_ZIP has no index.html at its root — a full-site replace would blank the site" 4
fi

# ───── 4. instructions ──────────────────────────────────────────────────
cat <<'DONE'

────────────────────────────────────────────────────────────
  Next step: deploy the zip to Hostinger
────────────────────────────────────────────────────────────

  Option A — ask Claude:  "deploy the website"
  Option B — /deploy-website skill (picks up /tmp/kytranempowerment_deploy.zip)
  Option C — manual:      gh api ... (Hostinger API token in platform_v2/.env)

  Verify after deploy:
    curl -sI https://kytranempowerment.com/ | head -1
    curl -s https://kytranempowerment.com/assets/portraits/archie.jpg | wc -c

────────────────────────────────────────────────────────────
DONE
