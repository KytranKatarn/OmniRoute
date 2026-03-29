"""
Video Generation Providers — Media Studio
==========================================
Cloud API adapters for video generation: Google Veo, Replicate, HuggingFace, LTX Studio.
Each provider implements submit/poll/download for async video generation.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class VideoProvider:
    """Base class for video generation providers."""

    name = "base"
    display_name = "Base Provider"
    is_free = False
    models = []

    def __init__(self):
        self.api_key = None

    @property
    def is_configured(self):
        return bool(self.api_key)

    def get_status(self):
        return {
            "name": self.name,
            "display_name": self.display_name,
            "configured": self.is_configured,
            "is_free": self.is_free,
            "models": self.models,
        }

    def submit(self, prompt, params=None):
        raise NotImplementedError

    def poll(self, job_id):
        raise NotImplementedError

    def download(self, url):
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.error(f"[{self.name}] Download failed: {e}")
            return None


# ---------------------------------------------------------------------------
# Google Veo 3.1 (free via aistudio.google.com)
# ---------------------------------------------------------------------------


class GoogleVeoProvider(VideoProvider):
    name = "google_veo"
    display_name = "Google Veo 3.1"
    is_free = True
    models = [
        {"id": "veo-3.1-generate-preview", "name": "Veo 3.1", "quality": "4K, 8sec, audio"},
    ]

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("GOOGLE_AI_API_KEY", "")

    def submit(self, prompt, params=None):
        params = params or {}
        model = params.get("model", "veo-3.1-generate-preview")
        try:
            resp = requests.post(
                f"{self.BASE_URL}/models/{model}:generateVideos",
                headers={"x-goog-api-key": self.api_key},
                json={
                    "instances": [{"prompt": prompt}],
                    "parameters": {
                        "aspectRatio": params.get("aspect_ratio", "16:9"),
                        "personGeneration": "allow_all",
                        "durationSeconds": params.get("duration", 8),
                    },
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            operation_name = data.get("name", "")
            return {
                "job_id": operation_name,
                "status": "processing",
                "provider": self.name,
            }
        except Exception as e:
            logger.error(f"[GoogleVeo] Submit failed: {e}")
            return {"job_id": None, "status": "failed", "error": str(e)}

    def poll(self, job_id):
        try:
            resp = requests.get(
                f"{self.BASE_URL}/{job_id}",
                headers={"x-goog-api-key": self.api_key},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("done"):
                samples = data.get("response", {}).get("generatedSamples", [])
                if samples:
                    video_uri = samples[0].get("video", {}).get("uri", "")
                    return {"status": "completed", "url": video_uri}
                return {"status": "failed", "error": "No samples in response"}
            return {"status": "processing"}
        except Exception as e:
            logger.error(f"[GoogleVeo] Poll failed: {e}")
            return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Replicate (free trial, then pay-per-gen)
# ---------------------------------------------------------------------------


class ReplicateVideoProvider(VideoProvider):
    name = "replicate"
    display_name = "Replicate"
    is_free = True
    models = [
        {"id": "lightricks/ltx-video", "name": "LTX-Video", "quality": "768x512, 24fps"},
        {"id": "wan-video/wan2.1", "name": "Wan 2.1", "quality": "720p, 5sec"},
    ]

    BASE_URL = "https://api.replicate.com/v1"

    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("REPLICATE_API_TOKEN", "")

    def submit(self, prompt, params=None):
        params = params or {}
        model = params.get("model", "lightricks/ltx-video")
        try:
            resp = requests.post(
                f"{self.BASE_URL}/models/{model}/predictions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": {
                        "prompt": prompt,
                        "num_frames": params.get("num_frames", 65),
                        "fps": params.get("fps", 25),
                        "width": params.get("width", 768),
                        "height": params.get("height", 512),
                    }
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "job_id": data.get("id"),
                "status": "processing",
                "provider": self.name,
                "poll_url": data.get("urls", {}).get("get"),
            }
        except Exception as e:
            logger.error(f"[Replicate] Submit failed: {e}")
            return {"job_id": None, "status": "failed", "error": str(e)}

    def poll(self, job_id):
        try:
            resp = requests.get(
                f"{self.BASE_URL}/predictions/{job_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            if status == "succeeded":
                output = data.get("output")
                url = output if isinstance(output, str) else (output[0] if output else "")
                return {"status": "completed", "url": url}
            elif status in ("failed", "canceled"):
                return {"status": "failed", "error": data.get("error", "Unknown error")}
            return {"status": "processing"}
        except Exception as e:
            logger.error(f"[Replicate] Poll failed: {e}")
            return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# HuggingFace Inference API (free, rate-limited)
# ---------------------------------------------------------------------------


class HuggingFaceVideoProvider(VideoProvider):
    name = "huggingface"
    display_name = "HuggingFace"
    is_free = True
    models = [
        {"id": "Lightricks/LTX-Video-0.9.7-diffusers", "name": "LTX-Video", "quality": "512x512"},
    ]

    BASE_URL = "https://api-inference.huggingface.co/models"

    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("HF_API_TOKEN", "")

    def submit(self, prompt, params=None):
        params = params or {}
        model = params.get("model", "Lightricks/LTX-Video-0.9.7-diffusers")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = requests.post(
                f"{self.BASE_URL}/{model}",
                headers=headers,
                json={"inputs": prompt},
                timeout=120,
            )
            if resp.status_code == 503:
                # Model loading
                eta = resp.json().get("estimated_time", 60)
                return {
                    "job_id": f"hf_{model}_{int(time.time())}",
                    "status": "loading",
                    "eta": eta,
                    "provider": self.name,
                    "_model": model,
                    "_prompt": prompt,
                }
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "video" in content_type or "octet-stream" in content_type:
                # Direct binary response — save immediately
                job_id = f"hf_direct_{int(time.time())}"
                return {
                    "job_id": job_id,
                    "status": "completed",
                    "provider": self.name,
                    "_binary": resp.content,
                }
            data = resp.json()
            return {
                "job_id": data.get("id", f"hf_{int(time.time())}"),
                "status": "processing",
                "provider": self.name,
            }
        except Exception as e:
            logger.error(f"[HuggingFace] Submit failed: {e}")
            return {"job_id": None, "status": "failed", "error": str(e)}

    def poll(self, job_id):
        # HF Inference is mostly synchronous — retry the request
        return {"status": "completed", "note": "HF returns video directly on submit"}


# ---------------------------------------------------------------------------
# LTX Studio (premium, free 800 credits)
# ---------------------------------------------------------------------------


class LTXStudioProvider(VideoProvider):
    name = "ltx_studio"
    display_name = "LTX Studio"
    is_free = False
    models = [
        {"id": "ltx-2.3", "name": "LTX-2.3", "quality": "1080p, 8sec"},
    ]

    BASE_URL = "https://api.ltx.video/v1"

    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("LTX_API_KEY", "")

    def submit(self, prompt, params=None):
        params = params or {}
        try:
            resp = requests.post(
                f"{self.BASE_URL}/generate",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": prompt,
                    "model": params.get("model", "ltx-2.3"),
                    "duration": params.get("duration", 5),
                    "aspect_ratio": params.get("aspect_ratio", "16:9"),
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "job_id": data.get("id"),
                "status": "processing",
                "provider": self.name,
            }
        except Exception as e:
            logger.error(f"[LTXStudio] Submit failed: {e}")
            return {"job_id": None, "status": "failed", "error": str(e)}

    def poll(self, job_id):
        try:
            resp = requests.get(
                f"{self.BASE_URL}/generations/{job_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            if status in ("completed", "done"):
                url = data.get("video_url", data.get("output", {}).get("url", ""))
                return {"status": "completed", "url": url}
            elif status == "failed":
                return {"status": "failed", "error": data.get("error", "Generation failed")}
            return {"status": "processing"}
        except Exception as e:
            logger.error(f"[LTXStudio] Poll failed: {e}")
            return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS = None


def get_video_providers():
    """Get all video provider instances (cached)."""
    global _PROVIDERS
    if _PROVIDERS is None:
        _PROVIDERS = {
            "google_veo": GoogleVeoProvider(),
            "replicate": ReplicateVideoProvider(),
            "huggingface": HuggingFaceVideoProvider(),
            "ltx_studio": LTXStudioProvider(),
        }
    return _PROVIDERS


def get_provider(name):
    """Get a specific provider by name."""
    providers = get_video_providers()
    return providers.get(name)


def get_provider_status():
    """Get status of all providers (configured, free, models)."""
    providers = get_video_providers()
    return [p.get_status() for p in providers.values()]
