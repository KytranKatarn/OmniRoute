"""Raw dispatch_json test to see what F.O.R.G.E. actually returns."""
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

from bridge_dispatcher import dispatch_json

prompt = """You are F.O.R.G.E. Return a JSON object with keys: impact_analysis (string), steps (array of objects with action, why, safe_auto), estimated_downtime (string). Example: {"impact_analysis": "...", "steps": [{"action":"stop container","why":"prep","safe_auto":true}], "estimated_downtime":"5 min"}. Rule: D-238013 host network mode. Return ONLY the JSON, no prose."""

print("Calling dispatch_json(capability='code-generation')...")
t0 = time.time()
try:
    result = dispatch_json(
        capability="code-generation",
        prompt=prompt,
        module_id="test_raw",
    )
    elapsed = round(time.time() - t0, 1)
    print(f"elapsed: {elapsed}s")
    print(f"type: {type(result).__name__}")
    print(f"value: {str(result)[:800]}")
except Exception as e:
    print(f"EXCEPTION after {round(time.time()-t0,1)}s: {type(e).__name__}: {e}")
