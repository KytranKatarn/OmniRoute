# Repair Bay publication gate — host adapter status and provisioning request

2026-10-15, Host OpenCode (opencode lane). Follows
`docs/plans/repair-bay-publication-gate-handoff.md` (Codex, item 2). Execution
and replacement admission remain **OFF**; no pilot is proposed here.

This change completes the **code** half of the host publication gate inside
`platform_v2`. It does **not** provision the isolated supervisor identity, the
systemd unit or the push/PR credentials — those are host steps that require
owner authorization and are listed verbatim below. Until they exist, every gate
entry point fails closed, so nothing activates in production.

## What this change delivers

| Handoff property | Status | Where |
|---|---|---|
| Isolated supervisor identity, private journal/key dir | **Code half** (verification, fail closed) | `tools/host_opencode/publication_gate.py::verify_supervisor_provisioning` |
| Exclusive publishing with durable intent, no bypass | **Implemented** (unwired) | `PublicationGate.publish/stop` over `PublicationFence` |
| Bind registration to verified seal + attempt/generation + host/boot + repo/branch/head | **Implemented** | `PublicationGate.register_from_seal` |
| Independent outcome reconciliation (identity-bound, no dict trust) | **Implemented** (unwired) | `ObservationAuthority` / `FileObservationAuthority` / `PublicationGate.reconcile` |
| Docker start/stop gating | **Implemented** | `DockerStartStopGate` |
| Signed receipt binding + consumer verification | **Binding produced + consumer verifies it** | `PublicationGate.receipt_binding`, `verify_publication_binding`, `services/codex_stop_receipts.py` |

Supporting, additive changes:

* `publication_fence.py` — read-only `snapshot()` (receipt binding + external
  tail/digest comparison), optional `attempt_id`/`generation` registration
  bindings, optional `request_id` on intent. The 5-field context and the
  push/pr_create operation set are unchanged, so existing callers/tests are
  unaffected.
* `services/codex_stop_receipts.py` — accepts an optional `publication_binding`,
  verifies it independently, and **still never authorises recovery**.
* `tests/test_publication_gate.py` (42 tests) and new binding cases in
  `tests/test_codex_broker_consumer.py`. Includes a real forked-process exercise:
  a local controlled endpoint accepts the request, the publishing client is
  killed **before** the response, the endpoint records success afterwards, and
  only independent reading acknowledges it.

## Deliberate non-claims

* A passing test suite is **not** host containment proof, and the injected
  identity/transport in tests is not authority. The isolated supervisor identity
  does not exist yet (the broker still runs as `kytran`, uid 1000), so the real
  host exercise (handoff item 3) has not run.
* `FileObservationAuthority` is the exercise implementation of the authority
  interface. Production needs the supervisor's outbound-operation ledger behind
  the same interface; a GitHub snapshot alone remains insufficient.
* The gate never certifies the trusted-stop contract and never sets a recovery
  flag.

## Broker wiring — deferred by the handoff, not forgotten

The handoff says "wire the trusted adapter to the broker only after exact-head
review and a host exercise." Accordingly this PR does **not** modify
`tools/host_opencode/broker.py`. The intended integration points are:

1. At seal time, call `PublicationGate.register_from_seal(sealed_assignment, ...)`
   with the boot id (`/proc/sys/kernel/random/boot_id`), host id and generation.
2. Add a broker publish path that calls `PublicationGate.publish(...)` as the
   **only** caller of the real push/PR-create transport (no runner fallback).
3. In the completion handler, attach `PublicationGate.receipt_binding()` as
   `publication_binding` in the signed receipt payload (the consumer already
   verifies it).
4. Use `build_publication_observer(gate)` for the completion observer instead of
   the fail-closed stub — read-only; unregistered journals still return `None`.

These are gated on item 3 (the isolated host exercise) and item 5 (explicit owner
approval).

## Host provisioning — EXECUTED 2026-10-15 (owner-authorized)

The owner authorized these host steps explicitly on 2026-10-15. Steps 1–3 ran on
`archie`; step 4 was left unscripted as agreed. Everything is reversible — the
pre-change unit is preserved at
`/etc/systemd/system/host-opencode-broker.service.bak-20261015-123948`, and
rolling back means restoring that file, `chown -R kytran:kytran
/var/lib/host-opencode` and restarting the unit.

