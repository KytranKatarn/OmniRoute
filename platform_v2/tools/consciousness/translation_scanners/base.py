"""Base contract for translation scanners.

Each scanner reads a source (HTML dir or existing translations row)
and yields ScannerResult objects. The orchestrator UPSERTs these into
translation_gaps.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class ScannerResult:
    """One gap row pending upsert into translation_gaps."""

    source: str
    gap_type: str  # "missing" | "untagged" | "quality_suspect"
    language: Optional[str] = None
    key: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    snippet: Optional[str] = None
    suggested_key: Optional[str] = None
    confidence: Optional[float] = None


class BaseScanner(ABC):
    """Scanner contract. scan() yields ScannerResult."""

    gap_type: str = ""

    @abstractmethod
    def scan(self) -> Iterator[ScannerResult]:
        """Yield gap rows. Must not write to DB (orchestrator handles that)."""
        raise NotImplementedError
