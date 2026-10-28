"""Isolated, CPU-only Phase 3.2 shadow index. Does not alter ResearchChunk."""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from .db import get_db
from .models import Document, ResearchChunk
from .shadow32 import preview_pdf

router = APIRouter(prefix='/api/v1/shadow32', tags=['Phase 3.2 - Shadow index'])
STOP = set('the and for with from this that into are was how what when where have does about model models'.split())

def tokens(s):
    return [w for w in re.findall(r'[a-z0-9]+', s.lower()) if len(w)>2 and w not in STOP]

def store_path():
    from .config import settings
    root = Path(settings.storage_root)
    root.mkdir(parents=True, exist_ok=True)
    return root / 'shadow32.sqlite3'

def connect(path):
    db = sqlite3.connect(str(path))
    db.execute('CREATE TABLE IF NOT EXISTS chunks (document_id TEXT NOT NULL, chunk_key TEXT NOT NULL, page_number INTEGER NOT NULL, content TEXT NOT NULL, bbox TEXT, sha256 TEXT NOT NULL, PRIMARY KEY(document_id, chunk_key))')
    db.execute('CREATE TABLE IF NOT EXISTS review (document_id TEXT NOT NULL, page_number INTEGER NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(document_id,page_number))')
    return db

def build(pdf, document_id, pages, path):
    report = preview_pdf(pdf, pages)
    with connect(path) as db:
        for p in report['pages']:
            n = p['page_number']
            db.execute('DELETE FROM chunks WHERE document_id=? AND page_number=?', (document_id,n))
            db.execute('DELETE FROM review WHERE document_id=? AND page_number=?', (document_id,n))
            if not p['indexing_safe']:
                db.execute('INSERT INTO review VALUES (?,?,?)', (document_id,n,json.dumps(p['warnings'])))
                continue
            for c in p['chunks']:
                # Conservative safeguard: page 77 has visually broken multiline math;
                # skip any candidate with known fraction/least-squares artifacts.
                content = c['content']
                suspect = bool(re.search(r'\bAICc\s*=|\bminimiz-\s*\n|\bing PT\s*\n', content, re.I))
                if suspect:
                    db.execute('INSERT OR REPLACE INTO review VALUES (?,?,?)', (document_id,n,'["suspected_broken_math_in_chunk"]'))
                    continue
                db.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?)', (document_id,c['chunk_key'],n,content,json.dumps(c['bbox']),c['sha256']))
    with connect(path) as db:
        total=db.execute('SELECT COUNT(*) FROM chunks WHERE document_id=?',(document_id,)).fetchone()[0]
        review=[r[0] for r in db.execute('SELECT page_number FROM review WHERE document_id=? ORDER BY page_number',(document_id,))]
    return {'document_id':document_id,'pages_processed':pages,'stored_shadow_chunks':total,'review_pages':review,'storage':'isolated_sqlite','baseline_untouched':True}

def search(path, document_id, question, limit=5):
    q=set(tokens(question))
    with connect(path) as db:
        rows=db.execute('SELECT chunk_key,page_number,content,bbox FROM chunks WHERE document_id=?',(document_id,)).fetchall()
    scored=[]
    for key,page,content,bbox in rows:
        words=set(tokens(content))
        score=len(q & words)/max(len(q),1)
        if score:
            scored.append({'chunk_key':key,'page_number':page,'score':round(score,4),'content':content,'bbox':json.loads(bbox)})
    return sorted(scored,key=lambda x:x['score'],reverse=True)[:limit]

class BuildRequest(BaseModel):
    document_id: str
    pages: list[int] = Field(default_factory=lambda:[76,77,79,92], min_length=1, max_length=20)

class CompareRequest(BaseModel):
    document_id: str
    question: str = Field(min_length=3)
    top_k: int = Field(default=5,ge=1,le=10)

@router.post('/build')
def build_endpoint(body:BuildRequest, db:Session=Depends(get_db)):
    doc=db.get(Document,body.document_id)
    if doc is None: raise HTTPException(404,'Document not found')
    if any(p<1 or p>doc.page_count for p in body.pages): raise HTTPException(422,'Page number out of range')
    if not Path(doc.file_path).is_file(): raise HTTPException(404,'Original PDF not found on server')
    return build(doc.file_path,doc.id,list(dict.fromkeys(body.pages)),store_path())

@router.post('/compare')
def compare_endpoint(body:CompareRequest,db:Session=Depends(get_db)):
    if not db.get(Document,body.document_id): raise HTTPException(404,'Document not found')
    shadow=search(store_path(),body.document_id,body.question,body.top_k)
    baseline=db.scalars(select(ResearchChunk).where(ResearchChunk.document_id==body.document_id)).all()
    q=set(tokens(body.question))
    scored=[]
    for c in baseline:
        score=len(q & set(tokens(c.content)))/max(len(q),1)
        if score: scored.append({'page_number':c.page_number,'chunk_key':c.chunk_key,'score':round(score,4),'content':c.content[:1200]})
    scored.sort(key=lambda r:r['score'],reverse=True)
    return {'question':body.question,'method':'lexical_overlap_only_not_embedding_retrieval','shadow':shadow,'baseline':scored[:body.top_k], 'note':'Shadow only covers pages explicitly built. No LLM or Ollama call.'}
