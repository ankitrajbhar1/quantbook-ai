import hashlib
import shutil
import tempfile
from pathlib import Path
import fitz
from fastapi import FastAPI, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, get_db
from .models import Document, Page, EvidenceBlock

app = FastAPI(title="QuantBook AI", version="0.1.0")

@app.on_event("startup")
def startup():
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)  # MVP only; use Alembic later

@app.get("/health")
def health():
    return {"status": "ok", "service": "quantbook-ai"}

@app.post("/api/v1/documents", status_code=201)
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF uploads are accepted")
    maximum = settings.max_upload_mb * 1024 * 1024
    h = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise HTTPException(413, "PDF exceeds upload limit")
                h.update(chunk)
                tmp.write(chunk)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
    if size == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(400, "Empty upload")
    try:
        with fitz.open(str(tmp_path)) as probe:
            if not probe.is_pdf:
                raise ValueError("Uploaded file is not a PDF")
            if probe.needs_pass:
                raise ValueError("Password-protected PDFs are not supported")
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(422, f"Invalid PDF: {exc}") from exc
    digest = h.hexdigest()
    existing = db.scalar(select(Document).where(Document.sha256 == digest))
    if existing:
        tmp_path.unlink(missing_ok=True)
        return {"document_id": existing.id, "status": existing.status, "page_count": existing.page_count, "duplicate": True}
    doc = Document(filename=Path(file.filename).name[:255], sha256=digest, file_path="")
    db.add(doc)
    db.flush()
    folder = settings.storage_root / doc.id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "original.pdf"
    shutil.move(str(tmp_path), target)
    doc.file_path = str(target.resolve())
    try:
        with fitz.open(str(target)) as pdf:
            if pdf.needs_pass:
                raise ValueError("Password-protected PDFs are not supported yet")
            if pdf.page_count == 0:
                raise ValueError("PDF contains no pages")
            doc.page_count = pdf.page_count
            for index, source_page in enumerate(pdf):
                number = index + 1
                page_image = folder / f"page_{number:04}.png"
                source_page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(str(page_image))
                page = Page(document_id=doc.id, page_number=number, width=source_page.rect.width,
                            height=source_page.rect.height, image_path=str(page_image.resolve()))
                db.add(page)
                db.flush()
                blocks = source_page.get_text("dict")["blocks"]
                for idx, block in enumerate(blocks):
                    bbox = [float(x) for x in block["bbox"]]
                    if block["type"] == 0:
                        content = "\n".join("".join(span["text"] for span in line["spans"])
                                            for line in block.get("lines", []))
                        if content.strip():
                            db.add(EvidenceBlock(page_id=page.id, block_type="text", content=content,
                                                 bbox=bbox, metadata_json={"order": idx}))
                    elif block["type"] == 1:
                        image_path = folder / f"page_{number:04}_image_{idx}.png"
                        pix = source_page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(bbox), alpha=False)
                        pix.save(str(image_path))
                        db.add(EvidenceBlock(page_id=page.id, block_type="image", bbox=bbox,
                                             asset_path=str(image_path.resolve()), metadata_json={"order": idx}))
            doc.status = "completed"
            db.commit()
    except Exception as exc:
        db.rollback()
        shutil.rmtree(folder, ignore_errors=True)
        if isinstance(exc, ValueError):
            raise HTTPException(422, str(exc)) from exc
        raise HTTPException(500, "PDF processing failed") from exc
    return {"document_id": doc.id, "status": doc.status, "page_count": doc.page_count, "duplicate": False}

@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc: raise HTTPException(404, "Document not found")
    return {"id": doc.id, "filename": doc.filename, "sha256": doc.sha256,
            "status": doc.status, "page_count": doc.page_count}

@app.get("/api/v1/documents/{document_id}/pages/{page_number}")
def get_page(document_id: str, page_number: int, db: Session = Depends(get_db)):
    page = db.scalar(select(Page).where(Page.document_id == document_id, Page.page_number == page_number))
    if not page: raise HTTPException(404, "Page not found")
    blocks = db.scalars(select(EvidenceBlock).where(EvidenceBlock.page_id == page.id)).all()
    return {"page_number": page.page_number, "width": page.width, "height": page.height,
            "image_url": f"/api/v1/documents/{document_id}/pages/{page_number}/image",
            "blocks": [{"id": x.id, "type": x.block_type, "text": x.content,
                        "bbox": x.bbox, "asset_url": (f"/api/v1/evidence/{x.id}/image" if x.asset_path else None)} for x in blocks]}

@app.get("/api/v1/documents/{document_id}/pages/{page_number}/image")
def get_page_image(document_id: str, page_number: int, db: Session = Depends(get_db)):
    page = db.scalar(select(Page).where(Page.document_id == document_id, Page.page_number == page_number))
    if not page: raise HTTPException(404, "Page not found")
    return FileResponse(page.image_path, media_type="image/png")

@app.get("/api/v1/evidence/{block_id}/image")
def get_evidence_image(block_id: str, db: Session = Depends(get_db)):
    block = db.get(EvidenceBlock, block_id)
    if not block or not block.asset_path: raise HTTPException(404, "Image not found")
    return FileResponse(block.asset_path, media_type="image/png")


@app.get("/api/v1/documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).order_by(Document.created_at.desc())).all()
    return [{"id": d.id, "filename": d.filename, "page_count": d.page_count, "status": d.status} for d in docs]

@app.get("/api/v1/documents/{document_id}/file")
def get_original_pdf(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return FileResponse(doc.file_path, media_type="application/pdf", filename=doc.filename)

@app.get("/api/v1/documents/{document_id}/search")
def search_document(document_id: str, q: str, db: Session = Depends(get_db)):
    if not q.strip() or len(q) > 200:
        raise HTTPException(400, "q must contain 1-200 non-whitespace characters")
    if not db.get(Document, document_id):
        raise HTTPException(404, "Document not found")
    rows = db.execute(
        select(EvidenceBlock, Page.page_number).join(Page, EvidenceBlock.page_id == Page.id)
        .where(Page.document_id == document_id, EvidenceBlock.block_type == "text",
               EvidenceBlock.content.ilike(f"%{q}%"))
        .order_by(Page.page_number).limit(50)
    ).all()
    return [{"page_number": n, "block_id": b.id, "text": b.content, "bbox": b.bbox} for b,n in rows]


# Phase 2 endpoints and local research workspace
from .phase2 import router as phase2_router
from fastapi.responses import HTMLResponse
app.include_router(phase2_router)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def workspace():
    from pathlib import Path
    return Path(__file__).with_name("workspace.html").read_text(encoding="utf-8")

# Phase 3 local semantic retrieval and grounded research
from .phase3 import router as phase3_router
app.include_router(phase3_router)

# Phase 3 layout32 API
from .layout32_api import router as layout32_router
app.include_router(layout32_router)

# Phase 3 shadow32 API
from .shadow32_index import router as shadow32_router
app.include_router(shadow32_router)

# Phase 3.3 API
from .phase33 import router as phase33_router
app.include_router(phase33_router)

# Phase 3.4 API
from .phase34 import router as phase34_router
app.include_router(phase34_router)