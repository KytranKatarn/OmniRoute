#!/usr/bin/env python3
"""Test V2 with Qwen 2.5 Coder"""
import sys
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

print("=" * 60)
print("V2 TEST with QWEN2.5-CODER:7B")
print("=" * 60)

from code_generation_engine import CodeGenerationEngine

class TestEngine(CodeGenerationEngine):
    def _select_model_for_task(self, category, prefer_contractor):
        return "qwen2.5-coder:7b"

engine = TestEngine()

result = engine.generate_with_validation(
    proposal_id=6,
    proposal_title="Fix bare except clause",
    proposal_description="""Change the bare 'except:' at line 43 to 'except Exception:'.

The code at line 43 is:
        except:
            continue

Change to:
        except Exception:
            continue

Note: 8 spaces before 'except', 12 spaces before 'continue'.""",
    category="code_quality",
    target_files=["platform_v2/tools/coderabbit/routes.py"],
    line_number=43,
    prefer_contractor=False
)

print(f"\nSuccess: {result.get('success')}")
print(f"Changes: {len(result.get('changes', []))}")

if result.get("validation_results"):
    for vr in result["validation_results"]:
        if vr.get('valid'):
            print(f"✅ Valid ({vr.get('match_type')})")
        else:
            err = vr.get('error', '')[:80]
            print(f"❌ {err}")

if result.get("changes"):
    c = result["changes"][0]
    print(f"\n--- Generated Change ---")
    print(f"Old:\n{c.get('old_content', '')}")
    print(f"\nNew:\n{c.get('new_content', '')}")
