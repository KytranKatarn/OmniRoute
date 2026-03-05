"""
OllamaDiffuser Service — Local Image Generation

Generates images using FLUX/Stable Diffusion models via a local OllamaDiffuser instance.
Runs on the same host as Ollama but as a separate service (port 11435).

GPU/CPU logic:
- Queries nvidia-smi for free VRAM
- >=4GB free → GPU (fast, ~10-30s)
- <4GB free → CPU (slow, ~2-5 min, uses system RAM)
- dolphin3-8k typically occupies ~7.4GB of 8GB VRAM, so CPU is the default path

Usage:
    from ai_bridge.diffuser_service import get_diffuser_service

    service = get_diffuser_service()
    result = service.generate_image("a cat in space", model="flux.1-schnell")
"""

import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict

import requests

logger = logging.getLogger(__name__)

# Configuration
_diffuser_host = os.getenv("OLLAMA_DIFFUSER_HOST", "http://host.docker.internal:11435")
if not _diffuser_host.startswith("http"):
    _diffuser_host = f"http://{_diffuser_host}"
DIFFUSER_HOST = _diffuser_host
DIFFUSER_MODEL = os.getenv("OLLAMA_DIFFUSER_MODEL", "flux.1-schnell")
REQUEST_TIMEOUT = 300  # 5 min — CPU generation is slow
GPU_VRAM_THRESHOLD_GB = 4.0  # Minimum free VRAM to use GPU


@dataclass
class DiffuserResult:
    """Result of an image generation operation."""
    success: bool
    file_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


