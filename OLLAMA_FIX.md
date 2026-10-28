# Ollama page analysis fix (M1 8 GB)

This build replaces the Ollama extraction path with structured JSON schema, bounded page image dimensions, shorter context, explicit validation and model unloading. It preserves the existing database and APIs.

## Upgrade
Back up your project. Replace `backend/app/vision.py` with this version (or merge the entire ZIP, preserving `.env`, `storage/`, and Docker volumes). Restart FastAPI.

Ensure `AI_PROVIDER=ollama`, `OLLAMA_VISION_MODEL=gemma3:4b` in `backend/.env`.

## Test
```sh
curl -sS -X POST 'http://127.0.0.1:8000/api/v1/documents/62539443-b7ef-46a6-b059-ff58a2706fda/pages/28/analyze' -H 'Content-Type: application/json' -d '{"force":true}' | python -m json.tool
```

If 502 persists, read the traceback in the FastAPI terminal. The application deliberately rejects malformed responses rather than saving fake empty results.

Note: Local 4B models may still struggle with complex charts, and inference can be slow on 8 GB RAM.
