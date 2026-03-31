"""
RunPod Serverless Video Provider — Media Studio
================================================
Adapter for RunPod serverless endpoints running LTX-Video.
Implements submit/poll/download for async video generation.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

RUNPOD_API_BASE = "https://api.runpod.ai/v2"

# RTX 3090 cost per second on RunPod serverless
COST_PER_SECOND_RTX3090 = 0.00036


class RunPodVideoProvider:
    """RunPod serverless video generation provider (LTX-Video)."""

    name = "runpod"
    display_name = "RunPod Serverless"
    is_free = False
    models = [
        {"id": "ltx-video", "name": "LTX-Video", "quality": "1024px, 120 frames, 30fps"},
    ]

    def __init__(self):
        self.api_key = os.getenv("RUNPOD_API_KEY", "")
        self.endpoint_id = os.getenv("RUNPOD_LTX_ENDPOINT_ID", "")

    def is_configured(self):
        """Returns True if both RUNPOD_API_KEY and RUNPOD_LTX_ENDPOINT_ID are set."""
        return bool(self.api_key and self.endpoint_id)

    # ------------------------------------------------------------------
    # is_configured as property alias for VideoProvider base compatibility
    # ------------------------------------------------------------------

    @property
    def _is_configured(self):
        return self.is_configured()

    def get_status(self):
        """Return provider status dict (matches VideoProvider.get_status interface)."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "configured": self.is_configured(),
            "is_free": self.is_free,
            "models": self.models,
        }

    def generate(self, prompt, params=None):
        """
        Submit a video generation job to RunPod.

        Args:
            prompt (str): Text prompt for video generation.
            params (dict): Optional generation parameters.

        Returns:
            dict: {job_id, status, provider} on success, {error} on failure.
        """
        params = params or {}
        payload = {
            "input": {
                "prompt": prompt,
                "negative_prompt": params.get("negative_prompt", ""),
                "width": params.get("width", 768),
                "height": params.get("height", 512),
                "num_frames": params.get("num_frames", 65),
                "fps": params.get("fps", 24),
                "num_inference_steps": params.get("num_inference_steps", 30),
                "guidance_scale": params.get("guidance_scale", 3.5),
            }
        }
        try:
            resp = requests.post(
                f"{RUNPOD_API_BASE}/{self.endpoint_id}/run",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
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
            logger.error(f"[RunPod] generate failed: {e}")
            return {"error": str(e)}

    # Alias for compatibility with VideoProvider submit/poll interface
    def submit(self, prompt, params=None):
        return self.generate(prompt, params)

    def get_status_for_job(self, job_id):
        """
        Poll a RunPod job for status and output URL.

        Args:
            job_id (str): RunPod job ID returned from generate().

        Returns:
            dict: status + output_url (when COMPLETED) + estimated_cost.
        """
        try:
            resp = requests.get(
                f"{RUNPOD_API_BASE}/{self.endpoint_id}/status/{job_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            run_status = data.get("status", "").upper()

            result = {"status": run_status.lower()}

            if run_status == "COMPLETED":
                output = data.get("output", {})
                result["output_url"] = output.get("video_url", output.get("url", ""))
                exec_time_ms = data.get("executionTime", 0)
                result["estimated_cost"] = round((exec_time_ms / 1000) * COST_PER_SECOND_RTX3090, 6)
            elif run_status == "FAILED":
                result["error"] = data.get("error", "Job failed on RunPod")

            return result
        except Exception as e:
            logger.error(f"[RunPod] get_status failed for job {job_id}: {e}")
            return {"error": str(e)}

    # Alias for VideoProvider poll interface
    def poll(self, job_id):
        result = self.get_status_for_job(job_id)
        if "error" in result and "status" not in result:
            return {"status": "error", "error": result["error"]}
        status = result.get("status", "processing")
        if status == "completed":
            return {"status": "completed", "url": result.get("output_url", "")}
        elif status == "failed":
            return {"status": "failed", "error": result.get("error", "Job failed")}
        return {"status": "processing"}

    def get_capabilities(self):
        """
        Return provider capabilities metadata.

        Returns:
            dict: Capability descriptor including resolution, frame, and cost limits.
        """
        return {
            "name": "runpod",
            "type": "cloud_gpu",
            "supports_video": True,
            "max_resolution": 1024,
            "max_frames": 120,
            "max_fps": 30,
            "models": ["ltx-video"],
            "cost_per_second": COST_PER_SECOND_RTX3090,
            "configured": self.is_configured(),
        }

    def download_result(self, output_url, save_path):
        """
        Stream-download a completed video to a local file.

        Args:
            output_url (str): URL returned in get_status_for_job output.
            save_path (str): Absolute path to save the video file.

        Returns:
            dict: {success, path, size_bytes} on success, {error} on failure.
        """
        try:
            resp = requests.get(output_url, stream=True, timeout=120)
            resp.raise_for_status()
            size = 0
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
            return {"success": True, "path": save_path, "size_bytes": size}
        except Exception as e:
            logger.error(f"[RunPod] download_result failed: {e}")
            return {"error": str(e)}

    # Alias for VideoProvider download interface
    def download(self, url):
        """Download and return raw bytes (VideoProvider base interface)."""
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.error(f"[RunPod] download failed: {e}")
            return None
