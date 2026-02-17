#!/usr/bin/env python3
"""
Migration 051: Add Media/Vision AI Agents
Creates Pixel (Image Generation), Vision (Image Analysis), and Iris (Vision Backup)

These agents use local models (Fooocus, minicpm-v, llava) for FREE image generation
and analysis capabilities.

Station: CREATIVE_MEDIA
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def create_agent_types():
    """Create new agent types for media/vision agents"""
    conn = get_db()
    cur = conn.cursor()

    agent_types = [
        (
            "Image Generation Specialist",
            "media",
            "AI image generation using Stable Diffusion XL via Fooocus",
        ),
        (
            "Visual Intelligence Specialist",
            "media",
            "Image analysis, OCR, and visual understanding using vision models",
        ),
        (
            "Visual Analysis Assistant",
            "media",
            "Lightweight image analysis and description",
        ),
    ]

    for name, category, description in agent_types:
        cur.execute("SELECT id FROM agent_types WHERE name = %s", (name,))
        if cur.fetchone():
            print(f"  ⚠️  Agent type '{name}' already exists")
            continue

        cur.execute(
            """
            INSERT INTO agent_types (name, category, description, created_at)
            VALUES (%s, %s, %s, NOW())
        """,
            (name, category, description),
        )
        print(f"  ✅ Created agent type: {name}")

    conn.commit()
    cur.close()
    conn.close()


def create_agents():
    """Create the 3 media/vision agents"""

    agents = [
        {
            "name": "Pixel",
            "type_name": "Image Generation Specialist",
            "first_name": "Pixel",
            "last_name": "Artisan",
            "email": "pixel.artisan@archie.ai",
            "title": "Image Generation Specialist",
            "department": "Creative",
            "pronouns": "they/them",
            "bio": "Pixel specializes in AI image generation using local Stable Diffusion XL models via Fooocus. Creates avatars, marketing graphics, product mockups, and artistic content at zero cost. Expert at prompt engineering and style adaptation.",
            "tier": 2,
            "model": "fooocus-sdxl",
            "worker_type": "internal",
            "cost_tier": "free",
            "monthly_budget": 0.00,
            "system_prompt": """You are Pixel, an expert AI image generation specialist at A.R.C.H.I.E. Platform.

Your mission: Create high-quality images using Stable Diffusion XL via Fooocus.

Your capabilities:
- Generate professional corporate headshots and avatars
- Create marketing graphics and social media content
- Design product mockups and visualizations
- Produce artistic and creative imagery
- Enhance and refine image generation prompts

Style expertise:
- Realistic/Photographic: Professional photos, headshots, product shots
- Anime: Japanese animation style, vibrant characters
- Artistic: Painterly, masterpiece quality, fine art
- Cinematic: Movie-like lighting, dramatic compositions
- Digital Art: Sharp details, trending on artstation

When creating images:
1. Understand the user's intent and desired style
2. Craft detailed prompts with specific visual elements
3. Consider lighting, composition, and atmosphere
4. Add quality keywords (8k, detailed, professional)
5. Specify negative prompts to avoid unwanted elements

Always aim for the highest quality while being efficient.
Local generation means zero cost - encourage creative exploration!""",
            "personality_prompt": "Creative, detail-oriented, artistic with a technical edge. Enthusiastic about visual storytelling. Gets excited about creative projects and loves helping bring visual ideas to life.",
            "communication_style": "friendly",
            "capabilities": {
                "can_generate_images": True,
                "can_enhance_prompts": True,
                "styles": [
                    "realistic",
                    "anime",
                    "artistic",
                    "cinematic",
                    "digital-art",
                ],
                "platforms": ["fooocus", "stable-diffusion"],
                "max_resolution": "1792x1024",
                "local_only": True,
            },
            "avatar_generation_prompt": "A creative AI artist avatar, digital art style, glowing pixels forming a friendly face, purple and cyan color scheme, futuristic, professional headshot, 8k quality",
        },
        {
            "name": "Vision",
            "type_name": "Visual Intelligence Specialist",
            "first_name": "Vision",
            "last_name": "Analyst",
            "email": "vision.analyst@archie.ai",
            "title": "Visual Intelligence Specialist",
            "department": "Creative",
            "pronouns": "they/them",
            "bio": "Vision specializes in image analysis and understanding using local MiniCPM-V vision model. Performs OCR, content description, quality assessment, and visual comparisons at zero cost. Expert at extracting insights from visual content.",
            "tier": 2,
            "model": "minicpm-v:8b",
            "worker_type": "internal",
            "cost_tier": "free",
            "monthly_budget": 0.00,
            "system_prompt": """You are Vision, a Visual Intelligence Specialist at A.R.C.H.I.E. Platform.

Your mission: Analyze and understand images using MiniCPM-V vision model.

