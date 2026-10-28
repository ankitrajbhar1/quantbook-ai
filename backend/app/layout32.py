"""Phase 3.2.1: read-only, coordinate-aware PDF text extraction.

Conservative two-column detection. Never infer heading/formula associations from
spatial proximity alone; expose original bounding boxes for visual review.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf


@dataclass
class LayoutBlock:
    text: str
    bbox: list[float]
    original_order: int
    column: str = "full"
    kind: str = "text"


def _valid_box(box, width, height):
    return (len(box) == 4 and 0 <= box[0] < box[2] <= width + 1
            and 0 <= box[1] < box[3] <= height + 1)


def extract_page_layout(page):
    """Return auditable blocks, a conservative reading order and diagnostics."""
    width, height = float(page.rect.width), float(page.rect.height)
    raw = page.get_text("dict", sort=False).get("blocks", [])
    blocks = []
    for i, item in enumerate(raw):
        if item.get("type") != 0:
            continue
        # PyMuPDF may merge left/right text on the same horizontal line
        # into one block. Use line boxes as atomic layout elements.
        for j, line in enumerate(item.get("lines", [])):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            bbox = [float(x) for x in line.get("bbox", [])]
            if text and _valid_box(bbox, width, height):
                blocks.append(LayoutBlock(text, bbox, i * 10000 + j))

    midpoint = width / 2
    margin = width * 0.035
    left = [b for b in blocks if b.bbox[2] < midpoint - margin]
    right = [b for b in blocks if b.bbox[0] > midpoint + margin]
    # Detect two columns only when there is meaningful text on both sides.
    # Wide diagrams/headers are retained separately; don't pretend they belong
    # to either column. Avoid assigning associations to formulas or captions.
    left_chars = sum(len(b.text) for b in left)
    right_chars = sum(len(b.text) for b in right)
    two_columns = (len(left) >= 2 and len(right) >= 2
                   and left_chars >= 80 and right_chars >= 80)

    if two_columns:
        for b in left:
            b.column = "left"
        for b in right:
            b.column = "right"
        # Split full-width elements into before/after groups around column
        # body. Embedded spanning blocks remain explicitly marked ambiguous.
        columns = left + right
        top = min(b.bbox[1] for b in columns)
        bottom = max(b.bbox[3] for b in columns)
        headers = [b for b in blocks if b.column == "full" and b.bbox[3] <= top]
        footers = [b for b in blocks if b.column == "full" and b.bbox[1] >= bottom]
        middle = [b for b in blocks if b.column == "full" and b not in headers and b not in footers]
        ordered = (sorted(headers, key=lambda b: (b.bbox[1], b.bbox[0]))
                   + sorted(left, key=lambda b: (b.bbox[1], b.bbox[0]))
                   + sorted(right, key=lambda b: (b.bbox[1], b.bbox[0]))
                   + sorted(middle, key=lambda b: (b.bbox[1], b.bbox[0]))
                   + sorted(footers, key=lambda b: (b.bbox[1], b.bbox[0])))
    else:
        ordered = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))

    return {
        "page_width": width,
        "page_height": height,
        "layout": "two_column_candidate" if two_columns else "single_or_complex",
        "warning": ("Reading order is heuristic; verify diagrams, formulas, and "
                    "method-to-equation associations against the PDF."),
        "blocks": [asdict(b) for b in ordered],
        "reading_text": "\n\n".join(b.text for b in ordered),
        "diagnostics": {
            "block_count": len(blocks),
            "left_blocks": len(left),
            "right_blocks": len(right),
            "ambiguous_full_width_blocks": sum(b.column == "full" for b in blocks),
            "original_order_changed": [b.original_order for b in ordered] != [b.original_order for b in blocks],
        },
    }


def extract_pdf_page(pdf_path: str | Path, page_number: int):
    if page_number < 1:
        raise ValueError("page_number must be >= 1")
    with pymupdf.open(str(pdf_path)) as pdf:
        if pdf.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if page_number > len(pdf):
            raise ValueError("Page not found")
        result = extract_page_layout(pdf[page_number - 1])
    result["page_number"] = page_number
    return result
