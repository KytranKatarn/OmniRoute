"""
AutoShorts Slideshow Generator
==============================
Builds a 15-30 second social media video from gallery images:
- Ken Burns slow zoom on each image (~4-5s each)
- Inspirational quote text overlay with fade-in
- Background music mixed underneath
- Smooth crossfade transitions between images
- Output: MP4 (1080x1080 square for LinkedIn, or 1080x1920 portrait for mobile)
"""

import logging
import os
import subprocess
import tempfile
import uuid

logger = logging.getLogger(__name__)

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VIDEO_OUTPUT_DIR = os.path.join(_APP_ROOT, "static", "social_videos")
MUSIC_DIR = os.path.join(_APP_ROOT, "static", "media", "music")

# Seconds each image is shown (Ken Burns effect duration)
SECONDS_PER_IMAGE = 5
TRANSITION_DURATION = 0.8
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1080
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def generate_slideshow(
    image_paths: list,
    quote_text: str = "",
    title: str = "",
    audio_mode: str = "music",
    target_duration: int = 25,
) -> dict:
    """
    Generate an AutoShorts-style slideshow video.

    Args:
        image_paths: list of absolute file paths to images
        quote_text: inspirational quote shown as text overlay
        title: optional title shown briefly at start
        audio_mode: 'music' | 'silent'
        target_duration: target video length in seconds

    Returns:
        dict with 'success', 'video_path', 'thumbnail_path' on success
        or 'success': False, 'error' on failure
    """
    if not image_paths:
        return {"success": False, "error": "No images provided"}

    os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)

    uid = uuid.uuid4().hex[:12]
    output_path = os.path.join(VIDEO_OUTPUT_DIR, f"sv_{uid}.mp4")
    thumb_path = os.path.join(VIDEO_OUTPUT_DIR, f"sv_{uid}_thumb.jpg")

    # Compute seconds per image based on target duration and image count
    n = len(image_paths)
    spi = max(3, min(6, target_duration // n))

    try:
        _build_video(image_paths, quote_text, title, audio_mode, output_path, spi)
        _extract_thumbnail(output_path, thumb_path)
        return {
            "success": True,
            "video_path": output_path,
            "thumbnail_path": thumb_path if os.path.exists(thumb_path) else None,
        }
    except Exception as exc:
        logger.exception("Slideshow generation failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _build_video(image_paths, quote_text, title, audio_mode, output_path, spi):
    n = len(image_paths)
    total_duration = n * spi

    with tempfile.TemporaryDirectory() as tmpdir:
        # Step 1: resize all images to square and write as numbered PNGs
        resized = []
        for i, src in enumerate(image_paths):
            dst = os.path.join(tmpdir, f"img{i:03d}.png")
            _resize_image(src, dst)
            resized.append(dst)

        # Step 2: build ffmpeg filter_complex for Ken Burns + crossfade
        filter_parts, inputs, last_label = _build_filter_complex(resized, spi, quote_text, title)

        # Step 3: assemble ffmpeg command
        cmd = ["ffmpeg", "-y"]

        # Image inputs (loop each for spi+transition seconds)
        for path in resized:
            cmd += ["-loop", "1", "-t", str(spi + TRANSITION_DURATION), "-i", path]

        # Music input
        music_file = _pick_music()
        if audio_mode == "music" and music_file:
            cmd += ["-i", music_file]
            has_audio = True
        else:
            has_audio = False

        # Filter complex
        cmd += ["-filter_complex", "\n".join(filter_parts)]
        cmd += ["-map", f"[{last_label}]"]

        if has_audio:
            music_idx = len(resized)
            cmd += [
                "-map",
                f"{music_idx}:a",
                "-af",
                f"afade=t=out:st={max(0, total_duration - 2)}:d=2,volume=0.4",
            ]

        cmd += [
            "-t",
            str(total_duration),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "128k"]

        cmd.append(output_path)

        logger.info("Running ffmpeg slideshow: %d images, %ds each, total %ds", n, spi, total_duration)
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[-2000:]
            raise RuntimeError(f"ffmpeg failed (rc={result.returncode}): {err}")


def _resize_image(src, dst):
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            src,
            "-vf",
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black",
            dst,
        ],
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Image resize failed for {src}: {result.stderr.decode(errors='replace')[-500:]}")


def _build_filter_complex(resized, spi, quote_text, title):
    """
    Build ffmpeg filter_complex strings for Ken Burns effect + crossfade transitions + text.
    Returns (filter_parts list, last_label string).
    """
    n = len(resized)
    filters = []
    inputs = []

    # Ken Burns zoom on each image
    for i in range(n):
        total_frames = int((spi + TRANSITION_DURATION) * 25)  # 25fps
        zoom_dir = "in" if i % 2 == 0 else "out"
        if zoom_dir == "in":
            zoom_expr = "min(zoom+0.0008,1.12)"
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"
        else:
            zoom_expr = "if(eq(on,1),1.12,max(zoom-0.0008,1.0))"
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"

        kb_filter = (
            f"[{i}:v]"
            f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}'"
            f":d={total_frames}:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:fps=25,"
            f"setpts=PTS-STARTPTS"
            f"[kb{i}]"
        )
        filters.append(kb_filter)

    # Crossfade transitions between Ken Burns clips
    if n == 1:
        last_label = "kb0"
    else:
        # Chain xfades: kb0 + kb1 → xf0, xf0 + kb2 → xf1, ...
        prev_label = "kb0"
        for i in range(1, n):
            offset = i * spi - TRANSITION_DURATION / 2
            out_label = f"xf{i - 1}"
            xf = (
                f"[{prev_label}][kb{i}]"
                f"xfade=transition=fade:duration={TRANSITION_DURATION}:offset={offset:.2f}"
                f"[{out_label}]"
            )
            filters.append(xf)
            prev_label = out_label
        last_label = f"xf{n - 2}"

    # Text overlay: quote
    if quote_text:
        safe_quote = _escape_ffmpeg_text(quote_text[:120])
        total_dur = n * spi
        fade_start = 1.0
        fade_end = total_dur - 1.5

        # Wrap long quotes at ~40 chars
        words = safe_quote.split(" ")
        lines, current = [], []
        for word in words:
            current.append(word)
            if len(" ".join(current)) > 38:
                lines.append(" ".join(current[:-1]))
                current = [word]
        if current:
            lines.append(" ".join(current))
        wrapped = r"\n".join(lines[:4])

        # Semi-transparent black bar behind text
        bar_h = min(180, 60 + len(lines) * 40)
        bar_y = OUTPUT_HEIGHT - bar_h - 60

        text_filter = (
            f"[{last_label}]"
            f"drawbox=x=0:y={bar_y}:w={OUTPUT_WIDTH}:h={bar_h}:color=black@0.55:t=fill,"
            f"drawtext=fontfile='{FONT_PATH}'"
            f":text='{wrapped}'"
            f":fontcolor=white@1.0"
            f":fontsize=36"
            f":x=(w-text_w)/2"
            f":y={bar_y + 20}"
            f":line_spacing=8"
            f":alpha='if(between(t,{fade_start},{fade_start}+0.6),(t-{fade_start})/0.6,"
            f"if(between(t,{fade_end},{fade_end}+0.6),1-(t-{fade_end})/0.6,1))'"
            f"[texted]"
        )
        filters.append(text_filter)
        last_label = "texted"

    return filters, list(range(n)), last_label


def _escape_ffmpeg_text(text):
    return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace("[", "\\[").replace("]", "\\]")


def _pick_music():
    """Return path to a random music file from MUSIC_DIR, or None."""
    if not os.path.isdir(MUSIC_DIR):
        return None
    tracks = [
        os.path.join(MUSIC_DIR, f)
        for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith((".mp3", ".m4a", ".ogg", ".wav", ".aac"))
    ]
    if not tracks:
        return None
    import random

    return random.choice(tracks)


def _extract_thumbnail(video_path, thumb_path):
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vframes", "1", "-vf", "scale=480:-1", thumb_path],
            capture_output=True,
            timeout=30,
        )
    except Exception as exc:
        logger.warning("Thumbnail extraction failed: %s", exc)
