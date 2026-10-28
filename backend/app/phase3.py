"""QuantBook AI Phase 3.1: local, source-grounded hybrid research.

Drop-in replacement for backend/app/phase3.py. No schema migration required.
"""
import logging
import math
import re
from collections import Counter

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Document, Page, EvidenceBlock, ResearchChunk

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/research", tags=["Phase 3.1 - Local Research"])


class IndexRequest(BaseModel):
    document_id: str
    force: bool = False
    max_pages: int | None = Field(default=None, ge=1, le=1000)


class AskRequest(BaseModel):
    document_id: str
    question: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=8)
    mode: str = Field(default="answer", pattern="^(answer|retrieve)$")
    include_structured_evidence: bool = False


class OllamaFailure(Exception):
    pass


def ollama_post(endpoint, body, timeout=180):
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(settings.ollama_base_url.rstrip("/") + endpoint, json=body)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Ollama returned a non-object JSON response")
            return data
    except (httpx.HTTPError, ValueError) as exc:
        log.exception("Ollama request failed: %s", endpoint)
        raise OllamaFailure("Ollama unavailable or invalid response; inspect backend logs") from exc


def embed(text):
    data = ollama_post("/api/embed", {
        "model": settings.ollama_embed_model, "input": text,
        "keep_alive": 0, "options": {"num_ctx": 2048},
    })
    vectors = data.get("embeddings")
    if not isinstance(vectors, list) or not vectors or not isinstance(vectors[0], list):
        raise OllamaFailure("Embedding model returned no vector")
    vector = vectors[0]
    if not vector or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
        raise OllamaFailure("Embedding vector invalid")
    return vector


