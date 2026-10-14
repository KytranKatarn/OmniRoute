# What The Fact Code Health routing

The authoritative October 12–14 audits retained 56 product findings and three
website findings, with no verified fixes. Product metrics (783 files/131,561
non-empty lines) and website metrics (11 files/1,668 non-empty lines) measure
size, not repair outcomes. IN REPAIR counts active proposals, not deployed fixes.

## Changes

- Map `standalone_what_the_fact/` to tracked `what-the-fact/` source. Preserve
  proposal fingerprint paths; resolve only the repair source/diff destination.
- Resolve registered external `.com` website source as `external_owner`, not
  missing. Stop before inference/diff generation and preserve the finding for
  owner routing. The website tree at `/mnt/standalone/websites/what-the-fact.com`
  is separate from this repository; inventing a repository patch destination
  would be unsafe. This PR does not implement external-repository shipping.
- Reject traversal and symlink escapes during source resolution.
- Show FINDINGS OPEN for fresh yellow findings, STALE only when the API reports
  `stale=true`, and ATTENTION when details are unknown. Apply the same rule to
  platform, standalone and website tables. No findings are hidden or subtracted.

## Validation

Run isolated Python tests with the opt-in network/DB-blocking plugin:

```bash
PYTHONPATH=platform_v2:ai_bridge python3 -m pytest --noconftest \
  -p tests.review_test_bootstrap -p no:cacheprovider -q \
  platform_v2/tests/test_wtf_code_health_routing.py \
  platform_v2/tests/test_resolve_proposal_source.py \
  platform_v2/tests/test_code_health_finding_count.py \
  platform_v2/tests/test_code_health_duplicate_repairs.py
node platform_v2/tests/js/test_code_health_status_labels.cjs
node --check platform_v2/static/js/consciousness.js
git diff --check
```

The component preview uses actual table renderers with fixture data and blocks
network requests. It is not an authenticated production browser check.

## Follow-up and rollout

No production scans, inference, proposal updates, unarchives or deployment are
part of this PR. Historical archived proposals remain historical; do not count
them as fixes. After human merge, the deployment owner must load the changed
services and browser asset using normal provenance checks, then verify product
source resolution through the running repair worker before approving targeted
repair generation. Review the three critical product flags for false positives
before repairing them; one historical SQL interpolation finding was already
classified as operator-controlled rather than an injection defect.

The website owner must route its three findings to the correct source repository
and release workflow. Only fixes that are merged, deployed and reproduced absent
in a subsequent authoritative audit should lower the verified backlog. Do not
bulk-reactivate hundreds of historical archived proposals; first reconcile the
current findings and deduplicate against the seven active product proposals.

Rollback is a normal code/asset revert and reload, with no schema/data rollback.
Keep external website proposals preserved if reverting would otherwise archive
them again; stop that drain until source ownership is resolved. No model,
dispatcher, infrastructure or Repair Bay admission configuration is changed.
