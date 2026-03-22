#!/usr/bin/env python3
"""
Generate photorealistic professional headshot portraits for ALL ARCHIE platform agents.
Uses ComfyUI API on hub (192.168.1.200:8188) with RealVisXL_V4.0 checkpoint.

Usage:
    python3 generate_portraits.py                    # Generate ALL portraits (overwrites existing)
    python3 generate_portraits.py --missing-only      # Only generate missing portraits
    python3 generate_portraits.py --agent-id 8       # Generate for specific agent ID
    python3 generate_portraits.py --checkpoint RealVisXL_V4.0.safetensors
    python3 generate_portraits.py --node starship    # Use Starship GPU (SD1.5 only)
    python3 generate_portraits.py --dry-run           # Show what would be generated
    python3 generate_portraits.py --sd15              # Use SD1.5 for faster generation
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Force unbuffered output for logging
sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)
sys.stderr = os.fdopen(sys.stderr.fileno(), "w", buffering=1)

# ── Config ──────────────────────────────────────────────────────────────────
HUB_COMFYUI = "http://192.168.1.200:8188"
STARSHIP_COMFYUI = "http://192.168.1.246:8188"
PORTRAITS_DIR = "/mnt/archie_brain/platform_v2/static/media/portraits"
DEFAULT_CHECKPOINT = "RealVisXL_V4.0.safetensors"
SD15_CHECKPOINT = "v1-5-pruned-emaonly.safetensors"

# SDXL = 768x768, SD1.5 = 512x512
SDXL_RES = (768, 768)
SD15_RES = (512, 512)

NEGATIVE_PROMPT = (
    "cartoon, anime, illustration, painting, blurry, low quality, deformed, "
    "disfigured, extra limbs, bad anatomy, watermark, text, logo, signature, "
    "frame, border, cropped, worst quality, jpeg artifacts, ugly, duplicate, "
    "morbid, mutilated, out of frame, mutation, poorly drawn face, "
    "sci-fi uniform, futuristic, fantasy costume, armor, helmet"
)

# DB connection
DB_HOST = "192.168.1.200"
DB_NAME = "archie"
DB_USER = "archie"
DB_PASS = os.environ.get("DB_PASSWORD", "")


# ── Ethnicity / appearance mapping from names ───────────────────────────────
# Maps (first_name, last_name) patterns to appearance descriptors
ETHNICITY_HINTS = {
    # East Asian
    "Jin Park": "Korean man",
    "Kai Tanaka": "Japanese man",
    "Wei Chen": "Chinese man",
    "Seo-Jun Kim": "Korean man",
    "Hana Yoshida": "Japanese woman",
    "Mei Lin Zhou": "Chinese woman",
    "Dr. Kenji Yamamoto": "Japanese man",
    "Yuki Sato": "Japanese non-binary person",
    "Aria Chen": "East Asian woman",
    # South Asian
    "Dr. Aisha Patel": "South Asian woman",
    "Priya Sharma": "South Asian woman",
    "Rohan Mehta": "South Asian man",
    "Ananya Rao": "South Asian woman",
    "Kavya Iyer": "South Asian woman",
    "Vikram Singh": "South Asian man",
    # Middle Eastern
    "Fatima Al-Rashid": "Middle Eastern woman wearing modest professional attire",
    "Omar Farah": "Somali man",
    "Amina Youssef": "Middle Eastern woman wearing hijab",
    "Tariq Hassan": "Middle Eastern man",
    "Zara Nazari": "Persian woman",
    "Layla Khoury": "Lebanese woman",
    # African / African diaspora
    "Amara Osei": "Ghanaian woman with dark skin",
    "Nia Williams": "Black woman",
    "Kofi Mensah": "Ghanaian man with dark skin",
    "Kwame Asante": "Ghanaian man with dark skin",
    "Adaeze Okonjo": "Nigerian woman with dark skin",
    "Chidi Okafor": "Nigerian man with dark skin",
    "Jabari Mwangi": "Kenyan man with dark skin",
    "Zuri Ndegwa": "Kenyan woman with dark skin",
    "Anika Osei": "Ghanaian woman with dark skin",
    "Folake Adeyemi": "Nigerian woman with dark skin",
    "Esi Boateng": "Ghanaian woman with dark skin",
    "Tendai Moyo": "Zimbabwean man with dark skin",
    # Latin American
    "Marcus Rivera": "Latino man",
    "Dante Morales": "Latino man",
    "Mia Santos": "Latina woman",
    "Isabella Reyes": "Latina woman",
    "Carlos Mendez": "Latino man",
    "Tomás Herrera": "Latino man",
    "Rafael Torres": "Latino man",
    "Lucia Vargas": "Latina woman",
    "Gabriela Fuentes": "Latina woman",
    # Eastern European
    "Sofia Petrov": "Eastern European woman",
    "Nadia Volkov": "Russian woman",
    "Elena Papadopoulos": "Greek woman",
    "Alexei Ivanovich": "Russian man",
    "Erik Andersson": "Scandinavian man with light features",
    "Ingrid Holmström": "Scandinavian woman with light features",
    "Viktor Novak": "Czech man",
    # Western European
    "Liam O'Brien": "Irish man with fair skin",
    "Marie-Claire LeBlanc": "French-Canadian woman",
    "Sophie Laurent": "French woman",
    "Callum Fraser": "Scottish man",
    "James Whitfield": "British man",
    # Indigenous / First Nations
    "Koda Begay": "Native American (Diné/Navajo) man with warm brown skin",
    "Niviaq Iqaluk": "Inuit woman with warm brown skin and dark hair",
    "Wren Tallchief": "Native American woman",
    # African American
    "David Park": "Black man, military veteran appearance",
    "Tyler Summers": "young Black man in his early 20s",
    "Grant Morrison": "Black man",
    "Jordan Reeves": "Black non-binary person",
    # Mixed / Other
    "Alex Whitehorse": "person of mixed heritage",
    "Atlas Reeves": "man of mixed heritage",
    "Morgan Blake": "person with androgynous features",
    "River Okafor-Johansson": "person of mixed Nigerian-Scandinavian heritage",
    "Dakota Silveira": "non-binary person of mixed heritage",
    "Quinn Delacroix": "non-binary person with artistic appearance",
    "Sage Nakamura": "non-binary person of Japanese heritage",
    # Default European-presenting
    "Eli Torres": "man",
    "Sarah Chen": "East Asian woman",
    "Rachel Kim": "Korean woman",
    "Hannah Berg": "woman with light features",
    "Maya Johal": "South Asian woman",
    "Noor Abbasi": "Middle Eastern woman",
    "Tess Morgan": "woman",
    "Ben Archer": "man",
    "Fiona McAllister": "Scottish woman with red hair",
    "Leo Marchetti": "Italian man",
    "Dina Petrov": "Eastern European woman",
    "Sam Okafor": "Nigerian man with dark skin",
}

# Special agents (AI entities, not human-presenting)
AI_AGENTS = {
    "A.R.C.H.I.E.": (
        "futuristic AI entity portrait, glowing cyan holographic face, "
        "digital neural network patterns, dark background with teal light streams, "
        "professional corporate style, photorealistic 3D render, 8k"
    ),
    "Vigil": (
        "futuristic AI security guardian portrait, stern digital face with amber glowing eyes, "
        "dark background with red security grid overlay, "
        "professional corporate style, photorealistic 3D render, 8k"
    ),
}


def get_db():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    return psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        cursor_factory=RealDictCursor,
    )


def get_agents(agent_id=None, missing_only=False):
    """Fetch agents for portrait generation."""
    conn = get_db()
    cur = conn.cursor()
    if agent_id:
        cur.execute(
            """SELECT id, display_name, name, first_name, last_name, pronouns, department, title
               FROM agents WHERE id = %s AND status = 'active'""",
            (agent_id,),
        )
    elif missing_only:
        # Only agents whose portrait file doesn't exist on disk
        cur.execute(
            """SELECT id, display_name, name, first_name, last_name, pronouns, department, title
               FROM agents WHERE status = 'active' ORDER BY id"""
        )
    else:
        cur.execute(
            """SELECT id, display_name, name, first_name, last_name, pronouns, department, title
               FROM agents WHERE status = 'active' ORDER BY id"""
        )
    agents = cur.fetchall()
    conn.close()

    if missing_only:
        # Filter to agents without a portrait file on disk
        agents = [
            a
            for a in agents
            if not os.path.exists(
                os.path.join(PORTRAITS_DIR, f"{a['name'].lower()}.png")
            )
        ]

    return agents


def build_prompt(agent):
    """Build a detailed, culturally-aware portrait prompt for an agent."""
    first_name = agent.get("first_name", "") or ""
    last_name = agent.get("last_name", "") or ""
    full_name = f"{first_name} {last_name}".strip()
    pronouns = agent.get("pronouns", "they/them") or "they/them"
    name_code = agent["name"]

    # Check if this is an AI agent
    if full_name in AI_AGENTS:
        return AI_AGENTS[full_name]

    # Determine gender presentation from pronouns
    if pronouns == "he/him":
        gender = "man"
        attire = "wearing a tailored dark suit with a crisp white shirt and subtle tie"
    elif pronouns == "she/her":
        gender = "woman"
        attire = "wearing a professional blazer over a blouse"
    else:  # they/them
        gender = "person with androgynous features"
        attire = "wearing a modern professional blazer"

    # Get ethnicity/appearance hint from name
    appearance = ETHNICITY_HINTS.get(full_name, gender)

    # If appearance already contains gender word, use it directly; otherwise prepend
    if gender not in appearance and "man" not in appearance and "woman" not in appearance and "person" not in appearance:
        appearance = f"{appearance} {gender}"

    # Age range based on title
    title = agent.get("title", "") or ""
    if "Junior" in title or "Intern" in title:
        age = "in their mid-20s"
    elif "Senior" in title or "Lead" in title or "Head" in title or "Chief" in title or "Director" in title or "Dr." in first_name:
        age = "in their early 40s"
    else:
        age = "in their early 30s"

    prompt = (
        f"professional corporate headshot photograph of a {appearance} {age}, "
        f"{attire}, "
        f"confident and approachable expression, looking directly at camera, "
        f"head and shoulders framing, centered composition, "
        f"neutral gray studio background, soft diffused studio lighting with subtle rim light, "
        f"shallow depth of field, shot on Canon EOS R5 85mm f/1.4, "
        f"photorealistic, high detail skin texture, natural skin tones, 8k, sharp focus"
    )

    return prompt


def get_available_checkpoints(comfyui_url):
    """List checkpoints available on a ComfyUI instance."""
    try:
        resp = urllib.request.urlopen(
            f"{comfyui_url}/object_info/CheckpointLoaderSimple", timeout=10
        )
        data = json.loads(resp.read())
        return data["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except Exception as e:
        print(f"  Error checking {comfyui_url}: {e}")
        return []


def build_workflow(prompt, negative_prompt, checkpoint, seed, width, height):
    """Build ComfyUI API workflow for portrait generation."""
    # Use fewer steps for SD1.5 vs SDXL
    is_sdxl = "XL" in checkpoint or "xl" in checkpoint or "sdxl" in checkpoint
    steps = 25 if is_sdxl else 20
    cfg = 7.0 if is_sdxl else 7.5

    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "portrait", "images": ["8", 0]},
        },
    }
    return workflow


def queue_prompt(comfyui_url, workflow):
    """Queue a prompt on ComfyUI and return the prompt_id."""
    payload = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{comfyui_url}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        return data.get("prompt_id")
    except Exception as e:
        print(f"  Error queuing prompt: {e}")
        return None


def wait_for_completion(comfyui_url, prompt_id, timeout=600):
    """Wait for a queued prompt to complete."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(
                f"{comfyui_url}/history/{prompt_id}", timeout=10
            )
            data = json.loads(resp.read())
            if prompt_id in data:
                status = data[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    msgs = status.get("messages", [])
                    print(f"  ComfyUI error: {msgs}")
                    return None
                outputs = data[prompt_id].get("outputs", {})
                # Check for images in outputs
                for node_id, output in outputs.items():
                    if "images" in output:
                        return output["images"]
                # If all nodes were cached, outputs may be empty — this is OK
                # Check if execution was cached
                cached_nodes = []
                for msg_type, msg_data in status.get("messages", []):
                    if msg_type == "execution_cached":
                        cached_nodes = msg_data.get("nodes", [])
                if cached_nodes and not outputs:
                    print("  Cached result (same seed) — no new image generated")
                    return "CACHED"
                # Status success but no images — generation produced nothing
                if status.get("completed"):
                    return []
        except Exception:
            pass
        time.sleep(3)
    print(f"  Timeout waiting for {prompt_id}")
    return None


def download_image(comfyui_url, image_info, dest_path):
    """Download a generated image from ComfyUI."""
    filename = image_info["filename"]
    subfolder = image_info.get("subfolder", "")
    img_type = image_info.get("type", "output")
    url = f"{comfyui_url}/view?filename={filename}&subfolder={subfolder}&type={img_type}"
    try:
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception as e:
        print(f"  Error downloading image: {e}")
        return False


def save_to_db(agent_id, image_path, prompt, seed, checkpoint, comfyui_url, gen_time_ms, width, height, file_size):
    """Save portrait record to agent_portraits table and update agents.avatar_url."""
    conn = get_db()
    cur = conn.cursor()
    # Determine GPU info from URL
    gpu_host = "hub" if "200" in comfyui_url else "starship"
    gpu_model = "Quadro M4000" if gpu_host == "hub" else "RTX 3070"

    try:
        # Delete any existing portrait record for this agent, then insert fresh
        cur.execute("DELETE FROM agent_portraits WHERE agent_id = %s", (agent_id,))
        cur.execute(
            """
            INSERT INTO agent_portraits (agent_id, canonical_image_path, identity_prompt, face_seed,
                                         model_used, approved, gpu_host, gpu_model, generation_time_ms,
                                         resolution_w, resolution_h, provider, file_size_bytes)
            VALUES (%s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s, 'comfyui', %s)
        """,
            (agent_id, image_path, prompt, seed, checkpoint, gpu_host, gpu_model,
             gen_time_ms, width, height, file_size),
        )

        # Update agents.avatar_url
        cur.execute(
            "UPDATE agents SET avatar_url = %s WHERE id = %s",
            (image_path, agent_id),
        )
        conn.commit()
    except Exception as e:
        print(f"  DB error: {e}")
        conn.rollback()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Generate agent portraits via ComfyUI")
    parser.add_argument("--agent-id", type=int, help="Generate for specific agent ID")
    parser.add_argument("--checkpoint", help="Override checkpoint (auto-detected)")
    parser.add_argument(
        "--node",
        choices=["hub", "starship"],
        default="hub",
        help="Which GPU to use (default: hub with RealVisXL)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show prompts without generating")
    parser.add_argument("--missing-only", action="store_true", help="Only generate missing portraits")
    parser.add_argument("--sd15", action="store_true", help="Use SD1.5 (faster, lower quality)")
    parser.add_argument("--seed", type=int, help="Fixed seed for reproducibility")
    parser.add_argument("--start-from", type=int, default=0, help="Start from Nth agent (for resuming)")
    args = parser.parse_args()

    os.makedirs(PORTRAITS_DIR, exist_ok=True)

    # Determine ComfyUI endpoint
    comfyui_url = STARSHIP_COMFYUI if args.node == "starship" else HUB_COMFYUI

    # Determine checkpoint and resolution
    if args.checkpoint:
        checkpoint = args.checkpoint
        is_sdxl = "XL" in checkpoint or "xl" in checkpoint or "sdxl" in checkpoint
    elif args.sd15 or args.node == "starship":
        # Starship only has SD1.5; also use SD1.5 if --sd15 flag
        checkpoint = "v1-5-pruned-emaonly.ckpt" if args.node == "starship" else SD15_CHECKPOINT
        is_sdxl = False
    else:
        checkpoint = DEFAULT_CHECKPOINT
        is_sdxl = True

    width, height = SDXL_RES if is_sdxl else SD15_RES

    print(f"═══════════════════════════════════════════════════")
    print(f"  ARCHIE Agent Portrait Generator")
    print(f"═══════════════════════════════════════════════════")
    print(f"  ComfyUI:    {comfyui_url}")
    print(f"  Checkpoint: {checkpoint}")
    print(f"  Resolution: {width}x{height}")
    print(f"  Mode:       {'Dry Run' if args.dry_run else 'LIVE GENERATION'}")
    print(f"═══════════════════════════════════════════════════")

    # Verify checkpoint availability
    if not args.dry_run:
        checkpoints = get_available_checkpoints(comfyui_url)
        if not checkpoints:
            print(f"ERROR: Cannot reach ComfyUI at {comfyui_url}")
            sys.exit(1)
        if checkpoint not in checkpoints:
            print(f"ERROR: {checkpoint} not found on {comfyui_url}")
            print(f"Available: {checkpoints}")
            sys.exit(1)
        print(f"  Checkpoint verified: {checkpoint}")

    # Get agents
    agents = get_agents(args.agent_id, args.missing_only)
    if args.start_from > 0:
        agents = agents[args.start_from:]

    print(f"  Agents to generate: {len(agents)}")
    print()

    if args.dry_run:
        for i, agent in enumerate(agents):
            name = agent["display_name"] or agent["name"]
            code = agent["name"].lower()
            prompt = build_prompt(agent)
            print(f"  [{i+1}] {name} → {code}.png")
            print(f"      {prompt[:120]}...")
            print()
        return

    # ── Generate portraits ──────────────────────────────────────────────────
    generated = 0
    failed = 0
    skipped = 0
    failed_agents = []

    for i, agent in enumerate(agents):
        name = agent["display_name"] or agent["name"]
        code = agent["name"].lower()
        dest_path = os.path.join(PORTRAITS_DIR, f"{code}.png")

        print(f"[{i+1}/{len(agents)}] Generating: {name} → {code}.png")

        prompt = build_prompt(agent)
        # Seed: reproducible per agent but includes a run timestamp component
        # so re-runs generate fresh images (avoids ComfyUI caching)
        run_seed_offset = int(time.time()) % 100000
        seed = args.seed if args.seed else (agent["id"] * 7919 + 42 + run_seed_offset) % (2**32)

        workflow = build_workflow(prompt, NEGATIVE_PROMPT, checkpoint, seed, width, height)

        gen_start = time.time()
        prompt_id = queue_prompt(comfyui_url, workflow)
        if not prompt_id:
            print(f"  FAILED to queue")
            failed += 1
            failed_agents.append(code)
            continue

        print(f"  Queued: {prompt_id}, seed={seed}, waiting...")
        images = wait_for_completion(comfyui_url, prompt_id, timeout=600)
        gen_time_ms = int((time.time() - gen_start) * 1000)

        if images == "CACHED":
            # Cached result — file may already exist from prior run
            if os.path.exists(dest_path):
                print(f"  SKIPPED (cached, file exists): {code}.png")
                skipped += 1
            else:
                print(f"  FAILED — cached but no file on disk")
                failed += 1
                failed_agents.append(code)
            continue

        if not images:
            print(f"  FAILED — no images returned")
            failed += 1
            failed_agents.append(code)
            continue

        if download_image(comfyui_url, images[0], dest_path):
            file_size = os.path.getsize(dest_path)
            rel_path = f"/static/media/portraits/{code}.png"
            save_to_db(
                agent["id"], rel_path, prompt, seed, checkpoint,
                comfyui_url, gen_time_ms, width, height, file_size,
            )
            print(f"  DONE: {rel_path} ({file_size/1024:.0f}KB, {gen_time_ms/1000:.1f}s)")
            generated += 1
        else:
            failed += 1
            failed_agents.append(code)

    # ── Summary ─────────────────────────────────────────────────────────────
    print()
    print(f"═══════════════════════════════════════════════════")
    print(f"  COMPLETE")
    print(f"═══════════════════════════════════════════════════")
    print(f"  Generated: {generated}")
    print(f"  Skipped:   {skipped}")
    print(f"  Failed:    {failed}")
    print(f"  Total:     {len(agents)}")
    if failed_agents:
        print(f"  Failed agents: {', '.join(failed_agents)}")
    print(f"═══════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
