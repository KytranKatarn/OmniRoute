# Media Studio Layer 1 — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Media Studio as a full LCARS module with ComfyUI image generation, Bridge dispatch, gallery, and queue — the foundation for Layers 2-4.

**Architecture:** Flask Blueprint with services layer (generation, gallery, comfyui_manager). All generation routes through Bridge dispatcher → Pixel agent → ComfyUI. GPU-tiered fleet dispatch ranks nodes best-first. Results stored in `media_library` table + filesystem with per-user ownership.

**Tech Stack:** Flask, PostgreSQL, ComfyUI API, Bridge dispatcher, LCARS CSS (panels + frames), StationOps terminal, archie-time.js

**Spec:** `docs/superpowers/specs/2026-03-13-media-studio-design.md`

---

## Chunk 1: Database + Services Backend

### Task 1: Database Migration 149

**Files:**
- Create: `database/migrations/149_media_studio_tables.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- Migration 149: Media Studio tables
-- Idempotent: uses IF NOT EXISTS / ON CONFLICT

-- Core media library — every generated asset
CREATE TABLE IF NOT EXISTS media_library (
    id SERIAL PRIMARY KEY,
    owner_type VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id INTEGER,
    media_type VARCHAR(20) NOT NULL,
    file_path TEXT NOT NULL,
    thumbnail_path TEXT,
    prompt TEXT,
    negative_prompt TEXT,
    model VARCHAR(100),
    provider VARCHAR(50),
    node_id INTEGER REFERENCES remote_nodes(id),
    seed BIGINT,
    width INTEGER,
    height INTEGER,
    duration_seconds DECIMAL(8,2),
    duration_ms INTEGER,
    cost DECIMAL(10,4) DEFAULT 0,
    is_favorite BOOLEAN DEFAULT false,
    is_deleted BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_media_library_owner ON media_library(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_library_type ON media_library(media_type);
CREATE INDEX IF NOT EXISTS idx_media_library_created ON media_library(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_library_not_deleted ON media_library(id) WHERE is_deleted = false;

-- Generation queue — job tracking (owner_id NOT NULL — queue jobs always have an owner)
CREATE TABLE IF NOT EXISTS media_generation_queue (
    id SERIAL PRIMARY KEY,
    owner_type VARCHAR(20) NOT NULL DEFAULT 'user',
    owner_id INTEGER NOT NULL,
    media_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    bridge_job_id INTEGER REFERENCES bridge_jobs(id) ON DELETE SET NULL,
    params JSONB NOT NULL DEFAULT '{}',
    result_media_id INTEGER REFERENCES media_library(id),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_media_queue_status ON media_generation_queue(status);
CREATE INDEX IF NOT EXISTS idx_media_queue_owner ON media_generation_queue(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_queue_bridge_job ON media_generation_queue(bridge_job_id);

-- Agent portraits — face identity system (Layer 2 ready)
CREATE TABLE IF NOT EXISTS agent_portraits (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) UNIQUE,
    canonical_image_path TEXT,
    identity_prompt TEXT,
    face_seed BIGINT,
    ip_adapter_ref_path TEXT,
    style_tags JSONB DEFAULT '[]',
    approved BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Media assignments — maps media to UI locations
CREATE TABLE IF NOT EXISTS media_assignments (
    id SERIAL PRIMARY KEY,
    media_id INTEGER REFERENCES media_library(id),
    assignment_type VARCHAR(50) NOT NULL,
    target_type VARCHAR(30) NOT NULL,
    target_id INTEGER,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_media_assignments_target ON media_assignments(target_type, target_id, is_active);

-- Agent voices — voice identity system (Layer 4 ready)
CREATE TABLE IF NOT EXISTS agent_voices (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) UNIQUE,
    provider VARCHAR(50) NOT NULL,
    voice_id VARCHAR(100),
    voice_params JSONB DEFAULT '{}',
    sample_path TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/149_media_studio_tables.sql
```

If the file isn't mounted, copy it first:
```bash
docker cp database/migrations/149_media_studio_tables.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/149_media_studio_tables.sql
```

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt media_*" -c "\dt agent_portraits" -c "\dt agent_voices"
```

Expected: 4 tables listed (media_library, media_generation_queue, media_assignments + agent_portraits, agent_voices)

- [ ] **Step 4: Commit**

```bash
git add database/migrations/149_media_studio_tables.sql
git commit -m "feat(media-studio): migration 149 — media library, queue, portraits, voices tables"
```

---

### Task 2: ComfyUI Manager Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/__init__.py`
- Create: `platform_v2/tools/media_studio/services/comfyui_manager.py`

**Context:** Wraps existing `ai_bridge/comfyui_service.py` (class `ComfyUIService`, singleton via `get_comfyui_service()`). Adds fleet awareness — discovers ComfyUI instances across nodes, classifies GPU tiers, ranks nodes for dispatch.

- [ ] **Step 1: Create services package**

Create empty `__init__.py`:
```python
"""Media Studio services."""
```

- [ ] **Step 2: Write comfyui_manager.py**

