from pathlib import Path
import inspect

from tools.media_studio.services.portrait_service import (
    _apply_corporate_brand,
    _portrait_negative_prompt,
    generate_canonical,
    generate_fanout,
    generate_variant,
)


def test_corporate_brand_is_added_once():
    prompt = _apply_corporate_brand("professional portrait")
    assert "Kytran Empowerment RAM mark" in prompt
    assert "background-only" in prompt
    assert _apply_corporate_brand(prompt) == prompt


def test_portrait_negative_prompt_allows_subtle_background_brand():
    negative = _portrait_negative_prompt()
    assert "large logo" in negative
    assert "logo over face" in negative
    assert "watermark" not in negative


def test_generation_paths_apply_corporate_brand():
    for function in (generate_canonical, generate_variant, generate_fanout):
        assert "_apply_corporate_brand" in inspect.getsource(function)


def test_portrait_auto_approval_job_is_removed():
    source = (Path(__file__).resolve().parents[1] / "services" / "fleet_jobs.py").read_text()
    assert "portrait_auto_approve" not in source
