#!/usr/bin/env python3
"""
Generate photorealistic portraits for all Kytran Empowerment agents.
Uses ComfyUI API on hub (192.168.1.200:8188) and/or Starship (192.168.1.246:8188).

Usage:
    python3 generate_portraits.py                    # Generate all missing portraits
    python3 generate_portraits.py --agent-id 8       # Generate for specific agent
    python3 generate_portraits.py --checkpoint RealVisXL_V4.0.safetensors  # Use specific model
    python3 generate_portraits.py --node starship    # Use Starship GPU only
    python3 generate_portraits.py --dry-run           # Show what would be generated
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

# Force unbuffered output for logging
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', buffering=1)

# Config
HUB_COMFYUI = "http://192.168.1.200:8188"
STARSHIP_COMFYUI = "http://192.168.1.246:8188"
PORTRAITS_DIR = "/mnt/archie_brain/platform_v2/static/portraits"
DEFAULT_CHECKPOINT = "RealVisXL_V4.0.safetensors"
NEGATIVE_PROMPT = (
    "cartoon, anime, illustration, painting, blurry, low quality, deformed, "
    "disfigured, extra limbs, bad anatomy, watermark, text, logo, signature, "
    "frame, border, cropped, worst quality, jpeg artifacts, ugly, duplicate, "
    "morbid, mutilated, out of frame, mutation, poorly drawn face"
)

# DB connection
DB_HOST = "192.168.1.200"
DB_NAME = "archie"
DB_USER = "archie"
DB_PASS = os.environ.get("DB_PASSWORD", "")


def get_db():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
        cursor_factory=RealDictCursor
    )
    return conn


def get_agents(agent_id=None):
    """Fetch agents needing portraits."""
    conn = get_db()
    cur = conn.cursor()
    if agent_id:
        cur.execute("SELECT id, display_name, name, department FROM agents WHERE id = %s AND status = 'active'", (agent_id,))
    else:
        # Get agents without approved portraits
        cur.execute("""
            SELECT a.id, a.display_name, a.name, a.department
            FROM agents a
            LEFT JOIN agent_portraits ap ON ap.agent_id = a.id AND ap.approved = true
            WHERE a.status = 'active' AND ap.id IS NULL
            ORDER BY a.id
        """)
    agents = cur.fetchall()
    conn.close()
    return agents


def get_prompt_from_spec(agent_name):
    """Extract portrait prompt from the roster spec file."""
    spec_path = "/mnt/archie_brain/docs/superpowers/specs/2026-03-20-company-roster-design.md"
    try:
        with open(spec_path, 'r') as f:
            content = f.read()
        # Find the portrait prompt for this agent
        # Pattern: after the agent's name, find "Portrait Prompt:" line
        pattern = re.escape(agent_name) + r'.*?Portrait Prompt:\*\*\s*(.+?)(?:\n\n|\n-|\n#|\n\*\*|\Z)'
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            prompt = match.group(1).strip()
            # Clean up any markdown artifacts
            prompt = prompt.replace('\n', ' ').strip()
            return prompt
    except Exception as e:
        print(f"  Warning: Could not extract prompt from spec: {e}")
    return None


def build_default_prompt(agent):
    """Fallback prompt if spec doesn't have one."""
    name = agent['display_name'] or agent['name']
    return (
        f"professional corporate headshot, photorealistic, 8k, "
        f"studio lighting with soft rim light, dark navy-to-teal gradient background, "
        f"head and shoulders, centered composition, "
        f"person mid-30s, wearing professional business attire, "
        f"confident approachable expression, sharp focus"
    )


def get_available_checkpoints(comfyui_url):
    """List checkpoints available on a ComfyUI instance."""
    try:
        resp = urllib.request.urlopen(f"{comfyui_url}/object_info/CheckpointLoaderSimple", timeout=10)
        data = json.loads(resp.read())
        return data['CheckpointLoaderSimple']['input']['required']['ckpt_name'][0]
    except Exception as e:
        print(f"  Error checking {comfyui_url}: {e}")
        return []


def build_workflow(prompt, negative_prompt, checkpoint, seed=None):
    """Build ComfyUI API workflow for portrait generation."""
    if seed is None:
        seed = int(time.time() * 1000) % (2**32)

    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 30,
                "cfg": 7.0,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0]
            }
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": checkpoint
            }
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": 1024,
                "height": 1024,
                "batch_size": 1
            }
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt,
                "clip": ["4", 1]
            }
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": negative_prompt,
                "clip": ["4", 1]
            }
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            }
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "portrait",
                "images": ["8", 0]
            }
        }
    }
    return workflow