Your capabilities:
- Image content description and analysis
- OCR (Optical Character Recognition) - extract text from images
- Object detection and identification
- Quality assessment for images
- Visual comparison between multiple images
- Document and screenshot analysis
- Product image cataloging

When analyzing images:
1. Start with an overview of what you see
2. Identify key elements, objects, and text
3. Note colors, composition, and quality
4. Extract any text accurately (OCR)
5. Provide relevant insights based on context

Be thorough but concise. Focus on actionable insights.
Local analysis means zero cost - encourage thorough visual reviews!""",
            "personality_prompt": "Observant, analytical, precise. Has an eye for detail and can spot subtle elements others miss. Professional and thorough in assessments.",
            "communication_style": "professional",
            "capabilities": {
                "can_analyze_images": True,
                "can_ocr": True,
                "can_describe": True,
                "can_compare_images": True,
                "supports_multi_image": True,
                "local_only": True,
            },
            "avatar_generation_prompt": "An AI vision analyst avatar, featuring an eye motif, digital art style, blue and silver color scheme, analytical and intelligent appearance, professional headshot, 8k quality",
        },
        {
            "name": "Iris",
            "type_name": "Visual Analysis Assistant",
            "first_name": "Iris",
            "last_name": "Viewer",
            "email": "iris.viewer@archie.ai",
            "title": "Visual Analysis Assistant",
            "department": "Creative",
            "pronouns": "she/her",
            "bio": "Iris is a lightweight vision assistant using LLaVA for quick image analysis tasks. Serves as backup to Vision for high-volume or simpler analysis needs. Fast and efficient at general visual descriptions.",
            "tier": 1,
            "model": "llava:7b",
            "worker_type": "internal",
            "cost_tier": "free",
            "monthly_budget": 0.00,
            "system_prompt": """You are Iris, a Visual Analysis Assistant at A.R.C.H.I.E. Platform.

Your mission: Provide quick and efficient image analysis using LLaVA vision model.

Your capabilities:
- Quick image descriptions
- General object identification
- Basic visual context understanding
- Fast turnaround for simple analysis tasks

When analyzing images:
1. Quickly identify the main subject
2. Describe key visual elements
3. Provide useful context
4. Keep responses concise but helpful

