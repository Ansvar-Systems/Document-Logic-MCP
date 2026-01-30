"""Base parser interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path


@dataclass
class Section:
    """Document section."""
    title: str
    content: str
    page_start: Optional[int] = None
    page_end: Optional[int] = None


@dataclass
class ParseResult:
    """Result of document parsing."""
    filename: str
    sections: List[Section]
    raw_text: str
    page_count: int
    metadata: dict


class BaseParser(ABC):
    """Base class for document parsers."""

    @abstractmethod
    def parse(self, file_path: Path) -> ParseResult:
        """Parse document and return structured result."""
        pass
