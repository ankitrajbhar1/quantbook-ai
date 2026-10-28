"""Phase 3.3: conservative, read-only PDF equation and table inspection."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import Document

router = APIRouter(prefix="/api/v1/phase33", tags=["Phase 3.3 - Equations and tables"])

# Assignment/equality is a stronger signal than a mention of a model or statistic.
EQUATION = re.compile(r"(?:=|[≤≥≈≠∑∫√]|(?<!\w)[±](?!\w))")
MATH_SYMBOL = re.compile(r"[=+−\-*/^αβγθφσμλ∑∫√≤≥≈≠]")
PLOT_MARKER = re.compile(r"^[\sGg•·.oOxX*+\-0-9]+$")
FRACTION_DENOM = re.compile(r"^[\s\dTtpqk()+−\-*/.]+$")
HEADING = re.compile(r"^(?:corrected AIC|information criteria|bayesian information criterion)\s*:?$", re.I)


def _bbox(values):
    return [round(float(v), 2) for v in values]


def _overlap_ratio(a, b):
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / max(1.0, min(a[2] - a[0], b[2] - b[0]))


def _fraction_candidate(lines, i):
    """Report possible numerator/denominator geometry; never assert verified LaTeX."""
    current = lines[i]
    if "AICc" not in current["text"] or "=" not in current["text"]:
        return None
    a = current["bbox"]
    possibilities = []
    for other in lines:
        b = other["bbox"]
        if other is current or not FRACTION_DENOM.fullmatch(other["text"]):
            continue
        if not re.search(r"[Tt]", other["text"]):
            continue
        vertical_gap = b[1] - a[3]
        if -5 <= vertical_gap <= 28 and _overlap_ratio(a, b) >= 0.35:
            possibilities.append((abs(vertical_gap), other))
    if not possibilities:
        return None
    denominator = min(possibilities, key=lambda item: item[0])[1]
    return {
        "kind": "possible_stacked_fraction",
        "numerator_line": current["text"],
        "denominator_line": denominator["text"],
        "numerator_bbox": a,
        "denominator_bbox": denominator["bbox"],
        "verified": False,
        "note": "Spatially associated only; fraction bar and mathematical correctness not verified.",
    }


def _valid_table(cells):
    if len(cells) < 2:
        return False
    width = max((len(row) for row in cells), default=0)
    if width < 2:
        return False
    values = [str(v).strip() for row in cells for v in row if v is not None and str(v).strip()]
    if len(values) < 4:
        return False
    occupied = len(values) / max(1, len(cells) * width)
    if occupied < 0.30:
        return False
    plot_like = sum(bool(PLOT_MARKER.fullmatch(v)) for v in values)
    if plot_like / len(values) > 0.60:
        return False
    # Require at least two populated rows to avoid chart/axis artifacts.
    populated_rows = sum(sum(bool(v and str(v).strip()) for v in row) >= 2 for row in cells)
    return populated_rows >= 2


def inspect_page(pdf_path: str | Path, page_number: int) -> dict:
    import pymupdf

    with pymupdf.open(str(pdf_path)) as doc:
        if doc.needs_pass:
            raise ValueError("Password-protected PDF")
        if not 1 <= page_number <= len(doc):
            raise ValueError("Page number out of range")
        page = doc[page_number - 1]
        lines = []
        for block in page.get_text("dict", sort=True).get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                content = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if content:
                    lines.append({"text": content, "bbox": _bbox(line["bbox"])})

        equations = []
        for i, line in enumerate(lines):
            content = line["text"]
            if HEADING.fullmatch(content) or not EQUATION.search(content):
                continue
            # A sentence containing '=' is relevant only if it has a mathematical
            # left side, or substantial symbolic structure.
            if "=" in content:
                lhs = content.split("=", 1)[0].strip()
                if len(lhs) > 48 or len(lhs.split()) > 7:
                    continue
            elif not MATH_SYMBOL.search(content):
                continue
            nearby = lines[max(0, i - 1):min(len(lines), i + 2)]
            entry = {
                "raw_text": content,
                "bbox": line["bbox"],
                "context_lines": [x["text"] for x in nearby],
                "status": "needs_visual_verification",
                "latex": None,
            }
            fraction = _fraction_candidate(lines, i)
            if fraction:
                entry["structure_candidate"] = fraction
            equations.append(entry)

        tables = []
        rejected = 0
        finder = getattr(page, "find_tables", None)
        if callable(finder):
            for table in finder().tables:
                cells = table.extract()
                if not _valid_table(cells):
                    rejected += 1
                    continue
                tables.append({
                    "bbox": _bbox(table.bbox),
                    "rows": cells,
                    "row_count": len(cells),
                    "column_count": max((len(r) for r in cells), default=0),
                    "status": "needs_structural_verification",
                })
        return {
            "page_number": page_number,
            "equation_candidates": equations,
            "tables": tables,
            "diagnostics": {
                "text_lines": len(lines),
                "equation_candidates": len(equations),
                "tables": len(tables),
                "rejected_table_candidates": rejected,
            },
            "note": "Read-only candidates; no verified LaTeX, LLM, embeddings, or database writes.",
        }


@router.get("/documents/{document_id}/pages/{page_number}")
def inspect_document_page(document_id: str, page_number: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    if not 1 <= page_number <= doc.page_count:
        raise HTTPException(422, "Page number out of range")
    if not Path(doc.file_path).is_file():
        raise HTTPException(404, "Original PDF not found")
    try:
        return inspect_page(doc.file_path, page_number)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
