from app.vision import offline_extract

def test_offline_does_not_hallucinate_charts_or_rules():
    result = offline_extract('Moving average is a mean.\nChart shown below')
    assert result['charts'] == []
    assert result['rules'] == []
    assert result['formulas'] == []
    assert len(result['concepts']) == 2
    assert 'NOT been interpreted' in result['warnings'][0]

def test_phase2_routes_exist():
    from app.main import app
    paths = {route.path for route in app.routes}
    assert '/api/v1/documents/{document_id}/pages/{page_number}/analyze' in paths
    assert '/api/v1/documents/{document_id}/knowledge' in paths
    assert '/api/v1/research/search' in paths