```python
"""ComfyUI fleet manager — discovers instances, classifies GPU tiers, ranks nodes.

Wraps ai_bridge.comfyui_service for local ComfyUI. Queries remote_nodes
for fleet-wide ComfyUI status reported via heartbeat.
"""

import logging
from typing import Dict, List, Optional, Tuple

from database import get_db_cursor

logger = logging.getLogger(__name__)

# GPU tier definitions — VRAM thresholds and supported features
GPU_TIERS = {
    "high": {
        "min_vram_mb": 24576,
        "features": [
            "sdxl",
            "animatediff_sdxl",
            "ip_adapter",
            "instantid",
            "large_batch",
        ],
    },
    "mid": {
        "min_vram_mb": 10240,
        "features": ["sdxl", "animatediff_sd15", "ip_adapter", "instantid"],
    },
    "base": {
        "min_vram_mb": 6144,
        "features": ["sd15", "sdxl_single", "animatediff_sd15", "ip_adapter_tight"],
    },
    "cpu": {
        "min_vram_mb": 0,
        "features": ["sd15_slow", "tts"],
    },
}

# Map operations to minimum required features
OPERATION_REQUIREMENTS = {
    "image_sd15": "sd15",
    "image_sdxl": "sdxl",
    "animatediff_sd15": "animatediff_sd15",
    "animatediff_sdxl": "animatediff_sdxl",
    "ip_adapter": "ip_adapter",
    "instantid": "instantid",
}


def classify_gpu_tier(vram_mb: int) -> str:
    """Classify a GPU into a capability tier based on VRAM."""
    for tier_name in ["high", "mid", "base"]:
        if vram_mb >= GPU_TIERS[tier_name]["min_vram_mb"]:
            return tier_name
    return "cpu"


def tier_supports_feature(tier: str, feature: str) -> bool:
    """Check if a GPU tier supports a specific feature."""
    tier_def = GPU_TIERS.get(tier, GPU_TIERS["cpu"])
    return feature in tier_def["features"]


def get_fleet_comfyui_status() -> List[Dict]:
    """Get ComfyUI status for all nodes including Starbase.

    Returns list of dicts with node_id, node_name, comfyui_healthy,
    vram_mb, gpu_name, gpu_tier, and supported features.
    """
    from ai_bridge.comfyui_service import get_comfyui_service

    nodes = []

    # Starbase (local) ComfyUI
    try:
        svc = get_comfyui_service()
        healthy = svc.health_check()
        stats = svc.get_system_stats() if healthy else {}
        vram_mb = 0
        gpu_name = "Unknown"
        if stats:
            devices = stats.get("devices", [])
            if devices:
                dev = devices[0]
                vram_mb = int(dev.get("vram_total", 0) / (1024 * 1024))
                gpu_name = dev.get("name", "Unknown")
        tier = classify_gpu_tier(vram_mb)
        nodes.append(
            {
                "node_id": None,
                "node_name": "Archie Starbase",
                "is_local": True,
                "comfyui_healthy": healthy,
                "vram_mb": vram_mb,
                "gpu_name": gpu_name,
                "gpu_tier": tier,
                "features": GPU_TIERS[tier]["features"],
            }
        )
    except Exception as e:
        logger.warning(f"Failed to check local ComfyUI: {e}")
        nodes.append(
            {
                "node_id": None,
                "node_name": "Archie Starbase",
                "is_local": True,
                "comfyui_healthy": False,
                "vram_mb": 0,
                "gpu_name": "Unknown",
                "gpu_tier": "cpu",
                "features": [],
            }
        )

    # Fleet nodes — read GPU info from remote_nodes.metadata
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, node_name, metadata, last_heartbeat,
                       EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) as heartbeat_age_s
                FROM remote_nodes
                WHERE status = 'online'
                ORDER BY node_name
                """
            )
            for row in cur.fetchall():
                meta = row["metadata"] or {}
                gpu_info = meta.get("gpu", {})
                vram_mb = gpu_info.get("vram_mb", 0)
                gpu_name = gpu_info.get("name", "Unknown")
                tier = gpu_info.get("tier") or classify_gpu_tier(vram_mb)
                comfyui_ok = meta.get("comfyui_healthy", False)
                # Stale heartbeat (>2 min) = unhealthy
                if row["heartbeat_age_s"] and row["heartbeat_age_s"] > 120:
                    comfyui_ok = False
                nodes.append(
                    {
                        "node_id": row["id"],
                        "node_name": row["node_name"],
                        "is_local": False,
                        "comfyui_healthy": comfyui_ok,
                        "vram_mb": vram_mb,
                        "gpu_name": gpu_name,
                        "gpu_tier": tier,
                        "features": GPU_TIERS.get(tier, GPU_TIERS["cpu"])[
                            "features"
                        ],
                    }
                )
    except Exception as e:
        logger.warning(f"Failed to query fleet nodes: {e}")

    return nodes


def get_available_models() -> List[Dict]:
    """Get available ComfyUI checkpoints from local instance."""
    from ai_bridge.comfyui_service import get_comfyui_service

    try:
        svc = get_comfyui_service()
        models = svc.get_models()
        return [{"name": m, "source": "local"} for m in models]
    except Exception as e:
        logger.warning(f"Failed to get models: {e}")
        return []


def can_node_handle(node_status: Dict, operation: str) -> bool:
    """Check if a node can handle the requested operation."""
    if not node_status.get("comfyui_healthy"):
        return False
    required_feature = OPERATION_REQUIREMENTS.get(operation)
    if not required_feature:
        return True
    return required_feature in node_status.get("features", [])


def rank_nodes_for_operation(operation: str) -> List[Dict]:
    """Return fleet nodes ranked best-first for a given operation.

    Filters to capable + healthy nodes, sorts by VRAM descending.
    """
    fleet = get_fleet_comfyui_status()
    capable = [n for n in fleet if can_node_handle(n, operation)]
    capable.sort(key=lambda n: n["vram_mb"], reverse=True)
    return capable


def build_txt2img_workflow(
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
) -> Dict:
    """Build a ComfyUI txt2img workflow JSON for the /prompt API.

    Returns a workflow dict with nodes:
    1: CheckpointLoaderSimple, 2: EmptyLatentImage,
    3: CLIPTextEncode (positive), 4: CLIPTextEncode (negative),
    5: KSampler, 6: VAEDecode, 7: SaveImage
    """
    import random

    if seed < 0:
        seed = random.randint(0, 2**63)

    return {
        "prompt": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": model},
            },
            "2": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt
                    or "blurry, low quality, distorted, deformed",
                    "clip": ["1", 1],
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["3", 0],
                    "negative": ["4", 0],
                    "latent_image": ["2", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": "normal",
                    "denoise": 1.0,
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {"images": ["6", 0], "filename_prefix": "media_studio"},
            },
        }
    }
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/
git commit -m "feat(media-studio): ComfyUI manager — GPU tiers, fleet discovery, workflow builder"
```

