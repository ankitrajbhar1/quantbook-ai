"""QuantBook AI Phase 3.1.1 retrieval helpers. No model calls or schema changes."""
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
    """Hybrid relevance, noise penalties, and diversity; preserves (cosine, chunk) API."""
    candidates = []
    for chunk in stored:
        semantic = cosine(query_vector, chunk.vector)
        if not math.isfinite(semantic):
            continue
        lexical = _coverage(question, chunk.content)
        score = (0.68 * semantic + 0.32 * lexical
                 + _focused_bonus(question, chunk.content)
                 - _toc_penalty(chunk.content)
                 - _noise_penalty(chunk.content))
        candidates.append((score, semantic, chunk))
    candidates.sort(key=lambda row: (-row[0], str(row[2].id)))
    # Consider the full small document index (199 chunks), not only the top 20.
    pool = candidates[:max(80, top_k * 15)]
    selected, pages = [], Counter()
    while pool and len(selected) < top_k:
        best_index, best_value = 0, -float('inf')
        for i, (score, semantic, chunk) in enumerate(pool):
            duplication = max((_jaccard(chunk.content, s[2].content) for s in selected), default=0.0)
            value = score - 0.09 * pages[chunk.page_number] - 0.10 * duplication
            if value > best_value:
                best_index, best_value = i, value
        chosen = pool.pop(best_index)
        selected.append(chosen)
        pages[chosen[2].page_number] += 1
    return [(semantic, chunk) for _, semantic, chunk in selected]
