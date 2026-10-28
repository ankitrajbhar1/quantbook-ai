# QuantBook AI Phase 3.2 — isolated shadow-index integration

## Install
From `~/Downloads/quantbook-ai/backend`:

```bash
unzip -o ~/Downloads/quantbook-phase32-integrated.zip -d .
python -m pytest -q tests/test_shadow32_index.py
```

Append **once** to `app/main.py` (if not already present):

```python
from .shadow32_index import router as shadow32_router
app.include_router(shadow32_router)
```

Restart your existing FastAPI server. PostgreSQL must be running for the two endpoints; Ollama is not required.

## One end-to-end acceptance test

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/shadow32/build \
 -H 'Content-Type: application/json' \
 -d '{"document_id":"62539443-b7ef-46a6-b059-ff58a2706fda","pages":[76,77,79,92]}' | python3 -m json.tool

curl -sS -X POST http://127.0.0.1:8000/api/v1/shadow32/compare \
 -H 'Content-Type: application/json' \
 -d '{"document_id":"62539443-b7ef-46a6-b059-ff58a2706fda","question":"Which ARIMA model is equivalent to Holt method?","top_k":3}' | python3 -m json.tool
```

This writes to an **isolated SQLite** shadow database under the configured `storage_root`, not to the existing `research_chunks` table. It deliberately quarantines page 77 because of suspected broken math, along with pages 76 and 79. Page 92 remains eligible. Search comparison uses simple lexical overlap and is **not** an embedding/semantic quality benchmark. It is limited to the four explicitly built pages and is not production-ready full-book ingestion.
