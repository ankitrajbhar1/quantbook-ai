from pathlib import Path
import pymupdf
from app.phase33 import inspect_page

def test_equation_candidates_are_unverified(tmp_path):
    path = tmp_path / 'math.pdf'
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), 'AIC = -2log(L) + 2k')
    doc.save(path)
    doc.close()
    result = inspect_page(path, 1)
    assert result['equation_candidates']
    assert result['equation_candidates'][0]['latex'] is None
    assert result['equation_candidates'][0]['status'] == 'needs_visual_verification'

def test_plain_prose_is_not_equation(tmp_path):
    path = tmp_path / 'plain.pdf'
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), 'Forecasting is useful for planning.')
    doc.save(path)
    doc.close()
    assert inspect_page(path, 1)['equation_candidates'] == []