---

### Task 3: Gallery Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/gallery_service.py`

**Context:** CRUD for `media_library` table. Per-user and per-agent ownership. Uses `get_db_cursor` pattern from `database.py`. Soft deletes only.

- [ ] **Step 1: Write gallery_service.py**

```python
"""Gallery service — media library CRUD with ownership tracking.

All queries filter by owner for access control. Soft-delete only.
"""

import logging
import os
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

MEDIA_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "static",
    "media",
)


def get_gallery(
    owner_type: str,
    owner_id: int,
    media_type: Optional[str] = None,
    favorites_only: bool = False,
    page: int = 1,
    per_page: int = 20,
) -> Dict:
    """Paginated media library query with filters."""
    offset = (page - 1) * per_page
    conditions = ["is_deleted = false", "owner_type = %s", "owner_id = %s"]
    params = [owner_type, owner_id]

    if media_type:
        conditions.append("media_type = %s")
        params.append(media_type)
    if favorites_only:
        conditions.append("is_favorite = true")

    where = " AND ".join(conditions)

    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT COUNT(*) as total FROM media_library WHERE {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT id, media_type, file_path, thumbnail_path, prompt, model,
                   provider, seed, width, height, duration_ms, cost,
                   is_favorite, metadata, created_at
            FROM media_library
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        items = cur.fetchall()

    return {
        "items": [dict(row) for row in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def get_media_detail(media_id: int, owner_type: str, owner_id: int) -> Optional[Dict]:
    """Full metadata with ownership check."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT * FROM media_library
            WHERE id = %s AND owner_type = %s AND owner_id = %s AND is_deleted = false
            """,
            (media_id, owner_type, owner_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def create_media_entry(
    owner_type: str,
    owner_id: Optional[int],
    media_type: str,
    file_path: str,
    thumbnail_path: Optional[str] = None,
    prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    node_id: Optional[int] = None,
    seed: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration_ms: Optional[int] = None,
    cost: float = 0,
    metadata: Optional[Dict] = None,
) -> int:
    """Insert a new media library entry. Returns the new ID."""
    import psycopg2.extras

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_library
                (owner_type, owner_id, media_type, file_path, thumbnail_path,
                 prompt, negative_prompt, model, provider, node_id, seed,
                 width, height, duration_ms, cost, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                owner_type,
                owner_id,
                media_type,
                file_path,
                thumbnail_path,
                prompt,
                negative_prompt,
                model,
                provider,
                node_id,
                seed,
                width,
                height,
                duration_ms,
                cost,
                psycopg2.extras.Json(metadata or {}),
            ),
        )
        return cur.fetchone()["id"]


def delete_media(media_id: int, owner_type: str, owner_id: int) -> bool:
    """Soft delete with ownership verification."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_library SET is_deleted = true
            WHERE id = %s AND owner_type = %s AND owner_id = %s AND is_deleted = false
            """,
            (media_id, owner_type, owner_id),
        )
        return cur.rowcount > 0


def toggle_favorite(media_id: int, owner_type: str, owner_id: int) -> Optional[bool]:
    """Toggle is_favorite flag. Returns new state or None if not found."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_library SET is_favorite = NOT is_favorite
            WHERE id = %s AND owner_type = %s AND owner_id = %s AND is_deleted = false
            RETURNING is_favorite
            """,
            (media_id, owner_type, owner_id),
        )
        row = cur.fetchone()
    return row["is_favorite"] if row else None


def assign_media(
    media_id: int,
    assignment_type: str,
    target_type: str,
    target_id: Optional[int] = None,
) -> int:
    """Link media to a UI location. Deactivates previous assignment for same target+type."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Deactivate previous
        cur.execute(
            """
            UPDATE media_assignments SET is_active = false
            WHERE assignment_type = %s AND target_type = %s AND target_id = %s
                  AND is_active = true
            """,
            (assignment_type, target_type, target_id),
        )
        # Create new
        cur.execute(
            """
            INSERT INTO media_assignments (media_id, assignment_type, target_type, target_id)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            (media_id, assignment_type, target_type, target_id),
        )
        return cur.fetchone()["id"]


def get_active_assignment(
    assignment_type: str, target_type: str, target_id: Optional[int] = None
) -> Optional[Dict]:
    """Get active media assignment for a target."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT ma.*, ml.file_path, ml.thumbnail_path
            FROM media_assignments ma
            JOIN media_library ml ON ml.id = ma.media_id
            WHERE ma.assignment_type = %s AND ma.target_type = %s
                  AND ma.target_id = %s AND ma.is_active = true
            """,
            (assignment_type, target_type, target_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/services/gallery_service.py
git commit -m "feat(media-studio): gallery service — CRUD, ownership, assignments"
```

---

### Task 4: Generation Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/generation_service.py`

**Context:** Orchestrates generation requests. Creates queue entries, dispatches to Bridge via `request_work()` (from `bridge_dispatcher.py`), handles completion/failure callbacks. Bridge dispatcher method signature: `request_work(capability, prompt, module_id, context, user_id, priority, prefer_gpu, prefer_agent)` → `DispatchResult`.

- [ ] **Step 1: Write generation_service.py**

