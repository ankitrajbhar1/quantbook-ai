"""Run: python tests/smoke_api.py [optional-base-url]. Requires running backend + Ollama."""
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
DOC = "62539443-b7ef-46a6-b059-ff58a2706fda"
QUESTIONS = [
    ("What is white noise, and how can autocorrelation help identify it?", ["white noise"]),
    ("How do ACF and PACF help identify ARIMA model orders?", ["acf", "pacf"]),
    ("How can seasonality be detected using autocorrelation?", ["season"]),
    ("Explain the difference between exponential smoothing and ARIMA.", ["arima", "smoothing"]),
    ("What are the limitations of forecasting models?", ["forecast"]),
]

def request(question):
    body = json.dumps({"document_id": DOC, "question": question, "top_k": 5, "mode": "answer"}).encode()
    req = urllib.request.Request(BASE + "/api/v1/research/ask", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as response:
        return json.load(response)

failures = 0
for number, (question, expected) in enumerate(QUESTIONS, 1):
    try:
        result = request(question)
        answer = result.get("answer", "")
        sources = result.get("sources", [])
        ok = bool(answer) and bool(sources) and all(word in answer.lower() for word in expected)
        if "simple exponential smoothing" in answer.lower() and "arima(0,2,2)" in answer.lower():
            ok = False
        print(f"{'PASS' if ok else 'REVIEW'} {number}: {question}")
        print("  ", answer[:500].replace("\n", " "))
        print("   pages:", [s["page_number"] for s in sources])
        failures += not ok
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        failures += 1
        print(f"FAIL {number}: {exc}")
print(f"\n{len(QUESTIONS) - failures}/{len(QUESTIONS)} basic smoke checks passed")
print("NOTE: Keyword smoke checks cannot establish factual correctness; review cited pages.")
sys.exit(bool(failures))
