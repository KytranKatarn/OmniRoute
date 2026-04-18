"""Tagged scanner — wraps the existing scan_and_seed_keys flow.

Emits ScannerResult rows for (key, language) pairs that exist as EN
source rows but are missing in other languages.

Queries `translations.source_label` (added by migration 321). The legacy
`translations.source` column tracks origin ('ai_generated' | 'human_edited'
| 'imported') and is not the product/site label.
"""

from __future__ import annotations

from typing import Iterator

from database import get_db_cursor

from .base import BaseScanner, ScannerResult


TARGET_LANGS = ("fr", "es", "pt", "de", "zh", "ar", "he")


class TaggedScanner(BaseScanner):
    gap_type = "missing"

    def __init__(self, source: str):
        self.source = source

    def scan(self) -> Iterator[ScannerResult]:
        with get_db_cursor() as (_conn, cur):
            # Get all English keys for this product/site.
            cur.execute(
                """SELECT key FROM translations
                   WHERE source_label = %s AND language = 'en'""",
                (self.source,),
            )
            en_keys = [r["key"] for r in cur.fetchall()]

            # For each target language, find missing translations
            for lang in TARGET_LANGS:
                if not en_keys:
                    continue
                cur.execute(
                    """SELECT key FROM translations
                       WHERE source_label = %s
                         AND language = %s
                         AND key = ANY(%s)""",
                    (self.source, lang, en_keys),
                )
                have = {r["key"] for r in cur.fetchall()}
                missing = set(en_keys) - have
                for key in missing:
                    yield ScannerResult(
                        source=self.source,
                        gap_type=self.gap_type,
                        language=lang,
                        key=key,
                    )
