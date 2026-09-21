"""Name the model behind a GPU process, exactly, from Ollama's own manifests.

WHY
---
``/api/ps`` says WHICH models are resident and how much VRAM each holds, but
never which CARD. ``nvidia-smi --query-compute-apps`` says which card a PROCESS
is on, but only knows PIDs. Joining them by comparing VRAM figures works only
when the numbers differ: measured on this hub, ``qwen2.5:7b`` and
``qwen2.5-coder:7b`` both report ``size_vram`` 4.92 GB, so byte-matching cannot
tell them apart and must refuse (see tools/department_hq/services/gpu_residency).

The authoritative join is the one Ollama itself uses. An ``ollama runner``
process is started with ``--model <path-to-weights-blob>``, and every model
manifest names its weights layer. So:

    pid -> /proc/<pid>/cmdline -> weights blob -> manifest -> model name

This module is the pure half of that: no /proc, no nvidia-smi, no subprocess --
just the manifest index and the resolution rules, so both the host exporter and
the test suite can use it. The host exporter (scripts/gpu_state_exporter.py)
supplies the process facts, because only the host can read ``/proc``:
``archie_platform`` has its own PID namespace and cannot resolve a host PID.

THE TRAP THIS MODULE EXISTS TO AVOID
------------------------------------
A weights blob identifies WEIGHTS, not a model tag. Many tags share one blob --
a Modelfile variant reuses its base's weights. Measured here: **7 of 19** weight
blobs are shared, including::

    sha256-...  ->  {qwen2.5:7b, vivid:latest, weave:latest}
    sha256-...  ->  {qwen2.5:1.5b, qwen25-classify:latest}

So the blob alone would have labelled a resident ``qwen2.5:7b`` as
``weave:latest`` -- a confident falsehood of exactly the kind this panel keeps
being fixed for. The fix is to intersect the blob's candidates with the set of
models ``/api/ps`` reports ACTUALLY resident. On the live hub that collapsed all
three processes to a unique name (3 exact, 0 ambiguous, 0 unresolved), including
a ``mistral:7b`` spanning both cards that byte-matching could never have named.

When the intersection still leaves more than one candidate, this returns the
CANDIDATES rather than a pick. Callers must render that as "one of these", never
choose for the reader.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Iterable, List, Optional, Set

# The layer mediaType that carries a model's weights. Ollama writes several
# layers per manifest (params, template, license); only this one is the blob a
# runner is started with.
_WEIGHTS_MEDIA_TYPE = "application/vnd.ollama.image.model"

# Ollama's on-disk layout: manifests/<registry>/<namespace>/<model>/<tag>
_MANIFEST_DEPTH = 4


def manifest_index(models_root: str) -> Dict[str, Set[str]]:
    """Map weights-blob filename -> the set of model names built on it.

    ``models_root`` is ``OLLAMA_MODELS`` (``/mnt/llm_drive/ollama/models`` on the
    hub). Returns blob names in on-disk form (``sha256-<hex>``, the digest with
    ``:`` replaced by ``-``) because that is what a runner's ``--model`` path
    ends with.

    Never raises: an unreadable or malformed manifest is skipped, because a
    single bad file must not blind the whole index.
    """
    index: Dict[str, Set[str]] = {}
    root = os.path.join(models_root, "manifests")
    if not os.path.isdir(root):
        return index
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            path = os.path.join(dirpath, fname)
            rel = os.path.relpath(path, root).split(os.sep)
            if len(rel) < _MANIFEST_DEPTH:
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    manifest = json.load(fh)
            except (OSError, ValueError):
                continue
            if not isinstance(manifest, dict):
                continue
            namespace, model, tag = rel[-3], rel[-2], rel[-1]
            # `library` is Ollama's default namespace and is not part of the
            # name a user types, so `library/mistral/7b` is `mistral:7b`.
            name = f"{model}:{tag}" if namespace == "library" else f"{namespace}/{model}:{tag}"
            for layer in manifest.get("layers") or []:
                if not isinstance(layer, dict):
                    continue
                if layer.get("mediaType") != _WEIGHTS_MEDIA_TYPE:
                    continue
                digest = (layer.get("digest") or "").replace(":", "-")
                if digest:
                    index.setdefault(digest, set()).add(name)
    return index


def blob_from_cmdline(cmdline: str) -> Optional[str]:
    """The weights-blob filename from an ``ollama runner`` command line.

    Accepts the NUL-joined /proc form already decoded to spaces. Returns None
    when the line carries no ``--model``, which is how a non-runner CUDA process
    (ComfyUI, say) is correctly left unnamed rather than guessed at.
    """
    if not cmdline:
        return None
    parts = cmdline.split()
    for i, tok in enumerate(parts):
        if tok == "--model" and i + 1 < len(parts):
            return os.path.basename(parts[i + 1])
        if tok.startswith("--model="):
            return os.path.basename(tok.split("=", 1)[1])
    return None


def resolve_model_name(
    blob: Optional[str],
    index: Dict[str, Set[str]],
    resident: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    """Name the model for a weights blob, narrowed by what is actually resident.

    Returns ``{"model": str|None, "candidates": [str], "exact": bool}``.

    ``resident`` is the set of names ``/api/ps`` reports loaded. It is what makes
    this exact: 7 of 19 blobs on this hub back several tags, so without it a
    resident ``qwen2.5:7b`` resolves to ``weave:latest`` just as plausibly.
    Passing None skips narrowing and will therefore report ambiguity honestly
    rather than inventing certainty.
    """
    if not blob:
        return {"model": None, "candidates": [], "exact": False}
    candidates = set(index.get(blob) or set())
    if not candidates:
        return {"model": None, "candidates": [], "exact": False}
    if resident is not None:
        narrowed = candidates & set(resident)
        # An empty intersection means the blob is real but nothing matching is
        # resident -- a racing load/unload. Keep the wider candidate set rather
        # than reporting nothing; the caller shows it as ambiguous.
        if narrowed:
            candidates = narrowed
    ordered: List[str] = sorted(candidates)
    if len(ordered) == 1:
        return {"model": ordered[0], "candidates": ordered, "exact": True}
    return {"model": None, "candidates": ordered, "exact": False}
