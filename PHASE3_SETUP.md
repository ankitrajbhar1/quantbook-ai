# QuantBook AI Phase 3 — Local book research (M1 8 GB)

This is a **full project** based on the working Phase 2 Ollama Fixed code. It adds semantic indexing, retrieval and grounded answers. **No OpenAI key required.**

## Preserve your existing data

Back up your project. **Do not delete Docker volumes** or `backend/storage`. Merge new files into your existing project root, or copy your existing `.env` and `storage` into this extracted project and ensure it connects to the same Docker database. The new `research_chunks` table is created automatically at startup. Existing document IDs and analyses remain.

From project root: `./scripts/start_mac.sh`. Ensure Ollama is running and models are installed: `ollama list` should show `nomic-embed-text`, `qwen3:4b`, and `gemma3:4b`.

`backend/.env`:

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_VISION_MODEL=gemma3:4b
OLLAMA_TEXT_MODEL=qwen3:4b
OLLAMA_EMBED_MODEL=nomic-embed-text
```

## Try the known book

Open http://127.0.0.1:8000/ and choose your uploaded book. Click **Index first 5 pages**; this is intentionally synchronous and may take time. Then try **Find evidence only** or **Ask book**. To answer questions across all 138 pages, use **Index entire book** once. Existing chunks are skipped on repeat indexing. Do not index concurrently.

Swagger examples:

`POST /api/v1/research/index`:
```json
{"document_id":"62539443-b7ef-46a6-b059-ff58a2706fda","max_pages":5,"force":false}
```
`GET /api/v1/research/status/62539443-b7ef-46a6-b059-ff58a2706fda`

`POST /api/v1/research/ask`:
```json
{"document_id":"62539443-b7ef-46a6-b059-ff58a2706fda","question":"What is autocorrelation and how is it used in residual diagnostics?","top_k":5,"mode":"answer"}
```
Set `mode` to `retrieve` for source retrieval without Qwen generation.

## Accuracy and memory

Each source includes the original PDF page, source image URL, original PDF URL with `#page=`, excerpt, and a source bbox when available. The model must cite `[S1]` etc, but answers still require verification. These are PDF page numbers, not necessarily printed book page labels. No automatic trading/backtesting claims. Page text is indexed; visual-only content needs Phase 2 page analysis and is not automatically in the semantic index.

Embeddings are stored in PostgreSQL as JSON vectors (portable but **not pgvector ANN**). Similarity is calculated in Python. This is suitable for a 138-page prototype but not a large library; use pgvector indexing for scale. Text chunks are page-local; no chapter detection yet. `keep_alive: 0` unloads models between requests, but Qwen 4B can still cause memory pressure while active. Use only one request at a time; don't run vision and Q&A concurrently. The full indexing endpoint is synchronous and can be slow.

If the embedding model changes, new embeddings are stored under its model name. Reindexing with `force=true` updates existing chunks. Changing original PDF content requires reuploading and reindexing.
