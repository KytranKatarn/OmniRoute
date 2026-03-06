"""
OllamaDiffuser Service — Local Image Generation

Generates images using Stable Diffusion models via a local OllamaDiffuser instance.
Runs as a separate Docker container (port 11435), CPU-only (Quadro M4000 is compute 5.2,
too old for current PyTorch CUDA).

Usage:
    from ai_bridge.diffuser_service import get_diffuser_service

    service = get_diffuser_service()
    result = service.generate_image("a cat in space", model="stable-diffusion-1.5")
"""

import logging
import os
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
DIFFUSER_MODEL = os.getenv("OLLAMA_DIFFUSER_MODEL", "stable-diffusion-1.5")
REQUEST_TIMEOUT = 600  # 10 min — CPU generation is slow


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
        {"name": "stable-diffusion-1.5", "description": "SD 1.5 — fast, versatile, unrestricted", "default_steps": 20},
        {"name": "realvisxl-v4", "description": "RealVisXL v4 — photorealistic SDXL, unrestricted", "default_steps": 25},
    ]

    def __init__(self, host: str = DIFFUSER_HOST, model: str = DIFFUSER_MODEL):
        self.host = host.rstrip("/")
        self.model = model
        self._healthy: Optional[bool] = None
        self._loaded_model: Optional[str] = None

    def health_check(self) -> bool:
        """Check if OllamaDiffuser service is reachable."""
        try:
            resp = requests.get(f"{self.host}/api/health", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                self._healthy = data.get("status") == "healthy"
                self._loaded_model = data.get("current_model")
            else:
                self._healthy = False
        except Exception:
            self._healthy = False
        return self._healthy

    @property
    def is_healthy(self) -> bool:
        if self._healthy is None:
            self.health_check()
        return self._healthy

    def get_models(self) -> Dict:
        """Get list of models from OllamaDiffuser."""
        try:
            resp = requests.get(f"{self.host}/api/models", timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"[DiffuserService] Failed to list models: {e}")
        return {"available": [], "installed": [], "current": None}

    def load_model(self, model_name: str) -> bool:
        """Load a model into OllamaDiffuser memory."""
        try:
            resp = requests.post(
                f"{self.host}/api/models/load",
                json={"model_name": model_name},
                timeout=120,
            )
            if resp.status_code == 200:
                self._loaded_model = model_name
                logger.info(f"[DiffuserService] Model {model_name} loaded")
                return True
            else:
                logger.warning(f"[DiffuserService] Load failed: {resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"[DiffuserService] Load error: {e}")
            return False

    def _ensure_model_loaded(self, model: str) -> bool:
        """Ensure the requested model is loaded, loading it if needed."""
        # Check current state
        self.health_check()
        if self._loaded_model == model:
            return True
        return self.load_model(model)

    def generate_image(
        self,
        prompt: str,
        model: str = None,
        steps: int = None,
        width: int = 512,
        height: int = 512,
        negative_prompt: str = "low quality, bad anatomy, worst quality, low resolution",
        seed: int = None,
    ) -> DiffuserResult:
        """Generate an image via OllamaDiffuser.

        Args:
            prompt: Text description of the image to generate
            model: Model name (default: stable-diffusion-1.5)
            steps: Number of inference steps (default depends on model)
            width: Output width in pixels
            height: Output height in pixels
            negative_prompt: What to avoid in generation
            seed: Random seed for reproducibility

        Returns:
            DiffuserResult with file_path and metadata
        """
        model = model or self.model

        # Default steps per model
        if steps is None:
            model_info = next((m for m in self.AVAILABLE_MODELS if m["name"] == model), None)
            steps = model_info["default_steps"] if model_info else 20

        # Ensure model is loaded
        if not self._ensure_model_loaded(model):
            return DiffuserResult(
                success=False,
                error=f"Failed to load model {model}"
            )

        logger.info(
            f"[DiffuserService] Generating image: model={model}, "
            f"steps={steps}, {width}x{height}, CPU"
        )

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "steps": steps,
            "width": width,
            "height": height,
            "response_format": "b64_json",
        }
        if seed is not None:
            payload["seed"] = seed

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

            data = resp.json()
            if data.get("status") == "error":
                return DiffuserResult(success=False, error=data.get("error", "Unknown error"))

            # Extract base64 image
            import base64
            img_b64 = data.get("image", "") or data.get("images", [""])[0]
            if not img_b64:
                return DiffuserResult(success=False, error="Empty image data in response")
            img_bytes = base64.b64decode(img_b64)

            # Save to disk
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
                    "hardware": "cpu",
                    "mime_type": "image/png",
                    "file_size_bytes": len(img_bytes),
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "duration_ms": duration_ms,
                    "seed": data.get("seed"),
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
        models = self.get_models() if healthy else {}

        return {
            "service_online": healthy,
            "host": self.host,
            "default_model": self.model,
            "loaded_model": self._loaded_model,
            "installed_models": models.get("installed", []),
            "available_models": models.get("available", []),
            "hardware": "cpu",
        }


# Singleton
_service: Optional[DiffuserService] = None


def get_diffuser_service() -> DiffuserService:
    """Get or create the singleton DiffuserService instance."""
    global _service
    if _service is None:
        _service = DiffuserService()
    return _service
