"""Canonical WTF tier vocabulary — SINGLE source of truth (audit 2026-07-14).

The platform pushes canonical tiers (see /api/internal/set-tier: kytran/owner/
admin/pro/agency/team/solo/starter/free). auth.py, billing.py and access.py
each carried a private, DRIFTED copy of the subscribed set that omitted
solo/team/agency — so a paying team/solo/agency subscriber (e.g. the
intelligence bundle) was paywalled after paying. All three now import this set.

Grant-only semantics: adding a name here can only WIDEN access, never narrow
it. Legacy names (professional/vip/business) are kept for pre-canonical stored
rows — do not remove without a data migration.
"""

SUBSCRIBED_TIERS = frozenset(
    {
        # canonical paid tiers (match /api/internal/set-tier + platform billing)
        "starter",
        "solo",
        "team",
        "agency",
        "pro",
        "enterprise",
        # owner / elevated identities
        "kytran",
        "owner",
        "admin",
        # legacy vocabulary kept for old stored rows (grant-only)
        "professional",
        "vip",
        "business",
    }
)
