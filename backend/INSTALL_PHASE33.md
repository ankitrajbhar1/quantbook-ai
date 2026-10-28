# QuantBook AI Phase 3.3 — Equation and table inspection

This is a **read-only inspection milestone**, not a finished equation interpreter.
It does not touch PostgreSQL, SQLite, embeddings, Ollama, or the 199 baseline chunks.

## Install
From `~/Downloads/quantbook-ai/backend`:

```bash
unzip -o ~/Downloads/quantbook-phase33.zip -d .
python -m pytest -q tests/test_phase33.py
```

Append these lines **once** to `app/main.py`, after `app` is initialized:

```python
from .phase33 import router as phase33_router
app.include_router(phase33_router)
```

Restart the FastAPI server and test one page:

```bash
curl -sS http://127.0.0.1:8000/api/v1/phase33/documents/62539443-b7ef-46a6-b059-ff58a2706fda/pages/77 | python3 -m json.tool
```

## Acceptance criteria
- Response contains `equation_candidates`, `tables`, and `diagnostics`.
- Equation candidates retain raw PDF text and bounding boxes and are marked `needs_visual_verification`.
- Tables, if detected, retain rows and bounding boxes and are marked `needs_structural_verification`.
- No extracted equation is claimed to be a verified mathematical reconstruction.

**Limitations:** Heuristic candidate detection can miss formulas and produce false positives. `find_tables()` depends on the installed PyMuPDF version and PDF structure. A zero-table result does not prove that a page has no tables.