def chunks_for_page(blocks, target=1100, overlap=170):
    """Keep original chunking stable, so existing 199 embeddings remain valid."""
    pieces = []
    for block in blocks:
        txt = re.sub(r"\s+", " ", block.content or "").strip()
        if not txt:
            continue
        if len(txt) > target:
            for start in range(0, len(txt), target - overlap):
                part = txt[start:start + target]
                if len(part) >= 35:
                    pieces.append((part, block.bbox))
                if start + target >= len(txt):
                    break
        else:
            pieces.append((txt, block.bbox))
    output, current, length = [], [], 0

    def flush():
        nonlocal current, length
        if current:
            content = "\n".join(t for t, _ in current)
            boxes = [b for _, b in current if isinstance(b, list) and len(b) == 4]
            bbox = ([min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None)
            output.append((content, bbox))
            current, length = [], 0

    for txt, bbox in pieces:
        if current and length + len(txt) > target:
            flush()
        current.append((txt, bbox))
        length += len(txt)
    flush()
    return output


def cosine(a, b):
    if len(a) != len(b):
        return -1.0
    aa, bb = sum(x*x for x in a), sum(x*x for x in b)
    return sum(x*y for x, y in zip(a, b)) / math.sqrt(aa*bb) if aa and bb else 0.0


def source_url(doc_id, page):
    return f"/api/v1/documents/{doc_id}/pages/{page}/image"


def source_record(chunk, score, rank):
    return {
        "citation_id": f"S{rank}", "chunk_id": chunk.id,
        "page_number": chunk.page_number, "text": chunk.content,
        "bbox": chunk.bbox, "score": round(score, 4),
        "source_url": source_url(chunk.document_id, chunk.page_number),
        "pdf_url": f"/api/v1/documents/{chunk.document_id}/file#page={chunk.page_number}",
    }


# Only remove high-confidence chart extraction artifacts. Never delete digits or formulas.
CHART_NOISE = re.compile(r"(?m)^\s*(?:G\s*){4,}$")
TOKEN = re.compile(r"[a-z0-9]+(?:\([0-9,]+\))?", re.I)
STOP = frozenset("the a an of to and or in for is are with how what explain difference between from that this be by at on as do does using can we it its their about model models time series data".split())


def clean_context(text):
    text = CHART_NOISE.sub(" ", text or "")
    text = re.sub(r"(?<!\w)(?:G\s+){5,}G(?!\w)", " ", text)
    text = text.replace("ﬁ", "fi").replace("ﬀ", "ff").replace("ﬃ", "ffi").replace("ﬂ", "fl")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def keywords(text):
    return [w for w in TOKEN.findall(clean_context(text).lower()) if len(w) > 1 and w not in STOP]


def lexical_score(question, content):
    """Normalized lexical coverage; helpful for exact technical terms and equations."""
    q = set(keywords(question))
    if not q:
        return 0.0
    words = set(keywords(content))
    return len(q & words) / len(q)




def retrieval_clean(text):
    """Remove high-confidence isolated chart markers; preserve formulas and prose."""
    text = (text or '').replace('ﬁ','fi').replace('ﬂ','fl').replace('ﬀ','ff').replace('ﬃ','ffi')
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # Only remove lines composed exclusively of chart marker G tokens.
        if re.fullmatch(r'(?:G\s*){3,}', stripped):
            continue
        lines.append(line)
    text = '\n'.join(lines)
    text = re.sub(r'(?<!\w)(?:G\s+){5,}G(?!\w)', ' ', text)
    return re.sub(r'[ \t]+', ' ', text).strip()

def _tokens(text):
    return [t for t in _TOKEN.findall(retrieval_clean(text).lower()) if len(t) > 1 and t not in _STOP]

def _coverage(question, content):
    query = set(_tokens(question))
    terms = set(_tokens(content))
    if not query:
        return 0.0
    return sum(bool(_ALIASES.get(q, {q}) & terms) for q in query) / len(query)

def _noise_penalty(content):
    raw = content or ''
    cleaned = retrieval_clean(raw)
    if not raw.strip():
        return 0.20
    removed_fraction = max(0.0, 1.0 - len(cleaned) / max(len(raw), 1))
    return min(0.16, removed_fraction * 0.24)

def _toc_penalty(content):
    text = retrieval_clean(content)
    lower = text.lower()
    # Detect a table of contents using multiple numbered entries with dotted leaders.
    entries = len(re.findall(r'\b\d{1,2}\.\d{1,2}\s+[a-z][^.\n]{3,65}\.{3,}', lower))
    return 0.24 if 'contents' in lower[:100] or entries >= 4 else 0.0

def _focused_bonus(question, content):
    q = set(_tokens(question))
    if not q:
        return 0.0
    text = retrieval_clean(content)
    # Reward one coherent short window that covers several distinct query concepts.
    words = _tokens(text)
    best = 0.0
    for i in range(0, len(words), 35):
        window = set(words[i:i+70])
        best = max(best, sum(bool(_ALIASES.get(t, {t}) & window) for t in q) / len(q))
    return 0.07 * best

def _jaccard(a, b):
    aa, bb = set(_tokens(a)), set(_tokens(b))
    return len(aa & bb) / len(aa | bb) if aa and bb else 0.0



def retrieve_chunks(question, query_vector, stored, top_k=5):
    """
    Phase 3.1.1: Improved hybrid retrieval.

    Features:
    - Semantic + lexical ranking
    - Focused relevance bonus
    - PDF extraction noise penalties
    - Improved table-of-contents filtering
    - Duplicate-content reduction
    - Page diversity
    - Preserves (cosine_score, chunk) API
    """

    candidates = []

    for chunk in stored:
        text = clean_context(chunk.content)

        if not text.strip():
            continue

        # --------------------------------------------------
        # 1. Improved table-of-contents detection
        # --------------------------------------------------

        # Detect dotted leaders:
        # "Introduction ............ 5"
        # "Introduction . . . . . . . 5"
        toc_dot_sequences = re.findall(
            r"(?:\.\s*){5,}",
            text,
        )

        # Detect numbered TOC entries ending in page numbers:
        # "8.2 ACF and PACF ............ 85"
        # "8.5 ARIMA vs ETS . . . . . . 92"
        #
        # Avoid crossing newline boundaries.
        toc_entries = re.findall(
            r"(?<!\w)\d+(?:\.\d+)*\s+"
            r"[^\n]{3,100}?"
            r"(?:\.\s*){5,}\d+\b",
            text,
        )

        has_contents_heading = bool(
            re.search(
                r"\bcontents\b",
                text,
                re.IGNORECASE,
            )
        )

        is_table_of_contents = (
            len(toc_entries) >= 3
            or (
                has_contents_heading
                and len(toc_dot_sequences) >= 3
            )
        )

        if is_table_of_contents:
            continue

        # --------------------------------------------------
        # 2. Semantic similarity
        # --------------------------------------------------

        semantic = cosine(
            query_vector,
            chunk.vector,
        )

        if not math.isfinite(semantic):
            continue

        # --------------------------------------------------
        # 3. Lexical relevance
        # --------------------------------------------------

        lexical = _coverage(
            question,
            text,
        )

        # --------------------------------------------------
        # 4. Hybrid relevance score
        # --------------------------------------------------

        score = (
            0.68 * semantic
            + 0.32 * lexical
            + _focused_bonus(question, text)
            - _toc_penalty(text)
            - _noise_penalty(chunk.content)
        )

        if not math.isfinite(score):
            continue

        candidates.append(
            (score, semantic, chunk)
        )

    # --------------------------------------------------
    # 5. Sort by hybrid relevance
    # --------------------------------------------------

    candidates.sort(
        key=lambda row: (
            -row[0],
            str(row[2].id),
        )
    )

    # Wider candidate pool for diversity-aware selection.
    pool = candidates[:max(80, top_k * 15)]

    selected = []
    pages = Counter()

    # --------------------------------------------------
    # 6. Diversity-aware reranking
    # --------------------------------------------------

    while pool and len(selected) < top_k:

        best_index = 0
        best_value = -float("inf")

        for i, (score, semantic, chunk) in enumerate(pool):

            duplication = max(
                (
                    _jaccard(
                        chunk.content,
                        selected_chunk[2].content,
                    )
                    for selected_chunk in selected
                ),
                default=0.0,
            )

            page_penalty = (
                0.09 * pages[chunk.page_number]
            )

            duplication_penalty = (
                0.10 * duplication
            )

            value = (
                score
                - page_penalty
                - duplication_penalty
            )

            if value > best_value:
                best_index = i
                best_value = value

        chosen = pool.pop(best_index)

        selected.append(chosen)

        pages[chosen[2].page_number] += 1

    # --------------------------------------------------
    # 7. Preserve existing API contract
    # --------------------------------------------------

    return [
        (semantic, chunk)
        for _, semantic, chunk in selected
    ]


def extract_final_answer(message):
    if not isinstance(message, dict):
        return ""
    content = message.get("content") or ""
    if not isinstance(content, str):
        return ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.I | re.S).strip()
    if re.search(r"</think>", content, re.I):
        content = re.split(r"</think>", content, flags=re.I)[-1].strip()
    if re.search(r"<think>", content, re.I):
        return ""
    return content


