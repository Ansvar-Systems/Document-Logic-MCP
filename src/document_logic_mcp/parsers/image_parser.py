"""Image parser using OCR (pytesseract)."""

import logging
from pathlib import Path

from .base import BaseParser, ParseResult, Section

logger = logging.getLogger(__name__)


class ImageParser(BaseParser):
    """Parser for image files (.png, .jpg, .jpeg, .tiff, .tif, .bmp, .gif, .webp).

    Uses Tesseract OCR via pytesseract to extract text from images.
    """

    def parse(self, file_path: Path) -> ParseResult:
        import pytesseract
        from PIL import Image

        img = Image.open(file_path)

        # Convert to RGB if necessary (e.g., RGBA, palette mode)
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")

        # Run OCR
        text = pytesseract.image_to_string(img).strip()

        if not text:
            sections = [Section(
                title="Image (no text detected)",
                content="OCR did not detect any readable text in this image.",
            )]
        else:
            # Try to split into sections by detected headings (ALL-CAPS lines)
            sections = self._detect_sections(text)
            if not sections:
                sections = [Section(title="OCR Text", content=text)]

        # Get OCR confidence data
        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in data["conf"] if int(c) >= 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        except Exception:
            avg_confidence = None

        metadata = {
            "parser": "pytesseract",
            "image_size": f"{img.width}x{img.height}",
            "image_mode": img.mode,
        }
        if avg_confidence is not None:
            metadata["ocr_confidence"] = round(avg_confidence, 1)

        return ParseResult(
            filename=file_path.name,
            sections=sections,
            raw_text=text,
            page_count=1,
            metadata=metadata,
        )

    @staticmethod
    def _detect_sections(text: str) -> list[Section]:
        """Simple section detection from OCR output."""
        lines = text.splitlines()
        sections: list[Section] = []
        current_title: str | None = None
        current_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            # ALL-CAPS short lines as headings
            if (
                stripped
                and stripped == stripped.upper()
                and stripped != stripped.lower()
                and len(stripped.split()) <= 8
                and len(stripped) < 100
            ):
                if current_title is not None or current_lines:
                    sections.append(Section(
                        title=current_title or "Text",
                        content="\n".join(current_lines).strip(),
                    ))
                current_title = stripped
                current_lines = []
            else:
                current_lines.append(line)

        if current_title is not None or current_lines:
            sections.append(Section(
                title=current_title or "Text",
                content="\n".join(current_lines).strip(),
            ))

        # Only use if we found real headings
        if sum(1 for s in sections if s.title != "Text") >= 2:
            return sections
        return []
