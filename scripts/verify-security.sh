#!/bin/bash

# ============================================================================
# SECURITY VERIFICATION SCRIPT
# Checks that no secrets are exposed before committing to Git
# Location: /mnt/archie_brain/scripts/verify-security.sh
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

echo "🔐 A.R.C.H.I.E. Security Verification"
echo "======================================"
echo ""

cd /mnt/archie_brain

# Check 1: .gitignore exists
echo -n "1. Checking .gitignore exists... "
if [ -f .gitignore ]; then
    echo -e "${GREEN}✅${NC}"
else
    echo -e "${RED}❌ Missing!${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check 2: .env is in .gitignore
echo -n "2. Checking .env is ignored... "
if git check-ignore .env >/dev/null 2>&1 || grep -q "^\.env$" .gitignore; then
    echo -e "${GREEN}✅${NC}"
else
    echo -e "${RED}❌ NOT IGNORED!${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check 3: secrets/ is in .gitignore
echo -n "3. Checking secrets/ is ignored... "
if git check-ignore secrets/ >/dev/null 2>&1 || grep -q "^secrets/" .gitignore; then
    echo -e "${GREEN}✅${NC}"
else
    echo -e "${RED}❌ NOT IGNORED!${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Check 4: .env is not tracked by git
echo -n "4. Checking .env not tracked... "
if git ls-files .env 2>/dev/null | grep -q .env; then
    echo -e "${RED}❌ .env IS TRACKED!${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✅${NC}"
fi

# Check 5: secrets/ not tracked by git
echo -n "5. Checking secrets/ not tracked... "
if git ls-files secrets/ 2>/dev/null | grep -q secrets; then
    echo -e "${RED}❌ secrets/ IS TRACKED!${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✅${NC}"
fi

# Check 6: No passwords in staged files
echo -n "6. Checking staged files for passwords... "
if git diff --cached | grep -iE "password.*=.*['\"].*['\"]" > /dev/null; then
    echo -e "${RED}❌ PASSWORDS FOUND IN STAGED FILES!${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✅${NC}"
fi

# Check 7: No API keys in staged files
echo -n "7. Checking staged files for API keys... "
if git diff --cached | grep -iE "(api.key|token).*=.*['\"].*['\"]" > /dev/null; then
    echo -e "${RED}❌ API KEYS FOUND IN STAGED FILES!${NC}"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}✅${NC}"
fi

# Check 8: .env.example has no real secrets
echo -n "8. Checking .env.example is safe... "
if [ -f .env.example ]; then
    if grep -iE "password.*=.*(change-this|your-|example|dummy)" .env.example > /dev/null; then
        echo -e "${GREEN}✅${NC}"
    else
        echo -e "${YELLOW}⚠️  May contain real secrets${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}⚠️  .env.example not found${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# Check 9: secrets directory has correct permissions
echo -n "9. Checking secrets/ permissions... "
if [ -d secrets ]; then
    PERMS=$(stat -c %a secrets 2>/dev/null || stat -f %Lp secrets 2>/dev/null)
    if [ "$PERMS" = "700" ]; then
        echo -e "${GREEN}✅${NC}"
    else
        echo -e "${YELLOW}⚠️  Should be 700, is $PERMS${NC}"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}⚠️  secrets/ not found${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

# Check 10: .env exists
echo -n "10. Checking .env exists... "
if [ -f .env ]; then
    echo -e "${GREEN}✅${NC}"
else
    echo -e "${YELLOW}⚠️  .env not found (copy from .env.example)${NC}"
    WARNINGS=$((WARNINGS + 1))
fi

echo ""
echo "======================================"

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}❌ SECURITY CHECK FAILED: $ERRORS errors${NC}"
    echo ""
    echo "⚠️  DO NOT COMMIT until errors are fixed!"
    echo ""
    echo "Common fixes:"
    echo "  - Add .env to .gitignore"
    echo "  - Add secrets/ to .gitignore"
    echo "  - Remove tracked .env: git rm --cached .env"
    echo "  - Remove passwords from code"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}⚠️  WARNINGS: $WARNINGS warnings${NC}"
    echo ""
    echo "Review warnings above. Safe to commit but check:"
    echo "  - .env.example has no real secrets"
    echo "  - secrets/ has correct permissions (700)"
    exit 0
else
    echo -e "${GREEN}✅ ALL SECURITY CHECKS PASSED!${NC}"
    echo ""
    echo "Safe to commit to Git! 🎉"
    exit 0
fi