REASONING_LEADS = (
    "i need to", "let me", "i'll craft", "i will now", "the user wants",
    "i should", "first, i", "i'll analyze", "i must", "let's analyze",
)


def answer_issues(answer, sources):
    """Cheap deterministic guards; NOT a semantic factuality proof."""
    issues = []
    if not answer.strip():
        return ["empty"]
    if len(answer) > 2500:
        issues.append("too_long")
    lower = answer.lower().lstrip()
    if lower.startswith(REASONING_LEADS) or "</think>" in lower:
        issues.append("reasoning_trace")
    # allowed = {s["citation_id"] for s in sources}
    # citations = set(re.findall(r"\[(S\d+)\]", answer))
    # if not citations or citations - allowed:
    #     issues.append("missing_or_invalid_citations")
    allowed = {s["citation_id"] for s in sources}
    citations = set(re.findall(r"\[(S\d+)\]", answer))

    insufficient_evidence = (
        answer.strip()
        == "The provided excerpts do not contain enough information to answer."
    )

    if citations - allowed:
        issues.append("missing_or_invalid_citations")

    elif not citations and not insufficient_evidence:
        issues.append("missing_or_invalid_citations")
    # Reject unsupported exact ARIMA orders rather than accepting an invented value.
    evidence = " ".join(clean_context(s["text"]).lower() for s in sources)
    for order in set(re.findall(r"\bARIMA\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)", answer, re.I)):
        norm = re.sub(r"\s+", "", order.lower())
        if norm not in re.sub(r"\s+", "", evidence):
            issues.append("unseen_arima_order")
            break
    # Known failure mode: claims about AR/MA cutoff directions. A small guard,
    # not a replacement for expert evaluation or model-based verification.
    if re.search(r"\bPACF\b.{0,45}\b(?:decay|tails? off)\b.{0,45}\bAR\s*\(\s*1\s*\)", answer, re.I):
        issues.append("suspect_ar_pacf_pattern")
    if re.search(r"simple exponential smoothing.{0,90}ARIMA\s*\(\s*0\s*,\s*2\s*,\s*2\s*\)", answer, re.I | re.S):
        issues.append("incorrect_ses_equivalence")
    return issues



