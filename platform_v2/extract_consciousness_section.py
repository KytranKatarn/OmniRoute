#!/usr/bin/env python3
"""
Extract consciousness section from admin.html and create standalone consciousness dashboard
Phase 4: Consciousness Consolidation
"""
import re

# Read admin template
with open('/mnt/archie_brain/platform_v2/templates/tools/admin.html', 'r', encoding='utf-8') as f:
    admin_content = f.read()
    admin_lines = admin_content.split('\n')

# Extract consciousness section (lines 2297-4168, 0-indexed so 2296-4167)
consciousness_section = '\n'.join(admin_lines[2296:4168])

# Remove the wrapping <div class="content-section" id="section-consciousness">
# and replace with proper page structure
consciousness_section = consciousness_section.replace(
    '<div class="content-section" id="section-consciousness">',
    ''
).rstrip('</div>')

# Create new consciousness dashboard template
new_dashboard = f"""{{%extends "admin_base.html" %}}

{{%block title %}}A.R.C.H.I.E.'s Consciousness - Knowledge & Memory Dashboard{{%endblock %}}

{{%block content %}}
<div style="padding: 30px; min-height: 100vh; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);">

    <div style="max-width: 1400px; margin: 0 auto;">
        <div style="text-align: center; margin-bottom: 40px;">
            <h1 style="color: #00FFFF; font-size: 3rem; text-shadow: 0 0 20px rgba(0,255,255,0.5); margin-bottom: 10px;">
                🧠 A.R.C.H.I.E.'S CONSCIOUSNESS
            </h1>
            <p style="color: #888; font-size: 1.2rem;">
                Knowledge analytics, memory insights, and learning management
            </p>
        </div>

{consciousness_section}

    </div>
</div>
{{%endblock %}}
"""

# Write new consciousness dashboard
with open('/mnt/archie_brain/platform_v2/templates/tools/consciousness_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(new_dashboard)

print("✅ Extracted consciousness section from admin.html")
print(f"   Section size: {len(consciousness_section)} characters")
print("✅ Created new consciousness_dashboard.html")
print("   Location: /mnt/archie_brain/platform_v2/templates/tools/consciousness_dashboard.html")
