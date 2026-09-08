# Hub systemd units

## `archie-mesh-ip-wait.service` + `docker.service.d-10-wait-for-mesh-ip.conf`

**The outage this prevents (2026-09-08 20:08 UTC, ~14 min, hub fully down).**

`archie_database` publishes 5432 on **two** host IPs (`docker-compose.yml`):

```
- "192.168.1.200:5432:5432"   # LAN
- "100.64.0.4:5432:5432"      # mesh (PR #822 / task #2142)
```

The mesh address lives on `tailscale1`, brought up by `tailscaled-headscale.service` —
a userspace VPN interface that appears **asynchronously**. Start a container that binds it
before it exists and Docker fails the whole network setup:

```
failed to bind host port 100.64.0.4:5432/tcp: cannot assign requested address
```

Postgres then exits **255** with `Networks={}` — running by some measures, attached to
nothing. `archie_platform` restart-loops on `could not translate host name
"archie_database"`, hub `:3000` flaps, and Citadel's front door correctly 502s every
public hostname. One absent address takes down the entire platform.

⚠️ **`restart: unless-stopped` does NOT cover this.** That policy restarts a container whose
*process* dies. Here the failure is in **start-time network setup**, so the container never
runs, `RestartCount` stays **0**, and Docker never retries. Measured, not assumed.

⚠️ **The mesh publish is load-bearing — do not "simplify" it away.** Citadel's DR replica
dials it directly: `primary_conninfo = 'host=100.64.0.4 port=5432 ... application_name=boston2_replica'`.

⚠️ **Do not widen it to `0.0.0.0:5432` either.** There is **no host firewall** on the hub
(`ufw` is not installed), so the two explicit binds *are* the access control. A wildcard
bind would put Postgres on every interface — a worse bug than the one being fixed.

### What the gate does

Blocks until `100.64.0.4` is actually assigned to `tailscale1`, ordered `Before=docker.service`.

**Bounded on purpose:** it gives up after 60s and **exits 0**, letting Docker start anyway.
This removes a *race*; it must never become a new way to wedge the host at boot. If the
address is genuinely missing the DB fails loudly exactly as before — the honest outcome.
Verified: with a bogus address it logs the warning and exits 0 after 60s.

`Wants=` (not `Requires=`) on the Docker drop-in, so a failed or absent gate can never
block Docker.

### Install

```bash
sudo install -m 755 scripts/systemd/archie-wait-mesh-ip.sh /usr/local/sbin/archie-wait-mesh-ip.sh
sudo install -m 644 scripts/systemd/archie-mesh-ip-wait.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo install -m 644 scripts/systemd/docker.service.d-10-wait-for-mesh-ip.conf \
     /etc/systemd/system/docker.service.d/10-wait-for-mesh-ip.conf
sudo systemctl daemon-reload
sudo systemctl enable --now archie-mesh-ip-wait.service
```

**Do NOT restart `docker.service` to apply this** — that bounces every container on the hub.
The ordering only matters at boot, so installing and enabling is enough.

Verify:
```bash
systemctl is-active archie-mesh-ip-wait.service                       # active
systemctl show docker.service -p After | tr ' ' '\n' | grep archie-mesh   # ordering applied
```
