"""Manually fire the auto_plan_generation job once to verify it runs
end-to-end through the real scheduler job function."""

import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

from tools.security_network.jobs import run_auto_plan_generation

print("Firing run_auto_plan_generation()...")
t0 = time.time()
try:
    run_auto_plan_generation()
    print(f"elapsed: {round(time.time()-t0, 1)}s  status: OK")
except Exception as e:
    print(f"elapsed: {round(time.time()-t0, 1)}s  status: EXCEPTION {type(e).__name__}: {e}")
