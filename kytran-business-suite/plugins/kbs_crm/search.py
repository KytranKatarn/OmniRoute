"""CRM search condition builder for customer list filtering."""


def build_search_conditions(search=None, segment_id=None) -> tuple:
    """Build SQL WHERE conditions for CRM customer search.

    Args:
        search: Text to search across name, email, company (ILIKE).
        segment_id: Filter to customers in this segment.

    Returns:
        Tuple of (list[str] conditions, list params).
    """
    conditions = []
    params = []

    if search:
        conditions.append(
            "(c.name ILIKE %s OR c.email ILIKE %s OR c.company ILIKE %s)"
        )
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])

    if segment_id is not None:
        conditions.append(
            "c.id IN (SELECT customer_id FROM crm_segment_members WHERE segment_id = %s)"
        )
        params.append(segment_id)

    return (conditions, params)
