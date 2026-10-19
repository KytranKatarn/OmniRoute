# Starbase SSH Origin Confirmation

**Verified:** 2026-10-16 (UTC)

**Purpose:** Preserve the evidence used to classify repeated Citadel SSH logins from Starbase.

## Verified facts

- Starbase's mesh address is `100.64.0.4`; Citadel is `100.64.0.10`.
- On 2026-10-16, Citadel logged repeated successful public-key SSH sessions for `root` from `209.107.108.214`. The reviewed log window contained 1,164 accepted-key events, all with the same key fingerprint, and no failed SSH authentications.
- A read-only outbound-IP check run from Starbase at the time of review returned `209.107.108.214`. Citadel's SSH logs also showed the same key fingerprint for sessions originating from Starbase's mesh address. This makes the external-source sessions consistent with Starbase's outbound NAT path.
- `209.107.108.214` is an observed **egress** address. Do not replace or conflate it with a node's ingress/public DNS address. Starbase's egress may change.
- The Citadel host journal independently recorded a hypervisor-initiated shutdown and orderly reboot. The WTF outage followed because PostgreSQL's configured secret-file mount was missing; this is separate from the SSH-origin finding.

## Safe handling for future reviews

Treat a matching IP as a useful correlation, not as identity by itself. Before classifying a future login as expected:

1. Compare the event's UTC timestamp, account, source IP, and SSH key fingerprint.
2. Verify Starbase's current egress from the Starbase host and compare it with the observed source. Do not rely on this dated address as a permanent allowlist.
3. Where possible, correlate the key fingerprint with a known Starbase-to-Citadel mesh login (`100.64.0.4` → `100.64.0.10`).
4. Keep alerts for unknown fingerprints, unexpected accounts, failed authentication bursts, or sessions that do not correlate with an authorized Starbase operation. Do not suppress alerts solely because the source IP matches.

This note records an observed origin; it does not authorize new SSH access, change firewall policy, or make root SSH logins safe by default.
