"""Read-only preview endpoint for Phase 3.2.1."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .layout32 import extract_pdf_page
from .models import Document

router = APIRouter(prefix="/api/v1/layout", tags=["Phase 3.2 - Layout Preview"])


@router.get("/documents/{document_id}/pages/{page_number}")
def preview_layout(document_id: str, page_number: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if page_number < 1 or page_number > document.page_count:
        raise HTTPException(status_code=404, detail="Page not found")
    path = Path(document.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Original PDF not available on disk")
    try:
        result = extract_pdf_page(path, page_number)
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(status_code=422, detail="Could not extract this PDF page") from None
    result["document_id"] = document_id
    return result
