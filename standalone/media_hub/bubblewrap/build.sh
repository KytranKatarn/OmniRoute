#!/usr/bin/env bash
# ============================================================================
# Media Hub TWA APK build script
# ============================================================================
# One-command build of a signed Fire TV / Android TV APK wrapping the Media
# Hub PWA manifest. Run from your dev machine (NOT the hub) — Bubblewrap
# shells out to the Android SDK + JDK + gradle which we don't install on
# the server.
#
# Prerequisites on your dev machine:
#   * Node.js 18+     (for npx)
#   * OpenJDK 17      (for jarsigner / keystore)
#   * Android Studio OR command-line tools — Bubblewrap will prompt and
#     offer to install the SDK components it needs
#
# On Fire TV / Android TV device (one-time):
#   Settings → My Fire TV → Developer options → ADB debugging ON
#   Settings → My Fire TV → About → (tap 7x) → enables Developer options
#
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MANIFEST_URL="${MANIFEST_URL:-https://media.kytranempowerment.com/static/manifest.json}"
PACKAGE="${PACKAGE:-com.kytranempowerment.mediahub}"
KEYSTORE="${KEYSTORE:-$HERE/android.keystore}"
KEY_ALIAS="${KEY_ALIAS:-android}"

say() { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m==> %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31m==> %s\033[0m\n' "$*" >&2; exit 1; }

# ----------------------------------------------------------------------------
# 1. Keystore — generate once, stored beside this script. Back it up or
#    every device install after a rebuild breaks until they trust the new
#    fingerprint.
# ----------------------------------------------------------------------------
if [[ ! -f "$KEYSTORE" ]]; then
    say "Creating Android keystore at $KEYSTORE"
    say "Pick a strong password — you'll reuse it for every future build."
    keytool -genkey -v \
        -keystore "$KEYSTORE" \
        -alias "$KEY_ALIAS" \
        -keyalg RSA -keysize 2048 -validity 25000
    warn "Back this file up — losing it means every Fire TV needs a reinstall."
fi

# ----------------------------------------------------------------------------
# 2. Init Bubblewrap project — scaffolds an Android Gradle project from the
#    PWA manifest. The overlay step below pins our package id + launcher
#    name + colours so they don't drift on re-init.
# ----------------------------------------------------------------------------
cd "$HERE"
if [[ ! -d twa ]]; then
    say "Bubblewrap init from $MANIFEST_URL"
    mkdir twa && cd twa
    npx --yes @bubblewrap/cli@latest init \
        --manifest="$MANIFEST_URL" \
        --directory="$(pwd)"
    cd "$HERE"
fi

say "Overlaying our twa-manifest.json (package id + theme + launcher name)"
cp "$HERE/twa-manifest.json" "$HERE/twa/twa-manifest.json"

# ----------------------------------------------------------------------------
# 3. Build signed APK.
# ----------------------------------------------------------------------------
cd "$HERE/twa"
say "Bubblewrap build — this invokes Gradle, takes a few minutes"
npx --yes @bubblewrap/cli@latest build \
    --manifest="$HERE/twa/twa-manifest.json" \
    --signingKeyPath="$KEYSTORE" \
    --signingKeyAlias="$KEY_ALIAS"

APK="$(find "$HERE/twa" -maxdepth 2 -name 'app-release-signed.apk' | head -1)"
[[ -f "$APK" ]] || die "Expected app-release-signed.apk not found"

# ----------------------------------------------------------------------------
# 4. Fingerprint — paste into ANDROID_APK_FINGERPRINTS env on the hub so
#    /.well-known/assetlinks.json advertises the new trust binding. Redeploy
#    mediahub_app for the env to take effect.
# ----------------------------------------------------------------------------
say "Fingerprint for /.well-known/assetlinks.json:"
npx --yes @bubblewrap/cli@latest fingerprint \
    --manifest="$HERE/twa/twa-manifest.json" || \
    keytool -list -v -keystore "$KEYSTORE" -alias "$KEY_ALIAS" | grep SHA256

# ----------------------------------------------------------------------------
# 5. Hand off to the user — we don't do ADB from here (keystores + devices
#    live on the human's network edge, not the hub).
# ----------------------------------------------------------------------------
cat <<EOF

============================================================================
APK ready: $APK

Next steps (run from a machine on the same LAN as the Fire TV):

  1. On Fire TV: Settings → About → (tap 7x) → Developer options → ADB on
  2. adb connect <fire-tv-ip>:5555
  3. adb install "$APK"

Then paste the SHA256 fingerprint above into the hub's .env:

  ANDROID_APK_FINGERPRINTS=<hex-with-colons>
  ANDROID_APK_PACKAGE=$PACKAGE

…and \`docker compose up -d --force-recreate mediahub_app\` so the
/.well-known/assetlinks.json route advertises the new APK. With the
binding in place, Fire TV hides the address bar and treats Media Hub
like a native app.
============================================================================
EOF
