from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from .db import get_db
from .models import Document, Page, EvidenceBlock, PageAnalysis, KnowledgeItem
from .config import settings
from .vision import analyze_page

router = APIRouter(prefix="/api/v1", tags=["Phase 2 - Intelligence"])
KINDS = ("concepts", "formulas", "charts", "rules")

class AnalyzeRequest(BaseModel):
    force: bool = False

class ResearchRequest(BaseModel):
    document_id: str
    question: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=30)

def get_page(db, doc_id, num):
    page = db.scalar(select(Page).where(Page.document_id == doc_id, Page.page_number == num))
    if page is None:
        raise HTTPException(404, "Document page not found")
    return page

def source_url(doc_id, page_num):
    return f"/api/v1/documents/{doc_id}/pages/{page_num}/image"

def output_item(k, num):
    return {"id": k.id, "kind": k.kind, "title": k.title, "details": k.body_json,
            "page_number": num, "bbox": k.source_bbox, "provenance": k.provenance,
            "review_status": k.review_status,
            "source_url": source_url(k.document_id, num)}

@router.post("/documents/{document_id}/pages/{page_number}/analyze")
def analyze(document_id: str, page_number: int, body: AnalyzeRequest, db: Session = Depends(get_db)):
    page = get_page(db, document_id, page_number)
    provider = settings.ai_provider
    model = ("text-preview-v1" if provider == "offline" else
             settings.ollama_vision_model if provider == "ollama" else settings.openai_model)
    prior = db.scalar(select(PageAnalysis).where(PageAnalysis.page_id == page.id, PageAnalysis.provider == provider, PageAnalysis.model == model))
    if prior and not body.force:
        return {"analysis_id": prior.id, "cached": True, "provider": provider, "model": model,
                "result": prior.result_json, "source_url": source_url(document_id, page_number)}
    blocks = db.scalars(select(EvidenceBlock).where(EvidenceBlock.page_id == page.id, EvidenceBlock.block_type == "text")).all()
    page_text = "\n".join(x.content or "" for x in blocks)
    try:
        result, actual_provider, actual_model = analyze_page(page.image_path, page_text)
    except Exception as exc:
        # Avoid leaking API keys, request headers, or provider response bodies.
        raise HTTPException(502, f"Page analysis failed ({type(exc).__name__}); check backend logs and provider settings") from exc
    try:
        if prior:
            db.query(KnowledgeItem).filter(KnowledgeItem.analysis_id == prior.id).delete(synchronize_session=False)
            prior.result_json = result
            analysis = prior
        else:
            analysis = PageAnalysis(page_id=page.id, provider=actual_provider, model=actual_model, result_json=result)
            db.add(analysis)
            db.flush()
        for kind in KINDS:
            for entry in result[kind][:100]:
                if not isinstance(entry, dict):
                    continue
                bbox = entry.get("bbox")
                if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox) and 0 <= bbox[0] < bbox[2] <= page.width and 0 <= bbox[1] < bbox[3] <= page.height):
                    bbox = None
                title = str(entry.get("title") or kind[:-1])[:250]
                provenance = str(entry.get("provenance") or "model_inference")
                if provenance not in ("explicit_text", "visible_figure", "model_inference"):
                    provenance = "model_inference"
                db.add(KnowledgeItem(document_id=document_id, page_id=page.id, analysis_id=analysis.id,
                                     kind=kind[:-1] if kind != "concepts" else "concept", title=title,
                                     body_json=entry, source_bbox=bbox, provenance=provenance))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"analysis_id": analysis.id, "cached": False, "provider": actual_provider,
            "model": actual_model, "result": result, "source_url": source_url(document_id, page_number)}

@router.get("/documents/{document_id}/pages/{page_number}/analysis")
def page_analysis(document_id: str, page_number: int, db: Session = Depends(get_db)):
    page = get_page(db, document_id, page_number)
    analyses = db.scalars(select(PageAnalysis).where(PageAnalysis.page_id == page.id).order_by(PageAnalysis.created_at.desc())).all()
    return [{"id": a.id, "provider": a.provider, "model": a.model, "result": a.result_json} for a in analyses]

@router.get("/documents/{document_id}/knowledge")
def knowledge(document_id: str, kind: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    if not db.get(Document, document_id):
        raise HTTPException(404, "Document not found")
    query = select(KnowledgeItem, Page.page_number).join(Page, KnowledgeItem.page_id == Page.id).where(KnowledgeItem.document_id == document_id)
    if kind:
        if kind not in ("concept", "formula", "chart", "rule"):
            raise HTTPException(400, "kind must be concept, formula, chart or rule")
        query = query.where(KnowledgeItem.kind == kind)
    rows = db.execute(query.order_by(Page.page_number).limit(limit)).all()
    return [output_item(item, num) for item, num in rows]

@router.post("/research/search")
def research_search(body: ResearchRequest, db: Session = Depends(get_db)):
    if not db.get(Document, body.document_id):
        raise HTTPException(404, "Document not found")
    # Grounded keyword retrieval; NOT generative Q&A or semantic retrieval.
    words = [w.strip(".,?!:;()[]").lower() for w in body.question.split() if len(w.strip(".,?!:;()[]")) >= 3]
    words = list(dict.fromkeys(words))[:12]
    if not words:
        raise HTTPException(400, "Question must contain a search term of at least 3 characters")
    rows = db.execute(select(EvidenceBlock, Page.page_number).join(Page, EvidenceBlock.page_id == Page.id)
                      .where(Page.document_id == body.document_id, EvidenceBlock.block_type == "text")
                      .order_by(Page.page_number)).all()
    matches = []
    for block, num in rows:
        hay = (block.content or "").lower()
        score = sum(hay.count(word) for word in words)
        if score:
            matches.append({"score": score, "page_number": num, "text": block.content,
                            "bbox": block.bbox, "evidence_id": block.id,
                            "source_url": source_url(body.document_id, num)})
    matches.sort(key=lambda x: (-x["score"], x["page_number"]))
    return {"mode": "keyword_evidence_search", "answer": None,
            "note": "These are source excerpts, not an AI-generated answer. Page analysis is a separate operation.",
            "results": matches[:body.limit]}