```python
"""Generation service — orchestrates media creation through Bridge dispatch.

Submits jobs to Bridge dispatcher which handles agent selection,
GPU-tiered fleet routing, and escalation chain.
"""

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import psycopg2.extras

from database import get_db_cursor

logger = logging.getLogger(__name__)

MEDIA_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "static",
    "media",
)

# Capability map: media type → Bridge capability
MEDIA_TYPE_CAPABILITIES = {
    "image": "image_generation",
    "video": "video_generation",
    "audio": "audio_generation",
}

# Default generation params
DEFAULT_IMAGE_PARAMS = {
    "model": "sd_xl_base_1.0.safetensors",
    "width": 1024,
    "height": 1024,
    "steps": 25,
    "cfg": 7.0,
    "sampler": "euler_ancestral",
    "seed": -1,
}


def submit_generation(
    user_id: int,
    media_type: str,
    prompt: str,
    negative_prompt: str = "",
    params: Optional[Dict] = None,
) -> Dict:
    """Submit a generation request.

    Creates queue entry, dispatches to Bridge, returns queue_id for polling.
    """
    if media_type not in MEDIA_TYPE_CAPABILITIES:
        return {"error": f"Unsupported media type: {media_type}"}

    merged_params = {**DEFAULT_IMAGE_PARAMS, **(params or {})}
    merged_params["prompt"] = prompt
    merged_params["negative_prompt"] = negative_prompt

    # Create queue entry
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO media_generation_queue
                (owner_type, owner_id, media_type, status, params)
            VALUES ('user', %s, %s, 'pending', %s)
            RETURNING id
            """,
            (user_id, media_type, psycopg2.extras.Json(merged_params)),
        )
        queue_id = cur.fetchone()["id"]

    # Dispatch to Bridge
    try:
        from ai_bridge.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        capability = MEDIA_TYPE_CAPABILITIES[media_type]

        # Build a generation-specific prompt for Bridge
        bridge_prompt = (
            f"Generate {media_type}: {prompt}\n"
            f"Model: {merged_params.get('model')}\n"
            f"Size: {merged_params.get('width')}x{merged_params.get('height')}\n"
            f"Steps: {merged_params.get('steps')}"
        )

        result = dispatcher.request_work(
            capability=capability,
            prompt=bridge_prompt,
            module_id="media_studio",
            context={
                "queue_id": queue_id,
                "params": merged_params,
                "media_type": media_type,
            },
            user_id=user_id,
            priority="normal",
            prefer_gpu=True,
            prefer_agent="Pixel",
        )

        # Update queue with Bridge job info
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'dispatched', started_at = NOW()
                WHERE id = %s
                """,
                (queue_id,),
            )

        return {
            "queue_id": queue_id,
            "status": "dispatched",
            "agent": getattr(result, "agent_name", None),
        }

    except Exception as e:
        logger.error(f"Bridge dispatch failed for queue {queue_id}: {e}")
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'failed', error_message = %s, completed_at = NOW()
                WHERE id = %s
                """,
                (str(e), queue_id),
            )
        return {"queue_id": queue_id, "status": "failed", "error": str(e)}


def on_generation_complete(
    queue_id: int,
    file_path: str,
    seed: Optional[int] = None,
    duration_ms: Optional[int] = None,
    provider: str = "comfyui",
    node_id: Optional[int] = None,
) -> Optional[int]:
    """Handle completed generation — save to library, update queue.

    Returns media_library ID or None on failure.
    """
    from .gallery_service import create_media_entry

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        logger.error(f"Queue entry {queue_id} not found")
        return None

    params = queue_row["params"] or {}

    # Move file to user's media directory
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    owner_dir = os.path.join(
        MEDIA_ROOT,
        f"{queue_row['owner_type']}s",
        str(queue_row["owner_id"] or "system"),
        date_str,
    )
    os.makedirs(owner_dir, exist_ok=True)

    filename = f"media_{queue_id}_{int(time.time())}.png"
    dest_path = os.path.join(owner_dir, filename)

    try:
        shutil.copy2(file_path, dest_path)
    except Exception as e:
        logger.error(f"Failed to copy media file: {e}")
        dest_path = file_path

    # Relative path for DB storage (from static/)
    rel_path = os.path.relpath(dest_path, os.path.join(MEDIA_ROOT, ".."))

    # Create thumbnail (256px wide)
    thumb_path = None
    try:
        from PIL import Image

        img = Image.open(dest_path)
        thumb_w = 256
        thumb_h = int(img.height * (thumb_w / img.width))
        img.thumbnail((thumb_w, thumb_h))
        thumb_filename = f"thumb_{filename}"
        thumb_full = os.path.join(owner_dir, thumb_filename)
        img.save(thumb_full, "PNG")
        thumb_path = os.path.relpath(thumb_full, os.path.join(MEDIA_ROOT, ".."))
    except Exception as e:
        logger.warning(f"Thumbnail generation failed: {e}")

    # Insert into media_library
    media_id = create_media_entry(
        owner_type=queue_row["owner_type"],
        owner_id=queue_row["owner_id"],
        media_type=queue_row["media_type"],
        file_path=rel_path,
        thumbnail_path=thumb_path,
        prompt=params.get("prompt"),
        negative_prompt=params.get("negative_prompt"),
        model=params.get("model"),
        provider=provider,
        node_id=node_id,
        seed=seed,
        width=params.get("width"),
        height=params.get("height"),
        duration_ms=duration_ms,
    )

    # Update queue
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'completed', result_media_id = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (media_id, queue_id),
        )

    return media_id


def on_generation_failed(queue_id: int, error: str) -> None:
    """Handle failed generation — update queue status."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'failed', error_message = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (error, queue_id),
        )


def cancel_generation(queue_id: int, user_id: int) -> bool:
    """Cancel a pending/dispatched generation. Returns True if cancelled."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'cancelled', completed_at = NOW()
            WHERE id = %s AND owner_type = 'user' AND owner_id = %s
                  AND status IN ('pending', 'dispatched')
            """,
            (queue_id, user_id),
        )
        return cur.rowcount > 0


def get_queue_status(
    owner_type: str = "user",
    owner_id: Optional[int] = None,
    limit: int = 20,
) -> list:
    """Get recent queue entries for polling."""
    with get_db_cursor() as (conn, cur):
        if owner_id:
            cur.execute(
                """
                SELECT q.*, ml.thumbnail_path
                FROM media_generation_queue q
                LEFT JOIN media_library ml ON ml.id = q.result_media_id
                WHERE q.owner_type = %s AND q.owner_id = %s
                ORDER BY q.created_at DESC
                LIMIT %s
                """,
                (owner_type, owner_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT q.*, ml.thumbnail_path
                FROM media_generation_queue q
                LEFT JOIN media_library ml ON ml.id = q.result_media_id
                ORDER BY q.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        return [dict(row) for row in cur.fetchall()]


def get_dashboard_stats(user_id: int) -> Dict:
    """Get dashboard statistics for a user."""
    with get_db_cursor() as (conn, cur):
        # Total generations
        cur.execute(
            "SELECT COUNT(*) as total FROM media_library WHERE owner_type = 'user' AND owner_id = %s AND is_deleted = false",
            (user_id,),
        )
        total = cur.fetchone()["total"]

        # By type
        cur.execute(
            """
            SELECT media_type, COUNT(*) as count
            FROM media_library
            WHERE owner_type = 'user' AND owner_id = %s AND is_deleted = false
            GROUP BY media_type
            """,
            (user_id,),
        )
        by_type = {row["media_type"]: row["count"] for row in cur.fetchall()}

        # Active queue
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM media_generation_queue
            WHERE owner_type = 'user' AND owner_id = %s
                  AND status IN ('pending', 'dispatched', 'generating')
            GROUP BY status
            """,
            (user_id,),
        )
        active_queue = {row["status"]: row["count"] for row in cur.fetchall()}

        # Recent (last 8 for dashboard grid)
        cur.execute(
            """
            SELECT id, media_type, thumbnail_path, file_path, prompt, created_at
            FROM media_library
            WHERE owner_type = 'user' AND owner_id = %s AND is_deleted = false
            ORDER BY created_at DESC LIMIT 8
            """,
            (user_id,),
        )
        recent = [dict(row) for row in cur.fetchall()]

    return {
        "total_generations": total,
        "by_type": by_type,
        "active_queue": active_queue,
        "recent": recent,
    }
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): generation service — Bridge dispatch, queue, callbacks"
```

