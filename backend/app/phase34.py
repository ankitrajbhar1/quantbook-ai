"""Phase 3.4: bounded, on-demand PDF visual inspection. No indexing or DB writes."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Document

router = APIRouter(prefix="/api/v1/phase34", tags=["Phase 3.4 - Visual PDF inspection"])

class VisionRequest(BaseModel):
    document_id: str
    page_number: int = Field(ge=1)
    question: str = Field(min_length=5, max_length=500)
    region: list[float] | None = Field(default=None, min_length=4, max_length=4)
    model: str = Field(default="gemma3:4b", pattern=r"^[a-zA-Z0-9_.:/-]{1,80}$")
    use_cache: bool = True


def _render(pdf_path: str, page_number: int, region: list[float] | None):
    import pymupdf
    with pymupdf.open(pdf_path) as pdf:
        if pdf.needs_pass or not 1 <= page_number <= len(pdf):
            raise ValueError("PDF is password protected or page is out of range")
        page = pdf[page_number - 1]
        rect = page.rect
        if region is not None:
            if not all(isinstance(v, (int, float)) and abs(v) < 100000 for v in region):
                raise ValueError("Invalid region coordinates")
            rect = pymupdf.Rect(*region)
            if rect.is_empty or rect.is_infinite or not page.rect.contains(rect):
                raise ValueError("Region must be a valid rectangle inside the page")
        # Limit pixel count to protect low-memory computers.
        zoom = min(1.5, 1400 / max(rect.width, rect.height))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect, alpha=False, colorspace=pymupdf.csRGB)
        return pix.tobytes("png"), [round(float(v), 2) for v in rect]


@router.post("/inspect")
def inspect_visual(body: VisionRequest, db: Session = Depends(get_db)):
    doc = db.get(Document, body.document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    pdf_path = Path(doc.file_path)
    if not pdf_path.is_file():
        raise HTTPException(404, "Original PDF not found")
    if body.page_number > doc.page_count:
        raise HTTPException(422, "Page number out of range")
    try:
        image, bbox = _render(str(pdf_path), body.page_number, body.region)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc

    digest = hashlib.sha256(image + body.question.encode() + body.model.encode()).hexdigest()
    cache_dir = pdf_path.parent / ".quantbook_vision_cache"
    cache_file = cache_dir / f"{digest}.json"
    if body.use_cache and cache_file.is_file():
        try:
            result = json.loads(cache_file.read_text(encoding="utf-8"))
            result["cached"] = True
            return result
        except (OSError, ValueError):
            pass

    prompt = (
        "Inspect the provided PDF image only. Answer the user's question using visible evidence. "
        "For mathematical expressions, preserve exact symbols, signs, numerator/denominator and subscripts. "
        "For charts, distinguish axes, labels, plotted data and legends. "
        "If anything is unreadable or ambiguous, say so explicitly. "
        "Do not claim that your transcription is verified. "
        f"Question: {body.question}"
    )
    payload = {
        "model": body.model,
        "stream": False,
        "keep_alive": 0,
        "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(image).decode("ascii")]}],
        "options": {"num_ctx": 2048, "num_predict": 450, "temperature": 0},
    }
    try:
        with httpx.Client(timeout=180) as client:
            response = client.post(settings.ollama_base_url.rstrip("/") + "/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Vision model unavailable or timed out; check Ollama and backend logs") from exc
    answer = data.get("message", {}).get("content", "")
    if not isinstance(answer, str) or not answer.strip():
        raise HTTPException(502, "Vision model returned an empty response")
    result = {
        "document_id": body.document_id,
        "page_number": body.page_number,
        "bbox": bbox,
        "question": body.question,
        "interpretation": answer.strip(),
        "model": body.model,
        "status": "unverified_visual_interpretation",
        "cached": False,
        "warning": "Model-generated interpretation; verify formulas and numerical values against the original PDF.",
    }
    # Cache is optional, best effort, and isolated from research DB/index.
    if body.use_cache:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return result
