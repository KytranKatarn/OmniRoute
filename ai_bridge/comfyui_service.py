"""
ComfyUI Service — Advanced Local Image Generation

Interfaces with ComfyUI's queue-based REST API for image generation.
Supports custom workflows, LoRAs, ControlNet, and unrestricted generation.

ComfyUI API flow:
    1. POST /prompt — submit a workflow, get a prompt_id
    2. GET /history/{prompt_id} — poll until complete
    3. GET /view?filename=... — download the output image

Usage:
    from ai_bridge.comfyui_service import get_comfyui_service

    service = get_comfyui_service()
    result = service.generate_image("a cat in space", model="v1-5-pruned-emaonly.safetensors")
"""

import copy
import json
import logging
import os
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

import requests

logger = logging.getLogger(__name__)

# Configuration
_comfyui_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
if not _comfyui_host.startswith("http"):
    _comfyui_host = f"http://{_comfyui_host}"
COMFYUI_HOST = _comfyui_host
REQUEST_TIMEOUT = int(os.getenv("COMFYUI_TIMEOUT", "1800"))  # 30 min default — M4000 SDXL needs ~10-15 min
POLL_INTERVAL = 3  # seconds between status polls

# Default workflow path
_default_workflow = os.path.join(os.path.dirname(__file__), "..", "comfyui", "workflows", "txt2img_default.json")


@dataclass
class ComfyUIResult:
    """Result of a ComfyUI image generation operation."""

    success: bool
    file_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


