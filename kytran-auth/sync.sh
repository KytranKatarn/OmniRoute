#!/usr/bin/env bash
# Propagate canonical kytran_auth.py to all product deployment directories.
# Run this after updating kytran-auth/kytran_auth.py, then rebuild affected containers.
#
# Usage: cd kytran-auth && ./sync.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANONICAL="$SCRIPT_DIR/kytran_auth.py"
ROOT="$(dirname "$SCRIPT_DIR")"

DESTINATIONS=(
    "$ROOT/archie-comms/kytran_auth.py"
    # Bundled kytran-auth-pkg/ destinations (pip-install from local bundle)
    "/mnt/standalone/kytran-gov-watch/kytran-auth-pkg/kytran_auth.py"
    "/mnt/standalone/kytran-civic-watch/kytran-auth-pkg/kytran_auth.py"
    "/mnt/standalone/kytran-legal-watch/kytran-auth-pkg/kytran_auth.py"
    "/mnt/standalone/kytran-market-watch/kytran-auth-pkg/kytran_auth.py"
    "$ROOT/kytran-business-suite/kytran-auth-pkg/kytran_auth.py"
    "$ROOT/kytran-server-manager/kytran-auth-pkg/kytran_auth.py"
    "$ROOT/standalone/media_hub/kytran-auth-pkg/kytran_auth.py"
    "$ROOT/what-the-fact/kytran-auth-pkg/kytran_auth.py"
    # what-the-fact/shared/kytran_auth.py is now a thin shim — do NOT overwrite it
    # kso: kytran_system_operations/kytran_auth.py is now a thin shim — do NOT overwrite it
)

echo "Syncing canonical kytran_auth.py to product directories..."
for dest in "${DESTINATIONS[@]}"; do
    if [[ -d "$(dirname "$dest")" ]]; then
        cp "$CANONICAL" "$dest"
        echo "  ✓ $(realpath --relative-to="$ROOT" "$dest")"
    else
        echo "  ✗ SKIP (dir missing): $dest"
    fi
done
echo "Done."
