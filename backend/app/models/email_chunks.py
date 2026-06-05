from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import Base


class EmailChunk(Base):
    """Child chunks of email bodies — parent-child retrieval path (Phase 2)."""

    __tablename__ = "email_chunks"

    chunk_id           = Column(String, primary_key=True)   # UUID
    email_content_hash = Column(String, ForeignKey("emails.email_content_hash"), nullable=False)
    chunk_index        = Column(Integer, nullable=False)     # 0-based position in email
    chunk_text         = Column(Text, nullable=False)        # ~200-350 token window
    chunk_embedding    = Column(Vector(1536))                # populated in Phase 2

    # Denormalised for pre-filtering without a join
    email_sent_dt      = Column(DateTime(timezone=True))
    email_subject      = Column(String)
    source_org         = Column(String)                      # inferred from key_points on same email

    email = relationship("Email", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunk_email_hash", "email_content_hash"),
        Index("ix_chunk_sent_dt",    "email_sent_dt"),
        Index("ix_chunk_source_org", "source_org"),
    )
