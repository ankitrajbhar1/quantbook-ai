import pymupdf
from app.layout32 import extract_page_layout, extract_pdf_page


def test_two_columns_keep_column_reading_order(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=500)
    page.insert_text((40, 80), "LEFT FIRST forecast concepts")
    page.insert_text((340, 80), "RIGHT FIRST forecast concepts")
    page.insert_text((40, 140), "LEFT SECOND forecasting models")
    page.insert_text((340, 140), "RIGHT SECOND forecasting models")
    page.insert_text((40, 200), "LEFT THIRD forecasting examples")
    page.insert_text((340, 200), "RIGHT THIRD forecasting examples")
    path = tmp_path / "layout.pdf"
    pdf.save(path)
    pdf.close()
    result = extract_pdf_page(path, 1)
    assert result["layout"] == "two_column_candidate"
    text = result["reading_text"]
    assert text.index("LEFT FIRST") < text.index("LEFT SECOND") < text.index("RIGHT FIRST")
    assert all(len(b["bbox"]) == 4 for b in result["blocks"])


def test_single_column_and_page_bounds(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Forecasting summary")
    path = tmp_path / "one.pdf"
    pdf.save(path)
    pdf.close()
    assert extract_pdf_page(path, 1)["layout"] == "single_or_complex"
    try:
        extract_pdf_page(path, 2)
    except ValueError:
        pass
    else:
        raise AssertionError("Out-of-range page should fail")