---

## Chunk 2: Blueprint + API Routes

### Task 5: Rebuild Blueprint + Routes

**Files:**
- Modify: `platform_v2/tools/media_studio/__init__.py`
- Modify: `platform_v2/tools/media_studio/routes.py` (full rewrite)

**Context:** Current `__init__.py` is minimal (no template_folder). Current `routes.py` has basic endpoints that route through `external_providers` with the legacy `get_db()` pattern. **This is a FULL REWRITE** — delete all existing route functions and replace entirely. Do NOT merge old code. The new routes use services layer with `get_db_cursor` context manager exclusively.

- [ ] **Step 1: Update __init__.py**

```python
"""Media Studio — AI media generation hub.

Full LCARS module for generating images, video, and audio through
Bridge dispatch with GPU-tiered fleet routing.
"""

from flask import Blueprint

media_studio_bp = Blueprint(
    "media_studio",
    __name__,
    url_prefix="/tools/media-studio",
    template_folder="templates",
    static_folder="static",
)

from . import routes  # noqa: E402, F401
```

- [ ] **Step 2: Rewrite routes.py**

```python
"""Media Studio API routes — thin HTTP handlers calling services.

All generation routes through Bridge dispatcher. Gallery with
per-user ownership. ComfyUI fleet status with GPU tiering.
"""

import logging

from flask import jsonify, request, render_template
from flask_login import login_required, current_user

from . import media_studio_bp

logger = logging.getLogger(__name__)


# ─── Page Route ─────────────────────────────────────────────────────

@media_studio_bp.route("/")
@login_required
def index():
    """Render the Media Studio LCARS UI."""
    return render_template("tools/media_studio/media_studio.html")


# ─── Dashboard ──────────────────────────────────────────────────────

@media_studio_bp.route("/api/dashboard")
@login_required
def api_dashboard():
    """Dashboard stats, recent generations, fleet GPU status."""
    from .services.generation_service import get_dashboard_stats
    from .services.comfyui_manager import get_fleet_comfyui_status

    stats = get_dashboard_stats(current_user.id)
    fleet = get_fleet_comfyui_status()

    return jsonify({"stats": stats, "fleet": fleet})


# ─── Generation ─────────────────────────────────────────────────────

@media_studio_bp.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    """Submit a generation request."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    media_type = data.get("media_type", "image")
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    result = submit_generation(
        user_id=current_user.id,
        media_type=media_type,
        prompt=prompt,
        negative_prompt=data.get("negative_prompt", ""),
        params={
            k: data[k]
            for k in ("model", "width", "height", "steps", "cfg", "sampler", "seed")
            if k in data
        },
    )

    if "error" in result:
        return jsonify(result), 400 if "Unsupported" in result["error"] else 500

    return jsonify(result), 201


# ─── Queue ──────────────────────────────────────────────────────────

@media_studio_bp.route("/api/queue")
@login_required
def api_queue():
    """Get generation queue for current user."""
    from .services.generation_service import get_queue_status

    limit = request.args.get("limit", 20, type=int)
    jobs = get_queue_status(owner_type="user", owner_id=current_user.id, limit=limit)
    return jsonify({"jobs": jobs})


@media_studio_bp.route("/api/queue/<int:queue_id>/cancel", methods=["POST"])
@login_required
def api_cancel_job(queue_id):
    """Cancel a pending/dispatched generation job."""
    from .services.generation_service import cancel_generation

    ok = cancel_generation(queue_id, current_user.id)
    if ok:
        return jsonify({"status": "cancelled"})
    return jsonify({"error": "Job not found or not cancellable"}), 404


# ─── Gallery ────────────────────────────────────────────────────────

@media_studio_bp.route("/api/gallery")
@login_required
def api_gallery():
    """Paginated gallery for current user."""
    from .services.gallery_service import get_gallery

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    media_type = request.args.get("type")
    favorites = request.args.get("favorites", "false").lower() == "true"

    result = get_gallery(
        owner_type="user",
        owner_id=current_user.id,
        media_type=media_type,
        favorites_only=favorites,
        page=page,
        per_page=per_page,
    )
    return jsonify(result)


@media_studio_bp.route("/api/gallery/<int:media_id>")
@login_required
def api_gallery_detail(media_id):
    """Single media detail with full metadata."""
    from .services.gallery_service import get_media_detail

    item = get_media_detail(media_id, "user", current_user.id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item)


@media_studio_bp.route("/api/gallery/<int:media_id>/favorite", methods=["POST"])
@login_required
def api_toggle_favorite(media_id):
    """Toggle favorite on a media item."""
    from .services.gallery_service import toggle_favorite

    new_state = toggle_favorite(media_id, "user", current_user.id)
    if new_state is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"is_favorite": new_state})


@media_studio_bp.route("/api/gallery/<int:media_id>", methods=["DELETE"])
@login_required
def api_delete_media(media_id):
    """Soft delete a media item."""
    from .services.gallery_service import delete_media

    ok = delete_media(media_id, "user", current_user.id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "deleted"})


# ─── Models + ComfyUI Status ───────────────────────────────────────

@media_studio_bp.route("/api/models")
@login_required
def api_models():
    """Available ComfyUI models across fleet."""
    from .services.comfyui_manager import get_available_models

    return jsonify({"models": get_available_models()})


@media_studio_bp.route("/api/comfyui/status")
@login_required
def api_comfyui_status():
    """Fleet ComfyUI health with GPU tiers."""
    from .services.comfyui_manager import get_fleet_comfyui_status

    return jsonify({"nodes": get_fleet_comfyui_status()})


# ─── Assignments ────────────────────────────────────────────────────

@media_studio_bp.route("/api/assignments/<target_type>/<int:target_id>")
@login_required
def api_get_assignment(target_type, target_id):
    """Get active media assignments for a target."""
    from .services.gallery_service import get_active_assignment

    assignment_type = request.args.get("type", "")
    if not assignment_type:
        return jsonify({"error": "type parameter required"}), 400

    result = get_active_assignment(assignment_type, target_type, target_id)
    return jsonify({"assignment": result})


@media_studio_bp.route("/api/assignments", methods=["POST"])
@login_required
def api_create_assignment():
    """Assign media to a UI location."""
    from .services.gallery_service import assign_media

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    required = ["media_id", "assignment_type", "target_type"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Required: {', '.join(required)}"}), 400

    assignment_id = assign_media(
        media_id=data["media_id"],
        assignment_type=data["assignment_type"],
        target_type=data["target_type"],
        target_id=data.get("target_id"),
    )
    return jsonify({"id": assignment_id}), 201
```

