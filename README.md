# QuantBook AI — Phase 2 (upgrade from Phase 1)

A runnable **local PDF research workspace** with optional **cloud multimodal analysis** for trading/finance/quant books. Built by extending the provided Phase 1 source, retaining its original upload, page and evidence APIs.

## Requirements (Apple Silicon Mac)

- Docker Desktop (running), Python 3.11 or 3.12, VS Code.
- No separate PostgreSQL installation; Docker uses `pgvector/pgvector:pg16`.
- Optional cloud API key and internet for actual chart/formula understanding. No key needed for offline text preview.
- Node.js is **not** required: the workspace is served directly by FastAPI.

## Run

1. Extract this ZIP. Open `quantbook-ai` in VS Code.
2. Ensure Docker Desktop is running.
3. **If upgrading your existing installation, copy `backend/.env` and `backend/storage/` from the old project into this one** (if your previous storage directory exists). Existing Postgres data lives in the named Docker volume. **Do not run `docker compose down -v`.** For an in-place upgrade, back up your folder first, then merge the new files into the original project directory, keeping `.env` and `storage` unchanged.
4. Review `backend/.env` (create it from `backend/.env.example` if missing). This project uses host port **5433** to avoid your prior 5432 conflict, and the Docker password `quantbook_dev`.
5. From the project root:

   ```bash
   chmod +x scripts/start_mac.sh
   ./scripts/start_mac.sh
   ```

6. Open **http://127.0.0.1:8000/** for the workspace, or **http://127.0.0.1:8000/docs** for Swagger.
7. Upload a small PDF; select its page; click **Analyze page**. Offline mode creates *text excerpts only* and does not interpret images.

**Existing DB upgrade:** New tables `page_analyses` and `knowledge_items` are created automatically at startup with `Base.metadata.create_all`. Existing Phase 1 tables are preserved. This is an additive MVP schema upgrade, not a general migration system. Production should use Alembic.

### Turn on multimodal vision (optional, paid)

Edit `backend/.env`:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Restart FastAPI. The model must support image input and JSON-object response format. Only the **selected page image and extracted text** are sent to the cloud provider on Analyze. The API key stays in `.env`; do not commit it. The default is `AI_PROVIDER=offline`, which sends nothing to the cloud.

Vision responses can be wrong, especially about plotted values, chart patterns, equations and exact coordinates. Items are saved as **unreviewed**, and any unverified box is set to `null`. Never use extracted strategies for live execution without independent verification and backtesting.

### Phase 2 endpoints

- `POST /api/v1/documents/{id}/pages/{n}/analyze` JSON `{ "force": false }` — analyze/cached response. `force=true` refreshes (cloud charges possible).
- `GET /api/v1/documents/{id}/pages/{n}/analysis` — saved analysis outputs.
- `GET /api/v1/documents/{id}/knowledge?kind=formula` — structured concepts, formulas, charts and rules with source page references.
- `POST /api/v1/research/search` JSON `{ "document_id":"...", "question":"moving average" }` — **keyword evidence retrieval**, not AI-generated Q&A.
- Existing Phase 1 upload, page, PDF, image, and search endpoints remain unchanged.

### Verify database

```bash
docker compose ps
docker compose exec db pg_isready -U quantbook -d quantbook
docker compose exec db psql -U quantbook -d quantbook -c '\dt'
```

Expected new tables include `page_analyses` and `knowledge_items` in addition to `documents`, `pages`, `evidence_blocks`.

### Run automated tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

### Limitations / next work

- Scanned PDFs require cloud vision for understanding; offline mode cannot OCR them.
- No vector embedding retrieval, autonomous trading agent, mathematical proof verification, or backtesting in this release.
- Source coordinates from AI are **untrusted suggestions**, not guaranteed pixel-perfect; missing/unverified boxes are `null`.
- Uploads and analysis are synchronous; large books can be slow. Use small samples first.
- Local development server has no authentication. Do **not** expose it publicly.
- API request failures are surfaced to the client without provider secrets; check server logs for details.


## Local multimodal AI (Ollama, Apple M1 8 GB)

This edition adds `AI_PROVIDER=ollama` support to the existing **page analysis** endpoint.
It does **not** yet add semantic retrieval or generative book-wide Q&A.

1. Install Ollama and download `gemma3:4b` (`ollama pull gemma3:4b`).
2. Confirm `curl http://127.0.0.1:11434/api/tags` returns the model.
3. In `backend/.env` set `AI_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_VISION_MODEL=gemma3:4b`.
4. Restart FastAPI. Reuse existing document IDs and database. Do **not** run `docker compose down -v`.
5. In the Research Workspace, analyze page 28, or POST `/api/v1/documents/{id}/pages/28/analyze` with `{"force":true}`.

The image is sent to the locally running Ollama service using `/api/chat` with `format=json`.
Requests may take several minutes on an 8 GB M1. The model unloads after each request to save memory.
Results are machine-generated and may contain errors; always inspect the source PDF page.
The source URL links to the PDF page image; model-suggested bounding boxes are accepted only when valid.
Keep your existing `.env` and `backend/storage` when merging. Never commit API keys.