def select_relevant_excerpt(question, text, max_chars=500):
    """
    Select question-relevant evidence from a retrieved PDF chunk.

    Lightweight text processing only:
    - No additional model calls
    - No database changes
    - No new dependencies
    """
    text = clean_context(text)

    if len(text) <= max_chars:
        return text

    # Normalize common PDF bullet formatting.
    text = re.sub(r"\s*[•●▪]\s*", "\n", text)

    # Split on sentence boundaries and line breaks.
    passages = re.split(r"(?<=[.!?])\s+|\n+", text)
    passages = [p.strip() for p in passages if len(p.strip()) >= 20]

    if not passages:
        return text[:max_chars]

    # Match question terms, including common forecasting concepts.
    question_terms = set(
        re.findall(r"[a-z]{3,}", question.lower())
    )

    question_terms -= {
        "what", "which", "when", "where", "why",
        "how", "are", "the", "and", "for", "with",
        "models", "model", "time", "series",
    }

    related_terms = {
        "limitations": {
            "limitation", "uncertainty", "assume",
            "assumptions", "residuals", "biased",
            "overfitting", "over", "fitting",
            "accuracy", "narrow", "uncorrelated",
        },
        "forecasting": {
            "forecast", "forecasts", "forecasting",
            "prediction", "predict",
        },
    }

    expanded_terms = set(question_terms)

    for term in question_terms:
        expanded_terms.update(related_terms.get(term, set()))

    def passage_score(passage):
        words = set(re.findall(r"[a-z]{3,}", passage.lower()))
        return len(words & expanded_terms)

    ranked = sorted(
        enumerate(passages),
        key=lambda item: (-passage_score(item[1]), item[0]),
    )

    selected = []
    used_chars = 0

    for _, passage in ranked:
        remaining = max_chars - used_chars

        if remaining <= 0:
            break

        if len(passage) > remaining:
            if not selected:
                selected.append(passage[:remaining])
            break

        selected.append(passage)
        used_chars += len(passage) + 1

    return " ".join(selected).strip()


def make_prompt(question, sources, max_chars):
    context = "\n\n".join(
        f'[{s["citation_id"]}] Page {s["page_number"]}: '
        f'{select_relevant_excerpt(question, s["text"], max_chars)}'
        for s in sources
    )


    system = (
        "You are a precise PDF question-answering assistant. "
        "Answer using only the provided PDF excerpts. "
        "Preserve the exact meaning of the source evidence. "

        "CRITICAL ACCURACY RULES: "
        "If the source says A is a special case of B, "
        "never claim B is a special case of A. "
        "Preserve directional relationships, negations, "
        "quantifiers, and mathematical equivalences. "
        "Do not change 'all', 'some', 'many', or 'none'. "

        "PDF text may contain flattened tables, diagrams, "
        "formulas, and headings in incorrect reading order. "
        "Do not associate a method with a formula unless "
        "the relationship is unambiguous. "

        "If a source statement is abbreviated, interpret it "
        "conservatively without reversing its meaning. "

        "Use specific facts supported by the excerpts. "
        "If evidence supports a partial answer, provide it. "
        "Write 1-3 concise sentences. "
        "Cite factual statements using [S1], [S2], etc. "
        "Only use citation IDs present in the excerpts. "

        "If no relevant evidence exists, respond exactly: "
        "The provided excerpts do not contain enough "
        "information to answer. "

        "Do not invent facts or explain your reasoning."
    )

    user = (
        "/no_think\n"
        f"PDF EXCERPTS:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        "Provide a concise, evidence-based answer with citations.\n"
        "ANSWER:"
    )

    return system, user

