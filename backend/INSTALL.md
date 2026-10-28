# Phase 3.2.2 CPU-only shadow preview

Copy `app/shadow32.py` into `backend/app/` and `tests/test_shadow32.py` into `backend/tests/`. Do not replace any existing files.

Run `python -m pytest -q tests/test_shadow32.py` from backend with the virtual environment active.

Then preview pages using the existing uploaded PDF file path stored in `documents.file_path` (or another known PDF path):

```bash
python - <<'PY'
import json
from pathlib import Path
from app.shadow32 import preview_pdf

pdf = Path(input('Absolute PDF path: ').strip()).expanduser()
report = preview_pdf(pdf, [76, 77, 79, 92])
out = Path.home() / 'Downloads' / 'quantbook-shadow-preview.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
for page in report['pages']:
    print(page['page_number'], 'safe=', page['indexing_safe'],
          'chunks=', page['candidate_chunks'],
          'chart=', page['excluded_chart_segments'])
print('Saved:', out)
PY
```

This stage is intentionally a preview only: no shadow table, embeddings, or retrieval switch is created. Inspect its content before any database integration.
