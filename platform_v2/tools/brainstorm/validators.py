"""Input validators for the Brainstorm module."""

MAX_TITLE_LENGTH = 200
MAX_GOAL_LENGTH = 500
MAX_CONTENT_LENGTH = 1000
MAX_CLUSTER_LENGTH = 100
MAX_TAGS = 10
MAX_TAG_LENGTH = 50


def _clean_required_string(value, field_name: str, max_length: int) -> str:
    if value is None:
        cleaned = ""
    elif isinstance(value, str):
        cleaned = value.strip()
    else:
        raise ValueError(f"{field_name} must be a string")
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or fewer")
    return cleaned


def _clean_optional_string(value, field_name: str, max_length: int) -> str | None:
    if value is None:
        cleaned = ""
    elif isinstance(value, str):
        cleaned = value.strip()
    else:
        raise ValueError(f"{field_name} must be a string")
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or fewer")
    return cleaned


def validate_title(value) -> str:
    return _clean_required_string(value, "title", MAX_TITLE_LENGTH)


def validate_goal(value) -> str | None:
    return _clean_optional_string(value, "goal", MAX_GOAL_LENGTH)


def validate_content(value) -> str:
    return _clean_required_string(value, "content", MAX_CONTENT_LENGTH)


def validate_cluster(value) -> str | None:
    return _clean_optional_string(value, "cluster", MAX_CLUSTER_LENGTH)


def validate_tags(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("tags must be a list")

    tags = []
    for tag in value:
        if not isinstance(tag, str):
            raise ValueError("tags must be strings")
        cleaned = tag.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_TAG_LENGTH:
            raise ValueError(f"tags must be {MAX_TAG_LENGTH} characters or fewer")
        tags.append(cleaned)

    if len(tags) > MAX_TAGS:
        raise ValueError(f"tags cannot include more than {MAX_TAGS} items")
    return tags


def validate_vote_delta(value) -> int:
    if isinstance(value, bool):
        raise ValueError("vote_delta must be +1 or -1")
    if isinstance(value, int):
        delta = value
    else:
        raise ValueError("vote_delta must be +1 or -1")
    if delta not in (-1, 1):
        raise ValueError("vote_delta must be +1 or -1")
    return delta
