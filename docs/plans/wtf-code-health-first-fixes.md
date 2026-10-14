# What The Fact: first finding fixes

This batch follows merged routing/status PR #3859. It changes no live data or
configuration and does not execute the manual bias backfill.

## Changes and limits

- Both app factories use a shared session-signing helper. Configured
  `FLASK_SECRET_KEY` remains unchanged and required by default. The existing
  explicit development opt-in generates a random ephemeral key instead of a
  fixed known signing key. Development sessions reset across app creations;
  persistent or multi-worker development must configure a stable secret.
- The manual bias backfill composes its schema with `psycopg2.sql.Identifier`;
  update values remain bound parameters. Connection/cursor cleanup runs on
  errors. Existing batching and v3-row skipping are retained. The old schema
  setting was operator-controlled, so this is defensive hardening, not proof
  of a remotely exploitable injection vulnerability.
- Bare-exception scanning uses parsed Python, ignoring comments/docstrings.
  Real bare handlers remain reported; invalid or dynamically executed source
  retains conservative text fallback. OpenParl's historical `except: pass`
  comment no longer becomes a live finding.
- Add module descriptions to the two app factories. Large-file findings and
  legitimate CLI progress output remain visible; no broad suppression is added.

## Verification

48 isolated tests pass, including real consumer app/nav registration, both
factories' signing initialization, cross-key signature rejection, quoted hostile
schema identifiers, update bindings, cleanup on failure, actual bare handlers,
comment false positives and conservative invalid-source detection. HTTP/database
access is blocked. The full tech SSO test suite could not collect on this host
because `flask_cors` is unavailable; run it in the product's isolated test image
before release. No production dependencies were installed.

F.O.R.G.E. review clarification: the bare-handler detector analyzes source
syntax; it neither executes inspected code nor catches its runtime failures.
Regression tests explicitly show an application exception still propagating
and the full auditor retaining findings when detection returns unknown. Thus
the `None` fallback is necessary to prevent false clean results, not an
application error-suppression mechanism. Real bare handlers remain findings.
The added integration test exposed an escaped-newline edge case in the text
fallback (`\\nexcept:` lacked the regex word boundary); the fallback now retains
that finding too. This broadens only uncertain-source detection.

```bash
WTF_DATABASE_URL=postgresql+psycopg2://invalid@127.0.0.1/isolated_not_a_database \
PYTHONPATH=platform_v2:ai_bridge:what-the-fact \
python3 -m pytest --import-mode=importlib --noconftest \
  -p tests.review_test_bootstrap -p no:cacheprovider -q \
  what-the-fact/tests/test_session_signing_key.py \
  what-the-fact/tests/test_bias_backfill_sql.py \
  what-the-fact/tests/test_nav_shell.py \
  platform_v2/tests/test_bare_except_detection.py \
  platform_v2/tests/test_code_health_direct_calls.py \
  platform_v2/tests/test_code_health_finding_count.py
git diff --check
```

An isolated before/after scan of four temporary source copies shows four targeted
flags before and zero after: two hardcoded development keys, schema interpolation
and a comment-only bare-exception flag. This does not predict a whole-product
total: the 56-count dashboard history can only be updated by a fresh audit using
the deployed scanner and source revision. False-positive removal is not a repair
of an actual production vulnerability.

## Release and rollback

Human merge and a separate operator release are required. Verify both app image
builds include `shared/session_security.py`; deploy/rebuild the affected consumer,
tech and ingest images through their existing release workflow. Verify the
platform's running audit process has imported the new scanner. Preserve configured
production signing keys so existing production sessions stay valid.

Then run a scoped authoritative re-audit, compare finding identities and source
revision, and reconcile the existing proposals without counting archival as a
fix. Do not bulk-reactivate historic proposals. The website's three findings and
its external source ownership remain separate work.

Rollback restores the previous application/scanner images and source revision;
no schema/data rollback or migration is needed. Do not rerun the backfill to test
rollback. The local-dev ephemeral-key behavior is the only intended change to
session behavior; reverting it restores the former fixed development fallback.
