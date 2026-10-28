"""CPU-only, read-only shadow chunk preview for QuantBook AI Phase 3.2.2."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from .layout32 import extract_pdf_page
from .layout32_correct import correct_layout


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def preview_page(layout: dict, target: int = 1100) -> dict:
    if target < 100:
        raise ValueError('target must be >= 100')
    result = correct_layout(layout)
    page = result['page_number']
    safe = bool(result['indexing_safe'])
    chunks = []
    pieces = []
    boxes = []

    def flush():
        if not pieces:
            return
        content = '\n'.join(pieces)
        key = f'p{page:05d}-s{len(chunks):04d}'
        chunks.append({'chunk_key': key, 'page_number': page,
                       'content': content, 'bbox': _union(boxes),
                       'sha256': hashlib.sha256(content.encode('utf-8')).hexdigest()})
        pieces.clear()
        boxes.clear()

    if safe:
        for seg in result['segments']:
            if seg['kind'] == 'chart_text':
                continue
            text = re.sub(r'\s+', ' ', seg.get('text', '')).strip()
            bbox = seg.get('bbox')
            if not text or not isinstance(bbox, list) or len(bbox) != 4:
                continue
            # Split oversized segments, without losing content.
            for start in range(0, len(text), target):
                piece = text[start:start + target]
                if pieces and sum(map(len, pieces)) + len(piece) > target:
                    flush()
                pieces.append(piece)
                boxes.append(bbox)
        flush()

    return {'page_number': page, 'indexing_safe': safe,
            'visual_review_required': result['visual_review_required'],
            'warnings': result['warnings'], 'chunks': chunks,
            'candidate_chunks': len(chunks),
            'excluded_chart_segments': sum(s['kind'] == 'chart_text' for s in result['segments']),
            'quarantined_segments': len(result['segments']) if not safe else 0,
            'diagnostics': result['diagnostics']}


def preview_pdf(pdf_path: str | Path, pages: list[int], target: int = 1100) -> dict:
    from pymupdf import open as open_pdf
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    with open_pdf(str(pdf_path)) as pdf:
        count = len(pdf)
    if not pages or any(not isinstance(p, int) or p < 1 or p > count for p in pages):
        raise ValueError(f'pages must be in 1..{count}')
    outputs = [preview_page(extract_pdf_page(pdf_path, p), target) for p in pages]
    return {'source_pdf': str(pdf_path), 'page_count': count, 'pages': outputs,
            'total_candidate_chunks': sum(x['candidate_chunks'] for x in outputs),
            'quarantined_pages': [x['page_number'] for x in outputs if not x['indexing_safe']],
            'note': 'Preview only. No database writes or embeddings.'}
