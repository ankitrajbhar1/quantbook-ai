"""Offline regression checks for pure Phase 3.1 helpers; no DB/Ollama required."""
import ast
import math
import re
import unittest
from collections import Counter
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "phase3.py"
TREE = ast.parse(SOURCE.read_text())
NAMES = {"clean_context", "keywords", "lexical_score", "cosine", "retrieve_chunks",
         "extract_final_answer", "answer_issues"}
KEEP = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
ENV = {"re": re, "math": math, "Counter": Counter}
exec(compile(ast.Module(body=KEEP, type_ignores=[]), str(SOURCE), "exec"), ENV)
ENV["CHART_NOISE"] = re.compile(r"(?m)^\s*(?:G\s*){4,}$")
ENV["TOKEN"] = re.compile(r"[a-z0-9]+(?:\([0-9,]+\))?", re.I)
ENV["REASONING_LEADS"] = ("i need to", "let me", "i'll craft", "i will now", "the user wants", "i should", "first, i", "i'll analyze", "i must", "let's analyze")
ENV["STOP"] = frozenset("the a an of to and or in for is are with how what explain difference between from that this be by at on as do does using can we it its their about model models time series data".split())

class TestPhase31(unittest.TestCase):
    def test_chart_noise_removed(self):
        result = ENV["clean_context"]("G G G G G G\nAutocorrelation is useful.\nG G G G G")
        self.assertIn("Autocorrelation", result)
        self.assertNotIn("G G G", result)

    def test_math_preserved(self):
        result = ENV["clean_context"]("ARIMA(0,1,1) and ±1.96/√T")
        self.assertIn("ARIMA(0,1,1)", result)
        self.assertIn("±1.96/√T", result)

    def test_thinking_removed(self):
        answer = ENV["extract_final_answer"]({"content": "I need to think.\n</think>\nAnswer [S1]."})
        self.assertEqual(answer, "Answer [S1].")

    def test_unclosed_thinking_rejected(self):
        self.assertEqual(ENV["extract_final_answer"]({"content": "<think>unfinished"}), "")

    def test_missing_citation_rejected(self):
        self.assertIn("missing_or_invalid_citations", ENV["answer_issues"]("No source.", [{"citation_id":"S1", "text":"Hello"}]))

    def test_unseen_arima_rejected(self):
        issues = ENV["answer_issues"]("ARIMA(9,9,9) is best [S1].", [{"citation_id":"S1", "text":"ARIMA(0,1,1)"}])
        self.assertIn("unseen_arima_order", issues)

    def test_wrong_ses_equivalence_rejected(self):
        issues = ENV["answer_issues"]("Simple exponential smoothing is equivalent to ARIMA(0,2,2) [S1].", [{"citation_id":"S1", "text":"ARIMA(0,2,2)"}])
        self.assertIn("incorrect_ses_equivalence", issues)

    def test_good_answer(self):
        self.assertEqual(ENV["answer_issues"]("ACF measures lag correlation [S1].", [{"citation_id":"S1", "text":"ACF measures lag correlation"}]), [])

if __name__ == "__main__":
    unittest.main()
