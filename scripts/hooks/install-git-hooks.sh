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
echo ""
echo "Git hooks installed successfully!"
echo "Protected branches: main, develop"
echo ""
echo "To bypass the warning (not recommended):"
echo "  git push --no-verify"