def generate_answer(question, sources):
    system, user = make_prompt(
        question,
        sources,
        max_chars=350,
    )

    system += (
        "\nReturn only a JSON object with one key named answer. "
        "The answer must be a short, source-grounded response "
        "with citations such as [S1]. "
        "Do not include planning or analysis."
    )

    data = ollama_post(
        "/api/chat",
        {
            "model": settings.ollama_text_model,
            "stream": False,
            "think": False,
            "format": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"}
                },
                "required": ["answer"],
                "additionalProperties": False,
            },
            "keep_alive": 0,
            "options": {
                "temperature": 0,
                "num_ctx": 2048,
                "num_predict": 512,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=180,
    )

    import json

    message = data.get("message") or {}
    raw_content = message.get("content") or ""
    done_reason = data.get("done_reason")

    log.warning(
        "Phase3.1 JSON diagnostic: done_reason=%s "
        "content_chars=%d eval_count=%s",
        done_reason,
        len(raw_content),
        data.get("eval_count"),
    )

    if done_reason == "length":
        raise OllamaFailure(
            "JSON generation truncated before completion"
        )

    try:
        parsed = json.loads(raw_content)
        answer = parsed["answer"]
        if not isinstance(answer, str):
            raise ValueError("answer must be a string")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        log.warning("Invalid structured answer: %s", exc)
        raise OllamaFailure(
            "Ollama did not return a valid structured answer"
        ) from exc

    # issues = answer_issues(answer, sources)

    # if issues:
    #     log.warning("Structured answer rejected: %s", issues)
    #     raise OllamaFailure(
    #         f"Structured answer failed validation: {', '.join(issues)}"
    #     )

    issues = answer_issues(answer, sources)

    if issues:
        log.warning(
            "Structured answer rejected: %s",
            issues,
        )

        log.warning(
            "Rejected answer preview: %r",
            answer[:800],
        )

        log.warning(
            "Allowed citation IDs: %s",
            [s["citation_id"] for s in sources],
        )

        raise OllamaFailure(
            f"Structured answer failed validation: {', '.join(issues)}"
        )

    return answer, sources


