# Entity-Graph Ingest Endpoint (T-ING-1) + Compose Env-Contract Delta (I2)

**Date:** 2026-06-14
**Status:** ✅ **DEPLOYED + VERIFIED LIVE 2026-06-14.** Endpoint live on `wtf-consumer` (Citadel/boston-2) — route `/api/internal/entity-graph/ingest` registered, `create_app()` boots clean (the `COPY ingest/` import chain resolves), smoke test green (401 without key; 400 on bad product, no DB write). Migration 034 = APPLIED LIVE (PR #1690 merged). F.O.R.G.E./verifier corrections folded in (schema hardcoded to `shared`; market already had `INTERNAL_API_KEY`; `journalist` already accepted by migration 033). **Next:** the 5 dataset adapters that POST here over the mesh.
**Refs:** ADR-EG-001 (`2026-06-14-entity-graph-edge-vocabulary-adr.md`) §5 (single-writer / I1) + §5 (compose env contract / I2). Standalone-extraction.md "Platform-Integration Env Contract".

---

## 1. What was authored (code — this wave)

| File | Change |
|---|---|
| `what-the-fact/consumer/entity_graph_routes.py` | **NEW.** `POST /api/internal/entity-graph/ingest` — the SINGLE WRITER. Auth `X-Internal-Key == INTERNAL_API_KEY`. Reuses the ONE resolver `_upsert_entity` (imported from `ingest.shared.entity_graph` — NO third resolver). Validates `entity_type` against the frozen 3 node types and `relationship_type` against the frozen 10-edge vocabulary (ADR §1 + §2.4). Writes `shared.entities` (via `_upsert_entity`) + `shared.entity_mentions` + `shared.entity_relationships`, all idempotent UPSERTs on the migration-030 unique keys. One transaction per request. Connects ONLY to `WTF_DATABASE_URL` (the `wtf` DB — canonical graph, never the `archie` signal bus, ADR §3). |
| `what-the-fact/consumer/app.py` | Register `entity_graph_bp` (same pattern as `entities_bp`). |
| `what-the-fact/Dockerfile.consumer` | Add `COPY ingest/ /app/ingest/` so the consumer image ships the existing single resolver. **Required:** the resolver lives in `ingest/shared/entity_graph.py`; the prior Dockerfile copied only `shared/` + `consumer/`, so without this line the import is a runtime `ModuleNotFoundError`. Deps (`SQLAlchemy`, `psycopg2-binary`) are already in root `requirements.txt`; `ingest/__init__.py` + `ingest/shared/__init__.py` are empty (no heavy import side-effects — verified). |

### Request body shape
```json
{
  "product": "gov-watch|civic-watch|legal-watch|market-watch|wtf",
  "entities":      [{"canonical_name","slug","entity_type","role":{...},"raw_name"?}],
  "mentions":      [{"entity":<ref>,"content_type","content_id","mention_context"?,"confidence"?}],
  "relationships": [{"from":<ref>,"to":<ref>,"relationship_type","source_id"?,"valid_from"?,"valid_to"?,"metadata"?}]
}
```
`<ref>` = an inline entity object (resolved+upserted) OR `{"slug":"..."}` to point at an existing node.

### Responses
- `200 {"ok":true, ...stats}` on success.
- `503` if `INTERNAL_API_KEY` unset · `401` on key mismatch.
- `400` on bad `product`, unknown `entity_type`/`relationship_type`, or missing required fields (no partial write — single transaction).
- `413` if a collection exceeds its 5000-row batch cap · `500` on unexpected DB error.

### Single-writer invariant (ADR §5 / I1)
gov / civic / legal / market adapters POST here over the **mesh**; they do NOT open a cross-host DB connection. Only WTF's own hub-resident adapters write the DB directly. This endpoint reuses `_upsert_entity` — there is exactly ONE resolver.

---

## 2. Compose env-contract delta (I2) — civic + market (NOT applied this wave)

The adapters need two vars in the **`environment:` block** (both composes have **NO `env_file:`** → a value sitting in `.env` is **silently absent** from the container otherwise). Verify the RUNTIME env with `docker inspect`, never by reading `.env` (standalone-extraction.md rule 4).

| Var | Default | Purpose |
|---|---|---|
| `ENTITY_INGEST_URL` | `http://100.64.0.4:3000/api/internal/entity-graph/ingest` | Where the adapter POSTs edges/mentions. **Mesh-routed.** See §2.1 on the exact host/port. |
| `INTERNAL_API_KEY` | `${INTERNAL_API_KEY:-}` (empty passthrough) | `X-Internal-Key` the ingest endpoint checks. |

### 2.1 ⚠️ ENTITY_INGEST_URL host/port — resolve before deploy
The ingest endpoint is served by **wtf-consumer**, which lives on **Citadel/boston-2** (mesh `100.64.0.10`) listening on host port **8103** (`media/operational-state`), NOT on the hub (`100.64.0.4`). The mesh-correct default is therefore:

```
ENTITY_INGEST_URL=http://100.64.0.10:8103/api/internal/entity-graph/ingest
```

Use the **mesh IP of the node that runs wtf-consumer** + its published port. Do NOT use a public hostname (`what-the-fact.com` → Citadel ingress Caddy → 60s CDN-style cap, bypasses the mesh). Confirm the live wtf-consumer node + port with `docker inspect` at deploy time; the table below shows the value to set once confirmed. (`100.64.0.4:3000` is a placeholder ONLY if the endpoint is later fronted by the hub — it is not today.)

### 2.2 Civic compose (`/mnt/standalone/kytran-civic-watch/docker-compose.yml`, service `watch-api`)
Civic ALREADY has `INTERNAL_API_KEY=${INTERNAL_API_KEY:-}` in its `environment:` block. **Add ONLY** `ENTITY_INGEST_URL`:
```yaml
    environment:
      # ... existing vars ...
      - INTERNAL_API_KEY=${INTERNAL_API_KEY:-}        # already present
      - ENTITY_INGEST_URL=${ENTITY_INGEST_URL:-http://100.64.0.10:8103/api/internal/entity-graph/ingest}
```

### 2.3 Market compose (`/mnt/standalone/kytran-market-watch/docker-compose.yml`, service `kytran_market_api`)
Market **ALREADY has** `INTERNAL_API_KEY=${INTERNAL_API_KEY:-}` in its `environment:` block (line 67 — verified; added with the 2026-05-26 set-tier work; it also carries a separate `AC_INTERNAL_TOKEN`). **Add ONLY** `ENTITY_INGEST_URL`:
```yaml
    environment:
      # ... existing vars (INTERNAL_API_KEY=${INTERNAL_API_KEY:-} already present, line 67) ...
      - ENTITY_INGEST_URL=${ENTITY_INGEST_URL:-http://100.64.0.10:8103/api/internal/entity-graph/ingest}
```
Market is **chrome-only** in the graph (ADR §5.1 W4 — no securities entity to feed, Link 6 placeholder). The var is wired now for contract-parity/future use; the market adapter feeds 0 edges honestly.

### 2.4 Also set the value in each VPS `.env` (append-only)
The composes default to a mesh URL but `INTERNAL_API_KEY` MUST match the wtf-consumer side. On Citadel/boston-2 (`root@100.64.0.10`), append (never overwrite) to each product `.env`:
```
INTERNAL_API_KEY=<same value as wtf-consumer INTERNAL_API_KEY>
ENTITY_INGEST_URL=http://100.64.0.10:8103/api/internal/entity-graph/ingest
```

### 2.5 Runtime verification (post-deploy, NOT this wave)
```bash
# civic
docker inspect kytran_watch_api  -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'ENTITY_INGEST_URL|INTERNAL_API_KEY'
# market
docker inspect kytran_market_api -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'ENTITY_INGEST_URL|INTERNAL_API_KEY'
```
Only `docker inspect` is authoritative — a correct `.env` value means nothing if the var isn't in the `environment:` block.

---

## 3. Deferred to later waves (NOT in scope here)
- ✅ Migration 034 (`chain_link_types` + dedup/merge machinery + `entity_external_ids` + `source_mention` + `status`/`merged_into` + guard trigger) — **APPLIED LIVE to the `wtf` DB 2026-06-14 (PR #1690 merged)**. NOTE: `journalist` was already an accepted `entity_type` BEFORE 034 — migration 033 widened the CHECK to `person|organization|journalist` (verified live: `CHECK (entity_type = ANY (ARRAY['person','organization','journalist']))`). 034 did NOT touch the entity_type CHECK; it added the merge/dedup/external-id tables + the chain catalog. So inbound `journalist` entities are accepted now.
- gov/civic/legal/market adapter code that POSTs to this endpoint (Wave 1 — Stage-1 deterministic merge ships WITH the adapters per W2).
- Nightly dedup scan co-located with the `wtf` DB (I3).
- The gov-watch + WTF own hub-resident adapters writing the DB directly via `_upsert_entity`.

---

## 4. Hard-constraint compliance (this wave)
- ✅ Authored code (`entity_graph_routes.py`, `app.py`, `Dockerfile.consumer`) + this note ONLY.
- ✅ NO git commit/push.
- ✅ NO docker build/deploy/rebuild/restart.
- ✅ NO migration applied, NO query against any live service.
- ✅ Reused the ONE resolver (`_upsert_entity`) — no third resolver.
- Static checks done: `py_compile` of the new route + `app.py` (OK); `from ingest.shared.entity_graph import _upsert_entity` resolves with no side-effects (OK).