```bash
# 1. Isolated supervisor identity (no login, no shell)
sudo groupadd --system host-opencode
sudo useradd --system --no-create-home --shell /usr/sbin/nologin --gid host-opencode host-opencode
#    -> uid 996, gid 986, shell /usr/sbin/nologin

# 2. Supervisor storage moved to that identity; modes strict
sudo chown -R host-opencode:host-opencode /var/lib/host-opencode
sudo chmod 700 /var/lib/host-opencode /var/lib/host-opencode/keys
sudo chmod 600 /var/lib/host-opencode/keys/broker_private.key
sudo chmod 644 /var/lib/host-opencode/broker_journal.db

# 3. Broker runs as the isolated user
#    /etc/systemd/system/host-opencode-broker.service:  User=kytran -> User=host-opencode
#    ...plus one directive the original proposal did not need (see below)
sudo systemctl daemon-reload && sudo systemctl restart host-opencode-broker
```

### Two deviations from the proposed script, both forced by measurement

Swapping `User=` alone does **not** preserve behaviour. Two facts were measured on
the host *before* the restart, not inferred:

1. **`SupplementaryGroups=docker` had to be added.** `kytran` is a member of
   `docker` (gid 988) and the broker's observer shells out to `docker inspect`.
   A transient unit run as `host-opencode` *without* that directive returns
   `DOCKER_INSPECT_FAIL`; *with* it, `DOCKER_INSPECT_OK`. Nothing else in the
   unit grants it, so it is load-bearing.
2. **`Group=kytran` was deliberately kept**, not switched to `host-opencode`.
   The client (`services/codex_broker_client.py`) checks that the socket **and
   its parent directory** are owned by the expected broker uid, and the socket
   is `0660`. Keeping group `kytran` preserves group-`rw` on the socket for the
   trusted runner while granting `kytran` no access at all to the supervisor's
   own files, which are `0700` and owner-only. A `chgrp` post-step would have
   raced the socket bind, because `Type=simple` runs `ExecStartPost` before
   Python has bound.

### Verified against the running host, not against the files

| check | result |
|---|---|
| broker process identity | `uid 996 (host-opencode)`, `gid 1000`, `Groups: 988 (docker) 1000 (kytran)` |
| socket | `/run/host-opencode-broker/broker.sock` owned `host-opencode:kytran`, mode `660` |
| real client handshake as uid 1000 with `broker_uid=996` | `JOURNAL_OK []` |
| the same client with the default `broker_uid=1000` | `BrokerUnavailable: broker_endpoint_untrusted` |
| `verify_supervisor_provisioning(...)` as uid 996 over the real paths | `PROVISIONING_OK` |
| the same call as uid 1000 (a runner identity) | `PublicationBlocked: not_supervisor_identity` |
| the same call with the keys dir temporarily widened to `0755` | `PublicationBlocked: keys_dir_not_private` (then restored to `0700`) |

Property (a) — an isolated supervisor identity with a private journal/key
directory — is satisfied on this host for the first time. It was designed to
fail closed until now, and the gate's refusal was demonstrated on the runner
identity before it passed on the supervisor one.

### Consequence for the runner — recorded, not paid, and not a live break

`scripts/agents/codex-delegation-worker.py` builds its client with
`broker_uid = int(os.environ.get("CODEX_BROKER_UID", os.getuid()))`. The worker
runs as `kytran`, so after this change its default is the wrong uid and the
trust check refuses. This is **not** a live break: the worker only constructs a
`BrokerClient` when `CODEX_WORKER_BROKER_ENABLED=1`, and nothing on the host
sets that variable — supervised execution is off, per the handoff. When item 5
enables it, `CODEX_BROKER_UID=996` must be exported into the worker's
environment. That file is under `scripts/agents/*`, which is blocked for the
opencode lane, so it is recorded here and handed to whoever owns that change
rather than edited around the guard.

### Step 4 (credentials) — still open, by design

Unchanged and deliberately unscripted: the gh token (`repo` scope) sits in
`/home/kytran/.config/gh/hosts.yml`, readable by any `kytran` process. Until it
moves, property (b)'s "the supervisor is the sole holder and caller of
push/PR-create credentials" is not satisfied — and the "sole caller" half only
arrives with the broker wiring below.

After provisioning, the gate is still inert until the broker wiring above lands.
The recommended order stays: provisioning → wiring PR → isolated host exercise
(item 3) → Codex verification (item 4) → explicit approval (item 5).

## Running the isolated tests

```bash
cd platform_v2
PYTHONPATH=. python3 -m pytest \
  tests/test_publication_gate.py tests/test_publication_fence.py \
  tests/test_publication_publisher.py tests/test_codex_broker_consumer.py \
  -q --noconftest
```

`--noconftest` is required: the shared `tests/conftest.py` opens the platform
database, which these disposable-SQLite tests deliberately avoid.