class ComfyUIService:
    """Service for generating images via local ComfyUI instance.

    Supports fleet routing: pass target_host to generate_image() or use
    target_host="auto" to auto-select the best GPU node by free VRAM.
    """

    def __init__(self, host: str = COMFYUI_HOST):
        self.host = host.rstrip("/")
        self._healthy: Optional[bool] = None
        self._models: Optional[List[str]] = None

    def select_best_comfyui_node(self) -> Optional[str]:
        """Find the best ComfyUI node by free VRAM.

        Queries remote_nodes for nodes with comfyui_available=true and fresh
        heartbeat, probes each for /system_stats, returns the one with most
        free VRAM. Returns None if no nodes available (falls back to hub).
        """
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT hostname, comfyui_port, gpu_vram_gb
                       FROM remote_nodes
                       WHERE is_active = true
                         AND comfyui_available = true
                         AND deployment_mode != 'starbase'
                         AND last_heartbeat > NOW() - INTERVAL '30 seconds'
                       ORDER BY gpu_vram_gb DESC NULLS LAST"""
                )
                candidates = cur.fetchall()

            best_host = None
            best_vram_free = 0

            for node in candidates:
                port = node["comfyui_port"] or 8188
                url = f"http://{node['hostname']}:{port}"
                try:
                    resp = requests.get(f"{url}/system_stats", timeout=3)
                    if resp.status_code == 200:
                        devices = resp.json().get("devices", [])
                        for dev in devices:
                            vram_free = dev.get("vram_free", 0) / 1e9
                            if vram_free > best_vram_free:
                                best_vram_free = vram_free
                                best_host = url
                except Exception:
                    continue

            if best_host:
                logger.info(
                    "[ComfyUI] Auto-selected node %s (%.1fGB VRAM free)",
                    best_host,
                    best_vram_free,
                )
            return best_host

        except Exception as e:
            logger.warning("[ComfyUI] Node selection failed: %s", e)
            return None

    def health_check(self) -> bool:
        """Check if ComfyUI is reachable."""
        try:
            resp = requests.get(f"{self.host}/system_stats", timeout=5)
            if resp.status_code == 200:
                self._healthy = True
                return True
        except Exception:
            pass
        self._healthy = False
        return False

    @property
    def is_healthy(self) -> bool:
        if self._healthy is None:
            self.health_check()
        return self._healthy

    # Container lifecycle constants
    COMFYUI_CONTAINER_NAME = os.getenv("COMFYUI_CONTAINER_NAME", "archie_comfyui")
    COMFYUI_WAKE_TIMEOUT = 90  # seconds to wait for health after start

    def is_stopped(self) -> bool:
        """Return True if ComfyUI container is not running (port unreachable).
        Distinguishes stopped from busy: a busy ComfyUI responds slowly but
        responds; a stopped one raises ConnectionRefusedError immediately."""
        try:
            if "://" in self.host:
                url = self.host.split("://", 1)[1]
            else:
                url = self.host
            host, _, port_str = url.rpartition(":")
            port = int(port_str) if port_str else 8188
            host = host or "archie_comfyui"
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            return False  # port open → container running
        except ConnectionRefusedError:
            return True  # port actively refused — container definitely stopped
        except (socket.timeout, OSError):
            return True  # could be transient network blip; caller will attempt docker start (no-op if running)

    def _container_state(self) -> str:
        """Return the docker container state string (running/exited/etc), or 'unknown'."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", self.COMFYUI_CONTAINER_NAME],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    def wake_if_stopped(self) -> bool:
        """Start the ComfyUI container if stopped, wait up to 90s for health.
        Returns True if ComfyUI is healthy after the call, False otherwise.

        Handles two cases:
        - Container exited/absent → docker start
        - Container running but port dead (internal crash) → docker restart

        WARNING: Blocks the calling thread for up to COMFYUI_WAKE_TIMEOUT seconds.
        Do NOT call from a synchronous web request handler — use wake_if_stopped_async().
        """
        if not self.is_stopped():
            return self.is_healthy

        # Distinguish: container exited vs running-but-crashed (port unresponsive)
        state = self._container_state()
        if state == "running":
            # Port is dead but container thinks it's running — force restart
            logger.info("[ComfyUI] Container running but unresponsive — restarting %s", self.COMFYUI_CONTAINER_NAME)
            try:
                subprocess.run(
                    ["docker", "restart", self.COMFYUI_CONTAINER_NAME],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.warning("[ComfyUI] docker restart unavailable: %s", e)
                return False
        else:
            logger.info("[ComfyUI] Container %s (%s) — starting", self.COMFYUI_CONTAINER_NAME, state)
            try:
                result = subprocess.run(
                    ["docker", "start", self.COMFYUI_CONTAINER_NAME],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode != 0:
                    logger.warning("[ComfyUI] docker start failed: %s", result.stderr.strip())
                    return False
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.warning("[ComfyUI] docker start unavailable: %s", e)
                return False

        # STAMP THE IDLE CLOCK — both branches above have just started or restarted
        # the container on demand, and STARTING IT IS USE (#5277).
        #
        # ⚠️ THERE ARE TWO ComfyUI LIFECYCLE MODULES AND THEY SHARE ONE CLOCK:
        #   * THIS module (ai_bridge/comfyui_service.py) WAKES the container — the
        #     "[ComfyUI] ..." log lines.
        #   * services/comfyui_lifecycle.py REAPS it on idle — the
        #     "ComfyUI idle for <n>s > 1800s — stopping" line — reading the SAME
        #     `system_config['comfyui_last_used_at']`.
        # The waker never wrote that key, so the reaper kept reading a timestamp
        # from 2026-06-22 and stopping the container ~28s after this function
        # started it, forever, ~2min period. Each cycle fired the ComfyUI VRAM
        # swap and evicted the Ollama GPU models to CPU for an SDXL load that
        # never arrived.
        #
        # PR #2501 stamped the equivalent path in comfyui_lifecycle.ensure_running()
        # — which is CORRECT but UNREACHABLE from here: the production wake path is
        # this function, and it does not call ensure_running(). Deployed and
        # measured: the clock stayed stale and the livelock continued. Fixing the
        # reaper's module did not fix the waker.
        #
        # Stamped BEFORE the health wait deliberately: ComfyUI is currently
        # unhealthy and never answers, so a stamp that only happened on success
        # would never happen at all.
        try:
            from services.comfyui_lifecycle import record_last_used  # noqa: PLC0415

            record_last_used()
        except Exception as e:  # never let bookkeeping break the wake
            logger.warning("[ComfyUI] could not stamp last_used: %s", e)

        logger.info("[ComfyUI] Waiting up to %ds for health", self.COMFYUI_WAKE_TIMEOUT)
        deadline = time.time() + self.COMFYUI_WAKE_TIMEOUT
        while time.time() < deadline:
            try:
                if self.is_healthy:
                    logger.info("[ComfyUI] Health confirmed after wake")
                    return True
            except Exception as e:
                logger.debug("[ComfyUI] Health probe error during wake: %s", e)
            time.sleep(5)

        logger.warning("[ComfyUI] Timed out waiting for health after wake")
        return False

    def stop_if_idle(self) -> bool:
        """Stop the ComfyUI container when P.I.X.E.L. has no pending work.

        Called by media_generation_worker after draining the queue to free
        VRAM for Ollama text models. No-op if ComfyUI is already stopped or
        still has jobs running/queued.

        Returns True if stopped (or already stopped), False if busy or failed.
        """
        if self.is_stopped():
            return True  # already idle

        queue = self.get_queue_status()
        if queue.get("running") or queue.get("pending"):
            logger.info("[ComfyUI] Skipping idle-stop — queue not empty: %s", queue)
            return False

        logger.info("[ComfyUI] Queue empty — stopping container for VRAM reclaim")
        try:
            result = subprocess.run(
                ["docker", "stop", self.COMFYUI_CONTAINER_NAME],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logger.info("[ComfyUI] Container stopped (P.I.X.E.L. idle)")
                return True
            logger.warning("[ComfyUI] docker stop failed: %s", result.stderr.strip())
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("[ComfyUI] docker stop unavailable: %s", e)
            return False

    def wake_if_stopped_async(self) -> None:
        """Fire wake_if_stopped() in a daemon thread and return immediately.

        Use this from web request handlers or dispatch paths where blocking 90s
        is unacceptable. The caller should return a "waking" status and let the
        next request retry once ComfyUI is healthy.
        """
        if not self.is_stopped():
            return  # already running — nothing to do
        import threading

        t = threading.Thread(target=self.wake_if_stopped, daemon=True)
        t.start()
        logger.info("[ComfyUI] Wake task started in background thread")

    def get_models(self) -> Dict:
        """Get available checkpoint models from ComfyUI."""
        try:
            resp = requests.get(f"{self.host}/object_info/CheckpointLoaderSimple", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                ckpts = (
                    data.get("CheckpointLoaderSimple", {})
                    .get("input", {})
                    .get("required", {})
                    .get("ckpt_name", [[]])[0]
                )
                self._models = ckpts if isinstance(ckpts, list) else []
                return {
                    "installed": self._models,
                    "available": [],
                    "current": self._models[0] if self._models else None,
                }
        except Exception as e:
            logger.debug(f"[ComfyUI] Failed to list models: {e}")
        return {"installed": [], "available": [], "current": None}

    def get_system_stats(self) -> Dict:
        """Get ComfyUI system stats (RAM, device info)."""
        try:
            resp = requests.get(f"{self.host}/system_stats", timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def get_queue_status(self) -> Dict:
        """Get current queue length."""
        try:
            resp = requests.get(f"{self.host}/queue", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "running": len(data.get("queue_running", [])),
                    "pending": len(data.get("queue_pending", [])),
                }
        except Exception:
            pass
        return {"running": 0, "pending": 0}

    def _load_workflow(self, workflow_path: str = None) -> Dict:
        """Load a workflow JSON file."""
        path = workflow_path or _default_workflow
        try:
            with open(path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            # Fallback: return a minimal inline workflow
            return self._minimal_workflow()

    def _minimal_workflow(self) -> Dict:
        """Minimal txt2img workflow as fallback."""
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": 7,
                    "denoise": 1,
                    "latent_image": ["5", 0],
                    "model": ["4", 0],
                    "negative": ["7", 0],
                    "positive": ["6", 0],
                    "sampler_name": "euler_ancestral",
                    "scheduler": "normal",
                    "seed": 42,
                    "steps": 20,
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {"batch_size": 1, "height": 512, "width": 512},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["4", 1], "text": "a beautiful sunset"},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["4", 1], "text": "low quality, bad anatomy"},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "archie", "images": ["8", 0]},
            },
        }

    def warmup(self, model: str = None) -> bool:
        """Pre-load a checkpoint into VRAM with a minimal 1-step, 64x64 generation.

        Returns True if warmup succeeded.
        """
        if not self.health_check():
            logger.warning("[ComfyUI] Warmup skipped — not reachable")
            return False

        if not model:
            # Use Pixel's default checkpoint
            model = "sd_xl_base_1.0.safetensors"

        logger.info(f"[ComfyUI] Warming up checkpoint: {model}")
        try:
            result = self.generate_image(
                prompt="warmup",
                model=model,
                steps=1,
                width=64,
                height=64,
                cfg=1.0,
            )
            if result.success:
                logger.info(f"[ComfyUI] Warmup complete: {model} loaded into VRAM")
                # Clean up the tiny warmup image
                if result.file_path:
                    try:
                        Path(result.file_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                return True
            else:
                logger.warning(f"[ComfyUI] Warmup failed: {result.error}")
                return False
        except Exception as e:
            logger.warning(f"[ComfyUI] Warmup error: {e}")
            return False

    def generate_image(
        self,
        prompt: str,
        model: str = None,
        steps: int = 20,
        width: int = 512,
        height: int = 512,
        negative_prompt: str = "low quality, bad anatomy, worst quality, low resolution",
        seed: int = None,
        workflow_path: str = None,
        cfg: float = 7.0,
        sampler: str = "euler_ancestral",
        target_host: str = None,
    ) -> ComfyUIResult:
        """Generate an image via ComfyUI.

        Args:
            prompt: Text description of the image
            model: Checkpoint filename (e.g., "v1-5-pruned-emaonly.safetensors")
            steps: Inference steps
            width/height: Output dimensions
            negative_prompt: What to avoid
            seed: Random seed (-1 or None for random)
            workflow_path: Custom workflow JSON path
            cfg: Classifier-free guidance scale
            sampler: Sampler name (euler_ancestral, dpmpp_2m, etc.)
            target_host: ComfyUI host URL override. Use "auto" to auto-select
                best GPU node by VRAM. None = use default hub.

        Returns:
            ComfyUIResult with file_path and metadata
        """
        # Fleet routing: resolve target host
        original_host = self.host
        if target_host == "auto":
            node_host = self.select_best_comfyui_node()
            if node_host:
                self.host = node_host
        elif target_host:
            self.host = target_host.rstrip("/")

        try:
            return self._do_generate(
                prompt,
                model,
                steps,
                width,
                height,
                negative_prompt,
                seed,
                workflow_path,
                cfg,
                sampler,
            )
        finally:
            self.host = original_host

    def _do_generate(
        self,
        prompt: str,
        model: str,
        steps: int,
        width: int,
        height: int,
        negative_prompt: str,
        seed: int,
        workflow_path: str,
        cfg: float,
        sampler: str,
    ) -> ComfyUIResult:
        """Internal generation — uses self.host (may be overridden by caller)."""
        # Load and customize workflow
        workflow = copy.deepcopy(self._load_workflow(workflow_path))

        # Set model
        if model:
            for node in workflow.values():
                if node.get("class_type") == "CheckpointLoaderSimple":
                    node["inputs"]["ckpt_name"] = model

        # Set prompt
        for node in workflow.values():
            if node.get("class_type") == "CLIPTextEncode":
                if node["inputs"].get("text") and "low quality" not in node["inputs"]["text"]:
                    node["inputs"]["text"] = prompt
                elif "low quality" in node["inputs"].get("text", ""):
                    node["inputs"]["text"] = negative_prompt

        # Set dimensions
        for node in workflow.values():
            if node.get("class_type") == "EmptyLatentImage":
                node["inputs"]["width"] = width
                node["inputs"]["height"] = height

        # Set sampler params
        for node in workflow.values():
            if node.get("class_type") == "KSampler":
                node["inputs"]["steps"] = steps
                node["inputs"]["cfg"] = cfg
                node["inputs"]["sampler_name"] = sampler
                if seed is not None and seed >= 0:
                    node["inputs"]["seed"] = seed
                else:
                    node["inputs"]["seed"] = int(time.time()) % (2**32)

        # Set unique filename prefix
        file_prefix = f"archie_{uuid.uuid4().hex[:8]}"
        for node in workflow.values():
            if node.get("class_type") == "SaveImage":
                node["inputs"]["filename_prefix"] = file_prefix

        # Submit to queue
        client_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": client_id}

        logger.info(
            "[ComfyUI] Generating: model=%s, steps=%d, %dx%d",
            model or "default",
            steps,
            width,
            height,
        )

        try:
            start = time.time()
            resp = requests.post(
                f"{self.host}/prompt",
                json=payload,
                timeout=30,
            )

            if resp.status_code != 200:
                return ComfyUIResult(
                    success=False,
                    error=f"ComfyUI queue error {resp.status_code}: {resp.text[:500]}",
                )

            prompt_id = resp.json().get("prompt_id")
            if not prompt_id:
                return ComfyUIResult(success=False, error="No prompt_id returned")

            # Poll for completion
            result = self._poll_completion(prompt_id, timeout=REQUEST_TIMEOUT)
            duration_ms = int((time.time() - start) * 1000)

            if not result["success"]:
                return ComfyUIResult(success=False, error=result.get("error", "Unknown"))

            # Download the output image
            output_images = result.get("images", [])
            if not output_images:
                return ComfyUIResult(success=False, error="No output images")

            img_info = output_images[0]
            img_data = self._download_image(
                img_info["filename"],
                img_info.get("subfolder", ""),
                img_info.get("type", "output"),
            )

            if not img_data:
                return ComfyUIResult(success=False, error="Failed to download output image")

            # Save to platform media directory
            date_str = datetime.now().strftime("%Y-%m-%d")
            file_uuid = str(uuid.uuid4())[:12]
            rel_dir = f"static/media/images/{date_str}"
            app_root = os.environ.get("FLASK_APP_ROOT", "/app")
            abs_dir = os.path.join(app_root, rel_dir)
            os.makedirs(abs_dir, exist_ok=True)

            file_name = f"{file_uuid}.png"
            file_path = os.path.join(abs_dir, file_name)
            with open(file_path, "wb") as f:
                f.write(img_data)

            return ComfyUIResult(
                success=True,
                file_path=f"/{rel_dir}/{file_name}",
                metadata={
                    "provider": "comfyui",
                    "model": model or "default",
                    "cost_usd": 0.0,
                    "hardware": "gpu" if self.host != COMFYUI_HOST else "cpu",
                    "comfyui_host": self.host,
                    "mime_type": "image/png",
                    "file_size_bytes": len(img_data),
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler": sampler,
                    "duration_ms": duration_ms,
                    "seed": seed,
                },
            )

        except requests.ConnectionError:
            return ComfyUIResult(
                success=False,
                error="ComfyUI service unavailable — is the container running?",
            )
        except requests.Timeout:
            return ComfyUIResult(
                success=False,
                error=f"Generation timed out after {REQUEST_TIMEOUT}s",
            )
        except Exception as e:
            logger.error(f"[ComfyUI] Generation failed: {e}")
            return ComfyUIResult(success=False, error=str(e))

    def _poll_completion(self, prompt_id: str, timeout: int = 600) -> Dict:
        """Poll ComfyUI history until the prompt completes."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                resp = requests.get(f"{self.host}/history/{prompt_id}", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if prompt_id in data:
                        entry = data[prompt_id]
                        status = entry.get("status", {})

                        if status.get("completed", False):
                            # Extract output images
                            images = []
                            outputs = entry.get("outputs", {})
                            for node_id, node_out in outputs.items():
                                for img in node_out.get("images", []):
                                    images.append(img)
                            return {"success": True, "images": images}

                        if status.get("status_str") == "error":
                            msgs = status.get("messages", [])
                            err = str(msgs) if msgs else "Workflow execution error"
                            return {"success": False, "error": err}

            except Exception as e:
                logger.debug("[ComfyUI] Poll error: %s", e)

            time.sleep(POLL_INTERVAL)

        return {"success": False, "error": f"Timed out after {timeout}s"}

    def _download_image(self, filename: str, subfolder: str = "", img_type: str = "output") -> Optional[bytes]:
        """Download an output image from ComfyUI."""
        try:
            params = {
                "filename": filename,
                "subfolder": subfolder,
                "type": img_type,
            }
            resp = requests.get(f"{self.host}/view", params=params, timeout=30)
            if resp.status_code == 200:
                return resp.content
        except Exception as e:
            logger.error("[ComfyUI] Image download failed: %s", e)
        return None

    def get_status(self) -> Dict:
        """Get service status for UI display."""
        healthy = self.health_check()
        models = self.get_models() if healthy else {}
        queue = self.get_queue_status() if healthy else {}
        stats = self.get_system_stats() if healthy else {}

        return {
            "service_online": healthy,
            "host": self.host,
            "installed_models": models.get("installed", []),
            "queue_running": queue.get("running", 0),
            "queue_pending": queue.get("pending", 0),
            "system_stats": stats,
            "hardware": "cpu",
        }


# Singleton
_service: Optional[ComfyUIService] = None


def get_comfyui_service() -> ComfyUIService:
    """Get or create the singleton ComfyUIService instance."""
    global _service
    if _service is None:
        _service = ComfyUIService()
    return _service
