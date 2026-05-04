#!/bin/bash
# Install A.R.C.H.I.E. git hooks
# Run this script to set up PR workflow protection

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

echo "Installing A.R.C.H.I.E. git hooks..."

# Create pre-push hook
cat > "$HOOKS_DIR/pre-push" << 'EOF'
#!/bin/bash
# Pre-push hook to warn before pushing directly to protected branches
# Part of A.R.C.H.I.E. PR Workflow

PROTECTED_BRANCHES="main develop"
CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null)

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Check if pushing to a protected branch
for branch in $PROTECTED_BRANCHES; do
    if [ "$CURRENT_BRANCH" = "$branch" ]; then
        echo ""
        echo -e "${YELLOW}╔════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${YELLOW}║  ⚠️  WARNING: Pushing directly to '$branch' branch${NC}"
        echo -e "${YELLOW}╚════════════════════════════════════════════════════════════╝${NC}"
        echo ""
        echo -e "${RED}This bypasses CodeRabbit code review!${NC}"
        echo ""
        echo "Recommended workflow:"
        echo -e "  1. ${GREEN}git checkout -b feature/your-feature${NC}"
        echo -e "  2. ${GREEN}git push -u origin feature/your-feature${NC}"
        echo "  3. Create PR on GitHub → CodeRabbit reviews"
        echo ""

        # Ask for confirmation
        read -p "Are you sure you want to push directly to '$branch'? (y/N): " -n 1 -r
        echo ""

        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${GREEN}Push cancelled. Use the PR workflow instead.${NC}"
            exit 1
        fi

        echo -e "${YELLOW}Proceeding with direct push (not recommended)...${NC}"
        echo ""
    fi
done

exit 0
EOF

chmod +x "$HOOKS_DIR/pre-push"

echo "✓ pre-push hook installed"

# ── Translation scan trigger (post-commit + post-merge) ──────────────────
# Carry-over from project #290 task #2365. Fires translation_coverage_scan
# when website/i18n files change in git. Trigger logic lives in the
# version-controlled translation_scan_trigger.sh — hooks just invoke it.

TRIGGER="$SCRIPT_DIR/translation_scan_trigger.sh"
SENTINEL_START="# >>> ARCHIE translation_scan_trigger BEGIN >>>"
SENTINEL_END="# <<< ARCHIE translation_scan_trigger END <<<"

# Idempotently inject the sentinel-marked block into a hook file. Preserves
# any existing hook content (e.g., the dev-hq audit-log post-commit hook).
inject_block() {
    local hook_path="$1"
    local prev_arg="$2"  # passed to trigger script ($1 in hook context)

    # Initialise hook if it doesn't exist yet.
    if [ ! -f "$hook_path" ]; then
        printf '#!/usr/bin/env bash\nexit 0\n' > "$hook_path"
        chmod +x "$hook_path"
    fi

    # Strip any prior sentinel block — supports re-runs after upgrades.
    if grep -q "$SENTINEL_START" "$hook_path"; then
        sed -i "/$SENTINEL_START/,/$SENTINEL_END/d" "$hook_path"
        # Trim trailing blank lines left behind.
        sed -i -e :a -e '/^$/{$d;N;ba' -e '}' "$hook_path"
    fi

    # Append the fresh block before any final `exit 0`.
    if grep -qE '^exit 0[[:space:]]*$' "$hook_path"; then
        # Insert before the last `exit 0`.
        awk -v s="$SENTINEL_START" -v e="$SENTINEL_END" \
            -v t="$TRIGGER" -v p="$prev_arg" '
            BEGIN { inserted = 0 }
            /^exit 0[[:space:]]*$/ && !inserted {
                print ""
                print s
                print "if [ -x \"" t "\" ]; then"
                print "    \"" t "\" " p " || true"
                print "fi"
                print e
                inserted = 1
            }
            { print }
        ' "$hook_path" > "$hook_path.tmp" && mv "$hook_path.tmp" "$hook_path"
    else
        # No `exit 0` line — just append.
        {
            printf '\n%s\n' "$SENTINEL_START"
            printf 'if [ -x "%s" ]; then\n' "$TRIGGER"
            printf '    "%s" %s || true\n' "$TRIGGER" "$prev_arg"
            printf 'fi\n'
            printf '%s\n' "$SENTINEL_END"
        } >> "$hook_path"
    fi

    chmod +x "$hook_path"
}

inject_block "$HOOKS_DIR/post-commit" ""
echo "✓ post-commit translation-scan trigger installed"

inject_block "$HOOKS_DIR/post-merge" "ORIG_HEAD"
echo "✓ post-merge translation-scan trigger installed"

echo ""
echo "Git hooks installed successfully!"
echo "Protected branches: main, develop"
echo "Translation scan trigger: post-commit + post-merge → translation_scan_trigger.sh"
echo ""
echo "To bypass push warning (not recommended):"
echo "  git push --no-verify"