- [ ] **Step 3: Create template directories**

```bash
mkdir -p platform_v2/tools/media_studio/templates/tools/media_studio
mkdir -p platform_v2/tools/media_studio/static/css
mkdir -p platform_v2/tools/media_studio/static/js
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/__init__.py platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): rebuild blueprint + routes — services-backed API"
```

---

### Task 6: Create media directories

**Files:**
- Create: `platform_v2/static/media/.gitkeep`

- [ ] **Step 1: Create filesystem directories**

```bash
mkdir -p platform_v2/static/media/users
mkdir -p platform_v2/static/media/agents
mkdir -p platform_v2/static/media/portraits
mkdir -p platform_v2/static/media/environments/hub
mkdir -p platform_v2/static/media/environments/nodes
touch platform_v2/static/media/.gitkeep
```

- [ ] **Step 2: Add to .gitignore**

Add to project `.gitignore`:
```
# Media Studio generated files (keep directory structure via .gitkeep)
platform_v2/static/media/users/
platform_v2/static/media/agents/
platform_v2/static/media/portraits/
platform_v2/static/media/environments/
!platform_v2/static/media/.gitkeep
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/media/.gitkeep .gitignore
git commit -m "feat(media-studio): media directory structure + gitignore"
```

---

### Task 6b: Update Module Registry Health Check + RBAC

**Files:**
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`

**Context:** The existing `media_studio_health_check()` in module_registry checks for the old template path. Must update to the new blueprint-local path. RBAC must add `MEDIA_STUDIO_GENERATE` and `MEDIA_STUDIO_MANAGE` permissions per CLAUDE.md rule #4.

- [ ] **Step 1: Update health check in module_registry.py**

Find the `media_studio_health_check` function and update the template path check to:
```python
os.path.exists(os.path.join(os.path.dirname(__file__), "tools", "media_studio", "templates", "tools", "media_studio", "media_studio.html"))
```

- [ ] **Step 2: Add RBAC permissions**

Add to `rbac.py` permission definitions:
```python
"MEDIA_STUDIO_GENERATE": "Can generate media (image, video, audio)",
"MEDIA_STUDIO_MANAGE": "Can manage gallery, assignments, and agent portraits",
```

Add both to the USER role's default permissions.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/module_registry.py platform_v2/rbac.py
git commit -m "feat(media-studio): update health check path + add RBAC permissions"
```