class DiffuserService:
    """Service for generating images via local OllamaDiffuser."""

    AVAILABLE_MODELS = [
        {"name": "flux.1-schnell", "vram_gb": 4.0, "description": "FLUX Schnell — fast, high quality"},
        {"name": "stable-diffusion-3.5", "vram_gb": 3.5, "description": "Stable Diffusion 3.5"},
    ]

    def __init__(self, host: str = DIFFUSER_HOST, model: str = DIFFUSER_MODEL):
        self.host = host.rstrip("/")
        self.model = model
        self._healthy: Optional[bool] = None

    def health_check(self) -> bool:
        """Check if OllamaDiffuser service is reachable."""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=3)
            self._healthy = resp.status_code == 200
        except Exception:
            self._healthy = False
        return self._healthy

    @property
    def is_healthy(self) -> bool:
        if self._healthy is None:
            self.health_check()
        return self._healthy

    def get_models(self) -> list:
        """Get list of models available on the OllamaDiffuser instance."""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code == 200:
                return resp.json().get("models", [])
        except Exception as e:
            logger.debug(f"[DiffuserService] Failed to list models: {e}")
        return []

    def get_gpu_status(self) -> Dict:
        """Query nvidia-smi for current VRAM availability.

        Returns:
            {available: bool, vram_free_gb: float, vram_total_gb: float, occupied_by: str|None}
        """
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = [p.strip() for p in result.stdout.strip().split(",")]
                if len(parts) >= 3:
                    vram_total = round(float(parts[0]) / 1024, 1)
                    vram_used = round(float(parts[1]) / 1024, 1)
                    vram_free = round(float(parts[2]) / 1024, 1)

                    # Check what Ollama model holds the GPU
                    occupied_by = None
                    try:
                        ollama_host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
                        if not ollama_host.startswith("http"):
                            ollama_host = f"http://{ollama_host}"
                        ps_resp = requests.get(f"{ollama_host}/api/ps", timeout=3)
                        if ps_resp.status_code == 200:
                            for m in ps_resp.json().get("models", []):
                                if m.get("size_vram", 0) > 0:
                                    occupied_by = m.get("name", "").replace(":latest", "")
                                    break
                    except Exception:
                        pass

                    return {
                        "available": True,
                        "vram_free_gb": vram_free,
                        "vram_total_gb": vram_total,
                        "vram_used_gb": vram_used,
                        "can_use_gpu": vram_free >= GPU_VRAM_THRESHOLD_GB,
                        "occupied_by": occupied_by,
                    }
        except Exception as e:
            logger.debug(f"[DiffuserService] nvidia-smi failed: {e}")

        return {"available": False, "vram_free_gb": 0, "vram_total_gb": 0,
                "can_use_gpu": False, "occupied_by": None}

    def generate_image(
        self,
        prompt: str,
        model: str = None,
        steps: int = 4,
        width: int = 1024,
        height: int = 1024,
        force_cpu: bool = False,
    ) -> DiffuserResult:
        """Generate an image via OllamaDiffuser.

        Args:
            prompt: Text description of the image to generate
            model: Model name (default: flux.1-schnell)
            steps: Number of inference steps
            width: Output width in pixels
            height: Output height in pixels
            force_cpu: Force CPU generation even if GPU is available

        Returns:
            DiffuserResult with file_path and metadata
        """
        model = model or self.model

        # Determine hardware
        gpu_status = self.get_gpu_status()
        use_gpu = gpu_status["can_use_gpu"] and not force_cpu
        hardware = "gpu" if use_gpu else "cpu"

        logger.info(
            f"[DiffuserService] Generating image: model={model}, hw={hardware}, "
            f"steps={steps}, {width}x{height}"
        )

        payload = {
            "model": model,
            "prompt": prompt,
            "parameters": {
                "steps": steps,
                "width": width,
                "height": height,
                "num_gpu": 1 if use_gpu else 0,
            },
        }

        try:
            start = time.time()
            resp = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            duration_ms = int((time.time() - start) * 1000)

            if resp.status_code != 200:
                return DiffuserResult(
                    success=False,
                    error=f"OllamaDiffuser error {resp.status_code}: {resp.text[:500]}"
                )

            # Save image to disk
            img_bytes = resp.content
            content_type = resp.headers.get("Content-Type", "")

            # If response is JSON with base64 image
            if "application/json" in content_type:
                import base64
                data = resp.json()
                img_b64 = data.get("image", "") or data.get("images", [""])[0]
                if not img_b64:
                    return DiffuserResult(success=False, error="Empty image data in response")
                img_bytes = base64.b64decode(img_b64)

            date_str = datetime.now().strftime("%Y-%m-%d")
            file_uuid = str(uuid.uuid4())[:12]
            rel_dir = f"static/media/images/{date_str}"
            abs_dir = os.path.join("/mnt/archie_brain/platform_v2", rel_dir)
            os.makedirs(abs_dir, exist_ok=True)

            file_name = f"{file_uuid}.png"
            file_path = os.path.join(abs_dir, file_name)
            with open(file_path, "wb") as f:
                f.write(img_bytes)

            return DiffuserResult(
                success=True,
                file_path=f"/{rel_dir}/{file_name}",
                metadata={
                    "provider": "ollama_diffuser",
                    "model": model,
                    "cost_usd": 0.0,
                    "hardware": hardware,
                    "mime_type": "image/png",
                    "file_size_bytes": len(img_bytes),
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "duration_ms": duration_ms,
                    "gpu_status": {
                        "vram_free_gb": gpu_status.get("vram_free_gb", 0),
                        "occupied_by": gpu_status.get("occupied_by"),
                    },
                },
            )

        except requests.ConnectionError:
            return DiffuserResult(
                success=False,
                error="OllamaDiffuser service unavailable — is the container running?"
            )
        except requests.Timeout:
            return DiffuserResult(
                success=False,
                error=f"Generation timed out after {REQUEST_TIMEOUT}s"
            )
        except Exception as e:
            logger.error(f"[DiffuserService] Generation failed: {e}")
            return DiffuserResult(success=False, error=str(e))

    def get_status(self) -> Dict:
        """Get service status summary for UI display."""
        healthy = self.health_check()
        gpu = self.get_gpu_status()
        models = self.get_models() if healthy else []

        return {
            "service_online": healthy,
            "host": self.host,
            "default_model": self.model,
            "available_models": [m.get("name", "") for m in models],
            "gpu": gpu,
            "cpu_fallback": True,  # Always available with 128GB RAM
        }


# Singleton
_service: Optional[DiffuserService] = None


def get_diffuser_service() -> DiffuserService:
    """Get or create the singleton DiffuserService instance."""
    global _service
    if _service is None:
        _service = DiffuserService()
    return _service
