"""Regression tests for services.model_sizes — the footprint table that decides placement.

THE BUG THESE PIN (measured 2026-09-07):

`can_node_run_model()` reads `model_sizes.lookup()` to decide which node may run a
model. Only 19 models had MEASURED entries; the other 21 in active use fell through
to a `params * 1.3` regex that FABRICATES a number, and nothing distinguished the
guess from a measurement.

Measured overstatements, real on-disk size (`ollama list`) vs what was guessed:

    arctic-embed-cpu      0.218 GB  ->  8.0   =  37x   (banned from the CPU nodes)
    gemma3:12b            8.1   GB  -> 15.6   =   2x   (CPU-demoted into failure;
                                                        this is what made the whole
                                                        translate capability look broken)
    qwen3-coder:30b      18.0   GB  -> 39.0   =   2x   (never dispatched)
    deepseek-coder-v2    8.9    GB  -> 20.8   =   2x   (never dispatched)
    engine/archie:7b      4.7   GB  ->  9.1   =   2x   (excluded from the Runabout)

Two MoE coder models sat pulled-but-unusable for months because of this.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_model_footprints.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import model_sizes as ms  # noqa: E402

# Real on-disk sizes measured from `ollama list` on the hub's HOST ollama, 2026-09-07.
# These are the models the platform actually has. If a future `ollama pull` adds one,
# it belongs here AND in _TABLE.
MEASURED_DISK_GB = {
    "qwen2.5:7b": 4.7,
    "qwen2.5-coder:7b": 4.7,
    "mistral:7b": 4.4,
    "gemma3:12b": 8.1,
    "gemma2:9b": 5.4,
    "llama3.2:3b": 2.0,
    "qwen2.5:1.5b": 0.986,
    "dolphin3:latest": 4.9,
    "dolphin3-8k:latest": 4.9,
    "qwen3:8b": 5.2,
    "aya-expanse:8b": 5.1,
    "qwen3-coder:30b": 18.0,
    "deepseek-coder-v2:16b": 8.9,
    "phi4:14b": 9.1,
    "qwen2.5vl:7b": 6.0,
    "minicpm-v:latest": 5.5,
    "moondream:latest": 1.7,
    "translategemma:4b": 3.3,
    "archie:7b": 4.7,
    "arctic-embed-cpu:latest": 0.218,
}


def test_every_installed_model_has_a_measured_entry():
    """No model we actually have may fall through to the fabricating regex."""
    missing = []
    for name in MEASURED_DISK_GB:
        if name in ms._TABLE:
            continue
        if name.split(":")[0] in ms._TABLE:
            continue
        missing.append(name)
    assert not missing, (
        "these installed models have NO measured footprint and will be sized by the "
        f"params*1.3 regex, which drives placement: {missing}. "
        "Add measured _TABLE entries (`ollama list` gives on-disk size)."
    )


def test_footprint_is_never_wildly_larger_than_the_file_on_disk():
    """A footprint may exceed disk size (KV cache, activations) but not absurdly.

    The regex produced 8.0GB for a 218MB model. Anything above ~2.5x disk plus a
    fixed 1.5GB of overhead is a fabrication, not an estimate.
    """
    offenders = []
    for name, disk in MEASURED_DISK_GB.items():
        f = ms.lookup(name)
        if f.vram_gb == 0.0:  # CPU-tier / cloud entries are declared, not derived
            continue
        ceiling = disk * 2.5 + 1.5
        if f.vram_gb > ceiling:
            offenders.append(f"{name}: disk={disk}GB vram={f.vram_gb}GB (ceiling {ceiling:.1f})")
    assert not offenders, "footprints implausibly larger than the model file: " + "; ".join(offenders)


def test_footprint_is_never_smaller_than_the_file_on_disk():
    """The opposite failure: under-sizing would place a model where it cannot load.

    Weights must fit, so vram >= disk for any GPU-tier model. This is the guard that
    stops someone 'fixing' an over-estimate by swinging too far the other way.
    """
    offenders = []
    for name, disk in MEASURED_DISK_GB.items():
        f = ms.lookup(name)
        if f.vram_gb == 0.0:  # CPU-tier by declaration
            continue
        if f.vram_gb < disk:
            offenders.append(f"{name}: disk={disk}GB but vram={f.vram_gb}GB")
    assert not offenders, "footprints SMALLER than the weights on disk: " + "; ".join(offenders)


def test_the_two_headline_regressions_stay_fixed():
    """Explicit guards on the two that caused real damage."""
    embed = ms.lookup("arctic-embed-cpu:latest")
    assert embed.vram_gb <= 1.0, (
        f"arctic-embed-cpu is 218MB on disk; got {embed.vram_gb}GB VRAM. At 8.0 it was "
        "banned from every CPU node, and a fleet.md hardware rule was written around "
        "that fabricated 16GB RAM figure."
    )
    assert embed.ram_gb <= 2.0, f"arctic-embed-cpu RAM should be ~1GB, got {embed.ram_gb}"

    g3 = ms.lookup("gemma3:12b")
    assert g3.vram_gb <= 12.0, (
        f"gemma3:12b is 8.1GB on disk and MUST fit the hub's 12GB TITAN X on one card; "
        f"got {g3.vram_gb}GB. The 15.6 guess is what CPU-demoted it into failure."
    )


def test_unknown_model_still_returns_a_usable_footprint_and_does_not_raise():
    """The fallback must stay fail-SAFE — refusing to size an unknown model would
    block placement entirely. It now logs a warning; verify it does not explode.

    (This test exists because the warning was added referencing a `logger` that the
    module did not define — it would have raised NameError on the first unknown model.)
    """
    f = ms.lookup("some-model-nobody-has-heard-of:13b")
    assert f.vram_gb > 0 and f.ram_gb > 0

    f2 = ms.lookup("weird-name-with-no-size")
    assert f2.vram_gb > 0 and f2.ram_gb > 0

    assert ms.lookup("") is not None


def test_fallback_warns_so_an_unknown_model_is_never_silent(caplog):
    """A fabricated footprint must announce itself — silence is how this went
    unnoticed across 21 models."""
    import logging

    with caplog.at_level(logging.WARNING, logger="services.model_sizes"):
        ms.lookup("totally-unknown-model:13b")
    assert any(
        "NO MEASURED FOOTPRINT" in r.message or "NO MEASURED FOOTPRINT" in r.getMessage() for r in caplog.records
    ), "the regex fallback must log a warning naming the model"
