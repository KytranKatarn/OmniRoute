"""
OCR Service for Family Tree module.
Tesseract OCR + LLM extraction via Bridge dispatch.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def ocr_document(file_path: str, language: str = "por+fra+eng") -> str:
    """
    Run Tesseract OCR on an image file.

    Args:
        file_path: Path to the image file.
        language: Tesseract language string (e.g. "por+fra+eng").

    Returns:
        Extracted text string, or empty string on error.
    """
    try:
        from PIL import Image
        import pytesseract

        image = Image.open(file_path)
        text = pytesseract.image_to_string(image, lang=language)
        return text.strip()
    except Exception as e:
        logger.error("ocr_document failed for %s: %s", file_path, e)
        return ""


def extract_structured_data(ocr_text: str, document_type: str = "unknown") -> dict:
    """
    Use Bridge dispatch to extract structured genealogical data from OCR text.

    Args:
        ocr_text: Raw text from OCR.
        document_type: Hint about document type (e.g. "birth_certificate", "marriage_record").

    Returns:
        Dict with extracted fields, or empty dict on error.
    """
    if not ocr_text:
        return {}

    try:
        from bridge_dispatcher import dispatch

        system_prompt = (
            "You are a genealogy document analyst. Extract structured data from OCR text of historical documents. "
            "Always respond with valid JSON only — no explanations, no markdown, just the JSON object."
        )

        prompt = (
            f"Extract genealogical information from this OCR text of a {document_type} document.\n\n"
            f"OCR TEXT:\n{ocr_text}\n\n"
            "Return a JSON object with these fields:\n"
            "- persons: list of objects, each with: first_name, last_name, role, birth_date, birth_place, "
            "death_date, death_place, gender\n"
            "- event_type: type of event documented (e.g. birth, marriage, death, baptism)\n"
            "- event_date: date of the event (string)\n"
            "- event_place: place where the event occurred\n"
            "- notes: any other relevant information\n\n"
            "Use null for missing fields. Respond with JSON only."
        )

        result = dispatch(
            prompt=prompt,
            capability="text_analysis",
            prefer_agent="quill",
            system_prompt=system_prompt,
        )

        if not result.success:
            logger.error("Bridge dispatch failed for extract_structured_data: %s", result.response)
            return {}

        response_text = result.response.strip()

        # Strip markdown code block wrappers if present
        response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
        response_text = re.sub(r"\s*```$", "", response_text)
        response_text = response_text.strip()

        return json.loads(response_text)

    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON from LLM response: %s", e)
        return {}
    except Exception as e:
        logger.error("extract_structured_data failed: %s", e)
        return {}


def process_document(
    file_path: str,
    document_type: str = "unknown",
    language: str = "por+fra+eng",
) -> tuple:
    """
    Full OCR + extraction pipeline.

    Args:
        file_path: Path to the image file.
        document_type: Hint about document type.
        language: Tesseract language string.

    Returns:
        Tuple of (ocr_text: str, extracted_data: dict).
    """
    ocr_text = ocr_document(file_path, language=language)
    extracted_data = extract_structured_data(ocr_text, document_type=document_type)
    return ocr_text, extracted_data
