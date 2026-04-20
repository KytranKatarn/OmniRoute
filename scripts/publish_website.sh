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

# ───── 2. rsync archie_brain → standalone ───────────────────────────────
say "syncing website source → standalone"
if [ "$DRY_RUN" = "1" ]; then
  rsync -avn --delete "$SRC_SITE/" "$DST_SITE/" | tail -15
else
  rsync -a --delete "$SRC_SITE/" "$DST_SITE/" || die "rsync failed" 3
fi

# ───── 3. create deploy zip ─────────────────────────────────────────────
say "creating deploy zip"
if [ "$DRY_RUN" = "1" ]; then
  say "  would create: $DEPLOY_ZIP"
else
  rm -f "$DEPLOY_ZIP"
  (
    cd "$DST_SITE"
    zip -rq "$DEPLOY_ZIP" . \
      -x ".git/*" ".github/*" \
      -x "CONTRIBUTING.md" "SECURITY.md" "CODE_OF_CONDUCT.md" \
      -x "CHANGELOG.md" "LICENSE" "README.md" ".gitignore"
  ) || die "zip creation failed" 4

  zip_size=$(du -h "$DEPLOY_ZIP" | cut -f1)
  say "zip ready: $DEPLOY_ZIP ($zip_size)"
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