---

### Task 6c: Fix MEDIA_ROOT Path for Docker

**Files:**
- Modify: `platform_v2/tools/media_studio/services/gallery_service.py`
- Modify: `platform_v2/tools/media_studio/services/generation_service.py`

**Context:** Inside Docker, the app runs at `/app/`. The relative `MEDIA_ROOT` path computation may resolve incorrectly. Use an absolute path based on Flask's `app.static_folder` or a known base path.

- [ ] **Step 1: Update MEDIA_ROOT in both services**

Replace the relative path computation in both files with:
```python
import os

# Resolve from known platform_v2 location — works both local and Docker
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLATFORM_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
MEDIA_ROOT = os.path.join(_PLATFORM_DIR, "static", "media")
```

Verify this resolves to `/app/static/media` in Docker and `platform_v2/static/media` locally.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/services/gallery_service.py platform_v2/tools/media_studio/services/generation_service.py
git commit -m "fix(media-studio): use absolute MEDIA_ROOT path for Docker compatibility"
```

---

## Chunk 3: LCARS Frontend UI

### Task 7: Media Studio HTML Template

**Files:**
- Create: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Context:** LCARS aesthetic. Uses `lcars-panels.css` for cards, `lcars-frames.css` for structural layout, `station-ops.js/css` for CREATIVE station terminal. Theme variables from `theme.css`. Tab pattern: `.nav-tab[data-tab]` buttons + `.tab-panel` divs. Fonts: Antonio (nav), Orbitron (titles), IBM Plex Mono (code). CSS class prefix: `ms-` for Media Studio namespace.

**This is the largest task.** The HTML template includes the full 5-tab UI: Dashboard, Generate, Gallery, Queue, and a CREATIVE station terminal panel.

- [ ] **Step 1: Write media_studio.html**

Use the `frontend-design` skill for this step. The template must:

1. Extend the base layout (`{% extends "base.html" %}`)
2. Include LCARS frame structure with sidebar elbows and colored segments
3. 5-tab navigation: Dashboard, Generate, Gallery, Portraits (greyed, Layer 2), Queue
4. CREATIVE station StationOps terminal panel on the right side
5. Dashboard tab: recent grid (8 thumbnails), GPU fleet cards, stats counters
6. Generate tab: wizard flow — media type buttons, model dropdown, prompt textarea, negative prompt (collapsible), size presets, advanced controls (collapsible), submit button
7. Gallery tab: masonry grid with lazy thumbnails, filter bar, click-to-detail modal with metadata
8. Queue tab: job list with status badges (colored), auto-refresh 5s polling
9. Use `archie-time.js` for all timestamps (`data-utc` + `data-fmt` attributes)
10. Use `escHtml()` for user content in DOM
11. All text uses `data-i18n` attributes
12. CSS prefix: `ms-` (media studio namespace)
13. Color accent: `--archie-purple` (#8b5cf6) for CREATIVE station theme
14. Mobile-responsive (the user is often on mobile)

The JS should:
- `switchMsTab(tabId)` — tab switching
- `loadDashboard()` — fetch `/api/dashboard`, render stats + recent + fleet
- `loadGallery(page)` — fetch `/api/gallery`, render masonry grid
- `loadQueue()` — fetch `/api/queue`, render job list, auto-poll 5s
- `submitGeneration()` — collect form → POST `/api/generate`
- `showMediaDetail(id)` — fetch detail, show LCARS tablet modal
- `cancelJob(queueId)` — POST cancel
- `toggleFavorite(mediaId)` — POST toggle
- All API calls via `fetch()` with error handling

**NOTE:** This file will be large (~1500-2000 lines for a full LCARS module). Use the `frontend-design` skill to ensure the UI is polished, advanced, and production-grade. Reference existing modules like Bridge Command (`bridge.html`) and Consciousness (`consciousness_dashboard.html`) for pattern consistency.

- [ ] **Step 2: Verify template renders**

```bash
docker compose restart archie_platform
```

Navigate to http://192.168.1.200:3000/tools/media-studio and verify the page loads with all 5 tabs visible.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/templates/
git commit -m "feat(media-studio): LCARS UI — dashboard, generate, gallery, queue tabs"
```

---

### Task 8: Media Studio CSS

**Files:**
- Create: `platform_v2/tools/media_studio/static/css/media-studio.css`