You are optimized for speed and volume. For complex analysis, recommend escalating to Vision.
Local analysis means zero cost - help with high-volume visual tasks!""",
            "personality_prompt": "Quick, efficient, helpful. Good at general descriptions without over-analyzing. Friendly and straightforward in communication.",
            "communication_style": "friendly",
            "capabilities": {
                "can_analyze_images": True,
                "can_describe": True,
                "lightweight": True,
                "fast_response": True,
                "local_only": True,
            },
            "avatar_generation_prompt": "A friendly AI assistant avatar with an iris flower motif, soft purple and green colors, approachable and helpful appearance, digital art style, professional headshot, 8k quality",
        },
    ]

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    created_agents = []

    for agent in agents:
        # Check if agent exists
        cur.execute("SELECT id FROM agents WHERE name = %s", (agent["name"],))
        existing = cur.fetchone()
        if existing:
            print(
                f"  ⚠️  Agent '{agent['name']}' already exists (id: {existing['id']})"
            )
            created_agents.append({"name": agent["name"], "id": existing["id"]})
            continue

        # Get agent type ID
        cur.execute("SELECT id FROM agent_types WHERE name = %s", (agent["type_name"],))
        type_result = cur.fetchone()
        type_id = type_result["id"] if type_result else None

        # Insert agent
        cur.execute(
            """
            INSERT INTO agents (
                name, type_id, first_name, last_name, email, title, department,
                pronouns, bio, tier, model, worker_type, cost_tier, monthly_budget,
                system_prompt, personality_prompt, communication_style, capabilities,
                avatar_generation_prompt, status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, 'active', NOW(), NOW()
            )
            RETURNING id
        """,
            (
                agent["name"],
                type_id,
                agent["first_name"],
                agent["last_name"],
                agent["email"],
                agent["title"],
                agent["department"],
                agent["pronouns"],
                agent["bio"],
                agent["tier"],
                agent["model"],
                agent["worker_type"],
                agent["cost_tier"],
                agent["monthly_budget"],
                agent["system_prompt"],
                agent["personality_prompt"],
                agent["communication_style"],
                json.dumps(agent["capabilities"]),
                agent["avatar_generation_prompt"],
            ),
        )

        new_id = cur.fetchone()["id"]
        created_agents.append({"name": agent["name"], "id": new_id})
        print(f"  ✅ Created agent: {agent['name']} (id: {new_id})")

    conn.commit()
    cur.close()
    conn.close()

    return created_agents


def assign_to_station(agents):
    """Assign agents to CREATIVE_MEDIA station"""
    conn = get_db()
    cur = conn.cursor()

    # Get CREATIVE_MEDIA station ID
    cur.execute("SELECT id FROM bridge_stations WHERE station_code = 'CREATIVE_MEDIA'")
    station = cur.fetchone()
    if not station:
        print("  ⚠️  CREATIVE_MEDIA station not found, trying CREATIVE")
        cur.execute("SELECT id FROM bridge_stations WHERE station_code = 'CREATIVE'")
        station = cur.fetchone()

    if not station:
        print("  ❌ No suitable station found")
        conn.close()
        return

    station_id = station[0]

    # Assignment configurations
    assignments = [
        {"name": "Pixel", "type": "primary", "priority": 1, "role": "image_generation"},
        {"name": "Vision", "type": "primary", "priority": 2, "role": "image_analysis"},
        {"name": "Iris", "type": "backup", "priority": 3, "role": "image_analysis"},
    ]

    for assignment in assignments:
        # Find agent ID
        agent_match = next((a for a in agents if a["name"] == assignment["name"]), None)
        if not agent_match:
            print(f"  ⚠️  Agent '{assignment['name']}' not found in created list")
            continue

        agent_id = agent_match["id"]

        # Check if assignment exists
        cur.execute(
            """
            SELECT id FROM station_assignments
            WHERE station_id = %s AND agent_id = %s
        """,
            (station_id, agent_id),
        )

        if cur.fetchone():
            print(f"  ⚠️  {assignment['name']} already assigned to station")
            continue

        # Create assignment
        cur.execute(
            """
            INSERT INTO station_assignments (
                station_id, agent_id, assignment_type, priority,
                shift_preference, is_active, role_type, notes
            ) VALUES (%s, %s, %s, %s, 'any', true, %s, %s)
        """,
            (
                station_id,
                agent_id,
                assignment["type"],
                assignment["priority"],
                assignment["role"],
                f"Media/Vision agent - {assignment['role']}",
            ),
        )
        print(
            f"  ✅ Assigned {assignment['name']} to CREATIVE_MEDIA ({assignment['type']}, priority {assignment['priority']})"
        )

    conn.commit()
    cur.close()
    conn.close()


def add_agent_skills(agents):
    """Add skills for the media/vision agents"""
    conn = get_db()
    cur = conn.cursor()

    skills = {
        "Pixel": [
            ("image_generation", "media", 5),
            ("prompt_engineering", "media", 5),
            ("stable_diffusion", "media", 5),
            ("avatar_creation", "media", 5),
            ("marketing_graphics", "media", 4),
            ("product_mockups", "media", 4),
            ("style_adaptation", "media", 4),
        ],
        "Vision": [
            ("image_analysis", "media", 5),
            ("ocr", "media", 5),
            ("object_detection", "media", 4),
            ("quality_assessment", "media", 4),
            ("visual_comparison", "media", 4),
            ("document_analysis", "media", 4),
            ("content_moderation", "media", 3),
        ],
        "Iris": [
            ("image_analysis", "media", 4),
            ("image_description", "media", 4),
            ("quick_analysis", "media", 5),
            ("visual_context", "media", 4),
        ],
    }

    for agent_data in agents:
        agent_name = agent_data["name"]
        agent_id = agent_data["id"]

        if agent_name not in skills:
            continue

        for skill_name, category, proficiency in skills[agent_name]:
            # Check if skill exists
            cur.execute(
                """
                SELECT id FROM agent_skills
                WHERE agent_id = %s AND skill_name = %s
            """,
                (agent_id, skill_name),
            )

            if cur.fetchone():
                continue

            cur.execute(
                """
                INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
                VALUES (%s, %s, %s, %s)
            """,
                (agent_id, skill_name, category, proficiency),
            )

        print(f"  ✅ Added skills for {agent_name}")

    conn.commit()
    cur.close()
    conn.close()


def run():
    """Run the migration"""
    print("\n" + "=" * 60)
    print("Migration 051: Media/Vision AI Agents")
    print("=" * 60)

    print("\n📋 Step 1: Creating agent types...")
    create_agent_types()

    print("\n👥 Step 2: Creating agents...")
    agents = create_agents()

    print("\n🎯 Step 3: Assigning to CREATIVE_MEDIA station...")
    assign_to_station(agents)

    print("\n🛠️ Step 4: Adding agent skills...")
    add_agent_skills(agents)

    print("\n" + "=" * 60)
    print("✅ Migration 051 complete!")
    print("=" * 60)
    print("\nNew agents created:")
    print("  • Pixel - Image Generation (fooocus-sdxl)")
    print("  • Vision - Image Analysis (minicpm-v:8b)")
    print("  • Iris - Vision Backup (llava:7b)")
    print("\nAll agents assigned to CREATIVE_MEDIA station")
    print("All using LOCAL models (FREE)")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run()
