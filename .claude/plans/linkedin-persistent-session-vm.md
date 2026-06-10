# LinkedIn Persistent Trusted-Session VM — implementation spec (#3953 / #3708)

**Status**: spec (owner-gated — needs a VM + a one-time human login). 2026-06-10.
**Why**: LinkedIn posting is blocked by a step-up password wall when mobile-captured
cookies are replayed by a headless DESKTOP browser on a datacenter IP (KB #272122).
The wall is about **device + IP fingerprint trust**, not input method — so a louder
automation (mouse/keyboard GUI agent) hits the SAME wall at 100× the cost/fragility.
The fix is a **persistent, human-trusted browser profile** that stays warm.

## Core idea (the one insight)
Use a VM as the **session-establishment + persistence surface**, NOT as a per-action
mouse-clicker. The human logs in ONCE on a stable device/IP; LinkedIn trusts that
device; the profile (cookies + localStorage + device fingerprint) persists on disk;
all subsequent actions still go through the cheap voyager/Playwright path
(`browser_service` → `archie_browser` skills) pointed at that persistent profile.

- VM = trusted persistent profile  → **YES**
- VM = per-reply GUI clicker        → **NO** (same wall, fragile, expensive)

## Architecture
1. **Small VM / dedicated browser container** with:
   - A **stable, residential-ish egress IP** (NOT a datacenter range LinkedIn flags).
     Options: a residential proxy bound to the profile, or hosting the profile on a
     node whose egress LinkedIn already trusts (e.g. the owner's home LAN via the
     hub, since the owner logs in from there normally).
   - **Playwright `launch_persistent_context(user_data_dir=...)`** — a persistent
     profile dir, NOT ephemeral `storage_state`. This keeps the full device
     fingerprint (not just cookies), which is what survives step-up.
2. **One-time human login** (the owner action this is gated on):
   - Expose the VM's browser over a remote-desktop / noVNC / ttyd-browser surface
     (KSO-assisted capture per #3708), OR run it on a device the owner already uses.
   - Owner logs into LinkedIn once, completes any 2FA/step-up. Profile is now trusted.
3. **`archie_browser` points at the persistent profile** for the relevant agent
   (342 / company / creed accounts → one profile dir each). `browser_session_service`
   shifts from storing `storage_state` blobs to referencing the persistent profile.
4. **Keep-warm**: a low-frequency benign read (e.g. `linkedin_feed` every few hours)
   keeps the session from expiring; never let it go fully cold.

## What this unblocks
- #3948 (posting) — the staged EN/FR launch posts can finally publish.
- #3964 WRITE leg — reply-send to comments.
- #3975 — post_url capture works once posting works (already wired).
- Eliminates the recurring monthly manual cookie-import chore.

## Owner action required (cannot be automated)
- Provide/confirm the VM or trusted device + egress IP.
- Perform the ONE-TIME interactive LinkedIn login (remote desktop / noVNC).
After that, the platform side (persistent-context wiring, keep-warm job) is buildable
and testable.

## Explicitly rejected
- GUI mouse/keyboard agent driving each action — hits the same step-up wall, breaks
  on every LinkedIn A/B layout, vision round-trip per action. Voyager/Playwright API
  stays the action path.
- OAuth — LinkedIn integration is intentionally Playwright/cookie (34 skills),
  DO-NOT-OAuth per KB #272120.

## Refs
KB #272122 (step-up wall), #272120 (DO-NOT-OAuth), #270262 (S.C.O.U.T. bot-bypass
fabric), tasks #3953 / #3708 / #3948 / #3964 / #3975.