**Context:** CSS prefix `ms-`. CREATIVE station accent: `--archie-purple` (#8b5cf6). Uses LCARS panel/frame classes as base. Custom styles for masonry gallery, generation wizard, queue status badges, GPU fleet cards. Mobile-first responsive.

- [ ] **Step 1: Write media-studio.css**

Key classes to implement:
- `.ms-dashboard-grid` — CSS Grid for stats cards (auto-fill, minmax 280px)
- `.ms-recent-grid` — 4-column grid for recent thumbnails (2-col on mobile)
- `.ms-gallery-grid` — Masonry-style via CSS columns (4 cols → 2 → 1 responsive)
- `.ms-gallery-item` — Image card with hover overlay showing prompt snippet
- `.ms-generate-form` — Wizard layout with sections
- `.ms-prompt-area` — Styled textarea with LCARS input treatment
- `.ms-model-select` — Styled dropdown
- `.ms-size-presets` — Button group for size options
- `.ms-advanced-toggle` — Collapsible section
- `.ms-queue-item` — Job row with status indicator
- `.ms-status-badge` — Colored badges: pending (orange), dispatched (cyan), generating (purple pulse), completed (green), failed (red), cancelled (grey)
- `.ms-gpu-card` — Fleet node card with VRAM bar and tier badge
- `.ms-tier-badge` — GPU tier label (high/mid/base/cpu)
- `.ms-media-modal` — Full-size media viewer modal (LCARS tablet design per `bm-` pattern)
- `.ms-detail-meta` — Metadata grid in detail modal

All colors via CSS variables (`var(--archie-purple)`, `var(--archie-green)`, etc.).

- [ ] **Step 2: Link CSS in template**

Add `<link>` in the template's `{% block extra_css %}`:
```html
<link rel="stylesheet" href="{{ url_for('media_studio.static', filename='css/media-studio.css') }}">
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): LCARS CSS — gallery grid, wizard, queue badges, GPU cards"
```

---

## Chunk 4: Integration + Deploy

### Task 9: Wire ComfyUI Generation End-to-End

**Files:**
- Modify: `platform_v2/tools/media_studio/services/generation_service.py`

**Context:** The current `submit_generation` dispatches to Bridge, but we also need a direct ComfyUI path for when Bridge dispatches back to Pixel agent on local ComfyUI. This task wires the actual image file retrieval from ComfyUI output directory after generation completes.

- [ ] **Step 1: Add direct ComfyUI generation function**

Add to `generation_service.py`:

```python
def generate_via_comfyui(queue_id: int) -> Optional[int]:
    """Direct ComfyUI generation — called when Bridge assigns to local Pixel.

    Builds workflow, submits to ComfyUI API, polls for completion,
    retrieves output file, calls on_generation_complete.
    """
    from ai_bridge.comfyui_service import get_comfyui_service
    from .comfyui_manager import build_txt2img_workflow

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_generation_queue WHERE id = %s", (queue_id,))
        queue_row = cur.fetchone()

    if not queue_row:
        return None

    params = queue_row["params"] or {}
    svc = get_comfyui_service()

    # Update status
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_generation_queue SET status = 'generating' WHERE id = %s",
            (queue_id,),
        )

    try:
        import time

        start = time.time()

        # Generate via ComfyUI service
        result = svc.generate_image(
            prompt=params.get("prompt", ""),
            model=params.get("model", "sd_xl_base_1.0.safetensors"),
            steps=params.get("steps", 25),
            width=params.get("width", 1024),
            height=params.get("height", 1024),
            cfg=params.get("cfg", 7.0),
            sampler=params.get("sampler", "euler_ancestral"),
            seed=params.get("seed", -1),
            negative_prompt=params.get("negative_prompt", ""),
        )

        duration_ms = int((time.time() - start) * 1000)

        if result.success and result.file_path:
            return on_generation_complete(
                queue_id=queue_id,
                file_path=result.file_path,
                seed=params.get("seed"),
                duration_ms=duration_ms,
                provider="comfyui",
            )
        else:
            on_generation_failed(queue_id, result.error or "Unknown ComfyUI error")
            return None

    except Exception as e:
        logger.error(f"ComfyUI generation failed for queue {queue_id}: {e}")
        on_generation_failed(queue_id, str(e))
        return None
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): direct ComfyUI generation path for local Pixel agent"
```

---

### Task 10: Integration Test + Deploy

**Files:** None (testing only)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify module loads**

Navigate to http://192.168.1.200:3000/tools/media-studio
Expected: LCARS UI renders with all tabs

- [ ] **Step 3: Test API endpoints**

```bash
# Dashboard
docker exec archie_platform curl -s http://localhost:3000/tools/media-studio/api/dashboard | python3 -m json.tool

# Models
docker exec archie_platform curl -s http://localhost:3000/tools/media-studio/api/models | python3 -m json.tool

# ComfyUI fleet status
docker exec archie_platform curl -s http://localhost:3000/tools/media-studio/api/comfyui/status | python3 -m json.tool

# Gallery (empty)
docker exec archie_platform curl -s http://localhost:3000/tools/media-studio/api/gallery | python3 -m json.tool
```

- [ ] **Step 4: Test image generation (if ComfyUI healthy)**

Submit a test generation via the UI:
- Prompt: "a starship bridge interior, LCARS panels, dramatic lighting"
- Model: sd_xl_base_1.0
- Size: 1024x1024
- Steps: 25

Verify: queue entry created, status updates, image appears in gallery on completion.

- [ ] **Step 5: Final commit + push**

```bash
git push origin main
```

- [ ] **Step 6: Update Dev HQ**

Use MCP tools:
```
mcp update_project_understanding — media studio layer 1 complete
mcp complete_task — with notes on what was built
mcp log_decision — "Rebuilt media_studio as services-backed LCARS module with GPU-tiered fleet dispatch"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | DB Migration 149 | `database/migrations/149_media_studio_tables.sql` |
| 2 | ComfyUI Manager | `services/comfyui_manager.py` |
| 3 | Gallery Service | `services/gallery_service.py` |
| 4 | Generation Service | `services/generation_service.py` |
| 5 | Blueprint + Routes (full rewrite) | `__init__.py`, `routes.py` |
| 6 | Media Directories | `static/media/`, `.gitignore` |
| 6b | Health Check + RBAC | `module_registry.py`, `rbac.py` |
| 6c | Fix MEDIA_ROOT Docker Path | `gallery_service.py`, `generation_service.py` |
| 7 | LCARS HTML Template | `templates/.../media_studio.html` |
| 8 | Media Studio CSS | `static/css/media-studio.css` |
| 9 | ComfyUI E2E Wire | `services/generation_service.py` |
| 10 | Integration Test | Deploy + verify |

**Skills to invoke during execution:**
- `frontend-design` — Task 7 (HTML template) and Task 8 (CSS)
- `ui-ux-pro-max` — Task 7 for advanced LCARS design patterns
- `superpowers:subagent-driven-development` — parallel task execution