@router.post("/index")
def index_document(body: IndexRequest, db: Session = Depends(get_db)):
    doc = db.get(Document, body.document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    model = settings.ollama_embed_model
    pages = db.scalars(select(Page).where(Page.document_id == doc.id)
                       .order_by(Page.page_number).limit(body.max_pages)).all()
    existing = db.scalars(select(ResearchChunk).where(
        ResearchChunk.document_id == doc.id, ResearchChunk.embedding_model == model)).all()
    by_key = {c.chunk_key: c for c in existing}
    added = skipped = 0
    try:
        for page in pages:
            blocks = db.scalars(select(EvidenceBlock).where(
                EvidenceBlock.page_id == page.id, EvidenceBlock.block_type == "text")
                .order_by(EvidenceBlock.id)).all()
            for index, (content, bbox) in enumerate(chunks_for_page(blocks)):
                key = f"p{page.page_number:05d}-c{index:04d}"
                previous = by_key.get(key)
                if previous and not body.force and previous.content == content:
                    skipped += 1
                    continue
                vector = embed(content)
                if previous:
                    previous.vector, previous.content, previous.bbox = vector, content, bbox
                else:
                    db.add(ResearchChunk(
                        document_id=doc.id, page_id=page.id, page_number=page.page_number,
                        chunk_key=key, embedding_model=model, content=content,
                        bbox=bbox, vector=vector))
                added += 1
            db.commit()
    except OllamaFailure as exc:
        db.rollback()
        raise HTTPException(502, f"{exc}; {added} chunks processed before failure") from exc
    total = db.scalar(select(func.count(ResearchChunk.id)).where(
        ResearchChunk.document_id == doc.id, ResearchChunk.embedding_model == model))
    return {"document_id": doc.id, "embedding_model": model,
            "indexed_new_or_updated": added, "skipped_unchanged": skipped,
            "total_chunks": total, "pages_considered": len(pages),
            "note": "Incremental index. Existing chunks retained; no reindex needed for Phase 3.1."}


@router.get("/status/{document_id}")
def index_status(document_id: str, db: Session = Depends(get_db)):
    if not db.get(Document, document_id):
        raise HTTPException(404, "Document not found")
    chunks = db.scalar(select(func.count(ResearchChunk.id)).where(
        ResearchChunk.document_id == document_id,
        ResearchChunk.embedding_model == settings.ollama_embed_model))
    pages = db.scalar(select(func.count(func.distinct(ResearchChunk.page_number))).where(
        ResearchChunk.document_id == document_id,
        ResearchChunk.embedding_model == settings.ollama_embed_model))
    return {"document_id": document_id, "embedding_model": settings.ollama_embed_model,
            "indexed_chunks": chunks, "indexed_pages": pages}


def structured_evidence_for_sources(doc, sources, max_pages=3):
    """Read-only, bounded inspection; never present candidate math as verified."""
    from pathlib import Path
    from .phase33 import inspect_page

    if not Path(doc.file_path).is_file():
        return {"status": "unavailable", "reason": "Original PDF not found", "pages": []}
    page_numbers = list(dict.fromkeys(
        s["page_number"] for s in sources if isinstance(s.get("page_number"), int)
    ))[:max_pages]
    pages = []
    for page_number in page_numbers:
        try:
            result = inspect_page(doc.file_path, page_number)
        except (ValueError, OSError, RuntimeError) as exc:
            pages.append({"page_number": page_number, "status": "error", "reason": str(exc)})
            continue
        pages.append({
            "page_number": page_number,
            "source_url": source_url(doc.id, page_number),
            "equations": [{
                "raw_text": e["raw_text"],
                "bbox": e["bbox"],
                "status": e["status"],
                "latex": e.get("latex"),
                "structure_candidate": e.get("structure_candidate"),
                "verified": False,
            } for e in result["equation_candidates"]],
            "tables": [{
                "bbox": t["bbox"], "rows": t["rows"],
                "status": t["status"], "verified": False,
            } for t in result["tables"]],
        })
    return {
        "status": "candidate_evidence_only",
        "pages": pages,
        "warning": "Equation/table candidates are NOT verified. Do not use as authoritative formulas without checking the PDF.",
    }


@router.post("/ask")
def ask(body: AskRequest, db: Session = Depends(get_db)):
    doc = db.get(Document, body.document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    stored = db.scalars(select(ResearchChunk).where(
        ResearchChunk.document_id == body.document_id,
        ResearchChunk.embedding_model == settings.ollama_embed_model)).all()
    if not stored:
        raise HTTPException(409, "No research index found. Run POST /api/v1/research/index first.")
    try:
        query_vector = embed(body.question)
    except OllamaFailure as exc:
        raise HTTPException(502, str(exc)) from exc
    ranked = retrieve_chunks(body.question, query_vector, stored, body.top_k)
    sources = [source_record(chunk, score, i + 1)
               for i, (score, chunk) in enumerate(ranked)]
    if body.mode == "retrieve":
        result = {"mode": "retrieve", "answer": None, "sources": sources,
                  "model": settings.ollama_embed_model,
                  "warning": "Similarity is not proof of relevance. Verify original PDF pages."}
        if body.include_structured_evidence:
            result["structured_evidence"] = structured_evidence_for_sources(doc, sources)
        return result
    try:
        answer, used_sources = generate_answer(body.question, sources)
    except OllamaFailure as exc:
        raise HTTPException(502, str(exc)) from exc
    result = {"mode": "local_rag", "answer": answer, "sources": used_sources,
              "model": settings.ollama_text_model,
              "warning": "Automated checks are not proof of factual accuracy. Verify claims and citations against the PDF."}
    if body.include_structured_evidence:
        result["structured_evidence"] = structured_evidence_for_sources(doc, sources)
    return result


# Phase 3.1.1 helper constants

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+", re.I)
_STOP = frozenset('the a an of to and or in for is are with how what explain difference between from that this be by at on as do does using can we it its their about model models time series data'.split())
_ALIASES = {
    'seasonality': {'seasonal', 'seasonality', 'periodic'},
    'seasonal': {'seasonal', 'seasonality', 'periodic'},
    'forecasting': {'forecast', 'forecasts', 'forecasting'},
    'forecast': {'forecast', 'forecasts', 'forecasting'},
    'limitations': {'limitations', 'limitation', 'assumptions', 'uncertainty', 'errors', 'residuals', 'accuracy'},
    'limitation': {'limitations', 'limitation', 'assumptions', 'uncertainty', 'errors', 'residuals', 'accuracy'},
    'smoothing': {'smoothing', 'smooth', 'ets'},
    'arima': {'arima'},
    'acf': {'acf', 'autocorrelation'},
    'pacf': {'pacf', 'partial'},
}




# Phase 4.1: unified response built on existing retrieval and evidence services.
class UnifiedRequest(BaseModel):
    document_id: str
    question: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=8)
    mode: str = Field(default="retrieve", pattern="^(answer|retrieve)$")
    include_visual_evidence: bool = False
    visual_page_number: int | None = Field(default=None, ge=1)
    visual_region: list[float] | None = Field(default=None, min_length=4, max_length=4)


def _formula_conflicts(evidence, vision_text, page_number):
    """Flag missing parenthesized factors in the *same named formula*.

    A conservative text-level safeguard, not a mathematical equivalence test.
    Other formulas and prose in the model response are ignored.
    """
    import re

    def normalize(text):
        text = (text or "").lower()
        text = text.replace("\\left", "").replace("\\right", "")
        text = text.replace("\\mathrm", "").replace("\\text", "")
        text = text.replace("\\operatorname", "")
        text = text.replace("\\_", "_")
        text = re.sub(r"\s+", "", text)
        text = text.replace("{", "").replace("}", "")
        text = text.replace("_", "")
        return text

    # Inspect the formula statement itself, not explanatory prose that may
    # incidentally mention missing factors.
    statements = [line.strip() for line in (vision_text or "").splitlines() if "=" in line]
    conflicts = []
    for page in evidence.get("pages", []):
        if page.get("page_number") != page_number:
            continue
        for equation in page.get("equations", []):
            raw = equation.get("raw_text", "")
            if "=" not in raw:
                continue
            lhs = normalize(raw.split("=", 1)[0])
            # Restrict comparison to a short, named LHS (e.g. AICc, BIC).
            if not re.fullmatch(r"[a-z][a-z0-9]{1,15}", lhs):
                continue
            matching = [line for line in statements
                        if normalize(line.split("=", 1)[0]).endswith(lhs)]
            if not matching:
                continue
            visual_formula = normalize(matching[0])
            source_factors = re.findall(r"\([^()]+\)", normalize(raw))
            # Compare factors, including repeated factors, against the formula.
            missing = [factor for factor in source_factors
                       if factor not in visual_formula]
            if missing:
                conflicts.append({
                    "source_equation": raw,
                    "visual_formula": matching[0],
                    "missing_parenthesized_terms": missing,
                    "status": "possible_disagreement_requires_review",
                })
    return conflicts


@router.post("/unified")
def unified_research(body: UnifiedRequest, db: Session = Depends(get_db)):
    """Unified, opt-in workflow. No index or DB mutations."""
    if body.include_visual_evidence and body.visual_page_number is None:
        raise HTTPException(422, "visual_page_number is required when include_visual_evidence is true")
    research = ask(AskRequest(
        document_id=body.document_id,
        question=body.question,
        top_k=body.top_k,
        mode=body.mode,
        include_structured_evidence=True,
    ), db)
    result = {
        "document_id": body.document_id,
        "question": body.question,
        "mode": research["mode"],
        "answer": research.get("answer"),
        "sources": research["sources"],
        "structured_evidence": research.get("structured_evidence"),
        "visual_evidence": None,
        "validation": {
            "status": "unverified",
            "warnings": ["Retrieved content and equation candidates are not proof of factual correctness."],
            "possible_disagreements": [],
        },
    }
    if body.include_visual_evidence:
        from .phase34 import VisionRequest, inspect_visual
        page = body.visual_page_number
        # Require the requested visual page to be among the cited retrieval pages.
        if page not in {s["page_number"] for s in research["sources"]}:
            raise HTTPException(422, "Visual page must be one of the retrieved source pages")
        visual = inspect_visual(VisionRequest(
            document_id=body.document_id,
            page_number=page,
            region=body.visual_region,
            question=body.question,
        ), db)
        result["visual_evidence"] = visual
        discrepancies = _formula_conflicts(
            result["structured_evidence"] or {}, visual["interpretation"], page
        )
        result["validation"]["possible_disagreements"] = discrepancies
        if discrepancies:
            result["validation"]["warnings"].append(
                "Visual interpretation may omit source equation terms; verify the original PDF."
            )
        result["validation"]["warnings"].append(
            "Visual interpretation is model-generated and unverified."
        )
    return result
