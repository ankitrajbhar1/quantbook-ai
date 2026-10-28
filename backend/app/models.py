import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, ForeignKey, DateTime, JSON, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    pages: Mapped[list["Page"]] = relationship(back_populates="document", cascade="all, delete-orphan")

class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer) # PDF physical page, 1-based
    printed_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    image_path: Mapped[str] = mapped_column(Text)
    document: Mapped[Document] = relationship(back_populates="pages")
    blocks: Mapped[list["EvidenceBlock"]] = relationship(back_populates="page", cascade="all, delete-orphan")

class EvidenceBlock(Base):
    __tablename__ = "evidence_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    block_type: Mapped[str] = mapped_column(String(20)) # text / image
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox: Mapped[list] = mapped_column(JSON) # PDF coordinates, top-left origin
    asset_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    page: Mapped[Page] = relationship(back_populates="blocks")

class PageAnalysis(Base):
    __tablename__ = "page_analyses"
    __table_args__ = (UniqueConstraint("page_id", "provider", "model", name="uq_page_analysis_provider_model"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("page_analyses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(250))
    body_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    provenance: Mapped[str] = mapped_column(String(24), default="model_inference")
    review_status: Mapped[str] = mapped_column(String(24), default="unreviewed")


class ResearchChunk(Base):
    """Portable local vector store. JSON vectors avoid requiring a pgvector migration."""
    __tablename__ = "research_chunks"
    __table_args__ = (UniqueConstraint("document_id", "embedding_model", "chunk_key", name="uq_research_chunk_model_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    chunk_key: Mapped[str] = mapped_column(String(100))
    embedding_model: Mapped[str] = mapped_column(String(100), index=True)
    content: Mapped[str] = mapped_column(Text)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    vector: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
