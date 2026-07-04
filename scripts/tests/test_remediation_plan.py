"""Controlled test for AI remediation plan generation."""

import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/ai_bridge")

import requests

print("=" * 60)
print("STAGE 1: Warm qwen2.5-coder:7b on Ollama")
print("=" * 60)
try:
    r = requests.post(
        "http://host.docker.internal:11434/api/generate",
        json={
            "model": "qwen2.5-coder:7b",
            "prompt": "ok",
            "stream": False,
            "options": {"num_predict": 1},
        },
        timeout=300,
    )
    print(f"warm HTTP status: {r.status_code}")
except Exception as e:
    print(f"warm failed: {e}")

print()
print("=" * 60)
print("STAGE 2: Clear dispatcher agent cache")
print("=" * 60)
try:
    from ai_bridge.bridge_dispatcher import get_dispatcher

    d = get_dispatcher()
    for attr in ("_agent_cache", "agent_cache", "_cached_agents"):
        if hasattr(d, attr):
            setattr(d, attr, None)
            print(f"cleared {attr}")
except Exception as e:
    print(f"dispatcher import skipped: {e}")

print()
print("=" * 60)
print("STAGE 3: Generate remediation plan for D-238013")
print("=" * 60)
from tools.security_network import compliance_service

t0 = time.time()
res = compliance_service.generate_remediation_plan("7d4ccdf3-a948-41a4-8fb7-31beaae4f101", "D-238013", user_id=2)
elapsed = round(time.time() - t0, 1)

print(f"elapsed: {elapsed}s")
print(f"success: {res.get('success')}")
print(f"plan_id: {res.get('plan_id')}")
print(f"fallback: {res.get('fallback')}")
print(f"error: {res.get('error')}")

plan = res.get("plan") or {}
print()
print("PLAN DETAILS:")
print(f"  model_used:       {plan.get('model_used', plan.get('_model'))}")
print(f"  estimated_downtime: {plan.get('estimated_downtime')}")
print(f"  best_window:      {plan.get('best_window')}")
print(f"  affected_containers: {plan.get('affected_containers')}")
print(f"  prerequisites_count: {len(plan.get('prerequisites') or [])}")
print(f"  steps_count:      {len(plan.get('steps') or [])}")
print(f"  impact_analysis:  {(plan.get('impact_analysis') or '')[:200]}")
print(f"  rollback_plan:    {(plan.get('rollback_plan') or '')[:150]}")
print()
steps = plan.get("steps") or []
for i, s in enumerate(steps[:5]):
    print(f"  STEP {i+1}: {str(s)[:200]}")
