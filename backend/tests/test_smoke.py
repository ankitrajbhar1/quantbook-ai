from app.models import Document, Page, EvidenceBlock

def test_tables_exist():
    assert Document.__tablename__ == "documents"
    assert Page.__tablename__ == "pages"
    assert EvidenceBlock.__tablename__ == "evidence_blocks"
