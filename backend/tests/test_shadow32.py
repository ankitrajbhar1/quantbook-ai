from app.shadow32 import preview_page


def block(text, n):
    return {'text': text, 'bbox': [20.0, float(n * 15), 220.0, float(n * 15 + 10)],
            'original_order': n, 'column': 'full', 'kind': 'text'}


def test_safe_preview_preserves_text_and_coordinates():
    source = {'page_number': 5, 'layout': 'single_or_complex',
              'blocks': [block('Forecasting methods are useful.', 1), block('Model fitting follows.', 3)]}
    out = preview_page(source)
    assert out['indexing_safe'] and out['candidate_chunks'] == 1
    assert 'Forecasting methods' in out['chunks'][0]['content']
    assert out['chunks'][0]['bbox'] == [20.0, 15.0, 220.0, 55.0]


def test_flowchart_is_quarantined():
    source = {'page_number': 79, 'layout': 'two_column_candidate', 'blocks': [
        block('Select model', 1), block('auto.arima()', 2), block('white noise', 3),
        block('calculate forecasts', 4), block('yes', 5)]}
    out = preview_page(source)
    assert not out['indexing_safe']
    assert out['chunks'] == []
    assert out['quarantined_segments'] > 0


def test_formula_fragment_is_quarantined():
    source = {'page_number': 76, 'layout': 'single_or_complex',
              'blocks': [block('√', 1), block('T as for ACF', 2)]}
    out = preview_page(source)
    assert out['visual_review_required']
    assert not out['chunks']
