"""
A.R.C.H.I.E. Shared Text Utilities
Reusable text processing functions for LLM pipelines.
"""


def smart_truncate(
    text: str,
    max_length: int = 12000,
    head_ratio: float = 0.3,
    tail_ratio: float = 0.5,
    separator: str = "\n\n...[truncated]...\n\n",
) -> str:
    """
    Intelligently truncate text for LLM context windows.

    Keeps first head_ratio + last tail_ratio of content.
    Solutions and conclusions tend to be at the end, so tail_ratio > head_ratio.

    Args:
        text: Input text to truncate
        max_length: Maximum character length (default 12000)
        head_ratio: Fraction of max_length to keep from start (default 0.3)
        tail_ratio: Fraction of max_length to keep from end (default 0.5)
        separator: Text inserted between head and tail (default truncation marker)

    Returns:
        Truncated text, or original text if under max_length
    """
    if not text or len(text) <= max_length:
        return text

    head_len = int(max_length * head_ratio)
    tail_len = int(max_length * tail_ratio)

    # Ensure we don't exceed max_length including separator
    available = max_length - len(separator)
    if head_len + tail_len > available:
        total = head_len + tail_len
        head_len = int(available * head_ratio / (head_ratio + tail_ratio))
        tail_len = available - head_len

    head = text[:head_len]
    tail = text[-tail_len:]

    return head + separator + tail


def estimate_tokens(text: str) -> int:
    """
    Rough token estimate (~4 chars per token for English text).
    Good enough for context window budgeting.
    """
    return len(text) // 4


def truncate_for_model(text: str, model_context: int = 8192) -> str:
    """
    Truncate text to fit within a model's context window.

    Args:
        text: Input text
        model_context: Model's context window in tokens (default 8192)

    Returns:
        Truncated text that fits within ~75% of context window
        (leaving room for system prompt + response)
    """
    target_tokens = int(model_context * 0.75)
    target_chars = target_tokens * 4

    return smart_truncate(text, max_length=target_chars)