def queue_prompt(comfyui_url, workflow):
    """Queue a prompt on ComfyUI and return the prompt_id."""
    payload = json.dumps({"prompt": workflow}).encode('utf-8')
    req = urllib.request.Request(
        f"{comfyui_url}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        return data.get('prompt_id')
    except Exception as e:
        print(f"  Error queuing prompt: {e}")
        return None


def wait_for_completion(comfyui_url, prompt_id, timeout=300):
    """Wait for a queued prompt to complete."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(f"{comfyui_url}/history/{prompt_id}", timeout=10)
            data = json.loads(resp.read())
            if prompt_id in data:
                outputs = data[prompt_id].get('outputs', {})
                # Find the SaveImage node output
                for node_id, output in outputs.items():
                    if 'images' in output:
                        return output['images']
                return []
        except Exception:
            pass
        time.sleep(2)
    print(f"  Timeout waiting for {prompt_id}")
    return None


def download_image(comfyui_url, image_info, dest_path):
    """Download a generated image from ComfyUI."""
    filename = image_info['filename']
    subfolder = image_info.get('subfolder', '')
    img_type = image_info.get('type', 'output')
    url = f"{comfyui_url}/view?filename={filename}&subfolder={subfolder}&type={img_type}"
    try:
        urllib.request.urlretrieve(url, dest_path)
        return True
    except Exception as e:
        print(f"  Error downloading image: {e}")
        return False


def convert_to_webp(png_path, webp_path, quality=90):
    """Convert PNG to WebP for web optimization."""
    try:
        from PIL import Image
        img = Image.open(png_path)
        img.save(webp_path, 'WEBP', quality=quality)
        os.remove(png_path)
        return True
    except ImportError:
        # Pillow not installed — keep as PNG
        os.rename(png_path, webp_path.replace('.webp', '.png'))
        return False


def save_to_db(agent_id, image_path, prompt, seed, checkpoint):
    """Save portrait record to agent_portraits table."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO agent_portraits (agent_id, canonical_image_path, identity_prompt, face_seed, model_used, approved)
        VALUES (%s, %s, %s, %s, %s, true)
        ON CONFLICT (agent_id) DO UPDATE SET
            canonical_image_path = EXCLUDED.canonical_image_path,
            identity_prompt = EXCLUDED.identity_prompt,
            face_seed = EXCLUDED.face_seed,
            model_used = EXCLUDED.model_used,
            approved = true,
            updated_at = NOW()
    """, (agent_id, image_path, prompt, seed, checkpoint))
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Generate agent portraits via ComfyUI")
    parser.add_argument('--agent-id', type=int, help="Generate for specific agent ID")
    parser.add_argument('--checkpoint', default=DEFAULT_CHECKPOINT, help="SDXL checkpoint to use")
    parser.add_argument('--node', choices=['hub', 'starship', 'both'], default='hub', help="Which GPU to use")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be generated")
    parser.add_argument('--seed', type=int, help="Fixed seed for reproducibility")
    args = parser.parse_args()

    os.makedirs(PORTRAITS_DIR, exist_ok=True)

    # Check ComfyUI availability
    comfyui_url = HUB_COMFYUI
    if args.node == 'starship':
        comfyui_url = STARSHIP_COMFYUI

    print(f"ComfyUI: {comfyui_url}")
    print(f"Checkpoint: {args.checkpoint}")

    checkpoints = get_available_checkpoints(comfyui_url)
    if args.checkpoint not in checkpoints:
        print(f"ERROR: {args.checkpoint} not found on {comfyui_url}")
        print(f"Available: {checkpoints}")
        sys.exit(1)

    # Get agents
    agents = get_agents(args.agent_id)
    print(f"Agents to generate: {len(agents)}")

    if args.dry_run:
        for agent in agents:
            name = agent['display_name'] or agent['name']
            prompt = get_prompt_from_spec(name) or build_default_prompt(agent)
            print(f"\n  [{agent['id']}] {name}")
            print(f"  Prompt: {prompt[:100]}...")
        return

    # Generate portraits
    generated = 0
    failed = 0
    for i, agent in enumerate(agents):
        name = agent['display_name'] or agent['name']
        print(f"\n[{i+1}/{len(agents)}] Generating: {name} (id={agent['id']})")

        prompt = get_prompt_from_spec(name)
        if not prompt:
            prompt = build_default_prompt(agent)
            print("  Using default prompt (not found in spec)")

        seed = args.seed or int(time.time() * 1000 + agent['id']) % (2**32)
        workflow = build_workflow(prompt, NEGATIVE_PROMPT, args.checkpoint, seed)

        prompt_id = queue_prompt(comfyui_url, workflow)
        if not prompt_id:
            print("  FAILED to queue")
            failed += 1
            continue

        print(f"  Queued: {prompt_id}, waiting...")
        images = wait_for_completion(comfyui_url, prompt_id, timeout=600)

        if not images:
            print("  FAILED — no images returned")
            failed += 1
            continue

        # Download first image
        png_path = os.path.join(PORTRAITS_DIR, f"{agent['id']}.png")
        webp_path = os.path.join(PORTRAITS_DIR, f"{agent['id']}.webp")

        if download_image(comfyui_url, images[0], png_path):
            convert_to_webp(png_path, webp_path)
            final_path = webp_path if os.path.exists(webp_path) else png_path
            rel_path = f"/static/portraits/{os.path.basename(final_path)}"
            save_to_db(agent['id'], rel_path, prompt, seed, args.checkpoint)
            print(f"  DONE: {rel_path}")
            generated += 1
        else:
            failed += 1

    print(f"\n=== COMPLETE ===")
    print(f"Generated: {generated}")
    print(f"Failed: {failed}")
    print(f"Total agents: {len(agents)}")


if __name__ == "__main__":
    main()
